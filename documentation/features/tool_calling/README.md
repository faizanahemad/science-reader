# LLM Tool Calling Framework

## Overview

The LLM Tool Calling Framework adds native, mid-response tool calling to the chat pipeline. Instead of requiring users to pre-configure actions before sending a message (e.g. the `/clarify` slash command or auto-clarify checkbox), the LLM can now autonomously invoke tools during a conversation turn -- asking clarifying questions, searching the web, looking up documents, managing PKB entries, running code, and more -- all within a single streaming response.

This transforms the application from a "configure then send" model to a truly agentic one where the LLM reasons about what it needs and acts accordingly. The framework supports multi-step tool chains (up to 5 iterations per turn), interactive tools that pause for user input, and server-side tools that execute silently.

**Key numbers**: 87 tools across 13 categories. 2 interactive tools (`ask_clarification`, `pkb_propose_memory`). Master toggle + per-category toggles. 60-second interactive timeout. 5-iteration hard cap. 50000-character result truncation. Tool use enabled by default with `ask_clarification` pre-selected. Search-intent auto-detection dynamically adds web search tools based on message keywords. Tool call history records all executions in per-user SQLite for LLM-driven result reuse.

**Plan reference**: `documentation/planning/plans/llm_tool_calling_framework.plan.md`

## User Guide

### Enabling Tool Calling

Tool calling is controlled via the chat settings panel (gear icon in the chat input area):

1. **Master toggle**: "Enable Tools" checkbox -- gates all tool functionality. When OFF, the LLM behaves exactly as before (plain text responses, no tool invocations). **Enabled by default** for new sessions.
2. **Tool selector dropdown**: When the master toggle is ON, a Bootstrap Select multi-select dropdown appears (`#settings-tool-selector`). This dropdown lists all 87 tools grouped by category using `<optgroup>` elements. Users can:
   - **Select/deselect individual tools** -- granular per-tool control
   - **Select/deselect entire categories** -- via the optgroup headers (Bootstrap Select `data-actions-box`)
   - **Search tools by name** -- via `data-live-search` filter
   - **See selection count** -- shows "{N} tools selected" when more than 3 are selected

**Default selections**: `ask_clarification` is selected by default. Web search tools are **not** selected by default in the UI but are **automatically injected** when the user's message contains search-intent keywords (see "Search-Intent Auto-Detection" below). PKB, Memory, Code Runner, Artefacts, and Prompts categories are deselected by default.

**Search-intent auto-detection**: When the user types a message containing phrases like "search the web", "google", "latest news about", "find me recent info", etc., the frontend automatically enables tool use and injects the 5 web search tools (`web_search`, `perplexity_search`, `jina_search`, `jina_read_page`, `read_link`) into the enabled tools list — even if the user hadn't manually selected them. This happens transparently in `sendMessageCallback()` after option merging, using `detectSearchIntent()` and `mergeWebSearchTools()` in `common-chat.js`. Code blocks in the message are stripped before keyword matching to avoid false positives. The detection does NOT return early or modify the message text — it only modifies the `options` object in-place.

Settings are persisted per-conversation via the existing chat settings mechanism (`checkboxes` payload in the `/reply` request). The dropdown uses Bootstrap Select 1.13.18 (compatible with Bootstrap 4.6).

### Available Tool Categories

| Category | Tools | Default | Description |
|---|---|---|---|
| `clarification` | 1 | ON | Interactive clarification questions with MCQ options. Pauses stream, shows modal, collects user answers, resumes. |
| `search` | 5 | ON | Web search (standard, Perplexity, Jina), page reading (Jina Reader, generic link reader). |
| `documents` | 14 | ON | Search/query conversation docs and global docs. List, get metadata, get full text, semantic search, LLM-answered questions. Upload, delete, tag, and folder-assign global docs. |
| `pkb` | 16 | OFF | Personal Knowledge Base operations. Search claims (hybrid/FTS/embedding), resolve `@`-references, get/add/edit/delete/pin claims, autocomplete, NL command agent, interactive memory proposals, list contexts/entities/tags. |
| `memory` | 7 | OFF | Conversation memory access. Memory pad read/write, conversation history, user detail/preferences, raw message retrieval. |
| `code_runner` | 1 | OFF | Run Python code in the project's conda environment. Default 30s timeout; LLM can specify custom timeout_seconds for longer tasks. Sandboxed. |
| `artefacts` | 8 | OFF | Conversation artefact (file) management. List, create, get, update, delete artefacts. LLM-powered propose/apply edits. |
| `prompts` | 5 | OFF | Saved prompts and LLM actions. List, get, create, update prompts. Run ephemeral LLM actions (explain, critique, expand, ELI5). |
| `conversation` | 5 | OFF | Search, list, and read individual messages. Get conversation overview and memory pad. BM25 keyword search + text/regex matching. |
| `cross_conversation` | 3+4 | OFF | Cross-conversation search/list/summary (3 tools) + tool call history (4 tools: list/get for search history, list/get for all tool history). |
| `aggregator` | 4 | OFF | Delegate sub-tasks to an autonomous agent. `delegate_task` (blocking), `delegate_task_background` (fires sub-agent in a daemon thread, returns task_id immediately so the main LLM can continue), `get_task_result` (polls by task_id), `list_background_tasks` (enumerate all tasks). 3 profiles: research, documents, general. |
| `coding` | 12 | OFF | File system navigation, PDF reading (with page selection), image analysis via vision LLM, LLM-agent file structure/summary, todo list management. `fs_read_file` now handles PDFs and images. Dedicated `fs_read_pdf` with page selection + truncation flag. `fs_get_file_structure_and_summary` is a tool-calling agent loop (up to 5 sub-calls). All paths sandboxed to project root. |
| `general` | 2 | OFF | Image generation and audio transcription. `generate_image`, `transcribe_audio`. |

Categories default to OFF for write-capable or resource-intensive tools (PKB, memory, code_runner, artefacts, prompts) and ON for read-only information retrieval (clarification, search, documents).

### How It Works (User Perspective)

**Flow 1 -- Tool-based clarification**:
User sends "Help me write a business plan" with tools enabled. The LLM invokes `ask_clarification` with questions like "What industry?" and "What stage is your business?". A modal appears with MCQ radio buttons. User selects answers and clicks Submit. The LLM receives the answers and continues generating a tailored business plan -- all in one turn, no re-send needed.

**Flow 2 -- Autonomous web search**:
User asks "What are the latest developments in quantum computing?". The LLM invokes `web_search` with a relevant query. An inline status pill shows "Searching the web..." briefly. Results are fed back to the LLM, which synthesizes them into a current, cited response.

**Flow 3 -- Multi-step tool chain**:
The LLM calls `web_search`, reviews results, then calls `ask_clarification` to narrow the topic, then calls `document_lookup` to cross-reference with uploaded docs. Each tool invocation shows a brief status indicator. The final response integrates all gathered information.

**Flow 4 -- Tools disabled**:
User has the master toggle OFF. The LLM responds with plain text only. If it would have asked clarifying questions, it writes them inline as text (existing behavior). No tool infrastructure is loaded.

**Flow 5 -- Interactive tool timeout**:
User doesn't respond to a clarification modal within 60 seconds. The LLM receives a "User did not respond within the timeout period" message and continues generating a best-effort response.

### Controls and Safety

| Control | Value | Description |
|---|---|---|
| Master toggle | `checkboxes.enable_tool_use` | Gates all tool functionality. OFF = zero overhead. |
| Per-tool selector | `checkboxes.enabled_tools` | Array of enabled tool name strings. Sent as `["ask_clarification", "web_search", ...]`. Legacy dict format `{category: bool}` also accepted for backward compatibility. |
| Iteration cap | 5 | Hard maximum tool-call rounds per turn. On the final iteration, `tool_choice="none"` forces a text-only response. |
| Interactive timeout | 60 seconds | `threading.Event.wait(timeout=60)`. Unblocks with timeout message if user doesn't respond. |
| Result truncation | 50000 characters | `TOOL_RESULT_TRUNCATION_LIMIT` in `code_common/tools.py`. Oversized results are truncated with `"\n... [truncated, result too long]"` suffix. |
| Fail-open execution | Always | `ToolRegistry.execute()` catches all exceptions. Tool errors produce an error message fed back to the LLM, never crash the response. |
| Backward compatibility | Full | When `tools=None` (default), the entire call stack is unchanged. No overhead for non-tool conversations. |

## Architecture

### Call Stack

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
        -> Iteration 1..5:
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

### Key Backend Functions

**`Conversation._get_enabled_tools(checkboxes)`** (`Conversation.py`):
Reads `checkboxes.enable_tool_use` (master toggle) and `checkboxes.enabled_tools`. Supports two input formats:
- **New format** (array): `enabled_tools` is a list of tool name strings, e.g. `["ask_clarification", "web_search", "perplexity_search"]`. Used directly as the enabled tool names.
- **Legacy format** (dict): `enabled_tools` is a dict of category booleans, e.g. `{"clarification": true, "search": true, "pkb": false}`. Maps categories to tool names via `TOOL_REGISTRY.get_tools_by_category()`.
- **Fallback**: If `enabled_tools` is `None` or missing but master toggle is ON, enables all tools.
Returns `TOOL_REGISTRY.get_openai_tools_param(enabled_names)` or `None`.

**`Conversation._run_tool_loop(...)`** (`Conversation.py`):
Generator method implementing the agentic loop. Accepts `tool_response_waiter` callable (defaults to `wait_for_tool_response` from endpoints) for interactive tool synchronization. Yields streaming dict chunks to the response generator.

**`_extract_text_from_openai_response(response)`** (`code_common/call_llm.py`):
Parses OpenAI streaming chunks. Maintains `pending_tool_calls` dict keyed by index. Yields `str` for text content and `dict` for completed tool calls (when `finish_reason == "tool_calls"`). Tool call dict shape: `{"type": "tool_call", "id": str, "function": {"name": str, "arguments": str}}`.

**`call_chat_model(..., tools=None, tool_choice=None)`** (`code_common/call_llm.py`):
Core API call function. When `tools` is provided, adds `tools` and `tool_choice` to the `client.chat.completions.create()` kwargs. Supports two modes: simple (text + system) and messages (pre-built messages array for continuation calls).

**`call_llm(..., tools=None, tool_choice=None)`** (`code_common/call_llm.py`):
High-level wrapper. Threads `tools` and `tool_choice` through to `call_chat_model()`. When streaming with tools, the generator may yield both `str` and `dict` items.

### Streaming Protocol

The existing streaming protocol uses newline-delimited JSON lines. Tool calling extends this with new event types.

**Existing events** (unchanged):
```json
{"text": "...", "status": "..."}
{"message_ids": {"assistant_message_id": "...", "user_message_id": "..."}}
```

**New tool-calling events**:

| Event Type | Fields | When Sent |
|---|---|---|
| `tool_call` | `type`, `tool_id`, `tool_name`, `tool_input` | LLM requests a tool invocation |
| `tool_status` | `type`, `tool_id`, `tool_status` | Tool execution state changes (`executing`, `waiting_for_user`, `completed`) |
| `tool_input_request` | `type`, `tool_id`, `tool_name`, `ui_schema` | Interactive tool needs user input (triggers modal) |
| `tool_result` | `type`, `tool_id`, `tool_name`, `result_summary`, `duration_seconds` | Tool execution completed, brief summary with execution time |

**Example event sequence for interactive tool**:
```
{"text": "Let me ask you some questions to better understand your needs."}
{"type": "tool_call", "tool_id": "call_abc123", "tool_name": "ask_clarification", "tool_input": {"questions": [...]}}
{"type": "tool_status", "tool_id": "call_abc123", "tool_status": "executing"}
{"type": "tool_status", "tool_id": "call_abc123", "tool_status": "waiting_for_user"}
{"type": "tool_input_request", "tool_id": "call_abc123", "tool_name": "ask_clarification", "ui_schema": {"questions": [{"question": "What industry?", "options": ["Tech", "Finance", "Healthcare", "Other"]}]}}
  ... user submits response via modal ...
{"type": "tool_status", "tool_id": "call_abc123", "tool_status": "completed"}
{"type": "tool_result", "tool_id": "call_abc123", "tool_name": "ask_clarification", "result_summary": "User answered 2 clarification questions", "duration_seconds": 12.3}
{"text": "Based on your answers, here is a tailored business plan for the tech industry..."}
```

**Example event sequence for server-side tool**:
```
{"type": "tool_call", "tool_id": "call_xyz789", "tool_name": "web_search", "tool_input": {"query": "quantum computing 2026"}}
{"type": "tool_status", "tool_id": "call_xyz789", "tool_status": "executing"}
{"type": "tool_status", "tool_id": "call_xyz789", "tool_status": "completed"}
{"type": "tool_result", "tool_id": "call_xyz789", "tool_name": "web_search", "result_summary": "Found 5 search results", "duration_seconds": 3.5}
{"text": "Here are the latest developments in quantum computing..."}
```

### Thread Synchronization (Interactive Tools)

Interactive tools (currently only `ask_clarification`) require pausing the background streaming thread to wait for user input. This uses Python's `threading.Event` mechanism:

**Server-side state** (`endpoints/conversations.py`):
```python
_tool_response_events = {}   # {tool_id: threading.Event}
_tool_response_data = {}     # {tool_id: dict}
_tool_response_lock = threading.Lock()
```

**Synchronization flow**:
1. `_run_tool_loop()` executes interactive tool, gets `ToolCallResult` with `needs_user_input=True`.
2. Loop yields `tool_input_request` event to the streaming response.
3. Loop calls `wait_for_tool_response(tool_id, timeout=60)`.
4. `wait_for_tool_response()` creates a `threading.Event`, stores it in `_tool_response_events[tool_id]`, and calls `event.wait(timeout=60)`.
5. UI renders modal. User fills in answers and clicks Submit.
6. UI POSTs to `POST /tool_response/<conversation_id>/<tool_id>` with `{"response": {...}}`.
7. `submit_tool_response()` acquires `_tool_response_lock`, stores response in `_tool_response_data[tool_id]`, calls `event.set()`.
8. `wait_for_tool_response()` unblocks, returns the response dict.
9. `_run_tool_loop()` formats the response as a tool result message and continues the loop.
10. On timeout (60s): `event.wait()` returns `False`, function returns `None`, loop feeds "User did not respond" to LLM.

### Tool Call Timing

Every tool call is timed end-to-end by `_run_tool_loop()` in `Conversation.py`. Two durations are tracked:

- **`tool_exec_duration`**: Wall-clock time for `TOOL_REGISTRY.execute()` only (server-side handler execution).
- **`tool_total_duration`**: Includes exec time plus any user-wait time for interactive tools (same as exec for server-side tools).

Timing appears in four places:

1. **`tool_result` streaming event**: New `duration_seconds` field (float, rounded to 2 decimal places) sent to the UI alongside `result_summary`.
2. **Inline status pill (UI)**: `ToolCallManager.showToolResult()` appends `(Xs)` to the result summary text displayed in the pill.
3. **Collapsible `<tool_calls_summary>` block**: Each tool line shows `(N chars, Xs)` instead of just `(N chars)`.
4. **`time_dict` (end-of-message YAML)**: New `tool_calls` key contains a list of `{name, duration_s, result_chars}` dicts. These appear in the "Time taken to reply for chatbot" collapsible at the end of the message.

Example `time_dict` entry:
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

### Tool Registry

The tool registry (`code_common/tools.py`) is the central mechanism for defining, storing, and executing tools.

**Core classes**:

`ToolContext` -- context passed to every tool handler:
- `conversation_id: str` -- current conversation ID
- `user_email: str` -- authenticated user email
- `keys: dict` -- API keys and credentials
- `conversation_summary: str` -- short conversation summary
- `recent_messages: list` -- last N messages

`ToolCallResult` -- returned by every tool handler:
- `tool_id: str` -- tool call ID from API response
- `tool_name: str` -- name of invoked tool
- `result: str` -- result text fed back to LLM
- `error: Optional[str]` -- error message if failed
- `needs_user_input: bool` -- True to pause for user input
- `ui_schema: Optional[dict]` -- payload for UI rendering

`ToolDefinition` -- a registered tool:
- `name: str` -- machine-readable name (e.g. `"web_search"`)
- `description: str` -- human-readable description for OpenAI API
- `parameters: dict` -- JSON Schema for accepted parameters
- `handler: Callable` -- function invoked on tool call
- `is_interactive: bool` -- True for tools requiring user input
- `category: str` -- grouping category for UI settings

`ToolRegistry` -- manages all tool definitions:
- `register(tool_def)` -- register a tool (overwrites if name exists)
- `get_tool(name)` -- lookup by name
- `get_all_tools()` -- all registered tools
- `get_tools_by_category(category)` -- filter by category
- `get_openai_tools_param(enabled_names)` -- convert to OpenAI API `tools` format
- `execute(name, args, context, tool_call_id)` -- execute handler (fail-open, never raises)

**Singleton**: `TOOL_REGISTRY = ToolRegistry()` -- global instance, imported by `Conversation.py` and `call_llm.py`.

**`@register_tool` decorator**: Convenience decorator that creates a `ToolDefinition` and registers it with `TOOL_REGISTRY` at import time.

### Frontend Architecture

**`ToolCallManager`** (`interface/tool-call-manager.js`) -- singleton object managing all tool call UI:

Key properties:
- `activeToolCalls: {}` -- tracks active tool calls `{toolId: {toolName, status}}`
- `currentModalToolId: null` -- currently displayed modal tool_id
- `_currentConversationId: null` -- conversation ID for current stream
- `_submitting: false` -- submit-in-flight guard

Key methods:
- `showToolCallStatus(toolId, toolName, status)` -- inline status pill (spinner during execution, auto-fade on completion)
- `handleToolInputRequest(conversationId, toolId, toolName, uiSchema)` -- renders modal for interactive tools
- `showToolResult(toolId, resultSummary)` -- inline completion indicator
- `submitToolResponse(conversationId, toolId, responseData)` -- POSTs to `/tool_response/{conv_id}/{tool_id}`
- `_renderClarificationQuestions($modalBody, questions)` -- MCQ radio button form
- `_collectClarificationAnswers()` -- collects selected answers from form
- `setupEventHandlers()` -- wires modal submit/skip buttons
- `reset()` -- clears state on new conversation

**Stream handler integration** (`interface/common-chat.js`):
`renderStreamingResponse()` is extended to detect tool event types in JSON-line chunks and dispatch to `ToolCallManager` methods.

**Settings UI** (`interface/interface.html` + `interface/chat.js`):
Master toggle checkbox (`#settings-enable_tool_use`) controls visibility of the tool selector. When enabled, a Bootstrap Select multi-select dropdown (`#settings-tool-selector`) appears with 13 `<optgroup>` categories and 87 individual tool `<option>` elements. The dropdown supports:
- `data-live-search="true"` -- type-ahead search filtering
- `data-actions-box="true"` -- Select All / Deselect All buttons
- `data-selected-text-format="count > 3"` -- shows count when >3 tools selected
- `data-count-selected-text="{0} tools selected"` -- count label format

Bootstrap Select 1.13.18 CDN is loaded in interface.html (CSS + JS). All selectpicker interactions are guarded with `typeof $.fn.selectpicker !== 'undefined'` checks.

Settings persistence reads selected tool names via `getSelectPickerValue('#settings-tool-selector', [])` and restores them via `$('#settings-tool-selector').val(names)` + `selectpicker('refresh')`. The `setModalFromState()` function handles both new array format and legacy dict format (converts categories to tool name arrays using a `categoryDefaults` mapping).

**Modal** (`interface/interface.html`):
`#tool-call-modal` -- Bootstrap 4.6 modal for interactive tool input. Rendered dynamically by `ToolCallManager.handleToolInputRequest()`.

**Service worker** (`interface/service-worker.js`):
`tool-call-manager.js` added to the precache file list.

## API Reference

### Endpoints

**`POST /tool_response/<conversation_id>/<tool_id>`** (`endpoints/conversations.py`)

Submit user response for an interactive tool call.

Request body:
```json
{
  "response": {
    "answers": [
      {"question": "What industry?", "selected_option": "Tech"},
      {"question": "What stage?", "selected_option": "Early-stage startup"}
    ]
  }
}
```

Responses:
- `200 {"status": "ok"}` -- response received, background thread unblocked
- `400 {"error": "Missing 'response' field"}` -- malformed request
- `404 {"error": "No pending tool request for tool_id: ..."}` -- no waiting thread for this tool_id

### Settings Payload

Tool settings are sent as part of the `checkboxes` object in the `/reply` request.

**New format** (per-tool selection via Bootstrap Select dropdown):
```json
{
  "checkboxes": {
    "enable_tool_use": true,
    "enabled_tools": [
      "ask_clarification",
      "web_search", "perplexity_search", "jina_search", "jina_read_page", "read_link",
      "document_lookup", "docs_list_conversation_docs", "docs_list_global_docs", "docs_query",
      "docs_get_full_text", "docs_get_info", "docs_answer_question",
      "docs_get_global_doc_info", "docs_query_global_doc", "docs_get_global_doc_full_text"
    ]
  }
}
```

**Legacy format** (per-category booleans, still supported for backward compatibility):
```json
{
  "checkboxes": {
    "enable_tool_use": true,
    "enabled_tools": {
      "clarification": true,
      "search": true,
      "documents": true,
      "pkb": false,
      "memory": false,
      "code_runner": false,
      "artefacts": false,
      "prompts": false
    }
  }
}
```

The backend (`_get_enabled_tools()`) auto-detects the format: if `enabled_tools` is a list, it uses tool names directly; if a dict, it maps categories to tools.

### JSON-Line Event Types

| Event Type | Key Fields | Description |
|---|---|---|
| `tool_call` | `type`, `tool_id`, `tool_name`, `tool_input` | LLM requested a tool invocation. `tool_input` is the parsed arguments dict. |
| `tool_status` | `type`, `tool_id`, `tool_status` | Execution state change. Values: `"executing"`, `"waiting_for_user"`, `"completed"`, `"error"`. |
| `tool_input_request` | `type`, `tool_id`, `tool_name`, `ui_schema` | Interactive tool needs user input. `ui_schema` contains the form definition. |
| `tool_result` | `type`, `tool_id`, `result_summary` | Tool completed. `result_summary` is a brief human-readable summary. |

## Developer Guide: Adding New Tools

This section covers everything needed to add a new tool to the framework. A developer should be able to follow these steps without reading any other documentation.

### Step 1: Define the tool with `@register_tool`

Open `code_common/tools.py` and add a new decorated function. The decorator registers the tool with `TOOL_REGISTRY` at import time.

```python
@register_tool(
    name="my_new_tool",
    description=(
        "Brief description of what this tool does. "
        "Include guidance on WHEN the LLM should use it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    is_interactive=False,       # True only if tool pauses for user input
    category="search",          # Must match an existing category or add a new one
)
def handle_my_new_tool(args: dict, context: ToolContext) -> ToolCallResult:
    """Handle the my_new_tool tool call.

    Parameters
    ----------
    args:
        Parsed arguments from the LLM. Contains 'query' (required)
        and 'max_results' (optional, default 5).
    context:
        Tool execution context with conversation_id, user_email, keys.

    Returns
    -------
    ToolCallResult
        Result text to feed back to the LLM.
    """
    query = args.get("query", "")
    max_results = args.get("max_results", 5)

    # --- Your tool logic here ---
    # Use context.keys for API credentials
    # Use context.conversation_id for conversation-scoped operations
    # Use context.user_email for user-scoped operations
    result_text = f"Found {max_results} results for: {query}"

    return ToolCallResult(
        tool_id="",          # Filled in by ToolRegistry.execute()
        tool_name="my_new_tool",
        result=result_text,  # This text is sent back to the LLM as a tool message
    )
```

**Key rules for tool definitions**:
- `name` must be unique across all tools
- `description` should tell the LLM WHEN to use the tool, not just what it does
- `parameters` must be a valid JSON Schema object
- Handler must return `ToolCallResult` (or the registry wraps the return value)
- Handler must never raise -- catch exceptions internally and return error in `ToolCallResult.error`
- Results are auto-truncated to 50000 characters by `_truncate_result()` (configurable via `TOOL_RESULT_TRUNCATION_LIMIT`)

### Step 2: Implement the handler logic

For **server-side tools** (most tools): implement the logic directly in the handler function. Use `context.keys` for API credentials, `context.conversation_id` and `context.user_email` for scoped operations.

For **interactive tools** (tools that need user input): return `ToolCallResult` with `needs_user_input=True` and `ui_schema` containing the form definition. The agentic loop will pause, the UI will render a modal, and the user's response will be fed back as the tool result.

```python
# Interactive tool example
return ToolCallResult(
    tool_id="",
    tool_name="my_interactive_tool",
    result="Waiting for user input.",
    needs_user_input=True,
    ui_schema={
        "prompt": "Please provide additional details:",
        "fields": [{"name": "detail", "type": "textarea"}],
    },
)
```

For interactive tools, you also need to add rendering logic in `ToolCallManager.handleToolInputRequest()` in `interface/tool-call-manager.js` to handle your `ui_schema` format.

### Step 3: Add UI toggle (if adding a new category)

If your tool belongs to an existing category, no UI changes are needed -- it will automatically appear in the dropdown under that category's optgroup when registered via `@register_tool`.

If you are adding a **new category**:

1. **HTML** (`interface/interface.html`): Add a new `<optgroup>` inside the `#settings-tool-selector` select element:
   ```html
   <optgroup label="My Category">
       <option value="my_new_tool">My New Tool</option>
   </optgroup>
   ```

2. **JavaScript** (`interface/chat.js`): Add the new category to the `categoryDefaults` mapping in `setModalFromState()` for legacy format backward compatibility:
   ```javascript
   my_category: ['my_new_tool']
   ```

3. **Backend** (`Conversation.py`): Add the category to the legacy mapping in `_get_enabled_tools()` so dict-format payloads are recognized:
   ```python
   "my_category": enabled_tools_config.get("my_category", False),
   ```
   Note: For the new list format, no backend changes are needed -- the tool name in the list is matched directly.

### Step 4: Test

Manual testing checklist:

1. **Tool appears in API**: Enable the tool's category, send a message, verify the tool appears in the `tools` parameter of the OpenAI API call (check server logs at DEBUG level).
2. **LLM invokes tool**: Craft a prompt that should trigger the tool (e.g. "Search the web for X" for a search tool). Verify the LLM returns a `tool_calls` response.
3. **Tool executes**: Verify the handler runs and returns a valid `ToolCallResult`. Check server logs for `"Executing tool: my_new_tool"` and `"Tool my_new_tool completed"`.
4. **Result fed back**: Verify the tool result appears in the messages array for the continuation call. The LLM should reference the tool's output in its response.
5. **Error handling**: Force an error in the handler. Verify the LLM receives an error message and responds gracefully (does not crash).
6. **Tools disabled**: Disable the category. Verify the tool does NOT appear in the API call.
7. **Interactive tools only**: Verify the modal appears, user can submit, response is received by the background thread, and the LLM continues.

