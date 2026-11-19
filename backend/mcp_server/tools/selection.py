"""Selection tools: ranking, diversity selection, Saved Sets, sequence extraction."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional

import polars as pl
from pydantic import Field

from .. import contacts, errors, refs, tables, vocab
from ..columns import canonical_expr, coverage
from ..descriptions import (
    EXTRACT_SEQUENCES,
    RANK_DESIGNS,
    SAVED_SETS,
    SELECT_DIVERSE_DESIGNS,
    TARGET_CONTACT_GROUPS_ARG,
)
from ..server import run_blocking

SEQUENCE_COLUMN = "Sequence"


def _prepare_metrics(
    df: pl.DataFrame, metrics: List[Dict[str, Any]]
) -> tuple:
    """Resolve every ranking metric, or fail.

    The REST engine skips a metric it cannot resolve and ranks on what is left, which
    produces a confident ranking that quietly ignored half the caller's criteria.
    """
    from ...filtering.schemas import RankingMetric

    resolved: List[RankingMetric] = []
    report: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for metric in metrics:
        name = str(metric.get("column"))
        direction = metric.get("higher_is_better")
        if direction is None:
            direction = vocab.higher_is_better(name)
            if direction is None:
                errors.fail(
                    errors.NO_RANKABLE_METRICS,
                    f"{name!r} is a raw column with no known sort direction. Pass "
                    "higher_is_better explicitly, or use a canonical metric from "
                    "describe_methods.",
                )
        covered = coverage(df, name)
        report.append(
            {
                "column": name,
                "higher_is_better": bool(direction),
                "weight": float(metric.get("weight", 1.0)),
                "designs_with_value": covered,
            }
        )
        if covered == 0:
            warnings.append(
                errors.warning(
                    errors.METRIC_NOT_APPLICABLE_FOR_METHOD,
                    f"No design in this selection has a value for {name!r}; it cannot "
                    "contribute to the ranking.",
                )
            )
            continue
        resolved.append(
            RankingMetric(
                column=name,
                weight=float(metric.get("weight", 1.0)),
                higher_is_better=bool(direction),
            )
        )

    if metrics and not resolved:
        errors.fail(
            errors.NO_RANKABLE_METRICS,
            "None of the requested metrics resolve to a column any design in this "
            f"selection has: {[m.get('column') for m in metrics]}. Call describe_columns "
            "with include_raw=true to see what is actually measured here.",
        )
    return resolved, report, warnings


def _rank(
    run_ids: List[str],
    filters: List[Dict[str, Any]],
    metrics: List[Dict[str, Any]],
    limit: int,
    columns: Optional[List[str]],
    target_contact_groups: Optional[List[Dict[str, Any]]] = None,
    ranking_mode: str = "worst_rank",
) -> Dict[str, Any]:
    from ...filtering.engine import apply_hard_filters, filter_cascade_counts, rank_designs
    from ...filtering.service import _pick_tiebreak_column

    refs.validate_run_ids(run_ids)
    inputs, warnings = contacts.build_inputs(run_ids, filters, target_contact_groups)
    df = inputs.df
    if df.is_empty():
        errors.fail(errors.EMPTY_SELECTION, f"No designs are loaded for {run_ids}.")

    specs = inputs.specs
    resolved, report, metric_warnings = _prepare_metrics(df, metrics)
    warnings.extend(metric_warnings)

    cascade = []
    for stage in filter_cascade_counts(df, specs) if specs else []:
        entry = stage.model_dump()
        # A __tc_* stage name means nothing to a reader; show the condition instead.
        entry["column"] = inputs.labels.get(entry["column"], entry["column"])
        cascade.append(entry)

    filtered = apply_hard_filters(df, specs)
    ranked = rank_designs(
        filtered,
        resolved,
        tiebreak_column=_pick_tiebreak_column(df),
        mode=ranking_mode,
    )
    passing = (
        int(ranked["pass_filters"].sum()) if "pass_filters" in ranked.columns else ranked.height
    )
    if specs and passing == 0:
        errors.fail(
            errors.EMPTY_SELECTION,
            f"No design passes every filter (of {df.height}). The cascade was {cascade}; "
            "relax the threshold on whichever stage dropped the most."
            + contacts.empty_selection_hint(target_contact_groups, warnings),
        )

    ranked = contacts.strip_virtual(ranked.sort("final_rank", nulls_last=True))
    selected = ["run_id", "design_id", "method", "final_rank", "quality_score", "pass_filters"]
    for name in columns or []:
        if canonical_expr(ranked, name) is None:
            errors.fail(
                errors.UNKNOWN_COLUMN,
                f"No column {name!r} in this selection. Nearest: "
                f"{errors.nearest(name, tables.visible_columns(ranked.columns))}.",
            )
        if name not in selected:
            ranked = ranked.with_columns(canonical_expr(ranked, name).alias(name))
            selected.append(name)
    selected = [c for c in selected if c in ranked.columns]

    tables.enforce_cell_budget(
        min(limit, ranked.height), len(selected), f"Lower limit below {limit}."
    )
    rows = ranked.head(limit).to_dicts()
    for row in rows:
        row.update(refs.decorate_structure_fields(row))

    return tables.build_table(
        rows,
        selected + ["structure_filename", "structure_url"],
        total_matching=ranked.height,
        warnings=warnings,
        extra={
            "metrics_resolved": report,
            "passing_filters": passing,
            "filter_cascade": cascade,
        },
    )


def _sequence_column(df: pl.DataFrame) -> Optional[str]:
    return SEQUENCE_COLUMN if SEQUENCE_COLUMN in df.columns else None


def _extract_for(rows: List[Dict[str, Any]]) -> int:
    """Extract sequences for designs that lack one. Returns how many succeeded."""
    from ...routers.designs import _sequences_extract_sync
    from ...schemas import SequenceExtractItem, SequenceExtractRequest

    items = []
    for row in rows:
        filename = refs.structure_filename(row)
        if not filename:
            continue
        items.append(
            SequenceExtractItem(
                run_id=str(row.get("run_id")),
                design_id=str(row.get("design_id")),
                pdb_file=filename,
                source_path=row.get("source_path"),
            )
        )
    if not items:
        return 0
    response = _sequences_extract_sync(SequenceExtractRequest(designs=items))
    return sum(1 for r in response.results if r.sequence)


def _diverse(
    run_ids: List[str],
    filters: List[Dict[str, Any]],
    metrics: List[Dict[str, Any]],
    budget: int,
    alpha: float,
    auto_extract_sequences: bool,
    save_as: Optional[str],
    columns: Optional[List[str]],
    target_contact_groups: Optional[List[Dict[str, Any]]] = None,
    ranking_mode: str = "worst_rank",
) -> Dict[str, Any]:
    from ...filtering.engine import count_missing_sequences, run_filtering_pipeline
    from ...filtering.schemas import FilterSpec, FilteringRunRequest, TargetContactGroup
    from ...filtering.service import _pick_tiebreak_column, run_filtering_and_save

    refs.validate_run_ids(run_ids)
    inputs, warnings = contacts.build_inputs(run_ids, filters, target_contact_groups)
    df = inputs.df
    if df.is_empty():
        errors.fail(errors.EMPTY_SELECTION, f"No designs are loaded for {run_ids}.")

    resolved, report, metric_warnings = _prepare_metrics(df, metrics)
    warnings.extend(metric_warnings)

    sequence_col = _sequence_column(df)
    if sequence_col is None or count_missing_sequences(df, sequence_col):
        if auto_extract_sequences:
            extracted = _extract_for(df.to_dicts())
            if extracted:
                warnings.append(
                    errors.warning(
                        errors.SEQUENCES_AUTO_EXTRACTED,
                        f"Extracted sequences from structures for {extracted} designs.",
                    )
                )
                inputs, extra_warnings = contacts.build_inputs(
                    run_ids, filters, target_contact_groups
                )
                df = inputs.df
                warnings.extend(extra_warnings)
                sequence_col = _sequence_column(df)
        if sequence_col is None:
            errors.fail(
                errors.SEQUENCES_REQUIRED,
                "Diversity selection needs sequences and these runs have none. Re-call "
                "with auto_extract_sequences=true, or call extract_sequences first.",
            )

    if save_as:
        request = FilteringRunRequest(
            name=save_as,
            run_ids=run_ids,
            filters=[FilterSpec(**f) for f in filters],
            target_contact_groups=[
                TargetContactGroup(**g) for g in (target_contact_groups or [])
            ],
            metrics=resolved,
            ranking_mode=ranking_mode,
            budget=budget,
            alpha=alpha,
        )
        saved = run_filtering_and_save(request)
        warnings.extend(
            errors.warning(errors.SEQUENCES_MISSING, message) for message in saved.warnings
        )
        table = _saved_set_designs(saved.saved_set_id, True, budget, 0, columns)
        table["saved_set_id"] = saved.saved_set_id
        table["saved_set_name"] = saved.name
        table["warnings"] = list(table.get("warnings") or []) + warnings
        table["metrics_resolved"] = report
        return table

    ranked, diverse = run_filtering_pipeline(
        df,
        inputs.specs,
        resolved,
        budget=budget,
        alpha=alpha,
        sequence_col=sequence_col,
        tiebreak_column=_pick_tiebreak_column(df),
        ranking_mode=ranking_mode,
    )
    if diverse is None or diverse.is_empty():
        missing = count_missing_sequences(ranked, sequence_col)
        if missing == 0 and target_contact_groups:
            errors.fail(
                errors.EMPTY_SELECTION,
                "No design passes the filters, so there is nothing to select from."
                + contacts.empty_selection_hint(target_contact_groups, warnings),
            )
        errors.fail(
            errors.SEQUENCES_REQUIRED,
            f"Diversity selection produced no designs: {missing} of {ranked.height} have "
            "no usable sequence. Re-call with auto_extract_sequences=true.",
        )
    diverse = contacts.strip_virtual(diverse)
    if diverse.height < budget:
        warnings.append(
            errors.warning(
                errors.RESULT_SMALLER_THAN_BUDGET,
                f"Selected {diverse.height} designs for a budget of {budget}; only that "
                "many passed the filters with a usable sequence.",
                {"missing_sequences": count_missing_sequences(ranked, sequence_col)},
            )
        )

    selected = ["run_id", "design_id", "method", "final_rank", "quality_score"]
    for name in columns or []:
        expr = canonical_expr(diverse, name)
        if expr is None:
            errors.fail(
                errors.UNKNOWN_COLUMN,
                f"No column {name!r} in this selection. Nearest: "
                f"{errors.nearest(name, tables.visible_columns(diverse.columns))}.",
            )
        if name not in selected:
            diverse = diverse.with_columns(expr.alias(name))
            selected.append(name)
    selected = [c for c in selected if c in diverse.columns]

    rows = diverse.sort("final_rank", nulls_last=True).to_dicts()
    for row in rows:
        row.update(refs.decorate_structure_fields(row))
    return tables.build_table(
        rows,
        selected + ["structure_filename", "structure_url"],
        total_matching=diverse.height,
        warnings=warnings,
        extra={"metrics_resolved": report, "budget": budget, "alpha": alpha},
    )


def _saved_set_designs(
    saved_set_id: str,
    in_diverse_set_only: bool,
    limit: int,
    offset: int,
    columns: Optional[List[str]],
) -> Dict[str, Any]:
    from ...filtering.service import get_saved_set_designs

    payload = get_saved_set_designs(saved_set_id)
    if payload is None:
        errors.fail(
            errors.DESIGN_NOT_FOUND,
            f"No saved set {saved_set_id!r}. Call saved_sets(action='list').",
        )

    rows = [d.model_dump() for d in payload.designs]
    total_all = len(rows)
    if in_diverse_set_only:
        rows = [r for r in rows if r.get("in_diverse_set")]

    flattened: List[Dict[str, Any]] = []
    for row in rows:
        metrics = row.pop("metrics", None) or {}
        merged = {**metrics, **row}
        merged.update(refs.decorate_structure_fields(merged))
        flattened.append(merged)

    selected = ["run_id", "design_id", "final_rank", "quality_score", "in_diverse_set"]
    for name in columns or []:
        if name not in selected:
            selected.append(name)
    selected += ["structure_filename", "structure_url"]

    total = len(flattened)
    tables.enforce_cell_budget(
        min(limit, max(0, total - offset)),
        len(selected),
        f"Lower limit below {limit}, or page with offset.",
    )
    return tables.build_table(
        flattened[offset : offset + limit],
        selected,
        total_matching=total,
        offset=offset,
        warnings=[]
        if in_diverse_set_only
        else [
            errors.warning(
                errors.TRUNCATED,
                f"This is the full ranked pool ({total_all} designs), not just the "
                "selected panel. Pass in_diverse_set_only=true for the panel.",
            )
        ],
        extra={
            "saved_set_id": saved_set_id,
            "in_diverse_set_only": in_diverse_set_only,
            "ranked_pool_size": total_all,
        },
    )


def _create_saved_set(name: Optional[str], designs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from ...filtering.service import MAX_SAVED_SET_DESIGNS, create_saved_set_from_designs
    from ...persistence.factory import get_designs_repository

    trimmed = (name or "").strip()
    if not trimmed:
        errors.fail(
            errors.INVALID_SAVED_SET_REQUEST,
            "action='create' needs a non-empty name.",
        )
    if not designs:
        errors.fail(
            errors.INVALID_SAVED_SET_REQUEST,
            "action='create' needs designs: a list of {run_id, design_id}. "
            "Call query_designs or rank_designs first.",
        )
    if len(designs) > MAX_SAVED_SET_DESIGNS:
        errors.fail(
            errors.INVALID_SAVED_SET_REQUEST,
            f"action='create' accepts at most {MAX_SAVED_SET_DESIGNS} designs; "
            f"got {len(designs)}. Split into multiple saved sets or narrow the selection.",
        )

    repo = get_designs_repository()
    if not repo.is_enabled():
        errors.fail(
            errors.PERSISTENCE_REQUIRED,
            "Saved Sets need DATABASE persistence. Set DATABASE in .env.",
        )

    resolved: List[Dict[str, Any]] = []
    run_ids: List[str] = []
    for index, ref in enumerate(designs):
        run_id = str(ref.get("run_id") or "").strip()
        design_id = str(ref.get("design_id") or "").strip()
        if not run_id or not design_id:
            errors.fail(
                errors.INVALID_SAVED_SET_REQUEST,
                f"designs[{index}] needs run_id and design_id. "
                "Call query_designs for valid keys.",
            )
        run_ids.append(run_id)
        resolved.append(
            {
                "run_id": run_id,
                "design_id": design_id,
                "source_path": ref.get("source_path"),
            }
        )
    refs.validate_run_ids(list(dict.fromkeys(run_ids)))
    rows = [
        refs.resolve_design(item["run_id"], item["design_id"], item.get("source_path"))
        for item in resolved
    ]

    saved = create_saved_set_from_designs(trimmed, rows)
    return {
        "saved_set_id": saved.saved_set_id,
        "name": saved.name,
        "design_count": saved.diverse_set_count,
        "source_run_ids": list(dict.fromkeys(str(r.get("run_id")) for r in rows)),
    }


def _saved_sets(
    action: str,
    saved_set_id: Optional[str],
    name: Optional[str],
    in_diverse_set_only: bool,
    limit: int,
    offset: int,
    columns: Optional[List[str]],
    designs: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    from ...filtering.service import list_saved_sets, rename_saved_set

    if action == "list":
        listing = list_saved_sets()
        return {
            "saved_sets": [s.model_dump(mode="json") for s in listing.saved_sets],
            "total": len(listing.saved_sets),
        }

    if action == "create":
        return _create_saved_set(name, designs or [])

    if not saved_set_id:
        errors.fail(
            errors.DESIGN_NOT_FOUND,
            f"action={action!r} needs saved_set_id. Call saved_sets(action='list') first.",
        )

    if action == "rename":
        if not name:
            errors.fail(errors.DESIGN_NOT_FOUND, "action='rename' needs a new name.")
        if not rename_saved_set(saved_set_id, name):
            errors.fail(errors.DESIGN_NOT_FOUND, f"No saved set {saved_set_id!r}.")
        return {"saved_set_id": saved_set_id, "name": name, "renamed": True}

    return _saved_set_designs(saved_set_id, in_diverse_set_only, limit, offset, columns)


def _extract(run_ids: List[str], limit: int) -> Dict[str, Any]:
    from ...cache import refresh_designs_cache
    from ...filtering.service import build_designs_dataframe

    refs.validate_run_ids(run_ids)
    df = build_designs_dataframe(run_ids)
    if df.is_empty():
        errors.fail(errors.EMPTY_SELECTION, f"No designs are loaded for {run_ids}.")

    sequence_col = _sequence_column(df)
    if sequence_col:
        from ...filtering.engine import has_usable_sequence

        pending = df.filter(~has_usable_sequence(sequence_col))
    else:
        pending = df

    rows = pending.head(limit).to_dicts()
    extracted = _extract_for(rows)
    refresh_designs_cache()
    return {
        "run_ids": run_ids,
        "designs_missing_sequences": pending.height,
        "attempted": len(rows),
        "extracted": extracted,
        "warnings": []
        if len(rows) >= pending.height
        else [
            errors.warning(
                errors.TRUNCATED,
                f"{pending.height - len(rows)} designs still have no sequence; call again.",
            )
        ],
    }


def register(mcp: Any) -> None:
    @mcp.tool(description=RANK_DESIGNS)
    async def rank_designs(
        run_ids: Annotated[List[str], Field(description="Runs to rank across.")],
        metrics: Annotated[
            List[Dict[str, Any]],
            Field(
                description=(
                    "Ranking metrics, each {column, weight, higher_is_better}. Omit "
                    "higher_is_better for a canonical metric to use its known direction."
                )
            ),
        ],
        filters: Annotated[
            Optional[List[Dict[str, Any]]],
            Field(description="Optional hard filters, as in query_designs."),
        ] = None,
        columns: Annotated[
            Optional[List[str]], Field(description="Extra metric columns to return.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Top N to return.")] = 25,
        ranking_mode: Annotated[
            Literal["worst_rank", "simple"],
            Field(
                description=(
                    "worst_rank: BoltzGen worst scaled rank (weight is inverse importance). "
                    "simple: lexicographic, metrics in list order. Default worst_rank."
                )
            ),
        ] = "worst_rank",
        target_contact_groups: Annotated[
            Optional[List[Dict[str, Any]]],
            Field(description=TARGET_CONTACT_GROUPS_ARG),
        ] = None,
    ) -> Dict[str, Any]:
        return await run_blocking(
            _rank,
            run_ids,
            filters or [],
            metrics,
            limit,
            columns,
            target_contact_groups,
            ranking_mode,
            heavy=True,
        )

    @mcp.tool(description=SELECT_DIVERSE_DESIGNS)
    async def select_diverse_designs(
        run_ids: Annotated[List[str], Field(description="Runs to select from.")],
        metrics: Annotated[
            List[Dict[str, Any]],
            Field(description="Ranking metrics, as in rank_designs."),
        ],
        filters: Annotated[
            Optional[List[Dict[str, Any]]], Field(description="Optional hard filters.")
        ] = None,
        budget: Annotated[int, Field(ge=1, le=200, description="Panel size to select.")] = 24,
        alpha: Annotated[
            float,
            Field(
                ge=0.0,
                le=1.0,
                description="Diversity weight. 0 is quality only; 1 is diversity only.",
            ),
        ] = 0.0,
        auto_extract_sequences: Annotated[
            bool, Field(description="Extract missing sequences from structures first (slow).")
        ] = False,
        save_as: Annotated[
            Optional[str],
            Field(description="Persist as a Saved Set with this name, visible in the web UI."),
        ] = None,
        columns: Annotated[
            Optional[List[str]], Field(description="Extra metric columns to return.")
        ] = None,
        ranking_mode: Annotated[
            Literal["worst_rank", "simple"],
            Field(description="As in rank_designs. Default worst_rank."),
        ] = "worst_rank",
        target_contact_groups: Annotated[
            Optional[List[Dict[str, Any]]],
            Field(description=TARGET_CONTACT_GROUPS_ARG),
        ] = None,
    ) -> Dict[str, Any]:
        return await run_blocking(
            _diverse,
            run_ids,
            filters or [],
            metrics,
            budget,
            alpha,
            auto_extract_sequences,
            save_as,
            columns,
            target_contact_groups,
            ranking_mode,
            heavy=True,
        )

    @mcp.tool(description=SAVED_SETS)
    async def saved_sets(
        action: Annotated[
            Literal["list", "get", "rename", "create"], Field(description="What to do.")
        ] = "list",
        saved_set_id: Annotated[
            Optional[str], Field(description="Required for get and rename.")
        ] = None,
        name: Annotated[
            Optional[str],
            Field(description="New name for rename, or the set name for create."),
        ] = None,
        designs: Annotated[
            Optional[List[Dict[str, Any]]],
            Field(
                description=(
                    "For create: designs to persist, each {run_id, design_id, source_path?}."
                )
            ),
        ] = None,
        in_diverse_set_only: Annotated[
            bool, Field(description="Return only the selected panel, not the ranked pool.")
        ] = True,
        columns: Annotated[
            Optional[List[str]], Field(description="Extra metric columns to return.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=200, description="Rows to return.")] = 25,
        offset: Annotated[int, Field(ge=0, description="Rows to skip.")] = 0,
    ) -> Dict[str, Any]:
        return await run_blocking(
            _saved_sets,
            action,
            saved_set_id,
            name,
            in_diverse_set_only,
            limit,
            offset,
            columns,
            designs,
        )

    @mcp.tool(description=EXTRACT_SEQUENCES)
    async def extract_sequences(
        run_ids: Annotated[List[str], Field(description="Runs whose designs need sequences.")],
        limit: Annotated[
            int, Field(ge=1, le=2000, description="Maximum designs to process in this call.")
        ] = 500,
    ) -> Dict[str, Any]:
        return await run_blocking(_extract, run_ids, limit, heavy=True)
