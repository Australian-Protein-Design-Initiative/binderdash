<template>
  <div class="designs-view">
    <div class="designs-header">
      <h2>Designs</h2>
      <div class="designs-controls">
        <!-- Controls removed - designs now auto-sync with selected runs -->
      </div>
    </div>

    <FilterChainSummary
      v-if="designsStore.selectedRunIds.length > 0 || designsStore.selectedSavedSetIds.length > 0"
      show-edit-filters-link
    />

          <div class="designs-content">
        <div class="designs-table-section">
          <DataTable
          ref="designsTableRef"
          :value="designsStore.filteredDesigns" 
          :loading="designsStore.loading"
          v-model:multiSortMeta="designsStore.tableMultiSortMeta"
          v-model:first="designsStore.tableFirst"
          sortMode="multiple"
          stripedRows
          paginator
          :rows="12"
          :rowsPerPageOptions="[12, 24, 48, 96]"
          paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
          currentPageReportTemplate="Showing {first} to {last} of {totalRecords} designs"
          showGridlines
          :resizableColumns="true"
          columnResizeMode="fit"
          :reorderableColumns="true"
          :reorderableRows="true"
          :rowHover="true"
          :scrollable="true"
          scrollHeight="800px"
          :selectOnClick="false"
          @row-click="onRowClick"
        >
          <template #header>
            <div class="designs-table-toolbar">
              <div class="designs-export-panel flex flex-column gap-2">
                <div class="designs-download-upload-row flex align-items-center">
                  <SplitButton 
                    :model="exportMenuItems"
                    label="Download Design Bundle (zip)"
                    icon="pi pi-box"
                    severity="secondary"
                    dropdownIcon="pi pi-chevron-down"
                    :loading="bundleDownloading"
                    @click="onDownloadBundle"
                    size="small"
                  />
                  <SplitButton
                    :model="mergeUploadMenuItems"
                    label="Upload extra data (TSV)"
                    icon="pi pi-upload"
                    severity="secondary"
                    dropdownIcon="pi pi-chevron-down"
                    size="small"
                    :disabled="designsStore.selectedRunIds.length === 0"
                    @click="openMergeTableDialog('tsv')"
                  />
                </div>
                <div class="flex align-items-center gap-1">
                  <Checkbox 
                    :modelValue="exportIncludeAllColumns"
                    @update:modelValue="val => exportIncludeAllColumns = !!val"
                    :binary="true"
                    inputId="include-all-cols"
                  />
                  <label for="include-all-cols" class="text-sm">Include all columns</label>
                </div>
              </div>
              <div class="designs-toolbar-row">
                <div class="designs-column-selector flex align-items-center">
                  <label for="designs-column-multiselect" class="text-sm font-medium">Show Columns:</label>
                  <MultiSelect
                    id="designs-column-multiselect"
                    v-model="visibleColumnFields"
                    :options="columnSelectOptions"
                    option-label="header"
                    option-value="field"
                    placeholder="Select columns"
                    filter
                    filter-placeholder="Search columns…"
                    display="chip"
                    :max-selected-labels="3"
                    selected-items-label="{0} columns shown"
                    :show-toggle-all="true"
                    :disabled="columnSelectOptions.length === 0"
                    class="designs-column-multiselect"
                    v-tooltip.bottom="'Choose which columns appear in the table'"
                  />
                </div>
                <div class="designs-toolbar-divider" aria-hidden="true" />
                <div class="select-top-controls">
                  <label for="select-top-count" class="text-sm font-medium">Select top:</label>
                  <InputNumber 
                    v-model="selectTopCount"
                    :min="1"
                    :max="Math.max(1, designsStore.filteredDesigns.length)"
                    placeholder="N"
                    size="small"
                    inputId="select-top-count"
                    class="select-top-input"
                    @input="(event) => selectTopCount = Number(event.value)"
                  />
                  <Button 
                    label="Select"
                    severity="secondary"
                    @click="selectTopRows"
                    size="small"
                    :disabled="!selectTopCount || selectTopCount < 1"
                  />
                </div>
              </div>
            </div>
          </template>

          <template #empty>
            <div class="text-center p-4">
              <i class="pi pi-table" style="font-size: 3rem; color: #6c757d;"></i>
              <h3>No Designs Found</h3>
              <p>Scan some folders and select runs to see designs here</p>
            </div>
          </template>

          <template #loading>
            <div class="text-center p-4">
              <i class="pi pi-spinner pi-spin" style="font-size: 2rem; color: #667eea;"></i>
              <p>Loading designs...</p>
            </div>
          </template>

          <Column
            headerStyle="width: 3rem"
            :exportable="false"
            headerClass="row-selection-cell"
            bodyClass="row-selection-cell"
          >
            <template #header>
              <Checkbox
                :modelValue="designsStore.tableHeaderSelectionChecked"
                :indeterminate="designsStore.tableHeaderSelectionIndeterminate"
                binary
                @update:modelValue="onTableHeaderSelectAllChange"
              />
            </template>
            <template #body="{ data }">
              <Checkbox
                :modelValue="designsStore.isDesignSelected(data)"
                binary
                @update:modelValue="(v) => designsStore.toggleDesignSelected(data, !!v)"
              />
            </template>
          </Column>

          <Column
            v-if="rankingColumn"
            :key="rankingColumn.field"
            :field="rankingColumn.field"
            :header="rankingColumn.header"
            :sortable="rankingColumn.sortable"
            :filter="rankingColumn.filter"
            :filterType="rankingColumn.filterType || 'text'"
            :showFilterMenu="rankingColumn.showFilterMenu"
            :style="rankingColumn.style"
          />

          <!-- Dynamic columns based on available data -->
          <Column 
            v-for="col in getVisibleColumns()" 
            :key="col.field"
            :field="col.field" 
            :header="col.header"
            :sortable="col.sortable"
            :filter="col.filter"
            :filterType="col.filterType || 'text'"
            :showFilterMenu="col.showFilterMenu"
            :style="col.style"
            :class="col.class"
          >
            <template #body="{ data }" v-if="col.field === 'good'">
              <span :class="['good-cell', goodCellModifier(data.good)]">
                <span
                  v-if="normalizeGood(data.good) === true"
                  class="good-cell-symbol"
                  title="Good"
                  aria-label="Good"
                >✓</span>
                <span
                  v-else-if="normalizeGood(data.good) === false"
                  class="good-cell-symbol"
                  title="Not good"
                  aria-label="Not good"
                >✗</span>
                <span v-else class="good-cell-dash" aria-label="Not rated">—</span>
              </span>
            </template>
            <template #body="{ data }" v-else-if="col.template">
              <component :is="col.template" :data="data" :field="col.field" />
            </template>
          </Column>

          <Column header="Actions" style="width: 180px" :exportable="false" :frozen="true" alignFrozen="right">
            <template #body="{ data }">
              <div class="action-buttons">
                <Button 
                  icon="pi pi-eye" 
                  size="small"
                  severity="secondary"
                  variant="outlined"
                  @click="viewDesign(data)"
                  rounded
                  tooltip="View Structure"
                />
                <Button 
                  icon="pi pi-download" 
                  size="small"
                  severity="secondary"
                  variant="outlined"
                  @click="downloadPdb(data)"
                  rounded
                  tooltip="Download PDB"
                />
                <Button 
                  icon="pi pi-code" 
                  size="small"
                  severity="secondary"
                  variant="outlined"
                  @click="openParamsDialog(data)"
                  rounded
                  :disabled="!data?.params"
                  tooltip="View Params JSON"
                />
              </div>
            </template>
          </Column>
        </DataTable>
      </div>

      <!-- Structure Viewer Section -->
      <div v-if="designsStore.selectedDesignCount > 0" class="structure-viewer-section">
        <div class="viewer-header">
          <h3>Structure Viewer</h3>
        </div>

        <div class="structure-info">
          <div v-if="designsStore.currentStructure" class="structure-details">
            <div class="details-section">
              <div class="details-section-title">Design Data</div>
              <div class="details-grid">
                <div class="detail-item">
                  <div class="detail-label">Design</div>
                  <div class="detail-value">{{ designsStore.currentStructure.design.design_id }}</div>
                </div>
                <div class="detail-item">
                  <div class="detail-label">Project</div>
                  <div class="detail-value">{{ designsStore.currentStructure.design.project_id }}</div>
                </div>
                <div class="detail-item">
                  <div class="detail-label">Run</div>
                  <div class="detail-value">{{ designsStore.currentStructure.design.run_name }}</div>
                </div>
                <div class="detail-item">
                  <div class="detail-label">Method</div>
                  <div class="detail-value">{{ designsStore.currentStructure.design.method }}</div>
                </div>
                <div class="detail-item">
                  <div class="detail-label">Length</div>
                  <div class="detail-value">{{ getLengthValue(designsStore.currentStructure.design) }}</div>
                </div>
                <div class="detail-item file-item">
                  <div class="detail-label">File</div>
                  <div class="detail-value file-value">
                    <span class="file-name truncate-ellipsis" :title="designsStore.currentStructure.filename">{{ designsStore.currentStructure.filename }}</span>
                    <Button 
                      icon="pi pi-download" 
                      size="small"
                      rounded
                      @click.stop="downloadCurrentPdb"
                      :aria-label="`Download ${designsStore.currentStructure.filename}`"
                      v-tooltip.top="'Download PDB'"
                    />
                  </div>
                </div>
                <template
                  v-for="field in extraVisibleDesignDataFields"
                  :key="'dd-extra-' + field"
                >
                  <div class="detail-item">
                    <div class="detail-label-row">
                      <div class="detail-label">{{ columnHeaderForDetail(field) }}</div>
                    </div>
                    <div
                      class="detail-value truncate-ellipsis"
                      :title="String(getDetailFieldValue(designsStore.currentStructure.design, field) ?? '')"
                    >
                      {{ getDetailFieldValue(designsStore.currentStructure.design, field) }}
                    </div>
                  </div>
                </template>
              </div>
            </div>

            <div class="details-section">
              <div class="details-section-title">Scores</div>
              <div class="details-grid">
                <template v-for="scoreField in STRUCTURE_CARD_SCORE_ORDER" :key="scoreField">
                  <div
                    v-if="hasValidValue(getScoreValue(designsStore.currentStructure.design, scoreField))"
                    class="detail-item"
                  >
                    <div
                      class="score-bar"
                      :style="{ backgroundColor: scoreFieldColor(scoreField, getScoreValue(designsStore.currentStructure.design, scoreField)) }"
                    ></div>
                    <div class="detail-label-row">
                      <div class="detail-label">{{ formatScoreHeader(scoreField) }}</div>
                    </div>
                    <div class="detail-value">
                      {{ formatScore(getScoreValue(designsStore.currentStructure.design, scoreField)) }}
                    </div>
                  </div>
                </template>
                <template
                  v-for="scoreField in extraVisibleScoreFields"
                  :key="'sc-extra-' + scoreField"
                >
                  <div class="detail-item">
                    <div
                      class="score-bar"
                      :style="{
                        backgroundColor: extraScoreBarColor(
                          scoreField,
                          getDetailFieldValue(designsStore.currentStructure.design, scoreField)
                        )
                      }"
                    ></div>
                    <div class="detail-label-row">
                      <div class="detail-label">{{ columnHeaderForDetail(scoreField) }}</div>
                    </div>
                    <div class="detail-value">
                      {{ formatExtraScoreValue(getDetailFieldValue(designsStore.currentStructure.design, scoreField)) }}
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </div>

        <div class="viewer-container" ref="viewerContainerRef" v-if="designsStore.currentStructure">
          <MolstarViewer 
            :pdb-url="molstarPdbUrlForViewer"
            :reference-url="molstarReferenceUrlForViewer"
            reference-data-format="mmcif"
            :membrane-data="referenceMembraneData"
            :structure-info="designsStore.currentStructure"
            :auto-focus="true"
            :show-controls="false"
            :tag-overlay="tagOverlayMode"
            :tag-binder-chain="tagPlacementBinderChain"
            ref="molstarViewerRef"
            @structure-loaded="onViewerStructureLoaded"
          />
          <div
            ref="viewerControlsRef"
            class="viewer-controls"
            :style="viewerControlsStyle"
          >
            <div
              class="viewer-controls-drag"
              @pointerdown="onViewerControlsPointerDown"
              @dblclick.stop="resetViewerControlsPosition"
              role="button"
              tabindex="0"
              aria-label="Drag to reposition toolbar. Double-click to reset position."
              v-tooltip.top="viewerControlsDragTooltip"
            >
              <i class="pi pi-ellipsis-v" aria-hidden="true" />
            </div>
            <Button 
              icon="pi pi-chevron-left" 
              @click="navigateToPreviousRow"
              :disabled="!designsStore.canNavigatePrevious"
              text
              rounded
            />
            <span class="structure-counter">
              {{ getCurrentRowPosition() }}
            </span>
            <Button 
              icon="pi pi-chevron-right" 
              @click="navigateToNextRow"
              :disabled="!designsStore.canNavigateNext"
              text
              rounded
            />
            <Button 
              :icon="structureGood === true ? 'pi pi-thumbs-up-fill' : 'pi pi-thumbs-up'"
              @click="setStructureGood(true)"
              rounded
              severity="secondary"
              class="viewer-thumb-btn viewer-thumb-btn--good"
              :class="{ 'viewer-thumb-btn--selected': structureGood === true }"
              :disabled="!designsStore.currentStructure || goodRatingPending"
              v-tooltip.top="'Mark good (click again to clear)'"
              aria-label="Mark design good"
            />
            <Button 
              :icon="structureGood === false ? 'pi pi-thumbs-down-fill' : 'pi pi-thumbs-down'"
              @click="setStructureGood(false)"
              rounded
              severity="secondary"
              class="viewer-thumb-btn viewer-thumb-btn--bad"
              :class="{ 'viewer-thumb-btn--selected': structureGood === false }"
              :disabled="!designsStore.currentStructure || goodRatingPending"
              v-tooltip.top="'Not good (click again to clear)'"
              aria-label="Mark design not good"
            />
            <Button 
              :icon="isSpinning ? 'pi pi-pause' : 'pi pi-play'" 
              @click="toggleSpin"
              text
              rounded
              :tooltip="isSpinning ? 'Pause Rotation' : 'Start Rotation'"
            />
            <Button 
              label="pLDDT" 
              @click="toggleAlphaFoldView"
              text
              rounded
              :class="{ 'p-button-outlined': alphafoldViewEnabled, 'strikethrough-disabled': !alphafoldViewEnabled }"
              tooltip="Toggle AlphaFold pLDDT coloring"
            />
            <Button
              label="Ref"
              @click="toggleReferenceStructureVisibility"
              text
              rounded
              :disabled="!referenceViewerUrl"
              :class="{
                'p-button-outlined': referenceViewerUrl && !referenceStructureVisible,
                'strikethrough-disabled': referenceViewerUrl && !referenceStructureVisible,
              }"
              tooltip="Toggle reference structure visibility"
              aria-label="Toggle reference structure visibility"
            />
            <Button
              @click="cycleTagOverlay"
              text
              rounded
              v-tooltip.top="tagToolbarTooltip"
              :aria-label="tagToolbarTooltip"
              :disabled="!designsStore.currentStructure || tagToolbarPending"
            >
              <span class="tag-toolbar-label">
                Tag:
                <span
                  v-if="tagOverlayMode === 'N'"
                  class="tag-toolbar-mode tag-toolbar-mode--n"
                >N</span>
                <span
                  v-else-if="tagOverlayMode === 'C'"
                  class="tag-toolbar-mode tag-toolbar-mode--c"
                >C</span>
                <span v-else class="tag-toolbar-mode">off</span>
              </span>
            </Button>
          </div>
        </div>

        <!-- The contact map's colour key and range slider render here (teleported from
             the Target contact map panel below) so the gradient sits against the
             structure it describes rather than several sections further down. -->
        <div id="contact-map-legend-slot" class="contact-map-legend-slot"></div>

        <div v-if="designsStore.currentStructure" class="advanced-options-section">
          <button
            type="button"
            class="advanced-options-disclosure"
            @click="toggleAdvancedOptions"
            :aria-expanded="showAdvancedOptions"
            aria-controls="advanced-options-content"
            id="advanced-options-disclosure"
          >
            <i
              class="pi advanced-options-chevron"
              :class="showAdvancedOptions ? 'pi-chevron-down' : 'pi-chevron-right'"
              aria-hidden="true"
            />
            <span class="advanced-options-disclosure-label">Reference structure</span>
          </button>
          <div
            v-show="showAdvancedOptions"
            id="advanced-options-content"
            role="region"
            aria-labelledby="advanced-options-disclosure"
            class="advanced-options-expanded"
          >
            <div class="advanced-options-body">
            <div class="advanced-row">
              <Checkbox
                v-model="showInputTargetStructure"
                :binary="true"
                input-id="adv-input-target"
              />
              <label for="adv-input-target" class="advanced-checkbox-label">
                Show input target structure (from run params)
              </label>
            </div>
            <div
              v-if="showInputTargetStructure && inputTargetsList.length > 1"
              class="advanced-row advanced-row--full"
            >
              <label class="advanced-label">Input target</label>
              <Dropdown
                v-model="selectedInputTargetId"
                :options="inputTargetDropdownOptions"
                option-label="label"
                option-value="value"
                placeholder="Select structure"
                class="advanced-dropdown"
              />
            </div>
            <p
              v-if="showInputTargetStructure && inputTargetsList.length === 0 && !inputTargetsLoading"
              class="advanced-hint advanced-hint--warn"
            >
              No input target structure found in run params.
            </p>
            <template v-if="!showInputTargetStructure">
              <div class="advanced-row advanced-row--full">
                <div class="advanced-label advanced-label-with-info">
                  <label for="adv-reference-source">Reference structure</label>
                  <i
                    class="pi pi-info-circle advanced-reference-info-icon"
                    v-tooltip.top="referenceStructureTooltipOptions"
                    tabindex="0"
                    aria-label="Reference structure help"
                  />
                </div>
                <div class="advanced-reference-source-controls">
                  <Dropdown
                    v-model="referenceManualSourceKind"
                    :options="referenceSourceKindOptions"
                    option-label="label"
                    option-value="value"
                    input-id="adv-reference-source-kind"
                    aria-label="Reference structure source"
                    class="advanced-reference-source-kind"
                  />
                  <InputText
                    v-model="referenceManualSource"
                    id="adv-reference-source"
                    placeholder="PDB ID or https://… (.pdb / .mmCIF, .gz)"
                    class="advanced-input advanced-input--in-reference-row"
                    @keydown.enter="onReferenceManualEnter"
                  />
                </div>
              </div>
            </template>
            <div class="advanced-row advanced-row--full">
              <label for="adv-reference-chains" class="advanced-label">Chains</label>
              <InputText
                v-model="referenceChainIdsInput"
                id="adv-reference-chains"
                placeholder="Optional — comma or space separated (e.g. A, B); TM-align and overlay use only these reference chains"
                class="advanced-input"
                @keydown.enter="onReferenceManualEnter"
              />
            </div>
            <div class="advanced-actions">
              <Button
                label="Load reference"
                icon="pi pi-sync"
                @click="() => loadReferenceOverlay()"
                :loading="referenceLoading"
                :disabled="!canLoadReferenceOverlay"
              />
              <Button
                label="Clear"
                icon="pi pi-times"
                severity="secondary"
                variant="outlined"
                @click="clearReferenceOverlay"
                :disabled="!referenceOverlayActive && !referenceViewerUrl"
              />
            </div>
            <div v-if="referenceMetrics" class="reference-metrics">
              <span>TM-score (design norm): {{ referenceMetrics.tmNormDesign.toFixed(3) }}</span>
              <span>TM-score (reference norm): {{ referenceMetrics.tmNormReference.toFixed(3) }}</span>
              <span>RMSD: {{ referenceMetrics.rmsd.toFixed(3) }} Å</span>
              <span>Aligned length: {{ referenceMetrics.alignedLength }}</span>
            </div>
            </div>
          </div>
        </div>

        <div v-if="designsStore.currentStructure" class="advanced-options-section">
          <button
            type="button"
            class="advanced-options-disclosure"
            @click="toggleTagPlacementOptions"
            :aria-expanded="showTagPlacementOptions"
            aria-controls="tag-placement-content"
            id="tag-placement-disclosure"
          >
            <i
              class="pi advanced-options-chevron"
              :class="showTagPlacementOptions ? 'pi-chevron-down' : 'pi-chevron-right'"
              aria-hidden="true"
            />
            <span class="advanced-options-disclosure-label">Tag placement</span>
          </button>
          <div
            v-show="showTagPlacementOptions"
            id="tag-placement-content"
            role="region"
            aria-labelledby="tag-placement-disclosure"
            class="advanced-options-expanded"
          >
            <div class="advanced-options-body">
              <p class="tag-metrics-hint">
                Metrics use the current parameters below. Values appear from cache when available, or after
                <strong> Auto detect</strong> runs. Otherwise cells show —.
                {{ !designsStore.selectedDesignCount ? ' Select design(s) in the table above.' : '' }}
              </p>
              <DataTable
                v-if="designsStore.selectedDesignCount"
                v-model:first="tagMetricsFirst"
                class="tag-metrics-datatable"
                :value="tagMetricsRows"
                :loading="tagMetricsLoading"
                dataKey="_tmKey"
                size="small"
                paginator
                v-model:rows="tagMetricsPageSize"
                :rowsPerPageOptions="[1, 5, 10, 25]"
                paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
                currentPageReportTemplate="{first}–{last} of {totalRecords}"
                showGridlines
                scrollable
                scrollHeight="280px"
              >
                <Column field="design_id" header="Design ID" :style="{ minWidth: '120px' }" frozen />
                <Column field="n_aa_type" header="N aa" :style="{ minWidth: '64px' }" />
                <Column field="c_aa_type" header="C aa" :style="{ minWidth: '64px' }" />
                <Column header="N SASA" :style="{ minWidth: '72px' }">
                  <template #body="{ data }">{{ formatTagMetricNum(data.n_sasa) }}</template>
                </Column>
                <Column header="C SASA" :style="{ minWidth: '72px' }">
                  <template #body="{ data }">{{ formatTagMetricNum(data.c_sasa) }}</template>
                </Column>
                <Column header="N % SASA" :style="{ minWidth: '80px' }">
                  <template #body="{ data }">{{ formatTagMetricNum(data.n_percent_sasa) }}</template>
                </Column>
                <Column header="C % SASA" :style="{ minWidth: '80px' }">
                  <template #body="{ data }">{{ formatTagMetricNum(data.c_percent_sasa) }}</template>
                </Column>
                <Column header="N % buried" :style="{ minWidth: '88px' }">
                  <template #body="{ data }">
                    <span :class="tagMetricsCellMutedClass(data.n_percent_sasa)">{{ formatTagMetricNum(data.n_percent_buried) }}</span>
                  </template>
                </Column>
                <Column header="C % buried" :style="{ minWidth: '88px' }">
                  <template #body="{ data }">
                    <span :class="tagMetricsCellMutedClass(data.c_percent_sasa)">{{ formatTagMetricNum(data.c_percent_buried) }}</span>
                  </template>
                </Column>
                <Column header="N–C (Å)" :style="{ minWidth: '72px' }">
                  <template #body="{ data }">{{ formatTagMetricNum(data.n_c_dist) }}</template>
                </Column>
                <Column header="N→tgt (Å)" :style="{ minWidth: '80px' }">
                  <template #body="{ data }">
                    <span :class="tagMetricsTgtDistClass(data, 'n')">{{ formatTagMetricNum(data.n_dist_target) }}</span>
                  </template>
                </Column>
                <Column header="C→tgt (Å)" :style="{ minWidth: '80px' }">
                  <template #body="{ data }">
                    <span :class="tagMetricsTgtDistClass(data, 'c')">{{ formatTagMetricNum(data.c_dist_target) }}</span>
                  </template>
                </Column>
                <Column header="N tgt hit" :style="{ minWidth: '72px' }">
                  <template #body="{ data }">
                    <span :class="tagMetricsHitClass(data.n_target_contacts)">{{ formatTagMetricBool(data.n_target_contacts) }}</span>
                  </template>
                </Column>
                <Column header="C tgt hit" :style="{ minWidth: '72px' }">
                  <template #body="{ data }">
                    <span :class="tagMetricsHitClass(data.c_target_contacts)">{{ formatTagMetricBool(data.c_target_contacts) }}</span>
                  </template>
                </Column>
                <Column header="Predicted" :style="{ minWidth: '88px' }">
                  <template #body="{ data }">
                    <span v-if="data.error" class="tag-metrics-error">—</span>
                    <span
                      v-else-if="String(data.predicted_tag ?? '').trim().toUpperCase() === 'N'"
                      class="tag-metrics-pred tag-metrics-pred--n"
                    >N</span>
                    <span
                      v-else-if="String(data.predicted_tag ?? '').trim().toUpperCase() === 'C'"
                      class="tag-metrics-pred tag-metrics-pred--c"
                    >C</span>
                    <span v-else>{{ data.predicted_tag ?? '—' }}</span>
                  </template>
                </Column>
                <Column field="pdb_file" header="Structure file" :style="{ minWidth: '140px' }" />
                <Column header="Sequence" :style="{ minWidth: '100px', maxWidth: '140px' }">
                  <template #body="{ data }">
                    <span
                      class="tag-metrics-seq"
                      :title="data.sequence || undefined"
                    >{{ data.sequence || '—' }}</span>
                  </template>
                </Column>
                <Column header="Error" :style="{ minWidth: '160px' }">
                  <template #body="{ data }">
                    <span v-if="data.error" class="tag-metrics-error">{{ data.error }}</span>
                    <span v-else>—</span>
                  </template>
                </Column>
              </DataTable>
              <div
                v-if="tagPlacementLoading && tagPlacementProgressTotal > 0"
                class="tag-placement-progress"
              >
                <ProgressBar :value="tagPlacementProgressPercent" />
                <span class="tag-placement-progress-label">
                  {{ tagPlacementProgressCurrent }} / {{ tagPlacementProgressTotal }}
                </span>
              </div>
              <div class="advanced-actions advanced-actions--tag-top">
                <Button
                  label="Auto detect"
                  icon="pi pi-bolt"
                  @click="runTagPlacementAutoDetect"
                  :loading="tagPlacementLoading"
                  :disabled="designsStore.selectedDesignCount === 0"
                />
              </div>
              <div class="advanced-row">
                <Checkbox
                  v-model="tagPlacementIgnoreCache"
                  input-id="tag-ignore-cache"
                  :binary="true"
                />
                <label for="tag-ignore-cache" class="advanced-checkbox-label">
                  Ignore cache, force recalculate (next Auto detect only)
                </label>
              </div>
              <div class="advanced-row">
                <Checkbox
                  v-model="tagPlacementOnlyEmptyTags"
                  input-id="tag-only-empty"
                  :binary="true"
                />
                <label for="tag-only-empty" class="advanced-checkbox-label">
                  Only assign empty tags
                </label>
              </div>
              <div class="advanced-row advanced-row--full">
                <label for="tag-binder-chain" class="advanced-label">Binder chain</label>
                <InputText
                  id="tag-binder-chain"
                  v-model="tagPlacementBinderChain"
                  maxlength="4"
                  class="advanced-input"
                  placeholder="B"
                />
              </div>
              <div class="advanced-row advanced-row--full">
                <label for="tag-target-chains" class="advanced-label">Target chain(s)</label>
                <InputText
                  id="tag-target-chains"
                  v-model="tagPlacementTargetChains"
                  class="advanced-input"
                  placeholder="Comma or space separated, e.g. A or HL"
                />
              </div>
              <div class="advanced-row advanced-row--full">
                <label for="tag-distant-from" class="advanced-label">Distant from</label>
                <InputText
                  id="tag-distant-from"
                  v-model="tagPlacementDistantFrom"
                  class="advanced-input"
                  placeholder="e.g. A118,A142 (optional)"
                />
              </div>
              <div class="advanced-row advanced-row--full">
                <label for="tag-sasa-probe" class="advanced-label">SASA probe radius (Å)</label>
                <InputNumber
                  id="tag-sasa-probe"
                  v-model="tagPlacementSasaProbe"
                  :min="0.1"
                  :max="4"
                  :step="0.1"
                  :show-buttons="true"
                  class="tag-placement-input-number"
                />
              </div>
              <div class="advanced-row advanced-row--full">
                <label for="tag-sasa-points" class="advanced-label">SASA sphere points</label>
                <InputNumber
                  id="tag-sasa-points"
                  v-model="tagPlacementSasaPoints"
                  :min="20"
                  :max="500"
                  :step="10"
                  :show-buttons="true"
                  class="tag-placement-input-number"
                />
              </div>
              <div class="advanced-row advanced-row--full">
                <label for="tag-sasa-threshold" class="advanced-label">SASA threshold (%)</label>
                <InputNumber
                  id="tag-sasa-threshold"
                  v-model="tagPlacementSasaThreshold"
                  :min="0"
                  :max="100"
                  :step="1"
                  :show-buttons="true"
                  class="tag-placement-input-number"
                />
              </div>
              <div class="advanced-row advanced-row--full">
                <label for="tag-more-dist" class="advanced-label">More distant threshold (Å)</label>
                <InputNumber
                  id="tag-more-dist"
                  v-model="tagPlacementMoreDist"
                  :min="0"
                  :max="50"
                  :step="0.5"
                  :show-buttons="true"
                  class="tag-placement-input-number"
                />
              </div>
            </div>
          </div>

        <div v-if="designsStore.currentStructure" class="advanced-options-section">
          <button
            type="button"
            class="advanced-options-disclosure"
            @click="toggleContactMapOptions"
            :aria-expanded="showContactMapOptions"
            aria-controls="contact-map-content"
            id="contact-map-disclosure"
          >
            <i
              class="pi advanced-options-chevron"
              :class="showContactMapOptions ? 'pi-chevron-down' : 'pi-chevron-right'"
              aria-hidden="true"
            />
            <span class="advanced-options-disclosure-label">Target contact map</span>
          </button>
          <div
            v-show="showContactMapOptions"
            id="contact-map-content"
            role="region"
            aria-labelledby="contact-map-disclosure"
            class="advanced-options-expanded"
          >
            <div class="advanced-options-body">
              <TargetContactMapPanel
                ref="contactMapPanelRef"
                :run-id="contactMapRunId"
                :selected-design-keys="contactMapSelectedKeys"
                @apply="applyContactMapColors"
                @clear="clearContactMapColors"
              />
            </div>
          </div>
        </div>
        </div>
      </div>

      <div v-else class="no-selection">
        <div class="no-selection-content">
          <i class="pi pi-cube" style="font-size: 3rem; color: #6c757d;"></i>
          <h3>No Structures Selected</h3>
          <p>Select one or more designs from the table above to view structures</p>
        </div>
      </div>
    </div>
    
    <Toast />

  <Dialog
    v-model:visible="bundleConfirmVisible"
    modal
    header="Large download"
    :style="{ width: '32rem' }"
  >
    <p class="mb-3">
      This bundle is about
      <strong>{{ formatBytes(bundleEstimate?.estimated_zip_bytes ?? 0) }}</strong>
      across {{ bundleEstimate?.structure_count ?? 0 }} structure file(s). The browser holds
      the whole archive in memory while it downloads.
    </p>
    <p class="mb-0 text-sm text-color-secondary">
      Narrow the selection or the active filters for a smaller bundle.
    </p>
    <template #footer>
      <Button label="Cancel" severity="secondary" text @click="bundleConfirmVisible = false" />
      <Button
        label="Download anyway"
        icon="pi pi-download"
        :loading="bundleDownloading"
        @click="runBundleDownload"
      />
    </template>
  </Dialog>

  <Dialog 
    v-model:visible="showParamsDialog" 
    modal 
    header="Run Parameters"
    :style="{ width: '60vw', maxWidth: '900px' }"
  >
    <div v-if="currentParamsJson" class="params-json-container">
      <pre class="params-pre">{{ currentParamsJson }}</pre>
    </div>
    <div v-else class="text-center p-3">No params available for this design</div>
  </Dialog>

  <Dialog
    v-model:visible="showMergeTableDialog"
    modal
    header="Upload extra data"
    :style="{ width: '32rem', maxWidth: '95vw' }"
  >
    <p class="text-sm m-0 mb-3">
      Upload a table with <code>design_id</code> (or equivalent). New columns are stored as annotations
      and survive re-ingest. Keys that already exist in pipeline data are skipped.
    </p>
    <div class="flex flex-column gap-3">
      <input
        ref="mergeTableFileInputRef"
        type="file"
        :accept="mergeTableFileAccept"
        style="display: none"
        @change="onMergeTableFileChange"
      />
      <div class="flex gap-2 align-items-center flex-wrap">
        <Button
          label="Choose file"
          icon="pi pi-file"
          size="small"
          severity="secondary"
          @click="mergeTableFileInputRef?.click()"
        />
        <span v-if="mergeTableFile" class="text-sm">{{ mergeTableFile.name }}</span>
        <span v-else class="text-sm text-color-secondary">No file selected</span>
      </div>
      <div class="flex flex-column gap-1">
        <label for="merge-design-id-col" class="text-sm font-medium">Design ID column (optional)</label>
        <InputText
          id="merge-design-id-col"
          v-model="mergeTableDesignIdColumn"
          placeholder="design_id"
          size="small"
        />
      </div>
      <div v-if="mergeTablePreview" class="merge-table-preview text-sm">
        <p class="m-0"><strong>Design ID column:</strong> {{ mergeTablePreview.design_id_column }}</p>
        <p class="m-0"><strong>Upload rows:</strong> {{ mergeTablePreview.upload_row_count }}</p>
        <p class="m-0"><strong>Matched designs:</strong> {{ mergeTablePreview.matched_design_count }}</p>
        <p class="m-0"><strong>Unknown design IDs:</strong> {{ mergeTablePreview.unknown_design_id_count }}</p>
        <p v-if="mergeTablePreview.new_columns?.length" class="m-0">
          <strong>New columns:</strong> {{ mergeTablePreview.new_columns.join(', ') }}
        </p>
        <p
          v-if="mergeTablePreview.pipeline_collision_columns?.length"
          class="m-0 text-orange-500"
        >
          <strong>Skipped (pipeline):</strong>
          {{ mergeTablePreview.pipeline_collision_columns.join(', ') }}
        </p>
        <p v-if="mergeTablePreview.preview" class="m-0">
          <strong>Would update:</strong> {{ mergeTablePreview.would_update_rows ?? 0 }} row(s)
        </p>
        <p v-if="!mergeTablePreview.preview && mergeTablePreview.updated != null" class="m-0">
          <strong>Updated:</strong> {{ mergeTablePreview.updated }} row(s)
        </p>
      </div>
    </div>
    <template #footer>
      <Button label="Cancel" severity="secondary" text @click="showMergeTableDialog = false" />
      <Button
        label="Preview"
        icon="pi pi-eye"
        severity="secondary"
        :loading="mergeTablePending"
        :disabled="!mergeTableFile"
        @click="runMergeTablePreview"
      />
      <Button
        label="Merge"
        icon="pi pi-check"
        :loading="mergeTablePending"
        :disabled="!mergeTableFile || !mergeTablePreview"
        @click="runMergeTableApply"
      />
    </template>
  </Dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import InputSwitch from 'primevue/inputswitch'
