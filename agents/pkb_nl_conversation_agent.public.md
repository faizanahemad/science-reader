# PKBNLConversationAgent — Public Interface

## Purpose

Conversation-compatible agent that wraps the PKB NL agent for `/pkb` and `/memory` slash commands. Integrates into `Conversation.reply` via the standard agent dispatch (field = `"PKBNLConversationAgent"`).

## Class: `PKBNLConversationAgent(Agent)`

### Constructor

```python
PKBNLConversationAgent(
    keys: dict,                    # API keys (passed to inner PKBNLAgent)
    model_name: str = "openai/gpt-4o-mini",  # LLM model for NL processing
    user_email: str = "",          # User email for PKB scoping
    detail_level: int = 1,         # Interface compat (unused)
    timeout: int = 60,             # Max execution time (seconds)
)
```

### Key Attributes

- `nl_command_text: str | None` — Set by `Conversation.reply` before `__call__`. Contains the raw NL command text from the slash command (e.g. `"add a reminder to buy gift on July 20th"`).
- `tool_response_waiter: Callable | None` — Set by `Conversation.reply` before `__call__`. Function to wait for user tool responses (for interactive `pkb_propose_memory` modal). Signature: `(tool_id: str, timeout: int) -> dict | None`.

### `__call__(text, images, temperature, stream, max_tokens, system, web_search)`

Standard agent interface. Yields streaming text chunks AND dict events.

The agent now streams intermediate progress to the UI in real-time. `__call__` yields formatted status updates per action as they happen (e.g. "🔍 Searching memories...", "✅ Added (ID: ...)", "✏️ Edited ...", "🗑️ Deleted ...").

1. Status message: "Processing your memory command..."
2. **Streaming action progress** (new): As the NL agent processes, `__call__` iterates over `PKBNLAgent.process_streaming()` events and yields formatted text per action in real-time
3. **If NL agent is uncertain** (needs_user_input=True):
   - Yields the question/message text
   - Yields `{"type": "tool_input_request", "tool_name": "pkb_propose_memory", "ui_schema": {...}}` dict — frontend shows the memory proposal modal
   - Waits for user response via `tool_response_waiter`
   - Adds user-confirmed claims to PKB, yielding status per claim
4. **Standard path** (NL agent is confident):
   - Intermediate action status updates streamed as they happen
   - Main NL response from `PKBNLAgent.process_streaming()`
   - Optional: collapsible operations summary (if multiple actions taken)
   - Optional: warnings

Interactive proposals still work the same way: `ask_clarification` triggers `tool_input_request` which shows the proposal modal.

### How It's Triggered

1. User types `/pkb <text>` or `/memory <text>`
2. `parseMessageForCheckBoxes.js` sets `checkboxes["pkb_nl_command"]` = `<text>`
3. `Conversation.reply()` detects this (BEFORE PKB retrieval), overrides checkboxes:
   - `field = "PKBNLConversationAgent"`
   - `use_pkb = False` (agent does its own PKB ops)
   - `perform_web_search = False`
   - `enable_previous_messages = "3"` (short history)
   - `enable_tool_use = False`
4. `get_preamble()` creates the agent instance
5. `reply()` sets `agent.nl_command_text` and `agent.tool_response_waiter` before calling `agent(prompt, ...)`

### Interactive Memory Proposal Flow

When the NL agent is uncertain (calls `ask_clarification`), the agent yields a `tool_input_request` SSE event with `tool_name="pkb_propose_memory"`. The streaming loop in `Conversation.reply()` (line ~10398) passes this dict through to the frontend. The frontend's `renderStreamingResponse` handles `tool_input_request` events and shows the modal via `ToolCallManager.handleToolInputRequest()`.

This works for both paths:
- **`/pkb` slash command path**: Agent yields the event directly
- **Main LLM tool path**: `handle_pkb_nl_command` returns `ToolCallResult(needs_user_input=True)` which the tool loop handles

### Integration Points

- **Conversation.py** line 62: import
- **Conversation.py** `get_preamble()`: field registration
- **Conversation.py** `reply()` line ~7172: checkbox overrides (moved before PKB retrieval)
- **Conversation.py** line ~9852: nl_command_text + tool_response_waiter injection
