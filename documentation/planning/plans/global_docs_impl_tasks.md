# Global Docs Folders & Tags — Granular Implementation Tasks

**Status:** Ready to implement  
**Parent plan:** `global_docs_folders_tags.plan.md`  
**Created:** 2026-02-26  
**Codebase snapshot:** Verified against actual files on disk (line numbers current as of this writing)

---

## Current Codebase State (Key Facts)

- `database/connection.py` — 312 lines. `create_tables()` at line 65. `GlobalDocuments` table at lines 142-153. Last index at line 308. `conn.commit()` at line 311.
- `database/global_docs.py` — 215 lines. Functions: `_db_path` (24), `add_global_doc` (28), `list_global_docs` (76), `get_global_doc` (113), `delete_global_doc` (146), `update_global_doc_metadata` (169).
- `endpoints/global_docs.py` — 346 lines. Blueprint `global_docs_bp`. Endpoints: upload (47), list (126), info (151), download (186), serve (232), delete (246), promote (266).
- `endpoints/__init__.py` — 78 lines. `global_docs_bp` registered at line 72. `file_browser_bp` at line 78 (last entry).
- `Conversation.py` — `get_global_documents_for_query()` at line 5540. `#gdoc_N` regex at line 5556 (`gdoc_refs = re.findall(...)`). `#gdoc_all` check at line 6666.
- `interface/global-docs-manager.js` — 232 lines. `renderList()` at line 84. `refresh()` at line 150. `setup()` at line 160. `$(document).ready` at line 230.
- `interface/interface.html` — `#global-docs-modal` at line 439. Modal body upload card at 449-477. List card at 478-491. Modal body closes at 492.
- `interface/common-chat.js` — 4039 lines. `@` autocomplete `handleInput()` at line 3494. `fetchAutocompleteResults()` at line 3541.
- No `database/doc_folders.py` or `database/doc_tags.py` exist yet.
- No `endpoints/doc_folders.py` exists yet.

---

## Phase 0: DB Schema + Helpers

**Goal:** Foundation only. No UI, no endpoints. Safe to ship to production immediately.

### Task 0.1 — Add new tables to `database/connection.py`

**File:** `database/connection.py`  
**What:** Add `GlobalDocFolders` CREATE TABLE, `GlobalDocTags` CREATE TABLE, `ALTER TABLE GlobalDocuments ADD COLUMN folder_id`, and 6 new indexes.

**Insertion point:** After line 153 (end of `sql_create_global_documents_table`), before line 155 (`# Extension custom scripts table`). Add two new SQL strings. Then in the execute block, after line 295 (`idx_GlobalDocuments_created_at` index), add the `ALTER TABLE` try/except and 6 new index `cur.execute()` calls. `conn.commit()` stays last.

**New SQL strings to add (after line 153):**
```python
sql_create_global_doc_folders_table = """CREATE TABLE IF NOT EXISTS GlobalDocFolders (
    folder_id     TEXT NOT NULL,
    user_email    TEXT NOT NULL,
    name          TEXT NOT NULL,
    parent_id     TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (folder_id, user_email)
);"""

sql_create_global_doc_tags_table = """CREATE TABLE IF NOT EXISTS GlobalDocTags (
    doc_id        TEXT NOT NULL,
    user_email    TEXT NOT NULL,
    tag           TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (doc_id, user_email, tag),
    FOREIGN KEY (doc_id, user_email) REFERENCES GlobalDocuments (doc_id, user_email)
);"""
```

**Add `create_table()` calls (after line 193, inside the `if conn is not None:` block, after existing create_table calls):**
```python
create_table(conn, sql_create_global_doc_folders_table)
create_table(conn, sql_create_global_doc_tags_table)
```

**Add after the `idx_GlobalDocuments_created_at` block (after line 296), before `idx_CustomScripts_user`:**
```python
# folder_id column on GlobalDocuments (additive migration)
try:
    cur.execute("ALTER TABLE GlobalDocuments ADD COLUMN folder_id TEXT DEFAULT NULL")
    log.info("Added folder_id column to GlobalDocuments table")
except Exception:
    pass  # Column already exists

cur.execute("CREATE INDEX IF NOT EXISTS idx_GlobalDocFolders_user ON GlobalDocFolders (user_email)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_GlobalDocFolders_parent ON GlobalDocFolders (user_email, parent_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_GlobalDocuments_folder ON GlobalDocuments (user_email, folder_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_user ON GlobalDocTags (user_email)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_tag ON GlobalDocTags (user_email, tag)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_doc ON GlobalDocTags (doc_id, user_email)")
```

