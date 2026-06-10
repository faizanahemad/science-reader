"""
Tests for Workstream W2 — distiller/ingestion derivation labeling.

The extraction LLM labels each candidate stated|extracted|inferred; the label
is threaded through execute_plan -> add_claim and recorded on meta_json.source,
with inferred claims getting the confidence cap from W1.
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


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


def _src(api, claim_id):
    return json.loads(api.claims.get(claim_id).meta_json)["source"]


def test_candidate_default_derivation():
    assert CandidateClaim("s", "fact", "personal").derivation == "extracted"


def test_distiller_threads_inferred_and_caps_confidence(api):
    api.llm = None
    distiller = ConversationDistiller(api, {"OPENROUTER_API_KEY": "test-key"}, api.config)
    cand = CandidateClaim(
        statement="User is health-conscious", claim_type="observation",
        context_domain="health", confidence=0.9, derivation="inferred",
    )
    plan = MemoryUpdatePlan(
        candidates=[cand],
        proposed_actions=[ProposedAction(action="add", candidate=cand)],
        source_conversation_id="conv-1",
    )
    result = distiller.execute_plan(plan, "all", approved_indices=[0])
    assert result.executed
    cid = result.execution_results[0].data.claim_id
    src = _src(api, cid)
    assert src["channel"] == "chat"
    assert src["derivation"] == "inferred"
    assert api.claims.get(cid).confidence <= api.config.inferred_confidence_cap


def test_distiller_stated_label_preserved(api):
    api.llm = None
    distiller = ConversationDistiller(api, {"OPENROUTER_API_KEY": "test-key"}, api.config)
    cand = CandidateClaim(
        statement="I work at Acme", claim_type="fact", context_domain="work",
        derivation="stated",
    )
    plan = MemoryUpdatePlan(
        candidates=[cand],
        proposed_actions=[ProposedAction(action="add", candidate=cand)],
        source_conversation_id="conv-2",
    )
    result = distiller.execute_plan(plan, "all", approved_indices=[0])
    cid = result.execution_results[0].data.claim_id
    assert _src(api, cid)["derivation"] == "stated"
    assert _src(api, cid)["channel"] == "chat"
