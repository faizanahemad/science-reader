## External API implementation notes (developer-facing)

This file is **developer-facing**: how the API is structured internally, how the
server is composed, and where state/DB/session concerns live.

### File/module hierarchy (high level)

The HTTP API is split into one Flask Blueprint per logical domain:

- `endpoints/auth.py`: login/session helpers and auth routes
- `endpoints/conversations.py`: conversations, messages, streaming chat, cancellations
- `endpoints/documents.py`: upload/list/download/delete conversation documents
- `endpoints/doubts.py`: doubt-clearing + temporary LLM action (streaming)
- `endpoints/audio.py`: TTS + transcription
- `endpoints/workspaces.py`: workspace CRUD + move conversation
- `endpoints/users.py`: user preference/memory storage
- `endpoints/sections.py`: section hidden-details storage
- `endpoints/prompts.py`: prompt CRUD
- `endpoints/pkb.py`: Personal Knowledge Base API (`/pkb/*`) + plan execution
- `endpoints/static_routes.py`: UI/static assets, session/lock utilities, proxy routes
- `endpoints/code_runner.py`: one-off code execution

Shared helpers:

- `endpoints/__init__.py`: `register_blueprints(app)` (central registry)
- `endpoints/state.py`: `AppState` + `init_state()` + `get_state()`
- `endpoints/session_utils.py`: `get_session_identity()` (email/name/loggedin)
- `endpoints/request_context.py`: convenience helpers to load state + keys + conversations
- `endpoints/utils.py`: shared endpoint utilities (e.g., key parsing / key attachment)
- `endpoints/responses.py`: standardized JSON error responses (`json_error`)

### App composition

- The entry point is `server.py` (app factory).
- `server.create_app(argv=None)`:
  - parses CLI flags/config
  - initializes Flask and extensions (CORS, cache, limiter, sessions, etc.)
  - calls `init_state(...)` to build `AppState`
  - calls DB schema initialization (`database.connection.create_tables(...)`)
  - calls `endpoints.register_blueprints(app)`

Blueprint registration order is defined in `endpoints/__init__.py` and is
important for any `before_app_request` hooks (auth first).

### Shared application state (`AppState`)

`endpoints/state.py` centralizes cross-endpoint state to avoid circular imports
and “module globals” drifting over time.

`AppState` typically holds:
- **Filesystem dirs**: `users_dir`, `conversation_folder`, `pdfs_dir`, `locks_dir`, etc.
- **Caches**: `conversation_cache` (conversation objects loaded on demand)
- **In-memory registries**: PKB pinned claims store, cancellation registries, etc.
- **Optional extension refs** (if needed): cache / limiter handles

Endpoints access state via `get_state()`.

### Session/auth model

- Auth uses a **cookie-based session**; user identity is read from `flask.session`.
- Most protected routes are decorated with `@login_required` from `endpoints/auth.py`.
- `get_session_identity()` returns `(email, name, loggedin)` using the session.
- Some routes are intentionally public-ish:
  - share endpoints like `/shared_chat/<conversation_id>` (see `static_routes.py` + `conversations.py`)
  - salted download route `/get_conversation_output_docs/<SALT>/...`

### Rate limiting

- Rate limiting is handled via `Flask-Limiter`.
- Endpoint modules import and use the shared limiter singleton (see `extensions.py`)
  so decorators can be applied without importing `server.py`.

### Standardized error responses

Most endpoint modules use `endpoints.responses.json_error(message, status=..., code=..., **extra)`.

Canonical shape:

```json
{
  "status": "error",
  "error": "Human-readable message",
  "message": "Human-readable message",
  "code": "optional_machine_code"
}
```

Important compatibility rule:
- We **do not** wrap successful list responses; arrays stay arrays to avoid UI/client breakage.

### API key handling (LLM keys)

Several endpoints need API keys (OpenAI/etc.) stored in-session.

Patterns:
- `endpoints.utils.keyParser(session)` extracts keys from the session.
- `endpoints.request_context.get_state_and_keys()` returns `(state, keys)`.
- `endpoints.request_context.attach_keys(obj, keys)` attaches keys to conversation/doc objects.
- `endpoints.request_context.get_conversation_with_keys(state, conversation_id=..., keys=...)` loads a cached conversation and attaches keys.

### Database layout & access

This repo uses SQLite for persistence.

Core DB:
- Stored under `AppState.users_dir` (typically `.../users/`).
- Main DB file: `users.db` (schema created by `database/connection.py:create_tables`)

DB modules (moved out of `server.py`):
- `database/connection.py`: connection + schema creation helpers
- `database/workspaces.py`: workspace tables + queries
- `database/conversations.py`: conversation tables + queries
- `database/doubts.py`: doubt tables + queries
- `database/users.py`: user details/preferences tables + queries
- `database/sections.py`: section hidden-details tables + queries

PKB DB:
- `endpoints/pkb.py` uses a separate sqlite file: `pkb.sqlite` under `AppState.users_dir`
- It depends on optional `truth_management_system` and returns **503** if unavailable.

### Streaming endpoints (implementation detail)

Some endpoints stream responses for UX:
- `/send_message/<conversation_id>`: uses a background task (`very_common.get_async_future`) and a queue to stream incremental output.
- `/clear_doubt/...` and `/temporary_llm_action`: stream newline-delimited JSON chunks over `text/plain`.
- `/tts/...`: can stream `audio/mpeg`.

Clients should treat these responses as streams (not a single JSON object).

---

## Recent additions: pre-send clarifications + post-send auto-takeaways

These live in `endpoints/conversations.py` and are intentionally implemented as:
- **Fail-open** (never blocks chat)
- **Non-blocking** (runs after streaming completes)
- **DB-compatible** (reuses existing `database/doubts.py` helpers; no schema migration)

### `POST /clarify_intent/<conversation_id>` (clarifications)

Implementation notes:
- **Auth + rate limit**: `@login_required` + `@limiter.limit(...)` (same pattern as other conversation endpoints).
- **Conversation context**:
  - Loads the `Conversation` via `get_conversation_with_keys(...)`.
  - Includes bounded context in the prompt (conversation running summary + last user+assistant turn) to avoid redundant clarifiers.
- **LLM**:
  - Uses `CallLLm(..., model_name=VERY_CHEAP_LLM[0])`.
  - Forces **strict JSON** output and parses it with a best-effort extractor so the endpoint can remain fail-open.
- **Schema normalization**:
  - The server clamps output to **0–3** questions and **2–5** options per question and returns a stable UI-friendly schema.

### Auto-doubt: “Auto takeaways” after `POST /send_message/<conversation_id>`

Goal:
- After streaming is complete, generate and persist a short quick-reference version of the assistant answer as a **root doubt**:
  - `doubt_text == "Auto takeaways"` (used for dedup)
  - `doubt_answer ==` generated takeaways

How it is triggered:
- In `send_message()` → `generate_response()`, after `response_queue.put("<--END-->")` and `conversation.clear_cancellation()`.
- Guarded by `checkboxes.persist_or_not` (if disabled, we skip auto-takeaways).

How it is made fast:
- The server **captures the assistant `response_message_id` and the final answer text from the streamed JSON-lines** emitted by `Conversation.__call__` (which yields `json.dumps(dict) + "\\n"`).
- This avoids waiting for `Conversation.persist_current_turn()` (which can be slow because it performs additional async LLM work like summaries/suggestions).

Fallback behavior:
- If `response_message_id` or answer text cannot be captured from the stream, we fall back to polling `conversation.get_field("messages")` for a bounded time window.

Persistence + dedup:
- Uses `database.doubts.get_doubts_for_message(...)` to check whether a root doubt with `doubt_text == "Auto takeaways"` already exists for that `(conversation_id, message_id)`.
- If none exists, inserts via `database.doubts.add_doubt(...)` with `parent_doubt_id=None`.

### How to add a new API endpoint

1. Choose the correct module (or create a new blueprint file if it’s a new domain).
2. Add the `@<blueprint>.route(...)` handler with `@login_required` + `@limiter.limit(...)` as appropriate.
3. Use `get_state()` and the helpers in `request_context.py` for consistent state/key loading.
4. For errors, prefer `json_error(...)` with a stable machine `code`.
5. Register the blueprint in `endpoints/__init__.py` (if new).
6. Validate route registration by creating the app and dumping `app.url_map`.


