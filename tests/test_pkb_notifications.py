"""Tests for PKB Notification System (v14)."""
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


class TestNotificationSchema:
    def test_table_exists(self, api):
        conn = api.db.connect()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pkb_notifications'"
        ).fetchone()
        assert row is not None

    def test_indexes_exist(self, api):
        conn = api.db.connect()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_notif%'"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "idx_notif_user_unresolved" in names
        assert "idx_notif_object" in names
        assert "idx_notif_activity" in names


class TestCreateNotification:
    def test_basic_create(self, api):
        nid = api.create_notification(
            priority="high", category="confirm_required",
            title="Confirm: test claim",
        )
        assert isinstance(nid, str) and len(nid) > 0

    def test_create_with_all_fields(self, api):
        nid = api.create_notification(
            priority="medium", category="auto_save",
            title="Auto-saved: running 5k",
            body="I run 5k every morning",
            object_type="claim", object_id="claim-123",
            activity_id="act-456",
            action_required=False,
            available_actions=["undo", "dismiss"],
            action_payload={"claim_id": "claim-123", "statement": "I run 5k"},
            source="distillation", session_id="conv-789",
        )
        notifs = api.get_notifications(unresolved_only=False)
        assert len(notifs) == 1
        n = notifs[0]
        assert n["priority"] == "medium"
        assert n["category"] == "auto_save"
        assert n["object_id"] == "claim-123"
        assert n["activity_id"] == "act-456"
        assert n["available_actions"] == ["undo", "dismiss"]
        assert n["action_payload"]["claim_id"] == "claim-123"
        assert n["session_id"] == "conv-789"


