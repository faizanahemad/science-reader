# Multi-Select Message Actions

A floating action bar that appears when one or more message checkboxes are ticked, providing batch operations on selected messages.

---

## Motivation

Every message has a checkbox (`history-message-checkbox`) that previously only supported "use as context" for the next send. Users often want to operate on groups of messages — delete irrelevant exchanges, hide old content, copy conversations for notes, or run LLM analysis on a subset. Repeating per-message dropdown actions N times is tedious.

## UI Flow

### Desktop
1. User clicks checkbox on one or more messages → messages highlight blue
2. Floating action bar appears at top of `#chatView`: `✓ N selected | 📋 Copy | 🗑 Delete | 👁 Hide | ⋯ More | ×`
3. Click action → executes on all selected messages
4. Bar disappears when all unchecked, "×" clicked, or destructive action completes

### Mobile
1. User taps checkbox (or taps card header when multi-select is already active)
2. Floating action bar appears at bottom (above input area, `position: fixed; bottom: 60px`)
3. "More" opens as **dropup** menu (above the bar)
4. Dropdown menu has `max-height: 50vh` with scroll to prevent viewport overflow

### Header-Tap Toggle
When at least one message is already checked (multi-select mode is active), tapping anywhere on a card header toggles that message's checkbox — providing a larger touch target than the small checkbox alone. When no messages are checked, header taps behave normally (triggering `handleMessageFocus`).

### Dismiss
- "×" button unchecks all checkboxes and hides the bar
- `Escape` key does the same
- After destructive actions (delete, hide), bar auto-dismisses

## Actions

| Action | Primary/More | Behavior |
|--------|-------------|----------|
| **Copy as Markdown** | Primary | Concatenates messages as `**Sender:** text`, copies to clipboard. Uses `navigator.clipboard` with textarea fallback for non-HTTPS. |
| **Delete Selected** | Primary | Confirm dialog → `POST /batch_delete_messages/<conv_id>` → refreshes chat view |
| **Hide Selected** | Primary | `POST /batch_hide_messages/<conv_id>` → refreshes chat view. Messages can be un-hidden via existing per-message toggle. |
| **Summarize** | More | Concatenates messages, calls `TempLlmManager.executeAction('summarize_selection', ...)` → opens temp LLM modal with streaming summary |
| **Ask Question About** | More | Keeps checkboxes checked (as context), focuses input with "Ask about the selected messages..." placeholder. User types question, existing send flow handles the rest. |
| **Run Preamble** | More (submenu) | Curated list of prompts. Selection calls TempLlmManager with `action_type: 'run_preamble'` + `preamble_name`. Backend loads prompt via `get_prompt(name)`. |
| **Fork from Last Selected** | More | Gets `Math.max(selectedIndices)`, calls existing `POST /fork_conversation/<conv_id>/<index>`, navigates to fork |
| **Use as Context** | More | Same as "Ask Question About" but without focusing input — just shows toast "N messages set as context" |

### Special Behaviors
- **Use as Context** and **Ask Question About** are the only actions that keep checkboxes checked after dismissing the bar (the send flow needs them checked)
- **Summarize** and **Run Preamble** open the existing Temp LLM modal (streaming, multi-turn follow-up supported)
- Placeholder text resets to default on next message send

## API Endpoints

### `POST /batch_delete_messages/<conversation_id>`

Request: `{ "message_ids": ["id1", "id2", ...] }`  
Response: `{ "deleted": N }`

Deletes all messages matching the given IDs in a single pass (one file lock, one save).

### `POST /batch_hide_messages/<conversation_id>`

Request: `{ "message_ids": ["id1", "id2", ...], "show_hide": "hide"|"show" }`  
Response: `{ "hidden": N }`

Sets `show_hide` field on matching messages in a single pass.

### Extended: `POST /temporary_llm_action`

Two new `action_type` values:
- `"summarize_selection"` — summarizes the `selected_text` (concatenated messages)
- `"run_preamble"` — uses `preamble_name` field to load a named prompt from `prompts.py` as system prompt, applies it to `selected_text`

New optional field: `preamble_name` (string) — name of the prompt template to load.

## Implementation Details

### Frontend: `MultiSelectManager` (common-chat.js)

Global object managing selection state:
- `_ids[]`, `_indices[]` — current selection
- `_sync()` — re-queries all checked checkboxes, updates bar
- `clearAll()` — unchecks all, removes highlights, hides bar
- `getSelectedTexts()` — returns messages as markdown strings in DOM order
- `_handleAction(action)` — dispatches to appropriate handler
- `_runPreamble(name)` — sets `TempLlmManager.preambleName` and calls `executeAction`
- `init()` — injects bar HTML, binds all event handlers

### Backend: `Conversation.py`

New methods:
- `delete_messages_batch(message_ids)` — filters messages list by ID set, saves
- `batch_show_hide_messages(message_ids, show_hide)` — sets field on matching messages, saves
- `temporary_llm_action(**kwargs)` — accepts `preamble_name` via kwargs for `run_preamble` action

### CSS: `workspace-styles.css`

- `.message-selected` — blue background + left border
- `#multi-select-bar` — sticky top, flex row, gap spacing
- Mobile: fixed bottom positioning, dropup menu, max-height scroll
- `.has-selection-bar` on `#chatView` for scroll-padding

### Conflict Avoidance

- **ContextMenuManager** (right-click on text selection) is completely separate — operates on text within a single message, not whole messages
- **handleMessageFocus** (card click) is suppressed when multi-select is active to prevent conflicts
- Existing checkbox gathering in the send flow is unchanged — it still reads all `.history-message-checkbox:checked` on send

## Available Preambles for Run Preamble

| ID | Label |
|----|-------|
| `engineering_excellence_prompt` | ⭐ Engineering Excellence |
| `more_related_questions_prompt` | ❓ Follow-up Questions |
| `general_chain_of_density_prompt` | 📝 Dense Summary |
| `preamble_argumentative` | ⚖️ Argumentative Analysis |
| `preamble_cot` | 🔗 Chain of Thought |
| `improve_code_prompt` | 💻 Improve Code |

## Files Modified

- `interface/common-chat.js` — MultiSelectManager, action bar, handlers, header-tap, multi-select guard on handleMessageFocus
- `interface/workspace-styles.css` — selection highlight, bar styles, mobile responsive
- `interface/temp-llm-manager.js` — `preamble_name` in request body, new ACTION_TITLES
- `Conversation.py` — `delete_messages_batch`, `batch_show_hide_messages`, `summarize_selection` prompt, `run_preamble` handling, `**kwargs`
- `endpoints/conversations.py` — `/batch_delete_messages`, `/batch_hide_messages`
- `endpoints/doubts.py` — `preamble_name` extraction and pass-through
