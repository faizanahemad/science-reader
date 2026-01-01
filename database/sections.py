"""
Section hidden-details persistence helpers.

This module encapsulates SQLite operations against the `SectionHiddenDetails`
table in `users.db`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from database.connection import create_connection


_default_users_dir: Optional[str] = None


def configure_users_dir(users_dir: str) -> None:
    """
    Configure a default `users_dir` for convenience during incremental refactors.

    Prefer passing `users_dir=...` explicitly; this default exists to keep legacy
    call sites working while we migrate.
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


def get_section_hidden_details(
    *,
    conversation_id: str,
    section_ids: list[str],
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, dict]:
    """
    Retrieve hidden details for multiple sections in a conversation.

    Returns
    -------
    dict[str, dict]
        Mapping `section_id -> {hidden, created_at, updated_at}`.
    """

    log = logger or logging.getLogger(__name__)
    if not section_ids:
        return {}

    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        placeholders = ",".join("?" * len(section_ids))
        query = f"""
            SELECT section_id, hidden, created_at, updated_at
            FROM SectionHiddenDetails
            WHERE conversation_id = ? AND section_id IN ({placeholders})
        """
        params = [conversation_id] + section_ids
        cur.execute(query, params)
        rows = cur.fetchall()

        section_details: dict[str, dict] = {}
        for row in rows:
            section_details[row[0]] = {"hidden": bool(row[1]), "created_at": row[2], "updated_at": row[3]}

        for section_id in section_ids:
            if section_id not in section_details:
                section_details[section_id] = {"hidden": False, "created_at": None, "updated_at": None}

        log.info(f"Retrieved hidden details for {len(section_ids)} sections in conversation {conversation_id}")
        return section_details
    except Exception as e:
        log.error(f"Error getting section hidden details: {e}")
        raise
    finally:
        conn.close()


def bulk_update_section_hidden_detail(
    *,
    conversation_id: str,
    section_updates: dict[str, bool],
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """
    Bulk update or create section hidden details for multiple sections.

    Parameters
    ----------
    section_updates:
        Mapping `section_id -> hidden` boolean.
    """

    log = logger or logging.getLogger(__name__)
    if not section_updates:
        return

    users_dir_resolved = _resolve_users_dir(users_dir)
    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    try:
        cur = conn.cursor()
        now = datetime.now().isoformat()

        for section_id, hidden_state in section_updates.items():
            cur.execute(
                """
                INSERT OR REPLACE INTO SectionHiddenDetails
                (conversation_id, section_id, hidden, created_at, updated_at)
                VALUES (
                    ?,  -- conversation_id
                    ?,  -- section_id
                    ?,  -- hidden
                    COALESCE((SELECT created_at FROM SectionHiddenDetails
                              WHERE conversation_id = ? AND section_id = ?), ?),  -- preserve created_at if exists
                    ?   -- updated_at
                )
                """,
                (conversation_id, section_id, hidden_state, conversation_id, section_id, now, now),
            )

        conn.commit()
        log.info(f"Bulk updated {len(section_updates)} section hidden details for conversation {conversation_id}")
    except Exception as e:
        log.error(f"Error in bulk updating section hidden details: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


