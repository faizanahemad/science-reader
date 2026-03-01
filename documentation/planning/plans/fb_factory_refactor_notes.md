# File Browser Factory Refactor — Change Notes

## What We Were Trying To Build

The goal was to fix three bugs reported by the user:

1. **File browser address bar not editable** — The address bar appeared unresponsive when the file browser was opened from the Settings modal after previously being configured by the Global Docs manager.
2. **File browser opened from Settings showed the Global Docs folder** — Opening the file browser from Settings (Actions tab) after it had been opened from Global Docs still showed the `storage/global_docs/...` directory from the previous session, because both entry points shared the same singleton.
3. **PDF files showed binary content instead of the PDF viewer** — Clicking a `.pdf` file in the tree showed "Binary file — cannot edit" instead of rendering the inline PDF.js viewer.

---

## Root Causes

### Bug 1 & 2: Shared singleton state between Settings and Global Docs

`FileBrowserManager` was an IIFE (Immediately Invoked Function Expression) — a singleton with exactly one `state` object and one `_config` object in memory:

```javascript
var FileBrowserManager = (function () {
    var _config = { ... };   // ONE shared config
    var state   = { ... };   // ONE shared state
    ...
    return { init, open, configure };
})();
```

`GlobalDocsManager` called `FileBrowserManager.configure({ rootPath, onMove, onDelete })` before opening the browser. This mutated the singleton's `_config` permanently. When the user later opened the file browser from Settings, it still had the Global Docs `rootPath` and the Global Docs `onMove`/`onDelete` callbacks — meaning:
- The tree showed `storage/global_docs/...` instead of the server root
- Move/delete operations in the Settings context went to the Global Docs API instead of the default file-browser API
- The address bar "not editable" was actually the state bleed from the `readOnly` or `showAddressBar` flags being set for one context and carrying over

### Bug 3: PDF binary early-return order

In `_doLoadFile`, the code flow was:

```
1. Fetch /file-browser/read
2. if (resp.is_binary) → show "Binary file" message, RETURN EARLY   ← PDFs hit this (null bytes)
3. ...
4. if (ext === '.pdf') → load PDF.js viewer                          ← never reached for PDFs
```

PDF files contain null bytes so `is_binary` was `true`, causing the early return before the `.pdf` extension check.

---

## Why We Decided To Make These Changes

**Option considered: context save/restore** — Before Global Docs opens, snapshot `_config` + `state`; restore when it closes. Rejected: fragile, doesn't handle the case where both are open simultaneously, hard to keep in sync.

**Option considered: reset() + re-init per open** — Add a `reset()` method. Rejected: loses Settings state (expanded dirs, current file) when switching contexts and back.

**Option chosen: factory pattern** — `createFileBrowser(instanceId, cfg)` creates a completely independent instance with its own DOM, `state`, and `_config` per call. This is the cleanest solution: no shared state, each embedding has full isolation, and both instances can coexist.

---

## Files Changed and Exact Changes

### 1. `interface/file-browser-manager.js`

**Change summary:** IIFE singleton → factory function. All 66 hardcoded `$('#fb-*')` selectors → `_$('keyName')` abstraction calls. `_config.dom` keys changed from static strings to `instanceId + '-keyName'` expressions. PDF check moved before binary check.

**Specific changes:**

**Lines 18–19 (opening):**
- Before: `var FileBrowserManager = (function () { 'use strict';`
- After: `function createFileBrowser(instanceId, initialCfg) { 'use strict'; ... (DOM clone block)`

The IIFE wrapper is replaced with a named factory function. An immediately-invoked `_mountDom()` closure at the top of the factory:
- Gets `<template id="file-browser-modal-template">` from the DOM
- Clones it with `cloneNode(true)`
- Walks all `[data-fb-key]` elements and assigns `id = instanceId + '-' + key`
- Walks all `[data-fb-for]` label elements and sets `for = instanceId + '-' + key`
- Appends the cloned fragment to `document.body`

