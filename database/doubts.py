"""
Doubt clearing persistence helpers.

This module encapsulates SQLite operations against the `DoubtsClearing` table in
`users.db`.

These helpers were originally implemented in `server.py`. We move them here to
reduce the size of `server.py` and to keep database logic separate from route
handlers.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Optional

from database.connection import create_connection


_default_users_dir: Optional[str] = None


def configure_users_dir(users_dir: str) -> None:
    """
    Configure a default `users_dir` for convenience during incremental refactors.

    Prefer passing `users_dir=...` explicitly to each function; this default
    exists to keep legacy call sites working while we migrate.
    """

    global _default_users_dir
    _default_users_dir = users_dir


def _resolve_users_dir(users_dir: Optional[str]) -> str:
    if users_dir is not None:
        return users_dir
    if _default_users_dir is None:
        raise RuntimeError("users_dir not configured. Pass users_dir=... or call configure_users_dir(users_dir).")
    return _default_users_dir


def _db_path(*, users_dir: str) -> str:
    return f"{users_dir}/users.db"


def add_doubt(
    *,
    conversation_id: str,
    user_email: str,
    message_id: str,
    doubt_text: str,
    doubt_answer: str,
    parent_doubt_id: str | None = None,
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> str:
    """
    Add a new doubt clearing record.

    Returns
    -------
    str
        The generated `doubt_id`.
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat()

        doubt_content = f"{conversation_id}_{message_id}_{doubt_text}_{doubt_answer}_{now}_{parent_doubt_id or ''}"
        doubt_id = hashlib.md5(doubt_content.encode()).hexdigest()

        is_root_doubt = parent_doubt_id is None

        cur.execute(
            """
            INSERT INTO DoubtsClearing
            (doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer,
             parent_doubt_id, is_root_doubt, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, parent_doubt_id, is_root_doubt, now, now),
        )

        if parent_doubt_id:
            cur.execute(
                """
                UPDATE DoubtsClearing
                SET child_doubt_id = ?, updated_at = ?
                WHERE doubt_id = ?
                """,
                (doubt_id, now, parent_doubt_id),
            )

        conn.commit()
        doubt_type = "root doubt" if is_root_doubt else f"follow-up to {parent_doubt_id}"
        log.info(f"Added {doubt_type} with ID {doubt_id} for conversation {conversation_id}, message {message_id}")
        return doubt_id
    except Exception as e:
        log.error(f"Error adding doubt clearing: {e}")
        raise
    finally:
        conn.close()


def delete_doubt(*, doubt_id: str, users_dir: str | None = None, logger: logging.Logger | None = None) -> bool:
    """
    Delete a doubt clearing record by doubt_id with tree restructuring.

    When deleting a node, attach its children to its parent (linked-list style deletion).
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        cur.execute("SELECT parent_doubt_id FROM DoubtsClearing WHERE doubt_id = ?", (doubt_id,))
        row = cur.fetchone()
        if not row:
            log.warning(f"No doubt clearing found with ID {doubt_id}")
            return False

        parent_doubt_id = row[0]

        cur.execute("SELECT doubt_id FROM DoubtsClearing WHERE parent_doubt_id = ?", (doubt_id,))
        children = cur.fetchall()
        child_doubt_ids = [child[0] for child in children]

        for child_doubt_id in child_doubt_ids:
            cur.execute(
                """
                UPDATE DoubtsClearing
                SET parent_doubt_id = ?, is_root_doubt = ?
                WHERE doubt_id = ?
                """,
                (parent_doubt_id, parent_doubt_id is None, child_doubt_id),
            )

        cur.execute("DELETE FROM DoubtsClearing WHERE doubt_id = ?", (doubt_id,))
        deleted_count = cur.rowcount
        conn.commit()

        if deleted_count > 0:
            log.info(f"Deleted doubt clearing with ID {doubt_id} and restructured {len(child_doubt_ids)} children")
            return True

        log.warning(f"Failed to delete doubt clearing with ID {doubt_id}")
        return False
    except Exception as e:
        log.error(f"Error deleting doubt clearing: {e}")
        raise
    finally:
        conn.close()


def get_doubt(*, doubt_id: str, users_dir: str | None = None, logger: logging.Logger | None = None):
    """Retrieve a doubt clearing record by doubt_id."""

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer,
                   parent_doubt_id, is_root_doubt, created_at, updated_at
            FROM DoubtsClearing
            WHERE doubt_id = ?
            """,
            (doubt_id,),
        )
        row = cur.fetchone()
        if row:
            return {
                "doubt_id": row[0],
                "conversation_id": row[1],
                "user_email": row[2],
                "message_id": row[3],
                "doubt_text": row[4],
                "doubt_answer": row[5],
                "parent_doubt_id": row[6],
                "is_root_doubt": bool(row[7]),
                "created_at": row[8],
                "updated_at": row[9],
            }
        return None
    except Exception as e:
        log.error(f"Error getting doubt clearing: {e}")
        raise
    finally:
        conn.close()


def get_doubt_children(*, doubt_id: str, users_dir: str | None = None, logger: logging.Logger | None = None) -> list[dict]:
    """Get all direct children of a doubt."""

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer,
                   parent_doubt_id, is_root_doubt, created_at, updated_at
            FROM DoubtsClearing
            WHERE parent_doubt_id = ?
            ORDER BY created_at ASC
            """,
            (doubt_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "doubt_id": row[0],
                "conversation_id": row[1],
                "user_email": row[2],
                "message_id": row[3],
                "doubt_text": row[4],
                "doubt_answer": row[5],
                "parent_doubt_id": row[6],
                "is_root_doubt": bool(row[7]),
                "created_at": row[8],
                "updated_at": row[9],
            }
            for row in rows
        ]
    except Exception as e:
        log.error(f"Error getting doubt children: {e}")
        raise
    finally:
        conn.close()


