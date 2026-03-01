# Document System Flow Reference

Complete reference for how all three document types flow through the system: message attachments, conversation (local) documents, and global documents. Covers UI, API endpoints, backend Python, storage layout, indexing, and lifecycle operations (upload, promote, delete, numbering, search).

---

## Overview: Three Document Types

| Type | Reference Syntax | Scope | Index Type | Init Time | Persistence |
|------|-----------------|-------|------------|-----------|-------------|
| Message Attachment | `#doc_N` (combined) | Current turn only | FastDocIndex (BM25) | 1-3 sec | Temporary |
| Conversation (Local) Doc | `#doc_N` (combined) | Conversation lifetime | FastDocIndex → promoted to ImmediateDocIndex | 15-45 sec (full) | Persistent |
| Global Doc | `#gdoc_N`, `"display name"`, `#folder:Name`, `#tag:name`, `#gdoc_all` | All conversations, all time | ImmediateDocIndex (FAISS) | 15-45 sec | Permanent |

Combined `#doc_N` numbering: uploaded conversation docs are numbered first (1..M), then message-attached docs (M+1..N).

---

## Part 1: Message Attachments

Message attachments are files attached to the current message via drag-and-drop onto the page or via the paperclip icon. They are indexed lightly (BM25 only) and are available only for the current turn. They can optionally be promoted to persistent conversation docs.

### 1.1 UI Flow

**Entry points** (both handled in `interface/common-chat.js`, function `setupPaperclipAndPageDrop()`, line ~2027):

- **Paperclip icon** (`#chat-paperclip-btn` or similar): click triggers `#chat-file-upload` hidden file input
- **Page drag-and-drop**: `document`-level `dragover`/`drop` event handlers

Both paths call `uploadFileAsAttachment(file, attId)`:
1. Create a temporary attachment strip entry with progress indicator
2. POST file to `/attach_doc_to_message/{conversationId}` via XHR
3. On success: call `enrichAttachmentWithDocInfo(attId, doc_id, source, title)` to update the strip

**UI element IDs:**
- `#chat-file-upload` — hidden file input for paperclip
- Attachment preview strip — rendered inline above the message box

### 1.2 API Endpoint

**`POST /attach_doc_to_message/<conversation_id>`** (`endpoints/documents.py`, line 82)

Function: `attach_doc_to_message_route(conversation_id)`

- Accepts: multipart file upload or JSON `{url: ...}`
- Saves uploaded file to `storage/pdfs/` (temp area)
- Calls: `conversation.add_message_attached_document(full_pdf_path)`
- Returns: `{"status": "...", "doc_id": "...", "source": "...", "title": "..."}`

### 1.3 Backend Python

**`Conversation.add_message_attached_document(pdf_url)`** (`Conversation.py`, line 1741)

1. Deduplicates by path + basename (lines 1774-1777)
2. Calls `create_fast_document_index(pdf_url, folder, keys)` → `FastDocIndex`
3. Appends `(doc_id, doc_storage, doc_source, display_name)` to `message_attached_documents_list` (`display_name` is `None` for message attachments)
   - `doc_storage` points to the canonical path (`storage/documents/{user_hash}/{doc_id}/`) for new uploads. Legacy per-conversation paths are updated to canonical on first load.
4. Rebuilds `doc_infos` from combined uploaded + message-attached list (lines 1787-1799)
5. Saves conversation state

**`Conversation.get_message_attached_documents(doc_id=None, readonly=False)`** (`Conversation.py`, line 1802)

- Loads `FastDocIndex` objects from `message_attached_documents_list`
- Optional filter by `doc_id`

### 1.4 Indexing: FastDocIndex

**`create_fast_document_index(pdf_url, folder, keys)`** (`DocIndex.py`, line 3066)

- Detects file type: pdf, docx, html, md, json, csv, txt, jpg, png, jpeg, bmp, svg, audio
- Extracts text via appropriate loader (PDFReaderTool, UnstructuredWordDocumentLoader, etc.)
- Splits into chunks
- Builds `BM25Okapi` keyword index (rank_bm25 library)
- Stores chunks in `raw_data`
- **Skips**: FAISS embeddings, LLM title/summary generation
- Returns `FastDocIndex` or `FastImageDocIndex`

**`FastDocIndex`** (`DocIndex.py`, line 2104):
- `_is_fast_index = True`
- `_bm25_index` — BM25Okapi instance
- `_bm25_chunks` — list of text chunks
- `_title` — derived from filename (no LLM)
- `_short_summary` — first 500 chars of text (no LLM)
- `_raw_index = None` (no FAISS)

**Key search methods:**
- `bm25_search(query, top_k=10)` (line 2254) — tokenize, score with BM25, return top-k chunks with score > 0
- `semantic_search_document(query, token_limit=16384)` (line 2281) — full text if under token limit, else BM25 results

### 1.5 Storage Layout (message attachments)

```
storage/conversations/{user_email}_{conv_id}/
├── {user_email}_{conv_id}-message_attached_documents_list.json
│   └── [["doc_id_A", "/path/to/storage/doc_id_A", "/path/to/file.pdf"], ...]
└── uploaded_documents/
    └── doc_id_A/
        ├── doc_id_A.index          (serialized FastDocIndex, dill format)
        ├── doc_id_A-raw_data.json  (chunks metadata)
        └── file.pdf                (document file)
```

> **Legacy path.** The layout above is the pre-canonical per-conversation path. New uploads are stored in the canonical doc store at `storage/documents/{user_hash}/{doc_id}/` (see Part 2 section 2.5a). Existing per-conversation paths are lazily migrated on first access and eagerly migrated at startup by `migrate_docs.py`. The tuple's `doc_storage` field always points to the current location, so callers don't need to know which layout is in use.

### 1.6 Promote to Conversation Doc

**UI**: Promote button on attachment strip entry → POST `/promote_message_doc/{conv_id}/{doc_id}`

**API** (`endpoints/documents.py`, line 119): `promote_message_doc_route(conversation_id, document_id)`

**Backend** (`Conversation.py`, line 1854): `promote_message_attached_document(doc_id)`
1. Finds doc in `message_attached_documents_list`
2. Calls `create_immediate_document_index(doc_source, folder, keys)` → full `ImmediateDocIndex` with FAISS + LLM
3. Removes from `message_attached_documents_list`
4. Appends to `uploaded_documents_list`
5. Rebuilds `doc_infos`
6. Saves conversation

---

## Part 2: Conversation (Local) Documents

Conversation documents are persistent within a conversation. They are uploaded via the conversation docs modal and are visible in the conversation panel. They start as `FastDocIndex` (fast, BM25-only) and can be promoted to full `ImmediateDocIndex` (FAISS + LLM) by the user.

### 2.1 UI Flow

**Entry point**: `#conversation-docs-button` button in the chat header

**Modal**: `#conversation-docs-modal` — two-card layout:
- Upload card: file picker, URL input, drag-and-drop area, progress bar
- List card: `#conv-docs-list` showing all conversation docs with action buttons

**Manager class**: `LocalDocsManager` (`interface/local-docs-manager.js`)

**Shared utilities**: `DocsManagerUtils` (`interface/local-docs-manager.js`)

**Initialization**: `LocalDocsManager.setup(conversationId)` — called from `ChatManager.setupAddDocumentForm()` (`interface/common-chat.js`, line 2144) when a conversation is opened.

**Upload flow:**
1. User selects file or pastes URL
2. `DocsManagerUtils.isValidFileType(file, $fileInput)` validates MIME/extension
3. `LocalDocsManager.upload(conversationId, fileOrUrl, displayName)` → `DocsManagerUtils.uploadWithProgress(endpoint, fileOrUrl, opts)`
4. XHR POST to `/upload_doc_to_conversation/{id}`:
   - 0–70%: upload progress from XHR `upload.onprogress`
   - 70–99%: indexing tick (50ms interval, increments by 1)
   - 100%: success
5. On success: reset form, `LocalDocsManager.refresh(conversationId)`

**`display_name` handling in the upload form:**
The upload form accepts an optional `display_name` field. If provided, it is stored in the 4-tuple as `entry[3]` and returned by `get_short_info()` as the `display_name` key. The UI shows `display_name` as a `badge badge-secondary` chip before the doc title when rendering the doc list. If absent, the doc title is used instead.

**List rendering** (`LocalDocsManager.renderList(conversationId, docs)`) renders each doc in `#conv-docs-list` with:
- View button (eye icon) → `showPDF()` via `/proxy_shared?url=...`
- Download button → `/download_doc_from_conversation/{id}/{docId}`
- Promote to global button → `GlobalDocsManager.promote(conversationId, docId)` then `LocalDocsManager.refresh()`
- Delete button → `LocalDocsManager.deleteDoc(conversationId, docId)` then `LocalDocsManager.refresh()`

**Public API of LocalDocsManager:**
- `LocalDocsManager.list(conversationId)` — GET `/list_documents_by_conversation/{id}`
- `LocalDocsManager.deleteDoc(conversationId, docId)` — DELETE `/delete_document_from_conversation/{id}/{docId}`
- `LocalDocsManager.upload(conversationId, fileOrUrl, displayName)` — POST with progress
- `LocalDocsManager.renderList(conversationId, docs)` — render list to DOM
- `LocalDocsManager.refresh(conversationId)` — fetch + re-render
- `LocalDocsManager.setup(conversationId)` — wire all event handlers (once per conversation open)

**Public API of DocsManagerUtils (shared with GlobalDocsManager):**
- `DocsManagerUtils.getMimeType(file)` — browser MIME or extension fallback
- `DocsManagerUtils.isValidFileType(file, $fileInput)` — validate against accept attribute
- `DocsManagerUtils.uploadWithProgress(endpoint, fileOrUrl, opts)` — XHR upload with progress (0→70% upload, 70→99% indexing tick)
- `DocsManagerUtils.setupDropArea($dropArea, $modal, $fileInput, onFileDrop)` — wire drag-and-drop

**DocsManagerUtils shared utility detail:**
Both `LocalDocsManager` and `GlobalDocsManager` share utility functions from `DocsManagerUtils` (defined at the top of `interface/local-docs-manager.js`, lines 23-273):
- `getMimeType(filename)` returns MIME type from extension, falling back to `application/octet-stream`.
- `isValidFileType(file)` validates against allowed PDF/image/doc types listed in the file input's `accept` attribute.
- `uploadWithProgress(opts)` is a unified XHR upload with progress callback. It handles both file uploads (multipart form data) and URL uploads (JSON body), returns a jQuery Deferred, and drives the 0-70% upload / 70-99% indexing tick progress pattern used by both managers.
- `setupDropArea(element, onDrop)` wires drag-and-drop events on a DOM element, toggling a visual highlight class during dragover.

Both managers call `DocsManagerUtils.uploadWithProgress()` for all uploads, so upload behavior (progress reporting, error handling, timeout) is consistent across local and global doc flows.

### 2.2 API Endpoints

**`POST /upload_doc_to_conversation/<conversation_id>`** (`endpoints/documents.py`, line 27)

Function: `upload_doc_to_conversation_route(conversation_id)`
- Accepts: multipart file upload (with optional `display_name` form field) or JSON `{pdf_url, display_name}`
- Saves uploaded file to `storage/pdfs/`
- Calls: `conversation.add_fast_uploaded_document(full_pdf_path, display_name=display_name)`
- Returns: `{"status": "Indexing started", "doc_id": ..., "source": ..., "title": ..., "display_name": ...}`

**`GET /list_documents_by_conversation/<conversation_id>`** (`endpoints/documents.py`, line 177)

Function: `list_documents_by_conversation(conversation_id)`
- Calls: `conversation.get_uploaded_documents(readonly=True)`
- Returns: array of `{"doc_id", "source", "title", "short_summary", "visible", "display_name"}`
  - `display_name` is `null` if not set; UI falls back to `title`

**`DELETE /delete_document_from_conversation/<conversation_id>/<document_id>`** (`endpoints/documents.py`, line 154)

Function: `delete_document_from_conversation_route(conversation_id, document_id)`
- Calls: `conversation.delete_uploaded_document(doc_id)`
- Note: does NOT delete filesystem storage

**`GET /download_doc_from_conversation/<conversation_id>/<doc_id>`** (`endpoints/documents.py`, line 199)

Function: `download_doc_from_conversation(conversation_id, doc_id)`
- Calls: `conversation.get_uploaded_documents(doc_id, readonly=True)`
- Returns: file via `send_from_directory()` or redirect to remote URL

### 2.3 Backend Python

**`Conversation.add_fast_uploaded_document(pdf_url, display_name=None)`** (`Conversation.py`, line 1601)
1. Deduplicates by path + basename
2. Calls `create_fast_document_index(pdf_url, folder, keys)` → `FastDocIndex`
3. Sets `doc_index._display_name = display_name`
4. Stores 4-tuple `(doc_id, doc_storage, doc_source, display_name)` in `uploaded_documents_list`
   - For new uploads, `doc_storage` is the canonical path `storage/documents/{user_hash}/{doc_id}/`. Legacy per-conversation paths are migrated transparently.
5. Rebuilds `doc_infos`
6. Saves conversation

**`Conversation.get_uploaded_documents(doc_id=None, readonly=False)`** (`Conversation.py`, line 1698)
- Iterates `uploaded_documents_list` entries; supports both old 3-tuples and new 4-tuples (backward-compatible). If a tuple's `doc_storage` points to a legacy per-conversation path, it is lazily migrated to the canonical store and the tuple is updated in place.
- Extracts `display_name` from `entry[3]` if present, else `None`.
- After loading each `DocIndex` from disk, sets `loaded._display_name = display_name` so `get_short_info()` returns it.
- Optional filter by `doc_id`

**`Conversation.delete_uploaded_document(doc_id)`** (`Conversation.py`, line 1723)
1. Filters `uploaded_documents_list` to remove entry
2. Rebuilds `doc_infos` with renumbered entries (lines 1733-1739)
3. Saves conversation
4. Does NOT delete filesystem storage (intentional: canonical files may be shared across conversations)

### 2.4 Indexing: FastDocIndex → ImmediateDocIndex

Conversation docs start as `FastDocIndex` (see Part 1 §1.4 for details). Full promotion to `ImmediateDocIndex`:

**`create_immediate_document_index(pdf_url, folder, keys)`** (`DocIndex.py`, line 2793)
- Same file type detection and text extraction as fast path
- Creates `DocIndex` (called `ImmediateDocIndex` in usage) or `ImageDocIndex`
- Launches FAISS index creation in background threads
- Launches LLM title/summary generation in background threads
- Returns after all async tasks complete

**Upgrade endpoint: FastDocIndex to full DocIndex**

`POST /upgrade_doc_index/<conversation_id>/<doc_id>` (`endpoints/documents.py`, line 230)

Upgrades a `FastDocIndex` to a full `DocIndex` in place. The flow:
1. Loads the existing `FastDocIndex` from the conversation's `uploaded_documents_list`.
2. Creates a new full `DocIndex` at the same canonical storage path via `create_immediate_document_index()`.
3. Copies `_display_name` from the old index to the new one.
4. Updates the conversation's tuple list to point at the new index.
5. Returns `{status: "ok", doc_id, info}` on success.

Intended for the "Analyze" button in the local docs panel (not yet wired in UI as of this writing).

**`ImmediateDocIndex` (class `DocIndex`)** (`DocIndex.py`, line 959 / alias line 2100):
- `_raw_index` — FAISS index over full chunks
- `_raw_index_small` — FAISS index over smaller chunks
- `_title` — LLM-generated
- `_short_summary` — LLM-generated
- `_display_name` — optional user-provided label (set externally after load; `None` by default)
- Full metadata in `indices`, `raw_data`, `review_data`, `static_data`, `_paper_details`

**Key DocIndex methods:**
- `get_short_info()` (line 1946) → `{visible, doc_id, source, title, short_summary, summary, display_name}`
  - `display_name` uses `getattr(self, "_display_name", None)` — safe for pickled instances predating this field

**Full `get_short_info()` return fields (8 keys):**

```
DocIndex.get_short_info() returns a dict with:
  visible       - bool; whether the doc is visible in the doc list
  doc_id        - str; mmh3 hash of (source + filetype + doc_type)
  source        - str; relative file path (absolute stripped to repo-relative)
  title         - str; auto-generated or cached LLM-generated title
  short_summary - str; auto-generated or cached brief summary
  summary       - str; alias for short_summary
  display_name  - str or None; user-provided name from upload form
  is_fast_index - bool; True for FastDocIndex/ImmediateDocIndex, False for full DocIndex
```

The `is_fast_index` field reflects the `_is_fast_index` class attribute: `True` on `FastDocIndex` (line 2170) and `ImmediateDocIndex` (line 2385), `False` on the base `DocIndex`. This lets the UI distinguish lightweight BM25-only indices from fully indexed docs without loading the full object.
- `semantic_search_document(query, token_limit)` — FAISS semantic search
- `streaming_get_short_answer(query, mode, save_answer)` (line 1828) — FAISS + LLM answer
- `get_doc_data(top_key, inner_key)` (line 1167) — lazy-load persisted data
- `set_doc_data(top_key, inner_key, value)` (line 1215) — persist data with file locking
- `load_local(folder)` (line 1992) — deserialize from `{folder}/{doc_id}.index` (dill)
- `save_local()` (line 2011) — serialize to disk with file locking

**doc_id generation**: mmh3 hash of (source + filetype + doc_type)

### 2.5 Storage Layout (conversation docs)

```
storage/conversations/{user_email}_{conv_id}/
├── {user_email}_{conv_id}-uploaded_documents_list.json
│   └── [["doc_id_1", "/abs/path/to/doc_id_1/", "/abs/path/to/file.pdf", null], ...]  # 4-tuple; null = no display_name
├── {user_email}_{conv_id}-message_attached_documents_list.json
│   └── [["doc_id_2", "/abs/path/to/doc_id_2/", "/abs/path/to/file2.pdf", null], ...]
└── uploaded_documents/
    ├── doc_id_1/                           # FastDocIndex (pre-promotion)
    │   ├── doc_id_1.index                  # Serialized FastDocIndex (dill)
    │   ├── doc_id_1-raw_data.json          # BM25 chunks metadata
    │   └── original_file.pdf
    └── doc_id_2/                           # ImmediateDocIndex (post-promotion)
        ├── doc_id_2.index                  # Serialized DocIndex (dill)
        ├── doc_id_2-indices.partial        # FAISS indices (dill, binary)
        ├── doc_id_2-indices.json           # FAISS index metadata
        ├── doc_id_2-raw_data.partial       # Chunks (dill, binary)
        ├── doc_id_2-raw_data.json          # Chunks metadata
        ├── doc_id_2-_paper_details.partial # Paper details (dill, binary)
        ├── doc_id_2-_paper_details.json    # Paper details metadata
        ├── doc_id_2-static_data.json       # doc_source, filetype, type, text
        └── original_file.pdf
```

Large data stores use `.partial` (binary dill) + `.json` (metadata/small) pair format. File locking is handled via `locks/{doc_id}.lock`.

> **Legacy path.** The `uploaded_documents/` tree shown above is the pre-canonical per-conversation layout. New uploads go to the canonical doc store at `storage/documents/{user_hash}/{doc_id}/` (see section 2.5a below). The `/abs/path/` values in the JSON tuples now point to canonical paths for new docs. Old per-conversation paths are lazily migrated on first load and eagerly migrated at startup by `migrate_docs.py`. The file structure inside each `{doc_id}/` directory is identical regardless of which parent it lives under.


### 2.5a Canonical Doc Store (storage/documents/)

Since the canonical doc store was introduced, all new document uploads (conversation docs and message attachments) are stored in a shared, user-scoped directory instead of under each conversation. This means multiple conversations can reference the same physical files without duplication.

**Canonical layout:**

```
storage/documents/
└── {user_hash}/                          # md5(user_email), 32-char hex
    ├── _sha256_index.json                # SHA-256 content dedup index
    ├── _sha256_index.json.lock           # FileLock for index writes
    ├── {doc_id_1}/                       # one directory per document
    │   ├── {doc_id_1}.index              # Serialized DocIndex (dill)
    │   ├── {doc_id_1}-raw_data.json
    │   ├── {doc_id_1}-indices.partial    # (if promoted to ImmediateDocIndex)
    │   └── original_file.pdf
    └── {doc_id_2}/
        └── ...
```

**Key concepts:**

- `doc_id` is an mmh3 hash of (source + filetype + doc_type). It serves as the directory name and the primary key within a user's store.
- `user_hash` is `hashlib.md5(email.encode()).hexdigest()`, the same hash used for global docs.
- SHA-256 is a separate, content-based hash used purely for dedup. Two files with different names but identical bytes will map to the same `doc_id` via the SHA-256 index.

**`_sha256_index.json` structure:**

```json
{
  "<sha256_hex>": "<doc_id>",
  "<sha256_hex>": "<doc_id>"
}
```

Written atomically (temp file + `os.replace`). Protected by a FileLock at `_sha256_index.json.lock` (30s timeout).

**`store_or_get()` flow (canonical_docs.py):**

1. If `source_path` is a local file, compute its SHA-256 hash.
2. Look up the hash in `_sha256_index.json`. If a matching `doc_id` exists and its canonical directory is present, return immediately (dedup hit).
3. Acquire a per-SHA file lock at `{canonical_parent}/.sha_{sha256[:16]}.lock` to prevent races on identical concurrent uploads.
4. Call the provided `build_fn(canonical_parent)` to create the DocIndex inside `{user_hash}/{doc_id}/`.
5. Register the SHA-256 to doc_id mapping in the index for future lookups.
6. Return the canonical storage path.

URL sources bypass the SHA-256 check (no local file to hash) but still go through the canonical directory structure.

**Lazy migration (on first access):**

When `Conversation.get_uploaded_documents()` loads a tuple whose `doc_storage` points to a legacy per-conversation path (detected by `is_canonical_path()` returning `False`), it calls `migrate_doc_to_canonical()`. This function:

