# MCP Server Setup and Operations

How to set up, configure, and operate the 8 MCP servers that provide tools to OpenCode (and potentially other MCP clients like Claude Code or OpenClaw).

For feature details and architecture of the web search server, see `documentation/features/mcp_web_search_server/README.md`.

---

## Architecture Overview

The science-reader process (`python server.py`) starts the Flask web app **and** spawns 7 MCP servers as daemon threads. An 8th MCP server (pdf-reader) runs as a local npx process managed by OpenCode.

```
python server.py
  ├── Flask web app (port 5000)
  ├── Web Search MCP    (port 8100)  — mcp_server/mcp_app.py
  ├── PKB MCP           (port 8101)  — mcp_server/pkb.py
  ├── Documents MCP     (port 8102)  — mcp_server/docs.py          [4 or 9 tools, see MCP_TOOL_TIER]
  ├── Artefacts MCP     (port 8103)  — mcp_server/artefacts.py
  ├── Conversation MCP  (port 8104)  — mcp_server/conversation.py
  ├── Prompts MCP       (port 8105)  — mcp_server/prompts_actions.py
  └── Code Runner MCP   (port 8106)  — mcp_server/code_runner_mcp.py

OpenCode (port 3000)
  └── pdf-reader MCP    (local npx)  — @sylphx/pdf-reader-mcp
```

All 7 remote MCP servers use JWT bearer-token authentication with the same `MCP_JWT_SECRET`. The pdf-reader is a local stdio-based server that doesn't need auth.

**Total tools: 37** across all 8 servers.

---

## Prerequisites

Install the MCP dependencies (if not already present):

```bash
pip install "mcp[cli]>=1.12.0" "PyJWT>=2.8.0"
```

These are also listed in `filtered_requirements.txt`.

---

## 1. Choose a JWT Secret

All 7 MCP servers use the same JWT secret for token verification.

```bash
export MCP_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo $MCP_JWT_SECRET   # save this somewhere safe
```

Current production value is stored in `/tmp/run_science_reader.sh`.

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

**CLI options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--email` | required | Client identifier embedded in the token |
| `--days` | 365 | Token lifetime in days |
| `--secret` | `$MCP_JWT_SECRET` | Override the env var if needed |

You can generate multiple tokens (different emails, different expiry) — each gets its own rate-limit bucket on the server.

---

## 3. Start the Server

All 7 MCP servers start automatically alongside Flask when `python server.py` is run with `MCP_JWT_SECRET` set.

### Local development

```bash
export MCP_JWT_SECRET="your-secret-here"
python server.py
```

You should see all servers start:

```
 * Running on http://127.0.0.1:5000          # Flask
INFO:     Uvicorn running on http://0.0.0.0:8100    # Web Search MCP
INFO:     Uvicorn running on http://0.0.0.0:8101    # PKB MCP
INFO:     Uvicorn running on http://0.0.0.0:8102    # Documents MCP
INFO:     Uvicorn running on http://0.0.0.0:8103    # Artefacts MCP
INFO:     Uvicorn running on http://0.0.0.0:8104    # Conversation MCP
INFO:     Uvicorn running on http://0.0.0.0:8105    # Prompts MCP
INFO:     Uvicorn running on http://0.0.0.0:8106    # Code Runner MCP
```

### Production (with screen)

```bash
screen -S science-reader
bash /tmp/run_science_reader.sh
# Ctrl+A, D to detach
```

Or manually:
```bash
screen -S science-reader
export MCP_JWT_SECRET="your-secret-here"
export SECRET_KEY=XX GOOGLE_CLIENT_ID=XXX GOOGLE_CLIENT_SECRET=XXX
# ... (all other env vars — see /tmp/run_science_reader.sh for full list)
python server.py
# Ctrl+A, D to detach
```

### Environment variables

**Core MCP variables:**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCP_JWT_SECRET` | **Yes** | — | HS256 signing secret. No MCP servers start without it. |
| `MCP_PORT` | No | `8100` | Port for the Web Search MCP server |
| `MCP_RATE_LIMIT` | No | `10` | Max requests per token per minute |
| `MCP_ENABLED` | No | `true` | Set to `false` to disable all MCP servers |
| `MCP_TOOL_TIER` | No | `baseline` | `"baseline"` (4 tools) or `"full"` (all 9 tools) for the Documents MCP. Controls which docs tools are registered at startup. |

