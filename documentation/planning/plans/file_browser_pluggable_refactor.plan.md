# FileBrowserManager — Pluggable Config Refactor

**Status:** Planning
**Created:** 2026-02-26
**Scope:** `interface/file-browser-manager.js` only. No backend changes. No HTML changes. Fully backward-compatible.
**Estimated effort:** ~9h

---

## 1. Why

### 1.1 Current Problem
`FileBrowserManager` has exactly **one** pluggable hook (`onMove`). Every other behavior is hardcoded:
- All 9 API endpoint paths are string literals in the function bodies.
- All 50+ DOM element IDs (`#file-browser-*`) are hardcoded selectors.
- All toolbar button enable/disable rules are hardcoded in `_updateToolbarForFileType()`.
- All context menu items (new file, rename, delete, move) are hardcoded.
- Tree row rendering is fixed HTML (`<span class="tree-icon">`, `<span class="tree-name">`).
- There is no way to use the file browser in a second context without forking the file.

### 1.2 The Goal
We need to embed the file browser in **two contexts**:

1. **Settings → Actions (current)** — full-featured general-purpose file browser. No changes to current behavior.
2. **Global Docs Folder View (new)** — embedded inside the global docs modal, pre-navigated to `storage/global_docs/{user_hash}/`, showing doc titles + tag chips instead of raw `{doc_id}/` directory names, with folder CRUD wired to our doc folder API, and no code editor.

### 1.3 Why Refactor Instead of Fork
- A fork creates two parallel UIs to maintain. Every bug fix or feature in the file browser must be applied twice.
- The `onMove` callback pattern is already proven and working. Extending it to all operations is a mechanical, low-risk change.
- Every new embedding context (e.g. a future “pick a document” file picker) gets it for free.

### 1.4 Guiding Principle
> **All defaults must reproduce today’s exact behavior.** The Settings → Actions usage passes no config today and must continue to work without any changes after this refactor.

---

## 2. Compatibility Requirements

| Requirement | Detail |
|---|---|
| Zero breaking changes | `FileBrowserManager.init()` with no arguments must behave identically to today |
| Zero HTML changes | No new `<div>` or `id=` attributes added to `interface.html` for the existing usage |
| Zero backend changes | All existing `/file-browser/*` endpoints unchanged |
| `configure(cfg)` still works | Post-init override still merges into `_config` |
| `onMove` contract unchanged | Same `(srcPath, destPath, done)` signature, same default implementation |
| Service worker version bump | `file-browser-manager.js` is precached — `?v=N` in script tag AND `CACHE_VERSION` in `service-worker.js` must be bumped together after the refactor |

---

## 3. Full Config Schema (Target State)

This is the complete `_config` object after the refactor. Every field has a default that reproduces today’s behavior exactly.

