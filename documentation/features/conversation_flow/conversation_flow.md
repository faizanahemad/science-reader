# Conversation Message Flow

This doc explains how chat messages move from UI to server and back, and how the UI renders streaming responses. This is the core path most edits will touch.

## End-to-End Flow (UI -> Server -> UI)

1) **UI submit**
- Entry: `interface/chat.js` binds `#sendMessageButton` to `sendMessageCallback()` in `interface/common-chat.js`.
- `sendMessageCallback()` collects settings and payload, clears the input, and calls:
  - `ChatManager.sendMessage(conversationId, messageText, options, links, search, attached_claim_ids, referenced_claim_ids, referenced_friendly_ids)`
- Before sending, `parseMemoryReferences()` extracts `@references` from the message text. These can reference any PKB object type — claims, contexts, entities, tags, or domains.

**Slash commands (pre-send intercepts)** — `parseMessageForCheckBoxes()` in `interface/parseMessageForCheckBoxes.js` scans the raw message for slash command tokens (outside backtick spans) and sets flags on the `options` object. `sendMessageCallback()` checks these flags before calling `ChatManager.sendMessage`:

| Command | Flag set | Behavior |
|---------|----------|----------|
| `/clarify` | `clarify_request: true` | Does NOT send. Fires `ClarificationsManager.requestAndShowClarifications()` with `forceClarify: true`; Q&A is appended to textarea for the user to review and send manually. |
| `/search` | `perform_web_search: true` | Enables web search augmentation for this message. |
| `/scholar` | `googleScholar: true` | Enables Google Scholar search. |
| `/draw` | `draw: true` | Instructs the LLM to produce Mermaid / draw.io diagrams. |
| `/execute` | `execute: true` | Instructs the LLM to emit and execute code server-side. |
| `/history N` | `enable_previous_messages: "N"` | Includes the last N messages in context. |
| `/detailed N` | `provide_detailed_answers: "N"` | Sets response detail level (1–4). |
| `/more` | `tell_me_more: true` | Requests a longer continuation. |
| `/ensemble` | `ensemble: true` | Forces multi-model ensemble response. |
| `/delete` | `delete_last_turn: true` | Deletes the last conversation turn. |
| `/image <prompt>` | `generate_image: true` | **Image generation and editing.** Strips `/image`, uses remaining text as prompt. Backend intercepts in `Conversation.reply()` and calls `_handle_image_generation()` instead of the normal LLM path. Before calling the image model, detects an input image via two priority rules: (1) image attached to the current message (`query["images"]`), (2) last preceding assistant message with `generated_images` metadata (loaded from disk). If an input image is found, passes it to the model as a multipart content array `[{image_url}, {text}]` for editing/transformation; otherwise pure generation. Gathers conversation context (summary + last 2 messages + deep context), refines the prompt via a cheap LLM, calls Nano Banana 2, stores the PNG in `{conv_storage}/images/`, and streams a markdown image card. Image is downloadable inline and included in LLM vision context on subsequent turns. See `documentation/features/image_generation/README.md`. |

| `/pkb <text>` | `pkb_nl_command: true` | **PKB Natural Language command.** Strips `/pkb` (or `/memory`), routes the remaining text to the `PKBNLConversationAgent` inside `Conversation.reply()`. The agent uses the PKB NL backend (`PKBNLAgent`) with tools for CRUD on claims/entities/tags/contexts. Bypasses the normal LLM path, PKB retrieval, and `checkMemoryUpdates`. Streams the agent's NL response directly. If the NL agent is uncertain, it may trigger the `pkb_propose_memory` interactive tool flow (see Tool Calling Pipeline below). Alias: `/memory`. See `documentation/features/truth_management_system/README.md`. |
| `/memory <text>` | `pkb_nl_command: true` | Alias for `/pkb <text>`. |
**Backend-only commands** (not parsed by frontend — intercepted in `Conversation.reply()` before the normal LLM path):

| Command | Behavior |
|---------|----------|
| `/title <text>` (alias: `/set_title`) | Sets conversation title manually. Bypasses LLM title generation. |
| `/temp <text>` (alias: `/temporary`) | Sends message as temporary — not persisted to conversation history. |
**Per-turn enable/disable toggles** (new): `/enable_X` and `/disable_X` commands override any Basic Options checkbox for the current turn only. 14 pairs covering `search`, `pkb`, `tools`, `opencode`, `planner`, `memory_pad`, `auto_clarify`, `persist`, `ppt_answer`, `context_menu`, `slides_inline`, `only_slides`, `render_close`, `search_exact`. Parsed via `processCommand()` in `parseMessageForCheckBoxes.js`.

**Model/Agent/Preamble selection** (new):

| Command Pattern | Flag set | Behavior |
|----------------|----------|----------|
| `/model_<short_name>` | `main_model: [canonical]` | Selects model for this turn. **Replaces** modal selection. Short name resolved to canonical via `_resolveSlashCatalogName()` using cached `GET /api/slash_commands` catalog. |
| `/agent_<short_name>` | `field: canonical` | Selects agent for this turn. **Replaces** modal selection. |
| `/preamble_<short_name>` | `preamble_options: [...]` | Adds preamble for this turn. **Additive** — appended to modal-selected preambles via `mergeOptions()`. |

**Slash command autocomplete** (pre-submit UX):
- Typing `/` in the chat input triggers the slash autocomplete dropdown (0-character minimum — shows all commands immediately).
- Commands are fetched from `GET /api/slash_commands` **once on page load** and cached in `window._slashCommandCatalog`. No network calls during typing.
- Fuzzy matching (ported from `file-browser-manager.js` `_fuzzyMatch`) supports sequential character matching with scoring: exact substring, word-boundary, and out-of-order character matching.
- Display: 5 items max visible with scroll, grouped by category with thin separator headers. Matched characters highlighted in bold blue.
- Selection: First item pre-selected. Arrow keys navigate, Enter/Tab to apply, Escape to dismiss.
- Model, agent, and preamble lists are generated dynamically from settings modal `<option>` elements, so the autocomplete stays current when modal options change.
- See `documentation/features/slash_command_system.md` for the full command catalog and implementation details.
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
- **Tool calling branch**: When `checkboxes.enable_tool_use` is true and `checkboxes.enabled_tools` has at least one enabled category, `reply()` calls `_get_enabled_tools()` to build the tools config and then `_run_tool_loop()` instead of the normal LLM path. `_run_tool_loop()` is a generator that yields the same dict format as the normal path, plus tool-specific event types (`tool_call`, `tool_status`, `tool_input_request`, `tool_result`). The loop runs up to 5 iterations; on the final iteration, `tool_choice="none"` forces text output. When the LLM returns multiple tool calls in a single response, they are classified as interactive or non-interactive: **non-interactive tools execute in parallel** via `ThreadPoolExecutor` (each thread receives a `deepcopy` of `ToolContext` to avoid shared mutable state), while **interactive tools** (`ask_clarification`, `pkb_propose_memory`) execute sequentially since they require `threading.Event` synchronization via `POST /tool_response/<conv_id>/<tool_id>` (60s timeout). The system prompt includes explicit guidance telling the LLM to issue multiple tool calls at once for independent information needs, since parallel execution means wall-clock time equals the slowest tool rather than the sum of all tools. Tool results are truncated to `TOOL_RESULT_TRUNCATION_LIMIT` characters (currently 50000, defined in `code_common/tools.py`) before being appended to the messages array as `{"role": "tool"}` messages for LLM continuation. Each tool call is timed (`tool_exec_duration` for handler execution, `tool_total_duration` including user-wait time); timing flows into `tool_result` events (`duration_seconds`), the collapsible `<tool_calls_summary>` block, and `time_dict['tool_calls']` (list of `{name, duration_s, result_chars}` dicts appended in `reply()`). See `documentation/features/tool_calling/README.md`.

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

