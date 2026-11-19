# MCP server

Binderdash exposes a [Model Context Protocol](https://modelcontextprotocol.io) server so an AI agent can analyse binder design campaigns directly: filtering and ranking designs, selecting diverse panels, inspecting interfaces, and saving curated Saved Sets for review in the web UI.

The server uses **stateless streamable-HTTP** and is mounted in the same FastAPI process as the REST API at **`/api/mcp/`** (note the trailing slash; `POST /api/mcp` returns a 307 redirect to it). Running in-process lets the MCP server share the REST API's in-memory design cache directly.

## Installing

Docker (dev and production compose) enables MCP by default. `backend/Dockerfile` compiles with `--extra mcp`, so images built from it install `fastmcp` and mount `/api/mcp/`. Both `docker-compose.yml` and `docker-compose.dev.yml` use that Dockerfile. Because Compose does not rebuild automatically after a Dockerfile change, run `docker compose up -d --build` once on an existing stack to pick it up.

In a local virtual environment, `fastmcp` is an optional extra. Without it, the app starts normally without mounting the MCP endpoint (logged at `INFO` level on startup). To enable it locally:

```bash
uv pip install -r backend/requirements.txt
uv pip install "fastmcp>=3.4,<4"     # or: uv pip install -e "backend[mcp]"
```

The desktop build excludes MCP. PyInstaller installs from the checked-in `backend/requirements.txt`, which omits the `mcp` extra. Do not regenerate `requirements.txt` with `--extra mcp`. `fastmcp` pulls roughly thirty transitive packages (`keyring`, `jeepney`/`SecretStorage`, `aiofile`/`caio`, and others) that load backends via entry points and D-Bus and are not listed in `desktop/binderdash.spec`'s `hiddenimports`. Containers do not have this PyInstaller constraint, so Docker enables the extra at build time.

No environment variable toggles the mount; availability depends solely on whether `fastmcp` can be imported. Because the mount happens at module import time (before tests can patch settings), an environment flag would be untestable and could hide why the endpoint is absent.

## Authenticating

MCP uses the same **per-user API keys** as scripted REST access (see [Authentication](../setup/authentication.md)). Create one with:

```bash
python -m backend.cli key create alice --name mcp
```

Send it as `Authorization: Bearer bd_…` (canonical) or `X-Binderdash-Api-Key: bd_…`. Keys use the same TTL cache as REST, so revoking a key applies to both immediately.

API keys require `DATABASE`. Without database persistence, no key store exists and all requests return 401 (logged as a startup warning). With `DISABLE_AUTHENTICATION=true`, the server mounts without authentication and logs a warning.

### Client configuration

The web UI generates client snippets for you: open **account menu > API keys > Create**, then expand *"Use with Claude Code or another AI agent (MCP)"* or *"Use Claude Science"* on the new-key panel. Both prefill this server's URL and the new key. These sections appear only when MCP is mounted (`GET /api/auth/status` reports `mcp.enabled`).

Add the server to Claude Code with one command:

```bash
claude mcp add --transport http --scope user binderdash \
  https://binderdash.example.org/api/mcp/ \
  --header "Authorization: Bearer bd_your_key_here"
```

Alternatively, edit `~/.claude.json` (all projects) or `.mcp.json` (one project) directly. That command writes the following JSON structure, which other MCP clients also accept:

```json
{
  "mcpServers": {
    "binderdash": {
      "type": "http",
      "url": "https://binderdash.example.org/api/mcp/",
      "headers": { "Authorization": "Bearer bd_your_key_here" }
    }
  }
}
```

The key is stored in plain text in that file, so use a dedicated expiring key per agent and revoke it from the UI when finished. A project-scoped `.mcp.json` is shared with anyone who clones the repository, and Claude Code prompts each user to approve the server before first use.

For Claude Science, open **Settings > Connectors > Add Connector**, choose **Local URL**, and enter:

- Name: `binderdash`
- Server address: `https://binderdash.example.org/api/mcp/`
- Type: Streamable HTTP
- Advanced settings: leave OAuth Client ID, OAuth Server URL, and Scopes empty, and paste the following into the header command field (Claude Science executes it locally on each connect and sends the printed JSON as request headers):

```bash
echo '{"Authorization": "Bearer bd_your_key_here"}'
```

The key is embedded in that command in plain text. The new-key panel's **Use Claude Science** section prefills these values.

## Tools

| Tool | Purpose |
|---|---|
| `list_runs` | Projects, runs, methods, **design counts**, filters, timestamps, signed download URLs, merge groups |
| `describe_methods` | Canonical metrics, **sort directions**, ranking presets |
| `describe_columns` | Columns for a selection, per-method coverage and ranges |
| `query_designs` | Filter, sort, page and project the design table |
| `summarize_designs` | Quantiles and histograms without returning rows |
| `rank_designs` | Multi-metric rank-based scoring with a filter cascade |
| `select_diverse_designs` | Filter, rank, and de-duplicate by sequence; optional Saved Set |
| `saved_sets` | List, read, create (from design keys), rename Saved Sets |
| `extract_sequences` | Extract sequences from structures into the derived cache |
| `inspect_structures` | Chains, roles, sequences, `binderdash_*` interface metrics, and a tokenised structure URL |
| `read_structure_file` | Raw structure text, size-capped. Over the cap, the error includes a download URL |
| `export_structures` | Manifest plus an absolute GET URL for a tar of the structures |
| `list_target_residues` | Targets in a run scope, residue labels to filter on, contact coverage |
| `target_contact_profile` | Per-residue mean ΔSASA / closest approach / contact frequency |
| `prepare_sequences` | Add N/C tags, linkers, stops and short names; return a download URL for the ordering table |
| `merge_design_columns` | Add TSV/CSV columns to the design table (same as Upload extra data) |

No plotting tool is exposed: `query_designs` returns column-selected tabular data for an agent to chart itself. For bulk exports, `list_runs` provides `designs_json_url` and `designs_tsv_url` per run with a short-lived `download_token` (JWT claims bound to that `run_id` and format, valid for ~10 minutes). Fetch those URLs with `curl` without the MCP API key instead of raising `query_designs` limits past the response size cap. Download URLs are absolute when the server knows its public origin (`PUBLIC_BASE_URL`, falling back to `https://` plus `DOMAIN`, then the incoming request). The response also includes `base_url`. Each run reports `ingested_at` (first Binderdash ingest) and `folder_mtime` (run-directory mtime at ingest).

`inspect_structures` returns one absolute `structure_url` per design with a token scoped to that run and filename. `export_structures` stashes the file list and returns an absolute `GET /api/pdbs/tar?download_id=&download_token=` URL that you can fetch with `curl` without an API key or request body. Both tokens expire after about 10 minutes, and the archive stash is cleared on server restart. `read_structure_file` enforces a size cap (20 KB default, 200 KB hard limit); exceeding the cap returns an error containing the download URL for local parsing. The `structure_url` field on rows from `query_designs`, `rank_designs`, `select_diverse_designs`, and `saved_sets` has no token and cannot be fetched directly; call `inspect_structures` or `export_structures` instead.

### Target contacts

`query_designs`, `rank_designs`, and `select_diverse_designs` accept an optional `target_contact_groups` parameter alongside `filters`. A contact condition applies a threshold on a target residue (for example, "A166 within 5 Å of the binder (heavy atoms)" or "the epitope buries at least 30% of its surface on binding"), evaluated from the design's structure as a hard filter.

```json
{"target_key": "…", "label": "PD-L1", "filters": [
  {"residues": ["A54", "A56"], "scope": "any", "metric": "distance",
   "distance_type": "heavy", "operator": "<=", "value": 5.0}
]}
```

`metric` is `distance` (with `distance_type` `ca`, `cb`, or `heavy`), `sasa_bound`, or `delta_sasa`. `unit` is `angstrom` or `percent` of the residue's theoretical maximum (Tien et al. 2013). `scope` is `any` or `all` of the listed residues, `count` (with `min_count`), or `site_percent` (the metric summed over the listed residues). Supplying one group per target lets a single call specify equivalent residues under different construct numbering schemes; if a design's run is outside a group's scope, that group does not filter it.

Call `list_target_residues` first to get the `target_key` and residue labels, and `target_contact_profile` to inspect which residues binders contact before choosing filter thresholds. Runs are grouped into targets by **sequence** (not chain ID), so one target spans runs that assign different chain letters.

Computing per-residue contact records is not exposed as an MCP tool because parsing every structure in a selection takes minutes; trigger it from the Compute button in the web UI's Filtering tab. A design without cached contact records fails every contact condition, so tools emit a `TARGET_CONTACTS_UNAVAILABLE` warning and note in empty results that contacts may not have been computed yet.

### Preparing sequences for ordering

`prepare_sequences` runs the same construct builder as the Prepare Sequences tab (`backend/seq_prep/`): N/C-terminal tags and linkers, start methionine, stop codons, post-stop padding, and short names. Pass a run/design selection, a `config` matching the tab's settings, and `format` (`twist` default, `fasta`, `tsv`, `csv`, or `json`).

`prepare_sequences` does **not** run DnaChisel, because constraint solving for a few hundred designs takes minutes and exceeds typical tool call timeouts. When DNA output is enabled, the tool returns an unoptimised reverse translation (matching the UI before you click Optimize DNA) with `dna_optimized: false` and a warning, because a plain reverse translation looks identical to optimised DNA on inspection and synthesis problems appear only after ordering. Generate constraint-checked DNA from the UI or its exported script.

Construct rows are omitted from the tool response to avoid filling the agent context window. Instead, the response returns counts, warnings, and a `download_url` with a short-lived token scoped to that request and format (fetchable without the MCP API key). The server stores the request in memory without writing to disk and renders the file when you fetch the URL; the URL expires after the TTL or a server restart.

Designs without a placed tag are skipped and reported in a skip list, so an unconfigured selection is flagged explicitly instead of outputting untagged constructs. Pass `default_tag` to supply a fallback terminus for untagged designs.

The MCP write scope covers read and analysis operations, Saved Sets (including creating sets from design lists), merging extra TSV/CSV columns into designs, and compute-and-cache operations (sequence extraction, structural metrics) that populate derived caches. Scanning, ingesting, deleting, and cache refresh are not exposed.

## Differences from the REST API

The MCP layer does not mirror the REST API; it addresses the issues catalogued in `BINDERDASH_API_OVERHAUL.md` without breaking existing REST clients:

- Sort directions are explicit: `iptm` and `ptm` are higher-is-better, while `pae_interaction` and `rmsd` are lower-is-better. `order="auto"` applies the expected direction, and requesting the opposite emits a `SORT_DIRECTION_OVERRIDE` warning instead of returning a reversed ranking without notice.
- Canonical column names resolve per method (for example, `iptm` maps to `Average_i_pTM` for BindCraft and `design_to_target_iptm` for BoltzGen). Canonical resolution takes precedence over a matching raw column name because `pae_interaction` is also RFdiffusion's raw column name, and matching the raw name first would leave other methods null.
- Server filesystem paths are omitted: `pdb_file` is replaced by `structure_filename`, `structure_format`, and `structure_url`; `params`, `target_sequence`, `run_path`, and per-replicate `^\d+_` columns are excluded.
- Sorting, `limit`, `offset`, and column projection run server-side (REST does not support these).
- Errors and partial results are reported explicitly: a ranking metric that resolves for no design raises an error instead of being skipped, and a diverse set smaller than its budget explains why.
- Oversized responses return a `RESPONSE_TOO_LARGE` error instead of truncating output.

## Response shape

Data-returning tools share one envelope. Rows are returned as arrays instead of objects (using 40-55% fewer tokens on wide tables) and floats are rounded to four significant figures:

```json
{
  "columns": ["run_id", "design_id", "method", "iptm", "structure_filename"],
  "rows": [["bc", "d1", "bindcraft", 0.9123, "d1.pdb"]],
  "total_matching": 1240, "returned": 25, "offset": 0, "truncated": true,
  "methods": {"bindcraft": {"columns": ["Average_i_pTM"], "higher_is_better": true}},
  "warnings": [{"code": "MERGED_RUN", "message": "..."}]
}
```

Errors are formatted as `[CODE] message` and end with a concrete next tool call: `UNKNOWN_COLUMN` (including the nearest column names), `AMBIGUOUS_DESIGN_REF`, `NO_RANKABLE_METRICS`, `RESPONSE_TOO_LARGE`, `EMPTY_SELECTION`, `SEQUENCES_REQUIRED`, and `INVALID_TARGET_CONTACT_FILTER`.

## Implementation notes

The package directory is `backend/mcp_server/` (not `mcp`), because `pytest` adds `backend/` to `sys.path`, where a package named `mcp` would shadow the SDK imported by `fastmcp`.

- `server.py`: FastMCP instance, `TokenVerifier`, the ASGI app, the `X-Binderdash-Api-Key` header shim, and `run_blocking` (service-layer calls run in `asyncio.to_thread`, with a semaphore on heavy calls so an agent loop cannot starve the interactive web UI sharing the process).
- `vocab.py`: canonical metrics, sort directions, and ranking presets (moved server-side from `frontend/src/config/rankingPresets.ts`).
- `columns.py`, `refs.py`, `tables.py`, `errors.py`, `descriptions.py`: shared column resolution, reference parsing, table formatting, error helpers, and tool descriptions.
- `contacts.py`: shared target-contact filtering. Conditions are evaluated into boolean `__tc_*` columns via `filtering.service.build_filter_inputs` (the same entry point used by the REST filtering endpoints) and appended to the hard filters, so tools treat them as standard filters and strip the virtual columns before returning rows.
- `tools/`: `discovery.py`, `designs.py`, `selection.py`, `structures.py`, `target_contacts.py`.

Two integration points in `backend/main.py` are required:

1. CSRF exemption for `/api/mcp/`: the MCP sub-app authenticates via `Authorization` only and does not read cookies, so CSRF protection does not apply. Without the exemption, a missing API key returns a `text/plain` 403 `"CSRF token missing"` response that MCP clients cannot parse.
2. Lifespan chaining: mounting a sub-app in Starlette does not start its lifespan, which is where the streamable-HTTP session manager initializes. Without chaining the sub-app lifespan, imports succeed but every tool call fails at runtime with `"Task group is not initialized"`.

Tool descriptions in `descriptions.py` are the agent's only documentation; treat edits to them as behaviour changes.
