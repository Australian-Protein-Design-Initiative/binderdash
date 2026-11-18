import pandas as pd
import polars as pl
import pytest

import backend.filtering.engine as engine_mod
from backend.filtering.engine import (
    apply_hard_filters,
    count_missing_sequences,
    filter_cascade_counts,
    keep_best_mpnn_per_backbone,
    rank_designs,
    run_filtering_pipeline,
    select_diverse,
    select_lazy_greedy,
    sequence_similarity_fn,
)
from backend.filtering.metrics import is_excluded_metric_column, resolve_column, resolve_column_per_row
from backend.filtering.schemas import FilterSpec, RankingMetric, SizeBucket


def _df():
    return pl.DataFrame(
        {
            "design_id": ["a", "b", "c", "d"],
            "iptm": [0.9, 0.5, 0.8, 0.85],
            "rmsd": [1.0, 3.0, 2.0, 5.0],
            "sequence": ["AAAAAAAAAA", "AAAAAAAAAB", "CCCCCCCCCC", "CCCCCCCCCD"],
        }
    )


class TestApplyHardFilters:
    def test_pass_and_fail_columns(self):
        df = _df()
        filters = [FilterSpec(column="rmsd", operator="<", threshold=2.5)]
        out = apply_hard_filters(df, filters)

        assert out["pass_rmsd_filter"].to_list() == [True, False, True, False]
        assert out["num_filters_passed"].to_list() == [1, 0, 1, 0]
        assert out["pass_filters"].to_list() == [True, False, True, False]

    def test_missing_column_fails_all(self):
        df = _df()
        filters = [FilterSpec(column="does_not_exist", operator="<", threshold=1.0)]
        out = apply_hard_filters(df, filters)
        assert not out["pass_filters"].any()

    def test_no_filters_all_pass(self):
        df = _df()
        out = apply_hard_filters(df, [])
        assert out["pass_filters"].all()

    def test_operators(self):
        df = _df()
        assert apply_hard_filters(df, [FilterSpec(column="rmsd", operator="<=", threshold=2.0)])[
            "pass_filters"
        ].sum() == 2
        assert apply_hard_filters(df, [FilterSpec(column="iptm", operator=">", threshold=0.85)])[
            "pass_filters"
        ].sum() == 1
        assert apply_hard_filters(df, [FilterSpec(column="iptm", operator=">=", threshold=0.85)])[
            "pass_filters"
        ].sum() == 2


def _cross_method_df():
    """Mimics the reported bug: an rfd run (raw column ``pae_interaction``) and a
    bindcraft run (raw column ``Average_i_pAE``) aggregated together, plus an rfd3 row
    that has neither raw column (no pae equivalent in this fixture).
    """
    return pl.DataFrame(
        {
            "design_id": ["rfd1", "rfd2", "bc1", "bc2", "rfd3_1"],
            "method": ["rfd", "rfd", "bindcraft", "bindcraft", "rfd3"],
            "pae_interaction": [5.0, 15.0, None, None, None],
            "Average_i_pAE": [None, None, 8.0, 20.0, None],
        }
    )


class TestCanonicalCrossMethodFilters:
    def test_filter_on_canonical_name_resolves_per_method(self):
        df = _cross_method_df()
        out = apply_hard_filters(
            df, [FilterSpec(column="pae_interaction", operator="<=", threshold=10)]
        )
        # rfd1 (5.0) and bc1 (8.0) pass on their respective raw columns; rfd2 (15.0) and
        # bc2 (20.0) fail on value; rfd3_1 has no pae equivalent at all and is exempted.
        assert out.filter(pl.col("design_id") == "rfd1")["pass_filters"].item() is True
        assert out.filter(pl.col("design_id") == "bc1")["pass_filters"].item() is True
        assert out.filter(pl.col("design_id") == "rfd2")["pass_filters"].item() is False
        assert out.filter(pl.col("design_id") == "bc2")["pass_filters"].item() is False
        assert out.filter(pl.col("design_id") == "rfd3_1")["pass_filters"].item() is True

    def test_filter_on_raw_column_name_unaffected(self):
        # Filtering on the literal raw column name (not the canonical name) keeps the
        # prior single-method behaviour: only rows with that literal column populated
        # can pass, everyone else fails (including rows of other methods).
        df = _cross_method_df()
        out = apply_hard_filters(
            df, [FilterSpec(column="Average_i_pAE", operator="<=", threshold=10)]
        )
        assert out.filter(pl.col("design_id") == "bc1")["pass_filters"].item() is True
        assert out.filter(pl.col("design_id") == "bc2")["pass_filters"].item() is False
        assert out.filter(pl.col("design_id") == "rfd1")["pass_filters"].item() is False

    def test_rank_on_canonical_name_resolves_per_method(self):
        df = _cross_method_df()
        ranked = rank_designs(
            df, [RankingMetric(column="pae_interaction", weight=1, higher_is_better=False)]
        )
        # Lower pae_interaction is better (higher_is_better=False): rfd1 (5.0) beats
        # bc1 (8.0); the rfd3 row has no equivalent at all and should rank worst.
        by_id = {row["design_id"]: row["final_rank"] for row in ranked.iter_rows(named=True)}
        assert by_id["rfd1"] < by_id["bc1"] < by_id["rfd2"] < by_id["bc2"]
        assert by_id["rfd3_1"] == max(by_id.values())


def _text_df():
    return pl.DataFrame(
        {
            "design_id": ["a", "b", "c", "d", "e"],
            "name": ["Boltzgen_1", "rfd_design_2", "BINDCRAFT_3", "", None],
        }
    )


class TestStringOperators:
    def test_contains_case_insensitive(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="contains", text_value="design")])
        assert out["pass_filters"].to_list() == [False, True, False, False, False]

    def test_not_contains(self):
        df = _text_df()
        out = apply_hard_filters(
            df, [FilterSpec(column="name", operator="not_contains", text_value="design")]
        )
        # nulls/empty are not-null-safe False for the positive contains check, so
        # not_contains treats them as passing (they definitely don't contain "design").
        assert out["pass_filters"].to_list() == [True, False, True, True, True]

    def test_starts_with_case_insensitive(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="starts_with", text_value="bindcraft")])
        assert out["pass_filters"].to_list() == [False, False, True, False, False]

    def test_ends_with(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="ends_with", text_value="_2")])
        assert out["pass_filters"].to_list() == [False, True, False, False, False]

    def test_equals_case_sensitive(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="equals", text_value="Boltzgen_1")])
        assert out["pass_filters"].to_list() == [True, False, False, False, False]

    def test_not_equals(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="not_equals", text_value="Boltzgen_1")])
        assert out["pass_filters"].to_list() == [False, True, True, True, True]

    def test_regex(self):
        df = _text_df()
        # anchored pattern: exactly one run of lowercase letters, "_", then digits —
        # "rfd_design_2" has an extra "_design" segment so it should NOT match despite
        # ending in "_2".
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="regex", text_value=r"^[a-z]+_\d+$")])
        assert out["pass_filters"].to_list() == [False, False, False, False, False]

    def test_regex_matches_expected_rows(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="regex", text_value=r"design")])
        assert out["pass_filters"].to_list() == [False, True, False, False, False]

    def test_missing_text_value_fails_all(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="contains", text_value=None)])
        assert not out["pass_filters"].any()


class TestGoodAndTagFilters:
    def test_good_true_false_and_unrated(self):
        df = pl.DataFrame(
            {
                "design_id": ["a", "b", "c"],
                "good": [True, False, None],
                "tag": ["N", "C", None],
            }
        )
        good = apply_hard_filters(
            df, [FilterSpec(column="good", operator="equals", text_value="true")]
        )
        bad = apply_hard_filters(
            df, [FilterSpec(column="good", operator="equals", text_value="false")]
        )
        unrated = apply_hard_filters(df, [FilterSpec(column="good", operator="is_empty")])
        tagged_n = apply_hard_filters(
            df, [FilterSpec(column="tag", operator="equals", text_value="N")]
        )
        assert good["pass_filters"].to_list() == [True, False, False]
        assert bad["pass_filters"].to_list() == [False, True, False]
        assert unrated["pass_filters"].to_list() == [False, False, True]
        assert tagged_n["pass_filters"].to_list() == [True, False, False]

    def test_missing_good_and_tag_are_unrated(self):
        df = pl.DataFrame({"design_id": ["a", "b"]})
        unrated = apply_hard_filters(df, [FilterSpec(column="good", operator="is_empty")])
        good = apply_hard_filters(
            df, [FilterSpec(column="good", operator="equals", text_value="true")]
        )
        empty_tag = apply_hard_filters(df, [FilterSpec(column="tag", operator="is_empty")])
        assert unrated["pass_filters"].to_list() == [True, True]
        assert good["pass_filters"].to_list() == [False, False]
        assert empty_tag["pass_filters"].to_list() == [True, True]

    def test_good_numeric_zero_one(self):
        df = pl.DataFrame({"design_id": ["a", "b"], "good": [1, 0]})
        good = apply_hard_filters(
            df, [FilterSpec(column="good", operator="equals", text_value="true")]
        )
        bad = apply_hard_filters(
            df, [FilterSpec(column="good", operator="equals", text_value="false")]
        )
        assert good["pass_filters"].to_list() == [True, False]
        assert bad["pass_filters"].to_list() == [False, True]


