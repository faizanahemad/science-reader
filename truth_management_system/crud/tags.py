"""
Tags CRUD operations for PKB v0.

TagCRUD provides data access for tags (hierarchical labels):
- add(): Create new tag with cycle validation
- edit(): Update tag fields with cycle validation
- delete(): Delete tag (cascades to claim_tags)
- get(): Retrieve by ID
- get_or_create(): Get existing or create new tag
- get_hierarchy(): Get full path from root to tag
- get_children(): Get immediate children of a tag
- list(): Query with filters
"""

import sqlite3
import logging
from typing import Optional, List, Dict, Any, Tuple

from .base import BaseCRUD
from ..database import PKBDatabase
from ..models import Tag, TAG_COLUMNS
from ..utils import now_iso

logger = logging.getLogger(__name__)


class TagCRUD(BaseCRUD[Tag]):
    """
    CRUD operations for tags.
    
    Tags are hierarchical labels for organizing claims. They can form
    a tree structure via parent_tag_id. Cycle detection ensures the
    hierarchy remains a valid tree.
    
    Attributes:
        db: PKBDatabase instance.
        user_email: Optional user email for multi-user filtering.
    """
    
    def _table_name(self) -> str:
        return "tags"
    
    def _id_column(self) -> str:
        return "tag_id"
    
    def _to_model(self, row: sqlite3.Row) -> Tag:
        return Tag.from_row(row)
    
    def _ensure_user_email(self, tag: Tag) -> Tag:
        """Ensure tag has user_email set if CRUD has user_email."""
        if self.user_email and not tag.user_email:
            tag.user_email = self.user_email
        return tag
    
    def add(self, tag: Tag) -> Tag:
        """
        Add a new tag with cycle validation.
        
        If user_email is set on this CRUD instance, it will be applied
        to the tag if not already set.
        
        Args:
            tag: Tag instance to add.
            
        Returns:
            The added tag.
            
        Raises:
            ValueError: If parent_tag_id would create a cycle.
            sqlite3.IntegrityError: If tag with same user+name+parent exists.
        """
        # Ensure tag has user_email
        tag = self._ensure_user_email(tag)
        
        # Validate no cycle (only relevant if tag has a parent)
        if tag.parent_tag_id:
            self._validate_no_cycle(tag.tag_id, tag.parent_tag_id)
        
        with self.db.transaction() as conn:
            columns = ', '.join(TAG_COLUMNS)
            placeholders = ', '.join(['?' for _ in TAG_COLUMNS])
            
            conn.execute(
                f"INSERT INTO tags ({columns}) VALUES ({placeholders})",
                tag.to_insert_tuple()
            )
            
            logger.debug(f"Added tag: {tag.tag_id} ({tag.name})")
        
        return tag
    
    def edit(
        self,
        tag_id: str,
        patch: Dict[str, Any]
    ) -> Optional[Tag]:
        """
        Update tag fields with cycle validation.
        
        Args:
            tag_id: ID of tag to update.
            patch: Dict of field-value pairs to update.
            
        Returns:
            Updated tag or None if not found.
            
        Raises:
            ValueError: If new parent_tag_id would create a cycle.
        """
        if not patch:
            return self.get(tag_id)
        
        if not self.exists(tag_id):
            return None
        
        # Validate no cycle if parent is being changed
        if 'parent_tag_id' in patch and patch['parent_tag_id']:
            self._validate_no_cycle(tag_id, patch['parent_tag_id'])
        
        with self.db.transaction() as conn:
            sql, params = self._build_update_sql(tag_id, patch)
            conn.execute(sql, params)
            
            logger.debug(f"Updated tag: {tag_id}")
        
        return self.get(tag_id)
    
    def delete(self, tag_id: str) -> bool:
        """
        Delete a tag.
        
        The claim_tags links are cascade-deleted by foreign key.
        Child tags have their parent_tag_id set to NULL.
        
        Args:
            tag_id: ID of tag to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        if not self.exists(tag_id):
            return False
        
        with self.db.transaction() as conn:
            # Child tags will have parent_tag_id set to NULL by ON DELETE SET NULL
            conn.execute("DELETE FROM tags WHERE tag_id = ?", (tag_id,))
            logger.debug(f"Deleted tag: {tag_id}")
        
        return True
    
    def _validate_no_cycle(
        self,
        tag_id: str,
        parent_id: str
    ) -> None:
        """
        Validate that setting parent would not create a cycle.
        
        Walks up the parent chain from parent_id to ensure tag_id
        is not encountered (which would create a cycle).
        
        Args:
            tag_id: ID of tag being added/updated.
            parent_id: Proposed parent tag ID.
            
        Raises:
            ValueError: If a cycle would be created.
        """
        if tag_id == parent_id:
            raise ValueError(f"Tag cannot be its own parent: {tag_id}")
        
        visited = {tag_id}
        current = parent_id
        
        while current:
            if current in visited:
                raise ValueError(f"Cycle detected: setting parent to {parent_id} would create a cycle")
            
            visited.add(current)
            parent = self.get(current)
            current = parent.parent_tag_id if parent else None
    
    def get_or_create(
        self,
        name: str,
        parent_tag_id: Optional[str] = None,
        meta_json: Optional[str] = None
    ) -> Tuple[Tag, bool]:
        """
        Get existing tag or create new one.
        
        If user_email is set, scopes to that user.
        
        Args:
            name: Tag name.
            parent_tag_id: Optional parent for hierarchy.
            meta_json: Optional metadata for new tags.
            
        Returns:
            Tuple of (tag, created) where created is True if new.
        """
        existing = self.find_by_name_and_parent(name, parent_tag_id)
        if existing:
            return existing, False
        
        tag = Tag.create(
            name=name,
            parent_tag_id=parent_tag_id,
            user_email=self.user_email,
            meta_json=meta_json
        )
        self.add(tag)
        return tag, True
    
    def find_by_name_and_parent(
        self,
        name: str,
        parent_tag_id: Optional[str] = None
    ) -> Optional[Tag]:
        """
        Find tag by name and parent.
        
        If user_email is set, only searches tags owned by that user.
        
        Args:
            name: Tag name.
            parent_tag_id: Parent tag ID (None for root tags).
            
        Returns:
            Tag or None if not found.
        """
        if self.user_email:
            if parent_tag_id:
                row = self.db.fetchone(
                    "SELECT * FROM tags WHERE name = ? AND parent_tag_id = ? AND user_email = ?",
                    (name, parent_tag_id, self.user_email)
                )
            else:
                row = self.db.fetchone(
                    "SELECT * FROM tags WHERE name = ? AND parent_tag_id IS NULL AND user_email = ?",
                    (name, self.user_email)
                )
        else:
            if parent_tag_id:
                row = self.db.fetchone(
                    "SELECT * FROM tags WHERE name = ? AND parent_tag_id = ? AND user_email IS NULL",
                    (name, parent_tag_id)
                )
            else:
                row = self.db.fetchone(
                    "SELECT * FROM tags WHERE name = ? AND parent_tag_id IS NULL AND user_email IS NULL",
                    (name,)
                )
        
        return Tag.from_row(row) if row else None
    
    def find_by_name(
        self,
        name_pattern: str,
        limit: int = 100
    ) -> List[Tag]:
        """
        Search tags by name pattern.
        
        Args:
            name_pattern: Pattern to match (case-insensitive, partial).
            limit: Maximum results.
            
        Returns:
            List of matching tags.
        """
        rows = self.db.fetchall(
            "SELECT * FROM tags WHERE name LIKE ? ORDER BY name LIMIT ?",
            (f"%{name_pattern}%", limit)
        )
        return [Tag.from_row(row) for row in rows]
    
    def get_hierarchy(self, tag_id: str) -> List[Tag]:
        """
        Get full path from root to this tag.
        
        Args:
            tag_id: ID of tag.
            
        Returns:
            List of tags from root to tag (inclusive), or empty if not found.
        """
        tag = self.get(tag_id)
        if not tag:
            return []
        
        path = [tag]
        current = tag.parent_tag_id
        
        while current:
            parent = self.get(current)
            if parent:
                path.insert(0, parent)
                current = parent.parent_tag_id
            else:
                break
        
        return path
    
    def get_full_path_string(self, tag_id: str, separator: str = "/") -> str:
        """
        Get tag hierarchy as a path string.
        
        Args:
            tag_id: ID of tag.
            separator: Path separator.
            
        Returns:
            Path string like "health/fitness/running".
        """
        hierarchy = self.get_hierarchy(tag_id)
        return separator.join(tag.name for tag in hierarchy)
    
    def get_children(
        self,
        parent_tag_id: Optional[str] = None
    ) -> List[Tag]:
        """
        Get immediate children of a tag.
        
        Args:
            parent_tag_id: Parent tag ID, or None for root tags.
            
        Returns:
            List of child tags.
        """
        if parent_tag_id:
            rows = self.db.fetchall(
                "SELECT * FROM tags WHERE parent_tag_id = ? ORDER BY name",
                (parent_tag_id,)
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM tags WHERE parent_tag_id IS NULL ORDER BY name"
            )
        
        return [Tag.from_row(row) for row in rows]
    
    def get_descendants(self, tag_id: str) -> List[Tag]:
        """
        Get all descendants of a tag (children, grandchildren, etc.).
        
        Uses recursive CTE for efficient traversal.
        
        Args:
            tag_id: ID of parent tag.
            
        Returns:
            List of all descendant tags.
        """
        rows = self.db.fetchall("""
            WITH RECURSIVE descendants AS (
                SELECT * FROM tags WHERE parent_tag_id = ?
                UNION ALL
                SELECT t.* FROM tags t
                JOIN descendants d ON t.parent_tag_id = d.tag_id
            )
            SELECT * FROM descendants ORDER BY name
        """, (tag_id,))
        
        return [Tag.from_row(row) for row in rows]
    
    def get_root_tags(self) -> List[Tag]:
        """Get all top-level tags (no parent)."""
        return self.get_children(parent_tag_id=None)
    
    def get_with_claim_count(
        self,
        limit: int = 100
    ) -> List[Tuple[Tag, int]]:
        """
        Get tags with their claim counts.
        
        Args:
            limit: Maximum results.
            
        Returns:
            List of (tag, claim_count) tuples, sorted by count descending.
        """
        rows = self.db.fetchall("""
            SELECT t.*, COUNT(ct.claim_id) as claim_count
            FROM tags t
            LEFT JOIN claim_tags ct ON t.tag_id = ct.tag_id
            GROUP BY t.tag_id
            ORDER BY claim_count DESC
            LIMIT ?
        """, (limit,))
        
        return [(Tag.from_row(row), row['claim_count']) for row in rows]
    
    def move(
        self,
        tag_id: str,
        new_parent_id: Optional[str]
    ) -> Optional[Tag]:
        """
        Move tag to a new parent.
        
        Args:
            tag_id: ID of tag to move.
            new_parent_id: New parent ID, or None to make root tag.
            
        Returns:
            Updated tag or None if not found.
            
        Raises:
            ValueError: If move would create a cycle.
        """
        return self.edit(tag_id, {'parent_tag_id': new_parent_id})
