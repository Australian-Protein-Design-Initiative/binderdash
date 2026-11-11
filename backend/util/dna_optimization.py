import io
import logging
import threading
from contextlib import redirect_stdout
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

import dnachisel as dc
import primer3
import python_codon_tables as pct

logger = logging.getLogger(__name__)

FIXED_STOP_DNA = "TAA"
FIXED_START_DNA = "ATG"
# DnaChisel's random search can miss a sequence that satisfies the constraints.
# Re-run a design that fails with NoSolutionError this many times before reporting it.
OPTIMIZATION_ATTEMPTS = 5
_NO_SOLUTION_MESSAGE = "Constraints could not be resolved (No solution found)."

# primer3's thermodynamic alignment scores at most 60 bp per sequence, so
# hairpin / inverted-repeat Tm is computed on sliding windows of that width.
_HAIRPIN_WINDOW = 60
# primer3's module-level helpers share one mutable ThermoAnalysis object, so
# concurrent optimisation batches (each runs in its own thread) must not call
# it simultaneously.
_PRIMER3_LOCK = threading.Lock()


@lru_cache(maxsize=20000)
def _hairpin_tm(window: str) -> float:
    """Concentration-independent (IDT-style) hairpin Tm of a <= 60 nt window."""
    if len(window) < 8:
        return -99.0
    try:
        with _PRIMER3_LOCK:
            return float(primer3.calc_hairpin(window).tm)
    except Exception:
        return -99.0


def _hairpin_breaches(
    sequence: str, min_tm: float, stride: int
) -> List[Tuple[int, int, float]]:
    """Windows whose hairpin Tm reaches ``min_tm``, merged into breach spans.

    Returns ``(start, end, tm)`` tuples in local sequence coordinates. With a
    stride of 10 any hairpin whose arms+loop span <= 50 nt is guaranteed to
    fall entirely inside at least one window (primer3 cannot score structures
    spanning more than 60 nt at all).
    """
    n = len(sequence)
    if n == 0:
        return []
    starts = list(range(0, max(1, n - _HAIRPIN_WINDOW + 1), max(1, stride)))
    if n > _HAIRPIN_WINDOW:
        last = n - _HAIRPIN_WINDOW
        if starts[-1] != last:
            starts.append(last)

    hot: List[Tuple[int, int, float]] = []
    for start in starts:
        window = sequence[start : start + _HAIRPIN_WINDOW]
        tm = _hairpin_tm(window)
        if tm >= min_tm:
            hot.append((start, start + len(window), tm))

    merged: List[List[Any]] = []
    for start, end, tm in sorted(hot):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] = max(merged[-1][2], tm)
        else:
            merged.append([start, end, tm])
    return [(s, e, t) for s, e, t in merged]


class AvoidInvertedRepeats(dc.Specification):
    """Avoid inverted repeats (snapback hairpins) with Tm >= ``min_tm``.

    Gene synthesis vendors reject sequences whose self-complementary
    structures melt at or above a threshold Tm, computed the same way
    primer3 / IDT do (concentration-free nearest-neighbour alignment).
    DnaChisel's ``AvoidHairpins`` misses these because it requires a long
    exact Watson-Crick stem within a short window.
    """

    best_possible_score = 0

    def __init__(
        self,
        min_tm: float = 68.0,
        stride: int = 10,
        location: Any = None,
        boost: float = 1.0,
    ) -> None:
        self.min_tm = float(min_tm)
        self.stride = max(1, int(stride))
        self.boost = boost
        self.location = dc.Location.from_data(location)

    def initialized_on_problem(self, problem: Any, role: Optional[str] = None) -> "AvoidInvertedRepeats":
        return self._copy_with_full_span_if_no_location(problem)

    def evaluate(self, problem: Any) -> dc.SpecEvaluation:
        offset = self.location.start if self.location is not None else 0
        sequence = self.location.extract_sequence(problem.sequence)
        breaches = _hairpin_breaches(sequence, self.min_tm, self.stride)
        locations = [dc.Location(start + offset, end + offset) for start, end, _ in breaches]
        score = -sum(tm - self.min_tm for _, _, tm in breaches)
        return dc.SpecEvaluation(self, problem, score, locations=locations)

    def localized(self, location: Any, problem: Any = None, with_righthand: bool = True) -> Optional["AvoidInvertedRepeats"]:
        new_location = self.location.overlap_region(location)
        if new_location is None:
            return None
        new_location.start = max(self.location.start, new_location.start - _HAIRPIN_WINDOW)
        if with_righthand:
            new_location.end = min(self.location.end, new_location.end + _HAIRPIN_WINDOW)
        return self.copy_with_changes(location=new_location)

    def label_parameters(self) -> List[Tuple[str, str]]:
        return [("min_tm", str(self.min_tm))]

    def short_label(self) -> str:
        return "No inverted repeat above %g C" % self.min_tm

    def breach_label(self) -> str:
        return "inverted repeat above %g C" % self.min_tm


