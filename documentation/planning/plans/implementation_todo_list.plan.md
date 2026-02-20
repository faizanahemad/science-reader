---
name: Three-Extension Architecture — Exhaustive Implementation Todo List
overview: >
  Ordered, code-backed, agent-assigned todo list for implementing the three-extension
  architecture: shared infrastructure, headless bridge extension, main UI integration,
  and iframe sidepanel extension. Every task references verified code locations.
status: ready
created: 2026-02-19
depends-on:
  - extension_headless_bridge.plan.md
  - main_ui_extension_integration.plan.md
  - extension_iframe_sidepanel.plan.md
---

# Three-Extension Architecture — Implementation Todo List

## Dependency Graph

```
Phase 1: Shared Infrastructure
    ├── 1A: Create extension-shared/ directory
    ├── 1B: Split extractor.js → core + ui
    ├── 1C: Create script-runner-core.js
    ├── 1D: Move sandbox to shared
    ├── 1E: Extract full-page capture helper
    ├── 1F: Create build.sh
    └── 1G: Verify current extension still works
             │
             ├──────────────────────────────────┐
             │                                  │
    Phase 2: Headless Bridge        Phase 3: Main UI Integration
    (parallel w/ Phase 3)           (parallel w/ Phase 2)
    ├── 2A: manifest.json           ├── 3A: extension-bridge.js
    ├── 2B: bridge.js               ├── 3B: page-context-manager.js
    ├── 2C: service-worker.js       ├── 3C: tab-picker-manager.js
    ├── 2D: Wire shared modules     ├── 3D: workflow-manager.js
    ├── 2E: Icons                   ├── 3E: script-manager.js
    └── 2F: Test headless ext       ├── 3F: HTML additions
                    │               ├── 3G: CSS additions
                    │               ├── 3H: common-chat.js hook
                    │               ├── 3I: Script tags + init
                    │               └── 3J: Test main UI integration
                    │                          │
                    └──────────┬───────────────┘
                               │
                      Phase 4: Iframe Sidepanel
                      ├── 4A: manifest.json
                      ├── 4B: background.js
                      ├── 4C: sidepanel.html + css
                      ├── 4D: Icons
                      └── 4E: Test iframe extension
                               │
                      Phase 5: Integration Testing
                      └── 5A: All 3 extensions together
```

---

## Phase 1: Shared Infrastructure (~1-1.5 days)

**Goal**: Create `extension-shared/` directory with reusable modules split from existing code.
All other phases depend on this completing first.

---

### Task 1A: Create extension-shared/ directory structure
**Effort**: 15 min | **Agent**: quick | **Plan ref**: Headless plan §0

Create the top-level `extension-shared/` directory with placeholder README.

**Steps**:
1. `mkdir -p extension-shared/`
2. Create `extension-shared/README.md` explaining purpose, module list, dev symlink usage, production build usage

**Files created**:
- `extension-shared/README.md`

**Acceptance**: Directory exists, README explains the shared module strategy.

---

### Task 1B: Split extractor.js into extractor-core.js + extractor-ui.js
**Effort**: 3-4h | **Agent**: deep | **Plan ref**: Headless plan §0, Task 5
**Depends on**: 1A

The most critical shared infrastructure task. The current
`extension/content_scripts/extractor.js` (2,057 lines) must be split cleanly.

**Verified split boundary**: Line 1859 (from explore agent analysis)

**extractor-core.js** (~1,848 lines → `extension-shared/extractor-core.js`):
- Lines 11-19: IIFE wrapper + idempotency guard (`window.__aiAssistantInjected`)
- Lines 20-845: `extractPageContent()` dispatcher + 15 site-specific extractors + generic fallback + `buildResult()` + `getSelectedText()`
- Lines 847-1157: Modal system — NOTE: the `handleQuickAction()` function (lines 1164-1215) mixes core API logic with modal UI. Must split:
  - Core part: `quickActionRequest(action, text)` → API call to `/ext/chat/quick`, returns JSON → stays in core
  - UI part: `handleQuickAction(action, text)` → calls core, renders markdown in modal → goes to UI
- Lines 1221-1254: `getPageMetrics()`, `scrollToPosition()`
- Lines 1256-1857: Scroll detection (9 functions) + capture context management (12 functions) + `KNOWN_SCROLL_SELECTORS`
- Message handler for CORE types only: EXTRACT_PAGE, GET_SELECTION, GET_PAGE_METRICS, SCROLL_TO, INIT_CAPTURE_CONTEXT, SCROLL_CONTEXT_TO, GET_CONTEXT_METRICS, RELEASE_CAPTURE_CONTEXT
- Export public API on `window.__extractorCore`

