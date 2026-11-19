import asyncio
import gzip
import logging
import os
import stat
import tarfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from ..auth import (
    get_current_user_optional,
    get_current_user_optional_with_query,
)
from ..download_tokens import (
    DownloadTokenError,
    verify_structure_archive_token,
    verify_structure_file_token,
)
from ..structure_archive import get as get_structure_archive
from ..cache import get_run_metadata
from ..path_policy import is_allowed_path
from ..auth_providers.base import AuthUser
from ..settings import settings
from ..schemas import PdbTarRequest
from ..util.input_targets import find_input_target_by_id
from ..util.structure_paths import resolve_structure_path
from ..util.superpose import (
    PDB_ID_PATTERN,
    fetch_reference_structure,
    parse_reference_chain_list,
    superpose_reference_onto_design,
    superpose_reference_path_onto_design,
)


# Router for run file endpoints
router = APIRouter(prefix="/api/runs", tags=["files"])

_REFERENCE_CACHE: "OrderedDict[str, Tuple[bytes, Dict[str, Any]]]" = OrderedDict()
_REFERENCE_CACHE_MAX = 64


def _reference_cache_get(key: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
    if key not in _REFERENCE_CACHE:
        return None
    val = _REFERENCE_CACHE.pop(key)
    _REFERENCE_CACHE[key] = val
    return val


def _reference_cache_put(key: str, payload: Tuple[bytes, Dict[str, Any]]) -> None:
    if key in _REFERENCE_CACHE:
        del _REFERENCE_CACHE[key]
    _REFERENCE_CACHE[key] = payload
    while len(_REFERENCE_CACHE) > _REFERENCE_CACHE_MAX:
        _REFERENCE_CACHE.popitem(last=False)


def _sync_aligned_reference(
    run_id: str,
    align_filename: str,
    mode: str,
    source: Optional[str],
    input_target_id: Optional[str],
    reference_chains: Optional[str],
) -> Tuple[bytes, Dict[str, Any]]:
    run_metadata = get_run_metadata(run_id)
    if not run_metadata:
        raise FileNotFoundError("Run not found")

    structure_files = run_metadata.get("pdb_files", [])
    meth = run_metadata.get("method")
    design_path = _resolve_structure_path(structure_files, align_filename, meth)
    if design_path is None or not design_path.exists():
        raise FileNotFoundError("Design structure not found")

    chain_key = (reference_chains or "").strip()
    cache_key = (
        f"{run_id}\x1f{align_filename}\x1f{mode}\x1f{source or ''}\x1f{input_target_id or ''}\x1f{chain_key}\x1fmmcif"
    )
    ref_chain_ids = parse_reference_chain_list(reference_chains)
    cached = _reference_cache_get(cache_key)
    if cached is not None:
        return cached

    mode_l = (mode or "manual").lower()
    if mode_l == "manual":
        if not source or not source.strip():
            raise ValueError("manual mode requires non-empty source")
        s = source.strip()
        if not (
            PDB_ID_PATTERN.match(s)
            or s.lower().startswith(("http://", "https://"))
        ):
            raise ValueError(
                "source must be a 4-character PDB ID, an http(s) URL to a structure file, "
                "or a PDBTM entry / JSON URL"
            )
        try:
            ref_bytes, fmt, pdbtm_membrane = fetch_reference_structure(s)
        except ValueError:
            raise
        except requests.RequestException as e:
            raise ValueError(f"Failed to download reference: {e}") from e
        out, metrics = superpose_reference_onto_design(
            ref_bytes, fmt, design_path, pdbtm_membrane, ref_chain_ids
        )
    elif mode_l == "input_target":
        if not input_target_id:
            raise ValueError("input_target mode requires input_target_id")
        info = find_input_target_by_id(run_metadata, input_target_id)
        if info is None:
            raise ValueError("Unknown input_target_id")
        if not info.path.is_file():
            raise ValueError("Input target file not found on disk")
        out, metrics = superpose_reference_path_onto_design(
            info.path, design_path, ref_chain_ids
        )
    else:
        raise ValueError("mode must be manual or input_target")

    _reference_cache_put(cache_key, (out, metrics))
    return out, metrics


# Implementation lives in util/structure_paths so non-router code can use it; the
# private alias is kept because several modules already import it from here.
_resolve_structure_path = resolve_structure_path


def _media_type_for_structure_path(structure_path: Path) -> str:
    if structure_path.suffix.lower() == ".gz":
        inner = Path(structure_path.stem).suffix.lower()
        if inner == ".cif":
            return "chemical/x-mmcif"
        if inner == ".pdb":
            return "chemical/x-pdb"
        return "application/octet-stream"
    ext = structure_path.suffix.lower()
    if ext == ".cif":
        return "chemical/x-mmcif"
    if ext == ".pdb":
        return "chemical/x-pdb"
    return "application/octet-stream"


@router.get("/{run_id}/files/pdb/{filename}")
async def get_pdb_file(
    run_id: str,
    filename: str,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional_with_query),
    ):
    """Legacy endpoint for serving PDB files; kept for backwards compatibility."""
    try:
        run_metadata = get_run_metadata(run_id)
        if not run_metadata:
            raise HTTPException(status_code=404, detail="Run not found")

        pdb_files = run_metadata.get("pdb_files", [])
        method = run_metadata.get("method")
        pdb_path = _resolve_structure_path(pdb_files, filename, method)
        if pdb_path is None:
            raise HTTPException(status_code=404, detail="PDB file not found in run")

        if not pdb_path.exists():
            raise HTTPException(status_code=404, detail="PDB file not found on disk")

        if pdb_path.suffix.lower() == ".gz":
            media_type = _media_type_for_structure_path(pdb_path)
            with gzip.open(str(pdb_path), "rb") as gz_f:
                content = gz_f.read()
            return Response(content=content, media_type=media_type)

        return FileResponse(
            str(pdb_path), media_type="chemical/x-pdb", filename=filename
        )
    except HTTPException:
        raise
    except Exception as e:
        from logging import getLogger

        getLogger(__name__).error(f"Error in get_pdb_file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _authorize_structure_file(
    request: Request,
    run_id: str,
    filename: str,
    download_token: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
) -> Optional[AuthUser]:
    """Session, API key, or a download token scoped to this exact file.

    A present ``download_token`` is the only credential considered. Falling
    through to the session cookie would let a query param skip CSRF on a
    cookie-authenticated browser request.
    """
    if download_token:
        try:
            verify_structure_file_token(download_token, run_id=run_id, filename=filename)
        except DownloadTokenError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        return None
    return await get_current_user_optional_with_query(request, token=token)


@router.get("/{run_id}/files/structure/{filename}")
async def get_structure_file(
    run_id: str,
    filename: str,
    current_user: Optional[AuthUser] = Depends(_authorize_structure_file),
):
    """Serve a structure file (PDB or mmCIF) for a run."""
    try:
        run_metadata = get_run_metadata(run_id)
        if not run_metadata:
            raise HTTPException(status_code=404, detail="Run not found")

        structure_files = run_metadata.get("pdb_files", [])
        method = run_metadata.get("method")
        structure_path = _resolve_structure_path(structure_files, filename, method)

        if structure_path is None:
            raise HTTPException(status_code=404, detail="Structure file not found in run")
        if not structure_path.exists():
            raise HTTPException(status_code=404, detail="Structure file not found on disk")

        media_type = _media_type_for_structure_path(structure_path)
        if structure_path.suffix.lower() == ".gz":
            with gzip.open(str(structure_path), "rb") as gz_f:
                content = gz_f.read()
            return Response(content=content, media_type=media_type)

        return FileResponse(str(structure_path), media_type=media_type, filename=filename)
    except HTTPException:
        raise
    except Exception as e:
        from logging import getLogger

        getLogger(__name__).error(f"Error in get_structure_file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{run_id}/files/reference")
async def get_aligned_reference_structure(
    run_id: str,
    align_filename: str,
    mode: str = "manual",
    source: Optional[str] = None,
    input_target_id: Optional[str] = None,
    reference_chains: Optional[str] = Query(
        None,
        description="Optional comma/space-separated reference chain IDs (limits TM-align and returned structure)",
    ),
    current_user: Optional[AuthUser] = Depends(get_current_user_optional_with_query),
):
    """Return the reference structure superimposed onto the given design (TM-align, mmCIF)."""
    try:
        content, metrics = await asyncio.to_thread(
            _sync_aligned_reference,
            run_id,
            align_filename,
            mode,
            source,
            input_target_id,
            reference_chains,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logging.getLogger(__name__).error(f"Error in get_aligned_reference_structure: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    headers = {
        "X-Binderdash-TM-Norm-Design": f"{metrics['tm_score_norm_design']:.6f}",
        "X-Binderdash-TM-Norm-Reference": f"{metrics['tm_score_norm_reference']:.6f}",
        "X-Binderdash-RMSD": f"{metrics['rmsd']:.6f}",
        "X-Binderdash-Aligned-Length": str(int(metrics["aligned_length"])),
    }
    mem = metrics.get("membrane")
    if isinstance(mem, dict):
        p1 = mem.get("plane1")
        p2 = mem.get("plane2")
        n = mem.get("normal")
        c = mem.get("centroid")
        rad = mem.get("radius")
        if (
            isinstance(p1, (list, tuple))
            and len(p1) == 3
            and isinstance(p2, (list, tuple))
            and len(p2) == 3
            and isinstance(n, (list, tuple))
            and len(n) == 3
            and isinstance(c, (list, tuple))
            and len(c) == 3
            and isinstance(rad, (int, float))
        ):
            headers["X-Binderdash-Membrane-Plane1"] = f"{float(p1[0]):.6f},{float(p1[1]):.6f},{float(p1[2]):.6f}"
            headers["X-Binderdash-Membrane-Plane2"] = f"{float(p2[0]):.6f},{float(p2[1]):.6f},{float(p2[2]):.6f}"
            headers["X-Binderdash-Membrane-Normal"] = f"{float(n[0]):.6f},{float(n[1]):.6f},{float(n[2]):.6f}"
            headers["X-Binderdash-Membrane-Centroid"] = f"{float(c[0]):.6f},{float(c[1]):.6f},{float(c[2]):.6f}"
            headers["X-Binderdash-Membrane-Radius"] = f"{float(rad):.6f}"
    return Response(content=content, media_type="chemical/x-mmcif", headers=headers)


# Router for PDB tar streaming
pdbs_router = APIRouter(prefix="/api/pdbs", tags=["pdbs"])


def stream_tar_archive(file_entries: List[Tuple[str, Path]]):
    for arcname, fpath in file_entries:
        try:
            fstat = fpath.stat()
            if not stat.S_ISREG(fstat.st_mode):
                logging.getLogger(__name__).warning(
                    f"Skipping non-regular file: {fpath}"
                )
                continue
            tarinfo = tarfile.TarInfo(name=arcname)
            tarinfo.size = fstat.st_size
            tarinfo.mtime = int(fstat.st_mtime)
            tarinfo.mode = fstat.st_mode
            tarinfo.type = tarfile.REGTYPE
            yield tarinfo.tobuf()
            with fpath.open("rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
            padding_size = (512 - (fstat.st_size % 512)) % 512
            if padding_size > 0:
                yield b"\0" * padding_size
        except FileNotFoundError:
            logging.getLogger(__name__).warning(
                f"File not found for tar archive: {fpath}"
            )
            continue
        except Exception as e:
            logging.getLogger(__name__).error(
                f"Error processing file {fpath} for tar: {e}"
            )
            continue
    yield b"\0" * 1024


@pdbs_router.get("/tar")
async def download_stashed_pdbs_tar(
    download_id: Optional[str] = Query(None),
    download_token: Optional[str] = Query(None),
):
    """Stream a tar stashed by the MCP ``export_structures`` tool.

    The member list lives server-side. The token is bound to ``download_id``
    and is the only credential this route accepts.
    """
    if not download_id or not download_token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        verify_structure_archive_token(download_token, download_id=download_id)
    except DownloadTokenError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    members = get_structure_archive(download_id)
    if not members:
        raise HTTPException(
            status_code=404,
            detail="Archive expired or unknown. Call export_structures again.",
        )
    headers = {"Content-Disposition": "attachment; filename=designs_pdbs.tar"}
    return StreamingResponse(
        stream_tar_archive(members),
        media_type="application/x-tar",
        headers=headers,
    )


@pdbs_router.post("/tar")
async def download_pdbs_tar(
    request: PdbTarRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    try:
        if not request.items:
            raise HTTPException(status_code=400, detail="No items provided")
        file_entries: List[Tuple[str, Path]] = []
        for item in request.items:
            run = get_run_metadata(item.run_id)
            if not run:
                logging.getLogger(__name__).warning(
                    f"Run not found for tar request: {item.run_id}"
                )
                continue
            pdb_paths = run.get("pdb_files", [])
            matched = _resolve_structure_path(
                pdb_paths, item.filename, run.get("method")
            )
            if matched and matched.exists():
                project_id = run.get("project_id", "project") or "project"
                run_name = run.get("metadata", {}).get("name", "run") or "run"
                arcname = f"{project_id}/{run_name}/{item.filename}"
                file_entries.append((arcname, matched))
            else:
                logging.getLogger(__name__).warning(
                    f"Requested PDB not found in run {item.run_id}: {item.filename}"
                )
        if not file_entries:
            raise HTTPException(status_code=404, detail="No valid PDB files found")
        headers = {"Content-Disposition": "attachment; filename=designs_pdbs.tar"}
        return StreamingResponse(
            stream_tar_archive(file_entries),
            media_type="application/x-tar",
            headers=headers,
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.getLogger(__name__).error(f"Error creating PDBs tar: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Router for directory tree browsing
tree_router = APIRouter(tags=["tree"])


@tree_router.get("/api/tree")
async def get_tree(
    path: str = "",
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    logging.getLogger(__name__).info(
        f"get_tree called with path: '{path}', run_base_dirs: {settings.run_base_dirs}"
    )
    try:
        if not path:
            folders = []
            for base_dir in settings.run_base_dirs:
                if not base_dir.strip():
                    continue
                try:
                    resolved = str(Path(base_dir).expanduser().resolve())
                except (OSError, RuntimeError):
                    continue
                if os.path.exists(resolved) and os.path.isdir(resolved):
                    folders.append(
                        {
                            "name": os.path.basename(resolved),
                            "path": resolved,
                            "has_children": True,
                        }
                    )
            if not folders:
                logging.getLogger(__name__).warning(
                    "No usable base directories configured in RUN_BASE_DIRS"
                )
            return {"folders": folders}
        else:
            # Containment first, so the error for a path outside the bases does not
            # reveal whether it exists.
            if not is_allowed_path(path, settings.run_base_dirs):
                raise ValueError(f"Path not within allowed base directories: {path}")
            if not os.path.exists(path) or not os.path.isdir(path):
                raise ValueError(f"Path does not exist or is not a directory: {path}")

            folders = []
            logging.getLogger(__name__).info(f"Listing contents of directory: {path}")
            try:
                items = os.listdir(path)
                logging.getLogger(__name__).info(
                    f"Found {len(items)} items in {path}: {items[:10]}..."
                )
                for item in items:
                    item_path = os.path.join(path, item)
                    if os.path.isdir(item_path) or os.path.islink(item_path):
                        has_children = False
                        try:
                            if os.path.islink(item_path):
                                target_path = os.path.realpath(item_path)
                                if os.path.isdir(target_path):
                                    has_children = any(
                                        os.path.isdir(
                                            os.path.join(target_path, subitem)
                                        )
                                        for subitem in os.listdir(target_path)
                                    )
                            else:
                                has_children = any(
                                    os.path.isdir(os.path.join(item_path, subitem))
                                    for subitem in os.listdir(item_path)
                                )
                        except (PermissionError, OSError):
                            has_children = True

                        folders.append(
                            {
                                "name": item,
                                "path": item_path,
                                "has_children": has_children,
                            }
                        )
            except PermissionError:
                logging.getLogger(__name__).warning(
                    f"Permission denied accessing directory: {path}"
                )
                return {"folders": []}

            return {"folders": folders}
    except Exception as e:
        logging.getLogger(__name__).error(f"Error in get_tree: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
