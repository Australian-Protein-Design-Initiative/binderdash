"""Orchestration layer wiring the filtering engine to BinderDash's design cache and
Saved Sets persistence. Keeps ``routers/filtering.py`` and ``routers/saved_sets.py``
thin — they just deserialize the request and hand off to a sync function here (run via
``asyncio.to_thread``, matching the rest of the designs router).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

import polars as pl

from ..cache import get_designs_for_run_ids
from ..persistence.factory import get_designs_repository
from .engine import (
    apply_hard_filters,
    count_missing_sequences,
    filter_cascade_counts,
    keep_best_mpnn_per_backbone,
    rank_designs,
    run_filtering_pipeline,
)
from .metrics import (
    RAW_TO_CANONICAL,
    available_columns_for_methods,
    higher_is_better,
    is_excluded_metric_column,
)
from .target_contacts_service import augment_with_target_contacts
from .schemas import (
    USER_ANNOTATION_COLUMNS,
    ColumnInfo,
    DesignKey,
    DiverseDesignRow,
    FilteringApplyRequest,
    FilteringApplyResponse,
    FilteringDiversityRequest,
    FilteringDiversityResponse,
    FilteringPreviewRequest,
    FilteringPreviewResponse,
    FilteringRankRequest,
    FilteringRankResponse,
    FilteringRunRequest,
    FilteringRunResponse,
    FilterSpec,
    RankedDesignRow,
    SavedSet,
    SavedSetDesignRow,
    SavedSetDesignsResponse,
    SavedSetListResponse,
    TargetContactGroup,
)

# Identity/text columns exposed to the Hard Filters column picker alongside numeric
# metrics, so string-match/regex filters (e.g. run_name contains "..."), which the
# engine already supports for any column (see engine._STRING_OPS), can replace the
# Designs tab's old client-side quick-filter panel for these fields.
_STRING_FILTER_COLUMNS = ["design_id", "project_id", "run_name", "method", "Sequence"]


def build_designs_dataframe(run_ids: List[str]) -> pl.DataFrame:
    """Aggregate DataFrame for the given runs, from the in-memory designs cache (loads
    on demand for runs not already cached). Empty DataFrame if no designs found.

    Design dicts are heterogeneous (method-dependent columns; see CLAUDE.md) — polars
    infers a union schema across the row dicts and fills missing keys with null,
    matching pandas' prior behaviour here.
    """
    rows = get_designs_for_run_ids(run_ids)
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, infer_schema_length=None)



@dataclass
class FilterInputs:
    """The designs DataFrame plus the full filter list for a request.

    Target-contact conditions are evaluated into boolean ``__tc_*`` columns here (see
    target_contacts_service.augment_with_target_contacts) and appended to the ordinary
    hard filters, so everything downstream — cascade counts, ranking, diversity
    selection, Saved Sets, and the MCP tools — treats them as plain filters.
    """

    df: pl.DataFrame
    specs: List[FilterSpec]
    labels: Dict[str, str] = dc_field(default_factory=dict)
    warnings: List[str] = dc_field(default_factory=list)


def build_filter_inputs(
    run_ids: List[str],
    filters: List[FilterSpec],
    target_contact_groups: Optional[List[TargetContactGroup]] = None,
) -> FilterInputs:
    df = build_designs_dataframe(run_ids)
    if df.is_empty() or not target_contact_groups:
        return FilterInputs(df=df, specs=list(filters))
    df, contact_specs, labels, warnings = augment_with_target_contacts(
        df, target_contact_groups, run_ids
    )
    return FilterInputs(
        df=df, specs=[*filters, *contact_specs], labels=labels, warnings=warnings
    )


def _sample_values(series: pl.Series) -> Optional[Dict[str, float]]:
    series = series.drop_nulls()
    if series.len() == 0:
        return None
    return {
        "min": float(series.min()),  # type: ignore[arg-type]
        "max": float(series.max()),  # type: ignore[arg-type]
        "mean": float(series.mean()),  # type: ignore[arg-type]
        "median": float(series.median()),  # type: ignore[arg-type]
    }


def compute_available_columns(run_ids: List[str]) -> List[ColumnInfo]:
    df = build_designs_dataframe(run_ids)
    if df.is_empty():
        return []

    by_method = available_columns_for_methods(df) if "method" in df.columns else {}
    if by_method:
        all_numeric_cols = sorted({c for cols in by_method.values() for c in cols})
    else:
        all_numeric_cols = sorted(c for c, dt in zip(df.columns, df.dtypes) if dt.is_numeric())
    all_numeric_cols = [
        c
        for c in all_numeric_cols
        if not is_excluded_metric_column(c) and c not in USER_ANNOTATION_COLUMNS
    ]

    # Raw per-method columns that share a canonical concept (e.g. rfd's pae_interaction
    # and bindcraft's Average_i_pAE) are collapsed into a single entry named after the
    # canonical concept — the engine resolves that name per-row by method (see
    # engine._resolve_canonical), so one picker entry is enough to filter/rank across an
    # aggregate of runs from different methods, instead of the user having to know to
    # pick a method-specific raw column that silently excludes every other method.
    canonical_groups: Dict[str, List[str]] = {}
    standalone_cols: List[str] = []
    for col in all_numeric_cols:
        canonical = RAW_TO_CANONICAL.get(col)
        if canonical:
            canonical_groups.setdefault(canonical, []).append(col)
        else:
            standalone_cols.append(col)

    columns: List[ColumnInfo] = []
    for canonical, raw_cols in canonical_groups.items():
        present_in_runs = sorted(
            {str(m) for m, cols in by_method.items() if any(c in cols for c in raw_cols)}
        )
        raw_col_set = set(raw_cols)
        raw_columns_by_method = {
            str(m): c
            for m, cols in by_method.items()
            for c in raw_col_set
            if c in cols
        }
        combined = pl.concat([df[c].drop_nulls().cast(pl.Float64) for c in raw_cols])
        columns.append(
            ColumnInfo(
                name=canonical,
                canonical_name=canonical,
                present_in_runs=present_in_runs,
                dtype="f64",
                sample_values=_sample_values(combined),
                raw_columns=raw_columns_by_method,
                higher_is_better=higher_is_better(canonical),
            )
        )

    for col in standalone_cols:
        present_in_runs = sorted(str(m) for m, cols in by_method.items() if col in cols)
        columns.append(
            ColumnInfo(
                name=col,
                canonical_name=None,
                present_in_runs=present_in_runs,
                dtype=str(df[col].dtype),
                sample_values=_sample_values(df[col]),
                higher_is_better=higher_is_better(col),
            )
        )

    string_cols = [c for c in _STRING_FILTER_COLUMNS if c in df.columns]
    if string_cols and "method" in df.columns:
        for col in string_cols:
            present_in_runs = sorted(
                str(m)
                for m in df["method"].unique().to_list()
                if df.filter(pl.col("method") == m)[col].drop_nulls().len() > 0
            )
            columns.append(
                ColumnInfo(
                    name=col,
                    canonical_name=None,
                    present_in_runs=present_in_runs,
                    dtype=str(df[col].dtype),
                    sample_values=None,
                )
            )

    # Good and Tag are set by the user (thumbs rating, N/C terminus), not written by
    # a pipeline. They apply to every design, including ones not rated or tagged yet,
    # so they stay in the picker when the key is still absent from the design dicts.
    methods = (
        sorted({str(m) for m in df["method"].drop_nulls().unique().to_list()})
        if "method" in df.columns
        else []
    )
    present = {c.name for c in columns}
    annotation_dtypes = {"good": "Boolean", "tag": "String"}
    for name in USER_ANNOTATION_COLUMNS:
        if name in present:
            continue
        columns.append(
            ColumnInfo(
                name=name,
                canonical_name=None,
                present_in_runs=methods,
                dtype=annotation_dtypes[name],
                sample_values=None,
            )
        )

    return sorted(columns, key=lambda c: c.name)


def compute_preview(request: FilteringPreviewRequest) -> FilteringPreviewResponse:
    inputs = build_filter_inputs(
        request.run_ids, request.filters, request.target_contact_groups
    )
    df = inputs.df
    total = df.height
    if df.is_empty():
        return FilteringPreviewResponse(
            total_designs=0, per_filter_counts=[], final_passing=0, available_columns=[]
        )

    stages = filter_cascade_counts(df, inputs.specs)
    for stage in stages:
        label = inputs.labels.get(stage.column)
        if label:
            stage.label = label
    final_passing = stages[-1].remaining if stages else total
    return FilteringPreviewResponse(
        total_designs=total,
        per_filter_counts=stages,
        final_passing=final_passing,
        available_columns=compute_available_columns(request.run_ids),
    )


def compute_apply(request: FilteringApplyRequest) -> FilteringApplyResponse:
    """Hard filters only, returning the actual matching design keys — for live-narrowing
    the Designs table (see plan §7A.2), as opposed to ``compute_preview``'s per-stage
    counts (used for the filter-cascade summary UI) or ``run_filtering_and_save``'s full
    filter+rank+diversity pipeline (used for Saved Set creation).
    """
    inputs = build_filter_inputs(
        request.run_ids, request.filters, request.target_contact_groups
    )
    df = inputs.df
    if df.is_empty():
        return FilteringApplyResponse(total_designs=0, passing_keys=[], final_passing=0)

    filtered = apply_hard_filters(df, inputs.specs)
    passing = filtered.filter(pl.col("pass_filters"))
    keys = [
        DesignKey(
            run_id=str(row["run_id"]),
            design_id=str(row["design_id"]),
            source_path=row.get("source_path"),
        )
        for row in passing.iter_rows(named=True)
    ]
    return FilteringApplyResponse(
        total_designs=df.height, passing_keys=keys, final_passing=len(keys)
    )


def _pick_tiebreak_column(df: pl.DataFrame) -> Optional[str]:
    for candidate in ("design_to_target_iptm", "iptm", "Average_i_pTM"):
        if candidate in df.columns:
            return candidate
    return None


def compute_rank(request: FilteringRankRequest) -> FilteringRankResponse:
    """Hard filters + ranking (boltzgen Algorithm 2 worst-case rank), no diversity
    selection and no Saved Set persistence — backs the Filtering tab's explicit "Apply
    Ranking" button (see plan §7A.2). Cheap relative to diversity selection (polars-only,
    no BioPython alignment), but still not debounced/live like ``compute_apply`` since
    it's a deliberate user action.
    """
    inputs = build_filter_inputs(
        request.run_ids, request.filters, request.target_contact_groups
    )
    df = inputs.df
    if df.is_empty():
        return FilteringRankResponse(designs=[], total_designs=0)

    filtered = apply_hard_filters(df, inputs.specs)
    ranked = rank_designs(
        filtered,
        request.metrics,
        tiebreak_column=_pick_tiebreak_column(df),
        mode=request.ranking_mode,
    )

    rows = [
        RankedDesignRow(
            run_id=str(row["run_id"]),
            design_id=str(row["design_id"]),
            source_path=row.get("source_path"),
            final_rank=_safe_int(row.get("final_rank")),
            quality_score=_safe_float(row.get("quality_score")),
        )
        for row in ranked.iter_rows(named=True)
    ]
    return FilteringRankResponse(designs=rows, total_designs=df.height)


def _diversity_warnings(
    ranked: pl.DataFrame,
    sequence_col: Optional[str],
    budget: int,
    selected: int,
    best_mpnn_only: bool = False,
) -> List[str]:
    """Explain a diverse set that is empty or smaller than the requested budget.

    Diversity selection depends on sequences the designs table may simply not carry
    yet. Previously that surfaced as ``diverse_set_count: 0`` with no reason given.
    """
    candidates = ranked.filter(pl.col("pass_filters")) if "pass_filters" in ranked.columns else ranked
    if best_mpnn_only:
        candidates = keep_best_mpnn_per_backbone(candidates)
    if not sequence_col:
        return [
            "Diversity selection was skipped: these runs have no Sequence column. "
            "Extract sequences first (POST /api/sequences/extract), then re-run."
        ]

    warnings: List[str] = []
    missing = count_missing_sequences(candidates, sequence_col)
    if missing:
        warnings.append(
            f"{missing} of {candidates.height} designs passing the filters have no "
            "sequence and were excluded from diversity selection. Extract sequences "
            "for those runs to include them."
        )
    if selected < budget:
        pool = (
            "remained after keeping the best MPNN variant per backbone and dropping designs without a usable sequence"
            if best_mpnn_only
            else "passed the filters with a usable sequence"
        )
        warnings.append(
            f"Diversity selection returned {selected} designs for a budget of {budget}; "
            f"only that many designs {pool}."
        )
    return warnings


def compute_diversity_preview(request: FilteringDiversityRequest) -> FilteringDiversityResponse:
    """Full filter+rank+diversity pipeline, without persisting a Saved Set — backs the
    Filtering tab's explicit "Apply Diversity Filter" button (see plan §7A.2). Shares
    ``run_filtering_pipeline`` with ``run_filtering_and_save``, just skips the
    ``create_saved_set``/``add_saved_set_designs`` repo calls.
    """
    inputs = build_filter_inputs(
        request.run_ids, request.filters, request.target_contact_groups
    )
    df = inputs.df
    if df.is_empty():
        return FilteringDiversityResponse(
            designs=[], total_designs=0, passing_filters=0, diverse_set_count=0
        )

    sequence_col = "Sequence" if "Sequence" in df.columns else None
    ranked, diverse = run_filtering_pipeline(
        df,
        inputs.specs,
        request.metrics,
        budget=request.budget,
        alpha=request.alpha,
        sequence_col=sequence_col,
        tiebreak_column=_pick_tiebreak_column(df),
        size_buckets=request.size_buckets,
        random_state=request.random_state,
        ranking_mode=request.ranking_mode,
        best_mpnn_only=request.best_mpnn_only,
    )

    diverse_keys = set()
    if diverse is not None:
        diverse_keys = set(
            zip(
                diverse["run_id"].cast(pl.Utf8).to_list(),
                diverse["design_id"].cast(pl.Utf8).to_list(),
            )
        )

    passing_filters = (
        int(ranked["pass_filters"].sum()) if "pass_filters" in ranked.columns else ranked.height
    )

    rows = [
        DiverseDesignRow(
            run_id=str(row["run_id"]),
            design_id=str(row["design_id"]),
            source_path=row.get("source_path"),
            final_rank=_safe_int(row.get("final_rank")),
            quality_score=_safe_float(row.get("quality_score")),
            in_diverse_set=(str(row["run_id"]), str(row["design_id"])) in diverse_keys,
        )
        for row in ranked.iter_rows(named=True)
    ]
    diverse_set_count = diverse.height if diverse is not None else 0
    return FilteringDiversityResponse(
        designs=rows,
        total_designs=df.height,
        passing_filters=passing_filters,
        diverse_set_count=diverse_set_count,
        warnings=_diversity_warnings(
            ranked,
            sequence_col,
            request.budget,
            diverse_set_count,
            best_mpnn_only=request.best_mpnn_only,
        ),
    )


def run_filtering_and_save(request: FilteringRunRequest) -> FilteringRunResponse:
    inputs = build_filter_inputs(
        request.run_ids, request.filters, request.target_contact_groups
    )
    df = inputs.df
    if df.is_empty():
        raise ValueError("No designs found for the given run_ids")
    if "design_id" not in df.columns or "run_id" not in df.columns:
        raise ValueError("Designs are missing required design_id/run_id columns")

    sequence_col = "Sequence" if "Sequence" in df.columns else None
    ranked, diverse = run_filtering_pipeline(
        df,
        inputs.specs,
        request.metrics,
        budget=request.budget,
        alpha=request.alpha,
        sequence_col=sequence_col,
        tiebreak_column=_pick_tiebreak_column(df),
        size_buckets=request.size_buckets,
        random_state=request.random_state,
        apply_diversity=request.apply_diversity,
        ranking_mode=request.ranking_mode,
        best_mpnn_only=request.best_mpnn_only,
    )

    diverse_keys = set()
    if diverse is not None:
        diverse_keys = set(
            zip(
                diverse["run_id"].cast(pl.Utf8).to_list(),
                diverse["design_id"].cast(pl.Utf8).to_list(),
            )
        )

    passing_filters = (
        int(ranked["pass_filters"].sum()) if "pass_filters" in ranked.columns else ranked.height
    )
    diverse_set_count = diverse.height if diverse is not None else 0
    # Without diversity selection the "budget" is the full passing set.
    top_set_count = (
        diverse_set_count if not request.apply_diversity else min(request.budget, ranked.height)
    )
    warnings = (
        []
        if not request.apply_diversity
        else _diversity_warnings(
            ranked,
            sequence_col,
            request.budget,
            diverse_set_count,
            best_mpnn_only=request.best_mpnn_only,
        )
    )

    saved_set_id = str(uuid.uuid4())
    repo = get_designs_repository()
    repo.create_saved_set(
        saved_set_id=saved_set_id,
        name=request.name,
        source_run_ids=request.run_ids,
        filter_params=request.model_dump(),
        result_summary={
            "total_input": df.height,
            "passing_filters": passing_filters,
            "top_set_count": top_set_count,
            "diverse_set_count": diverse_set_count,
            "warnings": warnings,
        },
    )

    reserved_cols = {"run_id", "design_id", "source_path"}
    design_rows: List[Dict[str, Any]] = []
    for row in ranked.iter_rows(named=True):
        run_id = str(row["run_id"])
        design_id = str(row["design_id"])
        design_rows.append(
            {
                "design_id": design_id,
                "run_id": run_id,
                "source_path": row.get("source_path"),
                "final_rank": _safe_int(row.get("final_rank")),
                "quality_score": _safe_float(row.get("quality_score")),
                "in_diverse_set": (run_id, design_id) in diverse_keys,
                "metrics": {
                    k: v
                    for k, v in row.items()
                    if k not in reserved_cols
                    and not k.startswith("__tc_")
                    and _is_json_scalar(v)
                },
            }
        )
    repo.add_saved_set_designs(saved_set_id, design_rows)

    return FilteringRunResponse(
        saved_set_id=saved_set_id,
        name=request.name,
        total_input=df.height,
        passing_filters=passing_filters,
        top_set_count=top_set_count,
        diverse_set_count=diverse_set_count,
        warnings=warnings,
    )


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_json_scalar(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (bool, int, str)):
        return True
    if isinstance(value, float):
        return not math.isnan(value)
    return False


def _saved_set_from_row(row: Dict[str, Any]) -> SavedSet:
    summary = row["result_summary"]
    # design_count is the actual size of the saved set (the diversity-selected
    # subset) — NOT len(list_saved_set_designs(...)), which stores every ranked
    # design (pass or fail the hard filters) so the per-design table can show
    # in_diverse_set/final_rank for the whole ranked pool. Using that length here
    # previously made design_count equal total_input for almost every saved set.
    return SavedSet(
        id=row["id"],
        name=row["name"],
        created_at=str(row["created_at"]),
        source_run_ids=row["source_run_ids"],
        filter_params=row["filter_params"],
        design_count=int(summary.get("diverse_set_count", 0)),
        total_input=int(summary.get("total_input", 0)),
    )


def list_saved_sets() -> SavedSetListResponse:
    repo = get_designs_repository()
    return SavedSetListResponse(
        saved_sets=[_saved_set_from_row(row) for row in repo.list_saved_sets()]
    )


def get_saved_set(saved_set_id: str) -> Optional[SavedSet]:
    repo = get_designs_repository()
    row = repo.get_saved_set(saved_set_id)
    if row is None:
        return None
    return _saved_set_from_row(row)


def get_saved_set_designs(saved_set_id: str) -> Optional[SavedSetDesignsResponse]:
    repo = get_designs_repository()
    if repo.get_saved_set(saved_set_id) is None:
        return None
    rows = repo.list_saved_set_designs(saved_set_id)
    return SavedSetDesignsResponse(
        designs=[
            SavedSetDesignRow(
                design_id=r["design_id"],
                run_id=r["run_id"],
                source_path=r["source_path"] or None,
                final_rank=r["final_rank"],
                quality_score=r["quality_score"],
                in_diverse_set=r["in_diverse_set"],
                metrics=r["metrics"],
            )
            for r in rows
        ]
    )


def delete_saved_set(saved_set_id: str) -> bool:
    repo = get_designs_repository()
    return repo.delete_saved_set(saved_set_id)


def rename_saved_set(saved_set_id: str, name: str) -> bool:
    """Sets are otherwise immutable snapshots (see plan §7A.4) — rename is the one
    allowed mutation.
    """
    repo = get_designs_repository()
    return repo.rename_saved_set(saved_set_id, name)
