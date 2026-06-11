"""
Tag-linked retrieval strategy (Workstream W-D).

``TagSearchStrategy`` is the symmetric counterpart of ``EntitySearchStrategy``:
where the entity strategy resolves *named things* and pulls their linked claims,
this one resolves *category tags* (health, work, family, ...) and pulls claims
linked to those tags via the ``claim_tags`` join table — traversing the tag
hierarchy (``TagCRUD.resolve_claims``) so a parent tag also surfaces claims
under its descendant tags. It participates in hybrid RRF fusion as another
ranked list.

Why a separate retrieval list: tags are a coarse, curated *category* axis that
is orthogonal to lexical (FTS) and semantic (embedding) match and to named
entities. A dedicated list *introduces* thematically-related claims that share
no query tokens, are no strong paraphrase, and name no entity (e.g. the query
"how are my fitness goals" matching a claim tagged ``health`` like "switched to
a Mediterranean diet"), and RRF gives the "found by tag *and* embedding => rank
higher" boost for free while de-duplicating by ``claim_id``.

Design notes (deliberately mirror ``entity_search``):
- INERT by default: gated on ``config.tag_strategy_enabled`` (default False), so
  it is not even registered until explicitly turned on and eval-gated. Returns
  an empty list (an RRF no-op) when disabled, the query is empty, or no tag
  resolves — tag-free queries are unaffected.
- Tag resolution uses exact (case-insensitive) name match against the user's
  tags. The orchestrator can supply higher-quality category tags from the single
  rewrite LLM call (``tag_names``); otherwise matching query tokens are used,
  which is self-filtering (non-tag tokens resolve to nothing).
- Ranking reuses the cached per-claim embeddings (``EmbeddingStore``). When no
  query embedding is available it degrades gracefully to the recency order
  returned by ``TagCRUD.resolve_claims`` instead of blocking on a synchronous
  embedding call.
- RRF consumes only rank *order*, so the exact score values here are
  informational; correctness depends on the returned ordering.
"""

import logging
import re
from typing import Dict, List, Optional

import numpy as np

from .base import SearchStrategy, SearchFilters, SearchResult
from .embedding_search import EmbeddingStore
from ..config import PKBConfig
from ..crud.tags import TagCRUD
from ..database import PKBDatabase
from ..models import Claim

logger = logging.getLogger(__name__)

try:
    from common import time_logger
except ImportError:  # pragma: no cover - fallback when common is unavailable
    time_logger = logger

# Lowercased word tokens used as candidate tag names when no rewrite tags are
# supplied. Exact DB matching against the user's tags makes this self-filtering.
_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")


