"""
Embedding-based search strategy for PKB v0.

Provides:
- EmbeddingStore: Manages embedding storage, caching, and batch computation
- EmbeddingSearchStrategy: Cosine similarity search over embeddings

Uses code_common/call_llm.py for embedding generation.
"""

import logging
from typing import List, Dict, Optional, Any
import numpy as np

from .base import SearchStrategy, SearchFilters, SearchResult
from ..database import PKBDatabase
from ..config import PKBConfig
from ..models import Claim
from ..constants import ClaimStatus
from ..utils import now_iso, get_parallel_executor

logger = logging.getLogger(__name__)

# Import time_logger for guaranteed visibility
try:
    from common import time_logger
except ImportError:
    # Fallback to regular logger if time_logger not available
    time_logger = logger


class EmbeddingStore:
    """
    Manages claim embeddings with caching and batch computation.
    
    Embeddings are stored in the claim_embeddings table as BLOBs.
    Supports parallel computation for batch operations.
    
    Attributes:
        db: PKBDatabase instance.
        keys: API keys for embedding calls.
        config: PKBConfig with settings.
    """
    
    def __init__(
        self,
        db: PKBDatabase,
        keys: Dict[str, str],
        config: PKBConfig
    ):
        """
        Initialize embedding store.
        
        Args:
            db: PKBDatabase instance.
            keys: Dict with OPENROUTER_API_KEY.
            config: PKBConfig with embedding settings.
        """
        self.db = db
        self.keys = keys
        self.config = config
        self.executor = get_parallel_executor(config.max_parallel_embedding_calls)
    
    def get_embedding(self, claim_id: str) -> Optional[np.ndarray]:
        """
        Get cached embedding for a claim.
        
        Args:
            claim_id: ID of claim.
            
        Returns:
            Numpy array or None if not cached.
        """
        row = self.db.fetchone(
            "SELECT embedding FROM claim_embeddings WHERE claim_id = ?",
            (claim_id,)
        )
        
        if row and row['embedding']:
            return np.frombuffer(row['embedding'], dtype=np.float32)
        return None
    
    def store_embedding(
        self,
        claim_id: str,
        embedding: np.ndarray,
        model_name: str = None
    ) -> None:
        """
        Store embedding for a claim.
        
        Args:
            claim_id: ID of claim.
            embedding: Numpy array embedding.
            model_name: Model used to generate embedding.
        """
        model_name = model_name or self.config.embedding_model
        embedding_blob = embedding.astype(np.float32).tobytes()
        
        with self.db.transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO claim_embeddings (claim_id, embedding, model_name, created_at)
                VALUES (?, ?, ?, ?)
            """, (claim_id, embedding_blob, model_name, now_iso()))
    
    def compute_and_store(self, claim: Claim) -> np.ndarray:
        """
        Compute embedding for a claim and store it.
        
        Uses get_document_embedding from code_common/call_llm.py.
        
        Args:
            claim: Claim to embed.
            
        Returns:
            Computed embedding.
        """
        try:
            from code_common.call_llm import get_document_embedding
        except ImportError:
            logger.error("code_common.call_llm not available")
            raise ImportError("code_common.call_llm is required for embeddings")
        
        embedding = get_document_embedding(claim.statement, self.keys)
        self.store_embedding(claim.claim_id, embedding)
        
        logger.debug(f"Computed and stored embedding for claim {claim.claim_id}")
        return embedding
    
    def ensure_embeddings(self, claims: List[Claim]) -> Dict[str, np.ndarray]:
        """
        Ensure embeddings exist for all claims, computing if needed.
        
        Uses parallel computation for efficiency.
        
        Args:
            claims: List of claims to ensure embeddings for.
            
        Returns:
            Dict mapping claim_id to embedding.
        """
        result = {}
        to_compute = []
        
        # Check which embeddings exist
        for claim in claims:
            emb = self.get_embedding(claim.claim_id)
            if emb is not None:
                result[claim.claim_id] = emb
            else:
                to_compute.append(claim)
        
        # Compute missing embeddings in parallel
        if to_compute:
            logger.info(f"Computing {len(to_compute)} embeddings in parallel")
            computed = self.executor.map_parallel(
                self.compute_and_store,
                to_compute,
                timeout=120.0
            )
            
            for claim, emb in zip(to_compute, computed):
                result[claim.claim_id] = emb
        
        return result
    
    def delete_embedding(self, claim_id: str) -> None:
        """Delete cached embedding for a claim."""
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM claim_embeddings WHERE claim_id = ?", (claim_id,))
    
    def get_all_embeddings(
        self,
        filters: SearchFilters = None
    ) -> List[tuple]:
        """
        Get all embeddings matching filters.
        
        Args:
            filters: Optional filters to apply.
            
        Returns:
            List of (claim_id, embedding) tuples.
        """
        filters = filters or SearchFilters()
        conditions, params = filters.to_sql_conditions()
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        sql = f"""
            SELECT ce.claim_id, ce.embedding
            FROM claim_embeddings ce
            JOIN claims c ON ce.claim_id = c.claim_id
            WHERE {where_clause}
        """
        
        rows = self.db.fetchall(sql, tuple(params))
        
        return [
            (row['claim_id'], np.frombuffer(row['embedding'], dtype=np.float32))
            for row in rows
        ]


class EmbeddingSearchStrategy(SearchStrategy):
    """
    Cosine similarity search over claim embeddings.
    
    Computes query embedding and finds most similar stored embeddings.
    More semantic than FTS but requires embedding computation.
    
    Attributes:
        db: PKBDatabase instance.
        keys: API keys for embedding calls.
        config: PKBConfig with settings.
        store: EmbeddingStore for managing embeddings.
    """
    
    def __init__(
        self,
        db: PKBDatabase,
        keys: Dict[str, str],
        config: PKBConfig
    ):
        """
        Initialize embedding search strategy.
        
        Args:
            db: PKBDatabase instance.
            keys: Dict with OPENROUTER_API_KEY.
            config: PKBConfig with settings.
        """
        self.db = db
        self.keys = keys
        self.config = config
        self.store = EmbeddingStore(db, keys, config)
    
    def name(self) -> str:
        return "embedding"
    
    def search(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Execute embedding similarity search.
        
        Args:
            query: Search query string.
            k: Number of results to return.
            filters: Optional filters to apply.
            
        Returns:
            List of SearchResult objects, ordered by cosine similarity.
        """
        filters = filters or SearchFilters()
        time_logger.info(f"[EMBEDDING] Search called with query_len={len(query)}, user_email={filters.user_email}")
        
        if not self.config.embedding_enabled:
            time_logger.warning("[EMBEDDING] Embedding search disabled in config")
            return []
        
        try:
            from code_common.call_llm import get_query_embedding
        except ImportError:
            time_logger.error("[EMBEDDING] code_common.call_llm not available")
            return []
        
        # Compute query embedding
        time_logger.info("[EMBEDDING] Computing query embedding...")
        query_emb = get_query_embedding(query, self.keys)
        # Use 'is not None' instead of truthiness check for numpy arrays
        if query_emb is None:
            time_logger.error("[EMBEDDING] get_query_embedding returned None")
            return []
        time_logger.info(f"[EMBEDDING] Query embedding computed, shape={query_emb.shape if hasattr(query_emb, 'shape') else len(query_emb)}")
        
        # Get filtered claims
        candidates = self._get_filtered_claims(filters)
        time_logger.info(f"[EMBEDDING] Got {len(candidates)} candidate claims after filtering")
        if not candidates:
            time_logger.info("[EMBEDDING] No candidates found, returning empty")
            return []
        
        # Ensure all candidates have embeddings
        embeddings = self.store.ensure_embeddings(candidates)
        
        # Compute cosine similarities
        scores = []
        for claim in candidates:
            emb = embeddings.get(claim.claim_id)
            if emb is not None:
                sim = self._cosine_similarity(query_emb, emb)
                scores.append((claim, float(sim)))
        
        # Sort by similarity and return top-k
        scores.sort(key=lambda x: x[1], reverse=True)
        
        results = []
        for claim, score in scores[:k]:
            result = SearchResult.from_claim(
                claim=claim,
                score=score,
                source=self.name(),
                metadata={'similarity_type': 'cosine'}
            )
            results.append(result)
        
        logger.debug(f"Embedding search '{query}' returned {len(results)} results")
        return results
    
    def _get_filtered_claims(self, filters: SearchFilters) -> List[Claim]:
        """
        Get all claims matching filters.
        
        Args:
            filters: Filters to apply.
            
        Returns:
            List of matching Claim objects.
        """
        conditions, params = filters.to_sql_conditions()
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Replace 'c.' prefix since we're selecting directly from claims
        where_clause = where_clause.replace('c.', '')
        
        sql = f"SELECT * FROM claims WHERE {where_clause}"
        rows = self.db.fetchall(sql, tuple(params))
        
        return [Claim.from_row(row) for row in rows]
    
    def _cosine_similarity(
        self,
        vec1: np.ndarray,
        vec2: np.ndarray
    ) -> float:
        """
        Compute cosine similarity between two vectors.
        
        Args:
            vec1: First vector.
            vec2: Second vector.
            
        Returns:
            Cosine similarity (-1 to 1, higher = more similar).
        """
        dot = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot / (norm1 * norm2)
