"""Short-lived, object-scoped JWTs for downloading design tables without an API key.

Minted by MCP ``list_runs`` into ``designs_json_url`` / ``designs_tsv_url`` so an agent
can curl the REST path without access to the MCP config's bearer key. Claims bind the
token to one ``run_id`` and one ``format``; anything else is rejected.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from jose import JWTError, jwt

from .auth import ALGORITHM
from .settings import SECRET_KEY

PURPOSE_DESIGNS_DOWNLOAD = "designs_download"
PURPOSE_PREPARE_DOWNLOAD = "prepare_download"
DEFAULT_TTL_SECONDS = 600

DesignsFormat = Literal["json", "tsv"]
PrepareFormat = Literal["json", "tsv", "csv", "twist", "fasta"]


class DownloadTokenError(ValueError):
    """Token missing, expired, or not valid for the requested object."""


def mint_designs_download_token(
    run_id: str,
    fmt: DesignsFormat,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "purpose": PURPOSE_DESIGNS_DOWNLOAD,
        "run_id": str(run_id),
        "format": fmt,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_designs_download_token(token: str) -> Dict[str, Any]:
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise DownloadTokenError("Invalid or expired download_token") from e
    if claims.get("purpose") != PURPOSE_DESIGNS_DOWNLOAD:
        raise DownloadTokenError("download_token is not a designs download token")
    run_id = claims.get("run_id")
    fmt = claims.get("format")
    if not isinstance(run_id, str) or not run_id.strip():
        raise DownloadTokenError("download_token missing run_id")
    if fmt not in ("json", "tsv"):
        raise DownloadTokenError("download_token missing or invalid format")
    return {"run_id": run_id, "format": fmt}


def assert_designs_download_claims(
    claims: Dict[str, Any],
    *,
    run_id: Optional[str],
    fmt: DesignsFormat,
) -> None:
    """Ensure the token is scoped exactly to this single-run download."""
    if not run_id or claims["run_id"] != run_id:
        raise DownloadTokenError("download_token does not match run_ids")
    if claims["format"] != fmt:
        raise DownloadTokenError("download_token does not match format")


def mint_prepare_download_token(
    prepare_id: str,
    fmt: PrepareFormat,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Scope a download to one stashed prepare request and one format.

    A prepare request is a whole configuration, far too large for a JWT claim, so
    the payload is stashed server-side and the token carries only its id. This is
    a separate purpose from the designs download rather than a widening of it, so
    a token for one can never be replayed against the other.
    """
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "purpose": PURPOSE_PREPARE_DOWNLOAD,
        "prepare_id": str(prepare_id),
        "format": fmt,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_prepare_download_token(token: str, *, prepare_id: str, fmt: str) -> None:
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise DownloadTokenError("Invalid or expired download_token") from e
    if claims.get("purpose") != PURPOSE_PREPARE_DOWNLOAD:
        raise DownloadTokenError("download_token is not a prepare download token")
    if claims.get("prepare_id") != prepare_id:
        raise DownloadTokenError("download_token does not match prepare_id")
    if claims.get("format") != fmt:
        raise DownloadTokenError("download_token does not match format")