import Dropdown from 'primevue/dropdown'
import SplitButton from 'primevue/splitbutton'
import MultiSelect from 'primevue/multiselect'
import ProgressBar from 'primevue/progressbar'
import { useToast } from 'primevue/usetoast'
import Toast from 'primevue/toast'
import Dialog from 'primevue/dialog'
import MolstarViewer from './MolstarViewer.vue'
import TargetContactMapPanel from './TargetContactMapPanel.vue'
import FilterChainSummary from './FilterChainSummary.vue'
import type { MembraneData } from '../membraneOverlay'
import { bundlesApi, designsApi, runsApi } from '../webapi'
import type { MergeTableResponse, TagMetricsRow, TagPlacementResultRow } from '../webapi'
import { useDesignsStore, useAppStore, useAuthStore } from '../stores'
import { buildSessionState } from '../session/sessionState'
import type { Design } from '../types/store'
import { PERSISTENCE_KEYS, tagPlacementKey, advRefKey } from '../persistence/keys'
import { kvGet, kvSet, kvRemove } from '../persistence/store'
import {
    BINDERDASH_RANKING_FIELD,
    STRUCTURE_CARD_SCORE_ORDER,
    niceNameForScoreField,
    scoreFieldColor,
} from '../config/pipelineDisplay'

const toast = useToast()
const designsTableRef = ref<{ d_columnOrder: string[] | null } | null>(null)

// Use Pinia stores
const designsStore = useDesignsStore()
const appStore = useAppStore()
const authStore = useAuthStore()

watch(
  () => designsStore.tableColumnOrderEpoch,
  () => {
    const table = designsTableRef.value
    if (table) table.d_columnOrder = null
  }
)

// Local UI state (not shared across components)
const showAdvancedOptions = ref(false)
const showTagPlacementOptions = ref(false)
const showContactMapOptions = ref(false)
const molstarViewerRef = ref<any>(null)
const contactMapPanelRef = ref<any>(null)

const tagOverlayMode = ref<'none' | 'N' | 'C'>('none')
const tagToolbarPending = ref(false)
const TAG_PLACEMENT_DEFAULTS = {
  binderChain: 'B',
  targetChains: '',
  distantFrom: '',
  sasaProbe: 1.4,
  sasaPoints: 100,
  sasaThreshold: 30,
  moreDist: 5,
  onlyEmptyTags: false,
} as const

const tagPlacementBinderChain = ref<string>(TAG_PLACEMENT_DEFAULTS.binderChain)
const tagPlacementTargetChains = ref<string>(TAG_PLACEMENT_DEFAULTS.targetChains)
const tagPlacementDistantFrom = ref<string>(TAG_PLACEMENT_DEFAULTS.distantFrom)
const tagPlacementSasaProbe = ref<number>(TAG_PLACEMENT_DEFAULTS.sasaProbe)
const tagPlacementSasaPoints = ref<number>(TAG_PLACEMENT_DEFAULTS.sasaPoints)
const tagPlacementSasaThreshold = ref<number>(TAG_PLACEMENT_DEFAULTS.sasaThreshold)
const tagPlacementMoreDist = ref<number>(TAG_PLACEMENT_DEFAULTS.moreDist)
const tagPlacementOnlyEmptyTags = ref<boolean>(TAG_PLACEMENT_DEFAULTS.onlyEmptyTags)
const tagPlacementIgnoreCache = ref(false)
const tagPlacementLoading = ref(false)
const tagPlacementProgressCurrent = ref(0)
const tagPlacementProgressTotal = ref(0)

const tagPlacementProgressPercent = computed(() => {
  const t = tagPlacementProgressTotal.value
  if (!t) return 0
  return Math.min(100, Math.round((tagPlacementProgressCurrent.value / t) * 100))
})

type TagMetricsTableRow = TagMetricsRow & { _tmKey: string }

const tagMetricsRows = ref<TagMetricsTableRow[]>([])
const tagMetricsLoading = ref(false)
const tagMetricsFirst = ref(0)
const tagMetricsPageSize = ref(1)
let tagMetricsDebounceTimer: ReturnType<typeof setTimeout> | null = null