class TestEmptyOperators:
    def test_is_empty_matches_null_and_empty_string(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="is_empty")])
        assert out["pass_filters"].to_list() == [False, False, False, True, True]

    def test_is_not_empty(self):
        df = _text_df()
        out = apply_hard_filters(df, [FilterSpec(column="name", operator="is_not_empty")])
        assert out["pass_filters"].to_list() == [True, True, True, False, False]


class TestFilterCascadeCounts:
    def test_sequential_narrowing(self):
        df = _df()
        filters = [
            FilterSpec(column="rmsd", operator="<", threshold=4.0),
            FilterSpec(column="iptm", operator=">", threshold=0.7),
        ]
        stages = filter_cascade_counts(df, filters)
        assert len(stages) == 2
        assert stages[0].remaining == 3  # a, b, c pass rmsd<4
        assert stages[1].remaining == 2  # of those, a and c also have iptm>0.7


class TestRankDesigns:
    def test_higher_is_better_ranks_best_first(self):
        df = apply_hard_filters(_df(), [])
        ranked = rank_designs(df, [RankingMetric(column="iptm", weight=1, higher_is_better=True)])
        assert ranked[0, "design_id"] == "a"  # highest iptm
        assert ranked["final_rank"].to_list() == [1, 2, 3, 4]
        assert ranked[0, "quality_score"] == 1.0
        assert ranked[-1, "quality_score"] == 0.0

    def test_lower_is_better_metric(self):
        df = apply_hard_filters(_df(), [])
        ranked = rank_designs(df, [RankingMetric(column="rmsd", weight=1, higher_is_better=False)])
        assert ranked[0, "design_id"] == "a"  # lowest rmsd

    def test_filter_failure_penalises_rank(self):
        df = apply_hard_filters(_df(), [FilterSpec(column="rmsd", operator="<", threshold=2.5)])
        ranked = rank_designs(df, [RankingMetric(column="iptm", weight=1, higher_is_better=True)])
        # "d" has the 3rd-highest iptm but fails the filter, so despite iptm=0.85
        # it should rank below designs that passed filters, even ones with lower iptm.
        passing_ranks = ranked.filter(pl.col("pass_filters"))["final_rank"]
        failing_ranks = ranked.filter(~pl.col("pass_filters"))["final_rank"]
        assert passing_ranks.max() < failing_ranks.min()

    def test_worst_case_across_multiple_metrics(self):
        # "b" is best on iptm-adjacent metric but worst on rmsd; the worst-case (max)
        # rank should push it down even though one metric favours it.
        df = apply_hard_filters(_df(), [])
        ranked = rank_designs(
            df,
            [
                RankingMetric(column="iptm", weight=1, higher_is_better=True),
                RankingMetric(column="rmsd", weight=1, higher_is_better=False),
            ],
        )
        assert ranked[0, "design_id"] == "a"

    def test_no_metrics_leaves_all_tied(self):
        df = apply_hard_filters(_df(), [])
        ranked = rank_designs(df, [])
        assert (ranked["max_rank"] == 1).all()

    def test_tiebreak_column(self):
        df = pl.DataFrame({"design_id": ["x", "y"], "score": [1.0, 1.0], "iptm": [0.5, 0.9]})
        df = apply_hard_filters(df, [])
        ranked = rank_designs(
            df,
            [RankingMetric(column="score", weight=1, higher_is_better=True)],
            tiebreak_column="iptm",
        )
        assert ranked[0, "design_id"] == "y"

    def test_simple_ranking_is_lexicographic(self):
        # a and c tie on iptm; c's lower rmsd breaks the tie. b has the best rmsd
        # but a worse iptm, so it sorts after both.
        df = apply_hard_filters(
            pl.DataFrame(
                {
                    "design_id": ["a", "b", "c"],
                    "iptm": [0.9, 0.8, 0.9],
                    "rmsd": [5.0, 1.0, 2.0],
                }
            ),
            [],
        )
        ranked = rank_designs(
            df,
            [
                RankingMetric(column="iptm", weight=1, higher_is_better=True),
                RankingMetric(column="rmsd", weight=1, higher_is_better=False),
            ],
            mode="simple",
        )
        assert ranked["design_id"].to_list() == ["c", "a", "b"]

    def test_simple_ranking_ignores_weight(self):
        df = apply_hard_filters(
            pl.DataFrame(
                {
                    "design_id": ["a", "b", "c"],
                    "iptm": [0.9, 0.8, 0.9],
                    "rmsd": [5.0, 1.0, 2.0],
                }
            ),
            [],
        )
        metrics = [
            RankingMetric(column="iptm", weight=99, higher_is_better=True),
            RankingMetric(column="rmsd", weight=0.01, higher_is_better=False),
        ]
        ranked = rank_designs(df, metrics, mode="simple")
        assert ranked["design_id"].to_list() == ["c", "a", "b"]

    def test_simple_ranking_filter_failure_sorts_last(self):
        df = apply_hard_filters(_df(), [FilterSpec(column="rmsd", operator="<", threshold=2.5)])
        ranked = rank_designs(
            df,
            [RankingMetric(column="iptm", weight=1, higher_is_better=True)],
            mode="simple",
        )
        passing_ranks = ranked.filter(pl.col("pass_filters"))["final_rank"]
        failing_ranks = ranked.filter(~pl.col("pass_filters"))["final_rank"]
        assert passing_ranks.max() < failing_ranks.min()

    def test_simple_ranking_null_sorts_last(self):
        df = pl.DataFrame({"design_id": ["a", "b"], "iptm": [0.4, None]})
        df = apply_hard_filters(df, [])
        ranked = rank_designs(
            df,
            [RankingMetric(column="iptm", weight=1, higher_is_better=True)],
            mode="simple",
        )
        assert ranked["design_id"].to_list() == ["a", "b"]

    def test_unknown_ranking_mode_raises(self):
        df = apply_hard_filters(_df(), [])
        with pytest.raises(ValueError, match="Unknown ranking mode"):
            rank_designs(df, [], mode="zscore")


