# API Data Caching via Entity Version Counters

## Motivation & Background

Every user action that navigates between conversations fires 7+ parallel GET requests that re-fetch full JSON payloads from the server — even when nothing has changed. Switching to a previously-viewed conversation re-downloads the entire message list, doubts map, pinned messages, documents, settings, memory pad, and conversation details every time. The server queries SQLite, serializes potentially hundreds of messages into JSON, and transfers it all over the wire — only for the client to parse, re-render, and discard its previous identical copy.

There is no data caching layer. The Service Worker caches static assets (JS/CSS/images) but explicitly skips all JSON API responses (`NetworkOnly`). The client's only "cache" is an IndexedDB DOM snapshot of the rendered conversation HTML (`rendered-state-manager.js`), which avoids re-rendering but still re-fetches all data to verify freshness.

### The core problem

Every GET request does full work on the server (DB query + JSON serialization + transfer) regardless of whether the data changed since the client last fetched it. On a typical session with 10 conversation switches, that's 70+ redundant full-payload API responses.

### What we want

- **Returning to a conversation**: If nothing changed, the server responds with `304 Not Modified` (empty body, ~200 bytes). No DB query, no JSON serialization, no payload transfer.
- **Cross-device freshness**: If another device modified data, the stale device automatically gets fresh data on its next request — no polling, no push channel, no client-side invalidation logic.
- **Transparent to calling code**: Existing JS call sites (`$.get`, `$.ajax`, `fetch`) require minimal changes. The caching logic lives in a single wrapper function.
- **Per-entity granularity**: Editing the memory pad doesn't invalidate the messages cache. Only the specific entity scope that changed triggers a re-fetch.

### What we are NOT doing

- No real-time push (SSE/WebSocket for live sync across devices). Freshness is checked on each request.
- No new "sync" or "diff" API endpoints. Existing endpoints get version-aware conditional responses.
- No client-side invalidation logic. The server is the sole authority on freshness.
- No offline data access. This is a caching optimization, not an offline-first architecture.

---

## Current State: Detailed Audit

### A. How GET Calls Are Made Today

The client uses a mix of patterns with no enforced standard:

| Pattern | Approximate Count | Used By |
|---------|-------------------|---------|
| `$.get(url, callback)` | ~25 calls | Older modules (common-chat.js, workspace-manager.js) |
| `$.ajax({url, type:'GET'})` | ~7 calls | When caller needs jqXHR promise |
| `$.getJSON(url, callback)` | ~8 calls | File browser, doc folders |
| `fetch(url)` | ~20 calls | Newer modules (doubt-manager.js, artefacts-manager.js, chat.js) |

There is one existing wrapper `apiCall()` at `common.js:6705` but it's used in only ~5 places (mostly POST). No global `$.ajaxSetup` or `ajaxPrefilter` exists.

### B. Server Response Headers Today

None of the GET data endpoints set any cache-related HTTP headers. All return bare `jsonify(...)` responses. Flask does not add `Cache-Control`, `ETag`, or `Last-Modified` to `jsonify()` responses by default. There is no `@app.after_request` hook in the codebase.

### C. Existing Version/Timestamp Infrastructure

| Entity | `updated_at` exists? | Reliably maintained? |
|--------|---------------------|---------------------|
| `UserToConversationId` | Yes (TEXT) | **No** — set on INSERT only, never updated on mutations |
| `UserDetails` | Yes (TEXT) | Yes — `users.py:93` sets it on every UPDATE |
| `DoubtsClearing` | Yes (TEXT) | Yes — all mutations in `doubts.py` set it |
| `SectionHiddenDetails` | Yes (TEXT) | Yes — INSERT OR REPLACE always sets it |
| `PinnedMessages` | **No column** | N/A — only `created_at` exists |
| `WorkspaceMetadata` | Yes (TEXT) | Mostly — one `SET expanded=0` path doesn't update it |
| `messages` (conv store) | Yes (REAL) | Partial — NULL on insert, set on edit/hide, not set on move |
| `documents` (conv store) | **No column** | N/A — only `created_at` exists |
| `artefacts` (conv store) | Yes (REAL) | Partial — NULL on insert, set on update |

**Conversation-level version/timestamp: Does not exist.** The `Conversation` Python object has no `_version`, `_last_modified`, or per-scope version counters. The closest thing is `memory["last_updated"]` — a string in a JSON blob inside the dill-serialized object, updated inconsistently.

**Server-side in-memory `conversation_cache`** (`server.py:507`, `common.py:1819`): LRU dict of 200 live `Conversation` objects. No staleness tracking, no version checking, no TTL. Objects are mutated in-place since the server is single-process.

### D. Client-Side Data Storage Today

| Storage | What's Stored | Purpose |
|---------|--------------|---------|
| IndexedDB `science-chat-rendered-state` | DOM HTML snapshots per conversation (max 30, 4MB each) | Instant visual restore on conversation switch |
| `localStorage` | UI preferences, last active conversation, editor type, collapse states | UI state persistence |
| `sessionStorage` | Minimal session flags | Tab-scoped state |

**No API response data is cached client-side.** Every GET request always hits the server.

---

## Design

### Core Mechanism: ETag + If-None-Match (HTTP Conditional Requests)

The design uses standard HTTP conditional request semantics:

```
First request:
  Client:  GET /list_messages_by_conversation/abc123
  Server:  200 OK
           ETag: "m47"
           Body: {messages: [...]}

Subsequent request (data unchanged):
  Client:  GET /list_messages_by_conversation/abc123
           If-None-Match: "m47"
  Server:  304 Not Modified
           (empty body)
  Client:  uses cached response from IndexedDB

Subsequent request (data changed):
  Client:  GET /list_messages_by_conversation/abc123
           If-None-Match: "m47"
  Server:  200 OK
           ETag: "m48"
           Body: {messages: [...updated...]}
  Client:  stores new response + ETag in IndexedDB
```

The `304` path skips the DB query and JSON serialization entirely — the server only needs to look up a single integer version counter.

### Entity Version Scopes

Each version scope is an independent monotonic integer counter. Scopes are not hierarchical — a change in one scope does not propagate upward to parent scopes unless the parent scope's API response actually changes.

| Version Scope | Governs (GET API) | Granularity |
|---------------|-------------------|-------------|
| `user:{email}:convlist` | `/list_conversation_by_user/{domain}` | Per user per domain (see note) |
| `conv:{id}:messages` | `/list_messages_by_conversation/{id}` | Per conversation |
| `conv:{id}:settings` | `/get_conversation_settings/{id}` | Per conversation |
| `conv:{id}:details` | `/get_conversation_details/{id}` | Per conversation |
| `conv:{id}:mempad` | `/fetch_memory_pad/{id}` | Per conversation |
| `conv:{id}:docs` | `/list_documents_by_conversation/{id}` | Per conversation |
| `conv:{id}:pins` | `/get_pinned_messages/{id}` | Per conversation |
| `conv:{id}:doubtmap` | `/get_messages_with_doubts/{id}` | Per conversation |
| `conv:{id}:artefacts` | `/artefacts/{id}` (GET list) | Per conversation |
| `msg:{convId}:{msgId}:doubts` | `/get_doubts/{convId}/{msgId}` | Per message |
| `doubt:{doubtId}` | `/get_doubt/{doubtId}` | Per doubt |
| `artefact:{convId}:{artefactId}` | `/artefacts/{convId}/{artefactId}` (GET single) | Per artefact |

**Domain note**: The conversation list is per-domain, but the version counter is per-user (not per-domain) because operations like `delete_conversation` or `archive_conversation` affect the list regardless of which domain view the client has. The domain is a client-side filter on the conversation list — the server returns conversations for one domain, but the version counter `user:{email}:convlist` bumps on any structural change across all domains. This is conservative (may over-invalidate if a change happened in a different domain than the one the client is viewing) but correct and simple. Per-domain versioning can be added later if needed.

### What Does NOT Get Cached

| Endpoint | Reason |
|----------|--------|
| `/get_lock_status/{id}` | Ephemeral real-time state; must always be fresh |
| `/send_message/{id}` | POST with streaming response |
| `/clear_doubt/{convId}/{msgId}` | POST with streaming response |
| `/regenerate_doubt/{doubtId}` | POST with streaming response |
| All POST/PUT/DELETE endpoints | Mutations; not cacheable |
| `/search_conversations` | POST; different query each time |
| `/get_user_info` | Very small payload, called once on page load |
| `/model_catalog` | Changes rarely, small payload, called once per session |

### Mutation-to-Scope Bump Map

Every POST/PUT/DELETE mutation that changes persisted data must bump the version counters of all entity scopes whose GET API response would change as a result. This is the complete map for in-scope endpoints.

#### Conversation List Scope (`user:{email}:convlist`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Create conversation | `POST /create_conversation/{domain}/` | `conversations.py:2489` |
| Create conversation in workspace | `POST /create_conversation/{domain}/{workspace_id}` | `conversations.py:2492` |
| Create temporary conversation | `POST /create_temporary_conversation/{domain}` | `conversations.py:2508` |
| Delete conversation | `DELETE /delete_conversation/{id}` | `conversations.py:1007` |
| Clone conversation | `POST /clone_conversation/{id}` | `conversations.py:917` |
| Fork conversation | `POST /fork_conversation/{id}/{msg_index}` | `conversations.py:965` |
| Set flag | `POST /set_flag/{id}/{flag}` | `conversations.py:1942` |
| Archive/unarchive | `POST /archive_conversation/{id}` | `conversations.py:2006` |
| Auto-archive all | `POST /auto_archive_all/{domain}` | `conversations.py:2081` |
| Move to workspace | `PUT /move_conversation_to_workspace/{id}` | `workspaces.py:184` |
| Create workspace | `POST /create_workspace/{domain}/{name}` | `workspaces.py:38` |
| Update workspace | `PUT /update_workspace/{workspace_id}` | `workspaces.py:104` |
| Delete workspace | `DELETE /delete_workspace/{domain}/{id}` | `workspaces.py:156` |
| Move workspace | `PUT /move_workspace/{workspace_id}` | `workspaces.py:232` |
| Send message | `POST /send_message/{id}` | `conversations.py:2689` |
| Create conversation from doubt | `POST /create_conversation_from_doubt_thread/{doubtId}` | `doubts.py:823` |

**Note on `send_message`**: The conversation list response includes `title`, `last_updated`, and `summary_till_now` — all of which change when messages are sent (`persist_current_turn` at `Conversation.py:4743` updates `memory["last_updated"]` and `memory["title"]`). Therefore sending a message bumps both `conv:{id}:messages` and `user:{email}:convlist`.

#### Messages Scope (`conv:{id}:messages`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Send message | `POST /send_message/{id}` | `conversations.py:2689` |
| Edit message | `POST /edit_message_from_conversation/{id}/{mid}/{idx}` | `conversations.py:641` |
| Revert message | `POST /revert_message_from_conversation/{id}/{mid}/{idx}` | `conversations.py:700` |
| Hide/show message | `POST /show_hide_message_from_conversation/{id}/{mid}/{idx}` | `conversations.py:845` |
| Batch hide | `POST /batch_hide_messages/{id}` | `conversations.py:895` |
| Batch delete | `POST /batch_delete_messages/{id}` | `conversations.py:874` |
| Delete single message | `DELETE /delete_message_from_conversation/{id}/{mid}/{idx}` | `conversations.py:1040` |
| Delete message pair | `DELETE /delete_message_pair/{id}/{mid}/{idx}` | `conversations.py:1120` |
| Delete last message | `DELETE /delete_last_message/{id}` | `conversations.py:1428` |
| Move messages | `POST /move_messages_up_or_down/{id}` | `conversations.py:796` |
| Move pair as doubt | `POST /move_pair_as_doubt/{id}/{mid}/{idx}` | `conversations.py:1216` |
| Get coding hint | `POST /get_coding_hint/{id}` | `conversations.py:1684` |
| Get full solution | `POST /get_full_solution/{id}` | `conversations.py:1798` |

#### Settings Scope (`conv:{id}:settings`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Set settings | `PUT /set_conversation_settings/{id}` | `conversations.py:447` |
| Make stateless | `DELETE /make_conversation_stateless/{id}` | `conversations.py:593` |
| Make stateful | `PUT /make_conversation_stateful/{id}` | `conversations.py:619` |

#### Details Scope (`conv:{id}:details`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Set flag | `POST /set_flag/{id}/{flag}` | `conversations.py:1942` |
| Make stateless/stateful | `DELETE /make_conversation_stateless/{id}`, `PUT /make_conversation_stateful/{id}` | `conversations.py:593,619` |
| Send message | `POST /send_message/{id}` | `conversations.py:2689` |

**Note**: `get_conversation_details` returns `get_metadata()` which includes `title`, `last_updated`, `summary_till_now`, `flag`, `conversation_settings` — all volatile fields. It bumps on send_message because title/summary/last_updated change.

#### Memory Pad Scope (`conv:{id}:mempad`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Set memory pad | `POST /set_memory_pad/{id}` | `conversations.py:1510` |

#### Documents Scope (`conv:{id}:docs`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Upload doc | `POST /upload_doc_to_conversation/{id}` | `documents.py:41` |
| Attach doc to message | `POST /attach_doc_to_message/{id}` | `documents.py:101` |
| Remove doc | `DELETE /remove_doc_from_conversation/{id}/{doc_id}` | `documents.py:139` |
| Add doc | `POST /add_doc_to_conversation/{id}` | `documents.py:180` |
| Detach doc | `DELETE /detach_doc_from_conversation/{id}/{doc_id}` | `documents.py:215` |
| Update doc metadata | `PATCH /docs/{id}/{doc_id}/metadata` | `documents.py:239` |
| Upgrade doc index | `POST /upgrade_doc_index/{id}/{doc_id}` | `documents.py:342` |
| Replace doc | `POST /docs/{id}/{doc_id}/replace` | `documents.py:658` |
| Cleanup orphan docs | `POST /cleanup_orphan_docs` | `documents.py:487` |
| Promote global doc to local | `POST /global_docs/promote/{id}/{doc_id}` | `global_docs.py:424` |

#### Pins Scope (`conv:{id}:pins`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Pin/unpin message | `POST /pin_message/{id}/{mid}` | `conversations.py:2189` |
| Delete message (if pinned) | `DELETE /delete_message_from_conversation/...` | `conversations.py:1040` |
| Delete message pair (if pinned) | `DELETE /delete_message_pair/...` | `conversations.py:1120` |
| Delete last message (if pinned) | `DELETE /delete_last_message/{id}` | `conversations.py:1428` |