const formatTagMetricNum = (v: number | null | undefined): string => {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

const formatTagMetricBool = (v: boolean | null | undefined): string => {
  if (v === true) return 'Yes'
  if (v === false) return 'No'
  return '—'
}

const tagMetricsCellMutedClass = (percentSasa: number | null | undefined): string => {
  const threshold = tagPlacementSasaThreshold.value
  if (percentSasa == null || Number.isNaN(Number(percentSasa))) return ''
  if (typeof threshold !== 'number' || Number.isNaN(Number(threshold))) return ''
  return Number(percentSasa) < threshold ? 'tag-metrics-cell tag-metrics-cell--muted' : 'tag-metrics-cell'
}

const tagMetricsTgtDistClass = (row: TagMetricsRow, which: 'n' | 'c'): string => {
  const n = row.n_dist_target
  const c = row.c_dist_target
  const nn = n == null || Number.isNaN(Number(n)) ? null : Number(n)
  const cc = c == null || Number.isNaN(Number(c)) ? null : Number(c)

  if (nn == null && cc == null) return ''
  if (nn != null && cc == null) return which === 'n' ? 'tag-metrics-cell tag-metrics-cell--highlight' : ''
  if (cc != null && nn == null) return which === 'c' ? 'tag-metrics-cell tag-metrics-cell--highlight' : ''
  if (nn != null && cc != null) {
    if (nn === cc) return 'tag-metrics-cell'
    if (which === 'n') return nn > cc ? 'tag-metrics-cell tag-metrics-cell--highlight' : 'tag-metrics-cell'
    return cc > nn ? 'tag-metrics-cell tag-metrics-cell--highlight' : 'tag-metrics-cell'
  }
  return ''
}

const tagMetricsHitClass = (v: boolean | null | undefined): string => {
  if (v === false) return 'tag-metrics-cell tag-metrics-cell--highlight'
  if (v === true) return 'tag-metrics-cell'
  return ''
}

/** Empty target → opposite chain for binder A/B; flipping A↔B updates target if it still matched the old default. */
const applyOppositeBinderDefaultTargetChains = (
  oldBinder: string | undefined,
  newBinder: string | undefined,
) => {
  const t = tagPlacementTargetChains.value.trim().toUpperCase()
  const o = oldBinder != null ? String(oldBinder).trim().toUpperCase() : ''
  const n = newBinder != null ? String(newBinder).trim().toUpperCase() : ''
  const opposite = (binder: string) => {
    if (binder === 'B') return 'A'
    if (binder === 'A') return 'B'
    return ''
  }
  const pn = opposite(n)
  if (t === '') {
    if (pn) tagPlacementTargetChains.value = pn
    return
  }
  const po = opposite(o)
  if (po && t === po && pn && t !== pn) {
    tagPlacementTargetChains.value = pn
  }
}

const makePlaceholderTagMetricsRow = (d: Design, index: number): TagMetricsTableRow => {
  const fn = designsStore.getStructureFilename(d)
  const sp = d.source_path != null ? String(d.source_path) : ''
  return {
    run_id: String(d.run_id),
    design_id: String(d.design_id),
    pdb_file: fn || undefined,
    _tmKey: `${d.run_id}:${d.design_id}:${index}:${sp}`,
  }
}

const tagMetricsDesignItems = () =>
  designsStore.selectedDesigns.map((d) => {
    const fn = designsStore.getStructureFilename(d)
    return {
      run_id: String(d.run_id),
      design_id: String(d.design_id),
      pdb_file: fn || undefined,
      source_path: d.source_path != null ? String(d.source_path) : undefined,
    }
  })

const TAG_PLACEMENT_BATCH_SIZE = 10

const chunkArray = <T,>(items: T[], size: number): T[][] => {
  const safe = Math.max(1, Math.floor(size))
  const out: T[][] = []
  for (let i = 0; i < items.length; i += safe) {
    out.push(items.slice(i, i + safe))
  }
  return out
}

const loadTagMetrics = async () => {
  tagMetricsFirst.value = 0
  if (!showTagPlacementOptions.value || !designsStore.selectedDesignCount) {
    tagMetricsRows.value = []
    return
  }
  const designs = designsStore.selectedDesigns
  tagMetricsRows.value = designs.map((d, i) => makePlaceholderTagMetricsRow(d, i))
  tagMetricsLoading.value = true
  try {
    const distant = tagPlacementDistantFrom.value.trim()
    const targetChains = tagPlacementTargetChains.value.trim()
    const res = await designsApi.postTagMetrics({
      designs: tagMetricsDesignItems(),
      binder_chain: tagPlacementBinderChain.value.trim() || 'B',
      target_chains: targetChains || null,
      distant_from: distant || null,
      sasa_probe_radius: tagPlacementSasaProbe.value,
      sasa_n_points: tagPlacementSasaPoints.value,
      sasa_threshold: tagPlacementSasaThreshold.value,
      more_distant_threshold: tagPlacementMoreDist.value,
      cache_only: true,
      ignore_cache: false,
    })
    for (let i = 0; i < tagMetricsRows.value.length; i++) {
      const prev = tagMetricsRows.value[i]
      const r = res.results[i]
      if (!prev || !r) continue
      if (r.run_id !== prev.run_id || r.design_id !== prev.design_id) continue
      tagMetricsRows.value[i] = { ...r, _tmKey: prev._tmKey }
    }
  } catch (e) {
    console.warn('Tag metrics load failed', e)
    tagMetricsRows.value = designs.map((d, i) => makePlaceholderTagMetricsRow(d, i))
  } finally {
    tagMetricsLoading.value = false
  }
}

const refreshTagMetricsRowsAfterPlacement = async (designs: Design[]) => {
  if (designs.length === 0) return
  const distant = tagPlacementDistantFrom.value.trim()
  const targetChains = tagPlacementTargetChains.value.trim()
  const res = await designsApi.postTagMetrics({
    designs: designs.map((d) => {
      const fn = designsStore.getStructureFilename(d)
      return {
        run_id: String(d.run_id),
        design_id: String(d.design_id),
        pdb_file: fn || undefined,
        source_path: d.source_path != null ? String(d.source_path) : undefined,
      }
    }),
    binder_chain: tagPlacementBinderChain.value.trim() || 'B',
    target_chains: targetChains || null,
    distant_from: distant || null,
    sasa_probe_radius: tagPlacementSasaProbe.value,
    sasa_n_points: tagPlacementSasaPoints.value,
    sasa_threshold: tagPlacementSasaThreshold.value,
    more_distant_threshold: tagPlacementMoreDist.value,
    cache_only: false,
    ignore_cache: false,
  })
  for (const r of res.results) {
    const idx = tagMetricsRows.value.findIndex(
      (row) => row.run_id === r.run_id && row.design_id === r.design_id,
    )
    if (idx >= 0) {
      tagMetricsRows.value[idx] = { ...r, _tmKey: tagMetricsRows.value[idx]._tmKey }
    }
  }
}

const scheduleTagMetricsLoad = () => {
  if (tagMetricsDebounceTimer) clearTimeout(tagMetricsDebounceTimer)
  tagMetricsDebounceTimer = setTimeout(() => {
    tagMetricsDebounceTimer = null
    void loadTagMetrics()
  }, 450)
}

watch(
  [
    showTagPlacementOptions,
    () => designsStore.selectedDesignCount,
    () => designsStore.selectAllFiltered,
    tagPlacementBinderChain,
    tagPlacementTargetChains,
    tagPlacementDistantFrom,
    tagPlacementSasaProbe,
    tagPlacementSasaPoints,
    tagPlacementSasaThreshold,
    tagPlacementMoreDist,
  ],
  () => scheduleTagMetricsLoad(),
  { immediate: true },
)

const applyTagPlacementDefaults = () => {
  tagPlacementBinderChain.value = TAG_PLACEMENT_DEFAULTS.binderChain
  tagPlacementTargetChains.value = TAG_PLACEMENT_DEFAULTS.targetChains
  tagPlacementDistantFrom.value = TAG_PLACEMENT_DEFAULTS.distantFrom
  tagPlacementSasaProbe.value = TAG_PLACEMENT_DEFAULTS.sasaProbe
  tagPlacementSasaPoints.value = TAG_PLACEMENT_DEFAULTS.sasaPoints
  tagPlacementSasaThreshold.value = TAG_PLACEMENT_DEFAULTS.sasaThreshold
  tagPlacementMoreDist.value = TAG_PLACEMENT_DEFAULTS.moreDist
  tagPlacementOnlyEmptyTags.value = TAG_PLACEMENT_DEFAULTS.onlyEmptyTags
  applyOppositeBinderDefaultTargetChains(undefined, tagPlacementBinderChain.value)
}

const persistTagPlacementSettings = (runId: string) => {
  const probe = tagPlacementSasaProbe.value
  const points = tagPlacementSasaPoints.value
  const threshold = tagPlacementSasaThreshold.value
  const moreDist = tagPlacementMoreDist.value
  void kvSet(tagPlacementKey(runId), {
    binderChain: tagPlacementBinderChain.value.trim() || TAG_PLACEMENT_DEFAULTS.binderChain,
    targetChains: tagPlacementTargetChains.value,
    distantFrom: tagPlacementDistantFrom.value,
    sasaProbe: typeof probe === 'number' && !Number.isNaN(probe) ? probe : TAG_PLACEMENT_DEFAULTS.sasaProbe,
    sasaPoints: typeof points === 'number' && !Number.isNaN(points) ? points : TAG_PLACEMENT_DEFAULTS.sasaPoints,
    sasaThreshold:
      typeof threshold === 'number' && !Number.isNaN(threshold)
        ? threshold
        : TAG_PLACEMENT_DEFAULTS.sasaThreshold,
    moreDist:
      typeof moreDist === 'number' && !Number.isNaN(moreDist) ? moreDist : TAG_PLACEMENT_DEFAULTS.moreDist,
    onlyAssignEmptyTags: tagPlacementOnlyEmptyTags.value === true,
  })
}

const restoreTagPlacementSettings = async (runId: string) => {
  try {
    const o = await kvGet<Record<string, unknown>>(tagPlacementKey(runId))
    if (!o || typeof o !== 'object') {
      applyTagPlacementDefaults()
      return
    }
    if (typeof o.binderChain === 'string' && o.binderChain.length <= 4) {
      tagPlacementBinderChain.value = o.binderChain
    } else {
      tagPlacementBinderChain.value = TAG_PLACEMENT_DEFAULTS.binderChain
    }
    if (typeof o.targetChains === 'string') {
      tagPlacementTargetChains.value = o.targetChains
    } else {
      tagPlacementTargetChains.value = TAG_PLACEMENT_DEFAULTS.targetChains
    }
    if (typeof o.distantFrom === 'string') {
      tagPlacementDistantFrom.value = o.distantFrom
    } else {
      tagPlacementDistantFrom.value = TAG_PLACEMENT_DEFAULTS.distantFrom
    }
    const probe = o.sasaProbe
    if (typeof probe === 'number' && !Number.isNaN(probe) && probe >= 0.1 && probe <= 4) {
      tagPlacementSasaProbe.value = probe
    } else {
      tagPlacementSasaProbe.value = TAG_PLACEMENT_DEFAULTS.sasaProbe
    }
    const points = o.sasaPoints
    if (typeof points === 'number' && !Number.isNaN(points) && points >= 20 && points <= 500) {
      tagPlacementSasaPoints.value = Math.round(points)
    } else {
      tagPlacementSasaPoints.value = TAG_PLACEMENT_DEFAULTS.sasaPoints
    }
    const threshold = o.sasaThreshold
    if (typeof threshold === 'number' && !Number.isNaN(threshold) && threshold >= 0 && threshold <= 100) {
      tagPlacementSasaThreshold.value = threshold
    } else {
      tagPlacementSasaThreshold.value = TAG_PLACEMENT_DEFAULTS.sasaThreshold
    }
    const moreDist = o.moreDist
    if (typeof moreDist === 'number' && !Number.isNaN(moreDist) && moreDist >= 0 && moreDist <= 50) {
      tagPlacementMoreDist.value = moreDist
    } else {
      tagPlacementMoreDist.value = TAG_PLACEMENT_DEFAULTS.moreDist
    }
    if (typeof o.onlyAssignEmptyTags === 'boolean') {
      tagPlacementOnlyEmptyTags.value = o.onlyAssignEmptyTags
    } else {
      tagPlacementOnlyEmptyTags.value = TAG_PLACEMENT_DEFAULTS.onlyEmptyTags
    }
    applyOppositeBinderDefaultTargetChains(undefined, tagPlacementBinderChain.value)
  } catch {
    applyTagPlacementDefaults()
  }
}

const designHasTagNOrC = (design: Record<string, unknown>) => {
  const t = tagOverlayFromDesignField(design)
  return t === 'N' || t === 'C'
}

const tagToolbarTooltip = computed(() => {
  if (tagOverlayMode.value === 'none') return 'His-tag overlay: off (click for N-terminus)'
  if (tagOverlayMode.value === 'N') return 'Showing N-terminus marker (click for C-terminus)'
  return 'Showing C-terminus marker (click to turn off)'
})

const tagOverlayFromDesignField = (design: Record<string, unknown> | undefined): 'none' | 'N' | 'C' => {
  if (!design) return 'none'
  const raw = design.tag ?? design.Tag
  if (raw == null) return 'none'
  const s = String(raw).trim()
  if (!s || s === '-' || s.toUpperCase() === 'NONE') return 'none'
  const u = s.toUpperCase()
  if (u === 'N') return 'N'
  if (u === 'C') return 'C'
  return 'none'
}

const cycleTagOverlay = () => {
  const cs = designsStore.currentStructure
  if (!cs || tagToolbarPending.value) return
  const cur = tagOverlayMode.value
  const nextTag: 'N' | 'C' | null =
    cur === 'none' ? 'N' : cur === 'N' ? 'C' : null
  tagToolbarPending.value = true
  void (async () => {
    try {
      await designsStore.patchDesignTag(cs.design, nextTag)
    } catch (e) {
      console.error('Tag toolbar persist failed', e)
      toast.add({
        severity: 'error',
        summary: 'Tag update failed',
        detail: e instanceof Error ? e.message : String(e),
        life: 5000,
      })
    } finally {
      tagToolbarPending.value = false
    }
  })()
}

const toggleTagPlacementOptions = () => {
  showTagPlacementOptions.value = !showTagPlacementOptions.value
}

const toggleContactMapOptions = () => {
  showContactMapOptions.value = !showContactMapOptions.value
}

const contactMapRunId = computed(
  () => designsStore.currentStructure?.design.run_id ?? null
)

/** The table selection, narrowed to the run being viewed - the map colours one target. */
const contactMapSelectedKeys = computed(() =>
  designsStore.selectedDesigns
    .filter((d) => String(d.run_id) === contactMapRunId.value)
    .map((d) => ({
      run_id: String(d.run_id),
      design_id: String(d.design_id),
      source_path: d.source_path != null ? String(d.source_path) : undefined,
    }))
)

const applyContactMapColors = (
  colors: { chain: string; resseq: number; r: number; g: number; b: number }[]
) => {
  void molstarViewerRef.value?.applyResidueColorMap?.(colors)
}

const clearContactMapColors = () => {
  void molstarViewerRef.value?.clearResidueColorMap?.()
}

/** A remount discards the painted colours, so repaint once the new structure settles. */
const onViewerStructureLoaded = () => {
  contactMapPanelRef.value?.repaint?.()
}

const runTagPlacementAutoDetect = async () => {
  const sel = designsStore.selectedDesigns
  if (!sel.length) {
    toast.add({ severity: 'warn', summary: 'No selection', detail: 'Select designs in the table first.', life: 2500 })
    return
  }
  const skippedTagged =
    tagPlacementOnlyEmptyTags.value
      ? sel.filter((d) => designHasTagNOrC(d as Record<string, unknown>))
      : []
  const toProcess =
    tagPlacementOnlyEmptyTags.value
      ? sel.filter((d) => !designHasTagNOrC(d as Record<string, unknown>))
      : sel
  if (tagPlacementOnlyEmptyTags.value && toProcess.length === 0) {
    toast.add({
      severity: 'warn',
      summary: 'Tag placement',
      detail:
        skippedTagged.length > 0
          ? `All ${skippedTagged.length} selected design(s) already have tag N or C.`
          : 'No designs to process.',
      life: 4000,
    })
    return
  }
  tagPlacementLoading.value = true
  tagPlacementProgressTotal.value = toProcess.length
  tagPlacementProgressCurrent.value = 0
  const allResults: TagPlacementResultRow[] = []
  try {
    const distant = tagPlacementDistantFrom.value.trim()
    const targetChains = tagPlacementTargetChains.value.trim()
    const basePayload = {
      binder_chain: tagPlacementBinderChain.value.trim() || 'B',
      target_chains: targetChains || null,
      distant_from: distant || null,
      sasa_probe_radius: tagPlacementSasaProbe.value,
      sasa_n_points: tagPlacementSasaPoints.value,
      sasa_threshold: tagPlacementSasaThreshold.value,
      more_distant_threshold: tagPlacementMoreDist.value,
      refresh_cache_after: false,
      ignore_cache: tagPlacementIgnoreCache.value === true,
    }
    const designByKey = new Map<string, Design>(
      toProcess.map((d) => [`${d.run_id}::${d.design_id}`, d]),
    )
    for (const batch of chunkArray(toProcess, TAG_PLACEMENT_BATCH_SIZE)) {
      const res = await designsApi.postTagPlacement({
        ...basePayload,
        designs: batch.map((d) => {
          const fn = designsStore.getStructureFilename(d)
          return {
            run_id: String(d.run_id),
            design_id: String(d.design_id),
            pdb_file: fn || undefined,
            source_path: d.source_path != null ? String(d.source_path) : undefined,
          }
        }),
      })
      const successfulBatchDesigns: Design[] = []
      for (const row of res.results) {
        allResults.push(row)
        designsStore.applyTagPlacementResult(row)
        if (!row.error) {
          const d = designByKey.get(`${row.run_id}::${row.design_id}`)
          if (d) successfulBatchDesigns.push(d)
        }
      }
      if (successfulBatchDesigns.length > 0) {
        try {
          await refreshTagMetricsRowsAfterPlacement(successfulBatchDesigns)
        } catch (e) {
          console.warn('Tag metrics refresh after placement failed', e)
        }
      }
      tagPlacementProgressCurrent.value += batch.length
      await nextTick()
    }
    if (allResults.length === 0) {
      toast.add({
        severity: 'warn',
        summary: 'Tag placement',
        detail: 'No tag-placement results were returned by the server.',
        life: 4500,
      })
      return
    }
    const failed = allResults.filter((r) => r.error)
    const ok = allResults.filter((r) => !r.error)
    const tagAssigned = (r: TagPlacementResultRow) => {
      const t = r.tag
      if (t == null) return false
      const u = String(t).trim().toUpperCase()
      return u === 'N' || u === 'C'
    }
    const ambiguousOk = ok.filter((r) => !tagAssigned(r))
    const ambiguousMsg = 'Some ambiguous tags not assigned'
    const skipSuffix =
      skippedTagged.length > 0 ? ` Skipped ${skippedTagged.length} with existing N/C tag.` : ''
    if (failed.length === 0 && ambiguousOk.length === 0) {
      toast.add({
        severity: 'success',
        summary: 'Tag placement',
        detail: `Updated ${ok.length} design(s).${skipSuffix}`,
        life: 3500,
      })
    } else if (failed.length === 0 && ambiguousOk.length > 0) {
      const assignedN = ok.length - ambiguousOk.length
      const detail =
        assignedN > 0
          ? `${assignedN} design(s) tagged (N/C). ${ambiguousMsg} (${ambiguousOk.length} design(s)).${skipSuffix}`
          : `${ambiguousMsg} (${ambiguousOk.length} design(s)).${skipSuffix}`
      toast.add({
        severity: 'warn',
        summary: 'Tag placement',
        detail,
        life: 6000,
      })
    } else {
      const parts = [
        `${ok.length} ok, ${failed.length} failed. First error: ${failed[0]?.error ?? 'unknown'}`,
      ]
      if (ambiguousOk.length > 0) {
        parts.push(`${ambiguousMsg}.`)
      }
      if (skipSuffix) {
        parts.push(skipSuffix.trim())
      }
      toast.add({
        severity: 'warn',
        summary: 'Tag placement',
        detail: parts.join(' '),
        life: 6000,
      })
    }
  } catch (e) {
    console.error('Tag placement batch failed', e)
    toast.add({
      severity: 'error',
      summary: 'Tag placement failed',
      detail: e instanceof Error ? e.message : String(e),
      life: 5000,
    })
  } finally {
    if (toProcess.length > 0) {
      try {
        await designsApi.refreshDesignsCache()
        await designsStore.fetchDesigns()
      } catch (e2) {
        console.warn('Designs cache refresh after tag placement failed', e2)
      }
    }
    tagPlacementLoading.value = false
    tagPlacementProgressTotal.value = 0
    tagPlacementProgressCurrent.value = 0
  }
}

const viewerContainerRef = ref<HTMLElement | null>(null)
const viewerControlsRef = ref<HTMLElement | null>(null)
const viewerControlsPos = ref<{ left: number; top: number } | null>(null)

const viewerControlsDragTooltip =
  'Drag to move toolbar. Double-click here to snap back to the default position.'

let viewerDragActive = false
let viewerDragPointerId: number | null = null
let viewerDragStart = { clientX: 0, clientY: 0, left: 0, top: 0 }

const viewerControlsStyle = computed(() => {
  if (!viewerControlsPos.value) return {}
  const { left, top } = viewerControlsPos.value
  return {
    left: `${Math.round(left)}px`,
    top: `${Math.round(top)}px`,
    transform: 'none',
  } as Record<string, string>
})

function persistViewerControlsPos() {
  if (viewerControlsPos.value) {
    void kvSet(PERSISTENCE_KEYS.viewerControlsPos, viewerControlsPos.value)
  } else {
    void kvRemove(PERSISTENCE_KEYS.viewerControlsPos)
  }
}

async function loadViewerControlsPos() {
  try {
    const o = await kvGet<{ left?: unknown; top?: unknown }>(PERSISTENCE_KEYS.viewerControlsPos)
    if (!o || typeof o !== 'object') return
    if (typeof o.left === 'number' && typeof o.top === 'number' && Number.isFinite(o.left) && Number.isFinite(o.top)) {
      viewerControlsPos.value = { left: o.left, top: o.top }
    }
  } catch {
    /* ignore */
  }
}

function clampViewerControlsPosition(left: number, top: number): { left: number; top: number } {
  const c = viewerContainerRef.value
  const el = viewerControlsRef.value
  if (!c || !el) return { left, top }
  const cw = c.clientWidth
  const ch = c.clientHeight
  const ew = el.offsetWidth
  const eh = el.offsetHeight
  return {
    left: Math.max(0, Math.min(left, Math.max(0, cw - ew))),
    top: Math.max(0, Math.min(top, Math.max(0, ch - eh))),
  }
}

function clampViewerControlsIfNeeded() {
  if (!viewerControlsPos.value) return
  const next = clampViewerControlsPosition(viewerControlsPos.value.left, viewerControlsPos.value.top)
  viewerControlsPos.value = next
}

function onViewerControlsPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  const container = viewerContainerRef.value
  const controls = viewerControlsRef.value
  if (!container || !controls) return
  e.preventDefault()
  e.stopPropagation()
  const cr = container.getBoundingClientRect()
  const er = controls.getBoundingClientRect()
  const left = er.left - cr.left
  const top = er.top - cr.top
  viewerDragActive = true
  viewerDragPointerId = e.pointerId
  viewerDragStart = { clientX: e.clientX, clientY: e.clientY, left, top }
  try {
    controls.setPointerCapture(e.pointerId)
  } catch {
    /* ignore */
  }
  window.addEventListener('pointermove', onViewerControlsPointerMove)
  window.addEventListener('pointerup', onViewerControlsPointerUp)
  window.addEventListener('pointercancel', onViewerControlsPointerUp)
}

function onViewerControlsPointerMove(e: PointerEvent) {
  if (!viewerDragActive || e.pointerId !== viewerDragPointerId) return
  const dx = e.clientX - viewerDragStart.clientX
  const dy = e.clientY - viewerDragStart.clientY
  viewerControlsPos.value = clampViewerControlsPosition(
    viewerDragStart.left + dx,
    viewerDragStart.top + dy
  )
}

function onViewerControlsPointerUp(e: PointerEvent) {
  if (!viewerDragActive) return
  if (viewerDragPointerId != null && e.pointerId !== viewerDragPointerId) return
  const controls = viewerControlsRef.value
  try {
    if (controls && viewerDragPointerId != null) {
      controls.releasePointerCapture(viewerDragPointerId)
    }
  } catch {
    /* ignore */
  }
  window.removeEventListener('pointermove', onViewerControlsPointerMove)
  window.removeEventListener('pointerup', onViewerControlsPointerUp)
  window.removeEventListener('pointercancel', onViewerControlsPointerUp)
  viewerDragActive = false
  viewerDragPointerId = null
  persistViewerControlsPos()
}

function resetViewerControlsPosition() {
  viewerControlsPos.value = null
  persistViewerControlsPos()
}

const referenceStructureHelp =
  'Use Source: RCSB PDB for a 4-letter code from files.rcsb.org; PDBTM for the same code via pdbtm.unitmp.org/entry/{id} (RCSB coordinates + membrane overlay when available); URL for any http(s) link to a structure file or a PDBTM entry/JSON URL — http(s) inputs always use URL resolution regardless of Source. Plain PDB IDs ignore the URL option and load from RCSB unless you switch to PDBTM.'

const REFERENCE_SOURCE_KINDS = ['rcsb', 'pdbtm', 'url'] as const
type ReferenceManualSourceKind = (typeof REFERENCE_SOURCE_KINDS)[number]

const referenceSourceKindOptions: Array<{ label: string; value: ReferenceManualSourceKind }> = [
  { label: 'RCSB PDB', value: 'rcsb' },
  { label: 'PDBTM', value: 'pdbtm' },
  { label: 'URL', value: 'url' },
]

const PDB_ID_FOR_REFERENCE_RE = /^[0-9][A-Za-z0-9]{3}$/i

function resolveManualReferenceSourceForApi(
  raw: string,
  kind: ReferenceManualSourceKind,
): string {
  const s = raw.trim()
  if (!s) return s
  if (/^https?:\/\//i.test(s)) return s
  if (PDB_ID_FOR_REFERENCE_RE.test(s)) {
    const id = s.toUpperCase()
    if (kind === 'pdbtm') {
      return `https://pdbtm.unitmp.org/entry/${id}`
    }
    return id
  }
  return s
}

const referenceStructureTooltipOptions = {
  value: referenceStructureHelp,
  showDelay: 150,
  autoHide: false,
}

const referenceViewerUrl = ref('')
const referenceBlobUrlToRevoke = ref<string | null>(null)

/** Mol* may still be fetching a blob URL when we swap designs; revoking immediately yields status 0 (esp. Firefox). */
const REFERENCE_BLOB_REVOKE_DELAY_MS = 15_000
const scheduleRevokeReferenceBlobUrl = (url: string | null | undefined) => {
  if (!url) return
  window.setTimeout(() => {
    try {
      URL.revokeObjectURL(url)
    } catch {
      /* ignore */
    }
  }, REFERENCE_BLOB_REVOKE_DELAY_MS)
}
const referenceOverlayActive = ref(false)
const referenceManualSource = ref('')
const referenceManualSourceKind = ref<ReferenceManualSourceKind>('rcsb')
const referenceChainIdsInput = ref('')
const showInputTargetStructure = ref(false)
const selectedInputTargetId = ref<string | null>(null)
const inputTargetsList = ref<Array<{ id: string; label: string }>>([])
const inputTargetsLoading = ref(false)
const referenceLoading = ref(false)
const referenceMetrics = ref<{
  tmNormDesign: number
  tmNormReference: number
  rmsd: number
  alignedLength: number
} | null>(null)
const referenceMembraneData = ref<MembraneData | null>(null)
const isSpinning = ref(false)
const alphafoldViewEnabled = ref(true)
const referenceStructureVisible = ref(true)
const goodRatingPending = ref(false)
const exportIncludeAllColumns = ref(false)
const selectTopCount = ref<number | null>(null)
const exportMenuItems = ref([
  { label: 'Download TSV', icon: 'pi pi-download', command: () => onDownloadTsv() },
  { label: 'Download CSV', icon: 'pi pi-download', command: () => onDownloadCsv() },
  { label: 'Download PDBs', icon: 'pi pi-box', command: () => onDownloadPdbs() },
  { label: 'Download FASTA (Binders)', icon: 'pi pi-file', command: () => onDownloadFasta() }
])

const bundleDownloading = ref(false)
const bundleConfirmVisible = ref(false)
const bundleEstimate = ref<{ estimated_zip_bytes: number; structure_count: number } | null>(null)
/** Above this the zip is held in browser memory long enough to be worth a warning. */
const BUNDLE_CONFIRM_BYTES = 500 * 1024 * 1024

const mergeUploadMenuItems = ref([
  {
    label: 'Upload extra data (CSV)',
    icon: 'pi pi-upload',
    command: () => openMergeTableDialog('csv')
  }
])

// Params dialog state
const showParamsDialog = ref(false)
const currentParamsJson = ref<string>('')

const showMergeTableDialog = ref(false)
const mergeTableFileInputRef = ref<HTMLInputElement | null>(null)
const mergeTableFile = ref<File | null>(null)
const mergeTableDesignIdColumn = ref('')
const mergeTablePreview = ref<MergeTableResponse | null>(null)
const mergeTablePending = ref(false)
const mergeTableFileAccept = ref('.tsv,.txt,text/tab-separated-values')

const openMergeTableDialog = (format: 'tsv' | 'csv' = 'tsv') => {
  if (designsStore.selectedRunIds.length === 0) {
    toast.add({
      severity: 'warn',
      summary: 'No runs selected',
      detail: 'Select runs in the Runs tab before uploading extra data.',
      life: 4000
    })
    return
  }
  mergeTableFileAccept.value =
    format === 'csv'
      ? '.csv,text/csv'
      : '.tsv,.txt,text/tab-separated-values'
  mergeTableFile.value = null
  mergeTablePreview.value = null
  mergeTableDesignIdColumn.value = ''
  if (mergeTableFileInputRef.value) mergeTableFileInputRef.value.value = ''
  showMergeTableDialog.value = true
}

const onMergeTableFileChange = (ev: Event) => {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  mergeTableFile.value = f ?? null
  mergeTablePreview.value = null
}

const runMergeTableUpload = async (preview: boolean) => {
  if (!mergeTableFile.value) return
  const runIds = designsStore.selectedRunIds
  if (runIds.length === 0) {
    toast.add({
      severity: 'warn',
      summary: 'No runs selected',
      detail: 'Select runs in the Runs tab first.',
      life: 4000
    })
    return
  }
  mergeTablePending.value = true
  try {
    const result = await designsApi.mergeTableUpload({
      file: mergeTableFile.value,
      runIds,
      preview,
      designIdColumn: mergeTableDesignIdColumn.value || undefined
    })
    mergeTablePreview.value = result
    if (!preview) {
      await designsStore.fetchDesignsForRuns(runIds)
      const skip = new Set(result.pipeline_collision_columns ?? [])
      const toShow = (result.new_columns ?? []).filter((c) => !skip.has(c))
      designsStore.ensureColumnsVisible(toShow)
      toast.add({
        severity: 'success',
        summary: 'Columns merged',
        detail: `Updated ${result.updated ?? 0} design row(s).`,
        life: 4000
      })
      showMergeTableDialog.value = false
    }
  } catch (err: unknown) {
    const detail =
      err instanceof Error ? err.message : 'The table could not be imported.'
    toast.add({
      severity: 'error',
      summary: preview ? 'Import preview failed' : 'Import failed',
      detail,
      life: 6000
    })
  } finally {
    mergeTablePending.value = false
  }
}

const runMergeTablePreview = () => runMergeTableUpload(true)
const runMergeTableApply = () => runMergeTableUpload(false)

const columnSelectOptions = computed(() => designsStore.columnsForSelectedRuns)

/** Preserve existing column order when toggling via MultiSelect. */
const visibleColumnFields = computed<string[]>({
  get: () => designsStore.visibleColumns,
  set: (fields) => {
    const next = new Set(fields)
    const kept = designsStore.visibleColumns.filter((f) => next.has(f))
    const keptSet = new Set(kept)
    const added = fields.filter((f) => !keptSet.has(f))
    designsStore.visibleColumns = [...kept, ...added]
  }
})

// Methods

const loadDesigns = async () => {
  if (!authStore.canLoadData) {
    console.log('Authentication required - skipping designs load')
    return
  }

  try {
    await designsStore.ensureDesignsForCurrentSelection()
  } catch (error: any) {
    console.error('Error loading designs:', error)
    // Don't show toast for authentication errors - user will be redirected to login
    if (error?.message !== 'Authentication required') {
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: 'Failed to load designs',
        life: 3000
      })
    }
  }
}

const viewDesign = (design: any): void => {
  designsStore.viewDesign(design)
}

const onRowClick = (event: any): void => {
  const target = event.originalEvent.target as HTMLElement
  const isButton = target.closest('button') || target.closest('.p-button')
  const isCheckbox = target.closest('.p-checkbox') || target.closest('input[type="checkbox"]')
  // Missing the checkbox but clicking its cell must toggle that row only — not
  // call viewDesign, which replaces the whole selection with the clicked row.
  const isSelectionCell = !!target.closest('td.row-selection-cell')

  if (isSelectionCell) {
    if (!isCheckbox) {
      const checked = designsStore.isDesignSelected(event.data)
      designsStore.toggleDesignSelected(event.data, !checked)
    }
    return
  }

  if (!isButton && !isCheckbox) {
    viewDesign(event.data)
  }
}

const downloadPdb = async (design: any): Promise<void> => {
  try {
    const filename = designsStore.getStructureFilename(design)
    if (!filename) {
      throw new Error('No structure file found for this design')
    }
    
    // Get the PDB URL for this design
    const pdbUrl = runsApi.getPdbFileUrl(design.run_id, filename)
    
    // Create a temporary anchor element to trigger download
    const link = document.createElement('a')
    link.href = pdbUrl
    link.download = filename
    link.target = '_blank'
    
    // Append to body, click, and remove
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    
    toast.add({
      severity: 'success',
      summary: 'Download Started',
      detail: `Downloading ${filename}`,
      life: 3000
    })
  } catch (error: any) {
    console.error('Error downloading PDB:', error)
    toast.add({
      severity: 'error',
      summary: 'Download Failed',
      detail: error.message || 'Failed to download PDB file',
      life: 3000
    })
  }
}

const openParamsDialog = (design: any): void => {
  try {
    const params = design?.params
    currentParamsJson.value = params ? JSON.stringify(params, null, 2) : ''
    showParamsDialog.value = true
  } catch (err) {
    currentParamsJson.value = ''
    showParamsDialog.value = true
  }
}