class TestDiversitySelection:
    def test_lazy_greedy_returns_budget_items(self):
        import numpy as np

        quality = np.array([1.0, 0.9, 0.5, 0.4, 0.2])
        seqs = ["AAAAAAAAAA", "AAAAAAAAAB", "CCCCCCCCCC", "CCCCCCCCCD", "GGGGGGGGGG"]
        sim_fn = sequence_similarity_fn(seqs)
        selected = select_lazy_greedy(quality, sim_fn, budget=3, alpha=0.5)
        assert len(selected) == 3
        assert 0 in selected  # highest quality always seeded first

    def test_budget_exceeds_population_returns_all(self):
        import numpy as np

        quality = np.array([1.0, 0.5])
        sim_fn = sequence_similarity_fn(["AAAA", "BBBB"])
        selected = select_lazy_greedy(quality, sim_fn, budget=10, alpha=0.5)
        assert selected == [0, 1]

    def test_size_buckets_cap_selection(self):
        import numpy as np

        # 4 short high-quality sequences, 1 long low-quality; cap short bucket at 1.
        quality = np.array([1.0, 0.95, 0.9, 0.85, 0.1])
        seqs = ["AAAA", "AAAC", "AAAG", "AAAT", "GGGGGGGGGGGGGGGG"]
        sim_fn = sequence_similarity_fn(seqs)
        buckets = [SizeBucket(min=0, max=10, num_designs=1)]
        selected = select_lazy_greedy(
            quality, sim_fn, budget=2, alpha=0.0, lengths=[len(s) for s in seqs], size_buckets=buckets
        )
        short_selected = [i for i in selected if len(seqs[i]) < 10]
        assert len(short_selected) <= 1


