"""Codon table used for reverse translation.

Ported from ``frontend/src/stores/seqPrep.ts``. The forward table picks the most
frequent codon per amino acid, tie-broken by codon name, which matches
``optimize._naive_translate_protein``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

FIXED_STOP_DNA = "TAA"
FIXED_START_DNA = "ATG"

# Offline / API-failure fallback; matches the frontend's hardcoded E. coli table.
ECOLI_FORWARD: Dict[str, str] = {
    "A": "GCT", "R": "CGT", "N": "AAC", "D": "GAT", "C": "TGC", "Q": "CAG",
    "E": "GAA", "G": "GGT", "H": "CAT", "I": "ATT", "L": "CTG", "K": "AAA",
    "M": "ATG", "F": "TTC", "P": "CCT", "S": "TCT", "T": "ACC", "W": "TGG",
    "Y": "TAT", "V": "GTT", "*": "TAA", "X": "GCT",
}


def _build_reverse(
    forward: Dict[str, str], primary_stop: str, all_stops: Optional[List[str]] = None
) -> Dict[str, str]:
    reverse = {
        codon.upper(): aa for aa, codon in forward.items() if aa != "*"
    }
    stops = list(dict.fromkeys(s.upper() for s in (all_stops or [primary_stop])))
    for sc in stops:
        reverse[sc] = "*"
    return reverse


@dataclass(frozen=True)
class CodonTable:
    label: str
    forward: Dict[str, str]
    reverse: Dict[str, str]
    stop: str = FIXED_STOP_DNA

    @classmethod
    def ecoli_fallback(cls) -> "CodonTable":
        return cls(
            label="E. coli",
            forward=dict(ECOLI_FORWARD),
            reverse=_build_reverse(ECOLI_FORWARD, "TAA", ["TAA", "TAG", "TGA"]),
            stop="TAA",
        )

    @classmethod
    def from_detail(
        cls,
        label: str,
        stop_codons: List[str],
        codons_by_aa: Dict[str, Dict[str, float]],
    ) -> "CodonTable":
        """Build from the shape ``util.codon_tables.load_codon_table_detail`` returns."""
        stops = [s.upper() for s in stop_codons]
        stop = stops[0] if stops else FIXED_STOP_DNA
        forward: Dict[str, str] = {}
        for aa, freqs in codons_by_aa.items():
            if aa == "*" or not freqs:
                continue
            # Most frequent first, ties broken by codon name, as the frontend does.
            best = sorted(freqs.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            forward[aa] = best.upper()
        # The frontend substitutes Ala (or Leu) for unknown residues rather than
        # emitting NNN, so a construct containing X still reverse-translates.
        forward.setdefault("X", forward.get("A") or forward.get("L") or "GCT")
        forward["*"] = stop
        return cls(
            label=label,
            forward=forward,
            reverse=_build_reverse(forward, stop, stops),
            stop=stop,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "forward": dict(self.forward),
            "stop_codons": sorted({c for c, aa in self.reverse.items() if aa == "*"}),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, object]) -> "CodonTable":
        forward = dict(d["forward"])  # type: ignore[arg-type]
        stops = [str(s) for s in d.get("stop_codons") or [FIXED_STOP_DNA]]
        return cls(
            label=str(d.get("label") or ""),
            forward=forward,
            reverse=_build_reverse(forward, stops[0], stops),
            stop=stops[0],
        )