const navigateToNextRow = () => {
  designsStore.navigateStructure('next')
}

const navigateToPreviousRow = () => {
  designsStore.navigateStructure('previous')
}

const getCurrentRowPosition = () => {
  return designsStore.getCurrentRowPosition()
}

const normalizeGood = (v: unknown): boolean | null => {
  if (v === true || v === 'true' || v === 1 || v === '1') return true
  if (v === false || v === 'false' || v === 0 || v === '0') return false
  if (v === '' || (typeof v === 'string' && v.trim() === '')) return null
  return null
}

const goodCellModifier = (v: unknown): string => {
  const n = normalizeGood(v)
  if (n === true) return 'good-cell--true'
  if (n === false) return 'good-cell--false'
  return 'good-cell--empty'
}

const structureGood = computed((): boolean | null => {
  const d = designsStore.currentStructure?.design as Record<string, unknown> | undefined
  if (!d || !Object.prototype.hasOwnProperty.call(d, 'good')) return null
  return normalizeGood(d.good)
})

const setStructureGood = async (clicked: boolean) => {
  const cur = designsStore.currentStructure
  if (!cur || goodRatingPending.value) return
  const current = structureGood.value
  const nextVal: boolean | null = current === clicked ? null : clicked
  goodRatingPending.value = true
  try {
    await designsStore.patchDesignGood(cur.design, nextVal)
  } catch (err: any) {
    toast.add({
      severity: 'error',
      summary: 'Could not update rating',
      detail: err?.message || 'Request failed',
      life: 4000
    })
  } finally {
    goodRatingPending.value = false
  }
}

const toggleSpin = async () => {
  if (molstarViewerRef.value) {
    await molstarViewerRef.value.toggleSpin()
    // Update local state to reflect the change
    isSpinning.value = molstarViewerRef.value.isSpinning
  }
}

const toggleAlphaFoldView = async () => {
  if (molstarViewerRef.value) {
    await molstarViewerRef.value.toggleAlphaFoldView()
    // Update local state to reflect the change
    alphafoldViewEnabled.value = molstarViewerRef.value.alphafoldViewEnabled
  }
}

const toggleReferenceStructureVisibility = async () => {
  if (!molstarViewerRef.value || !referenceViewerUrl.value) return
  await molstarViewerRef.value.toggleReferenceStructureVisibility()
  referenceStructureVisible.value = molstarViewerRef.value.referenceStructureVisible
}

const onTableHeaderSelectAllChange = (value: boolean) => {
  if (designsStore.tableHeaderSelectionIndeterminate) {
    designsStore.toggleSelectAllFiltered(true)
    return
  }
  designsStore.toggleSelectAllFiltered(value)
}

const selectTopRows = () => {
  if (!selectTopCount.value || selectTopCount.value < 1) {
    return
  }
  
  const sortedDesigns = designsStore.orderedFilteredDesigns

  const topRows = sortedDesigns.slice(0, selectTopCount.value)
  
  // Update the store's selected designs
  designsStore.setSelectionFromDesigns(topRows)
  
  toast.add({
    severity: 'success',
    summary: 'Selection Updated',
    detail: `Selected top ${selectTopCount.value} designs`,
    life: 2000
  })
}

// Export helpers
const getRowsToExport = () => {
  const selected = designsStore.selectedDesigns
  return (selected && selected.length > 0) ? selected : designsStore.filteredDesigns
}

const getColumnsToExport = () => {
  const replaceRunId = (cols: string[]) => {
    return cols.map(c => (c === 'run_id' ? 'binderdash_run_id' : c)).filter((v, i, a) => a.indexOf(v) === i)
  }

  if (exportIncludeAllColumns.value) {
    // All distinct keys across rows
    const rows = getRowsToExport()
    const keySet = new Set<string>()
    rows.forEach((r: any) => Object.keys(r).forEach(k => keySet.add(k)))
    return replaceRunId(Array.from(keySet))
  }
  return replaceRunId(designsStore.visibleColumns)
}

const toSeparatedValues = (rows: any[], cols: string[], sep: string): string => {
  const esc = (v: any) => {
    if (v == null) return ''
    
    // Handle objects by serializing them as JSON
    if (typeof v === 'object' && v !== null) {
      const s = JSON.stringify(v)
      return sep === ',' && /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
    }
    
    const s = String(v)
    return sep === ',' && /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
  }
  const header = cols.join(sep)
  const valueFor = (r: any, c: string) => {
    if (c === 'binderdash_run_id') return r['run_id']
    return r[c]
  }
  const lines = rows.map(r => cols.map(c => esc(valueFor(r, c))).join(sep))
  return [header, ...lines].join('\n')
}

