"""
Cross-conversation search index (FTS5) database helpers.

This module manages a **separate** SQLite database ``search_index.db`` that
lives alongside ``users.db`` in the users directory.  Unlike the core tables
which live in ``users.db``, the search index is fully rebuildable from source
conversation files and can be safely deleted + re-created.

Three tables:

* ``ConversationSearchMeta`` (FTS5) — one row per conversation (title, summary,
  memory_pad, concatenated message TLDRs). This is the **fast path**.
* ``ConversationSearchMessages`` (FTS5) — one row per ~10-message chunk
  (headers + bold text + TLDRs). This is the **deep path**.
* ``ConversationSearchState`` (regular) — filterable metadata (workspace,
  domain, flag, dates, message counts, friendly_id).

Design decisions:
  - Direct FTS5 tables (no content table, no triggers) because source data is
    dill-serialized files on disk, not in SQLite.
  - WAL mode for concurrent reads + single writer.
  - ``porter unicode61`` tokenizer for stemming and Unicode support.
  - Column weights: title (3.0) > summary (2.0) > message_tldrs (1.5)
    > memory_pad (1.0) > headers_and_bold (1.0).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _search_db_path(users_dir: str) -> str:
    """Return the path to ``search_index.db`` inside *users_dir*."""
    return os.path.join(users_dir, "search_index.db")


def get_search_connection(users_dir: str) -> sqlite3.Connection:
    """Open a connection to ``search_index.db`` with WAL mode and REGEXP.

    Every call returns a **new** short-lived connection (the same
    pattern used by ``database/conversations.py``).  Callers must
    ``conn.close()`` in a ``finally`` block.
    """
    db_path = _search_db_path(users_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # dict-like rows

    # Enable WAL for concurrent read/write
    conn.execute("PRAGMA journal_mode=WAL")

    # Register a REGEXP function for regex search mode
    def _regexp(pattern: str, value: str) -> bool:
        if value is None:
            return False
        try:
            return bool(re.search(pattern, value, re.IGNORECASE))
        except re.error:
            return False

    conn.create_function("REGEXP", 2, _regexp)
    return conn


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

_SQL_CREATE_META_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS ConversationSearchMeta USING fts5(
    conversation_id UNINDEXED,
    user_email UNINDEXED,
    title,
    summary,
    memory_pad,
    message_tldrs,
    tokenize='porter unicode61'
);
"""

