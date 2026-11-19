from pathlib import Path

import pytest

import backend.settings as _settings_mod
from backend.persistence.factory import set_designs_repository
from backend.persistence.noop_repo import NoopDesignsRepository
from backend.persistence.sqlite_repo import SqliteDesignsRepository

# The app refuses to start without an existing RUN_BASE_DIRS (main.lifespan), and pytest
# runs without the repo's .env. Tests that need specific base dirs set their own.
if not _settings_mod.settings.run_base_dirs:
    _settings_mod.settings.run_base_dirs = [str(Path(__file__).resolve().parent / "fixtures")]


@pytest.fixture(autouse=True)
def _reset_api_key_cache():
    """backend/api_keys.py holds module-level mutable cache state.

    Without this, a positive/negative cache entry from one test can leak into
    the next and make results depend on test ordering.
    """
    from backend.api_keys import reset_cache

    reset_cache()
    yield
    reset_cache()


@pytest.fixture
def sqlite_designs_repo(tmp_path: Path):
    url = f"sqlite:///{tmp_path}/designs.sqlite"
    repo = SqliteDesignsRepository(url)
    repo.init_schema()
    set_designs_repository(repo)
    yield repo
    set_designs_repository(NoopDesignsRepository())


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import backend.auth as auth_mod
    import backend.main as main_mod
    import backend.settings as settings_mod
    from backend.auth import get_current_user_optional
    from backend.routers.designs import _authorize_list_designs
    from fastapi.testclient import TestClient

    patched_settings = main_mod.settings.model_copy(update={"auth_disabled": True})
    for mod in (main_mod, settings_mod, auth_mod):
        monkeypatch.setattr(mod, "settings", patched_settings)
    monkeypatch.setattr(
        main_mod,
        "default_sqlite_url",
        lambda: f"sqlite:///{tmp_path}/api.sqlite",
    )

    async def _auth_bypass():
        return None

    app = main_mod.app
    app.dependency_overrides[get_current_user_optional] = _auth_bypass
    app.dependency_overrides[_authorize_list_designs] = _auth_bypass
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
