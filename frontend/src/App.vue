<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import Tabs from 'primevue/tabs'
import TabList from 'primevue/tablist'
import Button from 'primevue/button'
import RestoreSessionDialog from './components/RestoreSessionDialog.vue'
import Tab from 'primevue/tab'
import TabPanels from 'primevue/tabpanels'
import TabPanel from 'primevue/tabpanel'
import Toast from 'primevue/toast'
import { useToast } from 'primevue/usetoast'
import RunsView from './components/DesignsView.vue'
import PrepareSequencesView from './components/PrepareSequencesView.vue'
import PlotsView from './components/PlotsView.vue'
import FilteringView from './components/FilteringView.vue'
import SavedSetsView from './components/SavedSetsView.vue'
import FolderBrowser from './components/FolderBrowser.vue'
import SelectRunsPanel from './components/SelectRunsPanel.vue'
import LoginView from './components/LoginView.vue'
import UserMenu from './components/UserMenu.vue'
import AccountView from './components/AccountView.vue'
import ApiKeysView from './components/ApiKeysView.vue'
import { useAppStore, useDesignsStore, usePlotsStore, useRunsStore, useAuthStore } from './stores'
import { healthApi } from './webapi'

// Use Pinia stores
const appStore = useAppStore()
const designsStore = useDesignsStore()
const plotsStore = usePlotsStore()
const runsStore = useRunsStore()
const authStore = useAuthStore()
const toast = useToast()

// Create refs to components so we can call their methods
const runsViewRef = ref<any>(null)
const plotsViewRef = ref<any>(null)

const onIngestComplete = async (): Promise<void> => {
  await runsStore.fetchRuns()
  if (designsStore.selectedRunIds.length > 0) {
    await designsStore.fetchDesignsForRuns(designsStore.selectedRunIds)
  }
}

// Tab `value`s with a matching Tab in the TabList below.
const TAB_IDS = ['designs', 'plots', 'filtering', 'saved-sets', 'seq-prep', 'select-runs', 'ingest'] as const
// "Overlay" views have a TabPanel but deliberately no matching Tab — PrimeVue's
// TabPanel renders on `equals(d_value, value)` alone (verified in
// node_modules/primevue/tabpanel), so this swaps the panel area without a nav
// entry, reusing the tab-panel card chrome for the Account/API-keys screens.
const OVERLAY_VIEWS = ['account', 'api-keys'] as const
const VALID_TABS = [...TAB_IDS, ...OVERLAY_VIEWS] as const
type TabId = (typeof VALID_TABS)[number]

function isValidTab(value: string): value is TabId {
  return (VALID_TABS as readonly string[]).includes(value)
}

const initialHashTab = window.location.hash.slice(1)
if (isValidTab(initialHashTab)) {
  appStore.setActiveTab(initialHashTab)
}

// Backed by appStore.activeTab so other components (e.g. DesignsView's "go to
// Filtering tab" banner) can switch tabs without prop-drilling a ref through App.vue.
const mainTab = computed<string>({
  get: () => appStore.activeTab,
  set: (tab) => appStore.setActiveTab(tab)
})

const isOverlayView = computed(() => (OVERLAY_VIEWS as readonly string[]).includes(mainTab.value))

// Remembers the last real tab so closing an overlay view (Account/API keys)
// returns the user to where they were, rather than always landing on Designs.
const previousTab = ref<string>(mainTab.value)
watch(mainTab, (tab, oldTab) => {
  if (!(OVERLAY_VIEWS as readonly string[]).includes(oldTab)) {
    previousTab.value = oldTab
  }
})

function closeOverlayView() {
  mainTab.value = previousTab.value
}

function handleUserMenuNavigate(view: 'account' | 'api-keys') {
  mainTab.value = view
}

watch(mainTab, (tab) => {
  if (window.location.hash.slice(1) !== tab) {
    window.location.hash = tab
  }
})

function handleHashChange() {
  const tab = window.location.hash.slice(1)
  if (isValidTab(tab) && tab !== appStore.activeTab) {
    appStore.setActiveTab(tab)
  }
}

onMounted(() => window.addEventListener('hashchange', handleHashChange))
onUnmounted(() => window.removeEventListener('hashchange', handleHashChange))

// Overlay views (Account/API keys) require an authenticated session — bounce
// back to Designs if auth status resolves to "not authenticated" while one is open.
watch(
  () => [isOverlayView.value, authStore.isAuthEnabled, authStore.isAuthenticated] as const,
  ([overlay, authEnabled, authenticated]) => {
    if (overlay && authEnabled && !authenticated) {
      mainTab.value = 'designs'
    }
  }
)

watch(
  () => [mainTab.value, authStore.canLoadData] as const,
  async ([tab, canLoad]) => {
    if (!canLoad) return
    if (tab === 'designs' || tab === 'plots') {
      await designsStore.ensureDesignsForCurrentSelection()
    }
    if (tab === 'plots') {
      await nextTick()
      await plotsViewRef.value?.syncFromDesignTable?.()
    }
  },
  { immediate: true }
)

const tabNavGroupSecondaryPt = {
  root: { class: 'tab-nav-group-secondary' }
}

// Track if authentication has been initialized
const authInitialized = ref(false)
const restoreDialogVisible = ref(false)

// Build identity for the footer. /health only returns it to an authenticated
// caller, so wait for the session rather than asking on mount and getting nothing.
const buildLabel = ref('')
watch(
  () => authStore.canLoadData,
  async (canLoad) => {
    if (!canLoad || buildLabel.value) return
    try {
      buildLabel.value = (await healthApi.get()).build?.label ?? ''
    } catch {
      // A footer is never worth surfacing an error for.
    }
  },
  { immediate: true }
)

// Initialize authentication on app start
onMounted(async () => {
  try {
    await authStore.initializeAuth()
  } catch (error) {
    console.error('Auth initialization failed:', error)
  } finally {
    authInitialized.value = true
  }
  const params = new URLSearchParams(window.location.search)
  const authErr = params.get('auth_error')
  if (authErr === 'not_allowed') {
    toast.add({
      severity: 'error',
      summary: 'Sign-in denied',
      detail: 'Your Google account is not on the allowed list.',
      life: 8000
    })
  } else if (authErr === 'oauth_failed') {
    toast.add({
      severity: 'error',
      summary: 'Google sign-in failed',
      detail: 'Try again or use another sign-in method.',
      life: 8000
    })
  }
  if (authErr) {
    const url = new URL(window.location.href)
    url.searchParams.delete('auth_error')
    window.history.replaceState({}, document.title, url.pathname + url.search + url.hash)
  }
})

// Computed property to check if we should show loading state
const shouldShowLoading = computed(() => {
  // Show loading if auth hasn't been initialized yet
  return !authInitialized.value
})
</script>

