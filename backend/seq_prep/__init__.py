"""Prepare Sequences: tag placement, construct assembly, short names, exports.

The single implementation of the construct builder. The API serves it, and the
downloadable script inlines this package's source verbatim, so the two cannot
drift. See ``plans/seq_prep_download_script.md``.
"""

from .build import PreparedRow, build_row, build_rows, raw_sequence
from .codon import FIXED_START_DNA, FIXED_STOP_DNA, CodonTable
from .config import PlacedTag, PrepareConfig, SCHEMA_VERSION, migrate_js_replacement
from .mixed import Segment, validate_mixed_sequence
from .optimize import optimize_sequences, tool_versions
from .shortnames import ShortNameStrategy, compute_short_names
from .tags import (
    CUSTOM_TAG_VISUAL,
    DEFAULT_POST_STOP_PADDING,
    DEFAULT_TWIST_CONSTRAINTS,
    TAG_PRESET_DEFS,
    serialize_constraint_for_dnachisel,
)

__all__ = [
    "CUSTOM_TAG_VISUAL",
    "CodonTable",
    "DEFAULT_POST_STOP_PADDING",
    "DEFAULT_TWIST_CONSTRAINTS",
    "FIXED_START_DNA",
    "FIXED_STOP_DNA",
    "PlacedTag",
    "PrepareConfig",
    "PreparedRow",
    "SCHEMA_VERSION",
    "Segment",
    "ShortNameStrategy",
    "TAG_PRESET_DEFS",
    "build_row",
    "build_rows",
    "compute_short_names",
    "migrate_js_replacement",
    "optimize_sequences",
    "raw_sequence",
    "serialize_constraint_for_dnachisel",
    "tool_versions",
    "validate_mixed_sequence",
]