```javascript
var _config = {

    // ── Group 1: API Endpoints ─────────────────────────────────────────
    // All paths used by AJAX calls. Override the whole object or individual keys.
    // Set any value to null to disable that operation entirely.
    endpoints: {
        tree:     '/file-browser/tree',     // GET  ?path=  → {status, entries:[{name,type}]}
        read:     '/file-browser/read',     // GET  ?path=  → {status, content, size, is_binary, too_large}
        write:    '/file-browser/write',    // POST {path, content}
        mkdir:    '/file-browser/mkdir',    // POST {path}
        rename:   '/file-browser/rename',   // POST {old_path, new_path}
        delete:   '/file-browser/delete',   // POST {path, recursive}
        move:     '/file-browser/move',     // POST {src_path, dest_path}  (used by default onMove)
        upload:   '/file-browser/upload',   // POST multipart {file, path, overwrite}
        download: '/file-browser/download', // GET  ?path=
        serve:    '/file-browser/serve',    // GET  ?path=  (PDF inline)
        aiEdit:   '/file-browser/ai-edit'  // POST {path, instruction, selection?, ...}
    },

    // ── Group 2: DOM Element IDs ───────────────────────────────────────
    // IDs of elements that FileBrowserManager reads/writes/binds to.
    // Only the elements that EXIST in the current HTML need to be listed.
    // For a second embedding, supply different IDs pointing to a second
    // set of elements (e.g. inside a modal).
    dom: {
        modal:              'file-browser-modal',
        openBtn:            'settings-file-browser-modal-open-button',
        tree:               'file-browser-tree',
        addressBar:         'file-browser-address-bar',
        suggestionDropdown: 'file-browser-suggestion-dropdown',
        editorContainer:    'file-browser-editor-container',
        previewContainer:   'file-browser-preview-container',
        wysiwygContainer:   'file-browser-wysiwyg-container',
        pdfContainer:       'file-browser-pdf-container',
        emptyState:         'file-browser-empty-state',
        dirtyIndicator:     'file-browser-dirty-indicator',
        tabBar:             'file-browser-tab-bar',
        viewBtnGroup:       'fb-view-btngroup',
        viewSelect:         'file-browser-view-select',
        saveBtn:            'file-browser-save-btn',
        discardBtn:         'file-browser-discard-btn',
        reloadBtn:          'file-browser-reload-btn',
        wrapBtn:            'file-browser-wrap-btn',
        downloadBtn:        'file-browser-download-btn',
        uploadBtn:          'file-browser-upload-btn',
        aiEditBtn:          'file-browser-ai-edit-btn',
        refreshBtn:         'file-browser-refresh-btn',
        newFileBtn:         'file-browser-new-file-btn',
        newFolderBtn:       'file-browser-new-folder-btn',
        sidebarToggle:      'file-browser-sidebar-toggle',
        closeBtn:           'file-browser-close-btn',
        themeSelect:        'file-browser-theme-select',
        contextMenu:        'file-browser-context-menu',
        confirmModal:       'file-browser-confirm-modal',
        nameModal:          'file-browser-name-modal',
        moveModal:          'file-browser-move-modal'
    },

    // ── Group 3: Behavior Flags ────────────────────────────────────────
    // All default true/false reproduce current behavior.
    readOnly:        false,   // true = no write/create/rename/delete/upload; hides those buttons
    allowUpload:     true,    // show/enable upload button and modal
    allowDelete:     true,    // show/enable delete in context menu
    allowRename:     true,    // show/enable rename in context menu
    allowCreate:     true,    // show/enable new file + new folder buttons
    allowMove:       true,    // show/enable move in context menu + DnD
    allowAiEdit:     true,    // show/enable AI Edit button
    showEditor:      true,    // false = tree-only mode; editor panel hidden entirely
    showAddressBar:  true,    // false = hide address bar

    // ── Group 4: Root & Title ──────────────────────────────────────────
    rootPath: '.',            // Directory to load when modal opens
    title:    'File Browser', // Text shown in modal header (not currently in HTML — future use)

    // ── Group 5: Operation Callbacks ──────────────────────────────────
    // Same contract as onMove: receive operation args + done(errorMsg|null).
    // null errorMsg = success. String = error message shown as toast.
    // Set to null to use default endpoint-based implementation.
    onMove: function (srcPath, destPath, done) {
        // default: POST to endpoints.move
        $.ajax({ url: _config.endpoints.move, method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ src_path: srcPath, dest_path: destPath }),
            success: function (r) { done(r.status === 'success' ? null : (r.error || 'Move failed')); },
            error:   function ()  { done('Move failed'); }
        });
    },
    onDelete: null,      // function(path, done) — null = use default endpoint
    onRename: null,      // function(oldPath, newPath, done) — null = use default endpoint
    onCreateFolder: null,// function(path, done) — null = use default endpoint
    onCreateFile: null,  // function(path, done) — null = use default endpoint
    onUpload: null,      // function(file, targetDir, done) — null = use default XHR upload
    onSave: null,        // function(path, content, done) — null = use default write endpoint

    // ── Group 6: Selection / Lifecycle Events ─────────────────────────
    // Pure notification callbacks — no done() needed.
    onSelect: null,      // function(path, type, entry) — user clicks a tree item
    onOpen:   null,      // function() — modal opened
    onClose:  null,      // function() — modal closed

    // ── Group 7: Custom Rendering ──────────────────────────────────────
    enrichEntry: null,   // function(entry, path, done) — async, add extra fields to entry
                         // call done(enrichedEntry). null = no enrichment.
    renderEntry: null,   // function(entry, path) — return jQuery $li or null for default rendering.
    buildContextMenu: null  // function(path, type) — return [{label,icon,action}] or null for default.
};
```

---

## 4. Helper: `_$` Selector Indirection

The key mechanical change that makes DOM IDs configurable without touching every individual selector:

```javascript
// Add this ONE helper function near the top of the IIFE, after _config is defined:
function _$(id) {
    return $('#' + (_config.dom[id] || id));
}
```

Then every `$('#file-browser-save-btn')` becomes `_$('saveBtn')`. This is the only structural pattern change — everything else is either config field reads or guard `if` statements.

**Why this approach:**
- Single change per selector site — grep-and-replace is mechanical.
- `_$('saveBtn')` is readable and self-documenting.
- Falls back to using `id` directly if not found in `_config.dom` (safety net).
- No jQuery plugin, no proxy, no Proxy object — just a one-line helper.

---

## 5. Helper: `_ep` Endpoint Accessor

```javascript
// Add alongside _$:
function _ep(name) {
    return _config.endpoints[name] || null;
}
```

Usage: `$.getJSON(_ep('tree'), { path: dirPath })`. If the endpoint is `null`, the caller guards with:
```javascript
if (!_ep('write')) { showToast('Write not supported', 'error'); return; }
```

---

## 6. Implementation Tasks

### Task 0: Preparation (~15 min)
- Create a git branch: `feature/file-browser-pluggable`.
- Verify current tests pass (open file browser in Settings → Actions, do a rename, move, upload — smoke test).
- Note current `?v=N` in `interface.html` script tag and `CACHE_VERSION` in `service-worker.js` for the final version bump.

---

### Task 1: Expand `_config` with all groups (~45 min)
**File:** `interface/file-browser-manager.js`
**Lines to change:** 62–87 (current `_config` block)

Replace the current `_config = { onMove: ... }` with the full schema from §3.

**Critical:** The `onMove` default implementation must now reference `_config.endpoints.move` instead of the hardcoded string `'/file-browser/move'`:
```javascript
// BEFORE (line 73):
url: '/file-browser/move',

// AFTER:
url: _config.endpoints.move,
```

**Validation:** `FileBrowserManager.init()` with no args must still open and function. No behavior change.

---

### Task 2: Add `_$` and `_ep` helpers (~15 min)
**File:** `interface/file-browser-manager.js`
**Insert after:** line 87 (end of `_config` block), before `var state = {`

