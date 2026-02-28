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
- Expand/collapse state persisted to server.
- Active conversation highlighted with auto-expand of parent workspaces.

**API endpoints:**
- `POST /create_workspace/<domain>/<name>` — optional `parent_workspace_id` in JSON body
- `PUT /move_workspace/<workspace_id>` — JSON body: `{ "parent_workspace_id": "..." }`
- `GET /get_workspace_path/<workspace_id>` — returns breadcrumb path from root
- `PUT /update_workspace/<workspace_id>` — rename, recolor, expand/collapse
- `DELETE /delete_workspace/<domain>/<workspace_id>` — cascade-safe deletion
- `PUT /move_conversation_to_workspace/<conversation_id>` — move conversation

**Key files:** `database/workspaces.py`, `endpoints/workspaces.py`, `interface/workspace-manager.js`, `interface/workspace-styles.css`
**Docs:** `documentation/features/workspaces/README.md`

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
- For very long answers, the server appends a TLDR block after the main response.
- Trigger conditions:
  - Answer length > 1000 words
  - No specialized agent is active
  - Not cancelled; model is not `FILLER_MODEL`
- The TLDR is generated with `tldr_summary_prompt`, using the user query + running summary + full answer.
- Model selection uses `conversation_settings.model_overrides.tldr_model` if set, otherwise `CHEAP_LONG_CONTEXT_LLM[0]`.
- The TLDR is wrapped in a collapsible `<details>` section with header “📝 TLDR Summary (Quick Read)”.

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
- Delete the last message, delete the whole conversation.
- Move selected messages up/down (re-order history).
- Show/hide messages (UI-driven visibility behavior).

**API**
- `POST /edit_message_from_conversation/<conversation_id>/<message_id>/<index>`
- `POST /move_messages_up_or_down/<conversation_id>`
- `POST /show_hide_message_from_conversation/<conversation_id>/<message_id>/<index>`
- `DELETE /delete_message_from_conversation/<conversation_id>/<message_id>/<index>`
- `DELETE /delete_last_message/<conversation_id>`
- `DELETE /delete_conversation/<conversation_id>`
- `POST /clone_conversation/<conversation_id>`

**Persistence**
- Message list is persisted per conversation in the conversation folder.
- Deleting a conversation also cleans DB mappings via `database.conversations.cleanup_deleted_conversations(...)` and deletes local conversation storage.

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
  - List card: `#conv-docs-list` with per-doc actions: View (PDF viewer via `/proxy_shared`), Download, Promote to Global, Delete.
- Manager class: `LocalDocsManager` (`interface/local-docs-manager.js`) — `setup()`, `upload()`, `list()`, `renderList()`, `refresh()`, `deleteDoc()`.
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

**Display Name**
- Optional field in the upload modal ("Display Name (optional)" input).
- Sent as `display_name` in FormData (file upload) or JSON body (URL upload).
- Stored as the 4th element of the tuple in `uploaded_documents_list`: `(doc_id, storage, source, display_name)`.
- `get_uploaded_documents()` injects it back onto each loaded `DocIndex` as `_display_name` (backward-compatible with old 3-tuples — missing 4th element defaults to `None`).
- `get_short_info()` returns `display_name` alongside title/source; UI shows it as a badge above the filename (same pattern as global docs).
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

**Persistence**
- `{conv_storage}/uploaded_documents/{doc_id}/` — per-doc folder with `.index` pickle, FAISS indices, BM25 chunks, source file.
- `{conv_storage}/{conv_id}-uploaded_documents_list.json` — list of `(doc_id, doc_storage, doc_source, display_name)` 4-tuples (`display_name` may be `None` for older entries; code is backward-compatible with 3-tuples).
- `{conv_storage}/{conv_id}-message_attached_documents_list.json` — same format for attachment-scoped docs.

**Key files**
- `interface/local-docs-manager.js` — `LocalDocsManager` + `DocsManagerUtils` (new file, unified modal)
- `interface/common-chat.js` — `setupPaperclipAndPageDrop()`, `setupAddDocumentForm()` (delegates to LocalDocsManager)
- `interface/interface.html` — `#conversation-docs-modal`, `#conversation-docs-button`
- `endpoints/documents.py` — all 6 conversation doc routes
- `Conversation.py` — `add_fast_uploaded_document()` (line 1601), `add_message_attached_document()` (line 1741), `get_uploaded_documents()` (line 1698), `delete_uploaded_document()` (line 1723), `promote_message_attached_document()` (line 1854), `get_uploaded_documents_for_query()` (line 5447)
- `DocIndex.py` — `DocIndex`, `FastDocIndex`, `create_fast_document_index()`, `create_immediate_document_index()`

**See also**: `documentation/features/documents/doc_flow_reference.md` — full end-to-end flow reference with function names, line numbers, and storage layouts for all three document types.

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
- Users can **promote** a conversation-scoped document to global via the Promote button in the conversation docs list. The doc is moved (not copied) — no re-indexing required.
- Docs can be **organized into hierarchical folders** (pure DB metadata — storage paths unchanged) and **tagged** (free-form, many-to-many).
- Chat input autocomplete: type `#folder:` or `#tag:` to get a dropdown of matching names (debounced).

**UI — Global Docs Modal**
- Entry point: Global Docs button (globe icon) in the sidebar/toolbar → opens `#global-docs-modal`.
- **Two views** controlled by `#global-docs-view-switcher` (located in the **modal header** between the title and close button):
  - **List view**: flat doc list with `#gdoc_N` badge, display name, tag chips, action buttons. Filter bar (`#global-docs-filter`) filters in real time by tag or display name.
  - **Folder view**: independent `createFileBrowser('global-docs-fb', {...})` instance embedded directly. The **Folders** button in the modal header view switcher directly opens this embedded file browser via `GlobalDocsManager._openFileBrowser()`. No separate "Manage Folders" button exists.
- Upload card: file picker (`#global-doc-file-input`), URL input, drag-and-drop area, folder picker (`#global-doc-folder-select`), XHR progress bar (0–70% upload, 70–99% indexing tick, via `DocsManagerUtils.uploadWithProgress()`).
- Per-doc actions: View (`showPDF()` via `/global_docs/serve`), Download, Delete, Edit Tags (opens tag editor).
- Manager class: `GlobalDocsManager` (`interface/global-docs-manager.js`) with `_viewMode`, `_folderCache`, `_userHash` state; `filterDocList()`, `openTagEditor()`, `_loadFolderCache()` methods.
- Promote from conversation docs list: `GlobalDocsManager.promote(conversationId, docId)` called from `LocalDocsManager.renderList()`.

**API**
- `POST /global_docs/upload` — upload a file or URL; indexes via `create_immediate_document_index()`. Accepts optional `folder_id`.
- `GET /global_docs/list` — returns 1-indexed array including `tags` array and `folder_id` field.
- `GET /global_docs/info/<doc_id>` — detailed info including DocIndex metadata.
- `GET /global_docs/download/<doc_id>` — download source file, with DocIndex fallback for stale paths.
- `GET /global_docs/serve?file=<doc_id>` — PDF viewer endpoint.
- `DELETE /global_docs/<doc_id>` — delete DB row and filesystem storage.
- `POST /global_docs/promote/<conversation_id>/<doc_id>` — copy-verify-delete promote flow.
- `POST /global_docs/<doc_id>/tags` — set tags `{"tags": [...]}` (replaces all existing).
- `GET /global_docs/tags` — list all distinct tags for current user.
- `GET /global_docs/autocomplete?q=<prefix>` — tag name autocomplete for `#tag:` in chat input.
- `GET /doc_folders`, `POST /doc_folders`, `PATCH /doc_folders/<id>`, `DELETE /doc_folders/<id>` — folder CRUD.
- `POST /doc_folders/<id>/assign` — assign/unassign a doc to a folder.
- `GET /doc_folders/<id>/docs` — list docs in folder.
- `GET /doc_folders/autocomplete?q=<prefix>` — folder name autocomplete for `#folder:` in chat input.

**Persistence**
- **Database**: `GlobalDocuments` table in `users.db` (composite PK `(doc_id, user_email)`). Added `folder_id` column via idempotent `ALTER TABLE` migration. `GlobalDocFolders` table for folder hierarchy. `GlobalDocTags` table for tag assignments (composite PK `(doc_id, user_email, tag)`).
- **Filesystem**: `storage/global_docs/{md5(user_email)}/{doc_id}/` — storage paths unchanged by folder metadata.
- Numbering is positional (1-based by `created_at ASC`). Deleting a doc renumbers subsequent ones.

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

**API**
- Mostly invoked through the main chat pipeline: `POST /send_message/<conversation_id>`
  - controlled by `checkboxes.perform_web_search`, `checkboxes.googleScholar`, and query-provided `search` list.

**Persistence**
- Search results may be stored into message metadata/config (primarily UI display), and the final answer content embeds results in collapsible wrappers.

---

### 5b) MCP Web Search Server (External Tool Access)

**What it does**
- Exposes 3 of the project's web search agents as MCP (Model Context Protocol) tools accessible from external coding assistants like OpenCode and Claude Code.
- Tools: `perplexity_search` (Perplexity AI models), `jina_search` (Jina AI with full web content retrieval), `deep_search` (multi-hop iterative search with interleaved search-answer cycles).
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
**Docs:** `documentation/features/mcp_web_search_server/README.md`, `documentation/planning/plans/mcp_web_search_server.plan.md`
**Ops:** `documentation/product/ops/mcp_server_setup.md` (full 8-server architecture, all 37 tools, JWT setup, Documents MCP tool tiers, Jina timeouts, nginx), `documentation/product/ops/server_restart_guide.md` (restart procedures for all 3 screen sessions)

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
 `opencode.json` (project root): provider config (`openrouter` with `{env:OPENROUTER_API_KEY}`, `amazon-bedrock` with region), MCP servers (7 servers on ports 8100-8106), permissions (bash/edit/webfetch allowed), compaction settings, AGENTS.md instructions.
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

### 6) Multi-model responses and formatting

**What it does**
- The UI can select multiple models for a single request via the “Main Model” multi-select.
- If multiple models are selected and no specialized agent is chosen, the conversation runs a multi-model “ensemble” response.
- Responses are streamed in a **collapsible per-model format**, so users can expand each model’s output.

**How models are invoked**
- Multiple model names are passed in `checkboxes.main_model` (array).
- The server normalizes them and, when appropriate, uses an `NResponseAgent` to orchestrate streaming.
- The underlying multi-model streamer executes models in parallel but displays their outputs sequentially (order of first response).

**Formatting of multi-model output**
- Each model’s response is wrapped in a `<details>` block with a header like “Response from <model>”.
- A `---` separator is appended after all model responses.
- The UI renders these sections as collapsible blocks with standard markdown support.

**Key implementations**
- `Conversation.py` (model selection + ensemble trigger + agent wiring).
- `agents/search_and_information_agents.py` (`NResponseAgent`).
- `call_llm.py` (`CallMultipleLLM`) + `common.py` (`stream_multiple_models`).

---

### 6) PKB (Personal Knowledge Base) / Claims Memory System

**What it does**
- Stores personal facts, preferences, decisions, and tasks as **claims** (atomic memory units) in a SQLite-backed Personal Knowledge Base.
- Each claim has: statement, claim_type, context_domain, friendly_id, possible_questions (QnA), and optional contexts/groups.
- **Contexts** (groups) organize claims hierarchically; referencing `@context_friendly_id` in chat resolves to all claims within that context and sub-contexts.
- **Entities** represent people, organizations, or other named objects linked to claims. Referencing `@entity_friendly_id` resolves to all claims linked to that entity (any role).
- **Tags** categorize claims and form a hierarchy. Referencing `@tag_friendly_id` resolves to all claims tagged with that tag and all descendant tags (recursive).
- **Domains** are topic namespaces (health, work, personal, etc.). Referencing `@domain_friendly_id` filters claims by that context domain.
- Retrieves relevant claims as context for the current query, combining multiple sources with explicit prioritization:
  1. `@friendly_id` / `@memory:uuid` references (highest -- user explicitly asked for these)
  2. attached claims ("Use in next message" UI selection)
  3. globally pinned claims
  4. conversation-pinned claims
  5. auto-retrieved via hybrid (FTS5 + embedding) search

**Universal @References (v0.7)**

All PKB object types are referenceable in chat via `@friendly_id` with type-suffixed IDs to eliminate namespace clashes:

| Reference Type | Suffix | Example | Resolves To |
|---------------|--------|---------|-------------|
| Claim | none (most common) | `@prefer_morning_a3f2` | Single claim |
| Context | `_context` | `@health_goals_context` | All claims in context + sub-contexts (recursive) |
| Entity | `_entity` | `@john_smith_person_entity` | All claims linked to entity via `claim_entities` join |
| Tag | `_tag` | `@fitness_tag` | All claims tagged with tag + descendant tags (recursive CTE) |
| Domain | `_domain` | `@health_domain` | All claims with matching `context_domain` |

The backend resolver (`resolve_reference()`) uses suffix-based routing for fast dispatch:
- If reference ends with `_context` → resolve as context
- If reference ends with `_entity` → resolve as entity
- If reference ends with `_tag` → resolve as tag
- If reference ends with `_domain` → resolve as domain
- No suffix → backwards-compatible path (claim_number → claim friendly_id → legacy context → context name fallback)

**Autocomplete** (UI: `@` in chat input) now returns results across all five categories:
- `memories`: claim friendly_ids
- `contexts`: context friendly_ids (with `_context` suffix)
- `entities`: entity friendly_ids (with `_entity` suffix, icon: person)
- `tags`: tag friendly_ids (with `_tag` suffix, icon: tag)
- `domains`: domain friendly_ids (with `_domain` suffix, icon: grid)

**Chat integration flow**
- UI parses `@references` from message text (`parseMemoryReferences()`) and collects "Use Now" attachments (`PKBManager.getPendingAttachments()`).
- Server injects conversation-pinned claim IDs from session state.
- `Conversation.reply()` fetches claims via `_get_pkb_context()` in a background thread.
- Each `@friendly_id` is resolved by `resolve_reference()` which routes by suffix to the correct resolver (claim, context, entity, tag, or domain).
- Full PKB context is sent to a cheap LLM for distillation (extracts relevant user prefs).
- After distillation, explicitly `[REFERENCED]` claims are re-injected verbatim via `_extract_referenced_claims()` to ensure they reach the main LLM word-for-word.
- The combined user_info_text (distilled prefs + referenced claims) is injected into the `permanent_instructions` slot of the chat prompt.

**Toggle**
- Controlled by `checkboxes.use_pkb` (UI: "Use PKB Memory" checkbox, default enabled). When unchecked, PKB retrieval and user info distillation are skipped entirely.

**APIs**
- PKB management and retrieval:
  - `GET/POST/PUT/DELETE /pkb/claims[...]`
  - `GET/POST/PUT/DELETE /pkb/contexts[...]`
  - `POST /pkb/search`
  - `POST /pkb/relevant_context`
  - `POST /pkb/analyze_statement` (LLM-powered auto-fill: extracts claim_type, context_domain, tags, entities, possible_questions, friendly_id from a statement in one call; used by the "Auto-fill" button in the Add/Edit Memory modal and by text ingestion enrichment)
  - `GET /pkb/autocomplete?prefix=...` (powers `@` autocomplete in chat input; returns memories, contexts, entities, tags, domains)
  - pinning endpoints (`/pkb/*/pin`, `/pkb/pinned`, conversation pinning routes)
- Main chat uses PKB context automatically if available (part of `send_message` execution).

**Persistence**
- PKB uses a separate sqlite DB: `pkb.sqlite` under `users_dir`.
- Schema v7 with: claims, contexts, context_claims (M:N), entities (with `friendly_id`), tags (with `friendly_id`), claim_entities, claim_tags, claims_fts (FTS5), claim_embeddings.
- Entity and tag friendly_ids are auto-generated with type suffixes (`_entity`, `_tag`) and indexed.
- Context friendly_ids have `_context` suffix (migrated from unsuffixed in v6→v7).
- Domain references are computed at query time (no separate DB table).
- Conversation-level pinned claims are tracked server-side (in app state) and injected into chat requests.

**Key files**
- `truth_management_system/` -- core module (models, CRUD, search, LLM helpers)
- `truth_management_system/llm_helpers.py` -- `LLMHelpers` class, `analyze_claim_statement()` (shared single-call extraction for auto-fill and text ingestion enrichment), `ClaimAnalysisResult` dataclass
- `truth_management_system/interface/structured_api.py` -- StructuredAPI facade, `resolve_reference()` (suffix-based routing), `autocomplete()` (all 5 categories)
- `truth_management_system/interface/text_ingestion.py` -- `TextIngestionDistiller`, `_enrich_candidates()` (post-parse enrichment with tags/entities/questions)
- `truth_management_system/crud/entities.py` -- `get_by_friendly_id()`, `resolve_claims()`, `search_friendly_ids()`
- `truth_management_system/crud/tags.py` -- `get_by_friendly_id()`, `resolve_claims()` (recursive CTE), `search_friendly_ids()`
- `truth_management_system/utils.py` -- `generate_entity_friendly_id()`, `generate_tag_friendly_id()`, `generate_context_friendly_id()`, `domain_to_friendly_id()`
- `truth_management_system/database.py` -- `_migrate_v6_to_v7()` (adds friendly_id to entities/tags, appends `_context` to contexts)
- `Conversation.py` -- `_get_pkb_context()`, `_extract_referenced_claims()`
- `interface/pkb-manager.js` -- UI for claims CRUD, contexts, search
- `interface/common-chat.js` -- autocomplete rendering for all 5 categories (entities, tags, domains with type badges)
- `interface/parseMessageForCheckBoxes.js` -- `parseMemoryReferences()` for `@` reference parsing
- `endpoints/pkb.py` -- REST API endpoints

**Differentiator**
- This is a major capability gap vs "plain ChatGPT chat": it supports an internal, queryable memory store with explicit attachment, pinning, context grouping, entity and tag linking, domain namespacing, inline `@` references with type-aware autocomplete across all object types, recursive resolution (contexts and tags), and QnA-style retrieval.

---

### 6b) Cross-Conversation Message References

**What it does**
- Users can reference specific messages from any of their conversations using `@conversation_<friendly_id>_message_<index_or_hash>` syntax.
- The referenced message content is injected into the LLM prompt alongside PKB claims, enabling knowledge reuse across conversations without copy-paste.
- Each conversation gets a short, human-readable `conversation_friendly_id` (e.g. `react_optimization_b4f2`) generated from the title.
- Each message gets a `message_short_hash` (6-char base36) for stable cross-conversation referencing.

**UI**
- Sidebar context menu: "Copy Conversation Reference" (first item, `fa-at` icon) copies the conversation friendly ID.
- Message card headers: reference badge shows `#<index> . <hash>`. Click copies the full `@conversation_<fid>_message_<hash>` reference.
- During streaming, badges update with hashes when `message_ids` arrive.

**Backend**
- `_get_pkb_context()` separates conversation refs from PKB refs using `CONV_REF_PATTERN` regex.
- Resolves conversation friendly ID via DB lookup, loads conversation via cache-aware loader, extracts the target message.
- Injects as `[REFERENCED @conversation_...]` blocks that survive post-distillation re-injection.

**Key files:** `conversation_reference_utils.py`, `Conversation.py`, `database/conversations.py`, `interface/workspace-manager.js`, `interface/common-chat.js`
**Docs:** `documentation/features/cross_conversation_references/README.md`

---

### 6c) Clarification Flow (`/clarify` Slash Command)

**What it does**
- User types `/clarify`, `/clarification`, or `/clarifications` anywhere in a message (outside backtick spans) and presses Enter.
- Instead of sending the message, the app fires the clarification flow: calls the `/clarify_intent` endpoint, shows a modal with 1–3 clarifying questions, and appends the answered Q&A to the message composer in a `[Clarifications]` block.
- Multiple rounds are supported — each `/clarify` call appends another block separated by `---`; Q numbering resets to Q1 per round.
- Never auto-sends: the user always controls when to actually send the message.
- **Auto Clarify checkbox** (`settings-auto_clarify`) also triggers the flow before sending (with `forceClarify: false`); in that mode, if the backend finds no questions needed, the modal auto-closes and the message sends normally.

**`forceClarify` flag**
- Slash command → `forceClarify: true` → backend MUST produce 1–3 questions, never returns "already clear"
- Auto-clarify checkbox → `forceClarify: false` → backend may return `needs_clarification: false`; modal auto-closes

**Context used by the clarification LLM**
- Conversation summary (running summary field)
- Last 3 turns of history (assistant capped 8k chars, user capped 6k chars)
- Raw PKB claims (no LLM summarization step; capped at 6k chars)
- Current message text (with `/clarify` tokens stripped)

**API**
- `POST /clarify_intent/<conversation_id>` — `{ messageText, checkboxes, forceClarify }` → `{ needs_clarification: bool, questions: [ { id, prompt, options: [ { id, label } ] } ] }`
- Rate limit: 30/minute. Fail-open: always returns valid JSON.

**Model override**
- `clarify_intent_model` key in conversation model overrides controls which LLM generates the questions. Default: `VERY_CHEAP_LLM[0]`. Configurable per-conversation via the "Clarify Models" section in the Model Overrides modal.

**Key files**: `interface/parseMessageForCheckBoxes.js` (`processClarifyCommand`), `interface/common-chat.js` (send intercept), `interface/clarifications-manager.js` (modal + multi-round append), `endpoints/conversations.py` (`clarify_intent` endpoint), `interface/chat.js` (`clarify_intent_model` persistence)
**Full docs**: `documentation/product/behavior/CLARIFICATIONS_AND_AUTO_DOUBT_CONTEXT.md`

---

### 7) “Doubt clearing” as a first-class workflow

**What it does**
- A dedicated endpoint that streams an explanation of a specific message.
- Persists the doubt and its answer into SQLite (`DoubtsClearing`), supports follow-up chains.
- Supports cancellation of doubt clearing independently from main chat cancellation.

**API**
- `POST /clear_doubt/<conversation_id>/<message_id>` (streaming)
- `GET /get_doubt/<doubt_id>`
- `GET /get_doubts/<conversation_id>/<message_id>`
- `DELETE /delete_doubt/<doubt_id>`
- `POST /cancel_doubt_clearing/<conversation_id>` (conversation cancellation helpers)

**Persistence**
- `users.db` table: `DoubtsClearing`

---

### 8) Next question suggestions

**What it does**
- Suggests “what to ask next” based on recent conversation context and summary.

**API**
- `GET /get_next_question_suggestions/<conversation_id>`

---

### 9) Code execution + artifacts (plots, files, diagrams)

**What it does**
- When enabled (checkboxes or preamble options), the assistant can:
  - emit code blocks intended for execution,
  - execute code in a persistent python session,
  - stream stdout/stderr back into the chat,
  - publish generated artifacts:
    - plots/images (served via `/get_conversation_output_docs/...`)
    - generated files with downloadable links
  - handle diagrams:
    - Mermaid blocks (detected and rendered by the client)
    - Draw.io XML payloads (saved + links for editing and downloading)

**API**
- Main flow: `POST /send_message/<conversation_id>` (streaming)
- Explicit one-off runner:
  - `POST /run_code_once` with `{ "code_string": "..." }`
- Artifact serving:
  - `GET /get_conversation_output_docs/<SALT>/<conversation_id>/<filename>`

**Android implications**
- You’ll need:
  - a streaming parser,
  - Markdown rendering,
  - special-case handling for `<slide-presentation>` wrappers,
  - a way to render mermaid/drawio or at least open in browser.

---

### 10) Slides / presentations

**What it does**
- When “ppt_answer” mode is enabled, the conversation uses a slide agent to generate:
  - storyboard
  - final HTML slide presentation
- Response is wrapped with a marker:
  - `<slide-presentation> ... </slide-presentation>`

**API**
- Triggered via `POST /send_message/<conversation_id>` with `checkboxes.ppt_answer=true`.

**Android implications**
- Decide whether to:
  - render the HTML slide deck in a WebView, or
  - transform it to native slides (harder), or
  - provide “open in browser”.

---

### 11) Audio: TTS / podcast mode + transcription

**What it does**
- Generate audio for a message:
  - normal TTS
  - “code-aware” TTS variants
  - podcast-style conversions (streaming and non-streaming)
- Transcribe uploaded audio.

**API**
- `POST /tts/<conversation_id>/<message_id>` (streaming `audio/mpeg` or file)
- `POST /is_tts_done/<conversation_id>/<message_id>` (legacy “always done”)
- `POST /transcribe` (multipart form `audio`)

**Differentiator**
- This is a strong “accessibility + content repurposing” story compared to default ChatGPT chat.

---

### 12) Titles, temporary mode, and prompt controls

**What it does**
- Slash command: `/title ...` or `/set_title ...`
- Temporary mode: `/temp ...` disables persistence for that interaction.
- **Stateless conversations**: Right-click → "Toggle Stateless" marks a conversation for deletion on next page reload. The conversation works normally during the current session.
- **New Temporary Chat button**: The `#new-temp-chat` button in the top-right chat bar creates a fresh conversation in the default workspace and marks it stateless in a single atomic server request (`POST /create_temporary_conversation/{domain}`). The server handles cleanup of old stateless conversations, creation, stateless marking, and list building in one call. The conversation is deleted on next page reload.
- User-controllable system/preamble options:
  - formatting variants
  - “TTS friendly” style guide
  - “Engineering Excellence”, “Google GL”, interview modes, etc.
- Custom prompts: options prefixed with `custom:<prompt_name>` load from the prompts manager.

**API**
- Mostly via `POST /send_message/<conversation_id>` payload:
  - `checkboxes.preamble_options`
  - `checkboxes.permanentText`
  - `checkboxes.main_model`
  - `checkboxes.field` (agent selection)

---

## UI shell caching (Service Worker)

The web UI registers a Service Worker to cache the app shell (JS/CSS/icons) so that reopening the interface does not re-download the same assets.

**Scope + behavior**
- Service Worker: `interface/service-worker.js` (served at `/interface/service-worker.js`).
- Cache scope: same-origin `/interface/*` and `/static/*` assets (GET only).
- Navigation: `/interface` and `/interface/<conversation_id>` are **NetworkFirst** with offline fallback.
- APIs, streaming, uploads, and downloads are **NetworkOnly** by design.

**PWA icon precache**
- Icons are precached to prevent repeated icon fetches:
  - `/interface/icons/app-icon.svg`
  - `/interface/icons/maskable-icon.svg`

**Server cache headers (PWA assets)**
- The manifest + icons are served with long-lived cache headers to avoid repeated fetches.

---

## Local conversation storage (important for parity + ops)

Conversations are persisted to the filesystem (not only SQLite):

- Directory layout (conceptual):
  - `<conversation_folder>/<conversation_id>/`
    - `<conversation_id>.index` (serialized conversation object)
    - `<conversation_id>-messages.json` (messages cached to JSON)
    - `<conversation_id>-memory.json` (memory cached to JSON)
    - `uploaded_documents/` (DocIndex artifacts)
  - A separate shared `locks/` directory is used for `FileLock` locks.

This design supports fast local reads, incremental field updates (messages/memory),
and avoids loading everything for every request.

---

## Chrome Extension (Sidepanel Client)

The Chrome extension provides an AI assistant sidepanel integrated into the browser. It connects to the **same unified backend** (`server.py`, port 5000) as the web UI, using the full `Conversation.py` pipeline. JWT authentication, real-time streaming, workspace-aware. Built with vanilla JS, jQuery (jsTree), and KaTeX (math rendering).

**Documentation**: `documentation/features/extension/extension_design_overview.md` (architecture + conversation flow), `extension_implementation.md` (file-by-file reference), `extension_api.md` (endpoint reference).

### Extension-specific capabilities

| Capability | Details |
|-----------|---------|
| **Sidepanel Chat** | Full-height sidepanel with message streaming, markdown (marked.js), syntax highlighting (highlight.js), KaTeX math rendering. Same conversation pipeline as web UI (PKB, agents, TLDR, math formatting). |
| **Page Context Grounding** | "Include page" button extracts current tab content (site-specific extractors for 16 apps: Google Docs, Gmail, Sheets, Twitter/X, Reddit, GitHub, YouTube, Wikipedia, Stack Overflow, LinkedIn, Medium/Substack, Notion, Quip, Overleaf, Confluence, Slack). Content injected as grounding messages in LLM prompt (64K char limit single page, 128K multi-tab). |
| **Multi-Tab Scroll Capture** | Capture content from other tabs using scroll+screenshot+OCR. 4 per-tab capture modes: Auto, DOM, OCR, Full OCR. Auto-detects document apps via URL patterns. Deferred OCR with immediate tab restoration. On-page toast overlays during capture. |
| **Screenshots + OCR** | Viewport screenshots, full-page scrolling screenshots. Vision-LLM OCR (gemini-2.5-flash-lite, 8 workers). Inner scroll container auto-detection for web apps with fixed shells (Office Word Online, Google Docs, Notion, etc.). Pipelined OCR (40-60% faster than batch). |
| **Voice Input** | MediaRecorder + `/transcribe` endpoint. Recording state UI indicator. |
| **Workspace Sidebar** | jsTree-based hierarchical workspace tree matching main UI. Workspace folders with color indicators. Expand/collapse. Domain switching (assistant/search/finchat). "Browser Extension" workspace auto-created per domain. |
| **Conversation Management** | "New Chat" (permanent) + "Quick Chat" (temporary) buttons. 8-item right-click context menu: Copy Reference, Open in New Window, Clone, Toggle Stateless, Set Flag (7 colors), Move to Workspace, Save, Delete. |
| **File Attachments** | Drag-and-drop PDF/images anywhere on sidepanel. FastDocIndex upload (BM25, 1-3s). Preview thumbnails (images) and styled badges (PDFs) above input. Persistent rendering in sent messages. |
| **Document Management Panel** | Overlay panel with two collapsible sections: conversation docs + global docs. Upload, download, remove operations. Accessible via toolbar button. |
| **PKB Claims Panel** | Read-only overlay panel with debounced text search, type/domain/status filter dropdowns, paginated "Load more". Color-coded claim type badges. |
| **Attachment Context Menu** | Right-click on rendered message attachments: Download, Promote to Conversation Doc, Promote to Global Doc, Delete. |
| **Custom Scripts** | Tampermonkey-like scripts created via chat (LLM sees page structure, iterative refinement) or direct CodeMirror editor. `aiAssistant` API: dom (22 methods), clipboard, llm (ask/stream), ui (toast/modal), storage. Action exposure: floating toolbar, injected DOM buttons, command palette (Ctrl+Shift+K), context menu. Sandboxed execution. |
| **Quick Actions** | Right-click context menu on page text: Explain, Summarize, Translate, etc. Opens modal overlay on page with LLM response. |
| **Settings** | Model, prompt, history length, auto-include page, domain, workspace. Stored in `chrome.storage.local` + synced to server via `/ext/settings`. Configurable backend URL (localhost:5000 vs production). |

### Extension backend endpoints

The extension uses two categories of endpoints:

1. **Main backend endpoints** (shared with web UI) — conversations, workspaces, documents, global docs, claims/PKB, send_message, model catalog, prompts, transcribe. CORS configured for `chrome-extension://*` origin.

2. **Extension-specific endpoints** (`/ext/*` prefix) — auth (login/logout/verify), scripts CRUD (9 endpoints), workflows CRUD (5 endpoints), OCR, settings, chat quick action. Implemented in `endpoints/ext_*.py`.

### Extension architecture constraints

- **Chrome MV3 CSP**: `script-src 'self'` — all libraries bundled locally in `extension/lib/` (jQuery, jsTree, KaTeX, marked.js, highlight.js). No CDN references.
- **IIFE modules**: Panel scripts (DocsPanel, ClaimsPanel) use IIFE pattern loaded as plain `<script>` before ES module `sidepanel.js`. Access API via `window.API` global.
- **Storage**: Auth token + settings in `chrome.storage.local`. Conversations stored server-side via `Conversation.py` filesystem storage (same as web UI).
- **Streaming**: Newline-delimited JSON parsing via `streamJsonLines()` — reads `{"status":"...", "content":"...", "type":"..."}` lines from `/send_message/<id>`.

---

## Android app: what to build (parity checklist)

### Networking and streaming
- Implement a streaming client for `POST /send_message/<conversation_id>`.
  - Parse newline-delimited JSON.
  - Handle partial JSON lines and buffer correctly.
  - Update the UI incrementally.
- Implement streaming for:
  - `POST /clear_doubt/...` (newline-delimited JSON)
  - `POST /temporary_llm_action` (newline-delimited JSON)
- Implement binary streaming for:
  - `POST /tts/...` (audio/mpeg)

### Data model
- Conversation:
  - `conversation_id`, `domain`, `workspace`
  - message list (sender/text/message_id/index)
  - optionally: local caching for offline viewing
- Documents:
  - list + download + delete
  - doc references (`#doc_n`) helper UI
- PKB:
  - list/search claims; CRUD for claims and contexts
  - pin/unpin and "attach to next message"
  - parse `@memory:<id>` and `@friendly_id` references (client-side)
  - `@` autocomplete dropdown for claims, contexts, entities, tags, and domains
  - type-suffixed friendly IDs: claims (no suffix), contexts (`_context`), entities (`_entity`), tags (`_tag`), domains (`_domain`)
  - toggle via `use_pkb` checkbox (default: on)

### UI screens (suggested)
- Login / session
- Workspace list + conversation list
- Chat screen:
  - message stream rendering
  - “status” progress line support
  - attach documents
  - toggle options (web search, memory pad, PKB memory, planner, reward dialer, model selection, preamble)
  - next question suggestions
  - per-message actions: doubt clearing, TTS, edit/delete, show/hide, edit as artefact, save to memory, table of contents
- PKB screen:
  - claims CRUD
  - auto-fill button (LLM extracts type, domain, tags, questions, friendly_id from statement)
  - pinned claims
  - search
  - conflict resolution
- Audio screen/player:
  - play streamed or downloaded mp3
  - allow “podcast mode”

---

## How this differs from ChatGPT (grounded differentiators)

### Explicit “knowledge + retrieval” primitives
- First-class conversation document library with `#doc_n` referencing and doc-aware prompts.
- Optional PKB with:
  - pinned memories,
  - "attach for next message" flows,
  - conversation-pinned claims,
  - hybrid search retrieval,
  - universal `@` references for claims, contexts, entities, tags, and domains (v0.7),
  - type-aware autocomplete across all PKB object types,
  - recursive resolution for contexts and tags (entire subtrees).

### Multi-agent orchestration
- Switchable agents for:
  - deep research / web search,
  - literature review,
  - interview simulation (v1 and v2),
  - code solving and multi-step code reasoning,
  - slide generation,
  - book/table-of-contents generation (ToC/Book agents),
  - “what-if” scenario generation.

### Execution and artifact generation
- Code execution in a persistent environment + automatic embedding of outputs.
- Diagram generation and publishing (Mermaid + Draw.io) with shareable links.

### Accessibility + repurposing
- TTS and podcast conversions (including code-aware variants).
- Transcription endpoint for audio input.

### Strong “workflow” endpoints beyond chat
- Doubt clearing as a dedicated streaming endpoint with DB-backed history.
- Workspaces for organization; shareable chat views.

---

## Sales pitch material (templates)

### 15-second pitch
“It’s a research-grade chat assistant that can **ingest your documents**, **search the web**, and **pull from a personal knowledge base**, then stream answers while producing **artifacts**—code outputs, diagrams, slides, and audio—so teams can go from question → deliverable in one workflow.”

### Persona-based value props
- **Researchers/Students**: doc-grounded answers, literature review agents, summaries, citations-like link surfacing.
- **Engineers**: code execution + generated plots/files, code solving agents, diagram export.
- **Interview prep**: interview simulators, coding interview prompts, code-aware TTS for practice.
- **Knowledge workers**: PKB memory + pinning, workspaces, conversation summaries and “next question” nudges.
- **Accessibility**: TTS/podcast mode for listening-first consumption.

### “Why not just ChatGPT?”
- Built-in **document library + doc referencing** per conversation.
- Built-in **PKB** for structured memory retrieval, pinning, and universal `@` references across claims, contexts, entities, tags, and domains.
- Built-in **execution + artifacts** (plots/files/diagrams) and **streaming** UX for long tasks.
- Built-in **specialized agents** for research, interviews, slides, and more.

---

## Notes / known implementation behaviors (useful for parity)

- Streaming responses are **newline-delimited JSON objects** (not SSE).
- Certain response segments use **HTML/markers** inside `text`:
  - `<answer> ... </answer>`
  - `<slide-presentation> ... </slide-presentation>`
  - TLDR segments wrapped after long answers.
- Cancellations exist for:
  - main response streaming
  - doubt clearing streaming
- Conversation locking uses filesystem lock files; clients may see "waiting for lock" warnings in stream.

---

## File Browser & Editor
Full-screen modal file browser and code editor accessible from the chat-settings-modal **Actions** tab. Intended for server-side file management without leaving the chat interface.

**Entry point**: Settings → Actions tab → **File Browser** button.
**What it does**
 Displays a VS Code-like file tree of the server's working directory (lazy-loaded, depth-first expansion).
 Opens files in a CodeMirror 5 editor with syntax highlighting (Python, JS, TS, CSS, HTML, XML, Markdown, JSON).
 For `.md` / `.markdown` files: a **Raw / Preview / WYSIWYG** view-mode selector appears above the editor. WYSIWYG embeds EasyMDE inline; CodeMirror is the source of truth and is synced before every save.
 For `.pdf` files: renders inline using the bundled PDF.js viewer with a scoped download-progress bar. No download prompt.
 Address bar with fuzzy autocomplete dropdown — substring + sequential character matching with filename-priority scoring and highlighted matches.
 Right-click context menu and sidebar buttons: **New File**, **New Folder**, **Rename**, **Move to…**, **Delete**.
 **Drag-and-drop move**: drag any tree item onto a folder to move it. Dropping onto the tree background (outside any folder item) moves the item to the **root directory**. Drop targets highlight with a dashed blue outline; the tree background highlights with a dashed blue outline + faint tint (`.fb-drag-over-root`) when hovering over root. Prevents moving a folder into itself or its own descendant.
 **Context-menu move**: right-click → "Move to…" opens `#file-browser-move-modal` (z-index 100004) with a lazy-expanding folder-only tree. A **/ (root)** item is pinned at the top of the tree so items can be moved to the root directory. Move Here button enables once a destination is selected.
 **Decoupled move backend**: move is routed through `_config.onMove(src, dest, done)`. Default calls `POST /file-browser/move`. Override at `FileBrowserManager.init({onMove: fn})` or `.configure({onMove: fn})` for embedding in other contexts (e.g. the Global Docs Folder view uses `onMove` to call `POST /doc_folders/<id>/assign`).
 In-modal confirm and naming dialogs (replaces native `confirm()` / `prompt()` which are blocked behind z-index:100000).
 **Ctrl+S / Cmd+S** saves the current file; **Escape** closes the modal (with dirty-check confirmation). **Cmd+K / Ctrl+K** opens AI Edit overlay.
 **AI Edit (Cmd+K)**: LLM-assisted inline editing — selection or whole file, unified diff preview, Accept / Reject / Edit Instruction flow, conversation context injection.
 **Reload from Disk**, **Word Wrap** toggle, **Download**, and drag-and-drop **Upload** (XHR progress bar) toolbar buttons.
 Binary files detected (null-byte scan in first 8 KB) and shown with informational message. Files over 2 MB blocked with a **Load Anyway** override.
 Theme picker: Monokai (default) / Default light.
**API** (`endpoints/file_browser.py`, all `@login_required`)
 `GET /file-browser/tree?path=.` — list directory (dirs first, sorted)
 `GET /file-browser/read?path=...&force=true` — read file content
 `POST /file-browser/write` — write file `{path, content}`
 `POST /file-browser/mkdir` — create directory `{path}`
 `POST /file-browser/rename` — rename/move `{old_path, new_path}`
 `POST /file-browser/move` — move file/directory `{src_path, dest_path}` (full new path). 409 if dest exists, 400 if moving folder into itself. Reuses `os.rename()` + `_safe_resolve()` pattern.
 `POST /file-browser/delete` — delete file/dir `{path, recursive}`
 `GET /file-browser/download?path=...` — download file as attachment
 `POST /file-browser/upload` — upload file (multipart, with overwrite flag)
 `GET /file-browser/serve?path=...` — serve file inline (used by PDF.js viewer; MIME auto-detected)
 `POST /file-browser/ai-edit` — LLM-assisted edit `{path, instruction, selection?, conversation_id?}`

**Security**: all paths validated via `os.path.realpath()` + `startswith(SERVER_ROOT)` — cannot escape the server root.

**Modal architecture**: The modal is a plain `position: fixed` `<div>` (not a Bootstrap `.modal`). Opened/closed with raw DOM manipulation to avoid Bootstrap JS stacking conflicts when the settings modal is already open. No backdrop. View switching (`editor / preview / wysiwyg / pdf / empty-state`) uses vanilla `element.style.display` (not jQuery `.show()/.hide()`) to avoid Bootstrap `!important` utility class conflicts.
**Key files**: `endpoints/file_browser.py`, `interface/file-browser-manager.js`
**Docs**: `documentation/features/file_browser/README.md`

**Pluggable Config API**: `FileBrowserManager` exposes a 7-group config schema allowing full customization for different embedding contexts — endpoints, DOM IDs, behavior flags (read-only, allowUpload, allowDelete, showEditor, etc.), root path, CRUD operation callbacks (`onMove`, `onDelete`, `onRename`, `onCreateFolder`, `onCreateFile`, `onSave`), lifecycle events (`onOpen`, `onClose`, `onSelect`), and custom rendering hooks (`enrichEntry`, `renderEntry`, `buildContextMenu`). Used by the Global Docs Folder view to embed the file browser as a folder-only organizer. `FileBrowserManager.init([cfg])` / `.configure(cfg)` — both use `$.extend(true, ...)` deep merge so partial overrides are safe.

---

## Operations and deployment

For running, restarting, and maintaining the server infrastructure behind these capabilities:

- **[Server Restart Guide](../ops/server_restart_guide.md)** — 3 screen sessions (science-reader, opencode_server, extension_server), JWT extraction, deferred restart pattern, full stack restart sequence
- **[MCP Server Setup](../ops/mcp_server_setup.md)** — 8 MCP servers (37 tools), JWT auth, token generation, OpenCode/Claude Code config, Jina timeout tuning, nginx
- **[LLM Model Management](../ops/llm_model_management.md)** — model configuration and provider setup
- **[Legacy Server Runbook](../ops/server_ops_and_runbook.md)** — original deployment notes (nginx, SSL, Docker, vLLM)

---

## Removed features

### Dark mode toggle (darkmode-js)

**Removed from**: `interface/interface.html`, `interface/shared.html`

Previously the app loaded `darkmode-js@1.5.7` from CDN and called `new Darkmode({...}).showWidget()` on page load. This injected a floating toggle button that applied a full-page `mix-blend-mode: difference` CSS overlay to invert colors.

**Why it was removed**: `mix-blend-mode: difference` is a blunt color inversion that does not work for complex dynamic apps. Specific failures in this app:

- **Bootstrap components**: Hardcoded color values (`#007bff`, `#28a745`, etc.) invert to unpredictable colors. Blue buttons become orange, green badges become magenta.
- **Stacking context conflicts**: Elements with `z-index`, `position: fixed/sticky`, `transform`, or `opacity < 1` create stacking contexts. The darkmode overlay sits at one z-level -- elements above it are not inverted, elements below are. The app has many such elements: modals, dropdowns, vakata context menus (`z-index: 99999`), the scroll-to-bottom button, the fixed chat input area. Result: inconsistent partial inversion.
- **Dynamic content**: The overlay is static. Streamed chat messages, jsTree sidebar nodes, dynamically created modals, and toasts may or may not be affected depending on their stacking context.
- **Form controls**: `<input>`, `<textarea>`, `<select>` have browser-native rendering that interacts unpredictably with `mix-blend-mode`. Bootstrap styling on these adds another layer of specificity conflicts.
- **Rich rendered content**: MathJax equations, syntax-highlighted code blocks, and images all have explicit colors that invert to unreadable results.

`darkmode-js` is designed for simple static pages (marketing sites, blogs, documentation) with mostly black-on-white text. It is not suitable for full-page apps with complex z-index stacks, dynamic DOM, and styled UI components.

**What would work instead**: A proper CSS custom properties theme system (`var(--bg-primary)`, `var(--text-primary)`, etc.) where a dark palette is defined and swapped via a class on `<body>`. This requires every color in every component to go through CSS variables -- a significant effort not currently planned.
