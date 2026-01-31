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

### Workspaces

Conversations can be organized into **workspaces** per user and domain:
- create/update/delete workspaces
- move conversations between workspaces
- default workspace auto-created per `(user, domain)`

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
  "checkboxes": { "...": "various options" },
  "links": ["optional url list"],
  "search": ["optional search query list"],
  "attached_claim_ids": ["optional PKB claim ids"],
  "referenced_claim_ids": ["optional PKB claim ids extracted from @memory:<id> refs"]
}
```

Server-side injection:
- `conversation_pinned_claim_ids` is injected by the server (from per-conversation pinned claims state).

**Streaming response shape**
- Each line is `json.dumps({ "text": "...", "status": "..." }) + "\n"` (plus additional keys sometimes).
- The client should:
  - split by newline,
  - parse each JSON object,
  - append `text` to the assistant message,
  - optionally show `status` as progress UI.

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

### 6) PKB (Personal Knowledge Base) integration

**What it does**
- Retrieves relevant “claims” as context for the current query.
- Combines multiple sources with explicit prioritization:
  1. referenced claims (e.g. `@memory:<id>` references)
  2. attached claims (“use in next message” selection)
  3. globally pinned claims
  4. conversation-pinned claims
  5. auto-retrieved via hybrid search

**APIs**
- PKB management and retrieval:
  - `GET/POST/PUT/DELETE /pkb/claims[...]`
  - `POST /pkb/search`
  - `POST /pkb/relevant_context`
  - pinning endpoints (`/pkb/*/pin`, `/pkb/pinned`, conversation pinning routes)
- Main chat uses PKB context automatically if available (part of `send_message` execution).

**Persistence**
- PKB uses a separate sqlite DB: `pkb.sqlite` under `users_dir`.
- Conversation-level pinned claims are tracked server-side (in app state) and injected into chat requests.

**Differentiator**
- This is a major capability gap vs “plain ChatGPT chat”: it supports an internal, queryable memory store with explicit attachment and pinning flows.

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
  - list/search claims
  - pin/unpin and “attach to next message”
  - parse `@memory:<id>` references (client-side)

### UI screens (suggested)
- Login / session
- Workspace list + conversation list
- Chat screen:
  - message stream rendering
  - “status” progress line support
  - attach documents
  - toggle options (web search, memory pad, planner, reward dialer, model selection, preamble)
  - next question suggestions
  - per-message actions: doubt clearing, TTS, edit/delete, show/hide
- PKB screen:
  - claims CRUD
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
  - “attach for next message” flows,
  - conversation-pinned claims,
  - hybrid search retrieval.

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
- Built-in **PKB** for structured memory retrieval and pinning.
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
- Conversation locking uses filesystem lock files; clients may see “waiting for lock” warnings in stream.


