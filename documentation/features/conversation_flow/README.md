# Conversation Message Flow

This doc explains how chat messages move from UI to server and back, and how the UI renders streaming responses. This is the core path most edits will touch.

## End-to-End Flow (UI -> Server -> UI)

1) **UI submit**
- Entry: `interface/chat.js` binds `#sendMessageButton` to `sendMessageCallback()` in `interface/common-chat.js`.
- `sendMessageCallback()` collects settings and payload, clears the input, and calls:
  - `ChatManager.sendMessage(conversationId, messageText, options, links, search, attached_claim_ids, referenced_claim_ids, referenced_friendly_ids)`
- Before sending, `parseMemoryReferences()` extracts `@references` from the message text. These can reference any PKB object type — claims, contexts, entities, tags, or domains.

**Slash commands (pre-send intercepts)** — `parseMessageForCheckBoxes()` in `interface/parseMessageForCheckBoxes.js` scans the raw message for slash command tokens (outside backtick spans) and sets flags on the `options` object. `sendMessageCallback()` checks these flags before calling `ChatManager.sendMessage`:

| Command | Aliases | Behavior |
|---------|---------|----------|
| `/clarify` | `/clarification`, `/clarifications` | Strips the token, sets `options.clarify_request = true`; `sendMessageCallback` fires `ClarificationsManager.requestAndShowClarifications()` with `forceClarify: true` and does NOT send the message. The clarification Q&A is appended to the textarea for the user to review and send manually. |

See `documentation/product/behavior/CLARIFICATIONS_AND_AUTO_DOUBT_CONTEXT.md` for full clarification flow details.

**PKB `@` autocomplete** (pre-submit UX):
- Typing `@` in the chat input triggers `fetchAutocompleteResults()` in `interface/common-chat.js`.
- The autocomplete dropdown calls `GET /pkb/autocomplete?prefix=...` and shows results in five categories:
  - **Memories** (claims): icon `bi-journal-text`
  - **Contexts**: icon `bi-folder`, friendly_ids ending in `_context`
  - **Entities**: icon `bi-person`, friendly_ids ending in `_entity`
  - **Tags**: icon `bi-tag`, friendly_ids ending in `_tag`
  - **Domains**: icon `bi-grid`, friendly_ids ending in `_domain`
- Selecting a result inserts the full friendly_id (with suffix) into the message text.
- The suffix determines the resolution type at the backend; see step 3 for details.

2) **Immediate user render**
- `ChatManager.sendMessage()` immediately renders the user card before the server responds:
  - `ChatManager.renderMessages(conversationId, [userMessage], false, ...)`
- If the user has selected history-message checkboxes, those IDs are added to the payload and the UI clears the checkboxes locally before sending.

3) **Streaming request**
- `ChatManager.sendMessage()` sends `POST /send_message/<conversation_id>` with JSON body:
  - `messageText`, `checkboxes` (settings), `links`, `search`
  - optional `attached_claim_ids`, `referenced_claim_ids`, `referenced_friendly_ids`
- `referenced_friendly_ids` can include any PKB object type: claims (no suffix), contexts (`_context`), entities (`_entity`), tags (`_tag`), and domains (`_domain`). The suffix determines which resolver is invoked.
- The response is streamed (`text/plain`) as newline-delimited JSON chunks.
- Server also injects `conversation_pinned_claim_ids` into the request context (for PKB memory pinning).
- In `Conversation.reply()`, all PKB claims are fetched via `_get_pkb_context()` and included in the distillation prompt. Each `@friendly_id` is resolved by `resolve_reference()` in `structured_api.py`, which uses suffix-based routing to dispatch to the correct resolver:
  - `_entity` suffix → entity CRUD `resolve_claims()` — all claims linked to entity via `claim_entities` join
  - `_tag` suffix → tag CRUD `resolve_claims()` — recursive CTE collects claims from tag + all descendant tags
  - `_domain` suffix → domain filter — claims matching `context_domain` or `context_domains`
  - `_context` suffix → context CRUD `resolve_claims()` — recursive CTE collects claims from context + sub-contexts
  - No suffix → backwards-compatible path (claim_number → claim friendly_id → legacy context → context name fallback)
