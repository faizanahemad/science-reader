# Plan: PKB NL Tool UI Enhancements & Default Tools Config

**Status:** PARTIAL — Group A (bug fixes) done. Group B interactive tool architecture partially done (implemented as pkb_propose_memory instead of pkb_propose_updates; B7-B9 UI not wired).

**Date**: 2026-03-10
**Status**: Draft
**Phase**: Phase 3 of PKB enhancements

## Goals

1. Add `pkb_nl_command` and `pkb_delete_claim` to the UI tool selector and category defaults
2. Fix PKB search timing bug when `/pkb` slash command is used
3. Fix `enable_tools` vs `enable_tool_use` key mismatch bug
4. Skip `checkMemoryUpdates` for `/pkb` and `/memory` commands
5. Create a `DEFAULT_ENABLED_TOOLS` config constant in JS
6. Enable `pkb_nl_command` by default for the main LLM
7. Create `pkb_propose_updates` interactive tool for PKB claim confirmation (works in both /pkb agent and main LLM tool calling contexts)
8. Support bubbling interactive tool requests from nested `pkb_nl_command` back to the main UI

## Requirements

### R1: Tool Selector UI Completeness
- `pkb_nl_command` and `pkb_delete_claim` must appear in the "Knowledge Base (PKB)" optgroup in `#settings-tool-selector`
- `chat.js` `categoryDefaults.pkb` must include both tools
- `pkb_nl_command` must be `selected` by default (like `ask_clarification`)

### R2: Bug Fixes
- **PKB search timing**: The `/pkb` override at line 7240 sets `checkboxes["use_pkb"] = False` AFTER `use_pkb` is already read at line 7174. Fix: move the `/pkb` override block BEFORE the PKB retrieval check.
- **enable_tools key mismatch**: Line 7247 sets `checkboxes["enable_tools"] = False` but `_get_enabled_tools()` checks `checkboxes.get('enable_tool_use', False)`. Fix: change to `checkboxes["enable_tool_use"] = False`.

### R3: Skip checkMemoryUpdates for /pkb
- In `common-chat.js` line 3237, add `&& !options.pkb_nl_command` to the condition
- This prevents the automatic memory proposal flow from firing when user explicitly used the PKB NL agent

### R4: Default Tools Configuration
- Define `DEFAULT_ENABLED_TOOLS` array constant in `chat.js`
- Use it in `resetSettingsToDefaults()` (replace hardcoded `['ask_clarification']`)
- Use it in `buildSettingsStateFromControlsOrDefaults()` as fallback
- HTML `selected` attributes must match the constant
- Default list: `['ask_clarification', 'pkb_nl_command']`

### R5: PKB Propose Updates Interactive Tool
- New interactive tool `pkb_propose_updates` (category: "pkb", is_interactive: True)
- Works like `ask_clarification` — returns `ToolCallResult(needs_user_input=True, ui_schema={...})`
- ui_schema contains proposed claims with all fields (statement, type, domain, tags, dates, entities)
- ToolCallManager renders a memory-proposal-style modal for user review/edit
- User can accept, edit, or reject each proposal
- Response flows back through existing `/tool_response` endpoint

### R6: Interactive Tool Bubbling from pkb_nl_command
Architecture for enabling `pkb_nl_command` (when called by main LLM) to surface interactive modals:

**Design: Two-phase execution with callback injection**

1. **PKBNLAgent gets a `user_input_callback`**: When the NL agent needs user input (e.g., `propose_updates` action), it calls a callback function instead of returning immediately.

2. **Tool handler path** (main LLM calls `pkb_nl_command`):
   - `handle_pkb_nl_command` injects a `user_input_callback` backed by `threading.Event`
   - NL agent calls callback → callback creates Event, stores ui_schema, returns a sentinel
   - Tool handler detects sentinel and returns `ToolCallResult(needs_user_input=True, ui_schema=...)`
   - `_run_tool_loop` handles pause/resume as usual
   - On resume, tool handler gets user response, injects it back into NL agent state, re-runs remaining loop
   
   **Simpler alternative**: NL agent returns `NLCommandResult` with `needs_user_input=True` and `ui_schema`. Tool handler checks this and returns `ToolCallResult(needs_user_input=True, ...)`. On second call (with user response in args), tool handler creates new NL agent with the response context and continues.

