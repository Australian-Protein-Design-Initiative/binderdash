import logging
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .auth import CSRF_COOKIE_NAME, request_has_valid_api_key, request_is_authenticated
from .mcp_server import MCP_MOUNT_PATH, build_mcp_http_app
from .routers import api_keys as api_keys_routes
from .routers import bundles as bundles_routes
from .routers import auth as auth_routes
from .routers import designs as designs_routes
from .routers import files as files_routes
from .routers import filtering as filtering_routes
from .routers import plots as plots_routes
from .routers import runs as runs_routes
from .routers import saved_sets as saved_sets_routes
from .routers import desktop as desktop_routes
from .routers import sequences as sequences_routes
from .persistence.factory import default_sqlite_url, init_designs_repository_from_url
from .runtime_paths import static_root
from .settings import CORS_ALLOWED_ORIGINS, SECRET_KEY, raw_settings, settings
from .version import build_label, build_payload


_root_level = getattr(logging, settings.log_level, logging.INFO)
logging.basicConfig(
    level=_root_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger().setLevel(_root_level)
logger = logging.getLogger(__name__)

_STATIC_ROOT = static_root()
_STATIC_ASSETS = _STATIC_ROOT / "assets"


_MCP_APP = build_mcp_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = (raw_settings.database or "").strip() or default_sqlite_url()
    init_designs_repository_from_url(db_url)
    from .cache import hydrate_caches_from_repository

    hydrate_caches_from_repository()
    _sync_admin_flags()
    async with AsyncExitStack() as stack:
        if _MCP_APP is not None:
            # Mounting does not start the streamable-HTTP session manager -- that
            # happens in the sub-app's own lifespan, which Starlette does not run for
            # mounted apps. Skip this and every tool call fails at runtime with "Task
            # group is not initialized", never at import and never in a smoke test that
            # only checks for a 401. AsyncExitStack keeps the single yield an
            # asynccontextmanager requires and unwinds on the task that entered, which
            # the anyio cancel scopes inside the session manager demand.
            inner = _MCP_APP.app  # unwrap the header shim
            await stack.enter_async_context(inner.router.lifespan_context(inner))
            _warn_if_mcp_unusable()
        yield
    from .api_keys import flush_last_used

    flush_last_used()


def _warn_if_mcp_unusable() -> None:
    """Auth on but no key store means every MCP request 401s, indistinguishably.

    Only meaningful once the repository is initialised, hence inside the lifespan.
    """
    from .api_keys import api_keys_available

    if not settings.auth_disabled and not api_keys_available():
        logger.warning(
            "MCP is mounted at %s but API keys are unavailable (no DATABASE); every "
            "request will be rejected with 401",
            MCP_MOUNT_PATH,
        )


def _sync_admin_flags() -> None:
    """Re-apply BINDERDASH_ADMIN_USERS to every stored user at startup.

    Login-time sync alone is not enough: a demoted admin who never logs in
    again would keep admin rights on their API keys indefinitely. The allowlist
    is read from the environment at import time, so it can only change across a
    restart -- which makes "sync on boot + sync on login" complete.
    """
    try:
        from .persistence.factory import get_designs_repository

        repo = get_designs_repository()
        if not repo.is_enabled():
            return
        admin_ids: list[int] = []
        for user in repo.list_users():
            uid = user.get("id")
            if uid is None:
                continue
            identities = repo.list_user_identities(int(uid))
            if any(
                settings.is_admin_identity(
                    i.get("provider") or "", i.get("identifier") or "", user.get("email")
                )
                for i in identities
            ):
                admin_ids.append(int(uid))
        changed = repo.sync_admin_flags(admin_ids)
        if changed:
            logger.info("Admin flags synced from BINDERDASH_ADMIN_USERS: %d changed", changed)
    except Exception:
        logger.exception("Admin flag sync failed")


_OPENAPI_URL = "/openapi.json"

# The schema, Swagger UI and ReDoc routes are served by hand below (hence the three
# Nones) so the reported version can depend on who is asking. "unversioned" is what
# anonymous callers see; a signed-in caller gets the real build label.
app = FastAPI(
    lifespan=lifespan,
    version="unversioned",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=False,
)


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if request.method in ["GET", "HEAD", "OPTIONS"]:
        return await call_next(request)
    if request.url.path in [
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/status",
        "/api/auth/google/login",
        "/api/auth/google/callback",
    ]:
        return await call_next(request)
    path = request.url.path
    if path == MCP_MOUNT_PATH or path.startswith(MCP_MOUNT_PATH + "/"):
        # The MCP sub-app authenticates with a bearer token and never reads a cookie,
        # so there is no ambient credential for a hostile page to abuse -- CSRF has
        # nothing to defend here. Leaving it on would answer a missing or revoked key
        # with a text/plain 403 "CSRF token missing" that no MCP client can parse,
        # instead of the protocol's 401 with WWW-Authenticate. Exact-or-slash, not a
        # bare startswith, so a future /api/mcp-admin is not silently exempted too.
        return await call_next(request)
    if settings.auth_disabled:
        return await call_next(request)
    if request_has_valid_api_key(request):
        return await call_next(request)
    csrf_token = request.headers.get("X-CSRF-Token")
    if not csrf_token:
        return Response(
            content="CSRF token missing",
            status_code=403,
            headers={"Content-Type": "text/plain"},
        )
    cookie_csrf_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_csrf_token or csrf_token != cookie_csrf_token:
        return Response(
            content="CSRF token mismatch",
            status_code=403,
            headers={"Content-Type": "text/plain"},
        )
    return await call_next(request)


if _STATIC_ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_STATIC_ASSETS)), name="assets")
else:
    logger.warning(
        "Static assets directory missing at %s — run `pnpm run build` in frontend/ "
        "(or build the image with BUILD_FRONTEND=true).",
        _STATIC_ASSETS,
    )

