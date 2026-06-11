# Doubt System Enhancements Plan

## Background

The doubt system provides a persistent, threaded Q&A layer attached to individual messages. It supports manual doubts (user-triggered via context menu) and auto-doubts (5 parallel threads generated after each assistant reply). This plan covers 7 enhancements to improve discoverability, usability, and learning value.

## Decisions Made

- **Cross-conversation view**: Full-screen modal (not a page/tab). Clicking a doubt navigates to the conversation and opens that doubt thread.
- **Threading UX**: Keep current linear chat view per-thread. Improve the overview modal: sort pinned first, user doubts above auto-doubts, collapsible preview cards.
- **Notification**: Pulse `.has-doubts-btn` animation when it first appears + toast after 20-30s delay poll. No SSE.
- **Selective auto-doubts**: Per-conversation stored setting (via existing `set_conversation_settings`).
- **Thread summarization**: Button at top of doubt chat modal. Creates a new child doubt using `senior_engineer_summary_prompt` with conversation summary + doubt thread content only (no raw chat message text).
- **Regeneration**: "↻" button in each assistant answer card header. Re-runs the LLM and replaces the answer in-place.

---

## Feature 1: Pin/Star Doubts

### Requirements
- User can pin/unpin any root doubt from the overview modal
- Pinned doubts appear first in the overview, then user-created doubts, then auto-doubts
- Sort: pinned (by date desc) → user-created unpinned (by date desc) → auto-doubts unpinned (by date desc)

### Why
- With 5+ auto-doubts per message, user-created doubts (higher signal) get buried
- Pinning lets users mark high-value threads for quick access

### Implementation

**DB**: Add `pinned boolean DEFAULT 0` column to `DoubtsClearing` (CREATE TABLE + ALTER TABLE migration in `database/connection.py`).

**Backend**:
- `POST /pin_doubt/<doubt_id>` — toggles `pinned` field. Body: `{ "pinned": true|false }`. New route in `endpoints/doubts.py`.
- `database/doubts.py`: add `update_doubt_pinned(doubt_id, pinned)` helper.
- `get_doubts_for_message()`: Change ORDER BY to: `pinned DESC, is_root_doubt DESC, CASE WHEN doubt_text LIKE 'Auto%' THEN 1 ELSE 0 END ASC, created_at DESC`. This makes pinned first, then user doubts, then auto-doubts.
- All SELECT helpers: add `pinned` to select list and return dict.

**Frontend** (`interface/doubt-manager.js`):
- `createDoubtPreviewCard()`: Add pin icon button (📌 / outlined pin). Click handler calls `POST /pin_doubt/<doubt_id>`.
- Visual: pinned cards get a highlighted left border or subtle background tint.
- Re-render the overview after pin/unpin.

### Files Modified
- `database/connection.py` — schema + migration
- `database/doubts.py` — `update_doubt_pinned()`, SELECT updates
- `endpoints/doubts.py` — new route
- `interface/doubt-manager.js` — pin button + sort rendering

---

## Feature 2: Doubt Answer Regeneration

### Requirements
- "↻" button in the header of each assistant answer card in the doubt chat modal
- Clicking it re-runs the LLM with the same `doubt_text` and context, replacing the existing answer
- Shows loading state during regeneration; streaming updates the card in-place

### Why
- Sometimes the answer is poor quality (wrong model, bad preamble, or unlucky generation)
- Currently the only option is to delete and re-ask (loses the doubt_id and threading)

### Implementation

**Backend**:
- `POST /regenerate_doubt/<doubt_id>` — new route in `endpoints/doubts.py`
  - Loads the doubt record
  - Calls `conversation.clear_doubt()` with the same `message_id`, `doubt_text`, `doubt_history` (ancestors), `with_context` (from saved field), and current `doubt_preamble_options` from request body
  - Streams response exactly like `/clear_doubt`
  - On completion: UPDATE the existing row's `doubt_answer` and `updated_at` (no new record)
- `database/doubts.py`: add `update_doubt_answer(doubt_id, new_answer)` helper

**Frontend** (`interface/doubt-manager.js`):
- `createDoubtChatCard()` for assistant cards: add "↻" button in `.doubt-card-actions`
- Click handler:
  - Shows spinner in the card body
  - Calls `POST /regenerate_doubt/<doubt_id>` with `{ preamble_options: [...] }`
  - Streams response into the same card body (reuse `renderStreamingDoubtResponse` logic)
  - On completion, updates `currentDoubtHistory` entry's `doubt_answer`

