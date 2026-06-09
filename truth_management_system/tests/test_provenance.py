"""
Tests for Workstream E (provenance).

E1: distilled claims record source_conversation_id / source_message_id in
    meta_json and expose it via get_claim_provenance ("why do I know this?").
E2: distilled-from-conversation claims get a `source:conversation` tag.

Covers the add_claim provenance path, meta_json merge, the distiller threading
(MemoryUpdatePlan -> execute_plan -> add_claim) without hitting the LLM, and the
get_claim_provenance API.
"""

import json

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.interface.conversation_distillation import (
    ConversationDistiller,
    CandidateClaim,
    ProposedAction,
    MemoryUpdatePlan,
)
from truth_management_system.crud.links import get_claim_tags


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


def _tags(api, claim_id):
    return {t.name for t in get_claim_tags(api.db, claim_id)}


# --------------------------------------------------------------------------- #
# E1 — add_claim provenance
# --------------------------------------------------------------------------- #
def test_add_claim_records_provenance(api):
    r = api.add_claim(
        "I prefer tea", "preference", "personal", auto_extract=False,
        source_conversation_id="conv-1", source_message_id="msg-9",
    )
    meta = json.loads(api.claims.get(r.data.claim_id).meta_json)
    src = meta["source"]
    assert src["conversation_id"] == "conv-1"
    assert src["message_id"] == "msg-9"
    assert src["distilled"] is True
    assert src["type"] == "chat_distillation"


def test_provenance_merges_with_existing_meta(api):
    r = api.add_claim(
        "pinned + sourced", "fact", "personal", auto_extract=False,
        meta_json=json.dumps({"pinned": True}),
        source_conversation_id="conv-2",
    )
    meta = json.loads(api.claims.get(r.data.claim_id).meta_json)
    assert meta["pinned"] is True               # preserved
    assert meta["source"]["conversation_id"] == "conv-2"


def test_manual_claim_has_no_source(api):
    r = api.add_claim("plain fact", "fact", "personal", auto_extract=False)
    prov = api.get_claim_provenance(r.data.claim_id)
    assert prov.success
    assert prov.data["source_type"] == "manual"
    assert prov.data["conversation_id"] is None
    assert prov.data["distilled"] is False


def test_get_claim_provenance_missing(api):
    assert not api.get_claim_provenance("nope").success


# --------------------------------------------------------------------------- #
# E2 — source:conversation tag
# --------------------------------------------------------------------------- #
def test_conversation_source_adds_tag(api):
    r = api.add_claim(
        "tagged by source", "fact", "personal", auto_extract=False,
        source_conversation_id="conv-3",
    )
    assert "source:conversation" in _tags(api, r.data.claim_id)


def test_message_only_does_not_tag(api):
    """A message id without a conversation id records provenance but no tag."""
    r = api.add_claim(
        "msg only", "fact", "personal", auto_extract=False,
        source_message_id="m1",
    )
    assert "source:conversation" not in _tags(api, r.data.claim_id)
    assert api.get_claim_provenance(r.data.claim_id).data["message_id"] == "m1"


# --------------------------------------------------------------------------- #
# Distiller threading (no LLM) — plan provenance reaches the saved claim
# --------------------------------------------------------------------------- #
def test_distiller_threads_provenance_to_claim(api):
    api.llm = None  # skip auto_extract LLM calls (distiller hardcodes auto_extract=True)
    distiller = ConversationDistiller(api, {"OPENROUTER_API_KEY": "test-key"})
    cand = CandidateClaim(
        statement="I switched teams at work", claim_type="fact",
        context_domain="work",
    )
    plan = MemoryUpdatePlan(
        candidates=[cand],
        proposed_actions=[ProposedAction(action="add", candidate=cand)],
        source_conversation_id="conv-77",
        source_message_id="msg-5",
    )
    result = distiller.execute_plan(plan, "all", approved_indices=[0])
    assert result.executed
    created = result.execution_results[0]
    assert created.success
    prov = api.get_claim_provenance(created.object_id).data
    assert prov["conversation_id"] == "conv-77"
    assert prov["message_id"] == "msg-5"
    assert "source:conversation" in _tags(api, created.object_id)