# Pro (CCC) and Arg (CGG, CGA) codons that synthesis vendors reject in runs.
_DEFAULT_RUN_CODONS = ("CGG", "CGA", "CCC")
# Lowercase acgt in a sequence are literal nucleotides (custom 5'/3' additions),
# not amino acids. They are not recoded, and they shift the coding frame.
_LITERAL_NT = set("acgt")


class AvoidConsecutiveCodons(dc.Specification):
    """Avoid runs of more than ``max_run`` codons drawn from ``codons``.

    Codons are read in the design/tag reading frame (``frame`` is the
    nucleotide offset of the first coding codon), not from nucleotide 0.
    A 5' addition whose length is not a multiple of 3 leaves ``frame`` at
    1 or 2; triplets that merely contain CGG/CGA/CCC across a codon
    boundary are not runs.
    """

    best_possible_score = 0
    # A run can cross a frozen codon, so this must not be split per free interval.
    keep_global = True

    def __init__(
        self,
        codons: Optional[Sequence[str]] = None,
        max_run: int = 2,
        frame: int = 0,
        location: Any = None,
        boost: float = 1.0,
    ) -> None:
        chosen = codons if codons is not None else _DEFAULT_RUN_CODONS
        self.codons = tuple(str(c).upper() for c in chosen)
        self.max_run = int(max_run)
        self.frame = int(frame) % 3
        self.boost = boost
        self.location = dc.Location.from_data(location)

    def initialized_on_problem(self, problem: Any, role: Optional[str] = None) -> "AvoidConsecutiveCodons":
        return self._copy_with_full_span_if_no_location(problem)

    def _violating_runs(self, sequence: str) -> List[Tuple[int, int, int]]:
        bad = set(self.codons)
        runs: List[Tuple[int, int, int]] = []
        run_start = 0
        run_len = 0
        i = self.frame
        while i + 3 <= len(sequence):
            if sequence[i : i + 3] in bad:
                if run_len == 0:
                    run_start = i
                run_len += 1
            elif run_len > self.max_run:
                runs.append((run_start, run_start + 3 * run_len, run_len))
                run_len = 0
            else:
                run_len = 0
            i += 3
        if run_len > self.max_run:
            runs.append((run_start, run_start + 3 * run_len, run_len))
        if self.location is None:
            return runs
        kept: List[Tuple[int, int, int]] = []
        for start, end, length in runs:
            if self.location.overlap_region(dc.Location(start, end)) is not None:
                kept.append((start, end, length))
        return kept

    def evaluate(self, problem: Any) -> dc.SpecEvaluation:
        runs = self._violating_runs(problem.sequence)
        locations = [dc.Location(start, end) for start, end, _ in runs]
        score = -sum(length - self.max_run for _, _, length in runs)
        return dc.SpecEvaluation(self, problem, score, locations=locations)

    def label_parameters(self) -> List[Tuple[str, str]]:
        return [("max_run", str(self.max_run)), ("frame", str(self.frame))]

    def short_label(self) -> str:
        return "No more than %d consecutive %s codons" % (self.max_run, "/".join(self.codons))

    def breach_label(self) -> str:
        return "more than %d consecutive %s codons" % (self.max_run, "/".join(self.codons))