class TestParallelSeedAlignment:
    """The multicore seed-alignment path (_parallel_seed_similarities, used by
    select_diverse when there's enough work to be worth ProcessPoolExecutor overhead)
    must produce results *identical* to the serial path — no approximation, purely a
    concurrency change (see engine.py module docstring and PARALLEL_SEED_ALIGNMENT_MIN_PAIRS).
    """

    def _random_designs(self, n: int, seed: int = 0):
        import random as _random

        import numpy as np

        rng = _random.Random(seed)
        seqs = [
            "".join(rng.choices("ACDEFGHIKLMNPQRSTVWY", k=rng.randint(60, 150)))
            for _ in range(n)
        ]
        np.random.seed(seed)
        quality = np.random.uniform(0, 1, n)
        return pl.DataFrame({"sequence": seqs, "quality_score": quality})

    def test_parallel_path_matches_serial_path_exactly(self, monkeypatch):
        df = self._random_designs(n=300)

        parallel_out = select_diverse(
            df, sequence_col="sequence", budget=20, alpha=0.2, random_state=0
        )

        monkeypatch.setattr(engine_mod, "PARALLEL_SEED_ALIGNMENT_MIN_PAIRS", 10**9)
        serial_out = select_diverse(
            df, sequence_col="sequence", budget=20, alpha=0.2, random_state=0
        )

        assert parallel_out["sequence"].to_list() == serial_out["sequence"].to_list()

    def test_below_threshold_uses_serial_path_and_still_correct(self):
        # n - budget is small, so the parallel-path early-out shouldn't even trigger,
        # but the result should still be a valid budget-sized selection.
        df = self._random_designs(n=50)
        out = select_diverse(df, sequence_col="sequence", budget=10, alpha=0.2, random_state=0)
        assert out.height == 10

    def test_max_workers_override_still_correct(self):
        df = self._random_designs(n=250)
        out = select_diverse(
            df, sequence_col="sequence", budget=15, alpha=0.3, random_state=0, max_workers=2
        )
        assert out.height == 15


class TestRunFilteringPipeline:
    def test_full_pipeline_with_diversity(self):
        df = _df()
        filters = [FilterSpec(column="rmsd", operator="<", threshold=6.0)]
        metrics = [RankingMetric(column="iptm", weight=1, higher_is_better=True)]
        ranked, diverse = run_filtering_pipeline(
            df, filters, metrics, budget=2, alpha=0.2, sequence_col="sequence"
        )
        assert len(ranked) == 4
        assert diverse is not None
        assert len(diverse) == 2

    def test_pipeline_without_sequence_col_skips_diversity(self):
        df = _df()
        ranked, diverse = run_filtering_pipeline(df, [], [], budget=2, alpha=0.2, sequence_col=None)
        assert diverse is None
        assert len(ranked) == 4

    def test_diverse_set_excludes_designs_failing_filters(self):
        # rmsd < 2.5 only passes a (1.0) and c (2.0) — b (3.0) and d (5.0) fail.
        # A budget larger than the passing count must not pull in failing designs to
        # fill it: the diverse set should be capped at the passing count (2), and
        # every selected design_id must be one that actually passed the filter.
        df = _df()
        filters = [FilterSpec(column="rmsd", operator="<", threshold=2.5)]
        metrics = [RankingMetric(column="iptm", weight=1, higher_is_better=True)]
        ranked, diverse = run_filtering_pipeline(
            df, filters, metrics, budget=4, alpha=0.2, sequence_col="sequence"
        )
        assert len(ranked) == 4
        assert diverse is not None
        assert len(diverse) == 2
        assert set(diverse["design_id"].to_list()) == {"a", "c"}

    def test_pipeline_apply_diversity_false_keeps_all_passing(self):
        df = _df()
        filters = [FilterSpec(column="rmsd", operator="<", threshold=2.5)]
        metrics = [RankingMetric(column="iptm", weight=1, higher_is_better=True)]
        ranked, diverse = run_filtering_pipeline(
            df,
            filters,
            metrics,
            budget=1,
            alpha=0.2,
            sequence_col="sequence",
            apply_diversity=False,
        )
        assert len(ranked) == 4
        assert diverse is not None
        assert len(diverse) == 2
        assert set(diverse["design_id"].to_list()) == {"a", "c"}

    def test_best_mpnn_only_collapses_before_diversity(self):
        # a2 is a worse MPNN variant of the same backbone as a1 (higher pae_interaction).
        # Quality-only diversity with a large budget would keep both unless the collapse
        # runs first. a1 wins on primary score even though a2 has the higher iptm.
        df = pl.DataFrame(
            {
                "design_id": ["a1", "a2", "b1", "solo"],
                "method": ["rfd", "rfd", "rfd", "rfd"],
                "backbone_id": ["bbA", "bbA", "bbB", None],
                "pae_interaction": [5.0, 20.0, 8.0, 1.0],
                "plddt_binder": [70.0, 95.0, 80.0, 50.0],
                "iptm": [0.4, 0.99, 0.5, 0.2],
                "sequence": ["AAAAAAAAAA", "CCCCCCCCCC", "GGGGGGGGGG", "TTTTTTTTTT"],
            }
        )
        metrics = [RankingMetric(column="iptm", weight=1, higher_is_better=True)]
        _, diverse = run_filtering_pipeline(
            df,
            [],
            metrics,
            budget=4,
            alpha=0.0,
            sequence_col="sequence",
            best_mpnn_only=True,
        )
        assert diverse is not None
        assert set(diverse["design_id"].to_list()) == {"a1", "b1", "solo"}

    def test_best_mpnn_only_ignored_when_diversity_off(self):
        df = pl.DataFrame(
            {
                "design_id": ["a1", "a2"],
                "method": ["rfd", "rfd"],
                "backbone_id": ["bbA", "bbA"],
                "pae_interaction": [5.0, 20.0],
                "sequence": ["AAAAAAAAAA", "CCCCCCCCCC"],
            }
        )
        _, diverse = run_filtering_pipeline(
            df,
            [],
            [],
            budget=1,
            alpha=0.0,
            sequence_col="sequence",
            apply_diversity=False,
            best_mpnn_only=True,
        )
        assert diverse is not None
        assert set(diverse["design_id"].to_list()) == {"a1", "a2"}


