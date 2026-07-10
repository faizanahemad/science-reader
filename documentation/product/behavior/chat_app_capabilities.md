## Chat App Capabilities (Product + Engineering Analysis)

This document describes **what the chat app actually supports today** based on:
- `Conversation.py` (core runtime behavior and orchestration)
- `endpoints/external_api.md` (HTTP surface area)
- `database/external_db.md` (persistence layer)

Primary goals:
- Build a faithful **Android client** (feature parity + payload/streaming behavior).
- Clearly articulate **how this differs from ChatGPT**.
- Provide **sales pitch** materials grounded in real capabilities.

---

## What this app is (one paragraph)

This project is a **multi-modal research + productivity chat system** that combines:
- a conversation engine (`Conversation.py`) that can operate as a normal chat assistant *or* as specialized agents (deep research, literature review, interview simulation, code solving, slide generation, etc.),
- document ingestion + retrieval (`DocIndex` and friends),
- optional PKB (Personal Knowledge Base) memory retrieval and pinning,
- streaming-first UX (answers arrive incrementally),
- and utility workflows (TTS/podcast audio, transcription, code execution, diagrams, next-question suggestions, doubt clearing).

---

## Core user-facing concepts

### Conversation

Each conversation has:
- **Messages**: ordered list with `sender` and `text`, plus `message_id`, `conversation_id`, etc.
- **Memory**:
  - `running_summary`: rolling summary of the conversation (“what matters so far”).
  - `title` and `title_force_set` (manual title set via slash command).
  - **Memory Pad**: an extra “facts/notes” buffer that can be updated from assistant responses and reused in future prompts.
- **Uploaded documents**: a list of document indexes (PDFs, local files, images, data files) attached to the conversation.
- **Locking and cancellation state**: to avoid concurrent modifications and allow cancelling streaming responses.
- **Optional flag/statefulness**:
  - “Stateless mode” disables some persistence/context behavior (exposed in API).

### Workspaces (Hierarchical)

Conversations are organized into **hierarchical workspaces** per user and domain:
- Unlimited nesting depth — workspaces can contain sub-workspaces and conversations at any level.
- Create, rename, recolor, delete, and move workspaces.
- Move conversations between workspaces.
- Default workspace ("General") auto-created per `(user, domain)`.
- Deleting a workspace moves its children and conversations to its parent (or General if root).
- Cycle-safe moves — cannot move a workspace into its own descendant.

**Sidebar UI** uses jsTree (jQuery plugin) for a VS Code-like file explorer:
- Folder icons for workspaces (with color-coded left border), comment icons for conversations.
- Right-click context menus and triple-dot (kebab) menus on every node.
- Workspace context menu: New Conversation, New Sub-Workspace, Rename, Change Color, Move to... (with breadcrumb paths like `General > Private > Target`), Delete.
- Conversation context menu: Copy Conversation Reference, Open in New Window, Clone, Toggle Stateless, Set Flag, Move to... (with breadcrumb paths), Delete.
- Toolbar: file+ creates conversation in selected workspace, folder+ always creates top-level workspace.
- **New Temporary Chat button** (`fa-eye-slash`, `btn-outline-secondary`) in the top-right chat bar: creates a conversation in the default workspace and immediately marks it stateless. The conversation works normally during the session but is permanently deleted on next page reload. No confirmation modal is shown (since the user explicitly chose temporary mode).
- **Temporary conversation cleanup & graceful fallback**: When the UI loads and calls `GET /list_conversation_by_user/{domain}`, the backend deletes expired stateless conversations (older than 5 minutes) and returns `{conversations: [...], deleted_temporary_ids: [...]}`. The 5-minute grace period prevents race conditions in multi-tab scenarios where one tab's page load would delete a temp conversation another tab is still using. The UI uses `deleted_temporary_ids` to proactively clear stale `lastActiveConversationId` entries from `localStorage`. If the URL contains a conversation ID that no longer exists (e.g. a bookmarked temp chat), the UI shows a warning toast and falls back to the first available conversation. `setActiveConversation()` also validates against the loaded conversation list before firing any API calls — if the conversation is missing, it shows a toast and falls back instead of triggering cascading 404 errors from `getConversationDetails`, `fetchMemoryPad`, etc. All error handlers in `setActiveConversation` use `showToast()` instead of `alert()`.
- Expand/collapse state persisted to server.
- Active conversation highlighted with auto-expand of parent workspaces.
- **Recent Conversations section**: Collapsible "Recent" section above the workspace tree showing the 5 most recently updated conversations across all workspaces. One-click access to active conversations without navigating the workspace hierarchy. Right-click context menu reuses the same conversation menu as jsTree nodes (via fake node construction). Active conversation highlighted in both the Recent section and jsTree simultaneously. Collapse/expand state persisted to `localStorage` (scoped by user+domain). Pure front-end feature — no backend changes, data sourced from the existing `WorkspaceManager.conversations` array (already sorted by `last_updated` DESC).
- **Pinned Conversations section**: Collapsible "Pinned" section below Recent, showing flagged conversations (top 5 most recent). Reuses the existing flag/color system — any conversation with a flag appears here. Color filter dropdown (All / 🔴🔵🟢🟡🟠🟣) narrows to a specific flag color; selection persisted in `localStorage`. Flagged conversations also float above unflagged within their jsTree workspace folder (sort comparator). Right-click context menu same as Recent/jsTree. No backend changes — uses existing `/set_flag` endpoint and `flag` field from conversation metadata.
- **Conversation Archiving**: Archive/Unarchive action in the conversation context menu. Archived conversations are hidden from Recent, Pinned, and the workspace tree by default. Toggle "Show Archived" button (eye icon in sidebar toolbar) loads archived conversations and renders them in a separate "Archived" group at the bottom of the sidebar. Unarchive only available when "Show Archived" is active. Backend: `archived` property on `Conversation`, `POST /archive_conversation/<id>` toggles the flag, `GET /list_conversation_by_user` accepts `?include_archived=true`. Dimmed/italic CSS styling.
- **Time View**: Sidebar toggle (clock icon) switches between workspace tree and a flat chronological view grouped by Today / This Week / This Month / This Quarter / Older. No workspace folders shown; Recent section also hidden (Pinned stays visible). Flagged conversations float to top within each time group. Active conversation highlighted. Each group is independently collapsible with state persisted in `localStorage`. "Older" group auto-collapsed by default (visual auto-archival). Toggle state persisted. Switching back to workspace view auto-expands the active conversation's folder.
- **Message Pinning (Stars)**: Star icon on assistant message headers to pin/unpin. Pinned state persisted in SQLite `PinnedMessages` table. `POST /pin_message/<conv_id>/<msg_id>` toggles pin. `GET /get_pinned_messages/<conv_id>` returns list. Starred Messages toolbar button (★) opens a modal showing ~200-char previews of all pinned messages with "Go to message" (scrolls + highlight flash) and "View full" (shows rendered markdown inline). Pin persists across message edit/regeneration (keyed by `message_id`). Pinned message IDs fetched on conversation load; filled star icon marks pinned messages. **LLM context effect**: in auto-* history modes, up to 5 most-recently-pinned turns are always included in the LLM context window (assistant verbatim, user truncated to 200+200 tokens).
- **Smart Auto-Archival**: Automatically archives stale conversations based on multi-signal scoring. Staleness clock = max(last_updated, last_opened_at). Grace period modifiers: message count (<4 msgs → 0.5×, 4-40 → 1×, >40 → 2×) and superseded detection (newer similar conversation → 0.5×). Hybrid BM25→embedding similarity for supersession (Jaccard >0.4 pre-filter, cosine >0.75 confirmation). Exempt: flagged, pinned messages, `auto_archive_exempt` flag. Throttled to once/hour, max 5 per load, cap 50 candidates. Toast notification with Undo button. Archived section splits into "Auto-archived" and "Archived" sub-groups. User preference: grace period dropdown in chat-settings (Never/30/60/90/180 days, DB-backed). Mass archive button for bulk cleanup. Properties: `last_opened_at` (set on every history load), `auto_archive_exempt`, `archive_source` ("auto"/"manual"/null). Cache: `ConversationSimilarityCache` table stores BM25 tokens + embeddings per conversation.