def _naive_translate_protein(protein_seq: str, table_id: str = "e_coli_316407") -> str:
    """Translates protein to DNA naively by picking the most frequent codon.
    DnaChisel needs a starting DNA seq to optimize."""
    try:
        table = pct.get_codons_table(table_id, replace_U_by_T=True)
    except Exception:
        table = pct.get_codons_table("e_coli_316407", replace_U_by_T=True)

    best_codons: Dict[str, str] = {}
    for aa, codons in table.items():
        if aa == "*":
            continue
        if isinstance(codons, dict):
            ordered = sorted(codons.items(), key=lambda x: (-x[1], x[0]))
            if ordered:
                best_codons[aa.upper()] = ordered[0][0].upper()

    best_codons.setdefault("X", "NNN")

    dna_parts: List[str] = []
    for aa in protein_seq.upper():
        if aa == "*":
            stop_ordered = sorted(table.get("*", {}).items(), key=lambda x: (-x[1], x[0]))
            dna_parts.append(stop_ordered[0][0].upper() if stop_ordered else FIXED_STOP_DNA)
        else:
            dna_parts.append(best_codons.get(aa, "NNN"))
    return "".join(dna_parts)


def build_dnachisel_constraint(
    constraint_type: str, params: Dict[str, Any], codon_table_id: str = "e_coli_316407"
) -> Optional[Any]:
    try:
        # Strip caller-supplied location; free-interval locations are applied later.
        clean = {k: v for k, v in params.items() if k != "location"}
        if constraint_type == "EnforceGCContent":
            return dc.EnforceGCContent(**clean)
        elif constraint_type == "AvoidHairpins":
            return dc.AvoidHairpins(**clean)
        elif constraint_type == "AvoidPattern":
            pattern = clean.get("pattern")
            if isinstance(pattern, dict) and pattern.get("type") == "RepeatedKmerPattern":
                rep_params = pattern.get("params", {})
                k_size = rep_params.get("k_size") or rep_params.get("k")
                n_repeats = rep_params.get("n_repeats") or rep_params.get("n")
                if k_size is None or n_repeats is None:
                    logger.warning(
                        f"RepeatedKmerPattern missing k_size or n_repeats in {rep_params}"
                    )
                    return None
                from dnachisel.SequencePattern import RepeatedKmerPattern

                # dnachisel names it kmer_size; callers (and the frontend
                # defaults) use k_size.
                return dc.AvoidPattern(
                    RepeatedKmerPattern(n_repeats=int(n_repeats), kmer_size=int(k_size))
                )
            else:
                return dc.AvoidPattern(pattern)
        elif constraint_type == "AvoidRareCodons":
            merged = {"species": codon_table_id, **clean}
            return dc.AvoidRareCodons(**merged)
        elif constraint_type == "UniquifyAllKmers":
            return dc.UniquifyAllKmers(**clean)
        elif constraint_type == "AvoidInvertedRepeats":
            return AvoidInvertedRepeats(**clean)
        elif constraint_type == "AvoidConsecutiveCodons":
            return AvoidConsecutiveCodons(**clean)
        else:
            logger.warning(f"Unknown constraint type: {constraint_type}")
            return None
    except Exception as e:
        logger.error(f"Failed to build constraint {constraint_type} with params {params}: {e}")
        return None


def resolve_fixed_mask(
    protein_seq: str, fixed: Optional[Sequence[bool]]
) -> List[bool]:
    """Return a per-residue fixed mask.

    When ``fixed`` is omitted, every stop (``*``) is frozen as TAA.
    When present, it is the complete mask and must match the protein length;
    only stop residues, or a leading Met (M), may be marked fixed.
    """
    if fixed is None:
        return [aa == "*" for aa in protein_seq]
    if len(fixed) != len(protein_seq):
        raise ValueError(
            f"fixed mask length {len(fixed)} does not match protein length {len(protein_seq)}"
        )
    mask = [bool(v) for v in fixed]
    for i, (aa, is_fixed) in enumerate(zip(protein_seq, mask)):
        if not is_fixed:
            continue
        if aa == "*":
            continue
        if aa == "M" and i == 0:
            continue
        raise ValueError(
            f"Residue {i} is marked fixed but is '{aa}'; "
            "only stop (*) or a leading Met (M) can be fixed"
        )
    return mask


def fixed_codon_dna(aa: str) -> str:
    """Exact DNA written for a fixed residue."""
    if aa == "*":
        return FIXED_STOP_DNA
    if aa == "M":
        return FIXED_START_DNA
    raise ValueError(f"No fixed codon defined for amino acid '{aa}'")


