"""
Unit tests for the claim embedding cache (Workstream A / M1).

These tests are network-free: the embedding functions in
``code_common.call_llm`` are monkeypatched with deterministic stand-ins, so no
real embedding API calls are made. They verify:

1. ``EmbeddingStore.get_embedding`` is model-aware (returns None for vectors
   stored under a different embedding model).
2. ``StructuredAPI.add_claim`` populates the embedding cache on insert.
3. ``LLMHelpers.check_similarity`` reuses supplied cached embeddings instead of
   recomputing each existing claim's vector.
"""

import numpy as np
import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.llm_helpers import LLMHelpers
from truth_management_system.models import Claim


# ---------------------------------------------------------------------------
# Deterministic, network-free embedding stand-ins
# ---------------------------------------------------------------------------

_EMBED_DIM = 64


def _fake_vector(text: str) -> np.ndarray:
    """Deterministic pseudo-embedding derived from the text hash.

    Uses a zero-centered Gaussian in a moderately high dimension so cosine
    similarity between distinct texts stays low (well under the 0.85 threshold
    that would otherwise trigger an LLM contradiction check in
    ``_classify_relation``). This keeps the tests fully network-free.
    """
    seed = abs(hash(text)) % (2**32)
    rng = np.random.default_rng(seed)
    return rng.standard_normal(_EMBED_DIM).astype(np.float32)


@pytest.fixture
def patched_embeddings(monkeypatch):
    """Patch code_common.call_llm embedding fns with counting stand-ins.

    Returns a dict with 'doc_calls' and 'query_calls' lists for assertions.
    """
    import code_common.call_llm as call_llm

    counters = {"doc_calls": [], "query_calls": []}

    def fake_doc(text, keys):
        counters["doc_calls"].append(text)
        return _fake_vector(text)

    def fake_query(text, keys):
        counters["query_calls"].append(text)
        return _fake_vector(text)

    monkeypatch.setattr(call_llm, "get_document_embedding", fake_doc)
    monkeypatch.setattr(call_llm, "get_query_embedding", fake_query)
    return counters


@pytest.fixture
def api():
    """In-memory PKB StructuredAPI with a fake API key present."""
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    keys = {"OPENROUTER_API_KEY": "test-key"}
    return StructuredAPI(db, keys, config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_add_claim_populates_embedding_cache(api, patched_embeddings):
    """add_claim should store an embedding row for the new claim."""
    result = api.add_claim(
        statement="The sky is blue on a clear day",
        claim_type="fact",
        context_domain="personal",
        auto_extract=False,
    )
    assert result.success, result.errors
    cid = result.object_id

    # A cache row exists for the new claim.
    row = api.db.fetchone(
        "SELECT claim_id, model_name FROM claim_embeddings WHERE claim_id = ?",
        (cid,),
    )
    assert row is not None
    assert row["model_name"] == api.config.embedding_model

    # Exactly one document embedding was computed (the compute_and_store call).
    assert len(patched_embeddings["doc_calls"]) == 1


def test_get_embedding_is_model_aware(api, patched_embeddings):
    """Cached vectors from a different model must not be returned."""
    result = api.add_claim(
        statement="I prefer tea over coffee",
        claim_type="preference",
        context_domain="personal",
        auto_extract=False,
    )
    assert result.success, result.errors
    cid = result.object_id

    store = api._get_embedding_store()
    assert store is not None

    # Same model (default) -> hit.
    assert store.get_embedding(cid) is not None
    assert store.get_embedding(cid, expected_model=api.config.embedding_model) is not None

    # Different model -> miss (forces recompute upstream).
    assert store.get_embedding(cid, expected_model="some/other-model") is None


def test_check_similarity_reuses_cached_embeddings(patched_embeddings):
    """check_similarity must not recompute vectors present in the cache map."""
    config = PKBConfig(db_path=":memory:")
    keys = {"OPENROUTER_API_KEY": "test-key"}
    llm = LLMHelpers(keys, config)

    c1 = Claim(claim_id="c1", claim_type="fact", statement="Paris is in France",
               context_domain="learning")
    c2 = Claim(claim_id="c2", claim_type="fact", statement="Rome is in Italy",
               context_domain="learning")
    cached = {"c1": _fake_vector(c1.statement), "c2": _fake_vector(c2.statement)}

    # With a full cache map, no document embeddings should be computed.
    results = llm.check_similarity(
        "Berlin is in Germany", [c1, c2], threshold=-1.0, cached_embeddings=cached
    )
    assert len(patched_embeddings["doc_calls"]) == 0
    assert len(results) == 2  # threshold -1.0 includes all (cosine in [-1, 1])
    # The new claim's (query) embedding is computed once.
    assert len(patched_embeddings["query_calls"]) == 1

    # Without a cache map, it falls back to recomputing each existing claim.
    llm.check_similarity("Berlin is in Germany", [c1, c2], threshold=-1.0)
    assert len(patched_embeddings["doc_calls"]) == 2
