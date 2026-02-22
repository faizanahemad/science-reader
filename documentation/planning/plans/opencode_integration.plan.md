# OpenCode Integration Plan

## Status: Draft
## Created: 2026-02-22
## Last Updated: 2026-02-22 (MCP servers implemented, OpenCode toggle design added, noReply/AGENTS.md clarified, slash commands updated, autocomplete designed, UI insertion points identified, cancellation handling designed, full terminal UI via xterm.js designed with edge cases)

---

## 1. Requirements

### 1.1 What We Are Building

An integration layer that routes chat messages from the existing Flask-based conversational UI through OpenCode (`opencode serve`) instead of directly calling LLM provider APIs. This gives every conversation access to OpenCode's agentic capabilities — tool use (bash, file edit, grep, LSP), MCP servers, multi-step planning, and context compaction — while preserving the existing UI, streaming format, and all current features (PKB, documents, math formatting, TLDR, agents).

### 1.2 What We Are NOT Building

- A new UI. The browser-facing API (`POST /send_message`) stays identical — newline-delimited JSON streaming.
- A replacement for Conversation.py. It remains the orchestration layer that assembles context, manages persistence, and post-processes responses.
- A migration of all existing agents. Existing agents (research, interview, slides, etc.) stay in Conversation.py initially. Migration is per-agent, decided later.

### 1.3 Goals

1. **Agentic responses**: The LLM can use tools (bash, file edit, code execution, web search, etc.) naturally during conversations, instead of being limited to text-only replies.
2. **MCP-powered context**: PKB memory, documents, and other data sources exposed as MCP tools that the model can call on-demand, in addition to auto-injected context.
3. **Session continuity**: Each conversation maps to an OpenCode session with persistent context, compaction, and tool history.
4. **Configurable per conversation**: Users can toggle OpenCode mode, control context injection level, and manage OpenCode sessions from the existing UI.
5. **Zero UI regression**: Existing streaming, math rendering, TLDR summaries, message persistence, and all UI features work unchanged.
6. **Incremental adoption**: OpenCode mode is opt-in per conversation. Non-OpenCode conversations work exactly as today.

### 1.4 Vision

```
Browser ←── newline-delimited JSON (unchanged) ──→ Flask / Conversation.py
                                                          │
                                                  ┌───────┴────────┐
                                                  │ Context Assembly│
                                                  │ (configurable) │
                                                  └───────┬────────┘
                                                          │ SSE
                                                          ▼
                                                 opencode serve :4096
                                                  ┌───────┴────────┐
                                                  │ Built-in tools │
                                                  │ bash, edit,    │
                                                  │ grep, LSP ...  │
                                                  └───────┬────────┘
                                                          │
                                          ┌───────────────┼───────────────┐
                                          ▼               ▼               ▼
                                     PKB MCP        Document MCP    Web Search MCP
                                    (:8101)         (:8102)         (:8100, existing)
```

The Flask server becomes a **translation layer** between the browser's newline-delimited JSON protocol and OpenCode's SSE event protocol, while retaining ownership of:
- User authentication and session management
- Conversation persistence and message history
- PKB context assembly and injection
- Document reference resolution
- Post-processing (TLDR, math formatting, message IDs)
- UI-facing API contract

OpenCode owns:
- LLM provider communication
- Tool execution (bash, file edit, grep, LSP, MCP tools)
- Agentic loops (plan, execute, verify)
- Session-level context and compaction
- MCP tool orchestration

---

## 2. Architecture

### 2.1 System Components

| Component | Location | Role | New/Modified |
|-----------|----------|------|-------------|
| `opencode serve` | Port 4096 | Headless AI engine with tools and MCP | New (external process) |
| `opencode_client/` | New Python package | HTTP client for OpenCode server API + SSE streaming bridge | New |
| `mcp_server/pkb.py` | Sub-module of existing mcp_server/ | PKB as MCP tools (wraps StructuredAPI) on port 8101 | New |
| `mcp_server/docs.py` | Sub-module of existing mcp_server/ | Documents as MCP tools (wraps DocIndex + global_docs) on port 8102 | New |
| `mcp_server/artefacts.py` | Sub-module of existing mcp_server/ | Artefacts as MCP tools (wraps Conversation artefact helpers) on port 8103 | New |
| `mcp_server/conversation.py` | Sub-module of existing mcp_server/ | Conversation/memory tools on port 8104 | New |
| `mcp_server/prompts_actions.py` | Sub-module of existing mcp_server/ | Prompts + temporary LLM actions on port 8105 | New |
| `mcp_server/` (existing) | Existing | Web search MCP (already running on :8100) | Unchanged |
| `mcp_server/auth.py` | Existing | JWT verification/generation — shared by ALL sub-modules | Unchanged |
| `Conversation.py` | Existing | Orchestration: context assembly, OpenCode routing, post-processing | Modified |
| `call_llm.py` | Existing | Direct LLM calls (still used for non-OpenCode conversations) | Unchanged |
| `endpoints/conversations.py` | Existing | `/send_message` endpoint | Minor modifications |
| `interface/` | Existing | Browser UI | Minor modifications (settings) |
| `opencode.json` | New config file | OpenCode server configuration (MCP servers, permissions, model) | New |

### 2.2 MCP Sub-Module Architecture (KEY ARCHITECTURE DECISION)

All new MCP servers live as sub-modules **within the existing `mcp_server/` package** (not as separate top-level packages). They share `mcp_server/auth.py` for JWT verification but each runs on its own port as a separate uvicorn daemon thread.

```
mcp_server/
    __init__.py          ← MODIFIED: add start_*_mcp_server() calls
    auth.py              ← UNCHANGED: shared JWT verify/generate
    mcp_app.py           ← UNCHANGED: existing web search server
    pkb.py               ← NEW: PKB MCP tools (port 8101)
    docs.py              ← NEW: Documents MCP tools (port 8102)
    artefacts.py         ← NEW: Artefacts MCP tools (port 8103)
    conversation.py      ← NEW: Conversation/memory tools (port 8104)
    prompts_actions.py   ← NEW: Prompts + LLM actions (port 8105)
```

Each new sub-module follows this pattern:

```python
# mcp_server/pkb.py (example)

def create_pkb_mcp_app(jwt_secret: str, rate_limit: int = 10) -> tuple[ASGIApp, Any]:
    """Create PKB MCP server. Returns (asgi_app, fastmcp_instance)."""
    from mcp.server.fastmcp import FastMCP
    from mcp_server.mcp_app import JWTAuthMiddleware, RateLimitMiddleware, _health_check
    # ... define @mcp.tool() functions ...
    # ... return wrapped Starlette app ...

def start_pkb_mcp_server() -> None:
    """Start PKB MCP server in daemon thread. Reads PKB_MCP_ENABLED, PKB_MCP_PORT env vars."""
    # same pattern as start_mcp_server() in __init__.py
```

The `mcp_server/__init__.py` gains 5 new `start_*_mcp_server()` functions imported from sub-modules, all called from `server.py:main()`.

### 2.3 Message Flow (OpenCode Mode)

```
1. Browser sends POST /send_message/{conversation_id}
   Body: { messageText, checkboxes: { opencode_enabled: true, ... }, ... }

2. endpoints/conversations.py extracts query, passes to Conversation.__call__()

3. Conversation.reply() checks opencode_enabled:
   a. Gets or creates OpenCode session for this conversation
   b. Assembles context (history summary, PKB distillation, doc refs) per injection config
   c. Sends context as noReply message (if new context available):
      POST /session/{session_id}/prompt_async
      Body: { noReply: true, system: "<user identity + MCP instructions>",
              parts: [{ type: "text", text: "<assembled context>" }] }
   d. Sends user message:
      POST /session/{session_id}/prompt_async
      Body: { model: { providerID: "<provider>", modelID: "<model>" },
              parts: [{ type: "text", text: "<user message>" }] }
   e. Listens to GET /event SSE stream, filtering for this session's events
   f. For each SSE event:
      - message.part.updated (text) -> yield {"text": delta, "status": "Generating..."}
      - message.part.updated (tool) -> yield {"text": "", "status": "Running <tool>..."}
      - session.idle -> stream complete
      - session.error -> yield error status
   g. Applies math formatting to accumulated text
   h. Generates TLDR if response is long
   i. Generates message_ids and persists messages

4. Conversation.__call__() wraps each yield as json.dumps(chunk) + "\n"

5. Browser receives and renders incrementally (unchanged)
```

### 2.4 Session Management

- Each conversation stores `opencode_session_ids: List[str]` in conversation_settings.
- Default: reuse the most recent session (maintains OpenCode's internal context across messages).
- User can create a new session within the same conversation (via `/oc_new` command or UI button).
- User can switch between sessions (via `/oc_sessions` command or UI selector).
- OpenCode session stores its own context history, tool call logs, and manages compaction independently.
- Flask's `running_summary` and message history are always injected into the OpenCode prompt as system/user context, providing conversation continuity even if the OpenCode session is new.

### 2.5 Context Injection (Configurable Per Conversation)

Context injection level is stored in `conversation_settings.opencode_config.injection_level`:

| Level | What's auto-injected into prompt | What's available via MCP tools only |
|-------|----------------------------------|-------------------------------------|
| `minimal` | Conversation history summary only | PKB, documents, memory pad |
| `medium` (default) | History summary + top PKB claims + referenced docs | Deeper PKB search, full doc text, memory pad |
| `full` | Everything (current behavior: history, PKB distillation, docs, memory pad, as given in current UI basically the chat_slow_reply_prompt with some additional modifications to tell where the doc locations are) | Extras only |

Note that artefact writing requires us to pass the location of the artefact file directly. artefacts are the only way to create things in our server, everything else is read only. 
Memories or claims are also editable and creation is allowed so their MCP should allow that.

The model always has access to MCP tools regardless of injection level. Auto-injection reduces tool-call latency for common context; MCP tools allow the model to pull more when needed.

### 2.6 OpenCode Configuration (opencode.json)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-20250514",
  "small_model": "anthropic/claude-haiku-4-5",
  "permission": {
    "bash": "allow",
    "edit": "allow",
    "webfetch": "allow"
  },
  "compaction": {
    "auto": true,
    "prune": true,
    "reserved": 10000
  },
  "instructions": ["AGENTS.md"],
  "mcp": {
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
    "web-search": {
      "type": "remote",
      "url": "http://localhost:8100/",
      "oauth": false,
      "headers": { "Authorization": "Bearer {env:MCP_JWT_TOKEN}" },
      "enabled": true
    }
  },
  "server": {
    "port": 4096,
    "hostname": "127.0.0.1"
  }
}
```

Note: `MCP_JWT_TOKEN` is the same token for all servers — generated once from `MCP_JWT_SECRET` via `python -m mcp_server.auth --email opencode@system --days 3650`.

### 2.7 OpenCode SSE Event to Flask Streaming Translation

The streaming bridge translates OpenCode SSE events to the existing `{"text": "...", "status": "..."}` format:

| OpenCode SSE Event | Condition | Flask yield |
|---------------------|-----------|-------------|
| `message.part.updated` | `part.type == "text"` | `{"text": delta, "status": "Generating response..."}` |
| `message.part.updated` | `part.type == "tool"`, `state.status == "running"` | `{"text": "", "status": "Running {tool}..."}` |
| `message.part.updated` | `part.type == "tool"`, `state.status == "completed"` | `{"text": "", "status": "Tool {tool} completed"}` |
| `message.part.updated` | `part.type == "tool"`, `state.status == "error"` | `{"text": "", "status": "Tool {tool} failed: {error}"}` |
| `message.part.updated` | `part.type == "reasoning"` | (skip or optionally yield as status) |
| `session.status` | `type == "busy"` | `{"text": "", "status": "Processing..."}` |
| `session.idle` | -- | Signal stream completion |
| `session.error` | -- | `{"text": "", "status": "Error: {message}"}` |
| `permission.updated` | -- | Auto-approve (all tools allowed) |

**Delta handling**: Use `delta` field when present (incremental text). Fall back to diffing `part.text` (full accumulated) if delta missing. Track parts by `part.id` to handle multiple concurrent parts.

### 2.8 Context Injection via `noReply` Messages

A key discovery from the OpenCode API: the `noReply` flag in message body lets us inject context into a session **without triggering an AI response**. This is cleaner than stuffing everything into a system prompt.

**Strategy**:
1. On first message in a session, send a `noReply` message with:
   - `system`: User identity, MCP tool instructions ("You are assisting user X. Their email is Y. Pass it as user_email to PKB and document tools.")
   - `parts`: [{ type: "text", text: "<conversation history summary>" }]
2. On each subsequent message, if new context is available (e.g., PKB claims, referenced docs), send another `noReply` message with the updated context.
3. Then send the actual user message as a normal `prompt_async`.

**Benefits over system prompt stuffing**:
- Context appears as a natural conversation turn (model processes it like a user message)
- System prompt stays lean and stable (identity + MCP instructions only)
- Context can be updated incrementally without resending the entire system prompt
- OpenCode's compaction handles old context messages naturally

**When to skip noReply**:
- If no new context is available (e.g., same PKB claims, no new docs) — just send the user message
- If `injection_level` is `minimal` and history summary hasn't changed

**`noReply` vs `system` parameter**:
- `system` sets the system prompt for the entire session context
- `system` is appended to the system prompt array for that specific message, does NOT replace the base prompt (AGENTS.md + environment)
- `noReply` injects a user-visible message that the model sees but doesn't respond to
- `noReply` messages are regular user messages in history — they survive compaction and are included in future LLM calls
- Use `system` for identity/instructions (static), use `noReply` for dynamic context (PKB, docs, history)
**AGENTS.md Auto-Loading (Important Discovery)**:
OpenCode automatically reads `AGENTS.md` from the project root directory when `opencode serve` starts. From the official docs: "You can provide custom instructions to opencode by creating an AGENTS.md file. It contains instructions that will be included in the LLM's context to customize its behavior for your specific project."

This means:
- OpenCode already knows our project structure, coding conventions, and patterns from AGENTS.md
- We do NOT need to re-inject project guidelines via `noReply`
- `noReply` should only inject **conversation-specific** context: running summary, PKB claims, referenced docs, user identity
- Our `opencode.json` also references AGENTS.md via the `instructions` field, providing a double load path
- Subdirectory AGENTS.md files (e.g., `mcp_server/AGENTS.md`) are loaded contextually when OpenCode reads files in those directories

**Source code confirmation** (from `packages/opencode/src/session/prompt.ts`):
```python
# noReply behavior verified from source:
# if input.noReply === true:
#     return message  # Just stores message, no LLM loop
# return loop({ sessionID: input.sessionID })  # Only runs LLM if noReply is false/absent
```

### 2.9 Full OpenCode Server API Reference

The following is the complete API surface from the official docs (https://opencode.ai/docs/server/). The plan uses a subset; this reference ensures we can expand integration later.

| Category | Method | Path | Description |
|----------|--------|------|-------------|
| Global | GET | /global/health | Health check and version |
| Global | GET | /global/event | Global events (SSE) |
| Global | GET | /event | All events (SSE) -- primary event stream |
| Config | GET | /config | Get config |
| Config | PATCH | /config | Update config at runtime |
| Config | GET | /config/providers | List providers and default models |
| Sessions | GET | /session | List all sessions |
| Sessions | POST | /session | Create session (body: { parentID?, title? }) |
| Sessions | GET | /session/:id | Get session details |
| Sessions | PATCH | /session/:id | Update session (body: { title? }) |
| Sessions | DELETE | /session/:id | Delete session |
| Sessions | GET | /session/status | Status for all sessions |
| Sessions | GET | /session/:id/children | Child sessions |
| Sessions | GET | /session/:id/todo | Todo list for session |
| Sessions | POST | /session/:id/abort | Abort running session |
| Sessions | POST | /session/:id/fork | Fork session at message (body: { messageID? }) |
| Sessions | POST | /session/:id/summarize | Summarize session (body: { providerID, modelID }) |
| Sessions | POST | /session/:id/revert | Revert message (body: { messageID, partID? }) |
| Sessions | POST | /session/:id/unrevert | Restore reverted messages |
| Sessions | POST | /session/:id/share | Share session |
| Sessions | DELETE | /session/:id/share | Unshare session |
| Sessions | GET | /session/:id/diff | Get diff (query: messageID?) |
| Sessions | POST | /session/:id/permissions/:permissionID | Respond to permission (body: { response, remember? }) |
| Messages | GET | /session/:id/message | List messages (query: limit?) |
| Messages | POST | /session/:id/message | Send message sync (body: { messageID?, model?, agent?, noReply?, system?, tools?, parts, format? }) |
| Messages | GET | /session/:id/message/:messageID | Get message details |
| Messages | POST | /session/:id/prompt_async | Send message async (same body, returns 204) |
| Messages | POST | /session/:id/command | Execute command (body: { messageID?, agent?, model?, command, arguments }) |
| Messages | POST | /session/:id/shell | Run shell command (body: { agent, model?, command }) |
| MCP | GET | /mcp | Get MCP server status |
| MCP | POST | /mcp | Add MCP server dynamically (body: { name, config }) |
| Agents | GET | /agent | List available agents |
| Commands | GET | /command | List all commands |

### 2.10 OpenCode Commands Reference
Available commands can be listed via `GET /command`.
Key commands and their routing when OpenCode mode is active:

| User types in chat | OpenCode API call | Result |
|-------------------|-------------------|--------|
| `/compact` | `POST /session/{id}/command` body: `{command:"compact"}` | Compacts session context to save tokens |
| `/abort` | `POST /session/{id}/abort` | Stops current LLM generation immediately |
| `/new` | `POST /session` + update conversation_settings | Creates new OpenCode session for this conversation |
| `/sessions` | Read from `conversation_settings.opencode_config.session_ids` | Lists all OpenCode sessions for this conversation |
| `/fork` | `POST /session/{id}/fork` | Branches conversation from current point |
| `/summarize` | `POST /session/{id}/summarize` body: `{providerID, modelID}` | Summarizes session to compress context |
| `/status` | `GET /session/status` | Shows OpenCode session status |
| `/diff` | `GET /session/{id}/diff` | Shows file changes made in this session |
| `/revert` | `POST /session/{id}/revert` body: `{messageID}` | Undoes last message |
| `/mcp` | `GET /mcp` | Shows MCP server status |
| `/models` | `GET /config/providers` | Shows available models and providers |
| `/help` | Static list | Shows available OpenCode commands |

**Conflict resolution with existing slash commands:**
- `/title` and `/set_title` are OUR commands — always handled by Conversation.py regardless of OpenCode mode
- `/temp` and `/temporary` are OUR commands — always handled by Conversation.py
- If a command matches both an OpenCode command and a future local command, local takes precedence (local commands are checked first in reply())
- Unknown `/` commands in OpenCode mode are sent to OpenCode via `POST /session/{id}/command` as a passthrough

---

## 3. MCP Sub-Module Detailed Specification

### 3.1 Design Principles

1. **All tools accept `user_email` and optionally `conversation_id`** as required parameters. The OpenCode system prompt instructs the model: "The current user's email is `{user_email}`. Pass it as `user_email` to all MCP tool calls."
2. **Artefacts are the ONLY file creation mechanism**. The model MUST use artefact tools to create any persistent output. There is no filesystem write path outside of artefacts.
3. **PKB claims and memories are writable**. The model can add/edit claims. All other data (docs, history) is read-only via MCP.
4. **All tool return values are JSON-serializable strings**. ActionResult, DocIndex results, and other complex types are serialized to JSON text for LLM consumption.
5. **Errors are returned as strings, never raised**. MCP tools catch all exceptions and return error descriptions so the LLM can recover gracefully.
6. **All sub-modules reuse `mcp_server/auth.py`** for JWT verification and `mcp_server/mcp_app.py` for `JWTAuthMiddleware`, `RateLimitMiddleware`, and `_health_check`.

### 3.2 Implementation Pattern (Identical for All Sub-Modules)

Each sub-module exports two functions:

```python
# mcp_server/{name}.py

def create_{name}_mcp_app(jwt_secret: str, rate_limit: int = 10) -> tuple[ASGIApp, Any]:
    """
    Create {name} MCP server as ASGI app.
    Returns (asgi_app, fastmcp_instance).
    Pattern: identical to create_mcp_app() in mcp_app.py.
    """
    import contextlib
    from mcp.server.fastmcp import FastMCP
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from mcp_server.mcp_app import JWTAuthMiddleware, RateLimitMiddleware, _health_check

    mcp = FastMCP("{Display Name}", stateless_http=True, json_response=True, streamable_http_path="/")

    @mcp.tool()
    def tool_name(user_email: str, ...) -> str:
        """Tool docstring — used by LLM to decide when to call this tool."""
        ...

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    mcp_starlette = mcp.streamable_http_app()
    outer_app = Starlette(
        routes=[Route("/health", _health_check, methods=["GET"]), Mount("/", app=mcp_starlette)],
        lifespan=lifespan,
    )
    app_with_rate_limit = RateLimitMiddleware(outer_app, rate=rate_limit, window=60)
    app_with_auth = JWTAuthMiddleware(app_with_rate_limit, jwt_secret=jwt_secret)
    return app_with_auth, mcp


def start_{name}_mcp_server() -> None:
    """
    Start {name} MCP server in daemon thread.
    Env vars: {NAME}_MCP_ENABLED (default "true"), {NAME}_MCP_PORT (default XXXX).
    Reuses MCP_JWT_SECRET and MCP_RATE_LIMIT.
    Pattern: identical to start_mcp_server() in __init__.py.
    """
    import os, threading, logging
    logger = logging.getLogger(__name__)
    if os.getenv("{NAME}_MCP_ENABLED", "true").lower() == "false":
        return
    jwt_secret = os.getenv("MCP_JWT_SECRET", "")
    if not jwt_secret:
        logger.warning("{NAME} MCP server not starting: MCP_JWT_SECRET not set")
        return
    port = int(os.getenv("{NAME}_MCP_PORT", "XXXX"))
    rate_limit = int(os.getenv("MCP_RATE_LIMIT", "10"))

    def _run():
        import uvicorn
        from mcp_server.{name} import create_{name}_mcp_app
        app, _ = create_{name}_mcp_app(jwt_secret=jwt_secret, rate_limit=rate_limit)
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

    thread = threading.Thread(target=_run, name="mcp-{name}", daemon=True)
    thread.start()
```

### 3.3 Updated `mcp_server/__init__.py`

Add imports and calls for all 5 new servers:

```python
# In mcp_server/__init__.py — ADD after existing start_mcp_server():

from mcp_server.pkb import start_pkb_mcp_server
from mcp_server.docs import start_docs_mcp_server
from mcp_server.artefacts import start_artefacts_mcp_server
from mcp_server.conversation import start_conversation_mcp_server
from mcp_server.prompts_actions import start_prompts_actions_mcp_server
```

These are called from `server.py:main()` alongside the existing `start_mcp_server()` call.

### 3.4 PKB MCP Server (`mcp_server/pkb.py`, port 8101)

**Environment variables**: `PKB_MCP_ENABLED` (default `true`), `PKB_MCP_PORT` (default `8101`)

**Initialization**: At server startup, instantiate shared StructuredAPI:
```python
from truth_management_system.structured_api import StructuredAPI
from endpoints.utils import keyParser
_pkb_api: StructuredAPI | None = None

def _get_pkb_api() -> StructuredAPI:
    global _pkb_api
    if _pkb_api is None:
        keys = keyParser({})
        _pkb_api = StructuredAPI(keys=keys)  # user-scoped via .for_user(email) per call
    return _pkb_api
```

**Tool Inventory** (10 tools):

| Tool | StructuredAPI method | Params | Returns | Notes |
|------|---------------------|--------|---------|-------|
| `pkb_search` | `api.for_user(email).search()` | `user_email`, `query`, `k=20`, `strategy="hybrid"` | JSON: list of claims | Primary search |
| `pkb_get_claim` | `api.for_user(email).get_claim()` | `user_email`, `claim_id` | JSON: single claim | Get by ID |
| `pkb_get_claims_by_ids` | `api.for_user(email).get_claims_by_ids()` | `user_email`, `claim_ids: list[str]` | JSON: list of claims | Batch get |
| `pkb_resolve_reference` | `api.for_user(email).resolve_reference()` | `user_email`, `reference_id` | JSON: resolved objects | `@`-reference resolution |
| `pkb_autocomplete` | `api.for_user(email).autocomplete()` | `user_email`, `prefix`, `limit=10` | JSON: list of matches | friendly_id prefix search |
| `pkb_get_pinned_claims` | `api.for_user(email).get_pinned_claims()` | `user_email`, `limit=50` | JSON: list of claims | Globally pinned |
| `pkb_resolve_context` | `api.for_user(email).resolve_context()` | `user_email`, `context_id` | JSON: context + claims | Full context tree |
| `pkb_add_claim` | `api.for_user(email).add_claim()` | `user_email`, `statement`, `claim_type`, `context_domain`, `tags=None` | JSON: ActionResult | Add new memory/claim |
| `pkb_edit_claim` | `api.for_user(email).edit_claim()` | `user_email`, `claim_id`, `statement=None`, `tags=None`, ...patch fields | JSON: ActionResult | Edit existing claim |
| `pkb_pin_claim` | `api.for_user(email).pin_claim()` | `user_email`, `claim_id`, `pin=True` | JSON: ActionResult | Pin/unpin for prominence |

**Return serialization**: All `ActionResult` objects serialized to `json.dumps(result.__dict__)`. Lists of claims serialized to `json.dumps([c.__dict__ for c in claims])`.

### 3.5 Documents MCP Server (`mcp_server/docs.py`, port 8102)

**Environment variables**: `DOCS_MCP_ENABLED` (default `true`), `DOCS_MCP_PORT` (default `8102`)

**Covers**: both conversation-scoped documents AND global documents.

**Initialization**: DocIndex loaded per-request from storage path (no shared state needed — DocIndex is small).

**Tool Inventory** (9 tools):

| Tool | Underlying | Params | Returns | Notes |
|------|-----------|--------|---------|-------|
| `docs_list_conversation_docs` | `DocIndex.load_local()` + conversation artefact helpers | `user_email`, `conversation_id` | JSON: list of {doc_id, title, short_summary, doc_storage_path} | List docs attached to conversation |
| `docs_list_global_docs` | `database/global_docs.list_global_docs()` | `user_email` | JSON: list of {index, doc_id, display_name, title, short_summary, doc_storage_path} | List user's global docs |
| `docs_get_info` | `DocIndex.load_local().brief_summary` + short_summary | `user_email`, `doc_storage_path` | JSON: {title, brief_summary, short_summary, text_len, visible} | Doc metadata without full text |
| `docs_query` | `DocIndex.load_local().semantic_search_document()` | `user_email`, `doc_storage_path`, `query`, `token_limit=4096` | str: relevant passages | Semantic search in doc |
| `docs_get_full_text` | `DocIndex.load_local().get_raw_doc_text()` | `user_email`, `doc_storage_path`, `token_limit=16000` | str: full document text | Full text retrieval |
| `docs_answer_question` | `DocIndex.load_local().get_short_answer()` | `user_email`, `doc_storage_path`, `question` | str: LLM-generated answer | RAG-style Q&A over doc |
| `docs_get_global_doc_info` | `database/global_docs.get_global_doc()` + DocIndex | `user_email`, `doc_id` | JSON: {doc_id, display_name, title, short_summary, doc_storage_path, source} | Global doc metadata |
| `docs_query_global_doc` | `DocIndex.load_local().semantic_search_document()` (via global doc storage) | `user_email`, `doc_id`, `query`, `token_limit=4096` | str: relevant passages | Semantic search in global doc |
| `docs_get_global_doc_full_text` | `DocIndex.load_local().get_raw_doc_text()` | `user_email`, `doc_id`, `token_limit=16000` | str: full text | Full text of global doc |

**Path resolution**:
- Conversation docs: `DocIndex.load_local(doc_storage_path)` where `doc_storage_path` comes from doc metadata in `docs_list_conversation_docs`.
- Global docs: load doc from DB → get `doc_storage` field → `DocIndex.load_local(doc_storage)`.

**Cache note**: Consider a simple LRU cache keyed by `doc_storage_path` to avoid repeated deserialization for the same doc within a session.

### 3.6 Artefacts MCP Server (`mcp_server/artefacts.py`, port 8103)

**CRITICAL**: Artefacts are the **only file creation mechanism** in the system. The model MUST use these tools to produce any persistent output (documents, code, reports, notes). OpenCode can also directly edit the artefact files using its built-in bash/edit tools once it has the absolute file path.

**Environment variables**: `ARTEFACTS_MCP_ENABLED` (default `true`), `ARTEFACTS_MCP_PORT` (default `8103`)

**Initialization**: Each tool call loads the conversation via `Conversation.load_local(conversation_folder)` where `conversation_folder = os.path.join(STORAGE_DIR, "conversations", conversation_id)`.

**Confirmed Conversation.py method signatures** (read directly from source):
```python
conv.list_artefacts() -> list  # list of metadata dicts (no content)
conv.create_artefact(name: str, file_type: str, initial_content: str = "") -> dict  # metadata + "content" key
conv.get_artefact(artefact_id: str) -> dict  # metadata + "content" key (reads file from disk)
conv.update_artefact_content(artefact_id: str, content: str) -> dict  # metadata + "content" key
conv.delete_artefact(artefact_id: str) -> None
conv.artefacts_path  # property: os.path.join(conv._storage, "artefacts")  ← absolute dir path
# Full file path = os.path.join(conv.artefacts_path, entry["file_name"])
```

**Tool Inventory** (baseline tier: 7, full tier: 9):

| Tool | Tier | Conversation method | Params | Returns | Notes |
|------|------|---------------------|--------|---------|-------|
| `artefacts_list` | baseline | `conv.list_artefacts()` | `user_email`, `conversation_id` | JSON: list of {id, name, file_type, file_name, created_at, updated_at, size_bytes} | List all artefacts |
| `artefacts_create` | baseline | `conv.create_artefact()` | `user_email`, `conversation_id`, `name`, `file_type`, `initial_content=""` | JSON: {id, name, file_type, file_name, created_at, updated_at, size_bytes, content, file_path} | **Primary file creation tool**. Returns `file_path` so OpenCode can directly edit with bash/edit tools. |
| `artefacts_get` | baseline | `conv.get_artefact()` | `user_email`, `conversation_id`, `artefact_id` | JSON: metadata + content + `file_path` (absolute) | Read content + metadata + filesystem path |
| `artefacts_get_file_path` | baseline | `conv.artefacts_path` + `entry["file_name"]` | `user_email`, `conversation_id`, `artefact_id` | str: absolute file path | **Key for OpenCode direct edits** — returns path like `/storage/conversations/{id}/artefacts/name-uuid.md` |
| `artefacts_update` | baseline | `conv.update_artefact_content()` | `user_email`, `conversation_id`, `artefact_id`, `content` | JSON: metadata + content | Overwrite full content via MCP (alternative to direct file edit) |
| `artefacts_delete` | baseline | `conv.delete_artefact()` | `user_email`, `conversation_id`, `artefact_id` | JSON: {success: true} | Delete file + metadata |
| `artefacts_propose_edits` | full | HTTP `POST /artefacts/{conv_id}/{art_id}/propose_edits` | `user_email`, `conversation_id`, `artefact_id`, `instruction`, `selection_start_line=None`, `selection_end_line=None` | JSON: {proposed_ops, diff_text, base_hash, new_hash} | LLM-generated edit proposal with diff. Only in full tier — OpenCode can use bash edit directly instead. |
| `artefacts_apply_edits` | full | HTTP `POST /artefacts/{conv_id}/{art_id}/apply_edits` | `user_email`, `conversation_id`, `artefact_id`, `base_hash`, `ops: list` | JSON: {success, content} | Apply proposed ops if hash matches. Only in full tier. |
| `artefacts_get_message_link` | full | HTTP `GET /artefacts/{conv_id}/message_links` | `user_email`, `conversation_id` | JSON: message->artefact link map | Only in full tier. |

**File types supported**: `md`, `txt`, `py`, `js`, `json`, `html`, `css`

**Why `artefacts_get_file_path` is critical**: OpenCode has bash and file-edit tools. Once the model knows the absolute path to an artefact file (e.g., `/home/user/storage/conversations/abc123/artefacts/report-uuid.md`), it can directly edit it with `sed`, `vim`, OpenCode's native edit tool, or any bash command. This is more powerful than only going through the MCP `artefacts_update` tool.

**Usage guidance for LLM** (injected in system prompt):
```
Artefacts are the ONLY way to create persistent files in this system.
- Use artefacts_create to create a new file (returns file_path for direct editing).
- Use artefacts_get_file_path to get the absolute path for an existing artefact.
- Use OpenCode's native edit/bash tools to edit artefacts directly via the file path.
- Use artefacts_update only when you want to replace full content via MCP.
File types: md, txt, py, js, json, html, css.
```

**Internal note on propose/apply**: For `artefacts_propose_edits` and `artefacts_apply_edits` (full tier only), call the Flask endpoint via HTTP (localhost). This avoids duplicating the LLM call logic. Use `requests.post(f"http://localhost:{FLASK_PORT}/artefacts/{conv_id}/{art_id}/propose_edits", ...)` with an internal service token.

### 3.7 Conversation MCP Server (`mcp_server/conversation.py`, port 8104)

**Environment variables**: `CONVERSATION_MCP_ENABLED` (default `true`), `CONVERSATION_MCP_PORT` (default `8104`)

**Tool Inventory** (7 tools):

| Tool | Underlying | Params | Returns | Notes |
|------|-----------|--------|---------|-------|
| `conv_get_memory_pad` | `GET /fetch_memory_pad/{conv_id}` | `user_email`, `conversation_id` | str: memory pad text | Per-conversation scratchpad |
| `conv_set_memory_pad` | `POST /set_memory_pad/{conv_id}` | `user_email`, `conversation_id`, `text` | JSON: {success} | Update scratchpad |
| `conv_get_history` | `GET /get_conversation_history/{conv_id}` | `user_email`, `conversation_id`, `query=""` | str: formatted history | Conversation history summary |
| `conv_get_messages` | `GET /list_messages_by_conversation/{conv_id}` | `user_email`, `conversation_id` | JSON: list of messages | Raw message list |
| `conv_get_user_detail` | `GET /get_user_detail` | `user_email` | str: user memory/bio | User's persistent memory |
| `conv_get_user_preference` | `GET /get_user_preference` | `user_email` | str: user preferences | User's preferences |
| `conv_set_user_detail` | `POST /modify_user_detail` | `user_email`, `text` | JSON: {success} | Update user memory |

**Implementation**: These tools call the Flask endpoints via HTTP (localhost) rather than direct Python calls. This keeps the MCP server decoupled from Flask's request context (session auth, etc.). Use an internal service auth token shared between the MCP server and Flask.

**Internal service token**: Set `FLASK_INTERNAL_TOKEN` env var. Flask endpoints check for this token in an `X-Internal-Token` header as an alternative to session auth.

**Alternative**: Call Python modules directly if they don't require Flask context. `Conversation.load_local()` and `memory_pad` property work fine without Flask context. Prefer direct Python calls where possible to avoid HTTP overhead.

### 3.8 Prompts + Actions MCP Server (`mcp_server/prompts_actions.py`, port 8105)

**Environment variables**: `PROMPTS_MCP_ENABLED` (default `true`), `PROMPTS_MCP_PORT` (default `8105`)

**Tool Inventory** (baseline tier: 3, full tier: 5):

| Tool | Tier | Underlying | Params | Returns | Notes |
|------|------|-----------|--------|---------|-------|
| `prompts_list` | baseline | `GET /get_prompts` | `user_email` | JSON: list of {name, description, category, tags} | List all saved prompts |
| `prompts_get` | baseline | `GET /get_prompt_by_name/{name}` | `user_email`, `name` | JSON: {name, content, metadata} | Get prompt content by name |
| `temp_llm_action` | baseline | `POST /temporary_llm_action` | `user_email`, `action_type`, `selected_text`, `conversation_id=None`, `user_message=None` | str: LLM response text | Ephemeral LLM action (explain, critique, expand, eli5) |
| `prompts_create` | full | `POST /create_prompt` | `user_email`, `name`, `content`, `description=None`, `category=None`, `tags=None` | JSON: {success, name} | Save new prompt |
| `prompts_update` | full | `PUT /update_prompt` | `user_email`, `name`, `content`, `description=None`, `category=None`, `tags=None` | JSON: {success, name} | Update existing prompt |

**Action types for `temp_llm_action`**: `explain`, `critique`, `expand`, `eli5`, `ask_temp`

**Implementation**: Call Flask endpoints via HTTP (localhost). `temp_llm_action` is a streaming endpoint — collect all chunks and concatenate before returning.

### 3.9 Code Runner MCP Server (`mcp_server/code_runner_mcp.py`, port 8106)

**Added per user request**. Exposes the project's Python sandboxed code runner as an MCP tool. While OpenCode has bash built-in, this tool runs code inside the **project's own IPython persistent environment** — useful for data analysis, plotting, and computation that needs access to project-installed libraries (pandas, numpy, scikit-learn, etc.) and the project's own Python packages.

**Environment variables**: `CODE_RUNNER_MCP_ENABLED` (default `true`), `CODE_RUNNER_MCP_PORT` (default `8106`)

**Confirmed `run_code_once` signature** (from code_runner.py):
```python
def run_code_once(code_string: str, session=None) -> flask.Response:
    # Runs via PythonEnvironmentWithForceKill(), timeout=120s
    # Returns format_execution_output_for_ui(success, failure_reason, stdout, stderr)
    # → JSON Response with execution result formatted for UI display
```

**Tool Inventory** (1 tool, both tiers):

| Tool | Tier | Underlying | Params | Returns | Notes |
|------|------|-----------|--------|---------|-------|
| `run_python_code` | baseline | `run_code_once(code_string)` | `user_email`, `code_string` | str: formatted output (stdout, stderr, success/failure) | Python-only. 120s timeout. IPython environment with project libraries. |

**Why this differs from OpenCode's bash tool**:
- Runs inside the project's Python environment (conda `science-reader` env)
- Has access to all project-installed packages (pandas, numpy, scikit-learn, matplotlib, etc.)
- Uses IPython with persistent state across calls within a session
- Output is cleaned/formatted for readability by an LLM post-processor

**Implementation**: Direct Python call to `run_code_once(code_string)`. The function returns a Flask Response — extract `.get_data(as_text=True)` to get the string output.

**Note**: The endpoint (`POST /run_code_once`) is session-auth protected. The MCP tool calls `run_code_once()` directly as a Python function (no HTTP), which avoids auth.

---

## 4. Complete Tool Inventory and Tiering

### 4.1 Single Token Auth (No Extra Setup)

All MCP servers share one `MCP_JWT_SECRET` and one token. No additional setup beyond what already exists:

```bash
# One-time setup (same as today for web search MCP):
export MCP_JWT_SECRET="your-secret-here"
python -m mcp_server.auth --email opencode@system --days 3650
# Copy the token → paste into opencode.json MCP headers
```

The single token goes into `opencode.json` headers for ALL 6 MCP servers (same token, different URLs). This matches the existing ops pattern in `documentation/product/ops/mcp_server_setup.md`.

### 4.2 Tiered Tooling System

Tools are organized into two tiers controlled by `MCP_TOOL_TIER` env var:

| Tier | Env value | Tool count | Use case |
|------|-----------|------------|----------|
| **Baseline** | `MCP_TOOL_TIER=baseline` (default) | ~25 tools | Core functionality. Fast startup, lean context. |
| **Full** | `MCP_TOOL_TIER=full` | ~45 tools | All tools. When you need everything. |

Per-server enable/disable (independent of tier):

| Server | Env var | Default | Port |
|--------|---------|---------|------|
| Web Search | `MCP_ENABLED` | `true` | 8100 |
| PKB | `PKB_MCP_ENABLED` | `true` | 8101 |
| Documents | `DOCS_MCP_ENABLED` | `true` | 8102 |
| Artefacts | `ARTEFACTS_MCP_ENABLED` | `true` | 8103 |
| Conversation | `CONVERSATION_MCP_ENABLED` | `true` | 8104 |
| Prompts/Actions | `PROMPTS_MCP_ENABLED` | `true` | 8105 |
| Code Runner | `CODE_RUNNER_MCP_ENABLED` | `true` | 8106 |

Implementation: Each `create_*_mcp_app()` function reads `MCP_TOOL_TIER` at startup and registers only the tools for that tier:

```python
# In create_pkb_mcp_app():
tier = os.getenv("MCP_TOOL_TIER", "baseline")
is_full = tier == "full"

@mcp.tool()
def pkb_search(user_email: str, query: str, k: int = 20) -> str:
    ...  # always registered (baseline)

if is_full:
    @mcp.tool()
    def pkb_get_claims_by_ids(user_email: str, claim_ids: list) -> str:
        ...  # only in full tier
```

### 4.3 Baseline Tier (25 tools — default)

| # | Tool | Server | What it does |
|---|------|--------|--------------|
| 1 | `pkb_search` | pkb | Search PKB by query (hybrid FTS5 + embeddings) |
| 2 | `pkb_get_claim` | pkb | Get single claim by ID |
| 3 | `pkb_resolve_reference` | pkb | Resolve @friendly_id to claims/context/entity/tag |
| 4 | `pkb_get_pinned_claims` | pkb | Get globally pinned claims |
| 5 | `pkb_add_claim` | pkb | Add new memory/claim (write) |
| 6 | `pkb_edit_claim` | pkb | Edit existing claim (write) |
| 7 | `docs_list_conversation_docs` | docs | List documents attached to a conversation |
| 8 | `docs_list_global_docs` | docs | List user's global documents |
| 9 | `docs_query` | docs | Semantic search within a document |
| 10 | `docs_get_full_text` | docs | Get full text of a document |
| 11 | `artefacts_list` | artefacts | List all artefacts in a conversation |
| 12 | `artefacts_create` | artefacts | **Create file** (returns absolute path for direct editing) |
| 13 | `artefacts_get` | artefacts | Get artefact content + metadata + absolute file path |
| 14 | `artefacts_get_file_path` | artefacts | Get absolute filesystem path for an artefact |
| 15 | `artefacts_update` | artefacts | Overwrite artefact content via MCP |
| 16 | `artefacts_delete` | artefacts | Delete artefact |
| 17 | `conv_get_memory_pad` | conversation | Read per-conversation scratchpad |
| 18 | `conv_set_memory_pad` | conversation | Write to per-conversation scratchpad |
| 19 | `conv_get_history` | conversation | Get formatted conversation history/summary |
| 20 | `conv_get_user_detail` | conversation | Get user's persistent memory/bio |
| 21 | `conv_get_user_preference` | conversation | Get user's preferences |
| 22 | `prompts_list` | prompts_actions | List saved prompts |
| 23 | `prompts_get` | prompts_actions | Get prompt content by name |
| 24 | `temp_llm_action` | prompts_actions | Run ephemeral LLM action (explain/critique/expand/eli5) |
| 25 | `run_python_code` | code_runner | Run Python code in project's IPython environment |

**Total baseline: 25 tools** (+ 5 web search tools = 30 visible to OpenCode)

### 4.4 Full Tier Additional Tools (+20, total 45)

| # | Tool | Server | What it does | Why deferred |
|---|------|--------|--------------|-------------|
| 26 | `pkb_autocomplete` | pkb | Prefix search across PKB object types | Nice-to-have, search covers main use case |
| 27 | `pkb_get_claims_by_ids` | pkb | Batch get multiple claims | Rarely needed directly |
| 28 | `pkb_resolve_context` | pkb | Get full context tree with all claims | Large payloads; search is better |
| 29 | `pkb_pin_claim` | pkb | Pin/unpin claim for prominence | Low frequency operation |
| 30 | `docs_get_info` | docs | Doc metadata without content | Covered by list tools |
| 31 | `docs_answer_question` | docs | LLM Q&A over a document | Expensive (LLM call); use docs_query instead |
| 32 | `docs_get_global_doc_info` | docs | Global doc metadata | Covered by list tools |
| 33 | `docs_query_global_doc` | docs | Semantic search in global doc | Listed separately for clarity but redundant with docs_query |
| 34 | `docs_get_global_doc_full_text` | docs | Full text of global doc | Listed separately for clarity |
| 35 | `artefacts_propose_edits` | artefacts | LLM edit proposal with diff (propose/apply flow) | OpenCode can edit directly via file path |
| 36 | `artefacts_apply_edits` | artefacts | Apply proposed ops if hash matches | Paired with propose_edits |
| 37 | `artefacts_get_message_link` | artefacts | Get message->artefact link map | Rarely needed by model |
| 38 | `conv_get_messages` | conversation | Raw message list | History summary covers most use cases |
| 39 | `conv_set_user_detail` | conversation | Update user memory (write) | Risky — model editing user bio autonomously |
| 40 | `prompts_create` | prompts_actions | Save new prompt | Write operation; low frequency |
| 41 | `prompts_update` | prompts_actions | Update existing prompt | Write operation; low frequency |

(Items 42-45 reserved for future features)

### 4.5 Permanently Skipped Tools (not in any tier)

| Feature | Tools not implementing | Reason |
|---------|----------------------|--------|
| Workspaces | create/list/move/delete workspace | UI-only organizational feature; no agentic value |
| Cross-conversation references | resolve cross-conv ref | Complex `@conversation_X_message_Y` syntax; model can use conv_get_history instead |
| Sections/hidden-details | get/update section | UI state only; invisible to model in chat |
| Doubts/takeaways CRUD | get_doubt, list_doubts, delete_doubt | Auto-generated by system; model doesn't need to manage them |
| Conversation lifecycle | create/delete/clone/stateful/stateless | Dangerous for autonomous model execution |
| Audio / TTS | tts, transcribe | Text-only agentic flows |
| File attachments (upload) | upload_doc | Binary upload; browser-initiated, can't do over MCP |
| Suggestion generation | get_next_question_suggestions | Passive UI feature |
| Cancellation endpoints | cancel_response | Session management only |
| Conversation editing | edit_message, move_messages, show_hide | UI manipulation only |

---

## 5. Implementation Plan

### Milestone 0: MCP Sub-Modules (FIRST — prerequisite for everything)

**Goal**: Implement all 5 new MCP sub-modules under `mcp_server/`. This must be done before the OpenCode client library, because OpenCode needs the MCP servers registered in `opencode.json` to call tools.

**Risk**: Conversation.load_local() may require Flask app context. Mitigation: test in isolation; fall back to HTTP calls to Flask endpoints if direct Python calls don't work.

#### Task 0.1: Create `mcp_server/pkb.py` (port 8101)

- Create file with `create_pkb_mcp_app()` and `start_pkb_mcp_server()` functions
- Implement all 10 PKB tools (see §3.4)
- StructuredAPI initialized once at server startup via `_get_pkb_api()` helper
- Each tool calls `api.for_user(user_email)` to scope to requesting user
- ActionResult serialized to JSON string

**Files to create**: `mcp_server/pkb.py`

#### Task 0.2: Create `mcp_server/docs.py` (port 8102)

- Create file with `create_docs_mcp_app()` and `start_docs_mcp_server()` functions
- Implement all 9 document tools (see §3.5)
- Use `DocIndex.load_local(doc_storage_path).set_api_keys(keys)` per call
- Global docs: query `database/global_docs` functions for doc metadata
- `set_api_keys()` called with `keyParser({})` result

**Files to create**: `mcp_server/docs.py`

#### Task 0.3: Create `mcp_server/artefacts.py` (port 8103)

- Create file with `create_artefacts_mcp_app()` and `start_artefacts_mcp_server()` functions
- Implement all 9 artefact tools (see §3.6)
- Direct Python calls: `Conversation.load_local(folder)` for list/create/read/update/delete/metadata
- HTTP calls to Flask for propose_edits/apply_edits (these invoke LLM internally)
- FLASK_PORT env var (default `5000`) for localhost calls
- Add CRITICAL docstrings emphasizing this is the ONLY way to create files

**Files to create**: `mcp_server/artefacts.py`

#### Task 0.4: Create `mcp_server/conversation.py` (port 8104)

- Create file with `create_conversation_mcp_app()` and `start_conversation_mcp_server()` functions
- Implement all 7 conversation/memory tools (see §3.7)
- Prefer direct Python calls: `Conversation.load_local(folder)` + `.memory_pad` property
- User detail/preference: direct DB calls via `database/users.py` functions if available; otherwise HTTP to Flask

**Files to create**: `mcp_server/conversation.py`

#### Task 0.5: Create `mcp_server/prompts_actions.py` (port 8105)

- Create file with `create_prompts_actions_mcp_app()` and `start_prompts_actions_mcp_server()` functions
- Implement all 5 prompt + action tools (see §3.8)
- Prompts: direct DB calls via `database/prompts.py` functions if available
- `temp_llm_action`: HTTP call to Flask endpoint (streaming — collect and join)

**Files to create**: `mcp_server/prompts_actions.py`

#### Task 0.6: Update `mcp_server/__init__.py`

Add imports and `start_*_mcp_server()` functions for all 5 new sub-modules.

The updated module docstring lists all 6 servers with their ports and env vars.

**Files to modify**: `mcp_server/__init__.py`

#### Task 0.7: Update `server.py` to launch new MCP servers

Add 5 new calls in `server.py:main()` alongside the existing `start_mcp_server()` call.

**Files to modify**: `server.py`

#### Task 0.8: Create `opencode.json`

Create the OpenCode config file in project root, registering all 6 MCP servers (5 new + existing web search), with permissions and default model.

**Files to create**: `opencode.json`

#### Task 0.9: Test each MCP server independently

For each server:
1. Start Flask + that MCP server in isolation
2. Call each tool via `curl` or Python MCP client
3. Verify correct data returned
4. Verify JWT auth works (401 on missing token, 200 on valid)
5. Verify user scoping (user A cannot see user B's data)

---

### Milestone 1: OpenCode Client Library (Foundation)

**Goal**: Create a Python HTTP client that talks to `opencode serve` and translates SSE events to the Flask streaming format.

**Risk**: SSE event format may have undocumented behaviors. Mitigation: test against running `opencode serve` instance early.

#### Task 1.1: Create `opencode_client/` package structure

Create the package skeleton:

```
opencode_client/
    __init__.py              # Public API exports
    client.py                # OpencodeClient class (HTTP operations)
    sse_bridge.py            # SSE -> newline-delimited JSON translator
    session_manager.py       # Conversation-to-session mapping
    config.py                # Configuration constants
```

**Files to create**: `opencode_client/__init__.py`, `opencode_client/client.py`, `opencode_client/sse_bridge.py`, `opencode_client/session_manager.py`, `opencode_client/config.py`

**Dependencies to add**: `sseclient-py` (or `httpx-sse`) for SSE parsing, `httpx` for async HTTP (or `requests` for sync).

#### Task 1.2: Implement `OpencodeClient` class

Core HTTP client wrapping OpenCode's REST API:

```python
class OpencodeClient:
    def __init__(self, base_url="http://localhost:4096", username="opencode", password=None):
        ...

    # Session management
    def create_session(self, title=None, parent_id=None) -> dict: ...
    def get_session(self, session_id) -> dict: ...
    def list_sessions(self) -> List[dict]: ...
    def delete_session(self, session_id) -> bool: ...
    def update_session(self, session_id, title=None) -> dict: ...
    def abort_session(self, session_id) -> bool: ...
    def fork_session(self, session_id, message_id=None) -> dict: ...
    def summarize_session(self, session_id, provider_id, model_id) -> bool: ...
    def get_session_status(self) -> dict: ...
    def get_session_children(self, session_id) -> List[dict]: ...
    def get_session_diff(self, session_id, message_id=None) -> List[dict]: ...
    def get_session_todos(self, session_id) -> List[dict]: ...
    def revert_message(self, session_id, message_id, part_id=None) -> bool: ...
    def unrevert_session(self, session_id) -> bool: ...

    # Messaging
    def send_message_sync(self, session_id, parts, model=None, agent=None,
                          system=None, tools=None, no_reply=False, format=None) -> dict: ...
    def send_message_async(self, session_id, parts, model=None, agent=None,
                           system=None, tools=None, no_reply=False) -> None: ...
    def send_context(self, session_id, text, system=None) -> None:
        """Send a noReply message to inject context without triggering AI response."""
        ...
    def get_messages(self, session_id, limit=None) -> List[dict]: ...
    def get_message(self, session_id, message_id) -> dict: ...

    # Commands and Shell
    def execute_command(self, session_id, command, arguments="", agent=None, model=None) -> dict: ...
    def run_shell(self, session_id, command, agent, model=None) -> dict: ...

    # SSE streaming
    def stream_events(self, session_id=None) -> Generator[dict, None, None]: ...

    # Permissions
    def respond_permission(self, session_id, permission_id, response, remember=False) -> bool: ...

    # Health
    def health_check(self) -> dict: ...

    # Config
    def get_config(self) -> dict: ...
    def update_config(self, patch) -> dict: ...
    def get_providers(self) -> dict: ...

    # MCP (dynamic registration)
    def get_mcp_status(self) -> dict: ...
    def add_mcp_server(self, name, config) -> dict: ...

    # Agents
    def list_agents(self) -> List[dict]: ...

    # Sharing
    def share_session(self, session_id) -> dict: ...
    def unshare_session(self, session_id) -> dict: ...
```

**Key implementation notes**:
- `send_message_async` calls `POST /session/{id}/prompt_async` (returns 204 immediately).
- `send_context` calls `send_message_async` with `no_reply=True` — injects context without triggering AI response.
- `model` parameter is an object: `{ "providerID": "anthropic", "modelID": "claude-sonnet-4-5" }`, not a string.
- `stream_events` connects to `GET /event` SSE endpoint (global stream), yields parsed event dicts.
- All methods handle HTTP basic auth via `username`/`password` (env vars: `OPENCODE_SERVER_USERNAME`, `OPENCODE_SERVER_PASSWORD`).
- Timeout handling: LLM calls can take minutes; use generous timeouts.
- `fork_session` is useful for branching conversations (fork at a specific message).
- `summarize_session` requires `providerID` and `modelID` — used for context compaction.
- `add_mcp_server` calls `POST /mcp` for dynamic MCP registration at runtime.
- `execute_command` calls `POST /session/{id}/command` — used for `/oc_compact`, etc.
- `abort_session` calls `POST /session/{id}/abort` — immediately stops generation.

**Files to modify**: `opencode_client/client.py`

#### Task 1.3: Implement `SSEBridge` class

Translates OpenCode SSE events to Flask streaming chunks:

```python
class SSEBridge:
    def __init__(self, client: OpencodeClient, session_id: str):
        ...

    def stream_response(self) -> Generator[dict, None, None]:
        """
        Yields: {"text": "...", "status": "..."} dicts
        Filters SSE events for the target session_id.
        Handles text deltas, tool status, errors, completion.
        """
        ...
```

**Key implementation notes**:
- Filter events by `properties.part.sessionID == self.session_id` or `properties.sessionID == self.session_id`.
- Track text parts by `part.id` for delta accumulation.
- Detect completion via `session.idle` event for the target session.
- Handle `permission.updated` events by auto-approving via `POST /session/{id}/permissions/{permissionID}`.
- Handle reconnection if SSE connection drops.

**Files to modify**: `opencode_client/sse_bridge.py`

#### Task 1.4: Implement `SessionManager` class

Maps conversation IDs to OpenCode session IDs:

```python
class SessionManager:
    def __init__(self, client: OpencodeClient):
        ...

    def get_or_create_session(self, conversation_id, conversation_settings) -> str:
        """Get existing session_id or create new one."""
        ...

    def create_new_session(self, conversation_id, title=None) -> str:
        """Force-create a new session for conversation."""
        ...

    def list_sessions_for_conversation(self, conversation_id) -> List[dict]:
        """List all sessions attached to a conversation."""
        ...

    def switch_session(self, conversation_id, session_id) -> bool:
        """Switch active session for a conversation."""
        ...
```

**Key implementation notes**:
- Session IDs stored in `conversation_settings.opencode_config.session_ids` (list) and `conversation_settings.opencode_config.active_session_id` (string).
- Uses Conversation's existing `get_conversation_settings()` / `set_conversation_settings()` for persistence.

**Files to modify**: `opencode_client/session_manager.py`

#### Task 1.5: Integration test with live `opencode serve`

Manual verification:
1. Start `opencode serve --port 4096`
2. Run a Python script that creates a session, sends a message, and streams the response
3. Verify SSE events are received and translated correctly
4. Verify tool calls appear in the event stream (e.g., ask OpenCode to list files)

**Deliverable**: Working standalone test script in `opencode_client/test_integration.py`

---

### Milestone 2: Conversation.py Integration

**Goal**: Add OpenCode routing to `Conversation.reply()` as an alternative to direct `call_llm`.

**Risk**: This is the most complex milestone -- touches the core streaming pipeline. Mitigation: OpenCode mode is opt-in; non-OpenCode path stays completely unchanged.

#### Task 2.1: Add OpenCode settings to conversation configuration

Add new settings to the checkboxes dict and conversation_settings:

**Per-message settings (checkboxes)**:
- `opencode_enabled`: boolean (default: `false`) -- route this message through OpenCode
- `opencode_model`: string (optional) -- override model for this message

**Per-conversation settings (conversation_settings.opencode_config)**:
- `session_ids`: List[str] -- all OpenCode session IDs for this conversation
- `active_session_id`: str -- currently active session
- `injection_level`: str -- "minimal" / "medium" / "full" (default: "medium")
- `opencode_model`: str -- default model for OpenCode (overridable per-message)
- `always_enabled`: bool -- always use OpenCode for this conversation (default: false)

**Files to modify**:
- `interface/interface.html` -- add OpenCode checkbox and settings to chat-settings-modal
- `interface/common.js` `getOptions()` -- collect `opencode_enabled`, `opencode_model`
- `endpoints/conversations.py` `set_conversation_settings()` -- allow `opencode_config` key
- `Conversation.py` -- read new settings in `reply()`

#### Task 2.2: Create OpenCode routing branch in `reply()`

Add a new branch in `Conversation.reply()` (around line 5576 where checkboxes are read):

```python
# After existing checkboxes extraction (line ~5576)
opencode_enabled = checkboxes.get("opencode_enabled", False)

# Check conversation-level setting as fallback
if not opencode_enabled:
    oc_config = self.get_conversation_settings().get("opencode_config", {})
    opencode_enabled = oc_config.get("always_enabled", False)

if opencode_enabled:
    yield from self._reply_via_opencode(query, userData, checkboxes, **kwargs)
    return
# ... existing reply logic continues unchanged ...
```

**Files to modify**: `Conversation.py`

#### Task 2.3: Implement `_reply_via_opencode()` method

New method in Conversation class. This is the core integration point:

```python
def _reply_via_opencode(self, query, userData, checkboxes, **kwargs):
    """Route the reply through OpenCode server instead of direct LLM call.
    
    Flow:
    1. Get or create OpenCode session
    2. Assemble context based on injection_level
    3. Send system prompt (identity + MCP instructions) if new session
    4. Send context as noReply message (if new context available)
    5. Send user message via prompt_async
    6. Stream SSE events and translate to Flask format
    7. Apply math formatting to accumulated text
    8. Generate TLDR if needed
    9. Generate message_ids and persist
    """
    ...
```

**Key implementation details**:
- `_assemble_opencode_context()` builds the system prompt with injected context based on `injection_level`.
- `_build_opencode_system_prompt()` includes user identity (`user_email`), conversation summary, injected PKB/doc context, and instructions for MCP tool usage (e.g., "The user's email is X. Pass it as user_email when calling PKB or document tools.").
- `_resolve_opencode_model()` resolves model from checkboxes -> conversation_settings -> default.
- Math formatting applied to each delta (reusing `process_math_formatting` from `math_formatting.py`).
- TLDR generation reuses existing logic from `reply()`.
- Persistence reuses existing `persist_current_turn` pattern.
- Cancellation checked on each event loop iteration via `self.is_cancelled()`.

**Files to modify**: `Conversation.py`

#### Task 2.4: Implement context assembly helpers

```python
def _assemble_opencode_context(self, query, injection_level):
    """Build context parts to inject as noReply message based on injection level.
    
    Parameters
    ----------
    query : dict
        The user's query dict with messageText, checkboxes, etc.
    injection_level : str
        "minimal", "medium", or "full"
    
    Returns
    -------
    str or None
        Context text to send as noReply message, or None if no context to inject.
    """
    parts = []
    
    # Always include conversation history summary
    summary = self.get_running_summary()
    if summary:
        parts.append(f"[CONVERSATION HISTORY SUMMARY]\n{summary}")

    if injection_level in ("medium", "full"):
        # PKB distillation (same as existing _get_pkb_context flow)
        if query.get("checkboxes", {}).get("use_pkb", True):
            pkb_context = self._get_pkb_context_for_opencode(query)
            if pkb_context:
                parts.append(f"[USER'S PERSONAL KNOWLEDGE]\n{pkb_context}")

        # Referenced documents
        doc_context = self._get_doc_context_for_opencode(query)
        if doc_context:
            parts.append(f"[REFERENCED DOCUMENTS]\n{doc_context}")

    if injection_level == "full":
        # Memory pad
        memory_pad = self.get_memory_pad()
        if memory_pad:
            parts.append(f"[MEMORY PAD]\n{memory_pad}")
        # Full recent messages
        recent = self._get_recent_messages_text(limit=10)
        if recent:
            parts.append(f"[RECENT MESSAGES]\n{recent}")

    return "\n\n---\n\n".join(parts) if parts else None
```

**Files to modify**: `Conversation.py`

#### Task 2.5: Add OpenCode command routing (no /oc_ prefix)

When OpenCode mode is enabled, slash commands route directly to OpenCode without an `/oc_` prefix. Commands are detected in `reply()` after the existing `/title` and `/temp` handlers (which always run regardless of mode), and before the OpenCode routing branch.

**Command routing logic** (in `reply()`, after line 5920):
```python
# Only when OpenCode mode is active
if opencode_enabled:
    opencode_commands = {
        "/compact": lambda: self._opencode_command("compact"),
        "/abort": lambda: self._opencode_abort(),
        "/new": lambda: self._opencode_new_session(),
        "/sessions": lambda: self._opencode_list_sessions(),
        "/fork": lambda: self._opencode_command("fork"),
        "/summarize": lambda: self._opencode_summarize(),
        "/status": lambda: self._opencode_status(),
        "/diff": lambda: self._opencode_diff(),
        "/revert": lambda: self._opencode_revert(),
        "/mcp": lambda: self._opencode_mcp_status(),
        "/models": lambda: self._opencode_models(),
        "/help": lambda: self._opencode_help(),
    }
    
    msg_text = query["messageText"].strip()
    cmd_word = msg_text.split()[0] if msg_text.startswith("/") else None
    
    if cmd_word and cmd_word in opencode_commands:
        yield from opencode_commands[cmd_word]()
        return
    elif cmd_word and cmd_word.startswith("/") and cmd_word not in ("/title", "/set_title", "/temp", "/temporary"):
        # Unknown slash command — pass through to OpenCode as-is
        yield from self._opencode_passthrough_command(msg_text)
        return
```

**Conflict resolution:**
- `/title`, `/set_title`, `/temp`, `/temporary` — always handled locally (lines 5886-5920), checked BEFORE OpenCode commands
- Known OpenCode commands (`/compact`, `/abort`, etc.) — handled by dedicated methods
- Unknown `/` commands — passed through to OpenCode via `POST /session/{id}/command`
- Non-slash messages — routed to `_reply_via_opencode()` for normal conversation
**Files to modify**: `Conversation.py`

#### Task 2.6: Integration testing

Test the complete flow:
1. Enable OpenCode mode on a conversation
2. Send a message -- verify it routes through OpenCode
3. Verify streaming works (text arrives incrementally)
4. Verify tool calls appear as status updates
5. Verify PKB MCP tools are called when model decides to query memory
6. Verify document MCP tools work
7. Verify artefact creation works (model uses artefacts_create)
8. Verify TLDR generates for long responses
9. Verify math formatting works
10. Verify message persistence works
11. Verify cancellation works
12. Verify non-OpenCode conversations are unaffected

---

### Milestone 3: UI Integration

**Goal**: Add OpenCode controls to the chat UI.

#### Task 3.1: Add OpenCode controls to chat settings modal

**A. OpenCode toggle in Basic Options section:**
Insert after line 2053 of `interface/interface.html` (after "Use PKB Memory" checkbox), following the existing `col-md-3` pattern:
```html
<div class="col-md-3">
    <div class="form-check mb-2">
        <input class="form-check-input" id="settings-enable_opencode" type="checkbox">
        <label class="form-check-label" for="settings-enable_opencode">
            <strong style="color:#6f42c1;">⚡ OpenCode</strong>
        </label>
    </div>
</div>
```

**B. OpenCode Settings button in Actions section:**
Insert after line 2180 of `interface/interface.html` (after "Model Overrides" button), following the existing `col` pattern:
```html
<div class="col">
    <button class="btn btn-outline-primary btn-sm rounded-pill w-100" id="settings-opencode-modal-open-button">
        <i class="bi bi-terminal"></i> OpenCode
    </button>
</div>
```

**C. OpenCode Settings modal:**
Insert after line 2424 of `interface/interface.html` (after model-overrides-modal), following the same Bootstrap modal pattern:
- Modal ID: `opencode-settings-modal`
- Z-index: 1070 (higher than model-overrides at 1065)
- Contents:
  - Toggle: "Always use OpenCode" → maps to `opencode_config.always_enabled`
  - Dropdown: "Context Injection Level" → maps to `opencode_config.injection_level` (minimal/medium/full)
  - MCP Server toggles: 6 checkboxes for PKB/Docs/Artefacts/Conversation/Prompts/Code Runner enable/disable
  - Session info display: current session ID, session count
  - Button: "New Session" → creates fresh OpenCode session
  - Button: "Open Full OpenCode UI" → opens the full UI modal (§12)

**D. Button event handler:**
Add to `interface/chat.js` (after existing model-overrides handler around line 311):
```javascript
$('#settings-opencode-modal-open-button').click(function() {
    if (!ConversationManager.activeConversationId) {
        showToast('Select a conversation first', 'warning');
        return;
    }
    loadOpencodeSettings(ConversationManager.activeConversationId);
    $('#opencode-settings-modal').modal('show');
});
```

**Files to modify**: `interface/interface.html`, `interface/chat.js`

#### Task 3.2: Wire up settings collection

Update `getOptions()` in `interface/common.js` to collect:
- `opencode_enabled` from the checkbox
- `opencode_model` from model selector (if different from main_model)

**Files to modify**: `interface/common.js`

#### Task 3.3: Add OpenCode session controls

Add UI elements for session management:
 Button to create new OpenCode session (sends `/new` via chat)
- Display current session ID in conversation info panel
- Session switcher (if multiple sessions exist)

**Files to modify**: `interface/common-chat.js`, `interface/interface.html`

#### Task 3.4: Per-conversation settings persistence

Extend the conversation settings modal to save OpenCode configuration:
- `opencode_config.always_enabled` -- always use OpenCode for this conversation
- `opencode_config.injection_level` -- context injection level
- `opencode_config.opencode_model` -- default model override

Uses existing `PUT /set_conversation_settings/<conversation_id>` endpoint.

**Files to modify**: `interface/chat.js` (settings persistence), `endpoints/conversations.py` (allow opencode_config key)

---

### Milestone 4: OpenCode Server Lifecycle

**Goal**: Manage the `opencode serve` process alongside the Flask server.

#### Task 4.1: OpenCode server startup strategy

**Recommended approach**: Require `opencode serve` to be started separately. This is simpler, more explicit, and allows independent restarts.

Alternative (future): Start `opencode serve` as a subprocess from `server.py:main()` using `subprocess.Popen`.

**Files to modify**: startup scripts, documentation

#### Task 4.2: Health check integration

Add OpenCode health check to Flask's startup sequence:
- On Flask startup, check `GET http://localhost:4096/global/health`
- If OpenCode is not running, log warning but don't block Flask startup
- OpenCode features are gracefully disabled if server is unreachable
- The `opencode_enabled` checkbox in the UI can be grayed out if health check fails

**Files to modify**: `server.py` or `endpoints/state.py`

#### Task 4.3: Documentation

- Add OpenCode setup instructions to operational docs
- Document environment variables needed
- Document the new chat settings and commands
- Update `documentation/features/` with OpenCode integration feature doc
- Update `documentation/README.md` with new feature entry

**Files to create**: `documentation/features/opencode_integration/README.md`

---

## 6. Milestones Summary and Dependencies

```
Milestone 0: MCP Sub-Modules ──────────────────────────────────────────┐
  (pkb, docs, artefacts, conversation, prompts_actions)                 │
                                                                        │
Milestone 1: OpenCode Client Library ──────────────────────────────┐   │
                                                                    │   │
                                                                    v   v
Milestone 2: Conversation.py Integration ──────────────────────────────┐
                                                                        │
Milestone 3: UI Integration <───────────────────────────────────────────┤
                                                                        │
Milestone 4: OpenCode Server Lifecycle <────────────────────────────────┘
```

- **Milestone 0** (MCP Sub-Modules) is first — OpenCode needs MCP servers to call tools.
- **Milestone 1** (Client Library) can be built in parallel with Milestone 0.
- **Milestone 2** depends on Milestone 1. It can start before Milestone 0 is complete.
- **Milestone 3** depends on Milestone 2.
- **Milestone 4** can start anytime but is most useful after Milestone 2.

---

## 7. Key Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OpenCode SSE event format changes between versions | Streaming bridge breaks | Pin OpenCode version; add event type validation with graceful fallback |
| OpenCode session context grows too large | Slow responses, context errors | Use `/oc_compact` command; set `injection_level` to `minimal` for long conversations |
| MCP tool latency adds to response time | Slower responses when model uses tools | Cache frequently-used PKB/doc data; set MCP server timeouts |
| Permission prompts block streaming | Response hangs waiting for approval | Auto-approve all permissions (all tools set to `allow` in opencode.json) |
| OpenCode server crashes mid-stream | Partial response, broken UI state | SSE bridge detects disconnect, yields error status, conversation falls back gracefully |
| Multiple users hitting same OpenCode session | Data leakage | Sessions are per-conversation; never share session IDs across users |
| Existing agents break when OpenCode mode is enabled | Feature regression | OpenCode mode is completely separate branch in reply(); existing agent path untouched |
| `noReply` messages consume context window | Large context injections reduce available tokens | Use injection_level "minimal" for token-constrained conversations; rely on MCP tools for on-demand context |
| Dynamic MCP registration fails silently | MCP tools unavailable | Health-check MCP servers on startup; retry dynamic registration; fall back to static config |
| Conversation.load_local() requires Flask app context | MCP servers can't call it directly | Test in isolation; fall back to HTTP calls to Flask endpoints if needed |
| artefacts_propose_edits calls LLM internally | Double-charging tokens, slow | Use HTTP call to Flask endpoint (which manages LLM keys correctly) |

---

## 8. Files Modified/Created Summary

### New Files
- `mcp_server/pkb.py` — PKB MCP server (port 8101)
- `mcp_server/docs.py` — Documents MCP server (port 8102)
- `mcp_server/artefacts.py` — Artefacts MCP server (port 8103)
- `mcp_server/conversation.py` — Conversation/memory MCP server (port 8104)
- `mcp_server/prompts_actions.py` — Prompts + actions MCP server (port 8105)
- `mcp_server/code_runner_mcp.py` — Code runner MCP server (port 8106)
- `opencode_client/__init__.py`
- `opencode_client/client.py`
- `opencode_client/sse_bridge.py`
- `opencode_client/session_manager.py`
- `opencode_client/config.py`
- `opencode_client/test_integration.py`
- `opencode.json`
- `documentation/features/opencode_integration/README.md`

### Modified Files
- `mcp_server/__init__.py` — Add 5 new `start_*_mcp_server()` imports + calls
- `server.py` — Add 5 new MCP server startup calls (5-10 lines total)
- `Conversation.py` — Add OpenCode routing branch, `_reply_via_opencode()`, context assembly helpers, command proxying
- `endpoints/conversations.py` — Allow `opencode_config` in conversation_settings
- `interface/interface.html` — Add OpenCode settings to chat-settings-modal
- `interface/common.js` — Collect OpenCode settings in `getOptions()`
- `interface/common-chat.js` — OpenCode session controls
- `interface/chat.js` — OpenCode settings persistence

### Unchanged Files (critical to verify)
- `call_llm.py` — No changes; still used for non-OpenCode conversations
- `code_common/call_llm.py` — No changes
- `mcp_server/mcp_app.py` — No changes to existing web search MCP
- `mcp_server/auth.py` — No changes; shared by all MCP servers
- `truth_management_system/` — No changes; PKB MCP server wraps it externally
- `DocIndex.py` — No changes; Documents MCP server wraps it externally
- All existing agents — No changes; agent routing only activates when `opencode_enabled` is false

---

## 9. Environment Variables

### New Variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENCODE_SERVER_URL` | `http://localhost:4096` | OpenCode server base URL |
| `OPENCODE_SERVER_PASSWORD` | (none) | HTTP basic auth password for OpenCode server |
| `OPENCODE_SERVER_USERNAME` | `opencode` | HTTP basic auth username for OpenCode server |
| `PKB_MCP_ENABLED` | `true` | Enable/disable PKB MCP server |
| `PKB_MCP_PORT` | `8101` | PKB MCP server port |
| `DOCS_MCP_ENABLED` | `true` | Enable/disable Documents MCP server |
| `DOCS_MCP_PORT` | `8102` | Documents MCP server port |
| `ARTEFACTS_MCP_ENABLED` | `true` | Enable/disable Artefacts MCP server |
| `ARTEFACTS_MCP_PORT` | `8103` | Artefacts MCP server port |
| `CONVERSATION_MCP_ENABLED` | `true` | Enable/disable Conversation MCP server |
| `CONVERSATION_MCP_PORT` | `8104` | Conversation MCP server port |
| `PROMPTS_MCP_ENABLED` | `true` | Enable/disable Prompts/Actions MCP server |
| `PROMPTS_MCP_PORT` | `8105` | Prompts/Actions MCP server port |
| `CODE_RUNNER_MCP_ENABLED` | `true` | Enable/disable Code Runner MCP server |
| `CODE_RUNNER_MCP_PORT` | `8106` | Code Runner MCP server port |
| `MCP_TOOL_TIER` | `baseline` | Tool tier: `baseline` (~25 tools) or `full` (~45 tools) |
| `FLASK_PORT` | `5000` | Flask server port (used by MCP servers for internal HTTP calls) |
| `MCP_JWT_TOKEN` | (generated) | Pre-generated JWT token for opencode.json MCP registration. Same token used for ALL MCP servers. |

### Existing Variables (reused)
| Variable | Purpose |
|----------|---------|
| `MCP_JWT_SECRET` | Shared JWT secret for ALL MCP servers (existing + new) |
| `MCP_RATE_LIMIT` | Rate limit for MCP calls (shared across all servers) |
| `MCP_ENABLED` | Enable/disable the existing web search MCP server (unchanged) |
| `MCP_PORT` | Port for existing web search MCP server (unchanged, 8100) |

---

## 10. Alternatives Considered

### Alternative A: Replace call_llm.py with OpenCode client directly
**Rejected**: Too invasive. Would require rewriting the entire CallLLm interface and breaking all non-OpenCode conversations. The opt-in branch approach preserves backwards compatibility.

### Alternative B: Run MCP servers as local (stdio) instead of remote (HTTP)
**Rejected**: Local MCP servers are per-process. Since OpenCode runs as a separate process, it can only talk to remote MCP servers. HTTP also allows separate scaling and monitoring.

### Alternative C: Use OpenCode's `opencode run` CLI instead of `opencode serve`
**Rejected**: `opencode run` is fire-and-forget with no session persistence. `opencode serve` provides session management, SSE streaming, and concurrent access -- all required for a multi-user Flask app.

### Alternative D: Embed OpenCode as a Python library
**Rejected**: OpenCode is written in Go/TypeScript, not Python. No native Python embedding available. The HTTP server API is the intended integration mechanism.

### Alternative E: Top-level separate packages (`pkb_mcp_server/`, `documents_mcp_server/`)
**Rejected**: User requested sub-modules under `mcp_server/`. Sub-modules share auth.py and reduce package sprawl while keeping per-port separation.

### Alternative F: Single MCP server (one port, all tools)
**Rejected**: Single server creates a monolith with no domain separation. Separate ports allow independent enable/disable and scaling. Also OpenCode's `opencode.json` allows per-server auth headers.

---

## 11. Integration Points Reference (from codebase analysis)

### Conversation.py Key Locations
- `__call__()` at line 4575 -- Entry point, yields `json.dumps(chunk) + "\n"`
- `reply()` at line 5441 -- Main reply method, generator that yields dicts
- Checkboxes extraction at line ~5576 -- Where `opencode_enabled` will be read
- Field/agent routing at lines ~5078-5267 -- Pattern to follow for OpenCode routing
- `get_conversation_settings()` at line ~1133 -- Persistent per-conversation config
- `set_conversation_settings()` at line ~1145 -- Save persistent config

### CallLLm Interface (unchanged, for reference)
- Constructor: `CallLLm(keys, model_name=None, use_gpt4=False, use_16k=False)`
- Call: `__call__(text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None)`
- Located in `call_llm.py` line 54

### Existing MCP Server Pattern (to replicate exactly)
- `mcp_server/__init__.py` -- `start_mcp_server()` with env var checks and daemon thread
- `mcp_server/mcp_app.py` -- FastMCP with `@mcp.tool()` decorators, Starlette middleware for JWT auth + rate limiting
- `mcp_server/auth.py` -- JWT verification/generation (`verify_jwt()`, `generate_token()`)
- `server.py` lines 371-373 -- Integration point (3 lines: import, call, continue)

### StructuredAPI (PKB) Key Methods for MCP
- `search(query, strategy="hybrid", k=20, filters=None)` -- Hybrid FTS5 + embedding search
- `resolve_reference(reference_id)` -- Suffix-based routing (_context, _entity, _tag, _domain)
- `get_pinned_claims(limit=50)` -- Globally pinned claims
- `autocomplete(prefix, limit=10)` -- Across all 5 object types
- `for_user(user_email)` -- Returns user-scoped API instance

### DocIndex Key Methods for MCP
- `DocIndex.load_local(folder)` -- Load serialized index from disk
- `semantic_search_document(query, token_limit)` -- FAISS-based semantic search
- `brief_summary` property -- Title + short summary
- `get_raw_doc_text()` -- Full document text
- `get_short_answer(query, mode)` -- LLM-generated answer from doc context
- `set_api_keys(keys)` -- Inject keys after loading

### Artefacts Key Methods (Conversation.py)
- `conv.create_artefact(name, file_type, initial_content)` -- Creates file + metadata
- `conv.list_artefacts()` -- Returns list of artefact metadata dicts
- `conv.get_artefact(artefact_id)` -- Returns metadata + file path
- `conv.get_artefact_content(artefact_id)` -- Returns file content string
- `conv.update_artefact(artefact_id, content)` -- Overwrites file content
- `conv.delete_artefact(artefact_id)` -- Deletes file + metadata
- Storage path: `storage/conversations/{conversation_id}/artefacts/`

### Conversation Memory and History
- `conv.memory_pad` -- property (get/set) for per-conversation scratchpad
- `conv.get_conversation_history(query="")` -- formatted history string
- `conv.get_message_list()` -- raw message list
- `conv.running_summary` -- auto-generated running summary
- Memory pad endpoints: `POST /set_memory_pad/{conv_id}`, `GET /fetch_memory_pad/{conv_id}`

### Global Docs DB Functions
- `database/global_docs.list_global_docs(user_hash)` -- list user's global docs
- `database/global_docs.get_global_doc(doc_id)` -- get single doc metadata
- Storage path: `storage/global_docs/{user_hash}/{doc_id}/`

### OpenCode SSE Events (critical for streaming bridge)
- `message.part.updated` with `delta` field -- Incremental text streaming
- `message.part.updated` with `part.type == "tool"` -- Tool execution status
- `session.idle` -- Completion signal
- `session.error` -- Error signal
- `permission.updated` -- Permission request (auto-approve)

### Settings Flow
- UI `getOptions()` in `interface/common.js` line ~4230 -- Collects all checkboxes
- Sent as `checkboxes` dict in POST /send_message body
- Read in `Conversation.reply()` at line ~5576
- Per-conversation persistent settings via `get/set_conversation_settings()`
- Conversation settings managed via `PUT /set_conversation_settings/<conversation_id>`

---

## 10. OpenCode Toggle — Per-Conversation Setting Design

### 10.1 Goal

Allow users to opt-in to OpenCode-based answering on a per-conversation basis. When disabled (the default), the conversation follows the normal direct-LLM path. When enabled, messages are routed through `opencode serve` for agentic capabilities.

### 10.2 Current Settings Architecture (Findings)

**Backend (`Conversation.py` lines 1133-1164):**
```python
def get_conversation_settings(self) -> dict:
    settings = self.get_field("conversation_settings")
    return settings if isinstance(settings, dict) else {}

def set_conversation_settings(self, settings: dict, overwrite: bool = True) -> dict:
    self.set_field("conversation_settings", settings, overwrite=overwrite)
    return settings
```

**Current structure:**
```json
{
  "model_overrides": {
    "summary_model": "...",
    "tldr_model": "...",
    "artefact_propose_edits_model": "...",
    "doubt_clearing_model": "...",
    "context_action_model": "...",
    "doc_long_summary_model": "...",
    "doc_long_summary_v2_model": "...",
    "doc_short_answer_model": "..."
  }
}
```

**API endpoints:**
- `GET /get_conversation_settings/<conversation_id>` (endpoints/conversations.py lines 215-231)
- `PUT /set_conversation_settings/<conversation_id>` (endpoints/conversations.py lines 234-292)

**UI:** jQuery + Bootstrap 4.6 modal (`#model-overrides-modal` in interface.html), selects populated from ModelCatalog. Load via GET, save via PUT, cached in `ConversationManager.conversationSettings`.

**Checkboxes vs Settings:**
- `checkboxes` are per-message, sent in `POST /send_message` body, NOT persisted. Examples: `use_pkb`, `perform_web_search`.
- `conversation_settings` are per-conversation, persisted to disk. Currently only `model_overrides`.

### 10.3 Proposed OpenCode Toggle Design

**Two-level toggle:**

1. **Per-message checkbox** (`opencode_enabled` in checkboxes) — ad-hoc opt-in for a single message
2. **Per-conversation setting** (`opencode_config.always_enabled` in conversation_settings) — persistent, all messages in this conversation go through OpenCode

**Updated conversation_settings structure:**
```json
{
  "model_overrides": { ... },
  "opencode_config": {
    "always_enabled": false,
    "injection_level": "medium",
    "session_ids": [],
    "active_session_id": null
  }
}
```

**Decision logic in `Conversation.reply()` (around line 5576):**
```python
# Determine whether to use OpenCode for this message
opencode_for_this_message = checkboxes.get("opencode_enabled", False)
settings = self.get_conversation_settings()
opencode_config = settings.get("opencode_config", {})
opencode_always = opencode_config.get("always_enabled", False)

if opencode_for_this_message or opencode_always:
    yield from self._reply_via_opencode(query, checkboxes, opencode_config)
else:
    # NOTE: There is no _reply_normal() method. The existing ~5000-line body of reply()
    # IS the normal path. When OpenCode is enabled, we yield from _reply_via_opencode()
    # and `return` to skip the rest. When disabled, execution simply continues below.
    pass  # Fall through to rest of reply()
```

### 10.4 Implementation Tasks

**Backend (Conversation.py):**
1. Add `_reply_via_opencode()` method — sends message to OpenCode, translates SSE to yield format
2. Add toggle check at the top of `reply()` — route based on `opencode_enabled` checkbox or `always_enabled` setting
3. Session management: `_get_or_create_opencode_session()` reads/writes `session_ids` and `active_session_id` in conversation_settings

**Endpoint changes (endpoints/conversations.py):**
1. Modify `PUT /set_conversation_settings` to accept `opencode_config` alongside `model_overrides`
2. Validate `opencode_config` structure: `always_enabled` (bool), `injection_level` (enum: minimal/medium/full), `session_ids` (list), `active_session_id` (str|null)
3. Add `opencode_enabled` to checkbox defaults in `POST /send_message` handler (default: False)

**UI changes (interface/):**
1. Add "Use OpenCode" checkbox in message send area (same pattern as `use_pkb` checkbox)
2. Add OpenCode section in model-overrides-modal (or new modal):
   - Toggle: "Always use OpenCode for this conversation" (maps to `always_enabled`)
   - Dropdown: "Context injection level" (minimal / medium / full)
3. Wire up via existing jQuery + AJAX pattern (load GET → populate → save PUT)

### 10.5 Routing Flow Diagram

```
POST /send_message
  │
  ▼
endpoints/conversations.py extracts checkboxes + query
  │
  ▼
Conversation.reply(query, checkboxes)
  │
  ├── checkboxes["opencode_enabled"] == True  ─┐
  │                                               │
  ├── settings.opencode_config.always_enabled ──┤
  │                                               │
  │   ┌───────────────────────────────────────────┘
  │   ▼
  │   _reply_via_opencode()
  │     │
  │     ├── Get/create OpenCode session
  │     ├── Inject context via noReply message (if needed)
  │     ├── Send user message via prompt_async
  │     ├── Listen to SSE events
  │     ├── Translate events to {"text": ..., "status": ...}
  │     └── yield chunks back to Flask
  │
  └── else: existing reply() body continues  (existing path, unchanged)
```

### 10.6 Key Design Decisions

- **Default is OFF**: OpenCode is disabled by default for all conversations. Users explicitly enable it.
- **Per-message overrides per-conversation**: If `always_enabled` is True but user sends with `opencode_enabled=False`, the per-message checkbox wins (allows temporarily bypassing OpenCode).
- **Session persistence**: OpenCode session IDs stored in conversation_settings so context carries across browser refreshes.
- **Backward compatible**: Conversations without `opencode_config` continue to work exactly as before — the normal reply path is the default.



### 10.7 Slash Command Autocomplete

When OpenCode mode is enabled, the chat textarea provides autocomplete for `/` commands, similar to the existing `@` mention autocomplete for PKB references.

**Trigger:** User types `/` followed by 3+ characters while OpenCode mode is active.

**Architecture** (replicates `@` autocomplete from `interface/common-chat.js` lines 3618-3960):

| Component | `@` autocomplete (existing) | `/` autocomplete (new) |
|-----------|---------------------------|----------------------|
| Trigger char | `@` | `/` |
| Min prefix | 1 character | 3 characters |
| Data source | Backend API (`/pkb/autocomplete`) | Static client-side list |
| Dropdown ID | `#pkb-autocomplete-dropdown` | `#slash-autocomplete-dropdown` |
| Selection result | Inserts `@friendly_id ` | Inserts `/command ` |

**Static command list** (no backend call needed):
```javascript
var OPENCODE_COMMANDS = [
    { command: "compact", description: "Compress session context to save tokens", icon: "bi-arrows-collapse" },
    { command: "abort", description: "Stop current generation", icon: "bi-stop-circle" },
    { command: "new", description: "Create new OpenCode session", icon: "bi-plus-circle" },
    { command: "sessions", description: "List all sessions for this conversation", icon: "bi-list" },
    { command: "fork", description: "Branch conversation from current point", icon: "bi-diagram-2" },
    { command: "summarize", description: "Summarize session to reduce context", icon: "bi-file-text" },
    { command: "status", description: "Show OpenCode session status", icon: "bi-info-circle" },
    { command: "diff", description: "Show file changes in this session", icon: "bi-file-diff" },
    { command: "revert", description: "Undo last message", icon: "bi-arrow-counterclockwise" },
    { command: "mcp", description: "Show MCP server status", icon: "bi-hdd-network" },
    { command: "models", description: "Show available models", icon: "bi-cpu" },
    { command: "help", description: "Show available commands", icon: "bi-question-circle" },
];
```

**Implementation points:**
1. Create `initSlashAutocomplete()` IIFE in `interface/common-chat.js` (after existing autocomplete at line 3960)
2. Trigger detection: in `handleSlashInput()`, find last `/` before cursor, extract prefix, filter commands
3. Enable/disable: only active when `$('#settings-enable_opencode').is(':checked')` returns true
4. Dropdown: reuse same CSS pattern as `#pkb-autocomplete-dropdown` (position: absolute, z-index: 1100, max-height: 240px)
5. Keyboard navigation: same ArrowUp/Down/Enter/Tab/Escape pattern as `@` autocomplete
6. Selection: insert `/command ` at the `/` position, set cursor after space

**Key difference from `@` autocomplete:** No debounce or API call needed — filtering a 12-item static list is instant.

**Files to modify**: `interface/common-chat.js`

### 10.8 PKB Async Future Reuse

**Problem:** In `reply()`, PKB retrieval starts at line 5522 as an async future, BEFORE checkboxes are extracted at line 5576. If we fork to the OpenCode path after line 5576, the PKB future is already running.

**Solution:** Pass the already-started `pkb_context_future` to `_reply_via_opencode()` instead of wasting it:

```python
# In reply(), after the fork decision (line ~5576):
if opencode_enabled:
    yield from self._reply_via_opencode(
        query, userData, checkboxes,
        pkb_context_future=pkb_context_future  # Already started at line 5522
    )
    return

# In _reply_via_opencode():
def _reply_via_opencode(self, query, userData, checkboxes, pkb_context_future=None):
    opencode_config = self.get_conversation_settings().get("opencode_config", {})
    injection_level = opencode_config.get("injection_level", "medium")
    
    # For medium/full injection, use the already-running PKB future
    pkb_context = ""
    if injection_level in ("medium", "full") and pkb_context_future is not None:
        try:
            pkb_result = pkb_context_future.result(timeout=30)  # Wait for it
            pkb_context = self._format_pkb_for_opencode(pkb_result)
        except Exception as e:
            logger.warning(f"PKB retrieval failed for OpenCode path: {e}")
    
    # Use pkb_context in noReply context injection
    # ...
```

**For `minimal` injection level:** The PKB future result is simply ignored (the future runs to completion in the background and is garbage collected).

**Files to modify**: `Conversation.py`

### 10.9 Cancellation Handling in OpenCode Path

**Existing mechanism** (Conversation.py):
- `cancellation_requests` dict in `base.py` (global, keyed by conversation_id)
- `POST /cancel_response/<conversation_id>` sets `cancellation_requests[cid] = {"cancelled": True, "timestamp": ...}`
- `self.is_cancelled()` checks the dict (lines 4601-4607)
- `self.clear_cancellation()` removes the entry (lines 4609-4614)
- Currently checked at lines 7864 (early), 7972 (before agent), 8543 (in streaming loop — critical)

**OpenCode path must replicate this pattern:**

```python
def _reply_via_opencode(self, query, userData, checkboxes, pkb_context_future=None):
    # ... setup, context injection, send message ...
    
    # SSE streaming loop (equivalent to line 8543 check)
    for event in sse_bridge.stream_events():
        # Check cancellation on every event
        if self.is_cancelled():
            logger.info(f"OpenCode response cancelled for {self.conversation_id}")
            # Tell OpenCode to stop too
            try:
                self.opencode_client.abort_session(session_id)
            except Exception:
                pass  # Best-effort abort
            yield {
                "text": "\n\n**Response was cancelled by user**",
                "status": "Response cancelled",
            }
            break
        
        # Normal event processing
        if event.type == "message.part.updated":
            yield {"text": event.text_delta, "status": "Generating..."}
        elif event.type == "session.idle":
            break
        elif event.type == "session.error":
            yield {"text": f"\n\nOpenCode error: {event.error}", "status": "Error"}
            break
```

**Abort mapping:**
- User clicks Cancel in UI → `POST /cancel_response/{cid}` → sets `cancellation_requests[cid]`
- SSE loop checks `self.is_cancelled()` → calls `POST /session/{session_id}/abort` on OpenCode
- OpenCode stops generation, SSE stream ends
- We yield cancellation message and break

**Lock handling:**
- The lock check at lines 5455-5475 runs BEFORE the OpenCode fork point, so both paths respect locks
- No additional lock handling needed in the OpenCode path

**Files to modify**: `Conversation.py`

### 10.10 Identified Gaps and Resolutions

| Gap | Description | Resolution |
|-----|-------------|------------|
| `_reply_normal()` reference | §10.3 code references `_reply_normal()` but no such method exists — the normal path is the rest of `reply()` after `return` | Use `return` after `yield from _reply_via_opencode()` to skip the rest of reply(). No new method needed. |
| PKB future waste | PKB retrieval starts before the fork point | Pass `pkb_context_future` to OpenCode path (§10.8) |
| Cancellation | OpenCode path needs its own cancellation check | Check `is_cancelled()` in SSE loop, call `POST /session/{id}/abort` (§10.9) |
| Message persistence | Existing path uses `persist_current_turn()` at end of reply() | OpenCode path must also call `persist_current_turn()` with the accumulated answer text |
| TLDR generation | Existing path generates TLDR for long answers | OpenCode path should also trigger TLDR generation if answer exceeds threshold |
| Math formatting | Existing path applies math rendering fixes | OpenCode path should apply same `fix_math_rendering()` post-processing |
| Token counting | Existing path tracks token usage for billing | OpenCode path should estimate tokens from SSE event metadata (if available) or from text length |
| Reward system | Existing path initializes reward system at line 5676 | OpenCode path can skip this (rewards are for our LLM calls, not OpenCode's) |
| Existing `/title` and `/temp` | These commands run before the fork | No conflict — they are checked at lines 5886-5920, before the OpenCode command routing |
| Per-message override of always_enabled | §10.6 mentions this but no code shown | When `always_enabled=True` but `opencode_enabled=False` in checkboxes, the per-message wins: `if checkboxes.get("opencode_enabled") is False and not explicitly unchecked: use opencode_always` — need careful tri-state logic (True/False/not-present) |

---

## 12. OpenCode Terminal UI — xterm.js + flask-sock + Python PTY (Approach C)

### 12.1 Decision

**Chosen: Approach C** (custom xterm.js terminal with Flask WebSocket backend). This approach was selected over iframe-based alternatives (opencode web, ttyd) because:

- **Integrated auth**: Uses our existing Flask `@login_required` + `session["email"]` — no double-login, no shared passwords
- **Same-origin**: No CORS/iframe issues — everything runs on the same Flask domain/port
- **Remote-safe**: Clean deployment on DigitalOcean behind nginx with HTTPS, no PTY exposure outside Flask auth boundary
- **Per-user sessions**: Terminal access scoped to authenticated user, rate-limited by email
- **Audit capability**: Can log terminal activity per user
- **No extra processes**: Runs inside Flask (no separate ttyd or opencode web process)

Approaches A (iframe opencode web) and B (ttyd) are **not pursued** because:
- A has unknown subpath routing, double-auth UX issues, and single shared password
- B has critical security risks (full PTY exposure), known CVEs, Safari bugs, and no per-user auth

### 12.2 Architecture

```
Browser (xterm.js)                Flask (server.py:5000)             PTY
┌──────────────────┐              ┌─────────────────────┐           ┌──────────┐
│ xterm.js terminal│◄──── wss ───►│ /ws/terminal        │◄── fd ──►│ opencode │
│ fit addon        │              │ flask-sock handler   │           │ CLI      │
│ web-links addon  │              │ pty.fork() + select  │           │ (Bubble  │
│                  │              │ session auth check   │           │  Tea)    │
└──────────────────┘              └─────────────────────┘           └──────────┘
```

**Data flow:**
1. Browser opens WebSocket to `wss://domain.com/ws/terminal`
2. Flask checks `session["email"]` — rejects if not logged in
3. Flask spawns `opencode` in a PTY via `pty.fork()` or `ptyprocess.PtyProcess.spawn()`
4. Reader thread reads PTY fd → sends to WebSocket (UTF-8, replace errors)
5. WebSocket input → writes to PTY fd (raw bytes, handles Ctrl sequences natively)
6. On disconnect: kill process group, reap children, close PTY fd

### 12.3 Access Points (Three Ways to Open)

| Access Point | Route | Auth | Description |
|-------------|-------|------|-------------|
| **Chat settings modal button** | Opens `#opencode-terminal-modal` | `@login_required` on page | Button in chat-settings-modal Actions section, opens fullscreen modal overlay |
| **Fullscreen modal** | `#opencode-terminal-modal` (in interface.html) | Session cookie (already on page) | Bootstrap modal with `max-width:95vw; height:90vh`, connects WebSocket on show |
| **Standalone page** | `GET /terminal` | `@login_required` + `@limiter.limit` | Dedicated `interface/terminal.html` page, full browser tab, opens in new tab |

All three connect to the same WebSocket endpoint: `GET /ws/terminal` (upgraded to WebSocket).

### 12.4 New Dependencies

```
flask-sock>=0.7.0       # WebSocket support for Flask (lightweight, uses simple-websocket)
ptyprocess>=0.7.0       # Robust PTY management (cross-platform, used by pexpect)
```

Add to `filtered_requirements.txt`. Both are pure Python, no compilation needed. `ptyprocess` is preferred over raw `pty` module because it handles edge cases (cleanup, signal forwarding, encoding).

**Why flask-sock over flask-socketio:**
- flask-sock is 300 lines, flask-socketio is 3000+ with engine.io dependency
- We don't need namespaces, rooms, or polling fallback — pure WebSocket is fine
- flask-sock gives us the raw `ws` object for binary data, which we need for PTY I/O
- Flask session is automatically available in flask-sock handlers

### 12.5 Backend Implementation (`endpoints/terminal.py`)

New file: `endpoints/terminal.py` (~250 lines)

```python
"""
WebSocket-based terminal for OpenCode TUI.

Spawns `opencode` in a PTY, bridges I/O to browser via WebSocket + xterm.js.
Auth-protected by Flask session (same as all other endpoints).
"""

import json
import logging
import os
import select
import signal
import struct
import threading
import time
import fcntl
import termios
from typing import Dict, Optional

from flask import Blueprint, session, send_from_directory
from flask_sock import Sock

from endpoints.auth import login_required
from endpoints.session_utils import get_session_identity
from extensions import limiter

logger = logging.getLogger(__name__)

terminal_bp = Blueprint("terminal", __name__)

# ─── Global session registry (per-user terminal sessions) ─────────────
# Key: user_email, Value: TerminalSession object
_terminal_sessions: Dict[str, "TerminalSession"] = {}
_sessions_lock = threading.Lock()

# ─── Configuration ────────────────────────────────────────────────────
TERMINAL_IDLE_TIMEOUT = int(os.getenv("TERMINAL_IDLE_TIMEOUT", "1800"))   # 30 min
TERMINAL_MAX_SESSIONS = int(os.getenv("TERMINAL_MAX_SESSIONS", "5"))       # per user
TERMINAL_SCROLLBACK = int(os.getenv("TERMINAL_SCROLLBACK", "5000"))
OPENCODE_BINARY = os.getenv("OPENCODE_BINARY", "opencode")
PROJECT_DIR = os.getenv("PROJECT_DIR", os.getcwd())


class TerminalSession:
    """
    Manages a single PTY process for a user.

    Handles:
    - PTY spawning with process group isolation
    - Terminal resize (SIGWINCH propagation)
    - Idle timeout detection
    - Graceful and forced cleanup
    - Zombie process prevention
    """

    def __init__(self, user_email: str, cols: int = 80, rows: int = 24):
        self.user_email = user_email
        self.cols = cols
        self.rows = rows
        self.pid: Optional[int] = None
        self.fd: Optional[int] = None
        self.alive = False
        self.last_activity = time.time()
        self.created_at = time.time()
        self._lock = threading.Lock()

    def spawn(self) -> None:
        """Spawn opencode in a new PTY with process group isolation."""
        import pty as pty_module

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["COLUMNS"] = str(self.cols)
        env["LINES"] = str(self.rows)

        pid, fd = pty_module.fork()

        if pid == 0:
            # ─── Child process ───
            # Create new process group (so we can kill all children)
            os.setsid()
            os.chdir(PROJECT_DIR)
            os.execvpe(
                OPENCODE_BINARY,
                [OPENCODE_BINARY, PROJECT_DIR],
                env,
            )
            # execvpe does not return; if it fails:
            os._exit(1)
        else:
            # ─── Parent process ───
            self.pid = pid
            self.fd = fd
            self.alive = True
            # Set initial terminal size
            self._set_winsize(self.cols, self.rows)
            logger.info(
                f"Terminal spawned for {self.user_email}: pid={pid}, fd={fd}"
            )

    def resize(self, cols: int, rows: int) -> None:
        """Propagate terminal resize to PTY (sends SIGWINCH)."""
        self.cols = cols
        self.rows = rows
        if self.fd is not None:
            self._set_winsize(cols, rows)

    def _set_winsize(self, cols: int, rows: int) -> None:
        """Set PTY window size (triggers SIGWINCH in child)."""
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
        except (OSError, ValueError) as e:
            logger.warning(f"Failed to set winsize: {e}")

    def read(self, timeout: float = 0.1) -> Optional[bytes]:
        """Non-blocking read from PTY fd. Returns None if nothing available."""
        if self.fd is None or not self.alive:
            return None
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if ready:
                data = os.read(self.fd, 65536)  # 64KB buffer
                if data:
                    self.last_activity = time.time()
                    return data
                else:
                    # EOF — process exited
                    self.alive = False
                    return None
        except (OSError, ValueError):
            self.alive = False
            return None

    def write(self, data: bytes) -> None:
        """Write input to PTY fd."""
        if self.fd is not None and self.alive:
            try:
                os.write(self.fd, data)
                self.last_activity = time.time()
            except OSError as e:
                logger.warning(f"PTY write error: {e}")
                self.alive = False

    def is_idle(self) -> bool:
        """Check if session has been idle beyond timeout."""
        return (time.time() - self.last_activity) > TERMINAL_IDLE_TIMEOUT

    def cleanup(self) -> None:
        """
        Kill process and all children, close fd, prevent zombies.

        Uses process group kill (os.killpg) to ensure child processes
        spawned by opencode (LSP servers, tools, etc.) are also terminated.
        """
        with self._lock:
            if not self.alive and self.pid is None:
                return

            self.alive = False
            pid = self.pid
            fd = self.fd
            self.pid = None
            self.fd = None

        # 1. Close PTY fd first (signals EOF to child)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

        if pid is not None:
            # 2. Try graceful SIGTERM to process group
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

            # 3. Wait briefly for graceful exit
            for _ in range(10):  # 1 second total
                try:
                    result = os.waitpid(pid, os.WNOHANG)
                    if result[0] != 0:
                        logger.info(f"Terminal pid={pid} exited gracefully")
                        return
                except ChildProcessError:
                    return  # Already reaped
                time.sleep(0.1)

            # 4. Force kill if still alive
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                os.waitpid(pid, 0)  # Reap zombie
                logger.info(f"Terminal pid={pid} force-killed")
            except (OSError, ChildProcessError):
                pass

    def __del__(self):
        self.cleanup()
```

**WebSocket handler:**
```python
@terminal_bp.route("/terminal")
@limiter.limit("30 per minute")
@login_required
def terminal_page():
    """Serve the standalone terminal page."""
    return send_from_directory("interface", "terminal.html", max_age=0)


def _ws_auth_check() -> Optional[str]:
    """
    Verify WebSocket connection is authenticated.
    Returns user email if valid, None if not.
    Flask session is available in flask-sock handlers.
    """
    email = session.get("email")
    name = session.get("name")
    if not email or not name:
        return None
    return email


sock = Sock()  # Initialized in server.py via sock.init_app(app)


@sock.route("/ws/terminal")
def terminal_websocket(ws):
    """
    WebSocket endpoint for terminal I/O.

    Protocol:
    - Client sends JSON: {"type": "input", "data": "..."} for keyboard input
    - Client sends JSON: {"type": "resize", "cols": N, "rows": N} for resize
    - Client sends JSON: {"type": "ping"} for keepalive
    - Server sends JSON: {"type": "output", "data": "..."} for terminal output
    - Server sends JSON: {"type": "exit", "code": N} when process exits
    - Server sends JSON: {"type": "error", "message": "..."} on error
    """
    # ─── Auth check ───
    email = _ws_auth_check()
    if not email:
        ws.send(json.dumps({"type": "error", "message": "Not authenticated"}))
        ws.close(1008, "Unauthorized")
        return

    logger.info(f"Terminal WebSocket connected for {email}")

    # ─── Get or create terminal session ───
    terminal = None
    try:
        with _sessions_lock:
            if email in _terminal_sessions and _terminal_sessions[email].alive:
                terminal = _terminal_sessions[email]
                logger.info(f"Reattaching to existing terminal for {email}")
            else:
                terminal = TerminalSession(user_email=email)
                terminal.spawn()
                _terminal_sessions[email] = terminal

        # ─── Reader thread: PTY → WebSocket ───
        reader_alive = threading.Event()
        reader_alive.set()

        def pty_reader():
            """Read PTY output and send to WebSocket."""
            while reader_alive.is_set() and terminal.alive:
                data = terminal.read(timeout=0.05)
                if data:
                    try:
                        text = data.decode("utf-8", errors="replace")
                        ws.send(json.dumps({"type": "output", "data": text}))
                    except Exception:
                        break  # WebSocket closed
                # Check idle timeout
                if terminal.is_idle():
                    try:
                        ws.send(json.dumps({
                            "type": "error",
                            "message": f"Terminal idle for {TERMINAL_IDLE_TIMEOUT}s, disconnecting"
                        }))
                    except Exception:
                        pass
                    terminal.cleanup()
                    break

            # Process exited or disconnected
            if not terminal.alive:
                try:
                    ws.send(json.dumps({"type": "exit", "code": 0}))
                except Exception:
                    pass

        reader_thread = threading.Thread(target=pty_reader, daemon=True)
        reader_thread.start()

        # ─── Main loop: WebSocket → PTY ───
        while terminal.alive:
            try:
                raw = ws.receive(timeout=5)
                if raw is None:
                    break  # WebSocket closed

                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "input":
                    terminal.write(msg["data"].encode("utf-8"))

                elif msg_type == "resize":
                    cols = int(msg.get("cols", 80))
                    rows = int(msg.get("rows", 24))
                    terminal.resize(cols, rows)

                elif msg_type == "ping":
                    ws.send(json.dumps({"type": "pong"}))
                    terminal.last_activity = time.time()

            except json.JSONDecodeError:
                # Raw binary input (fallback)
                if isinstance(raw, (str, bytes)):
                    terminal.write(raw.encode("utf-8") if isinstance(raw, str) else raw)
            except Exception as e:
                logger.warning(f"Terminal WebSocket error for {email}: {e}")
                break

    except Exception as e:
        logger.exception(f"Terminal fatal error for {email}: {e}")
    finally:
        # ─── Cleanup ───
        reader_alive.clear()
        if terminal:
            terminal.cleanup()
        with _sessions_lock:
            if email in _terminal_sessions:
                del _terminal_sessions[email]
        logger.info(f"Terminal WebSocket disconnected for {email}")
```

### 12.6 Edge Cases and Solutions

| # | Edge Case | Problem | Solution |
|---|-----------|---------|----------|
| 1 | **Zombie processes** | Child process exits but parent doesn't `waitpid()` → zombie | `TerminalSession.cleanup()` calls `os.waitpid(pid, 0)` after kill. Reader thread detects EOF (empty `os.read()`) and triggers cleanup. |
| 2 | **Terminal resize** | Browser window/modal resizes but PTY doesn't know | Client sends `{"type":"resize","cols":N,"rows":N}` on xterm.js `onResize`. Server calls `fcntl.ioctl(fd, TIOCSWINSZ, ...)` which sends SIGWINCH to child. |
| 3 | **Idle timeout** | User opens terminal, walks away → process runs forever | Reader thread checks `terminal.is_idle()` every read cycle. After `TERMINAL_IDLE_TIMEOUT` (default 30 min), sends warning and kills session. |
| 4 | **Browser tab close** | User closes tab without explicit disconnect → WebSocket drops → no cleanup | `finally` block in WebSocket handler always runs on disconnect (flask-sock guarantees this). Calls `terminal.cleanup()` and removes from registry. |
| 5 | **Process group cleanup** | `opencode` spawns child processes (LSP servers, tools, formatters) — killing only `opencode` PID leaves orphans | `os.setsid()` in child creates new process group. `os.killpg(os.getpgid(pid), SIGTERM)` kills entire group. Fallback to `SIGKILL` after 1s. |
| 6 | **Ctrl+C / Ctrl+D / Ctrl+Z** | Terminal control signals must pass through WebSocket correctly | xterm.js sends raw bytes for these (Ctrl+C = `\x03`, Ctrl+D = `\x04`, Ctrl+Z = `\x1a`). These are written directly to PTY fd as `terminal.write(data)`. The PTY's terminal driver handles signal generation (SIGINT, EOF, SIGTSTP) automatically. |
| 7 | **Unicode/binary safety** | PTY may output non-UTF-8 bytes (binary data, corrupted sequences) | `data.decode("utf-8", errors="replace")` replaces invalid bytes with U+FFFD. xterm.js handles this gracefully. |
| 8 | **Backpressure** | Command produces massive output (e.g., `cat /dev/urandom`) faster than WebSocket can send | `select.select()` with 0.05s timeout rate-limits reads to ~20/sec. 64KB read buffer caps per-read size. WebSocket `ws.send()` blocks if send buffer is full (flask-sock uses synchronous sends). If client disconnects, send raises exception → cleanup. |
| 9 | **Server restart** | Flask restarts → all PTY sessions die with no notification | PTY child processes get SIGHUP when parent exits (because `os.setsid()` isn't in parent). They terminate naturally. On next connect, fresh session is created. |
| 10 | **Multiple tabs** | User opens terminal in two tabs simultaneously | One TerminalSession per email. Second tab reattaches to same PTY (sees same output). Both WebSocket handlers share the same `TerminalSession` object. If one disconnects, the other keeps working. When last disconnects, cleanup runs. |
| 11 | **OOM / resource exhaustion** | Runaway process consumes all memory/CPU | `TERMINAL_MAX_SESSIONS` limits total sessions. Can add `resource.setrlimit()` in child before `execvpe()` to cap memory. Linux cgroups can be used for production hardening. |
| 12 | **Stale sessions in registry** | Server crash leaves entries in `_terminal_sessions` but PTY is dead | Reader thread detects `terminal.alive = False` (EOF from `os.read`) → triggers cleanup → removes from registry. On reconnect, dead session is replaced with fresh one. |

### 12.7 Frontend: xterm.js Module (`interface/opencode-terminal.js`)

New file: `interface/opencode-terminal.js` (~200 lines)

**CDN dependencies** (add to `interface/terminal.html` and `interface/interface.html`):
```html
<!-- xterm.js core + addons (only loaded when terminal is used) -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css">
<script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@0.11.0/lib/addon-web-links.min.js"></script>
```

**Note on lazy loading:** In `interface.html`, the xterm.js scripts should be loaded dynamically (only when the terminal modal is first opened) to avoid adding load time to the main page:
```javascript
function loadXtermScripts(callback) {
    if (window.Terminal) { callback(); return; }  // Already loaded
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css';
    document.head.appendChild(link);
    var script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js';
    script.onload = function() {
        // Load addons after core
        var fit = document.createElement('script');
        fit.src = 'https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js';
        fit.onload = function() {
            var weblinks = document.createElement('script');
            weblinks.src = 'https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@0.11.0/lib/addon-web-links.min.js';
            weblinks.onload = callback;
            document.head.appendChild(weblinks);
        };
        document.head.appendChild(fit);
    };
    document.head.appendChild(script);
}
```

**Terminal module:**
```javascript
/**
 * OpenCode Terminal — xterm.js WebSocket bridge.
 *
 * Provides terminal UI in both a modal (inside interface.html) and
 * standalone page (terminal.html). Connects to /ws/terminal WebSocket.
 */
var OpencodeTerminal = (function() {
    var term = null;
    var socket = null;
    var fitAddon = null;
    var webLinksAddon = null;
    var connected = false;
    var reconnectAttempts = 0;
    var MAX_RECONNECT = 3;
    var containerEl = null;
    var pingInterval = null;

    var THEME = {
        background: '#1e1e2e',
        foreground: '#cdd6f4',
        cursor: '#f5e0dc',
        cursorAccent: '#1e1e2e',
        selectionBackground: '#585b70',
        black: '#45475a',
        red: '#f38ba8',
        green: '#a6e3a1',
        yellow: '#f9e2af',
        blue: '#89b4fa',
        magenta: '#f5c2e7',
        cyan: '#94e2d5',
        white: '#bac2de',
        brightBlack: '#585b70',
        brightRed: '#f38ba8',
        brightGreen: '#a6e3a1',
        brightYellow: '#f9e2af',
        brightBlue: '#89b4fa',
        brightMagenta: '#f5c2e7',
        brightCyan: '#94e2d5',
        brightWhite: '#a6adc8'
    };

    function init(containerId) {
        containerEl = document.getElementById(containerId);
        if (!containerEl) {
            console.error('Terminal container not found:', containerId);
            return;
        }

        term = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", Menlo, Monaco, monospace',
            theme: THEME,
            scrollback: 5000,
            convertEol: true,
            allowProposedApi: true
        });

        fitAddon = new FitAddon.FitAddon();
        webLinksAddon = new WebLinksAddon.WebLinksAddon();
        term.loadAddon(fitAddon);
        term.loadAddon(webLinksAddon);
    }

    function connect() {
        if (connected) return;

        // Build WebSocket URL (auto ws/wss based on page protocol)
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var wsUrl = protocol + '//' + window.location.host + '/ws/terminal';

        socket = new WebSocket(wsUrl);

        socket.onopen = function() {
            connected = true;
            reconnectAttempts = 0;

            // Open terminal in container (must happen AFTER container is visible)
            if (!term._core) {
                // First connection — terminal not yet opened
                term.open(containerEl);
            }
            fitAddon.fit();

            // Send initial size
            var dims = fitAddon.proposeDimensions();
            if (dims) {
                socket.send(JSON.stringify({
                    type: 'resize',
                    cols: dims.cols,
                    rows: dims.rows
                }));
            }

            // Terminal input → WebSocket
            term.onData(function(data) {
                if (socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ type: 'input', data: data }));
                }
            });

            // Terminal resize → WebSocket
            term.onResize(function(size) {
                if (socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({
                        type: 'resize',
                        cols: size.cols,
                        rows: size.rows
                    }));
                }
            });

            // Keepalive ping every 30s
            pingInterval = setInterval(function() {
                if (socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ type: 'ping' }));
                }
            }, 30000);

            term.write('\x1b[32mConnected to OpenCode terminal\x1b[0m\r\n');
        };

        socket.onmessage = function(event) {
            try {
                var msg = JSON.parse(event.data);
                switch (msg.type) {
                    case 'output':
                        term.write(msg.data);
                        break;
                    case 'exit':
                        term.write('\r\n\x1b[31mProcess exited (code ' + msg.code + ')\x1b[0m\r\n');
                        connected = false;
                        break;
                    case 'error':
                        term.write('\r\n\x1b[31mError: ' + msg.message + '\x1b[0m\r\n');
                        break;
                    case 'pong':
                        break;  // Keepalive response
                }
            } catch (e) {
                // Raw text fallback
                term.write(event.data);
            }
        };

        socket.onclose = function(event) {
            connected = false;
            clearInterval(pingInterval);

            if (event.code === 1008) {
                // Auth failure
                term.write('\r\n\x1b[31mAuthentication failed. Please log in.\x1b[0m\r\n');
                return;
            }

            if (reconnectAttempts < MAX_RECONNECT) {
                reconnectAttempts++;
                var delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 10000);
                term.write('\r\n\x1b[33mDisconnected. Reconnecting in ' +
                    (delay / 1000) + 's... (attempt ' + reconnectAttempts + '/' + MAX_RECONNECT + ')\x1b[0m\r\n');
                setTimeout(connect, delay);
            } else {
                term.write('\r\n\x1b[31mDisconnected. Max reconnect attempts reached.\x1b[0m\r\n');
                term.write('\x1b[33mPress any key to reconnect...\x1b[0m\r\n');
                term.onData(function handler() {
                    term.off('data', handler);  // One-shot
                    reconnectAttempts = 0;
                    connect();
                });
            }
        };

        socket.onerror = function() {
            term.write('\r\n\x1b[31mWebSocket error\x1b[0m\r\n');
        };
    }

    function disconnect() {
        connected = false;
        clearInterval(pingInterval);
        if (socket) {
            socket.close();
            socket = null;
        }
    }

    function dispose() {
        disconnect();
        if (term) {
            term.dispose();
            term = null;
        }
        fitAddon = null;
        webLinksAddon = null;
    }

    function fit() {
        if (fitAddon && term) {
            fitAddon.fit();
        }
    }

    function focus() {
        if (term) { term.focus(); }
    }

    return {
        init: init,
        connect: connect,
        disconnect: disconnect,
        dispose: dispose,
        fit: fit,
        focus: focus
    };
})();
```

**Bootstrap modal gotcha:** xterm.js cannot render into a hidden container (it needs dimensions to calculate character grid). Solution: call `term.open()` and `fitAddon.fit()` only AFTER the modal is fully shown (use Bootstrap's `shown.bs.modal` event, not `show.bs.modal`):
```javascript
// In interface.html or chat.js
$('#opencode-terminal-modal').on('shown.bs.modal', function() {
    loadXtermScripts(function() {
        if (!OpencodeTerminal._initialized) {
            OpencodeTerminal.init('opencode-terminal-container');
            OpencodeTerminal._initialized = true;
        }
        OpencodeTerminal.connect();
        OpencodeTerminal.fit();
        OpencodeTerminal.focus();
    });
});

$('#opencode-terminal-modal').on('hidden.bs.modal', function() {
    OpencodeTerminal.disconnect();
});

// Handle modal resize (browser window resize while modal is open)
$(window).on('resize', function() {
    if ($('#opencode-terminal-modal').hasClass('show')) {
        OpencodeTerminal.fit();
    }
});
```

### 12.8 HTML Changes

**A. Terminal modal in `interface/interface.html`** (insert after line 2424, after model-overrides-modal):
```html
<!-- OpenCode Terminal Modal (fullscreen) -->
<div id="opencode-terminal-modal" class="modal fade" tabindex="-1" role="dialog"
     style="z-index: 1080;" data-backdrop="static" data-keyboard="false">
    <div class="modal-dialog" role="document"
         style="max-width: 95vw; margin: 2vh auto;">
        <div class="modal-content" style="height: 90vh; background: #1e1e2e;">
            <div class="modal-header py-1" style="background: #313244; border-bottom: 1px solid #45475a;">
                <h6 class="modal-title" style="color: #cdd6f4;">
                    <i class="bi bi-terminal" style="color: #89b4fa;"></i> OpenCode Terminal
                </h6>
                <div>
                    <button class="btn btn-sm btn-outline-light mr-2" id="opencode-terminal-newtab"
                            title="Open in new tab" style="font-size: 0.75rem;">
                        <i class="bi bi-box-arrow-up-right"></i>
                    </button>
                    <button type="button" class="close" data-dismiss="modal"
                            style="color: #cdd6f4;" aria-label="Close">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
            </div>
            <div class="modal-body p-0" style="height: calc(100% - 40px);">
                <div id="opencode-terminal-container"
                     style="width: 100%; height: 100%;"></div>
            </div>
        </div>
    </div>
</div>
```

**B. "Open Terminal" button in chat-settings-modal Actions section** (insert after line 2180):
```html
<div class="col">
    <button class="btn btn-outline-info btn-sm rounded-pill w-100"
            id="settings-opencode-terminal-button"
            title="Open OpenCode Terminal">
        <i class="bi bi-terminal"></i> Terminal
    </button>
</div>
```

**C. "Open in new tab" handler:**
```javascript
$('#opencode-terminal-newtab').click(function() {
    window.open('/terminal', '_blank');
});
```

**D. Standalone page** (`interface/terminal.html`, new file):
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenCode Terminal</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #1e1e2e; overflow: hidden; height: 100vh; }
        #terminal-container { width: 100vw; height: 100vh; }
    </style>
</head>
<body>
    <div id="terminal-container"></div>

    <script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@0.11.0/lib/addon-web-links.min.js"></script>
    <script src="/interface/opencode-terminal.js"></script>
    <script>
        OpencodeTerminal.init('terminal-container');
        OpencodeTerminal.connect();
        window.addEventListener('resize', function() { OpencodeTerminal.fit(); });
    </script>
</body>
</html>
```

### 12.9 Server Integration

**`server.py` changes** (in `create_app()`, after CORS setup ~line 300):
```python
# Initialize flask-sock for WebSocket support
from flask_sock import Sock
sock = Sock(app)
```

**`endpoints/__init__.py` changes** (in `register_blueprints()`):
```python
from .terminal import terminal_bp, sock as terminal_sock
app.register_blueprint(terminal_bp)
terminal_sock.init_app(app)
```

### 12.10 Remote Deployment (DigitalOcean Ubuntu)

**nginx WebSocket proxy** (add to existing server block):
```nginx
# WebSocket terminal endpoint
location /ws/terminal {
    proxy_pass http://127.0.0.1:5000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket-specific timeouts
    proxy_read_timeout 3600s;    # 1 hour (matches idle timeout)
    proxy_send_timeout 60s;
    proxy_connect_timeout 10s;

    # Disable buffering for WebSocket
    proxy_buffering off;
}

# Terminal standalone page
location /terminal {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

**Security hardening for remote:**

| Measure | Implementation |
|---------|---------------|
| **Auth gating** | WebSocket handler checks `session["email"]` before spawning PTY. No session = `ws.close(1008)`. Flask session cookies are httponly + secure + samesite. |
| **Rate limiting** | `@limiter.limit("30 per minute")` on `/terminal` page. WebSocket connections limited by `TERMINAL_MAX_SESSIONS` per user. |
| **Process isolation** | `os.setsid()` creates isolated process group. Child processes can't escape group. |
| **Idle timeout** | `TERMINAL_IDLE_TIMEOUT=1800` (30 min default). Auto-kill after inactivity. |
| **Session cap** | `TERMINAL_MAX_SESSIONS=5` per user. Prevents fork bombs via terminal. |
| **HTTPS enforced** | `SESSION_COOKIE_SECURE=True` means cookies only sent over HTTPS. WebSocket auto-upgrades to `wss://` on HTTPS pages. |
| **No directory traversal** | `opencode` runs in `PROJECT_DIR` only. PTY doesn't expose arbitrary paths (opencode's own sandboxing handles this). |
| **Graceful cleanup** | `finally` block always runs — even on server crash, PTY processes get SIGHUP from parent exit. |
| **Audit logging** | Every connect/disconnect logged with email: `logger.info(f"Terminal WebSocket connected for {email}")` |

### 12.11 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TERMINAL_IDLE_TIMEOUT` | `1800` | Seconds of inactivity before terminal auto-kills (30 min) |
| `TERMINAL_MAX_SESSIONS` | `5` | Maximum concurrent terminal sessions per user |
| `TERMINAL_SCROLLBACK` | `5000` | xterm.js scrollback buffer lines |
| `OPENCODE_BINARY` | `opencode` | Path to opencode binary (in case it's not in PATH) |
| `PROJECT_DIR` | `os.getcwd()` | Working directory for opencode (project root) |

### 12.12 Implementation Tasks (Milestone 5)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 5.1 | Install flask-sock + ptyprocess | `filtered_requirements.txt` | 5 min |
| 5.2 | Create `endpoints/terminal.py` with TerminalSession class + WebSocket handler | `endpoints/terminal.py` (new, ~250 lines) | 2-3 hours |
| 5.3 | Register terminal blueprint + sock in server startup | `endpoints/__init__.py`, `server.py` | 15 min |
| 5.4 | Create `interface/opencode-terminal.js` module | `interface/opencode-terminal.js` (new, ~200 lines) | 1-2 hours |
| 5.5 | Add terminal modal to interface.html | `interface/interface.html` (after line 2424) | 30 min |
| 5.6 | Add terminal button to chat-settings-modal | `interface/interface.html` (after line 2180) | 10 min |
| 5.7 | Wire up modal events + lazy loading in chat.js | `interface/chat.js` | 30 min |
| 5.8 | Create standalone `interface/terminal.html` | `interface/terminal.html` (new, ~30 lines) | 15 min |
| 5.9 | Add nginx WebSocket proxy config to ops docs | `documentation/features/opencode_integration/README.md` | 15 min |
| 5.10 | Test: local (macOS) + remote (Ubuntu) | Manual testing | 1-2 hours |
| **Total** | | **4 new files, 3 modified** | **~6-8 hours** |

### 12.13 Testing Checklist

- [ ] Terminal opens via chat-settings-modal button
- [ ] Terminal opens as fullscreen modal
- [ ] Terminal opens in new tab via `/terminal`
- [ ] `/terminal` page redirects to `/login` if not authenticated
- [ ] WebSocket rejects connection without valid session
- [ ] xterm.js renders correctly in modal (no blank screen)
- [ ] Terminal resize works (modal resize + browser resize)
- [ ] Ctrl+C sends SIGINT to opencode process
- [ ] Ctrl+D sends EOF
- [ ] Idle timeout kills session after 30 min
- [ ] Browser tab close triggers cleanup (no zombie processes)
- [ ] Reconnection works (3 attempts with exponential backoff)
- [ ] Multiple browser tabs reattach to same PTY
- [ ] Works over HTTPS with nginx reverse proxy
- [ ] Rate limiting prevents abuse
- [ ] Large output doesn't crash browser (scrollback limit works)
- [ ] Unicode characters render correctly
- [ ] Colored output renders correctly (256-color + truecolor)