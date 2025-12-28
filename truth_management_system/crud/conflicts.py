"""
Conflicts CRUD operations for PKB v0.

ConflictCRUD provides data access for conflict sets:
- create(): Create conflict set from 2+ claims (sets claims to contested)
- resolve(): Mark conflict as resolved with notes
- ignore(): Mark conflict as ignored
- add_member(): Add claim to existing conflict
- remove_member(): Remove claim from conflict
- get(): Retrieve by ID
- list(): Query with filters
"""

import sqlite3
import logging
from typing import Optional, List, Dict, Any

from .base import BaseCRUD
from ..database import PKBDatabase
from ..models import ConflictSet, CONFLICT_SET_COLUMNS
from ..constants import ConflictStatus, ClaimStatus
from ..utils import now_iso, generate_uuid

logger = logging.getLogger(__name__)


class ConflictCRUD(BaseCRUD[ConflictSet]):
    """
    CRUD operations for conflict sets.
    
    Conflict sets group contradicting claims for user review.
    When claims are added to a conflict set, their status is
    changed to "contested".
    
    Attributes:
        db: PKBDatabase instance.
        user_email: Optional user email for multi-user filtering.
    """
    
    def _table_name(self) -> str:
        return "conflict_sets"
    
    def _id_column(self) -> str:
        return "conflict_set_id"
    
    def _to_model(self, row: sqlite3.Row) -> ConflictSet:
        conflict_set = ConflictSet.from_row(row)
        # Populate member_claim_ids
        conflict_set.member_claim_ids = self._get_member_ids(conflict_set.conflict_set_id)
        return conflict_set
    
    def _ensure_user_email(self, conflict_set: ConflictSet) -> ConflictSet:
        """Ensure conflict_set has user_email set if CRUD has user_email."""
        if self.user_email and not conflict_set.user_email:
            conflict_set.user_email = self.user_email
        return conflict_set
    
    def _get_member_ids(self, conflict_set_id: str) -> List[str]:
        """Get claim IDs that are members of this conflict set."""
        rows = self.db.fetchall(
            "SELECT claim_id FROM conflict_set_members WHERE conflict_set_id = ?",
            (conflict_set_id,)
        )
        return [row['claim_id'] for row in rows]
    
    def create(
        self,
        claim_ids: List[str],
        notes: Optional[str] = None
    ) -> ConflictSet:
        """
        Create a new conflict set from 2+ claims.
        
        All member claims are set to "contested" status.
        If user_email is set, the conflict set is scoped to that user.
        
        Args:
            claim_ids: List of claim IDs (must be >= 2).
            notes: Optional notes about the conflict.
            
        Returns:
            The created conflict set.
            
        Raises:
            ValueError: If fewer than 2 claims provided.
        """
        if len(claim_ids) < 2:
            raise ValueError("Conflict set requires at least 2 claims")
        
        # Verify all claims exist (and belong to user if user_email is set)
        for claim_id in claim_ids:
            if self.user_email:
                row = self.db.fetchone(
                    "SELECT 1 FROM claims WHERE claim_id = ? AND user_email = ?", 
                    (claim_id, self.user_email)
                )
            else:
                row = self.db.fetchone("SELECT 1 FROM claims WHERE claim_id = ?", (claim_id,))
            if not row:
                raise ValueError(f"Claim not found: {claim_id}")
        
        conflict_set = ConflictSet.create(user_email=self.user_email, resolution_notes=notes)
        
        with self.db.transaction() as conn:
            # Insert conflict set
            columns = ', '.join(CONFLICT_SET_COLUMNS)
            placeholders = ', '.join(['?' for _ in CONFLICT_SET_COLUMNS])
            conn.execute(
                f"INSERT INTO conflict_sets ({columns}) VALUES ({placeholders})",
                conflict_set.to_insert_tuple()
            )
            
            # Add members
            for claim_id in claim_ids:
                conn.execute(
                    "INSERT INTO conflict_set_members (conflict_set_id, claim_id) VALUES (?, ?)",
                    (conflict_set.conflict_set_id, claim_id)
                )
            
            # Set claims to contested
            placeholders = ','.join(['?' for _ in claim_ids])
            conn.execute(
                f"UPDATE claims SET status = ?, updated_at = ? WHERE claim_id IN ({placeholders})",
                (ClaimStatus.CONTESTED.value, now_iso()) + tuple(claim_ids)
            )
            
            logger.info(f"Created conflict set {conflict_set.conflict_set_id} with {len(claim_ids)} claims")
        
        conflict_set.member_claim_ids = claim_ids
        return conflict_set
    
    def resolve(
        self,
        conflict_set_id: str,
        resolution_notes: str,
        winning_claim_id: Optional[str] = None,
        loser_status: str = ClaimStatus.SUPERSEDED.value
    ) -> Optional[ConflictSet]:
        """
        Mark conflict as resolved.
        
        If a winning claim is specified, it becomes "active" while
        others are set to loser_status (default: superseded).
        
        Args:
            conflict_set_id: ID of conflict set.
            resolution_notes: Notes explaining resolution.
            winning_claim_id: Optional claim ID that "won" the conflict.
            loser_status: Status for losing claims (superseded, retracted, historical).
            
        Returns:
            Updated conflict set or None if not found.
        """
        conflict_set = self.get(conflict_set_id)
        if not conflict_set:
            return None
        
        with self.db.transaction() as conn:
            # Update conflict set status
            conn.execute(
                "UPDATE conflict_sets SET status = ?, resolution_notes = ?, updated_at = ? WHERE conflict_set_id = ?",
                (ConflictStatus.RESOLVED.value, resolution_notes, now_iso(), conflict_set_id)
            )
            
            # Update claim statuses
            if winning_claim_id and winning_claim_id in conflict_set.member_claim_ids:
                # Winner becomes active
                conn.execute(
                    "UPDATE claims SET status = ?, updated_at = ? WHERE claim_id = ?",
                    (ClaimStatus.ACTIVE.value, now_iso(), winning_claim_id)
                )
                
                # Losers get loser_status
                losers = [cid for cid in conflict_set.member_claim_ids if cid != winning_claim_id]
                if losers:
                    placeholders = ','.join(['?' for _ in losers])
                    conn.execute(
                        f"UPDATE claims SET status = ?, updated_at = ? WHERE claim_id IN ({placeholders})",
                        (loser_status, now_iso()) + tuple(losers)
                    )
            else:
                # No winner, all remain contested (user can manually update)
                pass
            
            logger.info(f"Resolved conflict set {conflict_set_id}")
        
        return self.get(conflict_set_id)
    
    def ignore(self, conflict_set_id: str) -> Optional[ConflictSet]:
        """
        Mark conflict as ignored (user chose not to resolve).
        
        Claims remain contested but conflict is closed.
        
        Args:
            conflict_set_id: ID of conflict set.
            
        Returns:
            Updated conflict set or None if not found.
        """
        if not self.exists(conflict_set_id):
            return None
        
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE conflict_sets SET status = ?, updated_at = ? WHERE conflict_set_id = ?",
                (ConflictStatus.IGNORED.value, now_iso(), conflict_set_id)
            )
            
            logger.info(f"Ignored conflict set {conflict_set_id}")
        
        return self.get(conflict_set_id)
    
    def add_member(
        self,
        conflict_set_id: str,
        claim_id: str
    ) -> Optional[ConflictSet]:
        """
        Add a claim to an existing conflict set.
        
        The claim is set to "contested" status.
        
        Args:
            conflict_set_id: ID of conflict set.
            claim_id: ID of claim to add.
            
        Returns:
            Updated conflict set or None if not found.
        """
        if not self.exists(conflict_set_id):
            return None
        
        # Verify claim exists
        row = self.db.fetchone("SELECT 1 FROM claims WHERE claim_id = ?", (claim_id,))
        if not row:
            raise ValueError(f"Claim not found: {claim_id}")
        
        with self.db.transaction() as conn:
            # Add to members (ignore if already exists)
            conn.execute(
                "INSERT OR IGNORE INTO conflict_set_members (conflict_set_id, claim_id) VALUES (?, ?)",
                (conflict_set_id, claim_id)
            )
            
            # Set claim to contested
            conn.execute(
                "UPDATE claims SET status = ?, updated_at = ? WHERE claim_id = ?",
                (ClaimStatus.CONTESTED.value, now_iso(), claim_id)
            )
            
            logger.debug(f"Added claim {claim_id} to conflict set {conflict_set_id}")
        
        return self.get(conflict_set_id)
    
    def remove_member(
        self,
        conflict_set_id: str,
        claim_id: str,
        restore_status: str = ClaimStatus.ACTIVE.value
    ) -> Optional[ConflictSet]:
        """
        Remove a claim from a conflict set.
        
        If fewer than 2 claims remain, the conflict set is deleted.
        
        Args:
            conflict_set_id: ID of conflict set.
            claim_id: ID of claim to remove.
            restore_status: Status to set on removed claim.
            
        Returns:
            Updated conflict set, or None if deleted or not found.
        """
        conflict_set = self.get(conflict_set_id)
        if not conflict_set:
            return None
        
        if claim_id not in conflict_set.member_claim_ids:
            return conflict_set
        
        with self.db.transaction() as conn:
            # Remove from members
            conn.execute(
                "DELETE FROM conflict_set_members WHERE conflict_set_id = ? AND claim_id = ?",
                (conflict_set_id, claim_id)
            )
            
            # Restore claim status
            conn.execute(
                "UPDATE claims SET status = ?, updated_at = ? WHERE claim_id = ?",
                (restore_status, now_iso(), claim_id)
            )
            
            # Check remaining members
            remaining = conn.execute(
                "SELECT COUNT(*) FROM conflict_set_members WHERE conflict_set_id = ?",
                (conflict_set_id,)
            ).fetchone()[0]
            
            if remaining < 2:
                # Delete conflict set and restore remaining claim
                remaining_claims = conn.execute(
                    "SELECT claim_id FROM conflict_set_members WHERE conflict_set_id = ?",
                    (conflict_set_id,)
                ).fetchall()
                
                for row in remaining_claims:
                    conn.execute(
                        "UPDATE claims SET status = ?, updated_at = ? WHERE claim_id = ?",
                        (restore_status, now_iso(), row['claim_id'])
                    )
                
                conn.execute("DELETE FROM conflict_sets WHERE conflict_set_id = ?", (conflict_set_id,))
                logger.info(f"Deleted conflict set {conflict_set_id} (fewer than 2 members)")
                return None
            
            logger.debug(f"Removed claim {claim_id} from conflict set {conflict_set_id}")
        
        return self.get(conflict_set_id)
    
    def get_open(self) -> List[ConflictSet]:
        """Get all open (unresolved) conflict sets."""
        return self.list(filters={'status': ConflictStatus.OPEN.value}, order_by='-created_at')
    
    def get_for_claim(self, claim_id: str) -> List[ConflictSet]:
        """
        Get all conflict sets containing a claim.
        
        Args:
            claim_id: ID of claim.
            
        Returns:
            List of conflict sets containing the claim.
        """
        rows = self.db.fetchall("""
            SELECT cs.* FROM conflict_sets cs
            JOIN conflict_set_members csm ON cs.conflict_set_id = csm.conflict_set_id
            WHERE csm.claim_id = ?
            ORDER BY cs.created_at DESC
        """, (claim_id,))
        
        return [self._to_model(row) for row in rows]
