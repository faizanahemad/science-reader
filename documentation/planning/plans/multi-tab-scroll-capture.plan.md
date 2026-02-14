# Multi-Tab Scroll Capture — Feature Plan

**Goal**: Allow the extension's multi-tab reader to capture content from other tabs using the scroll+screenshot+OCR pipeline (not just DOM extraction), making it a useful "document writing helper" that can pull context from Google Docs, Word Online, Quip, SharePoint, and similar apps across multiple tabs.

**Status**: Implemented (Milestones 1-4 complete). Critical first-load bug fixed.

---

## 0. Bug Fix: createNewConversation Nullifying Multi-Tab Context

**Bug**: On first extension load (no conversation exists yet), after `handleTabSelection()` sets multi-tab `state.pageContext`, the user sends a message → `sendMessage()` calls `createNewConversation()` (because `!state.currentConversation`) → `createNewConversation()` calls `removePageContext()` → wipes the multi-tab context to `null` → `sendMessage()` then auto-attaches single-tab content, overwriting the user's multi-tab selection.

**Debug trace confirming the bug**:
```
[DEBUG pageContext] SET: null → isMultiTab=true len=49487          ← handleTabSelection sets it
[DEBUG pageContext] SET: isMultiTab=true len=49487 → null          ← createNewConversation nullifies it
[DEBUG pageContext] stack: set → removePageContext → createNewConversation
[Sidepanel] Auto-attaching page content (no existing context)      ← sendMessage sees null, overwrites
[DEBUG pageContext] SET: null → isMultiTab=false len=3106          ← single-tab auto-attach
```

**Fix**: In `sendMessage()`, `handleScriptGeneration()`, and `handleQuickSuggestion()` — all call sites where `createNewConversation()` is called as an implicit side effect (not user-initiated) — save `state.pageContext`, `state.multiTabContexts`, and `state.selectedTabIds` before the call, then restore them after. The user-initiated "New Chat" button call (line 340, 432) correctly continues to clear context.

**Files changed**: `extension/sidepanel/sidepanel.js` — three call sites updated with save/restore pattern.

**Also removed**: Debug proxy on `state.pageContext` (was temporary for tracing).

---

## 1. Problem Statement

The multi-tab reader (`handleTabSelection()` in `sidepanel.js`) currently uses **DOM extraction only** (`EXTRACT_FROM_TAB` → `EXTRACT_PAGE`). This works for regular web pages but fails for document apps (Google Docs, Office Word Online, Quip, Notion, SharePoint) where content is canvas-rendered or hidden in complex DOM structures. We already have a scroll+screenshot+OCR pipeline that handles these apps on the *active* tab — this feature extends it to **any selected tab**.

## 2. Chrome API Constraints

### Why this is non-trivial

- **`chrome.tabs.captureVisibleTab(windowId)`** — captures whatever is currently visible in the browser window. A background tab is **not rendered** — there are no pixels to capture.
- **There is no Chrome API to screenshot a non-active tab.** `chrome.tabCapture` captures video streams, not still images. `chrome.desktopCapture` captures the entire screen with a user permission prompt each time.
- **Content script messages work on background tabs** — DOM extraction can run in parallel on any tab. But scroll+capture is fundamentally a visual operation requiring the tab to be active.
- **The sidepanel persists across tab switches** — `manifest.json` sets `side_panel.default_path` at the extension level (not per-tab), so the sidepanel JS context survives `chrome.tabs.update(tabId, { active: true })`.

### Implication

**Scroll-capturing a non-active tab requires temporarily activating it.** The user will see tabs switching. This is unavoidable.

## 3. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Capture mode setting** | Global default in Settings + per-tab override in tab modal | Flexibility: mix DOM and scroll-OCR tabs in one selection |
| **Tab switching UX** | Show progress toast, switch tabs, capture, switch back | Chrome API limitation — no alternative. User confirmed this is acceptable |
| **Auto-detect mode** | Yes — three modes: simple, scroll, auto | Auto tries DOM first, falls back to scroll+OCR for document apps / short content |
| **Orchestrator** | Sidepanel (not service worker) | Sidepanel already drives pipelined capture, survives tab switches, has progress UI |

## 4. Capture Mode Settings

### 4.1 New Setting: `multiTabCaptureMode`

Added to `state.settings` and persisted via `Storage.setSettings()`:

```javascript
state.settings = {
    // ... existing ...
    multiTabCaptureMode: 'auto'  // 'simple' | 'scroll' | 'auto'
};
```

