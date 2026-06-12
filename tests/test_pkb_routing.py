"""Exhaustive tests for route_candidate (Tiered B1)."""
import pytest
from truth_management_system.routing import route_candidate, Route, RouteResult
from truth_management_system.autonomy import derive_policy


def _candidate(confidence=0.9, derivation="stated", domain="personal",
               claim_type="fact"):
    return {"confidence": confidence, "derivation": derivation,
            "context_domain": domain, "claim_type": claim_type}


def _match(relation=None, similarity=0.0):
    return {"relation": relation, "similarity_score": similarity}


class TestHardEscalations:
    """Hard escalations always return CONFIRM (except at Full with auto flags)."""

    def test_conflict_always_confirms(self):
        policy = derive_policy(100)  # even at Full
        r = route_candidate(_candidate(), policy, _match("conflict", 0.85))
        assert r.route == Route.CONFIRM
        assert r.gate == "conflict"

    def test_inferred_confirms_below_full(self):
        for level in [0, 25, 50, 75]:
            policy = derive_policy(level)
            r = route_candidate(_candidate(derivation="inferred"), policy)
            assert r.route == Route.CONFIRM
            assert r.gate == "inferred"

    def test_inferred_saves_at_full(self):
        policy = derive_policy(100)  # capture_inferred_auto = True
        r = route_candidate(_candidate(confidence=0.9, derivation="inferred"), policy)
        # At Full, inferred can auto-save if other gates pass
        assert r.route == Route.SAVE

    def test_sensitive_domain_confirms_below_full(self):
        for domain in ["health", "finance", "relationships"]:
            policy = derive_policy(50)
            r = route_candidate(_candidate(domain=domain), policy)
            assert r.route == Route.CONFIRM
            assert r.gate == "sensitive"

    def test_sensitive_domain_saves_at_full(self):
        policy = derive_policy(100)  # capture_sensitive_auto = True
        r = route_candidate(_candidate(domain="health"), policy)
        assert r.route == Route.SAVE

    def test_high_stakes_types_confirm(self):
        for ctype in ["decision", "task", "reminder"]:
            policy = derive_policy(100)
            r = route_candidate(_candidate(claim_type=ctype), policy)
            assert r.route == Route.CONFIRM
            assert r.gate == "high_stakes"


class TestSilentSkip:
    """Duplicate and low-confidence items are silently skipped."""

    def test_exact_duplicate_skips(self):
        policy = derive_policy(50)
        r = route_candidate(_candidate(), policy, _match("duplicate", 0.95))
        assert r.route == Route.SKIP
        assert r.gate == "duplicate"

    def test_near_duplicate_below_threshold_does_not_skip(self):
        policy = derive_policy(50)
        r = route_candidate(_candidate(), policy, _match("duplicate", 0.88))
        # Below 0.92 threshold, not skipped — goes to auto-save or confirm
        assert r.route != Route.SKIP

    def test_low_confidence_skips(self):
        policy = derive_policy(50)
        r = route_candidate(_candidate(confidence=0.3), policy)
        assert r.route == Route.SKIP
        assert r.gate == "low_confidence"


class TestAutoSave:
    """Confident, safe, stated/extracted claims auto-save when policy allows."""

    def test_balanced_auto_saves_at_085(self):
        policy = derive_policy(50)
        r = route_candidate(_candidate(confidence=0.9, derivation="stated"), policy)
        assert r.route == Route.SAVE
        assert r.gate == "auto_save"

    def test_balanced_confirms_below_085(self):
        policy = derive_policy(50)
        r = route_candidate(_candidate(confidence=0.8, derivation="stated"), policy)
        assert r.route == Route.CONFIRM  # 0.8 < 0.85

    def test_proactive_auto_saves_at_075(self):
        policy = derive_policy(75)
        r = route_candidate(_candidate(confidence=0.76), policy)
        assert r.route == Route.SAVE

    def test_assisted_auto_saves_at_095(self):
        policy = derive_policy(25)
        r = route_candidate(_candidate(confidence=0.96), policy)
        assert r.route == Route.SAVE

    def test_full_auto_saves_everything_non_escalated(self):
        policy = derive_policy(100)  # threshold = 0.0
        r = route_candidate(_candidate(confidence=0.5, derivation="extracted"), policy)
        assert r.route == Route.SAVE

    def test_manual_never_auto_saves(self):
        policy = derive_policy(0)
        r = route_candidate(_candidate(confidence=1.0), policy)
        assert r.route == Route.CONFIRM
        assert r.gate == "policy_manual"


class TestRelatedMatch:
    """Related (near-neighbor) claims still auto-save if safe."""

    def test_related_safe_auto_saves(self):
        policy = derive_policy(50)
        r = route_candidate(
            _candidate(confidence=0.9, derivation="stated"),
            policy,
            _match("related", 0.8)
        )
        assert r.route == Route.SAVE

    def test_related_but_inferred_confirms(self):
        policy = derive_policy(50)
        r = route_candidate(
            _candidate(confidence=0.9, derivation="inferred"),
            policy,
            _match("related", 0.8)
        )
        assert r.route == Route.CONFIRM


class TestPolicyInteraction:
    """Route respects the policy derived from different autonomy levels."""

    def test_consistent_with_derive_policy(self):
        """At manual, everything confirms. At full, most saves."""
        c = _candidate(confidence=0.9, derivation="stated", domain="personal", claim_type="fact")
        assert route_candidate(c, derive_policy(0)).route == Route.CONFIRM
        assert route_candidate(c, derive_policy(50)).route == Route.SAVE
        assert route_candidate(c, derive_policy(100)).route == Route.SAVE

    def test_none_policy_is_safe(self):
        """If policy is None/empty, defaults to all-confirm (safe)."""
        r = route_candidate(_candidate(), {})
        assert r.route == Route.CONFIRM


class TestAuditability:
    """RouteResult carries reason and gate for traceability."""

    def test_result_has_reason(self):
        r = route_candidate(_candidate(), derive_policy(50))
        assert isinstance(r.reason, str) and len(r.reason) > 0
        assert isinstance(r.gate, str) and len(r.gate) > 0

    def test_source_guard_conflict_cannot_bypass(self):
        """Even with capture_sensitive_auto=True (Full), conflict still confirms."""
        policy = derive_policy(100)
        r = route_candidate(_candidate(), policy, _match("conflict", 0.5))
        assert r.route == Route.CONFIRM
        assert r.gate == "conflict"
