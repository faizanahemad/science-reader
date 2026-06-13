# SQLite Storage Migration Plan

## Status: IN PROGRESS (Phase 1 — Planning Complete)

---

## Motivation & Background

### What This Application Is

A Flask-based chat application (`server.py`) that manages multi-turn conversations with LLMs. Each conversation is a folder in `storage/conversations/{conversation_id}/` containing JSON files, dill pickles, artefact files, and document indices.

### The Current Storage Problem

Per-conversation data is stored as 8–11 separate JSON files, each atomically rewritten on every mutation:

```
storage/conversations/{conv_id}/
├── {conv_id}.index                              # dill pickle of Conversation object
├── {conv_id}-messages.json                      # ALL messages (full rewrite every turn)
├── {conv_id}-messages.json.bak                  # backup
├── {conv_id}-memory.json                        # title, summary, metadata
├── {conv_id}-artefacts.json                     # artefact metadata list
├── {conv_id}-artefact_message_links.json        # message→artefact mapping
├── {conv_id}-uploaded_documents_list.json       # document references
├── {conv_id}-message_attached_documents_list.json
├── {conv_id}-conversation_settings.json         # per-conversation config
├── {conv_id}-message_search_index.json          # BM25 index (rebuilt per message)
├── {conv_id}-indices.partial                    # dill: FAISS embeddings
├── {conv_id}-raw_documents_index.partial        # dill: document index structures
└── artefacts/                                   # artefact content files
```

### Performance (Benchmarked)

| Operation | JSON (current) at 500 msgs (1MB) | SQLite | Speedup |
|-----------|----------------------------------|--------|---------|
| Append 2 messages | 8.9ms | 0.4ms | 22x |
| Edit 1 message | 8.3ms | 0.004ms | 2000x |
| Delete 1 message | 14.1ms | 0.07ms | 200x |
| Show/hide 1 message | 9.8ms | 0.005ms | 1900x |
| Batch delete 10 | 20.3ms | 0.2ms | 100x |
| Load all messages | 1.9ms | 0.8ms | 2.5x |

At median conversation size (14KB, ~10 messages) the difference is negligible. At P99 (1.3MB, ~200 messages) and power-user conversations (1.9MB, ~500 messages), it's substantial.

### Structural Problems

1. **No partial updates** — changing one character in one message rewrites all messages
2. **File proliferation** — 167 conversations = 2000+ files in storage directory
3. **FileLock contention** — separate locks per field; no transaction semantics across fields
4. **Manual search index** — `message_search_index.json` rebuilt on every message (yet another full rewrite)
5. **In-memory state loss** — `pinned_claims` (user-visible) lost on server restart
6. **Concurrent access** — `remember_tokens.json` uses FileLock (single-writer bottleneck for auth)
7. **Dill fragility** — critical conversation state (`_memory_pad`, `_domain`, `_flag`, `_archived`) survives only in a binary dill pickle with zero recovery path if corrupted
8. **Dual visibility flags** — `show_hide` (string) and `user_hidden` (bool) are two fields for the same concept; only one is read, causing a silent bug
9. **32-bit message_id** — `mmh3.hash` produces 32-bit IDs; birthday collision at ~65k messages; same text always produces same ID

---

## Goals

1. Migrate all high-value JSON stores to SQLite for O(1) mutations
2. Eliminate the dill `.index` blob for conversation metadata (move all durable state to SQLite)
3. Replace the manual BM25 search index with SQLite FTS5 (eliminate a subsystem)
4. Persist currently-volatile in-memory state (`pinned_claims`)
5. Consolidate per-conversation files: from 8–11 JSON + dill → 1 SQLite + dill (for embeddings only)
6. Fix data model bugs (dual visibility, 32-bit IDs, running_summary leak, dill-only state)
7. Lazy migration: old conversations auto-migrate on first access; no downtime
8. Never break existing storage: new system coexists; JSON kept as backup

## Non-Goals

