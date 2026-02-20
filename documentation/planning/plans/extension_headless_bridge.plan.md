---
name: Headless Bridge Extension (Standalone)
overview: >
  A NEW standalone Chrome extension (extension-headless/) that provides Chrome-permission-gated
  capabilities (page extraction, multi-tab capture, screenshot OCR, custom script injection)
  to any web page via a content script bridge. This extension has ZERO UI — no sidepanel,
  no popup, no context menus. It injects a bridge content script into designated pages
  (the main web UI at localhost:5000 and production domain) and responds to requests via
  postMessage. Content scripts for page extraction and script execution are injected
  ON-DEMAND via chrome.scripting.executeScript (not auto-injected) to avoid conflicts
  with the existing full-UI extension. The extension makes zero backend API calls.
status: draft
created: 2026-02-18
revised: 2026-02-19
oracle-validated: true
depends-on: none
depended-on-by:
  - main_ui_extension_integration.plan.md
  - extension_iframe_sidepanel.plan.md
---

# Headless Bridge Extension — Standalone Plan

## Purpose & Intent

### Why This Exists

We have three ways users interact with our AI assistant:

1. **Main web UI** (`interface/interface.html`) — Full-featured: workspaces, PKB, artefacts, 
   global docs, prompts, doubts, clarifications, code editor, math rendering, etc.
2. **Current Chrome extension** (`extension/`) — Dedicated sidepanel with its own chat UI,
   page extraction, multi-tab capture, custom scripts. But it will never reach feature
   parity with the main UI.
3. **Iframe sidepanel extension** (planned) — Shows the main UI inside the extension
   sidepanel as an iframe, giving users the full main UI while browsing.

All three need access to Chrome-only capabilities: reading page content from other tabs,
capturing screenshots, executing custom scripts on pages. These capabilities require
Chrome extension permissions that a regular web page cannot have.

**This headless bridge extension is the shared foundation.** It is a pure service layer —
no UI, no opinions about how users interact. It simply answers questions like "what tabs
are open?", "extract the content of tab 42", "take a screenshot of tab 7". Any page that
has the bridge content script can ask these questions.

### Multi-Extension Architecture

```
User's Browser
==============

  Current Extension        Iframe Extension         Main UI (tab)
  (extension/)             (extension-iframe/)       (localhost:5000)
  +-----------------+      +-------------------+     +------------------+
  | Own sidepanel   |      | iframe -> main UI |     | Full web app     |
  | Own page extract|      | at localhost:5000 |     |                  |
  | Own scripts     |      |                   |     |                  |
  | Self-contained  |      | Depends on v      |     | Depends on v     |
  +-----------------+      +--------+----------+     +--------+---------+
                                    |                          |
                       +------------+--------------------------+
                       v
  +--------------------------------------------+
  | Headless Bridge Extension                  |
  | (extension-headless/)                      |
  |                                            |
  | * Zero UI                                  |
  | * bridge.js on main UI pages               |
  | * On-demand extractor/script injection     |
  | * Service worker handles Chrome APIs       |
  | * Responds via postMessage                 |
  +--------------------------------------------+
```

### What This Extension Does