**Test:** `conda activate science-reader && python -c "from database.connection import create_tables; create_tables(users_dir='users'); print('OK')"` — must print OK with no errors.

---

### Task 0.2 — Create `database/doc_folders.py`

**File:** `database/doc_folders.py` (new file)  
**Pattern:** Mirror `database/global_docs.py` exactly — keyword-only args, `_db_path()`, open/close connection per function, try/except logging.

**Functions to implement:**

```python
def _db_path(*, users_dir: str) -> str:
    return os.path.join(users_dir, "users.db")

def create_folder(*, users_dir: str, user_email: str, name: str, parent_id: Optional[str] = None) -> str:
    """Create a new folder. Returns folder_id (uuid4 string)."""
    # INSERT INTO GlobalDocFolders (folder_id, user_email, name, parent_id, created_at, updated_at)
    # Return folder_id

def rename_folder(*, users_dir: str, user_email: str, folder_id: str, new_name: str) -> bool:
    """Rename a folder. Returns True on success."""
    # UPDATE GlobalDocFolders SET name=?, updated_at=? WHERE folder_id=? AND user_email=?

def move_folder(*, users_dir: str, user_email: str, folder_id: str, new_parent_id: Optional[str]) -> bool:
    """Move a folder to a new parent (None = root). Returns True on success."""
    # UPDATE GlobalDocFolders SET parent_id=?, updated_at=? WHERE folder_id=? AND user_email=?

def delete_folder(*, users_dir: str, user_email: str, folder_id: str) -> bool:
    """Delete a folder row only. Does NOT delete docs or sub-folders.
    Caller must handle orphan docs (move to parent or delete) before calling this."""
    # DELETE FROM GlobalDocFolders WHERE folder_id=? AND user_email=?

def list_folders(*, users_dir: str, user_email: str) -> list[dict]:
    """Return all folders for user as flat list. JS builds tree from parent_id."""
    # SELECT folder_id, name, parent_id, created_at, updated_at FROM GlobalDocFolders WHERE user_email=?
    # Also compute doc_count: SELECT COUNT(*) FROM GlobalDocuments WHERE user_email=? AND folder_id=?
    # Add doc_count to each folder dict

def get_folder(*, users_dir: str, user_email: str, folder_id: str) -> Optional[dict]:
    """Get single folder by ID."""

def get_folder_by_name(*, users_dir: str, user_email: str, name: str) -> Optional[dict]:
    """Get folder by name (case-insensitive). Used for #folder: chat reference resolution."""
    # SELECT ... WHERE user_email=? AND lower(name)=lower(?)

def assign_doc_to_folder(*, users_dir: str, user_email: str, doc_id: str, folder_id: Optional[str]) -> bool:
    """Set GlobalDocuments.folder_id for a doc. Pass None to unfile (move to root)."""
    # UPDATE GlobalDocuments SET folder_id=?, updated_at=? WHERE doc_id=? AND user_email=?

def get_docs_in_folder(*, users_dir: str, user_email: str, folder_id: Optional[str], recursive: bool = False) -> list[str]:
    """Return doc_ids in a folder. If recursive=True, includes all descendant folders.
    folder_id=None means Unfiled (GlobalDocuments.folder_id IS NULL)."""
    # Non-recursive: SELECT doc_id FROM GlobalDocuments WHERE user_email=? AND folder_id IS [NOT] NULL / = ?
    # Recursive: BFS queue over GlobalDocFolders child folders
```

**Test:** `python -c "from database.doc_folders import create_folder, list_folders; fid = create_folder(users_dir='users', user_email='test@test.com', name='Test'); print(list_folders(users_dir='users', user_email='test@test.com'))"` — must show list with one folder.

---

### Task 0.3 — Create `database/doc_tags.py`

**File:** `database/doc_tags.py` (new file)  
**Pattern:** Same as `doc_folders.py`.

