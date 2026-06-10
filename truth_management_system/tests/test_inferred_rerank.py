"""
Tests for Workstream W3 — inferred claims down-ranked in the re-rank.

apply_recency_confidence_rerank multiplies inferred claims' score by
(1 - inferred_rerank_penalty), active even when w_recency/w_confidence are 0.
"""

import json

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.models import Claim
from truth_management_system.search.base import (
    SearchResult,
    apply_recency_confidence_rerank,
)


def _result(statement, derivation, score):
    meta = json.dumps({"source": {"channel": "chat", "derivation": derivation}})
    claim = Claim.create(
        statement=statement, claim_type="fact", context_domain="personal",
        meta_json=meta,
    )
    r = SearchResult(claim=claim, score=score, source="test", is_contested=False)
    r.metadata["rrf_score"] = score
    return r


def test_inferred_downranked_below_stated():
    cfg = PKBConfig(db_path=":memory:")  # defaults: penalty 0.1, weights 0
    results = [
        _result("inferred one", "inferred", 0.10),
        _result("stated one", "stated", 0.095),
    ]
    out = apply_recency_confidence_rerank(results, cfg)
    # inferred 0.10*0.9=0.09 < stated 0.095 -> stated now ranks first
    assert out[0].claim.statement == "stated one"
    assert out[1].metadata["inferred_factor"] == pytest.approx(0.9)


def test_penalty_zero_is_noop():
    cfg = PKBConfig(db_path=":memory:", inferred_rerank_penalty=0.0)
    results = [
        _result("inferred one", "inferred", 0.10),
        _result("stated one", "stated", 0.095),
    ]
    out = apply_recency_confidence_rerank(results, cfg)
    assert out[0].claim.statement == "inferred one"  # order unchanged
    assert out[0].score == 0.10


def test_stated_not_penalized():
    cfg = PKBConfig(db_path=":memory:")
    r = _result("stated", "stated", 0.10)
    out = apply_recency_confidence_rerank([r], cfg)
    assert out[0].score == pytest.approx(0.10)
    assert out[0].metadata["inferred_factor"] == 1.0
