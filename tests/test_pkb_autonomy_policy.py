"""Exhaustive tests for derive_policy — the memory autonomy band table (A2)."""
import pytest
from truth_management_system.autonomy import derive_policy, _BAND_TABLE, _FACET_KEYS, _level


class TestDetentMapping:
    """_level maps 0-100 to the correct detent index."""

    @pytest.mark.parametrize("val,expected", [
        (0, 0), (5, 0), (12, 0),   # Manual
        (13, 1), (25, 1), (37, 1),  # Assisted
        (38, 2), (50, 2), (62, 2),  # Balanced
        (63, 3), (75, 3), (87, 3),  # Proactive
        (88, 4), (100, 4),          # Full
    ])
    def test_detent_boundaries(self, val, expected):
        assert _level(val) == expected

    def test_clamps_negative(self):
        assert _level(-5) == 0

    def test_clamps_above_100(self):
        assert _level(150) == 4


class TestDerivePolicy:
    """derive_policy returns correct band values."""

    def test_returns_metadata(self):
        p = derive_policy(50)
        assert p["_autonomy"] == 50
        assert p["_level"] == "balanced"

    def test_all_keys_present(self):
        p = derive_policy(50)
        for key in _BAND_TABLE:
            assert key in p, f"Missing key: {key}"

    @pytest.mark.parametrize("autonomy,level_name", [
        (0, "manual"), (25, "assisted"), (50, "balanced"),
        (75, "proactive"), (100, "full"),
    ])
    def test_detent_names(self, autonomy, level_name):
        assert derive_policy(autonomy)["_level"] == level_name

    # ─── Invariant I5: Manual (0) = everything off/confirm ───────────────────
    def test_invariant_i5_manual_all_off(self):
        p = derive_policy(0)
        assert p["capture_safe_stated_threshold"] is None  # always confirm
        assert p["capture_inferred_auto"] is False
        assert p["capture_sensitive_auto"] is False
        assert p["stm_promotion_threshold"] == 999
        assert p["dedup_on_add"] == "off"
        assert p["consolidation_threshold"] is None
        assert p["entity_merge_threshold"] is None
        assert p["conflict_resolution"] == "manual"
        assert p["update_existing_auto"] == "confirm"
        assert p["dormancy_mode"] == "off"
        assert p["sweep_interval_seconds"] == 0
        assert p["hard_expiry_auto"] is False
        assert p["enrichment_mode"] == "on_demand"
        assert p["overview_refresh"] == "manual"

    # ─── Invariant: Full (100) = maximally autonomous ────────────────────────
    def test_full_maximally_auto(self):
        p = derive_policy(100)
        assert p["capture_safe_stated_threshold"] == 0.0
        assert p["capture_inferred_auto"] is True
        assert p["capture_sensitive_auto"] is True
        assert p["stm_promotion_threshold"] == 1
        assert p["dedup_on_add"] == "reinforce"
        assert p["consolidation_threshold"] == 0.93
        assert p["entity_merge_threshold"] == 0.85
        assert p["conflict_resolution"] == "auto"
        assert p["update_existing_auto"] == "auto"
        assert p["dormancy_mode"] == "aggressive"
        assert p["sweep_interval_seconds"] == 3600
        assert p["hard_expiry_auto"] is True
        assert p["enrichment_mode"] == "auto"
        assert p["overview_refresh"] == "continuous"

    # ─── Balanced (50) = the recommended default ─────────────────────────────
    def test_balanced_values(self):
        p = derive_policy(50)
        assert p["capture_safe_stated_threshold"] == 0.85
        assert p["capture_inferred_auto"] is False
        assert p["dormancy_mode"] == "gentle"
        assert p["sweep_interval_seconds"] == 43200  # 12h
        assert p["conflict_resolution"] == "manual"

    # ─── Proactive (75) ──────────────────────────────────────────────────────
    def test_proactive_values(self):
        p = derive_policy(75)
        assert p["capture_safe_stated_threshold"] == 0.75
        assert p["conflict_resolution"] == "assisted"
        assert p["update_existing_auto"] == "non_sensitive_confident"
        assert p["dormancy_mode"] == "on"

    # ─── Invariant I4: Pure / deterministic ──────────────────────────────────
    def test_invariant_i4_deterministic(self):
        p1 = derive_policy(42)
        p2 = derive_policy(42)
        assert p1 == p2

    def test_invariant_i4_deterministic_with_overrides(self):
        o = {"lifecycle": 0, "capture": 100}
        p1 = derive_policy(50, o)
        p2 = derive_policy(50, o)
        assert p1 == p2


class TestFacetOverrides:
    """Per-facet overrides work correctly."""

    def test_lifecycle_override_to_manual(self):
        p = derive_policy(100, {"lifecycle": 0})
        # Lifecycle keys should be at Manual level
        assert p["dormancy_mode"] == "off"
        assert p["sweep_interval_seconds"] == 0
        assert p["hard_expiry_auto"] is False
        # But capture should still be at Full
        assert p["capture_safe_stated_threshold"] == 0.0

    def test_capture_override_to_full(self):
        p = derive_policy(0, {"capture": 100})
        # Capture at Full
        assert p["capture_safe_stated_threshold"] == 0.0
        assert p["capture_inferred_auto"] is True
        # Curation still at Manual
        assert p["conflict_resolution"] == "manual"

    def test_multiple_overrides(self):
        p = derive_policy(50, {"lifecycle": 100, "curation": 0})
        assert p["dormancy_mode"] == "aggressive"  # lifecycle at Full
        assert p["conflict_resolution"] == "manual"  # curation at Manual
        assert p["capture_safe_stated_threshold"] == 0.85  # capture at Balanced (master)

    def test_override_clamped(self):
        p = derive_policy(50, {"lifecycle": 999})
        assert p["dormancy_mode"] == "aggressive"  # clamped to 100 → Full

    def test_unknown_facet_ignored(self):
        p1 = derive_policy(50, {"unknown_facet": 100})
        p2 = derive_policy(50)
        assert p1 == p2


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_clamping_negative_autonomy(self):
        p = derive_policy(-50)
        assert p["_level"] == "manual"
        assert p["_autonomy"] == 0

    def test_clamping_above_100(self):
        p = derive_policy(200)
        assert p["_level"] == "full"
        assert p["_autonomy"] == 100

    def test_boundary_12_13(self):
        """12 is Manual, 13 is Assisted."""
        assert derive_policy(12)["_level"] == "manual"
        assert derive_policy(13)["_level"] == "assisted"

    def test_boundary_37_38(self):
        assert derive_policy(37)["_level"] == "assisted"
        assert derive_policy(38)["_level"] == "balanced"

    def test_boundary_62_63(self):
        assert derive_policy(62)["_level"] == "balanced"
        assert derive_policy(63)["_level"] == "proactive"

    def test_boundary_87_88(self):
        assert derive_policy(87)["_level"] == "proactive"
        assert derive_policy(88)["_level"] == "full"

    def test_all_band_table_keys_in_some_facet(self):
        """Every band-table key must belong to a facet."""
        all_facet_keys = set()
        for keys in _FACET_KEYS.values():
            all_facet_keys.update(keys)
        for key in _BAND_TABLE:
            assert key in all_facet_keys, f"{key} not assigned to any facet"

    def test_band_table_tuples_have_5_entries(self):
        for key, vals in _BAND_TABLE.items():
            assert len(vals) == 5, f"{key} has {len(vals)} entries, expected 5"
