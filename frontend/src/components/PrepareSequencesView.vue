<template>
  <div class="prepare-sequences-view">
    <div class="ps-header">
      <h2>Prepare sequences</h2>
    </div>

    <div class="ps-intro-box">
      <p class="ps-intro">
        <strong>Tagging:</strong> Tags you place in the <strong>N-tagged</strong> and <strong>C-tagged</strong> areas are only added to designs whose
        <strong>tag</strong> column is <code>N</code> or <code>C</code> respectively. Designs with another tag value get
        only the core sequence plus the global N/C terminal additions and optional terminal stops.
      </p>
      <p class="ps-case-help">
        <strong>Entering amino acid and nucleotides:</strong> Sequences entered in uppercase are interpreted as amino acids, lowercase are nucleotides. You can mix and match
        upper and lowercase (eg <code>atgGS</code> translates to <code>MGS</code>).
      </p>
      <p class="ps-case-help">
        <br>
        <strong>Short names:</strong> Optional strategies shorten <code>design_id</code> to ≤32 characters for synthesis orders.
      </p>
    </div>

    <div class="ps-order-name">
      <label for="ps-export-order-name">Order name:</label>
      <InputText
        id="ps-export-order-name"
        v-model="seqPrep.exportOrderName"
        placeholder="Optional; used in download filenames instead of prepared_sequences"
        class="w-full"
      />
    </div>

    <div class="ps-builder card-like">
      <div class="ps-builder-row">
        <div class="ps-zone">
          <span class="ps-zone-label">N-tagged</span>
          <div class="ps-chips">
            <Chip
              v-for="(t, i) in seqPrep.nTags"
              :key="t.id"
              :label="`${t.label} ${tagSequenceDisplay(t.kind, t.sequence)}`"
              removable
              class="ps-tag-chip"
              :style="tagPresetChipCssVars(t.kind)"
              @remove="seqPrep.removeTag('n', i)"
            >
              <div class="ps-tag-chip-body">
                <span class="ps-tag-chip-name">{{ t.label }}</span>
                <span class="ps-tag-chip-seq">{{ tagSequenceDisplay(t.kind, t.sequence) }}</span>
              </div>
            </Chip>
            <span v-if="seqPrep.nTags.length === 0" class="ps-placeholder">Add tags below</span>
          </div>
        </div>
        <span class="ps-binder-label">-{design}-</span>
        <div class="ps-zone">
          <span class="ps-zone-label">C-tagged</span>
          <div class="ps-chips">
            <Chip
              v-for="(t, i) in seqPrep.cTags"
              :key="t.id"
              :label="`${t.label} ${tagSequenceDisplay(t.kind, t.sequence)}`"
              removable
              class="ps-tag-chip"
              :style="tagPresetChipCssVars(t.kind)"
              @remove="seqPrep.removeTag('c', i)"
            >
              <div class="ps-tag-chip-body">
                <span class="ps-tag-chip-name">{{ t.label }}</span>
                <span class="ps-tag-chip-seq">{{ tagSequenceDisplay(t.kind, t.sequence) }}</span>
              </div>
            </Chip>
            <span v-if="seqPrep.cTags.length === 0" class="ps-placeholder">Add tags below</span>
          </div>
        </div>
      </div>

      <div class="ps-palette">
        <div class="ps-palette-group">
          <span class="ps-palette-label">Add to N side:</span>
          <Button
            v-for="p in seqPrep.presetOptionsN"
            :key="'n-' + p.kind"
            size="small"
            severity="secondary"
            outlined
            :label="p.display_sequence ? `${p.tag_name} ${p.display_sequence}` : p.tag_name"
            class="ps-preset-btn"
            :style="tagPresetChromeStyle(p.kind)"
            @click="seqPrep.addPreset('n', p)"
          />
        </div>
        <div class="ps-palette-group">
          <span class="ps-palette-label">Add to C side:</span>
          <Button
            v-for="p in seqPrep.presetOptionsC"
            :key="'c-' + p.kind"
            size="small"
            severity="secondary"
            outlined
            :label="p.display_sequence ? `${p.tag_name} ${p.display_sequence}` : p.tag_name"
            class="ps-preset-btn"
            :style="tagPresetChromeStyle(p.kind)"
            @click="seqPrep.addPreset('c', p)"
          />
        </div>
      </div>
      <div class="ps-custom-row">
        <InputText
          v-model="seqPrep.customTagInput"
          placeholder="Custom sequence (UPPERCASE=AA, lowercase=nuc)"
          class="ps-custom-input"
          @keyup.enter="addCustomBoth"
        />
        <Button size="small" label="Add custom → N" @click="seqPrep.addCustomTag('n')" />
        <Button size="small" label="Add custom → C" @click="seqPrep.addCustomTag('c')" />
      </div>
    </div>

    <div class="ps-form grid card-like">
      <div class="ps-field">
        <label for="ps-npre">Add sequence to all N-terminal</label>
        <InputText
          id="ps-npre"
          v-model="seqPrep.nTerminalPrefix"
          class="w-full ps-terminal-input ps-terminal-input--n"
        />
      </div>
      <div class="ps-field">
        <label for="ps-csuf">Add sequence to all C-terminal</label>
        <InputText
          id="ps-csuf"
          v-model="seqPrep.cTerminalSuffix"
          class="w-full ps-terminal-input ps-terminal-input--c"
        />
      </div>
      <div class="ps-field ps-checks ps-checks--stops">
        <div class="ps-stop-check">
          <Checkbox v-model="seqPrep.includeStopForNTagged" input-id="ps-stop-n" binary />
          <label for="ps-stop-n">Include * stop for N-tagged</label>
        </div>
        <div class="ps-stop-check">
          <Checkbox v-model="seqPrep.includeStopForCTagged" input-id="ps-stop-c" binary />
          <label for="ps-stop-c">Include * stop for C-tagged</label>
        </div>
        <div class="ps-stop-check">
          <Checkbox v-model="seqPrep.useDoubleStop" input-id="ps-stop-double" binary />
          <label for="ps-stop-double">Use double stop **</label>
        </div>
        <div class="ps-stop-check">
          <Checkbox v-model="seqPrep.dontModifyStartAtg" input-id="ps-start-atg" binary />
          <label for="ps-start-atg">Don't modify 5' start (ATG)</label>
        </div>
      </div>
      <div class="ps-field">
        <label for="ps-chain">Chain to extract (PDB/mmCIF)</label>
        <Select
          id="ps-chain"
          v-model="seqPrep.extractChain"
          :options="chainOptions"
          class="w-full"
        />
      </div>
      <div class="ps-field-row ps-field-row--padding">
        <div class="ps-field">
          <label for="ps-pad">Post-stop padding</label>
          <InputText
            id="ps-pad"
            v-model="seqPrep.postStopPadding"
            class="w-full"
            placeholder="UPPERCASE=AA, lowercase=nuc (a,c,g,t)"
          />
        </div>
        <div class="ps-field">
          <label for="ps-pad-up-to">Pad up to nucleotide length (bp)</label>
          <InputNumber
            id="ps-pad-up-to"
            v-model="seqPrep.postStopPadUpToNucleotideLength"
            class="w-full"
            :min="0"
            :allow-empty="true"
            placeholder="Leave empty to omit padding"
          />
        </div>
        <div class="ps-field ps-field-span-2">
          <div class="ps-stop-check">
            <Checkbox
              v-model="seqPrep.onlyUseNTerminalTagWhenPaddingRequired"
              input-id="ps-ntag-pad-only"
              binary
            />
            <label for="ps-ntag-pad-only">Only use N-terminal tag when padding required</label>
          </div>
        </div>
        <div class="ps-field ps-field-span-2">
          <div class="ps-stop-check">
            <Checkbox
              v-model="seqPrep.onlyUseCTerminalTagWhenPaddingRequired"
              input-id="ps-ctag-pad-only"
              binary
            />
            <label for="ps-ctag-pad-only">Only use C-terminal tag when padding required</label>
          </div>
        </div>
      </div>
      <div v-if="seqPrep.dnaMode" class="ps-field">
        <label for="ps-minlen">Minimum DNA fragment length (bp)</label>
        <InputNumber
          id="ps-minlen"
          v-model="seqPrep.minDnaFragmentLength"
          :min="0"
          :max="100000"
          class="w-full"
        />
      </div>
    </div>

    <TogglePanel
      header="Short name"
      v-model:collapsed="shortNamePanelCollapsed"
      class="ps-short-name-panel card-like mb-4"
      :class="{ 'ps-short-name-panel--warn': shortNameUniquenessWarning }"
    >
      <p class="ps-short-name-lead">
        Strategies to shorten <code>design_id</code> to ≤32 characters for synthesis orders.
        <br>
      </p>
      <div class="ps-short-name-grid">
        <div class="ps-field">
          <label for="ps-sn-strategy">Strategy</label>
          <Select
            id="ps-sn-strategy"
            v-model="seqPrep.shortNameKind"
            :options="shortNameStrategyOptions"
            option-label="label"
            option-value="value"
            class="w-full"
          />
        </div>
        <div class="ps-field">
          <label for="ps-sn-max">Max length</label>
          <InputNumber
            id="ps-sn-max"
            v-model="seqPrep.shortNameMaxLen"
            class="w-full"
            :min="8"
            :max="64"
          />
        </div>
        <div v-if="seqPrep.shortNameKind === 'regex'" class="ps-field ps-field-span-2">
          <label>Regex replace on design_id</label>
          <div class="ps-short-name-row">
            <InputText v-model="seqPrep.shortNameRegexPattern" placeholder="Pattern" class="flex-1" />
            <InputText v-model="seqPrep.shortNameRegexReplacement" placeholder="Replacement" class="flex-1" />
            <InputText v-model="seqPrep.shortNameRegexFlags" placeholder="Flags (e.g. g)" class="w-6rem" />
          </div>
        </div>
        <div v-if="seqPrep.shortNameKind === 'splitTake'" class="ps-field ps-field-span-2">
          <label>Split + 1-based indices (comma-separated)</label>
          <div class="ps-short-name-row">
            <InputText v-model="seqPrep.shortNameSplitDelimiter" placeholder="Delimiter" class="w-8rem" />
            <InputText v-model="seqPrep.shortNameSplitIndices" placeholder="e.g. 1,2,3" class="flex-1" />
          </div>
        </div>
        <div v-if="seqPrep.shortNameKind === 'splitTake'" class="ps-field">
          <label for="ps-sn-split-add-pre">Add prefix</label>
          <InputText id="ps-sn-split-add-pre" v-model="seqPrep.shortNameSplitAddPrefix" class="w-full" placeholder="Optional" />
        </div>
        <div v-if="seqPrep.shortNameKind === 'splitTake'" class="ps-field">
          <label for="ps-sn-split-add-suf">Add suffix</label>
          <InputText id="ps-sn-split-add-suf" v-model="seqPrep.shortNameSplitAddSuffix" class="w-full" placeholder="Optional" />
        </div>
        <div v-if="seqPrep.shortNameKind === 'splitTake'" class="ps-field ps-field-span-2">
          <div class="ps-short-name-row">
            <Checkbox v-model="seqPrep.shortNameSplitAddHash" input-id="ps-sn-split-hash" binary />
            <label
              for="ps-sn-split-hash"
              title="Appends _{hash} after the joined segments (hash from design_id). Stem is shortened if needed for max length."
              >Add hash</label
            >
          </div>
        </div>
        <template v-if="seqPrep.shortNameKind === 'pattern'">
          <div class="ps-field">
            <label>Prefix</label>
            <InputText v-model="seqPrep.shortNamePatternPrefix" class="w-full" />
          </div>
          <div class="ps-field">
            <label>UID length / number pad</label>
            <div class="ps-short-name-row">
              <InputNumber v-model="seqPrep.shortNamePatternUidLength" :min="3" :max="10" class="w-full" />
              <InputNumber v-model="seqPrep.shortNamePatternNumberPad" :min="0" :max="6" class="w-full" />
            </div>
          </div>
        </template>
        <div v-if="seqPrep.shortNameKind === 'smartStemHash'" class="ps-field ps-field-span-2">
          <div class="ps-short-name-row">
            <Checkbox v-model="seqPrep.shortNameSmartStemIncludeHash" input-id="ps-sn-stem-hash" binary />
            <label for="ps-sn-stem-hash" title="Append base52 hash of the original AA sequence after the stem.">Include hash</label>
          </div>
        </div>
        <div
          v-if="
            seqPrep.shortNameKind === 'smartStemHash' ||
            seqPrep.shortNameKind === 'smartRegexStrip' ||
            (seqPrep.shortNameKind === 'splitTake' && seqPrep.shortNameSplitAddHash)
          "
          class="ps-field"
        >
          <label>Hash length (base52)</label>
          <InputNumber
            v-model="seqPrep.shortNameSmartHashLen"
            :min="3"
            :max="10"
            class="w-full"
            :disabled="seqPrep.shortNameKind === 'smartStemHash' && !seqPrep.shortNameSmartStemIncludeHash"
          />
        </div>
        <div v-if="seqPrep.shortNameKind === 'smartStemHash'" class="ps-field ps-field-span-2">
          <div class="ps-short-name-row">
            <Checkbox v-model="seqPrep.shortNameSmartStemIncludeIndex" input-id="ps-sn-stem-idx" binary />
            <label
              for="ps-sn-stem-idx"
              title="Append 1-based row index after the hash when hash is on, or after the stem when hash is off (stem shortened to fit max length)."
              >Include index</label
            >
          </div>
        </div>
        <div v-if="seqPrep.shortNameKind === 'smartStemHash'" class="ps-field ps-field-span-2">
          <div class="ps-short-name-row">
            <Checkbox v-model="seqPrep.shortNameSmartStemRemoveCommonPrefix" input-id="ps-sn-stem-lcp" binary />
            <label
              for="ps-sn-stem-lcp"
              title="Strip the longest prefix shared by every design_id in the current table (no effect with a single row)."
              >Remove common prefix</label
            >
          </div>
          <div class="ps-short-name-row">
            <Checkbox v-model="seqPrep.shortNameSmartStemRemoveCommonSuffix" input-id="ps-sn-stem-lcs" binary />
            <label
              for="ps-sn-stem-lcs"
              title="Strip the longest suffix shared by every design_id in the current table (no effect with a single row)."
              >Remove common suffix</label
            >
          </div>
        </div>
        <div v-if="seqPrep.shortNameKind === 'smartStemHash'" class="ps-field">
          <label for="ps-sn-stem-add-pre">Add prefix</label>
          <InputText id="ps-sn-stem-add-pre" v-model="seqPrep.shortNameSmartStemAddPrefix" class="w-full" placeholder="Optional" />
        </div>
        <div v-if="seqPrep.shortNameKind === 'smartStemHash'" class="ps-field">
          <label for="ps-sn-stem-add-suf">Add suffix</label>
          <InputText id="ps-sn-stem-add-suf" v-model="seqPrep.shortNameSmartStemAddSuffix" class="w-full" placeholder="Optional" />
        </div>
        <div v-if="seqPrep.shortNameKind === 'smartRegexStrip'" class="ps-field ps-field-span-2">
          <label>Drop prefix (regex)</label>
          <InputText v-model="seqPrep.shortNameStripPrefixRegex" class="w-full" placeholder="^batch-\d+_" />
        </div>
        <div v-if="seqPrep.shortNameKind === 'smartRegexStrip'" class="ps-field ps-field-span-2">
          <label>Drop suffix (regex)</label>
          <InputText v-model="seqPrep.shortNameStripSuffixRegex" class="w-full" placeholder="_suffix$" />
        </div>
        <div v-if="seqPrep.shortNameKind === 'smartRegexStrip'" class="ps-field">
          <label>New prefix</label>
          <InputText v-model="seqPrep.shortNameStripNewPrefix" class="w-full" placeholder="Optional replacement prefix" />
        </div>
      </div>
      <div class="ps-short-name-footer">
        <Button
          size="small"
          severity="secondary"
          outlined
          label="Clear short names (DB)"
          :disabled="seqPrep.preparedRows.length === 0"
          @click="onClearShortNames"
        />
        <Message
          v-if="seqPrep.shortNameDedupeCount > 0"
          severity="warn"
          class="ps-sn-dedupe"
          :closable="false"
        >
          <div class="ps-warnings-banner-inner">
            <i class="pi pi-exclamation-triangle ps-warn-banner-icon" aria-hidden="true" />
            <span>Auto-deduped: {{ seqPrep.shortNameDedupeCount }} name(s) needed a suffix</span>
          </div>
        </Message>
      </div>
      <div v-if="shortNamePreviewLines.length > 0" class="ps-sn-preview">
        <strong>Preview:</strong>
        <ul class="ps-sn-preview-list">
          <li v-for="(line, i) in shortNamePreviewLines" :key="i">{{ line }}</li>
        </ul>
      </div>
    </TogglePanel>

    <div class="ps-optimization-toolbar card-like mt-3">
      <div class="ps-opt-header">
        <div class="ps-codon-field">
          <label for="ps-codon-table" class="ps-codon-label">Target organism (Codon table)</label>
          <Select
            id="ps-codon-table"
            v-model="seqPrep.selectedCodonTable"
            :options="seqPrep.codonTableOptions"
            option-label="label"
            option-value="value"
            :loading="seqPrep.codonTablesListLoading || seqPrep.codonTablesDetailLoading"
            class="ps-codon-select w-full md:w-20rem"
          />
        </div>
        <div class="ps-opt-actions">
          <Button
            label="Optimize DNA"
            icon="pi pi-bolt"
            severity="primary"
            :loading="seqPrep.optimizing"
            :disabled="seqPrep.preparedRows.length === 0"
            @click="seqPrep.runOptimization()"
          />
        </div>
      </div>
    </div>

    <TogglePanel
      header="DNA Optimization Constraints"
      v-model:collapsed="optimizationPanelCollapsed"
      class="ps-optimization-panel card-like mb-4"
    >
      <div class="ps-opt-content">
        <Message v-if="seqPrep.optimizationGlobalError" severity="error" :closable="false" class="ps-opt-msg mb-4">{{ seqPrep.optimizationGlobalError }}</Message>
        <Message v-if="seqPrep.optimizationStale && seqPrep.optimizationEverSucceeded" severity="warn" :closable="false" class="ps-opt-msg mb-4">Inputs changed. Run optimization to update sequence DNA.</Message>

        <div class="ps-opt-panel-actions">
          <Button
            label="Defaults"
            icon="pi pi-refresh"
            severity="secondary"
            size="small"
            @click="seqPrep.resetConstraintsToDefaults()"
          />
        </div>

        <DataTable :value="seqPrep.optimizationConstraints" class="p-datatable-sm" responsiveLayout="scroll">
          <Column field="enabled" header="Active" style="width: 5rem">
            <template #body="{ data }">
              <Checkbox v-model="data.enabled" :binary="true" />
            </template>
          </Column>
          <Column field="type" header="Constraint Type" style="width: 14rem">
            <template #body="{ data, index }">
              <Select
                :model-value="data.type"
                :options="constraintTypeOptions"
                class="w-full"
                @update:model-value="(v: string) => onConstraintTypeChange(data, v, index)"
              />
            </template>
          </Column>
          <Column field="params" header="Parameters">
            <template #body="{ data, index }">
              <Select
                v-if="data.type === 'ExcludeRestrictionSite'"
                :model-value="data.params?.enzyme"
                :options="restrictionEnzymeOptions"
                option-label="label"
                option-value="value"
                option-group-label="label"
                option-group-children="items"
                :filter="true"
                filter-placeholder="Search enzyme or site"
                :filter-fields="['value', 'site', 'label']"
                placeholder="Select a restriction enzyme"
                class="w-full"
                @update:model-value="(v: string) => (data.params = { enzyme: v })"
              >
                <template #optiongroup="{ option }">
                  <strong class="ps-restriction-group-label">{{ option.label }}</strong>
                </template>
              </Select>
              <InputText
                v-else
                :model-value="constraintParamsText(index, data)"
                class="w-full"
                placeholder='{"mini": 0.25}'
                @update:model-value="(v: string) => onConstraintParamsInput(index, data, v)"
              />
            </template>
          </Column>
          <Column headerStyle="width: 4rem">
            <template #body="{ index }">
               <Button icon="pi pi-trash" severity="danger" text @click="onRemoveConstraint(index)" />
            </template>
          </Column>
        </DataTable>

        <div class="ps-opt-table-footer-actions">
          <Button
            label="Add Constraint"
            icon="pi pi-plus"
            severity="secondary"
            size="small"
            @click="seqPrep.addConstraint()"
          />
        </div>
      </div>
    </TogglePanel>

    <div class="ps-actions">
      <Button
        label="Extract missing sequences from structures"
        icon="pi pi-download"
        severity="help"
        :loading="seqPrep.extracting"
        :disabled="seqPrep.inputDesigns.length === 0"
        @click="onExtractMissing"
      />
      <span class="ps-hint">{{ inputSummary }}</span>
    </div>

    <div class="ps-view-bar">
      <div class="ps-view-toggle">
        <span :class="{ 'ps-toggle-active': !seqPrep.dnaMode }">Amino acid</span>
        <ToggleSwitch
          id="ps-view-mode"
          v-model="seqPrep.dnaMode"
          aria-label='Show as "Amino acid / Nucleotide"'
        />
        <span :class="{ 'ps-toggle-active': seqPrep.dnaMode }">Nucleotide</span>
      </div>
      <div class="ps-view-toggle">
        <span :class="{ 'ps-toggle-active': !seqPrep.goodOnly }">All</span>
        <ToggleSwitch
          id="ps-good-only"
          v-model="seqPrep.goodOnly"
          aria-label="Scope: all in scope or good designs only"
        />
        <span :class="{ 'ps-toggle-active': seqPrep.goodOnly }">Good only</span>
      </div>
    </div>

    <div class="ps-table-toolbar">
      <div class="ps-show-pad-toggle">
        <ToggleSwitch
          id="ps-show-post-pad"
          v-model="seqPrep.showPostStopPadding"
          :disabled="seqPrep.dnaMode"
          aria-label="Show post-stop padding (amino acid view)"
        />
        <label
          for="ps-show-post-pad"
          class="ps-show-pad-label"
          :class="{ 'ps-show-pad-label--disabled': seqPrep.dnaMode }"
        >
          Show post-stop padding
        </label>
      </div>
      <label for="ps-column-toggle" class="ps-column-toggle-label">Columns</label>
      <MultiSelect
        id="ps-column-toggle"
        v-model="selectedColumnKeys"
        :options="columnOptions"
        option-label="label"
        option-value="key"
        placeholder="Columns"
        class="ps-column-multiselect"
        display="chip"
        :max-selected-labels="3"
      />
    </div>

    <DataTable
      v-model:filters="tableFilters"
      :value="preparedRowsForTable"
      striped-rows
      paginator
      resizable-columns
      show-gridlines
      filter-display="row"
      :rows="5"
      :rowsPerPageOptions="[5, 10, 24, 48, 96]"
      data-key="row_key"
      class="ps-table"
    >
      <Column
        v-if="selectedColumnKeys.includes('design')"
        field="design_id"
        filter-field="design_filter_text"
        header="Design"
        sortable
        :show-filter-menu="false"
        style="min-width: 13rem"
        body-class="ps-design-cell"
      >
        <template #body="{ data }">
          <span class="ps-design-meta">
            <span class="ps-design-meta-label">Short name:</span>
            <code class="ps-short-name-code">{{ data.short_name }}</code>
            <br />
            <span class="ps-design-meta-label">Design ID:</span> {{ data.design_id }}<br />
            <span class="ps-design-meta-label">Project:</span> {{ data.project_id }}<br />
            <span class="ps-design-meta-label">Run:</span> {{ data.run_name }}
          </span>
        </template>
        <template #filter="{ filterModel, filterCallback }">
          <InputGroup class="p-column-filter w-full bd-inputgroup-inline-clear">
            <InputText
              v-model="filterModel.value"
              type="text"
              placeholder="Filter"
              class="ps-col-filter-input"
              @input="filterCallback()"
            />
            <InputGroupAddon>
              <Button
                icon="pi pi-times"
                severity="secondary"
                variant="text"
                :disabled="!filterModel.value"
                aria-label="Clear design filter"
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
        v-if="selectedColumnKeys.includes('sequence')"
        header="Sequence"
        bodyClass="ps-sequence-cell"
        style="width: 24rem"
      >
        <template #body="{ data }">
          <span class="seq-wrap">
            <template v-if="seqPrep.dnaMode && data.prepared_dna">
              <span
                v-for="(seg, i) in data.segments_dna || [{ text: data.prepared_dna, cssClass: 'seq-seg-dna-body' }]"
                :key="i"
                :class="[seg.cssClass, { 'seq-seg-fixed': seg.fixed }]"
                :style="seg.style"
              >{{ seg.text }}</span>
            </template>
            <template v-else>
              <span
                v-for="(seg, i) in aaSegmentsForView(data)"
                :key="i"
                :class="[seg.cssClass, { 'seq-seg-fixed': seg.fixed }]"
                :style="seg.style"
              >{{ seg.text }}</span>
            </template>
          </span>
        </template>
      </Column>
      <Column
        v-if="selectedColumnKeys.includes('tag')"
        field="tag"
        header="Tag End"
        sortable
        :show-filter-menu="false"
        style="width: 1%; white-space: nowrap"
      >
        <template #filter="{ filterModel, filterCallback }">
          <InputGroup class="p-column-filter ps-tag-filter-input-group bd-inputgroup-inline-clear">
            <InputText
              v-model="filterModel.value"
              type="text"
              placeholder="N/C"
              class="ps-col-filter-input"
              @input="filterCallback()"
            />
            <InputGroupAddon>
              <Button
                icon="pi pi-times"
                severity="secondary"
                variant="text"
                :disabled="!filterModel.value"
                aria-label="Clear tag filter"
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
        v-if="selectedColumnKeys.includes('length')"
        field="sort_tagged_length"
        :header="lengthColumnHeader"
        sortable
        style="width: 8rem"
      >
        <template #body="{ data }">
          {{ taggedLength(data) }}
        </template>
      </Column>
      <Column
        v-if="selectedColumnKeys.includes('warnings')"
        field="sort_warnings"
        header="Warnings"
        sortable
        style="width: 10rem"
      >
        <template #body="{ data }">
          <span v-if="data.warnings.length > 0" class="ps-warn-cell">
            <i class="pi pi-exclamation-triangle ps-warn-icon" aria-hidden="true" />
            <span class="ps-warn-text">{{ data.warnings.join(', ') }}</span>
          </span>
        </template>
      </Column>
      <Column
        v-if="selectedColumnKeys.includes('extinction')"
        field="sort_extinction_coeff_reduced"
        header="ε₂₈₀"
        sortable
        style="width: 7.5rem"
      >
        <template #body="{ data }">
          <span class="ps-ext-stack">
            <span class="ps-ext-main">{{ data.extinction_coeff_reduced }}</span>
            <span
              v-if="data.extinction_coeff_reduced !== data.extinction_coeff_oxidized"
              class="ps-ext-ox"
            >
              (ox: {{ data.extinction_coeff_oxidized }})
            </span>
          </span>
        </template>
      </Column>
      <Column
        v-if="selectedColumnKeys.includes('pi')"
        field="isoelectric_point"
        header="pI"
        sortable
        style="width: 5rem"
      >
        <template #body="{ data }">
          {{ formatPi(data.isoelectric_point) }}
        </template>
      </Column>
    </DataTable>

    <p v-if="preparedLengthStats.count > 0" class="ps-length-summary">
      Tagged lengths ({{ preparedLengthStats.unit }}):
      <strong>min</strong> {{ preparedLengthStats.min }},
      <strong>max</strong> {{ preparedLengthStats.max }}
      <span class="ps-length-n">({{ preparedLengthStats.count }} sequence(s))</span>
      <template
        v-if="
          seqPrep.dnaMode &&
          seqPrep.optimizationEverSucceeded &&
          !seqPrep.optimizationStale
        "
      >
        <span class="ps-length-codon-meta">
          Codon optimized for {{ seqPrep.activeCodonTable.label }}, with
          {{ enabledOptimizationConstraintCount }} additional DNA optimization constraints.
        </span>
      </template>
    </p>
    <p v-else class="ps-length-summary ps-length-summary--empty">No sequences in scope.</p>

    <Message
      v-if="seqPrep.validationErrors.length > 0"
      severity="error"
      class="ps-validation-msg"
      :closable="false"
    >
      <ul class="ps-validation-list">
        <li v-for="(err, i) in seqPrep.validationErrors" :key="i">{{ err }}</li>
      </ul>
    </Message>

    <Message
      v-if="rowsWithWarnings.length > 0"
      severity="warn"
      class="ps-warnings-banner"
      :closable="false"
    >
      <div class="ps-warnings-banner-inner">
        <i class="pi pi-exclamation-triangle ps-warn-banner-icon" aria-hidden="true" />
        <div class="ps-warnings-banner-body">
          <p class="ps-warnings-banner-lead">
            <strong>Warning:</strong> Some designs are less than ideal.
          </p>
          <ul class="ps-warnings-summary-list">
            <li v-for="(line, i) in warningsSummaryLines" :key="i">{{ line }}</li>
          </ul>
          <div class="ps-warnings-ack">
            <Checkbox v-model="warningsAcknowledged" input-id="ps-warn-ack" binary />
            <label for="ps-warn-ack">Acknowledged, continue anyway</label>
          </div>
        </div>
      </div>
    </Message>

    <Message
      v-if="rowsWithInvalidTagEnd.length > 0"
      severity="warn"
      class="ps-warnings-banner"
      :closable="false"
    >
      <div class="ps-warnings-banner-inner">
        <i class="pi pi-exclamation-triangle ps-warn-banner-icon" aria-hidden="true" />
        <div class="ps-warnings-banner-body">
          <p class="ps-warnings-banner-lead">
            <strong>Warning:</strong> Some designs have no value in the <strong>Tag End</strong> column.
            Terminii-specific tags will only be applied to sequences where the tag column is <code>N</code> or <code>C</code>.
          </p>
          <p v-if="invalidTagDesignSummary" class="ps-invalid-tag-summary">{{ invalidTagDesignSummary }}</p>
          <div class="ps-warnings-ack">
            <Checkbox v-model="tagColumnAcknowledged" input-id="ps-tag-col-ack" binary />
            <label for="ps-tag-col-ack">Acknowledged, continue anyway</label>
          </div>
        </div>
      </div>
    </Message>

    <Message
      v-if="dnaWarningActive"
      severity="warn"
      class="ps-warnings-banner"
      :closable="false"
    >
      <div class="ps-warnings-banner-inner">
        <i class="pi pi-exclamation-triangle ps-warn-banner-icon" aria-hidden="true" />
        <div class="ps-warnings-banner-body">
          <p class="ps-warnings-banner-lead">
            <strong>Warning:</strong> DNA has not been optimized with current settings.
          </p>
          <div class="ps-warnings-ack">
            <Checkbox v-model="dnaStalenessAcknowledged" input-id="ps-dna-stale-ack" binary />
            <label for="ps-dna-stale-ack">Acknowledged, continue anyway</label>
          </div>
        </div>
      </div>
    </Message>

    <div class="ps-download">
      <SplitButton
        label="Download Design Bundle (zip)"
        icon="pi pi-box"
        severity="secondary"
        :disabled="!downloadAllowed"
        :loading="bundleDownloading"
        @click="downloadBundle"
        :model="downloadMenuItems"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useToast } from 'primevue/usetoast'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import SplitButton from 'primevue/splitbutton'
import Checkbox from 'primevue/checkbox'
import InputText from 'primevue/inputtext'
import InputGroup from 'primevue/inputgroup'
import InputGroupAddon from 'primevue/inputgroupaddon'
import InputNumber from 'primevue/inputnumber'
import ToggleSwitch from 'primevue/toggleswitch'
import Select from 'primevue/select'
import MultiSelect from 'primevue/multiselect'
import Chip from 'primevue/chip'
import Message from 'primevue/message'
import TogglePanel from './TogglePanel.vue'
import {
  preparedExportBasename,
  tagPresetChipCssVars,
  tagPresetChromeStyle,
  tagSequenceDisplay,
  useSeqPrepStore,
  OPTIMIZATION_CONSTRAINT_TYPES,
  type PreparedRow,
  WARNING_LONG_NAME_NOT_UNIQUE,
  WARNING_SHORT_NAME_NOT_UNIQUE
} from '../stores/seqPrep'
import type { ShortNameStrategy } from '../stores/shortName'
import { useDesignsStore } from '../stores/designs'
import { bundlesApi } from '../webapi'
import { buildPreparedRows, buildPrepareState } from '../session/prepareState'
import { buildSessionState } from '../session/sessionState'
import {
  RESTRICTION_ENZYMES,
  type RestrictionEnzyme
} from '../utils/restrictionEnzymes'

const seqPrep = useSeqPrepStore()
const toast = useToast()

const shortNamePanelCollapsed = ref(true)
const optimizationPanelCollapsed = ref(true)

// Display text is kept separately from `params`. The field used to bind
// `:value="JSON.stringify(params)"` and only commit on blur, so any parent
// re-render (these constraints are deep-watched) wrote the last saved JSON
// back over in-progress edits.
const constraintParamsDrafts = ref<string[]>([])

function constraintParamsText(index: number, data: { params?: unknown }): string {
  const draft = constraintParamsDrafts.value[index]
  if (draft !== undefined) return draft
  return JSON.stringify(data.params ?? {})
}

function setConstraintParamsDraft(index: number, text: string) {
  const next = constraintParamsDrafts.value.slice()
  next[index] = text
  constraintParamsDrafts.value = next
}

function onConstraintParamsInput(index: number, data: { params?: unknown }, value: string) {
  setConstraintParamsDraft(index, value)
  try {
    const parsed = JSON.parse(value)
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
      data.params = parsed
    }
  } catch {
    // Incomplete JSON while typing; the draft stays until it parses.
  }
}

watch(
  () => seqPrep.optimizationConstraints,
  (rows) => {
    constraintParamsDrafts.value = rows.map((row: { params?: unknown }) =>
      JSON.stringify(row.params ?? {})
    )
  }
)

function onRemoveConstraint(index: number) {
  seqPrep.removeConstraint(index)
  const next = constraintParamsDrafts.value.slice()
  next.splice(index, 1)
  constraintParamsDrafts.value = next
}

const constraintTypeOptions = [...OPTIMIZATION_CONSTRAINT_TYPES]

interface RestrictionEnzymeOptionGroup {
  label: RestrictionEnzyme['category']
  items: Array<{ label: string; value: string; site: string }>
}

const restrictionEnzymeOptions = computed<RestrictionEnzymeOptionGroup[]>(() => {
  const groups = new Map<RestrictionEnzyme['category'], RestrictionEnzymeOptionGroup>()
  for (const e of RESTRICTION_ENZYMES) {
    if (!groups.has(e.category)) {
      groups.set(e.category, { label: e.category, items: [] })
    }
    groups.get(e.category)!.items.push({
      label: `${e.name} — ${e.site}`,
      value: e.name,
      site: e.site
    })
  }
  return [...groups.values()]
})

/** Reset params to a sensible default whenever the constraint type changes. */
function onConstraintTypeChange(data: any, newType: string, index: number) {
  if (data.type === newType) return
  data.type = newType
  switch (newType) {
    case 'EnforceGCContent':
      data.params = { mini: 0.25, maxi: 0.7 }
      break
    case 'AvoidHairpins':
      data.params = { stem_size: 20, hairpin_window: 48 }
      break
    case 'AvoidPattern':
      data.params = { pattern: '' }
      break
    case 'ExcludeRestrictionSite':
      data.params = { enzyme: 'BsaI' }
      break
    case 'AvoidRareCodons':
      data.params = { min_frequency: 0.09 }
      break
    case 'UniquifyAllKmers':
      data.params = { k: 12 }
      break
    default:
      data.params = {}
  }
  setConstraintParamsDraft(index, JSON.stringify(data.params ?? {}))
}

