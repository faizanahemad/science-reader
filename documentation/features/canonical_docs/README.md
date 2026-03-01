# Canonical Document Store

Store a document once, reference it from many conversations. The canonical doc store replaces the old per-conversation storage model where each conversation kept its own copy of uploaded documents. Now every uploaded document lives at a single canonical path under `storage/documents/{user_hash}/{doc_id}/`, and conversations hold lightweight tuple references that point there. Content-based SHA-256 deduplication catches the same file uploaded under different names, so identical content is never indexed twice.

## Architecture Overview

Before this feature, uploading the same PDF to three conversations created three independent copies, each with its own FAISS index, summaries, and metadata. The canonical store inverts that model:

1. **Single canonical copy.** Every document is stored once at `storage/documents/{user_hash}/{doc_id}/`.
2. **Tuple references.** Conversations store `(doc_id, doc_storage, source_url, display_name)` tuples in `uploaded_documents_list`. These tuples point at the canonical path. No file copying happens.
3. **SHA-256 dedup.** A per-user index file maps content hashes to `doc_id` values. If the same file is uploaded again (even under a different filename), the existing index is reused.
4. **Upgrade propagation.** When a FastDocIndex is upgraded to a full DocIndex via the "Analyze" button, the upgrade happens in-place at the canonical path. Every conversation referencing that doc sees the upgraded index on next load, with zero extra work.
5. **Clone is free.** Cloning a conversation copies only the tuple list. No `shutil.copytree`.

## Storage Layout

```
storage/documents/{user_hash}/
    _sha256_index.json            <-- {sha256_hex: doc_id} mapping for dedup
    _sha256_index.json.lock       <-- FileLock protecting the index file
    {doc_id_A}/
        {doc_id_A}.index          <-- dill-pickled DocIndex / FastDocIndex
        indices/                  <-- FAISS vector stores
        raw_data/                 <-- document chunks
        static_data/              <-- source metadata
        review_data/              <-- analysis data
        _paper_details/           <-- paper metadata
        locks/                    <-- per-field locks
    {doc_id_B}/
        ...
```

`{user_hash}` is the MD5 hex digest of the user's email address (matches the convention used by global docs). Each `{doc_id}/` subdirectory is created by `DocIndex.__init__` when it receives the canonical parent as its storage argument.

Legacy per-conversation paths looked like this:

```
storage/conversations/{conv_id}/uploaded_documents/{doc_id}/
```

Documents at legacy paths are migrated to the canonical layout either lazily (on first access) or eagerly (at startup).

## SHA-256 Deduplication

### How It Works

Every user has a JSON index file at `storage/documents/{user_hash}/_sha256_index.json`. This file maps SHA-256 content hashes to `doc_id` values:

```json
{
  "a1b2c3d4e5f6...": "1234567890",
  "f6e5d4c3b2a1...": "9876543210"
}
```

When a local file is uploaded, the system:

1. Computes the SHA-256 hash of the file contents (read in 1 MB chunks).
2. Acquires a per-hash `FileLock` at `.sha_{hash_prefix}.lock` to prevent concurrent uploads of the same content from racing.
3. Looks up the hash in `_sha256_index.json`.
4. If a match is found and the canonical directory still exists on disk, returns the existing path immediately. No indexing happens.
5. If no match, calls the `build_fn` to create a new DocIndex, then registers the hash in the index.

For URL-based uploads (not local files), SHA-256 dedup is skipped. The `doc_id`-level check inside DocIndex still prevents exact-source duplicates.

### The Index File

The index file is read and written under a `FileLock` at `_sha256_index.json.lock`. Writes use atomic replace: content goes to a `.tmp` file first, then `os.replace()` swaps it in (atomic on POSIX). If the index file is missing or corrupted, it resets to an empty dict and logs a warning.

### Dedup Scenarios

| Scenario | Same SHA-256? | Result |
|----------|---------------|--------|
| Same file, same name | Yes | Reuses existing canonical index. No new indexing. |
| Same file, different name | Yes | SHA-256 match catches it. Reuses existing canonical index. |
| Different file, same name | No | New canonical index created. Different `doc_id`. |

## Core API (canonical_docs.py)

### Hash Helpers

| Function | Signature | Description |
|----------|-----------|-------------|
| `compute_file_hash` | `(path: str) -> str` | Returns the SHA-256 hex digest (64 chars) of a local file. Reads in 1 MB chunks. |
| `user_hash` | `(email: str) -> str` | Returns the MD5 hex digest (32 chars) of an email address. Matches the global docs convention. |

### SHA-256 Index Management

| Function | Signature | Description |
|----------|-----------|-------------|
| `register_sha256` | `(docs_folder, u_hash, sha256, doc_id) -> None` | Records a SHA-256 to doc_id mapping. Thread-safe: acquires the index lock internally. |
| `lookup_by_sha256` | `(docs_folder, u_hash, sha256) -> str or None` | Looks up a hash. Returns the `doc_id` if found and the canonical directory still exists on disk, `None` otherwise. |

### Path Helpers

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_canonical_parent` | `(docs_folder, u_hash) -> str` | Returns `<docs_folder>/<user_hash>/`. Does not create the directory. |
| `get_canonical_storage` | `(docs_folder, u_hash, doc_id) -> str` | Returns `<docs_folder>/<user_hash>/<doc_id>/`. Does not create the directory. |
| `is_canonical_path` | `(docs_folder, path) -> bool` | Returns `True` if `path` lives under the canonical docs folder. Used by lazy migration to distinguish old per-conversation paths from already-migrated canonical paths. |

### Core Operations

| Function | Signature | Description |
|----------|-----------|-------------|
| `store_or_get` | `(docs_folder, u_hash, source_path, build_fn) -> str` | The main entry point. Ensures a canonical index exists for the given source. Returns the absolute path to the canonical `doc_id` directory. See "Upload Flow" below for the full sequence. |
| `migrate_doc_to_canonical` | `(docs_folder, u_hash, doc_id, old_storage, source_path="") -> str` | Moves an existing per-conversation doc folder into the canonical store. Also registers the SHA-256 hash. Returns the canonical path, or `old_storage` as a safe fallback if migration fails. |

## Upload Flow

Step-by-step sequence when a document is uploaded to a conversation with `docs_folder` configured:

1. **Endpoint receives file.** The upload endpoint saves the file to `state.pdfs_dir` and calls `conversation.add_fast_uploaded_document(pdf_path, docs_folder=state.docs_folder)` (or `add_uploaded_document` / `add_message_attached_document`).

2. **Compute user hash.** The Conversation method calls `canonical_docs.user_hash(self.user_id)` to get the MD5 of the user's email.

3. **Define build_fn.** A closure is created that calls `create_fast_document_index()` (or `create_immediate_document_index()`) with the canonical parent as storage, sets visibility and display name, calls `save_local()`, and returns the DocIndex.

4. **Call store_or_get.** `canonical_docs.store_or_get(docs_folder, u_hash, pdf_path, build_fn)` runs the dedup pipeline:
   - If `pdf_path` is a local file, compute its SHA-256.
   - Acquire a per-hash `FileLock`.
   - Check `_sha256_index.json` for a match.
   - **Hit:** Return the existing canonical path. Skip indexing entirely.
   - **Miss:** Call `build_fn(canonical_parent)`. DocIndex creates `{doc_id}/` inside the parent. Register the SHA-256 mapping.

5. **Load and return.** The Conversation method calls `DocIndex.load_local(canonical_storage)` to get the index object, then appends a `(doc_id, doc_storage, source_url, display_name)` tuple to `uploaded_documents_list`.

6. **Rebuild doc_infos.** The `doc_infos` string is rebuilt from all uploaded documents and saved to the conversation.

## Lazy Migration

When `get_uploaded_documents()` is called with a `docs_folder` argument, it checks each document's `doc_storage` path:

1. Call `canonical_docs.is_canonical_path(docs_folder, doc_storage)` on each entry.
2. If the path is already canonical, skip it.
3. If the path is a legacy per-conversation path, call `canonical_docs.migrate_doc_to_canonical()` to move it.
4. Update the tuple in `uploaded_documents_list` with the new canonical path.
5. If any entries changed, persist the updated list via `set_field(..., overwrite=True)`.

This means old conversations are migrated transparently the first time they're loaded after the feature is deployed. No user action required.

### migrate_doc_to_canonical Details

The migration function:

1. Acquires a `FileLock` on `{canonical_storage}.lock`.
2. If the canonical directory already exists (another conversation already migrated this doc), removes the old directory and returns the existing canonical path.
3. If the old directory doesn't exist, logs a warning and returns the old path as a safe fallback.
4. Otherwise, `shutil.copytree` the old directory to the canonical location, then `shutil.rmtree` the old one.
5. Registers the SHA-256 hash (best-effort: tries the original source file first, falls back to hashing the `.index` dill file).

## Eager Startup Migration (migrate_docs.py)

For deployments with many existing conversations, waiting for lazy migration on first access could be slow. The eager migration runs once at startup and processes all conversations in parallel.

### How It Works

1. **Sentinel check.** Looks for `storage/documents/.local_migration_done`. If present, skips entirely.
2. **Discover conversations.** Lists all directories under `storage/conversations/`.
3. **Parallel processing.** Spawns a `ThreadPoolExecutor` with `max_workers` threads (default: 4). Each thread loads one conversation, iterates its `uploaded_documents_list` and `message_attached_documents_list`, and calls `migrate_doc_to_canonical()` for any non-canonical paths.
4. **Progress logging.** Logs progress every ~10% of conversations processed, including counts of migrated, skipped, and failed documents plus elapsed time.
5. **Persist changes.** If any entries changed within a conversation, the updated lists are saved via `set_field()` and `save_local()`.
6. **Sentinel file.** If zero failures occurred, writes the sentinel file with a timestamp. If any failures happened, the sentinel is NOT written, so migration re-runs on next startup.

### Sentinel File

The sentinel lives at `storage/documents/.local_migration_done`. Its contents are a single line with the completion timestamp:

```
Migration completed at 2026-02-28T14:30:00.000000
```

The sentinel is only written when all conversations migrate without errors. Partial failures cause the migration to re-run on the next boot, which is safe because `migrate_doc_to_canonical` is idempotent.

### Usage from server.py

```python
from migrate_docs import run_local_docs_migration