### Files Modified
- `endpoints/doubts.py` — new route
- `database/doubts.py` — `update_doubt_answer()`
- `interface/doubt-manager.js` — regen button + streaming in-place

---

## Feature 3: Doubt Thread Summarization

### Requirements
- "Summarize Thread" button at top of doubt chat modal (in modal header area)
- Creates a new child doubt at the end of the current thread
- Uses `senior_engineer_summary_prompt` from `prompts.py`
- Input context: conversation running_summary + all doubt Q&A pairs in the thread (NOT the raw chat message text from the main conversation)
- The summary doubt answer appears as a new card at the bottom of the chat

### Why
- Long doubt threads (especially auto-doubts with 4+ children) are hard to scan
- A summarization pass extracts actionable knowledge (concepts, caveats, key questions) into a single digestible card
- Avoids leaking main conversation content into the summary — keeps it focused on what was discussed in the doubt thread itself

### Implementation

**Backend**:
- `POST /summarize_doubt_thread/<doubt_id>` — new route in `endpoints/doubts.py`
  - `doubt_id` is any doubt in the thread (the endpoint walks up to root, then collects the full tree)
  - Builds context from:
    1. `conversation.running_summary` (if available) — provides background
    2. All doubt Q&A pairs in the thread chronologically
  - Prompt: `senior_engineer_summary_prompt` appended after the context
  - Streams response
  - On completion: saves as a new child doubt with `doubt_text = "Thread Summary"`, `parent_doubt_id` = last doubt in chain

**Frontend** (`interface/doubt-manager.js`):
- Add "📋 Summarize" button in `#doubt-chat-modal .modal-header` (beside the back button)
- Only visible when `currentDoubtHistory.length > 0` (can't summarize empty thread)
- Click handler: disables button, calls endpoint, appends user card ("Thread Summary") + streams assistant card
- After completion: updates `currentDoubtHistory`

### Files Modified
- `endpoints/doubts.py` — new route
- `Conversation.py` — new method `summarize_doubt_thread()` or reuse `clear_doubt()` with special prompt
- `interface/doubt-manager.js` — summarize button

---

## Feature 4: Cross-Conversation Doubt View (Global Modal)

### Requirements
- Accessible from a top-level button in the UI (sidebar or navbar)
- Full-screen modal showing ALL user's doubts across all conversations
- Sortable by: date (default), pinned first
- Searchable: free-text search across `doubt_text` and `doubt_answer`
- Filterable: pinned only, user-created only, auto-doubts only
- Each entry shows: doubt question preview, answer preview, conversation title, date
- Clicking a doubt: closes global modal → navigates to that conversation → opens doubt chat modal for that thread
- "Go to message" link: scrolls to the source message in the conversation

### Why
- Currently doubts are only discoverable per-message. User has no way to find "that explanation about gradient descent I got last week"
- Turns the doubt system into a searchable personal learning journal

### Implementation

**Backend**:
- `GET /get_all_doubts?page=1&page_size=20&search=&filter=all|pinned|user|auto&sort=date_desc`
  - New route in `endpoints/doubts.py`
  - Returns paginated list of root doubts for the current user
  - Search: `WHERE (doubt_text LIKE ? OR doubt_answer LIKE ?)` with `%query%`
  - Filter: `pinned=1`, `doubt_text NOT LIKE 'Auto%'` for user, `doubt_text LIKE 'Auto%'` for auto
  - Include `conversation_id` in response so frontend can navigate
- `database/doubts.py`: `get_all_doubts_for_user(user_email, page, page_size, search, filter, sort)` helper
- Need conversation title for display: join with conversation metadata or return `conversation_id` and let frontend resolve the title from loaded state (simpler)

**Frontend**:
- New file: `interface/global-doubts-modal.js` (or section in `doubt-manager.js`)
- New modal HTML in `interface/interface.html`: `#global-doubts-modal`
  - Search bar, filter pills (All / Pinned / My Doubts / Auto), sort toggle
  - Scrollable list of doubt cards with pagination (infinite scroll or pages)
  - Each card: pin icon, question preview, answer preview (truncated), conversation name, date
- Entry point: button in sidebar/navbar — e.g. an icon button with tooltip "My Doubts"
- Click behavior:
  1. Close global modal
  2. If different conversation: call `loadConversation(conversationId)` (existing function)
  3. After load: call `DoubtManager.openDoubtChat(doubtId)`

### Files Modified
- `database/doubts.py` — new query helper
- `endpoints/doubts.py` — new route
- `interface/interface.html` — modal HTML + entry button
- `interface/doubt-manager.js` (or new file) — global modal logic

---

## Feature 5: Selective Auto-Doubts (Per-Conversation)

### Requirements
- Per-conversation setting: which auto-doubt categories are enabled
- Categories: `takeaways`, `maximize_learning`, `challenge_verify`, `foundations_practice`, `answer_questions`
- Default: all enabled (current behavior)
- UI: checkboxes in a per-conversation settings area (or inside the existing conversation settings)
- Backend reads this before dispatching auto-doubt futures

### Why
- Some users only want takeaways, not all 5 (costs tokens, creates noise)
- Different conversations have different needs (technical study → all, casual → takeaways only)

### Implementation

**Backend**:
- In `set_conversation_settings`: accept new key `auto_doubt_categories` (list of strings). Validate against allowed set.
- In the dispatch block (`endpoints/conversations.py` ~L1942): read `conversation.get_conversation_settings().get("auto_doubt_categories", None)`. If `None`, run all. Otherwise, only dispatch functions whose category is in the list.
- Mapping:
  ```python
  AUTO_DOUBT_DISPATCH = {
      "takeaways": _create_auto_takeaways_doubt_for_last_assistant_message,
      "maximize_learning": _create_maximize_learning_doubt,
      "challenge_verify": _create_challenge_and_verify_doubt,
      "foundations_practice": _create_foundations_and_practice_doubt,
      "answer_questions": _create_answer_raised_questions_doubt,
  }
  ```

**Frontend**:
- In the conversation settings modal (or a new section in `#chat-settings-modal`): 5 checkboxes, all checked by default
- On save: `PUT /set_conversation_settings/<conversation_id>` with `{ "auto_doubt_categories": ["takeaways", "maximize_learning", ...] }`
- On load: `GET /get_conversation_settings/<conversation_id>` → populate checkboxes

### Files Modified
- `endpoints/conversations.py` — validation in `set_conversation_settings`, dispatch filtering in `send_message`
- `interface/interface.html` — checkboxes UI
- `interface/chat.js` — load/save wiring

---

## Feature 6: Doubt Notification (Pulse + Toast)

### Requirements
- When auto-doubts finish generating for a message, the `.has-doubts-btn` for that message pulses briefly (CSS animation)
- After a ~25s delay from reply completion, frontend polls `GET /get_messages_with_doubts/<conversation_id>` and shows a toast: "✨ Learning aids ready for your last reply" if new doubts appeared
- No SSE, no persistent connection

### Why
- Currently auto-doubts appear silently; user has no idea when they're ready
- A pulse + toast provides a gentle, non-blocking notification

### Implementation

**CSS** (`interface/interface.html` or separate CSS):
```css
@keyframes doubt-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.3); opacity: 0.7; }
}
.has-doubts-btn.doubt-new-pulse {
  animation: doubt-pulse 0.6s ease-in-out 3;
  color: #007bff !important;
}
```

**Frontend** (`interface/common-chat.js`):
- After reply streaming completes (where `<--END-->` is detected / `completed: true`), set a 25s `setTimeout`
- In the callback: call `GET /get_messages_with_doubts/<conversation_id>`
- For any newly-visible `.has-doubts-btn` that was previously hidden: add class `doubt-new-pulse`, show toast
- Remove the pulse class after animation ends (3 cycles ≈ 1.8s, or listen for `animationend`)

**No backend changes needed** — uses existing endpoint.

### Files Modified
- `interface/interface.html` (CSS section) — pulse animation
- `interface/common-chat.js` — delayed poll + toast + pulse trigger

---

## Feature 7: Doubt Threading UX Improvement (Overview Modal)

### Requirements
- In the doubts overview modal, sort order: pinned → user-created → auto-doubts (each group by date desc)
- Auto-doubt cards get a subtle "Auto" badge/tag
- User-created doubt cards have no badge (or a "You" badge)
- Each preview card is collapsible (click to expand/collapse the answer preview)
- Visual hierarchy: pinned cards have a pin icon + highlighted border

### Why
- With 5+ auto-doubts per message, the overview gets noisy
- Clear visual separation between user's questions and auto-generated content

### Implementation

This is mostly a frontend change to `renderDoubtsOverview()` and `createDoubtPreviewCard()`.

**Frontend** (`interface/doubt-manager.js`):
- `renderDoubtsOverview()`: sort the doubts array before rendering (pinned first, then user, then auto, each by date desc)
- `createDoubtPreviewCard()`: 
  - If `doubt.doubt_text` starts with "Auto" or matches known auto-doubt texts → add "Auto" badge `<span class="badge badge-secondary">Auto</span>`
  - If `doubt.pinned` → add pin icon + accent border
  - Preview body is collapsed by default (only shows Q), click expands to show A preview
  
**Heuristic for auto-doubt detection**: `doubt_text` in `["Auto takeaways", "Maximize Learning and Perspectives", "Challenge & Verify", "Foundations & Practice", "Answer Raised Questions"]`

### Files Modified
- `interface/doubt-manager.js` — sorting + badges + collapsible cards

---

## Feature 8: "Ask About This Doubt" from Main Chat

### Requirements
- Context menu option on any message that has doubts: "Continue doubt in main chat"
- Opens a sub-menu or modal listing the doubt threads for that message
- User picks a thread → the doubt thread content is injected into the next main-chat reply as additional context
- The main chat message is sent normally but the LLM sees the doubt Q&A as background

### Why
- Sometimes a doubt thread reveals something important that should feed back into the main conversation
- Bridges the isolated doubt world back into the primary conversation flow

### Implementation

**Frontend** (`interface/context-menu-manager.js` + `interface/common-chat.js`):
- New context menu item: "Continue doubt in main chat" (only shown if `.has-doubts-btn` is visible for that message)
- Click: fetch `GET /get_doubts/<conversation_id>/<message_id>`, show a quick picker (dropdown or mini-modal) of root doubts (question preview)
- On selection: flatten the selected thread's Q&A into text, inject into the `permanentText` field (or a one-time context injection field)
- User then types their message normally; the injected doubt context rides along as part of `permanentText` for that turn
- After send: clear the injected text from `permanentText` (one-shot injection)

**Alternative simpler approach**: Instead of permanentText manipulation, prepend the doubt context to the user's message text as a `[Doubt Context]` block that the backend recognizes and moves into context position (similar to how `[Clarifications]` blocks work).

**Backend**: No new endpoint needed — the existing `permanentText` mechanism or message preprocessing handles it.

### Files Modified
- `interface/context-menu-manager.js` — new menu item + handler
- `interface/common-chat.js` — doubt-to-context injection logic

---

## Feature 9: Doubt Answer Length Control + Preamble Selector in Modal

### Requirements
- At the top of the doubt chat modal: a compact control bar with:
  1. **Length toggle**: Short / Medium / Long buttons (pill group)
  2. **Preamble selector**: same multi-select as the settings modal `#settings-doubt-preamble-selector`, but inline in the doubt modal for quick switching
- These override the settings-modal values for the current doubt session
- Length toggle maps to: Short → adds "Short" to preamble list; Long → adds "Long"; Medium → neither

### Why
- Auto-doubts are often too verbose; user wants quick "Short" mode
- Switching preamble requires opening a separate settings modal — friction kills the flow
- Inline controls let the user tune response style mid-conversation without leaving the doubt modal

### Implementation

**Frontend** (`interface/doubt-manager.js`):
- Add a `.doubt-modal-controls` bar inside `#doubt-chat-modal .modal-body` above `#doubt-chat-messages`:
  ```html
  <div class="doubt-modal-controls d-flex align-items-center gap-2 mb-2">
    <div class="btn-group btn-group-sm" role="group">
      <button class="btn btn-outline-secondary doubt-length-btn" data-length="short">Short</button>
      <button class="btn btn-outline-secondary doubt-length-btn active" data-length="medium">Medium</button>
      <button class="btn btn-outline-secondary doubt-length-btn" data-length="long">Long</button>
    </div>
    <select class="form-control form-control-sm" id="doubt-modal-preamble-selector" multiple data-live-search="true" style="max-width: 200px;">
      <!-- Same options as settings-doubt-preamble-selector -->
    </select>
  </div>
  ```
- On modal open (`openDoubtChatModal`): populate preamble selector from `chatSettingsState.doubt_preamble_options`, set length to "Medium"
- `sendDoubt()`: read length + preamble from modal controls instead of (or merged with) `chatSettingsState`
- Length logic: if "Short" active, ensure "Short" is in preamble list sent; if "Long", ensure "Long" is in list; if "Medium", remove both

**Backend**: No changes — already accepts `preamble_options` which can include "Short"/"Long".

### Files Modified
- `interface/interface.html` — control bar HTML in doubt modal
- `interface/doubt-manager.js` — read inline controls, merge with preamble list
- CSS for `.doubt-modal-controls`

---

## Feature 10: Copy Entire Doubt Thread

### Requirements
- "📋 Copy Thread" button in the doubt chat modal header (beside Summarize)
- Copies the entire Q&A thread as formatted markdown to clipboard
- Format: `## Q: <question>\n\n<answer>\n\n---\n\n` for each pair

### Why
- Users want to paste doubt threads into notes, Quip docs, study materials, or share with others
- Currently they'd have to copy each card individually

### Implementation

**Frontend** (`interface/doubt-manager.js`):
- Add button in `#doubt-chat-modal .modal-header`: `<button id="doubt-copy-thread-btn" class="btn btn-sm btn-outline-secondary" title="Copy Thread"><i class="bi bi-clipboard"></i> Copy Thread</button>`
- Click handler:
  ```js
  const threadText = this.currentDoubtHistory.map(d =>
    `## Q: ${d.doubt_text}\n\n${d.doubt_answer}\n\n---`
  ).join('\n\n');
  navigator.clipboard.writeText(threadText);
  showToast('Thread copied to clipboard', 'success');
  ```
- Uses `currentDoubtHistory` which already has the full thread loaded

**Backend**: No changes needed.

### Files Modified
- `interface/doubt-manager.js` — copy button + handler
- `interface/interface.html` — button HTML in modal header (if not added dynamically)

---

## Feature 11: Doubt Thread as Conversation Seed

### Requirements
- "💬 Continue as Conversation" button in the doubt chat modal header
- Creates a new conversation pre-loaded with the doubt thread as initial context
- The new conversation's first assistant message is a summary of the doubt thread
- User is navigated to the new conversation

### Why
- Sometimes a doubt thread evolves into a topic that deserves full conversation treatment (with web search, tools, full history)
- Avoids manually copy-pasting doubt content into a new chat

### Implementation

**Frontend** (`interface/doubt-manager.js`):
- "Continue as Conversation" button in modal header
- Click handler:
  1. Build a seed text from the doubt thread: concatenate all Q&A pairs as a structured context block
  2. Call `ConversationManager.createConversation()` (existing) — get new `conversation_id`
  3. Close doubt modal
  4. Navigate to new conversation
  5. Set the message input to something like: "Continue from the doubt thread above. [thread context injected]"
  6. Or better: use the `permanentText` field to inject the doubt thread as persistent context for the new conversation's first turn, then auto-send a starter message

**Alternative approach — backend-driven**:
- `POST /create_conversation_from_doubt/<doubt_id>` — new endpoint
  - Creates conversation
  - Injects doubt thread content as the conversation's initial `running_summary` or as a pre-seeded user+assistant message pair
  - Returns new `conversation_id`
- Frontend just calls this, then navigates

**My recommendation**: Backend-driven approach is cleaner — the doubt thread content becomes part of the conversation's memory from the start, not just a one-shot permanentText injection.

**Backend** (`endpoints/doubts.py` or `endpoints/conversations.py`):
- `POST /create_conversation_from_doubt_thread/<doubt_id>`:
  - Load doubt thread (walk to root, flatten chronologically)
  - Create new conversation via existing `create_conversation()` helper
  - Set `running_summary` to a formatted version of the doubt thread
  - Add a synthetic first message pair: user="Continue exploring this topic" + assistant="Based on our previous discussion: [brief summary of thread]"
  - Return `{ conversation_id, redirect_url }`

### Files Modified
- `endpoints/conversations.py` or `endpoints/doubts.py` — new endpoint
- `interface/doubt-manager.js` — button + navigation logic

---

## Feature 12: Auto-Doubt Model Selection

### Requirements
- Per-conversation setting: which model to use for auto-doubt generation
- Accessible via the existing model overrides UI (same pattern as `quick_action_model`, `clarify_intent_model`)
- Key: `auto_doubt_model`
- Default: `gemini-flash-3.5-non-reasoning` (current hardcoded value)

### Why
- Some users want higher quality auto-doubts (reasoning model for "Challenge & Verify")
- Others want cheaper/faster models to reduce cost
- The current hardcoded model can't be tuned per conversation

### Implementation

**Backend**:
- Add `"auto_doubt_model"` to `allowed_keys` in `set_conversation_settings`
- In each `_create_*_doubt` function: replace hardcoded model with:
  ```python
  auto_doubt_model = conversation.get_model_override("auto_doubt_model", "gemini-flash-3.5-non-reasoning")
  ```
- All 5 auto-doubt functions use this override

**Frontend**:
- In `#model-overrides-modal` (existing modal for per-conversation model overrides): add a dropdown `#settings-auto-doubt-model` with the same model options
- Wire into `saveConversationModelOverrides()` / `loadConversationModelOverrides()` following existing pattern

