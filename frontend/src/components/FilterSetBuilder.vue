<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Panel from 'primevue/panel'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Select from 'primevue/select'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import Slider from 'primevue/slider'
import Tag from 'primevue/tag'
import ToggleSwitch from 'primevue/toggleswitch'
import Message from 'primevue/message'
import Checkbox from 'primevue/checkbox'
import { useToast } from 'primevue/usetoast'
import { useDesignsStore, useFilteringStore } from '../stores'
import { getMethodTagStyle } from '../config/pipelineDisplay'
import { RANKING_MODES, RANKING_PRESETS, rankingOrdinal } from '../config/rankingPresets'
import MetricColumnSelector from './MetricColumnSelector.vue'
import TargetContactFilters from './TargetContactFilters.vue'
import type { FilterSpecDto, RankingMetricDto } from '../webapi'
import type { InputNumberInputEvent } from 'primevue/inputnumber'
import { columnDisplayName } from '../utils/filterLabel'

const filteringStore = useFilteringStore()
const designsStore = useDesignsStore()
const toast = useToast()

// Operator sets mirror the backend FilterSpec superset (plan §7A.1) — numeric vs
// string vs empty-check, chosen per the selected column's dtype.
const NUMERIC_OPERATORS: { label: string; value: string }[] = [
  { label: '<  (lower is better)', value: '<' },
  { label: '≤', value: '<=' },
  { label: '>  (higher is better)', value: '>' },
  { label: '≥', value: '>=' }
]

const STRING_OPERATORS: { label: string; value: string }[] = [
  { label: 'contains', value: 'contains' },
  { label: 'does not contain', value: 'not_contains' },
  { label: 'starts with', value: 'starts_with' },
  { label: 'ends with', value: 'ends_with' },
  { label: 'equals', value: 'equals' },
  { label: 'not equals', value: 'not_equals' },
  { label: 'regex', value: 'regex' }
]

const EMPTY_OPERATORS: { label: string; value: string }[] = [
  { label: 'is empty', value: 'is_empty' },
  { label: 'is not empty', value: 'is_not_empty' }
]

function isNumericColumn(column: string): boolean {
  return filteringStore.columnKind(column) === 'numeric'
}

function isBooleanColumn(column: string): boolean {
  return filteringStore.columnKind(column) === 'boolean'
}

// Good is good / bad / unrated. The choice encodes operator + text_value; there is
// no separate threshold field. "true"/"false" match the engine's normalised text.
const GOOD_OPERATORS: { label: string; value: string }[] = [
  { label: 'good', value: 'good' },
  { label: 'bad', value: 'bad' },
  { label: 'unrated', value: 'unrated' }
]

function booleanChoice(filter: FilterSpecDto): string {
  if (filter.operator === 'is_empty') return 'unrated'
  if (filter.text_value === 'false') return 'bad'
  return 'good'
}

function applyBooleanChoice(filter: FilterSpecDto, choice: string) {
  if (choice === 'unrated') {
    filter.operator = 'is_empty'
    filter.text_value = null
  } else if (choice === 'bad') {
    filter.operator = 'equals'
    filter.text_value = 'false'
  } else {
    filter.operator = 'equals'
    filter.text_value = 'true'
  }
  filter.threshold = null
}

function operatorsForColumn(column: string): { label: string; value: string }[] {
  const base = isNumericColumn(column) ? NUMERIC_OPERATORS : STRING_OPERATORS
  return [...base, ...EMPTY_OPERATORS]
}

function isEmptyOperator(operator: string): boolean {
  return operator === 'is_empty' || operator === 'is_not_empty'
}

const savedSetName = ref('')

// Presets dropdown for "3. Ranking Metrics" — a one-shot action (replaces the whole
// list), not stored as its own persisted state. Its displayed value is derived from
// filteringStore.rankingMetrics itself (below), not tracked separately, so it stays
// accurate no matter how those metrics got there: the fresh-session default, a
// hydrated-from-IndexedDB previous session, or a loaded Saved Set recipe. It reverts
// to the empty placeholder once the metrics no longer match a preset for the current
// mode exactly (e.g. after editing a weight or the column order).
function metricsEqual(a: RankingMetricDto[], b: RankingMetricDto[]): boolean {
  return (
    a.length === b.length &&
    a.every((m, i) => m.column === b[i].column && m.weight === b[i].weight && m.higher_is_better === b[i].higher_is_better)
  )
}

const presetsForMode = computed(() =>
  RANKING_PRESETS.filter((p) => p.mode === filteringStore.rankingMode)
)

const selectedPreset = computed<string | null>(
  () => presetsForMode.value.find((p) => metricsEqual(filteringStore.rankingMetrics, p.metrics))?.key ?? null
)

/** Priority label for an enabled simple-ranking row (1st, 2nd, …), counting only
 * enabled rows above it. Disabled rows are not keys. */
function simplePriority(index: number): string | null {
  const metric = filteringStore.rankingMetrics[index]
  if (!metric || metric.enabled === false) return null
  const position = filteringStore.rankingMetrics
    .slice(0, index + 1)
    .filter((m) => m.enabled !== false).length
  return rankingOrdinal(position)
}

function handleApplyPreset(key: string | null) {
  const preset = RANKING_PRESETS.find((p) => p.key === key)
  if (!preset) return
  filteringStore.setRankingMetrics(preset.metrics)
  toast.add({ severity: 'success', summary: `"${preset.label}" preset applied`, life: 3000 })
}

onMounted(async () => {
  if (filteringStore.hasSelectedRuns) {
    await filteringStore.fetchAvailableColumns()
    await filteringStore.flushApply()
  }
})

watch(
  () => filteringStore.activeRunIds.slice().sort().join(','),
  async () => {
    filteringStore.previewResult = null
    filteringStore.clearAppliedFilters()
    await filteringStore.fetchAvailableColumns()
    await filteringStore.flushApply()
  }
)

const handlePreview = async () => {
  try {
    await filteringStore.runPreview()
  } catch (err) {
    toast.add({
      severity: 'error',
      summary: 'Preview failed',
      detail: err instanceof Error ? err.message : 'Unknown error',
      life: 6000
    })
  }
}

const handleApplyRanking = async () => {
  try {
    await filteringStore.applyRanking()
    toast.add({
      severity: 'success',
      summary: 'Ranking applied',
      detail: 'Designs table sorted by Ranking (binderdash_ranking, 1 = best).',
      life: 4000
    })
  } catch (err) {
    toast.add({
      severity: 'error',
      summary: 'Failed to apply ranking',
      detail: err instanceof Error ? err.message : 'Unknown error',
      life: 6000
    })
  }
}

const handleApplyDiversity = async () => {
  try {
    await filteringStore.applyDiversityFilter()
    const res = filteringStore.lastDiversityResult
    const warnings = res?.warnings ?? []
    toast.add({
      // A diverse set short of the budget (usually designs with no sequence) must not
      // be reported as an unqualified success — that's how it went unnoticed before.
      severity: warnings.length ? 'warn' : 'success',
      summary: warnings.length ? 'Diversity filter applied with warnings' : 'Diversity filter applied',
      detail: res
        ? [
            `${res.diverse_set_count} diverse designs selected from ${res.passing_filters} passing filters (of ${res.total_designs} total).`,
            ...warnings
          ].join(' ')
        : undefined,
      life: warnings.length ? 12000 : 8000
    })
  } catch (err) {
    toast.add({
      severity: 'error',
      summary: 'Failed to apply diversity filter',
      detail: err instanceof Error ? err.message : 'Unknown error',
      life: 6000
    })
  }
}

// InputNumber only emits `update:model-value` on blur/Enter, not per keystroke —
// its `input` event fires live as the user types, so use that to keep the debounced
// apply in sync without requiring the field to lose focus.
const handleThresholdInput = (filter: FilterSpecDto, event: InputNumberInputEvent) => {
  filter.threshold = typeof event.value === 'number' ? event.value : null
  filteringStore.scheduleApply()
}

const handleDisableAllFilters = () => {
  filteringStore.disableAllFilters()
  toast.add({ severity: 'info', summary: 'All filters disabled', life: 3000 })
}

const handleDiversityEnabledChange = (enabled: boolean) => {
  filteringStore.setDiversityEnabled(enabled)
  toast.add({
    severity: 'info',
    summary: enabled ? 'Diversity selection enabled' : 'Diversity selection disabled',
    life: 3000
  })
}

const handleCreateSavedSet = async () => {
  const name = savedSetName.value.trim()
  if (!name) {
    toast.add({ severity: 'warn', summary: 'Name required', detail: 'Give the saved set a name.', life: 4000 })
    return
  }
  try {
    const res = await filteringStore.createSavedSet(name)
    const warnings = res.warnings ?? []
    toast.add({
      severity: warnings.length ? 'warn' : 'success',
      summary: warnings.length ? 'Saved set created with warnings' : 'Saved set created',
      detail: [
        `"${res.name}": ${res.diverse_set_count} designs selected from ${res.passing_filters} passing filters (of ${res.total_input} total).`,
        ...warnings
      ].join(' '),
      life: warnings.length ? 12000 : 8000
    })
    savedSetName.value = ''
  } catch (err) {
    toast.add({
      severity: 'error',
      summary: 'Failed to create saved set',
      detail: err instanceof Error ? err.message : 'Unknown error',
      life: 6000
    })
  }
}

const formatSampleRange = (col: { sample_values?: { min: number; max: number } | null }) => {
  if (!col.sample_values) return '—'
  return `${col.sample_values.min.toFixed(2)} – ${col.sample_values.max.toFixed(2)}`
}

const formatEquivalentColumns = (col: { raw_columns?: Record<string, string> }) => {
  if (!col.raw_columns || Object.keys(col.raw_columns).length === 0) return '—'
  return Object.entries(col.raw_columns)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([method, raw]) => `${method}: ${raw}`)
    .join(', ')
}

interface CascadeRow {
  column: string
  operator: string
  threshold: number | null
  remaining: number | null
  enabled: boolean
  isFinal: boolean
  isDiversity: boolean
  isMpnn: boolean
}

// Every configured filter is listed (including disabled ones), plus diversity
// selection once it's been run, plus MPNN duplicate removal when that collapse
// is on — all sourced from filteringStore's shared filterChain (see
// stores/filtering.ts) so this table and the top-of-page FilterChainSummary
// chain never drift apart. "Final set" is always its own trailing summary row
// — no threshold, and its remaining count mirrors whichever stage above it
// last actually narrowed the set (diversity selection if applied and enabled,
// else MPNN duplicate removal when that step is on, else the last enabled
// filter, else the unfiltered total when nothing is configured/enabled).
const cascadeRows = computed<CascadeRow[]>(() => {
  const rows: CascadeRow[] = filteringStore.filterChain.map((item) => ({
    column: item.label ?? item.column,
    operator: item.operator,
    threshold: item.threshold,
    remaining: item.remaining,
    enabled: item.enabled,
    isFinal: false,
    isDiversity: item.type === 'diversity',
    isMpnn: item.type === 'mpnn'
  }))

  let finalRemaining = filteringStore.initialDesignCount ?? 0
  for (let i = rows.length - 1; i >= 0; i--) {
    if (rows[i].remaining != null) {
      finalRemaining = rows[i].remaining as number
      break
    }
  }
  rows.push({
    column: 'Final set',
    operator: '',
    threshold: null,
    remaining: finalRemaining,
    enabled: true,
    isFinal: true,
    isDiversity: false,
    isMpnn: false
  })

  return rows
})

function cascadeRowClass(data: CascadeRow) {
  return {
    'fsb-cascade-row--final': data.isFinal,
    'fsb-cascade-row--disabled': !data.enabled,
    'fsb-cascade-row--diversity': data.isDiversity,
    'fsb-cascade-row--mpnn': data.isMpnn
  }
}

// Alpha (quality<->diversity trade-off) is meaningful across orders of magnitude near
// zero — BoltzGen's own defaults are 0.001/0.01 (see docs quoted below) — so a linear
// 0-1 slider leaves almost no usable range near the defaults. Driven on a log10 scale
// instead, from 1e-4 (as close to "quality only" as the slider goes) up to 1.0
// ("diversity only"); exact values (including 0) are still enterable via the InputNumber.
const ALPHA_LOG_MIN = -4
const ALPHA_LOG_MAX = 0
const ALPHA_MARKS: { value: number; label: string }[] = [
  { value: 0.001, label: 'protein (0.001)' },
  { value: 0.01, label: 'peptide (0.01)' }
]

function alphaMarkPosition(value: number): number {
  return ((Math.log10(value) - ALPHA_LOG_MIN) / (ALPHA_LOG_MAX - ALPHA_LOG_MIN)) * 100
}

const alphaLogSlider = computed<number>({
  get: () => Math.log10(Math.max(filteringStore.alpha, 10 ** ALPHA_LOG_MIN)),
  set: (v: number) => {
    filteringStore.alpha = Math.round(10 ** v * 1e6) / 1e6
  }
})
</script>

