# Multi-Select Message Actions

**Status:** DONE (June 2026)
**Created:** 2026-06-13  
**Scope:** A floating action bar that appears when one or more message checkboxes are ticked, providing batch operations on selected messages. Works on desktop and mobile without conflicting with the existing LLM right-click context menu.

**Related features:** Existing `history-message-checkbox` on every message, existing `ContextMenuManager` (LLM right-click), existing `Fork from here` per-message action.

**Non-goals:** Replacing the LLM right-click context menu, drag-to-reorder messages, inline annotation/highlighting within message text.

---

## 1. Background & Motivation

Every message in the chat view has a checkbox (`history-message-checkbox`) that currently only supports "use as context" for the next query. This is underutilized — users often want to operate on groups of messages: delete a chunk of irrelevant back-and-forth, collapse old content, copy an exchange for notes, or run LLM analysis on a subset of the conversation.

The current per-message dropdown (⋮ menu) only operates on individual messages. For batch operations, users must repeat the same action N times — tedious and error-prone.

---

## 2. Initial Ideas Considered

All actions that were brainstormed with pros/cons:

| # | Action | Verdict | Reason |
|---|--------|---------|--------|
| 1 | Use as Context | **Selected** | Already exists via checkboxes, just needs surfacing in the action bar |
| 2 | Delete Selected | **Selected** | High value, low effort — batch delete avoids N individual confirmations |
| 3 | Collapse/Hide Group | **Selected** | Sets `show_hide: "hide"` on all selected — declutters long conversations |
| 4 | Move Up/Down N steps | Deferred | Complex edge cases with pair-awareness and alternation preservation |
| 5 | Summarize Together | **Selected** | Run LLM on selected messages, show summary in modal |
| 6 | Ask Question About | **Selected** | Prepopulate context with selected messages + focus input for question |
| 7 | NQS on Selection | Deferred | Overlaps with Ask Question About; can add later |
| 8 | Run Preamble/Prompt | **Selected** | Apply any prompt template from prompts.py to selected messages |
| 9 | Copy as Markdown | **Selected** | Pure frontend, quick export for notes/sharing |
| 10 | Fork from Last Selected | **Selected** | Calls existing fork endpoint with index of last selected message |
| 11 | Add to Memory Pad | Deferred | Requires distillation quality tuning |
| 12 | Create Artefact | Deferred | Needs artefact naming UX |
| 13 | Compare Responses | Deferred | Needs diff UI, very niche |
| 14 | Re-ask with Current Settings | Deferred | Confusing UX around which messages are re-asked |
| 15 | Tag/Label Messages | Deferred | Needs tag management schema |
| 16 | Export to Document | Deferred | Heavy formatting work |

**Final selected actions (8):** Use as Context, Delete Selected, Collapse/Hide, Summarize, Ask Question About, Run Preamble, Copy as Markdown, Fork from Last Selected.

---

## 3. Design Decisions

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | How to select messages? | **Existing checkboxes** + tap/click on message header toggles checkbox | Explicit, works on all devices, no gesture conflicts |
| 2 | How to open action menu? | **Floating action bar** appears when ≥1 checkbox is ticked | Like Gmail/Photos — device-agnostic, no right-click needed |
| 3 | Bar position? | **Top of `#chatView`** on desktop, **bottom** (above input) on mobile | Thumb-reachable on mobile, visible on desktop |
| 4 | Conflict with LLM right-click? | **None** — they serve different purposes | Right-click = text selection actions, Action bar = whole-message batch ops |
| 5 | "More" dropdown on mobile | **Opens upward (dropup)** to avoid going below screen | Standard mobile pattern for bottom-anchored menus |
| 6 | Dismiss behavior | **"×" unselects all messages** and hides bar | Clean state reset, no orphaned selections |
| 7 | Which actions in primary bar? | Copy, Delete, Hide, + "More" overflow | Most frequent/quick actions visible; LLM-heavy actions in overflow |
| 8 | "More" overflow contents | Summarize, Ask About, Run Preamble, Fork, Use as Context | These require more thought/interaction, appropriate for secondary menu |
| 9 | Visual feedback for selected | **Light blue background + left border** on checked message cards | Clear visual grouping without being jarring |
| 10 | Run Preamble sub-menu | Shows list of available preambles from `/list_preambles` endpoint | Needs new lightweight endpoint to list prompt template names |
| 11 | Settings dependency | **None** — always available when checkboxes are present | No new setting needed; checkboxes are already part of the UI |
| 12 | Long-press on mobile header | Toggles checkbox (alternative to tapping small checkbox) | Larger touch target for fat fingers |

---

## 4. UX Flow

### Desktop
1. User clicks checkbox on one or more messages
2. Floating action bar slides in at top of `#chatView`: `✓ N selected | 📋 Copy | 🗑 Delete | 👁 Hide | ⋯ More | ×`
3. Click action → executes on all selected messages
4. Bar disappears on: all unchecked, "×" clicked, or destructive action completes

### Mobile
1. User taps checkbox or long-presses message header
2. Floating action bar appears at **bottom** (above input area)
3. "More" opens as **dropup** menu (above the bar) so it doesn't go off-screen
4. Same dismiss behavior as desktop

### Action Details

| Action | Behavior |
|--------|----------|
| **Copy as Markdown** | Concatenate selected messages as `**User:** text\n\n**Assistant:** text\n\n...`, copy to clipboard, show toast |
| **Delete Selected** | Confirm dialog ("Delete N messages?"), call batch delete endpoint, refresh chat view |
| **Collapse/Hide** | Set `show_hide: "hide"` on all selected via endpoint, refresh chat view, show toast "N messages hidden" |
| **Summarize** | POST selected message IDs → backend runs LLM summary → display in temp-LLM modal (reuse existing infrastructure) |
| **Ask Question About** | Uncheck all, set selected message IDs as context (same as existing checkbox behavior), focus input area, show toast "N messages set as context" |
| **Run Preamble** | Sub-menu lists available preambles. Selection sends message IDs + preamble name → backend → temp-LLM modal |
| **Fork from Last** | Call `POST /fork_conversation/{conv_id}/{max_selected_index}`, navigate to fork |
| **Use as Context** | Same as "Ask Question About" but without focusing input — just marks them for next send |

---

## 5. Technical Approach

### New Files
- None — all code goes into existing files

### Modified Files
- `interface/common-chat.js` — selection state management, action bar rendering, action handlers
- `interface/workspace-styles.css` — action bar CSS, selected-message highlight
- `endpoints/conversations.py` — batch delete, batch hide endpoints
- `prompts.py` — expose `list_preambles()` function (or new endpoint)

### Existing Infrastructure Reused
- `history-message-checkbox` — already on every message with `message-id` attribute
- `ContextMenuManager.tempLlmAction()` — for Summarize and Run Preamble results display
- `POST /fork_conversation/<conv_id>/<msg_index>` — for Fork from Last
- `showToast()` — for feedback
- `ConversationManager.setActiveConversation()` — for fork navigation

---

## 6. Granular Tasks

### Phase 1: Selection Infrastructure + Action Bar Shell

**Task 1.1: Selection state tracking**
- Add `MultiSelectManager` object (or extend in common-chat.js)
- Properties: `selectedMessageIds: []`, `selectedIndices: []`
- Listen to checkbox change events, update state
- Method: `getSelectedIds()`, `getSelectedIndices()`, `clearAll()`, `count()`

**Task 1.2: Visual highlight on selected messages**
- CSS class `.message-selected` on parent `.card` when checkbox is checked
- Style: light blue background (`#e3f2fd`), 3px left border (`#1976d2`)
- Toggle class on checkbox change

**Task 1.3: Floating action bar HTML + CSS**
- Fixed-position bar (top on desktop, bottom on mobile)
- Structure: `<div id="multi-select-bar">` with count label, action buttons, dismiss "×"
- CSS: z-index above chat, slide-in animation, responsive positioning
- Media query: `@media (max-width: 768px)` → bottom positioning

**Task 1.4: Show/hide action bar logic**
- Show bar when `count() >= 1`
- Hide + `clearAll()` when "×" clicked
- Hide when last checkbox unchecked
- Update count label on every change

