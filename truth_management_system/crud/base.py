"""
Base CRUD class and FTS sync helpers for PKB v0.

Provides:
- BaseCRUD: Abstract base class with shared CRUD patterns
- sync_claim_to_fts(): Manual FTS sync for claims (if triggers disabled)
- sync_note_to_fts(): Manual FTS sync for notes (if triggers disabled)

The BaseCRUD class provides common operations like get(), list(), and
timestamp updates. Concrete implementations override for specific tables.

Note: If using FTS triggers (default), manual sync is not needed.
Manual sync functions are provided for cases where triggers are disabled.
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional, List, Dict, Any
import sqlite3
import logging

from ..database import PKBDatabase
from ..utils import now_iso

T = TypeVar('T')

logger = logging.getLogger(__name__)


class BaseCRUD(ABC, Generic[T]):
    """
    Abstract base class for CRUD operations.
    
    Provides common patterns for database access:
    - get(): Retrieve single record by ID
    - list(): Query with filters, pagination
    - _update_timestamp(): Set updated_at on modifications
    
    Subclasses must implement:
    - _table_name(): Return table name
    - _id_column(): Return primary key column name
    - _to_model(): Convert SQLite row to model instance
    
    Attributes:
        db: PKBDatabase instance for data access.
        user_email: Optional user email for multi-user filtering.
    """
    
    def __init__(self, db: PKBDatabase, user_email: Optional[str] = None):
        """
        Initialize CRUD with database connection.
        
        Args:
            db: PKBDatabase instance.
            user_email: Optional user email for multi-user filtering.
                       If provided, all operations are scoped to this user.
        """
        self.db = db
        self.user_email = user_email
    
    @abstractmethod
    def _table_name(self) -> str:
        """Return the database table name."""
        pass
    
    @abstractmethod
    def _id_column(self) -> str:
        """Return the primary key column name."""
        pass
    
    @abstractmethod
    def _to_model(self, row: sqlite3.Row) -> T:
        """Convert SQLite row to model instance."""
        pass
    
    def _user_filter_sql(self, prefix: str = "WHERE") -> str:
        """
        Build SQL fragment for user_email filtering.
        
        Args:
            prefix: SQL prefix ('WHERE' or 'AND').
            
        Returns:
            SQL fragment for user filtering, or empty string if no filter.
        """
        if self.user_email:
            return f" {prefix} user_email = ?"
        return ""
    
    def _user_filter_params(self) -> tuple:
        """Get params for user filtering."""
        return (self.user_email,) if self.user_email else ()
    
    def get(self, id: str) -> Optional[T]:
        """
        Retrieve a single record by ID.
        
        If user_email is set, only returns records owned by that user.
        
        Args:
            id: Primary key value.
            
        Returns:
            Model instance or None if not found.
        """
        if self.user_email:
            row = self.db.fetchone(
                f"SELECT * FROM {self._table_name()} WHERE {self._id_column()} = ? AND user_email = ?",
                (id, self.user_email)
            )
        else:
            row = self.db.fetchone(
                f"SELECT * FROM {self._table_name()} WHERE {self._id_column()} = ?",
                (id,)
            )
        return self._to_model(row) if row else None
    
    def exists(self, id: str) -> bool:
        """
        Check if a record exists.
        
        If user_email is set, only checks records owned by that user.
        
        Args:
            id: Primary key value.
            
        Returns:
            True if record exists.
        """
        if self.user_email:
            row = self.db.fetchone(
                f"SELECT 1 FROM {self._table_name()} WHERE {self._id_column()} = ? AND user_email = ?",
                (id, self.user_email)
            )
        else:
            row = self.db.fetchone(
                f"SELECT 1 FROM {self._table_name()} WHERE {self._id_column()} = ?",
                (id,)
            )
        return row is not None
    
    def list(
        self,
        filters: Dict[str, Any] = None,
        order_by: str = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[T]:
        """
        Query records with filters and pagination.
        
        If user_email is set, only returns records owned by that user.
        
        Args:
            filters: Column-value pairs for WHERE clause.
            order_by: Column name for ORDER BY (prefix with - for DESC).
            limit: Maximum records to return.
            offset: Number of records to skip.
            
        Returns:
            List of model instances.
        """
        sql = f"SELECT * FROM {self._table_name()}"
        params = []
        conditions = []
        
        # Add user_email filter if set
        if self.user_email:
            conditions.append("user_email = ?")
            params.append(self.user_email)
        
        # Build WHERE clause from filters
        if filters:
            for col, val in filters.items():
                if val is None:
                    conditions.append(f"{col} IS NULL")
                elif isinstance(val, (list, tuple)):
                    placeholders = ','.join(['?' for _ in val])
                    conditions.append(f"{col} IN ({placeholders})")
                    params.extend(val)
                else:
                    conditions.append(f"{col} = ?")
                    params.append(val)
        
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        
        # Add ORDER BY
        if order_by:
            if order_by.startswith('-'):
                sql += f" ORDER BY {order_by[1:]} DESC"
            else:
                sql += f" ORDER BY {order_by} ASC"
        else:
            sql += f" ORDER BY {self._id_column()} ASC"
        
        # Add pagination
        sql += f" LIMIT {limit} OFFSET {offset}"
        
        rows = self.db.fetchall(sql, tuple(params))
        return [self._to_model(row) for row in rows]
    
    def count(self, filters: Dict[str, Any] = None) -> int:
        """
        Count records matching filters.
        
        If user_email is set, only counts records owned by that user.
        
        Args:
            filters: Column-value pairs for WHERE clause.
            
        Returns:
            Count of matching records.
        """
        sql = f"SELECT COUNT(*) FROM {self._table_name()}"
        params = []
        conditions = []
        
        # Add user_email filter if set
        if self.user_email:
            conditions.append("user_email = ?")
            params.append(self.user_email)
        
        if filters:
            for col, val in filters.items():
                if val is None:
                    conditions.append(f"{col} IS NULL")
                elif isinstance(val, (list, tuple)):
                    placeholders = ','.join(['?' for _ in val])
                    conditions.append(f"{col} IN ({placeholders})")
                    params.extend(val)
                else:
                    conditions.append(f"{col} = ?")
                    params.append(val)
        
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        
        row = self.db.fetchone(sql, tuple(params))
        return row[0] if row else 0
    
    def _update_timestamp(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add updated_at timestamp to data dict.
        
        Args:
            data: Dictionary of column values.
            
        Returns:
            Data dict with updated_at set.
        """
        data['updated_at'] = now_iso()
        return data
    
    def _build_update_sql(
        self,
        id: str,
        patch: Dict[str, Any]
    ) -> tuple:
        """
        Build UPDATE SQL statement.
        
        Args:
            id: Primary key value.
            patch: Column-value pairs to update.
            
        Returns:
            Tuple of (sql, params).
        """
        patch = self._update_timestamp(patch)
        
        set_clause = ', '.join([f"{k} = ?" for k in patch.keys()])
        params = list(patch.values()) + [id]
        
        sql = f"UPDATE {self._table_name()} SET {set_clause} WHERE {self._id_column()} = ?"
        return sql, params


