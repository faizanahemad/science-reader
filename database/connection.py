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
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
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
                                    show_hide text,
                                    with_context boolean DEFAULT 0,
                                    pinned boolean DEFAULT 0,
                                    bookmarked boolean DEFAULT 0,
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

    # Global documents table (index-once, use-everywhere)
    sql_create_global_documents_table = """CREATE TABLE IF NOT EXISTS GlobalDocuments (
                                    doc_id          TEXT NOT NULL,
                                    user_email      TEXT NOT NULL,
                                    display_name    TEXT,
                                    doc_source      TEXT NOT NULL,
                                    doc_storage     TEXT NOT NULL,
                                    title           TEXT,
                                    short_summary   TEXT,
                                    created_at      TEXT NOT NULL,
                                    updated_at      TEXT NOT NULL,
                                    PRIMARY KEY (doc_id, user_email)
                                ); """

    sql_create_global_doc_folders_table = """CREATE TABLE IF NOT EXISTS GlobalDocFolders (
                                        folder_id     TEXT NOT NULL,
                                        user_email    TEXT NOT NULL,
                                        name          TEXT NOT NULL,
                                        parent_id     TEXT,
                                        created_at    TEXT NOT NULL,
                                        updated_at    TEXT NOT NULL,
                                        PRIMARY KEY (folder_id, user_email)
                                    ); """

    sql_create_global_doc_tags_table = """CREATE TABLE IF NOT EXISTS GlobalDocTags (
                                        doc_id        TEXT NOT NULL,
                                        user_email    TEXT NOT NULL,
                                        tag           TEXT NOT NULL,
                                        created_at    TEXT NOT NULL,
                                        PRIMARY KEY (doc_id, user_email, tag),
                                        FOREIGN KEY (doc_id, user_email) REFERENCES GlobalDocuments (doc_id, user_email)
                                    ); """

    # Extension custom scripts table (Tampermonkey-like user scripts).
    sql_create_custom_scripts_table = """CREATE TABLE IF NOT EXISTS CustomScripts (
                                    script_id TEXT PRIMARY KEY,
                                    user_email TEXT NOT NULL,
                                    name TEXT NOT NULL,
                                    description TEXT,
                                    script_type TEXT DEFAULT 'functional',
                                    match_patterns TEXT NOT NULL,
                                    match_type TEXT DEFAULT 'glob',
                                    code TEXT NOT NULL,
                                    actions TEXT,
                                    enabled INTEGER DEFAULT 1,
                                    version INTEGER DEFAULT 1,
                                    conversation_id TEXT,
                                    created_with_llm INTEGER DEFAULT 1,
                                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                                ); """

    # Extension workflows table (multi-step prompt workflows).
    sql_create_extension_workflows_table = """CREATE TABLE IF NOT EXISTS ExtensionWorkflows (
                                    workflow_id TEXT PRIMARY KEY,
                                    user_email TEXT NOT NULL,
                                    name TEXT NOT NULL,
                                    steps_json TEXT NOT NULL,
                                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
        create_table(conn, sql_create_global_documents_table)
        create_table(conn, sql_create_custom_scripts_table)
        create_table(conn, sql_create_extension_workflows_table)
        create_table(conn, sql_create_global_doc_folders_table)
        create_table(conn, sql_create_global_doc_tags_table)
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

    # Add conversation_friendly_id column if it doesn't exist (cross-conversation references)
    try:
        cur.execute(
            "ALTER TABLE UserToConversationId ADD COLUMN conversation_friendly_id text"
        )
        log.info("Added conversation_friendly_id column to UserToConversationId table")
    except Exception:
        pass  # Column already exists

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_UserToConversationId_friendly_id "
        "ON UserToConversationId (user_email, conversation_friendly_id)"
    )

    # Add child_doubt_id column if it doesn't exist (for bidirectional pointers)
    try:
        cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN child_doubt_id text")
        log.info("Added child_doubt_id column to DoubtsClearing table")
    except Exception:
        # Column already exists or other error - this is fine
        pass

    # Add show_hide column if it doesn't exist (per-doubt collapse state for the
    # doubt chat modal; NULL/empty is treated as expanded by the UI).
    try:
        cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN show_hide text")
        log.info("Added show_hide column to DoubtsClearing table")
    except Exception:
        # Column already exists or other error - this is fine
        pass

    # Add with_context column if it doesn't exist (preserves whether the doubt
    # was asked with conversation context so follow-ups restore the same mode).
    try:
        cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN with_context boolean DEFAULT 0")
        log.info("Added with_context column to DoubtsClearing table")
    except Exception:
        pass

    # Add pinned column if it doesn't exist (user can pin important root doubts).
    try:
        cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN pinned boolean DEFAULT 0")
        log.info("Added pinned column to DoubtsClearing table")
    except Exception:
        pass

    # Add bookmarked column if it doesn't exist (user can bookmark specific answers within a thread).
    try:
        cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN bookmarked boolean DEFAULT 0")
        log.info("Added bookmarked column to DoubtsClearing table")
    except Exception:
        pass

    # Add display_attachments column if it doesn't exist (stores JSON list of file attachments
    # so attachment badges re-render on page reload, consistent with normal messages).
    try:
        cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN display_attachments text DEFAULT NULL")
        log.info("Added display_attachments column to DoubtsClearing table")
    except Exception:
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

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_GlobalDocuments_user_email ON GlobalDocuments (user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_GlobalDocuments_created_at ON GlobalDocuments (user_email, created_at)"
    )

    # folder_id column on GlobalDocuments (additive migration, idempotent)
    try:
        cur.execute("ALTER TABLE GlobalDocuments ADD COLUMN folder_id TEXT DEFAULT NULL")
        log.info("Added folder_id column to GlobalDocuments table")
    except Exception:
        pass  # Column already exists

    # index_type column on GlobalDocuments — 'fast' for FastDocIndex, 'full' for DocIndex
    try:
        cur.execute("ALTER TABLE GlobalDocuments ADD COLUMN index_type TEXT DEFAULT 'full'")
        log.info("Added index_type column to GlobalDocuments table")
    except Exception:
        pass  # Column already exists

    # priority column on GlobalDocuments — 1-5 reliability scale, default 3 ("medium")
    try:
        cur.execute("ALTER TABLE GlobalDocuments ADD COLUMN priority INTEGER DEFAULT 3")
        log.info("Added priority column to GlobalDocuments table")
    except Exception:
        pass  # Column already exists

    # date_written column on GlobalDocuments — ISO date string, defaults to NULL (UI uses created_at)
    try:
        cur.execute("ALTER TABLE GlobalDocuments ADD COLUMN date_written TEXT DEFAULT NULL")
        log.info("Added date_written column to GlobalDocuments table")
    except Exception:
        pass  # Column already exists

    # deprecated column on GlobalDocuments — tombstone flag, 0=false 1=true
    try:
        cur.execute("ALTER TABLE GlobalDocuments ADD COLUMN deprecated INTEGER DEFAULT 0")
        log.info("Added deprecated column to GlobalDocuments table")
    except Exception:
        pass  # Column already exists

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_GlobalDocFolders_user ON GlobalDocFolders (user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_GlobalDocFolders_parent ON GlobalDocFolders (user_email, parent_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_GlobalDocuments_folder ON GlobalDocuments (user_email, folder_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_user ON GlobalDocTags (user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_tag ON GlobalDocTags (user_email, tag)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_doc ON GlobalDocTags (doc_id, user_email)"
    )

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_CustomScripts_user ON CustomScripts (user_email)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_CustomScripts_enabled ON CustomScripts (user_email, enabled)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_CustomScripts_type ON CustomScripts (script_type)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ExtensionWorkflows_user ON ExtensionWorkflows (user_email)"
    )

    # PinnedMessages table — star/pin assistant messages within a conversation
    cur.execute("""CREATE TABLE IF NOT EXISTS PinnedMessages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        preview TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(conversation_id, message_id)
    )""")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_PinnedMessages_conv ON PinnedMessages (conversation_id)"
    )

    # ConversationSimilarityCache — cached BM25 tokens + embeddings for auto-archival
    cur.execute("""CREATE TABLE IF NOT EXISTS ConversationSimilarityCache (
        conversation_id TEXT PRIMARY KEY,
        title_summary_hash TEXT,
        bm25_tokens TEXT,
        embedding BLOB,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # remember_tokens — replaces remember_tokens.json (concurrent auth access)
    cur.execute("""CREATE TABLE IF NOT EXISTS RememberTokens (
        token TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rt_email ON RememberTokens (email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rt_expires ON RememberTokens (expires_at)")

    # pinned_claims — replaces in-memory dict (persists across restarts)
    cur.execute("""CREATE TABLE IF NOT EXISTS PinnedClaims (
        conversation_id TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        user_email TEXT NOT NULL,
        pinned_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (conversation_id, claim_id)
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pc_conv ON PinnedClaims (conversation_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pc_user ON PinnedClaims (user_email)")

    # Fix redundant indexes (drop safely — IF EXISTS handles already-dropped)
    for idx in ("idx_User_email_doc_conversation", "idx_UserDetails_email"):
        cur.execute(f"DROP INDEX IF EXISTS {idx}")

    # Add missing index: lookup conversation by ID (used by getConversationById)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_utci_conversation_id ON UserToConversationId (conversation_id)"
    )
    # Unique constraint on friendly_id per user
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_utci_friendly_id "
        "ON UserToConversationId (user_email, conversation_friendly_id) "
        "WHERE conversation_friendly_id IS NOT NULL"
    )

    conn.commit()
    conn.close()
