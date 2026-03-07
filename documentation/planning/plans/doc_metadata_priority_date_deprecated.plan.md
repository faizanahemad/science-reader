# Document Metadata: Priority, Date Written, Deprecated

**Status: COMPLETE** (all 8 phases implemented, March 2026)

## Goal

Add three metadata fields to **both** global and local (conversation) documents:

1. **Priority / Reliability** (integer 1-5): Indicates how authoritative the document is.
   - 5 = "very high" — authoritative primary source
   - 4 = "high" — reliable reference
   - 3 = "medium" — standard document (default)
   - 2 = "low" — informal, draft, or less reliable
   - 1 = "very low" — meeting recording, raw notes, unverified

2. **Date Written** (ISO date string or null): When the document was originally authored. Defaults to upload date. Users can override via date picker.

3. **Deprecated** (boolean, default false): Tombstones a document. Deprecated docs are **excluded from RAG** when referenced via `#doc_all` / `#gdoc_all` / `#folder:` / `#tag:`. Individual explicit references (`#doc_1`, `#gdoc_3`) still resolve but inject a caveat.

## Design Decisions

- **Local doc storage**: Priority, date_written, deprecated are stored as **DocIndex attributes** (`_priority`, `_date_written`, `_deprecated`), persisted in the `.index` dill file. The conversation 4-tuple is NOT extended. This is backward-compatible — old pickled DocIndex instances will use `getattr` defaults.
- **Global doc storage**: Also stored as **GlobalDocuments DB columns** (source of truth for list views). When a DocIndex is loaded, the DB values are applied to the DocIndex attributes. This avoids needing to deserialize every `.index` file just to render the list view.
- **RAG behavior**:
  - Deprecated docs excluded from `#doc_all`, `#gdoc_all`, `#folder:`, `#tag:` resolution. Explicit `#doc_N` / `#gdoc_N` still resolve but inject a caveat: `[DEPRECATED DOCUMENT — included for reference only, prefer other sources]`.
  - Multi-doc references sorted by priority (descending), then date_written (descending, most recent first). Equal-priority docs keep their original positional order.
  - Priority described to LLM using words: "very high", "high", "medium", "low", "very low" — NOT numbers. Injected per-doc in the context preamble.
- **Edit UI**: Inline on doc row — small dropdown for priority, date input for date_written, checkbox for deprecated. No separate edit modal.
- **opencode_client**: No changes needed — it's a session/message bridge, not a document proxy. MCP tool changes flow through automatically.

## What Is NOT Changing

- Tuple structure for `uploaded_documents_list` and `message_attached_documents_list` — stays as 4-tuple / 3-tuple
- `#doc_N` / `#gdoc_N` numbering — positional, unchanged
- Tags system — unaffected
- Folder system — unaffected
- DocIndex class hierarchy — no new subclasses
- File browser behavior — no changes

---

## Current State

### Global Documents DB (GlobalDocuments table)
```
doc_id, user_email, display_name, doc_source, doc_storage,
title, short_summary, created_at, updated_at, folder_id, index_type
```
11 columns total. `folder_id` and `index_type` added via idempotent ALTER TABLE.

### Local Documents (Conversation state)
- `uploaded_documents_list`: 4-tuple `(doc_id, doc_storage, doc_source, display_name)`
- `message_attached_documents_list`: 3-tuple `(doc_id, doc_storage, doc_source)`
- Metadata lives in the DocIndex `.index` file (dill-serialized)

### DocIndex.get_short_info() returns
```python
{visible, doc_id, source, title, short_summary, summary, display_name, is_fast_index}
```

### Tool/MCP returns for doc listings
- Conversation docs: `{index, doc_id, title, short_summary, doc_storage_path, source, display_name}`
- Global docs: `{index, doc_id, display_name, title, short_summary, doc_storage_path, source, folder_id, tags}`
- Global doc info: `{doc_id, display_name, title, short_summary, doc_storage_path, source, created_at, updated_at}`

---

## Target State

### Global Documents DB
```
doc_id, user_email, display_name, doc_source, doc_storage,
title, short_summary, created_at, updated_at, folder_id, index_type,
priority, date_written, deprecated                                    ← NEW
```

### DocIndex attributes (both local and global)
```python
self._priority = 3          # int 1-5, default 3 ("medium")
self._date_written = None   # ISO date string or None (defaults to upload date)
self._deprecated = False    # bool
```

### DocIndex.get_short_info() returns
```python
{visible, doc_id, source, title, short_summary, summary, display_name, is_fast_index,
 priority, date_written, deprecated}                                   ← NEW
```

### Priority label mapping (used in LLM context and UI)
```python
PRIORITY_LABELS = {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}
```

---

## Files to Modify

| File | Change |
|------|--------|
| `database/connection.py` | 3 new ALTER TABLE migrations for `priority`, `date_written`, `deprecated` |
| `database/global_docs.py` | Update `add_global_doc()`, `list_global_docs()`, `get_global_doc()`, `update_global_doc_metadata()` |
| `DocIndex.py` | Add `_priority`, `_date_written`, `_deprecated` attrs; update `get_short_info()` |
| `Conversation.py` | Update `add_fast_uploaded_document()`, `add_uploaded_document()`, `add_message_attached_document()` to accept new params; update `get_uploaded_documents()` / `get_global_documents_for_query()` for RAG behavior; update `_inject_dynamic_doc_descriptions()` |
| `endpoints/documents.py` | Accept new form fields on upload; return new fields on list/info |
| `endpoints/global_docs.py` | Accept new form fields on upload/promote; add `PATCH` endpoint for metadata edit; return new fields on list/info |
| `interface/interface.html` | Add form fields to both upload modals; add inline edit controls to doc rows |
| `interface/local-docs-manager.js` | Upload reads new fields; renderList shows badges + inline edit |
| `interface/global-docs-manager.js` | Upload reads new fields; renderList shows badges + inline edit |
| `code_common/tools.py` | Update 4 doc tool handlers to return new fields; update dynamic descriptions |
| `mcp_server/docs.py` | Update 4 MCP tool handlers to return new fields |
| `interface/service-worker.js` | Bump CACHE_VERSION |

---

## Phase 0 — DocIndex Attributes & DB Schema (Foundation)

Pure additions. No behavior change until wired up.

### Task 0.1 — Add DocIndex attributes

**File:** `DocIndex.py`

In `DocIndex.__init__()` (around line 1018, after `_display_name`):

```python
self._priority = 3          # 1-5 scale, default "medium"
self._date_written = None   # ISO date string, e.g. "2026-03-01"
self._deprecated = False
```

Add module-level constant (near top of file or near `get_short_info`):

```python
PRIORITY_LABELS = {1: "very low", 2: "low", 3: "medium", 4: "high", 5: "very high"}
```

Update `get_short_info()` (line ~1952-1967) to include 3 new keys:

```python
info = {
    # ... existing 8 keys ...
    "priority": getattr(self, "_priority", 3),
    "priority_label": PRIORITY_LABELS.get(getattr(self, "_priority", 3), "medium"),
    "date_written": getattr(self, "_date_written", None),
    "deprecated": getattr(self, "_deprecated", False),
}
```

All uses of `getattr` with defaults ensure backward compatibility with old pickled instances.

### Task 0.2 — Add GlobalDocuments columns

**File:** `database/connection.py`

Add 3 idempotent ALTER TABLE migrations (after the existing `index_type` migration around line 328):

```python
# Priority: 1-5 reliability/authority scale, default 3 ("medium")
try:
    cursor.execute("ALTER TABLE GlobalDocuments ADD COLUMN priority INTEGER DEFAULT 3")
except Exception:
    pass

# Date written: ISO date string, defaults to NULL (UI will default to created_at)
try:
    cursor.execute("ALTER TABLE GlobalDocuments ADD COLUMN date_written TEXT DEFAULT NULL")
except Exception:
    pass

# Deprecated: tombstone flag
try:
    cursor.execute("ALTER TABLE GlobalDocuments ADD COLUMN deprecated INTEGER DEFAULT 0")
except Exception:
    pass
```

### Task 0.3 — Update database/global_docs.py functions

**`add_global_doc()`** — add 3 new parameters:

```python
def add_global_doc(
    *, users_dir, user_email, doc_id, doc_source, doc_storage,
    title="", short_summary="", display_name="",
    folder_id=None, index_type="full",
    priority=3, date_written=None, deprecated=False,    # ← NEW
) -> bool:
```

Update the INSERT statement to include `priority`, `date_written`, `deprecated`.

**`list_global_docs()`** — update SELECT to include new columns. Add to the returned dict:
- `"priority": row["priority"] or 3`
- `"date_written": row["date_written"]`
- `"deprecated": bool(row["deprecated"])`

**`get_global_doc()`** — same: add the 3 new columns to SELECT and returned dict.

**`update_global_doc_metadata()`** — extend to accept `priority`, `date_written`, `deprecated` as optional fields. Add them to the dynamic SET clause alongside existing `title`, `short_summary`, `display_name`.

---

## Phase 1 — Backend Endpoints (Accept & Return New Fields)

### Task 1.1 — Update upload endpoints to accept new fields

**`endpoints/global_docs.py` — `upload_global_doc()`:**

Read from form/JSON:
```python
priority = int(request.form.get('priority', 3) or 3)
date_written = request.form.get('date_written') or None
deprecated = request.form.get('deprecated', '').lower() in ('true', '1', 'yes')
```

Pass to `add_global_doc(..., priority=priority, date_written=date_written, deprecated=deprecated)`.

Also set on the DocIndex after creation:
```python
doc_index._priority = priority
doc_index._date_written = date_written or datetime.now().strftime("%Y-%m-%d")
doc_index._deprecated = deprecated
doc_index.save_local()
```

**`endpoints/documents.py` — `upload_doc_to_conversation_route()`:**

Read from form/JSON:
```python
priority = int(request.form.get('priority', 3) or 3)
date_written = request.form.get('date_written') or None
deprecated = request.form.get('deprecated', '').lower() in ('true', '1', 'yes')
```

Pass to `conversation.add_fast_uploaded_document(..., priority=priority, date_written=date_written, deprecated=deprecated)`.

### Task 1.2 — Update Conversation.py doc-add methods

**`add_fast_uploaded_document()`** (line 1616) — add `priority=3, date_written=None, deprecated=False` parameters. After creating the DocIndex:

```python
doc_index._priority = priority
doc_index._date_written = date_written or datetime.now().strftime("%Y-%m-%d")
doc_index._deprecated = deprecated
doc_index.save_local()
```

**`add_message_attached_document()`** (line 1782) — same pattern. Message attachments default to priority=3, date_written=today, deprecated=False. No UI fields needed (they're lightweight).

**`add_uploaded_document()`** (line 1676, if used for full index) — same pattern.

### Task 1.3 — Update list/info endpoints to return new fields

**`endpoints/documents.py` — `list_documents_by_conversation()`:**

After loading each DocIndex, the `get_short_info()` dict already includes the new fields (from Task 0.1). No additional code needed — but verify the returned JSON includes `priority`, `priority_label`, `date_written`, `deprecated`.

**`endpoints/global_docs.py` — `list_global_docs_route()`:**

The DB query (Task 0.3) already returns the new fields. Include them in the JSON response:
```python
{
    # ... existing fields ...
    "priority": doc.get("priority", 3),
    "priority_label": PRIORITY_LABELS.get(doc.get("priority", 3), "medium"),
    "date_written": doc.get("date_written"),
    "deprecated": doc.get("deprecated", False),
}
```

**`endpoints/global_docs.py` — `get_global_doc_info()`:**

Same — include new fields from DB row.

### Task 1.4 — Add PATCH endpoint for inline metadata edit

**`endpoints/global_docs.py`** — new route:

```python
@global_docs_bp.route('/global_docs/<doc_id>/metadata', methods=['PATCH'])
@login_required
def update_global_doc_metadata_route(doc_id):
    """Update priority, date_written, deprecated (and existing fields) for a global doc."""
    email = session["email"]
    data = request.json or {}

    priority = data.get("priority")       # int 1-5 or None
    date_written = data.get("date_written")  # ISO date or None
    deprecated = data.get("deprecated")   # bool or None

    # Validate priority range
    if priority is not None:
        priority = max(1, min(5, int(priority)))

    update_global_doc_metadata(
        users_dir=state.users_dir, user_email=email, doc_id=doc_id,
        priority=priority, date_written=date_written, deprecated=deprecated,
        # Pass existing params as None to leave unchanged
        title=data.get("title"), short_summary=data.get("short_summary"),
        display_name=data.get("display_name"),
    )

    # Also update the DocIndex on disk
    doc_row = get_global_doc(users_dir=state.users_dir, user_email=email, doc_id=doc_id)
    if doc_row and doc_row.get("doc_storage"):
        doc_index = DocIndex.load_local(doc_row["doc_storage"])
        if doc_index:
            if priority is not None:
                doc_index._priority = priority
            if date_written is not None:
                doc_index._date_written = date_written
            if deprecated is not None:
                doc_index._deprecated = deprecated
            doc_index.save_local()

    return jsonify({"status": "ok"})
```

**`endpoints/documents.py`** — new route for local docs:

```python
@documents_bp.route('/docs/<conversation_id>/<doc_id>/metadata', methods=['PATCH'])
@login_required
def update_conversation_doc_metadata_route(conversation_id, doc_id):
    """Update priority, date_written, deprecated for a conversation doc."""
    data = request.json or {}
    conversation = load_conversation(conversation_id)

    # Find the doc's storage path from the tuple list
    docs_list = conversation.get_field("uploaded_documents_list") or []
    doc_storage = None
    for entry in docs_list:
        if entry[0] == doc_id:
            doc_storage = entry[1]
            break

    if not doc_storage:
        return json_error("Document not found", 404)

    doc_index = DocIndex.load_local(doc_storage)
    if not doc_index:
        return json_error("Could not load document index", 500)

    priority = data.get("priority")
    date_written = data.get("date_written")
    deprecated = data.get("deprecated")

    if priority is not None:
        doc_index._priority = max(1, min(5, int(priority)))
    if date_written is not None:
        doc_index._date_written = date_written
    if deprecated is not None:
        doc_index._deprecated = bool(deprecated)

    doc_index.save_local()
    return jsonify({"status": "ok"})
```

---

## Phase 2 — RAG Behavior Changes

### Task 2.1 — Deprecated doc exclusion

**`Conversation.py` — `get_uploaded_documents_for_query()`** (line ~5447):

When processing `#doc_all`:
- After loading all docs, filter out those with `_deprecated == True`
- For individually-referenced deprecated docs (`#doc_3`), keep them but add caveat

```python
# After loading doc:
if getattr(doc_index, "_deprecated", False):
    if is_all_docs_reference:
        continue  # Skip deprecated in #doc_all
    else:
        # Individual reference — inject caveat
        doc_context = "[DEPRECATED DOCUMENT — included for reference only, prefer other sources]\n" + doc_context
```

**`Conversation.py` — `get_global_documents_for_query()`** (line ~5535):

Same pattern for `#gdoc_all`, `#folder:`, `#tag:`:
- Filter out deprecated docs from batch references
- Keep individually-referenced deprecated docs with caveat

### Task 2.2 — Priority sorting and labeling

**`Conversation.py` — `get_uploaded_documents_for_query()`:**

After collecting all referenced docs, sort by priority then date:

```python
# Sort docs: priority desc, then date_written desc (most recent first)
def _doc_sort_key(doc):
    p = getattr(doc, "_priority", 3)
    d = getattr(doc, "_date_written", "") or ""
    return (-p, d == "", d)  # negate priority for desc; empty dates last; then date desc needs reverse

# Sort: highest priority first, then most recent date first
attached_docs.sort(key=lambda d: (-getattr(d, "_priority", 3),
                                   -(len(getattr(d, "_date_written", "") or "")),  
                                   getattr(d, "_date_written", "") or ""), 
                   reverse=False)
# Simpler: use a tuple sort key
# (-priority, -date_written_sortable)
```

When building the LLM context string for each doc, prefix with priority label:

```python
priority_label = PRIORITY_LABELS.get(getattr(doc, "_priority", 3), "medium")
date_str = getattr(doc, "_date_written", None)
meta_parts = [f"Reliability: {priority_label}"]
if date_str:
    meta_parts.append(f"Date written: {date_str}")

doc_header = f"#doc_{idx} (Title: '{doc.title}') [{', '.join(meta_parts)}]"
```

Example LLM context:
```
#doc_1 (Title: 'RFC 9110: HTTP Semantics') [Reliability: very high, Date written: 2022-06-01]
...content...

#doc_2 (Title: 'Team meeting notes Mar 2026') [Reliability: very low, Date written: 2026-03-05]
...content...
```

**Same pattern for `get_global_documents_for_query()`.**

### Task 2.3 — Update doc_infos string

The `doc_infos` field (injected into the system prompt so the LLM knows available docs) should include priority labels and deprecated status:

```python
# Current format:
# #doc_1: (Title of Doc)[/path/to/file.pdf]

# New format:
# #doc_1: (Title of Doc)[/path/to/file.pdf] [reliability: very high, date: 2026-01-15]
# #doc_2: (Title of Doc)[/path/to/file.pdf] [reliability: low, date: 2025-06-01] [DEPRECATED]
```

Update the `doc_infos` rebuild logic in `add_fast_uploaded_document()`, `add_uploaded_document()`, `delete_uploaded_document()`, and `promote_message_attached_document()`.

---

## Phase 3 — Frontend UI

### Task 3.1 — Upload form fields (both modals)

**`interface/interface.html` — Global docs modal upload card:**

Add after the display_name input, before the upload button:

```html
<!-- Priority / Reliability -->
<div class="form-group">
    <label for="global-doc-priority" class="small text-muted mb-1">Reliability</label>
    <select id="global-doc-priority" class="form-control form-control-sm">
        <option value="5">Very High — authoritative source</option>
        <option value="4">High — reliable reference</option>
        <option value="3" selected>Medium — standard document</option>
        <option value="2">Low — draft / informal</option>
        <option value="1">Very Low — meeting notes / unverified</option>
    </select>
</div>

<!-- Date Written -->
<div class="form-group">
    <label for="global-doc-date-written" class="small text-muted mb-1">Date Written</label>
    <input type="date" id="global-doc-date-written" class="form-control form-control-sm"
           placeholder="Defaults to today">
</div>
```

**`interface/interface.html` — Conversation docs modal upload card:**

Same fields with `conv-doc-priority` and `conv-doc-date-written` IDs.

Note: Deprecated checkbox is NOT shown on upload (new docs shouldn't start deprecated). It's only available in the list view for existing docs.

### Task 3.2 — JS upload methods read new fields

**`interface/global-docs-manager.js` — `upload()`:**

```javascript
var priority = $('#global-doc-priority').val() || '3';
var dateWritten = $('#global-doc-date-written').val() || '';

DocsManagerUtils.uploadWithProgress({
    url: '/global_docs/upload',
    file: file,
    displayName: displayName,
    extraFields: {
        priority: priority,
        date_written: dateWritten
    },
    // ... existing opts
});
```

**`interface/local-docs-manager.js` — `LocalDocsManager.upload()`:**

```javascript
var priority = $('#conv-doc-priority').val() || '3';
var dateWritten = $('#conv-doc-date-written').val() || '';

DocsManagerUtils.uploadWithProgress({
    url: '/upload_doc_to_conversation/' + conversationId,
    file: file,
    displayName: displayName,
    extraFields: {
        priority: priority,
        date_written: dateWritten
    },
    // ... existing opts
});
```

`DocsManagerUtils.uploadWithProgress()` already supports `extraFields` — it appends them to FormData. No changes needed there.

### Task 3.3 — Doc list rendering with inline edit

**`interface/global-docs-manager.js` — `renderList()`:**

Each doc row currently shows: `#gdoc_N` badge, display name, title, source, tag chips, action buttons.

Add after the title/source section, before action buttons:

```javascript
// Priority badge (click to cycle)
var priorityLabels = {1:'Very Low',2:'Low',3:'Medium',4:'High',5:'Very High'};
var priorityColors = {1:'secondary',2:'warning',3:'info',4:'primary',5:'success'};
var p = doc.priority || 3;
var $priorityBadge = $('<select class="form-control form-control-sm d-inline-block" style="width:auto;font-size:0.75rem;padding:1px 4px;height:auto;">')
    .append('<option value="5"' + (p===5?' selected':'') + '>⭐ Very High</option>')
    .append('<option value="4"' + (p===4?' selected':'') + '>High</option>')
    .append('<option value="3"' + (p===3?' selected':'') + '>Medium</option>')
    .append('<option value="2"' + (p===2?' selected':'') + '>Low</option>')
    .append('<option value="1"' + (p===1?' selected':'') + '>Very Low</option>')
    .on('change', function() {
        GlobalDocsManager._updateMetadata(doc.doc_id, {priority: parseInt($(this).val())});
    });

// Date written (inline date input)
var $dateInput = $('<input type="date" class="form-control form-control-sm d-inline-block" style="width:auto;font-size:0.75rem;padding:1px 4px;height:auto;">')
    .val(doc.date_written || '')
    .attr('title', 'Date written')
    .on('change', function() {
        GlobalDocsManager._updateMetadata(doc.doc_id, {date_written: $(this).val()});
    });

// Deprecated checkbox
var $deprecatedCb = $('<input type="checkbox" class="ml-2" title="Mark as deprecated">')
    .prop('checked', doc.deprecated || false)
    .on('change', function() {
        GlobalDocsManager._updateMetadata(doc.doc_id, {deprecated: $(this).is(':checked')});
    });
var $deprecatedLabel = $('<label class="small text-muted mb-0 ml-1">Deprecated</label>');
```

**New helper method — `GlobalDocsManager._updateMetadata(docId, fields)`:**

```javascript
_updateMetadata: function(docId, fields) {
    $.ajax({
        url: '/global_docs/' + docId + '/metadata',
        method: 'PATCH',
        contentType: 'application/json',
        data: JSON.stringify(fields),
        success: function() {
            showToast('Document updated', 'success');
        },
        error: function() {
            showToast('Failed to update document', 'error');
            GlobalDocsManager.refresh();  // revert UI
        }
    });
}
```

**`interface/local-docs-manager.js` — `LocalDocsManager.renderList()`:**

Same pattern but targeting the conversation doc PATCH endpoint:

```javascript
_updateMetadata: function(conversationId, docId, fields) {
    $.ajax({
        url: '/docs/' + conversationId + '/' + docId + '/metadata',
        method: 'PATCH',
        contentType: 'application/json',
        data: JSON.stringify(fields),
        success: function() { showToast('Document updated', 'success'); },
        error: function() {
            showToast('Failed to update document', 'error');
            LocalDocsManager.refresh(conversationId);
        }
    });
}
```

### Task 3.4 — Visual treatment for deprecated docs

Deprecated docs in the list view get:
- Reduced opacity (`opacity: 0.5`)
- Strikethrough on title text
- "DEPRECATED" badge in red

```javascript
if (doc.deprecated) {
    $row.css('opacity', '0.5');
    $title.css('text-decoration', 'line-through');
    $row.find('.doc-badges').append('<span class="badge badge-danger ml-1">DEPRECATED</span>');
}
```

---

## Phase 4 — Tool Calling Framework

### Task 4.1 — Update document tool handlers in code_common/tools.py

**`handle_docs_list_conversation_docs`** (line ~1291):

Add new fields to each doc entry in the returned JSON:
```python
{
    # ... existing fields ...
    "priority": info.get("priority", 3),
    "priority_label": info.get("priority_label", "medium"),
    "date_written": info.get("date_written"),
    "deprecated": info.get("deprecated", False),
}
```

**`handle_docs_list_global_docs`** (line ~1361):

The DB query already returns the new fields (Phase 0 Task 0.3). Add to JSON:
```python
{
    # ... existing fields ...
    "priority": doc.get("priority", 3),
    "priority_label": PRIORITY_LABELS.get(doc.get("priority", 3), "medium"),
    "date_written": doc.get("date_written"),
    "deprecated": doc.get("deprecated", False),
}
```

**`handle_docs_get_info`** (line ~1513):

Add new fields from DocIndex attributes:
```python
{
    # ... existing fields ...
    "priority": getattr(doc, "_priority", 3),
    "priority_label": PRIORITY_LABELS.get(getattr(doc, "_priority", 3), "medium"),
    "date_written": getattr(doc, "_date_written", None),
    "deprecated": getattr(doc, "_deprecated", False),
}
```

**`handle_docs_get_global_doc_info`** (line ~1604):

Add from DB row:
```python
{
    # ... existing fields ...
    "priority": row.get("priority", 3),
    "priority_label": PRIORITY_LABELS.get(row.get("priority", 3), "medium"),
    "date_written": row.get("date_written"),
    "deprecated": row.get("deprecated", False),
}
```

### Task 4.2 — Update dynamic description injection

**`Conversation.py` — `_inject_dynamic_doc_descriptions()`** (line ~6495):

Update the doc listing format to include priority and deprecated:

```python
# Current format:
#   1. My Paper (doc_id: abc123, path: /storage/...)
# New format:
#   1. My Paper (doc_id: abc123, path: /storage/..., reliability: very high, date: 2026-01-15)
#   2. Old Notes (doc_id: def456, path: /storage/..., reliability: low) [DEPRECATED]
```

For global docs:
```python
label = PRIORITY_LABELS.get(gdoc.get("priority", 3), "medium")
deprecated_tag = " [DEPRECATED]" if gdoc.get("deprecated") else ""
date_part = f", date: {gdoc['date_written']}" if gdoc.get("date_written") else ""
line = f"  {idx}. {name} (doc_id: {gdoc['doc_id']}, path: {path}, reliability: {label}{date_part}){deprecated_tag}"
```

For conversation docs (load DocIndex to get attributes):
```python
label = PRIORITY_LABELS.get(getattr(doc_index, "_priority", 3), "medium")
deprecated_tag = " [DEPRECATED]" if getattr(doc_index, "_deprecated", False) else ""
date_part = f", date: {getattr(doc_index, '_date_written', '')}" if getattr(doc_index, "_date_written", None) else ""
line = f"  {idx}. {name} (#doc_{idx}, path: {path}, reliability: {label}{date_part}){deprecated_tag}"
```

---

## Phase 5 — MCP Server

### Task 5.1 — Update MCP doc tool handlers

**`mcp_server/docs.py`:**

**`docs_list_global_docs()`** — same as tool handler: add `priority`, `priority_label`, `date_written`, `deprecated` to JSON.

**`docs_list_conversation_docs()`** — load DocIndex, add new fields from `get_short_info()`.

**`docs_get_info()`** — add new fields from DocIndex attributes.

**`docs_get_global_doc_info()`** — add new fields from DB row.

All other doc tools (query, full_text, answer_question) return raw text content, not metadata — no changes needed.

### Task 5.2 — Update MCP tool descriptions

For `docs_list_global_docs` and `docs_list_conversation_docs`, update the tool descriptions to mention the new metadata fields:

```python
description = (
    "List all global documents for the current user. "
    "Returns doc_id, display_name, title, short_summary, doc_storage_path, source, "
    "folder_id, tags, priority (1-5 with label), date_written, and deprecated status. "
    "Priority indicates document reliability: 5=very high (authoritative), 3=medium (default), 1=very low. "
    "Deprecated documents are tombstoned and should be deprioritized."
)
```

---

## Phase 6 — Promote Flow Updates

### Task 6.1 — Promote conversation doc → global doc

**`endpoints/global_docs.py` — `promote_doc_to_global()`:**

After copying the DocIndex to global storage:
1. Read `_priority`, `_date_written`, `_deprecated` from the DocIndex
2. Pass them to `add_global_doc(..., priority=p, date_written=d, deprecated=dep)`

```python
doc_index = DocIndex.load_local(target_storage)
priority = getattr(doc_index, "_priority", 3)
date_written = getattr(doc_index, "_date_written", None)
deprecated = getattr(doc_index, "_deprecated", False)

add_global_doc(
    ...,
    priority=priority,
    date_written=date_written,
    deprecated=deprecated,
)
```

### Task 6.2 — Promote message attachment → conversation doc

**`Conversation.py` — `promote_message_attached_document()`:**

Preserve metadata from the FastDocIndex when creating the full ImmediateDocIndex:

```python
old_priority = getattr(fast_doc, "_priority", 3)
old_date = getattr(fast_doc, "_date_written", None)
old_deprecated = getattr(fast_doc, "_deprecated", False)

# ... create_immediate_document_index ...

new_doc._priority = old_priority
new_doc._date_written = old_date
new_doc._deprecated = old_deprecated
new_doc.save_local()
```

---

## Phase 7 — Documentation

### Task 7.1 — Update feature docs

Update these files to reflect the new metadata:
- `documentation/features/global_docs/README.md` — new DB columns, API response fields, upload form fields, inline edit
- `documentation/features/documents/local_docs_features.md` — DocIndex attributes, upload fields, inline edit
- `documentation/features/documents/doc_flow_reference.md` — get_short_info() new fields, RAG behavior changes
- `documentation/features/tool_calling/README.md` — updated document tool return schemas

---

## Implementation Order

1. **Phase 0** — DocIndex attrs + DB schema + database functions. Pure additions, zero behavior change.
2. **Phase 1** — Backend endpoints accept and return new fields.
3. **Phase 2** — RAG behavior (deprecated exclusion, priority sorting, LLM labels).
4. **Phase 3** — Frontend UI (upload forms, inline edit, visual treatment).
5. **Phase 4** — Tool calling framework updates.
6. **Phase 5** — MCP server updates.
7. **Phase 6** — Promote flow metadata preservation.
8. **Phase 7** — Documentation updates.

Build incrementally: each phase is independently deployable. Phase 0+1 alone gives the data layer. Phase 2 adds RAG intelligence. Phase 3 adds user control. Phases 4-5 expose to LLM tools.

---

## Risk Analysis

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Old pickled DocIndex missing `_priority`/`_date_written`/`_deprecated` | Certain (all existing docs) | `getattr(self, "_priority", 3)` with defaults everywhere |
| Priority sort changes doc order in existing conversations | Medium | Sort is only applied during query resolution, not in the stored list. Positional `#doc_N` numbering unchanged. |
| Deprecated docs silently disappearing from `#doc_all` confuses users | Low | The doc_infos system prompt still shows `[DEPRECATED]` tag, so the LLM can explain if asked |
| Inline edit on doc rows feels cramped on mobile | Medium | Use responsive classes: show badges on mobile, show full inline controls on desktop |
| DB migration adds columns with defaults — no data loss | None | ALTER TABLE ADD COLUMN with DEFAULT is safe on SQLite |
| `date_written` date picker format varies by browser | Low | HTML5 `<input type="date">` is ISO-formatted (YYYY-MM-DD) in all modern browsers |
| MCP and tool-calling return schemas diverge | Low | Both read from the same DB / DocIndex; keep field names identical in both codebases |

---

## Summary of All Code Changes

### `DocIndex.py`
- Add `PRIORITY_LABELS` dict
- Add `_priority`, `_date_written`, `_deprecated` in `__init__()` (and `FastDocIndex.__init__()`)
- Update `get_short_info()` to return 3 new keys + `priority_label`

### `database/connection.py`
- 3 idempotent ALTER TABLE migrations

### `database/global_docs.py`
- `add_global_doc()`: 3 new parameters, updated INSERT
- `list_global_docs()`: updated SELECT, 3 new dict keys
- `get_global_doc()`: updated SELECT, 3 new dict keys
- `update_global_doc_metadata()`: 3 new optional parameters

### `endpoints/global_docs.py`
- `upload_global_doc()`: read 3 new form fields, pass to add_global_doc + set on DocIndex
- `list_global_docs_route()`: include new fields in response
- `get_global_doc_info()`: include new fields in response
- `promote_doc_to_global()`: preserve metadata from DocIndex
- NEW: `PATCH /global_docs/<doc_id>/metadata` for inline edit

### `endpoints/documents.py`
- `upload_doc_to_conversation_route()`: read 3 new form fields, pass to add_fast_uploaded_document
- `list_documents_by_conversation()`: get_short_info() already returns new fields
- NEW: `PATCH /docs/<conversation_id>/<doc_id>/metadata` for inline edit

### `Conversation.py`
- `add_fast_uploaded_document()`: 3 new params, set on DocIndex
- `add_message_attached_document()`: set defaults on DocIndex
- `promote_message_attached_document()`: preserve metadata across promote
- `get_uploaded_documents_for_query()`: deprecated exclusion, priority sort, LLM labels
- `get_global_documents_for_query()`: deprecated exclusion, priority sort, LLM labels
- `_inject_dynamic_doc_descriptions()`: include priority/deprecated in doc listings
- `doc_infos` rebuild: include priority labels and deprecated tags

### `code_common/tools.py`
- `handle_docs_list_conversation_docs`: 4 new fields in JSON
- `handle_docs_list_global_docs`: 4 new fields in JSON
- `handle_docs_get_info`: 4 new fields in JSON
- `handle_docs_get_global_doc_info`: 4 new fields in JSON

### `mcp_server/docs.py`
- `docs_list_conversation_docs()`: 4 new fields in JSON
- `docs_list_global_docs()`: 4 new fields in JSON
- `docs_get_info()`: 4 new fields in JSON
- `docs_get_global_doc_info()`: 4 new fields in JSON
- Updated tool descriptions

### `interface/interface.html`
- Global docs upload: priority dropdown + date picker
- Conversation docs upload: priority dropdown + date picker

### `interface/global-docs-manager.js`
- `upload()`: read priority + date_written from form
- `renderList()`: inline priority dropdown, date input, deprecated checkbox, visual treatment
- NEW: `_updateMetadata(docId, fields)` helper

### `interface/local-docs-manager.js`
- `LocalDocsManager.upload()`: read priority + date_written from form
- `LocalDocsManager.renderList()`: inline priority dropdown, date input, deprecated checkbox
- NEW: `LocalDocsManager._updateMetadata(conversationId, docId, fields)` helper

### `interface/service-worker.js`
- Bump CACHE_VERSION