class TagSearchStrategy(SearchStrategy):
    """Retrieve claims linked to category tags inferred from the query."""

    def __init__(self, db: PKBDatabase, keys: Dict[str, str], config: PKBConfig):
        """
        Args:
            db: PKBDatabase instance.
            keys: Dict with OPENROUTER_API_KEY (optional; the strategy works
                without it, falling back to recency ordering).
            config: PKBConfig with tag_strategy_* settings.
        """
        self.db = db
        self.keys = keys
        self.config = config
        self.store = EmbeddingStore(db, keys, config)

    def name(self) -> str:
        return "tag"

    def search(
        self,
        query: str,
        k: int = 20,
        filters: SearchFilters = None,
        tag_names: Optional[List[str]] = None,
        query_embedding: Optional[np.ndarray] = None,
    ) -> List[SearchResult]:
        """
        Resolve query tags, pull their status-filtered linked claims (hierarchy
        included), rank by semantic fit, and return the top-N as
        ``source="tag"`` results.

        ``tag_names`` lets the orchestrator supply category tags from the rewrite
        LLM (instead of the token heuristic); ``query_embedding`` lets it supply
        an already-computed query vector so ranking does not make a second
        embedding call. Both are best-effort: ``None`` => self-extract tokens /
        self-compute the embedding.

        Returns an empty list (an RRF no-op) when the strategy is disabled, the
        query is empty, or no tag resolves — so tag-free queries are unaffected.
        """
        filters = filters or SearchFilters()
        if not getattr(self.config, "tag_strategy_enabled", False):
            return []
        if not query or not query.strip():
            return []

        tag_ids = self._resolve_tag_ids(query, filters, tag_names=tag_names)
        if not tag_ids:
            return []

        top_n = max(1, int(getattr(self.config, "tag_strategy_top_n", 5)))
        max_depth = max(0, int(getattr(self.config, "tag_strategy_max_depth", 10)))
        tag_crud = TagCRUD(self.db, user_email=filters.user_email)
        per_tag_limit = max(top_n * 4, 20)

        # Pull claims via resolve_claims, which already applies the status filter
        # (default active + contested) and user scope, and traverses the tag
        # hierarchy — this is what keeps archived/superseded/expired claims out.
        claims_by_id: Dict[str, Claim] = {}
        for tag_id in tag_ids:
            try:
                for claim in tag_crud.resolve_claims(
                    tag_id,
                    statuses=filters.statuses,
                    max_depth=max_depth,
                    limit=per_tag_limit,
                ):
                    claims_by_id.setdefault(claim.claim_id, claim)
            except Exception as exc:  # pragma: no cover - defensive
                time_logger.debug(
                    f"[TAG] resolve_claims failed for {tag_id}: {exc}"
                )

        if not claims_by_id:
            return []

        ranked = self._rank(query, list(claims_by_id.values()), query_emb=query_embedding)
        matched = sorted(tag_ids)
        results: List[SearchResult] = []
        for claim, score in ranked[:top_n]:
            results.append(
                SearchResult.from_claim(
                    claim=claim,
                    score=score,
                    source=self.name(),
                    metadata={"matched_tags": matched},
                )
            )
        time_logger.info(
            f"[TAG] {len(results)} results from {len(matched)} tags, "
            f"{len(claims_by_id)} candidate claims"
        )
        return results

    # ------------------------------------------------------------------ #
    # Tag resolution
    # ------------------------------------------------------------------ #
    def _resolve_tag_ids(
        self,
        query: str,
        filters: SearchFilters,
        tag_names: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Resolve up to ``tag_strategy_max_tags`` tag ids by exact name match.

        ``tag_names`` lets a caller (e.g. the rewrite strategy) supply category
        tags from its LLM call instead of the token heuristic; when None they are
        extracted from ``query``. Resolution preserves first-seen order and is
        capped to bound candidate-claim fan-out (anti-flooding).
        """
        forms = tag_names if tag_names is not None else self._extract_tag_forms(query)
        forms = [f.strip() for f in forms if f and f.strip()]
        if not forms:
            return []

        max_tags = max(1, int(getattr(self.config, "tag_strategy_max_tags", 5)))
        ordered: List[str] = []
        seen = set()

        for form in forms:
            for tid in self._match_by_name(form, filters.user_email):
                if tid not in seen:
                    seen.add(tid)
                    ordered.append(tid)
            if len(ordered) >= max_tags:
                break
        return ordered[:max_tags]

    @staticmethod
    def _extract_tag_forms(query: str) -> List[str]:
        """Candidate tag names from query word tokens (deduped, lowercased)."""
        forms: List[str] = []
        seen = set()
        for m in _WORD.finditer(query):
            tok = m.group(0).lower()
            if tok not in seen:
                seen.add(tok)
                forms.append(tok)
        return forms

    def _match_by_name(self, form: str, user_email: Optional[str]) -> List[str]:
        """Exact (case-insensitive) tag-name match, user-scoped when known."""
        if user_email:
            rows = self.db.fetchall(
                "SELECT tag_id FROM tags WHERE name = ? COLLATE NOCASE "
                "AND (user_email = ? OR user_email IS NULL)",
                (form, user_email),
            )
        else:
            rows = self.db.fetchall(
                "SELECT tag_id FROM tags WHERE name = ? COLLATE NOCASE",
                (form,),
            )
        return [row["tag_id"] for row in rows]

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
            time_logger.debug(f"[TAG] query embedding unavailable: {exc}")
            return None

    @staticmethod
    def _cosine(vec1: np.ndarray, vec2: np.ndarray) -> float:
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))