| Mode | Behavior |
|------|----------|
| `simple` | DOM extraction only (current behavior). Fast (~1s/tab). |
| `scroll` | Scroll+screenshot+OCR for every selected tab. Slow (~10-30s/tab) but works on canvas/doc apps. |
| `auto` | Try DOM extraction first. If result < 500 chars OR `needsScreenshot` flag is set OR URL matches known doc-app patterns, automatically fall back to scroll+OCR. |

### 4.2 Settings Panel UI

Add a new setting group in `sidepanel.html` between "Auto-include page content" and the divider:

```html
<div class="setting-group">
    <label for="multi-tab-capture-mode">Multi-tab capture mode</label>
    <select id="multi-tab-capture-mode" class="select">
        <option value="auto">Auto (detect doc apps)</option>
        <option value="simple">Simple (DOM only)</option>
        <option value="scroll">Scroll + OCR (all tabs)</option>
    </select>
    <div class="setting-help">
        How other tabs are captured. Auto tries DOM first and falls back to scroll+OCR for document apps.
    </div>
</div>
```

### 4.3 Per-Tab Override in Tab Modal

Each tab row in the selection modal gets a small capture mode badge/toggle:

```
┌──────────────────────────────────────────────────────┐
│ ☑ 📄 Google Docs - Project Plan           [📷 OCR ▾]│
│     docs.google.com/document/d/...                   │
│ ☑ 📄 Stack Overflow - React Hooks          [📄 DOM ▾]│
│     stackoverflow.com/questions/...                  │
│ ☑ 📄 Word Online - Meeting Notes           [🔄 Auto▾]│
│     onedrive.live.com/edit.aspx...                   │
└──────────────────────────────────────────────────────┘
```

- Default value comes from the global `multiTabCaptureMode` setting
- User can override per-tab via a small dropdown: `📄 DOM` / `📷 OCR` / `🔄 Auto`
- Known doc-app URLs could auto-default to `scroll` even if global is `simple`

## 5. Architecture

### 5.1 Enhanced `handleTabSelection()` Flow

```
User clicks "Add Selected" in tab modal
  │
  ├── Partition tabs by capture mode:
  │   ├── simpleTabs = tabs where mode == 'simple'
  │   ├── scrollTabs = tabs where mode == 'scroll'
  │   └── autoTabs = tabs where mode == 'auto'
  │
  ├── Phase 1: Extract simple + auto tabs via DOM (parallel)
  │   for each tab in simpleTabs + autoTabs:
  │     EXTRACT_FROM_TAB → get content
  │
  ├── Phase 2: Identify auto tabs needing scroll fallback
  │   autoTabs where: content.length < 500 || needsScreenshot || matchesDocAppUrl(url)
  │   → move to scrollTabs
  │
  ├── Phase 3: Scroll-capture tabs (sequential, requires tab activation)
  │   ├── Save current active tab ID (originalTabId)
  │   ├── For each tab in scrollTabs:
  │   │   ├── chrome.tabs.update(tabId, { active: true })
  │   │   ├── Wait for tab to render (~500ms + check document ready)
  │   │   ├── captureAndOcrPipelined(tabInfo, { onProgress })
  │   │   │   └── (scroll → screenshot → OCR per page, same as existing)
  │   │   └── Store result in contexts[]
  │   └── chrome.tabs.update(originalTabId, { active: true })
  │       (restore original tab)
  │
  └── Phase 4: Assemble results
      Combine all contexts into state.multiTabContexts + state.pageContext
      (same format as current: "## Tab: {title}\nURL: {url}\n\n{content}")
```

### 5.2 New Function: `captureTabWithScrollOcr(tabId, tabInfo, onProgress)`

This is the key new function. It:

1. Activates the target tab
2. Waits for it to render
3. Reuses the existing `captureAndOcrPipelined()` but targeting the specified tab (not just `active: true, currentWindow: true`)
4. Returns the OCR result
5. Does NOT restore the original tab (caller handles that after all tabs are done)

```javascript
/**
 * Activate a tab, run scroll+screenshot+OCR on it, return extracted text.
 *
 * IMPORTANT: This switches the active tab. Caller must restore the original tab.
 *
 * @param {number} tabId - Tab to capture
 * @param {Object} tabInfo - { url, title } for OCR context
 * @param {Function} onProgress - Progress callback
 * @returns {Promise<{content: string, pages: Array, meta: Object}|null>}
 */
async function captureTabWithScrollOcr(tabId, tabInfo, onProgress) { ... }
```

### 5.3 Adapting `captureAndOcrPipelined()` for Arbitrary Tabs

Currently `captureAndOcrPipelined()` finds the active tab:
```javascript
const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
tab = tabs[0];
```

For multi-tab capture, we need to pass the target tab ID explicitly. Two options:

