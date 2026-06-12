"""Tests for pkb_user_settings table and StructuredAPI get/set methods (A1)."""
import json
import pytest
from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI


@pytest.fixture
def api():
    """Create an in-memory StructuredAPI instance."""
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.initialize_schema()
    return StructuredAPI(db, {}, config, user_email="test@example.com")


class TestUserSettings:
    def test_get_defaults_when_no_row(self, api):
        """No settings row => returns config default_autonomy."""
        settings = api.get_user_settings()
        assert settings["memory_autonomy"] == 0  # config.default_autonomy = 0
        assert settings["facet_overrides"] is None
        assert settings["updated_at"] is None

    def test_set_and_get(self, api):
        """Set then get returns the saved values."""
        result = api.set_user_settings(memory_autonomy=75)
        assert result["memory_autonomy"] == 75
        assert result["facet_overrides"] is None
        assert result["updated_at"] is not None

        settings = api.get_user_settings()
        assert settings["memory_autonomy"] == 75

    def test_set_with_overrides(self, api):
        """facet_overrides round-trips as JSON."""
        overrides = {"capture": {"auto_save": False}}
        api.set_user_settings(memory_autonomy=50, facet_overrides=overrides)
        settings = api.get_user_settings()
        assert settings["facet_overrides"] == overrides

    def test_upsert(self, api):
        """Second set overwrites first."""
        api.set_user_settings(memory_autonomy=25)
        api.set_user_settings(memory_autonomy=80)
        assert api.get_user_settings()["memory_autonomy"] == 80

    def test_clamp_range(self, api):
        """Autonomy is clamped to [0, 100]."""
        api.set_user_settings(memory_autonomy=-10)
        assert api.get_user_settings()["memory_autonomy"] == 0
        api.set_user_settings(memory_autonomy=200)
        assert api.get_user_settings()["memory_autonomy"] == 100

    def test_requires_email(self, api):
        """set without email raises ValueError."""
        bare = StructuredAPI(api.db, {}, api.config, user_email=None)
        with pytest.raises(ValueError):
            bare.set_user_settings(memory_autonomy=50)

    def test_get_for_different_user(self, api):
        """Settings are per-email."""
        api.set_user_settings(memory_autonomy=90)
        other = api.get_user_settings(email="other@example.com")
        assert other["memory_autonomy"] == 0  # default, no row

    def test_table_exists_after_migration(self, api):
        """The table is present in the schema."""
        conn = api.db.connect()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pkb_user_settings'"
        ).fetchone()
        assert row is not None


class TestDefaultAutonomy:
    def test_config_default_is_zero(self):
        """PKBConfig ships with default_autonomy=0 (dev-inert)."""
        config = PKBConfig()
        assert config.default_autonomy == 0

    def test_config_to_dict_includes_default_autonomy(self):
        config = PKBConfig(default_autonomy=50)
        d = config.to_dict()
        assert d["default_autonomy"] == 50

    def test_config_from_dict(self):
        config = PKBConfig.from_dict({"default_autonomy": 75})
        assert config.default_autonomy == 75


class TestForUserPolicyResolution:
    """for_user attaches the correct policy from user settings."""

    def test_for_user_attaches_policy_default(self, api):
        """No settings row => policy derived from default_autonomy=0 (Manual)."""
        user_api = api.for_user("new@example.com")
        assert user_api.policy is not None
        assert user_api.policy["_level"] == "manual"
        assert user_api.policy["_autonomy"] == 0
        assert user_api.policy["capture_safe_stated_threshold"] is None  # confirm

    def test_for_user_with_saved_settings(self, api):
        """Saved autonomy=75 => Proactive policy."""
        api.set_user_settings(memory_autonomy=75, email="pro@example.com")
        user_api = api.for_user("pro@example.com")
        assert user_api.policy["_level"] == "proactive"
        assert user_api.policy["capture_safe_stated_threshold"] == 0.75
        assert user_api.policy["conflict_resolution"] == "assisted"

    def test_for_user_with_overrides(self, api):
        """Facet overrides are applied."""
        api.set_user_settings(
            memory_autonomy=50,
            facet_overrides={"lifecycle": 0},
            email="mixed@example.com"
        )
        user_api = api.for_user("mixed@example.com")
        assert user_api.policy["_level"] == "balanced"
        # Lifecycle overridden to Manual
        assert user_api.policy["dormancy_mode"] == "off"
        assert user_api.policy["sweep_interval_seconds"] == 0
        # Capture still at Balanced
        assert user_api.policy["capture_safe_stated_threshold"] == 0.85

    def test_bare_api_has_no_policy(self, api):
        """Direct construction (not via for_user) has policy=None."""
        assert api.policy is None
