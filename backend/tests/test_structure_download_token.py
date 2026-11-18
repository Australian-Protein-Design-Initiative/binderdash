"""Structure-file and structure-archive download tokens."""

import io
import tarfile
from pathlib import Path

import backend.cache as cache_mod
from backend.auth import COOKIE_NAME, create_access_token
from backend.download_tokens import (
    mint_designs_download_token,
    mint_structure_archive_token,
    mint_structure_file_token,
)
from backend.settings import LocalUser
from backend.structure_archive import clear as clear_archive
from backend.structure_archive import put as stash_archive


def _enable_auth(api_client, monkeypatch) -> None:
    import backend.auth as auth_mod
    import backend.main as main_mod
    import backend.settings as settings_mod

    patched = settings_mod.settings.model_copy(
        update={
            "auth_disabled": False,
            "local_users": [LocalUser(username="alice", password_hash="x")],
        }
    )
    for mod in (settings_mod, main_mod, auth_mod):
        monkeypatch.setattr(mod, "settings", patched)


def _seed_structure(tmp_path: Path) -> None:
    pdb = tmp_path / "design.pdb"
    pdb.write_text("END\n", encoding="utf-8")
    cache_mod.run_cache["run-a"] = {
        "run_id": "run-a",
        "project_id": "proj",
        "method": "bindcraft",
        "metadata": {"name": "run"},
        "pdb_files": [str(pdb)],
    }


def setup_function() -> None:
    cache_mod.run_cache.clear()
    clear_archive()


def teardown_function() -> None:
    cache_mod.run_cache.clear()
    clear_archive()


def test_download_token_allows_unauthenticated_structure_get(api_client, monkeypatch, tmp_path) -> None:
    _enable_auth(api_client, monkeypatch)
    _seed_structure(tmp_path)
    token = mint_structure_file_token("run-a", "design.pdb")
    response = api_client.get(
        "/api/runs/run-a/files/structure/design.pdb",
        params={"download_token": token},
    )
    assert response.status_code == 200
    assert response.content == b"END\n"


def test_download_token_wrong_file_is_403(api_client, monkeypatch, tmp_path) -> None:
    _enable_auth(api_client, monkeypatch)
    _seed_structure(tmp_path)
    token = mint_structure_file_token("run-a", "other.pdb")
    response = api_client.get(
        "/api/runs/run-a/files/structure/design.pdb",
        params={"download_token": token},
    )
    assert response.status_code == 403


def test_download_token_wrong_run_is_403(api_client, monkeypatch, tmp_path) -> None:
    _enable_auth(api_client, monkeypatch)
    _seed_structure(tmp_path)
    token = mint_structure_file_token("run-b", "design.pdb")
    response = api_client.get(
        "/api/runs/run-a/files/structure/design.pdb",
        params={"download_token": token},
    )
    assert response.status_code == 403


def test_designs_token_is_not_a_structure_token(api_client, monkeypatch, tmp_path) -> None:
    _enable_auth(api_client, monkeypatch)
    _seed_structure(tmp_path)
    token = mint_designs_download_token("run-a", "json")
    response = api_client.get(
        "/api/runs/run-a/files/structure/design.pdb",
        params={"download_token": token},
    )
    assert response.status_code == 403


def test_without_token_requires_auth_when_enabled(api_client, monkeypatch, tmp_path) -> None:
    _enable_auth(api_client, monkeypatch)
    _seed_structure(tmp_path)
    response = api_client.get("/api/runs/run-a/files/structure/design.pdb")
    assert response.status_code == 401


def test_session_cookie_still_downloads(api_client, monkeypatch, tmp_path) -> None:
    _enable_auth(api_client, monkeypatch)
    _seed_structure(tmp_path)
    session = create_access_token({"sub": "alice", "provider": "local"})
    api_client.cookies.set(COOKIE_NAME, session)
    response = api_client.get("/api/runs/run-a/files/structure/design.pdb")
    assert response.status_code == 200
    assert response.content == b"END\n"


def test_session_query_token_still_downloads(api_client, monkeypatch, tmp_path) -> None:
    _enable_auth(api_client, monkeypatch)
    _seed_structure(tmp_path)
    session = create_access_token({"sub": "alice", "provider": "local"})
    response = api_client.get(
        "/api/runs/run-a/files/structure/design.pdb",
        params={"token": session},
    )
    assert response.status_code == 200


def test_invalid_download_token_does_not_fall_through_to_cookie(
    api_client, monkeypatch, tmp_path
) -> None:
    _enable_auth(api_client, monkeypatch)
    _seed_structure(tmp_path)
    session = create_access_token({"sub": "alice", "provider": "local"})
    api_client.cookies.set(COOKIE_NAME, session)
    response = api_client.get(
        "/api/runs/run-a/files/structure/design.pdb",
        params={"download_token": "not-a-token"},
    )
    assert response.status_code == 403


def test_archive_get_streams_tar(api_client, tmp_path) -> None:
    pdb = tmp_path / "a.pdb"
    pdb.write_text("END\n", encoding="utf-8")
    download_id = stash_archive([("proj/run/a.pdb", pdb)])
    token = mint_structure_archive_token(download_id)
    response = api_client.get(
        "/api/pdbs/tar",
        params={"download_id": download_id, "download_token": token},
    )
    assert response.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:") as archive:
        assert archive.getnames() == ["proj/run/a.pdb"]
        member = archive.extractfile("proj/run/a.pdb")
        assert member is not None
        assert member.read() == b"END\n"


def test_archive_token_does_not_read_another_stash(api_client, tmp_path) -> None:
    pdb = tmp_path / "a.pdb"
    pdb.write_text("END\n", encoding="utf-8")
    mine = stash_archive([("proj/run/a.pdb", pdb)])
    theirs = stash_archive([("proj/run/a.pdb", pdb)])
    token = mint_structure_archive_token(theirs)
    response = api_client.get(
        "/api/pdbs/tar",
        params={"download_id": mine, "download_token": token},
    )
    assert response.status_code == 403


def test_archive_get_404s_after_the_stash_is_gone(api_client, tmp_path) -> None:
    pdb = tmp_path / "a.pdb"
    pdb.write_text("END\n", encoding="utf-8")
    download_id = stash_archive([("proj/run/a.pdb", pdb)], ttl_seconds=0)
    token = mint_structure_archive_token(download_id)
    response = api_client.get(
        "/api/pdbs/tar",
        params={"download_id": download_id, "download_token": token},
    )
    assert response.status_code == 404
    assert "export_structures" in response.json()["detail"]
