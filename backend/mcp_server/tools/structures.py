"""Structure tools: inspect_structures, read_structure_file, export_structures."""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field

from .. import errors, refs
from ..descriptions import EXPORT_STRUCTURES, INSPECT_STRUCTURES, READ_STRUCTURE_FILE
from ..server import run_blocking

MAX_INSPECT = 24
DEFAULT_READ_BYTES = 20_000
MAX_READ_BYTES = 200_000


def _structure_path(run_id: str, design: Dict[str, Any]) -> Path:
    from ...cache import get_run_metadata
    from ...routers.files import _resolve_structure_path

    filename = refs.structure_filename(design)
    if not filename:
        errors.fail(
            errors.STRUCTURE_UNAVAILABLE,
            f"Design {design.get('design_id')!r} in run {run_id!r} has no structure file "
            "recorded.",
        )
    run = get_run_metadata(run_id) or {}
    path = _resolve_structure_path(run.get("pdb_files", []), filename, run.get("method"))
    if path is None or not path.is_file():
        errors.fail(
            errors.STRUCTURE_UNAVAILABLE,
            f"Structure {filename!r} for design {design.get('design_id')!r} is recorded "
            "but missing on disk.",
        )
    return path


def _inspect(
    designs: List[Dict[str, Any]], include_metrics: bool, include_sequences: bool
) -> Dict[str, Any]:
    from ...cache import get_run_metadata
    from ...filtering.chain_roles import resolve_chain_roles_cached
    from ...routers.designs import _structural_metrics_sync
    from ...schemas import StructuralMetricsRequest, TagPlacementItem
    from ...util.pdb_to_fasta import get_chain_sequences

    if len(designs) > MAX_INSPECT:
        errors.fail(
            errors.RESPONSE_TOO_LARGE,
            f"{len(designs)} designs requested; the maximum is {MAX_INSPECT} because "
            "each structure is analysed on demand. Split the call.",
        )

    warnings: List[Dict[str, Any]] = []
    resolved: List[Dict[str, Any]] = []
    for ref in designs:
        run_id = str(ref.get("run_id"))
        design = refs.resolve_design(run_id, str(ref.get("design_id")), ref.get("source_path"))
        path = _structure_path(run_id, design)
        run = get_run_metadata(run_id) or {}
        roles = resolve_chain_roles_cached(
            run_id, run.get("method") or "", run.get("pdb_files", [])
        )
        if roles.ambiguous_chain_ids:
            warnings.append(
                errors.warning(
                    errors.CHAIN_ROLES_AMBIGUOUS,
                    f"Run {run_id}: chains {roles.ambiguous_chain_ids} could not be "
                    "classified as binder or target; treat their metrics with caution.",
                )
            )
        entry: Dict[str, Any] = {
            "run_id": run_id,
            "design_id": design.get("design_id"),
            "method": design.get("method"),
            "binder_chain_ids": roles.binder_chain_ids,
            "target_chain_ids": roles.target_chain_ids,
            "ambiguous_chain_ids": roles.ambiguous_chain_ids,
            "size_bytes": path.stat().st_size,
            **refs.decorate_structure_fields(design),
        }
        entry["structure_url"] = refs.structure_download_url(
            run_id, entry.get("structure_filename")
        )
        if include_sequences:
            sequences = get_chain_sequences(str(path))
            entry["chain_sequences"] = sequences
            entry["chain_lengths"] = {c: len(s) for c, s in sequences.items()}
            binder = "".join(sequences.get(c, "") for c in roles.binder_chain_ids)
            entry["binder_sequence"] = binder
            entry["binder_length"] = len(binder)
        resolved.append(entry)
        ref["_design"] = design

    if include_metrics:
        request = StructuralMetricsRequest(
            designs=[
                TagPlacementItem(
                    run_id=e["run_id"],
                    design_id=str(e["design_id"]),
                    pdb_file=e["structure_filename"],
                    source_path=(d.get("_design") or {}).get("source_path"),
                )
                for e, d in zip(resolved, designs)
            ]
        )
        response = _structural_metrics_sync(request)
        by_key = {(r.run_id, r.design_id): r for r in response.results}
        for entry in resolved:
            row = by_key.get((entry["run_id"], str(entry["design_id"])))
            if row is None:
                continue
            entry["metrics"] = row.metrics or {}
            if row.error:
                warnings.append(
                    errors.warning(
                        errors.STRUCTURE_UNAVAILABLE,
                        f"Metrics for {entry['design_id']}: {row.error}",
                    )
                )

    from ..urls import public_base_url, with_relative_note

    return {
        "designs": resolved,
        "returned": len(resolved),
        "base_url": public_base_url(),
        "warnings": warnings,
        "note": with_relative_note(
            "binderdash_* metrics are computed by Binderdash from the as-generated "
            "structure, and are deliberately distinct from the pipeline's own reported "
            "values for similar quantities. structure_url is absolute when base_url is "
            "set and already includes a short-lived download_token — curl it with no "
            "API key. It expires in ~10 minutes."
        ),
    }


