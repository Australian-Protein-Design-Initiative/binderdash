"""The design table: query_designs and summarize_designs."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional

import polars as pl
from pydantic import Field

from .. import contacts, errors, refs, tables, vocab
from ..columns import canonical_expr
from ..descriptions import (
    MERGE_DESIGN_COLUMNS,
    QUERY_DESIGNS,
    SUMMARIZE_DESIGNS,
    TARGET_CONTACT_GROUPS_ARG,
)
from ..server import run_blocking

# Identity columns worth having on every row; anything else must be asked for.
BASE_COLUMNS = ["run_id", "design_id", "method"]
DEFAULT_EXTRA_COLUMNS = ["iptm", "pae_interaction", "rmsd"]

PRIMARY_SCORE = "primary_score"
DEFAULT_SORT = "default"
_SORT_KEY = "__binderdash_sort_key"
_SORT_KEY_2 = "__binderdash_sort_key_2"
MERGE_TABLE_MAX_BYTES = 1_048_576


def _default_sort(df: pl.DataFrame, warnings: List[Dict[str, Any]]) -> Optional[pl.DataFrame]:
    """Best designs first: iptm descending, then pae_interaction ascending.

    Both are canonical, so they resolve to whichever raw column each method uses, and a
    mixed-method table orders sensibly from one call. The second key is not a tiebreak
    for the first -- it orders the designs that have no iptm at all (rfd runs that were
    never re-scored), which would otherwise land in an arbitrary order at the end.
    """
    iptm = canonical_expr(df, "iptm")
    pae = canonical_expr(df, "pae_interaction")
    if iptm is None and pae is None:
        return None
    if iptm is None:
        warnings.append(
            errors.warning(
                errors.METRIC_NOT_APPLICABLE_FOR_METHOD,
                "No design here reports iptm; sorted by pae_interaction ascending instead.",
            )
        )
    return df.with_columns(
        [
            (-iptm.cast(pl.Float64, strict=False)).alias(_SORT_KEY)
            if iptm is not None
            else pl.lit(None, dtype=pl.Float64).alias(_SORT_KEY),
            pae.cast(pl.Float64, strict=False).alias(_SORT_KEY_2)
            if pae is not None
            else pl.lit(None, dtype=pl.Float64).alias(_SORT_KEY_2),
        ]
    ).sort([_SORT_KEY, _SORT_KEY_2], descending=False, nulls_last=True)


def _resolve_sort(
    df: pl.DataFrame, name: str, order: str, warnings: List[Dict[str, Any]]
) -> tuple:
    """(expression, descending) for sorting, with the direction trap made loud."""
    expr = canonical_expr(df, name)
    if expr is None:
        errors.fail(
            errors.UNKNOWN_COLUMN,
            f"No column {name!r} in this selection. Nearest: "
            f"{errors.nearest(name, tables.visible_columns(df.columns))}. Call "
            "describe_columns for the full list, or describe_methods for canonical names.",
        )

    known = vocab.higher_is_better(name)
    if order == "auto":
        if known is None:
            warnings.append(
                errors.warning(
                    errors.SORT_DIRECTION_OVERRIDE,
                    f"{name!r} is a raw column with no known direction; sorted descending. "
                    "Pass order='asc' if lower is better for this metric.",
                )
            )
            return expr, True
        return expr, known

    descending = order == "desc"
    if known is not None and descending != known:
        better = "higher" if known else "lower"
        warnings.append(
            errors.warning(
                errors.SORT_DIRECTION_OVERRIDE,
                f"For {name!r}, {better} is better, but you asked for order={order!r}: "
                "the worst designs are now first.",
            )
        )
    return expr, descending


def _primary_score_sort(df: pl.DataFrame) -> Optional[pl.DataFrame]:
    """Sort each design by its own method's primary score, in that method's direction.

    A mixed-method selection has no single score column. Negating the higher-is-better
    methods puts every row on one "smaller is better" scale, so one ascending sort
    orders them all sensibly and scoreless rows land last.
    """
    if "method" not in df.columns:
        return None
    keys: List[pl.Expr] = []
    for method in df["method"].unique().to_list():
        config = vocab.primary_score_for_method(str(method))
        if not config:
            continue
        for column in config["columns"]:
            if column not in df.columns:
                continue
            value = pl.col(column).cast(pl.Float64, strict=False)
            keys.append(
                pl.when(pl.col("method").cast(pl.Utf8) == str(method))
                .then(-value if config["higher_is_better"] else value)
                .otherwise(None)
            )
            break
    if not keys:
        return None
    return df.with_columns(pl.coalesce(keys).alias(_SORT_KEY)).sort(
        _SORT_KEY, descending=False, nulls_last=True
    )


def _select_columns(
    df: pl.DataFrame, columns: Optional[List[str]], include_sequence: bool
) -> List[str]:
    available = tables.visible_columns(df.columns)
    if columns:
        chosen: List[str] = []
        for name in columns:
            if canonical_expr(df, name) is None:
                errors.fail(
                    errors.UNKNOWN_COLUMN,
                    f"No column {name!r} in this selection. Nearest: "
                    f"{errors.nearest(name, available)}. Call describe_columns for the "
                    "full list.",
                )
            chosen.append(name)
    else:
        chosen = [c for c in DEFAULT_EXTRA_COLUMNS if canonical_expr(df, c) is not None]

    out = [c for c in BASE_COLUMNS if c in df.columns]
    for name in chosen:
        if name not in out:
            out.append(name)
    if include_sequence and "Sequence" in df.columns and "Sequence" not in out:
        out.append("Sequence")
    return out + ["structure_filename", "structure_url"]


def _materialise(df: pl.DataFrame, columns: List[str]) -> pl.DataFrame:
    """Resolve each requested column into a real column of that name.

    Overwrites a same-named raw column rather than skipping it: for a canonical metric
    the resolved expression is the correct value for every method, and the raw column is
    correct for only one of them.
    """
    additions = []
    for name in columns:
        if name in ("structure_filename", "structure_url"):
            continue
        expr = canonical_expr(df, name)
        if expr is not None:
            additions.append(expr.alias(name))
    return df.with_columns(additions) if additions else df


def _query(
    run_ids: List[str],
    filters: List[Dict[str, Any]],
    columns: Optional[List[str]],
    sort: str,
    order: str,
    limit: int,
    offset: int,
    include_sequence: bool,
    target_contact_groups: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    from ...filtering.engine import apply_hard_filters

    refs.validate_run_ids(run_ids)
    inputs, warnings = contacts.build_inputs(run_ids, filters, target_contact_groups)
    df = inputs.df
    if df.is_empty():
        errors.fail(
            errors.EMPTY_SELECTION,
            f"No designs are loaded for {run_ids}. Check the run_ids with list_runs.",
        )

    for run_id in run_ids:
        if refs.is_merged_run(run_id):
            warnings.append(
                errors.warning(
                    errors.MERGED_RUN,
                    f"Run {run_id} merges several folders, so design_id can repeat. Use "
                    "source_path to identify a specific design.",
                )
            )

    total_before = df.height
    if inputs.specs:
        annotated = apply_hard_filters(df, inputs.specs)
        drop = [
            c
            for c in annotated.columns
            if c.startswith("pass_") or c == "num_filters_passed" or c == "pass_filters"
        ]
        df = contacts.strip_virtual(
            annotated.filter(pl.col("pass_filters")).drop(drop, strict=False)
        )
        if df.is_empty():
            errors.fail(
                errors.EMPTY_SELECTION,
                f"All {total_before} designs failed the filters. Call summarize_designs on "
                "these columns to see the real value ranges, then relax the thresholds."
                + contacts.empty_selection_hint(target_contact_groups, warnings),
            )
    else:
        df = contacts.strip_virtual(df)

    if sort in (DEFAULT_SORT, PRIMARY_SCORE):
        sorted_df = (
            _default_sort(df, warnings) if sort == DEFAULT_SORT else _primary_score_sort(df)
        )
        if sorted_df is None:
            warnings.append(
                errors.warning(
                    errors.SORT_DIRECTION_OVERRIDE,
                    f"Cannot sort by {sort!r} for these methods, so rows are unsorted. "
                    "Pass an explicit sort column.",
                )
            )
        else:
            df = sorted_df
    else:
        expr, descending = _resolve_sort(df, sort, order, warnings)
        df = df.with_columns(expr.alias(_SORT_KEY)).sort(
            _SORT_KEY, descending=descending, nulls_last=True
        )

    total_matching = df.height
    selected = _select_columns(df, columns, include_sequence)
    tables.enforce_cell_budget(
        min(limit, max(0, total_matching - offset)),
        len(selected),
        f"Ask for fewer columns (currently {len(selected)}) or a smaller limit "
        f"(currently {limit}), or call summarize_designs instead.",
    )

    rows = _materialise(df.slice(offset, limit), selected).to_dicts()
    for row in rows:
        row.update(refs.decorate_structure_fields(row))

    methods = {}
    if "method" in df.columns:
        for method in df["method"].unique().to_list():
            config = vocab.primary_score_for_method(str(method))
            if config:
                methods[str(method)] = config

    return tables.build_table(
        rows,
        selected,
        total_matching=total_matching,
        offset=offset,
        methods=methods,
        warnings=warnings,
        extra={"total_before_filters": total_before, "sorted_by": sort},
    )


def _histogram(series: pl.Series, bins: int) -> Dict[str, Any]:
    low, high = float(series.min()), float(series.max())  # type: ignore[arg-type]
    if low == high:
        return {"edges": [tables.clean_cell(low), tables.clean_cell(high)], "counts": [series.len()]}
    width = (high - low) / bins
    counts = [0] * bins
    for value in series.to_list():
        counts[min(int((value - low) / width), bins - 1)] += 1
    return {
        "edges": [tables.clean_cell(low + i * width) for i in range(bins + 1)],
        "counts": counts,
    }


def _summarize(
    run_ids: List[str], columns: List[str], group_by: Optional[str], histogram_bins: int
) -> Dict[str, Any]:
    from ...filtering.service import build_designs_dataframe

    refs.validate_run_ids(run_ids)
    df = build_designs_dataframe(run_ids)
    if df.is_empty():
        errors.fail(errors.EMPTY_SELECTION, f"No designs are loaded for {run_ids}.")

    if group_by and group_by not in df.columns:
        errors.fail(
            errors.UNKNOWN_COLUMN,
            f"Cannot group by {group_by!r}. Nearest: "
            f"{errors.nearest(group_by, list(df.columns))}.",
        )

    resolved: Dict[str, pl.Expr] = {}
    for name in columns:
        expr = canonical_expr(df, name)
        if expr is None:
            errors.fail(
                errors.UNKNOWN_COLUMN,
                f"No column {name!r} in this selection. Nearest: "
                f"{errors.nearest(name, tables.visible_columns(df.columns))}.",
            )
        resolved[name] = expr.cast(pl.Float64, strict=False)

    warnings: List[Dict[str, Any]] = []
    groups: List[tuple] = [(None, df)]
    if group_by:
        values = df[group_by].unique().to_list()
        if len(values) > 40:
            warnings.append(
                errors.warning(
                    errors.TRUNCATED,
                    f"{group_by!r} has {len(values)} distinct values; summarised the first 40.",
                )
            )
            values = values[:40]
        groups = [(v, df.filter(pl.col(group_by) == v)) for v in values]

    out: List[Dict[str, Any]] = []
    for value, frame in groups:
        stats: Dict[str, Any] = {"group": value, "n_designs": frame.height, "columns": {}}
        for name, expr in resolved.items():
            series = frame.select(expr.alias("v"))["v"].drop_nulls()
            if series.len() == 0:
                stats["columns"][name] = {"coverage": 0}
                warnings.append(
                    errors.warning(
                        errors.METRIC_NOT_APPLICABLE_FOR_METHOD,
                        f"No design in group {value!r} has a value for {name!r}.",
                    )
                )
                continue
            entry: Dict[str, Any] = {
                "coverage": series.len(),
                "min": tables.clean_cell(float(series.min())),  # type: ignore[arg-type]
                "q1": tables.clean_cell(series.quantile(0.25)),
                "median": tables.clean_cell(series.median()),
                "q3": tables.clean_cell(series.quantile(0.75)),
                "max": tables.clean_cell(float(series.max())),  # type: ignore[arg-type]
                "mean": tables.clean_cell(series.mean()),
                "higher_is_better": vocab.higher_is_better(name),
            }
            if histogram_bins:
                entry["histogram"] = _histogram(series, histogram_bins)
            stats["columns"][name] = entry
        out.append(stats)

    return {
        "run_ids": run_ids,
        "total_designs": df.height,
        "group_by": group_by,
        "groups": out,
        "warnings": warnings,
    }


def _merge_columns(
    run_ids: List[str],
    table: str,
    fmt: str,
    design_id_column: Optional[str],
    preview: bool,
) -> Dict[str, Any]:
    from ...cache import refresh_designs_cache
    from ...design_merge import apply_merge_table_upload
    from ...persistence.factory import get_designs_repository

    refs.validate_run_ids(run_ids)
    if not table or not str(table).strip():
        errors.fail(
            errors.INVALID_MERGE_TABLE,
            "table is empty. Pass TSV or CSV text including a header row with a "
            "design_id column.",
        )
    encoded = table.encode("utf-8")
    if len(encoded) > MERGE_TABLE_MAX_BYTES:
        errors.fail(
            errors.FILE_TOO_LARGE,
            f"table is {len(encoded)} bytes; the maximum is {MERGE_TABLE_MAX_BYTES}. "
            "Split the upload or drop unused columns.",
        )

    repo = get_designs_repository()
    if not repo.is_enabled():
        errors.fail(
            errors.PERSISTENCE_REQUIRED,
            "Merging columns needs DATABASE persistence. Set DATABASE in .env.",
        )

    filename = "upload.csv" if fmt == "csv" else "upload.tsv"
    try:
        result = apply_merge_table_upload(
            encoded,
            filename,
            run_ids,
            design_id_column=design_id_column,
            preview=preview,
        )
    except ValueError as exc:
        errors.fail(
            errors.INVALID_MERGE_TABLE,
            f"{exc}. Check the header row and design_id_column.",
        )
    if not preview:
        refresh_designs_cache()
    return result


def register(mcp: Any) -> None:
    @mcp.tool(description=QUERY_DESIGNS)
    async def query_designs(
        run_ids: Annotated[List[str], Field(description="Runs to query, from list_runs.")],
        filters: Annotated[
            Optional[List[Dict[str, Any]]],
            Field(
                description=(
                    "Hard filters, each {column, operator, threshold|text_value}. Numeric "
                    "operators: <, <=, >, >=. String: contains, not_contains, starts_with, "
                    "ends_with, equals, not_equals, regex."
                )
            ),
        ] = None,
        columns: Annotated[
            Optional[List[str]],
            Field(description="Columns to return. Canonical names resolve per method."),
        ] = None,
        sort: Annotated[
            str,
            Field(
                description=(
                    "Column to sort by; 'default' is iptm descending then pae_interaction "
                    "ascending, and 'primary_score' uses each method's own primary score "
                    "in its own direction."
                )
            ),
        ] = DEFAULT_SORT,
        order: Annotated[
            Literal["auto", "asc", "desc"],
            Field(description="'auto' applies the metric's known direction."),
        ] = "auto",
        limit: Annotated[int, Field(ge=1, le=200, description="Rows to return.")] = 25,
        offset: Annotated[int, Field(ge=0, description="Rows to skip, for paging.")] = 0,
        include_sequence: Annotated[
            bool, Field(description="Include the amino-acid sequence (large; caps limit at 100).")
        ] = False,
        target_contact_groups: Annotated[
            Optional[List[Dict[str, Any]]],
            Field(description=TARGET_CONTACT_GROUPS_ARG),
        ] = None,
    ) -> Dict[str, Any]:
        return await run_blocking(
            _query,
            run_ids,
            filters or [],
            columns,
            sort,
            order,
            min(limit, 100) if include_sequence else limit,
            offset,
            include_sequence,
            target_contact_groups,
            heavy=True,
        )

    @mcp.tool(description=SUMMARIZE_DESIGNS)
    async def summarize_designs(
        run_ids: Annotated[List[str], Field(description="Runs to summarise.")],
        columns: Annotated[
            List[str], Field(max_length=6, description="Up to 6 numeric columns.")
        ],
        group_by: Annotated[
            Optional[str],
            Field(description="Column to group by, e.g. 'run_id' or 'method'. Max 40 groups."),
        ] = None,
        histogram_bins: Annotated[
            int, Field(ge=0, le=20, description="Histogram bins per column; 0 for none.")
        ] = 0,
    ) -> Dict[str, Any]:
        return await run_blocking(
            _summarize, run_ids, columns, group_by, histogram_bins, heavy=True
        )

    @mcp.tool(description=MERGE_DESIGN_COLUMNS)
    async def merge_design_columns(
        run_ids: Annotated[
            List[str], Field(description="Runs whose designs to annotate.")
        ],
        table: Annotated[
            str,
            Field(description="Full TSV or CSV text, including a header row."),
        ],
        format: Annotated[
            Literal["tsv", "csv"],
            Field(description="How to parse `table`. Default tsv."),
        ] = "tsv",
        design_id_column: Annotated[
            Optional[str],
            Field(description="Column that identifies designs; defaults to design_id."),
        ] = None,
        preview: Annotated[
            bool,
            Field(description="If true, report matches without writing."),
        ] = False,
    ) -> Dict[str, Any]:
        return await run_blocking(
            _merge_columns, run_ids, table, format, design_id_column, preview
        )
