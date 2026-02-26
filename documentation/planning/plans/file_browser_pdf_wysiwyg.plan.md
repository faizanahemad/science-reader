# File Browser: PDF Viewer + WYSIWYG Markdown Editor

## Goal

Extend the existing File Browser modal with two new capabilities:

1. **PDF Viewing** — when a `.pdf` file is selected in the tree, show it rendered in-browser using the already-bundled PDF.js viewer, replacing the current "binary file" message.
2. **WYSIWYG Markdown Editing** — add a third view mode (alongside existing Raw/Preview) for markdown files, allowing rich-text in-browser editing using EasyMDE, embedded inline in the file browser panel. The view-mode selector is a responsive dropdown on narrow screens and a button group on wide screens.

---

## Requirements

### Functional — PDF Viewing

1. Clicking a `.pdf` file in the tree loads and displays it using the PDF.js iframe viewer.
2. PDF is fetched via a new Flask endpoint `/file-browser/serve?path=...` that streams raw bytes with correct MIME type (`application/pdf`), without forcing a download attachment header.
3. During load, a scoped progress bar (`#fb-pdf-progress`) shows download percentage or bytes downloaded.
4. Once loaded, the PDF.js iframe fills the viewer area.
5. Toolbar state for PDF files:
   - **Disabled**: Save, Discard, AI Edit, Word Wrap (not applicable to PDF)
   - **Active**: Download (downloads the PDF), Upload (unchanged)
6. The tab bar / view-mode selector is hidden for PDF files.
7. Closing or navigating to a different file destroys the PDF blob URL to free memory.
8. The `/file-browser/serve` endpoint is sandboxed to the server root (same `_safe_resolve()` as all other endpoints) and requires `@login_required`.

### Functional — WYSIWYG Markdown Editing

1. For `.md` / `.markdown` files, the view-mode selector shows three options: **Raw**, **Preview**, **WYSIWYG**.
2. **Raw** — existing CodeMirror editor (unchanged).
3. **Preview** — existing rendered HTML preview (unchanged).
4. **WYSIWYG** — EasyMDE embedded inline inside `#file-browser-wysiwyg-container`, filling the editor area.
5. Switching **Raw → WYSIWYG**: current CodeMirror content is read and set into EasyMDE.
6. Switching **WYSIWYG → Raw**: current EasyMDE content is read back and set into CodeMirror (source of truth), then EasyMDE is hidden.
7. Switching **WYSIWYG → Preview**: sync WYSIWYG → CodeMirror first, then render preview.
8. **Save while in WYSIWYG mode**: sync EasyMDE → CodeMirror, then call normal `_saveFile()`.
9. Dirty tracking: changes made in EasyMDE mark `state.isDirty = true` the same way CodeMirror changes do.
10. AI Edit: disabled (button greyed) when in WYSIWYG mode (AI Edit only operates on the CodeMirror buffer).
11. Word Wrap button: disabled/hidden when in WYSIWYG mode (EasyMDE handles its own wrapping).
12. EasyMDE toolbar: bold, italic, heading, quote, code, ul, ol, link, image, table, undo, redo — standard subset.
13. EasyMDE `previewRender` uses the project's `marked.js` (already loaded globally).
14. EasyMDE instance is created lazily on first WYSIWYG switch and reused thereafter (same pattern as CodeMirror).
15. On file close or navigation to a different file, EasyMDE is cleared but not destroyed (reuse on next WYSIWYG open).

### Responsive View-Mode Selector

1. On **wide screens** (≥ 576 px / Bootstrap `sm` breakpoint): the current Code/Preview tab bar (`#file-browser-tab-bar`) becomes a button group with three buttons: Raw | Preview | WYSIWYG (shown only for markdown).
2. On **narrow screens** (< 576 px): replace the tab bar with a `<select>` dropdown containing the same three options.
3. Implementation: a single `#file-browser-view-select` `<select>` (always in DOM) is shown on narrow screens; a button group `#file-browser-tab-bar` is shown on wide screens. Both are driven by the same `_setViewMode(mode)` function. Media-query CSS handles visibility.
4. For non-markdown, non-PDF files: both controls are hidden (same as current behaviour for Code tab bar).

---

## Architecture / Design Decisions

### PDF: New Flask `/file-browser/serve` endpoint

The existing `/file-browser/download` endpoint uses `as_attachment=True` which forces a browser download and does not work for inline XHR blob-fetch by PDF.js. A new endpoint `/file-browser/serve` is needed with `as_attachment=False` (inline) so the file can be fetched as a blob and rendered by PDF.js.

Both endpoints share the same `_safe_resolve()` path-security check. The serve endpoint auto-detects MIME type via `mimetypes.guess_type()`, defaulting to `application/octet-stream`.

### PDF: Scoped progress elements

The existing `showPDF()` in `common.js` looks up `#progress`, `#progressbar`, `#progress-status` globally (not scoped). Rather than calling `showPDF()` directly, the file browser implements its own `_loadFilePDF(filePath)` function that:
- Is a near-copy of `showPDF()` logic
- Scopes all element lookups to `#file-browser-pdf-container` via `document.querySelector` relative to that container
- Cleans up the previous blob URL on each new load

### WYSIWYG: EasyMDE embedded inline

`MarkdownEditorManager` (used by chat cards) opens a separate modal. For the file browser we want inline embedding. We create a fresh EasyMDE instance inside `#file-browser-wysiwyg-container` using the same options as `MarkdownEditorManager.initEasyMDE()`.

**Source of truth**: CodeMirror always holds the canonical markdown content. WYSIWYG is a view into it. Before any save, close, AI edit, or view switch away from WYSIWYG, we sync EasyMDE → CodeMirror.

### State additions

```javascript
state.isPdf      = false;   // Whether current file is a PDF
state.viewMode   = 'raw';   // 'raw' | 'preview' | 'wysiwyg' (for markdown files)
state.fbEasyMDE  = null;    // EasyMDE instance (created lazily, persisted)
state.pdfBlobUrl = null;    // Current PDF blob URL (for cleanup on file change)
```

### Toolbar button enable/disable by view and file type

| Button      | PDF    | Markdown-Raw | Markdown-Preview | Markdown-WYSIWYG | Other text |
|-------------|--------|--------------|------------------|------------------|------------|
| Save        | off    | on           | on               | on (sync first)  | on         |
| Discard     | off    | on           | on               | on (sync first)  | on         |
| AI Edit     | off    | on           | on               | off              | on         |
| Word Wrap   | off    | on           | off              | off              | on         |
| Download    | on     | on           | on               | on               | on         |
| Upload      | on     | on           | on               | on               | on         |

---

## Implementation Plan

### Task 1 — Flask endpoint: `/file-browser/serve`

**File**: `endpoints/file_browser.py`

1. Add import `import mimetypes` at the top (if not already present).
2. After the `download_file()` function, add a new route:

```python
@file_browser_bp.route("/file-browser/serve", methods=["GET"])
@login_required
def serve_file():
    """Serve a file inline (for in-browser viewing, e.g. PDF).
    Uses send_file with as_attachment=False so the browser renders it inline.
    Path is sandboxed to server root via _safe_resolve().
    """
    rel_path = request.args.get("path", "")
    if not rel_path:
        return json_error("Missing 'path' parameter", status=400, code="missing_param")
    resolved = _safe_resolve(rel_path)
    if resolved is None:
        return json_error("Path escapes server root", status=403, code="path_forbidden")
    if not os.path.isfile(resolved):
        return json_error("File not found", status=404, code="not_found")
    mime, _ = mimetypes.guess_type(resolved)
    mime = mime or "application/octet-stream"
    try:
        return send_file(resolved, mimetype=mime, as_attachment=False)
    except OSError:
        logger.exception("Failed to serve file: %s", resolved)
        return json_error("Failed to serve file", status=500, code="os_error")
```

**Risks**: None. Identical security model to `download_file()`.

---

### Task 2 — HTML: PDF container and view-mode selector

**File**: `interface/interface.html`

#### 2a — View-mode selector (replaces/extends current tab bar)

Find `#file-browser-tab-bar`. Replace with:

```html
<!-- View mode: button group (wide screens) + select (narrow screens) -->
<div id="file-browser-tab-bar" class="d-none">
  <!-- Button group shown on sm+ screens -->
  <div id="fb-view-btngroup" class="btn-group btn-group-sm d-none d-sm-inline-flex" role="group">
    <button type="button" class="btn btn-outline-secondary active" data-view="raw">Raw</button>
    <button type="button" class="btn btn-outline-secondary" data-view="preview">Preview</button>
    <button type="button" class="btn btn-outline-secondary" data-view="wysiwyg">WYSIWYG</button>
  </div>
  <!-- Select shown on xs screens only -->
  <select id="file-browser-view-select" class="form-control form-control-sm d-sm-none" style="width:auto;display:inline-block;">
    <option value="raw">Raw</option>
    <option value="preview">Preview</option>
    <option value="wysiwyg">WYSIWYG</option>
  </select>
</div>
```

#### 2b — WYSIWYG container (alongside editor/preview containers)

Inside `#file-browser-editor-wrapper`, after `#file-browser-preview-container`, add:

```html
<div id="file-browser-wysiwyg-container" style="display:none; flex:1; overflow:auto;"></div>
```

#### 2c — PDF container (alongside the others)

Inside `#file-browser-editor-wrapper`, after WYSIWYG container:

```html
<div id="file-browser-pdf-container" style="display:none; flex:1; flex-direction:column; overflow:hidden;">
  <!-- Progress indicator (shown during PDF load) -->
  <div id="fb-pdf-progress" style="display:none; padding: 4px 8px;">
    <div class="progress" style="height:6px;">
      <div id="fb-pdf-progressbar" class="progress-bar" role="progressbar" style="width:0%;"></div>
    </div>
    <small id="fb-pdf-progress-status" class="text-muted"></small>
  </div>
  <!-- PDF.js iframe -->
  <iframe id="fb-pdfjs-viewer"
          src="/interface/pdf.js/web/viewer.html"
          data-original-src="/interface/pdf.js/web/viewer.html"
          style="display:none; flex:1; border:none; width:100%; height:100%;"
          allowfullscreen webkitallowfullscreen>
  </iframe>
</div>
```

**Risks**: Existing layout must not break. The new containers are hidden by default (`display:none`) and follow the existing pattern. The `#file-browser-editor-wrapper` must use `display:flex; flex-direction:column` (verify in CSS).

---

### Task 3 — JS: PDF viewing in `file-browser-manager.js`

**File**: `interface/file-browser-manager.js`

#### 3a — State additions (in the `state` object near top of file)

```javascript
isPdf: false,
pdfBlobUrl: null,
viewMode: 'raw',
fbEasyMDE: null,
```

#### 3b — Extend `_showView()` function

Add `'pdf'` and `'wysiwyg'` cases:

```javascript
function _showView(view, messageHtml) {
    var edEl = document.getElementById('file-browser-editor-container');
    var prEl = document.getElementById('file-browser-preview-container');
    var wyEl = document.getElementById('file-browser-wysiwyg-container');
    var pdEl = document.getElementById('file-browser-pdf-container');
    var emEl = document.getElementById('file-browser-empty-state');

    edEl.style.display = (view === 'editor')  ? 'block' : 'none';
    prEl.style.display = (view === 'preview') ? 'block' : 'none';
    wyEl.style.display = (view === 'wysiwyg') ? 'flex'  : 'none';
    pdEl.style.display = (view === 'pdf')     ? 'flex'  : 'none';
    emEl.style.display = (view === 'empty' || view === 'message') ? 'flex' : 'none';

    if (view === 'message' && messageHtml) {
        emEl.innerHTML = '<div class="text-center text-muted">' + messageHtml + '</div>';
    }
}
```

#### 3c — `_loadFilePDF(filePath)` — new function