**Per-server port overrides (all optional):**

| Variable | Default | Server |
|----------|---------|--------|
| `MCP_PORT` | `8100` | Web Search |
| `PKB_MCP_PORT` | `8101` | PKB |
| `DOCS_MCP_PORT` | `8102` | Documents |
| `ARTEFACTS_MCP_PORT` | `8103` | Artefacts |
| `CONVERSATION_MCP_PORT` | `8104` | Conversation |
| `PROMPTS_MCP_PORT` | `8105` | Prompts & Actions |
| `CODE_RUNNER_MCP_PORT` | `8106` | Code Runner |

**Per-server enable flags (all default to `"true"`):**

| Variable | Server |
|----------|--------|
| `PKB_MCP_ENABLED` | PKB |
| `DOCS_MCP_ENABLED` | Documents |
| `ARTEFACTS_MCP_ENABLED` | Artefacts |
| `CONVERSATION_MCP_ENABLED` | Conversation |
| `PROMPTS_MCP_ENABLED` | Prompts & Actions |
| `CODE_RUNNER_MCP_ENABLED` | Code Runner |

The MCP servers also need the same API keys as the Flask server (loaded via `keyParser({})`): `OPENROUTER_API_KEY`, `jinaAIKey`, `openAIKey`, scraping keys, etc.

### Disabling MCP servers

- Don't set `MCP_JWT_SECRET` (all MCP servers skip startup, Flask runs normally), or
- Set `MCP_ENABLED=false` to disable all, or
- Set individual `*_MCP_ENABLED=false` to disable specific servers

Flask is never affected by MCP startup failures.

### Verify servers are running

```bash
# Health check all 7 servers
for port in 8100 8101 8102 8103 8104 8105 8106; do
  echo -n "Port $port: "
  curl -s http://localhost:$port/health
  echo
done
```

All should return `{"status":"ok"}`. The health endpoint is unauthenticated.

---

## 4. Configure OpenCode

OpenCode uses two config files in the project root:

- **`opencode.json`** — 7 remote MCP servers (web-search through code-runner)
- **`opencode.jsonc`** — 1 local MCP server (pdf-reader via npx)

### opencode.json (7 remote servers)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "web-search": {
      "type": "remote",
      "url": "http://localhost:8100/",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:MCP_JWT_TOKEN}" },
      "enabled": true
    },
    "pkb": {
      "type": "remote",
      "url": "http://localhost:8101/",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:MCP_JWT_TOKEN}" },
      "enabled": true
    },
    "documents": {
      "type": "remote",
      "url": "http://localhost:8102/",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:MCP_JWT_TOKEN}" },
      "enabled": true
    },
    "artefacts": {
      "type": "remote",
      "url": "http://localhost:8103/",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:MCP_JWT_TOKEN}" },
      "enabled": true
    },
    "conversation": {
      "type": "remote",
      "url": "http://localhost:8104/",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:MCP_JWT_TOKEN}" },
      "enabled": true
    },
    "prompts-actions": {
      "type": "remote",
      "url": "http://localhost:8105/",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:MCP_JWT_TOKEN}" },
      "enabled": true
    },
    "code-runner": {
      "type": "remote",
      "url": "http://localhost:8106/",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:MCP_JWT_TOKEN}" },
      "enabled": true
    }
  }
}
```

### opencode.jsonc (local pdf-reader)

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "pdf-reader": {
      "type": "local",
      "command": ["npx", "-y", "@sylphx/pdf-reader-mcp"],
      "enabled": true
    }
  }
}
```

### Critical config notes