- After distillation, only `[REFERENCED ...]` claims are re-injected verbatim into the final prompt via `_extract_referenced_claims()` to ensure explicitly referenced claims are never lost.
- **Cross-conversation message references** (`@conversation_<fid>_message_<hash>`) are also detected here. Before PKB resolution, `_get_pkb_context()` separates conversation refs from PKB friendly IDs using `CONV_REF_PATTERN`, resolves them via `_resolve_conversation_message_refs()`, and injects the referenced message text as `[REFERENCED @conversation_...]` blocks. These survive post-distillation re-injection alongside PKB claims.
- For complete details on how PKB references are parsed, resolved, and injected, see [PKB Reference Resolution Flow](../truth_management_system/pkb_reference_resolution_flow.md).
- For cross-conversation message references, see [Cross-Conversation Message References](../cross_conversation_references/README.md).

4) **Streaming render**
- `sendMessageCallback()` calls `renderStreamingResponse(response, ...)` in `interface/common-chat.js`.
- This reads `ReadableStream` chunks, parses per-line JSON, and incrementally renders markdown via `renderInnerContentAsMarkdown()`.
- The UI creates a placeholder assistant card on the first chunk and updates it in-place as chunks arrive.
- Streaming updates the status bar in the card header to show server progress (e.g. “Preparing prompt ...”, “Calling LLM ...”).
- On cancellation, the UI swaps status text to “Response cancelled by user” and re-enables the send button.

5) **Persistence + follow-ups**
- Server persists messages + summary after completion (in `Conversation.persist_current_turn`).
- UI updates next-question suggestions after stream completion.

## Chat Settings Management

Settings are managed via the **chat-settings-modal** in `interface/interface.html` and persisted across sessions via `localStorage`.

### Architecture

| Layer | File | Role |
|-------|------|------|
| HTML | `interface/interface.html` | Checkbox/select elements in the `#chat-settings-modal` |
| Persistence | `interface/chat.js` | `buildSettingsStateFromControlsOrDefaults()`, `collectSettingsFromModal()`, `setModalFromState()`, `persistSettingsStateFromModal()`, `getPersistedSettingsState()`, `resetSettingsToDefaults()` |
| Runtime read | `interface/common.js` | `getOptions(parentElementId, type)` reads DOM state into the `checkboxes` object sent with each message |
| Backend | `Conversation.py` | `reply()` reads `query["checkboxes"]` and uses flags to gate features |

### Settings Lifecycle

1. **On page load**: `loadSettingsIntoModal()` (chat.js) calls `getPersistedSettingsState()` which reads from `localStorage` keyed by tab name (`${tab}chatSettingsState`). Falls back to `buildSettingsStateFromControlsOrDefaults()` on first run.
2. **On modal close**: `persistSettingsStateFromModal()` collects values via `collectSettingsFromModal()`, saves to `window.chatSettingsState` and `localStorage`.
3. **On send message**: `getOptions('chat-options', 'assistant')` (common.js) reads current checkbox/select state and returns the `checkboxes` object. This is merged with slash-command overrides from `parseMessageForCheckBoxes()` and sent in the POST body.
4. **On reset**: `resetSettingsToDefaults()` resets all controls to hardcoded defaults.

### Key Settings (Basic Options checkboxes)

| Setting | DOM ID | Default | Backend key | What it controls |
|---------|--------|---------|-------------|-----------------|
| Search | `settings-perform-web-search-checkbox` | off | `perform_web_search` | Web search augmentation |
| Search Exact | `settings-search-exact` | off | `search_exact` | Exact match search mode |
| Auto Clarify | `settings-auto_clarify` | off | `auto_clarify` | Auto-ask clarifying questions |
| Persist | `settings-persist_or_not` | **on** | `persist_or_not` | Save messages to conversation history |
| PPT Answer | `settings-ppt-answer` | off | `ppt_answer` | Slide/presentation mode |
| Use Memory Pad | `settings-use_memory_pad` | off | `use_memory_pad` | Include memory pad in prompt |
| Use PKB Memory | `settings-use_pkb` | **on** | `use_pkb` | PKB claim retrieval + user info distillation |
| LLM Right-Click Menu | `settings-enable_custom_context_menu` | on (desktop) | `enable_custom_context_menu` | Context menu on selected text |
| Planner | `settings-enable_planner` | off | `enable_planner` | Multi-step planner agent (hidden) |

## Server-Side Streaming

### Endpoint
- `POST /send_message/<conversation_id>` in `endpoints/conversations.py`
- Uses a background task and a queue to stream output:
  - `Conversation.__call__()` yields JSON lines from `Conversation.reply()`.

### Conversation Streaming
- `Conversation.__call__()` (`Conversation.py`) yields `json.dumps(chunk) + "\n"`.
- `Conversation.reply()` yields dicts like:
  - `{ "text": "...", "status": "...", "message_ids": { "user_message_id": "...", "response_message_id": "..." } }`
- `message_ids` appear during streaming; the UI uses them to update card metadata and message actions. The `message_ids` dict also includes `user_message_short_hash` and `response_message_short_hash` (6-char base36 hashes) when the conversation has a `conversation_friendly_id`. These are used by the UI to update message reference badges.
- Stream chunks may also include status-only updates (`text: ""`) to drive UX progress indicators.

### Math Formatting Pipeline (Backend)
- LLM streaming responses pass through `stream_text_with_math_formatting()` (`math_formatting.py`) before reaching `Conversation.reply()`. This function accepts plain text strings from `code_common/call_llm.py`'s streaming output, and `call_llm.py` (the UI shim) wraps `code_common`'s text chunks before yielding them up the stack.
- This generator buffers tokens to avoid splitting math delimiters (`\[`, `\]`, `\(`, `\)`) across chunk boundaries.
- `process_math_formatting()` doubles backslashes (`\[` → `\\[`) so that after markdown processing, MathJax sees the correct `\[` in the DOM.
- `ensure_display_math_newlines()` inserts `\n` around display math delimiters (`\\[`, `\\]`) to help the frontend breakpoint detector split sections at math boundaries.
- See [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md) and `dev/call_llm_impl.md` for implementation details.

### Persistence
- `Conversation.persist_current_turn()` writes:
  - messages (`messages` field) -- each message dict now includes `message_short_hash` (6-char base36) when the conversation has a `conversation_friendly_id`
  - running summary (`memory.running_summary`)
  - title (`memory.title`)
  - conversation_friendly_id (`memory.conversation_friendly_id`) -- generated on first persist, stored in both memory and `UserToConversationId` DB table
- `Conversation.get_message_ids()` hashes `(conversation_id + user_id + messageText)` to create stable IDs. It also returns `user_message_short_hash` and `response_message_short_hash` when the conversation has a friendly ID.
- Conversation-level model overrides (stored in `conversation_settings`) can switch the models used for summaries, TLDR, artefact edits, and context menu actions.
- Doc Index overrides (`doc_long_summary_model`, `doc_long_summary_v2_model`, `doc_short_answer_model`) apply when reading uploaded documents and generating document summaries/answers.
- See `documentation/features/conversation_model_overrides/README.md` for the override system details.

## Sidebar Conversation Selection (pre-chat)

Before any chat message can be sent, a conversation must be selected in the sidebar. The sidebar is rendered by `WorkspaceManager` (`interface/workspace-manager.js`) using **jsTree** (jQuery tree plugin).

### How conversations appear in the sidebar

1. `WorkspaceManager.loadConversationsWithWorkspaces(autoselect)` fires two parallel AJAX requests:
   - `GET /list_workspaces/{domain}` — workspace metadata (including `parent_workspace_id` for hierarchical nesting)
   - `GET /list_conversation_by_user/{domain}` — conversation metadata (title, last_updated, flag, workspace_id)
