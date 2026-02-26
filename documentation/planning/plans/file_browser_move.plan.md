# File Browser — Move File/Folder Feature Plan

## Goals

Add the ability to move files and folders within the file browser, exposed via:
1. **Drag and drop** — drag a tree item onto a target folder in the sidebar tree
2. **Right-click context menu → Move** — opens a destination picker modal with a lazy-expanding folder tree

The move operation must be **decoupled from backend implementation** via a configurable `onMove` callback so the file browser can be embedded in other contexts (PKB, attachments, etc.) with different backend endpoints or move semantics.

---

## Requirements

### Functional
- Any file or folder can be dragged onto any folder in the sidebar tree to move it
- Right-clicking any file or folder shows a "Move" item in the context menu
- Clicking Move opens a destination picker modal with a folder-only tree (no files shown)
- The destination tree supports lazy expansion (click to expand, same as main tree)
- After move, the source item disappears from its old location; the tree refreshes
- If the currently open file is moved, `state.currentPath` and address bar update to the new path
- Prevents invalid moves: cannot move a folder into itself or into its own descendant
- Shows an inline error (toast) if the move fails (409 conflict, etc.)
- Drag visual feedback: folder under cursor highlights while dragging over it
- Move is cancellable (Escape or clicking outside the modal)

### Non-Functional / Architecture
- `FileBrowserManager.init()` accepts an optional config object with `onMove(srcPath, destPath, callback)` — default implementation calls `POST /file-browser/move`
- Backend adds `POST /file-browser/move` endpoint (wraps existing rename logic)
- All new JS follows existing IIFE module pattern, `var` keyword, jQuery
- No new dependencies

---

## Architecture: Decoupling

### Config Callback Pattern

```javascript
// Caller can override at init time:
FileBrowserManager.init({
    onMove: function(srcPath, destPath, done) {
        // custom move implementation
        // call done(null) on success, done(errorMessage) on failure
    }
});
```

Default implementation (inside the module):
```javascript
var _config = {
    onMove: function(srcPath, destPath, done) {
        $.ajax({
            url: '/file-browser/move',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ src_path: srcPath, dest_path: destPath }),
            success: function(r) { done(r.status === 'success' ? null : (r.error || 'Move failed')); },
            error: function(xhr) {
                var msg = 'Move failed';
                try { msg = JSON.parse(xhr.responseText).error || msg; } catch(e) {}
                done(msg);
            }
        });
    }
};
```

`init()` now accepts an optional config argument:
```javascript
function init(cfg) {
    _config = $.extend({}, _config, cfg || {});
    // ... rest of init
}
```

---

## Backend: `/file-browser/move` Endpoint

### Why a new endpoint vs. reusing `/rename`
The existing `/rename` semantics cover both rename-in-place and cross-directory moves. Adding a dedicated `/move` makes the API intent explicit and allows different validation (e.g., you could later add quota checks, permission checks, or audit logs specific to moves). Implementation-wise it is a thin wrapper over the same `_safe_resolve` + `os.rename` pattern.

### Endpoint spec
```
POST /file-browser/move
Content-Type: application/json

{
    "src_path": "relative/source/path",
    "dest_path": "relative/destination/dir/basename"
                  OR just "relative/destination/dir/" (auto-basename)
}
```

- `dest_path` is the **full new path** (not just the destination directory). The JS layer computes it as `destDir + '/' + basename(srcPath)`.
- Returns `json_ok()` on success
- Returns 400 if fields missing, 403 if path escapes root, 404 if source not found, 409 if dest already exists, 500 on OS error

### Implementation sketch
```python
@file_browser_bp.route("/file-browser/move", methods=["POST"])
@login_required
def move():
    data = request.get_json(silent=True) or {}
    src_rel = data.get("src_path", "")
    dest_rel = data.get("dest_path", "")
    # validate, safe_resolve, existence check, os.rename
    # (same pattern as rename())
```

---

## Frontend: New State

Add to `state` object:
```javascript
dragSource: null,        // {path, type, name} of item being dragged
moveTarget: null,        // {path, type, name} of item being moved (context menu)
```

---

## Frontend: Drag and Drop

### Events (delegated on `#file-browser-tree`)