## Files Modified and Created

| File | Type | Description |
|---|---|---|
| `code_common/tools.py` | **New** | Tool registry framework: `ToolRegistry`, `ToolDefinition`, `ToolContext`, `ToolCallResult`, `@register_tool` decorator, 87 tool definitions, `TOOL_REGISTRY` singleton |
| `code_common/call_llm.py` | Modified | Added `tools` and `tool_choice` parameters to `call_chat_model()` and `call_llm()`. Extended `_extract_text_from_openai_response()` to parse streaming `delta.tool_calls` and yield tool call dicts. |
| `call_llm.py` (project root) | Modified | Threaded `tools` and `tool_choice` through `CallLLm.__call__()` to the underlying `call_llm()` |
| `Conversation.py` | Modified | Added `_get_enabled_tools(checkboxes)`, `_run_tool_loop()` generator method, tool-aware branching in `reply()`, preamble injection for tool awareness, `search_messages()`, `list_messages()`, `read_message()`, `get_conversation_details()`, `_get_or_create_search_index()`, `_index_messages_for_search()`, `message_search_index` in `store_separate` |
| `endpoints/conversations.py` | Modified | Added `POST /tool_response/<conversation_id>/<tool_id>` endpoint, `wait_for_tool_response()` function, thread-safe response storage (`_tool_response_events`, `_tool_response_data`, `_tool_response_lock`). Added 5 conversation message tools (search, list, read, details, memory pad) |
| `interface/tool-call-manager.js` | **New** | `ToolCallManager` singleton: inline status indicators, interactive tool modal rendering, MCQ form, response submission, event handler wiring |
| `interface/interface.html` | Modified | Added Bootstrap Select 1.13.18 CDN (CSS + JS), master "Enable Tools" toggle, `<select multiple id="settings-tool-selector">` with 13 `<optgroup>` categories and 87 individual tool `<option>` elements, `#tool-call-modal` Bootstrap modal for interactive tools, CSS for dropdown max-height, Conversation optgroup (5 tools) |
| `interface/chat.js` | Modified | Settings persistence for `enable_tool_use` and `enabled_tools` (reads from selectpicker as array of tool names), `setModalFromState()` with dual-format support (new array + legacy dict via `categoryDefaults` mapping), selectpicker refresh on modal open, `conversation` category in `categoryDefaults` |
| `interface/common-chat.js` | Modified | Extended `renderStreamingResponse()` to detect and dispatch tool event types (`tool_call`, `tool_status`, `tool_input_request`, `tool_result`) to `ToolCallManager`. Added search-intent auto-detection: `WEB_SEARCH_TOOLS` constant, `SEARCH_INTENT_PATTERNS` (27 regex patterns), `detectSearchIntent()` and `mergeWebSearchTools()` functions, plus inline interception in `sendMessageCallback()` after `mergeOptions()`. |
| `interface/common.js` | Modified | `getOptions()` reads tool settings from `#settings-tool-selector` selectpicker via IIFE with fallback |
| `interface/service-worker.js` | Modified | Added `tool-call-manager.js` to precache file list |
| `code_common/conversation_search.py` | **New** | Shared tool metadata (CONVERSATION_TOOLS dict), markdown extraction (`extract_markdown_features`), BM25 message index (`MessageSearchIndex`), tokenization with unigram+bigram support |

## Tool Inventory (87 Tools)

### clarification (1 tool)

| Tool | Description | Interactive |
|---|---|---|
| `ask_clarification` | Ask user clarifying questions to better understand their request. Use when the user explicitly asks you to ask questions, or when you detect significant ambiguity. | Yes |

**Parameters** (`ask_clarification`): `questions` (required) -- array of objects, each with `question` (string) and `options` (array of 2-5 strings, MCQ choices).

### search (5 tools)

| Tool | Description | Interactive |
|---|---|---|
| `web_search` | Search the web for current information. Provide query and context for best results. Runs in headless mode with query bypass (see Note 12). | No |
| `perplexity_search` | Search using Perplexity AI for web information. Provide query and context for best results. Runs in headless mode with query bypass (see Note 12). | No |
| `jina_search` | Search using Jina AI with full web content retrieval. Provide query and context for best results. Runs in headless mode with query bypass (see Note 12). | No |
| `jina_read_page` | Read a web page using Jina Reader API, returns clean markdown. | No |
| `read_link` | Read any link (web page, PDF, image, YouTube) and return text content. | No |

**Key parameters**:
- `web_search`: `query` (required), `context` (string, default ""), `num_results` (int, default 5)
- `perplexity_search`: `query` (required), `context` (string, default ""), `detail_level` (int 1-4, default 1)
- `jina_search`: `query` (required), `context` (string, default ""), `detail_level` (int, default 1)
- `jina_read_page`: `url` (required)
- `read_link`: `url` (required), `context` (string, default "Read and extract all content"), `detailed` (bool, default false)

### documents (14 tools)

| Tool | Description | Interactive |
|---|---|---|
| `document_lookup` | Search user's uploaded or global documents for specific information. | No |
| `docs_list_conversation_docs` | List all documents attached to a conversation. Returns priority, priority_label, date_written, deprecated for each doc. | No |
| `docs_list_global_docs` | List all global documents for current user. Returns priority, priority_label, date_written, deprecated for each doc. | No |
| `docs_query` | Semantic search within a document by storage path. | No |
| `docs_get_full_text` | Retrieve full text content of a document by storage path. | No |
| `docs_get_info` | Get metadata about a document (including priority, date_written, deprecated) without retrieving full text. | No |
| `docs_answer_question` | Ask a question about a document and get LLM-generated answer. | No |
| `docs_get_global_doc_info` | Get metadata about a global document by doc_id (including priority, date_written, deprecated). | No |
| `docs_query_global_doc` | Semantic search within a global document by doc_id. | No |
| `docs_get_global_doc_full_text` | Retrieve full text content of a global document by doc_id. | No |
| `upload_global_doc` | Upload a local file as a global document. Reads the file from the server filesystem, indexes it, and registers it. Optionally attach tags. | No |
| `delete_global_doc` | Delete a global document by ID. Removes the database record (does not delete filesystem storage). | No |
| `set_global_doc_tags` | Set tags on a global document (replaces existing tags). Atomically replaces all tags with the provided list. | No |
| `assign_doc_to_folder` | Assign a global document to a folder, or move to Unfiled by passing empty folder_id. | No |

**Key parameters**:
- `document_lookup`: `query` (required), `doc_scope` (enum: "conversation"/"global"/"all", default "all")
- `docs_query` / `docs_query_global_doc`: `doc_storage_path` or `doc_id` (required), `query` (required), `token_limit` (int, default 4096)
- `docs_get_full_text` / `docs_get_global_doc_full_text`: `doc_storage_path` or `doc_id` (required), `token_limit` (int, default 16000)
- `docs_answer_question`: `doc_storage_path` (required), `question` (required)
- `upload_global_doc`: `file_path` (required), `tags` (array of strings, optional)
- `delete_global_doc`: `doc_id` (required)
- `set_global_doc_tags`: `doc_id` (required), `tags` (array of strings, required)
- `assign_doc_to_folder`: `doc_id` (required), `folder_id` (required, empty string for Unfiled)

### pkb (16 tools)

| Tool | Description | Interactive |
|---|---|---|
| `pkb_search` | Search user's PKB for relevant claims using hybrid search. | No |
| `pkb_get_claim` | Retrieve a single claim from PKB by claim ID. | No |
| `pkb_resolve_reference` | Resolve a PKB `@`-reference (friendly ID) to its full object(s). | No |
| `pkb_get_pinned_claims` | Retrieve user's pinned (high-priority) PKB claims. | No |
| `pkb_add_claim` | Add a new claim to the PKB (write operation). | No |
| `pkb_edit_claim` | Edit an existing claim in the PKB (write operation). | No |
| `pkb_get_claims_by_ids` | Retrieve multiple claims by their IDs in a single call. | No |
| `pkb_autocomplete` | Autocomplete PKB friendly IDs by prefix. | No |
| `pkb_resolve_context` | Resolve a context to its full claim tree. | No |
| `pkb_pin_claim` | Pin or unpin a claim for prominence (write operation). | No |
| `pkb_delete_claim` | Soft-delete (retract) a claim from the PKB. Marked as retracted and excluded from default search results. | No |
| `pkb_nl_command` | Process a natural language command against the PKB. Accepts free-form text and performs multi-step CRUD operations using an internal agentic LLM loop. | No |
| `pkb_propose_memory` | Propose memory entries (claims) to the user for review before saving. Shows a modal with pre-filled fields the user can edit and confirm. | Yes |
| `pkb_list_contexts` | List all PKB contexts for the user. Returns context_id, name, description, and claim_count. | No |
| `pkb_list_entities` | List all PKB entities for the user. Returns entity_id, entity_type, name, and metadata. | No |
| `pkb_list_tags` | List all PKB tags for the user. Returns tag_id, name, parent_tag_id, and metadata. | No |

