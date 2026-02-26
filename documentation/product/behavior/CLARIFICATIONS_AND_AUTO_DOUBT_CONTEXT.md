# Clarifications Feature — Implementation Reference

## Overview

This document describes the implemented clarification system and the planned (not yet built) automatic doubt generation feature.

**Feature 1: `/clarify` Slash Command** — **IMPLEMENTED**
- User types `/clarify` (or `/clarification`, `/clarifications`) anywhere in a message
- On Enter, the clarification flow fires instead of sending the message
- The backend generates 1–3 clarifying questions using the conversation context, PKB, and conversation summary
- Answers are appended to the message composer as a structured `[Clarifications]` block
- Multiple rounds of `/clarify` are supported, each separated by `---`

**Feature 2: Automatic Doubt Generation ("Auto Takeaways")** — **PLANNED, NOT YET IMPLEMENTED**
- After a reply completes, automatically generate a crisp summary as a persistent doubt
- See section at the bottom of this file for the design notes

---

## Feature 1: `/clarify` Slash Command

### Frontend — Command Detection (`interface/parseMessageForCheckBoxes.js`)

`processClarifyCommand(result, lines)` scans every line of the raw message for `/clarify`, `/clarification`, or `/clarifications` tokens that are NOT inside backtick spans (inline code or fenced code blocks). When found:
- Sets `result.clarify_request = true`
- Strips the token from that line

This is called from `parseMessageForCheckBoxes()` which runs before `sendMessageCallback()` inspects the options.

### Frontend — Send Intercept (`interface/common-chat.js`)

In `sendMessageCallback()`, after parsing checkboxes:

```javascript
if (options.clarify_request) {
    // Strip /clarify tokens from raw messageText (preserving newlines)
    let cleanedText = messageText
        .replace(/[ \t]*\/clarif(?:ications?|y)?\b[ \t]*/gi, '')
        .replace(/^[ \t]*\n/mg, '')
        .replace(/\s+$/, '');

    // Update textarea with cleaned text (use raw assignment, not jQuery .val(),
    // to preserve newlines correctly)
    document.getElementById('messageText').value = cleanedText;

    // Fire clarification flow — do NOT send the message
    ClarificationsManager.requestAndShowClarifications(
        conversationId,
        cleanedText,
        { autoSend: false, forceClarify: true }
    );
    return; // abort normal send
}
```

Key detail: `cleanedText` is derived from raw `messageText` (not from `parsed_message.text`). Using `parsed_message.text` collapses whitespace/newlines, which would corrupt multi-line messages.

---

### ClarificationsManager (`interface/clarifications-manager.js`)

Central object managing the clarification modal and state.

**State fields**:
- `currentConversationId` — active conversation
- `currentMessageText` — the cleaned message text (without `/clarify` tokens)
- `forceClarify` — boolean, true when triggered by the slash command

**`requestAndShowClarifications(conversationId, messageText, opts)`**:
- Entry point. Called by the slash command intercept and also by the "Clarify" button (manual trigger).
- Stores `opts.forceClarify` in `this.forceClarify`
- Shows the modal in loading state
- Calls `_fetchClarifications()`

**`_fetchClarifications(conversationId, messageText)`**:
- `POST /clarify_intent/<conversationId>` with body:
  ```json
  {
    "messageText": "...",
    "checkboxes": { ... },
    "forceClarify": true
  }
  ```

**`_handleClarificationsResponse(data)`**:
- If `forceClarify=true` and `data.needs_clarification === false`:
  - Shows toast: "No further questions found"
  - Closes modal
  - Does **NOT** auto-send the message
- If questions present: renders them in the modal

**`_buildNewEntries(questions)`**:
- Always starts Q numbering from 1 regardless of how many rounds have been done
- No cross-round Q number continuity

**`applyToComposer(answers)`**:
- Reads current textarea value
- Checks whether a `[Clarifications]` block already exists
- If no existing block: appends `\n\n[Clarifications]\n` + Q1-based entries
- If block exists (multi-round): appends `\n---\n` + Q1-based entries for this round
- Updates `document.getElementById('messageText').value` directly (not jQuery `.val()`) to preserve newlines

---

### Multi-Round Clarification Format