1. Moves the per-conversation `{doc_id}/` directory into `storage/documents/{user_hash}/{doc_id}/`.
2. Registers the file's SHA-256 hash in the dedup index.
3. Updates the tuple's `doc_storage` in the conversation's JSON list.
4. If the canonical directory already exists (another conversation migrated the same doc first), removes the old directory and returns the existing canonical path.
5. Falls back to the old path if anything goes wrong, so reads never break.

**Eager startup migration (`migrate_docs.py`):**

At server startup, `run_local_docs_migration()` walks every conversation directory in parallel (default 4 threads via `ThreadPoolExecutor`) and migrates both `uploaded_documents_list` and `message_attached_documents_list` entries that still point to legacy paths. A sentinel file at `storage/documents/.local_migration_done` prevents re-scanning on subsequent restarts. If any conversation fails, the sentinel is not written and migration retries on the next startup.

**Backward compatibility summary:**

| Scenario | Behavior |
|----------|----------|
| New upload | Stored directly in `storage/documents/{user_hash}/{doc_id}/` via `store_or_get()` |
| Old conversation loaded | Lazy migration moves doc to canonical store on first `get_uploaded_documents()` call |
| Server startup | Eager migration via `migrate_docs.py` processes all conversations in parallel |
| Clone conversation | Tuples are copied as-is; both conversations share the same canonical files |
| Promote to global | Copies from canonical store to `storage/global_docs/`; does NOT delete the canonical source |
| Tuple format | 4-tuple `(doc_id, doc_storage, doc_source, display_name)` unchanged; `doc_storage` now points to canonical path |

### 2.6 Numbering: #doc_N

Numbering is **positional and 1-based**, rebuilt from the combined list on every add/delete/promote:

```
#doc_1 ... #doc_M   → uploaded_documents_list (M items)
#doc_M+1 ... #doc_N → message_attached_documents_list (N-M items)
```

**`doc_infos` field**: rebuilt after every mutation, stored on Conversation object:
```
#doc_1: (Title of Doc One)[/path/to/file1.pdf]
#doc_2: (Title of Doc Two)[https://example.com/paper.pdf]
#doc_3: (Attached Image)[/path/to/image.png]
```

This field is injected into the LLM system prompt so the model knows which docs are available.

**Deletion renumbers**: Removing `#doc_2` from a 3-doc list makes the old `#doc_3` become the new `#doc_2`.

### 2.7 Search / Query Resolution: #doc_N

**`Conversation.get_uploaded_documents_for_query(query, replace_reference=True)`** (`Conversation.py`, line 5447)

1. Extract code blocks to avoid false matches
2. Regex `r"#doc_\d+"` — find all `#doc_N` references in message text
3. Load combined list: `uploaded_documents + message_attached_documents`
4. Resolve each reference: `all_documents[N - 1]` (1-based → 0-based)
5. Categorize by file type:
   - Readable: PDFs, images, HTML, small files → `attached_docs_readable`
   - Data: CSV, JSON, Excel, Parquet → `attached_docs_data`
6. If `replace_reference=True`, expand `#doc_1` → `#doc_1 (Title of #doc_1 'Actual Title')\n...`
7. Return: `(query, attached_docs, attached_docs_names, (readable, readable_names), (data, data_names))`

During LLM reply generation, `semantic_search_document(query)` is called on each referenced doc to retrieve relevant chunks, which are then injected into the LLM prompt.

---

## Part 3: Global Documents

Global documents are user-owned, persistent across all conversations and sessions. They are uploaded via the global docs modal and referenced via `#gdoc_N` syntax or quoted display name. They always use full `ImmediateDocIndex` (FAISS + LLM).

### 3.1 UI Flow

**Entry point**: Global docs button in the sidebar or toolbar → opens `#global-docs-modal`

**Manager class**: `GlobalDocsManager` (`interface/global-docs-manager.js`, 232 lines)

Uses `DocsManagerUtils` (from `interface/local-docs-manager.js`) for shared upload, validation, and drop-area logic.

**Upload flow** (`GlobalDocsManager.upload(fileOrUrl, displayName)`):
1. Validates file type via `DocsManagerUtils.isValidFileType()`
2. Calls `DocsManagerUtils.uploadWithProgress('/global_docs/upload', fileOrUrl, opts)`
3. XHR POST with progress (0→70% upload, 70→99% indexing tick)
4. On success: `_resetForm()`, `refresh()`, show toast

**List rendering** (`GlobalDocsManager.renderList(docs)`): renders in modal with:
- `#gdoc_N` badge (1-based index)
- Display name badge
- Title and source
- Action buttons: View (`showPDF` via `/global_docs/serve`), Download, Delete

**Public API of GlobalDocsManager:**
- `GlobalDocsManager.list()` — GET `/global_docs/list`
- `GlobalDocsManager.deleteDoc(docId)` — DELETE `/global_docs/{docId}`
- `GlobalDocsManager.promote(conversationId, docId)` — POST `/global_docs/promote/{convId}/{docId}`
- `GlobalDocsManager.getInfo(docId)` — GET `/global_docs/info/{docId}`
- `GlobalDocsManager.isValidFileType(file)` — delegates to DocsManagerUtils
- `GlobalDocsManager.upload(fileOrUrl, displayName)` — POST with progress
- `GlobalDocsManager.renderList(docs)` — render list to DOM
- `GlobalDocsManager.refresh()` — fetch + re-render
- `GlobalDocsManager.setup()` — wire all event handlers

### 3.2 API Endpoints

All endpoints in `endpoints/global_docs.py`.

**`POST /global_docs/upload`** (line 47)

Function: `upload_global_doc()`
- Accepts: multipart file or JSON `{url: ...}`, optional `display_name`
- Calls `_ensure_user_global_dir(state, email)` → creates `storage/global_docs/{user_hash}/`
- Creates full `DocIndex` via `create_immediate_document_index()`
- Registers in DB via `database.global_docs.add_global_doc()`
- Returns: `{"status": "ok", "doc_id": doc_id}`

**`GET /global_docs/list`** (line 126)

Function: `list_global_docs_route()`
- Calls `database.global_docs.list_global_docs(users_dir, user_email)` (ordered by `created_at ASC`)
- Returns: array of `{index (1-based), doc_id, display_name, title, short_summary, source, created_at}`

**`GET /global_docs/info/<doc_id>`** (line 151)

Function: `get_global_doc_info(doc_id)`
- Returns: `{doc_id, display_name, title, short_summary, source, created_at, doc_type, doc_filetype, visible}`

**`GET /global_docs/download/<doc_id>`** (line 186)

Function: `download_global_doc(doc_id)`
- Serves document file from `doc_storage` on disk

**`GET /global_docs/serve`** (line 232)

Function: `serve_global_doc()`
- Query-param wrapper: `?file={doc_id}` → delegates to `download_global_doc()`

**`DELETE /global_docs/<doc_id>`** (line 246)

Function: `delete_global_doc_route(doc_id)`
- Calls `database.global_docs.delete_global_doc()` to remove DB record
- Calls `shutil.rmtree()` to delete storage directory

**`POST /global_docs/promote/<conversation_id>/<doc_id>`** (line 266)

Function: `promote_doc_to_global(conversation_id, doc_id)`

Promote conversation doc → global doc:
1. Find doc in `conversation.uploaded_documents_list`
2. Copy source storage dir → `{global_docs_dir}/{user_hash}/{doc_id}/`
3. Load `DocIndex` from copied storage
4. Update `DocIndex._storage` to new path
5. Save `DocIndex` locally
6. Register in `GlobalDocuments` table via `add_global_doc()`
7. Remove from `conversation.uploaded_documents_list`
8. Rebuild `conversation.doc_infos`
9. Delete original source storage dir **only if it is NOT a canonical path**. If the source lives in `storage/documents/` (canonical store), it is kept intact because other conversations may reference it. The check uses `is_canonical_path()` from `canonical_docs.py`.
10. Save conversation

### 3.3 Database Schema

Table: `GlobalDocuments` (`database/connection.py`, lines 142-153)

```sql
CREATE TABLE IF NOT EXISTS GlobalDocuments (
    doc_id          TEXT NOT NULL,
    user_email      TEXT NOT NULL,
    display_name    TEXT,
    doc_source      TEXT NOT NULL,
    doc_storage     TEXT NOT NULL,
    title           TEXT,
    short_summary   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (doc_id, user_email)
);
CREATE INDEX idx_GlobalDocuments_user_email ON GlobalDocuments(user_email);
CREATE INDEX idx_GlobalDocuments_created_at ON GlobalDocuments(user_email, created_at);
```

Database: `storage/users/users.db`

**CRUD functions** (`database/global_docs.py`):

| Function | Line | Description |
|----------|------|-------------|
| `add_global_doc(users_dir, user_email, doc_id, doc_source, doc_storage, title, short_summary, display_name)` | 28 | INSERT OR IGNORE — returns True if inserted |
| `list_global_docs(users_dir, user_email)` | 76 | SELECT all for user, ORDER BY created_at ASC → List[dict] |
| `get_global_doc(users_dir, user_email, doc_id)` | 113 | SELECT single row → Optional[dict] |
| `delete_global_doc(users_dir, user_email, doc_id)` | 146 | DELETE row only (not filesystem) → bool |
| `update_global_doc_metadata(users_dir, user_email, doc_id, title, short_summary, display_name)` | 169 | UPDATE non-None fields, set updated_at → bool |

### 3.4 Storage Layout (global docs)

```
storage/
├── global_docs/
│   └── {md5(user_email)}/              # per-user directory
│       ├── {doc_id_1}/
│       │   ├── {doc_id_1}.index        # Serialized DocIndex (dill)
│       │   ├── {doc_id_1}-indices.partial
│       │   ├── {doc_id_1}-indices.json
│       │   ├── {doc_id_1}-raw_data.partial
│       │   ├── {doc_id_1}-raw_data.json
│       │   ├── {doc_id_1}-static_data.json
│       │   └── original_file.pdf
│       └── {doc_id_2}/
│           └── ...
└── users/
    └── users.db                        # GlobalDocuments table
```

User hash: `hashlib.md5(email.encode()).hexdigest()` (`_user_hash()` in `endpoints/global_docs.py`, line 36)

### 3.5 Numbering: #gdoc_N

Numbering is **positional and 1-based** from `list_global_docs()` result (ordered by `created_at ASC`).

**Not stable on deletion**: Removing `#gdoc_2` from a 3-doc list makes old `#gdoc_3` become new `#gdoc_2`.

**Alternative reference syntax**: Users can reference global docs in several ways:
```
"my paper name"        → matched case-insensitively against display_name column
#folder:Name           → references all docs in the named folder (non-recursive)
#tag:name              → references all docs with that tag
#gdoc_all              → references all global docs at once
#global_doc_all        → alias for #gdoc_all
```

### 3.6 Search / Query Resolution: #gdoc_N

**`Conversation.get_global_documents_for_query()`** (`Conversation.py`, lines 5535–5689)

