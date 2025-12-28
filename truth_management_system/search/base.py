"""
Base classes and utilities for search strategies.

Provides:
- SearchStrategy: Abstract base class for all search strategies
- SearchFilters: Dataclass for search filtering parameters
- SearchResult: Dataclass for search results with scores and metadata
- merge_results_rrf: Reciprocal Rank Fusion for combining results
- dedupe_results: Remove duplicate claims, keep highest score
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from ..models import Claim
from ..constants import ClaimStatus


@dataclass
class SearchFilters:
    """
    Filters applicable to all search strategies.
    
    Attributes:
        statuses: Claim statuses to include (default: active + contested).
        context_domains: Filter to specific domains (None = all).
        claim_types: Filter to specific types (None = all).
        tag_ids: Filter to claims with these tags (None = all).
        entity_ids: Filter to claims with these entities (None = all).
        valid_at: Filter to claims valid at this timestamp (None = no filter).
        include_contested: Include contested claims (with warnings).
        user_email: Filter to claims owned by this user (None = all).
    """
    statuses: List[str] = field(default_factory=lambda: ClaimStatus.default_search_statuses())
    context_domains: Optional[List[str]] = None
    claim_types: Optional[List[str]] = None
    tag_ids: Optional[List[str]] = None
    entity_ids: Optional[List[str]] = None
    valid_at: Optional[str] = None
    include_contested: bool = True
    user_email: Optional[str] = None
    
    def to_sql_conditions(self) -> tuple:
        """
        Convert filters to SQL WHERE conditions.
        
        Returns:
            Tuple of (conditions_list, params_list).
        """
        conditions = []
        params = []
        
        # User email filter (most important for multi-user)
        if self.user_email:
            conditions.append("c.user_email = ?")
            params.append(self.user_email)
        
        # Status filter
        if self.statuses:
            placeholders = ','.join(['?' for _ in self.statuses])
            conditions.append(f"c.status IN ({placeholders})")
            params.extend(self.statuses)
        
        # Context domain filter
        if self.context_domains:
            placeholders = ','.join(['?' for _ in self.context_domains])
            conditions.append(f"c.context_domain IN ({placeholders})")
            params.extend(self.context_domains)
        
        # Claim type filter
        if self.claim_types:
            placeholders = ','.join(['?' for _ in self.claim_types])
            conditions.append(f"c.claim_type IN ({placeholders})")
            params.extend(self.claim_types)
        
        # Validity filter
        if self.valid_at:
            conditions.append("c.valid_from <= ?")
            conditions.append("(c.valid_to IS NULL OR c.valid_to >= ?)")
            params.extend([self.valid_at, self.valid_at])
        
        return conditions, params


@dataclass
class SearchResult:
    """
    Unified search result with metadata.
    
    Attributes:
        claim: The matched Claim object.
        score: Relevance score (interpretation varies by strategy).
        source: Which strategy produced this result.
        is_contested: Whether the claim is in contested status.
        warnings: List of warnings (e.g., "contested claim").
        metadata: Additional strategy-specific metadata.
    """
    claim: Claim
    score: float
    source: str  # 'fts', 'embedding', 'rewrite', 'mapreduce', 'llm_rerank'
    is_contested: bool
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Add contested warning if applicable."""
        if self.is_contested and "contested" not in str(self.warnings).lower():
            self.warnings.append(
                "This claim is contested and may conflict with other claims."
            )
    
    @classmethod
    def from_claim(
        cls,
        claim: Claim,
        score: float,
        source: str,
        metadata: Dict[str, Any] = None
    ) -> 'SearchResult':
        """
        Create SearchResult from a Claim.
        
        Args:
            claim: The Claim object.
            score: Relevance score.
            source: Strategy name.
            metadata: Optional additional metadata.
            
        Returns:
            SearchResult instance.
        """
        return cls(
            claim=claim,
            score=score,
            source=source,
            is_contested=claim.status == ClaimStatus.CONTESTED.value,
            metadata=metadata or {}
        )


