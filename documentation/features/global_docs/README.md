# Global Documents

Index a document once and reference it from any conversation via `#gdoc_N`, `#global_doc_N`, `"display name"`, `#folder:Name`, or `#tag:name` syntax.

Index a document once and reference it from any conversation via `#gdoc_N`, `#global_doc_N`, or `"display name"` syntax.

## Overview

Global Documents are user-scoped documents stored outside any conversation. They can be uploaded once, indexed once, and then referenced from any conversation using `#gdoc_1`, `#gdoc_2`, by their display name in quotes (e.g., `"my research paper"`), by folder (`#folder:Research`), or by tag (`#tag:arxiv`) — identical in spirit to how `#doc_1` references conversation-scoped documents.

Docs can be organized into **hierarchical folders** (DB-metadata only — storage paths are unchanged) and **tagged** (free-form, many-to-many) for filtering and chat referencing. The modal offers two views: a **List view** with tag chips and filter bar, and a **Folder view** backed by the pluggable file browser for drag-and-drop folder organization.

## User Guide

### Creating a Global Document

1. Click the **Global Docs** button (globe icon) in the chat doc bar.
2. In the modal, paste a URL **or** drag-and-drop a file onto the drop area **or** click "browse" to select a file. Supported formats: PDF, Word, HTML, Markdown, CSV, Excel, JSON, images, audio — same as the conversation add-document modal.
3. Optionally set a **display name** — this lets you reference the doc by name (e.g., `"my paper"`) instead of by index.
4. Click **Upload**. Progress is shown as a percentage (0-100%).
5. The document appears in the list with its `#gdoc_N` reference number and display name badge (if set).

### Referencing in Conversations

Type the reference syntax in any message:

| Syntax | Effect |
|--------|--------|
| `#gdoc_1` | Reference global doc 1 (RAG-grounded answer) |
| `#global_doc_1` | Same as `#gdoc_1` |
| `"my doc name"` | Reference by display name (case-insensitive match) |
| `#gdoc_all` / `#global_doc_all` | Reference all global docs |
| `#folder:Research` | Reference all docs assigned to the "Research" folder |
| `#tag:arxiv` | Reference all docs tagged "arxiv" |
| `#summary_gdoc_1` | Force summary generation |
| `#dense_summary_gdoc_1` | Force dense summary generation |
| `#full_gdoc_1` | Get raw full text |

Mix with conversation docs: `#doc_1 and #gdoc_1 compare these papers`.

Mix by name: `"my research paper" summarize the key findings`.

Mix folder+tag: `#folder:ML and #tag:2026 latest findings`.

**Autocomplete in chat input** — type `#folder:` or `#tag:` to get a dropdown of matching names (debounced, powered by `/doc_folders/autocomplete?q=` and `/global_docs/autocomplete?q=`).

### Managing Global Documents

Open the Global Docs modal to:
- **View**: Click the eye icon to open in PDF viewer.
- **Download**: Click the download icon.
- **Delete**: Click the trash icon (confirmation required).
- **Tag**: Click the tag icon (or tag chip area) on any doc row to open the tag editor and add/remove free-form tags.
- **Switch views**: Use the **List / Folder** toggle at the top of the modal to switch between the flat list view and the hierarchical folder view.
- **Manage Folders**: In Folder view, click the **Manage Folders** button to open the pluggable file browser for drag-and-drop folder organization.
- **Filter**: Use the filter bar (List view) to filter by tag, display name, or title.
- **Upload to folder**: When a folder is selected in the folder picker (`#global-doc-folder-select`) before uploading, the new doc is assigned to that folder automatically.

### Folder Organization

Folders are hierarchical (parent/child), stored in the `GlobalDocFolders` DB table. They are **pure metadata** — the filesystem storage paths for doc indices are unchanged regardless of folder assignments. A doc can be in at most one folder.

- Create, rename, move, and delete folders via the **Manage Folders** file browser (opens the pluggable `FileBrowserManager` configured with `onMove` pointing to `POST /doc_folders/<id>/assign`).
- `#folder:Name` references resolve to all docs directly assigned to that folder (non-recursive).

