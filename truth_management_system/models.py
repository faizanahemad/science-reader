"""
Data models for PKB v0.

Defines dataclasses for all database entities:
- Claim: Atomic memory units (facts, preferences, decisions, etc.)
- Note: Longer narrative content
- Entity: Canonical people, places, topics
- Tag: Hierarchical labels
- ConflictSet: Groups of contradicting claims
- ClaimTag, ClaimEntity: Join table models

Each model includes:
- to_dict(): Convert to dictionary for DB insert
- from_row(): Create from SQLite row
- Computed fields (prefixed with _) for runtime data
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import sqlite3

try:
    import numpy as np
except ImportError:
    np = None  # Embeddings optional

from .utils import now_iso, epoch_iso, generate_uuid
from .constants import ClaimStatus, ClaimType, EntityType, EntityRole, ConflictStatus


# =============================================================================
# Column Definitions
# =============================================================================

CLAIM_COLUMNS = [
    'claim_id', 'user_email', 'claim_type', 'statement', 'subject_text', 'predicate',
    'object_text', 'context_domain', 'status', 'confidence', 'created_at',
    'updated_at', 'valid_from', 'valid_to', 'meta_json', 'retracted_at'
]

NOTE_COLUMNS = [
    'note_id', 'user_email', 'title', 'body', 'context_domain', 'meta_json',
    'created_at', 'updated_at'
]

ENTITY_COLUMNS = [
    'entity_id', 'user_email', 'entity_type', 'name', 'meta_json', 'created_at', 'updated_at'
]

TAG_COLUMNS = [
    'tag_id', 'user_email', 'name', 'parent_tag_id', 'meta_json', 'created_at', 'updated_at'
]

CONFLICT_SET_COLUMNS = [
    'conflict_set_id', 'user_email', 'status', 'resolution_notes', 'created_at', 'updated_at'
]


# =============================================================================
# Claim Model
# =============================================================================

@dataclass
class Claim:
    """
    Atomic memory unit in the personal knowledge base.
    
    Claims represent discrete pieces of personal information such as
    facts, preferences, decisions, tasks, and reminders.
    
    Attributes:
        claim_id: Unique identifier (UUID).
        user_email: Email of the user who owns this claim (for multi-user support).
        claim_type: Type from ClaimType enum.
        statement: The actual claim text.
        context_domain: Life domain from ContextDomain enum.
        status: Lifecycle state from ClaimStatus enum.
        subject_text: SPO subject (optional extraction).
        predicate: SPO predicate (optional extraction).
        object_text: SPO object (optional extraction).
        confidence: Confidence score (0.0-1.0).
        created_at: ISO timestamp of creation.
        updated_at: ISO timestamp of last update.
        valid_from: Start of temporal validity.
        valid_to: End of temporal validity (None = forever).
        meta_json: Extensible JSON metadata.
        retracted_at: ISO timestamp when soft-deleted.
        
    Computed fields (not stored):
        _embedding: Vector embedding for similarity search.
        _tags: List of tag names attached to this claim.
        _entities: List of entities attached to this claim.
    """
    claim_id: str
    claim_type: str
    statement: str
    context_domain: str
    user_email: Optional[str] = None
    status: str = ClaimStatus.ACTIVE.value
    subject_text: Optional[str] = None
    predicate: Optional[str] = None
    object_text: Optional[str] = None
    confidence: Optional[float] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    valid_from: str = field(default_factory=epoch_iso)
    valid_to: Optional[str] = None
    meta_json: Optional[str] = None
    retracted_at: Optional[str] = None
    
    # Computed fields (not stored in DB)
    _embedding: Optional[Any] = field(default=None, repr=False, compare=False)
    _tags: List[str] = field(default_factory=list, repr=False, compare=False)
    _entities: List[Dict] = field(default_factory=list, repr=False, compare=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for DB insert (excludes computed fields).
        
        Returns:
            Dictionary with column names as keys.
        """
        return {k: getattr(self, k) for k in CLAIM_COLUMNS}
    
    def to_insert_tuple(self) -> tuple:
        """
        Return tuple for SQL INSERT in column order.
        
        Returns:
            Tuple of values matching CLAIM_COLUMNS order.
        """
        return tuple(getattr(self, k) for k in CLAIM_COLUMNS)
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Claim':
        """
        Create Claim from SQLite row.
        
        Args:
            row: SQLite Row object with claim data.
            
        Returns:
            New Claim instance.
        """
        row_keys = row.keys() if hasattr(row, 'keys') else CLAIM_COLUMNS
        return cls(**{k: row[k] for k in CLAIM_COLUMNS if k in row_keys})
    
    @classmethod
    def create(
        cls,
        statement: str,
        claim_type: str,
        context_domain: str,
        user_email: Optional[str] = None,
        **kwargs
    ) -> 'Claim':
        """
        Factory method to create a new claim with generated ID.
        
        Args:
            statement: The claim text.
            claim_type: Type from ClaimType enum.
            context_domain: Domain from ContextDomain enum.
            user_email: Email of the owning user (for multi-user support).
            **kwargs: Additional fields.
            
        Returns:
            New Claim instance with generated claim_id.
        """
        # Filter out None values so defaults are used
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return cls(
            claim_id=generate_uuid(),
            claim_type=claim_type,
            statement=statement,
            context_domain=context_domain,
            user_email=user_email,
            **filtered_kwargs
        )
    
    @property
    def is_contested(self) -> bool:
        """Check if this claim is in contested status."""
        return self.status == ClaimStatus.CONTESTED.value
    
    @property
    def is_active(self) -> bool:
        """Check if this claim is active."""
        return self.status == ClaimStatus.ACTIVE.value
    
    @property
    def is_retracted(self) -> bool:
        """Check if this claim has been soft-deleted."""
        return self.status == ClaimStatus.RETRACTED.value