**API endpoints:**
- `GET /get_auto_archive_setting` — returns `{auto_archive_grace_days: N}`
- `POST /set_auto_archive_setting` — body `{auto_archive_grace_days: N}`, validates N ∈ {0,30,60,90,180}
- `POST /auto_archive_all/<domain>` — mass archive all stale conversations (no cap), returns `{count, archived_ids}`
- `POST /create_workspace/<domain>/<name>` — optional `parent_workspace_id` in JSON body
- `PUT /move_workspace/<workspace_id>` — JSON body: `{ "parent_workspace_id": "..." }`
- `GET /get_workspace_path/<workspace_id>` — returns breadcrumb path from root
- `PUT /update_workspace/<workspace_id>` — rename, recolor, expand/collapse
- `DELETE /delete_workspace/<domain>/<workspace_id>` — cascade-safe deletion
- `PUT /move_conversation_to_workspace/<conversation_id>` — move conversation
- `POST /archive_conversation/<conversation_id>` — toggle archived state
- `POST /pin_message/<conversation_id>/<message_id>` — toggle message pin (star)
- `GET /get_pinned_messages/<conversation_id>` — list pinned messages with previews

**Key files:** `database/workspaces.py`, `database/pinned_messages.py`, `endpoints/workspaces.py`, `endpoints/conversations.py`, `interface/workspace-manager.js`, `interface/workspace-styles.css`, `interface/common-chat.js`
**Docs:** `documentation/features/workspaces/README.md`

### Multi-Conversation Tabs

Up to 5 conversations can be open simultaneously with instant switching:

- **Desktop**: Horizontal tab bar (`#conv-tab-bar`) between toolbar and chat area. Each tab gets its own DOM pane (`#chatView-{conversationId}`) inside `#chatView-container`. Switching tabs toggles CSS `.active` class -- no re-render needed.
- **Mobile**: Tab list in gear dropdown (`.gear-tab-nav`). Switching saves current state via `RenderedStateManager.saveNow()` then reloads via `setActiveConversation()`.
- **Opening tabs**: Ctrl+click (or Meta+click) a sidebar conversation, or right-click context menu "Open in New Tab". New Temp Chat opens in new tab when tabs are active.
- **Closing tabs**: Click x on a tab. Can't close last tab. Warns if response is streaming.
- **Persistence**: Tab state persisted to `localStorage` keyed by `{email}:{domain}`. Domain switch clears all tabs.
- **`$chatView(convId)` accessor**: Global function replacing all `$('#chatView')` references. Returns the correct pane for a conversation, with fallback to `$('#chatView')` before TabManager initializes.

**Key files:** `interface/tab-manager.js` (TabManager module), `interface/common-chat.js` (`$chatView()` + caller updates), `interface/workspace-manager.js` (sidebar integration), `interface/rendered-state-manager.js` (pane-aware snapshots), `interface/style.css`, `interface/interface.html`
**Docs:** `documentation/features/multi_conversation_tabs.md`

### Domains

Routes frequently include `<domain>`. In practice, it’s a tenant-like namespace for organizing a user’s content and workspaces.

---

## Capability map (features → API → storage)

This section is the “copy into Android” backbone: what exists, how to call it, what’s persisted.

### 1) Streaming chat responses

**What it does**
- The main chat request is streamed token-by-token / chunk-by-chunk.
- Streaming is newline-delimited; each line is a JSON string emitted by `Conversation.__call__` (which yields JSON objects from `reply()`).
- The server wraps this with a background task and a queue so the request thread can stream while work continues.

**API**
- `POST /send_message/<conversation_id>` (streaming `text/plain`)

**Request payload (from web UI)**
```json
{
  "messageText": "string",
  "checkboxes": { "perform_web_search": false, "use_pkb": true, "...": "various options" },
  "links": ["optional url list"],
  "search": ["optional search query list"],
  "attached_claim_ids": ["optional PKB claim ids from 'Use Now' button"],
  "referenced_claim_ids": ["optional PKB claim ids from @memory:<uuid> refs"],
  "referenced_friendly_ids": ["optional friendly IDs from @friendly_id refs (claims, contexts, entities, tags, domains, and cross-conversation message refs)"]
}
```

Server-side injection:
- `conversation_pinned_claim_ids` is injected by the server (from per-conversation pinned claims state).
- `_users_dir` and `_conversation_loader` are injected for cross-conversation reference resolution.

**Streaming response shape**
- Each line is `json.dumps({ "text": "...", "status": "..." }) + "\n"` (plus additional keys sometimes).
- The client should:
  - split by newline,
  - parse each JSON object,
  - append `text` to the assistant message,
  - optionally show `status` as progress UI.
- Some chunks include `message_ids` once the server has generated and/or persisted message IDs.
  - Shape: `{ "message_ids": { "user_message_id": "...", "response_message_id": "...", "user_message_short_hash": "...", "response_message_short_hash": "..." } }`.
  - The UI uses this to update DOM attributes so delete/move/doubts actions target the correct IDs.
  - `*_short_hash` fields (6-char base36) are present when the conversation has a `conversation_friendly_id`. They update message reference badges for the cross-conversation reference system.

**Client rendering behavior (web UI)**
- The UI renders the user message immediately, before the server responds.
- A placeholder assistant card is created when the first stream chunk arrives.
- Streaming chunks are rendered incrementally into the same card to minimize reflow.
- Breakpoints (headers/rules/paragraphs) split the streaming output into sections for stable rendering.
- Slide content (`<slide-presentation>` tags) is buffered until closing tags arrive to avoid partial HTML.
- On completion, the UI does a final render pass, initializes voting UI, and requests next-question suggestions.

**TLDR auto-summary for long answers**
- For answers >300 words, the server appends a TLDR block after the main response.
- **Controlled by "Answer TLDR" toggle** in chat settings modal (Behavior & Memory). Disabled by default. Setting key: `enable_answer_tldr`.
- Trigger: answer > 300 words, TLDR enabled, no agent active, not cancelled, not `FILLER_MODEL`.
- The prompt frames the task as writing a short direct answer (not a summary), producing better results for long responses.
- **Mid-stream async**: TLDR future fires once streaming crosses 300 words (partial answer). Runs in parallel with remaining streaming. Collected post-stream (15s timeout). Falls back to sync if future wasn't fired.
- Helper: `Conversation._generate_tldr_text(answer_text, user_query, summary_text)`. Model: `SUPERFAST_LLM[0]`.
- Wrapped in collapsible `<details>` with header “📝 TLDR Summary (Quick Read)”.

**Persistence**
- Conversation content is persisted to the filesystem under a per-conversation folder (see “Local conversation storage” below).
- Conversation membership/workspace mapping is persisted to `users.db` tables:
  - `UserToConversationId`
  - `ConversationIdToWorkspaceId`

---

### 2) Conversation history + summarization

**What it does**
- Creates a readable “conversation history” that merges:
  - rolling summary (`running_summary`)
  - recent messages formatted into a narrative-like view
- Also supports LLM-based context extraction windows for long chats.
- **Auto Context modes** (Light / Medium / Deep) intelligently select which past messages to include per query — see [`documentation/features/auto_context/README.md`](../features/auto_context/README.md).

**History selector options:** `∅` (stateless), `1`–`10` (fixed turns), `infinite`, `auto-light`, `auto-medium` (default), `auto-deep`.

**Pinned messages in LLM context**: When history mode is any `auto-*` mode, pinned (starred) assistant messages are always included in the conversation history sent to the LLM — they survive truncation regardless of how far back they are. Up to 5 most-recently-pinned turns are injected at their chronological position. The user message in each pinned turn is truncated to 200+200 tokens (first/last via `get_first_last_parts`); the assistant message is included verbatim. Pins are excluded when: history mode is `infinite`/`∅`/numeric, manual message selection (checkboxes) is active, or no pins exist. Implementation: `Conversation.py` (`retrieve_prior_context` + `reply`), `code_common/auto_context.py` (`assemble_auto_context`).

**API**
- `GET /get_conversation_history/<conversation_id>?query=...`
- `GET /list_messages_by_conversation/<conversation_id>`
- `GET /get_conversation_details/<conversation_id>`

**Persistence**
- `running_summary` lives in conversation-local memory (`memory.running_summary`) persisted in the conversation folder.

**Client rendering for history**
- History is fetched with `GET /list_messages_by_conversation/<conversation_id>`.
- The UI renders each message card with markdown conversion, optional show-more for long messages, and per-message action menus.
- Cards are assigned a stable `message-id` attribute to support edit/delete/move/doubts workflows.

---

### 3) Message editing / re-ordering / deletion

**What it does**
- Edit a message text in-place.
- Delete a specific message (by `message_id` and/or index).
- Delete a user+assistant pair in one action.
- Delete the last message, delete the whole conversation.
- Move selected messages up/down (re-order history).
- Show/hide messages (UI-driven visibility behavior).
- **Promote a pair as a doubt** — move a user+assistant pair out of the main chat history and into the doubts layer of the preceding assistant message, preserving its content.

**API**
- `POST /edit_message_from_conversation/<conversation_id>/<message_id>/<index>`
- `POST /move_messages_up_or_down/<conversation_id>`
- `POST /show_hide_message_from_conversation/<conversation_id>/<message_id>/<index>`
- `DELETE /delete_message_from_conversation/<conversation_id>/<message_id>/<index>`
- `DELETE /delete_message_pair/<conversation_id>/<message_id>/<index>`
- `DELETE /delete_last_message/<conversation_id>`
- `DELETE /delete_conversation/<conversation_id>`
- `POST /clone_conversation/<conversation_id>`
- `POST /move_pair_as_doubt/<conversation_id>/<message_id>/<index>` — promotes a user+assistant pair as a doubt on the preceding assistant message, then removes both from history

**Persistence**
- Message list is persisted per conversation in the conversation folder.
- Deleting a conversation also cleans DB mappings via `database.conversations.cleanup_deleted_conversations(...)` and deletes local conversation storage.
- **Doubt cleanup on delete**: all four delete endpoints (`delete_message_from_conversation`, `delete_message_pair`, `delete_last_message`, `move_pair_as_doubt`) now delete any `DoubtsClearing` rows attached to the removed message IDs after deletion succeeds. This prevents orphaned doubt records accumulating for messages that no longer exist. Cleanup is non-fatal — logged on failure but does not block the delete response. See `documentation/features/doubt_and_temp_llm/README.md` for details.

**Triple-dot dropdown menu items (per message card)**
- Show Doubts / Ask New Doubt
- Move Up / Move Down
- Artefacts / Fork from here
- Delete Message
- Delete Pair
- **Move Pair as Doubt** (hidden when no valid preceding assistant message exists)

---

### 4) Document ingestion + document-grounded Q&A
**What it does**
- Attach documents to a conversation via the unified **Conversation Docs modal** (`#conversation-docs-modal`) or via drag-and-drop / paperclip attachment to the current message.
- Documents are indexed and available for RAG: reference them in messages with `#doc_N`.
- Three ingress paths:
  1. **Conversation panel upload** — file picker or URL input in the modal; creates a `FastDocIndex` (BM25-only, 1-3 sec). Docs persist for the conversation lifetime.
  2. **Message attachment** — drag-and-drop onto the page or click the paperclip icon; creates a `FastDocIndex`. Available for the current turn only.
  3. **Promote message attachment** — one-click promote upgrades a message attachment to a conversation doc with a full `ImmediateDocIndex` (FAISS + LLM, 15-45 sec).
- Supports both:
  - "readable docs" (PDFs, HTML, images, small local files)
  - "data docs" (CSV/TSV/XLSX/Parquet/JSON) with preview injection into prompts
- Produces `doc_infos` that maps `#doc_N` references to titles/sources; injected into LLM system prompt.

**UI — Conversation Docs Modal**
- Entry point: `#conversation-docs-button` in the chat header (replaces old `#add-document-button-chat`).
- Modal: `#conversation-docs-modal` — two-card layout:
  - Upload card: file picker (`#conv-doc-file-input`), URL input, drag-and-drop area, XHR progress bar (0–70% upload, 70–99% indexing tick).
  - List card: `#conv-docs-list` with per-doc actions: View (PDF viewer via `/proxy_shared`), Download, Promote to Global, **Analyze** (flask icon — upgrades `FastDocIndex` to full index; shows live phase progress), **Edit / Replace** (pencil icon — opens `#doc-edit-modal` for metadata editing and optional file replacement with SSE progress), Delete.
- Manager class: `LocalDocsManager` (`interface/local-docs-manager.js`) — `setup()`, `upload()`, `list()`, `renderList()`, `refresh()`, `deleteDoc()`, `analyzeDoc()`, `_listenUpgradeProgress()`, `openEditModal()`, `_replaceDoc()`, `_listenReplaceProgress()`.
- Shared upload utilities: `DocsManagerUtils` (`interface/local-docs-manager.js`) — `uploadWithProgress()`, `isValidFileType()`, `setupDropArea()`, `getMimeType()`.
- Initialized via `LocalDocsManager.setup(conversationId)` called from `common-chat.js` when a conversation is opened (replaces old `ChatManager.setupAddDocumentForm()`).

**UI — Message Attachment (Paperclip / Drag-and-Drop)**
- Paperclip click → `#chat-file-upload` hidden file input.
- Page-level drag-and-drop → same flow.
- Both handled in `setupPaperclipAndPageDrop()` (`interface/common-chat.js`, line ~2027).
- On success: `enrichAttachmentWithDocInfo()` updates the attachment strip above the message box.

**API**
- `POST /upload_doc_to_conversation/<conversation_id>` — upload file or URL with optional `display_name` → `FastDocIndex`; returns `{doc_id, source, title, display_name}`
- `GET /list_documents_by_conversation/<conversation_id>` — returns array of `{doc_id, source, title, short_summary, visible, display_name}` (`display_name` is `null` if not set)
- `GET /download_doc_from_conversation/<conversation_id>/<doc_id>` — serve or redirect file
- `DELETE /delete_document_from_conversation/<conversation_id>/<document_id>` — remove from list (filesystem not deleted)
- `POST /attach_doc_to_message/<conversation_id>` — paperclip/drag-drop attachment → `FastDocIndex`
- `POST /promote_message_doc/<conversation_id>/<doc_id>` — promote attachment to conversation doc → `ImmediateDocIndex`
- `POST /upgrade_doc_index/<conversation_id>/<doc_id>` — **async** upgrade of a `FastDocIndex` to full `DocIndex` (FAISS + LLM); returns `202 {task_id}` immediately; the upgrade runs in a background thread
- `GET /upgrade_doc_index_progress/<task_id>` — SSE stream of upgrade progress; phases: `reading → chunking → embedding → indexing → title_summary → long_summary → saving → done`; final event has `{status: "completed", is_fast_index: false}` or `{status: "error"}`. Task cleaned up 120s after completion.
- `POST /docs/<conversation_id>/<doc_id>/replace` — **async** replace source file and re-index; returns `202 {task_id}`; accepts multipart form with `pdf_file` (required) and optional `display_name`
- `GET /replace_doc_progress/<task_id>` — SSE stream of replacement progress; phases: `reading → title_summary → long_summary → saving → done`; final event has `{status: "completed", new_doc_id: "..."}` or `{status: "error"}`. Task cleaned up 120s after completion.
- `PATCH /docs/<conversation_id>/<doc_id>/metadata` — update metadata including `display_name`, `priority`, `date_written`, `deprecated`

**Display Name**
- Optional field in the upload modal ("Display Name (optional)" input).
- Sent as `display_name` in FormData (file upload) or JSON body (URL upload).
- Stored as the 4th element of the tuple in `uploaded_documents_list`: `(doc_id, storage, source, display_name)`.
- `get_uploaded_documents()` injects it back onto each loaded `DocIndex` as `_display_name` (backward-compatible with old 3-tuples — missing 4th element defaults to `None`).
- `get_short_info()` returns `display_name` alongside title/source; UI shows it as a badge above the filename (same pattern as global docs).
**@doc/ Autocomplete**
- Type `@doc/` in the chat textarea to open a unified dropdown showing both local and global docs.
- Local docs: loaded from `DocIndex.load_local()` to get real `_title` (filename-derived for FastDocIndex, LLM-generated for full) and `_short_summary` (first 500 chars for fast, LLM for full) — no LLM calls at autocomplete time.
- Global docs: loaded from the `GlobalDocuments` DB row.
- Each result shows a type badge: blue "local", green "global". Selecting inserts `#doc_N` or `#gdoc_N` directly into the textarea.
- Backend endpoint: `GET /docs/autocomplete?conversation_id=&prefix=&limit=10` (`endpoints/documents.py`).
- Max 20 results per type in dynamic tool descriptions; capped at 100 chars per doc in the UI popover.

**User message conventions**
- Reference doc N: `#doc_1`, `#doc_2`, ... (1-based, combined numbering: uploaded docs first, then message-attached docs)
- Reference all docs: `#doc_all` / `#all_docs` and similar aliases.
- Summary directives: `#summary_doc_N`, etc.

**Numbering**
- Combined 1-based index: `#doc_1`..`#doc_M` = uploaded conversation docs; `#doc_M+1`..`#doc_N` = message-attached docs.
- Rebuilt from the combined list on every add/delete/promote. Deletion renumbers subsequent docs.
- `doc_infos` field on `Conversation` object holds the current mapping (format: `#doc_1: (Title)[source]`).

**Indexing**
- `FastDocIndex` (`DocIndex.py`, line 2104): BM25-only (rank_bm25), 1-3 sec. Used for initial uploads and message attachments.
- `ImmediateDocIndex` / `DocIndex` (`DocIndex.py`, line 959): FAISS embeddings + LLM title/summary, 15-45 sec. Created on promote.
- Factory functions: `create_fast_document_index()` (line 3066), `create_immediate_document_index()` (line 2793).
- `progress_callback` parameter on `create_immediate_document_index()` and `DocIndex.__init__()` — callable `(phase, message)` invoked at each stage; used by the upgrade background thread to stream progress to the SSE endpoint.

**Persistence (Canonical Doc Store)**
- **Canonical store**: `storage/documents/{md5(user_email)}/{doc_id}/` — single source of truth for all document indices.  Conversations and global docs hold *references* (tuples with `doc_storage` pointing here), not copies.
- **SHA-256 dedup index**: `storage/documents/{md5(user_email)}/_sha256_index.json` — maps content hashes to `doc_id` values, catching the same file uploaded under different names.
- **Dedup behavior**: Same file uploaded to N conversations → indexed once, referenced N times.  Same file under a different name → SHA-256 catches the duplicate.  "Analyze" upgrade in one conversation propagates to all conversations referencing the same doc.
- **Clone**: Copies only the tuple list — no `shutil.copytree` of doc folders.
- **Legacy path** (pre-migration): `{conv_storage}/uploaded_documents/{doc_id}/` — lazily migrated to canonical on first access; eager parallel migration at server startup via `migrate_docs.py` (sentinel file `storage/documents/.local_migration_done`).
- **Tuple format**: `(doc_id, doc_storage, doc_source, display_name)` 4-tuple; `doc_storage` now points to canonical path.
- `{conv_storage}/{conv_id}-uploaded_documents_list.json` — list of reference tuples (backward-compatible with old 3-tuples).
- `{conv_storage}/{conv_id}-message_attached_documents_list.json` — same format for attachment-scoped docs.

**Key files**
- `canonical_docs.py` — canonical store module: `store_or_get()`, `compute_file_hash()`, SHA-256 index management, lazy migration helper
- `migrate_docs.py` — eager startup migration: parallel `ThreadPoolExecutor`, progress logging, sentinel file
- `interface/local-docs-manager.js` — `LocalDocsManager` + `DocsManagerUtils` (unified modal)
- `interface/common-chat.js` — `setupPaperclipAndPageDrop()`, `setupAddDocumentForm()` (delegates to LocalDocsManager)
- `interface/interface.html` — `#conversation-docs-modal`, `#conversation-docs-button`
- `endpoints/documents.py` — 7 conversation doc routes (including `/upgrade_doc_index`)
- `endpoints/state.py` — `AppState` with `docs_folder` field
- `Conversation.py` — `add_fast_uploaded_document()`, `add_message_attached_document()`, `get_uploaded_documents()`, `delete_uploaded_document()`, `promote_message_attached_document()`, `clone_conversation()` (all accept `docs_folder` param for canonical store)
- `DocIndex.py` — `DocIndex`, `FastDocIndex`, `create_fast_document_index()`, `create_immediate_document_index()`, `get_short_info()` (now returns `is_fast_index`)

**See also**: `documentation/features/canonical_docs/README.md` — full canonical doc store architecture, SHA-256 dedup, migration strategy.
**See also**: `documentation/features/documents/doc_flow_reference.md` — full end-to-end flow reference with function names and storage layouts for all three document types.

---

### 4b) Global Documents — index once, use everywhere

**What it does**
- Provides a user-scoped document library that lives outside any single conversation.
- A document is uploaded and indexed once (via file or URL) and then available across every conversation the user opens.
- Reference syntax is identical in spirit to conversation docs but uses the `#gdoc_N` / `#global_doc_N` prefix, quoted display names, folder names, or tag names:
| Reference | Effect |
|-----------|--------|
| `#gdoc_1` or `#global_doc_1` | RAG-grounded answer from global doc 1 |
| `"my doc name"` | Reference by display name (case-insensitive match) |
| `#gdoc_all` or `#global_doc_all` | Query all global docs |
| `#folder:Research` | Query all docs in the "Research" folder |
| `#tag:arxiv` | Query all docs tagged "arxiv" |
| `#summary_gdoc_1` | Force summary of global doc 1 |
| `#dense_summary_gdoc_1` | Force dense summary of global doc 1 |
| `#full_gdoc_1` | Retrieve raw full text of global doc 1 |
- Users can **promote** a conversation-scoped document to global via the Promote button in the conversation docs list. Promotion is now **canonical-aware**: if the source doc is in the canonical store (`storage/documents/`), it is copied to global docs storage but the canonical source is preserved (not deleted), since other conversations may still reference it. FastDocIndex sources are auto-upgraded to full DocIndex on promote.
- Docs can be **organized into hierarchical folders** (pure DB metadata — storage paths unchanged) and **tagged** (free-form, many-to-many).
- Chat input autocomplete: type `#folder:` or `#tag:` to get a dropdown of matching names (debounced).

**UI — Global Docs Modal**
- Entry point: Global Docs button (globe icon) in the sidebar/toolbar → opens `#global-docs-modal`.
- **Two views** controlled by `#global-docs-view-switcher` (located in the **modal header** between the title and close button):
  - **List view**: flat doc list with `#gdoc_N` badge, display name, tag chips, action buttons. Filter bar (`#global-docs-filter`) filters in real time by tag or display name.
  - **Folder view**: independent `createFileBrowser('global-docs-fb', {...})` instance embedded directly. The **Folders** button in the modal header view switcher directly opens this embedded file browser via `GlobalDocsManager._openFileBrowser()`. No separate "Manage Folders" button exists.
- Upload card: file picker (`#global-doc-file-input`), URL input, drag-and-drop area, folder picker (`#global-doc-folder-select`), XHR progress bar (0–70% upload, 70–99% indexing tick, via `DocsManagerUtils.uploadWithProgress()`).
- Per-doc actions: View (`showPDF()` via `/global_docs/serve`), Download, **Edit / Replace** (pencil icon — opens `#doc-edit-modal` for metadata editing including tags/folder, and optional file replacement with SSE progress), Delete, Edit Tags (opens inline tag editor).
- Manager class: `GlobalDocsManager` (`interface/global-docs-manager.js`) with `_viewMode`, `_folderCache`, `_userHash` state; `filterDocList()`, `openTagEditor()`, `_loadFolderCache()`, `openEditModal()`, `_replaceDoc()`, `_listenReplaceProgress()`, `_saveTags()` methods.
- Promote from conversation docs list: `GlobalDocsManager.promote(conversationId, docId)` called from `LocalDocsManager.renderList()`.

**API**
- `POST /global_docs/upload` — upload a file or URL; indexes via `create_immediate_document_index()`. Accepts optional `folder_id`.
- `GET /global_docs/list` — returns 1-indexed array including `tags` array and `folder_id` field.
- `GET /global_docs/info/<doc_id>` — detailed info including DocIndex metadata.
- `GET /global_docs/download/<doc_id>` — download source file, with DocIndex fallback for stale paths.
- `GET /global_docs/serve?file=<doc_id>` — PDF viewer endpoint.
- `DELETE /global_docs/<doc_id>` — delete DB row and filesystem storage.
- `POST /global_docs/promote/<conversation_id>/<doc_id>` — copy-verify-delete promote flow.
- `POST /global_docs/<doc_id>/replace` — **async** replace source file and re-index; returns `202 {task_id}`; accepts multipart form with `pdf_file` (required) and optional `display_name`. Preserves metadata (priority, date_written, deprecated, tags, folder); regenerates title/summary.
- `GET /global_docs/replace_progress/<task_id>` — SSE stream of replacement progress; phases: `reading → title_summary → long_summary → saving → done`.
- `PATCH /global_docs/<doc_id>/metadata` — update metadata including `display_name`, `priority`, `date_written`, `deprecated`.
- `POST /global_docs/<doc_id>/tags` — set tags `{"tags": [...]}` (replaces all existing).
- `GET /global_docs/tags` — list all distinct tags for current user.
- `GET /global_docs/autocomplete?q=<prefix>` — tag name autocomplete for `#tag:` in chat input.
- `GET /doc_folders`, `POST /doc_folders`, `PATCH /doc_folders/<id>`, `DELETE /doc_folders/<id>` — folder CRUD.
- `POST /doc_folders/<id>/assign` — assign/unassign a doc to a folder.
- `GET /doc_folders/<id>/docs` — list docs in folder.
- `GET /doc_folders/autocomplete?q=<prefix>` — folder name autocomplete for `#folder:` in chat input.

**Persistence**
- **Database**: `GlobalDocuments` table in `users.db` (composite PK `(doc_id, user_email)`). Columns: `folder_id` (folder assignment), `index_type` (`'fast'` or `'full'` — tracks whether the doc uses `FastDocIndex` or full `DocIndex`). `GlobalDocFolders` table for folder hierarchy. `GlobalDocTags` table for tag assignments (composite PK `(doc_id, user_email, tag)`).
- **Filesystem**: `storage/global_docs/{md5(user_email)}/{doc_id}/` — storage paths unchanged by folder metadata.
- **Canonical store integration**: When promoting a conversation doc to global, the canonical source (`storage/documents/`) is preserved if other conversations reference it. Promote copies to global storage; `index_type` is set based on whether the source was a `FastDocIndex` (auto-upgraded on promote) or full `DocIndex`.
- Numbering is positional (1-based by `created_at DESC`). Deleting a doc renumbers subsequent ones.

**Key files**
- `database/global_docs.py`, `database/doc_folders.py`, `database/doc_tags.py` — DB CRUD layers.
- `endpoints/global_docs.py` — Flask Blueprint (`global_docs_bp`) with 10 routes.
- `endpoints/doc_folders.py` — Flask Blueprint (`doc_folders_bp`) with 7 folder routes.
- `Conversation.py` — `get_global_documents_for_query()` with display-name matching, `#gdoc_all` support, `#folder:` + `#tag:` resolution (lines 5561–5593), and 7 reply-flow integration points.
- `interface/global-docs-manager.js` — `GlobalDocsManager` with dual-view, tag editor, folder cache, independent `createFileBrowser('global-docs-fb', ...)` instance, `_openFileBrowser()` method, `onUpload` hook for global docs upload routing.
- `interface/common-chat.js` — `#folder:`/`#tag:` autocomplete in `handleInput()` before `@` check.
- `interface/local-docs-manager.js` — `DocsManagerUtils` shared upload utilities.
- `endpoints/static_routes.py` — `_is_missing_local_path()` guard on proxy routes.
- Global docs always use full `ImmediateDocIndex` (FAISS + LLM); conversation docs start as `FastDocIndex` and can be promoted.
- Global docs are user-scoped (keyed by email hash), not conversation-scoped.
**See also**: `documentation/features/global_docs/README.md`, `documentation/features/documents/doc_flow_reference.md`.
---

### 5) Web search + “research augmentation”

**What it does**
- Enriches answers with web search results and/or scholar-style search depending on UI toggles.
- Uses specialized agents for deep research and search strategies (e.g. Jina agents, Perplexity agent).
- **SUPERFAST_LLM optimization**: Jina search query generation and per-query combiner use `SUPERFAST_LLM[0]` (`inception/mercury-2`) for faster execution. Includes validation assertions (non-empty list of 2-tuples with non-empty string queries) and automatic fallback to `CHEAP_LLM[0]` on structured output parsing failure.

**API**
- Mostly invoked through the main chat pipeline: `POST /send_message/<conversation_id>`
  - controlled by `checkboxes.perform_web_search`, `checkboxes.googleScholar`, and query-provided `search` list.

**Persistence**
- Search results may be stored into message metadata/config (primarily UI display), and the final answer content embeds results in collapsible wrappers.

---

### 5b) MCP Web Search Server (External Tool Access)

**What it does**
- Exposes 2 of the project's web search agents as MCP (Model Context Protocol) tools accessible from external coding assistants like OpenCode and Claude Code.
- Tools: `perplexity_search` (Perplexity AI models, accepts `context` parameter), `jina_search` (Jina AI with full web content retrieval, accepts `context` parameter).
- Page-reader tools: `jina_read_page` (lightweight Jina Reader API for web pages), `read_link` (multi-format reader for web pages, PDFs, images, and YouTube via `download_link_data`).
- Runs alongside the Flask server in a daemon thread on a separate port (default 8100) using streamable-HTTP transport.

**Authentication**
- JWT bearer tokens (HS256) verified via Starlette middleware.
- Token generation CLI: `python -m mcp_server.auth --email user@example.com --days 365`.
- Clients send a static `Authorization: Bearer <jwt>` header — no OAuth flow.

**Rate limiting**
- Per-token token-bucket rate limiting (default 10 requests/minute, configurable via `MCP_RATE_LIMIT` env var).

**Configuration**
- `MCP_JWT_SECRET` (required), `MCP_PORT` (default 8100), `MCP_RATE_LIMIT` (default 10), `MCP_ENABLED` (default true).
- Reuses the same API keys (via `keyParser({})`) and agent classes as the Flask server.

**API**
- Not HTTP REST — uses the MCP protocol over streamable-HTTP. Clients connect via MCP client configuration (see client config examples in feature docs).
- Health check: `GET /health` on port 8100 (no auth required).
- Served via nginx reverse proxy at `/mcp` in production.

**Startup**
- Automatically starts from `python server.py` (no separate entry point).
- Gracefully skips if `MCP_JWT_SECRET` is not set or `MCP_ENABLED=false`.
- MCP server failure never affects the Flask server (isolated daemon thread).

**Key files:** `mcp_server/__init__.py`, `mcp_server/auth.py`, `mcp_server/mcp_app.py`, `server.py` (3-line integration).
**Documents MCP Server (port 8102)**
- Exposes document listing, querying, and full-text retrieval as MCP tools.
- **`MCP_TOOL_TIER`** env var controls tool set: `"baseline"` (4 tools, default) or `"full"` (9 tools).
- Baseline tools: `docs_list_conversation_docs`, `docs_list_global_docs`, `docs_query`, `docs_get_full_text`.
- Full-tier adds: `docs_get_info`, `docs_answer_question`, `docs_get_global_doc_info`, `docs_query_global_doc`, `docs_get_global_doc_full_text`.
- `docs_list_global_docs` returns: `index`, `doc_id`, `display_name`, `title`, `short_summary`, `doc_storage_path`, `source`, `folder_id`, `tags`.
- `docs_list_conversation_docs` returns: `index`, `doc_id`, `title`, `short_summary`, `doc_storage_path`, `source`, `display_name`.
- Key file: `mcp_server/docs.py`
**Conversation MCP Server (port 8104)**
- Exposes 12 conversation/memory tools: 7 original (memory pad get/set, history, user detail/preferences get/set, raw messages) + 5 new conversation message tools (search_messages, list_messages, read_message, get_conversation_details, get_conversation_memory_pad).
- New tools use BM25 keyword search (unigram+bigram, with markdown header/bold boosting) and text/regex matching for message search.
- All tools accept `conversation_id` as an explicit required parameter for external MCP client usage.
- Shared tool metadata defined once in `code_common/conversation_search.py` (`CONVERSATION_TOOLS` dict), imported by both `code_common/tools.py` (tool-calling) and `mcp_server/conversation.py` (MCP).
- Key file: `mcp_server/conversation.py`
**Docs:** `documentation/features/mcp_web_search_server/README.md`, `documentation/planning/plans/mcp_web_search_server.plan.md`
**Ops:** `documentation/product/ops/mcp_server_setup.md` (full 8-server architecture + Context7 local MCP, all 49 tools, JWT setup, Documents MCP tool tiers, Jina timeouts, nginx), `documentation/product/ops/server_restart_guide.md` (restart procedures for all 3 screen sessions)

**Differentiator**
- Allows the same powerful search agents available in the chat UI to be invoked directly from coding tools. No other chat system exposes its search pipeline as MCP tools for developer workflows.

---


### 5c) OpenCode Integration (Agentic Chat via `opencode serve`)

**What it does**
 Routes chat messages through an `opencode serve` instance (port 4096) instead of calling LLM provider APIs directly, giving every conversation access to OpenCode's agentic capabilities: tool use (bash, file edit, grep, LSP), MCP servers, multi-step planning, and context compaction.
 Opt-in per message via the `opencode_enabled` checkbox. Non-OpenCode conversations work exactly as before.
 Supports **two LLM providers**: OpenRouter (default, model IDs like `anthropic/claude-sonnet-4.5`) and AWS Bedrock (model IDs like `anthropic.claude-sonnet-4-5-20250929-v1:0`). Only Claude 4.5 and 4.6 models (Haiku, Sonnet, Opus) are supported.
 Per-conversation OpenCode sessions with persistent context, compaction, and tool history.
 Configurable context injection levels (minimal/medium/full) control how much conversation context is auto-injected vs available via MCP tools.

**Architecture**
 Flask server acts as a translation layer between the browser's newline-delimited JSON protocol and OpenCode's SSE event stream.
 The `opencode_client/` Python package provides: HTTP client (`OpencodeClient`), session manager (`SessionManager`), and SSE bridge (`SSEBridge`).
 SSE Bridge translates OpenCode events (`message.part.delta`, `session.idle`, tool status) into the existing `{"text": ..., "status": ...}` streaming format.
 Math formatting (`process_math_formatting`) applied to each OpenCode delta to match non-OpenCode rendering pipeline.
 Context injected into OpenCode sessions via `noReply` messages (stored without triggering AI response).

**Providers and model routing**
 Model resolver (`_resolve_opencode_model`) maps UI model names to `{providerID, modelID}` pairs.
 OpenRouter: model-family prefixes like `anthropic/` are part of the model ID (not extracted as provider).
 Bedrock: `BEDROCK_MODEL_MAP` translates OpenRouter-style names to Bedrock model IDs.
 Provider/model selection available via OpenCode settings modal in the UI.

**SSE event handling**
 OpenCode wraps ALL events under SSE `event: message`. Real event type is in `data["type"]`.
 Delta events have flat properties structure (`properties.field`, `properties.content`).
 Bridge handles reconnection (up to 5 retries), cancellation (abort session), and permission auto-approval.

**Slash commands (OpenCode mode)**
 `/compact`, `/abort`, `/new`, `/sessions`, `/fork`, `/summarize`, `/status`, `/diff`, `/revert`, `/mcp`, `/models`, `/help`
 Local commands (`/title`, `/temp`) always handled by Conversation.py. Unknown commands passed through to OpenCode.

**API**
 Main flow: `POST /send_message/<conversation_id>` with `checkboxes.opencode_enabled=true` — same endpoint, same streaming format.
 OpenCode settings: persisted in `conversation_settings.opencode_config` (provider, model, session IDs, injection level).
 Settings validated in `endpoints/conversations.py` against whitelisted provider and model values.

**UI**
 OpenCode settings modal (`#opencode-settings-modal`) with Provider dropdown (OpenRouter/Bedrock) and Model dropdown (5 Claude models).
 `opencode_enabled` checkbox in the chat options area.
 Save handler persists `opencode_provider` and `opencode_model` to conversation settings.

**Configuration**
 `opencode.json` (project root): provider config (`openrouter` with `{env:OPENROUTER_API_KEY}`, `amazon-bedrock` with region), MCP servers (7 remote servers on ports 8100-8106 + Context7 local MCP via `npx -y @upstash/context7-mcp`), permissions (bash/edit/webfetch allowed), compaction settings, AGENTS.md instructions.
 Environment variables: `OPENROUTER_API_KEY`, `OPENCODE_BASE_URL`, `OPENCODE_DEFAULT_PROVIDER`, `OPENCODE_DEFAULT_MODEL`, timeouts, SSE reconnect settings.

**Key files**
 `opencode_client/` — `client.py` (HTTP client), `session_manager.py` (conversation-to-session mapping), `sse_bridge.py` (SSE-to-Flask bridge), `config.py` (env var config)
 `Conversation.py` — `BEDROCK_MODEL_MAP`, `_resolve_opencode_model()`, `_reply_via_opencode()`, `_build_opencode_system_prompt()`, `_assemble_opencode_context()`, OpenCode slash command routing in `reply()`
 `opencode.json` — OpenCode server configuration
 `interface/interface.html` — OpenCode settings modal
 `interface/chat.js` — Settings save/load handlers
 `endpoints/conversations.py` — Settings validation whitelist
**Docs:** `documentation/features/opencode_integration/README.md`, `documentation/planning/plans/opencode_integration.plan.md`

**Differentiator**
 Transforms the chat app from a text-only assistant into an agentic system that can execute tools (bash, file editing, web search, code execution) as part of its responses. No other integration preserves the existing UI, streaming format, PKB memory, document grounding, and math rendering while adding full tool-use capabilities via a separate AI engine.

---


### 5d) Web Terminal (Browser-based Shell)

**What it does**
 Browser-based terminal accessible from Settings → Actions → Terminal, or as a standalone page at `/terminal`.
 Spawns the user's default shell (`$SHELL` or `/bin/bash`) in a PTY on the server, bridges I/O to the browser via WebSocket + xterm.js.
 General-purpose terminal — users can run any command including `opencode` if desired.
 Per-user session registry with reattach support (second tab reconnects to same PTY), configurable idle timeout (30 min default), max-sessions cap, and process-group cleanup on disconnect.

**Architecture**
 Frontend: xterm.js (CDN-loaded) with Catppuccin Mocha theme, fit addon for auto-resize.
 Backend: `endpoints/terminal.py` — `TerminalSession` class manages PTY lifecycle; `flask-sock` WebSocket endpoint at `/ws/terminal` bridges PTY ↔ browser.
 Auth: WebSocket handler checks `session["email"]` before spawning PTY. No session = `ws.close(1008)`.
 Modal uses raw DOM manipulation (no Bootstrap JS) to stack safely over the settings modal. Document-level delegated click handler bypasses Bootstrap event interference.

**nginx WebSocket proxy (required for production)**
 If deployed behind nginx, WebSocket connections to `/ws/terminal` will silently fail without proper upgrade headers. Add this location block inside the existing `server { }` block:

```nginx
# WebSocket terminal endpoint
location /ws/terminal {
    proxy_pass http://127.0.0.1:5000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket-specific timeouts
    proxy_read_timeout 3600s;    # 1 hour (matches idle timeout)
    proxy_send_timeout 60s;
    proxy_connect_timeout 10s;

    # Disable buffering for WebSocket
    proxy_buffering off;
}
```

**Config env vars**
 `TERMINAL_SHELL` — shell binary (default: `$SHELL` or `/bin/bash`), `TERMINAL_IDLE_TIMEOUT` — seconds before idle disconnect (default: 1800), `TERMINAL_MAX_SESSIONS` — max concurrent sessions per user, `PROJECT_DIR` — starting directory for the shell.

**Key files**
 `endpoints/terminal.py` — PTY + WebSocket handler, `TerminalSession` class, session registry
 `interface/opencode-terminal.js` — xterm.js client module (lazy-loaded when terminal opens)
 `interface/terminal.html` — standalone terminal page
 `interface/interface.html` — terminal modal HTML + document-level click handler
 `interface/chat.js` — `window._showTerminalModal()` / `window._closeTerminalModal()` global functions
**Docs:** `documentation/features/opencode_integration/README.md` (OpenCode integration docs include terminal), `documentation/planning/plans/opencode_integration.plan.md` (sections 12-13)

---


### 5e) LLM Tool Calling Framework (Native Mid-Response Tool Use)

**What it does**
 Adds native, mid-response tool calling to the chat pipeline — the LLM can autonomously invoke tools during a conversation turn.
 98 tools across 14 categories: clarification (1), search (5), documents (14), pkb (16), memory (7), code_runner (1), artefacts (8), prompts (5), conversation (5), cross_conversation (7 — 3 cross-conversation search + 4 tool call history), aggregator (4 — delegate_task, delegate_task_background, get_task_result, list_background_tasks), coding (12 — file system, PDF, image analysis, agent file summary, bash, todos), general (2 — generate_image, transcribe_audio), meta (1 — request_tools).
 Multi-step agentic loop: up to 10 tool-call iterations per turn (configurable `max_iterations`), with `tool_choice="none"` on the final iteration to force text output. Zero-cost `request_tools` expansions (max 2/turn) don't consume iteration budget.
 Interactive tools (ask_clarification, pkb_propose_memory) pause streaming, show a Bootstrap modal for user input (MCQ questions or editable proposed claims), wait up to 120s via `threading.Event`, then resume.
 Server-side tools (web search, document lookup, PKB operations, code execution, etc.) execute silently with inline status indicators.
 **6-mode tool selection** replaces the old master toggle + selectpicker:
   - `hybrid` (default): Fast LLM (VERY_CHEAP_LLM) selects 15-25 relevant tools per turn + `request_tools` fallback meta-tool. Best balance of token savings and capability.
   - `smart`: Same LLM selection but no fallback. Slightly fewer tokens.
   - `tiered`: Adaptive core set (~12 tools personalized from user's usage history) + `request_tools` for on-demand loading. Most token-efficient.
   - `manual`: User picks specific tools from Bootstrap Select multi-select dropdown (11 category optgroups, 98 tools).
   - `internal_only`: ONLY the host-gated internal-knowledge tool group (`search_local_internal_kb` + `ask_internal_kb` + `internal_search` + `read_internal_page` + `search_moma` + `search_yaqs` + `get_bug` + `search_code` + `search_code_standard`) — no web/perplexity search, no artefact auto-include; dedicated preamble. Resolves to no tools on hosts without the internal-search script. See `features/tool_calling/internal_search_tool.md` and `features/tool_calling/internal_search_fastpath_tools.md`.
   - `none`: Plain text, zero tool overhead.
 `request_tools` meta-tool: LLM can load additional tools mid-turn. Description dynamically lists all available-but-not-loaded tool names. Zero-cost when called alone (doesn't use iteration budget).
 Adaptive Tier 1: personalized per-user core tool set (fixed base of 5 + most-frequently-used from last 30 days via tool_call_history DB). Falls back to static 12-tool set for new users.
 Backward-compatible: old payloads with `enable_tool_use: true/false` and no `tool_mode` field map to `manual`/`none` mode.
 All 98 handlers have real implementations — mirrors the MCP server logic (DocIndex, StructuredAPI, Conversation methods, HTTP delegation for propose_edits/apply_edits/temp_llm_action). Aggregator tool (`delegate_task`) runs a non-streaming sub-agent loop via `run_agent_loop()` in `code_common/agent_tool.py`.
 **Auto-detection of tool need (backend)**: `Conversation._detect_auto_tools()` automatically activates tools when `tool_mode == "none"` and the message contains URLs or search-intent phrases. URLs inject `jina_read_page` + `read_link`; search phrases inject `perplexity_search` + `jina_search` + `jina_read_page` + `read_link`. Upgrades mode to `manual` with only detected tools. ~20 regex patterns with code-block stripping. Compiled regex cached on class.

**Architecture**
 Tool registry: `code_common/tools.py` — `ToolRegistry`, `ToolDefinition`, `ToolContext`, `ToolCallResult`, `@register_tool` decorator, `TOOL_REGISTRY` singleton, `TIER_1_TOOLS`, `get_adaptive_tier1_tools()`, `_select_relevant_tools()`, `get_compact_tool_menu()`. Agent sub-loop: `code_common/agent_tool.py` — `AGENT_PROFILES`, `AGENT_DEFAULT_MODEL`, `run_agent_loop()`.
 LLM integration: `call_chat_model()` and `call_llm()` accept `tools`/`tool_choice` params; `_extract_text_from_openai_response()` yields both `str` (text) and `dict` (tool_call) from streaming.
 Agentic loop: `Conversation._run_tool_loop()` generator — iterates up to 10 times, executes tools, handles interactive pausing, builds continuation messages. Zero-cost `request_tools` handling: if the only tool call is `request_tools`, expands `tools_config` and continues without incrementing iteration counter (max 2 per turn). When multiple tool calls are returned in one LLM response, non-interactive tools execute in **parallel** via `ThreadPoolExecutor` (each thread gets a `deepcopy` of `ToolContext` for thread safety), while interactive tools execute sequentially.
 Tool awareness: preamble injection when tools enabled provides usage guidance and **explicitly instructs the LLM to issue multiple tool calls at once** for independent information needs (parallel execution means wall-clock time equals the slowest tool, not the sum). Dynamic document listings injected into document tool descriptions. Remaining tool names injected into `request_tools` description.
 Integration flow: UI `#settings-tool_mode` select → `checkboxes.tool_mode` in `/reply` payload → `_get_enabled_tools()` dispatches by mode (tiered/smart/hybrid/manual/none) → OpenAI `tools` param built → `_inject_dynamic_doc_descriptions()` enriches doc tools → `_run_tool_loop()` enters agentic iteration.
 Smart Select: `_select_relevant_tools(user_message, summary, keys)` calls `VERY_CHEAP_LLM[0]` with compact tool menu (~2,175 tokens), HIGH RECALL prompt, returns JSON array of tool names. Guardrails: min 3 (else merge TIER_1), max 30, fail-open to static TIER_1_TOOLS. Context includes last user-assistant turn for better follow-up detection.
 Performance: Tool selection fires as `get_async_future` at the earliest point in `reply()` (~860 lines before resolution), running in parallel with PKB retrieval, prior context, TLDR extraction, and doc processing. Net latency: ~0ms. Adaptive Tier 1 cached per user (1-day TTL). UI shows "Selecting tools..." status in smart/hybrid mode.
 Interactive sync: `threading.Event` per tool_call_id, `POST /tool_response/<conv_id>/<tool_id>` endpoint unblocks the waiting thread.
 Streaming protocol: extends existing JSON-lines with `tool_call`, `tool_status`, `tool_input_request`, `tool_result` event types.
 Tool call timing: every tool call is timed end-to-end (`tool_exec_duration` for handler execution, `tool_total_duration` including user-wait for interactive tools). Timing appears in `tool_result` streaming events (`duration_seconds` field), inline status pills (`(Xs)` suffix), collapsible `<tool_calls_summary>` blocks (`(N chars, Xs)`), and `time_dict['tool_calls']` (list of `{name, duration_s, result_chars}` dicts in end-of-message YAML).

**Tool Categories**

| Category | Tools | Default | Key Operations |
|---|---|---|---|
| `clarification` | 1 | ON | MCQ clarification questions with modal UI |
| `search` | 5 | ON | Web search (Perplexity, Jina), page reading. Auto-injected by backend `_detect_auto_tools()` when URLs or search-intent keywords detected. |
| `documents` | 10 | ON | List/query/retrieve conversation docs and global docs |
|| `pkb` | 13 | OFF (`pkb_nl_command` default-enabled) | Search claims, get/add/edit/delete/pin claims, resolve @-references, NL command (`pkb_nl_command`), delete claim (`pkb_delete_claim`), interactive memory proposal (`pkb_propose_memory`) |
| `memory` | 7 | OFF | Memory pad, conversation history, user details/preferences |
| `code_runner` | 1 | OFF | Python code execution (120s timeout, IPython) |
| `artefacts` | 8 | OFF | List/create/get/update/delete artefacts, LLM-powered edits |
| `prompts` | 5 | OFF | List/get/create/update prompts, ephemeral LLM actions |
| `conversation` | 5 | OFF | Search, list, read messages. Get conversation overview and memory pad. BM25 keyword search + text/regex matching. |
| `cross_conversation` | 3+4 | OFF | Cross-conversation search/list/summary (3 tools) + tool call history (4 tools: list/get for search history, list/get for all tool history). |
| `aggregator` | 1 | OFF | `delegate_task` meta-tool: delegates sub-tasks to an autonomous agent with its own tool access. 3 profiles (`research`, `documents`, `general`), up to 5 iterations, `gpt-4o-mini` default model, 1-level recursion. Core module: `code_common/agent_tool.py`. |

**API**
 Settings: `checkboxes.enable_tool_use` (master toggle), `checkboxes.enabled_tools` (array of tool name strings, e.g. `["ask_clarification", "web_search", ...]`; legacy per-category dict format also accepted for backward compatibility).
 New endpoint: `POST /tool_response/<conversation_id>/<tool_id>` — submit interactive tool response `{ "response": { "answers": [...] } }` → 200/400/404.
 Main flow: `POST /send_message/<conversation_id>` — same endpoint, tools activated when enabled.

**Streaming response extensions**
 New event types in JSON-lines: `tool_call` (LLM requests tool), `tool_status` (executing/waiting/completed), `tool_input_request` (modal needed), `tool_result` (completion summary + `duration_seconds` timing).

**Persistence**
 Tool settings persisted per-conversation via existing chat settings mechanism (`checkboxes` payload).
 Tool results not separately persisted — they become part of the conversation messages.

**Key files**
`code_common/tools.py` — Tool registry + 87 tool definitions with real handlers, `DEFAULT_ENABLED_TOOLS`
`code_common/conversation_search.py` — Shared conversation tool metadata (`CONVERSATION_TOOLS`), BM25 message search index (`MessageSearchIndex`), markdown feature extraction
`code_common/agent_tool.py` — Agent sub-loop: `AGENT_PROFILES`, `AGENT_DEFAULT_MODEL`, `AGENT_MAX_ITERATIONS`, `AGENT_TOOLS` shared metadata, `run_agent_loop()`
`code_common/call_llm.py` — `tools`/`tool_choice` passthrough, streaming tool_call parsing
`call_llm.py` (root) — `CallLLm` tools passthrough
`Conversation.py` — `_get_enabled_tools()`, `_run_tool_loop()`, preamble injection, `reply()` tool branching, `search_messages()`, `list_messages()`, `read_message()`, `get_conversation_details()`, `_index_messages_for_search()`, `message_search_index` in `store_separate`
`endpoints/conversations.py` — `POST /tool_response` endpoint, thread-safe response store
`interface/tool-call-manager.js` — `ToolCallManager` singleton (inline status, modal, response submission)
`interface/interface.html` — Bootstrap Select 1.13.18 CDN, tool settings `<select multiple>` with 11 optgroups and 87 options, `#tool-call-modal`
`interface/chat.js`, `interface/common.js`, `interface/common-chat.js` — settings persistence (selectpicker read/write with dual-format legacy support), stream handler, search-intent auto-detection (`detectSearchIntent`, `mergeWebSearchTools`, `SEARCH_INTENT_PATTERNS`), default tool enablement (`computeDefaultStateForTab` with `enable_tool_use: true`)
`interface/service-worker.js` — cache version bump, precache

**Docs:** `documentation/features/tool_calling/README.md`, `documentation/features/agent_delegate_task/README.md`, `documentation/planning/plans/llm_tool_calling_framework.plan.md`, `documentation/planning/plans/agent_delegate_task.plan.md`

**Differentiator**
 Transforms the chat from a single-turn request-response system into an agentic system where the LLM can chain multiple tool calls (search, lookup documents, query PKB, execute code, manage artefacts) within a single response turn, and delegate complex multi-tool workflows to autonomous sub-agents via `delegate_task`. No other chat system integrates document RAG, PKB memory, code execution, web search, and agent delegation as native LLM tools with a per-category permission model and interactive UI.

---

### 6) Multi-model responses and formatting

**What it does**
- The "Main Model" selector (`#settings-main-model-selector`) is a bootstrap-select enhanced `<select multiple>` that defaults to **single-select mode** — clicking a model replaces the previous selection in one click. A "Multi-select" toggle button at the top of the dropdown switches to multi-select mode for ensemble responses. Mode preference persists to `localStorage` (`modelSelectorMultiMode`).
- In single mode, a `changed.bs.select` handler in `chat.js` intercepts selections and deselects all others, keeping only the newly clicked model.
- In multi-select mode, the user can select multiple models; the conversation runs a multi-model "ensemble" response.
- Responses are streamed in a **collapsible per-model format**, so users can expand each model's output.

**How models are invoked**
- Multiple model names are passed in `checkboxes.main_model` (array).
- The server normalizes them and, when appropriate, uses an `NResponseAgent` to orchestrate streaming.
- The underlying multi-model streamer executes models in parallel but displays their outputs sequentially (order of first response).
- **Host-local synthetic models** (both pass only **user question + running summary**; no full history / chat tools / OpenRouter fallback):
  - **`local/gemini-rag`**: `~/.local/bin/gemini-rag-query` (`GEMINI_RAG_SCRIPT_PATH`). Always `--detailed`, and (from the chat path) always `--reformulate` + `--duckie`. Learning: optional CLI flags stay off by default when invoking the binary by hand. Pipeline: optional ≤16-word search rewrite → concurrent duckie_cli + moma discovery → parallel page reads (default **`--max-urls 20`**, hard clamp 1–20; override with `GEMINI_RAG_MAX_URLS` or CLI `--max-urls`) → Gemini synthesis over moma extracts + duckie text (+ FAQ/next expansion). Kill-switch: `GEMINI_RAG_DISABLED=1`. Implementation: `code_common/local_cli_llms.py`.
  - **`local/gemini-agent`**: `~/.local/bin/gemini-agent-query` (`GEMINI_AGENT_SCRIPT_PATH`). Fast ReAct profile (`--max-depth 2 --personas 0 --max-loops 2 --max-tool-iterations 4 --loop-mode direct-retry --budget 20 --history-window 2 --synth-backend gemini`). Kill-switch: `GEMINI_AGENT_DISABLED=1`. Implementation: `code_common/local_cli_llms.py`.