```javascript
/** Resolve a config DOM key to a jQuery wrapped element. */
function _$(key) { return $('#' + (_config.dom[key] || key)); }

/** Resolve a config endpoint name to its URL string, or null if disabled. */
function _ep(name) { return (_config.endpoints && _config.endpoints[name]) || null; }
```

**Note:** `_$` and `_ep` must be defined AFTER `_config` but BEFORE any function that uses them. In the IIFE, `_config` is a `var` so it is hoisted — but its value is not available until after line 87 executes. Since JS hoists `var` declarations but not assignments, and functions in IIFEs are called after the IIFE executes, this ordering is safe.

---

### Task 3: Replace all hardcoded DOM selectors (~2h)
**File:** `interface/file-browser-manager.js`

Mechanically replace every `$('#file-browser-X')` with `_$('xKey')` using the mapping table below.
Use find-and-replace in your editor. After each replacement, search for the old string to confirm it’s gone.

**Selector Replacement Table:**

| Old selector | New call | Config key | Line(s) |
|---|---|---|---|
| `$('#file-browser-modal')` | `_$('modal')` | `dom.modal` | 2098, 2567 |
| `$('#settings-file-browser-modal-open-button')` | `_$('openBtn')` | `dom.openBtn` | 2098, 2101 |
| `$('#file-browser-tree')` | `_$('tree')` | `dom.tree` | 552, 569, 2474, 2488, 2501 |
| `$('#file-browser-address-bar')` | `_$('addressBar')` | `dom.addressBar` | 815, 846, 907, 929, 959, 988, 1219, 1514, 1561, 2327, 2332, 2377 |
| `$('#file-browser-suggestion-dropdown')` | `_$('suggestionDropdown')` | `dom.suggestionDropdown` | 780 |
| `$('#file-browser-editor-container')` | `_$('editorContainer')` | `dom.editorContainer` | 217, 430 |
| `$('#file-browser-preview-container')` | `_$('previewContainer')` | `dom.previewContainer` | 218 |
| `$('#file-browser-wysiwyg-container')` | `_$('wysiwygContainer')` | `dom.wysiwygContainer` | 219, 364 |
| `$('#file-browser-pdf-container')` | `_$('pdfContainer')` | `dom.pdfContainer` | 220 |
| `$('#file-browser-empty-state')` | `_$('emptyState')` | `dom.emptyState` | 221 |
| `$('#file-browser-dirty-indicator')` | `_$('dirtyIndicator')` | `dom.dirtyIndicator` | 201, 205 |
| `$('#file-browser-tab-bar')` | `_$('tabBar')` | `dom.tabBar` | 908, 930, 960, 998, 1562, 1600, 1606 |
| `$('#fb-view-btngroup')` | `_$('viewBtnGroup')` | `dom.viewBtnGroup` | 338, 339, 2553 |
| `$('#file-browser-view-select')` | `_$('viewSelect')` | `dom.viewSelect` | 341, 995, 2560 |
| `$('#file-browser-save-btn')` | `_$('saveBtn')` | `dom.saveBtn` | 202, 206, 314, 2110 |
| `$('#file-browser-discard-btn')` | `_$('discardBtn')` | `dom.discardBtn` | 203, 207, 315, 2115 |
| `$('#file-browser-ai-edit-btn')` | `_$('aiEditBtn')` | `dom.aiEditBtn` | 316, 914, 940, 1006, 1554, 2271 |
| `$('#file-browser-wrap-btn')` | `_$('wrapBtn')` | `dom.wrapBtn` | 317, 473, 916, 942, 1556, 2123 |
| `$('#file-browser-reload-btn')` | `_$('reloadBtn')` | `dom.reloadBtn` | 318, 915, 941, 1555, 2120 |
| `$('#file-browser-download-btn')` | `_$('downloadBtn')` | `dom.downloadBtn` | 320, 917, 943, 961, 1557, 2126 |
| `$('#file-browser-upload-btn')` | `_$('uploadBtn')` | `dom.uploadBtn` | 2129 |
| `$('#file-browser-refresh-btn')` | `_$('refreshBtn')` | `dom.refreshBtn` | 2209 |
| `$('#file-browser-new-file-btn')` | `_$('newFileBtn')` | `dom.newFileBtn` | 2215 |
| `$('#file-browser-new-folder-btn')` | `_$('newFolderBtn')` | `dom.newFolderBtn` | 2221 |
| `$('#file-browser-sidebar-toggle')` | `_$('sidebarToggle')` | `dom.sidebarToggle` | 1597, 1604, 2204 |
| `$('#file-browser-close-btn')` | `_$('closeBtn')` | `dom.closeBtn` | 2199 |
| `$('#file-browser-theme-select')` | `_$('themeSelect')` | `dom.themeSelect` | 2544 |
| `$('#file-browser-context-menu')` | `_$('contextMenu')` | `dom.contextMenu` | 1172, 1179, 2509, 2536 |
| `$('#file-browser-confirm-modal')` | `_$('confirmModal')` | `dom.confirmModal` | 1426, 2260 |
| `$('#file-browser-name-modal')` | `_$('nameModal')` | `dom.nameModal` | 2245 |
| `$('#file-browser-move-modal')` | `_$('moveModal')` | `dom.moveModal` | 1249, 1288, 2169 |

**Note on `getElementById` calls:** `document.getElementById('file-browser-wysiwyg-container')` at line 364 and `document.getElementById('file-browser-pdf-container')` at line 251 use the raw DOM API. Replace with:
```javascript
// line 364:
var container = document.getElementById(_config.dom.wysiwygContainer);
// line 251:
var pdfEl = document.getElementById(_config.dom.pdfContainer);
```

