"""
LLM Rewrite search strategy for PKB v0.

RewriteSearchStrategy uses a fast LLM to transform natural language queries
into optimized search terms, then runs BOTH FTS and embedding search on the
rewritten queries. Optionally informed by the PKB overview (Key Areas) to
produce domain-aware expansions.

This is "S4" in the plan - good for vague queries that need interpretation.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from .base import SearchStrategy, SearchFilters, SearchResult, merge_results_rrf
from .fts_search import FTSSearchStrategy
from ..database import PKBDatabase
from ..config import PKBConfig

logger = logging.getLogger(__name__)


@dataclass
class RewriteMetadata:
    """
    Metadata about query rewriting.

    Attributes:
        original_query: The user's original query.
        rewritten_query: The transformed FTS query.
        embedding_query: The natural-language query for embedding search.
        extracted_keywords: Keywords extracted by LLM.
        extracted_tags: Suggested tags from LLM.
        extracted_entities: Entities identified in query.
        llm_model: Model used for rewriting.
    """
    original_query: str
    rewritten_query: str
    embedding_query: str = ""
    extracted_keywords: List[str] = field(default_factory=list)
    extracted_tags: List[str] = field(default_factory=list)
    extracted_entities: List[str] = field(default_factory=list)
    llm_model: str = ""


class RewriteSearchStrategy(SearchStrategy):
    """
    LLM rewrites query into optimized FTS keywords + embedding query,
    then runs both and merges via RRF.

    Optionally uses PKB overview Key Areas to inform domain-aware expansion.

    Attributes:
        db: PKBDatabase instance.
        keys: API keys for LLM calls.
        config: PKBConfig with settings.
        fts: FTSSearchStrategy for keyword search.
        overview_context: Optional Key Areas snippet for domain awareness.
    """

    def __init__(
        self,
        db: PKBDatabase,
        keys: Dict[str, str],
        config: PKBConfig,
        overview_context: str = None,
    ):
        self.db = db
        self.keys = keys
        self.config = config
        self.fts = FTSSearchStrategy(db)
        self.overview_context = overview_context or ""
        self._embedding = None
        if config.embedding_enabled and keys.get("OPENROUTER_API_KEY"):
            try:
                from .embedding_search import EmbeddingSearchStrategy
                self._embedding = EmbeddingSearchStrategy(db, keys, config)
            except Exception:
                pass

    def set_overview_context(self, overview_context: str):
        """Update overview context (called per-request if available)."""
        self.overview_context = overview_context or ""

    def name(self) -> str:
        return "rewrite"

    def search(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None,
    ) -> List[SearchResult]:
        """
        Rewrite query using LLM, then execute both FTS and embedding search,
        merge results via RRF.
        """
        filters = filters or SearchFilters()

        rewritten, metadata = self._rewrite_query(query)

        if not rewritten:
            logger.warning(f"Rewrite failed for query: {query}")
            rewritten = query

        # FTS with rewritten keywords
        fts_results = self.fts.search(rewritten, k, filters)
        for r in fts_results:
            r.source = "rewrite_fts"

        # Embedding with the natural-language embedding_query
        embedding_results = []
        embedding_query = metadata.embedding_query or query
        if self._embedding:
            try:
                embedding_results = self._embedding.search(embedding_query, k, filters)
                for r in embedding_results:
                    r.source = "rewrite_embedding"
            except Exception as e:
                logger.warning(f"Rewrite embedding search failed: {e}")

        # Merge via RRF
        if embedding_results:
            merged = merge_results_rrf([fts_results, embedding_results], k=k)
        else:
            merged = fts_results[:k]

        # Tag with rewrite metadata
        for result in merged:
            result.source = self.name()
            result.metadata["rewrite"] = {
                "original": metadata.original_query,
                "rewritten_fts": metadata.rewritten_query,
                "embedding_query": metadata.embedding_query,
                "keywords": metadata.extracted_keywords,
            }

        logger.debug(
            f"Rewrite search '{query}' -> fts='{rewritten}' emb='{embedding_query}' returned {len(merged)} results"
        )
        return merged

    def search_with_metadata(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None,
    ) -> Tuple[List[SearchResult], RewriteMetadata]:
        """Execute rewrite search and return full metadata."""
        filters = filters or SearchFilters()

        rewritten, metadata = self._rewrite_query(query)

        if not rewritten:
            rewritten = query

        # FTS with rewritten keywords
        fts_results = self.fts.search(rewritten, k, filters)
        for r in fts_results:
            r.source = "rewrite_fts"

        # Embedding with the natural-language embedding_query
        embedding_results = []
        embedding_query = metadata.embedding_query or query
        if self._embedding:
            try:
                embedding_results = self._embedding.search(embedding_query, k, filters)
                for r in embedding_results:
                    r.source = "rewrite_embedding"
            except Exception as e:
                logger.warning(f"Rewrite embedding search failed: {e}")

        if embedding_results:
            merged = merge_results_rrf([fts_results, embedding_results], k=k)
        else:
            merged = fts_results[:k]

        for result in merged:
            result.source = self.name()

        return merged, metadata

    def _rewrite_query(self, query: str) -> Tuple[str, RewriteMetadata]:
        """
        Use SUPERFAST_LLM to rewrite query into FTS keywords + embedding query.
        If overview_context is available, includes it for domain-aware expansion.
        """
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            logger.error("code_common.call_llm not available")
            return query, RewriteMetadata(original_query=query, rewritten_query=query, embedding_query=query)

        # Use SUPERFAST_LLM for low latency
        try:
            from common import SUPERFAST_LLM
            model = SUPERFAST_LLM[0]
        except ImportError:
            model = self.config.llm_model

        overview_block = ""
        if self.overview_context:
            overview_block = f"""
The user's knowledge base covers these domains:
{self.overview_context}

Use this to expand the query with domain-relevant terms the user likely cares about.
"""

        prompt = f"""Rewrite this search query into optimized search terms for a personal knowledge base.
{overview_block}
The knowledge base contains personal facts, preferences, decisions, memories, tasks, and reminders.

Produce:
1. "fts_query": space-separated keywords for full-text search (OR-joined, 3-6 terms)
2. "embedding_query": a natural-language sentence that captures the semantic intent (for vector similarity)
3. "keywords": array of individual keyword terms
4. "tags": relevant category tags (e.g., health, work, family)
5. "entities": specific people, places, or things mentioned

Return ONLY JSON:
{{"fts_query": "...", "embedding_query": "...", "keywords": [...], "tags": [...], "entities": [...]}}

Query: {query}

JSON:"""

        try:
            response = call_llm(self.keys, model, prompt, temperature=0.0)

            # Strip markdown fences
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            parsed = json.loads(text)

            keywords = parsed.get("keywords", [])
            tags = parsed.get("tags", [])
            entities = parsed.get("entities", [])
            fts_query = parsed.get("fts_query", " OR ".join(keywords)) or " OR ".join(keywords)
            embedding_query = parsed.get("embedding_query", query) or query

            metadata = RewriteMetadata(
                original_query=query,
                rewritten_query=fts_query,
                embedding_query=embedding_query,
                extracted_keywords=keywords,
                extracted_tags=tags,
                extracted_entities=entities,
                llm_model=model,
            )

            if self.config.log_llm_calls:
                logger.info(f"Query rewrite: '{query}' -> fts='{fts_query}' emb='{embedding_query}'")

            return fts_query, metadata

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM rewrite response: {e}")
            return query, RewriteMetadata(original_query=query, rewritten_query=query, embedding_query=query)
        except Exception as e:
            logger.error(f"Query rewrite failed: {e}")
            return query, RewriteMetadata(original_query=query, rewritten_query=query, embedding_query=query)

    def expand_query(self, query: str) -> List[str]:
        """Get query expansion suggestions (keywords only)."""
        _, metadata = self._rewrite_query(query)
        return metadata.extracted_keywords
