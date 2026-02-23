# OpenCode Integration

Route chat messages through `opencode serve` for agentic capabilities (tool use, MCP, multi-step planning), with multi-provider support (OpenRouter + AWS Bedrock), SSE-to-Flask streaming bridge, per-conversation session management, configurable context injection, and provider/model selection UI.

## Overview

The OpenCode integration adds an optional routing mode to `Conversation.py` that sends user messages to an `opencode serve` instance (port 4096) instead of calling LLM provider APIs directly. The Flask server becomes a **translation layer** between:

- **Browser** (newline-delimited JSON streaming, unchanged) and
- **OpenCode** (SSE event stream with tool use, MCP, agentic loops)

When OpenCode mode is enabled for a message (via the `opencode_enabled` checkbox in the UI), the conversation:
1. Gets or creates an OpenCode session for this conversation
2. Assembles context (history summary, PKB distillation, doc refs) per injection config
3. Sends context as a `noReply` message (context injection without triggering AI response)
4. Sends the user message via `prompt_async`
5. Streams SSE events via the SSE Bridge, translating to Flask format
6. Applies math formatting to match non-OpenCode rendering pipeline
7. Generates TLDR if response is long enough
8. Persists messages

Non-OpenCode conversations work exactly as before — this is fully opt-in per message.

## Architecture

```
Browser <── newline-delimited JSON (unchanged) ──> Flask / Conversation.py
                                                        |
                                                ┌───────┴────────┐
                                                | Context Assembly|
                                                | (configurable) |
                                                └───────┬────────┘
                                                        | SSE
                                                        v
                                               opencode serve :4096
                                                ┌───────┴────────┐
                                                | Built-in tools |
                                                | bash, edit,    |
                                                | grep, LSP ...  |
                                                └───────┬────────┘
                                                        |
                                        ┌───────────────┼───────────────┐
                                        v               v               v
                                   PKB MCP        Document MCP    Web Search MCP
                                  (:8101)         (:8102)         (:8100, existing)
```

**Flask server owns**: User auth, conversation persistence, message history, PKB context assembly, document reference resolution, post-processing (TLDR, math formatting, message IDs), UI-facing API contract.

**OpenCode owns**: LLM provider communication, tool execution, agentic loops (plan-execute-verify), session-level context and compaction, MCP tool orchestration.

## Multi-Provider Support

The integration supports two LLM providers:

| Provider | Provider ID | Model ID Format | Auth |
|----------|-------------|-----------------|------|
| **OpenRouter** (default) | `openrouter` | `anthropic/claude-sonnet-4.5` (OpenRouter model IDs) | `OPENROUTER_API_KEY` env var, referenced in `opencode.json` via `{env:OPENROUTER_API_KEY}` |
| **AWS Bedrock** | `amazon-bedrock` | `anthropic.claude-sonnet-4-5-20250929-v1:0` (Bedrock model IDs) | AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`) |

### Supported Models

Only Claude 4.5 and 4.6 models are supported:

| UI Name | OpenRouter Model ID | Bedrock Model ID |
|---------|--------------------|--------------------|
| Claude Haiku 4.5 | `anthropic/claude-haiku-4.5` | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| Claude Sonnet 4.5 | `anthropic/claude-sonnet-4.5` | `anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Claude Opus 4.5 | `anthropic/claude-opus-4.5` | `anthropic.claude-opus-4-5-20251101-v1:0` |
| Claude Sonnet 4.6 | `anthropic/claude-sonnet-4.6` | `anthropic.claude-sonnet-4-6` |
| Claude Opus 4.6 | `anthropic/claude-opus-4.6` | `anthropic.claude-opus-4-6-v1` |

### Model Routing Logic (`_resolve_opencode_model`)

The resolver in `Conversation.py` handles the mapping from UI model names to OpenCode `{providerID, modelID}` pairs:

1. **Explicit provider prefix** (`openrouter/...` or `amazon-bedrock/...`): Extract provider, remainder is model ID.
2. **Model-family prefix** (`anthropic/...`, `openai/...`, etc.): Pass the FULL string as `modelID` to the default provider (OpenRouter). OpenRouter accepts `anthropic/claude-sonnet-4.5` as a model ID — the `anthropic/` is part of the model name, not a provider split.
3. **Bedrock provider**: Translate via `BEDROCK_MODEL_MAP` from OpenRouter-style names to Bedrock model IDs (dot notation, version suffixed).
4. **No `/`**: Use default provider with model as-is.

This is critical because a direct Anthropic API key is NOT available. Model IDs like `anthropic/claude-sonnet-4.5` must route through OpenRouter (where `anthropic/` is part of the model identifier) rather than being misinterpreted as `provider=anthropic`.

## SSE Bridge (Event Translation)

The SSE Bridge (`opencode_client/sse_bridge.py`) translates OpenCode's SSE event stream into the `{"text": ..., "status": ...}` newline-delimited JSON format that the Flask UI expects.

### SSE Event Structure (Key Discovery)

OpenCode sends ALL SSE events with the SSE `event:` field set to `message`. The actual event type lives inside `data["type"]`:

```
event: message
data: {"type": "message.part.delta", "properties": {"field": "text", "content": "Hello", ...}}
```

This means the bridge must extract the real event type from `data["type"]` when `raw_event_type == "message"`, rather than dispatching on the SSE `event:` field directly.

### Delta Event Structure (Flat)

`message.part.delta` events have a **flat** properties structure:

```json
{
  "type": "message.part.delta",
  "properties": {
    "sessionID": "ses_abc123",
    "messageID": "msg_def456",
    "partID": "part_ghi789",
    "field": "text",
    "content": "the delta text"
  }
}
```

This differs from `message.part.updated` which nests a full `part` object inside properties (`properties.part.type`, `properties.part.text`, etc.).

### Event Translation Table

| OpenCode SSE Event | Condition | Flask Yield |
|-------------------|-----------|-------------|
| `message.part.delta` | `field == "text"` | `{"text": content, "status": "Generating response..."}` |
| `message.part.delta` | `field == "reasoning"` | (skip) |
| `message.part.updated` | `part.type == "text"` | `{"text": delta, "status": "Generating response..."}` |
| `message.part.updated` | `part.type == "tool"`, running | `{"text": "", "status": "Running {tool}..."}` |
| `message.part.updated` | `part.type == "tool"`, completed | `{"text": "", "status": "Tool {tool} completed"}` |
| `message.part.updated` | `part.type == "tool"`, error | `{"text": "", "status": "Tool {tool} failed: {error}"}` |
| `session.idle` | -- | Signal stream completion (`_done` flag) |
| `session.error` | -- | `{"text": "OpenCode error: ...", "status": "Error: ..."}` |
| `session.status` | `type == "busy"` | `{"text": "", "status": "Processing..."}` |
| `permission.updated` | auto-approve enabled | Auto-approves via API, `{"text": "", "status": "Permission auto-approved"}` |

### Reconnection

The bridge handles SSE connection drops with automatic reconnection:
- Up to `OPENCODE_SSE_MAX_RECONNECTS` (default 5) consecutive retries
- `OPENCODE_SSE_RECONNECT_DELAY` (default 2.0s) between retries
- Connection errors (ConnectionError, OSError, StopIteration) trigger reconnection
- Other exceptions terminate the stream immediately

### Cancellation

The bridge accepts an `is_cancelled_fn` callback (checked on every event). When cancellation is detected, it calls `client.abort_session()` and yields a cancellation message.

## Session Management

Each conversation maps to one or more OpenCode sessions. The `SessionManager` (`opencode_client/session_manager.py`) tracks this mapping via `conversation_settings.opencode_config`:

```json
{
  "opencode_config": {
    "active_session_id": "ses_abc123",
    "session_ids": ["ses_abc123", "ses_def456"],
    "injection_level": "medium",
    "opencode_provider": "openrouter",
    "opencode_model": "anthropic/claude-sonnet-4.5"
  }
}
```

**Session lifecycle**:
- `get_or_create_session()`: Returns active session, creates new one if none exists or if the existing one is stale (no longer on server).
- `create_new_session()`: Force-creates a new session and makes it active. Used by `/new` slash command.
- `switch_session()`: Switch active session within the conversation's session list.
- `list_sessions_for_conversation()`: Returns enriched session objects, pruning stale IDs.
- Sessions decouple from Conversation.py via callbacks (`get_settings_fn`, `set_settings_fn`) to avoid circular imports.

## Context Injection (`noReply` Messages)

Context is injected into OpenCode sessions using the `noReply` flag on messages, which stores the message in the session without triggering an AI response.

**Injection levels** (configurable per conversation via `opencode_config.injection_level`):

| Level | Auto-Injected | Available via MCP Only |
|-------|--------------|------------------------|
| `minimal` | Conversation history summary only | PKB, documents, memory pad |
| `medium` (default) | History summary + top PKB claims + referenced docs | Deeper PKB search, full doc text, memory pad |
| `full` | Everything (history, PKB distillation, docs, memory pad) | Extras only |

**Strategy**:
1. On first message, send a `noReply` message with system prompt (user identity, MCP instructions) and assembled context.
2. On subsequent messages, send `noReply` with updated context if available.
3. Then send the actual user message as a normal `prompt_async`.

**`noReply` vs `system` parameter**:
- `system` sets a system prompt addition for the entire session context (appended to base, does not replace AGENTS.md).
- `noReply` injects a user-visible message the model sees but doesn't respond to — survives compaction.
- Use `system` for identity/instructions (static), use `noReply` for dynamic context (PKB, docs, history).

## Math Formatting

Non-OpenCode providers run every streaming chunk through `process_math_formatting()` (via `stream_text_with_math_formatting()` in `call_llm.py`), which doubles backslashes for math delimiters:

- `\[` -> `\\[`, `\]` -> `\\]`
- `\(` -> `\\(`, `\)` -> `\\)`

The frontend expects this doubled form for MathJax/KaTeX rendering. Without it, single-backslash sequences get eaten by the JS/HTML parser, causing garbled characters.

The OpenCode streaming loop now applies the same `process_math_formatting()` to each delta chunk before yielding, matching the non-OpenCode behavior exactly. This is done at lines 4922-4940 of `Conversation.py`.

## Slash Commands

When OpenCode mode is active, slash commands are routed through dedicated handlers:

| Command | Action |
|---------|--------|
| `/compact` | Compact session context to save tokens |
| `/abort` | Stop current LLM generation immediately |
| `/new` | Create new OpenCode session for this conversation |
| `/sessions` | List all OpenCode sessions for this conversation |
| `/fork` | Branch conversation from current point |
| `/summarize` | Summarize session to compress context |
| `/status` | Show OpenCode session status |
| `/diff` | Show file changes made in this session |
| `/revert` | Undo last message |
| `/mcp` | Show MCP server status |
| `/models` | Show available models and providers |
| `/help` | Show available OpenCode commands |

**Conflict resolution**: `/title`, `/set_title`, `/temp`, `/temporary` are always handled locally by `Conversation.py`. Unknown slash commands are passed through to OpenCode via `POST /session/{id}/command`.

## UI Settings

The OpenCode settings modal (`interface/interface.html`, `#opencode-settings-modal`) provides:

1. **Provider dropdown** (`#opencode-provider`): OpenRouter (default) or Amazon Bedrock.
2. **Model dropdown** (`#opencode-model`): The 5 supported Claude models.
3. **Save button**: Persists `opencode_provider` and `opencode_model` to conversation settings via `POST /set_conversation_settings`.

Settings are validated in `endpoints/conversations.py` against allowed values:
- `opencode_provider`: `"openrouter"`, `"amazon-bedrock"`
- `opencode_model`: `"anthropic/claude-haiku-4.5"`, `"anthropic/claude-sonnet-4.5"`, `"anthropic/claude-opus-4.5"`, `"anthropic/claude-sonnet-4.6"`, `"anthropic/claude-opus-4.6"`

## Configuration

### `opencode.json` (project root)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4.5",
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
  "provider": {
    "openrouter": {
      "models": {},
      "options": {
        "apiKey": "{env:OPENROUTER_API_KEY}"
      }
    },
    "amazon-bedrock": {
      "models": {},
      "options": {
        "region": "us-east-1"
      }
    }
  },
  "instructions": ["AGENTS.md"],
  "mcp": {
    "web-search": { "type": "remote", "url": "http://localhost:8100/", "enabled": true },
    "pkb": { "type": "remote", "url": "http://localhost:8101/", "enabled": true },
    "documents": { "type": "remote", "url": "http://localhost:8102/", "enabled": true },
    "artefacts": { "type": "remote", "url": "http://localhost:8103/", "enabled": true },
    "conversation": { "type": "remote", "url": "http://localhost:8104/", "enabled": true },
    "prompts-actions": { "type": "remote", "url": "http://localhost:8105/", "enabled": true },
    "code-runner": { "type": "remote", "url": "http://localhost:8106/", "enabled": true }
  },
  "server": { "port": 4096, "hostname": "127.0.0.1" }
}
```

**Provider config notes**:
- `models: {}` is required (empty = accept all models for that provider).
- `options` holds provider-specific auth: `apiKey` for OpenRouter, `region` for Bedrock.
- `{env:OPENROUTER_API_KEY}` syntax resolves environment variables at server startup.
- No `anthropic` provider block — user does not have a direct Anthropic API key.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENROUTER_API_KEY` | Yes (for OpenRouter) | — | OpenRouter API key, used by both Flask LLM calls and OpenCode |
| `AWS_ACCESS_KEY_ID` | For Bedrock | — | AWS credential for Bedrock |
| `AWS_SECRET_ACCESS_KEY` | For Bedrock | — | AWS credential for Bedrock |
| `AWS_REGION` | For Bedrock | `us-east-1` | AWS region |
| `OPENCODE_BASE_URL` | No | `http://localhost:4096` | OpenCode server URL |
| `OPENCODE_SERVER_USERNAME` | No | `opencode` | HTTP Basic Auth username |
| `OPENCODE_SERVER_PASSWORD` | No | (empty) | HTTP Basic Auth password |
| `OPENCODE_DEFAULT_PROVIDER` | No | `openrouter` | Default provider when none specified |
| `OPENCODE_DEFAULT_MODEL` | No | `anthropic/claude-sonnet-4.5` | Default model when none specified |
| `OPENCODE_SYNC_TIMEOUT` | No | `300` | Timeout for synchronous LLM calls (seconds) |
| `OPENCODE_ASYNC_TIMEOUT` | No | `10` | Timeout for async prompt dispatch (seconds) |
| `OPENCODE_SSE_CONNECT_TIMEOUT` | No | `15` | Timeout for SSE connection (seconds) |
| `OPENCODE_SSE_RECONNECT_DELAY` | No | `2.0` | Delay between SSE reconnects (seconds) |
| `OPENCODE_SSE_MAX_RECONNECTS` | No | `5` | Max consecutive SSE reconnects |
| `OPENCODE_AUTO_APPROVE_PERMISSIONS` | No | `true` | Auto-approve tool permission requests |

### Starting OpenCode Server

```bash
# Set environment variables first
export OPENROUTER_API_KEY=sk-or-v1-...
export MCP_JWT_TOKEN=<your-mcp-jwt-token>

# Start with debug logging
opencode serve --log-level DEBUG --print-logs
```

The server runs on port 4096 by default. The Flask server connects to it via the `opencode_client` library.

## OpenCode Client Library (`opencode_client/`)

A Python package providing HTTP client, session manager, and SSE bridge:

| File | Purpose |
|------|---------|
| `client.py` | `OpencodeClient` — synchronous HTTP client wrapping the full OpenCode REST API (sessions, messages, commands, config, MCP, permissions, sharing) |
| `session_manager.py` | `SessionManager` — maps conversation IDs to OpenCode sessions via `conversation_settings` callbacks |
| `sse_bridge.py` | `SSEBridge` — translates SSE events to Flask streaming chunks with reconnection and cancellation |
| `config.py` | Configuration constants from environment variables with sensible defaults |
| `__init__.py` | Package marker |

### OpencodeClient API Summary

The client wraps every documented OpenCode server endpoint:

| Category | Methods |
|----------|---------|
| Health | `health_check()` |
| Config | `get_config()`, `update_config()`, `get_providers()` |
| Sessions | `create_session()`, `get_session()`, `list_sessions()`, `delete_session()`, `update_session()`, `abort_session()`, `fork_session()`, `summarize_session()`, `get_session_status()`, `get_session_children()`, `get_session_diff()`, `get_session_todos()`, `revert_message()`, `unrevert_session()` |
| Messages | `send_message_sync()`, `send_message_async()`, `send_context()`, `get_messages()`, `get_message()` |
| Commands | `execute_command()`, `run_shell()` |
| SSE | `stream_events()` — manual SSE parser with session-level filtering |
| Permissions | `respond_permission()` |
| MCP | `get_mcp_status()`, `add_mcp_server()` |
| Agents | `list_agents()` |
| Sharing | `share_session()`, `unshare_session()` |

## Key Files

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `opencode_client/__init__.py` | ~1 | Package marker |
| `opencode_client/client.py` | ~963 | HTTP client wrapping full OpenCode REST API |
| `opencode_client/config.py` | ~105 | Configuration constants from env vars |
| `opencode_client/session_manager.py` | ~343 | Conversation-to-session mapping with callback-based persistence |
| `opencode_client/sse_bridge.py` | ~508 | SSE-to-Flask streaming bridge with event translation, reconnection, cancellation |
| `opencode.json` | ~85 | OpenCode server configuration (providers, MCP servers, permissions) |

### Modified Files

| File | Change |
|------|--------|
| `Conversation.py` | `BEDROCK_MODEL_MAP` (5 models), `_resolve_opencode_model()`, `_reply_via_opencode()` (full OpenCode routing), `_build_opencode_system_prompt()`, `_assemble_opencode_context()`, OpenCode slash command routing in `reply()`, math formatting on OpenCode stream deltas |
| `endpoints/conversations.py` | `opencode_provider` and `opencode_model` added to validated settings whitelist |
| `interface/interface.html` | OpenCode settings modal with Provider and Model dropdowns |
| `interface/chat.js` | Save/load handlers for `opencode_provider` and `opencode_model` settings |
| `interface/common-chat.js` | Diagnostic logging for raw backend text (stream debugging) |
| `agents/search_and_information_agents.py` | Perplexity model updates (`sonar-reasoning` -> `sonar-pro`, `sonar-reasoning-pro` -> `sonar-deep-research`) |

## Implementation Notes (Bugs Found and Fixed)

### 1. SSE Event Type Mismatch (Critical)

OpenCode sends ALL SSE events with `event: message` as the SSE event field. The actual event type (`message.part.delta`, `session.idle`, etc.) is inside `data["type"]`. The original `_handle_event` dispatched on `sse_event.get("event", "")` which was always `"message"` — matching nothing in the handler. All events were silently dropped.

**Fix**: Extract `event_type = data["type"]` when `raw_event_type == "message"`.

### 2. Delta Event Data Structure Mismatch

`message.part.delta` events have a flat structure (`properties.field`, `properties.content`, `properties.partID`) — NOT a nested `properties.part` dict. The old handler expected `properties.part.type` and `properties.part.text`.

**Fix**: Added `_handle_part_delta()` method that reads `props["field"]` and `props["content"]` directly.

### 3. Provider Routing Bug (Critical)

The original `_resolve_opencode_model()` extracted `anthropic` from `anthropic/claude-sonnet-4.5` and set `providerID="anthropic"` — but the user has no direct Anthropic API key. This caused `x-api-key header is required` errors.

**Fix**: Only extract actual OpenCode providers (`openrouter`, `amazon-bedrock`). Model-family prefixes like `anthropic/` stay intact as part of the OpenRouter model ID.

### 4. Missing Math Formatting (Critical)

Non-OpenCode providers run every chunk through `process_math_formatting()` which doubles backslashes. OpenCode's SSE bridge was yielding raw deltas with single backslashes — causing garbled characters in the UI.

**Fix**: Import and apply `process_math_formatting` to each OpenCode text delta before yielding.

### 5. Perplexity Model Sunset

`perplexity/sonar-reasoning` and `perplexity/sonar-reasoning-pro` were discontinued. Replaced with `sonar-pro` and `sonar-deep-research`.

### 6. Empty Anthropic API Key

OpenCode runtime config had `"anthropic": { "options": { "apiKey": "" } }`. Removed the `anthropic` provider block from `opencode.json` since only OpenRouter and Bedrock are available.

## Rendering Pipeline

The full path from OpenCode to rendered UI text:

1. **OpenCode SSE**: `event: message` with `data.type: message.part.delta`, `data.properties.content: "delta text"`
2. **SSE Bridge**: Extracts real event type from `data.type`, reads `props.content`, returns `{"text": delta, "status": "Generating..."}`
3. **Math Formatting**: `process_math_formatting(delta)` doubles backslashes for math delimiters
4. **Conversation.py**: Yields `{"text": formatted_delta, "status": ...}` as `json.dumps(chunk) + "\n"`
5. **Flask**: Streams as `text/plain` newline-delimited JSON
6. **Browser JS**: `renderStreamingResponse()` parses JSON, `parseGamificationTags()`, `.replace(/\n/g, '  \n')`, accumulates in `rendered_answer`, calls `renderInnerContentAsMarkdown()` (via `marked.marked()`), sets `innerHTML`

## Planning Document

Full design rationale, MCP sub-module specifications, tool inventory, and milestone breakdown: `documentation/planning/plans/opencode_integration.plan.md`