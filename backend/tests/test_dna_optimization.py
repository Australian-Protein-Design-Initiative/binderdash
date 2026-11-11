import pytest

from backend.util.dna_optimization import (
    FIXED_STOP_DNA,
    _hairpin_breaches,
    build_dnachisel_constraint,
    fixed_nt_indices,
    free_intervals,
    resolve_fixed_mask,
)


def test_optimize_dna_basic(api_client) -> None:
    payload = {
        "sequences": {
            "d1": "MGS",
            "d2": "MYQ",
        },
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.25, "maxi": 0.75}}
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "elapsed_seconds" in data
    results = data["results"]
    assert len(results) == 2

    dict_res = {r["design_id"]: r for r in results}
    assert "d1" in dict_res
    assert "d2" in dict_res

    assert dict_res["d1"]["optimized_dna"] is not None
    assert dict_res["d2"]["optimized_dna"] is not None
    assert dict_res["d1"]["error"] is None
    assert len(dict_res["d1"]["optimized_dna"]) == 9
    assert len(dict_res["d2"]["optimized_dna"]) == 9


def test_optimize_dna_invalid_constraint(api_client) -> None:
    payload = {
        "sequences": {"d1": "MGS"},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "UnknownConstraint", "enabled": True, "params": {}}
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200
    res = resp.json()["results"][0]
    assert res["error"] is None
    assert res["optimized_dna"] is not None


@pytest.mark.timeout(10)
def test_optimize_dna_no_solution(api_client) -> None:
    payload = {
        "sequences": {"d1": "MGS"},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 1.0, "maxi": 1.0}},
            {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.0, "maxi": 0.0}},
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    res = data["results"][0]
    assert res["error"] is not None


def test_optimize_dna_disabled_constraint(api_client) -> None:
    payload = {
        "sequences": {"d1": "MGS"},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "EnforceGCContent", "enabled": False, "params": {"mini": 1.0, "maxi": 1.0}},
            {"type": "EnforceGCContent", "enabled": False, "params": {"mini": 0.0, "maxi": 0.0}},
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    res = data["results"][0]
    assert res["error"] is None


def test_resolve_fixed_mask_defaults_and_shift() -> None:
    assert resolve_fixed_mask("MGS*", None) == [False, False, False, True]
    assert resolve_fixed_mask("MA*M", [False, False, True, False]) == [
        False,
        False,
        True,
        False,
    ]
    # 5' insert moves which residue index is fixed (rescan, not stored coordinates).
    assert fixed_nt_indices(resolve_fixed_mask("MA*M", None)) == [6, 7, 8]
    assert fixed_nt_indices(resolve_fixed_mask("GMA*M", None)) == [9, 10, 11]
    assert free_intervals(12, [6, 7, 8]) == [(0, 6), (9, 12)]
    # Removing the stop drops the span.
    assert fixed_nt_indices(resolve_fixed_mask("MAM", None)) == []


def test_resolve_fixed_mask_rejects_bad_masks() -> None:
    with pytest.raises(ValueError, match="length"):
        resolve_fixed_mask("MGS", [False, False])
    # Leading Met may be fixed; an internal non-stop may not.
    assert resolve_fixed_mask("MGS", [True, False, False]) == [True, False, False]
    with pytest.raises(ValueError, match="leading Met|only stop"):
        resolve_fixed_mask("MGS", [False, True, False])


def test_optimize_dna_leading_met_stays_atg(api_client) -> None:
    from backend.util.dna_optimization import FIXED_START_DNA

    payload = {
        "sequences": {"d1": "MGS*"},
        "fixed": {"d1": [True, False, False, True]},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.25, "maxi": 0.75}}
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["error"] is None
    dna = res["optimized_dna"]
    assert dna is not None
    assert dna.startswith(FIXED_START_DNA)
    assert dna.endswith(FIXED_STOP_DNA)
    assert len(dna) == 12


def test_optimize_dna_terminal_stop_stays_taa(api_client) -> None:
    payload = {
        "sequences": {"d1": "MGS*"},
        "fixed": {"d1": [False, False, False, True]},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.25, "maxi": 0.75}}
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["error"] is None
    dna = res["optimized_dna"]
    assert dna is not None
    assert dna.endswith(FIXED_STOP_DNA)
    assert len(dna) == 12


def test_optimize_dna_internal_stop_stays_taa(api_client) -> None:
    payload = {
        "sequences": {"d1": "MA*M"},
        "fixed": {"d1": [False, False, True, False]},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.25, "maxi": 0.75}}
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["error"] is None
    dna = res["optimized_dna"]
    assert dna is not None
    assert dna[6:9] == FIXED_STOP_DNA
    assert len(dna) == 12


