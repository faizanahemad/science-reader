"""
MCP server package.

Exposes ``start_mcp_server()`` for the web search MCP server and
``start_*_mcp_server()`` helpers for six domain-specific MCP servers.
All run as daemon threads alongside the main Flask application.

Servers
-------
Web Search   (port 8100)  — ``start_mcp_server()``
PKB          (port 8101)  — ``start_pkb_mcp_server()``
Documents    (port 8102)  — ``start_docs_mcp_server()``
Artefacts    (port 8103)  — ``start_artefacts_mcp_server()``
Conversation (port 8104)  — ``start_conversation_mcp_server()``
Prompts      (port 8105)  — ``start_prompts_actions_mcp_server()``
Code Runner  (port 8106)  — ``start_code_runner_mcp_server()``
Environment variables
---------------------
MCP_ENABLED : str
    Set to ``"false"`` to skip web search MCP startup (default ``"true"``).
MCP_JWT_SECRET : str
    **Required.** HS256 secret for bearer-token verification.  Shared by all servers.
MCP_PORT : str
    Port for the web search MCP server (default ``8100``).
MCP_RATE_LIMIT : str
    Max tool calls per token per minute (default ``10``).  Shared by all servers.
MCP_TOOL_TIER : str
    Tool tier: ``"baseline"`` (default, ~25 tools) or ``"full"`` (~40 tools).
PKB_MCP_ENABLED, PKB_MCP_PORT : str
    Enable/port for PKB MCP (defaults ``"true"`` / ``8101``).
DOCS_MCP_ENABLED, DOCS_MCP_PORT : str
    Enable/port for Documents MCP (defaults ``"true"`` / ``8102``).
ARTEFACTS_MCP_ENABLED, ARTEFACTS_MCP_PORT : str
    Enable/port for Artefacts MCP (defaults ``"true"`` / ``8103``).
CONVERSATION_MCP_ENABLED, CONVERSATION_MCP_PORT : str
    Enable/port for Conversation MCP (defaults ``"true"`` / ``8104``).
PROMPTS_MCP_ENABLED, PROMPTS_MCP_PORT : str
    Enable/port for Prompts/Actions MCP (defaults ``"true"`` / ``8105``).
CODE_RUNNER_MCP_ENABLED, CODE_RUNNER_MCP_PORT : str
    Enable/port for Code Runner MCP (defaults ``"true"`` / ``8106``).
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)


def start_mcp_server() -> None:
    """Start the MCP web search server in a daemon thread.

    Reads configuration from environment variables (see module docstring).
    Does nothing if ``MCP_ENABLED=false`` or ``MCP_JWT_SECRET`` is not set.
    The thread is a daemon so it exits automatically when the main process
    (Flask) terminates.
    """
    if os.getenv("MCP_ENABLED", "true").lower() == "false":
        logger.info("MCP server disabled (MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the MCP web search server."
        )
        return

    port = int(os.getenv("MCP_PORT", "8100"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            from mcp_server.mcp_app import create_mcp_app

            app, _mcp = create_mcp_app(jwt_secret=jwt_secret, rate_limit=rate_limit)
            logger.info("MCP web search server starting on port %d", port)
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("MCP server failed to start")

    thread = threading.Thread(target=_run, name="mcp-server", daemon=True)
    thread.start()
    logger.info(
        "MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )


# ---------------------------------------------------------------------------
# Domain-specific MCP servers (imported from sub-modules)
# ---------------------------------------------------------------------------

from mcp_server.pkb import start_pkb_mcp_server
from mcp_server.docs import start_docs_mcp_server
from mcp_server.artefacts import start_artefacts_mcp_server
from mcp_server.conversation import start_conversation_mcp_server
from mcp_server.prompts_actions import start_prompts_actions_mcp_server
from mcp_server.code_runner_mcp import start_code_runner_mcp_server

__all__ = [
    "start_mcp_server",
    "start_pkb_mcp_server",
    "start_docs_mcp_server",
    "start_artefacts_mcp_server",
    "start_conversation_mcp_server",
    "start_prompts_actions_mcp_server",
    "start_code_runner_mcp_server",
]