class TestKeepBestMpnnPerBackbone:
    def test_keeps_lower_pae_for_rfd(self):
        df = pl.DataFrame(
            {
                "design_id": ["worse", "better"],
                "method": ["rfd", "rfd"],
                "backbone_id": ["bb", "bb"],
                "pae_interaction": [30.0, 4.0],
                "plddt_binder": [99.0, 50.0],
            }
        )
        out = keep_best_mpnn_per_backbone(df)
        assert out["design_id"].to_list() == ["better"]


class TestMissingSequencesAreExcludedNotBlankFilled:
    """A design with no sequence must never reach the diversity pool.

    Blank-filling made such a design align to zero against everything, i.e. normalised
    identity 0 — maximally *dissimilar* — so the diversity term actively preferred the
    designs we know least about, and the resulting panel silently contained sequenceless
    picks.
    """

    def _df_with_gaps(self):
        # b and d have no usable sequence; both are high quality, so a diversity term
        # that scores them as maximally dissimilar would select them first.
        return pl.DataFrame(
            {
                "design_id": ["a", "b", "c", "d"],
                "quality_score": [0.5, 1.0, 0.4, 0.99],
                "sequence": ["AAAAAAAAAA", None, "CCCCCCCCCC", "   "],
            }
        )

    def test_blank_and_null_sequences_never_selected(self):
        out = select_diverse(self._df_with_gaps(), sequence_col="sequence", budget=4, alpha=0.5)
        assert set(out["design_id"].to_list()) == {"a", "c"}

    def test_all_sequences_missing_yields_empty_not_crash(self):
        # Every pair would divide by max(0, 0) -> ZeroDivisionError before the fix.
        df = pl.DataFrame(
            {"design_id": ["a", "b"], "quality_score": [1.0, 0.5], "sequence": [None, ""]}
        )
        out = select_diverse(df, sequence_col="sequence", budget=2, alpha=0.5)
        assert out.height == 0

    def test_count_missing_sequences_reports_the_shortfall(self):
        assert count_missing_sequences(self._df_with_gaps(), "sequence") == 2
        assert count_missing_sequences(self._df_with_gaps(), "Sequence") == 4
        assert count_missing_sequences(self._df_with_gaps(), None) == 4

    def test_identical_empty_sequences_score_as_identical(self):
        # Guards direct callers of the similarity function: 0/0 is not "maximally diverse".
        assert sequence_similarity_fn(["", ""])(0, 1) == 1.0

    def test_pipeline_diverse_set_smaller_than_budget_when_sequences_missing(self):
        ranked, diverse = run_filtering_pipeline(
            self._df_with_gaps(), [], [], budget=4, alpha=0.5, sequence_col="sequence"
        )
        assert ranked.height == 4
        assert diverse is not None
        assert diverse.height == 2


class TestExcludedMetricColumns:
    def test_bindcraft_per_replicate_columns_excluded(self):
        for col in ("1_pLDDT", "2_i_pTM", "5_Unrelaxed_Clashes", "1_Binder_BetaSheet%"):
            assert is_excluded_metric_column(col), col

    def test_normal_columns_not_excluded(self):
        for col in ("Average_i_pTM", "Binder_RMSD", "design_to_target_iptm", "rmsd"):
            assert not is_excluded_metric_column(col), col


class TestMetricsMapping:
    def test_resolve_canonical_column(self):
        assert resolve_column("iptm", "bindcraft", ["Average_i_pTM", "other"]) == "Average_i_pTM"

    def test_resolve_unmapped_method_returns_none(self):
        assert resolve_column("iptm", "rfd", ["pae_interaction"]) is None

    def test_resolve_raw_column_passthrough(self):
        assert resolve_column("custom_col", "bindcraft", ["custom_col"]) == "custom_col"

    def test_resolve_column_per_row(self):
        df = pd.DataFrame(
            {
                "method": ["bindcraft", "rfd3"],
                "Average_i_pTM": [0.9, None],
                "iptm": [None, 0.7],
            }
        )
        resolved = resolve_column_per_row(df, "iptm")
        assert resolved.tolist() == pytest.approx([0.9, 0.7])

    def test_bindcraft_rmsd_resolves_to_the_column_bindcraft_actually_writes(self):
        # BindCraft's results table has Average_Binder_RMSD, not a bare Binder_RMSD, so
        # canonical "rmsd" used to resolve to nothing for every bindcraft design.
        assert (
            resolve_column("rmsd", "bindcraft", ["Average_Binder_RMSD", "Average_Target_RMSD"])
            == "Average_Binder_RMSD"
        )

    def test_resolve_rfd_iptm_fallback_when_boltz_iptm_present(self):
        assert resolve_column("iptm", "rfd", ["rmsd", "boltz_iptm"]) == "boltz_iptm"

    def test_resolve_ipsae_per_method(self):
        assert resolve_column("ipsae", "boltzgen", ["design_ipsae_min", "design_to_target_ipsae"]) == "design_ipsae_min"
        assert resolve_column("ipsae", "rfd3", ["rf3_ipsae_min", "iptm"]) == "rf3_ipsae_min"
        assert resolve_column("ipsae", "bindcraft", ["Average_i_pTM"]) is None
        assert resolve_column("ipsae", "rfd", ["rmsd", "boltz_iptm"]) is None

    def test_resolve_binder_plddt_per_method(self):
        assert resolve_column("binder_plddt", "bindcraft", ["Average_Binder_pLDDT"]) == "Average_Binder_pLDDT"
        assert resolve_column("binder_plddt", "rfd", ["plddt", "plddt_binder"]) == "plddt_binder"
        assert resolve_column("binder_plddt", "rfd", ["plddt"]) == "plddt"
        assert resolve_column("binder_plddt", "boltzgen", ["design_ptm"]) is None

    def test_resolve_rfd_iptm_none_when_boltz_iptm_absent(self):
        assert resolve_column("iptm", "rfd", ["rmsd", "pae_interaction"]) is None

    def test_resolve_column_per_row_rfd_optional_boltz_iptm(self):
        df = pd.DataFrame(
            {
                "method": ["rfd", "rfd", "bindcraft"],
                "boltz_iptm": [0.6, None, None],
                "Average_i_pTM": [None, None, 0.8],
            }
        )
        resolved = resolve_column_per_row(df, "iptm")
        assert resolved.tolist() == pytest.approx([0.6, float("nan"), 0.8], nan_ok=True)