**Key parameters**:
- `pkb_search`: `query` (required), `k` (int, default 20), `strategy` (enum: "hybrid"/"fts"/"embedding", default "hybrid")
- `pkb_add_claim`: `statement` (required), `claim_type` (required), `context_domain` (required), `tags` (array of strings)
- `pkb_edit_claim`: `claim_id` (required), `statement` (optional), `tags` (optional)
- `pkb_pin_claim`: `claim_id` (required), `pin` (bool, default true)
- `pkb_delete_claim`: `claim_id` (required)
- `pkb_nl_command`: `command` (required), `model` (optional, default openai/gpt-4o-mini)
- `pkb_propose_memory`: `claims` (required, array of objects with `text`, `claim_type`, optional `valid_from`/`valid_to`/`tags`/`entities`/`context`), `message` (optional)
- `pkb_list_contexts`: no required parameters
- `pkb_list_entities`: `entity_type` (optional filter), `limit` (int, default 100)
- `pkb_list_tags`: `limit` (int, default 100)

### memory (7 tools)

| Tool | Description | Interactive |
|---|---|---|
| `conv_get_memory_pad` | Get per-conversation memory pad (scratchpad). | No |
| `conv_set_memory_pad` | Set (overwrite) per-conversation memory pad (write operation). | No |
| `conv_get_history` | Get formatted conversation history (summary + recent messages). | No |
| `conv_get_user_detail` | Get user's persistent memory/bio. | No |
| `conv_get_user_preference` | Get user's stored preferences. | No |
| `conv_get_messages` | Get raw message list from a conversation. | No |
| `conv_set_user_detail` | Update user's persistent memory/bio (write operation). | No |

**Key parameters**:
- `conv_get_memory_pad` / `conv_set_memory_pad` / `conv_get_history` / `conv_get_messages`: `conversation_id` (required)
- `conv_set_memory_pad`: `conversation_id` (required), `text` (required)
- `conv_set_user_detail`: `text` (required)

### code_runner (1 tool)

| Tool | Description | Interactive |
|---|---|---|
| `run_python_code` | Run Python code in project's conda environment. Default 30s timeout; LLM specifies custom `timeout_seconds` (e.g. 60-120) for longer tasks. | No |

**Parameters**: `code_string` (required) -- the Python code to execute. `timeout_seconds` (optional, default 30) -- max seconds to run; LLM should set higher (e.g. 60-120) for data processing or heavy computation.

### artefacts (8 tools)

| Tool | Description | Interactive |
|---|---|---|
| `artefacts_list` | List all artefacts in a conversation. | No |
| `artefacts_create` | Create a new artefact file in conversation (write operation). | No |
| `artefacts_get` | Get artefact metadata, content, and file_path. | No |
| `artefacts_get_file_path` | Get absolute file path for an artefact. | No |
| `artefacts_update` | Update full content of an artefact (write operation). | No |
| `artefacts_delete` | Delete an artefact file and metadata (write operation). | No |
| `artefacts_propose_edits` | Propose LLM-generated edits to an artefact (advanced). | No |
| `artefacts_apply_edits` | Apply proposed edit operations to an artefact (advanced). | No |

**Key parameters**:
- `artefacts_create`: `conversation_id` (required), `name` (required), `file_type` (required), `initial_content` (string, default "")
- `artefacts_update`: `conversation_id` (required), `artefact_id` (required), `content` (required)
- `artefacts_propose_edits`: `conversation_id` (required), `artefact_id` (required), `instruction` (required), `selection_start_line` (optional), `selection_end_line` (optional)
- `artefacts_apply_edits`: `conversation_id` (required), `artefact_id` (required), `base_hash` (required), `ops` (array of objects, required)

### prompts (5 tools)

| Tool | Description | Interactive |
|---|---|---|
| `prompts_list` | List all saved prompts with metadata. | No |
| `prompts_get` | Get a specific prompt by name including content and metadata. | No |
| `temp_llm_action` | Run ephemeral LLM action on selected text (explain, critique, expand, ELI5). | No |
| `prompts_create` | Create a new prompt (write operation). | No |
| `prompts_update` | Update existing prompt's content and metadata (write operation). | No |

**Key parameters**:
- `prompts_get`: `name` (required)
- `temp_llm_action`: `action_type` (required, enum: "explain"/"critique"/"expand"/"eli5"/"ask_temp"), `selected_text` (required), `conversation_id` (optional), `user_message` (optional)
- `prompts_create` / `prompts_update`: `name` (required), `content` (required), `description` (optional), `category` (optional), `tags` (optional)

### conversation (5 tools)

| Tool | Description | Interactive |
|---|---|---|
| `search_messages` | Search within conversation messages using BM25 keyword or text/regex matching. | No |
| `list_messages` | List messages with 300-char preview and TLDR summary. | No |
| `read_message` | Read full message content by ID or index, with markdown features. | No |
| `get_conversation_details` | Get conversation overview: title, summary, message IDs, docs, artefacts. | No |
| `get_conversation_memory_pad` | Get the conversation's auto-updated memory pad of extracted facts. | No |

**Key parameters**:
- `search_messages`: `conversation_id` (required), `query` (required), `mode` (enum: "bm25"/"text", default "bm25"), `sender_filter` (enum: "user"/"model"), `top_k` (int, default 10), `min_length` (int), `max_length` (int)
- `list_messages`: `conversation_id` (required), `start` (int), `end` (int), `from_end` (bool, default false), `sender_filter` (enum: "user"/"model")
- `read_message`: `conversation_id` (required), `message_id` (string) OR `index` (int, supports negative)
- `get_conversation_details`: `conversation_id` (required)
- `get_conversation_memory_pad`: `conversation_id` (required)

### cross_conversation — Tool Call History (4 tools)

| Tool | Description | Interactive |
|---|---|---|
| `list_search_history` | List previous web searches and page reads with metadata (ID, tool, query, result size, timestamp). Use before making a new search to check for duplicates. | No |
| `get_search_results` | Get full result text of previous searches/page reads by ID list. Avoids re-executing expensive searches. | No |
| `list_tool_call_history` | List previous tool calls across ALL categories (search, documents, PKB, etc.) with metadata. | No |
| `get_tool_call_results` | Get full result text of any previous tool calls by ID list. | No |

**Key parameters**:
- `list_search_history`: `query_contains` (substring filter on args), `conversation_only` (bool, default false), `limit` (int, default 20, max 100), `since_hours` (number)
- `get_search_results`: `ids` (required, array of strings, 1-10 IDs from list_search_history)
- `list_tool_call_history`: `tool_name_filter` (exact tool name), `tool_category_filter` (category string), `conversation_only` (bool), `limit` (int, default 20), `since_hours` (number)
- `get_tool_call_results`: `ids` (required, array of strings, 1-10 IDs from list_tool_call_history)


### aggregator (4 tools)

| Tool | Description | Interactive |
|---|---|---|
| `delegate_task` | Delegate a sub-task to an autonomous agent (blocking). Runs a full tool loop (up to 5 iterations) and returns a synthesised answer. 3 profiles: `research`, `documents`, `general`. | No |
| `delegate_task_background` | Fire-and-forget version. Starts the sub-agent in a daemon thread and returns a `task_id` immediately so the main LLM can continue working in parallel. | No |
| `get_task_result` | Poll for the result of a background task by `task_id`. Returns `{"status": "running"|"done"|"error", "result": "..."}`. | No |
| `list_background_tasks` | List all background tasks (running and completed) in this server session. Returns task_id, status, age, and result preview. Expired tasks (>30 min) are pruned during this call. | No |

**Key parameters**:
- `delegate_task`: `prompt` (required), `profile` (required, enum: `"research"`/`"documents"`/`"general"`)
- `delegate_task_background`: same params — returns `{"task_id": "<uuid>", "status": "running"}` immediately
- `get_task_result`: `task_id` (required)
- `list_background_tasks`: `status_filter` (enum: "all"/"running"/"done"/"error", default "all")

**Background execution**: Tasks in `_BACKGROUND_TASKS` dict in `code_common/agent_tool.py`, keyed by UUID4. Daemon thread runs `run_agent_loop()`, writes result on completion. Tasks expire after 30 min. The `general` profile includes `delegate_task_background`.

**Synchronous notes** (for `delegate_task`): `run_agent_loop()` is a plain blocking function. Calls `call_llm(stream=False)`, executes tool calls via `TOOL_REGISTRY.execute()`. 1-level recursion guard (stripped at depth ≥ 2). Default model: `openai/gpt-4o-mini`. 5-min wall-clock timeout.

**Plan reference**: `documentation/planning/plans/agent_delegate_task.plan.md`

### general (2 tools)

| Tool | Description | Interactive |
|---|---|---|
| `generate_image` | Generate an image from a text prompt. Optionally accepts a base64 input image for editing/transformation. | No |
| `transcribe_audio` | Transcribe an audio file to text. Reads the audio file from the server filesystem and returns transcribed text using OpenAI or AssemblyAI. | No |

**Key parameters**:
- `generate_image`: `prompt` (required), `base64_input` (optional, base64 data URI of existing image to edit)
- `transcribe_audio`: `audio_file_path` (required)

### coding (12 tools)