2. Conversations are grouped by `workspace_id` and sorted by `last_updated` descending.
3. `renderTree(convByWs)` builds a flat node array (workspace nodes as folders, conversation nodes as files) and initializes jsTree with `default-dark` theme, `types`, `wholerow`, and `contextmenu` plugins.
4. Workspace nodes use `parent: "ws_" + parent_workspace_id` (or `"#"` for root) so jsTree builds the hierarchy.

### How a conversation gets selected

- **Click in sidebar**: jsTree `select_node.jstree` event fires. If the selected node ID starts with `cv_`, extracts the conversation ID and calls `ConversationManager.setActiveConversation(conversationId)`.
- **Deep link** (`/interface/<conversation_id>`): `getConversationIdFromUrl()` extracts the ID. `loadConversationsWithWorkspaces(true)` calls `ConversationManager.setActiveConversation(id)` and `highlightActiveConversation(id)`.
- **Resume from localStorage**: On page load without a deep link, the UI reads `lastActiveConversationId:{email}:{domain}` from localStorage and resumes that conversation.
- **Auto-select first**: Falls back to the first conversation in the sorted list.
- **After CRUD** (create, move, delete): `loadConversationsWithWorkspaces(false)` refreshes the tree without auto-selecting, then re-highlights the current active conversation.
- **New Temporary Chat** (`#new-temp-chat` button in an always-visible column in the top-right chat bar, accessible on both mobile and desktop): `createTemporaryConversation()` sends a single `POST /create_temporary_conversation/{domain}` request. The server atomically cleans up old stateless conversations, creates a new conversation in the default workspace, marks it stateless, and returns the full conversation + workspace lists. The UI renders the tree from the response via `_processAndRenderData()`, then sets the new conversation active and highlights it. No separate `statelessConversation()` call is needed.

### Highlight timing

jsTree initializes asynchronously. `highlightActiveConversation(conversationId)` may be called before the tree DOM exists. If `_jsTreeReady` is false, the conversation ID is queued in `_pendingHighlight` and processed when the `ready.jstree` event fires. Highlighting opens all parent workspace nodes (from root down) and calls `tree.select_node()`.

### Mobile sidebar behavior

A capture-phase event interceptor (`installMobileConversationInterceptor`) listens for `touchend`/`pointerup`/`click` on `document`. On mobile widths (<=768px), tapping a conversation node hides the sidebar (`#chat-assistant-sidebar` gets `d-none`) and expands the chat area before calling `ConversationManager.setActiveConversation()`. The interceptor checks `WorkspaceManager._contextMenuOpenedAt` — if the context menu was opened within the last 800ms (set when a long-press or right-click triggers the context menu), the handler skips navigation. This prevents a long-press from both showing the menu and switching conversations. A timestamp is used instead of a boolean because the same handler fires for three events in sequence (`touchend` → `pointerup` → `click`); a boolean would be consumed by the first and the second would navigate. The jsTree `select_node.jstree` handler has the same 800ms guard.

### Context menus (conversation management from sidebar)

Right-clicking or clicking the triple-dot (kebab) button on a conversation node opens a context menu with actions: Copy Conversation Reference, Open in New Window, Clone, Toggle Stateless, Set Flag, Move to..., Delete. "Copy Conversation Reference" copies the `conversation_friendly_id` (e.g. `react_optimization_b4f2`) to clipboard for use in cross-conversation message references. The "Move to..." submenu lists all workspaces with full breadcrumb paths (e.g. `General > Private > Target`) so the user can see exactly where each workspace sits in the hierarchy.

Right-clicking or clicking the triple-dot on a workspace node offers: New Conversation, New Sub-Workspace, Rename, Change Color, Move to..., Delete. The workspace "Move to..." submenu also uses breadcrumb paths and disables invalid targets (descendants, current parent) to prevent cycles.

The context menu (`vakata-context`) uses `z-index: 99999` to render above all page elements including next-question-suggestions and Bootstrap modals.

### Key files for sidebar flow

- `interface/workspace-manager.js` — `WorkspaceManager` object (tree rendering, selection, CRUD, context menus, breadcrumb path builder)
- `interface/workspace-styles.css` — jsTree styling overrides, vakata context menu styling
- `interface/interface.html` — sidebar toolbar HTML and jsTree container `#workspaces-container`
- Full sidebar documentation: `documentation/features/workspaces/README.md`

## UI Rendering Pipeline

### Conversation load (history + snapshot restore)
Location: `interface/common-chat.js` (ConversationManager.activateConversation)

- On conversation selection (triggered by sidebar click, deep link, or auto-select — see above), the UI first tries to restore a DOM snapshot via `RenderedStateManager.restore(conversationId)` for fast paint.
- In parallel, it fetches the canonical message list via `ChatManager.listMessages(conversationId)`.
- If the snapshot matches the latest message list, it keeps the snapshot; otherwise it re-renders from the API list.
- Post-load work includes:
  - fetching conversation settings (for model overrides)
  - rendering documents
  - wiring document upload/download/share buttons
  - focusing the input and updating the URL

### `ChatManager.renderMessages()` (history + non-streaming)
Location: `interface/common-chat.js`

- Builds a `.message-card` for each message.
- Uses `renderInnerContentAsMarkdown()` to convert markdown to HTML.
- Adds action dropdown (doubts, move, artefacts, delete) and vote UI.
  - The artefacts entry (`.open-artefacts-button`) is an important ingress to the artefacts modal.
- The right-side triple-dot menu comes from `initialiseVoteBank()` (in `interface/common.js`).
  - This menu can expose edit actions for user/assistant messages (and other vote-related actions).
  - It also includes "Edit as Artefact" for assistant answers, creating an artefact that syncs back on save.
  - "Save to Memory" opens the PKB "Add Memory" modal (`#pkb-claim-edit-modal`) with the message text pre-filled into the statement field. Calls `PKBManager.openAddClaimModalWithText(text)`. Strips `<answer>` tags before inserting. Defaults type to `fact` and domain to `personal`.
- Applies `showMore()` for long responses and adds scroll-to-top button for long assistant messages.
- Updates URL with message focus for deep-linking.
- Message IDs drive all follow-on actions; `message-index` is computed from the number of message cards in `#chatView` (not global `.card` count).
- When a message contains slide markup, the renderer schedules a slide resize pass after the markdown is rendered.

### `renderStreamingResponse()` (streaming)
Location: `interface/common-chat.js`

- Creates a placeholder assistant card by calling `ChatManager.renderMessages(...)` with a server message stub.
- Accumulates streamed text in `rendered_answer` and periodically re-renders via `renderInnerContentAsMarkdown()`.
- Splits content at safe breakpoints (headers, paragraphs, rules, display math closings) using `getTextAfterLastBreakpoint()` to reduce reflow.
- Handles `<answer>` blocks and slide content buffering (`<slide-presentation>` tags) to avoid partial rendering.
- When `message_ids` arrive, updates DOM attributes so action buttons map to correct IDs. Also updates `.message-ref-badge` elements with `message_short_hash` values for both user and assistant cards.
- On completion:
  - final render pass
  - `initialiseVoteBank(...)`
  - `renderNextQuestionSuggestions(conversationId)`
  - optional scroll-to-hash for deep links
- Mermaid blocks are normalized and rendered after the stream completes.

**Math-aware rendering gate** (Feb 2026):
- Before each render, `isInsideDisplayMath(rendered_answer)` checks for unclosed `$$` or `\\[` blocks. If inside one, rendering is **deferred** until the math block closes. This prevents MathJax from attempting to typeset incomplete expressions.
- The re-render threshold is **dynamic**: 200 chars when the section contains display math (fewer MathJax re-runs), 80 chars for text-only sections.
- `getTextAfterLastBreakpoint()` now tracks `\\[...\\]` display math blocks as protected environments and places breakpoints after completed display math (types: `"after-display-math-bracket"`, `"after-display-math-dollar"`).
- See [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md) for full details.

