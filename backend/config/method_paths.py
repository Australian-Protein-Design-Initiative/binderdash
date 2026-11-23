"""
Pipeline ``method`` identifiers, path heuristics, params keys, and structure file resolution.

Consolidates former ``pipeline_ids``, ``path_heuristics``, ``input_structure_keys``, and ``file_resolve``.
"""

from __future__ import annotations

import re
from typing import Dict, Final, FrozenSet, Optional, Sequence, Tuple

# --- Known method string literals (run metadata, folder layouts) -------------

PIPELINE_METHOD_IDS: Final[tuple[str, ...]] = (
    "bindcraft",
    "rfd",
    "boltzgen",
    "rfd3",
    "rfd4_proteina",
    "bindcraft2",
)

PIPELINE_METHOD_IDS_SET: Final[FrozenSet[str]] = frozenset(PIPELINE_METHOD_IDS)

# --- Run / project path segments (``run_discovery`` name guessing) -------------

_RUN_NAME_SEGMENT_BLOCKLIST: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(p)
    for p in (
        r"^results.*$",
        r"^bindcraft$",
        r"^rfd$",
        r"^boltzgen$",
        r"^rfd3$",
        r"^rfd4$",
        r"^rfd4_proteina$",
        r"^bc2$",
        r"^batches$",
        r"^\d+$",
    )
)

_PROJECT_ID_SEGMENT_BLOCKLIST: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(p)
    for p in (
        r"^runs$",
        r"^results.*$",
        r"^batch.*$",
        r"^bindcraft$",
        r"^rfd$",
        r"^boltzgen$",
        r"^rfd3$",
        r"^rfd4$",
        r"^rfd4_proteina$",
        r"^bc2$",
        r"^\d+$",
    )
)


def is_disallowed_run_name_segment(name: str) -> bool:
    return any(p.match(name) for p in _RUN_NAME_SEGMENT_BLOCKLIST)


def is_disallowed_project_id_segment(name: str) -> bool:
    return any(p.match(name) for p in _PROJECT_ID_SEGMENT_BLOCKLIST)


def should_prune_walk_bindcraft_batches(path_parts: Sequence[str]) -> bool:
    """Skip descending into ``.../results/bindcraft/batches/...`` (nf-core bindcraft batch runs)."""
    if "batches" not in path_parts:
        return False
    try:
        i = path_parts.index("batches")
    except ValueError:
        return False
    return (
        i >= 2
        and path_parts[i - 1] == "bindcraft"
        and path_parts[i - 2] == "results"
    )

# --- Params JSON keys for input / target structures (``input_targets``) --------

STRUCTURE_PARAM_KEYS_BY_METHOD: Final[Dict[str, Tuple[str, ...]]] = {
    "bindcraft": (
        "target_pdb",
        "starting_pdb",
        "input_pdb",
        "pdb_path",
        "target_path",
        "binder_target",
        "structure",
    ),
    "rfd": (
        "target_pdb",
        "input_pdb",
        "pdb_path",
        "starting_pdb",
    ),
    "boltzgen": (
        "target_pdb",
        "input_pdb",
        "pdb_path",
        "structure",
    ),
    "rfd3": (
        "target_pdb",
        "input_pdb",
        "pdb_path",
    ),
    # Config mode (--rfd4_config) names the target inside the YAML spec, not in
    # params.json; only params mode (--input_pdb) is resolvable from here.
    "rfd4_proteina": (
        "input_pdb",
        "target_pdb",
        "pdb_path",
    ),
    "bindcraft2": (
        "input_pdb",
        "target_pdb",
        "target_path",
        "pdb_path",
        "binder_scaffold",
    ),
}

# --- Structure basename matching (``files`` router; Boltzgen rank* prefixes) -----

METHODS_STRUCTURE_BASENAME_STRIP_FIRST_UNDERSCORE: Final[FrozenSet[str]] = frozenset({"boltzgen"})


def structure_resolve_uses_strip_after_first_underscore(method: Optional[str]) -> bool:
    return (method or "") in METHODS_STRUCTURE_BASENAME_STRIP_FIRST_UNDERSCORE