### Settings Storage & Retrieval — Where to Look

All Basic Options settings share a single serialisation path. When adding or debugging a setting:

| Question | Where to look |
|---|---|
| **Where is the checkbox HTML?** | `interface/interface.html` — search for `settings-<key>` in `#chat-settings-modal > .basic-options` area |
| **What is the default value?** | `interface/chat.js` `buildSettingsStateFromControlsOrDefaults()` — each key's fallback is defined here |
| **How is the modal restored on open?** | `interface/chat.js` `setModalFromState(state)` — maps `state.<key>` to `$('#settings-<key>').prop('checked', ...)` or `.val(...)` |
| **How is the value collected on modal close?** | `interface/chat.js` `collectSettingsFromModal()` — reads DOM and returns plain object |
| **How is it persisted across sessions?** | `interface/chat.js` `persistSettingsStateFromModal()` → `localStorage.setItem('${tab}chatSettingsState', JSON.stringify(state))` |
| **How is it loaded on page load?** | `interface/chat.js` `getPersistedSettingsState()` → parses `localStorage.getItem('${tab}chatSettingsState')` |
| **What is the in-memory runtime object?** | `window.chatSettingsState` — updated on every modal close and on page load |
| **Settings that gate client-side behaviour only** | Check `interface/common-chat.js` (e.g. `auto_pkb_extract` gates `checkMemoryUpdates()`). These are NOT sent to the backend. |
| **Settings sent to the backend** | `interface/common.js` `getOptions('chat-options', 'assistant')` reads DOM checkboxes in `#chat-options` and returns the `checkboxes` POST body key |

**Key rule**: a setting that only controls frontend behaviour (like `auto_pkb_extract`) lives in `chatSettingsState` and is read from `window.chatSettingsState` in `common-chat.js`. A setting that controls backend behaviour (like `use_pkb`) must also flow through `getOptions()` so it appears in `checkboxes` in the POST body.

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
| Auto-save facts | `settings-auto_pkb_extract` | **on** | `auto_pkb_extract` | Automatic post-message fact detection via `PKBManager.checkMemoryUpdates()` → `POST /pkb/propose_updates`. When OFF the 3-second delayed check is suppressed entirely — no HTTP call is made and no memory-proposal modal appears. Does not affect `/pkb` slash commands or the `pkb_propose_memory` interactive tool. See `documentation/features/truth_management_system/README.md#auto-save-facts-auto_pkb_extract`. |
| LLM Right-Click Menu | `settings-enable_custom_context_menu` | on (desktop) | `enable_custom_context_menu` | Context menu on selected text |
| Planner | `settings-enable_planner` | off | `enable_planner` | Multi-step planner agent (hidden) |
| Default Temp Chat | `settings-default_temp_chat` | off | *(client-only)* | When ON, page load auto-creates a temporary chat (via `WorkspaceManager.createTemporaryConversation()`) instead of resuming the last conversation. Fires once per page load via `activateChatTab()` with a `window._defaultTempChatCreated` guard to prevent repeated creation on tab switches. |

| Enable Tool Use | `settings-enable_tool_use` | off | `enable_tool_use` | Master toggle for LLM tool calling (requires at least one category enabled). **Default-enabled tools**: When tool use is enabled, `DEFAULT_ENABLED_TOOLS` (`ask_clarification`, `pkb_nl_command`) are always force-enabled regardless of per-category selection (configured in `code_common/tools.py` and enforced in `interface/chat.js` `resetSettingsToDefaults()`). |
| Enabled Tools | `settings-enabled_tools` (per-category checkboxes) | all off | `enabled_tools` | Per-category tool toggles: clarification, search, documents, pkb, memory, code_runner, artefacts, prompts, conversation. PKB category includes `pkb_nl_command` (NL agent), `pkb_delete_claim`, and `pkb_propose_memory` (interactive modal). See `documentation/features/tool_calling/README.md` |
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
   - `GET /list_conversation_by_user/{domain}` — returns `{"conversations": [...], "deleted_temporary_ids": [...]}`. The `conversations` array contains conversation metadata (title, last_updated, flag, workspace_id). The `deleted_temporary_ids` array lists conversation IDs of stateless (temporary) conversations that were deleted during this request (only those older than the 5-minute grace period). The UI uses `deleted_temporary_ids` to proactively clear stale `lastActiveConversationId` entries from `localStorage`. Backward-compatible: the UI also handles a flat array response (old format) via `Array.isArray()` check.
