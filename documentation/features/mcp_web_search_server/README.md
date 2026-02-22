# MCP Web Search Server

Expose the project's web search agents (Perplexity, Jina, Interleaved deep search) as MCP tools accessible from external coding assistants like OpenCode and Claude Code, over streamable HTTP with JWT bearer-token authentication and per-token rate limiting. Also exposes page-reader tools (`jina_read_page`, `read_link`) for fetching web page, PDF, and image content.

## Overview

The MCP (Model Context Protocol) web search server runs alongside the existing Flask application inside a daemon thread. It serves search-agent tools and page-reader tools over the streamable-HTTP transport on a separate port (default 8100). External clients connect with a static `Authorization: Bearer <jwt>` header — no OAuth flow, no token refresh.

The server reuses the same search agents and API key loading (`keyParser({})`) as the main Flask app. No new key management or agent code was introduced.

## Architecture

```
python server.py
    |
    +-- Flask Server (port 5000) — web UI, API endpoints, conversations
    |
    +-- MCP Server (port 8100, daemon thread)
            |
            +-- Starlette ASGI app
            |       |
            |       +-- JWTAuthMiddleware (outermost)
            |       +-- RateLimitMiddleware
            |       +-- FastMCP streamable-http app
            |               |
            |               +-- perplexity_search tool
            |               +-- jina_search tool
            |               +-- deep_search tool
            |               +-- jina_read_page tool
            |               +-- read_link tool
            |
            +-- uvicorn (runs inside daemon thread)
```

The MCP server is started from `server.py:main()` via `start_mcp_server()`. It runs in a `threading.Thread(daemon=True)` so it shares the process with Flask (direct agent imports) and auto-exits when the main process terminates.

## MCP Tools

### perplexity_search

Search using Perplexity AI models (sonar-pro, sonar). Higher `detail_level` progressively adds reasoning and deep-research models.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | required | The search query or question |
| `detail_level` | int | 1 | Search depth: 1=fast (2 models), 3=+reasoning, 4=+deep-research |
| `model_name` | str | "default" | LLM model for query generation/combining. "default" uses `CHEAP_LLM[0]` |

Wraps `PerplexitySearchAgent` from `agents/search_and_information_agents.py`.

### jina_search

Search using Jina AI with full web content retrieval. Fetches actual page content, summarises long pages, handles PDFs.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | required | The search query or question |
| `detail_level` | int | 1 | Search depth: 1=5 results, 2=8 results, 3+=20 results |
| `model_name` | str | "default" | LLM model for query generation/combining |

Wraps `JinaSearchAgent` from `agents/search_and_information_agents.py`.

### deep_search

Multi-hop iterative search with interleaved search-answer cycles. Runs N rounds of: plan queries, search, write partial answer, repeat. Best for complex research questions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | required | The search query or question |
| `detail_level` | int | 2 | Search depth passed to sub-agents (1-4) |
| `model_name` | str | "default" | LLM model for answer writing |
| `interleave_steps` | int | 3 | Number of search-answer cycles (1-5) |
| `sources` | str | "web,perplexity,jina" | Comma-separated list of sources to use |

Wraps `InterleavedWebSearchAgent` from `agents/search_and_information_agents.py`.

### jina_read_page

Read a web page using the Jina Reader API (`r.jina.ai`). Returns clean markdown text. Lightweight and fast — suitable for standard web pages. For PDFs, images, or links needing heavier processing, use `read_link`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | str | required | Full URL of the page to read |

Calls the Jina Reader API directly (same endpoint as `JinaSearchAgent.fetch_jina_content`). Requires the `jinaAIKey` environment variable.

### read_link

Read any link — web page, PDF, or image — and return its text content. Handles different content types automatically:

- **Web pages**: Scraped via ScrapingAnt / BrightData / Jina (first success wins).
- **PDFs**: Downloaded and extracted (with HTML fallback for arxiv / openreview / aclanthology).
- **Images**: OCR + GPT-4 vision captioning.
- **YouTube**: Transcript extraction via AssemblyAI.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | str | required | Full URL to read (web page, PDF, image, or YouTube link) |
| `context` | str | "Read and extract all content from this page." | What you are looking for — helps focus extraction for images and long documents |
| `detailed` | bool | False | If True, uses deeper extraction (more scraping services, longer timeouts) |

Wraps `download_link_data` from `base.py`. Requires scraping service API keys (`scrapingant`, `brightdataUrl`, or `jinaAIKey`). Image OCR requires `openAIKey` or `OPENROUTER_API_KEY`. YouTube transcription requires `ASSEMBLYAI_API_KEY`.

## Authentication

JWT bearer tokens verified via Starlette middleware (`JWTAuthMiddleware`). No OAuth flow — clients send a pre-generated static JWT string.

### Token generation

```bash
export MCP_JWT_SECRET=your-secret-here
python -m mcp_server.auth --email user@example.com --days 365
```

Output:
```
Generated MCP bearer token (expires: 2027-02-21):
eyJhbGciOiJIUzI1NiIs...

Use in client config:
  Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### Token format

JWT payload (HS256):
```json
{
  "email": "user@example.com",
  "scopes": ["search"],
  "iat": 1740000000,
  "exp": 1771536000
}
```

### Verification flow

1. `JWTAuthMiddleware` extracts the `Authorization: Bearer <token>` header.
2. `verify_jwt(token, MCP_JWT_SECRET)` decodes with PyJWT, checks signature + expiry.
3. Valid token: request proceeds, `email` and `scopes` attached to ASGI scope.
4. Invalid/missing token: `401 Unauthorized` JSON response.
5. Health-check (`GET /health`) is exempt from auth.

## Rate Limiting

`RateLimitMiddleware` implements per-token token-bucket rate limiting.

- Each unique bearer token gets an independent bucket.
- Tokens refill linearly over the configured window.
- Requests exceeding the limit receive `429 Too Many Requests` with a `Retry-After` header.
- Bucket key: first 20 characters of the bearer token (privacy-safe, unique per client).
- Fallback key for non-bearer requests: client IP.

Configuration: `MCP_RATE_LIMIT` env var (default: 10 requests per 60-second window).

## Environment Variables

### New (MCP-specific)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCP_JWT_SECRET` | Yes | — | HS256 signing secret for JWT verification. MCP server does not start if unset. |
| `MCP_PORT` | No | `8100` | Port for the MCP streamable-HTTP server |
| `MCP_RATE_LIMIT` | No | `10` | Max tool calls per token per minute |
| `MCP_ENABLED` | No | `true` | Set to `false` to disable MCP server entirely |

### Existing (required by search agents)

These are already used by the Flask server and loaded via `keyParser({})`:

| Variable | Used By |
|----------|---------|
| `OPENROUTER_API_KEY` | All 3 agents (LLM calls) |
| `jinaAIKey` | JinaSearchAgent (Jina search + reader APIs) |
| `openAIKey` | All agents (fallback LLM, embeddings) |
| `googleSearchApiKey` | InterleavedWebSearchAgent (web source sub-agent) |
| `googleSearchCxId` | InterleavedWebSearchAgent (web source sub-agent) |
| `serpApiKey` | InterleavedWebSearchAgent (web source sub-agent) |
| `bingKey` | InterleavedWebSearchAgent (web source sub-agent) |
| `brightdataProxy` | Web scraping in search pipeline |

## Client Configuration

### OpenCode

In `opencode.json` (project root) or `~/.config/opencode/opencode.json` (global). OpenCode uses the `"mcp"` key (not `"mcpServers"`).

