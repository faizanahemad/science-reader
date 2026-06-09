"""
Unit tests for the post-fusion recency/confidence re-rank (Workstream C1).

Network-free and DB-free: builds SearchResult fixtures directly and checks the
pure re-rank function. The key invariant is C3: with w_recency == w_confidence
== 0 the ranking is unchanged exactly.
"""
import json
from datetime import datetime, timezone, timedelta

from truth_management_system.config import PKBConfig
from truth_management_system.models import Claim
from truth_management_system.search.base import (
    SearchResult,
    apply_recency_confidence_rerank,
)

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _result(key: str, rrf_score: float, *, days_ago: float = 0.0,
            claim_type: str = "fact", confidence=None, pinned: bool = False) -> SearchResult:
    claim = Claim.create(statement=f"claim {key}", claim_type=claim_type, context_domain="personal")
    claim.updated_at = _iso(days_ago)
    if confidence is not None:
        claim.confidence = confidence
    if pinned:
        claim.meta_json = json.dumps({"pinned": True})
    r = SearchResult.from_claim(claim, score=rrf_score, source="fts")
    r.metadata["rrf_score"] = rrf_score
    return r


def test_zero_weights_are_a_noop():
    """Default weights (0,0) must leave order AND scores untouched."""
    cfg = PKBConfig()  # w_recency = w_confidence = 0
    old = _result("old", 0.020, days_ago=400)
    new = _result("new", 0.016, days_ago=1)
    out = apply_recency_confidence_rerank([old, new], cfg, now=NOW)
    assert [r.claim.statement for r in out] == ["claim old", "claim new"]
    assert out[0].score == 0.020 and out[1].score == 0.016


def test_recency_promotes_newer_claim():
    """With w_recency on and a short half-life, the newer claim overtakes."""
    cfg = PKBConfig(w_recency=2.0, recency_half_life_days=30.0)
    old = _result("old", 0.020, days_ago=400)  # higher raw rank
    new = _result("new", 0.016, days_ago=1)
    out = apply_recency_confidence_rerank([old, new], cfg, now=NOW)
    assert out[0].claim.statement == "claim new"
    assert out[0].metadata["recency_factor"] > out[1].metadata["recency_factor"]


def test_pinned_claim_keeps_full_recency():
    """A pinned (older) claim keeps recency=1.0 and is not decayed."""
    cfg = PKBConfig(w_recency=2.0, recency_half_life_days=30.0)
    pinned_old = _result("pinned", 0.020, days_ago=400, pinned=True)
    new = _result("new", 0.016, days_ago=1)
    out = apply_recency_confidence_rerank([pinned_old, new], cfg, now=NOW)
    pinned_factor = next(r.metadata["recency_factor"] for r in out if r.claim.statement == "claim pinned")
    assert pinned_factor == 1.0
    assert out[0].claim.statement == "claim pinned"  # stays on top (higher rrf, no decay)


def test_grace_floor_protects_fresh_claims():
    """Claims younger than recency_grace_days keep recency=1.0."""
    cfg = PKBConfig(w_recency=2.0, recency_half_life_days=10.0, recency_grace_days=14.0)
    fresh = _result("fresh", 0.016, days_ago=5)  # within grace
    out = apply_recency_confidence_rerank([fresh], cfg, now=NOW)
    assert out[0].metadata["recency_factor"] == 1.0


def test_per_type_half_life_override():
    """A long per-type half-life makes a 'fact' decay slower than the default."""
    cfg = PKBConfig(w_recency=1.0, recency_half_life_days=10.0,
                    half_life_by_type={"fact": 100000.0})
    fact = _result("fact", 0.016, days_ago=400, claim_type="fact")
    obs = _result("obs", 0.016, days_ago=400, claim_type="observation")
    out = apply_recency_confidence_rerank([fact, obs], cfg, now=NOW)
    fact_factor = next(r.metadata["recency_factor"] for r in out if r.claim.statement == "claim fact")
    obs_factor = next(r.metadata["recency_factor"] for r in out if r.claim.statement == "claim obs")
    assert fact_factor > obs_factor
    assert fact_factor > 0.99  # effectively no decay


def test_confidence_weight_promotes_confident_claim():
    """With w_confidence on, the higher-confidence claim is promoted."""
    cfg = PKBConfig(w_confidence=2.0)
    low = _result("low", 0.018, confidence=0.2)
    high = _result("high", 0.016, confidence=0.95)
    out = apply_recency_confidence_rerank([low, high], cfg, now=NOW)
    assert out[0].claim.statement == "claim high"


def test_empty_input_is_safe():
    assert apply_recency_confidence_rerank([], PKBConfig(w_recency=1.0), now=NOW) == []


# --------------------------------------------------------------------------- #
# C2 — contested down-ranking
# --------------------------------------------------------------------------- #
def _contested(result: SearchResult) -> SearchResult:
    result.claim.status = "contested"
    return result


def test_contested_penalty_default_is_noop():
    """contested_penalty == 1.0 (default) must not change scores/order."""
    cfg = PKBConfig()  # contested_penalty defaults to 1.0
    a = _contested(_result("a", 0.020))
    b = _result("b", 0.016)
    out = apply_recency_confidence_rerank([a, b], cfg, now=NOW)
    assert [r.claim.statement for r in out] == ["claim a", "claim b"]
    assert out[0].score == 0.020 and out[1].score == 0.016


def test_contested_penalty_buries_contested_claim():
    """A high-ranked contested claim sinks below an uncontested one."""
    cfg = PKBConfig(contested_penalty=0.5)
    contested = _contested(_result("contested", 0.020))
    clean = _result("clean", 0.016)
    out = apply_recency_confidence_rerank([contested, clean], cfg, now=NOW)
    # 0.020 * 0.5 = 0.010 < 0.016 -> clean now wins
    assert out[0].claim.statement == "claim clean"
    assert abs(out[1].score - 0.010) < 1e-9
    assert out[1].metadata["contested_factor"] == 0.5


def test_contested_penalty_only_affects_contested():
    """Uncontested claims keep contested_factor == 1.0."""
    cfg = PKBConfig(contested_penalty=0.1)
    clean = _result("clean", 0.020)
    out = apply_recency_confidence_rerank([clean], cfg, now=NOW)
    assert out[0].score == 0.020
    assert out[0].metadata["contested_factor"] == 1.0


def test_contested_penalty_composes_with_weights():
    """Penalty multiplies on top of recency/confidence factors."""
    cfg = PKBConfig(w_confidence=1.0, default_confidence=0.5, contested_penalty=0.5)
    contested = _contested(_result("c", 0.040))  # conf factor 0.5, penalty 0.5
    out = apply_recency_confidence_rerank([contested], cfg, now=NOW)
    # 0.040 * (0.5 ** 1.0) * 0.5 = 0.010
    assert abs(out[0].score - 0.010) < 1e-9
