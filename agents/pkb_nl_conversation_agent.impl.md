# PKBNLConversationAgent — Implementation Details

## Architecture

```
User: /pkb add reminder to buy gift on July 20th
  |
parseMessageForCheckBoxes.js
  -> checkboxes["pkb_nl_command"] = "add reminder to buy gift on July 20th"
  -> messageText = "" (stripped)
  |
Conversation.reply()
  -> Detects pkb_nl_command BEFORE use_pkb read (timing bug fix)
  -> Overrides: field="PKBNLConversationAgent", use_pkb=False, enable_tool_use=False, etc.
  -> Restores messageText = nl_command_text
  |
get_preamble(field="PKBNLConversationAgent")
  -> Creates PKBNLConversationAgent(keys, model, user_email)
  |
Agent dispatch (line ~9852)
  -> agent.nl_command_text = _pkb_nl_command_text
  -> agent.tool_response_waiter = query["_tool_response_waiter"]
  -> main_ans_gen = agent(prompt, system=preamble, stream=True)
  |
PKBNLConversationAgent.__call__()
  -> Extracts conversation context from prompt
  -> Calls _run_nl_agent_streaming(nl_command, conversation_context)
    -> PKBNLAgent.process_streaming() (generator yielding event dicts)
  |
  +-- If result.needs_user_input (NL agent uncertain):
  |     -> Yields question text
  |     -> Yields {"type": "tool_input_request", "tool_name": "pkb_propose_memory", ...}
  |     -> Calls tool_response_waiter(tool_id, timeout=120)
  |     -> On user confirmation: _add_confirmed_claims() -> adds each claim via StructuredAPI
  |     -> Yields status per claim (checkmark/cross)
  |
  +-- Standard path (streaming):
        -> Iterates streaming events from process_streaming()
        -> Yields formatted text per action (emoji + summary):
           "🔍 Searching memories...", "✅ Added (ID: ...)",
           "✏️ Edited ...", "🗑️ Deleted ...", "⚠️ Parse error..."
        -> Yields final response + optional actions summary + warnings
  |
Conversation.reply() streaming loop (line ~10398)
  -> Passes dict events (tool_input_request) through to frontend
  -> Wraps string chunks in {"text": ..., "status": ...}
```

## Context Module Overrides

When `/pkb` is detected, these checkboxes are overridden in `reply()` BEFORE PKB retrieval:

| Checkbox | Value | Effect |
|---|---|---|
| `field` | `"PKBNLConversationAgent"` | Routes to PKB agent |
| `use_pkb` | `False` | Skips PKB retrieval (agent does its own) |
| `perform_web_search` | `False` | Skips web search |
| `googleScholar` | `False` | Skips Google Scholar |
| `enable_previous_messages` | `"3"` | Short history (3 turns) |
| `enable_tool_use` | `False` | Disables tool loop (agent has own) |
| `messageText` | Restored from nl_command | So prompt template includes it |

## Interactive pkb_propose_memory Flow

### NLCommandResult Changes (nl_agent.py)

Added fields:
- `needs_user_input: bool = False` — signals the result requires user review
- `proposed_claims: List[Dict] = []` — pre-filled claims for the proposal modal

When `PKBNLAgent.process()` encounters `ask_clarification` action:
- If claims were already added: extracts proposal data from add_claim action inputs
- If no claims yet: extracts a basic proposal from the user's original command text
- Returns `NLCommandResult(needs_user_input=True, proposed_claims=[...])` instead of a plain text question

### Two Paths for Interactive Proposals

**Path 1: `/pkb` slash command (agent path)**
1. `PKBNLConversationAgent.__call__` detects `result.needs_user_input`
2. Generates a unique `tool_id` (e.g. `pkb_propose_abc123`)
3. Yields `{"type": "tool_input_request", "tool_name": "pkb_propose_memory", "ui_schema": {...}}`
4. Streaming loop passes it through (line ~10398 checks for `tool_input_request` type)
5. Frontend `renderStreamingResponse` -> `ToolCallManager.handleToolInputRequest()` -> shows modal
6. User edits and submits via `/tool_response` endpoint
7. `tool_response_waiter(tool_id)` returns user data
8. Agent calls `_add_confirmed_claims()` to save each confirmed claim

