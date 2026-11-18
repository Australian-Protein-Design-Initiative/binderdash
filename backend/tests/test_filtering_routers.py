"""Integration tests for /api/filtering/* and /api/saved-sets/* endpoints."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

import backend.cache as cache_mod

FIXTURE_PDB = Path(__file__).resolve().parent / "fixtures" / "two_chain_minimal.pdb"


def _design(run_id: str, i: int, **extra: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "run_id": run_id,
        "design_id": f"d{i}",
        "method": "bindcraft",
        "source_path": "",
        "pdb_file": FIXTURE_PDB.name,
        "Average_i_pTM": 0.5 + i * 0.05,
        "Binder_RMSD": 3.0 - i * 0.1,
        "Sequence": "A" * 10 + chr(65 + i),
    }
    row.update(extra)
    return row


def _seed_run(run_id: str = "run-filt-1", n: int = 10) -> None:
    cache_mod.run_cache.clear()
    cache_mod.designs_cache.clear()
    cache_mod.designs_by_run_id.clear()
    cache_mod.run_cache[run_id] = {
        "run_id": run_id,
        "method": "bindcraft",
        "path": "/fake",
        "pdb_files": [str(FIXTURE_PDB)],
    }
    rows = [_design(run_id, i) for i in range(n)]
    cache_mod.designs_by_run_id[run_id] = rows
    cache_mod.designs_cache.extend(rows)


class TestFilteringPreview:
    def test_preview_counts(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/preview",
            json={
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "Binder_RMSD", "operator": "<", "threshold": 2.8}],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_designs"] == 10
        assert body["per_filter_counts"][0]["remaining"] == 7
        assert body["final_passing"] == 7
        names = {c["name"] for c in body["available_columns"]}
        assert "iptm" in names
        assert "rmsd" in names

    def test_preview_no_runs_found(self, api_client, sqlite_designs_repo) -> None:
        cache_mod.run_cache.clear()
        cache_mod.designs_by_run_id.clear()
        cache_mod.designs_cache.clear()
        resp = api_client.post("/api/filtering/preview", json={"run_ids": ["missing"]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["total_designs"] == 0


class TestFilteringColumns:
    def test_columns_canonical_mapping(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post("/api/filtering/columns", json={"run_ids": ["run-filt-1"]})
        assert resp.status_code == 200, resp.text
        by_name = {c["name"]: c for c in resp.json()["columns"]}
        assert by_name["iptm"]["canonical_name"] == "iptm"
        assert by_name["rmsd"]["canonical_name"] == "rmsd"
        assert by_name["iptm"]["sample_values"]["min"] == 0.5
        assert "median" in by_name["iptm"]["sample_values"]
        assert by_name["iptm"]["raw_columns"] == {"bindcraft": "Average_i_pTM"}
        assert by_name["rmsd"]["raw_columns"] == {"bindcraft": "Binder_RMSD"}
        assert by_name["iptm"]["higher_is_better"] is True
        assert by_name["rmsd"]["higher_is_better"] is False
        assert by_name["good"]["dtype"] == "Boolean"
        assert by_name["tag"]["dtype"] == "String"

    def test_good_and_tag_filters(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        rows = cache_mod.designs_by_run_id["run-filt-1"]
        rows[0]["good"] = True
        rows[0]["tag"] = "N"
        rows[1]["good"] = False
        rows[1]["tag"] = "C"
        resp = api_client.post(
            "/api/filtering/apply",
            json={
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "good", "operator": "equals", "text_value": "true"}],
            },
        )
        assert resp.status_code == 200, resp.text
        assert [k["design_id"] for k in resp.json()["passing_keys"]] == ["d0"]
        resp = api_client.post(
            "/api/filtering/apply",
            json={
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "tag", "operator": "equals", "text_value": "C"}],
            },
        )
        assert resp.status_code == 200, resp.text
        assert [k["design_id"] for k in resp.json()["passing_keys"]] == ["d1"]
        resp = api_client.post(
            "/api/filtering/apply",
            json={
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "good", "operator": "is_empty"}],
            },
        )
        assert resp.status_code == 200, resp.text
        ids = {k["design_id"] for k in resp.json()["passing_keys"]}
        assert "d0" not in ids and "d1" not in ids
        assert "d2" in ids


class TestFilteringApply:
    def test_apply_returns_matching_keys(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/apply",
            json={
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "Binder_RMSD", "operator": "<", "threshold": 2.8}],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_designs"] == 10
        assert body["final_passing"] == 7
        assert len(body["passing_keys"]) == 7
        for key in body["passing_keys"]:
            assert key["run_id"] == "run-filt-1"
            assert key["design_id"].startswith("d")

    def test_apply_no_filters_returns_all(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/apply", json={"run_ids": ["run-filt-1"], "filters": []}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["final_passing"] == 10

    def test_apply_text_operator(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/apply",
            json={
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "design_id", "operator": "equals", "text_value": "d0"}],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["final_passing"] == 1
        assert body["passing_keys"][0]["design_id"] == "d0"

    def test_apply_empty_run_ids(self, api_client, sqlite_designs_repo) -> None:
        cache_mod.run_cache.clear()
        cache_mod.designs_by_run_id.clear()
        cache_mod.designs_cache.clear()
        resp = api_client.post("/api/filtering/apply", json={"run_ids": ["missing"], "filters": []})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"total_designs": 0, "passing_keys": [], "final_passing": 0}


class TestFilteringRank:
    def test_rank_returns_final_rank_and_quality_score(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/rank",
            json={
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "Binder_RMSD", "operator": "<", "threshold": 2.8}],
                "metrics": [{"column": "Average_i_pTM", "weight": 1.0, "higher_is_better": True}],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_designs"] == 10
        # apply_hard_filters + rank_designs rank *all* input rows (failing rows are
        # penalised via num_filters_passed, not dropped) — see engine.rank_designs.
        assert len(body["designs"]) == 10
        ranks = [d["final_rank"] for d in body["designs"]]
        assert sorted(ranks) == list(range(1, 11))
        # Best Average_i_pTM among rows passing the filter should be rank 1.
        best = next(d for d in body["designs"] if d["final_rank"] == 1)
        assert best["quality_score"] == 1.0

    def test_rank_no_runs_found(self, api_client, sqlite_designs_repo) -> None:
        cache_mod.run_cache.clear()
        cache_mod.designs_by_run_id.clear()
        cache_mod.designs_cache.clear()
        resp = api_client.post("/api/filtering/rank", json={"run_ids": ["missing"]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"designs": [], "total_designs": 0}

    def test_rank_no_metrics_still_ranks(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/rank", json={"run_ids": ["run-filt-1"], "filters": [], "metrics": []}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_designs"] == 10
        assert len(body["designs"]) == 10
        for d in body["designs"]:
            assert d["final_rank"] is not None
            assert d["quality_score"] is not None


class TestFilteringDiversity:
    def test_diversity_selects_subset_and_does_not_persist(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/diversity",
            json={
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "Binder_RMSD", "operator": "<", "threshold": 2.8}],
                "metrics": [{"column": "Average_i_pTM", "weight": 1.0, "higher_is_better": True}],
                "budget": 3,
                "alpha": 0.2,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_designs"] == 10
        assert body["passing_filters"] == 7
        assert body["diverse_set_count"] == 3
        diverse_rows = [d for d in body["designs"] if d["in_diverse_set"]]
        assert len(diverse_rows) == 3
        for d in diverse_rows:
            assert d["run_id"] == "run-filt-1"
            assert d["final_rank"] is not None

        # Must not create a Saved Set as a side effect.
        listed = api_client.get("/api/saved-sets")
        assert listed.status_code == 200, listed.text
        assert listed.json()["saved_sets"] == []

    def test_diversity_no_runs_found(self, api_client, sqlite_designs_repo) -> None:
        cache_mod.run_cache.clear()
        cache_mod.designs_by_run_id.clear()
        cache_mod.designs_cache.clear()
        resp = api_client.post(
            "/api/filtering/diversity",
            json={"run_ids": ["missing"], "budget": 5, "alpha": 0.1},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "designs": [],
            "total_designs": 0,
            "passing_filters": 0,
            "diverse_set_count": 0,
            "warnings": [],
        }


class TestFilteringRun:
    def test_run_creates_saved_set(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/run",
            json={
                "name": "My Saved Set",
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "Binder_RMSD", "operator": "<", "threshold": 2.8}],
                "metrics": [{"column": "Average_i_pTM", "weight": 1.0, "higher_is_better": True}],
                "budget": 3,
                "alpha": 0.2,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "My Saved Set"
        assert body["total_input"] == 10
        assert body["passing_filters"] == 7
        assert body["top_set_count"] == 3
        assert body["diverse_set_count"] == 3

    def test_run_persists_ui_state_including_best_mpnn(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/run",
            json={
                "name": "With UI state",
                "run_ids": ["run-filt-1"],
                "filters": [],
                "metrics": [{"column": "Average_i_pTM", "weight": 1.0, "higher_is_better": True}],
                "budget": 4,
                "alpha": 0.1,
                "apply_diversity": True,
                "ui_state": {
                    "run_ids": ["run-filt-1"],
                    "visible_columns": ["design_id", "Average_i_pTM"],
                    "sort": [{"field": "Average_i_pTM", "order": -1}],
                    "best_mpnn_only": True,
                },
            },
        )
        assert resp.status_code == 200, resp.text
        saved = api_client.get(f"/api/saved-sets/{resp.json()['saved_set_id']}")
        assert saved.status_code == 200, saved.text
        ui_state = saved.json()["filter_params"]["ui_state"]
        assert ui_state["best_mpnn_only"] is True
        assert ui_state["visible_columns"] == ["design_id", "Average_i_pTM"]
        assert ui_state["sort"] == [{"field": "Average_i_pTM", "order": -1}]

    def test_run_without_diversity_keeps_all_passing(self, api_client, sqlite_designs_repo) -> None:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/run",
            json={
                "name": "All passing",
                "run_ids": ["run-filt-1"],
                "filters": [{"column": "Binder_RMSD", "operator": "<", "threshold": 2.8}],
                "metrics": [{"column": "Average_i_pTM", "weight": 1.0, "higher_is_better": True}],
                "budget": 3,
                "alpha": 0.2,
                "apply_diversity": False,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["passing_filters"] == 7
        assert body["diverse_set_count"] == 7
        assert body["top_set_count"] == 7
        assert body.get("warnings", []) == []

        designs = api_client.get(f"/api/saved-sets/{body['saved_set_id']}/designs")
        assert designs.status_code == 200, designs.text
        assert sum(1 for r in designs.json()["designs"] if r["in_diverse_set"]) == 7

    def test_run_no_matching_runs_returns_400(self, api_client, sqlite_designs_repo) -> None:
        cache_mod.run_cache.clear()
        cache_mod.designs_by_run_id.clear()
        cache_mod.designs_cache.clear()
        resp = api_client.post(
            "/api/filtering/run",
            json={"name": "Empty", "run_ids": ["missing"], "budget": 5, "alpha": 0.1},
        )
        assert resp.status_code == 400


class TestSavedSetsCrud:
    def _create_saved_set(self, api_client, sqlite_designs_repo) -> str:
        _seed_run()
        resp = api_client.post(
            "/api/filtering/run",
            json={
                "name": "Set A",
                "run_ids": ["run-filt-1"],
                "filters": [],
                "metrics": [{"column": "Average_i_pTM", "weight": 1.0, "higher_is_better": True}],
                "budget": 4,
                "alpha": 0.1,
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["saved_set_id"]

    def test_list_and_get(self, api_client, sqlite_designs_repo) -> None:
        saved_set_id = self._create_saved_set(api_client, sqlite_designs_repo)

        listed = api_client.get("/api/saved-sets")
        assert listed.status_code == 200, listed.text
        ids = {s["id"] for s in listed.json()["saved_sets"]}
        assert saved_set_id in ids

        got = api_client.get(f"/api/saved-sets/{saved_set_id}")
        assert got.status_code == 200, got.text
        assert got.json()["name"] == "Set A"
        # design_count is the diversity-selected set size (budget=4), not the 10
        # ranked/input designs — see _saved_set_from_row in filtering/service.py.
        assert got.json()["design_count"] == 4
        assert got.json()["total_input"] == 10

    def test_get_missing_returns_404(self, api_client, sqlite_designs_repo) -> None:
        resp = api_client.get("/api/saved-sets/does-not-exist")
        assert resp.status_code == 404

    def test_designs_endpoint(self, api_client, sqlite_designs_repo) -> None:
        saved_set_id = self._create_saved_set(api_client, sqlite_designs_repo)
        resp = api_client.get(f"/api/saved-sets/{saved_set_id}/designs")
        assert resp.status_code == 200, resp.text
        rows = resp.json()["designs"]
        assert len(rows) == 10
        assert rows[0]["final_rank"] == 1
        assert sum(1 for r in rows if r["in_diverse_set"]) == 4

    def test_delete(self, api_client, sqlite_designs_repo) -> None:
        saved_set_id = self._create_saved_set(api_client, sqlite_designs_repo)
        deleted = api_client.delete(f"/api/saved-sets/{saved_set_id}")
        assert deleted.status_code == 200, deleted.text
        again = api_client.delete(f"/api/saved-sets/{saved_set_id}")
        assert again.status_code == 404
        assert api_client.get(f"/api/saved-sets/{saved_set_id}").status_code == 404

    def test_rename(self, api_client, sqlite_designs_repo) -> None:
        saved_set_id = self._create_saved_set(api_client, sqlite_designs_repo)
        resp = api_client.patch(f"/api/saved-sets/{saved_set_id}", json={"name": "Renamed Set"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Renamed Set"
        got = api_client.get(f"/api/saved-sets/{saved_set_id}")
        assert got.json()["name"] == "Renamed Set"

    def test_rename_missing_returns_404(self, api_client, sqlite_designs_repo) -> None:
        resp = api_client.patch("/api/saved-sets/does-not-exist", json={"name": "X"})
        assert resp.status_code == 404

    def test_rename_empty_name_returns_400(self, api_client, sqlite_designs_repo) -> None:
        saved_set_id = self._create_saved_set(api_client, sqlite_designs_repo)
        resp = api_client.patch(f"/api/saved-sets/{saved_set_id}", json={"name": "   "})
        assert resp.status_code == 400

    def test_download_bundle_contains_table_and_structures(
        self, api_client, sqlite_designs_repo
    ) -> None:
        """Saved sets download the standard bundle (see routers/bundles.py), which is
        TSV rather than the CSV this endpoint emitted before bundles existed."""
        saved_set_id = self._create_saved_set(api_client, sqlite_designs_repo)
        resp = api_client.get(f"/api/saved-sets/{saved_set_id}/download")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/zip"

        zf = zipfile.ZipFile(BytesIO(resp.content))
        names = zf.namelist()
        assert names
        assert all(name.startswith("saved_set_Set_A/") for name in names)
        relative = {name.split("/", 1)[1] for name in names}
        assert "designs.tsv" in relative
        assert "manifest.json" in relative
        assert "designs.csv" not in relative
        structure_entries = [n for n in relative if n.startswith("structures/")]
        assert len(structure_entries) == 10

        header = zf.read("saved_set_Set_A/designs.tsv").decode().splitlines()[0]
        assert "design_id" in header
        assert "final_rank" in header

    def test_download_missing_returns_404(self, api_client, sqlite_designs_repo) -> None:
        resp = api_client.get("/api/saved-sets/does-not-exist/download")
        assert resp.status_code == 404
