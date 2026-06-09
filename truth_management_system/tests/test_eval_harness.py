"""
Tests for the PKB retrieval eval harness.

Two layers:
1. Pure metric unit tests (no DB, no network).
2. A network-free FTS baseline guard: seed the bundled dataset into a temp PKB,
   run the FTS strategy, and assert aggregate recall@k / MRR stay above a
   conservative floor. This catches retrieval regressions in CI without
   requiring an embedding API key.

Run with:
    python -m pytest truth_management_system/tests/test_eval_harness.py -v
"""

import pytest

from truth_management_system.tests.eval.metrics import (
    recall_at_k,
    precision_at_k,
    reciprocal_rank,
    mean_reciprocal_rank,
    aggregate_case_metrics,
)
from truth_management_system.tests.eval.dataset import load_dataset
from truth_management_system.tests.eval.runner import EvalRunner


# --------------------------------------------------------------------- metrics

class TestMetrics:
    def test_recall_at_k_basic(self):
        retrieved = ["a", "b", "c", "d"]
        assert recall_at_k(retrieved, {"a", "c"}, k=4) == 1.0
        assert recall_at_k(retrieved, {"a", "z"}, k=4) == 0.5
        assert recall_at_k(retrieved, {"z"}, k=4) == 0.0

    def test_recall_at_k_cutoff(self):
        retrieved = ["a", "b", "c", "d"]
        # 'c' is at rank index 2 -> excluded from top-2
        assert recall_at_k(retrieved, {"a", "c"}, k=2) == 0.5
        # k<=0 means no cutoff
        assert recall_at_k(retrieved, {"a", "c"}, k=0) == 1.0

    def test_recall_at_k_empty_expected(self):
        assert recall_at_k(["a"], set(), k=5) == 0.0

    def test_precision_at_k(self):
        retrieved = ["a", "b", "c", "d"]
        assert precision_at_k(retrieved, {"a", "b"}, k=2) == 1.0
        assert precision_at_k(retrieved, {"a"}, k=4) == 0.25
        assert precision_at_k([], {"a"}, k=4) == 0.0

    def test_reciprocal_rank(self):
        assert reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0
        assert reciprocal_rank(["a", "b", "c"], {"b"}) == 0.5
        assert reciprocal_rank(["a", "b", "c"], {"c"}) == pytest.approx(1.0 / 3.0)
        assert reciprocal_rank(["a", "b", "c"], {"z"}) == 0.0
        assert reciprocal_rank(["a", "b", "c"], set()) == 0.0

    def test_mean_reciprocal_rank(self):
        retrieved = [["a", "b"], ["x", "y"]]
        expected = [{"a"}, {"y"}]  # RR = 1.0 and 0.5 -> mean 0.75
        assert mean_reciprocal_rank(retrieved, expected) == pytest.approx(0.75)
        assert mean_reciprocal_rank([], []) == 0.0

    def test_aggregate_case_metrics(self):
        cases = [
            {"recall@5": 1.0, "rr": 1.0},
            {"recall@5": 0.0, "rr": 0.0},
        ]
        agg = aggregate_case_metrics(cases)
        assert agg["recall@5"] == 0.5
        assert agg["rr"] == 0.5
        assert aggregate_case_metrics([]) == {}

    def test_aggregate_missing_keys_count_as_zero(self):
        cases = [{"recall@5": 1.0}, {"rr": 1.0}]
        agg = aggregate_case_metrics(cases)
        # each key averaged over total case count (2)
        assert agg["recall@5"] == 0.5
        assert agg["rr"] == 0.5


# ------------------------------------------------------------------- dataset

def test_seed_dataset_loads_and_validates():
    ds = load_dataset()
    assert ds.claims and ds.cases
    # validate() (called in load) guarantees every expected key is known
    known = set(ds.claim_keys())
    for case in ds.cases:
        assert set(case.expected).issubset(known)


# ------------------------------------------------------- FTS baseline guard

# Conservative floors tuned below observed FTS numbers on the seed set:
#   lexical recall@5=1.0 mrr=1.0 ; semantic recall@5=0.125 ; multi=1.0 ; temporal recall=1.0
# The gap floor asserts FTS is much stronger on lexical than paraphrase queries —
# i.e. the harness demonstrates the retrieval gap that embeddings/hybrid must close.
LEXICAL_RECALL_FLOOR = 0.8
LEXICAL_MRR_FLOOR = 0.7
LEXICAL_OVER_SEMANTIC_GAP = 0.4
EVAL_K = 5


def _fts_report():
    """Run the FTS strategy over the seed dataset (network-free) and return the report."""
    ds = load_dataset()
    # keys={} forces a network-free run: only the FTS strategy is registered.
    with EvalRunner(keys={}) as runner:
        runner.seed(ds)
        report = runner.run(ds, strategy_names=["fts"], k=EVAL_K)
    return ds, report


def test_fts_lexical_baseline_guard():
    """FTS must stay strong on the lexical subset (regression guard)."""
    ds, report = _fts_report()
    lex = report.by_category.get("lexical", {})
    recall = lex.get(f"recall@{EVAL_K}", 0.0)
    mrr = lex.get("mrr", 0.0)
    assert recall >= LEXICAL_RECALL_FLOOR, f"FTS lexical recall@{EVAL_K}={recall:.3f} below floor {LEXICAL_RECALL_FLOOR}"
    assert mrr >= LEXICAL_MRR_FLOOR, f"FTS lexical MRR={mrr:.3f} below floor {LEXICAL_MRR_FLOOR}"
    assert len(report.per_case) == len(ds.cases)


def test_fts_semantic_gap_is_visible():
    """
    FTS should be materially worse on paraphrase (semantic) queries than on
    lexical ones. This documents the gap embedding/hybrid retrieval must close
    and guards against the dataset silently regressing to all-lexical (which
    would hide that signal).
    """
    _, report = _fts_report()
    lex_recall = report.by_category.get("lexical", {}).get(f"recall@{EVAL_K}", 0.0)
    sem_recall = report.by_category.get("semantic", {}).get(f"recall@{EVAL_K}", 0.0)
    assert lex_recall - sem_recall >= LEXICAL_OVER_SEMANTIC_GAP, (
        f"Expected FTS lexical recall to exceed semantic recall by "
        f">= {LEXICAL_OVER_SEMANTIC_GAP}; got lexical={lex_recall:.3f}, semantic={sem_recall:.3f}"
    )


def test_report_has_all_categories():
    """The dataset must exercise every category so the breakdown stays meaningful."""
    _, report = _fts_report()
    expected_categories = {
        "lexical", "semantic", "multi", "temporal", "recency",
        "conflict", "hard_negative", "scoped", "lifecycle",
    }
    assert expected_categories.issubset(report.by_category.keys())


def test_precision_is_reported():
    """precision@k must be present alongside recall@k and mrr."""
    _, report = _fts_report()
    assert f"precision@{EVAL_K}" in report.aggregate
    assert f"recall@{EVAL_K}" in report.aggregate
    assert "mrr" in report.aggregate


def test_existing_capabilities_scoped_and_lifecycle():
    """
    Guards for already-shipped behavior the dataset exercises:
      - scoped: per-case SearchFilters still return the in-scope target.
      - lifecycle: superseded/expired claims are excluded by default, so the
        *active* target is still recalled despite stale siblings.
    These should stay high; a regression here is a real bug (not 'room to grow').
    """
    _, report = _fts_report()
    scoped_recall = report.by_category.get("scoped", {}).get(f"recall@{EVAL_K}", 0.0)
    lifecycle_recall = report.by_category.get("lifecycle", {}).get(f"recall@{EVAL_K}", 0.0)
    assert scoped_recall >= 0.8, f"scoped recall regressed: {scoped_recall:.3f}"
    assert lifecycle_recall >= 0.8, f"lifecycle recall regressed: {lifecycle_recall:.3f}"
