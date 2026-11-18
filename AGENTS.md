# AGENTS.md

## Project overview

- Single-page app to view results of de novo protein binder design runs
- Frontend: Vite + Typescript + Vue 3 (Composition API) + PrimeVue, Mol* viewer, Vega-Lite plots
- Backend: FastAPI (async) serving API and built frontend static files
- **Pipeline config** (method IDs, run folder signatures, score columns, plot defaults, path heuristics, structure-file rules, score column names matching source files): `backend/config/` (`run_signatures.py`, `plot_defaults.py`, `method_paths.py`, `score_labels.py`). Import `backend.config` or submodules; `run_discovery` still imports `run_folder_signatures` from there.

## Setup commands

- ALWAYS ensure any existing conda environment is deactivated before running any commands: `conda deactivate; conda deactivate`
- Backend (Python 3.11+, uv):
  - Create venv: `uv venv -p python3.12 .venv && source .venv/bin/activate`
  - Update dependencies if required, modify `backend/pyproject.toml` then run `uv pip compile backend/pyproject.toml -o backend/requirements.txt`
  - Install deps: `uv pip install -r backend/requirements.txt`
  - MCP server (`/api/mcp/`): **on by default in Docker** (`backend/Dockerfile` compiles with `--extra mcp`; an existing stack needs `docker compose up -d --build` once). In a local venv, opt in with `uv pip install "fastmcp>=3.4,<4"`. Deliberately absent from `backend/requirements.txt` because the PyInstaller desktop build installs from that file and its spec does not declare fastmcp's ~30 transitive backends — do not add it there. Without it the endpoint is simply not mounted. See [`docs/development/mcp.md`](docs/development/mcp.md).
  - Dev/test deps: `uv pip compile backend/pyproject.toml --extra dev -o backend/requirements-dev.txt && uv pip install -r backend/requirements-dev.txt` (includes runtime deps plus `pytest` and `pytest-timeout`)
  - Start API dev server: `uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
- Frontend (pnpm, Vite, PrimeVue):
  - `cd frontend && pnpm install`
  - Dev server: `pnpm run dev`
  - Watch mode (auto-rebuild): `pnpm run watch:build`
- Build frontend for backend to serve:
  - `pnpm run build` (output configured to backend static dir)
- Containerised (optional):
  - `docker compose up --build`
- Desktop (pywebview + PyInstaller):
  - Build frontend first: `cd frontend && pnpm run build`
  - Dev launcher: `uv pip install pywebview && uv run python -m desktop.main`
  - Linux AppImage: `bash desktop/packaging/build-linux-appimage.sh`
  - macOS zip: `bash desktop/packaging/build-macos.sh`
  - Windows zip: `powershell -File desktop/packaging/build-windows.ps1`
  - See [`desktop/README.md`](desktop/README.md)

## Environment configuration

- Use `.env` (create from `.env.example`) and ensure `.env` is in `.gitignore`
- Expected variables:
  - `RUN_BASE_DIRS="/data/runs,/data2/runs"` (comma-separated list of base directories)
  - `DISABLE_AUTHENTICATION="true|false"`
  - `BINDERDASH_ADMIN_USERS` (optional; comma-separated; matches a user's email, `provider:identifier`, or bare username; re-applied at every startup and login, so this file is authoritative; no `*` wildcard)
  - `PAM_GECOS_EMAIL` (optional, default false; read a PAM user's email from the **5th GECOS field only** so their PAM and Google logins share one account. Field 5 is used because `chfn` cannot write it — the earlier fields are user-editable under the usual `CHFN_RESTRICT="rwh"`, so trusting them would allow account takeover. Set with `sudo usermod -c "user,,,,addr@example.org" user`.)
  - API keys are **per-user** — named, expiring, revocable — created in the UI account menu or via `python -m backend.cli key create <user> --name <name>`, and sent as `Authorization: Bearer <key>` or `X-Binderdash-Api-Key`. They require `DATABASE`. (The old single shared `BINDERDASH_API_KEY` was **removed**; a leftover line in `.env` is ignored, not fatal.)
  - `LOCAL_USERS="user1:$2b$...,user2:$2b$..."` (optional; bcrypt hashes; enabled when non-empty)
  - `PAM_LOCAL_ENABLED` / `PAM_LOCAL_ALLOWED_USERS` / `PAM_LOCAL_SERVICE` (optional; PAM after `LOCAL_USERS`; default service `common-auth`; Docker: either `LOCAL_USERS`, add users in the image, or optional bind-mounts of host `/etc/passwd` + `/etc/group` + `/etc/shadow` — commented in `docker-compose.yml`, security-sensitive)
  - **PAM in Docker** — mounting host `/etc/passwd`, `/etc/group`, `/etc/shadow` is necessary but *not sufficient*; two things make logins fail with a plain "Incorrect username or password":
    1. **`group_add: ["42"]`** (gid `shadow`) on the service. `pam_unix` shells out to `/sbin/unix_chkpwd`, which is setgid `shadow` but refuses to use that privilege for a user other than its caller — an anti-brute-force measure. A container running as `BINDERDASH_UID` (default 1000) makes a cross-user request for every other account, so the helper returns `PAM_AUTHINFO_UNAVAIL` (rc 9), which `pam_unix` reports as an ordinary auth failure. Diagnose with `printf %s pw | /sbin/unix_chkpwd <user> nullok; echo $?` as the app user (9 = cannot read shadow) versus as that user's own uid (7 = read fine, wrong password).
    2. **Recreate after any host account change.** These are single-*file* bind mounts, so they pin an inode, and `passwd(1)` replaces `/etc/shadow` rather than editing it. A running container keeps reading the pre-change file, so password changes and new users are silently invisible. `docker compose restart` does not help — `docker compose up -d --force-recreate` does. Compare `md5sum /etc/shadow` inside and outside the container to confirm.
  - `GOOGLE_AUTH_ENABLED`, `GOOGLE_AUTH_CLIENT_ID`, `GOOGLE_AUTH_CLIENT_SECRET`, `GOOGLE_AUTH_REDIRECT_URI`, `GOOGLE_AUTH_ALLOWED_USERS` (optional; Google OAuth; emails case-insensitive)
  - `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `DATABASE`, `CORS_ALLOWED_ORIGINS` as needed
 - `PUBLIC_BASE_URL` (optional; origin with no trailing slash for absolute MCP download URLs. When unset, `https://$DOMAIN` is used if `DOMAIN` is a real hostname, otherwise the incoming request host)