| Tool | Description | Interactive |
|---|---|---|
| `fs_read_file` | Read file contents. Text: numbered lines with optional line range. PDF: page-separated text (pdfplumber). Image: vision LLM produces OCR + Scene + Objects + Summary. | No |
| `fs_write_file` | Write (create or overwrite) a file within the project directory. Creates parent directories as needed. | No |
| `fs_list_dir` | List entries in a project directory: name, type, size, last-modified. | No |
| `fs_find_files` | Find files matching a glob pattern under a base directory (recursive). Returns paths relative to project root. | No |
| `fs_grep` | Search file contents by regular expression. Returns matching lines with file and line number. | No |
| `fs_file_info` | Get metadata (exists, type, size, modified) for a path. Useful for existence checks before reading/writing. | No |
| `todo_write` | Write/replace a structured todo list (global or per-conversation). Each task: content, status, priority. | No |
| `todo_read` | Read the current todo list (global or per-conversation). Returns JSON array of task objects. | No |
| `fs_read_pdf` | Dedicated PDF reader with page selection (int, `'1-5'` range, `'1,3,5'` list, or array). Metadata header reports pages read, total, and truncation flag. | No |
| `fs_get_file_structure_and_summary` | LLM agent loop (up to 5 sub-calls) to produce STRUCTURE outline + 2-3 paragraph SUMMARY. Autonomously picks strategy per file type. For images: single vision call. | No |
| `fs_patch_file` | Replace a line range with new content. Write operation. | No |
| `fs_bash` | Run a bash command in the project root. 300s timeout. Write-capable. | No |

**Key parameters**:
- `fs_read_file`: `path` (required), `start_line` (int, default 1), `end_line` (int, default 0 = end). Ignored for PDFs and images.
- `fs_read_pdf`: `path` (required), `pages` (optional — int, string `'1-5'`/`'1,3,5'`, or int array)
- `fs_get_file_structure_and_summary`: `path` (required)
- `fs_write_file`: `path` (required), `content` (required)
- `fs_patch_file`: `path` (required), `start_line` (required), `end_line` (required), `new_content` (required)
- `fs_bash`: `command` (required), `timeout_seconds` (optional, default 30)
- `fs_list_dir`: `path` (string, default ".")
- `fs_find_files`: `pattern` (required), `base_path` (string, default "."), `max_results` (int, default 100)
- `fs_grep`: `pattern` (required, Python regex), `path` (default "."), `include_glob` (default "*"), `case_sensitive` (bool, default true), `max_results` (int, default 100)
- `fs_file_info`: `path` (required)
- `todo_write`: `todos` (required, JSON string array), `scope` (enum: "global"/"conversation", default "global"), `conversation_id` (required when scope="conversation")
- `todo_read`: `scope` (default "global"), `conversation_id` (required when scope="conversation")

**Safety**: All file system tools enforce path-traversal protection — any path that resolves outside `os.getcwd()` (the project root) is rejected with an error. File operations cannot escape the project directory.

**Todo storage**: Global todos → `storage/todo.json`. Conversation todos → `storage/conversations/{conv_id}/todo.json`. Task objects support arbitrary fields; recommended schema: `{id, content, status, priority}`. IDs are auto-assigned (1-based) if missing.

**MCP server**: `mcp_server/coding_tools.py` — port 8108. All 12 coding tools available via MCP including `fs_read_pdf`, `fs_get_file_structure_and_summary`, and image/PDF branches of `fs_read_file`. Entry in `opencode.json` as `coding-tools`.

**`fs_get_file_structure_and_summary` agent design**: Uses `TOOL_REGISTRY.get_openai_tools_param()` to give the LLM real OpenAI-format schemas for 5 tools (`fs_read_file`, `fs_read_pdf`, `fs_grep`, `fs_list_dir`, `fs_bash`). Calls `call_llm(stream=True, tools=[...], messages=[...])`, collects text chunks and tool-call dicts from the generator, executes via `TOOL_REGISTRY.execute()`, appends results to message history, loops back. On max tool calls: removes tools and nudges LLM to produce `STRUCTURE:` / `SUMMARY:` free text.

**Image support** (`_FS_IMAGE_EXTENSIONS`): `.jpg/.jpeg/.png/.gif/.webp/.bmp/.tiff/.tif`. `_fs_describe_image()` calls `call_llm(..., images=[abs_path])` with `VERY_CHEAP_LLM[0]` = `google/gemini-3.1-flash-lite-preview` (confirmed vision-capable in `VISION_CAPABLE_MODELS`). Returns four sections: **OCR**, **Scene Description**, **Objects & Elements**, **Summary**.
## Implementation Notes

1. **Coexistence with `/clarify`**: The tool-based `ask_clarification` and the existing `/clarify` slash command + auto-clarify checkbox are independent systems. `/clarify` is a pre-send mechanism (intercepts before the message reaches the LLM). Tool-based clarification is mid-response (LLM decides to ask). Both can be active simultaneously without conflict.

2. **Model compatibility**: Tool calling uses the OpenAI-native `tools` parameter via OpenRouter. Not all models support tool calling. If a model does not support tools, the `tools` parameter should be omitted (the master toggle should be OFF, or the backend should validate model capability).

3. **Messages mode for continuation**: After the first LLM call in the tool loop, continuation calls use the `messages` parameter (pre-built messages array) rather than `text`/`system` parameters. This preserves the full conversation context including tool call/result pairs.

4. **Tool choice on final iteration**: On the last allowed iteration (iteration 5), `tool_choice="none"` is passed to force the LLM to produce a text-only response, preventing infinite tool loops.

5. **Write operations**: Tools marked as write operations (PKB add/edit/pin, memory pad set, artefact create/update/delete, prompt create/update) modify persistent state. Their categories default to OFF to prevent unintended writes.

6. **Result truncation**: All tool results are passed through `_truncate_result()` which caps at `TOOL_RESULT_TRUNCATION_LIMIT = 50000` characters (defined in `code_common/tools.py`). The suffix length is now computed dynamically (`max_len - len(suffix)`), so the truncated output is exactly `max_len` characters. Truncation is applied in two places: (a) most handlers call `_truncate_result()` on their result text before returning, and (b) `ToolRegistry.execute()` calls it again as a safety net. The double application is idempotent. Previously the limit was 4000 characters with a suffix math bug that produced 4003-char outputs; both issues are now fixed.

7. **Fail-open design**: `ToolRegistry.execute()` wraps all handler calls in try/except. On any exception, it returns a `ToolCallResult` with the error message. The LLM receives the error and can decide how to proceed (retry, skip, or inform the user). The streaming response never crashes due to a tool error.

8. **Thread safety**: The tool response synchronization uses `threading.Lock` for the shared `_tool_response_events` and `_tool_response_data` dicts, and `threading.Event` for blocking/unblocking. Each tool call gets its own Event instance.

9. **Service worker cache**: When modifying `tool-call-manager.js`, bump both `CACHE_VERSION` in `service-worker.js` and the `?v=N` query parameter in the script tag in `interface.html`.

10. **Handler implementation status**: All 87 tool handlers have real implementations wired to the underlying business logic. No stubs remain. The handlers mirror the exact logic from the MCP server modules (`mcp_server/docs.py`, `mcp_server/pkb.py`, `mcp_server/conversation.py`, `mcp_server/code_runner_mcp.py`, `mcp_server/artefacts.py`, `mcp_server/prompts_actions.py`) and call the same underlying functions (e.g. `DocIndex.semantic_search_document()`, `StructuredAPI.for_user().search()`, `Conversation.list_artefacts()`) directly without going through MCP transport. Helper functions per category (e.g. `_docs_load_doc_index()`, `_get_pkb_api()`, `_conv_load()`, `_art_load_conversation()`, `_get_prompt_manager()`) are defined inline in `code_common/tools.py` before each category's tool registrations.

11. **HTTP-delegated tools**: Two artefact tools (`artefacts_propose_edits`, `artefacts_apply_edits`) and one prompt tool (`temp_llm_action`) delegate to Flask HTTP endpoints rather than calling business logic directly. This is because these operations involve complex LLM streaming or optimistic concurrency that is already implemented in the Flask endpoints.

12. **Headless mode and query bypass for search tools**: All search tool handlers (`web_search`, `perplexity_search`, `jina_search`) run their underlying agents in **headless mode** (`headless=True`). In headless mode, the agent skips the combiner LLM step and returns raw search results directly. Additionally, the tool handlers pre-format the `query` and `context` parameters as a Python code block containing a list of `(query, context)` tuples. This format is recognized by the agent's `extract_queries_contexts()` method (in `WebSearchWithAgent.__call__`), which parses the code block directly and bypasses the internal LLM query-generation step. This is important because the calling LLM has already crafted a good query — there is no need for a second LLM call inside the agent to re-generate queries. The same pattern is used in the MCP server tools (`mcp_server/mcp_app.py`). When adding a new search tool, follow this pattern: accept a `context` parameter, format as `"```python\n[({repr(query)}, {repr(context)})]\n```"`, and pass the formatted string to the agent.

