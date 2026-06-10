"""
Entity-linked retrieval strategy (Workstream W-C).

``EntitySearchStrategy`` participates in hybrid RRF fusion as another ranked
list. It resolves named entities mentioned in the query, pulls the claims those
entities are linked to (honoring the same status filter as the other
strategies, so compaction-archived / superseded / expired claims are not
resurfaced), ranks them by semantic fit to the query, and returns the top-N.

Why a separate retrieval list rather than a post-hoc boost: a dedicated list
also *introduces* entity-linked claims that literal/semantic search missed
entirely (higher recall for named entities), and RRF gives the "found by both
embedding and entity link => rank higher" boost for free while de-duplicating
by ``claim_id`` automatically.

Design notes:
- Entity resolution uses exact (case-insensitive) name match plus, when
  ``config.entity_alias_match`` is set, ``meta_json.aliases`` (W6). Surface
  forms are extracted from the query with a cheap capitalized-span / quoted-span
  heuristic; exact DB matching makes the loose extraction self-filtering
  (non-entity capitalized words simply resolve to nothing).
- Ranking reuses the cached per-claim embeddings (``EmbeddingStore``). When no
  query embedding is available (no API key / embeddings disabled / cold cache)
  the strategy degrades gracefully to the recency order returned by
  ``EntityCRUD.resolve_claims`` instead of blocking on synchronous embedding.
- RRF consumes only rank *order*, so the exact score values here are
  informational; correctness depends on the returned ordering.
"""

import json
import logging
import re
from typing import Dict, List, Optional

import numpy as np

from .base import SearchStrategy, SearchFilters, SearchResult
from .embedding_search import EmbeddingStore
from ..config import PKBConfig
from ..crud.entities import EntityCRUD
from ..database import PKBDatabase
from ..models import Claim

logger = logging.getLogger(__name__)

try:
    from common import time_logger
except ImportError:  # pragma: no cover - fallback when common is unavailable
    time_logger = logger

# Capitalized multi-word spans (e.g. "Acme Corp", "Project Atlas") and quoted
# spans are treated as candidate entity surface forms.
_CAP_SPAN = re.compile(r"[A-Z][\w&.'\-]*(?:\s+[A-Z][\w&.'\-]*)*")
_QUOTED = re.compile(r"\"([^\"]+)\"|'([^']+)'")


