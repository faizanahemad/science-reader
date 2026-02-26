"""
Document tag management helpers.

Provides CRUD operations for the GlobalDocTags table which enables
free-form tagging of global documents. Tags are scoped per-user and
stored normalised (one row per doc+tag combination).

All functions open/close their own SQLite connections (consistent with other
database/ modules like global_docs.py and conversations.py).
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


def add_tag(*, users_dir: str, user_email: str, doc_id: str, tag: str) -> bool:
    """Add a single tag to a document. No-op if already exists.

    Returns True if a new tag row was inserted, False otherwise.
    """
    now = datetime.utcnow().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO GlobalDocTags (doc_id, user_email, tag, created_at) VALUES (?, ?, ?, ?)",
            (doc_id, user_email, tag, now),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error adding tag '{tag}' to doc {doc_id} for {user_email}: {e}")
        return False
    finally:
        conn.close()


def remove_tag(*, users_dir: str, user_email: str, doc_id: str, tag: str) -> bool:
    """Remove a single tag from a document.

    Returns True if a tag row was deleted, False otherwise.
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "DELETE FROM GlobalDocTags WHERE doc_id=? AND user_email=? AND tag=?",
            (doc_id, user_email, tag),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(
            f"Error removing tag '{tag}' from doc {doc_id} for {user_email}: {e}"
        )
        return False
    finally:
        conn.close()


def set_tags(*, users_dir: str, user_email: str, doc_id: str, tags: list[str]) -> bool:
    """Replace all tags for a document atomically in a single transaction.

    Deletes existing tags and inserts the new set. Returns True on success.
    """
    now = datetime.utcnow().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        conn.execute(
            "DELETE FROM GlobalDocTags WHERE doc_id=? AND user_email=?",
            (doc_id, user_email),
        )
        for tag in tags:
            conn.execute(
                "INSERT OR IGNORE INTO GlobalDocTags (doc_id, user_email, tag, created_at) VALUES (?, ?, ?, ?)",
                (doc_id, user_email, tag, now),
            )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting tags for doc {doc_id} for {user_email}: {e}")
        return False
    finally:
        conn.close()


def list_tags_for_doc(*, users_dir: str, user_email: str, doc_id: str) -> list[str]:
    """Return sorted list of tags for a document."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "SELECT tag FROM GlobalDocTags WHERE doc_id=? AND user_email=? ORDER BY tag",
            (doc_id, user_email),
        )
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error listing tags for doc {doc_id} for {user_email}: {e}")
        return []
    finally:
        conn.close()


def list_all_tags(*, users_dir: str, user_email: str) -> list[str]:
    """Return sorted list of distinct tags for the user across all documents."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "SELECT DISTINCT tag FROM GlobalDocTags WHERE user_email=? ORDER BY tag",
            (user_email,),
        )
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error listing all tags for {user_email}: {e}")
        return []
    finally:
        conn.close()


def list_docs_by_tag(*, users_dir: str, user_email: str, tag: str) -> list[str]:
    """Return doc_ids that have a given tag (case-insensitive)."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "SELECT doc_id FROM GlobalDocTags WHERE user_email=? AND lower(tag)=lower(?)",
            (user_email, tag),
        )
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error listing docs by tag '{tag}' for {user_email}: {e}")
        return []
    finally:
        conn.close()
