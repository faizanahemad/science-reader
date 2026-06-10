"""
Tests for Workstream W10 — audit coverage for merges and provenance changes.

merge_entities, merge_tags, consolidate_claims and the reinforce derivation
upgrade write entries to the audit_log (read back via get_audit_log).
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


def _audit_actions(api):
    res = api.get_audit_log(limit=100)
    assert res.success
    return [e.get("action") for e in res.data["entries"]]


def test_merge_entities_audited(api):
    a = api.add_entity("john", "person").data
    b = api.add_entity("john smith", "person").data
    api.merge_entities(a.entity_id, b.entity_id)
    assert "merge" in _audit_actions(api)


def test_merge_tags_audited(api):
    a = api.add_tag("ml").data
    b = api.add_tag("machine learning").data
    api.merge_tags(a.tag_id, b.tag_id)
    assert "merge" in _audit_actions(api)


def test_derivation_upgrade_audited(api):
    r = api.add_claim(
        "User runs daily", "observation", "health", auto_extract=False,
        derivation="inferred",
    )
    api.reinforce_claim(r.data.claim_id, upgrade_derivation=True)
    assert "derivation_change" in _audit_actions(api)