**IMPORTANT CORRECTION**: The modal system (lines 847-1157) should actually stay in **extractor-ui.js** since it's purely UI. Only extraction logic, scroll system, and page metrics go to core. Revised split:

**extractor-core.js** (extraction + scroll + metrics, ~1,450 lines):
- Lines 11-19: IIFE + guard
- Lines 20-845: Extraction functions (dispatcher + 15 site-specific + generic + helpers)
- Lines 1164-1215: `quickActionRequest()` — ONLY the API call part
- Lines 1221-1254: Page metrics
- Lines 1256-1857: Scroll detection + capture context
- Message handler for core message types
- Exports on `window.__extractorCore`

**extractor-ui.js** (modal + toast + floating button, ~400 lines → NOT shared, stays in extension/):
- Lines 847-1157: Modal system (6 functions)
- Lines 1164-1215: `handleQuickAction()` — UI rendering part, calls `window.__extractorCore.quickActionRequest()`
- Lines 1937-1993: `showToast()`
- Lines 1995-2053: `createFloatingButton()`
- Own message handler for: QUICK_ACTION, SHOW_MODAL, HIDE_MODAL

**Steps**:
1. Read extractor.js completely
2. Create `extension-shared/extractor-core.js` — write IIFE wrapper first, then extraction functions, then scroll system, then message handler, then exports (write in chunks)
3. Create `extension/content_scripts/extractor-ui.js` — modal system, quick action UI handler, toast, floating button, UI message handler
4. Refactor `handleQuickAction()`: core API logic → core module export; UI rendering → UI module
5. Create symlink: `extension/content_scripts/extractor-core.js` → `../../extension-shared/extractor-core.js`
6. Update `extension/manifest.json` content_scripts:
   ```json
   {
     "matches": ["<all_urls>"],
     "js": ["content_scripts/extractor-core.js", "content_scripts/extractor-ui.js"],
     "run_at": "document_idle"
   }
   ```
   (Load order matters — core MUST load first)
7. Delete original `extension/content_scripts/extractor.js`

**Acceptance**:
- No console errors on any page
- Site-specific extractors work (test Google Docs, Reddit, GitHub)
- Scroll detection works (test on pages with inner scroll containers)
- Floating button appears
- Quick actions work (right-click → Explain/Summarize)
- Toast notifications display
- Modal opens/closes correctly
- Full-page capture works (test on long Wikipedia article)

---

### Task 1C: Create script-runner-core.js (on-demand mode)
**Effort**: 2h | **Agent**: deep | **Plan ref**: Headless plan §0, Task 7
**Depends on**: 1A

Create a shared variant of `extension/content_scripts/script_runner.js` (1,449 lines)
that supports on-demand initialization instead of auto-init.

**Current auto-init** (verified by explore agent):
- IIFE wrapper at line 13, `window.__scriptRunnerInitialized` guard
- `initialize()` called unconditionally at line 1435
- `initialize()` calls `loadScriptsForCurrentUrl()` + sets up MutationObserver for SPA nav

**Chrome API dependencies** (11 calls, all extension-specific):
- `chrome.runtime.sendMessage()` (lines 554, 1074) — LLM requests, script loading
- `chrome.runtime.lastError` (lines 558, 1078)
- `chrome.storage.local.get/set()` (lines 595, 610) — per-script storage
- `chrome.runtime.getURL()` (lines 827, 839) — sandbox iframe URL
- `chrome.runtime.onMessage.addListener()` (line 1338) — control messages

**Message types handled** (line 1338):
- EXECUTE_SCRIPT_ACTION, GET_LOADED_SCRIPTS, TEST_SCRIPT, RELOAD_SCRIPTS, GET_PAGE_CONTEXT

**Changes for on-demand mode**:
1. At line 1435, add mode check before `initialize()`:
   ```javascript
   if (window.__scriptRunnerMode !== 'ondemand') {
       initialize();
   }
   ```
2. Add `initialize` to public API at line 1438:
   ```javascript
   window.__scriptRunner = {
       initialize,              // NEW: explicit init for on-demand mode
       loadedScripts,
       callHandler,
       loadScriptsForCurrentUrl,
       showToast,
       showModal,
       closeModal
   };
   ```

**Steps**:
1. Copy `extension/content_scripts/script_runner.js` to `extension-shared/script-runner-core.js`
2. Add mode check at line 1435
3. Add `initialize` to public API
4. Create symlink: `extension/content_scripts/script-runner-core.js` → `../../extension-shared/script-runner-core.js`
5. Update `extension/manifest.json`: `"script_runner.js"` → `"script-runner-core.js"`
6. Verify script_ui.js still works (depends on `window.__scriptRunner` API)

