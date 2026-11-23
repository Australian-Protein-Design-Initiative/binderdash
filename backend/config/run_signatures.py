"""
Declarative run folder detection and design-table wiring.

Keep ``primary_score_columns`` aligned with ``frontend/src/config/pipelineDisplay.ts``
(primary score chip / column resolution).
"""

from __future__ import annotations

from typing import Any, Dict, List

# Directories to skip during recursive walk (common to all signatures)
DEFAULT_SKIP_DIRS: List[str] = [".nextflow", "work"]

run_folder_signatures: List[Dict[str, Any]] = [
    {
        "method": "bindcraft",
        "submethod": "nf-binder-design",
        "priority": 1,  # Higher priority = checked first
        "required_files": ["results/bindcraft/final_design_stats.csv"],
        "required_dirs": ["results/bindcraft/accepted"],
        "results_table": "results/bindcraft/final_design_stats.csv",
        "pdb_pattern": "results/bindcraft/accepted/*.pdb",
        "params_files": ["results/params.json"],
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["Design"],
        "primary_score_columns": ["Average_i_pTM"],
        "sort_ascending": False,
        "structure_file_column": None,
        "structure_search_patterns": [
            "{design_id}.pdb",
            "{design_id}_*.pdb",
            "{design_id}*.pdb",
        ],
        # bindcraft_n_traj is per input PDB; total = n_traj × n_targets
        "trajectory_count_params_key": "bindcraft_n_traj",
        "trajectory_count_per_target": True,
        "trajectory_count_file": "results/bindcraft/trajectory_stats.csv",
    },
    {
        "method": "rfd",
        "submethod": "nf-binder-design",
        "priority": 2,
        "required_files": ["results/combined_scores.tsv"],
        "required_dirs": [
            "results/af2_initial_guess",
            "results/proteinmpnn",
            "results/rfdiffusion",
        ],
        "results_table": "results/combined_scores.tsv",
        "pdb_pattern": "results/af2_initial_guess/pdbs/*.pdb",
        "params_files": ["results/params.json"],
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["description"],
        "primary_score_columns": ["pae_interaction"],
        "sort_ascending": True,
        "structure_file_column": None,
        "structure_search_patterns": ["{design_id}.pdb"],
    },
    {
        "method": "bindcraft",
        "submethod": "regular",
        "priority": 3,
        "required_files": ["final_design_stats.csv"],
        "required_dirs": ["Accepted"],
        "results_table": "final_design_stats.csv",
        "pdb_pattern": "Accepted/*.pdb",
        "params_files": ["../settings.json"],
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["Design"],
        "primary_score_columns": ["Average_i_pTM"],
        "sort_ascending": False,
        "structure_file_column": None,
        "structure_search_patterns": [
            "{design_id}.pdb",
            "{design_id}_*.pdb",
            "{design_id}*.pdb",
        ],
    },
    {
        "method": "rfd",
        "submethod": "regular",
        "priority": 4,
        "required_dirs": ["af2_initial_guess"],
        "results_table": "combined_scores.tsv",
        "pdb_pattern": "af2_initial_guess/pdbs/*.pdb",
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["description"],
        "primary_score_columns": ["pae_interaction"],
        "sort_ascending": True,
        "structure_file_column": None,
        "structure_search_patterns": ["{design_id}.pdb"],
    },
    {
        "method": "boltzgen",
        "submethod": "nf-binder-design",
        "priority": 5,
        "required_dirs": ["results/boltzgen/filtered/final_ranked_designs"],
        "required_patterns": [
            "results/boltzgen/filtered/final_ranked_designs/final_designs_metrics_*.csv"
        ],
        "results_table_pattern": "results/boltzgen/filtered/final_ranked_designs/final_designs_metrics_*.csv",
        "structure_pattern": "results/boltzgen/filtered/final_ranked_designs/final_*_designs/*.cif",
        "structure_format": "cif",
        "params_files": ["results/params.json"],
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["id"],
        "primary_score_columns": ["design_to_target_iptm"],
        "sort_ascending": False,
        "structure_file_column": "file_name",
        "structure_search_patterns": [
            "{file_name}",
            "rank*_{file_name}",
        ],
        "trajectory_count_params_key": "num_designs",
        "trajectory_count_file": "results/boltzgen/filtered/final_ranked_designs/all_designs_metrics.csv",
    },
    {
        "method": "rfd3",
        "submethod": "nf-binder-design",
        "priority": 6,
        "required_files": ["results/rfd3/combined_scores.tsv"],
        "required_dirs": [
            "results/rfd3/rosettafold3",
            "results/rfd3/rfdiffusion3",
        ],
        "results_table": "results/rfd3/combined_scores.tsv",
        "structure_pattern": "results/rfd3/rosettafold3/output/*/*.cif",
        "additional_pdb_patterns": [
            "results/rfd3/rosettafold3/output/*/*.cif.gz",
            "results/rfd3/rosettafold3/output/*/*.pdb",
            "results/rfd3/rosettafold3/output/*/*.pdb.gz",
        ],
        "structure_format": "cif",
        "params_files": ["results/params.json"],
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["id"],
        "primary_score_columns": [
            "iptm",
            "pair_pae",
            "rf3_ipsae_min",
            "rf3_rmsd_target_aligned_binder_rmsd_all",
        ],
        "sort_ascending": False,
        "structure_file_column": None,
        "structure_base_dir": "results/rfd3/rosettafold3/output/{design_id}",
        "structure_search_patterns": [
            "{design_id}_model.cif",
            "{design_id}_model.cif.gz",
            "{design_id}_model.pdb",
            "{design_id}_model.pdb.gz",
        ],
    },
    {
        "method": "rfd4_proteina",
        "submethod": "nf-binder-design",
        "priority": 7,
        "required_files": ["results/rfd4_proteina/combined_scores.tsv"],
        "required_dirs": ["results/rfd4_proteina/designs"],
        "results_table": "results/rfd4_proteina/combined_scores.tsv",
        "structure_pattern": "results/rfd4_proteina/designs/*.cif",
        "additional_pdb_patterns": [
            "results/rfd4_proteina/designs/*.cif.gz",
            "results/rfd4_proteina/designs/*.cif.zst",
        ],
        "structure_format": "cif",
        "params_files": ["results/params.json"],
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["id"],
        # combined_scores.tsv itself carries only identity and sequence. The interface
        # score comes from the oracle's sibling metrics table, merged on ingest by
        # run_discovery._merge_rfd4_inline_metrics: ``oracle_ppi_iptm_coi`` is the
        # interface pTM for the chain of interest (the binder), rescaled to 0-1.
        # ``consensus_z`` is the fallback for a run refolded with --refold_with but
        # with no inline metrics table. Both are 0-1 and higher-is-better, so neither
        # outranks the other on scale alone.
        "primary_score_columns": ["oracle_ppi_iptm_coi", "consensus_z"],
        "sort_ascending": False,
        # A run with neither has only length/batch/seed to offer; report no primary
        # score rather than one of those.
        "primary_score_fallback": False,
        "structure_file_column": None,
        "structure_search_patterns": [
            "{design_id}.cif",
            "{design_id}.cif.gz",
            "{design_id}.cif.zst",
        ],
        "trajectory_count_params_key": "rfd4_n_designs",
    },
    # BindCraft2 (--method bc2). Two tiers: ``ranked.csv`` is the accepted designs,
    # written only once at least one design passes BindCraft2's filters; a campaign
    # that accepted nothing still has ``refolded.csv``, every scored candidate with an
    # ``outcome`` column saying why it was rejected. Both are published only when the
    # stage produced rows, so each tier needs its own signature.
    {
        "method": "bindcraft2",
        "submethod": "nf-binder-design",
        "priority": 8,
        "required_files": ["results/bc2/ranked.csv"],
        "required_dirs": ["results/bc2/ranked"],
        "results_table": "results/bc2/ranked.csv",
        "structure_pattern": "results/bc2/ranked/*.cif",
        # The refolded complexes belong to the run too, and a campaign that accepted a
        # single design otherwise offers one structure, too few for chain-role
        # resolution to tell the target from the binder (see filtering/chain_roles.py).
        # Design lookup is unaffected: ranked ids end _seq{n}, refolded ids _candidate{n}.
        "additional_pdb_patterns": [
            "results/bc2/batches/*/2_Refolded/Complexes/*.cif",
        ],
        "structure_format": "cif",
        "params_files": ["results/params.json"],
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["design"],
        # BindCraft2's own ranking metric: a distance-masked interface confidence,
        # 0-1, highest first (bindcraft/campaign_output.py sorts on -i_pDAE).
        # It alone, with no second column: i_pDAE is written only for a design that
        # has interface contacts, and a fallback on a different scale would rank the
        # rest against it. BindCraft2 likewise sorts a missing score last.
        "primary_score_columns": ["i_pDAE"],
        "sort_ascending": False,
        "structure_file_column": None,
        # BC2_CAMPAIGN_OUTPUT publishes every campaign's 3_Ranked/*.cif into one
        # directory under its bare basename, which equals the ``design`` column; the
        # looser globs are only a fallback in case that ever gains a prefix.
        "structure_search_patterns": [
            "{design_id}.cif",
            "*_{design_id}.cif",
            "{design_id}*.cif",
        ],
        "trajectory_count_params_key": "bc2_n_traj",
        "trajectory_count_file": "results/bc2/trajectories.csv",
    },
    {
        "method": "bindcraft2",
        "submethod": "nf-binder-design",
        "priority": 9,
        # refolded.csv alone, no required_dirs: a campaign that accepted nothing may
        # never create results/bc2/ranked, and the refolded table does not depend on it.
        "required_files": ["results/bc2/refolded.csv"],
        "results_table": "results/bc2/refolded.csv",
        # Refolded candidates keep their complexes per batch; only accepted designs
        # are republished into results/bc2/ranked/.
        "structure_pattern": "results/bc2/batches/*/2_Refolded/Complexes/*.cif",
        "structure_format": "cif",
        "params_files": ["results/params.json"],
        "skip_dirs": DEFAULT_SKIP_DIRS,
        "design_id_columns": ["design"],
        "primary_score_columns": ["i_pDAE"],
        "sort_ascending": False,
        "structure_file_column": None,
        "structure_search_patterns": [
            "{design_id}.cif",
            "*_{design_id}.cif",
            "{design_id}*.cif",
        ],
        "trajectory_count_params_key": "bc2_n_traj",
        "trajectory_count_file": "results/bc2/trajectories.csv",
    },
]
