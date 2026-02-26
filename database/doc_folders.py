"""
Document folder management helpers.

Provides CRUD operations for the GlobalDocFolders table which enables
hierarchical folder organisation of global documents. Each folder belongs
to a user and may have a parent folder (via parent_id) allowing nested trees.

All functions open/close their own SQLite connections (consistent with other
database/ modules like global_docs.py and conversations.py).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional
import uuid

from database.connection import create_connection


logger = logging.getLogger(__name__)


def _db_path(*, users_dir: str) -> str:
    return os.path.join(users_dir, "users.db")


def create_folder(
    *, users_dir: str, user_email: str, name: str, parent_id: Optional[str] = None
) -> str:
    """Create a new folder for a user. Returns the new folder_id (uuid4)."""
    folder_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        conn.execute(
            "INSERT INTO GlobalDocFolders (folder_id, user_email, name, parent_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (folder_id, user_email, name, parent_id, now, now),
        )
        conn.commit()
        return folder_id
    except Exception as e:
        logger.error(f"Error creating folder {name} for {user_email}: {e}")
        return ""
    finally:
        conn.close()


def rename_folder(
    *, users_dir: str, user_email: str, folder_id: str, new_name: str
) -> bool:
    """Rename a folder. Returns True on success."""
    now = datetime.utcnow().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "UPDATE GlobalDocFolders SET name=?, updated_at=? WHERE folder_id=? AND user_email=?",
            (new_name, now, folder_id, user_email),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error renaming folder {folder_id}: {e}")
        return False
    finally:
        conn.close()


def move_folder(
    *, users_dir: str, user_email: str, folder_id: str, new_parent_id: Optional[str]
) -> bool:
    """Move a folder to a new parent (None = root). Returns True on success."""
    now = datetime.utcnow().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "UPDATE GlobalDocFolders SET parent_id=?, updated_at=? WHERE folder_id=? AND user_email=?",
            (new_parent_id, now, folder_id, user_email),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error moving folder {folder_id}: {e}")
        return False
    finally:
        conn.close()


def delete_folder(*, users_dir: str, user_email: str, folder_id: str) -> bool:
    """Delete a folder row. Does NOT delete docs or sub-folders — caller must handle them first."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "DELETE FROM GlobalDocFolders WHERE folder_id=? AND user_email=?",
            (folder_id, user_email),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting folder {folder_id}: {e}")
        return False
    finally:
        conn.close()


def list_folders(*, users_dir: str, user_email: str) -> list[dict]:
    """Return all folders for the user as a flat list. Client builds tree from parent_id.
    Each dict includes doc_count (number of docs directly in that folder)."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "SELECT folder_id, name, parent_id, created_at, updated_at FROM GlobalDocFolders WHERE user_email=? ORDER BY name",
            (user_email,),
        )
        folders = [
            dict(
                zip(["folder_id", "name", "parent_id", "created_at", "updated_at"], row)
            )
            for row in cur.fetchall()
        ]
        # Add doc_count for each folder
        for f in folders:
            cnt_cur = conn.execute(
                "SELECT COUNT(*) FROM GlobalDocuments WHERE user_email=? AND folder_id=?",
                (user_email, f["folder_id"]),
            )
            f["doc_count"] = cnt_cur.fetchone()[0]
        return folders
    except Exception as e:
        logger.error(f"Error listing folders for {user_email}: {e}")
        return []
    finally:
        conn.close()


def get_folder(*, users_dir: str, user_email: str, folder_id: str) -> Optional[dict]:
    """Get a single folder by ID."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "SELECT folder_id, name, parent_id, created_at, updated_at FROM GlobalDocFolders WHERE folder_id=? AND user_email=?",
            (folder_id, user_email),
        )
        row = cur.fetchone()
        if row:
            return dict(
                zip(["folder_id", "name", "parent_id", "created_at", "updated_at"], row)
            )
        return None
    except Exception as e:
        logger.error(f"Error getting folder {folder_id}: {e}")
        return None
    finally:
        conn.close()


def get_folder_by_name(*, users_dir: str, user_email: str, name: str) -> Optional[dict]:
    """Get folder by name (case-insensitive). Used for #folder: chat reference resolution."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "SELECT folder_id, name, parent_id, created_at, updated_at FROM GlobalDocFolders WHERE user_email=? AND lower(name)=lower(?)",
            (user_email, name),
        )
        row = cur.fetchone()
        if row:
            return dict(
                zip(["folder_id", "name", "parent_id", "created_at", "updated_at"], row)
            )
        return None
    except Exception as e:
        logger.error(f"Error getting folder by name {name}: {e}")
        return None
    finally:
        conn.close()


def assign_doc_to_folder(
    *, users_dir: str, user_email: str, doc_id: str, folder_id: Optional[str]
) -> bool:
    """Set GlobalDocuments.folder_id for a doc. Pass None to unfile (move to Unfiled)."""
    now = datetime.utcnow().isoformat()
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.execute(
            "UPDATE GlobalDocuments SET folder_id=?, updated_at=? WHERE doc_id=? AND user_email=?",
            (folder_id, now, doc_id, user_email),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Error assigning doc {doc_id} to folder {folder_id}: {e}")
        return False
    finally:
        conn.close()


def get_docs_in_folder(
    *,
    users_dir: str,
    user_email: str,
    folder_id: Optional[str],
    recursive: bool = False,
) -> list[str]:
    """Return doc_ids in a folder. folder_id=None means Unfiled (folder_id IS NULL).
    If recursive=True, includes docs in all descendant folders (BFS)."""
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        # Get direct docs in this folder
        if folder_id is None:
            cur = conn.execute(
                "SELECT doc_id FROM GlobalDocuments WHERE user_email=? AND folder_id IS NULL",
                (user_email,),
            )
        else:
            cur = conn.execute(
                "SELECT doc_id FROM GlobalDocuments WHERE user_email=? AND folder_id=?",
                (user_email, folder_id),
            )
        doc_ids = [row[0] for row in cur.fetchall()]

        if recursive and folder_id is not None:
            # BFS over child folders
            queue = [folder_id]
            visited = {folder_id}
            while queue:
                current = queue.pop(0)
                child_cur = conn.execute(
                    "SELECT folder_id FROM GlobalDocFolders WHERE user_email=? AND parent_id=?",
                    (user_email, current),
                )
                for (child_id,) in child_cur.fetchall():
                    if child_id not in visited:
                        visited.add(child_id)
                        queue.append(child_id)
                        # Get docs in this child folder
                        doc_cur = conn.execute(
                            "SELECT doc_id FROM GlobalDocuments WHERE user_email=? AND folder_id=?",
                            (user_email, child_id),
                        )
                        doc_ids.extend(row[0] for row in doc_cur.fetchall())

        return doc_ids
    except Exception as e:
        logger.error(f"Error getting docs in folder {folder_id}: {e}")
        return []
    finally:
        conn.close()