13. **`deep_search` removed from MCP server**: The `InterleavedWebSearchAgent` (multi-hop iterative search) was removed from the MCP server. It remains available via the main chat UI (`Conversation.py`) and the extension server (`extension_server.py`) where the streaming multi-step search→answer loop is rendered progressively, but is not exposed as an MCP tool or tool-calling framework tool.

14. **MCP server search tool alignment**: The MCP server tools in `mcp_server/mcp_app.py` for `perplexity_search` and `jina_search` follow the same patterns as the tool-calling handlers: accept a `context` parameter, pre-format query+context as a Python code block for `extract_queries_contexts()` bypass, and run in headless mode. All MCP search tools operate headless (no combiner LLM, raw results returned to the MCP client).

15. **Default tool enablement**: Tool use is enabled by default for new sessions. `computeDefaultStateForTab()` in `chat.js` sets `enable_tool_use: true` and `enabled_tools: ['ask_clarification']`. `resetSettingsToDefaults()` also enables tool use and selects `ask_clarification`. The HTML dropdown has `<option value="ask_clarification" selected>` as the only pre-selected tool. The backend already defaults `clarification: True` in `_get_enabled_tools()`. This means every new conversation starts with the LLM able to ask clarifying questions via the `ask_clarification` tool without the user needing to configure anything.

16. **Search-intent auto-detection**: The frontend automatically injects web search tools when the user's message contains search-intent keywords. This is implemented entirely in `interface/common-chat.js` with three components:
    - **`WEB_SEARCH_TOOLS`**: constant array of the 5 search tool names (`web_search`, `perplexity_search`, `jina_search`, `jina_read_page`, `read_link`).
    - **`SEARCH_INTENT_PATTERNS`**: array of 27 regex patterns organized by category (explicit search commands, recency/currency phrases, browse/check, research, news, direct tool references). All patterns use `\b` word boundaries and `/i` case-insensitive flags to minimize false positives.
    - **`detectSearchIntent(messageText)`**: strips fenced code blocks (```` ``` ... ``` ````) and inline code (`` ` ... ` ``) from the message, then tests against all patterns. Returns `true` on first match.
    - **`mergeWebSearchTools(options)`**: sets `options.enable_tool_use = true` and de-duplicates the 5 search tools into `options.enabled_tools`.
    - **Interception point**: runs in `sendMessageCallback()` immediately after `mergeOptions()` (before `/clarify`, auto-clarify, and PKB slash command interceptions). Wrapped in try/catch with fail-open behavior — if detection throws, the message sends normally without search tools.
    - **No early return**: unlike `/clarify` interception, search-intent detection modifies `options` in-place and lets the send proceed normally.
    - **Example trigger phrases**: "search the web for X", "google Y", "latest news about Z", "find me recent info on", "what's the latest on", "look up", "check online", "news about", "headlines about", "enable web search".

17. **Shared tool metadata**: The 5 conversation-category tools define their names, descriptions, parameter schemas, and usage guidelines in a single dict `CONVERSATION_TOOLS` in `code_common/conversation_search.py`. Both `code_common/tools.py` (tool-calling framework) and `mcp_server/conversation.py` (MCP server) import from this shared source, ensuring descriptions are defined exactly once. The same module also provides `MessageSearchIndex` for BM25+text search and `extract_markdown_features()` for markdown structure extraction.

18. **BM25 message search index**: Conversation messages are incrementally indexed at persist time (`persist_current_turn`). The index stores unigram + bigram tokens with boosted weights for markdown headers and bold text. The `MessageSearchIndex` class serializes to/from JSON (the `BM25Okapi` object is rebuilt lazily from the stored token corpus). Older conversations without an index get a one-time full build on first search. The index is stored as `message_search_index` in `store_separate`.

