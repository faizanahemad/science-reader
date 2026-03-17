"""
Tool call history storage, query, and shared tool metadata.

Why this exists
---------------
This module provides:

1.  **SQLite storage layer** — ``ToolCallHistoryDB`` class that persists all
    tool call inputs and results (both from the LLM tool-calling framework and
    MCP server) in a shared SQLite database scoped by ``user_email``.
2.  **Deterministic ID generation** — ``tool_call_hash(tool_name, args)``
    produces a repeatable 16-char hex hash so the LLM can detect duplicate
    calls and reuse prior results.
3.  **Category resolution** — ``get_tool_category(tool_name)`` maps a tool
    name to its category using the live ``TOOL_REGISTRY``.
4.  **Shared tool metadata** — ``TOOL_HISTORY_TOOLS`` dict with canonical
    names, descriptions, and JSON Schema parameter definitions for the four
    *tool call history* tools.  Both ``code_common/tools.py`` (LLM tool-calling)
    and ``mcp_server/mcp_app.py`` (MCP server) import from here.
5.  **Auto-pruning** — on first init, old records are pruned by age and
    per-user row cap.

Storage
~~~~~~~
A separate SQLite file at ``storage/users/tool_call_history.sqlite`` (not
``users.db``) because tool history has high write frequency, large TEXT blobs,
and aggressive pruning.  Follows the ``pkb.sqlite`` / ``search_index.db``
precedent.

Dependencies
~~~~~~~~~~~~
- Standard library only (``sqlite3``, ``hashlib``, ``json``, ``time``, ``os``).
- ``loggers.py`` for logging.
- Lazy import of ``TOOL_REGISTRY`` to avoid circular dependencies.

Usage from tool-calling (code_common/tools.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    from code_common.tool_call_history import TOOL_HISTORY_TOOLS

    @register_tool(**_history_tool_kwargs("list_search_history"))
    def handle_list_search_history(args, context): ...

Usage from MCP server (mcp_server/mcp_app.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    from code_common.tool_call_history import get_tool_call_history_db

    db = get_tool_call_history_db()
    rows = db.list_calls(user_email, tool_category="search", limit=20)
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    "tool_call_history",
    logger_level=10,
    time_logger_level=10,
)


# ============================================================================
# Part 1: Deterministic ID Generation
# ============================================================================


def tool_call_hash(tool_name: str, args: dict) -> str:
    """Deterministic hash of tool name + canonical args.

    Produces a 16-char hex string (64 bits of entropy).  Collision probability
    is negligible for the expected volume (~10^-6 at 10,000 records).

    Parameters
    ----------
    tool_name:
        Registered tool name (e.g. ``"web_search"``).
    args:
        Tool arguments dict (order-independent — sorted internally).

    Returns
    -------
    str
        16-character lowercase hex hash.
    """
    canonical = json.dumps(args, sort_keys=True, ensure_ascii=False)
    raw = f"{tool_name}:{canonical}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ============================================================================
# Part 2: Category Resolution
# ============================================================================


def get_tool_category(tool_name: str) -> str:
    """Get tool category from the live TOOL_REGISTRY.

    Uses lazy import to avoid circular dependencies (tools.py imports us,
    we import tools.py's registry).

    Parameters
    ----------
    tool_name:
        Registered tool name.

    Returns
    -------
    str
        Category string (e.g. ``"search"``, ``"documents"``, ``"conversation"``)
        or ``"unknown"`` if the tool is not registered.
    """
    try:
        from code_common.tools import TOOL_REGISTRY

        tool_def = TOOL_REGISTRY.get_tool(tool_name)
        return tool_def.category if tool_def else "unknown"
    except Exception:
        return "unknown"


# ============================================================================
# Part 3: SQLite Storage Layer
# ============================================================================

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tool_call_history (
    id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_category TEXT NOT NULL,
    args_json TEXT NOT NULL,
    result_text TEXT,
    error TEXT,
    user_email TEXT NOT NULL,
    conversation_id TEXT,
    timestamp REAL NOT NULL,
    duration_seconds REAL,
    result_chars INTEGER,
    source TEXT NOT NULL DEFAULT 'tool_calling',
    PRIMARY KEY (id, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_tch_user ON tool_call_history(user_email);
CREATE INDEX IF NOT EXISTS idx_tch_tool ON tool_call_history(tool_name);
CREATE INDEX IF NOT EXISTS idx_tch_category ON tool_call_history(tool_category);
CREATE INDEX IF NOT EXISTS idx_tch_ts ON tool_call_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_tch_conv ON tool_call_history(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tch_id ON tool_call_history(id);
CREATE INDEX IF NOT EXISTS idx_tch_user_cat_ts
    ON tool_call_history(user_email, tool_category, timestamp DESC);
"""


class ToolCallHistoryDB:
    """SQLite-backed storage for tool call history.

    Thread-safe via ``check_same_thread=False`` and WAL mode.  All public
    methods are fail-open (catch and log exceptions, never raise).

    Parameters
    ----------
    db_path:
        Absolute path to the SQLite database file.  Created if missing.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        """Create/open the database and ensure schema exists."""
        try:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()
            logger.info("Tool call history DB initialized at %s", self._db_path)
        except Exception as e:
            error_logger.error("Failed to initialize tool call history DB: %s", e)
            self._conn = None

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def record(
        self,
        id: str,
        tool_name: str,
        tool_category: str,
        args_json: str,
        result_text: Optional[str],
        error: Optional[str],
        user_email: str,
        conversation_id: Optional[str],
        timestamp: float,
        duration_seconds: Optional[float],
        result_chars: Optional[int],
        source: str = "tool_calling",
    ) -> bool:
        """Insert a tool call record.  Fail-open — never raises.

        Returns
        -------
        bool
            True if the record was inserted successfully, False otherwise.
        """
        if not self._conn:
            return False
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO tool_call_history
                       (id, tool_name, tool_category, args_json, result_text,
                        error, user_email, conversation_id, timestamp,
                        duration_seconds, result_chars, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        id,
                        tool_name,
                        tool_category,
                        args_json,
                        result_text,
                        error,
                        user_email,
                        conversation_id,
                        timestamp,
                        duration_seconds,
                        result_chars,
                        source,
                    ),
                )
                self._conn.commit()
            return True
        except Exception as e:
            error_logger.error("Failed to record tool call: %s", e)
            return False

    # ------------------------------------------------------------------
    # List (metadata only — no result_text)
    # ------------------------------------------------------------------

    def list_calls(
        self,
        user_email: str,
        tool_category: Optional[str] = None,
        tool_name: Optional[str] = None,
        conversation_id: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List tool call metadata (no full result_text) for a user.

        Parameters
        ----------
        user_email:
            Scope to this user.
        tool_category:
            Filter by category (e.g. ``"search"``).  None = all.
        tool_name:
            Filter by exact tool name.  None = all.
        conversation_id:
            Filter by conversation.  None = all conversations.
        since:
            Epoch timestamp lower bound (inclusive).
        until:
            Epoch timestamp upper bound (inclusive).
        limit:
            Max rows to return (default 50, capped at 200).

        Returns
        -------
        list[dict]
            Metadata dicts ordered by timestamp DESC.  Keys:
            ``id``, ``tool_name``, ``tool_category``, ``args_json``,
            ``result_chars``, ``duration_seconds``, ``timestamp``,
            ``conversation_id``, ``source``, ``error``.
        """
        if not self._conn:
            return []
        limit = min(max(limit, 1), 200)
        try:
            conditions = ["user_email = ?"]
            params: list = [user_email]

            if tool_category:
                conditions.append("tool_category = ?")
                params.append(tool_category)
            if tool_name:
                conditions.append("tool_name = ?")
                params.append(tool_name)
            if conversation_id:
                conditions.append("conversation_id = ?")
                params.append(conversation_id)
            if since is not None:
                conditions.append("timestamp >= ?")
                params.append(since)
            if until is not None:
                conditions.append("timestamp <= ?")
                params.append(until)

            where = " AND ".join(conditions)
            params.append(limit)

            sql = f"""
                SELECT id, tool_name, tool_category, args_json,
                       result_chars, duration_seconds, timestamp,
                       conversation_id, source, error
                FROM tool_call_history
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            with self._lock:
                cursor = self._conn.execute(sql, params)
                columns = [desc[0] for desc in cursor.description]
                rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return rows
        except Exception as e:
            error_logger.error("Failed to list tool calls: %s", e)
            return []

    # ------------------------------------------------------------------
    # Get full results by IDs
    # ------------------------------------------------------------------

    def get_results(
        self,
        user_email: str,
        ids: List[str],
        tool_category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get full tool call records (including result_text) by IDs.

        Parameters
        ----------
        user_email:
            Scope to this user (security — cannot read other users' results).
        ids:
            List of tool call hash IDs.
        tool_category:
            Optional category filter (e.g. ``"search"`` for search-only tools).

        Returns
        -------
        list[dict]
            Full records including ``result_text``.  For each ID, returns the
            MOST RECENT execution (latest timestamp).
        """
        if not self._conn or not ids:
            return []
        try:
            # Cap at 10 IDs to prevent abuse
            ids = ids[:10]
            placeholders = ", ".join("?" for _ in ids)

            conditions = [f"id IN ({placeholders})", "user_email = ?"]
            params: list = list(ids) + [user_email]

            if tool_category:
                conditions.append("tool_category = ?")
                params.append(tool_category)

            where = " AND ".join(conditions)

            # For each ID, get the most recent execution
            sql = f"""
                SELECT id, tool_name, tool_category, args_json, result_text,
                       error, conversation_id, timestamp, duration_seconds,
                       result_chars, source
                FROM tool_call_history
                WHERE {where}
                ORDER BY timestamp DESC
            """
            with self._lock:
                cursor = self._conn.execute(sql, params)
                columns = [desc[0] for desc in cursor.description]
                all_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

            # Deduplicate: keep only the most recent per ID
            seen_ids: set = set()
            results = []
            for row in all_rows:
                if row["id"] not in seen_ids:
                    seen_ids.add(row["id"])
                    results.append(row)

            return results
        except Exception as e:
            error_logger.error("Failed to get tool call results: %s", e)
            return []

    # ------------------------------------------------------------------
    # Prune
    # ------------------------------------------------------------------

    def prune(self, max_age_days: int = 30, max_rows_per_user: int = 10000) -> int:
        """Delete old records.  Two passes:

        1. Delete rows older than ``max_age_days``.
        2. For each user, delete rows beyond ``max_rows_per_user`` (keeping newest).

        Returns
        -------
        int
            Total number of rows deleted.
        """
        if not self._conn:
            return 0
        total_deleted = 0
        try:
            cutoff = time.time() - max_age_days * 86400
            with self._lock:
                # Pass 1: age-based pruning
                cursor = self._conn.execute(
                    "DELETE FROM tool_call_history WHERE timestamp < ?",
                    (cutoff,),
                )
                total_deleted += cursor.rowcount

                # Pass 2: per-user row cap
                users_cursor = self._conn.execute(
                    "SELECT DISTINCT user_email FROM tool_call_history"
                )
                for (user_email,) in users_cursor.fetchall():
                    count_cursor = self._conn.execute(
                        "SELECT COUNT(*) FROM tool_call_history WHERE user_email = ?",
                        (user_email,),
                    )
                    count = count_cursor.fetchone()[0]
                    if count > max_rows_per_user:
                        excess = count - max_rows_per_user
                        del_cursor = self._conn.execute(
                            """DELETE FROM tool_call_history
                               WHERE rowid IN (
                                   SELECT rowid FROM tool_call_history
                                   WHERE user_email = ?
                                   ORDER BY timestamp ASC
                                   LIMIT ?
                               )""",
                            (user_email, excess),
                        )
                        total_deleted += del_cursor.rowcount

                self._conn.commit()
        except Exception as e:
            error_logger.error("Failed to prune tool call history: %s", e)
        return total_deleted


# ============================================================================
# Part 4: Module-Level Singleton
# ============================================================================

_db_instance: Optional[ToolCallHistoryDB] = None
_db_lock = threading.Lock()


def get_tool_call_history_db() -> Optional[ToolCallHistoryDB]:
    """Get or create the singleton ToolCallHistoryDB instance.

    Lazy-initializes on first call.  Runs startup pruning after first init.
    Returns None if initialization fails (fail-open).
    """
    global _db_instance
    if _db_instance is not None:
        return _db_instance

    with _db_lock:
        # Double-check after acquiring lock
        if _db_instance is not None:
            return _db_instance

        db_path = os.path.join(
            os.environ.get("STORAGE_DIR", "storage"),
            "users",
            "tool_call_history.sqlite",
        )
        try:
            _db_instance = ToolCallHistoryDB(db_path)
            # Prune old records on startup
            try:
                pruned = _db_instance.prune(max_age_days=30, max_rows_per_user=10000)
                if pruned > 0:
                    logger.info("Pruned %d old tool call history records", pruned)
            except Exception:
                pass
        except Exception as e:
            error_logger.error("Failed to create tool call history DB: %s", e)
            _db_instance = None

    return _db_instance


# ============================================================================
# Part 5: Search Tool Names (for category filtering)
# ============================================================================

SEARCH_TOOL_NAMES = frozenset(
    {
        "web_search",
        "perplexity_search",
        "jina_search",
        "jina_read_page",
        "read_link",
    }
)

_HISTORY_CATEGORY = "conversation"


# ============================================================================
# Part 6: Shared Tool Metadata (TOOL_HISTORY_TOOLS)
# ============================================================================

TOOL_HISTORY_TOOLS: Dict[str, dict] = {
    # ------------------------------------------------------------------
    # list_search_history
    # ------------------------------------------------------------------
    "list_search_history": {
        "name": "list_search_history",
        "description": (
            "List previous web searches and page reads from this session and "
            "past conversations. Returns metadata including a unique ID for "
            "each call, the tool used, search query/URL, result size, duration, "
            "and timestamp. Use this to check if a similar search was already "
            "performed before making a new one. Use get_search_results with "
            "the returned IDs to retrieve full results without re-executing "
            "the search."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query_contains": {
                    "type": "string",
                    "description": (
                        "Filter to searches whose args contain this substring "
                        "(case-insensitive). E.g. 'quantum' to find searches "
                        "about quantum computing."
                    ),
                },
                "conversation_only": {
                    "type": "boolean",
                    "description": (
                        "If true, only show searches from the current "
                        "conversation. Default false (all conversations)."
                    ),
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": ("Maximum results to return (default 20, max 100)."),
                    "default": 20,
                },
                "since_hours": {
                    "type": "number",
                    "description": (
                        "Only show searches from the last N hours. "
                        "Omit for no time filter."
                    ),
                },
            },
        },
        "is_interactive": False,
        "category": _HISTORY_CATEGORY,
        "usage_guidelines": (
            "• Use before making a new web search to avoid redundant calls.\n"
            "• query_contains is a substring match on the full args JSON, "
            "so you can match on query text, URLs, or tool names.\n"
            "• Returns metadata only — use get_search_results with the IDs "
            "to get full result text.\n"
            "• Results are ordered newest first."
        ),
    },
    # ------------------------------------------------------------------
    # get_search_results
    # ------------------------------------------------------------------
    "get_search_results": {
        "name": "get_search_results",
        "description": (
            "Get the full result text of previous web searches or page reads "
            "by their IDs. Use list_search_history first to find relevant IDs. "
            "This avoids re-executing expensive searches when the same "
            "information was already fetched."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of tool call IDs from list_search_history results."
                    ),
                    "minItems": 1,
                    "maxItems": 10,
                },
            },
            "required": ["ids"],
        },
        "is_interactive": False,
        "category": _HISTORY_CATEGORY,
        "usage_guidelines": (
            "• Pass IDs from list_search_history results.\n"
            "• Returns the most recent execution for each ID.\n"
            "• Results may be large — up to 50,000 chars per search result.\n"
            "• Max 10 IDs per call."
        ),
    },
    # ------------------------------------------------------------------
    # list_tool_call_history
    # ------------------------------------------------------------------
    "list_tool_call_history": {
        "name": "list_tool_call_history",
        "description": (
            "List previous tool calls across all categories (search, documents, "
            "PKB, memory, artefacts, etc.). Returns metadata for each call. "
            "Use get_tool_call_results with the returned IDs to retrieve "
            "full results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name_filter": {
                    "type": "string",
                    "description": (
                        "Filter by exact tool name (e.g. 'pkb_search', "
                        "'document_lookup')."
                    ),
                },
                "tool_category_filter": {
                    "type": "string",
                    "description": (
                        "Filter by category: search, documents, pkb, memory, "
                        "artefacts, prompts, conversation, code_runner, "
                        "clarification."
                    ),
                },
                "conversation_only": {
                    "type": "boolean",
                    "description": (
                        "If true, only show calls from the current conversation."
                    ),
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": ("Maximum results to return (default 20, max 100)."),
                    "default": 20,
                },
                "since_hours": {
                    "type": "number",
                    "description": ("Only show calls from the last N hours."),
                },
            },
        },
        "is_interactive": False,
        "category": _HISTORY_CATEGORY,
        "usage_guidelines": (
            "• This is the superset — queries ALL tool categories.\n"
            "• Use tool_category_filter to narrow (e.g. 'search', 'pkb').\n"
            "• Use tool_name_filter for exact tool name matches.\n"
            "• For search-only history, prefer list_search_history instead "
            "(same data, pre-filtered).\n"
            "• Results are ordered newest first."
        ),
    },
    # ------------------------------------------------------------------
    # get_tool_call_results
    # ------------------------------------------------------------------
    "get_tool_call_results": {
        "name": "get_tool_call_results",
        "description": (
            "Get the full result text of previous tool calls by their IDs "
            "(any category). Use list_tool_call_history first to find IDs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of tool call IDs from list_tool_call_history results."
                    ),
                    "minItems": 1,
                    "maxItems": 10,
                },
            },
            "required": ["ids"],
        },
        "is_interactive": False,
        "category": _HISTORY_CATEGORY,
        "usage_guidelines": (
            "• Pass IDs from list_tool_call_history results.\n"
            "• Returns the most recent execution for each ID.\n"
            "• No category restriction — retrieves any tool's results.\n"
            "• Max 10 IDs per call."
        ),
    },
}

# Convenience: list of all tool names in this module.
TOOL_HISTORY_TOOL_NAMES: List[str] = list(TOOL_HISTORY_TOOLS.keys())
