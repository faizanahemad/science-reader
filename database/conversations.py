"""
Conversation <-> user persistence helpers.

This module encapsulates SQLite operations against tables:
- UserToConversationId
- ConversationIdToWorkspaceId
- (cleanup touches) SectionHiddenDetails, DoubtsClearing

These helpers were originally implemented in `server.py`. We move them here to
reduce the size of `server.py` and to keep database logic separate from route
handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

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
        raise RuntimeError(
            "users_dir not configured. Pass users_dir=... or call configure_users_dir(users_dir)."
        )
    return _default_users_dir


def _db_path(*, users_dir: str) -> str:
    return f"{users_dir}/users.db"


def addConversation(
    user_email: str,
    conversation_id: str,
    workspace_id: Optional[str] = None,
    domain: Optional[str] = None,
    *,
    users_dir: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """
    Add a conversation for a user and ensure a conversation->workspace mapping row exists.

    This inserts into:
    - UserToConversationId
    - ConversationIdToWorkspaceId
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    default_workspace_id = f"default_{user_email}_{domain}"
    now = datetime.now()
    workspace_id_to_use = (
        workspace_id if workspace_id is not None else default_workspace_id
    )

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    if conn is None:
        log.error("Failed to connect to database when adding conversation")
        return False

    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO UserToConversationId
            (user_email, conversation_id, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_email, conversation_id, now, now),
        )
        cur.execute(
            """
            INSERT OR IGNORE INTO ConversationIdToWorkspaceId
            (conversation_id, user_email, workspace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, user_email, workspace_id_to_use, now, now),
        )
        conn.commit()
        return True
    except Exception as e:
        log.error(f"Error adding conversation for user {user_email}: {e}")
        return False
    finally:
        conn.close()


def checkConversationExists(
    user_email: str, conversation_id: str, *, users_dir: Optional[str] = None
) -> bool:
    """Return True if the user has access to the given conversation id."""

    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM UserToConversationId WHERE user_email=? AND conversation_id=?",
        (user_email, conversation_id),
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def getCoversationsForUser(
    user_email: str, domain: str, *, users_dir: Optional[str] = None
):
    """
    Fetch all conversations for a user, along with associated workspace metadata.
    """

    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            uc.user_email,
            uc.conversation_id,
            uc.created_at,
            uc.updated_at,
            cw.workspace_id,
            wm.workspace_name,
            wm.workspace_color
        FROM UserToConversationId uc
        LEFT JOIN ConversationIdToWorkspaceId cw
            ON uc.conversation_id = cw.conversation_id AND uc.user_email = cw.user_email
        LEFT JOIN WorkspaceMetadata wm
            ON cw.workspace_id = wm.workspace_id
        WHERE uc.user_email=?
        """,
        (user_email,),
    )
    rows = cur.fetchall()

    conversation_ids_to_update = [row[1] for row in rows if row[4] is None]
    if conversation_ids_to_update:
        placeholders = ",".join(["?"] * len(conversation_ids_to_update))
        cur.execute(
            f"UPDATE ConversationIdToWorkspaceId SET workspace_id=? WHERE conversation_id IN ({placeholders})",
            [f"default_{user_email}_{domain}"] + conversation_ids_to_update,
        )

        # Ensure WorkspaceMetadata exists for default workspace.
        cur.execute(
            "SELECT 1 FROM WorkspaceMetadata WHERE workspace_id=? AND domain=?",
            (f"default_{user_email}_{domain}", domain),
        )
        if not cur.fetchone():
            now = datetime.now()
            cur.execute(
                "INSERT INTO WorkspaceMetadata (workspace_id, workspace_name, workspace_color, domain, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"default_{user_email}_{domain}",
                    f"default_{user_email}_{domain}",
                    None,
                    domain,
                    now,
                    now,
                ),
            )

        conn.commit()

        updated_rows = []
        for row in rows:
            row = list(row)
            if row[4] is None:
                row[4] = f"default_{user_email}_{domain}"
                row[5] = f"default_{user_email}_{domain}"
                row[6] = None
            updated_rows.append(tuple(row))
        rows = updated_rows

    conn.close()
    return rows


def deleteConversationForUser(
    user_email: str, conversation_id: str, *, users_dir: Optional[str] = None
) -> None:
    """Delete conversation mapping rows for a user."""

    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM UserToConversationId WHERE user_email=? AND conversation_id=?",
            (user_email, conversation_id),
        )
        cur.execute(
            "DELETE FROM ConversationIdToWorkspaceId WHERE user_email=? AND conversation_id=?",
            (user_email, conversation_id),
        )
        conn.commit()
    finally:
        conn.close()