_SQL_CREATE_MESSAGES_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS ConversationSearchMessages USING fts5(
    conversation_id UNINDEXED,
    user_email UNINDEXED,
    chunk_index UNINDEXED,
    message_ids UNINDEXED,
    headers_and_bold,
    tldrs,
    tokenize='porter unicode61'
);
"""

_SQL_CREATE_STATE = """
CREATE TABLE IF NOT EXISTS ConversationSearchState (
    conversation_id TEXT PRIMARY KEY,
    user_email      TEXT NOT NULL,
    title           TEXT DEFAULT '',
    last_updated    TEXT DEFAULT '',
    domain          TEXT DEFAULT '',
    workspace_id    TEXT DEFAULT '',
    flag            TEXT DEFAULT 'none',
    message_count   INTEGER DEFAULT 0,
    indexed_message_count INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT '',
    updated_at      TEXT DEFAULT '',
    friendly_id     TEXT DEFAULT ''
);
"""

_SQL_STATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_css_user_email ON ConversationSearchState(user_email);",
    "CREATE INDEX IF NOT EXISTS idx_css_domain ON ConversationSearchState(domain);",
    "CREATE INDEX IF NOT EXISTS idx_css_workspace ON ConversationSearchState(workspace_id);",
    "CREATE INDEX IF NOT EXISTS idx_css_last_updated ON ConversationSearchState(last_updated);",
    "CREATE INDEX IF NOT EXISTS idx_css_flag ON ConversationSearchState(flag);",
]


def create_search_tables(
    *,
    users_dir: str,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Create (or verify) all tables/indexes in ``search_index.db``.

    Safe to call on every server startup — all DDL uses
    ``IF NOT EXISTS``.
    """
    log = logger or logging.getLogger(__name__)
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute(_SQL_CREATE_META_FTS)
        cur.execute(_SQL_CREATE_MESSAGES_FTS)
        cur.execute(_SQL_CREATE_STATE)
        for idx_sql in _SQL_STATE_INDEXES:
            cur.execute(idx_sql)
        conn.commit()
        log.info(
            "search_index.db: tables and indexes verified at %s",
            _search_db_path(users_dir),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Upsert helpers (Meta, Messages, State)
# ---------------------------------------------------------------------------


def upsert_conversation_meta(
    users_dir: str,
    conversation_id: str,
    user_email: str,
    title: str,
    summary: str,
    memory_pad: str,
    message_tldrs: str,
) -> None:
    """Insert or replace the FTS5 meta row for a conversation.

    FTS5 direct tables do not support UPDATE — we DELETE then INSERT.
    """
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM ConversationSearchMeta WHERE conversation_id = ?",
            (conversation_id,),
        )
        cur.execute(
            """INSERT INTO ConversationSearchMeta
               (conversation_id, user_email, title, summary, memory_pad, message_tldrs)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (conversation_id, user_email, title, summary, memory_pad, message_tldrs),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_conversation_messages_chunk(
    users_dir: str,
    conversation_id: str,
    user_email: str,
    chunk_index: int,
    message_ids_json: str,
    headers_and_bold: str,
    tldrs: str,
) -> None:
    """Insert or replace one message chunk row in the FTS5 messages table.

    Each chunk covers ~10 messages.  ``message_ids_json`` is a JSON array
    of message identifiers for result attribution.
    """
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        # Delete existing chunk for this conversation + chunk_index
        cur.execute(
            """DELETE FROM ConversationSearchMessages
               WHERE conversation_id = ? AND chunk_index = ?""",
            (conversation_id, str(chunk_index)),
        )
        cur.execute(
            """INSERT INTO ConversationSearchMessages
               (conversation_id, user_email, chunk_index, message_ids, headers_and_bold, tldrs)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                conversation_id,
                user_email,
                str(chunk_index),
                message_ids_json,
                headers_and_bold,
                tldrs,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_conversation_message_chunks(
    users_dir: str,
    conversation_id: str,
) -> None:
    """Delete ALL message chunk rows for a conversation (used before full reindex)."""
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM ConversationSearchMessages WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_conversation_state(
    users_dir: str,
    conversation_id: str,
    user_email: str,
    title: str = "",
    last_updated: str = "",
    domain: str = "",
    workspace_id: str = "",
    flag: str = "none",
    message_count: int = 0,
    indexed_message_count: int = 0,
    created_at: str = "",
    updated_at: str = "",
    friendly_id: str = "",
) -> None:
    """Insert or replace the state row for a conversation."""
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO ConversationSearchState
               (conversation_id, user_email, title, last_updated, domain,
                workspace_id, flag, message_count, indexed_message_count,
                created_at, updated_at, friendly_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conversation_id,
                user_email,
                title,
                last_updated,
                domain,
                workspace_id,
                flag,
                message_count,
                indexed_message_count,
                created_at,
                updated_at,
                friendly_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_conversation_from_index(
    users_dir: str,
    conversation_id: str,
) -> None:
    """Remove a conversation from ALL three index tables."""
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM ConversationSearchMeta WHERE conversation_id = ?",
            (conversation_id,),
        )
        cur.execute(
            "DELETE FROM ConversationSearchMessages WHERE conversation_id = ?",
            (conversation_id,),
        )
        cur.execute(
            "DELETE FROM ConversationSearchState WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Search (FTS5 MATCH + BM25 ranking)
# ---------------------------------------------------------------------------


def search_conversations_fts(
    users_dir: str,
    user_email: str,
    query: str,
    mode: str = "keyword",
    workspace_id: Optional[str] = None,
    domain: Optional[str] = None,
    flag: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sender_filter: Optional[str] = None,
    top_k: int = 20,
    deep: bool = False,
) -> list[dict]:
    """Search across conversations using FTS5.

    Parameters
    ----------
    mode : str
        ``keyword`` — FTS5 MATCH with BM25 ranking (default).
        ``phrase``  — FTS5 quoted phrase match.
        ``regex``   — SQL REGEXP on ConversationSearchState + meta content.
    deep : bool
        If True, also searches ``ConversationSearchMessages`` table.
    top_k : int
        Maximum number of results to return.

    Returns
    -------
    list[dict]
        Each dict has: conversation_id, title, friendly_id, last_updated,
        domain, workspace_id, flag, message_count, match_snippet,
        match_source, score.
    """
    conn = get_search_connection(users_dir)
    try:
        results = []

        if mode == "regex":
            results = _search_regex(
                conn,
                user_email,
                query,
                workspace_id,
                domain,
                flag,
                date_from,
                date_to,
                top_k,
            )
        else:
            # keyword or phrase mode — use FTS5 MATCH
            fts_query = _build_fts_query(query, mode)

            # Fast path: search meta table
            meta_results = _search_meta_fts(
                conn,
                user_email,
                fts_query,
                workspace_id,
                domain,
                flag,
                date_from,
                date_to,
                top_k,
            )
            results.extend(meta_results)

            # Deep path: also search messages table
            if deep and len(results) < top_k:
                remaining = top_k - len(results)
                seen_ids = {r["conversation_id"] for r in results}
                msg_results = _search_messages_fts(
                    conn,
                    user_email,
                    fts_query,
                    workspace_id,
                    domain,
                    flag,
                    date_from,
                    date_to,
                    remaining,
                    seen_ids,
                )
                results.extend(msg_results)

        # Filter out empty/useless results: no title, no snippet, no messages
        results = [
            r for r in results
            if r.get('title') or r.get('match_snippet') or r.get('message_count', 0) > 0
        ]

        return results[:top_k]
    finally:
        conn.close()


def _build_fts_query(query: str, mode: str) -> str:
    """Convert user query into FTS5 MATCH expression.

    - keyword: each word as an implicit AND (FTS5 default behaviour)
    - phrase: wrap in double quotes for exact phrase matching
    """
    if mode == "phrase":
        # Escape any existing double quotes
        escaped = query.replace('"', '""')
        return f'"{escaped}"'
    # keyword mode: pass through (FTS5 treats space-separated terms as implicit AND)
    return query


def _build_state_filters(
    workspace_id: Optional[str],
    domain: Optional[str],
    flag: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> tuple[str, list]:
    """Build SQL WHERE clauses for ConversationSearchState filters.

    Returns (where_fragment, params) — the fragment starts with "AND ..."
    and can be appended to an existing WHERE clause.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if workspace_id:
        clauses.append("s.workspace_id = ?")
        params.append(workspace_id)
    if domain:
        clauses.append("s.domain = ?")
        params.append(domain)
    if flag:
        clauses.append("s.flag = ?")
        params.append(flag)
    if date_from:
        clauses.append("s.last_updated >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("s.last_updated <= ?")
        params.append(date_to + "T23:59:59")
    if not clauses:
        return "", []
    return "AND " + " AND ".join(clauses), params


def _search_meta_fts(
    conn: sqlite3.Connection,
    user_email: str,
    fts_query: str,
    workspace_id: Optional[str],
    domain: Optional[str],
    flag: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    top_k: int,
) -> list[dict]:
    """Search the ConversationSearchMeta FTS5 table with BM25 ranking.

    Column weights: title=3.0, summary=2.0, memory_pad=1.0, message_tldrs=1.5
    (first two columns are UNINDEXED, weight 0).
    """
    filter_sql, filter_params = _build_state_filters(
        workspace_id,
        domain,
        flag,
        date_from,
        date_to,
    )

    sql = f"""
        SELECT
            m.conversation_id,
            s.title,
            s.friendly_id,
            s.last_updated,
            s.domain,
            s.workspace_id,
            s.flag,
            s.message_count,
            snippet(ConversationSearchMeta, -1, '<b>', '</b>', '...', 40) AS match_snippet,
            'meta' AS match_source,
            bm25(ConversationSearchMeta, 0, 0, 3.0, 2.0, 1.0, 1.5) AS score
        FROM ConversationSearchMeta m
        JOIN ConversationSearchState s
            ON m.conversation_id = s.conversation_id
        WHERE ConversationSearchMeta MATCH ?
            AND m.user_email = ?
            {filter_sql}
        ORDER BY score
        LIMIT ?
    """
    params = [fts_query, user_email] + filter_params + [top_k]

    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        # FTS5 match can fail on malformed queries — return empty
        return []


def _search_messages_fts(
    conn: sqlite3.Connection,
    user_email: str,
    fts_query: str,
    workspace_id: Optional[str],
    domain: Optional[str],
    flag: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    top_k: int,
    seen_ids: set,
) -> list[dict]:
    """Search the ConversationSearchMessages FTS5 table (deep path).

    Skips conversations already in ``seen_ids`` (from meta search).
    """
    filter_sql, filter_params = _build_state_filters(
        workspace_id,
        domain,
        flag,
        date_from,
        date_to,
    )

    sql = f"""
        SELECT
            msg.conversation_id,
            s.title,
            s.friendly_id,
            s.last_updated,
            s.domain,
            s.workspace_id,
            s.flag,
            s.message_count,
            snippet(ConversationSearchMessages, -1, '<b>', '</b>', '...', 40) AS match_snippet,
            'messages' AS match_source,
            bm25(ConversationSearchMessages, 0, 0, 0, 0, 1.0, 1.0) AS score
        FROM ConversationSearchMessages msg
        JOIN ConversationSearchState s
            ON msg.conversation_id = s.conversation_id
        WHERE ConversationSearchMessages MATCH ?
            AND msg.user_email = ?
            {filter_sql}
        GROUP BY msg.conversation_id
        ORDER BY score
        LIMIT ?
    """
    params = [fts_query, user_email] + filter_params + [top_k]

    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows if r["conversation_id"] not in seen_ids]
    except Exception:
        return []


def _search_regex(
    conn: sqlite3.Connection,
    user_email: str,
    pattern: str,
    workspace_id: Optional[str],
    domain: Optional[str],
    flag: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    top_k: int,
) -> list[dict]:
    """Regex search: REGEXP on ConversationSearchState title + meta content."""
    filter_sql, filter_params = _build_state_filters(
        workspace_id,
        domain,
        flag,
        date_from,
        date_to,
    )

    # Search state table title + join with meta for summary/memory_pad
    sql = f"""
        SELECT
            s.conversation_id,
            s.title,
            s.friendly_id,
            s.last_updated,
            s.domain,
            s.workspace_id,
            s.flag,
            s.message_count,
            '' AS match_snippet,
            CASE
                WHEN s.title REGEXP ? THEN 'title'
                WHEN m.summary REGEXP ? THEN 'summary'
                WHEN m.memory_pad REGEXP ? THEN 'memory_pad'
                ELSE 'tldrs'
            END AS match_source,
            0.0 AS score
        FROM ConversationSearchState s
        LEFT JOIN ConversationSearchMeta m
            ON s.conversation_id = m.conversation_id
        WHERE s.user_email = ?
            AND (
                s.title REGEXP ?
                OR m.summary REGEXP ?
                OR m.memory_pad REGEXP ?
                OR m.message_tldrs REGEXP ?
            )
            {filter_sql}
        LIMIT ?
    """
    params = [pattern] * 3 + [user_email] + [pattern] * 4 + filter_params + [top_k]

    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# List / Get (no search query)
# ---------------------------------------------------------------------------


def list_conversations_filtered(
    users_dir: str,
    user_email: str,
    workspace_id: Optional[str] = None,
    domain: Optional[str] = None,
    flag: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: str = "last_updated",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Browse/filter conversations without a search query.

    Returns state rows matching the optional filters, with pagination.
    """
    conn = get_search_connection(users_dir)
    try:
        filter_sql, filter_params = _build_state_filters(
            workspace_id,
            domain,
            flag,
            date_from,
            date_to,
        )

        # Validate sort_by to prevent SQL injection
        allowed_sorts = {
            "last_updated": "s.last_updated DESC",
            "title": "s.title ASC",
            "message_count": "s.message_count DESC",
            "created_at": "s.created_at DESC",
        }
        order_clause = allowed_sorts.get(sort_by, "s.last_updated DESC")

        sql = f"""
            SELECT
                s.conversation_id,
                s.title,
                s.friendly_id,
                s.last_updated,
                s.domain,
                s.workspace_id,
                s.flag,
                s.message_count,
                s.created_at,
                s.updated_at
            FROM ConversationSearchState s
            WHERE s.user_email = ?
                {filter_sql}
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
        """
        params = [user_email] + filter_params + [limit, offset]

        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation_state(
    users_dir: str,
    conversation_id: str,
) -> Optional[dict]:
    """Fetch the state row for a single conversation, or None if not indexed."""
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM ConversationSearchState WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_conversation_meta_text(
    users_dir: str,
    conversation_id: str,
) -> Optional[dict]:
    """Fetch the FTS5 meta row text fields for a single conversation.

    Returns dict with title, summary, memory_pad, message_tldrs or None.
    """
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT title, summary, memory_pad, message_tldrs
               FROM ConversationSearchMeta
               WHERE conversation_id = ?""",
            (conversation_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Backfill helpers
# ---------------------------------------------------------------------------


def get_backfill_candidates(
    users_dir: str,
    user_email: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Find conversations in ``UserToConversationId`` missing from search index.

    Returns list of ``(conversation_id, user_email)`` tuples.
    If *user_email* is None, returns candidates across all users.
    """
    from database.connection import create_connection

    users_db_path = os.path.join(users_dir, "users.db")
    users_conn = create_connection(users_db_path)

    search_conn = get_search_connection(users_dir)
    try:
        # Attach search_index.db to the users.db connection so we can
        # LEFT JOIN across the two databases.
        users_conn.execute(
            "ATTACH DATABASE ? AS search_db",
            (_search_db_path(users_dir),),
        )
        cur = users_conn.cursor()

        if user_email:
            cur.execute(
                """SELECT u.conversation_id, u.user_email
                   FROM UserToConversationId u
                   LEFT JOIN search_db.ConversationSearchState s
                       ON u.conversation_id = s.conversation_id
                   WHERE u.user_email = ?
                       AND s.conversation_id IS NULL""",
                (user_email,),
            )
        else:
            cur.execute(
                """SELECT u.conversation_id, u.user_email
                   FROM UserToConversationId u
                   LEFT JOIN search_db.ConversationSearchState s
                       ON u.conversation_id = s.conversation_id
                   WHERE s.conversation_id IS NULL""",
            )
        return cur.fetchall()
    finally:
        users_conn.close()
        search_conn.close()


def update_conversation_workspace(
    users_dir: str,
    conversation_id: str,
    workspace_id: str,
) -> None:
    """Targeted update of just the workspace_id in the state table.

    Used by ``move_conversation_to_workspace`` — avoids loading heavy
    dill files just to update one field.
    """
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE ConversationSearchState
               SET workspace_id = ?, updated_at = datetime('now')
               WHERE conversation_id = ?""",
            (workspace_id, conversation_id),
        )
        conn.commit()
    finally:
        conn.close()


def rebuild_index(
    users_dir: str,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Drop and recreate all three FTS5/state tables.

    After this call the index is empty — caller must run backfill to
    repopulate from conversation files.
    """
    log = logger or logging.getLogger(__name__)
    conn = get_search_connection(users_dir)
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS ConversationSearchMeta")
        cur.execute("DROP TABLE IF EXISTS ConversationSearchMessages")
        cur.execute("DROP TABLE IF EXISTS ConversationSearchState")
        conn.commit()
        log.info("search_index.db: dropped all tables for rebuild")
    finally:
        conn.close()

    # Recreate tables
    create_search_tables(users_dir=users_dir, logger=logger)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)
