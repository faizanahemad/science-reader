"""
Tests for Workstream D2/D3 (consolidation).

D2: cluster near-duplicate claims via cached embeddings and merge a cluster
    into one canonical claim (keeper active, duplicates superseded, tags unioned).
D3: detect entity name variants of the same type and merge them, recording the
    merged-away name as an alias on the canonical entity.

All offline: D2 clustering is exercised at the pure-helper level and via the API
by seeding the embedding cache directly (no LLM); consolidate/merge use
auto_extract=False.
"""

import numpy as np
import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.crud.links import get_claim_tags
from truth_management_system.constants import ClaimStatus
from truth_management_system.search.consolidation import (
    cluster_near_duplicate_claims,
    cluster_entity_variants,
    entity_name_similarity,
)


@pytest.fixture
def api():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {"OPENROUTER_API_KEY": "test-key"}, config)


# --------------------------------------------------------------------------- #
# D2 — clustering helper
# --------------------------------------------------------------------------- #
def test_cluster_near_duplicate_claims_groups_similar():
    emb = [
        ("a", np.array([1.0, 0.0, 0.0], dtype=np.float32)),
        ("b", np.array([0.99, 0.02, 0.0], dtype=np.float32)),
        ("c", np.array([0.0, 1.0, 0.0], dtype=np.float32)),
    ]
    clusters = cluster_near_duplicate_claims(emb, threshold=0.95)
    assert len(clusters) == 1
    assert set(clusters[0]["claim_ids"]) == {"a", "b"}
    assert clusters[0]["max_similarity"] >= 0.95


def test_cluster_near_duplicate_claims_below_threshold():
    emb = [
        ("a", np.array([1.0, 0.0], dtype=np.float32)),
        ("b", np.array([0.0, 1.0], dtype=np.float32)),
    ]
    assert cluster_near_duplicate_claims(emb, threshold=0.95) == []


# --------------------------------------------------------------------------- #
# D2 — consolidate_claims (supersede + tag union)
# --------------------------------------------------------------------------- #
def test_consolidate_claims_supersedes_and_unions_tags(api):
    a = api.add_claim("I love hiking", "preference", "personal",
                      auto_extract=False, tags=["outdoors"]).data.claim_id
    b = api.add_claim("I really love hiking", "preference", "personal",
                      auto_extract=False, tags=["fitness"]).data.claim_id
    r = api.consolidate_claims([a, b], keep_id=a)
    assert r.success
    assert r.data["kept"] == a and r.data["superseded"] == [b]
    assert api.claims.get(a).status == "active"
    assert api.claims.get(b).status == ClaimStatus.SUPERSEDED.value
    assert {t.name for t in get_claim_tags(api.db, a)} == {"outdoors", "fitness"}


def test_consolidate_claims_default_keeper_is_highest_confidence(api):
    a = api.add_claim("dup one", "fact", "personal",
                      auto_extract=False, confidence=0.4).data.claim_id
    b = api.add_claim("dup two", "fact", "personal",
                      auto_extract=False, confidence=0.9).data.claim_id
    r = api.consolidate_claims([a, b])  # no keep_id -> highest confidence
    assert r.success
    assert r.data["kept"] == b


def test_consolidate_claims_requires_two(api):
    a = api.add_claim("solo", "fact", "personal", auto_extract=False).data.claim_id
    assert not api.consolidate_claims([a]).success


def test_consolidate_claims_rejects_bad_keep_id(api):
    a = api.add_claim("x", "fact", "personal", auto_extract=False).data.claim_id
    b = api.add_claim("y", "fact", "personal", auto_extract=False).data.claim_id
    assert not api.consolidate_claims([a, b], keep_id="not-in-cluster").success


# --------------------------------------------------------------------------- #
# D3 — entity name similarity + clustering
# --------------------------------------------------------------------------- #
def test_entity_name_similarity_token_subset():
    assert entity_name_similarity("john", "John Smith", 0.85) >= 0.85
    assert entity_name_similarity("Google", "Microsoft", 0.85) < 0.85


def test_cluster_entity_variants_groups_by_name():
    class E:
        def __init__(self, i, n):
            self.entity_id, self.name = i, n
    ents = [E("1", "john"), E("2", "John Smith"), E("3", "Google")]
    clusters = cluster_entity_variants(ents, 0.85)
    assert len(clusters) == 1
    assert set(clusters[0]["entity_ids"]) == {"1", "2"}
    assert clusters[0]["suggested_keep_id"] == "2"  # longest/canonical name


# --------------------------------------------------------------------------- #
# D3 — merge_entities (aliases + claim re-pointing)
# --------------------------------------------------------------------------- #
def test_merge_entities_records_alias_and_deletes_source(api):
    src, _ = api.entities.get_or_create("john", "person")
    tgt, _ = api.entities.get_or_create("John Smith", "person")
    m = api.merge_entities(src.entity_id, tgt.entity_id)
    assert m.success
    assert m.data["aliases"] == ["john"]
    assert api.entities.get(src.entity_id) is None
    import json
    assert json.loads(api.entities.get(tgt.entity_id).meta_json)["aliases"] == ["john"]


def test_merge_entities_repoints_claims(api):
    src, _ = api.entities.get_or_create("acme", "org")
    tgt, _ = api.entities.get_or_create("Acme Corporation", "org")
    c = api.add_claim("works at acme", "fact", "work", auto_extract=False).data.claim_id
    api.link_entity_to_claim(c, src.entity_id)
    api.merge_entities(src.entity_id, tgt.entity_id)
    ents = api.get_claim_entities_list(c).data  # list of (Entity, role)
    assert any(ent.entity_id == tgt.entity_id for ent, _role in ents)


def test_merge_entities_rejects_self_and_missing(api):
    e, _ = api.entities.get_or_create("solo", "person")
    assert not api.merge_entities(e.entity_id, e.entity_id).success
    assert not api.merge_entities("nope", e.entity_id).success


def test_find_entity_duplicates_finds_variants(api):
    api.entities.get_or_create("bob", "person")
    api.entities.get_or_create("Bob Jones", "person")
    api.entities.get_or_create("Unrelated Org", "org")
    clusters = api.find_entity_duplicates("person").data
    assert len(clusters) == 1
    assert clusters[0]["max_similarity"] >= api.config.entity_dedup_threshold
