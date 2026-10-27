/**
 * IndexedDB persistence for the Prepare Sequences tab.
 *
 * Built on the same capture/restore pair the download bundle uses, so there is one
 * definition of "the Prepare Sequences settings" rather than two that can disagree.
 * Prepared sequences themselves are not stored: they are derived from these settings
 * plus the selected designs, and stale DNA shown as current would be worse than none.
 */

import { watch } from 'vue'
import { useSeqPrepStore } from '../stores/seqPrep'
import { PERSISTENCE_KEYS } from '../persistence/keys'
import { kvGet, kvSet } from '../persistence/store'
import { applyPrepareState, buildPrepareState } from './prepareState'
import type { PrepareSequencesStateDto } from './types'

const PERSIST_DEBOUNCE_MS = 400

let hydrated = false
let timer: ReturnType<typeof setTimeout> | null = null

export async function hydrateSeqPrepState(): Promise<void> {
    try {
        const payload = await kvGet<PrepareSequencesStateDto>(PERSISTENCE_KEYS.seqPrepState)
        if (payload) applyPrepareState(payload)
    } catch (e) {
        console.warn('Failed to hydrate Prepare Sequences state from IndexedDB', e)
    } finally {
        hydrated = true
        startPersisting()
    }
}

function startPersisting(): void {
    const seqPrep: any = useSeqPrepStore()
    watch(
        () => [
            seqPrep.nTags,
            seqPrep.cTags,
            seqPrep.exportOrderName,
            seqPrep.extractChain,
            seqPrep.dnaMode,
            seqPrep.goodOnly,
            seqPrep.selectedCodonTable,
            seqPrep.optimizationMethod,
            seqPrep.optimizationConstraints,
            seqPrep.shortNameKind
        ],
        () => {
            if (!hydrated) return
            if (timer) clearTimeout(timer)
            timer = setTimeout(() => {
                timer = null
                void kvSet(PERSISTENCE_KEYS.seqPrepState, buildPrepareState())
            }, PERSIST_DEBOUNCE_MS)
        },
        { deep: true }
    )
}
