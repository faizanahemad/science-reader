# SQLite Storage Migration Plan

## Status: IN PROGRESS (Phase 1 — Planning)

## Motivation

The application currently stores per-conversation data as 8–11 separate JSON files per conversation, each rewritten atomically on every mutation. Benchmarking shows:

- **Edit/delete/hide a message** (the most common user action after append): JSON requires full-file rewrite (read all → find → mutate → serialize all → fsync). At 500 messages (1MB file), this takes 8–14ms. SQLite does the same in **0.004–0.07ms** — a 200–2000x improvement.
- **Append 2 messages** (every conversation turn): JSON rewrites the full file. SQLite inserts 2 rows — 20–45x faster.
- **Load all messages**: SQLite is 2–22x faster depending on size (indexed sequential scan vs parse-from-scratch).

Beyond performance, the current architecture has structural problems:
- **File proliferation**: Each conversation creates 8–11 JSON files + 2–3 dill files + backup files. 167 conversations = ~2000+ files in the storage directory.
- **No partial updates**: Changing one field in one message rewrites all messages.
- **FileLock contention**: Separate locks per field per conversation; no transaction semantics across fields.
- **No built-in search**: A separate BM25 index (`message_search_index.json`) is maintained manually, adding another full-rewrite per message.
- **In-memory state loss**: `pinned_claims` (user-visible) is lost on restart with no recovery path.
- **Concurrent access**: Multiple requests hitting the same `remember_tokens.json` use the same FileLock — single-writer bottleneck.

## Goals

1. Migrate high-value JSON stores to SQLite for O(1) mutations
2. Replace the manual BM25 index with SQLite FTS5 (eliminate an entire subsystem)
3. Persist currently-volatile in-memory state (`pinned_claims`)
4. Consolidate per-conversation files into a single DB per conversation
5. Provide lazy migration (old conversations auto-migrate on first access)
6. Never break existing storage — new system coexists until migration completes

## Non-Goals

- Migrating dill pickles (FAISS indices, numpy embeddings, full Conversation object)
- Replacing diskcache (it uses SQLite internally already)
- Changing the API/endpoint layer (same interface, different backend)
- Multi-user database sharing (each user's conversations remain isolated)

## Architecture Decision: One DB Per Conversation

**Decision:** Each conversation gets its own `conversation.db` in its existing storage folder.

**Rationale:**
- Matches the existing isolation model (one folder per conversation)
- No cross-conversation transactions needed
- Backup/delete/fork = file operations on one DB file
- WAL mode works best with single-writer scenarios
- Avoids a single massive DB that grows unbounded
- Migration is per-conversation (lazy, incremental)

**Alternative considered:** One shared DB per user. Rejected because:
- Cross-conversation queries are already handled by `search_index.db`
- A single DB would require conversation_id in every query (overhead)
- Deleting a conversation would require DELETE + VACUUM instead of just removing a file

## Schema

```sql
-- Per-conversation database: {conv_id}/conversation.db
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

-- Messages (the primary win)
CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    position INTEGER NOT NULL,
    role TEXT NOT NULL,                    -- 'user' or 'model'
    text TEXT,
    show_hide TEXT NOT NULL DEFAULT 'show',
    config TEXT,                           -- JSON blob (model, temperature, etc.)
    answer_tldr TEXT,
    answer_keywords TEXT,                  -- JSON blob
    message_short_hash TEXT,
    user_hidden INTEGER DEFAULT 0,        -- soft-delete for user hide
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);
CREATE INDEX idx_msg_position ON messages(position);

-- Artefacts
CREATE TABLE artefacts (
    artefact_id TEXT PRIMARY KEY,
    name TEXT,
    filename TEXT,
    filetype TEXT,
    content_preview TEXT,                  -- first N chars for listing
    metadata TEXT,                         -- JSON blob for all other fields
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);

-- Artefact ↔ Message links
CREATE TABLE artefact_links (
    message_id TEXT NOT NULL,
    artefact_id TEXT NOT NULL,
    link_type TEXT DEFAULT 'created',      -- 'created', 'modified', 'referenced'
    PRIMARY KEY (message_id, artefact_id)
);
CREATE INDEX idx_artlink_artefact ON artefact_links(artefact_id);

-- Memory (key-value store for conversation metadata)
CREATE TABLE memory (
    key TEXT PRIMARY KEY,
    value TEXT                             -- JSON-encoded value
);
-- Keys: title, last_updated, running_summary, conversation_friendly_id,
--        title_force_set, auto_settings, etc.

-- Conversation settings
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT                             -- JSON-encoded value
);

-- Document lists (uploaded + attached)
CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,                -- 'uploaded' or 'attached'
    metadata TEXT,                         -- JSON blob
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec'))
);

-- Todo items (per-conversation)
CREATE TABLE todos (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'done', 'cancelled'
    position INTEGER,
    metadata TEXT,                         -- JSON blob
    created_at REAL NOT NULL DEFAULT (unixepoch('subsec')),
    updated_at REAL
);

-- Message full-text search (replaces message_search_index.json)
CREATE VIRTUAL TABLE messages_fts USING fts5(
    text,
    content=messages,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
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

### Changes to users.db (shared)

```sql
-- remember_tokens (replaces remember_tokens.json)
CREATE TABLE IF NOT EXISTS remember_tokens (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rt_email ON remember_tokens(email);
CREATE INDEX IF NOT EXISTS idx_rt_expires ON remember_tokens(expires_at);

-- pinned_claims (replaces in-memory dict — persists across restarts)
CREATE TABLE IF NOT EXISTS pinned_claims (
    conversation_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    user_email TEXT NOT NULL,
    pinned_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (conversation_id, claim_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_conv ON pinned_claims(conversation_id);
```

## What Changes Where

### New Files

| File | Purpose |
|---|---|
| `database/conversation_store.py` | `ConversationStore` class — per-conversation SQLite operations |
| `database/migration.py` | Lazy JSON→SQLite migration helpers |

### Modified Files

| File | Changes |
|---|---|
| `Conversation.py` | Replace `set_field`/`get_field` for migrated fields with `ConversationStore` methods. Remove `message_search_index` from `store_separate`. Add `conversation_store` lazy property. |
| `database/connection.py` | Add `remember_tokens` and `pinned_claims` table creation to `create_tables()` |
| `endpoints/auth.py` | Replace `remember_tokens.json` read/write with SQLite queries on `users.db` |
| `server.py` | Replace `pinned_claims` global dict with SQLite-backed helper |
| `endpoints/pkb.py` | Update `_pinned_store()` to use SQLite |
| `code_common/tools.py` | Update todo.json read/write to use ConversationStore |

### Untouched Files

- `DocIndex.py` — dill pickles for embeddings (no change)
- `canonical_docs.py` — `_sha256_index.json` (low priority, small file, infrequent writes)
- `agents/interview_simulator_agent*.py` — low priority
- `restart_server/` — `command_cache.json`, `workdir_config.json` (not conversation data)
- `prompts.json` — config file, not high-frequency

## Migration Strategy

### Lazy Per-Conversation Migration

```python
@property
def conversation_store(self) -> ConversationStore:
    """Lazy init + one-time migration from JSON to SQLite."""
    if self._conversation_store is None:
        db_path = os.path.join(self._storage, "conversation.db")
        store = ConversationStore(db_path)
        if store.is_empty():
            # Migrate from JSON files
            self._migrate_json_to_sqlite(store)
        self._conversation_store = store
    return self._conversation_store

def _migrate_json_to_sqlite(self, store: ConversationStore):
    """One-time migration of all JSON fields into SQLite."""
    # Messages
    json_path = os.path.join(self._storage, f"{self.conversation_id}-messages.json")
    if os.path.exists(json_path):
        with open(json_path) as f:
            messages = json.load(f)
        store.import_messages(messages)
    # Artefacts
    # ... same pattern for each field
    # After successful migration, rename .json → .json.migrated (keep as backup)
```

### Rollback Safety

- JSON files are NOT deleted after migration — they're renamed to `.json.migrated`
- If the new code has bugs, revert the code and rename `.migrated` back to `.json`
- A management command `python -m database.migration rollback <conv_id>` restores JSON from SQLite

### Migration Order

1. **remember_tokens** → users.db (no per-conversation migration needed; one-time on server start)
2. **pinned_claims** → users.db (one-time; scan existing conversations for any saved state)
3. **messages** → conversation.db (lazy per-conversation)
4. **artefacts + artefact_links** → conversation.db (lazy, same migration pass)
5. **memory + settings** → conversation.db (lazy, same pass)
6. **documents lists** → conversation.db (lazy, same pass)
7. **message_search_index** → FTS5 triggers (automatic, no explicit migration — triggers populate on INSERT)
8. **todo** → conversation.db (lazy)

## ConversationStore API

```python
class ConversationStore:
    """Per-conversation SQLite database wrapper."""
    
    def __init__(self, db_path: str):
        """Open/create the database with WAL mode."""
    
    def is_empty(self) -> bool:
        """Check if migration has occurred."""
    
    # --- Messages ---
    def get_messages(self) -> list[dict]:
    def append_messages(self, messages: list[dict]):
    def edit_message(self, message_id: str, text: str):
    def delete_message(self, message_id: str):
    def delete_messages_batch(self, message_ids: list[str]):
    def show_hide_message(self, message_id: str, show_hide: str):
    def batch_show_hide(self, message_ids: list[str], show_hide: str):
    def move_messages(self, message_ids: list[str], direction: str):
    def overwrite_messages(self, messages: list[dict]):  # for fork, insert-between
    def search_messages(self, query: str) -> list[dict]:  # FTS5
    def import_messages(self, messages: list[dict]):  # bulk migration
    
    # --- Artefacts ---
    def get_artefacts(self) -> list[dict]:
    def add_artefact(self, artefact: dict):
    def update_artefact(self, artefact_id: str, updates: dict):
    def delete_artefact(self, artefact_id: str):
    
    # --- Artefact Links ---
    def get_artefact_links(self) -> dict:
    def set_artefact_link(self, message_id: str, artefact_id: str, link_type: str = 'created'):
    def delete_artefact_link(self, message_id: str):
    
    # --- Memory ---
    def get_memory(self) -> dict:
    def set_memory(self, updates: dict):
    
    # --- Settings ---
    def get_settings(self) -> dict:
    def set_settings(self, updates: dict):
    
    # --- Documents ---
    def get_documents(self, doc_type: str = None) -> list[dict]:
    def add_document(self, doc_id: str, doc_type: str, metadata: dict = None):
    def delete_document(self, doc_id: str):
    
    # --- Todo ---
    def get_todos(self) -> list[dict]:
    def add_todo(self, todo: dict):
    def update_todo(self, todo_id: str, updates: dict):
    def delete_todo(self, todo_id: str):
    
    # --- Migration ---
    def import_messages(self, messages: list[dict]):
    def import_artefacts(self, artefacts: list[dict]):
    def import_memory(self, memory: dict):
    def import_settings(self, settings: dict):
    def import_documents(self, docs: list, doc_type: str):
    
    def close(self):
```

## Benefits Summary

| Metric | Before (JSON) | After (SQLite) |
|---|---|---|
| Edit 1 message (500 msgs) | 8.3ms | 0.004ms |
| Delete 1 message | 14.1ms | 0.07ms |
| Show/hide message | 9.8ms | 0.005ms |
| Append 2 messages | 8.9ms | 0.4ms |
| Batch delete 10 | 20.3ms | 0.2ms |
| Load all messages | 1.9ms | 0.8ms |
| Files per conversation | 8–11 JSON + 3 dill + backups | 1 SQLite + 2–3 dill |
| Message search | Custom BM25 index (manual rebuild) | FTS5 (auto-maintained via triggers) |
| Concurrent access | FileLock (blocks all readers) | WAL (concurrent reads during write) |
| Crash recovery | .bak file (manual) | WAL replay (automatic) |
| pinned_claims on restart | Lost | Persisted |
| remember_tokens concurrency | Full file rewrite race | Row-level granularity |

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Bug in new code corrupts data | JSON files kept as `.migrated` backup; rollback command available |
| SQLite file locked during long write | WAL mode + busy_timeout=5000ms; operations are sub-ms |
| Schema changes needed later | Version table in each DB; ALTER TABLE migrations on open |
| Connection left open → file lock held | Use context managers; ConversationStore.close() in Conversation.__del__ |
| Process crash mid-transaction | SQLite's WAL automatically rolls back incomplete transactions |
| Large messages (>1MB text) | SQLite handles multi-MB TEXT columns fine; no row size limit |

## Phase 2 Scope (Foundation)

1. Create `database/conversation_store.py` with full `ConversationStore` class
2. Create `database/migration.py` with JSON→SQLite import helpers
3. Add `remember_tokens` + `pinned_claims` tables to `database/connection.py`
4. Add `conversation_store` lazy property to `Conversation` class (does NOT replace existing code yet)
5. Write migration smoke test

## Phase 3 Scope (Implementation)

1. Rewire `messages` operations: `set_messages_field`, `get_field("messages")`, `edit_message`, `delete_message`, `show_hide_message`, `move_messages`, `delete_messages_batch`, `batch_show_hide_messages`
2. Rewire `artefacts` + `artefact_message_links` operations
3. Rewire `memory` + `conversation_settings` + document lists
4. Replace `message_search_index` with FTS5
5. Migrate `remember_tokens.json` → users.db
6. Migrate `pinned_claims` in-memory dict → users.db
7. Migrate `todo.json` → conversation.db
8. Remove `message_search_index` from `store_separate`
9. Update `save_local()` to skip SQLite-managed fields in dill dump
10. Add forced migration command: `python -m database.migration migrate_all <users_dir>`

## Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| JSONL (append-only log) | Doesn't help edit/delete; requires replay on load; compaction logic adds complexity |
| Per-message files | 500 file opens on load; directory overhead; index file becomes bottleneck |
| JSON + sidecar optimization | Only helps append (1 of 6 operations); edit/delete/hide still full-rewrite |
| One global DB for all conversations | Harder to delete/fork conversations; no isolation benefit |
| PostgreSQL/MySQL | Requires external server; SQLite already used in project; single-user app |
| MongoDB/Redis | External dependency; overkill for single-user single-server |
