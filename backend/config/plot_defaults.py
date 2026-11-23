"""Default scatter X/Y columns per pipeline when the plots UI loads."""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# Ordered fallbacks: first column name present in the dataframe wins.
PLOT_DEFAULT_XY_BY_METHOD: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "bindcraft": {
        "x": ("Average_pLDDT", "mean_plddt", "plddt"),
        "y": ("Average_i_pTM", "ipTM"),
    },
    "rfd": {
        "x": ("plddt_binder", "plddt"),
        "y": ("pae_interaction", "pae_binder"),
    },
    "rfd3": {
        "x": ("rf3_ipsae_min", "pair_pae"),
        "y": ("iptm",),
    },
    # RFD4-Proteina's scores are merged in from the oracle's inline metrics table;
    # consensus_z only exists when the run was also refolded (--refold_with). Column
    # names are post-standardisation ("Length") and post-merge.
    "rfd4_proteina": {
        "x": ("oracle_ppi_plddt_coi", "Length"),
        "y": ("oracle_ppi_iptm_coi", "consensus_z"),
    },
    "bindcraft2": {
        "x": ("pLDDT", "i_pAE"),
        "y": ("i_pTM", "i_pDAE"),
    },
}


def _first_present(columns: List[str], candidates: Tuple[str, ...]) -> str:
    colset = set(columns)
    for c in candidates:
        if c in colset:
            return c
    return ""


def default_plot_xy_columns(df: pd.DataFrame, method: str) -> Dict[str, str]:
    """Pick default numeric x/y for scatter plots; same logic as legacy ``get_default_plot_columns``."""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    defaults: Dict[str, str] = {"x": "", "y": ""}
    spec = PLOT_DEFAULT_XY_BY_METHOD.get(method, {})
    if spec:
        defaults["x"] = _first_present(numeric_cols, spec.get("x", ()))
        defaults["y"] = _first_present(numeric_cols, spec.get("y", ()))
    if not defaults["x"] and numeric_cols:
        defaults["x"] = numeric_cols[0]
    if not defaults["y"] and len(numeric_cols) > 1:
        defaults["y"] = numeric_cols[1]
    elif not defaults["y"] and numeric_cols:
        defaults["y"] = numeric_cols[0]
    return defaults
