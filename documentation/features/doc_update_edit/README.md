# Document Update / Edit Feature

**Status**: Implemented (March 2026)

## Overview

Update documents in place instead of deleting and re-uploading. An edit modal allows:
1. **Replacing the source file** with a new document (any supported type), triggering full re-indexing
2. **Editing metadata** (display name, priority, date written, deprecated, tags, folder)

Works for both **local (conversation) documents** and **global documents**.

## Motivation

Documents evolve. The previous workflow required deleting the old version and re-uploading, losing the document's identity and position in conversation references. This feature preserves document identity across updates.

## UI Details

### Edit Modal

Opened via the pencil icon button on any document row (local or global doc list).

**Modal sections:**
- **Current document info** (read-only): Shows title, source filename, and file type
- **Replace source file** (optional): Drag-and-drop area or Browse button. Selecting a new file triggers full re-indexing on save
- **Display Name**: Optional custom name for the document
- **Priority**: Dropdown (Very Low through Very High)
- **Date Written**: Date input
- **Deprecated**: Checkbox
- **Tags** (global docs only): Comma-separated tag input
- **Folder** (global docs only): Folder dropdown
- **Progress indicator**: Shown during re-indexing when a file is replaced

### Save Behavior

- **Metadata-only save** (no file selected): Instant PATCH request, modal closes
- **File replacement** (file selected): POST to replace endpoint, modal shows progress bar with SSE-streamed phases (reading, title_summary, long_summary, saving, done)

## API Endpoints

### Local Document Replace

```
POST /docs/<conversation_id>/<doc_id>/replace
```

**Request**: Multipart form data
- `pdf_file` (required): New source file
- `display_name` (optional): New display name

**Response**: `202 Accepted`
```json
{"status": "started", "task_id": "<uuid>"}
```

**Progress SSE**:
```
GET /replace_doc_progress/<task_id>
```

Returns `text/event-stream` with JSON events:
```json
{"status": "running", "phase": "reading", "message": "Extracting text..."}
{"status": "completed", "phase": "done", "new_doc_id": "...", "title": "...", "short_summary": "..."}
```

### Global Document Replace

```
POST /global_docs/<doc_id>/replace
```

Same request/response format as local. Progress SSE at:
```
GET /global_docs/replace_progress/<task_id>
```

### Metadata PATCH (Enhanced)

Both existing PATCH endpoints now support `display_name`:

```
PATCH /docs/<conversation_id>/<doc_id>/metadata
PATCH /global_docs/<doc_id>/metadata
```

Body: `{"display_name": "New Name", "priority": 4, "date_written": "2026-01-15", "deprecated": false}`

## Function Details

### Backend

| Function | File | Purpose |
|----------|------|---------|
| `replace_global_doc()` | `database/global_docs.py` | Atomically replace global doc in DB preserving metadata |
| `replace_uploaded_document()` | `Conversation.py` | Swap doc tuple in conversation list, rebuild doc_infos |
| `remove_sha256_entry()` | `canonical_docs.py` | Clean up SHA-256 dedup index during replacement |
| `replace_conversation_doc_route()` | `endpoints/documents.py` | POST endpoint for local doc replacement |
| `replace_global_doc_route()` | `endpoints/global_docs.py` | POST endpoint for global doc replacement |
| `_run_replace_local()` | `endpoints/documents.py` | Background worker for local doc replacement |
| `_run_replace_global()` | `endpoints/global_docs.py` | Background worker for global doc replacement |

### Frontend

| Method | File | Purpose |
|--------|------|---------|
| `LocalDocsManager.openEditModal()` | `local-docs-manager.js` | Open edit modal for local doc |
| `LocalDocsManager._replaceDoc()` | `local-docs-manager.js` | XHR POST + SSE progress for local |
| `LocalDocsManager._listenReplaceProgress()` | `local-docs-manager.js` | SSE listener for local replace |
| `GlobalDocsManager.openEditModal()` | `global-docs-manager.js` | Open edit modal for global doc |
| `GlobalDocsManager._replaceDoc()` | `global-docs-manager.js` | XHR POST + SSE progress for global |
| `GlobalDocsManager._listenReplaceProgress()` | `global-docs-manager.js` | SSE listener for global replace |
| `GlobalDocsManager._saveTags()` | `global-docs-manager.js` | Save tags after replace |

## Implementation Notes

### doc_id Behavior

`doc_id = mmh3.hash(source_path + filetype + type)`. When replacing with a different file, the doc_id may change (different path/type produces different hash). The replacement flow handles this by:

1. Creating the new DocIndex (gets new doc_id)
2. Atomically updating all references (conversation tuple, DB record)
3. Migrating tags from old doc_id to new doc_id
4. Deleting old storage

### Metadata Preservation

On file replacement, these fields are **preserved** from the old document:
- `display_name`, `priority`, `date_written`, `deprecated`, `tags`, `folder_id`, `created_at`

These fields are **regenerated** from the new content:
- `title`, `short_summary` (via DocIndex.get_short_info())

### Global Doc Propagation

Global doc updates propagate silently. All conversations referencing the doc will get the updated version on their next access.

## Files Modified

### Backend (5 files)
- `database/global_docs.py` — Added `replace_global_doc()`
- `Conversation.py` — Added `replace_uploaded_document()`
- `canonical_docs.py` — Added `remove_sha256_entry()`
- `endpoints/documents.py` — Added replace endpoint + SSE progress + display_name in PATCH
- `endpoints/global_docs.py` — Added replace endpoint + SSE progress + display_name in PATCH

### Frontend (3 files)
- `interface/interface.html` — Added `#doc-edit-modal`
- `interface/local-docs-manager.js` — Added edit button + openEditModal + _replaceDoc + _listenReplaceProgress
- `interface/global-docs-manager.js` — Added edit button + openEditModal + _replaceDoc + _listenReplaceProgress + _saveTags

### Other (1 file)
- `interface/service-worker.js` — Bumped CACHE_VERSION to v32