2. Conversations are grouped by `workspace_id` and sorted by `last_updated` descending.
3. `renderTree(convByWs)` builds a flat node array (workspace nodes as folders, conversation nodes as files) and initializes jsTree with `default-dark` theme, `types`, `wholerow`, and `contextmenu` plugins.
4. Workspace nodes use `parent: "ws_" + parent_workspace_id` (or `"#"` for root) so jsTree builds the hierarchy.

### How a conversation gets selected

- **Click in sidebar**: jsTree `select_node.jstree` event fires. If the selected node ID starts with `cv_`, extracts the conversation ID and calls `ConversationManager.setActiveConversation(conversationId)`.
- **Click in Recent section**: The "Recent" section above the workspace tree shows the 5 most recently updated conversations (plain DOM, not jsTree). Clicking an item calls `ConversationManager.setActiveConversation(convId)` — same as the jsTree click handler. Does NOT call `highlightActiveConversation()` separately (that is called internally by `setActiveConversation()` → `highLightActiveConversation()` → `WorkspaceManager.highlightActiveConversation()`). On mobile (<=768px), closes the sidebar before switching. Context menu (right-click) constructs a fake jsTree-like node object (`{ id: 'cv_' + convId, li_attr: {...} }`) and passes it to `buildConversationContextMenu()` for full feature parity.
- **Deep link** (`/interface/<conversation_id>`): `getConversationIdFromUrl()` extracts the ID. The ID is now **validated against the fetched conversation list** before calling `setActiveConversation()`. If the conversation no longer exists (e.g. a bookmarked temporary conversation that was cleaned up), a warning toast is shown and the UI falls through to the resume-from-localStorage or first-available-conversation path.
- **Resume from localStorage**: On page load without a deep link, the UI reads `lastActiveConversationId:{email}:{domain}` from localStorage and resumes that conversation. If the stored ID was among `deleted_temporary_ids`, the localStorage entry is cleared before the resume check, ensuring the UI doesn't try to load a deleted conversation.
- **Auto-select first**: Falls back to the first conversation in the sorted list.
- **After CRUD** (create, move, delete): `loadConversationsWithWorkspaces(false)` refreshes the tree without auto-selecting, then re-highlights the current active conversation.
- **New Temporary Chat** (`#new-temp-chat` button in an always-visible column in the top-right chat bar, accessible on both mobile and desktop): `createTemporaryConversation()` sends a single `POST /create_temporary_conversation/{domain}` request. The server atomically cleans up old stateless conversations, creates a new conversation in the default workspace, marks it stateless, and returns the full conversation + workspace lists. The UI renders the tree from the response via `_processAndRenderData()`, then sets the new conversation active and highlights it. No separate `statelessConversation()` call is needed.

### Deleted temporary conversation handling (graceful fallback)

When a conversation is set active via any path above, `ConversationManager.setActiveConversation(conversationId)` performs an **existence guard** before setting any state or firing API calls:

1. Checks if `conversationId` exists in `WorkspaceManager.conversations` (the already-loaded list).
2. If not found: clears the stale `lastActiveConversationId` from `localStorage`, shows a warning toast ("This conversation is no longer available. It may have been a temporary conversation that was cleaned up."), and recursively calls `setActiveConversation()` with the first available conversation. Returns early — no API calls are fired.
3. If found: proceeds normally (sets `activeConversationId`, saves to `localStorage`, fires `listMessages`, `getConversationDetails`, `getConversationSettings`, `fetchMemoryPad`, `LocalDocsManager.refresh`, etc.).

