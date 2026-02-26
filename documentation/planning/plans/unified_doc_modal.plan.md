# Unified Doc Modal

**Created:** 2026-02-25
**Status:** Implemented (2026-02-25)
**Depends On:** `interface/global-docs-manager.js`, `interface/common-chat.js`, `interface/interface.html`, `endpoints/documents.py`, `endpoints/global_docs.py`
**Related Docs:**
- `documentation/features/global_docs/README.md` — Global Docs feature reference
- `documentation/features/file_attachments/` — Message attachment (paperclip) system

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals](#goals)
3. [Non-Goals](#non-goals)
4. [Current State](#current-state)
5. [Design Overview](#design-overview)
6. [New HTML Elements](#new-html-elements)
7. [JS Architecture](#js-architecture)
8. [Files Changed](#files-changed)
9. [Implementation Tasks](#implementation-tasks)
10. [Risks and Mitigations](#risks-and-mitigations)

---

## Problem Statement

Conversation-scoped ("local") document upload and management uses an old modal (`#add-document-modal-chat`) and an inline badge strip (`#chat-doc-view` children) that are visually and architecturally inconsistent with the Global Docs modal introduced later. The inline strip wastes toolbar space and mixes doc management chrome with static toolbar buttons. Uploading and listing docs should live in one cohesive modal experience — same as global docs.

---

## Goals

- Replace `#add-document-button-chat` ("Add Doc") with a **"Docs" button** that opens a new conversation docs modal.
- New modal mirrors `#global-docs-modal` in layout: upload card (URL + drop + browse + display name + XHR progress) + list card (per-doc: view / download / promote-to-global / delete).
- Remove the old `#add-document-modal-chat` HTML and all its JS wiring.
- Remove inline doc badge rendering from `#chat-doc-view` (static toolbar buttons stay).
- Extract shared MIME-validation and XHR-upload-with-progress utilities into `DocsManagerUtils` used by both managers.
- `LocalDocsManager` handles all conversation-doc CRUD; `GlobalDocsManager` is refactored to use shared utils.
- Paperclip / drag-onto-page → `attach_doc_to_message` flow is **unchanged**.

---

## Non-Goals

- No changes to the backend endpoints or indexing tiers (local stays BM25 fast path, global stays full FAISS+LLM).
- No changes to the `#chat-file-upload` paperclip or message-attachment preview strip.
- No changes to the `#global-docs-modal` user-facing behavior (only internal code reuse).
- No changes to how `#gdoc_N` / `#doc_N` references work in LLM context.

---

## Current State (verified against code)

### UI entry points for local doc upload

| Trigger | Element | Handler (common-chat.js) | Endpoint |
|---|---|---|---|
| "Add Doc" button | `#add-document-button-chat` (line 279 interface.html) | `setupAddDocumentForm` opens `#add-document-modal-chat` (line 2080) | — |
| Modal URL submit | `#add-document-form` submit (line 2285) | `apiCall('/upload_doc_to_conversation/<id>', 'POST', {pdf_url})` | `/upload_doc_to_conversation/<id>` |
| Modal file browse | `#file-upload-button` click → `#pdf-file` change (line 2234) | `uploadFile_internal(file, attId)` XHR | `/upload_doc_to_conversation/<id>` |
| Modal drop area | `#drop-area` drop (line 2269) | `uploadFile_internal(file, attId)` XHR | `/upload_doc_to_conversation/<id>` |
| Paperclip | `#chat-file-upload-span` → `#chat-file-upload` change (line 2251) | `uploadFileAsAttachment(file, attId)` | `/attach_doc_to_message/<id>` |
| Page drag-drop | `$(document).on('drop')` (line 2342) | `uploadFileAsAttachment(file, attId)` | `/attach_doc_to_message/<id>` |

### Inline doc strip
- `renderDocuments(conversation_id, docs)` (line 2353) appends `<div class="d-inline-block">` children into `#chat-doc-view`.
- `chat_doc_view.children('div').remove()` clears them (static `<button>` children are NOT divs, so they survive).
- Static buttons in `#chat-doc-view`: `#get-chat-transcript`, `#share-chat`, `#add-document-button-chat`, `#global-docs-button`, plus ext buttons — all are `<button>` elements, not `<div>`.
- `renderDocuments` is called from **4 places** (all must be replaced):
  - line 162 — after promoting message attachment to conversation
  - line 736 — on conversation load in `openConversation`
  - line 2060 — inside `deleteDocument` success handler
  - line 2096 — inside `setupAddDocumentForm` upload success callback

### `setupAddDocumentForm` scope
- Defined lines 2078–2352 (inclusive), method of `ChatManager`.
- Called once from `openConversation` at line 738.
- Contains: `success()`, `failure()`, `uploadFile_internal()`, `uploadFileAsAttachment()`, `uploadFile()`, all event bindings for the old modal, file validation, document-level drag-drop.
- **Note:** `uploadFileAsAttachment()` and the document-level drag-drop handlers live inside `setupAddDocumentForm`. Moving them out is required since the method will be gutted.

### `deleteDocument` (lines 2053–2063)
- Calls `renderDocuments` in its success handler (line 2060). Must call `LocalDocsManager.refresh(conversationId)` instead.
- But `conversationId` is not a parameter of `deleteDocument` — it is passed in from the calling context inside `renderDocuments`. The new `LocalDocsManager` stores `conversationId` on itself after `setup(conversationId)`, so `deleteDocument` can delegate to `LocalDocsManager.refresh()` without needing to pass the id.

### `#uploadProgressContainer` / `#sendMessageButton`
- The old `uploadFile_internal` hides `#sendMessageButton` and shows `#uploadProgressContainer` (the spinner next to the send button) during upload (lines 2136–2137).
- The new modal upload will use its own inline spinner (`#conv-doc-upload-progress`) inside the modal, same pattern as `GlobalDocsManager`. The `#sendMessageButton` disable/hide will be **removed** from the new upload path — no need to block sending during a background doc upload inside a modal.
- Confirmed: `#uploadProgressContainer` is in the toolbar (interface.html line 340), adjacent to `#sendMessageButton` (line 334). It will no longer be touched by local doc upload.

### `showPDF` proxy endpoints
- Local docs: `showPDF(doc.source, "chat-pdf-content", "/proxy_shared")` (line 2401)
- Global docs: `showPDF(doc.doc_id, "chat-pdf-content", "/global_docs/serve")` (line 234 global-docs-manager.js)
- Local modal view button will use the same `/proxy_shared` pattern with `doc.source` as the first arg.

### `GlobalDocsManager` internal structure
- `_getMimeType(file)` (line 39) — extension→MIME map, can move to `DocsManagerUtils`
- `isValidFileType(file)` (line 64) — reads `#global-doc-file-input` accept attr, needs to accept the input element ID as a param to be reusable
- `upload(fileOrUrl, displayName)` (line 105) — XHR for files, `$.ajax` for URLs; reads `#global-doc-submit-btn`, `#global-doc-upload-spinner`, `#global-doc-upload-progress` — selector IDs need to be parameterised to be shared
- `setup()` (line 278) — wires all event handlers; references hardcoded element IDs throughout

### `#pdf-file` accept attr discrepancy
- `#pdf-file` (old modal, line 397) is missing `text/html` and `text/markdown` vs `#global-doc-file-input` and `#chat-file-upload`.
- New `#conv-doc-file-input` will use the same full accept list as `#chat-file-upload` (line 321 interface.html).

---

## Design Overview

### JS: Two objects, shared utilities

```
DocsManagerUtils  (top of local-docs-manager.js)
  getMimeType(file)
  isValidFileType(file, $fileInput)
  uploadWithProgress(endpoint, fileOrUrl, opts)
    opts: { $btn, $spinner, $progress, displayName, onSuccess, onError }
  setupDropArea($dropArea, $fileInput, onFileDrop)

LocalDocsManager  (local-docs-manager.js)
  conversationId: null          ← set on setup(conversationId)
  list(conversationId)          → GET /list_documents_by_conversation/<id>
  deleteDoc(conversationId, docId)  → DELETE /delete_document_from_conversation/<id>/<docId>
  upload(conversationId, fileOrUrl, displayName)
    → POST /upload_doc_to_conversation/<id>   (fast BM25 path, unchanged)
    → uses DocsManagerUtils.uploadWithProgress
  renderList(conversationId, docs)
    → list-group rows identical in structure to GlobalDocsManager.renderList
    → per-row actions: View (showPDF + /proxy_shared), Download, Promote to Global, Delete
  refresh(conversationId)       → list() then renderList()
  _resetForm()
  setup(conversationId)         → wires all #conversation-docs-modal event handlers

GlobalDocsManager  (global-docs-manager.js — refactored)
  _getMimeType  →  DocsManagerUtils.getMimeType
  isValidFileType  →  DocsManagerUtils.isValidFileType(file, $('#global-doc-file-input'))
  upload inner XHR  →  DocsManagerUtils.uploadWithProgress(...)
  setup drop area  →  DocsManagerUtils.setupDropArea(...)
  (list, deleteDoc, promote, getInfo, renderList, refresh — unchanged)
```

### HTML: New modal IDs

| ID | Purpose |
|---|---|
| `#conversation-docs-button` | Toolbar button (replaces `#add-document-button-chat`) |
| `#conversation-docs-modal` | Bootstrap modal container |
| `#conv-doc-upload-form` | Upload form |
| `#conv-doc-url` | URL text input |
| `#conv-doc-drop-area` | Drag-drop target |
| `#conv-doc-browse-btn` | "browse" link button |
| `#conv-doc-file-input` | Hidden file input |
| `#conv-doc-display-name` | Optional display name |
| `#conv-doc-submit-btn` | Upload submit button |
| `#conv-doc-upload-spinner` | Spinner span (shown during upload) |
| `#conv-doc-upload-progress` | "0%" text inside spinner |
| `#conv-doc-refresh-btn` | Refresh list button |
| `#conv-docs-list` | list-group for rendered doc rows |
| `#conv-docs-empty` | "No docs yet" empty state |

---

## New HTML Elements

### Toolbar button change (interface.html line 279)

**Remove:**
```html
<button id="add-document-button-chat" type="button" class="btn btn-primary mr-2 btn-sm mb-1">
  <i class="fa fa-plus">&nbsp; Add Doc</i>
</button>
```

**Add:**
```html
<button id="conversation-docs-button" type="button" class="btn btn-outline-primary mr-2 btn-sm mb-1">
  <i class="fa fa-file">&nbsp; Docs</i>
</button>
```

### Remove old modal (interface.html lines 379–411)

Remove entire block `<div class="modal" tabindex="-1" id="add-document-modal-chat"> ... </div>`.

### Add new modal (insert after line 411, before the global-docs-modal)

Structure mirrors `#global-docs-modal` exactly (lines 415–471 interface.html):
- `modal-lg`, two cards: "Add New Conversation Document" upload card + "Conversation Documents" list card
- Upload card: URL input, drop area, browse, display name, submit button + inline spinner with progress %
- List card: refresh button + `#conv-docs-list` list-group + `#conv-docs-empty` empty state
- `#conv-doc-file-input` uses same full accept list as `#chat-file-upload` (line 321)

### Script tag (interface.html near line 3607)

Add before the existing `global-docs-manager.js` tag:
```html
<script src="interface/local-docs-manager.js"></script>
```

---

## JS Architecture

### `interface/local-docs-manager.js` (new file)

```
DocsManagerUtils = {
  getMimeType(file),
  isValidFileType(file, $fileInput),
  uploadWithProgress(endpoint, fileOrUrl, opts),
  setupDropArea($dropArea, $fileInput, onFileDrop)
}

LocalDocsManager = {
  conversationId: null,
  list(conversationId),
  deleteDoc(conversationId, docId),
  upload(conversationId, fileOrUrl, displayName),
  renderList(conversationId, docs),
  refresh(conversationId),
  _resetForm(),
  setup(conversationId)
}

$(document).ready(function() { /* LocalDocsManager.setup called from common-chat.js */ })
```

### `interface/global-docs-manager.js` changes

- Remove `_getMimeType` → delegate to `DocsManagerUtils.getMimeType`
- Remove `isValidFileType` → delegate to `DocsManagerUtils.isValidFileType(file, $('#global-doc-file-input'))`
- Remove XHR upload boilerplate inside `upload()` → delegate to `DocsManagerUtils.uploadWithProgress`
- Remove drop area wiring inside `setup()` → delegate to `DocsManagerUtils.setupDropArea`
- `list`, `deleteDoc`, `promote`, `getInfo`, `renderList`, `refresh` — unchanged

### `interface/common-chat.js` changes

1. **`setupAddDocumentForm` (lines 2078–2352):** Replace body with single call to `LocalDocsManager.setup(conversationId)`. Keep the method signature so the `openConversation` call at line 738 continues to work.

2. **`uploadFileAsAttachment` and document-level drag-drop** are currently closures inside `setupAddDocumentForm`. Extract them as standalone functions (or move to module level) before gutting the method. They must survive as they serve the paperclip/page-drop flow.

3. **`renderDocuments` (lines 2353–2459):** Remove entirely. All 4 call sites replaced with `LocalDocsManager.refresh(LocalDocsManager.conversationId)`:
   - line 162: after promote-message-attachment success
   - line 736: on conversation load (alongside replacing `setupAddDocumentForm` call)
   - line 2060: inside `deleteDocument` success
   - line 2096 (inside old setupAddDocumentForm, deleted with it)

4. **`deleteDocument` (lines 2053–2063):** Replace `renderDocuments` call at line 2060 with `LocalDocsManager.refresh(conversationId)`. Note: `conversationId` is the parameter of `deleteDocument` — confirmed present at line 2053.

5. **`openConversation`** (line 738): `ChatManager.setupAddDocumentForm(conversationId)` becomes `LocalDocsManager.setup(conversationId)` directly, or the stub method calls it. Either way the net effect is identical.

---

## Files Changed

| File | Type of change |
|---|---|
| `interface/interface.html` | Remove `#add-document-modal-chat` (lines 379–411); rename toolbar button; add `#conversation-docs-modal`; add script tag for `local-docs-manager.js` |
| `interface/local-docs-manager.js` | **New file** — `DocsManagerUtils` + `LocalDocsManager` |
| `interface/global-docs-manager.js` | Refactor to use `DocsManagerUtils` (MIME, XHR, drop-area) |
| `interface/common-chat.js` | Gut `setupAddDocumentForm`; remove `renderDocuments`; extract `uploadFileAsAttachment` + doc-drop handler to module scope; update 3 remaining `renderDocuments` call sites |

No backend changes.

---

## Implementation Tasks

### Task 1 — Create `DocsManagerUtils` in `local-docs-manager.js`

Extract from `global-docs-manager.js`:
- `getMimeType(file)` — copy of `_getMimeType`, no changes
- `isValidFileType(file, $fileInput)` — copy of `isValidFileType` but takes `$fileInput` as param instead of hardcoding `$('#global-doc-file-input')`
- `uploadWithProgress(endpoint, fileOrUrl, opts)` — parameterised version of `GlobalDocsManager.upload`:
  - `opts`: `{ $btn, $spinner, $progress, displayName, onSuccess, onError }`
  - File path: XHR with onprogress 0–70%, setInterval tick 70–99% @ 1500ms
  - URL path: `$.ajax` JSON POST
  - Returns nothing (callbacks via opts)
- `setupDropArea($dropArea, $modal, $fileInput, onFileDrop)` — parameterised drop wiring with `stopPropagation` on both `$dropArea` and `$modal`

### Task 2 — Build `LocalDocsManager` in `local-docs-manager.js`

API helpers:
```js
list: function(conversationId) {
  return $.ajax({ url: '/list_documents_by_conversation/' + conversationId, type: 'GET' });
},
deleteDoc: function(conversationId, docId) {
  return $.ajax({ url: '/delete_document_from_conversation/' + conversationId + '/' + docId, type: 'DELETE' });
},
```

`upload(conversationId, fileOrUrl, displayName)`:
- Calls `DocsManagerUtils.uploadWithProgress('/upload_doc_to_conversation/' + conversationId, fileOrUrl, { $btn, $spinner, $progress, displayName, onSuccess: function() { LocalDocsManager._resetForm(); LocalDocsManager.refresh(conversationId); showToast(...); }, onError: ... })`

`renderList(conversationId, docs)`:
- Mirrors `GlobalDocsManager.renderList` structure exactly
- Each row: `#doc_N` index badge + display_name badge (if set) + title + source/date
- Action buttons: View (eye), Download, Promote-to-Global (globe), Delete (trash)
- **View**: `showPDF(doc.source, "chat-pdf-content", "/proxy_shared")` — same as old `renderDocuments` line 2401
- **Download**: `window.open('/download_doc_from_conversation/' + conversationId + '/' + doc.doc_id, '_blank')` — same as old line 2394
- **Promote**: `GlobalDocsManager.promote(conversationId, doc.doc_id)` then `LocalDocsManager.refresh(conversationId)` + `showToast(...)` — same logic as old lines 2434–2444
- **Delete**: `LocalDocsManager.deleteDoc(conversationId, doc.doc_id)` then `LocalDocsManager.refresh(conversationId)` + `showToast(...)`

`refresh(conversationId)`:
```js
refresh: function(conversationId) {
  LocalDocsManager.list(conversationId).done(function(docs) {
    LocalDocsManager.renderList(conversationId, docs);
  });
},
```

`_resetForm()`:
- Clears `#conv-doc-url`, `#conv-doc-display-name`, `#conv-doc-file-input`
- Resets `#conv-doc-drop-area` text to default

`setup(conversationId)`:
- Stores `LocalDocsManager.conversationId = conversationId`
- Opens modal on `#conversation-docs-button` click + calls `refresh(conversationId)`
- Wires `#conv-doc-browse-btn` → `$('#conv-doc-file-input').click()`
- File input change: validate via `DocsManagerUtils.isValidFileType`, show filename in drop area
- Drop area: `DocsManagerUtils.setupDropArea($('#conv-doc-drop-area'), $('#conversation-docs-modal'), $('#conv-doc-file-input'), function(file) { upload(conversationId, file, displayName); })`
- Form submit: validate file or URL, call `upload(conversationId, fileOrUrl, displayName)`
- Refresh button: `refresh(conversationId)`

### Task 3 — Refactor `GlobalDocsManager` to use `DocsManagerUtils`

- Replace `_getMimeType` call → `DocsManagerUtils.getMimeType`
- Replace `isValidFileType` call → `DocsManagerUtils.isValidFileType(file, $('#global-doc-file-input'))`
- Replace XHR upload block inside `upload()` → `DocsManagerUtils.uploadWithProgress('/global_docs/upload', fileOrUrl, { $btn: $('#global-doc-submit-btn'), $spinner: $('#global-doc-upload-spinner'), $progress: $('#global-doc-upload-progress'), displayName, onSuccess: ..., onError: ... })`
- Replace drop area wiring inside `setup()` → `DocsManagerUtils.setupDropArea($('#global-doc-drop-area'), $('#global-docs-modal'), $('#global-doc-file-input'), function(file) { GlobalDocsManager.upload(file, displayName); })`
- Remove `_getMimeType` and `isValidFileType` definitions from the file
- All other methods (`list`, `deleteDoc`, `promote`, `getInfo`, `renderList`, `refresh`, `_resetForm`) unchanged

### Task 4 — Add `#conversation-docs-modal` to `interface.html`

- Remove `#add-document-modal-chat` block (lines 379–411)
- Change toolbar button (line 279): id → `conversation-docs-button`, label → `<i class="fa fa-file">&nbsp; Docs</i>`, class `btn-outline-primary`
- Insert new `#conversation-docs-modal` after the old modal's location (before line 414 `<!-- Global Documents...`)
- Use full accept list from `#chat-file-upload` (line 321) for `#conv-doc-file-input`
- Add `<script src="interface/local-docs-manager.js"></script>` before line 3607 (global-docs-manager.js tag)

### Task 5 — Update `common-chat.js`

**5a. Extract `uploadFileAsAttachment` and document-level drag-drop to module scope**
- Both are currently closures inside `setupAddDocumentForm` (lines ~2187 and ~2333).
- Move them above the `var ChatManager = {` block or just above `setupAddDocumentForm` — before gutting the method.
- `uploadFileAsAttachment` needs `conversationId`: make it accept `conversationId` as a parameter, or read it from `ConversationManager.activeConversationId`. Check: `ConversationManager.activeConversationId` is set at line ~194 in common-chat.js — use it.
- The document-level `$(document).on('drop', ...)` handler also needs `conversationId`: same solution.

**5b. Gut `setupAddDocumentForm` body (lines 2078–2352)**
- Replace entire method body with:
  ```js
  setupAddDocumentForm: function(conversationId) {
      LocalDocsManager.setup(conversationId);
      // paperclip and page-drop wiring (moved to module scope above)
      setupPaperclipAndPageDrop(conversationId);
  },
  ```
- Or inline the calls directly — either way the method wrapper is kept so the call at line 738 doesn't need changing.

**5c. Remove `renderDocuments` (lines 2353–2459)**
- Delete the entire method.

**5d. Update call sites** (3 remaining after 5b removes the 4th):
- Line 162: `ChatManager.renderDocuments(conversationId, documents)` → `LocalDocsManager.refresh(LocalDocsManager.conversationId)`
- Line 736: `ChatManager.renderDocuments(conversationId, documents)` → `LocalDocsManager.refresh(conversationId)` (also line 738 call to `setupAddDocumentForm` remains, now delegates to `LocalDocsManager.setup`)
- Line 2060 (inside `deleteDocument`): `ChatManager.renderDocuments(conversationId, documents)` → `LocalDocsManager.refresh(conversationId)` (`conversationId` is the param of `deleteDocument`, confirmed present)

---

## Risks and Mitigations

| Risk | Detail | Mitigation |
|---|---|---|
| `uploadFileAsAttachment` loses `conversationId` closure | Currently a closure inside `setupAddDocumentForm`; extracting to module scope breaks the closure | Use `ConversationManager.activeConversationId` (set at conversation open, confirmed at ~line 194) |
| Document-level `$(document).on('drop')` bound multiple times | If `setupPaperclipAndPageDrop` is called on every conversation open, the handler stacks | Use `.off('drop').on('drop')` — same pattern already used in `GlobalDocsManager.setup()` |
| `renderDocuments` had `chat_doc_view.children('div').remove()` | Removed when method is deleted; no doc badges left in toolbar to clear | After migration, toolbar has no doc badges, so nothing to clear — safe |
| Static toolbar buttons are `<button>` not `<div>` | `children('div').remove()` never touched them — confirmed from HTML (lines 277–283) | No action needed |
| `deleteDocument` uses `renderDocuments` success — `conversationId` param | `conversationId` IS the first param of `deleteDocument` (confirmed line 2053) | Directly call `LocalDocsManager.refresh(conversationId)` |
| Old `#uploadProgressContainer` / `#sendMessageButton` blocking | Old upload hid send button during upload (lines 2136–2137); new modal uses inline progress | Simply don't include those calls in the new `DocsManagerUtils.uploadWithProgress` |
| `GlobalDocsManager.setup()` called from `$(document).ready` with no conversationId | It was always global; `LocalDocsManager.setup(conversationId)` is called per-conversation from `setupAddDocumentForm` | No change — the `ready` block stays for GlobalDocsManager only |
| `#pdf-file` accept list was missing `text/html`, `text/markdown` | Old bug; new `#conv-doc-file-input` uses full list | Use the same full accept list as `#chat-file-upload` (line 321) |
