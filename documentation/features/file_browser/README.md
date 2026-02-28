# File Browser & Editor

## Overview

Full-screen modal file browser and code editor accessible from the chat-settings-modal **Actions** tab. Provides VS Code-like file tree navigation, syntax-highlighted editing via CodeMirror 5, markdown preview with live toggle, and full CRUD operations. All file access is sandboxed to the server's working directory.

---

## Features

- VS Code-like collapsible file tree sidebar with lazy per-directory loading
- CodeMirror 5 editor with syntax highlighting for Python, JavaScript, TypeScript, CSS, HTML, XML, Markdown (GFM), JSON
- Markdown preview tab using the project's `renderMarkdownToHtml` / `marked.js` renderer with `hljs` code block highlighting
- Address bar for direct path navigation with fuzzy autocomplete dropdown (substring + sequential character matching, filename-boosted scoring, highlighted matches)
- Full CRUD: create files/folders, rename, delete (via right-click context menu or background context-click)
- Unsaved-changes guard: dirty indicator dot, Save / Discard buttons, confirmation dialog on close/navigate
- Keyboard shortcuts: `Ctrl+S` / `Cmd+S` save, `Escape` close, `Tab` indent
- Theme picker (Monokai default / Default light)
- Binary file detection (null-byte scan in first 8 KB) — shows informational message instead of loading garbled content
- 2 MB file size guard — shows warning with "Load Anyway" override button
- State persistence across modal open/close (expanded dirs, current file, scroll position — all in-memory)
- Sidebar collapse toggle (hide/show the 250 px tree panel to maximize editor width)
- Sidebar New File / New Folder buttons in the tree header for quick creation without right-clicking
- Inline naming modal for file/folder creation and renaming, replacing the browser's native `prompt()` with a target directory hint; also used for renaming items (pre-fills current name, auto-selects text)
- Reload from Disk button: re-fetches the currently open file from the server, with unsaved-changes confirmation if dirty
- Fuzzy address bar autocomplete: replaces browser-native datalist prefix matching with a custom dropdown supporting substring, fuzzy sequential character matching, and filename-priority scoring with highlighted matched characters
- In-modal confirmation and naming dialogs: all `confirm()` and `prompt()` calls replaced with styled overlay modals (z-index 100001-100002) that render correctly above the file browser's z-index:100000 overlay
- Word wrap toggle: toolbar button to toggle CodeMirror line wrapping on/off, with active state indicator
- Download button: triggers native browser download of the currently open file via `GET /file-browser/download`
- Upload button + modal: drag-and-drop or browse file upload with XHR progress bar, directory targeting, overwrite protection via `POST /file-browser/upload`
- AI Diff modal word wrap and colour CSS: long diff lines wrap instead of horizontal scrolling, with green/red/blue/grey line-class styling
- Edit Instruction with diff context: re-editing an AI instruction appends a summary of the previous diff result for follow-up refinement
- Bootstrap Icons CDN upgraded from 1.7.2 to 1.11.3 to support newer icons (`bi-text-wrap` added in 1.8.0)
- **PDF Viewer**: clicking a `.pdf` file in the tree renders it inline using the bundled PDF.js viewer (no download prompt). A scoped progress bar shows download progress. Save, AI Edit, Word Wrap, Reload are disabled for PDFs; Download remains active.
- **WYSIWYG Markdown Editing**: markdown files now have a three-mode view-mode selector (Raw / Preview / WYSIWYG). WYSIWYG embeds EasyMDE inline in the file browser panel. Content syncs back to CodeMirror (source of truth) on mode switch or save. AI Edit is disabled in WYSIWYG mode.
- **Responsive view-mode selector**: button group on ≥576 px screens (ids: `#fb-view-btngroup`, buttons have `data-view="raw|preview|wysiwyg"`); `<select id="file-browser-view-select">` on narrow screens. Both driven by `_setViewMode(mode)`.
- **Drag-and-drop move**: any tree item can be dragged onto a folder in the sidebar to move it. Dropping onto the tree background (outside any folder `<li>`) moves the item to the **root directory**. Visual feedback: dragged item dims (`.fb-drag-source`), valid drop targets highlight with a dashed blue outline (`.fb-drag-over`), the entire tree panel highlights with a dashed blue outline and faint blue tint (`.fb-drag-over-root`) when the cursor is over the tree background. Prevents moving a folder into itself or its own descendant.
- **Context-menu move**: right-click → "Move to…" opens a destination picker modal (`#file-browser-move-modal`) with a lazy-expanding folder-only tree. A **/ (root)** item (icon `bi-house-door`, class `fb-move-root-item`, `data-path="."`) is prepended above the sub-folder tree so the user can explicitly move the item to the root directory. Move button enables once a destination folder is selected.
- **Decoupled move backend**: move operations are routed through `_config.onMove(srcPath, destPath, done)`. Default implementation calls `POST /file-browser/move`. Override at `FileBrowserManager.init({onMove: fn})` or `FileBrowserManager.configure({onMove: fn})` for different embedding contexts.

---

## UI Details

### Entry Point

Settings modal → **Actions** tab → **File Browser** button (`#settings-file-browser-modal-open-button`).

A fallback click handler is also wired inline in `interface.html` so the button works even if `FileBrowserManager` fails to init silently.

### Modal Layout

- Full-screen overlay: `position: fixed; inset: 0; z-index: 100000 !important`
- The modal is **not** a Bootstrap `.modal` — it is a plain `<div>` with Bootstrap layout classes inside, opened/closed with manual DOM manipulation to avoid Bootstrap JS conflicts when another modal (settings) is already open.
- Inner layout: flex row → collapsible sidebar (250 px) + editor/viewer column
- Header bar: sidebar-toggle, address bar (with fuzzy autocomplete dropdown), dirty indicator, theme picker, word wrap toggle, AI Edit button, discard, save, reload-from-disk, download, upload, close
- Editor area shows one of five views at a time: editor, preview, wysiwyg, pdf, empty-state/message