3. **Agent wrapper path** (/pkb slash command, PKBNLConversationAgent):
   - PKBNLConversationAgent yields `tool_input_request` dict events from `__call__()`
   - Conversation.py `make_stream` normalizer already passes through dict events
   - The streaming loop in common-chat.js already handles `tool_input_request` events
   - Need to add `tool_response_waiter` to the agent context (passed via `query["_tool_response_waiter"]`)

**Recommended approach**: Two-phase NL agent execution:
- Phase 1: NL agent runs, may return `NLCommandResult(needs_user_input=True, ui_schema={...})`
- Wrapper (tool handler or agent) surfaces the modal and waits for user response
- Phase 2: NL agent re-runs with the original command + user's confirmed/edited data as additional context

This avoids coroutines and state preservation complexity. The NL agent is stateless between phases — the user's edited data simply becomes part of the input context for phase 2.

### R7: ToolCallManager UI for pkb_propose_updates
- New branch in `handleToolInputRequest()` for `toolName === 'pkb_propose_updates'`
- Renders memory-proposal-style form (reuse `showBulkProposalModal` pattern from pkb-manager.js)
- Each proposal shows: statement, claim_type, context_domain, tags, valid_from, valid_to, entities
- User can edit fields, toggle individual proposals on/off
- Submit collects confirmed proposals and sends via existing submitToolResponse flow

## Task List

### Group A: Bug Fixes & Quick Wins (no architecture changes)

**A1**: Fix `enable_tools` → `enable_tool_use` key mismatch (Conversation.py line 7247)
- Change `checkboxes["enable_tools"] = False` to `checkboxes["enable_tool_use"] = False`
- File: `Conversation.py`

**A2**: Fix PKB search timing bug (Conversation.py)
- Move the `/pkb` override block (lines 7225-7248) BEFORE the `use_pkb` read (line 7174)
- Or: re-read `use_pkb` from `checkboxes` after the override block
- File: `Conversation.py`

**A3**: Add `pkb_nl_command` and `pkb_delete_claim` to UI tool selector
- Add `<option>` elements to PKB optgroup in `interface.html` (after line 2428)
- Add `pkb_nl_command` with `selected` attribute
- File: `interface/interface.html`

**A4**: Update `categoryDefaults.pkb` in chat.js
- Add `pkb_nl_command` and `pkb_delete_claim` to the pkb array (line 661)
- File: `interface/chat.js`

**A5**: Create `DEFAULT_ENABLED_TOOLS` config and update reset/defaults
- Add constant in `chat.js`: `var DEFAULT_ENABLED_TOOLS = ['ask_clarification', 'pkb_nl_command'];`
- Update `resetSettingsToDefaults()` (line 1228) to use constant
- Update `buildSettingsStateFromControlsOrDefaults()` to use constant as fallback for enabled_tools
- File: `interface/chat.js`

**A6**: Skip checkMemoryUpdates for /pkb and /memory
- Add `&& !options.pkb_nl_command` condition at line 3237 in common-chat.js
- File: `interface/common-chat.js`

### Group B: Interactive PKB Propose Updates Tool (architecture work)

**B1**: Extend `NLCommandResult` with interactive fields
- Add `needs_user_input: bool = False` and `ui_schema: Optional[dict] = None` to `NLCommandResult`
- File: `truth_management_system/interface/nl_agent.py`

**B2**: Add `propose_updates` action to PKBNLAgent
- New terminal action in the NL agent's action loop
- When agent wants user confirmation, it returns `NLCommandResult(needs_user_input=True, ui_schema={proposals: [...]})`
- Add to system prompt action list
- File: `truth_management_system/interface/nl_agent.py`

**B3**: Register `pkb_propose_updates` as interactive tool
- `@register_tool(name="pkb_propose_updates", is_interactive=True, category="pkb")`
- Handler returns `ToolCallResult(needs_user_input=True, ui_schema=args)`
- File: `code_common/tools.py`

**B4**: Update `pkb_nl_command` tool handler for two-phase execution
- Phase 1: Run NL agent. If result has `needs_user_input=True`, return `ToolCallResult(needs_user_input=True, ui_schema=result.ui_schema, tool_name="pkb_propose_updates")`
- The tool loop will show the modal, get user response, and call the tool again
- Phase 2: When called with user's confirmed data, apply the confirmed proposals directly via PKB API
- File: `code_common/tools.py`

**B5**: Update PKBNLConversationAgent for interactive flow
- In `__call__()`, after calling `agent.process()`, check `result.needs_user_input`
- If True, yield `tool_input_request` event dict and wait via `tool_response_waiter`
- Apply confirmed proposals, then continue yielding the final message
- File: `agents/pkb_nl_conversation_agent.py`

**B6**: Pass `tool_response_waiter` to PKBNLConversationAgent
- In Conversation.py, when agent is PKBNLConversationAgent, pass `query.get("_tool_response_waiter")` as kwarg
- File: `Conversation.py`

**B7**: Add `pkb_propose_updates` UI rendering to ToolCallManager
- New branch in `handleToolInputRequest()` for `toolName === 'pkb_propose_updates'`
- Render proposal form with editable fields (statement, type, domain, tags, dates)
- Collect confirmed/edited proposals on submit
- File: `interface/tool-call-manager.js`

**B8**: Add `pkb_propose_updates` to tool selector HTML
- Add option to PKB optgroup (not selected by default — it's an internal tool used by pkb_nl_command)
- File: `interface/interface.html`

**B9**: Handle `pkb_propose_updates` response format in `_run_tool_loop`
- Add formatting branch alongside `ask_clarification` at line 6973 for `pkb_propose_updates`
- File: `Conversation.py`

### Group C: Documentation

**C1**: Update `agents/pkb_nl_conversation_agent.impl.md` with interactive flow details
**C2**: Update `truth_management_system/interface/nl_agent.py` impl/public docs
**C3**: Update `documentation/features/slash_command_system.md`

## Implementation Order

1. **A1, A2** — Bug fixes (critical, no dependencies)
2. **A3, A4, A5** — UI tool selector + defaults config (parallel)
3. **A6** — Skip checkMemoryUpdates
4. **B1, B2** — NL agent extensions (foundation)
5. **B3** — Register interactive tool
6. **B4** — Two-phase pkb_nl_command handler
7. **B5, B6** — Agent wrapper interactive flow
8. **B7** — ToolCallManager UI rendering
9. **B8, B9** — Tool selector + loop response handling
10. **C1-C3** — Documentation

## Alternatives Considered

### For interactive tool bubbling:
1. **Generator/coroutine pattern**: Make PKBNLAgent a generator that yields pause requests. Rejected — too invasive, changes the synchronous `process()` API that multiple callers depend on.
2. **Callback injection**: Inject a `user_input_callback` that the NL agent calls. More complex threading. Rejected in favor of simpler two-phase approach.
3. **Two-phase execution** (chosen): NL agent returns a result indicating it needs user input. Wrapper re-runs with confirmed data. Stateless between phases. Simple, testable.

### For default tools config:
1. **Backend-driven**: Serve defaults via API. Rejected — unnecessary complexity for current needs.
2. **JS constant + HTML selected** (chosen): Simple, matches existing patterns, single source of truth in JS.

## Files Modified

| File | Change Type |
|------|-------------|
| `Conversation.py` | Bug fix (lines 7174, 7247), pass tool_response_waiter to agent, handle pkb_propose_updates response |
| `interface/interface.html` | Add pkb_nl_command, pkb_delete_claim, pkb_propose_updates to tool selector |
| `interface/chat.js` | DEFAULT_ENABLED_TOOLS constant, update categoryDefaults, resetSettingsToDefaults |
| `interface/common-chat.js` | Skip checkMemoryUpdates for /pkb |
| `interface/tool-call-manager.js` | Render pkb_propose_updates modal |
| `code_common/tools.py` | Register pkb_propose_updates tool, update pkb_nl_command handler |
| `truth_management_system/interface/nl_agent.py` | Extend NLCommandResult, add propose_updates action |
| `agents/pkb_nl_conversation_agent.py` | Interactive flow support |
| `documentation/` | Updated docs |
