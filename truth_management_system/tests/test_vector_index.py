"""
Tests for Workstream B — the embedding-search vector index.

Covers VectorIndex correctness (flat backend == exact brute force), top-k edge
cases, the per-user index cache + staleness rebuild, and the filter-preserving
claim loader on the ANN fast path. All offline (synthetic vectors; no network).
"""

import numpy as np
import pytest

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.interface.structured_api import StructuredAPI
from truth_management_system.search.embedding_search import (
    EmbeddingStore,
    EmbeddingSearchStrategy,
)
from truth_management_system.search.base import SearchFilters
from truth_management_system.search import ann_vector_index as avi


def _brute_topk(query, items, k):
    q = query / (np.linalg.norm(query) or 1.0)
    scored = []
    for cid, v in items:
        nv = np.linalg.norm(v)
        scored.append((cid, float(np.dot(q, v) / nv) if nv else 0.0))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in scored[:k]]


def _items(n, dim=64, seed=1):
    rng = np.random.default_rng(seed)
    mat = rng.standard_normal((n, dim)).astype(np.float32)
    return [(f"c{i}", mat[i]) for i in range(n)]


# --------------------------------------------------------------------------- #
# VectorIndex correctness
# --------------------------------------------------------------------------- #
def test_flat_matches_brute_force():
    items = _items(200)
    index = avi.VectorIndex(backend="flat").build(items)
    rng = np.random.default_rng(99)
    for _ in range(5):
        q = rng.standard_normal(64).astype(np.float32)
        got = [cid for cid, _ in index.search(q, 10)]
        assert got == _brute_topk(q, items, 10)


def test_scores_descending_and_cosine_range():
    items = _items(50)
    index = avi.VectorIndex(backend="flat").build(items)
    q = items[3][1]  # query equals a stored vector -> it should rank first
    hits = index.search(q, 5)
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)
    assert hits[0][0] == "c3"
    assert scores[0] == pytest.approx(1.0, abs=1e-4)


def test_k_larger_than_n_and_empty():
    index = avi.VectorIndex(backend="flat").build(_items(3))
    assert len(index.search(np.ones(64, dtype=np.float32), 10)) == 3
    empty = avi.VectorIndex(backend="flat").build([])
    assert empty.search(np.ones(64, dtype=np.float32), 5) == []
    assert empty.size() == 0


def test_zero_query_returns_empty():
    index = avi.VectorIndex(backend="flat").build(_items(10))
    assert index.search(np.zeros(64, dtype=np.float32), 5) == []


@pytest.mark.skipif(not avi.faiss_available(), reason="faiss not installed")
def test_hnsw_backend_builds_and_searches():
    items = _items(500)
    index = avi.VectorIndex(backend="hnsw").build(items)
    assert index.backend == "hnsw"
    hits = index.search(items[0][1], 10)
    assert len(hits) == 10
    # The query vector itself should be among the near neighbors.
    assert "c0" in [cid for cid, _ in hits]


def test_hnsw_request_falls_back_to_flat_without_faiss(monkeypatch):
    monkeypatch.setattr(avi, "_FAISS_AVAILABLE", False)
    index = avi.VectorIndex(backend="hnsw")
    assert index.backend == "flat"


# --------------------------------------------------------------------------- #
# Per-user cache + staleness
# --------------------------------------------------------------------------- #
def _api(email="b@example.com"):
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    db.connect()
    db.initialize_schema()
    return StructuredAPI(db, {}, config, user_email=email)


def _seed_claim_with_embedding(api, store, statement, vec):
    r = api.add_claim(statement, "fact", "personal", auto_extract=False)
    store.store_embedding(r.object_id, np.asarray(vec, dtype=np.float32))
    return r.object_id


def test_get_index_caches_and_rebuilds_on_change():
    api = _api()
    store = EmbeddingStore(api.db, {}, api.config)
    avi.invalidate(api.db)
    _seed_claim_with_embedding(api, store, "one", [1, 0, 0])
    _seed_claim_with_embedding(api, store, "two", [0, 1, 0])

    idx1 = avi.get_index(api.db, store, api.user_email, "flat")
    idx2 = avi.get_index(api.db, store, api.user_email, "flat")
    assert idx1 is idx2  # cached (signature unchanged)
    assert idx1.size() == 2

    # Add another embedding -> signature changes -> rebuilt with new size.
    _seed_claim_with_embedding(api, store, "three", [0, 0, 1])
    idx3 = avi.get_index(api.db, store, api.user_email, "flat")
    assert idx3 is not idx1
    assert idx3.size() == 3


def test_index_is_user_scoped():
    api_a = _api("a@example.com")
    store_a = EmbeddingStore(api_a.db, {}, api_a.config)
    # Same shared DB, second user.
    api_b = StructuredAPI(api_a.db, {}, api_a.config, user_email="other@example.com")
    avi.invalidate(api_a.db)
    _seed_claim_with_embedding(api_a, store_a, "a-claim", [1, 0, 0])
    _seed_claim_with_embedding(api_b, store_a, "b-claim", [0, 1, 0])

    idx_a = avi.get_index(api_a.db, store_a, "a@example.com", "flat")
    idx_b = avi.get_index(api_a.db, store_a, "other@example.com", "flat")
    assert idx_a.size() == 1
    assert idx_b.size() == 1


# --------------------------------------------------------------------------- #
# Filter-preserving claim load on the ANN fast path
# --------------------------------------------------------------------------- #
def test_load_claims_by_ids_respects_filters():
    api = _api()
    store = EmbeddingStore(api.db, {}, api.config)
    active = _seed_claim_with_embedding(api, store, "active claim", [1, 0, 0])
    retired = _seed_claim_with_embedding(api, store, "retired claim", [0, 1, 0])
    api.delete_claim(retired)  # -> retracted, excluded by default statuses

    strat = EmbeddingSearchStrategy(api.db, {}, api.config)
    loaded = strat._load_claims_by_ids(
        [active, retired], SearchFilters(user_email=api.user_email)
    )
    assert active in loaded
    assert retired not in loaded  # filtered out by default status filter


def test_ann_search_returns_none_below_min_claims():
    # Default ann_min_claims (200) >> seeded count -> fast path declines,
    # signalling the caller to use the exact linear scan.
    api = _api()
    store = EmbeddingStore(api.db, {}, api.config)
    avi.invalidate(api.db)
    _seed_claim_with_embedding(api, store, "only claim", [1, 0, 0])
    strat = EmbeddingSearchStrategy(api.db, {}, api.config)
    out = strat._ann_search(
        np.array([1, 0, 0], dtype=np.float32), 5,
        SearchFilters(user_email=api.user_email),
    )
    assert out is None


def test_ann_search_engages_above_threshold():
    api = _api()
    store = EmbeddingStore(api.db, {}, api.config)
    avi.invalidate(api.db)
    api.config.ann_min_claims = 3  # lower threshold so the fast path engages
    rng = np.random.default_rng(5)
    target = None
    for i in range(6):
        vec = rng.standard_normal(8).astype(np.float32)
        cid = _seed_claim_with_embedding(api, store, f"claim {i}", vec)
        if i == 2:
            target, target_vec = cid, vec
    strat = EmbeddingSearchStrategy(api.db, {}, api.config)
    out = strat._ann_search(target_vec, 3, SearchFilters(user_email=api.user_email))
    assert out is not None
    # Querying with a stored vector should rank that claim first.
    assert out[0].claim.claim_id == target