Additionally, the `$.when(restorePromise, messagesRequest)` call has a `.fail()` handler that catches 404s if the conversation is deleted between the list-fetch and the message-fetch. This handler clears `localStorage` and falls back to the first available conversation.

Error handlers in `getConversationDetails()` and `fetchMemoryPad()` use `showToast('...', 'danger')` instead of `alert()` to avoid disruptive popups.

**Backend grace period**: `list_conversation_by_user` only deletes stateless conversations whose `memory.last_updated` is older than 5 minutes (`GRACE_PERIOD_SECONDS = 300`). This prevents a multi-tab race condition where Tab A's reload would delete a temp conversation that Tab B is still using. The `create_temporary_conversation` endpoint still deletes all previous stateless conversations immediately (since the user is explicitly replacing them).

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

#### DOM snapshot caching — what IS and IS NOT preserved

The snapshot (`RenderedStateManager`, `interface/rendered-state-manager.js`) stores the **serialised innerHTML** of `#chatView` in IndexedDB. This means:

- ✅ **Preserved**: rendered HTML of every message card (markdown → HTML, tabs, code blocks, MathJax output, slide iframes, section collapse state)
- ❌ **NOT preserved**: JavaScript event handlers attached to DOM nodes — these are lost when `chatView.innerHTML` is overwritten on restore.

Because event handlers are gone after a snapshot restore, any per-card JS initialisation that was performed during `renderMessages` must be **explicitly re-run** in the `keepSnapshot` branch (`activateConversation` ~line 729 of `common-chat.js`). Currently re-initialised after restore:

| Initialisation | Why needed after restore |
|---|---|
| `initialiseVoteBank($card, text, ...)` for each `.message-card` | Wires the right-side copy button click handler and populates the triple-dot dropdown menu with TTS / Edit / Save-to-Memory items. Without this, both buttons silently do nothing. |
| `attachSectionListeners($chatView[0])` | Re-attaches collapsible section toggle listeners. |
| `fetchConversationUIState(conversationId, ...)` | Restores persisted section hidden/visible state from server. |

**Developer rule**: if you add new JS-based initialisation inside `renderMessages` that attaches handlers to message cards (e.g. new button, new tooltip, new interactive widget), you **must** also call it in the `keepSnapshot` branch so snapshot-loaded conversations behave identically to freshly rendered ones.

#### Snapshot version invalidation

Snapshots are keyed by `RENDER_SNAPSHOT_VERSION` (defined in `interface/rendered-state-manager.js` via `window.UI_CACHE_VERSION`). Bump this version whenever the rendered HTML structure of message cards changes incompatibly (e.g. new card elements, changed class names, removed wrapper divs). Old snapshots whose version does not match are discarded and the conversation is re-rendered from the API. The service worker `CACHE_VERSION` in `interface/service-worker.js` should be bumped at the same time so clients pick up the new JS that reads the new snapshot format.
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
- **Tool call events**: When tool calling is active, `renderStreamingResponse()` detects tool event types (`tool_call`, `tool_status`, `tool_input_request`, `tool_result`) in JSON-line chunks by checking `typeof item === 'object' && item.type` in the stream handler. These events are dispatched to `ToolCallManager` methods (from `interface/tool-call-manager.js`), which shows inline status pills for server-side tools and a Bootstrap modal for interactive tools requiring user input.

**Math-aware rendering gate** (Feb 2026):
- Before each render, `isInsideDisplayMath(rendered_answer)` checks for unclosed `$$` or `\\[` blocks. If inside one, rendering is **deferred** until the math block closes. This prevents MathJax from attempting to typeset incomplete expressions.
- The re-render threshold is **dynamic**: 200 chars when the section contains display math (fewer MathJax re-runs), 80 chars for text-only sections.
- `getTextAfterLastBreakpoint()` now tracks `\\[...\\]` display math blocks as protected environments and places breakpoints after completed display math (types: `"after-display-math-bracket"`, `"after-display-math-dollar"`).
- See [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md) for full details.

