"""
Workspace persistence helpers.

This module contains the SQLite-backed functions for creatings
- creating/listing/updating/deleting workspaces
- mapping conversations -> workspaces

These functions were originally implemented in `server.py`. We move them here
so endpoint modules can depend on a small, well-defined DB layer without
importing the monolithic server module (avoids circular imports).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from database.connection import create_connection


def _db_path(*, users_dir: str) -> str:
    """Return the absolute path to the per-user SQLite database."""

    return f"{users_dir}/users.db"


def load_workspaces_for_user(*, users_dir: str, user_email: str, domain: str) -> list[dict[str, Any]]:
    """
    Retrieve all unique workspaces for a user (including metadata) for a given domain.

    Ensures a default workspace exists and is included in results.

    Parameters
    ----------
    users_dir:
        Directory containing `users.db`.
    user_email:
        User email identifier.
    domain:
        Domain to filter by.

    Returns
    -------
    list[dict[str, Any]]
        Each item includes `workspace_id`, `workspace_name`, `workspace_color`,
        `domain`, and `expanded` when available.
    """

    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()

    cur.execute(
        """
        SELECT DISTINCT c.workspace_id,
                        wm.workspace_name,
                        wm.workspace_color,
                        wm.domain,
                        wm.expanded
        FROM ConversationIdToWorkspaceId c
        LEFT JOIN WorkspaceMetadata wm ON c.workspace_id = wm.workspace_id
        WHERE c.user_email = ? AND c.workspace_id IS NOT NULL AND wm.domain = ?
        """,
        (user_email, domain),
    )
    rows = cur.fetchall()

    workspaces = [
        {
            "workspace_id": row[0],
            "workspace_name": row[1],
            "workspace_color": row[2],
            "domain": row[3],
            "expanded": row[4],
        }
        for row in rows
    ]

    default_workspace_id = f"default_{user_email}_{domain}"
    default_workspace_name = f"default_{user_email}_{domain}"

    has_default = any(ws["workspace_id"] == default_workspace_id for ws in workspaces)
    if not has_default:
        now = datetime.now()
        cur.execute(
            """
            INSERT OR IGNORE INTO WorkspaceMetadata
            (workspace_id, workspace_name, workspace_color, domain, expanded, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (default_workspace_id, default_workspace_name, None, domain, True, now, now),
        )

        # The mapping row for "workspace itself" (conversation_id is None)
        cur.execute(
            """
            INSERT OR IGNORE INTO ConversationIdToWorkspaceId
            (conversation_id, user_email, workspace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (None, user_email, default_workspace_id, now, now),
        )
        conn.commit()
        workspaces.append(
            {
                "workspace_id": default_workspace_id,
                "workspace_name": default_workspace_name,
                "workspace_color": None,
                "domain": domain,
                "expanded": True,
            }
        )

    conn.close()
    return workspaces


def addConversationToWorkspace(*, users_dir: str, user_email: str, conversation_id: str, workspace_id: str) -> None:
    """
    Create/ensure a conversation -> workspace mapping row.
    """

    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO ConversationIdToWorkspaceId
        (conversation_id, user_email, workspace_id, created_at, updated_at)
        VALUES(?,?,?,?,?)
        """,
        (conversation_id, user_email, workspace_id, datetime.now(), datetime.now()),
    )
    conn.commit()
    conn.close()


def moveConversationToWorkspace(*, users_dir: str, user_email: str, conversation_id: str, workspace_id: str) -> None:
    """Update an existing conversation -> workspace mapping."""

    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "UPDATE ConversationIdToWorkspaceId SET workspace_id=?, updated_at=? WHERE user_email=? AND conversation_id=?",
        (workspace_id, datetime.now(), user_email, conversation_id),
    )
    conn.commit()
    conn.close()


def removeConversationFromWorkspace(*, users_dir: str, user_email: str, conversation_id: str) -> None:
    """Delete a conversation -> workspace mapping row."""

    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM ConversationIdToWorkspaceId WHERE user_email=? AND conversation_id=?",
        (user_email, conversation_id),
    )
    conn.commit()
    conn.close()


def getWorkspaceForConversation(*, users_dir: str, conversation_id: str) -> Optional[dict[str, Any]]:
    """
    Retrieve workspace metadata associated with a conversation_id.

    Returns None if there is no mapping or no workspace_id.
    """

    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT workspace_id, user_email FROM ConversationIdToWorkspaceId WHERE conversation_id=?",
            (conversation_id,),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return None

        workspace_id, user_email = row
        cur.execute(
            """
            SELECT workspace_id, workspace_name, workspace_color, domain, expanded, created_at, updated_at
            FROM WorkspaceMetadata
            WHERE workspace_id=?
            """,
            (workspace_id,),
        )
        meta_row = cur.fetchone()
        if not meta_row:
            return {"workspace_id": workspace_id, "user_email": user_email}

        return {
            "workspace_id": meta_row[0],
            "workspace_name": meta_row[1],
            "workspace_color": meta_row[2],
            "domain": meta_row[3],
            "expanded": meta_row[4],
            "created_at": meta_row[5],
            "updated_at": meta_row[6],
            "user_email": user_email,
        }
    finally:
        conn.close()


