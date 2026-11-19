# Storage architecture

Binderdash stores data in three locations: a server-side database, browser IndexedDB, and the server filesystem. Use this reference when planning backups, multi-user deployments, or container rebuilds. For backup procedures, see [Backup and restore](../admin/backup-restore.md).

## 1. Server-side database (SQLite by default)

The `DATABASE` environment variable (see `AGENTS.md`, resolved in `backend/persistence/factory.py`) selects the database backend. When `DATABASE` is unset, Binderdash uses `NoopDesignsRepository`, disables database persistence (which also disables per-user API keys), and serves data from the in-memory cache populated by startup filesystem scans.

With `DATABASE=sqlite:///path/to/file` (or the default `backend/data/binderdash.sqlite`), `backend/persistence/sqlite_repo.py` creates these tables:

| Table | Contents |
|---|---|
| `binderdash_runs` | Run-level metadata: method, run name, project ID, resolved run path, `ingested_at`, and a `run_json` blob. |
| `binderdash_designs` | Per-design records with indexed columns (`run_id`, `design_id`, `tag`, `good`, `binder_chain`, `short_name`), a `data_json` blob for method-specific score columns, and `extra_data` for user-added fields. Startup reads this table into the in-memory `designs_cache` (see `cache.py`). |
| `binderdash_users` | User accounts: email, display name, picture URL, `is_admin`, `is_active`, and first/last login timestamps. Non-null emails are unique and link logins across auth providers. |
| `binderdash_user_identities` | Auth identities per `(provider, identifier)` mapped to `binderdash_users`. Credentials are stored separately in `LOCAL_USERS` bcrypt hashes or delegated to PAM or Google OAuth. |
| `binderdash_api_keys` | Per-user API keys: name, key prefix, `key_hash`, and created/expires/revoked/last-used timestamps. Key names are unique among active keys for a given user. |
| `binderdash_auth_users` | Legacy login-audit table kept for backward compatibility. Startup migrations copy existing rows into `binderdash_users` and `binderdash_user_identities`. |
| `binderdash_tag_metrics_cache` | Cached tag-placement metrics (SASA-based tag-site scoring), keyed by run, design, structure file, and tag parameters to avoid recomputing repeated UI requests. |
| `binderdash_structural_metrics_cache` | Cached structural metrics from `backend/filtering/structural_metrics.py` (secondary structure, hydrophobic patch area, hbonds/saltbridges, delta SASA), keyed by run, design, structure file, and chain selection. |
| `binderdash_target_contacts_cache` | Cached per-design target contact records, keyed by run, design, structure file, chains, and a parameter hash (`params_key`). |
| `binderdash_target_residues` | Per-run target residue reference data and `target_moves` flag, keyed by run, `params_key`, and chains. |
| `binderdash_saved_sets` | Named Saved Sets created from the Filtering tab: id, name, creation timestamp, source run IDs, filter/ranking/diversity recipe (`filter_params` JSON), and `result_summary` JSON. Saved Sets are stored server-side, shared across all users of the server/database, and unaffected by clearing browser data. |
| `binderdash_saved_set_designs` | Designs belonging to each Saved Set at creation time: design/run/source-path identifiers, final rank, quality score, diversity-subset membership, and a metrics snapshot. Saved Sets are immutable after creation except for renaming (`PATCH /api/saved-sets/{id}`); clicking "reapply filters" in the UI creates a new set instead of editing the existing one. |

None of these tables store structure files (PDB/CIF) or raw run output. They store only metadata, computed metrics, and filesystem paths pointing to the server files in §3.

SQLite is the only implemented backend. Setting `DATABASE` to any non-`sqlite` scheme (including `postgres` or `postgresql`) causes startup to fail with a `RuntimeError` instead of falling back to `NoopDesignsRepository`. To run without persistence, leave `DATABASE` unset.

## 2. Browser storage (per-user, per-browser, client-side only)

