"""Tool descriptions.

These are the only documentation an agent gets, so treat edits as behaviour changes.
Each follows the same shape: what it does, when to call it, what to call instead, the
gotcha that would otherwise produce a confidently wrong answer, and the size budget.
"""

LIST_RUNS = """List the binder design runs available in Binderdash.

Start here. Every other tool takes `run_id` values from this one.

Each run has a `method` (bindcraft, boltzgen, rfd, rfd3, ...), which determines what
columns its designs carry — there is no fixed schema across methods. Identify runs by
`run_id` and `method` (short, unambiguous); do not rely on a truncated `run_name` in a
client table view. Runs sharing a `merge_group` are separate folders of the same logical
campaign; designs from them can collide on `design_id`, which is why `source_path` exists.

`design_count` is always populated (from the in-memory cache, a cheap DB count, or
`structure_count` as a no-DB fallback) — you do not need an exploratory `query_designs`
just to learn sample sizes. `ingested_at` is when Binderdash first stored the run;
`folder_mtime` is the run directory's filesystem mtime snapshotted at ingest. Filter with
`methods`, `project_id`, `name_contains`, and `target_contains` rather than paging through
every run.

Each run includes `designs_json_url` and `designs_tsv_url` with a short-lived
`download_token` in the query string (scoped to that run + format, ~10 minutes).
The URLs are absolute when `base_url` is set. Curl them directly — no MCP API key
required — instead of pulling every design through MCP. Use `query_designs` /
`summarize_designs` for filtered, sorted, or aggregated subsets.

Cheap; returns metadata only.
"""

DESCRIBE_METHODS = """Explain the metric vocabulary: canonical names, sort directions, ranking presets.

Call this before your first `query_designs` sort or any `rank_designs` call, and
whenever you are about to reason about a metric by name.

The critical content is sort direction. Binderdash metrics do NOT share one: `iptm`
and `ptm` are higher-is-better, while `pae_interaction` and `rmsd` are
LOWER-is-better. Ranking a run by `pae_interaction` descending returns the worst
designs while looking entirely successful. Use canonical names and `order="auto"` and
the direction is applied for you.

Canonical names (`iptm`, `pae_interaction`, ...) resolve per-row to whichever raw
column that design's method actually uses — `Average_i_pTM` for bindcraft,
`design_to_target_iptm` for boltzgen, and so on. Prefer them over raw column names,
which silently match only one method. Tiny response; no run data involved.
"""

DESCRIBE_COLUMNS = """List the columns available across a set of runs, with per-method coverage and ranges.

Call this after `list_runs` when you need to know what is actually measurable for a
selection — particularly before filtering on a column you have not confirmed exists.

`coverage` is what matters in a mixed-method selection: a column present for only one
of three methods will filter out every design from the other two, which reads as a
harsh threshold rather than a missing column.

By default only canonical metrics and commonly useful columns are returned. Set
`include_raw=true` for every raw column name, which for a four-method selection is
150+ entries and several thousand tokens.
"""

QUERY_DESIGNS = """Query the design table: filter, sort, page, and choose columns.

The workhorse for *subsets* — inspect designs, pull metrics for your own analysis, and
gather data to plot yourself. There is no server-side plotting tool because you can
chart these rows directly. For the *full* table of a run, prefer the `designs_json_url`
/ `designs_tsv_url` from `list_runs` (short-lived download_token; curl without the MCP
API key) instead of raising `limit` until the cell budget rejects you. For distributions
and thresholds without rows, call `summarize_designs` first — it returns count, quartiles,
and optional histograms, so you can plan a top-N `limit` from `design_count` /
`total_matching` without a round trip that only exists to learn `n`.

Sorting defaults to `sort="default"`: best designs first, by `iptm` DESCENDING and
then `pae_interaction` ASCENDING for designs that report no iptm. Both are canonical,
so they resolve to whichever raw column each method uses and a mixed-method table
orders sensibly from one call. `sort="primary_score"` instead uses each method's own
configured primary score — the same order the Binderdash web UI shows. Any other
`sort` uses `order="auto"`, applying that metric's known direction (see
`describe_methods`) rather than a guess.

Filters are `{column, operator, value}`. Numeric operators are `<`, `<=`, `>`, `>=`;
string operators are `contains`, `not_contains`, `starts_with`, `ends_with`, `equals`,
`not_equals`, `regex`. Canonical column names resolve per method; raw names do not.

Budget: `limit` defaults to 25 and caps at 200, and rows x columns may not exceed
4000 cells — an oversized request is rejected with a suggested narrower call rather
than truncated, so what you receive is always the complete answer to what you asked.
Ask for the columns you need; the default column set is deliberately small.

`structure_url` on each row is a relative path with no download token and cannot
be fetched. Call `inspect_structures` for one file or `export_structures` for many.
"""