**Functions:**
```python
def add_tag(*, users_dir: str, user_email: str, doc_id: str, tag: str) -> bool:
    """Add a single tag to a doc. No-op if already exists (INSERT OR IGNORE)."""

def remove_tag(*, users_dir: str, user_email: str, doc_id: str, tag: str) -> bool:
    """Remove a single tag from a doc."""

def set_tags(*, users_dir: str, user_email: str, doc_id: str, tags: list[str]) -> bool:
    """Replace all tags for a doc atomically (DELETE existing + INSERT new)."""
    # In a transaction: DELETE FROM GlobalDocTags WHERE doc_id=? AND user_email=?
    # Then INSERT OR IGNORE for each tag in tags

def list_tags_for_doc(*, users_dir: str, user_email: str, doc_id: str) -> list[str]:
    """Return sorted list of tags for a single doc."""

def list_all_tags(*, users_dir: str, user_email: str) -> list[str]:
    """Return sorted list of distinct tags for the user (for autocomplete)."""
    # SELECT DISTINCT tag FROM GlobalDocTags WHERE user_email=? ORDER BY tag

def list_docs_by_tag(*, users_dir: str, user_email: str, tag: str) -> list[str]:
    """Return doc_ids that have a given tag (case-insensitive)."""
    # SELECT doc_id FROM GlobalDocTags WHERE user_email=? AND lower(tag)=lower(?)
```

**Test:** Add a tag, list it, remove it, verify empty.

---

### Task 0.4 — Update `database/global_docs.py`

**File:** `database/global_docs.py`  
**What:** Two targeted changes:

1. **`list_global_docs()`** (line 76): Add LEFT JOIN to include tags. Change SQL from plain `SELECT ... FROM GlobalDocuments` to:
   ```sql
   SELECT gd.doc_id, gd.user_email, gd.display_name, gd.doc_source, gd.doc_storage,
          gd.title, gd.short_summary, gd.created_at, gd.updated_at, gd.folder_id,
          GROUP_CONCAT(gt.tag, ',') as tags_csv
   FROM GlobalDocuments gd
   LEFT JOIN GlobalDocTags gt ON gd.doc_id = gt.doc_id AND gd.user_email = gt.user_email
   WHERE gd.user_email = ?
   GROUP BY gd.doc_id, gd.user_email
   ORDER BY gd.created_at DESC
   ```
   Post-process: split `tags_csv` → `tags` list. Add `folder_id` to returned dict.

2. **`add_global_doc()`** (line 28): Accept optional `folder_id: Optional[str] = None` param. Include in INSERT.

3. **New function** `list_global_docs_by_folder(*, users_dir, user_email, folder_id)` — thin wrapper calling `get_docs_in_folder()` then filtering `list_global_docs()` results. Add after `list_global_docs()`.

**Caution:** The `list_global_docs()` return value is consumed in several places. Adding `tags` and `folder_id` to the dict is purely additive — no consumer will break.

---

## Phase 1: API Endpoints

### Task 1.1 — Create `endpoints/doc_folders.py`

**File:** `endpoints/doc_folders.py` (new file)  
**Pattern:** Follow `endpoints/global_docs.py` — Blueprint, `@login_required`, `attach_keys`, `get_state_and_keys`, `json_error`.

**Endpoints:**

```
GET  /doc_folders               → list_folders() → [{folder_id, name, parent_id, doc_count, created_at}]
POST /doc_folders               → create_folder(name, parent_id?) → {folder_id, name, parent_id, created_at}
PATCH /doc_folders/<folder_id>  → rename or reparent {name?, parent_id?}
DELETE /doc_folders/<folder_id> → delete; action= "move_to_parent" (default) or "delete_docs"
POST /doc_folders/<folder_id>/assign → assign doc {doc_id} to folder
GET  /doc_folders/<folder_id>/docs  → get_docs_in_folder(recursive=request.args.get('recursive')=='true')
GET  /doc_folders/autocomplete      → list_folders() filtered by ?prefix=, return names only
```

**DELETE behavior:**
- `move_to_parent`: call `assign_doc_to_folder(folder_id=parent_id)` for all docs in folder. Then call `move_folder` for direct sub-folders to `parent_id`. Then `delete_folder`.
- `delete_docs`: this is intentionally NOT auto-implemented — it requires confirmation from caller. Endpoint accepts `action=delete_docs` but calls existing `delete_global_doc()` for each doc first, then recursively for sub-folders.

**Auth pattern** (copy from `global_docs.py` line 47-65):
```python
from endpoints.auth import login_required
from endpoints.request_context import attach_keys, get_state_and_keys
```
Get `user_email` via `get_state_and_keys(request)`.

**Rate limiting:** `@limiter.limit("100 per minute")` on write endpoints, `@limiter.limit("30 per minute")` on reads.

---

### Task 1.2 — Add tag endpoints to `endpoints/global_docs.py`

**File:** `endpoints/global_docs.py`  
**What:** Add 3 new routes at the bottom (after line 346):

```python
@global_docs_bp.route("/global_docs/<doc_id>/tags", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def set_doc_tags(doc_id: str):
    """Set tags for a doc. Body: {tags: ["ai", "ml"]}. Replaces all existing tags."""
    # get user_email, call set_tags(users_dir, user_email, doc_id, tags)
    # return {"status": "ok", "tags": tags}

@global_docs_bp.route("/global_docs/tags", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_all_tags_route():
    """List distinct tags for user. ?prefix= for autocomplete filtering."""
    # list_all_tags(users_dir, user_email)
    # filter by prefix if provided
    # return {"tags": [...]}

@global_docs_bp.route("/global_docs/autocomplete", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def global_docs_autocomplete():
    """Combined autocomplete for #folder:Name and #tag:Name in chat.
    ?type=folder&prefix=Re or ?type=tag&prefix=ml"""
```

**Import to add at top of file:**
```python
from database.doc_tags import set_tags, list_all_tags
```

---

### Task 1.3 — Update upload and promote endpoints in `endpoints/global_docs.py`

**File:** `endpoints/global_docs.py`  
**What:** Two small changes:

1. **`upload_global_doc()`** (line 47): Extract `folder_id = request.form.get('folder_id') or request.json.get('folder_id') if request.is_json else None`. Pass to `add_global_doc(..., folder_id=folder_id)`.

2. **`promote_doc_to_global()`** (line 271): Extract `folder_id` from request JSON body. Pass to `add_global_doc(..., folder_id=folder_id)`.

---

### Task 1.4 — Register `doc_folders_bp` in `endpoints/__init__.py`

**File:** `endpoints/__init__.py`  
**What:** Add two lines — import and register. After line 50 (`from .file_browser import file_browser_bp`):
```python
from .doc_folders import doc_folders_bp
```
After line 78 (`app.register_blueprint(file_browser_bp)`):
```python
app.register_blueprint(doc_folders_bp)
```

**Test:** `conda activate science-reader && python -c "from endpoints import register_blueprints; from flask import Flask; app = Flask(__name__); register_blueprints(app); print([str(r) for r in app.url_map.iter_rules() if 'doc_folder' in str(r)])"` — must list the 7 new routes.

---

### Task 1.5 — Update `list_global_docs` endpoint to include tags + folder_id

**File:** `endpoints/global_docs.py`, `list_global_docs_route()` (line 126)  
**What:** The route currently calls `list_global_docs()` and returns the result. After Task 0.4, each doc dict now has `tags` (list) and `folder_id`. The response JSON will automatically include them (no change needed IF the serializer handles lists). Verify `tags` is a list, not None — add `doc.get('tags') or []` fallback in the route response builder.

---

## Phase 2: Chat Reference Pipeline

### Task 2.1 — Add `#folder:` and `#tag:` detection in `Conversation.py`

**File:** `Conversation.py`  
**Where:** After line 5590 (end of the `gdoc_refs` + `gdoc_ref_names` block, before `quoted_names` processing).

**What to add:**
```python
# --- NEW: #folder: references ---
import re as _re
folder_refs = _re.findall(r'#folder:([\w/\-\.]+)', messageText)
for folder_name in folder_refs:
    from database.doc_folders import get_folder_by_name, get_docs_in_folder
    folder = get_folder_by_name(users_dir=users_dir, user_email=user_email, name=folder_name)
    if folder:
        folder_doc_ids = set(get_docs_in_folder(
            users_dir=users_dir, user_email=user_email,
            folder_id=folder['folder_id'], recursive=True
        ))
        from database.global_docs import list_global_docs as _lgd_folder
        all_rows = _lgd_folder(users_dir=users_dir, user_email=user_email)
        for idx_0, row in enumerate(all_rows):
            if row['doc_id'] in folder_doc_ids and (idx_0 + 1) not in gdoc_indices:
                gdoc_indices.append(idx_0 + 1)
                gdoc_ref_names.append(f"#gdoc_{idx_0 + 1}")

# --- NEW: #tag: references ---
tag_refs = _re.findall(r'#tag:([\w\-\.]+)', messageText)
for tag_name in tag_refs:
    from database.doc_tags import list_docs_by_tag
    tagged_doc_ids = set(list_docs_by_tag(users_dir=users_dir, user_email=user_email, tag=tag_name))
    from database.global_docs import list_global_docs as _lgd_tag
    all_rows = _lgd_tag(users_dir=users_dir, user_email=user_email)
    for idx_0, row in enumerate(all_rows):
        if row['doc_id'] in tagged_doc_ids and (idx_0 + 1) not in gdoc_indices:
            gdoc_indices.append(idx_0 + 1)
            gdoc_ref_names.append(f"#gdoc_{idx_0 + 1}")
```