def cleanup_deleted_conversations(
    conversation_ids: list[str],
    *,
    users_dir: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Remove DB rows for deleted conversations across supporting tables."""

    if not conversation_ids:
        return

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    if conn is None:
        log.error("Error! cannot create the database connection for cleanup.")
        return

    try:
        cur = conn.cursor()
        placeholders = ",".join(["?"] * len(conversation_ids))
        cur.execute(
            f"DELETE FROM SectionHiddenDetails WHERE conversation_id IN ({placeholders})",
            conversation_ids,
        )
        cur.execute(
            f"DELETE FROM DoubtsClearing WHERE conversation_id IN ({placeholders})",
            conversation_ids,
        )
        cur.execute(
            f"DELETE FROM ConversationIdToWorkspaceId WHERE conversation_id IN ({placeholders})",
            conversation_ids,
        )
        cur.execute(
            f"DELETE FROM UserToConversationId WHERE conversation_id IN ({placeholders})",
            conversation_ids,
        )
        conn.commit()
        log.info(
            f"Cleaned up database entries for {len(conversation_ids)} deleted conversations"
        )
    except Exception as e:
        log.error(f"Error cleaning up deleted conversations: {e}")
        conn.rollback()
    finally:
        conn.close()


def getAllCoversations(*, users_dir: Optional[str] = None):
    """Return all rows from UserToConversationId (legacy helper)."""

    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    cur = conn.cursor()
    cur.execute("SELECT * FROM UserToConversationId")
    rows = cur.fetchall()
    conn.close()
    return rows


def getConversationById(conversation_id: str, *, users_dir: Optional[str] = None):
    """Return UserToConversationId rows for a given conversation id."""

    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM UserToConversationId WHERE conversation_id=?", (conversation_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def removeUserFromConversation(
    user_email: str, conversation_id: str, *, users_dir: Optional[str] = None
) -> None:
    """Remove a user->conversation mapping row."""

    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM UserToConversationId WHERE user_email=? AND conversation_id=?",
        (user_email, conversation_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Cross-conversation reference helpers (conversation_friendly_id)
# ---------------------------------------------------------------------------


def setConversationFriendlyId(
    *,
    users_dir: str,
    user_email: str,
    conversation_id: str,
    conversation_friendly_id: str,
) -> None:
    """
    Set the conversation_friendly_id for a conversation in the DB mapping.

    Updates the UserToConversationId row for the given user+conversation pair.
    Used when a friendly ID is first generated (on first persist) or during
    backfill of older conversations.

    Parameters
    ----------
    users_dir : str
        Path to users directory for DB access.
    user_email : str
        The user's email address.
    conversation_id : str
        The conversation's full opaque ID.
    conversation_friendly_id : str
        The short human-readable identifier (e.g. "react_optimization_b4f2").
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "UPDATE UserToConversationId SET conversation_friendly_id=? "
        "WHERE user_email=? AND conversation_id=?",
        (conversation_friendly_id, user_email, conversation_id),
    )
    conn.commit()
    conn.close()


def getConversationIdByFriendlyId(
    *, users_dir: str, user_email: str, conversation_friendly_id: str
) -> Optional[str]:
    """
    Look up conversation_id from a conversation_friendly_id for a user.

    Used during cross-conversation reference resolution to find the target
    conversation from a short friendly identifier.

    Parameters
    ----------
    users_dir : str
        Path to users directory for DB access.
    user_email : str
        The user's email address (ownership check).
    conversation_friendly_id : str
        The short identifier to look up.

    Returns
    -------
    Optional[str]
        The conversation_id if found, else None.
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "SELECT conversation_id FROM UserToConversationId "
        "WHERE user_email=? AND conversation_friendly_id=?",
        (user_email, conversation_friendly_id),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def conversationFriendlyIdExists(
    *, users_dir: str, user_email: str, conversation_friendly_id: str
) -> bool:
    """
    Check if a conversation_friendly_id already exists for this user.

    Used during friendly ID generation to detect collisions before storing.

    Parameters
    ----------
    users_dir : str
        Path to users directory for DB access.
    user_email : str
        The user's email address.
    conversation_friendly_id : str
        The candidate friendly ID to check.

    Returns
    -------
    bool
        True if the friendly ID is already taken by another conversation.
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM UserToConversationId "
        "WHERE user_email=? AND conversation_friendly_id=?",
        (user_email, conversation_friendly_id),
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists
