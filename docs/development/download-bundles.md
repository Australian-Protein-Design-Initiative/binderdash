# Download bundles

A **design bundle** is a single zip archive containing downloaded design data and the UI state that produced it. You can inspect which runs, filters, ranking settings, and tags generated a folder of PDBs and sequences months later, and restore that state if the runs are still available.

Three endpoints build bundles through `backend/bundles/`:

| Entry point | Endpoint |
|---|---|
| Designs tab download button | `POST /api/bundles/designs` |
| Prepare Sequences download button | `POST /api/bundles/prepare-sequences` |
| Saved Sets "download" | `GET /api/saved-sets/{id}/download` |

Call `POST /api/bundles/estimate` beforehand to get counts and byte sizes without reading structure files, allowing the UI to warn before a large download.

## Scope

A bundle includes **the rows currently in the Designs table**: the selected designs if any are checked, or all filtered designs otherwise. It does not include unselected or filtered-out designs from the active runs.

## Contents

All files are placed inside a single top-level folder matching the zip filename: the order name for Prepare Sequences, `saved_set_<name>` for a Saved Set, or `binderdash_designs` for a plain Designs-tab download. Extracting the archive creates that folder instead of unpacking files into the current directory.

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

Prepare Sequences adds `constructs.tsv`, `constructs_aa.fasta`, `constructs_dna.fasta`, `constructs_twist_aa.csv`, `constructs_twist_dna.csv`, and `prepare_sequences.json`.

Every entry point writes the same core member list. A saved set created before UI state recording was added still includes `binderdash_session.json`, with `"captured": false` and a note explaining why it is empty.

General tables use TSV only; the Designs tab still offers a separate CSV download, so duplicating rows in both delimiters inside the archive is unnecessary. `constructs_twist_aa.csv` and `constructs_twist_dna.csv` use CSV because they are Twist vendor upload formats (amino acid and nucleotide). If no optimised DNA is available, `constructs_twist_dna.csv` is omitted and a warning is added to the manifest.

## Cached target contacts

`target_contacts.tsv` exports only records already present in `binderdash_target_contacts_cache` for the bundled designs. Computing SASA takes minutes, so downloads do not trigger it. Designs missing a cached record are listed in `manifest.json` under `coverage.designs_without_contacts`, alongside `coverage.contact_params_key` (records cached under an older parameter key are not readable by the current configuration and are excluded from coverage counts).

`sasa_apo` is read from the per-run reference map, except when a run's target moves between designs; in that case the per-design record provides its own `sasa_apo` value and overrides the shared reference so the SASA delta stays accurate.

## Versioning

Every JSON member includes `schema_version`, a `kind` discriminator, and the app version and git commit that generated it. Increment the **major** version only for breaking changes (removing or retyping a field); increment the minor version for additive optional fields. Readers reject any major version higher than the one they support and ignore unknown keys.

`backend/bundles/json_schemas.py` generates schemas from the Pydantic models at request time so each schema matches its corresponding JSON data. To detect unversioned model changes, `backend/tests/test_bundle_schemas.py` compares each generated schema against a golden snapshot in `backend/tests/fixtures/bundle_schemas/`. When that test fails, check whether the change is additive (regenerate the golden snapshot and increment the minor version) or breaking (add a new golden file, increment the major version, and keep the previous snapshot).

`SessionState` and `PrepareSequencesPayload` use `extra="allow"` because they mirror Pinia stores that change independently of the backend, and rejecting a download with HTTP 422 over an extra pass-through frontend field would break exports unnecessarily. Presentational fields (coloured segment spans, display duplicates) are accepted on input and stripped before writing so the archive stores data only.

## Build identity

`backend/version.py` resolves the app version and commit in this order:

1. The `BINDERDASH_GIT_COMMIT` environment variable (set as a Docker build arg).
2. `backend/_build_info.json` (written by `desktop/packaging/build-common.sh` for PyInstaller builds that have no `.git` directory).
3. `git rev-parse` in a source checkout.
4. `unknown`.

Resolution is lazy and cached, so the git subprocess runs at most once per process and only when a bundle is built.

## Memory and size

Bundles are written to a `tempfile.SpooledTemporaryFile` (up to 32 MB in RAM before spilling to disk) and streamed with an accurate `Content-Length` header. A streaming generator writer would omit `Content-Length`, turn mid-archive errors into truncated HTTP 200 responses, and still use similar memory because structure files are streamed in both approaches.

Set `BUNDLE_SPOOL_DIR` for desktop deployments where `/tmp` is mounted on tmpfs (RAM), so spilled files write to disk instead of memory.

`BUNDLE_MAX_STRUCTURE_FILES`, `BUNDLE_MAX_STRUCTURE_BYTES`, and `BUNDLE_MAX_TOTAL_BYTES` prevent oversized requests and return HTTP 413 with the measured estimate when exceeded. The UI uses a lower warning threshold because `response.blob()` buffers the entire archive in browser memory.

## Restore

"Restore session from JSON" in the app header loads a `binderdash_session.json` or `prepare_sequences.json` file back into the Pinia stores (`frontend/src/session/{sessionState,prepareState}.ts`). Restoration runs per section so filters still load even if some original runs are no longer present in Binderdash. Each section reports `applied`, `partial`, or `skipped`.

Filter and ranking restoration delegates to `filteringStore.loadRecipe()`, sharing the same code path used by a Saved Set's "Reapply filters" action.

Optimised DNA is not restored because it depends on both the settings and the input sequences. Leaving it blank and setting the store's staleness flag prompts you to re-run optimisation instead of displaying stale DNA.
