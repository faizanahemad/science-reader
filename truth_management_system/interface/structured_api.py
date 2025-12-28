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
from ..models import Claim, Note, Entity, Tag, ConflictSet
from ..constants import ClaimType, ClaimStatus, ContextDomain, EntityType
from ..crud import ClaimCRUD, NoteCRUD, EntityCRUD, TagCRUD, ConflictCRUD
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
        user_email: Optional[str] = None
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
        
        # Initialize search (we'll pass user_email in search methods)
        self.search_strategy = HybridSearchStrategy(db, keys, config)
        self.notes_search = NotesSearchStrategy(db, keys, config)
        
        # Initialize LLM helpers
        if keys.get("OPENROUTER_API_KEY"):
            self.llm = LLMHelpers(keys, config)
        else:
            self.llm = None
    
    def for_user(self, user_email: str) -> 'StructuredAPI':
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
            db=self.db,
            keys=self.keys,
            config=self.config,
            user_email=user_email
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
        **kwargs
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
                if claim_type == 'observation':
                    claim_type = extraction.claim_type
                
                # Check for similar claims
                existing = self.claims.get_active(context_domain=context_domain)
                similar = self.llm.check_similarity(statement, existing[:100])
                
                if similar:
                    for claim, sim, relation in similar[:3]:
                        if relation == 'duplicate':
                            warnings.append(f"Very similar claim exists: {claim.claim_id[:8]} ({sim:.2f})")
                        elif relation == 'contradicts':
                            warnings.append(f"May contradict claim: {claim.claim_id[:8]} ({sim:.2f})")
            
            # Create claim (user_email is applied by ClaimCRUD if set)
            claim = Claim.create(
                statement=statement,
                claim_type=claim_type,
                context_domain=context_domain,
                user_email=self.user_email,
                confidence=confidence,
                valid_from=valid_from,
                valid_to=valid_to,
                meta_json=meta_json
            )
            
            # Add to database
            claim = self.claims.add(claim, tags=tags, entities=entities)
            
            return ActionResult(
                success=True,
                action='add',
                object_type='claim',
                object_id=claim.claim_id,
                data=claim,
                warnings=warnings
            )
            
        except Exception as e:
            logger.error(f"Failed to add claim: {e}")
            return ActionResult(
                success=False,
                action='add',
                object_type='claim',
                errors=[str(e)]
            )
    
    def edit_claim(
        self,
        claim_id: str,
        **patch
    ) -> ActionResult:
        """
        Edit an existing claim.
        
        Args:
            claim_id: ID of claim to edit.
            **patch: Fields to update.
            
        Returns:
            ActionResult with updated claim.
        """
        try:
            claim = self.claims.edit(claim_id, patch)
            
            if claim:
                return ActionResult(
                    success=True,
                    action='edit',
                    object_type='claim',
                    object_id=claim_id,
                    data=claim
                )
            else:
                return ActionResult(
                    success=False,
                    action='edit',
                    object_type='claim',
                    object_id=claim_id,
                    errors=['Claim not found']
                )
                
        except Exception as e:
            logger.error(f"Failed to edit claim: {e}")
            return ActionResult(
                success=False,
                action='edit',
                object_type='claim',
                object_id=claim_id,
                errors=[str(e)]
            )
    
    def delete_claim(
        self,
        claim_id: str,
        mode: str = "retract"
    ) -> ActionResult:
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
                    action='delete',
                    object_type='claim',
                    object_id=claim_id,
                    data=claim
                )
            else:
                return ActionResult(
                    success=False,
                    action='delete',
                    object_type='claim',
                    object_id=claim_id,
                    errors=['Claim not found']
                )
                
        except Exception as e:
            logger.error(f"Failed to delete claim: {e}")
            return ActionResult(
                success=False,
                action='delete',
                object_type='claim',
                object_id=claim_id,
                errors=[str(e)]
            )
    
    def get_claim(self, claim_id: str) -> ActionResult:
        """Get a claim by ID."""
        claim = self.claims.get(claim_id)
        
        if claim:
            return ActionResult(
                success=True,
                action='get',
                object_type='claim',
                object_id=claim_id,
                data=claim
            )
        else:
            return ActionResult(
                success=False,
                action='get',
                object_type='claim',
                object_id=claim_id,
                errors=['Claim not found']
            )
    
    def add_claims_bulk(
        self,
        claims: List[Dict],
        auto_extract: bool = False,
        stop_on_error: bool = False
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
                statement = claim_data.get('statement', '').strip()
                
                if not statement:
                    results.append({
                        'index': i,
                        'success': False,
                        'claim_id': None,
                        'error': 'Empty statement',
                        'warnings': []
                    })
                    failed_count += 1
                    if stop_on_error:
                        break
                    continue
                
                claim_type = claim_data.get('claim_type', 'fact')
                context_domain = claim_data.get('context_domain', 'personal')
                tags = claim_data.get('tags', [])
                entities = claim_data.get('entities', [])
                confidence = claim_data.get('confidence')
                meta_json = claim_data.get('meta_json')
                
                # Add the claim using existing add_claim method
                result = self.add_claim(
                    statement=statement,
                    claim_type=claim_type,
                    context_domain=context_domain,
                    tags=tags,
                    entities=entities,
                    auto_extract=auto_extract,
                    confidence=confidence,
                    meta_json=meta_json
                )
                
                if result.success:
                    results.append({
                        'index': i,
                        'success': True,
                        'claim_id': result.object_id,
                        'error': None,
                        'warnings': result.warnings
                    })
                    added_count += 1
                else:
                    results.append({
                        'index': i,
                        'success': False,
                        'claim_id': None,
                        'error': '; '.join(result.errors),
                        'warnings': result.warnings
                    })
                    failed_count += 1
                    if stop_on_error:
                        break
                        
            except Exception as e:
                logger.error(f"Failed to add claim at index {i}: {e}")
                results.append({
                    'index': i,
                    'success': False,
                    'claim_id': None,
                    'error': str(e),
                    'warnings': []
                })
                failed_count += 1
                if stop_on_error:
                    break
        
        return ActionResult(
            success=failed_count == 0,
            action='bulk_add',
            object_type='claim',
            data={
                'results': results,
                'added_count': added_count,
                'failed_count': failed_count,
                'total': len(claims)
            },
            warnings=[f"Failed to add {failed_count} claims"] if failed_count > 0 else []
        )
    
    # =========================================================================
    # Notes API
    # =========================================================================
    
    def add_note(
        self,
        body: str,
        title: Optional[str] = None,
        context_domain: Optional[str] = None,
        meta_json: Optional[str] = None
    ) -> ActionResult:
        """Add a new note."""
        try:
            note = Note.create(
                body=body,
                title=title,
                context_domain=context_domain,
                meta_json=meta_json
            )
            
            note = self.notes.add(note)
            
            return ActionResult(
                success=True,
                action='add',
                object_type='note',
                object_id=note.note_id,
                data=note
            )
            
        except Exception as e:
            logger.error(f"Failed to add note: {e}")
            return ActionResult(
                success=False,
                action='add',
                object_type='note',
                errors=[str(e)]
            )
    
    def edit_note(self, note_id: str, **patch) -> ActionResult:
        """Edit an existing note."""
        try:
            note = self.notes.edit(note_id, patch)
            
            if note:
                return ActionResult(
                    success=True,
                    action='edit',
                    object_type='note',
                    object_id=note_id,
                    data=note
                )
            else:
                return ActionResult(
                    success=False,
                    action='edit',
                    object_type='note',
                    object_id=note_id,
                    errors=['Note not found']
                )
                
        except Exception as e:
            return ActionResult(
                success=False,
                action='edit',
                object_type='note',
                object_id=note_id,
                errors=[str(e)]
            )
    
    def delete_note(self, note_id: str) -> ActionResult:
        """Delete a note."""
        try:
            deleted = self.notes.delete(note_id)
            
            return ActionResult(
                success=deleted,
                action='delete',
                object_type='note',
                object_id=note_id,
                errors=[] if deleted else ['Note not found']
            )
            
        except Exception as e:
            return ActionResult(
                success=False,
                action='delete',
                object_type='note',
                object_id=note_id,
                errors=[str(e)]
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
        include_contested: bool = True
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
                include_contested=include_contested,
                user_email=self.user_email
            )
            
            if filters:
                if 'context_domains' in filters:
                    search_filters.context_domains = filters['context_domains']
                if 'claim_types' in filters:
                    search_filters.claim_types = filters['claim_types']
                if 'statuses' in filters:
                    search_filters.statuses = filters['statuses']
                if 'valid_at' in filters:
                    search_filters.valid_at = filters['valid_at']
            
            # Execute search
            if strategy == "hybrid":
                results = self.search_strategy.search(query, k=k, filters=search_filters)
            elif strategy == "fts":
                results = self.search_strategy.search(query, strategy_names=["fts"], k=k, filters=search_filters)
            elif strategy == "embedding":
                results = self.search_strategy.search(query, strategy_names=["embedding"], k=k, filters=search_filters)
            elif strategy == "rerank":
                results = self.search_strategy.search_with_rerank(query, k=k, filters=search_filters)
            else:
                results = self.search_strategy.search(query, k=k, filters=search_filters)
            
            return ActionResult(
                success=True,
                action='search',
                object_type='claim',
                data=results
            )
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return ActionResult(
                success=False,
                action='search',
                object_type='claim',
                errors=[str(e)]
            )
    
    def search_notes(
        self,
        query: str,
        k: int = 20,
        context_domain: Optional[str] = None
    ) -> ActionResult:
        """Search notes."""
        try:
            results = self.notes_search.search(query, k=k, context_domain=context_domain)
            
            return ActionResult(
                success=True,
                action='search',
                object_type='note',
                data=results
            )
            
        except Exception as e:
            return ActionResult(
                success=False,
                action='search',
                object_type='note',
                errors=[str(e)]
            )
    
    # =========================================================================
    # Entities & Tags API
    # =========================================================================
    
    def add_entity(
        self,
        name: str,
        entity_type: str,
        meta_json: Optional[str] = None
    ) -> ActionResult:
        """Add a new entity."""
        try:
            entity = Entity.create(
                name=name,
                entity_type=entity_type,
                meta_json=meta_json
            )
            
            entity = self.entities.add(entity)
            
            return ActionResult(
                success=True,
                action='add',
                object_type='entity',
                object_id=entity.entity_id,
                data=entity
            )
            
        except Exception as e:
            return ActionResult(
                success=False,
                action='add',
                object_type='entity',
                errors=[str(e)]
            )
    
    def add_tag(
        self,
        name: str,
        parent_tag_id: Optional[str] = None,
        meta_json: Optional[str] = None
    ) -> ActionResult:
        """Add a new tag."""
        try:
            tag = Tag.create(
                name=name,
                parent_tag_id=parent_tag_id,
                meta_json=meta_json
            )
            
            tag = self.tags.add(tag)
            
            return ActionResult(
                success=True,
                action='add',
                object_type='tag',
                object_id=tag.tag_id,
                data=tag
            )
            
        except Exception as e:
            return ActionResult(
                success=False,
                action='add',
                object_type='tag',
                errors=[str(e)]
            )
    
    # =========================================================================
    # Conflicts API
    # =========================================================================
    
    def create_conflict_set(
        self,
        claim_ids: List[str],
        notes: Optional[str] = None
    ) -> ActionResult:
        """Create a conflict set from 2+ claims."""
        try:
            conflict_set = self.conflicts.create(claim_ids, notes)
            
            return ActionResult(
                success=True,
                action='create_conflict',
                object_type='conflict_set',
                object_id=conflict_set.conflict_set_id,
                data=conflict_set
            )
            
        except ValueError as e:
            return ActionResult(
                success=False,
                action='create_conflict',
                object_type='conflict_set',
                errors=[str(e)]
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action='create_conflict',
                object_type='conflict_set',
                errors=[str(e)]
            )
    
    def resolve_conflict_set(
        self,
        conflict_set_id: str,
        resolution_notes: str,
        winning_claim_id: Optional[str] = None
    ) -> ActionResult:
        """Resolve a conflict set."""
        try:
            conflict_set = self.conflicts.resolve(
                conflict_set_id,
                resolution_notes,
                winning_claim_id
            )
            
            if conflict_set:
                return ActionResult(
                    success=True,
                    action='resolve_conflict',
                    object_type='conflict_set',
                    object_id=conflict_set_id,
                    data=conflict_set
                )
            else:
                return ActionResult(
                    success=False,
                    action='resolve_conflict',
                    object_type='conflict_set',
                    object_id=conflict_set_id,
                    errors=['Conflict set not found']
                )
                
        except Exception as e:
            return ActionResult(
                success=False,
                action='resolve_conflict',
                object_type='conflict_set',
                object_id=conflict_set_id,
                errors=[str(e)]
            )
    
    def get_open_conflicts(self) -> ActionResult:
        """Get all open conflict sets."""
        try:
            conflicts = self.conflicts.get_open()
            
            return ActionResult(
                success=True,
                action='get',
                object_type='conflict_set',
                data=conflicts
            )
            
        except Exception as e:
            return ActionResult(
                success=False,
                action='get',
                object_type='conflict_set',
                errors=[str(e)]
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
                    action='pin',
                    object_type='claim',
                    object_id=claim_id,
                    errors=['Claim not found']
                )
            
            # Parse existing meta_json or create new
            meta = {}
            if claim.meta_json:
                try:
                    meta = json.loads(claim.meta_json)
                except json.JSONDecodeError:
                    meta = {}
            
            # Update pinned status
            meta['pinned'] = pin
            
            # Save the updated claim
            updated_claim = self.claims.edit(claim_id, {'meta_json': json.dumps(meta)})
            
            if updated_claim:
                return ActionResult(
                    success=True,
                    action='pin' if pin else 'unpin',
                    object_type='claim',
                    object_id=claim_id,
                    data=updated_claim
                )
            else:
                return ActionResult(
                    success=False,
                    action='pin',
                    object_type='claim',
                    object_id=claim_id,
                    errors=['Failed to update claim']
                )
                
        except Exception as e:
            logger.error(f"Failed to pin claim: {e}")
            return ActionResult(
                success=False,
                action='pin',
                object_type='claim',
                object_id=claim_id,
                errors=[str(e)]
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
                filters={'status': ClaimStatus.ACTIVE.value},
                limit=500
            )  # Get more to filter
            
            pinned_claims = []
            for claim in all_claims:
                if claim.meta_json:
                    try:
                        meta = json.loads(claim.meta_json)
                        if meta.get('pinned', False):
                            pinned_claims.append(claim)
                            if len(pinned_claims) >= limit:
                                break
                    except json.JSONDecodeError:
                        continue
            
            return ActionResult(
                success=True,
                action='get_pinned',
                object_type='claim',
                data=pinned_claims
            )
            
        except Exception as e:
            logger.error(f"Failed to get pinned claims: {e}")
            return ActionResult(
                success=False,
                action='get_pinned',
                object_type='claim',
                errors=[str(e)]
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
                success=True,
                action='get_by_ids',
                object_type='claim',
                data=claims
            )
            
        except Exception as e:
            logger.error(f"Failed to get claims by IDs: {e}")
            return ActionResult(
                success=False,
                action='get_by_ids',
                object_type='claim',
                errors=[str(e)]
            )
