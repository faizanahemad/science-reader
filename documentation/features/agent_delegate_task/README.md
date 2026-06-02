# Agent Delegate Task (Aggregator Tool)

## Overview

The `delegate_task` tool is a meta-tool that encapsulates a full LLM-with-tools sub-loop behind a single tool call. The main LLM delegates a sub-task (e.g. "research X using web search and documents") to a sub-agent that has its own tool access, runs its own agentic loop, and returns a synthesized text answer.

This transforms complex multi-tool workflows from consuming the main conversation's iteration budget into a single tool call with an isolated sub-agent. The sub-agent runs silently (no streaming UI feedback) and returns only the final answer.

**Key numbers**: 4 tools (`delegate_task`, `delegate_task_background`, `get_task_result`, `list_background_tasks`), 3 configurable profiles, up to 5 sub-agent iterations, default model `openai/gpt-4o-mini`, 5-minute wall-clock timeout, 1-level recursion support.

**Plan reference**: `documentation/planning/plans/agent_delegate_task.plan.md`

## Motivation

The system has 87 tools across 13 categories. Complex user questions often require the main LLM to orchestrate multiple tool calls in sequence — consuming iteration budget (up to 5 rounds per turn) and context window on the main conversation. The delegate_task tool solves this by:

- Saving the main conversation's iteration budget for higher-level reasoning
- Isolating multi-step research into a dedicated sub-agent with its own context
- Enabling different tool profiles for different task types (research vs document analysis vs general)
- Keeping cost predictable with a configurable sub-agent model (`gpt-4o-mini` by default)

## User Guide

### How to Use

1. Enable the **Aggregator** category in the tool selector dropdown (gear icon → tool selector → Aggregator optgroup).
2. Send a message that requires multi-step tool work (e.g. "Research the latest developments in quantum computing and cross-reference with my uploaded papers").
3. The main LLM may choose to call `delegate_task` with a focused prompt and appropriate profile.
4. A status indicator shows "Delegating task..." while the sub-agent works.
5. The sub-agent's synthesized answer is returned to the main LLM, which incorporates it into its response.

### Profiles

| Profile | Tools Included | Best For |
|---------|---------------|----------|
| `research` | Web search (5), document query (10), conversation search (6), tool call history (4) — 25 tools | Web research, information gathering, cross-referencing search results with documents |
| `documents` | Document tools (10), conversation tools (7), cross-conversation search (3), tool call history (4) — 24 tools | Deep document analysis, cross-document querying, conversation history analysis |
| `general` | All of the above + memory tools (5) + code runner (1) + coding tools (12) + `delegate_task` + `delegate_task_background` + `list_background_tasks` — 65+ tools | Broadest capability set; includes code execution, file system access, and 1-level recursion |

All profiles exclude interactive tools (`ask_clarification`, `pkb_propose_memory`) and write tools (PKB writes, artefact writes, memory writes) for safety — the sub-agent is read-only + search + code execution.

### Example Flows

**Flow 1 — Research delegation**:
User asks "What are the latest breakthroughs in CRISPR gene editing?". The main LLM calls `delegate_task(prompt="Search for latest CRISPR breakthroughs in 2025-2026, focusing on therapeutic applications", profile="research")`. The sub-agent calls `web_search`, then `perplexity_search` for deeper results, synthesizes findings, and returns a comprehensive summary to the main LLM.

**Flow 2 — Document analysis delegation**:
User asks "Compare the methodology sections across my three uploaded papers". The main LLM calls `delegate_task(prompt="List all conversation docs, then query each for their methodology section and compare approaches", profile="documents")`. The sub-agent calls `docs_list_conversation_docs`, then `docs_query` on each doc, and returns a comparative analysis.

**Flow 3 — General task with code**:
User asks "Calculate the statistical significance of these results and search for similar studies". The main LLM calls `delegate_task(prompt="Run a t-test on [data] using Python, then search for comparable studies", profile="general")`. The sub-agent calls `run_python_code` for the calculation, then `web_search` for related studies.

**Flow 4 — Background delegation**:
**Flow 4 — Background delegation**:
User asks "Summarise this conversation AND research recent transformer efficiency papers". The main LLM calls `delegate_task_background(prompt="Research recent transformer efficiency papers", profile="research")`, gets `{"task_id": "abc-123", "status": "running"}` immediately, begins summarising, then calls `get_task_result(task_id="abc-123")` later to incorporate the results. It can also call `list_background_tasks()` to see all running and completed tasks.

## Architecture

### Core Module: `code_common/agent_tool.py`

Central module containing all agent configuration and the sub-agent loop.

**Constants**:
- `AGENT_DEFAULT_MODEL = "openai/gpt-4o-mini"` — default sub-agent model (cheap/fast)
- `AGENT_MAX_ITERATIONS = 5` — max tool loop iterations per sub-agent invocation
- `AGENT_TIMEOUT_SECONDS = 300` — 5-minute wall-clock timeout

