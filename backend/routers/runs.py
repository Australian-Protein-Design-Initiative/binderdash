import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user_optional
from ..cache import get_run_metadata, refresh_designs_cache, run_cache
from ..path_policy import is_allowed_path, is_within_bases, normalised_path
from ..persistence import run_group_key
from ..persistence.factory import get_designs_repository
from ..run_discovery import (
    compute_primary_score_stats,
    discover_run_at,
    find_runs_recursive,
    load_run_table,
    parse_designs_from_run,
    resolve_target_count,
    resolve_trajectory_count,
)
from ..schemas import (
    IngestPreviewRequest,
    IngestRequest,
    InputTargetItem,
    InputTargetsResponse,
    ScanRequest,
)
from ..util.input_targets import list_input_targets
from ..auth_providers.base import AuthUser
from ..settings import settings
from ..util.profiling import Timer


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runs", tags=["runs"])


def _scan_runs_sync(request: ScanRequest) -> Dict[str, Any]:
    try:
        _scan_t = Timer(
            logger, "POST /scan", folders=len(request.folders)
        ).start()
        runs: List[Dict[str, Any]] = []
        for folder_path in request.folders:
            if not is_allowed_path(folder_path, settings.run_base_dirs):
                logger.warning(
                    "Skipping path not within allowed base directories: %s (bases=%s)",
                    folder_path,
                    settings.run_base_dirs,
                )
                continue
            path = Path(folder_path)
            if not path.exists() or not path.is_dir():
                logger.warning(
                    f"Skipping non-existent or non-directory path: {folder_path}"
                )
                continue
            _folder_t = Timer(
                logger, "POST /scan.folder", folder=folder_path
            ).start()
            folder_runs = find_runs_recursive(path)
            _folder_t.log(runs_found=len(folder_runs))
            runs.extend(folder_runs)
            logger.info(f"Found {len(folder_runs)} runs in {folder_path}")

        merged = merge_runs(runs)
        if not request.force_rescan_of_ingested:
            repo = get_designs_repository()
            if repo.is_enabled():
                before = len(merged)
                merged = [
                    r
                    for r in merged
                    if repo.get_run_by_group_key(run_group_key(r)) is None
                ]
                if before != len(merged):
                    logger.info(
                        "POST /scan omitted %s already-ingested run(s) (force_rescan_of_ingested=false)",
                        before - len(merged),
                    )
        _scan_t.log(runs=len(merged))
        return {"runs": merged}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in scan_runs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/scan")
