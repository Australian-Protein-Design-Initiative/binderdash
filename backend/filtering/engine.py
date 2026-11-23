"""Generic filter / rank / diversity-selection engine.

Adapted from boltzgen's ``Filter`` task (repos/boltzgen/src/boltzgen/task/filter/filter.py),
stripped of design-directory/refolding-file assumptions so it can operate on any
DataFrame of design metrics, for any run type (or an aggregate of several).

Pipeline (mirrors boltzgen's three phases):
1. ``apply_hard_filters`` — each design is checked against threshold filters; designs
   are not dropped, only annotated (``pass_<column>_filter``, ``num_filters_passed``,
   ``pass_filters``), so ranking can penalise (not eliminate) filter failures.
2. ``rank_designs`` — two modes. ``worst_rank`` is boltzgen "Algorithm 2": rank-based,
   not z-score/absolute, scoring. For each ranking metric, compute the row's rank on
   ``(num_filters_passed, metric)`` (descending, so passing more filters and having a
   better metric both help), divide by the metric's inverse-importance weight, then take
   the *worst* (max) scaled rank across metrics as the design's quality key. ``simple``
   is a lexicographic sort: more filters passed first, then the metrics in list order
   (first metric is the primary key, the next breaks ties).
3. ``select_diverse`` — lazy-greedy selection over sequence identity (BioPython pairwise
   alignment), trading off quality vs. diversity via ``alpha``, honouring optional
   per-length-bucket selection caps.

The tabular stages (1-2, plus the preview cascade) run on **polars**, not pandas:
benchmarked at 60k rows, pandas' ``.apply(tuple, axis=1)`` row-wise rank (needed to
replicate boltzgen's joint-lexicographic ranking) cost ~0.15s per metric and pandas'
overall in-memory footprint for string-heavy columns (``Sequence``) was ~2.4x polars'
Arrow-backed one; polars' equivalent ``struct().rank()` verified numerically identical
(including tie handling) and costs ~0.006s per metric. Stage 3 (diversity selection)
stays row-wise Python/numpy either way — the BioPython pairwise alignment inside the
lazy-greedy loop dominates total latency by 5-10x over the entire tabular stage at any
DataFrame library, so migrating it here would not move the number that matters; it's
tracked as a separate, likely-algorithmic (not DataFrame-library) optimisation.
"""

from __future__ import annotations

import heapq
import multiprocessing
import os
import random
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import polars as pl
from Bio import Align

from .metrics import METRIC_ALIASES, resolve_column_map_for_methods
from .schemas import (
    EMPTY_OPERATORS,
    NUMERIC_OPERATORS,
    STRING_OPERATORS,
    FilterCascadeStage,
    FilterSpec,
    RankingMetric,
    SizeBucket,
)

# Below this many pairwise alignments, ProcessPoolExecutor startup/pickling overhead
# outweighs the benefit — see PARALLEL_SEED_ALIGNMENT_MIN_PAIRS usage in select_diverse.
PARALLEL_SEED_ALIGNMENT_MIN_PAIRS = 200

_NUMERIC_OPS: Dict[str, Callable[[pl.Expr, float], pl.Expr]] = {
    "<": lambda e, t: e < t,
    "<=": lambda e, t: e <= t,
    ">": lambda e, t: e > t,
    ">=": lambda e, t: e >= t,
}

# contains/starts_with/ends_with are case-insensitive to match the prior client-side
# filters' UX (see plan §7A.1); equals/not_equals/regex are case-sensitive.
#
# Negated ops (not_contains, not_equals) null-coalesce the *positive* check first, then
# negate — a null value doesn't contain/equal anything, so it should pass a "not_*"
# filter. Negating an un-coalesced (possibly-null) expression and only then coalescing
# would instead force null rows to fail every "not_*" filter, which is backwards.
_STRING_OPS: Dict[str, Callable[[pl.Expr, str], pl.Expr]] = {
    "contains": lambda e, v: e.str.to_lowercase().str.contains(v.lower(), literal=True).fill_null(False),
    "not_contains": lambda e, v: ~e.str.to_lowercase().str.contains(v.lower(), literal=True).fill_null(False),
    "starts_with": lambda e, v: e.str.to_lowercase().str.starts_with(v.lower()).fill_null(False),
    "ends_with": lambda e, v: e.str.to_lowercase().str.ends_with(v.lower()).fill_null(False),
    "equals": lambda e, v: (e == v).fill_null(False),
    "not_equals": lambda e, v: ~(e == v).fill_null(False),
    "regex": lambda e, v: e.str.contains(v, literal=False).fill_null(False),
}


def _resolve_canonical(
    df: pl.DataFrame, column: str, method_column: str = "method"
) -> Optional[Tuple[pl.Expr, pl.Expr]]:
    """If ``column`` is a canonical metric name (see ``metrics.METRIC_ALIASES``) and
    ``df`` has a method column, build a per-row-resolved value expression plus an
    "applicable" expression (True where this row's method has *any* raw column for the
    metric at all).

    Returns ``None`` when ``column`` isn't canonical, there's no method column, or no
    method in ``df`` has an equivalent for it — callers fall back to treating ``column``
    as a literal raw column name in all of these cases.
    """
    if column not in METRIC_ALIASES or method_column not in df.columns:
        return None

    methods = sorted({str(m) for m in df[method_column].unique().to_list()})
    col_map = resolve_column_map_for_methods(column, methods, df.columns)
    if not any(col_map.values()):
        return None

    value_expr: pl.Expr = pl.lit(None, dtype=pl.Float64)
    applicable_expr: pl.Expr = pl.lit(False)
    for method, raw_col in col_map.items():
        if raw_col is None:
            continue
        cond = pl.col(method_column).cast(pl.Utf8) == method
        value_expr = pl.when(cond).then(pl.col(raw_col)).otherwise(value_expr)
        applicable_expr = pl.when(cond).then(pl.lit(True)).otherwise(applicable_expr)
    return value_expr, applicable_expr


def _good_text_expr(df: pl.DataFrame) -> pl.Expr:
    """``good`` as ``"true"`` / ``"false"`` / null, whatever dtype the cache stored.

    The column is a bool once it has been rated, but a merged table can leave it as
    0/1 or the strings ``true``/``false``. String filters compare against ``"true"``
    and ``"false"``.
    """
    if "good" not in df.columns:
        return pl.lit(None, dtype=pl.Utf8)
    expr = pl.col("good")
    dtype = df.schema["good"]
    if dtype == pl.Boolean or dtype.is_numeric():
        flag = expr if dtype == pl.Boolean else expr.cast(pl.Boolean)
        return (
            pl.when(expr.is_null())
            .then(pl.lit(None, dtype=pl.Utf8))
            .when(flag)
            .then(pl.lit("true"))
            .otherwise(pl.lit("false"))
        )
    text = expr.cast(pl.Utf8).str.strip_chars().str.to_lowercase()
    return (
        pl.when(expr.is_null() | (text == ""))
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(text.is_in(["true", "1", "yes"]))
        .then(pl.lit("true"))
        .when(text.is_in(["false", "0", "no"]))
        .then(pl.lit("false"))
        .otherwise(text)
    )


def _operator_mask(col: pl.Expr, spec: FilterSpec) -> pl.Expr:
    """Boolean expression for one filter's operator, given the (already-resolved) value
    expression to test. Nulls fail non-empty-checks (conservative default for a value
    that's genuinely missing/NA on an otherwise-applicable row).
    """
    if spec.operator in EMPTY_OPERATORS:
        is_empty = col.is_null() | (col.cast(pl.Utf8) == "")
        return is_empty if spec.operator == "is_empty" else ~is_empty

    if spec.operator in NUMERIC_OPERATORS:
        if spec.threshold is None:
            return pl.lit(False)
        return _NUMERIC_OPS[spec.operator](col, spec.threshold).fill_null(False)

    if spec.operator in STRING_OPERATORS:
        if spec.text_value is None:
            return pl.lit(False)
        return _STRING_OPS[spec.operator](col.cast(pl.Utf8), spec.text_value).fill_null(False)

    raise ValueError(f"Unknown filter operator: {spec.operator}")