def build_doubt_tree(doubt_record: dict, *, users_dir: str | None = None, logger: logging.Logger | None = None) -> dict:
    """
    Recursively build a tree structure for a doubt and all its descendants.

    Returns
    -------
    dict
        Doubt record with a `children` array containing nested structure.
    """

    doubt_tree = dict(doubt_record)
    children = get_doubt_children(doubt_id=doubt_record["doubt_id"], users_dir=users_dir, logger=logger)

    doubt_tree["children"] = []
    for child in children:
        doubt_tree["children"].append(build_doubt_tree(child, users_dir=users_dir, logger=logger))

    return doubt_tree


def get_doubts_for_message(
    *,
    conversation_id: str,
    message_id: str,
    user_email: str | None = None,
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> list[dict]:
    """
    Retrieve all doubt clearing records for a specific message in hierarchical structure.

    Returns
    -------
    list[dict]
        List of root doubt trees with nested children.
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        if user_email:
            cur.execute(
                """
                SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer,
                       parent_doubt_id, is_root_doubt, created_at, updated_at
                FROM DoubtsClearing
                WHERE conversation_id = ? AND message_id = ? AND user_email = ? AND is_root_doubt = 1
                ORDER BY created_at DESC
                """,
                (conversation_id, message_id, user_email),
            )
        else:
            cur.execute(
                """
                SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer,
                       parent_doubt_id, is_root_doubt, created_at, updated_at
                FROM DoubtsClearing
                WHERE conversation_id = ? AND message_id = ? AND is_root_doubt = 1
                ORDER BY created_at DESC
                """,
                (conversation_id, message_id),
            )

        rows = cur.fetchall()
        root_doubts = [
            {
                "doubt_id": row[0],
                "conversation_id": row[1],
                "user_email": row[2],
                "message_id": row[3],
                "doubt_text": row[4],
                "doubt_answer": row[5],
                "parent_doubt_id": row[6],
                "is_root_doubt": bool(row[7]),
                "created_at": row[8],
                "updated_at": row[9],
            }
            for row in rows
        ]

        return [build_doubt_tree(d, users_dir=users_dir_resolved, logger=logger) for d in root_doubts]
    except Exception as e:
        log.error(f"Error getting doubts for message: {e}")
        raise
    finally:
        conn.close()


def get_doubt_history(*, doubt_id: str, users_dir: str | None = None, logger: logging.Logger | None = None) -> list[dict]:
    """
    Get the complete history of a doubt thread from root to the specified doubt.

    Returns a chronological chain (root first).
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        doubt_chain: list[dict] = []
        current_doubt_id: str | None = doubt_id

        while current_doubt_id:
            cur.execute(
                """
                SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer,
                       parent_doubt_id, is_root_doubt, created_at, updated_at
                FROM DoubtsClearing
                WHERE doubt_id = ?
                """,
                (current_doubt_id,),
            )
            row = cur.fetchone()
            if not row:
                break

            doubt_chain.append(
                {
                    "doubt_id": row[0],
                    "conversation_id": row[1],
                    "user_email": row[2],
                    "message_id": row[3],
                    "doubt_text": row[4],
                    "doubt_answer": row[5],
                    "parent_doubt_id": row[6],
                    "is_root_doubt": bool(row[7]),
                    "created_at": row[8],
                    "updated_at": row[9],
                }
            )
            current_doubt_id = row[6]

        doubt_chain.reverse()
        return doubt_chain
    except Exception as e:
        log.error(f"Error getting doubt history: {e}")
        raise
    finally:
        conn.close()


