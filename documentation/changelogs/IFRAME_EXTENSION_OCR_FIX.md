# Iframe Extension & OCR Fix Changelog

**Date**: February 27, 2026  
**Scope**: `extension-shared/`, `extension-iframe/`, `extension/`, `interface/`, `endpoints/`

---

## Summary

Full-page OCR capture for SharePoint Word Online (and similar cross-origin iframe document viewers) was broken in two separate ways: the scroll capture pipeline never found the scrollable element because it only probed the top frame, and the OCR backend returned empty results because the configured vision model does not support image input. Both were fixed. Additional fixes: tab-picker modal backdrop, content-viewer-modal height, and DOM/OCR split button.

---

## Bug 1: SharePoint Full-Page OCR — No Scroll Target (Cross-Origin Iframe)

### Symptom
Capture reported 1/14 pages, returned only page title and URL. Logs showed `findScrollTarget: NO scroll target found` in the top frame, and capture aborted.

### Root Cause
SharePoint Word Online renders the document inside a cross-origin iframe (`usc-word-edit.officeapps.live.com`). The extractor content script was only injected into and queried on the top-level SharePoint frame, which has no scrollable document container. The iframe frame was never probed.

### Fix — `extension-shared/operations-handler.js`

Added `findCaptureContextInFrames(tabId, chromeApi)`:
- Calls `chrome.webNavigation.getAllFrames({ tabId })` to enumerate all subframes
- For each subframe, injects `extractor-core.js` via `chrome.scripting.executeScript({ target: { tabId, frameIds: [frameId] } })`
- Sends `INIT_CAPTURE_CONTEXT` to each subframe via `chrome.tabs.sendMessage(tabId, msg, { frameId })`
- Returns the first subframe that responds with `ok: true`, along with its `captureFrameId`, `captureContextId`, `captureContextMetrics`, and `captureContextTarget`

Updated `captureTabFullOcr` flow:
1. Try `INIT_CAPTURE_CONTEXT` on top frame
2. If top frame returns `NO_SCROLL_TARGET` → call `findCaptureContextInFrames`
3. Pass `captureFrameId` + pre-supplied context to `captureFullPage`
4. All subsequent `SCROLL_CONTEXT_TO` and `RELEASE_CAPTURE_CONTEXT` messages routed to `{ frameId: captureFrameId }`

### Fix — `extension-shared/full-page-capture.js`

Complete rewrite to thread subframe support:
- Accepts `captureFrameId` option — passes as `{ frameId }` to every `chrome.tabs.sendMessage` call
- Accepts `captureContextId`, `captureContextMetrics`, `captureContextTarget` — skips `INIT_CAPTURE_CONTEXT` entirely when pre-supplied
- Added logging at every step: INIT result, each scroll position, `captureVisibleTab` success/fail, rate-limit retries

### Fix — `extension-shared/extractor-core.js`

`findKnownSelectorTarget()` was extended to try `canScrollByProbe()` as a fallback when `isScrollableCandidate()` rejects an element due to `overflow:hidden`. SharePoint's `.WACViewPanel` uses `overflow:hidden` on its scroll container but is scrollable via `scrollTop`. Previously it failed stage 1 and nothing matched.

Added comprehensive logging to all 5 stages of `findScrollTarget()` and to `scrollContextTo()`.

### Fix — Manifests

`webNavigation` permission added to both `extension/manifest.json` and `extension-iframe/manifest.json`. Required for `chrome.webNavigation.getAllFrames`.

### Fix — `extension-iframe/background/service-worker.js`

- Added `webNavigation.getAllFrames` to the `chromeApi` adapter
- Updated `tabs.sendMessage` wrapper to accept an `opts` parameter (passed as the third argument for `{ frameId }` routing)
- Added port lifecycle logging

---

## Bug 2: OCR Returns Empty — Wrong Vision Model

### Symptom
All 15 OCR calls returned empty string. Backend logs showed: `OCR failed for image 0: google/gemini-2.5-flash-lite is not supported for image input.`

### Root Cause
`OCR_VISION_MODEL` in `endpoints/ext_page_context.py` defaulted to `google/gemini-2.5-flash-lite`, which the OpenRouter API rejects for image/vision input. The `.catch` in the frontend swallowed the error silently, returning `''`.

### Fix — `endpoints/ext_page_context.py`

