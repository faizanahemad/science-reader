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
    folder_id: Optional[str] = None,
    index_type: str = "full",
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
             title, short_summary, folder_id, index_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, user_email, display_name, doc_source, doc_storage,
                title,
                short_summary,
                folder_id,
                index_type,
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
            SELECT gd.doc_id, gd.user_email, gd.display_name, gd.doc_source, gd.doc_storage,
                   gd.title, gd.short_summary, gd.created_at, gd.updated_at, gd.folder_id,
                   gd.index_type,
                   GROUP_CONCAT(gt.tag, ',') as tags_csv
            FROM GlobalDocuments gd
            LEFT JOIN GlobalDocTags gt ON gd.doc_id = gt.doc_id AND gd.user_email = gt.user_email
            WHERE gd.user_email = ?
            GROUP BY gd.doc_id, gd.user_email
            ORDER BY gd.created_at DESC
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
            "folder_id",
            "index_type",
            "tags_csv",
        ]
        result = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            tags_csv = row_dict.pop('tags_csv', '') or ''
            row_dict['tags'] = [t for t in tags_csv.split(',') if t]
            result.append(row_dict)
        return result
    finally:
        conn.close()

def list_global_docs_by_folder(*, users_dir: str, user_email: str, folder_id: Optional[str]) -> list[dict]:
    """Return global docs in a specific folder (or Unfiled if folder_id is None).
    Uses list_global_docs() and filters by folder_id for consistency."""
    all_docs = list_global_docs(users_dir=users_dir, user_email=user_email)
    if folder_id is None:
        return [d for d in all_docs if not d.get('folder_id')]
    return [d for d in all_docs if d.get('folder_id') == folder_id]

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


def update_doc_storage(
    *, users_dir: str, user_email: str, doc_id: str, new_storage: str
) -> bool:
    """
    Update the doc_storage path for a global doc after a filesystem move.

    Parameters
    ----------
    users_dir : str
        Path to users directory (for DB lookup).
    user_email : str
        Owner of the document.
    doc_id : str
        Document identifier.
    new_storage : str
        New filesystem path where the doc directory now lives.

    Returns
    -------
    bool
        True if a row was updated, False otherwise.
    """
    now = datetime.now().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE GlobalDocuments SET doc_storage=?, updated_at=? WHERE doc_id=? AND user_email=?",
            (new_storage, now, doc_id, user_email),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating doc_storage for {doc_id}: {e}")
        return False
    finally:
        conn.close()


def get_docs_in_fs_path(
    *, users_dir: str, user_email: str, path_prefix: str
) -> list:
    """
    Return all docs whose doc_storage starts with path_prefix.

    Used after a folder rename/move to bulk-update doc_storage paths for
    all documents contained within the renamed/moved directory tree.

    Parameters
    ----------
    users_dir : str
        Path to users directory (for DB lookup).
    user_email : str
        Owner of the documents.
    path_prefix : str
        Filesystem path prefix to match against doc_storage values.
        The trailing separator is normalised internally.

    Returns
    -------
    list[dict]
        Each dict contains 'doc_id' and 'doc_storage' keys.
    """
    # Escape LIKE wildcards in the path prefix
    escaped = path_prefix.rstrip(os.sep).replace('%', r'\%').replace('_', r'\_')
    like_pattern = escaped + os.sep + '%'
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT doc_id, doc_storage FROM GlobalDocuments WHERE user_email=? AND doc_storage LIKE ? ESCAPE '\\'",
            (user_email, like_pattern),
        )
        return [{"doc_id": row[0], "doc_storage": row[1]} for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error getting docs in fs path {path_prefix}: {e}")
        return []
    finally:
        conn.close()