```javascript
function _loadFilePDF(filePath) {
    var container = document.getElementById('file-browser-pdf-container');
    var progressWrap = document.getElementById('fb-pdf-progress');
    var progressBar  = document.getElementById('fb-pdf-progressbar');
    var progressStatus = document.getElementById('fb-pdf-progress-status');
    var viewer = document.getElementById('fb-pdfjs-viewer');

    // Reset
    progressBar.style.width = '0%';
    progressStatus.textContent = '';
    viewer.style.display = 'none';
    progressWrap.style.display = 'block';

    // Revoke previous blob URL to free memory
    if (state.pdfBlobUrl) {
        URL.revokeObjectURL(state.pdfBlobUrl);
        state.pdfBlobUrl = null;
    }

    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/file-browser/serve?path=' + encodeURIComponent(filePath), true);
    xhr.responseType = 'blob';

    xhr.onprogress = function(e) {
        if (e.lengthComputable) {
            var pct = (e.loaded / e.total) * 100;
            progressBar.style.width = pct + '%';
            progressStatus.textContent = 'Downloaded ' + (e.loaded / 1024).toFixed(1) + ' / ' + (e.total / 1024).toFixed(1) + ' KB (' + Math.round(pct) + '%)';
        } else {
            progressStatus.textContent = 'Downloaded ' + (e.loaded / 1024).toFixed(1) + ' KB';
        }
    };

    xhr.onload = function() {
        if (this.status === 200) {
            state.pdfBlobUrl = URL.createObjectURL(this.response);
            var originalSrc = viewer.getAttribute('data-original-src');
            viewer.setAttribute('src', originalSrc + '?file=' + encodeURIComponent(state.pdfBlobUrl));
            viewer.style.display = 'block';
            progressWrap.style.display = 'none';
        } else {
            progressWrap.style.display = 'none';
            _showView('message', '<i class="bi bi-exclamation-triangle" style="font-size:2rem;"></i><p class="mt-2">Failed to load PDF (HTTP ' + this.status + ')</p>');
        }
    };

    xhr.onerror = function() {
        progressWrap.style.display = 'none';
        _showView('message', '<i class="bi bi-exclamation-triangle" style="font-size:2rem;"></i><p class="mt-2">Network error loading PDF</p>');
    };

    xhr.send();
}
```

#### 3d — Extend `_doLoadFile()` to branch on PDF

In the `_doLoadFile()` function, after the binary/too-large guards and before the CodeMirror setup block, add:

```javascript
// PDF files — render with PDF.js
if (ext === '.pdf') {
    state.isPdf = true;
    state.isMarkdown = false;
    state.viewMode = 'raw';
    // Update toolbar state
    _updateToolbarForFileType();
    $('#file-browser-tab-bar').hide();
    _showView('pdf');
    _loadFilePDF(filePath);
    // Update address bar, tree highlight, etc. (same as text files)
    return;
}
state.isPdf = false;
```

#### 3e — `_updateToolbarForFileType()` — new helper

Enables/disables toolbar buttons based on current file type and view mode:

```javascript
function _updateToolbarForFileType() {
    var isPdf = state.isPdf;
    var isWysiwyg = (state.viewMode === 'wysiwyg');

    // Save / Discard
    $('#file-browser-save-btn').prop('disabled', isPdf);
    $('#file-browser-discard-btn').prop('disabled', isPdf);

    // AI Edit
    $('#file-browser-ai-edit-btn').prop('disabled', isPdf || isWysiwyg);

    // Word Wrap
    $('#file-browser-wrap-btn').prop('disabled', isPdf || isWysiwyg);
}
```

Call this from: `_doLoadFile()` after detecting file type, and from `_setViewMode()` after switching mode.

#### 3f — PDF blob URL cleanup

In `_closeModal()` and at the start of `_doLoadFile()`:

```javascript
if (state.pdfBlobUrl) {
    URL.revokeObjectURL(state.pdfBlobUrl);
    state.pdfBlobUrl = null;
}
```

---

### Task 4 — JS: WYSIWYG (EasyMDE) in `file-browser-manager.js`

#### 4a — `_setViewMode(mode)` — new central view-mode switcher

