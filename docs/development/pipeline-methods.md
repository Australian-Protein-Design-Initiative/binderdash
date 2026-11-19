# Adding a pipeline method type

Binderdash recognises design pipelines by `method` string (e.g. `bindcraft`, `rfd`, `boltzgen`, `rfd3`). When you add a new method, keep the backend detection/metadata and the frontend display config in sync.

## Backend

| Location | Changes |
| -------- | ------- |
| `backend/config/run_signatures.py` | `run_folder_signatures`: declarative entries for `method`, `submethod`, paths (`required_files`, `results_table`, `pdb_pattern`, ...), `primary_score_columns`, design id columns, and trajectory hints. Add a signature dict for the new method in the appropriate priority order. |
| `backend/config/method_paths.py` | `PIPELINE_METHOD_IDS`: add the new id. Update `_RUN_NAME_SEGMENT_BLOCKLIST` and `_PROJECT_ID_SEGMENT_BLOCKLIST` if path segments for the new layout should be ignored when inferring run or project names. |
| `backend/run_discovery.py` | Search for `method ==` and `get("method")` for branches covering target sequence, backbone id, dataframe standardisation, and structure resolution. Add branches only where the new pipeline needs custom handling. |
| `backend/config/score_labels.py` | Optional: add `SCORE_FIELD_LABELS` entries for human-readable names of new score columns in the API and UI. |

Each signature's `primary_score_columns` in `run_signatures.py` should match the client primary-score rules for that method.

## Frontend

Update the relevant exports in `frontend/src/config/pipelineDisplay.ts`:

| Export | Role |
| ------ | ---- |
| `PIPELINE_METHOD_IDS` / `PipelineMethodId` | Register the method id for filters, tags, and TypeScript types. |
| `METHOD_TAG_PALETTE`, `METHOD_TAG_DISPLAY` | Chip colour and icon for Select Runs method tags. |
| `SCORE_FIELD_DEFS` | Declare score columns (table, filters, colouring) for new CSV/TSV fields. |
| `METHOD_BEST_SCORE` | Primary/secondary columns and sort direction for "best design" grouping within MPNN variants. |
| `PRIMARY_SCORE_CHIP_RULES` | Columns used for the primary score chip on Select Runs (align with backend `primary_score_columns`). |
| `getStructureFilenameFromDesign` / `designHasStructureFile` | Add cases only if structure path resolution is non-standard (see existing `boltzgen` handling). |

Other modules may import these exports. After changing method ids or score fields, search `frontend/src` for the old method name or column names.
