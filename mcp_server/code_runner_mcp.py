"""
MCP code runner server application.

Creates a ``FastMCP`` instance that exposes a single Python code
execution tool (``run_python_code``) over the streamable-HTTP transport.

Authentication and rate limiting are handled by the same Starlette
middleware used by the web-search MCP server (``mcp_app.py``).

Entry point: ``create_code_runner_mcp_app(jwt_secret, rate_limit)``
returns a Starlette ``ASGIApp`` ready to be run with uvicorn.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from mcp_server.mcp_app import (
    JWTAuthMiddleware,
    RateLimitMiddleware,
    _health_check,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_code_runner_mcp_app(
    jwt_secret: str, rate_limit: int = 10
) -> tuple[ASGIApp, "FastMCP"]:
    """Create the MCP code runner server as an ASGI application.

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
        "Code Runner Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool: run_python_code
    # -----------------------------------------------------------------

    @mcp.tool()
    def run_python_code(user_email: str, code_string: str) -> str:
        """Run Python code in the project's IPython environment.

        Executes code in a sandboxed Python environment with access to
        project-installed libraries (pandas, numpy, scikit-learn, matplotlib, etc.).

        This differs from OpenCode's built-in bash tool:
        - Runs inside the project's conda environment (science-reader)
        - Has access to all project-installed packages
        - Uses IPython with persistent state across calls
        - Output is cleaned and formatted for readability
        - 120-second timeout

        Args:
            user_email: Email of the requesting user.
            code_string: Python code to execute. Can be multi-line.

        Returns:
            Formatted execution output (stdout, stderr, success/failure indicator).
        """
        try:
            from code_runner import run_code_once

            logger.info(
                "run_python_code called by %s (code length=%d)",
                user_email,
                len(code_string) if code_string else 0,
            )
            result = run_code_once(code_string)
            # run_code_once returns a formatted markdown string directly
            return result if isinstance(result, str) else str(result)
        except Exception as exc:
            logger.exception("run_python_code error: %s", exc)
            return f"Code execution failed: {exc}"

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
# Daemon-thread launcher (mirrors mcp_server/__init__.py pattern)
# ---------------------------------------------------------------------------


def start_code_runner_mcp_server() -> None:
    """Start the MCP code runner server in a daemon thread.

    Reads configuration from environment variables:
    - ``CODE_RUNNER_MCP_ENABLED``: set to ``"false"`` to skip (default ``"true"``)
    - ``CODE_RUNNER_MCP_PORT``: port number (default ``8106``)
    - ``MCP_JWT_SECRET``: HS256 secret for bearer-token verification (required)
    - ``MCP_RATE_LIMIT``: max tool calls per token per minute (default ``10``)

    Does nothing if disabled or if ``MCP_JWT_SECRET`` is not set.
    The thread is a daemon so it exits automatically when the main process
    (Flask) terminates.
    """
    if os.getenv("CODE_RUNNER_MCP_ENABLED", "true").lower() == "false":
        logger.info("Code Runner MCP server disabled (CODE_RUNNER_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — Code Runner MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the Code Runner MCP server."
        )
        return

    port = int(os.getenv("CODE_RUNNER_MCP_PORT", "8106"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_code_runner_mcp_app(
                jwt_secret=jwt_secret, rate_limit=rate_limit
            )
            logger.info("Code Runner MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("Code Runner MCP server failed to start")

    thread = threading.Thread(
        target=_run, name="code-runner-mcp-server", daemon=True
    )
    thread.start()
    logger.info(
        "Code Runner MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )
