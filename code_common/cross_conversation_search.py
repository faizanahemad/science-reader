"""
Cross-conversation search index manager and shared tool metadata.

This module provides the ``CrossConversationIndex`` class that manages the
lifecycle of the FTS5-based cross-conversation search index, and the
``CROSS_CONVERSATION_TOOLS`` dict consumed by both the LLM tool-calling
framework (``code_common/tools.py``) and the MCP conversation server
(``mcp_server/conversation.py``).

Architecture
~~~~~~~~~~~~
Three SQLite tables in ``{users_dir}/search_index.db``:

- **ConversationSearchMeta** (FTS5) — title, summary, memory_pad, TLDRs
- **ConversationSearchMessages** (FTS5) — message headers + bold + TLDRs
  in 10-message chunks
- **ConversationSearchState** (regular) — filterable metadata

All DB operations are delegated to ``database/search_index.py``.

Dependencies
~~~~~~~~~~~~
- ``database.search_index`` — all SQL operations
- ``code_common.conversation_search.extract_markdown_features`` — reused
  for header/bold extraction from message text
"""

from __future__ import annotations

import gc
import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    "cross_conversation_search",
    logger_level=10,
    time_logger_level=10,
)


# ============================================================================
# Part 1: CrossConversationIndex — Index lifecycle manager
# ============================================================================


class CrossConversationIndex:
    """Manages the cross-conversation FTS5 search index.

    Provides methods for:
    - Indexing conversation metadata and messages
    - Searching across conversations (keyword, phrase, regex)
    - Filtering by metadata (workspace, date, flag, domain)
    - Incremental updates and full rebuilds
    - Backfill of existing conversations

    Parameters
    ----------
    users_dir : str
        Absolute path to the users directory containing ``search_index.db``.
    """

    def __init__(self, users_dir: str):
        self.users_dir = users_dir

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_conversation(self, conversation: Any) -> None:
        """Full index/reindex of a single conversation.

        Extracts title, summary, memory_pad, message TLDRs, headers, bold
        text.  Creates meta row + chunked message rows (10 messages per
        chunk).  Updates state row with message_count and
        indexed_message_count.

        Parameters
        ----------
        conversation
            A ``Conversation`` object (from ``Conversation.py``).
        """
        from database.search_index import (
            delete_conversation_message_chunks,
            upsert_conversation_meta,
            upsert_conversation_messages_chunk,
            upsert_conversation_state,
        )

        try:
            conv_id = conversation.conversation_id
            user_email = self._get_user_email(conversation)

            # Extract metadata
            meta = self._extract_meta_fields(conversation)

            # Skip truly empty conversations: no title, no summary, no
            # memory_pad, no tldrs, and no messages.
            has_content = (
                meta["title"] or meta["summary"]
                or meta["memory_pad"] or meta["message_tldrs"]
                or self._get_message_count(conversation) > 0
            )
            if not has_content:
                logger.debug("Skipping empty conversation %s", conv_id)
                return

            upsert_conversation_meta(
                self.users_dir,
                conv_id,
                user_email,
                meta["title"],
                meta["summary"],
                meta["memory_pad"],
                meta["message_tldrs"],
            )

            # Extract and insert message chunks (delete existing first)
            delete_conversation_message_chunks(self.users_dir, conv_id)
            chunks = self._extract_message_chunks(conversation, start_index=0)
            for chunk in chunks:
                upsert_conversation_messages_chunk(
                    self.users_dir,
                    conv_id,
                    user_email,
                    chunk["chunk_index"],
                    chunk["message_ids_json"],
                    chunk["headers_and_bold"],
                    chunk["tldrs"],
                )

            # Update state row
            state_fields = self._extract_state_fields(conversation, meta, len(chunks))
            upsert_conversation_state(self.users_dir, **state_fields)

            logger.debug("Indexed conversation %s (full)", conv_id)
        except Exception as e:
            error_logger.warning(
                "index_conversation failed for %s: %s",
                getattr(conversation, "conversation_id", "?"),
                e,
            )

    def index_new_messages(self, conversation: Any, new_message_count: int = 0) -> None:
        """Incremental index: index only new messages since last index.

        Appends to existing message chunks or creates new chunks.
        Also updates meta row (summary/tldrs may have changed).

        Parameters
        ----------
        conversation
            A ``Conversation`` object.
        new_message_count
            Number of new messages added (used to determine start_index).
            If 0, reads ``indexed_message_count`` from the state table.
        """
        from database.search_index import (
            get_conversation_state,
            upsert_conversation_meta,
            upsert_conversation_messages_chunk,
            upsert_conversation_state,
        )

        try:
            conv_id = conversation.conversation_id
            user_email = self._get_user_email(conversation)

            # Determine where to start indexing messages
            state = get_conversation_state(self.users_dir, conv_id)
            if state:
                start_index = state["indexed_message_count"]
            else:
                start_index = 0

            # Always update meta (summary, memory_pad, tldrs may have changed)
            meta = self._extract_meta_fields(conversation)
            upsert_conversation_meta(
                self.users_dir,
                conv_id,
                user_email,
                meta["title"],
                meta["summary"],
                meta["memory_pad"],
                meta["message_tldrs"],
            )

            # Extract chunks for new messages only
            chunks = self._extract_message_chunks(conversation, start_index=start_index)
            for chunk in chunks:
                upsert_conversation_messages_chunk(
                    self.users_dir,
                    conv_id,
                    user_email,
                    chunk["chunk_index"],
                    chunk["message_ids_json"],
                    chunk["headers_and_bold"],
                    chunk["tldrs"],
                )

            # Update state with current counts
            total_messages = self._get_message_count(conversation)
            state_fields = self._extract_state_fields(
                conversation,
                meta,
                chunk_count=None,  # don't override indexed count from chunks
                total_messages=total_messages,
                indexed_messages=total_messages,  # all messages now indexed
            )
            upsert_conversation_state(self.users_dir, **state_fields)

            logger.debug(
                "Indexed conversation %s (incremental from %d)", conv_id, start_index
            )
        except Exception as e:
            error_logger.warning(
                "index_new_messages failed for %s: %s",
                getattr(conversation, "conversation_id", "?"),
                e,
            )

    def update_metadata(self, conversation: Any) -> None:
        """Update only metadata fields (title, summary, memory_pad, flag, workspace).

        Called when title changes, summary updates, or flag is set.
        Does NOT reindex messages.

        Parameters
        ----------
        conversation
            A ``Conversation`` object.
        """
        from database.search_index import (
            upsert_conversation_meta,
            upsert_conversation_state,
            get_conversation_state,
        )

        try:
            conv_id = conversation.conversation_id
            user_email = self._get_user_email(conversation)

            meta = self._extract_meta_fields(conversation)
            upsert_conversation_meta(
                self.users_dir,
                conv_id,
                user_email,
                meta["title"],
                meta["summary"],
                meta["memory_pad"],
                meta["message_tldrs"],
            )

            # Update state — preserve existing indexed_message_count
            existing_state = get_conversation_state(self.users_dir, conv_id)
            indexed_count = (
                existing_state["indexed_message_count"] if existing_state else 0
            )

            state_fields = self._extract_state_fields(
                conversation,
                meta,
                indexed_messages=indexed_count,
            )
            upsert_conversation_state(self.users_dir, **state_fields)

            logger.debug("Updated metadata for conversation %s", conv_id)
        except Exception as e:
            error_logger.warning(
                "update_metadata failed for %s: %s",
                getattr(conversation, "conversation_id", "?"),
                e,
            )

    def remove_conversation(self, conversation_id: str) -> None:
        """Delete all rows for a conversation from all 3 tables."""
        from database.search_index import delete_conversation_from_index

        try:
            delete_conversation_from_index(self.users_dir, conversation_id)
            logger.debug("Removed conversation %s from search index", conversation_id)
        except Exception as e:
            error_logger.warning(
                "remove_conversation failed for %s: %s", conversation_id, e
            )

    def backfill(
        self,
        conversation_folder: str,
        candidates: list,
        progress_callback: Optional[Callable] = None,
    ) -> None:
        """Index multiple conversations (used for startup backfill).

        Runs synchronously — caller is responsible for threading.
        Skips corrupted or unloadable conversations gracefully.

        Parameters
        ----------
        conversation_folder
            Path to the folder containing conversation subdirectories.
        candidates
            List of ``(conversation_id, user_email)`` tuples from
            ``get_backfill_candidates()``.
        progress_callback
            Optional callable receiving ``(indexed_count, total_count)``.
        """
        import os

        total = len(candidates)
        if total == 0:
            logger.info("Backfill: no candidates to index")
            return

        logger.info("Backfill: starting for %d conversations", total)
        indexed = 0

        for conv_id, user_email in candidates:
            try:
                conv_path = os.path.join(conversation_folder, conv_id)
                if not os.path.isdir(conv_path):
                    logger.debug("Backfill skip %s: directory not found", conv_id)
                    continue

                # Lazy import to avoid circular dependency
                from Conversation import Conversation

                conv = Conversation.load_local(conv_path)
                if conv is None:
                    logger.debug("Backfill skip %s: load_local returned None", conv_id)
                    continue

                self.index_conversation(conv)
                indexed += 1

                if indexed % 100 == 0:
                    logger.info("Backfill progress: %d/%d indexed", indexed, total)

                # Free memory periodically
                if indexed % 50 == 0:
                    gc.collect()

                if progress_callback:
                    progress_callback(indexed, total)

            except Exception as e:
                error_logger.warning("Backfill skip %s: %s", conv_id, e)

        logger.info("Backfill complete: %d/%d conversations indexed", indexed, total)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        user_email: str,
        query: str,
        mode: str = "keyword",
        deep: bool = False,
        workspace_id: Optional[str] = None,
        domain: Optional[str] = None,
        flag: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sender_filter: Optional[str] = None,
        top_k: int = 20,
    ) -> list[dict]:
        """Search across conversations.

        Parameters
        ----------
        mode : str
            ``keyword`` (default), ``phrase``, or ``regex``.
        deep : bool
            If True, also searches message headers/bold/TLDRs.
        top_k : int
            Maximum results to return.

        Returns
        -------
        list[dict]
            Each dict has: conversation_id, title, friendly_id, last_updated,
            domain, workspace_id, flag, message_count, match_snippet,
            match_source, score.
        """
        from database.search_index import search_conversations_fts

        return search_conversations_fts(
            self.users_dir,
            user_email,
            query,
            mode=mode,
            workspace_id=workspace_id,
            domain=domain,
            flag=flag,
            date_from=date_from,
            date_to=date_to,
            sender_filter=sender_filter,
            top_k=top_k,
            deep=deep,
        )

    def list_conversations(
        self,
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
        """Browse/filter conversations without a search query."""
        from database.search_index import list_conversations_filtered

        return list_conversations_filtered(
            self.users_dir,
            user_email,
            workspace_id=workspace_id,
            domain=domain,
            flag=flag,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )

    def get_summary(
        self,
        conversation_id: str,
        user_email: Optional[str] = None,
    ) -> Optional[dict]:
        """Get detailed summary for one conversation from the index.

        Supports both full conversation_id and friendly_id.  Resolution:
        1. Direct lookup by conversation_id in ConversationSearchState
        2. Lookup by friendly_id in ConversationSearchState
        3. Resolve via getConversationIdByFriendlyId() from database

        Returns
        -------
        dict or None
            All state fields + title, summary text, memory_pad excerpt,
            top 5 message TLDRs as highlights.
        """
        from database.search_index import (
            get_conversation_state,
            get_conversation_meta_text,
        )

        # Step 1: Direct lookup
        state = get_conversation_state(self.users_dir, conversation_id)

        # Step 2: Try friendly_id lookup
        if state is None:
            state = self._resolve_by_friendly_id(conversation_id, user_email)

        if state is None:
            return None

        real_conv_id = state["conversation_id"]

        # Get meta text
        meta = get_conversation_meta_text(self.users_dir, real_conv_id)

        result = dict(state)
        if meta:
            result["summary"] = meta.get("summary", "")
            result["memory_pad"] = meta.get("memory_pad", "")
            # Parse TLDRs and return top 5 as highlights
            tldrs_text = meta.get("message_tldrs", "")
            if tldrs_text:
                tldr_lines = [l.strip() for l in tldrs_text.split("\n") if l.strip()]
                result["highlights"] = tldr_lines[:5]
            else:
                result["highlights"] = []
        else:
            result["summary"] = ""
            result["memory_pad"] = ""
            result["highlights"] = []

        return result

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_meta_fields(self, conversation: Any) -> dict:
        """Extract title, latest summary, memory_pad, concatenated TLDRs.

        Returns dict with keys: title, summary, memory_pad, message_tldrs.
        Uses ``get_field("memory")`` for lazy-loaded fields and properties
        for attributes stored directly on the dill-serialized object.
        """
        memory = self._load_memory(conversation)

        title = memory.get("title", "") or ""
        summary = getattr(conversation, "running_summary", "") or ""
        memory_pad = getattr(conversation, "memory_pad", "") or ""

        # Concatenate answer_tldr from all model messages
        tldrs = []
        messages = self._get_messages(conversation)
        for msg in messages:
            tldr = msg.get("answer_tldr", "") or ""
            if tldr:
                tldrs.append(tldr)
        message_tldrs = "\n".join(tldrs)

        return {
            "title": title,
            "summary": summary,
            "memory_pad": memory_pad,
            "message_tldrs": message_tldrs,
        }

    def _extract_message_chunks(
        self,
        conversation: Any,
        start_index: int = 0,
    ) -> list[dict]:
        """Extract headers + bold + TLDRs from messages, chunked by 10.

        Reuses ``extract_markdown_features()`` from
        ``code_common/conversation_search.py`` for header/bold extraction.

        Returns list of dicts, each with: chunk_index, message_ids_json,
        headers_and_bold, tldrs.
        """
        from code_common.conversation_search import extract_markdown_features

        messages = self._get_messages(conversation)
        if start_index >= len(messages):
            return []

        CHUNK_SIZE = 10
        chunks = []

        for i in range(start_index, len(messages), CHUNK_SIZE):
            chunk_msgs = messages[i : i + CHUNK_SIZE]
            chunk_index = i // CHUNK_SIZE

            headers_parts = []
            bold_parts = []
            tldr_parts = []
            msg_ids = []

            for msg in chunk_msgs:
                text = msg.get("text", "") or ""
                msg_id = msg.get("id", msg.get("message_id", ""))
                if msg_id:
                    msg_ids.append(str(msg_id))

                # Extract structural features
                features = extract_markdown_features(text)
                for h in features.get("headers", []):
                    headers_parts.append(h.get("text", ""))
                bold_parts.extend(features.get("bold", []))

                # TLDRs
                tldr = msg.get("answer_tldr", "") or ""
                if tldr:
                    tldr_parts.append(tldr)

            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "message_ids_json": json.dumps(msg_ids),
                    "headers_and_bold": "\n".join(headers_parts + bold_parts),
                    "tldrs": "\n".join(tldr_parts),
                }
            )

        return chunks

    def _extract_state_fields(
        self,
        conversation: Any,
        meta: dict,
        chunk_count: Optional[int] = None,
        total_messages: Optional[int] = None,
        indexed_messages: Optional[int] = None,
    ) -> dict:
        """Extract all fields needed for ConversationSearchState row."""
        memory = self._load_memory(conversation)
        messages = self._get_messages(conversation)
        msg_count = total_messages if total_messages is not None else len(messages)

        # Compute indexed message count
        if indexed_messages is not None:
            idx_count = indexed_messages
        elif chunk_count is not None:
            idx_count = msg_count  # full index was done
        else:
            idx_count = msg_count

        conv_id = conversation.conversation_id
        user_email = self._get_user_email(conversation)

        # Get workspace_id from DB (conversation doesn't always carry it)
        workspace_id = self._get_workspace_id(conversation)
        # Use the property (reads _domain from dill), fallback to memory dict
        domain = getattr(conversation, "domain", "") or memory.get("domain", "") or ""
        flag = getattr(conversation, "flag", None) or "none"

        # Timestamps
        last_updated = memory.get("last_updated", "") or ""
        created_at = memory.get("created_at", "") or ""
        updated_at = datetime.now().isoformat()

        # Friendly ID
        friendly_id = self._get_friendly_id(conversation)

        return {
            "conversation_id": conv_id,
            "user_email": user_email,
            "title": meta["title"],
            "last_updated": last_updated,
            "domain": domain,
            "workspace_id": workspace_id,
            "flag": flag,
            "message_count": msg_count,
            "indexed_message_count": idx_count,
            "created_at": created_at,
            "updated_at": updated_at,
            "friendly_id": friendly_id,
        }

    # ------------------------------------------------------------------
    # Conversation data accessors (abstracts away Conversation internals)
    # ------------------------------------------------------------------

    @staticmethod
    def _load_memory(conversation: Any) -> dict:
        """Load the memory dict via get_field (lazy-load from JSON)."""
        if hasattr(conversation, "get_field") and callable(conversation.get_field):
            try:
                mem = conversation.get_field("memory")
                if isinstance(mem, dict):
                    return mem
            except Exception:
                pass
        # Fallback for non-standard conversation objects
        mem = getattr(conversation, "memory", None)
        return mem if isinstance(mem, dict) else {}

    @staticmethod
    def _get_user_email(conversation: Any) -> str:
        """Extract user email from a Conversation object."""
        # Prefer user_id attribute (always on dill-serialized object)
        email = getattr(conversation, "user_id", "") or ""
        if not email:
            memory = CrossConversationIndex._load_memory(conversation)
            email = memory.get("user_email", "")
        if not email:
            # Fallback: extract from conversation_id (format: email_uuid)
            conv_id = getattr(conversation, "conversation_id", "")
            if "_" in conv_id:
                email = conv_id.rsplit("_", 1)[0]
        return email or ""

    @staticmethod
    def _get_messages(conversation: Any) -> list:
        """Get the messages list from a Conversation object.

        Messages are a ``store_separate`` field — must use ``get_field``
        to trigger lazy-loading from the JSON file on disk.
        """
        if hasattr(conversation, "get_field") and callable(conversation.get_field):
            try:
                msgs = conversation.get_field("messages")
                if isinstance(msgs, list):
                    return msgs
            except Exception:
                pass
        # Fallback
        msgs = getattr(conversation, "messages", None)
        return msgs if isinstance(msgs, list) else []

    @staticmethod
    def _get_message_count(conversation: Any) -> int:
        """Get total message count."""
        messages = CrossConversationIndex._get_messages(conversation)
        return len(messages)

    @staticmethod
    def _get_workspace_id(conversation: Any) -> str:
        """Get workspace_id from conversation memory (lazy-loaded) or DB."""
        memory = CrossConversationIndex._load_memory(conversation)
        ws = memory.get("workspace_id", "")
        if not ws:
            ws = getattr(conversation, "workspace_id", "")
        return ws or ""

    @staticmethod
    def _get_friendly_id(conversation: Any) -> str:
        """Get conversation friendly ID from memory dict (lazy-loaded)."""
        memory = CrossConversationIndex._load_memory(conversation)
        fid = memory.get("conversation_friendly_id", "")
        if not fid:
            fid = getattr(conversation, "conversation_friendly_id", "")
        return fid or ""

    def _resolve_by_friendly_id(
        self,
        friendly_id: str,
        user_email: Optional[str] = None,
    ) -> Optional[dict]:
        """Resolve a friendly_id to a state row.

        1. Search ConversationSearchState.friendly_id
        2. Fall back to getConversationIdByFriendlyId() from DB
        """
        from database.search_index import get_search_connection, get_conversation_state

        # Try search in state table
        conn = get_search_connection(self.users_dir)
        try:
            cur = conn.cursor()
            if user_email:
                cur.execute(
                    "SELECT * FROM ConversationSearchState WHERE friendly_id = ? AND user_email = ?",
                    (friendly_id, user_email),
                )
            else:
                cur.execute(
                    "SELECT * FROM ConversationSearchState WHERE friendly_id = ?",
                    (friendly_id,),
                )
            row = cur.fetchone()
            if row:
                return dict(row)
        finally:
            conn.close()

        # Fall back to DB resolution
        if user_email:
            try:
                from database.conversations import getConversationIdByFriendlyId

                real_id = getConversationIdByFriendlyId(
                    users_dir=self.users_dir,
                    user_email=user_email,
                    conversation_friendly_id=friendly_id,
                )
                if real_id:
                    return get_conversation_state(self.users_dir, real_id)
            except Exception:
                pass

        return None


