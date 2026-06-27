# OpenCode Integration (Run Mode)

Routes chat messages through `opencode run` CLI subprocess for agentic capabilities (tool use, MCP, file editing, bash) — no persistent `opencode serve` server required. Each message spawns a short-lived subprocess. Session IDs are stored per-conversation for continuity across turns.

## Overview

The OpenCode integration adds an optional routing mode to `Conversation.py` that invokes `opencode run --format json` as a subprocess instead of calling LLM provider APIs directly.

**Key design philosophy**: OpenCode is used as a *worker* for small, atomic tasks. The main LLM conversation manager delegates specific coding/file work to opencode and gets back the result. This differs from the previous server-based approach where opencode was the conversation manager.

When OpenCode mode is enabled (via the `opencode_enabled` checkbox), the conversation:

1. Resolves the model string from conversation settings (defaults to `openrouter/anthropic/claude-sonnet-4.6`)
2. Assembles context (history summary, PKB, memory pad) per injection level
3. Prepends system prompt (user identity, conversation ID) for new sessions
4. Runs `opencode run --format json --model <model> [--session <id>] --dangerously-skip-permissions "<prompt>"`
5. Streams JSON event lines from stdout, translating them to Flask `{"text": ..., "status": ...}` chunks
6. Captures `sessionID` from the first event and persists it per-conversation for future turns
7. Applies math formatting and generates TLDR as normal
8. Persists messages

Non-OpenCode conversations work exactly as before — this is fully opt-in per message.

## Why Run Mode vs Serve Mode

| Aspect | `opencode run` (current) | `opencode serve` (previous) |
|--------|--------------------------|------------------------------|
| Server required | No — subprocess per call | Yes — must start and keep running |
| Session continuity | Via `--session <id>` flag | Via server-side session state |
| Timeout risk | Yes — long tasks may exceed `OPENCODE_RUN_TIMEOUT` | No — SSE streams indefinitely |
| Suitable task size | Small, atomic | Large, multi-step |
| Cold boot overhead | Per call (MCP init each time) | Once at server start |
| Robustness | High — no dangling server process | Lower — server crashes affect all convs |

## Architecture

```
Browser <── newline-delimited JSON (unchanged) ──> Flask / Conversation.py
                                                        |
                                                _reply_via_opencode()
                                                        |
                                            subprocess: opencode run
                                            --format json --model ...
                                            [--session <id>]
                                            --dangerously-skip-permissions
                                            "<context + user message>"
                                                        |
                                                stdout JSON events
                                                        |
                                          _run_opencode() generator
                                    (threaded reader, timeout enforced)
```

**Flask server owns**: User auth, conversation persistence, message history, PKB context assembly, session ID tracking, post-processing (TLDR, math formatting, message IDs), UI-facing API contract.

**opencode owns**: LLM provider communication, tool execution (bash, edit, grep, webfetch), agentic loops, MCP tool orchestration, file system work.

## Core Implementation

### `_run_opencode(prompt, model_str, session_id, timeout)` — `Conversation.py`

The low-level executor:

1. Builds the CLI command: `opencode run --format json --model <model_str> [--session <id>] --dangerously-skip-permissions <prompt>`
2. Spawns the process via `subprocess.Popen`
3. Uses two daemon threads (stdout + stderr) to read output without blocking
4. Yields parsed JSON event dicts line by line
5. Enforces `OPENCODE_RUN_TIMEOUT` (default 120s); kills process and yields error event on timeout

### `_reply_via_opencode(query, userData, checkboxes, pkb_context_future)` — `Conversation.py`

The main routing method:

1. Resolves model via `_resolve_opencode_model()`
2. Retrieves stored session ID via `_get_opencode_session_id()`
3. Assembles context via `_assemble_opencode_context()`
4. Prepends system prompt for new sessions (no stored session ID)
5. Calls `_run_opencode()` and streams events
6. Captures `sessionID` from first event, saves via `_save_opencode_session_id()`
7. Handles event types: `assistant`, `text`, `error`, `tool`, `tool-result`, `step-finish`

### Session Persistence

Session IDs are stored in `opencode_config` within `conversation_settings`:

```json
{
  "opencode_config": {
    "active_session_id": "ses_0f6282...",
    "session_ids": ["ses_0f6282...", "ses_0f6245..."],
    "injection_level": "medium",
    "opencode_provider": "openrouter",
    "opencode_model": "anthropic/claude-sonnet-4.6"
  }
}
```

`_get_opencode_session_id()` returns `active_session_id`.  
`_save_opencode_session_id(id)` writes it back and appends to `session_ids` list.

## JSON Event Format

`opencode run --format json` outputs one JSON object per line on stdout. Known event types:

| Event type | Key fields | Action |
|------------|------------|--------|
| `assistant` | `message.parts[].type`, `message.parts[].text` | Extract and stream text parts |
| `text` | `text` | Stream text delta directly |
| `error` | `error.data.message`, `sessionID` | Surface error, stop streaming |
| `tool` / `tool-call` | `toolName` | Yield status: `Running <tool>...` |
| `tool-result` | `toolName` | Yield status: `Tool <tool> completed` |
| `step-finish` | — | Yield status: `Step complete...` |
| `finish` | — | Stream end signal |

