# Global Docs — Folders, Tags & Enhanced UI

**Status:** Planning — Clarifications Finalized (2026-02-26)
**Created:** 2026-02-26
**Scope:** Folder hierarchy + tags + dual-view UI for global docs only. Local/conversation docs unchanged.

---

## 1. Goals & User Requirements

1. **Folder hierarchy for global docs only.** Local/conversation docs stay flat — they typically have few docs and don’t need organizing.

2. **Dual-view UI in the same modal.** A view-switcher (tab strip or button group) at the top of the global docs modal lets users toggle between:
   - **List view** — current flat list, unchanged look-and-feel.
   - **Folder view** — the **existing file browser** opened pre-navigated to `storage/global_docs/{user_hash}/`, with its `onMove` callback wired to sync folder assignments to DB. A lightweight split panel inside the modal is available as Phase 4b polish.

3. **Tags on global docs.** Each doc can have zero or more free-form text tags. Tags are:
   - Added/removed in a chip input UI on the doc row (inline edit or context menu).
   - Filterable in both list view and folder view via a search/filter bar.
   - Referenceable in chat via `#tag:TagName`.

4. **Folder assignment UX — all four paths:**
   - **File browser drag-and-drop** (via `FileBrowserManager.configure({onMove: fn})` hook) — primary path.
   - **Right-click context menu** on doc row in list view → "Move to Folder" submenu.
   - Folder picker dropdown in the upload form.
   - Folder picker on the promote-to-global flow.

5. **Default folder:** New docs with no folder assignment land in a virtual “Unfiled” root.

6. **Delete folder behavior:** Prompt user — “Move docs to parent folder or delete them?” Docs are never silently deleted.

7. **`#gdoc_all` unchanged** — still includes all global docs regardless of folder. New references:
   - `#folder:FolderName` — include all docs in that folder (recursive).
   - `#tag:TagName` — include all docs with that tag.
   - Both resolve through `ContextualReader` (map-reduce) for long-context handling — no hard cap.

8. **Canonical store (SHA256 dedup) for global docs.** `global_docs/{user_hash}/{doc_id}/` → `storage/documents/{user_hash}/{sha256_hash}/`. Local docs storage unchanged.

---

## 2. What Is NOT Changing

- `DocIndex` and `FastDocIndex` classes — no changes to indexing logic.
- Local/conversation docs (`uploaded_documents_list`, `local-docs-manager.js`) — no changes.
- `#gdoc_N`, `#gdoc_all`, `#global_doc_N` chat reference syntax — fully backward compatible.
- `GlobalDocuments` table primary key `(doc_id, user_email)` — no schema change to existing columns.
- Upload, delete, and download endpoints — all existing behavior preserved.
- `promote_to_global` endpoint — enhanced (folder picker param added), not replaced.

---

## 3. Current State (Relevant Facts)

### 3.1 Global Docs Storage
- **DB:** `GlobalDocuments(doc_id, user_email, display_name, doc_source, doc_storage, title, short_summary, created_at, updated_at)` in `users/users.db`.
- **Disk:** `storage/global_docs/{user_hash}/{doc_id}/` — always full `DocIndex`.
- `storage/documents/` exists but is unused (created at `server.py:342`).

### 3.2 Global Docs UI (`interface/global-docs-manager.js`)
- 232 lines. Methods: `list()`, `deleteDoc()`, `promote()`, `getInfo()`, `isValidFileType()`, `upload()`, `_resetForm()`, `renderList()`, `refresh()`, `setup()`.
- DOM IDs: `#global-docs-modal`, `#global-docs-list`, `#global-docs-empty`, `#global-doc-upload-form`, `#global-doc-url`, `#global-doc-browse-btn`, `#global-doc-drop-area`, `#global-doc-file-input`, `#global-doc-display-name`, `#global-doc-submit-btn`, `#global-doc-upload-spinner`, `#global-doc-upload-progress`, `#global-doc-refresh-btn`.
- **No filter, no search, no tag UI** exists today.
- `DocsManagerUtils` (from `local-docs-manager.js`) provides: `isValidFileType()`, `uploadWithProgress()`, `setupDropArea()`.

### 3.3 Chat Reference Pipeline (`Conversation.py`)
- `get_global_documents_for_query()` at line 5540: regex `#(?:gdoc|global_doc)_(\d+)` detects references.
- `#gdoc_all` detected at line 6666; synthesized as all `#gdoc_1 #gdoc_2 ...` and passed to the same method.
- Resolved docs merged into `attached_docs_readable` and `attached_docs_data` at lines 7717–7741.
- **Extension point: after line 5556** — add `#folder:` and `#tag:` detection here.

### 3.4 Database Patterns
- All tables in `users/users.db`, created via `create_tables(*, users_dir)` in `database/connection.py`.
- Pattern: `CREATE TABLE IF NOT EXISTS`, keyword-only args, `INSERT OR IGNORE`, try/except for `ALTER TABLE` migrations.
- `_db_path(*, users_dir)` helper in each module; each function opens/closes its own connection.
- PKB has a hierarchical tag system (`truth_management_system/crud/tags.py`) we can reference for flat doc tags.

### 3.5 jsTree (Already Available)
- jsTree 3.3.17 loaded globally from CDN (`interface.html` line 3649).
- Already used in `workspace-manager.js` with `types`, `wholerow`, `contextmenu`, `dnd` plugins.
- `workspace-styles.css` has jsTree overrides we can extend.

### 3.6 Bootstrap Tab Pattern (Established in Codebase)

### 3.7 File Browser (Updated — Key Reuse Opportunity)
**File:** `interface/file-browser-manager.js`, `endpoints/file_browser.py`

The file browser has been significantly upgraded and is now directly reusable as the folder management UI:

| Capability | How it helps us |
|---|---|
| Drag-and-drop move (tree item → folder) | Primary folder-assignment UX — drag a `{doc_id}/` folder to a new parent |
| "Move to…" context menu modal | Secondary folder-assignment UX via lazy folder-only tree picker |
| `_config.onMove(srcPath, destPath, done)` callback | **Override point** — we intercept moves to sync `GlobalDocFolders` DB |
| `FileBrowserManager.configure({onMove: fn})` | Post-init callback override, no file browser source changes needed |
| New Folder / Rename / Delete with confirm/name modals | Folder CRUD UI already built |
| `_safe_resolve()` sandbox includes `storage/` | `storage/global_docs/{user_hash}/` is already accessible |
| Address bar fuzzy autocomplete | Navigation within the doc store |

**Impact on plan:** Phase 4 reduced from ~6h to ~2h. jsTree DnD risk eliminated.
- PKB modal (`#pkb-tabs`) uses `nav nav-tabs` + `tab-pane fade` — the exact pattern to follow.
- File browser uses `viewMode` state variable for view-switching.

---

## 4. Data Model

### 4.1 New DB Tables (added to `database/connection.py` `create_tables()`)

```sql
-- Folder hierarchy for global docs
CREATE TABLE IF NOT EXISTS GlobalDocFolders (
    folder_id     TEXT NOT NULL,          -- uuid4
    user_email    TEXT NOT NULL,
    name          TEXT NOT NULL,          -- human-readable folder name
    parent_id     TEXT,                   -- NULL = root folder
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (folder_id, user_email)
);

-- Folder membership (one doc belongs to exactly one folder)
-- NULL folder_id = Unfiled
-- Adding a column to GlobalDocuments is simpler than a join table
-- since membership is 1:1 (one folder per doc).
-- ALTER TABLE migration:
ALTER TABLE GlobalDocuments ADD COLUMN folder_id TEXT DEFAULT NULL;

-- Tags (many-to-many: one doc can have many tags)
CREATE TABLE IF NOT EXISTS GlobalDocTags (
    doc_id        TEXT NOT NULL,
    user_email    TEXT NOT NULL,
    tag           TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (doc_id, user_email, tag),
    FOREIGN KEY (doc_id, user_email) REFERENCES GlobalDocuments (doc_id, user_email)
);
```

**Indexes to add:**
```sql
CREATE INDEX IF NOT EXISTS idx_GlobalDocFolders_user ON GlobalDocFolders (user_email);
CREATE INDEX IF NOT EXISTS idx_GlobalDocFolders_parent ON GlobalDocFolders (user_email, parent_id);
CREATE INDEX IF NOT EXISTS idx_GlobalDocuments_folder ON GlobalDocuments (user_email, folder_id);
CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_user ON GlobalDocTags (user_email);
CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_tag ON GlobalDocTags (user_email, tag);
CREATE INDEX IF NOT EXISTS idx_GlobalDocTags_doc ON GlobalDocTags (doc_id, user_email);
```

### 4.2 Design Rationale
- **One folder per doc** (`folder_id` column on `GlobalDocuments`) — simpler than a join table, matches user decision (strict hierarchy).
- **Tags in separate table** — many-to-many naturally, easy to query all docs for a tag.
- **`folder_id = NULL`** — Unfiled (virtual root). No special `Unfiled` folder row needed.
- **Folder depth** — unlimited nesting via `parent_id` self-reference.

---

## 5. Backend: New Files & Modified Files

### 5.1 New: `database/doc_folders.py`
Template: mirror `database/global_docs.py` style exactly.

```python
# Function signatures (keyword-only args, users_dir always first)
def create_folder(*, users_dir, user_email, name, parent_id=None) -> str:  # returns folder_id
def rename_folder(*, users_dir, user_email, folder_id, new_name) -> bool
def move_folder(*, users_dir, user_email, folder_id, new_parent_id) -> bool
def delete_folder(*, users_dir, user_email, folder_id) -> bool  # does NOT delete docs
def list_folders(*, users_dir, user_email) -> list[dict]  # all folders flat (tree built in caller)
def get_folder(*, users_dir, user_email, folder_id) -> Optional[dict]
def get_folder_by_name(*, users_dir, user_email, name) -> Optional[dict]  # for #folder: resolution
def assign_doc_to_folder(*, users_dir, user_email, doc_id, folder_id) -> bool  # UPDATE GlobalDocuments
def get_docs_in_folder(*, users_dir, user_email, folder_id, recursive=False) -> list[str]  # returns doc_ids
```

**`get_docs_in_folder(recursive=True)` implementation:**
- Fetch direct children: `SELECT doc_id FROM GlobalDocuments WHERE user_email=? AND folder_id=?`
- Fetch child folder_ids: `SELECT folder_id FROM GlobalDocFolders WHERE user_email=? AND parent_id=?`
- Recurse for each child folder. Use iteration with a queue to avoid deep recursion.

### 5.2 New: `database/doc_tags.py`

```python
def add_tag(*, users_dir, user_email, doc_id, tag) -> bool
def remove_tag(*, users_dir, user_email, doc_id, tag) -> bool
def set_tags(*, users_dir, user_email, doc_id, tags: list[str]) -> bool  # replace all tags for a doc
def list_tags_for_doc(*, users_dir, user_email, doc_id) -> list[str]
def list_all_tags(*, users_dir, user_email) -> list[str]  # distinct tags for user (for autocomplete)
def list_docs_by_tag(*, users_dir, user_email, tag) -> list[str]  # returns doc_ids
```

### 5.3 Modified: `database/connection.py`
- Add `GlobalDocFolders` CREATE TABLE.
- Add `GlobalDocTags` CREATE TABLE.
- Add `ALTER TABLE GlobalDocuments ADD COLUMN folder_id TEXT DEFAULT NULL` (try/except pattern).
- Add all 6 new indexes.

### 5.4 Modified: `database/global_docs.py`
- `list_global_docs()`: JOIN with `GlobalDocTags` to include `tags` array in each row.
- `add_global_doc()`: accept optional `folder_id` param.
- New: `list_global_docs_by_folder(*, users_dir, user_email, folder_id)` — for folder view API.
- New: `list_global_docs_by_tag(*, users_dir, user_email, tag)` — thin wrapper over `doc_tags.list_docs_by_tag()`.

---

## 6. Backend: New API Endpoints

### 6.1 New Blueprint: `endpoints/doc_folders.py`
Register as `doc_folders_bp` in `endpoints/__init__.py`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/doc_folders` | List all folders for user (flat; tree built in JS) |
| `POST` | `/doc_folders` | Create folder `{name, parent_id?}` |
| `PATCH` | `/doc_folders/<folder_id>` | Rename or move `{name?, parent_id?}` |
| `DELETE` | `/doc_folders/<folder_id>` | Delete folder; `action` param: `move_to_parent` or `delete_docs` |
| `POST` | `/doc_folders/<folder_id>/assign` | Assign doc `{doc_id}` to folder |
| `GET` | `/doc_folders/<folder_id>/docs` | List docs in folder (with `?recursive=true`) |
| `GET` | `/doc_folders/autocomplete?prefix=` | Folder names for `#folder:` autocomplete in chat |

**Response shape for `GET /doc_folders`:**
```json
[
  {"folder_id": "uuid", "name": "Research", "parent_id": null, "doc_count": 5, "created_at": "..."},
  {"folder_id": "uuid", "name": "AI/ML",    "parent_id": "<research-id>", "doc_count": 3, "created_at": "..."},
]
```
JS builds the tree from this flat list using `parent_id` pointers (same pattern as `workspace-manager.js` line 303–330).

### 6.2 New Endpoints in `endpoints/global_docs.py`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/global_docs/<doc_id>/tags` | Set tags `{tags: ["ai", "ml"]}` (replaces all) |
| `GET` | `/global_docs/tags` | List all distinct tags for user (autocomplete) |
| `GET` | `/global_docs/autocomplete?type=folder&prefix=` | Combined autocomplete for `#folder:` and `#tag:` |

### 6.3 Modified: `endpoints/global_docs.py`
- `list` endpoint: include `tags` array and `folder_id` in each doc response.
- `upload` endpoint: accept optional `folder_id` in payload.
- `promote` endpoint: accept optional `folder_id` in payload.

---

## 7. Chat Reference Pipeline Extension (`Conversation.py`)

### 7.1 Extension Point
In `get_global_documents_for_query()` (line 5540), after existing `#gdoc_N` regex detection at line 5556:

```python
# --- NEW: #folder: references ---
folder_refs = re.findall(r'#folder:([\w/\-\.]+)', messageText)
for folder_name in folder_refs:
    folder = get_folder_by_name(users_dir=users_dir, user_email=user_email, name=folder_name)
    if folder:
        doc_ids = get_docs_in_folder(users_dir=users_dir, user_email=user_email,
                                      folder_id=folder['folder_id'], recursive=True)
        gdoc_rows = list_global_docs(users_dir=users_dir, user_email=user_email)
        for row in gdoc_rows:
            if row['doc_id'] in doc_ids:
                gdoc_indices.append(row['_index'])  # 1-based index in the rows list

# --- NEW: #tag: references ---
tag_refs = re.findall(r'#tag:([\w\-\.]+)', messageText)
for tag_name in tag_refs:
    tagged_doc_ids = set(list_docs_by_tag(users_dir=users_dir, user_email=user_email, tag=tag_name))
    gdoc_rows = list_global_docs(users_dir=users_dir, user_email=user_email)
    for row in gdoc_rows:
        if row['doc_id'] in tagged_doc_ids:
            gdoc_indices.append(row['_index'])
```

### 7.2 Long-Context Handling
- No hard cap on doc count from folder/tag references.
- All resolved docs passed to `ContextualReader` (map-reduce) via the existing `get_multiple_answers()` path — same as `#gdoc_all`.
- `ContextualReader` already handles chunking and aggregation.

### 7.3 `#gdoc_all` Unchanged
`#gdoc_all` still expands to all global docs regardless of folder/tag. No behavior change.

### 7.4 Reference Display in Message
After resolution, `messageText` replacement adds clarification:
- `#folder:Research` → `#folder:Research (5 docs: 'Paper A', 'Paper B', ...)`
- `#tag:ml` → `#tag:ml (3 docs: 'Survey', 'Benchmark', 'Review')`

---

## 8. Frontend: UI Design

### 8.1 Modal View Switcher
Add a **Bootstrap button group** at the top of `#global-docs-modal` modal-body, before the upload card.
Follow the `#message-edit-tabs` pattern (interface.html line 1180).

```html
<!-- View switcher strip (added at top of modal-body) -->
<div class="d-flex justify-content-between align-items-center mb-3">
  <span class="text-muted small">Global Documents</span>
  <div class="btn-group btn-group-sm" id="global-docs-view-switcher" role="group">
    <button type="button" class="btn btn-outline-secondary active" data-view="list">
      <i class="fa fa-list"></i> List
    </button>
    <button type="button" class="btn btn-outline-secondary" data-view="folder">
      <i class="fa fa-folder"></i> Folders
    </button>
  </div>
</div>

<!-- List view container (current content, unchanged) -->
<div id="global-docs-view-list">
  <!-- upload card + list card go here -->
</div>

<!-- Folder view container (new, hidden by default) -->
<div id="global-docs-view-folder" style="display:none;">
  <!-- split panel goes here -->
</div>
```

**JS state:** `GlobalDocsManager._viewMode = 'list' | 'folder'`
Toggle on button group click, store in `localStorage` to persist across modal opens.

### 8.2 List View Enhancements
Additions to each row in existing `renderList()`:
- **Tag chips** — after the `#gdoc_N` badge: `<span class="badge badge-info badge-pill">tag</span>` per tag.
- **Tag filter bar** — above `#global-docs-list`: text input + active tag chips.
- **Folder badge** — small `badge-light` showing folder path (e.g. `Research/AI`), if assigned.
- **Context menu** on right-click: View | Download | Move to Folder | Edit Tags | Delete.

