# LLM Tool Calling Framework

## What This Is

The tool calling framework gives the LLM the ability to **autonomously invoke tools mid-response** — searching the web, querying documents, asking clarifying questions, running code, and more — all within a single conversation turn. The user enables/disables tools via the chat settings modal, and the system handles execution, synchronization, and result feeding transparently.

**Key facts**: 87 tools across 13 categories. Up to 10 tool-call iterations per turn. 2 interactive tools (`ask_clarification`, `pkb_propose_memory`) that pause for user input. Non-interactive tools execute in parallel via ThreadPoolExecutor. Tool call history persists results in per-user SQLite for cross-conversation reuse.

**Full tool inventory**: For the complete list of all 87 tools with their parameters, descriptions, and handler implementations, see `code_common/tools.py` — each tool is defined via `@register_tool` decorator with its JSON Schema, category, and handler function inline.

**Plan reference**: `documentation/planning/plans/llm_tool_calling_framework.plan.md`

**Frontend streaming integration**: For details on how tool events are dispatched through `renderStreamingResponse()` to `ToolCallManager`, see `documentation/features/conversation_flow/conversation_flow.md`.

---

## How the System Works (Integration Flow)

The tool calling system spans four layers: UI settings → frontend payload → backend resolution → LLM API. Understanding this flow is essential for debugging and extending.

### End-to-End Flow

```
User selects tools in settings modal
         │
         ▼
Frontend reads selectpicker → builds checkboxes payload
         │
         ▼
Search-intent and URL auto-detection may inject web search/read tools (backend, upgrades `none` → `manual`)
         │
         ▼
POST /reply with { checkboxes: { enable_tool_use: true, enabled_tools: [...] } }
         │
         ▼
Conversation._get_enabled_tools(checkboxes) resolves final tool list
         │
         ▼
Tool awareness text appended to system prompt (preamble)
         │
         ▼
Conversation._run_tool_loop() starts agentic loop
         │
         ├─► LLM API call with tools=tools_config, tool_choice="auto"
         │         │
         │         ├─► LLM returns text → yield to stream, done
         │         │
         │         └─► LLM returns tool_calls → execute tools → feed results back → loop
         │
         └─► On iteration N (max): tool_choice="none" forces text-only response
```

### What Gets Injected Into the Prompt

When tools are enabled, two things happen:

1. **System prompt augmentation** — A `## Available Tools` section is appended to the preamble listing each enabled tool's name and description, plus usage guidance (when to use, when not to, parallel calling tips).

2. **OpenAI `tools` parameter** — The full JSON Schema definitions (name, description, parameters) are passed to `client.chat.completions.create(tools=tools_config)`. This is how the model knows the calling conventions.

3. **Dynamic document descriptions** — If document tools are enabled, their descriptions are enriched with the actual list of available documents (conversation + global docs, capped at 20 per type) so the LLM can skip calling `docs_list_*` and go straight to `docs_query`/`docs_get_full_text`.

### The Agentic Loop (`_run_tool_loop`)

```
Iteration 1..N:
  1. Call LLM with tools (tool_choice="auto", or "none" on final iteration)
  2. Parse streaming response:
     - Text chunks → yield to client stream
     - Tool call dicts → collect until finish_reason="tool_calls"
  3. If tool calls received:
     - SPECIAL CASE: If only call is `request_tools` (max 2/turn):
       → Expand tools_config, append assistant+tool messages, continue WITHOUT incrementing iteration
     - Classify: interactive vs non-interactive (via ToolDefinition.is_interactive)
     - Non-interactive: execute ALL in parallel (ThreadPoolExecutor, max 5 workers)
     - Interactive: execute sequentially with threading.Event wait (60s timeout)
     - If `request_tools` called alongside other tools: expand tools_config for next iteration
     - Emit tool_call/tool_status/tool_result streaming events to UI
     - Append {"role": "tool", "tool_call_id": ..., "content": result} to messages
     - Record in tool call history DB (fail-open)
     - Continue loop
  4. If text only: break, done
```

**Hard caps**: 10 iterations max (configurable), 50,000 character result truncation, 60-second interactive tool timeout, 2 zero-cost `request_tools` expansions per turn.

---

## UI Settings and Tool Filtering

### The Chat Settings Modal

The gear icon in the chat input area opens `#chat-settings-modal`. Tool settings live in the **Behavior & Memory** accordion section:

1. **Tool Mode selector**: `#settings-tool_mode` — a `<select>` with 5 options controlling how tools are loaded per turn:

   | Mode | Value | Behavior | Token Cost |
   |------|-------|----------|-----------|
   | Hybrid (AI + fallback) | `hybrid` | Fast LLM selects relevant tools + `request_tools` fallback | ~3,500-5,000 |
   | Smart Select (AI picks) | `smart` | Fast LLM selects relevant tools, no fallback | ~3,000-4,500 |
   | Tiered (core + on-demand) | `tiered` | Adaptive core tools + `request_tools` meta-tool | ~2,500 |
   | Manual Selection | `manual` | User picks specific tools via selectpicker dropdown | varies |
   | No Tools | `none` | Plain text only, zero overhead | 0 |

   **Default**: `hybrid` — best balance of token savings and capability.

2. **Tool selector dropdown** (visible only in `manual` mode): `#settings-tool-selector` — a Bootstrap Select 1.13.18 `<select multiple>` with:
   - 11 `<optgroup>` categories (Clarification, Web Search, Documents, Knowledge Base, Memory, Conversation, Code Runner, Artefacts, Prompts, Aggregator, Coding & Files)
   - ~98 individual `<option>` elements, each with `value="tool_name_string"`
   - `data-live-search="true"` — type-ahead filtering
   - `data-actions-box="true"` — Select All / Deselect All per category
   - `data-selected-text-format="count > 3"` — shows "{N} tools selected" when >3 selected

### Default Selections

- Default tool mode: `hybrid` (both in HTML `selected` attribute and in `computeDefaultStateForTab()` / `resetSettingsToDefaults()` in `chat.js`)
- In `manual` mode, `ask_clarification` is pre-selected by default
- Web Search tools are auto-injected by backend `_detect_auto_tools()` when URLs or search phrases are present (upgrades `none` → `manual`)

### Settings Payload Format

The frontend sends tool settings as part of the `checkboxes` object in the `/reply` request:

**Current format** (5-mode system):
```json
{
  "checkboxes": {
    "tool_mode": "hybrid",
    "enable_tool_use": true,
    "enabled_tools": ["ask_clarification", "web_search"]
  }
}
```

`tool_mode` controls behavior. `enable_tool_use` is derived (`tool_mode !== 'none'`) for backward compatibility. `enabled_tools` is only meaningful when `tool_mode` is `"manual"`.

**Legacy format** (still accepted — no `tool_mode` field):
```json
{
  "checkboxes": {
    "enable_tool_use": true,
    "enabled_tools": ["ask_clarification", "web_search"]
  }
}
```
Maps to `tool_mode = "manual"` when `enable_tool_use` is true, `"none"` when false.

### Backend Resolution (`_get_enabled_tools`)

`Conversation._get_enabled_tools(checkboxes, user_email, users_dir, user_message, summary)` resolves the final OpenAI tools parameter:

1. If `TOOLS_AVAILABLE` is False or `TOOL_REGISTRY` is None → `None`
2. Resolve `tool_mode` from checkboxes (falls back to legacy `enable_tool_use` boolean)
3. Dispatch by mode:
   - **`none`** → `None`
   - **`tiered`** → `get_adaptive_tier1_tools(user_email)` — personalized core set based on usage history (falls back to static `TIER_1_TOOLS` for new users)
   - **`smart`** → `_select_relevant_tools(user_message, summary, keys)` — fast LLM picks 15-25 relevant tools
   - **`hybrid`** → same as `smart` but ensures `request_tools` meta-tool is always included as fallback
   - **`manual`** → read `enabled_tools` (list or legacy category dict)
4. Call `TOOL_REGISTRY.get_openai_tools_param(enabled_names)` → OpenAI format list
5. If `request_tools` is in the set: inject names of all NOT-loaded tools into its description (so LLM knows what to request)
6. Call `_inject_dynamic_doc_descriptions()` to enrich document tools with actual doc listings
7. Return list (or `None` if empty)

### The `request_tools` Meta-Tool

A special tool that lets the LLM load additional tools on demand:

- **Description** dynamically includes the names of all tools NOT currently loaded
- **Zero-cost expansion**: When `request_tools` is the ONLY tool call in a response, tools are expanded without consuming an iteration (max 2 expansions per turn)
- **Mixed-mode**: When called alongside other tools, expansion happens for the next iteration (counts normally)
- **Safety cap**: Max 2 zero-cost expansions per turn to prevent infinite loops

### Adaptive Tier 1

In `tiered` and `hybrid` modes, the core tool set is personalized per user:

- **Fixed base** (5 tools): ask_clarification, pkb_search, delegate_task, search_messages, request_tools
- **Adaptive portion**: Most frequently used tools by this user (last 30 days from `tool_call_history` DB)
- **Target size**: 12 tools total
- **Fallback**: Static `TIER_1_TOOLS` if user has < 10 recorded tool calls
- **Caching**: Results cached per user with 1-day TTL. DB is not re-queried on every turn.

### Smart Select (`_select_relevant_tools`)

Uses `VERY_CHEAP_LLM[0]` to pick tools per-turn:

- Input: user message (500 chars), conversation summary + last user-assistant turn (500 chars), compact tool menu (one line per tool)
- Prompt: HIGH RECALL — "err heavily on inclusion, missing a needed tool is much worse than including an unneeded one"
- Output: JSON array of tool names, validated against registry
- Fallback: returns static `TIER_1_TOOLS` on any error (timeout, parse failure, etc.)
- Guardrails: minimum 3 tools (else merge with TIER_1), maximum 30 tools

### Performance

- **Parallel execution**: Tool selection fires as a `get_async_future` at the earliest possible point in `reply()` (right after `/pkb` guard, ~860 lines before resolution). Runs in parallel with PKB retrieval, prior context, TLDR extraction, doc processing, and visual tab.
- **Streaming status**: In smart/hybrid mode, a "Selecting tools..." status is yielded to the UI before resolving the future.
- **Net latency cost**: Effectively 0ms — the ~200ms LLM call completes during other parallel work.
- **Tiered mode**: No LLM call at all — just a cached DB lookup (1-day TTL).

### Prompt Cache Implications

Each unique combination of enabled tools produces a different `tools` parameter, which means different prompt cache keys. In `tiered` mode, the stable core set maximizes cache hits. In `smart`/`hybrid` mode, cache hit rates are lower but token savings outweigh the cost.

---

## Auto-Detection of Tool Need (Backend)

The system has **one automatic tool activation mechanism** in `Conversation._detect_auto_tools()` (backend, `Conversation.py`). It runs inside `_get_enabled_tools()` when `tool_mode == "none"` and upgrades to `manual` mode with specific tools if the message warrants it.

### How It Works

1. Called from `_get_enabled_tools()` when tool_mode is `"none"` (tools disabled)
2. Strips code blocks (fenced and inline) from the user message
3. Checks two conditions:
   - **URLs present** → injects `jina_read_page`, `read_link`
   - **Search intent phrases match** → injects `perplexity_search`, `jina_search`, `jina_read_page`, `read_link`
4. If any tools activated: overrides `tool_mode` to `"manual"` with only the detected tools

### Trigger Patterns (Search Intent)

~20 regex patterns (case-insensitive, word-boundary-anchored):

- **Explicit search**: "search the web/internet", "google X", "look up", "search online/about"
- **Recency**: "find recent/latest", "latest news/updates/research", "what's the latest"
- **Browse**: "look/check/find online", "browse the web"
- **Research**: "find information on/about", "news about X"
- **Direct tool references**: "use the search tool", "enable web search", "with web search"

### URL Detection

Simple `https?://\S+` regex on code-stripped text. When a link is present, the LLM gets `jina_read_page` and `read_link` tools so it can fetch additional pages if needed (the main link pipeline `read_over_multiple_links` already fetches provided links independently).

### Design Principles

- **Backend-only**: no frontend detection logic needed; single source of truth
- **Transparent**: user doesn't need to manually enable tools
- **Additive only**: only activates when mode is `"none"`, never overrides existing tool selections
- **Code-aware**: strips fenced and inline code blocks before matching to avoid false positives
- **Lazy compilation**: regex compiled once and cached on class

### Tools Auto-Injected

| Trigger | Tools |
|---------|-------|
| URL in message | `jina_read_page`, `read_link` |
| Search intent phrase | `perplexity_search`, `jina_search`, `jina_read_page`, `read_link` |

---

## Relationship to MCP Servers

The system has **two independent tool mechanisms** that share implementation but operate separately:

| Aspect | Native Tool Calling | MCP Servers |
|--------|-------------------|-------------|
| **Consumer** | Chat UI (via `/reply` endpoint) | External clients (OpenCode, Claude Code) |
| **Transport** | OpenAI `tools` parameter in API calls | MCP streamable-HTTP with JWT auth |
| **Ports** | None (in-process) | 8100-8108 (8 daemon threads) |
| **Filtering** | UI selectpicker → `_get_enabled_tools()` | All tools always available per server |
| **Auth** | Session-based (Flask login) | JWT bearer token (`MCP_JWT_SECRET`) |
| **Control** | User toggles per conversation | Static server config |

### Shared Implementation

Both systems call the same underlying business logic:
- `DocIndex.semantic_search_document()` for document queries
- `StructuredAPI.for_user().search()` for PKB operations
- `WebSearchWithAgent` / `PerplexitySearchAgent` / `JinaSearchAgent` for web search
- `Conversation.search_messages()` for message search

Shared metadata is defined once and imported by both:
- `CONVERSATION_TOOLS` in `code_common/conversation_search.py` (5 conversation tools)
- `TOOL_HISTORY_TOOLS` in `code_common/tool_call_history.py` (4 history tools)
- `CROSS_CONVERSATION_TOOLS` in `code_common/cross_conversation_search.py` (3 cross-conv tools)

### MCP Server Architecture

8 MCP servers start as daemon threads alongside Flask when `MCP_JWT_SECRET` is set:

| Server | Port | Module | Tools |
|--------|------|--------|-------|
| Web Search | 8100 | `mcp_server/mcp_app.py` | 4 |
| PKB | 8101 | `mcp_server/pkb.py` | 8-15 (tier-dependent) |
| Documents | 8102 | `mcp_server/docs.py` | 4-9 (tier-dependent) |
| Artefacts | 8103 | `mcp_server/artefacts.py` | 8 |
| Conversation | 8104 | `mcp_server/conversation.py` | 5 |
| Prompts | 8105 | `mcp_server/prompts_actions.py` | 5 |
| Code Runner | 8106 | `mcp_server/code_runner_mcp.py` | 1 |
| Coding Tools | 8108 | `mcp_server/coding_tools.py` | 12 |

**Ops docs**: `documentation/product/ops/mcp_server_setup.md`

---

## Tool Call History

### What It Does

Records every tool execution (inputs, outputs, timing) in a per-user SQLite database. Enables the LLM to query past results and avoid redundant re-execution of expensive operations (especially web searches).

### Why It Exists

Tool results (`role: "tool"` messages in the agentic loop) are **ephemeral** — they exist only during `_run_tool_loop()` and are stripped from persisted messages. The `<tool_calls_summary>` block is regex-removed before storage. Without history, follow-up questions requiring the same search force complete re-execution.

### Architecture

```
Tool Execution (Conversation.py _run_tool_loop)
    │
    └── record to ToolCallHistoryDB (fail-open, try/except)

MCP Tool Execution (mcp_server/mcp_app.py)
    │
    └── record via _record_mcp_tool_call() (fail-open)
    
         ▼
ToolCallHistoryDB (storage/users/tool_call_history.sqlite)
    │
    ├── Queried by 4 LLM tools (list_search_history, get_search_results,
    │   list_tool_call_history, get_tool_call_results)
    │
    └── Auto-pruned: 30-day age limit, 10,000 rows per user
```

### Deterministic Hash IDs

`tool_call_hash(tool_name, args_dict)` = `SHA-256("tool_name:canonical_json")[:16]`

Same tool + same arguments always produces the same ID. This enables:
- Deduplication detection (LLM can check if a search was already performed)
- Argument order doesn't matter (`sort_keys=True`)
- 64 bits of entropy — negligible collision probability at expected volumes

### Storage Schema

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Deterministic hash (16-char hex) |
| `tool_name` | TEXT | e.g. `web_search`, `pkb_search` |
| `tool_category` | TEXT | e.g. `search`, `documents` |
| `args_json` | TEXT | JSON-serialized arguments |
| `result_text` | TEXT | Full result (capped at 50K chars) |
| `error` | TEXT | Error message if failed, NULL otherwise |
| `user_email` | TEXT | Scoping key |
| `conversation_id` | TEXT | Where the tool was called |
| `timestamp` | REAL | Unix epoch |
| `duration_seconds` | REAL | Wall-clock execution time |
| `result_chars` | INTEGER | Length of result_text |
| `source` | TEXT | `"tool_calling"` or `"mcp"` |

**Primary key**: `(id, timestamp)` — allows repeated executions of same tool+args.

### Query Tools

| Tool | Purpose |
|------|---------|
| `list_search_history` | List past web searches/page reads (search category only) |
| `get_search_results` | Get full result text by IDs (avoids re-executing) |
| `list_tool_call_history` | List past tool calls across ALL categories |
| `get_tool_call_results` | Get full results by IDs (any category) |

### Current Limitation

The query tools only support:
- `query_contains`: substring match on `args_json` (case-insensitive)
- Category/tool name exact filters
- Time-based filters (`since_hours`)
- Conversation scoping (`conversation_only`)

There is **no semantic or BM25 search** over tool call history. Finding past results requires knowing keywords that appear in the arguments. A `search_tool_call_history` tool with hybrid semantic+BM25 search (modeled after `MessageSearchIndex` in `conversation_search.py`) would make history significantly more useful.

### Key Files

| File | Role |
|------|------|
| `code_common/tool_call_history.py` | `ToolCallHistoryDB` class, hash function, shared tool metadata |
| `Conversation.py` | 2 recording hooks in `_run_tool_loop()` |
| `mcp_server/mcp_app.py` | `_record_mcp_tool_call()` helper, recording in 4 MCP tools |
| `code_common/tools.py` | 4 `@register_tool` registrations |

---

## Interactive Tools and Thread Synchronization

Two tools require pausing the streaming response to wait for user input:
- `ask_clarification` — shows MCQ modal for clarifying questions
- `pkb_propose_memory` — shows editable memory proposal cards

### Synchronization Mechanism

```
_run_tool_loop() thread                          User/Browser
        │                                              │
        ├── Execute interactive tool                   │
        │   → ToolCallResult(needs_user_input=True)    │
        │                                              │
        ├── Yield tool_input_request event ──────────► Modal appears
        │                                              │
        ├── Call wait_for_tool_response(tool_id, 60s)  │
        │   → Creates threading.Event                  │
        │   → event.wait(timeout=60)                   │
        │                                              │
        │                               User answers ──┤
        │                                              │
        │   ◄────── POST /tool_response/{conv}/{tool}  │
        │           → event.set()                      │
        │                                              │
        ├── Receive response data                      │
        ├── Format as tool result message              │
        └── Continue loop                              │
```

**Timeout behavior**: If user doesn't respond within 60 seconds, `event.wait()` returns False, and `"User did not respond within the timeout period"` is fed to the LLM, which then generates a best-effort response.

### API Endpoint

**`POST /tool_response/<conversation_id>/<tool_id>`** (`endpoints/conversations.py`)

Submit user response for an interactive tool call.

Request body:
```json
{"response": {"answers": [{"question": "What industry?", "selected_option": "Tech"}]}}
```

Responses:
- `200 {"status": "ok"}` — response received, background thread unblocked
- `400 {"error": "Missing 'response' field"}` — malformed request
- `404 {"error": "No pending tool request for tool_id: ..."}` — no waiting thread

### Frontend (`ToolCallManager` in `interface/tool-call-manager.js`)

Singleton managing all tool call UI:
- **Inline status pills**: show during tool execution (spinner), then fade after completion
- **Interactive modal** (`#tool-call-modal`): renders dynamically based on `ui_schema`
- **Push notifications**: via `NotificationManager` when modal appears (works in Electron/browser/mobile)
- **Keyboard**: Enter submits when modal is open (unless in textarea)
- **Skip/Cancel**: fires `{ skipped: true }` to server endpoint

---

## Tool Call Timing

Every tool execution is timed. Two durations tracked per call:

- **`tool_exec_duration`**: Wall-clock time for `TOOL_REGISTRY.execute()` only
- **`tool_total_duration`**: Exec time + user-wait time (for interactive tools; same as exec for server-side)

Timing appears in:
1. **`tool_result` streaming event**: `duration_seconds` field
2. **Inline status pill (UI)**: appends `(Xs)` to result summary
3. **Collapsible `<tool_calls_summary>` block**: shows `(N chars, Xs)` per tool
4. **`time_dict` (end-of-message YAML)**: `tool_calls` list with per-tool timing

---

## Parallel Tool Execution

When the LLM issues multiple tool calls in one response:

1. **Classify** each call as interactive or non-interactive (via `ToolDefinition.is_interactive`)
2. **Non-interactive**: execute ALL in parallel via `ThreadPoolExecutor` (max 5 workers). Each thread gets a `deepcopy` of `ToolContext`.
3. **Interactive**: execute sequentially AFTER all non-interactive tools complete (require `threading.Event` synchronization)
4. **Results emitted in original call order** regardless of completion order

The system prompt explicitly instructs the LLM to issue parallel calls: "All non-interactive tool calls in the same response are executed in parallel, so issuing multiple calls simultaneously is significantly faster than calling them one at a time across multiple rounds."

---

## Streaming Protocol

Tool calling extends the existing newline-delimited JSON streaming with new event types:

| Event Type | Key Fields | When Sent |
|------------|-----------|-----------|
| `tool_call` | `type`, `tool_id`, `tool_name`, `tool_input` | LLM requests a tool invocation |
| `tool_status` | `type`, `tool_id`, `tool_status` | Execution state change (`executing`, `waiting_for_user`, `completed`, `error`) |
| `tool_input_request` | `type`, `tool_id`, `tool_name`, `ui_schema` | Interactive tool needs user input |
| `tool_result` | `type`, `tool_id`, `tool_name`, `result_summary`, `duration_seconds` | Tool completed |

**Example sequence (server-side tool)**:
```json
{"type": "tool_call", "tool_id": "call_xyz", "tool_name": "web_search", "tool_input": {"query": "quantum computing 2026"}}
{"type": "tool_status", "tool_id": "call_xyz", "tool_status": "executing"}
{"type": "tool_status", "tool_id": "call_xyz", "tool_status": "completed"}
{"type": "tool_result", "tool_id": "call_xyz", "tool_name": "web_search", "result_summary": "Found 5 results", "duration_seconds": 3.5}
{"text": "Here are the latest developments in quantum computing..."}
```

---

## Tool Categories and Defaults

| Category | Count | Default | Description |
|----------|-------|---------|-------------|
| `clarification` | 1 | ON | Interactive MCQ clarification questions |
| `search` | 5 | OFF (auto-injected) | Web search, Perplexity, Jina, page reading |
| `documents` | 14 | OFF | Conversation + global doc search/query/list/upload/delete/tag |
| `pkb` | 16+ | OFF | Personal Knowledge Base CRUD, NL command, propose memory, STM |
| `memory` | 7 | OFF | Conversation memory pad, user details/preferences |
| `conversation` | 5 | OFF | BM25 message search, list/read messages, conversation details |
| `cross_conversation` | 7 | OFF | Cross-conv search + tool call history (4 tools) |
| `code_runner` | 1 | OFF | Run Python code (30s default timeout, configurable) |
| `artefacts` | 8 | OFF | File CRUD, LLM-powered propose/apply edits |
| `prompts` | 5 | OFF | Saved prompt management, temp LLM actions |
| `aggregator` | 4 | OFF | Delegate sub-tasks to autonomous agents (sync + background) |
| `coding` | 12 | OFF | File system ops, PDF, image analysis, bash, grep, todos |
| `general` | 2 | OFF | Image generation, audio transcription |

**Design principle**: Categories default OFF for write-capable or resource-intensive tools. Only `clarification` defaults ON to enable the core "ask me questions" behavior without configuration.

---

## Controls and Safety

| Control | Value | Description |
|---------|-------|-------------|
| Master toggle | `checkboxes.enable_tool_use` | Gates all tool functionality. OFF = zero overhead. |
| Per-tool selector | `checkboxes.enabled_tools` | Array of tool name strings. |
| Iteration cap | 10 | Hard maximum tool-call rounds per turn. Final iteration forces `tool_choice="none"`. |
| Interactive timeout | 60 seconds | `threading.Event.wait(timeout=60)`. |
| Result truncation | 50,000 characters | `TOOL_RESULT_TRUNCATION_LIMIT`. |
| Fail-open execution | Always | `ToolRegistry.execute()` catches all exceptions. Errors become LLM messages. |
| Path sandboxing | Project root | All file system tools reject paths that escape `os.getcwd()`. |
| Parallel workers | 5 | ThreadPoolExecutor max workers for concurrent tool calls. |

---

## Developer Guide: Adding New Tools

### Step 1: Define with `@register_tool`

In `code_common/tools.py`:

```python
@register_tool(
    name="my_new_tool",
    description=(
        "Brief description. Include guidance on WHEN the LLM should use it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
    is_interactive=False,
    category="search",   # Must match existing category or add new one
)
def handle_my_new_tool(args: dict, context: ToolContext) -> ToolCallResult:
    query = args.get("query", "")
    # ... implementation ...
    return ToolCallResult(
        tool_id="",
        tool_name="my_new_tool",
        result=_truncate_result(result_text),
    )
```

### Step 2: Rules for Tool Handlers

- `name` must be unique across all tools
- `description` should tell the LLM WHEN to use the tool, not just what it does
- Handler must NEVER raise — catch exceptions internally, return error in `ToolCallResult.error`
- Results are auto-truncated to 50,000 chars by `ToolRegistry.execute()` (safety net)
- Use `context.keys` for API credentials, `context.conversation_id` and `context.user_email` for scoping
- For interactive tools: return `ToolCallResult(needs_user_input=True, ui_schema={...})`

### Step 3: UI Changes (if adding a new category)

If using an existing category, no UI changes needed — the tool auto-appears in the dropdown.

For a **new category**:

1. **HTML** (`interface/interface.html`): Add `<optgroup>` in `#settings-tool-selector`:
   ```html
   <optgroup label="My Category">
       <option value="my_new_tool">My New Tool</option>
   </optgroup>
   ```

2. **JavaScript** (`interface/chat.js`): Add to `categoryDefaults` in `setModalFromState()`:
   ```javascript
   my_category: ['my_new_tool']
   ```

3. **Backend** (`Conversation.py`): Add to legacy mapping in `_get_enabled_tools()`:
   ```python
   "my_category": enabled_tools_config.get("my_category", False),
   ```

### Step 4: Expose via MCP (Optional)

To also expose the tool to external MCP clients, add a corresponding function in the appropriate `mcp_server/*.py` module. Use shared metadata dicts (like `CONVERSATION_TOOLS` pattern) to keep descriptions in sync.

### Step 5: Testing Checklist

1. Tool appears in API call when enabled (check server logs at DEBUG)
2. LLM invokes tool with appropriate prompt
3. Handler executes and returns valid `ToolCallResult`
4. Result fed back to LLM; LLM references output in response
5. Error handling: force an error, verify graceful degradation
6. Tool does NOT appear when disabled
7. Interactive tools only: modal renders, user can submit/skip, thread unblocks

---

## Headless Mode and Query Bypass (Search Tools)

All search tool handlers (`web_search`, `perplexity_search`, `jina_search`) run their underlying agents in **headless mode** (`headless=True`):
- Skips the combiner LLM step (no second LLM call to synthesize results)
- Returns raw search results directly

Additionally, handlers pre-format query+context as a Python code block:
```python
f"```python\n[({repr(query)}, {repr(context)})]\n```"
```

This format is recognized by the agent's `extract_queries_contexts()` method, which parses it directly and **bypasses the internal LLM query-generation step**. The calling LLM has already crafted a good query — no need for a second LLM call inside the agent.

---

## Implementation Notes

1. **Coexistence with `/clarify`**: Tool-based `ask_clarification` and the `/clarify` slash command are independent. `/clarify` is pre-send (intercepts before LLM). Tool-based clarification is mid-response (LLM decides). Both can be active simultaneously.

2. **Model compatibility**: Tool calling uses OpenAI-native `tools` parameter via OpenRouter. Not all models support tool calling. If a model doesn't support tools, the master toggle should be OFF (no backend model validation currently).

3. **Messages mode for continuation**: After the first LLM call, continuation calls use `messages` parameter (pre-built messages array including tool call/result pairs) rather than `text`/`system`.

4. **Write operations**: Tools that modify persistent state (PKB add/edit/pin, memory pad set, artefact create/update/delete, prompt create/update, file write/patch) belong to categories that default OFF.

5. **Service worker cache**: When modifying `tool-call-manager.js`, bump both `CACHE_VERSION` in `service-worker.js` and the `?v=N` query parameter in the script tag.

6. **HTTP-delegated tools**: `artefacts_propose_edits`, `artefacts_apply_edits`, and `temp_llm_action` delegate to Flask HTTP endpoints rather than calling business logic directly (complex LLM streaming or optimistic concurrency).

7. **SUPERFAST_LLM for Jina**: `jina_search` uses `SUPERFAST_LLM[0]` (`inception/mercury-2`) for faster per-query summarization.

8. **Default tool enablement**: `computeDefaultStateForTab()` and `resetSettingsToDefaults()` both set `enable_tool_use: true` and `enabled_tools: ['ask_clarification']`.

9. **Shared tool metadata pattern**: Tools that need to be registered in both the tool-calling framework and MCP servers define their metadata once in a shared module (e.g., `CONVERSATION_TOOLS`, `TOOL_HISTORY_TOOLS`, `CROSS_CONVERSATION_TOOLS`) and import from both sides.

---

## Key Files

| File | Role |
|------|------|
| `code_common/tools.py` | Tool registry framework + all 87 tool handler implementations |
| `code_common/call_llm.py` | `tools`/`tool_choice` params, streaming tool call extraction |
| `code_common/tool_call_history.py` | History DB, hash function, shared metadata for 4 history tools |
| `code_common/agent_tool.py` | Aggregator sub-agent loop, background task store, shared metadata |
| `code_common/conversation_search.py` | Shared metadata for 5 conversation tools, BM25 index |
| `code_common/cross_conversation_search.py` | Cross-conv FTS5 search, shared metadata for 3 tools |
| `Conversation.py` | `_get_enabled_tools()`, `_run_tool_loop()`, `_inject_dynamic_doc_descriptions()`, recording hooks |
| `call_llm.py` (root) | Threads `tools`/`tool_choice` through `CallLLm.__call__()` |
| `endpoints/conversations.py` | `/tool_response` endpoint, thread sync (`_tool_response_events/data/lock`) |
| `interface/tool-call-manager.js` | UI singleton: status pills, modal rendering, response submission |
| `interface/interface.html` | Bootstrap Select dropdown, `#tool-call-modal`, CSS |
| `interface/chat.js` | Settings persistence, `setModalFromState()`, `categoryDefaults` |
| `interface/common-chat.js` | Stream handler dispatch |
| `interface/common.js` | `getOptions()` reads tool settings from selectpicker |
| `interface/service-worker.js` | `tool-call-manager.js` in precache list |

---

## User Perspective: Example Flows

**Flow 1 — Tool-based clarification**:
User sends "Help me write a business plan" with tools enabled. The LLM invokes `ask_clarification` with questions like "What industry?" and "What stage is your business?". A modal appears with MCQ radio buttons. User selects answers and clicks Submit. The LLM receives the answers and continues generating a tailored business plan — all in one turn, no re-send needed.

**Flow 2 — Autonomous web search**:
User asks "What are the latest developments in quantum computing?". The LLM invokes `web_search` with a relevant query. An inline status pill shows "Searching the web..." briefly. Results are fed back to the LLM, which synthesizes them into a current, cited response.

**Flow 3 — Multi-step tool chain**:
The LLM calls `web_search`, reviews results, then calls `ask_clarification` to narrow the topic, then calls `document_lookup` to cross-reference with uploaded docs. Each tool invocation shows a brief status indicator. The final response integrates all gathered information.

**Flow 4 — Tools disabled**:
User has the master toggle OFF. The LLM responds with plain text only. If it would have asked clarifying questions, it writes them inline as text (existing behavior). No tool infrastructure is loaded.

**Flow 5 — Interactive tool timeout**:
User doesn't respond to a clarification modal within 60 seconds. The LLM receives a "User did not respond within the timeout period" message and continues generating a best-effort response.

---

## Call Stack Detail

**Without tools (existing path, unchanged)**:
```
Conversation.reply()
  -> CallLLm(prompt, images, system, keys, ...)
    -> call_llm(keys, model, text, images, system, stream=True)
      -> call_chat_model(model, text, images, temperature, system, keys)
        -> client.chat.completions.create(model, messages, stream=True)
        -> _extract_text_from_openai_response(response) -> yields str chunks
```

**With tools (new path)**:
```
Conversation.reply()
  -> tools_config = self._get_enabled_tools(checkboxes)
  -> if tools_config:
      -> _run_tool_loop(prompt, preamble, images, model, keys, tools_config, ...)
        -> Iteration 1..N:
          -> call_llm(keys, model, text/messages, tools=tools_config, tool_choice="auto")
            -> call_chat_model(..., tools=tools_config, tool_choice="auto")
              -> client.chat.completions.create(..., tools=tools_config)
              -> _extract_text_from_openai_response() -> yields str | dict
          -> If tool_call dicts received:
            -> Classify: interactive vs non-interactive
            -> Non-interactive tools: ThreadPoolExecutor parallel execution
               (each thread gets deepcopy of ToolContext)
            -> Interactive tools: sequential execution with wait_for_tool_response()
            -> Append all {"role": "tool", "tool_call_id": ..., "content": result} to messages
            -> Continue loop
          -> If text only: break loop, done
    else:
      -> existing path (unchanged)
```

