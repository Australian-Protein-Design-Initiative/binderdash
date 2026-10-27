"""Export writers: FASTA, TSV, CSV and the Twist order CSV.

Ported from ``PrepareSequencesView.vue``. Each returns a string rather than
writing a file, so the API can stream it and the script can save it.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .build import PreparedRow
from .config import PrepareConfig

_NON_NAME = re.compile(r"[^a-z0-9]+")
_UNDERSCORES = re.compile(r"_+")
_EDGE_UNDERSCORE = re.compile(r"^_|_$")


def sanitize_order_name(raw: str) -> str:
    t = raw.strip().lower()
    if not t:
        return ""
    cleaned = _EDGE_UNDERSCORE.sub("", _UNDERSCORES.sub("_", _NON_NAME.sub("_", t)))
    return cleaned[:120]


def export_basename(order_name: str, now: Optional[datetime] = None) -> str:
    """``{order_name_or_default}_{YYYYMMDD_HHmmss}``, no extension."""
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{sanitize_order_name(order_name) or 'prepared_sequences'}_{stamp}"


def sequence_for_export(row: PreparedRow, cfg: PrepareConfig) -> str:
    """The sequence the user asked to see: DNA in DNA mode, else AA.

    Post-stop padding is nucleotide spacer, so it translates to nonsense amino
    acids; ``show_post_stop_padding`` decides whether the AA export carries it.
    """
    if cfg.dna_mode:
        return row.prepared_dna or row.prepared_aa
    return row.prepared_aa if cfg.show_post_stop_padding else row.prepared_aa_display


def _pi(value: float) -> str:
    return "" if value != value or value in (float("inf"), float("-inf")) else str(value)


def to_fasta(rows: Sequence[PreparedRow], cfg: PrepareConfig) -> str:
    lines: List[str] = []
    for r in rows:
        lines.append(f">{r.design_id}")
        lines.append(sequence_for_export(r, cfg))
    return "\n".join(lines)


def _table_rows(rows: Sequence[PreparedRow], cfg: PrepareConfig) -> tuple[List[str], List[List[Any]]]:
    if cfg.dna_mode:
        cols = [
            "design_id", "project_id", "run_name", "tag", "original_sequence",
            "prepared_aa", "prepared_dna", "dna_length", "extinction_coeff_reduced",
            "extinction_coeff_oxidized", "isoelectric_point", "warnings", "short_name",
        ]
        body = [
            [
                r.design_id, r.project_id, r.run_name, r.tag, r.original_sequence,
                r.prepared_aa, r.prepared_dna or "", len(r.prepared_dna or ""),
                r.extinction_coeff_reduced, r.extinction_coeff_oxidized,
                _pi(r.isoelectric_point), "; ".join(r.warnings), r.short_name,
            ]
            for r in rows
        ]
        return cols, body

    cols = [
        "design_id", "project_id", "run_name", "tag", "original_sequence",
        "prepared_sequence", "length", "extinction_coeff_reduced",
        "extinction_coeff_oxidized", "isoelectric_point", "warnings", "short_name",
    ]
    body = []
    for r in rows:
        aa = sequence_for_export(r, cfg)
        body.append([
            r.design_id, r.project_id, r.run_name, r.tag, r.original_sequence,
            aa, len(aa), r.extinction_coeff_reduced, r.extinction_coeff_oxidized,
            _pi(r.isoelectric_point), "; ".join(r.warnings), r.short_name,
        ])
    return cols, body


def _write(cols: Sequence[str], body: Sequence[Sequence[Any]], delimiter: str) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    writer.writerow(cols)
    writer.writerows(body)
    return buf.getvalue().rstrip("\n")


def to_tsv(rows: Sequence[PreparedRow], cfg: PrepareConfig) -> str:
    return _write(*_table_rows(rows, cfg), delimiter="\t")


def to_csv(rows: Sequence[PreparedRow], cfg: PrepareConfig) -> str:
    return _write(*_table_rows(rows, cfg), delimiter=",")


def to_twist_csv(rows: Sequence[PreparedRow], cfg: PrepareConfig) -> str:
    """Vendor order format: short name, sequence, original design_id."""
    body = [[r.short_name, sequence_for_export(r, cfg), r.design_id] for r in rows]
    return _write(["name", "sequence", "original_name"], body, delimiter=",")


FORMATS = {
    "twist": (to_twist_csv, "csv"),
    "fasta": (to_fasta, "fasta"),
    "tsv": (to_tsv, "tsv"),
    "csv": (to_csv, "csv"),
}


def render(fmt: str, rows: Sequence[PreparedRow], cfg: PrepareConfig) -> str:
    try:
        writer, _ = FORMATS[fmt]
    except KeyError:
        raise ValueError(f"Unknown format '{fmt}'; expected one of {', '.join(sorted(FORMATS))}")
    return writer(rows, cfg)
