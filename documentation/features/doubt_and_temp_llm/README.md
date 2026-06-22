# Doubt Clearing & Temporary LLM Actions

Two related but distinct systems for asking questions about message content without affecting the main conversation thread.

> The doubt flow can also **edit the assistant answer** on explicit user request via the `propose_answer_edit` tool (diff preview + revert support). See [Edit the Answer from the Doubt Flow](#feature-edit-the-answer-from-the-doubt-flow).

---

## 1. Doubt Clearing System

### Motivation

Users often want to ask follow-up questions about a specific assistant (or user) message — to clarify a concept, dig deeper, or ask a follow-up — without polluting the main conversation thread. The doubt system provides a persistent, threaded Q&A layer attached to individual messages.

### UI Flow

1. User right-clicks on any message → context menu appears (`ContextMenuManager`)
2. Two doubt entry points:
   - **"Ask a Doubt"** → `handleAskDoubt(false)` — sends only the target message as context
   - **"Ask a Doubt (with context)"** → `handleAskDoubt(true)` — sends conversation summary + surrounding messages
3. If the user had text selected when right-clicking, that selection is captured as `currentSelection`
4. `ContextMenuManager.handleAskDoubt(withContext)` calls:
   ```js
   DoubtManager.askNewDoubt(conversationId, messageId, selectedText, withContext)
   ```
5. `DoubtManager` stores `selectedText` and `withContext`, resets `currentDoubtHistory`, opens the doubt chat modal
6. User types a question and submits → `DoubtManager` POSTs to `/clear_doubt/<conversation_id>/<message_id>`
7. Response streams back as newline-delimited JSON chunks; the modal renders them as conversation cards (user bubble left-indented, assistant bubble white)
8. After streaming completes, the final chunk contains `<doubt_id>...</doubt_id>` — the saved DB record ID
9. Follow-up doubts: user can ask again in the same modal; `parent_doubt_id` is passed so the backend retrieves the full thread history

A separate **"View Doubts"** button on each message opens a doubts overview modal showing all past doubt threads for that message, rendered as nested trees. When viewing a specific doubt thread (`doubt-chat-modal`), a **← back button** in the modal header returns to the doubts overview without needing to re-click the entry point.

### UI Flow — File Attachments

The doubt chat modal supports the same file attachment UI as the main chat input:

1. A paperclip button (📎) above the textarea opens a file picker; files can also be drag-dropped.
2. Uploaded files appear as thumbnail badges (images) or file badges (PDFs/docs) in a preview strip.
3. Badges can be removed before sending.
4. On send, `display_attachments` is included in the POST body alongside `doubt_text`.
5. After the modal closes, any unsent attachments are deleted via `DELETE /detach_doc_from_message/<conv_id>/<doc_id>` to avoid orphaned files.
6. When reopening a saved doubt thread, attachment badges are re-rendered from the `display_attachments` array stored in the DB.

**How the LLM sees attachments:**
- **Images** (`FastImageDocIndex`): loaded via `_get_attached_doc_images()` and passed as `images=` to `_run_tool_loop` / the fallback LLM call — the actual image bytes go to the vision endpoint directly, with no tool calls needed.
- **Text/data docs** (`FastDocIndex`): full text inlined directly into the prompt via `_get_attached_doc_texts()` as labelled `--- Attached: filename ---` sections.
- The `#doc_N` BM25 pipeline is intentionally **not** used for doubt attachments because the doubt LLM has no `document_lookup` tool, and newly uploaded files only exist in `message_attached_documents_list` (which `document_lookup` does not search).

### API

**`POST /clear_doubt/<conversation_id>/<message_id>`** (`endpoints/doubts.py`)

Request body:
```json
{
  "doubt_text": "string",
  "reward_level": 0,
  "selected_text": "optional highlighted text",
  "with_context": false,
  "parent_doubt_id": "optional, for follow-ups",
  "display_attachments": [{"doc_id": "...", "name": "...", "type": "image|file", "thumbnail": "..."}]
}
```

Streaming response (newline-delimited JSON):
- Each chunk: `{ text, status, conversation_id, message_id, type: "doubt_clearing", accumulated_text }`
- Final chunk: `{ completed: true, doubt_id: "...", accumulated_text }`

**`DELETE /detach_doc_from_message/<conversation_id>/<doc_id>`** — remove a message-attached document from the conversation (used to clean up unsent doubt/temp-LLM attachments on modal close)

**`GET /get_doubts/<conversation_id>/<message_id>`** — returns all doubt trees for a message  
**`GET /get_doubt/<doubt_id>`** — fetch a single doubt record  
**`DELETE /delete_doubt/<doubt_id>`** — delete a doubt and its entire sub-tree (recursive). Response includes `deleted_doubt_ids` (the target plus all descendants).  
**`POST /show_hide_doubt/<doubt_id>`** — persist a doubt answer card's collapse state (body `{ "show_hide": "show" | "hide" }`)  
**`POST /cancel_doubt_clearing/<conversation_id>`** — cancel an in-progress stream

### Backend: `Conversation.clear_doubt()`

(`Conversation.py`, line ~12427)

Parameters: `message_id, doubt_text, doubt_history, reward_level, selected_text="", with_context=False, display_attachments=None`

**Context building logic:**

- Always calls `get_context_around_message(message_id, before=4, after=2)` to fetch the target message and surrounding messages
- **`with_context=False`** (default): only the single target message is included in the prompt
- **`with_context=True`**: includes the conversation `running_summary` + all surrounding context messages, with the target marked `← [TARGET MESSAGE]`
- If `selected_text` is non-empty: injects `**Selected Text the user is asking about:** "..."` into the prompt between the context block and the user's doubt question
- If `doubt_history` is non-empty (follow-up): prepends the full prior Q&A thread as "Previous Doubt History"

**Attachment handling:**
- `_get_attached_doc_images(display_attachments)` → loads `FastImageDocIndex`/`ImageDocIndex` from `message_attached_documents_list` + `uploaded_documents_list`, returns `llm_image_source` paths
- `_get_attached_doc_texts(display_attachments)` → loads `FastDocIndex` entries, returns full extracted text
- Images passed as `images=_doubt_images` to `_run_tool_loop` (and fallback LLM call) — vision LLM sees them directly
- Text docs appended inline to `doubt_text` as `--- Attached: filename ---\n{text}` sections
- The `#doc_N` injection pipeline is not used — newly uploaded doubt files live only in `message_attached_documents_list` and the doubt LLM has no `document_lookup` tool

**LLM call:** `temperature=0.3`, `max_tokens=2000`, streaming  
**System prompt:** "You are a helpful AI assistant specializing in clarifying doubts and explaining complex concepts clearly and thoroughly. Avoid using markdown headers and avoid excessive formatting. Write with the intention to help the user learn and understand better without formatting bloat."

After streaming completes, the endpoint saves the Q&A to the DB via `database.doubts.add_doubt()`, persisting `display_attachments` as JSON.

### Storage: `DoubtsClearing` table in `users.db`

(`database/doubts.py`)

```
doubt_id          — MD5(conversation_id + message_id + doubt_text + answer + timestamp + parent_id)
conversation_id
user_email
message_id        — the message this doubt is about
doubt_text        — user's question (plain text, no injected #doc_N refs)
doubt_answer      — full LLM response (saved after streaming completes)
parent_doubt_id   — NULL for root doubts; points to parent for follow-ups
child_doubt_id    — forward pointer to next follow-up (singly linked)
is_root_doubt     — 1 if no parent
show_hide         — 'show' | 'hide' collapse state of the answer card in the doubt modal (NULL/empty = expanded)
created_at
updated_at
display_attachments — JSON array of {type, name, thumbnail, doc_id} for files attached to this doubt question
```

**Tree structure:** doubts form a linked list / tree. Each independent question on a message is a root (`is_root_doubt=1`). Follow-ups chain via `parent_doubt_id`.

**Key DB functions:**

| Function | Purpose |
|---|---|
| `add_doubt()` | Insert new record; if follow-up, also updates parent's `child_doubt_id` |
| `get_doubts_for_message()` | Fetches all root doubts for a message, then recursively builds full trees via `build_doubt_tree()` |
| `get_doubt_history()` | Walks `parent_doubt_id` chain backwards to root, reverses → chronological thread for LLM context |
| `delete_doubt()` | Recursively deletes the node and its entire sub-tree (all descendants). Returns the list of deleted `doubt_id`s. Deleting a root doubt removes its whole tree |
| `update_doubt_show_hide()` | Persists the per-doubt answer collapse state (`show`/`hide`) |

**When is the answer saved?** Only after the full stream completes, in the `finally` block of the stream generator. If streaming is interrupted, a partial answer may still be saved if `accumulated_doubt_answer` is non-empty.

### Answer Show/Hide (Collapse) in the Doubt Modal

Assistant doubt answer cards in the doubt chat modal (`#doubt-chat-modal`) carry a `[show]`/`[hide]` collapse toggle in the card header, mirroring the main-answer show/hide. This keeps long threads (especially the auto-doubts, which can be lengthy) scannable.

- **Where it appears:** assistant answer cards whose text is longer than 300 chars (the same threshold as the scroll-to-top button). User-question cards and short answers have no toggle. The overview preview cards (`createDoubtPreviewCard`) already truncate to 150 chars and are unaffected.
- **Collapse behaviour:** toggling adds/removes the `doubt-answer-collapsed` class on the card, which hides the `.card-body` (and the answer's scroll-to-top button) via CSS.
- **Persistence:** each toggle POSTs to `/show_hide_doubt/<doubt_id>` which calls `update_doubt_show_hide()`. State is restored when a thread is reopened (`renderDoubtHistory` passes `doubt.show_hide` into `createDoubtChatCard`).
- **Defaults:** a `NULL`/empty `show_hide` is treated as **expanded**, so existing doubts and freshly-streamed answers render expanded; only an explicit user collapse persists as `hide`.
- **Implementation:** `DoubtManager.ensureDoubtAnswerToggle(card, doubtId, showHide)` injects the toggle idempotently and applies the state. It is called from `createDoubtChatCard` (history render) and from both streaming-completion branches once the `doubt_id` is known. A document-delegated click handler in `setupChatEventHandlers` performs the toggle + persistence.

### Key Files

| File | Role |
|---|---|
| `interface/doubt-manager.js` | `DoubtManager` — modal, state, API call, streaming render, attachment wiring, badge rendering on reload |
| `interface/context-menu-manager.js` | `handleAskDoubt(withContext)` — entry point from right-click menu |
| `interface/common-chat.js` | `uploadFileToConversation()`, `renderDisplayAttachmentBadges()` — shared upload + badge helpers |
| `endpoints/doubts.py` | All doubt HTTP routes + streaming generator; reads `display_attachments` from request |
| `endpoints/documents.py` | `DELETE /detach_doc_from_message/<conv_id>/<doc_id>` — cleanup of unsent attachments |
| `Conversation.py` ~L12427 | `clear_doubt()`, `_get_attached_doc_images()`, `_get_attached_doc_texts()` |
| `database/doubts.py` | All SQLite operations on `DoubtsClearing`; `add_doubt()` stores `display_attachments` as JSON |
| `database/connection.py` | Migration adding `display_attachments TEXT` column to `DoubtsClearing` |

---

## 2. Temporary LLM Actions

### Motivation

Quick, ephemeral actions on selected text that don't need to be saved anywhere. The user selects text in a message, right-clicks, and gets an instant LLM response in a floating modal. The conversation is lost when the modal closes.

### UI Flow

**One-shot actions** (explain, critique, expand, eli5):
1. User selects text, right-clicks → picks an action
2. `ContextMenuManager` calls `TempLLMManager.executeAction(action, selectedText, messageContext, withContext)`
3. Modal opens immediately and starts streaming the response

**Multi-turn chat** (`ask_temp`):
1. User picks "Ask Temporarily" (with or without context)
2. `TempLLMManager.openTempChatModal(selectedText, messageContext, withContext)` opens the modal without auto-streaming
3. User types messages; each turn POSTs to `/temporary_llm_action` with the full `history` array
4. After each response completes, the user+assistant turn is appended to `TempLLMManager.currentHistory`
5. Next turn sends the updated history — multi-turn context is maintained

**Aside / BTW entry points** (ask without selecting text):
- `/aside <question>` or `/btw <question>` typed in the main message box → intercepted before send, opens temp chat modal with the question pre-filled and auto-submitted, conversation context included (`with_context=true`)
- 💬 **Aside button** next to the send button → opens temp chat modal with current textarea content as the question
- **Ctrl+Shift+Space** keyboard shortcut → same as the aside button
- All three routes call `openAsideChatModal(text)` in `common-chat.js`, which calls `TempLLMManager.openTempChatModal(text, { conversationId }, true)` and auto-clicks send if text is non-empty

**History is entirely client-side** — `TempLLMManager.currentHistory` is a plain JS array, reset to `[]` when the modal closes or a new action starts. Nothing is persisted to the DB.

### API

**`POST /temporary_llm_action`** (`endpoints/doubts.py`)

Request body:
```json
{
  "action_type": "explain|critique|expand|eli5|ask_temp",
  "selected_text": "...",
  "user_message": "for ask_temp only",
  "message_id": "optional",
  "message_text": "optional full message text",
  "conversation_id": "optional",
  "history": [{"role": "user|assistant", "content": "..."}],
  "with_context": false,
  "display_attachments": [{"doc_id": "...", "name": "...", "type": "image|file", "thumbnail": "..."}]
}
```

Streaming response (newline-delimited JSON):
- Each chunk: `{ text, status, type: "temporary_llm" }`
- Final chunk: `{ completed: true }`

### Backend Routing

The endpoint tries to load the conversation first:
- **If conversation is available:** delegates to `conversation.temporary_llm_action()` — uses the conversation's `quick_action_model` override and can access `get_context_around_message()`
- **If no conversation (or load fails):** falls back to `direct_temporary_llm_action()` in `endpoints/llm_actions.py` — direct LLM call using `EXPENSIVE_LLM[2]`

### Backend: `Conversation.temporary_llm_action()`

(`Conversation.py`, line ~12568)

**Context building (`with_context=True`):**
- Calls `get_context_around_message(message_id, before=4, after=2)`
- Injects surrounding messages with `← [SELECTED FROM THIS MESSAGE]` marker on the target
- Also appends last 3 entries of `running_summary`
- If `with_context=False`: only `message_context` (the raw message text) is included

**Attachment handling:**
- `_get_attached_doc_texts(display_attachments)` → inlines full extracted text for each text/data doc as `--- Attached: filename ---\n{text}` appended to the action prompt
- Temp LLM has no doc-reading pipeline, so text is always inlined directly (no `#doc_N` tool path)
- Image attachments are not currently inlined into temp LLM actions (temp LLM uses `images=[]`)
- All attachments (sent and unsent) are cleaned up via `DELETE /detach_doc_from_message` when the modal closes, tracked via `_sentDocIds`

**History formatting:** `_format_temp_history(history)` — takes last 6 messages, truncates each to 1000 chars, formats as `**User:** / **Assistant:**` blocks injected into the `ask_temp` prompt.

**Model:** `quick_action_model` override, defaulting to `QUICK_ACTION_LLM` (`anthropic/claude-sonnet-4.6`)  
**LLM call:** `temperature=0.4`, `max_tokens=2000` (adjustable: Short=800, Long=4000), streaming  
**System prompt:** "You are a helpful, clear, and engaging assistant. Respond concisely and in brief. Avoid using LaTeX or math notation."
**Tool support:** When tools toggle is active, uses `_run_tool_loop` with `TIER_1_TOOLS` (max 3 iterations) instead of a direct single-shot LLM call.

**Temp LLM modal header controls (same as doubt modal):**
- Length dropdown (S/M/L) — adjusts max_tokens and system prompt instructions
- Tools toggle (🔧) — enables tiered tool calling
- Preamble dropdown (multi-select) — appended to system prompt via `get_preamble()`
- Copy Thread button — copies entire thread as markdown
- Summarize button — sends thread to LLM for concise summary

### Fallback: `direct_temporary_llm_action()`

(`endpoints/llm_actions.py`)

Used when no conversation context is available. Builds the same action prompts but injects history as plain text into the prompt string. Uses `EXPENSIVE_LLM[2]` (or `quick_action_model` if available).  
**System prompt:** same as above but also adds "When using markdown headings you can use only level 4 headers (`####`). Write with the intention to help the user learn and understand better and expand their Knowledge boundaries."

### Action Types

| Action | Prompt focus |
|---|---|
| `explain` | Clear, comprehensive explanation with examples and analogies |
| `critique` | Strengths, weaknesses, logic, evidence, gaps, biases |
| `expand` | More context, details, examples, connections, implications |
| `eli5` | Very simple words, fun analogies, ends with "The Big Idea Is..." |
| `ask_temp` | Multi-turn conversational chat anchored to selected text |

### Key Files

| File | Role |
|---|---|
| `interface/temp-llm-manager.js` | `TempLLMManager` — modal, `currentHistory` array, streaming render, history append, attachment wiring + cleanup |
| `interface/context-menu-manager.js` | Entry points: `executeAction()` and `openTempChatModal()` calls |
| `interface/common-chat.js` | `openAsideChatModal()` helper; `/aside`+`/btw` send intercept; aside button + `Ctrl+Shift+Space` handlers; `uploadFileToConversation()`, `renderDisplayAttachmentBadges()` |
| `interface/parseMessageForCheckBoxes.js` | `processAsideCommand()` — detects `/aside`/`/btw` tokens, sets `result.aside_request=true` |
| `interface/interface.html` | `#asideButton` (💬) next to send button; attachment preview strip + paperclip in temp-LLM modal |
| `endpoints/doubts.py` | `POST /temporary_llm_action` route + streaming generator; reads `display_attachments` from request |
| `endpoints/documents.py` | `DELETE /detach_doc_from_message/<conv_id>/<doc_id>` — cleanup of all attachments on modal close |
| `endpoints/slash_commands.py` | `/aside` and `/btw` entries in `ACTION_COMMANDS` catalog |
| `Conversation.py` ~L12568 | `temporary_llm_action()`, `_get_attached_doc_texts()` — context-aware LLM call with inlined doc text |
| `endpoints/llm_actions.py` | `direct_temporary_llm_action()` — fallback without conversation |

---

## Comparison

| | Doubt Clearing | Temp LLM Actions |
|---|---|---|
| Persisted | Yes — `DoubtsClearing` SQLite table | No — memory only |
| Threaded follow-ups | Yes — linked list via `parent_doubt_id` | Yes — `currentHistory` array (lost on close) |
| Context modes | Target message only / full context | Message context / full context |
| Selected text support | Yes — injected into prompt | Yes — primary input |
| File attachments | Yes — images sent to vision LLM; text docs inlined; persisted in `display_attachments` DB column | Yes — text docs inlined; images not currently sent; all files cleaned up on close |
| Model | `QUICK_ACTION_LLM` (`anthropic/claude-sonnet-4.6`) | `QUICK_ACTION_LLM` via `quick_action_model` override |
| Tools | Optional — tiered (TIER_1_TOOLS, max 3 iters) | Optional — same tiered mode |
| Entry point | Right-click → "Ask a Doubt" | Right-click → explain/critique/expand/eli5/ask |
| View history | Yes — "View Doubts" button on message | No |

---

## Doubts Indicator Button

Messages that have existing doubts show a `<i class="bi bi-chat-left-text"></i>` button in the card header (left side, next to the ⋮ dropdown). Clicking it opens the doubts overview modal. The button is revealed via `GET /get_messages_with_doubts/<conversation_id>` on conversation load and immediately after a new doubt stream completes. See [Message Card Header](../message_card_header/README.md) for full details.

---

## Auto-Doubts System

After every assistant message streams completely, up to 5 pre-emptive doubt threads are created automatically in parallel to maximize learning and understanding. Controlled by the **"Auto-doubts"** checkbox in Chat Settings → Basic Options (default: enabled).

### Threads

| # | Root doubt_text | Structure | Purpose |
|---|---|---|---|
| 1 | **Auto takeaways** | Root + up to 4 children | Summary of key takeaways, then answers each next-question suggestion in detail (parallelized) |
| 2 | **Maximize Learning and Perspectives** | Root + 1 child | Expands on 3-5 critical concepts with intuition → Diverse Expert Perspectives (staff eng, principal eng, ML eng, EM, PM) |
| 3 | **Challenge & Verify** | Root + 1 child | Devil's Advocate (weaknesses, reasoning chains) → Common Mistakes (implementation + production/scale cascading failures) |
| 4 | **Foundations & Practice** | Root + 1 child | Prerequisites Check (mental models, not just definitions) → Apply It (exercise with non-obvious twist + solution) |
| 5 | **Answer Raised Questions** | Root | Finds and answers all questions the LLM posed in its response; skips if no questions found |

### Flow

1. Streaming completes → `generate_response()` puts `<--END-->` on queue
2. Checks `persist_or_not` AND `auto_doubts_enabled` from `checkboxes`
3. Dispatches all 5 functions via `get_async_future()` in parallel
4. Each function:
   - Resolves `message_id` + `answer_text` (fast path if captured during stream, else polls up to 120s)
   - Dedup: skips if a doubt with same `doubt_text` already exists for that message
   - Calls `gemini-flash-3.5-non-reasoning` (fast, cheap) — except Auto Takeaways root which uses `VERY_CHEAP_LLM[0]`
   - Persists via `add_doubt()` with appropriate `parent_doubt_id` for threading

### Auto Takeaways — Next-Question Expansion

After creating the root summary, waits (initial 10s then polls every 1s up to 60s total) for `conversation.next_question_suggestions` (set by `persist_current_turn()`), then for each suggestion (up to 4):
- Answers the question in detail (reasoning, intuition, examples) using conversation context
- All 4 LLM calls run in parallel via `ThreadPoolExecutor(max_workers=4)`
- Results are chained in order as a linked-list thread

### Internal Parallelization

Within each doubt function, sub-prompts also run in parallel:
- **Maximize Learning**: learning concepts + diverse perspectives → 2 parallel LLM calls
- **Challenge & Verify**: devil's advocate + common mistakes → 2 parallel LLM calls
- **Foundations & Practice**: prerequisites + apply-it exercise → 2 parallel LLM calls
- **Auto Takeaways** children: all 4 next-Q answers → 4 parallel LLM calls

### Configuration

- **UI**: "Auto-doubts" checkbox in Basic Options (`#settings-auto_doubts_enabled`), default checked
- **Backend key**: `checkboxes.auto_doubts_enabled` (default: `True`)
- **Slash commands**: `/enable_auto_doubts` and `/disable_auto_doubts` for per-turn override
- **Browser persistence**: localStorage via `chatSettingsState` — persists across sessions on same device (same mechanism as all Basic Options: persist, use_pkb, auto_pkb_extract, etc.)
- **Cross-device**: Not synced (same limitation as all Basic Options — localStorage only)
- **Per-conversation override**: Not currently supported. The setting is global. Could be extended via `PUT /set_conversation_settings` in future.

### Key Files

| File | What |
|------|------|
| `endpoints/conversations.py` ~L1830 | Scheduling block (dispatches all 5) |
| `endpoints/conversations.py` `_create_auto_takeaways_doubt_for_last_assistant_message` | Takeaways + next-Q children |
| `endpoints/conversations.py` `_create_maximize_learning_doubt` | Critical concepts expansion |
| `endpoints/conversations.py` `_create_challenge_and_verify_doubt` | Devil's Advocate + Common Mistakes |
| `endpoints/conversations.py` `_create_foundations_and_practice_doubt` | Prerequisites + Apply It |
| `endpoints/conversations.py` `_create_answer_raised_questions_doubt` | Answers LLM's own questions |
| `endpoints/conversations.py` `_resolve_message_id_and_text` | Shared helper for message resolution |
| `interface/interface.html` | Checkbox (`#settings-auto_doubts_enabled`) |
| `interface/chat.js` | Settings state wiring |
| `interface/common.js` `getOptions()` | Includes `auto_doubts_enabled` in checkboxes payload |


---

## 3. Doubt System Enhancements (2026-06)

The following features extend the base doubt clearing system with richer UX, knowledge management, and configurability.

### New Schema Columns

Added to `DoubtsClearing` table:
- `with_context` (boolean, DEFAULT 0) — preserves whether the doubt was created with conversation context
- `pinned` (boolean, DEFAULT 0) — user can pin important root doubts for priority sorting
- `bookmarked` (boolean, DEFAULT 0) — user can bookmark specific answers within a thread

### New Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/pin_doubt/<doubt_id>` | POST | Toggle pinned state. Body: `{ "pinned": bool }` |
| `/bookmark_doubt/<doubt_id>` | POST | Toggle bookmarked state. Body: `{ "bookmarked": bool }` |
| `/regenerate_doubt/<doubt_id>` | POST | Re-run LLM, stream new answer, update in-place. Body: `{ "preamble_options": [...] }` |
| `/summarize_doubt_thread/<doubt_id>` | POST | Summarize thread using `senior_engineer_summary_prompt`. Saves as new child doubt. |
| `/create_conversation_from_doubt_thread/<doubt_id>` | POST | Create new conversation seeded with doubt thread as `running_summary`. |
| `/get_all_doubts` | GET | Paginated cross-conversation doubts. Params: `page`, `page_size`, `search`, `filter` (all/pinned/user/auto). |

### Feature: Pin/Star Doubts

- Pin button (📌) on each preview card in the doubts overview modal
- Pinned doubts sort first, then user-created, then auto-doubts
- Visual: blue left border + light blue background on pinned cards
- Auto-doubt cards get a "Auto" badge for visual distinction

### Feature: Bookmarks

- Bookmark button (🔖) on assistant answer cards in the doubt chat modal
- Bookmarked state persisted per-doubt
- Overview cards show bookmark count badge when children are bookmarked

### Feature: Doubt Answer Regeneration

- ↻ button in the header of each assistant doubt answer card
- Streams new answer in-place (reuses `clear_doubt` with same parameters)
- Updates `doubt_answer` in DB without creating a new record
- Warning toast if the doubt has children (follow-ups based on old answer)

### Feature: Inline Length/Preamble/Tools Controls

- Control bar at top of both doubt chat modal and temp LLM modal with:
  - **Length dropdown**: Single button showing S/M/L label; click reveals Short/Medium/Long options. Replaces the old 3-button pill group to save space.
  - **Tools toggle**: 🔧 button — click to activate (turns blue). When active, enables tiered tool calling (`TIER_1_TOOLS`: 12 tools including perplexity_search, jina_search, document_lookup, pkb_search, delegate_task, request_tools). Uses `_run_tool_loop` with max 3 iterations. Off by default.
  - **Preamble selector**: multi-select dropdown, same options as settings modal doubt preamble
- Length maps to preamble in doubt: Short adds "Short", Long adds "Long", Medium = neither
- Length maps to max_tokens in temp LLM: Short=800, Medium=2000, Long=4000
- Preamble options in temp LLM: appended to system prompt via `get_preamble()`
- Tools: when enabled, the backend loads `TIER_1_TOOLS` via `TOOL_REGISTRY.get_openai_tools_param()` and calls `_run_tool_loop()` — the same tool-calling loop as the main conversation flow. `request_tools` meta-tool allows on-demand expansion to the full tool registry (free, no iteration cost).

### Feature: Copy Thread

- "Copy Thread" button in doubt chat modal header
- Copies entire Q&A thread as formatted markdown (`## Q: / answer / ---`)
- Uses `navigator.clipboard` API

### Feature: Doubt Thread Summarization

- "Summarize" button in doubt chat modal header
- Calls `/summarize_doubt_thread/<doubt_id>` which:
  - Collects full thread via BFS from all ancestors
  - Builds context from `running_summary` + doubt Q&A pairs only (NOT raw chat messages)
  - Uses `senior_engineer_summary_prompt` from `prompts.py`
  - Streams response and saves as new child doubt with `doubt_text = "Thread Summary"`

### Feature: "Continue Doubt in Main Chat"

- Context menu item: "Continue doubt in main chat"
- Fetches doubts for the message, shows picker if multiple threads
- Injects selected thread's Q&A as `[Doubt Context]...[/Doubt Context]` block into main chat input
- One-shot injection: user types next message which includes the doubt context

### Feature: Doubt Thread as Conversation Seed

- "New Chat" button in doubt chat modal header
- Calls `/create_conversation_from_doubt_thread/<doubt_id>` which:
  - Creates new conversation with same domain as source
  - Sets `running_summary` to formatted doubt thread content
- Frontend navigates to the new conversation after creation

### Feature: Doubt Notification (Pulse + Toast)

- After assistant reply streaming completes, a 25s delayed poll checks for new doubts
- Newly-revealed `.has-doubts-btn` buttons get a pulse animation (CSS `doubt-new-pulse`)
- Toast notification: "✨ Learning aids ready for your last reply"
- First reveal at 5s (no pulse), second poll at 25s (with pulse + toast)

### Feature: Selective Auto-Doubts (Per-Conversation)

- 5 category checkboxes below the "Auto-doubts" checkbox in settings:
  - takeaways, maximize_learning, challenge_verify, foundations_practice, answer_questions
- Saved via `PUT /set_conversation_settings` as `auto_doubt_categories` list
- Backend dispatch loop only runs categories present in the list (None = all)
- Show/hide with auto-doubts checkbox toggle

### Feature: Auto-Doubt Model Override

- Per-conversation model override: `auto_doubt_model`
- Dropdown in Model Overrides modal
- All 5 auto-doubt functions use `conversation.get_model_override("auto_doubt_model", "gemini-flash-3.5-non-reasoning")`
- Default: `gemini-flash-3.5-non-reasoning` (unchanged behavior)

### Feature: Global "My Doubts" Modal (Cross-Conversation)

- Entry point: sidebar toolbar button (journal-bookmark icon)
- Full-screen modal showing all root doubts across all conversations
- Search bar: free-text search across `doubt_text` and `doubt_answer`
- Filter pills: All / Pinned / My Doubts / Auto
- Pagination (20 per page)
- Click navigates to source conversation and opens the doubt thread
- Auto-doubt detection uses LIKE prefix matching for robustness

### Feature: Doubt Preambles

- Separate preamble selector for doubts in settings modal (`#settings-doubt-preamble-selector`)
- Safe preambles: None, Wife Prompt, Short, Deep Learn, Software and ML Learning, Senior Engineer Summary, Senior Engineer Mental Models, Argumentative, No AI
- Sent as `preamble_options` in `/clear_doubt` and `/regenerate_doubt` requests
- Backend calls `self.get_preamble(preamble_options, None)` and appends to system prompt

### Feature: Threading UX Improvements

- Overview modal sorts: pinned first → user-created → auto-doubts (each by date desc)
- Preview cards: collapsible answer (click body to toggle), visual hierarchy
- Separate visual treatment for pinned (blue border) and auto (badge) cards

### Key Files (Updated)

| File | New Additions |
|---|---|
| `interface/doubt-manager.js` | Pin/bookmark handlers, regen streaming, summarize, copy thread, global doubts modal, inline controls |
| `interface/context-menu-manager.js` | "Continue doubt in main chat" handler + doubt picker |
| `interface/common-chat.js` | `revealDoubtsButtons(conversationId, withPulse)` — pulse + toast notification |
| `interface/chat.js` | Auto-doubt category checkboxes, model override save/load |
| `endpoints/doubts.py` | 6 new routes: pin, bookmark, regenerate, summarize, get_all, create_from_thread |
| `endpoints/conversations.py` | `_AUTO_DOUBT_DISPATCH` dict, `auto_doubt_categories` validation, model override |
| `database/doubts.py` | `update_doubt_pinned()`, `update_doubt_bookmarked()`, `update_doubt_answer()`, `get_all_doubts_for_user()` |
| `database/connection.py` | `pinned` + `bookmarked` column migrations |


### Feature: Responsive Table Rendering

- All markdown tables in chat messages, doubt answers, and temp LLM responses are wrapped in `<div class="table-responsive" style="overflow-x:auto;">` via a `markdownParser.table` renderer override in `interface/common.js`.
- Prevents wide tables from causing horizontal scrolling on the entire page — tables scroll independently within their container.
- Single override covers all rendering paths (main messages via `renderInnerContentAsMarkdown`, doubt `marked.parse`, temp LLM `marked.parse`, streaming updates) since all go through the same global `markdownParser` renderer.

### Feature: Quick Action Model Constant

- `QUICK_ACTION_LLM = "anthropic/claude-sonnet-4.6"` defined in `common.py` alongside other model constants.
- Used as default by both `clear_doubt()` and `temporary_llm_action()` via `self.get_model_override("quick_action_model", QUICK_ACTION_LLM)`.
- Overridable per-conversation via model overrides settings.
- Separate from `SUPERFAST_LLM` (used for internal conversation operations like summarization, keyword extraction).


### Feature: Move Pair as Doubt

A message pair (user + assistant) anywhere in the conversation history can be promoted to a doubt on the **preceding assistant message** without losing the content.

**Motivation:** Sometimes a follow-up exchange in the main chat thread is really a clarification/side-question that belongs in the doubts layer rather than the primary conversation log. Moving it keeps the main thread clean while preserving the Q&A.

**UI entry point:** "Move Pair as Doubt" item in the per-message triple-dot dropdown menu, placed immediately after "Delete Pair". Uses the amber `text-warning` color to distinguish it from the red danger actions. The item is **hidden** (`display:none`) when no valid preceding assistant message exists (user message at index 0, or assistant message at index 0 or 1).

**Flow:**
1. User clicks "Move Pair as Doubt" on either card of the pair.
2. Client POSTs `POST /move_pair_as_doubt/<conversation_id>/<message_id>/<index>`.
3. Backend validates the pair, locates the preceding assistant message (the "target"), creates a doubt record with:
   - `doubt_text` = `[Promoted from Chat] <user message text>`
   - `doubt_answer` = assistant message text (verbatim, no LLM call)
   - `message_id` = the preceding assistant message's ID
4. Backend calls `conversation.delete_message_pair()` to remove both messages from chat history.
5. Backend deletes any existing doubts attached to the two promoted messages (they would otherwise become orphans with no card to attach to).
6. Response: `{ doubt_id, target_message_id, deleted_message_ids }`.
7. Client removes both cards from the DOM, calls `reindexMessageCards()`, reveals the `.has-doubts-btn` on the target card, shows a "Pair moved to doubts" success toast.

**`[Promoted from Chat]` prefix** appears in the `doubt_text` (question side only) so that when you open the doubts overview for the target message you can immediately see which entries came from the main chat vs. ones you typed directly.

**Backend:** `POST /move_pair_as_doubt/<conversation_id>/<message_id>/<index>` in `endpoints/conversations.py`. Rate-limited to 60/min. Requires login.

**Error states:**
- No valid pair at the index → 400 `no_pair_found`
- No preceding message → 400 `no_preceding_message`
- Preceding message is not an assistant message → 400 `no_preceding_assistant`
- `add_doubt` fails → 500 `doubt_creation_failed` (no messages deleted)
- Pair deletion fails after doubt created → 500 `pair_deletion_failed` (inconsistency logged; doubt exists but pair remains in history)

**Files modified:**
- `endpoints/conversations.py` — `move_pair_as_doubt` route
- `interface/common-chat.js` — "Move Pair as Doubt" item in `actionDropdown` template
- `interface/common.js` — delegated `.move-pair-as-doubt-button` click handler

---

### Doubt Cleanup on Message Deletion

When a message is deleted from conversation history, any doubts attached to that `message_id` in `DoubtsClearing` would previously become **orphaned rows** — still in the DB, but no longer reachable from any message card in the UI.

All four delete endpoints now clean up doubts for every deleted message after the deletion succeeds (non-fatal: logged but does not fail the request):

| Endpoint | Which message IDs are cleaned |
|---|---|
| `DELETE /delete_message_from_conversation/<cid>/<mid>/<idx>` | The single `message_id` from the URL (skipped if value is `"undefined"`, `"None"`, `"nan"`, or `""`) |
| `DELETE /delete_message_pair/<cid>/<mid>/<idx>` | All IDs returned by `conversation.delete_message_pair()` (0–2 IDs) |
| `DELETE /delete_last_message/<cid>` | Last 2 message IDs snapshotted from the message list **before** `delete_last_turn()` is called |
| `POST /move_pair_as_doubt/<cid>/<mid>/<idx>` | Both messages in the promoted pair (their doubts would be unreachable since the messages are removed) |

**Cleanup logic** (same pattern in all four):
1. Call `get_doubts_for_message(conversation_id, message_id, user_email)` to fetch all root doubts for the message.
2. For each root doubt, call `delete_doubt(doubt_id)` which BFS-walks and bulk-deletes the entire subtree.
3. Both calls are wrapped in individual `try/except` blocks so a failure on one message or one doubt does not prevent the rest from being cleaned up.

**Whole-conversation delete** (`DELETE /delete_conversation`) already issued `DELETE FROM DoubtsClearing WHERE conversation_id IN (...)` — that path is unchanged.

**Files modified:** `endpoints/conversations.py` — all four delete routes.

---

### Feature: Progressive Disclosure (TL;DR / Explanation / Deep Dive)

**Motivation:** Auto-doubt answers are long but users often only need the gist. Progressive disclosure structures answers into 3 collapsible tiers so users can skim the TL;DR and expand only what interests them.

**LLM Output Format:**
- System prompt appended with 3-section formatting instruction (skipped when "Short" preamble is active)
- Markers: `<tldr>...</tldr>`, `<explanation>...</explanation>`, `<deep_dive>...</deep_dive>`
- Applied to `clear_doubt()` in Conversation.py and all 8 long-answer auto-doubt functions via `_DOUBT_SECTION_FMT` constant

**Frontend Rendering:**
- `createDoubtChatCard` detects all 3 markers → renders as collapsible `<details class="section-details">` elements
- TL;DR: always visible (no collapse), styled with blue left border
- Explanation: `<details open>` by default for user doubts, uses persisted state
- Deep Dive: `<details>` (closed by default), uses persisted state
- During streaming: markers stripped from display text (`</?(?:tldr|explanation|deep_dive)>` regex), final re-render applies sections on completion
- Fallback: if markers are missing or answer is too short, renders as plain markdown (no sections)

**State Persistence:**
- Reuses existing `SectionHiddenDetails` table with `doubt_{doubt_id}_explain` and `doubt_{doubt_id}_deep` keys
- Toggle handler in `setupChatEventHandlers` calls `persistSectionState(conversationId, sectionHash, isHidden)`
- `/get_doubts` response includes `section_states` dict (all `doubt_*` prefixed section states for the conversation)
- `_sectionStates` stored on `DoubtManager` instance from API response

**Defaults:**
- Explanation: open (unless user previously collapsed it)
- Deep Dive: closed (unless user previously opened it)
- Card-level collapse (`ensureDoubtAnswerToggle`) is skipped when progressive disclosure sections are present

**Key Files:**
- `Conversation.py` ~L12730 — section format instruction in `clear_doubt()` system prompt
- `endpoints/conversations.py` — `_DOUBT_SECTION_FMT` constant, appended to 8 auto-doubt system prompts
- `endpoints/doubts.py` — `section_states` in `/get_doubts` response via `get_all_section_hidden_details`
- `interface/doubt-manager.js` — section parsing in `createDoubtChatCard`, post-streaming re-render, toggle handler, marker stripping during streaming
- `interface/interface.html` — `.doubt-progressive-disclosure` CSS styling

---

## Feature: Edit the Answer from the Doubt Flow

**Motivation:** Sometimes, while clearing a doubt about an assistant answer, the user realises the answer itself is wrong, incomplete, or could be phrased better. Instead of switching to the main edit dialog and re-typing, the user can simply ask the doubt LLM to update the answer. The doubt LLM proposes targeted text replacements, the user reviews a diff, and on approval the message is edited in place — with the original preserved so the change can be reverted.

### UX Flow

1. User opens a doubt on an assistant message and types something like *"update the answer to fix the time-complexity explanation"*.
2. The doubt LLM calls the `propose_answer_edit` tool with one or more `{old_text, new_text}` replacements (it may call `read_message` first to get the exact current text).
3. The backend validates each replacement against the current message text, computes a unified diff, and streams a special `answer_edit_proposal` chunk to the frontend.
4. The frontend opens the **Answer Edit diff modal** (`#answer-edit-diff-modal`) showing the diff, a summary, replacement match stats, and any warnings (e.g. replacements whose `old_text` wasn't found).
5. The user clicks **Accept & Apply** (or **Reject**). On accept, the frontend POSTs the matched replacements to the edit API.
6. The message card re-renders with the updated text. The original text is snapshotted server-side so a **Revert to Original** option becomes available.

**No false success on stale proposals:** the apply API re-validates every replacement against the *current* stored message text (not the text captured when the proposal was generated). `apply_message_replacements()` returns `(new_text, applied_count)` and only writes when `applied_count > 0`. If nothing matches — e.g. the answer changed between proposal and accept, or `old_text` differs by whitespace/markdown — the endpoint returns **HTTP 409 `no_replacements_matched`** instead of a misleading 200, the frontend shows a warning, and the card is left unchanged (so it no longer "appears edited then reverts on reload"). At the storage layer, `ConversationStore.edit_message()` raises `ValueError` if the `UPDATE` matches zero rows, converting a silent no-op into a loud failure.

**Important — edit only on explicit request:** The doubt system prompt instructs the LLM to call `propose_answer_edit` *only when the user explicitly asks to update/fix/edit the answer*. Normal doubt questions never trigger an edit proposal. Even when proposed, nothing is saved until the user approves the diff.

### Always-On Doubt Editor Tools

Two tools are **always** available in the doubt flow, independent of the 🔧 tools toggle:

- `read_message` — read the full current text of the target message.
- `propose_answer_edit` — propose text replacements for the target message (diff preview, user-approved).

These are defined as `DOUBT_DEFAULT_TOOLS = ["read_message", "propose_answer_edit"]` in `code_common/tools.py`. The doubt flow always runs through `_run_tool_loop` with these tools; `TIER_1_TOOLS` are merged in **only** when `tools_enabled` is on (the user's tools toggle). `clear_doubt()` passes `target_message_id` into the tool loop so `propose_answer_edit` knows which message to target even if the LLM omits the `message_id` argument.

### Tool: `propose_answer_edit`

- **Definition:** `code_common/conversation_search.py` (`CONVERSATION_TOOLS["propose_answer_edit"]`).
- **Handler:** `handle_propose_answer_edit()` in `code_common/tools.py`.
- **Parameters:** `conversation_id`, `message_id`, `replacements: [{old_text, new_text}]`, optional `summary`.
- **Behaviour:** Reads the target message, applies each replacement to an in-memory copy (first-occurrence exact-string match), marks each replacement `found: true/false`, computes a `difflib.unified_diff`, and returns a JSON proposal. It does **not** modify the message. If no `old_text` matched, it returns an error telling the LLM to call `read_message` for the exact text.
- **Proposal payload:** `{ proposal_type: "answer_edit", message_id, conversation_id, replacements (validated), original_text, new_text, diff_text, summary, found_count, total_count }`.

### Streaming the Proposal

- `_run_tool_loop` now includes `result_full` (the untruncated tool result) in every `tool_result` chunk.
- `clear_doubt()` detects a `tool_result` chunk whose `tool_name == "propose_answer_edit"`, parses `result_full`, and **yields a dict** `{ "type": "answer_edit_proposal", ... }` instead of plain text. The tool result is not echoed into the doubt answer text.
- `endpoints/doubts.py` passes any dict chunk through as a raw newline-delimited JSON line (text chunks are still wrapped as `doubt_clearing`).
- `interface/doubt-manager.js` detects `part.type === 'answer_edit_proposal'` in the streaming handler and calls `showAnswerEditDiffModal(part)`.

### Edit API (replacements support)

`POST /edit_message_from_conversation/<conversation_id>/<message_id>/<index>` now accepts **either**:
- `{ "text": "<full new text>" }` — full-body replace (legacy behaviour), or
- `{ "replacements": [{ "old_text": "...", "new_text": "..." }, ...] }` — sequential first-occurrence replacements applied to the current text.

Response: `{ message, new_text }`. The replacements path calls `Conversation.apply_message_replacements()`.

### Revert Support (multi-version undo stack)

Reverting is **multi-level**: every edit pushes the prior text onto a per-message version stack, and each revert pops one step, walking back through edits one at a time rather than jumping straight to the original.

- **Storage:** two columns on the `messages` table (`database/conversation_store.py`, each with an `ALTER TABLE … ADD COLUMN` migration for existing DBs):
  - `edit_history` — a JSON array (stack) of all prior versions, oldest first. `edit_message()` appends the current text before overwriting.
  - `original_text` — kept in sync with `edit_history[0]` (the pre-first-edit text). It is preserved purely for backward compatibility with the single-level UI check (`original_text != null` ⇔ "something to revert"). The JSON-store path mirrors both fields on the message dict.
- **Revert API:** `POST /revert_message_from_conversation/<conversation_id>/<message_id>/<index>` → `Conversation.revert_message()` pops the top of `edit_history`, restores it to `text`, and updates `original_text`/`edit_history` (clearing them when the stack empties). Returns `{ message, text, versions_remaining }`, where `versions_remaining` is how many further undo steps are still possible. Returns 409 `no_original` when there is nothing left to revert. Pre-stack data (only `original_text`, no `edit_history`) is handled by seeding a single-element stack.
- **`get_message_text`** returns `original_text` (or `null`) and `edit_versions` (the stack depth) so the UI can decide whether to show the undo option.
- **UI:** `initialiseVoteBank()` (`interface/common.js`) adds an **Undo Last Edit** item to the assistant card's triple-dot vote menu. It is hidden by default and revealed when either the card carries `data-has-original="true"` (set after an accepted edit, or after a revert that leaves earlier versions) or a background `get_message_text` check reports a non-null `original_text`. Clicking it confirms, calls the revert API, re-renders the card, re-inits the vote bank, and—using `versions_remaining`—keeps the undo item visible while earlier versions remain (toast reports how many are left).

### Diff Rendering Reuse

The diff modal reuses the artefact diff renderer. `interface/artefacts-manager.js` now exports `parseUnifiedDiff`, `buildDiffLine`, and `renderDiffInContainer(container, diffText)`; `doubt-manager.js` calls `ArtefactsManager.renderDiffInContainer()` (with a `<pre>` fallback). The modal reuses the existing `.artefact-diff-*` CSS classes (add = green, del = red).

### Files Modified

| File | Change |
|---|---|
| `database/conversation_store.py` | `original_text` + `edit_history` columns + migrations; `edit_message()` pushes prior text onto the stack; `get_original_text()`, `revert_message()` (pops one version, returns `(text, versions_remaining)`); `_msg_to_dict` includes `original_text`/`edit_history` |
| `Conversation.py` | `edit_message()` maintains the version stack (JSON path); new `apply_message_replacements()`, `revert_message()` (one-step undo, returns `{text, versions_remaining}`); `_run_tool_loop` `target_message_id` param + `result_full`; `clear_doubt()` always-on editor tools + `answer_edit_proposal` emission |
| `code_common/conversation_search.py` | `propose_answer_edit` tool definition |
| `code_common/tools.py` | `handle_propose_answer_edit`; `ToolContext.target_message_id`; `DOUBT_DEFAULT_TOOLS` constant |
| `endpoints/conversations.py` | edit API `replacements` support; `/revert_message_from_conversation` returns `versions_remaining`; `original_text` + `edit_versions` in `get_message_text` |
| `endpoints/doubts.py` | pass dict chunks through as raw JSON lines |
| `interface/interface.html` | `#answer-edit-diff-modal` |
| `interface/doubt-manager.js` | `answer_edit_proposal` handling, `showAnswerEditDiffModal()`, `_applyAnswerEdit()`, `_doubtEscapeHtml` |
| `interface/artefacts-manager.js` | exported `parseUnifiedDiff`/`buildDiffLine`/`renderDiffInContainer` |
| `interface/common.js` | "Undo Last Edit" vote-menu item in `initialiseVoteBank()` (multi-version, uses `versions_remaining`) |
