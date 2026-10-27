/**
 * Capture and restore the Prepare Sequences tab's settings.
 *
 * The seqPrep store persists nothing today, so these two functions serve double duty:
 * they populate prepare_sequences.json in a download bundle, and they back the tab's
 * IndexedDB persistence so tag and codon settings survive a page reload.
 */

import { useSeqPrepStore } from '../stores/seqPrep'
import {
    PREPARE_KIND,
    PREPARE_SCHEMA_VERSION,
    type PrepareSequencesStateDto,
    type RestoreOutcome
} from './types'
import { assertReadableVersion } from './sessionState'

/** Settings that only affect short-name generation; grouped so the JSON stays readable. */
const SHORT_NAME_FIELDS = [
    'shortNameKind',
    'shortNameMaxLen',
    'shortNameRegexPattern',
    'shortNameRegexReplacement',
    'shortNameRegexFlags',
    'shortNameSplitDelimiter',
    'shortNameSplitIndices',
    'shortNameSplitAddPrefix',
    'shortNameSplitAddSuffix',
    'shortNameSplitAddHash',
    'shortNamePatternPrefix',
    'shortNamePatternUidLength',
    'shortNamePatternNumberPad',
    'shortNameSmartHashLen',
    'shortNameSmartStemIncludeHash',
    'shortNameSmartStemIncludeIndex',
    'shortNameSmartStemRemoveCommonPrefix',
    'shortNameSmartStemRemoveCommonSuffix',
    'shortNameSmartStemAddPrefix',
    'shortNameSmartStemAddSuffix',
    'shortNameStripPrefixRegex',
    'shortNameStripSuffixRegex',
    'shortNameStripNewPrefix'
] as const

const STOP_FIELDS = [
    'includeStopForNTagged',
    'includeStopForCTagged',
    'useDoubleStop',
    'dontModifyStartAtg',
    'showPostStopPadding',
    'postStopPadding',
    'postStopPadUpToNucleotideLength',
    'onlyUseNTerminalTagWhenPaddingRequired',
    'onlyUseCTerminalTagWhenPaddingRequired',
    'minDnaFragmentLength'
] as const

function plain<T>(value: T): T {
    return JSON.parse(JSON.stringify(value ?? null))
}

function collect(store: any, fields: readonly string[]): Record<string, any> {
    const out: Record<string, any> = {}
    for (const field of fields) out[field] = plain(store[field])
    return out
}

function restore(store: any, source: Record<string, any> | undefined, fields: readonly string[]): void {
    if (!source) return
    for (const field of fields) {
        const value = source[field]
        if (value === undefined) continue
        if (typeof store[field] === typeof value || store[field] === null) {
            store[field] = value
        }
    }
}

export function buildPrepareState(): PrepareSequencesStateDto {
    const seqPrep: any = useSeqPrepStore()
    return {
        schema_version: PREPARE_SCHEMA_VERSION,
        kind: PREPARE_KIND,
        order_name: seqPrep.exportOrderName ?? '',
        extract_chain: seqPrep.extractChain ?? '',
        good_only: !!seqPrep.goodOnly,
        dna_mode: !!seqPrep.dnaMode,
        n_tags: plain(seqPrep.nTags ?? []),
        c_tags: plain(seqPrep.cTags ?? []),
        stop_options: collect(seqPrep, STOP_FIELDS),
        short_name_strategy: collect(seqPrep, SHORT_NAME_FIELDS),
        codon_table_id: seqPrep.selectedCodonTable ?? null,
        optimization_method: seqPrep.optimizationMethod ?? null,
        optimization_constraints: plain(seqPrep.optimizationConstraints ?? []),
        // Seeds are only replayable against these exact versions: a DnaChisel
        // upgrade can change the search order, and so the DNA for a given seed.
        tool_versions: plain(seqPrep.optimizationToolVersions ?? {})
    }
}

/**
 * Prepared rows for the bundle, minus the fields that only exist to drive the UI.
 *
 * Each row carries the seed that produced its DNA, so the run can be replayed
 * rather than only described.
 */