**Task 1.5: Header tap to toggle checkbox (mobile UX)**
- Click/tap on `.card-header` (outside buttons/dropdown) toggles the message's checkbox
- Long-press on mobile also toggles (300ms threshold)

### Phase 2: Simple Actions (Frontend-only or lightweight backend)

**Task 2.1: Copy as Markdown**
- Collect text from selected message cards
- Format as `**Sender:** text\n\n` per message
- `navigator.clipboard.writeText()`, toast "Copied N messages"

**Task 2.2: Delete Selected**
- Confirm dialog: "Delete N messages? This cannot be undone."
- On confirm: POST `/batch_delete_messages/<conv_id>` with `{ message_ids: [...] }`
- Backend: new endpoint that deletes messages by ID from the messages list, saves
- Refresh chat view on success

**Task 2.3: Collapse/Hide Group**
- POST `/batch_hide_messages/<conv_id>` with `{ message_ids: [...] }`
- Backend: sets `show_hide: "hide"` on matching messages, saves
- Refresh chat view, toast "N messages hidden"
- Note: messages can be un-hidden via existing show/hide toggle mechanism

**Task 2.4: Use as Context**
- Mark the checkboxes as checked (already are), trigger existing "use as context" flow
- Toast "N messages set as context for next message"
- Clear selection (bar disappears)

**Task 2.5: Fork from Last Selected**
- Get `Math.max(...selectedIndices)`
- Call `POST /fork_conversation/<conv_id>/<max_index>`
- Navigate to fork (reuse existing fork handler code)

### Phase 3: LLM-Powered Actions

**Task 3.1: Summarize Together**
- POST `/summarize_messages/<conv_id>` with `{ message_ids: [...] }`
- Backend: collect message texts, run through LLM with summary prompt
- Return summary text
- Display in temp-LLM modal (reuse `ContextMenuManager.showTempLlmModal()` or equivalent)

**Task 3.2: Ask Question About**
- Set selected messages as context (like Use as Context)
- Focus the input textarea
- Show placeholder text: "Ask about the selected messages..."
- Clear selection but keep context attached

**Task 3.3: Run Preamble submenu**
- "More → Run Preamble" opens a sub-dropdown listing available preambles
- Need `GET /list_preambles` endpoint (returns names of prompt templates from prompts.py)
- On selection: POST `/run_preamble_on_messages/<conv_id>` with `{ message_ids: [...], preamble: "name" }`
- Backend: collect texts, apply named preamble as system prompt, run LLM
- Display in temp-LLM modal

### Phase 4: Polish

**Task 4.1: "More" dropdown as dropup on mobile**
- Detect mobile (screen width or `isProbablyMobileDevice()`)
- Add `.dropup` class to the "More" button's dropdown container on mobile
- Ensure menu doesn't overflow viewport

**Task 4.2: Keyboard shortcut (desktop)**
- `Escape` while bar is visible → dismiss (clearAll)
- Optional: `Ctrl+A` in chat view → select all visible messages

**Task 4.3: Accessibility**
- Action bar has `role="toolbar"`, `aria-label="Message actions"`
- Buttons have `aria-label` descriptions
- Count announcement via `aria-live="polite"` region

---

