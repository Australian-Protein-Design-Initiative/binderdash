/**
 * Prepare sequences tab: tagging, optional DNA view, exports.
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useDesignsStore } from './designs'
import {
    designsApi,
    sequencesApi,
    type CodonTableDetailResponseDto,
    type DnaOptConstraintSpecDto
} from '../webapi'
import type { Design } from '../types/store'
import {
    isoelectricPoint,
    molarExtinctionCoefficient,
    sequenceWarnings
} from '../utils/protParam'
import {
    computeShortNames,
    sanitizeShortNameSegment,
    validateShortNameRegexStrip,
    validateShortNameRegex,
    type ShortNameRowInput,
    type ShortNameStrategy
} from './shortName'

/** design_id shared by more than one row in the current prepare set. */
export const WARNING_LONG_NAME_NOT_UNIQUE = 'Long name not unique'
/** Short name matched another row before the auto `_N` suffix. */
export const WARNING_SHORT_NAME_NOT_UNIQUE = 'Short name not unique'

export type TagZone = 'n' | 'c'

export type PresetTagKind =
    | 'hisN'
    | 'hisC'
    | 'flag'
    | 'cmyc'
    | 'ha'
    | 'avi'
    | 'strep'
    | 'ctag'
    | 'snac'
    | 'tev'
    | 'linker'
    | 'stop'
    | 'custom'

/** Frozen stop codon used for every `*` in prepare-sequences DNA (preview and optimisation). */
export const FIXED_STOP_DNA = 'TAA'
/** Frozen start codon when the coding sequence begins with Met / ATG. */
export const FIXED_START_DNA = 'ATG'

/**
 * UI-level constraint types shown in the DNA Optimization panel. Most map
 * 1:1 to dnachisel specifications; `ExcludeRestrictionSite` is a convenience
 * wrapper that is serialised to `AvoidPattern` with `pattern: "<enzyme>_site"`
 * just before being sent to the backend (dnachisel recognises the `_site`
 * suffix and resolves it via Biopython's restriction table).
 */
export const OPTIMIZATION_CONSTRAINT_TYPES = [
    'ExcludeRestrictionSite',
    'EnforceGCContent',
    'AvoidHairpins',
    'AvoidPattern',
    'AvoidRareCodons',
    'UniquifyAllKmers',
    'AvoidInvertedRepeats',
    'AvoidConsecutiveCodons'
] as const

export type OptimizationConstraintType = (typeof OPTIMIZATION_CONSTRAINT_TYPES)[number]

/** Default DNA optimisation constraints, similar to the DNA optimisation/complexity rules used by Twist Biosciences for gene synthesis. */
export const DEFAULT_DNAOPT_CONSTRAINTS: DnaOptConstraintSpecDto[] = [
    { type: 'EnforceGCContent', enabled: true, params: { mini: 0.25, maxi: 0.64 } },
    { type: 'EnforceGCContent', enabled: true, params: { mini: 0.35, maxi: 0.75, window: 50 } },
    { type: 'AvoidHairpins', enabled: true, params: { stem_size: 20, hairpin_window: 48 } },
    { type: 'AvoidPattern', enabled: true, params: { pattern: 'AAAAAAAAA' } },
    { type: 'AvoidPattern', enabled: true, params: { pattern: 'TTTTTTTTT' } },
    { type: 'AvoidPattern', enabled: true, params: { pattern: 'GGGGGG' } },
    { type: 'AvoidPattern', enabled: true, params: { pattern: 'CCCCCC' } },
    { type: 'AvoidRareCodons', enabled: true, params: { min_frequency: 0.09 } },
    { type: 'UniquifyAllKmers', enabled: true, params: { k: 12 } },
    { type: 'AvoidPattern', enabled: true, params: { pattern: { type: 'RepeatedKmerPattern', params: { n_repeats: 2, k_size: 20 } } } },
    { type: 'AvoidInvertedRepeats', enabled: true, params: { min_tm: 68 } },
    { type: 'AvoidConsecutiveCodons', enabled: true, params: { codons: ['CGG', 'CGA', 'CCC'], max_run: 2 } },
    { type: 'AvoidPattern', enabled: true, params: { pattern: 'GGAGG' } },
    { type: 'AvoidPattern', enabled: true, params: { pattern: 'TAAGGAG' } }
]

/**
 * Translate UI-only constraint types (e.g. `ExcludeRestrictionSite`) into the
 * shape understood by the backend / dnachisel. Unknown types pass through so
 * future additions degrade gracefully.
 */
export function serializeConstraintForBackend(
    c: DnaOptConstraintSpecDto
): DnaOptConstraintSpecDto {
    if (c.type === 'ExcludeRestrictionSite') {
        const enzyme = typeof c.params?.enzyme === 'string' ? c.params.enzyme.trim() : ''
        return {
            type: 'AvoidPattern',
            enabled: c.enabled,
            params: enzyme ? { pattern: `${enzyme}_site` } : { pattern: '' }
        }
    }
    return c
}

export interface PlacedTag {
    id: string
    kind: PresetTagKind
    sequence: string
    label: string
}

export interface PreparedSegment {
    text: string
    cssClass: string
    style?: Record<string, string>
    /** When true, every residue in this segment stays fixed during DNA optimisation. */
    fixed?: boolean
}

export interface PreparedRow {
    row_key: string
    design_id: string
    /** Space-joined design_id, project_id, run_name for DataTable text filter. */
    design_filter_text: string
    run_id: string
    run_name: string
    project_id: string
    /** For API/cache updates (dedupe with design_id). */
    source_path: string
    tag: string
    original_sequence: string
    prepared_aa: string
    /** AA string for UI: same as prepared_aa except post-stop padding is omitted. */
    prepared_aa_display: string
    prepared_dna: string | null
    segments_aa: PreparedSegment[]
    /** Coloured AA segments for UI: omits post-stop padding only (terminal stop follows stop options). */
    segments_aa_display: PreparedSegment[]
    segments_dna: PreparedSegment[] | null
    extinction_coeff_reduced: number
    extinction_coeff_oxidized: number
    isoelectric_point: number
    warnings: string[]
    /** Twist / vendor short name (≤32 chars after strategy + dedupe). */
    short_name: string
}

/** Preset row for palette chips and prepared-sequence styling. */
export interface TagPresetDefinition {
    kind: PresetTagKind
    tag_name: string
    sequence: string
    /** UI-only rendering of the sequence (e.g. cleavage site marked with ↓). */
    display_sequence?: string
    color: string
    background: string
    foreground: string
    zones: ('n' | 'c')[]
}

export const TAG_PRESET_DEFS: readonly TagPresetDefinition[] = [
    {
        kind: 'hisN',
        tag_name: 'His-N',
        sequence: 'HHHHHHSG',
        color: '#1565c0',
        background: 'rgba(21, 101, 192, 0.12)',
        foreground: '#0d47a1',
        zones: ['n']
    },
    {
        kind: 'hisC',
        tag_name: 'His-C',
        sequence: 'GSHHHHHH',
        color: '#1565c0',
        background: 'rgba(21, 101, 192, 0.12)',
        foreground: '#0d47a1',
        zones: ['c']
    },
    {
        kind: 'flag',
        tag_name: 'FLAG',
        sequence: 'DYKDDDDK',
        color: '#2e7d32',
        background: 'rgba(46, 125, 50, 0.12)',
        foreground: '#1b5e20',
        zones: ['n', 'c']
    },
    {
        kind: 'cmyc',
        tag_name: 'cMyc',
        sequence: 'EQKLISEEDL',
        color: '#ef6c00',
        background: 'rgba(239, 108, 0, 0.12)',
        foreground: '#e65100',
        zones: ['n', 'c']
    },
    {
        kind: 'ha',
        tag_name: 'HA',
        sequence: 'YPYDVPDYA',
        color: '#7b1fa2',
        background: 'rgba(123, 31, 162, 0.1)',
        foreground: '#6a1b9a',
        zones: ['n', 'c']
    },
    {
        kind: 'avi',
        tag_name: 'AviTag',
        sequence: 'GLNDIFEAQKIEWHE',
        color: '#00838f',
        background: 'rgba(0, 131, 143, 0.12)',
        foreground: '#006064',
        zones: ['n', 'c']
    },
    {
        kind: 'strep',
        tag_name: 'Strep-tag II',
        sequence: 'WSHPQFEK',
        color: '#5e35b1',
        background: 'rgba(94, 53, 177, 0.12)',
        foreground: '#4527a0',
        zones: ['n', 'c']
    },
    {
        kind: 'ctag',
        tag_name: 'C-tag',
        sequence: 'EPEA',
        color: '#6d4c41',
        background: 'rgba(109, 76, 65, 0.12)',
        foreground: '#4e342e',
        zones: ['c']
    },
    {
        kind: 'snac',
        tag_name: 'SNAC-tag',
        sequence: 'GSHHW',
        display_sequence: 'G↓SHHW',
        color: '#c2185b',
        background: 'rgba(194, 24, 91, 0.12)',
        foreground: '#880e4f',
        zones: ['n', 'c']
    },
    {
        kind: 'tev',
        tag_name: 'TEV-site',
        sequence: 'ENLYFQS',
        display_sequence: 'ENLYFQ↓S',
        color: '#303f9f',
        background: 'rgba(48, 63, 159, 0.12)',
        foreground: '#1a237e',
        zones: ['n', 'c']
    },
    {
        kind: 'linker',
        tag_name: 'G4S',
        sequence: 'GGGGS',
        color: '#aaaaaa',
        background: 'rgba(48, 48, 48, 0.1)',
        foreground: '#aaaaaa',
        zones: ['n', 'c']
    },
    {
        kind: 'stop',
        tag_name: 'STOP*',
        sequence: '*',
        color: '#b23a3a',
        background: 'rgba(178, 58, 58, 0.15)',
        foreground: '#8b1e1e',
        zones: ['n', 'c']
    }
]

/** Sequence as shown in the UI (cleavage sites marked with ↓, e.g. SNAC `G↓SHHW`). */
export function tagSequenceDisplay(kind: PresetTagKind, sequence: string): string {
    const def = TAG_PRESET_DEFS.find(p => p.kind === kind)
    return def?.display_sequence && def.sequence === sequence ? def.display_sequence : sequence
}

export const CUSTOM_TAG_VISUAL = {
    color: '#aa0000',
    background: 'rgba(69, 90, 100, 0.1)',
    foreground: '#37474f'
} as const

function appendTerminalStopAa(
    segmentLists: PreparedSegment[][],
    exportPartLists: string[][],
    doubleStop: boolean
): void {
    const count = doubleStop ? 2 : 1
    for (const segList of segmentLists) {
        for (let i = 0; i < count; i += 1) {
            segList.push({ text: '*', cssClass: 'seq-seg-stop', fixed: true })
        }
    }
    const stopAa = doubleStop ? '**' : '*'
    for (const parts of exportPartLists) {
        parts.push(stopAa)
    }
}

function appendTerminalStopDna(
    mainDnaChunks: string[],
    mainSegChunks: PreparedSegment[][],
    _table: CodonTable,
    doubleStop: boolean
): void {
    const count = doubleStop ? 2 : 1
    for (let i = 0; i < count; i += 1) {
        mainDnaChunks.push(FIXED_STOP_DNA)
        mainSegChunks.push([{ text: FIXED_STOP_DNA, cssClass: 'seq-seg-stop', fixed: true }])
    }
}

/** Default post-stop padding (lowercase = nucleotides). */
export const DEFAULT_POST_STOP_PADDING =
    'ttgtgttgcgatagcccagtatgatattctaaggcgttacgctgatgaatattctacggaattgccataggcgttgaacgctacacggacgatacgaatt'

interface PostStopPaddingChunk {
    dna: string
    aaMixed: string
}

function paddingRequiredForMainDna(
    mainDnaLen: number,
    padTargetBp: number,
    padRaw: string,
    table: CodonTable
): boolean {
    const standardTrim = padRaw.trim()
    if (!standardTrim || padTargetBp <= 0 || mainDnaLen >= padTargetBp) {
        return false
    }
    const { dna: standardUnit } = mixedToDnaSegments(standardTrim, table, 'seq-seg-dna-body')
    return standardUnit.length > 0
}

function computePostStopPaddingChunks(
    mainDnaLen: number,
    padTargetBp: number,
    padRaw: string,
    table: CodonTable
): PostStopPaddingChunk[] {
    const standardTrim = padRaw.trim()
    if (!paddingRequiredForMainDna(mainDnaLen, padTargetBp, padRaw, table)) {
        return []
    }
    const standardUnit = mixedToDnaSegments(standardTrim, table, 'seq-seg-dna-body')
    const standardLen = standardUnit.dna.length

    const chunks: PostStopPaddingChunk[] = []
    let remaining = padTargetBp - mainDnaLen

    while (remaining >= standardLen) {
        chunks.push({ dna: standardUnit.dna, aaMixed: standardTrim })
        remaining -= standardLen
    }
    if (remaining > 0) {
        chunks.push({
            dna: standardUnit.dna.slice(0, remaining),
            aaMixed: standardUnit.dna.slice(0, remaining).toLowerCase()
        })
    }
    return chunks
}

export interface CodonTable {
    label: string
    forward: Record<string, string>
    reverse: Record<string, string>
    stop: string
}

const ECOLI_FORWARD: Record<string, string> = {
    A: 'GCT',
    R: 'CGT',
    N: 'AAC',
    D: 'GAT',
    C: 'TGC',
    Q: 'CAG',
    E: 'GAA',
    G: 'GGT',
    H: 'CAT',
    I: 'ATT',
    L: 'CTG',
    K: 'AAA',
    M: 'ATG',
    F: 'TTC',
    P: 'CCT',
    S: 'TCT',
    T: 'ACC',
    W: 'TGG',
    Y: 'TAT',
    V: 'GTT',
    '*': 'TAA',
    X: 'GCT'
}

function buildReverse(
    forward: Record<string, string>,
    primaryStop: string,
    allStopCodons?: string[]
): Record<string, string> {
    const reverse: Record<string, string> = {}
    for (const [aa, codon] of Object.entries(forward)) {
        if (aa === '*') continue
        reverse[codon.toUpperCase()] = aa
    }
    const stops =
        allStopCodons && allStopCodons.length > 0
            ? [...new Set(allStopCodons.map(s => s.toUpperCase()))]
            : [primaryStop.toUpperCase()]
    for (const sc of stops) {
        reverse[sc] = '*'
    }
    return reverse
}

/** Offline / API-failure fallback; matches prior hardcoded E. coli table. */
const FALLBACK_ECOLLI_CODON_TABLE: CodonTable = {
    label: 'E. coli',
    forward: { ...ECOLI_FORWARD },
    reverse: buildReverse(ECOLI_FORWARD, 'TAA', ['TAA', 'TAG', 'TGA']),
    stop: 'TAA'
}

function codonDetailDtoToTable(detail: CodonTableDetailResponseDto): CodonTable {
    const stops = detail.stop_codons.map(s => s.toUpperCase())
    const stop = stops[0] || 'TAA'
    const forward: Record<string, string> = {}
    for (const [aa, freqs] of Object.entries(detail.codons_by_aa)) {
        if (aa === '*') continue
        const pairs = Object.entries(freqs)
        pairs.sort((a, b) => {
            if (b[1] !== a[1]) return b[1] - a[1]
            return a[0].localeCompare(b[0])
        })
        if (pairs.length > 0) {
            forward[aa] = pairs[0][0].toUpperCase()
        }
    }
    if (!forward.X) {
        forward.X = forward.A || forward.L || 'GCT'
    }
    forward['*'] = stop
    const reverse = buildReverse(forward, stop, stops)
    return { label: detail.label, forward, reverse, stop }
}

const N_TERMINAL_SEGMENT_STYLE: Record<string, string> = {
    display: 'inline-block',
    boxDecorationBreak: 'clone',
    WebkitBoxDecorationBreak: 'clone',
    fontWeight: '600',
    padding: '0.12em 0.28em',
    borderRadius: '4px',
    border: '1px solid #00796b',
    backgroundColor: '#b2dfdb',
    color: '#004d40'
}

const C_TERMINAL_SEGMENT_STYLE: Record<string, string> = {
    display: 'inline-block',
    boxDecorationBreak: 'clone',
    WebkitBoxDecorationBreak: 'clone',
    fontWeight: '600',
    padding: '0.12em 0.28em',
    borderRadius: '4px',
    border: '1px solid #ad1457',
    backgroundColor: '#f8bbd0',
    color: '#880e4f'
}

const VALID_NUC = new Set(['a', 'c', 'g', 't'])

export function validateMixedSequence(s: string, fieldName: string): string | null {
    for (const ch of s) {
        if (ch >= 'A' && ch <= 'Z') continue
        if (ch === '*') continue
        if (VALID_NUC.has(ch)) continue
        if (/\s/.test(ch)) continue
        return `${fieldName}: invalid character '${ch}'`
    }
    return null
}

let tagIdCounter = 0
function nextTagId(): string {
    tagIdCounter += 1
    return `t-${tagIdCounter}`
}

function getRawSequence(d: Design): string {
    const fields = ['Sequence', 'sequence', 'binder_sequence', 'binder_seq', 'seq'] as const
    for (const f of fields) {
        const v = (d as Record<string, unknown>)[f]
        if (v != null && String(v).trim()) return String(v).trim()
    }
    return ''
}

function segmentClass(kind: PresetTagKind): string {
    if (kind === 'hisN' || kind === 'hisC') return 'seq-seg-his'
    if (kind === 'flag') return 'seq-seg-flag'
    if (kind === 'cmyc') return 'seq-seg-cmyc'
    if (kind === 'ha') return 'seq-seg-ha'
    if (kind === 'avi') return 'seq-seg-avi'
    if (kind === 'strep') return 'seq-seg-strep'
    if (kind === 'ctag') return 'seq-seg-ctag'
    if (kind === 'snac') return 'seq-seg-snac'
    if (kind === 'tev') return 'seq-seg-tev'
    if (kind === 'linker') return 'seq-seg-linker'
    if (kind === 'stop') return 'seq-seg-stop'
    return 'seq-seg-custom'
}

export function tagPresetVisual(kind: PresetTagKind): {
    borderColor: string
    background: string
    color: string
} {
    const def = TAG_PRESET_DEFS.find(p => p.kind === kind)
    if (def) {
        return { borderColor: def.color, background: def.background, color: def.foreground }
    }
    return {
        borderColor: CUSTOM_TAG_VISUAL.color,
        background: CUSTOM_TAG_VISUAL.background,
        color: CUSTOM_TAG_VISUAL.foreground
    }
}

/** Same chrome for outlined palette buttons and tag chips (see `TAG_PRESET_DEFS`). */
export function tagPresetChromeStyle(kind: PresetTagKind): Record<string, string> {
    const v = tagPresetVisual(kind)
    return {
        borderColor: v.borderColor,
        borderWidth: '1px',
        borderStyle: 'solid',
        backgroundColor: v.background,
        color: v.color
    }
}

/**
 * CSS variables for preset tag chips. `App.vue` uses `!important` on `.p-chip` / `.p-component *`;
 * `PrepareSequencesView` applies these vars with matching `!important` so chips match palette buttons.
 */
export function tagPresetChipCssVars(kind: PresetTagKind): Record<string, string> {
    const v = tagPresetVisual(kind)
    return {
        '--ps-chip-border': v.borderColor,
        '--ps-chip-bg': v.background,
        '--ps-chip-fg': v.color
    }
}

function segmentStyleForPresetKind(kind: PresetTagKind): Record<string, string> {
    const v = tagPresetVisual(kind)
    return {
        borderWidth: '1px',
        borderStyle: 'solid',
        borderColor: v.borderColor,
        backgroundColor: v.background,
        color: v.color,
        fontWeight: '600',
        padding: '0.1em 0.2em',
        borderRadius: '3px'
    }
}

/** Lowercase, alphanumerics only, other chars → single underscores, trimmed edges. */
export function sanitizeExportOrderNameSegment(raw: string): string {
    const t = raw.trim().toLowerCase()
    if (!t) return ''
    const cleaned = t
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '')
    return cleaned.length > 120 ? cleaned.slice(0, 120) : cleaned
}

/** `YYYYMMDD_HHmmss` in local time, safe for filenames. */
export function formatPreparedExportDatestamp(d = new Date()): string {
    const y = d.getFullYear()
    const mo = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const h = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    const s = String(d.getSeconds()).padStart(2, '0')
    return `${y}${mo}${day}_${h}${mi}${s}`
}

/** `{sanitized_order_or_prepared_sequences}_{datestamp}` — no extension. */
export function preparedExportBasename(orderNameRaw: string): string {
    const seg = sanitizeExportOrderNameSegment(orderNameRaw)
    const prefix = seg || 'prepared_sequences'
    return `${prefix}_${formatPreparedExportDatestamp()}`
}

function isLowerNuc(c: string): boolean {
    return VALID_NUC.has(c)
}

function isUpperAa(c: string): boolean {
    return (c >= 'A' && c <= 'Z') || c === '*'
}

type MixedRun = { type: 'upper' | 'lower'; text: string }

function splitMixedRuns(mixed: string): MixedRun[] {
    const runs: MixedRun[] = []
    let i = 0
    const n = mixed.length
    while (i < n) {
        const c = mixed[i]
        if (/\s/.test(c)) {
            i += 1
            continue
        }
        const lower = isLowerNuc(c)
        const upper = isUpperAa(c)
        if (!lower && !upper) {
            i += 1
            continue
        }
        const start = i
        if (lower) {
            while (i < n && isLowerNuc(mixed[i])) i += 1
            runs.push({ type: 'lower', text: mixed.slice(start, i) })
        } else {
            while (i < n && isUpperAa(mixed[i])) i += 1
            runs.push({ type: 'upper', text: mixed.slice(start, i) })
        }
    }
    return runs
}

function mixedToAaSegments(
    mixed: string,
    cssClass: string,
    style: Record<string, string> | undefined,
    codonTable: CodonTable
): { segments: PreparedSegment[]; exportText: string } {
    const segments: PreparedSegment[] = []
    let exportText = ''
    const runs = splitMixedRuns(mixed)
    for (const run of runs) {
        if (run.type === 'upper') {
            if (!run.text) continue
            let buf = ''
            const flushBuf = () => {
                if (!buf) return
                const seg: PreparedSegment = style
                    ? { text: buf, cssClass, style: { ...style } }
                    : { text: buf, cssClass }
                segments.push(seg)
                exportText += buf
                buf = ''
            }
            for (const ch of run.text) {
                if (ch === '*') {
                    flushBuf()
                    segments.push({ text: '*', cssClass: 'seq-seg-stop', fixed: true })
                    exportText += '*'
                } else {
                    buf += ch
                }
            }
            flushBuf()
            continue
        }
        const low = run.text
        const full = Math.floor(low.length / 3)
        for (let t = 0; t < full; t += 1) {
            const tri = low.slice(t * 3, t * 3 + 3).toUpperCase()
            const aa = codonTable.reverse[tri] ?? 'X'
            const ch = aa === '*' ? '*' : aa
            segments.push({
                text: ch,
                cssClass: ch === '*' ? 'seq-seg-stop' : cssClass,
                style: ch === '*' ? undefined : style ? { ...style } : undefined,
                fixed: ch === '*' ? true : undefined
            })
            exportText += ch
        }
        const rem = low.slice(full * 3)
        if (rem) {
            segments.push({ text: rem, cssClass: 'seq-seg-nuc-remainder' })
            exportText += '-'.repeat(rem.length)
        }
    }
    return { segments, exportText }
}

function literalAaToDnaSegments(
    aa: string,
    codonTable: CodonTable,
    bodyCssClass = 'seq-seg-dna-body',
    bodyStyle?: Record<string, string>
): { dna: string; segments: PreparedSegment[] } {
    let dna = ''
    const segments: PreparedSegment[] = []
    let bodyBuf = ''
    const flushBody = () => {
        if (bodyBuf) {
            const seg: PreparedSegment = bodyStyle
                ? { text: bodyBuf, cssClass: bodyCssClass, style: { ...bodyStyle } }
                : { text: bodyBuf, cssClass: bodyCssClass }
            segments.push(seg)
            bodyBuf = ''
        }
    }
    for (const ch of aa) {
        if (/\s/.test(ch)) continue
        if (ch === '*') {
            flushBody()
            dna += FIXED_STOP_DNA
            segments.push({ text: FIXED_STOP_DNA, cssClass: 'seq-seg-stop', fixed: true })
        } else {
            const u = ch.toUpperCase()
            if (u >= 'A' && u <= 'Z') {
                const codon = codonTable.forward[u] || codonTable.forward['X']
                dna += codon
                bodyBuf += codon
            }
        }
    }
    flushBody()
    return { dna, segments }
}

function mixedToDnaSegments(
    mixed: string,
    codonTable: CodonTable,
    bodyCssClass: string,
    bodyStyle?: Record<string, string>
): { dna: string; segments: PreparedSegment[] } {
    let dna = ''
    const segments: PreparedSegment[] = []
    let bodyBuf = ''
    const flushBody = () => {
        if (bodyBuf) {
            const seg: PreparedSegment = bodyStyle
                ? { text: bodyBuf, cssClass: bodyCssClass, style: { ...bodyStyle } }
                : { text: bodyBuf, cssClass: bodyCssClass }
            segments.push(seg)
            bodyBuf = ''
        }
    }
    const runs = splitMixedRuns(mixed)
    for (const run of runs) {
        if (run.type === 'upper') {
            const sub = literalAaToDnaSegments(run.text, codonTable, bodyCssClass, bodyStyle)
            dna += sub.dna
            for (const s of sub.segments) {
                if (s.cssClass === 'seq-seg-stop') {
                    flushBody()
                    segments.push(s)
                } else if (s.cssClass === bodyCssClass) {
                    bodyBuf += s.text
                }
            }
            continue
        }
        const low = run.text
        for (let i = 0; i < low.length; i += 3) {
            const tri = low.slice(i, i + 3)
            if (tri.length < 3) {
                const up = tri.toUpperCase()
                dna += up
                bodyBuf += up
                continue
            }
            const up = tri.toUpperCase()
            if (codonTable.reverse[up] === '*') {
                flushBody()
                dna += up
                segments.push({ text: up, cssClass: 'seq-seg-stop', fixed: true })
            } else {
                dna += up
                bodyBuf += up
            }
        }
    }
    flushBody()
    return { dna, segments }
}

function mergeDnaSegments(segments: PreparedSegment[], bodyClass: string): PreparedSegment[] {
    const out: PreparedSegment[] = []
    let buf = ''
    let bufStyle: Record<string, string> | undefined
    const flush = () => {
        if (buf) {
            const seg: PreparedSegment = bufStyle
                ? { text: buf, cssClass: bodyClass, style: { ...bufStyle } }
                : { text: buf, cssClass: bodyClass }
            out.push(seg)
            buf = ''
            bufStyle = undefined
        }
    }
    for (const s of segments) {
        if (s.cssClass === 'seq-seg-stop' || s.fixed) {
            flush()
            out.push(s)
        } else {
            buf += s.text
            if (!bufStyle && s.style) {
                bufStyle = s.style
            }
        }
    }
    flush()
    return out
}

/** Split binder-core AA so each `*` is its own fixed stop segment. */
export function splitCoreAaSegments(core: string): PreparedSegment[] {
    const segments: PreparedSegment[] = []
    let buf = ''
    const flush = () => {
        if (!buf) return
        segments.push({ text: buf, cssClass: 'seq-seg-core' })
        buf = ''
    }
    for (const ch of core) {
        if (ch === '*') {
            flush()
            segments.push({ text: '*', cssClass: 'seq-seg-stop', fixed: true })
        } else {
            buf += ch
        }
    }
    flush()
    return segments
}

const IN_FRAME_TAG_CLASSES = new Set([
    'seq-seg-his',
    'seq-seg-flag',
    'seq-seg-cmyc',
    'seq-seg-ha',
    'seq-seg-avi',
    'seq-seg-strep',
    'seq-seg-ctag',
    'seq-seg-snac',
    'seq-seg-tev',
    'seq-seg-linker',
    'seq-seg-stop'
])

/**
 * Nucleotide offset (0, 1 or 2) at which design and preset-tag codons begin.
 *
 * A custom addition is mixed: uppercase residues are codons (3 nt) and a
 * leftover lowercase run (`seq-seg-nuc-remainder`) is raw bases. That leftover
 * is what shifts the reading frame; the design and preset tags share whatever
 * frame it leaves. When there is no design core, the first preset tag anchors it.
 */
export function codingFrameOffset(segments: PreparedSegment[]): number {
    const anchorAt = (classes: Set<string>): number | null => {
        let nt = 0
        for (const seg of segments) {
            if (seg.cssClass === 'seq-seg-nuc-remainder') {
                nt += seg.text.length
                continue
            }
            if (classes.has(seg.cssClass) && seg.text.length > 0) {
                return ((nt % 3) + 3) % 3
            }
            nt += seg.text.length * 3
        }
        return null
    }
    const fromCore = anchorAt(new Set(['seq-seg-core']))
    if (fromCore !== null) return fromCore
    return anchorAt(IN_FRAME_TAG_CLASSES) ?? 0
}

/** Expand segment `fixed` flags to a per-residue mask matching the concatenated AA. */
export function expandFixedFromSegments(segments: PreparedSegment[]): {
    aa: string
    fixed: boolean[]
} {
    let aa = ''
    const fixed: boolean[] = []
    for (const seg of segments) {
        for (const ch of seg.text) {
            aa += ch
            fixed.push(!!seg.fixed)
        }
    }
    return { aa, fixed }
}

/**
 * When enabled and the coding AA starts with Met, split that residue into its own
 * fixed segment so DNA optimisation keeps the 5' codon as ATG.
 * Always returns a new array so callers can safely replace the source list in place.
 */
export function applyFixedStartMethionine(
    segments: PreparedSegment[],
    enabled: boolean
): PreparedSegment[] {
    if (!enabled || segments.length === 0) return segments.slice()
    const first = segments[0]
    if (!first.text || first.text[0] !== 'M') return segments.slice()
    if (first.text === 'M') {
        if (first.fixed) return segments.slice()
        return [{ ...first, fixed: true }, ...segments.slice(1)]
    }
    const restText = first.text.slice(1)
    const out: PreparedSegment[] = [
        {
            text: 'M',
            cssClass: first.cssClass,
            style: first.style ? { ...first.style } : undefined,
            fixed: true
        }
    ]
    if (restText) {
        out.push({
            text: restText,
            cssClass: first.cssClass,
            style: first.style ? { ...first.style } : undefined,
            fixed: first.fixed
        })
    }
    out.push(...segments.slice(1))
    return out
}

/**
 * When enabled and the coding DNA starts with ATG, carve that codon into a fixed segment.
 * Keeps the original lead segment chrome (N-terminal / tag colours) so AA and NT views match.
 */
export function applyFixedStartAtgDna(
    mainDna: string,
    mainSegChunks: PreparedSegment[][],
    enabled: boolean
): { mainDna: string; mainSegChunks: PreparedSegment[][] } {
    if (!enabled || mainDna.length < 3) {
        return { mainDna, mainSegChunks }
    }
    if (mainDna.slice(0, 3).toUpperCase() !== FIXED_START_DNA) {
        return { mainDna, mainSegChunks }
    }
    const dna = FIXED_START_DNA + mainDna.slice(3)
    const flat: PreparedSegment[] = []
    for (const chunk of mainSegChunks) {
        flat.push(...chunk)
    }
    const joined = flat.map(s => s.text).join('')
    if (joined.length < 3 || joined.slice(0, 3).toUpperCase() !== FIXED_START_DNA) {
        return { mainDna: dna, mainSegChunks }
    }
    const lead = flat[0]
    const leadCssClass = lead?.cssClass || 'seq-seg-dna-body'
    const leadStyle = lead?.style ? { ...lead.style } : undefined
    // Drop the first 3 nt from existing segments, then prepend a fixed ATG segment.
    let skip = 3
    const rest: PreparedSegment[] = []
    for (const seg of flat) {
        if (skip <= 0) {
            rest.push(seg)
            continue
        }
        if (seg.text.length <= skip) {
            skip -= seg.text.length
            continue
        }
        rest.push({
            ...seg,
            text: seg.text.slice(skip)
        })
        skip = 0
    }
    return {
        mainDna: dna,
        mainSegChunks: [
            [
                {
                    text: FIXED_START_DNA,
                    cssClass: leadCssClass,
                    style: leadStyle,
                    fixed: true
                }
            ],
            rest
        ]
    }
}

