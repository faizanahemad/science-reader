# AI Edit (Cmd+K) -- LLM-Assisted Inline Editing

## Intent & Goals

Build a Cursor-style Cmd+K inline edit experience for both the File Browser modal and the Artefacts modal. The core loop: user opens a file in the editor, optionally selects a region of text, hits Cmd+K (or clicks the AI Edit button), types a natural language instruction in a small overlay, and the LLM edits the selection (or the whole file). A diff preview shows exactly what changed. The user accepts or rejects.

Goals:

1. When a file is open in the File Browser editor, the user selects text (or not), clicks the AI Edit button or presses Cmd+K, a small overlay modal collects an instruction, the LLM edits the selection (or whole file), a diff preview appears, and the user accepts or rejects.
2. Add conversation context as an option: a checkbox to include the running summary plus the last 2 messages, and optionally `retrieve_prior_context_llm_based` for deep context extraction when the edit depends on conversation history.
3. Build a well-formatted LLM prompt that includes file content, the selected region, surrounding context lines, and conversation context.
4. Unify the UX pattern across both File Browser and Artefacts modals so Cmd+K works the same way everywhere.
5. For Artefacts, don't rebuild the propose/diff/apply pipeline. Just add the Cmd+K entry point that feeds into the existing flow.

## Requirements

### Functional Requirements

**File Browser:**

1. AI Edit button in the top bar, placed between the theme selector and the discard button. Icon: `bi-magic`. Tooltip: "AI Edit (Cmd+K)".
2. Cmd+K / Ctrl+K keyboard shortcut registered in CodeMirror's `extraKeys` map. Opens the same overlay as the button.
3. AI Edit overlay modal (z-index 100001, same pattern as the naming modal in the file browser) containing:
   - Instruction textarea with placeholder text: "Describe the changes you want..."
   - Info line showing "Editing: lines X-Y (selected)" when text is selected, or "Editing: entire file" when nothing is selected
   - Checkbox: "Include conversation context" (greyed out and disabled if no conversation is currently open)
   - Nested checkbox (visible only when parent is checked): "Deep context extraction" with a note that it adds 2-5 seconds of latency
   - Cancel and Generate buttons
   - Loading spinner on the Generate button while the LLM processes the request
4. After the LLM responds: a diff preview overlay showing a unified diff with green/red coloring.
   - Accept button: splices the replacement into CodeMirror (`replaceRange` for a selection edit, `setValue` for a whole-file edit)
   - Reject button: closes the overlay, no changes applied
   - Edit instruction button: returns to the instruction modal with the previous instruction text preserved
5. Files longer than 500 lines without a selection trigger a toast: "File too large for whole-file AI edit. Please select a region."
6. Binary files: the AI Edit button is disabled (same detection as the existing binary file guard).
7. No file open: the AI Edit button is disabled. Clicking it shows a toast: "No file open".

**Artefacts:**

8. Cmd+K / Ctrl+K keyboard shortcut on the artefacts textarea (`#artefact-editor-textarea`).
9. Same overlay modal UX for collecting the instruction.
10. The Generate action feeds into the existing `proposeEdits` pipeline, keeping the per-hunk diff in the Diff tab.
11. Add `retrieve_prior_context_llm_based` support to the `propose_edits` backend endpoint so deep context extraction is available from the artefacts flow too.

**Shared:**

12. Shared helpers extracted to `endpoints/llm_edit_utils.py` so both the file browser endpoint and the artefacts endpoint can reuse prompt building, context gathering, and response parsing.
13. Conversation context gathered via `conversation_id` obtained from `getConversationIdFromUrl()` in `common-chat.js`.
14. Well-formatted prompt template (detailed in the Prompt Engineering section below).

### Non-Functional Requirements

- No new JS frameworks. jQuery + Bootstrap 4.6 + CodeMirror 5 only.
- No new pip or npm dependencies.
- Follow the existing IIFE module pattern in `file-browser-manager.js`.
- Follow the existing Flask blueprint pattern in `endpoints/file_browser.py`.
- Security: path traversal prevention on the file browser endpoint (reuse `_safe_path()`).
- Performance: the LLM call should show a spinner. When deep context is enabled, display a "Extracting context..." message since it adds 2-5 seconds of latency.
- Keyboard shortcut must not conflict with browser defaults. Cmd+K in most browsers opens the address bar on Mac, so `preventDefault()` is required when CodeMirror or the artefacts textarea has focus.

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backend strategy | New endpoint in `file_browser.py` + extract shared helpers to `llm_edit_utils.py` | The artefacts endpoint is coupled to `artefact_id` and `conversation_id`. File browser files are server-local paths. Shared helpers give code reuse without coupling the two systems together. |
| Prompt strategy | Direct replacement text (not JSON ops) | LLMs produce better raw text than structured JSON operations. This eliminates the `_extract_json` to `_parse_operations` to `_apply_ops` pipeline and its 4 failure modes: malformed JSON, wrong line numbers, conflicting ops, off-by-one errors. Artefacts keeps JSON ops for backward compatibility. |
| UX flow | Simplified two-phase: propose, then diff preview, then accept/reject | Users need to see what changed before it hits their file. This is the core Cursor UX insight. Per-hunk selection is overkill for the file browser context; that's what the artefacts advanced flow already provides. |
| Conversation context | Cheap by default (summary + last 2 messages), deep extraction optional | `retrieve_prior_context_llm_based` adds 2-5 seconds of latency. Most edits don't need full conversation history. Deep extraction stays available for complex context-dependent edits. |
| `conversation_id` source | `getConversationIdFromUrl()` from `common-chat.js` | Already exists, extracts from the URL hash. If no conversation is open, the context checkbox is greyed out. |
| Overlay modal pattern | Same z-index 100001 overlay as the naming modal | Proven pattern in this codebase. Avoids Bootstrap modal stacking conflicts. |
| Artefacts integration | Add Cmd+K shortcut, feed into existing `proposeEdits` | Artefacts already has a sophisticated propose/diff/apply pipeline. Don't rebuild it. Just add the keyboard shortcut as a new entry point. |

## Prompt Engineering

### System Prompt

```
You are a precise code editor. Return ONLY the edited content inside a single fenced code block. Do not include explanations, commentary, or anything outside the code block. Do not include line numbers in the output. Preserve the original formatting, indentation, and style unless the instruction specifically asks to change them.
```

### User Prompt Template (selection edit)

```
## Instruction
{instruction}

## File Info
- Path: {file_path}
- Language: {detected_language}

## Conversation Context
### Summary
{running_summary or "(not included)"}

### Recent Messages
{formatted_last_2_messages or "(not included)"}

### Extracted Context
{retrieve_prior_context_llm_based_result or "(not included)"}

## Selected Region (lines {start_line}-{end_line})
Edit ONLY this content and return the complete replacement:

```{lang}
{selected_text}
```

## Surrounding Context (read-only, for reference only -- do NOT include in output)
### Before selection (lines {max(1, start-15)}-{start-1}):
```
{lines_before_selection}
```

### After selection (lines {end+1}-{min(total, end+15)}):
```
{lines_after_selection}
```
```

### User Prompt Template (whole-file edit)

```
## Instruction
{instruction}

## File Info
- Path: {file_path}
- Language: {detected_language}

## Conversation Context
### Summary
{running_summary or "(not included)"}

### Recent Messages
{formatted_last_2_messages or "(not included)"}

### Extracted Context
{retrieve_prior_context_llm_based_result or "(not included)"}

## Full File Content
Edit this file and return the complete updated content:

```{lang}
{file_content}
```
```

### Prompt Design Notes

- The surrounding context (15 lines before and after the selection) gives the LLM enough local context to make coherent edits without including the entire file.
- Conversation context sections are only populated when the user checks the "Include conversation context" box. Otherwise they show "(not included)" so the LLM knows they were intentionally omitted.
- The system prompt is strict about returning only a code block. This makes response parsing reliable: find the first ``` and last ``` markers, extract everything between them.
- Language detection uses file extension mapping (same `MODE_MAP` pattern from the file browser, but mapped to language names instead of CodeMirror modes).

## API Design

### New Endpoint: POST /file-browser/ai-edit

Request:
```json
{
  "path": "relative/to/server/root/file.py",
  "instruction": "Refactor this function to use list comprehension",
  "selection": {"start_line": 10, "end_line": 25},
  "conversation_id": "abc123",
  "include_context": true,
  "deep_context": false
}
```

The `selection` field is optional. When omitted, the entire file is edited. The `conversation_id`, `include_context`, and `deep_context` fields are all optional.

