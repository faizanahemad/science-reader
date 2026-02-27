# Multi-Tab Scroll Capture

**Feature**: Multi-tab content capture with scroll+screenshot+OCR for document apps  
**Status**: Implemented  
**Last Updated**: February 27, 2026

---

## Overview

The multi-tab scroll capture feature extends the extension's multi-tab reader to capture content from other browser tabs using the scroll+screenshot+OCR pipeline. This is essential for document apps (Google Docs, Word Online, Quip, SharePoint, Notion) where content is canvas-rendered or hidden in complex DOM structures that regular DOM extraction cannot reach.

The feature supports 4 capture modes per tab, handles tab switching for OCR capture (since `chrome.tabs.captureVisibleTab()` only works on the active tab), and restores the original tab after screenshots are taken — before waiting for OCR, since OCR is just API calls that don't need the tab active.

## Capture Modes

| Mode | UI Label | Behavior |
|------|----------|----------|
| `auto` | 🔄 Auto | Try DOM extraction first. Fall back to Full OCR if content < 500 chars, `needsScreenshot` flag is set, or URL matches known doc-app patterns. |
| `simple` | 📄 DOM | DOM text extraction only. Fast (~1s/tab). Works for regular web pages. |
| `ocr` | 📷 OCR | Take a single viewport screenshot and run OCR. Good for short doc-app pages. |
| `scroll` | 📸 Full OCR | Scroll+multiple screenshots+pipelined OCR. Slow (~10-30s/tab) but captures full document content from canvas-rendered apps. |

### Settings

- **Global default**: `multiTabCaptureMode` in Settings panel (dropdown: Auto/Simple/OCR/Scroll)
- **Per-tab override**: Dropdown per tab row in the tab selection modal
- **Auto-detection**: Known doc-app URLs auto-default to Full OCR when global mode is `auto`
- Persisted in `chrome.storage.local` via `Storage.setSettings()`

## Architecture

### 4-Phase Pipeline (`handleTabSelection()`)

```
Phase 1: Parallel DOM extraction for all tabs (with retry on failure)
    ↓
Phase 2: Auto-mode fallback detection
    (check content length < 500, needsScreenshot flag, URL patterns)
    ↓
Phase 3: Sequential screenshot capture
    - Save original tab ID
    - For each capture tab:
        - Activate tab (chrome.tabs.update)
        - Pre-inject content script if needed (PING test)
        - Show on-page toast overlay
        - Capture screenshots (single or scroll)
        - Collect deferred OCR promises
    - Restore original tab (try/finally, guaranteed)
    ↓
Phase 3b: Await deferred OCR
    (original tab already restored, OCR runs as background API calls)
    ↓
Phase 4: Assemble results into state.pageContext + state.multiTabContexts
```

### Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deferred OCR | Screenshots captured immediately, OCR awaited after tab restoration | User sees their original tab restored within seconds; OCR runs as background API calls |
| Tab restoration | `try/finally` block | Guarantees restoration even on errors/cancellation |
| Content script injection | PING test + explicit `chrome.scripting.executeScript` | Content scripts aren't injected on pre-existing tabs after extension reload |
| On-page toast | `chrome.scripting.executeScript` with inline function | Shows progress directly on the captured tab |

### Deferred OCR Flow

```
Tab A (original) → Tab B (capture target)
    - Activate Tab B
    - Scroll + capture screenshots (fast, ~1s each)
    - Fire OCR API call per screenshot (non-blocking)
    - Collect OCR promises (don't await yet)
→ Tab C (next capture target, if any)
    - Same process
→ Tab A (restore original)
    - NOW await all OCR promises
    - Assemble results
```

This means:
- Tab switches last only as long as screenshots take (~5-15s per tab)
- OCR processing (~10-30s per tab) happens while user is back on their original tab
- Total wall-clock time is reduced since OCR overlaps with user's continued work

## Document App URL Patterns

`DOC_APP_URL_PATTERNS` in `sidepanel.js` contains 16 regex patterns:

- `docs.google.com/document`, `docs.google.com/spreadsheets`, `docs.google.com/presentation`
- `word.cloud.microsoft`, `onedrive.live.com/edit`, `sharepoint.com*.aspx`
- `quip.com`, `notion.so`, `notion.site`
- `coda.io/d/`, `airtable.com`
- `overleaf.com/project`
- `confluence.*/wiki`
- `dropboxpaper.com`, `paper.dropbox.com`
- `docs.zoho.com`

## Progress UI

During capture, the tab modal stays open and switches from tab selection to a progress view:

- Per-tab status: ⏳ pending → 📷 active → ✅ done / ❌ error / ⏭️ skipped
- Per-tab detail: "Extracting DOM...", "Screenshot 3/8", "OCR pending...", "OCR (12345 chars)"
- Cancel button (`btn-danger` style) sets `state.multiTabCaptureAborted` flag
- On cancellation: current capture stops, already-captured tabs are kept, remaining tabs shown as skipped

## Bug Fix: createNewConversation Wiping Multi-Tab Context

### Problem

On first extension load (no conversation exists), after `handleTabSelection()` sets `state.pageContext` with multi-tab content:
1. User sends first message
2. `sendMessage()` calls `createNewConversation()` (because `!state.currentConversation`)
3. `createNewConversation()` calls `removePageContext()` → wipes `state.pageContext` to `null`
4. `sendMessage()` sees no pageContext → auto-attaches single-tab content only

### Fix

Save/restore pattern at all 3 implicit `createNewConversation()` call sites:
- `sendMessage()` (~line 1190)
- `handleScriptGeneration()` (~line 1427)
- `handleQuickSuggestion()` (~line 3310)

```javascript
// Before createNewConversation
const savedPageContext = state.pageContext;
const savedMultiTabContexts = state.multiTabContexts ? [...state.multiTabContexts] : [];
const savedSelectedTabIds = state.selectedTabIds ? [...state.selectedTabIds] : [];

await createNewConversation();

// Restore if wiped
if (savedPageContext && !state.pageContext) {
    state.pageContext = savedPageContext;
    state.multiTabContexts = savedMultiTabContexts;
    state.selectedTabIds = savedSelectedTabIds;
    console.log('[Sidepanel] Restoring pageContext after auto-creating conversation');
}
```

The user-initiated "New Chat" button correctly clears context (no save/restore there).

## Files Modified

| File | Changes |
|------|---------|
| `extension/sidepanel/sidepanel.js` | New state fields (`ocrCache`, `multiTabCaptureAborted`, `multiTabCaptureMode`); `DOC_APP_URL_PATTERNS` constant (16 patterns); `isDocAppUrl()` helper; `captureTabWithScrollOcr()` function with `deferOcr` option; complete rewrite of `handleTabSelection()` with 4-phase pipeline; `showTabModal()` with per-tab capture mode dropdowns; save/restore pattern at 3 `createNewConversation()` call sites |
| `extension/sidepanel/sidepanel.html` | Multi-tab capture mode dropdown in settings; per-tab capture mode `<select>` in tab modal; progress view (`tab-capture-progress`, `tab-progress-list`); abort button (`abort-tab-capture`, `btn-danger`) |
| `extension/sidepanel/sidepanel.css` | `.tab-capture-mode` dropdown styles; `.tab-capture-progress`, `.tab-progress-list` progress view; `.btn-danger` style; `.spin` animation; per-status classes (`.done`, `.active`, `.error`) |
| `extension/extension_implementation.md` | State object updated, new functions documented, Multi-Tab section expanded |
| `extension/README.md` | Feature bullet updated with 4 modes and deferred OCR |
| `documentation/planning/plans/multi-tab-scroll-capture.plan.md` | Bug fix documented, status updated to implemented |

## Related Existing Features

