import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user_optional
from ..schemas import (
    CodonTableDetailResponse,
    CodonTableListResponse,
    CodonTableOption,
    DnaOptimizeRequest,
    DnaOptimizeResponse,
    DnaOptResultRow,
)
from ..auth_providers.base import AuthUser
from ..util.dna_optimization import optimize_sequences
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
            request.frame,
        )
    except Exception as e:
        logger.exception("dna optimization batch failed")
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}") from e
        
    result_rows = [
        DnaOptResultRow(
            design_id=design_id, 
            optimized_dna=res["optimized_dna"],
            error=res["error"]
        )
        for design_id, res in results_dict.items()
    ]
    
    elapsed = float(time.time() - start_time)
    return DnaOptimizeResponse(results=result_rows, elapsed_seconds=elapsed)

