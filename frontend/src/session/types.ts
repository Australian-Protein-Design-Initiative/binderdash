/**
 * Shapes of the versioned JSON files a download bundle carries.
 *
 * These mirror the backend models in backend/session_state.py and
 * backend/bundles/models.py. Both sides are deliberately tolerant of unknown keys, so
 * adding a field here does not require a backend change to keep downloads working.
 */

export const SESSION_SCHEMA_VERSION = '1.0'
// 1.1 adds per-row 'seed' and 'tool_versions' so an optimisation run can be replayed.
// Additive, so 1.0 readers still accept it (see assertReadableVersion).
export const PREPARE_SCHEMA_VERSION = '1.1'

export const SESSION_KIND = 'binderdash.session'
export const PREPARE_KIND = 'binderdash.prepare_sequences'

export interface BuildInfoDto {
    app_version: string
    git_commit?: string | null
    git_dirty?: boolean | null
    build_source?: string
    python_version?: string
    platform?: string
}

export interface SessionSortDto {
    field: string
    order: number
}

export interface SessionRunRefDto {
    run_id: string
    run_name?: string | null
    project_id?: string | null
    method?: string | null
    run_path?: string | null
}

export interface SessionStateDto {
    schema_version: string
    kind?: string
    captured?: boolean
    note?: string | null
    captured_at?: string | null
    active_view?: string | null
    runs: SessionRunRefDto[]
    run_ids: string[]
    selection_mode: 'explicit' | 'all_filtered'
    selected_design_count?: number | null
    visible_columns: string[]
    sort: SessionSortDto[]
    best_mpnn_only?: boolean | null
    saved_set_ids: string[]
    filtering: Record<string, any>
    plots: Record<string, any>
    saved_set_id?: string | null
    binderdash?: BuildInfoDto | null
}

export interface PrepareSequencesStateDto {
    schema_version: string
    kind?: string
    order_name: string
    extract_chain: string
    good_only: boolean
    dna_mode: boolean
    n_tags: Array<Record<string, any>>
    c_tags: Array<Record<string, any>>
    /** Legacy free-text additions, now ordinary custom tags flagged `always`; read on restore only. */
    n_terminal_prefix?: string
    c_terminal_suffix?: string
    stop_options: Record<string, any>
    short_name_strategy: Record<string, any>
    codon_table_id?: string | null
    optimization_method?: string | null
    optimization_constraints: Array<Record<string, any>>
    /** Dependency versions the per-row seeds are replayable against (schema 1.1+). */
    tool_versions?: Record<string, string>
    rows?: Array<Record<string, any>>
}

/** What a restore actually managed to do, per section, for reporting back to the user. */
export interface RestoreOutcome {
    section: string
    status: 'applied' | 'skipped' | 'partial'
    detail?: string
}