### Tagging

Tags are free-form strings (e.g., `arxiv`, `2026`, `ml`, `reference`). A doc can have any number of tags. Tags are stored in the `GlobalDocTags` DB table (composite PK: `doc_id`, `user_email`, `tag`).

- Add/remove tags via the tag editor in the doc row.
- Tags appear as badge chips on each doc row in List view.
- `#tag:name` references resolve to all docs tagged with that exact tag.

### Dual-View UI

The Global Docs modal (`#global-docs-modal`) has two views controlled by `#global-docs-view-switcher`:

- **List view** (`#global-docs-view-list`): Flat list with `#gdoc_N` badge, display name, title, source, tag chips, and action buttons. Filter bar (`#global-docs-filter`) filters rows in real time.
- **Folder view** (`#global-docs-view-folder`): Folder tree embedded via `FileBrowserManager.configure({onMove: fn, ...})`. A **Manage Folders** button opens the file browser for drag-and-drop folder moves.

### Promoting Conversation Documents

Click the globe icon on any conversation document button in the doc bar. The document moves from the conversation to global storage (no re-indexing needed). It is removed from the conversation and becomes available across all conversations.

## API Endpoints

### Core Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/global_docs/upload` | Upload new global document (file or URL). Accepts optional `folder_id` form field. |
| GET | `/global_docs/list` | List all global docs (includes `tags` array and `folder_id` fields) |
| GET | `/global_docs/info/<doc_id>` | Get detailed info for a global doc |
| GET | `/global_docs/download/<doc_id>` | Download source file |
| GET | `/global_docs/serve?file=<doc_id>` | Serve doc for PDF viewer |
| DELETE | `/global_docs/<doc_id>` | Delete a global doc |
| POST | `/global_docs/promote/<conv_id>/<doc_id>` | Promote conversation doc to global |

### Tag Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/global_docs/<doc_id>/tags` | Set tags `{"tags": ["t1", "t2"]}` — replaces all existing tags |
| GET | `/global_docs/tags` | List all distinct tags for current user |
| GET | `/global_docs/autocomplete?q=<prefix>` | Autocomplete for `#tag:` references |

### Folder Endpoints (`doc_folders_bp`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/doc_folders` | List all folders (flat, with `folder_id`, `parent_id`, `name`) |
| POST | `/doc_folders` | Create folder `{"name": "...", "parent_id": null}` |
| PATCH | `/doc_folders/<folder_id>` | Rename or re-parent folder |
| DELETE | `/doc_folders/<folder_id>` | Delete folder (`?action=move_docs_to_parent` or `?action=delete_docs`) |
| POST | `/doc_folders/<folder_id>/assign` | Assign doc to folder `{"doc_id": "..."}`. `null` removes assignment |
| GET | `/doc_folders/<folder_id>/docs` | List docs in folder |
| GET | `/doc_folders/autocomplete?q=<prefix>` | Autocomplete for `#folder:` references |

### POST /global_docs/upload

**Request (file):** Multipart with `pdf_file` field, optional `display_name` form field.

**Request (URL):** `{"pdf_url": "https://...", "display_name": "optional name"}`

**Response:** `{"status": "ok", "doc_id": "..."}`

### GET /global_docs/list

**Response:**
```json
[
  {
    "index": 1,
    "doc_id": "123456789",
    "display_name": "My Paper",
    "title": "A Study of X",
    "short_summary": "This paper examines...",
    "source": "https://arxiv.org/...",
    "created_at": "2026-02-15T10:30:00"
  }
]
```

### POST /global_docs/promote/<conversation_id>/<doc_id>

Moves a conversation doc to global storage. The doc is removed from the conversation and a global DB row is created. Uses copy-verify-delete for safety.

**Response:** `{"status": "ok", "doc_id": "..."}`

## Storage Layout

```
storage/global_docs/{user_email_md5_hash}/{doc_id}/
    {doc_id}.index      -- serialized DocIndex
    indices/            -- FAISS vector stores
    raw_data/           -- document chunks
    static_data/        -- source metadata
    review_data/        -- analysis data
    _paper_details/     -- paper metadata
    locks/              -- per-field locks
```

## Database

### GlobalDocuments Table (`users.db`)

| Column | Type | Description |
|--------|------|-------------|
| doc_id | TEXT | DocIndex document ID (PK with user_email) |
| user_email | TEXT | Owner email (PK with doc_id) |
| display_name | TEXT | User-editable name |
| doc_source | TEXT | Original URL or file path |
| doc_storage | TEXT | Filesystem path to DocIndex folder |
| title | TEXT | Cached DocIndex title |
| short_summary | TEXT | Cached DocIndex summary |
| folder_id | TEXT | FK to `GlobalDocFolders.folder_id` (nullable, added via idempotent ALTER TABLE migration) |
| created_at | TEXT | ISO timestamp |
| updated_at | TEXT | ISO timestamp |

### GlobalDocFolders Table (new)

| Column | Type | Description |
|--------|------|-------------|
| folder_id | TEXT | UUID primary key (PK with user_email) |
| user_email | TEXT | Owner email |
| name | TEXT | Folder display name |
| parent_id | TEXT | Parent folder_id (null = root) |
| created_at | TEXT | ISO timestamp |
| updated_at | TEXT | ISO timestamp |

Indexes: `(user_email)`, `(user_email, name)`, `(user_email, parent_id)`.

### GlobalDocTags Table (new)

| Column | Type | Description |
|--------|------|-------------|
| doc_id | TEXT | Part of composite PK |
| user_email | TEXT | Part of composite PK |
| tag | TEXT | Free-form tag string (part of composite PK) |
| created_at | TEXT | ISO timestamp |

Composite PK: `(doc_id, user_email, tag)`. Indexes: `(user_email)`, `(user_email, tag)`, `(doc_id, user_email)`.
## Numbering

Global docs use positional numbering (1-based, ordered by `created_at ASC`). Deleting a doc renumbers subsequent ones. This matches how `#doc_N` works for conversation docs.

## Implementation Flows

### Upload Flow

1. **UI** (`interface/global-docs-manager.js`): User clicks Upload in the Global Docs modal, or drags a file onto the drop area. `GlobalDocsManager.upload()` uses XHR (for file uploads, with progress events at 0-70% during transfer, then 70-99% ticking during server-side indexing) or `$.ajax` (for URL uploads). Sends either a multipart form (file) or JSON body (URL) to `POST /global_docs/upload`. Drag-and-drop handlers use `stopPropagation()` to prevent the document-level handlers in `common-chat.js` from hijacking the drop.
2. **Endpoint** (`endpoints/global_docs.py:upload_global_doc()`):
   - Reads session email, computes user hash, ensures per-user storage directory exists at `storage/global_docs/{md5(email)}/`.
   - If file: saves to `state.pdfs_dir`, then calls `create_immediate_document_index(full_pdf_path, user_storage, keys)`.
   - If URL: calls `convert_to_pdf_link_if_needed(url)` then `create_immediate_document_index(pdf_url, user_storage, keys)`.
3. **DocIndex** (`DocIndex.py:create_immediate_document_index()`): Downloads/parses the document, builds FAISS indices, extracts metadata. Stores artifacts under `user_storage/{doc_id}/`.
4. **Persist**: `doc_index.save_local()` writes the serialized index. `add_global_doc()` inserts a row into `GlobalDocuments` table with `doc_id`, `doc_source`, `doc_storage`, cached `title`/`short_summary`.
5. **Response**: Returns `{"status": "ok", "doc_id": "..."}` to the UI.
6. **UI update**: `GlobalDocsManager` calls `loadDocs()` to refresh the list.

### Reference Resolution Flow (in `Conversation.reply()`)

When a user sends a message containing `#gdoc_N`, `#global_doc_N`, or `"display name"`:

1. **Query injection** (`endpoints/conversations.py`, line ~1368): Before calling `conversation.reply(query)`, the endpoint injects `_user_email`, `_users_dir`, and `_global_docs_dir` into the query dict.
2. **Initial regex parse** (`Conversation.py`, line ~5579): `reply()` extracts `attached_gdocs` via `re.findall(r"#(?:gdoc|global_doc)_\d+", query["messageText"])`. Also checks for `#gdoc_all` / `#global_doc_all`. Additionally detects quoted strings (`"..."` or curly quotes) that may match global doc display names.
3. **Summary pattern** (line ~5618): Extended regex pattern includes `#summary_gdoc_N` and `#dense_summary_gdoc_N` variants. If the matched reference is a gdoc, calls `get_global_documents_for_query()` instead of `get_uploaded_documents_for_query()`.
4. **Full-text pattern** (line ~5770): Extended regex includes `#full_gdoc_N` and `#raw_gdoc_N`. Same gdoc branch logic as summaries.
5. **Async resolution** (line ~5974): For standard gdoc references (including quoted names), launches `gdocs_future = get_async_future(self.get_global_documents_for_query, ...)`. If `#gdoc_all`, first lists all global docs from DB and constructs a synthetic message text with all `#gdoc_N` references.
6. **`get_global_documents_for_query()`** (line ~4504):
   - Parses `#gdoc_N` / `#global_doc_N` references from message text.
   - **Quoted display-name matching**: Extracts `"quoted strings"` (straight and curly quotes), looks up each against the `display_name` column of all user's global docs (case-insensitive). Matched names are converted to `#gdoc_N` indices and merged with the numeric references. Duplicates are skipped.
   - Calls `list_global_docs(users_dir, user_email)` to get all user's global docs ordered by `created_at`.
   - Validates indices (1-based) against the list length.
   - For each valid index, calls `DocIndex.load_local(gdoc_row["doc_storage"])` to load the pre-built index.
   - Attaches API keys and model overrides to each loaded DocIndex.
   - Classifies docs as readable (PDF, images, HTML) or data (CSV, JSON, Parquet, etc.).
   - During `replace_reference`, replaces both `#gdoc_N` tags and the original `"quoted name"` text in the message with the resolved doc title info.
   - Returns the same 5-tuple as `get_uploaded_documents_for_query()`: `(query, attached_docs, attached_docs_names, (readable, readable_names), (data, data_names))`.
7. **Merge** (line ~6536): When `gdocs_future` resolves, its results are appended to the conversation doc results — `attached_docs`, `attached_docs_readable`, `attached_docs_data` lists are concatenated. The downstream RAG pipeline then treats all docs uniformly.

### Promote Flow

1. **UI** (`interface/common-chat.js`): User clicks the globe icon on a conversation doc button. JS calls `POST /global_docs/promote/{conversation_id}/{doc_id}`.
2. **Endpoint** (`endpoints/global_docs.py:promote_doc_to_global()`):
   - Loads the conversation and finds the doc entry by `doc_id` in `uploaded_documents_list`.
   - Computes the target path: `storage/global_docs/{md5(email)}/{doc_id}/`.
   - **Copy**: `shutil.copytree(source_storage, target_storage)`.
   - **Verify**: `DocIndex.load_local(target_storage)` — if load fails, deletes the copy and returns 500.
   - **Update storage path**: Sets `doc_index._storage = target_storage` and `doc_index.save_local()` to fix internal path references.
   - **Register**: `add_global_doc(...)` creates the DB row.
   - **Remove from conversation**: Filters the doc out of `uploaded_documents_list`, rebuilds `doc_infos`, saves the conversation.
   - **Cleanup**: `shutil.rmtree(source_storage)` removes the old conversation copy.
3. **Response**: Returns `{"status": "ok", "doc_id": "..."}`.
4. **UI update**: JS reloads conversation docs (the promoted doc disappears from the conversation doc bar).

### Delete Flow

