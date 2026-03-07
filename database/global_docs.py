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
    priority: int = 3,
    date_written: Optional[str] = None,
    deprecated: bool = False,
) -> bool:
    """
    Insert a new global doc row. Deduplicates on (doc_id, user_email).

    Returns True if inserted, False if already exists or error.
    """
    now = datetime.now().isoformat()
    priority = max(1, min(5, int(priority)))
    deprecated_int = 1 if deprecated else 0
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO GlobalDocuments
            (doc_id, user_email, display_name, doc_source, doc_storage,
             title, short_summary, folder_id, index_type,
             priority, date_written, deprecated,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, user_email, display_name, doc_source, doc_storage,
                title,
                short_summary,
                folder_id,
                index_type,
                priority,
                date_written,
                deprecated_int,
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
    Return all global docs for a user, ordered by created_at DESC.

    Each dict contains: doc_id, user_email, display_name, doc_source,
    doc_storage, title, short_summary, created_at, updated_at, folder_id,
    index_type, tags, priority, priority_label, date_written, deprecated.
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT gd.doc_id, gd.user_email, gd.display_name, gd.doc_source, gd.doc_storage,
                   gd.title, gd.short_summary, gd.created_at, gd.updated_at, gd.folder_id,
                   gd.index_type,
                   gd.priority, gd.date_written, gd.deprecated,
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
            "priority",
            "date_written",
            "deprecated",
            "tags_csv",
        ]
        result = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            tags_csv = row_dict.pop('tags_csv', '') or ''
            row_dict['tags'] = [t for t in tags_csv.split(',') if t]
            row_dict['priority'] = row_dict.get('priority') or 3
            row_dict['priority_label'] = {1: 'very low', 2: 'low', 3: 'medium', 4: 'high', 5: 'very high'}.get(row_dict['priority'], 'medium')
            row_dict['deprecated'] = bool(row_dict.get('deprecated', 0))
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
                   title, short_summary, created_at, updated_at,
                   folder_id, index_type, priority, date_written, deprecated
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
            "folder_id",
            "index_type",
            "priority",
            "date_written",
            "deprecated",
        ]
        row_dict = dict(zip(columns, row))
        row_dict['priority'] = row_dict.get('priority') or 3
        row_dict['priority_label'] = {1: 'very low', 2: 'low', 3: 'medium', 4: 'high', 5: 'very high'}.get(row_dict['priority'], 'medium')
        row_dict['deprecated'] = bool(row_dict.get('deprecated', 0))
        return row_dict
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


def replace_global_doc(
    *,
    users_dir: str,
    user_email: str,
    old_doc_id: str,
    new_doc_id: str,
    new_doc_source: str,
    new_doc_storage: str,
    new_title: str,
    new_short_summary: str,
    new_index_type: str = "full",
) -> bool:
    """
    Replace a global doc's identity (doc_id, source, storage, title, summary)
    while preserving user-set metadata (display_name, priority, date_written,
    deprecated, folder_id, tags, created_at).

    Strategy: read old row -> delete old row -> insert new row with merged fields.
    This handles the primary key change (doc_id changes when file type changes).
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        # Read old row to preserve metadata
        cur.execute(
            "SELECT * FROM GlobalDocuments WHERE user_email = ? AND doc_id = ?",
            (user_email, old_doc_id),
        )
        old_row = cur.fetchone()
        if old_row is None:
            return False

        # Column name mapping from row
        columns = [desc[0] for desc in cur.description]
        old_data = dict(zip(columns, old_row))

        # Delete old row
        cur.execute(
            "DELETE FROM GlobalDocuments WHERE user_email = ? AND doc_id = ?",
            (user_email, old_doc_id),
        )

        # Insert new row with merged fields
        now = datetime.now().isoformat()
        cur.execute(
            """INSERT INTO GlobalDocuments
               (doc_id, user_email, display_name, doc_source, doc_storage,
                title, short_summary, folder_id, index_type,
                priority, date_written, deprecated, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_doc_id,
                user_email,
                old_data.get("display_name", ""),
                new_doc_source,
                new_doc_storage,
                new_title,
                new_short_summary,
                old_data.get("folder_id"),
                new_index_type,
                old_data.get("priority", 3),
                old_data.get("date_written"),
                old_data.get("deprecated", 0),
                old_data.get("created_at", now),
                now,
            ),
        )
        conn.commit()

        # Migrate tags from old doc_id to new doc_id
        try:
            cur.execute(
                "UPDATE GlobalDocTags SET doc_id = ? WHERE user_email = ? AND doc_id = ?",
                (new_doc_id, user_email, old_doc_id),
            )
            conn.commit()
        except Exception:
            pass  # Tags table may not exist or have no entries

        return True
    except Exception as e:
        logger.error(f"Error replacing global doc {old_doc_id} -> {new_doc_id}: {e}")
        conn.rollback()
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
    priority: Optional[int] = None,
    date_written: Optional[str] = None,
    deprecated: Optional[bool] = None,
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
    if priority is not None:
        updates.append("priority = ?")
        values.append(max(1, min(5, int(priority))))
    if date_written is not None:
        updates.append("date_written = ?")
        values.append(date_written)
    if deprecated is not None:
        updates.append("deprecated = ?")
        values.append(1 if deprecated else 0)
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
