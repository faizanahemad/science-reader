# MCP Web Search Server

**Created:** 2026-02-21
**Status:** Implemented
**Depends On:** Search agents (`agents/search_and_information_agents.py`), Flask server (`server.py`), API key loading (`endpoints/utils.py`)
**Related Docs:**
- `documentation/features/web_search/` — web search implementation notes
- `agents/search_and_information_agents.py` — agent source (PerplexitySearchAgent, JinaSearchAgent, InterleavedWebSearchAgent)
- `agents/base_agent.py` — Agent base class
- `endpoints/utils.py` — `keyParser()` function for API key resolution
- `extensions.py` — Flask-Limiter rate limiting pattern

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals](#goals)
3. [Non-Goals](#non-goals)
4. [Requirements](#requirements)
5. [Current State](#current-state)
6. [Design Overview](#design-overview)
7. [Authentication](#authentication)
8. [Rate Limiting](#rate-limiting)
9. [MCP Tools (3 Search Agents)](#mcp-tools-3-search-agents)
10. [API Key Loading](#api-key-loading)
11. [Integration with server.py](#integration-with-serverpy)
12. [Nginx Configuration](#nginx-configuration)
13. [Client Configuration](#client-configuration)
14. [File Structure](#file-structure)
15. [Implementation Plan (Milestones)](#implementation-plan-milestones)
16. [Files to Create/Modify (Summary)](#files-to-createmodify-summary)
17. [Testing Plan](#testing-plan)
18. [Risks and Mitigations](#risks-and-mitigations)
19. [Alternatives Considered](#alternatives-considered)

---

## Problem Statement

The project has powerful web search agents (`PerplexitySearchAgent`, `JinaSearchAgent`, `InterleavedWebSearchAgent`) that are only accessible through the Flask-based conversational UI. There is no way to invoke these agents from external coding tools like OpenCode or Claude Code.

**What we need:**

- An MCP (Model Context Protocol) server that exposes 3 web search agents as MCP tools.
- Bearer token authentication so the server can be hosted on the internet securely.
- Rate limiting to prevent abuse and DDoS attacks, consistent with existing Flask server patterns.
- The MCP server must start alongside the existing Flask server when running `python server.py` — no separate entry point.
- Clients (OpenCode, Claude Code) connect with a simple `Authorization: Bearer <token>` header.

---

## Goals

1. **Expose 3 search agents as MCP tools:** PerplexitySearchAgent, JinaSearchAgent, InterleavedWebSearchAgent.
2. **Bearer token authentication:** JWT-based verification server-side; clients just send a static bearer token string.
3. **Rate limiting:** Per-token rate limiting via Starlette middleware, mirroring Flask server patterns.
4. **Single entry point:** Starts from `python server.py` alongside the Flask app (MCP runs on a separate port in a daemon thread).
5. **Remote access:** Served via streamable HTTP transport, accessible through nginx reverse proxy.
6. **Minimal footprint:** Reuse existing `keyParser()` for API key loading — no new key management module.

---

## Non-Goals

- Full OAuth 2.1 flow (no authorization server, no token refresh — just static bearer tokens).
- Exposing all 7+ search agents (only 3 specified).
- Web UI for managing tokens or monitoring MCP usage.
- MCP resources or prompts (tools only).
- Replacing or modifying the existing Flask server behavior.
- Streaming MCP responses (agents stream internally, but MCP tool returns the final collected text).

---

## Requirements

### Functional

- **FR-1:** MCP server exposes `perplexity_search`, `jina_search`, and `deep_search` tools.
- **FR-2:** Each tool accepts a `query` (str), `detail_level` (int, 1-4), and optional `model_name` (str).
- **FR-3:** Server validates bearer token on every request using PyJWT.
- **FR-4:** Invalid/expired/missing tokens return 401 Unauthorized.
- **FR-5:** Rate limiting: configurable per-token limit (default 10 requests/minute).
- **FR-6:** MCP server starts automatically when `python server.py` is run.
- **FR-7:** A CLI utility generates JWT tokens: `python -m mcp_server.auth --email user@example.com --days 365`.

### Non-Functional

- **NFR-1:** MCP server runs on port 8100 (configurable via `MCP_PORT` env var).
- **NFR-2:** Uses stateless HTTP transport (`stateless_http=True`, `json_response=True`) for horizontal scalability.
- **NFR-3:** Agents reuse API keys from environment variables (same as Flask server).
- **NFR-4:** MCP server failure must not crash the Flask server (daemon thread with error handling).
- **NFR-5:** Logging uses the project's existing `logging.getLogger(__name__)` pattern.

### Environment Variables (New)

| Variable | Required | Default | Description |
|---|---|---|---|
| `MCP_JWT_SECRET` | Yes | — | Secret key for JWT signing/verification. Server logs a warning and disables MCP if not set. |
| `MCP_PORT` | No | `8100` | Port for the MCP streamable HTTP server. |
| `MCP_RATE_LIMIT` | No | `10` | Max tool calls per token per minute. |
| `MCP_ENABLED` | No | `true` | Set to `false` to disable MCP server startup. |

### Environment Variables (Existing, Required by Agents)

These are already used by the Flask server and read via `keyParser()`:

| Variable | Used By |
|---|---|
| `OPENROUTER_API_KEY` | All 3 agents (LLM calls via CallLLm) |
| `jinaAIKey` | JinaSearchAgent (Jina search + reader APIs) |
| `openAIKey` | All agents (fallback LLM, embeddings) |
| `googleSearchApiKey` | InterleavedWebSearchAgent (web source sub-agent) |
| `googleSearchCxId` | InterleavedWebSearchAgent (web source sub-agent) |
| `serpApiKey` | InterleavedWebSearchAgent (web source sub-agent) |
| `bingKey` | InterleavedWebSearchAgent (web source sub-agent) |
| `brightdataProxy` | Web scraping in search pipeline |

---

## Current State

### How search agents work today

**Agent base class** (`agents/base_agent.py:41-46`):
```python
class Agent:
    def __init__(self, keys):
        self.keys = keys

    def __call__(self, text, images=[], temperature=0.7, stream=False,
                 max_tokens=None, system=None, web_search=False):
        pass
```

**Agent instantiation pattern** (from `Conversation.py:5093-5112`):
```python
# All agents take: keys dict, model_name str, detail_level int, timeout int
agent = PerplexitySearchAgent(
    self.get_api_keys(),
    model_name=model_name if isinstance(model_name, str) else model_name[0],
    detail_level=kwargs.get("detail_level", 1),
    timeout=90,
)
```

**Agent call pattern** — agents are generators yielding `{"text": str, "status": str}` dicts:
```python
for chunk in agent(text, stream=True):
    result_text += chunk.get("text", "")
```

### Three target agents

**1. PerplexitySearchAgent** (`search_and_information_agents.py:1406`):
```python
class PerplexitySearchAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60,
                 num_queries=5, headless=False, no_intermediate_llm=False):
```
- Extends `WebSearchWithAgent`. Uses Perplexity AI models (`sonar-pro`, `sonar`, optionally `sonar-reasoning`, `sonar-reasoning-pro`, `sonar-deep-research` at higher detail levels).
- Generates diverse query-context pairs, fans them out across multiple Perplexity models in parallel.
- Requires: `OPENROUTER_API_KEY` (for LLM), `openAIKey` (fallback).

**2. JinaSearchAgent** (`search_and_information_agents.py:1560`):
```python
class JinaSearchAgent(PerplexitySearchAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60,
                 num_queries=5, headless=False, no_intermediate_llm=False):
```
- Extends `PerplexitySearchAgent`. Uses Jina AI search API (`s.jina.ai`) and reader API (`r.jina.ai`) to fetch real web content.
- Fetches full content for PDF links, truncates + summarizes long content with a cheap LLM, runs per-query mini-combiner.
- Requires: `jinaAIKey` (asserted in constructor at line 1580), `OPENROUTER_API_KEY`.

**3. InterleavedWebSearchAgent** (`search_and_information_agents.py:2220`):
```python
class InterleavedWebSearchAgent(Agent):
    def __init__(self, keys, model_name, detail_level=2, timeout=90,
                 interleave_steps=3, min_interleave_steps=2,
                 num_queries_per_step=3, sources=None,
                 min_successful_sources=2, show_intermediate_results=False,
                 headless=False, planner_model_name=None,
                 max_sources_chars=60_000):
```
- Extends `Agent` directly (not WebSearchWithAgent). Multi-hop iterative search with N search→answer cycles.
- A planner LLM proposes queries at each step; sub-agents (web/perplexity/jina) fetch results; an answer LLM continues building the response.
- Supports early-stop sentinels, configurable sources/steps.
- Requires: all keys needed by its sub-agents (web, perplexity, jina).

### API key loading today

**`endpoints/utils.py:18-82` — `keyParser(session)`:**
- Reads all API keys from environment variables.
- Merges with Flask session overrides (session takes priority if non-empty).
- For MCP server: call `keyParser({})` with empty dict (no session) → pure env-var lookup.

### Flask server startup

**`server.py:361-375` — `main()`:**
```python
def main(argv=None):
    app = create_app(argv)
    from endpoints.auth import cleanup_tokens
    cleanup_tokens()
    app.run(host="0.0.0.0", port=5000, threaded=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

**Integration point:** Start MCP server in `main()` after `create_app()` and before `app.run()`. The MCP server runs in a daemon thread on its own port so it doesn't block Flask.

---

## Design Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  python server.py                                               │
│                                                                 │
│  ┌──────────────────────┐    ┌────────────────────────────────┐ │
│  │  Flask Server         │    │  MCP Server (daemon thread)    │ │
│  │  Port 5000            │    │  Port 8100                     │ │
│  │                       │    │                                │ │
│  │  Web UI, API          │    │  FastMCP (streamable HTTP)     │ │
│  │  endpoints, auth,     │    │                                │ │
│  │  conversations        │    │  Tools:                        │ │
│  │                       │    │   - perplexity_search          │ │
│  │                       │    │   - jina_search                │ │
│  │                       │    │   - deep_search                │ │
│  │                       │    │                                │ │
│  │                       │    │  Auth: JWT TokenVerifier       │ │
│  │                       │    │  Rate Limit: Starlette MW      │ │
│  └──────────────────────┘    └────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
   Nginx :443/                    Nginx :443/mcp
   (proxy to :5000)               (proxy to :8100)
```

**Key design decisions:**

1. **Daemon thread, not subprocess:** MCP server runs in a daemon thread via `threading.Thread(daemon=True)`. This shares the process and allows direct import of agent classes. Daemon thread dies automatically when the main Flask process exits.

2. **Stateless HTTP transport:** `stateless_http=True` + `json_response=True`. No session state on the server. Each tool call is a self-contained HTTP request. This is the recommended MCP transport for production.

3. **Collected (not streaming) tool responses:** MCP tool functions run the agent generator to completion and return the final concatenated text. MCP protocol supports streaming, but collected responses are simpler and sufficient for search results.

4. **API keys from env vars:** Call `keyParser({})` once at MCP server init. No per-request key resolution. All clients share the server's API keys.

---

## Authentication

### Server-Side: JWT Verification

The MCP server uses the official `mcp` SDK's `TokenVerifier` protocol. We implement a custom `JWTTokenVerifier` that decodes and validates JWT tokens using PyJWT.

**How it works:**

1. Server reads `MCP_JWT_SECRET` from environment at startup.
2. Admin generates a JWT token using the CLI helper (see below).
3. Client includes `Authorization: Bearer <jwt_token>` in requests.
4. `JWTTokenVerifier.verify_token(token)` decodes the JWT, checks signature + expiry.
5. Returns `AccessToken(client_id=email, scopes=["search"])` on success, `None` on failure.
6. MCP SDK automatically returns 401 if `verify_token` returns `None`.

**TokenVerifier implementation** (`mcp_server/auth.py`):
```python
import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

class JWTTokenVerifier(TokenVerifier):
    def __init__(self, secret: str):
        self.secret = secret

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = jwt.decode(token, self.secret, algorithms=["HS256"])
            return AccessToken(
                token=token,
                client_id=payload.get("email", "unknown"),
                scopes=payload.get("scopes", ["search"]),
                expires_at=payload.get("exp"),
            )
        except jwt.InvalidTokenError:
            return None
```

**Token generation CLI** (`python -m mcp_server.auth`):
```python
# Usage: MCP_JWT_SECRET=mysecret python -m mcp_server.auth --email user@example.com --days 365
# Output: eyJhbGciOiJIUzI1NiIs...  (copy this into client config)

import jwt
from datetime import datetime, timedelta, timezone

def generate_token(secret: str, email: str, days: int = 365) -> str:
    payload = {
        "email": email,
        "scopes": ["search"],
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=days),
    }
    return jwt.encode(payload, secret, algorithm="HS256")
```

### Client-Side: Simple Bearer Token

Clients never deal with JWT internals. They receive a pre-generated token string and include it verbatim:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

No OAuth flow, no token refresh, no client registration. Just a static string in client config.

---

## Rate Limiting

### Approach

A Starlette `BaseHTTPMiddleware` that implements per-token token-bucket rate limiting. This mirrors the existing Flask `@limiter.limit()` pattern from `extensions.py` but adapted for ASGI.

**Why Starlette middleware:** The MCP Python SDK uses Starlette internally for streamable HTTP transport. There is no built-in rate limiting in the SDK. Starlette middleware is the idiomatic extension point.

### Implementation (`mcp_server/mcp_app.py`, inside the server module):

```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-token token-bucket rate limiter for MCP tool calls."""

    def __init__(self, app, rate: int = 10, per: int = 60):
        super().__init__(app)
        self.rate = rate       # max requests per period
        self.per = per         # period in seconds
        self.buckets = {}      # token_prefix -> (tokens_remaining, last_refill_time)

    async def dispatch(self, request, call_next):
        auth = request.headers.get("authorization", "")
        # Use first 20 chars of bearer token as bucket key (unique per token, not full token for privacy)
        key = auth[7:27] if auth.startswith("Bearer ") else (request.client.host if request.client else "unknown")

        now = time.time()
        tokens, last = self.buckets.get(key, (self.rate, now))
        elapsed = now - last
        tokens = min(self.rate, tokens + (elapsed / self.per) * self.rate)

        if tokens < 1:
            return JSONResponse(
                {"error": "Rate limit exceeded. Try again later."},
                status_code=429,
                headers={"Retry-After": str(self.per)},
            )

        self.buckets[key] = (tokens - 1, now)
        return await call_next(request)
```

**Configuration:** `MCP_RATE_LIMIT` env var (default 10 requests/minute). Applies to all MCP endpoints uniformly.

**Comparison with Flask server:**
- Flask: `@limiter.limit("10 per minute")` per-endpoint decorators, key = user email or IP.
- MCP: Starlette middleware, key = bearer token prefix, single configurable rate for all tools.

---

## MCP Tools (3 Search Agents)

### Tool Definitions

Each tool follows the same pattern:
1. Load API keys via `keyParser({})`.
2. Instantiate the agent with keys + parameters from the tool arguments.
3. Call the agent and collect all yielded text chunks.
4. Return the concatenated result string.

**Default model:** `OPENROUTER_API_KEY`-backed models. Default model name will be a sensible default from existing agent usage (e.g., from `CHEAP_LLM` or a configured model). Configurable via the `model_name` tool parameter.

### Tool 1: `perplexity_search`

```python
@mcp.tool()
async def perplexity_search(
    query: str,
    detail_level: int = 1,
    model_name: str = "default",
) -> str:
    """Search using Perplexity AI models (sonar-pro, sonar).
    Higher detail_level (1-4) adds reasoning and deep-research models.

    Args:
        query: The search query or question.
        detail_level: Search depth. 1=fast (2 models), 3=+reasoning, 4=+deep-research.
        model_name: LLM model for query generation and combining. Use "default" for auto-selection.
    """
    keys = _get_keys()
    model = _resolve_model(model_name)
    agent = PerplexitySearchAgent(keys, model_name=model, detail_level=detail_level, timeout=90)
    return _collect_agent_output(agent, query)
```

### Tool 2: `jina_search`

```python
@mcp.tool()
async def jina_search(
    query: str,
    detail_level: int = 1,
    model_name: str = "default",
) -> str:
    """Search using Jina AI with full web content retrieval.
    Fetches actual page content (not just snippets), summarizes long pages, handles PDFs.

    Args:
        query: The search query or question.
        detail_level: Search depth. 1=5 results, 2=8 results, 3+=20 results.
        model_name: LLM model for query generation and combining. Use "default" for auto-selection.
    """
    keys = _get_keys()
    model = _resolve_model(model_name)
    agent = JinaSearchAgent(keys, model_name=model, detail_level=detail_level, timeout=120)
    return _collect_agent_output(agent, query)
```

### Tool 3: `deep_search`

```python
@mcp.tool()
async def deep_search(
    query: str,
    detail_level: int = 2,
    model_name: str = "default",
    interleave_steps: int = 3,
    sources: str = "web,perplexity,jina",
) -> str:
    """Multi-hop iterative search with interleaved search-answer cycles.
    Runs N rounds of: plan queries -> search -> write partial answer -> repeat.
    Best for complex questions requiring deep research.

    Args:
        query: The search query or question.
        detail_level: Search depth passed to sub-agents (1-4).
        model_name: LLM model for answer writing. Use "default" for auto-selection.
        interleave_steps: Number of search-answer cycles (1-5). More steps = deeper but slower.
        sources: Comma-separated list of sources: "web", "perplexity", "jina". Default uses all three.
    """
    keys = _get_keys()
    model = _resolve_model(model_name)
    source_list = [s.strip() for s in sources.split(",") if s.strip()]
    agent = InterleavedWebSearchAgent(
        keys, model_name=model, detail_level=detail_level, timeout=120,
        interleave_steps=interleave_steps, sources=source_list,
        show_intermediate_results=False, headless=True,
    )
    return _collect_agent_output(agent, query)
```

### Helper Functions

```python
import os
from endpoints.utils import keyParser
from common import CHEAP_LLM

_keys_cache = None

def _get_keys() -> dict:
    """Load API keys from environment (cached after first call)."""
    global _keys_cache
    if _keys_cache is None:
        _keys_cache = keyParser({})
    return _keys_cache

def _resolve_model(model_name: str) -> str:
    """Resolve 'default' to a sensible LLM model name."""
    if model_name == "default" or not model_name:
        return CHEAP_LLM[0]  # e.g., a fast OpenRouter model
    return model_name

def _collect_agent_output(agent, query: str) -> str:
    """Run agent generator to completion and return concatenated text."""
    result_parts = []
    try:
        for chunk in agent(query, stream=True):
            text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            result_parts.append(text)
    except Exception as e:
        logger.exception(f"Agent execution error: {e}")
        return f"Search failed: {str(e)}"
    return "".join(result_parts)
```

---

## API Key Loading

No separate key management module is needed. The MCP server reuses the existing `keyParser()` function from `endpoints/utils.py`.

**How it works:**

1. `keyParser(session)` reads all API keys from environment variables.
2. If a Flask session is provided, session values override env vars.
3. For the MCP server, we pass an empty dict `{}` as the session — this gives us pure env-var lookup.
4. Keys are cached after the first call (`_keys_cache`) since env vars don't change at runtime.

**Key function reference** (`endpoints/utils.py:18-82`):
```python
def keyParser(session) -> dict[str, Any]:
    keyStore = {
        "openAIKey": os.getenv("openAIKey", ""),
        "jinaAIKey": os.getenv("jinaAIKey", ""),
        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ""),
        "googleSearchApiKey": os.getenv("googleSearchApiKey", ""),
        "googleSearchCxId": os.getenv("googleSearchCxId", ""),
        "serpApiKey": os.getenv("serpApiKey", ""),
        "bingKey": os.getenv("bingKey", ""),
        "brightdataProxy": os.getenv("brightdataProxy", ""),
        # ... 20+ more keys
    }
    # Merge session overrides (empty dict = no overrides = env only)
    for k, v in keyStore.items():
        key = session.get(k, v)
        ...
    return keyStore
```

---

## Integration with server.py

### Approach

The MCP server runs in a **daemon thread** started from `server.py:main()`. This ensures:
- Both servers start from `python server.py`.
- MCP server shares the same process (direct access to agent imports).
- Daemon thread auto-exits when Flask exits (Ctrl+C or process kill).
- MCP server failure doesn't crash Flask (wrapped in try/except).

### Integration point

**`server.py:main()`** — add MCP startup between `create_app()` and `app.run()`:

```python
def main(argv=None):
    app = create_app(argv)
    from endpoints.auth import cleanup_tokens
    cleanup_tokens()

    # --- NEW: Start MCP server in background ---
    from mcp_server import start_mcp_server
    start_mcp_server()
    # --- END NEW ---

    app.run(host="0.0.0.0", port=5000, threaded=True)
    return 0
```

### `start_mcp_server()` implementation (`mcp_server/__init__.py`):

```python
import logging
import os
import threading

logger = logging.getLogger(__name__)

def start_mcp_server():
    """Start the MCP web search server in a daemon thread.

    Reads configuration from environment variables:
    - MCP_ENABLED: set to 'false' to disable (default: 'true')
    - MCP_JWT_SECRET: required JWT secret for auth
    - MCP_PORT: server port (default: 8100)
    - MCP_RATE_LIMIT: requests per minute per token (default: 10)

    Does nothing if MCP_ENABLED=false or MCP_JWT_SECRET is not set.
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

    def _run():
        try:
            from mcp_server.mcp_app import create_mcp_app
            mcp = create_mcp_app(jwt_secret=jwt_secret, rate_limit=rate_limit)
            logger.info(f"MCP web search server starting on port {port}")
            mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
        except Exception:
            logger.exception("MCP server failed to start")

    thread = threading.Thread(target=_run, name="mcp-server", daemon=True)
    thread.start()
    logger.info(f"MCP server thread started (port={port}, rate_limit={rate_limit}/min)")
```

### Safeguards

- **MCP_ENABLED=false:** Completely skips MCP startup. Useful for dev environments without the `mcp` package installed.
- **Missing MCP_JWT_SECRET:** Logs a warning and skips. Server runs normally without MCP.
- **Import errors:** If `mcp` package is not installed, the import inside `_run()` fails gracefully (logged, Flask continues).
- **Runtime errors:** Wrapped in try/except inside the thread. Flask is unaffected.

---

## Nginx Configuration

Add a location block for the MCP server alongside the existing Flask proxy.

**Addition to nginx config** (e.g., `/etc/nginx/sites-available/science-reader`):

```nginx
# Existing Flask proxy
location / {
    proxy_pass http://localhost:5000;
    proxy_read_timeout 300;
    proxy_connect_timeout 300;
    proxy_send_timeout 300;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
}

# NEW: MCP web search server
location /mcp {
    proxy_pass http://localhost:8100;
    proxy_read_timeout 300;
    proxy_connect_timeout 300;
    proxy_send_timeout 300;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
    proxy_cache off;
}
```

**Note:** The MCP SDK serves its streamable HTTP endpoint at `/mcp` by default. The nginx `location /mcp` block forwards directly to the MCP server's root. If the SDK path needs adjusting, the `FastMCP.run()` or Starlette mount path can be configured.

---

## Client Configuration

### OpenCode

**Config file:** `opencode.json` or `.opencode.json` in the project root:

```json
{
  "mcpServers": {
    "web-search": {
      "type": "remote",
      "url": "https://your-domain.com/mcp",
      "headers": {
        "Authorization": "Bearer <your-jwt-token>"
      }
    }
  }
}
```

### Claude Code

**Config file:** `.mcp.json` in the project root, or `~/.claude/claude_desktop_config.json`:

Using `mcp-remote` bridge (most compatible):
```json
{
  "mcpServers": {
    "web-search": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://your-domain.com/mcp",
        "--header",
        "Authorization:Bearer ${MCP_AUTH_TOKEN}"
      ],
      "env": {
        "MCP_AUTH_TOKEN": "<your-jwt-token>"
      }
    }
  }
}
```

Direct streamable HTTP (if supported by the client version):
```json
{
  "mcpServers": {
    "web-search": {
      "type": "url",
      "url": "https://your-domain.com/mcp",
      "headers": {
        "Authorization": "Bearer <your-jwt-token>"
      }
    }
  }
}
```

### Token Generation

Run once to generate a token for each client:
```bash
export MCP_JWT_SECRET=your-secret-here
python -m mcp_server.auth --email yourname@example.com --days 365
```

Output:
```
Generated MCP bearer token (expires: 2027-02-21):
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6In...

Use in client config:
  Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6In...
```

---

## File Structure

```
mcp_server/
├── __init__.py          # start_mcp_server() — thread launcher, env var checks
├── mcp_app.py           # FastMCP app, 3 tool definitions, rate limit middleware, helpers
└── auth.py              # JWTTokenVerifier class + CLI token generator (__main__)
```

**Lines of code estimate:**
- `__init__.py`: ~50 lines
- `mcp_app.py`: ~180 lines
- `auth.py`: ~80 lines
- `server.py` change: ~4 lines

**Total: ~310 lines of new code + 4 lines modified.**

---

## Implementation Plan (Milestones)

### Milestone 1: Auth Module (`mcp_server/auth.py`)

**Goal:** JWT token verification and generation, independent of MCP.

**Tasks:**
1. Create `mcp_server/` directory and `mcp_server/__init__.py` (empty initially).
2. Create `mcp_server/auth.py` with:
   - `JWTTokenVerifier` class implementing `TokenVerifier` protocol.
   - `generate_token(secret, email, days)` function.
   - `__main__` block with argparse for CLI token generation.
3. Test token generation and verification manually:
   - Generate a token: `MCP_JWT_SECRET=test python -m mcp_server.auth --email test@test.com --days 1`
   - Verify the output is a valid JWT decodable with `jwt.decode()`.

**Dependencies:** `PyJWT` package (`pip install PyJWT`).

**Risks:**
- `PyJWT` vs `jwt` package name confusion. Must install `PyJWT`, import as `jwt`. The `jwt` package on PyPI is different and incompatible.

### Milestone 2: MCP App with Tools (`mcp_server/mcp_app.py`)

**Goal:** Working MCP server with 3 search tools, auth, and rate limiting.

**Tasks:**
1. Create `mcp_server/mcp_app.py` with:
   - `create_mcp_app(jwt_secret, rate_limit)` factory function.
   - `RateLimitMiddleware` class (Starlette BaseHTTPMiddleware).
   - `_get_keys()` helper (calls `keyParser({})`).
   - `_resolve_model(model_name)` helper.
   - `_collect_agent_output(agent, query)` helper.
   - 3 tool functions: `perplexity_search`, `jina_search`, `deep_search`.
2. Wire up auth: pass `JWTTokenVerifier` and `AuthSettings` to `FastMCP` constructor.
3. Test locally without Flask integration:
   - Run standalone: `MCP_JWT_SECRET=test python -c "from mcp_server.mcp_app import create_mcp_app; m = create_mcp_app('test', 10); m.run(transport='streamable-http', port=8100)"`
   - Use `curl` or MCP inspector to call tools with a valid bearer token.

**Dependencies:** `mcp[cli]` package (official MCP Python SDK).

**Risks:**
- Agent constructors may fail if required env vars (e.g., `OPENROUTER_API_KEY`) are not set. The `_collect_agent_output` helper catches exceptions and returns an error string.
- `keyParser` imports `Conversation` and `DocIndex` at module level (`endpoints/utils.py:14-15`). If those modules have heavy startup costs, the import inside the daemon thread could be slow. Mitigation: the import happens once and is cached.
- The `mcp` SDK's `AuthSettings` requires `issuer_url` and `resource_server_url` as `AnyHttpUrl`. For local testing use `http://localhost:8100`. For production use the actual domain. This could be an env var (`MCP_SERVER_URL`) or hardcoded to `http://localhost:{port}` since nginx handles the public URL. Need to verify if the SDK validates these URLs against incoming requests or if they're only used for OAuth metadata endpoints (`.well-known/`). If the latter, localhost is fine.

### Milestone 3: Integration with server.py (`mcp_server/__init__.py` + `server.py`)

**Goal:** MCP server starts automatically from `python server.py`.

**Tasks:**
1. Implement `start_mcp_server()` in `mcp_server/__init__.py` (env var checks, thread launch).
2. Add 3 lines to `server.py:main()`:
   ```python
   from mcp_server import start_mcp_server
   start_mcp_server()
   ```
3. Test:
   - `python server.py` starts both Flask (port 5000) and MCP (port 8100).
   - `MCP_ENABLED=false python server.py` starts only Flask.
   - Missing `MCP_JWT_SECRET` logs warning, only Flask starts.
   - MCP server crash doesn't affect Flask.

**Risks:**
- Thread startup ordering: MCP thread starts before `app.run()`. The thread runs `mcp.run()` which calls `uvicorn.run()` internally. This is blocking within the thread but non-blocking for the main thread. Should work, but verify that uvicorn's event loop doesn't conflict with Flask's threading model.
- Port conflicts: if port 8100 is in use, uvicorn will raise an error inside the thread. This is logged and Flask continues.

### Milestone 4: Nginx + Client Config + End-to-End Test

**Goal:** Working remote access from OpenCode or Claude Code.

**Tasks:**
1. Add nginx `/mcp` location block (see [Nginx Configuration](#nginx-configuration)).
2. Reload nginx: `sudo nginx -t && sudo systemctl reload nginx`.
3. Generate a production token: `MCP_JWT_SECRET=<production-secret> python -m mcp_server.auth --email admin@example.com --days 365`.
4. Configure OpenCode or Claude Code client (see [Client Configuration](#client-configuration)).
5. End-to-end test: invoke `perplexity_search` from OpenCode/Claude Code, verify results.

**Risks:**
- Nginx path rewriting: verify that `/mcp` is passed through correctly to the MCP server. The MCP SDK's streamable HTTP endpoint path must match.
- MCP protocol version mismatch between client and server. The `mcp` Python SDK and `mcp-remote` npm package should be compatible, but version pinning is recommended.

---

## Files to Create/Modify (Summary)

### Files to Create

| File | Lines (est.) | Description |
|---|---|---|
| `mcp_server/__init__.py` | ~50 | `start_mcp_server()` — env var checks, daemon thread launcher |
| `mcp_server/mcp_app.py` | ~180 | FastMCP app, 3 tools, rate limit middleware, key/model helpers |
| `mcp_server/auth.py` | ~80 | `JWTTokenVerifier`, `generate_token()`, CLI `__main__` |

### Files to Modify

| File | Change | Lines Changed |
|---|---|---|
| `server.py` | Add `from mcp_server import start_mcp_server; start_mcp_server()` in `main()` | ~4 |

### No Changes Needed

- `agents/search_and_information_agents.py` — agents are used as-is, no modifications.
- `endpoints/utils.py` — `keyParser()` used as-is with empty session dict.
- `extensions.py` — Flask rate limiting unchanged.
- `Conversation.py` — no changes; MCP server imports agents directly.

---

## Testing Plan

### Unit Tests

1. **Token generation and verification:**
   - Generate token with known secret + email + expiry.
   - Verify `JWTTokenVerifier.verify_token()` returns correct `AccessToken`.
   - Verify expired token returns `None`.
   - Verify token signed with wrong secret returns `None`.
   - Verify malformed token returns `None`.

2. **Rate limiting:**
   - Send `rate + 1` requests rapidly; verify last one gets 429.
   - Wait for refill period; verify requests succeed again.
   - Verify different tokens have independent buckets.

### Integration Tests

3. **MCP tool calls (local, no nginx):**
   - Start MCP server standalone on localhost:8100.
   - Call each tool with a valid bearer token using `curl` or MCP inspector.
   - Verify non-empty search results are returned.
   - Verify 401 on missing/invalid token.
   - Verify 429 on rate limit exceeded.

4. **server.py integration:**
   - `python server.py` with `MCP_JWT_SECRET` set: both servers start.
   - `python server.py` without `MCP_JWT_SECRET`: only Flask starts, no error.
   - `MCP_ENABLED=false python server.py`: only Flask starts.
   - Kill Flask (Ctrl+C): MCP thread exits (daemon).

### End-to-End Tests

5. **Remote access via nginx:**
   - Call MCP tools through `https://domain/mcp` with bearer token.
   - Verify results from OpenCode or Claude Code client.

---

## Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| `mcp` package not installed on production server | MCP won't start | Medium | Import inside thread; Flask runs normally. Add to `filtered_requirements.txt`. |
| `PyJWT` not installed | Auth module fails to import | Medium | Add to requirements. Error is clear ("No module named 'jwt'"). |
| Agent requires API keys not set in env | Tool call returns error string | Low | `_collect_agent_output` catches all exceptions and returns friendly error. |
| Port 8100 already in use | MCP server fails to bind | Low | Log error, Flask continues. Configurable via `MCP_PORT`. |
| Heavy module imports slow daemon thread startup | MCP takes a few seconds to become ready | Low | Acceptable. MCP availability is not time-critical. |
| uvicorn event loop conflicts with Flask threads | Unknown behavior | Low | uvicorn runs in its own thread with its own event loop. No shared state. |
| Token leaked in client config file | Unauthorized access | Medium | Tokens are long-lived JWTs; advise users to keep configs private, use env var substitution. Rate limiting bounds damage. |
| Rate limit state in-memory (lost on restart) | Brief window without limits after restart | Low | Acceptable for this scale. Could add Redis storage later. |

---

## Alternatives Considered

### 1. Separate `mcp_server.py` entry point

**Rejected.** User explicitly requires `python server.py` as the single entry point. A separate script would require two processes and complicate deployment.

### 2. Mount MCP as ASGI sub-app inside Flask

**Rejected.** Flask is WSGI, not ASGI. Mixing WSGI (Flask) and ASGI (MCP/Starlette) in the same server requires adapters (e.g., `asgiref.wsgi_to_asgi`) which add complexity and potential bugs. Separate ports via daemon thread is cleaner.

### 3. Full OAuth 2.1 flow

**Rejected.** Overkill for this use case. We need a static bearer token for 1-2 clients, not a multi-tenant auth system. JWT verification gives us cryptographic validation + expiry without the OAuth ceremony.

### 4. Simple string comparison for auth (env var token == bearer token)

**Rejected in favor of JWT.** User explicitly requested JWT with PyJWT. JWT adds expiry, claims (email), and cryptographic verification. Simple comparison would work but lacks these features.

### 5. Expose all 7+ search agents

**Rejected.** User specified only 3: PerplexitySearchAgent, JinaSearchAgent, InterleavedWebSearchAgent. More tools can be added later following the same pattern.

### 6. Streaming MCP tool responses

**Deferred.** The MCP protocol supports streaming tool results, and our agents are generators. However, the initial implementation collects results for simplicity. Streaming can be added later by yielding `TextContent` chunks from the tool function if latency becomes an issue. This is a compatible change — no protocol or client config change needed.

---

## Dependencies to Install

```bash
pip install "mcp[cli]"    # Official MCP Python SDK with CLI tools
pip install PyJWT          # JWT token signing/verification
```

Add to `filtered_requirements.txt`:
```
mcp[cli]
PyJWT
```