- **Inner scroll container detection** (`extractor.js`): 5-stage pipeline detecting scrollable containers in 15+ apps. Used by the scroll-capture pipeline to find the right element to scroll.
- **Pipelined OCR** (`captureAndOcrPipelined()` in `sidepanel.js`): Per-screenshot OCR dispatch during capture. Extended with `targetTabId` parameter for cross-tab use and `deferOcr` option for deferred OCR promises.
- **OCR context preservation**: `isOcr` guards on 12+ `state.pageContext` assignment sites prevent accidental overwrite of OCR content.
- **Content viewer**: Supports mixed DOM+OCR multi-tab results with per-tab pagination.

---

## Bug Fix: Cross-Origin Iframe Scroll Capture (Feb 2026)

### Problem

SharePoint Word Online (and similar document viewers) render content inside a **cross-origin iframe** (`usc-word-edit.officeapps.live.com`). The top-level SharePoint page has no scrollable container — the document lives in the subframe. The previous implementation only injected the extractor content script into the top frame, which returned `NO_SCROLL_TARGET` immediately and produced only the page title + URL as extracted content.

Additionally, the OCR pipeline was using `google/gemini-2.5-flash-lite` as the default vision model, which does not support image input — causing all OCR calls to silently return empty strings.

### Root Causes

1. **Subframe not probed**: `captureTabFullOcr` sent `INIT_CAPTURE_CONTEXT` only to the top frame. When it failed, capture aborted without checking subframes.
2. **Wrong OCR model**: `OCR_VISION_MODEL` defaulted to `google/gemini-2.5-flash-lite`, which the OpenRouter API rejects for image input.
3. **Auto-checkbox**: The tab-picker modal was auto-checking tab checkboxes for known full-OCR sites, which should only auto-select the mode dropdown — not select which tabs to include.

### Fix: Sub-frame Probe in `findCaptureContextInFrames`

A new helper `findCaptureContextInFrames(tabId, chromeApi)` was added to `extension-shared/operations-handler.js`:

```javascript
// Enumerate all subframes via chrome.webNavigation.getAllFrames
// For each subframe, inject extractor-core.js via chrome.scripting.executeScript
//   with target: { tabId, frameIds: [frameId] }
// Send INIT_CAPTURE_CONTEXT to each subframe until one succeeds
// Return { captureFrameId, captureContextId, captureContextMetrics, captureContextTarget }
```

The `captureTabFullOcr` flow is now:

```
1. Inject extractor-core.js into top frame
2. Send INIT_CAPTURE_CONTEXT to top frame
3. If top frame returns NO_SCROLL_TARGET:
   → Call findCaptureContextInFrames() to probe all subframes
   → First subframe that returns ok:true wins
4. Pass captureFrameId + pre-supplied context to captureFullPage()
5. All subsequent SCROLL_CONTEXT_TO / RELEASE_CAPTURE_CONTEXT messages
   are routed to that subframe via { frameId: captureFrameId }
```

This required `webNavigation` permission in both `extension/manifest.json` and `extension-iframe/manifest.json`.

### Fix: `full-page-capture.js` Sub-frame Support

`extension-shared/full-page-capture.js` was updated to accept:
- `captureFrameId` — routes all `chrome.tabs.sendMessage` calls to the specific subframe
- `captureContextId`, `captureContextMetrics`, `captureContextTarget` — pre-supplied context from the probe, skipping the `INIT_CAPTURE_CONTEXT` step entirely

### Fix: `extractor-core.js` Probe Fallback

`findKnownSelectorTarget()` in `extension-shared/extractor-core.js` was extended to try `canScrollByProbe()` as a fallback when `isScrollableCandidate()` rejects an element due to `overflow:hidden`. This covers `.WACViewPanel` in SharePoint Word Online, which uses `overflow:hidden` on the scroll container but is in fact scrollable via `scrollTop`.

### Fix: OCR Model