## 7. API Endpoints (New)

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/batch_delete_messages/<conv_id>` | `{ message_ids: [] }` | `{ deleted: N }` |
| POST | `/batch_hide_messages/<conv_id>` | `{ message_ids: [] }` | `{ hidden: N }` |
| POST | `/summarize_messages/<conv_id>` | `{ message_ids: [] }` | `{ summary: "..." }` |
| POST | `/run_preamble_on_messages/<conv_id>` | `{ message_ids: [], preamble: "name" }` | `{ result: "..." }` |
| GET | `/list_preambles` | — | `{ preambles: ["name1", ...] }` |

Existing endpoints reused:
- `POST /fork_conversation/<conv_id>/<msg_index>` (already built)

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Action bar overlaps content | Users can't see messages behind it | Make bar compact (single row), semi-transparent background, or shift chat padding |
| Accidental batch delete | Data loss | Mandatory confirmation dialog with count |
| LLM actions slow on large selections | Poor UX, timeout | Show spinner in modal, limit to 20 messages max, truncate if needed |
| "More" dropdown clipped on mobile | Unusable actions | Dropup positioning + viewport boundary check |
| Checkbox state lost on chat refresh | Confusing | Accept this — selection is ephemeral, same as email clients |
| Conflict with existing checkbox "use as context" behavior | Double handling | "Use as Context" in action bar IS the same flow — just more explicit |

---

## 9. Implementation Order

```
Phase 1 (foundation) → Phase 2 (simple actions) → Phase 3 (LLM actions) → Phase 4 (polish)
```

Each phase is independently shippable. Phase 1 + Phase 2 gives immediate value. Phase 3 adds power-user features. Phase 4 is UX refinement.

Estimated effort: ~3-4 hours for Phases 1-2, ~2-3 hours for Phase 3, ~1 hour for Phase 4.

---

## 10. Critical Implementation Context

This section contains architectural details a coding agent needs to implement correctly.

### How "Use as Context" currently works

1. Each message has `<input type="checkbox" class="history-message-checkbox" message-id="...">` (line ~2492 of common-chat.js)
2. On send (line ~3434 of common-chat.js), all checked checkboxes are gathered into `history_message_ids[]`, checkboxes are unchecked, and IDs are merged into the `options` object via `mergeOptions(parsed_message, options)`
3. The `options` object (called `checkboxes` in `sendMessage` params) is sent as `requestBody.checkboxes` to the backend
4. Backend uses `history_message_ids` to include those messages as context for the LLM call
5. If `render_close_to_source` setting is on, the response is rendered near the checked messages in the DOM

**Key insight**: The "Use as Context" action in the multi-select bar should simply leave the checkboxes checked (they already are) and let the existing send flow handle it. Just show a toast and dismiss the bar.

### Move Up/Down existing pattern (common.js line ~2455)

The existing move handler already collects all checked checkboxes and moves them together:
```javascript
$(".history-message-checkbox:checked").each(function() {
    ids.push($(this).attr('message-id'));
    $(this).prop('checked', false);
});
ChatManager.moveMessagesUpOrDown(ids, direction);
```
This means multi-select move is already partially implemented. The action bar just needs to call this.

### TempLlmManager (for Summarize and Run Preamble)

- `TempLlmManager.openModal(action, selectedText, autoStream)` — opens modal, optionally auto-streams
- Endpoint: `POST /temporary_llm_action` in `endpoints/doubts.py` (line 215)
- Request body: `{ action_type, selected_text, user_message, message_id, message_text, conversation_id, history, with_context }`
- For multi-select Summarize/Preamble, we can pass concatenated message texts as `selected_text` and a new `action_type` like `"summarize_selection"` or `"run_preamble"`
- The temp LLM modal already handles streaming display

### Single delete endpoint (existing)

- `DELETE /delete_message_from_conversation/<conv_id>/<message_id>/<index>`
- For batch delete, either loop client-side or add a new batch endpoint (preferred — single save_local call)

### Show/hide endpoint (existing)

- `POST /show_hide_message_from_conversation/<conv_id>/<message_id>/<index>` with body `{ show_hide: "show"|"hide" }`
- Toggles a single message. For batch hide, either loop client-side (N requests) or add a batch endpoint.
- Messages with `show_hide: "hide"` are not rendered by the frontend.

### File locations

| What | File | Line(s) |
|------|------|---------|
| Checkbox HTML template | `common-chat.js` | ~2492 |
| Checkbox gathering on send | `common-chat.js` | ~3434-3445 |
| Move handler (multi-select aware) | `common.js` | ~2455-2475 |
| Single delete endpoint | `endpoints/conversations.py` | ~922-967 |
| TempLlmManager | `interface/temp-llm-manager.js` | full file (~500 lines) |
| Temp LLM endpoint | `endpoints/doubts.py` | ~215-290 |
| Preambles available | `prompts.py` | lines 66-93, 267-443 |
| ContextMenuManager | `interface/context-menu-manager.js` | full file (~600 lines) |
| Action dropdown per message | `common-chat.js` | ~2450-2490 |
| Message card structure | `common-chat.js` | ~2420-2500 (renderMessages) |
| `isProbablyMobileDevice()` | check for mobile detection utility |

### Preambles suitable for "Run Preamble" submenu

From `prompts.py`, these make sense on a group of messages:
- `senior_engineer_summary_prompt` — structured summary
- `senior_engineer_mental_models_and_thought_process_prompt` — extract mental models
- `more_related_questions_prompt` — generate follow-up questions (NQS-like)
- `engineering_excellence_prompt` — evaluate quality
- `scientific_chain_of_density_prompt` / `general_chain_of_density_prompt` — iterative summarization
- `tldr_summary_prompt` — quick TLDR

### CSS/Layout context

- Chat view: `#chatView` — scrollable container of `.card.message-card` elements
- Message cards: `.card.message-card` with `.card-header` (sender + actions) and `.card-body > .actual-card-text`
- Existing styles in `interface/workspace-styles.css` and inline in `interface.html`
- Mobile breakpoint: 768px (used throughout the app)
- Input area: `#messageText` textarea at bottom of chat

