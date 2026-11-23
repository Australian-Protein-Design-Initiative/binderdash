"""Discovery tools: what runs exist, what the metrics mean, what columns are available."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import Field

from .. import errors, refs, vocab
from ..descriptions import DESCRIBE_COLUMNS, DESCRIBE_METHODS, LIST_RUNS
from ..server import run_blocking


def _design_counts_for(run_ids: List[str]) -> Dict[str, int]:
    """Prefer in-memory cache; otherwise a cheap DB GROUP BY; else structure_count later."""
    from ...cache import designs_by_run_id

    counts: Dict[str, int] = {}
    missing: List[str] = []
    for rid in run_ids:
        cached = designs_by_run_id.get(rid)
        if cached is not None:
            counts[rid] = len(cached)
        else:
            missing.append(rid)
    if not missing:
        return counts

    try:
        from ...persistence.factory import get_designs_repository

        repo = get_designs_repository()
    except RuntimeError:
        return counts

    if not repo.is_enabled():
        return counts

    for rid, n in repo.count_designs_by_run_id(missing).items():
        counts[rid] = n
    return counts


def _iso_timestamp(value: Union[str, float, int, None]) -> Optional[str]:
    """Normalise DB datetime strings or epoch seconds to ISO-8601 UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return None
    # SQLite datetime('now') is "YYYY-MM-DD HH:MM:SS" (UTC, no offset).
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1) + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _matches_filters(
    row: Dict[str, Any],
    *,
    methods: Optional[List[str]],
    project_id: Optional[str],
    name_contains: Optional[str],
    target_contains: Optional[str],
) -> bool:
    if methods:
        allowed = {m.strip().lower() for m in methods if m and m.strip()}
        if allowed and str(row.get("method") or "").lower() not in allowed:
            return False
    if project_id is not None and project_id != "":
        if str(row.get("project_id") or "") != project_id:
            return False
    if name_contains:
        needle = name_contains.lower()
        if needle not in str(row.get("run_name") or "").lower():
            return False
    if target_contains:
        needle = target_contains.lower()
        if needle not in str(row.get("target") or "").lower():
            return False
    return True


def _summarise_runs(
    run_ids: Optional[List[str]],
    methods: Optional[List[str]],
    project_id: Optional[str],
    name_contains: Optional[str],
    target_contains: Optional[str],
) -> Dict[str, Any]:
    from ...cache import run_cache

    if run_ids:
        refs.validate_run_ids(run_ids)
        selected_ids = list(run_ids)
    else:
        selected_ids = list(run_cache.keys())

    # Runs sharing a project/name pair are separate folders of one campaign; the REST
    # API silently merges them, which is where duplicate design_ids come from.
    groups: Dict[str, List[str]] = {}
    for rid, meta in run_cache.items():
        name = (meta.get("metadata") or {}).get("name") or meta.get("run_name") or "unknown"
        groups.setdefault(f"{meta.get('project_id', 'unknown')}/{name}", []).append(rid)

    counts = _design_counts_for(selected_ids)

    rows: List[Dict[str, Any]] = []
    for rid in selected_ids:
        meta = run_cache.get(rid)
        if meta is None:
            continue
        metadata = meta.get("metadata") or {}
        name = metadata.get("name") or meta.get("run_name") or "unknown"
        group = f"{meta.get('project_id', 'unknown')}/{name}"
        structure_count = len(meta.get("pdb_files") or [])
        # Cache or DB count when available; otherwise structure_count is the best
        # proxy without loading every design row into memory (no-DB / desktop).
        design_count = counts[rid] if rid in counts else structure_count
        row = {
            "run_id": rid,
            "project_id": meta.get("project_id"),
            "run_name": name,
            "method": meta.get("method"),
            "submethod": meta.get("submethod"),
            "target": metadata.get("target") or metadata.get("target_name"),
            "structure_count": structure_count,
            "design_count": design_count,
            "ingested_at": _iso_timestamp(meta.get("ingested_at")),
            "folder_mtime": _iso_timestamp(meta.get("folder_mtime")),
            "merge_group": group if len(groups[group]) > 1 else None,
            "designs_json_url": refs.designs_json_url(rid),
            "designs_tsv_url": refs.designs_tsv_url(rid),
        }
        if not _matches_filters(
            row,
            methods=methods,
            project_id=project_id,
            name_contains=name_contains,
            target_contains=target_contains,
        ):
            continue
        rows.append(row)

    from ..urls import public_base_url, with_relative_note

    rows.sort(key=lambda r: (str(r["project_id"]), str(r["run_name"])))
    return {
        "runs": rows,
        "total_runs": len(rows),
        "methods": sorted({str(r["method"]) for r in rows if r["method"]}),
        "base_url": public_base_url(),
        "note": with_relative_note(
            "designs_json_url / designs_tsv_url include a short-lived download_token "
            "scoped to that run and format — curl them without the MCP API key "
            "(tokens expire in ~10 minutes). They are absolute when base_url is set. "
            "Prefer that over pulling every row through MCP."
        ),
    }


