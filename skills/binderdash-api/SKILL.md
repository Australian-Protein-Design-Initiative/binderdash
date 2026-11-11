---
name: binderdash-api
priority: 5
description: >
  Documents the Binderdash REST API for agents — projects, runs, designs, PDB/CIF
  downloads, DNA codon optimisation (DnaChisel), and tag placement. Agents should
  use this skill when the user mentions Binderdash, Binderdash API keys, Bearer or
  API-key auth, fetches designs/runs/PDBs from a Binderdash instance (URL in $BINDERDASH_BASE_URL),
  wants design tables sorted by metrics (iptm, pae_interaction, Average_i_pTM,
  rf3_ipsae_min, design_to_target_iptm), adds N-/C-terminal tags (His, FLAG, HA,
  cMyc, AviTag, Strep-tag II, C-tag, SNAC-tag, TEV-site, G4S linker, STOP*), or optimises DNA with GC/hairpin/restriction-site/codon
  constraints. Binderdash returns non-standard JSON (flat design dicts with
  method-dependent columns); this skill prevents agents from guessing shapes.
---

# Binderdash API skill

Binderdash is a web app + FastAPI service that aggregates the results of de novo protein binder design runs (BindCraft, RFdiffusion / RFdiffusion3, BoltzGen, …), tailored for use with outputs from the nf-binder-design pipeline. This skill describes how an agent can drive the same REST API the browser frontend uses, both for read-only data extraction (designs, scores, PDB/CIF files) and for the DNA optimisation / sequence preparation workflow.

> **Prefer the MCP server if the instance has one.** Binderdash exposes MCP at
> `/api/mcp/` (same API key, `Authorization: Bearer bd_…`). It fixes, by construction,
> most of what the NEVER list below warns about: canonical metric names resolve per
> method, sort directions come from a server-side vocabulary instead of being guessed,
> `pdb_file` server paths are replaced by `structure_filename`/`structure_url`, and
> sort/limit/column-selection happen server-side. Use this REST skill when MCP is
> unavailable, or for the DNA optimisation and tag-placement workflows, which MCP does
> not cover. See `docs/development/mcp.md`.

## When to Use This Skill

- User mentions **Binderdash** or the URL of a Binderdash instance (deployed or local)
- Working with Binderdash API keys, `Authorization: Bearer`, or `X-Binderdash-Api-Key` headers
- Fetching designs, runs, or PDB/CIF structure files via the Binderdash API
- Producing TSV/CSV/JSON design tables sorted by metrics (`iptm`, `pae_interaction`, `Average_i_pTM`, `rf3_ipsae_min`, `design_to_target_iptm`)
- Adding **N- or C-terminal tags** (His, FLAG, HA, cMyc, AviTag, Strep-tag II, C-tag, SNAC-tag, TEV-site, G4S linker, STOP*) to binder sequences
- **DNA codon optimisation** with constraints (GC content, hairpins, restriction sites, codon usage, Twist defaults)
- Probing Binderdash **auth status** or checking which auth providers are enabled
- Needing the live **OpenAPI spec** at `/openapi.json` for endpoint shapes

> **Human-maintained docs:** `docs/development/api.md` covers the same ground in prose; this skill is the agent-facing twin.

## NEVER

- **NEVER** call `/files/structure/{file}` in a loop for bulk downloads — use `POST /api/pdbs/tar` (streaming tar, single request)
- **NEVER** include `EnforceTranslation` in the constraints array — the backend always adds it; duplicates cause errors
- **NEVER** assume all designs share the same columns — columns are method-dependent; check the run's `method` first, then consult the per-method score table
- **NEVER** assume a universal "iptm" column exists — the JSON key differs by method (`Average_i_pTM`, `iptm`, `design_to_target_iptm`, `pae_interaction`); always check the method first and use the correct column name and sort direction from the per-method table below
- **NEVER** use the plotting endpoints (`/api/runs/plots/*`) — all numeric columns are already in `/api/designs`; plot locally
- **NEVER** guess the response shape for an undocumented endpoint — fetch `/openapi.json` and read the schema first
- **NEVER** hardcode an API key token in scripts — use environment variables only
- **NEVER** try to create or manage an API key via the API — key management (`/api/api-keys/*`) is session-cookie-only by design; keys can only be obtained from the web UI or the CLI (`python -m backend.cli key create`)
- **NEVER** assume `Sequence` is populated on every design — it is extracted on demand; if null, call `POST /api/designs/sequences` first

## Before calling any endpoint

0. **Base URL**: `printenv BINDERDASH_BASE_URL BINDERDASH_TOKEN`. If the URL is unset, ask the user (see Base URL below).
1. **Auth check**: `GET /api/auth/status`. If `auth_disabled: true`, omit all auth headers. Otherwise, set `$AUTH`.
2. **Method check**: From `GET /api/runs`, note each run's `method` — it determines which score columns exist and the correct sort direction.
3. **Batch over loop**: For >1 design, prefer batch endpoints (`/api/designs?run_ids=...`, `POST /api/pdbs/tar`) over per-file calls.
4. **Large payloads**: `/api/designs` can return thousands of dicts. Pipe through `jq` to filter/sort client-side rather than requesting subsets — there is no server-side pagination or column selection.

## Base URL and OpenAPI

- **Your instance**: read from the `BINDERDASH_BASE_URL` environment variable (e.g. `https://binderdash.example.com`, no trailing slash). Check it with `printenv BINDERDASH_BASE_URL`. If it is unset, ask the user for the web address of their Binderdash instance (a deployed server, or e.g. `http://localhost:8000` if running locally) and suggest they add `export BINDERDASH_BASE_URL=...` to their shell profile, alongside `BINDERDASH_TOKEN`. Never guess a hostname.
- **Development**: typically `http://localhost:8911` (the port mapping defined in `docker-compose.dev.yml`; the in-container port is `8000`). When running uvicorn directly without Docker, the URL is usually `http://localhost:8000`.
- **Interactive docs**: `${BASE}/docs` (Swagger UI), `${BASE}/redoc` (ReDoc), and the raw spec at `${BASE}/openapi.json`. **Always treat `/openapi.json` as the source of truth** for the exact request/response shapes - the curl snippets in this skill are the common cases, but new endpoints or fields may have been added since.
- **Health check**: `GET ${BASE}/health` returns `{"status": "healthy", "timestamp": "..."}` and is unauthenticated; use it as a quick liveness probe.

For all examples below, set:

```bash
BASE="${BINDERDASH_BASE_URL:?set BINDERDASH_BASE_URL to your Binderdash URL}"   # e.g. http://localhost:8911 in dev
```

## Authentication

Protected endpoints require credentials unless the deployment sets `DISABLE_AUTHENTICATION=true` (all endpoints public). Check what is enabled:

```bash
curl -sS "$BASE/api/auth/status" | jq '{auth_disabled, providers, api_keys}'
```

### API key (preferred for agents and scripts)

Binderdash API keys are **per-user, named, expiring, and revocable** — there is no single shared server secret to export. An agent cannot mint its own key; ask the user for one, obtained from the web UI (account menu, top-right → "API keys") or via CLI:

```bash
python -m backend.cli user create --email you@example.org --admin
python -m backend.cli key create you@example.org --name bootstrap
```

The token prints to stdout alone and is shown once (the server stores only a hash). Keys require `DATABASE` to be configured on the server; without persistence, key endpoints return `503`.

Once you have a token, send it on **every** request - including `POST`/`PATCH`/`DELETE`. No login, session cookie, or CSRF token is needed.

Either header form works:

- `Authorization: Bearer <token>`
- `X-Binderdash-Api-Key: <token>`

```bash
export BINDERDASH_TOKEN='<token from the UI or `key create`>'
BASE="${BINDERDASH_BASE_URL:?set BINDERDASH_BASE_URL to your Binderdash URL}"
AUTH=(-H "Authorization: Bearer $BINDERDASH_TOKEN")
```

Examples:

```bash
# List runs
curl -sS "${AUTH[@]}" "$BASE/api/runs" | jq '.runs | length'

# POST without CSRF
curl -sS "${AUTH[@]}" -H 'Content-Type: application/json' \
    -X POST "$BASE/api/sequences/optimize-dna" \
    -d '{"sequences":{"d1":"MAEK"},"codon_table_id":"e_coli_316407","method":"match_codon_usage","constraints":[]}'
```

`GET /api/auth/status` reports a top-level `api_keys: {enabled, reason}` (`reason` is `null`, `"auth_disabled"`, or `"persistence_disabled"`) rather than a per-provider entry. Wrong, expired, or missing keys return `401 Authentication required`. Note `/api/api-keys/*` (creating/renaming/revoking keys) and admin-only `/api/users` reject API-key auth with `403` — those routes are session-cookie-only, so an agent holding only a token cannot manage keys, only use one.

### Browser session (username/password + CSRF)

For interactive use via the SPA, or when no API key is configured:

- **Login**: `POST /api/auth/login` with `{"username": "...", "password": "..."}`. The response sets the session cookie and returns `{"csrf_token": "...", "user": {...}}`.
- **CSRF**: every state-changing request (`POST`, `PUT`, `PATCH`, `DELETE`) **must** include both the session cookie and the header `X-CSRF-Token: <token>`. `GET`/`HEAD`/`OPTIONS` are exempt. A missing or mismatched token returns `403 CSRF token mismatch`.
- **Other providers**: Google OAuth (`GET /api/auth/google/login`) and PAM when configured server-side.
- **Logout**: `POST /api/auth/logout`.

```bash
COOKIES=$(mktemp)
CSRF=$(curl -sS -c "$COOKIES" -H 'Content-Type: application/json' \
    -d '{"username":"alice","password":"secret"}' \
    "$BASE/api/auth/login" | jq -r .csrf_token)

curl -sS -b "$COOKIES" -H "X-CSRF-Token: $CSRF" \
    -H 'Content-Type: application/json' -d '{...}' "$BASE/api/runs/scan"
```

When auth is fully disabled, plain `curl "$BASE/api/runs"` is enough for all methods.

> **Convention:** All examples below use `${AUTH[@]}` (API key header). When no API key token is available and auth is enabled, replace `${AUTH[@]}` with `-b "$COOKIES" -H "X-CSRF-Token: $CSRF"` for state-changing requests, or omit for `GET`.

## Data model

Binderdash has three nested entities:

1. **Project** - a logical grouping (`project_id`), inferred from a parent directory name in the run's filesystem path. There is no dedicated project endpoint; you discover projects by listing runs and grouping by `project_id`.
2. **Run** - one execution of a binder design pipeline; has a stable `run_id` (UUID), a `method` (`bindcraft`, `rfd`, `rfd3`, `boltzgen`, ...), and `metadata` (display `name`, `pdb_count`, `trajectory_count`, `primary_score_stats`, `results_file`). A run may merge multiple ingestion paths under the same `project_id`/`name` - `merged_count` and `total_pdb_count` then appear in `metadata`.
3. **Design** - one row from the run's results table, augmented with `design_id`, `backbone_id` (design id with MPNN/AF2 suffixes stripped), `run_id`, `project_id`, `run_name`, `method`, `run_path`, `pdb_file` (**full server-side filesystem path** — use `split("/")[-1]` or `basename` when passing to endpoints that expect a filename), and **all original columns of the upstream results table flattened in**. The exact extra keys therefore depend on the method - anything you saw in BindCraft's `final_design_stats.csv` or RFD3's score table will appear here verbatim.

Designs may also carry user-edited fields persisted by Binderdash itself: `good` (boolean ★), `tag` (`"N"` or `"C"` - see DNA tag section), `Sequence` (binder amino-acid sequence, extracted on demand from the PDB), `binder_chain`, `short_name` (Twist-friendly short identifier), and method-derived metric columns like `Average_i_pTM`, `iptm`, `pae_interaction`, `Average_pLDDT`, `design_to_target_iptm`, `rf3_ipsae_min`, `pair_pae`, `rf3_rmsd_target_aligned_binder_rmsd_all`.

Per-method primary score columns and their preferred sort direction:

| Method      | Primary score columns                                                                              | Sort   |
| ----------- | -------------------------------------------------------------------------------------------------- | ------ |
| `bindcraft` | `Average_i_pTM`                                                                                    | desc   |
| `rfd`       | `pae_interaction`                                                                                  | asc    |
| `boltzgen`  | `design_to_target_iptm`                                                                            | desc   |
| `rfd3`      | `iptm`, `pair_pae`, `rf3_ipsae_min`, `rf3_rmsd_target_aligned_binder_rmsd_all` (first available)  | desc   |

> **Column name gotcha:** "iptm" is NOT a universal column. The actual JSON key differs by method:
> - BindCraft → `Average_i_pTM` (higher is better, sort descending)
> - RFD3 → `iptm` (higher is better, sort descending)
> - BoltzGen → `design_to_target_iptm` (higher is better, sort descending)
> - RFD → `pae_interaction` (lower is better, sort ascending)
>
> Always check the method first and use the correct column name. Do NOT assume `iptm` exists.

## Common task: list runs and designs, sort by a metric

The two read endpoints you need 95% of the time:

- `GET /api/runs` - array of run objects (uses the in-memory cache, hydrated from SQLite at startup).
- `GET /api/designs[?run_ids=<rid1>,<rid2>,...]` - array of design dicts; filtering is **only** by `run_ids` (CSV). All other filtering/sorting/column selection is client-side.
- `GET /api/runs/{run_id}/table` - the raw results table for one run, returned as `{ "columns": [...], "data": [{...}], "total_rows": N }`.

### List all runs and pick one by name

```bash
curl -sS "${AUTH[@]}" "$BASE/api/runs" | jq '.runs[] | {run_id, project_id, name: .metadata.name, method, pdb_count: .metadata.pdb_count}'
```

### Get all designs for a project, sorted by a metric, output as TSV

The `jq` recipe below filters to a project, sorts descending by `iptm`, and emits a tab-separated table. Adjust `$proj`, the sort key, and the output columns as needed:

```bash
proj="cxcr2_b1"
runs=$(curl -sS "$BASE/api/runs" | jq -r --arg p "$proj" '.runs[] | select(.project_id==$p) | .run_id' | paste -sd,)

curl -sS "${AUTH[@]}" "$BASE/api/designs?run_ids=$runs" \
  | jq -r '
      .designs
      | sort_by(-(.iptm // -1e30))
      | (["design_id","run_name","iptm","pae_interaction","Average_pLDDT","pdb_file"] | @tsv),
        (.[] | [.design_id, .run_name, .iptm, .pae_interaction, .Average_pLDDT, .pdb_file] | @tsv)
    '
```

For ascending metrics like `pae_interaction`, use `sort_by(.pae_interaction // 1e30)`.

### CSV instead of TSV (`@csv`) — snippet, pipe from the designs curl above

```bash
... | jq -r '.designs | (["design_id","iptm"] | @csv), (.[] | [.design_id, .iptm] | @csv)'
```

### JSON subset of columns

```bash
curl -sS "${AUTH[@]}" "$BASE/api/designs?run_ids=$runs" \
  | jq '[.designs[] | {design_id, run_name, iptm, pae_interaction, pdb_file, good, tag}]'
```

### Filter to designs marked "good" — snippet, pipe from the designs curl above

```bash
... | jq '[.designs[] | select(.good == true)]'
```

### Top N per run

```bash
curl -sS "${AUTH[@]}" "$BASE/api/designs?run_ids=$runs" \
  | jq '
      .designs
      | group_by(.run_id)
      | map(sort_by(-(.iptm // -1e30)) | .[0:5])
      | flatten
    '
```

## Common task: download PDB / CIF structure files

Each design has a `pdb_file` field containing the **full server-side filesystem path** (e.g. `/data/runs/project/results/design.pdb`). API endpoints that accept a filename expect just the **basename** (e.g. `design.pdb`). Use `split("/") | last` in jq or `os.path.basename()` in Python to extract it. To download the file:

```
GET /api/runs/{run_id}/files/structure/{filename}
```

This serves both `.pdb` and `.cif` (transparently decompressing `.pdb.gz` / `.cif.gz`). The `Content-Type` is `chemical/x-pdb` or `chemical/x-mmcif`. There is also a legacy alias `GET /api/runs/{run_id}/files/pdb/{filename}` that behaves identically.

Single file:

```bash
curl -sS "${AUTH[@]}" -o "$design_id.cif" \
  "$BASE/api/runs/$run_id/files/structure/$(jq -rn --arg s "$pdb_file" '$s|@uri')"
```