export const useSeqPrepStore = defineStore('seqPrep', () => {
    const nTags = ref<PlacedTag[]>([])
    const cTags = ref<PlacedTag[]>([])
    const nTerminalPrefix = ref('')
    const cTerminalSuffix = ref('')
    const includeStopForNTagged = ref(true)
    const includeStopForCTagged = ref(true)
    const useDoubleStop = ref(false)
    /** When true, a leading Met / ATG in the coding construct stays fixed during DNA opt. */
    const dontModifyStartAtg = ref(true)

    const goodOnly = ref(false)
    const extractChain = ref('B')
    const dnaMode = ref(false)
    /** AA view/export: when false, omit post-stop padding (NT view ignores). */
    const showPostStopPadding = ref(true)
    const postStopPadding = ref(DEFAULT_POST_STOP_PADDING)
    const postStopPadUpToNucleotideLength = ref<number | null>(300)
    const onlyUseNTerminalTagWhenPaddingRequired = ref(false)
    const onlyUseCTerminalTagWhenPaddingRequired = ref(false)
    const minDnaFragmentLength = ref(300)
    const customTagInput = ref('')
    const exportOrderName = ref('')
    const extracting = ref(false)
    const codonTableOptions = ref<{ label: string; value: string }[]>([])
    const codonTablesById = ref<Record<string, CodonTable>>({})
    const codonTablesListLoading = ref(false)
    const codonTablesDetailLoading = ref(false)
    const selectedCodonTable = ref('')
    let codonTableListLoaded = false
    const codonDetailInflight = new Map<string, Promise<void>>()
    let codonDetailLoadCount = 0

    const activeCodonTable = computed((): CodonTable => {
        const id = selectedCodonTable.value
        const t = id ? codonTablesById.value[id] : undefined
        return t ?? FALLBACK_ECOLLI_CODON_TABLE
    })

    async function fetchCodonTableDetail(tableId: string): Promise<void> {
        if (!tableId || codonTablesById.value[tableId]) return
        const existing = codonDetailInflight.get(tableId)
        if (existing) {
            await existing
            return
        }
        const run = (async () => {
            codonDetailLoadCount += 1
            codonTablesDetailLoading.value = true
            try {
                const d = await sequencesApi.getCodonTable(tableId)
                const table = codonDetailDtoToTable(d)
                const next = { ...codonTablesById.value, [tableId]: table }
                if (d.value !== tableId) {
                    next[d.value] = table
                }
                codonTablesById.value = next
            } catch {
                codonTablesById.value = {
                    ...codonTablesById.value,
                    [tableId]: FALLBACK_ECOLLI_CODON_TABLE
                }
            } finally {
                codonDetailLoadCount -= 1
                codonTablesDetailLoading.value = codonDetailLoadCount > 0
            }
        })()
        codonDetailInflight.set(tableId, run)
        try {
            await run
        } finally {
            codonDetailInflight.delete(tableId)
        }
    }

    async function ensureCodonTablesLoaded(): Promise<void> {
        if (!codonTableListLoaded) {
            codonTablesListLoading.value = true
            try {
                const res = await sequencesApi.listCodonTables()
                codonTableOptions.value = res.items
                codonTableListLoaded = true
                const preferred = res.items.find(i => i.value === 'e_coli_316407')
                if (
                    !selectedCodonTable.value ||
                    !res.items.some(i => i.value === selectedCodonTable.value)
                ) {
                    selectedCodonTable.value = preferred?.value ?? res.items[0]?.value ?? ''
                }
            } catch {
                codonTableOptions.value = [{ label: 'E. coli (offline)', value: 'e_coli_316407' }]
                codonTablesById.value = { e_coli_316407: FALLBACK_ECOLLI_CODON_TABLE }
                selectedCodonTable.value = 'e_coli_316407'
                codonTableListLoaded = true
            } finally {
                codonTablesListLoading.value = false
            }
        }
    }

    watch(selectedCodonTable, id => {
        if (!id) return
        void fetchCodonTableDetail(id)
    })

    /** Twist-style cap: auto short-name strategy when prepare set design_ids are all within this length. */
    const SHORT_NAME_AUTO_DESIGN_ID_LEN = 32

    let applyingAutoShortNameStrategy = false
    const shortNameStrategyAutoManaged = ref(true)

    const shortNameKind = ref<ShortNameStrategy['kind']>('none')
    const shortNameMaxLen = ref(32)
    const shortNameRegexPattern = ref('^batch-[0-9]')
    const shortNameRegexReplacement = ref('')
    const shortNameRegexFlags = ref('g')
    const shortNameSplitDelimiter = ref('_')
    const shortNameSplitIndices = ref('1,2,3')
    const shortNameSplitAddPrefix = ref('')
    const shortNameSplitAddSuffix = ref('')
    const shortNameSplitAddHash = ref(false)
    const shortNamePatternPrefix = ref('design')
    const shortNamePatternUidLength = ref(5)
    const shortNamePatternNumberPad = ref(0)
    const shortNameSmartHashLen = ref(5)
    const shortNameSmartStemIncludeHash = ref(true)
    const shortNameSmartStemIncludeIndex = ref(false)
    const shortNameSmartStemRemoveCommonPrefix = ref(false)
    const shortNameSmartStemRemoveCommonSuffix = ref(true)
    const shortNameSmartStemAddPrefix = ref('')
    const shortNameSmartStemAddSuffix = ref('')
    const shortNameStripPrefixRegex = ref('^batch-\\d+_')
    const shortNameStripSuffixRegex = ref('')
    const shortNameStripNewPrefix = ref('')

    const effectiveShortNameStrategy = computed((): ShortNameStrategy => {
        const k = shortNameKind.value
        if (k === 'regex') {
            return {
                kind: 'regex',
                pattern: shortNameRegexPattern.value,
                replacement: shortNameRegexReplacement.value,
                flags: shortNameRegexFlags.value
            }
        }
        if (k === 'splitTake') {
            const parts = shortNameSplitIndices.value
                .split(/[,\s]+/)
                .map(s => parseInt(s.trim(), 10))
                .filter(n => Number.isFinite(n) && n > 0)
            return {
                kind: 'splitTake',
                delimiter: shortNameSplitDelimiter.value || '_',
                indices: parts.length > 0 ? parts : [1, 2, 3],
                addPrefix: shortNameSplitAddPrefix.value,
                addSuffix: shortNameSplitAddSuffix.value,
                addHash: shortNameSplitAddHash.value,
                hashLen: shortNameSmartHashLen.value
            }
        }
        if (k === 'pattern') {
            return {
                kind: 'pattern',
                prefix: shortNamePatternPrefix.value,
                uidLength: shortNamePatternUidLength.value,
                numberPad: shortNamePatternNumberPad.value
            }
        }
        if (k === 'smartStemHash') {
            return {
                kind: 'smartStemHash',
                includeHash: shortNameSmartStemIncludeHash.value,
                hashLen: shortNameSmartHashLen.value,
                includeIndex: shortNameSmartStemIncludeIndex.value,
                removeCommonPrefix: shortNameSmartStemRemoveCommonPrefix.value,
                removeCommonSuffix: shortNameSmartStemRemoveCommonSuffix.value,
                addPrefix: shortNameSmartStemAddPrefix.value,
                addSuffix: shortNameSmartStemAddSuffix.value
            }
        }
        if (k === 'smartRegexStrip') {
            return {
                kind: 'smartRegexStrip',
                prefixPattern: shortNameStripPrefixRegex.value,
                suffixPattern: shortNameStripSuffixRegex.value,
                newPrefix: shortNameStripNewPrefix.value,
                hashLen: shortNameSmartHashLen.value
            }
        }
        return { kind: 'none' }
    })

    const validationErrors = computed((): string[] => {
        const errs: string[] = []
        const strat = effectiveShortNameStrategy.value
        const reErr = validateShortNameRegex(strat)
        if (reErr) errs.push(reErr)
        const stripErr = validateShortNameRegexStrip(strat)
        if (stripErr) errs.push(stripErr)
        for (const t of [...nTags.value, ...cTags.value]) {
            if (t.kind === 'custom') {
                const e = validateMixedSequence(t.sequence, `Tag "${t.label}"`)
                if (e) errs.push(e)
            }
        }
        const fields = [
            [nTerminalPrefix.value, 'N-terminal prefix'],
            [cTerminalSuffix.value, 'C-terminal suffix']
        ] as const
        for (const [val, name] of fields) {
            const e = validateMixedSequence(val.trim(), name)
            if (e) errs.push(e)
        }
        const padTrim = postStopPadding.value.trim()
        const padTargetVal = postStopPadUpToNucleotideLength.value
        const usePadTarget =
            padTargetVal != null && Number.isFinite(padTargetVal) && padTargetVal > 0
        if (usePadTarget) {
            const e = validateMixedSequence(padTrim, 'Post-stop padding')
            if (e) errs.push(e)
            const { dna: padUnit } = mixedToDnaSegments(padTrim, activeCodonTable.value, 'seq-seg-dna-body')
            if (padUnit.length === 0) {
                errs.push(
                    'Post-stop padding: must expand to at least one nucleotide to pad to a target length'
                )
            }
        }
        return errs
    })

    const canDownload = computed(() => validationErrors.value.length === 0)

    const presetOptionsN = computed(() => TAG_PRESET_DEFS.filter(d => d.zones.includes('n')))

    const presetOptionsC = computed(() => TAG_PRESET_DEFS.filter(d => d.zones.includes('c')))

    const inputDesigns = computed((): Design[] => {
        const ds = useDesignsStore()
        const sel = ds.selectedDesigns
        let rows: Design[] =
            sel.length > 0 ? [...sel] : [...ds.filteredDesigns]
        if (goodOnly.value) {
            rows = rows.filter(d => d.good === true)
        }
        return rows
    })

    const prepareSetShortNameFingerprint = computed(() =>
        [...inputDesigns.value]
            .map(d => {
                const sp = String((d as Record<string, unknown>).source_path ?? '')
                return `${d.run_id}\x1f${d.design_id}\x1f${sp}`
            })
            .sort((a, b) => a.localeCompare(b))
            .join('\x1e')
    )

    function applyAutoShortNameStrategyIfManaged(): void {
        if (!shortNameStrategyAutoManaged.value) return
        const rows = inputDesigns.value
        if (rows.length === 0) return
        const allWithin = rows.every(
            d => String(d.design_id ?? '').length <= SHORT_NAME_AUTO_DESIGN_ID_LEN
        )
        const next: ShortNameStrategy['kind'] = allWithin ? 'none' : 'smartStemHash'
        if (shortNameKind.value === next) return
        applyingAutoShortNameStrategy = true
        shortNameKind.value = next
        applyingAutoShortNameStrategy = false
    }

    watch(
        prepareSetShortNameFingerprint,
        () => {
            applyAutoShortNameStrategyIfManaged()
        },
        { immediate: true }
    )

    watch(shortNameKind, () => {
        if (applyingAutoShortNameStrategy) return
        shortNameStrategyAutoManaged.value = false
    })

    function appendTagsAa(
        tags: PlacedTag[],
        segmentsAa: PreparedSegment[],
        aaExportParts: string[],
        table: CodonTable
    ) {
        for (const t of tags) {
            if (!t.sequence) continue
            if (t.kind === 'stop') {
                segmentsAa.push({ text: '*', cssClass: 'seq-seg-stop', fixed: true })
                aaExportParts.push('*')
                continue
            }
            if (t.kind === 'custom') {
                const { segments, exportText } = mixedToAaSegments(
                    t.sequence,
                    segmentClass(t.kind),
                    segmentStyleForPresetKind(t.kind),
                    table
                )
                segmentsAa.push(...segments)
                aaExportParts.push(exportText)
            } else {
                segmentsAa.push({
                    text: t.sequence,
                    cssClass: segmentClass(t.kind),
                    style: segmentStyleForPresetKind(t.kind)
                })
                aaExportParts.push(t.sequence)
            }
        }
    }

    function appendTagsDna(
        tags: PlacedTag[],
        dnaParts: string[],
        segParts: PreparedSegment[][],
        table: CodonTable
    ) {
        for (const t of tags) {
            if (!t.sequence) continue
            if (t.kind === 'stop') {
                dnaParts.push(FIXED_STOP_DNA)
                segParts.push([{ text: FIXED_STOP_DNA, cssClass: 'seq-seg-stop', fixed: true }])
                continue
            }
            const tagCssClass = segmentClass(t.kind)
            const tagStyle = segmentStyleForPresetKind(t.kind)
            if (t.kind === 'custom') {
                const { dna, segments } = mixedToDnaSegments(t.sequence, table, tagCssClass, tagStyle)
                dnaParts.push(dna)
                segParts.push(mergeDnaSegments(segments, tagCssClass))
            } else {
                const { dna, segments } = literalAaToDnaSegments(t.sequence, table, tagCssClass, tagStyle)
                dnaParts.push(dna)
                segParts.push(segments)
            }
        }
    }

    function resolveIncludeNTags(
        tagCol: string,
        mainDnaLenWithoutTerminalTags: number,
        usePostStopPadTarget: boolean,
        padRaw: string,
        padTargetBp: number,
        table: CodonTable
    ): boolean {
        if (tagCol !== 'N') return false
        if (!onlyUseNTerminalTagWhenPaddingRequired.value) return true
        if (!usePostStopPadTarget) return false
        return paddingRequiredForMainDna(
            mainDnaLenWithoutTerminalTags,
            padTargetBp,
            padRaw,
            table
        )
    }

    function resolveIncludeCTags(
        tagCol: string,
        mainDnaLenWithoutTerminalTags: number,
        usePostStopPadTarget: boolean,
        padRaw: string,
        padTargetBp: number,
        table: CodonTable
    ): boolean {
        if (tagCol !== 'C') return false
        if (!onlyUseCTerminalTagWhenPaddingRequired.value) return true
        if (!usePostStopPadTarget) return false
        return paddingRequiredForMainDna(
            mainDnaLenWithoutTerminalTags,
            padTargetBp,
            padRaw,
            table
        )
    }

    function buildMainDnaForRow(
        table: CodonTable,
        nFix: string,
        cFix: string,
        tagCol: string,
        core: string,
        includeNTags: boolean,
        includeCTags: boolean
    ): { mainDna: string; mainSegChunks: PreparedSegment[][] } {
        const mainDnaChunks: string[] = []
        const mainSegChunks: PreparedSegment[][] = []

        if (nFix) {
            const { dna, segments } = mixedToDnaSegments(
                nFix,
                table,
                'seq-seg-nfix',
                { ...N_TERMINAL_SEGMENT_STYLE }
            )
            mainDnaChunks.push(dna)
            mainSegChunks.push(mergeDnaSegments(segments, 'seq-seg-nfix'))
        }
        if (tagCol === 'N' && includeNTags) {
            appendTagsDna(nTags.value, mainDnaChunks, mainSegChunks, table)
        }
        {
            const { dna, segments } = literalAaToDnaSegments(core, table)
            mainDnaChunks.push(dna)
            mainSegChunks.push(mergeDnaSegments(segments, 'seq-seg-dna-body'))
        }
        if (tagCol === 'C' && includeCTags) {
            appendTagsDna(cTags.value, mainDnaChunks, mainSegChunks, table)
        }
        if (cFix) {
            const { dna, segments } = mixedToDnaSegments(
                cFix,
                table,
                'seq-seg-cfix',
                { ...C_TERMINAL_SEGMENT_STYLE }
            )
            mainDnaChunks.push(dna)
            mainSegChunks.push(mergeDnaSegments(segments, 'seq-seg-cfix'))
        }
        if (
            (tagCol === 'N' && includeStopForNTagged.value) ||
            (tagCol === 'C' && includeStopForCTagged.value)
        ) {
            appendTerminalStopDna(mainDnaChunks, mainSegChunks, table, useDoubleStop.value)
        }

        return { mainDna: mainDnaChunks.join(''), mainSegChunks }
    }

    function appendPreparedBodyAa(
        table: CodonTable,
        tagCol: string,
        nFix: string,
        cFix: string,
        core: string,
        includeNTags: boolean,
        includeCTags: boolean,
        segmentsAa: PreparedSegment[],
        segmentsAaDisplay: PreparedSegment[],
        aaExportParts: string[],
        aaExportPartsDisplay: string[]
    ): void {
        if (nFix) {
            const { segments, exportText } = mixedToAaSegments(
                nFix,
                'seq-seg-nfix',
                { ...N_TERMINAL_SEGMENT_STYLE },
                table
            )
            segmentsAa.push(...segments)
            segmentsAaDisplay.push(...segments)
            aaExportParts.push(exportText)
            aaExportPartsDisplay.push(exportText)
        }
        if (tagCol === 'N' && includeNTags) {
            appendTagsAa(nTags.value, segmentsAa, aaExportParts, table)
            appendTagsAa(nTags.value, segmentsAaDisplay, aaExportPartsDisplay, table)
        }
        {
            const coreSegs = splitCoreAaSegments(core)
            segmentsAa.push(...coreSegs)
            segmentsAaDisplay.push(...coreSegs)
            aaExportParts.push(core)
            aaExportPartsDisplay.push(core)
        }
        if (tagCol === 'C' && includeCTags) {
            appendTagsAa(cTags.value, segmentsAa, aaExportParts, table)
            appendTagsAa(cTags.value, segmentsAaDisplay, aaExportPartsDisplay, table)
        }
        if (cFix) {
            const { segments, exportText } = mixedToAaSegments(
                cFix,
                'seq-seg-cfix',
                { ...C_TERMINAL_SEGMENT_STYLE },
                table
            )
            segmentsAa.push(...segments)
            segmentsAaDisplay.push(...segments)
            aaExportParts.push(exportText)
            aaExportPartsDisplay.push(exportText)
        }
        if (
            (tagCol === 'N' && includeStopForNTagged.value) ||
            (tagCol === 'C' && includeStopForCTagged.value)
        ) {
            appendTerminalStopAa(
                [segmentsAa, segmentsAaDisplay],
                [aaExportParts, aaExportPartsDisplay],
                useDoubleStop.value
            )
        }
    }

    const preparedRowsInternal = computed((): Omit<PreparedRow, 'short_name'>[] => {
        const table = activeCodonTable.value
        const nFix = nTerminalPrefix.value.trim()
        const cFix = cTerminalSuffix.value.trim()
        const padRaw = postStopPadding.value.trim()
        const padTargetVal = postStopPadUpToNucleotideLength.value
        const usePostStopPadTarget =
            padTargetVal != null && Number.isFinite(padTargetVal) && padTargetVal > 0
        const padTargetBp = usePostStopPadTarget ? Math.floor(Number(padTargetVal)) : 0

        return inputDesigns.value.map((d): Omit<PreparedRow, 'short_name'> => {
            const raw = getRawSequence(d)
            const core = raw.replace(/\*+$/g, '').trim()
            const tagCol = String((d as Record<string, unknown>).tag ?? '')
                .trim()
                .toUpperCase()

            const segmentsAa: PreparedSegment[] = []
            const segmentsAaDisplay: PreparedSegment[] = []
            const aaExportParts: string[] = []
            const aaExportPartsDisplay: string[] = []

            const bodyWithoutTerminalTags = buildMainDnaForRow(
                table,
                nFix,
                cFix,
                tagCol,
                core,
                false,
                false
            )
            const probeLen = bodyWithoutTerminalTags.mainDna.length
            const includeNTags = resolveIncludeNTags(
                tagCol,
                probeLen,
                usePostStopPadTarget,
                padRaw,
                padTargetBp,
                table
            )
            const includeCTags = resolveIncludeCTags(
                tagCol,
                probeLen,
                usePostStopPadTarget,
                padRaw,
                padTargetBp,
                table
            )

            appendPreparedBodyAa(
                table,
                tagCol,
                nFix,
                cFix,
                core,
                includeNTags,
                includeCTags,
                segmentsAa,
                segmentsAaDisplay,
                aaExportParts,
                aaExportPartsDisplay
            )

            const freezeStart = dontModifyStartAtg.value
            const segmentsAaFixed = applyFixedStartMethionine(segmentsAa, freezeStart)
            const segmentsAaDisplayFixed = applyFixedStartMethionine(
                segmentsAaDisplay,
                freezeStart
            )

            const needMainDnaForPad =
                dnaMode.value || (usePostStopPadTarget && padRaw.length > 0)
            let mainDna = ''
            let mainSegChunks: PreparedSegment[][] = []
            if (needMainDnaForPad) {
                const optDna = !optimizationStale.value ? optimizedDnaByDesign.value[d.design_id] : undefined
                if (optDna) {
                    mainDna = optDna
                    // Re-apply feature colouring: build the original segment layout (same
                    // nucleotide lengths since optimisation preserves translation) and reslice
                    // the optimised sequence across those boundaries.
                    const built = buildMainDnaForRow(
                        table,
                        nFix,
                        cFix,
                        tagCol,
                        core,
                        includeNTags,
                        includeCTags
                    )
                    const marked = applyFixedStartAtgDna(
                        built.mainDna,
                        built.mainSegChunks,
                        freezeStart
                    )
                    let offset = 0
                    mainSegChunks = marked.mainSegChunks.map(chunk =>
                        chunk.map(seg => {
                            const slice = optDna.slice(offset, offset + seg.text.length)
                            offset += seg.text.length
                            return { ...seg, text: slice }
                        })
                    )
                } else {
                    ;({ mainDna, mainSegChunks } = buildMainDnaForRow(
                        table,
                        nFix,
                        cFix,
                        tagCol,
                        core,
                        includeNTags,
                        includeCTags
                    ))
                    ;({ mainDna, mainSegChunks } = applyFixedStartAtgDna(
                        mainDna,
                        mainSegChunks,
                        freezeStart
                    ))
                }
            }

            const paddingChunks =
                usePostStopPadTarget && padRaw && needMainDnaForPad
                    ? computePostStopPaddingChunks(mainDna.length, padTargetBp, padRaw, table)
                    : []

            for (const chunk of paddingChunks) {
                const { segments, exportText } = mixedToAaSegments(
                    chunk.aaMixed,
                    'seq-seg-padding',
                    undefined,
                    table
                )
                segmentsAaFixed.push(...segments)
                aaExportParts.push(exportText)
            }

            let prepared_aa = aaExportParts.join('')
            const prepared_aa_display = aaExportPartsDisplay.join('')

            const ext = molarExtinctionCoefficient(prepared_aa)
            const pi = isoelectricPoint(prepared_aa)
            const warns = sequenceWarnings(prepared_aa)
            const optError = !optimizationStale.value ? optimizedErrorsByDesign.value[d.design_id] : undefined
            if (optError) {
                warns.push(`DNA Opt: ${optError}`)
            }

            let segments_dna: PreparedSegment[] | null = null
            let prepared_dna: string | null = null

            if (dnaMode.value) {
                let dna = mainDna
                const padSegChunks: PreparedSegment[][] = []
                for (const chunk of paddingChunks) {
                    dna += chunk.dna
                    const { dna: unitDna, segments: padSegs } = mixedToDnaSegments(
                        chunk.aaMixed,
                        table,
                        'seq-seg-dna-body'
                    )
                    if (unitDna.length > 0 && chunk.dna.length === unitDna.length) {
                        padSegChunks.push(mergeDnaSegments(padSegs, 'seq-seg-padding'))
                    } else {
                        padSegChunks.push([{ text: chunk.dna, cssClass: 'seq-seg-padding' }])
                    }
                }

                const bodyLen = dna.length
                const padDnaOnly =
                    usePostStopPadTarget && padRaw
                        ? padRaw.replace(/[^aAcCgGtT]/g, '').toUpperCase()
                        : ''
                const minL = Math.max(0, minDnaFragmentLength.value)
                if (minL > 0 && dna.length < minL && padDnaOnly.length > 0) {
                    let i = 0
                    while (dna.length < minL) {
                        dna += padDnaOnly[i % padDnaOnly.length]
                        i += 1
                    }
                }
                prepared_dna = dna

                const flatSegs: PreparedSegment[] = []
                for (const chunk of mainSegChunks) {
                    flatSegs.push(...chunk)
                }
                for (const chunk of padSegChunks) {
                    flatSegs.push(...chunk)
                }
                if (dna.length > bodyLen) {
                    const extra = dna.slice(bodyLen)
                    flatSegs.push({ text: extra, cssClass: 'seq-seg-padding' })
                }
                segments_dna = flatSegs
            }

            return {
                row_key: `${d.run_id}\x1f${d.design_id}\x1f${(d as Record<string, unknown>).source_path ?? ''}`,
                design_id: d.design_id,
                design_filter_text: [d.design_id, d.project_id, d.run_name].filter(Boolean).join(' '),
                run_id: d.run_id,
                run_name: d.run_name,
                project_id: d.project_id,
                source_path: String((d as Record<string, unknown>).source_path ?? ''),
                tag: tagCol || '-',
                original_sequence: raw || '(missing)',
                prepared_aa,
                prepared_aa_display,
                prepared_dna,
                segments_aa: segmentsAaFixed,
                segments_aa_display: segmentsAaDisplayFixed,
                segments_dna,
                extinction_coeff_reduced: ext.reduced,
                extinction_coeff_oxidized: ext.oxidized,
                isoelectric_point: pi,
                warnings: warns
            }
        })
    })

    const shortNameComputation = computed(() => {
        const rows = preparedRowsInternal.value
        const inputs = rows.map(
            (r): ShortNameRowInput => ({
                row_key: r.row_key,
                design_id: r.design_id,
                original_aa: r.original_sequence,
                prepared_aa: r.prepared_aa,
                prepared_dna: r.prepared_dna,
                tag: r.tag
            })
        )
        return computeShortNames(inputs, effectiveShortNameStrategy.value, shortNameMaxLen.value)
    })

    const preparedRows = computed((): PreparedRow[] => {
        const rows = preparedRowsInternal.value
        const { map, nonUniqueRowKeys } = shortNameComputation.value
        const designIdCounts = new Map<string, number>()
        for (const r of rows) {
            designIdCounts.set(r.design_id, (designIdCounts.get(r.design_id) ?? 0) + 1)
        }
        return rows.map(r => {
            const sn =
                map.get(r.row_key) ??
                (sanitizeShortNameSegment(r.design_id) || r.design_id)
            const warnings = [...r.warnings]
            if ((designIdCounts.get(r.design_id) ?? 0) > 1) {
                warnings.push(WARNING_LONG_NAME_NOT_UNIQUE)
            }
            if (nonUniqueRowKeys.has(r.row_key)) {
                warnings.push(WARNING_SHORT_NAME_NOT_UNIQUE)
            }
            return { ...r, short_name: sn, warnings }
        })
    })

    let shortNamePersistTimer: ReturnType<typeof setTimeout> | null = null
    async function flushShortNamesToBackend(): Promise<void> {
        const rows = preparedRowsInternal.value
        if (rows.length === 0) return
        const strat = effectiveShortNameStrategy.value
        try {
            if (strat.kind === 'none') {
                return
            }
            const { map } = shortNameComputation.value
            await designsApi.updateShortNames({
                updates: rows.map(r => ({
                    run_id: r.run_id,
                    design_id: r.design_id,
                    source_path: r.source_path || undefined,
                    short_name: map.get(r.row_key) ?? null
                })),
                refresh_cache_after: false
            })
        } catch {
            /* offline or auth; short names still work in-session */
        }
    }

    watch(
        () => [
            shortNameKind.value,
            shortNameMaxLen.value,
            preparedRowsInternal.value,
            effectiveShortNameStrategy.value
        ],
        () => {
            if (shortNamePersistTimer) clearTimeout(shortNamePersistTimer)
            shortNamePersistTimer = setTimeout(() => {
                void flushShortNamesToBackend()
            }, 450)
        },
        { deep: true }
    )

    async function clearShortNames(): Promise<void> {
        applyingAutoShortNameStrategy = true
        shortNameKind.value = 'none'
        applyingAutoShortNameStrategy = false
        const rows = preparedRowsInternal.value
        if (rows.length === 0) return
        try {
            await designsApi.updateShortNames({
                updates: rows.map(r => ({
                    run_id: r.run_id,
                    design_id: r.design_id,
                    source_path: r.source_path || undefined,
                    short_name: null
                })),
                refresh_cache_after: false
            })
            const ds = useDesignsStore()
            await ds.fetchDesigns()
        } catch {
            /* ignore */
        }
    }

    function addPreset(zone: TagZone, preset: TagPresetDefinition) {
        if (!preset.zones.includes(zone)) return
        const t: PlacedTag = {
            id: nextTagId(),
            kind: preset.kind,
            sequence: preset.sequence,
            label: preset.tag_name
        }
        if (zone === 'n') nTags.value = [...nTags.value, t]
        else cTags.value = [...cTags.value, t]
    }

    function addCustomTag(zone: TagZone) {
        const s = customTagInput.value.trim()
        if (!s) return
        const t: PlacedTag = {
            id: nextTagId(),
            kind: 'custom',
            sequence: s,
            label: 'Custom'
        }
        if (zone === 'n') nTags.value = [...nTags.value, t]
        else cTags.value = [...cTags.value, t]
        customTagInput.value = ''
    }

    function removeTag(zone: TagZone, index: number) {
        if (zone === 'n') {
            nTags.value = nTags.value.filter((_, i) => i !== index)
        } else {
            cTags.value = cTags.value.filter((_, i) => i !== index)
        }
    }

    async function fetchMissingSequences(): Promise<{ ok: number; errors: string[] }> {
        const ds = useDesignsStore()
        const chain = extractChain.value.trim() || 'B'
        const items: {
            run_id: string
            design_id: string
            pdb_file: string
            chain: string
            source_path?: string
        }[] = []
        const errors: string[] = []

        for (const d of inputDesigns.value) {
            if (getRawSequence(d)) continue
            const fn = ds.getStructureFilename(d)
            if (!fn) {
                errors.push(`${d.design_id}: no structure file`)
                continue
            }
            const sp = (d as Record<string, unknown>).source_path
            items.push({
                run_id: d.run_id,
                design_id: d.design_id,
                pdb_file: fn,
                chain,
                source_path: sp != null ? String(sp) : undefined
            })
        }

        if (items.length === 0) {
            return { ok: 0, errors }
        }

        extracting.value = true
        try {
            const res = await designsApi.extractSequences({
                designs: items,
                refresh_cache_after: true
            })
            let ok = 0
            for (const r of res.results) {
                if (r.error) errors.push(`${r.design_id}: ${r.error}`)
                else ok += 1
            }
            await ds.fetchDesigns()
            return { ok, errors }
        } finally {
            extracting.value = false
        }
    }

    const optimizationConstraints = ref<DnaOptConstraintSpecDto[]>(JSON.parse(JSON.stringify(DEFAULT_DNAOPT_CONSTRAINTS)))
    const optimizationMethod = ref<string>('match_codon_usage')
    const optimizedDnaByDesign = ref<Record<string, string>>({})
    const optimizedErrorsByDesign = ref<Record<string, string>>({})
    const optimizing = ref(false)
    const optimizationGlobalError = ref<string | null>(null)
    const optimizationStale = ref(false)
    /** True after at least one successful per-sequence optimisation in this session (used for stale messaging). */
    const optimizationEverSucceeded = ref(false)

    watch(
        [
            nTags,
            cTags,
            nTerminalPrefix,
            cTerminalSuffix,
            includeStopForNTagged,
            includeStopForCTagged,
            useDoubleStop,
            dontModifyStartAtg,
            postStopPadding,
            postStopPadUpToNucleotideLength,
            onlyUseNTerminalTagWhenPaddingRequired,
            onlyUseCTerminalTagWhenPaddingRequired,
            selectedCodonTable,
            optimizationConstraints
        ],
        () => {
            optimizationStale.value = true
        },
        { deep: true }
    )

    async function runOptimization() {
        const seqs: Record<string, string> = {}
        const fixedByDesign: Record<string, boolean[]> = {}
        const frameByDesign: Record<string, number> = {}
        for (const row of preparedRows.value) {
            if (!row.segments_aa_display.length && !row.prepared_aa_display) continue
            const { aa, fixed } = expandFixedFromSegments(row.segments_aa_display)
            const codingAa = aa || row.prepared_aa_display
            if (!codingAa) continue
            seqs[row.design_id] = codingAa
            fixedByDesign[row.design_id] = fixed.length === codingAa.length
                ? fixed
                : codingAa.split('').map(ch => ch === '*')
            frameByDesign[row.design_id] = codingFrameOffset(row.segments_aa_display)
        }
        if (Object.keys(seqs).length === 0) {
            optimizationGlobalError.value = 'No sequences in scope to optimise.'
            return
        }

        const snapshotAa = { ...seqs }
        const snapshotFixed = Object.fromEntries(
            Object.entries(fixedByDesign).map(([id, mask]) => [id, [...mask]])
        )

        optimizing.value = true
        optimizationGlobalError.value = null
        try {
            const req = {
                sequences: seqs,
                fixed: fixedByDesign,
                frame: frameByDesign,
                codon_table_id: selectedCodonTable.value || FALLBACK_ECOLLI_CODON_TABLE.label,
                method: optimizationMethod.value,
                constraints: optimizationConstraints.value.map(serializeConstraintForBackend)
            }
            const res = await sequencesApi.optimizeDna(req)

            const stillMatches = Object.keys(snapshotAa).every(id => {
                const row = preparedRows.value.find(r => r.design_id === id)
                if (!row) return false
                const { aa, fixed } = expandFixedFromSegments(row.segments_aa_display)
                const codingAa = aa || row.prepared_aa_display
                if (codingAa !== snapshotAa[id]) return false
                const snap = snapshotFixed[id] || []
                if (fixed.length !== snap.length) return false
                return fixed.every((v, i) => v === snap[i])
            })
            if (!stillMatches) {
                // Coding sequence / fixed mask changed while the request was in flight.
                return
            }

            const optMap: Record<string, string> = {}
            const errMap: Record<string, string> = {}
            for (const r of res.results) {
                if (r.optimized_dna) {
                    optMap[r.design_id] = r.optimized_dna
                }
                if (r.error) {
                    errMap[r.design_id] = r.error
                }
            }
            optimizedDnaByDesign.value = optMap
            optimizedErrorsByDesign.value = errMap
            optimizationStale.value = false
            optimizationEverSucceeded.value = Object.keys(optMap).length > 0
        } catch (e: any) {
            optimizationGlobalError.value = String(e)
        } finally {
            optimizing.value = false
        }
    }

    function resetConstraintsToDefaults() {
        optimizationConstraints.value = JSON.parse(JSON.stringify(DEFAULT_DNAOPT_CONSTRAINTS))
    }

    function addConstraint() {
        optimizationConstraints.value.push({
            type: 'ExcludeRestrictionSite',
            enabled: true,
            params: { enzyme: 'NdeI' }
        })
    }

    function removeConstraint(idx: number) {
        optimizationConstraints.value.splice(idx, 1)
    }

    const shortNameDedupeCount = computed(() => shortNameComputation.value.dedupeCount)

    return {
        nTags,
        cTags,
        nTerminalPrefix,
        cTerminalSuffix,
        includeStopForNTagged,
        includeStopForCTagged,
        useDoubleStop,
        dontModifyStartAtg,
        goodOnly,
        extractChain,
        dnaMode,
        showPostStopPadding,
        postStopPadding,
        postStopPadUpToNucleotideLength,
        onlyUseNTerminalTagWhenPaddingRequired,
        onlyUseCTerminalTagWhenPaddingRequired,
        minDnaFragmentLength,
        customTagInput,
        exportOrderName,
        extracting,
        codonTableOptions,
        codonTablesListLoading,
        codonTablesDetailLoading,
        selectedCodonTable,
        activeCodonTable,
        optimizationConstraints,
        optimizationMethod,
        optimizedDnaByDesign,
        optimizedErrorsByDesign,
        optimizing,
        optimizationGlobalError,
        optimizationStale,
        optimizationEverSucceeded,
        ensureCodonTablesLoaded,
        validationErrors,
        canDownload,
        presetOptionsN,
        presetOptionsC,
        inputDesigns,
        preparedRows,
        addPreset,
        addCustomTag,
        removeTag,
        fetchMissingSequences,
        getRawSequence,
        runOptimization,
        resetConstraintsToDefaults,
        addConstraint,
        removeConstraint,
        shortNameKind,
        shortNameMaxLen,
        shortNameRegexPattern,
        shortNameRegexReplacement,
        shortNameRegexFlags,
        shortNameSplitDelimiter,
        shortNameSplitIndices,
        shortNameSplitAddPrefix,
        shortNameSplitAddSuffix,
        shortNameSplitAddHash,
        shortNamePatternPrefix,
        shortNamePatternUidLength,
        shortNamePatternNumberPad,
        shortNameSmartHashLen,
        shortNameSmartStemIncludeHash,
        shortNameSmartStemIncludeIndex,
        shortNameSmartStemRemoveCommonPrefix,
        shortNameSmartStemRemoveCommonSuffix,
        shortNameSmartStemAddPrefix,
        shortNameSmartStemAddSuffix,
        shortNameStripPrefixRegex,
        shortNameStripSuffixRegex,
        shortNameStripNewPrefix,
        effectiveShortNameStrategy,
        shortNameDedupeCount,
        clearShortNames
    }
})
