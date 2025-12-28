"""
Notes CRUD operations for PKB v0.

NoteCRUD provides data access for notes (narrative content):
- add(): Create new note
- edit(): Update note fields, invalidate embedding if body changes
- delete(): Hard-delete note
- get(): Retrieve by ID
- list(): Query with filters

FTS sync is handled by SQLite triggers (default).
"""

import sqlite3
import logging
from typing import Optional, List, Dict, Any

from .base import BaseCRUD, delete_note_embedding
from ..database import PKBDatabase
from ..models import Note, NOTE_COLUMNS
from ..utils import now_iso

logger = logging.getLogger(__name__)


class NoteCRUD(BaseCRUD[Note]):
    """
    CRUD operations for notes.
    
    Notes are for longer narrative content that doesn't fit the
    structured claim format. They support FTS search and embeddings.
    
    Attributes:
        db: PKBDatabase instance.
        user_email: Optional user email for multi-user filtering.
    """
    
    def _table_name(self) -> str:
        return "notes"
    
    def _id_column(self) -> str:
        return "note_id"
    
    def _to_model(self, row: sqlite3.Row) -> Note:
        return Note.from_row(row)
    
    def _ensure_user_email(self, note: Note) -> Note:
        """Ensure note has user_email set if CRUD has user_email."""
        if self.user_email and not note.user_email:
            note.user_email = self.user_email
        return note
    
    def add(self, note: Note) -> Note:
        """
        Add a new note.
        
        If user_email is set on this CRUD instance, it will be applied
        to the note if not already set.
        
        Args:
            note: Note instance to add.
            
        Returns:
            The added note.
            
        Example:
            note = Note.create(
                body="Meeting notes from today...",
                title="Team Sync 2024-01-15",
                context_domain="work"
            )
            note = crud.add(note)
        """
        # Ensure note has user_email
        note = self._ensure_user_email(note)
        
        with self.db.transaction() as conn:
            columns = ', '.join(NOTE_COLUMNS)
            placeholders = ', '.join(['?' for _ in NOTE_COLUMNS])
            
            conn.execute(
                f"INSERT INTO notes ({columns}) VALUES ({placeholders})",
                note.to_insert_tuple()
            )
            
            # FTS sync is handled by triggers
            logger.debug(f"Added note: {note.note_id}")
        
        return note
    
    def edit(
        self,
        note_id: str,
        patch: Dict[str, Any]
    ) -> Optional[Note]:
        """
        Update note fields.
        
        If 'body' is changed, the cached embedding is invalidated.
        
        Args:
            note_id: ID of note to update.
            patch: Dict of field-value pairs to update.
            
        Returns:
            Updated note or None if not found.
        """
        if not patch:
            return self.get(note_id)
        
        existing = self.get(note_id)
        if not existing:
            return None
        
        body_changed = 'body' in patch and patch['body'] != existing.body
        
        with self.db.transaction() as conn:
            sql, params = self._build_update_sql(note_id, patch)
            conn.execute(sql, params)
            
            # Invalidate embedding if body changed
            if body_changed:
                delete_note_embedding(conn, note_id)
                logger.debug(f"Invalidated embedding for note: {note_id}")
            
            logger.debug(f"Updated note: {note_id}")
        
        return self.get(note_id)
    
    def delete(self, note_id: str) -> bool:
        """
        Delete a note (hard delete).
        
        Unlike claims, notes are hard-deleted since they don't
        have conflict set dependencies.
        
        Args:
            note_id: ID of note to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        if not self.exists(note_id):
            return False
        
        with self.db.transaction() as conn:
            # Delete embedding first (cascade should handle this but be explicit)
            conn.execute("DELETE FROM note_embeddings WHERE note_id = ?", (note_id,))
            
            # Delete note (FTS cleanup handled by trigger)
            conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
            
            logger.debug(f"Deleted note: {note_id}")
        
        return True
    
    def get_by_domain(
        self,
        context_domain: str,
        limit: int = 100
    ) -> List[Note]:
        """
        Get notes in a specific domain.
        
        Args:
            context_domain: Domain to filter by.
            limit: Maximum notes to return.
            
        Returns:
            List of notes in the domain.
        """
        return self.list(
            filters={'context_domain': context_domain},
            order_by='-updated_at',
            limit=limit
        )
    
    def get_recent(self, limit: int = 20) -> List[Note]:
        """
        Get most recently updated notes.
        
        Args:
            limit: Maximum notes to return.
            
        Returns:
            List of recent notes.
        """
        return self.list(order_by='-updated_at', limit=limit)
    
    def search_by_title(
        self,
        title_pattern: str,
        limit: int = 100
    ) -> List[Note]:
        """
        Search notes by title (LIKE pattern).
        
        Args:
            title_pattern: Pattern to match (use % for wildcards).
            limit: Maximum notes to return.
            
        Returns:
            List of matching notes.
        """
        rows = self.db.fetchall(
            "SELECT * FROM notes WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (f"%{title_pattern}%", limit)
        )
        return [Note.from_row(row) for row in rows]
