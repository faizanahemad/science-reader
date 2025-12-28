"""
FTS/BM25 search strategy for PKB v0.

FTSSearchStrategy provides full-text search using SQLite FTS5:
- BM25 ranking for relevance
- Fast, deterministic baseline search
- Supports all standard filters
"""

import logging
import re
from typing import List, Optional

from .base import SearchStrategy, SearchFilters, SearchResult
from ..database import PKBDatabase
from ..models import Claim
from ..constants import ClaimStatus

logger = logging.getLogger(__name__)

# Import time_logger for guaranteed visibility
try:
    from common import time_logger
except ImportError:
    # Fallback to regular logger if time_logger not available
    time_logger = logger


class FTSSearchStrategy(SearchStrategy):
    """
    BM25 ranking via SQLite FTS5.
    
    This is the default, fast, deterministic search strategy.
    Uses FTS5's built-in BM25 function for relevance ranking.
    
    Attributes:
        db: PKBDatabase instance.
    """
    
    def __init__(self, db: PKBDatabase):
        """
        Initialize FTS search strategy.
        
        Args:
            db: PKBDatabase instance.
        """
        self.db = db
    
    def name(self) -> str:
        return "fts"
    
    def search(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Execute FTS5 search with BM25 ranking.
        
        Args:
            query: Search query string.
            k: Number of results to return.
            filters: Optional filters to apply.
            
        Returns:
            List of SearchResult objects, ordered by BM25 score.
        """
        filters = filters or SearchFilters()
        
        # Sanitize query for FTS5
        fts_query = self._sanitize_query(query)
        time_logger.info(f"[FTS] Original query: '{query[:100]}...', sanitized: '{fts_query[:100]}...'")
        if not fts_query:
            time_logger.warning(f"[FTS] Empty FTS query after sanitization: {query}")
            return []
        
        # Build SQL with filters
        conditions, params = filters.to_sql_conditions()
        time_logger.info(f"[FTS] Filters: user_email={filters.user_email}, conditions={conditions}, params_len={len(params)}")
        
        # Note: bm25() returns negative values (more negative = better match)
        # We negate it so higher scores = better matches
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        sql = f"""
            SELECT c.*, -bm25(claims_fts) as score
            FROM claims_fts
            JOIN claims c ON claims_fts.claim_id = c.claim_id
            WHERE claims_fts MATCH ?
              AND {where_clause}
            ORDER BY score DESC
            LIMIT ?
        """
        
        try:
            time_logger.info(f"[FTS] Executing SQL with fts_query='{fts_query}', k={k}")
            rows = self.db.fetchall(sql, (fts_query,) + tuple(params) + (k,))
            time_logger.info(f"[FTS] Query returned {len(rows)} rows")
            
            results = []
            for row in rows:
                claim = Claim.from_row(row)
                result = SearchResult.from_claim(
                    claim=claim,
                    score=row['score'],
                    source=self.name(),
                    metadata={'fts_query': fts_query}
                )
                results.append(result)
            
            time_logger.info(f"[FTS] Search '{query[:50]}...' returned {len(results)} results")
            return results
            
        except Exception as e:
            time_logger.error(f"[FTS] Search failed: {e}", exc_info=True)
            return []
    
    def _sanitize_query(self, query: str) -> str:
        """
        Sanitize query for FTS5 syntax.
        
        Removes special characters that could cause syntax errors
        and handles multi-word queries appropriately.
        
        Args:
            query: Raw query string.
            
        Returns:
            Sanitized FTS5 query string.
        """
        # Remove FTS5 operators that might cause issues
        # Keep alphanumeric, spaces, and basic punctuation
        sanitized = re.sub(r'[^\w\s\-]', ' ', query)
        
        # Collapse multiple spaces
        sanitized = ' '.join(sanitized.split())
        
        if not sanitized:
            return ""
        
        # Split into words and create OR query for flexibility
        words = sanitized.split()
        
        if len(words) == 1:
            # Single word: use prefix matching
            return f"{words[0]}*"
        
        # Multiple words: combine with OR for broader matching
        # Also add the full phrase for exact matching boost
        terms = [f'"{sanitized}"']  # Exact phrase
        terms.extend([f"{w}*" for w in words])  # Prefix match each word
        
        return " OR ".join(terms)
    
    def search_exact_phrase(
        self,
        phrase: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Search for exact phrase match.
        
        Args:
            phrase: Exact phrase to search for.
            k: Number of results.
            filters: Optional filters.
            
        Returns:
            List of SearchResults with exact phrase matches.
        """
        filters = filters or SearchFilters()
        conditions, params = filters.to_sql_conditions()
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Quote the phrase for exact matching
        fts_query = f'"{phrase}"'
        
        sql = f"""
            SELECT c.*, -bm25(claims_fts) as score
            FROM claims_fts
            JOIN claims c ON claims_fts.claim_id = c.claim_id
            WHERE claims_fts MATCH ?
              AND {where_clause}
            ORDER BY score DESC
            LIMIT ?
        """
        
        try:
            rows = self.db.fetchall(sql, (fts_query,) + tuple(params) + (k,))
            
            results = []
            for row in rows:
                claim = Claim.from_row(row)
                result = SearchResult.from_claim(
                    claim=claim,
                    score=row['score'],
                    source=f"{self.name()}_exact"
                )
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Exact phrase search failed: {e}")
            return []
    
    def search_by_column(
        self,
        column: str,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Search in a specific FTS column.
        
        Args:
            column: Column to search (statement, predicate, subject_text, object_text).
            query: Search query.
            k: Number of results.
            filters: Optional filters.
            
        Returns:
            List of SearchResults from the specified column.
        """
        filters = filters or SearchFilters()
        conditions, params = filters.to_sql_conditions()
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Column-specific query
        sanitized = self._sanitize_query(query)
        fts_query = f"{column}:{sanitized}"
        
        sql = f"""
            SELECT c.*, -bm25(claims_fts) as score
            FROM claims_fts
            JOIN claims c ON claims_fts.claim_id = c.claim_id
            WHERE claims_fts MATCH ?
              AND {where_clause}
            ORDER BY score DESC
            LIMIT ?
        """
        
        try:
            rows = self.db.fetchall(sql, (fts_query,) + tuple(params) + (k,))
            
            results = []
            for row in rows:
                claim = Claim.from_row(row)
                result = SearchResult.from_claim(
                    claim=claim,
                    score=row['score'],
                    source=f"{self.name()}_{column}",
                    metadata={'column': column}
                )
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Column search failed: {e}")
            return []
