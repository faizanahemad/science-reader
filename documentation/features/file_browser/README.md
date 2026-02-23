# File Browser & Editor

## Overview

Full-screen modal file browser and code editor accessible from the chat-settings-modal **Actions** tab. Provides VS Code-like file tree navigation, syntax-highlighted editing via CodeMirror 5, markdown preview with live toggle, and full CRUD operations. All file access is sandboxed to the server's working directory.

---

## Features

- VS Code-like collapsible file tree sidebar with lazy per-directory loading
- CodeMirror 5 editor with syntax highlighting for Python, JavaScript, TypeScript, CSS, HTML, XML, Markdown (GFM), JSON
- Markdown preview tab using the project's `renderMarkdownToHtml` / `marked.js` renderer with `hljs` code block highlighting
- Address bar for direct path navigation with HTML5 `<datalist>` autocomplete populated from the loaded tree
- Full CRUD: create files/folders, rename, delete (via right-click context menu or background context-click)
- Unsaved-changes guard: dirty indicator dot, Save / Discard buttons, confirmation dialog on close/navigate
- Keyboard shortcuts: `Ctrl+S` / `Cmd+S` save, `Escape` close, `Tab` indent
- Theme picker (Monokai default / Default light)
- Binary file detection (null-byte scan in first 8 KB) — shows informational message instead of loading garbled content
- 2 MB file size guard — shows warning with "Load Anyway" override button
- State persistence across modal open/close (expanded dirs, current file, scroll position — all in-memory)
- Sidebar collapse toggle (hide/show the 250 px tree panel to maximize editor width)
- Sidebar New File / New Folder buttons in the tree header for quick creation without right-clicking
- Inline naming modal for file/folder creation, replacing the browser's native `prompt()` with a target directory hint

---

## UI Details

### Entry Point

Settings modal → **Actions** tab → **File Browser** button (`#settings-file-browser-modal-open-button`).

A fallback click handler is also wired inline in `interface.html` so the button works even if `FileBrowserManager` fails to init silently.

### Modal Layout

- Full-screen overlay: `position: fixed; inset: 0; z-index: 100000 !important`
- The modal is **not** a Bootstrap `.modal` — it is a plain `<div>` with Bootstrap layout classes inside, opened/closed with manual DOM manipulation to avoid Bootstrap JS conflicts when another modal (settings) is already open.
- Inner layout: flex row → collapsible sidebar (250 px) + editor/viewer column
- Header bar: sidebar-toggle, address bar (with datalist), refresh, theme picker, save, discard, close
- Editor area shows one of three views at a time: editor, preview, empty-state

### Address Bar Autocomplete

The address bar (`#file-browser-address-bar`) is an `<input list="file-browser-path-suggestions">` element backed by a `<datalist id="file-browser-path-suggestions">`. After every tree load, `_refreshPathSuggestions()` scans all rendered `<li>` elements in the tree and repopulates the datalist with their `data-path` values. When the user selects a suggestion from the native dropdown (fires the `change` event), `_navigateAddressBar(value)` is called immediately — no Enter keypress required.

### Markdown Tab Bar

For `.md` / `.markdown` files only, a **Code / Preview** tab bar appears above the editor. Clicking **Preview** calls `_renderPreview()` and calls `_showView('preview')`. Clicking **Code** calls `_showView('editor')`. Tab state is tracked in `state.activeTab`.

### Context Menu

Right-click on any tree `<li>` populates `state.contextTarget` and shows `#file-browser-context-menu` at cursor coordinates. Right-clicking the tree background (not on an item) sets `state.contextTarget` to the current directory for "create here" operations. Menu items: **New File**, **New Folder**, **Rename**, **Delete**. The New File and New Folder actions use the naming modal (see below) instead of the browser's native `prompt()`.

### Sidebar Header Buttons

The sidebar header row (next to the Refresh button) contains two quick-action buttons:

- **New File** (`#file-browser-new-file-btn`, icon `bi-file-earmark-plus`)
- **New Folder** (`#file-browser-new-folder-btn`, icon `bi-folder-plus`)

Both use the same styling as the Refresh button: `btn btn-sm btn-link text-muted p-0 mr-1`. Clicking either opens the naming modal (see below) with the target directory determined by `_getTargetDir()`.

### Naming Modal

The naming modal (`#file-browser-name-modal`) replaces the browser's native `prompt()` for file and folder creation. It provides a cleaner UX with a visible target directory hint so the user knows where the new item will be created.

Layout and behavior:

- Fixed overlay with `z-index: 100001` (one above the file browser modal) and a semi-transparent backdrop
- Title text changes dynamically: "New File" or "New Folder" depending on the action
- Input field for the file or folder name
- Directory hint below the input showing the resolved target directory
- Cancel and Create buttons in the footer
- Enter key confirms, Escape key cancels, clicking the backdrop cancels

Target directory logic uses `_getTargetDir()`, which checks in order: `state.contextTarget` (from right-click), parent directory of `state.currentPath` (currently open file), then `state.currentDir` as fallback.

---

## API Endpoints

All endpoints require `@login_required` and are registered under the `file_browser_bp` Flask Blueprint.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/file-browser/tree?path=.` | List directory entries (dirs first, alphabetical) |
| GET | `/file-browser/read?path=...` | Read file content (`force=true` bypasses 2 MB guard) |
| POST | `/file-browser/write` | Write file content `{"path": "...", "content": "..."}` |
| POST | `/file-browser/mkdir` | Create directory `{"path": "..."}` |
| POST | `/file-browser/rename` | Rename or move `{"old_path": "...", "new_path": "..."}` |
| POST | `/file-browser/delete` | Delete file or directory `{"path": "...", "recursive": true}` |

### Response Shape

All endpoints return JSON:

```json
{ "status": "success" }
// or
{ "status": "error", "error": "human-readable message" }
```

`/file-browser/read` additionally returns:

```json
{
  "status": "success",
  "content": "file contents as string",
  "size": 1234,
  "is_binary": false,
  "too_large": false
}
```

`/file-browser/tree` returns:

```json
{
  "status": "success",
  "entries": [
    { "name": "mydir", "type": "dir" },
    { "name": "script.py", "type": "file" }
  ]
}
```

### Security

- All paths are resolved with `os.path.realpath()` and checked against `SERVER_ROOT` (`os.getcwd()` at startup).
- Any path that escapes the server root returns a 403 error.
- Deleting `SERVER_ROOT` itself is refused.
- Binary detection: first 8 KB of file is checked for null bytes; binary files are not loaded into the editor.
- File size guard: files over 2 MB are rejected unless `force=true` is passed.

---

## Modal Display Architecture

### Why Bootstrap's `.modal('show')` is NOT used

Bootstrap 4's modal JS (`$.fn.modal`) does not support stacking — if a modal is already open (the chat settings modal), calling `.modal('show')` on a second modal causes z-index conflicts, duplicate backdrop injection, and broken `modal-open` body class management.

**Solution**: The file browser modal is bypassed from Bootstrap's JS entirely. It is opened and closed with raw DOM manipulation:

```javascript
// Open
modal.style.display = 'block';
modal.classList.add('show');
modal.setAttribute('aria-hidden', 'false');
document.body.classList.add('modal-open');

// Close
modal.classList.remove('show');
modal.style.display = 'none';
modal.setAttribute('aria-hidden', 'true');
if ($('.modal.show').length === 0) {
    document.body.classList.remove('modal-open');
}
```

### Why Bootstrap utility class `.d-flex` is not used on view containers

Bootstrap utility classes use `!important`, so `display: flex !important` on `#file-browser-empty-state` (from the `d-flex` class) would override jQuery's `.hide()` which sets `display: none` without `!important`. All three view containers (`#file-browser-editor-container`, `#file-browser-preview-container`, `#file-browser-empty-state`) are shown/hidden via vanilla `element.style.display` to avoid this conflict.

### No backdrop

The modal is full-screen (`position: fixed; inset: 0`), so a backdrop is unnecessary. No backdrop element is created. On close, `_closeModal()` actively sweeps any orphaned `.modal-backdrop` elements (from Bootstrap handling other modals) and also removes any `#file-browser-backdrop` element that old cached JS versions may have injected.

### data-backdrop attribute

The modal `<div>` has no `data-backdrop` attribute. Earlier versions had `data-backdrop="false"` which Bootstrap 4 still interprets to inject a backdrop on `.modal('show')`. This attribute was removed.

### CodeMirror initialization delay

CodeMirror does not render correctly inside hidden containers. `_ensureEditor()` is called inside a `setTimeout(..., 50)` after the modal becomes visible, not before. On subsequent opens, the existing editor instance is refreshed via `state.cmEditor.refresh()`.

---

## Implementation Details

### JS Module Structure

`file-browser-manager.js` is an **IIFE** (Immediately Invoked Function Expression) that returns a plain object `FileBrowserManager` exposed on `window`. It uses no ES module syntax (`import`/`export`) and no classes — plain `var` declarations and named inner functions, consistent with the project's jQuery + Bootstrap 4.6 legacy style.

```javascript
var FileBrowserManager = (function () {
    'use strict';
    // ... private state and functions ...
    return { init, open, loadFile, saveFile, discardChanges };
})();
```

All event handlers are bound in `FileBrowserManager.init()`, which is called once on DOM ready. The module's internal state is held in a single `state` object (see State Object section).

---

### File Tree Rendering

The left-side file/folder tree is a **fully custom implementation** — plain jQuery DOM manipulation with `<ul>/<li>` elements. No third-party tree library is used for the tree.

> **Note:** `jstree 3.3.17` (CDN CSS + JS) is currently loaded in `interface.html` but is **not used by the file browser**. It is used by the Workspaces feature sidebar. The jstree `<link>` and `<script>` tags in the HTML are for Workspaces, not for the File Browser.

#### How the tree is built

`loadTree(dirPath, $parentUl)` is the core rendering function:

1. Calls `GET /file-browser/tree?path=<dirPath>` — server returns `{ entries: [{name, type}] }` sorted dirs-first alphabetically.
2. Builds a `<ul>` and for each entry creates a `<li>` with:
   - `data-path` — relative path from server root
   - `data-type` — `'file'` or `'dir'`
   - `data-name` — just the entry's filename
   - A `<span class="tree-icon"><i class="bi ..."></i></span>` for the Bootstrap Icon
   - A `<span class="tree-name">` with the file/folder name as text
3. If a directory was previously expanded (`state.expandedDirs[path]` is truthy), `loadTree()` recurses immediately to re-populate its children.
4. Attaches the built `<ul>` into `#file-browser-tree` (root) or into the parent `<li>` node (subdirectory).
5. Calls `_refreshPathSuggestions()` to repopulate the address bar `<datalist>` with all visible paths.

#### Expand / collapse

`_toggleDir($li)` handles directory clicks:

- **Expand**: Adds path to `state.expandedDirs`, updates icon to `bi-folder2-open`, appends a placeholder `<ul>`, calls `loadTree(dirPath, $li.parent())` to fill it.
- **Collapse**: Removes path from `state.expandedDirs`, removes the child `<ul>` from the DOM, resets icon to `bi-folder-fill`.

Expand state is persisted in `state.expandedDirs` (in-memory only) so the tree re-opens to the same expansion state after modal close/reopen.

#### File icons

Icons use **Bootstrap Icons** (`bi-*` classes). The `ICON_MAP` constant maps extensions to specific icon classes:

| Extension(s) | Icon class |
|---|---|
| `.py` | `bi-filetype-py` |
| `.js` | `bi-filetype-js` |
| `.ts`, `.tsx` | `bi-filetype-tsx` |
| `.jsx` | `bi-filetype-jsx` |
| `.json` | `bi-filetype-json` |
| `.html`, `.htm` | `bi-filetype-html` |
| `.css` | `bi-filetype-css` |
| `.xml` | `bi-filetype-xml` |
| `.md` | `bi-filetype-md` |
| `.svg` | `bi-filetype-svg` |
| `.yml`, `.yaml` | `bi-filetype-yml` |
| `.sh` | `bi-terminal` |
| `.txt` | `bi-file-earmark-text` |
| others | `bi-file-earmark` |
| directory (collapsed) | `bi-folder-fill text-warning` |
| directory (expanded) | `bi-folder2-open text-warning` |

---

### CodeMirror Integration

The editor uses **CodeMirror 5.65.16**, loaded in `interface.html` with all required language modes pre-loaded.

`_ensureEditor()` creates the instance lazily on first open (inside a 50 ms `setTimeout` after the modal becomes visible, to avoid the blank-render bug with hidden containers). On subsequent opens, `state.cmEditor.refresh()` is called instead.

Editor config: line numbers, fold gutter, active line highlight, bracket matching, 4-space indent, `Tab` inserts spaces. Theme defaults to `monokai`; switchable to `default` (light) via the theme picker.

Dirty tracking: the `change` event on CodeMirror compares `cmEditor.getValue()` to `state.originalContent` (content as loaded from server). If different, `state.isDirty = true` and the dirty indicator dot appears.

---

### Backend Path Security

`SERVER_ROOT` is set to `os.getcwd()` at module import time (server startup). Every incoming path is:
1. Joined with `SERVER_ROOT` using `os.path.join()`
2. Resolved to a real absolute path with `os.path.realpath()` (resolves symlinks, `..` traversal)
3. Checked that it starts with `SERVER_ROOT + os.sep` — any path escaping the working directory returns HTTP 403

Additionally, `delete` refuses to delete `SERVER_ROOT` itself.

---

## AI Edit (Cmd+K)

LLM-assisted inline editing, similar to Cursor's Cmd+K. When a file is open in the editor:

 **Button**: "AI Edit" button in the top bar (between theme selector and discard). Icon: magic wand.
 **Shortcut**: Cmd+K / Ctrl+K opens the AI Edit overlay.
 **Selection edit**: Select text, then Cmd+K. Only the selected lines are sent to the LLM for editing.
 **Whole-file edit**: No selection + Cmd+K edits the entire file (limited to 500 lines).

### Instruction Modal
 Textarea for natural language edit instructions
 "Include conversation context" checkbox (greyed out if no conversation open)
 "Deep context extraction" nested checkbox (adds 2-5s latency, uses `retrieve_prior_context_llm_based`)
 Ctrl+Enter / Cmd+Enter to submit

### Diff Preview
 Unified diff with green (additions) / red (deletions) coloring
 Accept: splices edit into CodeMirror (`replaceRange` for selection, `setValue` for whole file)
 Reject: discards the proposed edit
 Edit Instruction: returns to instruction modal with previous text preserved

### API
 `POST /file-browser/ai-edit` — accepts `path`, `instruction`, `selection` (optional), `conversation_id`, `include_context`, `deep_context`
 Returns `proposed` (replacement text), `diff_text` (unified diff), `base_hash`, line info

### Key Functions
 `_showAiEditModal()` — captures selection, shows instruction overlay
 `_hideAiEditModal()` — closes instruction overlay
 `_generateAiEdit()` — POSTs to `/file-browser/ai-edit`, shows diff on success
 `_acceptAiEdit()` — applies proposed edit to editor
 `_rejectAiEdit()` — discards proposed edit
 `_renderDiffPreview()` — renders unified diff as colored HTML

---
## Implementation Notes

### Files Created

- `endpoints/file_browser.py` — Flask Blueprint (`file_browser_bp`) with 6 endpoints, path traversal prevention, binary detection, 2 MB size guard
- `interface/file-browser-manager.js` — IIFE module (`FileBrowserManager`) with full tree rendering, CodeMirror integration, address bar autocomplete, CRUD operations, keyboard shortcuts, modal lifecycle

### Files Modified

- `endpoints/__init__.py` — Registered `file_browser_bp` blueprint
- `interface/interface.html` — Added File Browser button in Actions section; full-screen modal HTML (no Bootstrap modal classes/attributes); context menu HTML; naming modal (`#file-browser-name-modal`); sidebar New File (`#file-browser-new-file-btn`) and New Folder (`#file-browser-new-folder-btn`) buttons; `<datalist id="file-browser-path-suggestions">`; `<script>` tag with cache-buster version; fallback click handler
- `interface/style.css` — Added file browser CSS: sidebar layout, tree item styling, editor/preview containers, tab bar, context menu, dirty indicator, empty state
- `interface/service-worker.js` — Added `file-browser-manager.js` to precache list; cache version bumped on each JS update

### Key Public API (file-browser-manager.js)

| Function | Description |
|----------|-------------|
| `FileBrowserManager.init()` | Binds all event handlers; called once on DOM ready |
| `FileBrowserManager.open()` | Opens the file browser modal |
| `FileBrowserManager.loadFile(path, force)` | Loads a file into CodeMirror (with binary/size guards) |
| `FileBrowserManager.saveFile()` | Writes current editor content to server |
| `FileBrowserManager.discardChanges()` | Reverts editor to last saved content |

### Key Internal Functions

| Function | Description |
|----------|-------------|
| `loadTree(dirPath, $parentUl)` | Fetches and renders a directory listing in the sidebar |
| `_toggleDir($li)` | Expands/collapses a tree directory node |
| `_showView(view, messageHtml)` | Switches between editor / preview / empty-state views |
| `_showFileBrowserModal()` | Opens the modal with manual DOM manipulation; kills any stale backdrop |
| `_closeModal()` | Closes modal, sweeps orphan backdrops, conditionally removes `modal-open` |
| `_refreshPathSuggestions()` | Repopulates the `<datalist>` with current tree paths for autocomplete |
| `_renderPreview()` | Renders current editor content as markdown HTML into preview container |
| `_ensureEditor()` | Lazily creates the CodeMirror instance on first open |
| `_confirmIfDirty()` | Shows a confirm dialog if there are unsaved changes; returns boolean |
| `_createFile()`, `_createFolder()` | CRUD via naming modal + API calls |
| `_renameItem()`, `_deleteItem()` | CRUD prompts + API calls |
| `_getTargetDir()` | Determines target directory for new file/folder (contextTarget, then currentPath parent, then currentDir) |
| `_showNameModal(type, callback)` | Shows naming modal for file or folder creation |
| `_hideNameModal()` | Hides the naming modal and clears state |
| `_nameModalConfirm()` | Validates input and fires callback from naming modal |

### State Object

```javascript
var state = {
    currentPath: null,       // Currently open file (relative to server root)
    currentDir: '.',         // Currently viewed directory
    originalContent: '',     // File content as loaded (for dirty comparison and discard)
    isDirty: false,          // Unsaved changes flag
    cmEditor: null,          // CodeMirror 5 instance (created lazily)
    sidebarVisible: true,    // Sidebar collapse state
    expandedDirs: {},        // Map of expanded directory paths → true
    isMarkdown: false,       // Whether current file is .md/.markdown
    activeTab: 'code',       // 'code' or 'preview'
    contextTarget: null,     // Tree item targeted by context menu
    currentTheme: 'monokai', // Active CodeMirror theme
    initialized: false,
    pathSuggestions: [],     // Ordered list of tree paths for autocomplete
    pathSuggestionMap: {}    // Set-like map for O(1) lookup on address bar change event
};
```

### CodeMirror Mode Mapping

| Extension(s) | Mode |
|---|---|
| `.py`, `.pyw` | `python` |
| `.js`, `.mjs`, `.jsx` | `javascript` |
| `.ts`, `.tsx` | `{ name: 'javascript', typescript: true }` |
| `.json` | `{ name: 'javascript', json: true }` |
| `.html`, `.htm` | `htmlmixed` |
| `.css` | `css` |
| `.xml`, `.svg` | `xml` |
| `.md`, `.markdown` | `gfm` |
| others | `null` (plain text) |

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+S` / `Cmd+S` | Save current file |
| `Escape` | Close modal (with unsaved changes confirmation if dirty) |
| `Tab` (in editor) | Insert 4 spaces |

---

## Service Worker Cache

`file-browser-manager.js` is listed in the `PRECACHE_URLS` array in `interface/service-worker.js` under the path `/interface/interface/file-browser-manager.js`. The `<script>` tag in `interface.html` includes a `?v=N` cache-buster query string. **Both** the service worker `CACHE_VERSION` constant and the `?v=N` in the script tag must be bumped together whenever `file-browser-manager.js` changes, otherwise stale JS may be served from the browser's HTTP cache or the service worker cache.

If a stale version of the JS is running (visible symptom: `#file-browser-backdrop` div appearing in the DOM), the user must unregister the service worker in DevTools and hard-refresh, or a matching cache version bump will force the SW to re-fetch on the next page load.

---

## Known Issues and Historical Fixes

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Backdrop `#file-browser-backdrop` appears covering the modal | Old cached JS (which created a custom backdrop div) served from service worker / HTTP cache | Bumped cache version; removed backdrop creation from JS; added `document.getElementById('file-browser-backdrop').remove()` in open and close paths as a defensive sweep |
| Modal not visible at all | Bootstrap classes `modal fade` on the div caused Bootstrap JS to manage display, conflicting with manual open from a separate modal | Removed all Bootstrap modal classes and `data-backdrop` / `data-keyboard` attributes from the `<div>`; modal is now a plain positioned div |
| Empty state div overlaying the editor after file load | `_showView()` used jQuery `.show()/.hide()` which `!important` utility classes overpowered | Rewrote to use vanilla `element.style.display` |
| Preview container covered entire editor area | `position: absolute` on preview container made it fill the wrapper regardless of flex state | Changed to `flex: 1` so it participates normally in the flex row |
| CodeMirror renders blank on first open | CodeMirror instantiated before modal was visible | Deferred `_ensureEditor()` to 50 ms after modal `display: block` |
| Address bar autocomplete not working | `change` event not bound; datalist not populated | Added `_refreshPathSuggestions()` call after every `loadTree()` completion; bound `change` event to call `_navigateAddressBar()` |
| Browser `prompt()` for file creation | `prompt()` is ugly and doesn't show target directory | Replaced with inline naming modal overlay showing target directory hint |
