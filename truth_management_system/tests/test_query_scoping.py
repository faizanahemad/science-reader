"""
Tests for Workstream W-B — per-strategy query scoping.

HybridSearchStrategy.search accepts an optional ``strategy_queries`` map so the
focused current message can be routed to literal FTS while the contextual
(summary-laden) query stays with embedding/rewrite. Passing ``None`` (the
default) must route the single ``query`` to every strategy unchanged.
"""

from typing import List

from truth_management_system.config import PKBConfig
from truth_management_system.database import PKBDatabase
from truth_management_system.search.base import (
    SearchStrategy,
    SearchFilters,
    SearchResult,
)
from truth_management_system.search.hybrid_search import HybridSearchStrategy


class _RecordingStrategy(SearchStrategy):
    """Stub strategy that records the query it was handed."""

    def __init__(self, source: str):
        self._source = source
        self.seen_query = None

    def search(self, query: str, k: int = 20, filters: SearchFilters = None) -> List[SearchResult]:
        self.seen_query = query
        return []

    def name(self) -> str:
        return self._source


def _hybrid_with_stubs():
    config = PKBConfig(db_path=":memory:")
    db = PKBDatabase(config)
    hybrid = HybridSearchStrategy(db, {}, config)
    fts, emb = _RecordingStrategy("fts"), _RecordingStrategy("embedding")
    hybrid.strategies = {"fts": fts, "embedding": emb}
    return hybrid, fts, emb


def test_strategy_queries_routes_focused_to_fts():
    hybrid, fts, emb = _hybrid_with_stubs()
    hybrid.search(
        "CONTEXTUAL SUMMARY QUERY",
        strategy_names=["fts", "embedding"],
        strategy_queries={"fts": "FOCUSED MESSAGE"},
    )
    assert fts.seen_query == "FOCUSED MESSAGE"
    assert emb.seen_query == "CONTEXTUAL SUMMARY QUERY"  # unlisted -> base query


def test_none_routes_single_query_everywhere():
    hybrid, fts, emb = _hybrid_with_stubs()
    hybrid.search(
        "ONE QUERY",
        strategy_names=["fts", "embedding"],
        strategy_queries=None,
    )
    assert fts.seen_query == "ONE QUERY"
    assert emb.seen_query == "ONE QUERY"


def test_single_strategy_branch_honors_override():
    """The len==1 fast path must also apply strategy_queries."""
    hybrid, fts, _ = _hybrid_with_stubs()
    hybrid.search(
        "CONTEXTUAL",
        strategy_names=["fts"],
        strategy_queries={"fts": "FOCUSED"},
    )
    assert fts.seen_query == "FOCUSED"