const chainOptions = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']

const shortNameStrategyOptions: Array<{ label: string; value: ShortNameStrategy['kind'] }> = [
  { label: 'None (sanitised design_id)', value: 'none' },
  { label: 'Regex replace', value: 'regex' },
  { label: 'Split + take indices (1-based)', value: 'splitTake' },
  { label: 'Prefix + sorted DNA-set uid + index', value: 'pattern' },
  { label: 'Smart: stem + hash', value: 'smartStemHash' },
  { label: 'Smart: Regex drop prefix / suffix', value: 'smartRegexStrip' }
]

const columnOptions: Array<{ key: string; label: string }> = [
  { key: 'design', label: 'Design' },
  { key: 'sequence', label: 'Sequence' },
  { key: 'tag', label: 'Tag End' },
  { key: 'length', label: 'Length' },
  { key: 'warnings', label: 'Warnings' },
  { key: 'extinction', label: 'ε₂₈₀' },
  { key: 'pi', label: 'pI' },
]

const selectedColumnKeys = ref<string[]>(
  columnOptions
    .map((o) => o.key)
    .filter((key) => key !== 'extinction' && key !== 'pi')
)

const shortNamePreviewLines = computed(() => {
  const rows = seqPrep.preparedRows.slice(0, 3)
  return rows.map((r) => `${r.design_id} → ${r.short_name}`)
})

function onClearShortNames() {
  void (async () => {
    await seqPrep.clearShortNames()
    toast.add({ severity: 'success', summary: 'Short names cleared', detail: 'Persisted null short_name for rows in scope.', life: 3000 })
  })()
}

const lengthColumnHeader = computed(() =>
  seqPrep.dnaMode ? 'Length (nt)' : 'Length (aa)'
)

type PreparedRowWithSort = PreparedRow & {
  sort_tagged_length: number
  sort_warnings: string
  sort_extinction_coeff_reduced: number
}

const preparedRowsForTable = computed<PreparedRowWithSort[]>(() =>
  seqPrep.preparedRows.map((row) => ({
    ...row,
    sort_tagged_length: taggedLength(row),
    sort_warnings: row.warnings.join(', '),
    sort_extinction_coeff_reduced: row.extinction_coeff_reduced
  }))
)

const tableFilters = ref({
  design_filter_text: { value: null as string | null, matchMode: 'contains' as const },
  tag: { value: null as string | null, matchMode: 'contains' as const }
})

const warningsAcknowledged = ref(false)
const tagColumnAcknowledged = ref(false)

const NAME_UNIQUENESS_WARNINGS = new Set([
  WARNING_LONG_NAME_NOT_UNIQUE,
  WARNING_SHORT_NAME_NOT_UNIQUE
])

const shortNameUniquenessWarning = computed(() =>
  seqPrep.preparedRows.some((r) => r.warnings.some((w) => NAME_UNIQUENESS_WARNINGS.has(w)))
)

const preparedRowsFingerprint = computed(() =>
  seqPrep.preparedRows
    .map((r) => {
      const nameWarnings = r.warnings.filter((w) => NAME_UNIQUENESS_WARNINGS.has(w)).join(',')
      return `${r.row_key}:${r.prepared_aa}:${r.tag}:${nameWarnings}`
    })
    .join('|')
)

watch(preparedRowsFingerprint, () => {
  warningsAcknowledged.value = false
  tagColumnAcknowledged.value = false
})

const dnaStalenessAcknowledged = ref(false)

watch(
  () =>
    [seqPrep.dnaMode, seqPrep.optimizationStale, seqPrep.optimizationEverSucceeded] as const,
  () => {
    dnaStalenessAcknowledged.value = false
  }
)

const rowsWithWarnings = computed(() => seqPrep.preparedRows.filter((r) => r.warnings.length > 0))

const rowsWithInvalidTagEnd = computed(() =>
  seqPrep.preparedRows.filter((r) => r.tag !== 'N' && r.tag !== 'C')
)

const invalidTagDesignSummary = computed(() => {
  const rows = rowsWithInvalidTagEnd.value
  if (rows.length === 0) return ''
  const ids = rows.map((r) => r.design_id)
  const maxShow = 5
  const shown = ids.slice(0, maxShow)
  const more = ids.length > maxShow ? ` … (${ids.length} total)` : ''
  return `Affected design_id: ${shown.join(', ')}${more}.`
})

const enabledOptimizationConstraintCount = computed(
  () => seqPrep.optimizationConstraints.filter((c) => c.enabled).length
)

/** Shown until a successful Optimize DNA run; also while results are stale (matches panel "Inputs changed"). */
const dnaWarningActive = computed(
  () => !seqPrep.optimizationEverSucceeded || seqPrep.optimizationStale
)

const warningsSummaryLines = computed(() => {
  const map = new Map<string, string[]>()
  for (const r of rowsWithWarnings.value) {
    for (const w of r.warnings) {
      if (!map.has(w)) map.set(w, [])
      map.get(w)!.push(r.design_id)
    }
  }
  const lines: string[] = []
  const maxShow = 5
  for (const [warn, ids] of map) {
    const uniq = [...new Set(ids)]
    const shown = uniq.slice(0, maxShow)
    const more = uniq.length > maxShow ? ' …' : ''
    lines.push(`Designs ${shown.join(', ')}${more}: ${warn}`)
  }
  return lines
})

const downloadAllowed = computed(() => {
  if (!seqPrep.canDownload) return false
  if (rowsWithWarnings.value.length > 0 && !warningsAcknowledged.value) return false
  if (rowsWithInvalidTagEnd.value.length > 0 && !tagColumnAcknowledged.value) return false
  if (dnaWarningActive.value && !dnaStalenessAcknowledged.value) return false
  return true
})

onMounted(() => {
  void seqPrep.ensureCodonTablesLoaded()
})

const inputSummary = computed(() => {
  const n = seqPrep.inputDesigns.length
  if (n === 0) return 'No designs in scope (select rows on Designs or use Good only).'
  return `${n} design(s)`
})

function aaSegmentsForView(data: PreparedRow): PreparedRow['segments_aa_display'] {
  return seqPrep.showPostStopPadding ? data.segments_aa : data.segments_aa_display
}

function aaSequenceForExport(r: PreparedRow): string {
  if (seqPrep.dnaMode && r.prepared_dna) return r.prepared_dna
  if (!seqPrep.dnaMode) return seqPrep.showPostStopPadding ? r.prepared_aa : r.prepared_aa_display
  return r.prepared_aa
}

function taggedLength(data: PreparedRow): number {
  if (seqPrep.dnaMode) return (data.prepared_dna ?? '').length
  return seqPrep.showPostStopPadding ? data.prepared_aa.length : data.prepared_aa_display.length
}

function formatPi(v: number): string {
  if (!Number.isFinite(v)) return '—'
  return v.toFixed(2)
}

function exportPiRaw(v: number): string {
  if (!Number.isFinite(v)) return ''
  return String(v)
}

const preparedLengthStats = computed(() => {
  const rows = seqPrep.preparedRows
  const dna = seqPrep.dnaMode
  const unit = dna ? 'nt' : 'aa'
  if (rows.length === 0) {
    return { count: 0, min: 0, max: 0, unit }
  }
  const lens = rows.map((r) =>
    dna ? (r.prepared_dna ?? '').length : (seqPrep.showPostStopPadding ? r.prepared_aa.length : r.prepared_aa_display.length)
  )
  return {
    count: rows.length,
    min: Math.min(...lens),
    max: Math.max(...lens),
    unit
  }
})

function addCustomBoth() {
  seqPrep.addCustomTag('n')
}

function onExtractMissing() {
  void (async () => {
    const { ok, errors } = await seqPrep.fetchMissingSequences()
    if (ok > 0) {
      toast.add({
        severity: 'success',
        summary: 'Sequences extracted',
        detail: `Updated ${ok} design(s).`,
        life: 4000
      })
    }
    if (errors.length > 0) {
      toast.add({
        severity: 'warn',
        summary: 'Some rows skipped',
        detail: errors.slice(0, 5).join('; ') + (errors.length > 5 ? '…' : ''),
        life: 6000
      })
    }
    if (ok === 0 && errors.length === 0) {
      toast.add({
        severity: 'info',
        summary: 'Nothing to extract',
        detail: 'All designs in scope already have a sequence.',
        life: 3000
      })
    }
  })()
}

function downloadBlob(blob: Blob, filename: string) {
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function exportDownloadStem(): string {
  return preparedExportBasename(seqPrep.exportOrderName)
}

function guardDownload(): boolean {
  if (!seqPrep.canDownload) {
    toast.add({
      severity: 'error',
      summary: 'Invalid sequence input',
      detail: seqPrep.validationErrors[0] ?? 'Fix validation errors before downloading.',
      life: 5000
    })
    return false
  }
  if (rowsWithWarnings.value.length > 0 && !warningsAcknowledged.value) {
    toast.add({
      severity: 'warn',
      summary: 'Acknowledge warnings',
      detail: 'Check the warning box above or adjust sequences before downloading.',
      life: 5000
    })
    return false
  }
  if (rowsWithInvalidTagEnd.value.length > 0 && !tagColumnAcknowledged.value) {
    toast.add({
      severity: 'warn',
      summary: 'Acknowledge tag column',
      detail: 'Set the tag column to N or C where needed, or tick the tag acknowledgement before downloading.',
      life: 5000
    })
    return false
  }
  if (dnaWarningActive.value && !dnaStalenessAcknowledged.value) {
    toast.add({
      severity: 'warn',
      summary: 'Acknowledge DNA not optimised',
      detail: 'Run Optimize DNA or tick the DNA acknowledgement before downloading.',
      life: 5000
    })
    return false
  }
  return true
}

function downloadFasta() {
  if (!guardDownload()) return
  const rows = seqPrep.preparedRows
  if (rows.length === 0) {
    toast.add({ severity: 'warn', summary: 'No data', detail: 'No sequences to export', life: 2500 })
    return
  }
  const lines: string[] = []
  for (const r of rows) {
    const body = aaSequenceForExport(r)
    lines.push(`>${r.design_id}`)
    lines.push(body)
  }
  downloadBlob(new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' }), `${exportDownloadStem()}.fasta`)
  toast.add({ severity: 'success', summary: 'FASTA', detail: `${rows.length} record(s)`, life: 2500 })
}

function toTsv(): void {
  if (!guardDownload()) return
  const rows = seqPrep.preparedRows
  if (rows.length === 0) return
  const dna = seqPrep.dnaMode
  const cols = dna
    ? [
        'design_id',
        'project_id',
        'run_name',
        'tag',
        'original_sequence',
        'prepared_aa',
        'prepared_dna',
        'dna_length',
        'extinction_coeff_reduced',
        'extinction_coeff_oxidized',
        'isoelectric_point',
        'warnings',
        'short_name'
      ]
    : [
        'design_id',
        'project_id',
        'run_name',
        'tag',
        'original_sequence',
        'prepared_sequence',
        'length',
        'extinction_coeff_reduced',
        'extinction_coeff_oxidized',
        'isoelectric_point',
        'warnings',
        'short_name'
      ]
  const esc = (v: string | number) => {
    const s = String(v ?? '')
    if (s.includes('\t') || s.includes('\n') || s.includes('"')) return `"${s.replace(/"/g, '""')}"`
    return s
  }
  const lines = [cols.join('\t')]
  for (const r of rows) {
    if (dna) {
      lines.push(
        [
          esc(r.design_id),
          esc(r.project_id),
          esc(r.run_name),
          esc(r.tag),
          esc(r.original_sequence),
          esc(r.prepared_aa),
          esc(r.prepared_dna || ''),
          esc((r.prepared_dna || '').length),
          esc(r.extinction_coeff_reduced),
          esc(r.extinction_coeff_oxidized),
          esc(exportPiRaw(r.isoelectric_point)),
          esc(r.warnings.join('; ')),
          esc(r.short_name)
        ].join('\t')
      )
    } else {
      const aa = aaSequenceForExport(r)
      lines.push(
        [
          esc(r.design_id),
          esc(r.project_id),
          esc(r.run_name),
          esc(r.tag),
          esc(r.original_sequence),
          esc(aa),
          esc(aa.length),
          esc(r.extinction_coeff_reduced),
          esc(r.extinction_coeff_oxidized),
          esc(exportPiRaw(r.isoelectric_point)),
          esc(r.warnings.join('; ')),
          esc(r.short_name)
        ].join('\t')
      )
    }
  }
  downloadBlob(
    new Blob([lines.join('\n')], { type: 'text/tab-separated-values;charset=utf-8' }),
    `${exportDownloadStem()}.tsv`
  )
  toast.add({ severity: 'success', summary: 'TSV', detail: `${rows.length} row(s)`, life: 2500 })
}

function toCsv(): void {
  if (!guardDownload()) return
  const rows = seqPrep.preparedRows
  if (rows.length === 0) return
  const dna = seqPrep.dnaMode
  const cols = dna
    ? [
        'design_id',
        'project_id',
        'run_name',
        'tag',
        'original_sequence',
        'prepared_aa',
        'prepared_dna',
        'dna_length',
        'extinction_coeff_reduced',
        'extinction_coeff_oxidized',
        'isoelectric_point',
        'warnings',
        'short_name'
      ]
    : [
        'design_id',
        'project_id',
        'run_name',
        'tag',
        'original_sequence',
        'prepared_sequence',
        'length',
        'extinction_coeff_reduced',
        'extinction_coeff_oxidized',
        'isoelectric_point',
        'warnings',
        'short_name'
      ]
  const esc = (v: string | number) => {
    const s = String(v ?? '')
    if (s.includes(',') || s.includes('\n') || s.includes('"')) return `"${s.replace(/"/g, '""')}"`
    return s
  }
  const lines = [cols.join(',')]
  for (const r of rows) {
    if (dna) {
      lines.push(
        [
          esc(r.design_id),
          esc(r.project_id),
          esc(r.run_name),
          esc(r.tag),
          esc(r.original_sequence),
          esc(r.prepared_aa),
          esc(r.prepared_dna || ''),
          esc((r.prepared_dna || '').length),
          esc(r.extinction_coeff_reduced),
          esc(r.extinction_coeff_oxidized),
          esc(exportPiRaw(r.isoelectric_point)),
          esc(r.warnings.join('; ')),
          esc(r.short_name)
        ].join(',')
      )
    } else {
      const aa = aaSequenceForExport(r)
      lines.push(
        [
          esc(r.design_id),
          esc(r.project_id),
          esc(r.run_name),
          esc(r.tag),
          esc(r.original_sequence),
          esc(aa),
          esc(aa.length),
          esc(r.extinction_coeff_reduced),
          esc(r.extinction_coeff_oxidized),
          esc(exportPiRaw(r.isoelectric_point)),
          esc(r.warnings.join('; ')),
          esc(r.short_name)
        ].join(',')
      )
    }
  }
  downloadBlob(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }), `${exportDownloadStem()}.csv`)
  toast.add({ severity: 'success', summary: 'CSV', detail: `${rows.length} row(s)`, life: 2500 })
}

function toCsvTwist(): void {
  if (!guardDownload()) return
  const rows = seqPrep.preparedRows
  if (rows.length === 0) {
    toast.add({ severity: 'warn', summary: 'No data', detail: 'No sequences to export', life: 2500 })
    return
  }
  const cols = ['name', 'sequence', 'original_name'] as const
  const esc = (v: string | number) => {
    const s = String(v ?? '')
    if (s.includes(',') || s.includes('\n') || s.includes('"')) return `"${s.replace(/"/g, '""')}"`
    return s
  }
  const lines = [cols.join(',')]
  for (const r of rows) {
    const sequence = aaSequenceForExport(r)
    lines.push([esc(r.short_name), esc(sequence), esc(r.design_id)].join(','))
  }
  downloadBlob(
    new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }),
    `${exportDownloadStem()}_twist.csv`
  )
  toast.add({ severity: 'success', summary: 'Twist CSV', detail: `${rows.length} row(s)`, life: 2500 })
}

const bundleDownloading = ref(false)

/**
 * The superset bundle: everything the Designs bundle carries, plus the construct
 * sequences and the settings that produced them.
 */
async function downloadBundle(): Promise<void> {
  if (!guardDownload()) return
  const rows = seqPrep.preparedRows
  if (rows.length === 0) {
    toast.add({ severity: 'warn', summary: 'No data', detail: 'No sequences to export', life: 2500 })
    return
  }

  bundleDownloading.value = true
  try {
    const designsStore = useDesignsStore()
    const keys = rows.map((r: PreparedRow) => ({
      run_id: String(r.run_id),
      design_id: String(r.design_id),
      source_path: r.source_path ?? ''
    }))
    const blob = await bundlesApi.downloadPrepareBundle({
      keys,
      run_ids: Array.from(new Set(keys.map((k) => k.run_id))),
      label: exportDownloadStem(),
      session: buildSessionState(),
      prepared: { ...buildPrepareState(), rows: buildPreparedRows() }
    })
    downloadBlob(blob, `${exportDownloadStem()}.zip`)
    toast.add({
      severity: 'success',
      summary: 'Design bundle',
      detail: `${rows.length} construct(s) with sequences, structures and settings`,
      life: 3000
    })
  } catch (err: any) {
    console.error('Error downloading prepare-sequences bundle:', err)
    toast.add({
      severity: 'error',
      summary: 'Download Failed',
      detail: err?.message || 'Failed to build the design bundle',
      life: 5000
    })
  } finally {
    bundleDownloading.value = false
  }
}

const downloadMenuItems = [
  { label: 'Download CSV (Twist-ready)', icon: 'pi pi-download', command: () => toCsvTwist() },
  { label: 'Download FASTA', icon: 'pi pi-download', command: () => downloadFasta() },
  { label: 'Download TSV', icon: 'pi pi-download', command: () => toTsv() },
  { label: 'Download CSV', icon: 'pi pi-download', command: () => toCsv() }
]
</script>

<style scoped>
.prepare-sequences-view {
  max-width: 100%;
}

.ps-header h2 {
  margin-top: 0;
}