- When adding new env vars, update `.env.example` accordingly
- Do not delete `.env`, but ensure it is in `.gitignore`

## Frontend guidelines (Vite + Vue 3 + PrimeVue)

- Use `pnpm` for package management
- Composition API; component order: `<template>`, `<script>`, `<style>`

## Design style guide and principles

- Use default PrimeVue styling and components, unless otherwise specified
- Use checkboxes for row selection in DataTables, where row selection is required: https://primevue.org/datatable/#checkbox_row_selection

## Testing and quality

- Backend: `pytest` for unit/API tests
- Frontend: Playwright for end-to-end testing
  - Install root dependencies: `pnpm install` (first time only)
  - Run tests: `pnpm test` (installs browsers and runs full suite)
  - Individual commands: `pnpm test:playwright`, `pnpm test:ui`, `pnpm test:headed`, `pnpm test:debug`
  - Test configuration: `playwright.config.js` with automatic server startup
  - Test documentation: `tests/README.md` with comprehensive workflow testing
  - Helper script: `run-tests.js` for automated test execution

## Code style

- Do not write extraneous comments in the code; comment where code deviates from typical patterns or is particularly complex / cryptic. Don't comment on lines that would be self-explanatory to a junior developer.
- Python: type hints, guard clauses, meaningful names, log to stderr; import order: stdlib → common externals → other externals → internal
- Vue: Composition API, minimal comments, Australian English spelling in comments
- Secrets: never hardcode; always use environment variables