def fixed_nt_indices(fixed_mask: Sequence[bool]) -> List[int]:
    """Expand per-residue fixed flags to nucleotide indexes (codon = 3 nt)."""
    indices: List[int] = []
    for i, is_fixed in enumerate(fixed_mask):
        if is_fixed:
            base = 3 * i
            indices.extend([base, base + 1, base + 2])
    return indices


def free_intervals(seq_len: int, fixed_indices: Sequence[int]) -> List[Tuple[int, int]]:
    """Inclusive-start, exclusive-end nucleotide intervals that are not fixed."""
    fixed_set = set(fixed_indices)
    intervals: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i in range(seq_len):
        if i in fixed_set:
            if start is not None:
                intervals.append((start, i))
                start = None
        elif start is None:
            start = i
    if start is not None:
        intervals.append((start, seq_len))
    return intervals


def _constraint_min_span(constraint: Any) -> int:
    """Minimum interval length for a constraint to be meaningful."""
    window = getattr(constraint, "window", None)
    if window is not None:
        try:
            return max(1, int(window))
        except (TypeError, ValueError):
            pass
    hairpin_window = getattr(constraint, "hairpin_window", None)
    if hairpin_window is not None:
        try:
            return max(1, int(hairpin_window))
        except (TypeError, ValueError):
            pass
    k = getattr(constraint, "k", None)
    if k is not None:
        try:
            return max(1, int(k))
        except (TypeError, ValueError):
            pass
    pattern = getattr(constraint, "pattern", None)
    if pattern is not None:
        size = getattr(pattern, "size", None)
        if size is not None:
            try:
                return max(1, int(size))
            except (TypeError, ValueError):
                pass
        if isinstance(pattern, str):
            return max(1, len(pattern))
    return 3


def _apply_fixed_dna(dna: str, protein: str, fixed_mask: Sequence[bool]) -> str:
    """Overwrite each fixed codon with its frozen DNA (TAA for stop, ATG for start Met)."""
    chars = list(dna)
    for i, is_fixed in enumerate(fixed_mask):
        if not is_fixed:
            continue
        start = 3 * i
        codon = fixed_codon_dna(protein[i])
        chars[start : start + 3] = list(codon)
    return "".join(chars)


def _localize_constraints(
    base_constraints: List[Any], intervals: List[Tuple[int, int]]
) -> List[Any]:
    localized: List[Any] = []
    for constraint in base_constraints:
        # Runs and other sequence-wide specs must see the whole construct.
        if getattr(constraint, "keep_global", False):
            localized.append(constraint)
            continue
        min_span = _constraint_min_span(constraint)
        for start, end in intervals:
            if end - start < min_span:
                continue
            localized.append(
                constraint.copy_with_changes(location=dc.Location(start, end))
            )
    return localized


def _with_coding_frame(constraints: List[Any], frame: int) -> List[Any]:
    """Pin AvoidConsecutiveCodons to this design's coding frame."""
    bound: List[Any] = []
    for constraint in constraints:
        if isinstance(constraint, AvoidConsecutiveCodons):
            bound.append(constraint.copy_with_changes(frame=frame))
        else:
            bound.append(constraint)
    return bound


def _coding_frame_of(design_id: str, frames: Dict[str, int]) -> int:
    if design_id not in frames:
        return 0
    frame = int(frames[design_id])
    if frame not in (0, 1, 2):
        raise ValueError(f"coding frame for {design_id} must be 0, 1 or 2, got {frame}")
    return frame


def _codon_optimize_objectives(
    codon_table_id: str, method: str, intervals: List[Tuple[int, int]]
) -> List[Any]:
    objectives: List[Any] = []
    for start, end in intervals:
        if (end - start) < 3 or (end - start) % 3 != 0:
            continue
        objectives.append(
            dc.CodonOptimize(
                species=codon_table_id,
                method=method,
                location=dc.Location(start, end),
            )
        )
    return objectives


def _solve_once(
    initial_dna: str,
    seq_constraints: List[Any],
    objectives: List[Any],
) -> str:
    problem = dc.DnaOptimizationProblem(
        sequence=initial_dna,
        constraints=seq_constraints,
        objectives=objectives,
    )
    captured = io.StringIO()
    with redirect_stdout(captured):
        problem.resolve_constraints()
        problem.optimize()
    return problem.sequence


def _optimize_with_retries(
    design_id: str,
    initial_dna: str,
    seq_constraints: List[Any],
    objectives: List[Any],
) -> Dict[str, Optional[str]]:
    """Solve one design, retrying stochastic "no solution" failures."""
    for attempt in range(1, OPTIMIZATION_ATTEMPTS + 1):
        try:
            return {
                "optimized_dna": _solve_once(initial_dna, seq_constraints, objectives),
                "error": None,
            }
        except dc.NoSolutionError as e:
            if attempt < OPTIMIZATION_ATTEMPTS:
                logger.warning(
                    f"No solution found for {design_id} "
                    f"(attempt {attempt}/{OPTIMIZATION_ATTEMPTS}); retrying: {e}"
                )
                continue
            logger.error(
                f"No solution found for {design_id} after {OPTIMIZATION_ATTEMPTS} attempts: {e}"
            )
            return {"optimized_dna": None, "error": _NO_SOLUTION_MESSAGE}
        except Exception as e:
            logger.exception(f"Exception during optimization of {design_id}")
            return {"optimized_dna": None, "error": str(e)}
    return {"optimized_dna": None, "error": _NO_SOLUTION_MESSAGE}


def _pieces_from_mixed_sequence(
    seq: str, fixed_mask: Optional[Sequence[bool]]
) -> List[Tuple[str, str, bool, int, int]]:
    """Split a construct into literal nucleotides and amino-acid codons.

    Lowercase ``acgt`` are literal bases (one nucleotide, always frozen).
    Every other character is one residue (three nucleotides). Returns
    ``(kind, char, fixed, nt_start, nt_end)`` with ``kind`` ``"nt"`` or ``"aa"``.
    """
    if fixed_mask is not None and len(fixed_mask) != len(seq):
        raise ValueError(
            f"fixed mask length {len(fixed_mask)} does not match protein length {len(seq)}"
        )
    pieces: List[Tuple[str, str, bool, int, int]] = []
    nt = 0
    seen_aa = False
    for i, ch in enumerate(seq):
        if ch in _LITERAL_NT:
            pieces.append(("nt", ch.upper(), True, nt, nt + 1))
            nt += 1
            continue
        aa = ch.upper()
        if fixed_mask is None:
            is_fixed = aa == "*"
        else:
            is_fixed = bool(fixed_mask[i])
        if is_fixed and aa != "*" and not (aa == "M" and not seen_aa):
            raise ValueError(
                f"Residue {i} is marked fixed but is '{aa}'; "
                "only stop (*) or a leading Met (M) can be fixed"
            )
        seen_aa = True
        pieces.append(("aa", aa, is_fixed, nt, nt + 3))
        nt += 3
    return pieces


