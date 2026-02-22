"""
MCP artefacts server application.

Creates a ``FastMCP`` instance that exposes 9 artefact management tools
over the streamable-HTTP transport on port 8103.

Artefacts are the ONLY file creation mechanism in the system. The model
MUST use these tools to produce any persistent output (documents, code,
reports, notes). OpenCode can also directly edit artefact files using its
built-in bash/edit tools once it has the absolute ``file_path``.

Authentication and rate limiting are handled by Starlette middleware
that wraps the ASGI app returned by ``FastMCP.streamable_http_app()``.
This follows the same pattern as ``mcp_server/mcp_app.py``.

Entry point: ``create_artefacts_mcp_app(jwt_secret, rate_limit)`` returns a
Starlette ``ASGIApp`` ready to be run with uvicorn.

Launcher: ``start_artefacts_mcp_server()`` runs it in a daemon thread.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from typing import Any, Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_server.mcp_app import JWTAuthMiddleware, RateLimitMiddleware, _health_check

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STORAGE_DIR = os.environ.get("STORAGE_DIR", "storage")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))


# ---------------------------------------------------------------------------
# Conversation loader
# ---------------------------------------------------------------------------


def _load_conversation(conversation_id: str):
    """Load a conversation by its ID from the local storage directory.

    Parameters
    ----------
    conversation_id : str
        Unique conversation identifier.

    Returns
    -------
    Conversation
        Loaded conversation instance.
    """
    from Conversation import Conversation

    folder = os.path.join(STORAGE_DIR, "conversations", conversation_id)
    return Conversation.load_local(folder)




# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_artefacts_mcp_app(jwt_secret: str, rate_limit: int = 10) -> tuple[ASGIApp, Any]:
    """Create the MCP artefacts server as an ASGI application.

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
        "Artefacts Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool 1: artefacts_list
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_list(user_email: str, conversation_id: str) -> str:
        """List all artefacts in a conversation.

        Returns a JSON array of artefact metadata objects, each containing:
        id, name, file_type, file_name, created_at, updated_at, size_bytes.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation to list artefacts from.
        """
        try:
            conv = _load_conversation(conversation_id)
            artefacts = conv.list_artefacts()
            return json.dumps(artefacts)
        except Exception as exc:
            logger.exception("artefacts_list error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 2: artefacts_create
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_create(
        user_email: str,
        conversation_id: str,
        name: str,
        file_type: str,
        initial_content: str = "",
    ) -> str:
        """Create a new artefact file in the conversation.

        Artefacts are the ONLY way to create persistent files. Returns
        file_path for direct editing with bash/edit tools.
        File types: md, txt, py, js, json, html, css.

        This is the primary file creation tool in the system. The returned
        file_path is an absolute path that OpenCode can use with native
        edit/bash tools for subsequent modifications.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation to create the artefact in.
            name: Display name for the artefact.
            file_type: File extension (e.g., 'md', 'py', 'json').
            initial_content: Initial file content (default empty).
        """
        try:
            conv = _load_conversation(conversation_id)
            result = conv.create_artefact(name, file_type, initial_content)
            result["file_path"] = os.path.join(
                conv.artefacts_path, result["file_name"]
            )
            return json.dumps(result)
        except Exception as exc:
            logger.exception("artefacts_create error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 3: artefacts_get
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_get(
        user_email: str, conversation_id: str, artefact_id: str
    ) -> str:
        """Get artefact metadata, content, and file_path.

        Returns the full artefact including its content read from disk
        and the absolute file_path for direct editing.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
        """
        try:
            conv = _load_conversation(conversation_id)
            result = conv.get_artefact(artefact_id)
            result["file_path"] = os.path.join(
                conv.artefacts_path, result["file_name"]
            )
            return json.dumps(result)
        except Exception as exc:
            logger.exception("artefacts_get error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 4: artefacts_get_file_path
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_get_file_path(
        user_email: str, conversation_id: str, artefact_id: str
    ) -> str:
        """Get the absolute file path for an artefact.

        Returns JUST the absolute filesystem path so OpenCode can edit
        the artefact directly with native bash/edit tools. This is the
        key tool for enabling direct file manipulation.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
        """
        try:
            conv = _load_conversation(conversation_id)
            _idx, entry = conv._get_artefact_entry(artefact_id)
            file_path = os.path.join(conv.artefacts_path, entry["file_name"])
            return json.dumps({"file_path": file_path})
        except Exception as exc:
            logger.exception("artefacts_get_file_path error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 5: artefacts_update
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_update(
        user_email: str, conversation_id: str, artefact_id: str, content: str
    ) -> str:
        """Update the full content of an artefact.

        Overwrites the artefact file with the given content. Use this
        when replacing the entire file via MCP. For partial edits,
        prefer using artefacts_get_file_path and editing directly.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
            content: New file content to write.
        """
        try:
            conv = _load_conversation(conversation_id)
            result = conv.update_artefact_content(artefact_id, content)
            return json.dumps(result)
        except Exception as exc:
            logger.exception("artefacts_update error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 6: artefacts_delete
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_delete(
        user_email: str, conversation_id: str, artefact_id: str
    ) -> str:
        """Delete an artefact file and its metadata.

        Removes the artefact file from disk and clears its metadata
        entry from the conversation.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact to delete.
        """
        try:
            conv = _load_conversation(conversation_id)
            conv.delete_artefact(artefact_id)
            return json.dumps({"success": True})
        except Exception as exc:
            logger.exception("artefacts_delete error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 7: artefacts_propose_edits (full tier)
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_propose_edits(
        user_email: str,
        conversation_id: str,
        artefact_id: str,
        instruction: str,
        selection_start_line: Optional[int] = None,
        selection_end_line: Optional[int] = None,
    ) -> str:
        """Propose LLM-generated edits to an artefact.

        Sends the instruction to the Flask backend which generates
        edit operations using an LLM. Returns proposed ops and a diff.
        Only in full tier — OpenCode can use bash edit directly instead.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
            instruction: Natural language edit instruction for the LLM.
            selection_start_line: Optional start line of selection to edit.
            selection_end_line: Optional end line of selection to edit.
        """
        import requests

        try:
            url = (
                f"http://localhost:{FLASK_PORT}"
                f"/artefacts/{conversation_id}/{artefact_id}/propose_edits"
            )
            body: dict[str, Any] = {"instruction": instruction}
            if selection_start_line is not None:
                body["selection_start_line"] = selection_start_line
            if selection_end_line is not None:
                body["selection_end_line"] = selection_end_line
            resp = requests.post(url, json=body, timeout=120)
            resp.raise_for_status()
            return json.dumps(resp.json())
        except Exception as exc:
            logger.exception("artefacts_propose_edits error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 8: artefacts_apply_edits (full tier)
    # -----------------------------------------------------------------

    @mcp.tool()
    def artefacts_apply_edits(
        user_email: str,
        conversation_id: str,
        artefact_id: str,
        base_hash: str,
        ops: list,
    ) -> str:
        """Apply proposed edit operations to an artefact.

        Applies previously proposed ops if the base_hash matches
        (optimistic concurrency control). Only in full tier.

        Args:
            user_email: Email of the requesting user.
            conversation_id: Conversation containing the artefact.
            artefact_id: Unique identifier of the artefact.
            base_hash: Hash of the content the ops were generated against.
            ops: List of edit operations to apply.
        """
        import requests

        try:
            url = (
                f"http://localhost:{FLASK_PORT}"
                f"/artefacts/{conversation_id}/{artefact_id}/apply_edits"
            )
            body = {"base_hash": base_hash, "ops": ops}
            resp = requests.post(url, json=body, timeout=60)
            resp.raise_for_status()
            return json.dumps(resp.json())
        except Exception as exc:
            logger.exception("artefacts_apply_edits error: %s", exc)
            return json.dumps({"error": str(exc)})

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
# Launcher: start in daemon thread (called from server.py)
# ---------------------------------------------------------------------------


def start_artefacts_mcp_server() -> None:
    """Start the MCP artefacts server in a daemon thread.

    Reads configuration from environment variables:
    - ``ARTEFACTS_MCP_ENABLED``: set to ``"false"`` to skip (default ``"true"``).
    - ``ARTEFACTS_MCP_PORT``: port number (default ``8103``).
    - ``MCP_JWT_SECRET``: HS256 secret for bearer-token verification.
    - ``MCP_RATE_LIMIT``: max tool calls per token per minute (default ``10``).

    The thread is a daemon so it exits automatically when the main process
    (Flask) terminates.
    """
    if os.getenv("ARTEFACTS_MCP_ENABLED", "true").lower() == "false":
        logger.info("Artefacts MCP server disabled (ARTEFACTS_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — Artefacts MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the artefacts MCP server."
        )
        return

    port = int(os.getenv("ARTEFACTS_MCP_PORT", "8103"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_artefacts_mcp_app(
                jwt_secret=jwt_secret, rate_limit=rate_limit
            )
            logger.info("Artefacts MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("Artefacts MCP server failed to start")

    thread = threading.Thread(target=_run, name="mcp-artefacts-server", daemon=True)
    thread.start()
    logger.info(
        "Artefacts MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )
