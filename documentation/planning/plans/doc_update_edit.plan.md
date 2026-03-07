# Document Update / Edit Feature

**Status**: PLANNING (March 2026)

## Goal

Add a document update/edit feature for both local (conversation) and global documents. Instead of deleting and re-uploading, users can open an edit modal to:

1. **Replace the source file** — upload a new file to replace the existing one, triggering full re-indexing
2. **Edit metadata** — change display name, priority, date_written, deprecated, tags, folder (consolidating the current inline editing into the modal)

This replaces the mental model of "delete + re-upload" with "update in place" — matching how real documents evolve in a team/company setting.

---

## Design Decisions

### D1: Version history → **Full replace, no history**
Old version is deleted. The updated doc fully replaces the old one. Simpler, less storage.

### D2: UI pattern → **Modal dialog**
A popup edit form with: current doc info, optional file re-upload area, editable display name, metadata fields (priority, date, deprecated), tags (global docs). Clean separation from the document list.

### D3: Re-indexing behavior → **Blocking with progress indicator**
Show a progress bar in the modal. Document is temporarily unavailable during re-indexing. Simple and predictable. Reuses the existing SSE progress pattern from the upgrade endpoint.

### D4: Global doc update propagation → **Silent update**
Global doc updates silently. Conversations that reference it will get the new version next time they access it. No notifications.

### D5: File type change → **Any supported type allowed**
The replacement file can be any supported format (PDF, Word, Markdown, CSV, etc.). The document identity stays the same regardless of file type change.

### D6: Title/summary regeneration → **Always regenerate on file replace**
When the source file is replaced, the LLM-generated title and short_summary are regenerated from the new content. User-set metadata fields (priority, date_written, deprecated, display_name) are preserved.

### D7: Edit modal consolidation → **Combined modal**
One modal for everything: edit display name, metadata, tags, folder, AND optionally replace the source file. File upload section is optional — if no file selected, only metadata changes are saved. This replaces the current inline editing with a richer experience.

### D8: Local doc canonical store behavior → **Update everywhere**
Since local docs in the canonical store are shared across conversations, updating the file updates it everywhere. This is consistent with the "single source of truth" model.

### D9: doc_id preservation strategy → **Save new file to old source path**
Critical: `doc_id = mmh3.hash(doc_source + doc_filetype + doc_type)`. Since we allow file type changes, the doc_id WILL change if filetype changes. Our strategy:

- **For metadata-only edits**: No doc_id change. PATCH endpoint updates metadata on existing DocIndex.
- **For file replacement**: We create a NEW DocIndex with the new file. The new DocIndex gets its own doc_id (based on the new file's path+type). We then:
  1. Delete the old DocIndex storage folder
  2. Update all references (conversation tuples, DB records) to point to the new doc_id and storage path
  3. Preserve user-set metadata (display_name, priority, date_written, deprecated, tags)

This approach is clean because it works regardless of file type changes and doesn't require hacking the doc_id hash.

---

## Architecture Overview

```
User clicks "Edit" on document row
         │
    ┌────▼──────────────────────┐
    │     Edit Modal opens       │
    │                            │
    │  ┌─ Current doc info ────┐ │
    │  │ Title, source, type   │ │
    │  └───────────────────────┘ │
    │                            │
    │  ┌─ File re-upload ──────┐ │
    │  │ Drop area / browse    │ │
    │  │ (optional)            │ │
    │  └───────────────────────┘ │
    │                            │
    │  ┌─ Metadata fields ─────┐ │
    │  │ Display name          │ │
    │  │ Priority dropdown     │ │
    │  │ Date written          │ │
    │  │ Deprecated checkbox   │ │
    │  │ Tags (global only)    │ │
    │  │ Folder (global only)  │ │
    │  └───────────────────────┘ │
    │                            │
    │  [Cancel]        [Save]    │
    └────────────────────────────┘
         │
         ▼
    ┌─ File changed? ─────────────────────┐
    │                                      │
    │  YES                          NO     │
    │  ▼                            ▼      │
    │  POST /replace endpoint  PATCH /meta │
    │  ├─ Save new file             │      │
    │  ├─ Create new DocIndex       │      │
    │  ├─ Copy metadata from old    │      │
    │  ├─ Delete old storage        │      │
    │  ├─ Update references         │      │
    │  ├─ Update DB (global)        │      │
    │  └─ Return new doc info       │      │
    │                                      │
    └──────────────────────────────────────┘
```

---

## Files to Modify

### Backend (5 files)
1. **`endpoints/documents.py`** — Add `POST /docs/<conversation_id>/<doc_id>/replace` endpoint + SSE progress
2. **`endpoints/global_docs.py`** — Add `POST /global_docs/<doc_id>/replace` endpoint + SSE progress
3. **`Conversation.py`** — Add `replace_uploaded_document(old_doc_id, new_doc_index)` method to swap doc references in tuples
4. **`database/global_docs.py`** — Add `replace_global_doc(...)` function to atomically update doc_id, doc_source, doc_storage, title, summary while preserving metadata
5. **`canonical_docs.py`** — Add helper to remove old SHA-256 entry and register new one during replacement

### Frontend (3 files)
6. **`interface/interface.html`** — Add edit modal HTML (shared between local and global, parameterized)
7. **`interface/local-docs-manager.js`** — Add edit button to rows, open edit modal, wire up replace + metadata save
8. **`interface/global-docs-manager.js`** — Add edit button to rows, open edit modal with tags/folder fields, wire up replace + metadata save

### Documentation (1 file)
9. **`documentation/features/doc_update_edit/README.md`** — User-facing feature documentation

**Total: 9 files** (5 backend, 3 frontend, 1 docs)

---

## Implementation Phases

### Phase 0: Database & Backend Foundation

**Goal**: Add the `replace` backend functions and endpoints for both local and global docs.

#### 0.1: Add `replace_global_doc()` to `database/global_docs.py`

This function atomically replaces the doc identity in the DB while preserving user-set metadata.

```python
def replace_global_doc(
    *,
    users_dir: str,
    user_email: str,
    old_doc_id: str,
    new_doc_id: str,
    new_doc_source: str,
    new_doc_storage: str,
    new_title: str,
    new_short_summary: str,
    new_index_type: str = "full",
) -> bool:
    """
    Replace a global doc's identity (doc_id, source, storage, title, summary)
    while preserving user-set metadata (display_name, priority, date_written,
    deprecated, folder_id, tags, created_at).

    Strategy: read old row → delete old row → insert new row with merged fields.
    This handles the primary key change (doc_id changes when file type changes).
    """
    conn = create_connection(_db_path(users_dir=users_dir))
    try:
        cur = conn.cursor()
        # Read old row to preserve metadata
        cur.execute(
            "SELECT * FROM GlobalDocuments WHERE user_email = ? AND doc_id = ?",
            (user_email, old_doc_id),
        )
        old_row = cur.fetchone()
        if old_row is None:
            return False

        # Column name mapping from row
        columns = [desc[0] for desc in cur.description]
        old_data = dict(zip(columns, old_row))

        # Delete old row
        cur.execute(
            "DELETE FROM GlobalDocuments WHERE user_email = ? AND doc_id = ?",
            (user_email, old_doc_id),
        )

        # Insert new row with merged fields
        now = datetime.now().isoformat()
        cur.execute(
            """INSERT INTO GlobalDocuments
               (doc_id, user_email, display_name, doc_source, doc_storage,
                title, short_summary, folder_id, index_type,
                priority, date_written, deprecated, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_doc_id,
                user_email,
                old_data.get("display_name", ""),      # preserved
                new_doc_source,                          # new
                new_doc_storage,                         # new
                new_title,                               # new (regenerated)
                new_short_summary,                       # new (regenerated)
                old_data.get("folder_id"),               # preserved
                new_index_type,                          # new
                old_data.get("priority", 3),             # preserved
                old_data.get("date_written"),            # preserved
                old_data.get("deprecated", 0),           # preserved
                old_data.get("created_at", now),         # preserved
                now,                                     # updated
            ),
        )
        conn.commit()

        # Migrate tags from old doc_id to new doc_id
        try:
            cur.execute(
                "UPDATE GlobalDocTags SET doc_id = ? WHERE user_email = ? AND doc_id = ?",
                (new_doc_id, user_email, old_doc_id),
            )
            conn.commit()
        except Exception:
            pass  # Tags table may not exist or have no entries

        return True
    except Exception as e:
        logger.error(f"Error replacing global doc {old_doc_id} -> {new_doc_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
```

#### 0.2: Add `replace_uploaded_document()` to `Conversation.py`

```python
def replace_uploaded_document(self, old_doc_id, new_doc_id, new_doc_storage, new_doc_source, display_name=None):
    """Replace a document in uploaded_documents_list with new identity.

    Swaps the tuple for old_doc_id with a new tuple pointing to
    new_doc_id/new_doc_storage while preserving the display_name.
    Rebuilds doc_infos for LLM context.
    """
    docs_list = self.get_field("uploaded_documents_list") or []
    updated = []
    found = False
    for entry in docs_list:
        if entry[0] == old_doc_id:
            # Preserve display_name from old entry if not overridden
            old_display = entry[3] if len(entry) > 3 else None
            dn = display_name if display_name is not None else old_display
            updated.append((new_doc_id, new_doc_storage, new_doc_source, dn))
            found = True
        else:
            updated.append(entry)
    if not found:
        return False
    self.set_field("uploaded_documents_list", updated, overwrite=True)
    # Rebuild doc_infos
    current_documents = self.get_uploaded_documents(readonly=True)
    doc_infos = "\n".join(
        [self._format_doc_info_line(i, d) for i, d in enumerate(current_documents)]
    )
    self.doc_infos = doc_infos
    self.save_local()
    return True
```

#### 0.3: Add SHA-256 index cleanup to `canonical_docs.py`

```python
def remove_sha256_entry(docs_folder: str, u_hash: str, doc_id: str):
    """Remove a doc_id from the SHA-256 dedup index (called during replacement)."""
    index_path = os.path.join(docs_folder, u_hash, "_sha256_index.json")
    lock_path = index_path + ".lock"
    with FileLock(lock_path, timeout=30):
        if not os.path.exists(index_path):
            return
        with open(index_path, "r") as f:
            index = json.load(f)
        # Remove entries that map to this doc_id
        index = {sha: did for sha, did in index.items() if did != doc_id}
        with open(index_path, "w") as f:
            json.dump(index, f)
```

### Phase 1: Replace Endpoint — Local Documents

**Goal**: Add the replace endpoint for conversation documents.

**File**: `endpoints/documents.py`

**Endpoint**: `POST /docs/<conversation_id>/<doc_id>/replace`

```python
# In-memory task tracker for replacement tasks (same pattern as _UPGRADE_TASKS)
_REPLACE_TASKS: dict = {}


@documents_bp.route("/docs/<conversation_id>/<doc_id>/replace", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def replace_conversation_doc_route(conversation_id: str, doc_id: str):
    """Replace a conversation document's source file and re-index.

    Accepts multipart form with:
      - pdf_file: new source file (required)
      - display_name: optional new display name (preserved from old if omitted)
    
    Returns 202 with task_id for SSE progress tracking.
    """
    state, keys = get_state_and_keys()
    conversation = attach_keys(state.conversation_cache.get(conversation_id), keys)
    if conversation is None:
        return json_error("Conversation not found", status=404, code="not_found")

    # Validate document exists
    docs_list = conversation.get_field("uploaded_documents_list") or []
    old_entry = None
    for entry in docs_list:
        if entry[0] == doc_id:
            old_entry = entry
            break
    if old_entry is None:
        return json_error("Document not found", status=404, code="not_found")

    pdf_file = request.files.get("pdf_file")
    if not pdf_file:
        return json_error("No file provided", status=400, code="bad_request")

    # Save new file to temp location
    full_pdf_path = os.path.join(state.pdfs_dir, pdf_file.filename)
    pdf_file.save(full_pdf_path)

    display_name = (request.form.get("display_name") or "").strip() or None

    # Load old DocIndex to capture metadata
    from DocIndex import DocIndex
    old_doc_index = DocIndex.load_local(old_entry[1])
    old_metadata = {}
    if old_doc_index:
        old_metadata = {
            "priority": getattr(old_doc_index, "_priority", 3),
            "date_written": getattr(old_doc_index, "_date_written", None),
            "deprecated": getattr(old_doc_index, "_deprecated", False),
            "display_name": display_name or getattr(old_doc_index, "_display_name", None),
        }

    old_doc_storage = old_entry[1]
    docs_folder = getattr(state, "docs_folder", None)

    task_id = str(uuid.uuid4())
    _REPLACE_TASKS[task_id] = {
        "status": "running",
        "phase": "queued",
        "message": "Starting replacement…",
        "conversation_id": conversation_id,
        "old_doc_id": doc_id,
    }

    t = threading.Thread(
        target=_run_replace_local_background,
        args=(task_id, conversation_id, doc_id, old_doc_storage,
              full_pdf_path, old_metadata, keys, state, docs_folder),
        daemon=True,
    )
    t.start()
    return jsonify({"status": "started", "task_id": task_id}), 202


def _run_replace_local_background(
    task_id, conversation_id, old_doc_id, old_doc_storage,
    new_source_path, old_metadata, keys, state, docs_folder,
):
    """Background thread: create new index, swap references, clean up old."""
    task = _REPLACE_TASKS[task_id]

    def _progress(phase, message):
        task["phase"] = phase
        task["message"] = message

    try:
        from DocIndex import create_immediate_document_index, DocIndex
        import shutil

        _progress("reading", "Extracting text from new document…")

        if docs_folder:
            # Canonical store: build in canonical location
            import canonical_docs as _cd
            u_hash = _cd.user_hash(state.conversation_cache.get(conversation_id).user_id)
            parent_dir = os.path.join(docs_folder, u_hash)
        else:
            parent_dir = os.path.dirname(old_doc_storage)

        new_doc_index = create_immediate_document_index(
            new_source_path, parent_dir, keys, progress_callback=_progress
        )

        # Preserve metadata from old doc
        new_doc_index._priority = old_metadata.get("priority", 3)
        new_doc_index._date_written = old_metadata.get("date_written")
        new_doc_index._deprecated = old_metadata.get("deprecated", False)
        new_doc_index._display_name = old_metadata.get("display_name")
        new_doc_index._visible = True
        new_doc_index.save_local()

        _progress("saving", "Updating conversation…")

        new_doc_id = new_doc_index.doc_id
        new_doc_storage = new_doc_index._storage

        # Update conversation references
        conversation = state.conversation_cache.get(conversation_id)
        if conversation is not None:
            from endpoints.request_context import attach_keys as _ak
            conversation = _ak(conversation, keys)
            conversation.replace_uploaded_document(
                old_doc_id, new_doc_id, new_doc_storage,
                new_doc_index.doc_source, old_metadata.get("display_name"),
            )

        # Clean up old storage (if different from new)
        if old_doc_storage != new_doc_storage and os.path.isdir(old_doc_storage):
            shutil.rmtree(old_doc_storage, ignore_errors=True)

        # Clean up SHA-256 index for old doc
        if docs_folder:
            try:
                _cd.remove_sha256_entry(docs_folder, u_hash, old_doc_id)
            except Exception:
                pass

        short_info = new_doc_index.get_short_info()
        task.update({
            "status": "completed",
            "phase": "done",
            "message": "Document replaced successfully.",
            "new_doc_id": new_doc_id,
            "title": short_info.get("title", ""),
            "short_summary": short_info.get("short_summary", ""),
        })
    except Exception as exc:
        traceback.print_exc()
        task.update({"status": "error", "phase": "error", "message": str(exc)})
    finally:
        def _cleanup():
            time.sleep(120)
            _REPLACE_TASKS.pop(task_id, None)
        threading.Thread(target=_cleanup, daemon=True).start()


@documents_bp.route("/replace_doc_progress/<task_id>")
@login_required
def replace_doc_progress(task_id: str):
    """SSE stream of replacement progress — same pattern as upgrade_doc_index_progress."""
    def generate():
        while True:
            task = _REPLACE_TASKS.get(task_id)
            if task is None:
                yield f"data: {json.dumps({'phase': 'error', 'message': 'Unknown task'})}\n\n"
                break
            yield f"data: {json.dumps(task)}\n\n"
            if task.get("status") in ("completed", "error"):
                break
            time.sleep(1.5)
    return Response(stream_with_context(generate()), mimetype="text/event-stream")
```

### Phase 2: Replace Endpoint — Global Documents

**Goal**: Add the replace endpoint for global documents.

**File**: `endpoints/global_docs.py`

**Endpoint**: `POST /global_docs/<doc_id>/replace`

```python
# In-memory task tracker (same pattern)
_REPLACE_TASKS: dict = {}


@global_docs_bp.route("/global_docs/<doc_id>/replace", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def replace_global_doc_route(doc_id: str):
    """Replace a global document's source file and re-index.

    Accepts multipart form with:
      - pdf_file: new source file (required)
      - display_name: optional new display name
    
    Returns 202 with task_id for SSE progress tracking.
    """
    state, keys = get_state_and_keys()
    email = session.get("email", "")

    doc_row = get_global_doc(users_dir=state.users_dir, user_email=email, doc_id=doc_id)
    if doc_row is None:
        return json_error("Global doc not found", status=404, code="not_found")

    pdf_file = request.files.get("pdf_file")
    if not pdf_file:
        return json_error("No file provided", status=400, code="bad_request")

    full_pdf_path = os.path.join(state.pdfs_dir, pdf_file.filename)
    pdf_file.save(full_pdf_path)

    display_name = (request.form.get("display_name") or "").strip() or None

    task_id = str(uuid.uuid4())
    _REPLACE_TASKS[task_id] = {
        "status": "running",
        "phase": "queued",
        "message": "Starting replacement…",
        "doc_id": doc_id,
    }

    t = threading.Thread(
        target=_run_replace_global_background,
        args=(task_id, doc_id, doc_row, full_pdf_path,
              display_name, email, keys, state),
        daemon=True,
    )
    t.start()
    return jsonify({"status": "started", "task_id": task_id}), 202


def _run_replace_global_background(
    task_id, old_doc_id, doc_row, new_source_path,
    display_name, email, keys, state,
):
    """Background thread: create new index, update DB, clean up old."""
    task = _REPLACE_TASKS[task_id]

    def _progress(phase, message):
        task["phase"] = phase
        task["message"] = message

    try:
        from DocIndex import create_immediate_document_index, DocIndex
        import shutil

        _progress("reading", "Extracting text from new document…")

        old_doc_storage = doc_row.get("doc_storage", "")
        folder_id = doc_row.get("folder_id")
        user_storage = _ensure_user_global_dir(state, email, folder_id=folder_id)

        new_doc_index = create_immediate_document_index(
            new_source_path, user_storage, keys, progress_callback=_progress
        )

        # Preserve user-set metadata from old doc
        new_doc_index._priority = doc_row.get("priority", 3)
        new_doc_index._date_written = doc_row.get("date_written")
        new_doc_index._deprecated = bool(doc_row.get("deprecated", 0))
        new_doc_index._display_name = display_name or doc_row.get("display_name")
        new_doc_index.save_local()

        _progress("saving", "Updating database…")

        new_doc_id = new_doc_index.doc_id
        short_info = new_doc_index.get_short_info()

        # Atomically replace in DB (preserves metadata, tags, folder)
        from database.global_docs import replace_global_doc as _db_replace
        _db_replace(
            users_dir=state.users_dir,
            user_email=email,
            old_doc_id=old_doc_id,
            new_doc_id=new_doc_id,
            new_doc_source=new_source_path,
            new_doc_storage=new_doc_index._storage,
            new_title=short_info.get("title", ""),
            new_short_summary=short_info.get("short_summary", ""),
        )

        # Clean up old storage (if different path)
        if old_doc_storage and old_doc_storage != new_doc_index._storage:
            if os.path.isdir(old_doc_storage):
                shutil.rmtree(old_doc_storage, ignore_errors=True)

        task.update({
            "status": "completed",
            "phase": "done",
            "message": "Document replaced successfully.",
            "new_doc_id": new_doc_id,
            "title": short_info.get("title", ""),
            "short_summary": short_info.get("short_summary", ""),
        })
    except Exception as exc:
        traceback.print_exc()
        task.update({"status": "error", "phase": "error", "message": str(exc)})
    finally:
        def _cleanup():
            time.sleep(120)
            _REPLACE_TASKS.pop(task_id, None)
        threading.Thread(target=_cleanup, daemon=True).start()


@global_docs_bp.route("/global_docs/replace_progress/<task_id>")
@login_required
def replace_global_doc_progress(task_id: str):
    """SSE stream of replacement progress."""
    def generate():
        while True:
            task = _REPLACE_TASKS.get(task_id)
            if task is None:
                yield f"data: {json.dumps({'phase': 'error', 'message': 'Unknown task'})}\n\n"
                break
            yield f"data: {json.dumps(task)}\n\n"
            if task.get("status") in ("completed", "error"):
                break
            time.sleep(1.5)
    return Response(
        stream_with_context(generate()), mimetype="text/event-stream"
    )
```

**Note**: Also need to add `import json, threading, time, uuid` and `from flask import Response, stream_with_context` to `global_docs.py` if not already present. Also need to add `from database.global_docs import replace_global_doc` to imports.

### Phase 3: Frontend — Edit Modal HTML

**Goal**: Add a shared edit modal to `interface.html` that works for both local and global docs.

**File**: `interface/interface.html`

Add after the existing doc modals (after line ~560):

```html
<!-- Document Edit Modal (shared by local and global docs) -->
<div class="modal fade" id="doc-edit-modal" tabindex="-1" role="dialog"
     aria-labelledby="docEditModalLabel" aria-hidden="true">
  <div class="modal-dialog modal-lg" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="docEditModalLabel">Edit Document</h5>
        <button type="button" class="close" data-dismiss="modal" aria-label="Close">
          <span aria-hidden="true">&times;</span>
        </button>
      </div>
      <div class="modal-body">
        <!-- Current doc info (read-only) -->
        <div class="mb-3 p-2 bg-light rounded">
          <small class="text-muted">Current document</small>
          <div id="doc-edit-current-title" class="font-weight-bold"></div>
          <small id="doc-edit-current-source" class="text-muted"></small>
          <span id="doc-edit-current-type" class="badge badge-secondary ml-1"></span>
        </div>

        <!-- File re-upload (optional) -->
        <div class="form-group">
          <label class="font-weight-bold">Replace Source File <small class="text-muted">(optional)</small></label>
          <div id="doc-edit-drop-area"
               style="border: 2px dashed #aaa; padding: 10px; text-align: center; cursor: pointer;">
            Drop a new document here to replace the source file, or click Browse.
          </div>
          <input type="file" id="doc-edit-file-input" style="display:none;"
                 accept=".pdf,.doc,.docx,.html,.htm,.md,.markdown,.txt,.csv,.tsv,.json,.jsonl,.rtf,.xls,.xlsx,.jpg,.jpeg,.png,.svg,.bmp,.mp3,.wav,.webm,.ogg,.flac,.aac,.m4a,.opus,.parquet">
          <button type="button" class="btn btn-sm btn-outline-secondary mt-1" id="doc-edit-browse-btn">
            <i class="fa fa-folder-open"></i> Browse
          </button>
          <div id="doc-edit-file-selected" class="mt-1 small text-success" style="display:none;">
            <i class="fa fa-check"></i> <span id="doc-edit-file-name"></span>
            <button type="button" class="btn btn-sm btn-link text-danger p-0 ml-2" id="doc-edit-file-clear">
              <i class="fa fa-times"></i> Clear
            </button>
          </div>
        </div>

        <hr>

        <!-- Metadata fields -->
        <div class="form-group">
          <label for="doc-edit-display-name">Display Name</label>
          <input type="text" class="form-control" id="doc-edit-display-name"
                 placeholder="Optional custom name">
        </div>

        <div class="form-row">
          <div class="form-group col-md-4">
            <label for="doc-edit-priority">Priority</label>
            <select class="form-control" id="doc-edit-priority">
              <option value="5">Very High</option>
              <option value="4">High</option>
              <option value="3" selected>Medium</option>
              <option value="2">Low</option>
              <option value="1">Very Low</option>
            </select>
          </div>
          <div class="form-group col-md-4">
            <label for="doc-edit-date-written">Date Written</label>
            <input type="date" class="form-control" id="doc-edit-date-written">
          </div>
          <div class="form-group col-md-4">
            <label>Status</label>
            <div class="form-check mt-2">
              <input type="checkbox" class="form-check-input" id="doc-edit-deprecated">
              <label class="form-check-label" for="doc-edit-deprecated">Deprecated</label>
            </div>
          </div>
        </div>

        <!-- Tags (global docs only) -->
        <div class="form-group" id="doc-edit-tags-group" style="display:none;">
          <label for="doc-edit-tags">Tags <small class="text-muted">(comma-separated)</small></label>
          <input type="text" class="form-control" id="doc-edit-tags"
                 placeholder="e.g. research, finance, q4-report">
        </div>

        <!-- Folder (global docs only) -->
        <div class="form-group" id="doc-edit-folder-group" style="display:none;">
          <label for="doc-edit-folder">Folder</label>
          <select class="form-control" id="doc-edit-folder">
            <option value="">— No folder —</option>
          </select>
        </div>

        <!-- Progress indicator (shown during re-indexing) -->
        <div id="doc-edit-progress-area" style="display:none;">
          <div class="progress mb-2">
            <div class="progress-bar progress-bar-striped progress-bar-animated"
                 id="doc-edit-progress-bar" role="progressbar" style="width: 0%;">
            </div>
          </div>
          <small id="doc-edit-progress-message" class="text-muted">Starting…</small>
        </div>
      </div>

      <div class="modal-footer" id="doc-edit-footer">
        <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
        <button type="button" class="btn btn-primary" id="doc-edit-save-btn">
          <i class="fa fa-save"></i> Save Changes
        </button>
      </div>
    </div>
  </div>
</div>
```

### Phase 4: Frontend — Local Docs Edit Integration

**Goal**: Add edit button to local doc rows and wire up the edit modal.

**File**: `interface/local-docs-manager.js`

#### 4.1: Add edit button to each document row

In the `renderList` function, add an edit button (pencil icon) to the `$actions` div, before the delete button:

```javascript
// Edit button — opens edit modal
var $editBtn = $('<button class="btn btn-sm btn-outline-secondary mr-1" title="Edit / Replace Document"></button>')
    .append('<i class="fa fa-pencil"></i>');
(function (docRef, cId) {
    $editBtn.click(function () {
        LocalDocsManager.openEditModal(cId, docRef);
    });
}(doc, conversationId));
```

Insert into the actions assembly line before `$deleteBtn`:
```javascript
$actions.append($viewBtn).append($downloadBtn).append($promoteBtn);
if ($analyzeBtn) { $actions.append($analyzeBtn); }
$actions.append($editBtn);   // NEW
$actions.append($deleteBtn);
```

#### 4.2: Add `openEditModal` method to LocalDocsManager

```javascript
openEditModal: function (conversationId, doc) {
    var $modal = $('#doc-edit-modal');
    
    // Reset state
    $('#doc-edit-file-input').val('');
    $('#doc-edit-file-selected').hide();
    $('#doc-edit-progress-area').hide();
    $('#doc-edit-save-btn').prop('disabled', false).html('<i class="fa fa-save"></i> Save Changes');
    
    // Populate current doc info
    $('#doc-edit-current-title').text(doc.display_name || doc.title || 'Untitled');
    $('#doc-edit-current-source').text(doc.source || '');
    $('#doc-edit-current-type').text(doc.doc_filetype || '');
    $('#docEditModalLabel').text('Edit Document');
    
    // Populate metadata fields
    $('#doc-edit-display-name').val(doc.display_name || '');
    $('#doc-edit-priority').val(doc.priority || 3);
    $('#doc-edit-date-written').val(doc.date_written || '');
    $('#doc-edit-deprecated').prop('checked', !!doc.deprecated);
    
    // Hide global-only fields
    $('#doc-edit-tags-group').hide();
    $('#doc-edit-folder-group').hide();
    
    // Wire up drop area
    DocsManagerUtils.wireDropArea(
        '#doc-edit-drop-area', '#doc-edit-file-input', '#doc-edit-browse-btn'
    );
    
    // File selection display
    $('#doc-edit-file-input').off('change').on('change', function () {
        var file = this.files[0];
        if (file) {
            $('#doc-edit-file-name').text(file.name);
            $('#doc-edit-file-selected').show();
        }
    });
    $('#doc-edit-file-clear').off('click').on('click', function () {
        $('#doc-edit-file-input').val('');
        $('#doc-edit-file-selected').hide();
    });
    
    // Save handler
    $('#doc-edit-save-btn').off('click').on('click', function () {
        var newFile = $('#doc-edit-file-input')[0].files[0] || null;
        var metadata = {
            display_name: $('#doc-edit-display-name').val().trim() || null,
            priority: parseInt($('#doc-edit-priority').val(), 10),
            date_written: $('#doc-edit-date-written').val() || null,
            deprecated: $('#doc-edit-deprecated').is(':checked'),
        };
        
        if (newFile) {
            // File replacement: POST /docs/<conv>/<doc_id>/replace
            LocalDocsManager._replaceDoc(conversationId, doc.doc_id, newFile, metadata);
        } else {
            // Metadata-only: PATCH /docs/<conv>/<doc_id>/metadata
            LocalDocsManager._updateMetadata(conversationId, doc.doc_id, metadata);
            $modal.modal('hide');
            LocalDocsManager.refresh(conversationId);
            if (typeof showToast === 'function') showToast('Document updated.', 'success');
        }
    });
    
    $modal.modal('show');
},

_replaceDoc: function (conversationId, docId, file, metadata) {
    var $saveBtn = $('#doc-edit-save-btn');
    var $progress = $('#doc-edit-progress-area');
    var $bar = $('#doc-edit-progress-bar');
    var $msg = $('#doc-edit-progress-message');
    
    $saveBtn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Replacing…');
    $progress.show();
    $bar.css('width', '5%');
    $msg.text('Uploading file…');
    
    var formData = new FormData();
    formData.append('pdf_file', file);
    if (metadata.display_name) formData.append('display_name', metadata.display_name);
    
    $.ajax({
        url: '/docs/' + conversationId + '/' + docId + '/replace',
        method: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        xhr: function () {
            var xhr = new XMLHttpRequest();
            xhr.upload.addEventListener('progress', function (e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded / e.total) * 30);  // 0-30% for upload
                    $bar.css('width', pct + '%');
                }
            });
            return xhr;
        },
        success: function (resp) {
            if (resp && resp.task_id) {
                // Listen for SSE progress
                LocalDocsManager._listenReplaceProgress(
                    resp.task_id, conversationId, $bar, $msg, $saveBtn, metadata
                );
            } else {
                $progress.hide();
                $('#doc-edit-modal').modal('hide');
                LocalDocsManager.refresh(conversationId);
                if (typeof showToast === 'function') showToast('Document replaced.', 'success');
            }
        },
        error: function (xhr) {
            $progress.hide();
            $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Save Changes');
            var msg = 'Error replacing document.';
            try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
            if (typeof showToast === 'function') showToast(msg, 'danger');
        }
    });
},

_listenReplaceProgress: function (taskId, conversationId, $bar, $msg, $saveBtn, metadata) {
    var source = new EventSource('/replace_doc_progress/' + taskId);
    source.onmessage = function (event) {
        var data = JSON.parse(event.data);
        $msg.text(data.message || '');
        
        // Map phases to progress %
        var phaseMap = {queued: 30, reading: 45, title_summary: 60, long_summary: 75, saving: 90, done: 100, error: 100};
        var pct = phaseMap[data.phase] || 35;
        $bar.css('width', pct + '%');
        
        if (data.status === 'completed') {
            source.close();
            // Also update metadata if changed (the replace endpoint preserves old metadata,
            // but user may have changed metadata in the modal simultaneously)
            if (data.new_doc_id) {
                LocalDocsManager._updateMetadata(conversationId, data.new_doc_id, metadata);
            }
            setTimeout(function () {
                $('#doc-edit-progress-area').hide();
                $('#doc-edit-modal').modal('hide');
                LocalDocsManager.refresh(conversationId);
                if (typeof showToast === 'function') showToast('Document replaced successfully.', 'success');
            }, 500);
        } else if (data.status === 'error') {
            source.close();
            $bar.addClass('bg-danger');
            $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Retry');
            if (typeof showToast === 'function') showToast('Replace failed: ' + data.message, 'danger');
        }
    };
    source.onerror = function () {
        source.close();
        $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Retry');
        if (typeof showToast === 'function') showToast('Connection lost during replacement.', 'danger');
    };
},
```

### Phase 5: Frontend — Global Docs Edit Integration

**Goal**: Add edit button to global doc rows, wire up edit modal with tags/folder fields.

**File**: `interface/global-docs-manager.js`

Same pattern as Phase 4, but additionally:
- Show tags field (`#doc-edit-tags-group`), populated with current tags
- Show folder field (`#doc-edit-folder-group`), populated from `_folderCache`
- Use `/global_docs/<doc_id>/replace` endpoint
- Use `/global_docs/replace_progress/<task_id>` for SSE
- On metadata-only save, use existing `_updateMetadata` which calls `PATCH /global_docs/<doc_id>/metadata`

#### 5.1: Add edit button in `renderList`

Same pattern — insert before `$deleteBtn`:

```javascript
var $editBtn = $('<button class="btn btn-sm btn-outline-secondary mr-1" title="Edit / Replace Document"></button>')
    .append('<i class="fa fa-pencil"></i>');
$editBtn.click(function () {
    GlobalDocsManager.openEditModal(doc);
});
```

Update actions assembly:
```javascript
$actions.append($viewBtn).append($downloadBtn).append($editBtn).append($deleteBtn);
```

#### 5.2: Add `openEditModal` and `_replaceDoc` to GlobalDocsManager

```javascript
openEditModal: function (doc) {
    var $modal = $('#doc-edit-modal');
    
    // Reset
    $('#doc-edit-file-input').val('');
    $('#doc-edit-file-selected').hide();
    $('#doc-edit-progress-area').hide();
    $('#doc-edit-save-btn').prop('disabled', false).html('<i class="fa fa-save"></i> Save Changes');
    
    // Current info
    $('#doc-edit-current-title').text(doc.display_name || doc.title || 'Untitled');
    $('#doc-edit-current-source').text(doc.doc_source || doc.source || '');
    $('#doc-edit-current-type').text(doc.doc_filetype || '');
    $('#docEditModalLabel').text('Edit Global Document');
    
    // Metadata
    $('#doc-edit-display-name').val(doc.display_name || '');
    $('#doc-edit-priority').val(doc.priority || 3);
    $('#doc-edit-date-written').val(doc.date_written || '');
    $('#doc-edit-deprecated').prop('checked', !!doc.deprecated);
    
    // Tags (global only)
    $('#doc-edit-tags-group').show();
    $('#doc-edit-tags').val((doc.tags || []).join(', '));
    
    // Folder (global only)
    $('#doc-edit-folder-group').show();
    var $folderSelect = $('#doc-edit-folder');
    $folderSelect.find('option:not(:first)').remove();
    GlobalDocsManager._folderCache.forEach(function (f) {
        $folderSelect.append($('<option>').val(f.id).text(f.name));
    });
    $folderSelect.val(doc.folder_id || '');
    
    // Wire drop area
    DocsManagerUtils.wireDropArea(
        '#doc-edit-drop-area', '#doc-edit-file-input', '#doc-edit-browse-btn'
    );
    
    // File selection display
    $('#doc-edit-file-input').off('change').on('change', function () {
        var file = this.files[0];
        if (file) {
            $('#doc-edit-file-name').text(file.name);
            $('#doc-edit-file-selected').show();
        }
    });
    $('#doc-edit-file-clear').off('click').on('click', function () {
        $('#doc-edit-file-input').val('');
        $('#doc-edit-file-selected').hide();
    });
    
    // Save
    $('#doc-edit-save-btn').off('click').on('click', function () {
        var newFile = $('#doc-edit-file-input')[0].files[0] || null;
        var metadata = {
            display_name: $('#doc-edit-display-name').val().trim() || null,
            priority: parseInt($('#doc-edit-priority').val(), 10),
            date_written: $('#doc-edit-date-written').val() || null,
            deprecated: $('#doc-edit-deprecated').is(':checked'),
        };
        var tags = $('#doc-edit-tags').val().trim();
        
        if (newFile) {
            GlobalDocsManager._replaceDoc(doc.doc_id, newFile, metadata, tags);
        } else {
            // Metadata-only update
            GlobalDocsManager._updateMetadata(doc.doc_id, metadata);
            // Update tags if changed
            if (tags !== (doc.tags || []).join(', ')) {
                GlobalDocsManager._saveTags(doc.doc_id, tags);
            }
            $modal.modal('hide');
            GlobalDocsManager.refresh();
            if (typeof showToast === 'function') showToast('Document updated.', 'success');
        }
    });
    
    $modal.modal('show');
},

_replaceDoc: function (docId, file, metadata, tags) {
    var $saveBtn = $('#doc-edit-save-btn');
    var $progress = $('#doc-edit-progress-area');
    var $bar = $('#doc-edit-progress-bar');
    var $msg = $('#doc-edit-progress-message');
    
    $saveBtn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Replacing…');
    $progress.show();
    $bar.css('width', '5%');
    $msg.text('Uploading file…');
    
    var formData = new FormData();
    formData.append('pdf_file', file);
    if (metadata.display_name) formData.append('display_name', metadata.display_name);
    
    $.ajax({
        url: '/global_docs/' + docId + '/replace',
        method: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        xhr: function () {
            var xhr = new XMLHttpRequest();
            xhr.upload.addEventListener('progress', function (e) {
                if (e.lengthComputable) {
                    var pct = Math.round((e.loaded / e.total) * 30);
                    $bar.css('width', pct + '%');
                }
            });
            return xhr;
        },
        success: function (resp) {
            if (resp && resp.task_id) {
                GlobalDocsManager._listenReplaceProgress(
                    resp.task_id, $bar, $msg, $saveBtn, metadata, tags
                );
            } else {
                $progress.hide();
                $('#doc-edit-modal').modal('hide');
                GlobalDocsManager.refresh();
                if (typeof showToast === 'function') showToast('Document replaced.', 'success');
            }
        },
        error: function (xhr) {
            $progress.hide();
            $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Save Changes');
            var msg = 'Error replacing document.';
            try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
            if (typeof showToast === 'function') showToast(msg, 'danger');
        }
    });
},

_listenReplaceProgress: function (taskId, $bar, $msg, $saveBtn, metadata, tags) {
    var source = new EventSource('/global_docs/replace_progress/' + taskId);
    source.onmessage = function (event) {
        var data = JSON.parse(event.data);
        $msg.text(data.message || '');
        
        var phaseMap = {queued: 30, reading: 45, title_summary: 60, long_summary: 75, saving: 90, done: 100, error: 100};
        var pct = phaseMap[data.phase] || 35;
        $bar.css('width', pct + '%');
        
        if (data.status === 'completed') {
            source.close();
            // Update metadata and tags on the new doc
            if (data.new_doc_id) {
                GlobalDocsManager._updateMetadata(data.new_doc_id, metadata);
                if (tags) GlobalDocsManager._saveTags(data.new_doc_id, tags);
            }
            setTimeout(function () {
                $('#doc-edit-progress-area').hide();
                $('#doc-edit-modal').modal('hide');
                GlobalDocsManager.refresh();
                if (typeof showToast === 'function') showToast('Document replaced successfully.', 'success');
            }, 500);
        } else if (data.status === 'error') {
            source.close();
            $bar.addClass('bg-danger');
            $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Retry');
            if (typeof showToast === 'function') showToast('Replace failed: ' + data.message, 'danger');
        }
    };
    source.onerror = function () {
        source.close();
        $saveBtn.prop('disabled', false).html('<i class="fa fa-save"></i> Retry');
        if (typeof showToast === 'function') showToast('Connection lost during replacement.', 'danger');
    };
},

_saveTags: function (docId, tagsStr) {
    var tagList = tagsStr.split(',').map(function (t) { return t.trim().toLowerCase(); }).filter(Boolean);
    $.ajax({
        url: '/global_docs/' + docId + '/tags',
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify({ tags: tagList }),
    });
},
```

### Phase 6: Backend — Extend Metadata PATCH for display_name (both endpoints)

The existing `PATCH /docs/<conv>/<doc_id>/metadata` and `PATCH /global_docs/<doc_id>/metadata` endpoints already handle priority, date_written, deprecated. We need to add `display_name` support for the metadata-only save path from the edit modal.

**File**: `endpoints/documents.py` — `update_conversation_doc_metadata_route`

Add to the existing handler:
```python
display_name = data.get("display_name")
# ... after loading doc_index:
if display_name is not None:
    doc_index._display_name = display_name if display_name else None
```

Also update the conversation tuple to reflect the new display_name:
```python
if display_name is not None:
    docs_list = conversation.get_field("uploaded_documents_list") or []
    updated = []
    for entry in docs_list:
        if entry[0] == doc_id:
            entry = entry[:3] + (display_name if display_name else None,)
            if len(entry) < 4:
                entry = entry + (display_name if display_name else None,)
        updated.append(entry)
    conversation.set_field("uploaded_documents_list", updated, overwrite=True)
    conversation.save_local()
```

**File**: `endpoints/global_docs.py` — `update_global_doc_metadata_route`

Already supports `display_name` via `update_global_doc_metadata(... display_name=data.get("display_name"))`. No changes needed.

### Phase 7: Documentation

**File**: `documentation/features/doc_update_edit/README.md`

Write user-facing documentation covering:
- Feature overview and motivation
- How to use the edit modal (both local and global docs)
- File replacement behavior (re-indexing, metadata preservation)
- Metadata editing (display name, priority, date_written, deprecated, tags)
- API endpoints for programmatic access
- Behavioral notes (canonical store sharing, silent propagation)

---

## Risk Analysis

### R1: doc_id Changes on File Replacement (HIGH)

**Risk**: When replacing with a different file (different path or type), `doc_id = mmh3.hash(source + filetype + type)` produces a different ID. All conversation tuples and DB records need updating.

**Mitigation**: The `replace_uploaded_document()` method on Conversation and `replace_global_doc()` in database handle the ID swap atomically. Old storage is cleaned up after new storage is confirmed.

**Edge case**: If the new file produces the same doc_id as an EXISTING different document (hash collision), the new DocIndex would overwrite the existing one. This is extremely unlikely with mmh3 but should be logged as a warning.

### R2: Canonical Store Sharing (MEDIUM)

**Risk**: When a document in the canonical store is shared across multiple conversations and gets replaced, ALL conversations see the new content. User chose "update everywhere" but may not realize the scope.

**Mitigation**: The edit modal should show a warning when the doc is in the canonical store: "This document is shared across conversations. Replacing the file will update it everywhere." This is an informational notice, not a blocker.

### R3: Concurrent Access During Re-indexing (LOW)

**Risk**: While re-indexing, another request might try to load the doc from the old storage path (which is being deleted).

**Mitigation**: The background thread creates the new index first, then swaps references, then deletes old. The swap is atomic (single field update). Worst case: a concurrent reader gets a brief 404 for the old path, but the next request will use the new path.

### R4: Large File Re-indexing Time (LOW)

**Risk**: Re-indexing a large document (100+ pages, audio transcription) could take 30-60 seconds. The blocking progress approach means the user must wait.

**Mitigation**: The SSE progress stream provides real-time feedback (phases: reading → title_summary → long_summary → saving → done). The user sees exactly what's happening. For very large files, this is unavoidable — the alternative (background non-blocking) was rejected in design decisions.

---

## Implementation Order

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7
  DB       Local      Global    HTML       Local     Global    Metadata   Docs
  fns      endpoint   endpoint  modal      JS        JS        PATCH
```

Each phase is independently deployable except:
- Phase 3 (HTML modal) must come before Phase 4-5 (JS wiring)
- Phase 0 (DB functions) must come before Phase 1-2 (endpoints)
- Phase 6 (metadata PATCH) can be done at any time (independent)

---

## Summary

**What**: Document update/edit feature with file replacement + metadata editing in a modal dialog.

**Why**: Documents evolve. Delete-and-reupload is a bad mental model. Update-in-place is natural.

**How**: Edit modal → optional file upload triggers re-indexing with progress → metadata preserved → references updated atomically.

**Scope**: Both local (conversation) and global documents. 9 files modified across 7 phases.

**Key patterns reused**: SSE progress (from upgrade endpoint), metadata inline editing (from metadata plan), XHR upload with progress (from upload forms), background threading (from upgrade endpoint).
