"""
Catalog CRUD for dynamic claim types and context domains.

TypeCatalogCRUD and DomainCatalogCRUD manage the claim_types_catalog and
context_domains_catalog tables respectively.  These tables store the set of
valid types/domains, combining system defaults (user_email IS NULL) with
user-defined entries.

Why we need this:
    In v0.4 and earlier, types and domains were hardcoded Python enums.
    v0.5.1 introduces dynamic types and domains stored in the database so
    that users can add custom ones without code changes.
"""

import logging
from typing import List, Dict, Optional

from ..database import PKBDatabase
from ..utils import now_iso

logger = logging.getLogger(__name__)


class TypeCatalogCRUD:
    """
    CRUD for claim_types_catalog.

    Each row has:
        type_name (PK together with user_email):  machine-readable key (e.g. 'fact')
        user_email:  NULL for system defaults, non-NULL for user-created
        display_name:  Human-friendly label (e.g. 'Fact')
        description:  Optional longer description
        created_at:  ISO timestamp

    Attributes:
        db: PKBDatabase instance.
        user_email: Optional user email; when set, list() merges system + user rows.
    """

    def __init__(self, db: PKBDatabase, user_email: Optional[str] = None):
        self.db = db
        self.user_email = user_email

    def list(self) -> List[Dict]:
        """Return all valid types (system + user-defined), ordered by name.

        Returns:
            List of dicts with keys: type_name, display_name, description,
            is_system (bool), created_at.
        """
        sql = """
            SELECT type_name, display_name, description, user_email, created_at
            FROM claim_types_catalog
            WHERE user_email = ''
        """
        params: list = []
        if self.user_email:
            sql += " OR user_email = ?"
            params.append(self.user_email)
        sql += " ORDER BY type_name"

        rows = self.db.fetchall(sql, tuple(params))
        result: List[Dict] = []
        seen = set()
        for r in rows:
            name = r["type_name"]
            if name in seen:
                continue
            seen.add(name)
            result.append({
                "type_name": name,
                "display_name": r["display_name"] or name.capitalize(),
                "description": r["description"],
                "is_system": r["user_email"] == '',
                "created_at": r["created_at"],
            })
        return result

    def add(self, type_name: str, display_name: str = None, description: str = None) -> Dict:
        """Add a user-defined type.

        Args:
            type_name: Machine-readable key.
            display_name: Human-friendly label.
            description: Optional description.

        Returns:
            Dict with the new entry.

        Raises:
            ValueError: If user_email is not set.
        """
        if not self.user_email:
            raise ValueError("Cannot add type without user_email")
        ts = now_iso()
        display = display_name or type_name.replace('_', ' ').capitalize()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO claim_types_catalog (type_name, user_email, display_name, description, created_at) VALUES (?, ?, ?, ?, ?)",
                (type_name, self.user_email, display, description, ts)
            )
        return {"type_name": type_name, "display_name": display, "description": description, "is_system": False, "created_at": ts}

    def delete(self, type_name: str) -> bool:
        """Delete a user-defined type.  System types cannot be deleted.

        Args:
            type_name: The type to delete.

        Returns:
            True if a row was deleted.
        """
        if not self.user_email:
            return False
        with self.db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM claim_types_catalog WHERE type_name = ? AND user_email = ?",
                (type_name, self.user_email)
            )
            return cur.rowcount > 0


class DomainCatalogCRUD:
    """
    CRUD for context_domains_catalog.

    Each row has:
        domain_name (PK together with user_email):  machine-readable key (e.g. 'health')
        user_email:  NULL for system defaults, non-NULL for user-created
        display_name:  Human-friendly label (e.g. 'Health')
        description:  Optional longer description
        created_at:  ISO timestamp

    Attributes:
        db: PKBDatabase instance.
        user_email: Optional user email; when set, list() merges system + user rows.
    """

    def __init__(self, db: PKBDatabase, user_email: Optional[str] = None):
        self.db = db
        self.user_email = user_email

    def list(self) -> List[Dict]:
        """Return all valid domains (system + user-defined), ordered by name.

        Returns:
            List of dicts with keys: domain_name, display_name, description,
            is_system (bool), created_at.
        """
        sql = """
            SELECT domain_name, display_name, description, user_email, created_at
            FROM context_domains_catalog
            WHERE user_email = ''
        """
        params: list = []
        if self.user_email:
            sql += " OR user_email = ?"
            params.append(self.user_email)
        sql += " ORDER BY domain_name"

        rows = self.db.fetchall(sql, tuple(params))
        result: List[Dict] = []
        seen = set()
        for r in rows:
            name = r["domain_name"]
            if name in seen:
                continue
            seen.add(name)
            result.append({
                "domain_name": name,
                "display_name": r["display_name"] or name.replace('_', ' ').title(),
                "description": r["description"],
                "is_system": r["user_email"] == '',
                "created_at": r["created_at"],
            })
        return result

    def add(self, domain_name: str, display_name: str = None, description: str = None) -> Dict:
        """Add a user-defined domain.

        Args:
            domain_name: Machine-readable key.
            display_name: Human-friendly label.
            description: Optional description.

        Returns:
            Dict with the new entry.

        Raises:
            ValueError: If user_email is not set.
        """
        if not self.user_email:
            raise ValueError("Cannot add domain without user_email")
        ts = now_iso()
        display = display_name or domain_name.replace('_', ' ').title()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO context_domains_catalog (domain_name, user_email, display_name, description, created_at) VALUES (?, ?, ?, ?, ?)",
                (domain_name, self.user_email, display, description, ts)
            )
        return {"domain_name": domain_name, "display_name": display, "description": description, "is_system": False, "created_at": ts}

    def delete(self, domain_name: str) -> bool:
        """Delete a user-defined domain.  System domains cannot be deleted.

        Args:
            domain_name: The domain to delete.

        Returns:
            True if a row was deleted.
        """
        if not self.user_email:
            return False
        with self.db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM context_domains_catalog WHERE domain_name = ? AND user_email = ?",
                (domain_name, self.user_email)
            )
            return cur.rowcount > 0
