/**
 * Client-side protein analysis aligned with BioPython Bio.SeqUtils.ProtParam /
 * IsoelectricPoint (Bjellqvist pKa tables).
 */

export const WARNING_CONTAINS_CYS = 'Contains Cys'
export const WARNING_LOW_EXTINCTION = 'Low extinction coefficient at 280 nm (ε₂₈₀)'
/** Table label for WARNING_LOW_EXTINCTION. */
export const WARNING_LOW_EXTINCTION_SHORT = 'Low ε₂₈₀'
/** ε₂₈₀ of a single Trp; constructs below it are hard to quantify by A280. */
export const LOW_EXTINCTION_THRESHOLD = 5500

const POSITIVE_PKS: Record<string, number> = {
    Nterm: 7.5,
    K: 10.0,
    R: 12.0,
    H: 5.98
}

const NEGATIVE_PKS: Record<string, number> = {
    Cterm: 3.55,
    D: 4.05,
    E: 4.45,
    C: 9.0,
    Y: 10.0
}

const PK_N_TERMINAL: Record<string, number> = {
    A: 7.59,
    M: 7.0,
    S: 6.93,
    P: 8.36,
    T: 6.82,
    V: 7.44,
    E: 7.7
}

const PK_C_TERMINAL: Record<string, number> = {
    D: 4.55,
    E: 4.75
}

export function normalizeProteinSequence(raw: string): string {
    return raw
        .replace(/\*/g, '')
        .replace(/\s/g, '')
        .toUpperCase()
        .replace(/[^A-Z]/g, '')
}

/** Coding sequence before the first in-frame stop (*); used for Cys / Trp warnings only. */
export function codingSequenceBeforeStop(raw: string): string {
    const i = raw.indexOf('*')
    const slice = i === -1 ? raw : raw.slice(0, i)
    return normalizeProteinSequence(slice)
}

export function molarExtinctionCoefficient(aa: string): { reduced: number; oxidized: number } {
    const s = normalizeProteinSequence(aa)
    let nW = 0
    let nY = 0
    let nC = 0
    for (const ch of s) {
        if (ch === 'W') nW += 1
        else if (ch === 'Y') nY += 1
        else if (ch === 'C') nC += 1
    }
    const reduced = nW * 5500 + nY * 1490
    const oxidized = reduced + Math.floor(nC / 2) * 125
    return { reduced, oxidized }
}

function countChargedAas(s: string): Record<'K' | 'R' | 'H' | 'D' | 'E' | 'C' | 'Y', number> {
    const out: Record<string, number> = { K: 0, R: 0, H: 0, D: 0, E: 0, C: 0, Y: 0 }
    for (const ch of s) {
        if (ch in out) out[ch] += 1
    }
    return out as Record<'K' | 'R' | 'H' | 'D' | 'E' | 'C' | 'Y', number>
}

export function isoelectricPoint(aa: string): number {
    const s = normalizeProteinSequence(aa)
    if (s.length === 0) return Number.NaN

    const aaCounts = countChargedAas(s)
    const charged: Record<string, number> = {
        Nterm: 1,
        Cterm: 1,
        ...aaCounts
    }

    let posPks = { ...POSITIVE_PKS }
    let negPks = { ...NEGATIVE_PKS }
    const nterm = s[0]
    const cterm = s[s.length - 1]
    if (nterm in PK_N_TERMINAL) {
        posPks = { ...posPks, Nterm: PK_N_TERMINAL[nterm]! }
    }
    if (cterm in PK_C_TERMINAL) {
        negPks = { ...negPks, Cterm: PK_C_TERMINAL[cterm]! }
    }

    function chargeAtPh(pH: number): number {
        let positive = 0
        for (const [aa, pK] of Object.entries(posPks)) {
            const n = charged[aa] ?? 0
            positive += n * (1.0 / (10 ** (pH - pK) + 1.0))
        }
        let negative = 0
        for (const [aa, pK] of Object.entries(negPks)) {
            const n = charged[aa] ?? 0
            negative += n * (1.0 / (10 ** (pK - pH) + 1.0))
        }
        return positive - negative
    }

    let pH = 7.775
    let min_ = 4.05
    let max_ = 12
    while (true) {
        const charge = chargeAtPh(pH)
        if (max_ - min_ <= 0.0001) return pH
        if (charge > 0) min_ = pH
        else max_ = pH
        pH = (min_ + max_) / 2
    }
}

export function sequenceWarnings(aa: string): string[] {
    const s = codingSequenceBeforeStop(aa)
    const w: string[] = []
    if (s.includes('C')) w.push(WARNING_CONTAINS_CYS)
    if (molarExtinctionCoefficient(s).reduced < LOW_EXTINCTION_THRESHOLD) {
        w.push(WARNING_LOW_EXTINCTION)
    }
    return w
}
