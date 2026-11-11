/**
 * Centralized API client for Binderdash frontend
 * All API calls should go through this module
 */

/**
 * Thrown from every throw site inside apiRequest() so callers can distinguish
 * "server said no" (with a real HTTP status) from a network/parsing failure.
 */
export class ApiError extends Error {
    status: number

    constructor(message: string, status: number) {
        super(message)
        this.name = 'ApiError'
        this.status = status
    }
}

// Basic type definitions
interface ApiRequestOptions {
    method?: string;
    headers?: Record<string, string>;
    body?: string | FormData;
    requireAuth?: boolean;
    jsonBody?: boolean;
}

interface Folder {
    path: string;
    name: string;
    has_children: boolean;
}

interface TreeResponse {
    folders: Folder[];
}

interface PrimaryScoreStats {
    column: string;
    count: number;
    min: number;
    max: number;
    mean: number;
    median: number;
    stddev: number;
}

interface Run {
    run_id: string;
    project_id: string;
    method: string;
    path: string;
    metadata: {
        name: string;
        pdb_count: number;
        trajectory_count?: number;
        target_count?: number;
        primary_score_stats?: PrimaryScoreStats;
        results_file: string;
        merged_count?: number;
        total_pdb_count?: number;
    };
}

interface RunsResponse {
    runs: Run[];
}

export interface IngestPreviewReingestItem {
    run_group_key: string
    display_name: string
}

export interface IngestPreviewResponse {
    reingest: IngestPreviewReingestItem[]
}

interface Design {
    design_id: string;
    project_id: string;
    run_name: string;
    method: string;
    pae_interaction?: number;
    Average_i_pTM?: number;
    pdb_file?: string;
    run_path: string;
    run_id: string;
    [key: string]: any; // Allow additional properties
}

interface DesignsResponse {
    designs: Design[];
}

export interface TagPlacementItem {
    run_id: string
    design_id: string
    pdb_file?: string | null
    source_path?: string | null
}

export interface TagPlacementRequest {
    designs: TagPlacementItem[]
    binder_chain?: string
    /** Comma- or space-separated chain IDs for target distance / contact calcs. */
    target_chains?: string | null
    distant_from?: string | null
    sasa_probe_radius?: number
    sasa_n_points?: number
    sasa_threshold?: number
    more_distant_threshold?: number
    /** When false, server skips rebuilding designs cache (use refreshDesignsCache once after a batch). */
    refresh_cache_after?: boolean
    /** When true, only return rows found in SQLite tag-metrics cache (no heavy compute). */
    cache_only?: boolean
    /** When true, skip cache reads and recompute metrics (still writes cache when persistence enabled). */
    ignore_cache?: boolean
}

export interface TagPlacementResultRow {
    run_id: string
    design_id: string
    tag?: string | null
    error?: string | null
}

export interface TagPlacementResponse {
    results: TagPlacementResultRow[]
}

export interface MergeTableResponse {
    preview: boolean
    design_id_column: string
    upload_row_count: number
    new_columns: string[]
    matched_design_count: number
    unknown_design_id_count: number
    skipped_columns: string[]
    pipeline_collision_columns: string[]
    would_update_rows?: number
    matched?: number
    updated?: number
    skipped_keys?: number
    unknown_design_ids?: number
}

export interface TagMetricsRow {
    run_id: string
    design_id: string
    pdb_file?: string | null
    sequence?: string | null
    n_aa_type?: string | null
    c_aa_type?: string | null
    n_sasa?: number | null
    c_sasa?: number | null
    n_percent_sasa?: number | null
    c_percent_sasa?: number | null
    n_percent_buried?: number | null
    c_percent_buried?: number | null
    n_c_dist?: number | null
    n_dist_target?: number | null
    c_dist_target?: number | null
    n_target_contacts?: boolean | null
    c_target_contacts?: boolean | null
    predicted_tag?: string | null
    error?: string | null
}

export interface TagMetricsResponse {
    results: TagMetricsRow[]
}

export interface SequenceExtractItem {
    run_id: string
    design_id: string
    pdb_file: string
    chain?: string
    source_path?: string | null
}

export interface SequenceExtractResultRow {
    run_id: string
    design_id: string
    sequence?: string | null
    error?: string | null
}

export interface SequenceExtractResponse {
    results: SequenceExtractResultRow[]
}

interface MessageResponse {
    message: string;
}

const API_BASE = ''

// CSRF token management
let csrfToken: string | null = null

export const setCsrfToken = (token: string | null) => {
    csrfToken = token
}

export const getCsrfToken = (): string | null => {
    return csrfToken
}

async function errorDetailFromResponse(response: Response): Promise<string> {
    try {
        const body = await response.json()
        const detail = body?.detail
        if (typeof detail === 'string' && detail.trim()) {
            return detail
        }
        if (Array.isArray(detail)) {
            const parts = detail.map((item: unknown) => {
                if (item && typeof item === 'object' && 'msg' in item) {
                    return String((item as { msg: string }).msg)
                }
                return String(item)
            })
            if (parts.length) return parts.join('; ')
        }
    } catch {
        /* response may not be JSON */
    }
    return `Request failed (${response.status})`
}

/**
 * Generic fetch wrapper with error handling and CSRF protection
 */
