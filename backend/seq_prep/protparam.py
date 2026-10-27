"""Extinction coefficient, isoelectric point and per-sequence warnings.

Ported from ``frontend/src/utils/protParam.ts``, which follows BioPython's
``Bio.SeqUtils.ProtParam`` / ``IsoelectricPoint`` (Bjellqvist pKa tables).
Reimplemented rather than imported so the generated script needs no BioPython.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

WARNING_CONTAINS_CYS = "Contains Cys"
WARNING_LOW_EXTINCTION = "Low extinction coefficient at 280 nm (ε₂₈₀)"
#: ε₂₈₀ of a single Trp; constructs below it are hard to quantify by A280.
LOW_EXTINCTION_THRESHOLD = 5500

POSITIVE_PKS: Dict[str, float] = {"Nterm": 7.5, "K": 10.0, "R": 12.0, "H": 5.98}
NEGATIVE_PKS: Dict[str, float] = {"Cterm": 3.55, "D": 4.05, "E": 4.45, "C": 9.0, "Y": 10.0}
PK_N_TERMINAL: Dict[str, float] = {
    "A": 7.59, "M": 7.0, "S": 6.93, "P": 8.36, "T": 6.82, "V": 7.44, "E": 7.7
}
PK_C_TERMINAL: Dict[str, float] = {"D": 4.55, "E": 4.75}

_NON_ALPHA = re.compile(r"[^A-Z]")


def normalize_protein_sequence(raw: str) -> str:
    return _NON_ALPHA.sub("", raw.replace("*", "").upper())


def coding_sequence_before_stop(raw: str) -> str:
    """Coding residues before the first in-frame stop; used for warnings only."""
    i = raw.find("*")
    return normalize_protein_sequence(raw if i == -1 else raw[:i])


def molar_extinction_coefficient(aa: str) -> Tuple[int, int]:
    """Return ``(reduced, oxidized)`` at 280 nm."""
    s = normalize_protein_sequence(aa)
    reduced = s.count("W") * 5500 + s.count("Y") * 1490
    return reduced, reduced + (s.count("C") // 2) * 125


def isoelectric_point(aa: str) -> float:
    s = normalize_protein_sequence(aa)
    if not s:
        return float("nan")

    charged = {"Nterm": 1, "Cterm": 1}
    for residue in "KRHDECY":
        charged[residue] = s.count(residue)

    pos_pks = dict(POSITIVE_PKS)
    neg_pks = dict(NEGATIVE_PKS)
    if s[0] in PK_N_TERMINAL:
        pos_pks["Nterm"] = PK_N_TERMINAL[s[0]]
    if s[-1] in PK_C_TERMINAL:
        neg_pks["Cterm"] = PK_C_TERMINAL[s[-1]]

    def charge_at_ph(ph: float) -> float:
        positive = sum(
            charged.get(aa_, 0) * (1.0 / (10 ** (ph - pk) + 1.0))
            for aa_, pk in pos_pks.items()
        )
        negative = sum(
            charged.get(aa_, 0) * (1.0 / (10 ** (pk - ph) + 1.0))
            for aa_, pk in neg_pks.items()
        )
        return positive - negative

    ph, lo, hi = 7.775, 4.05, 12.0
    while True:
        charge = charge_at_ph(ph)
        if hi - lo <= 0.0001:
            return ph
        if charge > 0:
            lo = ph
        else:
            hi = ph
        ph = (lo + hi) / 2


def sequence_warnings(aa: str) -> List[str]:
    s = coding_sequence_before_stop(aa)
    warnings: List[str] = []
    if "C" in s:
        warnings.append(WARNING_CONTAINS_CYS)
    if molar_extinction_coefficient(s)[0] < LOW_EXTINCTION_THRESHOLD:
        warnings.append(WARNING_LOW_EXTINCTION)
    return warnings
