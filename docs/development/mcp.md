# MCP server

Binderdash exposes a [Model Context Protocol](https://modelcontextprotocol.io) server so
an AI agent can analyse binder design campaigns directly — filter and rank designs,
select diverse panels, inspect interfaces, and hand curated Saved Sets back to a human in
the web UI.

The server is **stateless streamable-HTTP**, mounted into the same FastAPI process as the
REST API at **`/api/mcp/`** (note the trailing slash; `POST /api/mcp` 307-redirects to
it). Because it runs in-process it shares the same in-memory design cache as the REST
API — one cache, no drift.

## Installing

**Docker (dev and prod compose): already on.** `backend/Dockerfile` compiles with
`--extra mcp`, so every image built from it has `fastmcp` and mounts the endpoint. Both
`docker-compose.yml` and `docker-compose.dev.yml` build from that Dockerfile, so there is
nothing to configure. Note that Compose does **not** rebuild on a Dockerfile change on its
own — an existing stack needs `docker compose up -d --build` once to pick it up.

**Local venv: opt in.** `fastmcp` is an optional extra, so a plain install does not get
it; the app runs exactly as before and the endpoint is simply not mounted (an INFO line
says so at startup).

```bash
uv pip install -r backend/requirements.txt
uv pip install "fastmcp>=3.4,<4"     # or: uv pip install -e "backend[mcp]"
```

**Desktop: deliberately excluded.** The PyInstaller build installs from the checked-in
`backend/requirements.txt`, which does not carry the extra — see below for why. Do not
"fix" that inconsistency by regenerating `requirements.txt` with `--extra mcp`; it is
what keeps the desktop bundle working.

There is **no env var** to turn it on or off — the mount is gated purely on whether
`fastmcp` imports. A flag would be untestable (the mount happens at module import,
before tests can patch settings) and would add a second way for the endpoint to be
silently missing.

It is an extra rather than a plain dependency because it pulls roughly thirty transitive
distributions (`keyring`, `jeepney`/`SecretStorage`, `aiofile`/`caio`, …) that resolve
backends through entry points and D-Bus and are not declared in
`desktop/binderdash.spec`'s `hiddenimports`. Containers have no such constraint, which is
why they opt in at build time while the desktop bundle does not.

## Authenticating

MCP uses the same **per-user API keys** as scripted REST access (see
[Authentication](../setup/authentication.md)). Mint one with:

```bash
python -m backend.cli key create alice --name mcp
```

Send it as `Authorization: Bearer bd_…` (canonical) or `X-Binderdash-Api-Key: bd_…`.
Keys are validated through the same TTL cache as REST, so revoking a key takes effect
for both at the same moment.

Requires `DATABASE`; without persistence there is no key store and every request is
rejected with 401 (the startup log warns about this explicitly). With
`DISABLE_AUTHENTICATION=true` the server mounts with no auth at all and logs a warning.

### Client configuration

The web UI does this for you: **account menu → API keys → Create**, then expand
*"Use with Claude Code or another AI agent (MCP)"* or *"Use Claude Science"* on the
new-key panel. Both fill in this server's URL and the new key. The sections only appear
when the server actually has MCP mounted (`GET /api/auth/status` reports `mcp.enabled`).

Claude Code, in one command:

```bash
claude mcp add --transport http --scope user binderdash \
  https://binderdash.example.org/api/mcp/ \
  --header "Authorization: Bearer bd_your_key_here"
```

Or edit `~/.claude.json` (all projects) or `.mcp.json` (one project) directly — this is
exactly what the command above writes, and other MCP clients take the same shape:

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

The key is stored in that file in plain text, so prefer a dedicated expiring key per
agent and revoke it from the UI when finished. A project-scoped `.mcp.json` is shared
with anyone who clones the repo, and Claude Code asks each of them to approve the server
before first use.

Claude Science uses its own connector form. Open **Settings → Connectors → Add
Connector** and choose **Local URL**, then:

- **Name:** `binderdash`
- **Server address:** `https://binderdash.example.org/api/mcp/`
- **Advanced settings:** leave OAuth Client ID, OAuth Server URL and Scopes empty, and
  paste this into the header command field. Claude Science runs it on your machine on
  each connect and sends the JSON it prints as request headers:

```bash
echo '{"Authorization": "Bearer bd_your_key_here"}'
```

- **Type:** Streamable HTTP

The key is inside that command in plain text. The new-key panel's **Use Claude Science**
section fills these three values in and shows the form.

## Tools

| Tool | Purpose |
|---|---|
| `list_runs` | Projects, runs, methods, **design counts**, filters, timestamps, signed download URLs, merge groups |
| `describe_methods` | Canonical metrics, **sort directions**, ranking presets |
| `describe_columns` | Columns for a selection, per-method coverage and ranges |
| `query_designs` | Filter, sort, page and project the design table |
| `summarize_designs` | Quantiles and histograms without returning rows |
| `rank_designs` | Multi-metric rank-based scoring with a filter cascade |
| `select_diverse_designs` | Filter → rank → de-duplicate by sequence; optional Saved Set |
| `saved_sets` | List, read, rename Saved Sets |
| `extract_sequences` | Extract sequences from structures into the derived cache |
| `inspect_structures` | Chains, roles, sequences, `binderdash_*` interface metrics, and a tokenised structure URL |
| `read_structure_file` | Raw structure text, size-capped. Over the cap, the error includes a download URL |
| `export_structures` | Manifest plus an absolute GET URL for a tar of the structures |
| `list_target_residues` | Targets in a run scope, residue labels to filter on, contact coverage |
| `target_contact_profile` | Per-residue mean ΔSASA / closest approach / contact frequency |
| `prepare_sequences` | Add N/C tags, linkers, stops and short names; return a download URL for the ordering table |

There is deliberately **no plotting tool**: `query_designs` returns column-selected
tabular data and an agent charts it itself. For bulk dumps, `list_runs` includes
`designs_json_url` / `designs_tsv_url` per run with a short-lived `download_token`
(JWT claims bound to that `run_id` + format, ~10 minutes) — curl those URLs
without the MCP API key rather than raising `query_designs` limits until the cell
budget rejects you. Download URLs are absolute when the server knows its public
origin (`PUBLIC_BASE_URL`, else `https://` plus `DOMAIN`, else the incoming
request). The same response includes `base_url`. Each run also reports
`ingested_at` (first Binderdash ingest) and `folder_mtime` (run-directory mtime
at ingest).

`inspect_structures` returns one absolute `structure_url` per design, with a
token scoped to that run and filename. `export_structures` stashes the file list
and returns one absolute `GET /api/pdbs/tar?download_id=&download_token=` URL;
curl it with no API key and no body. Both expire in about 10 minutes and the
archive stash does not survive a restart. `read_structure_file` stays capped
(20 KB default, 200 KB hard limit); over the cap the error includes that
download URL so the file can be parsed locally. `structure_url` on
`query_designs`, `rank_designs`, `select_diverse_designs` and `saved_sets` rows
has no token and is not fetchable — call `inspect_structures` or
`export_structures`.

### Target contacts

`query_designs`, `rank_designs` and `select_diverse_designs` take an optional
`target_contact_groups` alongside `filters`. A contact condition is a threshold on a
target residue rather than a design-table column - "A166 within 5 Å of the binder
(heavy atoms)", "the epitope buries at least 30% of its surface on binding" - evaluated
from the design's structure and applied as a hard filter.

```json
{"target_key": "…", "label": "PD-L1", "filters": [
  {"residues": ["A54", "A56"], "scope": "any", "metric": "distance",
   "distance_type": "heavy", "operator": "<=", "value": 5.0}
]}
```

`metric` is `distance` (with `distance_type` `ca`/`cb`/`heavy`), `sasa_bound` or
`delta_sasa`; `unit` is `angstrom` or `percent` of the residue's theoretical maximum
(Tien et al. 2013); `scope` is `any`/`all` of the listed residues, `count` (with
`min_count`) or `site_percent` (the metric summed over them). One group per target lets
a single call name equivalent residues under two different constructs' numbering; a
design whose run is outside a group's scope is exempt from that group.

Call `list_target_residues` first for the `target_key` and the residue labels, and
`target_contact_profile` to see what the binders actually touch before choosing
residues to filter on. Runs are grouped into targets by **sequence**, not chain ID, so
one target spans runs that letter its chain differently.

Computing the per-residue records is deliberately **not** a tool: it parses every
structure in the selection and takes minutes, so it stays behind the web UI's Compute
button in the Filtering tab. A design with no record fails every contact condition, so
tools emit a `TARGET_CONTACTS_UNAVAILABLE` warning and an empty result explains that
contacts may be uncomputed rather than reporting it as a real answer.

### Preparing sequences for ordering

`prepare_sequences` runs the same construct builder as the Prepare Sequences tab
(`backend/seq_prep/`): N/C-terminal tags and linkers, start methionine, stop codons,
post-stop padding and short names. It takes a run/design selection plus a `config`
matching the tab's settings, and `format` picks `twist` (default), `fasta`, `tsv`,
`csv` or `json`.

It deliberately does **not** run DnaChisel: constraint solving takes minutes for a few
hundred designs, which is too long for a tool call. With DNA enabled the result is a
plain reverse translation (what the UI shows before Optimize DNA is pressed), flagged
as `dna_optimized: false` with a warning, since a reverse translation is
indistinguishable from an optimised one by eye and the difference only shows up after
ordering. Constraint-checked DNA comes from the UI or its downloaded script.

The rows are **not** returned in the tool result - an ordering table for a few hundred
designs would swamp the context. The result carries counts, warnings and a
`download_url` with a short-lived token scoped to that request and format; fetch it
without the MCP API key. Nothing is written to disk: the request is held in memory and
rendered when the URL is fetched, so the URL stops working after the TTL or a restart.

Designs without a placed tag are skipped and listed, so a selection that was never set
up in the UI returns an explicit skip list rather than untagged constructs; `default_tag`
overrides that for designs with no tag recorded.

**Write scope** is read + analysis + Saved Sets, plus the compute-and-cache writes
(sequence extraction, structural metrics) that only populate derived caches. Scanning,
ingesting, deleting, cache refresh and merge-table upload are not exposed.

## How the tool surface differs from REST

The MCP layer deliberately does not mirror the REST API — it is where the problems
catalogued in `BINDERDASH_API_OVERHAUL.md` get fixed without changing existing REST
consumers.

- **Sort direction is never guessed.** `iptm`/`ptm` are higher-is-better;
  `pae_interaction`/`rmsd` are lower-is-better. `order="auto"` applies the known
  direction, and asking for the opposite produces a `SORT_DIRECTION_OVERRIDE` warning
  rather than a confidently reversed leaderboard.
- **Canonical column names resolve per method.** `iptm` is `Average_i_pTM` for
  bindcraft and `design_to_target_iptm` for boltzgen. Canonical resolution takes
  precedence over a same-named raw column — `pae_interaction` is *also* rfd's own column
  name, and preferring the literal would null out every other method.
- **Server paths never leave the server.** `pdb_file` is replaced by
  `structure_filename` / `structure_format` / `structure_url`; `params`,
  `target_sequence`, `run_path` and per-replicate `^\d+_` columns are never returned.
- **Server-side sort, limit, offset and column selection**, which REST does not have.
- **Silent failures become loud.** A ranking metric that resolves for no design is an
  error, not a skipped term. A diverse set short of its budget always says why.
- **Oversized responses are refused, not truncated** (`RESPONSE_TOO_LARGE`), because
  silent truncation reads as a complete answer.

## Response shape

Data-returning tools share one envelope. Rows are arrays rather than objects (40–55%
fewer tokens on a wide table) and floats are rounded to four significant figures:

```json
{
  "columns": ["run_id", "design_id", "method", "iptm", "structure_filename"],
  "rows": [["bc", "d1", "bindcraft", 0.9123, "d1.pdb"]],
  "total_matching": 1240, "returned": 25, "offset": 0, "truncated": true,
  "methods": {"bindcraft": {"columns": ["Average_i_pTM"], "higher_is_better": true}},
  "warnings": [{"code": "MERGED_RUN", "message": "..."}]
}
```

Errors are raised as `[CODE] message`, always ending in a concrete next call —
`UNKNOWN_COLUMN` (with the nearest names), `AMBIGUOUS_DESIGN_REF`,
`NO_RANKABLE_METRICS`, `RESPONSE_TOO_LARGE`, `EMPTY_SELECTION`, `SEQUENCES_REQUIRED`,
`INVALID_TARGET_CONTACT_FILTER`.

## Implementation notes

`backend/mcp_server/` — named `mcp_server`, not `mcp`, because pytest puts `backend/` on
`sys.path` where a package called `mcp` shadows the SDK that fastmcp imports.

- `server.py` — FastMCP instance, `TokenVerifier`, the ASGI app, the
  `X-Binderdash-Api-Key` header shim, and `run_blocking` (service-layer calls go through
  `asyncio.to_thread`, with a semaphore for the heavy ones so an agent's tool loop cannot
  starve the interactive web UI sharing the process).
- `vocab.py` — canonical metrics, directions, ranking presets (moved server-side from
  `frontend/src/config/rankingPresets.ts`).
- `columns.py`, `refs.py`, `tables.py`, `errors.py`, `descriptions.py` — the shared spine.
- `contacts.py` — the shared target-contact path: conditions are evaluated into boolean
  `__tc_*` columns by `filtering.service.build_filter_inputs` (the same entry point the
  REST filtering endpoints use) and appended to the hard filters, so every tool treats
  them as ordinary filters and only has to strip the virtual columns before returning
  rows.
- `tools/` — `discovery.py`, `designs.py`, `selection.py`, `structures.py`,
  `target_contacts.py`.

Two integration points in `backend/main.py` are load-bearing:

1. **CSRF exemption** for the mount path. The MCP sub-app authenticates only via
   `Authorization` and never reads a cookie, so there is no ambient credential to abuse;
   without the exemption a missing key yields a `text/plain` 403 "CSRF token missing"
   that no MCP client can interpret.
2. **Lifespan chaining.** Mounting does not start the streamable-HTTP session manager —
   that happens in the sub-app's own lifespan, which Starlette does not run for mounted
   apps. Without it every tool call fails at runtime with "Task group is not
   initialized", never at import.

Tool descriptions in `descriptions.py` are the agent's only documentation; treat edits to
them as behaviour changes.