const downloadBlob = (blob: Blob, filename: string) => {
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

const onDownloadCsv = () => {
  const rows = getRowsToExport()
  const cols = getColumnsToExport()
  const content = toSeparatedValues(rows as any[], cols as string[], ',')
  downloadBlob(new Blob([content], { type: 'text/csv;charset=utf-8' }), 'designs.csv')
}

const onDownloadTsv = () => {
  const rows = getRowsToExport()
  const cols = getColumnsToExport()
  const content = toSeparatedValues(rows as any[], cols as string[], '\t')
  downloadBlob(new Blob([content], { type: 'text/tab-separated-values;charset=utf-8' }), 'designs.tsv')
}

const onDownloadPdbs = async () => {
  try {
    const rows = getRowsToExport().filter((d: any) => designsStore.getStructureFilename(d))
    if (rows.length === 0) {
      toast.add({ severity: 'warn', summary: 'No PDBs', detail: 'No structure files to download', life: 2500 })
      return
    }
    const items = rows.map((d: any) => ({ run_id: d.run_id, filename: designsStore.getStructureFilename(d) }))
    const blob = await runsApi.downloadPdbsTar(items)
    downloadBlob(blob, 'designs_pdbs.tar')
  } catch (err: any) {
    console.error('Error downloading PDBs tar:', err)
    toast.add({ severity: 'error', summary: 'Download Failed', detail: err?.message || 'Failed to download PDBs', life: 3000 })
  }
}

const formatBytes = (value: number): string => {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

const bundleRequest = () => {
  const rows = getRowsToExport()
  const keys = rows.map((d: any) => ({
    run_id: String(d.run_id),
    design_id: String(d.design_id),
    source_path: d.source_path ?? ''
  }))
  const runIds = Array.from(new Set(keys.map((k: any) => k.run_id)))

  // Columns the server cannot recompute (the Binderdash ranking is applied client-side
  // from the filtering store), keyed the same way the backend keys a design.
  const clientColumns: Record<string, Record<string, any>> = {}
  for (const row of rows as any[]) {
    const rank = row[BINDERDASH_RANKING_FIELD]
    if (rank === undefined || rank === null) continue
    clientColumns[`${row.run_id}\u001f${row.design_id}\u001f${row.source_path ?? ''}`] = {
      [BINDERDASH_RANKING_FIELD]: rank
    }
  }

  return {
    keys,
    run_ids: runIds,
    label: 'binderdash_designs',
    include_heavy: exportIncludeAllColumns.value,
    session: buildSessionState(),
    client_columns: clientColumns
  }
}

const runBundleDownload = async () => {
  bundleDownloading.value = true
  try {
    const request = bundleRequest()
    const blob = await bundlesApi.downloadDesignsBundle(request)
    downloadBlob(blob, 'binderdash_designs.zip')
    toast.add({
      severity: 'success',
      summary: 'Design bundle',
      detail: `${request.keys.length} design(s) with structures, tables and session state`,
      life: 3000
    })
  } catch (err: any) {
    console.error('Error downloading design bundle:', err)
    toast.add({
      severity: 'error',
      summary: 'Download Failed',
      detail: err?.message || 'Failed to build the design bundle',
      life: 5000
    })
  } finally {
    bundleDownloading.value = false
    bundleConfirmVisible.value = false
  }
}

const onDownloadBundle = async () => {
  const rows = getRowsToExport()
  if (rows.length === 0) {
    toast.add({ severity: 'warn', summary: 'No Designs', detail: 'No designs to export', life: 2500 })
    return
  }
  try {
    const estimate = await bundlesApi.estimate(bundleRequest())
    bundleEstimate.value = estimate
    if (estimate.exceeds_cap) {
      toast.add({
        severity: 'error',
        summary: 'Selection too large',
        detail: estimate.cap_messages.join('; '),
        life: 8000
      })
      return
    }
    if (estimate.estimated_zip_bytes > BUNDLE_CONFIRM_BYTES) {
      bundleConfirmVisible.value = true
      return
    }
  } catch (err) {
    // The estimate is a courtesy; if it fails, still let the download be attempted.
    console.warn('Bundle estimate failed, downloading anyway', err)
  }
  await runBundleDownload()
}

const onDownloadFasta = () => {
  try {
    const rows = getRowsToExport()
    if (rows.length === 0) {
      toast.add({ severity: 'warn', summary: 'No Designs', detail: 'No designs to export', life: 2500 })
      return
    }

    // Find designs with sequence data
    const designsWithSequence = rows.filter((d: any) => {
      // Check for sequence in various possible field names
      const sequenceFields = ['Sequence', 'sequence', 'binder_sequence', 'binder_seq', 'seq']
      return sequenceFields.some(field => d[field] && String(d[field]).trim())
    })

    if (designsWithSequence.length === 0) {
      toast.add({ severity: 'warn', summary: 'No Sequences', detail: 'No sequence data found in selected designs', life: 2500 })
      return
    }

    // Generate FASTA content
    const fastaContent = designsWithSequence.map((d: any) => {
      // Find the sequence field (prioritize 'Sequence' then 'sequence' then others)
      const sequenceFields = ['Sequence', 'sequence', 'binder_sequence', 'binder_seq', 'seq']
      let sequence = ''
      
      for (const field of sequenceFields) {
        if (d[field] && String(d[field]).trim()) {
          sequence = String(d[field]).trim()
          break
        }
      }

      return `>${d.design_id}\n${sequence}`
    }).join('\n')

    downloadBlob(new Blob([fastaContent], { type: 'text/plain;charset=utf-8' }), 'designs_binders.fasta')
    
    toast.add({
      severity: 'success',
      summary: 'FASTA Downloaded',
      detail: `Downloaded ${designsWithSequence.length} sequences`,
      life: 3000
    })
  } catch (err: any) {
    console.error('Error downloading FASTA:', err)
    toast.add({ severity: 'error', summary: 'Download Failed', detail: err?.message || 'Failed to download FASTA', life: 3000 })
  }
}

const getPdbUrl = () => {
  if (!designsStore.currentStructure) return ''
  return runsApi.getPdbFileUrl(designsStore.currentStructure.design.run_id, designsStore.currentStructure.filename)
}

/**
 * When the reference overlay is on, `referenceViewerUrl` updates after `loadReferenceOverlay` finishes.
 * The watch that updates these refs MUST be registered after the `currentStructure?.filename` and `run_id`
 * watchers below so that `loadReferenceOverlay()` runs first and sets `referenceLoading` before we evaluate.
 * Otherwise the first flush pushes (new PDB, stale blob) and Mol* loads twice (double flash).
 */
const molstarPdbUrlForViewer = ref('')
const molstarReferenceUrlForViewer = ref('')

const inputTargetDropdownOptions = computed(() =>
  inputTargetsList.value.map((t) => ({ label: t.label, value: t.id }))
)

const canLoadReferenceOverlay = computed(() => {
  if (!designsStore.currentStructure || referenceLoading.value) return false
  if (showInputTargetStructure.value) {
    if (inputTargetsList.value.length === 0) return false
    if (inputTargetsList.value.length > 1 && !selectedInputTargetId.value) return false
    return true
  }
  return referenceManualSource.value.trim().length > 0
})

const onReferenceManualEnter = (e: KeyboardEvent) => {
  e.preventDefault()
  if (!canLoadReferenceOverlay.value) return
  void loadReferenceOverlay()
}

const toggleAdvancedOptions = () => {
  showAdvancedOptions.value = !showAdvancedOptions.value
  if (showAdvancedOptions.value) {
    const rid = designsStore.currentStructure?.design.run_id
    if (rid) {
      void refreshInputTargetsForRun(rid).then(() => {
        if (selectedInputTargetId.value) {
          const ok = inputTargetsList.value.some((t) => t.id === selectedInputTargetId.value)
          if (!ok) selectedInputTargetId.value = null
        }
        if (inputTargetsList.value.length === 1) {
          selectedInputTargetId.value = inputTargetsList.value[0].id
        }
      })
    }
  }
}

const persistAdvancedRef = (runId: string) => {
  void kvSet(advRefKey(runId), {
    manual: referenceManualSource.value,
    sourceKind: referenceManualSourceKind.value,
    chains: referenceChainIdsInput.value,
    useInput: showInputTargetStructure.value,
    inputId: selectedInputTargetId.value,
    overlay: referenceOverlayActive.value,
  })
}

const restoreAdvancedRef = async (runId: string) => {
  try {
    const o = await kvGet<Record<string, unknown>>(advRefKey(runId))
    if (!o || typeof o !== 'object') return
    if (typeof o.manual === 'string') referenceManualSource.value = o.manual
    if (
      typeof o.sourceKind === 'string' &&
      (REFERENCE_SOURCE_KINDS as readonly string[]).includes(o.sourceKind)
    ) {
      referenceManualSourceKind.value = o.sourceKind as ReferenceManualSourceKind
    }
    if (typeof o.chains === 'string') referenceChainIdsInput.value = o.chains
    if (typeof o.useInput === 'boolean') showInputTargetStructure.value = o.useInput
    if (o.inputId != null && o.inputId !== '') selectedInputTargetId.value = String(o.inputId)
    if (typeof o.overlay === 'boolean') referenceOverlayActive.value = o.overlay
  } catch {
    /* ignore */
  }
}

const persistGlobalAdvRef = () => {
  void kvSet(PERSISTENCE_KEYS.advRefGlobal, {
    manual: referenceManualSource.value,
    sourceKind: referenceManualSourceKind.value,
    chains: referenceChainIdsInput.value,
    useInput: showInputTargetStructure.value,
  })
}

const loadGlobalAdvRef = async () => {
  try {
    const o = await kvGet<Record<string, unknown>>(PERSISTENCE_KEYS.advRefGlobal)
    if (!o || typeof o !== 'object') return
    if (typeof o.manual === 'string') referenceManualSource.value = o.manual
    if (
      typeof o.sourceKind === 'string' &&
      (REFERENCE_SOURCE_KINDS as readonly string[]).includes(o.sourceKind)
    ) {
      referenceManualSourceKind.value = o.sourceKind as ReferenceManualSourceKind
    }
    if (typeof o.chains === 'string') referenceChainIdsInput.value = o.chains
    if (typeof o.useInput === 'boolean') showInputTargetStructure.value = o.useInput
  } catch {
    /* ignore */
  }
}

const revokeReferenceBlob = () => {
  if (referenceBlobUrlToRevoke.value) {
    scheduleRevokeReferenceBlobUrl(referenceBlobUrlToRevoke.value)
    referenceBlobUrlToRevoke.value = null
  }
  referenceViewerUrl.value = ''
}

const clearReferenceOverlay = () => {
  revokeReferenceBlob()
  referenceOverlayActive.value = false
  referenceMetrics.value = null
  referenceMembraneData.value = null
  referenceStructureVisible.value = true
  molstarViewerRef.value?.resetReferenceVisibilityPreference?.()
  const cs = designsStore.currentStructure
  if (cs?.design.run_id) persistAdvancedRef(cs.design.run_id)
}

const parseMembraneHeaders = (res: Response): MembraneData | null => {
  const p1h = res.headers.get('X-Binderdash-Membrane-Plane1')
  const p2h = res.headers.get('X-Binderdash-Membrane-Plane2')
  const nh = res.headers.get('X-Binderdash-Membrane-Normal')
  const ch = res.headers.get('X-Binderdash-Membrane-Centroid')
  const rh = res.headers.get('X-Binderdash-Membrane-Radius')
  if (!p1h || !p2h || !nh || !ch || !rh) return null
  const tri = (s: string): [number, number, number] | null => {
    const a = s.split(',').map((x) => parseFloat(x.trim()))
    if (a.length !== 3 || a.some((x) => Number.isNaN(x))) return null
    return [a[0], a[1], a[2]]
  }
  const plane1 = tri(p1h)
  const plane2 = tri(p2h)
  const normal = tri(nh)
  const centroid = tri(ch)
  const radius = parseFloat(rh)
  if (!plane1 || !plane2 || !normal || !centroid || Number.isNaN(radius)) return null
  return { plane1, plane2, normal, centroid, radius }
}

const loadReferenceOverlay = async (silent = false) => {
  const cs = designsStore.currentStructure
  if (!cs) return
  const previousBlobUrl = referenceBlobUrlToRevoke.value
  referenceLoading.value = true
  referenceMetrics.value = null
  referenceMembraneData.value = null
  let responseOk = false
  try {
    const runId = cs.design.run_id
    const filename = cs.filename
    let requestUrl: string
    if (showInputTargetStructure.value) {
      let tid = selectedInputTargetId.value
      if (!tid && inputTargetsList.value.length === 1) {
        tid = inputTargetsList.value[0].id
      }
      if (!tid) throw new Error('Select an input target structure')
      requestUrl = runsApi.getAlignedReferenceUrl(runId, filename, {
        mode: 'input_target',
        inputTargetId: tid,
        referenceChains: referenceChainIdsInput.value,
      })
    } else {
      const inputEl = document.getElementById(
        'adv-reference-source',
      ) as HTMLInputElement | null
      const domSrc = inputEl?.value?.trim() ?? ''
      if (domSrc && domSrc !== referenceManualSource.value.trim()) {
        referenceManualSource.value = domSrc
      }
      const src = referenceManualSource.value.trim()
      if (!src) throw new Error('Enter a PDB ID or URL')
      const resolved = resolveManualReferenceSourceForApi(
        src,
        referenceManualSourceKind.value,
      )
      requestUrl = runsApi.getAlignedReferenceUrl(runId, filename, {
        mode: 'manual',
        source: resolved,
        referenceChains: referenceChainIdsInput.value,
      })
    }
    const res = await fetch(requestUrl, { credentials: 'include' })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch {
        try {
          const t = await res.text()
          if (t) detail = t.slice(0, 200)
        } catch {
          /* ignore */
        }
      }
      throw new Error(detail || `HTTP ${res.status}`)
    }
    responseOk = true
    const tmD = res.headers.get('X-Binderdash-TM-Norm-Design')
    const tmR = res.headers.get('X-Binderdash-TM-Norm-Reference')
    const rmsdH = res.headers.get('X-Binderdash-RMSD')
    const alenH = res.headers.get('X-Binderdash-Aligned-Length')
    if (tmD && tmR && rmsdH && alenH) {
      referenceMetrics.value = {
        tmNormDesign: parseFloat(tmD),
        tmNormReference: parseFloat(tmR),
        rmsd: parseFloat(rmsdH),
        alignedLength: parseInt(alenH, 10),
      }
    }
    referenceMembraneData.value = parseMembraneHeaders(res)
    const blob = await res.blob()
    const objectUrl = URL.createObjectURL(blob)
    if (previousBlobUrl) {
      scheduleRevokeReferenceBlobUrl(previousBlobUrl)
    }
    referenceBlobUrlToRevoke.value = objectUrl
    referenceViewerUrl.value = objectUrl
    referenceOverlayActive.value = true
    persistAdvancedRef(runId)
    if (!silent) {
      toast.add({ severity: 'success', summary: 'Reference loaded', life: 2000 })
    }
  } catch (e: unknown) {
    referenceOverlayActive.value = false
    referenceMembraneData.value = null
    if (responseOk) {
      revokeReferenceBlob()
    }
    const msg = e instanceof Error ? e.message : String(e)
    if (!silent) {
      toast.add({ severity: 'error', summary: 'Reference failed', detail: msg, life: 5000 })
    }
  } finally {
    referenceLoading.value = false
  }
}

const refreshInputTargetsForRun = async (runId: string) => {
  inputTargetsLoading.value = true
  inputTargetsList.value = []
  try {
    const r = await runsApi.getInputTargets(runId)
    inputTargetsList.value = r.targets || []
    if (inputTargetsList.value.length === 1) {
      selectedInputTargetId.value = inputTargetsList.value[0].id
    }
  } catch {
    inputTargetsList.value = []
  } finally {
    inputTargetsLoading.value = false
  }
}

const downloadCurrentPdb = async (): Promise<void> => {
  try {
    if (!designsStore.currentStructure) return
    const filename = designsStore.currentStructure.filename
    const runId = designsStore.currentStructure.design.run_id
    if (!filename || !runId) return
    const pdbUrl = runsApi.getPdbFileUrl(runId, filename)
    const link = document.createElement('a')
    link.href = pdbUrl
    link.download = filename
    link.target = '_blank'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    toast.add({ severity: 'success', summary: 'Download Started', detail: `Downloading ${filename}` , life: 2500 })
  } catch (error: any) {
    console.error('Error downloading PDB:', error)
    toast.add({ severity: 'error', summary: 'Download Failed', detail: error?.message || 'Failed to download PDB file', life: 3000 })
  }
}

const hasValidValue = (value: any): boolean => {
  return value !== null && value !== undefined && value !== '' && !isNaN(Number(value))
}

const getScoreValue = (design: any, field: string): any => {
  if (field === 'min_interation_pae') {
    const correct = design.min_interaction_pae
    const typo = design.min_interation_pae
    if (hasValidValue(correct)) return correct
    if (hasValidValue(typo)) return typo
    return undefined
  }
  return design[field]
}

const formatScore = (value: any): string => {
  if (!hasValidValue(value)) return ''
  const num = Number(value)
  return num.toFixed(3)
}

const formatScoreHeader = (fieldName: string): string => niceNameForScoreField(fieldName)

const getLengthValue = (design: any): string | number => {
  const len = design?.Length ?? design?.length
  return (len != null && !isNaN(Number(len))) ? Number(len) : ''
}


const STATIC_STRUCTURE_DETAIL_FIELDS = new Set([
  'design_id',
  'project_id',
  'run_name',
  'method',
  'Length',
  'length'
])

const isBooleanDetailValue = (v: unknown): boolean => v === true || v === false

const isNumericDetailValue = (v: unknown): boolean => {
  if (v === null || v === undefined || v === '') return false
  if (typeof v === 'boolean') return false
  const n = Number(v)
  return Number.isFinite(n)
}

const isStringDetailValue = (v: unknown): boolean => typeof v === 'string' && v !== ''

const getDetailFieldValue = (design: Record<string, unknown> | undefined, field: string): unknown => {
  if (!design) return undefined
  return getScoreValue(design, field)
}

const columnHeaderForDetail = (field: string): string => {
  const col = designsStore.columnsForSelectedRuns.find(c => c.field === field)
  if (col?.header) return col.header
  return formatScoreHeader(field)
}

const formatExtraScoreValue = (value: unknown): string => {
  if (value === true) return 'Yes'
  if (value === false) return 'No'
  if (isNumericDetailValue(value)) return Number(value).toFixed(3)
  return ''
}

const extraScoreBarColor = (field: string, raw: unknown): string => {
  if (raw === true) return '#2ecc71'
  if (raw === false) return '#e74c3c'
  return scoreFieldColor(field, raw)
}

/** Columns shown in structure Design Data / Scores cards: toggled/visible columns. */
const structureDetailFieldSource = computed((): string[] => {
  const seen = new Set<string>()
  const out: string[] = []
  for (const field of designsStore.visibleColumns) {
    if (seen.has(field)) continue
    seen.add(field)
    out.push(field)
  }
  return out
})

const extraVisibleScoreFields = computed((): string[] => {
  const design = designsStore.currentStructure?.design as Record<string, unknown> | undefined
  if (!design) return []
  const primary = new Set(STRUCTURE_CARD_SCORE_ORDER)
  const out: string[] = []
  for (const field of structureDetailFieldSource.value) {
    if (STATIC_STRUCTURE_DETAIL_FIELDS.has(field) || primary.has(field)) continue
    if (field === BINDERDASH_RANKING_FIELD) continue
    const v = getDetailFieldValue(design, field)
    if (v !== null && v !== undefined && typeof v === 'object') continue
    if (isBooleanDetailValue(v) || isNumericDetailValue(v)) out.push(field)
  }
  return out
})

const extraVisibleDesignDataFields = computed((): string[] => {
  const design = designsStore.currentStructure?.design as Record<string, unknown> | undefined
  if (!design) return []
  const primary = new Set(STRUCTURE_CARD_SCORE_ORDER)
  const out: string[] = []
  for (const field of structureDetailFieldSource.value) {
    if (STATIC_STRUCTURE_DETAIL_FIELDS.has(field) || primary.has(field)) continue
    const v = getDetailFieldValue(design, field)
    if (field === BINDERDASH_RANKING_FIELD) {
      if (isNumericDetailValue(v)) out.push(field)
      continue
    }
    if (isStringDetailValue(v) && !isNumericDetailValue(v)) out.push(field)
  }
  return out
})

const rankingColumn = computed(() => {
  if (!designsStore.visibleColumns.includes(BINDERDASH_RANKING_FIELD)) return null
  return designsStore.columnsForSelectedRuns.find((col) => col.field === BINDERDASH_RANKING_FIELD) ?? null
})

const getVisibleColumns = () => {
  if (designsStore.columnsForSelectedRuns.length === 0) {
    return []
  }

  return designsStore.columnsForSelectedRuns.filter((col: any) =>
    col.field !== BINDERDASH_RANKING_FIELD && designsStore.visibleColumns.includes(col.field)
  )
}


// Watchers
// Designs load is triggered from App.vue (tab + auth) and run selection in the store.

// Sync spinning state when viewer changes
watch(() => molstarViewerRef.value?.isSpinning, (newSpinningState) => {
  if (newSpinningState !== undefined) {
    isSpinning.value = newSpinningState
  }
}, { immediate: true })

// Sync alphafoldView state when viewer changes
watch(() => molstarViewerRef.value?.alphafoldViewEnabled, (newAlphaFoldState) => {
  if (newAlphaFoldState !== undefined) {
    alphafoldViewEnabled.value = newAlphaFoldState
  }
}, { immediate: true })

watch(() => molstarViewerRef.value?.referenceStructureVisible, (v) => {
  if (v !== undefined) {
    referenceStructureVisible.value = v
  }
}, { immediate: true })

watch(
  () => designsStore.currentStructure?.design,
  (design) => {
    tagOverlayMode.value = tagOverlayFromDesignField(
      design as Record<string, unknown> | undefined
    )
  },
  { immediate: true, deep: true }
)

watch(
  () => designsStore.currentStructure?.design.run_id,
  async (runId, prev) => {
    try {
      if (!runId) {
        revokeReferenceBlob()
        referenceMetrics.value = null
        referenceMembraneData.value = null
        inputTargetsList.value = []
        selectedInputTargetId.value = null
        applyTagPlacementDefaults()
        return
      }
      if (runId === prev) {
        return
      }
      revokeReferenceBlob()
      referenceMetrics.value = null
      referenceMembraneData.value = null
      await restoreAdvancedRef(runId)
      await restoreTagPlacementSettings(runId)
      const needInputTargets =
        showAdvancedOptions.value ||
        (referenceOverlayActive.value && showInputTargetStructure.value)
      if (needInputTargets) {
        await refreshInputTargetsForRun(runId)
        if (selectedInputTargetId.value) {
          const ok = inputTargetsList.value.some((t) => t.id === selectedInputTargetId.value)
          if (!ok) selectedInputTargetId.value = null
        }
        if (inputTargetsList.value.length === 1) {
          selectedInputTargetId.value = inputTargetsList.value[0].id
        }
      } else {
        inputTargetsList.value = []
      }
      if (referenceOverlayActive.value && canLoadReferenceOverlay.value) {
        await loadReferenceOverlay(true)
      } else if (referenceOverlayActive.value) {
        referenceOverlayActive.value = false
        persistAdvancedRef(runId)
      }
    } catch (e) {
      console.error('DesignsView: reference/run watcher failed', e)
    }
  },
  { immediate: true }
)

watch(showInputTargetStructure, (useInput) => {
  const rid = designsStore.currentStructure?.design.run_id
  if (useInput && rid && inputTargetsList.value.length === 0 && !inputTargetsLoading.value) {
    void refreshInputTargetsForRun(rid)
  }
})

watch(
  () => designsStore.currentStructure?.filename,
  async (fn, prev) => {
    if (!fn || fn === prev || !referenceOverlayActive.value) return
    if (canLoadReferenceOverlay.value) {
      await loadReferenceOverlay(true)
    }
  }
)

watch(
  [
    () => designsStore.currentStructure?.design?.run_id,
    () => designsStore.currentStructure?.filename,
    referenceOverlayActive,
    referenceLoading,
    referenceViewerUrl,
  ],
  () => {
    const cs = designsStore.currentStructure
    if (!cs) {
      molstarPdbUrlForViewer.value = ''
      molstarReferenceUrlForViewer.value = ''
      return
    }
    const pdb = runsApi.getPdbFileUrl(cs.design.run_id, cs.filename)
    if (!referenceOverlayActive.value) {
      molstarPdbUrlForViewer.value = pdb
      molstarReferenceUrlForViewer.value = ''
      return
    }
    if (referenceLoading.value) {
      if (molstarPdbUrlForViewer.value !== '') {
        return
      }
      molstarPdbUrlForViewer.value = pdb
      molstarReferenceUrlForViewer.value = ''
      return
    }
    molstarPdbUrlForViewer.value = pdb
    molstarReferenceUrlForViewer.value = referenceViewerUrl.value
  },
  { flush: 'pre', immediate: true }
)

watch(
  [
    referenceManualSource,
    referenceManualSourceKind,
    referenceChainIdsInput,
    showInputTargetStructure,
    selectedInputTargetId,
  ],
  () => {
    const rid = designsStore.currentStructure?.design.run_id
    if (rid) persistAdvancedRef(rid)
    persistGlobalAdvRef()
  }
)

watch(tagPlacementBinderChain, (nv, ov) => {
  applyOppositeBinderDefaultTargetChains(ov, nv)
})

watch(
  [
    tagPlacementBinderChain,
    tagPlacementTargetChains,
    tagPlacementDistantFrom,
    tagPlacementSasaProbe,
    tagPlacementSasaPoints,
    tagPlacementSasaThreshold,
    tagPlacementMoreDist,
    tagPlacementOnlyEmptyTags,
  ],
  () => {
    const rid = designsStore.currentStructure?.design.run_id
    if (rid) persistTagPlacementSettings(rid)
  },
)

watch(
  () => designsStore.currentStructure,
  () => {
    void nextTick(() => clampViewerControlsIfNeeded())
  }
)

function onViewerControlsResize() {
  clampViewerControlsIfNeeded()
}

// Lifecycle
onMounted(() => {
  void loadGlobalAdvRef()
  void loadViewerControlsPos()
  window.addEventListener('resize', onViewerControlsResize)
})

onUnmounted(() => {
  if (tagMetricsDebounceTimer) clearTimeout(tagMetricsDebounceTimer)
  if (referenceBlobUrlToRevoke.value) {
    try {
      URL.revokeObjectURL(referenceBlobUrlToRevoke.value)
    } catch {
      /* ignore */
    }
    referenceBlobUrlToRevoke.value = null
  }
  window.removeEventListener('resize', onViewerControlsResize)
  window.removeEventListener('pointermove', onViewerControlsPointerMove)
  window.removeEventListener('pointerup', onViewerControlsPointerUp)
  window.removeEventListener('pointercancel', onViewerControlsPointerUp)
})

// Expose methods to parent component
defineExpose({
  loadDesigns
})
</script>

<style scoped>
.designs-view {
  --rating-good-bg: #d8f3dc;
  --rating-good-fg: #1b4332;
  --rating-bad-bg: #fcd4e0;
  --rating-bad-fg: #9d174d;

  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.designs-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 1rem;
  border-bottom: 1px solid #e9ecef;
}

.designs-header h2 {
  margin: 0;
  color: #495057;
}

.designs-controls {
  display: flex;
  gap: 0.5rem;
}

.designs-content {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.designs-table-section {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  overflow: hidden;
}

.designs-table-toolbar {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  width: 100%;
  box-sizing: border-box;
  padding-bottom: 0.75rem;
  gap: 0;
}

.designs-column-selector {
  gap: 0.75rem;
  min-width: 0;
}

.designs-toolbar-row {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
  margin-top: 0.75rem;
  width: 100%;
  box-sizing: border-box;
}

.designs-toolbar-divider {
  width: 1px;
  align-self: stretch;
  min-height: 1.75rem;
  background: #ced4da;
  flex-shrink: 0;
}

.designs-column-multiselect {
  min-width: 14rem;
  max-width: min(100%, 28rem);
}

.designs-export-panel {
  border: 1px solid #ced4da;
  border-radius: 8px;
  padding: 0.5rem 0.75rem;
  width: 100%;
  box-sizing: border-box;
}

.designs-download-upload-row {
  column-gap: 0;
  gap: 0;
}

.designs-download-upload-row > .p-splitbutton + .p-splitbutton {
  margin-left: 0.5rem;
}

/* Holds the contact map's colour key, teleported from the Target contact map panel.
   Collapses to nothing when the map is off, so it costs no space in the usual case. */
.contact-map-legend-slot {
  padding: 0.5rem 0.75rem 0.25rem;
}

.contact-map-legend-slot:empty {
  display: none;
}

.advanced-options-section {
  margin-top: 1rem;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.advanced-options-disclosure {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  margin: 0;
  border: none;
  background: #f8f9fa;
  padding: 0.65rem 1rem;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: #495057;
}

.advanced-options-disclosure:hover {
  background: #e9ecef;
}

.advanced-options-chevron {
  font-size: 0.85rem;
  color: #6c757d;
  flex-shrink: 0;
}

.advanced-options-disclosure-label {
  font-weight: 600;
  font-size: 1rem;
}

.advanced-options-expanded {
  padding: 1rem 1.25rem 1.25rem;
  border-top: 1px solid #e9ecef;
}

.advanced-options-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.advanced-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.advanced-row--full {
  flex-wrap: wrap;
}

.advanced-label {
  min-width: 140px;
  font-weight: 500;
  color: #495057;
}

.advanced-label-with-info {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}

.advanced-label-with-info label {
  margin: 0;
  cursor: default;
}

.advanced-reference-info-icon {
  font-size: 0.7rem;
  color: #6c757d;
  cursor: help;
  line-height: 1;
}

.advanced-reference-info-icon:hover,
.advanced-reference-info-icon:focus-visible {
  color: #495057;
  outline: none;
}

.advanced-checkbox-label {
  margin: 0;
  cursor: pointer;
  color: #495057;
}

.advanced-reference-source-controls {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 0.5rem;
  min-width: 200px;
}

.advanced-reference-source-kind {
  flex-shrink: 0;
  width: 9.75rem;
}

.advanced-input {
  flex: 1;
  min-width: 200px;
  max-width: 100%;
}

.advanced-input--in-reference-row {
  min-width: 0;
}

.advanced-dropdown {
  flex: 1;
  min-width: 200px;
  max-width: 420px;
}

.advanced-hint {
  margin: 0;
  font-size: 0.9rem;
  color: #6c757d;
}

.advanced-hint--warn {
  color: #856404;
}

.advanced-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.tag-placement-progress {
  margin-bottom: 0.75rem;
}

.tag-placement-progress-label {
  display: block;
  margin-top: 0.35rem;
  font-size: 0.85rem;
  color: var(--text-color-secondary, #6c757d);
}

.tag-metrics-hint {
  margin: 0 0 0.5rem 0;
  font-size: 0.875rem;
  color: #6c757d;
}

.tag-metrics-datatable {
  margin-bottom: 0.75rem;
}

.tag-metrics-cell {
  display: inline-block;
  padding: 0.1rem 0.3rem;
  border-radius: 0.25rem;
}

.tag-metrics-cell--muted {
  background: #f1f3f5;
}

.tag-metrics-cell--highlight {
  background: #fff3bf;
}

.tag-metrics-pred {
  font-weight: 700;
}

.tag-metrics-pred--n {
  color: #1e5ac8;
}

.tag-metrics-pred--c {
  color: #780000;
}

.tag-metrics-seq {
  display: inline-block;
  max-width: 8rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.tag-metrics-error {
  color: #c62828;
  font-size: 0.8125rem;
}

.advanced-actions--tag-top {
  margin-bottom: 0.75rem;
}

.tag-placement-input-number {
  width: 100%;
  max-width: 220px;
}

.reference-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem 1.5rem;
  font-size: 0.875rem;
  color: #495057;
  padding-top: 0.5rem;
  border-top: 1px solid #e9ecef;
}

.structure-viewer-section {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  padding: 1.5rem;
}

.viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.viewer-header h3 {
  margin: 0;
  color: #495057;
}

.viewer-controls {
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.35rem;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #e9ecef;
  border-radius: 9999px;
  padding: 0.25rem 0.5rem 0.25rem 0.15rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  opacity: 1;
  z-index: 5;
}

.viewer-controls-drag {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  padding: 0.2rem 0.4rem;
  margin-left: -0.05rem;
  margin-right: 0.1rem;
  cursor: grab;
  touch-action: none;
  color: #868e96;
  border-right: 1px solid #dee2e6;
  border-radius: 9999px 0 0 9999px;
  user-select: none;
}

.viewer-controls-drag:hover {
  color: #495057;
  background: rgba(0, 0, 0, 0.05);
}

.viewer-controls-drag:active {
  cursor: grabbing;
}

.viewer-controls-drag:focus-visible {
  outline: 2px solid #667eea;
  outline-offset: 1px;
}

.structure-counter {
  font-weight: 500;
  color: #495057;
  min-width: 60px;
  text-align: center;
}

.viewer-container {
  position: relative;
}

/* Controls are always visible */

.structure-info {
  margin-bottom: 1rem;
  padding: 1rem;
  background: #f8f9fa;
  border-radius: 6px;
}

.details-section {
  margin-bottom: 0.75rem;
}

.details-section-title {
  font-weight: 600;
  color: #495057;
  margin-bottom: 0.5rem;
}

.details-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.75rem 1rem;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  background: #ffffff;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  padding: 0.5rem 0.75rem;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: box-shadow 0.15s ease, transform 0.15s ease, border-color 0.15s ease;
}

.detail-item.clickable {
  cursor: pointer;
}

.score-bar {
  height: 6px;
  border-radius: 3px;
  margin-bottom: 0.25rem;
}

.detail-label {
  font-size: 0.8rem;
  color: #6c757d;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.detail-label-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
  min-width: 0;
}

.detail-label-row .detail-label {
  flex: 1;
  min-width: 0;
}

.detail-value {
  font-size: 1rem;
  color: #343a40;
  font-weight: 600;
  word-break: break-all;
}

.file-item .file-value {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.truncate-ellipsis {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-item:hover {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
  border-color: #e2e6ea;
}

/* Removed full-width spanning for file item to match other cards */

.file-value {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.file-value :deep(.p-button) {
  flex-shrink: 0;
  aspect-ratio: 1;
}

.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  /* Assume ~8px per char average for this font size; 128 chars ≈ 1024px */
  max-width: 1024px;
}


.no-selection {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  padding: 3rem;
}

.no-selection-content {
  text-align: center;
  color: #6c757d;
}

.no-selection-content h3 {
  margin: 1rem 0 0.5rem 0;
  color: #495057;
}

.no-selection-content p {
  margin: 0;
  font-size: 1rem;
}

/* PrimeVue overrides */
:deep(.p-datatable) {
  border: none;
}

:deep(.p-datatable .p-datatable-thead > tr > th) {
  background: #f8f9fa;
  border-bottom: 1px solid #e9ecef;
  font-weight: 600;
}

:deep(.p-datatable .p-datatable-tbody > tr > td) {
  border-bottom: 1px solid #f1f3f4;
}

:deep(.p-datatable .p-datatable-tbody > tr:hover > td) {
  background: #f8f9fa;
}

:deep(.p-datatable .p-datatable-tbody > tr) {
  cursor: pointer;
}

:deep(.p-datatable .p-datatable-tbody > tr > td) {
  user-select: none;
}

/* Pagination spacing improvements */
:deep(.p-datatable .p-paginator) {
  padding: 1rem 0;
  gap: 0.5rem;
}

:deep(.p-datatable .p-paginator .p-paginator-pages) {
  gap: 0.25rem;
}

:deep(.p-datatable .p-paginator .p-paginator-pages .p-paginator-page) {
  margin: 0 0.125rem;
}

:deep(.p-datatable .p-paginator .p-paginator-first,
       .p-datatable .p-paginator .p-paginator-prev,
       .p-datatable .p-paginator .p-paginator-next,
       .p-datatable .p-paginator .p-paginator-last) {
  margin: 0 0.25rem;
}

:deep(.p-datatable .p-paginator .p-paginator-current) {
  margin: 0 1rem;
}

:deep(.p-datatable .p-paginator .p-dropdown) {
  margin-left: 0.5rem;
}

.params-json-container {
  max-height: 70vh;
  overflow: auto;
}

.params-pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.9rem;
  margin: 0;
}

/* Select top controls styling */
.select-top-input {
  width: 60px;
  min-width: 60px;
}

.select-top-input :deep(.p-inputnumber-input) {
  text-align: center;
  width: 100%;
}

.select-top-controls {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  white-space: nowrap;
  flex-shrink: 0;
}

.viewer-controls :deep(.p-button.strikethrough-disabled .p-button-label) {
  text-decoration: line-through;
}

.viewer-controls :deep(.viewer-thumb-btn.p-button) {
  border-width: 1px;
  border-style: solid;
}

.viewer-controls :deep(.viewer-thumb-btn--good.p-button) {
  background: var(--rating-good-bg) !important;
  color: var(--rating-good-fg) !important;
  border-color: color-mix(in srgb, var(--rating-good-fg) 20%, transparent) !important;
}

.viewer-controls :deep(.viewer-thumb-btn--good.p-button:not(:disabled):hover) {
  background: color-mix(in srgb, var(--rating-good-bg) 82%, var(--rating-good-fg)) !important;
  border-color: color-mix(in srgb, var(--rating-good-fg) 35%, transparent) !important;
}

.viewer-controls :deep(.viewer-thumb-btn--good.p-button.viewer-thumb-btn--selected) {
  box-shadow: inset 0 0 0 2px var(--rating-good-fg);
}

.viewer-controls :deep(.viewer-thumb-btn--bad.p-button) {
  background: var(--rating-bad-bg) !important;
  color: var(--rating-bad-fg) !important;
  border-color: color-mix(in srgb, var(--rating-bad-fg) 22%, transparent) !important;
}

.viewer-controls :deep(.viewer-thumb-btn--bad.p-button:not(:disabled):hover) {
  background: color-mix(in srgb, var(--rating-bad-bg) 80%, var(--rating-bad-fg)) !important;
  border-color: color-mix(in srgb, var(--rating-bad-fg) 38%, transparent) !important;
}

.viewer-controls :deep(.viewer-thumb-btn--bad.p-button.viewer-thumb-btn--selected) {
  box-shadow: inset 0 0 0 2px var(--rating-bad-fg);
}

.viewer-controls :deep(.viewer-thumb-btn.p-button:disabled) {
  opacity: 0.45;
}

.tag-toolbar-label {
  display: inline-flex;
  align-items: baseline;
  gap: 0.25rem;
}

.tag-toolbar-mode {
  font-weight: 700;
}

.tag-toolbar-mode--n {
  color: #1e5ac8;
}

.tag-toolbar-mode--c {
  color: #780000;
}

.good-cell {
  box-sizing: border-box;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  min-height: 1.85rem;
  line-height: 1;
}

.good-cell--true,
.good-cell--false {
  width: 100%;
  padding: 0.35rem 0.5rem;
  border-radius: 0.35rem;
}

.good-cell--true {
  background-color: var(--rating-good-bg);
  color: var(--rating-good-fg);
}

.good-cell--false {
  background-color: var(--rating-bad-bg);
  color: var(--rating-bad-fg);
}

.good-cell--empty {
  width: 100%;
  justify-content: center;
  padding: 0.15rem 0;
}

.good-cell-symbol {
  font-size: 1.15rem;
  font-weight: 700;
}

.good-cell-dash {
  color: var(--p-text-muted-color, #6c757d);
  font-size: 0.95rem;
  font-weight: 400;
}
</style>