run_local_docs_migration(
    conversation_folder=conversation_folder,
    docs_folder=docs_folder,
    logger=logger,
    max_workers=4,
)
```

## Conversation Method Changes

Five methods on the `Conversation` class accept an optional `docs_folder` parameter. When provided, they route through the canonical store instead of per-conversation storage.

### add_fast_uploaded_document

```python
def add_fast_uploaded_document(self, pdf_url, display_name=None, docs_folder=None)
```

Creates a `FastDocIndex` (BM25 only, no FAISS/LLM). When `docs_folder` is set, builds via `store_or_get` into the canonical parent. Stores a 4-tuple `(doc_id, doc_storage, source_url, display_name)` in `uploaded_documents_list`.

### add_uploaded_document

```python
def add_uploaded_document(self, pdf_url, docs_folder=None)
```

Creates a full `ImmediateDocIndex` (FAISS + LLM summaries). Same canonical routing as above. Stores a tuple in `uploaded_documents_list`.

### add_message_attached_document

```python
def add_message_attached_document(self, pdf_url, docs_folder=None)
```

Creates a `FastDocIndex` for a message attachment. Stored in `message_attached_documents_list` (separate from conversation docs). Can be promoted later.

### promote_message_attached_document

```python
def promote_message_attached_document(self, doc_id, docs_folder=None)
```

Promotes a message-attached doc to a full conversation document. Removes from `message_attached_documents_list`, creates a full `ImmediateDocIndex` via `store_or_get`, and adds to `uploaded_documents_list`.

### get_uploaded_documents

```python
def get_uploaded_documents(self, doc_id=None, readonly=False, docs_folder=None) -> List[DocIndex]
```

Loads uploaded documents. When `docs_folder` is provided, performs lazy migration on any non-canonical paths before loading. Returns a list of `DocIndex` instances with API keys and model overrides attached (unless `readonly=True`).

## Clone Behavior

Cloning a conversation (`clone_conversation()`) copies only the tuple list from `uploaded_documents_list`. No `shutil.copytree` of document directories happens. The comment in the code explains:

> Canonical store: doc tuples point to shared canonical paths, no file copying needed. Per-conversation docs (legacy) are not copied either, they will be lazy-migrated on first access if docs_folder is configured.

This makes cloning fast regardless of how many documents the conversation has.

## Promote to Global

When a conversation document is promoted to a global document (`POST /global_docs/promote/<conversation_id>/<doc_id>`), the endpoint is aware of canonical paths:

1. Checks whether the source storage is in the canonical store via `canonical_docs.is_canonical_path()`.
2. Copies the document to the global docs directory (`storage/global_docs/{user_hash}/{doc_id}/`).
3. Verifies the copy loads correctly.
4. If the source was a FastDocIndex, upgrades it to a full index.
5. Registers the global doc in the database.
6. Removes the doc from the conversation's `uploaded_documents_list`.
7. **Only deletes the source directory if it is NOT in the canonical store.** Canonical paths are shared across conversations and must not be removed. The relevant guard:

```python
if not source_is_canonical:
    shutil.rmtree(source_storage, ignore_errors=True)
