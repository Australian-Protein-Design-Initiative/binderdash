import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, Response, status
from jose import JWTError, jwt

from .auth_providers.base import AuthUser
from .settings import SECRET_KEY, settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
COOKIE_NAME = "binderdash_session"
CSRF_COOKIE_NAME = "binderdash_csrf"
API_KEY_HEADER = "X-Binderdash-Api-Key"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def set_auth_cookie(
    response: Response, token: str, expires_delta: Optional[timedelta] = None
):
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        expires=expire,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response):
    response.delete_cookie(
        key=COOKIE_NAME, path="/", httponly=True, secure=False, samesite="lax"
    )


def get_token_from_cookie(request: Request) -> Optional[str]:
    return request.cookies.get(COOKIE_NAME)


def request_has_valid_api_key(request: Request) -> bool:
    from .api_keys import resolve_principal

    return resolve_principal(request) is not None


def user_from_api_key(request: Request) -> Optional[AuthUser]:
    from .api_keys import resolve_principal

    principal = resolve_principal(request)
    if principal is None:
        return None
    return AuthUser(
        username=principal.username,
        provider=principal.provider,
        email=principal.email,
        display_name=principal.display_name,
        user_id=principal.user_id,
        is_admin=principal.is_admin,
        auth_method="api_key",
        api_key_id=principal.key_id,
    )


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str):
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=False,
        samesite="lax",
        path="/",
    )


def clear_csrf_cookie(response: Response):
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/", secure=False, samesite="lax")


def _claims_to_user(sub: str, provider: str, email: Optional[str]) -> AuthUser:
    if provider == "local":
        if not any(u.username == sub for u in settings.local_users):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AuthUser(username=sub, provider="local", email=None)
    if provider == "pam":
        if not settings.pam_local_enabled or not settings.is_pam_user_allowed(sub):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AuthUser(username=sub, provider="pam", email=None)
    if provider == "google":
        em = (email or sub or "").strip()
        if not settings.google_auth_enabled or not settings.is_google_user_allowed(em):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AuthUser(username=em, provider="google", email=em)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _account_disabled(status_code: int) -> HTTPException:
    """401 for a request on an existing session (the client treats it as signed
    out), 403 at login (the credentials were fine; the account is not)."""
    return HTTPException(status_code=status_code, detail="This account is disabled")


def _enrich_from_db(user: AuthUser, uid: Optional[int]) -> AuthUser:
    """Attach user_id/is_admin to a session user.

    Authorization still comes from settings (``_claims_to_user`` has already
    re-validated the allowlists); the database only enriches, with one exception:
    a user marked inactive is rejected, as their API keys already are. Any other
    failure here degrades to "not an admin" rather than rejecting the request.
    """
    try:
        from .persistence.factory import get_designs_repository

        repo = get_designs_repository()
        row = None
        if uid is not None:
            row = repo.get_user_by_id(uid)
        if row is None:
            # Cookie issued before this release, or the user was merged away.
            row = repo.get_user_by_identity(user.provider, identity_for(user))
        if row is None:
            return user
        if not row.get("is_active", True):
            raise _account_disabled(status.HTTP_401_UNAUTHORIZED)
        return user.model_copy(
            update={
                "user_id": row.get("id"),
                "is_admin": bool(row.get("is_admin")),
                "display_name": user.display_name or row.get("display_name"),
                "picture_url": user.picture_url or row.get("picture_url"),
                "email": user.email or row.get("email"),
            }
        )
    except HTTPException:
        raise
    except RuntimeError:
        return user
    except Exception:
        logger.exception("Failed to enrich session user from repository")
        return user


def _decode_user_from_payload(payload: dict[str, Any]) -> AuthUser:
    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    provider = payload.get("provider") or "local"
    email = payload.get("email")
    if email is not None and not isinstance(email, str):
        email = str(email)
    user = _claims_to_user(str(sub), str(provider), email)
    raw_uid = payload.get("uid")
    uid = int(raw_uid) if isinstance(raw_uid, (int, str)) and str(raw_uid).isdigit() else None
    return _enrich_from_db(user, uid)


async def get_current_user(request: Request) -> AuthUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = get_token_from_cookie(request)
    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return _decode_user_from_payload(payload)
    except HTTPException:
        raise
    except JWTError:
        raise credentials_exception


async def get_current_active_user(current_user: AuthUser = Depends(get_current_user)):
    return current_user


async def get_current_user_optional(request: Request):
    if settings.auth_disabled:
        return None

    api_user = user_from_api_key(request)
    if api_user is not None:
        return api_user

    token = get_token_from_cookie(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_current_user(request)


async def request_is_authenticated(request: Request) -> bool:
    """Non-raising "does this caller have a session or key?", for responses that
    reveal more to a known user than to an anonymous one.

    Auth being disabled counts as authenticated: there is nobody to withhold from.
    """
    if settings.auth_disabled:
        return True
    if request_has_valid_api_key(request):
        return True
    try:
        await get_current_user(request)
    except HTTPException:
        return False
    return True


async def get_current_user_optional_with_query(
    request: Request,
    token: Optional[str] = None,
):
    if settings.auth_disabled:
        return None

    api_user = user_from_api_key(request)
    if api_user is not None:
        return api_user

    cookie_token = get_token_from_cookie(request)
    if cookie_token:
        try:
            return await get_current_user(request)
        except Exception:
            pass

    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return _decode_user_from_payload(payload)
        except (JWTError, HTTPException):
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def identity_for(user: AuthUser) -> str:
    """The stable per-provider identifier used to key an identity row."""
    return user.username


def record_login_audit(user: AuthUser) -> Optional[dict[str, Any]]:
    """Upsert the user + identity for a successful login. Returns the user row.

    Never raises: a database blip must not stop someone logging in. The caller
    simply issues a token without a ``uid`` claim in that case.
    """
    try:
        from .persistence.factory import get_designs_repository

        repo = get_designs_repository()
        return repo.upsert_login_identity(
            provider=user.provider,
            identifier=identity_for(user),
            email=user.email,
            display_name=user.display_name,
            picture_url=user.picture_url,
            is_admin=settings.is_admin_identity(
                user.provider, identity_for(user), user.email
            ),
        )
    except RuntimeError:
        # Repository not initialised (no persistence configured).
        logger.warning("Login not recorded: designs repository is not initialised")
        return None
    except Exception:
        logger.exception("upsert_login_identity failed")
        return None


def issue_session_cookies(response: Response, user: AuthUser) -> str:
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    token_data: dict[str, Any] = {
        "sub": user.username,
        "provider": user.provider,
    }
    if user.email:
        token_data["email"] = user.email
    row = record_login_audit(user)
    if row and not row.get("is_active", True):
        raise _account_disabled(status.HTTP_403_FORBIDDEN)
    if row and row.get("id") is not None:
        # Cached so per-request auth needs no database round trip. is_admin is
        # deliberately NOT in the token: the cookie lives 24h, so a demoted
        # admin would keep their rights for a day. It is resolved per request.
        token_data["uid"] = int(row["id"])
        # Fill in what only the database knows, so the login response carries
        # the same shape as /api/auth/me and the client is not left with a
        # user object missing is_admin until its next refresh.
        user.user_id = int(row["id"])
        user.is_admin = bool(row.get("is_admin"))
        user.display_name = user.display_name or row.get("display_name")
        user.picture_url = user.picture_url or row.get("picture_url")
        user.email = user.email or row.get("email")
    access_token = create_access_token(
        data=token_data,
        expires_delta=access_token_expires,
    )
    set_auth_cookie(response, access_token, access_token_expires)
    csrf = generate_csrf_token()
    set_csrf_cookie(response, csrf)
    return csrf