- Migrating FAISS embedding indices out of dill (numpy arrays are not relational)
- Replacing diskcache (it uses SQLite internally already)
- Changing the frontend API contract
- Multi-user database sharing (conversations remain per-user isolated)

---

## Architecture Decisions

### One SQLite DB Per Conversation

Each conversation gets `conversation.db` in its existing storage folder.

**Why:**
- Matches existing isolation (one folder per conversation)
- Fork/delete/backup = file operations on one DB
- WAL mode optimized for single-writer
- No unbounded growth of a shared DB
- Migration is incremental (per-conversation)

**Rejected:** One shared DB per user — cross-conversation queries already served by `search_index.db`; single DB requires conversation_id in every query; delete requires DELETE+VACUUM.

### Eliminating the Dill `.index` Blob

The `.index` dill pickle currently stores the entire `Conversation` object (minus `store_separate` fields). This is fragile, opaque, and prevents recovery of critical state.

**What's in the dill blob today (24 attributes):**

| Attribute | Type | Durable? | Action |
|-----------|------|----------|--------|
| `conversation_id` | str | Identity | Keep in dill (needed for load_local) |
| `user_id` | str (= email) | Identity | Keep in dill |
| `_storage` | str (path) | Derived | Keep in dill (set on load) |
| `_stateless` | bool | Config | Move to `settings` table |
| `_domain` | str | **HIGH VALUE** | Move to `memory` table |
| `_flag` | str/None | **HIGH VALUE** | Move to `memory` table |
| `_archived` | bool | **HIGH VALUE** | Move to `memory` table |
| `_auto_archive_exempt` | bool | Durable | Move to `memory` table |
| `_archive_source` | str/None | Durable | Move to `memory` table |
| `_last_opened_at` | datetime | Durable | Move to `memory` table |
| `_access_log` | List[str] | Durable (30-day window) | Move to `memory` table |
| `_memory_pad` | str | **HIGH VALUE** (user knowledge) | Move to `memory` table |
| `_context_data` | dict | Transient (resets on restart) | Drop from dill; initialize fresh |
| `_next_question_suggestions` | list | Transient UI state | Drop from dill; initialize empty |
| `_running_summary` | str | Cache of memory[-1] | Drop from dill; derive on read |
| `_doc_infos` | str | Cache (rebuilt from docs) | Drop from dill; derive on read |
| `_request_tools_expansions` | int | Per-request counter | Drop from dill; always 0 |
| `_opencode_client` | OpencodeClient | **Non-serializable** (requests.Session) | Drop from dill; lazy-init |
| `_opencode_session_manager` | SessionManager | Has lambda refs | Drop from dill; lazy-init |
| `doc_infos` | property alias | Redundant | N/A |
| `memory_pad` | property alias | Redundant | N/A |
| `next_question_suggestions` | property alias | Redundant | N/A |
| `running_summary` | property alias | Redundant | N/A |
| `stateless` | property alias | Redundant | N/A |

**After migration, the dill blob contains ONLY:**
- `conversation_id`, `user_id`, `_storage` — the 3 identity fields needed to locate and open the SQLite DB

Everything else either moves to SQLite or is transient/derived. The dill blob becomes a ~200-byte stub that's effectively disposable — if it corrupts, we can reconstruct it from `conversation.db` + the folder path.

**Long-term:** Once all conversations are migrated, `save_local()` can be replaced with a `metadata.json` file containing just `{conversation_id, user_id}` — eliminating dill entirely for conversation objects. The `.index` file would only remain for `DocIndex` objects (embedding vectors).

---

## Complete Storage Inventory

### What's Already in SQLite (No Action Needed)

| Database | Location | Tables | Purpose |
|----------|----------|--------|---------|
| `users.db` | `storage/users/` | 14 tables | Users, conversations, workspaces, doubts, docs, scripts, workflows, pinned messages, similarity cache |
| `search_index.db` | `storage/users/` | 3 (2 FTS5) | Cross-conversation full-text search |
| `pkb.sqlite` | `storage/users/` | ~12 tables | Personal Knowledge Base (claims, entities, contexts) |
| `tool_call_history.sqlite` | `storage/users/` | 1 table | MCP tool invocation audit |
| diskcache | `storage/cache/` | Internal SQLite | Function result caching (@CacheResults) |

### What Migrates to SQLite (This Plan)

| Store | Current Location | Issue | New Location |
|-------|-----------------|-------|--------------|
| messages | `{conv}-messages.json` | Full rewrite every turn | `conversation.db` messages table |
| artefacts | `{conv}-artefacts.json` | Full rewrite on create/edit | `conversation.db` artefacts table |
| artefact_message_links | `{conv}-artefact_message_links.json` | Full rewrite | `conversation.db` artefact_links table |
| memory | `{conv}-memory.json` | Updated every turn | `conversation.db` memory table |
| conversation_settings | `{conv}-conversation_settings.json` | Occasional writes | `conversation.db` settings table |
| uploaded_documents_list | `{conv}-uploaded_documents_list.json` | Append on upload | `conversation.db` documents table |
| message_attached_documents_list | `{conv}-message_attached_documents_list.json` | Append | `conversation.db` documents table |
| message_search_index | `{conv}-message_search_index.json` | Entire subsystem rebuilt per msg | **Eliminated** — replaced by FTS5 triggers |
| todo | `storage/todo.json` or per-conv | Full rewrite | `conversation.db` todos table |
| remember_tokens | `storage/users/remember_tokens.json` | Concurrent auth access | `users.db` remember_tokens table |
| pinned_claims | In-memory dict (lost on restart) | **Data loss on restart** | `users.db` pinned_claims table |
| _memory_pad, _domain, _flag, etc. | Dill blob only | No recovery if corrupt | `conversation.db` memory table |

### What Stays As Files (Not Migrating)

| Store | Why Keep As-Is |
|-------|---------------|
| `{conv}-indices.partial` (dill) | FAISS/numpy arrays — not relational data |
| `{conv}-raw_documents_index.partial` (dill) | Same |
| `{doc_id}.index` (DocIndex dill) | Complex object graph with embeddings |
| `artefacts/{filename}` | Content files (markdown, code) — filesystem is correct for these |
| `images/`, `audio_messages/` | Binary media files |
| `_sha256_index.json` | Low priority; small file, infrequent writes |
| `prompts.json` | Config file, not high-frequency |
| `command_cache.json` (restart_server) | Infrastructure, not user data |
| `interview_sessions/*.json` | Ephemeral/temp |

### In-Memory Caches (Action Items)

| Cache | Action |
|-------|--------|
| `pinned_claims` (server.py) | Move to `users.db` (this plan) |
| `conversation_cache` (200 items) | Keep as-is (backed by disk) |
| `process_youtube_video` (1000 items, expensive) | Future: switch to diskcache |
| `web_scrape_page` (100 items) | Future: switch to diskcache |
| `prompt_cache` | Keep (rebuilt from file on restart) |

---

## Data Model Issues & Fixes

### Issue 1: Redundant Fields Per Message

Every message stores `user_id` and `conversation_id` — ALWAYS identical for all messages in a conversation.

**Fix:** Drop both. The conversation.db IS the conversation.

### Issue 2: Dual Visibility Flags

- `show_hide_message()` writes `msg["show_hide"] = "show"/"hide"` (string)
- `batch_show_hide_messages()` writes `msg["user_hidden"] = True/False` (bool)
- `get_message_summaries()` reads ONLY `show_hide` — batch-hide is silently broken

**Fix:** Single `hidden INTEGER DEFAULT 0`. Both operations write the same column.

### Issue 3: message_id is 32-bit mmh3

`mmh3.hash(conversation_id + user_id + text, signed=False)` = 32-bit unsigned int. Birthday collision at ~65k messages. Same text = same ID always.

**Fix:** New messages get `uuid4().hex`. Migrated messages keep old IDs.

### Issue 4: Config Blob Oversized

Entire UI state (20+ keys incl. link_context, search results) stored per model message. Never read back.