```javascript
function _setViewMode(mode) {
    // Before leaving WYSIWYG, sync content back to CodeMirror
    if (state.viewMode === 'wysiwyg' && mode !== 'wysiwyg') {
        _syncWysiwygToCodeMirror();
    }

    state.viewMode = mode;

    // Update button group active state
    $('#fb-view-btngroup .btn').removeClass('active');
    $('#fb-view-btngroup .btn[data-view="' + mode + '"]').addClass('active');
    // Update select value
    $('#file-browser-view-select').val(mode);

    if (mode === 'raw') {
        _showView('editor');
        setTimeout(function() { if (state.cmEditor) state.cmEditor.refresh(); }, 10);
    } else if (mode === 'preview') {
        _renderPreview();
        _showView('preview');
    } else if (mode === 'wysiwyg') {
        _showView('wysiwyg');
        _initOrRefreshEasyMDE();
    }

    _updateToolbarForFileType();
}
```

#### 4b — Event wiring for new tab bar and select

```javascript
// Button group (wide screens)
$(document).on('click', '#fb-view-btngroup .btn', function() {
    var mode = $(this).attr('data-view');
    _setViewMode(mode);
});

// Select (narrow screens)
$(document).on('change', '#file-browser-view-select', function() {
    _setViewMode($(this).val());
});
```

Replace the old `$('#file-browser-tab-bar').on('click', '.btn', ...)` handler with `_setViewMode()` calls (for backward compat, keep the old `data-tab` event and translate: `'code' → 'raw'`, `'preview' → 'preview'`).

#### 4c — `_initOrRefreshEasyMDE()` — lazy init + content sync

```javascript
function _initOrRefreshEasyMDE() {
    var content = state.cmEditor ? state.cmEditor.getValue() : '';
    var container = document.getElementById('file-browser-wysiwyg-container');

    if (!state.fbEasyMDE) {
        // Create textarea for EasyMDE to attach to
        var ta = document.createElement('textarea');
        ta.id = 'fb-easymde-textarea';
        container.appendChild(ta);

        state.fbEasyMDE = new EasyMDE({
            element: ta,
            spellChecker: false,
            autofocus: false,
            status: false,
            minHeight: '300px',
            toolbar: [
                'bold', 'italic', 'heading', '|',
                'quote', 'code', 'unordered-list', 'ordered-list', '|',
                'link', 'image', 'table', '|',
                'undo', 'redo'
            ],
            previewRender: function(plainText) {
                if (typeof marked !== 'undefined') {
                    return marked.parse ? marked.parse(plainText) : marked(plainText);
                }
                return plainText;
            }
        });

        // Dirty tracking
        state.fbEasyMDE.codemirror.on('change', function() {
            if (!state.isDirty) {
                state.isDirty = true;
                _updateDirtyIndicator();
            }
        });
    }

    state.fbEasyMDE.value(content);
    setTimeout(function() {
        state.fbEasyMDE.codemirror.refresh();
    }, 50);
}
```

#### 4d — `_syncWysiwygToCodeMirror()` — sync before save/switch

```javascript
function _syncWysiwygToCodeMirror() {
    if (state.fbEasyMDE && state.cmEditor) {
        var content = state.fbEasyMDE.value();
        state.cmEditor.setValue(content);
    }
}
```

#### 4e — Patch `_saveFile()` to sync WYSIWYG first

At the top of `_saveFile()` (or `_doSave()`):

```javascript
if (state.viewMode === 'wysiwyg') {
    _syncWysiwygToCodeMirror();
}
```

#### 4f — Show/hide tab bar for markdown vs other file types

In `_doLoadFile()`, after setting `state.isMarkdown`:

```javascript
if (state.isMarkdown) {
    // Reset to Raw when loading a new markdown file
    state.viewMode = 'raw';
    $('#fb-view-btngroup .btn').removeClass('active');
    $('#fb-view-btngroup .btn[data-view="raw"]').addClass('active');
    $('#file-browser-view-select').val('raw');
    $('#file-browser-tab-bar').show();
} else {
    $('#file-browser-tab-bar').hide();
}
```

#### 4g — Clear EasyMDE on file navigation

When loading a new file (not destroying instance, just clear content to avoid stale state):

```javascript
if (state.fbEasyMDE) {
    state.fbEasyMDE.value('');
}
```

---

### Task 5 — CSS additions

**File**: `interface/style.css`

