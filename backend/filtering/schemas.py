from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..session_state import SessionState


NUMERIC_OPERATORS = ("<", "<=", ">", ">=")
# Designs-table columns the user sets (Good / Tag), not pipeline metrics. Always
# offered as hard filters; a missing column means every design is still unset.
USER_ANNOTATION_COLUMNS = ("good", "tag")
STRING_OPERATORS = (
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "equals",
    "not_equals",
    "regex",
)
EMPTY_OPERATORS = ("is_empty", "is_not_empty")


class FilterSpec(BaseModel):
    """A single hard filter — a strict superset of the operators the pre-existing
    client-side Designs-tab custom-filter system supported (see plan §7A.1), so this
    engine can be the single source of truth for both the REST API and the UI.

    ``column`` may be a canonical metric name (see ``filtering.metrics``) or a raw
    DataFrame column name.

    Numeric operators (``<``, ``<=``, ``>``, ``>=``) follow the boltzgen convention:
    lower-is-better metrics use "<" (or "<="), higher-is-better metrics use ">" (or
    ">="); use ``threshold``.

    String operators (``contains``, ``not_contains``, ``starts_with``, ``ends_with``,
    ``equals``, ``not_equals``, ``regex``) compare against ``text_value``.
    ``contains``/``starts_with``/``ends_with`` are case-insensitive (matching the prior
    client-side filters' UX); ``equals``/``not_equals``/``regex`` are case-sensitive.

    ``is_empty``/``is_not_empty`` need neither ``threshold`` nor ``text_value``.
    """

    column: str
    operator: Literal[
        "<", "<=", ">", ">=",
        "contains", "not_contains", "starts_with", "ends_with",
        "equals", "not_equals", "regex",
        "is_empty", "is_not_empty",
    ]
    threshold: Optional[float] = None
    text_value: Optional[str] = None


RankingMode = Literal["worst_rank", "simple"]


class RankingMetric(BaseModel):
    """One column in a ranking recipe.

    In ``worst_rank`` mode, ``weight`` is the *inverse-importance* weight: a design's
    rank on this metric is divided by ``weight`` before taking the max across metrics,
    so a larger weight de-emphasises the metric. In ``simple`` mode the list order is
    the sort priority (first metric is primary) and ``weight`` is ignored.
    """

    column: str
    weight: float = 1.0
    higher_is_better: bool = True


class SizeBucket(BaseModel):
    """Caps the number of diverse-set selections whose sequence length falls in [min, max)."""

    min: int
    max: int
    num_designs: int


class ColumnInfo(BaseModel):
    name: str
    canonical_name: Optional[str] = None
    present_in_runs: List[str] = Field(default_factory=list)
    dtype: str
    sample_values: Optional[Dict[str, float]] = None  # {"min":..., "max":..., "mean":...}
    # For a canonical (merged) entry: {method: raw_column_name} showing which raw
    # per-method column this concept resolves to, e.g. {"rfd": "pae_interaction",
    # "bindcraft": "Average_i_pAE"}. Empty/absent for standalone raw columns.
    raw_columns: Dict[str, str] = Field(default_factory=dict)
    # Known sort/filter direction from filtering.metrics.METRIC_DIRECTIONS (also
    # resolved for raw aliases). None when unknown or non-score (identity columns).
    higher_is_better: Optional[bool] = None


class FilterCascadeStage(BaseModel):
    column: str
    operator: str
    threshold: Optional[float] = None
    text_value: Optional[str] = None
    # Designs remaining after this stage — filters cascade sequentially (each stage's
    # input is the prior stage's output), so this is also "how many passed this
    # stage"; there's no separate independent count to report.
    remaining: int
    # Human-readable stage name. Set for target-contact stages, whose column is an
    # internal ``__tc_*`` virtual column that means nothing to a reader.
    label: Optional[str] = None


class DesignKey(BaseModel):
    run_id: str
    design_id: str
    source_path: Optional[str] = None


class TargetContactFilterSpec(BaseModel):
    """One condition on a set of target residues, e.g. "any of A166,A167 within 8 A of
    the binder (heavy atoms)" or "all of A166,A170 buried by at least 20% on binding".

    ``residues`` are labels in ``<chain><resseq>[<icode>]`` form (``A166``), matching
    nf-binder-design's complex_sasa.py convention.
    """

    residues: List[str] = Field(default_factory=list)
    # "any"/"all": the condition must hold for at least one / every listed residue.
    # "count": for at least ``min_count`` of them. "site_percent": sum the metric over
    # the listed residues and compare that total (percent units only).
    scope: Literal["any", "all", "count", "site_percent"] = "any"
    min_count: Optional[int] = None
    metric: Literal["distance", "sasa_bound", "delta_sasa"] = "distance"
    distance_type: Literal["ca", "cb", "heavy"] = "heavy"
    # Angstroms (A^2 for SASA metrics) or percent of the residue's theoretical maximum.
    unit: Literal["angstrom", "percent"] = "angstrom"
    operator: Literal["<", "<=", ">", ">="] = "<="
    value: float = 0.0


class TargetContactGroup(BaseModel):
    """Contact filters written against one target.

    Multiple groups let a single filter set say "residue A166 on target X, and the
    equivalent residue B142 on target Y", where the two targets have different
    numbering or constructs. A design whose run falls outside a group's scope is exempt
    from that group's filters, so each design is only constrained by the conditions
    written against its own target.
    """

    target_key: str = ""
    # Empty means "every run in scope whose target is target_key".
    run_ids: List[str] = Field(default_factory=list)
    label: Optional[str] = None
    filters: List[TargetContactFilterSpec] = Field(default_factory=list)


class TargetResidueDto(BaseModel):
    label: str
    chain: str
    resseq: int
    icode: str = " "
    resname: str
    aa1: str
    sasa_apo: float


class TargetInfo(BaseModel):
    target_key: str
    label: str
    run_ids: List[str] = Field(default_factory=list)
    chain_ids: List[str] = Field(default_factory=list)
    length: int = 0
    residues: List[TargetResidueDto] = Field(default_factory=list)


class TargetContactCoverage(BaseModel):
    run_id: str
    run_name: Optional[str] = None
    target_key: str = ""
    total_designs: int = 0
    computed_designs: int = 0
    target_moves: bool = False


class TargetResiduesRequest(BaseModel):
    run_ids: List[str]


class TargetResiduesResponse(BaseModel):
    targets: List[TargetInfo] = Field(default_factory=list)
    coverage: List[TargetContactCoverage] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class TargetContactsComputeRequest(BaseModel):
    run_ids: List[str]
    # Restrict to specific designs; empty means every design in the given runs that has
    # no cached record yet.
    design_keys: List[DesignKey] = Field(default_factory=list)
    ignore_cache: bool = False
    max_workers: Optional[int] = None


class TargetContactsComputeResponse(BaseModel):
    computed: int = 0
    cached: int = 0
    failed: int = 0
    errors: List[str] = Field(default_factory=list)
    coverage: List[TargetContactCoverage] = Field(default_factory=list)


class TargetContactProfileRequest(BaseModel):
    """Per-residue aggregate across a design set, for the structure viewer's colour map."""

    run_ids: List[str]
    design_keys: List[DesignKey] = Field(default_factory=list)
    target_key: Optional[str] = None
    metric: Literal["delta_sasa", "contact_frequency", "distance"] = "delta_sasa"
    unit: Literal["angstrom", "percent"] = "angstrom"
    distance_type: Literal["ca", "cb", "heavy"] = "heavy"
    # Contact definition for metric="contact_frequency".
    contact_metric: Literal["distance", "delta_sasa"] = "distance"
    contact_threshold: float = 5.0


class TargetContactProfileRow(BaseModel):
    label: str
    chain: str
    resseq: int
    resname: str
    aa1: str
    mean: Optional[float] = None
    median: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    contact_fraction: float = 0.0
    n: int = 0


class TargetContactProfileResponse(BaseModel):
    target_key: str = ""
    residues: List[TargetContactProfileRow] = Field(default_factory=list)
    n_designs: int = 0
    warnings: List[str] = Field(default_factory=list)


class FilteringPreviewRequest(BaseModel):
    run_ids: List[str]
    filters: List[FilterSpec] = Field(default_factory=list)
    target_contact_groups: List[TargetContactGroup] = Field(default_factory=list)
    metrics: List[RankingMetric] = Field(default_factory=list)


class FilteringPreviewResponse(BaseModel):
    total_designs: int
    per_filter_counts: List[FilterCascadeStage]
    final_passing: int
    available_columns: List[ColumnInfo]