**Caution:** Import inside the function body (lazy import pattern) — consistent with existing `from database.global_docs import list_global_docs as _list_global_docs` inside the function. Do NOT add module-level imports.

---

### Task 2.2 — Add replacement text for `#folder:` and `#tag:` in message display

**File:** `Conversation.py`  
**Where:** After the `gdoc_ref_names` replacement loop (search for where `messageText` is replaced with `gdoc_tag`). Add analogous replacements for `#folder:Name` → `#folder:Name (N docs)` and `#tag:name` → `#tag:name (N docs)`.

**Low priority:** The chat still works without this (reference resolution works); this is purely display polish. Skip if time is tight.

---

## Phase 3: List View Enhancements

### Task 3.1 — Add folder picker `<select>` to upload form in `interface/interface.html`

**File:** `interface/interface.html`  
**Where:** After line 469 (`</div>` closing the display-name form-group), before line 470 (`<button type="submit"...`).

**What to add:**
```html
<div class="form-group" id="global-doc-folder-group">
  <label for="global-doc-folder-select">Folder (optional)</label>
  <select class="form-control form-control-sm" id="global-doc-folder-select">
    <option value="">Unfiled</option>
  </select>
</div>
```

---

### Task 3.2 — Add view-switcher + filter bar HTML to `interface/interface.html`

**File:** `interface/interface.html`  
**Where:** After line 448 (`<div class="modal-body">`), before line 449 (`<div class="card mb-3">`).

**What to add:**
```html
<!-- View switcher + filter bar -->
<div class="d-flex justify-content-between align-items-center mb-2">
  <div class="btn-group btn-group-sm" id="global-docs-view-switcher" role="group">
    <button type="button" class="btn btn-outline-secondary active" data-view="list">
      <i class="fa fa-list"></i> List
    </button>
    <button type="button" class="btn btn-outline-secondary" data-view="folder">
      <i class="fa fa-folder"></i> Folders
    </button>
  </div>
  <button class="btn btn-sm btn-outline-info" id="global-docs-manage-folders-btn" title="Open File Browser for folder management" style="display:none;">
    <i class="fa fa-folder-open"></i> Manage Folders
  </button>
</div>
```

Also wrap existing list card content in `<div id="global-docs-view-list">` and add hidden `<div id="global-docs-view-folder" style="display:none;">` — see Task 3.6 for the folder view HTML.

---

### Task 3.3 — Add filter bar HTML inside the list card

**File:** `interface/interface.html`  
**Where:** After line 484 (`</button>` — end of refresh button), before line 485 (`</div>` — end of card-header).

**What to add:**
```html
<input type="text" id="global-docs-filter" class="form-control form-control-sm mt-1"
       placeholder="Filter by title or tag...">
```

---

### Task 3.4 — Update `renderList()` in `global-docs-manager.js` to show tags + folder badge

**File:** `interface/global-docs-manager.js`  
**Where:** Inside `renderList()` (line 84), inside the `docs.forEach` loop (lines 95-147).

**What:** After the `$info` block that appends the `#gdoc_N` badge and title, add:
- Tags chips: `(doc.tags || []).forEach(tag => $info.append($('<span class="badge badge-pill badge-secondary mr-1">').text(tag)))`
- Tag add button: small `+` button that opens inline tag editor (Task 3.5)
- Folder badge: if `doc.folder_id`, show `<span class="badge badge-light">{folderName}</span>` — need a folder name lookup (cache from `GET /doc_folders` response stored in `GlobalDocsManager._folderCache`)
- Store `data-tags` and `data-title` attributes on `$item` for client-side filtering
- Store `data-doc-id` on `$item` for context menu

