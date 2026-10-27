/**
 * Generate parity vectors from the original TypeScript implementation.
 *
 * The construct builder now lives in Python (`backend/seq_prep/`). These vectors
 * pin the two ports whose behaviour is hardest to eyeball - the isoelectric-point
 * bisection and short-name generation - against the TS that produced today's
 * orders, so the port is verified rather than assumed.
 *
 * Run via `backend/tests/fixtures/regenerate_seq_prep_vectors.sh`.
 *
 * Short-name strategies that take a user-supplied regex are deliberately limited
 * here to patterns that behave identically under JS and Python. Short names are
 * Python-only now, and `$1` style replacements are migrated on load; see
 * `plans/seq_prep_download_script.md`.
 */

import {
    isoelectricPoint,
    molarExtinctionCoefficient,
    sequenceWarnings
} from '../src/utils/protParam'
import {
    computeShortNames,
    hashBase52,
    sanitizeShortNameSegment,
    type ShortNameRowInput,
    type ShortNameStrategy
} from '../src/stores/shortName'

const PROTEIN_CASES = [
    '',
    'M',
    'MKWVTFISLLW',
    'MKWVTFISLLFLFSSAYSRGVFRRDAHKSEVAHRFKDLGEENFKALVLIAFAQYLQQCPFEDHVKLVNEVTEFAK',
    'GGGGSHHHHHHSG*',
    'CCCCWWWYYY',
    'ACDEFGHIKLMNPQRSTVWY',
    'MKWVTFISLL*GGGG',
    'DDDDDDDDDD',
    'KKKKKKKKKK',
    'MGSSHHHHHHSSGLVPRGSHMASMTGGQQMGRGSEF'
]

const ROWS: ShortNameRowInput[] = [
    { row_key: 'k1', design_id: 'batch-1_designA_model0', original_aa: 'MKWVTFISLL', prepared_aa: 'MKWVTFISLL*', prepared_dna: 'ATGAAATGGGTTACCTTCATTTCTCTGCTGTAA', tag: 'N' },
    { row_key: 'k2', design_id: 'batch-1_designB_model0', original_aa: 'GGCDEFHIKW', prepared_aa: 'GGCDEFHIKW*', prepared_dna: 'GGTGGTTGCGATGAATTCCATATTAAATGGTAA', tag: 'C' },
    { row_key: 'k3', design_id: 'batch-2_designC_model1', original_aa: 'MMMMMMKKKK', prepared_aa: 'MMMMMMKKKK*', prepared_dna: 'ATGATGATGATGATGATGAAAAAAAAAAAATAA', tag: 'N' },
    { row_key: 'k4', design_id: 'batch-2_designC_model1', original_aa: 'MMMMMMKKKK', prepared_aa: 'MMMMMMKKKK*', prepared_dna: 'ATGATGATGATGATGATGAAAAAAAAAAAATAA', tag: 'N' }
]

const STRATEGIES: Record<string, ShortNameStrategy> = {
    none: { kind: 'none' },
    regex_strip_prefix: { kind: 'regex', pattern: '^batch-[0-9]+_', replacement: '', flags: '' },
    splitTake: { kind: 'splitTake', delimiter: '_', indices: [2, 3], addPrefix: 'ord', addSuffix: '', addHash: true, hashLen: 5 },
    splitTake_nohash: { kind: 'splitTake', delimiter: '_', indices: [1, 2], addPrefix: '', addSuffix: 'x', addHash: false, hashLen: 5 },
    pattern: { kind: 'pattern', prefix: 'design', uidLength: 5, numberPad: 3 },
    pattern_nopad: { kind: 'pattern', prefix: '', uidLength: 6, numberPad: 0 },
    smartStemHash: { kind: 'smartStemHash', includeHash: true, hashLen: 5, includeIndex: false, removeCommonPrefix: false, removeCommonSuffix: true, addPrefix: '', addSuffix: '' },
    smartStemHash_idx: { kind: 'smartStemHash', includeHash: true, hashLen: 4, includeIndex: true, removeCommonPrefix: true, removeCommonSuffix: false, addPrefix: 'p', addSuffix: 's' },
    smartStemHash_nohash: { kind: 'smartStemHash', includeHash: false, hashLen: 5, includeIndex: true, removeCommonPrefix: true, removeCommonSuffix: true, addPrefix: '', addSuffix: '' },
    smartRegexStrip: { kind: 'smartRegexStrip', prefixPattern: '^batch-[0-9]+_', suffixPattern: '_model[0-9]+$', newPrefix: 'bd', hashLen: 5 }
}

const out = {
    _comment: 'Generated from the TypeScript implementation by frontend/scripts/genSeqPrepVectors.ts. Do not edit by hand.',
    protparam: PROTEIN_CASES.map(seq => {
        const ext = molarExtinctionCoefficient(seq)
        const pi = isoelectricPoint(seq)
        return {
            sequence: seq,
            extinction_reduced: ext.reduced,
            extinction_oxidized: ext.oxidized,
            isoelectric_point: Number.isFinite(pi) ? pi : null,
            warnings: sequenceWarnings(seq)
        }
    }),
    hash_base52: ['', 'MKWVTFISLL', 'batch-1_designA', 'x'.repeat(200)].map(input => ({
        input,
        len5: hashBase52(input, 5),
        len10: hashBase52(input, 10)
    })),
    sanitize: ['  batch-1_design  ', 'a//b??c', '___x___', '', 'A-B_C'].map(input => ({
        input,
        output: sanitizeShortNameSegment(input)
    })),
    short_names: Object.entries(STRATEGIES).map(([name, strategy]) => {
        const res = computeShortNames(ROWS, strategy, 32)
        return {
            strategy: name,
            spec: strategy,
            names: ROWS.map(r => [r.row_key, res.map.get(r.row_key)]),
            dedupe_count: res.dedupeCount,
            non_unique: [...res.nonUniqueRowKeys].sort()
        }
    })
}

console.log(JSON.stringify(out, null, 2))
