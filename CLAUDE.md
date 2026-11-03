# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Binderdash is a single-page web app to explore results from de novo protein binder design runs (RFdiffusion, BindCraft, BoltzGen, RFdiffusion3, etc.). This file supplements `AGENTS.md` — read `AGENTS.md` for the authoritative setup, env-var, releasing, and code-style rules; it is not repeated here.

## Commands not obvious from AGENTS.md

- **Always deactivate conda first** and activate the repo venv before backend work: `conda deactivate; conda deactivate; source .venv/bin/activate`.
- Run a single backend test: `cd backend && pytest tests/test_dna_optimization.py -k some_name -x`. Tests live in `backend/tests/` (not the root `tests/`, which is Playwright E2E).
- Frontend fast inner loop for backend-served UI: `cd frontend && pnpm run watch:build` (rebuilds into `backend/static/`, so the FastAPI server at :8000 serves the latest UI). Use `pnpm run dev` (:5173) only when you don't need the built static path.
- `pnpm test` from the repo root runs the full Playwright suite and auto-starts servers per `playwright.config.js`.

## Cutting a release

The authoritative procedure is the **Releasing** section of `AGENTS.md`: the four manifests that must move together (`package.json`, `frontend/package.json`, `backend/pyproject.toml`, `desktop/pyproject.toml`), the `CHANGELOG.md` handling, the `vX.Y.Z` tag that must match `backend/pyproject.toml`, and the pre-tag checklist. Follow it, don't re-derive it.

Three things that section doesn't cover, all verified against the code:

- **Where the running app gets its version** (`backend/version.py`, `build_identity()`), in precedence order: `BINDERDASH_VERSION` env var → **`backend/_build_info.json`** → `backend/pyproject.toml` → `"0.0.0"`. Note the middle one: `desktop/packaging/build-common.sh` writes `backend/_build_info.json`, it's gitignored, and nothing deletes it. A checkout that ever built the desktop app reports that stale version and commit hash forever, in the UI footer, `/health` and the generated sequence prep script. **Delete `backend/_build_info.json` after a desktop build** if you want a dev tree to report its real version.
- `importlib.metadata` is tried before `pyproject.toml`, but `backend/uv.lock` declares the project `virtual`, so `binderdash-backend` is never installed and that lookup normally misses. If someone installs it, the dist-info version wins and will go stale.
- The version string in `backend/uv.lock` (`name = "binderdash-backend"`) does **not** track `backend/pyproject.toml` and has been stale since 0.1.0. Harmless for a virtual project; don't "fix" it as part of a release.

Build identity is only shown to authenticated callers (see `request_is_authenticated` in `backend/auth.py`): anonymous `/health` has no `build` key and `/openapi.json` reports `unversioned`. A release that appears not to have taken effect may just be an unauthenticated look at it.

## Architecture: the ingest → persist → cache → serve pipeline

The backend's central job is turning heterogeneous run-output folders on disk into a queryable, sortable design table. The data flow is:

1. **Scan** (`run_discovery.py`, `POST /api/runs/scan`) — walks `RUN_BASE_DIRS` (or user-selected folders), matching folders against **run signatures** to detect method, run name, project ID, and results-table location. Signatures are declarative and live in `backend/config/run_signatures.py`.
2. **Ingest** (`POST /api/runs/ingest`) — parses each run's results tables (TSV/CSV) plus structure files into flat per-design dicts, then writes them via the **persistence repository**.
3. **Persist** (`backend/persistence/`) — a swappable `DesignsRepository` Protocol (`protocol.py`); the SQLite implementation (`sqlite_repo.py`) is default, a `noop_repo.py` exists for the no-DB case. Selected by `DATABASE` env var via `factory.py`. Design dicts are split into indexed DB columns plus a `data_json` blob for method-specific columns.
4. **Cache** (`cache.py`) — on startup, `hydrate_caches_from_repository()` loads all designs into in-memory `run_cache`, `designs_cache`, and `designs_by_run_id`. **The API serves reads from these in-memory caches, not the DB directly.** After mutations, refresh the cache (`POST /api/designs/refresh-cache`).
5. **Serve** (`backend/routers/`) — `designs.py`, `runs.py`, `plots.py`, `files.py`, `sequences.py`, `auth.py`, `desktop.py`, each mounted in `main.py`.

**Key consequence:** designs are *flat dicts whose columns depend on the method*. There is no fixed schema. Sorting and "primary score" selection are driven by per-method config, not hardcoded columns.

## Config is data, not code (`backend/config/`)

Method-specific behaviour is centralised as declarative tables. When adding/adjusting pipeline support, edit these rather than scattering conditionals:

- `run_signatures.py` — folder-detection signatures: `method`, `submethod`, `priority`, results-table location, `primary_score_columns`, `sort_ascending`. **The first (lowest-priority-number) signature per method also defines its primary sort score** (see `cache._method_score_config`).
- `method_paths.py` — method IDs, project/run path heuristics, params keys, structure-file basename rules.
- `plot_defaults.py` — default scatter X/Y columns per method.
- `score_labels.py` — human labels for metric columns (`Average_i_pTM`, `pae_interaction`, `iptm`, `rf3_ipsae_min`, …); the raw keys match source TSV/CSV headers.

