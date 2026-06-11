"""
Hybrid search strategy for PKB v0.

HybridSearchStrategy combines multiple search strategies:
- Executes selected strategies in parallel
- Merges results using Reciprocal Rank Fusion (RRF)
- Optionally applies LLM reranking to top candidates
"""

import json
import logging
from typing import List, Dict, Optional, Any

from .base import SearchStrategy, SearchFilters, SearchResult, merge_results_rrf, dedupe_results, apply_recency_confidence_rerank
from .fts_search import FTSSearchStrategy
from .embedding_search import EmbeddingSearchStrategy
from .rewrite_search import RewriteSearchStrategy
from .mapreduce_search import MapReduceSearchStrategy
from .entity_search import EntitySearchStrategy
from .tag_search import TagSearchStrategy
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

        # W-C: entity-linked retrieval. Works without an API key (it degrades to
        # recency ordering when no query embedding is available), so it is
        # registered independent of the key gate, behind its config flag.
        if getattr(config, "entity_strategy_enabled", True):
            self.strategies["entity"] = EntitySearchStrategy(db, keys, config)

        # W-D: tag-linked retrieval, symmetric to the entity strategy. INERT by
        # default (tag_strategy_enabled=False) so it is not registered — and thus
        # never runs — until explicitly enabled and eval-gated. Like the entity
        # strategy it works without an API key (degrades to recency order).
        if getattr(config, "tag_strategy_enabled", False):
            self.strategies["tag"] = TagSearchStrategy(db, keys, config)
    
    def search(
        self,
        query: str,
        strategy_names: List[str] = None,
        k: int = 20,
        filters: SearchFilters = None,
        llm_rerank: bool = False,
        llm_rerank_top_n: int = 50,
        strategy_queries: Dict[str, str] = None,
        strategy_context: Dict[str, Any] = None
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
        # Default to FTS + embedding + rewrite (combined mode)
        if strategy_names is None:
            strategy_names = ["fts"]
            if "embedding" in self.strategies:
                strategy_names.append("embedding")
            if "rewrite" in self.strategies:
                strategy_names.append("rewrite")
            if "entity" in self.strategies:
                strategy_names.append("entity")
            if "tag" in self.strategies:
                strategy_names.append("tag")
        
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

        # Rewrite/entity unification: make ONE rewrite LLM call up front and
        # share its output with the rewrite + entity strategies (single source of
        # query derivation). Inert unless enabled with a key and 'rewrite' active;
        # callers may also pass a precomputed strategy_context to override.
        if strategy_context is None:
            strategy_context = self._build_strategy_context(query, active_strategies)

        # Execute strategies in parallel
        all_results = self._execute_parallel(query, active_strategies, k * 2, filters, strategy_queries, strategy_context)
        time_logger.info(f"[HYBRID] Strategy results: {[(name, len(r)) for name, r in zip(active_strategies, all_results)]}")
        
        # Merge using RRF. Per-strategy weights (W-A) let us trust some
        # strategies more than others (e.g. embedding > fts); an empty mapping
        # (the default) reproduces plain unweighted RRF exactly.
        merged_k = llm_rerank_top_n if llm_rerank else k
        merged = merge_results_rrf(
            all_results,
            k=merged_k,
            strategy_weights=getattr(self.config, "rrf_strategy_weights", None),
        )
        time_logger.info(f"[HYBRID] Merged results: {len(merged)}")

        # Post-fusion recency + confidence re-weight (Workstream C). No-op when
        # w_recency == w_confidence == 0 (the default), so ranking is unchanged
        # unless the weights are tuned.
        merged = apply_recency_confidence_rerank(merged, self.config)
        
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
        filters: SearchFilters,
        strategy_queries: Dict[str, str] = None,
        strategy_context: Dict[str, Any] = None
    ) -> List[List[SearchResult]]:
        """
        Execute multiple strategies in parallel.
        
        Args:
            query: Search query.
            strategy_names: Strategies to execute.
            k: Results per strategy.
            filters: Filters to apply.
            strategy_queries: Optional per-strategy query overrides; a strategy
                absent from the map uses ``query``. ``None`` => every strategy
                uses ``query`` (unchanged behavior).
            strategy_context: Optional shared, precomputed inputs from the single
                rewrite call — ``precomputed_rewrite_metadata`` (consumed by the
                rewrite strategy to skip its LLM call), ``entity_surface_forms``
                and ``entity_query_embedding`` (consumed by the entity strategy).
                Absent keys => each strategy uses its own path (unchanged).
            
        Returns:
            List of result lists from each strategy.
        """
        def _query_for(name: str) -> str:
            if strategy_queries and name in strategy_queries:
                return strategy_queries[name]
            return query

        ctx = strategy_context or {}

        def _search(name: str, strategy, q: str) -> List[SearchResult]:
            """Call strategy.search, passing shared-context kwargs only to the
            enhanced strategies that accept them (keeps the base interface clean)."""
            if name == "rewrite" and ctx.get("precomputed_rewrite_metadata") is not None:
                return strategy.search(
                    q, k, filters,
                    precomputed_metadata=ctx["precomputed_rewrite_metadata"],
                )
            if name == "entity" and (
                ctx.get("entity_surface_forms") is not None
                or ctx.get("entity_query_embedding") is not None
            ):
                return strategy.search(
                    q, k, filters,
                    surface_forms=ctx.get("entity_surface_forms"),
                    query_embedding=ctx.get("entity_query_embedding"),
                )
            if name == "tag" and (
                ctx.get("tag_names") is not None
                or ctx.get("tag_query_embedding") is not None
            ):
                return strategy.search(
                    q, k, filters,
                    tag_names=ctx.get("tag_names"),
                    query_embedding=ctx.get("tag_query_embedding"),
                )
            return strategy.search(q, k, filters)

        if len(strategy_names) == 1:
            # Single strategy, no parallelization needed
            name = strategy_names[0]
            strategy = self.strategies[name]
            return [_search(name, strategy, _query_for(name))]
        
        def run_strategy(name: str) -> List[SearchResult]:
            try:
                time_logger.info(f"[HYBRID] Running strategy: {name}")
                strategy = self.strategies[name]
                results = _search(name, strategy, _query_for(name))
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

    def _build_strategy_context(
        self,
        query: str,
        active_strategies: List[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Make ONE rewrite LLM call and package its output for sharing.

        Returns a context dict with the precomputed RewriteMetadata (so the
        rewrite strategy skips its own LLM call) and — when the entity strategy
        is active and ``entity_use_rewrite_entities`` is set — the LLM-named
        entities (and a reusable query vector of the rewrite's embedding_query)
        for the entity strategy.

        Returns ``None`` (the inert path) when disabled, no API key is present,
        or 'rewrite' is not an active strategy — leaving every strategy on its
        own path (current behavior). Never raises: any failure degrades to None.
        """
        if not getattr(self.config, "rewrite_is_query_source", True):
            return None
        if "rewrite" not in active_strategies or "rewrite" not in self.strategies:
            return None
        if not self.keys.get("OPENROUTER_API_KEY"):
            return None

        rewrite = self.strategies["rewrite"]
        try:
            # The single source-of-truth LLM call.
            _, metadata = rewrite._rewrite_query(query)
        except Exception as e:  # pragma: no cover - defensive
            time_logger.warning(f"[HYBRID] rewrite metadata precompute failed: {e}")
            return None

        context: Dict[str, Any] = {"precomputed_rewrite_metadata": metadata}

        # Feed the higher-quality LLM entities to the entity strategy (capped
        # downstream by entity_strategy_max_entities). Only when entities were
        # actually named, so entity-free queries add no extra work.
        if (
            "entity" in active_strategies
            and getattr(self.config, "entity_use_rewrite_entities", True)
            and getattr(metadata, "extracted_entities", None)
        ):
            context["entity_surface_forms"] = list(metadata.extracted_entities)
            # Reuse one query vector (of the semantic embedding_query) for entity
            # ranking instead of a separate raw-query embedding call. Best-effort.
            emb = self._embed_query(getattr(metadata, "embedding_query", "") or query)
            if emb is not None:
                context["entity_query_embedding"] = emb

        # W-D: feed the rewrite LLM's category tags to the tag strategy (capped
        # downstream by tag_strategy_max_tags). Only when tags were actually
        # suggested, so tag-free queries add no extra work. Reuse the entity
        # strategy's query vector when it was already computed (one embed call).
        if (
            "tag" in active_strategies
            and getattr(self.config, "tag_use_rewrite_tags", True)
            and getattr(metadata, "extracted_tags", None)
        ):
            context["tag_names"] = list(metadata.extracted_tags)
            tag_emb = context.get("entity_query_embedding")
            if tag_emb is None:
                tag_emb = self._embed_query(
                    getattr(metadata, "embedding_query", "") or query
                )
            if tag_emb is not None:
                context["tag_query_embedding"] = tag_emb

        return context

    def _embed_query(self, text: str):
        """Best-effort query embedding for reuse; returns None on any failure."""
        if not text or not self.keys.get("OPENROUTER_API_KEY"):
            return None
        if not getattr(self.config, "embedding_enabled", True):
            return None
        try:
            from code_common.call_llm import get_query_embedding
            emb = get_query_embedding(text, self.keys)
            return emb if emb is not None else None
        except Exception:  # pragma: no cover - defensive
            return None

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

    def set_overview_context(self, overview_context: str):
        """Pass overview context to the rewrite strategy for domain-aware expansion."""
        if "rewrite" in self.strategies:
            self.strategies["rewrite"].set_overview_context(overview_context)
