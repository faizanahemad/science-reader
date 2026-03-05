# Local (Conversation) Document Features

Local docs are per-conversation documents uploaded by the user or attached to messages. They are stored in the canonical doc store and referenced by 4-tuple entries in the conversation state. This page covers features beyond basic upload and delete: display names, index types, the upgrade flow, the DocsManagerUtils shared library, and the comparison with global docs features (folders, tags) that are NOT available for local docs.

## Overview Table (Feature Comparison)

| Feature | Local Docs | Global Docs |
|---------|------------|-------------|
| Upload file or URL | Yes | Yes |
| Display name | Yes (optional, stored in 4-tuple) | Yes |
| Auto title + summary | Yes (FastDocIndex, lazy) | Yes |
| Semantic index (upgrade) | Yes (`POST /upgrade_doc_index`) | Always full index on upload |
| Tags | **No** | Yes (`GlobalDocTags` table) |
| Folders | **No** | Yes (`GlobalDocFolders` table, metadata-only) |
| Promote to global | Yes (globe icon) | N/A |
| Canonical storage | Yes (`storage/documents/{user_hash}/{doc_id}/`) | No (`storage/global_docs/{user_hash}/{doc_id}/`) |
| SHA-256 dedup | Yes | No |
| `#doc_N` reference syntax | Yes | No (uses `#gdoc_N`) |
| Visible in file browser | **No** (no file browser instance for local docs) | Yes (Folders view) |

## Display Name

The upload form accepts an optional `display_name` field, either as a form key (multipart upload) or a JSON key (URL upload).

Display name is stored as `entry[3]` in the 4-tuple that represents each local doc in the conversation state:

```
(doc_id, doc_storage, doc_source, display_name)
```

When the backend returns doc metadata via `get_short_info()`, the `display_name` key is included. The UI renders it as a badge chip before the doc title in the conversation's doc list panel.

If no display name was provided at upload time, the LLM-generated `title` from the DocIndex is used for display instead.

The `display_name` value is preserved through all migration and transfer operations:

- **Lazy migration**: When a conversation is opened and its docs are migrated to canonical storage on first access, the display name carries over from the old 4-tuple to the new one.
- **Eager migration**: The startup migration (`migrate_docs.py`) preserves display names when moving docs to canonical paths.
- **Clone**: Cloning a conversation copies the full 4-tuple, including display name.
- **Promote to global**: When a local doc is promoted to a global doc via the globe icon, the display name is copied to the `GlobalDocuments` DB row.

**Example**: Upload a file `myreport.pdf` with display name "Q3 Report". The doc list shows "Q3 Report" as a badge, with the LLM-generated title underneath. In chat, `#doc_1` resolves to this document.

## Index Types: FastDocIndex vs Full DocIndex

### FastDocIndex (Default on Upload)

When a user uploads a document to a conversation, a `FastDocIndex` is created. This index provides BM25 text search only, with no FAISS vector embeddings. Creation takes 1-3 seconds, keeping the upload experience snappy.

Key characteristics:

- `is_fast_index = True` in the `get_short_info()` response
- BM25 keyword search works immediately
- No semantic (vector) search capability
- No LLM-generated summaries, key notes, FAQ, or deep-dive sections
- The UI can check `is_fast_index` to show an "Analyze" indicator, signaling that a richer index is available on demand

### Full DocIndex (After Upgrade)

A full `DocIndex` adds several capabilities on top of what FastDocIndex provides:

- **FAISS semantic search**: Vector embeddings for similarity-based retrieval
- **LLM-generated summaries**: Short summary, detailed summary
- **Key notes and FAQ**: Extracted highlights and anticipated questions
- **Deep-dive sections**: Structured breakdown of the document's content

Creating a full DocIndex takes 15-45 seconds depending on document length and LLM response time.

### ImmediateDocIndex (Message Attachments)

`ImmediateDocIndex` is a subclass of `FastDocIndex` used specifically for message attachments (files dragged into the chat input). It also reports `is_fast_index = True` in `get_short_info()`. The distinction from a regular `FastDocIndex` is internal to the backend; from the UI's perspective, both behave the same way.

### get_short_info() Fields

The `get_short_info()` method on any DocIndex variant returns these 8 fields:

| Field | Type | Description |
|-------|------|-------------|
| `visible` | bool | Whether the doc should appear in the UI |
| `doc_id` | str | Unique document identifier |
| `source` | str | Original URL or file path |
| `title` | str | LLM-generated document title |
| `short_summary` | str | Brief LLM-generated summary |
| `summary` | str | Detailed LLM-generated summary |
| `display_name` | str or null | User-provided display name |
| `is_fast_index` | bool | `True` for FastDocIndex and ImmediateDocIndex |

## Upgrade Endpoint

```
POST /upgrade_doc_index/<conversation_id>/<doc_id>
```

Defined in `endpoints/documents.py`. This endpoint upgrades a `FastDocIndex` to a full `DocIndex` **asynchronously** — it returns immediately with a task ID and the client polls progress via SSE.

### Flow

1. **Validate**: Confirms the conversation and document exist; if the doc is already a full index, returns `{status: "ok", message: "Already a full index"}` immediately.
2. **Dispatch**: Launches a daemon background thread (`_run_upgrade_background`) and returns `202 {status: "started", task_id: "<uuid>"}` immediately to the caller.
3. **Background build**: The thread calls `create_immediate_document_index(doc_source, parent_dir, keys, progress_callback=...)` which emits progress phases as it runs: `reading → chunking → embedding → indexing → title_summary → long_summary → saving`.
4. **State tracking**: Progress is written into `_UPGRADE_TASKS[task_id]` — an in-memory dict keyed by task UUID. Each phase update overwrites `{phase, message, status}`.
5. **Completion**: On success, updates the conversation 4-tuple to point at the new index storage path and writes the conversation back to disk.
6. **Cleanup**: The task entry is removed from `_UPGRADE_TASKS` 120 seconds after completion.

### SSE Progress Stream

```
GET /upgrade_doc_index_progress/<task_id>
```

Returns an SSE stream (`text/event-stream`). Emits one JSON event per phase change:

```json
{"status": "running", "phase": "embedding", "message": "Preparing embedding model\u2026"}
```

Possible phase values in order: `queued`, `reading`, `chunking`, `embedding`, `indexing`, `faiss_start`, `title_summary`, `long_summary`, `saving`, `done`.

Final event when complete:

```json
{"status": "completed", "phase": "done", "message": "Full index built successfully.", "is_fast_index": false}
```

On error:

```json
{"status": "error", "phase": "error", "message": "<exception message>"}
```

### UI Behaviour

The "Analyze" button (flask icon) in `LocalDocsManager.renderList()` is shown only when `doc.is_fast_index === true`. Clicking it:

1. Shows `Starting…` spinner immediately.
2. POSTs to `/upgrade_doc_index/…` and receives `{task_id}`.
3. Opens an `EventSource` connection to `/upgrade_doc_index_progress/{task_id}` via `LocalDocsManager._listenUpgradeProgress()`.
4. Updates the button label with each incoming phase message.
5. On `completed` — closes the stream, refreshes the doc list, shows a success toast.
6. On `error` or connection loss — resets the button and shows an error toast.

### Behavior Notes

- **Idempotent**: If the doc already has a full `DocIndex`, the POST returns immediately without re-indexing.
- **Duration**: Typically 1-5 minutes depending on document length, embedding batch size, and LLM response times.
- **Failure safety**: If the background build fails, the original `FastDocIndex` remains intact at its canonical path.
- **No request timeout**: Because the heavy work runs in a background thread and the endpoint returns 202 immediately, there is no risk of Flask/nginx request timeouts causing a hung spinner.
- **In-memory only**: `_UPGRADE_TASKS` is not persisted — if the server restarts mid-upgrade the task is lost and the doc stays as `FastDocIndex`.

## DocsManagerUtils (Shared JS Utilities)

Defined at the top of `interface/local-docs-manager.js` (lines 23-273). This utility object is shared by both `LocalDocsManager` and `GlobalDocsManager`, providing common document handling functions.

### Key Functions

**`getMimeType(filename)`**

Returns a MIME type string derived from the file extension. Used during upload to set the correct `Content-Type` header for multipart requests.

**`isValidFileType(file)`**

Validates a file against the allowed upload types: PDF, common document formats (Word, Excel, CSV, HTML, Markdown, JSON), images, and audio. Returns `true` if the file type is accepted, `false` otherwise.

**`uploadWithProgress(opts)`**

Unified XHR uploader that handles both file (multipart) and URL (JSON) uploads. Accepts an options object:

| Option | Type | Description |
|--------|------|-------------|
| `url` | str | Target endpoint URL |
| `file` | File or null | File object for multipart upload |
| `pdfUrl` | str or null | URL string for URL-based upload |
| `displayName` | str or null | Optional display name |
| `onProgress` | function | Callback receiving progress percentage (0-100) |
| `onSuccess` | function | Callback receiving the parsed JSON response |
| `onError` | function | Callback receiving the error message |

Returns a jQuery Deferred. For file uploads, progress events fire at 0-70% during transfer, then tick from 70-99% while the server indexes the document. For URL uploads, progress is estimated.

The function also supports an `extraFields` parameter for adding additional form data fields (used by `GlobalDocsManager` to pass `folder_id`).

**`setupDropArea(element, onDrop)`**

Wires `dragover`, `dragleave`, and `drop` events on the given DOM element. On a valid file drop, calls `onDrop(file)`. Adds visual feedback (dashed border highlight) during drag hover.

## LocalDocsManager JS Class

Defined in `interface/local-docs-manager.js` (line 274). Manages conversation-scoped document CRUD operations and UI rendering for the local docs panel.

### Key Methods

**`LocalDocsManager.setup(conversationId)`**

One-time initialization per conversation open. Wires the upload form submit handler, configures the drop area via `DocsManagerUtils.setupDropArea()`, and binds event listeners for doc action buttons.

**`LocalDocsManager.refresh(conversationId)`**

Reloads the doc list from the server and re-renders the UI. Called after upload, delete, or promote operations.

**`LocalDocsManager.list(conversationId)`**

Sends `GET /docs/{conversationId}` to the server. Returns an array of `get_short_info()` dicts, one per document in the conversation.

**`LocalDocsManager.upload(conversationId, fileOrUrl, displayName)`**

Delegates to `DocsManagerUtils.uploadWithProgress()` targeting `POST /docs/{conversationId}/upload`. On success, calls `refresh()` to update the doc list.

**`LocalDocsManager.deleteDoc(conversationId, docId)`**

Sends `DELETE /docs/{conversationId}/{docId}` to remove the document from the conversation and canonical storage. On success, calls `refresh()`.

**`LocalDocsManager.renderList(conversationId, docs)`**

Renders the doc list rows in the local docs panel. Each row includes:

- Document title (from `get_short_info().title`)
- Display name badge (if set), shown before the title
- Promote-to-global button (globe icon)
- Delete button (trash icon)
- Fast index indicator (if `is_fast_index` is true)

### State Tracking

`LocalDocsManager.conversationId` tracks the currently-open conversation. This value is updated whenever the user switches conversations, ensuring that doc operations target the correct conversation.

## What Is NOT Supported for Local Docs

This section lists features that exist for global docs but have no equivalent for conversation-scoped local docs.

### No Tags

Tags exist only for global docs. The `GlobalDocTags` database table and the `/global_docs/<id>/tags` endpoints are specific to the global docs system. There is no tag endpoint for conversation docs, no tag storage in the 4-tuple, and no tag UI in `LocalDocsManager`.

### No Folders

Local docs are not organized into folders. The canonical storage directory is flat: `storage/documents/{user_hash}/{doc_id}/`. Each doc sits at the top level under the user's hash directory. `GlobalDocFolders` is a global-docs-only feature with no local docs counterpart.

### No File Browser UI

There is no file browser instance for local docs. The global docs Folders view uses an embedded `createFileBrowser('global-docs-fb', {...})` instance for drag-and-drop folder organization. Local docs have no equivalent. The local docs panel is a simple list rendered by `LocalDocsManager.renderList()`.

### No Search or Filter

The local docs panel shows all docs for the conversation without any filtering mechanism. Global docs list view has a filter bar (`#global-docs-filter`) that filters rows in real time by tag, display name, or title.

### No Bulk Operations

Local docs must be deleted or promoted one at a time. Each action button operates on a single document. There is no multi-select, no "delete all", and no batch promote.

## Canonical Storage and Dedup

Local docs use the canonical doc store at `storage/documents/{user_hash}/{doc_id}/`. The `canonical_docs.py` module provides the `store_or_get()` API, which computes a SHA-256 hash of the uploaded file content. If an identical file has already been stored (same content, possibly different filename), the existing canonical path is returned instead of creating a duplicate.

This dedup behavior is specific to local/conversation docs. Global docs do not use SHA-256 dedup; each upload creates a fresh index at `storage/global_docs/{user_hash}/{doc_id}/`.

Thread safety is handled via `FileLock` in `store_or_get()`, preventing race conditions when multiple conversations upload the same file concurrently.

## Reference Syntax

Local docs use `#doc_N` syntax in chat messages, where `N` is the 1-based positional index ordered by the document's position in the conversation's 4-tuple list.

| Syntax | Effect |
|--------|--------|
| `#doc_1` | Reference conversation doc 1 (RAG-grounded answer) |
| `#doc_all` | Reference all conversation docs |
| `#summary_doc_1` | Force summary generation for doc 1 |
| `#dense_summary_doc_1` | Force dense summary generation |
| `#full_doc_1` | Get raw full text of doc 1 |

Global docs use a separate namespace (`#gdoc_N`, `#global_doc_N`). Both can be mixed in a single message: `#doc_1 and #gdoc_2 compare these papers`.

## @doc/ Autocomplete

The `@doc/` trigger in the chat textarea (`interface/common-chat.js`) shows an autocomplete dropdown for both local and global docs. See `features/global_docs/README.md` for the full description of the unified dropdown.

For **local docs in fast-index mode** (`is_fast_index = true`), the autocomplete now loads the stored `DocIndex` object to retrieve `_title` and `_short_summary`. The fast index stores the filename as `_title` and the first 500 characters of extracted text as `_short_summary` — so the popover shows meaningful helper text even before the user runs the Analyze upgrade.

The backend endpoint is `GET /docs/autocomplete?conversation_id=<id>&prefix=<text>&limit=10` in `endpoints/documents.py`. It calls `DocIndex.load_local(doc_storage)` for each local doc to read title and short_summary without performing any LLM or embedding calls.
## Implementation Files

| File | Role |
|------|------|
| `interface/local-docs-manager.js` | `DocsManagerUtils` + `LocalDocsManager` JS class |
| `endpoints/documents.py` | Upload, delete, list, download, promote, upgrade endpoints |
| `Conversation.py` | `add_fast_uploaded_document(pdf_url, display_name=None, docs_folder=None)`, `add_message_attached_document(pdf_url, docs_folder=None)`, `promote_message_attached_document(doc_id, docs_folder=None)`, `get_uploaded_documents()`, `delete_uploaded_document()` |
| `DocIndex.py` | `DocIndex`, `FastDocIndex`, `ImmediateDocIndex`; `get_short_info()` |
| `canonical_docs.py` | `store_or_get()`, `migrate_doc_to_canonical()`, SHA-256 dedup |
| `migrate_docs.py` | Eager startup migration of legacy per-conversation paths |

### File Responsibilities

- **`local-docs-manager.js`**: All client-side logic for local docs. Contains both the shared `DocsManagerUtils` (reused by global docs) and the `LocalDocsManager` class. Handles upload progress, drag-and-drop, doc list rendering, and action button wiring.
- **`endpoints/documents.py`**: Server-side Flask endpoints for all document operations. The upgrade endpoint (`POST /upgrade_doc_index`) lives here alongside upload, delete, list, and download routes.
- **`Conversation.py`**: The conversation model holds the 4-tuple list and provides methods to add, remove, promote, and query documents. All add/promote methods accept `docs_folder` to route storage through the canonical doc store (`canonical_docs.store_or_get()`); when `docs_folder` is `None`, the legacy per-conversation path (`self.documents_path`) is used. API keys are obtained internally via `self.get_api_keys()`. `get_uploaded_documents_for_query()` handles `#doc_N` reference resolution during `reply()`.
- **`DocIndex.py`**: Defines the index class hierarchy. `FastDocIndex` is the lightweight default; `DocIndex` is the full-featured variant; `ImmediateDocIndex` handles message attachments.
- **`canonical_docs.py`**: Manages the canonical storage layer. `store_or_get()` is the primary entry point, handling SHA-256 hashing, dedup checks, and `FileLock` synchronization.
- **`migrate_docs.py`**: Runs at server startup. Migrates legacy per-conversation doc storage paths to the canonical layout using a `ThreadPoolExecutor` for parallel processing.
