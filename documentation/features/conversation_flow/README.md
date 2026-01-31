# Conversation Message Flow

This doc explains how chat messages move from UI to server and back, and how the UI renders streaming responses. This is the core path most edits will touch.

## End-to-End Flow (UI -> Server -> UI)

1) **UI submit**
- Entry: `interface/chat.js` binds `#sendMessageButton` to `sendMessageCallback()` in `interface/common-chat.js`.
- `sendMessageCallback()` collects settings and payload, clears the input, and calls:
  - `ChatManager.sendMessage(conversationId, messageText, options, links, search, attached_claim_ids, referenced_claim_ids)`

2) **Immediate user render**
- `ChatManager.sendMessage()` immediately renders the user card before the server responds:
  - `ChatManager.renderMessages(conversationId, [userMessage], false, ...)`

3) **Streaming request**
- `ChatManager.sendMessage()` sends `POST /send_message/<conversation_id>` with JSON body:
  - `messageText`, `checkboxes` (settings), `links`, `search`
  - optional `attached_claim_ids`, `referenced_claim_ids`
- The response is streamed (`text/plain`) as newline-delimited JSON chunks.

4) **Streaming render**
- `sendMessageCallback()` calls `renderStreamingResponse(response, ...)` in `interface/common-chat.js`.
- This reads `ReadableStream` chunks, parses per-line JSON, and incrementally renders markdown via `renderInnerContentAsMarkdown()`.

5) **Persistence + follow-ups**
- Server persists messages + summary after completion (in `Conversation.persist_current_turn`).
- UI updates next-question suggestions after stream completion.

## Server-Side Streaming

### Endpoint
- `POST /send_message/<conversation_id>` in `endpoints/conversations.py`
- Uses a background task and a queue to stream output:
  - `Conversation.__call__()` yields JSON lines from `Conversation.reply()`.

### Conversation Streaming
- `Conversation.__call__()` (`Conversation.py`) yields `json.dumps(chunk) + "\n"`.
- `Conversation.reply()` yields dicts like:
  - `{ "text": "...", "status": "...", "message_ids": { "user_message_id": "...", "response_message_id": "..." } }`
- `message_ids` appear during streaming; the UI uses them to update card metadata and message actions.

### Persistence
- `Conversation.persist_current_turn()` writes:
  - messages (`messages` field)
  - running summary (`memory.running_summary`)
  - title (`memory.title`)
- `Conversation.get_message_ids()` hashes `(conversation_id + user_id + messageText)` to create stable IDs.
- Conversation-level model overrides (stored in `conversation_settings`) can switch the models used for summaries, TLDR, artefact edits, and context menu actions.
- Doc Index overrides (`doc_long_summary_model`, `doc_long_summary_v2_model`, `doc_short_answer_model`) apply when reading uploaded documents and generating document summaries/answers.
- See `documentation/features/conversation_model_overrides/README.md` for the override system details.

## UI Rendering Pipeline

### `ChatManager.renderMessages()` (history + non-streaming)
Location: `interface/common-chat.js`

- Builds a `.message-card` for each message.
- Uses `renderInnerContentAsMarkdown()` to convert markdown to HTML.
- Adds action dropdown (doubts, move, artefacts, delete) and vote UI.
  - The artefacts entry (`.open-artefacts-button`) is an important ingress to the artefacts modal.
- The right-side triple-dot menu comes from `initialiseVoteBank()` (in `interface/common.js`).
  - This menu can expose edit actions for user/assistant messages (and other vote-related actions).
  - It also includes "Edit as Artefact" for assistant answers, creating an artefact that syncs back on save.
- Applies `showMore()` for long responses and adds scroll-to-top button for long assistant messages.
- Updates URL with message focus for deep-linking.

### `renderStreamingResponse()` (streaming)
Location: `interface/common-chat.js`

- Creates a placeholder assistant card by calling `ChatManager.renderMessages(...)` with a server message stub.
- Accumulates streamed text in `rendered_answer` and periodically re-renders via `renderInnerContentAsMarkdown()`.
- Splits content at safe breakpoints (headers, paragraphs, rules) using `getTextAfterLastBreakpoint()` to reduce reflow.
- Handles `<answer>` blocks and slide content buffering (`<slide-presentation>` tags) to avoid partial rendering.
- When `message_ids` arrive, updates DOM attributes so action buttons map to correct IDs.
- On completion:
  - final render pass
  - `initialiseVoteBank(...)`
  - `renderNextQuestionSuggestions(conversationId)`
  - optional scroll-to-hash for deep links

### `renderInnerContentAsMarkdown()`
Location: `interface/common.js`

Key responsibilities:
- Removes `<answer>` tags and renders markdown via `marked`.
- Supports streaming mode with a sibling "-md-render" element to avoid DOM thrash.
- Wraps `---` sections in `<details>` blocks and persists hidden/visible state.
- Handles slide presentation markup, producing a blob URL and optional inline iframe.
- Updates ToC and triggers MathJax typesetting.

## Deep Links + URL State

- URL is updated to `/interface/<conversation_id>/<message_id>` on card focus.
- During streaming, once `message_ids` arrive, `renderStreamingResponse()` attaches focus handlers.
- Hash deep links (ToC anchors) are resolved after render with `scrollToHashTargetInCard()`.

## Key Files

- `interface/chat.js` (UI wiring, settings, send button)
- `interface/common-chat.js` (ChatManager, renderMessages, renderStreamingResponse)
- `interface/common.js` (renderInnerContentAsMarkdown)
- `endpoints/conversations.py` (`/send_message` streaming endpoint)
- `Conversation.py` (reply, streaming yield, persistence)
