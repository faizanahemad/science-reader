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

## Implementation Order (Suggested)

1. **Pin/star doubts** — foundational for sorting everywhere else
2. **Threading UX improvement** — depends on pin field existing
3. **Doubt answer regeneration** — self-contained, high user value
4. **Doubt thread summarization** — builds on regeneration patterns
5. **Doubt notification** — purely frontend, independent
6. **Selective auto-doubts** — per-conversation settings
7. **Cross-conversation doubt view** — largest scope, depends on pin/search infrastructure

## Schema Changes Summary

New columns on `DoubtsClearing` (all with ALTER TABLE migration + CREATE TABLE update):
- `pinned boolean DEFAULT 0`

New conversation settings key:
- `auto_doubt_categories` (list of strings, stored in JSON in conversation settings)

No new tables required.
