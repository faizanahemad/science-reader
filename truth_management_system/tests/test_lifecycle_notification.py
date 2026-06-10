"""
Tests for Workstream W8 — lifecycle-change notification.

When an add/extract supersedes an existing claim, add_claim reports the change
in ActionResult.metadata["lifecycle_changes"], and the distiller aggregates
them onto DistillationResult.lifecycle_changes.
"""

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


def test_add_with_supersedes_reports_lifecycle_change(api):
    old = api.add_claim("I live in Mumbai", "fact", "personal", auto_extract=False).data
    res = api.add_claim(
        "I live in Bengaluru", "fact", "personal", auto_extract=False,
        supersedes=old.claim_id,
    )
    assert res.success
    changes = res.metadata.get("lifecycle_changes", [])
    assert len(changes) == 1
    assert changes[0]["claim_id"] == old.claim_id
    assert changes[0]["new_status"] == "superseded"
    assert changes[0]["by_claim_id"] == res.data.claim_id


def test_plain_add_has_no_lifecycle_changes(api):
    res = api.add_claim("I like tea", "preference", "personal", auto_extract=False)
    assert res.metadata.get("lifecycle_changes", []) == []


def test_distiller_aggregates_lifecycle_changes(api):
    api.llm = None
    old = api.add_claim("I work at Acme", "fact", "work", auto_extract=False).data
    distiller = ConversationDistiller(api, {"OPENROUTER_API_KEY": "test-key"}, api.config)
    cand = CandidateClaim(
        statement="I work at Globex now", claim_type="fact", context_domain="work",
        derivation="stated",
    )
    plan = MemoryUpdatePlan(
        candidates=[cand],
        proposed_actions=[
            ProposedAction(action="supersede", candidate=cand, existing_claim=old)
        ],
        source_conversation_id="c1",
    )
    result = distiller.execute_plan(plan, "all", approved_indices=[0])
    assert result.executed
    assert any(c["claim_id"] == old.claim_id for c in result.lifecycle_changes)