### Address Bar Fuzzy Autocomplete

The address bar (`#file-browser-address-bar`) is an `<input>` with `autocomplete="off"` wrapped in a `position: relative` container. A custom dropdown div `#file-browser-suggestion-dropdown` (class `fb-suggestion-dropdown`) is positioned absolutely below the input.

After every tree load, `_refreshPathSuggestions()` scans all rendered `<li>` elements and stores sorted paths in `state.pathSuggestions` and `state.pathSuggestionMap`. No `<datalist>` is used.

On every keystroke (`input` event), `_filterAndShowSuggestions(query)` runs the fuzzy algorithm against all stored paths:

- **Fuzzy matching**: `_fuzzyMatch(needle, haystack)` performs case-insensitive sequential character matching. An exact substring match is tried first (bonus 1.5-2.0x). Then a sequential character scan scores results: consecutive matches = 1.0, word boundary matches = 0.8, mid-word matches = 0.3, gap penalty of -0.005 per character.
- **Path-aware scoring**: `_fuzzyMatchPath(query, path)` tries matching against the filename component first with a 1.5x score boost, then falls back to the full path.
- **Results**: sorted by score descending, limited to the top 30.
- **Rendering**: each result is rendered with `_renderHighlightedPath()`. The directory part appears in muted gray, the filename in dark text, and matched characters in bold blue (class `fb-match-char`).
- **Keyboard navigation**: ArrowDown/ArrowUp navigate the list, Enter selects the highlighted item (or navigates to the typed path if nothing is highlighted), Escape closes the dropdown.
- **Mouse and focus**: clicking an item navigates to it, clicking outside closes the dropdown, focusing the input re-opens the dropdown if text is present.

CSS classes: `.fb-suggestion-dropdown`, `.fb-suggestion-item`, `.fb-suggestion-item.active`, `.fb-match-char`, `.fb-match-filename`, `.fb-match-dir`.

### View-Mode Selector (Markdown files)

For `.md` / `.markdown` files only, a **Raw / Preview / WYSIWYG** view-mode selector appears above the editor area (`#file-browser-tab-bar`). It is hidden for all other file types.

On wide screens (≥576 px) a Bootstrap button group (`#fb-view-btngroup`) is shown; on narrow screens a `<select id="file-browser-view-select">` is shown instead. Both are driven by `_setViewMode(mode)` which:

- Syncs EasyMDE → CodeMirror before leaving WYSIWYG mode
- Updates button active states and the select value
- Calls `_showView()` with the appropriate view key
- Calls `_updateToolbarForFileType()` to disable incompatible toolbar buttons

The responsive swap is controlled entirely by CSS media queries — the `<select>` has no inline `display` style so the rule `@media (min-width: 576px) { #file-browser-view-select { display: none !important; } }` can override it. A prior version had `style="display:none;"` hardcoded on the select, which blocked the media query from showing it on narrow screens (fixed).

#### Sidebar coupling

The tab bar visibility is tied to the sidebar toggle:

- **Sidebar open** → tab bar visible (markdown file only)
- **Sidebar collapsed** → tab bar hidden (regardless of file type)

This is enforced in two places that must agree:
- `_toggleSidebar()`: on sidebar-open, calls `$('#file-browser-tab-bar').show()` if `state.isMarkdown`; on sidebar-collapse, always calls `.hide()`.
- `_doLoadFile()`: on markdown file load, calls `$('#file-browser-tab-bar').show()` **only if `state.sidebarVisible`** — so loading a new file while the sidebar is collapsed does not inadvertently re-show the tab bar.

The `state.sidebarVisible` guard in `_doLoadFile` is the critical coupling point. Without it, the two functions fight each other and the tab bar appears/disappears incorrectly.

### Context Menu

Right-click on any tree `<li>` populates `state.contextTarget` and shows `#file-browser-context-menu` at cursor coordinates. Right-clicking the tree background (not on an item) sets `state.contextTarget` to the current directory for "create here" operations. Menu items: **New File**, **New Folder**, **Rename**, **Move to…**, **Delete**. The New File and New Folder actions use the naming modal (see below) instead of the browser's native `prompt()`. Move opens the move destination modal (see below).

### Sidebar Header Buttons

The sidebar header row (next to the Refresh button) contains two quick-action buttons:

- **New File** (`#file-browser-new-file-btn`, icon `bi-file-earmark-plus`)
- **New Folder** (`#file-browser-new-folder-btn`, icon `bi-folder-plus`)

Both use the same styling as the Refresh button: `btn btn-sm btn-link text-muted p-0 mr-1`. Clicking either opens the naming modal (see below) with the target directory determined by `_getTargetDir()`.

### Naming Modal

The naming modal (`#file-browser-name-modal`) replaces the browser's native `prompt()` for file and folder creation and renaming. It provides a cleaner UX with a visible target directory hint so the user knows where the new item will be created.

Layout and behavior:

- Fixed overlay with `z-index: 100001` (one above the file browser modal) and a semi-transparent backdrop
- Title text changes dynamically: "New File", "New Folder", or "Rename" depending on the action
- Input field for the file or folder name; pre-filled with the current filename and auto-selected for rename operations
- Directory hint below the input showing the resolved target directory
- Cancel and OK buttons in the footer; OK button text changes: "Create" for new file/folder, "Rename" for rename
- Enter key confirms, Escape key cancels, clicking the backdrop cancels

Target directory logic uses `_getTargetDir()`, which checks in order: `state.contextTarget` (from right-click), parent directory of `state.currentPath` (currently open file), then `state.currentDir` as fallback.
Function signature: `_showNameModal(type, callback, opts)` where `type` can be `'file'`, `'folder'`, or `'rename'`, and `opts` can include `currentName` and `dir`.

### Confirm Modal

`#file-browser-confirm-modal` is a fixed overlay at `z-index: 100002` that replaces all native `confirm()` calls. Native browser dialogs are blocked behind the file browser's z-index:100000 overlay, so a custom in-modal solution is required.