---

## Backend Function Reference

**`_extract_text_from_openai_response(response)`** (`code_common/call_llm.py`):
Parses OpenAI streaming chunks. Maintains `pending_tool_calls` dict keyed by index. Yields `str` for text content and `dict` for completed tool calls (when `finish_reason == "tool_calls"`). Tool call dict shape: `{"type": "tool_call", "id": str, "function": {"name": str, "arguments": str}}`.

**`call_chat_model(..., tools=None, tool_choice=None)`** (`code_common/call_llm.py`):
Core API call function. When `tools` is provided, adds `tools` and `tool_choice` to the `client.chat.completions.create()` kwargs. Supports two modes: simple (text + system) and messages (pre-built messages array for continuation calls).

---

## Tool Registry Classes

```python
ToolContext:
  conversation_id: str
  user_email: str
  keys: dict
  conversation_summary: str
  recent_messages: list
  model_overrides: dict

ToolCallResult:
  tool_id: str
  tool_name: str
  result: str
  error: Optional[str]
  needs_user_input: bool
  ui_schema: Optional[dict]

ToolDefinition:
  name: str
  description: str
  parameters: dict  # JSON Schema
  handler: Callable
  is_interactive: bool
  category: str

ToolRegistry:
  register(tool_def) -> None
  get_tool(name) -> Optional[ToolDefinition]
  get_all_tools() -> List[ToolDefinition]
  get_tools_by_category(category) -> List[ToolDefinition]
  get_openai_tools_param(enabled_names) -> List[dict]
  execute(name, args, context, tool_call_id) -> ToolCallResult
```

**Singleton**: `TOOL_REGISTRY = ToolRegistry()` — global instance, imported by `Conversation.py` and `call_llm.py`.

---

## Dynamic Document Description Injection Details

When document tools are enabled, `_inject_dynamic_doc_descriptions(tools_param, user_email, users_dir)` enriches descriptions per-tool:

- **`docs_list_global_docs`**: Appends numbered listing of global documents (display_name, doc_id, path, priority label, deprecated tag) or "No global documents currently available."
- **`docs_list_conversation_docs`**: Appends numbered listing of conversation documents (name, #doc_N, path, priority label, deprecated tag) or "No documents attached to this conversation."
- **`docs_query`, `docs_get_full_text`, `docs_get_info`, `docs_answer_question`**: Appends combined `doc_storage_path` values from both conversation and global docs.
- **`docs_get_global_doc_info`, `docs_query_global_doc`, `docs_get_global_doc_full_text`**: Appends available global `doc_id` values.
- **Cap**: `_DOC_LIST_CAP = 20` docs per type. Truncated with "... and N more" when exceeded.
- **Lazy loading**: Docs fetched only when a matching tool is found in the enabled list.

---

## Extended Implementation Notes

10. **Handler implementation status**: All 87 tool handlers have real implementations wired to the underlying business logic. No stubs. Handlers mirror the exact logic from MCP server modules and call the same underlying functions (e.g. `DocIndex.semantic_search_document()`, `StructuredAPI.for_user().search()`, `Conversation.list_artefacts()`) directly without going through MCP transport. Helper functions per category (e.g. `_docs_load_doc_index()`, `_get_pkb_api()`, `_conv_load()`, `_art_load_conversation()`, `_get_prompt_manager()`) are defined inline in `code_common/tools.py`.

11. **`deep_search` removed from MCP server**: The `InterleavedWebSearchAgent` (multi-hop iterative search) was removed from the MCP server. It remains available via the main chat UI (`Conversation.py`) and the extension server where the streaming multi-step search→answer loop is rendered progressively, but is not exposed as an MCP tool or tool-calling framework tool.

12. **MCP server search tool alignment**: All MCP search tools in `mcp_server/mcp_app.py` follow the same patterns as tool-calling handlers: accept `context` parameter, pre-format as Python code block for `extract_queries_contexts()` bypass, run in headless mode.

13. **BM25 message search index**: Conversation messages are incrementally indexed at persist time (`persist_current_turn`). The index stores unigram + bigram tokens with boosted weights for markdown headers and bold text. `MessageSearchIndex` serializes to/from JSON (BM25Okapi rebuilt lazily from stored token corpus). Older conversations get one-time full build on first search. Stored as `message_search_index` in `store_separate`.

14. **Result truncation details**: `_truncate_result()` caps at `TOOL_RESULT_TRUNCATION_LIMIT = 50000` chars. Suffix length computed dynamically (`max_len - len(suffix)`). Applied in two places: (a) handlers call it before returning, (b) `ToolRegistry.execute()` as safety net. Double application is idempotent.

15. **Thread safety**: Tool response synchronization uses `threading.Lock` for shared `_tool_response_events` and `_tool_response_data` dicts, `threading.Event` for blocking/unblocking. Each tool call gets its own Event instance. Server-side state in `endpoints/conversations.py`: `_tool_response_events = {}`, `_tool_response_data = {}`, `_tool_response_lock = threading.Lock()`.

16. **SUPERFAST_LLM validation fallback**: Because `SUPERFAST_LLM` may produce malformed structured output (list-of-tuples format), query generation includes validation (non-empty list of 2-tuples with non-empty string queries) and falls back to `CHEAP_LLM[0]` on parsing failure.

17. **Selectpicker CDN dependencies**: JS: `bootstrap-select@1.13.18/dist/js/bootstrap-select.min.js` (after bootstrap.bundle.min.js). CSS: `bootstrap-select@1.13.18/dist/css/bootstrap-select.min.css`. Version 1.13.x required for Bootstrap 4.6 compatibility; 1.14+ targets Bootstrap 5 only. All selectpicker interactions guarded with `typeof $.fn.selectpicker !== 'undefined'`.

18. **Selectpicker initialization and refresh**: Initialized in inline `<script>` after the select element. Refreshed on modal open (`$('#chat-settings-modal').on('shown.bs.modal', ...)`), master toggle change, and in `collectSettingsFromModal()` before reading values. Legacy state restoration via `categoryDefaults` mapping in `setModalFromState()`.

19. **Settings persistence details**: Reads via `getSelectPickerValue('#settings-tool-selector', [])`. Restores via `$('#settings-tool-selector').val(names)` + `selectpicker('refresh')`. `setModalFromState()` handles both array (new) and dict (legacy) formats.

20. **`time_dict` example**:
```yaml
tool_calls:
- name: jina_search
  duration_s: 3.45
  result_chars: 4200
- name: ask_clarification
  duration_s: 15.2
  result_chars: 150
total_time_to_reply: 28.5
```

21. **`<tool_calls_summary>` block**: Regex-removed before message storage (Conversation.py lines 3836-3848). Only timing metadata in `time_dict.tool_calls` survives persistence.

22. **Tool call history DB indexes**: `user_email`, `tool_name`, `tool_category`, `timestamp`, `conversation_id`, `id`, composite `(user_email, tool_category, timestamp DESC)`.

23. **Tool call history singleton**: `get_tool_call_history_db()` returns module-level singleton, lazy-initialized with double-checked locking. Thread-safe via WAL mode and `threading.Lock`.

---

## Files Modified and Created (Original Implementation)

| File | Type | Description |
|------|------|-------------|
| `code_common/tools.py` | **New** | Tool registry framework + 87 tool definitions + `TOOL_REGISTRY` singleton |
| `code_common/call_llm.py` | Modified | `tools`/`tool_choice` params, `_extract_text_from_openai_response()` extended for tool calls |
| `call_llm.py` (root) | Modified | Threaded `tools`/`tool_choice` through `CallLLm.__call__()` |
| `Conversation.py` | Modified | `_get_enabled_tools()`, `_run_tool_loop()`, preamble injection, `search_messages()`, `list_messages()`, `read_message()`, `get_conversation_details()`, BM25 index |
| `endpoints/conversations.py` | Modified | `/tool_response` endpoint, `wait_for_tool_response()`, thread sync state |
| `interface/tool-call-manager.js` | **New** | ToolCallManager singleton (status pills, modal, submission) |
| `interface/interface.html` | Modified | Bootstrap Select CDN, tool selector dropdown (11 optgroups, 87 options), `#tool-call-modal`, CSS |
| `interface/chat.js` | Modified | Settings persistence, `setModalFromState()`, `categoryDefaults` |
| `interface/common-chat.js` | Modified | Stream handler dispatch |
| `Conversation.py` | Modified | `_detect_auto_tools()` — backend search-intent and URL auto-detection |
| `interface/common.js` | Modified | `getOptions()` reads tool settings from selectpicker |
| `interface/service-worker.js` | Modified | Precache list update |
| `code_common/conversation_search.py` | **New** | `CONVERSATION_TOOLS` dict, `MessageSearchIndex`, `extract_markdown_features()` |
| `code_common/tool_call_history.py` | **New** | `ToolCallHistoryDB`, `tool_call_hash()`, `TOOL_HISTORY_TOOLS`, `SEARCH_TOOL_NAMES` |

---

## Category-Specific Implementation Details

### Aggregator Tools

- **`delegate_task`**: `run_agent_loop()` is a plain blocking function. Calls `call_llm(stream=False)`, executes tool calls via `TOOL_REGISTRY.execute()`. 1-level recursion guard (stripped at depth ≥ 2). Default model: `openai/gpt-4o-mini`. 5-min wall-clock timeout.
- **`delegate_task_background`**: Tasks in `_BACKGROUND_TASKS` dict in `code_common/agent_tool.py`, keyed by UUID4. Daemon thread runs `run_agent_loop()`, writes result on completion. Tasks expire after 30 min. The `general` profile includes `delegate_task_background`.
- 3 profiles: `research` (search + documents tools), `documents` (documents + PKB tools), `general` (all non-interactive tools including background delegation).
- **Plan reference**: `documentation/planning/plans/agent_delegate_task.plan.md`

### Coding Tools

- **Path sandboxing**: All paths resolve via `_coding_resolve_safe_path()` — any path escaping `os.getcwd()` is rejected with ValueError.
- **`fs_read_file` multi-type support**: Text (numbered lines with range), PDF (pdfplumber page extraction), Image (vision LLM: OCR + Scene + Objects + Summary).
- **`fs_get_file_structure_and_summary` agent design**: Uses `TOOL_REGISTRY.get_openai_tools_param()` to give the LLM schemas for 5 tools (`fs_read_file`, `fs_read_pdf`, `fs_grep`, `fs_list_dir`, `fs_bash`). Up to 5 sub-calls. On max: removes tools, nudges LLM to produce `STRUCTURE:` / `SUMMARY:` free text. For images: single vision call.
- **Image support** (`_FS_IMAGE_EXTENSIONS`): `.jpg/.jpeg/.png/.gif/.webp/.bmp/.tiff/.tif`. Uses `VERY_CHEAP_LLM[0]` = `google/gemini-3.1-flash-lite-preview` (vision-capable). Returns: OCR, Scene Description, Objects & Elements, Summary.
- **Todo storage**: Global → `storage/todo.json`. Conversation → `storage/conversations/{conv_id}/todo.json`. Schema: `{id, content, status, priority}`. IDs auto-assigned (1-based) if missing.
- **MCP server**: `mcp_server/coding_tools.py` — port 8108. All 12 coding tools via MCP. Entry in `opencode.json` as `coding-tools`.
