---
name: Shared Operations Handler + Iframe Extension Extraction Capabilities
overview: >
  Extract the ~600 lines of Chrome API operation handlers from extension-headless
  into a shared module (extension-shared/operations-handler.js). Give extension-iframe
  its own service-worker that imports the shared handlers and exposes them via
  externally_connectable. Update ExtensionBridge to auto-detect transport (postMessage
  for headless bridge in regular tabs, chrome.runtime.sendMessage for iframe extension).
  This removes the fragile dependency of extension-iframe on extension-headless.
status: draft
created: 2026-02-19
revised: 2026-02-19
oracle-validated: true
depends-on:
  - extension_headless_bridge.plan.md
  - main_ui_extension_integration.plan.md
depended-on-by: none
---

# Shared Operations Handler + Iframe Extension Extraction Capabilities

## Purpose & Intent

### Problem Statement

The current extension-iframe is a dumb iframe wrapper (15-line background.js). For page
extraction features (extract page, multi-tab capture, OCR scroll, screenshots), it depends
on extension-headless being installed alongside it. The headless extension injects bridge.js
into the iframe via `content_scripts` with `all_frames: true`, which has proven fragile:

- `all_frames: false` was the default and caused bridge.js to never inject into the iframe
- URL pattern matching required exact matches (127.0.0.1 vs localhost)
- Race conditions between bridge.js injection and ExtensionBridge.init()
- Frame validation logic in bridge.js rejected iframe messages
- Two extensions must be installed and kept in sync

### Solution

1. Extract the operation handler logic from extension-headless into `extension-shared/operations-handler.js`
2. Give extension-iframe its own service-worker that imports the shared handlers
3. Use `externally_connectable` so the main UI (inside the iframe) can talk directly to the iframe extension's service-worker
4. Update `ExtensionBridge` to auto-detect which transport to use based on environment
5. Keep extension-headless for the regular-browser-tab use case (unchanged transport)

### Architecture After This Change

```
Main UI in regular browser tab            Main UI in iframe (sidepanel extension)
+----------------------------+            +----------------------------+
| interface/interface.html   |            | interface/interface.html   |
| ExtensionBridge            |            | ExtensionBridge            |
| transport: postMessage     |            | transport: externally_     |
|                            |            |   connectable              |
+----------+-----------------+            +----------+-----------------+
           |                                         |
           v                                         v
  bridge.js (content script)              chrome.runtime.sendMessage(extId)
           |                              chrome.runtime.connect(extId)
           v                                         |
  extension-headless/                                v
  service-worker.js                       extension-iframe/
  (Port transport)                        background.js (service-worker)
           |                              (onMessageExternal transport)
           v                                         |
  +----------------------------------------------+   |
  | extension-shared/operations-handler.js       |<--+
  | (shared operation handlers)                  |
  |                                              |
  | Imports: full-page-capture.js                |
  | Uses: chrome.tabs, chrome.scripting,         |
  |   chrome.tabs.captureVisibleTab              |
  +----------------------------------------------+
```

## Design Decisions

### D1: Communication Channel — externally_connectable (Option C)

**Decision**: Use `externally_connectable` manifest key so the main UI page can call
`chrome.runtime.sendMessage(extensionId, msg)` directly to the iframe extension's
service-worker. No content script injection needed.

**Why not postMessage relay (Option A)**: Adds a middleman (sidepanel.js) requiring
bidirectional message plumbing — essentially rebuilding bridge.js inside sidepanel.js.
More code, more latency, more bugs.

**Why not content script injection (Option B)**: This is exactly the fragile pattern
we are escaping. `all_frames:true` + URL matching into an iframe is unreliable.

**How it works**:
- Manifest declares `"externally_connectable": {"matches": ["http://localhost:5000/*", ...]}`
- Page calls `chrome.runtime.sendMessage(extId, {type: 'EXTRACT_CURRENT_PAGE', ...})`
- Service-worker listens on `chrome.runtime.onMessageExternal`
- For streaming operations (OCR progress), use `chrome.runtime.connect(extId)` for a
  persistent Port — same manifest entry, just `onConnectExternal` instead

**Extension ID discovery**: The iframe extension injects a tiny content script (~10 lines)
into matched URLs that sets `window.__aiIframeExtId = chrome.runtime.id`. This is NOT a
message relay — it just advertises the ID so the page knows who to talk to.

### D2: Shared Operation Handlers — Standalone Functions (Option A)

**Decision**: Extract handlers into `extension-shared/operations-handler.js` as standalone
exported functions that accept a `chromeApi` adapter object.

This follows the exact same pattern already used by `extension-shared/full-page-capture.js`
which accepts a `chromeApi` parameter with `captureVisibleTab`, `sendMessage`, `getTab`.

**Why not a class/factory (Option B)**: Unnecessary OOP for stateless functions. The only
shared state is `captureInProgress`, which becomes an explicit lock parameter.

**Why not duplication (Option C)**: 600 lines of non-trivial logic with screenshot timing,
scroll orchestration, and multi-tab capture. Duplication guarantees drift.

### D3: Keep extension-headless Separate — Yes

**Decision**: Keep extension-headless as a separate extension.

- Headless serves the regular-browser-tab use case (main UI opened directly)
- Extension-iframe serves the sidepanel iframe use case
- With shared operation handlers, both service-workers become thin transport adapters
  (~100 lines each). No meaningful duplication.
- Merging would increase complexity (Port + External messaging in one SW) and blast radius

### D4: ExtensionBridge — Auto-detect Transport (Option A)

**Decision**: Make `ExtensionBridge.init()` detect its environment and switch transport
automatically. The public API (extractCurrentPage, listTabs, etc.) stays identical.

Detection logic:
```javascript
var inExtensionIframe = false;
try {
    inExtensionIframe = (top !== self) &&
        document.referrer.startsWith('chrome-extension://');
} catch(e) {
    // cross-origin frame access error = likely extension iframe
    inExtensionIframe = true;
}
```

If `inExtensionIframe` and `window.__aiIframeExtId` exists:
- Use `chrome.runtime.sendMessage(extId, msg)` for simple request-response ops
- Use `chrome.runtime.connect(extId)` for streaming ops (progress events)

Otherwise: use existing postMessage transport (headless bridge).

## Current State (Before)

### extension-shared/ contents (already shared via symlinks)
- `extractor-core.js` (1628 lines) — DOM extraction with 16 site-specific extractors
- `full-page-capture.js` (215 lines) — Parameterized scroll+capture (accepts chromeApi adapter)
- `script-runner-core.js` (1476 lines) — Script execution engine
- `sandbox.html` + `sandbox.js` (245 lines) — Sandboxed execution

### extension-headless/background/service-worker.js (797 lines)
Operations implemented directly in service-worker:
- PING, LIST_TABS, GET_TAB_INFO
- EXTRACT_CURRENT_PAGE, EXTRACT_TAB
- CAPTURE_SCREENSHOT, CAPTURE_FULL_PAGE, CAPTURE_FULL_PAGE_WITH_OCR
- CAPTURE_MULTI_TAB (dom/ocr/full-ocr/auto modes)
- EXECUTE_SCRIPT

Utility functions:
- `isMainUITab(url)`, `isRestrictedUrl(url)`, `countWords(text)`
- `ensureExtractorInjected(tabId)`, `findTargetTab()`
- `sendResponse()`, `sendProgress()`
- `captureOneTab()`, `captureTabDom()`, `captureTabOcr()`, `captureTabFullOcr()`

Transport: Port-based (chrome.runtime.onConnect with bridge.js content script)

### extension-iframe/ (current — dumb wrapper)
- `manifest.json` — permissions: sidePanel, storage, scripting
- `background.js` (15 lines) — just opens sidepanel
- `sidepanel/sidepanel.js` (113 lines) — connection screen + iframe loader
- `content_scripts/floating-btn.js` (155 lines) — FAB button
- NO shared code, NO extraction capabilities, NO host_permissions

### interface/extension-bridge.js (255 lines)
- postMessage-only transport
- Detects bridge via: `window.__aiBridgeReady` flag, CustomEvent, PING fallback
- 11 operations: ping, extractCurrentPage, extractTab, listTabs, captureScreenshot,
  captureFullPage, captureMultiTab, executeScript, getTabInfo, captureFullPageWithOcr
- Progress callback support for streaming operations

## Implementation Plan

### Phase 1: Create Shared Operations Handler

**Goal**: Extract operation handler logic from headless service-worker into a reusable
ES module in extension-shared/.

#### Task 1.1: Create extension-shared/operations-handler.js

Create a new ES module that exports all operation handler functions. Each function
accepts a `chromeApi` adapter and returns a result (or throws an error object).

**Adapter interface** (passed by each service-worker):
```javascript
const chromeApi = {
    tabs: {
        query: (q) => chrome.tabs.query(q),
        get: (id) => chrome.tabs.get(id),
        sendMessage: (id, msg) => chrome.tabs.sendMessage(id, msg),
        update: (id, props) => chrome.tabs.update(id, props),
        captureVisibleTab: (wid, opts) => chrome.tabs.captureVisibleTab(wid, opts)
    },
    scripting: {
        executeScript: (opts) => chrome.scripting.executeScript(opts)
    },
    runtime: {
        id: chrome.runtime.id
    }
};
```

**Exported functions** (all async except handlePing):

Utilities (not exported, internal to module):
- `isMainUITab(url, patterns)` — accepts patterns array parameter
- `isRestrictedUrl(url)` — same logic
- `countWords(text)` — same logic
- `ensureExtractorInjected(tabId, chromeApi)` — uses chromeApi.scripting
- `findTargetTab(chromeApi, mainUIPatterns)` — uses chromeApi.tabs.query

Exported operation handlers:
- `handlePing(chromeApi)` → `{alive, version, extensionId}`
- `handleListTabs(chromeApi, mainUIPatterns)` → `{tabs: [...]}`
- `handleGetTabInfo(chromeApi, mainUIPatterns)` → `{id, title, url, favIconUrl}`
- `handleExtractCurrentPage(chromeApi, mainUIPatterns)` → `{tabId, title, url, content, wordCount, charCount, contentType, extractionMethod}`
- `handleExtractTab(chromeApi, payload)` → same shape as above
- `handleCaptureScreenshot(chromeApi, payload, captureState)` → `{tabId, dataUrl, width, height}`
- `handleCaptureFullPage(chromeApi, payload, captureState, onProgress)` → `{tabId, screenshots, pageTitle, pageUrl, scrollType, totalHeight, viewportHeight}`
- `handleCaptureFullPageWithOcr(chromeApi, payload, captureState, onProgress)` → streams progress, returns `{tabId, capturedCount, total, pageTitle, pageUrl, meta}`
- `handleCaptureMultiTab(chromeApi, payload, captureState, onProgress)` → `{results, completedCount, totalCount}`
- `handleExecuteScript(chromeApi, payload)` → `{tabId, result, success}`

**captureState parameter**: Replaces the module-level `captureInProgress` boolean.
Each service-worker owns its lock:
```javascript
const captureState = { inProgress: false };
```
Handlers check/set `captureState.inProgress` instead of a module global.

**onProgress parameter**: A callback function `(progressPayload) => void` that the
handler calls for streaming updates. The caller (service-worker) decides how to
send it (Port.postMessage, sendResponse, etc.).

**Internal helper functions** (also extracted, not exported):
- `captureOneTab(chromeApi, tabId, mode)` — mode dispatch (dom/ocr/full-ocr/auto)
- `captureTabDom(chromeApi, tab)` — DOM extraction via content script
- `captureTabOcr(chromeApi, tab)` — single viewport screenshot
- `captureTabFullOcr(chromeApi, tab)` — full-page scroll capture

**File size estimate**: ~650 lines (handlers + utilities + docstrings)

**Files created**:
- `extension-shared/operations-handler.js`

#### Task 1.2: Create symlinks in extension-headless and extension-iframe

```bash
# In extension-headless/background/
ln -s ../../extension-shared/operations-handler.js operations-handler.js

# In extension-iframe/background/
mkdir -p extension-iframe/background
ln -s ../../extension-shared/operations-handler.js extension-iframe/background/operations-handler.js
```

Note: build.sh already handles replacing symlinks with copies for all extension dirs.

**Files modified**: filesystem symlinks only

#### Task 1.3: Verify full-page-capture.js import path

`operations-handler.js` needs to import `full-page-capture.js`. Since both will be
in the same directory (via symlinks), the import is:
```javascript
import { captureFullPage } from './full-page-capture.js';
```
This works because in extension-headless/background/ both files are symlinked there,
and in extension-iframe/background/ both will also be symlinked there.

**Risk**: If the symlink structure places them in different directories, the relative
import breaks. Mitigation: verify symlink layout before proceeding.

**Files modified**: none (verification only)

### Phase 2: Refactor extension-headless Service-Worker

**Goal**: Slim down the headless service-worker to a thin transport adapter that imports
shared handlers. The Port-based transport (bridge.js ↔ service-worker) stays unchanged.

#### Task 2.1: Refactor extension-headless/background/service-worker.js

Replace inline handler implementations with imports from operations-handler.js.

Before (~797 lines):
```javascript
// All handler logic inline
async function handleExtractCurrentPage() { /* 30 lines */ }
async function handleCaptureFullPage(payload, port, requestId, clientId) { /* 60 lines */ }
// ... etc
```

After (~120 lines):
```javascript
import {
    handlePing, handleListTabs, handleGetTabInfo,
    handleExtractCurrentPage, handleExtractTab,
    handleCaptureScreenshot, handleCaptureFullPage,
    handleCaptureFullPageWithOcr, handleCaptureMultiTab,
    handleExecuteScript
} from './operations-handler.js';

const MAIN_UI_PATTERNS = ['localhost:5000', '127.0.0.1:5000', 'assist-chat.site'];
const captureState = { inProgress: false };
const chromeApi = { /* adapter */ };

// Port listener + dispatch + sendResponse/sendProgress
chrome.runtime.onConnect.addListener((port) => {
    // ... same Port plumbing as now, but dispatch calls imported handlers
    // For streaming ops, pass onProgress callback that calls sendProgress()
});
```

**Key changes**:
- Remove all `handle*` function bodies (replaced by imports)
- Remove utility functions (isMainUITab, isRestrictedUrl, etc.)
- Remove capture helper functions (captureOneTab, captureTabDom, etc.)
- Keep: Port listener, sendResponse, sendProgress, MAIN_UI_PATTERNS, chromeApi adapter
- Keep: handleMessage dispatcher (calls imported functions)
- Add: `captureState` object passed to capture handlers

**Verification**:
- Extension-headless should work identically after refactor
- Test: install headless extension, open main UI in regular tab, verify extraction buttons work

**Files modified**:
- `extension-headless/background/service-worker.js`

### Phase 3: Upgrade extension-iframe

**Goal**: Transform extension-iframe from a dumb iframe wrapper into a full extension
with its own service-worker, Chrome API permissions, and shared extraction capabilities.

#### Task 3.1: Update extension-iframe/manifest.json

Add required permissions, externally_connectable, shared file references.

Changes:
```json
{
    "permissions": [
        "sidePanel",
        "storage",
        "scripting",
        "tabs",
        "activeTab"
    ],
    "host_permissions": [
        "<all_urls>"
    ],
    "externally_connectable": {
        "matches": [
            "http://localhost:5000/*",
            "http://127.0.0.1:5000/*",
            "https://assist-chat.site/*"
        ]
    },
    "background": {
        "service_worker": "background/service-worker.js",
        "type": "module"
    },
    "content_scripts": [
        {
            "matches": ["<all_urls>"],
            "js": ["content_scripts/floating-btn.js"],
            "run_at": "document_end"
        },
        {
            "matches": [
                "http://localhost:5000/*",
                "http://127.0.0.1:5000/*",
                "https://assist-chat.site/*"
            ],
            "js": ["content_scripts/id-advertiser.js"],
            "run_at": "document_start",
            "all_frames": true
        }
    ],
    "web_accessible_resources": [{
        "resources": [
            "content_scripts/extractor-core.js",
            "content_scripts/script-runner-core.js",
            "sandbox/sandbox.html",
            "sandbox/sandbox.js"
        ],
        "matches": ["<all_urls>"]
    }],
    "sandbox": {
        "pages": ["sandbox/sandbox.html"]
    }
}
```

**Key additions**:
- `tabs` permission — needed for chrome.tabs.query, chrome.tabs.get
- `host_permissions: ["<all_urls>"]` — needed for chrome.scripting.executeScript on any tab
- `externally_connectable` — allows main UI pages to call chrome.runtime.sendMessage to this extension
- `background.service_worker` changed from `background.js` to `background/service-worker.js` (ES module)
- `content_scripts` adds `id-advertiser.js` for extension ID discovery
- `web_accessible_resources` — shared content scripts injected on-demand
- `sandbox` — for script-runner sandbox execution

**Risk**: The `externally_connectable.matches` only covers known URLs. Custom server
URLs won't be able to call the extension directly. Mitigation: document this limitation;
custom URLs can still use the headless extension approach.

**Files modified**:
- `extension-iframe/manifest.json`

#### Task 3.2: Create shared file symlinks in extension-iframe

```bash
# Content scripts (for on-demand injection into target tabs)
ln -s ../../extension-shared/extractor-core.js extension-iframe/content_scripts/extractor-core.js
ln -s ../../extension-shared/script-runner-core.js extension-iframe/content_scripts/script-runner-core.js

# Background (service-worker imports)
mkdir -p extension-iframe/background
ln -s ../../extension-shared/operations-handler.js extension-iframe/background/operations-handler.js
ln -s ../../extension-shared/full-page-capture.js extension-iframe/background/full-page-capture.js

# Sandbox
mkdir -p extension-iframe/sandbox
ln -s ../../extension-shared/sandbox.html extension-iframe/sandbox/sandbox.html
ln -s ../../extension-shared/sandbox.js extension-iframe/sandbox/sandbox.js
```

**Files created**: symlinks

#### Task 3.3: Create extension-iframe/content_scripts/id-advertiser.js

A tiny content script that advertises the extension ID to the page. Injected into
main UI URLs so ExtensionBridge can discover who to talk to.

```javascript
/**
 * ID Advertiser Content Script for AI Assistant Iframe Extension
 *
 * Injected into main UI pages (localhost:5000, assist-chat.site) to advertise
 * the extension ID. The main UI reads window.__aiIframeExtId to know which
 * extension to call via chrome.runtime.sendMessage().
 *
 * This is NOT a message relay — it only sets a single property.
 */
(function() {
    'use strict';
    window.__aiIframeExtId = chrome.runtime.id;
    document.dispatchEvent(new CustomEvent('ai-iframe-extension-ready', {
        detail: { extensionId: chrome.runtime.id }
    }));
})();
```

~10 lines. No message relay, no Port, no ongoing communication.

**Files created**:
- `extension-iframe/content_scripts/id-advertiser.js`

#### Task 3.4: Create extension-iframe/background/service-worker.js

New service-worker that imports shared handlers and exposes them via
`onMessageExternal` (request-response) and `onConnectExternal` (streaming).

Also preserves the existing sidepanel open behavior from the old background.js.

```javascript
/**
 * Service Worker for AI Assistant Iframe Sidepanel Extension
 *
 * Provides Chrome API operations (page extraction, tab listing, screenshots,
 * OCR capture, script execution) to the main UI loaded inside the sidepanel
 * iframe. Communication via externally_connectable (onMessageExternal for
 * request-response, onConnectExternal for streaming operations).
 *
 * Operation handler logic is imported from the shared operations-handler.js
 * module (extension-shared/).
 */
import {
    handlePing, handleListTabs, handleGetTabInfo,
    handleExtractCurrentPage, handleExtractTab,
    handleCaptureScreenshot, handleCaptureFullPage,
    handleCaptureFullPageWithOcr, handleCaptureMultiTab,
    handleExecuteScript
} from './operations-handler.js';

const P = '[IframeSW]';
const MAIN_UI_PATTERNS = ['localhost:5000', '127.0.0.1:5000', 'assist-chat.site'];
const captureState = { inProgress: false };

const chromeApi = {
    tabs: {
        query: (q) => chrome.tabs.query(q),
        get: (id) => chrome.tabs.get(id),
        sendMessage: (id, msg) => chrome.tabs.sendMessage(id, msg),
        update: (id, props) => chrome.tabs.update(id, props),
        captureVisibleTab: (wid, opts) => chrome.tabs.captureVisibleTab(wid, opts || {format:'png'})
    },
    scripting: {
        executeScript: (opts) => chrome.scripting.executeScript(opts)
    },
    runtime: { id: chrome.runtime.id }
};

// Sidepanel behavior (preserved from old background.js)
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'OPEN_SIDEPANEL' && sender.tab) {
        chrome.sidePanel.open({ tabId: sender.tab.id })
            .then(() => sendResponse({ success: true }))
            .catch((err) => sendResponse({ success: false, error: err.message }));
        return true;
    }
});

// === Request-Response Operations (onMessageExternal) ===
// For simple operations that return a single result.

chrome.runtime.onMessageExternal.addListener((msg, sender, sendResponse) => {
    // Validate sender URL matches externally_connectable patterns
    const senderUrl = sender.url || sender.tab?.url || '';
    if (!MAIN_UI_PATTERNS.some(p => senderUrl.includes(p))) {
        sendResponse({ success: false, error: { code: 'UNAUTHORIZED', message: 'Sender not allowed' } });
        return true;
    }

    const { type, payload } = msg;
    handleOperation(type, payload)
        .then(result => sendResponse({ success: true, payload: result }))
        .catch(err => sendResponse({
            success: false,
            error: { code: err.code || 'UNKNOWN', message: err.message || String(err) }
        }));
    return true; // keep channel open for async
});

// === Streaming Operations (onConnectExternal) ===
// For operations that send progress events (CAPTURE_FULL_PAGE, CAPTURE_FULL_PAGE_WITH_OCR, CAPTURE_MULTI_TAB)

chrome.runtime.onConnectExternal.addListener((port) => {
    port.onMessage.addListener((msg) => {
        const { type, payload, requestId } = msg;
        const onProgress = (progressPayload) => {
            try {
                port.postMessage({ type: 'PROGRESS', requestId, payload: progressPayload });
            } catch (_) {}
        };
        handleOperation(type, payload, onProgress)
            .then(result => {
                try { port.postMessage({ type: 'RESPONSE', requestId, success: true, payload: result }); }
                catch (_) {}
            })
            .catch(err => {
                try { port.postMessage({
                    type: 'RESPONSE', requestId, success: false,
                    error: { code: err.code || 'UNKNOWN', message: err.message || String(err) }
                }); } catch (_) {}
            });
    });
});

// === Operation Dispatcher ===

async function handleOperation(type, payload, onProgress) {
    switch (type) {
        case 'PING':
            return handlePing(chromeApi);
        case 'LIST_TABS':
            return handleListTabs(chromeApi, MAIN_UI_PATTERNS);
        case 'GET_TAB_INFO':
            return handleGetTabInfo(chromeApi, MAIN_UI_PATTERNS);
        case 'EXTRACT_CURRENT_PAGE':
            return handleExtractCurrentPage(chromeApi, MAIN_UI_PATTERNS);
        case 'EXTRACT_TAB':
            return handleExtractTab(chromeApi, payload);
        case 'CAPTURE_SCREENSHOT':
            return handleCaptureScreenshot(chromeApi, payload, captureState);
        case 'CAPTURE_FULL_PAGE':
            return handleCaptureFullPage(chromeApi, payload, captureState, onProgress);
        case 'CAPTURE_FULL_PAGE_WITH_OCR':
            return handleCaptureFullPageWithOcr(chromeApi, payload, captureState, onProgress);
        case 'CAPTURE_MULTI_TAB':
            return handleCaptureMultiTab(chromeApi, payload, captureState, onProgress);
        case 'EXECUTE_SCRIPT':
            return handleExecuteScript(chromeApi, payload);
        default:
            throw { code: 'UNKNOWN', message: 'Unknown operation: ' + type };
    }
}
```

~100 lines. All business logic delegated to shared handlers.

**Files created**:
- `extension-iframe/background/service-worker.js`

**Files deleted**:
- `extension-iframe/background.js` (replaced by background/service-worker.js)

#### Task 3.5: Move old background.js functionality

The old `extension-iframe/background.js` had sidepanel open behavior. This is now
in the new service-worker (Task 3.4). Delete the old file.

**Files deleted**:
- `extension-iframe/background.js`

### Phase 4: Update ExtensionBridge for Dual Transport

**Goal**: Make `interface/extension-bridge.js` auto-detect whether it's inside an
extension iframe and switch to `externally_connectable` transport, while keeping the
existing postMessage transport for the headless bridge case.

#### Task 4.1: Add environment detection to ExtensionBridge.init()

Add detection logic at the start of `init()`:

```javascript
var _inExtensionIframe = false;
var _iframeExtId = null;
var _useExternalTransport = false;

try {
    _inExtensionIframe = (top !== self) &&
        document.referrer.startsWith('chrome-extension://');
} catch(e) {
    _inExtensionIframe = true;
}
```

In `init()`, after environment detection:
- If `_inExtensionIframe`: look for `window.__aiIframeExtId` (set by id-advertiser.js)
  - If found immediately: activate with externally_connectable transport
  - If not found: listen for `ai-iframe-extension-ready` CustomEvent
  - Fallback: 2s timeout, check again, then give up
- If NOT in iframe: use existing postMessage detection (flag, event, PING)

**Files modified**:
- `interface/extension-bridge.js`

#### Task 4.2: Add externally_connectable transport to _sendMessage

Add a second transport path. Rename existing postMessage logic to `_sendMessagePostMessage`.
Add `_sendMessageExternal` (simple request-response via `chrome.runtime.sendMessage`)
and `_sendMessageExternalStreaming` (Port-based via `chrome.runtime.connect` for progress).

Main dispatcher:
```javascript
function _sendMessage(type, payload, timeoutMs) {
    if (!_available) return Promise.reject(new Error('Extension not available'));
    timeoutMs = timeoutMs || 30000;
    var requestId = _generateId();

    if (_useExternalTransport) {
        var STREAMING_OPS = [
            'CAPTURE_FULL_PAGE', 'CAPTURE_FULL_PAGE_WITH_OCR', 'CAPTURE_MULTI_TAB'
        ];
        if (STREAMING_OPS.indexOf(type) >= 0) {
            return _sendMessageExternalStreaming(type, payload, requestId, timeoutMs);
        }
        return _sendMessageExternal(type, payload, requestId, timeoutMs);
    }
    return _sendMessagePostMessage(type, payload, requestId, timeoutMs);
}
```

Simple request-response (uses chrome.runtime.sendMessage):
```javascript
function _sendMessageExternal(type, payload, requestId, timeoutMs) {
    return new Promise(function(resolve, reject) {
        var timer = setTimeout(function() {
            reject(new Error('Timeout: ' + type));
        }, timeoutMs);
        chrome.runtime.sendMessage(_iframeExtId, {
            type: type, payload: payload || {}, requestId: requestId
        }, function(response) {
            clearTimeout(timer);
            if (chrome.runtime.lastError) {
                reject(new Error(chrome.runtime.lastError.message));
                return;
            }
            if (response && response.success) resolve(response.payload);
            else reject(response ? response.error : { message: 'No response' });
        });
    });
}
```