**Note on `#fb-*` IDs:** The upload modal (`#fb-upload-*`), move modal (`#fb-move-*`), AI edit modal (`#fb-ai-*`), and PDF progress (`#fb-pdf-*`) elements have shorter prefixed IDs. These are internal to modals that are already referenced via the modal container IDs (`uploadModal`, `moveModal`, `confirmModal`, `nameModal`). Since these sub-elements are always inside their parent modal container, they can use **scoped selectors** instead of global IDs:
```javascript
// Instead of: $('#fb-upload-submit-btn')
// Use:        _$('uploadModal').find('#fb-upload-submit-btn')
// OR: add them to dom config too (simpler, more explicit):
```
For clarity, add the key internal sub-elements to `dom` as well (see full list in §3). This adds ~15 more keys but makes every selector explicit and overridable.

---

### Task 4: Replace all hardcoded endpoint strings (~45 min)
**File:** `interface/file-browser-manager.js`

Replace every hardcoded `/file-browser/X` string with `_ep('x')`. Add a null-guard at the top of each function that calls a nullable endpoint.

**Endpoint Replacement Table:**

| Old string | New call | Function | Line(s) |
|---|---|---|---|
| `'/file-browser/tree'` | `_ep('tree')` | `loadTree()` | 503 |
| `'/file-browser/tree'` | `_ep('tree')` | `_loadMoveTree()` | 1259 |
| `'/file-browser/read'` | `_ep('read')` | `_doLoadFile()` | 892 |
| `'/file-browser/read'` | `_ep('read')` | `_doReload()` | 1098 |
| `'/file-browser/write'` | `_ep('write')` | `saveFile()` | 1041 |
| `'/file-browser/write'` | `_ep('write')` | `_createFile()` | 1440 |
| `'/file-browser/mkdir'` | `_ep('mkdir')` | `_createFolder()` | 1471 |
| `'/file-browser/rename'` | `_ep('rename')` | `_renameItem()` | 1504 |
| `'/file-browser/delete'` | `_ep('delete')` | `_deleteItem()` | 1544 |
| `'/file-browser/serve'` | `_ep('serve')` | `_loadFilePDF()` | 267 |
| `'/file-browser/ai-edit'` | `_ep('aiEdit')` | `_submitAiEdit()` | 1848 |
| `'/file-browser/download'` | `_ep('download')` | `_downloadFile()` | 1988 |
| `'/file-browser/upload'` | `_ep('upload')` | `_doUpload()` | 2053 |

**Null-guard pattern** (add at top of each function that uses a nullable endpoint):
```javascript
function saveFile() {
    if (!_ep('write')) { showToast('Write not supported in this context', 'error'); return; }
    // ... rest of function
}

function _loadFilePDF(filePath) {
    if (!_ep('serve')) { showToast('PDF serving not supported', 'error'); return; }
    var xhr = new XMLHttpRequest();
    xhr.open('GET', _ep('serve') + '?path=' + encodeURIComponent(filePath), true);
    // ...
}

function _downloadFile() {
    if (!_ep('download')) return;
    var url = _ep('download') + '?path=' + encodeURIComponent(state.currentPath);
    // ...
}
```

**`loadTree` null-guard:**
```javascript
function loadTree(dirPath, $parentUl) {
    if (!_ep('tree')) return;  // tree browsing disabled
    $.getJSON(_ep('tree'), { path: dirPath })
    // ...
}
```

---

### Task 5: Add behavior flag guards (~1h)
**File:** `interface/file-browser-manager.js`

Add guards in two places:

#### 5a. At `_showFileBrowserModal()` — hide/show buttons on open

Add a helper called once when the modal opens:
```javascript
function _applyBehaviorFlags() {
    // readOnly implies all write operations disabled
    var ro = _config.readOnly;
    _$('saveBtn').toggle(!ro && !!_ep('write'));
    _$('discardBtn').toggle(!ro && !!_ep('write'));
    _$('newFileBtn').toggle(!ro && _config.allowCreate && !!_ep('write'));
    _$('newFolderBtn').toggle(!ro && _config.allowCreate && !!_ep('mkdir'));
    _$('uploadBtn').toggle(!ro && _config.allowUpload && !!_ep('upload'));
    _$('reloadBtn').toggle(!!_ep('read'));
    _$('downloadBtn').toggle(!!_ep('download'));
    _$('aiEditBtn').toggle(!ro && _config.allowAiEdit && !!_ep('aiEdit'));
    if (!_config.showEditor) {
        _$('editorContainer').hide();
        _$('previewContainer').hide();
        _$('wysiwygContainer').hide();
        _$('tabBar').hide();
    }
    if (!_config.showAddressBar) {
        _$('addressBar').closest('.fb-address-bar-wrap').hide();
    }
}
```

Call `_applyBehaviorFlags()` at the end of `_showFileBrowserModal()` (before the CodeMirror init).

#### 5b. In context menu builder — filter items based on flags

