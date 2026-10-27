"""Pydantic models for bundle requests and the JSON members of a bundle.

Two different typing postures here, on purpose:

* **Client-supplied payloads** (``SessionState`` in session_state.py,
  ``PrepareSequencesPayload`` below) use ``extra="allow"``. They mirror Pinia stores that
  move faster than the backend, and a download failing with a 422 because the frontend
  gained a field would be a poor trade for type strictness on data the backend only
  passes through.
* **Backend-authored payloads** (``BundleManifest`` and friends) are fully typed. The
  manifest is the thing consumers parse, so it is the contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..filtering.schemas import DesignKey
from ..schemas import DnaOptConstraintSpec
from ..session_state import SessionState

MANIFEST_SCHEMA_VERSION = "1.0"
# 1.1 adds PreparedRowExport.seed and PrepareSequencesPayload.tool_versions, so a
# recorded run can be replayed. Additive, so 1.0 readers still accept it.
PREPARE_SEQUENCES_SCHEMA_VERSION = "1.1"
CONTACTS_REFERENCE_SCHEMA_VERSION = "1.0"

BundleKind = Literal["designs", "prepare_sequences"]


# --- Request bodies -------------------------------------------------------------------


class BundleIncludeOptions(BaseModel):
    designs_table: bool = True
    binder_fasta: bool = True
    structures: bool = True
    target_contacts: bool = True
    session: bool = True


class BundleDesignsRequest(BaseModel):
    """Design *keys*, not rows.

    The server re-reads each design dict from the in-memory cache, which keeps a
    20k-design request around a megabyte instead of a couple of hundred, and makes the
    bundle's designs.tsv identical to ``GET /api/designs?format=tsv``. Anything the
    client computes and the server cannot (a ranking column, a short name) goes in
    ``client_columns``.
    """

    keys: List[DesignKey] = Field(default_factory=list)
    run_ids: List[str] = Field(default_factory=list)
    label: str = "binderdash_designs"
    include: BundleIncludeOptions = Field(default_factory=BundleIncludeOptions)
    include_heavy: bool = False
    session: Optional[SessionState] = None
    # design key -> extra column values merged onto that row.
    client_columns: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class PreparedRowExport(BaseModel):
    model_config = ConfigDict(extra="allow")

    row_key: str = ""
    design_id: str
    run_id: str = ""
    run_name: str = ""
    project_id: str = ""
    source_path: Optional[str] = None
    tag: str = ""
    short_name: str = ""
    original_sequence: str = ""
    prepared_aa: str
    prepared_dna: Optional[str] = None
    extinction_coeff_reduced: Optional[float] = None
    extinction_coeff_oxidized: Optional[float] = None
    isoelectric_point: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    # The DnaChisel seed that produced prepared_dna. Replay it (with the matching
    # tool_versions) to reproduce this exact sequence.
    seed: Optional[int] = None


class PreparedTag(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    kind: str = ""
    sequence: str = ""
    label: str = ""
    zone: Optional[str] = None
    # Applied to every design regardless of its tag-end column.
    always: bool = False


class PrepareSequencesPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = PREPARE_SEQUENCES_SCHEMA_VERSION
    kind: Literal["binderdash.prepare_sequences"] = "binderdash.prepare_sequences"
    generated_at: Optional[str] = None
    binderdash: Optional["BuildInfo"] = None

    order_name: str = ""
    extract_chain: str = ""
    good_only: bool = False
    dna_mode: bool = False

    n_tags: List[PreparedTag] = Field(default_factory=list)
    c_tags: List[PreparedTag] = Field(default_factory=list)
    # Legacy (before tags could be flagged "always"): read from old bundles, no longer written.
    n_terminal_prefix: str = ""
    c_terminal_suffix: str = ""

    stop_options: Dict[str, Any] = Field(default_factory=dict)
    short_name_strategy: Dict[str, Any] = Field(default_factory=dict)

    codon_table_id: Optional[str] = None
    optimization_method: Optional[str] = None
    optimization_constraints: List[DnaOptConstraintSpec] = Field(default_factory=list)
    # Versions the recorded seeds are replayable against; a DnaChisel upgrade can
    # change the search order and so the DNA for the same seed.
    tool_versions: Dict[str, str] = Field(default_factory=dict)

    rows: List[PreparedRowExport] = Field(default_factory=list)


class PrepareSequencesBundleRequest(BundleDesignsRequest):
    prepared: PrepareSequencesPayload
    label: str = "binderdash_constructs"


class BundleEstimateRequest(BundleDesignsRequest):
    """Same shape as the bundle request so the UI estimates the exact selection it will
    submit; ``session``/``client_columns`` are ignored."""


# --- Manifest -------------------------------------------------------------------------


class BuildInfo(BaseModel):
    app_version: str
    git_commit: Optional[str] = None
    git_dirty: Optional[bool] = None
    build_source: Literal["env", "build_file", "git", "unknown"] = "unknown"
    python_version: str = ""
    platform: str = ""


class BundleProvenance(BaseModel):
    source: Literal["live_selection", "saved_set"]
    run_ids: List[str] = Field(default_factory=list)
    saved_set_id: Optional[str] = None
    saved_set_name: Optional[str] = None
    saved_set_created_at: Optional[str] = None
    # Verbatim recipe from the saved set, minus ui_state (which is already the whole of
    # binderdash_session.json - no point carrying it twice in one archive).
    filter_params: Optional[Dict[str, Any]] = None


class BundleFileEntry(BaseModel):
    path: str
    size_bytes: int
    sha256: str
    media_type: str = "application/octet-stream"
    description: str = ""


class BundleCoverage(BaseModel):
    designs: int = 0
    designs_with_sequence: int = 0
    designs_without_sequence: int = 0
    structures_requested: int = 0
    structures_included: int = 0
    structures_missing: int = 0
    designs_with_contacts: int = 0
    designs_without_contacts: int = 0
    contact_params_key: Optional[str] = None
    constructs: int = 0


class BundleManifest(BaseModel):
    schema_version: str = MANIFEST_SCHEMA_VERSION
    kind: Literal["binderdash.manifest"] = "binderdash.manifest"
    bundle_id: str
    bundle_kind: BundleKind
    created_at: str
    label: str
    build: BuildInfo
    provenance: BundleProvenance
    coverage: BundleCoverage
    files: List[BundleFileEntry] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# --- Target contacts reference --------------------------------------------------------


class ContactReferenceResidue(BaseModel):
    label: str
    chain: str
    resseq: int
    icode: str = " "
    resname: str
    aa1: str = ""
    sasa_apo: float


class ContactReferenceRun(BaseModel):
    run_id: str
    run_name: str = ""
    method: str = ""
    target_key: str = ""
    binder_chain_ids: List[str] = Field(default_factory=list)
    target_chain_ids: List[str] = Field(default_factory=list)
    target_moves: bool = False
    error: Optional[str] = None
    residues: List[ContactReferenceResidue] = Field(default_factory=list)


class TargetContactsReference(BaseModel):
    schema_version: str = CONTACTS_REFERENCE_SCHEMA_VERSION
    kind: Literal["binderdash.target_contacts_reference"] = (
        "binderdash.target_contacts_reference"
    )
    generated_at: Optional[str] = None
    binderdash: Optional[BuildInfo] = None
    params_key: Optional[str] = None
    record_cutoff_angstrom: Optional[float] = None
    note: str = (
        "Residues further than record_cutoff_angstrom from the binder are omitted from "
        "target_contacts.tsv: their bound SASA equals sasa_apo here and their delta is 0."
    )
    runs: List[ContactReferenceRun] = Field(default_factory=list)


class BundleEstimate(BaseModel):
    design_count: int = 0
    structure_count: int = 0
    structures_missing: int = 0
    structure_bytes: int = 0
    tables_bytes_estimate: int = 0
    estimated_zip_bytes: int = 0
    contacts_rows: int = 0
    designs_with_contacts: int = 0
    max_structure_files: int = 0
    max_structure_bytes: int = 0
    max_total_bytes: int = 0
    exceeds_cap: bool = False
    cap_messages: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


PrepareSequencesPayload.model_rebuild()