## PR checklist

- Run backend tests (`pytest`) and linters
- Run frontend build  (`pnpm run build`) and linters
- Run Playwright tests: `pnpm test` (from project root)
- Update `.env.example` when env vars change
- Update documentation in `docs/`
- Update `CHANGELOG.md` for notable features and fixes (see format below)

## CHANGELOG.md

Follow [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Under each version heading (`## [Unreleased]` or `## [X.Y.Z] - YYYY-MM-DD`), use category subsections in this order:

- `### Added` — new features
- `### Changed` — changes in existing functionality
- `### Deprecated` — soon-to-be removed features
- `### Removed` — now removed features
- `### Fixed` — bug fixes
- `### Security` — vulnerabilities

Omit empty categories. Do **not** put `**Added**` / `**Changed**` / etc. at the start of bullet points — that belongs in the `###` heading.

Each bullet starts with a bold area prefix, then a colon and the change:

```markdown
### Added

- **Filtering**: Ranking has two modes. **Simple ranking** (the UI default) …
- **Auth / API**: **Per-user API keys** — named, expiring, revocable …
```

Prefer that prefix over topic subsections (`### Filtering`, `#### Docker Containerization`). If a topic spans categories, split its bullets across the matching `###` sections rather than inventing a nested heading.

For `[Unreleased]`, document the net state relative to the last release — consolidate overlapping entries, and drop or fold intermediate changes that later unreleased work superseded. Mark breaking behaviour with **BREAKING** in the bullet (or heading) when users must act.

## Releasing

Bump the version in **all four** project manifests (keep them in sync):

| File | Role |
|------|------|
| [`package.json`](package.json) | Root package (Playwright test runner) |
| [`frontend/package.json`](frontend/package.json) | Frontend npm package |
| [`backend/pyproject.toml`](backend/pyproject.toml) | **Canonical** app version — desktop packaging scripts, `GET /api/desktop/info`, and PyInstaller artifact names read this |
| [`desktop/pyproject.toml`](desktop/pyproject.toml) | Desktop packaging dependencies metadata |

Also update before tagging:

- [`CHANGELOG.md`](CHANGELOG.md) — consolidate `[Unreleased]` to the net state since the last release, then move those entries into a dated section (e.g. `## [0.3.0] - YYYY-MM-DD`); keep the empty `## [Unreleased]` heading at the top
- **Git tag** — `vX.Y.Z` must match `backend/pyproject.toml` (e.g. `v0.3.0` for version `0.3.0`). Pushing a `v*` tag triggers [`.github/workflows/desktop-release.yml`](.github/workflows/desktop-release.yml) to build and publish Linux AppImage, macOS zip, and Windows zip.

Check that documentation is up to date in `docs/`.

Optional doc touch-ups (examples only): [`desktop/README.md`](desktop/README.md).

**Not** app version strings (do not bump for releases): `frontend/src/persistence/db.ts` (`DB_VERSION` is IndexedDB schema version); dependency versions in lockfiles.

Pre-tag checklist:

1. All four manifests at the same version; tag matches `backend/pyproject.toml`
2. `CHANGELOG.md` finalised for the release
3. `pytest` (backend), `pnpm run build` (frontend), `pnpm test` (Playwright)
4. Rebuild frontend before desktop/PyInstaller builds (`cd frontend && pnpm run build`)
5. Build and smoke-test the desktop app **before pushing the `v*` tag** (the tag publishes the release artifacts). Minimum: Linux AppImage via `bash desktop/packaging/build-linux-appimage.sh`, then launch it and confirm the backend starts — `http://127.0.0.1:8765/health` returns 200 and the window opens, rather than the startup-error dialog. macOS and Windows zips are built by CI on the tag; check those when a change is platform-specific.