### Bootstrap version: 4.6

- Use Bootstrap 4 classes: `btn`, `btn-sm`, `btn-outline-*`, `dropdown`, `dropup`
- jQuery is available globally
- Icons: Bootstrap Icons (`bi bi-*`) used throughout

### Phase 2 Implementation Details

#### Batch Delete

The existing `delete_message(message_id, index)` in Conversation.py (line 4852):
- Acquires file lock, filters out the matching message from the messages list, calls `set_messages_field(messages, overwrite=True)`, saves
- For batch delete, add `delete_messages_batch(message_ids)` that filters out all matching IDs in one pass (single lock, single save)
- Endpoint pattern: `POST /batch_delete_messages/<conv_id>` with body `{ message_ids: ["id1", "id2", ...] }`
- After delete, frontend should call `ConversationManager.setActiveConversation(convId)` to refresh the chat view (this re-fetches via `ChatManager.listMessages`)

#### Batch Hide

The existing `show_hide_message(message_id, index, show_hide)` in Conversation.py (line 3469):
- Acquires file lock, iterates messages, sets `show_hide` field, saves
- For batch: add `batch_show_hide_messages(message_ids, show_hide)` — single lock, iterate once, save once
- Endpoint: `POST /batch_hide_messages/<conv_id>` with body `{ message_ids: [...], show_hide: "hide"|"show" }`
- Frontend calls show_hide with "hide" from the action bar. To un-hide, user uses existing per-message toggle.
- After hide, refresh chat view same as delete

#### Copy as Markdown

Pure frontend — no endpoint needed:
```javascript
// Gather selected messages in DOM order
var texts = [];
$('.message-card').each(function() {
    var msgId = $(this).find('.history-message-checkbox').attr('message-id');
    if (selectedIds.includes(msgId)) {
        var sender = $(this).find('.card-header .badge').text().trim() || 'Unknown';
        var text = $(this).find('.actual-card-text').text().trim();
        texts.push('**' + sender + ':** ' + text);
    }
});
navigator.clipboard.writeText(texts.join('\n\n'));
```
Note: `.actual-card-text` contains the rendered text. For raw markdown, would need to fetch from API — but clipboard copy of rendered text is sufficient for v1.

#### Use as Context

Already works — checkboxes checked → send flow gathers them. Action bar version:
1. Toast "N messages set as context for next message"
2. Focus `#messageText`
3. Dismiss action bar but DO NOT uncheck the checkboxes (they need to stay checked for send flow to pick them up)
4. This is the ONE action where dismiss doesn't uncheck — special case

#### Fork from Last Selected

```javascript
var maxIndex = Math.max(...selectedIndices);
// POST /fork_conversation/{convId}/{maxIndex} — already exists
```
Navigate to fork on success (reuse pattern from existing fork handler).

#### Chat view refresh pattern

