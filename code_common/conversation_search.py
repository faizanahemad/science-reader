"""
Conversation message search, indexing, and shared tool metadata.

Why this exists
---------------
This module provides:

1.  **Markdown feature extraction** — pulls headers (all levels), bold text,
    and italic text from message content using regex.
2.  **BM25 message index** — ``MessageSearchIndex`` class that incrementally
    indexes conversation messages with unigram + bigram tokenisation, and
    supports both BM25-ranked and substring/regex search.
3.  **Shared tool metadata** — canonical tool names, descriptions, and JSON
    Schema parameter definitions for the five *conversation* category tools.
    Both ``code_common/tools.py`` (LLM tool-calling) and
    ``mcp_server/conversation.py`` (MCP server) import from here so
    descriptions are defined in exactly one place.

Dependencies
~~~~~~~~~~~~
- ``rank_bm25`` (already in requirements: ``rank_bm25==0.2.2``)
- Standard library only for markdown extraction (regex-based, no heavy deps).

Usage from tool-calling (code_common/tools.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    from code_common.conversation_search import CONVERSATION_TOOLS

    @register_tool(**CONVERSATION_TOOLS["search_messages"])
    def handle_search_messages(args, context): ...

Usage from MCP server (mcp_server/conversation.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    from code_common.conversation_search import CONVERSATION_TOOLS

    desc = CONVERSATION_TOOLS["search_messages"]
    @mcp.tool(description=desc["description"])
    def search_messages(...): ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    "conversation_search",
    logger_level=10,
    time_logger_level=10,
)


# ============================================================================
# Part 1: Markdown Feature Extraction
# ============================================================================


def extract_markdown_features(text: str) -> dict:
    """Extract structural markdown features from message text.

    Parses headers (all levels ``#`` through ``######``), bold text
    (``**text**`` and ``__text__``), and italic text (``*text*`` and
    ``_text_``, excluding bold matches) using regex.

    Parameters
    ----------
    text:
        Raw message text (may contain markdown).

    Returns
    -------
    dict
        ``{"headers": [...], "bold": [...], "italic": [...]}``
        Each value is a list of extracted text strings (duplicates removed,
        order preserved).
    """
    if not text or not isinstance(text, str):
        return {"headers": [], "bold": [], "italic": []}

    # --- Headers: lines starting with 1-6 '#' characters ----------------
    header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    headers = []
    for m in header_pattern.finditer(text):
        level = len(m.group(1))
        content = m.group(2).strip()
        if content:
            headers.append({"level": level, "text": content})

    # --- Bold: **text** or __text__ --------------------------------------
    bold_pattern = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
    bold_texts = []
    seen_bold = set()
    for m in bold_pattern.finditer(text):
        content = (m.group(1) or m.group(2)).strip()
        if content and content not in seen_bold:
            bold_texts.append(content)
            seen_bold.add(content)

    # --- Italic: *text* or _text_ (excluding bold) -----------------------
    #  We match single * or _ delimiters but skip double ** / __ via
    #  negative lookbehind/lookahead.
    italic_pattern = re.compile(
        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"  # *text* (not **)
        r"|"
        r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)",  # _text_ (not __)
        re.DOTALL,
    )
    italic_texts = []
    seen_italic = set()
    for m in italic_pattern.finditer(text):
        content = (m.group(1) or m.group(2)).strip()
        # Skip if this text was already captured as bold
        if content and content not in seen_italic and content not in seen_bold:
            italic_texts.append(content)
            seen_italic.add(content)

    return {
        "headers": headers,
        "bold": bold_texts,
        "italic": italic_texts,
    }


# ============================================================================
# Part 2: Tokenisation (unigram + bigram)
# ============================================================================

# Simple word boundary tokeniser — splits on non-word characters.
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def tokenize_with_bigrams(text: str) -> List[str]:
    """Tokenise *text* into lowercased unigrams + underscore-joined bigrams.

    Example::

        >>> tokenize_with_bigrams("Hello World foo")
        ['hello', 'world', 'foo', 'hello_world', 'world_foo']

    Parameters
    ----------
    text:
        Raw text string.

    Returns
    -------
    list[str]
        Combined unigram + bigram token list.
    """
    words = _WORD_RE.findall(text.lower())
    bigrams = [f"{words[i]}_{words[i + 1]}" for i in range(len(words) - 1)]
    return words + bigrams


# ============================================================================
# Part 3: MessageSearchIndex
# ============================================================================


class MessageSearchIndex:
    """Incrementally-built BM25 + text-match index for conversation messages.

    **Lifecycle**

    1. Created empty (or loaded from ``from_dict()``).
    2. ``add_message()`` called at persist-time with each new user/model
       message — extracts markdown features, tokenises, appends to corpus.
    3. ``search_bm25()`` or ``search_text()`` called at query-time.
       The BM25Okapi object is lazily rebuilt from the stored token corpus
       on the first search after new messages are added (since BM25Okapi
       is not JSON-serialisable).

    **Persistence**

    ``to_dict()`` / ``from_dict()`` produce plain dicts that
    ``json.dump`` / ``json.load`` handle.  The BM25Okapi object itself is
    never serialised — only the tokenised corpus is, and BM25 is rebuilt
    on first search.

    Parameters
    ----------
    (none — use ``from_dict()`` to restore from persisted state)
    """

    def __init__(self) -> None:
        self._corpus: List[List[str]] = []  # parallel to _message_ids
        self._message_ids: List[str] = []
        self._metadata: Dict[str, dict] = {}  # message_id -> extracted features
        self._bm25 = None  # lazily built
        self._dirty = False  # True when corpus changed since last BM25 build

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    def add_message(
        self,
        message_id: str,
        text: str,
        sender: str = "user",
    ) -> None:
        """Index a single message incrementally.

        Extracts markdown features, tokenises into unigrams + bigrams,
        and appends to the internal corpus.  Marks the BM25 object as
        dirty so it is rebuilt on next search.

        Parameters
        ----------
        message_id:
            Unique identifier for the message.
        text:
            Full message text content.
        sender:
            ``"user"`` or ``"model"``.
        """
        if message_id in self._metadata:
            logger.debug("Message %s already indexed, skipping.", message_id)
            return

        # Extract markdown features
        features = extract_markdown_features(text)

        # Build a combined text that gives extra weight to headers/bold
        # by including them as additional tokens.
        header_texts = " ".join(h["text"] for h in features["headers"])
        bold_texts = " ".join(features["bold"])
        enriched = f"{text} {header_texts} {bold_texts}"

        tokens = tokenize_with_bigrams(enriched)

        self._corpus.append(tokens)
        self._message_ids.append(message_id)
        self._metadata[message_id] = {
            "sender": sender,
            "preview": text[:300],
            "length": len(text),
            "headers": features["headers"],
            "bold": features["bold"],
            "italic": features["italic"],
        }
        self._dirty = True
        logger.debug(
            "Indexed message %s (sender=%s, tokens=%d, headers=%d, bold=%d)",
            message_id,
            sender,
            len(tokens),
            len(features["headers"]),
            len(features["bold"]),
        )

    # ------------------------------------------------------------------
    # BM25 search
    # ------------------------------------------------------------------

    def _ensure_bm25(self) -> None:
        """Rebuild the BM25Okapi index from corpus if dirty or missing."""
        if self._bm25 is not None and not self._dirty:
            return
        if not self._corpus:
            self._bm25 = None
            return
        from rank_bm25 import BM25Okapi

        self._bm25 = BM25Okapi(self._corpus)
        self._dirty = False
        logger.debug("BM25 index rebuilt (%d documents).", len(self._corpus))

    def search_bm25(
        self,
        query: str,
        top_k: int = 10,
        sender_filter: Optional[str] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
    ) -> List[dict]:
        """BM25-ranked keyword search over indexed messages.

        Parameters
        ----------
        query:
            Search query text.
        top_k:
            Maximum number of results to return.
        sender_filter:
            If set, only return messages from this sender (``"user"`` or
            ``"model"``).
        min_length:
            Minimum message text length to include.
        max_length:
            Maximum message text length to include.

        Returns
        -------
        list[dict]
            Ranked results, each with keys: ``message_id``, ``score``,
            ``preview``, ``sender``, ``index``, ``headers``.
        """
        if not self._corpus or not query.strip():
            return []

        self._ensure_bm25()
        if self._bm25 is None:
            return []

        tokenized_query = tokenize_with_bigrams(query)
        scores = self._bm25.get_scores(tokenized_query)

        # Build (score, index) pairs, filter, sort
        results = []
        for idx, score in enumerate(scores):
            if score <= 0:
                continue
            mid = self._message_ids[idx]
            meta = self._metadata.get(mid, {})
            if sender_filter and meta.get("sender") != sender_filter:
                continue
            msg_len = meta.get("length", 0)
            if min_length is not None and msg_len < min_length:
                continue
            if max_length is not None and msg_len > max_length:
                continue
            results.append(
                {
                    "message_id": mid,
                    "score": round(float(score), 4),
                    "preview": meta.get("preview", ""),
                    "sender": meta.get("sender", ""),
                    "index": idx,
                    "headers": meta.get("headers", []),
                }
            )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    # ------------------------------------------------------------------
    # Text / regex search
    # ------------------------------------------------------------------

    def search_text(
        self,
        query: str,
        case_sensitive: bool = False,
        sender_filter: Optional[str] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        top_k: int = 20,
    ) -> List[dict]:
        """Substring or regex search over raw message previews.

        Tries the query as a regex first; falls back to plain substring
        matching if the regex is invalid.

        Parameters
        ----------
        query:
            Search string or regex pattern.
        case_sensitive:
            Whether matching is case-sensitive.
        sender_filter:
            If set, only return messages from this sender.
        min_length:
            Minimum message text length to include.
        max_length:
            Maximum message text length to include.
        top_k:
            Maximum results to return.

        Returns
        -------
        list[dict]
            Matching results with ``message_id``, ``match_snippet``,
            ``sender``, ``index``.
        """
        if not query:
            return []

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = None
        try:
            pattern = re.compile(query, flags)
            use_regex = True
        except re.error:
            use_regex = False

        results = []
        for idx, mid in enumerate(self._message_ids):
            meta = self._metadata.get(mid, {})
            if sender_filter and meta.get("sender") != sender_filter:
                continue
            msg_len = meta.get("length", 0)
            if min_length is not None and msg_len < min_length:
                continue
            if max_length is not None and msg_len > max_length:
                continue

            preview = meta.get("preview", "")
            if use_regex and pattern is not None:
                m = pattern.search(preview)
                if not m:
                    continue
                # Build a snippet around the match
                start = max(0, m.start() - 40)
                end = min(len(preview), m.end() + 40)
                snippet = (
                    ("..." if start > 0 else "")
                    + preview[start:end]
                    + ("..." if end < len(preview) else "")
                )
            else:
                compare_preview = preview if case_sensitive else preview.lower()
                compare_query = query if case_sensitive else query.lower()
                pos = compare_preview.find(compare_query)
                if pos == -1:
                    continue
                start = max(0, pos - 40)
                end = min(len(preview), pos + len(query) + 40)
                snippet = (
                    ("..." if start > 0 else "")
                    + preview[start:end]
                    + ("..." if end < len(preview) else "")
                )

            results.append(
                {
                    "message_id": mid,
                    "match_snippet": snippet,
                    "sender": meta.get("sender", ""),
                    "index": idx,
                }
            )
            if len(results) >= top_k:
                break

        return results

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise index state to a JSON-safe dict.

        The BM25Okapi object is *not* serialised — only the tokenised
        corpus.  BM25 is rebuilt lazily on next ``search_bm25()`` call.

        Returns
        -------
        dict
        """
        return {
            "version": 1,
            "corpus": self._corpus,
            "message_ids": self._message_ids,
            "metadata": self._metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessageSearchIndex":
        """Deserialise from a dict produced by ``to_dict()``.

        Parameters
        ----------
        data:
            Dict with keys ``corpus``, ``message_ids``, ``metadata``.

        Returns
        -------
        MessageSearchIndex
        """
        idx = cls()
        if not isinstance(data, dict):
            return idx
        idx._corpus = data.get("corpus", [])
        idx._message_ids = data.get("message_ids", [])
        idx._metadata = data.get("metadata", {})
        idx._dirty = True  # Force BM25 rebuild on first search
        return idx

    def __len__(self) -> int:
        return len(self._message_ids)

    def __contains__(self, message_id: str) -> bool:
        return message_id in self._metadata


# ============================================================================
# Part 4: Shared Tool Metadata
# ============================================================================
#
# Canonical tool names, descriptions, and parameter schemas.
# Both code_common/tools.py and mcp_server/conversation.py import
# CONVERSATION_TOOLS from here.
#
# Each entry is a dict with keys that can be splatted into
# @register_tool(**entry) for tool-calling, or read individually
# for MCP tool registration.
#
# Structure per tool:
#   name:          str — unique tool name
#   description:   str — LLM-facing description (WHEN to use, not just WHAT)
#   parameters:    dict — JSON Schema for the tool's accepted arguments
#   is_interactive: bool — whether the tool pauses for user input
#   category:      str — UI grouping category
#   usage_guidelines: str — extra usage hints (not sent to LLM, for docs only)
# ============================================================================

_CONVERSATION_CATEGORY = "conversation"

CONVERSATION_TOOLS: Dict[str, dict] = {
    # ------------------------------------------------------------------
    # search_messages
    # ------------------------------------------------------------------
    "search_messages": {
        "name": "search_messages",
        "description": (
            "Search within the current conversation's messages by keyword. "
            "Supports two modes: 'bm25' for relevance-ranked keyword search "
            "(best for topical queries like 'machine learning', 'error handling'), "
            "and 'text' for exact substring or regex matching (best for finding "
            "specific phrases, code snippets, or names). "
            "Use this when the user asks to find, recall, or locate something "
            "said earlier in the conversation. Prefer 'bm25' mode by default; "
            "use 'text' mode when the user wants an exact phrase match. "
            "Results include a preview snippet, sender role, and message index. "
            "Combine with read_message to get full message content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Conversation to search within.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Search query. For 'bm25' mode: natural-language keywords. "
                        "For 'text' mode: exact substring or regex pattern."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["bm25", "text"],
                    "description": (
                        "Search strategy. 'bm25' = relevance-ranked keyword search "
                        "(default, good for topical recall). 'text' = exact substring "
                        "or regex match (good for specific phrases or code)."
                    ),
                    "default": "bm25",
                },
                "sender_filter": {
                    "type": "string",
                    "enum": ["user", "model"],
                    "description": (
                        "Only return messages from this sender. Omit to search all."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum results to return (default 10).",
                    "default": 10,
                },
                "min_length": {
                    "type": "integer",
                    "description": (
                        "Only include messages with at least this many characters."
                    ),
                },
                "max_length": {
                    "type": "integer",
                    "description": (
                        "Only include messages with at most this many characters."
                    ),
                },
            },
            "required": ["conversation_id", "query"],
        },
        "is_interactive": False,
        "category": _CONVERSATION_CATEGORY,
        "usage_guidelines": (
            "• Default to mode='bm25' unless the user explicitly wants exact match.\n"
            "• For code searches, mode='text' with regex is more precise.\n"
            "• Use sender_filter='user' to search only user messages, "
            "'model' for assistant replies.\n"
            "• Results contain preview snippets (300 chars). "
            "Call read_message for full content.\n"
            "• The BM25 index includes unigram and bigram tokens, plus "
            "boosted markdown headers and bold text for better recall.\n"
            "• If the conversation has no search index yet (older conversations), "
            "the first search triggers a one-time full index build."
        ),
    },
    # ------------------------------------------------------------------
    # list_messages
    # ------------------------------------------------------------------
    "list_messages": {
        "name": "list_messages",
        "description": (
            "List messages in the current conversation with a short preview. "
            "Each result includes the message index, message_id, sender role, "
            "the first 300 characters of text, and the TLDR summary (if the "
            "assistant message has one). "
            "Use this to get an overview of conversation contents, browse "
            "messages by position, or find a specific message to read in full. "
            "Supports slicing by index range (from start or from end) and "
            "filtering by sender."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Conversation to list messages from.",
                },
                "start": {
                    "type": "integer",
                    "description": (
                        "Start index (0-based, inclusive). If from_end is true, "
                        "this is the offset from the last message."
                    ),
                },
                "end": {
                    "type": "integer",
                    "description": (
                        "End index (exclusive). If from_end is true, this is "
                        "the offset from the last message."
                    ),
                },
                "from_end": {
                    "type": "boolean",
                    "description": (
                        "If true, start/end count backwards from the last message. "
                        "E.g. start=0, end=10, from_end=true returns the last 10 messages."
                    ),
                    "default": False,
                },
                "sender_filter": {
                    "type": "string",
                    "enum": ["user", "model"],
                    "description": (
                        "Only list messages from this sender. Omit to list all."
                    ),
                },
            },
            "required": ["conversation_id"],
        },
        "is_interactive": False,
        "category": _CONVERSATION_CATEGORY,
        "usage_guidelines": (
            "• To see the last N messages: set from_end=true, start=0, end=N.\n"
            "• To see messages 5-15: set start=5, end=15.\n"
            "• Previews are 300 chars. Use read_message for full content.\n"
            "• The TLDR field is only present on assistant ('model') messages "
            "that had a TLDR generated during persist.\n"
            "• Messages are in chronological order (index 0 = earliest)."
        ),
    },
    # ------------------------------------------------------------------
    # read_message
    # ------------------------------------------------------------------
    "read_message": {
        "name": "read_message",
        "description": (
            "Read the full content of a specific message by its message_id "
            "or by its numeric index in the conversation. Returns the complete "
            "message text, sender, message_id, any extracted markdown headers, "
            "bold and italic text, and context (adjacent messages). "
            "Use this after search_messages or list_messages to get full "
            "content of a message of interest."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Conversation the message belongs to.",
                },
                "message_id": {
                    "type": "string",
                    "description": (
                        "Unique message identifier. Provide this OR index, not both."
                    ),
                },
                "index": {
                    "type": "integer",
                    "description": (
                        "Zero-based message index. Negative values count from the "
                        "end (-1 = last message). Provide this OR message_id."
                    ),
                },
            },
            "required": ["conversation_id"],
        },
        "is_interactive": False,
        "category": _CONVERSATION_CATEGORY,
        "usage_guidelines": (
            "• Provide exactly one of message_id or index.\n"
            "• index=-1 reads the last message, index=-2 the second-to-last, etc.\n"
            "• The response includes the full text — can be very long for "
            "detailed assistant responses. The tool-calling framework truncates "
            "results at 12000 chars.\n"
            "• Extracted headers/bold/italic are from the search index "
            "(available if the message was indexed).\n"
            "• Context includes 1 message before and 1 after for reference."
        ),
    },
    # ------------------------------------------------------------------
    # get_conversation_details
    # ------------------------------------------------------------------
    "get_conversation_details": {
        "name": "get_conversation_details",
        "description": (
            "Get a comprehensive overview of the conversation: title, summary, "
            "total message count with message IDs and short hashes, attached "
            "documents with their titles, artefacts in the conversation, "
            "conversation settings, and metadata like domain and last-updated "
            "timestamp. "
            "Use this to orient yourself within a conversation before diving "
            "into specific messages or documents. Also useful when the user "
            "asks 'what have we discussed?' or 'what files are attached?'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Conversation to get details for.",
                },
            },
            "required": ["conversation_id"],
        },
        "is_interactive": False,
        "category": _CONVERSATION_CATEGORY,
        "usage_guidelines": (
            "• This is a read-only overview tool — does not modify anything.\n"
            "• The summary is the auto-generated running summary from the "
            "conversation's memory field.\n"
            "• Message list includes message_id and message_short_hash for "
            "each message (useful for cross-references).\n"
            "• Document list includes doc_id, title, and short_summary.\n"
            "• Artefact list includes id, name, file_type, and size.\n"
            "• Use this as a starting point, then call specific tools "
            "(read_message, search_messages, etc.) for deeper inspection."
        ),
    },
    # ------------------------------------------------------------------
    # get_conversation_memory_pad
    # ------------------------------------------------------------------
    "get_conversation_memory_pad": {
        "name": "get_conversation_memory_pad",
        "description": (
            "Get the conversation's memory pad — a running scratchpad of "
            "extracted facts, key numbers, user preferences, and accumulated "
            "knowledge from the conversation so far. The memory pad is "
            "auto-updated after each turn with important details from the "
            "user's query and assistant's response. "
            "Use this when you need a factual summary of what has been "
            "discussed, or when the user asks about specific details, "
            "numbers, or decisions made earlier. Lighter-weight than "
            "searching through all messages."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Conversation to get the memory pad from.",
                },
            },
            "required": ["conversation_id"],
        },
        "is_interactive": False,
        "category": _CONVERSATION_CATEGORY,
        "usage_guidelines": (
            "• The memory pad is concise bullet-point format — much smaller "
            "than reading all messages.\n"
            "• It's auto-generated by an LLM extractor after each turn, so "
            "it captures important facts, numbers, metrics, and code snippets.\n"
            "• If you need verbatim quotes or full context, use "
            "search_messages + read_message instead.\n"
            "• The memory pad auto-compacts itself when it exceeds ~12000 "
            "words or ~128 lines, merging older entries."
        ),
    },
}


# Convenience: list of all tool names in this category.
CONVERSATION_TOOL_NAMES: List[str] = list(CONVERSATION_TOOLS.keys())