class EntitySearchStrategy(SearchStrategy):
    """Retrieve claims linked to entities named in the query."""

    def __init__(self, db: PKBDatabase, keys: Dict[str, str], config: PKBConfig):
        """
        Args:
            db: PKBDatabase instance.
            keys: Dict with OPENROUTER_API_KEY (optional; the strategy works
                without it, falling back to recency ordering).
            config: PKBConfig with entity_strategy_* settings.
        """
        self.db = db
        self.keys = keys
        self.config = config
        self.store = EmbeddingStore(db, keys, config)

    def name(self) -> str:
        return "entity"

    def search(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None,
        surface_forms: Optional[List[str]] = None,
        query_embedding: Optional[np.ndarray] = None,
    ) -> List[SearchResult]:
        """
        Resolve query entities, pull their status-filtered linked claims, rank
        by semantic fit, and return the top-N as ``source="entity"`` results.

        ``surface_forms`` lets the orchestrator supply higher-quality entity
        names from the rewrite LLM (instead of the regex heuristic);
        ``query_embedding`` lets it supply an already-computed query vector
        (e.g. of the rewrite's ``embedding_query``) so ranking does not make a
        second embedding call. Both are best-effort: ``None`` => current
        behavior (regex extraction / self-computed embedding).

        Returns an empty list (an RRF no-op) when the strategy is disabled, the
        query is empty, or no entity resolves — so entity-free queries are
        unaffected.
        """
        filters = filters or SearchFilters()
        if not getattr(self.config, "entity_strategy_enabled", True):
            return []
        if not query or not query.strip():
            return []

        entity_ids = self._resolve_entity_ids(query, filters, surface_forms=surface_forms)
        if not entity_ids:
            return []

        top_n = max(1, int(getattr(self.config, "entity_strategy_top_n", 5)))
        ent_crud = EntityCRUD(self.db, user_email=filters.user_email)
        per_entity_limit = max(top_n * 4, 20)

        # Pull claims via resolve_claims, which already applies the status
        # filter (default active + contested) and user scope — this is what
        # keeps compaction-archived/superseded/expired claims out.
        claims_by_id: Dict[str, Claim] = {}
        for entity_id in entity_ids:
            try:
                for claim in ent_crud.resolve_claims(
                    entity_id, statuses=filters.statuses, limit=per_entity_limit
                ):
                    claims_by_id.setdefault(claim.claim_id, claim)
            except Exception as exc:  # pragma: no cover - defensive
                time_logger.debug(
                    f"[ENTITY] resolve_claims failed for {entity_id}: {exc}"
                )

        if not claims_by_id:
            return []

        ranked = self._rank(query, list(claims_by_id.values()), query_emb=query_embedding)
        matched = sorted(entity_ids)
        results: List[SearchResult] = []
        for claim, score in ranked[:top_n]:
            results.append(
                SearchResult.from_claim(
                    claim=claim,
                    score=score,
                    source=self.name(),
                    metadata={"matched_entities": matched},
                )
            )
        time_logger.info(
            f"[ENTITY] {len(results)} results from {len(matched)} entities, "
            f"{len(claims_by_id)} candidate claims"
        )
        return results

    # ------------------------------------------------------------------ #
    # Entity resolution
    # ------------------------------------------------------------------ #
    def _resolve_entity_ids(
        self,
        query: str,
        filters: SearchFilters,
        surface_forms: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Resolve up to ``entity_strategy_max_entities`` entity ids.

        ``surface_forms`` lets a caller (e.g. the rewrite strategy) supply
        higher-quality names from its LLM call instead of the regex heuristic;
        when None they are extracted from ``query``. Resolution preserves
        first-seen order and is capped to bound candidate-claim fan-out
        (anti-flooding).
        """
        forms = surface_forms if surface_forms is not None else self._extract_surface_forms(query)
        forms = [f.strip() for f in forms if f and f.strip()]
        if not forms:
            return []

        max_entities = max(1, int(getattr(self.config, "entity_strategy_max_entities", 5)))
        ordered: List[str] = []
        seen = set()

        def _add(eids: List[str]) -> None:
            for eid in eids:
                if eid not in seen:
                    seen.add(eid)
                    ordered.append(eid)

        for form in forms:
            _add(self._match_by_name(form, filters.user_email))
            if len(ordered) >= max_entities:
                return ordered[:max_entities]

        if getattr(self.config, "entity_alias_match", True):
            _add(self._match_by_alias(forms, filters.user_email))
        return ordered[:max_entities]

    @staticmethod
    def _extract_surface_forms(query: str) -> List[str]:
        """Extract candidate entity names in first-seen order (deduped, case-insensitive)."""
        forms: List[str] = []
        seen = set()

        def _add(span: Optional[str]) -> None:
            span = (span or "").strip()
            if len(span) >= 2 and span.lower() not in seen:
                seen.add(span.lower())
                forms.append(span)

        for m in _QUOTED.finditer(query):
            _add(m.group(1) or m.group(2))
        for m in _CAP_SPAN.finditer(query):
            _add(m.group(0))
        return forms

    def _match_by_name(self, form: str, user_email: Optional[str]) -> List[str]:
        if user_email:
            rows = self.db.fetchall(
                "SELECT entity_id FROM entities WHERE name = ? COLLATE NOCASE "
                "AND (user_email = ? OR user_email IS NULL)",
                (form, user_email),
            )
        else:
            rows = self.db.fetchall(
                "SELECT entity_id FROM entities WHERE name = ? COLLATE NOCASE",
                (form,),
            )
        return [row["entity_id"] for row in rows]

    def _match_by_alias(
        self, forms: List[str], user_email: Optional[str]
    ) -> List[str]:
        lowered = {f.lower() for f in forms}
        if user_email:
            rows = self.db.fetchall(
                "SELECT entity_id, meta_json FROM entities "
                "WHERE meta_json LIKE '%aliases%' "
                "AND (user_email = ? OR user_email IS NULL) LIMIT 1000",
                (user_email,),
            )
        else:
            rows = self.db.fetchall(
                "SELECT entity_id, meta_json FROM entities "
                "WHERE meta_json LIKE '%aliases%' LIMIT 1000",
            )
        matched = []
        for row in rows:
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except (ValueError, TypeError):
                continue
            if not isinstance(meta, dict):
                continue
            aliases = meta.get("aliases") or []
            if not isinstance(aliases, list):
                continue
            if any(isinstance(a, str) and a.lower() in lowered for a in aliases):
                matched.append(row["entity_id"])
        return matched

    # ------------------------------------------------------------------ #
    # Ranking
    # ------------------------------------------------------------------ #
    def _rank(
        self,
        query: str,
        candidates: List[Claim],
        query_emb: Optional[np.ndarray] = None,
    ) -> List[tuple]:
        """
        Order candidates by cosine similarity to the query embedding when one is
        available; otherwise preserve the recency order from resolve_claims.
        Claims without a cached embedding sort after the scored ones.

        ``query_emb`` may be supplied by the caller (orchestrator) to reuse an
        already-computed query vector; when None it is computed from ``query``.
        """
        if query_emb is None:
            query_emb = self._query_embedding(query)
        if query_emb is None:
            return [(claim, 0.0) for claim in candidates]

        scored: List[tuple] = []
        unscored: List[Claim] = []
        for claim in candidates:
            emb = self.store.get_embedding(
                claim.claim_id, expected_model=self.config.embedding_model
            )
            if emb is None:
                unscored.append(claim)
            else:
                scored.append((claim, float(self._cosine(query_emb, emb))))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored + [(claim, 0.0) for claim in unscored]

    def _query_embedding(self, query: str) -> Optional[np.ndarray]:
        if not self.keys.get("OPENROUTER_API_KEY"):
            return None
        if not getattr(self.config, "embedding_enabled", True):
            return None
        try:
            from code_common.call_llm import get_query_embedding
        except ImportError:
            return None
        try:
            emb = get_query_embedding(query, self.keys)
            return emb if emb is not None else None
        except Exception as exc:  # pragma: no cover - defensive
            time_logger.debug(f"[ENTITY] query embedding unavailable: {exc}")
            return None

    @staticmethod
    def _cosine(vec1: np.ndarray, vec2: np.ndarray) -> float:
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))
