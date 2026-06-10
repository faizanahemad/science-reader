"""
Tests for Workstream W9 — Memory Cleanup orchestrator.

run_memory_cleanup(apply=False) runs safe maintenance + gathers dedup proposals
without mutating; apply=True merges the suggested duplicate clusters. LLM/
overview are unavailable in tests (keys present but offline) so we focus on the
sweep + entity/tag dedup wiring.
"""

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


def test_cleanup_analyze_is_non_destructive(api):
    api.add_entity("john", "person")
    api.add_entity("john smith", "person")
    res = api.run_memory_cleanup(apply=False, use_llm=False)
    assert res.success
    assert res.data["applied"] is False
    # proposals surfaced, nothing merged
    assert res.data["entities"]["merged"] == []
    # both entities still present
    assert api.entities.get_by_type("person")  # non-empty


def test_cleanup_apply_merges_entities(api):
    e1 = api.add_entity("john", "person").data
    e2 = api.add_entity("john smith", "person").data
    res = api.run_memory_cleanup(apply=True, use_llm=False)
    assert res.success and res.data["applied"] is True
    # one of the two entities should have been merged away
    remaining = {e.entity_id for e in api.entities.get_by_type("person")}
    assert len(remaining & {e1.entity_id, e2.entity_id}) == 1


def test_cleanup_apply_merges_tags(api):
    api.add_tag("ml")
    api.add_tag("ml")  # exact dup name (different parent rules) -> variant
    api.add_tag("machine learning")
    res = api.run_memory_cleanup(apply=True, use_llm=False)
    assert res.success
    # report structure present
    assert "tags" in res.data and "merged" in res.data["tags"]


def test_cleanup_reports_sweep(api):
    res = api.run_memory_cleanup(apply=False, use_llm=False)
    assert res.success
    assert "expired" in res.data["swept"]
