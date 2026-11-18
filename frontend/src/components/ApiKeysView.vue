<template>
  <div class="api-keys-view">
    <Button
      label="Back to Designs"
      icon="pi pi-arrow-left"
      severity="secondary"
      text
      class="api-keys-view__back"
      @click="emit('back')"
    />

    <Panel v-if="issuedKey" header="New API key created" class="api-keys-view__issued">
      <Message severity="warn" :closable="false">
        Copy this key now — it will not be shown again.
      </Message>
      <div class="api-keys-view__secret-row">
        <code class="api-keys-view__secret" ref="secretCodeRef">{{ issuedKey.key }}</code>
        <Button icon="pi pi-copy" label="Copy" size="small" @click="copySecret" />
        <Button icon="pi pi-times" label="Dismiss" size="small" severity="secondary" text @click="issuedKey = null" />
      </div>

      <Button
        :label="curlExpanded ? 'Hide curl example' : 'Show curl example'"
        :icon="curlExpanded ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"
        text
        size="small"
        class="api-keys-view__curl-toggle"
        @click="curlExpanded = !curlExpanded"
      />
      <pre v-if="curlExpanded" class="api-keys-view__curl">{{ curlSnippet }}</pre>

      <template v-if="mcpEnabled">
        <div class="api-keys-view__setup-toggles">
          <Button
            :label="mcpExpanded ? 'Hide AI agent (MCP) setup' : 'Use with Claude Code or another AI agent (MCP)'"
            :icon="mcpExpanded ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"
            text
            size="small"
            class="api-keys-view__curl-toggle"
            @click="mcpExpanded = !mcpExpanded"
          />
          <Button
            :label="claudeScienceExpanded ? 'Hide Claude Science setup' : 'Use Claude Science'"
            :icon="claudeScienceExpanded ? 'pi pi-chevron-up' : 'pi pi-chevron-down'"
            text
            size="small"
            class="api-keys-view__curl-toggle"
            @click="claudeScienceExpanded = !claudeScienceExpanded"
          />
        </div>
        <div v-if="mcpExpanded" class="api-keys-view__mcp">
          <p class="api-keys-view__mcp-intro">
            Binderdash speaks <a href="https://modelcontextprotocol.io" target="_blank" rel="noopener">MCP</a>,
            so an agent can query runs, rank and filter designs, and inspect interfaces directly.
          </p>

          <div class="api-keys-view__mcp-step">
            <h4>Claude Code — one command</h4>
            <p class="api-keys-view__mcp-hint">
              Run this in a terminal. Use <code>--scope project</code> instead to share it with
              collaborators via a <code>.mcp.json</code> in the repo (it would contain your key,
              so only do that for a key you are happy to share).
            </p>
            <div class="api-keys-view__snippet-row">
              <pre class="api-keys-view__curl">{{ mcpCliSnippet }}</pre>
              <Button icon="pi pi-copy" size="small" text v-tooltip.top="'Copy'" @click="copyText(mcpCliSnippet, 'Command copied.')" />
            </div>
          </div>

          <div class="api-keys-view__mcp-step">
            <h4>Or edit the config file directly</h4>
            <p class="api-keys-view__mcp-hint">
              Add to <code>~/.claude.json</code> (all projects) or <code>.mcp.json</code> in a
              project directory. Other MCP clients take the same <code>mcpServers</code> shape;
              see their docs for the file location.
            </p>
            <div class="api-keys-view__snippet-row">
              <pre class="api-keys-view__curl">{{ mcpJsonSnippet }}</pre>
              <Button icon="pi pi-copy" size="small" text v-tooltip.top="'Copy'" @click="copyText(mcpJsonSnippet, 'Config copied.')" />
            </div>
          </div>

          <Message severity="info" :closable="false">
            The key goes in a header, so it is stored in that config file in plain text. Prefer a
            dedicated, expiring key for each agent, and revoke it here when you are done.
          </Message>
        </div>

        <div v-if="claudeScienceExpanded" class="api-keys-view__mcp">
          <p class="api-keys-view__mcp-intro">
            In Claude Science, open <strong>Settings → Connectors → Add Connector</strong> and
            choose <strong>Local URL</strong>. Fill in the name and server address, open
            <strong>Advanced settings</strong>, and paste the command into the header field.
            Leave OAuth Client ID, OAuth Server URL and Scopes empty, and set the type to
            <strong>Streamable HTTP</strong>.
          </p>

          <div class="api-keys-view__mcp-step">
            <h4>Name</h4>
            <div class="api-keys-view__snippet-row">
              <pre class="api-keys-view__curl">{{ mcpServerName }}</pre>
              <Button icon="pi pi-copy" size="small" text v-tooltip.top="'Copy'" @click="copyText(mcpServerName, 'Name copied.')" />
            </div>
          </div>

          <div class="api-keys-view__mcp-step">
            <h4>Server address</h4>
            <div class="api-keys-view__snippet-row">
              <pre class="api-keys-view__curl">{{ mcpUrl }}</pre>
              <Button icon="pi pi-copy" size="small" text v-tooltip.top="'Copy'" @click="copyText(mcpUrl, 'Server address copied.')" />
            </div>
          </div>

          <div class="api-keys-view__mcp-step">
            <h4>Header command</h4>
            <p class="api-keys-view__mcp-hint">
              Claude Science runs this on your machine every time it connects, and adds the JSON
              it prints as request headers. Keep the single quotes so the shell leaves the double
              quotes alone.
            </p>
            <div class="api-keys-view__snippet-row">
              <pre class="api-keys-view__curl">{{ mcpScienceCommand }}</pre>
              <Button icon="pi pi-copy" size="small" text v-tooltip.top="'Copy'" @click="copyText(mcpScienceCommand, 'Command copied.')" />
            </div>
          </div>

          <figure class="api-keys-view__science-figure">
            <img
              class="api-keys-view__science-shot"
              :src="claudeScienceShot"
              width="559"
              height="722"
              alt="Claude Science connector form filled in: name binderdash, the MCP server address, empty OAuth fields, an echo command that prints an Authorization Bearer header, and Streamable HTTP selected."
            />
            <figcaption class="api-keys-view__science-caption">
              The same form, filled in. Copy the name, address and command above — the picture
              uses a dummy key and an example address.
            </figcaption>
          </figure>

          <Message severity="info" :closable="false">
            The key sits in that command in plain text. Prefer a dedicated, expiring key for
            Claude Science, and revoke it here when you are done.
          </Message>
        </div>
      </template>
    </Panel>

    <Panel header="Create a new key">
      <div class="api-keys-view__create-row">
        <InputText
          v-model="newKeyName"
          placeholder="Key name"
          class="api-keys-view__create-name"
          @keyup.enter="createKey"
        />
        <Select
          v-model="newKeyExpiry"
          :options="expiryOptions"
          option-label="label"
          option-value="value"
          class="api-keys-view__create-expiry"
        />
        <Button
          label="Create"
          icon="pi pi-plus"
          :loading="creating"
          :disabled="!newKeyName.trim()"
          @click="createKey"
        />
      </div>
    </Panel>

    <Panel header="Your API keys">
      <Message v-if="listError" severity="error" :closable="false">
        {{ listError }}
      </Message>

      <DataTable
        :value="keys"
        data-key="id"
        stripedRows
        :loading="loading"
        :rowHover="true"
      >
        <template #empty>
          <div class="api-keys-view__empty">
            <i class="pi pi-key" aria-hidden="true" />
            <p>No API keys yet.</p>
          </div>
        </template>
        <Column field="name" header="Name" />
        <Column field="key_prefix" header="Prefix">
          <template #body="{ data }">
            <code>{{ data.key_prefix }}…</code>
          </template>
        </Column>
        <Column header="Created">
          <template #body="{ data }">{{ formatDate(data.created_at) }}</template>
        </Column>
        <Column header="Last used">
          <template #body="{ data }">{{ data.last_used_at ? formatDate(data.last_used_at) : '—' }}</template>
        </Column>
        <Column header="Expires">
          <template #body="{ data }">{{ data.expires_at ? formatDate(data.expires_at) : 'Never' }}</template>
        </Column>
        <Column header="Status">
          <template #body="{ data }">
            <Tag :value="data.status" :severity="statusSeverity(data.status)" />
          </template>
        </Column>
        <Column header="Actions">
          <template #body="{ data }">
            <Button
              v-if="data.status === 'active'"
              icon="pi pi-trash"
              severity="danger"
              text
              v-tooltip.top="'Revoke'"
              :loading="revokingId === data.id"
              @click="confirmRevoke(data)"
            />
          </template>
        </Column>
      </DataTable>
    </Panel>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Panel from 'primevue/panel'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Message from 'primevue/message'