**Option A (Recommended)**: Add an optional `targetTabId` parameter:
```javascript
async function captureAndOcrPipelined(extractResponse, options = {}) {
    const targetTabId = options.targetTabId;
    let tab;
    if (targetTabId) {
        tab = await chrome.tabs.get(targetTabId);
    } else {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        tab = tabs[0];
    }
    // ... rest unchanged
}
```

**Option B**: Always pass the tab, make caller responsible. Bigger refactor, no clear benefit.

### 5.4 Known Doc-App URL Patterns (for Auto Mode)

Reuse and extend the `KNOWN_SCROLL_SELECTORS` list from `extractor.js`:

```javascript
const DOC_APP_URL_PATTERNS = [
    /docs\.google\.com\/document/,
    /docs\.google\.com\/spreadsheets/,
    /docs\.google\.com\/presentation/,
    /word\.cloud\.microsoft/,       // Word Online (new URL)
    /onedrive\.live\.com\/edit/,    // Word/Excel/PPT Online (legacy URL)
    /sharepoint\.com.*\.aspx/,      // SharePoint documents
    /quip\.com\//,
    /notion\.so\//,
    /notion\.site\//,
    /coda\.io\/d\//,
    /airtable\.com\//,
    /overleaf\.com\/project/,
    /confluence\..*\/wiki/,
    /dropboxpaper\.com/,
];
```

When `auto` mode is active and the tab URL matches any pattern, default to `scroll` without trying DOM first (known to fail on these).

## 6. Progress UI

### 6.1 Multi-Tab Progress Display

Replace the current simple spinner on the multi-tab button with a rich progress indicator:

```
┌─────────────────────────────────────────────────┐
│ 📑 Capturing 3 tabs...                          │
│                                                   │
│ ✅ Stack Overflow - React Hooks (DOM)           │
│ 📷 Google Docs - Project Plan (screenshot 3/8)  │
│ ⏳ Word Online - Meeting Notes (waiting...)      │
│                                                   │
│ [Cancel]                                          │
└─────────────────────────────────────────────────┘
```

This could be shown:
- **Option A**: In the tab modal itself (repurpose it as a progress view)
- **Option B**: As a floating toast/banner above the chat input
- **Option C**: In the page-context-bar area

**Recommendation**: Option A — keep the tab modal open but switch its content from selection to progress view. Natural flow: select tabs → see progress → modal closes when done.

### 6.2 Cancellation

- Show a "Cancel" button during capture
- On cancel: stop the capture loop, restore original tab, keep whatever was already captured
- Set an `abortCapture` flag that the scroll loop checks between iterations

## 7. Task Breakdown

### Milestone 1: Settings & UI Foundation
1. **Add `multiTabCaptureMode` to state.settings** — `sidepanel.js` state definition, `saveSettings()`, `loadSettings()`
2. **Add capture mode dropdown to Settings panel** — `sidepanel.html`, `sidepanel.css`
3. **Wire settings change handler** — `sidepanel.js`, save/load/apply
4. **Add per-tab capture mode toggle to tab modal** — `sidepanel.html` (modify tab list item template), `sidepanel.css`
5. **Wire per-tab toggle in `showTabModal()`** — set default from global setting, handle user overrides
6. **Add doc-app URL pattern list** — new constant in `sidepanel.js` or `shared/constants.js`
7. **Auto-default scroll mode for known doc URLs** — in `showTabModal()`, check URL against patterns

### Milestone 2: Core Multi-Tab Scroll Capture
8. **Refactor `captureAndOcrPipelined()` to accept `targetTabId`** — backward-compatible parameter addition
9. **Create `captureTabWithScrollOcr(tabId, tabInfo, onProgress)`** — tab activation, render wait, call pipelined capture, error handling
10. **Modify `handleTabSelection()` to partition tabs by mode** — simple/scroll/auto buckets
11. **Implement Phase 1: parallel DOM extraction** for simple + auto tabs
12. **Implement Phase 2: auto-mode fallback detection** — check content length, `needsScreenshot`, URL pattern
13. **Implement Phase 3: sequential scroll-capture loop** — save original tab, activate each scroll tab, capture, restore
14. **Implement Phase 4: result assembly** — merge DOM and OCR results into `multiTabContexts` + `pageContext`

### Milestone 3: Progress UI & UX Polish
15. **Create progress view in tab modal** — replace selection content with progress list during capture
16. **Wire progress callbacks** — per-tab status updates (waiting/capturing/done/error), per-screenshot progress for scroll tabs
17. **Add cancellation support** — abort flag, cancel button, partial result handling
18. **Tab restoration logic** — always restore original tab, even on errors/cancellation
19. **Handle edge cases**: tab closed during capture, permission errors, sidepanel losing focus