---

### Task 3.5 — Add inline tag editor

**File:** `interface/global-docs-manager.js`  
**What:** New method `GlobalDocsManager.openTagEditor(docId, currentTags, $chipContainer)`:
- Show small inline `<input type="text" class="form-control form-control-sm">` below chips
- Enter key: call `POST /global_docs/{docId}/tags` with updated tags array, re-render chips
- ESC: close editor
- Call from `+` button on each row

---

### Task 3.6 — Add client-side filter logic

**File:** `interface/global-docs-manager.js`  
**What:** New method `GlobalDocsManager.filterDocList(query)`:
```javascript
filterDocList: function(query) {
    var q = (query || '').toLowerCase().trim();
    $('#global-docs-list .list-group-item').each(function() {
        var title = ($(this).data('title') || '').toLowerCase();
        var tags = ($(this).data('tags') || '').toLowerCase();
        var match = !q || title.indexOf(q) !== -1 || tags.indexOf(q) !== -1;
        $(this).toggle(match);
    });
}
```
Wire to `#global-docs-filter` `input` event in `setup()`.

---

### Task 3.7 — Add right-click context menu on doc rows

**File:** `interface/global-docs-manager.js`  
**Pattern:** Copy the `$(document).on('contextmenu', ...)` pattern from `workspace-manager.js`.  
**What:** Right-click on `.list-group-item[data-doc-id]` shows a menu:
1. View
2. Download
3. Move to Folder → submenu populated from `GlobalDocsManager._folderCache`
4. Edit Tags
5. Delete

Store menu element in `$('#global-docs-context-menu')` (add simple HTML in interface.html).

---

### Task 3.8 — Wire folder picker in upload form + pass folder_id on submit

**File:** `interface/global-docs-manager.js`  
**Where:** In `setup()` (line 160) and in `upload()` (line 53).  
**What:**
- In `setup()`: on modal open, call `GlobalDocsManager._loadFolderCache()` which fetches `GET /doc_folders` and populates `#global-doc-folder-select`.
- In `upload()`: read `$('#global-doc-folder-select').val()` and pass as `folder_id` field in the form data.
- Add `GlobalDocsManager._folderCache = []` and `GlobalDocsManager._loadFolderCache()` method.

---

### Task 3.9 — Folder picker in promote flow

**File:** `interface/global-docs-manager.js`  
**Where:** `promote()` method (line 24).  
**What:** If `GlobalDocsManager._folderCache.length > 0`, show a small Bootstrap modal/popover asking "Add to folder?" with the folder `<select>`. Send `folder_id` in the POST body. If no folders exist, promote immediately (current behavior).

**Low priority** — promote flow works without this. Implement after other tasks.

---

## Phase 4: Folder View + File Browser Integration

### Task 4.1 — Add folder view HTML to `interface/interface.html`

**File:** `interface/interface.html`  
**Where:** Wrap existing modal-body content in `<div id="global-docs-view-list">` and add folder view container.

**Exact edit:**
- After `<div class="modal-body">` (line 448), add `<div id="global-docs-view-list">` opening tag (after the view-switcher from Task 3.2).
- Before `</div>` closing modal-body (line 492), close `</div>` for `global-docs-view-list` and add:
```html
</div><!-- /global-docs-view-list -->

<div id="global-docs-view-folder" style="display:none;" class="p-3 text-center text-muted">
  <i class="fa fa-folder-open fa-2x mb-2"></i>
  <p>Click <strong>Manage Folders</strong> to organize your global docs in the File Browser.</p>
  <p class="small">Drag folders in the file browser to reorganize. Your changes sync automatically.</p>
</div>
```

**Note:** The "Manage Folders" button (Task 3.2) opens the file browser. The folder view container shows instructions. A full jsTree split-panel is deferred (Phase 4b in the plan).

---

### Task 4.2 — Wire view-switcher JS in `global-docs-manager.js`