import { useToast } from 'primevue/usetoast'
import { apiKeysApi, parseApiTimestamp } from '../webapi'
import type { ApiKeyDto, CreatedApiKeyDto } from '../webapi'
import { useAuthStore } from '../stores/auth'

const emit = defineEmits<{
  back: []
}>()

const toast = useToast()
const authStore = useAuthStore()

const keys = ref<ApiKeyDto[]>([])
const loading = ref(false)
const listError = ref<string | null>(null)

// 0, not null, for "Never": PrimeVue Select decides whether to render a label
// at all with an emptiness check on the model value, so a null-valued option
// selects but displays blank. createKey maps 0 back to null for the API.
const NEVER_EXPIRES = 0

const expiryOptions = [
  { label: '30 days', value: 30 },
  { label: '90 days', value: 90 },
  { label: '365 days', value: 365 },
  { label: 'Never', value: NEVER_EXPIRES }
]

const newKeyName = ref('')
const newKeyExpiry = ref<number>(90)
const creating = ref(false)

const issuedKey = ref<CreatedApiKeyDto | null>(null)
const curlExpanded = ref(false)
const mcpExpanded = ref(false)
const claudeScienceExpanded = ref(false)
const secretCodeRef = ref<HTMLElement | null>(null)

const mcpServerName = 'binderdash'
// Vite asset URL. A static import needs a module declaration this project doesn't have.
const claudeScienceShot = new URL('../assets/claude-science-connector.webp', import.meta.url).href

const revokingId = ref<number | null>(null)

// The MCP server is an optional backend extra; don't advertise setup for an endpoint
// this deployment doesn't serve.
const mcpEnabled = computed(() => authStore.authStatus?.mcp?.enabled === true)
const mcpUrl = computed(
  () => `${window.location.origin}${authStore.authStatus?.mcp?.path ?? '/api/mcp/'}`
)

const curlSnippet = computed(() => {
  if (!issuedKey.value) return ''
  const origin = window.location.origin
  return `curl -H "X-Binderdash-Api-Key: ${issuedKey.value.key}" ${origin}/api/runs`
})

const mcpCliSnippet = computed(() => {
  if (!issuedKey.value) return ''
  return [
    'claude mcp add --transport http --scope user binderdash \\',
    `  ${mcpUrl.value} \\`,
    `  --header "Authorization: Bearer ${issuedKey.value.key}"`
  ].join('\n')
})

const mcpJsonSnippet = computed(() => {
  if (!issuedKey.value) return ''
  return JSON.stringify(
    {
      mcpServers: {
        binderdash: {
          type: 'http',
          url: mcpUrl.value,
          headers: { Authorization: `Bearer ${issuedKey.value.key}` }
        }
      }
    },
    null,
    2
  )
})

// Keys are bd_ + token_urlsafe (A-Za-z0-9_-), so single quotes keep the JSON intact in bash, zsh and PowerShell.
const mcpScienceCommand = computed(() => {
  if (!issuedKey.value) return ''
  return `echo '{"Authorization": "Bearer ${issuedKey.value.key}"}'`
})

function formatDate(value: string): string {
  const d = parseApiTimestamp(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString()
}

function statusSeverity(status: ApiKeyDto['status']): 'success' | 'warn' | 'danger' {
  if (status === 'active') return 'success'
  if (status === 'expired') return 'warn'
  return 'danger'
}

async function loadKeys() {
  loading.value = true
  listError.value = null
  try {
    const response = await apiKeysApi.list()
    keys.value = response.keys
  } catch (error) {
    console.error('Failed to list API keys:', error)
    listError.value = error instanceof Error ? error.message : 'Failed to load API keys'
  } finally {
    loading.value = false
  }
}

async function createKey() {
  const name = newKeyName.value.trim()
  if (!name) return
  creating.value = true
  try {
    const created = await apiKeysApi.create(
      name,
      newKeyExpiry.value === NEVER_EXPIRES ? null : newKeyExpiry.value
    )
    issuedKey.value = created
    curlExpanded.value = false
    claudeScienceExpanded.value = false
    newKeyName.value = ''
    newKeyExpiry.value = 90
    await loadKeys()
    toast.add({
      severity: 'success',
      summary: 'Key created',
      detail: `API key "${created.name}" created.`,
      life: 4000
    })
  } catch (error) {
    console.error('Failed to create API key:', error)
    toast.add({
      severity: 'error',
      summary: 'Create failed',
      detail: error instanceof Error ? error.message : 'Request failed',
      life: 5000
    })
  } finally {
    creating.value = false
  }
}

async function confirmRevoke(key: ApiKeyDto) {
  // No ConfirmationService registered in the app — plain window.confirm matches
  // the pattern already used for saved-set deletion (SavedSetsList.vue).
  if (!window.confirm(`Revoke API key "${key.name}"? Any client using it will stop working immediately.`)) return
  revokingId.value = key.id
  try {
    await apiKeysApi.revoke(key.id)
    await loadKeys()
    toast.add({
      severity: 'success',
      summary: 'Revoked',
      detail: `API key "${key.name}" revoked.`,
      life: 4000
    })
  } catch (error) {
    console.error('Failed to revoke API key:', error)
    toast.add({
      severity: 'error',
      summary: 'Revoke failed',
      detail: error instanceof Error ? error.message : 'Request failed',
      life: 5000
    })
  } finally {
    revokingId.value = null
  }
}

/** Copy to the clipboard. Returns false so callers can offer their own fallback. */
async function copyText(text: string, successDetail: string, quiet = false): Promise<boolean> {
  if (!text) return false
  // navigator.clipboard is undefined outside a secure context (e.g. served over
  // plain HTTP on the LAN).
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      toast.add({ severity: 'success', summary: 'Copied', detail: successDetail, life: 3000 })
      return true
    } catch (error) {
      console.error('Clipboard write failed:', error)
    }
  }
  if (!quiet) {
    toast.add({
      severity: 'info',
      summary: 'Clipboard unavailable',
      detail: 'Clipboard access is unavailable here — select the text and copy it manually.',
      life: 6000
    })
  }
  return false
}

async function copySecret() {
  const secret = issuedKey.value?.key
  if (!secret) return

  if (await copyText(secret, 'API key copied to clipboard.', true)) return

  // Fall back to selecting the key text so it can be copied by hand.
  const el = secretCodeRef.value
  if (el) {
    const range = document.createRange()
    range.selectNodeContents(el)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
  }
  toast.add({
    severity: 'info',
    summary: 'Select and copy',
    detail: 'Clipboard access is unavailable here — the key text has been selected for you to copy manually.',
    life: 6000
  })
}

onMounted(loadKeys)
</script>

<style scoped>
.api-keys-view {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.api-keys-view__back {
  align-self: flex-start;
}

.api-keys-view__secret-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  flex-wrap: wrap;
}

.api-keys-view__secret {
  flex: 1 1 auto;
  min-width: 16rem;
  padding: 0.5rem 0.75rem;
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 4px;
  word-break: break-all;
}

.api-keys-view__curl-toggle {
  margin-top: 0.5rem;
}

.api-keys-view__setup-toggles {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 0.75rem;
  margin-top: 0.5rem;
}

.api-keys-view__setup-toggles .api-keys-view__curl-toggle {
  margin-top: 0;
}

.api-keys-view__science-figure {
  margin: 0;
}

.api-keys-view__science-shot {
  display: block;
  width: min(100%, 28rem);
  height: auto;
  border: 1px solid #dee2e6;
  border-radius: 6px;
}

.api-keys-view__science-caption {
  margin: 0.35rem 0 0;
  max-width: 28rem;
  font-size: 0.875rem;
  color: #6c757d;
}

.api-keys-view__curl {
  margin-top: 0.5rem;
  padding: 0.75rem;
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 4px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.api-keys-view__mcp {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin-top: 0.5rem;
}

.api-keys-view__mcp-intro,
.api-keys-view__mcp-hint {
  margin: 0 0 0.5rem;
  color: #495057;
}

.api-keys-view__mcp-hint {
  font-size: 0.875rem;
}

.api-keys-view__mcp-step h4 {
  margin: 0 0 0.25rem;
  font-size: 0.95rem;
}

.api-keys-view__snippet-row {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
}

.api-keys-view__snippet-row .api-keys-view__curl {
  flex: 1 1 auto;
  margin-top: 0;
}

.api-keys-view__create-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.api-keys-view__create-name {
  flex: 1 1 16rem;
}

.api-keys-view__create-expiry {
  flex: 0 0 10rem;
}

.api-keys-view__empty {
  padding: 1.5rem;
  text-align: center;
  color: #6c757d;
}
</style>