SUMMARIZE_DESIGNS = """Summarise metric distributions without returning individual designs.

Call this to answer "is this run any good", "how do these two runs compare", or "where
should I put the threshold" — it is far cheaper than pulling rows and reducing them
yourself, and it works over selections too large for `query_designs` to return.

Returns count, min/max, mean, median, quartiles and optional histogram bins per
column, optionally grouped by another column (`run_id`, `method`, ...).

Budget: up to 6 columns, 40 groups and 20 histogram bins.
"""

RANK_DESIGNS = """Rank designs by one or more metrics, using Binderdash's rank-based scoring.

Call this when you want the best designs by a composite of several metrics, rather
than a single sort. Scoring is rank-based rather than absolute, so metrics on
different scales combine sensibly and results stay meaningful across runs.

`ranking_mode` is `worst_rank` (default here; BoltzGen-style: each metric is ranked,
divided by an inverse-importance `weight` — a larger weight de-emphasises it — and the
worst scaled rank wins) or `simple` (lexicographic: metrics in list order are the
primary, secondary, … keys, and `weight` is ignored). Omit `higher_is_better` for a
canonical metric and the known direction is used. Optional
`filters` are hard thresholds applied first; designs that fail are ranked but flagged,
never silently dropped, and the per-filter cascade counts tell you which threshold did
the damage.

Unlike the REST endpoint, a metric that resolves for no design in the selection is an
error rather than a silently skipped term — a "ranking" that quietly ignored half your
criteria is worse than no ranking.

Use `select_diverse_designs` instead when you want a non-redundant panel to order,
rather than a leaderboard.

`structure_url` on each row is a relative path with no download token and cannot
be fetched. Call `inspect_structures` for one file or `export_structures` for many.
"""

SELECT_DIVERSE_DESIGNS = """Select a diverse, high-quality panel of designs — filter, rank, then de-duplicate by sequence.

This is what you want when picking designs to actually order and test: the top N by
score are often near-identical sequences, and a panel of near-identical binders wastes
the experiment. Selection trades quality against pairwise sequence dissimilarity via
`alpha` (higher = more weight on diversity).

Requires sequences. Designs without one are EXCLUDED from the pool rather than
treated as maximally dissimilar, so the returned panel can be smaller than `budget`;
when that happens you get a warning saying exactly how many designs lacked sequences
and what to do about it. Set `auto_extract_sequences=true` to extract them from
structures first (slower, and it writes to the server's derived cache).

Set `save_as` to persist the result as a Saved Set, which appears in the Binderdash web
UI for a human to review — the natural way to hand a curated panel back.

Returns only the selected designs, not the whole ranked pool. Selection is
compute-heavy (pairwise alignment); expect seconds to a minute on large selections.

`structure_url` on each row is a relative path with no download token and cannot
be fetched. Call `inspect_structures` for one file or `export_structures` for many.
"""

SAVED_SETS = """List, read, create, or rename Saved Sets — curated design panels shared with the Binderdash web UI.

`action="list"` gives every saved set with its name, creation time, source runs and
counts. `action="get"` returns its designs; `action="rename"` renames one.
`action="create"` persists an explicit list of designs as a new Saved Set visible in
the web UI — the natural way to hand a panel chosen with `query_designs` or
`rank_designs` back to a human.

`create` takes `name` and `designs` (each `{run_id, design_id}`, plus `source_path`
when a merged run has colliding ids). Every listed design is the panel
(`in_diverse_set=true`). A set created this way has no filter recipe to reapply.
Capped at 500 designs; split larger panels.

A ranked/diversity set (from `select_diverse_designs(save_as=...)`) stores the
entire ranked pool with an `in_diverse_set` flag, so a "24-design panel" contains
thousands of rows. `get` therefore defaults to `in_diverse_set_only=true`; set it
false only when you specifically want the ranked pool, and page through it.

Create a diverse panel with `select_diverse_designs(save_as=...)`. Deleting is
deliberately not available here — do that in the web UI.

`structure_url` on a design row is a relative path with no download token and
cannot be fetched. Call `inspect_structures` for one file or `export_structures`
for many.
"""

MERGE_DESIGN_COLUMNS = """Add columns to the design table from TSV or CSV text, the same as Upload extra data in the web UI.

Call this to attach annotations (batch IDs, wet-lab scores, notes) to designs that
already exist in Binderdash. New columns land in extra_data and survive re-ingest;
pipeline fields (iptm, pae_interaction, ...) are never overwritten.

`table` is the full TSV or CSV text, including the header row. One column must
identify designs (`design_id` by default; pass `design_id_column` if yours is named
differently). `run_ids` scopes which runs to update — a design_id that exists only
in another run is counted as unknown.

Set `preview=true` first to see match counts, new column names, and pipeline-name
collisions without writing. Then re-call with `preview=false` to apply. After apply,
`query_designs` and `describe_columns` see the new columns immediately.

Capped at 1 MiB of table text. An empty table or a missing design-id column is an
error, not a no-op.
"""

