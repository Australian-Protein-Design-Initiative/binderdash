from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Authentication models
class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class ScanRequest(BaseModel):
    folders: List[str]
    force_rescan_of_ingested: bool = False


class IngestRequest(BaseModel):
    runs: List[Dict[str, Any]]


class IngestPreviewRequest(BaseModel):
    runs: List[Dict[str, Any]]


class IngestPreviewReingestItem(BaseModel):
    run_group_key: str
    display_name: str


class IngestPreviewResponse(BaseModel):
    reingest: List[IngestPreviewReingestItem]


class RunMetadata(BaseModel):
    run_id: str
    project_id: str
    path: str
    method: str  # e.g. bindcraft, rfd, boltzgen, rfd3
    results_table: Optional[str] = None
    pdb_files: List[str] = []
    metadata: Dict[str, Any] = {}


class PdbTarItem(BaseModel):
    run_id: str
    filename: str


class PdbTarRequest(BaseModel):
    items: List[PdbTarItem]


class DesignGoodUpdate(BaseModel):
    run_id: str
    design_id: str
    good: Optional[bool]
    source_path: Optional[str] = None


class DesignTagUpdate(BaseModel):
    run_id: str
    design_id: str
    tag: Optional[str] = None  # N, C, or None to clear
    source_path: Optional[str] = None


class SequenceExtractItem(BaseModel):
    run_id: str
    design_id: str
    pdb_file: str
    chain: str = "B"
    source_path: Optional[str] = None


class SequenceExtractRequest(BaseModel):
    designs: List[SequenceExtractItem]
    refresh_cache_after: bool = Field(
        default=True,
        description="When false, skip rebuilding the in-memory designs cache until a later refresh.",
    )


class SequenceExtractResultRow(BaseModel):
    run_id: str
    design_id: str
    sequence: Optional[str] = None
    error: Optional[str] = None


class SequenceExtractResponse(BaseModel):
    results: List[SequenceExtractResultRow]


class ShortNameUpdate(BaseModel):
    run_id: str
    design_id: str
    short_name: Optional[str] = None
    source_path: Optional[str] = None


class ShortNameBulkRequest(BaseModel):
    updates: List[ShortNameUpdate]
    refresh_cache_after: bool = Field(
        default=True,
        description="When true, reload designs cache from the database after persisting.",
    )


class ShortNameBulkResponse(BaseModel):
    updated: int


class MergeTableResponse(BaseModel):
    preview: bool
    design_id_column: str
    upload_row_count: int = 0
    new_columns: List[str] = []
    matched_design_count: int = 0
    unknown_design_id_count: int = 0
    skipped_columns: List[str] = []
    pipeline_collision_columns: List[str] = []
    would_update_rows: Optional[int] = None
    matched: Optional[int] = None
    updated: Optional[int] = None
    skipped_keys: Optional[int] = None
    unknown_design_ids: Optional[int] = None


class TagPlacementItem(BaseModel):
    run_id: str
    design_id: str
    pdb_file: Optional[str] = None
    source_path: Optional[str] = None


class TagPlacementRequest(BaseModel):
    designs: List[TagPlacementItem]
    binder_chain: str = "B"
    target_chains: Optional[str] = None
    distant_from: Optional[str] = None
    sasa_probe_radius: float = 1.4
    sasa_n_points: int = 100
    sasa_threshold: float = 30.0
    more_distant_threshold: float = 5.0
    refresh_cache_after: bool = Field(
        default=True,
        description="When false, skip rebuilding the in-memory designs cache until a later refresh.",
    )
    cache_only: bool = Field(
        default=False,
        description="When true, return cached tag metrics only (no compute); misses are empty rows.",
    )
    ignore_cache: bool = Field(
        default=False,
        description="When true, skip cache reads; recompute and refresh stored cache entries.",
    )


class TagPlacementResultRow(BaseModel):
    run_id: str
    design_id: str
    tag: Optional[str] = None
    error: Optional[str] = None


class TagPlacementResponse(BaseModel):
    results: List[TagPlacementResultRow]