**`AGENT_PROFILES`** — dict mapping profile names to lists of tool names. Adding a new tool to a profile = adding its name string to the appropriate list. Adding a new profile = adding a new key.

**`AGENT_TOOLS`** — shared metadata dict (like `CONVERSATION_TOOLS` and `TOOL_HISTORY_TOOLS`) defining all 4 aggregator tools' names, descriptions, parameters, categories, and interactive flags. Imported by both `code_common/tools.py` (tool-calling registration) and `mcp_server/mcp_app.py` (MCP registration) to ensure descriptions are defined exactly once.

### Sub-Agent Loop: `run_agent_loop()` and Background Variants

A synchronous (non-streaming) function used directly by `delegate_task` and run in a daemon thread by `delegate_task_background`:

```
run_agent_loop(prompt, profile, context, depth=1):
    1. Resolve tools: _resolve_agent_tools(profile, depth)
       - Validate tool names against TOOL_REGISTRY
       - Filter out interactive tools (is_interactive=True)
       - Strip delegate_task if depth >= 2 (recursion prevention)
    2. Build system prompt with parent conversation context
    3. Determine model: AGENT_DEFAULT_MODEL or model_overrides.get("agent_model")
    4. messages = [system, user(prompt)]
    5. Loop up to AGENT_MAX_ITERATIONS:
       a. call_llm(messages=messages, tools=tools, stream=False)
       b. Parse mixed response (str chunks + dict tool_calls)
       c. If text-only → return text
       d. If tool_calls → execute each via TOOL_REGISTRY.execute()
       e. Record each sub-agent tool call in tool_call_history (source="agent_delegate")
       f. Append assistant + tool messages, continue loop
    6. On last iteration: tool_choice="none" to force text
    7. Return final text (or error message)
```

Key difference from `_run_tool_loop()`: regular function (not a generator), non-streaming, returns a string.

### Background Execution: `delegate_task_background`, `get_task_result`, `list_background_tasks`

Allows the main LLM to fire a sub-agent concurrently and poll for results without blocking its own iteration budget. `list_background_tasks` enumerates all tasks (running, done, error) in the current server session.

**Storage**: `_BACKGROUND_TASKS: dict[str, dict]` in `code_common/agent_tool.py`, keyed by UUID4. Each entry: `{"status": "running"|"done"|"error", "result": str, "started_at": float}`. Protected by `_BACKGROUND_TASKS_LOCK = threading.Lock()`.

**`delegate_task_background`**: Creates entry, starts daemon thread running `run_agent_loop()`, returns `{"task_id": "...", "status": "running"}` immediately.

**`get_task_result`**: Returns `{"status": "running"|"done"|"error", "result": "..."}`. Lazily expires tasks older than 30 minutes.

**`list_background_tasks`**: Returns a JSON list of all tasks with their status, task_id, and started_at timestamp. Useful for the LLM to discover and poll multiple background tasks.

**Recursion guard**: `delegate_task_background` stripped from tool lists at depth ≥ 2, same as `delegate_task`.

**Caveat**: Tasks are in-memory only — a server restart clears all background tasks. For critical work, prefer synchronous `delegate_task`.

### Recursion Control

- `handle_delegate_task` handler calls `run_agent_loop(depth=1)`
- Inside the loop, if a tool call is for `delegate_task`, it calls `run_agent_loop(depth=depth+1)`
- `_resolve_agent_tools(profile, depth)` strips `delegate_task` from the tool list when `depth >= 2`
- Result: main LLM → `delegate_task` (depth=1, can see `delegate_task` in general profile) → `delegate_task` (depth=2, `delegate_task` stripped) → no further recursion

### Dual Registration

**Tool-calling framework** (`code_common/tools.py`):
```python
@register_tool(**_agent_tool_kwargs("delegate_task"))
def handle_delegate_task(args, context):
    prompt = args.get("prompt", "")
    profile = args.get("profile", "general")
    result_text = run_agent_loop(prompt, profile, context, depth=1)
    return ToolCallResult(tool_id="", tool_name="delegate_task", result=result_text)
```

**MCP server** (`mcp_server/mcp_app.py`):
```python
@mcp.tool()
def delegate_task(prompt: str, profile: str = "general") -> str:
    mcp_context = ToolContext(
        conversation_id="",
        user_email=getattr(_mcp_request_context, 'user_email', 'unknown'),
        keys=_get_keys(),
    )
    result = run_agent_loop(prompt, profile, mcp_context, depth=1)
    _record_mcp_tool_call(...)
    return result
```

Both paths call the same `run_agent_loop()` core function.

### Frontend Integration