class SearchStrategy(ABC):
    """
    Abstract base class for search strategies.
    
    All search strategies must implement:
    - search(): Execute search and return results
    - name(): Return strategy identifier
    
    Strategies may use different approaches:
    - FTS: BM25 ranking via SQLite FTS5
    - Embedding: Cosine similarity over vectors
    - LLM Rewrite: Transform query then FTS
    - LLM Map-Reduce: LLM scores candidates
    """
    
    @abstractmethod
    def search(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Execute search and return results.
        
        Args:
            query: Search query string.
            k: Number of results to return.
            filters: Optional filters to apply.
            
        Returns:
            List of SearchResult objects, ordered by score descending.
        """
        pass
    
    @abstractmethod
    def name(self) -> str:
        """
        Return the strategy identifier.
        
        Returns:
            Strategy name (e.g., 'fts', 'embedding').
        """
        pass


def merge_results_rrf(
    result_lists: List[List[SearchResult]],
    k: int = 60,
    rrf_k: int = 60
) -> List[SearchResult]:
    """
    Merge results from multiple strategies using Reciprocal Rank Fusion.
    
    RRF is a robust rank aggregation method that doesn't require
    score normalization across different strategies.
    
    Formula: score = sum(1 / (rank + k)) for each list
    
    Args:
        result_lists: List of result lists from different strategies.
        k: Number of final results to return.
        rrf_k: RRF constant (default: 60, as per original paper).
        
    Returns:
        Merged and re-ranked list of SearchResults.
    """
    # Track: claim_id -> (best_result, total_score, sources)
    scores: Dict[str, tuple] = {}
    
    for results in result_lists:
        for rank, result in enumerate(results):
            cid = result.claim.claim_id
            rrf_score = 1.0 / (rank + rrf_k)
            
            if cid in scores:
                _, total, sources = scores[cid]
                scores[cid] = (result, total + rrf_score, sources + [result.source])
            else:
                scores[cid] = (result, rrf_score, [result.source])
    
    # Sort by combined score
    sorted_items = sorted(scores.values(), key=lambda x: x[1], reverse=True)
    
    # Build final results
    final = []
    for result, score, sources in sorted_items[:k]:
        # Update result with combined info
        result.score = score
        result.metadata['sources'] = list(set(sources))
        result.metadata['rrf_score'] = score
        final.append(result)
    
    return final


def dedupe_results(results: List[SearchResult]) -> List[SearchResult]:
    """
    Remove duplicate claims, keeping the highest-scored instance.
    
    Args:
        results: List of SearchResults (may have duplicates).
        
    Returns:
        Deduplicated list with highest scores preserved.
    """
    seen: Dict[str, SearchResult] = {}
    
    for result in results:
        cid = result.claim.claim_id
        if cid not in seen or result.score > seen[cid].score:
            seen[cid] = result
    
    # Return in score order
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)


def apply_tag_filter(
    db,
    claim_ids: List[str],
    tag_ids: List[str]
) -> List[str]:
    """
    Filter claim IDs to those with specified tags.
    
    Args:
        db: PKBDatabase instance.
        claim_ids: List of claim IDs to filter.
        tag_ids: List of tag IDs that claims must have.
        
    Returns:
        Filtered list of claim IDs.
    """
    if not claim_ids or not tag_ids:
        return claim_ids
    
    claim_placeholders = ','.join(['?' for _ in claim_ids])
    tag_placeholders = ','.join(['?' for _ in tag_ids])
    
    rows = db.fetchall(f"""
        SELECT DISTINCT claim_id FROM claim_tags
        WHERE claim_id IN ({claim_placeholders})
          AND tag_id IN ({tag_placeholders})
    """, tuple(claim_ids) + tuple(tag_ids))
    
    return [row['claim_id'] for row in rows]


def apply_entity_filter(
    db,
    claim_ids: List[str],
    entity_ids: List[str]
) -> List[str]:
    """
    Filter claim IDs to those with specified entities.
    
    Args:
        db: PKBDatabase instance.
        claim_ids: List of claim IDs to filter.
        entity_ids: List of entity IDs that claims must have.
        
    Returns:
        Filtered list of claim IDs.
    """
    if not claim_ids or not entity_ids:
        return claim_ids
    
    claim_placeholders = ','.join(['?' for _ in claim_ids])
    entity_placeholders = ','.join(['?' for _ in entity_ids])
    
    rows = db.fetchall(f"""
        SELECT DISTINCT claim_id FROM claim_entities
        WHERE claim_id IN ({claim_placeholders})
          AND entity_id IN ({entity_placeholders})
    """, tuple(claim_ids) + tuple(entity_ids))
    
    return [row['claim_id'] for row in rows]