### Files Modified
- `endpoints/conversations.py` — add to `allowed_keys`
- `endpoints/conversations.py` — each `_create_*_doubt` function reads override
- `interface/interface.html` — dropdown in model overrides modal
- `interface/chat.js` — save/load wiring

---

## Feature 13: Doubt Thread Bookmarks

### Requirements
- Inside the doubt chat modal, user can bookmark specific doubt Q&A pairs within a long thread
- Bookmarked doubts get a visual indicator (⭐ or 🔖 icon)
- In the doubts overview modal, preview cards show "N bookmarks" badge
- Clicking the badge (or a "Jump to bookmarks" action) opens the thread and scrolls to the first bookmarked item

### Why
- Long auto-doubt threads (Auto Takeaways with 4 children = 10 cards) have buried gems
- Bookmarks let users mark "this specific answer was the key insight" for later retrieval
- Complements pinning (which works at the thread level) with within-thread granularity

### Implementation

**DB**: Add `bookmarked boolean DEFAULT 0` column to `DoubtsClearing` (same migration pattern as `pinned`).

**Backend**:
- `POST /bookmark_doubt/<doubt_id>` — toggles `bookmarked`. Body: `{ "bookmarked": true|false }`
- `database/doubts.py`: `update_doubt_bookmarked(doubt_id, bookmarked)` helper
- All SELECT helpers: add `bookmarked` to select list and return dict

