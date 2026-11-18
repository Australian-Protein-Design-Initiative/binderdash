<template>
  <div class="select-runs-panel">
    <div class="panel-header">
      <h2>Select Runs</h2>
      <p class="hint">
        Choose ingested runs to drive the Designs table and (by default) plots. Use the filter row under the column headers to narrow by project, method, or name.
      </p>
    </div>

    <Toolbar class="select-runs-toolbar">
      <template #start>
        <div class="show-selected-field">
          <InputSwitch
            v-model="showSelectedOnly"
            input-id="sr-show-selected"
            :aria-label="'Show only selected runs in the table'"
          />
          <label for="sr-show-selected" class="show-selected-label">Show only selected</label>
        </div>
      </template>
      <template #end>
        <div class="select-runs-toolbar-actions">
          <Button
            label="Refresh list"
            icon="pi pi-refresh"
            severity="secondary"
            outlined
            :loading="runsStore.loading"
            :disabled="ingesting"
            @click="runsStore.fetchRuns()"
          />
          <Button
            label="Re-Ingest Selected"
            icon="pi pi-download"
            severity="secondary"
            outlined
            :loading="ingesting"
            :disabled="tableSelection.length === 0"
            @click="reIngestSelected"
          />
          <Button
            label="Delete selected"
            icon="pi pi-trash"
            severity="danger"
            outlined
            :loading="deleting"
            :disabled="tableSelection.length === 0 || ingesting"
            @click="confirmDeleteSelected"
          />
        </div>
      </template>
    </Toolbar>

    <DataTable
      v-model:selection="tableSelection"
      selectionMode="multiple"
      :metaKeySelection="false"
      v-model:filters="filters"
      :value="dataForTable"
      data-key="run_id"
      lazy
      :total-records="filteredSortedRuns.length"
      v-model:first="tableFirst"
      :rows="tableRows"
      :sort-field="sortField ?? undefined"
      :sort-order="sortOrder ?? undefined"
      filter-display="row"
      stripedRows
      paginator
      :rowsPerPageOptions="[5, 10, 20, 50]"
      paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
      currentPageReportTemplate="Showing {first} to {last} of {totalRecords} runs"
      showGridlines
      :resizableColumns="true"
      columnResizeMode="fit"
      :reorderableColumns="true"
      :rowHover="true"
      :loading="runsStore.loading"
      @page="onPage"
      @sort="onSort"
    >
      <template #empty>
        <div class="empty-msg">
          <i class="pi pi-inbox empty-icon" aria-hidden="true" />
          <p v-if="runsStore.loading">Loading runs…</p>
          <template v-else-if="!runsStore.runs.length">
            <h3>No ingested runs</h3>
            <p>Use <strong>Ingest Runs</strong> to add runs from disk.</p>
          </template>
          <template v-else-if="showSelectedOnly && tableSelection.length === 0">
            <h3>No runs selected</h3>
            <p>Select runs in the table, or turn off <strong>Show only selected</strong>.</p>
          </template>
          <template v-else>
            <h3>No results</h3>
            <p>Adjust the column filters or use <strong>Ingest Runs</strong> to add data.</p>
          </template>
        </div>
      </template>
      <Column selectionMode="multiple" headerStyle="width: 3rem" />
      <Column
        field="metadata.name"
        filter-field="metadata.name"
        header="Name"
        sortable
        :show-filter-menu="false"
        filter-match-mode="contains"
        style="min-width: 12rem"
      >
        <template #body="{ data }">
          <div class="run-name">
            <i :class="getMethodIconClass(data.method)" class="protocol-icon" aria-hidden="true" />
            {{ data.metadata?.name ?? '—' }}
          </div>
        </template>
        <template #filter="{ filterModel, filterCallback }">
          <InputGroup class="p-column-filter sr-col-filter bd-inputgroup-inline-clear">
            <InputText
              v-model="filterModel.value"
              type="text"
              placeholder="Search by name"
              class="sr-col-filter-input"
              @input="filterCallback()"
            />
            <InputGroupAddon>
              <Button
                icon="pi pi-times"
                severity="secondary"
                variant="text"
                :disabled="!filterModel.value"
                aria-label="Clear name filter"
                @click="
                  filterModel.value = null;
                  filterCallback();
                "
              />
            </InputGroupAddon>
          </InputGroup>
        </template>
      </Column>
      <Column
        field="project_id"
        header="Project ID"
        sortable
        :show-filter-menu="false"
        filter-match-mode="in"
        style="min-width: 12rem"
      >
        <template #body="{ data }">
          <span class="project-id">{{ data.project_id || '—' }}</span>
        </template>
        <template #filter="{ filterModel, filterCallback }">
          <MultiSelect
            v-model="filterModel.value"
            :options="projectOptions"
            option-label="label"
            option-value="value"
            placeholder="All projects"
            filter
            filter-placeholder="Search projects..."
            show-clear
            display="chip"
            :max-selected-labels="2"
            class="p-column-filter sr-col-filter"
            @update:model-value="filterCallback()"
          />
        </template>
      </Column>
      <Column
        field="method"
        header="Method"
        sortable
        :show-filter-menu="false"
        filter-match-mode="in"
        style="min-width: 10rem"
      >
        <template #body="{ data }">
          <Tag
            :value="data.method"
            :style="getMethodTagStyle(data.method)"
            class="pipeline-palette-tag"
          />
        </template>
        <template #filter="{ filterModel, filterCallback }">
          <MultiSelect
            v-model="filterModel.value"
            :options="methodOptions"
            option-label="label"
            option-value="value"
            placeholder="All methods"
            filter
            filter-placeholder="Search methods..."
            show-clear
            display="chip"
            :max-selected-labels="2"
            class="p-column-filter sr-col-filter"
            @update:model-value="filterCallback()"
          />
        </template>
      </Column>
      <Column field="metadata.pdb_count" sortable style="min-width: 110px">
        <template #header>
          <span v-tooltip.top="'Accepted or filtered designs / pre-filter trajectories or designs'">Accepted / Total</span>
        </template>
        <template #body="{ data }">
          {{ formatAcceptedTotalText(data) }}
        </template>
      </Column>
      <Column field="metadata.primary_score_stats.median" sortable style="min-width: 300px">
        <template #header>
          <span
            v-tooltip.top="'Mean ± σ over accepted/filtered designs, range [min - max]; chip shows the score column.'"
          >Primary score</span>
        </template>
        <template #body="{ data }">
          <template v-for="w in [primaryScoreDisplay(data)]" :key="data.run_id">
            <div v-if="w" class="primary-score-row">
              <span v-tooltip.top="w.title" class="primary-score-numbers">{{ w.numbersLine }}</span>
              <Tag
                :value="w.chipLabel"
                :style="w.tagStyle"
                class="primary-score-type-tag pipeline-palette-tag"
              />
            </div>
            <span v-else class="muted-cell">—</span>
          </template>
        </template>
      </Column>
      <Column field="path" header="Path" style="min-width: 200px">
        <template #body="{ data }">
          <span class="run-path">{{ data.path }}</span>
        </template>
      </Column>
      <Column field="metadata.results_file" header="Results File" style="min-width: 150px">
        <template #body="{ data }">
          <span class="results-file">{{ data.metadata?.results_file ?? '—' }}</span>
        </template>
      </Column>
    </DataTable>

    <div class="panel-header saved-sets-header">
      <h2>
        <i class="pi pi-bookmark" aria-hidden="true" />
        Saved Sets
      </h2>
      <p class="hint">
        Include Saved Sets in the Designs table alongside runs (frozen snapshots — see the
        <strong>Saved Sets</strong> tab to rename, delete, or download them).
      </p>
    </div>

    <DataTable
      v-model:selection="savedSetSelection"
      selectionMode="multiple"
      :metaKeySelection="false"
      :value="filteringStore.savedSets"
      data-key="id"
      stripedRows
      showGridlines
      :rowHover="true"
      :loading="filteringStore.savedSetsLoading"
      class="saved-sets-table"
    >
      <template #empty>
        <div class="empty-msg">
          <i class="pi pi-bookmark empty-icon" aria-hidden="true" />
          <p v-if="filteringStore.savedSetsLoading">Loading saved sets…</p>
          <template v-else>
            <h3>No saved sets</h3>
            <p>Create one from the <strong>Filtering</strong> tab.</p>
          </template>
        </div>
      </template>
      <Column selectionMode="multiple" headerStyle="width: 3rem" />
      <Column field="name" header="Name" sortable style="min-width: 12rem">
        <template #body="{ data }">
          <div class="run-name">
            <Tag value="Set" severity="info" class="saved-set-badge" />
            {{ data.name }}
          </div>
        </template>
      </Column>
      <Column field="created_at" header="Created" sortable style="min-width: 10rem">
        <template #body="{ data }">
          {{ formatSavedSetDate(data.created_at) }}
        </template>
      </Column>
      <Column header="Source Runs" style="min-width: 10rem">
        <template #body="{ data }">
          {{ formatSourceRuns(data.source_run_ids) }}
        </template>
      </Column>
      <Column field="design_count" header="Design Count" sortable style="min-width: 8rem">
        <template #body="{ data }">
          {{ data.design_count }} / {{ data.total_input }}
        </template>
      </Column>
      <Column header="Actions" style="min-width: 12rem">
        <template #body="{ data }">
          <div class="saved-set-actions">
            <Button
              icon="pi pi-filter"
              severity="secondary"
              text
              v-tooltip.top="'Load filters (load recipe into Filtering tab)'"
              @click="loadFiltersForSet(data)"
            />
            <Button
              icon="pi pi-plus-circle"
              severity="secondary"
              text
              v-tooltip.top="'Select runs for set (add its source runs to the selection above)'"
              @click="selectRunsForSet(data)"
            />
          </div>
        </template>
      </Column>
    </DataTable>

    <Dialog
      v-model:visible="reingestDialogVisible"
      modal
      header="Re-ingest runs?"
      :style="{ width: 'min(32rem, 95vw)' }"
      :closable="true"
      @hide="onReingestDialogHide"
    >
      <p class="reingest-lead">
        These runs are already in the database. Ingesting again will replace stored designs and reset any <strong>tag</strong> and <strong>good</strong> values you set earlier:
      </p>
      <ul class="reingest-list">
        <li v-for="item in pendingReingest" :key="item.run_group_key">
          {{ item.display_name }}
        </li>
      </ul>
      <template #footer>
        <Button
          label="Cancel"
          severity="secondary"
          outlined
          @click="reingestDialogVisible = false"
        />
        <Button
          label="Ingest anyway"
          severity="warn"
          icon="pi pi-exclamation-triangle"
          :loading="ingesting"
          @click="confirmReingestIngest"
        />
      </template>
    </Dialog>

    <Dialog
      v-model:visible="deleteDialogVisible"
      modal
      header="Delete selected runs?"
      :style="{ width: 'min(32rem, 95vw)' }"
      :closable="true"
      @hide="onDeleteDialogHide"
    >
      <p class="delete-dialog-lead">
        This will remove the selected runs from the <strong>database</strong> (including their designs and tag metrics cache). Files on disk under your run folders are <strong>not</strong> deleted or modified.
      </p>
      <ul class="delete-dialog-list">
        <li v-for="run in pendingDeleteRuns" :key="run.run_id">
          {{ run.metadata?.name ?? run.run_id }}
        </li>
      </ul>
      <template #footer>
        <Button
          label="Cancel"
          severity="secondary"
          outlined
          :disabled="deleting"
          @click="deleteDialogVisible = false"
        />
        <Button
          label="Delete"
          severity="danger"
          icon="pi pi-trash"
          :loading="deleting"
          @click="deleteSelectedRuns"
        />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import DataTable from 'primevue/datatable'
import type { DataTablePageEvent, DataTableSortEvent } from 'primevue/datatable'
import Column from 'primevue/column'
import InputText from 'primevue/inputtext'
import InputGroup from 'primevue/inputgroup'
import InputGroupAddon from 'primevue/inputgroupaddon'
import MultiSelect from 'primevue/multiselect'
import Button from 'primevue/button'
import InputSwitch from 'primevue/inputswitch'
import Tag from 'primevue/tag'
import Toolbar from 'primevue/toolbar'
import Dialog from 'primevue/dialog'
import { useToast } from 'primevue/usetoast'
import { useRunsStore, useDesignsStore, usePlotsStore, useFilteringStore, useAppStore } from '../stores'
import type { Run } from '../types/store'
import { formatAcceptedTotalText, primaryScoreDisplay, formatSourceRunNames } from '../utils/runDisplay'
import { getMethodTagStyle, getMethodIconClass } from '../config/pipelineDisplay'
import { runsApi } from '../webapi'
import type { FilteringRunRequestDto, IngestPreviewReingestItem, SavedSetDto } from '../webapi'

const emit = defineEmits<{
  ingestComplete: []
}>()

const runsStore = useRunsStore()
const designsStore = useDesignsStore()
const plotsStore = usePlotsStore()
const filteringStore = useFilteringStore()
const appStore = useAppStore()
const toast = useToast()