1. **UI**: User clicks trash icon in Global Docs modal. JS confirms, then calls `DELETE /global_docs/{doc_id}`.
2. **Endpoint** (`endpoints/global_docs.py:delete_global_doc_route()`):
   - Looks up the doc row to get `doc_storage` path.
   - Deletes the DB row via `delete_global_doc()`.
   - Removes the filesystem directory via `shutil.rmtree()`.
3. **UI update**: `GlobalDocsManager` calls `loadDocs()` to refresh. Positional numbering shifts for subsequent docs.

### View Flow (PDF Viewer)

1. **UI** (`interface/global-docs-manager.js`): User clicks the eye icon on a global doc entry. JS calls `showPDF(doc.doc_id, "chat-pdf-content", "/global_docs/serve")` — reusing the same `showPDF()` function from `interface/common.js` that conversation docs use. This ensures identical behavior: full-viewport-height iframe, progress bar, resize handler.
2. **showPDF** constructs `GET /global_docs/serve?file=<doc_id>` as an XHR blob request.
3. **Endpoint** (`endpoints/global_docs.py:serve_global_doc()`): Reads the `file` query parameter as `doc_id` and delegates to `download_global_doc()`.
4. **Download logic** (`endpoints/global_docs.py:download_global_doc()`):
   - Checks if DB `doc_source` exists on disk → if yes, serves via `send_from_directory`.
   - **DocIndex fallback**: If DB `doc_source` does not exist (common after promote operations where the original file in `pdfs_dir` is cleaned up), loads the DocIndex from `doc_storage` and reads `doc_index.doc_source` — this points to the actual file inside the global docs storage directory. Serves from there.
   - Last resort: redirects to `doc_source` (for URL-based docs).
5. **showPDF callback**: Creates a blob URL, loads into the PDF.js `<iframe>` viewer, calls `resizePdfView()` which sets the iframe to full window height and binds a resize listener.

**Why not /proxy_shared?** Conversation docs use `/proxy_shared` which calls `cached_get_file()` — a function that checks `os.path.exists()` then falls back to `requests.get()`. For global docs the DB `doc_source` is often a stale local path (not a URL), so `requests.get()` crashes with `MissingSchema`. The `/global_docs/serve` endpoint handles the DocIndex fallback internally and serves the file directly.

### Drag-and-Drop Upload Flow

1. User drags a file onto the `#global-doc-drop-area` element in the modal.
2. `dragover`/`drop` handlers in `GlobalDocsManager.setup()` call `e.stopPropagation()` to prevent the document-level handlers in `common-chat.js` (lines ~2097-2113) from intercepting the drop and routing it to the conversation upload endpoint (`/upload_doc_to_conversation/<conv_id>`).
3. The modal itself also has `dragover.gdoc`/`drop.gdoc` handlers as a backup to prevent event bubbling.
4. On drop, the file is validated via `GlobalDocsManager.isValidFileType()` (mirrors `isValidFileType()` in `common-chat.js`), then uploaded via `GlobalDocsManager.upload()` using XHR with progress events.

## Debugging Guide

### Common Issues

**Global docs not resolving in messages**
- Check that `_user_email` and `_users_dir` are being injected into the query dict. Look at `endpoints/conversations.py` line ~1368.
- Verify the user has global docs in the DB: query `SELECT * FROM GlobalDocuments WHERE user_email = '{email}'` in `storage/users/users.db`.
- Check that the regex is matching: the pattern `#(?:gdoc|global_doc)_\d+` requires no space between `#` and `gdoc`.
- For quoted name references: ensure the `display_name` in the DB matches exactly (case-insensitive). Check with `SELECT display_name FROM GlobalDocuments WHERE user_email = '{email}'`.

**Quoted display-name not matching**
- Matching is case-insensitive but requires an exact string match (no fuzzy/partial).
- Curly quotes (`\u201c...\u201d`) and straight quotes (`"..."`) are both supported.
- The display_name must be non-empty in the DB. Docs without a display_name cannot be referenced by name.
- If the quoted text matches a display_name but also appears as a `#gdoc_N` index reference, the index reference takes precedence (no duplicate).

**Upload succeeds but doc not appearing in list**
- Check the `add_global_doc()` return value in server logs. If it returns `False`, the row may already exist (duplicate `doc_id` + `user_email`).
- Verify the `GlobalDocuments` table exists: `SELECT name FROM sqlite_master WHERE type='table' AND name='GlobalDocuments'`.

**Promote fails with "verify_failed"**
- The copied DocIndex could not be loaded from the target path. Check disk space and permissions on `storage/global_docs/`.
- Look for `DocIndex.load_local()` errors in the server log — the dill deserialization may fail if the index was built with a different library version.

**DocIndex.load_local() returns None**
- The `{doc_id}.index` file may be missing or corrupt in the storage directory.
- Check that the `doc_storage` path in the DB row points to an existing directory: `ls -la {doc_storage}/{doc_id}.index`.

**Wrong doc returned for `#gdoc_N`**
- Numbering is positional by `created_at ASC`. If a doc was deleted, all subsequent indices shift down by 1. This is by design (matches conversation doc behavior).
- Run `GET /global_docs/list` to see current numbering.

### Diagnostic Steps

1. **Check DB state**: `sqlite3 storage/users/users.db "SELECT doc_id, display_name, doc_storage, created_at FROM GlobalDocuments WHERE user_email='...' ORDER BY created_at ASC;"`
2. **Check storage**: `ls -la storage/global_docs/{md5_hash}/` — each subdirectory should be a `doc_id`.
3. **Check index integrity**: In Python: `from DocIndex import DocIndex; d = DocIndex.load_local('{path}'); print(d.get_short_info() if d else 'LOAD FAILED')`
4. **Check reply flow**: Set `logging.DEBUG` on `Conversation` module. Look for `gdoc_refs`, `gdoc_indices`, `loaded_docs` in the `get_global_documents_for_query()` path.
5. **Check endpoint injection**: Add a temporary log line in `endpoints/conversations.py` after line ~1370: `logger.debug(f"gdoc injection: email={email}, users_dir={state.users_dir}")`.

## Error Handling

### Endpoint Error Responses

All endpoints use `endpoints.responses.json_error()` for structured error responses:

```json
{
  "status": "error",
  "error": "Human-readable message",
  "message": "Human-readable message",
  "code": "machine_code"
}
```

| Endpoint | Error Code | HTTP Status | Cause |
|----------|-----------|-------------|-------|
| `POST /global_docs/upload` | `bad_request` | 400 | No file/URL provided, or indexing failed |
| `GET /global_docs/info/<doc_id>` | `not_found` | 404 | Doc ID not in DB for this user |
| `GET /global_docs/download/<doc_id>` | `not_found` | 404 | Doc ID not in DB, or source file missing |
| `DELETE /global_docs/<doc_id>` | `not_found` | 404 | Doc ID not in DB for this user |
| `POST /global_docs/promote/...` | `conversation_not_found` | 404 | Conversation ID invalid |
| `POST /global_docs/promote/...` | `not_found` | 404 | Doc ID not in conversation's doc list |
| `POST /global_docs/promote/...` | `verify_failed` | 500 | Copied DocIndex could not be loaded |
| `POST /global_docs/promote/...` | `promote_failed` | 500 | General exception during promote |

### Reply Flow Error Handling

- In `get_global_documents_for_query()`: Individual `DocIndex.load_local()` failures are caught per-doc. Failed docs are set to `None` and skipped silently — other docs in the same message still resolve.
- In `reply()` merge block (line ~6536): The entire `gdocs_future.result()` is wrapped in `try/except`. If global doc resolution fails entirely, conversation docs still work — the error is logged but does not abort the reply.
- In `get_global_documents_for_query()`: Out-of-range indices (e.g., `#gdoc_99` when only 3 docs exist) are silently filtered out during validation.

### Database Error Handling

- `add_global_doc()`: Uses `INSERT OR IGNORE` — duplicate `(doc_id, user_email)` pairs are silently skipped (returns `False`).
- `delete_global_doc()`: Returns `False` on SQL errors, logs the error. Filesystem cleanup is handled by the calling endpoint, not the DB function.
- `update_global_doc_metadata()`: Returns `False` if no fields to update or on SQL error. Only non-None fields are SET.
- All DB functions open and close their own SQLite connections (no connection pooling).

## Bug Fixes Applied

### Stale doc_source after promote (PDF viewer 500 error)

**Problem**: After promoting a conversation doc to global, the DB `doc_source` pointed to the original file in `storage/pdfs/` which no longer existed. Clicking View in the global docs modal called `/proxy_shared` with this stale path → `cached_get_file()` fell through to `requests.get()` on a local path → `MissingSchema` crash → 500 error.

**Fix (3 parts)**:
1. **Download endpoint** (`endpoints/global_docs.py`): Added DocIndex fallback — when DB `doc_source` doesn't exist, loads the DocIndex from `doc_storage` and serves from its actual `doc_source` (inside the global docs storage directory).
2. **View button** (`interface/global-docs-manager.js`): Changed from `/proxy_shared` with `doc.source` to reusing `showPDF()` with the new `/global_docs/serve` endpoint. This gives full-height PDF viewing and avoids the stale-path proxy issue.
3. **Proxy routes** (`endpoints/static_routes.py`): Added `_is_missing_local_path()` guard — both `/proxy` and `/proxy_shared` now return 404 for non-existent local paths instead of passing them to `requests.get()`. This prevents the `MissingSchema` crash for any caller (global docs or conversation docs).

### Drag-and-drop uploading to wrong endpoint

**Problem**: Dropping a file anywhere on the page (including the global docs modal) was intercepted by the document-level `$(document).on('drop')` handler in `common-chat.js` which called `uploadFile()` → `POST /upload_doc_to_conversation/<conv_id>`. No progress was shown and the file went to the conversation instead of global docs.

**Fix**: Added `#global-doc-drop-area` element with drag/drop handlers that call `e.stopPropagation()`. Also added modal-level handlers as backup. The drop area matches the conversation modal's UI pattern (dashed border, highlight on hover, same accepted file types).

### Empty PDF in viewer (zero-byte response)

**Problem**: After the stale-path fix, `cached_get_file()` returned an empty generator for missing local paths → `/proxy_shared` responded with 200 OK but zero bytes → PDF.js showed "The PDF file is empty".

**Fix**: The proxy routes now check `_is_missing_local_path()` before calling `cached_get_file()` and return `Response("File not found on disk", status=404)` instead of streaming an empty response.

## Implementation Files

### New Files (v1 — Core)
- `database/global_docs.py` — DB CRUD helpers
- `endpoints/global_docs.py` — Flask Blueprint with 7 endpoints (upload, list, info, download, serve, delete, promote)
- `interface/global-docs-manager.js` — Frontend JS manager with drag-drop, XHR progress, file validation

### New Files (v2 — Folders + Tags)
- `database/doc_folders.py` — 9 folder CRUD functions: `create_folder`, `rename_folder`, `move_folder`, `delete_folder`, `list_folders`, `get_folder`, `get_folder_by_name`, `assign_doc_to_folder`, `get_docs_in_folder`
- `database/doc_tags.py` — 6 tag CRUD functions: `add_tag`, `remove_tag`, `set_tags`, `list_tags_for_doc`, `list_all_tags`, `list_docs_by_tag`
- `endpoints/doc_folders.py` — Flask Blueprint `doc_folders_bp` with 7 folder endpoints

### Modified Files (v1)
- `database/connection.py` — `GlobalDocuments` table + indexes
- `endpoints/state.py` — `global_docs_dir` field on AppState
- `server.py` — create `global_docs_dir` on startup
- `endpoints/__init__.py` — register `global_docs_bp`
- `endpoints/conversations.py` — inject `_user_email`, `_global_docs_dir` into query dict
- `Conversation.py` — `get_global_documents_for_query()`, reply flow modifications (7 integration points)
- `interface/interface.html` — Global Docs button, modal HTML with drop area, script tag
- `interface/common-chat.js` — promote button on conversation doc buttons
- `endpoints/static_routes.py` — `_is_missing_local_path()` guard on proxy routes