In the context menu click/populate logic (around line 2509), filter `data-action` items:
```javascript
// Before showing context menu, hide disallowed actions:
function _buildContextMenu(path, type) {
    // Check for custom builder first
    if (_config.buildContextMenu) {
        var custom = _config.buildContextMenu(path, type);
        if (custom !== null) {
            _renderCustomContextMenu(custom);
            return;
        }
    }
    // Default: show/hide standard actions based on flags
    var $menu = _$('contextMenu');
    $menu.find('[data-action="new-file"]').toggle(_config.allowCreate && !_config.readOnly);
    $menu.find('[data-action="new-folder"]').toggle(_config.allowCreate && !_config.readOnly);
    $menu.find('[data-action="rename"]').toggle(_config.allowRename && !_config.readOnly);
    $menu.find('[data-action="delete"]').toggle(_config.allowDelete && !_config.readOnly);
    $menu.find('[data-action="move"]').toggle(_config.allowMove && !_config.readOnly);
}
```

Replace the raw context menu show logic at line ~2509 with a call to `_buildContextMenu(path, type)`.

---

### Task 6: Wire operation callbacks (`onDelete`, `onRename`, `onCreateFolder`, `onCreateFile`, `onSave`, `onUpload`) (~1h)
**File:** `interface/file-browser-manager.js`

Each CRUD function currently calls an endpoint directly. Wrap each one with the same pattern as `onMove`:
- If the config callback is non-null, call it.
- If null, use the default endpoint-based implementation.

**Pattern (identical for all operations):**
```javascript
function _deleteItem() {
    if (!state.contextTarget) return;
    var path = state.contextTarget.path;
    _showConfirmModal('Delete', '<p>Delete <strong>' + _basename(path) + '</strong>?</p>',
        function () {
            var done = function(err) {
                if (err) { showToast('Delete failed: ' + err, 'error'); return; }
                showToast('Deleted: ' + _basename(path), 'success');
                _refreshTree();
                if (state.currentPath === path) _showView('empty');
            };
            // NEW: check for custom callback
            if (_config.onDelete) {
                _config.onDelete(path, done);
            } else {
                // default: use endpoint
                if (!_ep('delete')) { done('Delete not supported'); return; }
                $.ajax({ url: _ep('delete'), method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ path: path, recursive: true }),
                    success: function(r) { done(r.status === 'success' ? null : (r.error || 'Delete failed')); },
                    error:   function()  { done('Delete failed'); }
                });
            }
        },
        { okText: 'Delete', okClass: 'btn-danger' }
    );
}
```

Apply same pattern to:
- `saveFile()` → check `_config.onSave` before `$.ajax(url: _ep('write'), ...)`
- `_renameItem()` → check `_config.onRename` before `$.ajax(url: _ep('rename'), ...)`
- `_createFolder()` → check `_config.onCreateFolder` before `$.ajax(url: _ep('mkdir'), ...)`
- `_createFile()` → check `_config.onCreateFile` before `$.ajax(url: _ep('write'), ...)`
- `_doUpload()` → check `_config.onUpload` before XHR to `_ep('upload')`

**Key:** The `done` callback signature is always `done(errorMsg|null)`. The surrounding UI logic (toast, tree refresh, dirty state reset) lives in the caller, not in the callback itself.

---

### Task 7: Add lifecycle event hooks (`onSelect`, `onOpen`, `onClose`) (~30 min)
**File:** `interface/file-browser-manager.js`

**`onSelect`** — fire when a tree item is clicked (after the default action):
```javascript
// In the tree click handler (around line 2474):
container.on('click', 'li', function(e) {
    var $li = $(this);
    var path = $li.data('path');
    var type = $li.data('type');
    // ... existing logic (toggleDir or loadFile) ...
    // Fire onSelect AFTER default action:
    if (_config.onSelect) {
        _config.onSelect(path, type, $li.data('entry') || { name: $li.data('name'), type: type });
    }
});
```

**`onOpen`** — fire at end of `_showFileBrowserModal()`:
```javascript
function _showFileBrowserModal() {
    // ... existing open logic ...
    _applyBehaviorFlags();  // Task 5
    if (_config.rootPath && _config.rootPath !== '.') {
        state.currentDir = _config.rootPath;
    }
    if (_config.onOpen) _config.onOpen();
}
```

**`onClose`** — fire at start of `_closeModal()` (before dirty check):
```javascript
function _closeModal() {
    if (_config.onClose) _config.onClose();
    // ... existing close logic ...
}
```

**`rootPath` handling in `_showFileBrowserModal()`:**
When `_config.rootPath` is set to a non-default path, `loadTree` should start from that path:
```javascript
// In _showFileBrowserModal(), where loadTree is first called:
var startDir = _config.rootPath || '.'
loadTree(startDir, null);
state.currentDir = startDir;
_$('addressBar').val(startDir);
```

---

### Task 8: Add `enrichEntry` + `renderEntry` custom rendering (~2h)
**File:** `interface/file-browser-manager.js`

This is the most complex task. It modifies the tree rendering loop (`loadTree`, lines 512–539).

#### 8a. Store `entry` object on each `<li>`

In the rendering loop, store the raw `entry` (plus any enriched fields) on the `$li` for use by `onSelect` and custom renderers:
```javascript
$li.data('entry', entry);   // add after line 522
```

#### 8b. Add `enrichEntry` support

`enrichEntry` is async — it fetches extra metadata per entry (e.g. doc title from `/global_docs/info/{doc_id}`). It must not block the tree render. The approach:
1. Render the tree immediately with default content (no delay).
2. After render, if `_config.enrichEntry` is set, call it per entry and update the `<li>` in place.

```javascript
// AFTER the entries.forEach loop (after line 539), add:
if (_config.enrichEntry) {
    $ul.find('li').each(function() {
        var $li = $(this);
        var entry = $li.data('entry');
        if (!entry) return;
        _config.enrichEntry(entry, $li.attr('data-path'), function(enriched) {
            $li.data('entry', enriched);  // update stored entry
            if (_config.renderEntry) {
                var $custom = _config.renderEntry(enriched, $li.attr('data-path'));
                if ($custom) {
                    // Replace <li> content (keep data attrs, draggable)
                    $li.empty().append($custom.contents());
                }
            }
        });
    });
}
```

**Important:** `enrichEntry` is called per visible entry. Callers should cache results (e.g. in a `Map` keyed by `doc_id`) to avoid re-fetching on every tree expand/refresh.

#### 8c. Add `renderEntry` support (sync, no enrichment)

For cases where the caller has all data already (e.g. from a pre-fetched batch):
```javascript
// In the entries.forEach loop, after building $li (after line 526):
if (_config.renderEntry) {
    var $custom = _config.renderEntry(entry, entryPath);
    if ($custom) {
        $li.empty().append($custom.contents());
    }
}
```

#### 8d. `renderEntry` contract
```javascript
// renderEntry(entry, path) must return:
// - a jQuery $li element whose .contents() will replace the default icon+name spans
// - OR null to use default rendering
//
// Example:
renderEntry: function(entry, path) {
    if (entry.type !== 'dir' || !entry.title) return null;
    var $wrap = $('<span></span>');
    $wrap.append($('<span class="tree-name"></span>').text(entry.title));
    (entry.tags || []).slice(0, 3).forEach(function(tag) {
        $wrap.append($('<span class="badge badge-pill badge-secondary ml-1" style="font-size:0.7em">' + tag + '</span>'));
    });
    return $wrap;
}
```

---

### Task 9: Add `buildContextMenu` custom rendering (~45 min)
**File:** `interface/file-browser-manager.js`

The context menu currently shows a fixed set of `<a data-action="...">` items. For the global docs context, we want different items (e.g. no “New File”, but “Rename Folder” maps to a folder rename API).

Replace the context menu display logic (around line 2509) with:
```javascript
function _showContextMenu(e, path, type) {
    state.contextTarget = { path: path, type: type };
    var $menu = _$('contextMenu');

    if (_config.buildContextMenu) {
        var items = _config.buildContextMenu(path, type);
        if (items !== null) {
            // Render custom menu items
            $menu.find('ul').empty();
            items.forEach(function(item) {
                var $a = $('<a href="#" class="dropdown-item"></a>')
                    .html('<i class="' + (item.icon || '') + ' mr-2"></i>' + item.label)
                    .on('click', function(e) {
                        e.preventDefault();
                        _hideContextMenu();
                        item.action(path, type);
                    });
                $menu.find('ul').append($('<li></li>').append($a));
            });
            _positionAndShow($menu, e);
            return;
        }
    }
    // Default: show/hide standard items based on flags (Task 5b)
    _buildContextMenu(path, type);
    _positionAndShow($menu, e);
}
```

---

### Task 10: Update `init()` event handler wiring to use `_$` (~30 min)
**File:** `interface/file-browser-manager.js`

The `init()` function (lines 2092–2587) wires ~60 event handlers, all using hardcoded `$('#file-browser-*')` selectors. After Task 3 replaces all selectors globally, `init()` is automatically fixed — no separate changes needed here.

**One additional change:** The hardcoded open-button binding (line 2101):
```javascript
// BEFORE:
$('#settings-file-browser-modal-open-button').on('click', function () {
    open();
});

// AFTER:
_$('openBtn').on('click', function () {
    open();
});
```
This allows a different button to open the file browser in a second embedding context.

---

### Task 11: Expose `open(path)` with optional start path (~15 min)
**File:** `interface/file-browser-manager.js`

The existing `open()` function opens the modal. Add an optional `path` argument to navigate to a specific directory on open (used by the “Manage Folders” button in global docs modal):
```javascript
function open(path) {
    if (path) { state.currentDir = path; }
    _showFileBrowserModal();
}
```

This is already additive — `open()` with no args uses `_config.rootPath` (Task 7), `open(path)` overrides for that one open.

---

### Task 12: Update public API + JSDoc (~15 min)
**File:** `interface/file-browser-manager.js`

```javascript
return {
    /**
     * Initialize event handlers. Call once on page load.
     * @param {object} [cfg] - Config overrides (see _config schema in plan).
     */
    init: init,
    /**
     * Open the file browser modal.
     * @param {string} [path] - Optional starting directory path.
     */
    open: open,
    loadFile:       loadFile,
    saveFile:       saveFile,
    discardChanges: discardChanges,
    /**
     * Override config options after initialization.
     * Supports all _config fields (endpoints, dom, flags, callbacks).
     * @param {object} cfg - Config overrides.
     */
    configure: function (cfg) { $.extend(true, _config, cfg); }  // deep merge for nested objects
};
```

**Change `$.extend` to `$.extend(true, ...)` (deep merge)** so callers can override individual endpoint keys without having to re-specify all 11:
```javascript
// BEFORE: shallow merge loses other endpoint keys
FileBrowserManager.configure({ endpoints: { upload: '/global_docs/upload' } });
// → _config.endpoints = { upload: '/global_docs/upload' }  → all other endpoints GONE

// AFTER: deep merge preserves other keys
FileBrowserManager.configure({ endpoints: { upload: '/global_docs/upload' } });
// → _config.endpoints = { tree: '/file-browser/tree', ..., upload: '/global_docs/upload' }
```