<template>
  <div class="binderdash-root">
    <!-- Show loading state while authentication is being initialized -->
    <div v-if="shouldShowLoading" class="loading-container">
      <div class="loading-content">
        <i class="pi pi-spinner pi-spin" style="font-size: 2rem; color: #667eea;"></i>
        <p>Initializing...</p>
      </div>
    </div>
        
    <!-- Show login page if authentication is required and user is not authenticated -->
    <LoginView v-else-if="authStore.shouldShowLogin" />
    
    <!-- Show main app if authentication is disabled or user is authenticated -->
    <template v-else>
      <header class="app-header">
        <div class="app-header__actions">
          <Button
            icon="pi pi-history"
            label="Restore session"
            severity="secondary"
            size="small"
            class="restore-session-button"
            v-tooltip.bottom="'Load a session JSON from a downloaded design bundle'"
            @click="restoreDialogVisible = true"
          />
          <UserMenu
            v-if="authStore.isAuthEnabled && authStore.isAuthenticated"
            @navigate="handleUserMenuNavigate"
          />
        </div>
        <div class="banner-overlay">
          <h1>Binderdash</h1>
          <p>De novo protein binder design results viewer</p>
        </div>
      </header>

      <main class="app-main">
        <Tabs
          v-model:value="mainTab"
          class="binderdash-main-tabs"
          :class="{ 'binderdash-main-tabs--overlay': isOverlayView }"
        >
          <TabList>
            <Tab value="designs">
              <span class="binderdash-tab-label">
                <i class="pi pi-table" aria-hidden="true" />
                <span>Designs</span>
              </span>
            </Tab>
            <Tab value="plots">
              <span class="binderdash-tab-label">
                <i class="pi pi-chart-line" aria-hidden="true" />
                <span>Plots</span>
              </span>
            </Tab>
            <Tab value="filtering">
              <span class="binderdash-tab-label">
                <i class="pi pi-filter" aria-hidden="true" />
                <span>Filtering</span>
              </span>
            </Tab>
            <Tab value="saved-sets">
              <span class="binderdash-tab-label">
                <i class="pi pi-bookmark" aria-hidden="true" />
                <span>Saved Sets</span>
              </span>
            </Tab>
            <Tab value="seq-prep">
              <span class="binderdash-tab-label">
                <svg
                  class="binderdash-tab-icon-dna"
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path
                    d="M4 1v14h1.25V1H4zm6.75 0v14H12V1h-1.25zM5.5 3.25h5v1h-5v-1zm0 2.5h5v1h-5v-1zm0 2.5h5v1h-5v-1zm0 2.5h5v1h-5v-1z"
                  />
                </svg>
                <span>Prepare Sequences</span>
              </span>
            </Tab>
            <Tab value="select-runs" :pt="tabNavGroupSecondaryPt">
              <span class="binderdash-tab-label">
                <i class="pi pi-list-check" aria-hidden="true" />
                <span>Select Runs</span>
              </span>
            </Tab>
            <Tab value="ingest">
              <span class="binderdash-tab-label">
                <i class="pi pi-download" aria-hidden="true" />
                <span>Ingest Runs</span>
              </span>
            </Tab>
          </TabList>
          <TabPanels>
            <TabPanel value="designs">
              <RunsView ref="runsViewRef" />
            </TabPanel>
            <TabPanel value="plots">
              <PlotsView ref="plotsViewRef" />
            </TabPanel>
            <TabPanel value="filtering">
              <FilteringView />
            </TabPanel>
            <TabPanel value="saved-sets">
              <SavedSetsView @reapply-filters="mainTab = 'filtering'" />
            </TabPanel>
            <TabPanel value="seq-prep">
              <PrepareSequencesView />
            </TabPanel>
            <TabPanel value="select-runs">
              <SelectRunsPanel @ingest-complete="onIngestComplete" />
            </TabPanel>
            <TabPanel value="ingest">
              <FolderBrowser @ingest-complete="onIngestComplete" />
            </TabPanel>
            <!-- Overlay views: no matching Tab in the TabList above, so `lazy`
                 defaults to false and these would otherwise mount (and fetch)
                 on every load — gated with v-if instead. -->
            <TabPanel value="account">
              <AccountView v-if="mainTab === 'account'" @back="closeOverlayView" />
            </TabPanel>
            <TabPanel value="api-keys">
              <ApiKeysView v-if="mainTab === 'api-keys'" @back="closeOverlayView" />
            </TabPanel>
          </TabPanels>
        </Tabs>
      </main>

      <RestoreSessionDialog v-model:visible="restoreDialogVisible" />

      <!-- Inside the authenticated branch: the build identity is not for the
           login page, where anyone on the network can read it. -->
      <footer v-if="buildLabel" class="app-footer">Binderdash {{ buildLabel }}</footer>
    </template>

    <Toast />
  </div>