**Bulk download as a tar archive** (much more efficient than calling the single endpoint in a loop):

```
POST /api/pdbs/tar
Body: { "items": [ { "run_id": "...", "filename": "..." }, ... ] }
```

The response is a streaming `application/x-tar` with entries arranged as `{project_id}/{run_name}/{filename}`. Example:

```bash
curl -sS "${AUTH[@]}" -H 'Content-Type: application/json' \
     -X POST "$BASE/api/pdbs/tar" \
     -d "$(jq -n --argjson items "$ITEMS" '{items:$items}')" \
     -o designs.tar
tar -xf designs.tar
```

Where `ITEMS` is built from a `/api/designs` response, e.g.:

```bash
ITEMS=$(curl -sS "${AUTH[@]}" "$BASE/api/designs?run_ids=$runs" \
        | jq '[.designs[] | select(.good==true) | {run_id, filename: (.pdb_file | split("/") | last)}]')
# NOTE: .pdb_file is a full path — must extract basename for the tar endpoint.
```

### TM-aligned reference structure

`GET /api/runs/{run_id}/files/reference?align_filename=...&mode=manual&source=2QKH` (or `mode=input_target&input_target_id=...`) returns a TM-aligned reference structure as mmCIF. The TM-score, RMSD, and aligned length are exposed via `X-Binderdash-*` response headers. Useful for overlaying a known target onto a design.

## DNA optimisation (`/api/sequences`)