if _STATIC_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_ROOT)), name="static")
else:
    logger.warning(
        "Static directory missing at %s — run `pnpm run build` in frontend/.",
        _STATIC_ROOT,
    )


@app.get("/health")
async def health_check(request: Request):
    # Liveness is public; the build identity it would otherwise hand to any scanner
    # on the internet is not. Signed-in callers (and auth-disabled installs) get both.
    payload: dict[str, object] = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if await request_is_authenticated(request):
        payload["build"] = build_payload()
    return payload


@app.get(_OPENAPI_URL, include_in_schema=False)
async def openapi_schema(request: Request):
    schema = app.openapi()  # cached on the app after the first call
    if not await request_is_authenticated(request):
        return schema
    return {**schema, "info": {**schema["info"], "version": build_label()}}


@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    return get_swagger_ui_html(openapi_url=_OPENAPI_URL, title="Binderdash API")


@app.get("/redoc", include_in_schema=False)
async def redoc_ui():
    return get_redoc_html(openapi_url=_OPENAPI_URL, title="Binderdash API")


@app.get("/favicon.ico")
async def get_favicon():
    path = _STATIC_ROOT / "favicon.ico"
    if not path.is_file():
        return Response(status_code=404)
    return FileResponse(str(path))


@app.get("/")
async def serve_frontend():
    path = _STATIC_ROOT / "index.html"
    if not path.is_file():
        return Response(
            content=(
                "Frontend bundle not found. Build the SPA (e.g. `cd frontend && pnpm run build`) "
                f"so files exist under {_STATIC_ROOT}."
            ),
            media_type="text/plain",
            status_code=503,
        )
    return FileResponse(str(path))


app.include_router(auth_routes.router)
app.include_router(api_keys_routes.router)
app.include_router(runs_routes.router)
app.include_router(designs_routes.router)
app.include_router(files_routes.router)
app.include_router(files_routes.pdbs_router)
app.include_router(files_routes.tree_router)
app.include_router(plots_routes.router)
app.include_router(sequences_routes.router)
app.include_router(filtering_routes.router)
app.include_router(saved_sets_routes.router)
app.include_router(bundles_routes.router)
if settings.binderdash_desktop:
    app.include_router(desktop_routes.router)

if _MCP_APP is not None:
    # Endpoint is /api/mcp/ (trailing slash); POST /api/mcp 307-redirects to it.
    app.mount(MCP_MOUNT_PATH, _MCP_APP, name="mcp")
    logger.info("MCP server mounted at %s/", MCP_MOUNT_PATH)