**Frontend** (`interface/doubt-manager.js`):
- `createDoubtChatCard()` for assistant cards: add bookmark icon button in `.doubt-card-actions`
- Click handler: toggle, call `POST /bookmark_doubt/<doubt_id>`, update icon state
- `createDoubtPreviewCard()`: if thread has any bookmarked children, show "N 🔖" badge
- When opening a thread with bookmarks: after render, scroll to first bookmarked card (optional, could be a "Jump to bookmark" button instead)

### Files Modified
- `database/connection.py` — schema + migration
- `database/doubts.py` — `update_doubt_bookmarked()`, SELECT updates
- `endpoints/doubts.py` — new route
- `interface/doubt-manager.js` — bookmark button + badge rendering

---

## Clarifications Added

1. **Regeneration + children**: Regeneration is allowed on any doubt. If it has children, show a warning toast: "Follow-up questions were based on the previous answer." Children are preserved (not deleted).

2. **Thread summarization parent**: Summary is appended as child of the chronologically last doubt in the flattened thread (regardless of tree branching).

3. **Cross-conversation view — conversation titles**: Backend JOIN with conversation metadata to include `conversation_title` in the response. No extra frontend fetch needed.

4. **Pin scope**: Pinning applies to root doubts only. The pin button appears on overview preview cards (which are always roots). Pinning a child would be meaningless since the overview only shows roots.

