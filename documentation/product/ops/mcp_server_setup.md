# MCP Web Search Server — Setup and Operations

How to set up, configure, and operate the MCP server that exposes search and page-reader tools to external coding assistants (OpenCode, Claude Code).

For feature details and architecture, see `documentation/features/mcp_web_search_server/README.md`.

---

## Prerequisites

Install the two new dependencies (if not already present):

```bash
pip install "mcp[cli]>=1.12.0" "PyJWT>=2.8.0"
```

These are also listed in `filtered_requirements.txt`.

---

## 1. Choose a JWT Secret

The MCP server uses JWT (JSON Web Token) bearer-token authentication. You need one secret string that is used both to **generate tokens** (for clients) and to **verify tokens** (on the server).

Pick any strong random string. Example:

```bash
export MCP_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo $MCP_JWT_SECRET   # save this somewhere safe
```

This secret must be the **same** everywhere — when generating tokens, when starting the server, and if you ever regenerate tokens later.

---

## 2. Generate a Bearer Token

```bash
export MCP_JWT_SECRET="your-secret-here"
python -m mcp_server.auth --email you@example.com --days 365
```

Output:

```
Generated MCP bearer token (expires: 2027-02-22):
eyJhbGciOiJIUzI1NiIs...

Use in client config:
  Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

Copy the token string. You will paste it into your client config (step 4).

**CLI options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--email` | required | Client identifier embedded in the token |
| `--days` | 365 | Token lifetime in days |
| `--secret` | `$MCP_JWT_SECRET` | Override the env var if needed |

You can generate multiple tokens (different emails, different expiry) — each gets its own rate-limit bucket on the server.

---

## 3. Start the Server

The MCP server starts automatically alongside Flask from `python server.py` when `MCP_JWT_SECRET` is set.

### Local development

```bash
export MCP_JWT_SECRET="your-secret-here"
python server.py
```

You should see both servers start:

```
 * Running on http://127.0.0.1:5000          # Flask
INFO:     Uvicorn running on http://0.0.0.0:8100    # MCP
```

Verify MCP is running:

```bash
curl http://localhost:8100/health
# {"status":"ok"}
```

### Production (with screen)

```bash
screen -S science-reader
export MCP_JWT_SECRET="your-secret-here"
export SECRET_KEY=XX GOOGLE_CLIENT_ID=XXX GOOGLE_CLIENT_SECRET=XXX
python server.py
# Ctrl+A, D to detach
```

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCP_JWT_SECRET` | **Yes** | — | HS256 signing secret. MCP server won't start without it. |
| `MCP_PORT` | No | `8100` | Port for the MCP server |
| `MCP_RATE_LIMIT` | No | `10` | Max requests per token per minute |
| `MCP_ENABLED` | No | `true` | Set to `false` to disable MCP entirely |

The MCP server also needs the same API keys as the Flask server (loaded via `keyParser({})`): `OPENROUTER_API_KEY`, `jinaAIKey`, `openAIKey`, scraping keys, etc.

### Disabling the MCP server

If you don't need MCP, either:
- Don't set `MCP_JWT_SECRET` (server logs a warning and Flask runs normally), or
- Set `MCP_ENABLED=false`

Flask is never affected by MCP startup failures.

---

## 4. Configure OpenCode

Create `opencode.json` in your project root (or `~/.config/opencode/opencode.json` for global config).

OpenCode uses the `"mcp"` key (not `"mcpServers"`). See [OpenCode MCP docs](https://opencode.ai/docs/mcp-servers/).

### Local (no nginx)

Point directly at the MCP port:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "web-search": {
      "type": "remote",
      "url": "http://localhost:8100/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer <paste-your-token-here>"
      },
      "enabled": true
    }
  }
}
```

Replace `<paste-your-token-here>` with the token from step 2.

**Important notes**:
- The URL is `http://localhost:8100/` (root path), NOT `/mcp`. The MCP handler's `streamable_http_path` is `"/"`. The `/mcp` path only applies when nginx rewrites the path (see section 5).
- `"oauth": false` is **required**. Without it, OpenCode sees the server's 401 response and tries OAuth Dynamic Client Registration, which our JWT-only server doesn't support. This causes OpenCode to mark the MCP as failed/disabled.
- `"enabled": true` ensures the server is active on startup.

