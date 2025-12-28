"""
Entities CRUD operations for PKB v0.

EntityCRUD provides data access for entities (canonical references):
- add(): Create new entity
- edit(): Update entity fields
- delete(): Delete entity (cascades to claim_entities)
- get(): Retrieve by ID
- get_or_create(): Get existing or create new entity
- find_by_name(): Search entities by name
- list(): Query with filters
"""

import sqlite3
import logging
from typing import Optional, List, Dict, Any, Tuple

from .base import BaseCRUD
from ..database import PKBDatabase
from ..models import Entity, ENTITY_COLUMNS
from ..utils import now_iso

logger = logging.getLogger(__name__)


class EntityCRUD(BaseCRUD[Entity]):
    """
    CRUD operations for entities.
    
    Entities are canonical references to people, places, topics, etc.
    They enable linking claims about the same subject and provide
    structured navigation.
    
    Attributes:
        db: PKBDatabase instance.
        user_email: Optional user email for multi-user filtering.
    """
    
    def _table_name(self) -> str:
        return "entities"
    
    def _id_column(self) -> str:
        return "entity_id"
    
    def _to_model(self, row: sqlite3.Row) -> Entity:
        return Entity.from_row(row)
    
    def _ensure_user_email(self, entity: Entity) -> Entity:
        """Ensure entity has user_email set if CRUD has user_email."""
        if self.user_email and not entity.user_email:
            entity.user_email = self.user_email
        return entity
    
    def add(self, entity: Entity) -> Entity:
        """
        Add a new entity.
        
        If user_email is set on this CRUD instance, it will be applied
        to the entity if not already set.
        
        Args:
            entity: Entity instance to add.
            
        Returns:
            The added entity.
            
        Raises:
            sqlite3.IntegrityError: If entity with same user+type+name exists.
        """
        # Ensure entity has user_email
        entity = self._ensure_user_email(entity)
        
        with self.db.transaction() as conn:
            columns = ', '.join(ENTITY_COLUMNS)
            placeholders = ', '.join(['?' for _ in ENTITY_COLUMNS])
            
            conn.execute(
                f"INSERT INTO entities ({columns}) VALUES ({placeholders})",
                entity.to_insert_tuple()
            )
            
            logger.debug(f"Added entity: {entity.entity_id} ({entity.entity_type}: {entity.name})")
        
        return entity
    
    def edit(
        self,
        entity_id: str,
        patch: Dict[str, Any]
    ) -> Optional[Entity]:
        """
        Update entity fields.
        
        Args:
            entity_id: ID of entity to update.
            patch: Dict of field-value pairs to update.
            
        Returns:
            Updated entity or None if not found.
        """
        if not patch:
            return self.get(entity_id)
        
        if not self.exists(entity_id):
            return None
        
        with self.db.transaction() as conn:
            sql, params = self._build_update_sql(entity_id, patch)
            conn.execute(sql, params)
            
            logger.debug(f"Updated entity: {entity_id}")
        
        return self.get(entity_id)
    
    def delete(self, entity_id: str) -> bool:
        """
        Delete an entity.
        
        The claim_entities links are cascade-deleted by foreign key.
        
        Args:
            entity_id: ID of entity to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        if not self.exists(entity_id):
            return False
        
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM entities WHERE entity_id = ?", (entity_id,))
            logger.debug(f"Deleted entity: {entity_id}")
        
        return True
    
    def get_or_create(
        self,
        name: str,
        entity_type: str,
        meta_json: Optional[str] = None
    ) -> Tuple[Entity, bool]:
        """
        Get existing entity or create new one.
        
        Uses the UNIQUE(user_email, entity_type, name) constraint to ensure uniqueness.
        
        Args:
            name: Entity name.
            entity_type: Entity type.
            meta_json: Optional metadata for new entities.
            
        Returns:
            Tuple of (entity, created) where created is True if new.
        """
        # Check if exists
        existing = self.find_by_type_and_name(entity_type, name)
        if existing:
            return existing, False
        
        # Create new
        entity = Entity.create(
            name=name,
            entity_type=entity_type,
            user_email=self.user_email,
            meta_json=meta_json
        )
        self.add(entity)
        return entity, True
    
    def find_by_type_and_name(
        self,
        entity_type: str,
        name: str
    ) -> Optional[Entity]:
        """
        Find entity by type and exact name.
        
        If user_email is set, only searches entities owned by that user.
        
        Args:
            entity_type: Entity type.
            name: Exact entity name.
            
        Returns:
            Entity or None if not found.
        """
        if self.user_email:
            row = self.db.fetchone(
                "SELECT * FROM entities WHERE entity_type = ? AND name = ? AND user_email = ?",
                (entity_type, name, self.user_email)
            )
        else:
            row = self.db.fetchone(
                "SELECT * FROM entities WHERE entity_type = ? AND name = ? AND user_email IS NULL",
                (entity_type, name)
            )
        return Entity.from_row(row) if row else None
    
    def find_by_name(
        self,
        name_pattern: str,
        entity_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Entity]:
        """
        Search entities by name pattern.
        
        Args:
            name_pattern: Pattern to match (case-insensitive, partial).
            entity_type: Optional type filter.
            limit: Maximum results.
            
        Returns:
            List of matching entities.
        """
        if entity_type:
            rows = self.db.fetchall(
                "SELECT * FROM entities WHERE name LIKE ? AND entity_type = ? ORDER BY name LIMIT ?",
                (f"%{name_pattern}%", entity_type, limit)
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM entities WHERE name LIKE ? ORDER BY name LIMIT ?",
                (f"%{name_pattern}%", limit)
            )
        
        return [Entity.from_row(row) for row in rows]
    
    def get_by_type(
        self,
        entity_type: str,
        limit: int = 100
    ) -> List[Entity]:
        """
        Get all entities of a specific type.
        
        Args:
            entity_type: Entity type to filter by.
            limit: Maximum results.
            
        Returns:
            List of entities of the specified type.
        """
        return self.list(
            filters={'entity_type': entity_type},
            order_by='name',
            limit=limit
        )
    
    def get_with_claim_count(
        self,
        entity_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Tuple[Entity, int]]:
        """
        Get entities with their claim counts.
        
        Args:
            entity_type: Optional type filter.
            limit: Maximum results.
            
        Returns:
            List of (entity, claim_count) tuples, sorted by count descending.
        """
        sql = """
            SELECT e.*, COUNT(ce.claim_id) as claim_count
            FROM entities e
            LEFT JOIN claim_entities ce ON e.entity_id = ce.entity_id
        """
        params = []
        
        if entity_type:
            sql += " WHERE e.entity_type = ?"
            params.append(entity_type)
        
        sql += " GROUP BY e.entity_id ORDER BY claim_count DESC LIMIT ?"
        params.append(limit)
        
        rows = self.db.fetchall(sql, tuple(params))
        return [(Entity.from_row(row), row['claim_count']) for row in rows]
    
    def merge(
        self,
        source_id: str,
        target_id: str
    ) -> Optional[Entity]:
        """
        Merge one entity into another.
        
        All claim links from source are moved to target, then source is deleted.
        
        Args:
            source_id: Entity to merge from (will be deleted).
            target_id: Entity to merge into (will be kept).
            
        Returns:
            Target entity or None if either not found.
        """
        source = self.get(source_id)
        target = self.get(target_id)
        
        if not source or not target:
            return None
        
        with self.db.transaction() as conn:
            # Update claim_entities to point to target
            # Handle potential duplicates by using INSERT OR IGNORE
            conn.execute("""
                INSERT OR IGNORE INTO claim_entities (claim_id, entity_id, role)
                SELECT claim_id, ?, role FROM claim_entities WHERE entity_id = ?
            """, (target_id, source_id))
            
            # Delete old links
            conn.execute("DELETE FROM claim_entities WHERE entity_id = ?", (source_id,))
            
            # Delete source entity
            conn.execute("DELETE FROM entities WHERE entity_id = ?", (source_id,))
            
            logger.info(f"Merged entity {source_id} into {target_id}")
        
        return self.get(target_id)
