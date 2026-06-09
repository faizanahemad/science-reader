"""
Tests for the conversation-distiller contradiction-detection follow-up
(deferred from Workstream D1).

When an extracted candidate claim contradicts/replaces a closely-matched
existing claim, the distiller proposes a user-confirmed "supersede" action
(save the new claim + link it as superseding/retiring the old one) instead of a
parallel conflicting claim. All offline (fake LLM / direct method calls).
"""

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.interface.conversation_distillation import (
    ConversationDistiller,
    CandidateClaim,
    ProposedAction,
)


class FakeLLMContra:
    """Minimal LLM stub: deterministic contradiction verdict + call counter."""

    def __init__(self, contradicts=True):
        self._contradicts = contradicts
        self.calls = 0

    def detect_contradiction(self, new_statement, existing_statement):
        self.calls += 1
        return self._contradicts


def _api(detect=True, email="distill@example.com"):
    config = PKBConfig(db_path=":memory:", distiller_detect_contradictions=detect)
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {}, config, user_email=email)


def _add(api, statement, claim_type="fact"):
    r = api.add_claim(statement, claim_type, "personal", auto_extract=False)
    assert r.success
    return api.claims.get(r.object_id)


def _distiller(api):
    return ConversationDistiller(api, {}, api.config)


# --------------------------------------------------------------------------- #
# _detect_contradictions
# --------------------------------------------------------------------------- #
def test_contradiction_upgrades_relation():
    api = _api()
    existing = _add(api, "I live in Mumbai")
    api.llm = FakeLLMContra(contradicts=True)
    d = _distiller(api)
    cand = CandidateClaim("I live in Bengaluru", "fact", "personal")
    out = d._detect_contradictions(cand, [(existing, "duplicate")])
    assert out == [(existing, "contradicts")]
    assert api.llm.calls == 1


def test_no_contradiction_keeps_relation():
    api = _api()
    existing = _add(api, "I live in Mumbai")
    api.llm = FakeLLMContra(contradicts=False)
    d = _distiller(api)
    cand = CandidateClaim("I enjoy hiking", "fact", "personal")
    out = d._detect_contradictions(cand, [(existing, "related")])
    assert out == [(existing, "related")]


def test_detection_disabled_by_config():
    api = _api(detect=False)
    existing = _add(api, "I live in Mumbai")
    api.llm = FakeLLMContra(contradicts=True)
    d = _distiller(api)
    cand = CandidateClaim("I live in Bengaluru", "fact", "personal")
    out = d._detect_contradictions(cand, [(existing, "duplicate")])
    assert out == [(existing, "duplicate")]
    assert api.llm.calls == 0  # gated off — no LLM call


def test_detection_noop_without_llm():
    api = _api()
    existing = _add(api, "I live in Mumbai")
    api.llm = None
    d = _distiller(api)
    cand = CandidateClaim("I live in Bengaluru", "fact", "personal")
    out = d._detect_contradictions(cand, [(existing, "duplicate")])
    assert out == [(existing, "duplicate")]


# --------------------------------------------------------------------------- #
# _propose_actions
# --------------------------------------------------------------------------- #
def test_proposes_supersede_on_contradiction():
    api = _api()
    existing = _add(api, "I live in Mumbai")
    d = _distiller(api)
    cand = CandidateClaim("I live in Bengaluru", "fact", "personal")
    actions = d._propose_actions([cand], [(cand, existing, "contradicts")])
    assert len(actions) == 1
    assert actions[0].action == "supersede"
    assert actions[0].existing_claim.claim_id == existing.claim_id


def test_contradiction_takes_priority_over_duplicate():
    api = _api()
    existing = _add(api, "I live in Mumbai")
    d = _distiller(api)
    cand = CandidateClaim("I live in Bengaluru", "fact", "personal")
    # Same candidate matched as both duplicate and contradicts -> supersede wins.
    matches = [(cand, existing, "duplicate"), (cand, existing, "contradicts")]
    actions = d._propose_actions([cand], matches)
    assert len(actions) == 1
    assert actions[0].action == "supersede"


# --------------------------------------------------------------------------- #
# _execute_action (supersede)
# --------------------------------------------------------------------------- #
def test_execute_supersede_links_and_retires_old():
    api = _api()
    existing = _add(api, "I live in Mumbai")
    api.llm = None  # keep add_claim offline (no auto-extract LLM calls)
    d = _distiller(api)
    cand = CandidateClaim("I live in Bengaluru", "fact", "personal")
    action = ProposedAction(
        action="supersede", candidate=cand,
        existing_claim=existing, relation="contradicts",
    )
    res = d._execute_action(action)
    assert res.success
    new_id = res.object_id

    # Old claim retired to superseded; new claim active.
    assert api.claims.get(existing.claim_id).status == "superseded"
    assert api.claims.get(new_id).status == "active"

    # A supersedes link exists from the new claim to the old one.
    link = api.db.fetchone(
        "SELECT from_claim_id, to_claim_id, link_type FROM claim_links "
        "WHERE from_claim_id = ? AND to_claim_id = ?",
        (new_id, existing.claim_id),
    )
    assert link is not None
    assert link["link_type"] == "supersedes"
