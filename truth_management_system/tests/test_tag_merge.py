"""
Tests for Workstream W6 — tag merge.

TagCRUD.merge re-points claim_tags, re-parents children, deletes source;
facade merge_tags records aliases; find_tag_duplicates clusters name variants.
"""

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.crud.links import link_claim_tag, get_claim_tags


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


def test_merge_repoints_claim_links(api):
    src = api.add_tag("ML").data
    tgt = api.add_tag("machine learning").data
    claim = api.add_claim("I study ML", "fact", "learning", auto_extract=False).data
    link_claim_tag(api.db, claim.claim_id, src.tag_id)

    res = api.merge_tags(src.tag_id, tgt.tag_id)
    assert res.success
    # link moved to target, source gone
    tag_ids = {t.tag_id for t in get_claim_tags(api.db, claim.claim_id)}
    assert tgt.tag_id in tag_ids
    assert src.tag_id not in tag_ids
    assert api.tags.get(src.tag_id) is None
    assert "ML" in res.data["aliases"]


def test_merge_reparents_children(api):
    parent = api.add_tag("sports").data
    target = api.add_tag("athletics").data
    child = api.add_tag("running", parent_tag_id=parent.tag_id).data

    api.merge_tags(parent.tag_id, target.tag_id)
    # child now hangs off the target
    assert api.tags.get(child.tag_id).parent_tag_id == target.tag_id


def test_merge_rejects_self(api):
    t = api.add_tag("solo").data
    assert not api.merge_tags(t.tag_id, t.tag_id).success


def test_merge_missing(api):
    t = api.add_tag("real").data
    assert not api.merge_tags("nope", t.tag_id).success


def test_merge_target_child_of_source_no_cycle(api):
    # target is a child of source; merging source->target must not self-cycle
    source = api.add_tag("vehicles").data
    target = api.add_tag("cars", parent_tag_id=source.tag_id).data
    res = api.merge_tags(source.tag_id, target.tag_id)
    assert res.success
    assert api.tags.get(source.tag_id) is None
    assert api.tags.get(target.tag_id).parent_tag_id is None


def test_find_tag_duplicates(api):
    api.add_tag("john")
    api.add_tag("john smith")
    api.add_tag("unrelated")
    res = api.find_tag_duplicates()
    assert res.success
    # the john / john smith pair should cluster
    joined = [set(c["names"].values()) for c in res.data]
    assert any({"john", "john smith"} <= names for names in joined)
