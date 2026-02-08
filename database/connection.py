"""
Database connection + schema helpers.

This module will own SQLite connection creation and schema initialization that
currently lives in `server.py` (e.g. create_connection/create_tables).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from sqlite3 import Error
from typing import Optional


def create_connection(db_file: str) -> sqlite3.Connection:
    """
    Create a database connection to a SQLite database.

    Parameters
    ----------
    db_file:
        Path to the SQLite database file.

    Returns
    -------
    sqlite3.Connection
        Open connection (caller is responsible for closing).
    """

    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except Error as e:
        raise RuntimeError(f"Failed to connect to sqlite DB at {db_file}: {e}") from e
    return conn


def create_table(conn: sqlite3.Connection, create_table_sql: str) -> None:
    """
    Create a table from the provided CREATE TABLE statement.
    """

    try:
        c = conn.cursor()
        c.execute(create_table_sql)
    except Error as e:
        raise RuntimeError(f"Failed to create table: {e}") from e


def delete_table(conn: sqlite3.Connection, table_name: str) -> None:
    """
    Delete a table from the database if it exists.
    """

    try:
        c = conn.cursor()
        c.execute(f"DROP TABLE IF EXISTS {table_name}")
    except Error as e:
        raise RuntimeError(f"Failed to delete table {table_name}: {e}") from e


def create_tables(*, users_dir: str, logger: Optional[logging.Logger] = None) -> None:
    """
    Create/upgrade core server tables and indexes.

    Parameters
    ----------
    users_dir:
        Directory containing `users.db`.
    logger:
        Optional logger for upgrade notes.
    """

    log = logger or logging.getLogger(__name__)
    database = os.path.join(users_dir, "users.db")

    sql_create_user_to_conversation_id_table = """CREATE TABLE IF NOT EXISTS UserToConversationId (
                                    user_email text,
                                    conversation_id text,
                                    created_at text,
                                    updated_at text
                                ); """

    sql_create_user_details_table = """CREATE TABLE IF NOT EXISTS UserDetails (
                                    user_email text PRIMARY KEY,
                                    user_preferences text,
                                    user_memory text,
                                    created_at text,
                                    updated_at text
                                ); """

    # ConversationId to WorkspaceId
    sql_create_conversation_id_to_workspace_id_table = """CREATE TABLE IF NOT EXISTS ConversationIdToWorkspaceId (
                                    conversation_id text PRIMARY KEY,
                                    user_email text,
                                    workspace_id text,
                                    created_at text,
                                    updated_at text
                                ); """

    # workspace metadata table
    sql_create_workspace_metadata_table = """CREATE TABLE IF NOT EXISTS WorkspaceMetadata (
                                    workspace_id text PRIMARY KEY,
                                    workspace_name text,
                                    workspace_color text,
                                    domain text,
                                    expanded boolean,
                                    parent_workspace_id text,
                                    created_at text,
                                    updated_at text
                                ); """

    # doubts clearing table
    sql_create_doubts_clearing_table = """CREATE TABLE IF NOT EXISTS DoubtsClearing (
                                    doubt_id text PRIMARY KEY,
                                    conversation_id text,
                                    user_email text,
                                    message_id text,
                                    doubt_text text,
                                    doubt_answer text,
                                    parent_doubt_id text,
                                    is_root_doubt boolean DEFAULT 1,
                                    created_at text,
                                    updated_at text,
                                    FOREIGN KEY (parent_doubt_id) REFERENCES DoubtsClearing (doubt_id)
                                ); """

    # section hidden details table
    sql_create_section_hidden_details_table = """CREATE TABLE IF NOT EXISTS SectionHiddenDetails (
                                    conversation_id text,
                                    section_id text,
                                    hidden boolean DEFAULT 0,
                                    created_at text,
                                    updated_at text,
                                    PRIMARY KEY (conversation_id, section_id)
                                ); """

    conn = create_connection(database)

    # create tables
    if conn is not None:
        create_table(conn, sql_create_user_to_conversation_id_table)
        create_table(conn, sql_create_user_details_table)
        create_table(conn, sql_create_conversation_id_to_workspace_id_table)
        create_table(conn, sql_create_workspace_metadata_table)
        create_table(conn, sql_create_doubts_clearing_table)
        create_table(conn, sql_create_section_hidden_details_table)
    else:
        raise RuntimeError("Error! cannot create the database connection.")

    cur = conn.cursor()
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_UserToConversationId_email_doc ON UserToConversationId (user_email, conversation_id)"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ConversationIdToWorkspaceId_conversation_id ON ConversationIdToWorkspaceId (conversation_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ConversationIdToWorkspaceId_workspace_id ON ConversationIdToWorkspaceId (workspace_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ConversationIdToWorkspaceId_user_email ON ConversationIdToWorkspaceId (user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_WorkspaceMetadata_workspace_id ON WorkspaceMetadata (workspace_id)"
    )
    # Add parent_workspace_id column if it doesn't exist (hierarchical workspaces)
    try:
        cur.execute("ALTER TABLE WorkspaceMetadata ADD COLUMN parent_workspace_id text")
        log.info("Added parent_workspace_id column to WorkspaceMetadata table")
    except Exception:
        # Column already exists or other error - this is fine
        pass

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_WorkspaceMetadata_parent_workspace_id ON WorkspaceMetadata (parent_workspace_id)"
    )

    # Add child_doubt_id column if it doesn't exist (for bidirectional pointers)
    try:
        cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN child_doubt_id text")
        log.info("Added child_doubt_id column to DoubtsClearing table")
    except Exception:
        # Column already exists or other error - this is fine
        pass

    # create indexes for DoubtsClearing table
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_conversation_id ON DoubtsClearing (conversation_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_user_email ON DoubtsClearing (user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_message_id ON DoubtsClearing (message_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_conv_msg ON DoubtsClearing (conversation_id, message_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_parent_doubt_id ON DoubtsClearing (parent_doubt_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_child_doubt_id ON DoubtsClearing (child_doubt_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_DoubtsClearing_is_root ON DoubtsClearing (is_root_doubt)"
    )

    # create indexes for SectionHiddenDetails table
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_SectionHiddenDetails_conversation_id ON SectionHiddenDetails (conversation_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_SectionHiddenDetails_section_id ON SectionHiddenDetails (section_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_SectionHiddenDetails_hidden ON SectionHiddenDetails (hidden)"
    )

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_User_email_doc_conversation ON UserToConversationId (user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_UserDetails_email ON UserDetails (user_email)"
    )
    conn.commit()
    conn.close()
