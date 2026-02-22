# MCP Server Architecture — Quick Reference

## 1. Tool Definition (Decorator Pattern)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Server Name", stateless_http=True, json_response=True, streamable_http_path="/")

@mcp.tool()
def my_tool(query: str, detail_level: int = 1, model_name: str = "default") -> str:
    """Tool description (becomes MCP schema).
    
    Args:
        query: Search query or input
        detail_level: Depth level (1-4)
        model_name: Model to use ("default" for auto-selection)
    """
    try:
        keys = _get_keys()
        model = _resolve_model(model_name)
        result = execute_handler(keys, query, model, detail_level)
        return result
    except Exception as exc:
        logger.exception("Tool error: %s", exc)
        return f"Error: {exc}"
```

**Key points:**
- Function parameters → MCP tool arguments (auto-schema)
- Docstring → tool description
- Return type: `str` (collected, not streamed)
- Always catch exceptions, return error string (never raise)

---

## 2. Transport Mechanism

| Aspect | Value |
|--------|-------|
| **Type** | Stateless HTTP (streamable-HTTP) |
| **Server** | Uvicorn ASGI |
| **Port** | 8100 (configurable: `MCP_PORT`) |
| **Path** | `/` (root, nginx rewrites `/mcp` → `/`) |
| **Protocol** | MCP over HTTP + JSON |
| **Scaling** | Horizontal (stateless) |

**FastMCP configuration:**
```python
mcp = FastMCP(
    "Server Name",
    stateless_http=True,        # No session state
    json_response=True,         # JSON request/response
    streamable_http_path="/"    # Root path
)
```

**Uvicorn startup:**
```python
import uvicorn
app = mcp.streamable_http_app()  # Get ASGI app
uvicorn.run(app, host="0.0.0.0", port=8100, log_level="info")
```

---

## 3. Authentication Flow (JWT Bearer Tokens)

### Token Structure
```python
import jwt
from datetime import datetime, timedelta, timezone

payload = {
    "email": "user@example.com",
    "scopes": ["search"],
    "iat": datetime.now(timezone.utc),
    "exp": datetime.now(timezone.utc) + timedelta(days=365)
}
token = jwt.encode(payload, MCP_JWT_SECRET, algorithm="HS256")
```

### Token Generation (CLI)
```bash
MCP_JWT_SECRET=your-secret python -m mcp_server.auth --email user@example.com --days 365
# Output: eyJhbGciOiJIUzI1NiIs...
```

### Server-Side Verification (Middleware)
```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class JWTAuthMiddleware:
    def __init__(self, app, jwt_secret: str):
        self.app = app
        self.jwt_secret = jwt_secret

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip auth for health checks
        if scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return

        # Extract bearer token
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")

        if not auth_header.startswith("Bearer "):
            response = JSONResponse({"error": "Missing Authorization header"}, status_code=401)
            await response(scope, receive, send)
            return

        token = auth_header[7:]  # Strip "Bearer "
        payload = verify_jwt(token, self.jwt_secret)
        if payload is None:
            response = JSONResponse({"error": "Invalid or expired token"}, status_code=401)
            await response(scope, receive, send)
            return

        # Attach client info to scope
        scope["mcp_client_email"] = payload.get("email", "unknown")
        scope["mcp_client_scopes"] = payload.get("scopes", [])
        await self.app(scope, receive, send)

def verify_jwt(token: str, secret: str) -> dict | None:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
```

### Client Usage
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

---

## 4. Startup from server.py (Daemon Thread)

### Integration Point (server.py:main())
```python
def main(argv=None):
    app = create_app(argv)
    from endpoints.auth import cleanup_tokens
    cleanup_tokens()

    # Start MCP server in daemon thread
    from mcp_server import start_mcp_server
    start_mcp_server()

    # Flask continues normally
    app.run(host="0.0.0.0", port=5000, threaded=True)
    return 0
```

### Daemon Thread Launcher (mcp_server/__init__.py)
```python
import logging
import os
import threading

logger = logging.getLogger(__name__)

def start_mcp_server() -> None:
    """Start MCP server in daemon thread.
    
    Environment variables:
    - MCP_ENABLED: "true"/"false" (default: "true")
    - MCP_JWT_SECRET: Required for auth
    - MCP_PORT: Server port (default: 8100)
    - MCP_RATE_LIMIT: Requests/minute per token (default: 10)
    """
    if os.getenv("MCP_ENABLED", "true").lower() == "false":
        logger.info("MCP server disabled (MCP_ENABLED=false)")
        return

    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning("MCP_JWT_SECRET not set — MCP server will not start")
        return

    port = int(os.getenv("MCP_PORT", "8100"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn
            from mcp_server.mcp_app import create_mcp_app

            app, _mcp = create_mcp_app(jwt_secret=jwt_secret, rate_limit=rate_limit)
            logger.info("MCP server starting on port %d", port)
            uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
        except Exception:
            logger.exception("MCP server failed to start")

    thread = threading.Thread(target=_run, name="mcp-server", daemon=True)
    thread.start()
    logger.info("MCP server thread started (port=%d, rate_limit=%d/min)", port, rate_limit)
```

**Safeguards:**
- ✅ Daemon thread exits when Flask exits
- ✅ MCP failure doesn't crash Flask (try/except in thread)
- ✅ Missing `MCP_JWT_SECRET` → logs warning, Flask runs normally
- ✅ `MCP_ENABLED=false` → skips startup entirely

---

## 5. Port Configuration & Health Check

### Environment Variables
```bash
MCP_ENABLED=true                # Enable/disable MCP
MCP_JWT_SECRET=<secret>         # Required for auth
MCP_PORT=8100                   # Server port (default: 8100)
MCP_RATE_LIMIT=10               # Requests/minute per token (default: 10)
```

### Health Check Endpoint
```python
from starlette.responses import JSONResponse

async def _health_check(request) -> JSONResponse:
    """Simple health check for load-balancers."""
    return JSONResponse({"status": "ok"})

# Add to routes
routes=[
    Route("/health", _health_check, methods=["GET"]),
    Mount("/", app=mcp_starlette),
]
```

**Usage:**
```bash
curl http://localhost:8100/health
# {"status":"ok"}
```

### Nginx Reverse Proxy
```nginx
# Add to /etc/nginx/sites-available/science-reader
location /mcp {
    proxy_pass http://localhost:8100/;  # Trailing slash rewrites /mcp → /
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

---

## 6. Rate Limiting (Per-Token Token-Bucket)

```python
import time
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

class RateLimitMiddleware:
    """Per-token token-bucket rate limiting."""

    def __init__(self, app: ASGIApp, rate: int = 10, window: int = 60) -> None:
        self.app = app
        self.rate = rate
        self.window = window
        self._buckets: dict[str, tuple[float, float]] = {}

    def _bucket_key(self, scope: Scope) -> str:
        """Derive rate-limit key from bearer token (first 20 chars)."""
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
        if auth.startswith("Bearer ") and len(auth) > 27:
            return auth[7:27]  # First 20 chars of token
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
```

---

## 7. Key Patterns to Reuse

### Module Structure
```
new_mcp_server/
├── __init__.py          # start_new_mcp_server() — env var checks, daemon thread
├── mcp_app.py           # create_new_mcp_app() — FastMCP, tools, middleware
└── auth.py              # (optional) JWT auth or reuse existing
```

### Helper Functions Pattern
```python
_keys_cache: dict | None = None

def _get_keys() -> dict:
    """Load API keys from environment (cached)."""
    global _keys_cache
    if _keys_cache is None:
        from endpoints.utils import keyParser
        _keys_cache = keyParser({})  # Empty session = env vars only
    return _keys_cache

def _resolve_model(model_name: str) -> str:
    """Resolve 'default' to concrete model name."""
    if model_name == "default" or not model_name:
        from common import CHEAP_LLM
        return CHEAP_LLM[0]
    return model_name

def _collect_agent_output(agent, query: str) -> str:
    """Run agent generator to completion, return concatenated text."""
    result_parts: list[str] = []
    try:
        for chunk in agent(query, stream=True):
            text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
            if text:
                result_parts.append(text)
    except Exception as exc:
        logger.exception("Agent execution error: %s", exc)
        return f"Error: {exc}"
    return "".join(result_parts)
```

### Middleware Stack Pattern
```python
from starlette.applications import Starlette
from starlette.routing import Mount, Route
import contextlib

def create_mcp_app(jwt_secret: str, rate_limit: int = 10) -> tuple[ASGIApp, Any]:
    """Create MCP ASGI app with auth and rate limiting."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("Server Name", stateless_http=True, json_response=True, streamable_http_path="/")

    # Define tools with @mcp.tool()
    @mcp.tool()
    def tool1(query: str) -> str:
        """Tool description."""
        return "result"

    # Lifespan context manager for session lifecycle
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            yield

    # Build Starlette app with middleware layers
    mcp_starlette = mcp.streamable_http_app()

    outer_app = Starlette(
        routes=[
            Route("/health", _health_check, methods=["GET"]),
            Mount("/", app=mcp_starlette),
        ],
        lifespan=lifespan,
    )

    # Apply middleware (order matters: rate limit → auth)
    app_with_rate_limit = RateLimitMiddleware(outer_app, rate=rate_limit, window=60)
    app_with_auth = JWTAuthMiddleware(app_with_rate_limit, jwt_secret=jwt_secret)

    return app_with_auth, mcp
```

### Startup Integration Template
```python
# In new_mcp_server/__init__.py
def start_new_mcp_server() -> None:
    if os.getenv("NEW_MCP_ENABLED", "true").lower() == "false":
        logger.info("New MCP server disabled")
        return

    jwt_secret = os.getenv("NEW_MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning("NEW_MCP_JWT_SECRET not set")
        return

    port = int(os.getenv("NEW_MCP_PORT", "8101"))
    rate_limit = int(os.getenv("NEW_MCP_RATE_LIMIT", "10"))

    def _run() -> None:
        try:
            import uvicorn
            from new_mcp_server.mcp_app import create_new_mcp_app
            app, _ = create_new_mcp_app(jwt_secret=jwt_secret, rate_limit=rate_limit)
            logger.info("New MCP server starting on port %d", port)
            uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
        except Exception:
            logger.exception("New MCP server failed to start")

    thread = threading.Thread(target=_run, name="new-mcp-server", daemon=True)
    thread.start()
    logger.info("New MCP server thread started (port=%d)", port)

# In server.py:main()
from new_mcp_server import start_new_mcp_server
start_new_mcp_server()
```

---

## 8. Dependencies

```bash
pip install "mcp[cli]>=1.12.0"      # Official MCP Python SDK
pip install "PyJWT>=2.8.0"          # JWT token signing/verification
pip install "uvicorn>=0.20.0"       # ASGI server (included with mcp)
pip install "starlette>=0.25.0"     # ASGI framework (included with mcp)
```

Add to `filtered_requirements.txt`:
```
mcp[cli]>=1.12.0
PyJWT>=2.8.0
```

---

## 9. Client Configuration

### OpenCode
```json
{
  "mcp": {
    "web-search": {
      "type": "remote",
      "url": "http://localhost:8100/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer <token>"
      },
      "enabled": true
    }
  }
}
```

### Claude Code
```json
{
  "mcpServers": {
    "web-search": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8100/",
        "--header",
        "Authorization:Bearer <token>"
      ]
    }
  }
}
```

---

## 10. Quick Checklist for New MCP Server

- [ ] Create `new_mcp_server/` directory
- [ ] Create `new_mcp_server/__init__.py` with `start_new_mcp_server()`
- [ ] Create `new_mcp_server/mcp_app.py` with `create_new_mcp_app()` and tools
- [ ] Create `new_mcp_server/auth.py` (or reuse existing JWT auth)
- [ ] Add startup call in `server.py:main()` before `app.run()`
- [ ] Add nginx `/new-mcp` location block
- [ ] Set environment variables: `NEW_MCP_JWT_SECRET`, `NEW_MCP_PORT`, `NEW_MCP_RATE_LIMIT`
- [ ] Generate token: `python -m new_mcp_server.auth --email user@example.com`
- [ ] Test health check: `curl http://localhost:8101/health`
- [ ] Test tool call with bearer token
- [ ] Update documentation in `documentation/features/new_mcp_server/`