**Lines 85–175 (`_config.dom` block):**
- Before: All 52 DOM keys hardcoded to static strings like `'file-browser-modal'`, `'fb-view-btngroup'`, etc.
- After: All 52 keys use `instanceId + '-keyName'` expressions (e.g. `instanceId + '-modal'`, `instanceId + '-viewBtnGroup'`)
- **Added**: 34 new keys for upload, move, AI edit, and PDF sub-modal elements that were previously hardcoded `$('#fb-*')` selectors but not in `_config.dom`:
  - Upload: `uploadDirHint`, `uploadFilename`, `uploadProgressWrap`, `uploadProgressBar`, `uploadProgressText`, `uploadSubmitBtn`, `uploadSpinner`, `uploadInput`, `uploadCancelBtn`, `uploadCloseBtn`, `uploadBrowseLink`, `uploadDropzone`
  - Move: `moveOkBtn`, `moveSrcName`, `moveDestHint`, `moveFolderTree`, `moveCancelBtn`
  - AI Edit: `aiEditInfo`, `aiEditIncludeSummary`, `aiEditIncludeMessages`, `aiEditIncludeMemory`, `aiEditDeepContext`, `aiEditHistoryCount`, `aiEditInstruction`, `aiEditSpinner`, `aiEditGenerate`, `aiEditCancel`, `aiDiffAccept`, `aiDiffReject`, `aiDiffEdit`, `aiDiffContent`
  - PDF: `pdfProgress`, `pdfProgressBar`, `pdfProgressStatus`, `pdfjsViewer`

**Lines ~430 (`_loadFilePDF`):**
- Before: `document.getElementById('fb-pdf-progress')` × 4 hardcoded calls
- After: `document.getElementById(_config.dom.pdfProgress || 'fb-pdf-progress')` × 4 (uses config key)

**Lines ~1108–1157 (`_doLoadFile` ordering fix):**
- Before order: `is_binary` check → `too_large` check → `.pdf` check
- After order: `.pdf` check → `is_binary` check → `too_large` check
- PDFs are binary so they were caught by `is_binary` before `.pdf` was ever evaluated

**Lines ~1177 (view button group selector):**
- Before: `$('#fb-view-btngroup .btn[data-view="raw"]').addClass('active')`
- After: `_$('viewBtnGroup').find('.btn[data-view="raw"]').addClass('active')`

**Lines ~1430–1499 (move modal functions):** 12 `$('#fb-move-*')` → `_$('move*')` calls

**Lines ~2065–2219 (AI edit functions):** 18 `$('#fb-ai-edit-*')` / `$('#fb-ai-diff-*')` → `_$('aiEdit*')` / `_$('aiDiff*')` calls

**Lines ~2306–2466 (upload functions and event bindings):** 24 `$('#fb-upload-*')` → `_$('upload*')` calls; multi-selector `$('#fb-upload-close, #fb-upload-cancel-btn')` → `_$('uploadCloseBtn').add(_$('uploadCancelBtn'))`

**Lines ~2574–2611 (AI edit event bindings):** 6 `$('#fb-ai-*')` → `_$('aiEdit*')` / `_$('aiDiff*')` calls

**Lines 2896–2950 (closing):**
- Before: `})();` IIFE close + `$(document).ready(function() { FileBrowserManager.init(); })`
- After:
  ```javascript
  // Apply initialCfg overrides
  if (initialCfg) { $.extend(true, _config, initialCfg); }
  return { init, open, loadFile, saveFile, discardChanges, configure };
  }   // end createFileBrowser

  window.createFileBrowser = createFileBrowser;

  $(document).ready(function () {
      window.FileBrowserManager = createFileBrowser('fb');
      _wirePrimaryOpenButton();
      window.FileBrowserManager.init();
  });

  function _wirePrimaryOpenButton() {
      document.addEventListener('click', function(event) {
          var button = event.target.closest('#settings-file-browser-modal-open-button');
          if (!button) return;
          event.preventDefault();
          if (window.FileBrowserManager && ...) window.FileBrowserManager.open();
      });
  }
  ```

---

### 2. `interface/interface.html`

**Change summary:** All file browser HTML (the main modal + 7 sub-modals/overlays, lines 2684–2942) moved into a `<template id="file-browser-modal-template">`. All static `id="file-browser-*"` and `id="fb-*"` attributes replaced with `data-fb-key="keyName"`. All `for="fb-*"` label attributes replaced with `data-fb-for="keyName"`. Static fallback click handler block removed (now in JS). Script version bumped `?v=26` → `?v=27`.

**Before (excerpt):**
```html
<!-- ═══ File Browser Modal ═══ -->
<div id="file-browser-modal" tabindex="-1" ...>
  ...
  <input id="file-browser-address-bar" ...>
  <div id="fb-view-btngroup" ...>
  ...
  <div id="fb-upload-submit-btn" ...>
  ...
</div>
<div id="file-browser-context-menu" ...>
...
<div id="file-browser-ai-diff-modal" ...>
  <div id="fb-ai-diff-content" ...>
```