Binderdash wraps [DnaChisel](https://edinburgh-genome-foundry.github.io/DnaChisel/) and [`python_codon_tables`](https://github.com/Edinburgh-Genome-Foundry/codon-usage-tables) to back-translate and codon-optimise binder protein sequences. The DNA *tags* themselves are not part of these endpoints - they are concatenated client-side (see next section) and then the assembled AA string is sent to the optimiser.

### List codon tables

```bash
curl -sS "$BASE/api/sequences/codon-tables" | jq '.items[] | select(.value | startswith("e_coli"))'
```

The full set comes from `python_codon_tables.get_all_available_codons_tables()`. The default the UI selects is `e_coli_316407` (E. coli K-12). The `value` field is what you pass as `codon_table_id`; the most useful builtins include:

- `e_coli_316407` - E. coli K-12 substr. MG1655 (default)
- `s_cerevisiae_4932` - S. cerevisiae
- `h_sapiens_9606` - Homo sapiens
- `c_griseus_10029` - CHO cells (C. griseus)
- `p_pastoris_4922` - Pichia pastoris

### Inspect a codon table

```bash
curl -sS "$BASE/api/sequences/codon-tables/e_coli_316407" \
  | jq '{value, label, stop_codons, leucine: .codons_by_aa.L}'
```

`codons_by_aa` is `{ "A": {"GCG": 0.34, "GCC": 0.27, ...}, ..., "*": {...} }` (frequencies sum to 1 per amino acid; stop codons live under the dedicated `stop_codons` array).

### Optimise a batch of sequences

```
POST /api/sequences/optimize-dna
Body: {
  "sequences":      { "design_id_1": "MAEK...", "design_id_2": "MGSS..." },
  "codon_table_id": "e_coli_316407",
  "method":         "match_codon_usage",
  "constraints":    [ { "type": "...", "enabled": true, "params": {...} }, ... ],
  "fixed":          { "design_id_1": [false, false, ..., true] }
}
```

Optional `fixed` is a per-residue boolean mask keyed by `design_id` (same length as that protein). Residues marked `true` must be stops (`*`, frozen as **TAA**) or a leading Met (`M`, frozen as **ATG**), and are excluded from codon optimisation and user constraints. When a design id is omitted from `fixed`, every `*` in that protein is treated as fixed. The Prepare Sequences UI always sends this mask from segment `fixed` flags.
#### `method` (codon optimisation objective)

This is passed straight to DnaChisel's `CodonOptimize`. Common values:

- `match_codon_usage` *(UI default)* - make the codon-usage histogram of the output match the host's table (best for **biological behaviour**, recommended for expression).
- `use_best_codon` - always pick the highest-frequency codon for each AA (most aggressive, but creates highly repetitive sequences and often clashes with `UniquifyAllKmers`).
- `harmonize_rca` - preserve the relative codon adaptiveness of the source host when re-encoding for a different host.

#### `constraints`

Each entry is `{"type": "<DnaChisel name>", "enabled": true, "params": {...}}`. The backend recognises:

| `type`                     | Notes                                                                                                                                              |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EnforceGCContent`         | `params: {mini, maxi, window?}` - fractions in `[0,1]`. Add a `window` (e.g. 50) for local GC bounds.                                              |
| `AvoidHairpins`            | `params: {stem_size, hairpin_window}` - e.g. `{20, 48}`. Exact Watson-Crick stems only.                                                            |
| `AvoidPattern`             | `params.pattern` is either a literal sequence (`"AAAAAAAAA"`, `"GGAGG"`) or a structured `{"type":"RepeatedKmerPattern","params":{"k_size":20,"n_repeats":2}}` (bans tandem repeats of a k-mer). Restriction-site shortcut: pass `"<EnzymeName>_site"` (e.g. `"BsaI_site"`) - DnaChisel resolves it via Biopython's restriction table. The frontend's `ExcludeRestrictionSite` UI helper rewrites `{"type":"ExcludeRestrictionSite","params":{"enzyme":"BsaI"}}` to this form before posting. |
| `AvoidRareCodons`          | `params: {min_frequency: 0.09}` - uses the same `codon_table_id` as the optimisation. Don't pass `species` yourself; the backend injects it.       |
| `UniquifyAllKmers`         | `params: {k: 12}` - bans repeated k-mers (de-novo synthesis vendors love this).                                                                     |
| `AvoidInvertedRepeats`     | `params: {min_tm: 68, stride?}` - rejects snapback hairpins whose Tm reaches `min_tm`, scored with primer3/IDT-style thermodynamic alignment. Catches the short GC-rich and imperfect inverted repeats vendors flag and `AvoidHairpins` misses. |
| `EnforceTranslation`       | Always added by the backend; do **not** include explicitly.                                                                                        |

The frontend's `DEFAULT_TWIST_CONSTRAINTS` (a known-good profile for Twist Bioscience gene synthesis) is:

```json
[
  { "type": "EnforceGCContent",  "params": { "mini": 0.25, "maxi": 0.64 } },
  { "type": "EnforceGCContent",  "params": { "mini": 0.35, "maxi": 0.75, "window": 50 } },
  { "type": "AvoidHairpins",     "params": { "stem_size": 20, "hairpin_window": 48 } },
  { "type": "AvoidPattern",      "params": { "pattern": "AAAAAAAAA" } },
  { "type": "AvoidPattern",      "params": { "pattern": "TTTTTTTTT" } },
  { "type": "AvoidPattern",      "params": { "pattern": "GGGGGG" } },
  { "type": "AvoidPattern",      "params": { "pattern": "CCCCCC" } },
  { "type": "AvoidRareCodons",   "params": { "min_frequency": 0.09 } },
  { "type": "UniquifyAllKmers",  "params": { "k": 12 } },
  { "type": "AvoidPattern",      "params": { "pattern": { "type": "RepeatedKmerPattern", "params": { "n_repeats": 2, "k_size": 20 } } } },
  { "type": "AvoidInvertedRepeats", "params": { "min_tm": 68 } },
  { "type": "AvoidPattern",      "params": { "pattern": "GGAGG" } },
  { "type": "AvoidPattern",      "params": { "pattern": "TAAGGAG" } }
]
```

Use this as a sensible starting point; add restriction-site exclusions for whatever cloning vector the user is targeting. All entries default to `"enabled": true`; set `enabled: false` to keep an entry in the request for round-tripping but skip it.

#### Response shape

```json
{
  "results": [
    { "design_id": "design_001", "optimized_dna": "ATGGCG...", "error": null },
    { "design_id": "design_002", "optimized_dna": null,        "error": "Constraints could not be resolved (No solution found)." }
  ],
  "elapsed_seconds": 2.31
}
```

Each design is independent - failures are per-row, not request-level. A `"No solution found"` failure has already been retried internally (up to five attempts) before it is returned. If many designs still fail with that error, relax the most restrictive constraint (typically `UniquifyAllKmers` `k`, or the windowed `EnforceGCContent`).

## DNA sequence tags (assembled client-side)

Tags are **not** persisted as DNA on the backend - Binderdash only stores `tag = "N"` or `"C"` on the design (whether to graft tags at the N- or C-terminus), plus the binder `Sequence`. The actual tag amino-acid sequences and the construct order live in the frontend (`frontend/src/stores/seqPrep.ts`). When acting as the agent doing sequence prep, replicate this same logic.

### Preset tag sequences

These are the canonical preset sequences the UI offers. Replicate them verbatim - they are the strings users expect to see when they ask for "His tag" or "FLAG":

| Preset    | Sequence (AA)   | Allowed zones |
| --------- | --------------- | ------------- |
| His-N     | `HHHHHHSG`      | N             |
| His-C     | `GSHHHHHH`      | C             |
| FLAG      | `DYKDDDDK`      | N, C          |
| cMyc      | `EQKLISEEDL`    | N, C          |
| HA        | `YPYDVPDYA`     | N, C          |
| AviTag    | `GLNDIFEAQKIEWHE` | N, C        |
| Strep-tag II | `WSHPQFEK`    | N, C          |
| C-tag     | `EPEA`          | C             |
| SNAC-tag  | `GSHHW`         | N, C          |
| TEV-site  | `ENLYFQS`       | N, C          |
| G4S linker | `GGGGS`        | N, C          |
| STOP*      | `*`            | N, C          |

A "custom" tag is whatever the user types (mixed AA / lowercase nucleotide allowed - see UI rules in `seqPrep.ts` if needed).

### Construct assembly order

For each design with binder AA sequence `core` (the `Sequence` field, trailing `*` stripped) and `tag ∈ {"N", "C", null}`:

```
prepared_aa = ""
if n_terminal_prefix: prepared_aa += n_terminal_prefix
if tag == "N":          prepared_aa += "".join(n_tags)
                        prepared_aa += core
if tag == "C":          prepared_aa += "".join(c_tags)
if c_terminal_suffix:   prepared_aa += c_terminal_suffix
if include_stop:        prepared_aa += "*"
```

`n_tags` / `c_tags` are ordered lists of preset or custom tag strings. If `tag` is null, neither list is emitted — `tag` acts as a per-design on/off switch. `n_terminal_prefix` / `c_terminal_suffix` are optional fixed flanking sequences from the user (e.g. `M` start codon, vector linker).

#### Example: add a C-terminal His tag (`GSHHHHHH`) to a design's binder

1. Read the design and ensure `Sequence` is populated. If it's missing, call `POST /api/designs/sequences` (see "Editing designs" below) to extract it from the design's PDB chain.
2. Set the design's `tag` field to `"C"` via `PATCH /api/designs/tag` (so future server-side renders agree with you):

   ```bash
   curl -sS "${AUTH[@]}" -H 'Content-Type: application/json' \
        -X PATCH "$BASE/api/designs/tag" \
        -d '{"run_id":"<rid>","design_id":"<did>","tag":"C"}'
   ```

3. Locally compose the construct: `prepared_aa = core + "GSHHHHHH" + ("*" if include_stop else "")`.
4. Send `prepared_aa` (and any other designs in the batch) to `POST /api/sequences/optimize-dna` to back-translate + codon-optimise to DNA. Leave the `*` in the AA string (or place a STOP* tag) when you want a terminal stop — those residues are frozen as **TAA** and are not rewritten by codon optimisation. Optionally send a matching `fixed` boolean array per design.

For multiple tags on the same terminus, just concatenate them in order, e.g. `core + "GGGGS" + "GSHHHHHH"` for a flexible-linker-then-His-tag.

## Editing designs (small write endpoints)

When the agent needs to persist user-facing edits the SPA also writes:

- `PATCH /api/designs/good` - body `{run_id, design_id, good: true|false|null, source_path?}`. Use `null` to clear.
- `PATCH /api/designs/tag` - body `{run_id, design_id, tag: "N"|"C"|null, source_path?}`. `null` clears the tag.
- `POST /api/designs/short-names` - bulk-set Twist short names: `{updates: [{run_id, design_id, source_path?, short_name}], refresh_cache_after?: bool}`.
- `POST /api/designs/sequences` - extract binder sequences from PDB chains (default chain `B`): `{designs: [{run_id, design_id, pdb_file, chain?, source_path?}], refresh_cache_after?: bool}`. Persists `Sequence` and `binder_chain` on each design.
- `POST /api/designs/tag-placement` - automatically assign `tag = "N"` or `"C"` per design based on SASA / contact analysis of the structure. Same body shape as `tag-metrics` below; results contain the chosen `tag`. Use this when the user wants Binderdash to *predict* the right terminus rather than picking one.
- `POST /api/designs/tag-metrics` - pre-compute the per-design metrics (`n_sasa`, `c_sasa`, `n_target_contacts`, ...) used for tag placement, with optional cache control (`cache_only`, `ignore_cache`).
- `POST /api/designs/refresh-cache` - force-rebuild the in-memory designs cache from the database after a batch of writes.

`source_path` distinguishes designs that share a `(run_id, design_id)` after run merging; pass it through verbatim from the design dict if present.

## Ingestion & plotting (admin / seldom-used)

**Do NOT read** unless the user explicitly asks about run ingestion, rescanning folders, or the SPA's Vega-Lite chart endpoints. See [`references/admin-endpoints.md`](references/admin-endpoints.md).

## Quick reference - endpoint cheat sheet

| Endpoint                                         | Purpose                                            |
| ------------------------------------------------ | -------------------------------------------------- |
| `GET  /openapi.json`                             | Live OpenAPI spec — source of truth                |
| `GET  /docs`                                     | Swagger UI                                         |
| `GET  /health`                                   | Liveness                                           |
| `GET  /api/auth/status`                          | Auth config (providers, disabled flag)             |
| `GET  /api/auth/me`                              | Current authenticated user                         |
| `POST /api/auth/login`                           | Username/password → cookie + CSRF token            |
| `DELETE /api/designs`                            | Bulk-delete designs (admin)                        |
| `GET  /api/runs`                                 | List all cached runs                               |
| `GET  /api/runs/{run_id}/table`                  | Raw results table for one run                      |
| `GET  /api/designs?run_ids=a,b`                  | Designs (filter by run, all other ops client-side) |
| `GET  /api/runs/{run_id}/files/structure/{file}` | PDB or CIF (gz handled)                            |
| `POST /api/pdbs/tar`                             | Bulk PDB/CIF download as tar                       |
| `GET  /api/runs/{run_id}/files/reference?...`    | TM-aligned reference structure (mmCIF + headers)   |
| `PATCH /api/designs/good`                        | Set/clear ★ flag                                   |
| `PATCH /api/designs/tag`                         | Set/clear `"N"` / `"C"` tag terminus               |
| `POST /api/designs/sequences`                    | Extract binder AA from PDB chain                   |
| `POST /api/designs/tag-placement`                | Predict tag terminus from structure                |
| `POST /api/designs/tag-metrics`                  | Per-terminus SASA / contacts                       |
| `POST /api/designs/short-names`                  | Bulk Twist short names                             |
| `GET  /api/sequences/codon-tables`               | Available codon tables                             |
| `GET  /api/sequences/codon-tables/{id}`          | Codon-frequency detail                             |
| `POST /api/sequences/optimize-dna`               | DnaChisel codon optimisation                       |
| `POST /api/filtering/preview`                    | Filter cascade: designs remaining after each stage |
| `POST /api/filtering/apply`                      | Hard filters only → passing design keys            |
| `POST /api/filtering/run`                        | Full filter→rank→diversity pipeline, saved as a Set|
| `GET  /api/saved-sets`                           | List saved sets (`design_count` = diverse set size, `total_input` = pre-filter count) |
| `GET  /api/saved-sets/{id}/designs`               | Full ranked table for a set, with `in_diverse_set` |

For anything not covered here, **fetch `/openapi.json` and read the schema for the relevant route** before constructing a request - it's authoritative and always up to date. Server-side filtering/ranking/diversity-selection request/response shapes are documented in full in `docs/development/api.md`'s "Filtering, ranking, and diversity selection" section.
