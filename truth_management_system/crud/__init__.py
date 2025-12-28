"""
CRUD operations for PKB v0.

This module provides data access classes for all PKB entities:
- ClaimCRUD: Manage claims (atomic memory units)
- NoteCRUD: Manage notes (narrative content)
- EntityCRUD: Manage entities (people, places, topics)
- TagCRUD: Manage hierarchical tags
- ConflictCRUD: Manage conflict sets

All CRUD classes inherit from BaseCRUD and provide:
- add(): Create new records
- get(): Retrieve by ID
- edit(): Update existing records
- delete(): Soft-delete (claims) or hard-delete
- list(): Query with filters

Link functions for join tables:
- link_claim_tag(), unlink_claim_tag()
- link_claim_entity(), unlink_claim_entity()
"""

from .base import BaseCRUD, sync_claim_to_fts, sync_note_to_fts
from .claims import ClaimCRUD
from .notes import NoteCRUD
from .entities import EntityCRUD
from .tags import TagCRUD
from .conflicts import ConflictCRUD
from .links import (
    link_claim_tag,
    unlink_claim_tag,
    link_claim_entity,
    unlink_claim_entity,
    get_claim_tags,
    get_claim_entities,
    get_tags_for_claims,
    get_entities_for_claims,
)

__all__ = [
    'BaseCRUD',
    'ClaimCRUD',
    'NoteCRUD',
    'EntityCRUD',
    'TagCRUD',
    'ConflictCRUD',
    'sync_claim_to_fts',
    'sync_note_to_fts',
    'link_claim_tag',
    'unlink_claim_tag',
    'link_claim_entity',
    'unlink_claim_entity',
    'get_claim_tags',
    'get_claim_entities',
    'get_tags_for_claims',
    'get_entities_for_claims',
]
