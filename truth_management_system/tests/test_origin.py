"""
Tests for Workstream W5 — auto vs curated origin on entities/tags.

- Auto-created during enrichment (link helpers) -> origin "auto".
- Manually created via the facade -> origin "curated".
- backfill_origin marks pre-existing rows curated (idempotent).
"""

import json

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.crud.links import (
    get_or_create_tag_by_name,
    get_or_create_entity_by_name,
)


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


def _meta(api, table, id_col, oid):
    row = api.db.fetchone(f"SELECT meta_json FROM {table} WHERE {id_col} = ?", (oid,))
    return json.loads(row["meta_json"]) if row["meta_json"] else {}


def test_manual_entity_is_curated(api):
    r = api.add_entity("Mom", "person")
    assert _meta(api, "entities", "entity_id", r.data.entity_id)["origin"] == "curated"


def test_manual_tag_is_curated(api):
    r = api.add_tag("coffee")
    assert _meta(api, "tags", "tag_id", r.data.tag_id)["origin"] == "curated"


def test_auto_created_entity_is_auto(api):
    eid = get_or_create_entity_by_name(api.db, "AutoOrg", "org")
    assert _meta(api, "entities", "entity_id", eid)["origin"] == "auto"


def test_auto_created_tag_is_auto(api):
    tid = get_or_create_tag_by_name(api.db, "autotag")
    assert _meta(api, "tags", "tag_id", tid)["origin"] == "auto"


def test_backfill_origin_idempotent(api):
    # Insert a legacy entity/tag with NULL meta_json directly.
    with api.db.transaction() as conn:
        conn.execute(
            "INSERT INTO entities (entity_id, entity_type, name, meta_json, created_at, updated_at) "
            "VALUES ('e-legacy', 'topic', 'legacy', NULL, '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO tags (tag_id, name, parent_tag_id, meta_json, created_at, updated_at) "
            "VALUES ('t-legacy', 'legacytag', NULL, NULL, '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z')"
        )
    out = api.backfill_origin()
    assert out["entities"] >= 1 and out["tags"] >= 1
    assert _meta(api, "entities", "entity_id", "e-legacy")["origin"] == "curated"
    assert _meta(api, "tags", "tag_id", "t-legacy")["origin"] == "curated"
    # Second run is a no-op.
    out2 = api.backfill_origin()
    assert out2 == {"entities": 0, "tags": 0}
