"""
Tests for Workstream W-D — tag-linked retrieval strategy.

These run fully offline (no API key): without a query embedding the strategy
degrades to recency ordering, so resolution, the tag-hierarchy traversal, status
filtering, the top-N / max-tags caps, the rewrite-tags passthrough and the
default-disabled no-op are all exercised here. Cosine ranking quality requires
embeddings and is covered with cached deterministic vectors.
"""

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.crud.claims import ClaimCRUD
from truth_management_system.crud.tags import TagCRUD
from truth_management_system.crud.links import link_claim_tag
from truth_management_system.constants import ClaimStatus
from truth_management_system.models import Claim
from truth_management_system.search.base import SearchFilters
from truth_management_system.search.tag_search import TagSearchStrategy


def _env(enabled=True):
    # The strategy is INERT by default; enable it explicitly for resolution tests.
    config = PKBConfig(db_path=":memory:", tag_strategy_enabled=enabled)
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return config, db, ClaimCRUD(db), TagCRUD(db)


def _claim(claims, statement, status="active"):
    c = Claim.create(statement=statement, claim_type="fact", context_domain="personal")
    c.status = status
    return claims.add(c)


def _tag(tags, name, parent_tag_id=None):
    tag, _created = tags.get_or_create(name, parent_tag_id=parent_tag_id)
    return tag


def test_resolves_tag_by_exact_name():
    config, db, claims, tags = _env()
    health = _tag(tags, "health")
    c = _claim(claims, "I switched to a Mediterranean diet.")
    link_claim_tag(db, c.claim_id, health.tag_id)

    strat = TagSearchStrategy(db, {}, config)
    # token-extraction path: "health" appears as a query word
    results = strat.search("how is my health going", filters=SearchFilters())

    assert [r.claim.claim_id for r in results] == [c.claim_id]
    assert results[0].source == "tag"
    assert health.tag_id in results[0].metadata["matched_tags"]


def test_explicit_tag_names_from_rewrite():
    """A caller (the rewrite LLM) can supply category tags the query lacks."""
    config, db, claims, tags = _env()
    health = _tag(tags, "health")
    c = _claim(claims, "Started running three times a week.")
    link_claim_tag(db, c.claim_id, health.tag_id)

    strat = TagSearchStrategy(db, {}, config)
    # Query has no literal "health" token; the rewrite supplies it.
    assert strat.search("am I keeping my fitness resolutions", filters=SearchFilters()) == []
    results = strat.search(
        "am I keeping my fitness resolutions",
        filters=SearchFilters(),
        tag_names=["health"],
    )
    assert [r.claim.claim_id for r in results] == [c.claim_id]


def test_no_tag_match_returns_empty():
    config, db, claims, tags = _env()
    health = _tag(tags, "health")
    c = _claim(claims, "I switched to a Mediterranean diet.")
    link_claim_tag(db, c.claim_id, health.tag_id)

    strat = TagSearchStrategy(db, {}, config)
    # No query token matches a known tag name.
    assert strat.search("tell me about the weather", filters=SearchFilters()) == []


def test_hierarchy_parent_tag_pulls_descendant_claims():
    """Resolving a parent tag surfaces claims tagged under descendant tags."""
    config, db, claims, tags = _env()
    health = _tag(tags, "health")
    fitness = _tag(tags, "fitness", parent_tag_id=health.tag_id)
    c = _claim(claims, "Ran a 10k personal best.")
    link_claim_tag(db, c.claim_id, fitness.tag_id)  # linked to the CHILD tag

    strat = TagSearchStrategy(db, {}, config)
    # Query resolves the parent "health"; hierarchy traversal reaches the child.
    results = strat.search("health update", filters=SearchFilters())
    assert [r.claim.claim_id for r in results] == [c.claim_id]


def test_status_filter_excludes_non_default_statuses():
    config, db, claims, tags = _env()
    work = _tag(tags, "work")
    active = _claim(claims, "Shipped the work project.", status="active")
    superseded = _claim(
        claims, "Old work deadline.", status=ClaimStatus.SUPERSEDED.value
    )
    link_claim_tag(db, active.claim_id, work.tag_id)
    link_claim_tag(db, superseded.claim_id, work.tag_id)

    strat = TagSearchStrategy(db, {}, config)
    ids = [r.claim.claim_id for r in strat.search("work status", filters=SearchFilters())]
    assert active.claim_id in ids
    assert superseded.claim_id not in ids


def test_top_n_cap():
    config, db, claims, tags = _env()
    config.tag_strategy_top_n = 3
    health = _tag(tags, "health")
    for i in range(8):
        c = _claim(claims, f"Health fact number {i}.")
        link_claim_tag(db, c.claim_id, health.tag_id)

    strat = TagSearchStrategy(db, {}, config)
    results = strat.search("health", filters=SearchFilters())
    assert len(results) == 3


def test_max_tags_cap():
    """Resolution is bounded by tag_strategy_max_tags (anti-flooding)."""
    config, db, claims, tags = _env()
    config.tag_strategy_max_tags = 3
    names = ["alpha", "bravo", "charlie", "delta", "echo"]
    for n in names:
        t = _tag(tags, n)
        c = _claim(claims, f"{n} note")
        link_claim_tag(db, c.claim_id, t.tag_id)

    strat = TagSearchStrategy(db, {}, config)
    ids = strat._resolve_tag_ids("ignored", SearchFilters(), tag_names=names)
    assert len(ids) == 3


def test_disabled_flag_is_noop():
    """Default-disabled (inert): must return nothing even with a matching tag."""
    config, db, claims, tags = _env(enabled=False)
    assert config.tag_strategy_enabled is False
    health = _tag(tags, "health")
    c = _claim(claims, "A health fact.")
    link_claim_tag(db, c.claim_id, health.tag_id)

    strat = TagSearchStrategy(db, {}, config)
    assert strat.search("health", filters=SearchFilters()) == []


def test_cosine_ranking_orders_by_similarity():
    """When a query embedding is available, results sort by cosine similarity."""
    import numpy as np

    config, db, claims, tags = _env()
    health = _tag(tags, "health")
    near = _claim(claims, "health near match")
    far = _claim(claims, "health far match")
    link_claim_tag(db, near.claim_id, health.tag_id)
    link_claim_tag(db, far.claim_id, health.tag_id)

    strat = TagSearchStrategy(db, {"OPENROUTER_API_KEY": "x"}, config)
    strat.store.store_embedding(near.claim_id, np.array([1.0, 0.0], dtype=np.float32))
    strat.store.store_embedding(far.claim_id, np.array([0.0, 1.0], dtype=np.float32))
    strat._query_embedding = lambda q: np.array([0.9, 0.1], dtype=np.float32)

    results = strat.search("health", filters=SearchFilters())
    assert [r.claim.claim_id for r in results] == [near.claim_id, far.claim_id]
    assert results[0].score > results[1].score