const showSelectedOnly = ref(false)
const ingesting = ref(false)
const deleting = ref(false)
const reingestDialogVisible = ref(false)
const deleteDialogVisible = ref(false)
const pendingDeleteRuns = ref<Run[]>([])
const pendingReingest = ref<IngestPreviewReingestItem[]>([])

const tableFirst = ref(0)
const tableRows = ref(10)
const sortField = ref<string | null>(null)
const sortOrder = ref<number | null>(null)

const filters = ref({
  project_id: { value: null as string[] | null, matchMode: 'in' as const },
  method: { value: null as string[] | null, matchMode: 'in' as const },
  'metadata.name': { value: null as string | null, matchMode: 'contains' as const }
})

const resetProjectAndMethodFilters = () => {
  filters.value.project_id.value = null
  filters.value.method.value = null
  filters.value['metadata.name'].value = null
}

const projectOptions = computed(() => {
  const set = new Set<string>()
  for (const r of runsStore.runs) {
    if (r.project_id) set.add(r.project_id)
  }
  return [...set].sort().map((value) => ({ label: value, value }))
})

const methodOptions = computed(() => {
  const set = new Set<string>()
  for (const r of runsStore.runs) {
    if (r.method) set.add(r.method)
  }
  return [...set].sort().map((value) => ({ label: value, value }))
})

