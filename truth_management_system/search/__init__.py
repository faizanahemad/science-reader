"""
Search strategies for PKB v0.

This module provides multiple search strategies for finding claims:
- FTSSearchStrategy: BM25 ranking via SQLite FTS5
- EmbeddingSearchStrategy: Cosine similarity over embeddings
- RewriteSearchStrategy: LLM rewrites query → FTS
- MapReduceSearchStrategy: LLM scores/ranks candidates
- HybridSearchStrategy: Combines multiple strategies with RRF

All strategies implement the SearchStrategy ABC and return
SearchResult objects with scores and metadata.

Usage:
    from truth_management_system.search import HybridSearchStrategy, SearchFilters
    
    search = HybridSearchStrategy(db, keys, config)
    results = search.search("what are my workout preferences?", k=10)
"""

from .base import (
    SearchStrategy,
    SearchFilters,
    SearchResult,
    merge_results_rrf,
    dedupe_results,
)
from .fts_search import FTSSearchStrategy
from .embedding_search import EmbeddingSearchStrategy, EmbeddingStore
from .rewrite_search import RewriteSearchStrategy
from .mapreduce_search import MapReduceSearchStrategy
from .hybrid_search import HybridSearchStrategy
from .notes_search import NotesSearchStrategy

__all__ = [
    'SearchStrategy',
    'SearchFilters',
    'SearchResult',
    'merge_results_rrf',
    'dedupe_results',
    'FTSSearchStrategy',
    'EmbeddingSearchStrategy',
    'EmbeddingStore',
    'RewriteSearchStrategy',
    'MapReduceSearchStrategy',
    'HybridSearchStrategy',
    'NotesSearchStrategy',
]
