"""
Global document persistence helpers.

Provides CRUD operations for the GlobalDocuments table which tracks documents
that are indexed once and referenceable from any conversation via #gdoc_N syntax.

All functions open/close their own SQLite connections (consistent with other
database/ modules like conversations.py and workspaces.py).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from database.connection import create_connection


logger = logging.getLogger(__name__)


def _db_path(*, users_dir: str) -> str:
    return os.path.join(users_dir, "users.db")


def add_global_doc(
    *,
    users_dir: str,
    user_email: str,
    doc_id: str,
    doc_source: str,
    doc_storage: str,
    title: str = "",
    short_summary: str = "",
    display_name: str = "",
) -> bool:
    """
    Insert a new global doc row. Deduplicates on (doc_id, user_email).

    Returns True if inserted, False if already exists or error.
    """
    now = datetime.now().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO GlobalDocuments
            (doc_id, user_email, display_name, doc_source, doc_storage,
             title, short_summary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                user_email,
                display_name,
                doc_source,
                doc_storage,
                title,
                short_summary,
                now,
                now,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error adding global doc {doc_id} for {user_email}: {e}")
        return False
    finally:
        conn.close()


def list_global_docs(*, users_dir: str, user_email: str) -> list[dict]:
    """
    Return all global docs for a user, ordered by created_at ASC.

    Each dict contains: doc_id, user_email, display_name, doc_source,
    doc_storage, title, short_summary, created_at, updated_at.
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT doc_id, user_email, display_name, doc_source, doc_storage,
                   title, short_summary, created_at, updated_at
            FROM GlobalDocuments
            WHERE user_email = ?
            ORDER BY created_at ASC
            """,
            (user_email,),
        )
        rows = cur.fetchall()
        columns = [
            "doc_id",
            "user_email",
            "display_name",
            "doc_source",
            "doc_storage",
            "title",
            "short_summary",
            "created_at",
            "updated_at",
        ]
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def get_global_doc(*, users_dir: str, user_email: str, doc_id: str) -> Optional[dict]:
    """Return a single global doc row or None."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT doc_id, user_email, display_name, doc_source, doc_storage,
                   title, short_summary, created_at, updated_at
            FROM GlobalDocuments
            WHERE user_email = ? AND doc_id = ?
            """,
            (user_email, doc_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        columns = [
            "doc_id",
            "user_email",
            "display_name",
            "doc_source",
            "doc_storage",
            "title",
            "short_summary",
            "created_at",
            "updated_at",
        ]
        return dict(zip(columns, row))
    finally:
        conn.close()


def delete_global_doc(*, users_dir: str, user_email: str, doc_id: str) -> bool:
    """
    Delete a global doc row.

    Does NOT delete filesystem storage — caller is responsible for that.
    Returns True if a row was deleted.
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM GlobalDocuments WHERE user_email = ? AND doc_id = ?",
            (user_email, doc_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting global doc {doc_id} for {user_email}: {e}")
        return False
    finally:
        conn.close()


def update_global_doc_metadata(
    *,
    users_dir: str,
    user_email: str,
    doc_id: str,
    title: Optional[str] = None,
    short_summary: Optional[str] = None,
    display_name: Optional[str] = None,
) -> bool:
    """
    Update cached metadata fields on a global doc row.

    Only non-None fields are updated. Returns True if a row was updated.
    """
    updates = []
    values = []
    if title is not None:
        updates.append("title = ?")
        values.append(title)
    if short_summary is not None:
        updates.append("short_summary = ?")
        values.append(short_summary)
    if display_name is not None:
        updates.append("display_name = ?")
        values.append(display_name)

    if not updates:
        return False

    updates.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.extend([user_email, doc_id])

    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE GlobalDocuments SET {', '.join(updates)} WHERE user_email = ? AND doc_id = ?",
            values,
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating global doc {doc_id} for {user_email}: {e}")
        return False
    finally:
        conn.close()
