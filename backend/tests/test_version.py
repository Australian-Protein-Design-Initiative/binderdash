"""Build identity resolution across the three ways Binderdash ships."""

from __future__ import annotations

import json
import subprocess

import pytest

import backend.version as version_mod


@pytest.fixture(autouse=True)
def _clear_cache():
    version_mod.build_identity.cache_clear()
    yield
    version_mod.build_identity.cache_clear()


def test_env_wins(monkeypatch) -> None:
    monkeypatch.setenv("BINDERDASH_GIT_COMMIT", "cafebabe1234")
    identity = version_mod.build_identity()
    assert identity.git_commit == "cafebabe1234"
    assert identity.source == "env"


def test_build_file_used_when_env_absent(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("BINDERDASH_GIT_COMMIT", raising=False)
    build_file = tmp_path / "_build_info.json"
    build_file.write_text(json.dumps({"version": "9.9.9", "git_commit": "deadbeef", "git_dirty": False}))
    monkeypatch.setattr(version_mod, "_build_info_path", lambda: build_file)
    identity = version_mod.build_identity()
    assert (identity.app_version, identity.git_commit, identity.source) == (
        "9.9.9",
        "deadbeef",
        "build_file",
    )


def test_falls_back_to_unknown_without_git(monkeypatch, tmp_path) -> None:
    """A frozen build has no .git and no git binary; that must degrade, not raise."""
    monkeypatch.delenv("BINDERDASH_GIT_COMMIT", raising=False)
    monkeypatch.setattr(version_mod, "_build_info_path", lambda: tmp_path / "absent.json")
    monkeypatch.setattr(version_mod, "_repo_root", lambda: None)
    identity = version_mod.build_identity()
    assert identity.source == "unknown"
    assert identity.git_commit is None
    assert identity.app_version


def test_git_failure_is_swallowed(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("BINDERDASH_GIT_COMMIT", raising=False)
    monkeypatch.setattr(version_mod, "_build_info_path", lambda: tmp_path / "absent.json")
    monkeypatch.setattr(version_mod, "_repo_root", lambda: tmp_path)

    def _boom(*args, **kwargs):
        raise FileNotFoundError("git not installed")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert version_mod.build_identity().source == "unknown"


def test_build_label_names_the_commit_and_whether_it_was_dirty(monkeypatch) -> None:
    monkeypatch.setattr(
        version_mod,
        "build_identity",
        lambda: version_mod.BuildIdentity("1.2.3", "cafebabe", True, "env"),
    )
    assert version_mod.build_label() == "1.2.3 (cafebabe, modified)"
    assert version_mod.build_payload()["git_dirty"] is True


def test_health_reports_the_build_to_an_authenticated_caller(api_client) -> None:
    # The api_client fixture runs with auth disabled, which counts as authenticated.
    body = api_client.get("/health").json()
    assert body["status"] == "healthy"
    assert body["build"]["version"]
    assert set(body["build"]) == {"version", "git_commit", "git_dirty", "label"}
    info = api_client.get("/openapi.json").json()["info"]
    assert info["version"] == version_mod.build_label()


def test_health_and_openapi_withhold_the_build_from_anonymous_callers(
    api_client, monkeypatch
) -> None:
    """Version disclosure is the one thing an internet-facing scanner can reach."""
    import backend.auth as auth_mod

    monkeypatch.setattr(
        auth_mod,
        "settings",
        auth_mod.settings.model_copy(update={"auth_disabled": False}),
    )
    body = api_client.get("/health").json()
    assert body["status"] == "healthy"
    assert "build" not in body
    assert api_client.get("/openapi.json").json()["info"]["version"] == "unversioned"
    assert api_client.get("/docs").status_code == 200


def test_desktop_router_still_reports_a_version() -> None:
    """Regression guard on moving _app_version out of routers/desktop.py."""
    from backend.routers.desktop import _app_version

    assert _app_version() not in ("", None)