# =============================================================================
# Note Model
# =============================================================================

@dataclass
class Note:
    """
    Longer narrative content in the knowledge base.
    
    Notes are for freeform text that doesn't fit the structured claim format.
    They can be linked to claims via entities/tags.
    
    Attributes:
        note_id: Unique identifier (UUID).
        user_email: Email of the user who owns this note (for multi-user support).
        body: The note content.
        title: Optional title.
        context_domain: Life domain for filtering.
        meta_json: Extensible JSON metadata.
        created_at: ISO timestamp of creation.
        updated_at: ISO timestamp of last update.
    """
    note_id: str
    body: str
    user_email: Optional[str] = None
    title: Optional[str] = None
    context_domain: Optional[str] = None
    meta_json: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    
    # Computed fields
    _embedding: Optional[Any] = field(default=None, repr=False, compare=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DB insert."""
        return {k: getattr(self, k) for k in NOTE_COLUMNS}
    
    def to_insert_tuple(self) -> tuple:
        """Return tuple for SQL INSERT."""
        return tuple(getattr(self, k) for k in NOTE_COLUMNS)
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Note':
        """Create Note from SQLite row."""
        row_keys = row.keys() if hasattr(row, 'keys') else NOTE_COLUMNS
        return cls(**{k: row[k] for k in NOTE_COLUMNS if k in row_keys})
    
    @classmethod
    def create(cls, body: str, user_email: Optional[str] = None, **kwargs) -> 'Note':
        """
        Factory method to create new note with generated ID.
        
        Args:
            body: The note content.
            user_email: Email of the owning user (for multi-user support).
            **kwargs: Additional fields (title, context_domain, meta_json).
            
        Returns:
            New Note instance with generated note_id.
        """
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        return cls(note_id=generate_uuid(), body=body, user_email=user_email, **filtered_kwargs)


# =============================================================================
# Entity Model
# =============================================================================

@dataclass
class Entity:
    """
    Canonical reference to a person, place, topic, etc.
    
    Entities enable linking claims about the same subject
    and provide structured navigation.
    
    Attributes:
        entity_id: Unique identifier (UUID).
        user_email: Email of the user who owns this entity (for multi-user support).
        entity_type: Type from EntityType enum.
        name: Display name of the entity.
        meta_json: Extensible JSON metadata.
        created_at: ISO timestamp of creation.
        updated_at: ISO timestamp of last update.
    """
    entity_id: str
    entity_type: str
    name: str
    user_email: Optional[str] = None
    meta_json: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DB insert."""
        return {k: getattr(self, k) for k in ENTITY_COLUMNS}
    
    def to_insert_tuple(self) -> tuple:
        """Return tuple for SQL INSERT."""
        return tuple(getattr(self, k) for k in ENTITY_COLUMNS)
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Entity':
        """Create Entity from SQLite row."""
        row_keys = row.keys() if hasattr(row, 'keys') else ENTITY_COLUMNS
        return cls(**{k: row[k] for k in ENTITY_COLUMNS if k in row_keys})
    
    @classmethod
    def create(cls, name: str, entity_type: str, user_email: Optional[str] = None, **kwargs) -> 'Entity':
        """
        Factory method to create new entity with generated ID.
        
        Args:
            name: Display name of the entity.
            entity_type: Type from EntityType enum.
            user_email: Email of the owning user (for multi-user support).
            **kwargs: Additional fields (meta_json).
            
        Returns:
            New Entity instance with generated entity_id.
        """
        return cls(
            entity_id=generate_uuid(),
            entity_type=entity_type,
            name=name,
            user_email=user_email,
            **kwargs
        )


# =============================================================================
# Tag Model
# =============================================================================

@dataclass
class Tag:
    """
    Hierarchical label for organizing claims.
    
    Tags can form a hierarchy via parent_tag_id for
    structured organization (e.g., health/fitness/running).
    
    Attributes:
        tag_id: Unique identifier (UUID).
        user_email: Email of the user who owns this tag (for multi-user support).
        name: Tag name (unique within parent).
        parent_tag_id: Parent tag for hierarchy (optional).
        meta_json: Extensible JSON metadata.
        created_at: ISO timestamp of creation.
        updated_at: ISO timestamp of last update.
    """
    tag_id: str
    name: str
    user_email: Optional[str] = None
    parent_tag_id: Optional[str] = None
    meta_json: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    
    # Computed fields
    _children: List['Tag'] = field(default_factory=list, repr=False, compare=False)
    _full_path: Optional[str] = field(default=None, repr=False, compare=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DB insert."""
        return {k: getattr(self, k) for k in TAG_COLUMNS}
    
    def to_insert_tuple(self) -> tuple:
        """Return tuple for SQL INSERT."""
        return tuple(getattr(self, k) for k in TAG_COLUMNS)
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Tag':
        """Create Tag from SQLite row."""
        row_keys = row.keys() if hasattr(row, 'keys') else TAG_COLUMNS
        return cls(**{k: row[k] for k in TAG_COLUMNS if k in row_keys})
    
    @classmethod
    def create(cls, name: str, parent_tag_id: Optional[str] = None, user_email: Optional[str] = None, **kwargs) -> 'Tag':
        """
        Factory method to create new tag with generated ID.
        
        Args:
            name: Tag name.
            parent_tag_id: Optional parent for hierarchy.
            user_email: Email of the owning user (for multi-user support).
            **kwargs: Additional fields (meta_json).
            
        Returns:
            New Tag instance with generated tag_id.
        """
        return cls(
            tag_id=generate_uuid(),
            name=name,
            user_email=user_email,
            parent_tag_id=parent_tag_id,
            **kwargs
        )


# =============================================================================
# ConflictSet Model
# =============================================================================

@dataclass
class ConflictSet:
    """
    Group of contradicting claims for resolution.
    
    When contradicting claims are detected, they are grouped
    into a conflict set for user review and resolution.
    
    Attributes:
        conflict_set_id: Unique identifier (UUID).
        user_email: Email of the user who owns this conflict set (for multi-user support).
        status: State from ConflictStatus enum.
        resolution_notes: User notes on resolution.
        created_at: ISO timestamp of creation.
        updated_at: ISO timestamp of last update.
        member_claim_ids: List of claim IDs in this conflict (populated from join).
    """
    conflict_set_id: str
    user_email: Optional[str] = None
    status: str = ConflictStatus.OPEN.value
    resolution_notes: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    
    # Populated from join table
    member_claim_ids: List[str] = field(default_factory=list, compare=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DB insert."""
        return {k: getattr(self, k) for k in CONFLICT_SET_COLUMNS}
    
    def to_insert_tuple(self) -> tuple:
        """Return tuple for SQL INSERT."""
        return tuple(getattr(self, k) for k in CONFLICT_SET_COLUMNS)
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'ConflictSet':
        """Create ConflictSet from SQLite row."""
        row_keys = row.keys() if hasattr(row, 'keys') else CONFLICT_SET_COLUMNS
        return cls(**{k: row[k] for k in CONFLICT_SET_COLUMNS if k in row_keys})
    
    @classmethod
    def create(cls, user_email: Optional[str] = None, **kwargs) -> 'ConflictSet':
        """
        Factory method to create new conflict set with generated ID.
        
        Args:
            user_email: Email of the owning user (for multi-user support).
            **kwargs: Additional fields (resolution_notes).
            
        Returns:
            New ConflictSet instance with generated conflict_set_id.
        """
        return cls(conflict_set_id=generate_uuid(), user_email=user_email, **kwargs)
    
    @property
    def is_open(self) -> bool:
        """Check if conflict is still open."""
        return self.status == ConflictStatus.OPEN.value
    
    @property
    def is_resolved(self) -> bool:
        """Check if conflict has been resolved."""
        return self.status == ConflictStatus.RESOLVED.value


# =============================================================================
# Join Table Models (for type safety in CRUD operations)
# =============================================================================

@dataclass
class ClaimTag:
    """
    Join between claims and tags (many-to-many).
    
    Attributes:
        claim_id: Foreign key to claims table.
        tag_id: Foreign key to tags table.
    """
    claim_id: str
    tag_id: str
    
    def to_tuple(self) -> tuple:
        """Return tuple for SQL INSERT."""
        return (self.claim_id, self.tag_id)


@dataclass
class ClaimEntity:
    """
    Join between claims and entities with role (many-to-many).
    
    Attributes:
        claim_id: Foreign key to claims table.
        entity_id: Foreign key to entities table.
        role: Role from EntityRole enum.
    """
    claim_id: str
    entity_id: str
    role: str
    
    def to_tuple(self) -> tuple:
        """Return tuple for SQL INSERT."""
        return (self.claim_id, self.entity_id, self.role)


@dataclass
class ConflictSetMember:
    """
    Join between conflict sets and claims.
    
    Attributes:
        conflict_set_id: Foreign key to conflict_sets table.
        claim_id: Foreign key to claims table.
    """
    conflict_set_id: str
    claim_id: str
    
    def to_tuple(self) -> tuple:
        """Return tuple for SQL INSERT."""
        return (self.conflict_set_id, self.claim_id)