def _filter_mask(df: pl.DataFrame, spec: FilterSpec) -> pl.Expr:
    """Boolean expression for one filter.

    ``spec.column`` is first tried as a canonical metric name (e.g. ``pae_interaction``)
    resolved per-row via each row's ``method`` — a design whose method has no equivalent
    for the metric at all is *exempted* (passes) rather than failed, since the filter
    doesn't apply to it; a design whose method does have the metric but whose value is
    null still fails, since that's a genuine per-design NA. Falls back to treating
    ``spec.column`` as a literal raw column name (missing columns fail every row, the
    prior conservative default) when it isn't a recognised canonical name.
    """
    resolved = _resolve_canonical(df, spec.column)
    if resolved is not None:
        value_expr, applicable_expr = resolved
        return pl.when(applicable_expr).then(_operator_mask(value_expr, spec)).otherwise(pl.lit(True))

    # Good/Tag are user annotations. Until anyone sets them the key is absent from
    # every design dict, which is the same as all-null: "is empty" matches every row
    # and a value match matches none. ``good`` is compared as "true"/"false" text so
    # a boolean, 0/1, or "True" column all accept the same filter.
    if spec.column == "good" and spec.operator in (*STRING_OPERATORS, *EMPTY_OPERATORS):
        return _operator_mask(_good_text_expr(df), spec)
    if spec.column == "tag" and spec.column not in df.columns:
        if spec.operator in (*STRING_OPERATORS, *EMPTY_OPERATORS):
            return _operator_mask(pl.lit(None, dtype=pl.Utf8), spec)
        return pl.lit(False)

    if spec.column not in df.columns:
        return pl.lit(False)

    return _operator_mask(pl.col(spec.column), spec)


def apply_hard_filters(df: pl.DataFrame, filters: List[FilterSpec]) -> pl.DataFrame:
    """Return a copy of ``df`` annotated with per-filter pass columns.

    Adds ``pass_<column>_filter`` for each filter, plus ``num_filters_passed`` (count of
    filters passed) and ``pass_filters`` (all filters passed). Filters whose column is
    missing from ``df`` are treated as failed for every row (conservative default).
    """
    out = df
    filter_cols: List[str] = []

    for spec in filters:
        col_name = f"pass_{spec.column}_filter"
        filter_cols.append(col_name)
        out = out.with_columns(_filter_mask(out, spec).alias(col_name))

    if filter_cols:
        out = out.with_columns(
            pl.sum_horizontal([pl.col(c).cast(pl.Int64) for c in filter_cols]).alias(
                "num_filters_passed"
            ),
            pl.all_horizontal([pl.col(c) for c in filter_cols]).alias("pass_filters"),
        )
    else:
        out = out.with_columns(
            pl.lit(0).alias("num_filters_passed"), pl.lit(True).alias("pass_filters")
        )

    return out


def filter_cascade_counts(df: pl.DataFrame, filters: List[FilterSpec]) -> List[FilterCascadeStage]:
    """Sequentially apply filters, reporting the remaining count after each stage.

    Used for the preview endpoint's per-stage cascade (each stage's "remaining" is the
    input to the next stage), distinct from ``apply_hard_filters``'s independent
    (non-cascading) per-filter annotation used for ranking.
    """
    stages: List[FilterCascadeStage] = []
    remaining = df
    for spec in filters:
        mask = _filter_mask(remaining, spec)
        remaining = remaining.filter(mask)
        stages.append(
            FilterCascadeStage(
                column=spec.column,
                operator=spec.operator,
                threshold=spec.threshold,
                text_value=spec.text_value,
                remaining=remaining.height,
            )
        )
    return stages


def _metric_value_expr(df: pl.DataFrame, metric: RankingMetric) -> Optional[pl.Expr]:
    """Raw metric value for one ranking row, or ``None`` when the metric is skipped.

    A weight of 0 drops the metric. A canonical name is resolved per row; a method
    with no equivalent contributes null (sorts last). A literal column that is absent
    from ``df`` is skipped.
    """
    if metric.weight == 0:
        return None
    resolved = _resolve_canonical(df, metric.column)
    if resolved is not None:
        raw_value_expr, applicable_expr = resolved
        return pl.when(applicable_expr).then(raw_value_expr).otherwise(None)
    if metric.column in df.columns:
        return pl.col(metric.column)
    return None


def _stamp_final_rank(out: pl.DataFrame) -> pl.DataFrame:
    """``final_rank`` is 1…N in the current row order; ``quality_score`` is 1…0."""
    n = out.height
    out = out.with_columns(pl.Series("final_rank", np.arange(1, n + 1)))
    denom = max(n - 1, 1)
    return out.with_columns(
        (1 - (pl.col("final_rank") - 1) / denom).alias("quality_score")
    )


def rank_designs(
    df: pl.DataFrame,
    metrics: List[RankingMetric],
    tiebreak_column: Optional[str] = None,
    mode: str = "worst_rank",
) -> pl.DataFrame:
    """Rank designs and stamp ``final_rank`` (1 = best) and ``quality_score``.

    ``mode="worst_rank"`` is boltzgen Algorithm 2: each metric's rank on
    ``(num_filters_passed, value)`` is divided by its inverse-importance weight, and
    the worst (max) scaled rank decides the order.

    ``mode="simple"`` sorts lexicographically. Passing more filters comes first, then
    the metrics in list order — the first is the primary key, the next breaks ties.
    Weights are ignored. Null metric values sort last.

    Requires ``num_filters_passed`` to already be present (see ``apply_hard_filters``).
    """
    if mode == "simple":
        return _rank_designs_simple(df, metrics, tiebreak_column=tiebreak_column)
    if mode != "worst_rank":
        raise ValueError(f"Unknown ranking mode: {mode}")
    return _rank_designs_worst(df, metrics, tiebreak_column=tiebreak_column)


def _rank_designs_worst(
    df: pl.DataFrame,
    metrics: List[RankingMetric],
    tiebreak_column: Optional[str] = None,
) -> pl.DataFrame:
    out = df
    if "num_filters_passed" not in out.columns:
        out = out.with_columns(pl.lit(0).alias("num_filters_passed"))

    rank_cols: List[str] = []
    for metric in metrics:
        metric_expr = _metric_value_expr(out, metric)
        if metric_expr is None:
            continue
        value_expr = metric_expr if metric.higher_is_better else -metric_expr
        rank_col = f"rank_{metric.column}"
        rank_cols.append(rank_col)
        out = out.with_columns(
            (
                pl.struct(["num_filters_passed", value_expr.alias("_v")]).rank(
                    method="min", descending=True
                )
                / metric.weight
            ).alias(rank_col)
        )

    if not rank_cols:
        out = out.with_columns(pl.lit(1.0).alias("max_rank"))
    else:
        out = out.with_columns(pl.max_horizontal(rank_cols).alias("max_rank"))

    sort_cols = ["max_rank"]
    descending = [False]
    if tiebreak_column and tiebreak_column in out.columns:
        sort_cols.append(tiebreak_column)
        descending.append(True)

    out = out.sort(by=sort_cols, descending=descending)
    return _stamp_final_rank(out)


def _rank_designs_simple(
    df: pl.DataFrame,
    metrics: List[RankingMetric],
    tiebreak_column: Optional[str] = None,
) -> pl.DataFrame:
    out = df
    if "num_filters_passed" not in out.columns:
        out = out.with_columns(pl.lit(0).alias("num_filters_passed"))

    sort_cols = ["num_filters_passed"]
    descending = [True]
    helper_cols: List[str] = []
    used_columns = set()
    for index, metric in enumerate(metrics):
        metric_expr = _metric_value_expr(out, metric)
        if metric_expr is None:
            continue
        helper = f"_simple_{index}"
        helper_cols.append(helper)
        used_columns.add(metric.column)
        out = out.with_columns(metric_expr.alias(helper))
        sort_cols.append(helper)
        descending.append(metric.higher_is_better)

    if (
        tiebreak_column
        and tiebreak_column in out.columns
        and tiebreak_column not in used_columns
    ):
        sort_cols.append(tiebreak_column)
        descending.append(True)

    out = out.sort(by=sort_cols, descending=descending, nulls_last=True)
    if helper_cols:
        out = out.drop(helper_cols)
    out = out.with_columns(pl.lit(None).cast(pl.Float64).alias("max_rank"))
    return _stamp_final_rank(out)


def _bucket_index(length: int, size_buckets: List[SizeBucket]) -> Optional[int]:
    for idx, bucket in enumerate(size_buckets):
        if bucket.min <= length < bucket.max:
            return idx
    return None


def select_lazy_greedy(
    quality: np.ndarray,
    sim_fn: Callable[[int, int], float],
    budget: int,
    alpha: float,
    lengths: Optional[List[int]] = None,
    size_buckets: Optional[List[SizeBucket]] = None,
    random_state: int = 0,
) -> List[int]:
    """Lazy-greedy selection maximising ``(1 - alpha) * quality + alpha * (1 - sim)``.

    Returns positional indices into ``quality`` (sorted ascending), mirroring
    boltzgen's ``select_lazy_greedy``. ``sim_fn(i, j)`` must return a symmetric
    similarity in [0, 1] (1 = identical).

    Row-wise Python/numpy, independent of the tabular DataFrame library — the pairwise
    BioPython alignment inside this loop is the actual latency bottleneck at scale (see
    module docstring), not the DataFrame operations feeding it.
    """
    n = len(quality)
    if n <= budget:
        return list(range(n))

    size_buckets = size_buckets or []
    random.seed(random_state)
    np.random.seed(random_state)

    selected = [int(np.argmax(quality))]
    remaining = set(range(n)) - set(selected)

    heap: List[Tuple[float, int]] = []
    for i in remaining:
        div = 1 - sim_fn(i, selected[0])
        gain = (1 - alpha) * quality[i] + alpha * div
        heapq.heappush(heap, (-gain, i))

    buckets = np.zeros(len(size_buckets) + 1)
    if lengths is not None:
        first_bucket = _bucket_index(lengths[selected[0]], size_buckets)
        buckets[first_bucket if first_bucket is not None else len(size_buckets)] += 1

    for _ in range(budget - 1):
        if not heap:
            break
        while heap:
            _neg_gain, cand = heapq.heappop(heap)

            bucket_idx = None
            if lengths is not None:
                bucket_idx = _bucket_index(lengths[cand], size_buckets)
                bucket_full = (
                    bucket_idx is not None
                    and buckets[bucket_idx] == size_buckets[bucket_idx].num_designs
                )
                if bucket_full:
                    continue

            true_div = 1 - max(sim_fn(cand, j) for j in selected)
            true_gain = (1 - alpha) * quality[cand] + alpha * true_div
            heapq.heappush(heap, (-true_gain, cand))

            if heap[0][1] == cand:
                heapq.heappop(heap)
                selected.append(cand)
                remaining.discard(cand)
                if lengths is not None:
                    buckets[bucket_idx if bucket_idx is not None else len(size_buckets)] += 1
                break

    return sorted(selected)


def sequence_similarity_fn(
    sequences: List[str], initial_cache: Optional[Dict[Tuple[int, int], float]] = None
) -> Callable[[int, int], float]:
    """Build a cached pairwise-identity similarity function over ``sequences``.

    Identity is normalised by the longer of the two sequences, matching boltzgen.
    ``initial_cache`` pre-seeds the cache (see ``_parallel_seed_similarities``) so
    already-computed pairs don't get recomputed.
    """
    aligner = Align.PairwiseAligner()
    cache: Dict[Tuple[int, int], float] = dict(initial_cache or {})

    def sim(i: int, j: int) -> float:
        if i == j:
            return 1.0
        key = (i, j) if i < j else (j, i)
        if key not in cache:
            seq1, seq2 = sequences[i], sequences[j]
            denom = max(len(seq1), len(seq2))
            # Two empty sequences are identical, not maximally diverse — and the
            # normalisation would divide by zero. select_diverse excludes empties
            # before reaching here; this guards direct callers.
            cache[key] = 1.0 if denom == 0 else aligner.align(seq1, seq2)[0].score / denom
        return cache[key]

    return sim


# Worker-process globals for ProcessPoolExecutor — BioPython's PairwiseAligner does not
# release the GIL (measured: threads gave zero speedup; processes gave ~4-9x on 4-16
# cores), so real parallelism needs separate processes. The aligner is constructed once
# per worker via the pool initializer, not per task, and only plain strings cross the
# process boundary (cheap to pickle) — no approximation, exact same alignment algorithm
# and result as the serial path, just computed concurrently.
_worker_aligner: Optional[Align.PairwiseAligner] = None


def _init_alignment_worker() -> None:
    global _worker_aligner
    _worker_aligner = Align.PairwiseAligner()


def _align_score(pair: Tuple[str, str]) -> float:
    assert _worker_aligner is not None
    seq1, seq2 = pair
    return _worker_aligner.align(seq1, seq2)[0].score


def _parallel_seed_similarities(
    sequences: List[str],
    seed_idx: int,
    candidate_indices: List[int],
    max_workers: Optional[int] = None,
) -> Dict[Tuple[int, int], float]:
    """Compute sim(seed_idx, i) for every candidate, in parallel.

    This is the single largest batch of independent pairwise alignments in diversity
    selection — the lazy-greedy heap's initial population requires exactly this
    O(n-1)-against-one comparison before any candidate can be selected — so it's the
    highest-leverage, safest thing to parallelise: fully independent per pair, no
    algorithmic change, same exact scores as computing them one at a time.
    """
    pairs = [(sequences[seed_idx], sequences[i]) for i in candidate_indices]
    if len(pairs) < PARALLEL_SEED_ALIGNMENT_MIN_PAIRS:
        aligner = Align.PairwiseAligner()
        scores = [aligner.align(s1, s2)[0].score for s1, s2 in pairs]
    else:
        if max_workers is None:
            max_workers = (
                len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
            )
        workers = max(1, min(max_workers, 16))  # diminishing returns observed past ~16
        chunksize = max(1, len(pairs) // (workers * 4))
        # Explicit "spawn": the default "fork" start method is unsafe here — this code
        # runs inside asyncio.to_thread from a FastAPI request handler, i.e. an already
        # multi-threaded process, and fork()ing a multi-threaded process risks deadlocks
        # in the child (observed as a DeprecationWarning from Python's own multiprocessing
        # module during testing). Spawn is slightly slower to start but correct.
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init_alignment_worker, mp_context=ctx
        ) as ex:
            scores = list(ex.map(_align_score, pairs, chunksize=chunksize))

    result: Dict[Tuple[int, int], float] = {}
    for idx, score in zip(candidate_indices, scores):
        length = max(len(sequences[seed_idx]), len(sequences[idx]))
        key = (seed_idx, idx) if seed_idx < idx else (idx, seed_idx)
        result[key] = 1.0 if length == 0 else score / length
    return result


def has_usable_sequence(sequence_col: str) -> pl.Expr:
    """Rows whose sequence is present and non-blank — the only ones diversity can score."""
    col = pl.col(sequence_col).cast(pl.Utf8)
    return col.is_not_null() & (col.str.strip_chars().str.len_chars() > 0)


def count_missing_sequences(df: pl.DataFrame, sequence_col: Optional[str]) -> int:
    """How many rows ``select_diverse`` would drop. ``df.height`` if the column is absent."""
    if not sequence_col or sequence_col not in df.columns:
        return df.height
    return df.height - int(df.select(has_usable_sequence(sequence_col).sum()).item() or 0)


# Same primary/secondary scores as frontend METHOD_BEST_SCORE. Secondary ties use the
# primary direction, matching the Designs-table collapse.
_MPNN_BEST_SCORE: Dict[str, Tuple[str, Tuple[str, ...], bool]] = {
    "bindcraft": ("Average_i_pTM", ("Average_Binder_pLDDT",), True),
    "rfd": ("pae_interaction", ("plddt_binder",), False),
    "boltzgen": ("design_to_target_iptm", ("design_ptm",), True),
    "rfd3": ("iptm", ("rf3_ipsae_min",), True),
    "bindcraft2": ("i_pDAE", ("i_pTM",), True),
    "rfd4_proteina": ("oracle_ppi_iptm_coi", ("oracle_ppi_plddt_coi",), True),
}


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _mpnn_variant_is_better(challenger: Dict[str, Any], current: Dict[str, Any]) -> bool:
    """Whether ``challenger`` should replace ``current`` as the best variant of a backbone."""
    cfg = _MPNN_BEST_SCORE.get(str(challenger.get("method") or ""))
    if cfg is None:
        return False
    primary, secondary, higher = cfg
    primary_challenger = _as_float(challenger.get(primary))
    if primary_challenger is None:
        return False
    primary_current = _as_float(current.get(primary))
    if primary_current is None:
        return True
    if primary_challenger != primary_current:
        return primary_challenger > primary_current if higher else primary_challenger < primary_current
    for field in secondary:
        score_challenger = _as_float(challenger.get(field))
        score_current = _as_float(current.get(field))
        if score_challenger is None or score_current is None:
            continue
        if score_challenger != score_current:
            return score_challenger > score_current if higher else score_challenger < score_current
    return False


def keep_best_mpnn_per_backbone(df: pl.DataFrame) -> pl.DataFrame:
    """One design per ``backbone_id`` (best primary score). Rows with no backbone are kept.

    Runs before diversity selection so the budget is spent on distinct backbones rather
    than on MPNN variants of a backbone already chosen.
    """
    if df.is_empty() or "backbone_id" not in df.columns:
        return df
    indexed = df.with_row_index("__mpnn_idx")
    keep_idx: List[int] = []
    groups: Dict[str, List[Dict[str, Any]]] = {}
    group_order: List[str] = []
    for row in indexed.iter_rows(named=True):
        backbone = row.get("backbone_id")
        if backbone is None or (isinstance(backbone, str) and not backbone.strip()):
            keep_idx.append(int(row["__mpnn_idx"]))
            continue
        key = str(backbone)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(row)
    for key in group_order:
        rows = groups[key]
        best = rows[0]
        for challenger in rows[1:]:
            if _mpnn_variant_is_better(challenger, best):
                best = challenger
        keep_idx.append(int(best["__mpnn_idx"]))
    return indexed.filter(pl.col("__mpnn_idx").is_in(keep_idx)).drop("__mpnn_idx")


def select_diverse(
    df: pl.DataFrame,
    sequence_col: str,
    budget: int,
    alpha: float,
    size_buckets: Optional[List[SizeBucket]] = None,
    random_state: int = 0,
    quality_col: str = "quality_score",
    max_workers: Optional[int] = None,
) -> pl.DataFrame:
    """Run lazy-greedy diversity selection over ``df`` (already ranked; see ``rank_designs``).

    Returns the selected subset, in the original row order of ``df``. When there's
    enough work to be worth it, the initial seed-vs-all-candidates alignment batch (see
    ``_parallel_seed_similarities``) runs across multiple processes; the rest of the
    lazy-greedy loop is unchanged and produces identical results either way.

    Designs without a usable sequence are **excluded** from the pool, not blank-filled.
    A blank sequence aligns to zero against everything, so its normalised identity is 0 —
    maximally dissimilar — which makes the diversity term *prefer* exactly the designs we
    know least about. Use ``count_missing_sequences`` to report the exclusion.
    """
    df = df.filter(has_usable_sequence(sequence_col))
    if df.is_empty():
        return df
    sequences = df[sequence_col].cast(pl.Utf8).to_list()
    quality = df[quality_col].to_numpy()
    lengths = [len(s) for s in sequences]

    initial_cache: Dict[Tuple[int, int], float] = {}
    n = len(quality)
    if n > budget:
        # Mirrors select_lazy_greedy's own (deterministic) seed choice exactly.
        seed_idx = int(np.argmax(quality))
        candidate_indices = [i for i in range(n) if i != seed_idx]
        initial_cache = _parallel_seed_similarities(
            sequences, seed_idx, candidate_indices, max_workers=max_workers
        )

    sim_fn = sequence_similarity_fn(sequences, initial_cache=initial_cache)
    selected = select_lazy_greedy(
        quality=quality,
        sim_fn=sim_fn,
        budget=budget,
        alpha=alpha,
        lengths=lengths,
        size_buckets=size_buckets,
        random_state=random_state,
    )
    return df[selected]


def run_filtering_pipeline(
    df: pl.DataFrame,
    filters: List[FilterSpec],
    metrics: List[RankingMetric],
    budget: int,
    alpha: float,
    sequence_col: Optional[str] = None,
    tiebreak_column: Optional[str] = None,
    size_buckets: Optional[List[SizeBucket]] = None,
    random_state: int = 0,
    apply_diversity: bool = True,
    ranking_mode: str = "worst_rank",
    best_mpnn_only: bool = False,
) -> Tuple[pl.DataFrame, Optional[pl.DataFrame]]:
    """Run the full filter -> rank -> diversity pipeline.

    Returns ``(ranked_df, diverse_df)``. ``ranked_df`` covers every input design
    (pass or fail the hard filters), annotated with ``pass_filters``/``final_rank``/
    ``quality_score`` — used for the full per-design table (see
    ``SavedSetDesignsResponse``). ``diverse_df`` is the diversity-selected subset,
    picked only from designs that passed every hard filter (a design that fails a
    filter must never end up in the saved/diverse set); it's ``None`` when
    ``apply_diversity`` is True but ``sequence_col`` is not provided or absent from
    ``df`` (quality-only ranking).

    When ``apply_diversity`` is False, ``diverse_df`` is every design that passed the
    hard filters (no budget / lazy-greedy pass) — used when the user turns diversity
    selection off and wants the saved set to be "all that pass".

    Designs whose sequence is missing or blank are excluded from ``diverse_df`` when
    diversity selection runs (see ``select_diverse``), so it can be smaller than
    ``budget`` — or empty — even when plenty of designs passed the filters. Callers
    should report that with ``count_missing_sequences`` rather than leave the
    shortfall unexplained.

    When ``best_mpnn_only`` is set and diversity selection runs, candidates that share a
    ``backbone_id`` are reduced to the best primary-score variant first (see
    ``keep_best_mpnn_per_backbone``). Designs with no backbone are kept. The flag does
    not change the set used when diversity selection is off.
    """
    filtered = apply_hard_filters(df, filters)
    ranked = rank_designs(
        filtered, metrics, tiebreak_column=tiebreak_column, mode=ranking_mode
    )

    candidates = ranked.filter(pl.col("pass_filters")) if "pass_filters" in ranked.columns else ranked
    diverse_df: Optional[pl.DataFrame] = None
    if not apply_diversity:
        diverse_df = candidates
    elif sequence_col and sequence_col in ranked.columns:
        if best_mpnn_only:
            candidates = keep_best_mpnn_per_backbone(candidates)
        diverse_df = select_diverse(
            candidates,
            sequence_col=sequence_col,
            budget=budget,
            alpha=alpha,
            size_buckets=size_buckets,
            random_state=random_state,
        )

    return ranked, diverse_df