INSPECT_STRUCTURES = """Analyse the 3D structures of specific designs: chains, roles, sequences, and interface metrics.

Call this to reason about the binder itself rather than its scores — which chain is
the binder, how long it is, how much surface it buries, whether the interface is
plausible.

Returns per design: chain IDs with binder/target roles, residue counts, sequences,
Binderdash's own computed interface metrics (`binderdash_*`, computed from the
as-generated structure and distinct from the pipeline's own reported values), and a
`structure_url`. That URL is absolute when `base_url` is set and already includes a
short-lived `download_token` (~10 minutes). Curl it with no API key, then parse the
file locally. It never returns a server filesystem path.

Metrics are computed on demand and cached; expect seconds per structure the first
time. Capped at 24 designs per call — a compute limit, not just a token one, so keep
batches small when `include_metrics` is on. Use `read_structure_file` only for a
small file you must read as text. A larger file is downloaded from `structure_url`.
"""

READ_STRUCTURE_FILE = """Return the raw text of one design's structure file (PDB or mmCIF).

Call this ONLY when you must read atom records yourself. For chains, sequences,
interface metrics or anything you would otherwise derive by parsing, call
`inspect_structures` — it is far cheaper and already computed.

Structure files are large: a 2 MB mmCIF is roughly 600k tokens and will not fit. The
default cap is 20 KB and the maximum is 200 KB; a file over the cap is an error that
includes a download URL, not a silent truncation. Download that file and parse it
locally. The cap is not raised.
"""

EXPORT_STRUCTURES = """Bundle the structure files for a set of designs into a downloadable archive.

Call this to hand a panel of structures to a human, or to fetch many structures at
once for local analysis. Returns an absolute `download_url` (GET) and the manifest
of what the tar contains, not the bytes. Curl that URL with no API key and no
request body. The link expires in ~10 minutes and does not survive a server restart.

Use `saved_sets(action="get")` or `select_diverse_designs` to choose the designs first.
"""

EXTRACT_SEQUENCES = """Extract amino-acid sequences from designs' structure files and cache them.

Call this when a tool has told you sequences are missing — typically
`select_diverse_designs`, which cannot work without them. Sequences are read from the
structure files and written to the server's derived cache, so this only needs doing
once per run.

This is the one genuinely slow read-side operation: it parses every structure in the
selection. Prefer `select_diverse_designs(auto_extract_sequences=true)`, which does it
only for the designs that actually need it.
"""


TARGET_CONTACT_GROUPS_ARG = (
    "Optional structure-derived conditions on target residues, applied as hard filters "
    "alongside `filters`. Each group is {target_key, run_ids?, label?, filters:[...]}, "
    "and each condition is {residues:['A166','A167'], scope, metric, distance_type, "
    "unit, operator, value}. metric is 'distance' (to the binder, using distance_type "
    "'ca'|'cb'|'heavy'), 'sasa_bound' (solvent accessible surface in the complex) or "
    "'delta_sasa' (surface buried on binding); unit is 'angstrom' or 'percent' of the "
    "residue's theoretical maximum. scope is 'any'|'all' of the listed residues, "
    "'count' (with min_count) or 'site_percent' (the metric summed over them). Call "
    "list_target_residues first for target_key and the residue labels. Requires "
    "precomputed contacts - see list_target_residues for coverage."
)

LIST_TARGET_RESIDUES = """List the target residues you can write contact conditions against.

Call this before using `target_contact_groups` on query_designs, rank_designs or
select_diverse_designs: it gives the `target_key` to write conditions against and the
residue labels (`<chain><resseq>`, e.g. "A166") they accept, plus each residue's
solvent accessible surface in the free target.

Runs sharing a target are grouped by sequence, not chain ID, so one target spans runs
that letter its chain differently; a condition written in one run's numbering therefore
constrains designs in all of them. When runs really do use different targets or
different numbering, you get one entry per target and write one group per target.

`coverage` reports how many designs per run have their per-residue contacts computed.
Conditions treat a design with no record as failing, so a run at 0 coverage silently
drops out of the result. Computing is deliberately not a tool - it parses every
structure and takes minutes - so press 'Compute target contacts' in the web UI's
Filtering tab when coverage is short.
"""

TARGET_CONTACT_PROFILE = """Per-residue summary of what a set of binders actually touches on the target.

Call this to find the epitope before filtering on it: which residues the designs bury,
how often, and how hard - then write a `target_contact_groups` condition on the
residues that matter. Also the cheapest way to compare epitopes between runs.

`metric="delta_sasa"` gives surface buried on binding (mean/median/min/max per
residue), `"distance"` the closest approach of the binder, and `"contact_frequency"`
the fraction of designs contacting the residue under `contact_metric` /
`contact_threshold`. Restrict to specific designs with `design_keys`, which is how you
profile a shortlist rather than the whole run.

Residues with no signal are omitted from the returned rows by default; set
`include_all=true` for every residue, including those no binder ever approaches.
"""