Layout and behavior:

- Title, body (supports HTML), OK and Cancel buttons
- OK button text and class are customizable (e.g. "Delete" with `btn-danger`, "Discard" with `btn-warning`)
- Escape closes, backdrop click closes

Function signature: `_showConfirmModal(title, bodyHtml, onConfirm, opts)`. The API is callback-based, not synchronous, since it replaces blocking `confirm()` calls with an async overlay.

Used by: delete item, discard changes, reload from disk (dirty check), close modal (dirty check), navigate to file (dirty check).

### Move Modal

`#file-browser-move-modal` is a fixed overlay at `z-index: 100004` that appears when the user selects **Move to…** from the context menu or drops a file via drag-and-drop.

Layout and behavior:

- Displays the source item name at the top (`#fb-move-src-name`)
- Lazy-expanding folder-only tree (`#fb-move-folder-tree`) — shows only directories (no files). A **/ (root)** item (`<div class="fb-move-dir-item fb-move-root-item" data-path=".">` with `bi-house-door` icon) is prepended at the top, separated from the sub-folder tree by a bottom border. Root is loaded on modal open; sub-folders expand on click by fetching from `/file-browser/tree`.
- Selected folder is highlighted with `.fb-move-selected` class; the `#fb-move-dest-hint` shows the full selected path.
- **Move Here** button (`#fb-move-ok-btn`) is disabled until a destination folder is selected; re-enabled on failure.
- **Cancel** button and backdrop click both dismiss the modal.
- After a successful move, the file tree is refreshed and a success toast is shown. If the currently open file was moved, `state.currentPath` and the address bar are updated to the new path.
- Prevents moving a folder into itself or its own descendant (validated client-side via `_isValidMoveTarget()` and server-side via the `/file-browser/move` endpoint).

Key functions: `_showMoveModal()`, `_hideMoveModal()`, `_loadMoveTree(dirPath, $container)`, `_confirmMove()`, `_moveItem(srcPath, destPath)`, `_isValidMoveTarget(srcPath, destDirPath)`.

### Word Wrap

Button: `#file-browser-wrap-btn` in the toolbar (after the theme picker), icon `bi-text-wrap`, label "Wrap" (text hidden on screens <576 px via `<span class="d-none d-sm-inline">`). Disabled when no file is open.

- Toggles the `lineWrapping` option on the CodeMirror instance via `state.cmEditor.setOption('lineWrapping', ...)`.
- Button shows the `.active` class when wrapping is enabled. State tracked in `state.wordWrap` (default: `false`).
- Function: `_toggleWordWrap()`.
- The `bi-text-wrap` icon was added to Bootstrap Icons in v1.8.0, so the CDN link was upgraded from 1.7.2 to 1.11.3.

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
| POST | `/file-browser/move` | Move file or directory `{"src_path": "...", "dest_path": "..."}`. dest_path is the full new path. 409 if dest exists, 400 if moving folder into itself |
| POST | `/file-browser/delete` | Delete file or directory `{"path": "...", "recursive": true}` |
| GET | `/file-browser/download?path=...` | Download file as attachment (`send_file` with `as_attachment=True`) |
| POST | `/file-browser/upload` | Upload file (multipart form-data: `file`, `path`, `overwrite`). Returns `{"path", "size"}`. 409 if exists without overwrite |
| GET | `/file-browser/serve?path=...` | Serve file inline for in-browser rendering (e.g. PDF). `send_file` with `as_attachment=False`. MIME auto-detected via `mimetypes.guess_type()` |

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

`file-browser-manager.js` uses a **factory function** `createFileBrowser(instanceId, initialCfg)` that returns an independent file browser instance. It uses no ES module syntax (`import`/`export`) and no classes — plain `var` declarations and named inner functions, consistent with the project's jQuery + Bootstrap 4.6 legacy style.

```javascript
function createFileBrowser(instanceId, initialCfg) {
    'use strict';
    // instanceId: 'fb' (default, CSS-compatible IDs) or e.g. 'global-docs-fb' (prefixed IDs)
    // initialCfg: deep-merged into _config defaults at creation time
    // ... private state and functions ...
    return { init, open, configure, loadFile, saveFile, discardChanges };
}
// Default instance for Settings > Actions > File Browser:
window.FileBrowserManager = createFileBrowser('fb');
```

All event handlers are bound in the instance's `init()`, which is called once on DOM ready. The module's internal state is held in a single `state` object per instance (see State Object section).

The `<template id="file-browser-template">` element in `interface.html` holds the single shared HTML markup. `_mountDom()` clones it and replaces all `data-fb-key` attribute values with prefixed IDs before inserting into the document. For `instanceId='fb'`, IDs match the CSS rules exactly (e.g. `file-browser-modal`). For other instance IDs, `_prefixId(key)` substitutes the prefix (e.g. `global-docs-fb-editor-wrapper`).

---

### Multi-Instance Architecture

The file browser follows a **one template, one set of CSS rules, N instances** philosophy. Any number of independent file browser instances can be created from the single `<template>` without forking HTML or CSS.

#### How it works

1. **One `<template>`**: `interface.html` has a single `<template id="file-browser-template">` with `data-fb-key` attributes on every significant element (e.g. `data-fb-key="modal"`, `data-fb-key="tree"`, `data-fb-key="editor-wrapper"`).

2. **`_mountDom()`**: Called during `init()`. Clones the template content. For each element with a `data-fb-key` attribute, calls `_prefixId(key)` to compute the actual DOM `id`. For `instanceId='fb'`, `_prefixId('modal')` → `'file-browser-modal'`. For `instanceId='global-docs-fb'`, `_prefixId('modal')` → `'global-docs-fb-modal'`. The cloned fragment is appended to `document.body`.

3. **`_$(key)`**: Internal helper that looks up a cached jQuery selector for a given key. All internal code uses `_$('modal')`, `_$('tree')`, etc. — never hardcoded IDs.

4. **CSS class-based theming**: Every layout-critical element in the template has an `fb-*` class in addition to its unique `id`. All CSS rules in `style.css` target `.fb-*` class selectors — never `#file-browser-*` IDs. This ensures both the default instance and any additional instance get the correct layout regardless of their prefixed IDs.

   CSS classes added to template elements: `.fb-modal`, `.fb-sidebar`, `.fb-tree`, `.fb-editor-wrapper`, `.fb-editor-container`, `.fb-tab-bar`, `.fb-view-btngroup`, `.fb-view-select`, `.fb-preview-container`, `.fb-wysiwyg-container`, `.fb-pdf-container`, `.fb-pdfjs-viewer`, `.fb-empty-state`, `.fb-address-bar`, `.fb-theme-select`, `.fb-context-menu`, `.fb-move-folder-tree`.

5. **`openBtn: null`**: Non-default instances pass `openBtn: null` in their config so `init()` does not bind a click handler to a non-existent button. The guard `if (_config.dom.openBtn) { ... }` in `init()` prevents double-binding.

#### Creating a new embedded instance

```javascript
var myFb = createFileBrowser('my-fb', {
    rootPath: 'storage/my_data/',
    openBtn: null,           // no auto-open button
    onUpload: function(file, targetDir, done) {
        // custom upload logic
        myApi.upload(file, targetDir)
            .then(function() { done(null); })
            .catch(function(err) { done(err.message); });
    }
});
myFb.init();
myFb.open();
```

The default `window.FileBrowserManager = createFileBrowser('fb')` instance is created at the bottom of `file-browser-manager.js` for backward compatibility with all existing call sites.

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
 `#fb-ai-diff-content` uses `white-space:pre-wrap; word-break:break-all` so long diff lines wrap instead of requiring horizontal scroll
 CSS classes for diff line types: `.ai-diff-add` (green `#e6ffec`), `.ai-diff-del` (red `#ffebe9`), `.ai-diff-hunk` (blue `#ddf4ff`, bold), `.ai-diff-header` (muted grey)
 Accept: splices edit into CodeMirror (`replaceRange` for selection, `setValue` for whole file)
 Reject: discards the proposed edit
 Edit Instruction: returns to instruction modal with previous text preserved. Now also appends a context line to the textarea: `--- Previous result: +N / -N lines. Give additional instructions below: ---\n` (counts parsed from `state.aiEditLastDiffText`). Cursor moves to end of textarea for immediate follow-up typing.

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
 `_editAiInstruction()` — returns to instruction modal from diff view, appends previous-result context summary
 `_showAiDiffModal()` — displays the diff preview modal, stores diff text in `state.aiEditLastDiffText`
 `_clearAiEditState()` — resets all AI edit state fields including `aiEditLastDiffText`

---
## Reload from Disk

Button: `#file-browser-reload-btn` in the top bar after Save, icon `bi-arrow-clockwise`, disabled when no file is open.

- If the file has unsaved changes, a confirm modal is shown before reloading
- Calls the existing `GET /file-browser/read` endpoint (no new backend needed)
- Preserves cursor position and scroll position after reload
- Updates `state.originalContent`, resets `state.isDirty`
- Shows success toast on reload, error toast on failure (404 if file was deleted from disk)
- Enable/disable logic mirrors the AI Edit button: enabled after a successful text file load, disabled on binary/too-large/no-file/file-deleted

Key functions: `_reloadFromDisk()` (dirty-check wrapper), `_doReload()` (performs the actual GET request).

---
## Download

Button: `#file-browser-download-btn` in the toolbar, icon `bi-download`. Disabled when no file is open.

- Triggers a native browser file download by creating a temporary `<a download>` element pointing to `GET /file-browser/download?path=...`.
- The Flask endpoint uses `send_file(..., as_attachment=True, download_name=filename)`. Path is sandboxed via `_safe_resolve()`.
- Function: `_downloadFile()`.

---
## Upload

Button: `#file-browser-upload-btn` in the toolbar, icon `bi-upload`. Always active (does not require a file to be open).

Opens `#file-browser-upload-modal` (`position:fixed; inset:0; z-index:100003`).

### Modal Features

- **Directory hint** showing the upload target directory (parent dir of current file, or current dir, or root)
- **Drag-and-drop zone** (`#fb-upload-dropzone`): highlights on dragover, accepts a dropped file
- **Browse link** (`#fb-upload-browse-link`): opens a hidden `<input type="file" id="fb-upload-input">`
- **Selected filename** shown in `#fb-upload-filename`
- **XHR upload with progress**: real progress bar (`#fb-upload-progress-bar`, `#fb-upload-progress-text`)
- **Cancel and Upload buttons**; spinner shown during upload
- On success: closes modal, refreshes file tree, shows toast

### Backend

`POST /file-browser/upload` (multipart form-data):

- Fields: `file` (the uploaded file), `path` (target directory), `overwrite` (optional, default false)
- Sanitises filename via `os.path.basename()`
- Returns `{"path": dest_rel, "size": N}` on success
- Returns 409 if the file already exists and `overwrite` is not set

### Key Functions

- `_showUploadModal()` / `_hideUploadModal()` — open/close the upload overlay
- `_setUploadFile(file)` — stages a file object for upload, updates the filename display
- `_doUpload()` — performs the XHR POST with progress tracking
- `_getUploadDir()` — determines the target directory for the upload
- `_uploadPendingFile` — module-level variable holding the staged file object

---
## Implementation Notes

### Files Created

- `endpoints/file_browser.py` — Flask Blueprint (`file_browser_bp`) with 11 endpoints (tree, read, write, mkdir, rename, **move**, delete, download, upload, serve, ai-edit), path traversal prevention, binary detection, 2 MB size guard. Move endpoint: `POST /file-browser/move`, validates both paths via `_safe_resolve()`, prevents self-moves, returns 400/404/409 errors.
- `interface/file-browser-manager.js` — **Factory function** `createFileBrowser(instanceId, initialCfg)` replacing IIFE singleton. Single `<template>` extraction. `_mountDom()`, `_prefixId()`, `_$(key)` helpers for multi-instance DOM management. `window.FileBrowserManager = createFileBrowser('fb')` for backward compatibility. Full CRUD, CodeMirror integration, all existing features preserved. **PDF fix**: `.pdf` extension check now runs before `is_binary` check in `_doLoadFile()` to prevent PDFs being shown as binary content.