### Remote server (behind nginx)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "web-search": {
      "type": "remote",
      "url": "https://your-domain.com/mcp",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer <paste-your-token-here>"
      },
      "enabled": true
    }
  }
}
```

### Configure Claude Code

Using `mcp-remote` bridge (`.mcp.json` in project root):

```json
{
  "mcpServers": {
    "web-search": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8100/",
        "--header",
        "Authorization:Bearer <paste-your-token-here>"
      ]
    }
  }
}
```

Or if your Claude Code version supports direct streamable-HTTP:

```json
{
  "mcpServers": {
    "web-search": {
      "type": "url",
      "url": "http://localhost:8100/",
      "headers": {
        "Authorization": "Bearer <paste-your-token-here>"
      }
    }
  }
}
```

---

## 5. Nginx Reverse Proxy (Production)

Add a `/mcp` location block inside your existing `server { }` block in the nginx config (e.g., `/etc/nginx/sites-available/science-reader`), alongside the existing Flask `/` location.

### With SSL

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    client_max_body_size 100M;

    # Flask (existing)
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

    # MCP server (add this block)
    # Trailing slash on proxy_pass rewrites /mcp → / so the MCP
    # handler (streamable_http_path="/") receives the correct path.
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
}
```

### HTTP only (dev/internal)

```nginx
server {
    listen 80;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
    }

    # Trailing slash on proxy_pass rewrites /mcp → / for the MCP handler.
    location /mcp {
        proxy_pass http://localhost:8100/;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

After editing:

```bash
sudo nginx -t              # test config syntax
sudo systemctl reload nginx
```

Then update your `opencode.json` URL to `https://your-domain.com/mcp`.

---

## 6. Available Tools

Once connected, OpenCode/Claude Code will see these tools:

| Tool | Description | Key params |
|------|-------------|------------|
| `perplexity_search` | Search via Perplexity AI models | `query`, `detail_level` (1-4) |
| `jina_search` | Search via Jina AI with full page content | `query`, `detail_level` (1-3) |
| `deep_search` | Multi-hop iterative research across sources | `query`, `interleave_steps` (1-5), `sources` |
| `jina_read_page` | Read a URL via Jina Reader (fast, markdown) | `url` |
| `read_link` | Read any URL — pages, PDFs, images, YouTube | `url`, `context`, `detailed` |

---

## 7. Troubleshooting

### MCP server not starting

Check the log output when running `python server.py`:

| Log message | Cause | Fix |
|------------|-------|-----|
| `MCP_JWT_SECRET not set` | Env var missing | `export MCP_JWT_SECRET="..."` before starting |
| `MCP server disabled` | `MCP_ENABLED=false` is set | Unset it or set to `true` |
| `MCP server failed to start` | Import error or port conflict | Check if `mcp` and `PyJWT` are installed; check if port 8100 is in use |

### Health check fails

```bash
curl http://localhost:8100/health
# If no response: MCP server is not running
# If {"status":"ok"}: server is up, problem is elsewhere
```

### Auth errors (401)

```bash
# Test with your token
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8100/mcp
```

Common causes:
- Token was generated with a **different** `MCP_JWT_SECRET` than the server is running with.
- Token has expired (check `--days` when you generated it).
- Missing `Bearer ` prefix in the Authorization header.

### Tools return "Search failed"

Agent API keys are missing. The MCP server reuses the same env vars as Flask. Ensure `OPENROUTER_API_KEY`, `jinaAIKey`, etc. are set in the same shell session.

### Rate limited (429)

Default is 10 requests/minute per token. Increase with:

```bash
export MCP_RATE_LIMIT=50
```

Rate limit state is in-memory — restarting the server resets all buckets.

### Nginx 502 on /mcp

1. Verify MCP is running: `curl http://localhost:8100/health`
2. Check nginx config: `location /mcp` must `proxy_pass http://localhost:8100` (not `http://localhost:8100/mcp` — nginx preserves the `/mcp` path).
3. Run `sudo nginx -t` to check for config syntax errors.

---

## 8. Token Management

### Rotate tokens

Generate a new token with the same secret — old tokens remain valid until they expire. To invalidate all existing tokens, change `MCP_JWT_SECRET` and restart the server (all old tokens become invalid immediately).

### Multiple clients

Generate separate tokens per client (different `--email`). Each gets an independent rate-limit bucket:

```bash
export MCP_JWT_SECRET="your-secret-here"
python -m mcp_server.auth --email dev1@team.com --days 365
python -m mcp_server.auth --email dev2@team.com --days 90
```

---

## Quick Reference

```bash
# Full setup from scratch
export MCP_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "Save this secret: $MCP_JWT_SECRET"

# Generate token
python -m mcp_server.auth --email you@example.com --days 365
# Copy the token output

# Start server (Flask + MCP)
python server.py

# Verify
curl http://localhost:8100/health

# Put token in opencode.json and start coding
```

---

## Key Files

| File | Purpose |
|------|---------|
| `mcp_server/__init__.py` | Daemon thread launcher, env var config |
| `mcp_server/auth.py` | JWT generation/verification, CLI entry point |
| `mcp_server/mcp_app.py` | FastMCP app, 5 tool definitions, middleware |
| `server.py` | Integration point (calls `start_mcp_server()` in `main()`) |
| `opencode.json` | OpenCode client config (project root) |
| `documentation/features/mcp_web_search_server/README.md` | Feature docs (architecture, tool reference, implementation details) |
