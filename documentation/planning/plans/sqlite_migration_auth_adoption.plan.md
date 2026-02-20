# SQLite Migration, Auth Adoption & Lock Improvement Plan

> **NOTE**: `extension_server.py` referenced in this document has been deprecated. The Chrome extension now uses `server.py` (port 5000). See `documentation/features/extension/` for current architecture.

**Version**: 1.0
**Created**: 2026-02-15
**Status**: Draft
**Scope**: Move Conversation.py data backend to SQLite, adopt extension's JWT auth, eliminate filesystem locks

---

## Table of Contents

1. [Goals & Requirements](#1-goals--requirements)
2. [Current State Analysis](#2-current-state-analysis)
3. [Target SQLite Schema Design](#3-target-sqlite-schema-design)
4. [Migration Strategy](#4-migration-strategy)
5. [Auth Migration](#5-auth-migration)
6. [Lock Elimination](#6-lock-elimination)
7. [Milestone & Task Breakdown](#7-milestone--task-breakdown)
8. [Risk Assessment & Mitigations](#8-risk-assessment--mitigations)
9. [Testing Strategy](#9-testing-strategy)
10. [Files Modified/Created](#10-files-modifiedcreated)

---

## 1. Goals & Requirements

### 1.1 Primary Goals

1. **Move conversation storage from filesystem to SQLite** — Replace the per-conversation directory of JSON/pickle files with structured SQLite tables for all user-visible, canonical data (messages, memory, settings, artefacts metadata, running summaries).
2. **Adopt extension's cleaner auth pattern** — Bring JWT-based authentication from the extension into the main server, supporting dual auth (JWT + session) for backward compatibility. Upgrade password verification to use DB-backed hashes with env fallback.
3. **Eliminate filesystem locks** — Replace the 6 `FileLock` instances in `Conversation.py` and `DocIndex.py` with SQLite transactions. Keep the 5 in-memory `threading.RLock`/`asyncio.Lock` instances as-is.

### 1.2 Design Principles

- **Incremental migration**: Production system must remain functional throughout. No big-bang switchover.
- **Storage abstraction layer**: Build an interface that both filesystem and SQLite backends implement. Swap backends without changing call sites.
- **Canonical vs cache**: SQLite stores the "source of truth" (messages, memory, settings). Binary blobs (FAISS indices, dill pickles) remain on filesystem as rebuildable caches.
- **Backward compatibility**: `get_session_identity()` signature stays unchanged. Existing conversation data is migrated losslessly.

### 1.3 Non-Goals (for this plan)

- Migrating FAISS binary indices into SQLite (they remain on filesystem)
- Full extension UI consolidation (covered in separate plan)
- Multi-worker/gunicorn deployment (follow-up work)

---

## 2. Current State Analysis

### 2.1 Conversation.py Storage

Each conversation creates a directory `storage/conversations/{conversation_id}/` containing:

| File | Format | Content | JSON-Serializable? | Size Range |
|------|--------|---------|---------------------|------------|
| `{id}.index` | Dill pickle | Conversation object (minus store_separate fields) with cached properties: `_running_summary`, `_memory_pad`, `_domain`, `_stateless`, `_flag`, `_context_data`, `_next_question_suggestions`, `_doc_infos` | No | 1-50KB |
| `{id}-memory.json` | JSON | `{title, last_updated, running_summary[], title_force_set, conversation_friendly_id, created_at}` | Yes | 1-500KB |
| `{id}-messages.json` | JSON | List of message dicts: `{message_id, text, sender, user_id, conversation_id, show_hide, config, answer_tldr, message_short_hash}` | Yes | 1KB-50MB |
| `{id}-uploaded_documents_list.json` | JSON | List of tuples: `(doc_id, doc_storage_path, pdf_url)` | Yes | <1KB |
| `{id}-artefacts.json` | JSON | List of artefact metadata dicts | Yes | <10KB |
| `{id}-artefact_message_links.json` | JSON | Dict: `message_id -> {artefact_id, message_index}` | Yes | <5KB |
| `{id}-conversation_settings.json` | JSON | Dict: `{model_overrides, ...}` | Yes | <1KB |
| `{id}-indices.partial` | Dill pickle | FAISS vector indices | No | 10-500MB |
| `{id}-raw_documents.partial` | Dill pickle | Raw document data | No | 1-50MB |
| `{id}-raw_documents_index.partial` | Dill pickle | Raw documents FAISS index | No | 10-500MB |
| `artefacts/{name}-{id}.{ext}` | Various | User-created content files | N/A | 1B-10MB |
| `uploaded_documents/{doc_id}/` | Various | DocIndex sub-directories | Mixed | 10KB-500MB |

**Key property**: `store_separate` defines which fields are stored as separate files: `["indices", "raw_documents", "raw_documents_index", "memory", "messages", "uploaded_documents_list", "artefacts", "artefact_message_links", "conversation_settings"]`

### 2.2 DocIndex.py Storage

Each uploaded document creates `uploaded_documents/{doc_id}/` containing:

| File | Format | Content | JSON-Serializable? |
|------|--------|---------|---------------------|
| `{doc_id}.index` | Dill pickle | DocIndex object (minus store_separate) | No |
| `{doc_id}-indices.partial` | Dill pickle | FAISS indices (summary_index) | No |
| `{doc_id}-raw_data.json` | JSON | Document chunks | Yes |
| `{doc_id}-static_data.json` | JSON | doc_source, doc_filetype, doc_type, doc_text | Yes |
| `{doc_id}-review_data.json` | JSON | Optional review/annotation data | Yes |
| `{doc_id}-_paper_details.partial` | Dill pickle | Optional paper metadata | No |

### 2.3 File Locking Inventory

**Filesystem FileLocks (6 instances — TO BE REPLACED):**

| Location | Lock Key Pattern | Protects | Timeout |
|----------|-----------------|----------|---------|
| `Conversation.save_local()` (line 1781) | `{locks_dir}/{conversation_id}.lock` | Writing pickled Conversation object | 600s |
| `Conversation.set_field()` (line 1947) | `{locks_dir}/{conversation_id}_{field}.lock` | Per-field JSON/pickle writes | 600s |
| `Conversation.persist_current_turn()` (line 3343) | `{locks_dir}/{conversation_id}_message_operations.lock` | Multi-step: append messages + update memory + update summary | 600s |
| `Conversation.show_hide_message()` (line 3109) | `{locks_dir}/{conversation_id}_message_operations.lock` | Modifying message show/hide status | 600s |
| `DocIndex.set_doc_data()` (line 1227) | `{locks_dir}/{doc_id}-{top_key}.lock` | Per-field document data writes | 600s |
| `DocIndex.save_local()` (line 2023) | `{locks_dir}/{doc_id}.lock` | Writing pickled DocIndex object | 600s |

**In-Memory Locks (5 instances — KEEP AS-IS):**

| Location | Lock Type | Protects |
|----------|-----------|----------|
| `common.py` DefaultDictQueue (line 1777) | `threading.RLock` | LRU conversation cache thread safety |
| `common.py` SetQueue (line 1735) | `threading.RLock` | Set-based queue operations |
| `common.py` SetQueueWithCount (line 1856) | `threading.RLock` | Counted set-queue operations |
| `agents/toc_book_agent.py` (line 76, 80) | `asyncio.Lock` | Async book/TOC generation coordination |

### 2.4 Auth Comparison

| Aspect | Main Server (Current) | Extension (Target) |
|--------|----------------------|-------------------|
| Auth type | Flask session cookies + remember-me | Stateless JWT tokens |
| Token format | Flask-managed session ID | `payload_b64.SHA256_signature` |
| Token expiry | Session: 31 days, Remember-me: 30 days | 7 days (configurable) |
| Login endpoint | `POST /login` (form data) | `POST /ext/auth/login` (JSON) |
| Credential check | Only `os.getenv("PASSWORD")` | DB hash (SHA256) → env fallback |
| Auth decorator | `@login_required` → redirect to `/login` | `@require_ext_auth` → JSON 401 |
| Identity access | `session.get("email")` via `get_session_identity()` | `request.ext_user_email` |
| User auto-create | No | Yes (on first login) |
| Password storage | None (env only) | `password_hash` column in `UserDetails` |

### 2.5 Existing DB Schema (users.db)

Tables already in `users.db`:
- `UserToConversationId` (user_email, conversation_id, created_at, updated_at, conversation_friendly_id)
- `UserDetails` (user_email PK, user_preferences, user_memory, created_at, updated_at)
- `ConversationIdToWorkspaceId` (conversation_id PK, user_email, workspace_id, created_at, updated_at)
- `WorkspaceMetadata` (workspace_id PK, workspace_name, workspace_color, domain, expanded, parent_workspace_id, created_at, updated_at)
- `DoubtsClearing` (doubt_id PK, conversation_id, user_email, message_id, doubt_text, doubt_answer, ...)
- `SectionHiddenDetails` ((conversation_id, section_id) PK, hidden)

---

## 3. Target SQLite Schema Design

### 3.1 Design Decisions

1. **Message text in main table**: Messages up to 100KB are well-handled by SQLite overflow pages. Keep `text` in the `messages` table for simplicity. Split only if profiling shows metadata-only scans are bottlenecked by text size.

2. **FAISS/dill blobs stay on filesystem**: Binary blobs (10-500MB) would balloon the DB, slow backups/vacuum, and increase corruption blast radius. Register them in a `conversation_blobs` table for tracking but store on disk.

3. **Running summaries as separate table**: Instead of rewriting a growing JSON array every turn, use a `conversation_running_summaries` table with `(conversation_id, summary_index)` PK. Appends become cheap INSERTs.

4. **Conversation object pickle replaced**: The `.index` dill file stores cached/derived state. After migration, reconstruct `Conversation` objects from canonical DB fields. Derived properties (`_running_summary`, `_memory_pad`, `_long_summary`, etc.) repopulate lazily.

5. **DocIndex canonical data in DB, binary caches on disk**: Store `static_data`, `raw_data` (chunks), and `review_data` in SQLite. Keep FAISS indices and paper details on filesystem.

6. **Optimistic concurrency**: Add `version INTEGER` column to `conversations` table. Bump on every write. Cache can check staleness via version comparison.

7. **WAL mode**: Enable `PRAGMA journal_mode=WAL` for concurrent read/write access. Set `PRAGMA busy_timeout=5000` for write contention.

### 3.2 New Tables (in `users.db` or a new `conversations.db`)

**Decision**: Use a **separate** `conversations.db` file to avoid bloating `users.db` (which is lightweight metadata). This also lets us backup/manage conversation data independently.

```sql
-- conversations.db

-- Core conversation metadata (replaces .index pickle + memory.json metadata)
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    domain TEXT DEFAULT 'assistant',
    title TEXT DEFAULT 'Start the Conversation',
    title_force_set INTEGER DEFAULT 0,
    conversation_friendly_id TEXT,
    stateless INTEGER DEFAULT 0,
    flag TEXT,
    memory_pad TEXT DEFAULT '',
    doc_infos TEXT DEFAULT '',
    context_data_json TEXT,           -- reward system persistent context
    next_question_suggestions_json TEXT, -- JSON array of suggestion strings
    created_at TEXT,
    updated_at TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    storage_path TEXT                  -- path to filesystem directory (for blobs/artefact files)
);

CREATE INDEX IF NOT EXISTS idx_conv_user_email ON conversations (user_email);
CREATE INDEX IF NOT EXISTS idx_conv_domain ON conversations (user_email, domain);
CREATE INDEX IF NOT EXISTS idx_conv_friendly_id ON conversations (user_email, conversation_friendly_id);
CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations (updated_at);

-- Messages (replaces messages.json)
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sender TEXT NOT NULL,              -- 'user' or 'model'
    user_id TEXT,
    text TEXT NOT NULL,
    show_hide TEXT DEFAULT 'show',
    config_json TEXT,                  -- model config used for this response
    answer_tldr TEXT,
    message_short_hash TEXT,
    message_index INTEGER,             -- ordering within conversation
    created_at TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_msg_conversation ON messages (conversation_id);
CREATE INDEX IF NOT EXISTS idx_msg_conv_index ON messages (conversation_id, message_index);
CREATE INDEX IF NOT EXISTS idx_msg_created ON messages (created_at);

-- Running summaries (replaces memory.running_summary[] array)
CREATE TABLE IF NOT EXISTS conversation_running_summaries (
    conversation_id TEXT NOT NULL,
    summary_index INTEGER NOT NULL,
    summary_text TEXT NOT NULL,
    created_at TEXT,
    PRIMARY KEY (conversation_id, summary_index),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);

-- Conversation settings (replaces conversation_settings.json)
CREATE TABLE IF NOT EXISTS conversation_settings (
    conversation_id TEXT PRIMARY KEY,
    settings_json TEXT DEFAULT '{}',
    updated_at TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);

-- Artefact metadata (replaces artefacts.json; files stay on disk)
CREATE TABLE IF NOT EXISTS artefacts (
    artefact_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    name TEXT,
    file_type TEXT,
    file_name TEXT,
    file_path TEXT,                     -- path to actual file on disk
    size_bytes INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_artefact_conv ON artefacts (conversation_id);

-- Artefact-message links (replaces artefact_message_links.json)
CREATE TABLE IF NOT EXISTS artefact_message_links (
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    artefact_id TEXT NOT NULL,
    message_index TEXT,
    PRIMARY KEY (conversation_id, message_id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id),
    FOREIGN KEY (artefact_id) REFERENCES artefacts(artefact_id)
);

-- Uploaded documents metadata (replaces uploaded_documents_list.json)
CREATE TABLE IF NOT EXISTS uploaded_documents (
    doc_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    doc_storage_path TEXT,             -- filesystem path to DocIndex directory
    pdf_url TEXT,
    doc_source TEXT,
    doc_filetype TEXT,
    doc_type TEXT,
    title TEXT,
    short_summary TEXT,
    visible INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_updoc_conv ON uploaded_documents (conversation_id);

-- DocIndex canonical data (replaces static_data.json, raw_data.json, review_data.json)
CREATE TABLE IF NOT EXISTS docindex_data (
    doc_id TEXT NOT NULL,
    data_key TEXT NOT NULL,            -- 'static_data', 'raw_data', 'review_data'
    data_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (doc_id, data_key),
    FOREIGN KEY (doc_id) REFERENCES uploaded_documents(doc_id)
);

-- Binary blob registry (tracks FAISS indices, dill pickles on filesystem)
CREATE TABLE IF NOT EXISTS blob_registry (
    owner_id TEXT NOT NULL,            -- conversation_id or doc_id
    owner_type TEXT NOT NULL,          -- 'conversation' or 'docindex'
    blob_type TEXT NOT NULL,           -- 'indices', 'raw_documents', 'raw_documents_index', '_paper_details'
    file_path TEXT NOT NULL,
    size_bytes INTEGER,
    sha256 TEXT,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (owner_id, owner_type, blob_type)
);

-- Auth: password hashes (extends UserDetails or new table)
-- We add password_hash to existing UserDetails table via ALTER TABLE
```

### 3.3 Schema Modifications to Existing Tables

```sql
-- In users.db: Add password_hash column to UserDetails
ALTER TABLE UserDetails ADD COLUMN password_hash TEXT;
```

---

## 4. Migration Strategy

### 4.1 Overview: Incremental 4-Phase Migration

```
Phase A: Storage Abstraction Layer
  └─ Build interface + FS backend + SQLite backend
  └─ Conversation.py uses interface (FS backend by default)

Phase B: Dual-Write for New Conversations
  └─ New conversations write to both FS and SQLite
  └─ Reads still from FS (SQLite as verification)
  └─ Feature flag per user/globally

Phase C: Background Migration of Old Conversations  
  └─ Idempotent migration script: load from FS → write canonical data to SQLite
  └─ Mark migrated_at timestamp
  └─ Verify consistency (row counts, checksums)

Phase D: SQLite-Primary Reads + FS Cleanup
  └─ Reads switch to SQLite-first, FS fallback
  └─ Eventually remove FS writes for canonical data
  └─ Keep FS for blobs (FAISS, artefact files, doc files)
```

### 4.2 Storage Abstraction Layer

Create `storage/conversation_store.py` with:

```python
class ConversationStore(ABC):
    """Abstract interface for conversation persistence."""
    
    @abstractmethod
    def get_field(self, conversation_id: str, field_name: str) -> Any: ...
    
    @abstractmethod
    def set_field(self, conversation_id: str, field_name: str, value: Any, overwrite: bool = False) -> None: ...
    
    @abstractmethod
    def save_conversation(self, conversation: 'Conversation') -> None: ...
    
    @abstractmethod
    def load_conversation(self, conversation_id: str) -> 'Conversation': ...
    
    @abstractmethod
    def persist_turn(self, conversation_id: str, user_msg: dict, model_msg: dict, 
                     memory_updates: dict, summary: str) -> None: ...
    
    @abstractmethod
    def get_messages(self, conversation_id: str) -> list: ...
    
    @abstractmethod
    def append_messages(self, conversation_id: str, messages: list) -> None: ...

class FilesystemStore(ConversationStore):
    """Current filesystem implementation — wraps existing get_field/set_field/save_local."""
    ...

class SQLiteStore(ConversationStore):
    """New SQLite implementation."""
    ...

class HybridStore(ConversationStore):
    """Reads from SQLite, falls back to filesystem. Writes to both."""
    ...
```

### 4.3 Conversation Object Reconstruction

After SQLite migration, `Conversation.load_local()` is replaced by constructing from DB fields:

**Canonical fields** (loaded from SQLite):
- `conversation_id`, `user_id`, `domain`, `stateless`, `flag`, `memory_pad`, `doc_infos`, `context_data`, `next_question_suggestions`
- Messages, memory/title, running summaries, settings, artefact metadata, uploaded documents list

**Derived/cached fields** (reconstructed lazily):
- `_running_summary` — derived from last entry of `conversation_running_summaries`
- `_brief_summary`, `_long_summary`, `_dense_summary` — on-demand from DocIndex
- `_raw_index`, `_raw_index_small` — loaded from filesystem blobs
- `_text_len`, `_brief_summary_len` — computed on access

**Object pickle (`.index`)** — no longer the source of truth. Can be kept temporarily as a performance cache but is not required.

### 4.4 JSON Corruption Recovery

Current `get_field()` has elaborate recovery:
1. Backup file (`.bak`)
2. Dill partial fallback
3. JSON array prefix salvage
4. JSON object truncation salvage
5. LLM-based JSON repair

**After SQLite migration**: All of this goes away. SQLite transactions are atomic — either the write succeeds or it doesn't. The `_atomic_write_json()`, `_quarantine_corrupt_file()`, `_salvage_json_array_prefix()`, `_attempt_json_salvage()`, `_attempt_json_llm_repair()` methods (~400 lines) become dead code.

### 4.5 Background Migration Script

```python
# migration/migrate_conversations_to_sqlite.py

def migrate_conversation(conversation_id: str, fs_path: str, db: sqlite3.Connection):
    """Idempotently migrate a single conversation from filesystem to SQLite."""
    
    # 1. Check if already migrated
    if conversation_exists_in_db(db, conversation_id):
        return "already_migrated"
    
    # 2. Load from filesystem
    conv = Conversation.load_local(fs_path)
    if conv is None:
        return "load_failed"
    
    # 3. Extract canonical data
    memory = conv.get_field("memory")
    messages = conv.get_field("messages")
    settings = conv.get_field("conversation_settings")
    artefacts = conv.get_field("artefacts")
    artefact_links = conv.get_field("artefact_message_links")
    uploaded_docs = conv.get_field("uploaded_documents_list")
    
    # 4. Write to SQLite in a single transaction
    with db:
        insert_conversation(db, conv, memory)
        insert_messages(db, conversation_id, messages)
        insert_running_summaries(db, conversation_id, memory.get("running_summary", []))
        insert_settings(db, conversation_id, settings)
        insert_artefacts(db, conversation_id, artefacts)
        insert_artefact_links(db, conversation_id, artefact_links)
        insert_uploaded_docs(db, conversation_id, uploaded_docs)
        
        # 5. Register blob files
        register_blobs(db, conversation_id, fs_path)
    
    return "migrated"
```

---

## 5. Auth Migration

### 5.1 Strategy: Dual Auth Bridge

Upgrade `get_session_identity()` to check JWT first, then fall back to Flask session. No call site changes needed (114 usages).

### 5.2 Implementation

**Step 1: Extract `ExtensionAuth` into shared module**

Move `ExtensionAuth` from `extension.py` to a new `auth/jwt_auth.py`:

```python
# auth/jwt_auth.py
class JWTAuth:
    """JWT token generation and verification."""
    
    JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("EXTENSION_JWT_SECRET", secrets.token_hex(32)))
    TOKEN_EXPIRY_HOURS = int(os.getenv("JWT_TOKEN_EXPIRY_HOURS", 168))  # 7 days
    
    @staticmethod
    def generate_token(email: str) -> str: ...
    
    @staticmethod
    def verify_token(token: str) -> dict | None: ...
```

**Step 2: Upgrade `check_credentials()` in `endpoints/auth.py`**

```python
def check_credentials(email: str, password: str) -> bool:
    """
    Validate user credentials.
    Check DB hash first (SHA256), fall back to env PASSWORD.
    """
    from database.users import getUserFromUserDetailsTable
    
    user = getUserFromUserDetailsTable(email, users_dir=get_state().users_dir)
    if user and user.get("password_hash"):
        return hashlib.sha256(password.encode()).hexdigest() == user["password_hash"]
    
    return os.getenv("PASSWORD", "XXXX") == password
```

**Step 3: Upgrade `get_session_identity()` in `endpoints/session_utils.py`**

```python
def get_session_identity() -> Tuple[Optional[str], Optional[str], bool]:
    """
    Return (email, name, loggedin) from JWT token or Flask session.
    JWT checked first (stateless API), then session (browser UI).
    """
    from flask import request
    
    # 1. Check JWT token in Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        from auth.jwt_auth import JWTAuth
        payload = JWTAuth.verify_token(token)
        if payload and "email" in payload:
            email = payload["email"]
            return email, email, True
    
    # 2. Fall back to Flask session
    email = dict(session).get("email", None)
    name = dict(session).get("name", None)
    return email, name, email is not None and name is not None
```

**Step 4: Add JWT login endpoint alongside existing session login**

```python
@auth_bp.route("/api/auth/login", methods=["POST"])
def api_login():
    """JSON-based login returning JWT token (for extension + API clients)."""
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    
    if check_credentials(email, password):
        from auth.jwt_auth import JWTAuth
        token = JWTAuth.generate_token(email)
        ensure_user_in_details(email)
        return jsonify({"token": token, "email": email})
    
    return jsonify({"error": "Invalid credentials"}), 401
```

**Step 5: Add `password_hash` column to `UserDetails`**

Migration in `database/connection.py`:
```python
try:
    cur.execute("ALTER TABLE UserDetails ADD COLUMN password_hash TEXT")
except Exception:
    pass  # Column already exists
```

### 5.3 Decorator Strategy

- **`@login_required`**: Keep for browser routes (redirects to `/login`)
- **`@api_auth_required`**: New decorator for API routes (returns JSON 401)
- Both use `get_session_identity()` internally, so JWT works transparently for both

---

## 6. Lock Elimination

### 6.1 Strategy

Replace filesystem `FileLock` instances with SQLite transactions. Key principles:
- **Never hold transactions during LLM calls** — compute outside, commit atomically
- **Use `BEGIN IMMEDIATE`** for write transactions (prevents deadlocks)
- **Enable WAL mode** for concurrent read/write
- **Optimistic concurrency** via `version` column on `conversations` table

### 6.2 Lock-by-Lock Replacement

**1. `Conversation.save_local()` lock → SQLite transaction**

Before:
```python
lock = FileLock(f"{lock_location}.lock")
with lock.acquire(timeout=600):
    # pickle Conversation object to .index file
```

After:
```python
def save(self):
    # Write canonical fields to SQLite in one transaction
    with self.db.begin_immediate():
        self.db.update_conversation(self.conversation_id, {
            "domain": self.domain,
            "stateless": self.stateless,
            "flag": self.flag,
            "memory_pad": self.memory_pad,
            ...
        })
    # Optionally write .index cache file (no lock needed — it's a cache)
```

**2. `Conversation.set_field()` lock → SQLite transaction**

Before:
```python
lock = FileLock(f"{lock_location}.lock")
with lock.acquire(timeout=600):
    # read JSON, merge/overwrite, write JSON atomically
```

After:
```python
def set_field(self, top_key, value, overwrite=False):
    if top_key in self._sqlite_fields:
        with self.db.begin_immediate():
            # Single UPDATE/INSERT — inherently atomic
            self.store.set_field(self.conversation_id, top_key, value, overwrite)
    elif top_key in self._blob_fields:
        # Blob fields still use filesystem (no lock needed for single-writer)
        self._write_blob(top_key, value)
```

**3. `Conversation.persist_current_turn()` lock → Single SQLite transaction**

This is the most complex lock — it protects a multi-step operation:
1. Read messages, append new user+model messages
2. Read memory, update title/summary
3. Append running summary
4. Update memory pad
5. Save everything

Before:
```python
lock = FileLock(f"{lock_location}.lock")
# LLM calls for summary + next questions happen BEFORE lock
summary = get_async_future(llm, prompt, ...)
next_questions = get_async_future(self.create_next_question_suggestions, ...)

with lock.acquire(timeout=600):
    # Multi-step read-modify-write of messages + memory + summary
```

After:
```python
# LLM calls happen OUTSIDE transaction (same as before)
summary_result = sleep_and_get_future_result(summary)
next_questions_result = sleep_and_get_future_result(next_questions)

# Single atomic transaction for all DB writes
with self.db.begin_immediate():
    # Insert user message
    self.store.insert_message(conversation_id, user_msg)
    # Insert model message
    self.store.insert_message(conversation_id, model_msg)
    # Append running summary
    self.store.append_running_summary(conversation_id, actual_summary)
    # Update conversation metadata (title, updated_at, version bump)
    self.store.update_conversation_metadata(conversation_id, {
        "title": title,
        "updated_at": now,
    })
    # Update settings if changed
    ...
```

**4. `Conversation.show_hide_message()` lock → SQLite UPDATE**

Before:
```python
lock = FileLock(f"{lock_location}.lock")
with lock.acquire(timeout=600):
    messages = self.get_field("messages")
    for m in messages:
        if m["message_id"] == message_id:
            m["show_hide"] = show_hide
    self.set_messages_field(messages, overwrite=True)
```

After:
```python
def show_hide_message(self, message_id, index, show_hide):
    self.store.update_message(message_id, {"show_hide": show_hide})
    # Single row UPDATE — inherently atomic, no lock needed
```

**5-6. DocIndex locks → Mixed approach**

For DocIndex JSON-serializable data (`raw_data`, `static_data`, `review_data`): use SQLite `docindex_data` table.

For DocIndex binary data (`indices`, `_paper_details`): keep filesystem writes. Since DocIndex writes are single-writer (created once during document upload, rarely updated), file locks can be simplified to filesystem `O_EXCL` or simply removed.

### 6.3 SQLite Configuration

```python
# In database initialization
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")     # 5 second wait for locks
conn.execute("PRAGMA synchronous=NORMAL")    # Good balance of safety + speed
conn.execute("PRAGMA foreign_keys=ON")
```

### 6.4 Code to Remove After Migration

Once all conversations are on SQLite, the following becomes dead code (~600 lines):

- `Conversation._atomic_write_json()` (~25 lines)
- `Conversation._quarantine_corrupt_file()` (~15 lines)
- `Conversation._salvage_json_array_prefix()` (~35 lines)
- `Conversation._salvage_json_object_by_truncation()` (~15 lines)
- `Conversation._attempt_json_salvage()` (~30 lines)
- `Conversation._attempt_json_llm_repair()` (~130 lines)
- `Conversation._apply_llm_json_patch_ops()` (~140 lines)
- `Conversation._coerce_llm_response_to_text()` (~15 lines)
- `Conversation._llm_repair_log()` (~10 lines)
- `Conversation.clear_lockfile()`, `check_lockfile()`, `check_all_lockfiles()`, `force_clear_all_locks()`, `get_stale_locks()`, `get_lock_status()` (~80 lines)
- `Conversation._get_lock_location()` (~8 lines)
- All FileLock imports and instances
- `endpoints/static_routes.py` lock cleanup code (lines 163-164)

---

## 7. Milestone & Task Breakdown

### M0: Foundation (Days 1-3)

| Task | Description | Files | Acceptance Criteria |
|------|-------------|-------|---------------------|
| **M0.1** | Create `conversations.db` schema + migration in `database/conversation_db.py` | NEW: `database/conversation_db.py` | All tables created, WAL mode enabled, indexes in place |
| **M0.2** | Add `password_hash` column to `UserDetails` | `database/connection.py` | Column exists, existing data unaffected |
| **M0.3** | Create `ConversationStore` abstract interface | NEW: `storage/conversation_store.py` | ABC with all required methods defined |
| **M0.4** | Implement `FilesystemStore` wrapping current behavior | NEW: `storage/filesystem_store.py` | All existing get_field/set_field/save_local/load_local behavior preserved |
| **M0.5** | Implement `SQLiteStore` | NEW: `storage/sqlite_store.py` | Full CRUD for all canonical fields via SQLite |
| **M0.6** | Implement `HybridStore` (read: SQLite → FS fallback; write: both) | NEW: `storage/hybrid_store.py` | Reads from SQLite first, falls back to FS. Writes to both. |

### M1: Auth Migration (Days 3-5)

| Task | Description | Files | Acceptance Criteria |
|------|-------------|-------|---------------------|
| **M1.1** | Extract `JWTAuth` into shared module | NEW: `auth/__init__.py`, `auth/jwt_auth.py` | Token generation + verification working, tests pass |
| **M1.2** | Upgrade `check_credentials()` to check DB hash first | `endpoints/auth.py` | DB hash checked first, env fallback preserved |
| **M1.3** | Upgrade `get_session_identity()` to check JWT first | `endpoints/session_utils.py` | JWT Bearer → identity works, session fallback preserved |
| **M1.4** | Add JSON-based login endpoint `/api/auth/login` | `endpoints/auth.py` | Returns JWT token on success, 401 on failure |
| **M1.5** | Add `@api_auth_required` decorator | `endpoints/auth.py` | Returns JSON 401 instead of redirect for API routes |
| **M1.6** | Wire extension to use main server's `/api/auth/login` | `extension/shared/constants.js`, `extension/shared/api.js` | Extension authenticates against main server |

### M2: Conversation.py Storage Abstraction (Days 5-9)

| Task | Description | Files | Acceptance Criteria |
|------|-------------|-------|---------------------|
| **M2.1** | Replace `Conversation.__init__()` to use `ConversationStore` | `Conversation.py` | Constructor accepts store parameter, creates via store |
| **M2.2** | Replace `Conversation.get_field()` to use store | `Conversation.py` | Field reads go through store interface |
| **M2.3** | Replace `Conversation.set_field()` to use store (remove FileLock) | `Conversation.py` | Field writes go through store, no FileLock |
| **M2.4** | Replace `Conversation.save_local()` to use store (remove FileLock) | `Conversation.py` | Save goes through store, no FileLock |
| **M2.5** | Replace `Conversation.load_local()` to use store | `Conversation.py` | Static method loads from store |
| **M2.6** | Replace `Conversation.persist_current_turn()` to use store (remove FileLock) | `Conversation.py` | Single SQLite transaction replaces multi-file lock |
| **M2.7** | Replace `Conversation.show_hide_message()` to use store (remove FileLock) | `Conversation.py` | Single UPDATE, no FileLock |
| **M2.8** | Replace `Conversation.set_messages_field()` to use store | `Conversation.py` | Messages written via store |
| **M2.9** | Update `DefaultDictQueue` factory to use store-based loading | `common.py`, `endpoints/request_context.py` | Cache creates Conversation objects via store |
| **M2.10** | Replace `Conversation.clone_conversation()` to use store | `Conversation.py` | Clone writes to store instead of FS copy |
| **M2.11** | Replace `Conversation.delete_conversation()` to use store | `Conversation.py` | Delete removes from DB + FS blobs |

### M3: DocIndex Storage Abstraction (Days 9-11)

| Task | Description | Files | Acceptance Criteria |
|------|-------------|-------|---------------------|
| **M3.1** | Create `DocIndexStore` interface and `SQLiteDocIndexStore` | NEW: `storage/docindex_store.py` | CRUD for docindex canonical data |
| **M3.2** | Replace `DocIndex.get_doc_data()` for JSON-serializable keys | `DocIndex.py` | `raw_data`, `static_data`, `review_data` read from SQLite |
| **M3.3** | Replace `DocIndex.set_doc_data()` for JSON-serializable keys (remove FileLock) | `DocIndex.py` | JSON keys written to SQLite, no FileLock |
| **M3.4** | Replace `DocIndex.save_local()` (remove FileLock for canonical data) | `DocIndex.py` | Canonical fields in SQLite, binary caches on FS |
| **M3.5** | Replace `DocIndex.load_local()` | `DocIndex.py` | Load from SQLite + FS blobs |
| **M3.6** | Register blob files in `blob_registry` table | `DocIndex.py` | FAISS indices tracked in DB, stored on FS |

### M4: Background Migration + Hybrid Mode (Days 11-14)

| Task | Description | Files | Acceptance Criteria |
|------|-------------|-------|---------------------|
| **M4.1** | Create idempotent migration script | NEW: `migration/migrate_conversations.py` | Migrates one conversation from FS to SQLite |
| **M4.2** | Create batch migration runner with progress tracking | NEW: `migration/batch_migrate.py` | Processes all conversations, logs progress, handles errors |
| **M4.3** | Add migration verification (consistency check) | NEW: `migration/verify_migration.py` | Compares FS vs SQLite data for each conversation |
| **M4.4** | Add feature flag for storage backend selection | `endpoints/state.py`, `server.py` | `STORAGE_BACKEND=fs|sqlite|hybrid` env var |
| **M4.5** | Wire `HybridStore` as default for canary testing | `server.py` | Hybrid mode reads SQLite first, falls back to FS |

### M5: Cleanup & Dead Code Removal (Days 14-16)

| Task | Description | Files | Acceptance Criteria |
|------|-------------|-------|---------------------|
| **M5.1** | Remove JSON corruption recovery code (~400 lines) | `Conversation.py` | Dead code removed, no functional change |
| **M5.2** | Remove lock management code (~80 lines) | `Conversation.py` | `clear_lockfile`, `check_lockfile`, etc. removed |
| **M5.3** | Remove `FileLock` imports from Conversation.py + DocIndex.py | `Conversation.py`, `DocIndex.py` | No `filelock` dependency for conversation operations |
| **M5.4** | Remove lock cleanup from `static_routes.py` | `endpoints/static_routes.py` | Lock directory cleanup code removed |
| **M5.5** | Update `store_separate` property to reflect new storage | `Conversation.py` | Property reflects what goes to SQLite vs FS |
| **M5.6** | Update documentation | `documentation/` | Architecture docs reflect new storage model |

### Execution Dependency Graph

```
M0 (Foundation) ──┬──> M1 (Auth)
                   ├──> M2 (Conversation Store) ──> M3 (DocIndex Store) ──> M4 (Migration)
                   └──────────────────────────────────────────────────────> M5 (Cleanup)
```

M0 must be complete before anything else. M1 can run in parallel with M2. M3 depends on M2's patterns. M4 depends on M2+M3. M5 comes last.

**Estimated Total Effort: 14-18 days**

---

## 8. Risk Assessment & Mitigations

### 8.1 High Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Data loss during migration** | Conversations lost permanently | Idempotent migration with verification. Never delete FS data until SQLite verified. Keep FS as read-only backup for 30+ days. |
| **SQLite write contention under load** | Requests timeout or fail | WAL mode + busy_timeout=5000. Keep transactions short (no LLM calls inside). Monitor `SQLITE_BUSY` errors. |
| **Conversation object reconstruction breaks functionality** | Chat pipeline fails | Keep `.index` pickle as optional cache during transition. Lazy-load derived fields. Extensive testing of reply/persist flow. |

### 8.2 Medium Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Large DB file growth** | Slow backups, potential corruption | Keep FAISS/binary blobs on filesystem. Monitor DB size. Set up periodic `VACUUM`. |
| **Dual-write divergence** | Inconsistent data between FS and SQLite | Add lightweight consistency checker. Log mismatches. Alert on divergence. |
| **Auth migration breaks existing sessions** | Users logged out | Additive change only — JWT added alongside sessions, never replacing. Session cookies continue working. |
| **DefaultDictQueue cache staleness** | Stale conversation state served | Add `version` field comparison. If DB version > cached version, reload from DB. |

### 8.3 Low Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| **FAISS indices become orphaned** | Wasted disk space | `blob_registry` table tracks all blobs. Cleanup script can find unregistered files. |
| **Extension auth secret mismatch** | Extension can't authenticate | Use same `JWT_SECRET` env var for both. Document in deployment. |

---

## 9. Testing Strategy

### 9.1 Unit Tests

| Test Area | Description |
|-----------|-------------|
| `SQLiteStore` CRUD | Test all get/set/delete operations for each table |
| `HybridStore` fallback | Test read-from-SQLite, fallback-to-FS behavior |
| `persist_turn` atomicity | Test that partial failures leave DB in consistent state |
| JWT generation/verification | Test token create, verify, expiry, tampering |
| `get_session_identity()` dual auth | Test JWT path, session path, both-missing path |
| `check_credentials()` DB+env | Test DB hash match, DB hash mismatch, no DB hash + env match |
| Message ordering | Test messages maintain correct order after migration |

### 9.2 Integration Tests

| Test Area | Description |
|-----------|-------------|
| Full conversation flow | Create conversation → send messages → persist → reload → verify |
| Migration roundtrip | Load FS conversation → migrate to SQLite → load from SQLite → compare |
| Concurrent writes | Multiple threads writing to same conversation → no corruption |
| Extension auth against main server | Extension login → JWT → subsequent API calls succeed |

### 9.3 Smoke Tests (Production)

| Test | Trigger |
|------|---------|
| New conversation creation | Verify appears in both FS and SQLite |
| Message persistence | Send message, verify in SQLite |
| Conversation listing | Verify listing from SQLite matches FS |
| Document upload | Upload doc, verify metadata in SQLite |

---

## 10. Files Modified/Created

### New Files

| File | Purpose |
|------|---------|
| `database/conversation_db.py` | conversations.db schema creation + connection management |
| `storage/conversation_store.py` | Abstract `ConversationStore` interface |
| `storage/filesystem_store.py` | FS backend (wraps current behavior) |
| `storage/sqlite_store.py` | SQLite backend |
| `storage/hybrid_store.py` | Hybrid read/write backend |
| `storage/docindex_store.py` | DocIndex storage interface + SQLite implementation |
| `auth/__init__.py` | Auth module init |
| `auth/jwt_auth.py` | Shared JWT auth (extracted from extension.py) |
| `migration/migrate_conversations.py` | Single-conversation migration |
| `migration/batch_migrate.py` | Batch migration runner |
| `migration/verify_migration.py` | Migration verification |

### Modified Files

| File | Changes |
|------|---------|
| `Conversation.py` | Use store interface; remove FileLock; remove JSON recovery code; remove lock management |
| `DocIndex.py` | Use store interface; remove FileLock for JSON fields |
| `common.py` | Update `DefaultDictQueue` factory to use store-based loading |
| `endpoints/auth.py` | Upgrade `check_credentials()`; add JWT login endpoint; add `@api_auth_required` |
| `endpoints/session_utils.py` | Upgrade `get_session_identity()` for dual auth |
| `endpoints/state.py` | Add storage backend feature flag |
| `endpoints/request_context.py` | Update conversation loading to use store |
| `endpoints/static_routes.py` | Remove lock cleanup code |
| `database/connection.py` | Add `password_hash` column migration; create `conversations.db` |
| `server.py` | Initialize storage backend; wire feature flag |
| `extension.py` | Extract `ExtensionAuth` → import from shared `auth/jwt_auth.py` |
| `extension_server.py` | Import auth from shared module |

### Deprecated (Eventually Removed)

| File/Code | Reason |
|-----------|--------|
| `storage/locks/` directory | Filesystem locks no longer needed |
| `Conversation._atomic_write_json()` | SQLite transactions replace this |
| `Conversation._attempt_json_*()` methods | No more JSON corruption possible |
| `Conversation.*lockfile*()` methods | No more file locks |

---

## Appendix A: Conversation.py Properties Mapped to SQLite

| Property | Current Storage | SQLite Target | Notes |
|----------|----------------|---------------|-------|
| `conversation_id` | `.index` pickle | `conversations.conversation_id` | PK |
| `user_id` | `.index` pickle | `conversations.user_email` | |
| `_domain` | `.index` pickle | `conversations.domain` | |
| `_stateless` | `.index` pickle | `conversations.stateless` | |
| `_flag` | `.index` pickle | `conversations.flag` | |
| `_memory_pad` | `.index` pickle | `conversations.memory_pad` | Can be large (12K+ words) |
| `_doc_infos` | `.index` pickle | `conversations.doc_infos` | |
| `_context_data` | `.index` pickle | `conversations.context_data_json` | JSON dict |
| `_next_question_suggestions` | `.index` pickle | `conversations.next_question_suggestions_json` | JSON array |
| `memory.title` | `memory.json` | `conversations.title` | |
| `memory.title_force_set` | `memory.json` | `conversations.title_force_set` | |
| `memory.last_updated` | `memory.json` | `conversations.updated_at` | |
| `memory.created_at` | `memory.json` | `conversations.created_at` | |
| `memory.conversation_friendly_id` | `memory.json` | `conversations.conversation_friendly_id` | |
| `memory.running_summary` | `memory.json` | `conversation_running_summaries` table | List → rows |
| `messages` | `messages.json` | `messages` table | List → rows |
| `conversation_settings` | `conversation_settings.json` | `conversation_settings` table | Dict → JSON column |
| `artefacts` | `artefacts.json` | `artefacts` table | List → rows |
| `artefact_message_links` | `artefact_message_links.json` | `artefact_message_links` table | Dict → rows |
| `uploaded_documents_list` | `uploaded_documents_list.json` | `uploaded_documents` table | List of tuples → rows |
| `indices` | `.partial` dill | `blob_registry` + filesystem | Binary — stays on disk |
| `raw_documents` | `.partial` dill | `blob_registry` + filesystem | Binary — stays on disk |
| `raw_documents_index` | `.partial` dill | `blob_registry` + filesystem | Binary — stays on disk |

---

## Appendix B: Extension DB Schema (Reference)

The extension's SQLite schema (in `extension.db`) serves as a design reference:

```sql
-- ExtensionConversations: id, user_email, title, model, system_prompt, created_at, updated_at, is_pinned, metadata_json
-- ExtensionMessages: id, conversation_id, role, content, model, created_at, token_count, metadata_json
-- ExtensionConversationMemories: id, conversation_id, key, value, created_at, updated_at
-- CustomScripts: id, user_email, name, description, script_content, script_type, is_enabled, ...
-- ExtensionWorkflows: id, user_email, name, description, workflow_data, ...
-- ExtensionSettings: id, user_email, key, value, created_at, updated_at
```

Our schema is more comprehensive (artefacts, running summaries, blob registry, DocIndex data) but follows similar patterns for conversations + messages.