### Files Modified

- `endpoints/__init__.py` — Registered `file_browser_bp` blueprint
- `interface/interface.html` — `<template id="file-browser-template">` extracted from inline HTML. All layout elements have `fb-*` classes added. View switcher moved to modal header for global-docs instance. `window.FileBrowserManager = createFileBrowser('fb')` initialization.
- `interface/style.css` — **All layout rules migrated from `#file-browser-*` ID selectors to `.fb-*` class selectors** to support multi-instance architecture. All `fb-*` classes added to template elements.
- `interface/service-worker.js` — Added `file-browser-manager.js` to precache list; cache version bumped on each JS update
- `interface/audio_process.js` — Added guard to skip Cmd+K / Ctrl+K voice shortcut when file browser modal is open

### Key Public API (file-browser-manager.js)

| Function | Description |
|----------|-------------|
| `FileBrowserManager.init(cfg)` | Binds all event handlers; merges optional config (e.g. `{ onMove: fn }`); called once on DOM ready |
| `FileBrowserManager.open()` | Opens the file browser modal |
| `FileBrowserManager.loadFile(path, force)` | Loads a file into CodeMirror (with binary/size guards) |
| `FileBrowserManager.saveFile()` | Writes current editor content to server |
| `FileBrowserManager.discardChanges()` | Reverts editor to last saved content |
| `FileBrowserManager.configure(cfg)` | Merges config overrides post-init, e.g. to set a custom `onMove` callback for a different embedding context |

### Key Internal Functions

| Function | Description |
|----------|-------------|
| `loadTree(dirPath, $parentUl)` | Fetches and renders a directory listing in the sidebar |
| `_toggleDir($li)` | Expands/collapses a tree directory node |
| `_showView(view, messageHtml)` | Switches between all five view states: `'editor'`, `'preview'`, `'wysiwyg'`, `'pdf'`, `'empty'`/`'message'`. Explicitly sets `edEl.style.display` so the CodeMirror container is hidden in all non-editor views. |
| `_showFileBrowserModal()` | Opens the modal with manual DOM manipulation; kills any stale backdrop |
| `_closeModal()` | Closes modal, sweeps orphan backdrops, conditionally removes `modal-open` |
| `_refreshPathSuggestions()` | Rebuilds sorted path list from tree for fuzzy autocomplete (no datalist) |
| `_renderPreview()` | Renders current editor content as markdown HTML into preview container |
| `_ensureEditor()` | Lazily creates the CodeMirror instance on first open |
| `_confirmIfDirty()` | Shows confirm modal if unsaved changes; calls callback when safe to proceed (async, not synchronous) |
| `_createFile()`, `_createFolder()` | CRUD via naming modal + API calls |
| `_renameItem()`, `_deleteItem()` | Rename via naming modal (pre-fills current name) + API call; Delete via confirm modal + API call |
| `_getTargetDir()` | Determines target directory for new file/folder (contextTarget, then currentPath parent, then currentDir) |
| `_showNameModal(type, callback, opts)` | Shows naming modal for file/folder creation or renaming |
| `_hideNameModal()` | Hides the naming modal and clears state |
| `_nameModalConfirm()` | Validates input and fires callback from naming modal |
| `_reloadFromDisk()` | Reload current file from disk with dirty-check confirmation |
| `_doReload()` | Internal: performs the actual reload GET request |
| `_fuzzyMatch(needle, haystack)` | Sequential char fuzzy matching with scoring (substring > consecutive > word-boundary > mid-word) |
| `_fuzzyMatchPath(query, path)` | Path-aware fuzzy match: tries filename first (1.5x boost), falls back to full path |
| `_filterAndShowSuggestions(query)` | Filters all paths by fuzzy query and renders the suggestion dropdown |
| `_hideSuggestionDropdown()` | Hides suggestion dropdown and resets navigation state |
| `_handleSuggestionNav(key)` | Arrow/Enter key navigation for the suggestion dropdown |
| `_renderHighlightedPath(path, indexes)` | Renders path HTML with matched chars highlighted in blue bold |
| `_showConfirmModal(title, body, onConfirm, opts)` | Shows in-modal confirmation dialog (replaces native confirm()) |
| `_hideConfirmModal()` | Hides confirm dialog |
| `_toggleWordWrap()` | Toggles CodeMirror `lineWrapping` option and updates button active state |
| `_downloadFile()` | Triggers native browser download of the currently open file |
| `_showUploadModal()` | Opens the upload modal overlay |
| `_hideUploadModal()` | Closes the upload modal and resets state |
| `_setUploadFile(file)` | Stages a file for upload, updates filename display |
| `_doUpload()` | Performs XHR POST to `/file-browser/upload` with progress tracking |
| `_getUploadDir()` | Determines target directory for upload |
| `_editAiInstruction()` | Returns to AI instruction modal from diff view with previous-result context |
| `_showAiDiffModal()` | Shows AI diff preview modal, stores diff text in state |
| `_clearAiEditState()` | Resets all AI edit state fields |
| `_loadFilePDF(filePath)` | Fetches PDF via XHR as blob, creates a blob URL, injects it into the PDF.js iframe in `#file-browser-pdf-container`. Shows scoped progress bar during download. Revokes previous blob URL before loading a new one. |
| `_setViewMode(mode)` | Switches the active view mode (`'raw'`, `'preview'`, `'wysiwyg'`). Syncs EasyMDE → CodeMirror before leaving WYSIWYG, updates button group and select, then calls `_showView()` and `_updateToolbarForFileType()`. |
| `_initOrRefreshEasyMDE()` | Lazily creates the EasyMDE instance (with `shortcuts` overrides to prevent Ctrl+S interception) inside `#file-browser-wysiwyg-container` on first call; on subsequent calls just sets content and refreshes the inner CodeMirror. Wires dirty tracking via EasyMDE's internal CodeMirror `change` event. |
| `_syncWysiwygToCodeMirror()` | Reads `fbEasyMDE.value()` and sets it as CodeMirror's value, keeping CodeMirror as the single source of truth. Called before every save, modal close, and mode switch away from WYSIWYG. |
| `_updateToolbarForFileType()` | Enables/disables toolbar buttons based on file type and view mode. PDF: disables Save, Discard, AI Edit, Wrap, Reload. WYSIWYG mode: additionally disables AI Edit and Wrap. |
| `_isValidMoveTarget(srcPath, destDirPath)` | Returns true if srcPath can be moved into destDirPath — blocks self-drops, descendant-drops, and same-parent no-ops. |
| `_moveItem(srcPath, destPath)` | Calls `_config.onMove()`, updates `state.currentPath` if the open file was moved, calls `_refreshTree()`, shows toast. |
| `_showMoveModal()` / `_hideMoveModal()` | Open/close the move destination modal; populate/clear folder tree and reset state. |
| `_loadMoveTree(dirPath, $container)` | Fetch folder-only tree from `/file-browser/tree` and render lazy-expandable folder list into the move modal. |
| `_confirmMove()` | Reads `state.moveDest`, constructs `destPath = moveDest + '/' + basename(srcPath)`, validates, calls `_moveItem()`. |

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
    pathSuggestionMap: {},    // Set-like map for O(1) lookup on address bar change event
    aiEditSelection: null,   // Selected text for AI edit
    aiEditProposed: null,    // Proposed replacement from AI edit
    aiEditOriginal: null,    // Original text before AI edit
    aiEditIsSelection: false, // Whether AI edit targets a selection vs whole file
    aiEditStartLine: null,   // Start line of AI edit selection
    aiEditEndLine: null,     // End line of AI edit selection
    aiEditBaseHash: null,    // Hash of file content at time of AI edit request
    aiEditLastDiffText: null, // Raw diff text from last AI edit, used for edit-instruction context summary
    wordWrap: false,           // Whether CodeMirror line wrapping is enabled
    isPdf: false,              // Whether current file is a PDF (no CodeMirror, uses PDF.js)
    pdfBlobUrl: null,          // Blob URL of currently loaded PDF (revoked on file change/close)
    viewMode: 'raw',           // Active view mode: 'raw' | 'preview' | 'wysiwyg' (markdown only)
    fbEasyMDE: null,           // EasyMDE instance (lazy-created in WYSIWYG container, persisted)
    dragSource: null,          // {path,type,name} of tree item currently being dragged (D&D move)
    moveTarget: null,          // {path,type,name} of item being moved via context menu
    moveDest: null             // Destination directory selected in move modal
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
| `Cmd+K` / `Ctrl+K` | Open AI Edit overlay (when editor focused) |