- **UI category**: "Aggregator" optgroup in the Bootstrap Select tool dropdown
- **Legacy support**: `aggregator: ['delegate_task', 'delegate_task_background', 'get_task_result', 'list_background_tasks']` in `categoryDefaults` (chat.js)
- **Backend**: `"aggregator": enabled_tools_config.get("aggregator", False)` in `_get_enabled_tools()` (Conversation.py)
- **Default**: OFF (not in `DEFAULT_ENABLED_TOOLS`) — user must explicitly enable

## Configuration

### Model Override

The sub-agent model can be overridden per-conversation via `model_overrides.agent_model`:

```python
# In conversation settings:
model_overrides = {"agent_model": "openai/gpt-4o"}  # Use a more capable model
```

If `agent_model` is not set, falls back to `AGENT_DEFAULT_MODEL` (`openai/gpt-4o-mini`).

### Adding Tools to Profiles

Edit `AGENT_PROFILES` in `code_common/agent_tool.py`:

```python
AGENT_PROFILES = {
    "research": [
        "web_search", "perplexity_search", ...,
        "my_new_tool",  # Just add the tool name string
    ],
    ...
}
```

New tools or MCPs added to the codebase become automatically available to the sub-agent by simply adding their registered name to the appropriate profile list.

### Adding New Profiles

Add a new key to `AGENT_PROFILES`:

```python
AGENT_PROFILES = {
    ...,
    "my_custom_profile": [
        "web_search", "document_lookup", "run_python_code",
    ],
}
```

The `profile` parameter's enum in the tool schema should be updated accordingly in `AGENT_TOOLS`.

## Tool Call History

Sub-agent tool executions are recorded in `tool_call_history.sqlite` with `source="agent_delegate"`. This distinguishes sub-agent calls from direct tool-calling framework calls (`source="tool_calling"`) and MCP calls (`source="mcp"`). The `delegate_task` call itself is also recorded by the existing recording hook in `_run_tool_loop()`.

## Implementation Notes

1. **Non-streaming execution**: The sub-agent uses `call_llm(stream=False, tools=...)` which returns a mixed list of `str` chunks and `dict` tool-call items. The `_parse_llm_response()` helper separates text from tool calls.

2. **Context limitations**: `ToolContext.conversation_summary` is not populated by `_run_tool_loop()` in current code. The sub-agent's system prompt is built with whatever context is available — for tool-calling invocations, conversation context may be available; for MCP invocations, no conversation history is accessible.

3. **Fail-open design**: The entire `run_agent_loop()` is wrapped in try/except. All errors produce text error messages returned as `ToolCallResult.result` — never crash the main response or MCP call.

4. **Thread safety**: Each sub-agent invocation creates its own messages list and tool context. No shared mutable state between concurrent sub-agent calls.

5. **Silent execution**: No streaming events sent to UI during sub-agent execution. Main tool loop shows a "Delegating task..." status pill.

6. **Background task expiry**: `_BACKGROUND_TASKS` entries older than 30 minutes deleted lazily on each `get_task_result` call. Server restart clears all tasks.

## Files

### Created
| File | Description |
|------|-------------|
| `code_common/agent_tool.py` | Core module: constants, profiles, `AGENT_TOOLS` metadata, `run_agent_loop()`, helpers |

### Modified
| File | Change |
|------|--------|
| `code_common/tools.py` | Added `delegate_task`, `delegate_task_background`, `get_task_result`, `list_background_tasks` `@register_tool` registrations + handlers |
| `mcp_server/mcp_app.py` | Added `delegate_task`, `delegate_task_background`, `get_task_result`, `list_background_tasks` `@mcp.tool()` registrations |
| `Conversation.py` | Added `aggregator` to legacy category mapping in `_get_enabled_tools()` |
| `interface/interface.html` | Added `<optgroup label="Aggregator">` with 4 tool options (`delegate_task`, `delegate_task_background`, `get_task_result`, `list_background_tasks`) |
| `interface/chat.js` | Added `aggregator: ['delegate_task', 'delegate_task_background', 'get_task_result', 'list_background_tasks']` to `categoryDefaults` |

### Documentation Updated
| File | Change |
|------|--------|
| `documentation/features/tool_calling/README.md` | Added aggregator category to tables, tool inventory section, architecture notes |
| `documentation/features/mcp_web_search_server/README.md` | Added `delegate_task` MCP tool description and architecture diagram entry |
| `documentation/product/behavior/chat_app_capabilities.md` | Updated tool counts and categories to include aggregator |
| `documentation/README.md` | Added agent_delegate_task feature entry |

## See Also

- `documentation/features/tool_calling/README.md` — Full tool calling framework docs (aggregator is one category)
- `documentation/features/mcp_web_search_server/README.md` — MCP server docs (delegate_task as MCP tool)
- `documentation/planning/plans/agent_delegate_task.plan.md` — Original plan with architecture decisions and code-review corrections