Streaming (uses chrome.runtime.connect for Port-based progress):
```javascript
function _sendMessageExternalStreaming(type, payload, requestId, timeoutMs) {
    return new Promise(function(resolve, reject) {
        var port = chrome.runtime.connect(_iframeExtId);
        var timer = setTimeout(function() {
            try { port.disconnect(); } catch(_) {}
            reject(new Error('Timeout: ' + type));
        }, timeoutMs);
        port.postMessage({ type: type, payload: payload || {}, requestId: requestId });
        port.onMessage.addListener(function(msg) {
            if (msg.requestId !== requestId) return;
            if (msg.type === 'PROGRESS') {
                _progressCallbacks.forEach(function(cb) {
                    try { cb(msg.payload); } catch(e) {}
                });
            } else if (msg.type === 'RESPONSE') {
                clearTimeout(timer);
                try { port.disconnect(); } catch(_) {}
                if (msg.success) resolve(msg.payload);
                else reject(msg.error || { message: 'Unknown error' });
            }
        });
        port.onDisconnect.addListener(function() {
            clearTimeout(timer);
            if (chrome.runtime.lastError) {
                reject(new Error(chrome.runtime.lastError.message));
            }
        });
    });
}
```

**Files modified**:
- `interface/extension-bridge.js`

#### Task 4.3: Update availability change notification

When using externally_connectable transport, availability lifecycle:
- Available when `_iframeExtId` is discovered
- Unavailable if `chrome.runtime.sendMessage` fails with connection error

When `_inExtensionIframe` is true and extension ID is found:
```javascript
_available = true;
_useExternalTransport = true;
_iframeExtId = window.__aiIframeExtId;
ExtensionBridge.isAvailable = true;
_notifyAvailability(true);
```

**Files modified**:
- `interface/extension-bridge.js`

### Phase 5: Cleanup and Documentation

#### Task 5.1: Update extension-shared/README.md

Add `operations-handler.js` to the module inventory. Document:
- Purpose: shared Chrome API operation handlers
- Adapter interface (chromeApi object shape)
- How each extension imports it
- captureState pattern for mutex management

**Files modified**:
- `extension-shared/README.md`

#### Task 5.2: Update extension architecture documentation

Update extension design docs to reflect:
- extension-iframe now has own extraction capabilities
- externally_connectable communication pattern
- shared operations handler architecture
- Both headless and iframe extensions import from extension-shared/

**Files modified**:
- Relevant docs in `documentation/features/extension/`

#### Task 5.3: Verify build.sh handles new symlinks

build.sh already processes all extension-* directories for symlinks. Verify it
correctly replaces the new symlinks in extension-iframe/background/ and
extension-iframe/content_scripts/ and extension-iframe/sandbox/.

No code changes expected — build.sh uses `find` to locate all symlinks pointing
to extension-shared/ in any extension directory.

**Files modified**: none (verification only)

## Risks and Mitigations

### R1: externally_connectable URL coverage

**Risk**: `externally_connectable.matches` only covers hardcoded URLs (localhost:5000,
127.0.0.1:5000, assist-chat.site). Custom server URLs won't work.

**Mitigation**: Document this limitation. Custom URL users need the headless extension.
Future enhancement: dynamic `externally_connectable` is not supported by Chrome, but
we could add a relay content script (registered dynamically via
`chrome.scripting.registerContentScripts()`) for custom URLs if needed.

### R2: chrome.runtime.sendMessage availability in iframe

**Risk**: The main UI page inside the iframe calls `chrome.runtime.sendMessage(extId, ...)`.
This requires the page to have access to `chrome.runtime` API. Web pages can access
`chrome.runtime.sendMessage` when the extension declares `externally_connectable` — this
is a standard Chrome API for web-to-extension communication.

**Mitigation**: Verified — `chrome.runtime.sendMessage` is available to web pages when
`externally_connectable` is declared in the target extension's manifest. This is
documented Chrome behavior, not a hack.

### R3: iframe sandbox restrictions

**Risk**: The sidepanel.html iframe might have sandbox attributes that prevent
`chrome.runtime.sendMessage` from working inside it.

**Mitigation**: The iframe in sidepanel.html does NOT use a `sandbox` attribute.
It's a plain `<iframe src="...">`. The `sandbox` in manifest.json is only for
the script-runner sandbox page, not the main UI iframe.

### R4: Extension ID stability

**Risk**: Extension IDs change when reloading unpacked extensions in development.

**Mitigation**: The id-advertiser.js content script sets the ID dynamically on
every page load. ExtensionBridge reads it at init time. No hardcoded IDs.

### R5: Race condition — id-advertiser.js vs ExtensionBridge.init()

**Risk**: ExtensionBridge.init() runs before id-advertiser.js sets the extension ID.

**Mitigation**: id-advertiser.js runs at `document_start` (earliest possible).
ExtensionBridge.init() runs from jQuery `$(document).ready()` which is `DOMContentLoaded`
or later. The content script will always run first. Additionally, the CustomEvent
`ai-iframe-extension-ready` provides a fallback detection mechanism.