Response (success):
```json
{
  "status": "success",
  "original": "original text (selection or full file)",
  "proposed": "LLM's replacement text",
  "diff_text": "unified diff for preview",
  "base_hash": "sha256 of file content at read time",
  "start_line": 10,
  "end_line": 25,
  "is_selection": true
}
```

Response (error):
```json
{
  "status": "error",
  "error": "File too large for whole-file edit (832 lines). Please select a region.",
  "code": "file_too_large"
}
```

Error codes: `file_too_large`, `file_not_found`, `binary_file`, `path_traversal`, `missing_instruction`, `llm_error`.

### Enhanced Artefacts Endpoint: POST /artefacts/<cid>/<aid>/propose_edits

Add a new optional field to the existing payload:

```json
{
  "instruction": "...",
  "selection": {"start_line": 4, "end_line": 12},
  "include_summary": true,
  "include_messages": true,
  "include_memory_pad": false,
  "history_count": 10,
  "deep_context": false
}
```

When `deep_context` is true, additionally call `conversation.retrieve_prior_context_llm_based(instruction)` and include the extracted context in the prompt. This is the only backend change needed for artefacts; the rest of the propose/diff/apply pipeline stays the same.

## Implementation Plan

### Phase 1: Backend Foundation (shared helpers + file browser endpoint)

**Task 1.1: Create `endpoints/llm_edit_utils.py`**

Priority: High. Effort: Medium.

Extract reusable helpers from `endpoints/artefacts.py` and add new ones:

- `_hash_content(text)` -- SHA256 hash of content (extracted from artefacts.py)
- `_line_number_content(text)` -- add line numbers to text (extracted from artefacts.py)
- `_format_recent_messages(messages, count)` -- format last N messages for prompt context (extracted from artefacts.py)
- `_consume_llm_output(response)` -- consume streaming LLM response into a string (extracted from artefacts.py)
- `detect_language_from_path(file_path)` -- NEW: extension-to-language-name mapping (`.py` to `python`, `.js` to `javascript`, etc.)
- `extract_code_from_response(llm_output)` -- NEW: regex to extract content between the first and last ``` markers. Fallback: if no markers found, return the full response text stripped of leading/trailing whitespace.
- `build_edit_prompt(instruction, file_path, content, selection, context_parts)` -- NEW: constructs the user prompt from the templates above. `selection` is a dict with `start_line`, `end_line`, `selected_text`, `lines_before`, `lines_after` or None for whole-file. `context_parts` is a dict with optional keys `summary`, `recent_messages`, `extracted_context`.
- `gather_conversation_context(conversation, instruction, include_context, deep_context)` -- NEW: loads conversation, gets running summary and last 2 messages. If `deep_context` is true, calls `conversation.retrieve_prior_context_llm_based(instruction)`. Returns a `context_parts` dict.

Files: `endpoints/llm_edit_utils.py` (NEW), `endpoints/artefacts.py` (update imports to use shared helpers).

**Task 1.2: Add `POST /file-browser/ai-edit` endpoint to `endpoints/file_browser.py`**

Priority: High. Effort: Medium.

Steps:
- Accept JSON payload: `path`, `instruction`, `selection` (optional), `conversation_id` (optional), `include_context` (optional), `deep_context` (optional)
- Validate `instruction` is non-empty
- Resolve file path using existing `_safe_path()` for path traversal prevention
- Read file content from disk
- Check: file exists, not binary (reuse existing binary detection), line count under 500 for whole-file edits (or selection must be provided)
- If `conversation_id` and `include_context`: load conversation via existing helpers, call `gather_conversation_context()`
- Build prompt using `build_edit_prompt()`
- Call LLM with `CallLLm` (temperature 0.2, max_tokens scaled to content size)
- Extract replacement text using `extract_code_from_response()`
- Generate unified diff using `difflib.unified_diff`
- Compute `base_hash` using `_hash_content()`
- Return JSON response with `original`, `proposed`, `diff_text`, `base_hash`, line info, `is_selection` flag

Files: `endpoints/file_browser.py` (MODIFIED).

**Task 1.3: Enhance artefacts `propose_edits` with `deep_context`**

Priority: Medium. Effort: Small.

- Add `deep_context` field to the payload parsing in the `propose_edits` endpoint
- When `deep_context` is true, call `conversation.retrieve_prior_context_llm_based(instruction)`
- Include the extracted context in the prompt passed to the LLM
- Use `gather_conversation_context()` from the shared helpers

Files: `endpoints/artefacts.py` (MODIFIED).

### Phase 2: Frontend -- File Browser AI Edit

**Task 2.1: Add AI Edit button and overlay modals to `interface.html`**

Priority: High. Effort: Small-Medium.

Add the AI Edit button to the file browser top bar:
- Button: `#file-browser-ai-edit-btn`, classes `btn btn-sm btn-outline-info`, icon `bi-magic`, text "AI Edit"
- Placement: between the theme selector and the discard button in the file browser header

