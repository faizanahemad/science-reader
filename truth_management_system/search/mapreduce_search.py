"""
LLM Map-Reduce search strategy for PKB v0.

MapReduceSearchStrategy uses an LLM to score and rank candidate claims.
This is the most expensive but most nuanced search strategy.

This is "S1" in the plan - good for complex queries requiring reasoning.
"""

import json
import logging
from typing import List, Dict, Optional

from .base import SearchStrategy, SearchFilters, SearchResult
from .fts_search import FTSSearchStrategy
from ..database import PKBDatabase
from ..config import PKBConfig
from ..models import Claim
from ..utils import get_parallel_executor

logger = logging.getLogger(__name__)


class MapReduceSearchStrategy(SearchStrategy):
    """
    LLM scores/ranks candidate claims.
    
    Process:
    1. Get candidate pool using FTS (fast pre-filter)
    2. Batch claims for LLM scoring
    3. LLM scores each claim for relevance
    4. Sort by LLM scores and return top-k
    
    Expensive but provides nuanced relevance ranking.
    
    Attributes:
        db: PKBDatabase instance.
        keys: API keys for LLM calls.
        config: PKBConfig with settings.
        executor: ParallelExecutor for concurrent scoring.
    """
    
    def __init__(
        self,
        db: PKBDatabase,
        keys: Dict[str, str],
        config: PKBConfig
    ):
        """
        Initialize map-reduce search strategy.
        
        Args:
            db: PKBDatabase instance.
            keys: Dict with OPENROUTER_API_KEY.
            config: PKBConfig with settings.
        """
        self.db = db
        self.keys = keys
        self.config = config
        self.executor = get_parallel_executor(config.max_parallel_llm_calls)
    
    def name(self) -> str:
        return "mapreduce"
    
    def search(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None,
        candidate_pool_size: int = 100
    ) -> List[SearchResult]:
        """
        Execute LLM-based search with scoring.
        
        Args:
            query: Search query string.
            k: Number of results to return.
            filters: Optional filters to apply.
            candidate_pool_size: Number of candidates to score.
            
        Returns:
            List of SearchResult objects, ordered by LLM relevance score.
        """
        filters = filters or SearchFilters()
        
        # 1. Get candidate pool using FTS
        fts = FTSSearchStrategy(self.db)
        candidates = fts.search(query, k=candidate_pool_size, filters=filters)
        
        if not candidates:
            return []
        
        # 2. Batch candidates for efficient LLM scoring
        batch_size = 15  # ~15 claims per LLM call to stay within context
        batches = [
            candidates[i:i+batch_size]
            for i in range(0, len(candidates), batch_size)
        ]
        
        # 3. Score batches (parallel if multiple batches)
        all_scores = []
        
        if len(batches) <= 1:
            # Single batch, no parallelization needed
            for batch in batches:
                scores = self._score_batch(query, batch)
                all_scores.extend(scores)
        else:
            # Multiple batches, score in parallel
            score_results = self.executor.map_parallel(
                lambda b: self._score_batch(query, b),
                batches,
                timeout=60.0
            )
            for batch_scores in score_results:
                all_scores.extend(batch_scores)
        
        # 4. Match scores to results and sort
        score_map = {s['claim_id']: s for s in all_scores}
        
        results = []
        for result in candidates:
            cid = result.claim.claim_id
            if cid in score_map:
                score_data = score_map[cid]
                result.score = score_data.get('score', 0.0)
                result.source = self.name()
                result.metadata['llm_score'] = score_data.get('score', 0.0)
                result.metadata['llm_reason'] = score_data.get('reason', '')
                results.append(result)
        
        # Sort by LLM score
        results.sort(key=lambda r: r.score, reverse=True)
        
        logger.debug(f"MapReduce search '{query}' scored {len(all_scores)} claims")
        return results[:k]
    
    def _score_batch(
        self,
        query: str,
        batch: List[SearchResult]
    ) -> List[Dict]:
        """
        Score a batch of claims using LLM.
        
        Args:
            query: Search query.
            batch: List of SearchResult objects to score.
            
        Returns:
            List of dicts with claim_id, score, reason.
        """
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            logger.error("code_common.call_llm not available")
            return [{'claim_id': r.claim.claim_id, 'score': r.score, 'reason': 'fallback'} for r in batch]
        
        # Build claims text
        claims_text = "\n".join([
            f"[{i+1}] ID:{r.claim.claim_id[:8]} | {r.claim.statement}"
            for i, r in enumerate(batch)
        ])
        
        prompt = f"""Score each claim's relevance to the search query.

Query: "{query}"

Claims to score:
{claims_text}

For each claim, provide a relevance score from 0.0 to 1.0:
- 1.0 = Directly answers the query
- 0.7-0.9 = Highly relevant
- 0.4-0.6 = Somewhat relevant
- 0.1-0.3 = Tangentially related
- 0.0 = Not relevant

Return JSON array only:
[{{"id": "claim_id_first_8_chars", "score": 0.8, "reason": "brief reason"}}]

JSON:"""

        try:
            response = call_llm(
                self.keys,
                self.config.llm_model,
                prompt,
                temperature=0.0  # Deterministic for consistency
            )
            
            # Parse JSON response
            parsed = json.loads(response.strip())
            
            # Map short IDs back to full IDs
            id_map = {r.claim.claim_id[:8]: r.claim.claim_id for r in batch}
            
            results = []
            for item in parsed:
                short_id = item.get('id', '')
                full_id = id_map.get(short_id)
                
                if full_id:
                    results.append({
                        'claim_id': full_id,
                        'score': float(item.get('score', 0.0)),
                        'reason': item.get('reason', '')
                    })
            
            return results
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM scoring response: {e}")
            # Fall back to original scores
            return [
                {'claim_id': r.claim.claim_id, 'score': r.score, 'reason': 'parse_error'}
                for r in batch
            ]
        except Exception as e:
            logger.error(f"LLM scoring failed: {e}")
            return [
                {'claim_id': r.claim.claim_id, 'score': r.score, 'reason': 'error'}
                for r in batch
            ]