# ============================================================================
# Part 2: CROSS_CONVERSATION_TOOLS — shared tool metadata
# ============================================================================

CROSS_CONVERSATION_TOOLS: Dict[str, dict] = {
    "search_conversations": {
        "name": "search_conversations",
        "description": (
            "Search across ALL of the user's conversations by keyword, phrase, or regex. "
            "Use this when the user asks to find something they discussed in a previous conversation, "
            "or when they reference past work without specifying which conversation. "
            "Returns matching conversations with title, date, snippet showing where the match is, "
            "conversation ID, and friendly ID. Use 'deep' mode to also search within message "
            "headers and key terms (slower but more thorough). "
            "Combine with get_conversation_summary for full details of a specific result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query. For keyword mode: natural language keywords. "
                        "For phrase mode: exact phrase. For regex mode: regex pattern."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["keyword", "phrase", "regex"],
                    "description": (
                        "Search mode. 'keyword' (default): BM25 ranked keyword search. "
                        "'phrase': exact phrase match. 'regex': regex pattern match."
                    ),
                    "default": "keyword",
                },
                "deep": {
                    "type": "boolean",
                    "description": (
                        "If true, also searches message headers and key terms (slower). "
                        "Default false searches only titles and summaries."
                    ),
                    "default": False,
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Filter to conversations in this workspace only.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Filter: only conversations updated on or after this date (ISO format YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "Filter: only conversations updated on or before this date (ISO format YYYY-MM-DD).",
                },
                "flag": {
                    "type": "string",
                    "enum": [
                        "red",
                        "blue",
                        "green",
                        "yellow",
                        "purple",
                        "orange",
                        "none",
                    ],
                    "description": "Filter by conversation color flag.",
                },
                "sender_filter": {
                    "type": "string",
                    "enum": ["user", "model"],
                    "description": "Only return matches from messages by this sender.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 20).",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
        "is_interactive": False,
        "category": "conversation",
        "usage_guidelines": (
            "Use when user asks 'where did we discuss X', 'find my conversation about Y', "
            "'what did I say about Z last week'. Start with keyword mode (fast path). "
            "Use deep=true only if keyword mode returns too few results. "
            "Use phrase mode for exact quotes. Use regex for patterns like error codes."
        ),
    },
    "list_user_conversations": {
        "name": "list_user_conversations",
        "description": (
            "Browse and filter the user's conversations WITHOUT a search query. "
            "Use this when the user wants to see their recent conversations, "
            "browse by workspace or domain, or filter by date range or flag color. "
            "Returns conversation titles, dates, message counts, and IDs. "
            "Supports pagination via offset parameter."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Filter to this workspace.",
                },
                "domain": {
                    "type": "string",
                    "description": "Filter by domain.",
                },
                "flag": {
                    "type": "string",
                    "enum": [
                        "red",
                        "blue",
                        "green",
                        "yellow",
                        "purple",
                        "orange",
                        "none",
                    ],
                    "description": "Filter by flag color.",
                },
                "date_from": {
                    "type": "string",
                    "description": "Only conversations updated on/after this date (YYYY-MM-DD).",
                },
                "date_to": {
                    "type": "string",
                    "description": "Only conversations updated on/before this date (YYYY-MM-DD).",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["last_updated", "created_at", "title", "message_count"],
                    "description": "Sort field (default: last_updated desc).",
                    "default": "last_updated",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 50).",
                    "default": 50,
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset (default 0).",
                    "default": 0,
                },
            },
            "required": [],
        },
        "is_interactive": False,
        "category": "conversation",
        "usage_guidelines": (
            "Use when user says 'show my recent chats', 'what conversations do I have in "
            "workspace X', 'list my flagged conversations'. No search query needed — this "
            "is for browsing and filtering."
        ),
    },
    "get_conversation_summary": {
        "name": "get_conversation_summary",
        "description": (
            "Get a detailed summary of a specific conversation by its ID or friendly ID. "
            "Returns: title, full running summary, message count, date range, workspace, "
            "domain, flag, top message TLDRs as highlights, and memory pad excerpt. "
            "Use after search_conversations to get details on a specific result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "The conversation ID or friendly ID to get summary for.",
                },
            },
            "required": ["conversation_id"],
        },
        "is_interactive": False,
        "category": "conversation",
        "usage_guidelines": (
            "Use after search_conversations or list_user_conversations to get full details "
            "on a specific conversation. The conversation_id comes from the search/list results."
        ),
    },
}