19. **Dynamic document description injection**: When document tools are enabled, `_get_enabled_tools()` calls `_inject_dynamic_doc_descriptions(tools_param, user_email, users_dir)` (defined at line 6495 in `Conversation.py`) to post-process the OpenAI tools parameter list. This enriches document tool descriptions with the actual list of currently available documents so the LLM can skip calling `docs_list_global_docs` or `docs_list_conversation_docs` and go straight to `docs_query` / `docs_get_full_text` with the correct `doc_storage_path`. The injection is per-tool:
    - **`docs_list_global_docs`**: Appends a numbered listing of global documents (display_name, doc_id, path, priority label, deprecated tag) or "No global documents currently available."
    - **`docs_list_conversation_docs`**: Appends a numbered listing of conversation documents (name, #doc_N, path, priority label, deprecated tag) or "No documents attached to this conversation."
    - **`docs_query`, `docs_get_full_text`, `docs_get_info`, `docs_answer_question`**: Appends combined `doc_storage_path` values from both conversation and global docs so the LLM can use them directly.
    - **`docs_get_global_doc_info`, `docs_query_global_doc`, `docs_get_global_doc_full_text`**: Appends available global `doc_id` values.
    - **Cap**: `_DOC_LIST_CAP = 20` docs per type to prevent token bloat. Truncated with "... and N more" when exceeded.
    - **Lazy loading**: Global docs (`list_global_docs`) and conversation docs (`get_field('uploaded_documents_list')`) are only fetched when a matching tool is found in the enabled list, and cached within the method scope.
    - **Fallback**: If `users_dir` is not provided, falls back to `endpoints.state.get_state().users_dir`.
    - **Key files**: `Conversation.py` (lines 6491-6647)

20. **SUPERFAST_LLM for Jina search performance**: The `jina_search` tool handler in `code_common/tools.py` and the `WebSearchWithAgent.__call__` query generation path in `agents/search_and_information_agents.py` use `SUPERFAST_LLM[0]` (`inception/mercury-2`) instead of `CHEAP_LLM[0]` for faster query generation and per-query summarization. In the tool-calling headless path, query generation is already bypassed (pre-formatted code block), so SUPERFAST_LLM primarily accelerates the per-query combiner call in `JinaSearchAgent.process_query()`. In the non-headless path (direct agent use), SUPERFAST_LLM generates the search queries. Because SUPERFAST_LLM may produce malformed structured output (list-of-tuples format), the query generation includes explicit validation (non-empty list of 2-tuples with non-empty string queries) and falls back to `CHEAP_LLM[0]` on parsing failure. Content summarization for long (>10K char) search results at `process_search_result()` already used `SUPERFAST_LLM[0]` before this change.

21. **Tool call timing instrumentation**: Each tool call in `_run_tool_loop()` is wrapped with `time.time()` to measure two durations: `tool_exec_duration` (time for `TOOL_REGISTRY.execute()` only) and `tool_total_duration` (exec + user wait for interactive tools). These durations flow through `tool_round_details` (7-tuple), the `tool_result` streaming event (`duration_seconds` field), the collapsible `<tool_calls_summary>` block (e.g. `(4200 chars, 3.5s)`), and `time_dict['tool_calls']` (list of per-tool timing dicts in the end-of-message YAML).

22. **Parallel tool execution**: When the LLM issues multiple tool calls in a single response, `_run_tool_loop()` classifies them as interactive or non-interactive (based on `ToolDefinition.is_interactive`). Non-interactive tools are executed in parallel via `ThreadPoolExecutor` (max 5 workers). Each thread receives a `deepcopy` of the `ToolContext` so handlers cannot mutate shared state across threads. `TOOL_REGISTRY.execute()` only reads the registry dict (thread-safe for concurrent reads) and dispatches to the handler function with its own args and context copy. Interactive tools (e.g. `ask_clarification`) are executed sequentially after all non-interactive tools complete, since they require `threading.Event` synchronization for user input. Results are emitted to the UI in original call order regardless of completion order. This means if the LLM issues `web_search` + `perplexity_search` + `document_lookup` simultaneously, all three run in parallel and the total wall-clock time is the duration of the slowest tool rather than the sum of all three.

23. **Prompt guidance for parallel tool calls**: The tool awareness preamble injected into the system prompt includes a "Parallel Tool Calls" section that explicitly instructs the LLM to issue multiple tool calls at once when it needs independent pieces of information. This is critical for latency reduction — since non-interactive tools execute in parallel, issuing N calls in one response takes the same wall-clock time as the slowest single call, versus N sequential rounds. The prompt text: "You can and SHOULD issue multiple tool calls at once when you need independent pieces of information... All non-interactive tool calls in the same response are executed in parallel, so issuing multiple calls simultaneously is significantly faster than calling them one at a time across multiple rounds."

## UI Implementation Details

### Tool Selector Dropdown

The tool selector uses Bootstrap Select 1.13.18 (`<select multiple>` enhanced with search, optgroups, and select-all functionality). This replaces the original flat inline checkboxes that only offered per-category granularity.

**CDN Dependencies** (added to `interface/interface.html`):
- JS: `https://cdn.jsdelivr.net/npm/bootstrap-select@1.13.18/dist/js/bootstrap-select.min.js` (after bootstrap.bundle.min.js)
- CSS: `https://cdn.jsdelivr.net/npm/bootstrap-select@1.13.18/dist/css/bootstrap-select.min.css` (after bootstrap-icons)
- Version 1.13.x is required for Bootstrap 4.6 compatibility. 1.14+ targets Bootstrap 5 only.

**Dropdown Structure**:
```html
<select id="settings-tool-selector" multiple data-live-search="true" data-actions-box="true"
        data-selected-text-format="count > 3" data-count-selected-text="{0} tools selected"
        title="Select tools...">
    <optgroup label="Clarification">
        <option value="ask_clarification" selected>Ask Clarification</option>
    </optgroup>
    <optgroup label="Web Search">
        <option value="web_search" selected>Web Search</option>
        <!-- ... 5 more search tools ... -->
    </optgroup>
    <!-- ... 6 more optgroups ... -->
</select>
```

**Initialization**: The selectpicker is initialized in an inline `<script>` block after the select element, guarded with `typeof $.fn.selectpicker !== 'undefined'`. It is also refreshed:
- On modal open (`$('#chat-settings-modal').on('shown.bs.modal', ...)`)
- On master toggle change (when "Enable Tools" is checked)
- In `collectSettingsFromModal()` before reading values

**Data Format**: The dropdown sends an array of tool name strings (e.g. `["ask_clarification", "web_search"]`) instead of the old category boolean dict. The backend `_get_enabled_tools()` method accepts both formats:
- `isinstance(enabled_tools_config, list)` -> new per-tool format, used directly
- `isinstance(enabled_tools_config, dict)` -> legacy per-category format, maps categories to tool names
- `None` -> all tools enabled (when master toggle is on)

**Legacy State Restoration**: `setModalFromState()` in `chat.js` handles loading saved state from both formats. For legacy dict format, it uses a `categoryDefaults` mapping object that maps each category name to its full list of tool names, then concatenates the enabled categories' tools into a flat array for `$('#settings-tool-selector').val(...)`.

**CSS**: Custom max-height rules for the dropdown menu are added in the `#chat-settings-modal` style block:
```css
#chat-settings-modal .bootstrap-select .dropdown-menu { max-height: 300px !important; }
#chat-settings-modal .bootstrap-select .dropdown-menu .inner { max-height: 280px !important; }
```

### Prompt Caching Considerations

The tool definitions sent to the LLM API are **partially caching-friendly**:
- Tool definitions are static and deterministic (generated from `ToolRegistry` singleton at import time)
- Registration order is deterministic (module load order in `tools.py`)
- However, since users can select/deselect individual tools, the tool list can vary between requests -> cache miss
- Different users with different selections = no shared prompt cache

To maximize cache hits: keep the same tool selection between messages in a conversation. Toggling tools mid-conversation invalidates the API prompt cache.

## Tool Call History

### Motivation

Tool results (the `role: "tool"` messages in the agentic loop) are ephemeral — they exist only during `_run_tool_loop()` and are stripped from persisted messages. The `<tool_calls_summary>` block is explicitly regex-removed before storage (Conversation.py lines 3836-3848). Only brief timing metadata (`time_dict.tool_calls`) survives. This means if a user asks a follow-up question that requires the same web search, the LLM must re-execute the search from scratch.

The Tool Call History system solves this by recording every tool execution (inputs, outputs, timing) in a per-user SQLite database. The LLM can then query past results via 4 new tools, avoiding redundant re-execution and enabling cross-conversation knowledge reuse.

### Architecture

```
Tool Execution (Conversation.py _run_tool_loop)
    |
    +-- record to ToolCallHistoryDB (fail-open, try/except)
    |
MCP Tool Execution (mcp_server/mcp_app.py)
    |
    +-- record via _record_mcp_tool_call() (fail-open)
    |
    v
ToolCallHistoryDB (storage/users/tool_call_history.sqlite)
    |
    +-- Queried by 4 new LLM tools (list_search_history, get_search_results,
    |   list_tool_call_history, get_tool_call_results)
    |
    +-- Queried by 4 new MCP tools (same names, same logic)
    |
    +-- Auto-pruned: 30-day age limit, 10,000 rows per user
```

### Storage Layer

**Database**: `storage/users/tool_call_history.sqlite` — a separate SQLite file (not `users.db`) because tool history has high write frequency, large TEXT blobs, and aggressive pruning. Follows the `pkb.sqlite` / `search_index.db` precedent.

**Schema** (`tool_call_history` table):

| Column | Type | Description |
|---|---|---|
| `id` | TEXT | Deterministic hash of `tool_name + sorted(args_json)` — 16-char hex via SHA-256. Same inputs always produce the same ID. |
| `tool_name` | TEXT | Registered tool name (e.g. `web_search`, `pkb_search`) |
| `tool_category` | TEXT | Category from `TOOL_REGISTRY` (e.g. `search`, `documents`) |
| `args_json` | TEXT | JSON-serialized tool arguments |
| `result_text` | TEXT | Full result text (capped at 50,000 chars at recording time) |
| `error` | TEXT | Error message if the tool failed, NULL otherwise |
| `user_email` | TEXT | User who executed the tool (scoping key) |
| `conversation_id` | TEXT | Conversation where the tool was called |
| `timestamp` | REAL | Unix epoch of execution |
| `duration_seconds` | REAL | Wall-clock execution time |
| `result_chars` | INTEGER | Length of result_text |
| `source` | TEXT | `"tool_calling"` or `"mcp"` |

**Primary key**: `(id, timestamp)` — allows the same tool+args combination to have multiple executions over time (results may change for web searches).

**Indexes**: user_email, tool_name, tool_category, timestamp, conversation_id, id, composite `(user_email, tool_category, timestamp DESC)`.

**Singleton**: `get_tool_call_history_db()` returns a module-level singleton instance, lazy-initialized with double-checked locking. Thread-safe via WAL mode and `threading.Lock`.

### Deterministic Hash IDs

`tool_call_hash(tool_name, args_dict)` in `code_common/tool_call_history.py` computes a 16-character lowercase hex hash:

```python
canonical = json.dumps(args, sort_keys=True, ensure_ascii=False)
raw = f"{tool_name}:{canonical}"
return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

This means:
- Same tool + same arguments = same ID (enables deduplication)
- Argument order doesn't matter (`sort_keys=True`)
- The LLM can check if a search was already performed before re-executing it
- 64 bits of entropy — collision probability is negligible at expected volumes (~10^-6 at 10,000 records)

### Recording Hooks

**Tool-calling framework** (`Conversation.py`, `_run_tool_loop()`):
Two insertion points — one after the main tool execution block and one after interactive tool execution. Both wrapped in `try/except` with `logger.warning()` (fail-open). Records: tool_name, arguments, result_text (capped at 50,000 chars), user_email from `ToolContext`, conversation_id, duration, source=`"tool_calling"`.

**MCP server** (`mcp_server/mcp_app.py`):
A `_record_mcp_tool_call()` helper is called after each of the 4 existing MCP tool functions (`web_search`, `perplexity_search`, `jina_read_page`, `read_link`). User email is passed via `_mcp_request_context` thread-local, set in `JWTAuthMiddleware.__call__()` at JWT decode time. Also fail-open.

### Search Tool Names

`SEARCH_TOOL_NAMES` (frozen set in `code_common/tool_call_history.py`):
- `web_search`
- `perplexity_search`
- `jina_search`
- `jina_read_page`
- `read_link`

Used by `list_search_history` and `get_search_results` to filter to search/page-visit tools only. The `list_tool_call_history` and `get_tool_call_results` tools query ALL categories without this filter.

### Shared Tool Metadata

`TOOL_HISTORY_TOOLS` dict in `code_common/tool_call_history.py` defines canonical names, descriptions, parameter schemas, and usage guidelines for all 4 history tools. Imported by both `code_common/tools.py` (tool-calling registration) and `mcp_server/mcp_app.py` (MCP registration). Follows the same pattern as `CONVERSATION_TOOLS` in `code_common/conversation_search.py`.

### Auto-Pruning

On first access to `get_tool_call_history_db()`, the singleton runs `prune(max_age_days=30, max_rows_per_user=10000)`. Two passes:
1. **Age-based**: Delete all records older than 30 days.
2. **Per-user cap**: For each user, delete oldest rows beyond 10,000 (keeping newest).

Pruning is logged but fail-open — if it errors, the DB continues to function.

### Files

| File | Type | Description |
|---|---|---|
| `code_common/tool_call_history.py` | **New** | `ToolCallHistoryDB` class, `tool_call_hash()`, `get_tool_category()`, `SEARCH_TOOL_NAMES`, `TOOL_HISTORY_TOOLS` shared metadata, `get_tool_call_history_db()` singleton |
| `Conversation.py` | Modified | Import added, 2 recording hooks in `_run_tool_loop()` (after main tool execution and after interactive tool execution) |
| `code_common/tools.py` | Modified | Import `TOOL_HISTORY_TOOLS`, 4 new `@register_tool` registrations in `cross_conversation` category |
| `mcp_server/mcp_app.py` | Modified | `_mcp_request_context` thread-local, `_record_mcp_tool_call()` helper, recording in 4 existing tools, 4 new MCP tool functions |
| `interface/interface.html` | Modified | 4 new `<option>` elements in cross-conversation `<optgroup>` |
| `interface/chat.js` | Modified | 4 entries added to `categoryDefaults` mapping |

### Plan Reference

`documentation/planning/plans/tool_call_history.plan.md`
