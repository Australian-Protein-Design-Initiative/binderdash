# Database migrations

## Summary

- Schema migrations run **automatically** whenever Binderdash opens the database, including server startup and `python -m backend.cli` commands.
- Migrations are strictly additive (new tables, new columns, or rows backfilled from older tables); no migration drops or renames tables or columns.
- Downgrades are not supported. To roll back an upgrade, restore your pre-upgrade backup.

## Migration mechanism

Binderdash does not use a migration framework or a schema version number. When `create_repository()` in `backend/persistence/factory.py` creates the SQLite repository, it calls `init_schema()` in `backend/persistence/sqlite_repo.py`, which:

1. Creates missing tables and indexes with `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`. New tables in a release are added here.
2. Calls each `_migrate_*` method in order, inspecting the current schema (`PRAGMA table_info`, `sqlite_master`) and applying changes only when missing:
    - `_migrate_binder_chain_column`, `_migrate_short_name_column`, `_migrate_extra_data_column`: add columns to `binderdash_designs`.
    - `_migrate_run_path_column`, `_migrate_ingested_at_column`: add columns to `binderdash_runs`.
    - `_migrate_auth_users_to_user_model`: copies logins from the legacy `binderdash_auth_users` table into `binderdash_users` and `binderdash_user_identities`, leaving existing identities untouched and keeping the legacy table in place.

Each step is idempotent: up-to-date databases are unchanged, and an interrupted startup completes the remaining steps on the next launch. Migrations do not emit log output.

Only the `sqlite` scheme is supported in `DATABASE` (Postgres is not implemented). Configuring any other scheme causes startup to fail with an error.

## Upgrading a server

1. Take a backup (see [Backup and restore](backup-restore.md#taking-a-database-backup)).
2. Update the code and rebuild:

    ```bash
    git pull
    docker compose build --build-arg GIT_COMMIT=$(git rev-parse --short=12 HEAD)
    ```

3. Restart with `docker compose up -d`. The new container upgrades the schema on startup.
4. Check `docker compose logs binderdash` for errors and confirm `/health` responds.

To roll back, stop the service, check out and rebuild the previous version, and restore your pre-upgrade backup. Running older code with a newer schema is untested.

## Running migrations manually

Normal upgrades do not require manual steps. You can trigger migrations before starting the web server, for example to verify an upgrade on a copy of a production database.

CLI commands open the database through the same `DATABASE` resolution and `init_schema()` path as the server, so a read-only command such as `user list` applies pending migrations and exits:

```bash
# Non-Docker server, from the repository root with the venv active
python -m backend.cli user list

# Docker Compose, using the newly built image and the same ./data volume
docker compose run --rm binderdash python -m backend.cli user list
```

To test on a database copy instead of the live file, override `DATABASE` for the command:

```bash
DATABASE="sqlite:////tmp/binderdash-copy.sqlite" python -m backend.cli user list
```

## Adding a migration (developers)

- Add a `_migrate_*` method to `SqliteDesignsRepository` and call it from `init_schema()` after the existing migration calls.
- Check the current schema first and return early if the change is already present, since `init_schema()` runs at startup.
- Keep migrations additive: do not drop or rename tables or columns, because installations may restore older backups and upgrade from earlier schemas.
- For new tables, add a `CREATE TABLE IF NOT EXISTS` statement to the `executescript` block.
