"""
Tests for Workstream D1 — supersession links + chain-head retrieval.

Covers:
- Schema v9 claim_links table + crud/links.py claim-claim helpers.
- StructuredAPI.supersede_claim: link creation, old->superseded, guards.
- Multi-hop chain-head traversal (cycle/depth guarded).
- add_claim(supersedes=...) explicit path.
- resolve_conflict_set records winner->loser supersedes links.
- Superseded claims drop out of default retrieval (chain head preferred).
- H4 bridge: a superseded claim cannot be reinforced.
"""

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.constants import ClaimStatus
from truth_management_system.crud.links import (
    link_claims,
    unlink_claims,
    get_incoming_links,
    get_outgoing_links,
    get_supersession_head,
    LINK_SUPERSEDES,
)


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


def _add(api, statement, ctype="fact", domain="personal"):
    return api.add_claim(statement, ctype, domain, auto_extract=False).data


# --------------------------------------------------------------------------- #
# Schema / links CRUD
# --------------------------------------------------------------------------- #
def test_schema_is_v9_with_claim_links(api):
    assert api.db.get_schema_version() >= 9
    row = api.db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='claim_links'"
    )
    assert row is not None


def test_link_claims_and_chain_head(api):
    a = _add(api, "v1")
    b = _add(api, "v2")
    c = _add(api, "v3")
    assert link_claims(api.db, b.claim_id, a.claim_id, LINK_SUPERSEDES)
    assert link_claims(api.db, c.claim_id, b.claim_id, LINK_SUPERSEDES)
    # head of the oldest is the newest
    assert get_supersession_head(api.db, a.claim_id) == c.claim_id
    assert get_supersession_head(api.db, c.claim_id) == c.claim_id
    assert len(get_incoming_links(api.db, a.claim_id)) == 1
    assert len(get_outgoing_links(api.db, c.claim_id)) == 1


def test_link_claims_rejects_self_and_dup(api):
    a = _add(api, "x")
    b = _add(api, "y")
    assert link_claims(api.db, a.claim_id, a.claim_id, LINK_SUPERSEDES) is None
    assert link_claims(api.db, b.claim_id, a.claim_id, LINK_SUPERSEDES)
    assert link_claims(api.db, b.claim_id, a.claim_id, LINK_SUPERSEDES) is None  # dup


def test_get_supersession_head_cycle_guard(api):
    a = _add(api, "a")
    b = _add(api, "b")
    link_claims(api.db, b.claim_id, a.claim_id, LINK_SUPERSEDES)
    link_claims(api.db, a.claim_id, b.claim_id, LINK_SUPERSEDES)  # cycle
    # must terminate, not loop forever
    head = get_supersession_head(api.db, a.claim_id)
    assert head in (a.claim_id, b.claim_id)


def test_unlink_claims(api):
    a = _add(api, "a")
    b = _add(api, "b")
    link_claims(api.db, b.claim_id, a.claim_id, LINK_SUPERSEDES)
    assert unlink_claims(api.db, b.claim_id, a.claim_id)
    assert get_incoming_links(api.db, a.claim_id) == []


# --------------------------------------------------------------------------- #
# StructuredAPI.supersede_claim
# --------------------------------------------------------------------------- #
def test_supersede_claim_transition(api):
    old = _add(api, "I live in Bengaluru")
    new = _add(api, "I live in Mumbai")
    res = api.supersede_claim(new.claim_id, old.claim_id, resolution_notes="moved")
    assert res.success
    assert res.data["head_claim_id"] == new.claim_id
    assert api.claims.get(old.claim_id).status == ClaimStatus.SUPERSEDED.value
    assert api.claims.get(new.claim_id).status == ClaimStatus.ACTIVE.value


def test_supersede_claim_guards(api):
    a = _add(api, "a")
    assert not api.supersede_claim(a.claim_id, a.claim_id).success  # self
    assert not api.supersede_claim(a.claim_id, "missing-id").success  # missing old
    assert not api.supersede_claim("missing-id", a.claim_id).success  # missing new


def test_supersede_claim_idempotent_link(api):
    old = _add(api, "old")
    new = _add(api, "new")
    r1 = api.supersede_claim(new.claim_id, old.claim_id)
    r2 = api.supersede_claim(new.claim_id, old.claim_id)
    assert r1.success and r2.success
    assert r2.warnings  # warns the link already existed
    assert len(get_incoming_links(api.db, old.claim_id)) == 1


def test_add_claim_supersedes_param(api):
    old = _add(api, "old address")
    res = api.add_claim(
        "new address", "fact", "personal",
        auto_extract=False, supersedes=old.claim_id,
    )
    assert res.success
    assert api.claims.get(old.claim_id).status == ClaimStatus.SUPERSEDED.value
    assert get_supersession_head(api.db, old.claim_id) == res.data.claim_id


# --------------------------------------------------------------------------- #
# Conflict resolution records the supersession graph
# --------------------------------------------------------------------------- #
def test_resolve_conflict_records_supersedes_links(api):
    a = _add(api, "the meeting is on Monday")
    b = _add(api, "the meeting is on Tuesday")
    cs = api.create_conflict_set([a.claim_id, b.claim_id], "scheduling conflict")
    assert cs.success
    res = api.resolve_conflict_set(
        cs.data.conflict_set_id, "Tuesday is correct", winning_claim_id=b.claim_id
    )
    assert res.success
    # loser superseded + a supersedes link b -> a recorded
    assert api.claims.get(a.claim_id).status == ClaimStatus.SUPERSEDED.value
    assert get_supersession_head(api.db, a.claim_id) == b.claim_id


# --------------------------------------------------------------------------- #
# Retrieval / lifecycle interplay
# --------------------------------------------------------------------------- #
def test_superseded_excluded_from_active_set(api):
    old = _add(api, "old job at Foo")
    new = _add(api, "new job at Bar")
    api.supersede_claim(new.claim_id, old.claim_id)
    active_ids = {c.claim_id for c in api.claims.get_active()}
    assert old.claim_id not in active_ids       # buried
    assert new.claim_id in active_ids           # chain head retained
    # default search statuses exclude superseded
    assert ClaimStatus.SUPERSEDED.value not in ClaimStatus.default_search_statuses()


def test_superseded_claim_cannot_be_reinforced(api):
    old = _add(api, "stale")
    new = _add(api, "fresh")
    api.supersede_claim(new.claim_id, old.claim_id)
    # H4 safeguard: reinforcing a superseded claim is refused
    res = api.reinforce_claim(old.claim_id)
    assert not res.success