# =============================================================================
# FTS Sync Helpers (for manual sync when triggers are disabled)
# =============================================================================

def sync_claim_to_fts(
    conn: sqlite3.Connection,
    claim_id: str,
    operation: str
) -> None:
    """
    Manually sync a claim to the FTS index.
    
    Note: Only needed if FTS triggers are disabled.
    With triggers enabled (default), this is handled automatically.
    
    Args:
        conn: Active database connection.
        claim_id: ID of claim to sync.
        operation: 'insert', 'update', or 'delete'.
    """
    if operation == 'delete':
        # For delete, we need the rowid which we don't have
        # This is why triggers are preferred
        logger.warning("Manual FTS delete requires rowid - use triggers instead")
        return
    
    # Get claim data
    row = conn.execute(
        "SELECT rowid, * FROM claims WHERE claim_id = ?",
        (claim_id,)
    ).fetchone()
    
    if not row:
        return
    
    if operation == 'insert':
        conn.execute("""
            INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (row['rowid'], row['claim_id'], row['statement'], row['predicate'],
              row['object_text'], row['subject_text'], row['context_domain']))
    
    elif operation == 'update':
        # FTS5 update = delete + insert
        conn.execute("""
            INSERT INTO claims_fts(claims_fts, rowid, claim_id, statement, predicate, object_text, subject_text, context_domain)
            VALUES ('delete', ?, ?, ?, ?, ?, ?, ?)
        """, (row['rowid'], row['claim_id'], row['statement'], row['predicate'],
              row['object_text'], row['subject_text'], row['context_domain']))
        
        conn.execute("""
            INSERT INTO claims_fts(rowid, claim_id, statement, predicate, object_text, subject_text, context_domain)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (row['rowid'], row['claim_id'], row['statement'], row['predicate'],
              row['object_text'], row['subject_text'], row['context_domain']))


def sync_note_to_fts(
    conn: sqlite3.Connection,
    note_id: str,
    operation: str
) -> None:
    """
    Manually sync a note to the FTS index.
    
    Note: Only needed if FTS triggers are disabled.
    
    Args:
        conn: Active database connection.
        note_id: ID of note to sync.
        operation: 'insert', 'update', or 'delete'.
    """
    if operation == 'delete':
        logger.warning("Manual FTS delete requires rowid - use triggers instead")
        return
    
    row = conn.execute(
        "SELECT rowid, * FROM notes WHERE note_id = ?",
        (note_id,)
    ).fetchone()
    
    if not row:
        return
    
    if operation == 'insert':
        conn.execute("""
            INSERT INTO notes_fts(rowid, note_id, title, body, context_domain)
            VALUES (?, ?, ?, ?, ?)
        """, (row['rowid'], row['note_id'], row['title'], row['body'], row['context_domain']))
    
    elif operation == 'update':
        conn.execute("""
            INSERT INTO notes_fts(notes_fts, rowid, note_id, title, body, context_domain)
            VALUES ('delete', ?, ?, ?, ?, ?)
        """, (row['rowid'], row['note_id'], row['title'], row['body'], row['context_domain']))
        
        conn.execute("""
            INSERT INTO notes_fts(rowid, note_id, title, body, context_domain)
            VALUES (?, ?, ?, ?, ?)
        """, (row['rowid'], row['note_id'], row['title'], row['body'], row['context_domain']))


def delete_claim_embedding(conn: sqlite3.Connection, claim_id: str) -> None:
    """
    Delete cached embedding for a claim.
    
    Called when claim statement changes to invalidate stale embedding.
    
    Args:
        conn: Active database connection.
        claim_id: ID of claim.
    """
    conn.execute("DELETE FROM claim_embeddings WHERE claim_id = ?", (claim_id,))


def delete_note_embedding(conn: sqlite3.Connection, note_id: str) -> None:
    """
    Delete cached embedding for a note.
    
    Args:
        conn: Active database connection.
        note_id: ID of note.
    """
    conn.execute("DELETE FROM note_embeddings WHERE note_id = ?", (note_id,))
