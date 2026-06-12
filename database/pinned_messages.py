"""
Pinned messages persistence helpers.

CRUD for the PinnedMessages table — allows starring/pinning assistant messages
within a conversation.
"""

from __future__ import annotations

import logging
from typing import Optional

from database.connection import create_connection


_default_users_dir: Optional[str] = None


def configure_users_dir(users_dir: str) -> None:
    global _default_users_dir
    _default_users_dir = users_dir


def _resolve_users_dir(users_dir: Optional[str]) -> str:
    if users_dir is not None:
        return users_dir
    if _default_users_dir is None:
        raise RuntimeError("users_dir not configured.")
    return _default_users_dir


def _db_path(*, users_dir: str) -> str:
    return f"{users_dir}/users.db"


def pin_message(
    *,
    conversation_id: str,
    message_id: str,
    user_email: str,
    preview: str = "",
    users_dir: str | None = None,
) -> bool:
    """Pin a message. Returns True if newly pinned, False if already pinned."""
    ud = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=ud))
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT OR IGNORE INTO PinnedMessages (conversation_id, message_id, user_email, preview) VALUES (?, ?, ?, ?)",
            (conversation_id, message_id, user_email, preview[:200] if preview else ""),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def unpin_message(
    *,
    conversation_id: str,
    message_id: str,
    users_dir: str | None = None,
) -> bool:
    """Unpin a message. Returns True if removed."""
    ud = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=ud))
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM PinnedMessages WHERE conversation_id = ? AND message_id = ?",
            (conversation_id, message_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_pinned_messages(
    *,
    conversation_id: str,
    users_dir: str | None = None,
) -> list[dict]:
    """Get all pinned messages for a conversation."""
    ud = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=ud))
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT message_id, preview, created_at FROM PinnedMessages WHERE conversation_id = ? ORDER BY created_at DESC",
            (conversation_id,),
        )
        return [{"message_id": r[0], "preview": r[1], "created_at": r[2]} for r in cur.fetchall()]
    finally:
        conn.close()


def update_preview(
    *,
    conversation_id: str,
    message_id: str,
    preview: str,
    users_dir: str | None = None,
) -> None:
    """Update preview text (e.g. after message edit/regen)."""
    ud = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=ud))
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE PinnedMessages SET preview = ? WHERE conversation_id = ? AND message_id = ?",
            (preview[:200] if preview else "", conversation_id, message_id),
        )
        conn.commit()
    finally:
        conn.close()
