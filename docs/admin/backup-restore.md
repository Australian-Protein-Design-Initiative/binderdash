# Backup and restore

Binderdash stores server state in a SQLite database, your run output directories, and configuration files. For full details on each storage location, see [Storage architecture](../development/storage.md).

## Files to back up

| Component | Docker Compose path | Non-Docker server path | Back up |
|---|---|---|---|
| SQLite database | `./data/binderdash.sqlite` on the host (`/app/data` in the container) | The path in `DATABASE`, or `backend/data/binderdash.sqlite` if `DATABASE` is unset | **Yes, essential** |
| Run output directories | The host directories mounted into the container and listed in `RUN_BASE_DIRS` | The directories in `RUN_BASE_DIRS` | **Yes**, if not already covered by your storage backups |
| `.env` | `./.env` | `./.env` | **Yes** (contains secrets, store it securely) |
| `docker-compose.yml`, `Caddyfile` | Repository root | - | Yes, if you have edited them |
| Caddy TLS certificates | `caddy_data` Docker volume | - | Optional |

Other server files do not need backups: bundle downloads are created in a temporary spool directory and deleted after transfer, and the built frontend is packaged in the container image.

### Database

Some data exists only in the database and cannot be reconstructed from run folders:

- Saved Sets and their frozen design lists.
- Per-design annotations made in the UI or via the API/MCP (`tag` and `good` flags, short names, edited sequences and binder chains, and columns merged from extra TSV/CSV files).
- Users, login identities, and API keys (keys are stored as SHA-256 hashes, so clients must create new keys if this table is lost).

The database also stores ingested run and design rows along with cached metrics (tag placement, structural metrics, and target contacts). You can rebuild those tables by re-scanning and re-ingesting the runs, though recomputing metrics is slow on large installations and does not recover the annotations above.

The backup contains user email addresses, so store it with the same access controls as `.env`.

### Run output directories

Binderdash opens run folders read-only and does not modify them. Because these directories are usually large and managed by your pipeline storage, they may already have separate backups. When restoring them:

- Restore runs to their original paths. The database records absolute paths into these directories; if the paths change, design rows remain visible, but Mol* viewing and structure downloads fail.
- Restore the directories (and their Docker volume mounts) before starting Binderdash. Run files are served only from inside `RUN_BASE_DIRS`, and startup fails if any `RUN_BASE_DIRS` directory is missing.

### `.env`

`.env` defines `SECRET_KEY`, `LOCAL_USERS` password hashes, the Google OAuth client secret, `BINDERDASH_ADMIN_USERS`, `DATABASE`, and `RUN_BASE_DIRS`. If `SECRET_KEY` changes, active browser sessions and outstanding download links become invalid and users must log in again. Stored data and API keys are unaffected.

When `SECRET_KEY` is unset, Binderdash generates a random key on startup, invalidating existing sessions on restart. Set `SECRET_KEY` explicitly in production.

### Caddy certificates

The `caddy_data` volume stores the TLS certificates obtained by Caddy. Backing it up is optional because Caddy requests new certificates automatically if the volume is missing, though keeping the volume avoids certificate authority rate limits during repeated rebuilds.

### Desktop app

The desktop app stores its database, settings (`desktop.json`), and log in a per-user directory:

- Linux: `~/.local/share/binderdash/` (or `$XDG_DATA_HOME/binderdash/`)
- macOS: `~/Library/Application Support/Binderdash/`
- Windows: `%LOCALAPPDATA%\Binderdash\`

Back up `binderdash.sqlite` (plus `-wal` if present, see below) and `desktop.json`.

### Browser-local state

Table layouts, column choices, unsaved filter settings, and similar UI state are stored in each user's browser (IndexedDB). Server backups do not include this state, and restoring a server does not affect it.

## Taking a database backup

SQLite runs in WAL mode, so recent writes may still be in `binderdash.sqlite-wal` instead of the main database file. **Do not copy `binderdash.sqlite` directly while the server is running**: the copy can miss recent writes or become inconsistent.

### Online backup (service running)

SQLite's online backup API writes a consistent snapshot without stopping Binderdash. The container image does not include the `sqlite3` CLI, so use Python's `sqlite3` module:

```bash
docker compose exec binderdash python -c \
  "import sqlite3,sys; sqlite3.connect(sys.argv[1]).backup(sqlite3.connect(sys.argv[2]))" \
  /app/data/binderdash.sqlite /app/data/binderdash-backup.sqlite
```

This writes `./data/binderdash-backup.sqlite` on the host. Move it out of `./data` to your off-host backup storage.

If you run Binderdash directly on a host, or have the `sqlite3` CLI installed on the Docker host:

```bash
sqlite3 data/binderdash.sqlite ".backup /path/to/backups/binderdash-$(date +%F).sqlite"
```

Both commands are safe to schedule with cron.

### Offline backup (service stopped)

Stop the service (`docker compose stop binderdash`), then copy `binderdash.sqlite` and, if present, `binderdash.sqlite-wal`. You do not need to copy the `-shm` file.

### Verifying a backup

```bash
python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('PRAGMA integrity_check').fetchone()[0])" \
  binderdash-backup.sqlite
```

This prints `ok` when the database passes SQLite's integrity check.

## Restoring

1. Stop the service with `docker compose stop binderdash` (or stop the server process).
2. If `.env` or the run directories were lost, restore them to their original paths.
3. **Delete any leftover `-wal` and `-shm` files** before replacing the database file. Applying a stale WAL file from the previous database to a restored snapshot can corrupt the database.

    ```bash
    rm -f data/binderdash.sqlite-wal data/binderdash.sqlite-shm
    cp /path/to/backups/binderdash-2026-11-20.sqlite data/binderdash.sqlite
    ```

4. Check file ownership: under Docker Compose, `BINDERDASH_UID:BINDERDASH_GID` must have write permission (see [Docker deployment](../setup/docker.md#container-user)).
5. Start the service with `docker compose start binderdash`.

At startup, Binderdash loads all runs and designs from the database into memory, making restored data immediately available. Backups from older Binderdash versions are upgraded automatically on startup (see [Database migrations](database-migrations.md)). Restoring a backup from a **newer** Binderdash version onto an older version is not supported.
