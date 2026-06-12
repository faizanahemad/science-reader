# Agent / Delegate Task Tool

**Status: IMPLEMENTED** (March 2026)

## Motivation and Background

The system currently has 57+ tools across 10 categories. Each tool performs a single, well-scoped operation. However, complex user questions often require the main LLM to orchestrate multiple tool calls in sequence — consuming iteration budget and context window on the main conversation.

An "agent" meta-tool solves this by encapsulating a full LLM-with-tools sub-loop behind a single tool call. The main LLM delegates a sub-task (e.g. "research X using web search and documents") to a sub-LLM that has its own tool access, runs its own agentic loop, and returns a synthesized answer. This:

- Saves the main conversation's iteration budget (10 rounds) for higher-level reasoning
- Isolates multi-step research into a dedicated sub-agent with its own context
- Enables different tool profiles for different task types (research vs document analysis vs general)
- Keeps cost predictable with a configurable sub-agent model

### Existing Infrastructure Leveraged

- `_run_tool_loop()` in `Conversation.py` — the existing agentic tool loop. The sub-agent needs a similar (but non-streaming, simpler) loop
- `TOOL_REGISTRY.get_openai_tools_param(names)` — converts tool names to OpenAI format
- `TOOL_REGISTRY.execute(name, args, context, tool_call_id)` — executes any registered tool
- `call_llm()` in `code_common/call_llm.py` — supports `tools` and `tool_choice` parameters
- `ToolContext` — carries conversation_id, user_email, keys, model_overrides, plus `conversation_summary` / `recent_messages` fields that currently exist on the dataclass but are not populated by `_run_tool_loop()` today
- Shared metadata dict pattern (CONVERSATION_TOOLS, TOOL_HISTORY_TOOLS) for tool/MCP registration

## Requirements

### Functional

- R1: A single tool `delegate_task` is registered (both as `@register_tool` and `@mcp.tool()`) under a new `aggregator` category.
- R2: The tool accepts two parameters:
  - `prompt` (string, required): The task description / question for the sub-agent
  - `profile` (string enum, required): One of `"research"`, `"documents"`, `"general"`. Determines which tools the sub-agent gets.
- R3: Three profiles are defined as a configuration constant `AGENT_PROFILES`:
  - `research`: Search tools + document query tools + conversation search tools. Optimized for web research and information gathering.
  - `documents`: Document tools (full set) + conversation tools. Optimized for document analysis, lookup, querying.
  - `general`: Union of all non-interactive tools enabled by default. Broadest capability set.
- R4: Each profile maps to a list of tool names. Adding a new tool to a profile = adding its name to the list. Adding a new profile = adding a new key to `AGENT_PROFILES`.
- R5: The sub-agent uses a configurable model specified by `AGENT_DEFAULT_MODEL` constant (default: a fast/cheap model like `openai/gpt-4o-mini`). Can be overridden via `model_overrides` if an `agent_model` key is present.
- R6: The sub-agent runs a non-streaming mini tool loop with max 5 iterations (`AGENT_MAX_ITERATIONS` constant).
- R7: The sub-agent receives a system prompt that includes parent conversation context, but **not from `ToolContext.conversation_summary` directly** because current code does not populate that field in `_run_tool_loop()`. The implementation must fetch context explicitly (e.g. from the current `Conversation` object when available, or by calling existing conversation-summary retrieval helpers/tools).
- R8: The sub-agent CANNOT use interactive tools (like `ask_clarification`). Interactive tools are filtered out from any profile's tool list.
- R9: **1-level recursion**: The sub-agent CAN call `delegate_task` itself (so it appears in `general` profile's tool list). However, the inner sub-agent (depth=2) CANNOT call `delegate_task` — it is stripped from the tool list at depth >= 2. Implemented via a `_depth` parameter on the handler (not exposed to the LLM).
- R10: The tool returns the sub-agent's final synthesized text answer as `ToolCallResult.result`. If the sub-agent fails or hits max iterations without producing text, return an error message.
- R11: All sub-agent tool executions must be explicitly recorded in `tool_call_history`. Current code records tool history in `Conversation._run_tool_loop()` **after** `TOOL_REGISTRY.execute()` returns; `TOOL_REGISTRY.execute()` itself does not record anything.
- R12: The `delegate_task` call itself is also recorded in tool_call_history by the existing recording hook in `_run_tool_loop`.

### Non-Functional

- NR1: Sub-agent execution is **synchronous and blocking** — the main LLM's tool loop waits for the result. This is standard tool behavior.
- NR2: Sub-agent execution is **silent** — no streaming events are sent to the UI during sub-agent execution. The main tool loop shows a "Delegating task..." status message.
- NR3: Sub-agent should respect the same API keys from `ToolContext.keys`.
- NR4: Sub-agent timeout: reasonable wall-clock timeout (e.g. 5 minutes) to prevent runaway executions.
- NR5: Fail-open: If the sub-agent loop crashes, the tool returns an error result (not a crash).

## Architecture

### New Module: `code_common/agent_tool.py`

Central module containing:
- `AGENT_DEFAULT_MODEL` — configurable constant for the sub-agent model
- `AGENT_MAX_ITERATIONS` — max tool loop iterations for sub-agent (default 5)
- `AGENT_PROFILES` — dict mapping profile names to lists of tool names
- `AGENT_TOOLS` — shared metadata dict (like `TOOL_HISTORY_TOOLS`) for the `delegate_task` tool definition, used by both `tools.py` and `mcp_app.py`
- `run_agent_loop()` — the core function: takes prompt, profile, context, depth → runs the mini tool loop → returns final text
- Helper: `_get_parent_agent_context(...)` — fetches parent conversation context explicitly because `ToolContext.conversation_summary` / `recent_messages` are not populated today
- Helper: `_build_agent_system_prompt(parent_context)` — builds the sub-agent's system prompt
- Helper: `_resolve_agent_tools(profile, depth)` — returns OpenAI-format tool list for the given profile, filtering interactive tools and `delegate_task` if depth >= 2

### Sub-Agent Loop Design

The sub-agent loop is a simplified, non-streaming version of `_run_tool_loop`:

```
def run_agent_loop(prompt, profile, context, depth=1):
    1. Resolve tools via _resolve_agent_tools(profile, depth)
    2. Fetch parent context explicitly (do not assume `context.conversation_summary` is populated)
    3. Build system prompt via _build_agent_system_prompt(parent_context)
    4. Determine model (AGENT_DEFAULT_MODEL or context.model_overrides.get("agent_model"))
    5. Build messages = [system, user(prompt)]
    6. Loop up to AGENT_MAX_ITERATIONS:
       a. Call call_llm(messages=messages, tools=tools, stream=False)  # non-streaming
       b. Parse the return value carefully: with tools enabled, non-streaming `call_llm()` may return a mixed list of `str` chunks and `dict` tool-call items rather than a plain string
       c. If response is text-only → return text
       d. If response has tool_calls → execute each via TOOL_REGISTRY.execute(), then explicitly record each tool call in tool_call_history
       e. Append assistant+tool messages, continue loop
    7. On last iteration, call with tool_choice="none" to force text
    8. Return final text (or error message if empty)
```

Key difference from `_run_tool_loop`: this is a regular function (not a generator), non-streaming, and returns a string.

### Tool Registration

**In `code_common/tools.py`:**
```python
from code_common.agent_tool import AGENT_TOOLS, run_agent_loop

def _agent_tool_kwargs(tool_name):
    return {k: v for k, v in AGENT_TOOLS[tool_name].items()
            if k in ('name', 'description', 'parameters', 'is_interactive', 'category')}

@register_tool(**_agent_tool_kwargs("delegate_task"))
def handle_delegate_task(args, context):
    prompt = args.get("prompt", "")
    profile = args.get("profile", "general")
    result_text = run_agent_loop(prompt, profile, context, depth=1)
    return ToolCallResult(tool_id="", tool_name="delegate_task", result=result_text)
```

**In `mcp_server/mcp_app.py`:**
```python
@mcp.tool()
async def delegate_task(prompt: str, profile: str = "general") -> str:
    """[description from AGENT_TOOLS]"""
    mcp_context = ToolContext(
        conversation_id="",
        user_email=getattr(_mcp_request_context, 'user_email', 'unknown'),
        keys=_get_keys(),
        model_overrides={},
    )
    result = run_agent_loop(prompt, profile, mcp_context, depth=1)
    _record_mcp_tool_call(...)
    return result
```

### Recursion Control (depth parameter)

- The `handle_delegate_task` handler calls `run_agent_loop(depth=1)`
- Inside `run_agent_loop`, when executing tool calls, if a tool_call is for `delegate_task`, it calls `run_agent_loop(depth=depth+1)`
- `_resolve_agent_tools(profile, depth)` strips `delegate_task` from the tool list when `depth >= 2`
- This means: main LLM → delegate_task (depth=1, can see delegate_task in general profile) → delegate_task (depth=2, delegate_task stripped from tools) → no further recursion possible

### Profile Configuration

```python
AGENT_PROFILES = {
    "research": [
        # Search tools
        "web_search", "perplexity_search", "jina_search", "jina_read_page", "read_link",
        # Document query tools (read-only)
        "document_lookup", "docs_list_conversation_docs", "docs_list_global_docs",
        "docs_query", "docs_get_full_text", "docs_get_info", "docs_answer_question",
        "docs_get_global_doc_info", "docs_query_global_doc", "docs_get_global_doc_full_text",
        # Conversation search
        "search_messages", "list_messages", "read_message",
        "search_conversations", "list_user_conversations", "get_conversation_summary",
        # Tool call history (reuse previous results)
        "list_search_history", "get_search_results",
        "list_tool_call_history", "get_tool_call_results",
    ],
    "documents": [
        # Full document tools
        "document_lookup", "docs_list_conversation_docs", "docs_list_global_docs",
        "docs_query", "docs_get_full_text", "docs_get_info", "docs_answer_question",
        "docs_get_global_doc_info", "docs_query_global_doc", "docs_get_global_doc_full_text",
        # Conversation tools (for cross-referencing)
        "search_messages", "list_messages", "read_message",
        "get_conversation_details", "get_conversation_memory_pad",
        "search_conversations", "list_user_conversations", "get_conversation_summary",
        # Tool call history
        "list_search_history", "get_search_results",
        "list_tool_call_history", "get_tool_call_results",
    ],
    "general": [
        # Search
        "web_search", "perplexity_search", "jina_search", "jina_read_page", "read_link",
        # Documents
        "document_lookup", "docs_list_conversation_docs", "docs_list_global_docs",
        "docs_query", "docs_get_full_text", "docs_get_info", "docs_answer_question",
        "docs_get_global_doc_info", "docs_query_global_doc", "docs_get_global_doc_full_text",
        # Conversation & cross-conversation
        "search_messages", "list_messages", "read_message",
        "get_conversation_details", "get_conversation_memory_pad",
        "search_conversations", "list_user_conversations", "get_conversation_summary",
        # Memory
        "conv_get_memory_pad", "conv_get_history",
        "conv_get_user_detail", "conv_get_user_preference", "conv_get_messages",
        # Tool call history
        "list_search_history", "get_search_results",
        "list_tool_call_history", "get_tool_call_results",
        # Code runner
        "run_python_code",
        # Delegate (for 1-level recursion — stripped at depth >= 2)
        "delegate_task",
    ],
}
```

Note: Interactive tools (`ask_clarification`) are NEVER included. Write tools (`conv_set_memory_pad`, `conv_set_user_detail`, PKB write tools, artefact write tools) are excluded from sub-agent profiles by default for safety — the sub-agent is read-only + search + code execution.

### Frontend Changes

**`interface/interface.html`** — New optgroup after Prompts:
```html
<optgroup label="Aggregator">
    <option value="delegate_task">Delegate Task</option>
</optgroup>
```

**`interface/chat.js`** — New entry in `categoryDefaults`:
```javascript
aggregator: ['delegate_task'],
```

### Conversation.py Changes

Minimal changes needed:
- The `_get_enabled_tools` legacy category mapping needs an `aggregator` entry (line ~6574)
- The `delegate_task` handler runs `run_agent_loop()` which uses `call_llm()` and `TOOL_REGISTRY.execute()` directly — it does NOT go through `_run_tool_loop` (that's the streaming generator). This avoids nesting generators.

### MCP Changes

**`mcp_server/mcp_app.py`** — One new MCP tool `delegate_task` following the same pattern as existing MCP tools. Uses the same `run_agent_loop()` core function.

## Implementation Tasks

### Task 1: Create `code_common/agent_tool.py`
- Define constants: `AGENT_DEFAULT_MODEL`, `AGENT_MAX_ITERATIONS`, `AGENT_PROFILES`
- Define `AGENT_TOOLS` shared metadata dict with `delegate_task` tool definition
- Implement `_get_parent_agent_context(...)` to fetch current-conversation context explicitly
- Implement `_build_agent_system_prompt(parent_context)` 
- Implement `_resolve_agent_tools(profile, depth)` — get tool names for profile, validate names against `TOOL_REGISTRY`, filter interactive tools via `ToolDefinition.is_interactive`, filter `delegate_task` if depth >= 2, convert to OpenAI format via `TOOL_REGISTRY`
- Implement a small helper for explicit tool-call history recording so the sub-agent loop matches `_run_tool_loop()` behavior
- Implement `run_agent_loop(prompt, profile, context, depth=1)` — the non-streaming mini tool loop, including mixed `call_llm(..., stream=False)` response parsing
- Add `_agent_tool_kwargs()` extraction helper

### Task 2: Register tool in `code_common/tools.py`
- Import from `code_common.agent_tool`
- Add `_agent_tool_kwargs()` extraction function
- Add `@register_tool(**_agent_tool_kwargs("delegate_task"))` with `handle_delegate_task` handler
- Handler extracts prompt, profile from args, calls `run_agent_loop()`, returns `ToolCallResult`

### Task 3: Register MCP tool in `mcp_server/mcp_app.py`
- Import from `code_common.agent_tool`
- Add `@mcp.tool()` function for `delegate_task`
- Include recording via `_record_mcp_tool_call()`

### Task 4: Update `Conversation.py`
- Add `"aggregator"` to the legacy category mapping in `_get_enabled_tools()` (~line 6574)

### Task 5: Update frontend
- `interface/interface.html`: Add `<optgroup label="Aggregator">` with `delegate_task` option
- `interface/chat.js`: Add `aggregator: ['delegate_task']` to `categoryDefaults`

### Task 6: Update documentation
- `documentation/features/tool_calling/README.md`: Add Aggregator Tools section
- `documentation/features/mcp_web_search_server/README.md`: Add delegate_task MCP tool
- `documentation/README.md`: Update feature index if needed

### Task 7: Update this plan with implementation status

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Sub-agent runs too long, blocking main loop | 5-iteration cap + wall-clock timeout (5 min). Last iteration forces `tool_choice="none"`. |
| Runaway recursion | Hard depth limit: delegate_task stripped from tools at depth >= 2. Max total nesting = 2 levels. |
| Sub-agent crashes, kills main response | Full try/except in handler — returns error text as ToolCallResult, never propagates exception. |
| Cost explosion from sub-agent model | Configurable `AGENT_DEFAULT_MODEL` defaults to cheap/fast model. Can be overridden per-conversation. |
| Sub-agent modifies state unexpectedly | Profiles exclude write tools by default (no PKB writes, no artefact writes, no memory writes). Only `general` includes `run_python_code` which is sandboxed. |
| Context mismatch — sub-agent lacks conversation context | Do not rely on `ToolContext.conversation_summary` because current code leaves it empty. Fetch parent context explicitly before building the sub-agent system prompt. |

## Alternatives Considered

1. **Reuse `_run_tool_loop` directly**: Rejected — it's a streaming generator tightly coupled to the HTTP response pipeline. The sub-agent needs a synchronous, non-streaming loop.
2. **Use `TemporaryConversation`**: Considered — but that class is for persistent cloning. Our sub-agent is ephemeral and doesn't need conversation storage.
3. **Expose profile tool lists in the UI**: Deferred — profile configuration via UI can be added later. For now, profiles are code-level constants.
4. **Separate tool registrations per profile**: Rejected — one tool with a profile parameter is cleaner and more extensible.

## Code-Review Corrections Incorporated

- `call_llm(..., stream=False, tools=...)` cannot be treated as returning only a string. In tool-calling mode it may return a mixed list of text chunks and structured `tool_call` dicts, so the sub-agent loop needs explicit parsing logic.
- `TOOL_REGISTRY.execute()` does **not** write to tool-call history. The existing recording happens in `Conversation._run_tool_loop()` after execution, so the sub-agent loop needs its own explicit recording helper.
- `ToolContext.conversation_summary` and `ToolContext.recent_messages` exist on the dataclass but are not populated in the current tool loop, so parent context must be fetched explicitly.
- The MCP version cannot rely on an implicit `mcp_context`; it needs to construct a real `ToolContext` using `_get_keys()` and `_mcp_request_context.user_email`.

## Files to Create/Modify

### Create
- `code_common/agent_tool.py` — Core module with constants, profiles, loop, shared metadata

### Modify
- `code_common/tools.py` — Add `delegate_task` registration + handler
- `mcp_server/mcp_app.py` — Add `delegate_task` MCP tool
- `Conversation.py` — Add `aggregator` to legacy category mapping
- `interface/interface.html` — Add Aggregator optgroup
- `interface/chat.js` — Add `aggregator` to `categoryDefaults`
- `documentation/features/tool_calling/README.md` — Add Aggregator Tools section
- `documentation/features/mcp_web_search_server/README.md` — Add delegate_task MCP tool
- `documentation/README.md` — Update feature index
