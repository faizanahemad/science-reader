"""
Tests for Workstream F1 (scheduled lifecycle sweep) and F4 (notifications).

F1: run_lifecycle_sweep runs hard-TTL expiry + soft-TTL dormancy unconditionally;
    the background scheduler is config-gated and start/stoppable.
F4: get_lifecycle_notifications surfaces soon-to-expire task/reminder claims and
    newly-dormant claims.

All offline (auto_extract=False; the dormancy clock is driven via the ``now``
parameter so no real time passes).
"""

from datetime import datetime, timezone, timedelta

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.utils import run_lifecycle_sweep, decay_dormant_claims
from truth_management_system import scheduler


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {}, config)


def _iso(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# --------------------------------------------------------------------------- #
# F1 — lifecycle sweep
# --------------------------------------------------------------------------- #
def test_run_lifecycle_sweep_expires_past_due(api):
    api.add_claim("old task", "task", "personal",
                  auto_extract=False, valid_to=_iso(-1))
    api.add_claim("future task", "task", "personal",
                  auto_extract=False, valid_to=_iso(30))
    counts = run_lifecycle_sweep(api.db, api.config)
    assert counts["expired"] == 1
    assert counts["dormant"] == 0


def test_run_lifecycle_sweep_dormancy_when_enabled(api):
    api.config.dormancy_threshold = 0.5  # enable soft-TTL
    api.config.recency_half_life_days = 30.0
    api.add_claim("stale fact", "fact", "personal", auto_extract=False)
    # Sweep far in the future so the claim's freshness drops below threshold.
    future = datetime.now(timezone.utc) + timedelta(days=365)
    counts = run_lifecycle_sweep(api.db, api.config, now=future)
    assert counts["dormant"] == 1


def test_api_run_lifecycle_sweep(api):
    api.add_claim("expired reminder", "reminder", "personal",
                  auto_extract=False, valid_to=_iso(-2))
    result = api.run_lifecycle_sweep()
    assert result.success
    assert result.data["expired"] == 1


# --------------------------------------------------------------------------- #
# F1 — scheduler
# --------------------------------------------------------------------------- #
def test_scheduler_disabled_by_default(api):
    assert scheduler.start_lifecycle_sweep_scheduler(api.db, api.config) is None
    assert scheduler.is_running() is False


def test_scheduler_starts_and_stops(api):
    cfg = PKBConfig(db_path=":memory:", sweep_interval_seconds=1)
    try:
        t = scheduler.start_lifecycle_sweep_scheduler(api.db, cfg)
        assert t is not None
        assert scheduler.is_running()
        # Idempotent: starting again returns the same live thread.
        assert scheduler.start_lifecycle_sweep_scheduler(api.db, cfg) is t
    finally:
        scheduler.stop_lifecycle_sweep_scheduler()


# --------------------------------------------------------------------------- #
# F4 — notifications
# --------------------------------------------------------------------------- #
def test_notifications_soon_to_expire_window(api):
    api.add_claim("call dentist", "reminder", "personal",
                  auto_extract=False, valid_to=_iso(2))     # within 7d
    api.add_claim("renew passport", "task", "personal",
                  auto_extract=False, valid_to=_iso(60))    # outside 7d
    data = api.get_lifecycle_notifications(within_days=7).data
    assert data["counts"]["soon_to_expire"] == 1
    assert data["soon_to_expire"][0]["statement"] == "call dentist"


def test_notifications_only_task_and_reminder(api):
    # A non-task/reminder claim with valid_to should not appear.
    api.add_claim("temp preference", "preference", "personal",
                  auto_extract=False, valid_to=_iso(3))
    data = api.get_lifecycle_notifications(within_days=7).data
    assert data["counts"]["soon_to_expire"] == 0


def test_notifications_newly_dormant(api):
    api.config.dormancy_threshold = 0.5
    api.config.recency_half_life_days = 30.0
    api.add_claim("stale note", "fact", "personal", auto_extract=False)
    # Flip to dormant via a future-dated sweep (stamps updated_at = now).
    future = datetime.now(timezone.utc) + timedelta(days=365)
    assert decay_dormant_claims(api.db, api.config, now=future) == 1
    data = api.get_lifecycle_notifications(within_days=7).data
    assert data["counts"]["newly_dormant"] == 1
    assert data["newly_dormant"][0]["statement"] == "stale note"
