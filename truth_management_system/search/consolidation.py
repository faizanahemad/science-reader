"""
Near-duplicate clustering for consolidation (Workstream D2/D3).

Pure, offline helpers — no LLM and no DB access:
- ``cluster_near_duplicate_claims`` groups claims whose cached embedding
  vectors are within a cosine-similarity threshold (D2).
- ``cluster_entity_variants`` groups same-type entities whose names look like
  variants of one canonical entity (D3), using string similarity plus a
  token-subset rule so "john" clusters with "John Smith".

Both use single-linkage (union-find) clustering and return only clusters of
size >= 2. The caller (StructuredAPI) turns these into merge proposals.
"""

from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

import numpy as np


class _UnionFind:
    """Minimal union-find for single-linkage clustering."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> List[List[int]]:
        out = defaultdict(list)
        for i in range(len(self.parent)):
            out[self.find(i)].append(i)
        return list(out.values())


def _normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def cluster_near_duplicate_claims(
    embeddings: List[Tuple[str, np.ndarray]],
    threshold: float = 0.95,
) -> List[Dict]:
    """
    Cluster claims by cosine similarity of their embedding vectors (D2).

    Args:
        embeddings: list of (claim_id, vector) pairs (e.g. from
            ``EmbeddingStore.get_all_embeddings``).
        threshold: minimum cosine similarity for two claims to be linked.

    Returns:
        List of clusters (size >= 2), each
        ``{"claim_ids": [...], "max_similarity": float}``, sorted by
        descending max similarity.
    """
    n = len(embeddings)
    if n < 2:
        return []

    ids = [cid for cid, _ in embeddings]
    mat = _normalize_rows(np.vstack([v for _, v in embeddings]).astype(np.float32))
    sims = mat @ mat.T  # cosine similarity (rows are unit vectors)

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if float(sims[i, j]) >= threshold:
                uf.union(i, j)

    clusters = []
    for members in uf.groups():
        if len(members) < 2:
            continue
        max_sim = max(
            float(sims[a, b])
            for ai, a in enumerate(members)
            for b in members[ai + 1:]
        )
        clusters.append({
            "claim_ids": [ids[m] for m in members],
            "max_similarity": round(max_sim, 4),
        })

    clusters.sort(key=lambda c: c["max_similarity"], reverse=True)
    return clusters


def _norm_name(s: str) -> str:
    return " ".join((s or "").lower().split())


def entity_name_similarity(a: str, b: str, threshold: float) -> float:
    """
    Similarity score in [0, 1] for two entity names.

    Exact (normalized) match = 1.0. When one name's tokens are a subset of the
    other's (e.g. "john" vs "john smith"), the score is boosted to at least
    ``threshold`` so partial-name variants cluster. Otherwise a character-level
    ``SequenceMatcher`` ratio is used.
    """
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb and (ta <= tb or tb <= ta):
        return max(ratio, threshold)
    return ratio


def cluster_entity_variants(
    entities: List,
    threshold: float = 0.85,
) -> List[Dict]:
    """
    Cluster same-type entities whose names are variants of one another (D3).

    Args:
        entities: list of Entity-like objects exposing ``entity_id`` and
            ``name`` (callers pass entities already grouped by type).
        threshold: minimum name similarity for two entities to be linked.

    Returns:
        List of clusters (size >= 2), each
        ``{"entity_ids": [...], "names": {id: name}, "suggested_keep_id": id,
        "max_similarity": float}``. The suggested keeper is the longest name
        (most complete canonical form), tie-broken alphabetically.
    """
    n = len(entities)
    if n < 2:
        return []

    uf = _UnionFind(n)
    max_pair = {}
    for i in range(n):
        for j in range(i + 1, n):
            s = entity_name_similarity(entities[i].name, entities[j].name, threshold)
            if s >= threshold:
                uf.union(i, j)
                max_pair[(i, j)] = s

    clusters = []
    for members in uf.groups():
        if len(members) < 2:
            continue
        msim = 0.0
        for ai, a in enumerate(members):
            for b in members[ai + 1:]:
                key = (a, b) if a < b else (b, a)
                if key in max_pair:
                    msim = max(msim, max_pair[key])
        members_ents = [entities[m] for m in members]
        keeper = max(members_ents, key=lambda e: (len((e.name or "")), e.name or ""))
        clusters.append({
            "entity_ids": [e.entity_id for e in members_ents],
            "names": {e.entity_id: e.name for e in members_ents},
            "suggested_keep_id": keeper.entity_id,
            "max_similarity": round(msim, 4),
        })

    clusters.sort(key=lambda c: c["max_similarity"], reverse=True)
    return clusters
