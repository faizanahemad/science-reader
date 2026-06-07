# Doubt Clearing & Temporary LLM Actions

Two related but distinct systems for asking questions about message content without affecting the main conversation thread.

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

### API

**`POST /clear_doubt/<conversation_id>/<message_id>`** (`endpoints/doubts.py`)

Request body:
```json
{
  "doubt_text": "string",
  "reward_level": 0,
  "selected_text": "optional highlighted text",
  "with_context": false,
  "parent_doubt_id": "optional, for follow-ups"
}
```

Streaming response (newline-delimited JSON):
- Each chunk: `{ text, status, conversation_id, message_id, type: "doubt_clearing", accumulated_text }`
- Final chunk: `{ completed: true, doubt_id: "...", accumulated_text }`

**`GET /get_doubts/<conversation_id>/<message_id>`** — returns all doubt trees for a message  
**`GET /get_doubt/<doubt_id>`** — fetch a single doubt record  
**`DELETE /delete_doubt/<doubt_id>`** — delete a doubt and its entire sub-tree (recursive). Response includes `deleted_doubt_ids` (the target plus all descendants).  
**`POST /show_hide_doubt/<doubt_id>`** — persist a doubt answer card's collapse state (body `{ "show_hide": "show" | "hide" }`)  
**`POST /cancel_doubt_clearing/<conversation_id>`** — cancel an in-progress stream

### Backend: `Conversation.clear_doubt()`

(`Conversation.py`, line ~12427)

Parameters: `message_id, doubt_text, doubt_history, reward_level, selected_text="", with_context=False`

**Context building logic:**

- Always calls `get_context_around_message(message_id, before=4, after=2)` to fetch the target message and surrounding messages
- **`with_context=False`** (default): only the single target message is included in the prompt
- **`with_context=True`**: includes the conversation `running_summary` + all surrounding context messages, with the target marked `← [TARGET MESSAGE]`
- If `selected_text` is non-empty: injects `**Selected Text the user is asking about:** "..."` into the prompt between the context block and the user's doubt question
- If `doubt_history` is non-empty (follow-up): prepends the full prior Q&A thread as "Previous Doubt History"

**LLM call:** `temperature=0.3`, `max_tokens=2000`, streaming  
**System prompt:** "You are a helpful AI assistant specializing in clarifying doubts and explaining complex concepts clearly and thoroughly. Avoid using markdown headers and avoid excessive formatting. Write with the intention to help the user learn and understand better without formatting bloat."

After streaming completes, the endpoint saves the Q&A to the DB via `database.doubts.add_doubt()`.

### Storage: `DoubtsClearing` table in `users.db`

(`database/doubts.py`)

```
doubt_id          — MD5(conversation_id + message_id + doubt_text + answer + timestamp + parent_id)
conversation_id
user_email
message_id        — the message this doubt is about
doubt_text        — user's question
doubt_answer      — full LLM response (saved after streaming completes)
parent_doubt_id   — NULL for root doubts; points to parent for follow-ups
child_doubt_id    — forward pointer to next follow-up (singly linked)
is_root_doubt     — 1 if no parent
show_hide         — 'show' | 'hide' collapse state of the answer card in the doubt modal (NULL/empty = expanded)
created_at
updated_at
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
| `interface/doubt-manager.js` | `DoubtManager` — modal, state (`selectedText`, `withContext`, `currentDoubtHistory`), API call, streaming render |
| `interface/context-menu-manager.js` | `handleAskDoubt(withContext)` — entry point from right-click menu |
| `endpoints/doubts.py` | All doubt HTTP routes + streaming generator |
| `Conversation.py` ~L12427 | `clear_doubt()` — context building + LLM call |
| `database/doubts.py` | All SQLite operations on `DoubtsClearing` |

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
  "with_context": false
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

**History formatting:** `_format_temp_history(history)` — takes last 6 messages, truncates each to 1000 chars, formats as `**User:** / **Assistant:**` blocks injected into the `ask_temp` prompt.

**Model:** `quick_action_model` override, defaulting to `SUPERFAST_LLM[0]`  
**LLM call:** `temperature=0.4`, `max_tokens=2000`, streaming  
**System prompt:** "You are a helpful, clear, and engaging assistant. Respond concisely and in brief. Avoid using LaTeX or math notation."

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
| `interface/temp-llm-manager.js` | `TempLLMManager` — modal, `currentHistory` array, streaming render, history append |
| `interface/context-menu-manager.js` | Entry points: `executeAction()` and `openTempChatModal()` calls |
| `interface/common-chat.js` | `openAsideChatModal()` helper; `/aside`+`/btw` send intercept; aside button + `Ctrl+Shift+Space` handlers |
| `interface/parseMessageForCheckBoxes.js` | `processAsideCommand()` — detects `/aside`/`/btw` tokens, sets `result.aside_request=true` |
| `interface/interface.html` | `#asideButton` (💬) next to send button |
| `endpoints/doubts.py` | `POST /temporary_llm_action` route + streaming generator |
| `endpoints/slash_commands.py` | `/aside` and `/btw` entries in `ACTION_COMMANDS` catalog |
| `Conversation.py` ~L12568 | `temporary_llm_action()` — context-aware LLM call |
| `endpoints/llm_actions.py` | `direct_temporary_llm_action()` — fallback without conversation |

---

## Comparison

| | Doubt Clearing | Temp LLM Actions |
|---|---|---|
| Persisted | Yes — `DoubtsClearing` SQLite table | No — memory only |
| Threaded follow-ups | Yes — linked list via `parent_doubt_id` | Yes — `currentHistory` array (lost on close) |
| Context modes | Target message only / full context | Message context / full context |
| Selected text support | Yes — injected into prompt | Yes — primary input |
| Model | `EXPENSIVE_LLM` (doubt model) | `SUPERFAST_LLM` via `quick_action_model` override |
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
