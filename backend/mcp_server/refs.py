"""Resolving runs, designs, and structure files for the MCP surface.

The REST API hands out ``pdb_file`` as an absolute server path while every file
endpoint wants a bare basename, and a merged run can hold two designs with the same
``design_id`` distinguished only by ``source_path``. Both traps are handled here, once,
so no tool re-implements them and no agent ever sees a server path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

from . import errors
from .urls import absolute_url


def structure_filename(design: Dict[str, Any]) -> Optional[str]:
    """The basename the file endpoints accept, derived from the stored absolute path."""
    raw = (design.get("pdb_file") or "").strip()
    if not raw:
        return None
    return Path(raw).name


def structure_format(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    name = filename[:-3] if filename.endswith(".gz") else filename
    suffix = Path(name).suffix.lower().lstrip(".")
    return suffix or None


def structure_url(run_id: str, filename: Optional[str]) -> Optional[str]:
    """Relative path with no download token.

    Table rows use this. It is not fetchable by an MCP client; ``inspect_structures``
    and ``export_structures`` mint a tokenised absolute URL instead.
    """
    if not filename:
        return None
    return f"/api/runs/{quote(run_id, safe='')}/files/structure/{quote(filename, safe='')}"


def structure_download_url(run_id: str, filename: Optional[str]) -> Optional[str]:
    """Absolute URL for one structure file, with a short-lived download token."""
    if not filename:
        return None
    from ..download_tokens import mint_structure_file_token

    token = mint_structure_file_token(run_id, filename)
    path = (
        f"/api/runs/{quote(run_id, safe='')}/files/structure/{quote(filename, safe='')}"
        f"?download_token={quote(token, safe='')}"
    )
    return absolute_url(path)


def designs_json_url(run_id: str) -> str:
    """URL for the JSON design table, with a short-lived download token."""
    from ..download_tokens import mint_designs_download_token

    token = mint_designs_download_token(run_id, "json")
    path = f"/api/designs?run_ids={quote(run_id, safe='')}&download_token={quote(token, safe='')}"
    return absolute_url(path)


def designs_tsv_url(run_id: str) -> str:
    """URL for the TSV design table, with a short-lived download token."""
    from ..download_tokens import mint_designs_download_token

    token = mint_designs_download_token(run_id, "tsv")
    path = (
        f"/api/designs?run_ids={quote(run_id, safe='')}"
        f"&format=tsv&download_token={quote(token, safe='')}"
    )
    return absolute_url(path)


def decorate_structure_fields(design: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the server-path ``pdb_file`` with agent-usable derived fields."""
    filename = structure_filename(design)
    return {
        "structure_filename": filename,
        "structure_format": structure_format(filename),
        "structure_url": structure_url(str(design.get("run_id") or ""), filename),
    }


def known_run_ids() -> List[str]:
    from ..cache import run_cache

    return list(run_cache.keys())


def validate_run_ids(run_ids: Sequence[str]) -> List[str]:
    from ..cache import run_cache

    unknown = [r for r in run_ids if r not in run_cache]
    if unknown:
        errors.fail(
            errors.UNKNOWN_RUN,
            f"No such run_id: {', '.join(unknown)}. Call list_runs to see valid run_ids.",
        )
    return list(run_ids)


def is_merged_run(run_id: str) -> bool:
    from ..cache import get_run_metadata

    meta = get_run_metadata(run_id) or {}
    return bool(meta.get("merged") or meta.get("is_merged"))


def resolve_design(
    run_id: str, design_id: str, source_path: Optional[str] = None
) -> Dict[str, Any]:
    """One design, or a directed error.

    A merged run can contain the same ``design_id`` more than once — the REST API
    silently returns whichever it finds first. Here that is an error naming the
    candidate ``source_path`` values, so the agent can disambiguate.
    """
    from ..cache import ensure_designs_loaded_for_run_ids, designs_by_run_id

    ensure_designs_loaded_for_run_ids([run_id])
    rows = designs_by_run_id.get(run_id) or []
    matches = [r for r in rows if str(r.get("design_id")) == str(design_id)]
    if source_path:
        matches = [r for r in matches if str(r.get("source_path") or "") == source_path]

    if not matches:
        errors.fail(
            errors.DESIGN_NOT_FOUND,
            f"No design {design_id!r} in run {run_id!r}"
            + (f" with source_path {source_path!r}" if source_path else "")
            + ". Call query_designs for this run to list valid design_ids.",
        )
    if len(matches) > 1:
        candidates = sorted({str(m.get("source_path") or "") for m in matches})
        errors.fail(
            errors.AMBIGUOUS_DESIGN_REF,
            f"Design {design_id!r} appears {len(matches)} times in merged run {run_id!r}. "
            f"Re-call with source_path set to one of: {candidates}.",
        )
    return matches[0]