class FilteringRunRequest(BaseModel):
    name: str
    run_ids: List[str]
    filters: List[FilterSpec] = Field(default_factory=list)
    target_contact_groups: List[TargetContactGroup] = Field(default_factory=list)
    metrics: List[RankingMetric] = Field(default_factory=list)
    # Omitted by older clients, which always used boltzgen worst-case rank.
    ranking_mode: RankingMode = "worst_rank"
    budget: int = 24
    # Quality only: the subset is the top of the ranking, up to the budget. BoltzGen's
    # own defaults (0.001 protein, 0.01 peptide) stay as UI slider marks, not this
    # omitted-field default. Matches the frontend (see stores/filtering.ts).
    alpha: float = 0.0
    size_buckets: List[SizeBucket] = Field(default_factory=list)
    random_state: int = 0
    # When False, the saved set is every design that passed the hard filters (no budget
    # / lazy-greedy diversity pass). Budget and alpha are still accepted so a disabled
    # diversity recipe can round-trip without losing the user's last settings.
    apply_diversity: bool = True
    # When true and diversity selection runs, keep one design per backbone_id (best
    # primary score) before the lazy-greedy pass. Ignored when apply_diversity is false.
    best_mpnn_only: bool = False
    # The UI state when the set was saved. Rides into the saved set's filter_params
    # blob, so a set downloaded later reproduces the table layout and not just the
    # filter recipe. Absent on sets created before this field existed.
    ui_state: Optional[SessionState] = None


class FilteringRunResponse(BaseModel):
    saved_set_id: str
    name: str
    total_input: int
    passing_filters: int
    top_set_count: int
    diverse_set_count: int
    # Why diverse_set_count can be smaller than budget (or zero) — without this the
    # shortfall is silent and reads as "diversity selection found nothing".
    warnings: List[str] = Field(default_factory=list)


class FilteringColumnsRequest(BaseModel):
    run_ids: List[str]


class FilteringColumnsResponse(BaseModel):
    columns: List[ColumnInfo]


class FilteringApplyRequest(BaseModel):
    """Hard filters only (no ranking/diversity) — for live-narrowing the Designs table.
    Cheap: a single polars filter pass, no ranking computation. See plan §7A.2.
    """

    run_ids: List[str]
    filters: List[FilterSpec] = Field(default_factory=list)
    target_contact_groups: List[TargetContactGroup] = Field(default_factory=list)


class FilteringApplyResponse(BaseModel):
    total_designs: int
    passing_keys: List[DesignKey]
    final_passing: int



class SavedSet(BaseModel):
    id: str
    name: str
    created_at: str
    source_run_ids: List[str]
    filter_params: Dict
    design_count: int
    total_input: int


class SavedSetListResponse(BaseModel):
    saved_sets: List[SavedSet]


class SavedSetDesignRow(BaseModel):
    design_id: str
    run_id: str
    source_path: Optional[str] = None
    final_rank: Optional[int] = None
    quality_score: Optional[float] = None
    in_diverse_set: bool = False
    metrics: Dict = Field(default_factory=dict)


class SavedSetDesignsResponse(BaseModel):
    designs: List[SavedSetDesignRow]


class SavedSetRenameRequest(BaseModel):
    name: str


class FilteringRankRequest(BaseModel):
    """Hard filters + ranking, no diversity selection and no Saved Set persistence —
    for the Filtering tab's explicit "Apply Ranking" action (see plan §7A.2).
    """

    run_ids: List[str]
    filters: List[FilterSpec] = Field(default_factory=list)
    target_contact_groups: List[TargetContactGroup] = Field(default_factory=list)
    metrics: List[RankingMetric] = Field(default_factory=list)
    ranking_mode: RankingMode = "worst_rank"


class RankedDesignRow(BaseModel):
    run_id: str
    design_id: str
    source_path: Optional[str] = None
    final_rank: Optional[int] = None
    quality_score: Optional[float] = None


class FilteringRankResponse(BaseModel):
    designs: List[RankedDesignRow]
    total_designs: int


class FilteringDiversityRequest(BaseModel):
    """Same shape as ``FilteringRunRequest`` minus ``name`` — runs the full
    filter+rank+diversity pipeline without persisting a Saved Set, for the Filtering
    tab's explicit "Apply Diversity Filter" action (see plan §7A.2).
    """

    run_ids: List[str]
    filters: List[FilterSpec] = Field(default_factory=list)
    target_contact_groups: List[TargetContactGroup] = Field(default_factory=list)
    metrics: List[RankingMetric] = Field(default_factory=list)
    ranking_mode: RankingMode = "worst_rank"
    budget: int = 24
    alpha: float = 0.0
    size_buckets: List[SizeBucket] = Field(default_factory=list)
    random_state: int = 0
    # Collapse to the best MPNN variant per backbone before diversity selection.
    best_mpnn_only: bool = False


class DiverseDesignRow(BaseModel):
    run_id: str
    design_id: str
    source_path: Optional[str] = None
    final_rank: Optional[int] = None
    quality_score: Optional[float] = None
    in_diverse_set: bool = False


class FilteringDiversityResponse(BaseModel):
    designs: List[DiverseDesignRow]
    total_designs: int
    passing_filters: int
    diverse_set_count: int
    warnings: List[str] = Field(default_factory=list)