const tableSelection = ref<Run[]>([])

const selectedRunIds = computed(() => new Set(tableSelection.value.map((r) => r.run_id)))

function resolveRunField(run: Run, field: string): unknown {
  return field.split('.').reduce<unknown>((obj, key) => {
    if (obj == null || typeof obj !== 'object') return undefined
    return (obj as Record<string, unknown>)[key]
  }, run)
}

function runMatchesColumnFilters(run: Run): boolean {
  const nameFilter = filters.value['metadata.name'].value
  if (nameFilter != null && String(nameFilter).trim() !== '') {
    const name = String(run.metadata?.name ?? '').toLowerCase()
    if (!name.includes(String(nameFilter).toLowerCase())) return false
  }
  const projects = filters.value.project_id.value
  if (projects != null && projects.length > 0 && !projects.includes(run.project_id)) {
    return false
  }
  const methods = filters.value.method.value
  if (methods != null && methods.length > 0 && !methods.includes(run.method)) {
    return false
  }
  return true
}

function compareFieldValues(a: unknown, b: unknown, order: number): number {
  if (a == null && b == null) return 0
  if (a == null) return 1
  if (b == null) return -1
  if (typeof a === 'number' && typeof b === 'number') {
    if (Number.isNaN(a) && Number.isNaN(b)) return 0
    if (Number.isNaN(a)) return 1
    if (Number.isNaN(b)) return -1
    return (a - b) * order
  }
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' }) * order
}

