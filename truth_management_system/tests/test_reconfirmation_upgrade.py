"""
Tests for Workstream W4 — reconfirmation upgrade (inferred -> stated).

When the user explicitly restates an inferred claim, reinforce_claim with
upgrade_derivation=True promotes derivation inferred->stated and lifts the
inferred confidence cap.
"""

import json

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


def _deriv(api, cid):
    return json.loads(api.claims.get(cid).meta_json)["source"]["derivation"]


def test_upgrade_promotes_inferred_to_stated(api):
    r = api.add_claim(
        "User is health-conscious", "observation", "health", auto_extract=False,
        derivation="inferred",
    )
    cid = r.data.claim_id
    assert _deriv(api, cid) == "inferred"
    capped = api.claims.get(cid).confidence

    res = api.reinforce_claim(cid, upgrade_derivation=True)
    assert res.success
    assert _deriv(api, cid) == "stated"
    # confidence nudged upward past the inferred cap
    assert api.claims.get(cid).confidence >= capped


def test_reinforce_without_flag_keeps_derivation(api):
    r = api.add_claim(
        "User likes hiking", "observation", "personal", auto_extract=False,
        derivation="inferred",
    )
    cid = r.data.claim_id
    api.reinforce_claim(cid)  # no upgrade
    assert _deriv(api, cid) == "inferred"


def test_upgrade_noop_for_already_stated(api):
    r = api.add_claim(
        "I am vegetarian", "fact", "health", auto_extract=False, derivation="stated",
    )
    cid = r.data.claim_id
    res = api.reinforce_claim(cid, upgrade_derivation=True)
    assert res.success
    assert _deriv(api, cid) == "stated"
    assert "Upgraded derivation" not in " ".join(res.warnings or [])