def _columns_for(run_ids: List[str], include_raw: bool) -> Dict[str, Any]:
    from ...filtering.service import compute_available_columns

    refs.validate_run_ids(run_ids)
    columns = compute_available_columns(run_ids)
    entries: List[Dict[str, Any]] = []
    for info in columns:
        payload = info.model_dump() if hasattr(info, "model_dump") else dict(info)
        name = payload.get("name") or payload.get("column")
        canonical = vocab.is_canonical(str(name))
        if not include_raw and not canonical:
            continue
        payload["is_canonical"] = canonical
        payload["higher_is_better"] = vocab.higher_is_better(str(name))
        entries.append(payload)
    return {
        "run_ids": run_ids,
        "columns": entries,
        "returned": len(entries),
        "total_available": len(columns),
        "include_raw": include_raw,
        "warnings": []
        if include_raw
        else [
            errors.warning(
                errors.TRUNCATED,
                "Canonical metrics only. Call again with include_raw=true for every "
                f"raw column ({len(columns)} in total).",
            )
        ],
    }


def register(mcp: Any) -> None:
    @mcp.tool(description=LIST_RUNS)
    async def list_runs(
        run_ids: Annotated[
            Optional[List[str]],
            Field(description="If set, only these runs are returned."),
        ] = None,
        methods: Annotated[
            Optional[List[str]],
            Field(
                description="Filter to these method IDs (bindcraft, bindcraft2, rfd3, rfd4_proteina, boltzgen, …)."
            ),
        ] = None,
        project_id: Annotated[
            Optional[str],
            Field(description="Exact project_id match."),
        ] = None,
        name_contains: Annotated[
            Optional[str],
            Field(description="Case-insensitive substring match on run_name."),
        ] = None,
        target_contains: Annotated[
            Optional[str],
            Field(description="Case-insensitive substring match on target."),
        ] = None,
    ) -> Dict[str, Any]:
        return await run_blocking(
            _summarise_runs, run_ids, methods, project_id, name_contains, target_contains
        )

    @mcp.tool(description=DESCRIBE_METHODS)
    async def describe_methods() -> Dict[str, Any]:
        from ...cache import run_cache

        methods = sorted({str(m.get("method")) for m in run_cache.values() if m.get("method")})
        return {
            "metrics": vocab.metric_catalogue(),
            "methods": {
                method: {
                    "primary_score": vocab.primary_score_for_method(method),
                }
                for method in methods
            },
            "ranking_presets": vocab.RANKING_PRESETS,
            "note": (
                "higher_is_better is per metric, not global: iptm/ptm are higher-is-better, "
                "pae_interaction/rmsd are lower-is-better."
            ),
        }

    @mcp.tool(description=DESCRIBE_COLUMNS)
    async def describe_columns(
        run_ids: Annotated[List[str], Field(description="Runs to describe, from list_runs.")],
        include_raw: Annotated[
            bool,
            Field(description="Include every raw per-method column, not just canonical metrics."),
        ] = False,
    ) -> Dict[str, Any]:
        return await run_blocking(_columns_for, run_ids, include_raw)