---

## Service Worker Cache

`file-browser-manager.js` is listed in the `PRECACHE_URLS` array in `interface/service-worker.js` under the path `/interface/interface/file-browser-manager.js`. The `<script>` tag in `interface.html` includes a `?v=N` cache-buster query string. **Both** the service worker `CACHE_VERSION` constant and the `?v=N` in the script tag must be bumped together whenever `file-browser-manager.js` changes, otherwise stale JS may be served from the browser's HTTP cache or the service worker cache.

If a stale version of the JS is running (visible symptom: `#file-browser-backdrop` div appearing in the DOM), the user must unregister the service worker in DevTools and hard-refresh, or a matching cache version bump will force the SW to re-fetch on the next page load.

---

## Pluggable Config API

The file browser can be configured for different embedding contexts via a 7-group config schema. All hardcoded `$('#file-browser-*')` selectors have been replaced with `_$(key)` lookups against `_config.dom`, and all endpoint strings replaced with `_ep(name)` lookups against `_config.endpoints`. Behavior flags, operation callbacks, lifecycle events, and custom rendering hooks allow full customization without forking the code.

### Public API

| Method | Signature | Description |
|--------|-----------|-------------|
| `init` | `init([cfg])` | Initialize event handlers. Call once on page load. Optional config overrides deep-merged into defaults. |
| `open` | `open([path])` | Open the file browser modal. Optional `path` sets the starting directory. |
| `configure` | `configure(cfg)` | Deep-merge config overrides after initialization. `$.extend(true, ...)` preserves unspecified keys. |
| `loadFile` | `loadFile(path, [force])` | Load a specific file into the editor. |
| `saveFile` | `saveFile()` | Save current file to server. |
| `discardChanges` | `discardChanges()` | Revert editor to last saved content. |

### Config Schema (7 Groups)

All defaults reproduce the current Settings > Actions > File Browser behavior exactly.

#### Group 1: Endpoints

```javascript
endpoints: {
    tree:     '/file-browser/tree',     // GET  ?path=
    read:     '/file-browser/read',     // GET  ?path=
    write:    '/file-browser/write',    // POST {path, content}
    mkdir:    '/file-browser/mkdir',    // POST {path}
    rename:   '/file-browser/rename',   // POST {old_path, new_path}
    delete:   '/file-browser/delete',   // POST {path, recursive}
    move:     '/file-browser/move',     // POST {src_path, dest_path}
    upload:   '/file-browser/upload',   // POST multipart {file, path}
    download: '/file-browser/download', // GET  ?path=
    serve:    '/file-browser/serve',    // GET  ?path=  (PDF inline)
    aiEdit:   '/file-browser/ai-edit'   // POST {path, instruction, ...}
}
```

Set any endpoint to `null` to disable that operation. If `write` is null, Save and Create File are disabled. If `tree` is null, tree browsing is disabled entirely.

#### Group 2: DOM Element IDs

47 configurable DOM IDs covering the main modal, tree, toolbar buttons, address bar, editor containers, and sub-modals (confirm, name, move, upload, AI edit/diff). All default to the existing `file-browser-*` IDs. Override for a second embedding that uses different DOM elements.

