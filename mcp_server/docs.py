"""
MCP document server application.

Creates a ``FastMCP`` instance that exposes document-related tools
(listing, querying, full-text retrieval, Q&A) for both conversation-scoped
documents and global documents over the streamable-HTTP transport.

Authentication and rate limiting are handled by Starlette middleware
imported from ``mcp_server.mcp_app`` (same JWT + rate-limit stack used by
the web-search MCP server).

Entry point: ``create_docs_mcp_app(jwt_secret, rate_limit)`` returns a
Starlette ``ASGIApp`` ready to be run with uvicorn.

Environment variables
---------------------
DOCS_MCP_ENABLED : str
    Set to ``"false"`` to skip startup (default ``"true"``).
DOCS_MCP_PORT : str
    Port for the docs MCP server (default ``8102``).
MCP_JWT_SECRET : str
    **Required.** HS256 secret for bearer-token verification.
MCP_RATE_LIMIT : str
    Max tool calls per token per minute (default ``10``).
MCP_TOOL_TIER : str
    ``"baseline"`` (4 tools) or ``"full"`` (all 9 tools). Default ``"baseline"``.
STORAGE_DIR : str
    Root storage directory (default ``"storage"``).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import threading
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from mcp_server.mcp_app import JWTAuthMiddleware, RateLimitMiddleware, _health_check

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_keys_cache: dict[str, Any] | None = None


def _get_keys() -> dict[str, Any]:
    """Load API keys from environment variables (cached after first call).

    Uses ``keyParser({})`` with an empty session dict so that only
    environment variables are consulted — no Flask session.
    """
    global _keys_cache
    if _keys_cache is None:
        from endpoints.utils import keyParser

        _keys_cache = keyParser({})
    return _keys_cache


def _user_hash(email: str) -> str:
    """Compute the user-hash used for per-user storage directories.

    Matches the implementation in ``endpoints/global_docs.py``.
    """
    return hashlib.md5(email.encode()).hexdigest()


def _storage_dir() -> str:
    """Return the root storage directory path."""
    return os.getenv("STORAGE_DIR", "storage")


def _users_dir() -> str:
    """Return the users directory path (``<storage>/users``).

    This is the ``users_dir`` parameter expected by ``database/global_docs``
    functions.
    """
    return os.path.join(os.getcwd(), _storage_dir(), "users")


def _conversation_folder() -> str:
    """Return the conversations directory path (``<storage>/conversations``)."""
    return os.path.join(os.getcwd(), _storage_dir(), "conversations")


def _load_doc_index(doc_storage_path: str):
    """Load a DocIndex from a storage path and set API keys.

    Parameters
    ----------
    doc_storage_path : str
        Absolute or relative path to the document storage folder.

    Returns
    -------
    DocIndex or None
        The loaded DocIndex with API keys set, or None on failure.
    """
    from DocIndex import DocIndex

    doc = DocIndex.load_local(doc_storage_path)
    if doc is None:
        return None
    doc.set_api_keys(_get_keys())
    return doc


def _load_conversation(conversation_id: str):
    """Load a Conversation object from disk.

    Parameters
    ----------
    conversation_id : str
        The conversation identifier.

    Returns
    -------
    Conversation or None
        The loaded conversation, or None on failure.
    """
    from Conversation import Conversation

    path = os.path.join(_conversation_folder(), conversation_id)
    if not os.path.isdir(path):
        return None
    return Conversation.load_local(path)


def _resolve_global_doc_storage(user_email: str, doc_id: str) -> tuple[dict | None, str | None]:
    """Look up a global document and return (metadata_dict, doc_storage_path).

    Parameters
    ----------
    user_email : str
        The user's email address.
    doc_id : str
        The global document identifier.

    Returns
    -------
    tuple[dict | None, str | None]
        (row_dict, doc_storage_path) or (None, None) if not found.
    """
    from database.global_docs import get_global_doc

    row = get_global_doc(
        users_dir=_users_dir(),
        user_email=user_email,
        doc_id=doc_id,
    )
    if row is None:
        return None, None
    return row, row.get("doc_storage", "")



# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_docs_mcp_app(jwt_secret: str, rate_limit: int = 10) -> tuple[ASGIApp, Any]:
    """Create the MCP document server as an ASGI application.

    Returns a tuple of ``(asgi_app, fastmcp_instance)`` so the caller
    can manage the FastMCP session lifecycle if needed.

    Parameters
    ----------
    jwt_secret:
        HS256 secret for JWT verification.
    rate_limit:
        Maximum tool calls per token per minute.

    Returns
    -------
    tuple[ASGIApp, FastMCP]
        The wrapped Starlette ASGI app and the underlying FastMCP instance.
    """
    from mcp.server.fastmcp import FastMCP

    tool_tier = os.getenv("MCP_TOOL_TIER", "baseline").lower()

    mcp = FastMCP(
        "Document Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Baseline Tool 1: docs_list_conversation_docs
    # -----------------------------------------------------------------

    @mcp.tool()
    def docs_list_conversation_docs(user_email: str, conversation_id: str) -> str:
        """List all documents attached to a conversation.

        Returns a JSON array of document metadata objects, each containing:
        ``doc_id``, ``title``, ``short_summary``, ``doc_storage_path``, and
        ``source``.  Use ``doc_storage_path`` with other docs tools to query
        or retrieve the document content.

        Args:
            user_email: The user's email address.
            conversation_id: The conversation identifier.
        """
        try:
            conv = _load_conversation(conversation_id)
            if conv is None:
                return json.dumps({"error": f"Conversation '{conversation_id}' not found."})

            # uploaded_documents_list stores tuples of (doc_id, doc_storage, pdf_url)
            doc_list = conv.get_field("uploaded_documents_list")
            if not doc_list:
                return json.dumps([])

            results = []
            for idx, entry in enumerate(doc_list):
                doc_id, doc_storage, pdf_url = entry[0], entry[1], entry[2]
                # Try to load the DocIndex to get title/summary
                doc = _load_doc_index(doc_storage)
                if doc is None:
                    results.append({
                        "index": idx + 1,
                        "doc_id": doc_id,
                        "title": "(failed to load)",
                        "short_summary": "",
                        "doc_storage_path": doc_storage,
                        "source": pdf_url,
                    })
                    continue
                results.append({
                    "index": idx + 1,
                    "doc_id": doc_id,
                    "title": doc.title,
                    "short_summary": doc.short_summary,
                    "doc_storage_path": doc_storage,
                    "source": pdf_url,
                })
            return json.dumps(results)
        except Exception as exc:
            logger.exception("docs_list_conversation_docs error: %s", exc)
            return json.dumps({"error": f"Failed to list conversation docs: {exc}"})

    # -----------------------------------------------------------------
    # Baseline Tool 2: docs_list_global_docs
    # -----------------------------------------------------------------

    @mcp.tool()
    def docs_list_global_docs(user_email: str) -> str:
        """List all global documents for a user.

        Global documents are indexed once and can be referenced from any
        conversation using ``#gdoc_N`` syntax.  Returns a JSON array of
        metadata objects with ``doc_id``, ``display_name``, ``title``,
        ``short_summary``, ``doc_storage_path``, and ``source``.

        Args:
            user_email: The user's email address.
        """
        try:
            from database.global_docs import list_global_docs

            rows = list_global_docs(
                users_dir=_users_dir(),
                user_email=user_email,
            )
            results = []
            for idx, row in enumerate(rows):
                results.append({
                    "index": idx + 1,
                    "doc_id": row.get("doc_id", ""),
                    "display_name": row.get("display_name", ""),
                    "title": row.get("title", ""),
                    "short_summary": row.get("short_summary", ""),
                    "doc_storage_path": row.get("doc_storage", ""),
                    "source": row.get("doc_source", ""),
                })
            return json.dumps(results)
        except Exception as exc:
            logger.exception("docs_list_global_docs error: %s", exc)
            return json.dumps({"error": f"Failed to list global docs: {exc}"})

    # -----------------------------------------------------------------
    # Baseline Tool 3: docs_query
    # -----------------------------------------------------------------

    @mcp.tool()
    def docs_query(
        user_email: str,
        doc_storage_path: str,
        query: str,
        token_limit: int = 4096,
    ) -> str:
        """Semantic search within a document.

        Finds and returns the most relevant passages from the document
        that match the query.  Use ``docs_list_conversation_docs`` or
        ``docs_list_global_docs`` first to obtain the ``doc_storage_path``.

        Args:
            user_email: The user's email address.
            doc_storage_path: Path to the document storage folder (from listing tools).
            query: The search query describing what information you need.
            token_limit: Maximum number of tokens in the returned passages (default 4096).
        """
        try:
            doc = _load_doc_index(doc_storage_path)
            if doc is None:
                return f"Error: Could not load document at '{doc_storage_path}'."
            return doc.semantic_search_document(query, token_limit=token_limit)
        except Exception as exc:
            logger.exception("docs_query error: %s", exc)
            return f"Error querying document: {exc}"

    # -----------------------------------------------------------------
    # Baseline Tool 4: docs_get_full_text
    # -----------------------------------------------------------------

    @mcp.tool()
    def docs_get_full_text(
        user_email: str,
        doc_storage_path: str,
        token_limit: int = 16000,
    ) -> str:
        """Retrieve the full text content of a document.

        Returns the complete document text including the brief summary.
        For very large documents the output may be truncated to
        ``token_limit`` tokens.  Use ``docs_query`` for targeted retrieval
        from large documents.

        Args:
            user_email: The user's email address.
            doc_storage_path: Path to the document storage folder (from listing tools).
            token_limit: Maximum number of tokens to return (default 16000).
        """
        try:
            doc = _load_doc_index(doc_storage_path)
            if doc is None:
                return f"Error: Could not load document at '{doc_storage_path}'."
            text = doc.get_raw_doc_text()
            # Rough token truncation (1 token ~ 4 chars)
            char_limit = token_limit * 4
            if len(text) > char_limit:
                text = text[:char_limit] + "\n\n[... truncated ...]"
            return text
        except Exception as exc:
            logger.exception("docs_get_full_text error: %s", exc)
            return f"Error retrieving document text: {exc}"

    # -----------------------------------------------------------------
    # Full-tier tools (registered only when MCP_TOOL_TIER=full)
    # -----------------------------------------------------------------

    if tool_tier == "full":

        # -------------------------------------------------------------
        # Full Tool 5: docs_get_info
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_get_info(user_email: str, doc_storage_path: str) -> str:
            """Get metadata about a document without retrieving its full text.

            Returns a JSON object with ``title``, ``brief_summary``,
            ``short_summary``, ``text_len`` (approximate character count),
            and ``visible`` (whether the document is active).

            Args:
                user_email: The user's email address.
                doc_storage_path: Path to the document storage folder (from listing tools).
            """
            try:
                doc = _load_doc_index(doc_storage_path)
                if doc is None:
                    return json.dumps({"error": f"Could not load document at '{doc_storage_path}'."})
                return json.dumps({
                    "title": doc.title,
                    "brief_summary": doc.brief_summary,
                    "short_summary": doc.short_summary,
                    "text_len": getattr(doc, "_text_len", 0),
                    "visible": doc.visible,
                })
            except Exception as exc:
                logger.exception("docs_get_info error: %s", exc)
                return json.dumps({"error": f"Failed to get document info: {exc}"})

        # -------------------------------------------------------------
        # Full Tool 6: docs_answer_question
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_answer_question(
            user_email: str,
            doc_storage_path: str,
            question: str,
        ) -> str:
            """Ask a question about a document and get an LLM-generated answer.

            Uses RAG-style retrieval: relevant passages are extracted from
            the document and fed to an LLM to produce a concise answer.
            Best for factual questions about the document's content.

            Args:
                user_email: The user's email address.
                doc_storage_path: Path to the document storage folder (from listing tools).
                question: The question to answer about the document.
            """
            try:
                from collections import defaultdict

                doc = _load_doc_index(doc_storage_path)
                if doc is None:
                    return f"Error: Could not load document at '{doc_storage_path}'."
                return doc.get_short_answer(question, mode=defaultdict(lambda: False))
            except Exception as exc:
                logger.exception("docs_answer_question error: %s", exc)
                return f"Error answering question: {exc}"

        # -------------------------------------------------------------
        # Full Tool 7: docs_get_global_doc_info
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_get_global_doc_info(user_email: str, doc_id: str) -> str:
            """Get metadata about a global document.

            Returns a JSON object with ``doc_id``, ``display_name``,
            ``title``, ``short_summary``, ``doc_storage_path``, ``source``,
            ``created_at``, and ``updated_at``.

            Args:
                user_email: The user's email address.
                doc_id: The global document identifier (from ``docs_list_global_docs``).
            """
            try:
                row, doc_storage = _resolve_global_doc_storage(user_email, doc_id)
                if row is None:
                    return json.dumps({"error": f"Global doc '{doc_id}' not found for user."})
                return json.dumps({
                    "doc_id": row.get("doc_id", ""),
                    "display_name": row.get("display_name", ""),
                    "title": row.get("title", ""),
                    "short_summary": row.get("short_summary", ""),
                    "doc_storage_path": doc_storage,
                    "source": row.get("doc_source", ""),
                    "created_at": row.get("created_at", ""),
                    "updated_at": row.get("updated_at", ""),
                })
            except Exception as exc:
                logger.exception("docs_get_global_doc_info error: %s", exc)
                return json.dumps({"error": f"Failed to get global doc info: {exc}"})

        # -------------------------------------------------------------
        # Full Tool 8: docs_query_global_doc
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_query_global_doc(
            user_email: str,
            doc_id: str,
            query: str,
            token_limit: int = 4096,
        ) -> str:
            """Semantic search within a global document.

            Resolves the global document by ``doc_id``, then performs
            semantic search to find relevant passages matching the query.

            Args:
                user_email: The user's email address.
                doc_id: The global document identifier (from ``docs_list_global_docs``).
                query: The search query describing what information you need.
                token_limit: Maximum number of tokens in the returned passages (default 4096).
            """
            try:
                row, doc_storage = _resolve_global_doc_storage(user_email, doc_id)
                if row is None:
                    return f"Error: Global doc '{doc_id}' not found for user."
                if not doc_storage:
                    return f"Error: Global doc '{doc_id}' has no storage path."
                doc = _load_doc_index(doc_storage)
                if doc is None:
                    return f"Error: Could not load global doc at '{doc_storage}'."
                return doc.semantic_search_document(query, token_limit=token_limit)
            except Exception as exc:
                logger.exception("docs_query_global_doc error: %s", exc)
                return f"Error querying global document: {exc}"

        # -------------------------------------------------------------
        # Full Tool 9: docs_get_global_doc_full_text
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_get_global_doc_full_text(
            user_email: str,
            doc_id: str,
            token_limit: int = 16000,
        ) -> str:
            """Retrieve the full text content of a global document.

            Resolves the global document by ``doc_id`` and returns its
            complete text.  For very large documents the output may be
            truncated to ``token_limit`` tokens.

            Args:
                user_email: The user's email address.
                doc_id: The global document identifier (from ``docs_list_global_docs``).
                token_limit: Maximum number of tokens to return (default 16000).
            """
            try:
                row, doc_storage = _resolve_global_doc_storage(user_email, doc_id)
                if row is None:
                    return f"Error: Global doc '{doc_id}' not found for user."
                if not doc_storage:
                    return f"Error: Global doc '{doc_id}' has no storage path."
                doc = _load_doc_index(doc_storage)
                if doc is None:
                    return f"Error: Could not load global doc at '{doc_storage}'."
                text = doc.get_raw_doc_text()
                # Rough token truncation (1 token ~ 4 chars)
                char_limit = token_limit * 4
                if len(text) > char_limit:
                    text = text[:char_limit] + "\n\n[... truncated ...]"
                return text
            except Exception as exc:
                logger.exception("docs_get_global_doc_full_text error: %s", exc)
                return f"Error retrieving global document text: {exc}"

    # -----------------------------------------------------------------
    # Build the Starlette ASGI app with middleware layers
    # -----------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            yield

    mcp_starlette = mcp.streamable_http_app()

    outer_app = Starlette(
        routes=[
            Route("/health", _health_check, methods=["GET"]),
            Mount("/", app=mcp_starlette),
        ],
        lifespan=lifespan,
    )

    app_with_rate_limit = RateLimitMiddleware(outer_app, rate=rate_limit, window=60)

    app_with_auth: ASGIApp = JWTAuthMiddleware(
        app_with_rate_limit, jwt_secret=jwt_secret
    )

    return app_with_auth, mcp


# ---------------------------------------------------------------------------
# Server launcher (daemon thread)
# ---------------------------------------------------------------------------


def start_docs_mcp_server() -> None:
    """Start the MCP document server in a daemon thread.

    Reads configuration from environment variables (see module docstring).
    Does nothing if ``DOCS_MCP_ENABLED=false`` or ``MCP_JWT_SECRET`` is not
    set.  The thread is a daemon so it exits automatically when the main
    process (Flask) terminates.
    """
    if os.getenv("DOCS_MCP_ENABLED", "true").lower() == "false":
        logger.info("Docs MCP server disabled (DOCS_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set \u2014 Docs MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the MCP document server."
        )
        return

    port = int(os.getenv("DOCS_MCP_PORT", "8102"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_docs_mcp_app(
                jwt_secret=jwt_secret, rate_limit=rate_limit
            )
            logger.info("Docs MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("Docs MCP server failed to start")

    thread = threading.Thread(target=_run, name="docs-mcp-server", daemon=True)
    thread.start()
    logger.info(
        "Docs MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )
