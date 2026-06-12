"""
Tiered persistence routing — decide SAVE/CONFIRM/SKIP per candidate.

Pure function ``route_candidate(candidate, policy, match_result)`` evaluates
the decision tree from the tiered persistence plan. First-match-wins, auditable,
no side effects.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional


# ─── Route outcomes ──────────────────────────────────────────────────────────
class Route:
    SAVE = "save"
    CONFIRM = "confirm"
    SKIP = "skip"


@dataclass
class RouteResult:
    """Outcome of route_candidate with an auditable reason."""
    route: str          # Route.SAVE / CONFIRM / SKIP
    reason: str         # Human-readable explanation of the branch taken
    gate: str           # Machine-readable gate name (e.g. "conflict", "inferred", "auto_save")


# ─── Defaults (used when policy doesn't provide; match the plan) ─────────────
_SENSITIVE_DOMAINS = frozenset({"health", "finance", "relationships"})
_HIGH_STAKES_TYPES = frozenset({"decision", "task", "reminder"})
_SAFE_TYPES = frozenset({"fact", "preference", "habit", "observation", "memory"})

_DEFAULT_AUTO_SAVE_CONFIDENCE = 0.85
_DEFAULT_SKIP_CONFIDENCE = 0.45
_DEFAULT_DUPLICATE_THRESHOLD = 0.92


def route_candidate(
    candidate: Dict[str, Any],
    policy: Dict[str, Any],
    match_result: Optional[Dict[str, Any]] = None,
) -> RouteResult:
    """Route a candidate claim to SAVE, CONFIRM, or SKIP.

    Args:
        candidate: Dict with at least: confidence (float 0-1), derivation (str),
            context_domain (str), claim_type (str).
        policy: Output of derive_policy() — must have capture_safe_stated_threshold.
            If None or missing keys, uses safe defaults (all-confirm).
        match_result: Optional dict from dedup analysis with: relation (str|None),
            similarity_score (float|None).

    Returns:
        RouteResult with the routing decision + auditable reason.
    """
    policy = policy or {}
    match_result = match_result or {}

    # Extract candidate signals
    confidence = float(candidate.get("confidence") or 0.8)
    derivation = candidate.get("derivation", "extracted")
    domain = candidate.get("context_domain", "personal")
    claim_type = candidate.get("claim_type", "fact")

    # Extract match signals
    relation = match_result.get("relation")  # None, "duplicate", "related", "conflict"
    similarity = float(match_result.get("similarity_score") or 0.0)

    # Policy thresholds (fall back to strict defaults if policy is incomplete)
    auto_save_threshold = policy.get("capture_safe_stated_threshold")
    capture_inferred_auto = policy.get("capture_inferred_auto", False)
    capture_sensitive_auto = policy.get("capture_sensitive_auto", False)

    # Config thresholds (could be in policy too; use defaults for now)
    skip_confidence = _DEFAULT_SKIP_CONFIDENCE
    dup_threshold = _DEFAULT_DUPLICATE_THRESHOLD

    sensitive_domains = _SENSITIVE_DOMAINS
    high_stakes_types = _HIGH_STAKES_TYPES
    safe_types = _SAFE_TYPES

    # ─── HARD ESCALATIONS (never silent unless capture_*_auto is True at Full) ─
    if relation == "conflict":
        return RouteResult(Route.CONFIRM, "conflicts with existing claim", "conflict")

    if derivation == "inferred" and not capture_inferred_auto:
        return RouteResult(Route.CONFIRM, "inferred — user didn't state this", "inferred")

    if domain in sensitive_domains and not capture_sensitive_auto:
        return RouteResult(Route.CONFIRM, f"sensitive domain: {domain}", "sensitive")

    if claim_type in high_stakes_types:
        return RouteResult(Route.CONFIRM, f"high-stakes type: {claim_type}", "high_stakes")

    # ─── SILENT SKIP (noise / exact dup) ─────────────────────────────────────
    if relation == "duplicate" and similarity >= dup_threshold:
        return RouteResult(Route.SKIP, f"duplicate (similarity={similarity:.2f})", "duplicate")

    if confidence < skip_confidence:
        return RouteResult(Route.SKIP, f"confidence too low ({confidence:.2f})", "low_confidence")

    # ─── SILENT AUTO-SAVE (safe, confident, low-stakes) ──────────────────────
    if auto_save_threshold is None:
        # Policy says always confirm (Manual level)
        return RouteResult(Route.CONFIRM, "policy requires confirmation (manual)", "policy_manual")

    allowed_derivations = {"stated", "extracted"}
    if capture_inferred_auto:
        allowed_derivations.add("inferred")

    if (confidence >= auto_save_threshold
            and derivation in allowed_derivations
            and claim_type in safe_types
            and relation in (None, "related")):
        return RouteResult(Route.SAVE, f"safe auto-save (conf={confidence:.2f}, {derivation})", "auto_save")

    # ─── EVERYTHING ELSE ─────────────────────────────────────────────────────
    return RouteResult(Route.CONFIRM, "does not meet auto-save criteria", "fallback")
