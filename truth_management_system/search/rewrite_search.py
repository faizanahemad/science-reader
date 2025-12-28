"""
LLM Rewrite → FTS search strategy for PKB v0.

RewriteSearchStrategy uses an LLM to transform natural language queries
into optimized search keywords, then runs FTS search on the result.

This is "S4" in the plan - good for vague queries that need interpretation.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from .base import SearchStrategy, SearchFilters, SearchResult
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
        extracted_keywords: Keywords extracted by LLM.
        extracted_tags: Suggested tags from LLM.
        extracted_entities: Entities identified in query.
        llm_model: Model used for rewriting.
    """
    original_query: str
    rewritten_query: str
    extracted_keywords: List[str] = field(default_factory=list)
    extracted_tags: List[str] = field(default_factory=list)
    extracted_entities: List[str] = field(default_factory=list)
    llm_model: str = ""


class RewriteSearchStrategy(SearchStrategy):
    """
    LLM rewrites query into keywords/tags, then runs FTS.
    
    Good for:
    - Vague or conversational queries
    - Queries that need semantic interpretation
    - Expanding query terms with synonyms
    
    Attributes:
        db: PKBDatabase instance.
        keys: API keys for LLM calls.
        config: PKBConfig with settings.
        fts: FTSSearchStrategy for actual search.
    """
    
    def __init__(
        self,
        db: PKBDatabase,
        keys: Dict[str, str],
        config: PKBConfig
    ):
        """
        Initialize rewrite search strategy.
        
        Args:
            db: PKBDatabase instance.
            keys: Dict with OPENROUTER_API_KEY.
            config: PKBConfig with settings.
        """
        self.db = db
        self.keys = keys
        self.config = config
        self.fts = FTSSearchStrategy(db)
    
    def name(self) -> str:
        return "rewrite"
    
    def search(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Rewrite query using LLM, then execute FTS search.
        
        Args:
            query: Natural language search query.
            k: Number of results to return.
            filters: Optional filters to apply.
            
        Returns:
            List of SearchResult objects with rewrite metadata.
        """
        filters = filters or SearchFilters()
        
        # Rewrite query
        rewritten, metadata = self._rewrite_query(query)
        
        if not rewritten:
            logger.warning(f"Rewrite failed for query: {query}")
            # Fall back to original query
            rewritten = query
        
        # Execute FTS with rewritten query
        results = self.fts.search(rewritten, k, filters)
        
        # Add rewrite metadata to results
        for result in results:
            result.source = self.name()
            result.metadata['rewrite'] = {
                'original': metadata.original_query,
                'rewritten': metadata.rewritten_query,
                'keywords': metadata.extracted_keywords
            }
        
        logger.debug(f"Rewrite search '{query}' -> '{rewritten}' returned {len(results)} results")
        return results
    
    def search_with_metadata(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> Tuple[List[SearchResult], RewriteMetadata]:
        """
        Execute rewrite search and return full metadata.
        
        Args:
            query: Natural language search query.
            k: Number of results to return.
            filters: Optional filters.
            
        Returns:
            Tuple of (results, metadata).
        """
        filters = filters or SearchFilters()
        
        rewritten, metadata = self._rewrite_query(query)
        
        if not rewritten:
            rewritten = query
        
        results = self.fts.search(rewritten, k, filters)
        
        for result in results:
            result.source = self.name()
        
        return results, metadata
    
    def _rewrite_query(self, query: str) -> Tuple[str, RewriteMetadata]:
        """
        Use LLM to rewrite query into search keywords.
        
        Args:
            query: Original natural language query.
            
        Returns:
            Tuple of (rewritten_query, metadata).
        """
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            logger.error("code_common.call_llm not available")
            return query, RewriteMetadata(
                original_query=query,
                rewritten_query=query
            )
        
        prompt = f"""Rewrite this search query into optimized keywords for a personal knowledge base.

The knowledge base contains personal facts, preferences, decisions, memories, tasks, and reminders.

Extract:
1. keywords: 1-3 word search terms (most important)
2. tags: relevant category tags (e.g., health, work, family)
3. entities: specific people, places, or things mentioned

Return JSON only:
{{"keywords": ["keyword1", "keyword2", ...], "tags": ["tag1", "tag2", ...], "entities": ["entity1", ...], "fts_query": "optimized search string"}}

Query: {query}

JSON:"""

        try:
            response = call_llm(
                self.keys,
                self.config.llm_model,
                prompt,
                temperature=self.config.llm_temperature
            )
            
            # Parse JSON response
            parsed = json.loads(response.strip())
            
            keywords = parsed.get('keywords', [])
            tags = parsed.get('tags', [])
            entities = parsed.get('entities', [])
            fts_query = parsed.get('fts_query', ' OR '.join(keywords))
            
            # Build rewritten query
            if not fts_query and keywords:
                fts_query = ' OR '.join(keywords)
            
            metadata = RewriteMetadata(
                original_query=query,
                rewritten_query=fts_query,
                extracted_keywords=keywords,
                extracted_tags=tags,
                extracted_entities=entities,
                llm_model=self.config.llm_model
            )
            
            # Log rewrite for debugging
            if self.config.log_llm_calls:
                logger.info(f"Query rewrite: '{query}' -> '{fts_query}'")
                logger.debug(f"Keywords: {keywords}, Tags: {tags}, Entities: {entities}")
            
            return fts_query, metadata
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return query, RewriteMetadata(
                original_query=query,
                rewritten_query=query
            )
        except Exception as e:
            logger.error(f"Query rewrite failed: {e}")
            return query, RewriteMetadata(
                original_query=query,
                rewritten_query=query
            )
    
    def expand_query(self, query: str) -> List[str]:
        """
        Get query expansion suggestions (keywords only).
        
        Args:
            query: Original query.
            
        Returns:
            List of expanded keyword terms.
        """
        _, metadata = self._rewrite_query(query)
        return metadata.extracted_keywords
