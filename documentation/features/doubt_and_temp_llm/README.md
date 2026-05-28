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

A separate **"View Doubts"** button on each message opens a doubts overview modal showing all past doubt threads for that message, rendered as nested trees.

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
**`DELETE /delete_doubt/<doubt_id>`** — delete with tree restructuring  
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
| `delete_doubt()` | Deletes node and re-parents its children to its parent (linked-list deletion) |

**When is the answer saved?** Only after the full stream completes, in the `finally` block of the stream generator. If streaming is interrupted, a partial answer may still be saved if `accumulated_doubt_answer` is non-empty.

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