.ps-intro-box {
  max-width: 52rem;
  margin-bottom: 1.25rem;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--p-content-border-color, #d7dde3);
  border-radius: 6px;
  background: var(--p-content-background, #fff);
}

.ps-intro {
  font-size: 0.9rem;
  line-height: 1.5;
  margin: 0 0 0.5rem 0;
}

.ps-case-help {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.45;
}

.ps-intro-box strong {
  font-weight: 700;
}

.ps-order-name {
  max-width: 32rem;
  margin-bottom: 1rem;
}

.ps-order-name label {
  display: block;
  font-size: 0.85rem;
  font-weight: 500;
  margin-bottom: 0.25rem;
}

.card-like {
  border: 1px solid var(--p-content-border-color, #dee2e6);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
  background: var(--p-content-background, #fff);
}

.ps-short-name-lead {
  margin: 0 0 0.75rem 0;
  font-size: 0.9rem;
  line-height: 1.45;
}

.ps-short-name-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  gap: 0.75rem 1rem;
}

.ps-field-span-2 {
  grid-column: 1 / -1;
}

.ps-short-name-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.ps-short-name-panel.ps-short-name-panel--warn.card-like {
  border-color: #dc2626;
}

.ps-short-name-footer {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.ps-sn-dedupe {
  width: 100%;
  margin: 0;
}

.ps-sn-dedupe .ps-warn-banner-icon {
  font-size: 1.15rem;
}

.ps-sn-preview {
  margin-top: 0.75rem;
  font-size: 0.85rem;
}

.ps-sn-preview-list {
  margin: 0.25rem 0 0 1.1rem;
  padding: 0;
}

.ps-design-cell .ps-short-name-code {
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
}

.ps-short-name-code {
  font-family: inherit;
  font-size: inherit;
}

.ps-optimization-toolbar.card-like {
  margin-bottom: 0.75rem;
}

.ps-opt-header {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  justify-content: space-between;
  align-items: flex-end;
}

.ps-codon-label {
  display: block;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.ps-opt-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.ps-opt-panel-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.ps-opt-table-footer-actions {
  display: flex;
  justify-content: center;
  margin-top: 1rem;
  padding-top: 0.5rem;
}

.ps-builder-row {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.ps-zone {
  flex: 1;
  min-width: 12rem;
  border: 1px dashed var(--p-content-border-color, #ced4da);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
}

.ps-zone-label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 0.35rem;
  color: var(--p-text-muted-color, #6c757d);
}

.ps-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
  min-height: 2rem;
}

.ps-placeholder {
  font-size: 0.85rem;
  color: var(--p-text-muted-color, #adb5bd);
}

.ps-binder-label {
  align-self: center;
  font-weight: 600;
  color: var(--p-primary-color, #667eea);
  padding: 0 0.25rem;
}

.ps-palette {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  margin-bottom: 0.75rem;
}

.ps-palette-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
}

.ps-palette-label {
  font-size: 0.85rem;
  font-weight: 500;
}

.ps-preset-btn {
  margin-right: 0.15rem;
}

/* Palette buttons + chips: colours from `TAG_PRESET_DEFS` in seqPrep store.
   Chips need !important + CSS vars so they beat global App.vue `.p-chip` / `.p-component *` rules. */

.prepare-sequences-view :deep(.ps-tag-chip.p-chip) {
  font-size: var(--p-button-sm-font-size, 0.875rem);
  border-color: var(--ps-chip-border) !important;
  border-width: 1px !important;
  border-style: solid !important;
  background-color: var(--ps-chip-bg) !important;
  color: var(--ps-chip-fg) !important;
}

.prepare-sequences-view :deep(.ps-tag-chip.p-chip .p-chip-label) {
  color: var(--ps-chip-fg) !important;
}

.ps-tag-chip-body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15em;
  line-height: 1.25;
  text-align: left;
  min-width: 0;
}

.ps-tag-chip-name {
  font-weight: 600;
}

.ps-tag-chip-seq {
  font-size: 0.72em;
  font-weight: 500;
  letter-spacing: 0.02em;
  word-break: break-all;
}

.prepare-sequences-view :deep(.ps-tag-chip .p-chip-remove-icon) {
  color: var(--ps-chip-fg) !important;
  opacity: 0.75;
}

.prepare-sequences-view :deep(.ps-tag-chip .p-chip-remove-icon:hover) {
  opacity: 1;
}

.ps-custom-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.ps-custom-input {
  flex: 1;
  min-width: 12rem;
}

.ps-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  gap: 1rem;
}

.ps-form.card-like {
  margin-top: 0.75rem;
  margin-bottom: 1rem;
}

.ps-field-row {
  display: grid;
  gap: 1rem;
}

.ps-field-row--padding {
  grid-column: 1 / -1;
  grid-template-columns: repeat(2, minmax(14rem, 1fr));
  gap: 0.5rem;
  width: 100%;
  max-width: 100%;
  justify-self: stretch;
  padding: 0.75rem;
  border: 1px solid var(--p-content-border-color, #dee2e6);
  border-radius: 6px;
  background: color-mix(in srgb, var(--p-content-background, #fff) 88%, #eef3ff 12%);
}

.ps-field-row--padding .ps-field-span-2 {
  grid-column: 1 / -1;
}

.ps-field-row--padding > .ps-field {
  margin: 0;
}

.ps-field-row--padding > .ps-field:first-child {
  margin-left: 0;
  padding-left: 0;
}

.ps-length-summary {
  margin: 0.75rem 0 0;
  font-size: 0.9rem;
  color: var(--p-text-color);
}

.ps-length-summary--empty {
  color: var(--p-text-muted-color, #6c757d);
}

.ps-length-summary .ps-length-n {
  color: var(--p-text-muted-color, #6c757d);
  font-size: 0.85rem;
}

.ps-length-summary .ps-length-codon-meta {
  display: block;
  margin-top: 0.35rem;
  color: var(--p-text-muted-color, #6c757d);
  font-size: 0.85rem;
}

.ps-field label {
  display: block;
  font-size: 0.85rem;
  margin-bottom: 0.25rem;
}

.ps-checks {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding-top: 1.4rem;
}

.ps-checks--stops {
  flex-direction: column;
  align-items: flex-start;
  gap: 0.4rem;
}

.ps-stop-check {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.ps-checks label {
  margin-bottom: 0;
}

.ps-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}

.ps-hint {
  font-size: 0.9rem;
  color: var(--p-text-muted-color, #6c757d);
}

.ps-download {
  margin-top: 1rem;
}

.ps-design-meta {
  display: block;
  font-size: 0.85rem;
  line-height: 1.45;
  word-break: break-word;
}

.prepare-sequences-view :deep(.p-datatable-tbody > tr > td .ps-design-meta-label) {
  font-weight: 600;
  color: var(--p-text-color);
  margin-right: 0.2em;
}

.seq-wrap {
  display: block;
  font-family: ui-monospace, monospace;
  font-size: 0.8rem;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: 1.4;
}

.prepare-sequences-view :deep(.ps-sequence-cell) {
  white-space: normal;
  vertical-align: top;
}

:deep(.seq-seg-core) {
  color: #212529;
}

/* Preset tag segments: inline :style from store (same JSON as chips). */

.prepare-sequences-view :deep(.ps-terminal-input--n.p-inputtext) {
  border-left: 3px solid #00897b;
  background: rgba(0, 137, 123, 0.06);
}

.prepare-sequences-view :deep(.ps-terminal-input--c.p-inputtext) {
  border-left: 3px solid #c2185b;
  background: rgba(194, 24, 91, 0.06);
}

:deep(.seq-seg-stop) {
  display: inline-block;
  padding: 0.04em 0.2em;
  border-radius: 3px;
  border: 1px solid #b23a3a;
  background: #d66868;
  color: #ffffff !important;
  font-weight: 700;
}

:deep(.seq-seg-fixed) {
  font-weight: 700;
  text-decoration-line: underline;
  text-decoration-style: double;
  text-decoration-thickness: from-font;
  text-underline-offset: 0.22em;
}

:deep(.seq-seg-nuc-remainder) {
  color: #6a1b9a;
  font-style: italic;
  text-decoration: underline;
  text-decoration-color: #ce93d8;
  font-size: 0.75em;
}

.ps-view-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 1.25rem;
  margin-bottom: 0.75rem;
}

.ps-view-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
}

.ps-toggle-active {
  font-weight: 700;
  color: var(--p-primary-color);
}

.ps-codon-field {
  min-width: 12rem;
}

.ps-codon-field label {
  display: block;
  font-size: 0.85rem;
  margin-bottom: 0.25rem;
}

.ps-table-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1rem;
  margin-bottom: 0.5rem;
}

.ps-column-toggle-label {
  font-size: 0.85rem;
  font-weight: 500;
}

.ps-column-multiselect {
  min-width: 14rem;
  max-width: min(100%, 36rem);
}

.prepare-sequences-view :deep(.ps-tag-filter-input-group .p-inputtext) {
  width: 7ch;
  min-width: 7ch;
  flex: 0 0 auto;
}

.ps-col-filter-input {
  flex: 1;
  min-width: 0;
}

.ps-warn-icon {
  color: #f59e0b;
  font-size: 2rem;
  margin-right: 0.35rem;
  flex-shrink: 0;
}

.ps-warn-cell {
  display: inline-flex;
  align-items: flex-start;
  gap: 0;
  padding: 0.25rem 0.4rem;
  border-radius: 4px;
  background: var(--p-message-warn-background, #fff3cd);
  border: 1px solid var(--p-message-warn-border-color, #ffeaa7);
  font-size: 0.8rem;
  line-height: 1.35;
}

.ps-warn-text {
  color: var(--p-text-color);
}

.ps-ext-stack {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  font-size: 0.85rem;
  line-height: 1.25;
}

.ps-ext-main {
  font-variant-numeric: tabular-nums;
}

.ps-ext-ox {
  font-size: 0.72rem;
  color: var(--p-text-muted-color, #6c757d);
}

.ps-warnings-banner {
  margin: 0.75rem 0;
  font-size: 0.9rem;
}

.ps-warnings-banner-inner {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
}

.ps-warn-banner-icon {
  color: #f59e0b;
  font-size: 1.15rem;
  margin-top: 0.1rem;
  flex-shrink: 0;
  font-size: 2rem;
}

.ps-warnings-banner-body {
  flex: 1;
  min-width: 0;
}

.ps-warnings-banner-lead {
  margin: 0 0 0.35rem 0;
}

.ps-invalid-tag-summary {
  margin: 0 0 0.5rem 0;
  font-size: 0.85rem;
  color: var(--p-text-muted-color, #6c757d);
}

.ps-warnings-summary-list {
  margin: 0 0 0.6rem 0;
  padding-left: 1.25rem;
}

.ps-warnings-ack {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.ps-warnings-ack label {
  margin: 0;
  font-size: 0.88rem;
  cursor: pointer;
}

.ps-validation-msg {
  margin: 0.75rem 0;
}

.ps-validation-list {
  margin: 0.25rem 0 0;
  padding-left: 1.25rem;
}

:deep(.seq-seg-padding) {
  color: #78909c;
  background: rgba(120, 144, 156, 0.12);
  border-radius: 2px;
  font-style: italic;
}

:deep(.seq-seg-dna-body) {
  color: #1565c0;
}

.ps-restriction-group-label {
  font-weight: 700;
  color: var(--p-text-color);
}
</style>
