"""
Structured API for PKB v0.

StructuredAPI provides a unified interface for all PKB operations:
- Claims: add, edit, delete, get, search
- Notes: add, edit, delete, get, search
- Entities: add, edit, delete, get, search
- Tags: add, edit, delete, get
- Conflicts: create, resolve, ignore

All methods return ActionResult objects with success status,
affected objects, and any warnings/errors.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from ..database import PKBDatabase
from ..config import PKBConfig
from ..models import Claim, Note, Entity, Tag, ConflictSet, Context
from ..constants import ClaimType, ClaimStatus, ContextDomain, EntityType
from ..crud import (
    ClaimCRUD,
    NoteCRUD,
    EntityCRUD,
    TagCRUD,
    ConflictCRUD,
    ContextCRUD,
    TypeCatalogCRUD,
    DomainCatalogCRUD,
)
from ..crud.links import (
    link_claim_entity,
    unlink_claim_entity,
    get_claim_entities,
    link_claim_tag,
    unlink_claim_tag,
    get_claim_tags,
    link_claims,
    get_supersession_head,
    LINK_SUPERSEDES,
)
from ..search import HybridSearchStrategy, SearchFilters, SearchResult
from ..search.notes_search import NotesSearchStrategy
from ..llm_helpers import LLMHelpers

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """
    Result of an API action.

    Attributes:
        success: Whether the action succeeded.
        action: Action that was taken.
        object_type: Type of object affected.
        object_id: ID of primary affected object.
        data: Result data (object, list, etc.).
        warnings: Non-fatal warnings.
        errors: Error messages if failed.
    """

    success: bool
    action: str  # add|edit|delete|search|get|create_conflict|resolve_conflict
    object_type: str  # claim|note|entity|tag|conflict_set
    object_id: Optional[str] = None
    data: Any = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class StructuredAPI:
    """
    Unified API for PKB operations.

    Provides a clean interface for all CRUD and search operations,
    suitable for UI integration and function calling from LLMs.

    Attributes:
        db: PKBDatabase instance.
        keys: API keys for LLM operations.
        config: PKBConfig with settings.
        user_email: Optional user email for multi-user filtering.
        claims: ClaimCRUD instance.
        notes: NoteCRUD instance.
        entities: EntityCRUD instance.
        tags: TagCRUD instance.
        conflicts: ConflictCRUD instance.
        search: HybridSearchStrategy instance.
        llm: LLMHelpers instance.
    """

    def __init__(
        self,
        db: PKBDatabase,
        keys: Dict[str, str],
        config: PKBConfig,
        user_email: Optional[str] = None,
    ):
        """
        Initialize structured API.

        Args:
            db: PKBDatabase instance.
            keys: Dict with OPENROUTER_API_KEY.
            config: PKBConfig with settings.
            user_email: Optional user email for multi-user filtering.
                       If provided, all operations are scoped to this user.
        """
        self.db = db
        self.keys = keys
        self.config = config
        self.user_email = user_email

        # Initialize CRUD instances (scoped to user if provided)
        self.claims = ClaimCRUD(db, user_email=user_email)
        self.notes = NoteCRUD(db, user_email=user_email)
        self.entities = EntityCRUD(db, user_email=user_email)
        self.tags = TagCRUD(db, user_email=user_email)
        self.conflicts = ConflictCRUD(db, user_email=user_email)
        self.contexts = ContextCRUD(db, user_email=user_email)
        self.type_catalog = TypeCatalogCRUD(db, user_email=user_email)
        self.domain_catalog = DomainCatalogCRUD(db, user_email=user_email)

        # Initialize search (we'll pass user_email in search methods)
        self.search_strategy = HybridSearchStrategy(db, keys, config)
        self.notes_search = NotesSearchStrategy(db, keys, config)

        # Initialize LLM helpers
        if keys.get("OPENROUTER_API_KEY"):
            self.llm = LLMHelpers(keys, config)
        else:
            self.llm = None

        # Lazily-initialized embedding cache store (see _get_embedding_store).
        self._embedding_store = None

    def _get_embedding_store(self):
        """
        Lazily construct and cache an EmbeddingStore for the claim embedding
        cache. Returns None when embeddings or the embedding cache are disabled,
        or when no API key is available.
        """
        if not (self.config.embedding_enabled and self.config.embedding_cache_enabled):
            return None
        if not self.keys.get("OPENROUTER_API_KEY"):
            return None
        if self._embedding_store is None:
            from ..search.embedding_search import EmbeddingStore

            self._embedding_store = EmbeddingStore(self.db, self.keys, self.config)
        return self._embedding_store

    def backfill_embeddings(self, context_domain: Optional[str] = None) -> Dict[str, int]:
        """
        Populate the embedding cache for existing active claims that are
        missing a vector (or were embedded with a stale model).

        Intended as a one-off / ops maintenance call after enabling the cache
        or changing the embedding model. Uses EmbeddingStore.ensure_embeddings
        which computes missing embeddings in parallel and stores them.

        Args:
            context_domain: Optional domain filter; when None, backfills all
                active claims for the scoped user.

        Returns:
            Dict with 'total' active claims considered and 'embedded' count
            resolved (cached + newly computed).
        """
        store = self._get_embedding_store()
        if store is None:
            return {"total": 0, "embedded": 0}

        claims = self.claims.get_active(context_domain=context_domain)
        if not claims:
            return {"total": 0, "embedded": 0}

        embeddings = store.ensure_embeddings(claims)
        return {"total": len(claims), "embedded": len(embeddings)}

    def backfill_provenance(self) -> Dict[str, int]:
        """
        Backfill two-axis provenance (channel + derivation) on existing claims
        that predate the provenance feature (Workstream W1).

        Idempotent: only claims whose ``meta_json.source`` lacks a ``derivation``
        are touched. Derivation/channel are inferred from the legacy source via
        ``utils.infer_legacy_provenance`` (manual→stated, else extracted). Writes
        meta_json directly (no embedding recompute, no audit noise).

        Returns dict with ``total`` claims scanned and ``updated`` count.
        """
        import json as _pjson
        from ..utils import parse_meta_json, set_provenance, infer_legacy_provenance

        rows = self.db.fetchall(
            "SELECT claim_id, meta_json FROM claims WHERE "
            "(user_email = ? OR (? IS NULL AND user_email IS NULL))",
            (self.user_email, self.user_email),
        )
        total = len(rows)
        updated = 0
        with self.db.transaction() as conn:
            for row in rows:
                meta = parse_meta_json(row["meta_json"])
                src = meta.get("source")
                if isinstance(src, dict) and src.get("derivation"):
                    continue  # already has provenance
                inferred = infer_legacy_provenance(row["meta_json"])
                set_provenance(
                    meta,
                    channel=inferred["channel"],
                    derivation=inferred["derivation"],
                )
                conn.execute(
                    "UPDATE claims SET meta_json = ? WHERE claim_id = ?",
                    (_pjson.dumps(meta), row["claim_id"]),
                )
                updated += 1
        logger.info(f"Provenance backfill: {updated}/{total} claims updated")
        return {"total": total, "updated": updated}

    @staticmethod
    def _with_curated_origin(meta_json: Optional[str]) -> str:
        """
        Stamp ``meta_json.origin = "curated"`` for user-created entities/tags
        (W5). Preserves any other meta keys and an existing explicit origin.
        """
        import json as _pjson
        from ..utils import parse_meta_json
        from ..constants import MetaJsonKeys

        meta = parse_meta_json(meta_json)
        meta.setdefault(MetaJsonKeys.ORIGIN, MetaJsonKeys.ORIGIN_CURATED)
        return _pjson.dumps(meta)

    def backfill_origin(self) -> Dict[str, int]:
        """
        Backfill ``meta_json.origin`` for existing entities and tags that
        predate the auto/curated distinction (W5). Idempotent: only rows lacking
        an ``origin`` are touched, and they are marked ``curated`` (history is
        treated as user-trusted). Returns counts per object type.
        """
        import json as _pjson
        from ..utils import parse_meta_json
        from ..constants import MetaJsonKeys

        out = {"entities": 0, "tags": 0}
        with self.db.transaction() as conn:
            for table, id_col, key in (
                ("entities", "entity_id", "entities"),
                ("tags", "tag_id", "tags"),
            ):
                rows = self.db.fetchall(
                    f"SELECT {id_col}, meta_json FROM {table}"
                )
                for row in rows:
                    meta = parse_meta_json(row["meta_json"])
                    if meta.get(MetaJsonKeys.ORIGIN):
                        continue
                    meta[MetaJsonKeys.ORIGIN] = MetaJsonKeys.ORIGIN_CURATED
                    conn.execute(
                        f"UPDATE {table} SET meta_json = ? WHERE {id_col} = ?",
                        (_pjson.dumps(meta), row[id_col]),
                    )
                    out[key] += 1
        logger.info(f"Origin backfill: {out}")
        return out

    def for_user(self, user_email: str) -> "StructuredAPI":
        """
        Create a new StructuredAPI instance scoped to a specific user.

        This is useful when you have a shared API instance and need
        to scope operations to a specific user.

        Args:
            user_email: User email to scope operations to.

        Returns:
            New StructuredAPI instance scoped to the user.
        """
        return StructuredAPI(
            db=self.db, keys=self.keys, config=self.config, user_email=user_email
        )

    # =========================================================================
    # Claims API
    # =========================================================================

    def add_claim(
        self,
        statement: str,
        claim_type: str,
        context_domain: str,
        tags: List[str] = None,
        entities: List[Dict] = None,
        auto_extract: bool = True,
        confidence: float = None,
        valid_from: str = None,
        valid_to: str = None,
        meta_json: str = None,
        **kwargs,
    ) -> ActionResult:
        """
        Add a new claim to the knowledge base.

        If user_email is set on this API instance, the claim will
        be automatically scoped to that user.

        Args:
            statement: The claim text.
            claim_type: Type from ClaimType enum.
            context_domain: Domain from ContextDomain enum.
            tags: List of tag names to link.
            entities: List of entity dicts {type, name, role}.
            auto_extract: Auto-extract tags/entities using LLM.
            confidence: Optional confidence score (0.0-1.0).
            valid_from: Start of validity period.
            valid_to: End of validity period.
            meta_json: Additional metadata as JSON string.

        Returns:
            ActionResult with created claim.
        """
        tags = tags or []
        entities = entities or []
        warnings = []

        # Enforce valid_to for time-bound claim types
        if claim_type in ("task", "reminder") and not valid_to:
            return ActionResult(
                success=False,
                action="add",
                object_type="claim",
                errors=[
                    "valid_to is required for task and reminder claims. "
                    "Please provide a deadline date (ISO 8601 format, e.g. '2025-07-20')."
                ],
            )

        try:
            # G2: combined-enrichment path. When enabled, derive
            # type/tags/entities/possible_questions from ONE combined LLM call
            # (analyze_claim_statement) instead of extract_single's 4-5 calls +
            # a separate generate_possible_questions call. A precomputed
            # analysis (e.g. from add_claims_bulk's parallel batch_analyze) can
            # be injected via the private `_analysis` kwarg to skip the call.
            analysis_questions = None
            precomputed = kwargs.get("_analysis")
            use_combined = (
                getattr(self.config, "combined_enrichment", True)
                or precomputed is not None
            )

            # Auto-extract if enabled and LLM available
            if auto_extract and (self.llm or precomputed is not None):
                if use_combined:
                    analysis = precomputed
                    if analysis is None:
                        analysis = self.llm.analyze_claim_statement(statement)
                    if not tags:
                        tags = list(analysis.tags or [])
                    if not entities:
                        entities = list(analysis.entities or [])
                    if claim_type == "observation" and analysis.claim_type:
                        claim_type = analysis.claim_type
                    # Reuse the questions from the same call (no extra LLM hit).
                    analysis_questions = analysis.possible_questions or None
                elif self.llm:
                    extraction = self.llm.extract_single(statement, context_domain)

                    # Merge extracted tags with provided
                    if not tags:
                        tags = extraction.tags

                    # Merge extracted entities with provided
                    if not entities:
                        entities = extraction.entities

                    # Use extracted type if not provided or generic
                    if claim_type == "observation":
                        claim_type = extraction.claim_type

            # Similarity / duplicate check (shared by both enrichment paths).
            if auto_extract and self.llm:
                # Check for similar claims
                existing = self.claims.get_active(context_domain=context_domain)

                # Cap the scan with a configurable limit (<= 0 means scan all).
                scan_limit = self.config.conflict_scan_limit
                if scan_limit and scan_limit > 0:
                    existing = existing[:scan_limit]

                # Reuse persisted embeddings for the existing claims instead of
                # recomputing them on every add. ensure_embeddings fills the
                # cache for any that are missing (or were built with a stale
                # model) and returns a claim_id -> vector map.
                cached_embeddings = None
                store = self._get_embedding_store()
                if store is not None and existing:
                    try:
                        cached_embeddings = store.ensure_embeddings(existing)
                    except Exception as e:
                        logger.warning(f"Embedding cache lookup failed: {e}")
                        cached_embeddings = None

                similar = self.llm.check_similarity(
                    statement, existing, cached_embeddings=cached_embeddings
                )

                if similar:
                    dup_mode = (self.config.reinforce_on_duplicate or "off").lower()
                    first_duplicate = None
                    for claim, sim, relation in similar[:3]:
                        if relation == "duplicate":
                            if first_duplicate is None:
                                first_duplicate = (claim, sim)
                            warnings.append(
                                f"Very similar claim exists: {claim.claim_id[:8]} ({sim:.2f})"
                            )
                        elif relation == "contradicts":
                            warnings.append(
                                f"May contradict claim: {claim.claim_id[:8]} ({sim:.2f})"
                            )

                    # H3 primary hook: an explicit restatement is the strongest
                    # reinforcement signal. When enabled, reinforce the existing
                    # near-duplicate instead of accumulating a redundant claim.
                    # Gated off by default (reinforce_on_duplicate="off") so this
                    # is opt-in and preserves today's create-anyway behavior.
                    if first_duplicate is not None and dup_mode in (
                        "reinforce",
                        "reinforce+warn",
                    ):
                        dup_claim, dup_sim = first_duplicate
                        reinforced = self.reinforce_claim(dup_claim.claim_id)
                        if reinforced.success:
                            reinforced.warnings = list(reinforced.warnings or []) + [
                                f"Reinforced existing claim {dup_claim.claim_id[:8]} "
                                f"(similarity {dup_sim:.2f}) instead of adding a duplicate"
                            ]
                            if dup_mode == "reinforce+warn":
                                reinforced.warnings += warnings
                            return reinforced
                        # Reinforcement refused (e.g. contested/superseded per the
                        # H4 safeguard): fall through to normal creation with the
                        # similarity warnings already recorded.

            # Parse multi-type/domain arrays.  The frontend may send them as
            # JSON strings (e.g. '["fact","preference"]') or as Python lists.
            import json as _json

            raw_types = kwargs.get("claim_types")
            raw_domains = kwargs.get("context_domains")
            claim_types_list = None
            context_domains_list = None
            if raw_types:
                claim_types_list = (
                    _json.loads(raw_types) if isinstance(raw_types, str) else raw_types
                )
            if raw_domains:
                context_domains_list = (
                    _json.loads(raw_domains)
                    if isinstance(raw_domains, str)
                    else raw_domains
                )

            # Handle possible_questions: user-provided or auto-generated
            raw_pq = kwargs.get("possible_questions")
            possible_questions_json = None
            if raw_pq:
                # User provided: could be JSON string or list
                if isinstance(raw_pq, str):
                    possible_questions_json = raw_pq  # already JSON string
                elif isinstance(raw_pq, list):
                    possible_questions_json = _json.dumps(raw_pq)
            elif analysis_questions:
                # G2: reuse the questions produced by the single combined
                # analyze_claim_statement call — no extra LLM round-trip.
                possible_questions_json = _json.dumps(analysis_questions)
            elif auto_extract and self.llm and not use_combined:
                # Legacy path only: a separate question-generation LLM call.
                try:
                    questions = self.llm.generate_possible_questions(
                        statement, claim_type
                    )
                    if questions:
                        possible_questions_json = _json.dumps(questions)
                except Exception as e:
                    logger.warning(f"Failed to auto-generate questions: {e}")

            # Provenance (Workstream E1/E2): when a caller (e.g. the conversation
            # distiller) supplies the originating conversation/message, record it
            # in meta_json under `source` so the claim can answer "why do I know
            # this?", and tag it `source:conversation`. Stored in meta_json (not
            # a column) to match the existing `pinned` / text-ingestion source
            # conventions and avoid a schema migration.
            # Provenance (two-axis: channel + derivation). channel = where the
            # claim entered (manual|chat|ingest|import); derivation = epistemic
            # basis (stated|extracted|inferred). Always recorded under
            # meta_json.source (no schema migration). E1/E2 conversation/message
            # provenance is folded in when supplied by the distiller.
            source_conversation_id = kwargs.get("source_conversation_id")
            source_message_id = kwargs.get("source_message_id")
            source_type = kwargs.get("source_type")
            channel = kwargs.get("channel") or source_type
            derivation = kwargs.get("derivation")

            from ..constants import ProvenanceChannel, Derivation
            from ..utils import set_provenance as _set_prov

            # Default channel: chat when distilled, else manual.
            if not channel:
                channel = (
                    ProvenanceChannel.CHAT.value
                    if (source_conversation_id or source_message_id)
                    else ProvenanceChannel.MANUAL.value
                )
            norm_channel = ProvenanceChannel.normalize(channel)
            # Default derivation: stated for manual, extracted otherwise.
            if not Derivation.is_valid(derivation or ""):
                derivation = (
                    Derivation.STATED.value
                    if norm_channel == ProvenanceChannel.MANUAL.value
                    else Derivation.EXTRACTED.value
                )

            # Legacy free-form `type` (kept for backward compatibility): an
            # explicit source_type wins; distilled-without-type stays the
            # historical "chat_distillation"; otherwise mirror the channel.
            if source_type:
                legacy_type = source_type
            elif source_conversation_id or source_message_id:
                legacy_type = "chat_distillation"
            else:
                legacy_type = norm_channel

            import json as _pjson
            _meta = {}
            if meta_json:
                try:
                    _meta = _pjson.loads(meta_json)
                except (ValueError, TypeError):
                    _meta = {}
            _set_prov(
                _meta,
                channel=norm_channel,
                derivation=derivation,
                legacy_type=legacy_type,
                conversation_id=source_conversation_id,
                message_id=source_message_id,
            )
            meta_json = _pjson.dumps(_meta)
            # E2: provenance tag so distilled claims are filterable.
            if source_conversation_id and "source:conversation" not in tags:
                tags = list(tags) + ["source:conversation"]

            # Inferred claims are trusted less: cap their confidence.
            if derivation == Derivation.INFERRED.value:
                _cap = getattr(self.config, "inferred_confidence_cap", 0.4)
                _base = confidence if confidence is not None else getattr(
                    self.config, "default_confidence", 0.5
                )
                confidence = min(_base, _cap)

            # Create claim (user_email is applied by ClaimCRUD if set)
            claim = Claim.create(
                statement=statement,
                claim_type=claim_type,
                context_domain=context_domain,
                user_email=self.user_email,
                confidence=confidence,
                valid_from=valid_from,
                valid_to=valid_to,
                meta_json=meta_json,
                claim_types=claim_types_list,
                context_domains=context_domains_list,
                possible_questions=possible_questions_json,
            )

            # Add to database
            claim = self.claims.add(claim, tags=tags, entities=entities)

            # Populate the embedding cache for the new claim so future
            # similarity checks and embedding search reuse it (best-effort).
            store = self._get_embedding_store()
            if store is not None:
                try:
                    store.compute_and_store(claim)
                except Exception as e:
                    logger.warning(
                        f"Failed to cache embedding for {claim.claim_id}: {e}"
                    )

            # D1: optional explicit supersession. When the caller knows this new
            # claim replaces existing one(s), `supersedes` carries the old
            # claim_id (or a list); link them and retire the old claim(s).
            supersedes = kwargs.get("supersedes")
            if supersedes:
                old_ids = supersedes if isinstance(supersedes, list) else [supersedes]
                for old_id in old_ids:
                    if not old_id:
                        continue
                    sres = self.supersede_claim(claim.claim_id, old_id)
                    if sres.success:
                        warnings.append(
                            f"Superseded claim {str(old_id)[:8]}"
                        )
                    else:
                        warnings.extend(sres.errors or [])

            self._record_audit("add", "claim", claim.claim_id)
            return ActionResult(
                success=True,
                action="add",
                object_type="claim",
                object_id=claim.claim_id,
                data=claim,
                warnings=warnings,
            )

        except Exception as e:
            logger.error(f"Failed to add claim: {e}")
            return ActionResult(
                success=False, action="add", object_type="claim", errors=[str(e)]
            )

    def edit_claim(self, claim_id: str, **patch) -> ActionResult:
        """
        Edit an existing claim.

        If the claim has no friendly_id and none is provided in the patch,
        one is auto-generated (using heuristic).

        If the claim has no possible_questions and none are provided,
        they are auto-generated via LLM (if available).

        Args:
            claim_id: ID of claim to edit.
            **patch: Fields to update.

        Returns:
            ActionResult with updated claim.
        """
        try:
            # Pre-fetch existing claim to check what needs auto-generation
            existing = self.claims.get(claim_id)
            if existing and self.llm:
                stmt = patch.get("statement", existing.statement)
                ctype = patch.get("claim_type", existing.claim_type)

                # Auto-generate possible_questions if claim has none and none provided
                if (
                    not existing.possible_questions
                    and "possible_questions" not in patch
                ):
                    try:
                        import json as _json

                        questions = self.llm.generate_possible_questions(stmt, ctype)
                        if questions:
                            patch["possible_questions"] = _json.dumps(questions)
                    except Exception as e:
                        logger.warning(
                            f"Failed to auto-generate questions on edit: {e}"
                        )

            claim = self.claims.edit(claim_id, patch)

            if claim:
                # If the statement changed, the cached embedding is stale —
                # recompute it so the cache stays consistent (best-effort).
                if "statement" in patch:
                    store = self._get_embedding_store()
                    if store is not None:
                        try:
                            store.compute_and_store(claim)
                        except Exception as e:
                            logger.warning(
                                f"Failed to refresh embedding for {claim_id}: {e}"
                            )

                self._record_audit(
                    "edit", "claim", claim_id, detail={"fields": list(patch.keys())}
                )
                return ActionResult(
                    success=True,
                    action="edit",
                    object_type="claim",
                    object_id=claim_id,
                    data=claim,
                )
            else:
                return ActionResult(
                    success=False,
                    action="edit",
                    object_type="claim",
                    object_id=claim_id,
                    errors=["Claim not found"],
                )

        except Exception as e:
            logger.error(f"Failed to edit claim: {e}")
            return ActionResult(
                success=False,
                action="edit",
                object_type="claim",
                object_id=claim_id,
                errors=[str(e)],
            )

    def delete_claim(self, claim_id: str, mode: str = "retract") -> ActionResult:
        """
        Soft-delete a claim.

        Args:
            claim_id: ID of claim to delete.
            mode: Deletion mode (only "retract" supported).

        Returns:
            ActionResult with retracted claim.
        """
        try:
            claim = self.claims.delete(claim_id, mode)

            if claim:
                self._record_audit("delete", "claim", claim_id, detail={"mode": mode})
                return ActionResult(
                    success=True,
                    action="delete",
                    object_type="claim",
                    object_id=claim_id,
                    data=claim,
                )
            else:
                return ActionResult(
                    success=False,
                    action="delete",
                    object_type="claim",
                    object_id=claim_id,
                    errors=["Claim not found"],
                )

        except Exception as e:
            logger.error(f"Failed to delete claim: {e}")
            return ActionResult(
                success=False,
                action="delete",
                object_type="claim",
                object_id=claim_id,
                errors=[str(e)],
            )

    def get_claim(self, claim_id: str) -> ActionResult:
        """Get a claim by ID."""
        claim = self.claims.get(claim_id)

        if claim:
            return ActionResult(
                success=True,
                action="get",
                object_type="claim",
                object_id=claim_id,
                data=claim,
            )
        else:
            return ActionResult(
                success=False,
                action="get",
                object_type="claim",
                object_id=claim_id,
                errors=["Claim not found"],
            )

    def add_claims_bulk(
        self,
        claims: List[Dict],
        auto_extract: bool = False,
        stop_on_error: bool = False,
    ) -> ActionResult:
        """
        Add multiple claims in a single operation.

        This method allows bulk addition of claims, useful for:
        - Importing memories from text files
        - Bulk manual entry from UI
        - Migration from other systems

        Args:
            claims: List of claim dicts, each containing:
                - statement (required): The claim text
                - claim_type (default: 'fact'): Type of claim
                - context_domain (default: 'personal'): Domain
                - tags (optional): List of tag names
                - entities (optional): List of entity dicts
                - confidence (optional): Confidence score
                - meta_json (optional): Additional metadata
            auto_extract: If True, extract entities/tags for each claim using LLM.
                         Note: This will be slower due to LLM calls per claim.
            stop_on_error: If True, stop at first failure; else continue and report all results.

        Returns:
            ActionResult with data containing:
                - results: List of {index, success, claim_id, error, warnings}
                - added_count: Number of successfully added claims
                - failed_count: Number of failed claims
                - total: Total claims processed
        """
        results = []
        added_count = 0
        failed_count = 0

        # G2: when auto-extracting, fan the combined per-claim analysis calls
        # out in parallel up-front (one combined LLM call each, run
        # concurrently) instead of letting each add_claim block on its own
        # synchronous call. The precomputed result is injected into add_claim.
        analyses = None
        if (
            auto_extract
            and self.llm
            and getattr(self.config, "combined_enrichment", True)
        ):
            try:
                statements = [
                    (c.get("statement") or "").strip() for c in claims
                ]
                analyses = self.llm.batch_analyze(statements)
            except Exception as e:
                logger.warning(f"Bulk batch_analyze failed, falling back: {e}")
                analyses = None

        for i, claim_data in enumerate(claims):
            try:
                # Extract claim fields with defaults
                statement = claim_data.get("statement", "").strip()

                if not statement:
                    results.append(
                        {
                            "index": i,
                            "success": False,
                            "claim_id": None,
                            "error": "Empty statement",
                            "warnings": [],
                        }
                    )
                    failed_count += 1
                    if stop_on_error:
                        break
                    continue

                claim_type = claim_data.get("claim_type", "fact")
                context_domain = claim_data.get("context_domain", "personal")
                tags = claim_data.get("tags", [])
                entities = claim_data.get("entities", [])
                confidence = claim_data.get("confidence")
                meta_json = claim_data.get("meta_json")

                # Add the claim using existing add_claim method
                add_kwargs = {}
                if analyses is not None and i < len(analyses) and analyses[i] is not None:
                    add_kwargs["_analysis"] = analyses[i]
                result = self.add_claim(
                    statement=statement,
                    claim_type=claim_type,
                    context_domain=context_domain,
                    tags=tags,
                    entities=entities,
                    auto_extract=auto_extract,
                    confidence=confidence,
                    meta_json=meta_json,
                    **add_kwargs,
                )

                if result.success:
                    results.append(
                        {
                            "index": i,
                            "success": True,
                            "claim_id": result.object_id,
                            "error": None,
                            "warnings": result.warnings,
                        }
                    )
                    added_count += 1
                else:
                    results.append(
                        {
                            "index": i,
                            "success": False,
                            "claim_id": None,
                            "error": "; ".join(result.errors),
                            "warnings": result.warnings,
                        }
                    )
                    failed_count += 1
                    if stop_on_error:
                        break

            except Exception as e:
                logger.error(f"Failed to add claim at index {i}: {e}")
                results.append(
                    {
                        "index": i,
                        "success": False,
                        "claim_id": None,
                        "error": str(e),
                        "warnings": [],
                    }
                )
                failed_count += 1
                if stop_on_error:
                    break

        return ActionResult(
            success=failed_count == 0,
            action="bulk_add",
            object_type="claim",
            data={
                "results": results,
                "added_count": added_count,
                "failed_count": failed_count,
                "total": len(claims),
            },
            warnings=[f"Failed to add {failed_count} claims"]
            if failed_count > 0
            else [],
        )

    # =========================================================================
    # Notes API
    # =========================================================================

    def add_note(
        self,
        body: str,
        title: Optional[str] = None,
        context_domain: Optional[str] = None,
        meta_json: Optional[str] = None,
    ) -> ActionResult:
        """Add a new note."""
        try:
            note = Note.create(
                body=body,
                title=title,
                context_domain=context_domain,
                meta_json=meta_json,
            )

            note = self.notes.add(note)

            return ActionResult(
                success=True,
                action="add",
                object_type="note",
                object_id=note.note_id,
                data=note,
            )

        except Exception as e:
            logger.error(f"Failed to add note: {e}")
            return ActionResult(
                success=False, action="add", object_type="note", errors=[str(e)]
            )

    def edit_note(self, note_id: str, **patch) -> ActionResult:
        """Edit an existing note."""
        try:
            note = self.notes.edit(note_id, patch)

            if note:
                return ActionResult(
                    success=True,
                    action="edit",
                    object_type="note",
                    object_id=note_id,
                    data=note,
                )
            else:
                return ActionResult(
                    success=False,
                    action="edit",
                    object_type="note",
                    object_id=note_id,
                    errors=["Note not found"],
                )

        except Exception as e:
            return ActionResult(
                success=False,
                action="edit",
                object_type="note",
                object_id=note_id,
                errors=[str(e)],
            )

    def delete_note(self, note_id: str) -> ActionResult:
        """Delete a note."""
        try:
            deleted = self.notes.delete(note_id)

            return ActionResult(
                success=deleted,
                action="delete",
                object_type="note",
                object_id=note_id,
                errors=[] if deleted else ["Note not found"],
            )

        except Exception as e:
            return ActionResult(
                success=False,
                action="delete",
                object_type="note",
                object_id=note_id,
                errors=[str(e)],
            )

    # =========================================================================
    # Search API
    # =========================================================================

    def search(
        self,
        query: str,
        strategy: str = "hybrid",
        k: int = 20,
        filters: Optional[Dict] = None,
        include_contested: bool = True,
    ) -> ActionResult:
        """
        Search claims.

        If user_email is set on this API instance, results are filtered
        to only include claims owned by that user.

        Args:
            query: Search query string.
            strategy: Search strategy ("hybrid", "fts", "embedding", etc.).
            k: Number of results.
            filters: Optional filter dict.
            include_contested: Include contested claims.

        Returns:
            ActionResult with list of SearchResult objects.
        """
        try:
            # Lazy lifecycle sweep: hard-TTL expiry + soft-TTL dormancy decay
            # (Workstream F2) before searching. Decay is inert unless
            # config.dormancy_threshold > 0.
            from ..utils import maybe_expire_claims
            maybe_expire_claims(self.db, self.user_email, self.config)
            # Build filters (include user_email for multi-user support)
            search_filters = SearchFilters(
                include_contested=include_contested, user_email=self.user_email
            )

            if filters:
                # Support both plural list form ("claim_types": ["fact","pref"])
                # and singular string form ("claim_type": "fact") from the UI.
                if "context_domains" in filters:
                    val = filters["context_domains"]
                    search_filters.context_domains = (
                        val if isinstance(val, list) else [val]
                    )
                elif "context_domain" in filters and filters["context_domain"]:
                    search_filters.context_domains = [filters["context_domain"]]

                if "claim_types" in filters:
                    val = filters["claim_types"]
                    search_filters.claim_types = val if isinstance(val, list) else [val]
                elif "claim_type" in filters and filters["claim_type"]:
                    search_filters.claim_types = [filters["claim_type"]]

                if "statuses" in filters:
                    search_filters.statuses = filters["statuses"]
                elif "status" in filters and filters["status"]:
                    search_filters.statuses = [filters["status"]]

                if "valid_at" in filters:
                    search_filters.valid_at = filters["valid_at"]

            # Execute search
            if strategy == "hybrid":
                results = self.search_strategy.search(
                    query, k=k, filters=search_filters
                )
            elif strategy == "fts":
                results = self.search_strategy.search(
                    query, strategy_names=["fts"], k=k, filters=search_filters
                )
            elif strategy == "embedding":
                results = self.search_strategy.search(
                    query, strategy_names=["embedding"], k=k, filters=search_filters
                )
            elif strategy == "rerank":
                results = self.search_strategy.search_with_rerank(
                    query, k=k, filters=search_filters
                )
            else:
                results = self.search_strategy.search(
                    query, k=k, filters=search_filters
                )

            return ActionResult(
                success=True, action="search", object_type="claim", data=results
            )

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return ActionResult(
                success=False, action="search", object_type="claim", errors=[str(e)]
            )

    def search_notes(
        self, query: str, k: int = 20, context_domain: Optional[str] = None
    ) -> ActionResult:
        """Search notes."""
        try:
            results = self.notes_search.search(
                query, k=k, context_domain=context_domain
            )

            return ActionResult(
                success=True, action="search", object_type="note", data=results
            )

        except Exception as e:
            return ActionResult(
                success=False, action="search", object_type="note", errors=[str(e)]
            )

    # =========================================================================
    # Entities & Tags API
    # =========================================================================

    def add_entity(
        self, name: str, entity_type: str, meta_json: Optional[str] = None
    ) -> ActionResult:
        """Add a new entity."""
        try:
            meta_json = self._with_curated_origin(meta_json)
            entity = Entity.create(
                name=name, entity_type=entity_type, meta_json=meta_json
            )

            entity = self.entities.add(entity)

            return ActionResult(
                success=True,
                action="add",
                object_type="entity",
                object_id=entity.entity_id,
                data=entity,
            )

        except Exception as e:
            return ActionResult(
                success=False, action="add", object_type="entity", errors=[str(e)]
            )

    def add_tag(
        self,
        name: str,
        parent_tag_id: Optional[str] = None,
        meta_json: Optional[str] = None,
    ) -> ActionResult:
        """Add a new tag."""
        try:
            meta_json = self._with_curated_origin(meta_json)
            tag = Tag.create(
                name=name, parent_tag_id=parent_tag_id, meta_json=meta_json
            )

            tag = self.tags.add(tag)

            return ActionResult(
                success=True,
                action="add",
                object_type="tag",
                object_id=tag.tag_id,
                data=tag,
            )

        except Exception as e:
            return ActionResult(
                success=False, action="add", object_type="tag", errors=[str(e)]
            )

    # =========================================================================
    # Conflicts API
    # =========================================================================

    def create_conflict_set(
        self, claim_ids: List[str], notes: Optional[str] = None
    ) -> ActionResult:
        """Create a conflict set from 2+ claims."""
        try:
            conflict_set = self.conflicts.create(claim_ids, notes)

            return ActionResult(
                success=True,
                action="create_conflict",
                object_type="conflict_set",
                object_id=conflict_set.conflict_set_id,
                data=conflict_set,
            )

        except ValueError as e:
            return ActionResult(
                success=False,
                action="create_conflict",
                object_type="conflict_set",
                errors=[str(e)],
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action="create_conflict",
                object_type="conflict_set",
                errors=[str(e)],
            )

    def resolve_conflict_set(
        self,
        conflict_set_id: str,
        resolution_notes: str,
        winning_claim_id: Optional[str] = None,
    ) -> ActionResult:
        """Resolve a conflict set."""
        try:
            conflict_set = self.conflicts.resolve(
                conflict_set_id, resolution_notes, winning_claim_id
            )

            if conflict_set:
                # D1: when the user picks a winner, the losers were just moved to
                # `superseded` by ConflictCRUD.resolve. Record the supersession
                # graph (winner -supersedes-> each loser) so chain-head retrieval
                # and "what replaced this?" queries work.
                if winning_claim_id:
                    try:
                        rows = self.db.fetchall(
                            "SELECT claim_id FROM conflict_set_members WHERE conflict_set_id = ?",
                            (conflict_set_id,),
                        )
                        for row in rows:
                            loser = row["claim_id"]
                            if loser != winning_claim_id:
                                link_claims(
                                    self.db, winning_claim_id, loser,
                                    link_type=LINK_SUPERSEDES,
                                    user_email=self.user_email,
                                )
                    except Exception as e:
                        logger.warning(
                            f"Could not record supersession links for "
                            f"conflict {conflict_set_id}: {e}"
                        )
                return ActionResult(
                    success=True,
                    action="resolve_conflict",
                    object_type="conflict_set",
                    object_id=conflict_set_id,
                    data=conflict_set,
                )
            else:
                return ActionResult(
                    success=False,
                    action="resolve_conflict",
                    object_type="conflict_set",
                    object_id=conflict_set_id,
                    errors=["Conflict set not found"],
                )

        except Exception as e:
            return ActionResult(
                success=False,
                action="resolve_conflict",
                object_type="conflict_set",
                object_id=conflict_set_id,
                errors=[str(e)],
            )

    def get_open_conflicts(self) -> ActionResult:
        """Get all open conflict sets."""
        try:
            conflicts = self.conflicts.get_open()

            return ActionResult(
                success=True, action="get", object_type="conflict_set", data=conflicts
            )

        except Exception as e:
            return ActionResult(
                success=False, action="get", object_type="conflict_set", errors=[str(e)]
            )

    # =========================================================================
    # Pinning API (Deliberate Memory Attachment)
    # =========================================================================

    def pin_claim(self, claim_id: str, pin: bool = True) -> ActionResult:
        """
        Toggle the pinned status of a claim.

        Pinned claims are always included in context retrieval, regardless of
        query relevance. This allows users to "force" certain memories to be
        used by the LLM.

        The pinned status is stored in the claim's meta_json field as:
        {"pinned": true/false}

        Args:
            claim_id: ID of the claim to pin/unpin.
            pin: True to pin, False to unpin.

        Returns:
            ActionResult with the updated claim.
        """
        import json

        try:
            # Get the existing claim
            claim = self.claims.get(claim_id)
            if not claim:
                return ActionResult(
                    success=False,
                    action="pin",
                    object_type="claim",
                    object_id=claim_id,
                    errors=["Claim not found"],
                )

            # Parse existing meta_json or create new
            meta = {}
            if claim.meta_json:
                try:
                    meta = json.loads(claim.meta_json)
                except json.JSONDecodeError:
                    meta = {}

            # Update pinned status
            meta["pinned"] = pin

            # Build the update. Pinning is an explicit "this matters" signal, so
            # (H3, weakest hook) also reinforce the claim — but only on pin (not
            # unpin) and never for contested/superseded claims (H4 safeguard).
            patch = {"meta_json": json.dumps(meta)}
            if pin and claim.status not in (
                ClaimStatus.CONTESTED.value,
                ClaimStatus.SUPERSEDED.value,
            ):
                rpatch, _ = self._build_reinforcement_patch(claim)
                patch.update(rpatch)

            # Save the updated claim
            updated_claim = self.claims.edit(claim_id, patch)

            if updated_claim:
                return ActionResult(
                    success=True,
                    action="pin" if pin else "unpin",
                    object_type="claim",
                    object_id=claim_id,
                    data=updated_claim,
                )
            else:
                return ActionResult(
                    success=False,
                    action="pin",
                    object_type="claim",
                    object_id=claim_id,
                    errors=["Failed to update claim"],
                )

        except Exception as e:
            logger.error(f"Failed to pin claim: {e}")
            return ActionResult(
                success=False,
                action="pin",
                object_type="claim",
                object_id=claim_id,
                errors=[str(e)],
            )

    def _build_reinforcement_patch(self, claim, strength: float = 1.0):
        """
        Build the column patch that reinforces a claim (Workstream H).

        Shared by ``reinforce_claim`` and other reinforcement signals (e.g.
        pinning) so the freshness/confidence math lives in one place. Does NOT
        apply the H4 contested/superseded safeguard — callers decide whether to
        skip reinforcement for those statuses.

        Returns:
            (patch, warnings) where ``patch`` is the dict of claim columns to
            update and ``warnings`` notes side effects (e.g. dormant revive).
        """
        from datetime import datetime, timezone, timedelta
        from ..utils import now_iso

        patch: Dict[str, Any] = {
            "last_reinforced_at": now_iso(),
            "reinforcement_count": (claim.reinforcement_count or 0) + 1,
        }

        # Confidence: asymptotic approach to 1.0 with diminishing returns.
        alpha = min(1.0, self.config.reinforce_alpha * max(0.0, float(strength)))
        base_conf = (
            claim.confidence
            if claim.confidence is not None
            else self.config.default_confidence
        )
        patch["confidence"] = round(base_conf + (1.0 - base_conf) * alpha, 6)

        # Extend hard TTL (valid_to) for configured types that have one.
        ttl_days = self.config.reinforce_ttl_days_by_type.get(claim.claim_type)
        if ttl_days and claim.valid_to:
            new_valid_to = datetime.now(timezone.utc) + timedelta(days=float(ttl_days))
            patch["valid_to"] = new_valid_to.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Revive a dormant claim.
        warnings: List[str] = []
        if claim.status == ClaimStatus.DORMANT.value:
            patch["status"] = ClaimStatus.ACTIVE.value
            warnings.append("Revived dormant claim to active")

        return patch, warnings

    def reinforce_claim(
        self, claim_id: str, strength: float = 1.0, upgrade_derivation: bool = False
    ) -> ActionResult:
        """
        Reinforce a claim — the single "use it or lose it" state transition
        (Workstream H). Re-affirming a claim keeps it fresh and ranking higher.

        Effects (all in one update):
        - ``last_reinforced_at = now`` (the clock recency/decay measure from).
        - ``reinforcement_count += 1``.
        - ``updated_at = now`` (set automatically by the CRUD layer).
        - ``confidence`` nudged toward 1.0 asymptotically:
          ``confidence + (1 - confidence) * (reinforce_alpha * strength)`` —
          diminishing returns, never exceeds 1.0.
        - Hard TTL extension: if ``reinforce_ttl_days_by_type[claim_type]`` is set
          and the claim has a ``valid_to``, push ``valid_to`` to ``now + ttl``.
        - Revive: a ``dormant`` claim flips back to ``active``.

        Safeguard (H4): reinforcing a ``contested`` or ``superseded`` claim is
        refused — that path should trigger conflict review, not a silent boost,
        so we don't resurrect claims known to be false/replaced.

        Args:
            claim_id: ID of the claim to reinforce.
            strength: Multiplier on ``reinforce_alpha`` (0..1 typical; e.g. an
                explicit restatement = 1.0, an implicit retrieval hit < 1.0).

        Returns:
            ActionResult with the updated Claim, or failure if not found /
            blocked by the safeguard.
        """
        try:
            claim = self.claims.get(claim_id)
            if not claim:
                return ActionResult(
                    success=False,
                    action="reinforce",
                    object_type="claim",
                    object_id=claim_id,
                    errors=["Claim not found"],
                )

            # H4 safeguard: do not silently boost a claim that is in conflict
            # or has been replaced — surface it for review instead.
            if claim.status in (
                ClaimStatus.CONTESTED.value,
                ClaimStatus.SUPERSEDED.value,
            ):
                return ActionResult(
                    success=False,
                    action="reinforce",
                    object_type="claim",
                    object_id=claim_id,
                    data=claim,
                    errors=[
                        f"Cannot reinforce a {claim.status} claim; resolve the "
                        f"conflict/supersession first"
                    ],
                )

            patch, warnings = self._build_reinforcement_patch(claim, strength)

            # W4 reconfirmation upgrade: when the user explicitly restates an
            # inferred claim, promote its derivation inferred -> stated (the
            # user has now confirmed the conclusion) and lift the inferred
            # confidence cap so it ranks like a stated claim.
            if upgrade_derivation:
                from ..utils import get_provenance, set_provenance, parse_meta_json
                from ..constants import Derivation
                import json as _pjson

                if get_provenance(claim.meta_json).get("derivation") == \
                        Derivation.INFERRED.value:
                    _meta = parse_meta_json(claim.meta_json)
                    set_provenance(_meta, derivation=Derivation.STATED.value)
                    patch["meta_json"] = _pjson.dumps(_meta)
                    warnings.append("Upgraded derivation inferred → stated")

            updated = self.claims.edit(claim_id, patch)
            if not updated:
                return ActionResult(
                    success=False,
                    action="reinforce",
                    object_type="claim",
                    object_id=claim_id,
                    errors=["Failed to reinforce claim"],
                )

            return ActionResult(
                success=True,
                action="reinforce",
                object_type="claim",
                object_id=claim_id,
                data=updated,
                warnings=warnings,
            )

        except Exception as e:
            logger.error(f"Failed to reinforce claim: {e}")
            return ActionResult(
                success=False,
                action="reinforce",
                object_type="claim",
                object_id=claim_id,
                errors=[str(e)],
            )

    def run_decay_sweep(self) -> ActionResult:
        """
        Run the soft-TTL dormancy decay sweep now (Workstream F2).

        Flips ``active`` claims whose freshness has fallen below
        ``config.dormancy_threshold`` to ``dormant`` (see
        ``utils.decay_dormant_claims``). Intended for a scheduled background job
        (F1) or manual/admin invocation; normal search also runs it lazily.
        Inert unless ``dormancy_threshold > 0``.

        Returns:
            ActionResult whose ``data`` is ``{"dormant_count": N}``.
        """
        try:
            from ..utils import decay_dormant_claims

            count = decay_dormant_claims(self.db, self.config, self.user_email)
            return ActionResult(
                success=True,
                action="decay",
                object_type="claim",
                data={"dormant_count": count},
            )
        except Exception as e:
            logger.error(f"Decay sweep failed: {e}")
            return ActionResult(
                success=False,
                action="decay",
                object_type="claim",
                errors=[str(e)],
            )

    def run_lifecycle_sweep(self) -> ActionResult:
        """
        Run the full lifecycle sweep now (Workstream F1): hard-TTL expiry +
        soft-TTL dormancy decay, scoped to this API's user.

        This is the on-demand counterpart to the background scheduler — useful
        for an admin/maintenance trigger. Inert dormancy unless
        ``dormancy_threshold > 0``.

        Returns:
            ActionResult whose ``data`` is ``{"expired": N, "dormant": M}``.
        """
        try:
            from ..utils import run_lifecycle_sweep

            counts = run_lifecycle_sweep(self.db, self.config, self.user_email)
            return ActionResult(
                success=True, action="sweep", object_type="claim", data=counts,
            )
        except Exception as e:
            logger.error(f"Lifecycle sweep failed: {e}")
            return ActionResult(
                success=False, action="sweep", object_type="claim", errors=[str(e)],
            )

    def get_lifecycle_notifications(
        self, within_days: int = None, limit: int = 50
    ) -> ActionResult:
        """
        Surface claims needing attention (Workstream F4).

        Two buckets, scoped to this API's user:
        - ``soon_to_expire``: active ``task``/``reminder`` claims whose
          ``valid_to`` falls within the next ``within_days`` days.
        - ``newly_dormant``: claims flipped to ``dormant`` within the last
          ``within_days`` days (the decay sweep stamps ``updated_at`` on flip).

        Args:
            within_days: look-ahead / look-back window (defaults to
                ``config.notify_expiry_within_days``).
            limit: max rows per bucket.

        Returns:
            ActionResult with ``data`` = {"soon_to_expire": [...],
            "newly_dormant": [...], "counts": {...}}.
        """
        try:
            from ..utils import now_iso
            from datetime import datetime, timezone, timedelta

            if within_days is None:
                within_days = self.config.notify_expiry_within_days

            now_dt = datetime.now(timezone.utc)
            now = now_iso()
            horizon = (now_dt + timedelta(days=within_days)).isoformat()
            lookback = (now_dt - timedelta(days=within_days)).isoformat()

            def _scope(sql, params):
                if self.user_email:
                    sql += " AND user_email = ?"
                    params.append(self.user_email)
                else:
                    sql += " AND user_email IS NULL"
                return sql, params

            # Soon-to-expire task/reminder claims still active.
            exp_sql = (
                "SELECT claim_id, statement, claim_type, valid_to, status "
                "FROM claims WHERE status = 'active' "
                "AND claim_type IN ('task', 'reminder') "
                "AND valid_to IS NOT NULL AND valid_to != '' "
                "AND valid_to >= ? AND valid_to <= ?"
            )
            exp_sql, exp_params = _scope(exp_sql, [now, horizon])
            exp_sql += " ORDER BY valid_to ASC LIMIT ?"
            exp_params.append(limit)
            soon = [
                {
                    "claim_id": r["claim_id"], "statement": r["statement"],
                    "claim_type": r["claim_type"], "valid_to": r["valid_to"],
                }
                for r in self.db.fetchall(exp_sql, tuple(exp_params))
            ]

            # Recently-dormant claims.
            dorm_sql = (
                "SELECT claim_id, statement, claim_type, updated_at, status "
                "FROM claims WHERE status = 'dormant' AND updated_at >= ?"
            )
            dorm_sql, dorm_params = _scope(dorm_sql, [lookback])
            dorm_sql += " ORDER BY updated_at DESC LIMIT ?"
            dorm_params.append(limit)
            dormant = [
                {
                    "claim_id": r["claim_id"], "statement": r["statement"],
                    "claim_type": r["claim_type"], "updated_at": r["updated_at"],
                }
                for r in self.db.fetchall(dorm_sql, tuple(dorm_params))
            ]

            return ActionResult(
                success=True, action="list", object_type="claim",
                data={
                    "soon_to_expire": soon,
                    "newly_dormant": dormant,
                    "counts": {
                        "soon_to_expire": len(soon),
                        "newly_dormant": len(dormant),
                    },
                    "within_days": within_days,
                },
            )
        except Exception as e:
            logger.error(f"Failed to build lifecycle notifications: {e}")
            return ActionResult(
                success=False, action="list", object_type="claim", errors=[str(e)],
            )

    def _record_audit(self, action, object_type, object_id, detail=None):
        """Best-effort append to the audit log (Workstream G3). Never raises."""
        try:
            from ..portability import record_audit

            record_audit(
                self.db, self.user_email, action, object_type, object_id, detail
            )
        except Exception as e:  # pragma: no cover - logging only
            logger.warning(f"Audit hook failed: {e}")

    def export_data(self) -> ActionResult:
        """
        Export this user's PKB as a JSON-serializable envelope (Workstream G3).

        Includes claims, links, entities, tags, contexts and join rows; excludes
        derived embeddings. See ``portability.export_user_data``.
        """
        try:
            from ..portability import export_user_data

            payload = export_user_data(self.db, self.user_email)
            return ActionResult(
                success=True, action="export", object_type="pkb", data=payload,
            )
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return ActionResult(
                success=False, action="export", object_type="pkb", errors=[str(e)],
            )

    def import_data(self, payload: Dict, mode: str = "merge") -> ActionResult:
        """
        Import an export envelope into this user's PKB (Workstream G3).

        Rows are re-owned to this user; ``merge`` mode skips primary-key
        collisions. See ``portability.import_user_data``.
        """
        try:
            from ..portability import import_user_data

            if not isinstance(payload, dict) or "data" not in payload:
                return ActionResult(
                    success=False, action="import", object_type="pkb",
                    errors=["Invalid import payload: missing 'data'"],
                )
            counts = import_user_data(self.db, self.user_email, payload, mode)
            self._record_audit("import", "pkb", None, detail=counts)
            return ActionResult(
                success=True, action="import", object_type="pkb", data=counts,
            )
        except Exception as e:
            logger.error(f"Import failed: {e}")
            return ActionResult(
                success=False, action="import", object_type="pkb", errors=[str(e)],
            )

    def get_audit_log(
        self, limit: int = 100, offset: int = 0, action: str = None
    ) -> ActionResult:
        """Return this user's audit-log entries, newest first (Workstream G3)."""
        try:
            from ..portability import get_audit_log

            entries = get_audit_log(
                self.db, self.user_email, limit=limit, offset=offset, action=action
            )
            return ActionResult(
                success=True, action="list", object_type="audit",
                data={"entries": entries, "count": len(entries)},
            )
        except Exception as e:
            logger.error(f"Failed to read audit log: {e}")
            return ActionResult(
                success=False, action="list", object_type="audit", errors=[str(e)],
            )

    def supersede_claim(
        self,
        new_claim_id: str,
        old_claim_id: str,
        resolution_notes: Optional[str] = None,
    ) -> ActionResult:
        """
        Record that ``new_claim_id`` supersedes ``old_claim_id`` (Workstream D1).

        Creates a ``supersedes`` link (new -> old) and moves the old claim to
        ``superseded`` status, so it drops out of default search
        (``ClaimStatus.default_search_statuses`` omits it) while staying
        retrievable/visible and queryable through the link graph. Retrieval then
        naturally prefers the chain head — the newest claim, found via
        ``get_supersession_head``.

        Guards: refuses self-supersession and missing claims; idempotent on the
        link (a duplicate edge is ignored). Use when the user confirms that a new
        claim replaces an older one.

        Args:
            new_claim_id: The newer claim that replaces the old one.
            old_claim_id: The claim being superseded.
            resolution_notes: Optional note stored on the link.

        Returns:
            ActionResult with ``data`` = {"new_claim_id", "old_claim_id",
            "link_id", "head_claim_id"}.
        """
        try:
            if new_claim_id == old_claim_id:
                return ActionResult(
                    success=False, action="supersede", object_type="claim",
                    object_id=old_claim_id,
                    errors=["A claim cannot supersede itself"],
                )

            new_claim = self.claims.get(new_claim_id)
            old_claim = self.claims.get(old_claim_id)
            if new_claim is None:
                return ActionResult(
                    success=False, action="supersede", object_type="claim",
                    object_id=new_claim_id,
                    errors=[f"New claim {new_claim_id} not found"],
                )
            if old_claim is None:
                return ActionResult(
                    success=False, action="supersede", object_type="claim",
                    object_id=old_claim_id,
                    errors=[f"Old claim {old_claim_id} not found"],
                )

            meta_json = None
            if resolution_notes:
                import json as _json
                meta_json = _json.dumps({"resolution_notes": resolution_notes})

            link_id = link_claims(
                self.db, new_claim_id, old_claim_id,
                link_type=LINK_SUPERSEDES,
                user_email=self.user_email, meta_json=meta_json,
            )

            warnings = []
            if link_id is None:
                warnings.append(
                    f"Supersession link {new_claim_id[:8]} -> {old_claim_id[:8]} "
                    f"already existed"
                )

            # Move the old claim to superseded (idempotent if already there).
            if old_claim.status != ClaimStatus.SUPERSEDED.value:
                self.claims.edit(
                    old_claim_id, {"status": ClaimStatus.SUPERSEDED.value}
                )

            head = get_supersession_head(self.db, old_claim_id)
            return ActionResult(
                success=True, action="supersede", object_type="claim",
                object_id=old_claim_id,
                data={
                    "new_claim_id": new_claim_id,
                    "old_claim_id": old_claim_id,
                    "link_id": link_id,
                    "head_claim_id": head,
                },
                warnings=warnings,
            )
        except Exception as e:
            logger.error(f"Failed to supersede claim: {e}")
            return ActionResult(
                success=False, action="supersede", object_type="claim",
                object_id=old_claim_id, errors=[str(e)],
            )

    # ----------------------------------------------------------------- #
    # D2 — Consolidation: cluster near-duplicate claims and merge them.
    # ----------------------------------------------------------------- #
    def _suggest_keeper(self, claims: List["Claim"]) -> "Claim":
        """Pick the canonical claim of a duplicate cluster: highest confidence,
        tie-broken by most recent creation."""
        def key(c):
            conf = c.confidence if c.confidence is not None else 0.0
            return (conf, c.created_at or "")
        return max(claims, key=key)

    def find_consolidation_candidates(
        self, threshold: float = None, limit: int = 50
    ) -> ActionResult:
        """
        Cluster near-duplicate active claims via cached embeddings (Workstream D2).

        Uses the A1 embedding cache (no LLM): pulls all active/contested claim
        vectors, single-linkage clusters those within ``threshold`` cosine
        similarity, and returns merge proposals for the existing proposal flow.

        Args:
            threshold: cosine-similarity cutoff (defaults to
                ``config.consolidation_similarity_threshold``).
            limit: maximum number of clusters to return.

        Returns:
            ActionResult with ``data`` = list of
            {claim_ids, statements, suggested_keep_id, max_similarity}.
        """
        try:
            store = self._get_embedding_store()
            if store is None:
                return ActionResult(
                    success=False, action="list", object_type="claim",
                    errors=["Embedding cache unavailable (disabled or no API key)"],
                )
            if threshold is None:
                threshold = self.config.consolidation_similarity_threshold

            from ..search.consolidation import cluster_near_duplicate_claims
            embeddings = store.get_all_embeddings(SearchFilters())
            clusters = cluster_near_duplicate_claims(embeddings, threshold)

            out = []
            for cl in clusters[:limit]:
                claims = [self.claims.get(cid) for cid in cl["claim_ids"]]
                claims = [c for c in claims if c is not None]
                if len(claims) < 2:
                    continue
                keeper = self._suggest_keeper(claims)
                out.append({
                    "claim_ids": [c.claim_id for c in claims],
                    "statements": {c.claim_id: c.statement for c in claims},
                    "suggested_keep_id": keeper.claim_id,
                    "max_similarity": cl["max_similarity"],
                })

            return ActionResult(
                success=True, action="list", object_type="claim", data=out,
            )
        except Exception as e:
            logger.error(f"Failed to find consolidation candidates: {e}")
            return ActionResult(
                success=False, action="list", object_type="claim", errors=[str(e)],
            )

    def consolidate_claims(
        self, claim_ids: List[str], keep_id: str = None
    ) -> ActionResult:
        """
        Merge a near-duplicate cluster into one canonical claim (Workstream D2).

        Keeps ``keep_id`` (or the suggested keeper) active, unions the
        duplicates' tags onto it, and supersedes the rest via D1 supersession
        links (so they stay linked and drop out of default search). Reversible
        by un-superseding the retired claims.

        Args:
            claim_ids: claim ids forming the duplicate cluster (>= 2).
            keep_id: the claim to keep; defaults to the suggested keeper.

        Returns:
            ActionResult with ``data`` = {"kept", "superseded": [...]}.
        """
        try:
            if not claim_ids or len(claim_ids) < 2:
                return ActionResult(
                    success=False, action="update", object_type="claim",
                    errors=["consolidate_claims needs at least two claim_ids"],
                )
            claims = {cid: self.claims.get(cid) for cid in set(claim_ids)}
            missing = [cid for cid, c in claims.items() if c is None]
            if missing:
                return ActionResult(
                    success=False, action="update", object_type="claim",
                    errors=[f"Claims not found: {', '.join(missing)}"],
                )
            if keep_id is None:
                keep_id = self._suggest_keeper(list(claims.values())).claim_id
            elif keep_id not in claims:
                return ActionResult(
                    success=False, action="update", object_type="claim",
                    object_id=keep_id,
                    errors=[f"keep_id {keep_id} is not in the cluster"],
                )

            from ..crud.links import get_claim_tags, link_claim_tag
            superseded = []
            for cid, claim in claims.items():
                if cid == keep_id:
                    continue
                # Preserve the duplicate's tags on the keeper (idempotent).
                for tag in get_claim_tags(self.db, cid):
                    link_claim_tag(self.db, keep_id, tag.tag_id)
                res = self.supersede_claim(
                    keep_id, cid, resolution_notes="consolidated duplicate (D2)"
                )
                if res.success:
                    superseded.append(cid)

            return ActionResult(
                success=True, action="update", object_type="claim",
                object_id=keep_id,
                data={"kept": keep_id, "superseded": superseded},
            )
        except Exception as e:
            logger.error(f"Failed to consolidate claims: {e}")
            return ActionResult(
                success=False, action="update", object_type="claim", errors=[str(e)],
            )

    # ----------------------------------------------------------------- #
    # D3 — Canonical entity resolution: dedupe entity variants w/ aliases.
    # ----------------------------------------------------------------- #
    def find_entity_duplicates(
        self, entity_type: str = None, threshold: float = None
    ) -> ActionResult:
        """
        Detect entity name variants of the same type (Workstream D3).

        Clusters same-type entities whose names are variants of one another
        ("john" vs "John Smith") using string similarity + a token-subset rule.
        No LLM required.

        Args:
            entity_type: restrict to one type; defaults to all EntityType values.
            threshold: name-similarity cutoff (defaults to
                ``config.entity_dedup_threshold``).

        Returns:
            ActionResult with ``data`` = list of
            {entity_ids, names, suggested_keep_id, max_similarity}.
        """
        try:
            if threshold is None:
                threshold = self.config.entity_dedup_threshold
            types = [entity_type] if entity_type else [e.value for e in EntityType]

            from ..search.consolidation import cluster_entity_variants
            out = []
            for et in types:
                ents = self.entities.get_by_type(et, limit=1000)
                out.extend(cluster_entity_variants(ents, threshold))

            out.sort(key=lambda c: c["max_similarity"], reverse=True)
            return ActionResult(
                success=True, action="list", object_type="entity", data=out,
            )
        except Exception as e:
            logger.error(f"Failed to find entity duplicates: {e}")
            return ActionResult(
                success=False, action="list", object_type="entity", errors=[str(e)],
            )

    def merge_entities(self, source_id: str, target_id: str) -> ActionResult:
        """
        Merge a duplicate entity into a canonical one, keeping aliases (D3).

        Records the source's name (and any aliases it already carried) in the
        target's ``meta_json.aliases``, then re-points the source's claim links
        to the target and deletes the source (via ``EntityCRUD.merge``).

        Args:
            source_id: entity to merge from (deleted).
            target_id: canonical entity to keep.

        Returns:
            ActionResult with ``data`` = {"entity_id", "aliases", "merged_from"}.
        """
        try:
            if source_id == target_id:
                return ActionResult(
                    success=False, action="merge", object_type="entity",
                    object_id=target_id, errors=["Cannot merge an entity into itself"],
                )
            source = self.entities.get(source_id)
            target = self.entities.get(target_id)
            if source is None or target is None:
                missing = source_id if source is None else target_id
                return ActionResult(
                    success=False, action="merge", object_type="entity",
                    object_id=missing, errors=[f"Entity {missing} not found"],
                )

            from ..utils import parse_meta_json
            import json as _json
            aliases = set()
            for ent in (target, source):
                meta = parse_meta_json(ent.meta_json) or {}
                aliases.update(meta.get("aliases", []) or [])
            aliases.add(source.name)
            aliases.discard(target.name)

            tmeta = parse_meta_json(target.meta_json) or {}
            tmeta["aliases"] = sorted(aliases)
            self.entities.edit(target_id, {"meta_json": _json.dumps(tmeta)})

            merged = self.entities.merge(source_id, target_id)
            if merged is None:
                return ActionResult(
                    success=False, action="merge", object_type="entity",
                    object_id=target_id, errors=["Merge failed"],
                )
            return ActionResult(
                success=True, action="merge", object_type="entity",
                object_id=target_id,
                data={
                    "entity_id": target_id,
                    "aliases": tmeta["aliases"],
                    "merged_from": source_id,
                },
            )
        except Exception as e:
            logger.error(f"Failed to merge entities: {e}")
            return ActionResult(
                success=False, action="merge", object_type="entity",
                object_id=target_id, errors=[str(e)],
            )

    def find_tag_duplicates(self, threshold: float = None) -> ActionResult:
        """
        Detect tag name variants proposed for merge (Workstream W6).

        Clusters tags whose names are variants of one another using the same
        string-similarity + token-subset rule as entity dedup. No LLM.

        Args:
            threshold: name-similarity cutoff (defaults to
                ``config.entity_dedup_threshold``).

        Returns:
            ActionResult with ``data`` = list of
            {tag_ids, names, suggested_keep_id, max_similarity}.
        """
        try:
            if threshold is None:
                threshold = self.config.entity_dedup_threshold
            from ..search.consolidation import cluster_tag_variants
            tags = self.tags.list(limit=2000, order_by="name")
            clusters = cluster_tag_variants(tags, threshold)
            return ActionResult(
                success=True, action="list", object_type="tag", data=clusters,
            )
        except Exception as e:
            logger.error(f"Failed to find tag duplicates: {e}")
            return ActionResult(
                success=False, action="list", object_type="tag", errors=[str(e)],
            )

    def merge_tags(self, source_id: str, target_id: str) -> ActionResult:
        """
        Merge a duplicate tag into a canonical one (Workstream W6).

        Records the source's name in the target's ``meta_json.aliases``, then
        re-points the source's claim links and re-parents its children to the
        target before deleting it (via ``TagCRUD.merge``). The target keeps its
        ``origin`` (a curated target stays curated).

        Args:
            source_id: tag to merge from (deleted).
            target_id: canonical tag to keep.

        Returns:
            ActionResult with ``data`` = {"tag_id", "aliases", "merged_from"}.
        """
        try:
            if source_id == target_id:
                return ActionResult(
                    success=False, action="merge", object_type="tag",
                    object_id=target_id, errors=["Cannot merge a tag into itself"],
                )
            source = self.tags.get(source_id)
            target = self.tags.get(target_id)
            if source is None or target is None:
                missing = source_id if source is None else target_id
                return ActionResult(
                    success=False, action="merge", object_type="tag",
                    object_id=missing, errors=[f"Tag {missing} not found"],
                )

            from ..utils import parse_meta_json
            import json as _json
            aliases = set()
            for tg in (target, source):
                meta = parse_meta_json(tg.meta_json) or {}
                aliases.update(meta.get("aliases", []) or [])
            aliases.add(source.name)
            aliases.discard(target.name)

            tmeta = parse_meta_json(target.meta_json) or {}
            tmeta["aliases"] = sorted(aliases)
            self.tags.edit(target_id, {"meta_json": _json.dumps(tmeta)})

            merged = self.tags.merge(source_id, target_id)
            if merged is None:
                return ActionResult(
                    success=False, action="merge", object_type="tag",
                    object_id=target_id, errors=["Merge failed"],
                )
            return ActionResult(
                success=True, action="merge", object_type="tag",
                object_id=target_id,
                data={
                    "tag_id": target_id,
                    "aliases": tmeta["aliases"],
                    "merged_from": source_id,
                },
            )
        except Exception as e:
            logger.error(f"Failed to merge tags: {e}")
            return ActionResult(
                success=False, action="merge", object_type="tag",
                object_id=target_id, errors=[str(e)],
            )

    def get_claim_provenance(self, claim_id: str) -> ActionResult:
        """
        Return where a claim came from — "why do I know this?" (Workstream E1).

        Reads the ``source`` object recorded in ``meta_json`` (set on distilled
        claims via ``add_claim``'s ``source_*`` params). For a chat-distilled
        claim this includes ``conversation_id`` / ``message_id`` so the UI can
        link back to the originating turn.

        Returns:
            ActionResult with ``data`` = {
              "claim_id", "source_type", "conversation_id", "message_id",
              "distilled", "created_at"
            }. ``source_type`` is "manual" when no provenance was recorded.
        """
        try:
            claim = self.claims.get(claim_id)
            if claim is None:
                return ActionResult(
                    success=False, action="get", object_type="claim",
                    object_id=claim_id, errors=[f"Claim {claim_id} not found"],
                )

            source = {}
            if claim.meta_json:
                import json as _json
                try:
                    meta = _json.loads(claim.meta_json)
                    raw = meta.get("source")
                    if isinstance(raw, dict):
                        source = raw
                    elif isinstance(raw, str):
                        source = {"type": raw}
                except (ValueError, TypeError):
                    pass

            return ActionResult(
                success=True, action="get", object_type="claim",
                object_id=claim_id,
                data={
                    "claim_id": claim_id,
                    "source_type": source.get("type", "manual"),
                    "conversation_id": source.get("conversation_id"),
                    "message_id": source.get("message_id"),
                    "distilled": bool(source.get("distilled", False)),
                    "created_at": claim.created_at,
                },
            )
        except Exception as e:
            logger.error(f"Failed to get claim provenance: {e}")
            return ActionResult(
                success=False, action="get", object_type="claim",
                object_id=claim_id, errors=[str(e)],
            )

    def get_pinned_claims(self, limit: int = 50) -> ActionResult:
        """
        Get all globally pinned claims for the current user.

        Pinned claims have meta_json.pinned = true and are always included
        in context retrieval.

        Args:
            limit: Maximum number of claims to return (default 50).

        Returns:
            ActionResult with list of pinned Claim objects.
        """
        import json
        from truth_management_system.models import ClaimStatus

        try:
            # Get active claims for the user
            # We need to filter by meta_json containing pinned=true
            # Since SQLite doesn't have native JSON querying, we'll filter in Python
            # Use list() which supports limit parameter
            all_claims = self.claims.list(
                filters={"status": ClaimStatus.ACTIVE.value}, limit=500
            )  # Get more to filter

            pinned_claims = []
            for claim in all_claims:
                if claim.meta_json:
                    try:
                        meta = json.loads(claim.meta_json)
                        if meta.get("pinned", False):
                            pinned_claims.append(claim)
                            if len(pinned_claims) >= limit:
                                break
                    except json.JSONDecodeError:
                        continue

            return ActionResult(
                success=True,
                action="get_pinned",
                object_type="claim",
                data=pinned_claims,
            )

        except Exception as e:
            logger.error(f"Failed to get pinned claims: {e}")
            return ActionResult(
                success=False, action="get_pinned", object_type="claim", errors=[str(e)]
            )

    def get_claims_by_ids(self, claim_ids: List[str]) -> ActionResult:
        """
        Get multiple claims by their IDs.

        This is useful for fetching specifically attached or referenced claims
        during context retrieval.

        Args:
            claim_ids: List of claim IDs to fetch.

        Returns:
            ActionResult with list of Claim objects (in order, None for missing).
        """
        try:
            claims = []
            for cid in claim_ids:
                claim = self.claims.get(cid)
                claims.append(claim)  # May be None if not found

            return ActionResult(
                success=True, action="get_by_ids", object_type="claim", data=claims
            )

        except Exception as e:
            logger.error(f"Failed to get claims by IDs: {e}")
            return ActionResult(
                success=False, action="get_by_ids", object_type="claim", errors=[str(e)]
            )

    # =========================================================================
    # Friendly ID & Reference Resolution (v0.5)
    # =========================================================================

    def get_claim_by_friendly_id(self, friendly_id: str) -> ActionResult:
        """
        Get a claim by its user-facing friendly_id.

        Args:
            friendly_id: The user-facing alphanumeric identifier.

        Returns:
            ActionResult with Claim if found.
        """
        try:
            claim = self.claims.get_by_friendly_id(friendly_id)
            if claim:
                return ActionResult(
                    success=True,
                    action="get",
                    object_type="claim",
                    object_id=claim.claim_id,
                    data=claim,
                )
            return ActionResult(
                success=False,
                action="get",
                object_type="claim",
                errors=[f"No claim found with friendly_id: {friendly_id}"],
            )
        except Exception as e:
            logger.error(f"Failed to get claim by friendly_id: {e}")
            return ActionResult(
                success=False, action="get", object_type="claim", errors=[str(e)]
            )

    def resolve_claim_identifier(self, identifier: str) -> Optional[Claim]:
        """
        Resolve any claim identifier to a Claim object.

        Tries multiple resolution strategies in order:
        1. @claim_N or claim_N or bare number -> claim_number lookup
        2. UUID format -> direct claim_id lookup
        3. friendly_id lookup (with or without @ prefix)

        This is the universal "find a claim by whatever the user typed" method.

        Args:
            identifier: Any string the user might use to reference a claim.
                       Supported formats: "42", "claim_42", "@claim_42",
                       "@friendly_id", "friendly_id", "uuid-string"

        Returns:
            Claim if found, None otherwise.
        """
        import re as _re

        if not identifier:
            return None

        # Strip leading @ if present
        ident = identifier.strip()
        if ident.startswith("@"):
            ident = ident[1:]

        # 1. Try as claim_N or bare number
        claim_num_match = _re.match(r"^claim_(\d+)$", ident)
        if claim_num_match:
            num = int(claim_num_match.group(1))
            claim = self.claims.get_by_claim_number(num)
            if claim:
                return claim

        # Also try bare number
        if ident.isdigit():
            claim = self.claims.get_by_claim_number(int(ident))
            if claim:
                return claim

        # 2. Try as UUID (direct claim_id)
        uuid_pattern = _re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.I
        )
        if uuid_pattern.match(ident):
            claim = self.claims.get(ident)
            if claim:
                return claim

        # 3. Try as friendly_id
        claim = self.claims.get_by_friendly_id(ident)
        if claim:
            return claim

        return None

    def resolve_reference(self, reference_id: str) -> ActionResult:
        """
        Resolve a @reference_id to claims.

        Uses suffix-based routing (v0.7) to determine the object type:
        - _context → context lookup (recursive claim collection)
        - _entity → entity lookup (all linked claims)
        - _tag → tag lookup (recursive tag tree claims)
        - _domain → domain filter (claims in that domain)
        - (no suffix) → claim lookup (backwards compatible)

        Falls back to legacy sequential resolution for references without
        a type suffix (backwards compatibility with v0.5-v0.6 references).

        This is the single entry point for reference resolution, used by
        both Conversation.py and REST endpoints.

        Args:
            reference_id: The friendly_id from an @reference in chat.

        Returns:
            ActionResult with data dict:
            {
                'type': 'claim' | 'context' | 'entity' | 'tag' | 'domain',
                'claims': List[Claim],
                'source_id': str,
                'source_name': str
            }
        """
        try:
            import re as _re

            # =================================================================
            # SPECIAL CASE: pkb_overview pseudo-reference
            # Returns the full overview content wrapped as a mock claim-like
            # object so it reaches the main LLM verbatim (source="referenced").
            # =================================================================
            if reference_id == "pkb_overview":
                try:
                    from .overview_manager import PKBOverviewManager
                    manager = PKBOverviewManager(self.db, self.keys, self.config)
                    result = manager.get_overview(self.user_email)

                    from ..models import Claim
                    from ..utils import generate_uuid, now_iso
                    mock_claim = Claim(
                        claim_id=generate_uuid(),
                        user_email=self.user_email,
                        claim_type="overview",
                        statement=result.content,
                        context_domain="personal",
                        created_at=now_iso(),
                        updated_at=now_iso(),
                        valid_from="1970-01-01T00:00:00Z",
                    )
                    return ActionResult(
                        success=True,
                        action="resolve",
                        object_type="reference",
                        object_id="pkb_overview",
                        data={
                            "type": "overview",
                            "claims": [mock_claim],
                            "source_id": "pkb_overview",
                            "source_name": "PKB Memory Overview",
                        },
                    )
                except Exception as e:
                    logger.warning(f"[resolve_reference] pkb_overview lookup failed: {e}")
                    return ActionResult(
                        success=False,
                        action="resolve",
                        object_type="reference",
                        errors=[f"Could not load PKB overview: {e}"],
                    )

            # =================================================================
            # FAST PATH: Suffix-based routing (v0.7)
            # =================================================================

            # 1a. _context suffix → context lookup
            if reference_id.endswith("_context"):
                context = self.contexts.get_by_friendly_id(reference_id)
                if context:
                    resolved_claims = self.contexts.resolve_claims(context.context_id)
                    logger.info(
                        f"[resolve_reference] Resolved '{reference_id}' as context '{context.name}' with {len(resolved_claims)} claims"
                    )
                    return ActionResult(
                        success=True,
                        action="resolve",
                        object_type="reference",
                        object_id=context.context_id,
                        data={
                            "type": "context",
                            "claims": resolved_claims,
                            "source_id": context.context_id,
                            "source_name": context.name,
                        },
                    )
                # Fall through to backwards-compat path if not found with _context suffix

            # 1b. _entity suffix → entity lookup
            if reference_id.endswith("_entity"):
                entity = self.entities.get_by_friendly_id(reference_id)
                if entity:
                    resolved_claims = self.entities.resolve_claims(entity.entity_id)
                    logger.info(
                        f"[resolve_reference] Resolved '{reference_id}' as entity '{entity.name}' ({entity.entity_type}) with {len(resolved_claims)} claims"
                    )
                    return ActionResult(
                        success=True,
                        action="resolve",
                        object_type="reference",
                        object_id=entity.entity_id,
                        data={
                            "type": "entity",
                            "claims": resolved_claims,
                            "source_id": entity.entity_id,
                            "source_name": f"{entity.name} ({entity.entity_type})",
                        },
                    )
                logger.info(f"[resolve_reference] No entity found for '{reference_id}'")
                return ActionResult(
                    success=False,
                    action="resolve",
                    object_type="reference",
                    errors=[f"No entity found with friendly_id: {reference_id}"],
                )

            # 1c. _tag suffix → tag lookup (recursive)
            if reference_id.endswith("_tag"):
                tag = self.tags.get_by_friendly_id(reference_id)
                if tag:
                    resolved_claims = self.tags.resolve_claims(tag.tag_id)
                    logger.info(
                        f"[resolve_reference] Resolved '{reference_id}' as tag '{tag.name}' with {len(resolved_claims)} claims"
                    )
                    return ActionResult(
                        success=True,
                        action="resolve",
                        object_type="reference",
                        object_id=tag.tag_id,
                        data={
                            "type": "tag",
                            "claims": resolved_claims,
                            "source_id": tag.tag_id,
                            "source_name": tag.name,
                        },
                    )
                logger.info(f"[resolve_reference] No tag found for '{reference_id}'")
                return ActionResult(
                    success=False,
                    action="resolve",
                    object_type="reference",
                    errors=[f"No tag found with friendly_id: {reference_id}"],
                )

            # 1d. _domain suffix → domain filter
            if reference_id.endswith("_domain"):
                domain_name = reference_id[: -len("_domain")]
                if domain_name:
                    resolved_claims = self._resolve_domain_claims(domain_name)
                    logger.info(
                        f"[resolve_reference] Resolved '{reference_id}' as domain '{domain_name}' with {len(resolved_claims)} claims"
                    )
                    return ActionResult(
                        success=True,
                        action="resolve",
                        object_type="reference",
                        object_id=domain_name,
                        data={
                            "type": "domain",
                            "claims": resolved_claims,
                            "source_id": domain_name,
                            "source_name": domain_name.replace("_", " ").title(),
                        },
                    )
                return ActionResult(
                    success=False,
                    action="resolve",
                    object_type="reference",
                    errors=[f"Invalid domain reference: {reference_id}"],
                )

            # =================================================================
            # BACKWARDS COMPATIBLE PATH: No suffix (claims + legacy contexts)
            # =================================================================

            # 2. Try as @claim_N numeric reference (e.g., "claim_42")
            claim_num_match = _re.match(r"^claim_(\d+)$", reference_id)
            if claim_num_match:
                num = int(claim_num_match.group(1))
                claim = self.claims.get_by_claim_number(num)
                if claim:
                    return ActionResult(
                        success=True,
                        action="resolve",
                        object_type="reference",
                        object_id=claim.claim_id,
                        data={
                            "type": "claim",
                            "claims": [claim],
                            "source_id": claim.claim_id,
                            "source_name": claim.statement[:80],
                        },
                    )

            # 3. Try as claim friendly_id (no suffix = claim)
            claim = self.claims.get_by_friendly_id(reference_id)
            if claim:
                return ActionResult(
                    success=True,
                    action="resolve",
                    object_type="reference",
                    object_id=claim.claim_id,
                    data={
                        "type": "claim",
                        "claims": [claim],
                        "source_id": claim.claim_id,
                        "source_name": claim.statement[:80],
                    },
                )

            # 4. Try as context friendly_id (legacy — contexts without _context suffix)
            context = self.contexts.get_by_friendly_id(reference_id)
            if context:
                resolved_claims = self.contexts.resolve_claims(context.context_id)
                logger.info(
                    f"[resolve_reference] Resolved '{reference_id}' as context (legacy, no suffix) '{context.name}' with {len(resolved_claims)} claims"
                )
                return ActionResult(
                    success=True,
                    action="resolve",
                    object_type="reference",
                    object_id=context.context_id,
                    data={
                        "type": "context",
                        "claims": resolved_claims,
                        "source_id": context.context_id,
                        "source_name": context.name,
                    },
                )

            # 5. Try as context name (fallback — case-insensitive, spaces → underscores)
            try:
                all_contexts = self.contexts.get_children(parent_context_id=None)
                for ctx in all_contexts:
                    if ctx.name and ctx.name.lower().replace(
                        " ", "_"
                    ) == reference_id.lower().replace(" ", "_"):
                        resolved_claims = self.contexts.resolve_claims(ctx.context_id)
                        logger.info(
                            f"[resolve_reference] Resolved '{reference_id}' as context by name '{ctx.name}' with {len(resolved_claims)} claims"
                        )
                        return ActionResult(
                            success=True,
                            action="resolve",
                            object_type="reference",
                            object_id=ctx.context_id,
                            data={
                                "type": "context",
                                "claims": resolved_claims,
                                "source_id": ctx.context_id,
                                "source_name": ctx.name,
                            },
                        )
            except Exception as e:
                logger.warning(f"[resolve_reference] Context name search failed: {e}")

            # 6. Not found
            logger.info(
                f"[resolve_reference] No claim, context, entity, tag, or domain found for '{reference_id}'"
            )
            return ActionResult(
                success=False,
                action="resolve",
                object_type="reference",
                errors=[
                    f"No memory, context, entity, tag, or domain found with ID: {reference_id}"
                ],
            )

        except Exception as e:
            logger.error(f"Failed to resolve reference: {e}")
            return ActionResult(
                success=False,
                action="resolve",
                object_type="reference",
                errors=[str(e)],
            )

    def _resolve_domain_claims(self, domain_name: str, limit: int = 50) -> list:
        """
        Get all claims in a given context domain.

        Used when a user references @domain_name_domain in chat.
        Queries claims where context_domain matches or context_domains
        JSON array contains the domain name.

        Args:
            domain_name: The domain key (e.g. "health", "work").
            limit: Maximum claims to return (default: 50).

        Returns:
            List of Claim objects in the domain.
        """
        from ..constants import ClaimStatus

        statuses = ClaimStatus.default_search_statuses()
        status_placeholders = ",".join(["?" for _ in statuses])

        user_filter = ""
        user_params = []
        if self.user_email:
            user_filter = " AND c.user_email = ?"
            user_params = [self.user_email]

        # Match primary context_domain OR JSON context_domains containing domain
        like_pattern = f'%"{domain_name}"%'

        sql = f"""
            SELECT c.* FROM claims c
            WHERE c.status IN ({status_placeholders}){user_filter}
              AND (c.context_domain = ? OR c.context_domains LIKE ?)
            ORDER BY c.updated_at DESC
            LIMIT ?
        """

        params = statuses + user_params + [domain_name, like_pattern, limit]
        rows = self.db.fetchall(sql, tuple(params))
        return [Claim.from_row(row) for row in rows]

    def autocomplete(self, prefix: str, limit: int = 10) -> ActionResult:
        """
        Search all PKB object types by friendly_id prefix for autocomplete.

        This powers the @autocomplete dropdown in the chat input.
        Returns matching memories, contexts, entities, tags, and domains.

        Args:
            prefix: The search prefix (characters typed after @).
            limit: Maximum results per category (default: 10).

        Returns:
            ActionResult with data dict:
            {
                'memories': [{'friendly_id', 'statement', 'claim_type', 'claim_id'}],
                'contexts': [{'friendly_id', 'name', 'description', 'context_id', 'claim_count'}],
                'entities': [{'friendly_id', 'name', 'entity_type', 'entity_id'}],
                'tags': [{'friendly_id', 'name', 'tag_id'}],
                'domains': [{'friendly_id', 'domain_name', 'display_name'}]
            }
        """
        try:
            # Search memories by friendly_id prefix
            memory_results = self.claims.search_friendly_ids(prefix, limit=limit)
            memories = [
                {
                    "friendly_id": c.friendly_id,
                    "statement": c.statement[:100],
                    "claim_type": c.claim_type,
                    "claim_id": c.claim_id,
                }
                for c in memory_results
            ]

            # Search contexts by friendly_id prefix
            context_results = self.contexts.search_friendly_ids(prefix, limit=limit)
            contexts = []
            for ctx in context_results:
                # Get claim count for each context
                claims = self.contexts.get_claims(ctx.context_id)
                contexts.append(
                    {
                        "friendly_id": ctx.friendly_id,
                        "name": ctx.name,
                        "description": ctx.description or "",
                        "context_id": ctx.context_id,
                        "claim_count": len(claims),
                    }
                )

            # Search entities by friendly_id prefix (v0.7)
            entities = []
            try:
                entity_results = self.entities.search_friendly_ids(prefix, limit=limit)
                entities = [
                    {
                        "friendly_id": e.friendly_id,
                        "name": e.name,
                        "entity_type": e.entity_type,
                        "entity_id": e.entity_id,
                    }
                    for e in entity_results
                ]
            except Exception as e:
                logger.debug(f"Entity autocomplete failed (may be pre-v7 DB): {e}")

            # Search tags by friendly_id prefix (v0.7)
            tags = []
            try:
                tag_results = self.tags.search_friendly_ids(prefix, limit=limit)
                tags = [
                    {
                        "friendly_id": t.friendly_id,
                        "name": t.name,
                        "tag_id": t.tag_id,
                    }
                    for t in tag_results
                ]
            except Exception as e:
                logger.debug(f"Tag autocomplete failed (may be pre-v7 DB): {e}")

            # Search domains by prefix (v0.7)
            # Domains are catalog entries — compute friendly_ids and filter by prefix
            domains = []
            try:
                from ..utils import domain_to_friendly_id

                all_domains = self.domain_catalog.list()
                for d in all_domains:
                    fid = domain_to_friendly_id(d["domain_name"])
                    if fid.startswith(prefix):
                        domains.append(
                            {
                                "friendly_id": fid,
                                "domain_name": d["domain_name"],
                                "display_name": d["display_name"],
                            }
                        )
                        if len(domains) >= limit:
                            break
            except Exception as e:
                logger.debug(f"Domain autocomplete failed: {e}")

            return ActionResult(
                success=True,
                action="autocomplete",
                object_type="reference",
                data={
                    "memories": memories,
                    "contexts": contexts,
                    "entities": entities,
                    "tags": tags,
                    "domains": domains,
                },
            )

        except Exception as e:
            logger.error(f"Autocomplete failed: {e}")
            return ActionResult(
                success=False,
                action="autocomplete",
                object_type="reference",
                errors=[str(e)],
            )

    # =========================================================================
    # Context Management (v0.5)
    # =========================================================================

    def add_context(
        self,
        name: str,
        friendly_id: Optional[str] = None,
        description: Optional[str] = None,
        parent_context_id: Optional[str] = None,
        claim_ids: Optional[List[str]] = None,
    ) -> ActionResult:
        """
        Create a new context (grouping of memories).

        If friendly_id is not provided, one will be auto-generated from the name.
        Optionally links claims to the context immediately.

        Args:
            name: Display name for the context.
            friendly_id: Optional user-specified friendly ID.
            description: Optional description.
            parent_context_id: Optional parent context for hierarchy.
            claim_ids: Optional list of claim IDs to link immediately.

        Returns:
            ActionResult with created Context.
        """
        try:
            context = Context.create(
                name=name,
                user_email=self.user_email,
                friendly_id=friendly_id,
                description=description,
                parent_context_id=parent_context_id,
            )

            created = self.contexts.add(context)

            # Link claims if provided
            if claim_ids:
                for cid in claim_ids:
                    self.contexts.add_claim(created.context_id, cid)

            return ActionResult(
                success=True,
                action="add",
                object_type="context",
                object_id=created.context_id,
                data=created,
            )

        except Exception as e:
            logger.error(f"Failed to add context: {e}")
            return ActionResult(
                success=False, action="add", object_type="context", errors=[str(e)]
            )

    def edit_context(self, context_id: str, **patch) -> ActionResult:
        """
        Update context fields.

        Args:
            context_id: ID of context to update.
            **patch: Fields to update (name, description, friendly_id, parent_context_id).

        Returns:
            ActionResult with updated Context.
        """
        try:
            updated = self.contexts.edit(context_id, patch)
            if updated:
                return ActionResult(
                    success=True,
                    action="edit",
                    object_type="context",
                    object_id=context_id,
                    data=updated,
                )
            return ActionResult(
                success=False,
                action="edit",
                object_type="context",
                errors=[f"Context not found: {context_id}"],
            )
        except Exception as e:
            logger.error(f"Failed to edit context: {e}")
            return ActionResult(
                success=False, action="edit", object_type="context", errors=[str(e)]
            )

    def delete_context(self, context_id: str) -> ActionResult:
        """
        Delete a context. Claims are NOT deleted, just unlinked.

        Args:
            context_id: ID of context to delete.

        Returns:
            ActionResult indicating success/failure.
        """
        try:
            if self.contexts.delete(context_id):
                return ActionResult(
                    success=True,
                    action="delete",
                    object_type="context",
                    object_id=context_id,
                )
            return ActionResult(
                success=False,
                action="delete",
                object_type="context",
                errors=[f"Context not found: {context_id}"],
            )
        except Exception as e:
            logger.error(f"Failed to delete context: {e}")
            return ActionResult(
                success=False, action="delete", object_type="context", errors=[str(e)]
            )

    def get_context(self, context_id: str) -> ActionResult:
        """
        Get a context by ID with child info and claim count.

        Args:
            context_id: ID of context to retrieve.

        Returns:
            ActionResult with Context.
        """
        try:
            context = self.contexts.get(context_id)
            if context:
                return ActionResult(
                    success=True,
                    action="get",
                    object_type="context",
                    object_id=context_id,
                    data=context,
                )
            return ActionResult(
                success=False,
                action="get",
                object_type="context",
                errors=[f"Context not found: {context_id}"],
            )
        except Exception as e:
            logger.error(f"Failed to get context: {e}")
            return ActionResult(
                success=False, action="get", object_type="context", errors=[str(e)]
            )

    def resolve_context(self, context_id: str) -> ActionResult:
        """
        Recursively get all claims under a context and its sub-contexts.

        Args:
            context_id: ID of the root context to resolve.

        Returns:
            ActionResult with List[Claim].
        """
        try:
            claims = self.contexts.resolve_claims(context_id)
            return ActionResult(
                success=True,
                action="resolve",
                object_type="context",
                object_id=context_id,
                data=claims,
            )
        except Exception as e:
            logger.error(f"Failed to resolve context: {e}")
            return ActionResult(
                success=False, action="resolve", object_type="context", errors=[str(e)]
            )

    def add_claim_to_context(self, context_id: str, claim_id: str) -> ActionResult:
        """
        Link a claim to a context.

        Args:
            context_id: ID of the context.
            claim_id: ID of the claim to link.

        Returns:
            ActionResult indicating success/failure.
        """
        try:
            if self.contexts.add_claim(context_id, claim_id):
                return ActionResult(
                    success=True,
                    action="link",
                    object_type="context_claim",
                    data={"context_id": context_id, "claim_id": claim_id},
                )
            return ActionResult(
                success=False,
                action="link",
                object_type="context_claim",
                errors=["Failed to link claim to context"],
            )
        except Exception as e:
            logger.error(f"Failed to add claim to context: {e}")
            return ActionResult(
                success=False,
                action="link",
                object_type="context_claim",
                errors=[str(e)],
            )

    def remove_claim_from_context(self, context_id: str, claim_id: str) -> ActionResult:
        """
        Unlink a claim from a context.

        Args:
            context_id: ID of the context.
            claim_id: ID of the claim to unlink.

        Returns:
            ActionResult indicating success/failure.
        """
        try:
            if self.contexts.remove_claim(context_id, claim_id):
                return ActionResult(
                    success=True,
                    action="unlink",
                    object_type="context_claim",
                    data={"context_id": context_id, "claim_id": claim_id},
                )
            return ActionResult(
                success=False,
                action="unlink",
                object_type="context_claim",
                errors=["Link not found"],
            )
        except Exception as e:
            logger.error(f"Failed to remove claim from context: {e}")
            return ActionResult(
                success=False,
                action="unlink",
                object_type="context_claim",
                errors=[str(e)],
            )

    # =========================================================================
    # Entity Linking (v0.5)
    # =========================================================================

    def link_entity_to_claim(
        self, claim_id: str, entity_id: str, role: str = "mentioned"
    ) -> ActionResult:
        """
        Link an entity to a claim with a specific role.

        Args:
            claim_id: ID of the claim.
            entity_id: ID of the entity.
            role: Role of the entity (subject, object, mentioned, about_person).

        Returns:
            ActionResult indicating success/failure.
        """
        try:
            success = link_claim_entity(self.db, claim_id, entity_id, role)
            if success:
                return ActionResult(
                    success=True,
                    action="link",
                    object_type="claim_entity",
                    data={"claim_id": claim_id, "entity_id": entity_id, "role": role},
                )
            return ActionResult(
                success=False,
                action="link",
                object_type="claim_entity",
                errors=["Failed to link entity to claim (may already exist)"],
            )
        except Exception as e:
            logger.error(f"Failed to link entity to claim: {e}")
            return ActionResult(
                success=False,
                action="link",
                object_type="claim_entity",
                errors=[str(e)],
            )

    def unlink_entity_from_claim(
        self, claim_id: str, entity_id: str, role: Optional[str] = None
    ) -> ActionResult:
        """
        Unlink an entity from a claim.

        If role is None, removes all roles for this entity-claim pair.

        Args:
            claim_id: ID of the claim.
            entity_id: ID of the entity.
            role: Optional role to remove (None = all roles).

        Returns:
            ActionResult indicating success/failure.
        """
        try:
            success = unlink_claim_entity(self.db, claim_id, entity_id, role)
            if success:
                return ActionResult(
                    success=True,
                    action="unlink",
                    object_type="claim_entity",
                    data={"claim_id": claim_id, "entity_id": entity_id, "role": role},
                )
            return ActionResult(
                success=False,
                action="unlink",
                object_type="claim_entity",
                errors=["Link not found"],
            )
        except Exception as e:
            logger.error(f"Failed to unlink entity from claim: {e}")
            return ActionResult(
                success=False,
                action="unlink",
                object_type="claim_entity",
                errors=[str(e)],
            )

    def get_claim_entities_list(self, claim_id: str) -> ActionResult:
        """
        Get all entities linked to a claim with their roles.

        Args:
            claim_id: ID of the claim.

        Returns:
            ActionResult with list of (Entity, role) tuples.
        """
        try:
            entities = get_claim_entities(self.db, claim_id)
            return ActionResult(
                success=True, action="get", object_type="claim_entity", data=entities
            )
        except Exception as e:
            logger.error(f"Failed to get claim entities: {e}")
            return ActionResult(
                success=False, action="get", object_type="claim_entity", errors=[str(e)]
            )

    # =========================================================================
    # Tag Linking
    # =========================================================================

    def link_tag_to_claim(self, claim_id: str, tag_id: str) -> ActionResult:
        """
        Link a tag to a claim.

        Two-way: the claim gets the tag and the tag's claims list includes
        the claim (both via the ``claim_tags`` join table).

        Args:
            claim_id: ID of the claim.
            tag_id: ID of the tag.

        Returns:
            ActionResult indicating success/failure.
        """
        try:
            success = link_claim_tag(self.db, claim_id, tag_id)
            if success:
                return ActionResult(
                    success=True,
                    action="link",
                    object_type="claim_tag",
                    data={"claim_id": claim_id, "tag_id": tag_id},
                )
            return ActionResult(
                success=False,
                action="link",
                object_type="claim_tag",
                errors=["Failed to link tag to claim (may already exist)"],
            )
        except Exception as e:
            logger.error(f"Failed to link tag to claim: {e}")
            return ActionResult(
                success=False,
                action="link",
                object_type="claim_tag",
                errors=[str(e)],
            )

    def unlink_tag_from_claim(self, claim_id: str, tag_id: str) -> ActionResult:
        """
        Unlink a tag from a claim.

        Args:
            claim_id: ID of the claim.
            tag_id: ID of the tag.

        Returns:
            ActionResult indicating success/failure.
        """
        try:
            success = unlink_claim_tag(self.db, claim_id, tag_id)
            if success:
                return ActionResult(
                    success=True,
                    action="unlink",
                    object_type="claim_tag",
                    data={"claim_id": claim_id, "tag_id": tag_id},
                )
            return ActionResult(
                success=False,
                action="unlink",
                object_type="claim_tag",
                errors=["Link not found"],
            )
        except Exception as e:
            logger.error(f"Failed to unlink tag from claim: {e}")
            return ActionResult(
                success=False,
                action="unlink",
                object_type="claim_tag",
                errors=[str(e)],
            )

    def get_claim_tags_list(self, claim_id: str) -> ActionResult:
        """
        Get all tags linked to a claim.

        Args:
            claim_id: ID of the claim.

        Returns:
            ActionResult with list of Tag objects.
        """
        try:
            tags = get_claim_tags(self.db, claim_id)
            return ActionResult(
                success=True, action="get", object_type="claim_tag", data=tags
            )
        except Exception as e:
            logger.error(f"Failed to get claim tags: {e}")
            return ActionResult(
                success=False, action="get", object_type="claim_tag", errors=[str(e)]
            )
