/**
 * Single source of truth for pipeline/method UI, score columns, colours, and Select Runs chips.
 *
 * Keep aligned with ``backend/run_discovery.py`` ``run_folder_signatures`` (primary score columns, methods).
 */

import type { Design } from '../types/store'

// --- Methods (filter dropdowns, tags, icons) --------------------------------

export const PIPELINE_METHOD_IDS = [
    'bindcraft',
    'rfd',
    'boltzgen',
    'rfd3',
    'rfd4_proteina',
    'bindcraft2',
] as const

export type PipelineMethodId = (typeof PIPELINE_METHOD_IDS)[number]

/**
 * Primitive palette names (PrimeVue styled mode). Chips use light saturation (50–100) for fill.
 * @see https://primevue.org/theming/styled/#colors
 */
export type PipelineTagPalette = 'emerald' | 'sky' | 'amber' | 'slate'

/** Chip fill + label colour using theme CSS variables. */
export interface PipelineTagColors {
    background: string
    color: string
}

/** Light chip background (pastel); pair with ``TAG_CHIP_FOREGROUND_SHADE`` for label contrast. */
const TAG_CHIP_BACKGROUND_SHADE = 100

/** Dark text on light chip (same hue as ``palette``). */
const TAG_CHIP_FOREGROUND_SHADE = 900

export function tagColorsFromPalette(palette: PipelineTagPalette): PipelineTagColors {
    return {
        background: `var(--p-${palette}-${TAG_CHIP_BACKGROUND_SHADE})`,
        color: `var(--p-${palette}-${TAG_CHIP_FOREGROUND_SHADE})`,
    }
}

const METHOD_TAG_PALETTE: Record<string, PipelineTagPalette> = {
    bindcraft: 'emerald',
    rfd: 'sky',
    rfd3: 'sky',
    rfd4_proteina: 'sky',
    bindcraft2: 'emerald',
    boltzgen: 'amber',
}

const METHOD_TAG_DEFAULT_PALETTE: PipelineTagPalette = 'slate'

const METHOD_TAG_DISPLAY: Record<string, { iconClass: string }> = {
    bindcraft: { iconClass: 'pi pi-code' },
    rfd: { iconClass: 'pi pi-file' },
    rfd3: { iconClass: 'pi pi-box' },
    rfd4_proteina: { iconClass: 'pi pi-box' },
    bindcraft2: { iconClass: 'pi pi-code' },
    boltzgen: { iconClass: 'pi pi-info-circle' },
}

const METHOD_TAG_DEFAULT = {
    iconClass: 'pi pi-info-circle',
}

export function getMethodTagColors(method: string | undefined): PipelineTagColors {
    const palette =
        method != null && method !== '' ? METHOD_TAG_PALETTE[method] ?? METHOD_TAG_DEFAULT_PALETTE : METHOD_TAG_DEFAULT_PALETTE
    return tagColorsFromPalette(palette)
}

/** Inline style object for `<Tag :style="getMethodTagStyle(...)">` (no `severity`). */
export function getMethodTagStyle(method: string | undefined): Record<string, string> {
    const c = getMethodTagColors(method)
    return { background: c.background, color: c.color }
}

export function getMethodIconClass(method: string | undefined): string {
    if (!method) return METHOD_TAG_DEFAULT.iconClass
    return METHOD_TAG_DISPLAY[method]?.iconClass ?? METHOD_TAG_DEFAULT.iconClass
}

// --- Score field definitions (table, filters, structure card, colours) -----

export type ScoreColorMode =
    | { kind: 'neutral' }
    | { kind: 'pae_angstrom' }
    | { kind: 'min_interaction_pae' }
    | { kind: 'span'; min: number; max: number; higherBetter: boolean }

export interface ScoreFieldDef {
    field: string
    tableHeader: string
    /** Human label for structure panel / tooltips; defaults to ``tableHeader``. */
    niceName?: string
    /** Include in min/max score range filter when the column exists on a design. */
    scoreRangeFilter: boolean
    /** Include in global text filter score subset when that column is visible. */
    globalFilterScore: boolean
    color: ScoreColorMode
}

function d(
    field: string,
    tableHeader: string,
    opts: Partial<Omit<ScoreFieldDef, 'field' | 'tableHeader'>> & {
        niceName?: string
        scoreRangeFilter?: boolean
        globalFilterScore?: boolean
        color?: ScoreColorMode
    } = {}
): ScoreFieldDef {
    return {
        field,
        tableHeader,
        niceName: opts.niceName,
        scoreRangeFilter: opts.scoreRangeFilter ?? false,
        globalFilterScore: opts.globalFilterScore ?? false,
        color: opts.color ?? { kind: 'neutral' },
    }
}