Add the AI Edit instruction overlay modal HTML (`#file-browser-ai-edit-modal`, z-index 100001):
- Instruction textarea: `#fb-ai-edit-instruction`, 3 rows, placeholder "Describe the changes you want..."
- Info line: `#fb-ai-edit-info` (dynamically shows "Editing: lines X-Y (selected)" or "Editing: entire file")
- Checkbox: `#fb-ai-edit-include-context` with label "Include conversation context"
- Nested checkbox: `#fb-ai-edit-deep-context` with label "Deep context extraction (adds 2-5s)" (hidden by default, shown when parent checked)
- Cancel button: `#fb-ai-edit-cancel`, class `btn btn-sm btn-secondary`
- Generate button: `#fb-ai-edit-generate`, class `btn btn-sm btn-primary`
- Spinner: `#fb-ai-edit-spinner` (hidden by default, shown during LLM call)

Add the diff preview overlay HTML (`#file-browser-ai-diff-modal`, z-index 100002):
- Diff display area: `#fb-ai-diff-content` (pre-formatted, scrollable, monospace)
- Accept button: `#fb-ai-diff-accept`, class `btn btn-sm btn-success`
- Reject button: `#fb-ai-diff-reject`, class `btn btn-sm btn-secondary`
- Edit instruction button: `#fb-ai-diff-edit`, class `btn btn-sm btn-outline-primary`

Files: `interface/interface.html` (MODIFIED).

**Task 2.2: Implement AI Edit logic in `file-browser-manager.js`**

Priority: High. Effort: Large (bulk of frontend work).

New `var` declarations inside the IIFE closure:

State additions:
- `aiEditSelection` -- from/to cursor positions captured when the overlay opens (null if no selection)
- `aiEditProposed` -- the LLM's replacement text (stored for accept action)
- `aiEditIsSelection` -- boolean, true if editing a selection vs whole file
- `aiEditStartLine` / `aiEditEndLine` -- 1-indexed line numbers for the selection
- `aiEditBaseHash` -- hash from the server response, for stale-content detection

New functions:

- `_showAiEditModal()` -- Captures the current CodeMirror selection (if any). Populates the info line. Checks if a conversation is open (via `getConversationIdFromUrl()`) and enables/disables the context checkbox accordingly. Shows the overlay.
- `_hideAiEditModal()` -- Closes the instruction overlay. Clears the spinner state.
- `_showAiDiffModal(diffText, proposed, isSelection, startLine, endLine)` -- Renders the diff with colored lines. Stores `proposed`, `isSelection`, `startLine`, `endLine` in state for the accept action.
- `_hideAiDiffModal()` -- Closes the diff overlay. Clears stored state.
- `_generateAiEdit()` -- Validates that instruction is non-empty. Builds the POST payload (path, instruction, selection info, conversation_id, context flags). Shows spinner. POSTs to `/file-browser/ai-edit`. On success: hides instruction overlay, shows diff overlay. On error: shows toast with the error message.
- `_acceptAiEdit()` -- If `aiEditIsSelection` is true: uses `cmEditor.replaceRange(proposed, from, to)` where `from`/`to` are the original selection positions. If false: uses `cmEditor.setValue(proposed)`. Marks the editor as dirty. Closes the diff overlay. Shows a success toast.
- `_rejectAiEdit()` -- Closes the diff overlay. No changes applied.
- `_editAiInstruction()` -- Closes the diff overlay. Reopens the instruction overlay with the previous instruction text still in the textarea.
- `_renderDiffPreview(diffText)` -- Parses unified diff text line by line. Lines starting with `+` (not `+++`) get class `ai-diff-add`. Lines starting with `-` (not `---`) get class `ai-diff-del`. Lines starting with `@@` get class `ai-diff-hunk`. Lines starting with `---` or `+++` get class `ai-diff-header`. All other lines are plain context. Returns HTML string.

Event handlers to add in `init()`:

- `#file-browser-ai-edit-btn` click: calls `_showAiEditModal()`
- `#fb-ai-edit-generate` click: calls `_generateAiEdit()`
- `#fb-ai-edit-cancel` click: calls `_hideAiEditModal()`
- `#fb-ai-diff-accept` click: calls `_acceptAiEdit()`
- `#fb-ai-diff-reject` click: calls `_rejectAiEdit()`
- `#fb-ai-diff-edit` click: calls `_editAiInstruction()`
- Ctrl+Enter / Cmd+Enter in `#fb-ai-edit-instruction`: calls `_generateAiEdit()`
- Escape key (document-level, scoped): closes whichever overlay is currently showing
- Cmd+K / Ctrl+K in CodeMirror `extraKeys`: calls `_showAiEditModal()` with `preventDefault()`
- `#fb-ai-edit-include-context` change: toggles visibility of the nested deep context checkbox
- On file load / file close: disable or enable the AI Edit button based on whether a file is open and whether it's binary

Files: `interface/file-browser-manager.js` (MODIFIED).

**Task 2.3: Add diff preview CSS styles to `style.css`**

Priority: Medium. Effort: Small.

New CSS classes:

- `.ai-diff-add` -- background: `rgba(25, 135, 84, 0.12)`, color: `#198754` (green for additions)
- `.ai-diff-del` -- background: `rgba(220, 53, 69, 0.12)`, color: `#dc3545` (red for deletions)
- `.ai-diff-hunk` -- background: `rgba(13, 110, 253, 0.08)`, color: `#0d6efd`, font-weight: 600 (blue for hunk headers)
- `.ai-diff-header` -- color: `#6c757d` (grey for file headers like `---` and `+++`)
- `.ai-diff-line` -- white-space: pre, font-family: `ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace`, font-size: 12px, padding: 1px 8px

Overlay modal styles (similar to the naming modal):
- Instruction modal: centered, max-width 500px, dark semi-transparent backdrop
- Diff modal: centered, max-width 80vw, max-height 70vh with scrollable diff content area

Files: `interface/style.css` (MODIFIED).

### Phase 3: Frontend -- Artefacts Cmd+K Integration

**Task 3.1: Add Cmd+K overlay HTML for artefacts in `interface.html`**

Priority: Medium. Effort: Small.

Add an overlay modal: `#artefact-ai-edit-modal` at appropriate z-index:
- Instruction textarea: `#art-ai-edit-instruction`
- Info line showing the selected line range (or "entire artefact")
- Checkbox: `#art-ai-edit-deep-context` with label "Deep context extraction"
- Generate and Cancel buttons

Files: `interface/interface.html` (MODIFIED).

**Task 3.2: Implement Cmd+K in `artefacts-manager.js`**

Priority: Medium. Effort: Medium.

- Add Ctrl+K / Cmd+K keydown handler on `#artefact-editor-textarea`. The handler calls `preventDefault()` and opens the overlay modal.
- Selection detection: use `selectionStart` / `selectionEnd` on the textarea, convert to line numbers by counting newlines in the text before the selection boundaries.
- Generate button handler: captures the instruction from the overlay, populates `#artefact-instruction` with it, sets the selection range, checks context boxes as needed, then calls the existing `proposeEdits()` function.
- This reuses the entire existing propose, diff, and apply pipeline. No new diff rendering needed.
- Add the `deep_context` flag to the `proposeEdits` AJAX payload.

Files: `interface/artefacts-manager.js` (MODIFIED).

### Phase 4: Cache Bump + Documentation

**Task 4.1: Bump cache version**

Priority: High. Effort: Tiny.

- `service-worker.js`: increment `CACHE_VERSION` (currently v18, bump to v19)
- `interface.html`: update the `?v=` query parameter on the script tags for `file-browser-manager.js` and `artefacts-manager.js`

Files: `interface/service-worker.js` (MODIFIED), `interface/interface.html` (MODIFIED).

**Task 4.2: Update documentation**

Priority: Low. Effort: Small.

- `documentation/features/file_browser/README.md` -- add an "AI Edit (Cmd+K)" section describing the feature, the button, the keyboard shortcut, the overlay flow, the diff preview, and the conversation context option.
- `documentation/features/conversation_artefacts/README.md` -- add a "Cmd+K Inline Edit" section describing the keyboard shortcut entry point and the deep context option.

Files: both READMEs (MODIFIED).