</template>

<style>
footer.app-footer {
  /* Right padding matches .app-main's, so the text lines up with the right edge
     of the tab panel above it. */
  padding: 0.5rem 2rem 0.75rem;
  text-align: right;
  font-size: 0.68rem;
  /* `footer` is required: the later `[class*="p-"]` override matches this
     element because the class name contains "p-", and it uses !important. */
  color: #b0b5ba !important;
  user-select: text;
}

.binderdash-root {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  background-color: #f8f9fa;
  width: 100% !important;
  max-width: none !important;
  margin: 0 !important;
  padding: 0 !important;
}

body {
  margin: 0 !important;
  padding: 0 !important;
  width: 100% !important;
  max-width: none !important;
}

.app-header {
  background-image: url('./assets/banner.webp');
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  position: relative;
  padding: 1rem 2rem;
  text-align: center;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
  width: 100%;
  box-sizing: border-box;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.app-header::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(102, 51, 153, 0.7); /* Purple filter at 70% opacity */
  z-index: 1;
}

.banner-overlay {
  position: relative;
  z-index: 2;
  color: white;
}

.banner-overlay h1 {
  margin: 0;
  font-size: 2rem;
  font-weight: 600;
  color: white;
  text-shadow: 0 2px 4px rgba(0,0,0,0.3);
}

.banner-overlay p {
  margin: 0.5rem 0 0 0;
  opacity: 0.9;
  font-size: 1rem;
  color: white;
  text-shadow: 0 1px 2px rgba(0,0,0,0.3);
}

.app-header__actions {
  position: absolute;
  top: 0.75rem;
  right: 1rem;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

/* Text buttons disappear here: the banner is purple, and the later
   `[class*="p-"]` colour override paints the label #495057. Match the
   account trigger (UserMenu.vue). */
.app-header .restore-session-button.p-button {
  color: #fff !important;
  background: rgba(0, 0, 0, 0.35) !important;
  border: 1px solid rgba(255, 255, 255, 0.55) !important;
}

.app-header .restore-session-button.p-button .p-button-icon,
.app-header .restore-session-button.p-button .p-button-label {
  color: #fff !important;
}

.app-header .restore-session-button.p-button:hover {
  background: rgba(0, 0, 0, 0.5) !important;
  border-color: rgba(255, 255, 255, 0.75) !important;
}

.loading-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: #f8f9fa;
}

.loading-content {
  text-align: center;
  color: #6c757d;
}

.loading-content p {
  margin: 1rem 0 0 0;
  font-size: 1rem;
}

.app-main {
  padding: 2rem;
  width: 100% !important;
  max-width: none !important;
  margin: 0 !important;
  box-sizing: border-box !important;
}

/* Global text color overrides - HIGH PRIORITY */
* {
  color: #495057 !important;
}

/* Ensure all text elements have proper contrast */
p, span, div, label, input, textarea, select, button, a, h1, h2, h3, h4, h5, h6 {
  color: #495057 !important;
}

/* App header override - keep white text on dark background */
.app-header, .app-header * {
  color: white !important;
}

.banner-overlay, .banner-overlay * {
  color: white !important;
}

.banner-overlay h1, .banner-overlay p {
  color: white !important;
}

/* PrimeVue Tabs (v4; replaces deprecated TabView) */
.app-main .binderdash-main-tabs.p-tabs {
  width: 100% !important;
  max-width: 100% !important;
}

.app-main .binderdash-main-tabs .p-tablist {
  border-radius: 8px 8px 0 0 !important;
  overflow: hidden;
}

/* Overlay views (Account/API keys) have no matching Tab, so the ink bar would
   otherwise sit frozen under whichever real tab was last active — hide it. */
.app-main .binderdash-main-tabs--overlay .p-tablist-active-bar {
  display: none !important;
}

.app-main .binderdash-main-tabs .binderdash-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.app-main .binderdash-main-tabs .binderdash-tab-label .pi {
  font-size: 1rem;
  opacity: 0.9;
}

.app-main .binderdash-main-tabs .binderdash-tab-label .binderdash-tab-icon-dna {
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
  opacity: 0.9;
}

/* Full-width row so margin-left: auto can separate the two groups */
.app-main .binderdash-main-tabs .p-tablist-tab-list {
  min-width: 100% !important;
  box-sizing: border-box !important;
}

/* [Designs, Plots, Prepare] | [Select Runs, Ingest] — only on Select Runs */
.app-main .binderdash-main-tabs .p-tab.tab-nav-group-secondary {
  margin-left: auto !important;
  padding-left: 1rem !important;
  border-left: 1px solid #dee2e6 !important;
}

.app-main .binderdash-main-tabs .p-tab {
  padding: 1rem 1.5rem !important;
  font-weight: 500 !important;
  color: #495057 !important;
  background: #f8f9fa !important;
  border: none !important;
  border-bottom: 2px solid transparent !important;
  border-radius: 0 !important;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease !important;
}

.app-main .binderdash-main-tabs .p-tab:not(.p-disabled):hover {
  background: #e9ecef !important;
  color: #212529 !important;
}

.app-main .binderdash-main-tabs .p-tab.p-tab-active {
  background: white !important;
  color: #667eea !important;
  border-bottom: 2px solid #667eea !important;
  font-weight: 600 !important;
}

.app-main .binderdash-main-tabs .p-tabpanels {
  background: white !important;
  border-radius: 0 0 8px 8px !important;
  padding: 2rem !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1) !important;
  width: 100% !important;
  box-sizing: border-box !important;
}

.app-main .binderdash-main-tabs .p-tabpanel {
  padding: 0 !important;
  width: 100% !important;
}

/* DataTable styling - COMPREHENSIVE OVERRIDE */
.p-datatable .p-datatable-thead > tr > th {
  background: #f8f9fa !important;
  color: #495057 !important;
  font-weight: 600 !important;
  border-bottom: 1px solid #dee2e6 !important;
}

/* Selection column: whole-cell clicks toggle the row (see DesignsView / metaKeySelection) */
.p-datatable td[data-p-selection-column="true"],
.p-datatable th[data-p-selection-column="true"],
.p-datatable td.row-selection-cell,
.p-datatable th.row-selection-cell {
  cursor: pointer;
}

.p-datatable .p-datatable-tbody > tr > td {
  color: #495057 !important;
  border-bottom: 1px solid #f1f3f4 !important;
}

.p-datatable .p-datatable-tbody > tr:hover > td {
  background: #f8f9fa !important;
}

/* TreeTable styling - COMPREHENSIVE OVERRIDE */
.p-treetable .p-treetable-thead > tr > th {
  background: #f8f9fa !important;
  color: #495057 !important;
  font-weight: 600 !important;
  border-bottom: 1px solid #dee2e6 !important;
}

.p-treetable .p-treetable-tbody > tr > td {
  color: #495057 !important;
  border-bottom: 1px solid #f1f3f4 !important;
}

.p-treetable .p-treetable-tbody > tr:hover > td {
  background: #f8f9fa !important;
}

/* Pagination styling - COMPREHENSIVE OVERRIDE */
.p-paginator {
  background: #f8f9fa !important;
  border-top: 1px solid #dee2e6 !important;
}

.p-paginator .p-paginator-current {
  color: #495057 !important;
  font-weight: 500 !important;
}

.p-paginator .p-paginator-pages .p-paginator-page {
  color: #495057 !important;
  background: white !important;
  border: 1px solid #dee2e6 !important;
}

.p-paginator .p-paginator-pages .p-paginator-page:hover {
  background: #e9ecef !important;
  color: #212529 !important;
}

.p-paginator .p-paginator-pages .p-paginator-page.p-highlight {
  background: #667eea !important;
  color: white !important;
  border-color: #667eea !important;
}

/* Dropdown styling - COMPREHENSIVE OVERRIDE */
.p-dropdown {
  background: white !important;
  border: 1px solid #dee2e6 !important;
  color: #495057 !important;
}

.p-dropdown:hover {
  border-color: #adb5bd !important;
}

.p-dropdown .p-dropdown-trigger {
  color: #6c757d !important;
}

.p-dropdown .p-dropdown-label {
  color: #495057 !important;
}

/* Tag styling - COMPREHENSIVE OVERRIDE */
.p-tag {
  font-weight: 500 !important;
}

/* Method + primary-score chips use PrimeVue palette vars (`pipelineDisplay.ts`), not `severity`. */
.p-tag.pipeline-palette-tag {
  border: none !important;
}

.p-tag.p-tag-success {
  background: #d4edda !important;
  color: #155724 !important;
  border: 1px solid #c3e6cb !important;
}

.p-tag.p-tag-info {
  background: #d1ecf1 !important;
  color: #0c5460 !important;
  border: 1px solid #bee5eb !important;
}

.p-tag.p-tag-warning {
  background: #fff3cd !important;
  color: #856404 !important;
  border: 1px solid #ffeaa7 !important;
}

/* Badge styling - COMPREHENSIVE OVERRIDE */
.p-badge {
  font-weight: 500 !important;
}

.p-badge.p-badge-info {
  background: #17a2b8 !important;
  color: white !important;
}

/* Toast styling - COMPREHENSIVE OVERRIDE */
.p-toast .p-toast-message {
  border-radius: 6px !important;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important;
}

.p-toast .p-toast-message .p-toast-message-content {
  padding: 1rem !important;
}

.p-toast .p-toast-message .p-toast-summary {
  font-weight: 600 !important;
  color: #495057 !important;
}

.p-toast .p-toast-message .p-toast-detail {
  color: #6c757d !important;
  margin-top: 0.25rem !important;
}

/* Chip styling - COMPREHENSIVE OVERRIDE */
.p-chip {
  background: #e9ecef !important;
  color: #495057 !important;
  border: 1px solid #dee2e6 !important;
}

.p-chip .p-chip-text {
  color: #495057 !important;
}

/* Input styling - COMPREHENSIVE OVERRIDE */
.p-inputtext {
  color: #495057 !important;
  background: white !important;
  border: 1px solid #dee2e6 !important;
}

.p-inputtext:focus {
  border-color: #667eea !important;
  box-shadow: 0 0 0 0.2rem rgba(102, 126, 234, 0.25) !important;
}

/* Label styling - COMPREHENSIVE OVERRIDE */
.p-component {
  color: #495057 !important;
}

/* Override any remaining light text */
.p-component * {
  color: #495057 !important;
}

/* Ensure icons don't inherit text color */
.pi {
  color: inherit !important;
}

/* Override any PrimeVue default text colors */
[class*="p-"] {
  color: #495057 !important;
}

/* Specific overrides for common PrimeVue text elements */
.p-component, .p-component * {
  color: #495057 !important;
}

/* Force readable text on all interactive elements */
button, input, select, textarea, a, .p-button, .p-dropdown, .p-inputtext {
  color: #495057 !important;
}

/* Override any remaining light grey text */
*[style*="color: rgb(108, 117, 125)"], 
*[style*="color: #6c757d"],
*[style*="color: rgb(173, 181, 189)"],
*[style*="color: #adb5bd"] {
  color: #495057 !important;
}

/* Comprehensive checkbox styling for TreeTable */
.p-treetable .p-checkbox {
  display: inline-block !important;
  visibility: visible !important;
  opacity: 1 !important;
  margin-right: 0.5rem !important;
  position: relative !important;
  z-index: 1 !important;
}

