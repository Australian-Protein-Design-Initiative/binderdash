"""Short-lived in-process store for structure-archive member lists.

``export_structures`` stashes the resolved files and hands back a URL. The GET
handler streams that list; the file paths never appear in the token or the URL.

ponytail: in-memory and single-process, so a stashed archive does not survive a
restart and would not be visible to a second worker. That is the same assumption
``cache.run_cache`` already makes.
"""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

DEFAULT_TTL_SECONDS = 600

# (expires_at, [(arcname, path), ...])
_LOCK = threading.Lock()
_ENTRIES: dict[str, tuple[float, List[Tuple[str, Path]]]] = {}


def _purge_expired(now: float) -> None:
    for key in [k for k, (expires, _) in _ENTRIES.items() if expires <= now]:
        _ENTRIES.pop(key, None)


def put(
    entries: Sequence[Tuple[str, Path]],
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Stash archive members and return an id."""
    download_id = secrets.token_urlsafe(12)
    stored = [(name, Path(path)) for name, path in entries]
    now = time.monotonic()
    with _LOCK:
        _purge_expired(now)
        _ENTRIES[download_id] = (now + ttl_seconds, stored)
    return download_id


def get(download_id: str) -> Optional[List[Tuple[str, Path]]]:
    now = time.monotonic()
    with _LOCK:
        _purge_expired(now)
        entry = _ENTRIES.get(download_id)
    if entry is None:
        return None
    _, members = entry
    return list(members)


def clear() -> None:
    with _LOCK:
        _ENTRIES.clear()