## Multi-Model Responses (Main Model selector)

The `settings-main-model-selector` is a `<select multiple>` enhanced with bootstrap-select. It defaults to **single-select mode** — clicking a model replaces the previous selection (1-click model switching). A "Multi-select" toggle button at the top of the dropdown enables multi-select mode, allowing the user to pick multiple models for ensemble responses. The mode preference is persisted to `localStorage` (`modelSelectorMultiMode` key).

In single mode, the `changed.bs.select` event handler in `chat.js` intercepts selections and deselects all other options, keeping only the newly clicked model. In multi mode, bootstrap-select's native multi-select behavior applies.

When the user selects **multiple models**, the request carries `checkboxes.main_model` as a list. The server uses this to decide between a single-model call and a multi-model ensemble.

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
- For full document upload/attachment/promote/query flow details, see `documentation/features/documents/doc_flow_reference.md`.

### Cancellation and error states
- The streaming controller is stored in `currentStreamingController` and can be cancelled via the stop button.
- On network errors or aborts, the UI resets the send/stop buttons and displays a status error in the card.

## Key Files

- `interface/workspace-manager.js` (WorkspaceManager — sidebar tree rendering, conversation selection, workspace CRUD, context menus; see `documentation/features/workspaces/README.md`)
- `interface/chat.js` (UI wiring, settings, send button)
- `interface/common-chat.js` (ChatManager, ConversationManager, renderMessages, renderStreamingResponse, getTextAfterLastBreakpoint, isInsideDisplayMath, fetchAutocompleteResults — `@` autocomplete for all PKB types, slash autocomplete IIFE v2 — fuzzy match, cached catalog, dropdown rendering with category headers)
- `interface/common.js` (renderInnerContentAsMarkdown, normalizeOverIndentedLists)
- `interface/parseMessageForCheckBoxes.js` (parseMemoryReferences — extracts `@references`; slash command parsing — `processCommand()` for all commands, `_resolveSlashCatalogName()` for model/agent/preamble name resolution, `mergeOptions()` for slash-vs-modal merge)
- `endpoints/conversations.py` (`/send_message` streaming endpoint)
- `endpoints/conversations.py` (`POST /tool_response/<conversation_id>/<tool_id>` — submit user response for interactive tool calls)
- `endpoints/pkb.py` (`/pkb/autocomplete` — returns memories, contexts, entities, tags, domains)
- `Conversation.py` (reply, streaming yield, persistence, `_get_pkb_context`, `_extract_referenced_claims`, `_resolve_conversation_message_refs`, `_ensure_conversation_friendly_id`)
- `conversation_reference_utils.py` (cross-conversation reference ID generation: `generate_conversation_friendly_id`, `generate_message_short_hash`, `CONV_REF_PATTERN`)
- `truth_management_system/interface/structured_api.py` (`resolve_reference` — suffix-based routing, `autocomplete` — all 5 categories)
- `truth_management_system/crud/entities.py` (`resolve_claims` — entity → linked claims)
- `truth_management_system/crud/tags.py` (`resolve_claims` — recursive tag → claims)
- `math_formatting.py` (stream_text_with_math_formatting, stream_with_math_formatting, process_math_formatting, ensure_display_math_newlines)
- `call_llm.py` (CallLLm, CallMultipleLLM, MockCallLLm — thin shim over `code_common/call_llm.py`; applies math formatting to responses)
- `code_common/call_llm.py` (call_llm, VISION_CAPABLE_MODELS — core LLM engine used by shim, TMS, and extension)
- `endpoints/image_gen.py` (`generate_image_from_prompt`, `_refine_prompt_with_llm`, `DEFAULT_IMAGE_MODEL`, `/api/generate-image` modal endpoint, `/api/conversation-image/<conv_id>/<filename>` serve endpoint)
- `interface/image-gen-manager.js` (standalone image generation modal — Settings → Image button)
- `Conversation._handle_image_generation()` (`Conversation.py` — handles `/image` command: context gathering, prompt refinement, image gen, file storage, streaming, persistence)
- `code_common/tools.py` (tool registry + 56 tool handlers across 9 categories; `ToolRegistry`, `@register_tool` decorator, `DEFAULT_ENABLED_TOOLS` list)
- `interface/tool-call-manager.js` (ToolCallManager — tool call UI rendering: inline status pills, interactive modal, `threading.Event` response submission)
- `endpoints/slash_commands.py` (`GET /api/slash_commands` — full command catalog endpoint with 7 categories, dynamic model/agent/preamble lists)