### Modified Files (v2 — Folders + Tags)
- `database/connection.py` — `GlobalDocFolders` + `GlobalDocTags` tables + `ALTER TABLE GlobalDocuments ADD COLUMN folder_id` migration + 6 new indexes
- `database/global_docs.py` — Tags LEFT JOIN in `list_global_docs()`, `folder_id` in `add_global_doc()`, new `list_global_docs_by_folder()`
- `endpoints/global_docs.py` — 3 new tag endpoints, `folder_id` support in upload/promote
- `endpoints/__init__.py` — `doc_folders_bp` registered
- `Conversation.py` — `#folder:` + `#tag:` detection at lines 5561–5593
- `interface/interface.html` — view switcher, folder picker, filter bar, view containers, `id="global-docs-dialog"` on modal-dialog div
- `interface/global-docs-manager.js` — `_viewMode`, `_folderCache`, `_userHash` state; `filterDocList()`, `openTagEditor()`, `_loadFolderCache()`; tag chips in `renderList()`; view switcher + "Manage Folders" + `FileBrowserManager.configure({onMove})`; `upload()` accepts `folderId` 3rd param
- `interface/common-chat.js` — `hashDebounceTimer`; `#folder:`/`#tag:` autocomplete before `@` in `handleInput()`; `fetchHashAutocomplete()`, `showHashAutocompleteDropdown()`
- `interface/local-docs-manager.js` — `extraFields` support in `DocsManagerUtils.uploadWithProgress` FormData builder
- `interface/service-worker.js` — `CACHE_VERSION` bumped `v26` → `v27`

## Known Limitations

- **No fuzzy display-name matching**: Quoted name references require an exact (case-insensitive) match against `display_name`. Partial matches or typos won't resolve.
- **No display-name uniqueness enforcement**: Two global docs can have the same `display_name`. When referenced by name, the first one (by `created_at`) wins.
- **Positional renumbering on delete**: Deleting `#gdoc_2` causes `#gdoc_3` to become `#gdoc_2`. Users who memorize indices may be surprised.
- **No bulk operations**: Upload, delete, and promote are one-at-a-time.
- **doc_source drift**: The DB `doc_source` can become stale after promote. The download endpoint handles this via DocIndex fallback, but the list endpoint still returns the stale path.
- **`#folder:` is non-recursive**: Only docs directly assigned to the named folder are returned; sub-folder docs are not included.
- **No folder picker in promote flow**: Promoted docs are unassigned (no folder). Assign via Folder view afterwards.
## Future Development Ideas

- **Rename / edit display name**: Add a `PATCH /global_docs/<doc_id>` endpoint to update `display_name` (the DB helper `update_global_doc_metadata` already supports this). Add an edit button in the UI list.
- **Fuzzy name matching**: Use Levenshtein distance or prefix matching for display-name references, with a configurable threshold.
- **Recursive `#folder:` resolution**: Traverse sub-folders so `#folder:ML` includes docs in `ML/NLP`, `ML/Vision`, etc.
- **Bulk upload**: Drag multiple files onto the drop area and index them in parallel.
- **Search within global docs**: Add a search box in the modal that queries `title`, `display_name`, and `short_summary` via FTS.
- **Sync doc_source on promote**: Update the DB `doc_source` to the DocIndex's actual `doc_source` after promote, eliminating the fallback need.
- **Context menu on doc rows**: Right-click → Move to Folder, Edit Tags, Delete (deferred).
- **Display `#folder:Name (N docs)` in rendered chat**: Replace the raw reference with a resolved label showing doc count.
- **Global doc references in PKB**: Allow PKB claims to reference global docs via `@gdoc_N` syntax.
- **Sharing**: Allow sharing global docs with other users or making them workspace-scoped rather than user-scoped.