Every event includes `sessionID` — captured on the first event of every run.

### Example Events

```json
{"type":"assistant","sessionID":"ses_abc123","message":{"parts":[{"type":"text","text":"Hello"}]}}
{"type":"error","sessionID":"ses_abc123","error":{"name":"APIError","data":{"message":"Unauthorized"}}}
```

## Model Resolution

`_resolve_opencode_model(checkboxes, oc_config)` returns a `provider/model` string for `--model`:

- If model already has an opencode provider prefix (`openrouter/...`, `amazon-bedrock/...`) → use as-is
- If model has a model-family prefix (`anthropic/...`) → prepend the configured provider: `openrouter/anthropic/claude-sonnet-4.6`
- Bare model name → prepend provider: `openrouter/claude-sonnet-4.6`

Default model: `openrouter/anthropic/claude-sonnet-4.6` (matches `opencode.json`).

Note: Bedrock model ID translation (previously done in `BEDROCK_MODEL_MAP`) is now handled by opencode itself — pass `amazon-bedrock/anthropic/claude-sonnet-4.6` and opencode translates internally.

## Context Injection

Context is assembled by `_assemble_opencode_context()` and prepended to the prompt text (since `opencode run` has no `noReply` mechanism):

| Injection level | Prepended content |
|-----------------|-------------------|
| `minimal` | Conversation history summary only |
| `medium` (default) | History summary + PKB knowledge |
| `full` | History + PKB + memory pad |

For the first message (no stored session ID), the system prompt (user identity, conversation ID, instructions) is also prepended.

## Slash Commands

When OpenCode mode is active, slash commands are routed to dedicated methods:

| Command | Implementation |
|---------|----------------|
| `/compact` | Runs `opencode run --session <id> "compact"` |
| `/abort` | Info only — subprocess already finished |
| `/new` | Clears `active_session_id`; next message creates new session |
| `/sessions` | Lists stored session IDs from `opencode_config` |
| `/fork` | Runs `opencode run --session <id> "fork"` |
| `/summarize` | Runs `opencode run --session <id> "compact"` |
| `/status` | Shows binary path, session ID, model, timeout |
| `/diff` | Asks opencode to summarize file changes via `--session` |
| `/revert` | Info only — use `/new` instead |
| `/mcp` | Asks opencode to list MCP server status |
| `/models` | Runs `opencode models` CLI command |
| `/help` | Shows help table |
| Unknown `/cmd` | Passed as prompt to `opencode run --session <id> "/cmd ..."` |

## UI Settings

The OpenCode settings modal (`#opencode-settings-modal`) provides:

1. **Info banner**: Explains run mode, recommends small atomic tasks
2. **Context Injection Level** (`#opencode-injection-level`): minimal/medium/full
3. **Provider** (`#opencode-provider`): OpenRouter (default) or Amazon Bedrock
4. **Model** (`#opencode-model`): Claude model selection; default is Sonnet 4.6
5. **Session Info**: Shows current session ID and count (read-only)
6. **New Session button**: Tells user to send `/new` in chat

The "Always use OpenCode" toggle was removed — it was only meaningful with a persistent server. Instead, use the per-message `enable_opencode` checkbox in chat settings.

## Configuration

### `opencode.json` (project root)

opencode reads this file for MCP servers, permissions, and provider config. The model in `opencode.json` acts as a fallback but is overridden by `--model` flag from our code.

```json
{
  "model": "openrouter/anthropic/claude-sonnet-4.6",
  "permission": { "bash": "allow", "edit": "allow", "webfetch": "allow" },
  "provider": {
    "openrouter": { "options": { "apiKey": "{env:OPENROUTER_API_KEY}" } }
  },
  "mcp": { ... }
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Required for OpenRouter provider |
| `OPENCODE_RUN_TIMEOUT` | `120` | Subprocess timeout in seconds per call |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | For Bedrock provider |

### OPENCODE_AVAILABLE

Set to `True` if the `opencode` binary is found on `PATH` (via `shutil.which("opencode")`). If not found, the flag is `False` and OpenCode mode is silently disabled.

## Important Usage Notes for LLM

When the main LLM routes a request to opencode:

- **Keep tasks small and atomic** — one well-defined task per message (e.g. "edit this function", "run tests", "find files matching X")
- **Long tasks time out** — the default timeout is 120s. Multi-step work should be broken into separate messages
- **Session continuity** — related tasks can share a session via the stored session ID; unrelated work should use `/new`
- **opencode is the worker, not the manager** — the main LLM decides what to do; opencode executes specific file/code operations

## Key Files

| File | Purpose |
|------|---------|
| `Conversation.py` | `_run_opencode()`, `_reply_via_opencode()`, `_resolve_opencode_model()`, `_get/save_opencode_session_id()`, all `_opencode_*` slash command methods |
| `opencode.json` | opencode configuration (MCP servers, permissions, provider keys) |
| `interface/interface.html` | `#opencode-settings-modal` — provider/model/injection settings |
| `interface/chat.js` | `loadOpencodeSettings()`, save button handler |
| `opencode_client/` | Legacy server-based client (kept for reference, not used in run mode) |