/**
 * Declarative score columns. Order is used for default visible column order after base columns.
 */
export const SCORE_FIELD_DEFS: readonly ScoreFieldDef[] = [
    d('pae_interaction', 'PAE Interaction', {
        niceName: 'PAE Interaction',
        scoreRangeFilter: true,
        globalFilterScore: true,
        color: { kind: 'pae_angstrom' },
    }),
    d('Average_i_pTM', 'Average i_pTM', {
        niceName: 'Average i-pTM',
        scoreRangeFilter: true,
        globalFilterScore: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('design_to_target_iptm', 'Design→Target ipTM', {
        niceName: 'Design→Target ipTM',
        scoreRangeFilter: true,
        globalFilterScore: false,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('quality_score', 'Quality Score', {
        scoreRangeFilter: true,
        color: { kind: 'neutral' },
    }),
    d('pLDDT', 'pLDDT', { color: { kind: 'neutral' } }),
    d('i_pTM', 'i_pTM', {
        scoreRangeFilter: true,
        globalFilterScore: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('ipTM', 'ipTM', {
        scoreRangeFilter: true,
        globalFilterScore: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('iptm', 'ipTM', {
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('pair_pae', 'Pair PAE', {
        scoreRangeFilter: true,
        color: { kind: 'pae_angstrom' },
    }),
    d('rf3_ipsae_min', 'RF3 ipSAE Min', {
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('rf3_rmsd_target_aligned_binder_rmsd_all', 'RF3 RMSD (Target-aligned Binder)', {
        scoreRangeFilter: true,
        color: { kind: 'neutral' },
    }),
    // RFD4-Proteina inline oracle metrics, merged from of3_/af3_inline_metrics.csv.
    // "coi" is the chain of interest: the binder. pTM/ipTM/pLDDT arrive rescaled to
    // 0-1 by the backend merge; PAE and RMSD stay in angstroms.
    d('oracle_ppi_iptm_coi', 'Interface pTM (binder)', {
        niceName: 'Interface pTM, binder chain (oracle)',
        scoreRangeFilter: true,
        globalFilterScore: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('oracle_ppi_plddt_coi', 'pLDDT (binder)', {
        niceName: 'pLDDT, binder chain (oracle)',
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('oracle_ppi_overall_ptm', 'pTM (complex)', {
        niceName: 'pTM, whole complex (oracle)',
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('oracle_ppi_ipae_coi', 'Interface PAE (binder)', {
        niceName: 'Interface PAE, binder chain (oracle)',
        scoreRangeFilter: true,
        color: { kind: 'pae_angstrom' },
    }),
    d('oracle_ppi_ranking_score', 'Oracle ranking score', {
        niceName: 'Oracle ranking score',
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('hotspot_obedience_hotspot_obedience', 'Hotspot obedience', {
        niceName: 'Hotspot obedience',
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('refolded_target_aligned_binder_rmsd_rmsd', 'Refolded binder RMSD', {
        niceName: 'Refolded binder RMSD, target-aligned (A)',
        color: { kind: 'span', min: 0, max: 3.5, higherBetter: false },
    }),
    d('consensus_z', 'Consensus z', {
        niceName: 'Cross-engine consensus z-score',
        scoreRangeFilter: true,
        color: { kind: 'neutral' },
    }),
    d('i_pDAE', 'i_pDAE', {
        niceName: 'Interface pDAE (distance-masked interface confidence)',
        scoreRangeFilter: true,
        globalFilterScore: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('i_pAE', 'i_pAE', {
        niceName: 'Interface PAE',
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: false },
    }),
    d('Binder_RMSD', 'Binder RMSD', {
        niceName: 'Binder RMSD',
        color: { kind: 'span', min: 0, max: 3.5, higherBetter: false },
    }),
    d('Hotspot_Contact_Fraction', 'Hotspot Contact Fraction', {
        niceName: 'Hotspot contact fraction',
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('Coldspot_Contact_Fraction', 'Coldspot Contact Fraction', {
        niceName: 'Coldspot contact fraction',
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: false },
    }),
    d('Off_Epitope_Contact_Fraction', 'Off-epitope Contact Fraction', {
        niceName: 'Off-epitope contact fraction',
        scoreRangeFilter: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: false },
    }),
    d('interaction_pae', 'Interaction PAE', {
        niceName: 'Interaction PAE',
        color: { kind: 'pae_angstrom' },
    }),
    d('min_interation_pae', 'Min interaction PAE', {
        niceName: 'Min interaction PAE',
        color: { kind: 'min_interaction_pae' },
    }),
    d('design_ipsae_min', 'Design ipSAE min', {
        niceName: 'Design ipSAE min',
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('Average_Binder_pLDDT', 'Average Binder pLDDT', {
        niceName: 'Average Binder pLDDT',
        globalFilterScore: true,
        color: { kind: 'span', min: 0, max: 1, higherBetter: true },
    }),
    d('plddt_binder', 'Binder pLDDT', {
        niceName: 'Binder pLDDT',
        globalFilterScore: true,
        color: { kind: 'span', min: 0, max: 100, higherBetter: true },
    }),
    d('Average_Binder_RMSD', 'Average Binder RMSD', {
        niceName: 'Average Binder RMSD',
        color: { kind: 'span', min: 0, max: 3.5, higherBetter: false },
    }),
    d('Average_Target_RMSD', 'Average Target RMSD', {
        niceName: 'Average Target RMSD',
        color: { kind: 'span', min: 0, max: 3.5, higherBetter: false },
    }),
    d('binder_aligned_rmsd', 'Binder Aligned RMSD', {
        niceName: 'Binder Aligned RMSD',
        color: { kind: 'span', min: 0, max: 3.5, higherBetter: false },
    }),
]

const SCORE_FIELD_BY_FIELD: ReadonlyMap<string, ScoreFieldDef> = new Map(
    SCORE_FIELD_DEFS.map((x) => [x.field, x])
)

/** Table column configs derived from defs (presence still checked per-design in the store). */
export function scoreColumnConfigsForTable(): ReadonlyArray<{ field: string; header: string }> {
    return SCORE_FIELD_DEFS.map((x) => ({ field: x.field, header: x.tableHeader }))
}

/** Nice labels for structure detail / score headers. */
export function niceNameForScoreField(field: string): string {
    const def = SCORE_FIELD_BY_FIELD.get(field)
    if (def?.niceName) return def.niceName
    if (def) return def.tableHeader
    return field.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
}

/** All nice names as a record (for legacy ``niceFieldNames`` consumers). */
export function niceFieldNamesRecord(): Record<string, string> {
    const o: Record<string, string> = {}
    for (const def of SCORE_FIELD_DEFS) {
        o[def.field] = def.niceName ?? def.tableHeader
    }
    return o
}

/** Default score column order when building first visible set (must match ``field`` in defs). */
export function defaultVisibleScoreColumnFields(): readonly string[] {
    return SCORE_FIELD_DEFS.map((x) => x.field)
}

/** Ordered score fields shown in the structure card (subset may exist per design). */
export const STRUCTURE_CARD_SCORE_ORDER: readonly string[] = [
    'Average_i_pTM',
    'design_to_target_iptm',
    'design_ipsae_min',
    'interaction_pae',
    'min_interation_pae',
    'Average_Binder_RMSD',
    'Average_Target_RMSD',
    'Average_Binder_pLDDT',
    'pae_interaction',
    'plddt_binder',
    'binder_aligned_rmsd',
    'iptm',
    'pair_pae',
    'rf3_ipsae_min',
    'rf3_rmsd_target_aligned_binder_rmsd_all',
    'i_pDAE',
    'i_pAE',
    'Binder_RMSD',
    'oracle_ppi_iptm_coi',
    'oracle_ppi_plddt_coi',
    'oracle_ppi_overall_ptm',
    'oracle_ppi_ipae_coi',
    'oracle_ppi_ranking_score',
    'hotspot_obedience_hotspot_obedience',
    'refolded_target_aligned_binder_rmsd_rmsd',
    'Hotspot_Contact_Fraction',
    'Coldspot_Contact_Fraction',
    'Off_Epitope_Contact_Fraction',
    'consensus_z',
]

/** Static design keys excluded from “extra” structure sections (not scores). */
export const DESIGN_TABLE_STATIC_FIELD_KEYS: ReadonlySet<string> = new Set([
    'design_id',
    'project_id',
    'run_name',
    'method',
    'good',
    'tag',
    ...SCORE_FIELD_DEFS.map((x) => x.field),
    'pdb_file',
    'run_path',
    'run_id',
    'target_sequence',
])

/** Extra known row keys when building columns (not scores; exclude from generic dynamic columns). */
const DESIGN_BUILD_COLUMN_EXTRA_KEYS = [
    'Length',
    'length',
    'file_name',
    'source_path',
    'backbone_id',
    'params',
    'min_interaction_pae',
    'design_ptm',
    // Client-only fields attached in the designs store — never show as table columns.
    'binderRowKey',
    '__source_saved_set_id',
] as const

/** Designs-table field written by Filtering → Apply Ranking. 1 = best.
 * Kept off pipeline names (`quality_score`, `final_rank`) so it cannot clash with a method's own column. */
export const BINDERDASH_RANKING_FIELD = 'binderdash_ranking'

export const BINDERDASH_RANKING_HEADER = 'Ranking'

export const DESIGN_BUILD_COLUMN_STATIC_KEYS: ReadonlySet<string> = new Set([
    ...DESIGN_TABLE_STATIC_FIELD_KEYS,
    ...DESIGN_BUILD_COLUMN_EXTRA_KEYS,
    BINDERDASH_RANKING_FIELD,
])

// --- Best design within MPNN group (primary / secondary scores) --------------

export interface MethodBestScoreConfig {
    primary: string
    secondary: readonly string[]
    higherIsBetter: boolean
}

export const METHOD_BEST_SCORE: Readonly<Record<string, MethodBestScoreConfig>> = {
    bindcraft: {
        primary: 'Average_i_pTM',
        secondary: ['Average_Binder_pLDDT'],
        higherIsBetter: true,
    },
    rfd: {
        primary: 'pae_interaction',
        secondary: ['plddt_binder'],
        higherIsBetter: false,
    },
    boltzgen: {
        primary: 'design_to_target_iptm',
        secondary: ['design_ptm'],
        higherIsBetter: true,
    },
    rfd3: {
        primary: 'iptm',
        secondary: ['rf3_ipsae_min'],
        higherIsBetter: true,
    },
    bindcraft2: {
        primary: 'i_pDAE',
        secondary: ['i_pTM'],
        higherIsBetter: true,
    },
    rfd4_proteina: {
        primary: 'oracle_ppi_iptm_coi',
        secondary: ['oracle_ppi_plddt_coi'],
        higherIsBetter: true,
    },
}

// --- Structure path: methods that use ``file_name`` when ``pdb_file`` is absent

export function getStructureFilenameFromDesign(design: Design): string {
    const fromPdb = design.pdb_file?.split('/').pop() || ''
    if (fromPdb) return fromPdb
    const d = design as Record<string, unknown>
    if (d.method === 'boltzgen') {
        const fn = d.file_name
        if (fn != null && String(fn).trim() !== '') return String(fn).trim()
    }
    return ''
}

export function designHasStructureFile(design: Design): boolean {
    if (design.pdb_file) return true
    const d = design as Record<string, unknown>
    return d.method === 'boltzgen' && d.file_name != null && String(d.file_name).trim() !== ''
}

// --- Select Runs primary score chip ------------------------------------------

type ChipRule =
    | {
          id: string
          kind: 'column'
          columns: readonly string[]
          chipLabel?: string
          tagPalette: PipelineTagPalette
      }
    | {
          id: string
          kind: 'includes'
          includes: readonly string[]
          chipLabel?: string
          tagPalette: PipelineTagPalette
      }

function normaliseColumnId(column: string): string {
    return column.toLowerCase().replace(/\s+/g, '')
}

export const PRIMARY_SCORE_CHIP_RULES: readonly ChipRule[] = [
    {
        id: 'boltzgen_design_to_target_iptm',
        kind: 'column',
        columns: ['design_to_target_iptm'],
        chipLabel: 'ipTM',
        tagPalette: 'amber',
    },
    {
        id: 'bindcraft_average_i_ptm',
        kind: 'column',
        columns: ['average_i_ptm'],
        chipLabel: 'ipTM',
        tagPalette: 'emerald',
    },
    {
        id: 'rfd_pae_interaction',
        kind: 'column',
        columns: ['pae_interaction'],
        tagPalette: 'sky',
    },
    {
        id: 'rfd3_iptm',
        kind: 'column',
        columns: ['iptm'],
        chipLabel: 'ipTM',
        tagPalette: 'emerald',
    },
    {
        id: 'rfd3_pair_pae',
        kind: 'column',
        columns: ['pair_pae'],
        tagPalette: 'sky',
    },
    {
        id: 'rfd3_ipsae',
        kind: 'column',
        columns: ['rf3_ipsae_min'],
        tagPalette: 'slate',
    },
    {
        id: 'rfd3_rmsd',
        kind: 'column',
        columns: ['rf3_rmsd_target_aligned_binder_rmsd_all'],
        tagPalette: 'slate',
    },
    {
        id: 'bindcraft2_i_pdae',
        kind: 'column',
        columns: ['i_pdae'],
        tagPalette: 'emerald',
    },
    {
        id: 'rfd4_oracle_iptm',
        kind: 'column',
        columns: ['oracle_ppi_iptm_coi'],
        tagPalette: 'sky',
    },
    {
        id: 'rfd4_consensus_z',
        kind: 'column',
        columns: ['consensus_z'],
        chipLabel: 'consensus z',
        tagPalette: 'sky',
    },
    {
        id: 'fallback_pae',
        kind: 'includes',
        includes: ['pae'],
        tagPalette: 'sky',
    },
    {
        id: 'fallback_iptm',
        kind: 'includes',
        includes: ['iptm'],
        chipLabel: 'ipTM',
        tagPalette: 'emerald',
    },
    {
        id: 'fallback_ptm',
        kind: 'includes',
        includes: ['ptm'],
        chipLabel: 'ipTM',
        tagPalette: 'emerald',
    },
]

const CHIP_DEFAULT_PALETTE: PipelineTagPalette = 'slate'

function chipRuleMatches(normalised: string, rule: ChipRule): boolean {
    if (rule.kind === 'column') {
        return rule.columns.some((c) => normaliseColumnId(c) === normalised)
    }
    return rule.includes.some((sub) => normalised.includes(normaliseColumnId(sub)))
}

export function resolvePrimaryScoreChip(column: string): {
    chipLabel: string
    tagColors: PipelineTagColors
} {
    const normalised = normaliseColumnId(column)
    for (const rule of PRIMARY_SCORE_CHIP_RULES) {
        if (!chipRuleMatches(normalised, rule)) continue
        return {
            chipLabel: rule.chipLabel ?? column,
            tagColors: tagColorsFromPalette(rule.tagPalette),
        }
    }
    return { chipLabel: column, tagColors: tagColorsFromPalette(CHIP_DEFAULT_PALETTE) }
}

// --- Score cell / heat colours (structure + table) --------------------------

const SCORE_COLOR_NEUTRAL = '#dfe6e9'

const clamp01 = (x: number) => Math.max(0, Math.min(1, x))
const lerp = (a: number, b: number, t: number) => a + (b - a) * t

function colorFromT(t: number): string {
    const r1 = 231,
        g1 = 76,
        b1 = 60
    const r2 = 241,
        g2 = 196,
        b2 = 15
    const r3 = 46,
        g3 = 204,
        b3 = 113
    if (t <= 0.5) {
        const k = t / 0.5
        const r = Math.round(lerp(r1, r2, k))
        const g = Math.round(lerp(g1, g2, k))
        const b = Math.round(lerp(b1, b2, k))
        return `rgb(${r}, ${g}, ${b})`
    }
    const k = (t - 0.5) / 0.5
    const r = Math.round(lerp(r2, r3, k))
    const g = Math.round(lerp(g2, g3, k))
    const b = Math.round(lerp(b2, b3, k))
    return `rgb(${r}, ${g}, ${b})`
}

/** PAE (Å): ≤10 green, 10–15 orange, >15 red (lower is better). */
function paeBandColor(v: number): string {
    if (v <= 10) return colorFromT(1)
    if (v <= 15) return 'rgb(241, 196, 15)'
    return colorFromT(0)
}

/** Min interaction PAE (Å): ≤5 green, >5–≤7 orange, >7 red. */
function minInteractionPaeBandColor(v: number): string {
    if (v <= 5) return colorFromT(1)
    if (v <= 7) return 'rgb(241, 196, 15)'
    return colorFromT(0)
}

export function scoreFieldColor(field: string, raw: unknown): string {
    const v = Number(raw)
    if (!Number.isFinite(v)) return SCORE_COLOR_NEUTRAL

    const def = SCORE_FIELD_BY_FIELD.get(field)
    const mode = def?.color ?? { kind: 'neutral' as const }

    switch (mode.kind) {
        case 'neutral':
            return SCORE_COLOR_NEUTRAL
        case 'pae_angstrom':
            return paeBandColor(v)
        case 'min_interaction_pae':
            return minInteractionPaeBandColor(v)
        case 'span': {
            const span = Math.max(1e-9, mode.max - mode.min)
            let t = clamp01((v - mode.min) / span)
            if (!mode.higherBetter) t = 1 - t
            return colorFromT(t)
        }
        default:
            return SCORE_COLOR_NEUTRAL
    }
}