Binderdash does not use `localStorage`. Client-side UI state is stored in IndexedDB via `frontend/src/persistence/` (`db.ts`, `store.ts`, `keys.ts`, `hydrate.ts`), using a single database (`binderdash-app`, object store `kv`) with namespaced keys defined in `PERSISTENCE_KEYS` (`keys.ts`):

| Key | Contents |
|---|---|
| `binderdash:designs-view-state-v1` | DesignsView table state: selections, column visibility/order, sort, tag placements. |
| `binderdash:plots-scatter-axes-v1` | Persisted X/Y axis choices per method for the Plots tab. |
| `binderdash:filtering-view-state-v1` | Filtering tab working state: hard filters, ranking metrics, alpha/budget, and diversity toggle state. This is unsaved in-progress state, separate from server-side Saved Sets. |
| `binderdash:seq-prep-state-v1` | Sequence Preparation tab UI state. |
| `binderdash-viewer-controls-pos` | Mol* viewer floating-controls panel position. |
| `binderdash-adv-ref-ui-global` | Advanced reference/overlay UI toggles (global). |
| `binderdash-adv-ref:<runId>` | Per-run advanced-reference overlay state. |
| `binderdash-tag-placement:<runId>` | Per-run tag placement UI state (independent of the DB-cached tag metrics in §1). |
| `binderdash-target-contact-map:<runId>` | Per-run target contact map UI state. |
| `binderdash:folders-ui-v1` | Folder Browser UI state (expanded folders, selection). |

IndexedDB data is scoped to a single browser profile on one machine. It is not shared across users or devices, is removed by "clear site data", and is independent of server-side persistence. Session authentication uses a separate signed cookie (`SessionMiddleware` in `backend/main.py`, signed with `SECRET_KEY`), not IndexedDB or `localStorage`.

## 3. Server filesystem

Binderdash uses two locations on the server filesystem:

- Run output directories (`RUN_BASE_DIRS` or ad hoc folders opened via the Folder Browser): original pipeline outputs including results tables and structure files. Binderdash opens these read-only: `run_discovery.py` scans them and `backend/routers/files.py` serves structure files on demand. Because the database stores only `run_path` and `source_path` references, moving or deleting a run folder causes structure-file downloads and Mol* viewing to fail even while the design rows remain in the database and cache.
- SQLite database file: stored at `backend/data/binderdash.sqlite` by default (see `default_sqlite_url()` in `backend/persistence/factory.py`). Under `docker-compose.yml`, `./data` on the host is mounted at `/app/data` so database state persists across container rebuilds.

## 4. Download bundles

Design bundle zips combine data from all three locations into a single archive without introducing a fourth storage backend: they include the run files (§3), cached metrics (§1), and a JSON snapshot of the browser UI state (§2) so a downloaded set can be inspected or restored later. See [Download bundles](download-bundles.md).

Saved Sets also store the active UI state inside their `filter_params` JSON column at creation time, so downloading a set later reproduces both the filter recipe and the table layout. Saved Sets created before this change do not include that field, and the exported bundle marks it as missing.

## Storage persistence summary

- Server-side storage of Saved Sets: Saved Sets are stored in the `binderdash_saved_sets` and `binderdash_saved_set_designs` SQLite tables. They are shared across all users connected to the same server and database file, independent of browser IndexedDB state.
- Clearing browser storage: removes only local UI preferences (table column layout, unsaved filter builder state, viewer panel positions, and tag placement scratch state). Run data, computed metrics, and Saved Sets remain intact.
- Deleting the SQLite file: removes ingested run and design rows and cached tag, structural, and target-contact metrics (which can be recomputed from disk), along with data that cannot be rebuilt from pipeline outputs on disk: Saved Sets, user accounts and identities, per-user API keys, login history, and user-added design fields (`good`, `tag`, `short_name`, `extra_data`). The original run output directories on the filesystem are not modified.
