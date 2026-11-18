// Mirrors the backend FilterSpec operator set (see FilterSetBuilder.vue) — kept as
// concise symbols/words for compact filter labels, shared by FilterChainSummary.vue.
const OPERATOR_SYMBOLS: Record<string, string> = {
    '<': '<',
    '<=': '≤',
    '>': '>',
    '>=': '≥',
    contains: 'contains',
    not_contains: 'not contains',
    starts_with: 'starts with',
    ends_with: 'ends with',
    equals: '=',
    not_equals: '≠',
    regex: 'matches',
    is_empty: 'is empty',
    is_not_empty: 'is not empty'
}

export interface FilterLabelParts {
    column: string
    operator: string
    threshold: number | null
    text_value: string | null
    /**
     * Target-contact stages arrive with a rendered description from the backend (their
     * `column` is an internal `__tc_*` name that means nothing to a reader), so it wins
     * over the operator/threshold formatting below.
     */
    label?: string
}

export function columnDisplayName(column: string): string {
    if (column === 'good') return 'Good'
    if (column === 'tag') return 'Tag'
    return column
}

export function formatFilterLabel(item: FilterLabelParts): string {
    if (item.label) return item.label
    if (item.column === 'good') {
        if (item.operator === 'equals' && item.text_value === 'true') return 'good'
        if (item.operator === 'equals' && item.text_value === 'false') return 'bad'
        if (item.operator === 'is_empty') return 'unrated'
    }
    const opLabel = OPERATOR_SYMBOLS[item.operator] ?? item.operator
    const column = columnDisplayName(item.column)
    if (item.operator === 'is_empty' || item.operator === 'is_not_empty') {
        return `${column} ${opLabel}`
    }
    if (item.text_value != null && item.text_value !== '') {
        return `${column} ${opLabel} "${item.text_value}"`
    }
    if (item.threshold != null) {
        return `${column} ${opLabel} ${item.threshold}`
    }
    return `${column} ${opLabel}`
}

/** Diversity-selection chain items use their own label (no threshold/operator symbol lookup). */
export function formatDiversityLabel(budget: number, alpha: number): string {
    return `Diversity: budget=${budget}, α=${alpha}`
}
