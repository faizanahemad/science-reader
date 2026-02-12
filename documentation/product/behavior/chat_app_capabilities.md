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
- Attach documents to a conversation by:
  - uploading a file (PDF, etc.)
  - providing a URL
- Retrieve documents by referencing `#doc_<n>` in the user message.
- Supports both:
  - “readable docs” (PDFs, HTML, images, small local files)
  - “data docs” (CSV/TSV/XLSX/Parquet/JSON) with preview injection into prompts
- Produces `doc_infos` that maps doc index references to titles/sources.

**API**
- `POST /upload_doc_to_conversation/<conversation_id>`
- `GET /list_documents_by_conversation/<conversation_id>`
- `GET /download_doc_from_conversation/<conversation_id>/<doc_id>`
- `DELETE /delete_document_from_conversation/<conversation_id>/<document_id>`

**User message conventions**
- Reference doc N: `#doc_1`, `#doc_2`, ...
- Reference all docs: `#doc_all` / `#all_docs` / similar aliases exist.
- There are also “summary doc” directives in message text (e.g. `#summary_doc_...`) used for forced summary workflows.

**Persistence**
- Conversation folder contains `uploaded_documents/` which stores `DocIndex` artifacts.
- The conversation’s field `uploaded_documents_list` stores tuples `(doc_id, doc_storage_path, pdf_url)` persisted in conversation storage.

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
- **New Temporary Chat button**: The `#new-temp-chat` button in the top-right chat bar creates a fresh conversation in the default workspace and immediately marks it stateless — a one-click way to start an ephemeral chat. Uses `statelessConversation(convId, suppressModal=true)` to skip the confirmation modal.
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