### Phase 5: Verification

- `node --check interface/file-browser-manager.js` -- syntax check
- `node --check interface/artefacts-manager.js` -- syntax check
- Python syntax check on `endpoints/llm_edit_utils.py`, `endpoints/file_browser.py`, `endpoints/artefacts.py`
- `lsp_diagnostics` on all modified Python files
- Manual test: open file browser, select text, Cmd+K, type instruction, verify diff preview, accept
- Manual test: open file browser, no selection, Cmd+K on a short file, verify whole-file edit
- Manual test: open file browser, no selection on a 600-line file, verify toast warning
- Manual test: open artefacts, Cmd+K, type instruction, verify it feeds into propose_edits pipeline
- Manual test: check context checkbox with no conversation open, verify it's greyed out

## Implementation Order

1. **Task 1.1** (shared helpers) -- no dependencies, foundation for everything else
2. **Task 1.2** (file browser endpoint) -- depends on 1.1
3. **Task 1.3** (artefacts deep_context) -- depends on 1.1, can parallelize with 1.2
4. **Task 2.1** (HTML for file browser overlays) -- can parallelize with Phase 1
5. **Task 2.3** (CSS styles) -- can parallelize with 2.1
6. **Task 2.2** (JS logic for file browser) -- depends on 1.2, 2.1, 2.3
7. **Task 3.1** (HTML for artefacts overlay) -- can parallelize with Phase 2
8. **Task 3.2** (JS logic for artefacts) -- depends on 1.3, 3.1
9. **Task 4.1** (cache bump) -- after all JS changes are done
10. **Task 4.2** (documentation) -- last
11. **Phase 5** (verification) -- after everything

Parallelization opportunities:
- Tasks 1.1 and 2.1 are independent (backend helpers vs HTML markup)
- Tasks 1.2 and 1.3 share the dependency on 1.1 but are independent of each other
- Tasks 2.1, 2.3, and 3.1 are all HTML/CSS with no backend dependency
- Tasks 2.2 and 3.2 are independent once their respective dependencies are met

Incremental approach: build the file browser flow end-to-end first (Phase 1 + Phase 2), verify it works, then add the artefacts integration (Phase 3). This way, if Phase 3 hits issues, Phase 2 is already working and usable.

## Edge Cases & Challenges

1. **Large files**: Cap whole-file edit at 500 lines. Show a toast with a clear message telling the user to select a region. The 500-line limit is checked server-side so it can't be bypassed.

2. **Binary files**: Disable the AI Edit button when the file is detected as binary. The file browser already has binary detection; reuse the same `is_binary` flag from the file read response.