**Acceptance**:
- Default mode: scripts auto-load as before (backwards compatible)
- On-demand mode: `window.__scriptRunnerMode = 'ondemand'` prevents auto-init
- `window.__scriptRunner.initialize()` callable manually
- Floating toolbar + command palette still work

---

### Task 1D: Move sandbox files to extension-shared/
**Effort**: 30 min | **Agent**: quick | **Plan ref**: Headless plan §0, Task 6
**Depends on**: 1A

**Files**:
- `extension/sandbox/sandbox.html` (19 lines) → `extension-shared/sandbox.html`
- `extension/sandbox/sandbox.js` (227 lines) → `extension-shared/sandbox.js`

**Why safe**: sandbox.js has ZERO chrome.* API calls. Pure web APIs (postMessage, Function constructor, structuredClone).

**Steps**:
1. Copy both files to `extension-shared/`
2. Replace originals with symlinks
3. Verify manifest sandbox path still works with symlinks
4. Test custom script execution in current extension

**Acceptance**: Custom scripts execute via sandbox without errors. RPC bridge works.

---

### Task 1E: Extract full-page capture helper
**Effort**: 1.5h | **Agent**: unspecified-low | **Plan ref**: Headless plan §0
**Depends on**: 1A

Extract the capture orchestration algorithm from `extension/background/service-worker.js`.

**Source**: service-worker.js lines 461-642
**Chrome APIs used**: `chrome.tabs.captureVisibleTab()`, `chrome.tabs.sendMessage()` (sends INIT_CAPTURE_CONTEXT, SCROLL_CONTEXT_TO, GET_CONTEXT_METRICS, RELEASE_CAPTURE_CONTEXT to content script)

**Steps**:
1. Create `extension-shared/full-page-capture.js` as ES module:
   ```javascript
   /**
    * Full-page capture orchestration.
    * Scrolls page capturing screenshots at each position.
    * @param {number} tabId
    * @param {object} chromeApi - { captureVisibleTab, sendMessage }
    * @param {function} onProgress - callback(step, total)
    * @returns {Promise<{screenshots: string[], pageTitle: string, pageUrl: string}>}
    */
   export async function captureFullPage(tabId, chromeApi, onProgress) { ... }
   ```
2. Extract algorithm from service-worker.js, parameterize chrome.* calls via `chromeApi` adapter
3. Refactor current service-worker.js to import and use the shared module:
   ```javascript
   import { captureFullPage } from '../extension-shared/full-page-capture.js';
   // or via symlink: import { captureFullPage } from './full-page-capture.js';
   ```
4. Verify full-page capture still works

**Acceptance**: Full-page capture works on long pages. Progress events fire. Screenshots returned as base64 PNG array.

---

### Task 1F: Create build.sh
**Effort**: 1h | **Agent**: quick | **Plan ref**: Headless plan §0
**Depends on**: 1A-1E

Production build script that replaces symlinks with actual file copies for Chrome Web Store packaging.

**Steps**:
1. Create `build.sh` at repo root
2. Logic: for each extension dir, find symlinks → extension-shared/, replace with copies
3. `chmod +x build.sh`
4. Test: run, verify symlinks become real files, verify extensions still load

**Acceptance**: `build.sh` runs cleanly. Each extension is self-contained after build.

---

### Task 1G: Verify current extension after all Phase 1 changes
**Effort**: 1h | **Agent**: manual testing | **Plan ref**: All Phase 1
**Depends on**: 1B, 1C, 1D, 1E, 1F

Full regression test of current extension.

**Test checklist**:
1. Extension loads without errors in `chrome://extensions/`
2. Sidepanel opens, chat works with streaming
3. Page extraction: Google Docs, Reddit, generic page
4. Full-page capture on long page
5. Quick actions (right-click → Explain/Summarize)
6. Floating button appears
7. Toast notifications display
8. Custom scripts load on matching pages
9. Script editor opens
10. Command palette (Ctrl+Shift+K) works
11. Sandbox script execution works
12. Multi-tab capture works

**Acceptance**: All 12 tests pass. Zero console errors. Zero behavior changes.

---

## Phase 2: Headless Bridge Extension (~2-2.5 days)

**Goal**: Create `extension-headless/` — a zero-UI extension providing Chrome API capabilities via postMessage bridge.
**Parallel with Phase 3** after Phase 1 completes.

---

### Task 2A: Create extension-headless/ directory and manifest.json
**Effort**: 30 min | **Agent**: quick | **Plan ref**: Headless plan §2, Task 1

