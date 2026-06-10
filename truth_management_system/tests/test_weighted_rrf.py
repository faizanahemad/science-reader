"""
Tests for Workstream W-A — weighted Reciprocal Rank Fusion.

merge_results_rrf accepts an optional ``strategy_weights`` mapping that
multiplies each strategy's reciprocal-rank contribution. An empty/None mapping
must reproduce plain unweighted RRF exactly (no-op default); a mapping that
down-weights a strategy must reorder ties in favour of the trusted strategy.
"""

import pytest

from truth_management_system.models import Claim
from truth_management_system.search.base import SearchResult, merge_results_rrf


def _result(statement, source):
    claim = Claim.create(
        statement=statement, claim_type="fact", context_domain="personal",
    )
    return SearchResult(claim=claim, score=0.0, source=source, is_contested=False)


def test_default_is_unweighted_rrf():
    """None / empty weights == plain RRF: tied ranks across strategies tie."""
    fts = [_result("A", "fts")]
    emb = [_result("B", "embedding")]
    out_none = merge_results_rrf([fts, emb], k=10)
    # Both at rank 0 in their own list -> identical 1/(0+60) scores.
    assert {r.claim.statement for r in out_none} == {"A", "B"}
    assert out_none[0].score == pytest.approx(out_none[1].score)
    assert out_none[0].score == pytest.approx(1.0 / 60)

    # Explicit empty mapping behaves identically to None.
    out_empty = merge_results_rrf([fts, emb], k=10, strategy_weights={})
    assert [r.score for r in out_empty] == [r.score for r in out_none]


def test_unlisted_source_defaults_to_weight_one():
    fts = [_result("A", "fts")]
    out = merge_results_rrf([fts], k=10, strategy_weights={"embedding": 0.5})
    # 'fts' absent from mapping -> weight 1.0 -> unchanged score.
    assert out[0].score == pytest.approx(1.0 / 60)


def test_downweighting_fts_loses_tie_to_embedding():
    fts = [_result("A", "fts")]
    emb = [_result("B", "embedding")]
    out = merge_results_rrf(
        [fts, emb], k=10, strategy_weights={"fts": 0.6, "embedding": 1.0}
    )
    assert out[0].claim.statement == "B"  # embedding wins the tie
    assert out[0].score == pytest.approx(1.0 / 60)
    assert out[1].claim.statement == "A"
    assert out[1].score == pytest.approx(0.6 / 60)


def test_weights_sum_across_strategies_for_same_claim():
    """A claim found by two strategies sums its weighted contributions."""
    # Same claim_id is required for the merge to combine; reuse one claim.
    shared_claim = Claim.create(
        statement="shared", claim_type="fact", context_domain="personal",
    )
    fts = [SearchResult(claim=shared_claim, score=0.0, source="fts", is_contested=False)]
    emb = [SearchResult(claim=shared_claim, score=0.0, source="embedding", is_contested=False)]
    out = merge_results_rrf(
        [fts, emb], k=10, strategy_weights={"fts": 0.6, "embedding": 1.0}
    )
    assert len(out) == 1  # deduped by claim_id
    assert out[0].score == pytest.approx((0.6 + 1.0) / 60)
    assert set(out[0].metadata["sources"]) == {"fts", "embedding"}
