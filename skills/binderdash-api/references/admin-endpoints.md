# Admin / seldom-used endpoints

**Do NOT read this file** unless the user explicitly asks about run ingestion, rescanning folders, or the SPA's Vega-Lite chart endpoints.

## Ingestion endpoints

Used by the SPA's "Add Runs" workflow. The data is typically already ingested when you interact with Binderdash as an agent.

- `POST /api/runs/scan` - given `{folders: [...], force_rescan_of_ingested?: bool}`, walk each folder under the server's allowed `RUN_BASE_DIRS`, detect run signatures, and return any unsaved runs.
- `POST /api/runs/ingest-preview` - for the runs in the body, list which already exist in the DB (re-ingest will reset `tag`/`good`).
- `POST /api/runs/ingest` - persist the runs returned by `/scan` to the SQLite/Postgres store (requires `DATABASE` configured server-side). Only `path` / `merged_paths` are read from each run; the server re-detects the run on disk, and folders outside `RUN_BASE_DIRS` are rejected with 400.
- `DELETE /api/runs/{run_id}` and `DELETE /api/runs` - remove one run or clear everything.
- `GET /api/tree?path=...` - file-tree browser limited to `RUN_BASE_DIRS`. Used by the SPA when picking folders to scan.
- `GET /api/runs/{run_id}/input-targets` - list "input target" structure files (e.g. the target PDB the binder was designed against), keyed by id; pair with `mode=input_target` on `/files/reference`.

## Plotting endpoints

The `/api/runs/plots/columns`, `/api/runs/plots/scatter`, and `/api/runs/plots/histogram` endpoints exist to drive Vega-Lite charts in the SPA. For an agent there is no reason to use them — once you have the design table from `/api/designs` (or the per-run `/api/runs/{run_id}/table`), do plotting in Python (`pandas` + `matplotlib`/`seaborn`/`altair`) or R (`ggplot2`). All numeric columns are already in the response and the backend's "scatter" endpoint does no computation beyond NaN/Inf cleaning.