**Steps**:
1. Create directory structure:
   ```
   extension-headless/
   ├── background/
   ├── content_scripts/
   ├── sandbox/
   └── assets/icons/
   ```
2. Create manifest.json:
   - `permissions`: `activeTab`, `scripting`, `tabs`
   - `content_scripts`: ONLY `bridge.js` on `http://localhost:5000/*` and `https://assist-chat.site/*`
   - `background.service_worker`: `"background/service-worker.js"` with `"type": "module"`
   - `sandbox.pages`: `["sandbox/sandbox.html"]`
   - `web_accessible_resources`: extractor-core.js, script-runner-core.js, sandbox files
   - NO `sidePanel`, `contextMenus`, `storage` permissions
   - NO auto-injected content scripts on `<all_urls>`

**Acceptance**: Extension loads in Chrome without errors.

---

### Task 2B: Create bridge.js content script
**Effort**: 3-4h | **Agent**: deep | **Plan ref**: Headless plan §3, Task 2

**File**: `extension-headless/content_scripts/bridge.js` (~130 lines)

Core communication layer between main UI page and service worker.

**Message protocol** (Headless plan §1.3):
```javascript
{
    channel: "ai-assistant-bridge",
    version: 1,
    direction: "page-to-ext" | "ext-to-page",
    requestId: "uuid",
    clientId: "uuid",
    type: "EXTRACT_PAGE" | "LIST_TABS" | etc.,
    payload: { ... }
}
```

**Implementation requirements**:
1. Generate unique `bridgeInstanceId`
2. Port connection: `chrome.runtime.connect({ name: 'bridge-' + bridgeInstanceId })`
3. Window message listener with validation:
   - `event.source === window`
   - `event.origin` in allowed origins
   - `event.data.channel === "ai-assistant-bridge"`
   - `event.data.direction === "page-to-ext"`
   - Required fields: `requestId`, `type`
   - Frame: `top === self` OR top is `chrome-extension://`
4. Forward to SW via Port, receive responses, post back to page
5. Port reconnect with exponential backoff (100ms→5s max)
6. Dispatch `CustomEvent("ai-assistant-bridge-ready")` on connect
7. Dispatch `CustomEvent("ai-assistant-bridge-disconnected")` on disconnect

**Acceptance**:
- `ai-assistant-bridge-ready` fires on main UI page load
- PING returns `{ alive: true, version: 1 }`
- Port reconnects after SW sleep (5+ min idle)
- Invalid messages silently dropped

---

### Task 2C: Create headless service-worker.js
**Effort**: 6-8h | **Agent**: deep | **Plan ref**: Headless plan §3, Task 3

**File**: `extension-headless/background/service-worker.js` (~500-600 lines)

The largest file. Write in small chunks.

**Structure** (write in this order):
1. ES module imports
2. Port tracking: `Map<bridgeId, port>`
3. `chrome.runtime.onConnect` handler
4. Message dispatcher: switch on `type`
5. Handlers:

| Handler | Chrome APIs | Source ref (current SW) |
|---------|------------|----------------------|
| `handlePing()` | None | New |
| `handleListTabs()` | `chrome.tabs.query()` | Lines 137-157 |
| `handleGetTabInfo()` | `chrome.tabs.query()` | Lines 137-157 |
| `handleExtractCurrentPage()` | `chrome.tabs.query()`, `chrome.scripting.executeScript()` | Lines 269-418 |
| `handleExtractTab(tabId)` | `chrome.scripting.executeScript()`, `chrome.tabs.sendMessage()` | Lines 269-418 |
| `handleCaptureScreenshot(tabId)` | `chrome.tabs.update()`, `chrome.tabs.captureVisibleTab()` | Lines 423-431 |
| `handleCaptureFullPage(tabId)` | Import from shared | Lines 461-642 |
| `handleCaptureMultiTab(tabs)` | Combination | New |
| `handleExecuteScript(tabId, code)` | `chrome.scripting.executeScript()` | Lines 656-868 |

6. `ensureExtractorInjected(tabId)` — on-demand injection helper
7. Single-flight capture lock
8. Progress events via Port
9. Error handling for restricted pages

**Steps** (small chunks):
1. File skeleton: imports, port map, onConnect
2. Message dispatcher switch
3. handlePing, handleListTabs, handleGetTabInfo
4. ensureExtractorInjected helper
5. handleExtractCurrentPage, handleExtractTab
6. handleCaptureScreenshot
7. handleCaptureFullPage (import shared module)
8. handleCaptureMultiTab with progress
9. handleExecuteScript (with on-demand script-runner injection)
10. Single-flight lock + error handling