- The URL is `http://localhost:<port>/` (root path), NOT `/mcp`. The MCP handler's `streamable_http_path` is `"/"`. The `/mcp` path only applies when nginx rewrites the path.
- `"oauth": false` is **required**. Without it, OpenCode sees the server's 401 response and tries OAuth Dynamic Client Registration, which our JWT-only server doesn't support.
- `{env:MCP_JWT_TOKEN}` tells OpenCode to read the token from the `MCP_JWT_TOKEN` environment variable at runtime. The OpenCode process must have this variable set when it starts.
- OpenCode registers MCP tools **only at startup**. If MCP servers were down when OpenCode started, the tools won't appear — restart OpenCode.

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

Repeat for each server (ports 8101-8106) with appropriate names.

---

## 5. Tool Reference (All 37 Tools)

### Web Search (port 8100) — 5 tools

| Tool | Description | Key params |
|------|-------------|------------|
| `perplexity_search` | Search via Perplexity AI models | `query`, `detail_level` (1-4) |
| `jina_search` | Search via Jina AI with full page content | `query`, `detail_level` (1-3) |
| `deep_search` | Multi-hop iterative research across sources | `query`, `interleave_steps` (1-5), `sources` |
| `jina_read_page` | Read a URL via Jina Reader (fast, markdown) | `url` |
| `read_link` | Read any URL — pages, PDFs, images, YouTube | `url`, `context`, `detailed` |

### PKB — Personal Knowledge Base (port 8101) — 6 tools

| Tool | Description | Key params |
|------|-------------|------------|
| `pkb_search` | Hybrid search (FTS5 + embedding) the PKB | `query`, `k`, `strategy` |
| `pkb_get_claim` | Retrieve a single claim by ID | `claim_id` |
| `pkb_resolve_reference` | Resolve a `@friendly_id` reference | `reference_id` |
| `pkb_get_pinned_claims` | Get high-priority pinned claims | `limit` |
| `pkb_add_claim` | Add a new fact/preference/decision to PKB | `statement`, `claim_type`, `context_domain` |
| `pkb_edit_claim` | Edit an existing claim | `claim_id`, `statement`, `tags` |

### Documents (port 8102) — 4 or 9 tools (see `MCP_TOOL_TIER`)

| Tool | Description | Key params |
|------|-------------|------------|
| `docs_list_conversation_docs` | List docs attached to a conversation | `conversation_id` |
| `docs_list_global_docs` | List all global documents | — |
| `docs_query` | Semantic search within a document | `doc_storage_path`, `query` |
| `docs_get_full_text` | Retrieve full document text | `doc_storage_path`, `token_limit` |

### Documents MCP tools (`MCP_TOOL_TIER`)

The Documents MCP server (port 8102) exposes different tool sets depending on the `MCP_TOOL_TIER` environment variable:

**Baseline tier (default, 4 tools):**

| Tool | Parameters | Purpose |
|------|-----------|---------|
| `docs_list_conversation_docs` | `user_email`, `conversation_id` | List docs attached to a conversation. Returns `doc_id`, `title`, `short_summary`, `doc_storage_path`, `source`, `display_name`. |
| `docs_list_global_docs` | `user_email` | List all global docs. Returns `index`, `doc_id`, `display_name`, `title`, `short_summary`, `doc_storage_path`, `source`, `folder_id`, `tags`. |
| `docs_query` | `user_email`, `doc_storage_path`, `query`, `token_limit` | Semantic search within a doc using its `doc_storage_path`. |
| `docs_get_full_text` | `user_email`, `doc_storage_path`, `token_limit` | Get full text of a doc using its `doc_storage_path`. |

**Full tier (`MCP_TOOL_TIER=full`, 5 additional tools):**

| Tool | Parameters | Purpose |
|------|-----------|---------|
| `docs_get_info` | `user_email`, `doc_storage_path` | Metadata (title, summary, text_len) without loading full text. |
| `docs_answer_question` | `user_email`, `doc_storage_path`, `question` | RAG Q&A — retrieves relevant passages and generates an answer. |
| `docs_get_global_doc_info` | `user_email`, `doc_id` | Global doc metadata including `doc_storage_path`, `created_at`, `updated_at`. |
| `docs_query_global_doc` | `user_email`, `doc_id`, `query`, `token_limit` | Semantic search in a global doc via `doc_id` (no path needed). |
| `docs_get_global_doc_full_text` | `user_email`, `doc_id`, `token_limit` | Full text of a global doc via `doc_id` (no path needed). |

**Typical usage pattern:**
1. Call `docs_list_global_docs(user_email)` to get the list with `doc_storage_path` values.
2. Use `doc_storage_path` with `docs_query` or `docs_get_full_text` to read content.
3. If only `doc_id` is known: call `docs_list_global_docs`, match by `doc_id`, use the `doc_storage_path`.

**Global doc reference syntax** (in chat messages — not MCP, for reference):
- `#gdoc_1`, `#global_doc_1` — by index (1-based, ordered by `created_at`)
- `"my doc name"` — by display name (case-insensitive)
- `#gdoc_all` — reference all global docs
- `#folder:Research` — all docs in folder "Research"
- `#tag:arxiv` — all docs tagged "arxiv"

### Artefacts (port 8103) — 8 tools

| Tool | Description | Key params |
|------|-------------|------------|
| `artefacts_list` | List all artefacts in a conversation | `conversation_id` |
| `artefacts_create` | Create a new file artefact | `name`, `file_type`, `initial_content` |
| `artefacts_get` | Get artefact content and metadata | `artefact_id` |
| `artefacts_get_file_path` | Get absolute file path for direct editing | `artefact_id` |
| `artefacts_update` | Overwrite artefact content | `artefact_id`, `content` |
| `artefacts_delete` | Delete an artefact | `artefact_id` |
| `artefacts_propose_edits` | LLM-generated edit proposals | `artefact_id`, `instruction` |
| `artefacts_apply_edits` | Apply proposed edits | `artefact_id`, `base_hash`, `ops` |

### Conversation (port 8104) — 7 tools

| Tool | Description | Key params |
|------|-------------|------------|
| `conv_get_memory_pad` | Get per-conversation scratchpad | `conversation_id` |
| `conv_set_memory_pad` | Set per-conversation scratchpad | `conversation_id`, `text` |
| `conv_get_history` | Get formatted conversation history | `conversation_id`, `query` |
| `conv_get_user_detail` | Get persistent user memory/bio | — |
| `conv_get_user_preference` | Get stored user preferences | — |
| `conv_get_messages` | Get raw message list | `conversation_id` |
| `conv_set_user_detail` | Update persistent user memory | `text` |

### Prompts & Actions (port 8105) — 5 tools

| Tool | Description | Key params |
|------|-------------|------------|
| `prompts_list` | List all saved prompts | — |
| `prompts_get` | Get a specific prompt by name | `name` |
| `temp_llm_action` | Run ephemeral LLM action on text | `action_type`, `selected_text` |
| `prompts_create` | Create a new prompt | `name`, `content` |
| `prompts_update` | Update an existing prompt | `name`, `content` |

### Code Runner (port 8106) — 1 tool

| Tool | Description | Key params |
|------|-------------|------------|
| `run_python_code` | Execute Python in project's IPython env | `code_string` |

### PDF Reader (local npx) — 1 tool

| Tool | Description | Key params |
|------|-------------|------------|
| `read_pdf` | Read content/metadata/images from PDFs | `sources`, `include_full_text`, `include_images` |

---

## 6. Nginx Reverse Proxy (Production)

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

Note: This only exposes the web search MCP (port 8100) externally. For external access to other MCP servers, add additional location blocks (e.g., `/mcp-pkb` → port 8101). For local-only use (OpenCode on the same machine), nginx is not needed — OpenCode connects directly to localhost ports.

After editing:

```bash
sudo nginx -t              # test config syntax
sudo systemctl reload nginx
```

---

## 7. Troubleshooting

### MCP servers not starting

Check the log output when running `python server.py`:

| Log message | Cause | Fix |
|------------|-------|-----|
| `MCP_JWT_SECRET not set` | Env var missing | `export MCP_JWT_SECRET="..."` before starting |
| `MCP server disabled` | `MCP_ENABLED=false` is set | Unset it or set to `true` |
| `MCP server failed to start` | Import error or port conflict | Check if `mcp` and `PyJWT` are installed; check if port is in use |

### Health check fails