3. **LLM response without code fences**: The `extract_code_from_response()` helper uses a regex fallback. If no ``` markers are found, it returns the full response text with leading/trailing whitespace stripped. This handles models that occasionally skip the fencing.

4. **LLM adds explanation outside code fence**: The extraction regex finds the first ``` and the last ``` in the response and takes only what's between them. Any preamble ("Here's the edited code:") or postscript ("I changed X to Y because...") is discarded.

5. **CodeMirror selection is 0-indexed**: CodeMirror's `getCursor()` returns 0-indexed line numbers. The backend expects 1-indexed lines. The frontend must add 1 when building the request payload. Partial line selections (where the cursor is in the middle of a line) should be expanded to full lines by setting `ch` to 0 for the start and to the end of the line for the end.

6. **File changed on disk during edit**: The `base_hash` in the response lets the frontend detect this. If the user accepts an edit but the file was modified on disk between the request and the accept, the hash won't match. For v1 this is low priority since it's a single-user tool, but the hash is there for future use.

7. **No conversation open**: `getConversationIdFromUrl()` returns null. The "Include conversation context" checkbox is greyed out and disabled. The `conversation_id` field is omitted from the request payload.

8. **Deep context adds latency**: When the user checks "Deep context extraction", show a spinner with "Extracting context..." text. The `retrieve_prior_context_llm_based` call takes 2-5 seconds. The UI should remain responsive during this time (the POST is async).

9. **Artefacts textarea vs CodeMirror**: The artefacts editor uses a plain `<textarea>` with `selectionStart`/`selectionEnd` properties (character offsets). Converting to line numbers requires counting newlines in the text before each offset. The file browser uses CodeMirror with `getCursor()` returning `{line, ch}` objects. Different selection APIs, but both produce the same `{start_line, end_line}` contract for the backend.

10. **Concurrent edits**: If the user changes the file in the editor while an AI edit request is in flight, the diff preview will be based on the snapshot at request time. Accepting the edit will replace content in the current editor state, which may have diverged. Mitigation for v1: when the user clicks Accept, compare the current editor content at the selection range against the `original` text from the response. If they differ, show a warning: "File content changed since the edit was generated. Apply anyway?"

11. **Escape key conflicts**: The file browser modal already uses Escape to close (with dirty check). The AI Edit overlay should intercept Escape first (closing the overlay) before it bubbles up to the modal close handler. Use `stopPropagation()` on the overlay's Escape handler.

12. **Cmd+K browser conflict**: On macOS, Cmd+K in some browsers focuses the address bar or creates a hyperlink. The CodeMirror `extraKeys` handler and the textarea keydown handler must call `preventDefault()` to suppress the browser default.

## Alternatives Considered

1. **JSON operations (like artefacts)**: Rejected for the file browser. The artefacts pipeline uses structured JSON operations (`replace_lines`, `insert_after`, etc.) which have 4 failure modes: malformed JSON, wrong line numbers, conflicting operations, and off-by-one errors. For the file browser, asking the LLM to return plain replacement text is simpler and more reliable. Artefacts keeps JSON ops for backward compatibility and because its per-hunk diff UI depends on them.

2. **Single-phase (no diff preview)**: Rejected. Users need to see what changed before the edit is applied. This is the core insight from Cursor's UX: the diff preview builds trust and lets users catch LLM mistakes before they land. Skipping the preview would make the feature feel dangerous.

3. **Per-hunk selection in file browser**: Rejected. The artefacts modal already provides per-hunk accept/reject in its Diff tab. Rebuilding that in the file browser adds complexity for marginal benefit. The file browser's simpler accept-all/reject-all flow is sufficient for its use case.

4. **Reuse artefacts endpoint directly**: Rejected. The artefacts endpoint is tightly coupled to `artefact_id` and `conversation_id`. File browser files are server-local paths that may not correspond to any artefact. Shared helpers (`llm_edit_utils.py`) are the right abstraction level: reuse the prompt building and response parsing without coupling the two systems.

5. **Always use `retrieve_prior_context_llm_based`**: Rejected. It adds 2-5 seconds of latency to every edit. Most edits ("rename this variable", "add a docstring", "convert to list comprehension") don't need conversation history at all. Making it opt-in via a checkbox respects the user's time while keeping the capability available for edits that genuinely need context.

6. **Streaming the LLM response**: Considered but deferred. Streaming would let the user see the replacement text as it generates, but the diff preview needs the complete response to compute. Streaming would require buffering the full response before showing the diff anyway, so the UX benefit is minimal. A spinner with "Generating..." is sufficient for v1.

7. **Inline diff in CodeMirror (like VS Code)**: Considered but deferred. VS Code shows inline diffs with green/red gutters directly in the editor. This would require CodeMirror plugins or custom gutter rendering. The overlay diff preview is simpler to implement and still gives the user a clear view of changes. Inline diff could be a v2 enhancement.

## Key Files

Files that will be created or modified:

| File | Status | Purpose |
|------|--------|---------|
| `endpoints/llm_edit_utils.py` | NEW | Shared helpers: prompt building, context gathering, response parsing, hashing |
| `endpoints/file_browser.py` | MODIFIED | New `POST /file-browser/ai-edit` endpoint |
| `endpoints/artefacts.py` | MODIFIED | Add `deep_context` support to `propose_edits`, import shared helpers |
| `interface/interface.html` | MODIFIED | AI Edit button, instruction overlay, diff preview overlay (both file browser and artefacts) |
| `interface/file-browser-manager.js` | MODIFIED | AI Edit logic: show/hide overlays, generate, accept/reject, diff rendering, Cmd+K shortcut |
| `interface/artefacts-manager.js` | MODIFIED | Cmd+K shortcut, overlay handler, feed into existing proposeEdits pipeline |
| `interface/style.css` | MODIFIED | Diff coloring classes, overlay modal styles |
| `interface/service-worker.js` | MODIFIED | Cache version bump |
| `documentation/features/file_browser/README.md` | MODIFIED | Document AI Edit feature |
| `documentation/features/conversation_artefacts/README.md` | MODIFIED | Document Cmd+K shortcut |