### Milestone 4: Integration & Testing
20. **Content viewer support for multi-tab OCR** — ensure content viewer shows paginated OCR from multiple tabs correctly (already partially supported via `isMultiTab`)
21. **OCR context persistence** — multi-tab OCR context should persist with same rules as single-tab OCR (don't overwrite on `attachPageContent` etc.)
22. **Update documentation** — `extension_implementation.md`, `extension_api.md`, `EXTENSION_DESIGN.md`, `README.md`
23. **Manual testing matrix**: simple-only, scroll-only, auto-mode, mixed, cancellation, tab-closed-during-capture, known doc apps

## 8. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Sidepanel state lost on tab switch** | High | Test early (Milestone 2, task 9). Sidepanel uses `default_path` at extension level → should persist. If not, fall back to service-worker orchestration with state in `chrome.storage.session`. |
| **Tab not fully rendered after activation** | Medium | Wait for `chrome.tabs.onUpdated` with `status: 'complete'` + configurable extra delay (default 500ms). For SPAs, the content script's `waitForScrollSettled()` handles lazy rendering. |
| **User navigates away during capture** | Medium | Check `tab.url` hasn't changed before each scroll step. If changed, skip tab with error. |
| **Tab closed during capture** | Medium | Wrap `chrome.tabs.get(tabId)` in try/catch. If tab gone, skip with error, continue to next tab. |
| **Very slow for many scroll tabs** | Medium | Show clear progress + time estimate. Allow cancellation. Consider parallelizing OCR across tabs (capture tab A → fire OCR → capture tab B → fire OCR → wait all OCR). |
| **`captureVisibleTab` rate limit across tabs** | Low | Same 1s delay + 1.2s backoff already in pipeline. Switching tabs adds ~500ms natural delay. |
| **Content script not injected in target tab** | Low | `handleExtractFromTab` already handles injection. For scroll capture, `INIT_CAPTURE_CONTEXT` will fail gracefully → fall back to DOM extraction for that tab. |

## 9. Alternatives Considered

### Alternative 1: Open tabs in a hidden/offscreen window
- `chrome.windows.create({ focused: false })` + move tab there → capture → move back
- **Rejected**: `captureVisibleTab` captures the *active* tab in the *specified window* — but if the window is not focused, Chrome may not render it. Also more complex and jarring.

### Alternative 2: Use Offscreen Document API
- Chrome's Offscreen Documents can create headless-ish pages
- **Rejected**: Can't render arbitrary web pages. Only works for extension pages.

### Alternative 3: Service worker orchestrates everything
- Service worker switches tabs and captures, sidepanel just displays results.
- **Rejected as primary**: Service worker can't use pipelined OCR (single `sendResponse` limitation). Keep as fallback if sidepanel doesn't survive tab switches.

### Alternative 4: Use `chrome.debugger` API for headless capture
- Attach debugger → `Page.captureScreenshot` → works on background tabs.
- **Rejected**: Requires `debugger` permission (scary permission prompt), shows "debugging this browser" bar, complex API. Overkill for this use case.

## 10. Files Affected

| File | Type | Changes |
|------|------|---------|
| `sidepanel/sidepanel.html` | Modify | Add capture mode setting dropdown; add per-tab mode toggle in tab modal template; add progress view markup |
| `sidepanel/sidepanel.js` | Modify | New setting in state + save/load; `captureTabWithScrollOcr()`; refactor `handleTabSelection()`; refactor `captureAndOcrPipelined()` for `targetTabId`; progress UI logic; cancellation; doc-app URL patterns |
| `sidepanel/sidepanel.css` | Modify | Capture mode toggle styles; progress view styles |
| `shared/constants.js` | Modify | `DOC_APP_URL_PATTERNS` constant (or keep in sidepanel.js) |
| `background/service-worker.js` | Minor | Only if service-worker fallback needed for tab switching |
| `extension_server.py` | None | No changes |
| Docs (5 files) | Modify | Document new setting, multi-tab capture modes, tab switching behavior |

## 11. Estimated Effort

| Milestone | Effort | Dependencies |
|-----------|--------|--------------|
| 1. Settings & UI Foundation | ~2 hours | None |
| 2. Core Multi-Tab Scroll Capture | ~4 hours | Milestone 1 |
| 3. Progress UI & UX Polish | ~2 hours | Milestone 2 |
| 4. Integration & Testing | ~2 hours | Milestone 3 |
| **Total** | **~10 hours** | |

The critical path is Milestone 2 — specifically verifying that the sidepanel survives tab switches and that `captureAndOcrPipelined()` works correctly on a freshly-activated tab.
