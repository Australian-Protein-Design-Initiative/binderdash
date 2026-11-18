<script setup lang="ts">
import { computed } from 'vue'
import Select from 'primevue/select'
import type { ColumnInfoDto } from '../webapi'
import { columnDisplayName } from '../utils/filterLabel'

const props = withDefaults(
  defineProps<{
    modelValue: string | null
    columns: ColumnInfoDto[]
    placeholder?: string
    disabled?: boolean
    inputId?: string
    /** Highlights the select with PrimeVue's invalid (red-border) styling — used to flag
     * a configured column that doesn't resolve to any data for the current run scope. */
    invalid?: boolean
  }>(),
  {
    placeholder: 'Select a column…',
    disabled: false,
    inputId: undefined,
    invalid: false
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
}>()

interface ColumnOption {
  name: string
  label: string
}

const options = computed<ColumnOption[]>(() =>
  [...props.columns]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((col) => ({
      name: col.name,
      label: (() => {
        const name = columnDisplayName(col.name)
        return col.canonical_name && col.canonical_name !== col.name
          ? `${name}  (${col.canonical_name})`
          : name
      })()
    }))
)

const value = computed<string | null>({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v)
})

const selectedColumnInfo = computed<ColumnInfoDto | undefined>(() =>
  props.columns.find((c) => c.name === props.modelValue)
)

const equivalentColumnsText = computed<string | null>(() => {
  const raw = selectedColumnInfo.value?.raw_columns
  if (!raw || Object.keys(raw).length === 0) return null
  return Object.entries(raw)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([method, col]) => `${method}: ${col}`)
    .join(' · ')
})
</script>

<template>
  <div class="metric-column-selector">
    <Select
      :id="inputId"
      v-model="value"
      :options="options"
      option-label="label"
      option-value="name"
      filter
      filter-placeholder="Search columns…"
      :placeholder="placeholder"
      :disabled="disabled"
      :invalid="invalid"
      show-clear
      class="metric-column-selector__select"
    />
    <span v-if="equivalentColumnsText" class="metric-column-selector__hint">
      resolves to: {{ equivalentColumnsText }}
    </span>
    <span
      v-if="selectedColumnInfo?.sample_values"
      class="metric-column-selector__hint"
      :title="`Present in: ${selectedColumnInfo.present_in_runs.join(', ') || 'unknown'}`"
    >
      min {{ selectedColumnInfo.sample_values.min.toFixed(3) }} · max
      {{ selectedColumnInfo.sample_values.max.toFixed(3) }} · mean
      {{ selectedColumnInfo.sample_values.mean.toFixed(3) }} · median
      {{ selectedColumnInfo.sample_values.median.toFixed(3) }}
    </span>
  </div>
</template>

<style scoped>
.metric-column-selector {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.metric-column-selector__select {
  width: 100%;
}

.metric-column-selector__hint {
  font-size: 0.75rem;
  color: #6c757d;
}
</style>
