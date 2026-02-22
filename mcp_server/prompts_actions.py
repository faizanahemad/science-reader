"""
MCP prompts & actions server application.

Creates a ``FastMCP`` instance that exposes prompt management tools
(``prompts_list``, ``prompts_get``, ``prompts_create``, ``prompts_update``)
and an ephemeral LLM action tool (``temp_llm_action``) over the
streamable-HTTP transport.

Authentication and rate limiting are handled by the same Starlette
middleware used by the web-search MCP server in ``mcp_app.py``.

Entry point: ``create_prompts_actions_mcp_app(jwt_secret, rate_limit)``
returns a Starlette ``ASGIApp`` ready to be run with uvicorn.

Environment variables
---------------------
PROMPTS_MCP_ENABLED : str
    Set to ``"false"`` to skip startup (default ``"true"``).
PROMPTS_MCP_PORT : str
    Port for this MCP server (default ``"8105"``).
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
from starlette.types import ASGIApp

from mcp_server.mcp_app import JWTAuthMiddleware, RateLimitMiddleware

logger = logging.getLogger(__name__)

FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))


# ---------------------------------------------------------------------------
# Health-check endpoint
# ---------------------------------------------------------------------------


async def _health_check(request: Request) -> JSONResponse:
    """Simple health-check endpoint for load-balancers."""
    return JSONResponse({"status": "ok", "server": "prompts-actions"})


# ---------------------------------------------------------------------------
# Prompt-storage helpers (direct Python calls — no HTTP round-trip)
# ---------------------------------------------------------------------------


def _get_prompt_manager():
    """Return the global ``WrappedManager`` from the prompts module.

    The prompts module creates a singleton ``manager`` backed by
    ``prompts.json``.  We import lazily so the MCP server process
    does not need to import Flask or heavy deps at module load time.

    Returns
    -------
    prompt_lib.wrapped_manager.WrappedManager
        The project-wide prompt manager instance.
    """
    from prompts import manager
    return manager


def _get_prompt_cache() -> dict:
    """Return the global prompt cache dict from the prompts module."""
    from prompts import prompt_cache
    return prompt_cache


# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_prompts_actions_mcp_app(
    jwt_secret: str, rate_limit: int = 10
) -> tuple[ASGIApp, Any]:
    """Create the MCP prompts & actions server as an ASGI application.

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
        "Prompts & Actions Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool 1 (baseline): prompts_list
    # -----------------------------------------------------------------

    @mcp.tool()
    def prompts_list(user_email: str) -> str:
        """List all saved prompts with metadata.

        Returns a JSON array of objects, each with keys:
        ``name``, ``description``, ``category``, ``tags``.

        Args:
            user_email: Email of the requesting user (for audit logging).
        """
        try:
            manager = _get_prompt_manager()
            prompt_names = manager.keys()
            results: list[dict] = []
            for name in prompt_names:
                try:
                    raw = manager.get_raw(name, as_dict=True)
                    results.append({
                        "name": name,
                        "description": raw.get("description", ""),
                        "category": raw.get("category", ""),
                        "tags": raw.get("tags", []),
                    })
                except Exception:
                    results.append({
                        "name": name,
                        "description": "",
                        "category": "",
                        "tags": [],
                    })
            logger.info("prompts_list: %d prompts for user=%s", len(results), user_email)
            return json.dumps(results)
        except Exception as exc:
            logger.exception("prompts_list error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 2 (baseline): prompts_get
    # -----------------------------------------------------------------

    @mcp.tool()
    def prompts_get(user_email: str, name: str) -> str:
        """Get a specific prompt by name, including its content and metadata.

        Returns a JSON object with keys:
        ``name``, ``content``, ``metadata`` (description, category, tags, version).

        Args:
            user_email: Email of the requesting user (for audit logging).
            name: The exact name of the prompt to retrieve.
        """
        try:
            manager = _get_prompt_manager()
            if name not in manager:
                return json.dumps({"error": f"Prompt '{name}' not found"})

            content = manager[name]
            try:
                raw = manager.get_raw(name, as_dict=True)
                metadata = {
                    "description": raw.get("description", ""),
                    "category": raw.get("category", ""),
                    "tags": raw.get("tags", []),
                    "version": raw.get("version", ""),
                    "created_at": raw.get("created_at", ""),
                    "updated_at": raw.get("last_modified", ""),
                }
            except Exception:
                metadata = {}

            logger.info("prompts_get: name=%s user=%s", name, user_email)
            return json.dumps({"name": name, "content": content, "metadata": metadata})
        except Exception as exc:
            logger.exception("prompts_get error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 3 (baseline): temp_llm_action
    # -----------------------------------------------------------------

    @mcp.tool()
    def temp_llm_action(
        user_email: str,
        action_type: str,
        selected_text: str,
        conversation_id: Optional[str] = None,
        user_message: Optional[str] = None,
    ) -> str:
        """Run an ephemeral LLM action on selected text.

        Supported action types: explain, critique, expand, eli5, ask_temp.

        The tool calls the Flask streaming endpoint internally and
        collects all response chunks into a single string.

        Args:
            user_email: Email of the requesting user (for audit logging).
            action_type: One of: explain, critique, expand, eli5, ask_temp.
            selected_text: The text to operate on.
            conversation_id: Optional conversation ID for context.
            user_message: Optional user prompt (used with ask_temp).
        """
        import requests as http_requests

        valid_actions = {"explain", "critique", "expand", "eli5", "ask_temp"}
        if action_type not in valid_actions:
            return f"Invalid action_type '{action_type}'. Must be one of: {', '.join(sorted(valid_actions))}"

        if not selected_text or not selected_text.strip():
            return "Error: selected_text is required and must not be empty."

        payload: dict[str, Any] = {
            "action_type": action_type,
            "selected_text": selected_text,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if user_message:
            payload["user_message"] = user_message

        logger.info(
            "temp_llm_action: action=%s user=%s conv=%s",
            action_type, user_email, conversation_id,
        )

        try:
            response = http_requests.post(
                f"http://localhost:{FLASK_PORT}/temporary_llm_action",
                json=payload,
                stream=True,
                timeout=120,
            )
            response.raise_for_status()

            result_parts: list[str] = []
            for line in response.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        text = chunk.get("text", "")
                        if text:
                            result_parts.append(text)
                        # Check for error in chunk
                        if chunk.get("error"):
                            error_status = chunk.get("status", "Unknown error")
                            if error_status and not result_parts:
                                return f"Error: {error_status}"
                    except json.JSONDecodeError:
                        # Non-JSON line — skip
                        continue

            if not result_parts:
                return "No response generated."
            return "".join(result_parts)

        except http_requests.exceptions.ConnectionError:
            return (
                f"Error: Could not connect to Flask server at localhost:{FLASK_PORT}. "
                "Is the main server running?"
            )
        except http_requests.exceptions.Timeout:
            return "Error: Request timed out (120s). The LLM action took too long."
        except http_requests.exceptions.HTTPError as exc:
            return f"Error: HTTP {exc.response.status_code} from Flask server."
        except Exception as exc:
            logger.exception("temp_llm_action error: %s", exc)
            return f"Error: {exc}"

    # -----------------------------------------------------------------
    # Tool 4 (full tier): prompts_create
    # -----------------------------------------------------------------

    @mcp.tool()
    def prompts_create(
        user_email: str,
        name: str,
        content: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> str:
        """Create a new prompt.

        Stores a prompt with the given name and content.  If a prompt
        with the same name already exists an error is returned.

        Args:
            user_email: Email of the requesting user (for audit logging).
            name: Unique name for the new prompt.
            content: The prompt text / template.
            description: Optional human-readable description.
            category: Optional category string.
            tags: Optional comma-separated tags (e.g. "coding,research").
        """
        try:
            manager = _get_prompt_manager()
            prompt_cache = _get_prompt_cache()

            if name in manager:
                return json.dumps({"error": f"Prompt '{name}' already exists. Use prompts_update to modify."})

            manager[name] = content
            prompt_cache[name] = content

            # Apply optional metadata
            edit_kwargs: dict[str, Any] = {}
            if description is not None:
                edit_kwargs["description"] = description
            if category is not None:
                edit_kwargs["category"] = category
            if tags is not None:
                edit_kwargs["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            if edit_kwargs:
                try:
                    manager.edit(name, **edit_kwargs)
                except Exception as e:
                    logger.warning("Could not set metadata for prompt '%s': %s", name, e)

            logger.info("prompts_create: name=%s user=%s", name, user_email)
            return json.dumps({"success": True, "name": name})
        except Exception as exc:
            logger.exception("prompts_create error: %s", exc)
            return json.dumps({"error": str(exc)})

    # -----------------------------------------------------------------
    # Tool 5 (full tier): prompts_update
    # -----------------------------------------------------------------

    @mcp.tool()
    def prompts_update(
        user_email: str,
        name: str,
        content: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> str:
        """Update an existing prompt's content and metadata.

        The prompt must already exist — use ``prompts_create`` for new
        prompts.

        Args:
            user_email: Email of the requesting user (for audit logging).
            name: Name of the prompt to update.
            content: New prompt text / template.
            description: Optional new description.
            category: Optional new category string.
            tags: Optional comma-separated tags (e.g. "coding,research").
        """
        try:
            manager = _get_prompt_manager()
            prompt_cache = _get_prompt_cache()

            if name not in manager:
                return json.dumps({"error": f"Prompt '{name}' not found. Use prompts_create to add."})

            manager[name] = content
            prompt_cache[name] = content

            # Apply optional metadata
            edit_kwargs: dict[str, Any] = {}
            if description is not None:
                edit_kwargs["description"] = description
            if category is not None:
                edit_kwargs["category"] = category
            if tags is not None:
                edit_kwargs["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            if edit_kwargs:
                try:
                    manager.edit(name, **edit_kwargs)
                except Exception as e:
                    logger.warning("Could not update metadata for prompt '%s': %s", name, e)

            logger.info("prompts_update: name=%s user=%s", name, user_email)
            return json.dumps({"success": True, "name": name})
        except Exception as exc:
            logger.exception("prompts_update error: %s", exc)
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
# Convenience launcher: start in a daemon thread
# ---------------------------------------------------------------------------


def start_prompts_actions_mcp_server() -> None:
    """Start the Prompts & Actions MCP server in a daemon thread.

    Reads configuration from environment variables:

    - ``PROMPTS_MCP_ENABLED`` — set to ``"false"`` to skip (default ``"true"``).
    - ``PROMPTS_MCP_PORT`` — port number (default ``"8105"``).
    - ``MCP_JWT_SECRET`` — HS256 secret (required, shared with web-search MCP).
    - ``MCP_RATE_LIMIT`` — max calls per token per minute (default ``"10"``).

    Does nothing if ``PROMPTS_MCP_ENABLED=false`` or ``MCP_JWT_SECRET`` is
    not set.  The thread is a daemon so it exits when the main Flask process
    terminates.
    """
    if os.getenv("PROMPTS_MCP_ENABLED", "true").lower() == "false":
        logger.info("Prompts MCP server disabled (PROMPTS_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — Prompts MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the Prompts & Actions MCP server."
        )
        return

    port = int(os.getenv("PROMPTS_MCP_PORT", "8105"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_prompts_actions_mcp_app(
                jwt_secret=jwt_secret, rate_limit=rate_limit
            )
            logger.info("Prompts MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("Prompts MCP server failed to start")

    thread = threading.Thread(
        target=_run, name="prompts-mcp-server", daemon=True
    )
    thread.start()
    logger.info(
        "Prompts MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )