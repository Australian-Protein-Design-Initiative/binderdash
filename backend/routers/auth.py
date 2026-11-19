from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from ..auth import (
    clear_auth_cookie,
    clear_csrf_cookie,
    get_current_active_user,
    issue_session_cookies,
)
from ..auth_providers.base import AuthUser
from ..auth_providers.google import get_oauth, google_oauth_configured
from ..auth_providers.local import authenticate_local
from ..schemas import LoginRequest
from ..settings import settings


router = APIRouter(prefix="/api/auth", tags=["auth"])


def safe_next_url(next_q: str | None) -> str:
    """Same-origin return path, including its query string and fragment.

    Browsers never send a URL fragment to the server, so the login page has to
    encode it into this value (``/#filtering`` arrives as ``next=%2F%23filtering``).
    """
    if not next_q:
        return "/"
    n = next_q.strip()
    if not n.startswith("/") or n.startswith("//") or n.startswith("/\\"):
        return "/"
    if any(ord(c) < 32 or c == "\\" for c in n):
        return "/"
    parts = urlsplit(n)
    if parts.scheme or parts.netloc:
        return "/"
    return n


def _without_auth_error(next_url: str) -> str:
    parts = urlsplit(next_url)
    if "auth_error=" not in parts.query:
        return next_url
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "auth_error"
    ]
    return urlunsplit(("", "", parts.path or "/", urlencode(query), parts.fragment))


def _auth_error_redirect(next_url: str, error: str) -> RedirectResponse:
    parts = urlsplit(safe_next_url(next_url))
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "auth_error"
    ]
    query.append(("auth_error", error))
    target = urlunsplit(("", "", parts.path or "/", urlencode(query), parts.fragment))
    return RedirectResponse(url=target, status_code=302)


@router.post("/login")
async def login(login_request: LoginRequest, response: Response):
    if not settings.local_auth_enabled() and not settings.pam_local_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Username/password login is disabled",
        )

    user = authenticate_local(login_request.username, login_request.password)
    if user is None and settings.pam_local_enabled:
        from ..auth_providers.pam import authenticate_pam

        user = await authenticate_pam(login_request.username, login_request.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    csrf_token = issue_session_cookies(response, user)
    return {
        "message": "Login successful",
        "user": _user_payload(user),
        "csrf_token": csrf_token,
    }


@router.post("/logout")
async def logout(response: Response):
    clear_auth_cookie(response)
    clear_csrf_cookie(response)
    return {"message": "Logout successful"}


def _user_payload(user: AuthUser) -> dict:
    last_login = None
    if user.user_id is not None:
        try:
            from ..persistence.factory import get_designs_repository

            row = get_designs_repository().get_user_by_id(user.user_id)
            if row:
                last_login = row.get("last_login_at")
        except Exception:
            pass
    return {
        "username": user.username,
        "provider": user.provider,
        "email": user.email,
        "display_name": user.display_name,
        "picture_url": user.picture_url,
        "user_id": user.user_id,
        "is_admin": user.is_admin,
        "auth_method": user.auth_method,
        "last_login_at": last_login,
    }


@router.get("/me")
async def read_users_me(current_user: AuthUser = Depends(get_current_active_user)):
    return _user_payload(current_user)


@router.get("/status")
async def auth_status():
    from ..api_keys import api_keys_available
    from ..mcp_server import MCP_MOUNT_PATH
    from ..mcp_server.server import mcp_available

    google_login_path = "/api/auth/google/login"
    if settings.auth_disabled:
        keys_reason = "auth_disabled"
    elif not api_keys_available():
        keys_reason = "persistence_disabled"
    else:
        keys_reason = None
    return {
        "auth_disabled": settings.auth_disabled,
        "desktop_mode": settings.binderdash_desktop,
        "providers": {
            "local": {"enabled": settings.local_auth_enabled()},
            "pam": {"enabled": settings.pam_local_enabled},
            "google": {
                "enabled": google_oauth_configured(),
                "login_url": google_login_path,
            },
        },
        "api_keys": {"enabled": keys_reason is None, "reason": keys_reason},
        # The MCP server is an optional extra, so the UI must not offer client setup
        # instructions for an endpoint this deployment does not serve.
        "mcp": {"enabled": mcp_available(), "path": f"{MCP_MOUNT_PATH}/"},
    }


@router.get("/google/login")
async def google_login(request: Request):
    if not google_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )
    request.session["post_oauth_next"] = safe_next_url(
        request.query_params.get("next")
    )
    oauth = get_oauth()
    return await oauth.google.authorize_redirect(
        request,
        settings.google_auth_redirect_uri,
    )


@router.get("/google/callback")
async def google_callback(request: Request):
    if not google_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )
    oauth = get_oauth()
    next_url = safe_next_url(request.session.pop("post_oauth_next", None))
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        return _auth_error_redirect(next_url, "oauth_failed")

    userinfo = token.get("userinfo") or {}
    if not (isinstance(userinfo, dict) and userinfo.get("email")):
        access = token.get("access_token")
        if access:
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(
                        "https://www.googleapis.com/oauth2/v3/userinfo",
                        headers={"Authorization": f"Bearer {access}"},
                    )
                    if r.status_code == 200:
                        userinfo = r.json()
            except Exception:
                pass
    if not isinstance(userinfo, dict):
        userinfo = {}
    email = (userinfo.get("email") or "").strip()
    if not email or not settings.is_google_user_allowed(email):
        return _auth_error_redirect(next_url, "not_allowed")

    next_url = _without_auth_error(next_url)
    # The identity stays keyed on the email (not the opaque `sub`) so existing
    # sessions and the allowlist check in _claims_to_user keep working; `name`
    # and `picture` were previously fetched and thrown away.
    user = AuthUser(
        username=email,
        provider="google",
        email=email,
        display_name=(userinfo.get("name") or "").strip() or None,
        picture_url=(userinfo.get("picture") or "").strip() or None,
    )
    resp = RedirectResponse(url=next_url, status_code=302)
    try:
        issue_session_cookies(resp, user)
    except HTTPException as e:
        if e.status_code == status.HTTP_403_FORBIDDEN:
            return _auth_error_redirect(next_url, "account_disabled")
        raise
    return resp
