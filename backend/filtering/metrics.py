"""Canonical metric name mapping across run types.

BinderDash run types (boltzgen, rfd, rfd3, bindcraft) name conceptually similar
metrics differently. This module provides a convenience mapping layer; the filtering
engine itself operates on raw DataFrame column names and does not require a metric to
be listed here.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Union, cast

import pandas as pd

# BindCraft writes one column per AF2 model replicate (always exactly 5: 1_pLDDT ..
# 5_pLDDT, 1_i_pTM .. 5_i_pTM, etc.) alongside the already-present Average_* aggregate.
# These are noise for filtering/ranking purposes (redundant with the Average_* column,
# and there are 5x as many of them) — excluded from the available-columns listing so
# they don't clutter the Hard Filters / Ranking Metrics column pickers.
_PER_REPLICATE_COLUMN_RE = re.compile(r"^\d+_")


def is_excluded_metric_column(name: str) -> bool:
    # ``__tc_*`` are virtual columns materialised per request for target-contact
    # conditions (see filtering.target_contacts_service); they are not data a user
    # could pick from the column list.
    if name.startswith("__tc_"):
        return True
    return bool(_PER_REPLICATE_COLUMN_RE.match(name))


# canonical name -> {method: raw column name(s)}. A method missing from the dict, or
# mapped to None, means that method has no equivalent for the metric. A list is a set
# of fallback candidates tried in order (first one present in the data wins) — used
# when a column is only sometimes available for that method, e.g. rfd runs that were
# optionally re-scored via a downstream Boltz-pulldown step.
METRIC_ALIASES: Dict[str, Dict[str, Optional[Union[str, List[str]]]]] = {
    "iptm": {
        "boltzgen": "design_to_target_iptm",
        "rfd3": "iptm",
        "bindcraft": "Average_i_pTM",
        # rfd has no native iptm; if the run was re-scored via Boltz pulldown,
        # boltz_iptm may be present as an extra column.
        "rfd": ["boltz_iptm"],
        "bindcraft2": "i_pTM",
        # Interface pTM for the chain of interest (the binder), from the oracle's
        # inline metrics table; rescaled to 0-1 on merge.
        "rfd4_proteina": "oracle_ppi_iptm_coi",
    },
    # Interface ipSAE (higher is better, same 0–1 sense as iptm). BindCraft and
    # plain RFdiffusion do not write an ipSAE column.
    "ipsae": {
        "boltzgen": "design_ipsae_min",
        "rfd3": "rf3_ipsae_min",
    },
    "ptm": {
        "boltzgen": "design_ptm",
        "bindcraft": "Average_pTM",
        "rfd3": "ptm",
        "bindcraft2": "pTM",
        "rfd4_proteina": "oracle_ppi_overall_ptm",
    },
    # Binder-chain confidence (pLDDT), not the complex-wide average. Candidates are
    # tried in order; a method with none of them present has no equivalent.
    "binder_plddt": {
        "bindcraft": "Average_Binder_pLDDT",
        "rfd": ["plddt_binder", "plddt"],
        # BoltzGen's final metrics table often has no pLDDT column (see boltzgen
        # issue #202); these are the names that appear when a run does carry one.
        "boltzgen": ["complex_plddt", "design_plddt"],
        "rfd3": ["plddt"],
        # BindCraft2's bare ``pLDDT`` is the binder chain's, not the complex average:
        # in the ranked mmCIF the binder chain's mean B-factor matches ``pLDDT`` and the
        # target chain's matches ``Target_pLDDT``. ``Unbound_Binder_pLDDT`` is the binder
        # predicted in isolation, a different quantity, so it is not a fallback here.
        "bindcraft2": "pLDDT",
        # ``_coi`` is the chain of interest, which for a binder run is the binder.
        "rfd4_proteina": "oracle_ppi_plddt_coi",
    },
    "rmsd": {
        "boltzgen": "bb_rmsd",
        "rfd": "rmsd",
        "rfd3": "rf3_rmsd_target_aligned_binder_rmsd_all",
        # BindCraft's results table reports the AF2-model-averaged column; a bare
        # Binder_RMSD does not exist there, so canonical "rmsd" silently resolved to
        # nothing for every bindcraft design (it is kept as a fallback candidate in
        # case an older/derived table has it).
        "bindcraft": ["Average_Binder_RMSD", "Binder_RMSD"],
        "bindcraft2": "Binder_RMSD",
        "rfd4_proteina": "refolded_target_aligned_binder_rmsd_rmsd",
    },
    "pae_interaction": {
        "rfd": "pae_interaction",
        "rfd3": "pair_pae",
        "boltzgen": "interaction_pae",
        "bindcraft": "Average_i_pAE",
        "bindcraft2": "i_pAE",
        # Mean interface PAE, in angstroms (not rescaled). ``min_ipae_coi`` is the
        # best single contact, a different statistic, so it stays a raw column.
        "rfd4_proteina": "oracle_ppi_ipae_coi",
    },
    "sequence": {
        "boltzgen": "designed_sequence",
        "rfd": "seq",
        "rfd3": "sequence",
        # ``_standardise_dataframe_columns`` folds ``sequence`` / ``Binder_Sequence``
        # into ``Sequence`` before the design reaches the cache.
        "rfd4_proteina": "Sequence",
        "bindcraft": "Sequence",
        "bindcraft2": "Sequence",
    },
    "design_id": {
        "boltzgen": "id",
        "rfd": "description",
        "rfd3": "id",
        "rfd4_proteina": "id",
        "bindcraft": "Design",
        "bindcraft2": "design",
    },
    "hbonds": {
        "boltzgen": "plip_hbonds_refolded",
        "bindcraft": "Average_n_InterfaceHbonds",
    },
    "saltbridge": {
        "boltzgen": "plip_saltbridge_refolded",
    },
    # Buried/change-in-solvent-accessible-surface-area at the binder-target interface
    # upon complex formation, as reported by the provider's own pipeline (refolded
    # structure for boltzgen, AF2-model-averaged for bindcraft) — distinct from
    # Binderdash's own independently-computed `binderdash_delta_sasa` (as-generated
    # structure, any method; see filtering.structural_metrics), which is deliberately
    # not folded into this alias to avoid conflating two different computations of a
    # similar-but-not-identical quantity under one name.
    "delta_sasa": {
        "boltzgen": "delta_sasa_refolded",
        "bindcraft": "Average_dSASA",
        "bindcraft2": "Interface_BuriedArea",
    },
    # BindCraft2's own ranking metric: a distance-masked interface confidence
    # derived from the interface PAE, 0-1, higher better. No other run type
    # writes an equivalent.
    "ipdae": {
        "bindcraft2": "i_pDAE",
    },
}

# canonical metric -> (higher_is_better, one-line meaning). Shared by MCP, REST
# ColumnInfo, and Filtering UI defaults. Identifiers/sequences are excluded below.
METRIC_DIRECTIONS: Dict[str, tuple[bool, str]] = {
    "iptm": (True, "Interface pTM: predicted accuracy of the binder-target interface, 0-1."),
    "ipsae": (True, "Interface ipSAE: interaction score from aligned error, 0-1. Higher is better."),
    "ptm": (True, "pTM: predicted accuracy of the whole complex, 0-1."),
    "binder_plddt": (True, "Binder-chain pLDDT: local confidence of the designed chain."),
    "rmsd": (False, "Backbone RMSD of the refolded/predicted binder against the design, Angstrom."),
    "pae_interaction": (False, "Predicted aligned error across the interface, Angstrom."),
    "hbonds": (True, "Hydrogen bonds across the interface."),
    "saltbridge": (True, "Salt bridges across the interface."),
    "delta_sasa": (True, "Interface area buried on complex formation, Angstrom^2."),
    "ipdae": (True, "Distance-masked interface confidence, 0-1 (BindCraft2 ranking metric)."),
}

# Metrics that are identifiers/sequences rather than scores — rankable never.
NON_SCORE_METRICS = {"sequence", "design_id"}

# raw column name -> canonical name. Best-effort: a raw column can only report one
# canonical name even if two concepts shared a raw name; first-registered wins.
RAW_TO_CANONICAL: Dict[str, str] = {}
for _canonical, _by_method in METRIC_ALIASES.items():
    for _raw in _by_method.values():
        _cands = [_raw] if isinstance(_raw, str) else (_raw or [])
        for _c in _cands:
            RAW_TO_CANONICAL.setdefault(_c, _canonical)


def _candidates(raw: Optional[Union[str, List[str]]]) -> List[str]:
    if raw is None:
        return []
    return [raw] if isinstance(raw, str) else raw


def higher_is_better(name: str) -> Optional[bool]:
    """Known sort direction for a canonical metric or a raw alias thereof.

    Returns ``None`` for unknown columns and non-score metrics (``sequence``,
    ``design_id``).
    """
    if name in NON_SCORE_METRICS:
        return None
    entry = METRIC_DIRECTIONS.get(name)
    if entry is not None:
        return entry[0]
    canonical = RAW_TO_CANONICAL.get(name)
    if canonical is None or canonical in NON_SCORE_METRICS:
        return None
    mapped = METRIC_DIRECTIONS.get(canonical)
    return mapped[0] if mapped is not None else None


def default_numeric_operator(name: str) -> str:
    """Sensible hard-filter operator for ``name``: ``>`` if higher-is-better, else ``<``."""
    return ">" if higher_is_better(name) is True else "<"


def resolve_column(canonical_or_raw: str, method: str, columns: List[str]) -> Optional[str]:
    """Resolve a canonical metric name (or a raw column name) to an actual column.

    Falls back to treating the input as a raw column name if there is no canonical
    mapping for it, or no mapping exists for ``method``. When a canonical name maps to
    several fallback candidates for ``method`` (e.g. an optional column that's only
    sometimes present), the first candidate found in ``columns`` wins.
    """
    mapping = METRIC_ALIASES.get(canonical_or_raw)
    if mapping is not None:
        for raw in _candidates(mapping.get(method)):
            if raw in columns:
                return raw
        return None
    if canonical_or_raw in columns:
        return canonical_or_raw
    return None


def resolve_column_per_row(
    df: pd.DataFrame, canonical_or_raw: str, method_column: str = "method"
) -> pd.Series:
    """Build a Series with, per-row, the value of ``canonical_or_raw`` resolved via that
    row's method. Used when a filter/ranking metric is applied across an aggregate of
    runs from different methods.
    """
    if canonical_or_raw not in METRIC_ALIASES:
        if canonical_or_raw in df.columns:
            return cast(pd.Series, df[canonical_or_raw])
        return pd.Series(pd.NA, index=df.index, dtype="float64")

    mapping = METRIC_ALIASES[canonical_or_raw]
    result = pd.Series(index=df.index, dtype="float64")
    for method, group in df.groupby(method_column):
        raw_col = next(
            (c for c in _candidates(mapping.get(str(method))) if c in df.columns), None
        )
        if raw_col:
            result.loc[group.index] = df.loc[group.index, raw_col]
        else:
            result.loc[group.index] = pd.NA
    return result


def resolve_column_map_for_methods(
    canonical_name: str, methods: List[str], columns: List[str]
) -> Dict[str, Optional[str]]:
    """Per-method raw-column resolution for a canonical metric name.

    Returns ``{method: raw_col_or_None}``. ``None`` means no candidate for that method
    is present in ``columns`` — i.e. that method has no equivalent for this metric at
    all (as opposed to having the column but a null value for a particular design),
    which callers use to *exempt* (not fail) that method's rows from a filter on this
    metric rather than penalise them for a concept that doesn't apply to them.
    """
    mapping = METRIC_ALIASES.get(canonical_name, {})
    result: Dict[str, Optional[str]] = {}
    for method in methods:
        result[method] = next(
            (c for c in _candidates(mapping.get(method)) if c in columns), None
        )
    return result


def available_columns_for_methods_pandas(
    df: pd.DataFrame, method_column: str = "method"
) -> Dict[str, List[str]]:
    """Numeric and boolean columns actually populated (at least one non-null value) for each method
    in ``df`` (pandas variant). A column that's numeric-dtype but entirely null for a
    given method (because it's another method's column in the union schema) is *not*
    reported as present for that method.
    """
    result: Dict[str, List[str]] = {}
    if method_column not in df.columns:
        return result
    for method, group in df.groupby(method_column):
        cols = group.select_dtypes(include=["number", "bool"]).columns
        present = [c for c in cols if group[c].notna().any()]
        result[str(method)] = present
    return result


def available_columns_for_methods(df, method_column: str = "method") -> Dict[str, List[str]]:
    """Numeric and boolean columns actually populated (at least one non-null value) for each method
    in ``df`` (polars.DataFrame, used by ``filtering.service`` — the pandas variant
    above is kept for standalone/test use of the other metrics.py helpers, which still
    operate on pandas). A column that's numeric-dtype but entirely null for a given
    method (because it's another method's column in the union schema) is *not* reported
    as present for that method — callers (e.g. the "Present in runs" / "Equivalent
    columns" UI, and canonical per-method raw-column resolution) rely on this to tell
    "this method has the metric" apart from "this method has no equivalent at all".
    """
    import polars as pl

    result: Dict[str, List[str]] = {}
    if not isinstance(df, pl.DataFrame):
        return available_columns_for_methods_pandas(df, method_column=method_column)
    if method_column not in df.columns:
        return result
    # Booleans alongside numerics: a pipeline's own pass/fail flag (RFD4-Proteina's
    # ``ppi_pass``, say) is a filterable column too, and the picker renders it as a
    # yes/no choice rather than a threshold.
    cols = sorted(
        c
        for c, dt in zip(df.columns, df.dtypes)
        if dt.is_numeric() or dt == pl.Boolean
    )
    for method in df[method_column].unique().to_list():
        sub = df.filter(pl.col(method_column) == method)
        present = [c for c in cols if sub[c].drop_nulls().len() > 0]
        result[str(method)] = present
    return result