### R6: Both headless and iframe extensions installed simultaneously

**Risk**: Both extensions try to provide extraction capabilities to the same page.

**Mitigation**: ExtensionBridge detects environment first:
- If in extension iframe (`top !== self` + chrome-extension referrer) → use iframe
  extension via externally_connectable. Headless bridge.js may also inject but
  ExtensionBridge ignores its postMessage events once external transport is active.
- If in regular tab → use headless bridge via postMessage. Iframe extension's
  id-advertiser.js also injects but ExtensionBridge ignores it (not in iframe).

Priority: iframe extension transport takes precedence when in iframe context.

## File Inventory (All Changes)

### New Files
| File | Lines (est.) | Description |
|---|---|---|
| `extension-shared/operations-handler.js` | ~650 | Shared operation handler functions |
| `extension-iframe/background/service-worker.js` | ~100 | Iframe extension service-worker |
| `extension-iframe/content_scripts/id-advertiser.js` | ~10 | Extension ID advertiser |

### Modified Files
| File | Change Type | Description |
|---|---|---|
| `extension-headless/background/service-worker.js` | Major refactor | ~797 to ~120 lines, imports shared handlers |
| `extension-iframe/manifest.json` | Update | Add permissions, externally_connectable, shared refs |
| `interface/extension-bridge.js` | Update | Add iframe detection + external transport (~50 lines added) |
| `extension-shared/README.md` | Update | Document new operations-handler.js module |

### Deleted Files
| File | Reason |
|---|---|
| `extension-iframe/background.js` | Replaced by background/service-worker.js |

### New Symlinks
| Symlink | Target |
|---|---|
| `extension-iframe/content_scripts/extractor-core.js` | `../../extension-shared/extractor-core.js` |
| `extension-iframe/content_scripts/script-runner-core.js` | `../../extension-shared/script-runner-core.js` |
| `extension-iframe/background/operations-handler.js` | `../../extension-shared/operations-handler.js` |
| `extension-iframe/background/full-page-capture.js` | `../../extension-shared/full-page-capture.js` |
| `extension-iframe/sandbox/sandbox.html` | `../../extension-shared/sandbox.html` |
| `extension-iframe/sandbox/sandbox.js` | `../../extension-shared/sandbox.js` |

### Existing Symlink (new, in extension-headless)
| Symlink | Target |
|---|---|
| `extension-headless/background/operations-handler.js` | `../../extension-shared/operations-handler.js` |

## Testing Checklist

### Phase 1-2 (Shared handlers + headless refactor)
- [ ] extension-headless loads without errors after refactor
- [ ] Open main UI in regular browser tab
- [ ] Verify extraction buttons appear (bridge detected)
- [ ] Extract single page — content + word count displayed
- [ ] List tabs via multi-tab picker — tabs shown
- [ ] OCR scroll capture — screenshots stream, OCR results combine
- [ ] Script execution via script manager — scripts run on target tab

### Phase 3 (Iframe extension upgrade)
- [ ] extension-iframe loads without manifest errors
- [ ] Sidepanel opens, connection screen works, iframe loads main UI
- [ ] id-advertiser.js runs inside iframe (check `window.__aiIframeExtId` in console)
- [ ] service-worker responds to external messages (test PING via console)
- [ ] No permission errors in service-worker console

### Phase 4 (ExtensionBridge dual transport)
- [ ] In iframe: ExtensionBridge detects external transport
- [ ] In iframe: extraction buttons appear
- [ ] In iframe: extract page — content + word count
- [ ] In iframe: multi-tab picker — tabs listed
- [ ] In iframe: OCR scroll capture with streaming progress
- [ ] In regular tab: postMessage transport still works (headless bridge)
- [ ] Both extensions installed: no conflicts, correct transport chosen

### Edge Cases
- [ ] Only iframe extension installed (no headless) — main UI in regular tab shows no buttons
- [ ] Only headless installed (no iframe) — iframe extension has no extraction (expected)
- [ ] Both installed — iframe uses own SW, regular tab uses headless
- [ ] Extension reloaded — ID changes, id-advertiser still works on next page load
- [ ] assist-chat.site (production) — externally_connectable matches work

## Implementation Order

Execute phases sequentially. Each phase should be independently verifiable.

1. **Phase 1** — Create operations-handler.js, symlinks (no behavior change yet)
2. **Phase 2** — Refactor headless SW to use shared handlers (verify headless still works)
3. **Phase 3** — Upgrade iframe extension (verify new SW works independently)
4. **Phase 4** — Update ExtensionBridge (verify both transports)
5. **Phase 5** — Docs and cleanup

Total estimated effort: ~800 lines of new/modified code across 7 files.
Estimated time: 1-2 sessions.