Changed default:
```python
# Before
OCR_VISION_MODEL: str = os.getenv("EXT_OCR_MODEL", "google/gemini-2.5-flash-lite")

# After
OCR_VISION_MODEL: str = os.getenv("EXT_OCR_MODEL", "google/gemini-2.5-flash")
```

`google/gemini-2.5-flash` supports vision/image input. The env var `EXT_OCR_MODEL` can still override this.

---

## Bug 3: Tab-Picker Auto-Checking Tab Checkboxes

### Symptom
When the tab-picker modal opened, tabs whose URLs matched known full-OCR sites (SharePoint, Google Docs, etc.) were automatically checked, selecting them for capture without user action.

### Root Cause
`_renderTabs()` in `interface/tab-picker-manager.js` included a block that called `$('#tab-check-' + idx).prop('checked', true)` for any tab where `_getDefaultMode(url) === 'full_ocr'`.

### Fix — `interface/tab-picker-manager.js`

Removed the auto-checkbox block. The mode dropdown still auto-selects `Full OCR` for known sites via `_getDefaultMode()`. Tab checkboxes are only set by the user or the global Select All/None buttons.

---

## Bug 4: Tab-Picker Modal Backdrop Overlaying Everything

### Symptom
Clicking `#ext-multi-tab` showed a `modal-backdrop fade show` div overlaying the page with no visible modal content.

### Root Cause
Two unclosed `</div>` tags in `interface/interface.html` — one for `#global-docs-modal` and one for `#chat-settings-modal` — caused `#tab-picker-modal` to be nested inside those hidden modals. Bootstrap's backdrop rendered but the content was invisible inside closed parents.

### Fix — `interface/interface.html`

Added missing `</div>` closers for both affected modals before the `#tab-picker-modal` definition.

---

## Feature: DOM / OCR / Full-Page OCR Split Button

### Change
The single `#ext-extract-page` button in the page-context panel was replaced with a Bootstrap 4.6 split-button dropdown group `#ext-extract-page-group`:

- `#ext-extract-dom` — DOM text extraction (fast, ~1s)
- `#ext-extract-ocr` — Single viewport screenshot → OCR
- `#ext-extract-full-ocr` — Scroll + multiple screenshots + OCR (for canvas/iframe doc apps)

### Files
- `interface/interface.html`: new split-button group HTML; hide logic updated to target `#ext-extract-page-group`
- `interface/page-context-manager.js`: three click handlers; `_resolveCurrentTabId()` helper; `_captureAndOcrPipelined()` function; `capturePageWithOcr()` public method

---

## Fix: `content-viewer-modal` Too Short

### Symptom
When opened from the page-context panel, `#content-viewer-modal` was very short and barely showed any content.

### Root Cause
- Modal container: `max-height:85vh` (collapses to content height when content is short on first open)
- Scroll wrapper: missing `min-height:0` (flex shrink broken without it)
- Textarea: `max-height:55vh` hard cap + `resize:vertical` instead of filling available space

### Fix — `interface/interface.html`

| Element | Before | After |
|---------|--------|-------|
| `.cv-modal-content` | `max-height:85vh` | `height:90vh` |
| scroll wrapper `<div>` | _(no min-height)_ | `min-height:0` added |
| `#cv-text` textarea | `max-height:55vh; resize:vertical` | `height:100%; resize:none` |

---

## Files Modified

| File | Change |
|------|--------|
| `extension-shared/operations-handler.js` | `findCaptureContextInFrames()`; subframe probe in `captureTabFullOcr`; `captureFrameId` threading; logging |
| `extension-shared/full-page-capture.js` | Full rewrite: subframe `frameId` routing; pre-supplied context skip; logging |
| `extension-shared/extractor-core.js` | `canScrollByProbe()` fallback in `findKnownSelectorTarget()`; stage logging |
| `extension-iframe/background/service-worker.js` | `webNavigation.getAllFrames` in chromeApi; `opts` param in `sendMessage`; port logging |
| `extension/manifest.json` | `webNavigation` permission |
| `extension-iframe/manifest.json` | `webNavigation` permission |
| `endpoints/ext_page_context.py` | OCR model default: `gemini-2.5-flash-lite` → `gemini-2.5-flash` |
| `interface/tab-picker-manager.js` | Removed auto-checkbox; kept mode dropdown auto-select |
| `interface/page-context-manager.js` | Split button handlers; `_resolveCurrentTabId()`; `capturePageWithOcr()` |
| `interface/interface.html` | Split button group; 2 missing `</div>` fixes; content-viewer-modal height fixes |

