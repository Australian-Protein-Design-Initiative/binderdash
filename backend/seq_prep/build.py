"""Assemble prepared constructs from designs plus a :class:`PrepareConfig`.

Ported from the ``preparedRows`` computed property in
``frontend/src/stores/seqPrep.ts``. One design in, one :class:`PreparedRow` out.

Assembly order is: N-terminal prefix, N tags (if ``tag == 'N'``), binder core,
C tags (if ``tag == 'C'``), C-terminal suffix, terminal stop, post-stop padding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .codon import FIXED_STOP_DNA, CodonTable
from .config import PlacedTag, PrepareConfig
from .mixed import (
    KIND_DNA_BODY,
    KIND_PADDING,
    KIND_STOP,
    Segment,
    apply_fixed_start_atg_dna,
    apply_fixed_start_methionine,
    expand_fixed_from_segments,
    literal_aa_to_dna_segments,
    merge_dna_segments,
    mixed_to_aa_segments,
    mixed_to_dna_segments,
    segment_kind_for_tag,
    split_core_aa_segments,
)
from .protparam import isoelectric_point, molar_extinction_coefficient, sequence_warnings
from .shortnames import ShortNameRowInput, compute_short_names, sanitize_short_name_segment

WARNING_LONG_NAME_NOT_UNIQUE = "Long name not unique"
WARNING_SHORT_NAME_NOT_UNIQUE = "Short name not unique"

_SEQUENCE_FIELDS = ("Sequence", "sequence", "binder_sequence", "binder_seq", "seq")


def raw_sequence(design: Dict[str, Any]) -> str:
    for field_name in _SEQUENCE_FIELDS:
        value = design.get(field_name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


@dataclass
class PreparedRow:
    row_key: str
    design_id: str
    run_id: str = ""
    run_name: str = ""
    project_id: str = ""
    source_path: str = ""
    tag: str = "-"
    short_name: str = ""
    original_sequence: str = ""
    prepared_aa: str = ""
    prepared_aa_display: str = ""
    prepared_dna: Optional[str] = None
    segments_aa: List[Segment] = field(default_factory=list)
    segments_aa_display: List[Segment] = field(default_factory=list)
    segments_dna: Optional[List[Segment]] = None
    extinction_coeff_reduced: int = 0
    extinction_coeff_oxidized: int = 0
    isoelectric_point: float = 0.0
    warnings: List[str] = field(default_factory=list)
    seed: Optional[int] = None

    def to_dict(self, *, include_segments: bool = True) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "row_key": self.row_key,
            "design_id": self.design_id,
            "run_id": self.run_id,
            "run_name": self.run_name,
            "project_id": self.project_id,
            "source_path": self.source_path,
            "tag": self.tag,
            "short_name": self.short_name,
            "original_sequence": self.original_sequence,
            "prepared_aa": self.prepared_aa,
            "prepared_dna": self.prepared_dna,
            "extinction_coeff_reduced": self.extinction_coeff_reduced,
            "extinction_coeff_oxidized": self.extinction_coeff_oxidized,
            "isoelectric_point": self.isoelectric_point,
            "warnings": list(self.warnings),
            "seed": self.seed,
        }
        if include_segments:
            d["prepared_aa_display"] = self.prepared_aa_display
            d["segments_aa"] = [s.to_dict() for s in self.segments_aa]
            d["segments_aa_display"] = [s.to_dict() for s in self.segments_aa_display]
            d["segments_dna"] = (
                [s.to_dict() for s in self.segments_dna] if self.segments_dna is not None else None
            )
        return d

    def coding_aa_and_fixed(self) -> Tuple[str, List[bool]]:
        """The sequence sent for DNA optimisation, with its fixed-residue mask.

        Post-stop padding is excluded: it is not translated, so it must not be
        codon-optimised.
        """
        aa, fixed = expand_fixed_from_segments(self.segments_aa_display)
        if not aa:
            aa = self.prepared_aa_display
            fixed = [ch == "*" for ch in aa]
        return aa, fixed


def _padding_required(main_dna_len: int, pad_target: int, pad_raw: str, table: CodonTable) -> bool:
    trimmed = pad_raw.strip()
    if not trimmed or pad_target <= 0 or main_dna_len >= pad_target:
        return False
    dna, _ = mixed_to_dna_segments(trimmed, table, KIND_DNA_BODY)
    return len(dna) > 0


def _post_stop_padding_chunks(
    main_dna_len: int, pad_target: int, pad_raw: str, table: CodonTable
) -> List[Tuple[str, str]]:
    """Repeat the padding unit until ``pad_target`` nt, truncating the last copy.

    Returns ``(dna, aa_mixed)`` pairs; the truncated tail has no amino-acid
    reading, so it is carried as lowercase nucleotides.
    """
    trimmed = pad_raw.strip()
    if not _padding_required(main_dna_len, pad_target, pad_raw, table):
        return []
    unit, _ = mixed_to_dna_segments(trimmed, table, KIND_DNA_BODY)
    chunks: List[Tuple[str, str]] = []
    remaining = pad_target - main_dna_len
    while remaining >= len(unit):
        chunks.append((unit, trimmed))
        remaining -= len(unit)
    if remaining > 0:
        tail = unit[:remaining]
        chunks.append((tail, tail.lower()))
    return chunks


def _append_tags_aa(
    tags: Sequence[PlacedTag], segments: List[Segment], export: List[str], table: CodonTable
) -> None:
    for tag in tags:
        if not tag.sequence:
            continue
        if tag.kind == "stop":
            segments.append(Segment("*", KIND_STOP, fixed=True))
            export.append("*")
            continue
        kind = segment_kind_for_tag(tag.kind)
        if tag.kind == "custom":
            segs, text = mixed_to_aa_segments(tag.sequence, kind, table)
            segments.extend(segs)
            export.append(text)
        else:
            segments.append(Segment(tag.sequence, kind))
            export.append(tag.sequence)


def _active_tags(tags: Sequence[PlacedTag], include: bool) -> List[PlacedTag]:
    """Tags flagged ``always`` apply to every design; the rest only where the tag end matches."""
    return [t for t in tags if include or t.always]


def _append_tags_dna(
    tags: Sequence[PlacedTag],
    dna_chunks: List[str],
    seg_chunks: List[List[Segment]],
    table: CodonTable,
) -> None:
    for tag in tags:
        if not tag.sequence:
            continue
        if tag.kind == "stop":
            dna_chunks.append(FIXED_STOP_DNA)
            seg_chunks.append([Segment(FIXED_STOP_DNA, KIND_STOP, fixed=True)])
            continue
        kind = segment_kind_for_tag(tag.kind)
        if tag.kind == "custom":
            dna, segs = mixed_to_dna_segments(tag.sequence, table, kind)
            seg_chunks.append(merge_dna_segments(segs, kind))
        else:
            dna, segs = literal_aa_to_dna_segments(tag.sequence, table, kind)
            seg_chunks.append(segs)
        dna_chunks.append(dna)


def _build_main_dna(
    cfg: PrepareConfig,
    table: CodonTable,
    tag_col: str,
    core: str,
    include_n: bool,
    include_c: bool,
) -> Tuple[str, List[List[Segment]]]:
    dna_chunks: List[str] = []
    seg_chunks: List[List[Segment]] = []

    _append_tags_dna(_active_tags(cfg.n_tags, include_n), dna_chunks, seg_chunks, table)

    dna, segs = literal_aa_to_dna_segments(core, table)
    dna_chunks.append(dna)
    seg_chunks.append(merge_dna_segments(segs, KIND_DNA_BODY))

    _append_tags_dna(_active_tags(cfg.c_tags, include_c), dna_chunks, seg_chunks, table)

    if (tag_col == "N" and cfg.include_stop_for_n_tagged) or (
        tag_col == "C" and cfg.include_stop_for_c_tagged
    ):
        for _ in range(2 if cfg.use_double_stop else 1):
            dna_chunks.append(FIXED_STOP_DNA)
            seg_chunks.append([Segment(FIXED_STOP_DNA, KIND_STOP, fixed=True)])

    return "".join(dna_chunks), seg_chunks


def _build_body_aa(
    cfg: PrepareConfig,
    table: CodonTable,
    tag_col: str,
    core: str,
    include_n: bool,
    include_c: bool,
) -> Tuple[List[Segment], str]:
    segments: List[Segment] = []
    export: List[str] = []

    _append_tags_aa(_active_tags(cfg.n_tags, include_n), segments, export, table)

    segments.extend(split_core_aa_segments(core))
    export.append(core)

    _append_tags_aa(_active_tags(cfg.c_tags, include_c), segments, export, table)

    if (tag_col == "N" and cfg.include_stop_for_n_tagged) or (
        tag_col == "C" and cfg.include_stop_for_c_tagged
    ):
        count = 2 if cfg.use_double_stop else 1
        for _ in range(count):
            segments.append(Segment("*", KIND_STOP, fixed=True))
        export.append("*" * count)

    return segments, "".join(export)


def build_row(
    design: Dict[str, Any],
    cfg: PrepareConfig,
    *,
    optimized_dna: Optional[str] = None,
    optimization_error: Optional[str] = None,
    seed: Optional[int] = None,
) -> PreparedRow:
    """Build one construct. ``optimized_dna`` replaces the naive reverse translation."""
    table = cfg.table()
    raw = raw_sequence(design)
    core = raw.rstrip("*").strip()
    tag_col = str(design.get("tag") or "").strip().upper()

    pad_raw = cfg.post_stop_padding.strip()
    pad_target_val = cfg.post_stop_pad_up_to_nucleotide_length
    use_pad_target = pad_target_val is not None and pad_target_val > 0
    pad_target = int(pad_target_val) if use_pad_target else 0

    # Whether the conditional terminal tags apply depends on the length without
    # them, so probe first.
    probe_dna, _ = _build_main_dna(cfg, table, tag_col, core, False, False)
    probe_len = len(probe_dna)

    def resolve(zone: str) -> bool:
        if tag_col != zone:
            return False
        only_when_needed = (
            cfg.only_use_n_terminal_tag_when_padding_required
            if zone == "N"
            else cfg.only_use_c_terminal_tag_when_padding_required
        )
        if not only_when_needed:
            return True
        if not use_pad_target:
            return False
        return _padding_required(probe_len, pad_target, pad_raw, table)

    include_n = resolve("N")
    include_c = resolve("C")

    segments_aa, prepared_aa = _build_body_aa(cfg, table, tag_col, core, include_n, include_c)
    freeze_start = cfg.dont_modify_start_atg
    segments_display = apply_fixed_start_methionine(segments_aa, freeze_start)
    prepared_aa_display = prepared_aa

    need_dna = cfg.dna_mode or (use_pad_target and bool(pad_raw))
    main_dna = ""
    main_seg_chunks: List[List[Segment]] = []
    if need_dna:
        built_dna, built_chunks = _build_main_dna(cfg, table, tag_col, core, include_n, include_c)
        built_dna, built_chunks = apply_fixed_start_atg_dna(built_dna, built_chunks, freeze_start)
        if optimized_dna:
            # Optimisation preserves translation, so segment lengths are unchanged;
            # reslice the optimised sequence over the same boundaries to keep colours.
            main_dna = optimized_dna
            offset = 0
            main_seg_chunks = []
            for chunk in built_chunks:
                out_chunk = []
                for seg in chunk:
                    out_chunk.append(
                        Segment(optimized_dna[offset : offset + len(seg.text)], seg.kind, seg.fixed)
                    )
                    offset += len(seg.text)
                main_seg_chunks.append(out_chunk)
        else:
            main_dna, main_seg_chunks = built_dna, built_chunks

    padding_chunks = (
        _post_stop_padding_chunks(len(main_dna), pad_target, pad_raw, table)
        if use_pad_target and pad_raw and need_dna
        else []
    )

    segments_full = list(segments_display)
    export_parts = [prepared_aa]
    for _chunk_dna, aa_mixed in padding_chunks:
        segs, text = mixed_to_aa_segments(aa_mixed, KIND_PADDING, table)
        segments_full.extend(segs)
        export_parts.append(text)
    prepared_aa = "".join(export_parts)

    prepared_dna: Optional[str] = None
    segments_dna: Optional[List[Segment]] = None
    if cfg.dna_mode:
        dna = main_dna
        pad_seg_chunks: List[List[Segment]] = []
        for chunk_dna, aa_mixed in padding_chunks:
            dna += chunk_dna
            unit_dna, pad_segs = mixed_to_dna_segments(aa_mixed, table, KIND_DNA_BODY)
            if unit_dna and len(chunk_dna) == len(unit_dna):
                pad_seg_chunks.append(merge_dna_segments(pad_segs, KIND_PADDING))
            else:
                pad_seg_chunks.append([Segment(chunk_dna, KIND_PADDING)])

        body_len = len(dna)
        # Short fragments are topped up nucleotide by nucleotide so the order meets
        # the vendor's minimum length.
        pad_dna_only = (
            "".join(c for c in pad_raw if c in "acgtACGT").upper()
            if use_pad_target and pad_raw
            else ""
        )
        min_len = max(0, cfg.min_dna_fragment_length)
        if min_len > 0 and len(dna) < min_len and pad_dna_only:
            i = 0
            while len(dna) < min_len:
                dna += pad_dna_only[i % len(pad_dna_only)]
                i += 1
        prepared_dna = dna

        flat: List[Segment] = [s for chunk in main_seg_chunks for s in chunk]
        flat.extend(s for chunk in pad_seg_chunks for s in chunk)
        if len(dna) > body_len:
            flat.append(Segment(dna[body_len:], KIND_PADDING))
        segments_dna = flat

    reduced, oxidized = molar_extinction_coefficient(prepared_aa)
    warnings = sequence_warnings(prepared_aa)
    if optimization_error:
        warnings.append(f"DNA Opt: {optimization_error}")

    return PreparedRow(
        row_key=f"{design.get('run_id', '')}\x1f{design.get('design_id', '')}\x1f{design.get('source_path', '') or ''}",
        design_id=str(design.get("design_id") or ""),
        run_id=str(design.get("run_id") or ""),
        run_name=str(design.get("run_name") or ""),
        project_id=str(design.get("project_id") or ""),
        source_path=str(design.get("source_path") or ""),
        tag=tag_col or "-",
        original_sequence=raw or "(missing)",
        prepared_aa=prepared_aa,
        prepared_aa_display=prepared_aa_display,
        prepared_dna=prepared_dna,
        segments_aa=segments_full,
        segments_aa_display=segments_display,
        segments_dna=segments_dna,
        extinction_coeff_reduced=reduced,
        extinction_coeff_oxidized=oxidized,
        isoelectric_point=isoelectric_point(prepared_aa),
        warnings=warnings,
        seed=seed,
    )


def build_rows(
    designs: Iterable[Dict[str, Any]],
    cfg: PrepareConfig,
    *,
    optimized: Optional[Dict[str, str]] = None,
    errors: Optional[Dict[str, str]] = None,
    seeds: Optional[Dict[str, int]] = None,
) -> List[PreparedRow]:
    """Build every construct, then assign short names across the whole set."""
    optimized = optimized or {}
    errors = errors or {}
    seeds = seeds or {}

    rows = [
        build_row(
            d,
            cfg,
            optimized_dna=optimized.get(str(d.get("design_id") or "")),
            optimization_error=errors.get(str(d.get("design_id") or "")),
            seed=seeds.get(str(d.get("design_id") or "")),
        )
        for d in designs
    ]

    inputs = [
        ShortNameRowInput(
            row_key=r.row_key,
            design_id=r.design_id,
            original_aa=r.original_sequence,
            prepared_aa=r.prepared_aa,
            prepared_dna=r.prepared_dna,
            tag=r.tag,
        )
        for r in rows
    ]
    result = compute_short_names(inputs, cfg.short_name, cfg.short_name_max_len)

    design_id_counts: Dict[str, int] = {}
    for r in rows:
        design_id_counts[r.design_id] = design_id_counts.get(r.design_id, 0) + 1

    for r in rows:
        r.short_name = result.names.get(r.row_key) or (
            sanitize_short_name_segment(r.design_id) or r.design_id
        )
        if design_id_counts.get(r.design_id, 0) > 1:
            r.warnings.append(WARNING_LONG_NAME_NOT_UNIQUE)
        if r.row_key in result.non_unique_row_keys:
            r.warnings.append(WARNING_SHORT_NAME_NOT_UNIQUE)
    return rows