| Event | Element | Action |
|-------|---------|--------|
| `dragstart` | `li` | Set `state.dragSource`, set `e.dataTransfer.effectAllowed = 'move'` |
| `dragend` | `li` | Clear `state.dragSource`, remove all `.fb-drag-over` classes |
| `dragover` | `li[data-type=dir]` | `e.preventDefault()`, add `.fb-drag-over` class if valid target |
| `dragleave` | `li[data-type=dir]` | Remove `.fb-drag-over` class |
| `drop` | `li[data-type=dir]` | Call `_moveItem(state.dragSource.path, targetPath + '/' + basename(dragSource.path))` |

### Validity check before drop
```javascript
function _isValidMoveTarget(srcPath, destDirPath) {
    // Cannot drop onto self (if src is a dir)
    if (srcPath === destDirPath) return false;
    // Cannot drop into own descendant
    if (destDirPath.indexOf(srcPath + '/') === 0) return false;
    // Cannot drop into own current parent (no-op)
    if (_parentDir(srcPath) === destDirPath) return false;
    return true;
}
```

### Make tree items draggable
In `loadTree()`, add `draggable="true"` attribute to each `$li`:
```javascript
var $li = $('<li></li>')
    .attr('data-path', entryPath)
    .attr('data-type', entry.type)
    .attr('data-name', entry.name)
    .attr('draggable', 'true');   // ADD THIS
```

---

## Frontend: Context Menu "Move" item

Add to `#file-browser-context-menu` HTML (after Rename, before Delete divider):
```html
<a class="dropdown-item" href="#" data-action="move"><i class="bi bi-folder-symlink"></i> Move to…</a>
```

Add case to `switch (action)` in context menu handler:
```javascript
case 'move': _showMoveModal(); break;
```

---

## Frontend: Move Destination Modal

### Modal HTML (z-index: 100004, between upload 100003 and context-menu 100005)

```html
<div id="file-browser-move-modal" style="display:none; position:fixed; inset:0; z-index:100004; background:rgba(0,0,0,0.35); align-items:center; justify-content:center;">
    <div style="background:#fff; border-radius:8px; box-shadow:0 4px 16px rgba(0,0,0,0.25); width:420px; max-width:94vw; padding:0; display:flex; flex-direction:column; max-height:80vh;">
        <div style="padding:10px 16px; border-bottom:1px solid #dee2e6; font-weight:600; font-size:0.9rem;">
            Move: <span id="fb-move-src-name" style="font-weight:400;"></span>
        </div>
        <div style="padding:8px 12px; font-size:0.8rem; color:#6c757d;">Select destination folder:</div>
        <div id="fb-move-folder-tree" style="flex:1; overflow-y:auto; padding:4px 8px; min-height:120px; max-height:45vh; border-top:1px solid #f0f0f0;"></div>
        <div id="fb-move-dest-hint" style="padding:6px 14px; font-size:0.78rem; color:#495057; border-top:1px solid #f0f0f0; min-height:28px;"></div>
        <div style="padding:10px 14px; border-top:1px solid #dee2e6; display:flex; justify-content:flex-end; gap:8px;">
            <button id="fb-move-cancel-btn" class="btn btn-sm btn-secondary">Cancel</button>
            <button id="fb-move-ok-btn" class="btn btn-sm btn-primary" disabled>Move Here</button>
        </div>
    </div>
</div>
```

### JS Functions

#### `_showMoveModal()`
- Sets `state.moveTarget = state.contextTarget`
- Populates `#fb-move-src-name` with the item's name
- Clears `#fb-move-folder-tree`, clears `#fb-move-dest-hint`
- Disables `#fb-move-ok-btn`
- Calls `_loadMoveTree('.', $('#fb-move-folder-tree'))` to populate root folders
- Shows modal with `display: flex`

#### `_loadMoveTree(dirPath, $container)`
- Similar to `loadTree()` but only renders `data-type=dir` entries
- Each folder `<li>` gets `data-path`, `data-type=dir`, `data-name` and click handler:
  - Expands/collapses sub-tree (same as `_toggleDir`)
  - Highlights selected folder and updates `#fb-move-dest-hint`
  - Enables `#fb-move-ok-btn`

#### `_hideMoveModal()`
- Hides modal, clears `state.moveTarget`