---

## Feature: OCR Comment Extraction (Mar 2026)

### Overview

OCR capture now supports extracting document comments, review annotations, margin notes, and sticky-note overlays (e.g. Microsoft Word/PDF review comments) alongside the main document content. This applies to all three OCR modes: single screenshot OCR, full-page scroll OCR, and multi-tab OCR.

### Design

Two separate LLM prompt strategies are used:

- **Clean mode** (default, `extract_comments=false`): uses `_build_ocr_messages_clean()` which explicitly instructs the model to ignore comment bubbles and return only the main document text as plain text. This is the same fast path as before.
- **Comments mode** (`extract_comments=true`): uses `_build_ocr_messages_with_comments()` which instructs the model to return a JSON object `{"text": "...", "comments": [{"anchor": "...", "body": "..."}]}`. The `text` key holds the clean main content; `comments` is an array of annotation objects where `anchor` is a short quote of the nearby text the comment refers to, and `body` is the comment text itself.

The backend parses the JSON response from the comments prompt, strips markdown fences if the model wraps the JSON, and falls back gracefully to treating the whole response as plain text if parsing fails.

### UI: Extract Comments Toggle

Two checkboxes were added, one per entry point:

- **`#ext-extract-comments-toggle`** — inside the `#ext-extract-page-group` split-button dropdown (below a divider, after the Full Page OCR item). Applies to all three modes in the single-tab flow: DOM (ignored), OCR (screenshot), and Full Page OCR (scroll).
- **`#tab-picker-extract-comments`** — in the tab-picker modal footer (left-aligned, `mr-auto`). Applies to all selected tabs in the multi-tab capture flow.

Both checkboxes default to unchecked (clean mode). The state is read at the moment the capture button is clicked and applies uniformly to all screenshots in that capture run.

### Data Flow

```
UI checkbox → extractComments flag
    ↓
POST /ext/ocr  { images: [...], extract_comments: true }
    ↓
_ocr_single_image(extract_comments=True)
    → _build_ocr_messages_with_comments(image_data_url)
    → call_llm(..., stream=False)
    → JSON parse { text, comments[] }
    ↓
Response: { text: combined_text, pages: [{index, text, comments: [{anchor, body}]}], extract_comments: true }
    ↓
JS: ocrPagesData[i].comments stored on each page
    ↓
content-viewer.js _buildPages():
    pageText + "\n--- COMMENTS ---\n[Re: anchor]\nbody\n..."
```

### Error Handling

- If the model returns non-JSON (prose, partial JSON, fenced markdown): the raw response is used as `text`, `comments` defaults to `[]`, and a warning is logged: `OCR image N: comments prompt returned non-JSON, falling back to raw text`.
- Markdown fences (`` ```json ... ``` ``) are stripped before JSON parsing.

### Files Modified

| File | Change |
|------|--------|
| `endpoints/ext_page_context.py` | Added `import json`; added `_build_ocr_messages_clean()` (plain text prompt) and `_build_ocr_messages_with_comments()` (JSON prompt); updated `_ocr_single_image()` to accept `extract_comments` param; updated `/ext/ocr` endpoint to read `extract_comments` from request, pass it through, and include it in response; updated docstrings |
| `interface/interface.html` | Added `#ext-extract-comments-toggle` checkbox in `#ext-extract-page-group` dropdown (after divider); added `#tab-picker-extract-comments` checkbox in tab-picker modal footer |
| `interface/page-context-manager.js` | `_ocrSingleScreenshot()` accepts and sends `extractComments`; `_captureAndOcrPipelined()` stores `comments` per page in `ocrPagesData`; OCR and Full OCR click handlers read checkbox; `setSingleContext()` stores `extractComments` flag; `capturePageWithOcr()` accepts `extractComments` |
| `interface/tab-picker-manager.js` | `_ocrSingleScreenshot()` accepts and sends `extractComments`; `_startCapture()` reads checkbox; screenshot progress handler passes flag; `_assembleResults()` accepts flag, preserves `comments` per page, adds `extractComments` to result objects |
| `interface/content-viewer.js` | `_buildPages()` OCR case: appends `--- COMMENTS ---` block with `[Re: anchor]` + body lines after page text when `ocrPage.comments` is non-empty |