```html
<!-- Filter bar (inside list-card card-header, next to Refresh btn) -->
<input type="text" id="global-docs-filter" class="form-control form-control-sm"
       placeholder="Search title or #tag...">
<div id="global-docs-active-tags" class="d-flex flex-wrap mt-1"></div>
```

**Client-side filter logic** (no API call):
- On input: hide rows where neither title nor `data-tags` attribute matches.
- On tag chip click in a row: add that tag to active filter chips, re-filter.
- Tags stored as `data-tags="ai,ml"` attribute on each `.list-group-item`.

---

### 8.3 Folder View — Split Panel Layout

```html
<div id="global-docs-view-folder" class="d-flex" style="height: 520px; display:none;">

  <!-- LEFT: folder tree (280px fixed) -->
  <div id="global-docs-folder-sidebar"
       class="border-right flex-shrink-0 d-flex flex-column"
       style="width: 280px; overflow: hidden;">
    <div class="p-2 border-bottom d-flex justify-content-between align-items-center">
      <strong class="small">Folders</strong>
      <button class="btn btn-xs btn-outline-secondary" id="global-docs-new-folder-btn"
              title="New folder"><i class="fa fa-plus"></i></button>
    </div>
    <div class="p-1 flex-grow-1 overflow-auto" id="global-docs-folder-tree"></div>
    <!-- Upload form in folder view (collapsed by default) -->
    <div class="p-2 border-top" id="global-docs-folder-upload">
      <!-- same form as list view, injected here on expand -->
    </div>
  </div>

  <!-- RIGHT: docs in selected folder -->
  <div class="flex-grow-1 d-flex flex-column overflow-hidden">
    <div class="p-2 border-bottom d-flex justify-content-between align-items-center">
      <span id="global-docs-folder-breadcrumb" class="small text-muted">All / Unfiled</span>
      <input type="text" id="global-docs-folder-filter"
             class="form-control form-control-sm" style="width:180px;"
             placeholder="Search...">
    </div>
    <div class="flex-grow-1 overflow-auto">
      <div id="global-docs-folder-list" class="list-group list-group-flush"></div>
    </div>
  </div>

</div>
```

**Modal size:** Upgrade `modal-lg` → `modal-xl` when folder view is active (toggle class on view switch).

### 8.4 Folder View — File Browser Integration (Primary Path)
The **existing file browser already works** as a full folder management UI for `storage/global_docs/{user_hash}/`.
It is sandboxed to `SERVER_ROOT` via `_safe_resolve()`, which includes `storage/` — so global docs storage is already accessible.

**Reuse strategy:**
1. Add a **"Manage Folders"** button in the global docs modal (next to Refresh) that calls `FileBrowserManager.open()` pre-navigated to `storage/global_docs/{user_hash}/`.
2. Wire `FileBrowserManager.configure({onMove: fn})` at init so when a user drags a doc-folder in the file browser to a new location:
   - Extract `doc_id` from `srcPath` (last path component)
   - Extract target folder name from `destPath`
   - Call `POST /doc_folders/<folder_id>/assign` to update DB
   - Call `done(null)` to let file browser refresh its tree
