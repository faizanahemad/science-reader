"""
MCP web search server application.

Creates a ``FastMCP`` instance that exposes search-agent tools
(``perplexity_search``, ``jina_search``, ``deep_search``) and page-reader
tools (``jina_read_page``, ``read_link``) over the streamable-HTTP
transport.

Authentication and rate limiting are handled by Starlette middleware
that wraps the ASGI app returned by ``FastMCP.streamable_http_app()``.
This avoids coupling to the MCP SDK's OAuth-oriented auth system and
keeps the bearer-token flow simple.

Entry point: ``create_mcp_app(jwt_secret, rate_limit)`` returns a
Starlette ``ASGIApp`` ready to be run with uvicorn.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_server.auth import verify_jwt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Starlette middleware — JWT authentication
# ---------------------------------------------------------------------------


class JWTAuthMiddleware:
    """ASGI middleware that enforces JWT bearer-token authentication.

    Every incoming request must carry an ``Authorization: Bearer <jwt>``
    header.  The token is verified against the configured HS256 secret.
    Requests without a valid token receive a ``401 Unauthorized`` JSON
    response.

    Health-check probes (``GET /health``) are exempted so load-balancers
    and monitoring can reach the server without credentials.

    Parameters
    ----------
    app:
        The next ASGI application in the middleware chain.
    jwt_secret:
        HS256 signing secret used by :func:`mcp_server.auth.verify_jwt`.
    """

    def __init__(self, app: ASGIApp, jwt_secret: str) -> None:
        self.app = app
        self.jwt_secret = jwt_secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Allow health checks without auth
        path = scope.get("path", "")
        if path == "/health":
            await self.app(scope, receive, send)
            return

        # Extract bearer token
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode(
            "utf-8", errors="ignore"
        )

        if not auth_header.startswith("Bearer "):
            response = JSONResponse(
                {
                    "error": "Missing or malformed Authorization header. Expected: Bearer <token>"
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        token = auth_header[7:]  # strip "Bearer "
        payload = verify_jwt(token, self.jwt_secret)
        if payload is None:
            response = JSONResponse(
                {"error": "Invalid or expired bearer token."},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        # Attach client info to scope for downstream logging
        scope["mcp_client_email"] = payload.get("email", "unknown")
        scope["mcp_client_scopes"] = payload.get("scopes", [])

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Starlette middleware — per-token rate limiting
# ---------------------------------------------------------------------------


class RateLimitMiddleware:
    """ASGI middleware implementing per-token token-bucket rate limiting.

    Each unique bearer token gets its own bucket.  Tokens refill
    linearly over the configured window.  Requests that exceed the
    limit receive ``429 Too Many Requests``.

    Parameters
    ----------
    app:
        The next ASGI application in the middleware chain.
    rate:
        Maximum number of requests per window (default 10).
    window:
        Window duration in seconds (default 60).
    """

    def __init__(self, app: ASGIApp, rate: int = 10, window: int = 60) -> None:
        self.app = app
        self.rate = rate
        self.window = window
        # bucket_key -> (tokens_remaining, last_refill_timestamp)
        self._buckets: dict[str, tuple[float, float]] = {}

    def _bucket_key(self, scope: Scope) -> str:
        """Derive a rate-limit key from the request.

        Uses the first 20 characters of the bearer token so that each
        client has an independent bucket.  Falls back to the client IP.
        """
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
        if auth.startswith("Bearer ") and len(auth) > 27:
            return auth[7:27]
        # Fallback to client IP
        client = scope.get("client")
        return client[0] if client else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        key = self._bucket_key(scope)
        now = time.time()

        tokens, last = self._buckets.get(key, (float(self.rate), now))
        elapsed = now - last
        # Refill tokens proportionally to elapsed time
        tokens = min(self.rate, tokens + (elapsed / self.window) * self.rate)

        if tokens < 1.0:
            response = JSONResponse(
                {"error": "Rate limit exceeded. Try again later."},
                status_code=429,
                headers={"Retry-After": str(self.window)},
            )
            await response(scope, receive, send)
            return

        self._buckets[key] = (tokens - 1.0, now)
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Health-check endpoint
# ---------------------------------------------------------------------------


async def _health_check(request: Request) -> JSONResponse:
    """Simple health-check endpoint for load-balancers."""
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Agent helpers (key loading, model resolution, output collection)
# ---------------------------------------------------------------------------

_keys_cache: dict[str, Any] | None = None


def _get_keys() -> dict[str, Any]:
    """Load API keys from environment variables (cached after first call).

    Uses the existing ``keyParser({})`` with an empty session dict so that
    only environment variables are consulted — no Flask session.
    """
    global _keys_cache
    if _keys_cache is None:
        from endpoints.utils import keyParser

        _keys_cache = keyParser({})
    return _keys_cache


def _resolve_model(model_name: str) -> str:
    """Resolve the sentinel value ``"default"`` to a concrete model name.

    Falls back to ``CHEAP_LLM[0]`` which is configured in ``common.py``.
    """
    if model_name == "default" or not model_name:
        from common import CHEAP_LLM

        return CHEAP_LLM[0]
    return model_name


def _collect_agent_output(agent: Any, query: str) -> str:
    """Run an agent generator to completion and return concatenated text.

    Agents yield dicts with a ``"text"`` key.  We collect all chunks and
    join them.  Any exception is caught and returned as a user-facing
    error string (the MCP tool never raises — it always returns text).

    Parameters
    ----------
    agent:
        An instantiated search agent (callable, returns a generator).
    query:
        The user's search query.

    Returns
    -------
    str
        Concatenated result text, or an error message on failure.
    """
    result_parts: list[str] = []
    try:
        for chunk in agent(query, stream=True):
            text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            if text:
                result_parts.append(text)
    except Exception as exc:
        logger.exception("Agent execution error: %s", exc)
        return f"Search failed: {exc}"
    return "".join(result_parts)


# ---------------------------------------------------------------------------
# Factory: build the complete ASGI application
# ---------------------------------------------------------------------------


def create_mcp_app(jwt_secret: str, rate_limit: int = 10) -> tuple[ASGIApp, Any]:
    """Create the MCP web search server as an ASGI application.

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
        "Web Search Server",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    # -----------------------------------------------------------------
    # Tool 1: perplexity_search
    # -----------------------------------------------------------------

    @mcp.tool()
    def perplexity_search(
        query: str,
        detail_level: int = 1,
        model_name: str = "default",
    ) -> str:
        """Search using Perplexity AI models (sonar-pro, sonar).

        Higher detail_level (1-4) progressively adds reasoning and
        deep-research models for more thorough results.

        Args:
            query: The search query or question.
            detail_level: Search depth. 1=fast (2 models), 3=+reasoning, 4=+deep-research.
            model_name: LLM model for query generation and combining. Use "default" for auto-selection.
        """
        from agents.search_and_information_agents import PerplexitySearchAgent

        keys = _get_keys()
        model = _resolve_model(model_name)
        agent = PerplexitySearchAgent(
            keys,
            model_name=model,
            detail_level=detail_level,
            timeout=120,
            headless=True,
        )
        return _collect_agent_output(agent, query)

    # -----------------------------------------------------------------
    # Tool 2: jina_search
    # -----------------------------------------------------------------

    @mcp.tool()
    def jina_search(
        query: str,
        detail_level: int = 1,
        model_name: str = "default",
    ) -> str:
        """Search using Jina AI with full web content retrieval.

        Fetches actual page content (not just snippets), summarises
        long pages, and handles PDFs.

        Args:
            query: The search query or question.
            detail_level: Search depth. 1=5 results, 2=8 results, 3+=20 results.
            model_name: LLM model for query generation and combining. Use "default" for auto-selection.
        """
        from agents.search_and_information_agents import JinaSearchAgent

        keys = _get_keys()
        model = _resolve_model(model_name)
        agent = JinaSearchAgent(
            keys,
            model_name=model,
            detail_level=detail_level,
            timeout=240,
            headless=True,
        )
        return _collect_agent_output(agent, query)

    # -----------------------------------------------------------------
    # Tool 3: deep_search
    # -----------------------------------------------------------------

    @mcp.tool()
    def deep_search(
        query: str,
        detail_level: int = 2,
        model_name: str = "default",
        interleave_steps: int = 3,
        sources: str = "web,perplexity,jina",
    ) -> str:
        """Multi-hop iterative search with interleaved search-answer cycles.

        Runs N rounds of: plan queries -> search -> write partial
        answer -> repeat.  Best for complex questions requiring deep
        research across multiple sources.

        Args:
            query: The search query or question.
            detail_level: Search depth passed to sub-agents (1-4).
            model_name: LLM model for answer writing. Use "default" for auto-selection.
            interleave_steps: Number of search-answer cycles (1-5). More steps = deeper but slower.
            sources: Comma-separated list of sources: "web", "perplexity", "jina". Default uses all three.
        """
        from agents.search_and_information_agents import InterleavedWebSearchAgent

        keys = _get_keys()
        model = _resolve_model(model_name)
        source_list = [s.strip() for s in sources.split(",") if s.strip()]
        agent = InterleavedWebSearchAgent(
            keys,
            model_name=model,
            detail_level=detail_level,
            timeout=240,
            interleave_steps=interleave_steps,
            sources=source_list,
            show_intermediate_results=False,
            headless=True,
        )
        return _collect_agent_output(agent, query)

    # -----------------------------------------------------------------
    # Tool 4: jina_read_page
    # -----------------------------------------------------------------

    @mcp.tool()
    def jina_read_page(url: str) -> str:
        """Read a web page using the Jina Reader API.

        Fetches the full content of a URL via Jina's reader endpoint
        (r.jina.ai) and returns it as clean markdown text.  This is a
        lightweight, fast reader suitable for standard web pages.

        For PDFs, images, or links that need heavier processing, use
        the ``read_link`` tool instead.

        Args:
            url: The full URL of the page to read (e.g. "https://example.com/article").
        """
        import requests

        keys = _get_keys()
        jina_key = keys.get("jinaAIKey", "")
        if not jina_key:
            import os

            jina_key = os.environ.get("jinaAIKey", "")
        if not jina_key:
            return "Error: No Jina API key configured. Set the jinaAIKey environment variable."

        reader_url = f"https://r.jina.ai/{url}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {jina_key}",
        }

        try:
            response = requests.get(reader_url, headers=headers, timeout=(20, 90))
            response.raise_for_status()
            data = response.json()
            content = data.get("data", {}).get("content", "")
            title = data.get("data", {}).get("title", "")
            if not content:
                return f"No content extracted from {url}"
            result_parts = []
            if title:
                result_parts.append(f"# {title}\n")
            result_parts.append(content)
            return "\n".join(result_parts)
        except requests.exceptions.Timeout:
            return f"Error: Request timed out while reading {url}"
        except requests.exceptions.HTTPError as exc:
            return f"Error: HTTP {exc.response.status_code} while reading {url}"
        except Exception as exc:
            logger.exception("jina_read_page error for %s: %s", url, exc)
            return f"Error reading page: {exc}"

    # -----------------------------------------------------------------
    # Tool 5: read_link
    # -----------------------------------------------------------------

    @mcp.tool()
    def read_link(
        url: str,
        context: str = "Read and extract all content from this page.",
        detailed: bool = False,
    ) -> str:
        """Read any link — web page, PDF, or image — and return its text content.

        Uses multiple scraping services and handles different content
        types automatically:

        - **Web pages**: Scraped via ScrapingAnt / BrightData / Jina
          (first success wins).
        - **PDFs**: Downloaded and extracted (with HTML fallback for
          arxiv / openreview / aclanthology).
        - **Images**: OCR + GPT-4 vision captioning.
        - **YouTube**: Transcript extraction via AssemblyAI.

        This is heavier than ``jina_read_page`` but handles a much
        wider range of link types.

        Args:
            url: The full URL to read (web page, PDF, image, or YouTube link).
            context: What you are looking for on this page. Helps focus extraction for images and long documents.
            detailed: If True, uses deeper extraction (more scraping services, longer timeouts). Default False.
        """
        keys = _get_keys()

        try:
            from base import download_link_data

            link_tuple = (url, "", context, keys, "", detailed)
            result = download_link_data(link_tuple, web_search_tmp_marker_name=None)
        except Exception as exc:
            logger.exception("read_link error for %s: %s", url, exc)
            return f"Error reading link: {exc}"

        if result.get("exception"):
            return f"Error reading link: {result.get('error', 'unknown error')}"

        # Prefer full_text (raw content), fall back to text (processed).
        content = result.get("full_text", "") or result.get("text", "")
        if not content or not content.strip():
            return f"No content extracted from {url}"

        title = result.get("title", "")
        is_pdf = result.get("is_pdf", False)
        is_image = result.get("is_image", False)
        partial = result.get("partial", False)

        parts = []
        # Header with metadata
        if title:
            parts.append(f"# {title}\n")
        type_label = "PDF" if is_pdf else "Image" if is_image else "Web page"
        meta = f"**Source**: {url} ({type_label})"
        if partial:
            meta += f" — ⚠ partial content ({result.get('error', 'unknown')})"
        parts.append(meta + "\n")
        parts.append(content)
        return "\n".join(parts)

    # -----------------------------------------------------------------
    # Build the Starlette ASGI app with middleware layers
    # -----------------------------------------------------------------

    # The MCP SDK requires the session manager lifecycle to be managed
    # explicitly when using streamable_http_app() (as opposed to run()).
    # We create a Starlette wrapper with a lifespan that starts/stops
    # the session manager, then mount the MCP sub-app inside it.

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