After delete/hide, refresh by re-calling:
```javascript
ConversationManager.setActiveConversation(ConversationManager.activeConversationId);
```
This triggers `ChatManager.listMessages()` which re-fetches and re-renders. Simple but causes a full re-render. Acceptable for v1.

#### Getting message index from message_id

The action bar only has `message_id` values (from checkboxes). Endpoints like delete use `message_id + index`. For batch endpoints, use only `message_ids` — the backend iterates the messages list and matches by ID. This avoids index staleness issues when multiple deletes happen.

#### Frontend notification pattern

All actions use `showToast(message, type)` where type is `'success'`, `'error'`, or `'warning'`. Already available globally.

### Phase 3 Implementation Details (LLM Actions)

#### TempLlmManager integration pattern

For Summarize and Run Preamble, reuse the existing `TempLlmManager.executeAction()`:
```javascript
TempLlmManager.executeAction(action, selectedText, messageContext, withContext);
```
Where:
- `action`: string like `'explain'`, `'critique'`, `'summarize_selection'`, etc.
- `selectedText`: the concatenated message texts
- `messageContext`: `{ messageId, messageText, conversationId }`
- `withContext`: boolean (false for multi-select — we're providing the context explicitly)

**Key**: The temp LLM modal already handles streaming, multi-turn follow-up, and rendering. We just need to pass the right data.

#### Backend: temporary_llm_action endpoint

`POST /temporary_llm_action` (in `endpoints/doubts.py` line 215):
```json
{
    "action_type": "summarize_selection",
    "selected_text": "**User:** msg1\n\n**Assistant:** msg2\n\n...",
    "user_message": "",
    "message_id": null,
    "message_text": "",
    "conversation_id": "conv_id_here",
    "history": [],
    "with_context": false
}
```

For multi-select actions, we pass the concatenated messages as `selected_text`. The backend's `temporary_llm_action` method (Conversation.py line ~12989) maps `action_type` to a system prompt. We need to add new action types:
- `"summarize_selection"` → system prompt that summarizes multiple messages
- `"run_preamble"` → uses the named preamble as system prompt

#### Adding new action_types to Conversation.temporary_llm_action

In Conversation.py line ~13050-13200, there's a `prompts` dict mapping action_type to system prompt strings. Add:
```python
"summarize_selection": f"""Summarize the following conversation exchange concisely...
{selected_text}
""",
"run_preamble": None,  # handled separately — prompt loaded from prompts.py by name
```

For "run_preamble", pass the preamble name as a new field (e.g., `data.get("preamble_name")`), load it via `get_prompt(preamble_name)`, and use it as the system prompt with `selected_text` as user content.

#### Ask Question About

This is simpler than Summarize — it doesn't need a new action_type:
1. Set checked messages as context (same as "Use as Context")
2. Focus `#messageText` textarea
3. Optionally set placeholder: `$('#messageText').attr('placeholder', 'Ask about the selected messages...')`
4. Dismiss action bar, keep checkboxes checked
5. User types their question and sends normally — existing flow handles the rest

#### Run Preamble submenu

Frontend needs a list of preamble names. Two approaches:
1. **Static list** (simpler): Hardcode a curated subset in JS — the ones useful for message analysis
2. **Dynamic endpoint** (more flexible): `GET /list_preambles` → returns `{ preambles: [...] }`

Recommended: Static curated list for v1. These are the preambles suitable for "run on messages":
```javascript
const MULTI_SELECT_PREAMBLES = [
    { id: 'senior_engineer_summary_prompt', label: '🔧 Senior Engineer Summary' },
    { id: 'senior_engineer_mental_models_and_thought_process_prompt', label: '🧠 Mental Models & Thought Process' },
    { id: 'more_related_questions_prompt', label: '❓ Generate Follow-up Questions' },
    { id: 'engineering_excellence_prompt', label: '⭐ Engineering Excellence Review' },
    { id: 'general_chain_of_density_prompt', label: '📝 Dense Summary (Chain of Density)' },
    { id: 'preamble_argumentative', label: '⚖️ Argumentative Analysis' },
    { id: 'preamble_cot', label: '🔗 Chain of Thought' },
    { id: 'improve_code_prompt', label: '💻 Improve Code' },
];
```

These are loaded from `prompts.json` via `manager["name"]` at module level in `prompts.py`. The inline-defined ones (like `senior_engineer_summary_prompt` at line 291) are also accessible via the manager. Backend should use `get_prompt(name)` to retrieve.

#### Request flow for Run Preamble

Frontend:
```javascript
var concatenated = selectedMessages.map(m => '**' + m.sender + ':** ' + m.text).join('\n\n');
TempLlmManager.currentSelection = concatenated;
TempLlmManager.currentMessageContext = { conversationId: convId };
TempLlmManager.currentActionType = 'run_preamble';
TempLlmManager.currentHistory = [];
TempLlmManager.withContext = false;
TempLlmManager.openModal('run_preamble', concatenated);
// Custom stream call with extra preamble_name field
fetch('/temporary_llm_action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        action_type: 'run_preamble',
        selected_text: concatenated,
        conversation_id: convId,
        preamble_name: selectedPreambleName,  // NEW field
    })
})
```

Or simpler: extend `TempLlmManager.streamActionResponse` to accept an extra `preamble_name` param and include it in the request body.

### Phase 4 Implementation Details (Polish)

#### Dropup on mobile

Bootstrap 4 supports dropup natively:
```html
<div class="dropup">  <!-- instead of "dropdown" -->
    <button data-toggle="dropdown">More</button>
    <div class="dropdown-menu">...</div>
</div>
```
Toggle class based on `window.isProbablyMobileDevice()` or `window.innerWidth < 768`.

#### Keyboard shortcuts

```javascript
$(document).on('keydown', function(e) {
    if (e.key === 'Escape' && MultiSelectManager.count() > 0) {
        MultiSelectManager.clearAll();
    }
});
```

#### Accessibility

Minimal aria additions:
```html
<div id="multi-select-bar" role="toolbar" aria-label="Selected message actions">
    <span aria-live="polite">3 messages selected</span>
    <button aria-label="Copy selected messages as markdown">📋</button>
    ...
</div>
```

#### Bar positioning and content overlap

To prevent the bar from covering messages:
```css
#chatView {
    transition: padding-top 0.2s;
}
#chatView.has-selection-bar {
    padding-top: 50px; /* height of bar */
}
/* Mobile: padding-bottom instead */
@media (max-width: 768px) {
    #chatView.has-selection-bar {
        padding-top: 0;
        padding-bottom: 50px;
    }
}
```
Toggle `.has-selection-bar` class when bar shows/hides.

### All prompts.json keys (for reference)

```
base_system, chat_slow_reply_prompt, code_agent_prompt1, code_agent_prompt2,
code_agent_prompt2_v2, code_agent_prompt3, code_agent_what_if_prompt,
coding_interview_prompt, dating_maverick_prompt, diagram_instructions, dynamic,
engineering_excellence_prompt, google_behavioral_interview_prompt, google_gl_prompt,
improve_code_prompt, improve_code_prompt_interviews, manager_assist_agent_prompt,
manager_assist_agent_short_prompt, manager_to_manager_framework_prompt,
math_formatting_instructions, ml_system_design_*, more_related_questions_prompt,
no_code_prompt, persist_current_turn_prompt, preamble_argumentative,
preamble_blackmail, preamble_code_exec, preamble_cot, preamble_creative,
preamble_easy_copy, preamble_explore, preamble_no_ai, preamble_no_ai_short,
preamble_no_code_exec, preamble_no_code_prompt, preamble_short, preamble_web_search,
relationship_prompt, short_coding_interview_prompt, tts_friendly_format_instructions,
wife_prompt
```

Plus inline-defined prompts in prompts.py (not in .json):
- `senior_engineer_summary_prompt` (line 291)
- `senior_engineer_mental_models_and_thought_process_prompt` (line 267)
- `scientific_chain_of_density_prompt` (line 356)
- `business_chain_of_density_prompt` (line 383)
- `technical_chain_of_density_prompt` (line 412)
- `general_chain_of_density_prompt` (line 443)
- `tldr_summary_prompt` (line 143)
- `keyword_extraction_prompt` (line 191)
