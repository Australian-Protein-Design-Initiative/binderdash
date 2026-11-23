"""Score / metric column names as in source TSV/CSV headers (API and logs)."""

from __future__ import annotations

from typing import Dict

SCORE_FIELD_LABELS: Dict[str, str] = {
    "Average_i_pTM": "Average i-pTM",
    "Average_pLDDT": "Average pLDDT",
    "Average_Binder_pLDDT": "Average binder pLDDT",
    "pae_interaction": "PAE interaction",
    "design_to_target_iptm": "Design→Target ipTM",
    "iptm": "ipTM",
    "ipTM": "ipTM",
    "pair_pae": "Pair PAE",
    "rf3_ipsae_min": "RF3 ipSAE min",
    "rf3_rmsd_target_aligned_binder_rmsd_all": "RF3 RMSD (target-aligned binder)",
    "consensus_z": "Consensus z-score",
    "i_pDAE": "Interface pDAE (interface confidence)",
    "i_pAE": "Interface PAE",
    "i_pTM": "Interface pTM",
    "Binder_RMSD": "Binder RMSD",
    "Hotspot_Contact_Fraction": "Hotspot contact fraction",
    "Coldspot_Contact_Fraction": "Coldspot contact fraction",
    "Off_Epitope_Contact_Fraction": "Off-epitope contact fraction",
    "Epitope_Residues_Contacted": "Epitope residues contacted",
    # RFD4-Proteina inline oracle metrics (merged from of3_/af3_inline_metrics.csv).
    # "coi" is the chain of interest, which for a binder run is the binder chain.
    # pTM / ipTM / pLDDT are rescaled from the file's 0-100 to 0-1 on merge; the PAE
    # and RMSD columns stay in angstroms.
    "oracle_ppi_iptm_coi": "Interface pTM, binder chain",
    "oracle_ppi_overall_iptm": "Interface pTM, whole complex",
    "oracle_ppi_iptm_A_1_B_1": "Interface pTM, chains A-B",
    "oracle_ppi_ptm_coi": "pTM, binder chain",
    "oracle_ppi_overall_ptm": "pTM, whole complex",
    "oracle_ppi_plddt_coi": "pLDDT, binder chain",
    "oracle_ppi_overall_plddt": "pLDDT, whole complex",
    "oracle_ppi_ipae_coi": "Interface PAE, binder chain (A)",
    "oracle_ppi_min_ipae_coi": "Minimum interface PAE, binder chain (A)",
    "oracle_ppi_pae_coi": "PAE, binder chain (A)",
    "oracle_ppi_overall_pae": "PAE, whole complex (A)",
    "oracle_ppi_ranking_score": "Oracle ranking score",
    "oracle_ppi_fraction_disordered": "Fraction disordered",
    "oracle_ppi_has_clash": "Has clash",
    "hotspot_obedience_hotspot_obedience": "Hotspot obedience",
    "refolded_backbone_rmsd_rmsd": "Refolded backbone RMSD (A)",
    "refolded_target_aligned_binder_rmsd_rmsd": "Refolded binder RMSD, target-aligned (A)",
    "ppi_pass": "Passed oracle filters",
    "pre_oracle_pass": "Passed pre-oracle filters",
    "inline_metrics_oracle": "Inline metrics oracle",
    "mean_plddt": "Mean pLDDT",
    "plddt": "pLDDT",
    "plddt_binder": "Binder pLDDT",
    "pae_binder": "PAE binder",
}