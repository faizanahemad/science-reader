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
    with_context: bool = False,
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
             parent_doubt_id, is_root_doubt, with_context, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer, parent_doubt_id, is_root_doubt, with_context, now, now),
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


def delete_doubt(*, doubt_id: str, users_dir: str | None = None, logger: logging.Logger | None = None) -> list[str]:
    """
    Delete a doubt clearing record by doubt_id, including its entire subtree.

    Deletion is recursive: the target doubt and all of its descendants
    (children, grandchildren, ...) are removed. Deleting a root doubt therefore
    removes its whole tree.

    Returns the list of deleted doubt_ids (the target plus all descendants), or
    an empty list if the target doubt did not exist / nothing was deleted.
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        cur.execute("SELECT doubt_id FROM DoubtsClearing WHERE doubt_id = ?", (doubt_id,))
        if not cur.fetchone():
            log.warning(f"No doubt clearing found with ID {doubt_id}")
            return []

        # Collect the target plus all descendants via a breadth-first walk of the
        # parent_doubt_id links, then delete them all in one statement.
        ids_to_delete: list[str] = [doubt_id]
        frontier: list[str] = [doubt_id]
        while frontier:
            placeholders = ",".join("?" for _ in frontier)
            cur.execute(
                f"SELECT doubt_id FROM DoubtsClearing WHERE parent_doubt_id IN ({placeholders})",
                tuple(frontier),
            )
            children = [r[0] for r in cur.fetchall()]
            # Guard against accidental cycles in the data.
            children = [c for c in children if c not in ids_to_delete]
            if not children:
                break
            ids_to_delete.extend(children)
            frontier = children

        placeholders = ",".join("?" for _ in ids_to_delete)
        cur.execute(
            f"DELETE FROM DoubtsClearing WHERE doubt_id IN ({placeholders})",
            tuple(ids_to_delete),
        )
        deleted_count = cur.rowcount
        conn.commit()

        if deleted_count > 0:
            log.info(
                f"Deleted doubt clearing with ID {doubt_id} and "
                f"{len(ids_to_delete) - 1} descendant(s) "
                f"({deleted_count} record(s) removed)"
            )
            return ids_to_delete

        log.warning(f"Failed to delete doubt clearing with ID {doubt_id}")
        return []
    except Exception as e:
        log.error(f"Error deleting doubt clearing: {e}")
        raise
    finally:
        conn.close()


def update_doubt_show_hide(
    *,
    doubt_id: str,
    show_hide: str,
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Persist the per-doubt collapse state for the doubt chat modal.

    Parameters
    ----------
    doubt_id : str
        The doubt record to update.
    show_hide : str
        Either ``"show"`` (expanded) or ``"hide"`` (collapsed).

    Returns
    -------
    bool
        True if a row was updated, False otherwise.
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    # Normalise to the two accepted values; anything else is treated as expanded.
    normalised = "hide" if str(show_hide).lower() == "hide" else "show"

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute(
            """
            UPDATE DoubtsClearing
            SET show_hide = ?, updated_at = ?
            WHERE doubt_id = ?
            """,
            (normalised, now, doubt_id),
        )
        updated = cur.rowcount
        conn.commit()
        if updated > 0:
            log.info(f"Updated show_hide={normalised} for doubt {doubt_id}")
            return True
        log.warning(f"No doubt found with ID {doubt_id} to update show_hide")
        return False
    except Exception as e:
        log.error(f"Error updating doubt show_hide: {e}")
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
                   parent_doubt_id, is_root_doubt, created_at, updated_at, show_hide, with_context,
                   pinned, bookmarked
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
                "show_hide": row[10] or "show",
                "with_context": bool(row[11]),
                "pinned": bool(row[12]),
                "bookmarked": bool(row[13]),
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
                   parent_doubt_id, is_root_doubt, created_at, updated_at, show_hide, with_context,
                   pinned, bookmarked
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
                "show_hide": row[10] or "show",
                "with_context": bool(row[11]),
                "pinned": bool(row[12]),
                "bookmarked": bool(row[13]),
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
                       parent_doubt_id, is_root_doubt, created_at, updated_at, show_hide, with_context,
                       pinned, bookmarked
                FROM DoubtsClearing
                WHERE conversation_id = ? AND message_id = ? AND user_email = ? AND is_root_doubt = 1
                ORDER BY pinned DESC, created_at DESC
                """,
                (conversation_id, message_id, user_email),
            )
        else:
            cur.execute(
                """
                SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer,
                       parent_doubt_id, is_root_doubt, created_at, updated_at, show_hide, with_context,
                       pinned, bookmarked
                FROM DoubtsClearing
                WHERE conversation_id = ? AND message_id = ? AND is_root_doubt = 1
                ORDER BY pinned DESC, created_at DESC
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
                "show_hide": row[10] or "show",
                "with_context": bool(row[11]),
                "pinned": bool(row[12]),
                "bookmarked": bool(row[13]),
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
                       parent_doubt_id, is_root_doubt, created_at, updated_at, show_hide, with_context,
                       pinned, bookmarked
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
                    "show_hide": row[10] or "show",
                    "with_context": bool(row[11]),
                    "pinned": bool(row[12]),
                    "bookmarked": bool(row[13]),
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



def get_message_ids_with_doubts(
    *,
    conversation_id: str,
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> list[str]:
    """Return distinct message_ids that have at least one root doubt in this conversation."""
    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT message_id FROM DoubtsClearing WHERE conversation_id = ? AND is_root_doubt = 1",
            (conversation_id,),
        )
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        log.error(f"Error getting message_ids with doubts: {e}")
        return []
    finally:
        conn.close()


def update_doubt_pinned(*, doubt_id: str, pinned: bool, users_dir: str | None = None, logger: logging.Logger | None = None) -> bool:
    """Toggle the pinned state of a doubt."""
    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute(
            "UPDATE DoubtsClearing SET pinned = ?, updated_at = ? WHERE doubt_id = ?",
            (int(pinned), now, doubt_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        log.error(f"Error updating doubt pinned: {e}")
        raise
    finally:
        conn.close()


def update_doubt_bookmarked(*, doubt_id: str, bookmarked: bool, users_dir: str | None = None, logger: logging.Logger | None = None) -> bool:
    """Toggle the bookmarked state of a doubt."""
    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute(
            "UPDATE DoubtsClearing SET bookmarked = ?, updated_at = ? WHERE doubt_id = ?",
            (int(bookmarked), now, doubt_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        log.error(f"Error updating doubt bookmarked: {e}")
        raise
    finally:
        conn.close()


def update_doubt_answer(*, doubt_id: str, doubt_answer: str, users_dir: str | None = None, logger: logging.Logger | None = None) -> bool:
    """Update the answer text of an existing doubt (used by regeneration)."""
    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute(
            "UPDATE DoubtsClearing SET doubt_answer = ?, updated_at = ? WHERE doubt_id = ?",
            (doubt_answer, now, doubt_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        log.error(f"Error updating doubt answer: {e}")
        raise
    finally:
        conn.close()


def get_all_doubts_for_user(
    *,
    user_email: str,
    page: int = 1,
    page_size: int = 20,
    search: str = "",
    filter_type: str = "all",
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> dict:
    """
    Get paginated root doubts across all conversations for a user.

    Returns dict with keys: doubts (list), total (int), page (int), page_size (int).
    """
    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        conditions = ["user_email = ?", "is_root_doubt = 1"]
        params: list = [user_email]

        if search:
            conditions.append("(doubt_text LIKE ? OR doubt_answer LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if filter_type == "pinned":
            conditions.append("pinned = 1")
        elif filter_type == "user":
            conditions.append("doubt_text NOT IN ('Auto takeaways', 'Maximize Learning and Perspectives', 'Challenge & Verify', 'Foundations & Practice', 'Answer Raised Questions')")
        elif filter_type == "auto":
            conditions.append("doubt_text IN ('Auto takeaways', 'Maximize Learning and Perspectives', 'Challenge & Verify', 'Foundations & Practice', 'Answer Raised Questions')")

        where = " AND ".join(conditions)

        # Count
        cur.execute(f"SELECT COUNT(*) FROM DoubtsClearing WHERE {where}", params)
        total = cur.fetchone()[0]

        # Fetch page
        offset = (page - 1) * page_size
        cur.execute(
            f"""SELECT doubt_id, conversation_id, user_email, message_id, doubt_text, doubt_answer,
                       parent_doubt_id, is_root_doubt, created_at, updated_at, show_hide, with_context,
                       pinned, bookmarked
                FROM DoubtsClearing WHERE {where}
                ORDER BY pinned DESC, created_at DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        )
        rows = cur.fetchall()
        doubts = [
            {
                "doubt_id": r[0], "conversation_id": r[1], "user_email": r[2],
                "message_id": r[3], "doubt_text": r[4],
                "doubt_answer": r[5][:200] if r[5] else "",
                "parent_doubt_id": r[6], "is_root_doubt": bool(r[7]),
                "created_at": r[8], "updated_at": r[9],
                "show_hide": r[10] or "show", "with_context": bool(r[11]),
                "pinned": bool(r[12]), "bookmarked": bool(r[13]),
            }
            for r in rows
        ]
        return {"doubts": doubts, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        log.error(f"Error getting all doubts for user: {e}")
        raise
    finally:
        conn.close()