<template>
  <div class="filter-set-builder">
    <Panel v-if="!filteringStore.hasSelectedRuns" header="Source Runs" class="fsb-panel">
      <p class="fsb-hint">
        No runs selected. Run scope for filtering comes from the <strong>Select
        Runs</strong> tab — pick one or more runs there, and they'll be pooled together
        here for filtering/ranking/diversity selection.
      </p>
    </Panel>

    <Panel v-if="filteringStore.hasSelectedRuns" header="Available Metrics" class="fsb-panel" toggleable collapsed>
      <div v-if="filteringStore.columnsLoading" class="fsb-hint">Loading columns…</div>
      <Message v-else-if="filteringStore.columnsError" severity="error" :closable="false">
        {{ filteringStore.columnsError }}
      </Message>
      <DataTable
        v-else
        :value="filteringStore.availableColumns"
        size="small"
        data-key="name"
        class="fsb-columns-table"
      >
        <Column field="name" header="Column" sortable>
          <template #body="{ data }">{{ columnDisplayName(data.name) }}</template>
        </Column>
        <Column field="canonical_name" header="Canonical" sortable>
          <template #body="{ data }">
            <Tag v-if="data.canonical_name" :value="data.canonical_name" severity="info" />
            <span v-else>—</span>
          </template>
        </Column>
        <Column header="Present in runs (method)">
          <template #body="{ data }">
            <Tag
              v-for="method in data.present_in_runs"
              :key="method"
              :value="method"
              :style="getMethodTagStyle(method)"
              class="pipeline-palette-tag fsb-method-tag"
            />
          </template>
        </Column>
        <Column header="Equivalent columns">
          <template #body="{ data }">{{ formatEquivalentColumns(data) }}</template>
        </Column>
        <Column header="Range">
          <template #body="{ data }">{{ formatSampleRange(data) }}</template>
        </Column>
      </DataTable>
    </Panel>

    <Panel v-if="filteringStore.hasSelectedRuns" header="1. Hard Filters" class="fsb-panel">
      <p class="fsb-hint">
        Every design must pass all filters to be counted as "passing". Filters are
        applied live to the Designs table.
      </p>
      <div
        v-for="(filter, idx) in filteringStore.filters"
        :key="idx"
        class="fsb-filter-row"
        :class="{ 'fsb-row--disabled': filter.enabled === false }"
      >
        <ToggleSwitch
          v-model="filter.enabled"
          :true-value="true"
          :false-value="false"
          aria-label="Enable filter"
          class="fsb-row__enable-toggle"
          @update:model-value="filteringStore.scheduleApply()"
        />
        <MetricColumnSelector
          v-model="filter.column"
          :columns="filteringStore.availableColumns"
          :disabled="filter.enabled === false"
          class="fsb-filter-row__column"
          @update:model-value="filteringStore.onFilterColumnChange(idx, $event)"
        />
        <Select
          v-if="isBooleanColumn(filter.column)"
          :model-value="booleanChoice(filter)"
          :options="GOOD_OPERATORS"
          option-label="label"
          option-value="value"
          :disabled="filter.enabled === false"
          class="fsb-filter-row__operator"
          @update:model-value="(value: string) => { applyBooleanChoice(filter, value); filteringStore.scheduleApply() }"
        />
        <Select
          v-else
          v-model="filter.operator"
          :options="operatorsForColumn(filter.column)"
          option-label="label"
          option-value="value"
          :disabled="filter.enabled === false"
          class="fsb-filter-row__operator"
          @update:model-value="filteringStore.scheduleApply()"
        />
        <InputNumber
          v-if="!isBooleanColumn(filter.column) && !isEmptyOperator(filter.operator) && isNumericColumn(filter.column)"
          v-model="filter.threshold"
          :min-fraction-digits="0"
          :max-fraction-digits="4"
          :disabled="filter.enabled === false"
          class="fsb-filter-row__threshold"
          @input="handleThresholdInput(filter, $event)"
        />
        <InputText
          v-else-if="!isBooleanColumn(filter.column) && !isEmptyOperator(filter.operator)"
          v-model="filter.text_value"
          :placeholder="filter.column === 'tag' ? 'N or C' : 'Value…'"
          :disabled="filter.enabled === false"
          class="fsb-filter-row__threshold"
          @update:model-value="filteringStore.scheduleApply()"
        />
        <Button
          icon="pi pi-trash"
          severity="danger"
          text
          rounded
          aria-label="Remove filter"
          @click="filteringStore.removeFilter(idx)"
        />
      </div>
      <div class="fsb-filter-actions">
        <Button
          label="Add filter"
          icon="pi pi-plus"
          text
          size="small"
          @click="filteringStore.addFilter()"
        />
        <Button
          label="Disable all filters"
          icon="pi pi-ban"
          text
          size="small"
          severity="secondary"
          @click="handleDisableAllFilters"
        />
        <span v-if="filteringStore.applyLoading" class="fsb-apply-status">
          <i class="pi pi-spin pi-spinner" /> Applying…
        </span>
        <span v-else-if="filteringStore.passingDesignKeys" class="fsb-apply-status">
          {{ filteringStore.passingDesignKeys.size }} designs passing
        </span>
      </div>
      <Message v-if="filteringStore.applyError" severity="error" :closable="false" class="fsb-preview-error">
        {{ filteringStore.applyError }}
      </Message>
    </Panel>

    <Panel v-if="filteringStore.hasSelectedRuns" header="2. Target contacts" class="fsb-panel">
      <TargetContactFilters />
    </Panel>

    <Panel v-if="filteringStore.hasSelectedRuns" header="3. Ranking Metrics (Quality Score)" class="fsb-panel">
      <label class="fsb-preset-row">
        Mode
        <Select
          v-model="filteringStore.rankingMode"
          :options="RANKING_MODES"
          option-label="label"
          option-value="key"
          class="fsb-preset-row__select fsb-preset-row__select--mode"
        />
      </label>
      <p v-if="filteringStore.rankingMode === 'simple'" class="fsb-hint">
        Simple ranking sorts by these metrics in order. The first enabled metric is
        the primary key, the next breaks ties, and so on. A design that passed more
        filters still ranks ahead of one that passed fewer.
      </p>
      <p v-else class="fsb-hint">
        Designs are ranked by the <em>worst</em> of their scaled ranks across these
        metrics (BoltzGen-style). Weight is inverse
        importance: a larger weight de-emphasises that metric.
      </p>
      <label class="fsb-preset-row">
        Preset
        <Select
          :model-value="selectedPreset"
          :options="presetsForMode"
          option-label="label"
          option-value="key"
          placeholder="Load a preset…"
          class="fsb-preset-row__select"
          @update:model-value="handleApplyPreset"
        />
        <span class="fsb-hint fsb-preset-row__hint">Replaces the metrics below.</span>
      </label>
      <div
        v-for="(metric, idx) in filteringStore.rankingMetrics"
        :key="idx"
        class="fsb-metric-row"
        :class="{
          'fsb-row--disabled': metric.enabled === false,
          'fsb-row--warning': filteringStore.rankingMetricWarnings.includes(idx)
        }"
      >
        <ToggleSwitch
          v-model="metric.enabled"
          :true-value="true"
          :false-value="false"
          aria-label="Enable ranking metric"
          class="fsb-row__enable-toggle"
        />
        <span
          v-if="filteringStore.rankingMode === 'simple'"
          class="fsb-metric-row__priority"
        >{{ simplePriority(idx) ?? '—' }}</span>
        <MetricColumnSelector
          v-model="metric.column"
          :columns="filteringStore.availableColumns"
          :disabled="metric.enabled === false"
          :invalid="filteringStore.rankingMetricWarnings.includes(idx)"
          class="fsb-metric-row__column"
          @update:model-value="filteringStore.onRankingColumnChange(idx, $event)"
        />
        <label v-if="filteringStore.rankingMode === 'worst_rank'" class="fsb-metric-row__weight-label">
          Weight
          <InputNumber
            v-model="metric.weight"
            :min="0.01"
            :max-fraction-digits="2"
            :step="0.5"
            :disabled="metric.enabled === false"
            class="fsb-metric-row__weight"
          />
        </label>
        <label class="fsb-metric-row__toggle">
          <input type="checkbox" v-model="metric.higher_is_better" :disabled="metric.enabled === false" />
          Higher is better
        </label>
        <Button
          icon="pi pi-trash"
          severity="danger"
          text
          rounded
          aria-label="Remove ranking metric"
          @click="filteringStore.removeRankingMetric(idx)"
        />
      </div>
      <div class="fsb-filter-actions">
        <Button
          label="Add ranking metric"
          icon="pi pi-plus"
          text
          size="small"
          @click="filteringStore.addRankingMetric()"
        />
        <Button
          label="Apply Ranking"
          icon="pi pi-sort-numeric-down"
          size="small"
          :loading="filteringStore.rankLoading"
          :disabled="!filteringStore.hasSelectedRuns"
          @click="handleApplyRanking"
        />
        <span v-if="filteringStore.rankedDesigns && !filteringStore.rankingDirty" class="fsb-apply-status">
          Ranked {{ filteringStore.rankedDesigns.size }} designs
        </span>
        <span v-else-if="filteringStore.rankingDirty" class="fsb-apply-status fsb-apply-status--dirty">
          Ranking settings changed — Apply Ranking, or Apply Diversity Filter, which re-ranks first.
        </span>
      </div>
      <Message v-if="filteringStore.rankError" severity="error" :closable="false" class="fsb-preview-error">
        {{ filteringStore.rankError }}
      </Message>
      <Message
        v-if="filteringStore.rankingMetricWarnings.length > 0"
        severity="warn"
        :closable="false"
        class="fsb-preview-error"
      >
        These metrics don't resolve to any data for the currently selected run(s) — no
        method has a non-null value for them, so they're being ignored in ranking:
        <strong>{{ filteringStore.rankingMetricWarnings.map((i) => filteringStore.rankingMetrics[i].column).join(', ') }}</strong>.
        This can happen after applying a preset built for a different pipeline method
        (e.g. "BoltzGen" on a non-BoltzGen run).
      </Message>
      <p class="fsb-hint">
        Click "Apply Ranking" after configuring metrics. This adds a
        <code>binderdash_ranking</code> column (1 = best) to the Designs table, shows it,
        and sorts by it, without narrowing which rows are shown. "Apply Diversity Filter"
        re-ranks with these metrics before it selects, so a change here also marks an
        applied diverse set unapplied until you apply it again.
      </p>
    </Panel>

    <Panel
      v-if="filteringStore.hasSelectedRuns"
      class="fsb-panel"
      :class="{
        'fsb-panel--diversity-off': !filteringStore.diversityEnabled,
        'fsb-panel--diversity-dirty': filteringStore.diversityDirty
      }"
    >
      <template #header>
        <div class="fsb-diversity-header">
          <ToggleSwitch
            :modelValue="filteringStore.diversityEnabled"
            aria-label="Enable diversity selection"
            @update:modelValue="handleDiversityEnabledChange"
          />
          <span>4. Diversity Selection</span>
          <Tag
            v-if="filteringStore.diversityDirty"
            severity="danger"
            value="Unapplied"
            class="fsb-diversity-header__dirty"
          />
        </div>
      </template>
      <div class="fsb-diversity-body" :aria-disabled="!filteringStore.diversityEnabled">
        <div class="fsb-best-mpnn-row">
          <Checkbox
            :modelValue="designsStore.bestMpnnOnly"
            @update:modelValue="designsStore.toggleBestMpnnOnly"
            :binary="true"
            inputId="fsb-best-mpnn-only"
            :disabled="!filteringStore.diversityEnabled"
          />
          <label for="fsb-best-mpnn-only">Keep only best MPNN variant per backbone</label>
        </div>

        <div class="fsb-diversity-row">
          <label class="fsb-diversity-field">
            Budget (designs in final set)
            <InputNumber
              v-model="filteringStore.budget"
              :min="1"
              show-buttons
              :disabled="!filteringStore.diversityEnabled"
            />
          </label>
          <label class="fsb-diversity-field fsb-diversity-field--alpha">
            Quality ↔ Diversity (α = {{ filteringStore.alpha }})
            <div class="fsb-alpha-slider-wrap">
              <Slider
                v-model="alphaLogSlider"
                :min="ALPHA_LOG_MIN"
                :max="ALPHA_LOG_MAX"
                :step="0.01"
                :disabled="!filteringStore.diversityEnabled"
              />
              <span
                v-for="mark in ALPHA_MARKS"
                :key="mark.value"
                class="fsb-alpha-mark"
                :style="{ left: alphaMarkPosition(mark.value) + '%' }"
              >{{ mark.label }}</span>
            </div>
            <div class="fsb-alpha-manual">
              <InputNumber
                v-model="filteringStore.alpha"
                :min="0"
                :max="1"
                :step="0.001"
                :min-fraction-digits="0"
                :max-fraction-digits="6"
                size="small"
                class="fsb-alpha-input"
                :disabled="!filteringStore.diversityEnabled"
              />
              <span class="fsb-hint">
                0 = quality only, 1 = diversity only. BoltzGen defaults: 0.001 (protein), 0.01
                (peptide-anything protocol).
              </span>
            </div>
          </label>
        </div>

        <details class="fsb-size-buckets">
          <summary>Size buckets (optional — caps selections per sequence-length range)</summary>
          <div
            v-for="(bucket, idx) in filteringStore.sizeBuckets"
            :key="idx"
            class="fsb-bucket-row"
          >
            <label>Min <InputNumber v-model="bucket.min" :min="0" :disabled="!filteringStore.diversityEnabled" /></label>
            <label>Max <InputNumber v-model="bucket.max" :min="0" :disabled="!filteringStore.diversityEnabled" /></label>
            <label>Count <InputNumber v-model="bucket.num_designs" :min="0" :disabled="!filteringStore.diversityEnabled" /></label>
            <Button
              icon="pi pi-trash"
              severity="danger"
              text
              rounded
              aria-label="Remove size bucket"
              :disabled="!filteringStore.diversityEnabled"
              @click="filteringStore.removeSizeBucket(idx)"
            />
          </div>
          <Button
            label="Add size bucket"
            icon="pi pi-plus"
            text
            size="small"
            :disabled="!filteringStore.diversityEnabled"
            @click="filteringStore.addSizeBucket()"
          />
        </details>

        <div class="fsb-filter-actions">
          <Button
            label="Apply Diversity Filter"
            icon="pi pi-sitemap"
            size="small"
            :loading="filteringStore.diversityLoading"
            :disabled="!filteringStore.hasSelectedRuns || !filteringStore.diversityEnabled"
            @click="handleApplyDiversity"
          />
          <span v-if="filteringStore.lastDiversityResult && !filteringStore.diversityDirty" class="fsb-apply-status">
            {{ filteringStore.lastDiversityResult.diverse_set_count }} diverse designs selected
            <template v-if="!filteringStore.diversityEnabled"> (disabled)</template>
          </span>
          <span v-else-if="filteringStore.diversityDirty" class="fsb-apply-status fsb-apply-status--dirty">
            Settings changed — click Apply to update the diverse subset.
          </span>
        </div>
        <Message v-if="filteringStore.diversityError" severity="error" :closable="false" class="fsb-preview-error">
          {{ filteringStore.diversityError }}
        </Message>
        <p class="fsb-hint">
          <template v-if="!filteringStore.diversityEnabled">
            Off — creating a Saved Set keeps every design that passes the hard filters
            (no budget). Turn on to select a diverse subset of size Budget.
          </template>
          <template v-else>
            Not applied automatically — this can be slow (pairwise alignment-based
            diversity selection). Narrows the Designs table to the diverse subset and
            sorts it by Ranking (<code>binderdash_ranking</code>, 1 = best). Same
            on/off as the Diversity tag in the filter cascade above.
          </template>
        </p>
      </div>
    </Panel>

    <Panel v-if="filteringStore.hasSelectedRuns" header="5. Filter cascade" class="fsb-panel">
      <span v-if="filteringStore.previewLoading" class="fsb-apply-status">
        <i class="pi pi-spin pi-spinner" /> Updating preview…
      </span>
      <Message v-if="filteringStore.previewError" severity="error" :closable="false" class="fsb-preview-error">
        {{ filteringStore.previewError }}
        <Button label="Retry" text size="small" @click="handlePreview" />
      </Message>
      <div v-if="filteringStore.previewResult" class="fsb-preview-result">
        <p>
          <strong>{{ filteringStore.previewResult.total_designs }}</strong> total designs
          across selected runs.
        </p>
        <DataTable
          v-if="cascadeRows.length > 0"
          :value="cascadeRows"
          size="small"
          :rowClass="cascadeRowClass"
        >
          <Column header="Filter">
            <template #body="{ data }">
              <Tag v-if="data.isFinal" severity="success" value="Final set" />
              <span v-else>{{ data.column }}</span>
            </template>
          </Column>
          <Column header="Threshold">
            <template #body="{ data }">{{ data.threshold !== null ? `${data.operator} ${data.threshold}` : data.operator }}</template>
          </Column>
          <Column field="remaining" header="Remaining" />
        </DataTable>
        <p v-if="!filteringStore.diversityEnabled" class="fsb-hint">
          Diversity selection is off — the final set is every design that passes the hard filters.
        </p>
        <p v-else-if="!filteringStore.lastDiversityResult || filteringStore.diversityDirty" class="fsb-hint">
          Diversity selection is on but not yet applied.
        </p>
      </div>
    </Panel>

    <Panel v-if="filteringStore.hasSelectedRuns" header="6. Create Saved Set" class="fsb-panel">
      <div class="fsb-create-row">
        <InputText
          v-model="savedSetName"
          placeholder="Saved set name…"
          class="fsb-create-row__name"
        />
        <Button
          label="Create Saved Set"
          icon="pi pi-save"
          :loading="filteringStore.creatingSavedSet"
          :disabled="!filteringStore.canCreateSavedSet"
          @click="handleCreateSavedSet"
        />
      </div>
      <Message
        v-if="filteringStore.createSavedSetError"
        severity="error"
        :closable="false"
        class="fsb-preview-error"
      >
        {{ filteringStore.createSavedSetError }}
      </Message>
      <p v-if="filteringStore.lastCreatedSavedSet" class="fsb-hint">
        Last created: <strong>{{ filteringStore.lastCreatedSavedSet.name }}</strong> —
        {{ filteringStore.lastCreatedSavedSet.diverse_set_count }} designs selected
        <template v-if="filteringStore.diversityEnabled">
          (budget {{ filteringStore.lastCreatedSavedSet.top_set_count }})
        </template>
        <template v-else>
          (all passing filters — diversity off)
        </template>
        , from
        {{ filteringStore.lastCreatedSavedSet.passing_filters }} passing filters of
        {{ filteringStore.lastCreatedSavedSet.total_input }} total. View it under Saved
        Sets.
      </p>
    </Panel>
  </div>
