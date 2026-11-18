/**
 * Filtering Store
 * Boltzgen-style filter/rank/diversity-selection state and Saved Sets management.
 * See .cursor/plans/boltzgen_filtering_ui.plan.md §7A for the redesign this
 * implements: run scope comes from `useDesignsStore().selectedRunIds` (no separate
 * run picker here — see plan §7A.2), hard filters are debounced and live-narrow the
 * Designs table via `passingDesignKeys`, and ranking/diversity are explicit actions
 * that populate `rankedDesigns`.
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import {
    EMPTY_FILTER_OPERATORS,
    STRING_FILTER_OPERATORS,
    filteringApi,
    savedSetsApi
} from '../webapi'
import type {
    ColumnInfoDto,
    DesignKeyDto,
    FilterSpecDto,
    FilteringPreviewResponseDto,
    FilteringRunRequestDto,
    FilteringRunResponseDto,
    RankingMetricDto,
    SavedSetDto,
    SizeBucketDto,
    TargetContactCoverageDto,
    TargetContactFilterSpecDto,
    TargetContactGroupDto,
    TargetContactProfileRequestDto,
    TargetContactProfileResponseDto,
    TargetInfoDto
} from '../webapi'
import { buildDesignKey } from '../utils/designKey'
import { useDesignsStore } from './designs'
import { PERSISTENCE_KEYS } from '../persistence/keys'
import { kvGet, kvSet } from '../persistence/store'
import {
    DEFAULT_RANKING_METRICS,
    DEFAULT_RANKING_MODE,
    type RankingMode
} from '../config/rankingPresets'

/** Debounce window for hard-filter round-trips (see plan §7A.2 — cheap, ~0.16s/60k rows). */
const APPLY_DEBOUNCE_MS = 300

/** Debounce window for persisting filter/ranking/diversity config to IndexedDB. */
const PERSIST_DEBOUNCE_MS = 400

/**
 * Designs per target-contact compute request. Sized to keep the process pool busy while
 * still advancing the progress bar every few seconds; a failure only redoes this many.
 */
const CONTACTS_BATCH_SIZE = 32

export interface RankedDesignInfo {
    final_rank: number | null
    quality_score: number | null
}

/** Enabled ranking metrics plus mode — what the rank and diversity endpoints receive. */
interface RankingRecipe {
    mode: RankingMode
    metrics: Array<Pick<RankingMetricDto, 'column' | 'weight' | 'higher_is_better'>>
}

export interface FilterChainItem {
    index: number
    type: 'filter' | 'diversity' | 'target_contact' | 'mpnn'
    /** For target-contact rows: which group the row belongs to. */
    groupIndex?: number
    /** Pre-rendered stage description; target-contact rows have no meaningful column. */
    label?: string
    column: string
    operator: string
    threshold: number | null
    text_value: string | null
    enabled: boolean
    remaining: number | null
}

