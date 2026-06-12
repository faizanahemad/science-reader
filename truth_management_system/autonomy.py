"""
Memory autonomy dial — policy derivation.

Pure function ``derive_policy(autonomy, overrides)`` maps the 0–100 master dial
(plus optional per-facet overrides) to a concrete policy dict that downstream
code (capture routing, curation, lifecycle, enrichment) reads.

No side-effects, no DB access, no imports outside stdlib + this package's
constants.  Designed for exhaustive unit testing.
"""

from __future__ import annotations
from typing import Any, Dict, Optional

# ─── Detent boundaries ───────────────────────────────────────────────────────
# [0, 12] → Manual(0), [13,37] → Assisted(25), [38,62] → Balanced(50),
# [63,87] → Proactive(75), [88,100] → Full(100)
_DETENT_BOUNDS = [(0, 12), (13, 37), (38, 62), (63, 87), (88, 100)]
_DETENT_NAMES = ["manual", "assisted", "balanced", "proactive", "full"]


def _level(autonomy: int) -> int:
    """Return detent index 0–4 from raw 0–100 value."""
    autonomy = max(0, min(100, int(autonomy)))
    for i, (lo, hi) in enumerate(_DETENT_BOUNDS):
        if lo <= autonomy <= hi:
            return i
    return 2  # fallback: balanced


# ─── Band table ──────────────────────────────────────────────────────────────
# Each entry: key → tuple of 5 values (manual, assisted, balanced, proactive, full)

_BAND_TABLE: Dict[str, tuple] = {
    # Capture facet
    "capture_safe_stated_threshold": (None, 0.95, 0.85, 0.75, 0.0),
    # None = always confirm; 0.0 = always save (non-escalated)
    "capture_inferred_auto": (False, False, False, False, True),
    "capture_sensitive_auto": (False, False, False, False, True),
    # ^ at Full, sensitive still notifies+undo (enforced by routing, not here)

    # STM promotion
    "stm_promotion_threshold": (999, 4, 3, 2, 1),
    # 999 = effectively manual

    # Curation
    "dedup_on_add": ("off", "warn", "reinforce", "reinforce", "reinforce"),
    "consolidation_threshold": (None, None, 0.97, 0.95, 0.93),
    # None = propose only
    "entity_merge_threshold": (None, None, 0.92, 0.88, 0.85),
    "conflict_resolution": ("manual", "manual", "manual", "assisted", "auto"),

    # Updates/edits to existing claims
    "update_existing_auto": ("confirm", "low_risk", "low_risk", "non_sensitive_confident", "auto"),

    # Lifecycle
    "dormancy_mode": ("off", "off", "gentle", "on", "aggressive"),
    "sweep_interval_seconds": (0, 86400, 43200, 21600, 3600),
    "hard_expiry_auto": (False, False, True, True, True),

    # Enrichment
    "enrichment_mode": ("on_demand", "auto", "auto", "auto", "auto"),
    "overview_refresh": ("manual", "on_demand", "periodic", "periodic", "continuous"),
}

# Facets and which keys belong to each (for override application)
_FACET_KEYS = {
    "capture": ["capture_safe_stated_threshold", "capture_inferred_auto",
                "capture_sensitive_auto", "stm_promotion_threshold"],
    "curation": ["dedup_on_add", "consolidation_threshold", "entity_merge_threshold",
                 "conflict_resolution", "update_existing_auto"],
    "lifecycle": ["dormancy_mode", "sweep_interval_seconds", "hard_expiry_auto"],
    "enrichment": ["enrichment_mode", "overview_refresh"],
}


def derive_policy(
    autonomy: int,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Derive the full policy dict from a master autonomy level + overrides.

    Args:
        autonomy: Integer 0–100 (clamped).
        overrides: Optional dict with per-facet autonomy overrides, e.g.
            ``{"lifecycle": 0}`` to keep lifecycle at Manual regardless.
            Keys are facet names; values are autonomy ints 0–100.

    Returns:
        Dict with every policy key set to its band-table value, plus metadata:
        ``_level`` (detent name), ``_autonomy`` (raw int).

    Invariants enforced:
        I4: policy is a pure function of (autonomy, overrides) — deterministic.
        I5: at autonomy=0 with no overrides, every auto-* key is off/confirm/None.
    """
    autonomy = max(0, min(100, int(autonomy)))
    level = _level(autonomy)
    overrides = overrides or {}

    policy: Dict[str, Any] = {
        "_autonomy": autonomy,
        "_level": _DETENT_NAMES[level],
    }

    # Compute per-facet effective levels
    facet_levels: Dict[str, int] = {}
    for facet in _FACET_KEYS:
        if facet in overrides:
            facet_levels[facet] = _level(max(0, min(100, int(overrides[facet]))))
        else:
            facet_levels[facet] = level

    # Fill policy from band table using each key's facet level
    for facet, keys in _FACET_KEYS.items():
        fl = facet_levels[facet]
        for key in keys:
            policy[key] = _BAND_TABLE[key][fl]

    return policy
