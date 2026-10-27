import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from ..auth import get_current_user_optional
from ..auth_providers.base import AuthUser
from ..bundles import (
    BundleCaps,
    BundleCapsError,
    BundleDesignsRequest,
    BundleEstimate,
    BundleEstimateRequest,
    BundleSpec,
    PrepareSequencesBundleRequest,
    check_caps,
    estimate as estimate_spec,
    iter_bundle,
    spec_from_live_request,
    spec_from_prepare_request,
    write_bundle,
)
from ..bundles.writer import BuiltBundle, check_spool_space
from ..settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bundles", tags=["bundles"])


def current_caps() -> BundleCaps:
    return BundleCaps(
        max_structure_files=settings.bundle_max_structure_files,
        max_structure_bytes=settings.bundle_max_structure_bytes,
        max_total_bytes=settings.bundle_max_total_bytes,
    )


def bundle_response(built: BuiltBundle) -> StreamingResponse:
    """Stream the built zip with a real Content-Length so the browser can show progress."""
    return StreamingResponse(
        iter_bundle(built),
        media_type="application/zip",
        headers={
            "Content-Length": str(built.size_bytes),
            "Content-Disposition": f'attachment; filename="{built.filename}"',
            "X-Binderdash-Bundle-Id": built.manifest.bundle_id,
        },
        background=BackgroundTask(built.close),
    )


def _build_sync(spec: BundleSpec) -> BuiltBundle:
    result = check_caps(spec, current_caps())
    message = check_spool_space(result.estimated_zip_bytes)
    if message:
        raise OSError(message)
    return write_bundle(spec)


async def _build_and_respond(spec: BundleSpec) -> StreamingResponse:
    if not spec.rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No designs matched the request, so there is nothing to bundle.",
        )
    try:
        built = await asyncio.to_thread(_build_sync, spec)
    except BundleCapsError as e:
        raise HTTPException(
            # Literal 413: starlette renamed this constant to HTTP_413_CONTENT_TOO_LARGE
            # only in 0.41, and the pinned 0.38 has just the old spelling, so naming
            # either one raises AttributeError on the other.
            status_code=413,
            detail={"message": str(e), "estimate": e.estimate.model_dump()},
        ) from e
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE, detail=str(e)
        ) from e
    return bundle_response(built)


@router.post("/estimate", response_model=BundleEstimate)
async def estimate_bundle(
    body: BundleEstimateRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    """Pre-flight size check. Resolves and stats the structure files; reads none of them."""
    spec = await asyncio.to_thread(spec_from_live_request, body)
    return estimate_spec(spec, current_caps())


@router.post("/designs")
async def download_designs_bundle(
    body: BundleDesignsRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    spec = await asyncio.to_thread(spec_from_live_request, body)
    return await _build_and_respond(spec)


@router.post("/prepare-sequences")
async def download_prepare_sequences_bundle(
    body: PrepareSequencesBundleRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    spec = await asyncio.to_thread(spec_from_prepare_request, body)
    return await _build_and_respond(spec)