Note: internal `$('#fb-*')` sub-element selectors (upload dropzone, move folder tree, AI edit form fields, PDF progress) remain hardcoded. These are inside shared modals and do not need per-embedding overrides.

#### Group 3: Behavior Flags

```javascript
readOnly:        false,   // true = no write/create/rename/delete/upload
allowUpload:     true,    // show/enable upload button
allowDelete:     true,    // show/enable delete in context menu
allowRename:     true,    // show/enable rename in context menu
allowCreate:     true,    // show/enable new file + new folder buttons
allowMove:       true,    // show/enable move in context menu + DnD
allowAiEdit:     true,    // show/enable AI Edit button
showEditor:      true,    // false = tree-only mode; editor panel hidden
showAddressBar:  true,    // false = hide address bar
```

Flags are applied via `_applyBehaviorFlags()` when the modal opens. `readOnly: true` implies all write operations disabled.

#### Group 4: Root and Title

```javascript
rootPath: '.',            // Directory to load when modal opens
title:    'File Browser', // Text shown in modal header (future use)
```

#### Group 5: Operation Callbacks

Each CRUD operation checks for a custom callback before falling back to the default endpoint-based implementation. All callbacks use the same `done(errorMsg|null)` pattern as `onMove`.

| Callback | Signature | Default |
|----------|-----------|---------|
| `onMove` | `(srcPath, destPath, done)` | POST to `endpoints.move` |
| `onDelete` | `(path, done)` | POST to `endpoints.delete` |
| `onRename` | `(oldPath, newPath, done)` | POST to `endpoints.rename` |
| `onCreateFolder` | `(path, done)` | POST to `endpoints.mkdir` |
| `onCreateFile` | `(path, done)` | POST to `endpoints.write` |
| `onUpload` | `(file, targetDir, done)` | XHR POST to `endpoints.upload`. Override to route uploads to a different backend (e.g. global docs upload endpoint). `targetDir` is the resolved upload directory path. Call `done(null)` on success or `done(errorMsg)` on failure. |
| `onSave` | `(path, content, done)` | POST to `endpoints.write` |

Set to `null` (default) to use the default endpoint-based implementation.

#### Group 6: Lifecycle Events

Pure notification callbacks (no `done()` needed).

| Event | Signature | When |
|-------|-----------|------|
| `onSelect` | `(path, type, entry)` | User clicks a tree item (after default action) |
| `onOpen` | `()` | Modal opened |
| `onClose` | `()` | Modal closed (after dirty check passes) |

#### Group 7: Custom Rendering

| Hook | Signature | Description |
|------|-----------|-------------|
| `enrichEntry` | `(entry, path, done)` | Async per-entry enrichment. Call `done(enrichedEntry)` when done. Runs after initial render. Callers should cache results to avoid API flooding. |
| `renderEntry` | `(entry, path)` | Sync custom rendering. Return a jQuery element to replace the default icon+name, or `null` for default rendering. |
| `buildContextMenu` | `(path, type)` | Return `[{label, icon, action}]` array for custom context menu items, or `null` for default menu. `action` receives `(path, type)`. |

### Example: Read-Only Folder Browser

```javascript
FileBrowserManager.configure({
    rootPath: 'storage/global_docs/abc123/',
    showEditor: false,
    readOnly: true,
    allowAiEdit: false,
    endpoints: {
        write: null,
        read: null,
        aiEdit: null
    },
    onOpen: function() { console.log('Folder browser opened'); },
    onSelect: function(path, type, entry) {
        console.log('Selected:', path, type);
    },
    enrichEntry: function(entry, path, done) {
        if (entry.type !== 'dir') { done(entry); return; }
        $.getJSON('/api/doc-info/' + entry.name, function(info) {
            done($.extend({}, entry, info));
        }).fail(function() { done(entry); });
    },
    renderEntry: function(entry, path) {
        if (entry.type !== 'dir' || !entry.title) return null;
        var $wrap = $('<span></span>');
        $wrap.append($('<span class="tree-name"></span>').text(entry.title));
        (entry.tags || []).slice(0, 3).forEach(function(tag) {
            $wrap.append($('<span class="badge badge-pill badge-secondary ml-1">' + tag + '</span>'));
        });
        return $wrap;
    }
});
FileBrowserManager.open('storage/global_docs/abc123/');
```

### Deep Merge Behavior

Both `init(cfg)` and `configure(cfg)` use `$.extend(true, _config, cfg)` (deep merge). This means partial overrides are safe:

```javascript
// Only override the upload endpoint; all other endpoints preserved
FileBrowserManager.configure({
    endpoints: { upload: '/custom/upload' }
});
```

### Refactor Files Modified

| File | Change |
|------|--------|
| `interface/file-browser-manager.js` | All config schema, helpers, behavior flags, callbacks, lifecycle events, custom rendering (Tasks 1-12) |
| `interface/interface.html` | Script tag `?v=` bump |
| `interface/service-worker.js` | `CACHE_VERSION` bump |

No HTML structure changes. No new DOM elements. No backend changes. All existing `/file-browser/*` endpoints unchanged.

---

## CSS Class System

All layout-critical file browser elements carry `fb-*` CSS classes in addition to their instance-specific `id` attributes. Style rules in `style.css` target only the `.fb-*` classes — never `#file-browser-*` IDs for layout.

**Why**: When a second instance is created with a different `instanceId` (e.g. `'global-docs-fb'`), its elements get different IDs (`#global-docs-fb-editor-wrapper` etc.) that would not match any `#file-browser-*` CSS rules. By targeting class selectors, all instances share the same layout styles automatically.

**Rule**: Never add a layout or sizing rule that targets a `#file-browser-*` ID selector. Always add or use the corresponding `.fb-*` class.

