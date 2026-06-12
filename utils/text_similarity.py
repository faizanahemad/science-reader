"""
Text similarity utilities for auto-archival superseded detection.

Provides BM25-style token matching (Jaccard) and embedding cosine similarity.
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Optional

import numpy as np

STOPWORDS = frozenset({
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "for", "of", "and",
    "or", "but", "not", "with", "as", "by", "from", "that", "this", "was",
    "are", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "shall",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "they", "them",
    "what", "which", "who", "when", "where", "how", "if", "then", "so",
    "about", "up", "out", "no", "just", "than", "too", "very", "also",
})


def tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alphanumeric, remove stopwords."""
    if not text:
        return []
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return [t for t in tokens if t and t not in STOPWORDS and len(t) > 1]


def jaccard_similarity(tokens_a: List[str], tokens_b: List[str]) -> float:
    """Jaccard index: |intersection| / |union|."""
    if not tokens_a or not tokens_b:
        return 0.0
    set_a, set_b = set(tokens_a), set(tokens_b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def embedding_cosine_similarity(emb_a, emb_b) -> float:
    """Cosine similarity between two embedding vectors. Returns 0.0 on invalid input."""
    if emb_a is None or emb_b is None:
        return 0.0
    a = np.frombuffer(emb_a, dtype=np.float32) if isinstance(emb_a, (bytes, bytearray)) else np.array(emb_a, dtype=np.float32)
    b = np.frombuffer(emb_b, dtype=np.float32) if isinstance(emb_b, (bytes, bytearray)) else np.array(emb_b, dtype=np.float32)
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return 0.0
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def compute_title_summary_hash(title: str, summary: str) -> str:
    """MD5 hash of title + summary[:200] for cache invalidation."""
    text = (title or "") + (summary or "")[:200]
    return hashlib.md5(text.encode("utf-8")).hexdigest()
