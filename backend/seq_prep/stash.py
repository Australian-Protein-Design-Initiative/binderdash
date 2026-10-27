"""Short-lived in-process store for prepare requests behind a download URL.

An MCP tool returns a URL rather than a few hundred constructs inline, and the
REST handler re-renders from the stashed request when that URL is fetched. The
output is never written to disk.

ponytail: in-memory and single-process, so a stashed request does not survive a
restart and would not be visible to a second worker. That is the same assumption
``cache.run_cache`` already makes. If Binderdash ever runs multi-worker, move
this to the designs repository or a shared cache.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TTL_SECONDS = 600

_LOCK = threading.Lock()
_ENTRIES: Dict[str, Tuple[float, Dict[str, Any], List[Dict[str, Any]]]] = {}


def _purge_expired(now: float) -> None:
    for key in [k for k, (expires, _, _) in _ENTRIES.items() if expires <= now]:
        _ENTRIES.pop(key, None)


def put(
    config: Dict[str, Any],
    designs: List[Dict[str, Any]],
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Stash a request and return its id."""
    prepare_id = secrets.token_urlsafe(12)
    now = time.monotonic()
    with _LOCK:
        _purge_expired(now)
        _ENTRIES[prepare_id] = (now + ttl_seconds, config, designs)
    return prepare_id


def get(prepare_id: str) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    now = time.monotonic()
    with _LOCK:
        _purge_expired(now)
        entry = _ENTRIES.get(prepare_id)
    if entry is None:
        return None
    _, config, designs = entry
    return config, designs


def clear() -> None:
    with _LOCK:
        _ENTRIES.clear()