**After (excerpt):**
```html
<template id="file-browser-modal-template">
<div data-fb-key="modal" tabindex="-1" ...>
  ...
  <input data-fb-key="addressBar" ...>
  <div data-fb-key="viewBtnGroup" ...>
  ...
  <button data-fb-key="uploadSubmitBtn" ...>
  ...
</div>
<div data-fb-key="contextMenu" ...>
...
<div data-fb-key="aiDiffModal" ...>
  <div data-fb-key="aiDiffContent" ...>
</template>
<!-- File browser instances are created dynamically by FileBrowserManager factory -->
```

79 `data-fb-key` attributes cover all configurable elements. 5 `data-fb-for` attributes cover checkbox `<label>` elements.

**Also removed (lines 3723–3732):** The inline `<script>` block in `interface.html` that wired `#settings-file-browser-modal-open-button` click → `FileBrowserManager.open()`. This is now handled by `_wirePrimaryOpenButton()` in `file-browser-manager.js`.

---

### 3. `interface/global-docs-manager.js`

**Change summary:** The `#global-docs-manage-folders-btn` click handler replaced — instead of calling `FileBrowserManager.configure(...)` and `FileBrowserManager.open(...)` (which mutated the shared singleton), it now creates an independent instance via `createFileBrowser('global-docs-fb', { rootPath, onMove, onDelete })`.

**Added at line 14 (module property):**
```javascript
_fileBrowser: null,  // Independent FileBrowser instance for the Global Docs folder browser
```

**Replaced lines 345–429 (click handler):**

Before:
```javascript
$('#global-docs-manage-folders-btn').on('click', function() {
    if (typeof FileBrowserManager === 'undefined') { alert('...'); return; }
    FileBrowserManager.configure({
        onMove: function(srcPath, destPath, done) { ... },
        onDelete: function(path, done) { ... }
    });
    var startPath = GlobalDocsManager._userHash ? 'storage/global_docs/' + ... : 'storage/global_docs';
    FileBrowserManager.configure({ rootPath: startPath });
    FileBrowserManager.open(startPath);
    $('#global-docs-modal').modal('hide');
});
```

After:
```javascript
$('#global-docs-manage-folders-btn').on('click', function() {
    if (typeof createFileBrowser === 'undefined') { alert('...'); return; }
    var startPath = ...;
    if (!GlobalDocsManager._fileBrowser) {
        GlobalDocsManager._fileBrowser = createFileBrowser('global-docs-fb', {
            rootPath: startPath,
            onMove: function(srcPath, destPath, done) { ... },  // unchanged logic
            onDelete: function(path, done) { ... }              // unchanged logic
        });
        GlobalDocsManager._fileBrowser.init();
    } else {
        GlobalDocsManager._fileBrowser.configure({ rootPath: startPath });
    }
    GlobalDocsManager._fileBrowser.open(startPath);
    $('#global-docs-modal').modal('hide');
});
```

Key difference: the `onMove`/`onDelete` logic is identical, but now it goes into a dedicated instance that never touches `window.FileBrowserManager`'s config or state.

---

### 4. `interface/service-worker.js`

- Line 15: `CACHE_VERSION = "v27"` → `"v28"` (forces cache invalidation for the JS changes)

---

### 5. `documentation/features/file_browser/README.md`

Updated sections: JS Module Structure, Files Created/Modified, Key Public API table, Group 2 DOM Element IDs description, Example: Read-Only Folder Browser, Deep Merge Behavior, Refactor Files Modified table. Added new section: **Multi-Instance / Factory Pattern**. Added Known Issues row for PDF binary fix.

---

## How To Revert These Changes

The patch file `fb_factory_refactor.patch` in this folder contains the full `git diff` output for all 5 files. To revert:

```bash
# Option 1: apply the reverse patch
git apply --reverse documentation/planning/plans/fb_factory_refactor.patch

# Option 2: restore individual files from git
git checkout HEAD -- interface/file-browser-manager.js
git checkout HEAD -- interface/interface.html
git checkout HEAD -- interface/global-docs-manager.js
git checkout HEAD -- interface/service-worker.js
git checkout HEAD -- documentation/features/file_browser/README.md
```

If you need to revert only some of the changes (e.g. keep the PDF fix but revert the factory refactor), use the patch file sections selectively:

- **PDF fix only** (in `file-browser-manager.js`): the hunk around lines 1108–1157 that reorders `.pdf` check before `is_binary` check
- **Factory + DOM abstraction** (all remaining hunks in `file-browser-manager.js`, all of `interface.html`, `global-docs-manager.js`)
- **Cache version bump** (`service-worker.js` single line change)