| Element | Class | Purpose |
|---------|-------|---------|
| Main modal div | `.fb-modal` | Full-screen overlay positioning |
| Sidebar | `.fb-sidebar` | 250px collapsible panel |
| File tree container | `.fb-tree` | Flex tree layout |
| Editor wrapper | `.fb-editor-wrapper` | Flex column fills remaining width |
| Editor container (CM) | `.fb-editor-container` | CodeMirror host sizing |
| Tab bar (view selector) | `.fb-tab-bar` | Raw/Preview/WYSIWYG selector row |
| View btn-group | `.fb-view-btngroup` | Bootstrap btn-group for wide screens |
| View select | `.fb-view-select` | `<select>` for narrow screens |
| Preview container | `.fb-preview-container` | Markdown preview flex sizing |
| WYSIWYG container | `.fb-wysiwyg-container` | EasyMDE host sizing |
| PDF container | `.fb-pdf-container` | PDF.js iframe host |
| PDF viewer iframe | `.fb-pdfjs-viewer` | Full-height iframe |
| Empty state | `.fb-empty-state` | "No file open" placeholder |
| Address bar | `.fb-address-bar` | Path input styling |
| Theme select | `.fb-theme-select` | Theme picker dropdown |
| Context menu | `.fb-context-menu` | Right-click menu positioning |
| Move folder tree | `.fb-move-folder-tree` | Folder-only tree in move modal |

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
| Context menu invisible behind file browser modal | Context menu z-index was 9999, file browser modal is 100000 | Bumped context menu z-index to 100005 |
| Rename/Delete from context menu did nothing | `_hideContextMenu()` nulled `state.contextTarget` before action could read it; global document click handler raced with action handler | Save target to local var before hiding, restore after; added `e.stopPropagation()` on context menu clicks |
| Native `confirm()`/`prompt()` dialogs invisible behind file browser | Browser native dialogs rendered behind the z-index:100000 file browser overlay | Replaced all 5 `confirm()`/`prompt()` calls with in-modal overlay dialogs (`_showConfirmModal`, `_showNameModal` with rename mode) |
| Address bar autocomplete only matches by prefix | Used HTML5 `datalist` which only supports browser-native prefix filtering | Replaced with custom fuzzy dropdown supporting substring, sequential char, and filename-priority matching |
| AI Edit / AI Diff modals render offscreen on mobile after keyboard/scroll shift | `#file-browser-ai-edit-modal` and `#file-browser-ai-diff-modal` used `position:absolute`, so after layout shifts the modal appeared offscreen on second open | Changed both to `position:fixed; inset:0`, matching the pattern of the name/confirm modals |
| `_closeModal()` re-entrancy race on double-call while dirty | No guard against concurrent calls; Escape + button tap could overwrite the pending confirm callback or race | Added guard at top of `_closeModal()`: `if ($('#file-browser-confirm-modal').css('display') === 'flex') return;` |
| Stale confirm/name dialogs visible on file browser re-open | `_showFileBrowserModal()` did not dismiss leftover confirm or name modals from a previous session | Added `_hideConfirmModal()` and `_hideNameModal()` calls at the start of `_showFileBrowserModal()` |
| Cmd+K / Ctrl+K voice shortcut conflicts with AI Edit shortcut | Global keydown handler in `audio_process.js` for voice recording intercepted Cmd+K even when the file browser was open | Added guard `if ($('#file-browser-modal').hasClass('show')) return;` in the `audio_process.js` keydown handler |
| CodeMirror editor container remained visible behind PDF and WYSIWYG views | `_showView()` set `display` on preview/wysiwyg/pdf/empty containers but never set `edEl.style.display`, so the CodeMirror `<div>` stayed `block` underneath other views | Added `edEl.style.display = (view === 'editor') ? 'block' : 'none'` as the first display assignment in `_showView()` |
| Responsive view-mode select never appeared on narrow screens | `<select id="file-browser-view-select">` had `style="display:none;"` hardcoded as an inline style, which the CSS media-query rule could not override | Removed `display:none` from the inline `style` attribute; visibility is now controlled entirely by the CSS `@media (min-width: 576px)` rule |
| EasyMDE intercepted Ctrl+S in WYSIWYG mode instead of saving the file | EasyMDE registers internal key bindings that fire before the global `keydown` handler calling `saveFile()` | Added `shortcuts: { toggleSideBySide: null, toggleFullScreen: null }` to the EasyMDE config to null out conflicting default bindings |
| Tab bar re-appears after loading a new file even when sidebar is collapsed | `_doLoadFile()` called `$('#file-browser-tab-bar').show()` unconditionally for markdown files, ignoring `state.sidebarVisible`. Toggling the sidebar hid the tab bar, but loading a new markdown file immediately re-showed it | Added `if (state.sidebarVisible)` guard around the `.show()` call in `_doLoadFile()`. `_toggleSidebar()` is the single authority for sidebar-coupled visibility; `_doLoadFile()` now defers to it |
| Toolbar button text (Wrap, AI Edit, Discard, Save) visible on narrow screens, wasting horizontal space | Button labels were plain text nodes always rendered | Wrapped each label in `<span class="d-none d-sm-inline">` — icons only on screens <576 px, icon + label on ≥576 px. `title` attributes preserved for hover tooltips at all sizes |
| Cannot move item to root directory via move modal | `_loadMoveTree('.')` only rendered sub-folders — there was no selectable item representing `/` (root) itself | Prepended a `<div class="fb-move-dir-item fb-move-root-item" data-path=".">` with `bi-house-door` icon and `/ (root)` label above the sub-folder tree in `_showMoveModal()`; `_isValidMoveTarget` and `_joinPath` already handled `'.'` correctly |
| Cannot move item to root directory via drag-and-drop | The `drop` handler was only bound on `li[data-type=dir]` items — dropping onto the tree background (where root has no `<li>`) had no handler | Added `dragover` / `dragleave` / `drop` handlers on `#file-browser-tree` container; a guard `if ($(e.target).closest('li').length) return` prevents double-firing when dropping on an `<li>`; `_joinPath('.', basename)` constructs the new root-level path |
