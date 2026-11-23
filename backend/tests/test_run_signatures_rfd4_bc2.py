"""Run detection and design parsing for the nf-binder-design rfd4_proteina and bc2 layouts.

Minimal folder trees mirroring the published output of
``--method rfd4_proteina`` and ``--method bc2`` on the develop branch of
Australian-Protein-Design-Initiative/nf-binder-design.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.run_discovery import (
    detect_run_type,
    extract_backbone_id,
    find_runs_recursive,
    parse_designs_from_run,
    resolve_trajectory_count,
)

# Two batches reusing the same example_id, as real runs do: 25 examples per batch.
RFD4_SCORES = (
    "id\tfilename\tsequence\tlength\texample_id\tbatch\tseed\tchain\tconsensus_z\n"
    "cx_b0_cxcr2_0\tcx_b0_cxcr2_0.cif\tALDLEN\t6\tcxcr2_0\t0\t0\tB\t0.5\n"
    "cx_b1_cxcr2_0\tcx_b1_cxcr2_0.cif\tSVAYEM\t6\tcxcr2_0\t1\t0\tB\t1.5\n"
)

# The oracle's sibling metrics table. Only a handful of its real columns, plus one
# generation hyperparameter and one work-directory path that must NOT be merged.
RFD4_INLINE_METRICS = (
    "work_hash,example_id,dataset_name,seed,generation.args.nsteps,"
    "hotspot_obedience.hotspot_obedience,pre_oracle_pass,oracle_ppi.overall_plddt,"
    "oracle_ppi.overall_ptm,oracle_ppi.iptm_coi,oracle_ppi.plddt_coi,"
    "oracle_ppi.ipae_coi,oracle_ppi.min_ipae_coi,oracle_ppi.ranking_score,"
    "oracle_ppi.refolded_structure_path,refolded_target_aligned_binder_rmsd.rmsd,"
    "ppi.pass,ppi.all_metrics_present\n"
    "ab/cd,cxcr2_0,cx_b0.json,0.0,60.0,0.6667,1.0,84.89,85.0,88.0,91.6,8.4438,1.115,"
    "0.89,rundir/x.cif,2.0829,1.0,1.0\n"
    "ef/gh,cxcr2_0,cx_b1.json,1.0,60.0,0.0833,1.0,61.72,52.0,9.0,32.23,29.633,24.26,"
    "0.18,rundir/y.cif,22.703,0.0,1.0\n"
)

BC2_COLUMNS = "campaign,design,length,outcome,Binder_Sequence,i_pDAE,i_pTM,pLDDT,pTM,i_pAE,hash\n"


def _make_rfd4_run(root: Path, *, inline_metrics: bool = False) -> Path:
    run = root / "cxcr2_flexloops_rfd4"
    designs = run / "results" / "rfd4_proteina" / "designs"
    designs.mkdir(parents=True)
    (run / "results" / "rfd4_proteina" / "combined_scores.tsv").write_text(RFD4_SCORES)
    if inline_metrics:
        (run / "results" / "rfd4_proteina" / "of3_inline_metrics.csv").write_text(
            RFD4_INLINE_METRICS
        )
    for name in ("cx_b0_cxcr2_0", "cx_b1_cxcr2_0"):
        (designs / f"{name}.cif").write_text("data_x\n")
    (designs / "rfd4_designs_batch0.tsv").write_text("id\tfilename\n")
    (run / "results" / "params.json").write_text(
        json.dumps({"params": {"method": "rfd4_proteina", "rfd4_n_designs": 100}})
    )
    return run


def _make_bc2_run(root: Path, *, accepted: bool) -> Path:
    run = root / ("cxcr2_bc2" if accepted else "cxcr2_bc2_none_accepted")
    bc2 = run / "results" / "bc2"
    # ``ranked/`` only exists once the publish step ran, so the no-accepted case omits it.
    (bc2 / "ranked").mkdir(parents=True) if accepted else bc2.mkdir(parents=True)
    (bc2 / "refolded.csv").write_text(
        BC2_COLUMNS
        + "camp_0,cx_denovo_l117_abc_candidate1,117,rejected,ELEE,0.9,0.14,0.95,0.7,0.96,abc\n"
        + "camp_0,cx_denovo_l117_abc_candidate2,117,accepted,AVQW,0.37,0.92,0.95,0.89,0.21,abc\n"
    )
    complexes = bc2 / "batches" / "camp_0" / "2_Refolded" / "Complexes"
    complexes.mkdir(parents=True)
    for n in (1, 2):
        (complexes / f"cx_denovo_l117_abc_candidate{n}.cif").write_text("data_x\n")
    (bc2 / "trajectories.csv").write_text("campaign,trajectory,design\ncamp_0,1,cx_denovo_l117_abc\n")
    (bc2 / "summary.csv").write_text("campaign,scope,metric\ncamp_0,campaign,trajectories\n")
    if accepted:
        (bc2 / "ranked.csv").write_text(
            BC2_COLUMNS
            + "camp_0,cx_denovo_l117_abc_seq0,117,accepted,AVQW,0.37,0.92,0.95,0.89,0.21,abc\n"
        )
        (bc2 / "ranked" / "cx_denovo_l117_abc_seq0.cif").write_text("data_x\n")
    (run / "results" / "params.json").write_text(
        json.dumps({"params": {"method": "bc2", "bc2_n_traj": 100}})
    )
    return run


def test_rfd4_proteina_detect_and_parse(tmp_path: Path) -> None:
    run = _make_rfd4_run(tmp_path)

    sig = detect_run_type(run)
    assert sig is not None
    assert sig["method"] == "rfd4_proteina"
    assert sig["submethod"] == "nf-binder-design"
    assert resolve_trajectory_count(run, sig) == 100

    runs = find_runs_recursive(tmp_path)
    assert len(runs) == 1
    # Only the design mmCIFs, not the per-batch TSVs alongside them.
    assert len(runs[0]["pdb_files"]) == 2

    designs = parse_designs_from_run(runs[0])
    assert [d["design_id"] for d in designs] == ["cx_b1_cxcr2_0", "cx_b0_cxcr2_0"]
    assert designs[0]["consensus_z"] == 1.5  # sorted by consensus_z, highest first
    assert Path(designs[0]["pdb_file"]).name == "cx_b1_cxcr2_0.cif"
    # ``sequence`` / ``length`` / ``chain`` fold into the canonical column names.
    assert designs[0]["Sequence"] == "SVAYEM"
    assert designs[0]["binder_chain"] == "B"


def test_bc2_prefers_ranked_table_when_designs_were_accepted(tmp_path: Path) -> None:
    run = _make_bc2_run(tmp_path, accepted=True)

    sig = detect_run_type(run)
    assert sig is not None
    assert sig["method"] == "bindcraft2"
    assert sig["results_table"] == "results/bc2/ranked.csv"
    assert resolve_trajectory_count(run, sig) == 100

    runs = find_runs_recursive(tmp_path)
    designs = parse_designs_from_run(runs[0])
    assert [d["design_id"] for d in designs] == ["cx_denovo_l117_abc_seq0"]
    assert Path(designs[0]["pdb_file"]).name == "cx_denovo_l117_abc_seq0.cif"
    # Candidates of one trajectory collapse onto a shared backbone.
    assert designs[0]["backbone_id"] == "cx_denovo_l117_abc"


def test_bc2_falls_back_to_refolded_when_nothing_was_accepted(tmp_path: Path) -> None:
    run = _make_bc2_run(tmp_path, accepted=False)

    sig = detect_run_type(run)
    assert sig is not None
    assert sig["method"] == "bindcraft2"
    assert sig["results_table"] == "results/bc2/refolded.csv"

    runs = find_runs_recursive(tmp_path)
    designs = parse_designs_from_run(runs[0])
    # Sorted by i_pDAE descending (BindCraft2 ranks on it, highest first); rejected
    # candidates are kept, with no structure.
    assert [d["design_id"] for d in designs] == [
        "cx_denovo_l117_abc_candidate1",
        "cx_denovo_l117_abc_candidate2",
    ]
    assert designs[0]["i_pDAE"] == 0.9
    assert designs[0]["outcome"] == "rejected"
    # Refolded complexes live under each batch, not in the accepted-only ranked/ dir.
    assert Path(designs[0]["pdb_file"]).parent.name == "Complexes"


def test_bindcraft2_backbone_id_strips_candidate_suffix() -> None:
    assert extract_backbone_id("cx_denovo_l117_abc_candidate12", "bindcraft2") == "cx_denovo_l117_abc"
    # ranked.csv names the same trajectory _seq{n}; both must fold onto one backbone.
    assert extract_backbone_id("cx_denovo_l117_abc_seq0", "bindcraft2") == "cx_denovo_l117_abc"
    # Other methods' suffixes are untouched by the added alternative.
    assert extract_backbone_id("bc_design_111_l93_s308700_mpnn10", "bindcraft") == "bc_design_111_l93_s308700"


def test_rfd4_config_mode_input_target_comes_from_the_spec(tmp_path: Path) -> None:
    """``--rfd4_config`` names the target inside the YAML spec, not in params.json."""
    from backend.util.input_targets import list_input_targets

    run = _make_rfd4_run(tmp_path)
    (run / "input").mkdir()
    (run / "input" / "target.cif").write_text("data_x\n")
    (run / "cxcr2_rfd4.yaml").write_text(
        "cxcr2:\n  input: input/target.cif\n  contig: \"60-120, /0, A1-325\"\n"
    )
    (run / "results" / "params.json").write_text(
        json.dumps(
            {"params": {"method": "rfd4_proteina", "rfd4_config": "cxcr2_rfd4.yaml"}}
        )
    )

    runs = find_runs_recursive(tmp_path)
    targets = list_input_targets(runs[0])
    assert [t.relative_path for t in targets] == ["input/target.cif"]
    assert "cxcr2_rfd4.yaml" in targets[0].label


def test_minimal_mmcif_without_occupancy_still_parses(tmp_path: Path) -> None:
    """BindCraft2 writes mmCIFs with no ``_atom_site.occupancy``, which Biopython's
    MMCIFParser requires. ``parse_mmcif`` supplies it, so chain roles, tag metrics and
    superposition keep working on those files.
    """
    from backend.tag_placement import load_structure
    from backend.util.pdb_to_fasta import get_chain_sequences
    from backend.util.structure_io import parse_mmcif

    cif = tmp_path / "minimal.cif"
    cif.write_text(
        "data_model\n#\nloop_\n"
        "_atom_site.group_PDB\n_atom_site.type_symbol\n_atom_site.label_atom_id\n"
        "_atom_site.label_alt_id\n_atom_site.label_comp_id\n_atom_site.label_asym_id\n"
        "_atom_site.label_seq_id\n_atom_site.pdbx_PDB_ins_code\n_atom_site.auth_seq_id\n"
        "_atom_site.auth_comp_id\n_atom_site.auth_asym_id\n_atom_site.auth_atom_id\n"
        "_atom_site.B_iso_or_equiv\n_atom_site.label_entity_id\n_atom_site.Cartn_x\n"
        "_atom_site.Cartn_y\n_atom_site.Cartn_z\n_atom_site.pdbx_PDB_model_num\n"
        "_atom_site.id\n"
        "ATOM N N . ALA A 1 ? 1 ALA B N 50.0 1 0.0 0.0 0.0 1 1\n"
        "ATOM C CA . ALA A 1 ? 1 ALA B CA 50.0 1 1.5 0.0 0.0 1 2\n"
        "ATOM C C . ALA A 1 ? 1 ALA B C 50.0 1 2.4 1.1 0.0 1 3\n"
        "ATOM N N . GLY A 2 ? 2 GLY B N 50.0 1 3.7 0.9 0.0 1 4\n"
        "ATOM C CA . GLY A 2 ? 2 GLY B CA 50.0 1 4.6 2.0 0.0 1 5\n"
        "ATOM C C . GLY A 2 ? 2 GLY B C 50.0 1 5.9 1.5 0.0 1 6\n"
        "#\n"
    )

    structure = parse_mmcif(str(cif))
    assert [c.id for c in structure.get_chains()] == ["B"]
    # Supplied rather than guessed away: a predicted model is fully occupied.
    assert {a.get_occupancy() for a in structure.get_atoms()} == {1.0}
    # ...and the consumers that read these files agree.
    assert get_chain_sequences(str(cif)) == {"B": "AG"}
    assert [c.id for c in load_structure(cif).get_chains()] == ["B"]


def test_rfd4_inline_oracle_metrics_are_merged_per_batch(tmp_path: Path) -> None:
    """combined_scores.tsv has no scores of its own; they come from the oracle's sibling
    metrics table. ``example_id`` repeats across batches, so the join has to use the
    batch named in ``dataset_name`` as well.
    """
    run = _make_rfd4_run(tmp_path, inline_metrics=True)

    runs = find_runs_recursive(tmp_path)
    designs = parse_designs_from_run(runs[0])
    by_id = {d["design_id"]: d for d in designs}
    assert set(by_id) == {"cx_b0_cxcr2_0", "cx_b1_cxcr2_0"}

    # Both rows share example_id cxcr2_0; each design must get its own batch's metrics
    # rather than four rows from a cartesian join.
    assert len(designs) == 2
    b0, b1 = by_id["cx_b0_cxcr2_0"], by_id["cx_b1_cxcr2_0"]

    # pTM / ipTM / pLDDT are rescaled from the file's 0-100 to 0-1...
    assert b0["oracle_ppi_iptm_coi"] == pytest.approx(0.88)
    assert b0["oracle_ppi_plddt_coi"] == pytest.approx(0.916)
    assert b0["oracle_ppi_overall_ptm"] == pytest.approx(0.85)
    assert b1["oracle_ppi_iptm_coi"] == pytest.approx(0.09)
    # ...while angstroms and unit-interval metrics are left alone.
    assert b0["oracle_ppi_ipae_coi"] == 8.4438
    assert b0["oracle_ppi_min_ipae_coi"] == 1.115
    assert b0["refolded_target_aligned_binder_rmsd_rmsd"] == 2.0829
    assert b0["oracle_ppi_ranking_score"] == 0.89
    assert b0["hotspot_obedience_hotspot_obedience"] == 0.6667

    # The oracle writes its flags as 0.0/1.0, but they are boolean in meaning: stored as
    # real bools so the Filtering tab offers yes/no instead of a 0-1 range.
    assert b0["ppi_pass"] is True
    assert b1["ppi_pass"] is False
    assert b0["pre_oracle_pass"] is True
    assert b0["ppi_all_metrics_present"] is True

    # Provenance of the metrics, and no generation config or work paths merged in.
    assert b0["inline_metrics_oracle"] == "of3"
    assert "generation_args_nsteps" not in b0
    assert "oracle_ppi_refolded_structure_path" not in b0
    # Dots would be read by Vega-Lite as nested field access.
    assert not [k for k in b0 if "." in k]


def test_rfd4_without_inline_metrics_reports_no_primary_score(tmp_path: Path) -> None:
    """A run with neither inline metrics nor a refold has only length/batch/seed, and
    must report no primary score rather than one of those.
    """
    from backend.run_discovery import compute_primary_score_stats, load_run_table

    run = _make_rfd4_run(tmp_path)
    scores = (run / "results" / "rfd4_proteina" / "combined_scores.tsv").read_text()
    # Drop the consensus_z column the base fixture carries.
    rows = [line.split("\t")[:-1] for line in scores.strip().split("\n")]
    (run / "results" / "rfd4_proteina" / "combined_scores.tsv").write_text(
        "\n".join("\t".join(r) for r in rows) + "\n"
    )

    runs = find_runs_recursive(tmp_path)
    df = load_run_table(runs[0])
    assert df is not None and "consensus_z" not in df.columns
    assert compute_primary_score_stats(df, runs[0]["signature"]) is None


def test_boolean_flag_columns_are_offered_as_filters() -> None:
    """A pipeline's own pass/fail flag has to reach the Filtering picker. The column list
    was numeric-only, so storing these as booleans would otherwise have dropped them.
    """
    import polars as pl

    from backend.filtering.metrics import available_columns_for_methods

    df = pl.DataFrame(
        {
            "method": ["rfd4_proteina", "rfd4_proteina"],
            "oracle_ppi_iptm_coi": [0.88, 0.09],
            "ppi_pass": [True, False],
            "design_id": ["a", "b"],
        }
    )
    present = available_columns_for_methods(df)["rfd4_proteina"]
    assert "ppi_pass" in present
    assert "oracle_ppi_iptm_coi" in present
    # Identity columns are not metrics and stay out.
    assert "design_id" not in present