async function apiRequest<T = any>(url: string, options: ApiRequestOptions = {}): Promise<T> {
    try {
        const useJson = options.jsonBody !== false && !(options.body instanceof FormData)
        const headers: Record<string, string> = { ...options.headers }
        if (useJson) {
            headers['Content-Type'] = 'application/json'
        }

        // Add CSRF token for state-changing operations
        if (options.requireAuth !== false && csrfToken && options.method && options.method !== 'GET') {
            headers['X-CSRF-Token'] = csrfToken
        }

        const response = await fetch(url, {
            headers,
            credentials: 'include', // Include cookies for authentication
            ...options
        })

        if (!response.ok) {
            // Handle authentication errors
            if (response.status === 401) {
                // Clear auth store state if available
                try {
                    const { useAuthStore } = await import('./stores/auth')
                    const authStore = useAuthStore()
                    authStore.clearAuth()
                } catch (error) {
                    // Auth store might not be available yet, ignore
                }
                throw new ApiError('Authentication required', response.status)
            }

            // Handle forbidden errors (403) - check if user is authenticated
            if (response.status === 403) {
                try {
                    const { useAuthStore } = await import('./stores/auth')
                    const authStore = useAuthStore()

                    // If auth is enabled and user is not authenticated, logout and show login page
                    if (authStore.isAuthEnabled && !authStore.isAuthenticated) {
                        // User is not authenticated, logout and show login page
                        await authStore.logout()
                        throw new ApiError('Authentication required', response.status)
                    }
                } catch (error) {
                    // If we can't check auth status or logout fails, just throw the original error
                    if (error instanceof ApiError && error.message === 'Authentication required') {
                        throw error
                    }
                }
                throw new ApiError(`Access forbidden: ${response.status}`, response.status)
            }

            throw new ApiError(await errorDetailFromResponse(response), response.status)
        }

        return await response.json()
    } catch (error) {
        console.error(`API request failed for ${url}:`, error)
        throw error
    }
}

/**
 * Tree/Folder Browser APIs
 */
export const treeApi = {
    /**
     * Get folder structure for the file browser
     * @param path - Optional path parameter to get children of a specific directory
     * @returns Promise with folder structure
     */
    async getTree(path = ''): Promise<TreeResponse> {
        const url = `${API_BASE}/api/tree${path ? `?path=${encodeURIComponent(path)}` : ''}`
        return await apiRequest<TreeResponse>(url)
    }
}

/**
 * Runs Management APIs
 */
export const runsApi = {
    /**
     * Scan selected folders for valid run directories
     * @param folders - List of folder paths to scan
     * @returns Promise with discovered runs
     */
    async scanRuns(
        folders: string[],
        options?: { forceRescanOfIngested?: boolean }
    ): Promise<RunsResponse> {
        return await apiRequest<RunsResponse>(`${API_BASE}/api/runs/scan`, {
            method: 'POST',
            body: JSON.stringify({
                folders,
                force_rescan_of_ingested: options?.forceRescanOfIngested ?? false
            }),
            requireAuth: true
        })
    },

    /**
     * List runs in the payload that already exist in the database (re-ingest will reset tag/good).
     */
    async ingestPreview(
        runs: Array<Record<string, unknown>>
    ): Promise<IngestPreviewResponse> {
        return await apiRequest<IngestPreviewResponse>(
            `${API_BASE}/api/runs/ingest-preview`,
            {
                method: 'POST',
                body: JSON.stringify({ runs }),
                requireAuth: true
            }
        )
    },

    /**
     * Persist discovered runs to the database (stable run_id per run_group_key).
     */
    async ingestRuns(runs: Array<Record<string, unknown>>): Promise<RunsResponse> {
        return await apiRequest<RunsResponse>(`${API_BASE}/api/runs/ingest`, {
            method: 'POST',
            body: JSON.stringify({ runs }),
            requireAuth: true
        })
    },

    /**
     * List all cached runs
     * @returns Promise with all cached runs
     */
    async listRuns(): Promise<RunsResponse> {
        return await apiRequest<RunsResponse>(`${API_BASE}/api/runs`, { requireAuth: true })
    },

    /**
     * Get results table data for a specific run
     * @param runId - Unique identifier for the run
     * @returns Promise with table data
     */
    async getRunTable(runId: string): Promise<any> {
        return await apiRequest(`${API_BASE}/api/runs/${runId}/table`, { requireAuth: true })
    },

    /**
     * Get structure file URL for a specific run and filename.
     * Supports both PDB (.pdb) and mmCIF (.cif) files.
     * @param runId - Unique identifier for the run
     * @param filename - Name of the structure file
     * @returns URL to the structure file (authentication via cookies)
     */
    getStructureFileUrl(runId: string, filename: string): string {
        const enc = encodeURIComponent(filename)
        return `${API_BASE}/api/runs/${runId}/files/structure/${enc}`
    },
    /**
     * Backwards-compatible alias for structure URLs.
     */
    getPdbFileUrl(runId: string, filename: string): string {
        return this.getStructureFileUrl(runId, filename)
    },

    /**
     * List input / target structure files discovered from run params.
     */
    async getInputTargets(runId: string): Promise<{ targets: Array<{ id: string; label: string }> }> {
        return await apiRequest(`${API_BASE}/api/runs/${runId}/input-targets`, { requireAuth: true })
    },

    /**
     * Build URL for TM-aligned reference structure (PDB) overlaid on a design file.
     */
    getAlignedReferenceUrl(
        runId: string,
        alignFilename: string,
        options: {
            mode: 'manual' | 'input_target'
            source?: string
            inputTargetId?: string
            referenceChains?: string
        }
    ): string {
        const params = new URLSearchParams()
        params.set('align_filename', alignFilename)
        params.set('mode', options.mode)
        if (options.mode === 'manual' && options.source != null && options.source !== '') {
            params.set('source', options.source)
        }
        if (options.mode === 'input_target' && options.inputTargetId != null) {
            params.set('input_target_id', options.inputTargetId)
        }
        const rc = options.referenceChains?.trim()
        if (rc) params.set('reference_chains', rc)
        return `${API_BASE}/api/runs/${runId}/files/reference?${params.toString()}`
    },

    /**
     * Download a tar archive of multiple PDB files.
     * @param items - Array of { run_id, filename }
     * @returns Blob of the tar file
     */
    async downloadPdbsTar(items: Array<{ run_id: string; filename: string }>): Promise<Blob> {
        const url = `${API_BASE}/api/pdbs/tar`
        const headers: Record<string, string> = {
            'Content-Type': 'application/json'
        }
        // Attach CSRF for POST requests if available
        try {
            const { getCsrfToken } = await import('./webapi')
            const token = getCsrfToken()
            if (token) headers['X-CSRF-Token'] = token
        } catch (_) {
            // ignore
        }

        const response = await fetch(url, {
            method: 'POST',
            headers,
            body: JSON.stringify({ items }),
            credentials: 'include'
        })

        if (!response.ok) {
            if (response.status === 401) throw new Error('Authentication required')
            throw new Error(`HTTP error! status: ${response.status}`)
        }

        return await response.blob()
    },

    /**
     * Remove a run from the cache
     * @param runId - Unique identifier for the run
     * @returns Promise with success message
     */
    async deleteRun(runId: string): Promise<MessageResponse> {
        return await apiRequest<MessageResponse>(`${API_BASE}/api/runs/${runId}`, {
            method: 'DELETE',
            requireAuth: true
        })
    },

    /**
     * Clear all runs from the cache
     * @returns Promise with success message
     */
    async clearRuns(): Promise<MessageResponse> {
        return await apiRequest<MessageResponse>(`${API_BASE}/api/runs`, {
            method: 'DELETE',
            requireAuth: true
        })
    }
}