/** Selected runs stay visible despite column filters and sort to the top. */
const filteredSortedRuns = computed((): Run[] => {
  const selected = selectedRunIds.value
  let runs = runsStore.runs
  if (showSelectedOnly.value) {
    runs = runs.filter((r) => selected.has(r.run_id))
  } else {
    runs = runs.filter((r) => selected.has(r.run_id) || runMatchesColumnFilters(r))
  }

  const field = sortField.value
  const order = sortOrder.value
  return [...runs].sort((a, b) => {
    const aSel = selected.has(a.run_id) ? 0 : 1
    const bSel = selected.has(b.run_id) ? 0 : 1
    if (aSel !== bSel) return aSel - bSel
    if (!field || order == null || order === 0) return 0
    return compareFieldValues(resolveRunField(a, field), resolveRunField(b, field), order)
  })
})

const dataForTable = computed((): Run[] => {
  const start = tableFirst.value
  return filteredSortedRuns.value.slice(start, start + tableRows.value)
})

function onPage(event: DataTablePageEvent) {
  tableFirst.value = event.first
  tableRows.value = event.rows
}

function onSort(event: DataTableSortEvent) {
  sortField.value = typeof event.sortField === 'string' ? event.sortField : null
  sortOrder.value = event.sortOrder ?? null
}

watch(
  [filters, showSelectedOnly, () => runsStore.runs.length],
  () => {
    tableFirst.value = 0
  },
  { deep: true }
)

watch(filteredSortedRuns, (runs) => {
  if (runs.length === 0) {
    tableFirst.value = 0
    return
  }
  if (tableFirst.value >= runs.length) {
    tableFirst.value = Math.max(0, Math.floor((runs.length - 1) / tableRows.value) * tableRows.value)
  }
})

const sameIdSet = (a: string[], b: string[]): boolean => {
  if (a.length !== b.length) return false
  const bs = new Set(b)
  return a.every((id) => bs.has(id))
}

watch(
  tableSelection,
  (sel) => {
    const ids = sel.map((r) => r.run_id)
    if (!sameIdSet(ids, designsStore.selectedRunIds)) {
      designsStore.setSelectedRunIds(ids)
    }
    if (!sameIdSet(ids, plotsStore.selectedRunIds)) {
      plotsStore.setSelectedRuns(ids)
    }
  },
  { deep: true }
)

watch(
  [() => runsStore.runs, () => designsStore.selectedRunIds],
  ([runs, selectedIds]) => {
    const ids = new Set(selectedIds)
    const nextSelection = ids.size === 0 ? [] : runs.filter((r) => ids.has(r.run_id))
    const currentIds = tableSelection.value.map((r) => r.run_id)
    const nextIds = nextSelection.map((r) => r.run_id)
    if (sameIdSet(currentIds, nextIds)) {
      return
    }
    tableSelection.value = nextSelection
  },
  { deep: true, immediate: true }
)

// --- Saved Sets inclusion (plan §7A.4: Select Runs handles inclusion, the
// standalone Saved Sets tab handles management) ---

const savedSetSelection = ref<SavedSetDto[]>([])

const formatSavedSetDate = (createdAt: string): string => {
  const d = new Date(createdAt)
  if (Number.isNaN(d.getTime())) return createdAt
  return d.toLocaleString()
}

const formatSourceRuns = (sourceRunIds: string[] | undefined): string =>
  formatSourceRunNames(sourceRunIds, runsStore.availableRuns)

function loadFiltersForSet(set: SavedSetDto) {
  filteringStore.loadRecipe(set.filter_params as FilteringRunRequestDto)
  appStore.setActiveTab('filtering')
  toast.add({
    severity: 'success',
    summary: 'Filters loaded',
    detail: `"${set.name}"'s filters, ranking, and diversity settings were loaded into the Filtering tab.`,
    life: 5000
  })
}

function selectRunsForSet(set: SavedSetDto) {
  const currentIds = new Set(tableSelection.value.map((r) => r.run_id))
  const missingIds = (set.source_run_ids ?? []).filter((id) => !currentIds.has(id))
  if (missingIds.length === 0) {
    toast.add({
      severity: 'info',
      summary: 'Already selected',
      detail: `All of "${set.name}"'s source runs are already selected.`,
      life: 4000
    })
    return
  }
  const byId = new Map(runsStore.runs.map((r) => [r.run_id, r]))
  const toAdd = missingIds.map((id) => byId.get(id)).filter((r): r is Run => !!r)
  tableSelection.value = [...tableSelection.value, ...toAdd]
  const notFound = missingIds.length - toAdd.length
  if (notFound > 0) {
    toast.add({
      severity: 'warn',
      summary: 'Some source runs unavailable',
      detail: `${notFound} of "${set.name}"'s source run(s) are no longer ingested.`,
      life: 6000
    })
  }
}

watch(
  savedSetSelection,
  (sel) => {
    const ids = sel.map((s) => s.id)
    if (!sameIdSet(ids, designsStore.selectedSavedSetIds)) {
      designsStore.setSelectedSavedSetIds(ids)
    }
  },
  { deep: true }
)

watch(
  [() => filteringStore.savedSets, () => designsStore.selectedSavedSetIds],
  ([sets, selectedIds]) => {
    const ids = new Set(selectedIds)
    const nextSelection = ids.size === 0 ? [] : sets.filter((s) => ids.has(s.id))
    const currentIds = savedSetSelection.value.map((s) => s.id)
    const nextIds = nextSelection.map((s) => s.id)
    if (sameIdSet(currentIds, nextIds)) {
      return
    }
    savedSetSelection.value = nextSelection
  },
  { deep: true, immediate: true }
)

const doIngest = async (rows: Run[]) => {
  ingesting.value = true
  try {
    for (const row of rows) {
      await runsApi.ingestRuns([row as unknown as Record<string, unknown>])
    }
    toast.add({
      severity: 'success',
      summary: 'Ingest complete',
      detail: `${rows.length} run(s) updated in the database.`,
      life: 4000
    })
    reingestDialogVisible.value = false
    pendingReingest.value = []
    emit('ingestComplete')
  } catch (error) {
    console.error('Ingest failed:', error)
    toast.add({
      severity: 'error',
      summary: 'Ingest failed',
      detail: error instanceof Error ? error.message : 'Request failed',
      life: 5000
    })
  } finally {
    ingesting.value = false
  }
}

const reIngestSelected = async () => {
  const rows = tableSelection.value
  if (rows.length === 0) {
    toast.add({
      severity: 'warn',
      summary: 'Nothing selected',
      detail: 'Select one or more rows in the table before re-ingesting.',
      life: 4000
    })
    return
  }
  try {
    const preview = await runsApi.ingestPreview(rows as unknown as Record<string, unknown>[])
    if (preview.reingest.length > 0) {
      pendingReingest.value = preview.reingest
      reingestDialogVisible.value = true
      return
    }
    await doIngest(rows)
  } catch (error) {
    console.error('Ingest preview failed:', error)
    toast.add({
      severity: 'error',
      summary: 'Ingest failed',
      detail: error instanceof Error ? error.message : 'Request failed',
      life: 5000
    })
  }
}

const confirmReingestIngest = async () => {
  await doIngest(tableSelection.value)
}

const onReingestDialogHide = () => {
  pendingReingest.value = []
}

const confirmDeleteSelected = () => {
  if (tableSelection.value.length === 0) {
    toast.add({
      severity: 'warn',
      summary: 'Nothing selected',
      detail: 'Select one or more rows in the table before deleting.',
      life: 4000
    })
    return
  }
  pendingDeleteRuns.value = [...tableSelection.value]
  deleteDialogVisible.value = true
}

const onDeleteDialogHide = () => {
  pendingDeleteRuns.value = []
}

