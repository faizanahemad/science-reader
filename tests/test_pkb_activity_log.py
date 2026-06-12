"""Tests for pkb_activity_log table, write helper, and undo (A4)."""
import json
import pytest
from datetime import datetime, timedelta, timezone
from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.initialize_schema()
    return StructuredAPI(db, {}, config, user_email="test@example.com")


class TestActivityLog:
    def test_log_activity_returns_id(self, api):
        aid = api.log_activity("auto_save", "capture", "claim", "c1")
        assert isinstance(aid, str) and len(aid) > 0

    def test_get_recent_activity(self, api):
        api.log_activity("auto_save", "capture", "claim", "c1")
        api.log_activity("auto_decay", "lifecycle", "claim", "c2")
        entries = api.get_recent_activity()
        assert len(entries) == 2
        actions = {e["action"] for e in entries}
        assert actions == {"auto_save", "auto_decay"}

    def test_activity_stores_prior_state(self, api):
        prior = json.dumps({"statement": "old value"})
        api.log_activity("auto_update", "capture", "claim", "c1", prior_state=prior)
        entries = api.get_recent_activity()
        assert entries[0]["action"] == "auto_update"

    def test_activity_table_exists(self, api):
        conn = api.db.connect()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pkb_activity_log'"
        ).fetchone()
        assert row is not None

    def test_limit(self, api):
        for i in range(10):
            api.log_activity("auto_save", "capture", "claim", f"c{i}")
        assert len(api.get_recent_activity(limit=3)) == 3


class TestUndo:
    def test_undo_auto_save(self, api):
        """Undo an auto_save retracts the claim."""
        # Create a claim first
        conn = api.db.connect()
        conn.execute(
            "INSERT INTO claims (claim_id, user_email, statement, claim_type, context_domain, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
            ("c1", "test@example.com", "Test fact", "fact", "personal",
             datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

        aid = api.log_activity("auto_save", "capture", "claim", "c1")
        result = api.undo_activity(aid)
        assert result["status"] == "undone"
        assert result["restored"] == "claim_retracted"

        # Verify claim is retracted
        row = conn.execute("SELECT status FROM claims WHERE claim_id = 'c1'").fetchone()
        assert row[0] == "retracted"

    def test_undo_auto_update(self, api):
        """Undo an auto_update restores prior statement."""
        conn = api.db.connect()
        conn.execute(
            "INSERT INTO claims (claim_id, user_email, statement, claim_type, context_domain, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
            ("c2", "test@example.com", "New value", "fact", "personal",
             datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

        prior = json.dumps({"statement": "Old value", "updated_at": "2025-01-01T00:00:00Z"})
        aid = api.log_activity("auto_update", "capture", "claim", "c2", prior_state=prior)
        result = api.undo_activity(aid)
        assert result["status"] == "undone"
        assert result["restored"] == "claim_reverted"

        row = conn.execute("SELECT statement FROM claims WHERE claim_id = 'c2'").fetchone()
        assert row[0] == "Old value"

    def test_undo_auto_decay(self, api):
        """Undo a decay reactivates the claim."""
        conn = api.db.connect()
        conn.execute(
            "INSERT INTO claims (claim_id, user_email, statement, claim_type, context_domain, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'dormant', ?, ?)",
            ("c3", "test@example.com", "Dormant fact", "fact", "personal",
             datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

        aid = api.log_activity("auto_decay", "lifecycle", "claim", "c3")
        result = api.undo_activity(aid)
        assert result["status"] == "undone"
        assert result["restored"] == "claim_reactivated"

        row = conn.execute("SELECT status FROM claims WHERE claim_id = 'c3'").fetchone()
        assert row[0] == "active"

    def test_undo_not_found(self, api):
        assert api.undo_activity("nonexistent")["status"] == "not_found"

    def test_undo_already_undone(self, api):
        conn = api.db.connect()
        conn.execute(
            "INSERT INTO claims (claim_id, user_email, statement, claim_type, context_domain, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
            ("c4", "test@example.com", "Test", "fact", "personal",
             datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

        aid = api.log_activity("auto_save", "capture", "claim", "c4")
        api.undo_activity(aid)
        result = api.undo_activity(aid)
        assert result["status"] == "already_undone"

    def test_undo_expired(self, api):
        """Activity past the 24h window returns expired."""
        conn = api.db.connect()
        # Manually insert an expired activity
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        conn.execute(
            """INSERT INTO pkb_activity_log
               (activity_id, user_email, action, facet, object_type, object_id,
                source, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("expired_id", "test@example.com", "auto_save", "capture", "claim", "c5",
             "system", expired_time, expired_time)
        )
        conn.commit()
        result = api.undo_activity("expired_id")
        assert result["status"] == "expired"