---

### Task 13: Service worker + cache version bump (~5 min)
**Files:** `interface/interface.html`, `interface/service-worker.js`

After all JS changes are done:
1. In `interface/interface.html`: find the `<script src=".../file-browser-manager.js?v=N">` tag and increment `N`.
2. In `interface/service-worker.js`: find `CACHE_VERSION` and increment it.
3. Both must be bumped **together** or stale JS will be served from service worker cache.

---

## 7. Implementation Order & Dependency Graph

```
Task 0  (prep + smoke test)
  │
Task 1  (expand _config schema)
  │
Task 2  (add _$ and _ep helpers)
  │
  ├── Task 3  (replace DOM selectors) ───────────────────────────────┐
  │                                                              │
  └── Task 4  (replace endpoint strings)                         │
        │                                                        │
        ├── Task 5  (behavior flag guards)                        │
        │     │                                                  │
        │     └── Task 6  (operation callbacks)                    │
        │           │                                            │
        │           └── Task 7  (lifecycle events + rootPath)      │
        │                 │                                      │
        │                 └── Task 8  (enrichEntry/renderEntry) ──┘
        │                       │
        │                       └── Task 9  (buildContextMenu)
        │
        └────────────────────────────────── Task 10 (init() uses _$)

Task 11 (open(path))  ── independent, can be done any time
Task 12 (public API update)  ── after all above
Task 13 (cache version bump)  ── very last
```

Tasks 3 and 4 can be done in parallel (different search patterns, no overlap).
Tasks 5, 6, 7, 8, 9 must be sequential (each builds on previous).

---

## 8. Time Estimates

| Task | Description | Estimate |
|---|---|---|
| 0 | Prep, smoke test, branch | 15 min |
| 1 | Expand `_config` schema | 45 min |
| 2 | Add `_$` and `_ep` helpers | 15 min |
| 3 | Replace all DOM selectors (~50 sites) | 90 min |
| 4 | Replace all endpoint strings (~13 sites) | 45 min |
| 5 | Behavior flag guards + `_applyBehaviorFlags()` | 60 min |
| 6 | Operation callbacks (6 functions) | 60 min |
| 7 | Lifecycle events + `rootPath` | 30 min |
| 8 | `enrichEntry` + `renderEntry` | 90 min |
| 9 | `buildContextMenu` | 45 min |
| 10 | `init()` uses `_$` (covered by Task 3) | 0 min |
| 11 | `open(path)` optional arg | 15 min |
| 12 | Public API + JSDoc | 15 min |
| 13 | Cache version bump | 5 min |
| **Total** | | **~9h** |

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `$.extend` shallow merge breaks nested `endpoints` override | High (if not fixed) | Silent data loss | Use `$.extend(true, ...)` deep merge in `configure()` (Task 12) |
| Missed selector — one `$('#file-browser-X')` not replaced | Medium | Broken in second context, fine in default | After Task 3, grep for `'#file-browser-'` and `'#fb-'` — zero results expected |
| `_$` helper called before `_config` is initialized | Low | TypeError | `_config` is a `var` at IIFE scope; `_$` is only called inside functions which run after init |
| `enrichEntry` called too many times — floods API | Medium | API rate limit / slow UI | Callers MUST cache by `entry.name` (doc_id). Document this in JSDoc |
| `renderEntry` replaces icon span — breaks DnD which relies on `draggable` attr | Low | DnD broken | `renderEntry` replaces `$li.contents()` not `$li` itself — `data-path`, `data-type`, `draggable` stay on `$li` |
| `readOnly` flag hides Save button but keyboard Ctrl+S still fires | Low | Silent no-op | In `saveFile()` add `if (_config.readOnly) return;` guard |
| Service worker serves stale JS after refactor | High (if not bumped) | Old code runs | Task 13 — bump both `?v=N` and `CACHE_VERSION` together |
| `null` endpoint + existing caller that doesn't guard | Medium | AJAX call to `null` URL fails silently | Add null-guard in every function (Task 4 pattern) |

---

## 10. Verification Checklist

### After each task — run the smoke test:
1. Open Settings → Actions → File Browser.
2. Browse to a directory, expand a folder.
3. Open a `.py` file — verify it loads in CodeMirror.
4. Open a `.md` file — verify Raw/Preview/WYSIWYG tabs appear.
5. Open a `.pdf` file — verify PDF viewer renders.
6. Rename a file — verify tree refreshes.
7. Create a folder — verify it appears in tree.
8. Move a file via drag-drop — verify it moves.
9. Move a file via right-click “Move to…” — verify picker shows correctly.
10. Delete a file — verify confirm modal appears and deletion works.
11. Upload a file — verify progress bar and success toast.
12. AI Edit (Cmd+K) — verify diff overlay appears.

### After Task 3 specifically:
- Grep for `'#file-browser-'` in `file-browser-manager.js` — **must be zero results**.
- Grep for `"#fb-"` in `file-browser-manager.js` — **must be zero results** (or only in HTML strings that are not selectors).

### After Task 4 specifically:
- Grep for `'/file-browser/'` in `file-browser-manager.js` — **must be zero results**.

