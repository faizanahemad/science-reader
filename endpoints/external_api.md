## External API (HTTP) — overview

This file is a **consumer-facing** reference for the Flask server API exported by this repo.
It’s intentionally brief: endpoint purpose + request/response shape “at a glance”.

### Base conventions

- **Base URL**: your running Flask server (e.g. `http://localhost:<port>`).
- **Auth/session**:
  - Most endpoints require a valid session (see **Auth**).
  - Some “shared” endpoints are public (no login).
- **Rate limiting**: most routes are protected by `Flask-Limiter`.
- **Error responses (standardized)**:
  - Most JSON error responses return the canonical shape:

```json
{
  "status": "error",
  "error": "Human-readable message",
  "message": "Human-readable message",
  "code": "machine_code_optional",
  "...": "optional extra fields"
}
```

- **Streaming endpoints**:
  - Some endpoints respond with `Content-Type: text/plain` and stream newline-delimited text/JSON chunks.

### Auth / session

#### `GET, POST /login`
- **Purpose**: create a logged-in session (credentials/flow depend on deployment).
- **Response**: sets session cookies; response may vary by auth mode.

#### `GET /logout`
- **Purpose**: clear login session.
- **Response (JSON)**: `{ "message": "..." }` or a redirect depending on mode.

#### `GET /get_user_info`
- **Purpose**: return currently logged-in user identity info.
- **Response (JSON)**: user info object.

---

## Conversations & messaging (`endpoints/conversations.py`)

#### `GET /list_conversation_by_user/<domain>`
- **Purpose**: list conversation metadata for a user within a domain.
- **Response (JSON)**: list of conversation metadata objects (sorted).

#### `POST /create_conversation/<domain>/` and `POST /create_conversation/<domain>/<workspace_id>`
- **Purpose**: create a new conversation (optionally inside a workspace).
- **Response (JSON)**: conversation metadata object (includes `workspace` field).

#### `GET /list_messages_by_conversation/<conversation_id>`
- **Purpose**: return conversation messages.
- **Response (JSON)**: array of message objects.

#### `GET /list_messages_by_conversation_shareable/<conversation_id>`
- **Purpose**: shareable message list (public-ish flow).
- **Response (JSON)**: `{ "messages": [...], "docs": [...] }`

#### `GET /get_conversation_history/<conversation_id>`
- **Purpose**: return a human-readable conversation history/summary text.
- **Query params**: `query` (optional).
- **Response (JSON)**: `{ "conversation_id": "...", "history": "...", "timestamp": <float> }`

#### `GET /get_conversation_details/<conversation_id>`
- **Purpose**: conversation metadata including workspace association.
- **Response (JSON)**: conversation metadata object with `workspace`.

#### `POST /send_message/<conversation_id>` (streaming)
- **Purpose**: stream assistant response for the provided user query payload.
- **Request (JSON)**: “legacy” chat payload (varies; forwarded into `Conversation.__call__`).
- **Response (text/plain)**: streamed chunks (ends with an internal end marker).

#### Conversation editing / state
- `POST /edit_message_from_conversation/<conversation_id>/<message_id>/<index>`
- `POST /move_messages_up_or_down/<conversation_id>`: body `{ "message_ids": [...], "direction": "up"|"down" }`
- `POST /show_hide_message_from_conversation/<conversation_id>/<message_id>/<index>`: body `{ "show_hide": ... }`
- `DELETE /delete_message_from_conversation/<conversation_id>/<message_id>/<index>`
- `DELETE /delete_last_message/<conversation_id>`
- `DELETE /delete_conversation/<conversation_id>`
- `POST /clone_conversation/<conversation_id>`
- `PUT /make_conversation_stateful/<conversation_id>`
- `DELETE /make_conversation_stateless/<conversation_id>`

**Responses**: JSON objects with `message` and/or metadata.

#### Memory pad
- `POST /set_memory_pad/<conversation_id>`: body `{ "text": "..." }`
- `GET /fetch_memory_pad/<conversation_id>`: response `{ "text": "..." }`

#### Flags
- `POST /set_flag/<conversation_id>/<flag>`

#### Suggestions
- `GET /get_next_question_suggestions/<conversation_id>`: response `{ "suggestions": [...] }`

