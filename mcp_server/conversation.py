"""
MCP conversation/memory server application.

Creates a ``FastMCP`` instance that exposes conversation and memory tools
(``conv_get_memory_pad``, ``conv_set_memory_pad``, ``conv_get_history``,
``conv_get_user_detail``, ``conv_get_user_preference``, ``conv_get_messages``,
``conv_set_user_detail``) over the streamable-HTTP transport.

Authentication and rate limiting are handled by the same Starlette
middleware used by the web-search MCP server (``mcp_server.mcp_app``).

Entry point: ``create_conversation_mcp_app(jwt_secret, rate_limit)``
returns a Starlette ``ASGIApp`` ready to be run with uvicorn.

Launcher: ``start_conversation_mcp_server()`` boots the server in a
daemon thread alongside the main Flask application.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from mcp_server.mcp_app import JWTAuthMiddleware, RateLimitMiddleware

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STORAGE_DIR = os.environ.get("STORAGE_DIR", "storage")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _users_dir() -> str:
    """Return the resolved users directory path.

    Uses the same convention as ``server.py``: ``<STORAGE_DIR>/users``.
    """
    return os.path.join(os.getcwd(), STORAGE_DIR, "users")


def _load_conversation(conversation_id: str):
    """Load a Conversation object from local storage by its ID.

    Parameters
    ----------
    conversation_id:
        Unique identifier of the conversation.

    Returns
    -------
    Conversation | None
        The loaded conversation, or *None* on failure.
    """
    from Conversation import Conversation

    folder = os.path.join(STORAGE_DIR, "conversations", conversation_id)
    if not os.path.isdir(folder):
        return None
    return Conversation.load_local(folder)


# ---------------------------------------------------------------------------
# Health-check endpoint
# ---------------------------------------------------------------------------


async def _health_check(request: Request) -> JSONResponse:
    """Simple health-check endpoint for load-balancers."""
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_conversation_mcp_app(
    jwt_secret: str, rate_limit: int = 10
) -> tuple[ASGIApp, Any]:
    """Create the MCP conversation/memory server as an ASGI application.

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

    mcp = FastMCP(
        "Conversation Memory Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool 1: conv_get_memory_pad
    # -----------------------------------------------------------------

    @mcp.tool()
    def conv_get_memory_pad(user_email: str, conversation_id: str) -> str:
        """Get the per-conversation memory pad (scratchpad).

        The memory pad stores factual data and details accumulated
        during the conversation.

        Args:
            user_email: Email of the user who owns the conversation.
            conversation_id: Unique identifier for the conversation.
        """
        try:
            conv = _load_conversation(conversation_id)
            if conv is None:
                return f"Error: conversation '{conversation_id}' not found."
            return conv.memory_pad or ""
        except Exception as exc:
            logger.exception("conv_get_memory_pad error: %s", exc)
            return f"Error retrieving memory pad: {exc}"

    # -----------------------------------------------------------------
    # Tool 2: conv_set_memory_pad
    # -----------------------------------------------------------------

    @mcp.tool()
    def conv_set_memory_pad(
        user_email: str, conversation_id: str, text: str
    ) -> str:
        """Set (overwrite) the per-conversation memory pad.

        Args:
            user_email: Email of the user who owns the conversation.
            conversation_id: Unique identifier for the conversation.
            text: New memory pad content (plain text).
        """
        try:
            conv = _load_conversation(conversation_id)
            if conv is None:
                return json.dumps({"success": False, "error": f"conversation '{conversation_id}' not found"})
            conv.set_memory_pad(text)
            return json.dumps({"success": True})
        except Exception as exc:
            logger.exception("conv_set_memory_pad error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 3: conv_get_history
    # -----------------------------------------------------------------

    @mcp.tool()
    def conv_get_history(
        user_email: str, conversation_id: str, query: str = ""
    ) -> str:
        """Get formatted conversation history (summary + recent messages).

        Returns a human-readable markdown string with conversation summary,
        recent messages, and metadata.

        Args:
            user_email: Email of the user who owns the conversation.
            conversation_id: Unique identifier for the conversation.
            query: Optional query to focus history retrieval on a topic.
        """
        try:
            conv = _load_conversation(conversation_id)
            if conv is None:
                return f"Error: conversation '{conversation_id}' not found."
            return conv.get_conversation_history(query=query)
        except Exception as exc:
            logger.exception("conv_get_history error: %s", exc)
            return f"Error retrieving conversation history: {exc}"

    # -----------------------------------------------------------------
    # Tool 4: conv_get_user_detail
    # -----------------------------------------------------------------

    @mcp.tool()
    def conv_get_user_detail(user_email: str) -> str:
        """Get the user's persistent memory/bio.

        User details persist across all conversations and contain
        biographical info, preferences, and accumulated knowledge
        about the user.

        Args:
            user_email: Email of the user.
        """
        try:
            from database.users import getUserFromUserDetailsTable

            user_details = getUserFromUserDetailsTable(
                user_email, users_dir=_users_dir(), logger=logger
            )
            if user_details is None:
                return ""
            return user_details.get("user_memory", "") or ""
        except Exception as exc:
            logger.exception("conv_get_user_detail error: %s", exc)
            return f"Error retrieving user details: {exc}"

    # -----------------------------------------------------------------
    # Tool 5: conv_get_user_preference
    # -----------------------------------------------------------------

    @mcp.tool()
    def conv_get_user_preference(user_email: str) -> str:
        """Get the user's stored preferences.

        User preferences persist across all conversations and describe
        how the user likes responses formatted, their expertise level,
        and other customisation options.

        Args:
            user_email: Email of the user.
        """
        try:
            from database.users import getUserFromUserDetailsTable

            user_details = getUserFromUserDetailsTable(
                user_email, users_dir=_users_dir(), logger=logger
            )
            if user_details is None:
                return ""
            return user_details.get("user_preferences", "") or ""
        except Exception as exc:
            logger.exception("conv_get_user_preference error: %s", exc)
            return f"Error retrieving user preferences: {exc}"

    # -----------------------------------------------------------------
    # Tool 6: conv_get_messages  (full tier)
    # -----------------------------------------------------------------

    @mcp.tool()
    def conv_get_messages(user_email: str, conversation_id: str) -> str:
        """Get the raw message list from a conversation.

        Returns a JSON-encoded list of message objects. Each message
        contains fields like ``text``, ``role``, ``timestamp``, etc.

        Args:
            user_email: Email of the user who owns the conversation.
            conversation_id: Unique identifier for the conversation.
        """
        try:
            conv = _load_conversation(conversation_id)
            if conv is None:
                return json.dumps({"error": f"conversation '{conversation_id}' not found"})
            messages = conv.get_message_list() or []
            return json.dumps(messages, default=str)
        except Exception as exc:
            logger.exception("conv_get_messages error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 7: conv_set_user_detail  (full tier)
    # -----------------------------------------------------------------

    @mcp.tool()
    def conv_set_user_detail(user_email: str, text: str) -> str:
        """Update the user's persistent memory/bio.

        Overwrites the stored user memory with the provided text.
        This data persists across all conversations.

        Args:
            user_email: Email of the user.
            text: New user memory/bio content (plain text).
        """
        try:
            from database.users import updateUserInfoInUserDetailsTable

            success = updateUserInfoInUserDetailsTable(
                user_email,
                user_memory=text,
                users_dir=_users_dir(),
                logger=logger,
            )
            return json.dumps({"success": success})
        except Exception as exc:
            logger.exception("conv_set_user_detail error: %s", exc)
            return json.dumps({"success": False, "error": str(exc)})

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
# Daemon-thread launcher (mirrors mcp_server/__init__.py)
# ---------------------------------------------------------------------------


def start_conversation_mcp_server() -> None:
    """Start the MCP conversation/memory server in a daemon thread.

    Reads configuration from environment variables:

    - ``CONVERSATION_MCP_ENABLED`` — set to ``"false"`` to skip startup
      (default ``"true"``).
    - ``CONVERSATION_MCP_PORT`` — port number (default ``8104``).
    - ``MCP_JWT_SECRET`` — HS256 secret for bearer-token verification.
    - ``MCP_RATE_LIMIT`` — max tool calls per token per minute (default ``10``).

    Does nothing if disabled or if ``MCP_JWT_SECRET`` is not set.
    The thread is a daemon so it exits automatically when the main process
    (Flask) terminates.
    """
    if os.getenv("CONVERSATION_MCP_ENABLED", "true").lower() == "false":
        logger.info("Conversation MCP server disabled (CONVERSATION_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — Conversation MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the Conversation MCP server."
        )
        return

    port = int(os.getenv("CONVERSATION_MCP_PORT", "8104"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_conversation_mcp_app(
                jwt_secret=jwt_secret, rate_limit=rate_limit
            )
            logger.info("Conversation MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("Conversation MCP server failed to start")

    thread = threading.Thread(
        target=_run, name="conversation-mcp-server", daemon=True
    )
    thread.start()
    logger.info(
        "Conversation MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )
