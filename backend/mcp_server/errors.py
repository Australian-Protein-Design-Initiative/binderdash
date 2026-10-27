"""Error and warning codes for the MCP surface.

Design rule: anything that would otherwise produce a plausible-looking but wrong
answer becomes an error or a mandatory warning. Every error message ends with a
concrete next call, not just a diagnosis.
"""

from __future__ import annotations

from typing import Any, Dict, List, NoReturn, Optional

# Errors — the request cannot be answered.
UNKNOWN_COLUMN = "UNKNOWN_COLUMN"
UNKNOWN_RUN = "UNKNOWN_RUN"
AMBIGUOUS_DESIGN_REF = "AMBIGUOUS_DESIGN_REF"
DESIGN_NOT_FOUND = "DESIGN_NOT_FOUND"
NO_RANKABLE_METRICS = "NO_RANKABLE_METRICS"
RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
EMPTY_SELECTION = "EMPTY_SELECTION"
SEQUENCES_REQUIRED = "SEQUENCES_REQUIRED"
NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
PERSISTENCE_REQUIRED = "PERSISTENCE_REQUIRED"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
STRUCTURE_UNAVAILABLE = "STRUCTURE_UNAVAILABLE"
INVALID_TARGET_CONTACT_FILTER = "INVALID_TARGET_CONTACT_FILTER"
INVALID_PREPARE_REQUEST = "INVALID_PREPARE_REQUEST"

# Warnings — partial success the caller must be told about.
METRIC_NOT_APPLICABLE_FOR_METHOD = "METRIC_NOT_APPLICABLE_FOR_METHOD"
SORT_DIRECTION_OVERRIDE = "SORT_DIRECTION_OVERRIDE"
SEQUENCES_AUTO_EXTRACTED = "SEQUENCES_AUTO_EXTRACTED"
SEQUENCES_MISSING = "SEQUENCES_MISSING"
CHAIN_ROLES_AMBIGUOUS = "CHAIN_ROLES_AMBIGUOUS"
MERGED_RUN = "MERGED_RUN"
TRUNCATED = "TRUNCATED"
RESULT_SMALLER_THAN_BUDGET = "RESULT_SMALLER_THAN_BUDGET"
MIXED_METHODS = "MIXED_METHODS"
TARGET_CONTACTS_UNAVAILABLE = "TARGET_CONTACTS_UNAVAILABLE"


def fail(code: str, message: str) -> NoReturn:
    """Raise a ToolError carrying a machine-readable code."""
    from fastmcp.exceptions import ToolError

    raise ToolError(f"[{code}] {message}")


def warning(code: str, message: str, detail: Optional[Any] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        entry["detail"] = detail
    return entry


def nearest(name: str, candidates: List[str], limit: int = 10) -> List[str]:
    """Closest names, so an UNKNOWN_COLUMN error is actionable.

    Canonical metric names are always in scope even though they are not raw columns --
    a typo'd "iptmm" should suggest "iptm", which no list of raw column names contains.
    """
    import difflib

    from ..filtering.metrics import METRIC_ALIASES

    candidates = list(dict.fromkeys(list(METRIC_ALIASES.keys()) + list(candidates)))
    close = difflib.get_close_matches(name, candidates, n=limit, cutoff=0.5)
    if close:
        return close
    lowered = name.lower()
    return [c for c in candidates if lowered in c.lower()][:limit]
