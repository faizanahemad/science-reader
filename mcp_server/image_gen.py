"""
MCP image generation server application.

Creates a ``FastMCP`` instance that exposes an image-generation tool
over the streamable-HTTP transport.  The tool wraps
``endpoints.image_gen.generate_image_from_prompt`` so that MCP clients
can generate (or edit) images via OpenRouter image-capable models.

Authentication and rate limiting are handled by Starlette middleware
imported from ``mcp_server.mcp_app`` (same JWT + rate-limit stack used by
the web-search MCP server).

Entry point: ``create_image_gen_mcp_app(jwt_secret, rate_limit)`` returns a
Starlette ``ASGIApp`` ready to be run with uvicorn.

Environment variables
---------------------
IMAGE_GEN_MCP_ENABLED : str
    Set to ``"false"`` to skip startup (default ``"true"``).
IMAGE_GEN_MCP_PORT : str
    Port for the image generation MCP server (default ``8107``).
MCP_JWT_SECRET : str
    **Required.** HS256 secret for bearer-token verification.
MCP_RATE_LIMIT : str
    Max tool calls per token per minute (default ``10``).
"""

from __future__ import annotations

import contextlib
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


# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_image_gen_mcp_app(
    jwt_secret: str, rate_limit: int = 10
) -> tuple[ASGIApp, Any]:
    """Create the MCP image generation server as an ASGI application.

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
        "Image Generation Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool 1: generate_image
    # -----------------------------------------------------------------

    @mcp.tool()
    def generate_image(
        prompt: str,
        model: str = "google/gemini-3.1-flash-image-preview",
        input_image: str | None = None,
    ) -> str:
        """Generate an image from a text prompt using OpenRouter image-capable models.

        Returns a JSON object with ``images`` (list of data-URI strings),
        ``text`` (any textual response from the model), and ``error``
        (null on success, descriptive string on failure).

        Optionally provide ``input_image`` as a base64 data URI to perform
        image editing rather than pure generation.

        Args:
            prompt: The image description or edit instruction.
            model: OpenRouter model ID (default: google/gemini-3.1-flash-image-preview).
            input_image: Optional base64 data URI of an existing image to edit/transform.
        """
        try:
            from endpoints.image_gen import generate_image_from_prompt

            keys = _get_keys()
            result = generate_image_from_prompt(
                prompt,
                keys,
                model=model,
                input_image=input_image,
            )
            if isinstance(result, (dict, list)):
                return json.dumps(result)
            return str(result)
        except Exception as exc:
            logger.exception("generate_image tool error: %s", exc)
            return json.dumps(
                {"images": [], "text": "", "error": f"Image generation failed: {exc}"}
            )

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


def start_image_gen_mcp_server() -> None:
    """Start the MCP image generation server in a daemon thread.

    Reads configuration from environment variables (see module docstring).
    Does nothing if ``IMAGE_GEN_MCP_ENABLED=false`` or ``MCP_JWT_SECRET`` is not
    set.  The thread is a daemon so it exits automatically when the main
    process (Flask) terminates.
    """
    if os.getenv("IMAGE_GEN_MCP_ENABLED", "true").lower() == "false":
        logger.info("Image Gen MCP server disabled (IMAGE_GEN_MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning(
            "MCP_JWT_SECRET not set — Image Gen MCP server will not start. "
            "Set MCP_JWT_SECRET to enable the MCP image generation server."
        )
        return

    port = int(os.getenv("IMAGE_GEN_MCP_PORT", "8107"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn

            app, _mcp = create_image_gen_mcp_app(
                jwt_secret=jwt_secret, rate_limit=rate_limit
            )
            logger.info("Image Gen MCP server starting on port %d", port)
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=port,
                log_level="info",
            )
        except Exception:
            logger.exception("Image Gen MCP server failed to start")

    thread = threading.Thread(target=_run, name="image-gen-mcp-server", daemon=True)
    thread.start()
    logger.info(
        "Image Gen MCP server thread started (port=%d, rate_limit=%d/min)",
        port,
        rate_limit,
    )
