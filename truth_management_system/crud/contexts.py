"""
Context CRUD operations for PKB v0.5.

ContextCRUD provides data access for contexts (hierarchical grouping of claims):
- add(): Create new context with cycle validation
- edit(): Update context fields with cycle validation
- delete(): Delete context (claims remain, just unlinked)
- get(): Retrieve by ID
- get_by_friendly_id(): Retrieve by user-facing friendly ID
- search_friendly_ids(): Search by friendly_id prefix (for autocomplete)
- get_children(): Get immediate child contexts
- get_descendants(): Get all descendant contexts
- resolve_claims(): Recursively get all claims under this context
- add_claim(): Link a claim to a context
- remove_claim(): Unlink a claim from a context
- get_claims(): Get claims directly in this context

Contexts allow users to organize memories into named groups/collections.
A context can contain claims directly and/or child contexts, forming a tree.
Resolution of a context recursively collects all leaf claims.

Why: Enables users to group memories by project, life area, or any custom
category and reference entire groups in conversation with @context_friendly_id.
"""

import sqlite3
import logging
from typing import Optional, List, Dict, Any, Tuple

from .base import BaseCRUD
from ..database import PKBDatabase
from ..models import Context, Claim, CONTEXT_COLUMNS, CLAIM_COLUMNS
from ..constants import ClaimStatus
from ..utils import now_iso, generate_uuid

logger = logging.getLogger(__name__)


class ContextCRUD(BaseCRUD[Context]):
    """
    CRUD operations for contexts (hierarchical claim groupings).
    
    Contexts allow users to organize claims into named groups.
    They can form a tree structure via parent_context_id.
    Cycle detection ensures the hierarchy remains a valid tree.
    
    A claim can belong to multiple contexts (many-to-many via context_claims).
    Resolving a context recursively collects claims from all sub-contexts.
    
    Attributes:
        db: PKBDatabase instance.
        user_email: Optional user email for multi-user filtering.
    """
    
    def _table_name(self) -> str:
        return "contexts"
    
    def _id_column(self) -> str:
        return "context_id"
    
    def _to_model(self, row: sqlite3.Row) -> Context:
        return Context.from_row(row)
    
    def _ensure_user_email(self, context: Context) -> Context:
        """Ensure context has user_email set if CRUD has user_email."""
        if self.user_email and not context.user_email:
            context.user_email = self.user_email
        return context
    
    def add(self, context: Context) -> Context:
        """
        Add a new context with cycle validation.
        
        If user_email is set on this CRUD instance, it will be applied
        to the context if not already set.
        
        Args:
            context: Context instance to add.
            
        Returns:
            The added context.
            
        Raises:
            ValueError: If parent_context_id would create a cycle.
            sqlite3.IntegrityError: If context with same user+friendly_id exists.
        """
        context = self._ensure_user_email(context)
        
        # Validate no cycle
        if context.parent_context_id:
            self._validate_no_cycle(context.context_id, context.parent_context_id)
        
        with self.db.transaction() as conn:
            columns = ', '.join(CONTEXT_COLUMNS)
            placeholders = ', '.join(['?' for _ in CONTEXT_COLUMNS])
            
            conn.execute(
                f"INSERT INTO contexts ({columns}) VALUES ({placeholders})",
                context.to_insert_tuple()
            )
            
            logger.debug(f"Added context: {context.context_id} ({context.name})")
        
        return context
    
    def edit(
        self,
        context_id: str,
        patch: Dict[str, Any]
    ) -> Optional[Context]:
        """
        Update context fields with cycle validation.
        
        Args:
            context_id: ID of context to update.
            patch: Dict of field-value pairs to update.
            
        Returns:
            Updated context or None if not found.
            
        Raises:
            ValueError: If new parent_context_id would create a cycle.
        """
        if not patch:
            return self.get(context_id)
        
        if not self.exists(context_id):
            return None
        
        # Validate no cycle if parent is being changed
        if 'parent_context_id' in patch and patch['parent_context_id']:
            self._validate_no_cycle(context_id, patch['parent_context_id'])
        
        with self.db.transaction() as conn:
            sql, params = self._build_update_sql(context_id, patch)
            conn.execute(sql, params)
            
            logger.debug(f"Updated context: {context_id}")
        
        return self.get(context_id)
    
    def delete(self, context_id: str) -> bool:
        """
        Delete a context.
        
        Claims linked to this context are NOT deleted, only the links
        (context_claims) are cascade-deleted.
        Child contexts have their parent_context_id set to NULL.
        
        Args:
            context_id: ID of context to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        if not self.exists(context_id):
            return False
        
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM contexts WHERE context_id = ?", (context_id,))
            logger.debug(f"Deleted context: {context_id}")
        
        return True
    
    def get_by_friendly_id(self, friendly_id: str) -> Optional[Context]:
        """
        Get a context by its user-facing friendly_id.
        
        If user_email is set, scoped to that user.
        
        Args:
            friendly_id: The user-facing alphanumeric identifier.
            
        Returns:
            Context if found, None otherwise.
        """
        if self.user_email:
            row = self.db.fetchone(
                "SELECT * FROM contexts WHERE friendly_id = ? AND user_email = ?",
                (friendly_id, self.user_email)
            )
        else:
            row = self.db.fetchone(
                "SELECT * FROM contexts WHERE friendly_id = ?",
                (friendly_id,)
            )
        return Context.from_row(row) if row else None
    
    def search_friendly_ids(self, prefix: str, limit: int = 10) -> List[Context]:
        """
        Search contexts by friendly_id prefix (for autocomplete).
        
        Args:
            prefix: The prefix to search for.
            limit: Maximum number of results.
            
        Returns:
            List of contexts matching the prefix.
        """
        if not prefix:
            return []
        
        if self.user_email:
            rows = self.db.fetchall(
                "SELECT * FROM contexts WHERE friendly_id LIKE ? AND user_email = ? ORDER BY friendly_id LIMIT ?",
                (f"{prefix}%", self.user_email, limit)
            )
        else:
            rows = self.db.fetchall(
                "SELECT * FROM contexts WHERE friendly_id LIKE ? ORDER BY friendly_id LIMIT ?",
                (f"{prefix}%", limit)
            )
        return [Context.from_row(row) for row in rows]
    
    def get_children(
        self,
        parent_context_id: Optional[str] = None
    ) -> List[Context]:
        """
        Get immediate children of a context.
        
        Args:
            parent_context_id: Parent context ID, or None for root contexts.
            
        Returns:
            List of child contexts.
        """
        user_filter = ""
        params = []
        
        if parent_context_id:
            base_sql = "SELECT * FROM contexts WHERE parent_context_id = ?"
            params.append(parent_context_id)
        else:
            base_sql = "SELECT * FROM contexts WHERE parent_context_id IS NULL"
        
        if self.user_email:
            user_filter = " AND user_email = ?"
            params.append(self.user_email)
        
        rows = self.db.fetchall(
            f"{base_sql}{user_filter} ORDER BY name",
            tuple(params)
        )
        return [Context.from_row(row) for row in rows]
    
    def get_descendants(self, context_id: str) -> List[Context]:
        """
        Get all descendants of a context (children, grandchildren, etc.).
        
        Uses recursive CTE for efficient traversal.
        
        Args:
            context_id: ID of parent context.
            
        Returns:
            List of all descendant contexts.
        """
        rows = self.db.fetchall("""
            WITH RECURSIVE descendants AS (
                SELECT * FROM contexts WHERE parent_context_id = ?
                UNION ALL
                SELECT c.* FROM contexts c
                JOIN descendants d ON c.parent_context_id = d.context_id
            )
            SELECT * FROM descendants ORDER BY name
        """, (context_id,))
        
        return [Context.from_row(row) for row in rows]
    
    def resolve_claims(
        self,
        context_id: str,
        statuses: List[str] = None,
        max_depth: int = 10
    ) -> List[Claim]:
        """
        Recursively get all claims under this context and all sub-contexts.
        
        This is the core resolution method used when a user references
        @context_friendly_id in a conversation. It traverses the context
        hierarchy and collects all linked claims.
        
        Args:
            context_id: ID of the root context to resolve.
            statuses: Filter by claim status (default: active + contested).
            max_depth: Maximum recursion depth to prevent runaway queries.
            
        Returns:
            List of unique claims (deduplicated by claim_id).
        """
        statuses = statuses or ClaimStatus.default_search_statuses()
        status_placeholders = ','.join(['?' for _ in statuses])
        
        user_filter = ""
        user_params = []
        if self.user_email:
            user_filter = " AND c.user_email = ?"
            user_params = [self.user_email]
        
        # Use recursive CTE to get all context IDs in hierarchy
        sql = f"""
            WITH RECURSIVE ctx_tree AS (
                SELECT context_id, 0 as depth FROM contexts WHERE context_id = ?
                UNION ALL
                SELECT c.context_id, ct.depth + 1 
                FROM contexts c
                JOIN ctx_tree ct ON c.parent_context_id = ct.context_id
                WHERE ct.depth < ?
            )
            SELECT DISTINCT c.* FROM claims c
            JOIN context_claims cc ON c.claim_id = cc.claim_id
            JOIN ctx_tree ct ON cc.context_id = ct.context_id
            WHERE c.status IN ({status_placeholders}){user_filter}
            ORDER BY c.updated_at DESC
        """
        
        params = [context_id, max_depth] + statuses + user_params
        rows = self.db.fetchall(sql, tuple(params))
        return [Claim.from_row(row) for row in rows]
    
    def add_claim(self, context_id: str, claim_id: str) -> bool:
        """
        Link a claim to a context.
        
        Args:
            context_id: ID of the context.
            claim_id: ID of the claim to link.
            
        Returns:
            True if linked, False if already linked or invalid.
        """
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO context_claims (context_id, claim_id) VALUES (?, ?)",
                    (context_id, claim_id)
                )
            logger.debug(f"Linked claim {claim_id} to context {context_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to link claim to context: {e}")
            return False
    
    def remove_claim(self, context_id: str, claim_id: str) -> bool:
        """
        Unlink a claim from a context.
        
        Args:
            context_id: ID of the context.
            claim_id: ID of the claim to unlink.
            
        Returns:
            True if unlinked, False if not found.
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM context_claims WHERE context_id = ? AND claim_id = ?",
                (context_id, claim_id)
            )
            if cursor.rowcount > 0:
                logger.debug(f"Unlinked claim {claim_id} from context {context_id}")
                return True
        return False
    
    def get_claims(
        self,
        context_id: str,
        statuses: List[str] = None
    ) -> List[Claim]:
        """
        Get claims directly linked to this context (not recursive).
        
        For recursive resolution, use resolve_claims().
        
        Args:
            context_id: ID of the context.
            statuses: Filter by claim status (default: active + contested).
            
        Returns:
            List of directly linked claims.
        """
        statuses = statuses or ClaimStatus.default_search_statuses()
        status_placeholders = ','.join(['?' for _ in statuses])
        
        user_filter = ""
        user_params = []
        if self.user_email:
            user_filter = " AND c.user_email = ?"
            user_params = [self.user_email]
        
        sql = f"""
            SELECT c.* FROM claims c
            JOIN context_claims cc ON c.claim_id = cc.claim_id
            WHERE cc.context_id = ?
              AND c.status IN ({status_placeholders}){user_filter}
            ORDER BY c.updated_at DESC
        """
        
        params = [context_id] + statuses + user_params
        rows = self.db.fetchall(sql, tuple(params))
        return [Claim.from_row(row) for row in rows]
    
    def get_contexts_for_claim(self, claim_id: str) -> List[Context]:
        """
        Get all contexts that a claim belongs to.
        
        Args:
            claim_id: ID of the claim.
            
        Returns:
            List of contexts containing this claim.
        """
        user_filter = ""
        user_params = []
        if self.user_email:
            user_filter = " AND ctx.user_email = ?"
            user_params = [self.user_email]
        
        sql = f"""
            SELECT ctx.* FROM contexts ctx
            JOIN context_claims cc ON ctx.context_id = cc.context_id
            WHERE cc.claim_id = ?{user_filter}
            ORDER BY ctx.name
        """
        
        params = [claim_id] + user_params
        rows = self.db.fetchall(sql, tuple(params))
        return [Context.from_row(row) for row in rows]
    
    def get_with_claim_count(self, limit: int = 100) -> List[Tuple[Context, int]]:
        """
        Get contexts with their claim counts.
        
        Args:
            limit: Maximum results.
            
        Returns:
            List of (context, claim_count) tuples.
        """
        user_filter = ""
        user_params = []
        if self.user_email:
            user_filter = " WHERE ctx.user_email = ?"
            user_params = [self.user_email]
        
        sql = f"""
            SELECT ctx.*, COUNT(cc.claim_id) as claim_count
            FROM contexts ctx
            LEFT JOIN context_claims cc ON ctx.context_id = cc.context_id
            {user_filter}
            GROUP BY ctx.context_id
            ORDER BY claim_count DESC
            LIMIT ?
        """
        
        params = user_params + [limit]
        rows = self.db.fetchall(sql, tuple(params))
        return [(Context.from_row(row), row['claim_count']) for row in rows]
    
    def _validate_no_cycle(
        self,
        context_id: str,
        parent_id: str
    ) -> None:
        """
        Validate that setting parent would not create a cycle.
        
        Args:
            context_id: ID of context being added/updated.
            parent_id: Proposed parent context ID.
            
        Raises:
            ValueError: If a cycle would be created.
        """
        if context_id == parent_id:
            raise ValueError(f"Context cannot be its own parent: {context_id}")
        
        visited = {context_id}
        current = parent_id
        
        while current:
            if current in visited:
                raise ValueError(
                    f"Cycle detected: setting parent to {parent_id} would create a cycle"
                )
            
            visited.add(current)
            parent = self.get(current)
            current = parent.parent_context_id if parent else None
