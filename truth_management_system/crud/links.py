"""
Link management functions for PKB v0.

Provides functions for managing claim-tag and claim-entity relationships:
- link_claim_tag(): Add tag to claim
- unlink_claim_tag(): Remove tag from claim
- link_claim_entity(): Add entity to claim with role
- unlink_claim_entity(): Remove entity from claim
- get_claim_tags(): Get all tags for a claim
- get_claim_entities(): Get all entities for a claim
- get_tags_for_claims(): Batch get tags for multiple claims
- get_entities_for_claims(): Batch get entities for multiple claims

These functions operate on the claim_tags and claim_entities join tables.
"""

import logging
from typing import List, Dict, Tuple, Optional

from ..database import PKBDatabase
from ..models import Tag, Entity
from ..utils import generate_uuid, now_iso

logger = logging.getLogger(__name__)


# =============================================================================
# Claim-Tag Links
# =============================================================================

def link_claim_tag(
    db: PKBDatabase,
    claim_id: str,
    tag_id: str
) -> bool:
    """
    Add a tag to a claim.
    
    Args:
        db: PKBDatabase instance.
        claim_id: ID of claim.
        tag_id: ID of tag to add.
        
    Returns:
        True if link was created, False if already exists.
    """
    with db.transaction() as conn:
        try:
            conn.execute(
                "INSERT INTO claim_tags (claim_id, tag_id) VALUES (?, ?)",
                (claim_id, tag_id)
            )
            logger.debug(f"Linked claim {claim_id} to tag {tag_id}")
            return True
        except Exception:
            # Already exists (primary key violation)
            return False


def unlink_claim_tag(
    db: PKBDatabase,
    claim_id: str,
    tag_id: str
) -> bool:
    """
    Remove a tag from a claim.
    
    Args:
        db: PKBDatabase instance.
        claim_id: ID of claim.
        tag_id: ID of tag to remove.
        
    Returns:
        True if link was removed, False if didn't exist.
    """
    with db.transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM claim_tags WHERE claim_id = ? AND tag_id = ?",
            (claim_id, tag_id)
        )
        removed = cursor.rowcount > 0
        if removed:
            logger.debug(f"Unlinked claim {claim_id} from tag {tag_id}")
        return removed


def get_claim_tags(
    db: PKBDatabase,
    claim_id: str
) -> List[Tag]:
    """
    Get all tags for a claim.
    
    Args:
        db: PKBDatabase instance.
        claim_id: ID of claim.
        
    Returns:
        List of Tag objects linked to the claim.
    """
    rows = db.fetchall("""
        SELECT t.* FROM tags t
        JOIN claim_tags ct ON t.tag_id = ct.tag_id
        WHERE ct.claim_id = ?
        ORDER BY t.name
    """, (claim_id,))
    
    return [Tag.from_row(row) for row in rows]


def get_tags_for_claims(
    db: PKBDatabase,
    claim_ids: List[str]
) -> Dict[str, List[Tag]]:
    """
    Batch get tags for multiple claims.
    
    More efficient than calling get_claim_tags for each claim.
    
    Args:
        db: PKBDatabase instance.
        claim_ids: List of claim IDs.
        
    Returns:
        Dict mapping claim_id to list of Tag objects.
    """
    if not claim_ids:
        return {}
    
    placeholders = ','.join(['?' for _ in claim_ids])
    rows = db.fetchall(f"""
        SELECT ct.claim_id, t.* FROM tags t
        JOIN claim_tags ct ON t.tag_id = ct.tag_id
        WHERE ct.claim_id IN ({placeholders})
        ORDER BY t.name
    """, tuple(claim_ids))
    
    result: Dict[str, List[Tag]] = {cid: [] for cid in claim_ids}
    for row in rows:
        claim_id = row['claim_id']
        if claim_id in result:
            result[claim_id].append(Tag.from_row(row))
    
    return result


def set_claim_tags(
    db: PKBDatabase,
    claim_id: str,
    tag_ids: List[str]
) -> None:
    """
    Set the exact set of tags for a claim.
    
    Removes existing tags and adds new ones in a single transaction.
    
    Args:
        db: PKBDatabase instance.
        claim_id: ID of claim.
        tag_ids: List of tag IDs to set (replaces existing).
    """
    with db.transaction() as conn:
        # Remove existing
        conn.execute("DELETE FROM claim_tags WHERE claim_id = ?", (claim_id,))
        
        # Add new
        for tag_id in tag_ids:
            conn.execute(
                "INSERT INTO claim_tags (claim_id, tag_id) VALUES (?, ?)",
                (claim_id, tag_id)
            )
        
        logger.debug(f"Set {len(tag_ids)} tags for claim {claim_id}")


# =============================================================================
# Claim-Entity Links
# =============================================================================

def link_claim_entity(
    db: PKBDatabase,
    claim_id: str,
    entity_id: str,
    role: str
) -> bool:
    """
    Add an entity to a claim with a specific role.
    
    Args:
        db: PKBDatabase instance.
        claim_id: ID of claim.
        entity_id: ID of entity to add.
        role: Entity role (subject, object, mentioned, about_person).
        
    Returns:
        True if link was created, False if already exists.
    """
    with db.transaction() as conn:
        try:
            conn.execute(
                "INSERT INTO claim_entities (claim_id, entity_id, role) VALUES (?, ?, ?)",
                (claim_id, entity_id, role)
            )
            logger.debug(f"Linked claim {claim_id} to entity {entity_id} with role {role}")
            return True
        except Exception:
            # Already exists (primary key violation)
            return False


def unlink_claim_entity(
    db: PKBDatabase,
    claim_id: str,
    entity_id: str,
    role: Optional[str] = None
) -> bool:
    """
    Remove an entity link from a claim.
    
    Args:
        db: PKBDatabase instance.
        claim_id: ID of claim.
        entity_id: ID of entity to remove.
        role: Optional role filter (if None, removes all roles).
        
    Returns:
        True if any links were removed.
    """
    with db.transaction() as conn:
        if role:
            cursor = conn.execute(
                "DELETE FROM claim_entities WHERE claim_id = ? AND entity_id = ? AND role = ?",
                (claim_id, entity_id, role)
            )
        else:
            cursor = conn.execute(
                "DELETE FROM claim_entities WHERE claim_id = ? AND entity_id = ?",
                (claim_id, entity_id)
            )
        
        removed = cursor.rowcount > 0
        if removed:
            logger.debug(f"Unlinked claim {claim_id} from entity {entity_id}")
        return removed


def get_claim_entities(
    db: PKBDatabase,
    claim_id: str
) -> List[Tuple[Entity, str]]:
    """
    Get all entities for a claim with their roles.
    
    Args:
        db: PKBDatabase instance.
        claim_id: ID of claim.
        
    Returns:
        List of (Entity, role) tuples.
    """
    rows = db.fetchall("""
        SELECT e.*, ce.role FROM entities e
        JOIN claim_entities ce ON e.entity_id = ce.entity_id
        WHERE ce.claim_id = ?
        ORDER BY ce.role, e.name
    """, (claim_id,))
    
    return [(Entity.from_row(row), row['role']) for row in rows]


def get_entities_for_claims(
    db: PKBDatabase,
    claim_ids: List[str]
) -> Dict[str, List[Tuple[Entity, str]]]:
    """
    Batch get entities for multiple claims.
    
    More efficient than calling get_claim_entities for each claim.
    
    Args:
        db: PKBDatabase instance.
        claim_ids: List of claim IDs.
        
    Returns:
        Dict mapping claim_id to list of (Entity, role) tuples.
    """
    if not claim_ids:
        return {}
    
    placeholders = ','.join(['?' for _ in claim_ids])
    rows = db.fetchall(f"""
        SELECT ce.claim_id, ce.role, e.* FROM entities e
        JOIN claim_entities ce ON e.entity_id = ce.entity_id
        WHERE ce.claim_id IN ({placeholders})
        ORDER BY ce.role, e.name
    """, tuple(claim_ids))
    
    result: Dict[str, List[Tuple[Entity, str]]] = {cid: [] for cid in claim_ids}
    for row in rows:
        claim_id = row['claim_id']
        if claim_id in result:
            result[claim_id].append((Entity.from_row(row), row['role']))
    
    return result


def set_claim_entities(
    db: PKBDatabase,
    claim_id: str,
    entities: List[Dict[str, str]]
) -> None:
    """
    Set the exact set of entities for a claim.
    
    Args:
        db: PKBDatabase instance.
        claim_id: ID of claim.
        entities: List of dicts with entity_id and role.
    """
    with db.transaction() as conn:
        # Remove existing
        conn.execute("DELETE FROM claim_entities WHERE claim_id = ?", (claim_id,))
        
        # Add new
        for entity_data in entities:
            conn.execute(
                "INSERT INTO claim_entities (claim_id, entity_id, role) VALUES (?, ?, ?)",
                (claim_id, entity_data['entity_id'], entity_data['role'])
            )
        
        logger.debug(f"Set {len(entities)} entities for claim {claim_id}")


# =============================================================================
# Utility Functions
# =============================================================================

def get_or_create_tag_by_name(
    db: PKBDatabase,
    tag_name: str,
    parent_tag_id: Optional[str] = None
) -> str:
    """
    Get or create a tag by name, return its ID.
    
    Args:
        db: PKBDatabase instance.
        tag_name: Name of tag.
        parent_tag_id: Optional parent tag ID.
        
    Returns:
        Tag ID.
    """
    if parent_tag_id:
        row = db.fetchone(
            "SELECT tag_id FROM tags WHERE name = ? AND parent_tag_id = ?",
            (tag_name, parent_tag_id)
        )
    else:
        row = db.fetchone(
            "SELECT tag_id FROM tags WHERE name = ? AND parent_tag_id IS NULL",
            (tag_name,)
        )
    
    if row:
        return row['tag_id']
    
    # Create new tag
    tag_id = generate_uuid()
    now = now_iso()
    db.execute(
        "INSERT INTO tags (tag_id, name, parent_tag_id, meta_json, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?)",
        (tag_id, tag_name, parent_tag_id, now, now)
    )
    db.connect().commit()
    
    return tag_id


def get_or_create_entity_by_name(
    db: PKBDatabase,
    entity_name: str,
    entity_type: str
) -> str:
    """
    Get or create an entity by type and name, return its ID.
    
    Args:
        db: PKBDatabase instance.
        entity_name: Name of entity.
        entity_type: Type of entity.
        
    Returns:
        Entity ID.
    """
    row = db.fetchone(
        "SELECT entity_id FROM entities WHERE entity_type = ? AND name = ?",
        (entity_type, entity_name)
    )
    
    if row:
        return row['entity_id']
    
    # Create new entity
    entity_id = generate_uuid()
    now = now_iso()
    db.execute(
        "INSERT INTO entities (entity_id, entity_type, name, meta_json, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?)",
        (entity_id, entity_type, entity_name, now, now)
    )
    db.connect().commit()
    
    return entity_id
