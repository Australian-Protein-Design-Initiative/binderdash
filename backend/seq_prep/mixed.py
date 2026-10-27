"""Mixed amino-acid / nucleotide sequence handling.

Tag and padding fields accept a mix of uppercase amino acids and lowercase
nucleotides, e.g. ``MGSSHHHHHHgaattc``. Ported from
``frontend/src/stores/seqPrep.ts``.

Segments carry a semantic ``kind`` rather than a CSS class; the frontend maps
``kind`` to colours. ``fixed`` marks residues that DNA optimisation must not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .codon import FIXED_START_DNA, FIXED_STOP_DNA, CodonTable

VALID_NUC = frozenset("acgt")

KIND_STOP = "stop"
KIND_CORE = "core"
KIND_DNA_BODY = "dna_body"
KIND_PADDING = "padding"
KIND_NUC_REMAINDER = "nuc_remainder"
KIND_CUSTOM = "custom"

_TAG_KIND_TO_SEGMENT = {
    "hisN": "his",
    "hisC": "his",
    "flag": "flag",
    "cmyc": "cmyc",
    "ha": "ha",
    "avi": "avi",
    "strep": "strep",
    "ctag": "ctag",
    "pelb": "pelb",
    "linker": "linker",
    "stop": KIND_STOP,
}


def segment_kind_for_tag(tag_kind: str) -> str:
    return _TAG_KIND_TO_SEGMENT.get(tag_kind, KIND_CUSTOM)


@dataclass
class Segment:
    text: str
    kind: str
    fixed: bool = False

    def to_dict(self) -> Dict[str, object]:
        d: Dict[str, object] = {"text": self.text, "kind": self.kind}
        if self.fixed:
            d["fixed"] = True
        return d


def validate_mixed_sequence(s: str, field_name: str) -> Optional[str]:
    """Uppercase A-Z, ``*``, lowercase acgt and whitespace only."""
    for ch in s:
        if "A" <= ch <= "Z" or ch == "*" or ch in VALID_NUC or ch.isspace():
            continue
        return f"{field_name}: invalid character '{ch}'"
    return None


def _is_upper_aa(c: str) -> bool:
    return ("A" <= c <= "Z") or c == "*"


def split_mixed_runs(mixed: str) -> List[Tuple[str, str]]:
    """Split into ``(kind, text)`` runs where kind is ``upper`` or ``lower``.

    Whitespace and characters that are neither are dropped.
    """
    runs: List[Tuple[str, str]] = []
    i, n = 0, len(mixed)
    while i < n:
        c = mixed[i]
        if c.isspace():
            i += 1
            continue
        lower = c in VALID_NUC
        upper = _is_upper_aa(c)
        if not lower and not upper:
            i += 1
            continue
        start = i
        if lower:
            while i < n and mixed[i] in VALID_NUC:
                i += 1
            runs.append(("lower", mixed[start:i]))
        else:
            while i < n and _is_upper_aa(mixed[i]):
                i += 1
            runs.append(("upper", mixed[start:i]))
    return runs


def mixed_to_aa_segments(
    mixed: str, kind: str, table: CodonTable
) -> Tuple[List[Segment], str]:
    """Render a mixed field as amino acids. Nucleotide runs are translated.

    A trailing partial codon cannot be translated, so it becomes one ``-`` per
    nucleotide in the exported string, matching the frontend.
    """
    segments: List[Segment] = []
    export: List[str] = []
    for run_kind, text in split_mixed_runs(mixed):
        if run_kind == "upper":
            buf = ""
            for ch in text:
                if ch == "*":
                    if buf:
                        segments.append(Segment(buf, kind))
                        export.append(buf)
                        buf = ""
                    segments.append(Segment("*", KIND_STOP, fixed=True))
                    export.append("*")
                else:
                    buf += ch
            if buf:
                segments.append(Segment(buf, kind))
                export.append(buf)
            continue
        full = len(text) // 3
        for t in range(full):
            tri = text[t * 3 : t * 3 + 3].upper()
            aa = table.reverse.get(tri, "X")
            is_stop = aa == "*"
            segments.append(
                Segment("*" if is_stop else aa, KIND_STOP if is_stop else kind, fixed=is_stop)
            )
            export.append("*" if is_stop else aa)
        rem = text[full * 3 :]
        if rem:
            segments.append(Segment(rem, KIND_NUC_REMAINDER))
            export.append("-" * len(rem))
    return segments, "".join(export)


def literal_aa_to_dna_segments(
    aa: str, table: CodonTable, body_kind: str = KIND_DNA_BODY
) -> Tuple[str, List[Segment]]:
    """Reverse-translate a pure amino-acid string. Every ``*`` is a fixed TAA."""
    dna: List[str] = []
    segments: List[Segment] = []
    body = ""
    for ch in aa:
        if ch.isspace():
            continue
        if ch == "*":
            if body:
                segments.append(Segment(body, body_kind))
                body = ""
            dna.append(FIXED_STOP_DNA)
            segments.append(Segment(FIXED_STOP_DNA, KIND_STOP, fixed=True))
        else:
            u = ch.upper()
            if "A" <= u <= "Z":
                codon = table.forward.get(u) or table.forward["X"]
                dna.append(codon)
                body += codon
    if body:
        segments.append(Segment(body, body_kind))
    return "".join(dna), segments


def mixed_to_dna_segments(
    mixed: str, table: CodonTable, body_kind: str
) -> Tuple[str, List[Segment]]:
    """Render a mixed field as DNA. Lowercase runs pass through verbatim."""
    dna: List[str] = []
    segments: List[Segment] = []
    body = ""

    def flush() -> None:
        nonlocal body
        if body:
            segments.append(Segment(body, body_kind))
            body = ""

    for run_kind, text in split_mixed_runs(mixed):
        if run_kind == "upper":
            sub_dna, sub_segs = literal_aa_to_dna_segments(text, table, body_kind)
            dna.append(sub_dna)
            for s in sub_segs:
                if s.kind == KIND_STOP:
                    flush()
                    segments.append(s)
                elif s.kind == body_kind:
                    body += s.text
            continue
        for i in range(0, len(text), 3):
            tri = text[i : i + 3]
            up = tri.upper()
            if len(tri) < 3:
                dna.append(up)
                body += up
                continue
            if table.reverse.get(up) == "*":
                flush()
                dna.append(up)
                segments.append(Segment(up, KIND_STOP, fixed=True))
            else:
                dna.append(up)
                body += up
    flush()
    return "".join(dna), segments


def merge_dna_segments(segments: List[Segment], body_kind: str) -> List[Segment]:
    """Collapse runs of non-fixed segments so colouring stays coarse."""
    out: List[Segment] = []
    buf = ""
    for s in segments:
        if s.kind == KIND_STOP or s.fixed:
            if buf:
                out.append(Segment(buf, body_kind))
                buf = ""
            out.append(s)
        else:
            buf += s.text
    if buf:
        out.append(Segment(buf, body_kind))
    return out


def split_core_aa_segments(core: str) -> List[Segment]:
    """Split the binder core so each ``*`` is its own fixed stop segment."""
    segments: List[Segment] = []
    buf = ""
    for ch in core:
        if ch == "*":
            if buf:
                segments.append(Segment(buf, KIND_CORE))
                buf = ""
            segments.append(Segment("*", KIND_STOP, fixed=True))
        else:
            buf += ch
    if buf:
        segments.append(Segment(buf, KIND_CORE))
    return segments


def expand_fixed_from_segments(segments: List[Segment]) -> Tuple[str, List[bool]]:
    """Flatten segments to the AA string plus a per-residue fixed mask."""
    aa: List[str] = []
    fixed: List[bool] = []
    for seg in segments:
        for ch in seg.text:
            aa.append(ch)
            fixed.append(seg.fixed)
    return "".join(aa), fixed


def apply_fixed_start_methionine(segments: List[Segment], enabled: bool) -> List[Segment]:
    """Split a leading Met into its own fixed segment so its codon stays ATG."""
    if not enabled or not segments:
        return list(segments)
    first = segments[0]
    if not first.text or first.text[0] != "M":
        return list(segments)
    if first.text == "M":
        if first.fixed:
            return list(segments)
        return [Segment("M", first.kind, fixed=True), *segments[1:]]
    out = [Segment("M", first.kind, fixed=True)]
    rest = first.text[1:]
    if rest:
        out.append(Segment(rest, first.kind, fixed=first.fixed))
    out.extend(segments[1:])
    return out


def apply_fixed_start_atg_dna(
    main_dna: str, chunks: List[List[Segment]], enabled: bool
) -> Tuple[str, List[List[Segment]]]:
    """Carve a leading ATG into its own fixed segment, keeping the lead colour."""
    if not enabled or len(main_dna) < 3:
        return main_dna, chunks
    if main_dna[:3].upper() != FIXED_START_DNA:
        return main_dna, chunks
    dna = FIXED_START_DNA + main_dna[3:]
    flat = [s for chunk in chunks for s in chunk]
    joined = "".join(s.text for s in flat)
    if len(joined) < 3 or joined[:3].upper() != FIXED_START_DNA:
        return dna, chunks
    lead_kind = flat[0].kind if flat else KIND_DNA_BODY
    skip = 3
    rest: List[Segment] = []
    for seg in flat:
        if skip <= 0:
            rest.append(seg)
            continue
        if len(seg.text) <= skip:
            skip -= len(seg.text)
            continue
        rest.append(Segment(seg.text[skip:], seg.kind, seg.fixed))
        skip = 0
    return dna, [[Segment(FIXED_START_DNA, lead_kind, fixed=True)], rest]