5. **Selective auto-doubts default**: When `auto_doubt_categories` is absent (`None`), all 5 run. UI shows all checkboxes checked when the setting doesn't exist.

---

## Implementation Order (Revised)

**Phase 1 — Foundations** (enable sorting and per-doubt metadata):
1. Pin/star doubts (DB + endpoint + UI)
2. Bookmarks (DB + endpoint + UI) — same migration batch
3. Threading UX improvement (depends on pin/bookmark fields)

**Phase 2 — Core UX** (biggest user-facing value):
4. Doubt answer regeneration
5. Doubt answer length control + inline preamble selector
6. Copy entire doubt thread
7. Doubt notification (pulse + toast)

**Phase 3 — Knowledge tools** (thread-level operations):
8. Doubt thread summarization
9. "Ask about this doubt" from main chat
10. Doubt thread as conversation seed

**Phase 4 — Configuration & scale**:
11. Selective auto-doubts (per-conversation)
12. Auto-doubt model selection
13. Cross-conversation doubt view (largest scope)

## Schema Changes Summary (Revised)

New columns on `DoubtsClearing` (all with ALTER TABLE migration + CREATE TABLE update):
- `pinned boolean DEFAULT 0`
- `bookmarked boolean DEFAULT 0`

New conversation settings keys:
- `auto_doubt_categories` (list of strings)
- `auto_doubt_model` (string, model name)

No new tables required.
