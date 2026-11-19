"""Server paths come from the server: RUN_BASE_DIRS limits browse/scan/ingest, ingest
rebuilds runs from disk instead of persisting what the client sent, stored runs
pointing outside the base dirs are not served, and disabled accounts are refused."""

from pathlib import Path

import pytest
from fastapi import HTTPException, Response

import backend.settings as settings_mod
from backend.auth_providers.base import AuthUser
from backend.path_policy import is_allowed_path, is_within_bases, run_paths_within_bases
from backend.settings import run_base_dir_problems


def _bindcraft_run(folder: Path) -> Path:
    (folder / "Accepted").mkdir(parents=True)
    (folder / "final_design_stats.csv").write_text("Design,Average_i_pTM\nd1,0.8\n")
    (folder / "Accepted" / "d1.pdb").write_text("END\n")
    return folder


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A base dir holding one run, set on the shared settings object.

    Requested before ``api_client`` so the copy that fixture makes inherits it.
    """
    b = tmp_path / "base"
    _bindcraft_run(b / "proj" / "run1")
    monkeypatch.setattr(settings_mod.settings, "run_base_dirs", [str(b)])
    return b


def test_path_policy(tmp_path: Path) -> None:
    inside = tmp_path / "base" / "run"
    inside.mkdir(parents=True)
    bases = [str(tmp_path / "base")]
    assert is_allowed_path(str(inside), []) is False  # no bases: nothing, not everything
    assert is_allowed_path(str(inside), bases)
    assert is_within_bases(str(inside), bases)
    assert not is_within_bases(f"{inside}/../../etc/passwd", bases)
    assert not is_within_bases(str(tmp_path / "base-other"), bases)  # prefix, not parent

    run = {"path": str(inside), "results_table": "t.csv", "pdb_files": [str(inside / "a.pdb")]}
    assert run_paths_within_bases(run, bases)
    assert not run_paths_within_bases({**run, "pdb_files": ["/etc/passwd"]}, bases)
    assert not run_paths_within_bases({**run, "results_table": "../../../../x.csv"}, bases)
    assert not run_paths_within_bases({**run, "merged_paths": [str(inside), "/etc"]}, bases)


def test_run_base_dir_problems(tmp_path: Path) -> None:
    assert run_base_dir_problems([]) and run_base_dir_problems([" ", ""])
    assert run_base_dir_problems([str(tmp_path), str(tmp_path / "missing")]) == [
        f"RUN_BASE_DIRS entry is not an existing directory: {tmp_path / 'missing'}"
    ]
    assert run_base_dir_problems([str(tmp_path)]) == []


def test_server_refuses_to_start_without_usable_base_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.main as main_mod
    from fastapi.testclient import TestClient

    for dirs in ([], [str(tmp_path / "missing")]):
        monkeypatch.setattr(
            main_mod, "settings", main_mod.settings.model_copy(update={"run_base_dirs": dirs})
        )
        with pytest.raises(RuntimeError, match="Refusing to start"):
            with TestClient(main_mod.app):
                pass


def test_ingest_rebuilds_run_from_disk(base: Path, api_client) -> None:
    run_dir = base / "proj" / "run1"
    forged = {
        "path": str(run_dir),
        "project_id": "proj",
        "metadata": {"name": "run1"},
        "results_table": "../../../../../../etc/hosts",
        "pdb_files": ["/etc/passwd"],
    }
    r = api_client.post("/api/runs/ingest", json={"runs": [forged]})
    assert r.status_code == 200, r.text
    (run,) = r.json()["runs"]
    assert run["pdb_files"] == [str(run_dir / "Accepted" / "d1.pdb")]
    assert run["results_table"] == "final_design_stats.csv"
    assert api_client.get(f"/api/runs/{run['run_id']}/files/pdb/passwd").status_code == 404


def test_ingest_rejects_folders_outside_base_or_not_runs(base: Path, api_client) -> None:
    outside = _bindcraft_run(base.parent / "outside")
    for path in (str(outside), f"{base}/../outside", str(base / "proj")):
        r = api_client.post("/api/runs/ingest", json={"runs": [{"path": path}]})
        assert r.status_code == 400, (path, r.text)


def test_tree_and_scan_stay_inside_base(base: Path, api_client) -> None:
    roots = api_client.get("/api/tree").json()["folders"]
    assert [f["path"] for f in roots] == [str(base.resolve())]
    assert api_client.get("/api/tree", params={"path": "/etc"}).status_code == 400
    scan = api_client.post("/api/runs/scan", json={"folders": ["/etc", str(base)]})
    assert [r["path"] for r in scan.json()["runs"]] == [str(base / "proj" / "run1")]


def test_hydrate_skips_stored_runs_outside_base(
    tmp_path: Path, sqlite_designs_repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend import cache

    b = tmp_path / "base"
    run_dir = _bindcraft_run(b / "run1")
    monkeypatch.setattr(settings_mod.settings, "run_base_dirs", [str(b)])
    good = {"path": str(run_dir), "pdb_files": [str(run_dir / "Accepted" / "d1.pdb")]}
    bad = {**good, "pdb_files": ["/etc/passwd"]}
    for rid, run in (("good", good), ("bad", bad)):
        run = {**run, "run_id": rid, "project_id": "p", "metadata": {"name": rid}, "method": "bindcraft"}
        sqlite_designs_repo.upsert_run_and_replace_designs(f"p/{rid}", rid, run, [])
    cache.hydrate_caches_from_repository()
    assert set(cache.run_cache) == {"good"}


def test_disabled_account_is_refused(sqlite_designs_repo) -> None:
    from backend.auth import _enrich_from_db, issue_session_cookies

    row = sqlite_designs_repo.upsert_login_identity(provider="local", identifier="alice")
    conn = sqlite_designs_repo._get_conn()
    conn.execute("UPDATE binderdash_users SET is_active = 0 WHERE id = ?", (row["id"],))
    conn.commit()
    alice = AuthUser(username="alice", provider="local")

    with pytest.raises(HTTPException) as session:
        _enrich_from_db(alice, row["id"])
    assert session.value.status_code == 401
    with pytest.raises(HTTPException) as login:
        issue_session_cookies(Response(), alice)
    assert login.value.status_code == 403