```css
/* File browser WYSIWYG container — EasyMDE fills the area */
#file-browser-wysiwyg-container {
    flex: 1;
    overflow: auto;
    display: flex;
    flex-direction: column;
}
#file-browser-wysiwyg-container .EasyMDEContainer {
    flex: 1;
    display: flex;
    flex-direction: column;
}
#file-browser-wysiwyg-container .CodeMirror {
    flex: 1;
    height: 100%;
}

/* File browser PDF container */
#file-browser-pdf-container {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
#fb-pdfjs-viewer {
    flex: 1;
    width: 100%;
    border: none;
}

/* View mode selector responsive behaviour */
/* On xs: hide button group, show select */
#fb-view-btngroup { display: none; }
@media (min-width: 576px) {
    #fb-view-btngroup { display: inline-flex !important; }
    #file-browser-view-select { display: none !important; }
}
```

---

### Task 6 — Service worker + cache bump

**File**: `interface/service-worker.js`

- Increment `CACHE_VERSION` by 1.
- Ensure `file-browser-manager.js` is in the precache list (it already is).

**File**: `interface/interface.html`

- Bump `?v=N` on the `<script src="file-browser-manager.js?v=N">` tag.

---

### Task 7 — Update feature documentation

**File**: `documentation/features/file_browser/README.md`

Add:
- PDF Viewer section under Features list
- WYSIWYG section under Features list
- API table: new `/file-browser/serve` endpoint
- UI Details: view-mode selector behaviour
- Implementation Notes: new functions, state fields, files modified

---

## Alternatives Considered

### Alternative: Reuse `showPDF()` from `common.js`

Rejected because `showPDF()` looks up `#progress`, `#progressbar`, `#progress-status` globally (not scoped to a subtree). Calling it from the file browser would either interfere with other progress bars on the page or require hacking the DOM. A local `_loadFilePDF()` copy scoped to `#file-browser-pdf-container` is cleaner.

### Alternative: WYSIWYG via `MarkdownEditorManager.openEditor()` (modal)

Rejected by user — the requirement is inline editing within the file browser panel, not a separate modal. Inline EasyMDE gives a better editing experience without context switching.

### Alternative: ContentEditable WYSIWYG (existing in markdown-editor.js)

EasyMDE is preferred because:
- Already loaded on the page (CDN in interface.html)
- Has a proper toolbar with all common markdown formatting actions
- Uses CodeMirror internally — consistent look/feel with the raw editor
- Handles large documents better than contenteditable

### Alternative: Side-by-side live preview

Not requested. The three-mode switcher (Raw / Preview / WYSIWYG) achieves the same goals with lower complexity. Live side-by-side would require splitting the editor area and handling sync on every keystroke.

---

## Possible Challenges

1. **EasyMDE height inside flex container**: EasyMDE renders a CodeMirror instance that may not naturally fill its container. Requires CSS overrides for `.EasyMDEContainer`, `.CodeMirror`, and `textarea` to use `flex:1; height:100%`. May need a `codemirror.refresh()` call after the container becomes visible.

2. **PDF.js iframe height**: The iframe must fill the full remaining height of `#file-browser-pdf-container`. Since the container is `display:flex; flex-direction:column`, the iframe needs `flex:1`. Test that this works on both desktop and mobile.

3. **Blob URL lifecycle**: If a user opens many PDFs without closing the modal, blob URLs accumulate in memory. The cleanup in `_loadFilePDF()` and `_closeModal()` handles this, but test with repeated file switching.

4. **Save/Discard in WYSIWYG mode**: The WYSIWYG → CodeMirror sync (`_syncWysiwygToCodeMirror()`) must be called before `_saveFile()` fetches the editor value. The existing `_saveFile()` reads from `state.cmEditor.getValue()`, so the sync must happen first.

5. **Tab bar state reset on file navigation**: When navigating from a markdown file to a non-markdown file and back, the `viewMode` must reset to `'raw'` and the button group active state must be correct. Test: open `.md` → switch to WYSIWYG → click `.py` → click `.md` again → should be in Raw mode.