def getConversationsForWorkspace(*, users_dir: str, workspace_id: str, user_email: str):
    """Return mapping rows for a given workspace + user."""

    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=?",
        (workspace_id, user_email),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def createWorkspace(
    *,
    users_dir: str,
    user_email: str,
    workspace_id: str,
    domain: str,
    workspace_name: str,
    workspace_color: Optional[str],
) -> None:
    """
    Create a new workspace for a user.

    Inserts a workspace record into:
    - WorkspaceMetadata (metadata)
    - ConversationIdToWorkspaceId (user-workspace mapping row where conversation_id is None)
    """

    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        now = datetime.now()

        cur.execute(
            """
            INSERT OR IGNORE INTO WorkspaceMetadata
            (workspace_id, workspace_name, workspace_color, domain, expanded, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (workspace_id, workspace_name, workspace_color, domain, True, now, now),
        )

        cur.execute(
            """
            INSERT INTO ConversationIdToWorkspaceId
            (conversation_id, user_email, workspace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (None, user_email, workspace_id, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def collapseWorkspaces(*, users_dir: str, workspace_ids: list[str]) -> None:
    """
    Collapse (set expanded=0) for all workspaces whose IDs are in the provided list.
    """

    if not workspace_ids:
        return

    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        placeholders = ",".join(["?"] * len(workspace_ids))
        sql = f"UPDATE WorkspaceMetadata SET expanded=0 WHERE workspace_id IN ({placeholders})"
        cur.execute(sql, tuple(workspace_ids))
        conn.commit()
    finally:
        conn.close()


def updateWorkspace(
    *,
    users_dir: str,
    user_email: str,
    workspace_id: str,
    workspace_name: Optional[str] = None,
    workspace_color: Optional[str] = None,
    expanded: Optional[bool] = None,
) -> None:
    """
    Update workspace metadata fields.

    Raises
    ------
    ValueError
        If no fields were provided.
    """

    if workspace_name is None and workspace_color is None and expanded is None:
        raise ValueError("At least one of workspace_name or workspace_color or expanded must be provided.")

    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        fields: list[str] = []
        values: list[Any] = []
        now = datetime.now()

        if workspace_name is not None:
            fields.append("workspace_name=?")
            values.append(workspace_name)
        if workspace_color is not None:
            fields.append("workspace_color=?")
            values.append(workspace_color)
        if expanded is not None:
            fields.append("expanded=?")
            values.append(expanded)

        fields.append("updated_at=?")
        values.append(now)
        values.append(workspace_id)

        sql = f"UPDATE WorkspaceMetadata SET {', '.join(fields)} WHERE workspace_id=?"
        cur.execute(sql, values)
        conn.commit()
    finally:
        conn.close()


def deleteWorkspace(*, users_dir: str, workspace_id: str, user_email: str, domain: str) -> None:
    """
    Delete a workspace for a user.

    Conversations in the workspace are moved to the user's default workspace before deletion.
    """

    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT conversation_id FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=?",
            (workspace_id, user_email),
        )
        conversations = cur.fetchall()

        default_workspace_id = f"default_{user_email}_{domain}"
        default_workspace_name = f"default_{user_email}_{domain}"

        # Ensure default workspace metadata exists.
        now = datetime.now()
        cur.execute(
            """
            INSERT OR IGNORE INTO WorkspaceMetadata
            (workspace_id, workspace_name, workspace_color, domain, expanded, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (default_workspace_id, default_workspace_name, None, domain, True, now, now),
        )

        # Ensure default workspace mapping row exists.
        cur.execute(
            """
            INSERT OR IGNORE INTO ConversationIdToWorkspaceId
            (conversation_id, user_email, workspace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (None, user_email, default_workspace_id, now, now),
        )

        # Move conversations to default workspace.
        for (conversation_id,) in conversations:
            if conversation_id is None:
                continue
            cur.execute(
                """
                UPDATE ConversationIdToWorkspaceId
                SET workspace_id=?, updated_at=?
                WHERE conversation_id=? AND user_email=?
                """,
                (default_workspace_id, datetime.now(), conversation_id, user_email),
            )

        # Delete the workspace mapping rows for this user.
        cur.execute(
            "DELETE FROM ConversationIdToWorkspaceId WHERE workspace_id=? AND user_email=?",
            (workspace_id, user_email),
        )

        # Delete workspace metadata if no mapping rows remain for this workspace_id.
        cur.execute("SELECT 1 FROM ConversationIdToWorkspaceId WHERE workspace_id=? LIMIT 1", (workspace_id,))
        if not cur.fetchone():
            cur.execute("DELETE FROM WorkspaceMetadata WHERE workspace_id=?", (workspace_id,))

        conn.commit()
    finally:
        conn.close()