</template>

<style scoped>
.filter-set-builder {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.fsb-panel {
  width: 100%;
}

.fsb-hint {
  font-size: 0.85rem;
  color: #6c757d;
  margin: 0.25rem 0 0.75rem 0;
}

.fsb-columns-table {
  width: 100%;
}

.fsb-filter-actions {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  margin-top: 0.25rem;
}

.fsb-apply-status {
  font-size: 0.85rem;
  color: #495057;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.fsb-method-tag {
  margin-right: 0.25rem;
}

.fsb-filter-row,
.fsb-metric-row,
.fsb-bucket-row {
  display: flex;
  /* flex-start, not center: MetricColumnSelector's height varies row-to-row (it grows
     when it shows a min/max/mean/median hint under the dropdown for whichever column is
     currently selected), and center-alignment against a variable-height sibling made
     the Select box visibly shift up/down between rows depending on whether its neighbour
     had a hint showing. flex-start keeps every control's top edge aligned regardless. */
  align-items: flex-start;
  gap: 0.75rem;
  margin-bottom: 0.6rem;
  flex-wrap: wrap;
}

/* Controls that don't grow (toggle, operator/weight fields, delete button) still want
   to be centered on the dropdown's own control line, not glued to the row's top edge. */
.fsb-row__enable-toggle,
.fsb-filter-row__operator,
.fsb-filter-row__threshold,
.fsb-filter-row > .p-button,
.fsb-metric-row__weight-label,
.fsb-metric-row__toggle,
.fsb-metric-row > .p-button {
  margin-top: 0.3rem;
}

.fsb-row--disabled {
  opacity: 0.55;
}

.fsb-row--warning {
  background-color: #fff5f5;
  border-radius: 6px;
  padding: 0.35rem 0.5rem;
  margin-left: -0.5rem;
  margin-right: -0.5rem;
}

.fsb-preset-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.85rem;
  font-weight: 500;
  margin-bottom: 0.75rem;
}

.fsb-preset-row__select {
  min-width: 14rem;
}

.fsb-preset-row__select--mode {
  min-width: 28rem;
}

.fsb-metric-row__priority {
  flex: 0 0 2.5rem;
  margin-top: 0.45rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: #495057;
}

.fsb-preset-row__hint {
  margin: 0;
  font-weight: 400;
}

.fsb-filter-row__column,
.fsb-metric-row__column {
  flex: 1 1 260px;
  min-width: 220px;
}

.fsb-filter-row__operator {
  min-width: 12rem;
}

.fsb-filter-row__threshold {
  min-width: 8rem;
}

/* Same PrimeVue InputNumber inner-<input>-overflow issue as
   .fsb-metric-row__weight below — belt and braces since this wrapper is also
   width-constrained next to a sibling (the delete button). */
.fsb-filter-row__threshold :deep(input) {
  width: 100%;
  box-sizing: border-box;
}

.fsb-metric-row__weight-label,
.fsb-metric-row__toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  color: #495057;
}

.fsb-metric-row__weight {
  width: 9rem;
}

/* PrimeVue's InputNumber inner <input> doesn't respect the wrapper's width by
   default and overflows past it (observed: 205px inner input inside a 144px
   wrapper), visually overlapping/painting over whatever sits to its right. */
.fsb-metric-row__weight :deep(input) {
  width: 100%;
  box-sizing: border-box;
}

.fsb-diversity-row {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}

.fsb-diversity-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  font-size: 0.85rem;
  font-weight: 500;
}

.fsb-diversity-field--alpha {
  min-width: 20rem;
  flex: 1;
}

.fsb-alpha-slider-wrap {
  position: relative;
  padding-bottom: 1.1rem;
}

.fsb-alpha-mark {
  position: absolute;
  top: 0.85rem;
  transform: translateX(-50%);
  font-size: 0.7rem;
  font-weight: 400;
  color: #6c757d;
  white-space: nowrap;
}

.fsb-alpha-manual {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.5rem;
  font-weight: 400;
}

.fsb-alpha-input {
  width: 8rem;
  flex-shrink: 0;
}

.fsb-alpha-input :deep(input) {
  width: 100%;
  box-sizing: border-box;
}

.fsb-best-mpnn-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: #495057;
  margin-bottom: 0.85rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--p-content-border-color, #dee2e6);
}

.fsb-size-buckets {
  margin-top: 0.5rem;
}

.fsb-size-buckets summary {
  cursor: pointer;
  font-size: 0.85rem;
  color: #495057;
  margin-bottom: 0.5rem;
}

.fsb-bucket-row label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
}

