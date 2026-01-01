"""
User details persistence helpers.

This module encapsulates SQLite operations against the `UserDetails` table in
`users.db`.

These helpers were originally implemented in `server.py`. We move them here to
reduce the size of `server.py` and to keep database logic separate from route
handlers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlite3 import Error

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


def addUserToUserDetailsTable(
    user_email: str,
    user_preferences: str | None = None,
    user_memory: str | None = None,
    *,
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Add a new user to the UserDetails table or update if it already exists.

    Parameters
    ----------
    user_email:
        User's email address.
    user_preferences:
        JSON string of user preferences (optional).
    user_memory:
        JSON string of what we know about the user (optional).
    users_dir:
        Base directory where `users.db` lives.
    logger:
        Optional logger for diagnostics.
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    if conn is None:
        log.error("Failed to connect to database when adding user details")
        return False

    cur = conn.cursor()
    try:
        cur.execute("SELECT user_email FROM UserDetails WHERE user_email=?", (user_email,))
        exists = cur.fetchone()

        current_time = datetime.now()
        if exists:
            cur.execute(
                """
                UPDATE UserDetails
                SET user_preferences=?, user_memory=?, updated_at=?
                WHERE user_email=?
                """,
                (user_preferences, user_memory, current_time, user_email),
            )
        else:
            cur.execute(
                """
                INSERT INTO UserDetails
                (user_email, user_preferences, user_memory, created_at, updated_at)
                VALUES(?,?,?,?,?)
                """,
                (user_email, user_preferences, user_memory, current_time, current_time),
            )

        conn.commit()
        return True
    except Error as e:
        log.error(f"Database error when adding user details: {e}")
        return False
    finally:
        conn.close()


def getUserFromUserDetailsTable(user_email: str, *, users_dir: str | None = None, logger: logging.Logger | None = None):
    """
    Retrieve user details from the UserDetails table.

    Returns
    -------
    dict | None
        User details or None if not found.
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    if conn is None:
        log.error("Failed to connect to database when retrieving user details")
        return None

    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM UserDetails WHERE user_email=?", (user_email,))
        row = cur.fetchone()
        if row:
            return {
                "user_email": row[0],
                "user_preferences": row[1],
                "user_memory": row[2],
                "created_at": row[3],
                "updated_at": row[4],
            }
        return None
    except Error as e:
        log.error(f"Database error when retrieving user details: {e}")
        return None
    finally:
        conn.close()


def updateUserInfoInUserDetailsTable(
    user_email: str,
    user_preferences: str | None = None,
    user_memory: str | None = None,
    *,
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """
    Update user information in the UserDetails table.

    Only provided fields are updated; other fields preserve current DB values.
    """

    log = logger or logging.getLogger(__name__)
    users_dir_resolved = _resolve_users_dir(users_dir)

    conn = create_connection(_db_path(users_dir=users_dir_resolved))
    if conn is None:
        log.error("Failed to connect to database when updating user details")
        return False

    cur = conn.cursor()
    try:
        cur.execute("SELECT user_preferences, user_memory FROM UserDetails WHERE user_email=?", (user_email,))
        row = cur.fetchone()
        if not row:
            return addUserToUserDetailsTable(
                user_email, user_preferences, user_memory, users_dir=users_dir_resolved, logger=log
            )

        current_preferences, current_memory = row
        update_preferences = user_preferences if user_preferences is not None else current_preferences
        update_memory = user_memory if user_memory is not None else current_memory

        cur.execute(
            """
            UPDATE UserDetails
            SET user_preferences=?, user_memory=?, updated_at=?
            WHERE user_email=?
            """,
            (update_preferences, update_memory, datetime.now(), user_email),
        )
        conn.commit()
        return True
    except Error as e:
        log.error(f"Database error when updating user details: {e}")
        return False
    finally:
        conn.close()


