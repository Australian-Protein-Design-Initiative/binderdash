import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..settings import settings, update_run_base_dirs
from ..version import app_version as _app_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


def _user_data_dir() -> str:
    try:
        from desktop.paths import user_data_dir

        return str(user_data_dir())
    except ImportError:
        return ""


def _validate_existing_dirs(dirs: List[str]) -> List[str]:
    cleaned: List[str] = []
    for raw in dirs:
        s = raw.strip()
        if not s:
            continue
        try:
            path = Path(s).expanduser().resolve()
        except (OSError, RuntimeError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid path {raw!r}: {e}",
            ) from e
        if not path.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Path is not a directory: {path}",
            )
        cleaned.append(str(path))
    return cleaned


class RunBaseDirsUpdate(BaseModel):
    run_base_dirs: List[str] = Field(default_factory=list)


@router.get("/info")
async def desktop_info():
    dirs = settings.run_base_dirs
    return {
        "desktop": True,
        "version": _app_version(),
        "data_dir": _user_data_dir(),
        "run_base_dirs": dirs,
        "needs_setup": len(dirs) == 0,
        "webview_api": True,
    }


@router.put("/run-base-dirs")
async def put_run_base_dirs(body: RunBaseDirsUpdate):
    cleaned = _validate_existing_dirs(body.run_base_dirs)
    update_run_base_dirs(cleaned)
    return {
        "run_base_dirs": settings.run_base_dirs,
        "needs_setup": len(settings.run_base_dirs) == 0,
    }


@router.post("/open-data-dir")
async def open_data_dir():
    data_dir = _user_data_dir()
    if not data_dir:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Desktop data directory is not available",
        )
    path = Path(data_dir)
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as e:
        logger.exception("Failed to open data directory %s", path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
    return {"ok": True, "data_dir": str(path)}
