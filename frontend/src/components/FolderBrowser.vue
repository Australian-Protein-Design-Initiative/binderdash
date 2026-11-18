<template>
  <div class="folder-browser">
    <DesktopSettings />

    <div class="browser-header">
      <h2>Ingest Runs</h2>
      <div class="header-actions">
        <div class="browser-controls">
          <Button 
            label="Refresh" 
            icon="pi pi-refresh" 
            @click="refreshTree"
            :loading="folderStore.loading"
            severity="secondary"
            outlined
          />
          <Button 
            label="Scan Selected Folders" 
            icon="pi pi-search" 
            @click="scanSelectedFolders"
            :loading="folderStore.scanning"
            :disabled="selectedFolderNodes.length === 0"
          />
          <Button 
            label="Clear Selection" 
            icon="pi pi-times" 
            @click="clearSelection"
            :disabled="selectedFolderNodes.length === 0"
            severity="secondary"
          />
        </div>
        <div class="scan-options">
          <Checkbox
            v-model="forceRescanOfIngested"
            input-id="forceRescanOfIngested"
            binary
          />
          <label for="forceRescanOfIngested">Force rescan of ingested</label>
        </div>
      </div>
    </div>

    <div v-if="folderStore.scanResults.length > 0" class="scan-results">
      <h3>Scan Results ({{ folderStore.scanResults.length }} runs found)</h3>
      <p class="scan-results-hint">
        Only runs discovered in this scan appear here. If <strong>Force rescan of ingested</strong> is off, runs already in the database are omitted even when their folders are selected. <strong>Ingest selected runs</strong> loads each chosen run from disk into the database. If a run was already ingested, you will be asked to confirm first because that replaces stored designs and clears saved <strong>tag</strong> and <strong>good</strong> values.
      </p>
      <div class="ingest-actions">
        <Button
          label="Ingest selected runs"
          icon="pi pi-download"
          :loading="ingesting"
          :disabled="folderStore.selectedRuns.length === 0"
          @click="ingestSelectedRuns"
        />
      </div>

      <DataTable 
        :value="folderStore.scanResults" 
        v-model:selection="folderStore.selectedRuns"
        selectionMode="multiple"
        :metaKeySelection="false"
        dataKey="run_id"
        stripedRows
        paginator
        :rows="10"
        :rowsPerPageOptions="[5, 10, 20, 50]"
        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
        currentPageReportTemplate="Showing {first} to {last} of {totalRecords} runs"
        :filters="filters"
        filterDisplay="menu"
        :globalFilterFields="['metadata.name', 'method', 'path', 'project_id']"
        showGridlines
        :resizableColumns="true"
        columnResizeMode="fit"
        :reorderableColumns="true"
        :rowHover="true"
      >
        <template #empty>
          <div class="text-center p-4">
            <i class="pi pi-search" style="font-size: 3rem; color: #6c757d;"></i>
            <h3>No Runs Found</h3>
            <p>No valid runs detected in selected folders</p>
          </div>
        </template>

        <Column selectionMode="multiple" headerStyle="width: 3rem"></Column>
        <Column header="Ingested" headerStyle="width: 4rem" bodyStyle="text-align: center">
          <template #body="{ data }">
            <span v-if="ingestStatusFor(data) === 'pending'" class="ingest-pending" aria-label="Ingesting">
              <i class="pi pi-spin pi-spinner"></i>
            </span>
            <i
              v-else-if="ingestStatusFor(data) === 'success'"
              class="pi pi-check ingest-ok"
              aria-label="Ingested"
            ></i>
            <i
              v-else-if="ingestStatusFor(data) === 'error'"
              class="pi pi-times ingest-err"
              aria-label="Ingest failed"
            ></i>
          </template>
        </Column>
        <Column field="metadata.name" header="Name" sortable style="min-width: 150px">
          <template #body="{ data }">
            <div class="run-name">
              <i :class="getMethodIconClass(data.method)" class="protocol-icon"></i>
              {{ data.metadata.name }}
            </div>
          </template>
        </Column>
        <Column field="project_id" header="Project ID" sortable style="min-width: 160px">
          <template #body="{ data }">
            <InputText
              v-model="data.project_id"
              class="project-id-input w-full"
              placeholder="Project ID"
              @click.stop
            />
          </template>
        </Column>
        <Column field="method" header="Method" sortable style="min-width: 100px">
          <template #body="{ data }">
            <Tag
              :value="data.method"
              :style="getMethodTagStyle(data.method)"
              class="pipeline-palette-tag"
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
        <Column field="path" header="Path" style="min-width: 200px">
          <template #body="{ data }">
            <span class="run-path">{{ data.path }}</span>
          </template>
        </Column>
        <Column field="metadata.results_file" header="Results File" style="min-width: 150px">
          <template #body="{ data }">
            <span class="results-file">{{ data.metadata.results_file }}</span>
          </template>
        </Column>
      </DataTable>
    </div>

    <div class="browser-content">
      <TreeTable 
        :value="folderStore.folders" 
        :loading="folderStore.loading"
        @node-expand="onNodeExpand"
        @node-collapse="onNodeCollapse"
        v-model:expandedKeys="folderStore.expandedKeys"
        dataKey="key"
        lazy
        :loadingIcon="'pi pi-spinner'"
        :loadingMode="'card'"
      >
        <Column field="name" header="Name" expander>
          <template #body="{ node }">
            <div class="folder-node">
              <input 
                type="checkbox"
                :checked="isNodeSelected(node)"
                @change="toggleNodeSelection(node)"
                @click="console.log('Checkbox clicked for node:', node.key)"
                class="folder-checkbox"
                style="pointer-events: auto; z-index: 10; position: relative; margin-right: 0.5rem;"
              />
              <i :class="getFolderIcon(node)" class="folder-icon"></i>
              <span>{{ node.name }}</span>
            </div>
          </template>
        </Column>
        <Column field="path" header="Path">
          <template #body="{ node }">
            <span class="folder-path">{{ node.path }}</span>
          </template>
        </Column>
      </TreeTable>
    </div>
    
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

    <Toast />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import TreeTable from 'primevue/treetable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import DataTable from 'primevue/datatable'
import Dialog from 'primevue/dialog'
import Tag from 'primevue/tag'
import InputText from 'primevue/inputtext'
import { useToast } from 'primevue/usetoast'
import Toast from 'primevue/toast'
import { useFolderStore } from '../stores'
import type { Run } from '../types/store'
import { runGroupKey } from '../utils/mergeRuns'
import { formatAcceptedTotalText } from '../utils/runDisplay'
import { getMethodTagStyle, getMethodIconClass } from '../config/pipelineDisplay'
import { runsApi } from '../webapi'
import type { IngestPreviewReingestItem } from '../webapi'
import DesktopSettings from './DesktopSettings.vue'

const emit = defineEmits(['ingestComplete'])

const toast = useToast()

// Use Pinia stores
const folderStore = useFolderStore()
const forceRescanOfIngested = ref(false)
const ingesting = ref(false)
const reingestDialogVisible = ref(false)
const pendingReingest = ref<IngestPreviewReingestItem[]>([])

type IngestRowStatus = 'idle' | 'pending' | 'success' | 'error'
const ingestStatusByGroupKey = ref<Record<string, IngestRowStatus>>({})

watch(
  () => folderStore.scanning,
  (v) => {
    if (v) ingestStatusByGroupKey.value = {}
  }
)

const ingestStatusFor = (row: Run): IngestRowStatus => {
  return ingestStatusByGroupKey.value[runGroupKey(row)] ?? 'idle'
}

const patchScanRowFromIngest = (outRun: Run) => {
  const gk = runGroupKey(outRun)
  const idx = folderStore.scanResults.findIndex((r) => runGroupKey(r) === gk)
  if (idx >= 0) {
    folderStore.scanResults[idx] = outRun
  }
  const sidx = folderStore.selectedRuns.findIndex((r) => runGroupKey(r) === gk)
  if (sidx >= 0) {
    folderStore.selectedRuns[sidx] = outRun
  }
}

// Local UI state (not shared across components)
const filters = ref<any>(null)

// Computed
const selectedFolderNodes = computed(() => {
  const selected: any[] = []
  for (const [key, value] of Object.entries(folderStore.selectedKeys)) {
    if (value !== null) {
      // Find the node in the folders tree
      const findNode = (nodes: any[], targetKey: string): any => {
        for (const node of nodes) {
          if (node.key === targetKey) {
            return node
          }
          if (node.children) {
            const found = findNode(node.children, targetKey)
            if (found) return found
          }
        }
        return null
      }
      
      const node = findNode(folderStore.folders, key)
      if (node) {
        selected.push(node)
      }
    }
  }
  return selected
})

// Methods
const loadFolders = async (path = '') => {
  try {
    await folderStore.fetchFolders(path)
  } catch (error) {
    console.error('Error loading folders:', error)
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to load folders',
      life: 3000
    })
  }
}

const refreshTree = async () => {
  try {
    // Clear current selection and expanded state to start fresh
    folderStore.clearSelection()
    folderStore.expandedKeys = {}
    
    // Reload the root folders
    await folderStore.fetchFolders()
    
    toast.add({
      severity: 'success',
      summary: 'Tree Refreshed',
      detail: 'File tree has been refreshed',
      life: 2000
    })
  } catch (error) {
    console.error('Error refreshing tree:', error)
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to refresh file tree',
      life: 3000
    })
  }
}

const loadChildren = async (node: any): Promise<void> => {
  console.log('loadChildren called for node:', node.path)
  try {
    await folderStore.loadChildren(node)
  } catch (error) {
    console.error('Error loading children:', error)
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to load folder children',
      life: 3000
    })
  }
}

const onNodeExpand = async (event: any): Promise<void> => {
  console.log('onNodeExpand called with event:', event)
  console.log('Event keys:', Object.keys(event))
  
  // For PrimeVue TreeTable lazy loading, the node data might be in a different property
  const node = event.node || event.data || event
  console.log('Node to expand:', node)
  
  if (!node) {
    console.error('No node data found in event')
    return
  }
  
  console.log('Node children:', node.children)
  console.log('Node has_children:', node.has_children)
  
  // For lazy loading, we need to load children when expanding
  if (node.has_children && !node.children) {
    console.log('Loading children for node:', node.path)
    await loadChildren(node)
  } else {
    console.log('Skipping load - conditions not met')
  }
}

const onNodeCollapse = (event: any): void => {
  console.log('onNodeCollapse called with event:', event)
}

const scanSelectedFolders = async () => {
  if (selectedFolderNodes.value.length === 0) return

  try {
    const runs = await folderStore.scanFolders(
      selectedFolderNodes.value.map((folder) => folder.path),
      { forceRescanOfIngested: forceRescanOfIngested.value }
    )

    toast.add({
      severity: 'success',
      summary: 'Scan Complete',
      detail: `Found ${runs.length} runs in selected folders`,
      life: 3000
    })
  } catch (error) {
    console.error('Error scanning folders:', error)
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to scan selected folders',
      life: 3000
    })
  }
}

const clearSelection = () => {
  folderStore.clearSelection()
}

