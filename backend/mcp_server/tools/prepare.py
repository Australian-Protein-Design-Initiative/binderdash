"""Build order-ready constructs from designs: tags, stops, padding, short names.

Returns a download URL rather than the constructs, because a few hundred of them
is a large tool result and the usual next step is handing the file to a vendor
rather than reading every sequence.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import quote

from pydantic import Field

from .. import errors, refs
from ..urls import absolute_url, public_base_url, with_relative_note

PREPARE_SEQUENCES = """\
Prepare order-ready sequences for designs: add N-/C-terminal affinity tags and
linkers, stop codons, post-stop padding, and generate vendor short names.

If `config` turns DNA on, the DNA is a plain reverse translation using the
chosen codon table - the same thing the UI shows before Optimize DNA is pressed.
This tool does not run DnaChisel, because constraint solving takes minutes for a
few hundred designs. For constraint-checked DNA to actually order, use the
Prepare Sequences tab or the Python script it generates.

Which end a tag goes on is read from each design's `tag` column (N or C), which
Binderdash computes from the structure. Designs with no `tag` are skipped unless
`default_tag` is set.

Returns counts, warnings and a short-lived `download_url`. Fetch that URL to get
the constructs in the requested format; it needs no API key. Nothing is written
to disk, and the URL expires in 10 minutes.

`config` accepts a Prepare Sequences payload (the same JSON a download bundle
records, and the CONFIG block of a downloaded script), so a saved configuration
can be replayed exactly. Omit it for the defaults: His-tag-free, single stop,
no padding.
"""


def _default_config(overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    config: Dict[str, Any] = dict(overrides or {})
    config.setdefault("stop_options", {})
    return config


def register(mcp: Any) -> None:
    @mcp.tool(description=PREPARE_SEQUENCES)
    async def prepare_sequences(
        run_ids: Annotated[List[str], Field(description="Runs to take designs from.")],
        design_ids: Annotated[
            Optional[List[str]],
            Field(description="Only these designs. Omit for every design in the runs."),
        ] = None,
        config: Annotated[
            Optional[Dict[str, Any]],
            Field(
                description=(
                    "Prepare Sequences payload: n_tags, c_tags (a tag with "
                    "always=true is added to every design, ignoring its tag end), "
                    "stop_options, short_name_strategy, "
                    "codon_table_id, optimization_constraints. Omit for defaults."
                )
            ),
        ] = None,
        format: Annotated[
            str,
            Field(description="twist, fasta, tsv, csv or json. Default twist (vendor order CSV)."),
        ] = "twist",
        good_only: Annotated[
            bool, Field(description="Only designs marked good.")
        ] = False,
        default_tag: Annotated[
            Optional[str],
            Field(description="Tag zone (N or C) for designs with no tag column value."),
        ] = None,
    ) -> Dict[str, Any]:
        from ...cache import designs_by_run_id, ensure_designs_loaded_for_run_ids
        from ...download_tokens import mint_prepare_download_token
        from ...seq_prep import PrepareConfig, build_rows, raw_sequence
        from ...seq_prep import stash as prepare_stash

        valid_formats = {"twist", "fasta", "tsv", "csv", "json"}
        if format not in valid_formats:
            errors.fail(
                errors.INVALID_PREPARE_REQUEST,
                f"format must be one of {sorted(valid_formats)}, got {format!r}.",
            )

        run_ids = refs.validate_run_ids(run_ids)
        ensure_designs_loaded_for_run_ids(run_ids)

        wanted = set(design_ids) if design_ids else None
        designs: List[Dict[str, Any]] = []
        for run_id in run_ids:
            for row in designs_by_run_id.get(run_id) or []:
                if wanted is not None and str(row.get("design_id")) not in wanted:
                    continue
                if good_only and row.get("good") is not True:
                    continue
                designs.append(dict(row))

        if not designs:
            errors.fail(
                errors.EMPTY_SELECTION,
                "No designs matched. Check run_ids and design_ids with query_designs, "
                "or clear good_only.",
            )

        if default_tag:
            designs = [
                {**d, "tag": (str(d.get("tag") or "").strip() or default_tag)} for d in designs
            ]

        skipped_no_tag = [
            str(d.get("design_id"))
            for d in designs
            if str(d.get("tag") or "").strip().upper() not in ("N", "C")
        ]
        skipped_no_sequence = [
            str(d.get("design_id")) for d in designs if not raw_sequence(d)
        ]
        usable = [
            d
            for d in designs
            if str(d.get("tag") or "").strip().upper() in ("N", "C") and raw_sequence(d)
        ]
        if not usable:
            errors.fail(
                errors.EMPTY_SELECTION,
                f"None of the {len(designs)} designs are usable: "
                f"{len(skipped_no_tag)} have no N/C tag, "
                f"{len(skipped_no_sequence)} have no sequence. "
                "Set default_tag, or use extract_sequences first.",
            )

        payload = _default_config(config)
        payload["good_only"] = good_only
        cfg = PrepareConfig.from_payload(payload)
        config_errors = cfg.validation_errors()
        if config_errors:
            errors.fail(errors.INVALID_PREPARE_REQUEST, "; ".join(config_errors))

        rows = build_rows(usable, cfg)

        prepare_id = prepare_stash.put(payload, usable)
        token = mint_prepare_download_token(prepare_id, format)  # type: ignore[arg-type]
        download_url = absolute_url(
            f"/api/sequences/prepare/download?prepare_id={quote(prepare_id, safe='')}"
            f"&format={quote(format, safe='')}&download_token={quote(token, safe='')}"
        )

        row_warnings = sorted({w for r in rows for w in r.warnings})
        if cfg.dna_mode:
            row_warnings.append(
                "DNA is a reverse translation, not codon-optimised: no GC, hairpin or "
                "restriction-site constraints were applied. Use the Prepare Sequences "
                "tab or its downloaded script before ordering."
            )
        return {
            "prepared": len(rows),
            "skipped_no_tag": skipped_no_tag[:20],
            "skipped_no_sequence": skipped_no_sequence[:20],
            "warnings": row_warnings,
            "dna_mode": cfg.dna_mode,
            # Say so explicitly: a reverse translation looks exactly like an
            # optimised sequence, and the difference matters once it is ordered.
            "dna_optimized": False,
            "format": format,
            "download_url": download_url,
            "base_url": public_base_url(),
            "expires_in_seconds": prepare_stash.DEFAULT_TTL_SECONDS,
            "note": with_relative_note(
                "GET download_url for the constructs. No API key. The link expires "
                "in ~10 minutes and does not survive a server restart."
            ),
            "example": {
                "design_id": rows[0].design_id,
                "short_name": rows[0].short_name,
                "prepared_aa": rows[0].prepared_aa[:120],
            },
        }