async def scan_runs(
    request: ScanRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    return await asyncio.to_thread(_scan_runs_sync, request)


@router.post("/ingest-preview")
async def ingest_preview(
    body: IngestPreviewRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    repo = get_designs_repository()
    if not repo.is_enabled():
        return {"reingest": []}
    merged = merge_runs(body.runs)
    reingest: List[Dict[str, str]] = []
    seen: set[str] = set()
    for run in merged:
        gk = run_group_key(run)
        if gk in seen:
            continue
        if repo.get_run_by_group_key(gk) is None:
            continue
        seen.add(gk)
        name = (run.get("metadata") or {}).get("name", gk)
        reingest.append({"run_group_key": gk, "display_name": str(name)})
    return {"reingest": reingest}


def rediscover_runs(submitted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rebuild each submitted run from disk, taking only its folder path(s) from the client.

    The ingest body is the run dicts that ``/scan`` (or ``GET /api/runs``) returned, but
    nothing in them is trusted beyond ``path`` / ``merged_paths``. Persisting them as sent
    would let a caller store any ``pdb_files`` or ``results_table`` and then read those
    files back through the structure and table endpoints.
    """
    rebuilt: List[Dict[str, Any]] = []
    for run in submitted:
        if not isinstance(run, dict):
            raise HTTPException(status_code=400, detail="Each run must be an object")
        folders = run.get("merged_paths") or [run.get("path")]
        if not isinstance(folders, list):
            raise HTTPException(status_code=400, detail="merged_paths must be a list")
        for folder in folders:
            if not is_within_bases(folder, settings.run_base_dirs):
                raise HTTPException(
                    status_code=400,
                    detail=f"Run folder is not within the allowed base directories: {folder}",
                )
            path = Path(normalised_path(folder))
            found = discover_run_at(path) if path.is_dir() else None
            if found is None:
                raise HTTPException(
                    status_code=400, detail=f"No recognised run found at: {folder}"
                )
            rebuilt.append(found)
    return rebuilt


def _ingest_runs_sync(body: IngestRequest) -> Dict[str, Any]:
    repo = get_designs_repository()
    if not repo.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="DATABASE is not configured or persistence is disabled",
        )
    try:
        merged = merge_runs(rediscover_runs(body.runs))
        out: List[Dict[str, Any]] = []
        for run in merged:
            gk = run_group_key(run)
            existing = repo.get_run_by_group_key(gk)
            run_id = str(existing["run_id"]) if existing else str(uuid.uuid4())
            run["run_id"] = run_id
            designs = parse_designs_from_run(run)
            sig = run.get("signature") or {}
            df_table = load_run_table(run)
            stats = compute_primary_score_stats(df_table, sig)
            md = run.setdefault("metadata", {})
            if stats:
                md["primary_score_stats"] = stats
            rp = Path(str(run.get("path", "")))
            if rp.is_dir():
                tc = resolve_trajectory_count(rp, sig)
                if tc is not None:
                    md["trajectory_count"] = tc
                n_targets = resolve_target_count(rp, sig)
                if n_targets is not None and n_targets > 1:
                    md["target_count"] = n_targets
            repo.upsert_run_and_replace_designs(gk, run_id, run, designs)
            run_cache[run_id] = run
            out.append(run)
        refresh_designs_cache()
        return {"runs": merge_runs(out)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("ingest_runs failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/ingest")
async def ingest_runs(
    body: IngestRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    repo = get_designs_repository()
    if not repo.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="DATABASE is not configured or persistence is disabled",
        )
    return await asyncio.to_thread(_ingest_runs_sync, body)


def _metadata_trajectory_int(md: Optional[Dict[str, Any]]) -> Optional[int]:
    """Prefer ``trajectory_count``; fall back to legacy ``attempt_count`` in stored run_json."""
    if not md:
        return None
    for key in ("trajectory_count", "attempt_count"):
        v = md.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


def merge_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged_runs: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        project_id = run.get("project_id", "unknown")
        run_name = run.get("metadata", {}).get("name", "unknown")
        group_key = f"{project_id}/{run_name}"
        if group_key not in merged_runs:
            merged_runs[group_key] = run.copy()
            merged_runs[group_key]["merged_paths"] = [run["path"]]
            merged_runs[group_key]["merged_pdb_files"] = run.get("pdb_files", []).copy()
        else:
            existing = merged_runs[group_key]
            existing["merged_paths"].append(run["path"])
            existing["merged_pdb_files"].extend(run.get("pdb_files", []))
            existing["metadata"]["merged_count"] = len(existing["merged_paths"])
            existing["metadata"]["total_pdb_count"] = len(existing["merged_pdb_files"])
            a = _metadata_trajectory_int(existing.get("metadata"))
            b = _metadata_trajectory_int(run.get("metadata"))
            if a is not None or b is not None:
                ai = a if a is not None else 0
                bi = b if b is not None else 0
                existing["metadata"]["trajectory_count"] = ai + bi
    result: List[Dict[str, Any]] = []
    for run in merged_runs.values():
        run.pop("merged_pdb_files", None)
        result.append(run)
    return result


@router.get("")
async def list_runs(
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    try:
        all_runs = list(run_cache.values())
        merged = merge_runs(all_runs)
        return {"runs": merged}
    except Exception as e:
        logger.error(f"Error in list_runs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{run_id}")
async def delete_run(
    run_id: str, current_user: Optional[AuthUser] = Depends(get_current_user_optional)
):
    repo = get_designs_repository()
    in_cache = run_id in run_cache
    deleted_db = repo.is_enabled() and repo.delete_run(run_id)
    if not in_cache and not deleted_db:
        raise HTTPException(status_code=404, detail="Run not found")
    if in_cache:
        del run_cache[run_id]
    refresh_designs_cache()
    return {"message": "Run removed"}


@router.delete("")
async def clear_runs(
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    repo = get_designs_repository()
    if repo.is_enabled():
        for row in repo.list_run_records():
            repo.delete_run(row["run_id"])
    run_cache.clear()
    refresh_designs_cache()
    return {"message": "All runs cleared"}


@router.get("/{run_id}/input-targets", response_model=InputTargetsResponse)
async def get_input_targets(
    run_id: str,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    run_metadata = get_run_metadata(run_id)
    if not run_metadata:
        raise HTTPException(status_code=404, detail="Run not found")
    targets = list_input_targets(run_metadata)
    return InputTargetsResponse(
        targets=[InputTargetItem(id=t.id, label=t.label) for t in targets]
    )


@router.get("/{run_id}/table")
async def get_run_table(
    run_id: str, current_user: Optional[AuthUser] = Depends(get_current_user_optional)
):
    try:
        run_metadata = get_run_metadata(run_id)
        if not run_metadata:
            raise HTTPException(status_code=404, detail="Run not found")
        df = load_run_table(run_metadata)
        if df is None:
            raise HTTPException(
                status_code=404, detail="Results table not found or could not be loaded"
            )
        df_clean = df.replace({np.nan: None, np.inf: None, -np.inf: None})
        data_records = [
            {col: row[col] for col in df_clean.columns}
            for _, row in df_clean.iterrows()
        ]
        return {
            "columns": df.columns.tolist(),
            "data": data_records,
            "total_rows": len(df),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_run_table: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
