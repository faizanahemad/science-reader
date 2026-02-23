# File Browser & Editor — Full-Screen Modal

## Goal

Add a **File Browser** action button to the chat-settings-modal Actions section that opens a full-screen modal. The modal provides a VS Code-like experience: a collapsible file tree sidebar on the left, an address bar on top for direct path navigation, and a code editor area on the right with syntax highlighting (via CodeMirror 5, already in the project). Markdown files get a live preview tab. Users can edit and save files or discard changes. Full CRUD: create new files/folders, rename, delete. All files within the server's running directory are accessible.

## Decisions (from clarification)

| Question | Decision |
|---|---|
| Authentication | `@login_required` on all endpoints |
| Modal stacking | Close chat-settings-modal first, then open file browser |
| Keyboard shortcuts | Ctrl+S / Cmd+S to save, Escape to close (with unsaved-changes confirm) |
| Hidden files | Always visible (`.git`, `__pycache__`, `node_modules`, `.env` — all shown) |
| Root directory | Server running directory only (sandboxed, cannot escape) |
| Markdown renderer | Reuse project's `marked.js` (same as chat messages) |
| File operations | Full CRUD — New File, New Folder, Rename, Delete (context menu) |
| Editor theme | Separate small theme picker dropdown in file browser header |
| CodeMirror modes | Only use pre-loaded modes (python, js, css, htmlmixed, xml, markdown, gfm). Other file types → plain text |
| State persistence | Preserve within session (last file, expanded dirs, sidebar state survive close/reopen) |
| Address bar | Shows both file and directory paths; typing a dir path navigates the tree |

## Requirements

### Functional
1. **Entry point**: New "File Browser" button in chat-settings-modal → Actions section
2. **Full-screen modal**: ~95vw × 90vh (matching the OpenCode Terminal modal pattern)
3. **File tree sidebar** (left panel):
   - Displays directory tree rooted at the server's working directory
   - Lazy-loaded (expand directories on click — don't load the entire tree upfront)
   - Collapsible/minimizable sidebar (toggle button to hide/show)
   - Icons to differentiate files vs directories
   - Click a file → loads it in the editor
   - Click a directory → expand/collapse + update address bar
   - Current file highlighted in tree
   - All files visible (including hidden files, `.git`, `__pycache__`, etc.)
   - Right-click context menu: New File, New Folder, Rename, Delete
4. **Address bar** (top):
   - Shows current file or directory path relative to server root
   - Editable — user can type/paste a path and press Enter to navigate
   - If path is a directory → navigate tree to that directory
   - If path is a file → load it in the editor
5. **Editor area** (right/main panel):
   - Uses CodeMirror 5 (already loaded in the project) for syntax highlighting
   - Auto-detect language mode from file extension (pre-loaded modes only: python, javascript, css, htmlmixed, xml, markdown, gfm; others → plain text)
   - Line numbers, code folding
   - Theme picker dropdown (small, in header) — maps to CodeMirror themes
   - For Markdown files (`.md`): tabbed Code / Preview view (reuse `marked.js` from `common.js`)
   - Read-only mode for binary files (show message) or very large files (show warning + truncate)
6. **Save / Discard**:
   - "Save" button writes changes back to server (also: Ctrl+S / Cmd+S)
   - "Discard" button reverts to last-saved content
   - Unsaved-changes indicator (asterisk `*` on filename in header)
   - Confirm prompt if navigating away with unsaved changes
   - Escape key closes modal (with unsaved-changes confirm if dirty)
7. **CRUD operations** (via right-click context menu on tree items):
   - **New File**: Prompt for name → create empty file → open in editor
   - **New Folder**: Prompt for name → create directory
   - **Rename**: Prompt for new name → rename file/folder
   - **Delete**: Confirm → delete file/folder (recursive for non-empty dirs? — confirm with extra warning)
8. **File size guard**: Files above 2MB show a warning before loading, with "Load Anyway" button
9. **State persistence**: Last opened file, expanded tree dirs, sidebar visibility persist across open/close within the same browser session (in-memory state, not localStorage)

### Non-Functional
- No new JS frameworks — jQuery + Bootstrap 4.6 + CodeMirror 5 only
- No new npm/pip dependencies (all libs already loaded via CDN in interface.html)
- Follow existing manager module pattern (`ArtefactsManager`, `PromptManager`)
- Follow existing endpoint blueprint pattern (`endpoints/*.py`)
- Security: `@login_required` on all endpoints + path traversal prevention (no escaping server root dir)

## Existing Patterns to Follow

### Button (interface.html, Actions section, ~line 2198)
```html
<div class="col">
    <button class="btn btn-primary btn-sm rounded-pill w-100" id="settings-file-browser-modal-open-button">
        <i class="bi bi-folder2-open"></i> File Browser
    </button>
</div>
```

### Manager module (e.g. `artefacts-manager.js`, `prompt-manager.js`)
```javascript
var FileBrowserManager = (function () {
    'use strict';
    var state = { ... };
    function init() { setupEventHandlers(); }
    function open() { loadTree(); $('#file-browser-modal').modal('show'); }
    return { init, open };
})();
FileBrowserManager.init();
```

### Full-screen modal (OpenCode Terminal modal, ~line 2504)
```html
<div id="file-browser-modal" class="modal fade" tabindex="-1"
     style="z-index: 1080;" data-backdrop="static" data-keyboard="false">
    <div class="modal-dialog" style="max-width: 95vw; margin: 2vh auto;">
        <div class="modal-content" style="height: 90vh;">
            ...
        </div>
    </div>
</div>
```

### Endpoint blueprint (endpoints/*.py)
```python
file_browser_bp = Blueprint('file_browser', __name__)
# All routes under /file-browser/...
```

### CodeMirror modes already loaded (interface.html lines 44-65)
- **Core**: codemirror 5.65.16 + monokai theme
- **Modes**: python, javascript, css, htmlmixed, xml, markdown, gfm
- **Addons**: closebrackets, matchbrackets, active-line, foldcode, foldgutter, indent-fold, overlay

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [☰] [address bar input                    ] [*] [theme ▾] [Save] [×]   │
├──────────┬───────────────────────────────────────────────────────────────┤
│ File     │ Editor Area (CodeMirror 5)                                   │
│ Tree     │                                                               │
│ Sidebar  │ ┌─ Tab: Code ─┬─ Tab: Preview (MD only) ─┐                   │
│          │ │                                          │                   │
│ (right-  │ │   (syntax highlighted code)              │                   │
│  click   │ │                                          │                   │
│  menu)   │ └──────────────────────────────────────────┘                   │
└──────────┴───────────────────────────────────────────────────────────────┘
```

### Component Breakdown

1. **Backend** (`endpoints/file_browser.py`) — 6 endpoints:
   - `GET /file-browser/tree?path=<relative_dir>` — directory listing (one level)
   - `GET /file-browser/read?path=<relative_file>` — file content + metadata
   - `POST /file-browser/write` — save/create file content
   - `POST /file-browser/mkdir` — create directory
   - `POST /file-browser/rename` — rename file/folder
   - `POST /file-browser/delete` — delete file/folder

2. **Frontend Manager** (`interface/file-browser-manager.js`) — IIFE module:
   - State: `currentPath`, `originalContent`, `isDirty`, `cmEditor`, `sidebarVisible`, `expandedDirs`
   - Methods: `init()`, `open()`, `loadTree()`, `loadFile()`, `saveFile()`, `discardChanges()`
   - CRUD: `createFile()`, `createFolder()`, `renameItem()`, `deleteItem()`
   - Context menu, keyboard shortcuts, theme picker
   - CodeMirror integration with mode autodetection
   - Markdown preview tab (reuse `marked.js` from `common.js`)

3. **Modal HTML** (in `interface.html`) — full-screen modal with sidebar + editor layout

4. **Button + Handler** — button in Actions section, handler wired in the manager's `init()`

5. **CSS** — inline `<style>` in modal section of `interface.html` or in `interface/style.css`

## Tasks

### Task 1: Backend — `endpoints/file_browser.py`
**Priority**: High
**Estimated effort**: Small-Medium
**Files**: `endpoints/file_browser.py` (new), `endpoints/__init__.py` (edit)

Create the Flask blueprint with 6 endpoints. All endpoints use `@login_required`.

**Security helper** (shared across all endpoints):
```python
import os

SERVER_ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _safe_resolve(relative_path: str) -> str | None:
    """Resolve a relative path to an absolute path, ensuring it stays within SERVER_ROOT."""
    resolved = os.path.realpath(os.path.join(SERVER_ROOT, relative_path))
    if not resolved.startswith(SERVER_ROOT + os.sep) and resolved != SERVER_ROOT:
        return None
    return resolved
```

#### 1a. `GET /file-browser/tree`
- Query param: `path` (relative to server root, default: `.`)
- Returns JSON: `{ "path": ".", "entries": [ { "name": "foo", "type": "dir" }, { "name": "bar.py", "type": "file", "size": 1234 } ] }`
- Sort: directories first, then files, both alphabetical (case-insensitive)
- Show ALL files including hidden (`.git`, `.env`, `__pycache__`, etc.)
- Path traversal prevention via `_safe_resolve()`

#### 1b. `GET /file-browser/read`
- Query param: `path` (relative to server root)
- Returns JSON: `{ "path": "foo/bar.py", "content": "...", "size": 1234, "extension": ".py", "is_binary": false }`
- **Binary detection**: Check first 8KB for null bytes; if binary, return `{ "is_binary": true, "content": null }`
- **Size guard**: If file > 2MB, return `{ "too_large": true, "size": N, "content": null }`
- Accept `?force=true` to skip size guard
- Path traversal prevention

#### 1c. `POST /file-browser/write`
- Body: `{ "path": "foo/bar.py", "content": "..." }`
- Writes content to file, returns `{ "ok": true, "size": N }`
- Create parent directories if they don't exist (`os.makedirs(parent, exist_ok=True)`)
- Works for both new files and existing files
- Path traversal prevention

#### 1d. `POST /file-browser/mkdir`
- Body: `{ "path": "foo/new_folder" }`
- Creates directory (with `exist_ok=True`), returns `{ "ok": true }`
- Path traversal prevention

#### 1e. `POST /file-browser/rename`
- Body: `{ "old_path": "foo/bar.py", "new_path": "foo/baz.py" }`
- Uses `os.rename()`, returns `{ "ok": true }`
- Both old and new paths must resolve within SERVER_ROOT
- Path traversal prevention on both paths

#### 1f. `POST /file-browser/delete`
- Body: `{ "path": "foo/bar.py" }`
- For files: `os.remove()`
- For directories: `shutil.rmtree()` (⚠️ dangerous — endpoint should confirm via `"recursive": true` in body for non-empty dirs)
- Returns `{ "ok": true }`
- Path traversal prevention
- **Safety**: Refuse to delete SERVER_ROOT itself

#### 1g. Register blueprint
- Add `from .file_browser import file_browser_bp` and `app.register_blueprint(file_browser_bp)` to `endpoints/__init__.py`

### Task 2: Frontend Modal HTML — `interface.html`
**Priority**: High
**Estimated effort**: Small
**Files**: `interface.html` (edit)

#### 2a. Add the "File Browser" button to Actions section (~line 2198, before the closing `</div>` of the row)
```html
<div class="col">
    <button class="btn btn-primary btn-sm rounded-pill w-100" id="settings-file-browser-modal-open-button">
        <i class="bi bi-folder2-open"></i> File Browser
    </button>
</div>
```

#### 2b. Add the full-screen modal (after the OpenCode Terminal modal, ~line 2531)

Layout structure:
```
modal (z-index: 1080, data-backdrop="static")
  modal-header (compact, py-1):
    [☰ sidebar toggle btn] [address bar input (flex:1)] [unsaved * indicator]
    [theme picker dropdown] [Discard btn] [Save btn] [× close btn]
  modal-body (flex row, height: calc(100% - header height), padding: 0):
    left-panel #file-browser-sidebar (width: 250px, collapsible):
      small toolbar row: [Refresh btn]
      div#file-browser-tree (scrollable, overflow-y: auto)
    right-panel #file-browser-editor-wrapper (flex: 1):
      tab-bar (only visible for .md files): [Code] [Preview]
      div#file-browser-editor-container (flex: 1, CodeMirror goes here)
      div#file-browser-preview-container (hidden by default, for MD preview, overflow-y: auto)
```

Key HTML details:
- Modal id: `file-browser-modal`
- Style: `z-index: 1080; data-backdrop="static"` (same as terminal modal)
- Modal dialog: `max-width: 95vw; margin: 2vh auto;`
- Modal content: `height: 90vh; display: flex; flex-direction: column;`
- Header: compact `py-1`, flex layout with address bar taking remaining space
- Sidebar default width: `250px`, transitions to `0px` when collapsed
- Editor container: `flex: 1; overflow: hidden;`
- Preview container: same position as editor, toggled visibility for markdown

#### 2c. Context menu HTML
A hidden positioned `<div>` for the right-click context menu on tree items:
```html
<div id="file-browser-context-menu" style="display:none; position:fixed; z-index:9999;">
    <div class="dropdown-menu show">
        <a class="dropdown-item" href="#" data-action="new-file"><i class="bi bi-file-plus"></i> New File</a>
        <a class="dropdown-item" href="#" data-action="new-folder"><i class="bi bi-folder-plus"></i> New Folder</a>
        <div class="dropdown-divider"></div>
        <a class="dropdown-item" href="#" data-action="rename"><i class="bi bi-pencil"></i> Rename</a>
        <a class="dropdown-item text-danger" href="#" data-action="delete"><i class="bi bi-trash"></i> Delete</a>
    </div>
</div>
```

### Task 3: Frontend Manager — `interface/file-browser-manager.js`
**Priority**: High
**Estimated effort**: Large (this is the bulk of the work)
**Files**: `interface/file-browser-manager.js` (new)

IIFE module pattern matching existing managers.

#### 3a. State
```javascript
var state = {
    currentPath: null,        // Currently open file path (relative)
    currentDir: '.',          // Currently viewed directory in address bar
    originalContent: '',      // Content as loaded from server (for discard)
    isDirty: false,           // Has unsaved changes
    cmEditor: null,           // CodeMirror 5 instance
    sidebarVisible: true,     // Sidebar collapse state
    expandedDirs: {},         // Map of expanded directory paths → true (preserves tree state)
    isMarkdown: false,        // Current file is .md
    activeTab: 'code',        // 'code' or 'preview' (for markdown)
    contextTarget: null,      // Tree item that was right-clicked (for context menu)
    currentTheme: 'monokai'   // Current CodeMirror theme
};
```

#### 3b. init()
- Bind button click: `$('#settings-file-browser-modal-open-button').on('click', ...)` — close settings modal first, then call `open()`
- Bind save/discard buttons
- Bind sidebar toggle button
- Bind address bar Enter key + form submission
- Bind `shown.bs.modal` → `cmEditor.refresh()`
- Bind keyboard shortcuts: `Ctrl+S` / `Cmd+S` → save, `Escape` → close (with dirty check)
- Bind tree click handlers (delegated on `#file-browser-tree`)
- Bind context menu (right-click on tree items)
- Bind theme picker change
- Bind markdown tab switching
- Do NOT create CodeMirror instance in init — create lazily on first `open()` or `loadFile()` to avoid issues with hidden container

#### 3c. open()
- Close chat-settings-modal: `$('#chat-settings-modal').modal('hide')`
- Small delay (e.g. 200ms) then show file browser: `$('#file-browser-modal').modal('show')`
- On `shown.bs.modal`: create CodeMirror if not yet created, then `cmEditor.refresh()`
- Load root tree if `expandedDirs` is empty (first open)
- If `currentPath` is set (reopening), re-highlight the file in the tree

#### 3d. loadTree(dirPath)
- `GET /file-browser/tree?path={dirPath}`
- Render entries as nested `<ul>/<li>` under the appropriate parent in `#file-browser-tree`
- Directories: click to expand/collapse (lazy load children), store in `expandedDirs`
- Files: click to call `loadFile(path)`
- Icons:
  - `bi bi-folder` / `bi bi-folder2-open` for collapsed/expanded dirs
  - `bi bi-file-earmark-code` for code files (.py, .js, .html, .css, etc.)
  - `bi bi-file-earmark-text` for text/markdown
  - `bi bi-file-earmark` for other files
- Highlight currently open file with `.active` class
- Right-click on any item → show context menu
- On re-expand after collapse: use cached children or re-fetch

#### 3e. loadFile(filePath)
- Check `isDirty` — if true, confirm before navigating ("You have unsaved changes. Discard?")
- `GET /file-browser/read?path={filePath}`
- Handle binary (`is_binary: true`) → show centered "Binary file — cannot edit" message in editor area, hide CodeMirror
- Handle too-large (`too_large: true`) → show warning with file size + "Load Anyway" button
- Normal: set CodeMirror content and mode
- Update address bar with file path
- Update `currentDir` to parent directory of the file
- Set `originalContent`, `isDirty = false`, update dirty indicator
- Show/hide markdown preview tab bar based on extension
- Reset `activeTab` to 'code'

**CodeMirror mode mapping** (extension → CM mode, only using pre-loaded modes):
```javascript
var MODE_MAP = {
    '.py': 'python',
    '.pyw': 'python',
    '.js': 'javascript',
    '.mjs': 'javascript',
    '.jsx': 'javascript',   // no jsx mode loaded, javascript is close enough
    '.ts': { name: 'javascript', typescript: true },
    '.tsx': { name: 'javascript', typescript: true },
    '.json': { name: 'javascript', json: true },
    '.html': 'htmlmixed',
    '.htm': 'htmlmixed',
    '.css': 'css',
    '.xml': 'xml',
    '.svg': 'xml',
    '.md': 'gfm',           // GFM mode is richer than plain markdown mode
    '.markdown': 'gfm'
};
// Anything not in the map → null (CodeMirror plain text / no mode)
```

#### 3f. saveFile()
- If not `isDirty`, no-op (button visually disabled)
- `POST /file-browser/write` with `{ path: state.currentPath, content: cmEditor.getValue() }`
- On success: `showToast('Saved: ' + filename, 'success')`, update `originalContent`, set `isDirty = false`
- On error: `showToast('Save failed: ' + err, 'error')`
- Also triggered by Ctrl+S / Cmd+S (prevent default browser save dialog)

#### 3g. discardChanges()
- If not `isDirty`, no-op
- Confirm: "Discard unsaved changes?"
- Set CodeMirror content to `originalContent`, set `isDirty = false`

#### 3h. Sidebar toggle
- Toggle `state.sidebarVisible`
- Add/remove `.collapsed` class on `#file-browser-sidebar` (CSS transition handles animation)
- Update toggle button icon (`bi-layout-sidebar` ↔ `bi-layout-sidebar-inset`)
- After transition (200ms): call `cmEditor.refresh()` (CodeMirror needs to recalculate layout)

#### 3i. Markdown preview
- Tab switching between Code and Preview (only visible when `.md`/`.markdown` file open)
- Preview: render markdown content to HTML using `marked.marked(content, { renderer: markdownParser })` from `common.js`
- Apply `hljs.highlightElement()` to code blocks in preview
- Toggle visibility of `#file-browser-editor-container` and `#file-browser-preview-container`

#### 3j. Unsaved changes guard
- On file navigation (tree click or address bar): check `isDirty`, `confirm()` if true
- On modal close attempt (× button or Escape): check `isDirty`, `confirm()` if true, prevent close if user cancels
- Visual indicator: show `*` before filename in address bar area when dirty
- Save button visual state: disabled/dim when not dirty, primary/highlighted when dirty

#### 3k. Context menu (CRUD)
- Right-click on tree item → show `#file-browser-context-menu` at mouse position
- Click outside or Escape → hide menu
- **New File**: Prompt for filename → `POST /file-browser/write` with empty content → refresh tree → open file
- **New Folder**: Prompt for folder name → `POST /file-browser/mkdir` → refresh tree
- **Rename**: Prompt with current name pre-filled → `POST /file-browser/rename` → refresh tree → update address bar if renamed file was open
- **Delete**: Confirm ("Delete {name}?", extra warning if non-empty dir "This will delete all contents") → `POST /file-browser/delete` with `{ path, recursive: true }` for dirs → refresh tree → clear editor if deleted file was open

#### 3l. Theme picker
- Small `<select>` dropdown in the modal header
- Options: monokai (default), dracula, material, eclipse, neat, default (light)
- Only include themes whose CSS is already loaded or add 2-3 popular theme CSS CDN links in `interface.html`
- On change: `cmEditor.setOption('theme', newTheme)`, save to `state.currentTheme`
- Note: monokai theme CSS is already loaded. For others, we need to add their CSS CDN links. If we want to keep it minimal, we can offer just monokai + default (light) which requires no extra CSS.

#### 3m. Address bar navigation
- On Enter key in address bar input:
  - Trim the value
  - `GET /file-browser/read?path={value}` — if success → load as file
  - If 404 or error → try `GET /file-browser/tree?path={value}` — if success → navigate tree to that directory
  - If both fail → `showToast('Path not found', 'error')`
- On clicking a directory in tree → update address bar to show that dir path

### Task 4: Button Handler Wiring
**Priority**: High
**Estimated effort**: Tiny
**Files**: `interface/chat.js` (edit)

Add click handler near other modal-open handlers (~line 332-339):
```javascript
$('#settings-file-browser-modal-open-button').click(function () {
    if (typeof FileBrowserManager !== 'undefined') {
        FileBrowserManager.open();
    } else {
        showToast('File browser not loaded', 'error');
    }
});
```

Note: `FileBrowserManager.open()` itself handles closing settings modal first, so this handler is simple delegation.

### Task 5: Script & Asset Registration
**Priority**: High
**Estimated effort**: Tiny
**Files**: `interface/interface.html` (edit), `interface/service-worker.js` (edit)

#### 5a. Add `<script>` tag in interface.html (near line 3135 where other scripts are loaded)
```html
<script src="interface/file-browser-manager.js"></script>
```

#### 5b. Add to service-worker.js cache list (near line 55)
```javascript
"/interface/interface/file-browser-manager.js",
```

#### 5c. CodeMirror theme CSS (if offering themes beyond monokai)
If we add a theme picker with more than monokai + default, add CSS CDN links:
```html
<!-- Additional CodeMirror themes for file browser -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/dracula.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/material.min.css">
```
Keep it to 2-3 extra themes max. Or start with monokai + default only (zero extra CSS).

### Task 6: CSS Styling
**Priority**: Medium
**Estimated effort**: Small
**Files**: `interface/style.css` (edit) or inline `<style>` block near the modal in `interface.html`

Key styles needed:

```css
/* File Browser Modal */
#file-browser-modal .modal-body {
    display: flex;
    padding: 0;
    overflow: hidden;
}
#file-browser-modal .modal-content {
    display: flex;
    flex-direction: column;
}
#file-browser-modal .modal-header {
    padding: 0.35rem 0.75rem;
    display: flex;
    align-items: center;
    gap: 8px;
}

/* Address bar */
#file-browser-address-bar {
    flex: 1;
    font-family: monospace;
    font-size: 0.85rem;
    padding: 2px 8px;
}

/* Sidebar */
#file-browser-sidebar {
    width: 250px;
    min-width: 0;
    border-right: 1px solid #dee2e6;
    overflow-y: auto;
    overflow-x: hidden;
    transition: width 0.2s ease;
    background: #f8f9fa;
    flex-shrink: 0;
}
#file-browser-sidebar.collapsed {
    width: 0;
    border-right: none;
}

/* File tree */
#file-browser-tree ul {
    list-style: none;
    padding-left: 16px;
    margin: 0;
}
#file-browser-tree > ul {
    padding-left: 4px;
}
#file-browser-tree li {
    cursor: pointer;
    padding: 2px 6px;
    white-space: nowrap;
    font-size: 0.82rem;
    border-radius: 3px;
    user-select: none;
}
#file-browser-tree li:hover {
    background: #e9ecef;
}
#file-browser-tree li.active {
    background: #007bff;
    color: #fff;
}
#file-browser-tree li .tree-icon {
    width: 16px;
    display: inline-block;
    text-align: center;
    margin-right: 4px;
}

/* Editor area */
#file-browser-editor-wrapper {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 0;
}
#file-browser-editor-container {
    flex: 1;
    overflow: hidden;
}
#file-browser-editor-container .CodeMirror {
    height: 100%;
    font-size: 13px;
}
#file-browser-preview-container {
    flex: 1;
    overflow-y: auto;
    padding: 16px 24px;
    display: none;
    background: #fff;
}

/* Markdown tab bar */
#file-browser-tab-bar {
    display: none;
    padding: 2px 8px;
    background: #f1f3f5;
    border-bottom: 1px solid #dee2e6;
}
#file-browser-tab-bar .btn {
    font-size: 0.78rem;
    padding: 1px 10px;
}
#file-browser-tab-bar .btn.active {
    font-weight: 600;
}

/* Dirty indicator */
.file-browser-dirty-indicator {
    color: #ffc107;
    font-weight: bold;
    margin-left: 4px;
    display: none;
}
.file-browser-dirty-indicator.visible {
    display: inline;
}

/* Context menu */
#file-browser-context-menu {
    position: fixed;
    z-index: 9999;
}
#file-browser-context-menu .dropdown-item {
    font-size: 0.82rem;
    padding: 4px 12px;
}

/* Theme picker */
#file-browser-theme-select {
    font-size: 0.75rem;
    padding: 1px 4px;
    width: auto;
    max-width: 120px;
}
```

### Task 7: Documentation
**Priority**: Low
**Estimated effort**: Tiny
**Files**: `documentation/features/file_browser/README.md` (new), `documentation/README.md` (edit)

Document:
- Feature overview
- API endpoints (6 endpoints with request/response format)
- UI components and interactions
- Keyboard shortcuts
- Files created/modified
- Security considerations (path traversal prevention, login required)

---

## Implementation Order

1. **Task 1** (Backend — 6 endpoints) — no frontend dependency
2. **Task 2** (Modal HTML + button) — can parallelize with Task 1
3. **Task 3** (JS Manager — core: init, tree, loadFile, save, discard, sidebar, address bar) — depends on 1 & 2
4. **Task 3 continued** (CRUD: context menu, new/rename/delete) — after core works
5. **Task 3 continued** (Polish: theme picker, markdown preview, keyboard shortcuts) — after CRUD
6. **Task 4** (Button handler in chat.js) — tiny, do with Task 3
7. **Task 5** (Script + asset registration) — tiny, do with Task 3
8. **Task 6** (CSS) — do alongside Task 2/3
9. **Task 7** (Docs) — do last

**Parallelization**: Tasks 1 and 2 are independent — do them simultaneously.
**Incremental approach for Task 3**: Build core editor first (open file, edit, save), then add CRUD, then polish (themes, markdown preview, keyboard shortcuts). This way each increment is testable.

## Risks & Alternatives

1. **Large file handling**: Opening a 10MB log file will freeze the browser. Mitigation: Server-side size guard (2MB default) + frontend warning + "Load Anyway" button.
2. **Binary files**: User clicks an image or .pyc file. Mitigation: Binary detection on server (null byte check in first 8KB), "cannot edit" message on frontend.
3. **Path traversal attacks**: User types `../../etc/passwd` in address bar. Mitigation: `os.path.realpath()` + `startswith(SERVER_ROOT)` check on every endpoint. Also `@login_required`.
4. **Recursive delete of important dirs**: User accidentally deletes a critical folder. Mitigation: Extra confirmation for non-empty directory delete. Cannot delete SERVER_ROOT itself.
5. **Concurrent editing**: Two tabs editing same file. Mitigation: Not handled in v1 — last write wins. Could add ETag-based optimistic locking later.
6. **Modal stacking z-index**: Avoided by closing chat-settings-modal before opening file browser.
7. **CodeMirror refresh after modal show**: CM doesn't render properly in hidden containers. Mitigation: Call `cm.refresh()` on `shown.bs.modal` event (standard pattern, already used in markdown-editor.js).
8. **Missing CodeMirror modes**: Many file types (yaml, shell, sql, rust, go, etc.) won't have syntax highlighting since we only use pre-loaded modes. They'll show as plain text. This is acceptable for v1 — can add more modes via CDN later if needed.
9. **Theme CSS not loaded**: If we offer themes beyond monokai + default, we need to add their CSS CDN links. Start with monokai + default to avoid extra assets, expand later.