#### `_confirmMove()`
- Gets selected destination dir from `state.moveDest`
- Computes `destPath = moveDest + '/' + _basename(state.moveTarget.path)`
- Validates with `_isValidMoveTarget`
- Calls `_moveItem(state.moveTarget.path, destPath)`

#### `_moveItem(srcPath, destPath)`
- Shows a brief loading state (disable Move button)
- Calls `_config.onMove(srcPath, destPath, function(err) { ... })`
- On success:
  - If `state.currentPath === srcPath`: update `state.currentPath = destPath` and address bar
  - Call `_refreshTree()` to reload entire tree
  - `_hideMoveModal()`
  - `showToast('Moved successfully', 'success')`
- On error:
  - `showToast(err, 'error')`
  - Re-enable Move button

---

## CSS Changes (`interface/style.css`)

```css
/* Drag-over highlight for move target folders */
#file-browser-tree li.fb-drag-over > .tree-icon,
#file-browser-tree li.fb-drag-over > .tree-name {
    background: #e3f0ff;
    border-radius: 3px;
}
#file-browser-tree li.fb-drag-over {
    outline: 1.5px dashed #4a90e2;
    outline-offset: -1px;
    border-radius: 3px;
}

/* Move modal folder tree item hover */
#fb-move-folder-tree li {
    padding: 3px 6px;
    cursor: pointer;
    border-radius: 4px;
    list-style: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 0.85rem;
    user-select: none;
}
#fb-move-folder-tree li:hover {
    background: #f0f4ff;
}
#fb-move-folder-tree li.fb-move-selected {
    background: #d0e4ff;
    font-weight: 600;
}
#fb-move-folder-tree ul {
    padding-left: 14px;
    margin: 0;
}
```

---

## Files Modified

| File | Change |
|------|--------|
| `endpoints/file_browser.py` | Add `POST /file-browser/move` endpoint |
| `interface/interface.html` | Add Move item to context menu; add move modal HTML |
| `interface/file-browser-manager.js` | `_config` + `onMove` callback; `state.dragSource`, `state.moveTarget`, `state.moveDest`; `init(cfg)` signature; `draggable="true"` on tree items; drag event handlers; `_showMoveModal`, `_loadMoveTree`, `_hideMoveModal`, `_confirmMove`, `_moveItem`, `_isValidMoveTarget`; expose `configure(cfg)` in public API |
| `interface/style.css` | Drag-over + move modal tree styles |
| `interface/service-worker.js` | Bump CACHE_VERSION v25 → v26 |
| `interface/interface.html` | Update `?v=24` → `?v=25` on file-browser-manager.js script tag |
| `documentation/features/file_browser/README.md` | Document move feature |

---

## Tasks (Atomic Implementation Steps)

1. **Backend**: Add `move()` endpoint to `endpoints/file_browser.py` (after `rename()`, same pattern)
2. **HTML**: Add `data-action="move"` item to `#file-browser-context-menu` (after Rename, before Delete divider)
3. **HTML**: Add `#file-browser-move-modal` HTML block (after upload modal, before AI edit modal)
4. **JS**: Add `_config` var + `init(cfg)` config merging + `state.dragSource / moveTarget / moveDest` to state
5. **JS**: Add `draggable="true"` to `$li` construction in `loadTree()`
6. **JS**: Add drag event handlers in `init()` (delegated on `#file-browser-tree`)
7. **JS**: Add `_isValidMoveTarget()`, `_moveItem()`, `_showMoveModal()`, `_loadMoveTree()`, `_hideMoveModal()`, `_confirmMove()` functions
8. **JS**: Add `case 'move'` to context menu action switch
9. **JS**: Wire up move modal buttons in `init()` + add `configure` to public API
10. **CSS**: Add drag-over + move modal tree styles to `style.css`
11. **Version bumps**: CACHE_VERSION v25→v26, script tag v24→v25

---

## Risks and Alternatives

- **`os.rename()` across filesystems**: On Linux/Mac this fails if source and dest are on different filesystems. For our use case (server-local files all on same FS) this is fine. If needed, fall back to `shutil.move()`.
- **Conflict on move**: 409 response if destination already has an item with the same name. The JS should surface this clearly with a toast: "A file named 'X' already exists there."
- **Undo**: Not planned in this iteration. A future `move_history` in state could support it.
- **Multi-select move**: Out of scope for this iteration.
