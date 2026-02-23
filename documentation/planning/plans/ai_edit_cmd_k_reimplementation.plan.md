# AI Edit (Cmd+K) — Reimplementation Plan

**Purpose**: This document captures the complete requirements, architecture, implementation details, and manual checkpoints for the Cmd+K AI Edit feature across File Browser and Artefacts modals, plus the chat-settings-modal backdrop bug fix. It is written to enable a clean reimplementation from a reverted codebase.

**Baseline**: Commit `1d42368` ("File Browwer") on `main` — this is the last pushed commit. Everything below describes what needs to be built ON TOP of that commit.

**Constraints**:
- jQuery + Bootstrap 4.6 + CodeMirror 5 only (no new frameworks)
- `var` keyword in legacy JS modules (not `let`/`const`)
- Follow existing IIFE module pattern in file-browser-manager.js
- Follow existing Flask blueprint pattern in file_browser.py
- Do NOT use Bootstrap `.modal('show')` / `.modal('hide')` for AI edit overlays (use vanilla DOM show/hide)
- Bump `CACHE_VERSION` in service-worker.js and `?v=N` on script tags together

---

## Table of Contents

1. [What Already Works (Committed Baseline)](#1-committed-baseline)
2. [Feature A: File Browser AI Edit](#2-file-browser-ai-edit)
3. [Feature B: Artefacts Cmd+K Integration](#3-artefacts-cmdk-integration)
4. [Feature C: Shared Backend Helpers](#4-shared-backend-helpers-llm_edit_utilspy)
5. [Feature D: Chat-Settings-Modal Backdrop Bug Fix](#5-chat-settings-modal-backdrop-bug-fix)
6. [Feature E: Artefacts Mobile Responsive](#6-artefacts-mobile-responsive)
   - 6.7 [Feature F: Reload from Disk (File Browser)](#67-feature-f-reload-from-disk-file-browser)
7. [Implementation Order with Checkpoints](#7-implementation-order-with-checkpoints)
8. [Files to Create/Modify](#8-files-to-createmodify)
9. [Known Pitfalls & Edge Cases](#9-known-pitfalls--edge-cases)
10. [Context Controls Architecture](#10-context-controls-architecture)

---

## 1. Committed Baseline

### 1.1 File Browser (file-browser-manager.js)

The committed version (`1d42368`) has a fully working file browser with:

**State object** (IIFE-scoped):
```javascript
var state = {
    currentPath: null,        // Currently open file path (relative to server root)
    currentDir: '.',          // Currently viewed directory
    originalContent: '',      // Content as loaded from server (for discard comparison)
    isDirty: false,           // Has unsaved changes
    cmEditor: null,           // CodeMirror 5 instance
    sidebarVisible: true,     // Sidebar collapse state
    expandedDirs: {},         // Map of expanded directory paths
    isMarkdown: false,        // Current file is .md/.markdown
    activeTab: 'code',        // 'code' or 'preview'
    contextTarget: null,      // Right-clicked tree item
    currentTheme: 'monokai',  // CodeMirror theme
    initialized: false,
    pathSuggestions: [],
    pathSuggestionMap: {}
};
```

**CodeMirror config:**
```javascript
state.cmEditor = CodeMirror($('#file-browser-editor-container')[0], {
    lineNumbers: true, theme: state.currentTheme, mode: null,
    autoCloseBrackets: true, matchBrackets: true, styleActiveLine: true,
    foldGutter: true,
    gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
    indentUnit: 4, tabSize: 4, indentWithTabs: false, lineWrapping: false,
    extraKeys: {
        'Tab': function(cm) { /* indent or insert 4 spaces */ }
    }
});
```

**Existing keyboard shortcuts:** Ctrl+S/Cmd+S (save), Escape (close with dirty check), Tab (indent/spaces).

**Top bar buttons (left to right):** Sidebar toggle | Address bar | Dirty indicator | Theme selector | Discard (hidden) | Save (disabled) | Close.

**Backend routes (endpoints/file_browser.py):** `/file-browser/tree`, `/file-browser/read`, `/file-browser/write`, `/file-browser/mkdir`, `/file-browser/rename`, `/file-browser/delete`. NO `/file-browser/ai-edit` route exists.

### 1.2 Artefacts (artefacts-manager.js)

The committed version has a full propose_edits pipeline:

**proposeEdits() sends:**
```javascript
{
    instruction: string,             // from #artefact-instruction textarea
    selection: { start_line, end_line },  // optional, from getSelectionLines()
    include_summary: boolean,        // #artefact-include-summary checkbox
    include_messages: boolean,       // #artefact-include-messages checkbox
    include_memory_pad: boolean,     // #artefact-include-memory checkbox
    history_count: number            // #artefact-history-count input (default 10)
}
```

**Backend route:** `POST /artefacts/<cid>/<aid>/propose_edits`
- Uses JSON ops schema (replace_range, insert_at, append, delete_range)
- Returns `{ proposed_ops, diff_text, base_hash, new_hash }`
- Has per-hunk diff rendering with checkboxes
- Does NOT accept `deep_context` parameter (that's new)

**Existing footer controls HTML IDs:** `#artefact-instruction`, `#artefact-include-summary`, `#artefact-include-messages`, `#artefact-include-memory`, `#artefact-history-count`, `#artefact-propose-btn`.

### 1.3 Chat Settings Modal (chat.js)

The committed handler re-passes options object on every click:
```javascript
$('#chatSettingsButton').click(function () {
    loadSettingsIntoModal();
    $('#chat-settings-modal').modal({
        backdrop: true, keyboard: true, focus: true, show: true
    });
    setTimeout(function() {
        $('#chat-settings-modal').focus();
    }, 100);
});
```

The `hidden.bs.modal` handler does NOT clean up backdrops.

### 1.4 Hint/Solution Modal Cleanup (codemirror.js)

The committed handlers only remove scroll buttons, NOT backdrops:
```javascript
// Inside renderStreamingHint() - accumulates on every call
$('#hint-modal').on('hidden.bs.modal', function() {
    $('.code-hint-scroll-top').remove();
    // NO backdrop removal!
});
// Same pattern for solution-modal
```

### 1.5 Z-Index Hierarchy (committed)

```
chat-settings-modal:    1055 (backdrop: 1054, dialog: 1056, content: 1057)
code-editor-modal:      1075
hint/solution modals:   1090
file-browser-modal:     100000
artefacts-modal:        100001  (estimated based on file browser)
```

**Known bug in committed baseline**: CSS rules like `#chat-settings-modal .modal-backdrop { z-index: 1054 }` never match because Bootstrap 4 appends `.modal-backdrop` to `<body>`, not inside the modal element. These are dead CSS rules.

---

## 2. Feature A: File Browser AI Edit

### 2.1 Requirements

Build a Cursor-style Cmd+K inline edit for the file browser. Core loop: user opens file -> optionally selects text -> hits Cmd+K (or clicks AI Edit button) -> types instruction in overlay -> LLM returns replacement text -> diff preview appears -> user accepts/rejects.

**Functional requirements:**
- AI Edit button in top bar (between theme selector and discard button)
  - Icon: `bi-magic`, text "AI Edit", class `btn btn-sm btn-outline-info`
  - ID: `#file-browser-ai-edit-btn`
  - Disabled when no file open or binary file; enabled when text file loaded
- Cmd+K / Ctrl+K keyboard shortcut registered in CodeMirror `extraKeys`
- Selection edit: select text then Cmd+K. Only selected lines sent to LLM
- Whole-file edit: no selection + Cmd+K. Limited to 500 lines
- File size guard: files >500 lines without selection -> toast warning, abort
- Binary file guard: AI Edit button disabled for binary files

### 2.2 UI: Instruction Overlay Modal

**HTML element:** `#file-browser-ai-edit-modal`
- Position: absolute inside file browser modal, z-index `100001`
- Display: `none` by default, set to `flex` when shown (NOT Bootstrap modal)
- Semi-transparent dark backdrop: `background: rgba(0,0,0,0.4)`
- Centered white card: `width: 500px; max-width: 90%`

**Contents:**
- Heading: "AI Edit" (or "AI Edit (Cmd+K)")
- Info line: `#fb-ai-edit-info` - dynamically shows:
  - "Editing: lines X-Y (selected)" when text is selected
  - "Editing: entire file" when no selection
- Instruction textarea: `#fb-ai-edit-instruction`, 3 rows, placeholder "Describe the changes you want..."
- Context controls (see Section 10 for full architecture):
  - `#fb-ai-edit-include-summary` checkbox - "Include summary"
  - `#fb-ai-edit-include-messages` checkbox - "Include recent messages"
  - `#fb-ai-edit-include-memory` checkbox - "Include memory pad"
  - `#fb-ai-edit-history-count` number input (default 10, range 0-50) - "History"
  - `#fb-ai-edit-deep-context` checkbox - "Deep context extraction (adds 2-5s)"
  - All context controls disabled/greyed when no conversation open
- Cancel button: `#fb-ai-edit-cancel`, class `btn btn-sm btn-secondary`
- Generate button: `#fb-ai-edit-generate`, class `btn btn-sm btn-primary`
- Spinner: `#fb-ai-edit-spinner`, hidden by default, shown during LLM call

### 2.3 UI: Diff Preview Overlay Modal

**HTML element:** `#file-browser-ai-diff-modal`
- Position: absolute inside file browser modal, z-index `100002`
- Same display pattern as instruction modal
- Larger: `width: 80vw; max-width: 900px; max-height: 80vh`

**Contents:**
- Heading: "AI Edit Preview"
- Diff content area: `#fb-ai-diff-content`, scrollable, monospace, bordered
  - Class: `.ai-diff-view`
  - Renders unified diff with colored lines (see CSS below)
- Buttons:
  - "Edit Instruction": `#fb-ai-diff-edit`, class `btn btn-sm btn-outline-primary` - returns to instruction modal
  - "Reject": `#fb-ai-diff-reject`, class `btn btn-sm btn-secondary` - discards edit
  - "Accept": `#fb-ai-diff-accept`, class `btn btn-sm btn-success` - applies edit to editor

### 2.4 CSS: Diff Styles (in style.css)

```css
.ai-diff-view {
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    font-size: 12px;
}
.ai-diff-line { white-space: pre; padding: 1px 8px; line-height: 1.5; }
.ai-diff-add { background: rgba(25, 135, 84, 0.12); color: #198754; }
.ai-diff-del { background: rgba(220, 53, 69, 0.12); color: #dc3545; }
.ai-diff-hunk { background: rgba(13, 110, 253, 0.08); color: #0d6efd; font-weight: 600; }
.ai-diff-header { color: #6c757d; }
```

### 2.5 State Additions (file-browser-manager.js)

Add to the `state` object:
```javascript
aiEditSelection: null,      // {from, to} CodeMirror cursor positions
aiEditProposed: null,       // LLM's replacement text
aiEditOriginal: null,       // Original text (selection or full file)
aiEditIsSelection: false,   // Whether editing a selection vs whole file
aiEditStartLine: null,      // 1-indexed start line
aiEditEndLine: null,        // 1-indexed end line
aiEditBaseHash: null        // Hash from server response
```

### 2.6 New Functions (file-browser-manager.js)

All functions are private (inside the IIFE closure).

**`_showAiEditModal()`**
- Guard: if no `state.cmEditor` or no `state.currentPath`, show toast and return
- If `cmEditor.somethingSelected()`:
  - Get from/to cursors, **expand to full lines**: `from: {line: from.line, ch: 0}`, `to: {line: to.line, ch: cmEditor.getLine(to.line).length}`
  - Store in `state.aiEditSelection`, set `aiEditStartLine`/`aiEditEndLine` (1-indexed: `line + 1`)
  - Set info text: "Editing: lines X-Y (selected)"
- Else:
  - Check `cmEditor.lineCount()` > 500 -> show toast "File too large..." and return
  - Set info text: "Editing: entire file"
- Check conversation availability via `getConversationIdFromUrl()`:
  - If convId exists: enable all context checkboxes and history input
  - If null: disable all context controls, uncheck them, set opacity 0.5
- Show modal: `document.getElementById('file-browser-ai-edit-modal').style.display = 'flex'`
- Focus instruction textarea after 50ms setTimeout

**`_hideAiEditModal()`**
- Set display to `'none'`
- Hide spinner, re-enable Generate button

**`_generateAiEdit()`**
- Validate instruction not empty
- Show spinner, disable Generate button
- Build payload:
  ```javascript
  var payload = {
      path: state.currentPath,
      instruction: instruction,
      include_summary: $('#fb-ai-edit-include-summary').is(':checked'),
      include_messages: $('#fb-ai-edit-include-messages').is(':checked'),
      include_memory_pad: $('#fb-ai-edit-include-memory').is(':checked'),
      history_count: parseInt($('#fb-ai-edit-history-count').val() || '10', 10),
      deep_context: $('#fb-ai-edit-deep-context').is(':checked')
  };
  ```
- If convId exists AND any context checkbox checked: add `conversation_id` to payload
- If selection edit: add `selection: { start_line, end_line }` to payload
- POST to `/file-browser/ai-edit` via `$.ajax()`
- On success:
  - Store `state.aiEditProposed`, `state.aiEditOriginal`, `state.aiEditBaseHash`
  - Hide instruction modal, show diff modal via `_showAiDiffModal(resp.diff_text)`
- On error: show toast with error message, hide instruction modal

**`_showAiDiffModal(diffText)`**
- Render diff HTML into `#fb-ai-diff-content` via `_renderDiffPreview()`
- Show modal: `display = 'flex'`

**`_hideAiDiffModal()`**
- Set display to `'none'`
- Clear `#fb-ai-diff-content` innerHTML

**`_acceptAiEdit()`**
- If no `state.aiEditProposed`: show toast, hide diff modal, return
- If selection edit:
  - `state.cmEditor.replaceRange(proposed, selection.from, selection.to)`
- If whole-file edit:
  - Save cursor position
  - `state.cmEditor.setValue(proposed)`
  - Restore cursor position
- Set `state.isDirty = true`, call `_updateDirtyState()`
- Hide diff modal, clear AI edit state
- Show success toast: "AI edit applied. Review and save when ready."

**`_rejectAiEdit()`**
- Hide diff modal, clear AI edit state

**`_editAiInstruction()`**
- Hide diff modal
- Re-show instruction modal (instruction text preserved in textarea)

**`_clearAiEditState()`**
- Set `aiEditProposed`, `aiEditOriginal`, `aiEditBaseHash` to null

**`_renderDiffPreview(diffText)`**
- If empty: return "No changes detected" message
- Split by newline, iterate lines:
  - `@@` prefix -> class `ai-diff-hunk`
  - `+++`/`---` prefix -> class `ai-diff-header`
  - `+` prefix (not `+++`) -> class `ai-diff-add`
  - `-` prefix (not `---`) -> class `ai-diff-del`
  - Default: class `ai-diff-line`
- HTML-escape each line (`&`, `<`, `>`)
- Return concatenated `<div class="...">escaped</div>` string

### 2.7 Event Handlers (in init())

```javascript
// AI Edit button click
$('#file-browser-ai-edit-btn').on('click', _showAiEditModal);

// Instruction modal buttons
$('#fb-ai-edit-cancel').on('click', _hideAiEditModal);
$('#fb-ai-edit-generate').on('click', _generateAiEdit);

// Diff modal buttons
$('#fb-ai-diff-accept').on('click', _acceptAiEdit);
$('#fb-ai-diff-reject').on('click', _rejectAiEdit);
$('#fb-ai-diff-edit').on('click', _editAiInstruction);

// Ctrl+Enter / Cmd+Enter submits instruction
$('#fb-ai-edit-instruction').on('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        _generateAiEdit();
    }
});

// Escape closes overlays (highest priority, before modal close)
$(document).on('keydown', function(e) {
    if (e.key === 'Escape') {
        // Check diff modal first (higher z-index)
        if (diffModal.style.display === 'flex') { e.stopPropagation(); _rejectAiEdit(); return; }
        if (editModal.style.display === 'flex') { e.stopPropagation(); _hideAiEditModal(); return; }
    }
});

// Backdrop click closes overlays
$('#file-browser-ai-edit-modal').on('click', function(e) { if (e.target === this) _hideAiEditModal(); });
$('#file-browser-ai-diff-modal').on('click', function(e) { if (e.target === this) _rejectAiEdit(); });
```

### 2.8 CodeMirror extraKeys Addition

Add to the existing `extraKeys` map:
```javascript
'Cmd-K': function(cm) { _showAiEditModal(); },
'Ctrl-K': function(cm) { _showAiEditModal(); }
```

### 2.9 Button Enable/Disable Logic

- On successful file load: `$('#file-browser-ai-edit-btn').prop('disabled', false)`
- On binary file detection: `$('#file-browser-ai-edit-btn').prop('disabled', true)`
- On too-large file warning: `$('#file-browser-ai-edit-btn').prop('disabled', true)`
- On file delete (if deleted file was open): `$('#file-browser-ai-edit-btn').prop('disabled', true)`

### 2.10 Backend: POST /file-browser/ai-edit

New route in `endpoints/file_browser.py`.

**Request payload:**
```json
{
  "path": "relative/to/server/root/file.py",
  "instruction": "Refactor this function to use list comprehension",
  "selection": { "start_line": 10, "end_line": 25 },
  "conversation_id": "abc123",
  "include_summary": true,
  "include_messages": true,
  "include_memory_pad": false,
  "history_count": 10,
  "deep_context": false
}
```

**Processing flow:**
1. Validate `path` and `instruction` non-empty
2. Resolve path via `_safe_resolve()` for path traversal prevention
3. Check file exists and is not binary (read first 8192 bytes, check for `\x00`)
4. Read file content as UTF-8
5. Determine if selection edit or whole-file edit
6. Check file size guard (>500 lines for whole-file)
7. Compute `base_hash` via `hash_content(content)`
8. If `conversation_id` provided and any context flag set:
   - Load conversation via `state_obj.conversation_cache[conversation_id]`
   - Set API keys via `conversation.set_api_keys(keys)`
   - Call `gather_conversation_context()` from `llm_edit_utils.py`
9. Build prompt via `build_edit_prompt()` from `llm_edit_utils.py`
10. Call LLM: `CallLLm(keys, model_name=EXPENSIVE_LLM[2])` with:
    - `stream=False, temperature=0.2, max_tokens=4000`
    - `system=SYSTEM_PROMPT` (from llm_edit_utils.py)
11. Extract code from response via `extract_code_from_response()`
12. Generate unified diff via `generate_diff()`
13. Return success response

**Success response:**
```json
{
  "status": "success",
  "original": "original text (selection or full file)",
  "proposed": "LLM replacement text",
  "diff_text": "unified diff for preview",
  "base_hash": "sha256 hex digest",
  "start_line": 10,
  "end_line": 25,
  "is_selection": true
}
```

**Error codes:** `missing_param`, `missing_instruction`, `path_forbidden`, `not_found`, `binary_file`, `file_too_large`, `llm_error`, `ai_edit_error`.

**Required imports (new to file_browser.py):**
```python
from difflib import unified_diff
from call_llm import CallLLm
from common import EXPENSIVE_LLM
from Conversation import Conversation
from database.conversations import checkConversationExists
from endpoints.llm_edit_utils import (
    hash_content, read_lines, consume_llm_output,
    extract_code_from_response, build_edit_prompt,
    gather_conversation_context, generate_diff, SYSTEM_PROMPT,
)
from endpoints.request_context import get_state_and_keys
from endpoints.session_utils import get_session_identity
from extensions import limiter
```

**Rate limit:** `@limiter.limit("20 per minute")`

---

## 3. Feature B: Artefacts Cmd+K Integration

### 3.1 Requirements

Add Cmd+K keyboard shortcut as a new entry point into the EXISTING `proposeEdits()` pipeline. Do NOT rebuild the propose/diff/apply flow. The Cmd+K overlay captures the instruction, syncs controls to the existing footer controls, then calls `proposeEdits()` directly.

### 3.2 State Addition

Add to artefacts-manager.js state:
```javascript
deepContext: false   // Temporary flag set from Cmd+K overlay, consumed by proposeEdits()
```

### 3.3 UI: Cmd+K Instruction Overlay

**HTML element:** `#artefact-ai-edit-modal`
- Position: absolute inside `#artefacts-modal`, z-index `1090`
- Display: `none` by default, `flex` when shown (vanilla DOM, NOT Bootstrap modal)
- Same visual style as file browser instruction overlay

**Contents:**
- Heading: "AI Edit (Cmd+K)"
- Info line: `#art-ai-edit-info` - shows "Editing: lines X-Y (selected)" or "Editing: entire artefact"
- Instruction textarea: `#art-ai-edit-instruction`, 3 rows
- Deep context checkbox: `#art-ai-edit-deep-context` - "Deep context extraction (adds 2-5s)"
- Context controls (mirroring footer):
  - `#art-ai-edit-include-summary` checkbox
  - `#art-ai-edit-include-messages` checkbox
  - `#art-ai-edit-include-memory` checkbox
  - `#art-ai-edit-history-count` number input
- Cancel: `#art-ai-edit-cancel`
- Generate: `#art-ai-edit-generate` (with spinner `#art-ai-edit-spinner`)

### 3.4 New Functions (artefacts-manager.js)

**`_showArtAiEditModal()`**
- Get textarea element: `document.getElementById('artefact-editor-textarea')`
- If `selectionStart !== selectionEnd`: compute line numbers from character offsets (count `\n`)
  - Show "Editing: lines X-Y (selected)"
- Else: show "Editing: entire artefact"
- Initialize modal controls FROM footer state (sync footer -> modal):
  ```javascript
  $('#art-ai-edit-include-summary').prop('checked', $('#artefact-include-summary').is(':checked'));
  $('#art-ai-edit-include-messages').prop('checked', $('#artefact-include-messages').is(':checked'));
  // ... same for memory, history-count
  $('#art-ai-edit-deep-context').prop('checked', false);  // always start unchecked
  ```
- Show modal: `display = 'flex'`
- Focus instruction textarea after 50ms

**`_hideArtAiEditModal()`**
- Set display to `'none'`, hide spinner, re-enable Generate

**`_generateArtAiEdit()`**
- Validate instruction not empty
- Sync modal controls BACK to footer controls:
  ```javascript
  $('#artefact-include-summary').prop('checked', $('#art-ai-edit-include-summary').is(':checked'));
  $('#artefact-include-messages').prop('checked', $('#art-ai-edit-include-messages').is(':checked'));
  // ... same for memory, history-count
  ```
- Put instruction text into `#artefact-instruction`
- Set `state.deepContext = $('#art-ai-edit-deep-context').is(':checked')`
- Hide overlay modal
- Call existing `proposeEdits()` function

### 3.5 proposeEdits() Modification

Add `deep_context` to the existing payload:
```javascript
var payload = {
    instruction: ...,
    selection: ...,
    include_summary: ...,
    include_messages: ...,
    include_memory_pad: ...,
    history_count: ...,
    deep_context: state.deepContext || false   // NEW
};
state.deepContext = false;   // Reset after use
```

### 3.6 Event Handlers

```javascript
// Cmd+K / Ctrl+K on textarea
$(document).off('keydown', '#artefact-editor-textarea').on('keydown', '#artefact-editor-textarea', function(e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); _showArtAiEditModal(); }
});

// Overlay buttons (use delegated .off().on() pattern)
$(document).off('click', '#art-ai-edit-cancel').on('click', '#art-ai-edit-cancel', _hideArtAiEditModal);
$(document).off('click', '#art-ai-edit-generate').on('click', '#art-ai-edit-generate', _generateArtAiEdit);

// Escape closes overlay
$(document).off('keydown.artAiEdit').on('keydown.artAiEdit', function(e) {
    if (e.key === 'Escape' && modal.style.display === 'flex') { e.stopPropagation(); _hideArtAiEditModal(); }
});

// Ctrl+Enter submits
$(document).off('keydown', '#art-ai-edit-instruction').on('keydown', '#art-ai-edit-instruction', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); _generateArtAiEdit(); }
});

// Backdrop click closes
$(document).off('click', '#artefact-ai-edit-modal').on('click', '#artefact-ai-edit-modal', function(e) {
    if (e.target === this) _hideArtAiEditModal();
});
```

### 3.7 Mobile: Auto-Close Sidebar on Artefact Selection

When user clicks an artefact list item on mobile (<768px), auto-close the sidebar:
```javascript
if (window.innerWidth < 768) {
    $('#artefacts-modal .artefact-sidebar').removeClass('show');
}
```

### 3.8 Backend: Add deep_context to propose_edits

In `endpoints/artefacts.py`, add to `propose_artefact_edits_route()`:
- Parse `deep_context = bool(payload.get('deep_context'))` from request
- When true, call `conversation.retrieve_prior_context_llm_based(query=instruction, required_message_lookback=30)`
- Include `extracted_context` in the LLM prompt (add section after memory pad)

---

## 4. Shared Backend Helpers (llm_edit_utils.py)

### 4.1 Purpose

New file `endpoints/llm_edit_utils.py` — shared by both file browser and artefacts endpoints. Avoids code duplication.

### 4.2 Module Contents

**Constants:**
- `LANGUAGE_MAP` — dict mapping file extensions to language names (`.py` -> `python`, `.js` -> `javascript`, etc.)
- `SYSTEM_PROMPT` — "You are a precise code editor. Return ONLY the edited content inside a single fenced code block..."

**Functions:**

| Function | Purpose |
|----------|---------|
| `hash_content(content)` | SHA-256 hex digest |
| `line_number_content(content)` | Add 1-based line numbers for LLM context |
| `read_lines(content, start, end)` | Extract 1-indexed inclusive line range |
| `consume_llm_output(result)` | Convert LLM response (string or iterable) to string |
| `extract_code_from_response(llm_output)` | Extract content between first/last ``` markers |
| `format_recent_messages(messages, limit)` | Format last N messages as "role: text" |
| `detect_language(file_path)` | Extension-to-language mapping |
| `gather_conversation_context(conversation, instruction, ...)` | Load summary, messages, memory pad, optional deep context |
| `build_edit_prompt(instruction, file_path, content, selection, context_parts)` | Build full LLM prompt (selection or whole-file) |
| `generate_diff(original, proposed)` | Generate unified diff string |

### 4.3 Prompt Templates

**Selection edit prompt structure:**
```
## Instruction
{instruction}

## File Info
- Path: {file_path}
- Language: {detected_language}

## Conversation Context
### Summary
{summary or "(not included)"}
### Recent Messages
{recent or "(not included)"}
### Extracted Context
{extracted or "(not included)"}
### Memory Pad
{memory_pad or omitted}

## Selected Region (lines {start}-{end})
Edit ONLY this content and return the complete replacement:
```{lang}
{selected_text}
```

## Surrounding Context (read-only, do NOT include in output)
### Before selection (lines X-Y):
```
{15 lines before selection}
```
### After selection (lines X-Y):
```
{15 lines after selection}
```
```

**Whole-file edit prompt structure:** Same header, then "## Full File Content" with entire file.

### 4.4 Key Design Decision: Plain Replacement vs JSON Ops

File browser uses **plain replacement text** (LLM returns the edited code directly in a code fence). This avoids the JSON operations pipeline that artefacts uses, which has 4 failure modes: malformed JSON, wrong line numbers, conflicting ops, off-by-one errors.

Artefacts keeps its existing JSON ops approach for backward compatibility and per-hunk diff UI.

---

## 5. Chat-Settings-Modal Backdrop Bug Fix

### 5.1 Root Cause Analysis (Three Interlocking Bugs)

**Bug 1: Bootstrap 4 State Machine Corruption (Primary)**
The click handler calls `.modal({backdrop: true, ...show: true})` on every click. In Bootstrap 4, passing an options object re-runs the Modal constructor. If `_isTransitioning` was still `true` from a previous rapid open/close, the `.show()` call bails out silently — backdrop gets created but `_showElement` never executes, so the modal stays `display: none`.

**Bug 2: Stale Backdrop at z-index 1089 (Primary)**
Hint/solution modals set their backdrop to z-index 1089. Their `hidden.bs.modal` cleanup had a race condition (checking `if (!$('.modal.show').length)` before removing). A stale backdrop at 1089 survives and sits above the chat-settings modal (z-index 1055), making it appear invisible.

**Bug 3: Accumulating Event Handlers (Contributing)**
The `hidden.bs.modal` handlers for hint/solution modals were registered inside `renderStreamingHint()`/`renderStreamingSolution()` — called every hint/solution request — so handlers stacked up, causing unpredictable cleanup behavior.

### 5.2 Fix: chat.js Changes

**One-time initialization on page load** (NOT inside click handler):
```javascript
$('#chat-settings-modal').modal({
    backdrop: true, keyboard: true, focus: true, show: false
});
```

**Click handler rewrite:**
```javascript
$('#chatSettingsButton').click(function () {
    loadSettingsIntoModal();
    var modalEl = $('#chat-settings-modal');
    var modalData = modalEl.data('bs.modal');
    // Reset Bootstrap internal state if stuck mid-transition
    if (modalData) {
        modalData._isTransitioning = false;
        if (modalData._isShown && !modalEl.hasClass('show')) {
            modalData._isShown = false;
        }
    }
    // Remove ALL orphaned backdrops
    $('.modal-backdrop').remove();
    $('body').removeClass('modal-open');
    // String invocation — avoids re-running Modal constructor
    modalEl.modal('show');
});
```

**shown.bs.modal handler:** Pin ALL backdrops to z-index 1054:
```javascript
$('#chat-settings-modal').on('shown.bs.modal', function () {
    $(this).focus();
    $('.modal-backdrop').css('z-index', 1054);
});
```

**hidden.bs.modal handler:** Clean up backdrops on close:
```javascript
$('#chat-settings-modal').on('hidden.bs.modal', function () {
    // ... existing auto-apply logic ...
    $('.modal-backdrop').remove();
    $('body').removeClass('modal-open');
});
```

### 5.3 Fix: codemirror.js Changes

**Hint modal** (in `renderStreamingHint()`):
```javascript
// Namespaced to prevent handler accumulation
$('#hint-modal').off('hidden.bs.modal.hintCleanup').on('hidden.bs.modal.hintCleanup', function() {
    $('.code-hint-scroll-top').remove();
    // Unconditionally remove backdrops
    $('.modal-backdrop').remove();
    $('body').removeClass('modal-open');
});
```

**Solution modal** (in `renderStreamingSolution()`):
```javascript
$('#solution-modal').off('hidden.bs.modal.solutionCleanup').on('hidden.bs.modal.solutionCleanup', function() {
    $('.code-solution-scroll-top').remove();
    $('.modal-backdrop').remove();
    $('body').removeClass('modal-open');
});
```

### 5.4 CSS Fix: Remove Dead Backdrop Rules

Remove all descendant selectors like `#chat-settings-modal .modal-backdrop { ... }` from the CSS in interface.html — they never match because Bootstrap appends backdrops to `<body>`. Add a comment explaining backdrop z-index is managed via JS.

### 5.5 Also Fix: model-overrides-modal shown handler

Add backdrop z-index pinning:
```javascript
$('#model-overrides-modal').on('shown.bs.modal', function () {
    $('#settings-summary-model').trigger('focus');
    // Fix stale high-z-index backdrops
    $('.modal-backdrop').last().css('z-index', parseInt($(this).css('z-index'), 10) - 1);
});
```

---

## 6. Feature E: Artefacts Mobile Responsive

### 6.1 Requirements

Make the artefacts modal usable on mobile (<768px):
- Full-screen modal (no margins)
- Sidebar hidden by default, toggled via hamburger button
- Header controls wrap and shrink
- Footer stacks vertically
- AI edit overlay responsive width (95%)

### 6.2 Sidebar Toggle Button

Add to artefacts modal header (visible only on mobile `d-md-none`):
```html
<button type="button" id="artefact-sidebar-toggle" class="btn btn-sm btn-outline-secondary d-md-none ml-2" title="Toggle sidebar">
    <i class="fa fa-bars"></i>
</button>
```

### 6.3 Sidebar Class

Change the sidebar div from inline style to a class:
- Add class: `artefact-sidebar` to the existing `<div class="border-right" style="width: 280px; ...">` div
- CSS handles the mobile behavior

### 6.4 CSS (all inside `@media (max-width: 767.98px)`)

```css
/* Full-screen modal */
#artefacts-modal .modal-dialog { max-width:100%!important; width:100%!important; height:100%!important; margin:0!important; }
#artefacts-modal .modal-content { height:100%!important; border-radius:0!important; }
#artefacts-modal .modal-body { height: calc(100vh - 140px)!important; }

/* Sidebar: hidden by default, slides in from left */
#artefacts-modal .artefact-sidebar { display:none; position:absolute; top:0; left:0; bottom:0; width:260px!important; z-index:10; background:#fff; box-shadow:2px 0 8px rgba(0,0,0,0.15); }
#artefacts-modal .artefact-sidebar.show { display:block; }

/* Header: wrap controls */
#artefacts-modal .modal-header { padding: 0.5rem 0.75rem; flex-wrap: wrap; }
#artefacts-modal .modal-header .close { font-size: 1.8rem; }
#artefacts-modal .modal-header select, #artefacts-modal .modal-header .btn { font-size: 0.75rem; padding: 0.2rem 0.4rem; }

/* Footer: stack vertically */
#artefacts-modal .modal-footer { flex-direction: column; align-items: stretch!important; padding: 0.5rem; }

/* Footer: instruction textarea full-width on mobile */
#artefacts-modal .modal-footer .flex-grow-1 { margin-right: 0!important; margin-bottom: 0.5rem; }

/* Footer: buttons wrap and stretch */
#artefacts-modal .modal-footer .d-flex:last-child { flex-wrap: wrap; gap: 4px; }
#artefacts-modal .modal-footer .d-flex:last-child .btn { flex: 1 1 auto; margin-right: 0!important; }

/* Footer: checkboxes wrap on mobile */
#artefacts-modal .modal-footer .d-flex.align-items-center.mt-2 { flex-wrap: wrap; gap: 2px 10px; }

/* Header: close button larger tap target */
#artefacts-modal .modal-header .close { padding: 0.25rem 0.5rem; margin: -0.25rem -0.25rem -0.25rem auto; opacity: 0.8; }
#artefacts-modal .modal-header .d-flex.align-items-center { flex-wrap: wrap; gap: 4px; }

/* AI edit overlay responsive */
#artefact-ai-edit-modal > div { width: 95%!important; max-width: 95%!important; }
```

### 6.5 JS: Sidebar Toggle and Close-on-outside-click

```javascript
// Toggle sidebar
$('#artefact-sidebar-toggle').on('click', function() {
    $('#artefacts-modal .artefact-sidebar').toggleClass('show');
});

// Close sidebar on outside click
$('#artefacts-modal .modal-body').on('click', function(e) {
    var sidebar = $('#artefacts-modal .artefact-sidebar');
    if (sidebar.hasClass('show') && !$(e.target).closest('.artefact-sidebar').length) {
        sidebar.removeClass('show');
    }
});
```

### 6.6 File Browser AI Edit Mobile CSS

```css
@media (max-width: 767.98px) {
    #file-browser-ai-edit-modal > div { width: 95%!important; max-width: 95%!important; }
    #file-browser-ai-diff-modal > div { width: 95%!important; max-width: 95%!important; max-height: 90vh!important; }
}
```

---


## 6.7 Feature F: Reload from Disk (File Browser)

### 6.7.1 Purpose

Allow users to reload the currently open file from disk. Useful when the file was edited externally (e.g., from a terminal, another editor tab, or a background process). The reload replaces the editor content with the latest on-disk version.

### 6.7.2 Requirements

- Reload button visible next to the existing Save button (`#file-browser-save-btn`)
- Button disabled when no file is open (same enable/disable logic as save)
- If editor has unsaved changes (`state.isDirty === true`), show a confirmation dialog before reloading
- On confirmation (or if not dirty), fetch fresh content from server and replace editor contents
- Reset dirty flag and update `state.originalContent` to match new content
- Show success toast after reload
- Show error toast if reload fails (e.g., file deleted from disk)

### 6.7.3 Backend: No New Endpoint Needed

**Reuse the existing `GET /file-browser/read` endpoint** — it already:
- Takes `path` query parameter
- Returns `{path, content, size, extension, is_binary}` for text files
- Handles binary detection, size guards, 404 for missing files
- Is secured with `@login_required`

No new backend route is required. The frontend simply calls the same endpoint it uses when opening a file.

### 6.7.4 Frontend: HTML Button

Add a reload button next to the save button in the file browser top bar:
```html
<!-- Inside #file-browser-top-bar, immediately after #file-browser-save-btn -->
<button class="btn btn-sm btn-secondary" id="file-browser-reload-btn" title="Reload from Disk" disabled>
    <i class="fa fa-sync-alt"></i>
</button>
```

**Placement**: Between `#file-browser-save-btn` and the theme selector (or wherever the save button sits in the button group). Mirror the save button's `btn-sm` sizing.

### 6.7.5 Frontend: JS Function (file-browser-manager.js)

Add inside the IIFE, alongside existing helper functions:

```javascript
/**
 * Reload the currently open file from disk.
 * Prompts for confirmation if there are unsaved changes.
 * Fetches fresh content via GET /file-browser/read and replaces editor contents.
 */
function _reloadFromDisk() {
    if (!state.currentPath) return;

    if (state.isDirty) {
        if (!confirm('You have unsaved changes. Reload from disk? All changes will be lost.')) {
            return;
        }
    }

    $.get('/file-browser/read', { path: state.currentPath }, function(resp) {
        if (resp.status === 'error') {
            showToast('Reload failed: ' + (resp.message || 'Unknown error'), 'danger');
            return;
        }
        if (resp.is_binary) {
            showToast('File is now binary — cannot display', 'warning');
            return;
        }
        if (resp.too_large) {
            showToast('File is now too large (> 2 MB)', 'warning');
            return;
        }
        var cursor = state.cmEditor.getCursor();
        var scrollInfo = state.cmEditor.getScrollInfo();
        state.cmEditor.setValue(resp.content);
        state.originalContent = resp.content;
        state.isDirty = false;
        _updateDirtyUI();
        // Restore cursor and scroll position
        state.cmEditor.setCursor(cursor);
        state.cmEditor.scrollTo(scrollInfo.left, scrollInfo.top);
        showToast('Reloaded from disk', 'success');
    }).fail(function(xhr) {
        if (xhr.status === 404) {
            showToast('File no longer exists on disk', 'danger');
        } else {
            showToast('Reload failed: ' + (xhr.statusText || 'Server error'), 'danger');
        }
    });
}
```

### 6.7.6 Frontend: Event Handler (in init())

```javascript
// Reload from disk
$('#file-browser-reload-btn').on('click', _reloadFromDisk);
```

### 6.7.7 Button Enable/Disable Logic

The reload button follows the **same enable/disable pattern as the save button**:

```javascript
// When a text file is loaded successfully:
$('#file-browser-reload-btn').prop('disabled', false);

// When file is closed, binary, or modal closes:
$('#file-browser-reload-btn').prop('disabled', true);
```

Add this alongside every place that enables/disables `#file-browser-save-btn`. Specifically:
- After successful file load in `_loadFile()` → enable
- In `_clearEditorState()` or file close → disable
- In binary file detection → disable
- On modal close → disable

### 6.7.8 Keyboard Shortcut (Optional Enhancement)

Consider adding `Ctrl+Shift+R` or `F5` as a reload shortcut in CodeMirror's `extraKeys`:
```javascript
// In CodeMirror extraKeys:
'Ctrl-Shift-R': function(cm) { _reloadFromDisk(); }
```
This is optional and can be added later if desired.

---

## 7. Implementation Order with Checkpoints

### Phase 1: Shared Backend Helpers (llm_edit_utils.py)

**Tasks:**
1. Create `endpoints/llm_edit_utils.py` with all functions listed in Section 4
2. Verify: `python -c "import endpoints.llm_edit_utils"` succeeds

**CHECKPOINT 1:** Run `python -c "from endpoints.llm_edit_utils import hash_content, build_edit_prompt, gather_conversation_context, generate_diff, SYSTEM_PROMPT; print('OK')"`. Must print OK.

### Phase 2: File Browser Backend (ai-edit endpoint)

**Tasks:**
1. Add imports to `endpoints/file_browser.py`
2. Add `POST /file-browser/ai-edit` route (Section 2.10)
3. Register any needed blueprint changes (should auto-register since file_browser_bp already exists)

**CHECKPOINT 2:** Start server. Use curl or Postman to POST to `/file-browser/ai-edit` with a test file path and instruction. Verify JSON response with `status: success`, `proposed`, `diff_text`. Test error cases: missing path, binary file, too-large file.

### Phase 3: Artefacts Backend (deep_context addition)

**Tasks:**
1. Add `deep_context` parsing to `propose_artefact_edits_route()` in `endpoints/artefacts.py`
2. Add `retrieve_prior_context_llm_based` call when `deep_context=true`
3. Include extracted context in LLM prompt

**CHECKPOINT 3:** Start server. Open artefacts modal, propose an edit with deep_context checkbox (once frontend is added). For now, verify via curl that `deep_context: true` in the payload triggers the additional context extraction. Check server logs for the LLM call.

### Phase 4: File Browser Frontend HTML + CSS

**Tasks:**
1. Add AI Edit button to file browser top bar in `interface.html` (between theme selector and discard)
2. Add instruction overlay modal HTML (`#file-browser-ai-edit-modal`)
3. Add diff preview overlay HTML (`#file-browser-ai-diff-modal`)
4. Add diff CSS classes to `style.css`
5. Add mobile responsive CSS for file browser AI edit overlays
6. Add Reload from Disk button (`#file-browser-reload-btn`) next to save button (Section 6.7.4)

**CHECKPOINT 4:** Open file browser in browser. Verify:
- AI Edit button visible in top bar (disabled)
- Open a text file -> button enables
- Open browser dev tools, manually set `document.getElementById('file-browser-ai-edit-modal').style.display = 'flex'` -> overlay appears centered with correct styling
- Same for diff modal

### Phase 5: File Browser Frontend JS

**Tasks:**
1. Add AI edit state properties to state object
2. Add `Cmd-K`/`Ctrl-K` to CodeMirror extraKeys
3. Implement all `_showAiEditModal`, `_hideAiEditModal`, `_generateAiEdit`, `_showAiDiffModal`, `_hideAiDiffModal`, `_acceptAiEdit`, `_rejectAiEdit`, `_editAiInstruction`, `_clearAiEditState`, `_renderDiffPreview` functions
4. Wire up all event handlers in `init()`
5. Add button enable/disable logic in file load, binary detection, and delete handlers
6. Add `_reloadFromDisk()` function and `#file-browser-reload-btn` click handler (Section 6.7.5-6.7.6)
7. Add reload button enable/disable alongside save button logic (Section 6.7.7)
8. Run `node --check interface/file-browser-manager.js`

**CHECKPOINT 5 (FULL END-TO-END):**
- Open file browser, open a .py file
- Select 3-4 lines, press Cmd+K
- Verify instruction overlay appears with "Editing: lines X-Y (selected)"
- Type an instruction, press Ctrl+Enter
- Verify spinner shows, then diff preview appears
- Verify diff has green (additions) and red (deletions) lines
- Click Accept -> verify editor content updated
- Verify editor shows as dirty (unsaved)
- Test Reject flow (no changes)
- Test Edit Instruction flow (returns to instruction modal with text preserved)
- Test Escape key closes overlays
- Test whole-file edit (no selection, small file)
- Test large file guard (>500 lines, no selection -> toast)
- Test with no conversation open (context controls greyed out)
- Test Reload from Disk button: open file, edit content, click reload -> confirm dialog appears
- Click confirm -> editor reverts to on-disk version, dirty flag cleared
- Test reload with no unsaved changes -> reloads silently with success toast
- Test reload after external file deletion -> error toast "File no longer exists on disk"

### Phase 6: Artefacts Frontend HTML

**Tasks:**
1. Add sidebar toggle button to artefacts modal header
2. Add `artefact-sidebar` class to sidebar div
3. Add Cmd+K overlay modal HTML (`#artefact-ai-edit-modal`) inside artefacts modal

**CHECKPOINT 6:** Open artefacts modal in browser. Verify overlay HTML renders correctly (same dev-tools manual display test). Verify sidebar toggle button visible on mobile viewport.

### Phase 7: Artefacts Frontend JS

**Tasks:**
1. Add `deepContext` to state
2. Add `_showArtAiEditModal`, `_hideArtAiEditModal`, `_generateArtAiEdit` functions
3. Wire up event handlers (Cmd+K, buttons, escape, backdrop click)
4. Add sidebar toggle and close-on-outside-click handlers
5. Add auto-close sidebar on artefact selection (mobile)
6. Modify `proposeEdits()` to include `deep_context`
7. Run `node --check interface/artefacts-manager.js`

**CHECKPOINT 7 (FULL END-TO-END):**
- Open artefacts, create or open an artefact
- Press Cmd+K -> verify overlay appears
- Type instruction, check "Deep context" checkbox
- Press Generate -> verify it feeds into existing propose_edits flow
- Verify diff tab shows proposed changes
- Test accept/reject flow
- Test mobile: resize to <768px, verify sidebar toggle works, verify overlay responsive

### Phase 8: Chat-Settings-Modal Backdrop Fix

**Tasks:**
1. Add one-time modal initialization in `chat.js`
2. Rewrite chatSettingsButton click handler
3. Update shown/hidden handlers
4. Add namespaced event handlers in `codemirror.js`
5. Remove dead CSS backdrop rules from `interface.html`
6. Add model-overrides-modal shown handler fix

**CHECKPOINT 8:**
- Open a hint modal, close it
- Open a solution modal, close it
- Click chat settings button -> modal MUST appear (not just backdrop)
- Repeat 5 times rapidly
- Open hint, close, open settings -> must work
- Open solution, close, open settings -> must work
- Verify no orphaned backdrops in DOM after closing all modals (`$('.modal-backdrop').length` should be 0)

### Phase 9: Cache Bump + Documentation

**Tasks:**
1. Increment `CACHE_VERSION` in `service-worker.js`
2. Update `?v=N` on script tags in `interface.html` for:
   - `file-browser-manager.js`
   - `artefacts-manager.js`
3. Update documentation:
   - `documentation/features/file_browser/README.md` — add AI Edit section
   - `documentation/features/conversation_artefacts/README.md` — add Cmd+K section

**CHECKPOINT 9:** Hard refresh browser (Ctrl+Shift+R). Verify new JS is loaded (check Network tab for updated `?v=N` query params). Verify service worker cache version updated.

---

## 8. Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `endpoints/llm_edit_utils.py` | CREATE | Shared helpers: prompt building, context gathering, response parsing, hashing |
| `endpoints/file_browser.py` | MODIFY | Add `POST /file-browser/ai-edit` endpoint + imports |
| `endpoints/artefacts.py` | MODIFY | Add `deep_context` support to `propose_edits` |
| `interface/interface.html` | MODIFY | AI Edit buttons, overlays (file browser + artefacts), sidebar toggle, Reload from Disk button, mobile CSS, backdrop CSS fix |
| `interface/file-browser-manager.js` | MODIFY | AI Edit logic: overlays, generate, accept/reject, diff rendering, Cmd+K, Reload from Disk |
| `interface/artefacts-manager.js` | MODIFY | Cmd+K shortcut, overlay, deep_context flag, mobile sidebar |
| `interface/chat.js` | MODIFY | Chat-settings-modal backdrop bug fix |
| `interface/codemirror.js` | MODIFY | Namespaced hint/solution modal cleanup handlers |
| `interface/style.css` | MODIFY | Diff coloring classes, artefacts mobile CSS (close button, body overflow, footer checkbox) |
| `interface/service-worker.js` | MODIFY | Cache version bump |
| `documentation/features/file_browser/README.md` | MODIFY | Document AI Edit feature |
| `documentation/features/conversation_artefacts/README.md` | MODIFY | Document Cmd+K shortcut |

---

## 9. Known Pitfalls & Edge Cases

### 9.1 CodeMirror Selection is 0-Indexed
CodeMirror `getCursor()` returns 0-indexed line numbers. Backend expects 1-indexed. Frontend must add 1: `startLine = from.line + 1`.

### 9.2 Selection Expansion to Full Lines
When user selects partial lines, expand selection to full lines:
- `from: {line: from.line, ch: 0}`
- `to: {line: to.line, ch: cmEditor.getLine(to.line).length}`

### 9.3 Artefacts Textarea vs CodeMirror
Artefacts uses plain `<textarea>` with `selectionStart`/`selectionEnd` (character offsets). Must count newlines to convert to line numbers. File browser uses CodeMirror with `getCursor()` returning `{line, ch}` objects.

### 9.4 Cmd+K Browser Conflicts
On macOS, Cmd+K opens browser address bar or creates hyperlink. Both CodeMirror `extraKeys` handler and textarea `keydown` handler MUST call `e.preventDefault()` to suppress browser default.

### 9.5 Escape Key Priority
File browser modal already uses Escape to close (with dirty check). AI Edit overlay must intercept Escape FIRST (via `stopPropagation()`) before it bubbles to modal close handler.

### 9.6 LLM Response Without Code Fences
`extract_code_from_response()` handles this: if no ``` markers found, returns full stripped text as fallback.

### 9.7 Bootstrap Modal Handler Accumulation
The `hidden.bs.modal` handlers in codemirror.js are registered inside `renderStreamingHint()`/`renderStreamingSolution()` which run on every request. MUST use `.off('event.namespace').on('event.namespace', ...)` pattern to prevent stacking.

### 9.8 Bootstrap 4 Modal State Machine
NEVER re-pass options object to `.modal()` on repeated opens. Initialize once with `show: false`, then use string invocation `.modal('show')`. Reset `_isTransitioning` and `_isShown` before showing if they got stuck.

### 9.9 Backdrop Cleanup Must Be Unconditional
Do NOT check `if (!$('.modal.show').length)` before removing backdrops — this races with Bootstrap's async removal. Always unconditionally remove: `$('.modal-backdrop').remove(); $('body').removeClass('modal-open');`

### 9.10 Dead CSS Rules for Backdrops
Bootstrap 4 appends `.modal-backdrop` to `<body>`, NOT inside the modal element. Descendant selectors like `#chat-settings-modal .modal-backdrop` never match and should be removed.

### 9.11 `var` Not `let`/`const`
All JS in this project uses `var`. Do NOT introduce `let` or `const` in legacy modules.

### 9.12 Context Controls Disabled When No Conversation
`getConversationIdFromUrl()` returns null when no conversation is open. All context checkboxes must be disabled, unchecked, and visually greyed out (`opacity: 0.5`) in this case.

---

## 10. Context Controls Architecture

### 10.1 Overview

Both File Browser and Artefacts AI Edit modals support optional conversation context for the LLM. Controls allow users to choose what context to include:

| Control | File Browser ID | Artefacts Modal ID | Artefacts Footer ID |
|---------|----------------|-------------------|-------------------|
| Include summary | `#fb-ai-edit-include-summary` | `#art-ai-edit-include-summary` | `#artefact-include-summary` |
| Include messages | `#fb-ai-edit-include-messages` | `#art-ai-edit-include-messages` | `#artefact-include-messages` |
| Include memory pad | `#fb-ai-edit-include-memory` | `#art-ai-edit-include-memory` | `#artefact-include-memory` |
| History count | `#fb-ai-edit-history-count` | `#art-ai-edit-history-count` | `#artefact-history-count` |
| Deep context | `#fb-ai-edit-deep-context` | `#art-ai-edit-deep-context` | N/A (state.deepContext) |

### 10.2 Sync Pattern (Artefacts Only)

The artefacts Cmd+K modal has DUPLICATE controls that mirror the footer. On open, footer state syncs TO the modal. On generate, modal state syncs BACK to footer. This ensures the existing `proposeEdits()` function reads correct values from footer controls.

### 10.3 Backend Context Gathering

`gather_conversation_context()` in `llm_edit_utils.py` handles all context loading:
- `include_summary=True` -> `conversation.running_summary`
- `include_messages=True` -> last N messages via `format_recent_messages()`
- `include_memory_pad=True` -> `conversation.memory_pad`
- `deep_context=True` -> `conversation.retrieve_prior_context_llm_based(query=instruction, required_message_lookback=30)`

### 10.4 conversation_id Source

`getConversationIdFromUrl()` from `common-chat.js` extracts the conversation ID from the URL hash. Available globally in the frontend.

---

## Appendix A: Terminal Endpoint Changes (Unrelated)

The uncommitted diff includes some debug print statements in `endpoints/terminal.py` and duplicate imports. These are unrelated to the AI Edit feature and should be reverted/cleaned up separately.