**Important**: Set `"oauth": false` — without it, OpenCode sees the server's 401 and tries OAuth Dynamic Client Registration, which our JWT-only server doesn't support. This causes OpenCode to mark the MCP as failed/disabled.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "web-search": {
      "type": "remote",
      "url": "http://localhost:8100/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer <your-jwt-token>"
      },
      "enabled": true
    }
  }
}
```

For production behind nginx, change the URL to `"https://your-domain.com/mcp"`.

### Claude Code

Using `mcp-remote` bridge (`.mcp.json`):

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

Direct streamable HTTP (if supported by client version):

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

## Nginx Configuration

Add alongside existing Flask proxy:

```nginx
location /mcp {
    proxy_pass http://localhost:8100/;
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

## Startup Behavior

1. `server.py:main()` calls `start_mcp_server()` after `create_app()` and before `app.run()`.
2. `start_mcp_server()` checks env vars:
   - `MCP_ENABLED=false` → skips entirely, logs info message.
   - `MCP_JWT_SECRET` not set → skips with warning, Flask runs normally.
3. On valid config: spawns a daemon thread that:
   - Imports `mcp_server.mcp_app` (lazy, inside thread — avoids heavy startup on main thread).
   - Creates the FastMCP app with tools, wraps with auth + rate limit middleware.
   - Runs uvicorn on `0.0.0.0:{MCP_PORT}`.
4. Thread failures are caught and logged — Flask is never affected.

## Implementation Files

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `mcp_server/__init__.py` | 75 | `start_mcp_server()` — env var checks, daemon thread launcher |
| `mcp_server/auth.py` | 164 | JWT `verify_jwt()`, `generate_token()`, CLI (`python -m mcp_server.auth`) |
| `mcp_server/mcp_app.py` | 541 | FastMCP app, 5 tool defs, `JWTAuthMiddleware`, `RateLimitMiddleware`, agent helpers |

### Modified Files

| File | Change |
|------|--------|
| `server.py` | 3 lines added in `main()` to import and call `start_mcp_server()` |
| `filtered_requirements.txt` | Added `mcp[cli]>=1.12.0` and `PyJWT>=2.8.0` |

### Unchanged (reused as-is)

| File | How it's used |
|------|---------------|
| `agents/search_and_information_agents.py` | `PerplexitySearchAgent`, `JinaSearchAgent`, `InterleavedWebSearchAgent` imported and instantiated by tool functions |
| `base.py` | `download_link_data` used by `read_link` tool for multi-format content extraction |
| `endpoints/utils.py` | `keyParser({})` called once to load API keys from env vars |
| `common.py` | `CHEAP_LLM[0]` used as default model name |

## Dependencies

```
mcp[cli]>=1.12.0    # Official MCP Python SDK (FastMCP, streamable-http)
PyJWT>=2.8.0        # JWT token signing/verification
```

Already present in the project: `starlette`, `uvicorn`, `httpx`.

## Implementation Details

### Agent invocation pattern

Tools are synchronous functions (not async) because the underlying search agents use synchronous generators. The MCP SDK handles running sync tools in a thread pool.

```python
@mcp.tool()
def perplexity_search(query: str, detail_level: int = 1, model_name: str = "default") -> str:
    keys = _get_keys()          # cached env-var lookup via keyParser({})
    model = _resolve_model(model_name)  # "default" -> CHEAP_LLM[0]
    agent = PerplexitySearchAgent(keys, model_name=model, detail_level=detail_level, timeout=90)
    return _collect_agent_output(agent, query)  # runs generator, collects text
```

### API key caching

`_get_keys()` calls `keyParser({})` once and caches the result in a module-level global. All clients share the server's API keys — no per-request key resolution.

### Output collection

`_collect_agent_output(agent, query)` iterates the agent's generator, collecting `chunk.get("text", "")` from each yielded dict, and returns the concatenated string. Exceptions are caught and returned as `"Search failed: {error}"` — MCP tools never raise.

### Session manager lifecycle

The MCP SDK requires explicit lifecycle management when using `streamable_http_app()` (as opposed to `mcp.run()`). The factory creates a Starlette wrapper with an `asynccontextmanager` lifespan that starts/stops `mcp.session_manager.run()`.

### Lazy imports

Agent classes, `keyParser`, and `CHEAP_LLM` are imported inside tool functions (not at module top level) to avoid heavy import chains when the daemon thread starts. The first tool call triggers the import; subsequent calls use cached references.

## Error Handling

### Startup errors

| Condition | Behavior |
|-----------|----------|
| `MCP_ENABLED=false` | Info log, Flask runs normally |
| `MCP_JWT_SECRET` not set | Warning log, Flask runs normally |
| `mcp` package not installed | Import error inside thread, logged, Flask runs normally |
| Port 8100 in use | uvicorn bind error inside thread, logged, Flask runs normally |

### Runtime errors

| Condition | Response |
|-----------|----------|
| Missing/invalid bearer token | `401 {"error": "..."}` |
| Expired bearer token | `401 {"error": "Invalid or expired bearer token."}` |
| Rate limit exceeded | `429 {"error": "Rate limit exceeded. Try again later."}` with `Retry-After` header |
| Agent API key not set | Tool returns `"Search failed: ..."` (no HTTP error) |
| Agent execution error | Tool returns `"Search failed: {exception}"` (caught, logged) |

## Debugging

### Verify MCP server is running

```bash
curl -s http://localhost:8100/health
# Expected: {"status":"ok"}
```

### Test auth

```bash
# Generate a test token
export MCP_JWT_SECRET=test
TOKEN=$(python -m mcp_server.auth --email test@test.com --days 1 2>/dev/null | tail -1)

# Call with valid token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8100/ -d '...'

# Call without token (expect 401)
curl http://localhost:8100/
# {"error":"Missing or malformed Authorization header. Expected: Bearer <token>"}
```

### Check logs

MCP server logs use Python's `logging.getLogger(__name__)` pattern. Look for:
- `mcp_server` — thread startup, env var checks
- `mcp_server.mcp_app` — tool execution, agent errors
- `mcp_server.auth` — token verification failures
- `uvicorn` — HTTP request logs

### Common issues

**MCP server not starting**
- Check `MCP_JWT_SECRET` is set in the environment where `python server.py` runs.
- Check `MCP_ENABLED` is not set to `false`.
- Check server logs for `"MCP server failed to start"`.

**Tools return "Search failed"**
- Agent API keys (`OPENROUTER_API_KEY`, `jinaAIKey`, etc.) must be set in the same environment.
- Check the agent-specific key requirements in the Environment Variables table above.

**Rate limit too aggressive**
- Increase `MCP_RATE_LIMIT` env var (e.g., `MCP_RATE_LIMIT=50`).
- Rate limit state is in-memory; restarting the server resets all buckets.

**Nginx 502 on /mcp**
- Verify MCP server is running on the expected port: `curl http://localhost:8100/health`.
- Check nginx config: `location /mcp` must `proxy_pass http://localhost:8100/` (trailing slash rewrites `/mcp` → `/`).

## Planning Document

Full design rationale, alternatives considered, and milestone breakdown: `documentation/planning/plans/mcp_web_search_server.plan.md`
