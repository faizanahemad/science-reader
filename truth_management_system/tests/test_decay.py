"""
Tests for Workstream F2 — soft-TTL dormancy decay sweep.

Covers:
- Inert by default (dormancy_threshold == 0 -> no-op).
- Stale active claims flip to dormant; fresh ones survive.
- Pinned claims and exempt types are never decayed.
- last_reinforced_at (not updated_at) drives the decay clock.
- Reinforcing a dormant claim revives it (F2 <-> H bridge).
- StructuredAPI.run_decay_sweep entry point.
- F3 status coordination: dormant is excluded from default search but stays
  in the visible set.
"""

from datetime import datetime, timezone, timedelta

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.models import Claim
from truth_management_system.constants import ClaimStatus
from truth_management_system.crud import ClaimCRUD
from truth_management_system.utils import decay_dormant_claims


def _iso(days_from_now: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days_from_now)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    keys = {"OPENROUTER_API_KEY": "test-key"}
    return StructuredAPI(db, keys, config)


def _add(api, statement="some memory", ctype="preference", **kw):
    return ClaimCRUD(api.db).add(Claim.create(statement, ctype, "health", **kw))


def _set_reinforced(api, claim_id, days_ago):
    ClaimCRUD(api.db).edit(claim_id, {"last_reinforced_at": _iso(-days_ago)})


def _status(api, claim_id):
    return api.claims.get(claim_id).status


# --------------------------------------------------------------------------- #
# Inert by default
# --------------------------------------------------------------------------- #
def test_decay_inert_by_default(api):
    claim = _add(api)
    _set_reinforced(api, claim.claim_id, 10_000)  # ancient
    # default config: dormancy_threshold == 0.0
    n = decay_dormant_claims(api.db, api.config)
    assert n == 0
    assert _status(api, claim.claim_id) == ClaimStatus.ACTIVE.value


# --------------------------------------------------------------------------- #
# Core decay behavior
# --------------------------------------------------------------------------- #
def test_decay_flips_stale_active_to_dormant(api):
    api.config.dormancy_threshold = 0.5
    api.config.recency_half_life_days = 30.0

    stale = _add(api, statement="old habit")
    _set_reinforced(api, stale.claim_id, 365)  # freshness = 0.5**(365/30) ~ 0
    fresh = _add(api, statement="recent habit")
    _set_reinforced(api, fresh.claim_id, 0)  # freshness = 1.0

    n = decay_dormant_claims(api.db, api.config)
    assert n == 1
    assert _status(api, stale.claim_id) == ClaimStatus.DORMANT.value
    assert _status(api, fresh.claim_id) == ClaimStatus.ACTIVE.value


def test_decay_uses_last_reinforced_not_updated_at(api):
    """A claim old by updated_at but recently reinforced must NOT go dormant."""
    api.config.dormancy_threshold = 0.5
    api.config.recency_half_life_days = 30.0

    claim = _add(api, statement="kept fresh by reinforcement")
    # updated_at ancient, last_reinforced_at recent
    ClaimCRUD(api.db).edit(
        claim.claim_id,
        {"updated_at": _iso(-400), "last_reinforced_at": _iso(-1)},
    )
    n = decay_dormant_claims(api.db, api.config)
    assert n == 0
    assert _status(api, claim.claim_id) == ClaimStatus.ACTIVE.value


def test_decay_skips_pinned(api):
    api.config.dormancy_threshold = 0.5
    api.config.recency_half_life_days = 30.0
    claim = _add(api, statement="pinned old fact")
    _set_reinforced(api, claim.claim_id, 365)
    api.pin_claim(claim.claim_id, pin=True)  # pin (also reinforces, so re-age)
    _set_reinforced(api, claim.claim_id, 365)  # make it stale again post-pin

    n = decay_dormant_claims(api.db, api.config)
    assert n == 0
    assert _status(api, claim.claim_id) == ClaimStatus.ACTIVE.value


def test_decay_skips_exempt_types(api):
    api.config.dormancy_threshold = 0.5
    api.config.recency_half_life_days = 30.0
    api.config.dormancy_exempt_types = ["fact"]

    fact = _add(api, statement="I am vegetarian", ctype="fact")
    _set_reinforced(api, fact.claim_id, 365)
    pref = _add(api, statement="old preference", ctype="preference")
    _set_reinforced(api, pref.claim_id, 365)

    n = decay_dormant_claims(api.db, api.config)
    assert n == 1
    assert _status(api, fact.claim_id) == ClaimStatus.ACTIVE.value
    assert _status(api, pref.claim_id) == ClaimStatus.DORMANT.value


def test_decay_respects_per_type_half_life(api):
    api.config.dormancy_threshold = 0.5
    api.config.recency_half_life_days = 30.0
    # A long half-life for 'fact' keeps it fresh at the same age.
    api.config.half_life_by_type = {"fact": 10_000.0}

    fact = _add(api, statement="durable fact", ctype="fact")
    _set_reinforced(api, fact.claim_id, 365)
    n = decay_dormant_claims(api.db, api.config)
    assert n == 0
    assert _status(api, fact.claim_id) == ClaimStatus.ACTIVE.value


# --------------------------------------------------------------------------- #
# Bridge to Workstream H: reinforce revives
# --------------------------------------------------------------------------- #
def test_reinforce_revives_decayed_claim(api):
    api.config.dormancy_threshold = 0.5
    api.config.recency_half_life_days = 30.0
    claim = _add(api, statement="forgotten then recalled")
    _set_reinforced(api, claim.claim_id, 365)

    decay_dormant_claims(api.db, api.config)
    assert _status(api, claim.claim_id) == ClaimStatus.DORMANT.value

    res = api.reinforce_claim(claim.claim_id)
    assert res.success
    assert res.data.status == ClaimStatus.ACTIVE.value


# --------------------------------------------------------------------------- #
# API entry point + status coordination
# --------------------------------------------------------------------------- #
def test_run_decay_sweep_entry_point(api):
    api.config.dormancy_threshold = 0.5
    api.config.recency_half_life_days = 30.0
    claim = _add(api)
    _set_reinforced(api, claim.claim_id, 365)

    res = api.run_decay_sweep()
    assert res.success
    assert res.action == "decay"
    assert res.data["dormant_count"] == 1
    assert _status(api, claim.claim_id) == ClaimStatus.DORMANT.value


def test_dormant_excluded_from_default_search_but_visible():
    assert ClaimStatus.DORMANT.value not in ClaimStatus.default_search_statuses()
    assert ClaimStatus.DORMANT.value in ClaimStatus.all_visible_statuses()