## Multi-Model Responses (Main Model multi-select)

When the user selects **multiple models** in `settings-main-model-selector`, the request carries `checkboxes.main_model` as a list. The server uses this to decide between a single-model call and a multi-model ensemble.

### Decision logic
- `Conversation.reply()` normalizes `checkboxes.main_model` into canonical model names.
- If it is a list with more than one unique model and no agent is selected, `ensemble` is enabled.
- If a specialized agent is selected (e.g. `NResponseAgent`), the agent is responsible for multi-model behavior.

### How ensemble streaming works
- The ensemble path instantiates `NResponseAgent` with the list of model names.
- `NResponseAgent` uses `CallMultipleLLM`, which in turn streams via `stream_multiple_models`.
- Models are executed in parallel but streamed **one model at a time** (order of first response).

### Formatting of multi-model output
- Each model’s response is wrapped in a `<details>` section with a header like “Response from <model>”.
- Output is still standard markdown/HTML; the UI does not add model labels itself.
- A `---` separator is appended after the multi-model output.

### UI tab rendering (multi-model + TLDR)
- The UI converts model responses (and TLDR, when present) into tabs inside the assistant message card.
- Tabs are built client-side in `renderInnerContentAsMarkdown()` after markdown render, so history reloads use the same layout.
- When only one model response exists and TLDR is present, tabs render as “Main” and “TLDR”.
- When multiple model responses exist, each model becomes its own tab label (derived from the “Response from …” summary), plus a “TLDR” tab if present.
- Tabs appear during streaming as soon as each model response `<details>` block arrives; additional tabs are added as more model output streams in.
- If there is only a single response and no TLDR, the UI keeps the normal (non-tabbed) layout.

Implementation note (Feb 2026):
- Tab construction/hiding is scoped to `.chat-card-body` (the message body), not just the markdown render element. This ensures single-model+TLDR hides duplicate render containers the same way multi-model hides its `<details>` sources.
- `showMore()` rebuilds DOM for long messages; it re-invokes `applyModelResponseTabs()` so tabs remain correct after expand/collapse.

Key refs:
- `Conversation.py` (model selection + ensemble trigger)
- `agents/search_and_information_agents.py` (`NResponseAgent`)
- `call_llm.py` (`CallMultipleLLM`)
- `common.py` (`stream_multiple_models`)

## TLDR Summary (auto-added after long answers)

`Conversation.reply()` can append a TLDR block to the end of the answer when the response is very long. This is a server-side augmentation that shows up as a collapsible “TLDR Summary” section in the UI.

### When it triggers
- The answer exceeds 1000 words (after stripping `<answer>` tags).
- The request is not cancelled.
- The model is not the `FILLER_MODEL`.
- No specialized agent is active (`agent is None`).

### How it is generated
- The TLDR prompt includes the user query, the running summary (if available), and the full answer content.
- The model is selected via conversation overrides if present:
  - `conversation_settings.model_overrides.tldr_model`, else `CHEAP_LONG_CONTEXT_LLM[0]`.
- The TLDR LLM runs non-streaming (`stream=False`) to get the full text, then wraps it in a collapsible block.

### How it is appended and rendered
- The TLDR is appended after the main answer with a horizontal rule (`---`), then an `<answer_tldr>` wrapper.
- The content itself is wrapped with `collapsible_wrapper(...)`, header: “📝 TLDR Summary (Quick Read)”.
- The UI renders the `<details>` section like any other markdown block and preserves open/close state.
- If TLDR generation fails, the error is logged and the main answer still completes.

### `renderInnerContentAsMarkdown()`
Location: `interface/common.js`