**Acceptance**:
- All 9 operation types return correct results
- Progress events fire during multi-tab capture
- Single-flight lock prevents concurrent captures
- Restricted pages (chrome://) return clean error
- Port disconnect mid-operation doesn't crash

---

### Task 2D: Wire shared modules into headless extension
**Effort**: 30 min | **Agent**: quick | **Plan ref**: Headless plan Tasks 4, 6, 7
**Depends on**: 1B, 1C, 1D, 2A

Create symlinks from extension-headless/ to extension-shared/:

```bash
ln -s ../../extension-shared/extractor-core.js extension-headless/content_scripts/extractor-core.js
ln -s ../../extension-shared/script-runner-core.js extension-headless/content_scripts/script-runner-core.js
ln -s ../../extension-shared/sandbox.html extension-headless/sandbox/sandbox.html
ln -s ../../extension-shared/sandbox.js extension-headless/sandbox/sandbox.js
ln -s ../../extension-shared/full-page-capture.js extension-headless/background/full-page-capture.js
```

**Acceptance**: Symlinks resolve. `ls -la` shows correct targets.

---

### Task 2E: Create headless extension icons
**Effort**: 30 min | **Agent**: quick | **Plan ref**: Headless plan Task 8

Different color from current extension (e.g., green vs blue). Can reuse `extension/generate_icons.py`.

**Files**: `extension-headless/assets/icons/icon{16,32,48,128}.png`

**Acceptance**: Visually distinct in `chrome://extensions/`.

---

### Task 2F: Test headless bridge extension
**Effort**: 2-3h | **Agent**: manual testing | **Plan ref**: Headless plan §4
**Depends on**: 2A-2E

| # | Test | Expected |
|---|------|----------|
| 1 | Bridge injection | `ai-assistant-bridge-ready` fires on localhost:5000 |
| 2 | PING | Returns `{ alive: true, version: 1 }` |
| 3 | LIST_TABS | Array of open tabs |
| 4 | EXTRACT_CURRENT_PAGE | Extracted content from non-main-UI tab |
| 5 | EXTRACT_TAB by ID | Specific tab's content |
| 6 | Google Docs extraction | Content extracted correctly |
| 7 | CAPTURE_SCREENSHOT | base64 PNG |
| 8 | Full-page capture | Screenshot array + progress events |
| 9 | Coexistence | Both extensions installed, no conflicts |
| 10 | SW sleep recovery | Bridge reconnects after 5+ min |
| 11 | Multiple UI tabs | Each gets correct response (clientId routing) |
| 12 | Restricted page | Clean error message |

**Acceptance**: All 12 tests pass.

---

## Phase 3: Main UI Extension Integration (~3-4 days)

**Goal**: Add extension-powered controls to `interface/` leveraging the headless bridge.
**Parallel with Phase 2** after Phase 1 completes.

---

### Task 3A: Create extension-bridge.js
**Effort**: 3-4h | **Agent**: deep | **Plan ref**: Main UI plan §4, Task 1

**File**: `interface/extension-bridge.js` (~200 lines)

Promise-based client library. Pattern: IIFE (matches existing modules like PKBManager, WorkspaceManager).

```javascript
var ExtensionBridge = (function() {
    var _available = false;
    var _clientId = 'client-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
    var _pendingRequests = {};  // requestId -> { resolve, reject, timeout }
    var _availabilityCallbacks = [];

    function _sendMessage(type, payload, timeoutMs) { /* ... */ }

    return {
        isAvailable: false,
        init: function() { /* listen for bridge-ready CustomEvent + window messages */ },
        onAvailabilityChange: function(cb) { /* ... */ },
        ping: function() { return _sendMessage('PING', {}); },
        extractCurrentPage: function() { return _sendMessage('EXTRACT_CURRENT_PAGE', {}, 30000); },
        extractTab: function(tabId) { return _sendMessage('EXTRACT_TAB', { tabId: tabId }, 30000); },
        listTabs: function() { return _sendMessage('LIST_TABS', {}); },
        captureScreenshot: function(tabId) { return _sendMessage('CAPTURE_SCREENSHOT', { tabId: tabId }, 30000); },
        captureFullPage: function(tabId) { return _sendMessage('CAPTURE_FULL_PAGE', { tabId: tabId }, 120000); },
        captureMultiTab: function(tabConfigs) { return _sendMessage('CAPTURE_MULTI_TAB', { tabs: tabConfigs }, 300000); },
        executeScript: function(tabId, code) { return _sendMessage('EXECUTE_SCRIPT', { tabId: tabId, code: code }, 30000); },
        getTabInfo: function() { return _sendMessage('GET_TAB_INFO', {}); },
        onProgress: function(cb) { /* ... */ }
    };
})();
```

**Key details**:
- Uses `var` (interface/ code style)
- `_sendMessage()` posts window.postMessage with `direction: "page-to-ext"`, returns Promise
- Listens for messages with `direction: "ext-to-page"` and matching `requestId`
- Detection: `CustomEvent("ai-assistant-bridge-ready")` + 2s fallback timeout
- Default timeout 30s, multi-tab 300s

**Acceptance**:
- When headless ext installed: `isAvailable` → `true`, callbacks fire
- When not installed: `isAvailable` stays `false` after 2s, no errors
- All methods return Promises that resolve/reject correctly

---

### Task 3B: Create page-context-manager.js
**Effort**: 3-4h | **Agent**: deep | **Plan ref**: Main UI plan §4, Task 2

**File**: `interface/page-context-manager.js` (~250 lines)

**Critical method — `getPageContextForPayload()`** must return EXACTLY the backend format (verified from `extension/shared/api.js` lines 493-525 and `Conversation.py:build_page_context_text()` line 9726):

```javascript
{
    url: string,
    title: string,
    content: string,
    screenshot: null,
    isScreenshot: false,
    isMultiTab: false,
    tabCount: 1,
    isOcr: false,
    sources: [],            // [{url, title, content, timestamp}] for multi-tab
    mergeType: "single",    // "single" or "multi"
    lastRefreshed: Date.now()
}
```

**Content limits** (from backend): single 64,000 chars, multi-tab 128,000 chars.

**Multi-tab format**: `## Tab: {title}\nURL: {url}\n\n{content}\n\n---`

**UI elements**: Collapsible panel above chat input — title bar, content preview, refresh/toggle/clear buttons.

**Acceptance**:
- Extract populates panel with title + URL + content preview
- `getPageContextForPayload()` returns correct format
- Clear removes context and hides panel
- Refresh re-extracts same tabs
- Multi-tab shows tab count badge

---

### Task 3C: Create tab-picker-manager.js
**Effort**: 4-5h | **Agent**: deep | **Plan ref**: Main UI plan §4, Task 3

**File**: `interface/tab-picker-manager.js` (~300 lines)

Bootstrap 4.6 modal for multi-tab capture.

**Features**:
- Fetch tabs via `ExtensionBridge.listTabs()`
- Tab rows: checkbox, favicon, title, URL, mode dropdown (Auto/DOM/OCR/Full OCR)
- Select All / Deselect All
- Progress bar during capture
- Cancel button
- Results → `PageContextManager.setMultiTabContext()`

**OCR flow** (mode = OCR or Full OCR):
1. `ExtensionBridge.captureScreenshot(tabId)` or `.captureFullPage(tabId)`
2. POST screenshot to `/ext/ocr` endpoint
3. Receive OCR text

**Acceptance**: Modal opens with tab list. Multi-tab capture with progress. Cancel works. Results flow to page context panel.

---

### Task 3D: Create workflow-manager.js
**Effort**: 3-4h | **Agent**: unspecified-high | **Plan ref**: Main UI plan §4, Task 4

**File**: `interface/workflow-manager.js` (~250 lines)

**Backend endpoints** (verified):
- `GET /ext/workflows/list` (`endpoints/ext_workflows.py` line 71)
- `POST /ext/workflows/create` (line 85)
- `PUT /ext/workflows/{id}`
- `DELETE /ext/workflows/{id}`

**UI**: Collapsible card in settings modal. Workflow list + editor + selector dropdown.

**Acceptance**: CRUD persists via API. Selected workflow_id available to chat send flow.

---

### Task 3E: Create script-manager.js
**Effort**: 4-5h | **Agent**: unspecified-high | **Plan ref**: Main UI plan §4, Task 5

**File**: `interface/script-manager.js` (~300 lines)

**Backend endpoints** (verified):
- `GET /ext/scripts/list` (`endpoints/ext_scripts.py` line 130)
- `POST /ext/scripts/create` (line 155)
- `GET/PUT/DELETE /ext/scripts/{id}`
- `POST /ext/scripts/generate`
- `POST /ext/scripts/validate`

**UI**: Collapsible card in settings modal. "Test on Page" grayed out when extension unavailable.

**Acceptance**: CRUD + LLM generation work. "Test on Page" calls bridge when available.

---

### Task 3F: Add HTML additions to interface.html
**Effort**: 2-3h | **Agent**: unspecified-high | **Plan ref**: Main UI plan §4, Tasks 6-9
**Depends on**: 3A-3E

**Additions to `interface/interface.html`**:
1. Extension controls button group (near chat input, ~line 291):
   - "Page" button (`#ext-extract-page`)
   - "Multi-tab" button (`#ext-multi-tab`)
   - Wrapped in `#extension-controls` div, `display: none` by default
2. Page context panel (`#page-context-panel`) above chat controls
3. Tab picker modal (`#tab-picker-modal`) — Bootstrap 4.6 modal with tab list
4. Workflow section in settings modal — collapsible card `#settings-workflows-section`
5. Script section in settings modal — collapsible card `#settings-scripts-section`

All HTML templates specified in Main UI plan §4, Tasks 6-9.

**Acceptance**: Elements have correct IDs. Modals open/close. Bootstrap patterns followed.

---

### Task 3G: Add CSS for new components
**Effort**: 1h | **Agent**: quick | **Plan ref**: Main UI plan §4, Task 10

**File**: `interface/style.css` (append ~50-80 lines)

Styles for: `#extension-controls`, `.page-context-header`, `#page-context-body`, `.tab-picker-item`, workflow/script list items.

CSS specified in Main UI plan §4, Task 10.

**Acceptance**: Components render correctly. No style conflicts.

---

### Task 3H: Hook page_context into common-chat.js send flow
**Effort**: 30 min | **Agent**: quick | **Plan ref**: Main UI plan §4, Task 11
**Depends on**: 3B

**File**: `interface/common-chat.js`
**Location**: After line 2911 (after `referenced_friendly_ids` block), before `clearAttachmentPreviews()` at line 2913.

**Add ~10 lines**:
```javascript
// Include page context from extension bridge if available
if (typeof PageContextManager !== 'undefined' && PageContextManager.hasContext()) {
    requestBody['page_context'] = PageContextManager.getPageContextForPayload();
}

// Include workflow_id if selected
if (typeof WorkflowManager !== 'undefined') {
    var workflowId = WorkflowManager.getSelectedWorkflowId();
    if (workflowId) {
        requestBody['workflow_id'] = workflowId;
    }
}
```

**Acceptance**:
- Without extension: requestBody unchanged
- With context: `page_context` in POST body, backend processes it
- Zero regressions in existing chat

---

### Task 3I: Add script tags and initialization
**Effort**: 30 min | **Agent**: quick | **Plan ref**: Main UI plan §4, Task 12
**Depends on**: 3A-3F

**File**: `interface/interface.html`
**Location**: After line 2946 (after `audio_process.js`)

```html
<!-- Extension Bridge Integration -->
<script src="interface/extension-bridge.js"></script>
<script src="interface/page-context-manager.js"></script>
<script src="interface/tab-picker-manager.js"></script>
<script src="interface/workflow-manager.js"></script>
<script src="interface/script-manager.js"></script>
```

**Init** (add to existing `$(document).ready()` or end of chat.js):
```javascript
ExtensionBridge.init();
ExtensionBridge.onAvailabilityChange(function(available) {
    if (available) {
        $('#extension-controls').show();
        WorkflowManager.init();
        ScriptManager.init();
    } else {
        $('#extension-controls').hide();
    }
});
```

**Acceptance**: Scripts load without errors. Controls appear/hide based on extension availability.

---

### Task 3J: Test main UI extension integration
**Effort**: 2-3h | **Agent**: manual testing | **Plan ref**: Main UI plan §6
**Depends on**: 3A-3I, Phase 2 complete

| # | Test | Expected |
|---|------|----------|
| 1 | No extension | Controls hidden, all features work |
| 2 | Extension installed | Controls appear, PING succeeds |
| 3 | Extract current page | Page context panel shows content |
| 4 | Extract Google Docs | Content extracted correctly |
| 5 | Clear context | Panel disappears |
| 6 | Send with context | Backend receives page_context, LLM responds about page |
| 7 | Multi-tab DOM | Both pages in panel |
| 8 | Multi-tab OCR | Screenshots + OCR text |
| 9 | Cancel capture | Partial results |
| 10 | Workflow CRUD | Create, edit, delete |
| 11 | Workflow selection | Backend applies steps |
| 12 | Script CRUD | Create, edit, delete |
| 13 | Script test | Executes via bridge |
| 14 | Works in iframe | All controls work in sidepanel |

**Acceptance**: All 14 tests pass. Zero regressions.

---

## Phase 4: Iframe Sidepanel Extension (~0.5 day)

**Goal**: Create `extension-iframe/` — thinnest extension, iframe to main UI in sidepanel.
**Depends on**: Phases 2 and 3 complete.

---

### Task 4A: Create extension-iframe/ directory and manifest.json
**Effort**: 15 min | **Agent**: quick | **Plan ref**: Iframe plan §2, Task 1

```
extension-iframe/
├── sidepanel/
└── assets/icons/
```

Manifest: `sidePanel` + `storage` permissions only. CSP: `frame-src http://localhost:5000 https://assist-chat.site`. NO content_scripts, host_permissions, tabs, scripting.

**Acceptance**: Extension loads in Chrome.

---

### Task 4B: Create background.js
**Effort**: 5 min | **Agent**: quick | **Plan ref**: Iframe plan §2, Task 2

**File**: `extension-iframe/background.js` (3 lines):
```javascript
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
```

**Acceptance**: Icon click opens sidepanel.

---

### Task 4C: Create sidepanel.html + sidepanel.css
**Effort**: 1-2h | **Agent**: quick | **Plan ref**: Iframe plan §2, Tasks 3-4

- iframe src = `http://localhost:5000/interface/interface.html`
- Loading spinner, error state, retry + server switch
- URL preference in `chrome.storage.local`
- `allow="microphone; clipboard-write"` on iframe
- `sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals allow-downloads"`

**Critical**: Flask does NOT send X-Frame-Options (verified — no changes needed).

Content specified in Iframe plan §2, Tasks 3-4.

**Acceptance**: Sidepanel loads main UI. Loading/error states work. Server switch works.

---

### Task 4D: Create iframe extension icons
**Effort**: 30 min | **Agent**: quick | **Plan ref**: Iframe plan §2, Task 5

Distinct color (e.g., purple). Files: `extension-iframe/assets/icons/icon{16,32,48,128}.png`

---

### Task 4E: Test iframe sidepanel extension
**Effort**: 1-2h | **Agent**: manual testing | **Plan ref**: Iframe plan §4
**Depends on**: 4A-4D, Phase 2, Phase 3

| # | Test | Expected |
|---|------|----------|
| 1 | Basic load | Main UI loads in iframe |
| 2 | Login | Session works |
| 3 | Chat | Streaming works |
| 4 | Workspaces | Navigation works |
| 5 | Page extraction (with headless) | Extracts from active tab |
| 6 | Multi-tab capture | Works through iframe |
| 7 | Server switch | localhost ↔ production |
| 8 | Retry | iframe loads after retry |
| 9 | Without headless | UI works, controls hidden |
| 10 | File upload | Works (sandbox allows) |

**Acceptance**: All 10 tests pass.

---

## Phase 5: Integration Testing (~1 day)

---

### Task 5A: Full integration test — all 3 extensions together
**Effort**: 4-6h | **Agent**: manual testing | **Plan ref**: All plans

**Scenario 1 — All 3 installed**: Main UI tab + iframe sidepanel + current extension all work. No message cross-talk.

**Scenario 2 — Headless + iframe only**: Iframe sidepanel works with full extraction. No errors.

**Scenario 3 — Headless + main UI tab only**: Extension controls work in regular tab.

**Scenario 4 — Current extension only**: Zero regressions from Phase 1 changes.

**Acceptance**: All 4 scenarios pass. No console errors. No conflicts.

---

## Summary

| Phase | Tasks | Effort | Parallel? |
|-------|-------|--------|-----------|
| 1: Shared Infrastructure | 1A-1G (7 tasks) | 1-1.5 days | Sequential (foundational) |
| 2: Headless Bridge | 2A-2F (6 tasks) | 2-2.5 days | After Phase 1, parallel w/ Phase 3 |
| 3: Main UI Integration | 3A-3J (10 tasks) | 3-4 days | After Phase 1, parallel w/ Phase 2 |
| 4: Iframe Sidepanel | 4A-4E (5 tasks) | 0.5 day | After Phases 2+3 |
| 5: Integration Testing | 5A (1 task) | 1 day | After Phase 4 |
| **Total** | **29 tasks** | **~8-10 days** | |

### Critical Path
Phase 1 → Phase 2 + Phase 3 (parallel) → Phase 4 → Phase 5

### Quick Wins (junior agent tasks)
- 1A, 1D, 1F: Directory creation, file moves, build script
- 2A, 2D, 2E: Manifest, symlinks, icons
- 3G, 3H, 3I: CSS, chat hook (10 lines), script tags
- 4A, 4B, 4D: Manifest, 3-line background.js, icons

### Complex Tasks (deep/senior agents)
- 1B: Split extractor.js (2,057 lines → 2 files)
- 2B, 2C: Bridge + service worker (core headless architecture)
- 3A, 3B, 3C: Bridge client + page context + tab picker (new UI modules)