Each `/clarify` call appends a new block. The first round starts the `[Clarifications]` header. Subsequent rounds are separated by `---`. Q numbering resets to Q1 each round.

```
Write a blog post about AI

[Clarifications]
- Q1: What format do you want?
  A: Bullet points
- Q2: How detailed?
  A: Very detailed

---
- Q1: Target audience?
  A: Software developers
- Q2: Tone?
  A: Informal and engaging
```

**Critical constraints** (bugs previously fixed):
- Newlines in the message are preserved by using the raw `messageText` string, not the parsed version
- Pasting multi-line clarification blocks into the textarea no longer loses leading lines (raw DOM assignment vs jQuery `.val()`)
- Q numbering never bleeds across rounds

---

### Backend Endpoint — `POST /clarify_intent/<conversation_id>` (`endpoints/conversations.py`)

**Rate limit**: 30/minute. **Auth**: `@login_required`.

**Request body**:
```json
{
  "messageText": "string",
  "checkboxes": {},
  "forceClarify": false
}
```

**Response**:
```json
{
  "needs_clarification": true,
  "questions": [
    {
      "id": "q1",
      "prompt": "What aspect are you interested in?",
      "options": [
        {"id": "opt1", "label": "Technical details"},
        {"id": "opt2", "label": "High-level overview"}
      ]
    }
  ]
}
```

**Fail-open**: If the LLM fails or JSON parse errors, returns `{"needs_clarification": false, "questions": []}`.

---

### Context Used in Clarification Prompt

The clarification endpoint builds a rich prompt using four context sources:

1. **Conversation Summary** — `conversation.get_field("memory", {}).get("running_summary", "")` if available; included as `<conversation_summary>` block

2. **Recent History** — last **3 turns** (each turn = one user message + one assistant message):
   - Assistant messages capped at 8,000 chars
   - User messages capped at 6,000 chars
   - Formatted as `User: ...\nAssistant: ...` pairs

3. **PKB Context** — raw personal knowledge base claims retrieved via `conversation._get_pkb_context(user_email, query=message_text, conversation_summary, k=8, ...)`:
   - Returns raw XML-tagged claims (e.g. `<claim id="...">...</claim>`)
   - **No LLM summarization step** — the raw claims are used directly
   - Capped at 6,000 chars
   - Omitted entirely if empty

4. **Message Text** — the user's current message (with `/clarify` tokens stripped)

---

### Force Clarification Flag

`forceClarify` / `force_clarify` is propagated end-to-end:

| Layer | Field | Value when `/clarify` is used |
|-------|-------|-------------------------------|
| Frontend send | `opts.forceClarify` | `true` |
| `_fetchClarifications()` POST body | `forceClarify` | `true` |
| Backend `clarify_intent` | `force_clarify` | `bool(payload.get("forceClarify", False))` |
| Backend prompt rules | conditional section | MUST produce questions, never skip |

**Prompt behavior differences**:

- `force_clarify=False` (normal / auto-clarify checkbox): If the question is specific enough, set `needs_clarification=false` and the modal auto-closes without sending.
- `force_clarify=True` (slash command): MUST produce 1–3 questions. Do NOT set `needs_clarification=false`. Ask about tone, format, audience, or scope even if the question seems specific. The backend rule: "Use facts from PKB to avoid asking things already known about the user."

---

### LLM Model Override for Clarify Intent

The clarification endpoint respects the per-conversation `clarify_intent_model` override.

**Default**: `VERY_CHEAP_LLM[0]`

**Override lookup**:
```python
model = conversation.get_model_override("clarify_intent_model", VERY_CHEAP_LLM[0])
```

**`allowed_keys`** in `endpoints/conversations.py`: includes `"clarify_intent_model"`.

**UI**: `interface/interface.html` — "Clarify Models" section inside `#model-overrides-modal`:
- Dropdown: `#settings-clarify-intent-model`

**Persistence** (`interface/chat.js`):
- `saveConversationModelOverrides()` — saves `clarify_intent_model` key from the dropdown
- `loadConversationModelOverrides()` — calls `setModelOverrideValue('#settings-clarify-intent-model', ...)` on conversation load

