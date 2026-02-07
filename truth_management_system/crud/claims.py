"""
Claims CRUD operations for PKB v0.

ClaimCRUD provides data access for claims (atomic memory units):
- add(): Create new claim with optional tags/entities
- edit(): Update claim fields, invalidate embedding if statement changes
- delete(): Soft-delete (set status=retracted)
- get(): Retrieve by ID
- list(): Query with filters
- get_by_entity(): Get claims linked to an entity
- get_by_tag(): Get claims with a specific tag

FTS sync is handled by SQLite triggers (default).
Embedding invalidation is handled on statement changes.
"""

import sqlite3
import logging
from typing import Optional, List, Dict, Any

from .base import BaseCRUD, delete_claim_embedding
from ..database import PKBDatabase
from ..models import Claim, CLAIM_COLUMNS
from ..constants import ClaimStatus
from ..utils import now_iso, generate_uuid

# Cache for the actual columns in the claims table (detected at runtime).
# This handles v2 databases that don't have friendly_id/claim_types/context_domains yet.
# The cache is reset when reset_claim_columns_cache() is called (e.g., after migration).
_actual_claim_columns = None


def reset_claim_columns_cache():
    """Reset the cached claim columns list. Called after schema migration."""
    global _actual_claim_columns
    _actual_claim_columns = None


def _get_actual_claim_columns(db: PKBDatabase) -> list:
    """
    Get the actual column list from the claims table at runtime.
    
    This ensures INSERT statements only reference columns that exist,
    which is critical for backwards compatibility when the database
    hasn't been migrated to v3 yet.
    
    Args:
        db: PKBDatabase instance.
        
    Returns:
        List of column names that exist in both CLAIM_COLUMNS and the actual table.
    """
    global _actual_claim_columns
    if _actual_claim_columns is not None:
        return _actual_claim_columns
    
    try:
        cursor = db.execute("PRAGMA table_info(claims)")
        db_columns = {row[1] for row in cursor.fetchall()}
        _actual_claim_columns = [c for c in CLAIM_COLUMNS if c in db_columns]
    except Exception:
        _actual_claim_columns = CLAIM_COLUMNS
    
    return _actual_claim_columns

logger = logging.getLogger(__name__)


class ClaimCRUD(BaseCRUD[Claim]):
    """
    CRUD operations for claims.
    
    Claims are the atomic memory units of the PKB. This class provides
    all data access operations for claims including linking to tags
    and entities.
    
    Attributes:
        db: PKBDatabase instance.
        user_email: Optional user email for multi-user filtering.
    """
    
    def _table_name(self) -> str:
        return "claims"
    
    def _id_column(self) -> str:
        return "claim_id"
    
    def _to_model(self, row: sqlite3.Row) -> Claim:
        return Claim.from_row(row)
    
    def _ensure_user_email(self, claim: Claim) -> Claim:
        """Ensure claim has user_email set if CRUD has user_email."""
        if self.user_email and not claim.user_email:
            claim.user_email = self.user_email
        return claim
    
    def add(
        self,
        claim: Claim,
        tags: List[str] = None,
        entities: List[Dict[str, str]] = None
    ) -> Claim:
        """
        Add a new claim with optional tags and entities.
        
        If user_email is set on this CRUD instance, it will be applied
        to the claim if not already set.
        
        Args:
            claim: Claim instance to add.
            tags: List of tag names to link (created if not exist).
            entities: List of entity dicts {type, name, role} to link.
            
        Returns:
            The added claim.
            
        Example:
            claim = Claim.create(
                statement="I prefer morning workouts",
                claim_type="preference",
                context_domain="health"
            )
            claim = crud.add(claim, tags=["fitness", "routine"])
        """
        tags = tags or []
        entities = entities or []
        
        # Ensure claim has user_email
        claim = self._ensure_user_email(claim)
        
        with self.db.transaction() as conn:
            # Auto-assign claim_number if the column exists and claim doesn't have one
            actual_cols = _get_actual_claim_columns(self.db)
            if 'claim_number' in actual_cols and not claim.claim_number:
                user_filter = claim.user_email or ''
                max_row = conn.execute(
                    "SELECT COALESCE(MAX(claim_number), 0) FROM claims WHERE COALESCE(user_email, '') = ?",
                    (user_filter,)
                ).fetchone()
                claim.claim_number = (max_row[0] if max_row else 0) + 1
            
            # Build INSERT statement using only columns that exist in the table.
            # This handles older databases that don't have all columns yet.
            columns = ', '.join(actual_cols)
            placeholders = ', '.join(['?' for _ in actual_cols])
            values = tuple(getattr(claim, k) for k in actual_cols)
            
            conn.execute(
                f"INSERT INTO claims ({columns}) VALUES ({placeholders})",
                values
            )
            
            # Link tags
            for tag_name in tags:
                tag_id = self._get_or_create_tag(conn, tag_name)
                conn.execute(
                    "INSERT OR IGNORE INTO claim_tags (claim_id, tag_id) VALUES (?, ?)",
                    (claim.claim_id, tag_id)
                )
            
            # Link entities
            for entity_data in entities:
                entity_id = self._get_or_create_entity(
                    conn,
                    entity_data.get('name'),
                    entity_data.get('type', 'other')
                )
                role = entity_data.get('role', 'mentioned')
                conn.execute(
                    "INSERT OR IGNORE INTO claim_entities (claim_id, entity_id, role) VALUES (?, ?, ?)",
                    (claim.claim_id, entity_id, role)
                )
            
            # FTS sync is handled by triggers
            logger.debug(f"Added claim: {claim.claim_id}")
        
        return claim
    
    def edit(
        self,
        claim_id: str,
        patch: Dict[str, Any]
    ) -> Optional[Claim]:
        """
        Update claim fields.
        
        If 'statement' is changed, the cached embedding is invalidated.
        
        Args:
            claim_id: ID of claim to update.
            patch: Dict of field-value pairs to update.
            
        Returns:
            Updated claim or None if not found.
            
        Example:
            claim = crud.edit(claim_id, {"statement": "Updated text", "confidence": 0.9})
        """
        if not patch:
            return self.get(claim_id)
        
        # Check if claim exists
        existing = self.get(claim_id)
        if not existing:
            return None
        
        # Auto-generate friendly_id if the existing claim doesn't have one
        if not existing.friendly_id and 'friendly_id' not in patch:
            from ..utils import generate_friendly_id
            stmt = patch.get('statement', existing.statement)
            patch['friendly_id'] = generate_friendly_id(stmt)
        
        statement_changed = 'statement' in patch and patch['statement'] != existing.statement
        
        with self.db.transaction() as conn:
            # Build and execute UPDATE
            sql, params = self._build_update_sql(claim_id, patch)
            conn.execute(sql, params)
            
            # Invalidate embedding if statement changed
            if statement_changed:
                delete_claim_embedding(conn, claim_id)
                logger.debug(f"Invalidated embedding for claim: {claim_id}")
            
            # FTS sync is handled by triggers
            logger.debug(f"Updated claim: {claim_id}")
        
        return self.get(claim_id)
    
    def delete(
        self,
        claim_id: str,
        mode: str = "retract"
    ) -> Optional[Claim]:
        """
        Soft-delete a claim by setting status to retracted.
        
        Hard deletion is not supported to preserve history and
        conflict set integrity.
        
        Args:
            claim_id: ID of claim to delete.
            mode: Only "retract" is supported (soft delete).
            
        Returns:
            Updated claim or None if not found.
        """
        return self.edit(claim_id, {
            'status': ClaimStatus.RETRACTED.value,
            'retracted_at': now_iso()
        })
    
    def get_by_entity(
        self,
        entity_id: str,
        role: Optional[str] = None,
        statuses: List[str] = None
    ) -> List[Claim]:
        """
        Get claims linked to an entity.
        
        If user_email is set, only returns claims owned by that user.
        
        Args:
            entity_id: ID of entity.
            role: Optional role filter (subject, object, mentioned).
            statuses: Filter by claim status (default: active + contested).
            
        Returns:
            List of claims linked to the entity.
        """
        statuses = statuses or ClaimStatus.default_search_statuses()
        
        sql = """
            SELECT c.* FROM claims c
            JOIN claim_entities ce ON c.claim_id = ce.claim_id
            WHERE ce.entity_id = ?
              AND c.status IN ({})
        """.format(','.join(['?' for _ in statuses]))
        
        params = [entity_id] + statuses
        
        # Add user_email filter
        if self.user_email:
            sql += " AND c.user_email = ?"
            params.append(self.user_email)
        
        if role:
            sql += " AND ce.role = ?"
            params.append(role)
        
        sql += " ORDER BY c.updated_at DESC"
        
        rows = self.db.fetchall(sql, tuple(params))
        return [Claim.from_row(row) for row in rows]
    
    def get_by_tag(
        self,
        tag_id: str,
        statuses: List[str] = None,
        include_children: bool = False
    ) -> List[Claim]:
        """
        Get claims with a specific tag.
        
        If user_email is set, only returns claims owned by that user.
        
        Args:
            tag_id: ID of tag.
            statuses: Filter by claim status (default: active + contested).
            include_children: Include claims with child tags.
            
        Returns:
            List of claims with the tag.
        """
        statuses = statuses or ClaimStatus.default_search_statuses()
        status_placeholders = ','.join(['?' for _ in statuses])
        
        user_filter = ""
        user_params = []
        if self.user_email:
            user_filter = " AND c.user_email = ?"
            user_params = [self.user_email]
        
        if include_children:
            # Get all descendant tag IDs using recursive CTE
            sql = f"""
                WITH RECURSIVE tag_tree AS (
                    SELECT tag_id FROM tags WHERE tag_id = ?
                    UNION ALL
                    SELECT t.tag_id FROM tags t
                    JOIN tag_tree tt ON t.parent_tag_id = tt.tag_id
                )
                SELECT DISTINCT c.* FROM claims c
                JOIN claim_tags ct ON c.claim_id = ct.claim_id
                JOIN tag_tree tt ON ct.tag_id = tt.tag_id
                WHERE c.status IN ({status_placeholders}){user_filter}
                ORDER BY c.updated_at DESC
            """
            params = [tag_id] + statuses + user_params
        else:
            sql = f"""
                SELECT c.* FROM claims c
                JOIN claim_tags ct ON c.claim_id = ct.claim_id
                WHERE ct.tag_id = ?
                  AND c.status IN ({status_placeholders}){user_filter}
                ORDER BY c.updated_at DESC
            """
            params = [tag_id] + statuses + user_params
        
        rows = self.db.fetchall(sql, tuple(params))
        return [Claim.from_row(row) for row in rows]
    
    def get_by_friendly_id(self, friendly_id: str) -> Optional[Claim]:
        """
        Get a claim by its user-facing friendly_id.
        
        If user_email is set on this CRUD instance, the lookup is scoped
        to that user's claims only.
        
        Args:
            friendly_id: The user-facing alphanumeric identifier.
            
        Returns:
            Claim if found, None otherwise.
        """
        if self.user_email:
            row = self.db.fetchone(
                "SELECT * FROM claims WHERE friendly_id = ? AND user_email = ?",
                (friendly_id, self.user_email)
            )
        else:
            row = self.db.fetchone(
                "SELECT * FROM claims WHERE friendly_id = ?",
                (friendly_id,)
            )
        return Claim.from_row(row) if row else None
    
    def get_by_claim_number(self, claim_number: int) -> Optional[Claim]:
        """
        Get a claim by its per-user numeric claim_number.
        
        Used to resolve @claim_N references in chat messages.
        
        Args:
            claim_number: The numeric identifier.
            
        Returns:
            Claim if found, None otherwise.
        """
        if self.user_email:
            row = self.db.fetchone(
                "SELECT * FROM claims WHERE claim_number = ? AND user_email = ?",
                (claim_number, self.user_email)
            )
        else:
            row = self.db.fetchone(
                "SELECT * FROM claims WHERE claim_number = ?",
                (claim_number,)
            )
        return Claim.from_row(row) if row else None
    
    def search_friendly_ids(self, prefix: str, limit: int = 10) -> List[Claim]:
        """
        Search claims by friendly_id prefix (for autocomplete).
        
        Returns claims whose friendly_id starts with the given prefix,
        scoped to the current user if user_email is set.
        
        Args:
            prefix: The prefix to search for.
            limit: Maximum number of results (default: 10).
            
        Returns:
            List of claims matching the prefix.
        """
        if not prefix:
            return []
        
        if self.user_email:
            rows = self.db.fetchall(
                "SELECT * FROM claims WHERE friendly_id LIKE ? AND user_email = ? AND status != ? ORDER BY friendly_id LIMIT ?",
                (f"{prefix}%", self.user_email, ClaimStatus.RETRACTED.value, limit)
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM claims WHERE friendly_id LIKE ? AND status != ? ORDER BY friendly_id LIMIT ?",
                (f"{prefix}%", ClaimStatus.RETRACTED.value, limit)
            )
        return [Claim.from_row(row) for row in rows]
    
    def get_contested(self) -> List[Claim]:
        """Get all claims with contested status."""
        return self.list(filters={'status': ClaimStatus.CONTESTED.value})
    
    def get_active(
        self,
        context_domain: Optional[str] = None,
        claim_type: Optional[str] = None
    ) -> List[Claim]:
        """
        Get active claims with optional filters.
        
        Args:
            context_domain: Filter by domain.
            claim_type: Filter by type.
            
        Returns:
            List of active claims.
        """
        filters = {'status': ClaimStatus.ACTIVE.value}
        if context_domain:
            filters['context_domain'] = context_domain
        if claim_type:
            filters['claim_type'] = claim_type
        
        return self.list(filters=filters, order_by='-updated_at')
    
    def search_by_predicate(
        self,
        predicate: str,
        statuses: List[str] = None
    ) -> List[Claim]:
        """
        Find claims with matching predicate.
        
        If user_email is set, only returns claims owned by that user.
        
        Args:
            predicate: Predicate to search for.
            statuses: Filter by status.
            
        Returns:
            List of matching claims.
        """
        statuses = statuses or ClaimStatus.default_search_statuses()
        status_placeholders = ','.join(['?' for _ in statuses])
        
        params = [predicate] + statuses
        
        user_filter = ""
        if self.user_email:
            user_filter = " AND user_email = ?"
            params.append(self.user_email)
        
        sql = f"""
            SELECT * FROM claims
            WHERE predicate = ?
              AND status IN ({status_placeholders}){user_filter}
            ORDER BY updated_at DESC
        """
        
        rows = self.db.fetchall(sql, tuple(params))
        return [Claim.from_row(row) for row in rows]
    
    def _get_or_create_tag(
        self,
        conn: sqlite3.Connection,
        tag_name: str
    ) -> str:
        """
        Get or create a tag by name.
        
        If user_email is set, scopes tag to that user.
        
        Args:
            conn: Active connection (for transaction).
            tag_name: Name of tag.
            
        Returns:
            Tag ID.
        """
        # Check if exists (scoped to user if set)
        if self.user_email:
            row = conn.execute(
                "SELECT tag_id FROM tags WHERE name = ? AND parent_tag_id IS NULL AND user_email = ?",
                (tag_name, self.user_email)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT tag_id FROM tags WHERE name = ? AND parent_tag_id IS NULL AND user_email IS NULL",
                (tag_name,)
            ).fetchone()
        
        if row:
            return row['tag_id']
        
        # Create new tag
        tag_id = generate_uuid()
        now = now_iso()
        conn.execute(
            "INSERT INTO tags (tag_id, user_email, name, parent_tag_id, meta_json, created_at, updated_at) VALUES (?, ?, ?, NULL, NULL, ?, ?)",
            (tag_id, self.user_email, tag_name, now, now)
        )
        return tag_id
    
    def _get_or_create_entity(
        self,
        conn: sqlite3.Connection,
        name: str,
        entity_type: str
    ) -> str:
        """
        Get or create an entity by type and name.
        
        If user_email is set, scopes entity to that user.
        
        Args:
            conn: Active connection (for transaction).
            name: Entity name.
            entity_type: Entity type.
            
        Returns:
            Entity ID.
        """
        # Check if exists (scoped to user if set)
        if self.user_email:
            row = conn.execute(
                "SELECT entity_id FROM entities WHERE entity_type = ? AND name = ? AND user_email = ?",
                (entity_type, name, self.user_email)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT entity_id FROM entities WHERE entity_type = ? AND name = ? AND user_email IS NULL",
                (entity_type, name)
            ).fetchone()
        
        if row:
            return row['entity_id']
        
        # Create new entity
        entity_id = generate_uuid()
        now = now_iso()
        conn.execute(
            "INSERT INTO entities (entity_id, user_email, entity_type, name, meta_json, created_at, updated_at) VALUES (?, ?, ?, ?, NULL, ?, ?)",
            (entity_id, self.user_email, entity_type, name, now, now)
        )
        return entity_id
