"""
Tests for Short-Term Cross-Conversation Memory (STM).

Covers: CRUD, expiry, reinforcement, auto-promotion, compaction integration,
recency rerank with last_accessed_at.
"""

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
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config, user_email="test@example.com")


# ─── CRUD ─────────────────────────────────────────────────────────────────────

class TestSTMCrud:
    def test_add_and_list(self, api):
        res = api.add_short_term_memory(
            statement="Debugging React hooks",
            conversation_id="conv-1",
            importance="high",
            ttl_class="week",
        )
        assert res.success
        assert res.data["statement"] == "Debugging React hooks"
        assert res.data["importance"] == "high"

        listed = api.get_active_short_term_memories(limit=10)
        assert listed.success
        assert len(listed.data) == 1
        assert listed.data[0]["statement"] == "Debugging React hooks"

    def test_add_validates_importance(self, api):
        res = api.add_short_term_memory(
            statement="test", conversation_id="c", importance="low"
        )
        assert not res.success

    def test_add_validates_ttl_class(self, api):
        res = api.add_short_term_memory(
            statement="test", conversation_id="c", ttl_class="forever"
        )
        assert not res.success

    def test_delete(self, api):
        add = api.add_short_term_memory("test", "c1")
        mid = add.data["memory_id"]
        res = api.delete_short_term_memory(mid)
        assert res.success
        listed = api.get_active_short_term_memories()
        assert len(listed.data) == 0

    def test_meta_json_round_trip(self, api):
        meta = {"reasoning": "active project", "source_conversation_title": "Chat about React"}
        add = api.add_short_term_memory("React migration", "c1", meta_json=meta)
        assert add.success
        listed = api.get_active_short_term_memories()
        assert listed.data[0]["meta_json"] == meta


# ─── Expiry ───────────────────────────────────────────────────────────────────

class TestSTMExpiry:
    def test_expire_removes_past_due(self, api):
        # Insert a memory, then manually set expires_at to the past
        add = api.add_short_term_memory("old context", "c1", ttl_class="session")
        mid = add.data["memory_id"]
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with api.db.transaction() as conn:
            conn.execute(
                "UPDATE pkb_short_term_memory SET expires_at = ? WHERE memory_id = ?",
                (past, mid),
            )
        result = api.expire_short_term_memories()
        assert result.success
        assert result.data == 1  # 1 deleted
        assert len(api.get_active_short_term_memories().data) == 0

    def test_expire_leaves_active(self, api):
        api.add_short_term_memory("still active", "c1", ttl_class="week")
        result = api.expire_short_term_memories()
        assert result.data == 0
        assert len(api.get_active_short_term_memories().data) == 1


# ─── Reinforcement & Promotion ────────────────────────────────────────────────

class TestSTMReinforcement:
    def test_reinforce_increments_count(self, api):
        add = api.add_short_term_memory("topic X", "c1", importance="medium")
        mid = add.data["memory_id"]
        res = api.reinforce_short_term_memory(mid)
        assert res.success
        assert res.data["reinforcement_count"] == 1

    def test_reinforce_extends_ttl(self, api):
        add = api.add_short_term_memory("topic X", "c1", ttl_class="day")
        mid = add.data["memory_id"]
        original_expires = add.data["expires_at"]
        api.reinforce_short_term_memory(mid)
        listed = api.get_active_short_term_memories()
        new_expires = listed.data[0]["expires_at"]
        # New expires should be later than original
        assert new_expires > original_expires

    def test_auto_promote_at_threshold(self, api):
        # Config default: stm_promotion_threshold=3, need importance=high
        add = api.add_short_term_memory("important thing", "c1", importance="high")
        mid = add.data["memory_id"]
        # Reinforce 3 times to hit threshold
        api.reinforce_short_term_memory(mid)
        api.reinforce_short_term_memory(mid)
        res = api.reinforce_short_term_memory(mid)
        assert res.success
        assert res.data["promoted_to_claim_id"] is not None

    def test_no_promote_if_medium_importance(self, api):
        add = api.add_short_term_memory("medium thing", "c1", importance="medium")
        mid = add.data["memory_id"]
        for _ in range(4):
            api.reinforce_short_term_memory(mid)
        listed = api.get_active_short_term_memories()
        assert listed.data[0]["promoted_to_claim_id"] is None

    def test_manual_promote(self, api):
        add = api.add_short_term_memory("promote me", "c1")
        mid = add.data["memory_id"]
        res = api.promote_short_term_memory(mid)
        assert res.success
        assert "claim_id" in res.data


# ─── Touch (last_accessed_at) ────────────────────────────────────────────────

class TestSTMTouch:
    def test_touch_short_term_memories(self, api):
        add = api.add_short_term_memory("stmt", "c1")
        mid = add.data["memory_id"]
        api.touch_short_term_memories([mid])
        listed = api.get_active_short_term_memories()
        assert listed.data[0]["last_accessed_at"] is not None

    def test_touch_claims_accessed(self, api):
        claim_res = api.add_claim(
            statement="I like Python", claim_type="preference", context_domain="tech"
        )
        assert claim_res.success
        claim_id = claim_res.data.claim_id
        api.touch_claims_accessed([claim_id])
        # Verify by reading the claim
        row = api.db.fetchone(
            "SELECT last_accessed_at FROM claims WHERE claim_id = ?", (claim_id,)
        )
        assert row is not None and row[0] is not None


# ─── Compaction in run_memory_cleanup ─────────────────────────────────────────

class TestSTMCompaction:
    def test_cleanup_reports_stm_expired(self, api):
        add = api.add_short_term_memory("old", "c1", ttl_class="session")
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        with api.db.transaction() as conn:
            conn.execute(
                "UPDATE pkb_short_term_memory SET expires_at = ? WHERE memory_id = ?",
                (past, add.data["memory_id"]),
            )
        res = api.run_memory_cleanup(apply=False, use_llm=False)
        assert res.success
        assert res.data["compaction"]["stm_expired"] == 1

    def test_cleanup_identifies_stale_claims(self, api):
        # Add a low-confidence, old claim
        api.add_claim(statement="old fact", claim_type="fact",
                      context_domain="personal", confidence=0.3)
        # Artificially age it
        old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        with api.db.transaction() as conn:
            conn.execute(
                "UPDATE claims SET last_accessed_at = ?, updated_at = ? WHERE statement = ?",
                (old_date, old_date, "old fact"),
            )
        res = api.run_memory_cleanup(apply=False, use_llm=False)
        assert res.success
        stale = res.data["compaction"]["stale_candidates"]
        assert len(stale) == 1
        assert stale[0]["statement"] == "old fact"

    def test_cleanup_archives_stale_on_apply(self, api):
        api.add_claim(statement="ancient fact", claim_type="fact",
                      context_domain="personal", confidence=0.2)
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        with api.db.transaction() as conn:
            conn.execute(
                "UPDATE claims SET last_accessed_at = ?, updated_at = ? WHERE statement = ?",
                (old_date, old_date, "ancient fact"),
            )
        res = api.run_memory_cleanup(apply=True, use_llm=False)
        assert res.success
        assert len(res.data["compaction"]["archived"]) == 1
        # Verify the claim is now archived
        row = api.db.fetchone(
            "SELECT status FROM claims WHERE statement = ?", ("ancient fact",)
        )
        assert row[0] == "archived"
