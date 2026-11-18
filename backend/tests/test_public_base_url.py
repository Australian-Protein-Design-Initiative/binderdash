"""Origin used to make MCP download URLs absolute."""

import pytest

import backend.settings as settings_mod
from backend.mcp_server.urls import absolute_url, public_base_url


def _settings(**update: str):
    return settings_mod.settings.model_copy(
        update={"public_base_url": "", "domain": "", **update}
    )


def test_public_base_url_wins_over_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_mod,
        "settings",
        _settings(public_base_url="https://bd.example", domain="other.example"),
    )
    assert public_base_url() == "https://bd.example"
    assert absolute_url("/api/designs") == "https://bd.example/api/designs"


def test_domain_used_when_public_base_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_mod,
        "settings",
        _settings(domain="binderdash.example.com"),
    )
    assert public_base_url() == "https://binderdash.example.com"


def test_localhost_domain_is_not_a_public_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod, "settings", _settings(domain="localhost"))

    def _no_request():
        raise RuntimeError("no request")

    fastmcp = pytest.importorskip("fastmcp.server.dependencies")
    monkeypatch.setattr(fastmcp, "get_http_request", _no_request)
    assert public_base_url() is None
    assert absolute_url("/api/pdbs/tar") == "/api/pdbs/tar"


def test_forwarded_headers_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod, "settings", _settings())
    fastmcp = pytest.importorskip("fastmcp.server.dependencies")

    class _Request:
        headers = {
            "x-forwarded-proto": "https, http",
            "x-forwarded-host": "bd.example, internal",
        }
        base_url = "http://binderdash:8000/"

    monkeypatch.setattr(fastmcp, "get_http_request", lambda: _Request())
    assert public_base_url() == "https://bd.example"


def test_request_base_when_no_forwarded_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod, "settings", _settings())
    fastmcp = pytest.importorskip("fastmcp.server.dependencies")

    class _Request:
        headers: dict[str, str] = {}
        base_url = "http://127.0.0.1:8000/"

    monkeypatch.setattr(fastmcp, "get_http_request", lambda: _Request())
    assert public_base_url() == "http://127.0.0.1:8000"
