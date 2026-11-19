# Development setup

Binderdash is a single-page app with two parts:

- Frontend: Vite + Vue 3 (Composition API) + PrimeVue, with the Mol\* structure viewer and Vega-Lite plots.
- Backend: FastAPI (async), serving the REST API and the built frontend as static files.

`AGENTS.md` in the repository root defines the code-style, environment-variable, and release rules.

## Prerequisites

- Python 3.11+ (tested with 3.12)
- [uv](https://github.com/astral-sh/uv) (Python package manager and runner)
- Node.js 18+ and [pnpm](https://pnpm.io/)
- Docker (optional, for the containerised workflow)

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI app; the frontend build is written to `backend/static/` |
| `backend/config/` | Per-pipeline detection and display rules (see [Adding a pipeline method type](pipeline-methods.md)) |
| `frontend/` | Vite + Vue SPA source |
| `desktop/` | pywebview + PyInstaller desktop packaging (see `desktop/README.md`) |
| `docs/` | This documentation (MkDocs) |
| `tests/` | Playwright end-to-end tests (backend unit tests are in `backend/tests/`) |
| `example_runs/` | Example run data (optional, not in git) |

## Environment configuration

Binderdash loads configuration from `.env` at the repository root. Copy `.env.example` as a starting point; it documents all supported variables. For local development, the defaults (authentication disabled, SQLite under `data/`, runs from `./example_runs`) are usually sufficient.

To create a local user account instead, set `DISABLE_AUTHENTICATION="false"` and add a bcrypt hash to `LOCAL_USERS`:

```bash
python backend/scripts/encrypt_password.py myusername  # prompts for the password
```

See [Authentication](../setup/authentication.md) for the other sign-in providers.

## Backend

Create a virtual environment and install dependencies:

```bash
uv venv -p python3.12 .venv && source .venv/bin/activate
uv pip install -r backend/requirements.txt
```

If a conda environment is active, deactivate it first so it does not shadow the venv.

Start the API server with auto-reload:

```bash
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The server listens on <http://localhost:8000>.

### Changing backend dependencies

After modifying `backend/pyproject.toml`, regenerate and install the pinned requirements:

```bash
uv pip compile backend/pyproject.toml -o backend/requirements.txt
uv pip install -r backend/requirements.txt
```

## Frontend

You can run the frontend in two modes.

To rebuild into `backend/static/` automatically (recommended while the backend is running so FastAPI on `:8000` serves the latest build):

```bash
cd frontend
pnpm install
pnpm run watch:build
```

To run the Vite dev server with hot reload on <http://localhost:5173> (proxying API calls to the backend):

```bash
cd frontend
pnpm install
pnpm run dev
```

For a one-off production build, run `pnpm run build` in `frontend/`.

## Docker development mode

`docker-compose.dev.yml` runs the backend with auto-reload and a separate container that rebuilds the frontend when Vue/TypeScript files change. The project directory is mounted from your filesystem.

Because the frontend container rebuilds `backend/static/` and the backend container updates `data/` inside the bind mount, run both containers under your host UID and GID. If your UID is not 1000, set `BINDERDASH_UID` and `BINDERDASH_GID` in `.env` first (see [Container user](../setup/docker.md#container-user)).

```bash
printf 'BINDERDASH_UID=%s\nBINDERDASH_GID=%s\n' "$(id -u)" "$(id -g)" >> .env
docker compose -f docker-compose.dev.yml up --build
# App: http://localhost:8001

docker compose -f docker-compose.dev.yml logs -f binderdash        # backend logs
docker compose -f docker-compose.dev.yml logs -f frontend-watcher  # frontend build logs

docker compose -f docker-compose.dev.yml down
```

Troubleshooting commands:

```bash
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml exec binderdash ls -la /app/backend/
docker compose -f docker-compose.dev.yml exec frontend-watcher ls -la /app/frontend/
```

Production deployment is covered in [Docker deployment](../setup/docker.md).

## Tests

Backend unit tests (pytest):

```bash
cd backend
pytest                                           # all tests
pytest tests/test_dna_optimization.py -k name -x  # a single test
```

End-to-end tests (Playwright), which start the servers defined in `playwright.config.js`:

```bash
pnpm test
```

See `tests/README.md` for details of the end-to-end workflow tests.

## Documentation

The docs are built with [MkDocs](https://www.mkdocs.org/) and versioned with [mike](https://github.com/jimporter/mike). To preview locally:

```bash
pip install -r requirements-docs.txt
mkdocs serve
```

The `docs` GitHub Actions workflow publishes to GitHub Pages on every push:

| Push to | Published as |
| --- | --- |
| `main` | `main`, aliased to `latest` (the default version) |
| `develop` | `develop` |
| a `vX.Y.Z` tag | `X.Y.Z` |

### README hero image

`docs/images/binderdash-hero.png` is composed from screenshots of a running instance. The scripts that produce it are in `docs/images/hero/`; see the header comment in `capture.js` for the steps.

## Contributing

- Python: type hints, standard import order, log to stderr.
- Vue: Composition API, with `.vue` sections ordered `<template>`, `<script>`, `<style>`.
- Add an entry to `CHANGELOG.md` for notable features and fixes.
- Releases: see the Releasing section of `AGENTS.md`. The app version in `backend/pyproject.toml` must match the `vX.Y.Z` tag.