3. This gives us drag-drop and Move-to-modal (via file browser's own Move modal) **for free** — zero new DnD code.

**What file browser provides for free:**
- Folder creation (New Folder button + naming modal)
- Rename (right-click → Rename)
- Delete (right-click → Delete + confirm modal)
- Drag-drop move (HTML5 DnD with visual feedback)
- "Move to…" context menu modal (lazy folder-only tree picker)
- Address bar with fuzzy autocomplete for navigation
- All sandboxed within `SERVER_ROOT`

**What it cannot provide (still needed in modal):**
- Human-readable doc titles (file browser shows raw `{doc_id}/` directories)
- Tag chips and tag filter
- `#gdoc_N` badge and action buttons (View, Download, Delete from DB)
- Folder name → `folder_id` DB mapping for `#folder:` resolution

**Therefore:** The DB tables (`GlobalDocFolders`, `DocFolderItems`) are still needed — not for the file browser UI, but for:
- `#folder:FolderName` chat reference resolution (name → doc_ids)
- Folder badge display in list view (name lookup)
- Folder picker `<select>` in upload/promote forms
- Context menu "Move to Folder" submenu in list view
- Data source: `GET /doc_folders` (flat list; JS builds tree with `parent_id`).
- Types: `folder` only (docs shown in right panel, not in tree).
- Plugins: `types`, `wholerow`, `contextmenu`, `dnd`.
- `onMove` hook: extract `doc_id` from `srcPath`, resolve target `folder_id` from `destPath`, call `POST /doc_folders/<folder_id>/assign`.
- **Right-click context menu on folder node** (in file browser): handled by file browser's existing context menu (Rename, New Folder, Delete, Move to…) — no new code needed.
- **`Unfiled` concept:** docs with `folder_id = NULL` in DB. File browser shows them at the root of `global_docs/{user_hash}/` — root = Unfiled.
- `select_node.jstree` event: **not used** — the file browser does not use jsTree. File browser uses its own custom `<ul>/<li>` tree with `data-path` attributes.

### 8.4b Split Panel Inside Modal (Phase 4b — Optional Polish)
If a user never needs the file browser's full-screen mode, a lightweight split panel inside the global docs modal can still be built:
- Left: jsTree initialized from `GET /doc_folders` (DB-based, human-readable names).
- Right: doc list filtered by selected folder.
- This is **deferred to Phase 4b** and is NOT required for the folder system to work.
- The file browser path (§8.4) is the **default and primary** implementation.

### 8.5 Tag Chip Input (Inline Edit)
On doc row in either view:
- Click a “+” icon → shows small inline text input.
- Press Enter → chip appears: `<span class="badge badge-pill badge-secondary">tag <i class="fa fa-times"></i></span>`.
- Click × on chip → remove tag.
- Both actions call `POST /global_docs/<doc_id>/tags` with full updated tag list.

### 8.6 Context Menu on Doc Row (Right-click)
Reuse jQuery `$(document).on('contextmenu', '.list-group-item', ...)` pattern from `workspace-manager.js` context menu.
Menu items:
1. View — same as eye button
2. Download
3. Move to Folder → submenu listing folder names (from cached folder list)
4. Edit Tags → opens inline tag editor
5. Delete

### 8.7 Folder Picker in Upload Form
Add below `#global-doc-display-name`:
```html
<div class="form-group">
  <label for="global-doc-folder-select">Folder (optional)</label>
  <select class="form-control form-control-sm" id="global-doc-folder-select">
    <option value="">Unfiled</option>
    <!-- populated from GET /doc_folders on modal open -->
  </select>
</div>
```
Value sent as `folder_id` in upload payload.

### 8.8 Folder Picker in Promote Flow
When `GlobalDocsManager.promote(convId, docId)` is called:
- If any folders exist: show a small modal/popover asking "Add to folder?" with the same `<select>`.
- If no folders: promote immediately (current behavior).

---

## 9. Chat Autocomplete for `#folder:` and `#tag:`

### 9.1 Current `@` Autocomplete (Existing)
Located in `interface/common-chat.js` lines ~3415–3625.
- Triggers on `@` character.
- Calls `PKBManager.searchAutocomplete(prefix, 8)`.
- Shows dropdown with PKB memories/contexts/entities.

### 9.2 New `#` Autocomplete Handler
Add a **separate** detection block for `#` prefix (does not touch existing `@` handler).

**Trigger:** user types `#folder:` or `#tag:` in the chat input textarea.

**Detection regex:** `/(?:^|\s)(#(?:folder|tag):([\w\-\.]*))/` — match at word boundary.

**API call:**
- `#folder:<prefix>` → `GET /doc_folders/autocomplete?prefix=<prefix>` → returns folder names.
- `#tag:<prefix>` → `GET /global_docs/tags?prefix=<prefix>` → returns tag strings.

**Dropdown UI:** Reuse existing `@` autocomplete dropdown element and styling.
- Section header: “Folders” or “Tags”.
- On select: insert full token `#folder:FolderName` or `#tag:tagname` at cursor.

**No change to `PKBManager` — this is a parallel handler in the same file.**

---

## 10. Implementation Phases

### Phase 0: DB Schema + Helpers (~2h)
**Goal:** Foundation. No UI, no endpoints yet.
- **Task 0.1:** Add `GlobalDocFolders`, `GlobalDocTags` tables and `folder_id` ALTER to `database/connection.py`.
- **Task 0.2:** Write `database/doc_folders.py` (all functions from §5.1).
- **Task 0.3:** Write `database/doc_tags.py` (all functions from §5.2).
- **Task 0.4:** Update `database/global_docs.py`: `list_global_docs()` joins tags, `add_global_doc()` accepts `folder_id`.
- **Files:** `database/connection.py`, new `database/doc_folders.py`, new `database/doc_tags.py`, `database/global_docs.py`
- **Risk:** Low. Pure new code + additive schema changes.

### Phase 1: Folder & Tag API Endpoints (~3h)
**Goal:** All REST endpoints working, testable via curl/Postman.
- **Task 1.1:** Write `endpoints/doc_folders.py` Blueprint (all endpoints from §6.1).
- **Task 1.2:** Add tag endpoints to `endpoints/global_docs.py` (§6.2).
- **Task 1.3:** Update `upload` and `promote` endpoints to accept `folder_id` (§6.3).
- **Task 1.4:** Register `doc_folders_bp` in `endpoints/__init__.py`.
- **Files:** New `endpoints/doc_folders.py`, `endpoints/global_docs.py`, `endpoints/__init__.py`
- **Risk:** Low. Follow existing endpoint patterns.

### Phase 2: Chat Reference Resolution (~3h)
**Goal:** `#folder:Name` and `#tag:Name` work in chat.
- **Task 2.1:** Add `#folder:` and `#tag:` detection in `Conversation.get_global_documents_for_query()` after line 5556.
- **Task 2.2:** Add reference replacement text (§7.4).
- **Task 2.3:** Add `#folder:` and `#tag:` to `doc_infos` manifest string.
- **Files:** `Conversation.py`
- **Risk:** Medium. Reply pipeline is sensitive. Test with `#gdoc_all` still working.

### Phase 3: List View Enhancements (~4h)
**Goal:** Current list view gains tag chips, folder badge, filter bar, context menu.
- **Task 3.1:** Update `renderList()` in `global-docs-manager.js`: add tag chips, folder badge per row.
- **Task 3.2:** Add filter bar above list (`#global-docs-filter` + active tag chips).
- **Task 3.3:** Client-side filter logic (`filterDocList()`).
- **Task 3.4:** Inline tag chip editor on `+` click.
- **Task 3.5:** Right-click context menu (reuse workspace-manager pattern).
- **Task 3.6:** Folder picker `<select>` in upload form; send `folder_id` on submit.
- **Task 3.7:** Folder picker popover on promote flow.
- **Files:** `interface/global-docs-manager.js`, `interface/interface.html`
- **Risk:** Medium. Many small UI changes; test each independently.

### Phase 4: Folder View — File Browser Integration (~2h, down from 6h)
**Goal:** Users can manage folders using the existing file browser. `onMove` hook syncs folder assignments to DB.
- **Task 4.1:** Add view-switcher button group to modal HTML (§8.1) — List / Folders toggle.
- **Task 4.2:** Add **"Manage Folders"** button in modal → calls `FileBrowserManager.open()` pre-navigated to `storage/global_docs/{user_hash}/`.
- **Task 4.3:** Wire `FileBrowserManager.configure({onMove: fn})` at app init (in `interface/chat.js` or `common-chat.js`): extract `doc_id` from moved path, call `/doc_folders/<folder_id>/assign`, refresh global docs list.
- **Task 4.4:** On modal open, call `GET /doc_folders` to populate folder picker `<select>` elements (for upload form and promote flow).
- **Task 4.5 (Phase 4b, optional):** Build lightweight jsTree split-panel inside modal as polish. Deferred — file browser covers the use case.
- **Files:** `interface/global-docs-manager.js`, `interface/interface.html`, `interface/chat.js` (or `common-chat.js` for `onMove` hook)
- **Risk:** Low (down from Medium-High). File browser DnD and Move modal already work and are well-tested. Only the `onMove` callback is new code.
- **Time saved vs original plan:** ~4h (no custom jsTree in modal, no custom DnD implementation).
- **Files:** `interface/global-docs-manager.js`, `interface/interface.html`, `interface/workspace-styles.css`
- **Risk:** Medium-High. jsTree DnD from list rows to tree nodes needs custom drag source handling.

### Phase 5: Chat Autocomplete for `#folder:` and `#tag:` (~2h)
**Goal:** Typing `#folder:Re` in chat shows matching folder names in dropdown.
- **Task 5.1:** Add `#` detection handler in `interface/common-chat.js` (§9.2).
- **Task 5.2:** Wire to `GET /doc_folders/autocomplete` and `GET /global_docs/tags`.
- **Task 5.3:** Style folder/tag results in existing autocomplete dropdown.
- **Files:** `interface/common-chat.js`
- **Risk:** Low-Medium. Does not touch existing `@` autocomplete logic.

---

## 11. Dependency Graph

```
Phase 0 (DB Schema + Helpers)
  └── Phase 1 (API Endpoints)
        ├── Phase 2 (Chat #folder:/#tag: resolution)
        ├── Phase 3 (List view enhancements)
        └── Phase 4 (Folder view — file browser integration)
              └── Phase 5 (Chat autocomplete)
```

Phases 2, 3, 4 can be parallelized after Phase 1 completes.
Phase 5 depends only on Phase 1 (needs the autocomplete endpoints).

---

## 12. Files Created / Modified Summary

### New Files
- `database/doc_folders.py` — folder CRUD helpers
- `database/doc_tags.py` — tag CRUD helpers
- `endpoints/doc_folders.py` — folder REST API Blueprint

### Modified Files
- `database/connection.py` — new tables, ALTER migration, new indexes
- `database/global_docs.py` — tags join in list, folder_id in add
- `endpoints/global_docs.py` — tag endpoints, folder_id in upload/promote, autocomplete
- `endpoints/__init__.py` — register doc_folders_bp
- `Conversation.py` — `#folder:` and `#tag:` detection + resolution in reply pipeline
- `interface/global-docs-manager.js` — view switcher, tag chips, filter, context menu, folder badge, "Manage Folders" button, `onMove` hook wiring
- `interface/interface.html` — view switcher HTML, folder picker in upload form, "Manage Folders" button
- `interface/chat.js` or `interface/common-chat.js` — `FileBrowserManager.configure({onMove: fn})` hook at init
- `interface/common-chat.js` — `#folder:` and `#tag:` autocomplete handler

---

## 13. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ~~jsTree DnD: dragging list-group rows onto tree nodes needs custom HTML5 drag source~~ | ~~Medium~~ | ~~Feature gap~~ | **ELIMINATED** — file browser provides DnD via `onMove` hook; no custom DnD needed |
| `get_global_documents_for_query()` regression: `#gdoc_N` broken by folder/tag addition | Medium | Reply broken | Wrap new code in separate block; run full test suite before merging |
| `ALTER TABLE` migration on existing prod DB fails | Low | DB error at startup | try/except pattern already established; migration is idempotent |
| Folder delete with `delete_docs` action removes docs user wanted | Medium | Data loss | Always show confirmation dialog; never silent-delete |
| Tag filter performance: many docs with many tags | Low | Slow UI | Client-side filter is O(n) per keystroke; fine for <500 docs; add server-side filter if needed later |
| File browser `onMove` hook: `doc_id` extraction from path may fail for edge-case paths | Low | Folder sync silently broken | Validate `doc_id` exists in `GlobalDocuments` before calling assign endpoint; log error and show toast on failure |
| File browser shows raw `{doc_id}/` dir names (not human-readable titles) | Medium | Poor UX in file browser | Accepted tradeoff — file browser is power-user path; global docs modal list view shows titles |
---

## 14. Out of Scope (Future)

- Cross-user folder sharing
- Folder-level access control / visibility flags
- Tag autocomplete from PKB entities (merge PKB tags with doc tags)
- Bulk tag assignment (select multiple docs, tag all at once)
- Folder color/icon customization
- Export folder as ZIP
- Canonical store / SHA256 dedup (deferred — orthogonal to this plan)

---

## 15. Testing Checklist

- [ ] Create folder, rename it, create subfolder, move subfolder to different parent
- [ ] Assign doc to folder via upload form folder picker
- [ ] Assign doc to folder via promote flow folder picker
- [ ] Assign doc to folder via context menu “Move to Folder”
- [ ] Assign doc to folder via drag-drop in folder view
- [ ] Delete folder with docs → prompt appears → choose “move to parent” → docs appear in parent folder
- [ ] Delete folder with docs → prompt appears → choose “delete docs” → docs gone from global list
- [ ] Add tags to doc via chip input → tags appear in list view row
- [ ] Filter list view by tag → only matching rows visible
- [ ] Filter list view by text search → only matching titles visible
- [ ] Click "Manage Folders" button → file browser opens pre-navigated to `storage/global_docs/{user_hash}/`
- [ ] Create folder in file browser → appears in folder picker `<select>` in upload form after refresh
- [ ] Drag doc-folder in file browser to a new folder → `onMove` hook fires → `GET /global_docs/list` shows updated `folder_id` on doc row
- [ ] Type `#folder:Research` in chat → autocomplete shows “Research” folder
- [ ] Send `#folder:Research` in chat → all docs in Research folder included in context
- [ ] Send `#tag:ml` in chat → all docs with `ml` tag included in context
- [ ] `#gdoc_all` still works as before (no regression)
- [ ] `#gdoc_N` still works as before (no regression)
- [ ] Upload new doc with folder selected → doc lands in that folder
- [ ] Promote local doc to global with folder selected → doc lands in that folder