- Injects `bridge.js` content script into main UI pages (localhost:5000/*, production domain)
- Listens for postMessage requests from those pages
- Executes Chrome API operations (tab queries, page extraction, screenshots, script injection)
- Returns results via postMessage
- Makes ZERO backend API calls (no auth needed, no cookies)

### What This Extension Does NOT Do

- No sidepanel, no popup, no context menus, no visible UI
- No backend API calls (the calling page handles all server communication)
- No auto-injected content scripts on arbitrary pages (avoids conflicts with current extension)
- No workflow/script management (that's the main UI's job)
- No chat, no conversations, no settings storage

### Relationship to Other Plans

| Plan | Relationship |
|------|-------------|
| `main_ui_extension_integration.plan.md` | Main UI adds controls that send requests TO this extension's bridge |
| `extension_iframe_sidepanel.plan.md` | Iframe extension loads main UI in iframe; main UI talks to this bridge |
| Current extension (`extension/`) | Completely independent. Both can be installed simultaneously without conflict |

### Why Separate Extension (Not Modifying Current)

1. **No conflict**: Current extension auto-injects extractor.js and script_runner.js on all pages. This extension injects on-demand only. No duplicate content scripts.
2. **Independent install**: Users can install just the headless bridge + use main UI in a tab. Or add the iframe extension. Or keep using the current extension. Mix and match.
3. **Independent development**: Current extension UI can keep improving without affecting the bridge.
4. **Clean separation of concerns**: The bridge is a pure service layer. No UI baggage.

## 0. Code Sharing Strategy and Corrections (Added 2026-02-19)

### MV3 Remote Code Restriction

Chrome Manifest V3 strictly prohibits loading remote JavaScript for execution. The default CSP is `script-src 'self'` and cannot be relaxed for extension pages. This means serving shared JS from the Flask server (CDN-like approach) **will not work** for content scripts or service workers.

### Approach: Modular Split + Shared Source Directory

Instead of copying files, we split the existing `extractor.js` (2,057 lines — not ~600 as initially estimated) into reusable modules kept in a new `extension-shared/` directory at the repo root:

```
extension-shared/                    # Canonical shared source files
├── extractor-core.js               # Extraction + scroll/capture (~1,600 lines, NO UI)
├── sandbox.html                    # Sandbox page for script execution
├── sandbox.js                      # Sandbox runtime (227 lines)
└── script-runner-core.js           # Script execution (modified for on-demand mode)
```

Each extension symlinks (development) or copies (production build) from `extension-shared/`:
- Current extension (`extension/`): Loads `extractor-core.js` + `extractor-ui.js` (UI-only additions)
- Headless extension (`extension-headless/`): Injects only `extractor-core.js` on-demand
- Iframe extension (`extension-iframe/`): No content scripts (headless bridge handles everything)

A `build.sh` script at repo root handles packaging for Chrome Web Store.

### extractor.js Split Detail

The existing `extension/content_scripts/extractor.js` (2,057 lines) is an IIFE with these sections:

| Lines | Section | Goes to |
|-------|---------|---------|
| 1-17 | Idempotency guard | extractor-core.js |
| 20-103 | `extractPageContent()` dispatcher | extractor-core.js |
| 105-1000+ | 16 site-specific extractors | extractor-core.js |
| 1000-1412 | Generic extraction, buildResult, page metrics, KNOWN_SCROLL_SELECTORS | extractor-core.js |
| 1413-1857 | Scroll target detection (5-stage pipeline), capture context management | extractor-core.js |
| 1859-1935 | chrome.runtime.onMessage handler (extraction + scroll messages only) | extractor-core.js |
| 1937-2057 | Toast, floating button, modal (UI elements) | extractor-ui.js (current ext only) |

### Key Correction: Scroll/Capture Is In extractor.js

The scroll detection and capture context system (captureContexts map, findScrollTarget 5-stage pipeline, initCaptureContext, scrollContextTo, getContextMetrics, releaseCaptureContext) is embedded in extractor.js lines 1413-1857 — NOT in a separate file, and NOT in service-worker.js.

The service-worker.js contains the **capture orchestration** algorithm (~180 lines) that calls these extractor.js functions via `chrome.tabs.sendMessage` and then calls `chrome.tabs.captureVisibleTab`. This orchestration logic is what the headless SW needs.

### Service Worker Is Larger Than Estimated

The current `extension/background/service-worker.js` is **910 lines** (not ~300). It contains:
- Context menu setup (lines 32-70)
- Message handler switch (lines 137-210)
- Sidepanel opener (lines 224-264)
- Page extraction handler with on-demand injection (lines 269-418)
- Screenshot capture (lines 423-431)
- `ensureExtractorInjected()` helper (lines 437-448)
- Full-page capture algorithm with capture context protocol (lines 461-642)
- Custom scripts handlers (lines 656-868)
- Tab change listeners (lines 870-906)
- Uses ES module imports: `import { QUICK_ACTIONS, MESSAGE_TYPES } from '../shared/constants.js'`

## 1. Architecture Design

### 1.1 Communication Flow

```
Main UI Page (interface.html — in tab or in iframe)
    |
    | window.postMessage({ channel: "ai-assistant-bridge", ... })
    v
bridge.js (content script, ISOLATED WORLD, injected into main UI pages)
    |
    | chrome.runtime.connect() -> persistent Port
    v
service-worker.js (background)
    |
    | chrome.scripting.executeScript() -> injects extractor.js on-demand
    | chrome.tabs.query() -> lists tabs
    | chrome.tabs.captureVisibleTab() -> screenshots
    v
Target Tab (on-demand injected extractor.js / script_runner.js)
    |
    | Result returned back through the same chain
    v
Main UI receives result via window.postMessage from bridge.js
```

### 1.2 Key Design Decisions (Oracle-Validated)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Bridge isolation | Isolated world (default for content scripts) | Prevents page JS from accessing bridge internals |
| Page-to-bridge comm | `window.postMessage` with strict origin + channel filter | Standard, secure, no alternatives for isolated world |
| Bridge-to-SW comm | `chrome.runtime.connect()` (Port) | Survives SW sleep, supports progress streaming, auto-wakes SW |
| Message format | `{ channel, version, direction, requestId, clientId, type, payload }` | Prevents collisions, enables multiplexing |
| Auth model | Extension makes zero backend calls | No cookie/auth complexity at all |
| Content script injection | On-demand via `chrome.scripting.executeScript()` | Avoids conflicts with current extension's auto-injected scripts |
| Multi-tab capture | Accept brief tab switching with progress UI + cancel button | `captureVisibleTab` requires active tab; no workaround |
| Concurrent captures | Single-flight lock in service worker | Prevents conflicts from multiple UI tabs |
| Multiple UI tabs/iframes | Per-tab `clientId`, responses routed by clientId + requestId | Clean multiplexing |
| Extension detection | Bridge dispatches `CustomEvent("ai-assistant-bridge-ready")` on `document` | Reliable, immediate, no polling |
| Permissions | Declared up front in manifest | No UI surface to request permissions later |

### 1.3 Message Protocol

Every message through the bridge follows this schema:

```javascript
// Page -> Bridge (via window.postMessage)
{
    channel: "ai-assistant-bridge",  // fixed namespace, prevents collisions
    version: 1,                      // protocol version for future compat
    direction: "page-to-ext",        // or "ext-to-page"
    requestId: "uuid-v4",            // unique per request, for response matching
    clientId: "uuid-v4",             // unique per page instance, for multiplexing
    type: "EXTRACT_PAGE",            // operation type (see 1.4)
    payload: { ... }                 // operation-specific data
}

// Bridge validates:
//   event.source === window
//   event.origin matches expected origins
//   event.data.channel === "ai-assistant-bridge"
//   event.data.direction === "page-to-ext"
//   top === self OR top origin is chrome-extension:// (iframe extension)
//
// Bridge forwards via Port to service worker with same requestId/clientId
// Service worker processes, returns result with matching requestId/clientId
// Bridge posts back to page with direction: "ext-to-page"
```

**Important for iframe context**: When the main UI is loaded inside the iframe extension's
sidepanel, `top !== self`. The bridge must allow this case when the top frame is a
`chrome-extension://` origin (the iframe extension). Validation rule:
- `top === self` (regular tab) OR
- `top origin starts with chrome-extension://` (inside iframe extension's sidepanel)

### 1.4 Operation Types

| Type | Description | Chrome APIs Used | Returns |
|------|-------------|-----------------|---------|
| `PING` | Extension detection handshake | None | `{ alive: true, version: 1 }` |
| `EXTRACT_CURRENT_PAGE` | Extract content from active non-main-UI tab | `chrome.tabs.query`, `chrome.scripting.executeScript` | `{ title, url, content, contentType }` |
| `EXTRACT_TAB` | Extract content from specific tab by ID | `chrome.scripting.executeScript`, `chrome.tabs.sendMessage` | Same as above |
| `LIST_TABS` | Get all open tabs in current window | `chrome.tabs.query` | `[{ id, title, url, favIconUrl, active }]` |
| `CAPTURE_SCREENSHOT` | Screenshot of a specific tab | `chrome.tabs.update` (activate), `chrome.tabs.captureVisibleTab` | `{ dataUrl }` (base64 PNG) |
| `CAPTURE_FULL_PAGE` | Scroll-capture entire page | `chrome.scripting.executeScript` (scroll helper), `chrome.tabs.captureVisibleTab` | `{ screenshots: [dataUrl, ...], pageTitle, pageUrl }` |
| `CAPTURE_MULTI_TAB` | Extract/capture from multiple tabs | Combination of above | `{ results: [{ tabId, title, url, content, screenshots, error }] }` |
| `EXECUTE_SCRIPT` | Run a custom script on a target tab | `chrome.scripting.executeScript` | `{ result }` |
| `GET_TAB_INFO` | Get info about the active tab | `chrome.tabs.query` | `{ id, title, url, favIconUrl }` |

### 1.5 On-Demand Content Script Injection

Unlike the current extension which auto-injects `extractor.js` on all pages at `document_idle`,
this extension injects content scripts ONLY when a request comes in:

```javascript
// In service-worker.js, when EXTRACT_TAB is requested:
async function injectAndExtract(tabId) {
    // 1. Inject extractor.js into the target tab
    await chrome.scripting.executeScript({
        target: { tabId: tabId },
        files: ['content_scripts/extractor.js']
    });
    
    // 2. Small delay for script to initialize
    await new Promise(r => setTimeout(r, 100));
    
    // 3. Send extraction message
    const result = await chrome.tabs.sendMessage(tabId, { type: 'EXTRACT_PAGE' });
    return result;
}
```

**Why on-demand**: If the user also has the current extension installed, auto-injecting
extractor.js would create duplicates. On-demand injection means this extension only touches
tabs when explicitly asked.

**Idempotency**: extractor.js must handle being injected multiple times gracefully
(the current extractor.js already does this — it checks if already initialized).

## 2. File Structure

```
extension-headless/
+-- manifest.json                    # Minimal permissions, no UI declarations
+-- background/
|   +-- service-worker.js            # Port handler, Chrome API operations, single-flight lock
+-- content_scripts/
|   +-- bridge.js                    # Auto-injected into main UI pages only
|   +-- extractor-core.js            # FROM extension-shared/, injected on-demand (~1,600 lines, no UI)
|   +-- script-runner-core.js        # FROM extension-shared/, on-demand mode (no auto-init)
+-- sandbox/
|   +-- sandbox.html                 # For custom script execution (CSP bypass)
|   +-- sandbox.js                   # Sandbox runtime
+-- assets/
    +-- icons/                       # Extension icons
        +-- icon16.png
        +-- icon32.png
        +-- icon48.png
        +-- icon128.png
```

**Total new files**: ~5-7 files (bridge.js and service-worker.js are new; extractor-core.js,
script-runner-core.js, and sandbox files symlinked/copied from extension-shared/)

**Note**: `script_ui.js` (floating toolbar/command palette) is NOT included. The floating 
toolbar is a current-extension-specific UX feature. In the headless model, scripts are 
managed and triggered from the main UI, not from an on-page toolbar.

## 3. Detailed Tasks

### Task 1: Create directory structure and manifest.json

Create `extension-headless/` directory with the manifest as described in Section 2.

Key manifest points:
- `permissions`: `activeTab`, `scripting`, `tabs` (no `sidePanel`, no `contextMenus`, no `storage`)
- `content_scripts`: Only `bridge.js` on main UI URLs
- `web_accessible_resources`: extractor.js, scroll-helper.js, script_runner.js, sandbox files
- No `action`, no `side_panel` config

### Task 2: Create bridge.js content script

**File**: `extension-headless/content_scripts/bridge.js` (~130 lines)

Responsibilities:
1. Establish Port connection to service worker on load
2. Listen for `window` message events from the page
3. Validate messages (origin, channel, direction, schema)
4. Forward validated requests to service worker via Port
5. Receive responses from service worker, post back to page
6. Handle Port disconnection with reconnect + exponential backoff (100ms start, 5s max)
7. Dispatch `CustomEvent("ai-assistant-bridge-ready")` when Port connected
8. Dispatch `CustomEvent("ai-assistant-bridge-disconnected")` when Port lost
9. Generate unique `bridgeInstanceId` for service worker tracking

Validation checks:
- `event.source === window`
- `event.origin` in allowed origins list
- `event.data.channel === "ai-assistant-bridge"`
- `event.data.direction === "page-to-ext"`
- Required fields present: `requestId`, `type`
- Frame check: `top === self` OR top frame is `chrome-extension://`

### Task 3: Create service-worker.js

**File**: `extension-headless/background/service-worker.js` (~500-600 lines)

Structure:
- Port connection handler (`chrome.runtime.onConnect`)
- Bridge port tracking (`Map<bridgeId, port>`)
- Message dispatcher (switch on `type`)
- Single-flight capture lock
- Handler functions (reuse logic from current extension's service-worker.js):
  - `handleListTabs()` — `chrome.tabs.query`, filter restricted pages
  - `handleExtractCurrentPage()` — find active non-main-UI tab, inject extractor, extract
  - `handleExtractTab({ tabId })` — inject extractor into specific tab, extract
  - `handleCaptureScreenshot({ tabId })` — activate tab, `captureVisibleTab`
  - `handleCaptureFullPage({ tabId, options })` — inject scroll-helper, scroll-capture loop, progress events
  - `handleCaptureMultiTab({ tabs })` — iterate tabs with per-tab mode, progress events
  - `handleExecuteScript({ tabId, code })` — inject script_runner, execute
  - `handleGetTabInfo()` — active tab info

Progress events for long operations sent via same Port:
```javascript
port.postMessage({
    requestId, clientId,
    type: 'PROGRESS',
    payload: { step: 3, total: 5, tabId: 42, message: 'Capturing tab 3 of 5...' }
});
```

### Task 4: Use extractor-core.js from extension-shared

**Source**: `extension-shared/extractor-core.js` (created from splitting extension/content_scripts/extractor.js)
**Destination**: `extension-headless/content_scripts/extractor-core.js` (symlink or copy)

This is the extraction engine WITHOUT UI elements (no floating button, no modals, no toasts).
The split removes ~400 lines of UI code from the original 2,057-line extractor.js.

Key properties of extractor-core.js:
- Idempotent init guard (`window.__aiAssistantInjected`)
- 16 site-specific extractors (Google Docs, Notion, SharePoint, etc.)
- Generic extraction fallback
- KNOWN_SCROLL_SELECTORS table for inner scroll detection
- 5-stage scroll target detection pipeline
- Capture context management (initCaptureContext, scrollContextTo, etc.)
- `chrome.runtime.onMessage` handler for: EXTRACT_PAGE, GET_SELECTION, GET_PAGE_METRICS, SCROLL_TO, INIT_CAPTURE_CONTEXT, SCROLL_CONTEXT_TO, GET_CONTEXT_METRICS, RELEASE_CAPTURE_CONTEXT
- Does NOT include: QUICK_ACTION, SHOW_MODAL, HIDE_MODAL handlers

### Task 5: Split extractor.js into core + UI (prerequisite, shared infra)

**Source**: `extension/content_scripts/extractor.js` (2,057 lines)
**Output**: `extension-shared/extractor-core.js` (~1,600 lines) + `extension/content_scripts/extractor-ui.js` (~400 lines)

This is a prerequisite/shared infrastructure task:
1. Move lines 1-1935 (extraction + scroll + message handler) to extractor-core.js
2. Remove QUICK_ACTION, SHOW_MODAL, HIDE_MODAL cases from the message handler in core
3. Move lines 1937-2057 (showToast, createFloatingButton, injectModalStyles) to extractor-ui.js
4. extractor-ui.js adds its own message listener for UI-only message types and initializes UI
5. Update current extension manifest to load both: `["content_scripts/extractor-core.js", "content_scripts/extractor-ui.js"]`
6. Verify current extension still works identically after the split

**Effort**: 3-4h (careful surgery, must test current extension still works)

### Task 6: Copy sandbox files

Copy `extension/sandbox/sandbox.html` and `extension/sandbox/sandbox.js` to `extension-headless/sandbox/`. Needed for custom script execution CSP bypass. No changes.

### Task 7: Create script-runner-core.js in extension-shared

**Source**: `extension/content_scripts/script_runner.js` (1,449 lines)
**Destination**: `extension-shared/script-runner-core.js`

script_runner.js currently auto-initializes on injection (loads scripts for current URL, watches URL changes via MutationObserver). For the headless extension, we need ON-DEMAND mode only.

Changes from original:
1. Add an init mode check: if `window.__scriptRunnerMode === 'ondemand'` skip auto-init
2. In on-demand mode, skip `loadScriptsForCurrentUrl()` and URL watching in `initialize()`
3. In on-demand mode, only respond to: TEST_SCRIPT, GET_PAGE_CONTEXT messages
4. The headless SW sets `window.__scriptRunnerMode = 'ondemand'` via a preceding executeScript call before injecting script-runner-core.js

**Effort**: 2h

### Task 8: Create extension icons

Create or adapt icons for the headless bridge extension. Use a different color/style from the current extension so users can distinguish them in `chrome://extensions/`.

## 4. Testing Strategy

| Test | Steps | Expected |
|------|-------|----------|
| Bridge injection | Install extension, open localhost:5000 | `ai-assistant-bridge-ready` event fires |
| PING round-trip | Send PING via postMessage from main UI console | Receive `{ alive: true, version: 1 }` |
| LIST_TABS | Send LIST_TABS | Receive array of open tabs |
| EXTRACT_CURRENT_PAGE | Open another tab with content, send from main UI | Receive extracted content |
| EXTRACT_TAB by ID | Send EXTRACT_TAB with specific tabId | Receive that tab's content |
| Google Docs extraction | Open Google Doc, extract | Content extracted correctly |
| CAPTURE_SCREENSHOT | Send CAPTURE_SCREENSHOT for a tab | Receive base64 PNG dataUrl |
| Full-page capture | Send CAPTURE_FULL_PAGE for a long page | Receive array of screenshots + progress events |
| Coexistence | Install both this and current extension | No conflicts, both work |
| SW sleep recovery | Wait 5+ min, then send request | Bridge reconnects, succeeds |
| Multiple UI tabs | Open 2 main UI tabs, extract from both | Each gets correct response |
| Restricted page | Try to extract from chrome:// page | Clean error message returned |

## 5. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| On-demand injection ~100ms slower than auto | Minor delay | Acceptable. Could cache injection state in SW. |
| Both extensions installed, no message cross-talk | N/A — not a problem | `chrome.tabs.sendMessage` is scoped to own extension. Each extension's content scripts are isolated. |
| `chrome.scripting.executeScript` fails on restricted pages | Can't extract | Return `{ error: "Cannot access this page" }` with URL |
| Port disconnects mid-capture | Partial results | Accumulate in SW, return partial on reconnect |
| `<all_urls>` host_permissions triggers Chrome review | Slower publishing | Required for on-demand injection. Document justification. |

## 6. Estimated Effort

| Task | Effort |
|------|--------|
| Task 1: Directory + manifest | 0.5h |
| Task 2: bridge.js | 3-4h |
| Task 3: service-worker.js | 6-8h |
| Task 4: Symlink extractor-core.js | 0.5h |
| Task 5: Split extractor.js (prerequisite, shared) | 3-4h |
| Task 6: Copy sandbox files | 0.5h |
| Task 7: Create script-runner-core.js | 2h |
| Task 8: Icons | 0.5h |
| **Total** | **~16-20h (2-2.5 days)** |

Note: Task 5 (splitting extractor.js) is shared infrastructure that benefits the current extension's maintainability too. If done first, it saves time across all extensions.

## 7. Success Criteria

1. Extension installs cleanly alongside current extension without conflicts
2. Bridge auto-injects on main UI pages (localhost:5000, production)
3. `ai-assistant-bridge-ready` event fires reliably within 1 second of page load
4. All operation types return correct results
5. Port reconnects automatically after service worker sleep
6. Single-flight lock prevents concurrent captures
7. Multiple main UI tabs/iframes receive independently routed responses
8. Zero backend API calls from the extension (verified via network tab)