class TestGetNotifications:
    def test_filter_by_priority(self, api):
        api.create_notification(priority="high", category="confirm_required", title="H")
        api.create_notification(priority="low", category="claim_confirmed", title="L")
        high = api.get_notifications(priority="high")
        assert len(high) == 1 and high[0]["title"] == "H"

    def test_filter_by_category(self, api):
        api.create_notification(priority="high", category="confirm_required", title="A")
        api.create_notification(priority="high", category="conflict_detected", title="B")
        conflicts = api.get_notifications(category="conflict_detected")
        assert len(conflicts) == 1 and conflicts[0]["title"] == "B"

    def test_unresolved_only(self, api):
        nid = api.create_notification(priority="high", category="confirm_required", title="X")
        api.resolve_notification(nid, "dismiss")
        unresolved = api.get_notifications(unresolved_only=True)
        assert len(unresolved) == 0
        all_notifs = api.get_notifications(unresolved_only=False)
        assert len(all_notifs) == 1

    def test_unseen_only(self, api):
        nid = api.create_notification(priority="high", category="confirm_required", title="Y")
        api.mark_seen([nid])
        unseen = api.get_notifications(unseen_only=True)
        assert len(unseen) == 0

    def test_pagination(self, api):
        for i in range(5):
            api.create_notification(priority="medium", category="auto_save", title=f"N{i}")
        page1 = api.get_notifications(limit=2, offset=0)
        page2 = api.get_notifications(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["title"] != page2[0]["title"]


class TestNotificationCount:
    def test_badge_count(self, api):
        api.create_notification(priority="high", category="confirm_required",
                                title="A", action_required=True)
        api.create_notification(priority="low", category="claim_confirmed",
                                title="B", action_required=False)
        api.create_notification(priority="medium", category="auto_save",
                                title="C", action_required=False)
        # Badge = unseen + action_required + high/medium
        count = api.get_notification_count()
        assert count == 1  # only the high action_required one

    def test_count_decreases_on_resolve(self, api):
        nid = api.create_notification(priority="high", category="confirm_required",
                                      title="A", action_required=True)
        assert api.get_notification_count() == 1
        api.resolve_notification(nid, "dismiss")
        assert api.get_notification_count() == 0


class TestResolveNotification:
    def test_dismiss(self, api):
        nid = api.create_notification(priority="medium", category="auto_save", title="T")
        result = api.resolve_notification(nid, "dismiss")
        assert result["status"] == "resolved"

    def test_not_found(self, api):
        result = api.resolve_notification("nonexistent", "dismiss")
        assert result["status"] == "not_found"

    def test_already_resolved(self, api):
        nid = api.create_notification(priority="medium", category="auto_save", title="T")
        api.resolve_notification(nid, "dismiss")
        result = api.resolve_notification(nid, "dismiss")
        assert result["status"] == "already_resolved"

    def test_approve_executes_claim(self, api):
        nid = api.create_notification(
            priority="high", category="confirm_required",
            title="Confirm: test",
            action_required=True,
            available_actions=["approve", "reject", "dismiss"],
            action_payload={
                "proposed_action": "add",
                "statement": "I like pizza",
                "claim_type": "preference",
                "context_domain": "personal",
                "confidence": 0.9,
            },
        )
        result = api.resolve_notification(nid, "approve")
        assert result["status"] == "resolved"
        assert result.get("claim_id") is not None
        # Verify claim was actually created
        conn = api.db.connect()
        row = conn.execute("SELECT statement FROM claims WHERE claim_id = ?",
                           (result["claim_id"],)).fetchone()
        assert row[0] == "I like pizza"

    def test_approve_stale_check_blocks_duplicate(self, api):
        # Add a claim first
        api.add_claim(statement="I like pizza", claim_type="preference",
                      context_domain="personal")
        # Create notification for same statement
        nid = api.create_notification(
            priority="high", category="confirm_required",
            title="Confirm: I like pizza",
            action_payload={
                "proposed_action": "add", "statement": "I like pizza",
                "claim_type": "preference", "context_domain": "personal",
            },
        )
        result = api.resolve_notification(nid, "approve")
        assert result["status"] == "stale_conflict"

    def test_reject_logs_activity(self, api):
        nid = api.create_notification(
            priority="high", category="confirm_required", title="Confirm: X",
            action_payload={"proposed_action": "add", "statement": "X",
                            "claim_type": "fact", "context_domain": "personal"},
        )
        api.resolve_notification(nid, "reject")
        entries = api.get_recent_activity()
        assert any(e["action"] == "user_reject" for e in entries)

    def test_undo_calls_undo_activity(self, api):
        # Create a claim and log activity
        result = api.add_claim(statement="Auto fact", claim_type="fact",
                               context_domain="personal")
        act_id = api.log_activity("auto_save", "capture", "claim", result.object_id)
        nid = api.create_notification(
            priority="medium", category="auto_save", title="Auto-saved",
            activity_id=act_id, object_type="claim", object_id=result.object_id,
        )
        resolve_result = api.resolve_notification(nid, "undo")
        assert resolve_result["status"] == "resolved"
        assert resolve_result["undo_status"] == "undone"


class TestConflictResolution:
    def test_pick_new_supersedes_existing(self, api):
        r1 = api.add_claim(statement="I prefer coffee", claim_type="preference",
                           context_domain="personal")
        r2 = api.add_claim(statement="I prefer tea", claim_type="preference",
                           context_domain="personal")
        cs = api.create_conflict_set([r1.object_id, r2.object_id])
        # Get the notification that was auto-created
        notifs = api.get_notifications(category="conflict_detected")
        assert len(notifs) == 1
        result = api.resolve_notification(notifs[0]["notification_id"], "pick_new")
        assert result["status"] == "resolved"
        # Check existing (second) claim was superseded
        conn = api.db.connect()
        row = conn.execute("SELECT status FROM claims WHERE claim_id = ?",
                           (r2.object_id,)).fetchone()
        assert row[0] == "superseded"


class TestMarkSeen:
    def test_mark_seen(self, api):
        nid1 = api.create_notification(priority="high", category="confirm_required", title="A")
        nid2 = api.create_notification(priority="medium", category="auto_save", title="B")
        count = api.mark_seen([nid1, nid2])
        assert count == 2
        notifs = api.get_notifications(unseen_only=True)
        assert len(notifs) == 0

    def test_mark_seen_idempotent(self, api):
        nid = api.create_notification(priority="high", category="confirm_required", title="A")
        api.mark_seen([nid])
        count = api.mark_seen([nid])
        assert count == 0


class TestBulkResolve:
    def test_bulk_dismiss(self, api):
        ids = []
        for i in range(3):
            ids.append(api.create_notification(priority="low", category="claim_confirmed", title=f"N{i}"))
        result = api.bulk_resolve(ids, "dismiss")
        assert result["resolved"] == 3


class TestSyncHooks:
    def test_undo_activity_resolves_notification(self, api):
        """When undo_activity is called directly, linked notification is auto-resolved."""
        result = api.add_claim(statement="Sync test", claim_type="fact",
                               context_domain="personal")
        act_id = api.log_activity("auto_save", "capture", "claim", result.object_id)
        nid = api.create_notification(
            priority="medium", category="auto_save", title="Synced",
            activity_id=act_id, object_id=result.object_id, object_type="claim",
        )
        # Undo via activity log directly (not via notification)
        api.undo_activity(act_id)
        # Notification should be auto-resolved
        notifs = api.get_notifications(unresolved_only=True)
        assert len(notifs) == 0
        all_notifs = api.get_notifications(unresolved_only=False)
        assert all_notifs[0]["action_taken"] == "undone_externally"

    def test_delete_claim_resolves_notifications(self, api):
        """When a claim is retracted, pending notifications for it are resolved."""
        result = api.add_claim(statement="Will be deleted", claim_type="fact",
                               context_domain="personal")
        nid = api.create_notification(
            priority="high", category="confirm_required", title="Pending",
            object_type="claim", object_id=result.object_id,
        )
        api.delete_claim(result.object_id)
        notifs = api.get_notifications(unresolved_only=True)
        assert len(notifs) == 0

    def test_resolve_notifications_for_object(self, api):
        api.create_notification(priority="medium", category="auto_save",
                                title="A", object_id="obj-1", object_type="claim")
        api.create_notification(priority="medium", category="auto_save",
                                title="B", object_id="obj-1", object_type="claim")
        count = api.resolve_notifications_for_object("obj-1")
        assert count == 2


class TestCheckRemindersDue:
    def test_creates_reminder_notification(self, api):
        """Reminder claims due within threshold get notifications."""
        from truth_management_system.utils import now_iso
        # Create a reminder claim due in 12 hours
        due = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        api.add_claim(statement="Dentist appointment", claim_type="reminder",
                      context_domain="personal", valid_to=due)
        count = api.check_reminders_due(threshold_hours=24)
        assert count == 1
        notifs = api.get_notifications(category="reminder_due")
        assert len(notifs) == 1
        assert "Dentist" in notifs[0]["title"]

    def test_no_duplicate_reminder_notification(self, api):
        """Same reminder doesn't get notified twice."""
        due = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        api.add_claim(statement="Dentist", claim_type="reminder",
                      context_domain="personal", valid_to=due)
        api.check_reminders_due(threshold_hours=24)
        api.check_reminders_due(threshold_hours=24)
        notifs = api.get_notifications(category="reminder_due", unresolved_only=False)
        assert len(notifs) == 1

    def test_past_due_not_notified(self, api):
        """Reminders already past are not notified (valid_to < now)."""
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        api.add_claim(statement="Expired", claim_type="reminder",
                      context_domain="personal", valid_to=past)
        count = api.check_reminders_due(threshold_hours=24)
        assert count == 0


class TestPruneLowPriority:
    def test_prune_excess(self, api):
        # Create 5 resolved low-priority notifications
        for i in range(5):
            nid = api.create_notification(priority="low", category="claim_confirmed", title=f"N{i}")
            api.resolve_notification(nid, "dismiss")
        # Prune to keep only 3
        pruned = api.prune_low_priority(keep=3)
        assert pruned == 2
        conn = api.db.connect()
        count = conn.execute(
            "SELECT COUNT(*) FROM pkb_notifications WHERE user_email = ? AND priority = 'low'",
            ("test@example.com",)
        ).fetchone()[0]
        assert count == 3

    def test_prune_no_action_when_under_cap(self, api):
        nid = api.create_notification(priority="low", category="claim_confirmed", title="X")
        api.resolve_notification(nid, "dismiss")
        pruned = api.prune_low_priority(keep=500)
        assert pruned == 0