1. Extract code blocks to avoid false matches
2. Parse `#gdoc_N` and `#global_doc_N` references via regex
3. Parse `"quoted display name"` references (case-insensitive match against `display_name`)
4. Load `list_global_docs(users_dir, user_email)` from DB
5. Validate indices (1-based, must be ≤ len(all_gdocs))
6. Load `DocIndex.load_local(gdoc_row["doc_storage"])` for each referenced doc
7. Set API keys and model overrides on each DocIndex
8. Categorize by file type (readable vs data)
9. Expand references in message text
10. Return: `(query, attached_docs, attached_docs_names, (readable, readable_names), (data, data_names))`

**Additional query patterns** (`Conversation.py`, lines 6659–6927):
- `#gdoc_all` / `#global_doc_all` — reference all global docs at once
- `#dense_summary_gdoc_N`, `#summary_global_doc_N` — request LLM summary of doc N
- `#full_gdoc_N`, `#raw_global_doc_N`, `#content_gdoc_N` — request full doc content

**Integration in reply generation** (`Conversation.py`, lines 7158–7734):
- `list_global_docs()` called to enumerate all user docs
- `get_global_documents_for_query()` called asynchronously via `get_async_future()`
- Results merged with conversation-uploaded doc results before LLM prompt construction

---

## Part 4: DocIndex Internals

### 4.1 Class Hierarchy

```
DocIndex (DocIndex.py, line 959)         — Full FAISS + LLM index
ImmediateDocIndex = DocIndex             — Alias (line 2100)
FastDocIndex (DocIndex.py, line 2104)    — BM25-only, lightweight
FastImageDocIndex (DocIndex.py, line 2338) — Image-only variant
ImageDocIndex                            — Image + FAISS variant
```

### 4.2 Factory Functions

| Function | File | Line | Creates | When Used |
|----------|------|------|---------|-----------|
| `create_fast_document_index(url, folder, keys)` | DocIndex.py | 3066 | FastDocIndex / FastImageDocIndex | Message attachments, initial conversation doc upload |
| `create_immediate_document_index(url, folder, keys)` | DocIndex.py | 2793 | DocIndex / ImageDocIndex | Promote flows, global doc upload |

### 4.3 Key DocIndex Methods

| Method | Line | Description |
|--------|------|-------------|
| `get_short_info()` | 1946 | Returns `{visible, doc_id, source, title, short_summary, summary}` |
| `semantic_search_document(query, token_limit)` | — | FAISS (full) or BM25 (fast) chunk retrieval |
| `streaming_get_short_answer(query, mode, save_answer)` | 1828 | FAISS search + LLM streaming answer |
| `get_doc_data(top_key, inner_key)` | 1167 | Lazy-load persisted data from disk |
| `set_doc_data(top_key, inner_key, value, overwrite)` | 1215 | Persist data to disk with file locking |
| `load_local(folder)` | 1992 | Deserialize from `{folder}/{doc_id}.index` (dill) |
| `save_local()` | 2011 | Serialize to disk with file locking |
| `bm25_search(query, top_k)` | 2254 | FastDocIndex only — BM25 keyword search |

### 4.4 Data Categories (store_separate)

Each DocIndex stores large data as separate files alongside the main `.index` pickle:

| Key | Format | Contents |
|-----|--------|---------|
| `indices` | `.partial` (dill, binary) + `.json` | FAISS vector indices |
| `raw_data` | `.partial` + `.json` | Document text chunks |
| `review_data` | `.partial` + `.json` | User annotations |
| `static_data` | `.json` | doc_source, filetype, type, raw text |
| `_paper_details` | `.partial` + `.json` | Paper metadata (arxiv/aclanthology) |

File locking: `locks/{doc_id}.lock` (FileLock) prevents concurrent write corruption.

---

## Part 5: State Management

**`AppState`** (`endpoints/state.py`, line 18):
- `global_docs_dir: str` (line 57) — path to `storage/global_docs/`
- `docs_folder: str` — path to `storage/documents/` (canonical doc store root, added for canonical store support)

**Initialization** (`server.py`, lines 343, 351, 379):
```python
global_docs_dir = os.path.join(os.getcwd(), folder, "global_docs")
os.makedirs(global_docs_dir, exist_ok=True)
init_state(..., global_docs_dir=global_docs_dir, ...)
```

```python
docs_folder = os.path.join(os.getcwd(), folder, "documents")
os.makedirs(docs_folder, exist_ok=True)
init_state(..., docs_folder=docs_folder, ...)
```

At startup, `run_local_docs_migration()` from `migrate_docs.py` is also called to eagerly migrate legacy per-conversation docs into the canonical store (see section 2.5a).

---

## Part 6: Files Modified / Created

### New File (Unified Doc Modal)
- `interface/local-docs-manager.js` — DocsManagerUtils + LocalDocsManager

### Modified Files (Unified Doc Modal)
- `interface/global-docs-manager.js` — refactored to delegate to DocsManagerUtils
- `interface/local-docs-manager.js` — contains `DocsManagerUtils` (shared upload, validation, drop-area utilities used by both `LocalDocsManager` and `GlobalDocsManager`)
- `interface/interface.html` — `#conversation-docs-modal`, `#conversation-docs-button`, script tag
- `interface/common-chat.js` — `setupAddDocumentForm` stub, `setupPaperclipAndPageDrop`, deleted `renderDocuments` and `listDocuments`

### Backend (unchanged by modal unification)
- `endpoints/documents.py` — conversation doc API routes
- `endpoints/global_docs.py` — global doc API routes
- `Conversation.py` — all document management methods
- `DocIndex.py` — DocIndex, FastDocIndex, ImmediateDocIndex classes and factory functions
- `database/global_docs.py` — GlobalDocuments CRUD
- `database/connection.py` — GlobalDocuments table schema
- `endpoints/state.py` — AppState with global_docs_dir

