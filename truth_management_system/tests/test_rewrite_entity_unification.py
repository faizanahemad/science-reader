"""
Tests for the PKB rewrite/entity unification (design ii).

Covers, fully offline (no API key required):
- config flags (defaults / to_dict / from_dict / env), inert defaults
- RewriteSearchStrategy.search/search_with_metadata reuse precomputed_metadata
  and skip the internal LLM call
- EntitySearchStrategy consumes orchestrator-supplied surface_forms (resolving an
  entity the regex heuristic would miss) and a precomputed query_embedding
  (skipping its own embedding call)
- HybridSearchStrategy makes EXACTLY ONE rewrite LLM call and feeds the entities
  to the entity strategy; the entity claim surfaces in the single top-level RRF
- the coordination is inert when the flag is off or no key is present

The single rewrite call is exercised by monkeypatching ``_rewrite_query`` with a
counter so no network/LLM is needed.
"""

import os
import types

import numpy as np
import pytest

from truth_management_system.config import PKBConfig, load_config
from truth_management_system.database import PKBDatabase
from truth_management_system.crud.claims import ClaimCRUD
from truth_management_system.crud.entities import EntityCRUD
from truth_management_system.crud.links import link_claim_entity
from truth_management_system.constants import EntityType
from truth_management_system.models import Claim, Entity
from truth_management_system.search.base import SearchFilters
from truth_management_system.search.entity_search import EntitySearchStrategy
from truth_management_system.search.rewrite_search import (
    RewriteSearchStrategy,
    RewriteMetadata,
)
from truth_management_system.search.hybrid_search import HybridSearchStrategy


def _env(embedding_enabled=False):
    config = PKBConfig(db_path=":memory:", embedding_enabled=embedding_enabled)
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return config, db, ClaimCRUD(db), EntityCRUD(db)


def _claim(claims, statement, status="active"):
    c = Claim.create(statement=statement, claim_type="fact", context_domain="personal")
    c.status = status
    return claims.add(c)


def _entity(entities, name):
    e = Entity.create(name=name, entity_type=EntityType.ORG.value)
    return entities.add(e)


# --------------------------------------------------------------------------- #
# Config flags
# --------------------------------------------------------------------------- #
def test_unification_flags_default_on_and_roundtrip():
    c = PKBConfig()
    assert c.rewrite_is_query_source is True
    assert c.entity_use_rewrite_entities is True
    d = c.to_dict()
    assert d["rewrite_is_query_source"] is True
    assert d["entity_use_rewrite_entities"] is True
    r = PKBConfig.from_dict(d)
    assert r.rewrite_is_query_source is True
    assert r.entity_use_rewrite_entities is True


def test_unification_flags_env_override(monkeypatch):
    monkeypatch.setenv("PKB_REWRITE_IS_QUERY_SOURCE", "false")
    monkeypatch.setenv("PKB_ENTITY_USE_REWRITE_ENTITIES", "false")
    e = load_config()
    assert e.rewrite_is_query_source is False
    assert e.entity_use_rewrite_entities is False


# --------------------------------------------------------------------------- #
# Rewrite: precomputed_metadata skips the LLM call
# --------------------------------------------------------------------------- #
def test_rewrite_uses_precomputed_metadata_without_llm_call():
    config, db, claims, entities = _env()
    strat = RewriteSearchStrategy(db, {}, config)  # no key => no embedding

    calls = []
    strat._rewrite_query = types.MethodType(
        lambda self, q: (_ for _ in ()).throw(AssertionError("LLM called")), strat
    )

    md = RewriteMetadata(
        original_query="q", rewritten_query="acme", embedding_query="about acme",
        extracted_entities=["Acme"],
    )
    # Must not raise (i.e. _rewrite_query must not be invoked).
    results = strat.search("q", filters=SearchFilters(), precomputed_metadata=md)
    assert isinstance(results, list)

    res2, md2 = strat.search_with_metadata("q", filters=SearchFilters(), precomputed_metadata=md)
    assert md2 is md