Import from `backend.config` or its submodules. Note `run_discovery` imports `run_folder_signatures` from `backend.config.run_signatures`.

## MCP server (`backend/mcp_server/`)

A stateless FastMCP server mounted at `/api/mcp/` in the same process, so tools call the
service layer in-process and share the design cache. Auth reuses the per-user `bd_` API
keys. **Optional** — gated on `fastmcp` being importable; every `fastmcp` import is
inside a function, so a build without the extra returns `None` from
`build_mcp_http_app()` and nothing mounts.

The package is `mcp_server`, **not** `mcp`: pytest puts `backend/` on `sys.path`, where a
package named `mcp` shadows the SDK fastmcp imports. Two things in `main.py` are
load-bearing and easy to break — the **CSRF exemption** for the mount path (else auth
failures surface as an unparseable `text/plain` 403) and **lifespan chaining** via
`AsyncExitStack` (else every tool call fails with "Task group is not initialized"). The
surface deliberately does not mirror REST; see `docs/development/mcp.md`.

## Auth model

Multiple auth backends coexist, resolved at request time (`backend/auth.py`, `backend/auth_providers/`): per-user API keys (`backend/api_keys.py`, via `Authorization: Bearer` or `X-Binderdash-Api-Key`), `LOCAL_USERS` (bcrypt), PAM, and Google OAuth — or fully disabled via `DISABLE_AUTHENTICATION`.

**Users and keys.** A *user* is a person (`binderdash_users`); an *identity* is one way they sign in (`binderdash_user_identities`, keyed `(provider, identifier)`). Identities collapse onto one user only when they assert the same **verified email** — local and PAM supply none, so they stay separate unless `PAM_GECOS_EMAIL` is enabled. Users are auto-created on first login; `is_admin` comes from the `BINDERDASH_ADMIN_USERS` allowlist and is re-synced at startup *and* login, so `.env` is authoritative. API keys are `bd_`-prefixed, stored as SHA-256 (never bcrypt — see the rationale in `backend/api_keys.py`), shown once, and validated through a TTL cache with a debounced `last_used_at` write. The `/api/api-keys` router is **session-cookie only**: an API key may not mint another key. Bootstrap with `python -m backend.cli`. Browser sessions use cookie sessions + **CSRF** (`X-CSRF-Token`); the CSRF middleware in `main.py` exempts GET/HEAD/OPTIONS, the login/logout/status/google routes, valid-API-key requests, and auth-disabled mode. API-key clients skip CSRF entirely. See `AUTHENTICATION.md`.

## Frontend architecture (`frontend/src/`)

- **State**: Pinia stores in `stores/` (`runs`, `designs`, `plots`, `folders`, `app`, `auth`, `seqPrep`).
- **Persistence**: user-facing state (selections, tag placements, merged CSV columns, axes) is persisted to **IndexedDB** via `persistence/` (`db.ts`, `store.ts`, `keys.ts`, `hydrate.ts`). `DB_VERSION` in `persistence/db.ts` is the IndexedDB schema version — **not** the app version; do not bump it for releases.
- **API client**: all backend calls go through `webapi.ts`.
- **Views**: `DesignsView.vue` (the sortable design table), `PlotsView.vue` (Vega-Lite), `MolstarViewer.vue` (Mol* 3D structures, with membrane/tag overlay helpers `membraneOverlay.ts`, `tagMarkerScreenOverlay.ts`, `molstarTerminalCa.ts`), `PrepareSequencesView.vue` (tag placement + DNA codon optimisation), `SelectRunsPanel.vue`, `FolderBrowser.vue`.

## Desktop app

The same FastAPI backend + built frontend ship as a `pywebview` desktop app (`desktop/`), packaged with PyInstaller into Linux AppImage / macOS zip / Windows zip. The **canonical app version is `backend/pyproject.toml`**; desktop packaging and `GET /api/desktop/info` read it, and the git tag `vX.Y.Z` must match it. See the Releasing section of `AGENTS.md` (four manifests must stay in sync) and `desktop/README.md`.

## Sequence prep specifics

`PrepareSequencesView.vue` + `backend/tag_placement.py` + `backend/seq_prep/` handle N-/C-terminal affinity tags (His/FLAG/HA/etc., G4S linkers) and DNA codon optimisation (DnaChisel, `backend/seq_prep/optimize.py` + `backend/util/codon_tables.py`) with GC/hairpin/restriction-site constraints. Tag-metric computation is lazy and cached. See `prepare_sequences_spec.md`.

`backend/seq_prep/` is the construct builder (tags, linkers, stops, padding, short names, exports) behind `POST /api/sequences/prepare`, the MCP `prepare_sequences` tool, and the downloadable Python script that `backend/seq_prep/script.py` generates by inlining this package's own source. **The same logic still exists in TypeScript** in `stores/seqPrep.ts`, `stores/shortName.ts` and `utils/protParam.ts`, which is what the live preview uses, so a change to tag presets, zone rules, short names or export columns must be made in both. `backend/tests/test_seq_prep_parity.py` is what catches it if you don't. Removing the TypeScript side is planned; see `plans/seq_prep_download_script.md`.