**Path 2: Main LLM tool call (tool loop path)**
1. Main LLM calls `pkb_nl_command` tool
2. `handle_pkb_nl_command` runs `PKBNLAgent.process()`
3. If `result.needs_user_input`: returns `ToolCallResult(needs_user_input=True, tool_name="pkb_propose_memory", ui_schema=...)`
4. Tool loop (line ~6950) detects `needs_user_input`, yields `tool_input_request` SSE
5. Frontend shows modal, user responds
6. Tool loop receives response, formats as tool result for the LLM
7. LLM sees confirmed claims and can make follow-up tool calls (e.g. `pkb_add_claim`)

### UI Modal (tool-call-manager.js)

`handleToolInputRequest` renders editable cards when `toolName === 'pkb_propose_memory'`:
- Each claim gets a card with: textarea (text), type dropdown, date fields (from/to), tags input, entities input, context input, remove button
- `_collectMemoryProposalResponse()` gathers edited data on submit
- Submit validates at least one claim remains
- Response format: `{ claims: [{text, claim_type, valid_from, valid_to, tags, entities, context}] }`

## Conversation Context Extraction

The agent receives the full assembled prompt (from `prompts.chat_slow_reply_prompt`). It extracts relevant context sections:

- Conversation summary (looks for `<conversation_summary>`, `<summary>`, or `Conversation Summary:` markers)
- Previous messages (looks for `<previous_messages>`, `<conversation_history>`, or `Previous Messages:` markers)

Context is capped at 4000 chars and appended to the NL command as reference material.

## Inner NL Agent Integration

The conversation agent delegates to `PKBNLAgent` (from `truth_management_system/interface/nl_agent.py`):

1. Gets user-scoped `StructuredAPI` via `get_pkb_api_for_user(email)`
2. Creates `PKBNLAgent(api, keys, model)`
3. Enriches NL command with conversation context
4. Calls `agent.process_streaming(enriched_command)` which yields event dicts in real-time
5. `__call__` iterates over streaming events and yields formatted text to the user (e.g. "🔍 Searching memories...", "✅ Added (ID: ...)")

The inner agent's `process_streaming()` is a generator variant of `process()`. It yields event dicts with a `type` field:
- `llm_call_start`, `thinking` ... iteration-level progress
- `action_start`, `action_result` ... per-action progress (name, success/fail, tool result data)
- `parse_error`, `unknown_action` ... error events
- `final_response`, `ask_clarification` ... terminal events (include `NLCommandResult`)
- `timeout`, `error`, `max_iterations` ... failure terminal events

**Backward compatibility:** `process()` is unchanged and still used by REST endpoint (`POST /pkb/nl_command`), MCP tool (`mcp_server/pkb.py`), and LLM tool handler (`code_common/tools.py`). The streaming path is additive.

The inner agent runs a JSON action loop (up to 5 iterations, 30s timeout) and can:
- Search, add, edit, delete, pin claims
- Add entities and tags
- Ask clarification questions (now returns interactive proposal)
- Return a natural language response

## Files Modified (Phase 3)

| File | Changes |
|---|---|
| `Conversation.py` | Bug fix: moved /pkb override before use_pkb read; fixed enable_tools->enable_tool_use; pass tool_response_waiter to agent |
| `interface/interface.html` | Added pkb_nl_command (selected), pkb_delete_claim, pkb_propose_memory to tool selector |
| `interface/chat.js` | Added tools to categoryDefaults.pkb; pkb_nl_command in resetSettingsToDefaults defaults |
| `interface/common-chat.js` | Skip checkMemoryUpdates for /pkb commands |
| `code_common/tools.py` | DEFAULT_ENABLED_TOOLS constant; pkb_propose_memory interactive tool; handle_pkb_nl_command bubbles up needs_user_input |
| `interface/tool-call-manager.js` | pkb_propose_memory modal rendering, form collection, submit handling; PKB STATUS_MESSAGES/ICONS |
| `truth_management_system/interface/nl_agent.py` | NLCommandResult.needs_user_input + proposed_claims; ask_clarification returns interactive proposal; `process_streaming()` generator variant of `process()` yielding event dicts |
| `agents/pkb_nl_conversation_agent.py` | tool_response_waiter attr; yield tool_input_request SSE; _add_confirmed_claims helper; `_run_nl_agent_streaming()` replaces `_run_nl_agent()`; `__call__` iterates streaming events and yields formatted text |