export const useFilteringStore = defineStore('filtering', () => {
    // Available columns (union across the active Designs-tab run scope)
    const availableColumns = ref<ColumnInfoDto[]>([])
    const columnsLoading = ref(false)
    const columnsError = ref<string | null>(null)

    // Filter set configuration
    const filters = ref<FilterSpecDto[]>([])

    // Target-contact conditions, one group per target (see backend TargetContactGroup):
    // a design is only constrained by the group written against its own target, which is
    // how equivalent residues under different numbering are expressed.
    const targetContactGroups = ref<TargetContactGroupDto[]>([])
    const targets = ref<TargetInfoDto[]>([])
    const targetCoverage = ref<TargetContactCoverageDto[]>([])
    const targetsLoading = ref(false)
    const targetsError = ref<string | null>(null)
    const contactsComputeProgress = ref<{ done: number; total: number; running: boolean }>({
        done: 0,
        total: 0,
        running: false
    })
    const contactsComputeError = ref<string | null>(null)
    // Fresh sessions (no persisted/loaded state) start with a single iptm@1.0 metric
    // rather than an empty list — see setRankingMetrics/RANKING_PRESETS for the
    // "iptm"/"BoltzGen" preset dropdown that can replace this.
    const rankingMode = ref<RankingMode>(DEFAULT_RANKING_MODE)
    const rankingMetrics = ref<RankingMetricDto[]>(DEFAULT_RANKING_METRICS.map((m) => ({ ...m })))
    const budget = ref<number>(24)
    // Quality only. BoltzGen's own defaults (0.001 protein, 0.01 peptide) stay as
    // slider marks, not the starting value.
    const alpha = ref<number>(0)
    const sizeBuckets = ref<SizeBucketDto[]>([])

    // Live-filter result: null = no active filter (show everything); otherwise the set
    // of design keys (see utils/designKey.ts) that pass the current hard filters.
    // Kept as plain reactive state (not fused into a single fetch-and-filter action) so
    // a future client-side-only path could populate it without a network round-trip —
    // see plan §7A.2's "keep the door open" constraint.
    const passingDesignKeys = ref<Set<string> | null>(null)
    const applyLoading = ref(false)
    const applyError = ref<string | null>(null)
    let applyDebounceTimer: ReturnType<typeof setTimeout> | null = null
    let applySeq = 0

    // Ranking result (from "Apply Ranking" or "Apply Diversity Filter"), keyed the same way.
    const rankedDesigns = ref<Map<string, RankedDesignInfo> | null>(null)
    const rankLoading = ref(false)
    const rankError = ref<string | null>(null)

    const diversityLoading = ref(false)
    const diversityError = ref<string | null>(null)
    const lastDiversityResult = ref<{ passing_filters: number; diverse_set_count: number; total_designs: number; warnings: string[] } | null>(null)

    // The raw diverse subset from the last "Apply Diversity Filter" run, kept separate
    // from `passingDesignKeys` (which reflects hard filters only) so the diversity step
    // can be toggled off — reverting to the hard-filter-only set — without re-running
    // the (slow, pairwise-alignment-based) diversity selection.
    const diverseDesignKeys = ref<Set<string> | null>(null)
    // Master on/off for diversity selection — shared by section 4's toggle and the
    // cascade tag. Default off: creating a Saved Set takes every design that passed
    // the hard filters (no budget). Turning it on without applying (or after editing
    // budget/α/buckets, the MPNN checkbox, or the ranking recipe) is the "dirty"
    // state the panel paints with a red border.
    const diversityEnabled = ref(false)
    const diversityAppliedSnapshot = ref<{
        budget: number
        alpha: number
        sizeBuckets: SizeBucketDto[]
        bestMpnnOnly: boolean
        ranking: RankingRecipe
    } | null>(null)
    // Last ranking recipe written into rankedDesigns (Apply Ranking, or Apply
    // Diversity Filter, which re-ranks before it selects).
    const rankingAppliedSnapshot = ref<RankingRecipe | null>(null)

    // Preview (filter cascade) — unchanged behaviour, now against designsStore.selectedRunIds
    const previewResult = ref<FilteringPreviewResponseDto | null>(null)
    const previewLoading = ref(false)
    const previewError = ref<string | null>(null)

    // Create Saved Set
    const creatingSavedSet = ref(false)
    const createSavedSetError = ref<string | null>(null)
    const lastCreatedSavedSet = ref<FilteringRunResponseDto | null>(null)

    // Saved Sets list
    const savedSets = ref<SavedSetDto[]>([])
    const savedSetsLoading = ref(false)
    const savedSetsError = ref<string | null>(null)

    // Looked up lazily (not at store-setup time) to avoid a circular-init issue: this
    // store's activeRunIds reads designsStore.selectedRunIds, and designsStore in turn
    // needs to consult this store's passingDesignKeys/rankedDesigns when computing
    // filteredDesigns — see stores/designs.ts.
    const activeRunIds = computed(() => useDesignsStore().selectedRunIds)
    const hasSelectedRuns = computed(() => activeRunIds.value.length > 0)

    // `enabled` (default true) is a local UI-only toggle so a row can be turned off
    // without deleting it — never sent to the backend. These computed views strip it
    // and drop disabled rows, and are what every outgoing request body is built from.
    const activeFilters = computed<FilterSpecDto[]>(() =>
        filters.value
            .filter((f) => f.enabled !== false)
            .map(({ column, operator, threshold, text_value }) => ({ column, operator, threshold, text_value }))
    )
    const activeRankingMetrics = computed<RankingMetricDto[]>(() =>
        rankingMetrics.value
            .filter((m) => m.enabled !== false)
            .map(({ column, weight, higher_is_better }) => ({ column, weight, higher_is_better }))
    )

    const rankingRecipe = (): RankingRecipe => ({
        mode: rankingMode.value,
        metrics: activeRankingMetrics.value.map((m) => ({
            column: m.column,
            weight: m.weight,
            higher_is_better: m.higher_is_better
        }))
    })

    // Enabled-only view of the contact groups, with the UI-only `enabled` flag stripped
    // and empty groups dropped — the shape the backend expects.
    const activeTargetContactGroups = computed<TargetContactGroupDto[]>(() =>
        targetContactGroups.value
            .map((group) => ({
                target_key: group.target_key,
                run_ids: group.run_ids ?? [],
                label: group.label ?? null,
                filters: group.filters
                    .filter((f) => f.enabled !== false && f.residues.length > 0)
                    .map(({ enabled, ...spec }) => spec)
            }))
            .filter((group) => group.filters.length > 0)
    )

    const hasActiveFilters = computed(
        () => activeFilters.value.length > 0 || activeTargetContactGroups.value.length > 0
    )

    const hasMultipleTargets = computed(() => targets.value.length > 1)

    /** Runs in scope that still need target contacts computed, for the coverage banner. */
    const runsMissingContacts = computed(() =>
        targetCoverage.value.filter((c) => c.computed_designs < c.total_designs)
    )
    const hasUncomputedContacts = computed(() => runsMissingContacts.value.length > 0)
    const contactCoverageTotals = computed(() =>
        targetCoverage.value.reduce(
            (acc, c) => ({
                computed: acc.computed + c.computed_designs,
                total: acc.total + c.total_designs
            }),
            { computed: 0, total: 0 }
        )
    )

    // Indices of enabled ranking-metric rows whose column isn't in availableColumns —
    // i.e. no currently-selected run's method has any non-null value for it (see
    // backend compute_available_columns, which already excludes entirely-null columns,
    // so "absent from availableColumns" covers both "doesn't exist" and "exists but is
    // all null/NA for this run scope"). Most likely to fire when applying a
    // method-specific preset (e.g. "BoltzGen") to a run of a different method — see
    // RANKING_PRESETS in config/rankingPresets.ts. Empty while columns are still loading
    // or no runs are selected, to avoid false positives before data arrives.
    const rankingMetricWarnings = computed<number[]>(() => {
        if (!hasSelectedRuns.value || columnsLoading.value) return []
        const known = new Set(availableColumns.value.map((c) => c.name))
        return rankingMetrics.value
            .map((m, idx) => (m.enabled !== false && m.column && !known.has(m.column) ? idx : -1))
            .filter((idx) => idx >= 0)
    })

    const canCreateSavedSet = computed(
        () =>
            hasSelectedRuns.value &&
            !creatingSavedSet.value &&
            (!diversityEnabled.value || budget.value > 0)
    )

    /** True when diversity is on but settings have not been applied (or have changed since). */
    const diversityDirty = computed(() => {
        if (!diversityEnabled.value) return false
        const snap = diversityAppliedSnapshot.value
        if (!snap) return true
        return (
            snap.budget !== budget.value ||
            snap.alpha !== alpha.value ||
            JSON.stringify(snap.sizeBuckets) !== JSON.stringify(sizeBuckets.value) ||
            snap.bestMpnnOnly !== useDesignsStore().bestMpnnOnly ||
            JSON.stringify(snap.ranking) !== JSON.stringify(rankingRecipe())
        )
    })

    /** True when the Ranking column was applied and the metrics or mode have since changed. */
    const rankingDirty = computed(
        () =>
            rankedDesigns.value != null &&
            rankingAppliedSnapshot.value != null &&
            JSON.stringify(rankingAppliedSnapshot.value) !== JSON.stringify(rankingRecipe())
    )

    // Total designs before any hard filter — same DataFrame the cascade counts below
    // derive from (previewResult always covers the full active run scope, even with
    // zero filters configured — see runPreview).
    const initialDesignCount = computed<number | null>(() => previewResult.value?.total_designs ?? null)

    // The key set that actually narrows the Designs table: diversity selection's result
    // when it has been run, is still enabled, and settings match the last apply; else
    // the hard-filter-only set. Toggling diversity off (or editing budget/α/buckets,
    // the MPNN checkbox, or the ranking recipe) reverts here without discarding the
    // cached diverse subset until the next apply.
    const effectivePassingKeys = computed<Set<string> | null>(() =>
        diversityEnabled.value && !diversityDirty.value && diverseDesignKeys.value
            ? diverseDesignKeys.value
            : passingDesignKeys.value
    )

    // Per-filter cascade, positioned for UI consumers that render the filter list as a
    // chain (FilterChainSummary.vue, and FilterSetBuilder.vue's cascade table). Each row
    // pairs a configured filter (including disabled ones) with the "designs remaining"
    // count after that stage — per_filter_counts is computed server-side from
    // activeFilters (enabled-only, same relative order), so it's zipped positionally
    // against just the enabled rows here. Guarded by a length check so a stale
    // (pre-debounce) preview doesn't get paired with the wrong filter while an edit is
    // in flight. If diversity selection has been run, it's appended as a
    // separately-toggleable stage (see diversityEnabled). "Keep only best MPNN
    // variant per backbone" collapses before that (and only while diversity
    // selection is on) — see designsStore.mpnnDedupeRemaining.
    const filterChain = computed<FilterChainItem[]>(() => {
        const stages = previewResult.value?.per_filter_counts ?? []
        // The backend appends target-contact stages after the plain hard filters (see
        // service.build_filter_inputs), so the positional zip below must expect both.
        const enabledCount =
            filters.value.filter((f) => f.enabled !== false).length +
            targetContactGroups.value.reduce(
                (n, g) => n + g.filters.filter((f) => f.enabled !== false && f.residues.length > 0).length,
                0
            )
        const stagesMatch = stages.length === enabledCount
        let stageIdx = 0
        const items: FilterChainItem[] = filters.value.map((filter, index) => {
            const enabled = filter.enabled !== false
            let remaining: number | null = null
            if (enabled) {
                remaining = stagesMatch ? stages[stageIdx].remaining : null
                stageIdx += 1
            }
            return {
                index,
                type: 'filter',
                column: filter.column,
                operator: filter.operator,
                threshold: filter.threshold ?? null,
                text_value: filter.text_value ?? null,
                enabled,
                remaining
            }
        })
        targetContactGroups.value.forEach((group, groupIndex) => {
            group.filters.forEach((filter, filterIndex) => {
                const enabled = filter.enabled !== false && filter.residues.length > 0
                let remaining: number | null = null
                if (enabled) {
                    remaining = stagesMatch ? stages[stageIdx]?.remaining ?? null : null
                    stageIdx += 1
                }
                items.push({
                    index: filterIndex,
                    groupIndex,
                    type: 'target_contact',
                    column: group.label ?? 'Target contacts',
                    operator: '',
                    threshold: null,
                    text_value: null,
                    label: stagesMatch ? stages[stageIdx - 1]?.label ?? undefined : undefined,
                    enabled,
                    remaining
                })
            })
        })

        // Before diversity selection: collapse MPNN variants on the hard-filter
        // set. Shown whenever that collapse is on, including before diversity
        // has been applied — then the final count is this row.
        const designsStore = useDesignsStore()
        if (designsStore.bestMpnnOnly && diversityEnabled.value) {
            items.push({
                index: -2,
                type: 'mpnn',
                column: 'Remove MPNN duplicates',
                label: 'Remove MPNN duplicates',
                operator: '',
                threshold: null,
                text_value: null,
                enabled: true,
                remaining: designsStore.mpnnDedupeRemaining
            })
        }

        // Show once the user has turned diversity on (even before apply) or has a
        // cached result they can re-enable — keeps the cascade tag in lock-step with
        // section 4's toggle.
        if (diversityEnabled.value || lastDiversityResult.value) {
            const applied =
                diversityEnabled.value &&
                !diversityDirty.value &&
                lastDiversityResult.value != null
            items.push({
                index: -1,
                type: 'diversity',
                column: 'Diversity Selection',
                operator: `budget=${budget.value}, α=${alpha.value}`,
                threshold: null,
                text_value: null,
                enabled: diversityEnabled.value,
                // Only counts as narrowing the cascade while enabled *and* applied —
                // matches disabled hard filters above (remaining=null), so cascade-
                // final-row logic that walks backward for the last non-null remaining
                // skips it when off or dirty.
                remaining: applied ? lastDiversityResult.value!.diverse_set_count : null
            })
        }
        return items
    })

    // --- Available columns ---

    const fetchAvailableColumns = async () => {
        if (!hasSelectedRuns.value) {
            availableColumns.value = []
            return
        }
        columnsLoading.value = true
        columnsError.value = null
        try {
            const res = await filteringApi.columns(activeRunIds.value)
            availableColumns.value = res.columns
        } catch (err) {
            columnsError.value = err instanceof Error ? err.message : 'Failed to load available columns'
            console.error('Error fetching filtering columns:', err)
        } finally {
            columnsLoading.value = false
        }
    }

    // --- Hard filters: debounced live-apply (see plan §7A.2) ---

    const runApplyNow = async () => {
        const seq = ++applySeq
        if (!hasSelectedRuns.value || !hasActiveFilters.value) {
            // No runs, or no filters configured — nothing to narrow by; show everything.
            passingDesignKeys.value = null
            applyLoading.value = false
            return
        }
        applyLoading.value = true
        applyError.value = null
        try {
            const res = await filteringApi.apply({
                run_ids: activeRunIds.value,
                filters: activeFilters.value,
                target_contact_groups: activeTargetContactGroups.value
            })
            if (seq !== applySeq) return
            passingDesignKeys.value = new Set(
                res.passing_keys.map((k) => buildDesignKey(k))
            )
        } catch (err) {
            if (seq !== applySeq) return
            applyError.value = err instanceof Error ? err.message : 'Failed to apply filters'
            console.error('Error applying filters:', err)
        } finally {
            if (seq === applySeq) applyLoading.value = false
        }
    }

    /**
     * Debounced entry point — call whenever a filter row (or its enabled toggle)
     * changes. Also re-runs the filter-cascade preview on the same debounce, so the
     * "Preview filter cascade" table stays in sync with live hard-filter edits instead
     * of needing a manual re-click.
     */
    const scheduleApply = () => {
        if (applyDebounceTimer) clearTimeout(applyDebounceTimer)
        applyDebounceTimer = setTimeout(() => {
            applyDebounceTimer = null
            void runApplyNow()
            void runPreview().catch(() => {
                /* surfaced via previewError; don't let it break the apply flow */
            })
        }, APPLY_DEBOUNCE_MS)
    }

    const flushApply = async () => {
        if (applyDebounceTimer) {
            clearTimeout(applyDebounceTimer)
            applyDebounceTimer = null
        }
        await Promise.all([
            runApplyNow(),
            runPreview().catch(() => {
                /* surfaced via previewError; don't let it break the apply flow */
            })
        ])
    }

    // --- Ranking / diversity: explicit actions, not debounced (see plan §7A.2) ---

    const applyRanking = async () => {
        if (!hasSelectedRuns.value) return
        rankLoading.value = true
        rankError.value = null
        try {
            const res = await filteringApi.rank({
                run_ids: activeRunIds.value,
                filters: activeFilters.value,
                target_contact_groups: activeTargetContactGroups.value,
                metrics: activeRankingMetrics.value,
                ranking_mode: rankingMode.value
            })
            const map = new Map<string, RankedDesignInfo>()
            for (const d of res.designs) {
                map.set(buildDesignKey(d), {
                    final_rank: d.final_rank ?? null,
                    quality_score: d.quality_score ?? null
                })
            }
            rankedDesigns.value = map
            rankingAppliedSnapshot.value = rankingRecipe()
            if (map.size > 0) useDesignsStore().presentBinderdashRanking()
        } catch (err) {
            rankError.value = err instanceof Error ? err.message : 'Failed to apply ranking'
            console.error('Error applying ranking:', err)
            throw err
        } finally {
            rankLoading.value = false
        }
    }

    const applyDiversityFilter = async () => {
        if (!hasSelectedRuns.value) return
        diversityLoading.value = true
        diversityError.value = null
        try {
            const res = await filteringApi.diversity({
                run_ids: activeRunIds.value,
                filters: activeFilters.value,
                target_contact_groups: activeTargetContactGroups.value,
                metrics: activeRankingMetrics.value,
                ranking_mode: rankingMode.value,
                budget: budget.value,
                alpha: alpha.value,
                size_buckets: sizeBuckets.value,
                best_mpnn_only: useDesignsStore().bestMpnnOnly
            })
            const rankMap = new Map<string, RankedDesignInfo>()
            const diverseKeys = new Set<string>()
            for (const d of res.designs) {
                const key = buildDesignKey(d)
                rankMap.set(key, {
                    final_rank: d.final_rank ?? null,
                    quality_score: d.quality_score ?? null
                })
                if (d.in_diverse_set) diverseKeys.add(key)
            }
            rankedDesigns.value = rankMap
            const appliedRanking = rankingRecipe()
            rankingAppliedSnapshot.value = appliedRanking
            if (rankMap.size > 0) useDesignsStore().presentBinderdashRanking()
            // Kept separate from passingDesignKeys (hard-filter-only) — see
            // effectivePassingKeys — so the step can be toggled off without discarding
            // the computed diverse subset.
            diverseDesignKeys.value = diverseKeys
            diversityEnabled.value = true
            diversityAppliedSnapshot.value = {
                budget: budget.value,
                alpha: alpha.value,
                sizeBuckets: sizeBuckets.value.map((b) => ({ ...b })),
                bestMpnnOnly: useDesignsStore().bestMpnnOnly,
                ranking: appliedRanking
            }
            lastDiversityResult.value = {
                passing_filters: res.passing_filters,
                diverse_set_count: res.diverse_set_count,
                total_designs: res.total_designs,
                warnings: res.warnings ?? []
            }
        } catch (err) {
            diversityError.value = err instanceof Error ? err.message : 'Failed to apply diversity filter'
            console.error('Error applying diversity filter:', err)
            throw err
        } finally {
            diversityLoading.value = false
        }
    }

    // --- Target contacts ---

    const fetchTargets = async () => {
        if (!hasSelectedRuns.value) {
            targets.value = []
            targetCoverage.value = []
            return
        }
        targetsLoading.value = true
        targetsError.value = null
        try {
            const res = await filteringApi.targetResidues(activeRunIds.value)
            targets.value = res.targets
            targetCoverage.value = res.coverage
            // A scope with exactly one target needs no target picker, so seed the single
            // group here rather than making the user choose from a list of one.
            if (targetContactGroups.value.length === 0 && res.targets.length === 1) {
                targetContactGroups.value = [
                    { target_key: res.targets[0].target_key, run_ids: [], label: res.targets[0].label, filters: [] }
                ]
            } else {
                reconcileTargetContactGroups(res.targets)
            }
        } catch (err) {
            targetsError.value = err instanceof Error ? err.message : 'Failed to load target residues'
            console.error('Error fetching target residues:', err)
        } finally {
            targetsLoading.value = false
        }
    }

    /**
     * Resolve design keys for the active run scope from the Designs store when the
     * caller does not supply them. Without this, Compute sends one empty-keys request
     * and the progress bar only jumps once the whole pool finishes.
     */
    const designKeysForActiveRuns = (): DesignKeyDto[] => {
        const runIds = new Set(activeRunIds.value)
        return useDesignsStore()
            .designs.filter((d) => runIds.has(String(d.run_id)))
            .map((d) => {
                const sp = (d as Record<string, unknown>).source_path
                return {
                    run_id: String(d.run_id),
                    design_id: String(d.design_id),
                    source_path: sp != null ? String(sp) : null
                }
            })
    }

    /**
     * Compute contact records for the runs in scope, in batches so the progress bar
     * advances and no single request runs long enough to time out. Sequential by
     * design: the backend already parallelises across a process pool internally.
     */
    const computeTargetContacts = async (designKeys?: DesignKeyDto[]) => {
        if (!hasSelectedRuns.value) return
        contactsComputeError.value = null
        const keys = designKeys?.length ? designKeys : designKeysForActiveRuns()
        const batches: DesignKeyDto[][] = []
        if (keys.length) {
            for (let i = 0; i < keys.length; i += CONTACTS_BATCH_SIZE) {
                batches.push(keys.slice(i, i + CONTACTS_BATCH_SIZE))
            }
        } else {
            // Designs table empty for this scope — fall back to one all-designs request.
            batches.push([])
        }

        const progressTotal = keys.length || 1
        contactsComputeProgress.value = { done: 0, total: progressTotal, running: true }
        try {
            for (const batch of batches) {
                const res = await filteringApi.computeTargetContacts({
                    run_ids: activeRunIds.value,
                    design_keys: batch
                })
                targetCoverage.value = res.coverage
                contactsComputeProgress.value = {
                    ...contactsComputeProgress.value,
                    done: Math.min(
                        progressTotal,
                        contactsComputeProgress.value.done + (batch.length || progressTotal)
                    )
                }
                if (res.errors.length && !contactsComputeError.value) {
                    contactsComputeError.value = res.errors.slice(0, 3).join('; ')
                }
            }
            await flushApply()
        } catch (err) {
            contactsComputeError.value =
                err instanceof Error ? err.message : 'Failed to compute target contacts'
            console.error('Error computing target contacts:', err)
            throw err
        } finally {
            contactsComputeProgress.value = { ...contactsComputeProgress.value, running: false }
        }
    }

    const fetchTargetContactProfile = async (
        payload: Omit<TargetContactProfileRequestDto, 'run_ids'> & { run_ids?: string[] }
    ): Promise<TargetContactProfileResponseDto> =>
        await filteringApi.targetContactProfile({
            ...payload,
            run_ids: payload.run_ids ?? activeRunIds.value
        })

    const isTargetInScope = (targetKey: string) =>
        targets.value.some((t) => t.target_key === targetKey)

    // Groups are restored from IndexedDB and outlive the run selection, so a group can
    // name a target that the current scope does not contain. Such a group matches no
    // runs: it silently filters nothing and its residue dropdown is empty. Re-point the
    // ones that have nothing to lose, and leave the rest for the user to resolve
    // (`staleTargetContactGroups` makes the target picker and a warning appear).
    const reconcileTargetContactGroups = (resolved: TargetInfoDto[]) => {
        if (resolved.length !== 1) return
        const only = resolved[0]
        targetContactGroups.value.forEach((group) => {
            if (group.target_key === only.target_key) return
            const hasSelections = group.filters.some((f) => f.residues.length > 0)
            if (hasSelections) return
            group.target_key = only.target_key
            group.label = only.label
        })
    }

    const staleTargetContactGroups = computed(() => {
        if (!targets.value.length) return new Set<number>()
        const stale = new Set<number>()
        targetContactGroups.value.forEach((group, index) => {
            if (!isTargetInScope(group.target_key)) stale.add(index)
        })
        return stale
    })

    const residuesForTarget = (targetKey: string) =>
        targets.value.find((t) => t.target_key === targetKey)?.residues ?? []

    const addTargetContactGroup = (targetKey?: string) => {
        const target = targets.value.find((t) => t.target_key === targetKey) ?? targets.value[0]
        targetContactGroups.value.push({
            target_key: target?.target_key ?? '',
            run_ids: [],
            label: target?.label ?? null,
            filters: []
        })
    }

    const removeTargetContactGroup = (groupIndex: number) => {
        targetContactGroups.value.splice(groupIndex, 1)
        scheduleApply()
    }

    const setTargetContactGroupTarget = (groupIndex: number, targetKey: string) => {
        const group = targetContactGroups.value[groupIndex]
        if (!group) return
        group.target_key = targetKey
        group.label = targets.value.find((t) => t.target_key === targetKey)?.label ?? null
        // Residue labels belong to the previous target's numbering, so they cannot carry
        // over: keep the rows but clear their selections.
        group.filters.forEach((filter) => {
            filter.residues = []
        })
        scheduleApply()
    }

    const addTargetContactFilter = (groupIndex: number) => {
        const group = targetContactGroups.value[groupIndex]
        if (!group) return
        group.filters.push({
            residues: [],
            scope: 'site_percent',
            metric: 'delta_sasa',
            distance_type: 'heavy',
            unit: 'percent',
            operator: '>=',
            value: 30,
            enabled: true
        })
    }

    const removeTargetContactFilter = (groupIndex: number, filterIndex: number) => {
        targetContactGroups.value[groupIndex]?.filters.splice(filterIndex, 1)
        scheduleApply()
    }

    const toggleTargetContactFilterEnabled = (groupIndex: number, filterIndex: number) => {
        const filter = targetContactGroups.value[groupIndex]?.filters[filterIndex]
        if (!filter) return
        filter.enabled = filter.enabled === false ? true : false
        scheduleApply()
    }

    // --- Reset / clear ---

    const clearAppliedFilters = () => {
        passingDesignKeys.value = null
        rankedDesigns.value = null
        useDesignsStore().dismissBinderdashRanking()
        applyError.value = null
        rankError.value = null
        diversityError.value = null
        lastDiversityResult.value = null
        diverseDesignKeys.value = null
        diversityAppliedSnapshot.value = null
        rankingAppliedSnapshot.value = null
        diversityEnabled.value = false
    }

    const disableAllFilters = () => {
        filters.value.forEach((filter) => {
            filter.enabled = false
        })
        targetContactGroups.value.forEach((group) => {
            group.filters.forEach((filter) => {
                filter.enabled = false
            })
        })
        scheduleApply()
    }

    const toggleFilterEnabled = (index: number) => {
        const filter = filters.value[index]
        if (!filter) return
        filter.enabled = filter.enabled === false ? true : false
        scheduleApply()
    }

    /** Toggle the diversity-selection stage on/off without re-running selection. */
    const toggleDiversityEnabled = () => {
        diversityEnabled.value = !diversityEnabled.value
    }

    const setDiversityEnabled = (enabled: boolean) => {
        diversityEnabled.value = enabled
    }

    // --- Preview (cascade) ---

    const runPreview = async () => {
        if (!hasSelectedRuns.value) {
            previewResult.value = null
            return
        }
        previewLoading.value = true
        previewError.value = null
        try {
            previewResult.value = await filteringApi.preview({
                run_ids: activeRunIds.value,
                filters: activeFilters.value,
                target_contact_groups: activeTargetContactGroups.value,
                metrics: activeRankingMetrics.value
            })
        } catch (err) {
            previewError.value = err instanceof Error ? err.message : 'Failed to run filter preview'
            console.error('Error running filtering preview:', err)
            throw err
        } finally {
            previewLoading.value = false
        }
    }

    // --- Filter/metric/bucket row editing ---

    const directionForColumn = (column: string): boolean | null => {
        const info = availableColumns.value.find((c) => c.name === column)
        const direction = info?.higher_is_better
        return typeof direction === 'boolean' ? direction : null
    }

    const defaultOperatorForColumn = (column: string): FilterSpecDto['operator'] => {
        // Match backend filtering.metrics.default_numeric_operator: ">" when known
        // higher-is-better, otherwise "<" (lower-is-better or unknown).
        return directionForColumn(column) === true ? '>' : '<'
    }

    const defaultHigherIsBetterForColumn = (column: string): boolean => {
        const direction = directionForColumn(column)
        return direction === null ? true : direction
    }

    const addFilter = () => {
        const firstColumn = availableColumns.value[0]?.name ?? ''
        filters.value.push({
            column: firstColumn,
            operator: defaultOperatorForColumn(firstColumn),
            threshold: 0,
            enabled: true
        })
        scheduleApply()
    }

    const removeFilter = (index: number) => {
        filters.value.splice(index, 1)
        scheduleApply()
    }

    /** Column picker changed: reset operator to one this column's dtype accepts. */
    const onFilterColumnChange = (index: number, column: string | null) => {
        const filter = filters.value[index]
        if (!filter) return
        filter.column = column ?? ''
        if (column) {
            const kind = columnKind(column)
            if (kind === 'boolean') {
                // good / bad / unrated. bad is the explicit false rating.
                filter.operator = 'equals'
                filter.text_value = 'true'
                filter.threshold = null
            } else if (kind === 'string') {
                const stringOps = new Set<string>([
                    ...STRING_FILTER_OPERATORS,
                    ...EMPTY_FILTER_OPERATORS
                ])
                if (column === 'tag' || !stringOps.has(filter.operator)) {
                    filter.operator = column === 'tag' ? 'equals' : 'contains'
                    filter.text_value = ''
                }
                filter.threshold = null
            } else {
                filter.operator = defaultOperatorForColumn(column)
                filter.text_value = null
                if (filter.threshold == null) filter.threshold = 0
            }
        }
        scheduleApply()
    }

    const columnKind = (column: string): 'numeric' | 'boolean' | 'string' => {
        const info = availableColumns.value.find((c) => c.name === column)
        if (!info) return 'numeric'
        const dtype = info.dtype.toLowerCase()
        if (dtype.includes('bool')) return 'boolean'
        if (dtype.includes('str') || dtype.includes('utf8')) return 'string'
        return 'numeric'
    }

    const addRankingMetric = () => {
        const firstColumn = availableColumns.value[0]?.name ?? ''
        rankingMetrics.value.push({
            column: firstColumn,
            weight: 1,
            higher_is_better: defaultHigherIsBetterForColumn(firstColumn),
            enabled: true
        })
    }

    const removeRankingMetric = (index: number) => {
        rankingMetrics.value.splice(index, 1)
    }

    /** Column picker changed: reset higher_is_better from known direction. */
    const onRankingColumnChange = (index: number, column: string | null) => {
        const metric = rankingMetrics.value[index]
        if (!metric) return
        metric.column = column ?? ''
        if (column) {
            metric.higher_is_better = defaultHigherIsBetterForColumn(column)
        }
    }

    /** Wholesale-replace the ranking metrics list — backs the presets dropdown
     * (RANKING_PRESETS in config/rankingPresets.ts). Clones so mutating a row afterwards
     * (e.g. tweaking a weight) doesn't touch the shared preset constant. */
    const setRankingMetrics = (metrics: RankingMetricDto[]) => {
        rankingMetrics.value = metrics.map((m) => ({ ...m }))
    }

    const addSizeBucket = () => {
        sizeBuckets.value.push({ min: 0, max: 100, num_designs: 5 })
    }

    const removeSizeBucket = (index: number) => {
        sizeBuckets.value.splice(index, 1)
    }

    // --- Saved Sets ---

    const fetchSavedSets = async () => {
        savedSetsLoading.value = true
        savedSetsError.value = null
        try {
            const res = await savedSetsApi.list()
            savedSets.value = res.saved_sets
        } catch (err) {
            savedSetsError.value = err instanceof Error ? err.message : 'Failed to load saved sets'
            console.error('Error fetching saved sets:', err)
        } finally {
            savedSetsLoading.value = false
        }
    }

    const createSavedSet = async (name: string): Promise<FilteringRunResponseDto> => {
        creatingSavedSet.value = true
        createSavedSetError.value = null
        try {
            // Dynamic import avoids a module cycle: sessionState imports this store.
            const { buildSessionState } = await import('../session/sessionState')
            const res = await filteringApi.run({
                name,
                run_ids: activeRunIds.value,
                filters: activeFilters.value,
                target_contact_groups: activeTargetContactGroups.value,
                metrics: activeRankingMetrics.value,
                ranking_mode: rankingMode.value,
                budget: budget.value,
                alpha: alpha.value,
                size_buckets: sizeBuckets.value,
                // Honour the same on/off as section 4 / the cascade tag — when off,
                // every design that passed the hard filters becomes the saved set
                // (no budget / lazy-greedy pass).
                apply_diversity: diversityEnabled.value,
                best_mpnn_only: useDesignsStore().bestMpnnOnly,
                // Table layout + best-MPNN preference ride along so a later download /
                // Reapply reproduces more than just the filter recipe.
                ui_state: buildSessionState()
            })
            lastCreatedSavedSet.value = res
            await fetchSavedSets()
            return res
        } catch (err) {
            createSavedSetError.value =
                err instanceof Error ? err.message : 'Failed to create saved set'
            console.error('Error creating saved set:', err)
            throw err
        } finally {
            creatingSavedSet.value = false
        }
    }

    const deleteSavedSet = async (savedSetId: string) => {
        try {
            await savedSetsApi.delete(savedSetId)
            savedSets.value = savedSets.value.filter((s) => s.id !== savedSetId)
        } catch (err) {
            savedSetsError.value = err instanceof Error ? err.message : 'Failed to delete saved set'
            console.error('Error deleting saved set:', err)
            throw err
        }
    }

    const resetFilterSet = () => {
        filters.value = []
        targetContactGroups.value = []
        rankingMode.value = DEFAULT_RANKING_MODE
        rankingMetrics.value = DEFAULT_RANKING_METRICS.map((m) => ({ ...m }))
        budget.value = 24
        alpha.value = 0
        sizeBuckets.value = []
        previewResult.value = null
        previewError.value = null
        lastCreatedSavedSet.value = null
        createSavedSetError.value = null
        clearAppliedFilters()
    }

    /**
     * Populate `filters`/`rankingMetrics`/`budget`/`alpha`/`sizeBuckets` from a
     * previously-saved filter recipe (a `SavedSet.filter_params`, which is a
     * serialized `FilteringRunRequest`). Deliberately does NOT touch `run_ids`/`name`
     * — run scope comes from `designsStore.selectedRunIds`, not the recipe (see plan
     * §7A.4 — called by the in-progress "reapply filters" button elsewhere).
     */
    const loadRecipe = (recipe: FilteringRunRequestDto): void => {
        // A saved recipe's filters/metrics never carry `enabled` (it's UI-only, never
        // sent to or stored by the backend — see activeFilters/activeRankingMetrics
        // above), so an absent flag means enabled. A session-state restore does carry
        // it, though, and reads back through here: honour it when present, or restoring
        // a session would silently re-enable rows the user had switched off.
        const wasEnabled = (row: { enabled?: boolean }) => row.enabled !== false
        filters.value = recipe.filters
            ? recipe.filters.map((f) => ({ ...f, enabled: wasEnabled(f) }))
            : []
        targetContactGroups.value = recipe.target_contact_groups
            ? recipe.target_contact_groups.map((g) => ({
                  ...g,
                  filters: g.filters.map((f) => ({ ...f, enabled: wasEnabled(f) }))
              }))
            : []
        rankingMetrics.value = recipe.metrics
            ? recipe.metrics.map((m) => ({ ...m, enabled: wasEnabled(m) }))
            : []
        // Recipes saved before ranking_mode existed always used worst-case rank.
        rankingMode.value =
            recipe.ranking_mode === 'simple' || recipe.ranking_mode === 'worst_rank'
                ? recipe.ranking_mode
                : 'worst_rank'
        budget.value = recipe.budget ?? 24
        alpha.value = recipe.alpha ?? 0
        sizeBuckets.value = recipe.size_buckets ? [...recipe.size_buckets] : []
        clearAppliedFilters()
        // Old recipes predate apply_diversity; they always ran diversity, so default on.
        // clearAppliedFilters resets the toggle to the fresh-UI default (off).
        diversityEnabled.value = recipe.apply_diversity !== false

        // ui_state is optional (sets created before it, or session restore which applies
        // best_mpnn_only itself). When present — Reapply / Load filters from a Saved Set —
        // restore the Designs-table preferences that rode along at save time.
        const ui = recipe.ui_state
        if (ui && typeof ui === 'object') {
            const designsStore = useDesignsStore()
            if (typeof ui.best_mpnn_only === 'boolean') {
                designsStore.bestMpnnOnly = ui.best_mpnn_only
            }
            if (Array.isArray(ui.sort) && ui.sort.length > 0) {
                designsStore.tableMultiSortMeta = ui.sort
                    .filter((s: any) => s && s.field)
                    .map((s: any) => ({
                        field: String(s.field),
                        order: s.order === -1 ? -1 : 1
                    }))
                designsStore.tableFirst = 0
            }
            if (Array.isArray(ui.visible_columns) && ui.visible_columns.length > 0) {
                designsStore.visibleColumns = ui.visible_columns.map(String)
            }
        }

        scheduleApply()
    }

    // --- Persistence (IndexedDB) — survive browser refresh; mirrors the pattern used
    // by the Designs tab's own view-state persistence (stores/designs.ts) and Plots'
    // scatter-axis preferences (stores/plots.ts). ---

    const filteringPersistenceHydrated = ref(false)
    let persistDebounceTimer: ReturnType<typeof setTimeout> | null = null

    const persistFilteringViewState = () => {
        if (!filteringPersistenceHydrated.value) return
        if (persistDebounceTimer) clearTimeout(persistDebounceTimer)
        persistDebounceTimer = setTimeout(() => {
            persistDebounceTimer = null
            void kvSet(PERSISTENCE_KEYS.filteringViewState, {
                filters: filters.value,
                targetContactGroups: targetContactGroups.value,
                rankingMode: rankingMode.value,
                rankingMetrics: rankingMetrics.value,
                budget: budget.value,
                alpha: alpha.value,
                sizeBuckets: sizeBuckets.value,
                diversityEnabled: diversityEnabled.value
            })
        }, PERSIST_DEBOUNCE_MS)
    }

    watch(
        [filters, targetContactGroups, rankingMode, rankingMetrics, budget, alpha, sizeBuckets, diversityEnabled],
        persistFilteringViewState,
        { deep: true }
    )

    const hydrateFromPersistence = async () => {
        try {
            const payload = await kvGet<{
                filters?: unknown
                targetContactGroups?: unknown
                rankingMode?: unknown
                rankingMetrics?: unknown
                budget?: unknown
                alpha?: unknown
                sizeBuckets?: unknown
                diversityEnabled?: unknown
            }>(PERSISTENCE_KEYS.filteringViewState)
            if (payload) {
                if (Array.isArray(payload.filters)) {
                    filters.value = payload.filters as FilterSpecDto[]
                }
                if (Array.isArray(payload.targetContactGroups)) {
                    targetContactGroups.value = payload.targetContactGroups as TargetContactGroupDto[]
                }
                if (payload.rankingMode === 'simple' || payload.rankingMode === 'worst_rank') {
                    rankingMode.value = payload.rankingMode
                }
                if (Array.isArray(payload.rankingMetrics)) {
                    rankingMetrics.value = payload.rankingMetrics as RankingMetricDto[]
                }
                if (typeof payload.budget === 'number') {
                    budget.value = payload.budget
                }
                if (typeof payload.alpha === 'number') {
                    alpha.value = payload.alpha
                }
                if (Array.isArray(payload.sizeBuckets)) {
                    sizeBuckets.value = payload.sizeBuckets as SizeBucketDto[]
                }
                if (typeof payload.diversityEnabled === 'boolean') {
                    diversityEnabled.value = payload.diversityEnabled
                }
            }
        } catch (e) {
            console.warn('Failed to hydrate filtering persistence from IndexedDB', e)
        } finally {
            filteringPersistenceHydrated.value = true
        }
    }

    return {
        // State
        availableColumns,
        columnsLoading,
        columnsError,
        filters,
        targetContactGroups,
        targets,
        targetCoverage,
        targetsLoading,
        targetsError,
        contactsComputeProgress,
        contactsComputeError,
        rankingMode,
        rankingMetrics,
        budget,
        alpha,
        sizeBuckets,
        passingDesignKeys,
        applyLoading,
        applyError,
        rankedDesigns,
        rankLoading,
        rankError,
        diversityLoading,
        diversityError,
        lastDiversityResult,
        diverseDesignKeys,
        diversityEnabled,
        diversityDirty,
        rankingDirty,
        previewResult,
        previewLoading,
        previewError,
        creatingSavedSet,
        createSavedSetError,
        lastCreatedSavedSet,
        savedSets,
        savedSetsLoading,
        savedSetsError,

        // Getters
        activeRunIds,
        columnKind,
        hasSelectedRuns,
        hasActiveFilters,
        activeTargetContactGroups,
        hasMultipleTargets,
        staleTargetContactGroups,
        isTargetInScope,
        runsMissingContacts,
        hasUncomputedContacts,
        contactCoverageTotals,
        rankingMetricWarnings,
        canCreateSavedSet,
        initialDesignCount,
        effectivePassingKeys,
        filterChain,

        // Actions
        fetchAvailableColumns,
        scheduleApply,
        flushApply,
        applyRanking,
        applyDiversityFilter,
        clearAppliedFilters,
        disableAllFilters,
        toggleFilterEnabled,
        toggleDiversityEnabled,
        setDiversityEnabled,
        runPreview,
        addFilter,
        removeFilter,
        onFilterColumnChange,
        fetchTargets,
        computeTargetContacts,
        fetchTargetContactProfile,
        residuesForTarget,
        addTargetContactGroup,
        removeTargetContactGroup,
        setTargetContactGroupTarget,
        addTargetContactFilter,
        removeTargetContactFilter,
        toggleTargetContactFilterEnabled,
        addRankingMetric,
        removeRankingMetric,
        onRankingColumnChange,
        setRankingMetrics,
        addSizeBucket,
        removeSizeBucket,
        fetchSavedSets,
        createSavedSet,
        deleteSavedSet,
        resetFilterSet,
        loadRecipe,
        hydrateFromPersistence
    }
})
