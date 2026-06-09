"""
Workstream B — vector index for embedding-search acceleration.

The default embedding search does a linear cosine scan in Python over every
candidate claim's vector. This module replaces that hot loop with a vector
index that supports two pluggable backends:

- ``flat`` (default): a single vectorized BLAS matmul over a normalized matrix
  of all the user's embeddings. Exact — it returns the *same* ranking as the
  linear cosine scan — but moves the O(N·d) work out of the Python interpreter,
  so it scales to tens of thousands of claims with millisecond latency and needs
  no third-party dependency.
- ``hnsw`` (optional): a faiss HNSW graph for approximate, sub-linear search at
  very large corpora. Used only when ``ann_backend="hnsw"`` and faiss is
  importable; otherwise it transparently falls back to ``flat``.

Indexes are built lazily from the A1 embedding cache (``claim_embeddings``),
cached per-user in this process, and rebuilt when a cheap **staleness
signature** (embedding row count + latest ``created_at``) changes — covering
add/edit/delete without an explicit maintenance hook. The caller (the embedding
search strategy) keeps the exhaustive linear scan as a correctness fallback.
"""

import logging
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

from .base import SearchFilters

logger = logging.getLogger(__name__)

try:  # faiss is optional — only needed for the approximate HNSW backend.
    import faiss  # type: ignore

    _FAISS_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
    _FAISS_AVAILABLE = False


def faiss_available() -> bool:
    """True if the optional faiss HNSW backend can be used."""
    return _FAISS_AVAILABLE


class VectorIndex:
    """
    An in-memory similarity index over a set of (claim_id, embedding) pairs.

    Cosine similarity is realized as an inner product over L2-normalized
    vectors. ``backend`` selects ``flat`` (numpy, exact) or ``hnsw`` (faiss,
    approximate); an ``hnsw`` request silently degrades to ``flat`` when faiss
    is unavailable.
    """

    def __init__(self, backend: str = "flat"):
        self.backend = "hnsw" if (backend == "hnsw" and _FAISS_AVAILABLE) else "flat"
        self.claim_ids: List[str] = []
        self.dim: Optional[int] = None
        self._matrix: Optional[np.ndarray] = None  # flat backend
        self._faiss = None  # hnsw backend

    @staticmethod
    def _normalize(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def build(self, items: List[Tuple[str, np.ndarray]]) -> "VectorIndex":
        """Build the index from (claim_id, vector) pairs."""
        self.claim_ids = [cid for cid, _ in items]
        self._matrix = None
        self._faiss = None
        if not items:
            return self

        matrix = np.vstack([v.astype(np.float32) for _, v in items])
        self.dim = matrix.shape[1]
        matrix = self._normalize(matrix)

        if self.backend == "hnsw":
            try:
                index = faiss.IndexHNSWFlat(self.dim, 32, faiss.METRIC_INNER_PRODUCT)
                index.hnsw.efConstruction = 80
                index.hnsw.efSearch = 64
                index.add(matrix)
                self._faiss = index
                return self
            except Exception as e:  # pragma: no cover - faiss runtime issue
                logger.warning(f"faiss HNSW build failed, using flat backend: {e}")
                self.backend = "flat"

        self._matrix = matrix
        return self

    def search(self, query: np.ndarray, k: int) -> List[Tuple[str, float]]:
        """
        Return up to ``k`` (claim_id, cosine_score) pairs, highest score first.
        """
        n = len(self.claim_ids)
        if n == 0:
            return []

        q = np.asarray(query, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        q = q / qn
        k = min(k, n)

        if self.backend == "hnsw" and self._faiss is not None:
            distances, indices = self._faiss.search(q.reshape(1, -1), k)
            return [
                (self.claim_ids[i], float(d))
                for d, i in zip(distances[0], indices[0])
                if i >= 0
            ]

        # flat (exact) backend: one matmul + partial sort.
        scores = self._matrix @ q  # (N,)
        if k < n:
            top = np.argpartition(-scores, k - 1)[:k]
        else:
            top = np.arange(n)
        top = top[np.argsort(-scores[top])]
        return [(self.claim_ids[i], float(scores[i])) for i in top]

    def size(self) -> int:
        return len(self.claim_ids)


# --------------------------------------------------------------------------- #
# Per-user process cache with staleness signature
# --------------------------------------------------------------------------- #
_INDEX_CACHE: Dict[tuple, tuple] = {}  # key -> (signature, VectorIndex)
_CACHE_LOCK = threading.Lock()


def _signature(db, user_email: Optional[str]) -> tuple:
    """
    Cheap staleness fingerprint of a user's cached embeddings: (count, latest
    created_at). Any add/edit (re-embed bumps created_at) / delete changes it.
    """
    sql = (
        "SELECT COUNT(*) AS c, MAX(ce.created_at) AS m "
        "FROM claim_embeddings ce JOIN claims c ON ce.claim_id = c.claim_id"
    )
    params: List = []
    if user_email:
        sql += " WHERE c.user_email = ?"
        params.append(user_email)
    row = db.fetchone(sql, tuple(params))
    if not row:
        return (0, None)
    return (row["c"], row["m"])


def get_index(db, store, user_email: Optional[str], backend: str = "flat") -> VectorIndex:
    """
    Return a current ``VectorIndex`` for ``user_email``, building or rebuilding
    it from the embedding cache when the staleness signature changes.
    """
    key = (id(db), user_email or "")
    sig = _signature(db, user_email)

    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None and cached[0] == sig and cached[1].backend == (
            "hnsw" if (backend == "hnsw" and _FAISS_AVAILABLE) else "flat"
        ):
            return cached[1]

    # Build outside the lock (embedding fetch + matrix build can be heavy).
    items = store.get_all_embeddings(
        SearchFilters(user_email=user_email, statuses=[])
    )
    index = VectorIndex(backend=backend).build(items)

    with _CACHE_LOCK:
        _INDEX_CACHE[key] = (sig, index)
    return index


def invalidate(db=None, user_email: Optional[str] = None) -> None:
    """Drop cached indexes (all, per-db, or per-user). Mainly for tests."""
    with _CACHE_LOCK:
        if db is None:
            _INDEX_CACHE.clear()
        elif user_email is None:
            for key in [k for k in _INDEX_CACHE if k[0] == id(db)]:
                _INDEX_CACHE.pop(key, None)
        else:
            _INDEX_CACHE.pop((id(db), user_email or ""), None)