`OCR_VISION_MODEL` in `endpoints/ext_page_context.py` was changed from `google/gemini-2.5-flash-lite` to `google/gemini-2.5-flash`. The `-lite` model does not support image/vision input. Override via `EXT_OCR_MODEL` env var.

### Fix: Tab-Picker Auto-Select Mode Only

In `interface/tab-picker-manager.js`, the `_renderTabs()` function previously auto-checked the tab checkbox (`#tab-check-{idx}`) for any tab whose URL matched `FULL_OCR_SITES`. This was removed. The mode dropdown still auto-selects `Full OCR` for known sites — the user must still manually tick which tabs to include.

### Fix: DOM/OCR/Full-Page OCR Split Button

The single `#ext-extract-page` button in the page-context panel (`interface/interface.html`) was replaced with a Bootstrap 4.6 split-button dropdown group (`#ext-extract-page-group`) with three options:
- **DOM** (`#ext-extract-dom`): fast DOM text extraction
- **OCR** (`#ext-extract-ocr`): single viewport screenshot → OCR
- **Full Page OCR** (`#ext-extract-full-ocr`): scroll + multi-screenshot + OCR

Handlers wired in `interface/page-context-manager.js`.

### Fix: Tab-Picker Modal Backdrop

Two missing `</div>` closers were found in `interface/interface.html` — one for `#global-docs-modal` and one for `#chat-settings-modal`. These caused `#tab-picker-modal` to be nested inside hidden parents, making the Bootstrap backdrop div overlay everything while the modal content was invisible.

### Fix: `content-viewer-modal` Height

The `#content-viewer-modal` in `interface/interface.html` was too short when opened from the page-context panel because:
- Modal container was `max-height:85vh` (shrinks to content) → changed to `height:90vh`
- The flex scroll wrapper lacked `min-height:0` (required for flex shrink) → added
- The textarea had a hard `max-height:55vh` cap → changed to `height:100%` with `resize:none`

### Files Modified

| File | Changes |
|------|---------|
| `extension-shared/operations-handler.js` | Added `findCaptureContextInFrames()`; updated `captureTabFullOcr` and `captureOneTab` to probe subframes; added `captureFrameId` threading through all message sends; comprehensive logging |
| `extension-shared/full-page-capture.js` | Complete rewrite: accepts `captureFrameId`, `captureContextId`, `captureContextMetrics`, `captureContextTarget`; routes all `sendMessage` calls via `{ frameId }`; skips `INIT_CAPTURE_CONTEXT` when context pre-supplied; added logging throughout |
| `extension-shared/extractor-core.js` | `findKnownSelectorTarget()` uses `canScrollByProbe()` fallback for `overflow:hidden` elements; logging added to all 5 stages of `findScrollTarget()` and `scrollContextTo()` |
| `extension-iframe/background/service-worker.js` | Added `webNavigation.getAllFrames` to `chromeApi`; `tabs.sendMessage` accepts `opts` parameter for `{ frameId }`; port lifecycle logging |
| `extension/manifest.json` | Added `webNavigation` permission |
| `extension-iframe/manifest.json` | Added `webNavigation` permission |
| `endpoints/ext_page_context.py` | `OCR_VISION_MODEL` default changed from `google/gemini-2.5-flash-lite` to `google/gemini-2.5-flash` |
| `interface/tab-picker-manager.js` | Removed auto-checkbox logic from `_renderTabs()`; kept mode dropdown auto-select; added `FULL_OCR_SITES` array and `_getDefaultMode()` |
| `interface/page-context-manager.js` | Split button handlers (`#ext-extract-dom`, `#ext-extract-ocr`, `#ext-extract-full-ocr`); added `_resolveCurrentTabId()`, `_captureAndOcrPipelined()`, `capturePageWithOcr()` |
| `interface/interface.html` | `#ext-extract-page` → `#ext-extract-page-group` split-button; fixed 2 unclosed `</div>` before `#tab-picker-modal`; `#content-viewer-modal` height fixes |
