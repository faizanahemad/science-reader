"""
Hybrid search strategy for PKB v0.

HybridSearchStrategy combines multiple search strategies:
- Executes selected strategies in parallel
- Merges results using Reciprocal Rank Fusion (RRF)
- Optionally applies LLM reranking to top candidates
"""

import json
import logging
from typing import List, Dict, Optional

from .base import SearchStrategy, SearchFilters, SearchResult, merge_results_rrf, dedupe_results
from .fts_search import FTSSearchStrategy
from .embedding_search import EmbeddingSearchStrategy
from .rewrite_search import RewriteSearchStrategy
from .mapreduce_search import MapReduceSearchStrategy
from ..database import PKBDatabase
from ..config import PKBConfig
from ..utils import get_parallel_executor

logger = logging.getLogger(__name__)

# Import time_logger for guaranteed visibility
try:
    from common import time_logger
except ImportError:
    # Fallback to regular logger if time_logger not available
    time_logger = logger


class HybridSearchStrategy:
    """
    Combines multiple search strategies with parallel execution and RRF merging.
    
    Features:
    - Parallel execution of independent strategies
    - Reciprocal Rank Fusion for combining results
    - Optional LLM reranking for final refinement
    - Configurable strategy selection
    
    Attributes:
        db: PKBDatabase instance.
        keys: API keys for LLM/embedding calls.
        config: PKBConfig with settings.
        strategies: Dict of available SearchStrategy instances.
        executor: ParallelExecutor for concurrent execution.
    """
    
    def __init__(
        self,
        db: PKBDatabase,
        keys: Dict[str, str],
        config: PKBConfig
    ):
        """
        Initialize hybrid search with all strategies.
        
        Args:
            db: PKBDatabase instance.
            keys: Dict with OPENROUTER_API_KEY.
            config: PKBConfig with settings.
        """
        self.db = db
        self.keys = keys
        self.config = config
        self.executor = get_parallel_executor(config.max_parallel_llm_calls)
        
        # Initialize all available strategies
        self.strategies: Dict[str, SearchStrategy] = {
            "fts": FTSSearchStrategy(db),
        }
        
        # Only add LLM-dependent strategies if keys are available
        if keys.get("OPENROUTER_API_KEY"):
            if config.embedding_enabled:
                self.strategies["embedding"] = EmbeddingSearchStrategy(db, keys, config)
            self.strategies["rewrite"] = RewriteSearchStrategy(db, keys, config)
            self.strategies["mapreduce"] = MapReduceSearchStrategy(db, keys, config)
    
    def search(
        self,
        query: str,
        strategy_names: List[str] = None,
        k: int = 20,
        filters: SearchFilters = None,
        llm_rerank: bool = False,
        llm_rerank_top_n: int = 50
    ) -> List[SearchResult]:
        """
        Execute hybrid search across multiple strategies.
        
        Args:
            query: Search query string.
            strategy_names: Strategies to use (default: ["fts", "embedding"]).
            k: Number of final results to return.
            filters: Optional filters to apply.
            llm_rerank: Whether to apply LLM reranking to top results.
            llm_rerank_top_n: Number of candidates for LLM reranking.
            
        Returns:
            List of SearchResult objects with combined scores.
        """
        # Default to FTS + embedding if available
        if strategy_names is None:
            strategy_names = ["fts"]
            if "embedding" in self.strategies:
                strategy_names.append("embedding")
        
        filters = filters or SearchFilters()
        time_logger.info(f"[HYBRID] Search called: query_len={len(query)}, strategies={strategy_names}, k={k}, user_email={filters.user_email}")
        
        # Filter to available strategies
        active_strategies = [
            name for name in strategy_names
            if name in self.strategies
        ]
        
        time_logger.info(f"[HYBRID] Active strategies: {active_strategies}, available: {list(self.strategies.keys())}")
        
        if not active_strategies:
            time_logger.warning("[HYBRID] No valid strategies specified")
            return []
        
        # Execute strategies in parallel
        all_results = self._execute_parallel(query, active_strategies, k * 2, filters)
        time_logger.info(f"[HYBRID] Strategy results: {[(name, len(r)) for name, r in zip(active_strategies, all_results)]}")
        
        # Merge using RRF
        merged_k = llm_rerank_top_n if llm_rerank else k
        merged = merge_results_rrf(all_results, k=merged_k)
        time_logger.info(f"[HYBRID] Merged results: {len(merged)}")
        
        # Optional LLM reranking
        if llm_rerank and len(merged) > k and "OPENROUTER_API_KEY" in self.keys:
            merged = self._llm_rerank(query, merged, k)
        
        # Ensure we don't return more than k results
        time_logger.info(f"[HYBRID] Returning {min(len(merged), k)} results")
        return merged[:k]
    
    def _execute_parallel(
        self,
        query: str,
        strategy_names: List[str],
        k: int,
        filters: SearchFilters
    ) -> List[List[SearchResult]]:
        """
        Execute multiple strategies in parallel.
        
        Args:
            query: Search query.
            strategy_names: Strategies to execute.
            k: Results per strategy.
            filters: Filters to apply.
            
        Returns:
            List of result lists from each strategy.
        """
        if len(strategy_names) == 1:
            # Single strategy, no parallelization needed
            strategy = self.strategies[strategy_names[0]]
            return [strategy.search(query, k, filters)]
        
        def run_strategy(name: str) -> List[SearchResult]:
            try:
                time_logger.info(f"[HYBRID] Running strategy: {name}")
                strategy = self.strategies[name]
                results = strategy.search(query, k, filters)
                time_logger.info(f"[HYBRID] Strategy {name} returned {len(results)} results")
                # Tag results with source
                for r in results:
                    r.source = name
                return results
            except Exception as e:
                time_logger.error(f"[HYBRID] Strategy {name} failed: {e}", exc_info=True)
                return []
        
        # Execute in parallel
        results = self.executor.map_parallel(
            run_strategy,
            strategy_names,
            timeout=60.0
        )
        
        return results
    
    def _llm_rerank(
        self,
        query: str,
        results: List[SearchResult],
        k: int
    ) -> List[SearchResult]:
        """
        Use LLM to rerank top candidates.
        
        Args:
            query: Original query.
            results: Results to rerank.
            k: Number of final results.
            
        Returns:
            Reranked list of SearchResult objects.
        """
        try:
            from code_common.call_llm import call_llm
        except ImportError:
            logger.warning("code_common.call_llm not available for reranking")
            return results
        
        # Build claims text for LLM
        claims_text = "\n".join([
            f"[{i+1}] {r.claim.statement}"
            for i, r in enumerate(results[:50])  # Limit to prevent context overflow
        ])
        
        prompt = f"""Rerank these claims by relevance to the query.

Query: "{query}"

Claims:
{claims_text}

Return the claim numbers in order of relevance (most relevant first).
Format: comma-separated numbers, e.g., "3,1,7,2,5"

Ranking:"""

        try:
            response = call_llm(
                self.keys,
                self.config.llm_model,
                prompt,
                temperature=0.0
            )
            
            # Parse ranking
            numbers = [int(n.strip()) for n in response.strip().split(',') if n.strip().isdigit()]
            
            # Reorder results
            reranked = []
            seen = set()
            
            for num in numbers[:k]:
                idx = num - 1  # Convert to 0-indexed
                if 0 <= idx < len(results) and idx not in seen:
                    result = results[idx]
                    result.source = "llm_rerank"
                    result.metadata['rerank_position'] = len(reranked) + 1
                    reranked.append(result)
                    seen.add(idx)
            
            # Add any remaining results not in ranking
            for i, result in enumerate(results):
                if i not in seen and len(reranked) < k:
                    reranked.append(result)
            
            logger.debug(f"LLM reranked {len(reranked)} results")
            return reranked
            
        except Exception as e:
            logger.error(f"LLM reranking failed: {e}")
            return results[:k]
    
    def search_simple(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Simple search using default strategies (FTS + embedding).
        
        Args:
            query: Search query.
            k: Number of results.
            filters: Optional filters.
            
        Returns:
            List of SearchResult objects.
        """
        return self.search(query, k=k, filters=filters)
    
    def search_with_rerank(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Search with LLM reranking enabled.
        
        Args:
            query: Search query.
            k: Number of results.
            filters: Optional filters.
            
        Returns:
            List of reranked SearchResult objects.
        """
        return self.search(
            query,
            k=k,
            filters=filters,
            llm_rerank=True,
            llm_rerank_top_n=min(50, k * 3)
        )
    
    def search_all_strategies(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None
    ) -> List[SearchResult]:
        """
        Search using all available strategies.
        
        Args:
            query: Search query.
            k: Number of results.
            filters: Optional filters.
            
        Returns:
            List of SearchResult objects from all strategies.
        """
        return self.search(
            query,
            strategy_names=list(self.strategies.keys()),
            k=k,
            filters=filters
        )
    
    def get_available_strategies(self) -> List[str]:
        """Get list of available strategy names."""
        return list(self.strategies.keys())