const doIngest = async (rows: Run[]) => {
  ingesting.value = true
  try {
    for (const row of rows) {
      const gk = runGroupKey(row)
      ingestStatusByGroupKey.value = { ...ingestStatusByGroupKey.value, [gk]: 'pending' }
      try {
        const res = await runsApi.ingestRuns([row as unknown as Record<string, unknown>])
        const outRun = res.runs[0] as Run | undefined
        if (outRun) {
          patchScanRowFromIngest(outRun)
        }
        ingestStatusByGroupKey.value = { ...ingestStatusByGroupKey.value, [gk]: 'success' }
      } catch (err) {
        ingestStatusByGroupKey.value = { ...ingestStatusByGroupKey.value, [gk]: 'error' }
        throw err
      }
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

const ingestSelectedRuns = async () => {
  const rows = folderStore.selectedRuns
  if (rows.length === 0) {
    toast.add({
      severity: 'warn',
      summary: 'Nothing selected',
      detail: 'Select one or more rows in the scan results table before ingesting.',
      life: 4000
    })
    return
  }
  try {
    const preview = await runsApi.ingestPreview(
      rows as unknown as Record<string, unknown>[]
    )
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
  await doIngest(folderStore.selectedRuns)
}

const onReingestDialogHide = () => {
  pendingReingest.value = []
}

const onNodeSelect = (event: any): void => {
  console.log('Node selected:', event.node)
  console.log('Current selectedKeys:', folderStore.selectedKeys)
}

const onNodeUnselect = (event: any): void => {
  console.log('Node unselected:', event.node)
  console.log('Current selectedKeys:', folderStore.selectedKeys)
}

const getFolderIcon = (node: any): string => {
  if (node.has_children) {
    return 'pi pi-folder-open'
  }
  return 'pi pi-folder'
}

const isNodeSelected = (node: any): boolean => {
  const result = folderStore.selectedKeys[node.key] === true
  console.log('isNodeSelected for node:', node.key, 'result:', result, 'selectedKeys:', folderStore.selectedKeys)
  return result
}

const toggleNodeSelection = (node: any): void => {
  console.log('toggleNodeSelection called for node:', node.key)
  console.log('Current selectedKeys before toggle:', folderStore.selectedKeys)
  
  folderStore.toggleNodeSelection(node.key)
  
  console.log('Selected keys after toggle:', folderStore.selectedKeys)
  console.log('isNodeSelected result:', isNodeSelected(node))
}

// Lifecycle
onMounted(async () => {
  await loadFolders()
  // After loading folders, check if any nodes should be expanded based on persisted state
  await restoreExpandedState()
})

// Restore expanded state for nodes that were previously expanded
const restoreExpandedState = async () => {
  const expandedKeys = folderStore.expandedKeys
  const keysToExpand = Object.keys(expandedKeys).filter(key => expandedKeys[key] === true)
  
  if (keysToExpand.length === 0) return
  
  // Sort keys by depth (shallowest first) to ensure parent nodes are loaded before children
  const sortedKeys = keysToExpand.sort((a, b) => {
    const depthA = (a.match(/\//g) || []).length
    const depthB = (b.match(/\//g) || []).length
    return depthA - depthB
  })
  
  // Load children for each expanded node, starting with the shallowest
  for (const key of sortedKeys) {
    const node = findNodeByKey(folderStore.folders, key)
    if (node && node.has_children && !node.children) {
      try {
        await loadChildren(node)
        // After loading children, recursively check if any of the children also need to be expanded
        await restoreExpandedStateRecursive(node.children, expandedKeys)
      } catch (error) {
        console.error('Error restoring expanded state for node:', key, error)
      }
    }
  }
}

// Recursively restore expanded state for nested nodes
const restoreExpandedStateRecursive = async (nodes: any[], expandedKeys: Record<string, boolean>) => {
  if (!nodes) return
  
  for (const node of nodes) {
    if (expandedKeys[node.key] === true && node.has_children && !node.children) {
      try {
        await loadChildren(node)
        // Continue recursively for any children that were also expanded
        if (node.children) {
          await restoreExpandedStateRecursive(node.children, expandedKeys)
        }
      } catch (error) {
        console.error('Error restoring expanded state for nested node:', node.key, error)
      }
    }
  }
}

// Helper function to find a node by its key
const findNodeByKey = (nodes: any[], targetKey: string): any => {
  for (const node of nodes) {
    if (node.key === targetKey) {
      return node
    }
    if (node.children) {
      const found = findNodeByKey(node.children, targetKey)
      if (found) return found
    }
  }
  return null
}
</script>

<style scoped>
.folder-browser {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.browser-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 1rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #e9ecef;
}

.browser-header h2 {
  margin: 0;
  color: #495057;
}

.header-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.75rem;
}

.browser-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: flex-end;
}

.scan-options {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.scan-options label {
  cursor: pointer;
  color: #495057;
  font-size: 0.95rem;
}

.reingest-lead {
  margin: 0 0 0.75rem 0;
  color: #495057;
  line-height: 1.5;
}

.reingest-list {
  margin: 0;
  padding-left: 1.25rem;
  color: #495057;
}

.reingest-list li {
  margin-bottom: 0.35rem;
}

.browser-content {
  min-height: 100px;
}

.folder-node {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.folder-checkbox {
  margin-right: 0.5rem;
  pointer-events: auto !important;
  z-index: 10 !important;
  position: relative !important;
}

/* Ensure checkbox is clickable and visible */
:deep(.folder-checkbox .p-checkbox) {
  pointer-events: auto !important;
  cursor: pointer !important;
  z-index: 10 !important;
  position: relative !important;
}

:deep(.folder-checkbox .p-checkbox .p-checkbox-box) {
  pointer-events: auto !important;
  cursor: pointer !important;
  z-index: 10 !important;
  position: relative !important;
}

:deep(.folder-checkbox input[type="checkbox"]) {
  pointer-events: auto !important;
  cursor: pointer !important;
  z-index: 10 !important;
  position: relative !important;
}

.folder-icon {
  color: #6c757d;
}

.folder-path {
  font-family: monospace;
  font-size: 0.9rem;
  color: #6c757d;
  word-break: break-all;
}


.scan-results {
  background: #f8f9fa;
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid #e9ecef;
  margin-bottom: 1rem;
}

.scan-results h3 {
  margin: 0 0 0.5rem 0;
  color: #495057;
}

.scan-results-hint {
  margin: 0 0 1rem 0;
  font-size: 0.9rem;
  color: #6c757d;
}

.ingest-actions {
  margin-bottom: 1rem;
}

.run-path {
  font-family: monospace;
  font-size: 0.9rem;
  color: #6c757d;
  word-break: break-all;
}

.run-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.run-type-icon {
  color: #6c757d;
}

.results-file {
  font-family: monospace;
  font-size: 0.9rem;
  color: #6c757d;
  word-break: break-all;
}

/* PrimeVue overrides */
:deep(.p-treetable) {
  border: 1px solid #e9ecef;
  border-radius: 8px;
}

:deep(.p-treetable .p-treetable-thead > tr > th) {
  background: #f8f9fa;
  border-bottom: 1px solid #e9ecef;
  font-weight: 600;
}

:deep(.p-treetable .p-treetable-tbody > tr > td) {
  border-bottom: 1px solid #f1f3f4;
}

:deep(.p-treetable .p-treetable-tbody > tr:hover > td) {
  background: #f8f9fa;
}

/* Ensure checkboxes are visible */
:deep(.p-treetable .p-checkbox) {
  margin-right: 0.5rem;
}

:deep(.p-treetable .p-checkbox .p-checkbox-box) {
  border: 1px solid #dee2e6;
  background: white;
}

:deep(.p-treetable .p-checkbox .p-checkbox-box.p-highlight) {
  background: #667eea;
  border-color: #667eea;
}

.ingest-ok {
  color: var(--p-green-500, #22c55e);
  font-weight: 600;
}

.ingest-err {
  color: var(--p-red-500, #ef4444);
}

.ingest-pending {
  color: var(--p-text-muted-color, #6c757d);
}

</style>