# --------------------------------------------------------------------------- #
# Entity: consumes orchestrator-supplied surface_forms + query_embedding
# --------------------------------------------------------------------------- #
def test_entity_consumes_supplied_surface_forms():
    config, db, claims, entities = _env()
    acme = _entity(entities, "Acme")
    c = _claim(claims, "Acme shipped a product.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    # A query with NO capitalized/quoted span: the regex heuristic finds nothing.
    assert strat.search("what did they ship", filters=SearchFilters()) == []
    # But supplied surface forms (from the rewrite LLM) resolve it.
    results = strat.search(
        "what did they ship", filters=SearchFilters(), surface_forms=["acme"]
    )
    assert [r.claim.claim_id for r in results] == [c.claim_id]


def test_entity_empty_surface_forms_is_explicit_noop():
    config, db, claims, entities = _env()
    acme = _entity(entities, "Acme")
    c = _claim(claims, "Acme shipped a product.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    # Explicit empty list (LLM named no entities) => resolve nothing, even though
    # the regex would have found "Acme" in the query text.
    assert strat.search("Acme news", filters=SearchFilters(), surface_forms=[]) == []


def test_entity_reuses_supplied_query_embedding():
    config, db, claims, entities = _env()
    acme = _entity(entities, "Acme")
    c = _claim(claims, "Acme shipped a product.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    strat = EntitySearchStrategy(db, {}, config)
    called = []
    strat._query_embedding = types.MethodType(
        lambda self, q: called.append(q) or np.array([1.0, 0.0]), strat
    )
    results = strat.search(
        "Acme", filters=SearchFilters(), query_embedding=np.array([0.1, 0.2, 0.3])
    )
    # The supplied vector is used; the strategy does NOT compute its own.
    assert called == []
    assert [r.claim.claim_id for r in results] == [c.claim_id]


# --------------------------------------------------------------------------- #
# Hybrid: exactly one rewrite LLM call, entities fed to entity strategy
# --------------------------------------------------------------------------- #
def _patch_single_rewrite(hybrid, entities=("Acme",), fts="acme"):
    calls = []

    def fake_rewrite(self, q):
        calls.append(q)
        md = RewriteMetadata(
            original_query=q, rewritten_query=fts, embedding_query=q,
            extracted_entities=list(entities),
        )
        return fts, md

    hybrid.strategies["rewrite"]._rewrite_query = types.MethodType(
        fake_rewrite, hybrid.strategies["rewrite"]
    )
    return calls


def test_hybrid_makes_single_rewrite_call_and_feeds_entities():
    config, db, claims, entities = _env()  # embedding disabled => offline-safe
    acme = _entity(entities, "Acme")
    c = _claim(claims, "Acme shipped a product.")
    link_claim_entity(db, c.claim_id, acme.entity_id, "subject")

    hybrid = HybridSearchStrategy(db, {"OPENROUTER_API_KEY": "test"}, config)
    calls = _patch_single_rewrite(hybrid, entities=("Acme",), fts="acme")

    results = hybrid.search(
        "what did they ship",
        strategy_names=["fts", "rewrite", "entity"],
        filters=SearchFilters(),
    )

    # Exactly ONE rewrite LLM call total (shared by rewrite + entity).
    assert len(calls) == 1
    # The entity-linked claim surfaced via the LLM entities (regex would miss it).
    assert c.claim_id in [r.claim.claim_id for r in results]


def test_hybrid_inert_when_flag_off():
    config, db, claims, entities = _env()
    hybrid = HybridSearchStrategy(db, {"OPENROUTER_API_KEY": "test"}, config)
    config.rewrite_is_query_source = False
    assert hybrid._build_strategy_context("q", ["fts", "rewrite", "entity"]) is None


def test_hybrid_inert_without_key():
    config, db, claims, entities = _env()
    hybrid = HybridSearchStrategy(db, {}, config)  # no key => rewrite not registered
    assert hybrid._build_strategy_context("q", ["fts", "entity"]) is None


def test_hybrid_context_built_when_enabled():
    config, db, claims, entities = _env()
    hybrid = HybridSearchStrategy(db, {"OPENROUTER_API_KEY": "test"}, config)
    _patch_single_rewrite(hybrid, entities=("Acme",))
    ctx = hybrid._build_strategy_context("q", ["fts", "rewrite", "entity"])
    assert ctx is not None
    assert isinstance(ctx["precomputed_rewrite_metadata"], RewriteMetadata)
    assert ctx["entity_surface_forms"] == ["Acme"]