/**
 * Designs Management APIs
 */
export const designsApi = {
    /**
     * List all designs from all cached runs
     * @returns Promise with all designs
     */
    async listDesigns(runIds?: string[]): Promise<DesignsResponse> {
        const qs =
            runIds && runIds.length > 0
                ? `?run_ids=${encodeURIComponent(runIds.join(','))}`
                : ''
        return await apiRequest<DesignsResponse>(`${API_BASE}/api/designs${qs}`, {
            requireAuth: true
        })
    },

    /**
     * Clear all designs from the cache
     * @returns Promise with success message
     */
    async clearDesigns(): Promise<MessageResponse> {
        return await apiRequest<MessageResponse>(`${API_BASE}/api/designs`, {
            method: 'DELETE',
            requireAuth: true
        })
    },

    async patchDesignGood(payload: {
        run_id: string
        design_id: string
        good: boolean | null
        source_path?: string
    }): Promise<{ ok: boolean }> {
        return await apiRequest<{ ok: boolean }>(`${API_BASE}/api/designs/good`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    },

    async patchDesignTag(payload: {
        run_id: string
        design_id: string
        tag: 'N' | 'C' | null
        source_path?: string
    }): Promise<{ ok: boolean }> {
        return await apiRequest<{ ok: boolean }>(`${API_BASE}/api/designs/tag`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    },

    async postTagPlacement(payload: TagPlacementRequest): Promise<TagPlacementResponse> {
        return await apiRequest<TagPlacementResponse>(`${API_BASE}/api/designs/tag-placement`, {
            method: 'POST',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    },

    async postTagMetrics(payload: TagPlacementRequest): Promise<TagMetricsResponse> {
        return await apiRequest<TagMetricsResponse>(`${API_BASE}/api/designs/tag-metrics`, {
            method: 'POST',
            body: JSON.stringify({ ...payload, refresh_cache_after: false }),
            requireAuth: true
        })
    },

    async refreshDesignsCache(): Promise<{ ok: boolean }> {
        return await apiRequest<{ ok: boolean }>(`${API_BASE}/api/designs/refresh-cache`, {
            method: 'POST',
            body: '{}',
            requireAuth: true
        })
    },

    async extractSequences(payload: {
        designs: SequenceExtractItem[]
        refresh_cache_after?: boolean
    }): Promise<SequenceExtractResponse> {
        return await apiRequest<SequenceExtractResponse>(`${API_BASE}/api/designs/sequences`, {
            method: 'POST',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    },

    async updateShortNames(payload: {
        updates: {
            run_id: string
            design_id: string
            short_name?: string | null
            source_path?: string | null
        }[]
        refresh_cache_after?: boolean
    }): Promise<{ updated: number }> {
        return await apiRequest<{ updated: number }>(`${API_BASE}/api/designs/short-names`, {
            method: 'POST',
            body: JSON.stringify({
                updates: payload.updates,
                refresh_cache_after: payload.refresh_cache_after ?? false
            }),
            requireAuth: true
        })
    },

    async mergeTableUpload(payload: {
        file: File
        runIds: string[]
        preview?: boolean
        designIdColumn?: string
    }): Promise<MergeTableResponse> {
        const form = new FormData()
        form.append('file', payload.file)
        form.append('run_ids', payload.runIds.join(','))
        form.append('preview', payload.preview ? 'true' : 'false')
        if (payload.designIdColumn?.trim()) {
            form.append('design_id_column', payload.designIdColumn.trim())
        }
        return await apiRequest<MergeTableResponse>(`${API_BASE}/api/designs/merge-table`, {
            method: 'POST',
            body: form,
            jsonBody: false,
            requireAuth: true
        })
    }
}

export interface CodonTableOptionDto {
    value: string
    label: string
}

export interface CodonTableListResponseDto {
    items: CodonTableOptionDto[]
}

export interface CodonTableDetailResponseDto {
    value: string
    label: string
    stop_codons: string[]
    codons_by_aa: Record<string, Record<string, number>>
}

export interface DnaOptConstraintSpecDto {
    type: string
    enabled: boolean
    params: Record<string, any>
}

export interface DnaOptimizeRequestDto {
    sequences: Record<string, string>
    /** Per-residue fixed mask keyed by design_id; stops marked true stay as TAA. */
    fixed?: Record<string, boolean[]>
    /** Coding-frame offset (0, 1 or 2) keyed by design_id. */
    frame?: Record<string, number>
    codon_table_id: string
    method: string
    constraints: DnaOptConstraintSpecDto[]
}

export interface DnaOptResultRowDto {
    design_id: string
    optimized_dna?: string | null
    error?: string | null
}

export interface DnaOptimizeResponseDto {
    results: DnaOptResultRowDto[]
    elapsed_seconds: number
}

export const sequencesApi = {
    async listCodonTables(): Promise<CodonTableListResponseDto> {
        return await apiRequest<CodonTableListResponseDto>(`${API_BASE}/api/sequences/codon-tables`, {
            requireAuth: true
        })
    },

    async getCodonTable(tableId: string): Promise<CodonTableDetailResponseDto> {
        const enc = encodeURIComponent(tableId)
        return await apiRequest<CodonTableDetailResponseDto>(
            `${API_BASE}/api/sequences/codon-tables/${enc}`,
            { requireAuth: true }
        )
    },

    async optimizeDna(request: DnaOptimizeRequestDto): Promise<DnaOptimizeResponseDto> {
        return await apiRequest<DnaOptimizeResponseDto>(`${API_BASE}/api/sequences/optimize-dna`, {
            method: 'POST',
            body: JSON.stringify(request),
            requireAuth: true
        })
    }
}

/**
 * Plots APIs - Simplified to work with raw data
 */
export const plotsApi = {
    /**
     * Get combined data from multiple runs for plotting
     * @param runIds - List of run IDs
     * @returns Promise with combined data and column information
     */
    async getCombinedData(runIds: string[]): Promise<{ data: any[], columns: string[], numericColumns: string[] }> {
        const allData: any[] = []
        const allColumns = new Set<string>()

        // Fetch data from each run
        for (const runId of runIds) {
            try {
                const runData = await runsApi.getRunTable(runId)
                if (runData && runData.data) {
                    // Add run_id to each row for identification
                    // TODO: Should this be done in the backend instead ?
                    const enrichedData = runData.data.map((row: any, idx: number) => {
                        // Derive a stable design identifier for selections/tooltips
                        const possibleId =
                            row.Design ?? row.design ?? row.description ?? row.name ?? row.id ?? null
                        const design_id = possibleId != null && String(possibleId).length > 0
                            ? String(possibleId)
                            : `${runId}__row_${idx}`
                        return {
                            ...row,
                            run_id: runId,
                            design_id
                        }
                    })
                    allData.push(...enrichedData)

                    // Collect all column names
                    runData.columns.forEach((col: string) => allColumns.add(col))
                }
            } catch (error) {
                console.warn(`Failed to load data for run ${runId}:`, error)
            }
        }

        // Determine numeric columns
        const numericColumns = Array.from(allColumns).filter(col => {
            if (allData.length === 0) return false
            // Check if column has numeric values (excluding null/undefined)
            return allData.some(row => {
                const v = row[col]
                if (v == null) return false
                const n = typeof v === 'number' ? v : Number(v)
                return Number.isFinite(n)
            })
        })

        return {
            data: allData,
            columns: Array.from(allColumns),
            numericColumns
        }
    }

    ,
    /**
     * Ask backend for numeric columns and sensible defaults across runs
     */
    async getPlotColumns(runIds: string[]): Promise<{ numeric_columns: string[], defaults: { x: string, y: string } }> {
        const url = `${API_BASE}/api/runs/plots/columns`
        return await apiRequest<{ numeric_columns: string[], defaults: { x: string, y: string } }>(url, {
            method: 'POST',
            body: JSON.stringify({ run_ids: runIds }),
            requireAuth: true
        })
    }
}

/**
 * Filtering & Saved Sets APIs
 */
export type FilterOperator =
    | '<' | '<=' | '>' | '>='
    | 'contains' | 'not_contains' | 'starts_with' | 'ends_with'
    | 'equals' | 'not_equals' | 'regex'
    | 'is_empty' | 'is_not_empty'

export const NUMERIC_FILTER_OPERATORS: FilterOperator[] = ['<', '<=', '>', '>=']
export const STRING_FILTER_OPERATORS: FilterOperator[] = [
    'contains', 'not_contains', 'starts_with', 'ends_with', 'equals', 'not_equals', 'regex'
]
export const EMPTY_FILTER_OPERATORS: FilterOperator[] = ['is_empty', 'is_not_empty']

export interface FilterSpecDto {
    column: string
    operator: FilterOperator
    /** Numeric operators (<, <=, >, >=). */
    threshold?: number | null
    /** String operators (contains, starts_with, equals, regex, ...). */
    text_value?: string | null
    /**
     * Local UI-only flag (not sent to the backend — stripped before any request body
     * is built, see stores/filtering.ts's `activeFilters`): lets a user temporarily
     * turn a filter off without losing its configuration. Defaults to true.
     */
    enabled?: boolean
}

export interface RankingMetricDto {
    column: string
    weight: number
    higher_is_better: boolean
    /** Local UI-only flag — see FilterSpecDto.enabled. */
    enabled?: boolean
}

export interface SizeBucketDto {
    min: number
    max: number
    num_designs: number
}

export interface ColumnInfoDto {
    name: string
    canonical_name?: string | null
    present_in_runs: string[]
    dtype: string
    sample_values?: { min: number; max: number; mean: number; median: number } | null
    raw_columns?: Record<string, string>
    /** Known sort/filter direction for canonical metrics (and raw aliases). */
    higher_is_better?: boolean | null
}

export interface FilterCascadeStageDto {
    column: string
    operator: string
    threshold?: number | null
    text_value?: string | null
    /** Designs remaining after this stage (filters cascade sequentially). */
    remaining: number
    /** Set for target-contact stages, whose `column` is an internal `__tc_*` name. */
    label?: string | null
}

export interface FilteringPreviewRequestDto {
    run_ids: string[]
    filters?: FilterSpecDto[]
    target_contact_groups?: TargetContactGroupDto[]
    metrics?: RankingMetricDto[]
}

export interface FilteringPreviewResponseDto {
    total_designs: number
    per_filter_counts: FilterCascadeStageDto[]
    final_passing: number
    available_columns: ColumnInfoDto[]
}

export interface FilteringColumnsResponseDto {
    columns: ColumnInfoDto[]
}

export interface FilteringRunRequestDto {
    name: string
    run_ids: string[]
    filters?: FilterSpecDto[]
    target_contact_groups?: TargetContactGroupDto[]
    metrics?: RankingMetricDto[]
    ranking_mode?: 'simple' | 'worst_rank'
    budget: number
    alpha: number
    size_buckets?: SizeBucketDto[]
    random_state?: number
    /** When false, save every design that passed hard filters (no budget/diversity). */
    apply_diversity?: boolean
    /** Collapse to the best MPNN variant per backbone before diversity selection. */
    best_mpnn_only?: boolean
    /**
     * UI snapshot at save time (table layout, best-MPNN toggle, etc.). Stored in the
     * Saved Set's filter_params and restored by Reapply / Load filters / bundle download.
     */
    ui_state?: Record<string, unknown> | null
}

export interface FilteringRunResponseDto {
    saved_set_id: string
    name: string
    total_input: number
    passing_filters: number
    top_set_count: number
    diverse_set_count: number
    warnings?: string[]
}

export interface SavedSetDto {
    id: string
    name: string
    created_at: string
    source_run_ids: string[]
    filter_params: Record<string, any>
    design_count: number
    total_input: number
}

export interface SavedSetListResponseDto {
    saved_sets: SavedSetDto[]
}

export interface SavedSetDesignRowDto {
    design_id: string
    run_id: string
    source_path?: string | null
    final_rank?: number | null
    quality_score?: number | null
    in_diverse_set: boolean
    metrics: Record<string, any>
}

export interface SavedSetDesignsResponseDto {
    designs: SavedSetDesignRowDto[]
}

export interface DesignKeyDto {
    run_id: string
    design_id: string
    source_path?: string | null
}

export interface FilteringApplyRequestDto {
    run_ids: string[]
    filters?: FilterSpecDto[]
    target_contact_groups?: TargetContactGroupDto[]
}

export interface FilteringApplyResponseDto {
    total_designs: number
    passing_keys: DesignKeyDto[]
    final_passing: number
}

export interface FilteringRankRequestDto {
    run_ids: string[]
    filters?: FilterSpecDto[]
    target_contact_groups?: TargetContactGroupDto[]
    metrics?: RankingMetricDto[]
    ranking_mode?: 'simple' | 'worst_rank'
}

export interface RankedDesignRowDto {
    run_id: string
    design_id: string
    source_path?: string | null
    final_rank?: number | null
    quality_score?: number | null
}

export interface FilteringRankResponseDto {
    designs: RankedDesignRowDto[]
    total_designs: number
}

export interface FilteringDiversityRequestDto {
    run_ids: string[]
    filters?: FilterSpecDto[]
    target_contact_groups?: TargetContactGroupDto[]
    metrics?: RankingMetricDto[]
    ranking_mode?: 'simple' | 'worst_rank'
    budget: number
    alpha: number
    size_buckets?: SizeBucketDto[]
    random_state?: number
    /** Collapse to the best MPNN variant per backbone before diversity selection. */
    best_mpnn_only?: boolean
}

export interface DiverseDesignRowDto {
    run_id: string
    design_id: string
    source_path?: string | null
    final_rank?: number | null
    quality_score?: number | null
    in_diverse_set: boolean
}

export interface FilteringDiversityResponseDto {
    designs: DiverseDesignRowDto[]
    total_designs: number
    passing_filters: number
    diverse_set_count: number
    warnings?: string[]
}

export type TargetContactMetric = 'distance' | 'sasa_bound' | 'delta_sasa'
export type TargetContactScope = 'any' | 'all' | 'count' | 'site_percent'
export type TargetDistanceType = 'ca' | 'cb' | 'heavy'

export interface TargetContactFilterSpecDto {
    /** Residue labels in `<chain><resseq>[<icode>]` form, e.g. "A166". */
    residues: string[]
    scope: TargetContactScope
    /** Only for scope="count". */
    min_count?: number | null
    metric: TargetContactMetric
    /** Only for metric="distance". */
    distance_type: TargetDistanceType
    /** Å² or % of the residue's theoretical maximum; SASA metrics only. */
    unit: 'angstrom' | 'percent'
    operator: '<' | '<=' | '>' | '>='
    value: number
    /** Local UI-only flag — see FilterSpecDto.enabled. */
    enabled?: boolean
}

export interface TargetContactGroupDto {
    /** Identifies which target the residue labels refer to (see TargetInfoDto). */
    target_key: string
    /** Empty means every run in scope whose target matches `target_key`. */
    run_ids?: string[]
    label?: string | null
    filters: TargetContactFilterSpecDto[]
}

export interface TargetResidueDto {
    label: string
    chain: string
    resseq: number
    icode: string
    resname: string
    aa1: string
    sasa_apo: number
}

export interface TargetInfoDto {
    target_key: string
    label: string
    run_ids: string[]
    chain_ids: string[]
    length: number
    residues: TargetResidueDto[]
}

export interface TargetContactCoverageDto {
    run_id: string
    run_name?: string | null
    target_key: string
    total_designs: number
    computed_designs: number
    /** The target's coordinates differ between designs, so apo SASA is per design. */
    target_moves: boolean
}

export interface TargetResiduesResponseDto {
    targets: TargetInfoDto[]
    coverage: TargetContactCoverageDto[]
    warnings: string[]
}

export interface TargetContactsComputeRequestDto {
    run_ids: string[]
    design_keys?: DesignKeyDto[]
    ignore_cache?: boolean
    max_workers?: number | null
}

export interface TargetContactsComputeResponseDto {
    computed: number
    cached: number
    failed: number
    errors: string[]
    coverage: TargetContactCoverageDto[]
}

export interface TargetContactProfileRequestDto {
    run_ids: string[]
    design_keys?: DesignKeyDto[]
    target_key?: string | null
    metric: 'delta_sasa' | 'contact_frequency' | 'distance'
    unit?: 'angstrom' | 'percent'
    distance_type?: TargetDistanceType
    contact_metric?: 'distance' | 'delta_sasa'
    contact_threshold?: number
}

export interface TargetContactProfileRowDto {
    label: string
    chain: string
    resseq: number
    resname: string
    aa1: string
    mean?: number | null
    median?: number | null
    min?: number | null
    max?: number | null
    contact_fraction: number
    n: number
}

export interface TargetContactProfileResponseDto {
    target_key: string
    residues: TargetContactProfileRowDto[]
    n_designs: number
    warnings: string[]
}


export const filteringApi = {
    /** Targets in the run scope, their residue catalogues, and compute coverage. */
    async targetResidues(runIds: string[]): Promise<TargetResiduesResponseDto> {
        return await apiRequest<TargetResiduesResponseDto>(
            `${API_BASE}/api/filtering/target-residues`,
            { method: 'POST', body: JSON.stringify({ run_ids: runIds }), requireAuth: true }
        )
    },

    /**
     * Compute and cache per-residue contact/SASA records. Expensive (two SASA passes
     * per design), so callers batch and show progress rather than requesting a whole
     * run scope in one call.
     */
    async computeTargetContacts(
        payload: TargetContactsComputeRequestDto
    ): Promise<TargetContactsComputeResponseDto> {
        return await apiRequest<TargetContactsComputeResponseDto>(
            `${API_BASE}/api/filtering/target-contacts/compute`,
            { method: 'POST', body: JSON.stringify(payload), requireAuth: true }
        )
    },

    /** Per-residue aggregate over a design set, for the structure viewer's colour map. */
    async targetContactProfile(
        payload: TargetContactProfileRequestDto
    ): Promise<TargetContactProfileResponseDto> {
        return await apiRequest<TargetContactProfileResponseDto>(
            `${API_BASE}/api/filtering/target-contacts/profile`,
            { method: 'POST', body: JSON.stringify(payload), requireAuth: true }
        )
    },

    async preview(payload: FilteringPreviewRequestDto): Promise<FilteringPreviewResponseDto> {
        return await apiRequest<FilteringPreviewResponseDto>(`${API_BASE}/api/filtering/preview`, {
            method: 'POST',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    },

    async columns(runIds: string[]): Promise<FilteringColumnsResponseDto> {
        return await apiRequest<FilteringColumnsResponseDto>(`${API_BASE}/api/filtering/columns`, {
            method: 'POST',
            body: JSON.stringify({ run_ids: runIds }),
            requireAuth: true
        })
    },

    /**
     * Hard filters only (no ranking/diversity) — for live-narrowing the Designs table.
     * Cheap; meant to be called on a debounce as filters are edited (see plan §7A.2).
     */
    async apply(payload: FilteringApplyRequestDto): Promise<FilteringApplyResponseDto> {
        return await apiRequest<FilteringApplyResponseDto>(`${API_BASE}/api/filtering/apply`, {
            method: 'POST',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    },

    async run(payload: FilteringRunRequestDto): Promise<FilteringRunResponseDto> {
        return await apiRequest<FilteringRunResponseDto>(`${API_BASE}/api/filtering/run`, {
            method: 'POST',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    },

    /**
     * Hard filters + ranking, no diversity selection, no Saved Set persistence.
     * Backs the Filtering tab's explicit "Apply Ranking" button (not debounced). See
     * plan §7A.2.
     */
    async rank(payload: FilteringRankRequestDto): Promise<FilteringRankResponseDto> {
        return await apiRequest<FilteringRankResponseDto>(`${API_BASE}/api/filtering/rank`, {
            method: 'POST',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    },

    /**
     * Full filter+rank+diversity pipeline without persisting a Saved Set. Backs the
     * Filtering tab's explicit "Apply Diversity Filter" button. See plan §7A.2.
     */
    async diversity(payload: FilteringDiversityRequestDto): Promise<FilteringDiversityResponseDto> {
        return await apiRequest<FilteringDiversityResponseDto>(`${API_BASE}/api/filtering/diversity`, {
            method: 'POST',
            body: JSON.stringify(payload),
            requireAuth: true
        })
    }
}

export const savedSetsApi = {
    async list(): Promise<SavedSetListResponseDto> {
        return await apiRequest<SavedSetListResponseDto>(`${API_BASE}/api/saved-sets`, {
            requireAuth: true
        })
    },

    async get(savedSetId: string): Promise<SavedSetDto> {
        const enc = encodeURIComponent(savedSetId)
        return await apiRequest<SavedSetDto>(`${API_BASE}/api/saved-sets/${enc}`, {
            requireAuth: true
        })
    },

    async getDesigns(savedSetId: string): Promise<SavedSetDesignsResponseDto> {
        const enc = encodeURIComponent(savedSetId)
        return await apiRequest<SavedSetDesignsResponseDto>(
            `${API_BASE}/api/saved-sets/${enc}/designs`,
            { requireAuth: true }
        )
    },

    async delete(savedSetId: string): Promise<{ ok: boolean }> {
        const enc = encodeURIComponent(savedSetId)
        return await apiRequest<{ ok: boolean }>(`${API_BASE}/api/saved-sets/${enc}`, {
            method: 'DELETE',
            requireAuth: true
        })
    },

    /**
     * Rename a saved set. Sets are otherwise immutable snapshots (see plan §7A.4) —
     * this is the only allowed mutation.
     */
    async rename(savedSetId: string, name: string): Promise<SavedSetDto> {
        const enc = encodeURIComponent(savedSetId)
        return await apiRequest<SavedSetDto>(`${API_BASE}/api/saved-sets/${enc}`, {
            method: 'PATCH',
            body: JSON.stringify({ name }),
            requireAuth: true
        })
    },

    /**
     * Download URL for a saved set's ZIP (designs.csv + structure files).
     * A plain link/window.open target — auth is via cookies, no fetch needed.
     */
    getDownloadUrl(savedSetId: string): string {
        const enc = encodeURIComponent(savedSetId)
        return `${API_BASE}/api/saved-sets/${enc}/download`
    }
}

/**
 * Authentication APIs
 */
export interface DesktopInfo {
    desktop: boolean
    version: string
    data_dir: string
    run_base_dirs: string[]
    needs_setup: boolean
    webview_api: boolean
}

export interface RunBaseDirsResponse {
    run_base_dirs: string[]
    needs_setup: boolean
}

export const desktopApi = {
    async getInfo(): Promise<DesktopInfo> {
        return await apiRequest<DesktopInfo>(`${API_BASE}/api/desktop/info`, {
            requireAuth: false
        })
    },

    async putRunBaseDirs(runBaseDirs: string[]): Promise<RunBaseDirsResponse> {
        return await apiRequest<RunBaseDirsResponse>(`${API_BASE}/api/desktop/run-base-dirs`, {
            method: 'PUT',
            body: JSON.stringify({ run_base_dirs: runBaseDirs }),
            requireAuth: false
        })
    },

    async openDataDir(): Promise<{ ok: boolean; data_dir: string }> {
        return await apiRequest<{ ok: boolean; data_dir: string }>(
            `${API_BASE}/api/desktop/open-data-dir`,
            {
                method: 'POST',
                body: '{}',
                requireAuth: false
            }
        )
    }
}

/**
 * Shape of `GET /api/auth/me` (and the `user` field of login). Collapses the
 * duplicated `User` interfaces previously declared separately in this file and
 * in stores/auth.ts. All the user-model fields are optional since a bare
 * local-auth install predates the user model and won't populate them.
 */
export interface AuthUserDto {
    username: string
    provider?: string
    email?: string | null
    user_id?: number | null
    is_admin?: boolean
    auth_method?: 'session' | 'api_key'
    display_name?: string | null
    picture_url?: string | null
    last_login_at?: string | null
}

export interface AuthStatusDto {
    auth_disabled: boolean
    desktop_mode: boolean
    providers: {
        local: { enabled: boolean }
        pam: { enabled: boolean }
        google: { enabled: boolean; login_url: string }
    }
    api_keys: { enabled: boolean; reason?: string }
    mcp?: { enabled: boolean; path: string }
}

export const authApi = {
    /**
     * Login with username and password
     * @param username - Username
     * @param password - Password
     * @returns Promise with login response including CSRF token
     */
    async login(username: string, password: string): Promise<{
        message: string
        user: AuthUserDto
        csrf_token: string
    }> {
        const response = await apiRequest<{
            message: string
            user: AuthUserDto
            csrf_token: string
        }>(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            body: JSON.stringify({ username, password }),
            requireAuth: false
        })

        // Store CSRF token for future requests
        setCsrfToken(response.csrf_token)

        return response
    },

    /**
     * Logout user
     * @returns Promise with logout message
     */
    async logout(): Promise<{ message: string }> {
        const response = await apiRequest<{ message: string }>(`${API_BASE}/api/auth/logout`, {
            method: 'POST',
            requireAuth: true
        })

        // Clear CSRF token
        setCsrfToken(null)

        return response
    },

    /**
     * Get current user information
     * @returns Promise with user data
     */
    async getMe(): Promise<AuthUserDto> {
        return await apiRequest<AuthUserDto>(
            `${API_BASE}/api/auth/me`,
            { requireAuth: true }
        )
    },

    /**
     * Check authentication status
     * @returns Promise with auth status
     */
    async getStatus(): Promise<AuthStatusDto> {
        return await apiRequest<AuthStatusDto>(`${API_BASE}/api/auth/status`, { requireAuth: false })
    }
}

/**
 * Timestamps from the API are UTC but shaped `YYYY-MM-DD HH:MM:SS` (no `Z`/offset),
 * so `new Date(s)` would misparse them as local time. Callers needing a Date should
 * go via this helper rather than constructing one directly from the raw string.
 */
export function parseApiTimestamp(value: string): Date {
    return new Date(`${value.replace(' ', 'T')}Z`)
}

export interface ApiKeyDto {
    id: number
    name: string
    key_prefix: string
    created_at: string
    last_used_at: string | null
    expires_at: string | null
    revoked_at: string | null
    status: 'active' | 'expired' | 'revoked'
}

export interface CreatedApiKeyDto extends ApiKeyDto {
    /** Plaintext secret — present only on the response to the create call, never again. */
    key: string
}

export const apiKeysApi = {
    async list(): Promise<{ keys: ApiKeyDto[] }> {
        return await apiRequest<{ keys: ApiKeyDto[] }>(`${API_BASE}/api/api-keys`, {
            requireAuth: true
        })
    },

    async create(name: string, expiresInDays: number | null): Promise<CreatedApiKeyDto> {
        return await apiRequest<CreatedApiKeyDto>(`${API_BASE}/api/api-keys`, {
            method: 'POST',
            body: JSON.stringify({ name, expires_in_days: expiresInDays }),
            requireAuth: true
        })
    },

    async rename(id: number, name: string): Promise<ApiKeyDto> {
        return await apiRequest<ApiKeyDto>(`${API_BASE}/api/api-keys/${id}`, {
            method: 'PATCH',
            body: JSON.stringify({ name }),
            requireAuth: true
        })
    },

    async revoke(id: number): Promise<MessageResponse> {
        return await apiRequest<MessageResponse>(`${API_BASE}/api/api-keys/${id}`, {
            method: 'DELETE',
            requireAuth: true
        })
    }
}

// --- Download bundles ------------------------------------------------------------

export interface BundleDesignKeyDto {
    run_id: string
    design_id: string
    source_path?: string | null
}

export interface BundleRequestDto {
    keys: BundleDesignKeyDto[]
    run_ids: string[]
    label?: string
    include_heavy?: boolean
    session?: Record<string, any> | null
    client_columns?: Record<string, Record<string, any>>
    include?: {
        designs_table?: boolean
        binder_fasta?: boolean
        structures?: boolean
        target_contacts?: boolean
        session?: boolean
    }
}

export interface PrepareBundleRequestDto extends BundleRequestDto {
    prepared: Record<string, any>
}

export interface BundleEstimateDto {
    design_count: number
    structure_count: number
    structures_missing: number
    structure_bytes: number
    estimated_zip_bytes: number
    contacts_rows: number
    designs_with_contacts: number
    max_structure_files: number
    max_structure_bytes: number
    max_total_bytes: number
    exceeds_cap: boolean
    cap_messages: string[]
    warnings: string[]
}

async function postForBlob(url: string, body: unknown): Promise<Blob> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    const token = getCsrfToken()
    if (token) headers['X-CSRF-Token'] = token

    const response = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        credentials: 'include'
    })

    if (!response.ok) {
        if (response.status === 401) throw new Error('Authentication required')
        // 413 carries a structured estimate; surface the measured size rather than a bare code.
        let detail = ''
        try {
            const payload = await response.json()
            detail =
                typeof payload?.detail === 'string'
                    ? payload.detail
                    : payload?.detail?.message ?? ''
        } catch (_) {
            // Non-JSON error body; fall through to the status code.
        }
        throw new Error(detail || `Download failed (HTTP ${response.status})`)
    }

    return await response.blob()
}

export const bundlesApi = {
    async estimate(request: BundleRequestDto): Promise<BundleEstimateDto> {
        return await apiRequest<BundleEstimateDto>(`${API_BASE}/api/bundles/estimate`, {
            method: 'POST',
            body: JSON.stringify(request),
            requireAuth: true
        })
    },

    async downloadDesignsBundle(request: BundleRequestDto): Promise<Blob> {
        return await postForBlob(`${API_BASE}/api/bundles/designs`, request)
    },

    async downloadPrepareBundle(request: PrepareBundleRequestDto): Promise<Blob> {
        return await postForBlob(`${API_BASE}/api/bundles/prepare-sequences`, request)
    }
}

/**
 * Default export with all API modules
 */
export default {
    tree: treeApi,
    runs: runsApi,
    designs: designsApi,
    sequences: sequencesApi,
    plots: plotsApi,
    filtering: filteringApi,
    savedSets: savedSetsApi,
    auth: authApi,
    apiKeys: apiKeysApi,
    desktop: desktopApi,
    bundles: bundlesApi
}