See `documentation/features/conversation_model_overrides/README.md` for the full override system.

---

### Auto Clarify Checkbox (Settings)

In addition to the slash command, users can enable **Auto Clarify** in chat settings (`settings-auto_clarify` checkbox). When enabled, `sendMessageCallback()` checks this flag and calls `ClarificationsManager.requestAndShowClarifications()` with `forceClarify: false`. In this mode, if the backend returns `needs_clarification=false`, the modal shows "Your question is clear!" and optionally auto-sends.

The key difference from the slash command:
- Slash command → `forceClarify: true` → always gets questions, never auto-sends
- Auto-clarify checkbox → `forceClarify: false` → skips modal if question is already clear, can auto-send

---

### Key Files

| File | Role |
|------|------|
| `interface/parseMessageForCheckBoxes.js` | `processClarifyCommand()` — detects `/clarify` tokens outside backticks, sets `result.clarify_request = true` |
| `interface/common-chat.js` | `sendMessageCallback()` — intercepts send, strips tokens, calls ClarificationsManager |
| `interface/clarifications-manager.js` | Full clarification flow: modal, API call, multi-round append, Q rendering |
| `endpoints/conversations.py` | `POST /clarify_intent/<conversation_id>` — LLM-backed question generation |
| `interface/interface.html` | Clarifications modal HTML + `#settings-clarify-intent-model` dropdown in model overrides |
| `interface/chat.js` | `saveConversationModelOverrides()` / `loadConversationModelOverrides()` — `clarify_intent_model` persistence |

### API Reference

**`POST /clarify_intent/<conversation_id>`**
- Auth: `@login_required`
- Rate limit: 30/minute
- Request: `{ messageText: string, checkboxes: object, forceClarify: bool }`
- Response: `{ needs_clarification: bool, questions: [ { id, prompt, options: [ { id, label } ] } ] }`
- Fail-open: always returns valid JSON; failures return `{ needs_clarification: false, questions: [] }`

---

---

## Feature 2: Automatic Doubt Generation ("Auto Takeaways") — PLANNED, NOT YET IMPLEMENTED

> The design notes below describe the intended behavior. This feature has not been built yet.

### Goals
- After `/send_message` streaming completes (server-side background task)
- Automatically generate "Auto takeaways" — short, crisp summary
- **No preamble**, key takeaways (3-6 bullets), actionables (0-5), important facts
- Target: 120-250 words
- Save as root doubt with `doubt_text = "Auto takeaways"` (for dedup)
- **No schema change initially** — use doubt_text for identification
- **Persist silently** — do NOT auto-open doubts modal
- Skip if persist_or_not is disabled

### Planned Implementation Points

**Backend** (`endpoints/conversations.py`):
- After streaming completes in `generate_response()`, if `persist_or_not` is enabled, call `_generate_auto_takeaways_for_message()` via `get_async_future()` (non-blocking)
- `_generate_auto_takeaways_for_message()` — retrieves last assistant message, deduplicates, calls LLM, saves via `database.doubts.add_doubt()`
- `_generate_takeaways_text()` — LLM call using `VERY_CHEAP_LLM[0]` with no-preamble prompt, `stream=False`, `max_tokens=500`
- Dedup key: `doubt_text == "Auto takeaways"` on the same `message_id`
- All failures are logged and swallowed — never affect user's streaming experience

**Storage** (no schema change):
- Use existing `DoubtsClearing` table
- `doubt_text = "Auto takeaways"` as stable marker
- `is_root_doubt = True`, `parent_doubt_id = None`

**UI** (optional enhancement):
- In `interface/doubt-manager.js` `renderDoubtsOverview()`, detect `doubt.doubt_text === "Auto takeaways"` and style with "Auto" badge or different icon

### Planned Prompt Structure

```
Create a concise summary of the following answer for quick reference.

Original Answer:
{answer_text[:4000]}

Create a summary with:
1. **Key Takeaways**: 3-6 bullet points
2. **Actionables**: 0-5 specific actions (only if applicable)
3. **Important Facts**: critical details to remember

Requirements:
- NO preamble or introduction
- Start directly with content
- Use bullet points
- Be crisp and direct
- Target 120-250 words
- Use markdown formatting
```
