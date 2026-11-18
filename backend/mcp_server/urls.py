"""Absolute download URLs for MCP clients.

An agent that only has the MCP config cannot see the server origin, and composing
``base + path + token`` is where a weaker client drops a piece. Download tools
therefore return one absolute URL with the token already in the query string.
"""

from __future__ import annotations

from typing import Optional


def public_base_url() -> Optional[str]:
    """Origin to prefix download paths with, or None when it cannot be known.

    Order: ``PUBLIC_BASE_URL``, then ``https://`` plus ``DOMAIN`` when that is a
    real hostname, then the incoming request (forwarded proto/host when both are
    set, otherwise the request's own scheme and host). Forwarded headers are
    copied into a URL returned to the authenticated caller only — they are not
    used for redirects or cookies.
    """
    from ..settings import settings

    configured = (settings.public_base_url or "").strip().rstrip("/")
    if configured:
        return configured

    domain = (settings.domain or "").strip()
    host = domain.split("://")[-1].strip().strip("/")
    if host and not _is_local_host(host):
        return f"https://{host}"

    return _request_base_url()


def absolute_url(path: str) -> str:
    """Prefix ``path`` when an origin is known. Leave it relative otherwise."""
    if path.startswith(("http://", "https://")):
        return path
    base = public_base_url()
    if not base:
        return path
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def with_relative_note(note: str) -> str:
    """Say so when the URLs in this payload could not be made absolute."""
    if public_base_url() is not None:
        return note
    return note.rstrip() + " base_url is unset, so download URLs are origin-relative."


def _is_local_host(host: str) -> bool:
    name = host.lower()
    return name == "localhost" or name.startswith("localhost:") or name.startswith("127.0.0.1")


def _request_base_url() -> Optional[str]:
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
    except Exception:
        return None
    if request is None:
        return None
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    if proto and host:
        return f"{proto}://{host}".rstrip("/")
    base = getattr(request, "base_url", None)
    if base is None:
        return None
    text = str(base).rstrip("/")
    return text or None