**See also:** `documentation/features/image_generation/README.md`

---

## Tool Calling Pipeline (Agentic Loop)

When the "Enable Tools" master toggle is ON and tools are selected in the Bootstrap Select dropdown, the conversation pipeline branches into an agentic tool-calling loop.

### Settings Flow (UI → Backend)

1. **UI**: User opens chat settings modal → checks "Enable Tools" → selects individual tools from the Bootstrap Select dropdown (`#settings-tool-selector`, 56 tools across 9 `<optgroup>` categories).
2. **JS persistence**: `collectSettingsFromModal()` / `getStateFromModal()` reads selected tool names via `getSelectPickerValue('#settings-tool-selector', [])` → stored as `state.enabled_tools` (array of tool name strings).
3. **Request payload**: `getOptions()` in `common.js` includes `enable_tool_use: true` and `enabled_tools: ["ask_clarification", "web_search", ...]` in the `checkboxes` object sent with `POST /send_message/<conversation_id>`.
4. **Backend parsing**: `Conversation._get_enabled_tools(checkboxes)` reads the payload:
   - If `enabled_tools` is a **list** → uses tool names directly (new format)
   - If `enabled_tools` is a **dict** → maps category booleans to tool names (legacy format)
   - If `None` but master toggle ON → enables all tools
   - Returns OpenAI-format `tools` parameter via `TOOL_REGISTRY.get_openai_tools_param(enabled_names)`

### Tool-Enabled Reply Flow

```
User sends message
  → POST /send_message/<conversation_id>
    → Conversation.reply()
      → tools_config = _get_enabled_tools(checkboxes)
      → IF tools_config is not None:
          → _run_tool_loop(prompt, preamble, images, model, keys, tools_config, ...)
            → Iteration 1 (of max 5):
              → call_llm(..., tools=tools_config, tool_choice="auto")
                → call_chat_model(..., tools=tools_config, tool_choice="auto")
                  → client.chat.completions.create(model, messages, tools=tools_config, stream=True)
                  → _extract_text_from_openai_response(response)
                    → yields str chunks (streamed text)
                    → yields dict chunks (tool_call objects when finish_reason="tool_calls")
              
              → IF tool_call dicts received:
                  → Classify tool calls: interactive vs non-interactive
                  → Stream tool_call events for ALL tools
                  
                  → NON-INTERACTIVE tools (parallel execution):
                      → Stream tool_status "executing" for all non-interactive tools
                      → ThreadPoolExecutor(max_workers=min(N, 5))
                          → Each thread: deepcopy(ToolContext) → TOOL_REGISTRY.execute()
                      → Collect results, emit tool_result/tool_status in original order
                      → Append all {"role": "tool"} messages
                  
                  → INTERACTIVE tools (sequential execution):
                      → For each interactive tool:
                          → Stream tool_status "executing" event
                          → TOOL_REGISTRY.execute(name, args, context, tool_call_id)
                          → IF needs_user_input:
                              → Stream tool_input_request event with ui_schema
                              → Stream tool_status "waiting_for_user" event
                              → wait_for_tool_response(tool_id, timeout=60)
                          → Stream tool_status "completed" event
                          → Stream tool_result event with summary
                          → Append {"role": "tool"} message
                  → Continue to next iteration
              
              → IF text only received:
                  → Stream text to client
                  → Break loop (done)
            
            → Iteration 5 (final):
              → call_llm(..., tools=tools_config, tool_choice="none")  ← forces text-only response
              → Stream final text response
        
        → ELSE (tools_config is None):
          → Existing non-tool reply path (unchanged)
```