class TagMetricsRow(BaseModel):
    run_id: str
    design_id: str
    pdb_file: Optional[str] = None
    sequence: Optional[str] = None
    n_aa_type: Optional[str] = None
    c_aa_type: Optional[str] = None
    n_sasa: Optional[float] = None
    c_sasa: Optional[float] = None
    n_percent_sasa: Optional[float] = None
    c_percent_sasa: Optional[float] = None
    n_percent_buried: Optional[float] = None
    c_percent_buried: Optional[float] = None
    n_c_dist: Optional[float] = None
    n_dist_target: Optional[float] = None
    c_dist_target: Optional[float] = None
    n_target_contacts: Optional[bool] = None
    c_target_contacts: Optional[bool] = None
    predicted_tag: Optional[str] = None
    error: Optional[str] = None


class TagMetricsResponse(BaseModel):
    results: List[TagMetricsRow]


class StructuralMetricsRequest(BaseModel):
    designs: List[TagPlacementItem]
    # Override chain roles for every design in the request; when omitted, roles are
    # resolved per-run (known per-method convention, else the sampled-sequence-identity
    # guess heuristic — see filtering.chain_roles).
    binder_chain_ids: Optional[List[str]] = None
    target_chain_ids: Optional[List[str]] = None
    cache_only: bool = Field(
        default=False,
        description="When true, return cached structural metrics only (no compute); misses are empty rows.",
    )
    ignore_cache: bool = Field(
        default=False,
        description="When true, skip cache reads; recompute and refresh stored cache entries.",
    )


class StructuralMetricsRow(BaseModel):
    run_id: str
    design_id: str
    pdb_file: Optional[str] = None
    binder_chain_ids: Optional[List[str]] = None
    target_chain_ids: Optional[List[str]] = None
    # Flat metric name -> value, all prefixed binderdash_ (binderdash_helix_fraction,
    # binderdash_sheet_fraction, binderdash_loop_fraction, binderdash_delta_sasa,
    # binderdash_hydrophobic_patch_area, binderdash_hbonds, binderdash_saltbridge,
    # binderdash_hydrophobicity, binderdash_<AA>_fraction, ...) to distinguish them from
    # provider-reported columns for the same/a similar concept; see
    # filtering.structural_metrics. Not a fixed schema, matching the rest of BinderDash's
    # method-dependent flat design dicts.
    metrics: Optional[Dict[str, float]] = None
    error: Optional[str] = None


class StructuralMetricsResponse(BaseModel):
    results: List[StructuralMetricsRow]


class InputTargetItem(BaseModel):
    id: str
    label: str


class InputTargetsResponse(BaseModel):
    targets: List[InputTargetItem]


class CodonTableOption(BaseModel):
    value: str
    label: str


class CodonTableListResponse(BaseModel):
    items: List[CodonTableOption]


class CodonTableDetailResponse(BaseModel):
    value: str
    label: str
    stop_codons: List[str]
    codons_by_aa: Dict[str, Dict[str, float]]


class DnaOptConstraintSpec(BaseModel):
    type: str
    enabled: bool = True
    params: Dict[str, Any] = {}


class DnaOptimizeRequest(BaseModel):
    sequences: Dict[str, str]
    codon_table_id: str
    method: str = "match_codon_usage"
    constraints: List[DnaOptConstraintSpec] = []
    # Per-residue fixed mask keyed by design_id. Stops marked true stay as TAA.
    # When a design_id is omitted, every * in that protein is treated as fixed.
    fixed: Optional[Dict[str, List[bool]]] = None
    # Coding-frame offset (0, 1 or 2) keyed by design_id. Nucleotide additions
    # whose length is not a multiple of 3 shift where design and tag codons start.
    frame: Optional[Dict[str, int]] = None


class DnaOptResultRow(BaseModel):
    design_id: str
    optimized_dna: Optional[str] = None
    error: Optional[str] = None


class DnaOptimizeResponse(BaseModel):
    results: List[DnaOptResultRow]
    elapsed_seconds: float