def test_optimize_dna_fixed_shift_after_5prime_insert(api_client) -> None:
    payload = {
        "sequences": {"d1": "GMA*M"},
        "fixed": {"d1": [False, False, False, True, False]},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.2, "maxi": 0.8}}
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["error"] is None
    dna = res["optimized_dna"]
    assert dna is not None
    assert dna[9:12] == FIXED_STOP_DNA
    assert len(dna) == 15


def test_optimize_dna_omitted_fixed_freezes_stops(api_client) -> None:
    payload = {
        "sequences": {"d1": "MGS*"},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["error"] is None
    assert res["optimized_dna"].endswith(FIXED_STOP_DNA)


def test_optimize_dna_fixed_length_mismatch(api_client) -> None:
    payload = {
        "sequences": {"d1": "MGS"},
        "fixed": {"d1": [False, False]},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["optimized_dna"] is None
    assert res["error"] is not None
    assert "length" in res["error"]


def test_no_solution_is_retried_before_reporting(monkeypatch: pytest.MonkeyPatch) -> None:
    import dnachisel as dc

    from backend.util import dna_optimization as opt

    calls = {"n": 0}
    real = dc.DnaOptimizationProblem.resolve_constraints

    def fail_first_design(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= opt.OPTIMIZATION_ATTEMPTS:
            raise dc.NoSolutionError("nope", problem=self)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(dc.DnaOptimizationProblem, "resolve_constraints", fail_first_design)
    results = opt.optimize_sequences(
        {"failing": "MGS", "ok": "MYQ"},
        "e_coli",
        [],
    )
    assert calls["n"] == opt.OPTIMIZATION_ATTEMPTS + 1
    assert results["failing"]["optimized_dna"] is None
    assert results["failing"]["error"] == (
        "Constraints could not be resolved (No solution found)."
    )
    assert results["ok"]["error"] is None
    assert results["ok"]["optimized_dna"] is not None


def test_no_solution_retry_can_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    import dnachisel as dc

    from backend.util import dna_optimization as opt

    calls = {"n": 0}
    real = dc.DnaOptimizationProblem.resolve_constraints

    def fail_until_last(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] < opt.OPTIMIZATION_ATTEMPTS:
            raise dc.NoSolutionError("nope", problem=self)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(dc.DnaOptimizationProblem, "resolve_constraints", fail_until_last)
    results = opt.optimize_sequences({"d1": "MGS"}, "e_coli", [])
    assert calls["n"] == opt.OPTIMIZATION_ATTEMPTS
    assert results["d1"]["error"] is None
    assert results["d1"]["optimized_dna"] is not None
    assert len(results["d1"]["optimized_dna"]) == 9


def test_non_solver_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    import dnachisel as dc

    from backend.util import dna_optimization as opt

    calls = {"n": 0}

    def boom(self, *args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("solver blew up")

    monkeypatch.setattr(dc.DnaOptimizationProblem, "resolve_constraints", boom)
    results = opt.optimize_sequences({"d1": "MGS"}, "e_coli", [])
    assert calls["n"] == 1
    assert results["d1"]["optimized_dna"] is None
    assert results["d1"]["error"] == "solver blew up"


def test_optimize_dna_fixed_non_stop_residue(api_client) -> None:
    payload = {
        "sequences": {"d1": "MGS"},
        "fixed": {"d1": [False, True, False]},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["optimized_dna"] is None
    assert res["error"] is not None
    assert "stop" in res["error"].lower() or "met" in res["error"].lower()


def test_repeated_kmer_pattern_builds_and_bans_tandem_repeats() -> None:
    """Regression: the backend previously passed k_size straight to
    RepeatedKmerPattern (whose kwarg is kmer_size), so the default tandem-repeat
    constraint silently failed to build."""
    import dnachisel as dc

    constraint = build_dnachisel_constraint(
        "AvoidPattern",
        {"pattern": {"type": "RepeatedKmerPattern", "params": {"n_repeats": 2, "k_size": 6}}},
    )
    assert constraint is not None
    problem = dc.DnaOptimizationProblem(
        sequence="AC" + "GGCAAAGGCAAA" + "GT",
        constraints=[constraint],
    )
    assert not constraint.evaluate(problem).passes

    clean = dc.DnaOptimizationProblem(
        sequence="ACGGCAAAGCACGGTTCAGCAATGTA",
        constraints=[constraint],
    )
    assert constraint.evaluate(clean).passes


def test_hairpin_breaches_detect_vendor_flagged_regions() -> None:
    # GC-rich self-complementary stretch (Ala/Arg-rich VHH CDR region) that
    # vendors reject as an "inverted repeat with >=68C Tm".
    hot = "ACCTGCAGATGAACTCGCTGCGTGCCGAAGACACCGCGGTGTATTACTGTGCACGCAGCGATCATGTGATGTATATTCTC"
    breaches = _hairpin_breaches(hot, 68.0, 10)
    assert len(breaches) >= 1
    assert max(tm for _, _, tm in breaches) >= 68.0

    calm = "AACGTTACGATTCAGGACTTGACCAGTTCGAATCGTAAGCTTAACGATCGATTCAAGGACTTGA"
    assert _hairpin_breaches(calm, 68.0, 10) == []


def test_optimize_dna_resolves_inverted_repeats(api_client) -> None:
    """The vendor-failed nanobody whose naive codon choice creates >=68C
    hairpins must optimise to a sequence free of them."""
    payload = {
        "sequences": {
            "d1": "KYLLPTAAAGLLLLAAQPAMAQVQLVESGGGLVQPGGSLRLSCAASPSSSNIFDYNALGWFRQAPGQGLEAVAALWLKYDTTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCARSDHVMYILCSYTSKIYWGQGTLVTVSSRGRGGGS*"
        },
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {"type": "EnforceGCContent", "enabled": True, "params": {"mini": 0.25, "maxi": 0.64}},
            {"type": "AvoidHairpins", "enabled": True, "params": {"stem_size": 20, "hairpin_window": 48}},
            {"type": "UniquifyAllKmers", "enabled": True, "params": {"k": 12}},
            {
                "type": "AvoidPattern",
                "enabled": True,
                "params": {"pattern": {"type": "RepeatedKmerPattern", "params": {"n_repeats": 2, "k_size": 20}}},
            },
            {"type": "AvoidInvertedRepeats", "enabled": True, "params": {"min_tm": 68}},
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["error"] is None, res["error"]
    dna = res["optimized_dna"]
    assert dna is not None
    assert _hairpin_breaches(dna, 68.0, 1) == []


def test_consecutive_codons_follow_the_coding_frame() -> None:
    """Three CCC codons after a 2 nt addition are a run only in frame 2.

    Reading from nucleotide 0 splits them into ACC/CCC/CCC and misses the run.
    """
    import dnachisel as dc

    from backend.util.dna_optimization import AvoidConsecutiveCodons

    seq = "AC" + "CCC" * 3
    in_frame = AvoidConsecutiveCodons(frame=2, max_run=2)
    from_start = AvoidConsecutiveCodons(frame=0, max_run=2)
    problem = dc.DnaOptimizationProblem(sequence=seq, constraints=[in_frame])
    assert not in_frame.evaluate(problem).passes
    assert from_start.evaluate(problem).passes

    # A CCC that straddles two codons (AAC|CCA) is not a CCC codon.
    straddling = dc.DnaOptimizationProblem(
        sequence="AACCCA", constraints=[from_start]
    )
    assert from_start.evaluate(straddling).passes

    solvable = dc.DnaOptimizationProblem(
        sequence=seq,
        constraints=[
            in_frame,
            dc.AvoidChanges(indices=[0, 1]),
            dc.EnforceTranslation(translation="PPP", location=dc.Location(2, 11)),
        ],
    )
    solvable.resolve_constraints()
    assert solvable.sequence[:2] == "AC"
    assert in_frame.evaluate(solvable).passes
    assert dc.translate(solvable.sequence[2:]) == "PPP"


def test_optimize_dna_preserves_unframed_prefix_and_breaks_codon_runs(api_client) -> None:
    payload = {
        "sequences": {"d1": "acPPP"},
        "frame": {"d1": 2},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [
            {
                "type": "AvoidConsecutiveCodons",
                "enabled": True,
                "params": {"codons": ["CGG", "CGA", "CCC"], "max_run": 2},
            }
        ],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["error"] is None, res["error"]
    dna = res["optimized_dna"]
    assert dna is not None
    assert dna[:2] == "AC"
    assert len(dna) == 11
    import dnachisel as dc

    from backend.util.dna_optimization import AvoidConsecutiveCodons

    assert dc.translate(dna[2:]) == "PPP"
    problem = dc.DnaOptimizationProblem(sequence=dna, constraints=[])
    assert AvoidConsecutiveCodons(frame=2, max_run=2).evaluate(problem).passes


def test_optimize_dna_rejects_bad_frame(api_client) -> None:
    payload = {
        "sequences": {"d1": "MGS"},
        "frame": {"d1": 4},
        "codon_table_id": "e_coli",
        "method": "match_codon_usage",
        "constraints": [],
    }
    resp = api_client.post("/api/sequences/optimize-dna", json=payload)
    assert resp.status_code == 200, resp.text
    res = resp.json()["results"][0]
    assert res["optimized_dna"] is None
    assert res["error"] is not None
    assert "frame" in res["error"]