### Final verification — second embedding test:
```javascript
// Paste in browser console after refactor to verify second-context config works:
FileBrowserManager.configure({
    rootPath: 'storage',
    showEditor: false,
    allowAiEdit: false,
    readOnly: true,
    onOpen: function() { console.log('opened'); },
    onClose: function() { console.log('closed'); },
    onSelect: function(path, type) { console.log('selected:', path, type); }
});
FileBrowserManager.open();
// Expected: modal opens at storage/, no editor panel, no Save/Discard/AI Edit buttons,
// console logs 'opened', clicking a file logs 'selected: ...'
```

---

## 11. How the Global Docs Folder View Will Use This

Once the refactor is done, wiring the global docs folder view takes approximately 2h:

```javascript
// In interface/chat.js or global-docs-manager.js setup:

var userHash = /* get from server or compute */;
var docRootPath = 'storage/global_docs/' + userHash + '/';

// Pre-fetch all global docs metadata once for enrichEntry cache:
var _docMetaCache = {};   // doc_id -> { title, tags }
GlobalDocsManager.list().done(function(docs) {
    docs.forEach(function(d) { _docMetaCache[d.doc_id] = d; });
});

// Wire the file browser for the global docs folder view:
FileBrowserManager.configure({
    rootPath:    docRootPath,
    showEditor:  false,          // tree-only, no CodeMirror
    allowAiEdit: false,
    allowCreate: false,          // docs are created via upload, not 'New File'
    endpoints: {
        upload:   '/global_docs/upload',   // override upload → our endpoint
        download: '/global_docs/download', // override download
        serve:    '/global_docs/serve',    // override serve for PDF viewer
        write:    null,                    // no raw file editing
        read:     null,                    // no raw file reading
        aiEdit:   null                     // no AI edit
    },
    onMove: function(srcPath, destPath, done) {
        // file browser moved a {doc_id}/ folder to a new parent
        var docId     = srcPath.split('/').pop();
        var folderDir = destPath.split('/').slice(0, -1).join('/');
        var folderName = folderDir.split('/').pop();
        // resolve folder name → folder_id via DB, then assign
        $.getJSON('/doc_folders/autocomplete', { prefix: folderName })
            .done(function(folders) {
                var match = folders.find(function(f) { return f.name === folderName; });
                if (!match) { done('Folder not found'); return; }
                $.post('/doc_folders/' + match.folder_id + '/assign', { doc_id: docId })
                    .done(function() { done(null); })
                    .fail(function() { done('Assign failed'); });
            });
    },
    enrichEntry: function(entry, path, done) {
        // Only enrich directory entries (each dir = one doc)
        if (entry.type !== 'dir') { done(entry); return; }
        var docId = entry.name;
        var cached = _docMetaCache[docId];
        if (cached) { done($.extend({}, entry, cached)); return; }
        // Not in cache: fetch individually
        $.getJSON('/global_docs/info/' + docId, function(info) {
            _docMetaCache[docId] = info;
            done($.extend({}, entry, info));
        }).fail(function() { done(entry); });
    },
    renderEntry: function(entry, path) {
        if (entry.type !== 'dir') return null;
        var title = entry.title || entry.name;
        var $wrap = $('<span></span>')
            .append($('<span class="tree-name"></span>').text(title));
        (entry.tags || []).slice(0, 3).forEach(function(tag) {
            $wrap.append($('<span class="badge badge-pill badge-secondary ml-1" style="font-size:0.7em">' + tag + '</span>'));
        });
        return $wrap;
    },
    buildContextMenu: function(path, type) {
        if (type !== 'dir') return [];  // no context menu on files
        return [
            { label: 'Rename Folder', icon: 'fa fa-edit',
              action: function(p) { /* call rename via API */ } },
            { label: 'Delete Folder', icon: 'fa fa-trash',
              action: function(p) { /* call delete via API */ } },
        ];
    },
    onSelect: function(path, type, entry) {
        if (type === 'dir' && entry.doc_id) {
            // Show doc detail in right panel of global docs modal
            GlobalDocsManager.renderFolderDocs(entry.folder_id);
        }
    },
    onOpen:  function() { GlobalDocsManager.switchToFolderView(); },
    onClose: function() { GlobalDocsManager.switchToListView(); }
});

// Open at doc root when 'Manage Folders' button is clicked:
$('#global-docs-manage-folders-btn').on('click', function() {
    FileBrowserManager.open(docRootPath);
});
```

---

## 12. Files Modified

| File | Change |
|---|---|
| `interface/file-browser-manager.js` | All changes (Tasks 1–12). This is the only file changed. |
| `interface/interface.html` | Bump `?v=N` on script tag (Task 13) |
| `interface/service-worker.js` | Bump `CACHE_VERSION` (Task 13) |

**No HTML structure changes.** No new `<div>` elements. No new `id=` attributes.
**No backend changes.** All existing `/file-browser/*` endpoints untouched.
**No other JS files change.** All other managers that call `FileBrowserManager.open()` or `FileBrowserManager.configure()` continue to work.

---

## 13. Out of Scope

- Multi-instance support (two file browsers open simultaneously on the same page) — the IIFE pattern and single `state` object don’t support this. Acceptable: global docs opens the file browser exclusively.
- Replacing CodeMirror with a different editor — editor type is not part of this config schema.
- Custom upload UI — the upload modal DOM is part of `interface.html`; a second embedding uses the same upload modal.
- Per-instance HTML — a second embedding in a modal still uses the same `#file-browser-modal` DOM. If true side-by-side instances are needed, the entire DOM layer needs to be parameterized too (future work).
- Unit tests — the codebase has no JS unit test framework. Manual smoke test is the verification method (checklist in §10).