```

This prevents the promote operation from breaking other conversations that reference the same canonical document.

## Upgrade Endpoint

### POST /upgrade_doc_index/<conversation_id>/<doc_id>

Upgrades a `FastDocIndex` to a full `DocIndex` with FAISS embeddings and LLM summaries. Rate-limited to 10 per minute.

The upgrade happens in-place at the canonical storage path:

1. Loads the document via `conversation.get_uploaded_documents(doc_id=doc_id, docs_folder=state.docs_folder)`.
2. If already a full index, returns immediately.
3. Builds a new `ImmediateDocIndex` in the same canonical parent directory.
4. Updates the tuple in `uploaded_documents_list` to point to the new storage.
5. Saves the conversation.

Because the upgrade writes to the canonical location, every conversation referencing this doc_id gets the full index on next load. No per-conversation upgrade needed.

**Response:** `{"status": "ok", "is_fast_index": false}`

## Configuration

### docs_folder in AppState

The `AppState` dataclass (in `endpoints/state.py`) includes a `docs_folder` field:

```python
@dataclass
class AppState:
    ...
    docs_folder: str  # Directory for canonical per-user document storage
    ...
```

This is set during `init_state()` in `server.py` and points to `storage/documents/`. Endpoints pass `state.docs_folder` to Conversation methods to enable canonical routing.

### max_workers for Migration

The `run_local_docs_migration()` function accepts a `max_workers` parameter (default: 4) controlling the `ThreadPoolExecutor` thread pool size. Higher values speed up migration on multi-core machines but increase I/O contention. 4 is a safe default for most deployments.

## Key Files

| File | Description |
|------|-------------|
| `canonical_docs.py` | Core module. SHA-256 hashing, index management, `store_or_get`, `migrate_doc_to_canonical`, path helpers. |
| `migrate_docs.py` | Eager startup migration. `ThreadPoolExecutor`-based parallel migration of all conversations, sentinel file mechanism. |
| `Conversation.py` | Five methods updated with `docs_folder` parameter: `add_fast_uploaded_document`, `add_uploaded_document`, `add_message_attached_document`, `promote_message_attached_document`, `get_uploaded_documents`. Clone logic updated to skip file copying. |
| `endpoints/documents.py` | `POST /upgrade_doc_index/<conversation_id>/<doc_id>` endpoint. In-place upgrade from FastDocIndex to full DocIndex at canonical path. |
| `endpoints/global_docs.py` | Promote-to-global endpoint updated with canonical path awareness. Skips source deletion for shared canonical paths. |
| `endpoints/state.py` | `AppState` dataclass with `docs_folder` field. |
| `database/connection.py` | `index_type` column migration on `GlobalDocuments` table. |
| `database/global_docs.py` | `index_type` field in `add_global_doc()` and `list_global_docs()`. |

## Database Changes

### index_type Column on GlobalDocuments

An `index_type` TEXT column was added to the `GlobalDocuments` table via an idempotent `ALTER TABLE` migration in `database/connection.py`:

```sql
ALTER TABLE GlobalDocuments ADD COLUMN index_type TEXT DEFAULT 'full'
```

Values are `'fast'` (for `FastDocIndex`) or `'full'` (for `DocIndex`/`ImmediateDocIndex`). This column is set during `add_global_doc()` based on the `_is_fast_index` attribute of the DocIndex at promote time.

## Thread Safety and Locking

The canonical store uses `filelock.FileLock` at multiple levels:

| Lock | Path | Protects |
|------|------|----------|
| SHA-256 index lock | `{user_hash}/_sha256_index.json.lock` | Reads and writes to the SHA-256 index file. |
| Per-hash build lock | `{user_hash}/.sha_{hash_prefix}.lock` | Prevents concurrent uploads of identical content from racing through the check-and-build sequence. Uses the first 16 chars of the SHA-256 hash. Timeout: 600 seconds. |
| Migration lock | `{canonical_storage}.lock` | Prevents concurrent migrations of the same doc_id from different conversations. Timeout: 60 seconds. |

All locks use `filelock.FileLock` which is cross-thread and cross-process safe on the same filesystem. Lock timeouts are generous to accommodate slow indexing operations (FAISS builds, LLM calls).

### Atomic Index Writes

The SHA-256 index file is written atomically: content goes to `_sha256_index.json.tmp`, then `os.replace()` swaps it into place. This is atomic on POSIX systems, preventing partial reads if a crash occurs mid-write.

## Implementation Notes

### DocIndex.__init__ Creates the Subdirectory

When `store_or_get` calls `build_fn(canonical_parent)`, the build function passes `canonical_parent` as the storage argument to `create_fast_document_index()` or `create_immediate_document_index()`. Inside DocIndex, `__init__` creates `{doc_id}/` as a subdirectory of the given parent. This is why `store_or_get` only needs to ensure the parent exists.

### load_local Convention

`DocIndex.load_local(folder)` looks for `{folder}/{basename(folder)}.index`. For a canonical path like `storage/documents/abc123/9876543210/`, it loads `9876543210/9876543210.index`. This convention means the doc_id doubles as both the directory name and the index filename stem.

### URL Sources Skip SHA-256

When `source_path` is a URL (not a local file), `os.path.isfile()` returns `False` and the SHA-256 dedup path is skipped entirely. The build proceeds without dedup. This is intentional: computing a hash requires downloading the file first, and DocIndex already handles URL-based source dedup at the doc_id level.

### Migration Fallback Hashing

During migration, if the original source file no longer exists on disk (common for old uploads where `pdfs_dir` was cleaned), `_register_hash_for_doc` falls back to hashing the `.index` dill file inside the canonical directory. This isn't a true content hash of the original document, but it still provides some dedup coverage for cases where the same conversation doc was migrated from multiple conversations.

### Sentinel File Guarantees

The sentinel file is only written when `total_failed == 0`. If even one conversation fails to migrate, the sentinel is withheld and migration re-runs on next startup. Since `migrate_doc_to_canonical` is idempotent (it checks whether the canonical directory already exists before copying), re-runs are safe and only process the remaining failures.