#### Cancellation endpoints
- `POST /cancel_response/<conversation_id>`
- `POST /cleanup_cancellations`
- `POST /cancel_coding_hint/<conversation_id>`
- `POST /cancel_coding_solution/<conversation_id>`
- `POST /cancel_doubt_clearing/<conversation_id>`

#### Output docs download (public-ish)
- `GET /get_conversation_output_docs/<SALT>/<conversation_id>/<document_file_name>`
- **Response**: file download (or JSON error).

#### Shared viewing (public-ish)
- `GET /shared_chat/<conversation_id>`: response `{ "messages": [...], "documents": [...], "metadata": {...} }`

---

## Documents (`endpoints/documents.py`)

#### `POST /upload_doc_to_conversation/<conversation_id>`
- **Purpose**: attach/upload a document to a conversation.
- **Request**:
  - multipart: `pdf_file`, or
  - JSON: `{ "pdf_url": "..." }`
- **Response (JSON)**: `{ "status": "Indexing started" }`

#### `GET /list_documents_by_conversation/<conversation_id>`
- **Response (JSON)**: array of document short-info objects.

#### `GET /download_doc_from_conversation/<conversation_id>/<doc_id>`
- **Response**: file download or redirect to source URL.

#### `DELETE /delete_document_from_conversation/<conversation_id>/<document_id>`
- **Response (JSON)**: `{ "status": "Document deleted" }`

---

## Doubts + temporary LLM (`endpoints/doubts.py`)

#### `POST /clear_doubt/<conversation_id>/<message_id>` (streaming)
- **Purpose**: stream a “doubt clearing” response and persist it in DB.
- **Request (JSON)**:
  - `doubt_text` (optional)
  - `parent_doubt_id` (optional)
  - `reward_level` (optional int)
- **Response (text/plain)**: newline-delimited JSON chunks including `status`, `text`, and final `doubt_id`.

#### `GET /get_doubt/<doubt_id>`
- **Response (JSON)**: `{ "success": true, "doubt": {...} }`

#### `DELETE /delete_doubt/<doubt_id>`
- **Response (JSON)**: `{ "success": true, "message": "..." }` (or error).

#### `GET /get_doubts/<conversation_id>/<message_id>`
- **Response (JSON)**: `{ "success": true, "doubts": [...], "count": <int> }`

#### `POST /temporary_llm_action` (streaming)
- **Purpose**: run an ephemeral LLM action, optionally with conversation context.
- **Request (JSON)**: fields like `action_type`, `selected_text`, `user_message`, `conversation_id`, `history`, `with_context`, etc.
- **Response (text/plain)**: newline-delimited JSON chunks.

---

## Audio (TTS + transcription) (`endpoints/audio.py`)

#### `POST /tts/<conversation_id>/<message_id>`
- **Purpose**: text-to-speech audio generation (streaming or file response).
- **Request (JSON)**: `text`, `streaming` (bool), `recompute`, `message_index`, `shortTTS`, `podcastTTS`
- **Response**:
  - streaming: `audio/mpeg` stream
  - non-streaming: `audio/mpeg` file

#### `POST /is_tts_done/<conversation_id>/<message_id>`
- **Response (JSON)**: `{ "is_done": true }`

#### `POST /transcribe`
- **Request**: multipart form with `audio` file.
- **Response (JSON)**: `{ "transcription": "..." }`

---

## Workspaces (`endpoints/workspaces.py`)

#### `POST /create_workspace/<domain>/<workspace_name>`
- **Request (JSON)** (optional): `{ "workspace_color": "..." }`
- **Response (JSON)**: `{ "workspace_id": "...", "workspace_name": "...", "workspace_color": "..." }`

#### `GET /list_workspaces/<domain>`
- **Response (JSON)**: array of workspace objects.

#### `PUT /update_workspace/<workspace_id>`
- **Request (JSON)**: any of `workspace_name`, `workspace_color`, `expanded`
- **Response (JSON)**: `{ "message": "Workspace updated successfully" }`

#### `POST /collapse_workspaces`
- **Request (JSON)**: `{ "workspace_ids": [...] }`
- **Response (JSON)**: `{ "message": "Workspaces collapsed successfully" }`

#### `DELETE /delete_workspace/<domain>/<workspace_id>`
- **Response (JSON)**: `{ "message": "Workspace deleted and conversations moved to default workspace." }`

#### `PUT /move_conversation_to_workspace/<conversation_id>`
- **Request (JSON)**: `{ "workspace_id": "..." }`
- **Response (JSON)**: `{ "message": "..." }`

---

## User details/preferences (`endpoints/users.py`)

#### `GET /get_user_detail`
- **Response (JSON)**: `{ "text": "..." }` (user memory)

#### `GET /get_user_preference`
- **Response (JSON)**: `{ "text": "..." }` (user preferences)

#### `POST /modify_user_detail`
- **Request (JSON)**: `{ "text": "..." }`
- **Response (JSON)**: `{ "message": "User details updated successfully" }`

#### `POST /modify_user_preference`
- **Request (JSON)**: `{ "text": "..." }`
- **Response (JSON)**: `{ "message": "User preferences updated successfully" }`

---

## Sections (hidden-details) (`endpoints/sections.py`)

#### `GET /get_section_hidden_details`
- **Query params**:
  - `conversation_id`
  - `section_ids` (comma-separated)
- **Response (JSON)**: `{ "section_details": {...} }`

#### `POST /update_section_hidden_details`
- **Request (JSON)**:
  - `conversation_id`
  - `section_details`: `{ "<section_id>": { "hidden": true|false }, ... }`
- **Response (JSON)**: `{ "status": "success", "message": "...", "updated_sections": {...}, "conversation_id": "..." }`

---

## Prompts (`endpoints/prompts.py`)

#### `GET /get_prompts`
- **Response (JSON)**: `{ "status": "success", "prompts": [...], "prompts_detailed": [...], "count": <int> }`

#### `GET /get_prompt_by_name/<prompt_name>`
- **Response (JSON)**: `{ "status": "success", "name": "...", "content": "...", "metadata": {...} }`

#### `POST /create_prompt`
- **Request (JSON)**: `{ "name": "...", "content": "...", "description"?, "category"?, "tags"? }`
- **Response (JSON)**: `{ "status": "success", "message": "...", "name": "...", "content": "..." }`

#### `PUT /update_prompt`
- **Request (JSON)**: `{ "name": "...", "content": "...", "description"?, "category"?, "tags"? }`
- **Response (JSON)**: `{ "status": "success", "message": "...", "name": "...", "new_content": "..." }`

---

## Personal Knowledge Base (PKB) (`endpoints/pkb.py`)

> All `/pkb/*` routes return **503** when PKB is not available.

#### Claims
- `GET /pkb/claims` (list)
- `POST /pkb/claims` (create)
- `POST /pkb/claims/bulk` (bulk create)
- `GET /pkb/claims/<claim_id>`
- `PUT /pkb/claims/<claim_id>`
- `DELETE /pkb/claims/<claim_id>`

#### Pinning
- `POST /pkb/claims/<claim_id>/pin`
- `GET /pkb/pinned`
- `POST /pkb/conversation/<conv_id>/pin`
- `GET /pkb/conversation/<conv_id>/pinned`
- `DELETE /pkb/conversation/<conv_id>/pinned`

#### Search / entities / tags / conflicts
- `POST /pkb/search`
- `GET /pkb/entities`
- `GET /pkb/tags`
- `GET /pkb/conflicts`
- `POST /pkb/conflicts/<conflict_id>/resolve`

#### Memory update & ingestion plans
- `POST /pkb/propose_updates`
- `POST /pkb/ingest_text`
- `POST /pkb/execute_ingest`
- `POST /pkb/execute_updates`

#### Conversation integration
- `POST /pkb/relevant_context`

Responses are JSON objects; shapes vary per endpoint (claims, entities, tags, conflicts, etc.).

---

## Static / interface / proxy (`endpoints/static_routes.py`)

- `GET /interface` and `GET /interface/<path:path>`: serve the UI.
- `GET /static/<path:filename>`: serve static files.
- `GET /favicon.ico`, `GET /loader.gif`
- Session/lock utilities:
  - `GET /clear_session`, `GET /clear_locks`, `GET /get_lock_status/<conversation_id>`
  - `POST /ensure_locks_cleared/<conversation_id>`, `POST /force_clear_locks/<conversation_id>`
- Sharing:
  - `GET /shared/<conversation_id>`
- Proxy:
  - `GET /proxy`, `GET /proxy_shared`

---

## Code runner (`endpoints/code_runner.py`)

#### `POST /run_code_once`
- **Purpose**: execute code once (implementation-defined sandboxing).
- **Request/Response**: JSON (see implementation doc for details).