.fsb-preview-result {
  margin-top: 1rem;
}

.fsb-diversity-header {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  font-weight: 600;
}

.fsb-diversity-header__dirty {
  font-weight: 500;
}

.fsb-panel--diversity-off {
  opacity: 0.55;
}

.fsb-panel--diversity-dirty {
  border: 2px solid #e53935;
  border-radius: 6px;
}

.fsb-apply-status--dirty {
  color: #c62828;
}

/* rowClass lands on PrimeVue <tr>s outside this component's scoped
   attribute, so :deep is required. text-decoration on <tr> is ignored by
   browsers — apply it (and the muted colour) to the cells. */
:deep(.fsb-cascade-row--final) {
  font-weight: 600;
  background-color: #e6f4ea !important;
}

:deep(.fsb-cascade-row--disabled td) {
  color: var(--p-text-muted-color, #888);
  text-decoration: line-through;
  opacity: 0.65;
}

:deep(.fsb-cascade-row--diversity:not(.fsb-cascade-row--disabled)) {
  background-color: #fff8e6 !important;
  font-style: italic;
}

:deep(.fsb-cascade-row--mpnn) {
  background-color: #fff8e6 !important;
  font-style: italic;
}

.fsb-preview-error {
  margin-top: 0.75rem;
}

.fsb-create-row {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}

.fsb-create-row__name {
  min-width: 20rem;
  flex: 1;
}
</style>
