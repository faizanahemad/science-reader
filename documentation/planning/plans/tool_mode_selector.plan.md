# Plan: Tool Mode Selector — 5-Mode Tool Selection System

**Status:** DONE (June 2026)

## Motivation

With all 97 tools enabled, the system consumes ~14,200 tokens per turn just for tool definitions in the OpenAI `tools` parameter. Most conversations use only 3-8 tools per turn. The current binary toggle (tools ON/OFF) forces a choice between full capability (expensive) and no tools (limiting).

**Goal**: Replace the binary checkbox with a 5-mode selector that offers optimal token efficiency while keeping all tools accessible.

## Requirements

1. Replace `#settings-enable_tool_use` checkbox with a 5-option selector
2. Each mode has a different token/latency/recall trade-off
3. Default to "Hybrid" mode (best balance)
4. Backward-compatible with existing payloads (`enable_tool_use: true/false`)
5. The existing per-tool selectpicker dropdown only shows in "Manual" mode
6. `request_tools` meta-tool acts as zero-cost internal expansion (doesn't consume iteration budget)
7. Smart Select uses `VERY_CHEAP_LLM[0]` for fast tool selection

## The 5 Modes

| # | Mode Value | UI Label | Behavior | Token Cost |
|---|-----------|----------|----------|------------|
| 1 | `tiered` | Tiered (core + on-demand) | Core 12 tools + `request_tools` meta-tool. LLM loads more categories on demand. | ~2,500 |
| 2 | `smart` | Smart Select (AI picks per turn) | Fast LLM selects 15-25 relevant tools based on message + context. No fallback. | ~3,000-4,500 + 200ms |
| 3 | `hybrid` | Hybrid (AI + fallback) | Smart Select + `request_tools` meta-tool for anything the selector missed. **Default.** | ~3,500-5,000 + 200ms |
| 4 | `manual` | Manual Selection | User picks specific tools via existing selectpicker dropdown. Current behavior. | Varies |
| 5 | `none` | No Tools | Plain text only, zero overhead. | 0 |

## Tier 1 Tool Set (12 tools)

Used directly in "tiered" mode and as the always-include base in other modes:

```python
TIER_1_TOOLS = [
    # Clarification
    "ask_clarification",
    # Search (no web_search — perplexity/jina are superior)
    "perplexity_search",
    "jina_search",
    "jina_read_page",
    "read_link",
    # Documents
    "document_lookup",
    "docs_query",
    "docs_get_full_text",
    # PKB
    "pkb_search",
    # Aggregator
    "delegate_task",
    # Conversation
    "search_messages",
    # Meta
    "request_tools",
]
```

### Adaptive Tier 1

Instead of always using the static TIER_1_TOOLS, `get_adaptive_tier1_tools(user_email)` builds a personalized set from:
- **Fixed base** (5 tools: ask_clarification, pkb_search, delegate_task, search_messages, request_tools)
- **Most frequently used tools** by this user in the last 30 days (from tool_call_history DB)
- Capped at 12 tools total

Falls back to static TIER_1_TOOLS when user has <10 recorded tool calls (new user).

Rationale:
- These cover the most common user intents (ask questions, search web, look up docs, recall conversation)
- `web_search` excluded — `perplexity_search` and `jina_search` are strictly better
- Write tools excluded from core (PKB add/edit, file write, etc.) — loaded on demand
- `delegate_task` included since it can itself access any tool via profiles

## `request_tools` Meta-Tool

### Definition

```python
@register_tool(
    name="request_tools",
    description=(
        "Load additional tools not in your current set. Available categories: "
        "search, documents, pkb, memory, conversation, cross_conversation, "
        "code_runner, artefacts, prompts, coding, aggregator, general. "
        "You can also request specific tool names. After calling this, "
        "the tools become available immediately."
    ),
    parameters={
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Categories to load (e.g. ['coding', 'artefacts'])"
            },
            "tool_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific tool names to load (e.g. ['fs_write_file'])"
            },
        },
    },
    is_interactive=False,
    category="meta",
)
```

### Zero-Cost Behavior

In `_run_tool_loop()`:
- If the LLM's ONLY tool call in a response is `request_tools`:
  - Expand `tools_config` with requested tools
  - Do NOT increment the iteration counter
  - Do NOT yield a tool_result event (transparent to user)
  - Re-call LLM immediately with expanded tools
- If `request_tools` is called alongside other tools:
  - Expand `tools_config` for the next iteration
  - Execute other tools normally (counts as iteration)
  - The expanded tools are available from the next iteration onward
- **Expansions are per-turn only** — each new turn starts fresh from Tier 1 (or Smart Select). No persistence of expanded tools across turns.

### Result

`request_tools` returns a brief confirmation: "Loaded N tools from categories: [...]" — this becomes the `role: tool` message content so the LLM knows what's now available.

### Dynamic Description Injection

When building `tools_config`, the `request_tools` description is enriched with the names of all tools NOT currently loaded. This way the LLM sees exactly what's available to request without guessing. Example appended text:

```
Tools available to load: artefacts_create, artefacts_delete, fs_bash, fs_write_file, ...
```

## Smart Select — Dynamic LLM-Based Tool Selection

### Flow

```
User message arrives
       │
       ▼
Build compact tool menu (97 tools × ~50 chars each = ~1,250 tokens)
       │
       ▼
Call VERY_CHEAP_LLM[0] with:
  - User message (last message only, not full history)
  - Conversation summary (first 500 chars)
  - Compact tool menu
  - Prompt: "Select relevant tools. Be generous. Return JSON array."
       │
       ▼
Parse JSON response → list of tool names
       │
       ▼
Filter to only tools that are actually registered
       │
       ▼
Build tools_config from selected names
```

### The Compact Tool Menu

Pre-computed at import time from `TOOL_REGISTRY`:

```python
COMPACT_TOOL_MENU = "\n".join(
    f"- {t.name} [{t.category}]: {t.description[:80]}"
    for t in TOOL_REGISTRY.get_all_tools()
)
```

~97 lines × ~90 chars = ~8,700 chars ≈ 2,175 tokens input to the selection LLM.

### Selection Prompt

```
Given this user message and conversation context, select which tools might be needed to answer. Be generous — include anything plausibly relevant. Include follow-up tools (e.g. if search is needed, also include read_link). Always include ask_clarification if the request is ambiguous.

Message: {user_message}
Context: {summary[:500]}

Available tools:
{COMPACT_TOOL_MENU}

Return ONLY a JSON array of tool names: ["tool1", "tool2", ...]
```

### Fallback Behavior

- If the selection LLM fails (timeout, parse error, empty response): fall back to TIER_1_TOOLS
- If it returns fewer than 3 tools: add TIER_1_TOOLS as supplement
- If it returns more than 30 tools: truncate to 30 (diminishing returns past that)
- Entire selection wrapped in try/except (fail-open: defaults to tiered mode)

### Caching

Cache the selection result keyed by `hash(user_message + tool_mode)` for the duration of the turn (no cross-turn caching — context changes).

## UI Changes

### HTML (`interface/interface.html`)

Replace the checkbox with a select:

```html
<!-- Before: -->
<input class="form-check-input" id="settings-enable_tool_use" type="checkbox" checked="">
<label>Enable Tools</label>

<!-- After: -->
<label>Tool Mode</label>
<select id="settings-tool_mode" class="form-control form-control-sm">
  <option value="tiered">Tiered (core + on-demand)</option>
  <option value="smart">Smart Select (AI picks)</option>
  <option value="hybrid" selected>Hybrid (AI + fallback)</option>
  <option value="manual">Manual Selection</option>
  <option value="none">No Tools</option>
</select>
```

### JavaScript (`interface/chat.js`)

- `collectSettingsFromModal()`: Read `$('#settings-tool_mode').val()` → `options.tool_mode`
- `setModalFromState()`: Set the selector value, show/hide selectpicker based on mode
- `computeDefaultStateForTab()`: Default to `tool_mode: "hybrid"`
- `resetSettingsToDefaults()`: Reset to `"hybrid"`
- Show `#settings-tool-selector` (selectpicker) only when mode = `"manual"`

### JavaScript (`interface/common-chat.js`)

- `mergeOptions()`: Include `tool_mode` in the options payload
- Search-intent auto-detection: still operates, but instead of force-enabling tools, it upgrades mode from `none` to `hybrid` if search intent detected

### Payload (`/reply` request)

```json
{
  "checkboxes": {
    "tool_mode": "hybrid",
    "enabled_tools": [...]  // only meaningful when tool_mode = "manual"
  }
}
```

### Backward Compatibility

```python
# In _get_enabled_tools():
tool_mode = checkboxes.get("tool_mode")
if tool_mode is None:
    # Legacy payload
    if checkboxes.get("enable_tool_use", False):
        tool_mode = "manual"
    else:
        tool_mode = "none"
```

## Backend Changes

### `Conversation.py` — `_get_enabled_tools()`

Refactor to dispatch on `tool_mode`:

```python
def _get_enabled_tools(self, checkboxes, user_email, users_dir, user_message="", summary=""):
    tool_mode = _resolve_tool_mode(checkboxes)
    
    if tool_mode == "none":
        return None
    elif tool_mode == "manual":
        # Existing logic: read enabled_tools list/dict
        ...
    elif tool_mode == "tiered":
        return TOOL_REGISTRY.get_openai_tools_param(TIER_1_TOOLS)
    elif tool_mode == "smart":
        selected = _select_relevant_tools(user_message, summary, keys)
        return TOOL_REGISTRY.get_openai_tools_param(selected)
    elif tool_mode == "hybrid":
        selected = _select_relevant_tools(user_message, summary, keys)
        # Ensure request_tools is always present as fallback
        if "request_tools" not in selected:
            selected.append("request_tools")
        return TOOL_REGISTRY.get_openai_tools_param(selected)
```

### `Conversation.py` — `_run_tool_loop()`

Add `request_tools` handling:

```python
# Inside the tool execution loop:
if all(tc["function"]["name"] == "request_tools" for tc in tool_calls):
    # Zero-cost expansion — don't increment iteration counter
    new_tools = _handle_request_tools(tool_calls[0]["function"]["arguments"])
    tools_config = TOOL_REGISTRY.get_openai_tools_param(
        current_tool_names + new_tools
    )
    # Append tool result message and continue without incrementing
    messages.append({"role": "tool", "tool_call_id": ..., "content": f"Loaded {len(new_tools)} tools"})
    continue  # skip iteration_count += 1
```

### `code_common/tools.py`

- Add `request_tools` registration (meta category)
- Add `TIER_1_TOOLS` constant
- Add `COMPACT_TOOL_MENU` pre-computed string
- Add `_select_relevant_tools(user_message, summary, keys)` function

## Dynamic Doc Description Injection

`_inject_dynamic_doc_descriptions()` still runs on whichever tools end up in the final `tools_config`. No change needed — it operates on the filtered list regardless of how it was produced.

## Search-Intent Auto-Detection Interaction

Current behavior: if search intent detected, force `enable_tool_use=true` and inject web search tools.

New behavior:
- If `tool_mode == "none"` and search intent detected → upgrade to `tool_mode = "hybrid"` (frontend)
- If `tool_mode` is anything else → no change needed (smart/hybrid will select search tools naturally)
- The `mergeWebSearchTools()` function still operates in "manual" mode to inject search tools into the user's selection

## Implementation Tasks

### Phase 1: Core Infrastructure
1. Add `request_tools` to `code_common/tools.py` with meta category
2. Add `TIER_1_TOOLS` constant
3. Add `COMPACT_TOOL_MENU` pre-computed string
4. Add `_select_relevant_tools()` function using `VERY_CHEAP_LLM[0]`
5. Refactor `_get_enabled_tools()` to dispatch on `tool_mode`
6. Add zero-cost `request_tools` handling in `_run_tool_loop()`

### Phase 2: UI
7. Replace checkbox with `<select>` in `interface/interface.html`
8. Update `interface/chat.js`: settings persistence, show/hide selectpicker
9. Update `interface/common-chat.js`: payload, search-intent interaction
10. Update `interface/common.js`: `getOptions()` reads new field

### Phase 3: Backward Compatibility & Polish
11. Add legacy `enable_tool_use` → `tool_mode` mapping in backend
12. Handle existing conversations with old settings format
13. Update documentation

## Files to Modify

| File | Changes |
|------|---------|
| `code_common/tools.py` | `request_tools` registration, `TIER_1_TOOLS`, `COMPACT_TOOL_MENU`, `_select_relevant_tools()` |
| `Conversation.py` | Refactor `_get_enabled_tools()`, zero-cost expansion in `_run_tool_loop()` |
| `interface/interface.html` | Replace checkbox with `<select id="settings-tool_mode">`, hide selectpicker conditionally |
| `interface/chat.js` | Read/write `tool_mode`, show/hide selectpicker, defaults |
| `interface/common-chat.js` | Payload includes `tool_mode`, search-intent upgrades mode |
| `interface/common.js` | `getOptions()` includes `tool_mode` |
| `documentation/features/tool_calling/README.md` | Document new modes |

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Smart Select LLM picks wrong tools | Hybrid mode has `request_tools` fallback. Fail-open to tiered. |
| `request_tools` called excessively | Limit to 2 expansions per turn. After 2, all remaining tools loaded. |
| Selection LLM timeout | 5-second timeout. On failure, fall back to TIER_1_TOOLS. |
| Legacy clients send old format | Backward compat mapping in `_get_enabled_tools()`. |
| User confusion about modes | Tooltip on each option explaining trade-off. Default (hybrid) just works. |

## Token Budget Summary

| Mode | `tools` param | Preamble | Selection call | Total overhead |
|------|--------------|----------|---------------|---------------|
| None | 0 | 0 | 0 | 0 |
| Tiered | ~2,500 | ~500 | 0 | ~3,000 |
| Smart | ~3,000-4,500 | ~500 | ~2,500 in + ~100 out | ~3,500-5,100 |
| Hybrid | ~3,500-5,000 | ~500 | ~2,500 in + ~100 out | ~4,000-5,600 |
| Manual (all) | ~14,200 | ~500 | 0 | ~14,700 |

Hybrid saves **~10,000 tokens per turn** vs current all-tools-on behavior.