def _read_file(
    run_id: str, design_id: str, source_path: Optional[str], max_bytes: int
) -> Dict[str, Any]:
    design = refs.resolve_design(run_id, design_id, source_path)
    path = _structure_path(run_id, design)
    size = path.stat().st_size
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(str(path), "rt", errors="replace") as handle:  # type: ignore[operator]
        text = handle.read(max_bytes + 1)

    if len(text) > max_bytes:
        if size > MAX_READ_BYTES:
            # Raising max_bytes cannot help here, so do not suggest it.
            download = refs.structure_download_url(run_id, refs.structure_filename(design))
            errors.fail(
                errors.FILE_TOO_LARGE,
                f"The structure is {size} bytes, above the {MAX_READ_BYTES}-byte hard "
                "limit, so this tool cannot return it. Download it and parse it locally: "
                f"{download}. The link includes a short-lived download_token and needs "
                "no API key. Call inspect_structures for chains, sequences and interface "
                "metrics without the atoms.",
            )
        errors.fail(
            errors.FILE_TOO_LARGE,
            f"The structure is {size} bytes on disk, over your max_bytes={max_bytes}. "
            f"Re-call with max_bytes={min(size + 1, MAX_READ_BYTES)}, or call "
            "inspect_structures instead — it already returns chains, sequences and "
            "interface metrics without the atoms.",
        )
    return {
        "run_id": run_id,
        "design_id": design_id,
        "size_bytes": size,
        "content": text,
        **refs.decorate_structure_fields(design),
    }


def _archive_name(run_id: str, filename: str) -> str:
    from ...cache import get_run_metadata

    run = get_run_metadata(run_id) or {}
    project_id = run.get("project_id", "project") or "project"
    run_name = (run.get("metadata") or {}).get("name", "run") or "run"
    return f"{project_id}/{run_name}/{filename}"


def _export(designs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from urllib.parse import quote

    from ...download_tokens import DEFAULT_TTL_SECONDS, mint_structure_archive_token
    from ...structure_archive import put as stash_archive
    from ..urls import absolute_url, public_base_url, with_relative_note

    manifest = []
    members = []
    missing = []
    for ref in designs:
        run_id = str(ref.get("run_id"))
        design = refs.resolve_design(run_id, str(ref.get("design_id")), ref.get("source_path"))
        filename = refs.structure_filename(design)
        try:
            path = _structure_path(run_id, design)
        except Exception:
            missing.append({"run_id": run_id, "design_id": design.get("design_id")})
            continue
        if not filename:
            missing.append({"run_id": run_id, "design_id": design.get("design_id")})
            continue
        manifest.append(
            {
                "run_id": run_id,
                "design_id": design.get("design_id"),
                "structure_filename": filename,
            }
        )
        members.append((_archive_name(run_id, filename), path))

    warnings = (
        [
            errors.warning(
                errors.STRUCTURE_UNAVAILABLE,
                f"{len(missing)} designs have no structure file on disk and are not in "
                "the archive.",
                missing,
            )
        ]
        if missing
        else []
    )
    if not members:
        return {
            "download_url": None,
            "base_url": public_base_url(),
            "manifest": manifest,
            "count": 0,
            "expires_in_seconds": None,
            "warnings": warnings,
            "note": "No structure files were available to archive.",
        }

    download_id = stash_archive(members, ttl_seconds=DEFAULT_TTL_SECONDS)
    token = mint_structure_archive_token(download_id)
    path = (
        f"/api/pdbs/tar?download_id={quote(download_id, safe='')}"
        f"&download_token={quote(token, safe='')}"
    )
    return {
        "download_url": absolute_url(path),
        "base_url": public_base_url(),
        "manifest": manifest,
        "count": len(manifest),
        "expires_in_seconds": DEFAULT_TTL_SECONDS,
        "warnings": warnings,
        "note": with_relative_note(
            "GET download_url to receive the tar. No API key and no request body. "
            "The link expires in ~10 minutes and does not survive a server restart — "
            "call export_structures again if it fails."
        ),
    }


def register(mcp: Any) -> None:
    @mcp.tool(description=INSPECT_STRUCTURES)
    async def inspect_structures(
        designs: Annotated[
            List[Dict[str, Any]],
            Field(
                max_length=MAX_INSPECT,
                description=(
                    "Designs to inspect, each {run_id, design_id, source_path?}. "
                    "source_path is only needed for merged runs."
                ),
            ),
        ],
        include_metrics: Annotated[
            bool, Field(description="Compute interface metrics (slower, cached).")
        ] = True,
        include_sequences: Annotated[
            bool, Field(description="Include per-chain sequences.")
        ] = True,
    ) -> Dict[str, Any]:
        return await run_blocking(
            _inspect, designs, include_metrics, include_sequences, heavy=True
        )

    @mcp.tool(description=READ_STRUCTURE_FILE)
    async def read_structure_file(
        run_id: Annotated[str, Field(description="Run the design belongs to.")],
        design_id: Annotated[str, Field(description="Design whose structure to read.")],
        source_path: Annotated[
            Optional[str], Field(description="Disambiguates a design in a merged run.")
        ] = None,
        max_bytes: Annotated[
            int,
            Field(
                ge=1_000,
                le=MAX_READ_BYTES,
                description="Refuse to return a file larger than this.",
            ),
        ] = DEFAULT_READ_BYTES,
    ) -> Dict[str, Any]:
        return await run_blocking(_read_file, run_id, design_id, source_path, max_bytes)

    @mcp.tool(description=EXPORT_STRUCTURES)
    async def export_structures(
        designs: Annotated[
            List[Dict[str, Any]],
            Field(
                max_length=500,
                description="Designs to bundle, each {run_id, design_id, source_path?}.",
            ),
        ],
    ) -> Dict[str, Any]:
        return await run_blocking(_export, designs)
