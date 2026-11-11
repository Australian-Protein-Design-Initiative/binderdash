"""Tag presets and the default DNA-optimisation constraint set.

Served to the frontend as data (``GET /api/sequences/tag-presets``) so the table
exists in one place. Colours live here because they are part of the preset's
identity in the UI palette; the builder itself only uses ``kind`` and ``sequence``.
"""

from __future__ import annotations

from typing import Any, Dict, List

TAG_PRESET_DEFS: List[Dict[str, Any]] = [
    {"kind": "hisN", "tag_name": "His-N", "sequence": "HHHHHHSG", "color": "#1565c0",
     "background": "rgba(21, 101, 192, 0.12)", "foreground": "#0d47a1", "zones": ["n"]},
    {"kind": "hisC", "tag_name": "His-C", "sequence": "GSHHHHHH", "color": "#1565c0",
     "background": "rgba(21, 101, 192, 0.12)", "foreground": "#0d47a1", "zones": ["c"]},
    {"kind": "flag", "tag_name": "FLAG", "sequence": "DYKDDDDK", "color": "#2e7d32",
     "background": "rgba(46, 125, 50, 0.12)", "foreground": "#1b5e20", "zones": ["n", "c"]},
    {"kind": "cmyc", "tag_name": "cMyc", "sequence": "EQKLISEEDL", "color": "#ef6c00",
     "background": "rgba(239, 108, 0, 0.12)", "foreground": "#e65100", "zones": ["n", "c"]},
    {"kind": "ha", "tag_name": "HA", "sequence": "YPYDVPDYA", "color": "#7b1fa2",
     "background": "rgba(123, 31, 162, 0.1)", "foreground": "#6a1b9a", "zones": ["n", "c"]},
    {"kind": "avi", "tag_name": "AviTag", "sequence": "GLNDIFEAQKIEWHE", "color": "#00838f",
     "background": "rgba(0, 131, 143, 0.12)", "foreground": "#006064", "zones": ["n", "c"]},
    {"kind": "strep", "tag_name": "Strep-tag II", "sequence": "WSHPQFEK", "color": "#5e35b1",
     "background": "rgba(94, 53, 177, 0.12)", "foreground": "#4527a0", "zones": ["n", "c"]},
    {"kind": "ctag", "tag_name": "C-tag", "sequence": "EPEA", "color": "#6d4c41",
     "background": "rgba(109, 76, 65, 0.12)", "foreground": "#4e342e", "zones": ["c"]},
    # No leading Met: a start codon has to come from the vector (e.g. NdeI) or the design.
    {"kind": "pelb", "tag_name": "pelB", "sequence": "KYLLPTAAAGLLLLAAQPAMA", "color": "#c2185b",
     "background": "rgba(194, 24, 91, 0.12)", "foreground": "#880e4f", "zones": ["n"], "always": True},
    {"kind": "snac", "tag_name": "SNAC-tag", "sequence": "GSHHW", "display_sequence": "G↓SHHW",
     "color": "#00796b", "background": "rgba(0, 121, 107, 0.12)", "foreground": "#004d40",
     "zones": ["n", "c"]},
    {"kind": "tev", "tag_name": "TEV-site", "sequence": "ENLYFQS", "display_sequence": "ENLYFQ↓S",
     "color": "#303f9f", "background": "rgba(48, 63, 159, 0.12)", "foreground": "#1a237e",
     "zones": ["n", "c"]},
    {"kind": "linker", "tag_name": "G4S", "sequence": "GGGGS", "color": "#aaaaaa",
     "background": "rgba(48, 48, 48, 0.1)", "foreground": "#aaaaaa", "zones": ["n", "c"]},
    {"kind": "stop", "tag_name": "STOP*", "sequence": "*", "color": "#b23a3a",
     "background": "rgba(178, 58, 58, 0.15)", "foreground": "#8b1e1e", "zones": ["n", "c"]},
]

CUSTOM_TAG_VISUAL: Dict[str, str] = {
    "color": "#aa0000",
    "background": "rgba(69, 90, 100, 0.1)",
    "foreground": "#37474f",
}

DEFAULT_TWIST_CONSTRAINTS: List[Dict[str, Any]] = [
    {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.25, "maxi": 0.64}},
    {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.35, "maxi": 0.75, "window": 50}},
    {"type": "AvoidHairpins", "enabled": True, "params": {"stem_size": 20, "hairpin_window": 48}},
    {"type": "AvoidPattern", "enabled": True, "params": {"pattern": "AAAAAAAAA"}},
    {"type": "AvoidPattern", "enabled": True, "params": {"pattern": "TTTTTTTTT"}},
    {"type": "AvoidPattern", "enabled": True, "params": {"pattern": "GGGGGG"}},
    {"type": "AvoidPattern", "enabled": True, "params": {"pattern": "CCCCCC"}},
    {"type": "AvoidRareCodons", "enabled": True, "params": {"min_frequency": 0.09}},
    {"type": "UniquifyAllKmers", "enabled": True, "params": {"k": 12}},
    {"type": "AvoidPattern", "enabled": True,
     "params": {"pattern": {"type": "RepeatedKmerPattern", "params": {"n_repeats": 2, "k_size": 20}}}},
    {"type": "AvoidInvertedRepeats", "enabled": True, "params": {"min_tm": 68}},
    {"type": "AvoidPattern", "enabled": True, "params": {"pattern": "GGAGG"}},
    {"type": "AvoidPattern", "enabled": True, "params": {"pattern": "TAAGGAG"}},
]

#: Default post-stop padding (lowercase = nucleotides).
DEFAULT_POST_STOP_PADDING = (
    "ttgtgttgcgatagcccagtatgatattctaaggcgttacgctgatgaatattctacggaattgcc"
    "ataggcgttgaacgctacacggacgatacgaatt"
)


def serialize_constraint_for_dnachisel(c: Dict[str, Any]) -> Dict[str, Any]:
    """``ExcludeRestrictionSite`` is UI sugar for an ``AvoidPattern`` on ``<enzyme>_site``.

    DnaChisel resolves the ``_site`` suffix through Biopython's restriction table.
    Unknown types pass through so future additions degrade gracefully.
    """
    if c.get("type") != "ExcludeRestrictionSite":
        return c
    enzyme = str((c.get("params") or {}).get("enzyme") or "").strip()
    return {
        "type": "AvoidPattern",
        "enabled": c.get("enabled", True),
        "params": {"pattern": f"{enzyme}_site" if enzyme else ""},
    }
