# Download bundles

A **design bundle** is a single zip holding the data of a download *and* the interface
state that produced it. The goal is that a folder of PDBs and sequences found six months
later can still be explained - which runs, which filters, which ranking, which tags - and,
where the runs still exist, restored.

Three places produce one, all through the same builder (`backend/bundles/`):

| Entry point | Endpoint |
|---|---|
| Designs tab download button | `POST /api/bundles/designs` |
| Prepare Sequences download button | `POST /api/bundles/prepare-sequences` |
| Saved Sets "download" | `GET /api/saved-sets/{id}/download` |

A pre-flight `POST /api/bundles/estimate` returns counts and byte sizes without reading
any structure file, so the UI can warn before a large download.

## What the scope is

The bundle covers **the rows currently in the Designs table** - the selected designs if
any, otherwise the filtered designs. It is not every design in the selected runs.

## Contents

Everything sits in one folder named after the download — the same name as the zip
file. That name is the order name (Prepare Sequences) or the saved-set name
(`saved_set_<name>`). A Designs-tab download that is neither uses `binderdash_designs`.
Extracting the archive creates that folder instead of scattering files into the
current directory.

```
<order_or_set_name>/
  manifest.json                   build info, file inventory with sha256, coverage counts
  designs.tsv                     one row per design, every column Binderdash holds
  binders.fasta                   binder sequences, >design_id
  binderdash_session.json         the UI state that produced the bundle
  target_contacts.tsv             cached per-residue distances and SASA (if computed)
  target_contacts_reference.json  per-run apo SASA reference and compute parameters
  structures/rank0001_<run>_<name>.pdb
  schemas/*.schema.json           JSON Schema for each JSON member
  README.txt
```

Prepare Sequences adds `constructs.tsv`, `constructs_aa.fasta`, `constructs_dna.fasta`,
`constructs_twist_aa.csv`, `constructs_twist_dna.csv` and `prepare_sequences.json`.

The member list does not depend on which entry point produced the bundle. A saved set
created before UI state was recorded still emits `binderdash_session.json`, with
`"captured": false` and a note explaining why it is empty.

Only TSV: the Designs tab still offers a CSV download separately, but carrying the same
rows twice in two delimiters inside one archive earns nothing. `constructs_twist_aa.csv`
and `constructs_twist_dna.csv` are exceptions because they are Twist vendor upload formats
(amino acid and nucleotide) rather than a general table. The nucleotide file is omitted,
with a manifest warning, when no optimised DNA is available.

## Target contacts are never computed on download

`target_contacts.tsv` holds whatever is already in `binderdash_target_contacts_cache` for
the bundled designs. A SASA computation is minutes-scale, so a download must not start
one. Designs with no cached record are reported in `manifest.json` under
`coverage.designs_without_contacts`, alongside `coverage.contact_params_key` - records
cached under an older parameter key are invisible to the reader and must not be counted
as covered.

`sasa_apo` comes from the per-run reference map, **except** for a run whose target moves
between designs, where the per-design record carries its own value and that one wins.
Using the shared reference there would give the wrong delta for exactly the runs where it
matters.

## Versioning

Every JSON member carries `schema_version`, a `kind` discriminator, and the app version
and git commit that wrote it. Bump the **major** only on a breaking change (a field
removed or retyped); additive optional fields bump the minor. Readers reject a major above
the one they know and ignore unknown keys.

Schemas are generated from the Pydantic models at request time
(`backend/bundles/json_schemas.py`), so a schema cannot disagree with the data beside it.
What that does not catch is a model changing without anyone bumping a version, so
`backend/tests/test_bundle_schemas.py` compares each generated schema against a golden
snapshot under `backend/tests/fixtures/bundle_schemas/`. A failure there means: decide
whether the change was additive (regenerate the golden, bump the minor) or breaking (new
golden file, bump the major, keep the old one).

`SessionState` and `PrepareSequencesPayload` use `extra="allow"`. They mirror Pinia stores
that move faster than the backend, and a download failing with a 422 because the frontend
gained a field would be a poor trade for strictness on data the backend only passes
through. Presentational fields (coloured segment spans, display duplicates) are accepted
on input but stripped before writing - the archive should be data, not a snapshot of one
UI's rendering.

## Build identity

`backend/version.py` resolves the app version and commit in this order: the
`BINDERDASH_GIT_COMMIT` env var (set as a Docker build arg), then
`backend/_build_info.json` (written by `desktop/packaging/build-common.sh`, the only
mechanism that works in a PyInstaller build where there is no `.git`), then
`git rev-parse` in a source checkout, then unknown. It is resolved lazily and cached, so
the subprocess runs at most once per process and only if a bundle is actually built.

## Memory and size

The zip is built into a `tempfile.SpooledTemporaryFile` (32 MB in RAM, then spilling to
disk) and streamed with a real `Content-Length`. A generator-based zip writer would avoid
the temp file but loses the length header, turns a mid-archive exception into a truncated
zip delivered with a 200, and saves no memory, since structure files stream either way.

`BUNDLE_SPOOL_DIR` matters on the desktop app, where `/tmp` is often tmpfs - i.e. RAM -
which would silently defeat the spill.

The caps (`BUNDLE_MAX_STRUCTURE_FILES`, `BUNDLE_MAX_STRUCTURE_BYTES`,
`BUNDLE_MAX_TOTAL_BYTES`) guard against a runaway request rather than normal use, and
return 413 with the measured estimate. The UI's own warning threshold is lower and is
about the browser: `response.blob()` holds the whole archive in memory client-side.

## Restore

"Restore session from JSON" in the app header reads a `binderdash_session.json` or
`prepare_sequences.json` back into the stores
(`frontend/src/session/{sessionState,prepareState}.ts`). It is deliberately per-section
and defensive: a bundle is often opened against a Binderdash whose runs have moved on, and
restoring the filters is still worth doing when two of the runs have gone. Each section
reports applied / partial / skipped.

The filter and ranking half delegates to `filteringStore.loadRecipe()`, which already
existed for a Saved Set's "Reapply filters", so there is one path for turning a stored
recipe back into filter-builder state.

Optimised DNA is not restored. It is a function of the settings plus the sequences, and
stale DNA presented as current would be worse than none; the store's staleness flag
prompts a re-run instead.