def _codon_intervals_for_blocks(
    blocks: Sequence[Tuple[int, int]], free: Sequence[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Free nucleotide spans snapped onto each coding block's codon grid."""
    snapped: List[Tuple[int, int]] = []
    for b0, b1 in blocks:
        for start, end in free:
            lo, hi = max(start, b0), min(end, b1)
            if hi <= lo:
                continue
            offset = (lo - b0) % 3
            if offset:
                lo += 3 - offset
            hi -= (hi - b0) % 3
            if hi - lo >= 3:
                snapped.append((lo, hi))
    return snapped


def optimize_sequences(
    sequences: Dict[str, str],
    codon_table_id: str,
    constraints: List[Dict[str, Any]],
    method: str = "match_codon_usage",
    fixed: Optional[Dict[str, List[bool]]] = None,
    frame: Optional[Dict[str, int]] = None,
) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Optimizes a batch of protein sequences.
    Returns: { design_id: {"optimized_dna": str | None, "error": str | None} }

    ``fixed`` maps design_id -> per-residue booleans. Residues marked true must be
    stops and are frozen as TAA, excluded from codon optimisation and user
    constraints. When a design_id is absent from ``fixed``, every ``*`` in that
    protein is treated as fixed.

    Lowercase ``acgt`` in a sequence are literal nucleotides from a custom
    addition (not amino acids). They stay frozen in the DNA and are not part of
    the codon grid. ``frame`` maps design_id -> 0, 1 or 2, the offset at which
    the design and preset-tag codons begin; ``AvoidConsecutiveCodons`` reads
    codons from there. Other constraints still see the whole construct.

    A design that fails with ``NoSolutionError`` is solved again from the same
    starting sequence, up to ``OPTIMIZATION_ATTEMPTS`` times, before that error
    is returned. Other errors are returned on the first failure.
    """
    results: Dict[str, Dict[str, Optional[str]]] = {}
    fixed = fixed or {}
    frame = frame or {}

    parsed_constraints: List[Any] = []
    for c in constraints:
        if not c.get("enabled", True):
            continue
        dc_c = build_dnachisel_constraint(c["type"], c.get("params", {}), codon_table_id)
        if dc_c:
            parsed_constraints.append(dc_c)

    for design_id, protein_seq in sequences.items():
        if not protein_seq:
            results[design_id] = {"optimized_dna": None, "error": "Empty sequence"}
            continue

        try:
            design_fixed = fixed.get(design_id) if design_id in fixed else None
            coding_frame = _coding_frame_of(design_id, frame)
            user_constraints = _with_coding_frame(parsed_constraints, coding_frame)
            has_literal = any(ch in _LITERAL_NT for ch in protein_seq)

            if has_literal:
                pieces = _pieces_from_mixed_sequence(protein_seq, design_fixed)
                aa_only = "".join(char for kind, char, _fixed, _s, _e in pieces if kind == "aa")
                naive_aa = _naive_translate_protein(aa_only, codon_table_id)
                dna_chars: List[str] = []
                aa_cursor = 0
                for kind, char, is_fixed, _start, _end in pieces:
                    if kind == "nt":
                        dna_chars.append(char)
                        continue
                    codon = naive_aa[aa_cursor : aa_cursor + 3]
                    aa_cursor += 3
                    if is_fixed:
                        codon = fixed_codon_dna(char)
                    dna_chars.append(codon)
                initial_dna = "".join(dna_chars)
                fixed_indices = [
                    i
                    for kind, _char, is_fixed, start, end in pieces
                    if kind == "nt" or is_fixed
                    for i in range(start, end)
                ]
                blocks = []
                block_start: Optional[int] = None
                block_aa: List[str] = []
                for kind, char, _is_fixed, start, end in pieces:
                    if kind == "aa":
                        if block_start is None:
                            block_start = start
                        block_aa.append(char)
                    elif block_start is not None:
                        blocks.append((block_start, start, "".join(block_aa)))
                        block_start = None
                        block_aa = []
                if block_start is not None:
                    blocks.append((block_start, len(initial_dna), "".join(block_aa)))
            else:
                protein = protein_seq.upper()
                fixed_mask = resolve_fixed_mask(protein, design_fixed)
                initial_dna = _apply_fixed_dna(
                    _naive_translate_protein(protein, codon_table_id),
                    protein,
                    fixed_mask,
                )
                fixed_indices = fixed_nt_indices(fixed_mask)
                blocks = [(0, len(initial_dna), protein)] if protein else []

            intervals = free_intervals(len(initial_dna), fixed_indices)

            if not intervals:
                results[design_id] = {"optimized_dna": initial_dna, "error": None}
                continue

            translation_constraints = [
                dc.EnforceTranslation(translation=aa, location=dc.Location(start, end))
                for start, end, aa in blocks
                if aa and (end - start) == 3 * len(aa)
            ]
            codon_intervals = _codon_intervals_for_blocks(
                [(start, end) for start, end, _aa in blocks], intervals
            )
            objectives = _codon_optimize_objectives(codon_table_id, method, codon_intervals)

            if fixed_indices:
                seq_constraints = [
                    *_localize_constraints(user_constraints, intervals),
                    dc.AvoidChanges(indices=fixed_indices),
                    *translation_constraints,
                ]
            else:
                seq_constraints = [
                    *user_constraints,
                    *translation_constraints,
                ]

            if not objectives:
                results[design_id] = {"optimized_dna": initial_dna, "error": None}
                continue
        except ValueError as e:
            results[design_id] = {"optimized_dna": None, "error": str(e)}
            continue
        except Exception as e:
            logger.exception(f"Exception preparing optimization of {design_id}")
            results[design_id] = {"optimized_dna": None, "error": str(e)}
            continue

        results[design_id] = _optimize_with_retries(
            design_id, initial_dna, seq_constraints, objectives
        )

    return results
