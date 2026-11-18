"""HTTP surface for /api/bundles/* and the saved-set download that shares its builder."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

import backend.cache as cache_mod

FIXTURE_PDB = Path(__file__).resolve().parent / "fixtures" / "two_chain_minimal.pdb"
RUN_ID = "run-bundle-http"


def _seed(n: int = 4) -> None:
    cache_mod.run_cache.clear()
    cache_mod.designs_cache.clear()
    cache_mod.designs_by_run_id.clear()
    cache_mod.run_cache[RUN_ID] = {
        "run_id": RUN_ID,
        "method": "bindcraft",
        "path": "/fake",
        "pdb_files": [str(FIXTURE_PDB)],
        "metadata": {"name": "http run"},
    }
    rows = [
        {
            "run_id": RUN_ID,
            "design_id": f"d{i}",
            "method": "bindcraft",
            "source_path": "",
            "pdb_file": FIXTURE_PDB.name,
            "Average_i_pTM": 0.5 + i * 0.05,
            "Binder_RMSD": 3.0 - i * 0.1,
            "Sequence": "ACDEFGHIK",
        }
        for i in range(n)
    ]
    cache_mod.designs_by_run_id[RUN_ID] = rows
    cache_mod.designs_cache.extend(rows)


def _keys(n: int) -> List[Dict[str, str]]:
    return [{"run_id": RUN_ID, "design_id": f"d{i}"} for i in range(n)]


def _zip(resp) -> zipfile.ZipFile:
    return zipfile.ZipFile(BytesIO(resp.content))


def _root(zf: zipfile.ZipFile) -> str:
    names = zf.namelist()
    assert names, "empty zip"
    assert all("/" in name and not name.startswith("/") for name in names), names
    roots = {name.split("/", 1)[0] for name in names}
    assert len(roots) == 1, roots
    return next(iter(roots))


def _read(zf: zipfile.ZipFile, relative: str) -> bytes:
    return zf.read(f"{_root(zf)}/{relative}")


def _relnames(zf: zipfile.ZipFile) -> set:
    root = _root(zf)
    return {name[len(root) + 1 :] for name in zf.namelist()}


class TestDesignsBundleRoute:
    def test_returns_a_zip(self, api_client, sqlite_designs_repo) -> None:
        _seed()
        resp = api_client.post(
            "/api/bundles/designs", json={"keys": _keys(3), "run_ids": [RUN_ID], "label": "demo"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/zip"
        assert "demo.zip" in resp.headers["content-disposition"]
        assert int(resp.headers["content-length"]) == len(resp.content)
        with _zip(resp) as zf:
            assert zf.testzip() is None
            assert _root(zf) == "demo"
            assert "manifest.json" in _relnames(zf)

    def test_empty_selection_is_a_400(self, api_client, sqlite_designs_repo) -> None:
        _seed()
        resp = api_client.post("/api/bundles/designs", json={"keys": [], "run_ids": [RUN_ID]})
        assert resp.status_code == 400

    def test_client_columns_are_merged(self, api_client, sqlite_designs_repo) -> None:
        _seed()
        resp = api_client.post(
            "/api/bundles/designs",
            json={
                "keys": _keys(1),
                "run_ids": [RUN_ID],
                "client_columns": {f"{RUN_ID}\x1fd0\x1f": {"binderdash_rank": 1}},
            },
        )
        assert resp.status_code == 200, resp.text
        with _zip(resp) as zf:
            header = _read(zf, "designs.tsv").decode().splitlines()[0]
        assert "binderdash_rank" in header

    def test_over_cap_is_413_with_the_estimate(
        self, api_client, sqlite_designs_repo, monkeypatch
    ) -> None:
        _seed()
        import backend.routers.bundles as bundles_router
        from backend.bundles.spec import BundleCaps

        monkeypatch.setattr(
            bundles_router,
            "current_caps",
            lambda: BundleCaps(
                max_structure_files=1, max_structure_bytes=0, max_total_bytes=0
            ),
        )
        resp = api_client.post(
            "/api/bundles/designs", json={"keys": _keys(4), "run_ids": [RUN_ID]}
        )
        assert resp.status_code == 413, resp.text
        detail = resp.json()["detail"]
        assert detail["estimate"]["exceeds_cap"] is True
        assert detail["estimate"]["structure_count"] == 4


class TestEstimateRoute:
    def test_estimate_matches_the_bundle_built_for_the_same_request(
        self, api_client, sqlite_designs_repo
    ) -> None:
        _seed()
        body = {"keys": _keys(3), "run_ids": [RUN_ID]}
        estimate = api_client.post("/api/bundles/estimate", json=body).json()
        assert estimate["design_count"] == 3
        assert estimate["structure_count"] == 3
        assert estimate["exceeds_cap"] is False

        resp = api_client.post("/api/bundles/designs", json=body)
        with _zip(resp) as zf:
            manifest = json.loads(_read(zf, "manifest.json"))
        assert manifest["coverage"]["designs"] == estimate["design_count"]
        assert manifest["coverage"]["structures_included"] == estimate["structure_count"]

    def test_estimate_reads_no_structure_bytes(self, api_client, sqlite_designs_repo) -> None:
        _seed()
        estimate = api_client.post(
            "/api/bundles/estimate", json={"keys": _keys(2), "run_ids": [RUN_ID]}
        ).json()
        assert estimate["structure_bytes"] == 2 * FIXTURE_PDB.stat().st_size


class TestPrepareSequencesRoute:
    def test_superset_members(self, api_client, sqlite_designs_repo) -> None:
        _seed()
        resp = api_client.post(
            "/api/bundles/prepare-sequences",
            json={
                "keys": _keys(2),
                "run_ids": [RUN_ID],
                "prepared": {
                    "order_name": "o1",
                    "rows": [
                        {"design_id": "d0", "short_name": "AA", "prepared_aa": "MHHHACD"},
                        {"design_id": "d1", "short_name": "BB", "prepared_aa": "MACD"},
                    ],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        with _zip(resp) as zf:
            assert _root(zf) == "binderdash_constructs"
            names = _relnames(zf)
        assert {"constructs.tsv", "constructs_aa.fasta", "prepare_sequences.json"} <= names

    def test_unknown_prepared_field_is_accepted(self, api_client, sqlite_designs_repo) -> None:
        """extra="allow" is the point: a frontend that gains a field must not break
        downloads for everyone until the backend catches up."""
        _seed()
        resp = api_client.post(
            "/api/bundles/prepare-sequences",
            json={
                "keys": _keys(1),
                "run_ids": [RUN_ID],
                "prepared": {
                    "rows": [
                        {
                            "design_id": "d0",
                            "prepared_aa": "MACD",
                            "some_field_invented_next_year": {"a": 1},
                        }
                    ]
                },
            },
        )
        assert resp.status_code == 200, resp.text

    def test_missing_required_prepared_field_is_422(
        self, api_client, sqlite_designs_repo
    ) -> None:
        _seed()
        resp = api_client.post(
            "/api/bundles/prepare-sequences",
            json={
                "keys": _keys(1),
                "run_ids": [RUN_ID],
                "prepared": {"rows": [{"design_id": "d0"}]},
            },
        )
        assert resp.status_code == 422


class TestSavedSetDownloadParity:
    def _create_set(self, api_client) -> str:
        resp = api_client.post(
            "/api/filtering/run",
            json={
                "name": "parity set",
                "run_ids": [RUN_ID],
                "filters": [],
                "metrics": [{"column": "Average_i_pTM", "weight": 1.0, "higher_is_better": True}],
                "budget": 4,
                "ui_state": {
                    "run_ids": [RUN_ID],
                    "visible_columns": ["design_id", "Average_i_pTM"],
                    "sort": [{"field": "Average_i_pTM", "order": -1}],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["saved_set_id"]

    def test_saved_set_download_has_the_same_shape_as_a_live_bundle(
        self, api_client, sqlite_designs_repo
    ) -> None:
        _seed()
        set_id = self._create_set(api_client)

        saved = api_client.get(f"/api/saved-sets/{set_id}/download")
        assert saved.status_code == 200, saved.text
        live = api_client.post(
            "/api/bundles/designs", json={"keys": _keys(4), "run_ids": [RUN_ID]}
        )
        assert live.status_code == 200, live.text

        def shape(resp) -> set:
            with _zip(resp) as zf:
                return {n for n in _relnames(zf) if not n.startswith("structures/")}

        assert shape(saved) == shape(live)
        with _zip(saved) as zf:
            assert _root(zf) == "saved_set_parity_set"
        with _zip(live) as zf:
            assert _root(zf) == "binderdash_designs"

    def test_saved_set_provenance_and_ui_state(self, api_client, sqlite_designs_repo) -> None:
        _seed()
        set_id = self._create_set(api_client)
        resp = api_client.get(f"/api/saved-sets/{set_id}/download")
        with _zip(resp) as zf:
            manifest = json.loads(_read(zf, "manifest.json"))
            session = json.loads(_read(zf, "binderdash_session.json"))

        assert manifest["provenance"]["source"] == "saved_set"
        assert manifest["provenance"]["saved_set_id"] == set_id
        assert manifest["provenance"]["saved_set_name"] == "parity set"
        # ui_state is binderdash_session.json; carrying it twice in one zip is waste.
        assert "ui_state" not in (manifest["provenance"]["filter_params"] or {})
        assert session["captured"] is True
        assert session["visible_columns"] == ["design_id", "Average_i_pTM"]

    def test_legacy_saved_set_without_ui_state_still_downloads(
        self, api_client, sqlite_designs_repo
    ) -> None:
        _seed()
        resp = api_client.post(
            "/api/filtering/run",
            json={
                "name": "legacy set",
                "run_ids": [RUN_ID],
                "metrics": [{"column": "Average_i_pTM", "weight": 1.0, "higher_is_better": True}],
                "budget": 4,
            },
        )
        set_id = resp.json()["saved_set_id"]
        download = api_client.get(f"/api/saved-sets/{set_id}/download")
        assert download.status_code == 200, download.text
        with _zip(download) as zf:
            assert _root(zf) == "saved_set_legacy_set"
            session = json.loads(_read(zf, "binderdash_session.json"))
        assert session["captured"] is False
        assert "before Binderdash recorded UI state" in session["note"]

    def test_unknown_saved_set_is_404(self, api_client, sqlite_designs_repo) -> None:
        _seed()
        resp = api_client.get("/api/saved-sets/does-not-exist/download")
        assert resp.status_code == 404