6. **Keyboard shortcuts in WYSIWYG mode**: EasyMDE may intercept `Ctrl+S`. Add an EasyMDE keyboard shortcut override or bind the `keydown` event on the EasyMDE container to call `_saveFile()` on `Ctrl+S`/`Cmd+S`.

7. **Cmd+K conflict in WYSIWYG mode**: AI Edit is disabled in WYSIWYG mode, but `Cmd+K` keydown handler in `file-browser-manager.js` must also check `state.viewMode !== 'wysiwyg'` before showing the AI Edit modal.

---

## Granular Task List (Junior Dev Checklist)

- [ ] **T1** `endpoints/file_browser.py` — add `import mimetypes`, add `serve_file()` route at bottom
- [ ] **T2a** `interface/interface.html` — find `#file-browser-tab-bar`, replace with new responsive view-mode selector HTML (button group + select)
- [ ] **T2b** `interface/interface.html` — add `#file-browser-wysiwyg-container` inside `#file-browser-editor-wrapper`
- [ ] **T2c** `interface/interface.html` — add `#file-browser-pdf-container` (with iframe + progress bar) inside `#file-browser-editor-wrapper`
- [ ] **T3a** `file-browser-manager.js` — add `isPdf`, `pdfBlobUrl`, `viewMode`, `fbEasyMDE` to `state` object
- [ ] **T3b** `file-browser-manager.js` — extend `_showView()` with `'wysiwyg'` and `'pdf'` cases
- [ ] **T3c** `file-browser-manager.js` — add `_loadFilePDF(filePath)` function
- [ ] **T3d** `file-browser-manager.js` — extend `_doLoadFile()` with PDF branch (return early for `.pdf`)
- [ ] **T3e** `file-browser-manager.js` — add `_updateToolbarForFileType()`, call from `_doLoadFile()` and `_setViewMode()`
- [ ] **T3f** `file-browser-manager.js` — add blob URL cleanup in `_closeModal()` and `_doLoadFile()`
- [ ] **T4a** `file-browser-manager.js` — add `_setViewMode(mode)` function
- [ ] **T4b** `file-browser-manager.js` — wire `#fb-view-btngroup` click and `#file-browser-view-select` change events
- [ ] **T4c** `file-browser-manager.js` — add `_initOrRefreshEasyMDE()` with lazy init, content sync, dirty tracking
- [ ] **T4d** `file-browser-manager.js` — add `_syncWysiwygToCodeMirror()`
- [ ] **T4e** `file-browser-manager.js` — patch `_saveFile()` to call `_syncWysiwygToCodeMirror()` first
- [ ] **T4f** `file-browser-manager.js` — patch `_doLoadFile()` to reset view mode + tab bar on markdown file load
- [ ] **T4g** `file-browser-manager.js` — clear EasyMDE content on new file navigation
- [ ] **T4h** `file-browser-manager.js` — patch `Cmd+K` handler to guard against WYSIWYG mode
- [ ] **T4i** `file-browser-manager.js` — add `Ctrl+S`/`Cmd+S` handler inside EasyMDE (or global keydown guard)
- [ ] **T5** `interface/style.css` — add CSS for WYSIWYG container, PDF container, responsive view-mode selector
- [ ] **T6** `interface/service-worker.js` + `interface/interface.html` — bump CACHE_VERSION and `?v=N`
- [ ] **T7** `documentation/features/file_browser/README.md` — update with new features

---

## Files Modified

| File | Change |
|------|--------|
| `endpoints/file_browser.py` | Add `serve_file()` route |
| `interface/interface.html` | Replace tab bar HTML; add WYSIWYG container; add PDF container; bump `?v=N` |
| `interface/file-browser-manager.js` | State additions; `_showView()` extension; `_loadFilePDF()`; `_setViewMode()`; `_initOrRefreshEasyMDE()`; `_syncWysiwygToCodeMirror()`; `_updateToolbarForFileType()`; event wiring; guards in save/Cmd+K |
| `interface/style.css` | CSS for WYSIWYG, PDF, responsive selector |
| `interface/service-worker.js` | Bump `CACHE_VERSION` |
| `documentation/features/file_browser/README.md` | New sections for PDF + WYSIWYG |