```bash
curl http://localhost:8100/health
# If no response: MCP server is not running
# If {"status":"ok"}: server is up, problem is elsewhere
```

### Auth errors (401)

```bash
# Test with your token
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8100/
```

Common causes:
- Token was generated with a **different** `MCP_JWT_SECRET` than the server is running with.
- Token has expired (check `--days` when you generated it).
- Missing `Bearer ` prefix in the Authorization header.

### OpenCode doesn't see MCP tools

1. MCP servers must be **running** when OpenCode starts — tools register at startup only
2. `MCP_JWT_TOKEN` must be set in the OpenCode process environment
3. Check `opencode.json` has correct entries with `{env:MCP_JWT_TOKEN}` in headers
4. Check `"oauth": false` is set for each server — without it, OpenCode tries OAuth and fails

### Tools return "Search failed" or errors

Agent API keys are missing. The MCP servers reuse the same env vars as Flask. Ensure `OPENROUTER_API_KEY`, `jinaAIKey`, etc. are set in the same shell session that runs `server.py`.

### Rate limited (429)

Default is 10 requests/minute per token. Increase with:

```bash
export MCP_RATE_LIMIT=50
```

Rate limit state is in-memory — restarting the server resets all buckets.

### Nginx 502 on /mcp

1. Verify MCP is running: `curl http://localhost:8100/health`
2. Check nginx config: `location /mcp` must `proxy_pass http://localhost:8100/` (trailing slash rewrites path)
3. Run `sudo nginx -t` to check for config syntax errors

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

## 9. Jina Timeout Configuration

Jina search timeouts were doubled from defaults for reliability:

| Location | Setting | Value |
|----------|---------|-------|
| `mcp_server/mcp_app.py:344` | JinaSearchAgent timeout | 240s (was 120s) |
| `mcp_server/mcp_app.py:427` | jina_read_page HTTP timeout | (20s connect, 90s read) — was (10s, 45s) |
| `agents/search_and_information_agents.py:1568` | JinaSearchAgent default timeout | 120s (was 60s) |
| `agents/search_and_information_agents.py:1590` | JinaSearchAgent HTTP timeout | (20s connect, 90s read) — was (10s, 45s) |

---

## Quick Reference

```bash
# Full setup from scratch
export MCP_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "Save this secret: $MCP_JWT_SECRET"

# Generate token
python -m mcp_server.auth --email you@example.com --days 365
# Copy the token output

# Start server (Flask + all 7 MCP servers)
python server.py

# Verify all servers
for port in 8100 8101 8102 8103 8104 8105 8106; do
  curl -s http://localhost:$port/health
done

# Start OpenCode with token
export MCP_JWT_TOKEN=<your-token>
opencode web --port 3000 --hostname 127.0.0.1
```

---

## Key Files

| File | Purpose |
|------|---------|
| `mcp_server/__init__.py` | All 7 server launcher functions, env var config |
| `mcp_server/auth.py` | JWT generation/verification, CLI entry point |
| `mcp_server/mcp_app.py` | Web Search MCP — 5 search/reader tools (port 8100) |
| `mcp_server/pkb.py` | PKB MCP — 6 knowledge base tools (port 8101) |
| `mcp_server/docs.py` | Documents MCP — 4 document tools (port 8102) |
| `mcp_server/artefacts.py` | Artefacts MCP — 8 file management tools (port 8103) |
| `mcp_server/conversation.py` | Conversation MCP — 7 memory/history tools (port 8104) |
| `mcp_server/prompts_actions.py` | Prompts MCP — 5 prompt/action tools (port 8105) |
| `mcp_server/code_runner_mcp.py` | Code Runner MCP — 1 Python execution tool (port 8106) |
| `server.py` | Integration point (calls all `start_*_mcp_server()` in `main()`) |
| `opencode.json` | OpenCode config — 7 remote MCP server definitions |
| `opencode.jsonc` | OpenCode config — local pdf-reader MCP server |
| `/tmp/run_science_reader.sh` | Production startup script with all env vars |
| `documentation/features/mcp_web_search_server/README.md` | Feature docs for web search server |
