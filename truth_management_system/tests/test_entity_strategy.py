"""
Tests for Workstream W-C — entity-linked retrieval strategy.

These run fully offline (no API key): without a query embedding the strategy
degrades to recency ordering, so resolution, status filtering, alias matching,
the top-N cap and the disabled-flag no-op are all exercised here. Cosine
ranking quality requires embeddings and is not covered offline.
"""

import json

import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.crud.claims import ClaimCRUD
from truth_management_system.crud.entities import EntityCRUD
from truth_management_system.crud.links import link_claim_entity
from truth_management_system.constants import ClaimStatus, EntityType
from truth_management_system.models import Claim, Entity
from truth_management_system.search.base import SearchFilters
from truth_management_system.search.entity_search import EntitySearchStrategy


def _env():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return config, db, ClaimCRUD(db), EntityCRUD(db)


def _claim(claims, statement, status="active"):
    c = Claim.create(statement=statement, claim_type="fact", context_domain="personal")
    c.status = status
    return claims.add(c)


def _entity(entities, name, aliases=None):
    meta = json.dumps({"aliases": aliases}) if aliases else None
    e = Entity.create(name=name, entity_type=EntityType.ORG.value, meta_json=meta)
    return entities.add(e)


def test_resolves_entity_by_exact_name():
    config, db, claims, entities = _env()
    acme = _entity(entities, "Acme")
    c = _claim(claims, "Acme shipped a new product line.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    results = strat.search("Tell me about Acme", filters=SearchFilters())

    assert [r.claim.claim_id for r in results] == [c.claim_id]
    assert results[0].source == "entity"
    assert acme.entity_id in results[0].metadata["matched_entities"]


def test_no_entity_match_returns_empty():
    config, db, claims, entities = _env()
    acme = _entity(entities, "Acme")
    c = _claim(claims, "Acme shipped a new product line.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    # lowercase, no capitalized/quoted span resolves to a known entity
    assert strat.search("tell me about the weather", filters=SearchFilters()) == []


def test_status_filter_excludes_non_default_statuses():
    config, db, claims, entities = _env()
    globex = _entity(entities, "Globex")
    active = _claim(claims, "Globex is hiring engineers.", status="active")
    superseded = _claim(
        claims, "Globex headquarters moved.", status=ClaimStatus.SUPERSEDED.value
    )
    link_claim_entity(db, active.claim_id, globex.entity_id, "subject")
    link_claim_entity(db, superseded.claim_id, globex.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    ids = [r.claim.claim_id for r in strat.search("News about Globex", filters=SearchFilters())]
    assert active.claim_id in ids
    assert superseded.claim_id not in ids  # compaction-archived claims stay hidden


def test_alias_match_resolves_variant():
    config, db, claims, entities = _env()
    acme = _entity(entities, "Acme Corporation", aliases=["ACME Inc", "Acme"])
    c = _claim(claims, "Acme Corporation reported earnings.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    # Query uses the alias surface form, not the canonical name.
    results = strat.search('News from "ACME Inc" today', filters=SearchFilters())
    assert [r.claim.claim_id for r in results] == [c.claim_id]


def test_alias_match_disabled():
    config, db, claims, entities = _env()
    config.entity_alias_match = False
    acme = _entity(entities, "Acme Corporation", aliases=["ACME Inc"])
    c = _claim(claims, "Acme Corporation reported earnings.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    # Alias-only query must not resolve when alias matching is off.
    assert strat.search('News from "ACME Inc" today', filters=SearchFilters()) == []


def test_top_n_cap():
    config, db, claims, entities = _env()
    config.entity_strategy_top_n = 3
    acme = _entity(entities, "Acme")
    for i in range(8):
        c = _claim(claims, f"Acme fact number {i}.")
        link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    results = strat.search("Acme", filters=SearchFilters())
    assert len(results) == 3


def test_disabled_flag_is_noop():
    config, db, claims, entities = _env()
    config.entity_strategy_enabled = False
    acme = _entity(entities, "Acme")
    c = _claim(claims, "Acme shipped a product.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    assert strat.search("Acme", filters=SearchFilters()) == []


def test_cosine_ranking_orders_by_similarity():
    """When a query embedding is available, results sort by cosine similarity."""
    import numpy as np

    config, db, claims, entities = _env()
    acme = _entity(entities, "Acme")
    near = _claim(claims, "Acme near match")
    far = _claim(claims, "Acme far match")
    link_claim_entity(db, near.claim_id, acme.entity_id, "subject")
    link_claim_entity(db, far.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {"OPENROUTER_API_KEY": "x"}, config)
    # Cache deterministic embeddings; query vector is closest to `near`.
    strat.store.store_embedding(near.claim_id, np.array([1.0, 0.0], dtype=np.float32))
    strat.store.store_embedding(far.claim_id, np.array([0.0, 1.0], dtype=np.float32))
    strat._query_embedding = lambda q: np.array([0.9, 0.1], dtype=np.float32)

    results = strat.search("Acme", filters=SearchFilters())
    assert [r.claim.claim_id for r in results] == [near.claim_id, far.claim_id]
    assert results[0].score > results[1].score


def test_cold_cache_claims_sort_after_scored():
    """Claims lacking a cached embedding rank after cosine-scored ones."""
    import numpy as np

    config, db, claims, entities = _env()
    acme = _entity(entities, "Acme")
    scored = _claim(claims, "Acme scored claim")
    cold = _claim(claims, "Acme cold claim")
    link_claim_entity(db, scored.claim_id, acme.entity_id, "subject")
    link_claim_entity(db, cold.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {"OPENROUTER_API_KEY": "x"}, config)
    strat.store.store_embedding(scored.claim_id, np.array([1.0, 0.0], dtype=np.float32))
    # `cold` has no cached embedding.
    strat._query_embedding = lambda q: np.array([1.0, 0.0], dtype=np.float32)

    results = strat.search("Acme", filters=SearchFilters())
    assert results[0].claim.claim_id == scored.claim_id
    assert cold.claim_id in [r.claim.claim_id for r in results]