### New Files (Canonical Doc Store)
- `canonical_docs.py` — `store_or_get()`, `migrate_doc_to_canonical()`, SHA-256 dedup index, `is_canonical_path()`
- `migrate_docs.py` — eager parallel migration of legacy per-conversation docs at startup

---

## Part 7: Quick Reference — Function Call Chains

### Upload conversation doc
```
User → #conversation-docs-button → #conversation-docs-modal
→ LocalDocsManager.upload()
→ DocsManagerUtils.uploadWithProgress('/upload_doc_to_conversation/{id}', file, {displayName})
→ upload_doc_to_conversation_route()   [endpoints/documents.py:27]
   extracts display_name from request.form (file) or request.json (URL)
→ conversation.add_fast_uploaded_document(path, display_name=display_name)   [Conversation.py:1601]
   sets doc_index._display_name, stores 4-tuple (doc_id, storage, source, display_name)
   storage path is canonical: storage/documents/{user_hash}/{doc_id}/ via store_or_get()
→ create_fast_document_index()   [DocIndex.py:3066]
→ FastDocIndex   (BM25, 1-3s; _display_name=None by default, set after construction)
→ get_short_info() returns {doc_id, source, title, short_summary, display_name}
→ LocalDocsManager.refresh()
```

### Upload message attachment
```
User → paperclip click or page drag-and-drop
→ setupPaperclipAndPageDrop()   [common-chat.js:~2027]
→ uploadFileAsAttachment()
→ POST /attach_doc_to_message/{id}
→ attach_doc_to_message_route()   [endpoints/documents.py:82]
→ conversation.add_message_attached_document()   [Conversation.py:1741]
→ create_fast_document_index()   [DocIndex.py:3066]
→ FastDocIndex   (BM25, 1-3s)
→ append to message_attached_documents_list, rebuild doc_infos
→ enrichAttachmentWithDocInfo()
```

### Promote message attachment → conversation doc
```
User → promote button in attachment strip
→ POST /promote_message_doc/{conv_id}/{doc_id}
→ promote_message_doc_route()   [endpoints/documents.py:119]
→ conversation.promote_message_attached_document()   [Conversation.py:1854]
→ create_immediate_document_index()   [DocIndex.py:2793]
→ ImmediateDocIndex   (FAISS + LLM, 15-45s)
→ move from message_attached_documents_list → uploaded_documents_list
→ rebuild doc_infos
```

### Promote conversation doc → global doc
```
User → promote button in #conv-docs-list
→ GlobalDocsManager.promote(conversationId, docId)
→ POST /global_docs/promote/{conv_id}/{doc_id}
→ promote_doc_to_global()   [endpoints/global_docs.py:266]
→ copy storage dir → global_docs/{user_hash}/{doc_id}/
→ update DocIndex._storage, save_local()
→ add_global_doc()   [database/global_docs.py:28]
→ remove from conversation.uploaded_documents_list
→ rebuild doc_infos, delete original storage dir only if NOT canonical (shared source preserved)
```

### Upload global doc
```
User → global docs modal → GlobalDocsManager.upload()
→ DocsManagerUtils.uploadWithProgress('/global_docs/upload')
→ upload_global_doc()   [endpoints/global_docs.py:47]
→ create_immediate_document_index()   [DocIndex.py:2793]
→ ImmediateDocIndex   (FAISS + LLM, 15-45s)
→ add_global_doc()   [database/global_docs.py:28]
→ GlobalDocsManager.refresh()
```

### Delete conversation doc
```
User → delete button in #conv-docs-list
→ LocalDocsManager.deleteDoc(conversationId, docId)
→ DELETE /delete_document_from_conversation/{id}/{docId}
→ delete_document_from_conversation_route()   [endpoints/documents.py:154]
→ conversation.delete_uploaded_document(docId)   [Conversation.py:1723]
→ filter uploaded_documents_list, rebuild doc_infos
→ LocalDocsManager.refresh()
Note: filesystem storage NOT deleted by this route (canonical files may be shared across conversations)
```

### Delete global doc
```
User → delete button in global docs modal
→ GlobalDocsManager.deleteDoc(docId)
→ DELETE /global_docs/{docId}
→ delete_global_doc_route()   [endpoints/global_docs.py:246]
→ delete_global_doc()   [database/global_docs.py:146]   (DB record)
→ shutil.rmtree()   (filesystem storage)
→ GlobalDocsManager.refresh()
```

### Resolve #doc_N reference in message
```
User message contains "#doc_2"
→ Conversation.get_uploaded_documents_for_query()   [Conversation.py:5447]
→ regex r"#doc_\d+" extracts indices
→ all_docs = get_uploaded_documents() + get_message_attached_documents()
→ doc = all_docs[N - 1]   (1-based → 0-based)
→ doc.semantic_search_document(query)   (FAISS or BM25 depending on index type)
→ inject retrieved chunks into LLM prompt
```

### Resolve #gdoc_N reference in message
```
User message contains "#gdoc_1"
→ Conversation.get_global_documents_for_query()   [Conversation.py:5535]
→ regex r"#(?:gdoc|global_doc)_(\d+)" extracts indices
→ all_gdocs = list_global_docs(users_dir, user_email)   (DB, ordered by created_at)
→ doc = DocIndex.load_local(all_gdocs[N - 1]["doc_storage"])
→ doc.semantic_search_document(query)   (FAISS)
→ inject retrieved chunks into LLM prompt
```
