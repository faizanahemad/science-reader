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

        try:
            # Auto-extract if enabled and LLM available
            if auto_extract and self.llm:
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

                # Check for similar claims
                existing = self.claims.get_active(context_domain=context_domain)
                similar = self.llm.check_similarity(statement, existing[:100])

                if similar:
                    for claim, sim, relation in similar[:3]:
                        if relation == "duplicate":
                            warnings.append(
                                f"Very similar claim exists: {claim.claim_id[:8]} ({sim:.2f})"
                            )
                        elif relation == "contradicts":
                            warnings.append(
                                f"May contradict claim: {claim.claim_id[:8]} ({sim:.2f})"
                            )

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
            elif auto_extract and self.llm:
                # Auto-generate questions using LLM
                try:
                    questions = self.llm.generate_possible_questions(
                        statement, claim_type
                    )
                    if questions:
                        possible_questions_json = _json.dumps(questions)
                except Exception as e:
                    logger.warning(f"Failed to auto-generate questions: {e}")

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
                result = self.add_claim(
                    statement=statement,
                    claim_type=claim_type,
                    context_domain=context_domain,
                    tags=tags,
                    entities=entities,
                    auto_extract=auto_extract,
                    confidence=confidence,
                    meta_json=meta_json,
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

            # Save the updated claim
            updated_claim = self.claims.edit(claim_id, {"meta_json": json.dumps(meta)})

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
