import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ..auth import get_current_user_optional
from ..schemas import (
    CodonTableDetailResponse,
    PrepareScriptRequest,
    PrepareSequencesRequest,
    PrepareSequencesResponse,
    TagPresetsResponse,
    CodonTableListResponse,
    CodonTableOption,
    DnaOptimizeRequest,
    DnaOptimizeResponse,
    DnaOptResultRow,
)
from ..auth_providers.base import AuthUser
from ..seq_prep import (
    CUSTOM_TAG_VISUAL,
    DEFAULT_POST_STOP_PADDING,
    DEFAULT_TWIST_CONSTRAINTS,
    TAG_PRESET_DEFS,
    PrepareConfig,
    build_rows,
)
from ..seq_prep import export as seq_export
from ..seq_prep import stash as prepare_stash
from ..seq_prep.config import SCHEMA_VERSION
from ..seq_prep.optimize import optimize_sequences, tool_versions
from ..seq_prep.script import generate_script, script_filename
from ..util.codon_tables import (
    CodonTableNotFoundError,
    CodonTableUpstreamError,
    list_builtin_codon_table_options,
    load_codon_table_detail,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sequences", tags=["sequences"])


@router.get("/codon-tables", response_model=CodonTableListResponse)
async def list_codon_tables(
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    try:
        raw_items = await asyncio.to_thread(list_builtin_codon_table_options)
    except Exception as e:
        logger.exception("list codon tables failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return CodonTableListResponse(
        items=[CodonTableOption(**item) for item in raw_items]
    )


@router.get("/codon-tables/{table_id}", response_model=CodonTableDetailResponse)
async def get_codon_table_detail(
    table_id: str,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    try:
        value, label, stop_codons, codons_by_aa = await asyncio.to_thread(
            load_codon_table_detail, table_id
        )
    except CodonTableNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Codon table not found: {table_id}"
        ) from None
    except CodonTableUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return CodonTableDetailResponse(
        value=value,
        label=label,
        stop_codons=stop_codons,
        codons_by_aa=codons_by_aa,
    )


@router.post("/optimize-dna", response_model=DnaOptimizeResponse)
async def optimize_dna_batch(
    request: DnaOptimizeRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    import time
    start_time = time.time()
    try:
        results_dict = await asyncio.to_thread(
            optimize_sequences,
            request.sequences,
            request.codon_table_id,
            [c.model_dump() for c in request.constraints],
            request.method,
            request.fixed,
            request.seeds,
        )
    except Exception as e:
        logger.exception("dna optimization batch failed")
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}") from e
        
    result_rows = [
        DnaOptResultRow(
            design_id=design_id,
            optimized_dna=res["optimized_dna"],
            error=res["error"],
            seed=res.get("seed"),
        )
        for design_id, res in results_dict.items()
    ]
    
    elapsed = float(time.time() - start_time)
    return DnaOptimizeResponse(
        results=result_rows, elapsed_seconds=elapsed, tool_versions=tool_versions()
    )



@router.get("/tag-presets", response_model=TagPresetsResponse)
async def list_tag_presets(
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    """Tag palette and optimisation defaults, served as data so the table has one home."""
    return TagPresetsResponse(
        presets=TAG_PRESET_DEFS,
        custom_visual=CUSTOM_TAG_VISUAL,
        default_constraints=DEFAULT_TWIST_CONSTRAINTS,
        default_post_stop_padding=DEFAULT_POST_STOP_PADDING,
    )


def _config_or_400(raw: dict) -> PrepareConfig:
    try:
        return PrepareConfig.from_payload(raw or {})
    except Exception as e:
        logger.exception("invalid prepare-sequences config")
        raise HTTPException(status_code=400, detail=f"Invalid config: {e}") from e


@router.post("/prepare", response_model=PrepareSequencesResponse)
async def prepare_sequences(
    request: PrepareSequencesRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    """Build constructs. The single implementation; the UI and MCP both call it."""
    cfg = _config_or_400(request.config)
    errors = cfg.validation_errors()
    if errors:
        return PrepareSequencesResponse(
            rows=[], validation_errors=errors, schema_version=SCHEMA_VERSION
        )
    try:
        rows = await asyncio.to_thread(
            build_rows,
            request.designs,
            cfg,
            optimized=request.optimized,
            errors=request.errors,
            seeds=request.seeds,
        )
    except Exception as e:
        logger.exception("prepare sequences failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return PrepareSequencesResponse(
        rows=[r.to_dict(include_segments=request.include_segments) for r in rows],
        validation_errors=[],
        schema_version=SCHEMA_VERSION,
    )


@router.post("/prepare/script", response_class=PlainTextResponse)
async def download_prepare_script(
    request: PrepareScriptRequest,
    current_user: Optional[AuthUser] = Depends(get_current_user_optional),
):
    """A standalone uv-runnable copy of the builder, configured as the UI is.

    POST rather than GET because the config is a whole document, too large for a
    query string.
    """
    cfg = _config_or_400(request.config)
    errors = cfg.validation_errors()
    if errors:
        raise HTTPException(
            status_code=400,
            detail="Configuration is not valid: " + "; ".join(errors),
        )
    try:
        source = await asyncio.to_thread(
            generate_script, cfg, include_self_check=request.include_self_check
        )
    except Exception as e:
        logger.exception("prepare script generation failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return PlainTextResponse(
        source,
        media_type="text/x-python",
        headers={"Content-Disposition": f'attachment; filename="{script_filename(cfg)}"'},
    )


_PREPARE_MEDIA_TYPES = {
    "json": "application/json",
    "tsv": "text/tab-separated-values",
    "csv": "text/csv",
    "twist": "text/csv",
    "fasta": "text/plain",
}


@router.get("/prepare/download", response_class=PlainTextResponse)
async def download_prepared(
    prepare_id: str = Query(..., description="Id returned by the prepare_sequences MCP tool"),
    fmt: str = Query("twist", alias="format"),
    download_token: str = Query(..., description="Short-lived token scoped to this id and format"),
):
    """Render a stashed prepare request. Nothing is written to disk.

    Deliberately not behind the session/API-key dependency: the token is the
    credential, scoped to one stashed request and one format, so an agent can
    curl it without the MCP bearer key.
    """
    from ..download_tokens import DownloadTokenError, verify_prepare_download_token

    try:
        verify_prepare_download_token(download_token, prepare_id=prepare_id, fmt=fmt)
    except DownloadTokenError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    entry = prepare_stash.get(prepare_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="This prepared set has expired or the server restarted; run the tool again.",
        )
    raw_config, designs = entry
    cfg = _config_or_400(raw_config)
    rows = await asyncio.to_thread(build_rows, designs, cfg)

    if fmt == "json":
        import json as _json

        body = _json.dumps([r.to_dict(include_segments=False) for r in rows], indent=2)
    else:
        try:
            body = seq_export.render(fmt, rows, cfg)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    suffix = "json" if fmt == "json" else seq_export.FORMATS[fmt][1]
    stem = seq_export.export_basename(cfg.order_name)
    return PlainTextResponse(
        body,
        media_type=_PREPARE_MEDIA_TYPES.get(fmt, "text/plain"),
        headers={"Content-Disposition": f'attachment; filename="{stem}.{suffix}"'},
    )
