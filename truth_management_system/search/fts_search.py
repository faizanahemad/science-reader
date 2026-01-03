"""
FTS/BM25 search strategy for PKB v0.

FTSSearchStrategy provides full-text search using SQLite FTS5:
- BM25 ranking for relevance
- Fast, deterministic baseline search
- Supports all standard filters
"""

import logging
import os
import re
import sqlite3
from typing import List, Optional

from .base import SearchStrategy, SearchFilters, SearchResult
from ..database import PKBDatabase
from ..models import Claim
from ..constants import ClaimStatus

logger = logging.getLogger(__name__)
FTS_SANITIZER_VERSION = "2026-01-02a"

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
        if os.environ.get("PKB_LOG_FTS_VERSION") == "1":
            time_logger.info(f"[FTS] Module={__file__}, sanitizer_version={FTS_SANITIZER_VERSION}")
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
        
        def _run_fts(fts_query_to_run: str):
            time_logger.info(f"[FTS] Executing SQL with fts_query='{fts_query_to_run}', k={k}")
            return self.db.fetchall(sql, (fts_query_to_run,) + tuple(params) + (k,))

        try:
            rows = _run_fts(fts_query)
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
            
        except sqlite3.OperationalError as e:
            # Defensive retry:
            # If the MATCH query accidentally contains an FTS column-scope like `opus:term`,
            # SQLite will raise "no such column: opus". This can happen if upstream code
            # passes raw FTS syntax or if the sanitizer is bypassed in a deployment.
            msg = str(e)
            # We also see this error with hyphenated tokens like 'claude-opus*' which
            # the FTS5 parser can interpret in a way that triggers a bogus column lookup
            # for the suffix token ('opus').
            if "no such column" in msg and (":" in query or "-" in query or "–" in query or "—" in query):
                try:
                    retry_query = re.sub(r"\b(\w+)\s*:\s*", r"\1 ", query)
                    retry_query = re.sub(r"[-–—]+", " ", retry_query)
                    retry_fts_query = self._sanitize_query(retry_query)
                    time_logger.warning(
                        f"[FTS] OperationalError='{msg}'. Retrying with safer query: "
                        f"orig='{query[:120]}', retry_sanitized='{retry_fts_query[:120]}'"
                    )
                    if retry_fts_query and retry_fts_query != fts_query:
                        rows = _run_fts(retry_fts_query)
                        results = []
                        for row in rows:
                            claim = Claim.from_row(row)
                            results.append(
                                SearchResult.from_claim(
                                    claim=claim,
                                    score=row["score"],
                                    source=self.name(),
                                    metadata={"fts_query": retry_fts_query, "retry": True},
                                )
                            )
                        return results
                except Exception:
                    # Fall through to returning []
                    pass

            time_logger.error(f"[FTS] Search failed: {e}", exc_info=True)
            return []
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
        # Remove any explicit FTS column scoping patterns like `foo:bar`.
        # We treat these as normal text unless the caller explicitly uses `search_by_column`.
        query = re.sub(r"\b(\w+)\s*:\s*", r"\1 ", query)
        # Hyphenated model names / identifiers (e.g. 'claude-opus-4.5') are common in prompts.
        # FTS5 treats '-' as an operator in many contexts; unquoted tokens like 'claude-opus*'
        # can produce OperationalError: "no such column: opus". Convert hyphens to spaces so
        # we only emit plain term tokens.
        query = re.sub(r"[-–—]+", " ", query)

        # Remove FTS5 operators / punctuation that might cause syntax errors.
        # Keep alphanumeric, spaces, and underscores.
        sanitized = re.sub(r"[^\w\s]", " ", query)
        
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
        allowed_columns = {"statement", "predicate", "subject_text", "object_text", "context_domain"}
        if column not in allowed_columns:
            raise ValueError(
                f"Invalid FTS column '{column}'. Allowed columns: {sorted(allowed_columns)}"
            )

        filters = filters or SearchFilters()
        conditions, params = filters.to_sql_conditions()
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Column-scoped query: apply the column prefix to each term.
        # We do NOT reuse _sanitize_query output directly because it can contain OR/quotes
        # that need column prefixes on each term.
        raw = re.sub(r"\b(\w+)\s*:\s*", r"\1 ", query)
        raw = re.sub(r"[-–—]+", " ", raw)
        raw = re.sub(r"[^\w\s]", " ", raw)
        raw = " ".join(raw.split())
        if not raw:
            return []

        words = raw.split()
        if len(words) == 1:
            fts_query = f"{column}:{words[0]}*"
        else:
            terms = [f'{column}:"{raw}"']
            terms.extend([f"{column}:{w}*" for w in words])
            fts_query = " OR ".join(terms)
        
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