#### Doubt Map Scope (`conv:{id}:doubtmap`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Clear doubt (creates new) | `POST /clear_doubt/{convId}/{msgId}` | `doubts.py:44` |
| Delete doubt | `DELETE /delete_doubt/{doubtId}` | `doubts.py:406` |
| Move pair as doubt | `POST /move_pair_as_doubt/{id}/{mid}/{idx}` | `conversations.py:1216` |
| Batch delete messages | `POST /batch_delete_messages/{id}` | `conversations.py:874` |
| Delete message | `DELETE /delete_message_from_conversation/...` | `conversations.py:1040` |
| Delete message pair | `DELETE /delete_message_pair/...` | `conversations.py:1120` |

#### Per-Message Doubts Scope (`msg:{convId}:{msgId}:doubts`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Clear doubt (creates new) | `POST /clear_doubt/{convId}/{msgId}` | `doubts.py:44` |
| Delete doubt | `DELETE /delete_doubt/{doubtId}` | `doubts.py:406` |
| Show/hide doubt | `POST /show_hide_doubt/{doubtId}` | `doubts.py:461` |
| Regenerate doubt | `POST /regenerate_doubt/{doubtId}` | `doubts.py:654` |
| Summarize doubt thread | `POST /summarize_doubt_thread/{doubtId}` | `doubts.py:716` |

#### Single Doubt Scope (`doubt:{doubtId}`)

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Clear doubt (child doubt added) | `POST /clear_doubt/{convId}/{msgId}` | `doubts.py:44` |
| Delete doubt | `DELETE /delete_doubt/{doubtId}` | `doubts.py:406` |
| Show/hide doubt | `POST /show_hide_doubt/{doubtId}` | `doubts.py:461` |
| Pin doubt | `POST /pin_doubt/{doubtId}` | `doubts.py:616` |
| Bookmark doubt | `POST /bookmark_doubt/{doubtId}` | `doubts.py:635` |
| Regenerate doubt | `POST /regenerate_doubt/{doubtId}` | `doubts.py:654` |
| Summarize doubt thread | `POST /summarize_doubt_thread/{doubtId}` | `doubts.py:716` |

#### Artefact Scopes

**Artefact list** (`conv:{id}:artefacts`):

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Create artefact | `POST /artefacts/{id}` | `artefacts.py:409` |
| Update artefact | `PUT /artefacts/{id}/{aid}` | `artefacts.py:444` |
| Delete artefact | `DELETE /artefacts/{id}/{aid}` | `artefacts.py:461` |
| Apply edits | `POST /artefacts/{id}/{aid}/apply_edits` | `artefacts.py:647` |
| Create/delete message link | `POST /artefacts/{id}/message_links`, `DELETE .../message_links/{mid}` | `artefacts.py:705,732` |
| Delete message (cascades to links) | `DELETE /delete_message_from_conversation/...` | `conversations.py:1040` |
| Delete message pair | `DELETE /delete_message_pair/...` | `conversations.py:1120` |

**Single artefact** (`artefact:{convId}:{artefactId}`):

| Mutation | Endpoint | File:Line |
|----------|----------|-----------|
| Update artefact | `PUT /artefacts/{id}/{aid}` | `artefacts.py:444` |
| Propose edits | `POST /artefacts/{id}/{aid}/propose_edits` | `artefacts.py:500` |
| Apply edits | `POST /artefacts/{id}/{aid}/apply_edits` | `artefacts.py:647` |

---

## Server-Side Implementation

### The `entity_versions` Table

A single new table in `users.db`:

```sql
CREATE TABLE IF NOT EXISTS entity_versions (
    scope TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (scope)
);
```

- `scope` is the version scope string, e.g. `user:alice@example.com:convlist`, `conv:abc123:messages`, `doubt:d789`.
- `version` is a monotonic integer, starting at 0.
- `updated_at` is for debugging/observability only; not used in version checks.

Rows are created lazily on first bump (INSERT OR IGNORE + UPDATE) or on first read (default to 0 if not found).

### Version Bump Function

A single reusable function called by every mutation:

```python
# database/entity_versions.py

def bump_version(users_dir: str, *scopes: str) -> None:
    """Atomically increment version counters for one or more scopes."""
    db_path = os.path.join(users_dir, "users.db")
    conn = sqlite3.connect(db_path)
    try:
        for scope in scopes:
            conn.execute(
                """INSERT INTO entity_versions (scope, version, updated_at)
                   VALUES (?, 1, datetime('now'))
                   ON CONFLICT(scope) DO UPDATE
                   SET version = version + 1, updated_at = datetime('now')""",
                (scope,)
            )
        conn.commit()
    finally:
        conn.close()


def get_version(users_dir: str, scope: str) -> int:
    """Get current version for a scope. Returns 0 if no row exists."""
    db_path = os.path.join(users_dir, "users.db")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT version FROM entity_versions WHERE scope = ?",
            (scope,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
```

### Scope String Builders

Helper functions to construct scope strings consistently:

```python
# database/entity_versions.py

def convlist_scope(email: str) -> str:
    return f"user:{email}:convlist"

def conv_scope(conversation_id: str, component: str) -> str:
    return f"conv:{conversation_id}:{component}"

def msg_doubts_scope(conversation_id: str, message_id: str) -> str:
    return f"msg:{conversation_id}:{message_id}:doubts"

def doubt_scope(doubt_id: str) -> str:
    return f"doubt:{doubt_id}"

def artefact_scope(conversation_id: str, artefact_id: str) -> str:
    return f"artefact:{conversation_id}:{artefact_id}"
```

### ETag Decorator for GET Endpoints

A decorator that checks `If-None-Match` against the current version and short-circuits with `304` if matched:

```python
# database/entity_versions.py or endpoints/cache_utils.py

from functools import wraps
from flask import request, make_response

def versioned_etag(scope_fn):
    """Decorator for GET endpoints. scope_fn receives the same kwargs as the 
    endpoint and returns the version scope string.
    
    Usage:
        @versioned_etag(lambda conversation_id, **kw: conv_scope(conversation_id, "messages"))
        def list_messages_by_conversation(conversation_id):
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            scope = scope_fn(**kwargs)
            current_version = get_version(get_state().users_dir, scope)
            etag = f'"{scope}:{current_version}"'
            
            # Check If-None-Match
            if_none_match = request.headers.get("If-None-Match")
            if if_none_match == etag:
                return make_response("", 304)
            
            # Version changed or no cached version — run the endpoint
            response = make_response(f(*args, **kwargs))
            response.headers["ETag"] = etag
            response.headers["Cache-Control"] = "no-cache"  # must revalidate
            return response
        return wrapper
    return decorator
```

**`Cache-Control: no-cache`** means "you can store this, but must revalidate with the server before using it." This is correct — we want the browser/client to always check freshness via `If-None-Match`, but to store the response for reuse when the server confirms `304`.

### Applying the Decorator to GET Endpoints

Example for `list_messages_by_conversation`:

```python
# Before:
@conversations_bp.route("/list_messages_by_conversation/<conversation_id>", methods=["GET"])
@limiter.limit("1000 per minute")
@login_required
def list_messages_by_conversation(conversation_id: str):
    ...

# After:
@conversations_bp.route("/list_messages_by_conversation/<conversation_id>", methods=["GET"])
@limiter.limit("1000 per minute")
@login_required
@versioned_etag(lambda conversation_id, **kw: conv_scope(conversation_id, "messages"))
def list_messages_by_conversation(conversation_id: str):
    ...
```

The decorator slots in after `@login_required` (so auth is checked before version lookup) and before the function body. If the ETag matches, the function body **never executes** — no DB query, no JSON serialization.

### Full GET Endpoint Decorator Map

| Endpoint | Decorator `scope_fn` |
|----------|---------------------|
| `list_conversation_by_user(domain)` | `lambda domain, **kw: convlist_scope(get_session_identity()[0])` |
| `list_messages_by_conversation(conversation_id)` | `lambda conversation_id, **kw: conv_scope(conversation_id, "messages")` |
| `get_conversation_settings(conversation_id)` | `lambda conversation_id, **kw: conv_scope(conversation_id, "settings")` |
| `get_conversation_details(conversation_id)` | `lambda conversation_id, **kw: conv_scope(conversation_id, "details")` |
| `fetch_memory_pad(conversation_id)` | `lambda conversation_id, **kw: conv_scope(conversation_id, "mempad")` |
| `list_documents_by_conversation(conversation_id)` | `lambda conversation_id, **kw: conv_scope(conversation_id, "docs")` |
| `get_pinned_messages(conversation_id)` | `lambda conversation_id, **kw: conv_scope(conversation_id, "pins")` |
| `get_messages_with_doubts(conversation_id)` | `lambda conversation_id, **kw: conv_scope(conversation_id, "doubtmap")` |
| `get_doubts(conversation_id, message_id)` | `lambda conversation_id, message_id, **kw: msg_doubts_scope(conversation_id, message_id)` |
| `get_doubt(doubt_id)` | `lambda doubt_id, **kw: doubt_scope(doubt_id)` |
| `list_artefacts(conversation_id)` (GET) | `lambda conversation_id, **kw: conv_scope(conversation_id, "artefacts")` |
| `get_artefact(conversation_id, artefact_id)` (GET) | `lambda conversation_id, artefact_id, **kw: artefact_scope(conversation_id, artefact_id)` |

### Inserting Version Bumps into Mutation Endpoints

Each mutation endpoint adds a `bump_version()` call after the mutation succeeds. Example for `edit_message_from_conversation`:

```python
# endpoints/conversations.py — edit_message_from_conversation
def edit_message_from_conversation(conversation_id, message_id, index):
    ...
    conversation.edit_message(message_id, int(index), message_text)
    # Bump version after successful mutation
    bump_version(state.users_dir, conv_scope(conversation_id, "messages"))
    return jsonify({"result": "success"})
```

Example for `send_message` (bumps multiple scopes):

```python
# At the end of send_message, after persist_current_turn completes:
bump_version(
    state.users_dir,
    conv_scope(conversation_id, "messages"),
    conv_scope(conversation_id, "details"),  # title/summary/last_updated change
    convlist_scope(email),                    # list metadata changes
)
```

Example for `delete_doubt` (bumps doubt-level and conversation-level scopes):

```python
# endpoints/doubts.py — delete_doubt
def delete_doubt(doubt_id):
    ...
    # Need conversation_id and message_id from the doubt record
    doubt_record = get_doubt_by_id(doubt_id, ...)
    conv_id = doubt_record["conversation_id"]
    msg_id = doubt_record["message_id"]
    
    delete_doubt_from_db(doubt_id, ...)
    
    bump_version(
        state.users_dir,
        doubt_scope(doubt_id),
        msg_doubts_scope(conv_id, msg_id),
        conv_scope(conv_id, "doubtmap"),
    )
    return jsonify({"success": True})
```

### In-Memory Version Cache (Server-Side Optimization)

Reading from SQLite on every GET request for the version check adds a DB round-trip. Since the server is single-process and all mutations go through the same process, we can cache versions in memory:

```python
# database/entity_versions.py

_version_cache: Dict[str, int] = {}

def bump_version(users_dir: str, *scopes: str) -> None:
    """Bump in DB and update in-memory cache."""
    # ... DB UPDATE as above ...
    for scope in scopes:
        _version_cache[scope] = _version_cache.get(scope, 0) + 1

def get_version(users_dir: str, scope: str) -> int:
    """Read from in-memory cache, falling back to DB."""
    if scope in _version_cache:
        return _version_cache[scope]
    # ... DB SELECT as above ...
    version = row[0] if row else 0
    _version_cache[scope] = version
    return version
```

The DB write is still needed for durability (survives server restart), but the read path becomes a dict lookup — effectively free. The cache is always consistent because the same process does both reads and writes.

On server startup, the cache starts empty and populates lazily from DB on first access. This is correct because a restart means a fresh process with no stale cache entries.

---

## Client-Side Implementation

### IndexedDB Cache Store

A new object store in the existing `science-chat-rendered-state` IndexedDB database (or a separate `api-cache` database if cleaner):

```javascript
// interface/api-cache.js

const API_CACHE_DB = 'api-response-cache';
const API_CACHE_STORE = 'responses';
const API_CACHE_VERSION = 1;
const MAX_CACHE_ENTRIES = 500;

class ApiCacheStore {
    constructor() {
        this._db = null;
        this._dbPromise = this._openDb();
    }
    
    async _openDb() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(API_CACHE_DB, API_CACHE_VERSION);
            req.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains(API_CACHE_STORE)) {
                    const store = db.createObjectStore(API_CACHE_STORE, { keyPath: 'url' });
                    store.createIndex('cachedAt', 'cachedAt');
                }
            };
            req.onsuccess = (e) => { this._db = e.target.result; resolve(this._db); };
            req.onerror = (e) => reject(e.target.error);
        });
    }
    
    async get(url) {
        const db = await this._dbPromise;
        return new Promise((resolve) => {
            const tx = db.transaction(API_CACHE_STORE, 'readonly');
            const req = tx.objectStore(API_CACHE_STORE).get(url);
            req.onsuccess = () => resolve(req.result || null);
            req.onerror = () => resolve(null);
        });
    }
    
    async put(url, data, etag) {
        const db = await this._dbPromise;
        const tx = db.transaction(API_CACHE_STORE, 'readwrite');
        tx.objectStore(API_CACHE_STORE).put({
            url: url,
            data: data,
            etag: etag,
            cachedAt: Date.now()
        });
        // Fire-and-forget eviction of oldest entries if over limit
        this._evictIfNeeded(db);
    }
    
    async clearAll() {
        const db = await this._dbPromise;
        const tx = db.transaction(API_CACHE_STORE, 'readwrite');
        tx.objectStore(API_CACHE_STORE).clear();
    }
    
    async _evictIfNeeded(db) {
        const tx = db.transaction(API_CACHE_STORE, 'readwrite');
        const store = tx.objectStore(API_CACHE_STORE);
        const countReq = store.count();
        countReq.onsuccess = () => {
            if (countReq.result > MAX_CACHE_ENTRIES) {
                // Delete oldest 20% by cachedAt
                const evictCount = Math.floor(MAX_CACHE_ENTRIES * 0.2);
                const idx = store.index('cachedAt');
                let deleted = 0;
                idx.openCursor().onsuccess = (e) => {
                    const cursor = e.target.result;
                    if (cursor && deleted < evictCount) {
                        cursor.delete();
                        deleted++;
                        cursor.continue();
                    }
                };
            }
        };
    }
}

const apiCache = new ApiCacheStore();
```

### The Transparent `cachedGet` Wrapper

A single function that all GET call sites use. Handles ETag/If-None-Match transparently:

```javascript
// interface/api-cache.js (continued)

/**
 * Transparent cached GET. Checks IndexedDB for a cached response + ETag,
 * sends If-None-Match if available, returns cached data on 304.
 * 
 * Returns a Promise that resolves to the parsed JSON response data.
 * Falls back to a normal fetch on any cache error.
 */
async function cachedGet(url) {
    let cached = null;
    try {
        cached = await apiCache.get(url);
    } catch (e) {
        // IndexedDB failure — proceed without cache
    }
    
    const headers = {};
    if (cached && cached.etag) {
        headers['If-None-Match'] = cached.etag;
    }
    
    const response = await fetch(url, { method: 'GET', headers: headers });
    
    if (response.status === 304 && cached) {
        // Server confirmed: cached data is current
        return cached.data;
    }
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const data = await response.json();
    
    // Store response + ETag for next time
    const etag = response.headers.get('ETag');
    if (etag) {
        try {
            await apiCache.put(url, data, etag);
        } catch (e) {
            // IndexedDB write failure — non-fatal, just won't cache
        }
    }
    
    return data;
}
```

### jQuery Compatibility

Many call sites use `$.get()` or `$.ajax()` which return jQuery Deferreds. Provide a compatibility wrapper:

```javascript
// interface/api-cache.js (continued)

/**
 * jQuery-compatible wrapper. Returns a jQuery Deferred that behaves
 * like $.get() — callers can chain .done(), .fail(), .then().
 */
cachedGet.jq = function(url) {
    var deferred = $.Deferred();
    cachedGet(url)
        .then(function(data) { deferred.resolve(data); })
        .catch(function(err) { deferred.reject(err); });
    return deferred.promise();
};
```

### Migrating Call Sites

The migration is mechanical. Each call site changes from its current pattern to `cachedGet`:

```javascript
// BEFORE ($.ajax):
return $.ajax({ url: '/list_messages_by_conversation/' + conversationId, type: 'GET' });

// AFTER:
return cachedGet.jq('/list_messages_by_conversation/' + conversationId);


// BEFORE ($.get):
$.get('/get_pinned_messages/' + conversationId, function(data) { ... });

// AFTER:
cachedGet('/get_pinned_messages/' + conversationId).then(function(data) { ... });


// BEFORE (fetch):
fetch('/get_doubts/' + conversationId + '/' + messageId)
    .then(function(r) { return r.json(); })
    .then(function(data) { ... });

// AFTER:
cachedGet('/get_doubts/' + conversationId + '/' + messageId)
    .then(function(data) { ... });
```

The `cachedGet` version is actually simpler at call sites because it handles JSON parsing internally.

### Logout Cache Clearing

Add to the existing `clearSwCaches()` function in `common.js`:

```javascript
// In clearSwCaches(), after localStorage.clear() and sessionStorage.clear():
if (typeof apiCache !== 'undefined' && apiCache.clearAll) {
    apiCache.clearAll();
}
```

---

## Implementation Tasks

### Task 1: Create `entity_versions` table and core functions

**Files**: `database/connection.py`, `database/entity_versions.py` (new)

1a. Add `entity_versions` table creation to `ensure_tables_created()` in `database/connection.py`:
```sql
CREATE TABLE IF NOT EXISTS entity_versions (
    scope TEXT NOT NULL PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

1b. Create `database/entity_versions.py` with:
- `bump_version(users_dir, *scopes)` — INSERT ON CONFLICT UPDATE + in-memory cache update
- `get_version(users_dir, scope)` — in-memory cache read with DB fallback
- Scope string builder functions: `convlist_scope(email)`, `conv_scope(conversation_id, component)`, `msg_doubts_scope(conversation_id, message_id)`, `doubt_scope(doubt_id)`, `artefact_scope(conversation_id, artefact_id)`
- In-memory `_version_cache` dict with lazy population

1c. Write unit tests for `bump_version` and `get_version`:
- Verify version starts at 0 for unknown scope
- Verify bump increments by 1
- Verify multiple bumps in one call
- Verify in-memory cache consistency with DB
- Verify DB persistence across cache clears

**Dependencies**: None
**Estimated scope**: Small (~150 lines)

### Task 2: Create `versioned_etag` decorator

**Files**: `endpoints/cache_utils.py` (new)

2a. Implement the `versioned_etag(scope_fn)` decorator:
- Extracts `If-None-Match` from request headers
- Calls `get_version()` to get current version
- Compares ETag; returns `304` if matched
- Otherwise runs the endpoint function, attaches `ETag` and `Cache-Control: no-cache` headers to response

2b. Handle edge cases:
- Multiple `If-None-Match` values (comma-separated per HTTP spec)
- Wildcard `*` (should bypass cache — treat as miss)
- Missing `scope_fn` return (skip caching for this request)
- Non-GET requests that hit the same route (skip caching)

2c. Write unit tests:
- 304 on matching ETag
- 200 with ETag on cache miss
- 200 with new ETag on version bump
- Correct headers (ETag format, Cache-Control)
- Edge cases above

**Dependencies**: Task 1
**Estimated scope**: Small (~80 lines + tests)

### Task 3: Add `versioned_etag` decorator to all GET endpoints

**Files**: `endpoints/conversations.py`, `endpoints/doubts.py`, `endpoints/documents.py`, `endpoints/artefacts.py`

Add the decorator to each GET endpoint in the decorator stack (after `@login_required`). 12 endpoints total:

| # | Endpoint | File |
|---|----------|------|
| 1 | `list_conversation_by_user` | `conversations.py:2281` |
| 2 | `list_messages_by_conversation` | `conversations.py:238` |
| 3 | `get_conversation_settings` | `conversations.py:428` |
| 4 | `get_conversation_details` | `conversations.py:351` |
| 5 | `fetch_memory_pad` | `conversations.py:1531` |
| 6 | `get_pinned_messages` | `conversations.py:2222` |
| 7 | `get_messages_with_doubts` | `conversations.py` (find exact line) |
| 8 | `list_documents_by_conversation` | `documents.py:292` |
| 9 | `get_doubts` | `doubts.py` |
| 10 | `get_doubt` | `doubts.py` |
| 11 | `list_artefacts` (GET handler) | `artefacts.py` |
| 12 | `get_artefact` (GET handler) | `artefacts.py` |

Each endpoint gets one new import and one decorator line. The function body does not change.

**Dependencies**: Task 2
**Estimated scope**: Small (12 one-line additions + imports)

### Task 4: Add `bump_version` calls to all mutation endpoints

**Files**: `endpoints/conversations.py`, `endpoints/doubts.py`, `endpoints/documents.py`, `endpoints/artefacts.py`, `endpoints/workspaces.py`, `endpoints/global_docs.py`

For each mutation endpoint listed in the Mutation-to-Scope Bump Map above, add a `bump_version()` call after the mutation succeeds. This is the largest task — ~45 mutation endpoints need version bumps.

Group by file for efficient editing:

**4a. `endpoints/conversations.py`** (~25 mutations):
- `send_message`: bump `conv:messages`, `conv:details`, `user:convlist`
- `create_conversation`, `create_temporary_conversation`: bump `user:convlist`
- `delete_conversation`: bump `user:convlist` (conversation-level scopes become irrelevant)
- `clone_conversation`, `fork_conversation`: bump `user:convlist`
- `edit_message_from_conversation`, `revert_message_from_conversation`: bump `conv:messages`
- `show_hide_message_from_conversation`, `batch_hide_messages`: bump `conv:messages`
- `batch_delete_messages`: bump `conv:messages`, `conv:doubtmap`
- `delete_message_from_conversation`: bump `conv:messages`, `conv:pins`, `conv:doubtmap`, `conv:artefacts`
- `delete_message_pair`: bump `conv:messages`, `conv:pins`, `conv:doubtmap`, `conv:artefacts`
- `delete_last_message`: bump `conv:messages`, `conv:pins`, `conv:doubtmap`
- `move_messages_up_or_down`: bump `conv:messages`
- `move_pair_as_doubt`: bump `conv:messages`, `conv:doubtmap` + relevant `msg:doubts`
- `set_conversation_settings`: bump `conv:settings`
- `make_conversation_stateless`, `make_conversation_stateful`: bump `conv:settings`, `conv:details`
- `set_memory_pad`: bump `conv:mempad`
- `set_flag`: bump `user:convlist`, `conv:details`
- `archive_conversation`: bump `user:convlist`
- `auto_archive_all`: bump `user:convlist`
- `pin_message`: bump `conv:pins`
- `get_coding_hint`, `get_full_solution`: bump `conv:messages`

**4b. `endpoints/doubts.py`** (~7 mutations):
- `clear_doubt`: bump `conv:doubtmap`, `msg:doubts`, `doubt:{id}`
- `delete_doubt`: bump `conv:doubtmap`, `msg:doubts`, `doubt:{id}`
- `show_hide_doubt`: bump `msg:doubts`, `doubt:{id}`
- `pin_doubt`, `bookmark_doubt`: bump `doubt:{id}`
- `regenerate_doubt`: bump `msg:doubts`, `doubt:{id}`
- `summarize_doubt_thread`: bump `doubt:{id}`
- `create_conversation_from_doubt_thread`: bump `user:convlist`

**4c. `endpoints/documents.py`** (~9 mutations):
- All doc mutations: bump `conv:docs`

**4d. `endpoints/artefacts.py`** (~5 mutations):
- Create/update/delete artefact: bump `conv:artefacts` + `artefact:{id}` where relevant
- Message link create/delete: bump `conv:artefacts`

**4e. `endpoints/workspaces.py`** (~4 mutations):
- All workspace structure mutations: bump `user:convlist`

**4f. `endpoints/global_docs.py`** (1 mutation):
- `promote`: bump `conv:docs`

**Dependencies**: Task 1
**Estimated scope**: Medium (~45 insertions across 6 files, each 1-5 lines)

### Task 5: Create client-side cache store and `cachedGet` wrapper

**Files**: `interface/api-cache.js` (new), `interface/interface.html`

5a. Create `interface/api-cache.js` with:
- `ApiCacheStore` class (IndexedDB CRUD with LRU eviction)
- `cachedGet(url)` async function (ETag/If-None-Match/304 handling)
- `cachedGet.jq(url)` jQuery-compatible wrapper
- `apiCache` singleton instance
- `MAX_CACHE_ENTRIES = 500` constant

5b. Add `<script src="api-cache.js"></script>` to `interface/interface.html` — must load before any JS that uses `cachedGet`. Place it early, after jQuery but before `common.js`.

5c. Add `apiCache.clearAll()` call to `clearSwCaches()` in `common.js`.

**Dependencies**: None (client-side only; can develop in parallel with Tasks 1-4)
**Estimated scope**: Small (~150 lines)

### Task 6: Migrate GET call sites to `cachedGet`

**Files**: `interface/common-chat.js`, `interface/workspace-manager.js`, `interface/chat.js`, `interface/doubt-manager.js`, `interface/local-docs-manager.js`, `interface/artefacts-manager.js`, `interface/context-menu-manager.js`

Migrate all GET call sites for the 12 in-scope endpoints to use `cachedGet`. This is a mechanical transformation:

**6a. `common-chat.js`** (~10 call sites):
- `ChatManager.listMessages()` (line 2577): `$.ajax GET` → `cachedGet.jq()`
- `ConversationManager.getConversationDetails()` (line 660): `$.ajax GET` → `cachedGet.jq()`
- `ConversationManager.getConversationSettings()` (line 674): `$.ajax GET` → `cachedGet.jq()`
- `ConversationManager.fetchMemoryPad()` (line 649): `$.ajax GET` → `cachedGet.jq()`
- `_fetchDoubtsData()` (line 3485): `fetch` → `cachedGet()`
- `revealDoubtsButtons()` (line 3471): `fetch` → `cachedGet()`
- `ChatManager._fetchAndHighlightPins()` (line 3274): `$.get` → `cachedGet()`
- `ChatManager._fetchPinsData()` (line 3288): `$.get` → `cachedGet().then()`
- Pinned messages modal handler (line 3347): `$.get` → `cachedGet()`

**6b. `workspace-manager.js`** (1 call site):
- `loadConversationsWithWorkspaces()` (line 286): `$.ajax GET` → `cachedGet.jq()`

**6c. `chat.js`** (2 call sites):
- `loadConversationModelOverrides()` (line 911): `$.ajax GET` → `cachedGet.jq()`
- `loadOpencodeSettings()` (line 996): `$.get` → `cachedGet()`

**6d. `doubt-manager.js`** (~5 call sites):
- `showDoubtsOverview()` (line 36): `fetch` → `cachedGet()`
- `openDoubtChat()` (line 245): `fetch` → `cachedGet()`
- `openDoubtChat()` follow-up tree (line 270): `fetch` → `cachedGet()`
- `getDoubtHistory()` (line 311): `fetch` → `cachedGet()`

**6e. `local-docs-manager.js`** (1 call site):
- `LocalDocsManager.list()` (line 288): `$.ajax GET` → `cachedGet.jq()`

**6f. `artefacts-manager.js`** (2 call sites):
- `listArtefacts()`: `fetch` → `cachedGet()`
- `getArtefact()`: `fetch` → `cachedGet()`

**6g. `context-menu-manager.js`** (1 call site):
- `handleContinueDoubtInChat()` (line 688): `fetch` → `cachedGet()`

Each migration:
1. Replace the HTTP call with `cachedGet()` or `cachedGet.jq()`
2. Remove the `.then(r => r.json())` step (cachedGet handles JSON parsing)
3. Keep the existing `.then(data => ...)` / `.done(function(data) {...})` callback unchanged
4. Keep existing error handling unchanged (add `.catch()` if not present)

**Dependencies**: Task 5
**Estimated scope**: Medium (~22 call sites, each 1-3 line change)

### Task 7: Integration testing and verification

**Files**: No new files; testing only.

7a. **Server-side version bump verification**:
- For each mutation endpoint, verify the correct scopes are bumped by checking the `entity_versions` table before and after
- Verify no scope is missed (cross-reference with Mutation-to-Scope Bump Map)
- Verify no spurious bumps (scopes that shouldn't change remain unchanged)

7b. **ETag round-trip verification**:
- For each of the 12 GET endpoints: make a request, verify ETag header in response
- Make same request with `If-None-Match: <etag>`, verify `304 Not Modified`
- Mutate the data, make same request with old ETag, verify `200` with new ETag
- Verify response body is identical on `200` (functional correctness)

7c. **Client-side cache verification**:
- Open DevTools, switch conversations, verify `If-None-Match` header is sent on second visit
- Verify `304` responses in Network tab when nothing changed
- Verify `200` responses when data actually changed
- Verify IndexedDB `api-response-cache` store has entries with correct ETags

7d. **Cross-device simulation**:
- Open app on two browser profiles (simulating two devices)
- Device A sends a message; Device B switches to that conversation
- Verify Device B gets `200` (not `304`) with fresh data

7e. **Cache clearing on logout**:
- Verify IndexedDB `api-response-cache` is cleared on logout
- Verify re-login starts with empty cache (all requests return `200`)

7f. **Error resilience**:
- Disable IndexedDB (private browsing or full storage), verify app works normally (just no caching)
- Corrupt a cached entry, verify app recovers gracefully (falls back to full fetch)

**Dependencies**: Tasks 3, 4, 6
**Estimated scope**: Testing only, no code

---

## Task Dependency Order

```
Task 1 (entity_versions table + bump/get functions)
 |
 +──> Task 2 (versioned_etag decorator)
 |     |
 |     +──> Task 3 (apply decorator to 12 GET endpoints)
 |
 +──> Task 4 (add bump_version calls to ~45 mutation endpoints)

Task 5 (client-side api-cache.js + cachedGet) [parallel with Tasks 1-4]
 |
 +──> Task 6 (migrate ~22 GET call sites to cachedGet)

Tasks 3 + 4 + 6 ──> Task 7 (integration testing)
```

Tasks 1-4 (server) and Task 5 (client) can be developed in parallel. Task 6 requires Task 5. Task 7 requires everything.

Recommended implementation order: **1 → 2 → 3 → 4** (server) in parallel with **5 → 6** (client), then **7** (testing).

---

## Decisions Log

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Versioning granularity | Per-entity-scope, not hierarchical | A doubt being created doesn't change what `/list_messages` returns. Hierarchical propagation would over-invalidate. Each API maps to exactly one version scope. |
| 2 | Entity vs API-level versioning | Entity-level | Multiple GET APIs can share the same entity scope (e.g. `conv:details` for both `get_conversation_details` and parts of `list_conversation_by_user`). Versioning the entity is correct; the API just reads from it. |
| 3 | No upward cascade | Version bumps are explicit per mutation | `send_message` bumps `conv:messages` + `user:convlist` explicitly because both API responses change. It does NOT bump `conv:pins` even though pins reference messages — the pins list itself didn't change. |
| 4 | No client-side invalidation | Server is sole authority via ETag | Another device could mutate at any time. Client-side invalidation is both insufficient (can't know about other devices) and unnecessary (server always knows current version). |
| 5 | No new sync/diff endpoint | Use HTTP ETag/If-None-Match on existing endpoints | Standard HTTP semantics. No API surface change. Client code barely changes — just uses a wrapper that adds one header. |
| 6 | `convlist` version scope is per-user, not per-domain | Per-user (conservative) | The conversation list is filtered by domain on the server, but mutations (delete, archive) can affect any domain. Per-domain versioning would miss cross-domain side effects. Over-invalidation is acceptable for this high-frequency endpoint. |
| 7 | `send_message` bumps `convlist` | Accept frequent invalidation | `get_metadata()` returns `title`, `last_updated`, `summary_till_now` which all change on message send. Excluding these from the list endpoint would require a separate lightweight endpoint — not worth the complexity. |
| 8 | Version storage | Single `entity_versions` table in `users.db` | Centralized, easy to query/debug, single `bump_version()` function. Alternative (columns on existing tables) would scatter logic across schemas. |
| 9 | In-memory version cache | Dict in server process | Single-process server means the cache is always consistent with DB. Avoids SQLite read on every GET request. DB is for durability across restarts. |
| 10 | Client cache storage | IndexedDB (separate DB `api-response-cache`) | `localStorage` has 5-10MB limit and is synchronous. IndexedDB handles large JSON payloads (message lists can be several MB), is async, and supports structured cloning. |
| 11 | Cache eviction | LRU, max 500 entries | 500 entries covers ~40 conversations worth of cached responses (12 endpoints per conversation + user-level). LRU eviction removes oldest 20% when limit is reached. |
| 12 | `Cache-Control` header | `no-cache` (not `no-store`) | `no-cache` means "store but revalidate." The browser's HTTP cache can also participate in the ETag check, providing a second layer of caching without any extra code. `no-store` would disable browser-level caching entirely. |
| 13 | jQuery compatibility | `cachedGet.jq()` wrapper returning Deferred | ~32 of the ~45 GET call sites use jQuery patterns. A compatibility wrapper avoids rewriting every call site to async/await. New code should use `cachedGet()` directly. |

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Missed version bump in a mutation endpoint** | Stale data served to client until a different mutation bumps the same scope, or user hard-refreshes | Systematic code review against the Mutation-to-Scope Bump Map. Integration tests (Task 7a) verify each mutation bumps correct scopes. Add a test that mutates every endpoint and checks version numbers. |
| **Streaming endpoints modify data after response starts** | `send_message` streams chunks to the client while `persist_current_turn` updates title/summary asynchronously. The version bump could happen before the streaming response completes. | Bump versions at the end of `persist_current_turn`, not at the start of streaming. The client receives the streamed response directly (not via cachedGet), and subsequent GET requests will see the bumped version. |
| **Over-invalidation of `convlist` scope** | Every message sent in any conversation invalidates the conversation list cache. In an active session, the list cache may rarely return 304. | Acceptable for now. The conversation list payload is relatively small (metadata only, no message bodies). If profiling shows this is a bottleneck, split volatile fields (`title`, `last_updated`) into a separate lightweight endpoint. |
| **IndexedDB unavailable** (private browsing, quota exceeded, browser bug) | `cachedGet` falls back to normal fetch. No caching benefit but no breakage. | All IndexedDB operations are wrapped in try/catch. The app works identically to today if IndexedDB is unavailable — just without caching. |
| **Stale in-memory version cache after server crash** | If the server crashes between a DB write and an in-memory cache update, the in-memory cache on restart will be cold (empty) and repopulate from DB on first access. | Not a real risk — the in-memory cache starts empty on every restart and lazily loads from DB. The DB is always the source of truth. |
| **Large cached responses consuming excessive IndexedDB storage** | A conversation with 500 messages could produce a multi-MB JSON response cached per-URL. With 500 entries, total storage could reach 100-500MB. | LRU eviction keeps entries bounded at 500. Most responses are small (settings, pins, memory pad). For the few large ones (message lists), the storage cost is justified by the bandwidth savings. Can add per-entry size limits if needed. |
| **ETag collision** | Two different scope states producing the same ETag string. | ETags include the full scope string + version number (e.g. `"conv:abc123:messages:47"`). Collisions are impossible for the same scope (monotonic counter) and extremely unlikely across scopes (scope string is unique). |
| **Concurrent requests + version bump race** | Client sends GET with `If-None-Match`, server bumps version between the check and the JSON serialization, client gets 304 but data just changed. | The version check and response generation happen within the same request handler (single-threaded per request in Flask). The decorator checks version, then if stale, calls the endpoint function synchronously. No mutation can interleave within the same request. Between requests, the next GET will see the bumped version. |
| **Database growth from fine-grained scopes** | Per-message-doubt scopes (`msg:{convId}:{msgId}:doubts`) could create many rows. A conversation with 100 messages that all have doubts would create 100 scope rows. | 100 rows is trivial for SQLite. Even 100,000 rows would be fine. The table is single-column indexed (PRIMARY KEY). Can add periodic cleanup of orphaned scopes (deleted conversations/messages) if the table grows large. |
| **Migration risk: call site regression** | Changing ~22 GET call sites could introduce bugs (wrong callback shape, missing error handling, jQuery vs Promise mismatch). | Migrate one file at a time. Test each file's functionality after migration. `cachedGet.jq()` returns the same shape as `$.ajax` (a thenable). The data returned is identical — only the transport is wrapped. |

---

## Verification Steps

1. **Cold start**: Clear IndexedDB. Start app. Verify all GET requests return `200` with `ETag` header, and responses are stored in IndexedDB.
2. **Warm revisit**: Switch to a conversation, switch away, switch back. Verify `304 Not Modified` for all 7 conversation-scoped GET requests in Network tab.
3. **Data change detection**: Send a message in a conversation. Switch away and back. Verify `list_messages` returns `200` (data changed), while `settings`, `docs`, `pins`, `mempad` return `304` (unchanged).
4. **Cross-scope isolation**: Edit memory pad. Verify only `fetch_memory_pad` returns `200` on next request; all other scopes return `304`.
5. **Doubt granularity**: Create a doubt on message A. Verify `get_messages_with_doubts` returns `200` (new doubt added to map). Verify `get_doubts` for message A returns `200`. Verify `get_doubts` for message B (which we also had cached) still returns `304`.
6. **Cross-device**: Open app on two browsers (different sessions, same user). Browser A sends a message. Browser B (which had the conversation cached) switches to it. Verify Browser B gets `200` with fresh data.
7. **Conversation list**: Create a new conversation. Verify `list_conversation_by_user` returns `200` on next load (version bumped). Open an existing conversation without modifications; verify list still returns `304`.
8. **Logout**: Log out. Verify IndexedDB `api-response-cache` store is cleared. Log in. Verify all requests return `200` (fresh data, new ETags).
9. **IndexedDB failure**: In DevTools, delete the `api-response-cache` database. Verify app continues to work normally — all requests return `200`, no errors in console.
10. **Performance**: Measure time for conversation switch (7 parallel GETs) with warm cache (7 x 304) vs cold (7 x 200). Expected: significant reduction in payload size and server-side DB query time.
11. **ETag header format**: Verify ETags are properly quoted (RFC 7232 requires double quotes: `"scope:version"`). Verify `If-None-Match` parsing handles quoted values.
12. **No regression**: Full manual walkthrough of core flows — send message, edit message, delete message, create/delete conversation, manage doubts, manage documents, pin messages, edit settings, save memory pad. Verify all operations work correctly and data is fresh after each mutation.

---

## Files Modified Summary

| File | Changes |
|------|---------|
| `database/connection.py` | Add `entity_versions` table to `ensure_tables_created()` |
| `database/entity_versions.py` | **New file.** `bump_version()`, `get_version()`, scope string builders, in-memory cache |
| `endpoints/cache_utils.py` | **New file.** `versioned_etag()` decorator |
| `endpoints/conversations.py` | Add `@versioned_etag` to 7 GET endpoints; add `bump_version()` to ~25 mutation endpoints |
| `endpoints/doubts.py` | Add `@versioned_etag` to 2 GET endpoints; add `bump_version()` to ~7 mutation endpoints |
| `endpoints/documents.py` | Add `@versioned_etag` to 1 GET endpoint; add `bump_version()` to ~9 mutation endpoints |
| `endpoints/artefacts.py` | Add `@versioned_etag` to 2 GET endpoints; add `bump_version()` to ~5 mutation endpoints |
| `endpoints/workspaces.py` | Add `bump_version()` to ~4 mutation endpoints |
| `endpoints/global_docs.py` | Add `bump_version()` to 1 mutation endpoint (`promote`) |
| `interface/api-cache.js` | **New file.** `ApiCacheStore` class, `cachedGet()`, `cachedGet.jq()` |
| `interface/interface.html` | Add `<script src="api-cache.js">` |
| `interface/common.js` | Add `apiCache.clearAll()` to `clearSwCaches()` |
| `interface/common-chat.js` | Migrate ~10 GET call sites to `cachedGet` |
| `interface/workspace-manager.js` | Migrate 1 GET call site to `cachedGet` |
| `interface/chat.js` | Migrate 2 GET call sites to `cachedGet` |
| `interface/doubt-manager.js` | Migrate ~5 GET call sites to `cachedGet` |
| `interface/local-docs-manager.js` | Migrate 1 GET call site to `cachedGet` |
| `interface/artefacts-manager.js` | Migrate 2 GET call sites to `cachedGet` |
| `interface/context-menu-manager.js` | Migrate 1 GET call site to `cachedGet` |

---

## Out of Scope

**PKB data caching**: The PKB module has ~50+ GET/POST endpoints. Adding version-aware caching to all of them is a large effort. The same pattern applies — can be added incrementally using the same `entity_versions` table and `versioned_etag` decorator.

**Global documents caching**: `global_docs/list`, `global_docs/{id}`, etc. Same pattern, lower priority (less frequently accessed than conversation data).

**User preferences caching**: `get_user_preference`, `get_user_detail`. Small payloads, called once per session. Low value.

**Slash command / model catalog caching**: Already effectively cached within a page session. Low value.

**Offline data access**: Would require pre-populating the cache and handling offline mutations. Different architecture entirely.

**Real-time push (SSE/WebSocket for live sync)**: The version-checking approach checks freshness on each request. For live updates (seeing a message appear without switching away/back), you'd need a push channel. The versioning infrastructure built here would complement a push system — the push notification could include the new version number, and the client would know which scope to re-fetch.

**Delta/incremental responses**: Currently, a version mismatch returns the full response. A more advanced system could return only the diff (e.g., only the new messages since version N). This is complex and can be layered on top of the versioning system later.

**Per-domain conversation list versioning**: Currently `user:{email}:convlist` is shared across domains. If a message is sent in the `code` domain, the `research` domain's list cache is also invalidated. Per-domain versioning (`user:{email}:convlist:{domain}`) would be more precise but adds complexity to mutations that affect cross-domain state (e.g., `delete_conversation` which doesn't know the caller's domain). Can be optimized later if over-invalidation is a measurable problem.

---

## Revision History

| Date | Changes |
|------|---------|
| Initial | Plan created with 7 tasks, 12 GET endpoints, ~45 mutation endpoints, 13 decisions |