export function buildPreparedRows(): Array<Record<string, any>> {
    const seqPrep: any = useSeqPrepStore()
    const seeds: Record<string, number> = seqPrep.optimizedSeedsByDesign ?? {}
    return (seqPrep.preparedRows ?? []).map((row: any) => {
        const {
            segments_aa,
            segments_aa_display,
            segments_dna,
            prepared_aa_display,
            design_filter_text,
            ...rest
        } = row
        const seed = seeds[row.design_id]
        return plain(seed != null ? { ...rest, seed } : rest)
    })
}

export function isPrepareState(payload: any): payload is PrepareSequencesStateDto {
    if (!payload || typeof payload !== 'object') return false
    if (payload.kind === PREPARE_KIND) return true
    return (
        typeof payload.schema_version === 'string' &&
        (Array.isArray(payload.n_tags) || Array.isArray(payload.c_tags))
    )
}

export function applyPrepareState(state: PrepareSequencesStateDto): RestoreOutcome[] {
    assertReadableVersion(state, 'prepare sequences file')

    const seqPrep: any = useSeqPrepStore()
    const outcomes: RestoreOutcome[] = []

    const nTags: Array<Record<string, any>> = Array.isArray(state.n_tags) ? plain(state.n_tags) : []
    const cTags: Array<Record<string, any>> = Array.isArray(state.c_tags) ? plain(state.c_tags) : []
    // Older saves had free-text additions applied to every design; they are now custom
    // tags flagged "always", outermost as before.
    const nFix = (state.n_terminal_prefix ?? '').trim()
    const cFix = (state.c_terminal_suffix ?? '').trim()
    if (nFix) {
        nTags.unshift({
            id: 'legacy-n-prefix', kind: 'custom', sequence: nFix, label: 'N-terminal prefix', always: true
        })
    }
    if (cFix) {
        cTags.push({
            id: 'legacy-c-suffix', kind: 'custom', sequence: cFix, label: 'C-terminal suffix', always: true
        })
    }
    if (Array.isArray(state.n_tags) || nFix) seqPrep.nTags = nTags
    if (Array.isArray(state.c_tags) || cFix) seqPrep.cTags = cTags
    outcomes.push({
        section: 'Tags',
        status: 'applied',
        detail: `${state.n_tags?.length ?? 0} N-terminal, ${state.c_tags?.length ?? 0} C-terminal`
    })

    restore(seqPrep, state.stop_options, STOP_FIELDS)
    restore(seqPrep, state.short_name_strategy, SHORT_NAME_FIELDS)
    outcomes.push({ section: 'Stop codons and short names', status: 'applied' })

    if (typeof state.order_name === 'string') seqPrep.exportOrderName = state.order_name
    if (typeof state.extract_chain === 'string' && state.extract_chain) {
        seqPrep.extractChain = state.extract_chain
    }
    if (typeof state.good_only === 'boolean') seqPrep.goodOnly = state.good_only
    if (typeof state.dna_mode === 'boolean') seqPrep.dnaMode = state.dna_mode

    if (state.codon_table_id) seqPrep.selectedCodonTable = state.codon_table_id
    if (state.optimization_method) seqPrep.optimizationMethod = state.optimization_method
    if (Array.isArray(state.optimization_constraints)) {
        seqPrep.optimizationConstraints = plain(state.optimization_constraints)
    }
    // Optimised DNA is still not restored: it is a function of these settings plus
    // the sequences, and stale DNA presented as current would be worse than none.
    // The bundle now records the seed and dependency versions for each row, so a
    // run can be reproduced by re-running Optimize DNA on the same versions, or
    // offline with the downloaded script and --seed-map.
    seqPrep.optimizationStale = true
    const recorded = state.tool_versions ?? {}
    const versionNote = Object.keys(recorded).length
        ? ` Recorded with ${Object.entries(recorded)
              .map(([k, v]) => `${k} ${v}`)
              .join(', ')}.`
        : ''
    outcomes.push({
        section: 'Codon optimisation',
        status: 'applied',
        detail: `Settings restored; re-run Optimize DNA to regenerate sequences.${versionNote}`
    })

    return outcomes
}