**File:** `interface/global-docs-manager.js`  
**Where:** In `setup()`.  
**What:**
```javascript
// View switcher
$('#global-docs-view-switcher').on('click', 'button[data-view]', function() {
    var view = $(this).data('view');
    GlobalDocsManager._viewMode = view;
    localStorage.setItem('globalDocsViewMode', view);
    $('#global-docs-view-switcher button').removeClass('active');
    $(this).addClass('active');
    if (view === 'list') {
        $('#global-docs-view-list').show();
        $('#global-docs-view-folder').hide();
        $('#global-docs-manage-folders-btn').hide();
        $('#global-docs-modal .modal-dialog').removeClass('modal-xl').addClass('modal-lg');
    } else {
        $('#global-docs-view-list').hide();
        $('#global-docs-view-folder').show();
        $('#global-docs-manage-folders-btn').show();
        $('#global-docs-modal .modal-dialog').removeClass('modal-lg').addClass('modal-xl');
    }
});
// Restore view from localStorage
GlobalDocsManager._viewMode = localStorage.getItem('globalDocsViewMode') || 'list';
```

---

### Task 4.3 — Wire "Manage Folders" button + FileBrowserManager.configure `onMove`

**File:** `interface/global-docs-manager.js`  
**Where:** In `setup()`.  
**What:**

```javascript
// Manage Folders button — opens file browser pre-navigated to global docs dir
$('#global-docs-manage-folders-btn').on('click', function() {
    // Get the user hash from a meta tag or from /global_docs/list response
    // Simplest: navigate to storage/global_docs/ root and let user drill in
    FileBrowserManager.configure({
        onMove: function(srcPath, destPath, done) {
            // srcPath is like "storage/global_docs/abc123/doc-uuid-here"
            // destPath is like "storage/global_docs/abc123/FolderName/doc-uuid-here"
            var srcParts = srcPath.split('/');
            var docId = srcParts[srcParts.length - 1];
            var destParts = destPath.split('/');
            var destDir = destParts.slice(0, -1).join('/');
            // Look up folder_id from destDir name via _folderCache
            var folderName = destParts[destParts.length - 2] || null;
            var folder = (GlobalDocsManager._folderCache || []).find(function(f) {
                return f.name === folderName;
            });
            var folderId = folder ? folder.folder_id : null;

            if (!docId || docId.length < 10) { done('Cannot determine doc_id from path'); return; }

            $.ajax({
                url: '/doc_folders/' + (folderId || 'root') + '/assign',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ doc_id: docId }),
                success: function(r) {
                    if (r.status === 'ok') {
                        GlobalDocsManager.refresh();
                        done(null);
                    } else {
                        done(r.error || 'Assign failed');
                    }
                },
                error: function(xhr) {
                    var msg = 'Assign failed';
                    try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
                    done(msg);
                }
            });
        }
    });
    // Get user hash: use a cached value or fetch from /global_docs/list first doc's storage path
    var userHash = GlobalDocsManager._userHash;
    var startPath = userHash ? 'storage/global_docs/' + userHash : 'storage/global_docs';
    FileBrowserManager.open(startPath);
    $('#global-docs-modal').modal('hide');
});
```

**User hash:** On first `refresh()`, extract from first doc's `doc_storage` path — store in `GlobalDocsManager._userHash`. Or add a `/global_docs/user_hash` endpoint. Simplest: parse from `list_global_docs` response `doc_storage` field (which is `storage/global_docs/{user_hash}/{doc_id}/`).

---

## Phase 5: Chat Autocomplete

### Task 5.1 — Add `#folder:` / `#tag:` detection handler in `common-chat.js`

**File:** `interface/common-chat.js`  
**Where:** Inside `handleInput()` (line 3494), after the `lastAtIndex === -1` check block (after line 3504).

**What:** Add a parallel block for `#folder:` and `#tag:` detection:
```javascript
// Check for #folder: or #tag: autocomplete
var hashMatch = textBeforeCursor.match(/#(folder|tag):([\w\-\.]*)$/);
if (hashMatch) {
    var refType = hashMatch[1];  // 'folder' or 'tag'
    var refPrefix = hashMatch[2]; // text typed after the colon
    clearTimeout(autocompleteState.hashDebounceTimer);
    autocompleteState.hashDebounceTimer = setTimeout(function() {
        fetchHashAutocomplete(refType, refPrefix, textarea);
    }, 200);
    return;  // don't trigger @ handler
}
```

**New function `fetchHashAutocomplete(refType, prefix, textarea)`:**
```javascript
function fetchHashAutocomplete(refType, prefix, textarea) {
    var url = refType === 'folder'
        ? '/doc_folders/autocomplete?prefix=' + encodeURIComponent(prefix)
        : '/global_docs/tags?prefix=' + encodeURIComponent(prefix);
    $.getJSON(url, function(resp) {
        var items = refType === 'folder' ? (resp.folders || []) : (resp.tags || []);
        if (!items.length) { hideAutocomplete(); return; }
        showHashAutocompleteDropdown(items, refType, prefix, textarea);
    }).fail(function() { hideAutocomplete(); });
}
```

**New function `showHashAutocompleteDropdown(items, refType, prefix, textarea)`:**
- Reuse existing `$autocompleteDropdown` element.
- For each item, show it. On click: insert `#folder:FolderName` or `#tag:tagname` at cursor (replace the partial `#folder:pre` with the full token).
- Section header: "Folders" or "Tags".

**Do NOT modify** the existing `handleInput()` `@` detection logic — only add to it.

---

## Dependency & Ordering

```
Task 0.1 (DB tables)
  └── Task 0.2 (doc_folders.py)
  └── Task 0.3 (doc_tags.py)
  └── Task 0.4 (global_docs.py update)
        └── Task 1.1 (doc_folders endpoints) + Task 1.2 (tag endpoints) + Task 1.3 (upload/promote)
              └── Task 1.4 (register blueprint) + Task 1.5 (list endpoint response update)
                    ├── Task 2.1 (Conversation.py #folder:/#tag: detection)
                    ├── Task 3.1-3.9 (list view enhancements, parallel)
                    └── Task 4.1-4.3 (folder view + file browser integration)
                          └── Task 5.1 (chat autocomplete)
```

Tasks 2.1, 3.x, and 4.x can all be done in parallel after Phase 1 is complete.

---

## Smoke Test Sequence (After Each Phase)

### After Phase 0:
```bash
conda activate science-reader
python -c "
from database.connection import create_tables
create_tables(users_dir='users')
from database.doc_folders import create_folder, list_folders
fid = create_folder(users_dir='users', user_email='test@x.com', name='Test')
print('folder created:', fid)
print('list:', list_folders(users_dir='users', user_email='test@x.com'))
from database.doc_tags import set_tags, list_tags_for_doc
set_tags(users_dir='users', user_email='test@x.com', doc_id='fake', tags=['ai','ml'])
print('tags:', list_tags_for_doc(users_dir='users', user_email='test@x.com', doc_id='fake'))
print('Phase 0 OK')
"
```

### After Phase 1:
```bash
conda activate science-reader
python server.py &
sleep 3
curl -s http://localhost:5000/doc_folders  # should return 401 (auth required, endpoint exists)
curl -s http://localhost:5000/global_docs/tags  # same
echo "Phase 1 endpoints reachable"
```

### After Phase 2:
Send a message with `#folder:Test` in a conversation that has global docs. Verify the folder's docs appear in context.

### After Phase 3:
Open Global Docs modal. Verify: tag chips visible on docs with tags, filter bar works, folder badge visible.

### After Phase 4:
Click "Manage Folders" button. File browser opens. Create a folder. Drag a doc-folder into it. Close file browser. Reopen global docs modal. Verify folder badge shows on the doc row.

### After Phase 5:
Type `#folder:` in chat input. Autocomplete dropdown shows folder names.

---

## Files Modified Summary

| File | Phase | Change |
|------|-------|--------|
| `database/connection.py` | 0.1 | New tables + ALTER + indexes |
| `database/doc_folders.py` | 0.2 | New file — folder CRUD |
| `database/doc_tags.py` | 0.3 | New file — tag CRUD |
| `database/global_docs.py` | 0.4 | Tags JOIN + folder_id in add + new list functions |
| `endpoints/doc_folders.py` | 1.1 | New file — folder REST API |
| `endpoints/global_docs.py` | 1.2, 1.3, 1.5 | Tag endpoints + folder_id in upload/promote |
| `endpoints/__init__.py` | 1.4 | Register doc_folders_bp |
| `Conversation.py` | 2.1 | #folder: and #tag: detection |
| `interface/interface.html` | 3.1, 3.2, 3.3, 4.1 | Folder picker, view switcher, filter bar, folder view div |
| `interface/global-docs-manager.js` | 3.4-3.9, 4.2, 4.3 | renderList, filter, tags, context menu, view switcher, file browser wire-up |
| `interface/common-chat.js` | 5.1 | #folder:/#tag: autocomplete handler |