### UI Stream Handling for Tool Events

The stream handler in `common-chat.js` (`renderStreamingResponse()`) processes JSON-line chunks. When a chunk has a `type` field matching a tool event type, it dispatches to `ToolCallManager`:

| Event Type | Handler | UI Effect |
|---|---|---|
| `tool_call` | `ToolCallManager.handleToolCall()` | Shows inline status pill with tool name |
| `tool_status` | `ToolCallManager.showToolCallStatus()` | Updates pill (spinner → checkmark) |
| `tool_input_request` | `ToolCallManager.handleToolInputRequest()` | Renders Bootstrap modal with MCQ form |
| `tool_result` | `ToolCallManager.showToolResult()` | Shows brief inline completion indicator with result summary and duration |

### Interactive Tool Synchronization (ask_clarification, pkb_propose_memory)

```
Backend thread                              UI (browser)
───────────────                              ────────────
_run_tool_loop() executes tool
  → tool returns needs_user_input=True
  → yields tool_input_request event  ──────→  Stream handler receives event
  → calls wait_for_tool_response()             ToolCallManager renders modal
    → creates threading.Event                  User sees MCQ questions
    → event.wait(timeout=60)                   User selects answers, clicks Submit
       ↓ (blocking)                            ↓
       ↓                              POST /tool_response/<conv_id>/<tool_id>
       ↓                                ──────→ submit_tool_response()
       ↓                                         stores response in _tool_response_data
       ↓                                         calls event.set()
    event unblocks  ←──────────────────────
  → reads response from _tool_response_data
  → formats as tool result message
  → continues loop with LLM continuation call
```

**`pkb_propose_memory` interactive flow**: When the NL agent (invoked via `pkb_nl_command` tool or `/pkb` slash command) is uncertain about the user's intent, it returns `needs_user_input=True` with `proposed_claims`. Two paths:
- **Main LLM path**: `handle_pkb_nl_command` returns `ToolCallResult(needs_user_input=True, tool_name="pkb_propose_memory")` → existing tool loop shows the interactive modal with editable claim cards (text, type, dates, tags, entities, context, remove button).
- **`/pkb` slash command path**: `PKBNLConversationAgent` yields `{"type": "tool_input_request"}` → streaming loop passes through → frontend shows modal → `tool_response_waiter` unblocks → agent adds confirmed claims via `_add_confirmed_claims()`.

### Key Files in the Tool Calling Flow

| File | Role in Flow |
|---|---|
| `interface/interface.html` | Bootstrap Select dropdown (`#settings-tool-selector`) with 56 tool options in 9 optgroups; `#tool-call-modal` for interactive tools |
| `interface/chat.js` | Settings read/write via `getSelectPickerValue()`, dual-format state restoration in `setModalFromState()` |
| `interface/common.js` | `getOptions()` includes `enable_tool_use` and `enabled_tools` array in request payload |
| `interface/common-chat.js` | Stream handler dispatches tool event types to `ToolCallManager` |
| `interface/tool-call-manager.js` | `ToolCallManager` singleton — status pills, modal rendering, response submission |
| `Conversation.py` | `_get_enabled_tools()` (dual-format), `_run_tool_loop()` (agentic loop), preamble injection |
| `code_common/tools.py` | `ToolRegistry`, `@register_tool`, 56 tool definitions + handlers, `DEFAULT_ENABLED_TOOLS` |
| `code_common/call_llm.py` | `tools`/`tool_choice` passthrough, `_extract_text_from_openai_response()` yields tool_call dicts |
| `endpoints/conversations.py` | `POST /tool_response` endpoint, `wait_for_tool_response()`, thread-safe storage |