const deleteSelectedRuns = async () => {
  const rows = [...pendingDeleteRuns.value]
  if (rows.length === 0) {
    deleteDialogVisible.value = false
    return
  }
  deleting.value = true
  try {
    for (const run of rows) {
      await runsStore.deleteRun(run.run_id)
    }
    tableSelection.value = []
    pendingDeleteRuns.value = []
    await runsStore.fetchRuns()
    resetProjectAndMethodFilters()
    await designsStore.fetchDesignsForRuns(designsStore.selectedRunIds)
    toast.add({
      severity: 'success',
      summary: 'Runs removed',
      detail: `${rows.length} run(s) deleted from the database (files on disk unchanged).`,
      life: 4000
    })
    deleteDialogVisible.value = false
  } catch (error) {
    console.error('Delete runs failed:', error)
    toast.add({
      severity: 'error',
      summary: 'Delete failed',
      detail: error instanceof Error ? error.message : 'Request failed',
      life: 5000
    })
    await runsStore.fetchRuns()
    resetProjectAndMethodFilters()
    pendingDeleteRuns.value = []
    deleteDialogVisible.value = false
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  runsStore.fetchRuns()
  filteringStore.fetchSavedSets()
})
</script>

<style scoped>
.select-runs-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.panel-header h2 {
  margin: 0 0 0.5rem 0;
  color: #495057;
}

.hint {
  margin: 0 0 1rem 0;
  color: #6c757d;
  font-size: 0.95rem;
}

.sr-col-filter {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.sr-col-filter-input {
  flex: 1;
  min-width: 0;
}

.select-runs-toolbar {
  width: 100%;
}

.select-runs-toolbar :deep(.p-toolbar) {
  border-radius: 6px;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.select-runs-toolbar-actions {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.show-selected-field {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.show-selected-label {
  font-size: 0.9rem;
  font-weight: 600;
  color: #495057;
  cursor: pointer;
  user-select: none;
}

.run-path {
  font-family: monospace;
  font-size: 0.9rem;
  color: #6c757d;
  word-break: break-all;
}

.project-id {
  color: #495057;
}

.run-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.protocol-icon {
  color: #6c757d;
  /* PrimeVue row-click skips targets it treats as “clickable”; the icon would otherwise block run selection. */
  pointer-events: none;
}

.muted-cell {
  color: #6c757d;
}

.primary-score-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.primary-score-numbers {
  font-family: ui-monospace, monospace;
  font-size: 0.85rem;
  color: #495057;
  word-break: break-word;
}

.primary-score-type-tag {
  flex-shrink: 0;
  max-width: 100%;
}

.primary-score-type-tag :deep(.p-tag-label) {
  max-width: 12rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.results-file {
  font-family: monospace;
  font-size: 0.9rem;
  color: #6c757d;
  word-break: break-all;
}

.empty-msg {
  padding: 1.5rem;
  text-align: center;
  color: #6c757d;
}

.empty-msg h3 {
  margin: 0.5rem 0 0.25rem 0;
  color: #495057;
  font-size: 1.1rem;
}

.empty-icon {
  font-size: 3rem;
  color: #6c757d;
}

.reingest-lead {
  margin: 0 0 0.75rem 0;
  line-height: 1.5;
  color: #495057;
}

.reingest-list {
  margin: 0 0 0 1.25rem;
  padding: 0;
  color: #495057;
}

.reingest-list li {
  margin: 0.25rem 0;
}

.delete-dialog-lead {
  margin: 0 0 0.75rem 0;
  line-height: 1.5;
  color: #495057;
}

.delete-dialog-list {
  margin: 0 0 0 1.25rem;
  padding: 0;
  color: #495057;
}

.delete-dialog-list li {
  margin: 0.25rem 0;
}

.saved-sets-header {
  margin-top: 0.5rem;
}

.saved-sets-header h2 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.5rem 0;
  color: #495057;
}

.saved-sets-table {
  margin-bottom: 0.5rem;
}

.saved-set-badge {
  flex-shrink: 0;
}

.saved-set-actions {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}
</style>