**Fix:** Extract `model` and `temperature` as columns. Store only non-default config keys in `metadata` JSON.

### Issue 5: running_summary Unbounded Growth

`memory["running_summary"]` is `List[str]` — appends one string per turn, only `[-1]` is ever consumed. Dead weight.

**Fix:** Store only last 3 entries max.

### Issue 6: Critical State in Dill-Only

`_memory_pad`, `_domain`, `_flag`, `_archived` — no recovery if `.index` corrupts.

**Fix:** Move all to `memory` table in SQLite.

### Issue 7: artefact_message_links is 1:1

Dict structure `{message_id → {artefact_id}}` — but one message can create multiple artefacts.

**Fix:** Many-to-many `artefact_links` table with composite PK.

### Issue 8: conversation_friendly_id Dual-Write

Stored in both memory dict AND `UserToConversationId` table. No UNIQUE constraint. Race condition.

**Fix:** Single authoritative source (users.db) with UNIQUE constraint.

### Issue 9: Redundant Indexes in users.db

4 indexes duplicate PKs (waste write I/O). 1 needed index missing.

**Fix:** Drop 4, add 1 + UNIQUE on friendly_id.

### Issue 10: user_id Naming Confusion

`Conversation.user_id` is set to `email` (not a UUID). Misleading name throughout codebase.

**Impact:** No schema change needed (we just don't carry it to message rows). Document the semantics.

---

## Final Schema

### Per-Conversation: `conversation.db`

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

-- Schema version for future migrations
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version VALUES (1);

-- Messages
CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    position INTEGER NOT NULL,
    role TEXT NOT NULL,                    -- 'user' or 'model'
    text TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,    -- 0=visible, 1=hidden (unified)
    model TEXT,                           -- model name (NULL for user messages)
    temperature REAL,                     -- (NULL for user messages)
    answer_tldr TEXT,
    answer_keywords TEXT,                 -- JSON: {entities, topics, technical_terms, general_terms}
    message_short_hash TEXT,
    metadata TEXT,                        -- JSON blob: display_attachments, generated_images, user_ask_*, slim config
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);
CREATE INDEX idx_msg_position ON messages(position);
CREATE INDEX idx_msg_hash ON messages(message_short_hash) WHERE message_short_hash IS NOT NULL;

-- Artefacts metadata (content stays on filesystem)
CREATE TABLE artefacts (
    artefact_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    filetype TEXT,
    size_bytes INTEGER,
    metadata TEXT,                         -- JSON blob for future fields
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);

-- Many-to-many: which messages created/modified which artefacts
CREATE TABLE artefact_links (
    message_id TEXT NOT NULL,
    artefact_id TEXT NOT NULL,
    link_type TEXT DEFAULT 'created',     -- 'created', 'modified', 'referenced'
    PRIMARY KEY (message_id, artefact_id)
);
CREATE INDEX idx_artlink_artefact ON artefact_links(artefact_id);

-- Key-value store for conversation metadata (replaces memory.json + dill blob state)
CREATE TABLE memory (
    key TEXT PRIMARY KEY,
    value TEXT                             -- JSON-encoded value
);
-- Expected keys: title, last_updated, running_summary, conversation_friendly_id,
--   title_force_set, created_at, memory_pad, domain, flag, archived,
--   auto_archive_exempt, archive_source, last_opened_at, access_log

-- Key-value store for user-configurable conversation settings
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT                             -- JSON-encoded value
);
-- Expected keys: model_overrides, opencode_config, auto_doubt_categories

-- Document references (uploaded + per-message attached)
CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,                -- 'uploaded' or 'attached'
    doc_storage TEXT,                      -- filesystem path to DocIndex
    doc_source TEXT,                       -- original URL or file path
    display_name TEXT,
    metadata TEXT,                         -- JSON blob for extras
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec'))
);

-- Per-conversation todo items
CREATE TABLE todos (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'done', 'cancelled'
    position INTEGER,
    metadata TEXT,
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);

-- Full-text search on messages (replaces message_search_index.json entirely)
CREATE VIRTUAL TABLE messages_fts USING fts5(
    text,
    content=messages,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

-- Auto-sync triggers (FTS stays in sync without application code)
CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER messages_au AFTER UPDATE OF text ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.rowid, new.text);
END;
```

### Changes to `users.db` (Shared)

```sql
-- Replace remember_tokens.json
CREATE TABLE IF NOT EXISTS remember_tokens (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rt_email ON remember_tokens(email);
CREATE INDEX IF NOT EXISTS idx_rt_expires ON remember_tokens(expires_at);

-- Replace in-memory pinned_claims dict
CREATE TABLE IF NOT EXISTS pinned_claims (
    conversation_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    user_email TEXT NOT NULL,
    pinned_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (conversation_id, claim_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_conv ON pinned_claims(conversation_id);

-- Fix indexes
DROP INDEX IF EXISTS idx_User_email_doc_conversation;   -- redundant (prefix of UNIQUE)
DROP INDEX IF EXISTS idx_UserDetails_email;              -- IS the PK
DROP INDEX IF EXISTS idx_ConversationIdToWorkspaceId_conversation_id;  -- IS the PK
DROP INDEX IF EXISTS idx_WorkspaceMetadata_workspace_id;              -- IS the PK

CREATE INDEX IF NOT EXISTS idx_utci_conversation_id
    ON UserToConversationId(conversation_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_utci_friendly_id
    ON UserToConversationId(user_email, conversation_friendly_id)
    WHERE conversation_friendly_id IS NOT NULL;
```

---

## Migration Mapping (Old → New)

| Old Location | Old Field | New Location | Transformation |
|---|---|---|---|
| messages.json | `msg["user_id"]` | **Dropped** | Redundant |
| messages.json | `msg["conversation_id"]` | **Dropped** | Redundant |
| messages.json | `msg["sender"]` | `messages.role` | Renamed |
| messages.json | `msg["show_hide"]` | `messages.hidden` | "show"→0, "hide"→1 |
| messages.json | `msg["user_hidden"]` | `messages.hidden` | OR'd: True→1 |
| messages.json | `msg["config"]["main_model"]` | `messages.model` | Extracted |
| messages.json | `msg["config"]` (full) | `messages.metadata` | Slimmed: keep only non-defaults |
| messages.json | `msg["display_attachments"]` | `messages.metadata.display_attachments` | Nested in JSON |
| messages.json | `msg["generated_images"]` | `messages.metadata.generated_images` | Nested in JSON |
| messages.json | `msg["user_ask_tldr"]` | `messages.metadata.user_ask_tldr` | Nested in JSON |
| messages.json | `msg["user_ask_keywords"]` | `messages.metadata.user_ask_keywords` | Nested in JSON |
| memory.json | `memory["running_summary"]` | `memory` key='running_summary' | **Trim to last 3** |
| memory.json | all other keys | `memory` table rows | 1:1 key→row |
| dill .index | `_memory_pad` | `memory` key='memory_pad' | Move from dill |
| dill .index | `_domain` | `memory` key='domain' | Move from dill |
| dill .index | `_flag` | `memory` key='flag' | Move from dill |
| dill .index | `_archived` | `memory` key='archived' | Move from dill |
| dill .index | `_auto_archive_exempt` | `memory` key='auto_archive_exempt' | Move from dill |
| dill .index | `_archive_source` | `memory` key='archive_source' | Move from dill |
| dill .index | `_last_opened_at` | `memory` key='last_opened_at' | Move from dill |
| dill .index | `_access_log` | `memory` key='access_log' | Move from dill |
| dill .index | `_context_data` | **Dropped** | Transient (reinit on load) |
| dill .index | `_next_question_suggestions` | **Dropped** | Transient |
| dill .index | `_running_summary` | **Dropped** | Derived from memory |
| dill .index | `_doc_infos` | **Dropped** | Derived from docs |
| dill .index | `_opencode_client` | **Dropped** | Lazy-init; non-serializable |
| dill .index | `_opencode_session_manager` | **Dropped** | Lazy-init; has lambdas |
| dill .index | `_request_tools_expansions` | **Dropped** | Per-request; always 0 |
| conversation_settings.json | all keys | `settings` table rows | 1:1 key→row |
| uploaded_documents_list.json | `(doc_id, storage, source, name)` | `documents` rows | Tuple → columns |
| message_attached_documents_list.json | `(doc_id, storage, source)` | `documents` rows (type='attached') | Same |
| artefacts.json | list of dicts | `artefacts` rows | 1:1 |
| artefact_message_links.json | `{msg_id: {artefact_id, idx}}` | `artefact_links` rows | Dict → rows |
| message_search_index.json | BM25 index | **Eliminated** | FTS5 triggers auto-maintain |
| todo.json | items list | `todos` rows | 1:1 |
| remember_tokens.json | `{token: {email, dates}}` | `users.db` remember_tokens | Dict → rows |
| server.py pinned_claims dict | `{conv_id: set(claim_id)}` | `users.db` pinned_claims | Dict → rows |

---

## ConversationStore API

```python
class ConversationStore:
    """Per-conversation SQLite wrapper. One instance per Conversation object."""
    
    def __init__(self, db_path: str):
        """Open/create DB with WAL mode. Create tables if needed."""
    
    def close(self):
        """Close connection. Called by Conversation.__del__ or explicit cleanup."""
    
    def is_empty(self) -> bool:
        """True if no messages exist (migration not yet run)."""
    
    def schema_version(self) -> int:
        """Current schema version for future ALTER TABLE migrations."""
    
    # === Messages ===
    def get_messages(self, include_hidden: bool = True) -> list[dict]:
        """All messages ordered by position. Returns list of dicts matching old format."""
    
    def get_message(self, message_id: str) -> dict | None:
        """Single message by ID."""
    
    def append_messages(self, messages: list[dict]):
        """Append messages at end. Assigns position = max+1."""
    
    def edit_message(self, message_id: str, text: str):
        """Update message text. Updates updated_at."""
    
    def delete_message(self, message_id: str):
        """Hard delete one message."""
    
    def delete_messages_batch(self, message_ids: list[str]):
        """Hard delete multiple messages."""
    
    def set_hidden(self, message_id: str, hidden: bool):
        """Show/hide one message."""
    
    def set_hidden_batch(self, message_ids: list[str], hidden: bool):
        """Show/hide multiple messages."""
    
    def move_messages(self, message_ids: list[str], direction: str):
        """Move selected messages up/down by swapping positions."""
    
    def overwrite_messages(self, messages: list[dict]):
        """Full replace (used by fork, insert-between). DELETE all + INSERT."""
    
    def search_messages(self, query: str, limit: int = 20) -> list[dict]:
        """FTS5 search. Returns matching messages with rank."""
    
    def message_count(self) -> int:
        """Fast COUNT(*)."""
    
    # === Artefacts ===
    def get_artefacts(self) -> list[dict]:
    def get_artefact(self, artefact_id: str) -> dict | None:
    def add_artefact(self, artefact: dict):
    def update_artefact(self, artefact_id: str, **updates):
    def delete_artefact(self, artefact_id: str):
    
    # === Artefact Links ===
    def get_artefact_links(self) -> dict[str, list[str]]:
        """Returns {message_id: [artefact_id, ...]}."""
    def get_links_for_artefact(self, artefact_id: str) -> list[str]:
        """Returns [message_id, ...]."""
    def add_link(self, message_id: str, artefact_id: str, link_type: str = 'created'):
    def remove_links_for_message(self, message_id: str):
    def remove_links_for_artefact(self, artefact_id: str):
    
    # === Memory (key-value) ===
    def get_memory(self) -> dict:
        """All memory keys as a dict."""
    def get_memory_key(self, key: str) -> Any:
        """Single key, JSON-decoded."""
    def set_memory(self, updates: dict):
        """Upsert multiple keys."""
    def set_memory_key(self, key: str, value: Any):
        """Upsert single key."""
    
    # === Settings (key-value) ===
    def get_settings(self) -> dict:
    def set_settings(self, updates: dict):
    def set_settings_key(self, key: str, value: Any):
    
    # === Documents ===
    def get_documents(self, doc_type: str = None) -> list[dict]:
    def add_document(self, doc_id: str, doc_type: str, doc_storage: str, doc_source: str, display_name: str = None):
    def delete_document(self, doc_id: str):
    def promote_document(self, doc_id: str):
        """Change type from 'attached' to 'uploaded'."""
    
    # === Todos ===
    def get_todos(self) -> list[dict]:
    def add_todo(self, todo: dict):
    def update_todo(self, todo_id: str, **updates):
    def delete_todo(self, todo_id: str):
    
    # === Migration ===
    def import_all(self, messages, artefacts, artefact_links, memory, settings, 
                   uploaded_docs, attached_docs, dill_attrs: dict):
        """Bulk import from old format. Single transaction."""
```

---

## Files Changed

### New Files

| File | Purpose | Lines (est.) |
|---|---|---|
| `database/conversation_store.py` | `ConversationStore` class | ~350 |
| `database/migration.py` | JSON/dill → SQLite migration + rollback commands | ~150 |

### Modified Files

| File | What Changes | Impact |
|---|---|---|
| `Conversation.py` | Add `conversation_store` property; rewire `set_field`/`get_field` for messages, memory, artefacts, settings, documents; update `save_local` to skip migrated fields; property setters for flag/archived/domain write to SQLite | Large (core file) |
| `Conversation.py` | `edit_message`, `delete_message`, `show_hide_message`, `move_messages`, `batch_show_hide_messages`, `delete_messages_batch`, `set_messages_field`, `get_message_ids` | Method bodies change |
| `Conversation.py` | `search_messages` → delegate to `ConversationStore.search_messages` (FTS5) | Simplification |
| `Conversation.py` | Remove `message_search_index` from `store_separate` | 1 line |
| `database/connection.py` | Add `remember_tokens`, `pinned_claims` table DDL; drop redundant indexes; add missing index | ~20 lines |
| `endpoints/auth.py` | Replace `remember_tokens.json` file I/O with SQLite queries | ~40 lines |
| `server.py` | Replace `pinned_claims` global dict with SQLite-backed functions | ~20 lines |
| `endpoints/pkb.py` | Update `_pinned_store()` to use SQLite | ~10 lines |
| `code_common/tools.py` | Update todo read/write to use `ConversationStore` | ~15 lines |

### Untouched

- `DocIndex.py`, `canonical_docs.py`, `YouTubeDocIndex.py` — embedding storage (separate concern)
- `agents/` — no direct message storage
- `endpoints/artefacts.py` — already goes through `Conversation` methods (transparent)
- `interface/` — no backend storage changes affect frontend
- `search_index.py` — cross-conversation index remains separate and complementary

---

## Migration Strategy

### Phase 2: Foundation (No Behavior Change)

1. Create `database/conversation_store.py` with full implementation
2. Create `database/migration.py` with `migrate_conversation(conv)` function
3. Add new tables to `database/connection.py`
4. Add `conversation_store` lazy property to `Conversation` (not yet used for reads/writes)
5. Verify: existing tests still pass; no behavior change

### Phase 3: Implementation (Incremental Cutover)

**Step 3.1: remember_tokens + pinned_claims (independent of conversations)**
- Modify `endpoints/auth.py` to use users.db
- Modify `server.py` / `endpoints/pkb.py` for pinned_claims
- One-time migration: read JSON, insert rows, rename `.json` → `.json.migrated`

**Step 3.2: messages (highest value)**
- In `Conversation`, gate on `conversation_store.is_empty()`:
  - If empty: use old JSON path (not yet migrated)
  - If not empty: use SQLite path
- Trigger migration on first `get_field("messages")` call for a conversation
- Rewire: `edit_message`, `delete_message`, `show_hide_message`, `move_messages`, batch ops

**Step 3.3: memory + settings + dill state**
- During migration: extract dill attrs → write to memory table
- After migration: property setters (`flag`, `archived`, `domain`, etc.) write to SQLite
- `save_local()` becomes a lightweight stub (just identity fields)

**Step 3.4: artefacts + links + documents**
- Same pattern: gate on is_empty, migrate on first access

**Step 3.5: FTS5 + remove message_search_index**
- FTS5 triggers populate automatically during message import
- Delete `_index_messages_for_search()` method
- Remove `message_search_index` from `store_separate`
- `search_messages()` delegates to `ConversationStore.search_messages()`

**Step 3.6: Cleanup**
- Add `python -m database.migration migrate_all <users_dir>` — forces migration of all conversations
- Add `python -m database.migration rollback <conv_id>` — restores from .migrated files
- Remove dead code paths (old JSON branches) after all conversations confirmed migrated

### Rollback Safety

- JSON files renamed to `.json.migrated` (not deleted)
- Code revert + rename `.migrated` → `.json` = full rollback
- `python -m database.migration rollback` automates this
- SQLite DB is ignored when JSON files are present (JSON takes precedence if both exist)

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Bug corrupts data during migration | JSON kept as .migrated backup; rollback command available |
| SQLite locked during long operation | WAL mode + busy_timeout=5000ms; all ops are sub-ms |
| Schema needs changes later | `schema_version` table; migrations run on DB open |
| Connection leak → stale file lock | Context manager pattern; `close()` in `__del__` |
| Process crash mid-transaction | WAL auto-rollback (SQLite guarantee) |
| Large messages (>1MB text) | SQLite handles multi-MB TEXT; no row size limit |
| Two code paths during transition | Gate on `is_empty()`; clear ownership of each path |
| `fork_from_message` needs full rewrite | `overwrite_messages()` handles this case explicitly |
| Cross-conversation search index not updated | `search_index.py` backfill still works (it loads conversations normally) |

---

## Benefits Summary (After Full Migration)

| Metric | Before | After |
|---|---|---|
| Edit 1 message (500 msgs) | 8.3ms | 0.004ms |
| Delete 1 message | 14.1ms | 0.07ms |
| Show/hide message | 9.8ms | 0.005ms |
| Append 2 messages | 8.9ms | 0.4ms |
| Batch delete 10 | 20.3ms | 0.2ms |
| Load all messages | 1.9ms | 0.8ms |
| Files per conversation | 11 JSON + 3 dill + backups | 1 SQLite + 1-2 dill (embeddings only) |
| Message search | Custom BM25 (manual rebuild per msg) | FTS5 (auto-maintained triggers) |
| Concurrency | FileLock (blocks readers) | WAL (concurrent reads during write) |
| Crash recovery | .bak file (manual) | WAL replay (automatic) |
| pinned_claims on restart | **Lost** | Persisted |
| _memory_pad on .index corruption | **Lost permanently** | Recoverable from SQLite |
| remember_tokens | Single-writer FileLock | Row-level concurrent access |
| Dill blob dependency | 24 attrs, non-serializable objects | 3 identity fields (disposable) |

---

## Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| JSONL (append-only) | Doesn't help edit/delete; requires replay; compaction adds complexity |
| Per-message files | 500 open() on load; directory overhead; index file bottleneck |
| JSON + append sidecar | Only helps 1 of 6 operations; edit/delete/hide still O(n) |
| One global DB per user | Harder to fork/delete conversations; no isolation benefit |
| PostgreSQL / MySQL | External server; SQLite already used; single-user app |
| Keep JSON + orjson speedup | 3-5x faster serialization but bottleneck is fsync not CPU; doesn't help mutations |
| Remove dill entirely now | DocIndex embeddings (numpy/FAISS) need binary serialization; conversation dill becomes trivial stub but DocIndex dill stays |