.p-treetable .p-checkbox .p-checkbox-box {
  display: inline-block !important;
  visibility: visible !important;
  opacity: 1 !important;
  width: 16px !important;
  height: 16px !important;
  border: 2px solid #dee2e6 !important;
  background: white !important;
  border-radius: 3px !important;
  position: relative !important;
  cursor: pointer !important;
  transition: all 0.2s ease !important;
}

.p-treetable .p-checkbox .p-checkbox-box:hover {
  border-color: #667eea !important;
  background: #f8f9fa !important;
}

.p-treetable .p-checkbox .p-checkbox-box.p-highlight {
  background: #667eea !important;
  border-color: #667eea !important;
}

.p-treetable .p-checkbox .p-checkbox-box.p-highlight .p-checkbox-icon {
  color: white !important;
  font-size: 12px !important;
  font-weight: bold !important;
}

.p-treetable .p-checkbox .p-checkbox-box .p-checkbox-icon {
  display: block !important;
  visibility: visible !important;
  opacity: 1 !important;
  color: white !important;
  font-size: 12px !important;
  font-weight: bold !important;
  text-align: center !important;
  line-height: 12px !important;
}

/* Ensure checkbox is clickable */
.p-treetable .p-checkbox input[type="checkbox"] {
  position: absolute !important;
  opacity: 0 !important;
  pointer-events: none !important;
}

/* TreeTable row styling to accommodate checkboxes */
.p-treetable .p-treetable-tbody > tr > td:first-child {
  padding-left: 0.5rem !important;
  position: relative !important;
}

.p-treetable .p-treetable-tbody > tr > td:first-child .folder-node {
  display: flex !important;
  align-items: center !important;
  gap: 0.5rem !important;
  padding-left: 0 !important;
}

/* Button styling improvements for better visibility */
/*
.p-button {
  color: #495057 !important;
  background: #ffffff !important;
  border: 1px solid #dee2e6 !important;
  font-weight: 500 !important;
  padding: 0.5rem 1rem !important;
  cursor: pointer !important;
  transition: all 0.2s ease !important;
  display: inline-flex !important;
  align-items: center !important;
  gap: 0.5rem !important;
}

.p-button:hover {
  background: #f8f9fa !important;
  border-color: #adb5bd !important;
  color: #212529 !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
}

.p-button:disabled {
  opacity: 0.6 !important;
  cursor: not-allowed !important;
  transform: none !important;
  box-shadow: none !important;
}
*/

/* Toast styling improvements - GLOBAL OVERRIDE */
.p-toast {
  opacity: 1 !important;
}

.p-toast .p-toast-message {
  background: white !important;
  border: 1px solid #e9ecef !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
  opacity: 1 !important;
  color: #495057 !important;
}

.p-toast .p-toast-message-content {
  background: white !important;
  opacity: 1 !important;
  color: #495057 !important;
}

.p-toast .p-toast-message-text {
  color: #495057 !important;
  opacity: 1 !important;
}

.p-toast .p-toast-message-icon {
  opacity: 1 !important;
}

.p-toast .p-toast-icon-close {
  opacity: 1 !important;
  color: #6c757d !important;
}

.p-toast .p-toast-icon-close:hover {
  color: #495057 !important;
}

/* Toast severity-specific styling */
.p-toast .p-toast-message.p-toast-message-success {
  background: #d4edda !important;
  border-color: #c3e6cb !important;
  color: #155724 !important;
}

.p-toast .p-toast-message.p-toast-message-error {
  background: #f8d7da !important;
  border-color: #f5c6cb !important;
  color: #721c24 !important;
}

.p-toast .p-toast-message.p-toast-message-warn {
  background: #fff3cd !important;
  border-color: #ffeaa7 !important;
  color: #856404 !important;
}

.p-toast .p-toast-message.p-toast-message-info {
  background: #d1ecf1 !important;
  border-color: #bee5eb !important;
  color: #0c5460 !important;
}
</style>