Key responsibilities:
- Removes `<answer>` tags and renders markdown via `marked`.
- **Normalizes over-indented list items** via `normalizeOverIndentedLists()` before passing to `marked`. Some LLMs indent bullets with 4+ spaces, which CommonMark treats as code blocks instead of list items. This pre-processing subtracts 4 spaces from such lines while preserving relative nesting.
- Supports streaming mode with a sibling "-md-render" element to avoid DOM thrash.
- **Min-height locking** (streaming mode): Before replacing innerHTML, locks the element's current height as `min-height` to prevent layout collapse. Released after MathJax re-typesets.
- Wraps `---` sections in `<details>` blocks and persists hidden/visible state.
- Handles slide presentation markup, producing a blob URL and optional inline iframe.
- Updates ToC and triggers MathJax typesetting (with min-height release in `_queueMathJax()` callback).
- Protects incomplete code fences and inline code during streaming to avoid invalid HTML.
- Avoids breaking or reflowing inside `<details>` blocks, code fences, or math blocks.
- See [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md) for math-specific rendering details.

## Deep Links + URL State

- URL is updated to `/interface/<conversation_id>/<message_id>` on card focus.
- During streaming, once `message_ids` arrive, `renderStreamingResponse()` attaches focus handlers.
- Hash deep links (ToC anchors) are resolved after render with `scrollToHashTargetInCard()`.

## Other Rendering Cases

### Shared conversation view
Location: `interface/shared.js`

- Shared links fetch a bundled payload with `messages` and `documents` and render them using the same `ChatManager.renderMessages()` path.
- The shared view disables voting initialization (history-only rendering), but still supports markdown, slides, and ToC.

### Document view alongside chat
- Document list and viewer are rendered via `ChatManager.renderDocuments()` and `showPDF()`.
- The chat UI does not reflow the message list when documents are loaded; PDF view toggles independently.

### Cancellation and error states
- The streaming controller is stored in `currentStreamingController` and can be cancelled via the stop button.
- On network errors or aborts, the UI resets the send/stop buttons and displays a status error in the card.

## Key Files

- `interface/workspace-manager.js` (WorkspaceManager — sidebar tree rendering, conversation selection, workspace CRUD, context menus; see `documentation/features/workspaces/README.md`)
- `interface/chat.js` (UI wiring, settings, send button)
- `interface/common-chat.js` (ChatManager, ConversationManager, renderMessages, renderStreamingResponse, getTextAfterLastBreakpoint, isInsideDisplayMath, fetchAutocompleteResults — `@` autocomplete for all PKB types)
- `interface/common.js` (renderInnerContentAsMarkdown, normalizeOverIndentedLists)
- `interface/parseMessageForCheckBoxes.js` (parseMemoryReferences — extracts `@references` from message text)
- `endpoints/conversations.py` (`/send_message` streaming endpoint)
- `endpoints/pkb.py` (`/pkb/autocomplete` — returns memories, contexts, entities, tags, domains)
- `Conversation.py` (reply, streaming yield, persistence, `_get_pkb_context`, `_extract_referenced_claims`, `_resolve_conversation_message_refs`, `_ensure_conversation_friendly_id`)
- `conversation_reference_utils.py` (cross-conversation reference ID generation: `generate_conversation_friendly_id`, `generate_message_short_hash`, `CONV_REF_PATTERN`)
- `truth_management_system/interface/structured_api.py` (`resolve_reference` — suffix-based routing, `autocomplete` — all 5 categories)
- `truth_management_system/crud/entities.py` (`resolve_claims` — entity → linked claims)
- `truth_management_system/crud/tags.py` (`resolve_claims` — recursive tag → claims)
- `math_formatting.py` (stream_text_with_math_formatting, stream_with_math_formatting, process_math_formatting, ensure_display_math_newlines)
- `call_llm.py` (CallLLm, CallMultipleLLM, MockCallLLm — thin shim over `code_common/call_llm.py`; applies math formatting to responses)
- `code_common/call_llm.py` (call_llm, VISION_CAPABLE_MODELS — core LLM engine used by shim, TMS, and extension)