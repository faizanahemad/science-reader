---
name: Deprecate Headless Extension — Unify on externally_connectable
overview: >
  Deprecate extension-headless entirely. The main web UI in regular browser tabs
  will use extension-iframe's service worker via externally_connectable, the same
  transport already used by the iframe sidepanel context. ExtensionBridge is
  simplified from dual-transport (postMessage + externally_connectable) to
  single-transport (externally_connectable only). The id-advertiser content script
  already runs on all matching pages (not just iframes), so the main UI in a
  regular tab already has access to the extension ID. This removes a redundant
  extension, eliminates the fragile postMessage bridge, and halves the transport
  code in ExtensionBridge.
status: implemented
created: 2026-02-20
revised: 2026-02-20
oracle-validated: true
depends-on:
  - shared_operations_iframe_extraction.plan.md
depended-on-by: none
---

# Deprecate Headless Extension — Unify on `externally_connectable`

## Purpose & Intent

### Problem Statement

We currently maintain two extensions that provide identical Chrome API capabilities
to the main web UI:

1. **extension-headless** — serves regular browser tabs via postMessage bridge
   (content script `bridge.js` ↔ service-worker via Port)
2. **extension-iframe** — serves the sidepanel iframe via `externally_connectable`
   (`chrome.runtime.sendMessage(extId)` / `chrome.runtime.connect(extId)`)

Both import the same 10 operation handlers from `extension-shared/operations-handler.js`.
The headless extension is redundant because `externally_connectable` works for **any
web page** matching the URL patterns — not just pages inside iframes.

Problems with maintaining both:
- Two extensions with identical capabilities must be kept in sync
- Two transport implementations in ExtensionBridge (377 lines, ~50% is postMessage code)
- postMessage transport is fragile (Port reconnection, exponential backoff, bridge.js injection timing)
- Users must install two extensions for full functionality
- Button visibility logic has an artificial `ext-btn-iframe-only` distinction

### Solution

1. Remove the postMessage transport from `ExtensionBridge` (keep only `externally_connectable`)
2. Rename iframe-specific variables to generic names (it's no longer iframe-only)
3. Simplify button visibility — all `ext-btn` buttons show when extension is available
4. Mark extension-headless as deprecated (keep files for reference)
5. Update build script and documentation

### Architecture After This Change

```
Main UI in regular browser tab            Main UI in iframe (sidepanel extension)
+----------------------------+            +----------------------------+
| interface/interface.html   |            | interface/interface.html   |
|                            |            |  (loaded inside iframe)    |
| ExtensionBridge.init()     |            | ExtensionBridge.init()     |
|   ↓ checks window.__aiExtId|            |   ↓ checks window.__aiExtId|
|   ↓ found (id-advertiser)  |            |   ↓ found (id-advertiser)  |
|   ↓ activateExtTransport() |            |   ↓ activateExtTransport() |
+------|---------------------+            +------|---------------------+
       | chrome.runtime.sendMessage(extId)        | chrome.runtime.sendMessage(extId)
       | chrome.runtime.connect(extId)            | chrome.runtime.connect(extId)
       v                                          v
+----------------------------------------------+
| extension-iframe service-worker              |
|  ↓ onMessageExternal / onConnectExternal     |
|  ↓ handleOperation(type, payload, onProgress)|
|  ↓ imports from operations-handler.js        |
+----------------------------------------------+
       |
       v
+----------------------------------------------+
| extension-shared/operations-handler.js       |
| (10 handlers via chromeApi adapter)          |
+----------------------------------------------+
```

**Key insight**: Both contexts use the exact same transport path. The only difference
is whether the browser tab is inside a sidepanel iframe or standalone — the extension
doesn't care. `id-advertiser.js` runs on all matching pages regardless.

## Design Decisions

### D1: Keep id-advertiser.js content script (don't switch to probe-based detection)

**Decision**: Keep the content script that injects `window.__aiExtId` into the main world.

**Why not probe-based**: An alternative is to call `chrome.runtime.sendMessage(hardcodedExtId)`
and catch errors. However:
- Extension ID changes for each unpacked dev install — can't hardcode it
- Published extension has a fixed ID, but dev workflow needs dynamic discovery
- Content script approach is already working and battle-tested
- `chrome.runtime` may not be defined at all if no extension is installed (Chrome 106+)

**How it works**: `id-advertiser.js` (content script, `document_start`, matching pages only)
injects a `<script>` tag into the main world that sets `window.__aiExtId = "<extId>"` and
dispatches a `CustomEvent("ai-extension-ready")`. ExtensionBridge.init() checks this
variable at DOMContentLoaded.

### D2: Remove postMessage transport entirely (no backward compatibility)

**Decision**: Delete all postMessage code from ExtensionBridge. No fallback.

**Why**: The headless extension is the ONLY consumer of postMessage transport. Once
deprecated, there is no code path that needs it. Keeping dead code adds confusion.

### D3: Simplify button visibility — remove ext-btn-iframe-only class

**Decision**: Show all `ext-btn` buttons when extension is available, regardless of context.

**Why**: The `ext-btn-iframe-only` class was added because in the old architecture,
the "Page" (extract) button only worked in iframe context (where extension-iframe had
its own service worker). In regular tabs, headless extension provided the capability
but through a different button/flow. Now that both contexts use the same extension,
there's no reason to distinguish. All operations work in both contexts.

### D4: Rename iframe-specific identifiers to generic names

**Decision**: `__aiIframeExtId` → `__aiExtId`, `ai-iframe-extension-ready` → `ai-extension-ready`

**Why**: These identifiers were named when they were iframe-specific. Now they serve
all contexts. The old names would confuse future developers into thinking they're
iframe-only. The rename is purely cosmetic — no behavior change.

### D5: Keep extension-headless files (don't delete)

**Decision**: Mark deprecated, keep for reference.

**Why**: Other plan documents reference it. It serves as a record of the postMessage
bridge pattern. Deleting adds risk for no real benefit. We just remove it from build.sh.

## Current State (Before)

### ExtensionBridge (interface/extension-bridge.js) — 377 lines

```
Lines  1-14:   File header (dual transport documentation)
Lines 15-16:   IIFE wrapper
Lines 18-23:   Debug logging (references __aiBridgeReady)
Lines 25-29:   Core state: _available, _clientId, _pendingRequests, _availabilityCallbacks, _progressCallbacks
Lines 31-34:   Dual transport state: _inExtensionIframe, _iframeExtId, _useExternalTransport
Lines 36-38:   _generateId() helper
Line  40:      STREAMING_OPS constant
Lines 42-55:   _sendMessage() — routes to postMessage or external based on flag
Lines 57-76:   _sendMessagePostMessage() — postMessage transport
Lines 78-99:   _sendMessageExternal() — chrome.runtime.sendMessage transport
Lines 101-133: _sendMessageExternalStreaming() — chrome.runtime.connect Port transport
Lines 135-174: _handleResponse() — postMessage response listener
Lines 176-181: _notifyAvailability() — callback notification
Lines 183-190: _activateExternalTransport() — sets state and notifies
Lines 192-248: _initPostMessageTransport() — bridge.js event listeners + PING probe
Lines 250-252: Public API return object start (isAvailable: false)
Lines 253-300: init() — iframe detection + transport selection
Lines 302-316: onAvailabilityChange(), onProgress() registration
Lines 318-374: Public API methods (ping, extractCurrentPage, listTabs, etc.)
Lines 375-377: IIFE closure
```

### interface.html — Button and init code

```
Line  281: <button id="ext-extract-page" class="... ext-btn ext-btn-iframe-only" style="display:none;"> Page
Line  282: <button id="ext-refresh-page" class="... ext-btn" style="display:none;"> Refresh
Line  283: <button id="ext-multi-tab" class="... ext-btn" style="display:none;"> Multi-tab
...
Line 3696: ExtensionBridge.init();
Line 3699: var isInIframe = (top !== self);
Line 3701: ExtensionBridge.onAvailabilityChange(function(available) {
Line 3704:     $('.ext-btn').not('.ext-btn-iframe-only').show();
Line 3705:     if (isInIframe) {
Line 3706:         $('.ext-btn-iframe-only').show();
Line 3707:     }
Line 3713:     $('.ext-btn').hide();
```

### id-advertiser.js (extension-iframe/content_scripts/) — 27 lines

Sets `window.__aiIframeExtId` and dispatches `ai-iframe-extension-ready` event.

### build.sh — Line 20

```bash
EXTENSION_DIRS=("extension" "extension-headless" "extension-iframe")
```

### Consumer files (NO changes needed — confirmed)

- `interface/page-context-manager.js` — uses: `isAvailable`, `onProgress`, `captureFullPageWithOcr`, `extractCurrentPage`
- `interface/tab-picker-manager.js` — uses: `isAvailable`, `listTabs`, `extractTab`
- `interface/script-manager.js` — uses: `isAvailable`, `executeScript`

All consumers use only the public API. Zero references to internal state, transport
type, postMessage, chrome.runtime, or iframe detection. **Zero consumer changes needed.**

## Implementation Plan

### Phase 1: Rename Identifiers (cosmetic, zero behavior change)

#### Task 1.1: Rename variables in id-advertiser.js

**Goal**: Replace iframe-specific names with generic names.

**File**: `extension-iframe/content_scripts/id-advertiser.js`

**Changes**:
- Line 5 (comment): `window.__aiIframeExtId` → `window.__aiExtId`
- Line 21: `'window.__aiIframeExtId = '` → `'window.__aiExtId = '`
- Line 22: `"ai-iframe-extension-ready"` → `"ai-extension-ready"`
- Update docstring to reflect it serves ALL matching pages, not just iframes

**New file content** (full replacement, 27 lines):

```javascript
/**
 * ID Advertiser Content Script for AI Assistant Extension
 *
 * Injected into main UI pages (localhost:5000, 127.0.0.1:5000, assist-chat.site)
 * to advertise the extension ID. The main UI reads window.__aiExtId to know
 * which extension to call via chrome.runtime.sendMessage().
 *
 * Uses script tag injection to set the property in the MAIN world (not the
 * content script's isolated world). Content script window properties are NOT
 * readable by page JavaScript — only injected script tags run in the main world.
 *
 * Runs at document_start on matching pages so it's available before
 * ExtensionBridge.init() runs at DOMContentLoaded.
 */
(function() {
    'use strict';
    var extId = chrome.runtime.id;

    // Inject into main world via script tag — content script's window is isolated
    var script = document.createElement('script');
    script.textContent = 'window.__aiExtId = ' + JSON.stringify(extId) + ';' +
        'document.dispatchEvent(new CustomEvent("ai-extension-ready",' +
        '{detail:{extensionId:' + JSON.stringify(extId) + '}}));';
    (document.head || document.documentElement).appendChild(script);
    script.remove();
})();
```

**Verification**: Load extension in Chrome, open localhost:5000, check console for
`window.__aiExtId` being set. Old `window.__aiIframeExtId` should be undefined.

#### Task 1.2: Rename references in extension-bridge.js (identifier rename only)

**Goal**: Update all references to match new names from Task 1.1. No logic changes yet.

**File**: `interface/extension-bridge.js`

**Changes** (find-and-replace):
- Line 262: `window.__aiIframeExtId` → `window.__aiExtId` (3 occurrences on lines 262, 263, 264)
- Line 270: `'ai-iframe-extension-ready'` → `'ai-extension-ready'`
- Lines 284, 285, 287: `window.__aiIframeExtId` → `window.__aiExtId`

**Verification**: `grep -n '__aiIframeExtId\|ai-iframe-extension-ready' interface/extension-bridge.js`
should return zero matches. `grep -n '__aiExtId\|ai-extension-ready'` should show 8 matches.

---

### Phase 2: Simplify ExtensionBridge (major refactor)

#### Task 2.1: Remove postMessage transport functions

**Goal**: Delete the three postMessage-specific functions.

**File**: `interface/extension-bridge.js`

**Remove** (3 blocks):
1. Lines 57-76: `_sendMessagePostMessage()` function — postMessage sender
2. Lines 135-174: `_handleResponse()` function — postMessage response listener
3. Lines 192-248: `_initPostMessageTransport()` function — bridge.js setup + PING probe

**Why safe to remove**:
- `_sendMessagePostMessage` is only called from `_sendMessage()` line 54
- `_handleResponse` is only registered as listener inside `_initPostMessageTransport()` line 194
- `_initPostMessageTransport` is only called from `init()` lines 290 and 298
- All three call sites are updated in Tasks 2.2 and 2.3

#### Task 2.2: Simplify _sendMessage() dispatcher

**Goal**: Remove the transport branching — always use external transport.

**File**: `interface/extension-bridge.js`

**Current** (lines 42-55):
```javascript
function _sendMessage(type, payload, timeoutMs) {
    console.log(P, '_sendMessage:', type, '_available:', _available, 'external:', _useExternalTransport);
    if (!_available) return Promise.reject(new Error('Extension not available'));
    timeoutMs = timeoutMs || 30000;
    var requestId = _generateId();

    if (_useExternalTransport) {
        if (STREAMING_OPS.indexOf(type) >= 0) {
            return _sendMessageExternalStreaming(type, payload, requestId, timeoutMs);
        }
        return _sendMessageExternal(type, payload, requestId, timeoutMs);
    }
    return _sendMessagePostMessage(type, payload, requestId, timeoutMs);
}
```

**New**:
```javascript
function _sendMessage(type, payload, timeoutMs) {
    console.log(P, '_sendMessage:', type, '_available:', _available);
    if (!_available) return Promise.reject(new Error('Extension not available'));
    timeoutMs = timeoutMs || 30000;
    var requestId = _generateId();

    if (STREAMING_OPS.indexOf(type) >= 0) {
        return _sendMessageExternalStreaming(type, payload, requestId, timeoutMs);
    }
    return _sendMessageExternal(type, payload, requestId, timeoutMs);
}
```

**What changed**: Removed `_useExternalTransport` check and postMessage fallback.

#### Task 2.3: Remove unused variables

**Goal**: Clean up variables that only existed for postMessage transport.

**File**: `interface/extension-bridge.js`

**Remove or simplify**:
- Line 23: `console.log(P, 'window.__aiBridgeReady at load time:', window.__aiBridgeReady);` — DELETE (headless-only)
- Line 26: `var _clientId = ...` — DELETE (only used by _sendMessagePostMessage)
- Line 27: `var _pendingRequests = {};` — DELETE (only used by _sendMessagePostMessage and _handleResponse)
- Line 32: `var _inExtensionIframe = false;` — DELETE (set but never read for logic, Oracle confirmed)
- Line 34: `var _useExternalTransport = false;` — DELETE (always true now, branching removed)

**Keep**:
- Line 25: `var _available = false;` — still needed
- Line 28: `var _availabilityCallbacks = [];` — still needed
- Line 29: `var _progressCallbacks = [];` — still needed
- Line 33: `var _iframeExtId = null;` — still needed (rename to `_extId` for clarity)
- Line 40: `var STREAMING_OPS = [...]` — still needed

**Variable rename**: `_iframeExtId` → `_extId` (used on lines 33, 79, 84, 102, 104, 184).
Update `_activateExternalTransport()` and `_sendMessageExternal()` and
`_sendMessageExternalStreaming()` to use `_extId`.

#### Task 2.4: Simplify _activateExternalTransport()

**Goal**: Remove the `_useExternalTransport` flag set (no longer needed).

**File**: `interface/extension-bridge.js`

**Current** (lines 183-190):
```javascript
function _activateExternalTransport(extId) {
    _iframeExtId = extId;
    _useExternalTransport = true;
    _available = true;
    ExtensionBridge.isAvailable = true;
    console.log(P, 'Activated external transport, extId:', extId);
    _notifyAvailability(true);
}
```

**New**:
```javascript
function _activate(extId) {
    _extId = extId;
    _available = true;
    ExtensionBridge.isAvailable = true;
    console.log(P, 'Extension detected, extId:', extId);
    _notifyAvailability(true);
}
```

**What changed**: Renamed function, removed `_useExternalTransport = true`, renamed variable.

#### Task 2.5: Rewrite init() function

**Goal**: Remove iframe detection gate and postMessage fallback. Simplified detection flow.

**File**: `interface/extension-bridge.js`

**Current init()** (lines 253-300): Checks `isInIframe`, branches between external
transport and postMessage transport, has 2s fallback timeout for iframe, etc.

**New init()**:
```javascript
init: function() {
    console.log(P, '--- init() START ---');

    // id-advertiser.js runs at document_start on matching pages.
    // It injects window.__aiExtId before DOMContentLoaded.
    if (window.__aiExtId) {
        console.log(P, 'init: extension ID found immediately:', window.__aiExtId);
        _activate(window.__aiExtId);
        console.log(P, '--- init() END (immediate) ---');
        return;
    }

    // Fallback: listen for the CustomEvent (covers edge case where
    // content script injection was delayed, e.g., extension just installed
    // or service worker cold start).
    document.addEventListener('ai-extension-ready', function(e) {
        if (_available) return; // Already activated
        var extId = e.detail && e.detail.extensionId;
        console.log(P, '>>> EVENT ai-extension-ready, extId:', extId);
        if (extId) {
            _activate(extId);
        }
    });

    // Timeout: if neither flag nor event arrives within 3s,
    // extension is not installed or not matching this URL.
    setTimeout(function() {
        if (_available) return;
        console.log(P, 'init: extension not detected after 3s — not available');
        // _available stays false, buttons stay hidden. No error needed.
    }, 3000);

    console.log(P, '--- init() END (waiting for event or timeout) ---');
}
```

**What changed**:
- Removed `isInIframe` check (lines 257-258, 262, 280-295)
- Removed postMessage fallback (lines 290, 297-298)
- Removed `_inExtensionIframe` assignments (lines 275, 286)
- Simplified to: check flag → listen event → 3s timeout
- Event listener name: `ai-extension-ready` (renamed from `ai-iframe-extension-ready`)

**Oracle validation on race condition**: id-advertiser.js runs at `document_start` and
injects an inline `<script>` tag which executes synchronously in the main world.
`ExtensionBridge.init()` runs at `DOMContentLoaded`. The flag is guaranteed to be set
before init() runs in normal conditions. The event fallback is a safety net for edge
cases (extension just installed, service worker cold start). The 3s timeout covers the
case where the extension is simply not installed.

#### Task 2.6: Update file header documentation

**Goal**: Update the module docstring to reflect single-transport architecture.

**File**: `interface/extension-bridge.js`

**Current** (lines 1-14): Describes dual transport (postMessage + externally_connectable).

**New**:
```javascript
/**
 * ExtensionBridge - Promise-based client library for Chrome extension communication.
 *
 * Uses externally_connectable transport via chrome.runtime.sendMessage(extId) for
 * simple request-response operations, and chrome.runtime.connect(extId) for streaming
 * operations (full-page capture, OCR, multi-tab).
 *
 * Extension detection: id-advertiser.js content script sets window.__aiExtId at
 * document_start. ExtensionBridge.init() reads this at DOMContentLoaded.
 *
 * Usage:
 *   ExtensionBridge.init();
 *   ExtensionBridge.onAvailabilityChange(function(available) { ... });
 *   ExtensionBridge.extractCurrentPage().then(function(data) { ... });
 */
```

**Verification for all Phase 2 tasks**:
1. `grep -n 'postMessage\|PostMessage\|_handleResponse\|_initPostMessage\|_sendMessagePostMessage\|__aiBridgeReady\|_clientId\|_pendingRequests\|_inExtensionIframe\|_useExternalTransport' interface/extension-bridge.js` → should return 0 matches
2. `grep -n '_extId\|_activate\|ai-extension-ready\|__aiExtId' interface/extension-bridge.js` → should show the new identifiers
3. Open localhost:5000 in a regular browser tab with extension installed → ExtensionBridge should detect extension and show buttons
4. Open sidepanel iframe → same behavior

---

### Phase 3: Simplify Button Visibility

#### Task 3.1: Remove ext-btn-iframe-only class from HTML button

**Goal**: The "Page" extract button should show in all contexts, not just iframe.

**File**: `interface/interface.html`

**Current** (line 281):
```html
<button id="ext-extract-page" class="btn btn-outline-info mr-2 btn-sm mb-1 ext-btn ext-btn-iframe-only" style="display:none;" title="Extract content from current page"><i class="fa fa-globe"></i> Page</button>
```

**New** (line 281):
```html
<button id="ext-extract-page" class="btn btn-outline-info mr-2 btn-sm mb-1 ext-btn" style="display:none;" title="Extract content from current page"><i class="fa fa-globe"></i> Page</button>
```

**What changed**: Removed `ext-btn-iframe-only` from the class list.

#### Task 3.2: Simplify onAvailabilityChange callback

**Goal**: Remove iframe-specific button visibility branching.

**File**: `interface/interface.html`

**Current** (lines 3696-3716):
```javascript
ExtensionBridge.init();
console.log('[MainUI] ExtensionBridge.init() returned. Registering onAvailabilityChange...');
console.log('[MainUI] .ext-btn count at callback registration:', $('.ext-btn').length);
var isInIframe = (top !== self);
console.log('[MainUI] isInIframe:', isInIframe);
ExtensionBridge.onAvailabilityChange(function(available) {
    console.log('[MainUI] >>> onAvailabilityChange FIRED:', available, '| isInIframe:', isInIframe);
    if (available) {
        $('.ext-btn').not('.ext-btn-iframe-only').show();
        if (isInIframe) {
            $('.ext-btn-iframe-only').show();
        }
        $('#settings-workflows-section').show();
        $('#settings-scripts-section').show();
        WorkflowManager.init();
        ScriptManager.init();
    } else {
        $('.ext-btn').hide();
    }
});
console.log('[MainUI] All extension init done. Waiting for bridge detection...');
```

**New**:
```javascript
ExtensionBridge.init();
console.log('[MainUI] ExtensionBridge.init() returned. Registering onAvailabilityChange...');
console.log('[MainUI] .ext-btn count at callback registration:', $('.ext-btn').length);
ExtensionBridge.onAvailabilityChange(function(available) {
    console.log('[MainUI] >>> onAvailabilityChange FIRED:', available);
    if (available) {
        $('.ext-btn').show();
        $('#settings-workflows-section').show();
        $('#settings-scripts-section').show();
        WorkflowManager.init();
        ScriptManager.init();
    } else {
        $('.ext-btn').hide();
    }
});
console.log('[MainUI] All extension init done. Waiting for extension detection...');
```

**What changed**:
- Removed `var isInIframe = (top !== self);` (line 3699)
- Removed `console.log` of isInIframe (line 3700)
- Removed isInIframe from onAvailabilityChange log (line 3702)
- Replaced `$('.ext-btn').not('.ext-btn-iframe-only').show()` + iframe branch with just `$('.ext-btn').show()`
- Updated final log message

**Verification**: Install extension, open localhost:5000 in regular tab. All three buttons
(Page, Refresh, Multi-tab) should appear. Open sidepanel iframe. Same three buttons.
Without extension installed, all three should be hidden.

---

### Phase 4: Update Build Script

#### Task 4.1: Remove extension-headless from build.sh

**Goal**: Don't process extension-headless symlinks during production builds.

**File**: `build.sh`

**Current** (line 20):
```bash
EXTENSION_DIRS=("extension" "extension-headless" "extension-iframe")
```

**New**:
```bash
EXTENSION_DIRS=("extension" "extension-iframe")
```

**Verification**: Run `./build.sh` — should complete without errors and not mention
extension-headless.

---

### Phase 5: Deprecate Headless Extension

#### Task 5.1: Add deprecation notice

**Goal**: Mark extension-headless as deprecated so future developers know not to use it.

**File**: Create `extension-headless/DEPRECATED.md`

**Content**:
```markdown
# DEPRECATED

This extension has been deprecated as of 2026-02-20.

## Why

The main web UI now communicates with `extension-iframe`'s service worker via
`externally_connectable` in both regular browser tabs and sidepanel iframe context.
The postMessage bridge transport that this extension provided is no longer needed.

## What replaced it

- `extension-iframe/` now serves both contexts
- `interface/extension-bridge.js` uses only `externally_connectable` transport
- `extension-shared/operations-handler.js` is imported by extension-iframe's service worker

## See also

- Plan: `documentation/planning/plans/deprecate_headless_unify_extension.plan.md`
- Architecture: `documentation/features/extension/extension_design_overview.md`
```

#### Task 5.2: Remove headless symlinks (optional cleanup)

**Goal**: Remove the symlinks in extension-headless/ that point to extension-shared/.
These were only needed for development when headless was active.

**Files**: Remove symlinks:
- `extension-headless/background/operations-handler.js` → `../../extension-shared/operations-handler.js`
- `extension-headless/background/full-page-capture.js` → `../../extension-shared/full-page-capture.js`
- `extension-headless/content_scripts/extractor-core.js` → `../../extension-shared/extractor-core.js`
- `extension-headless/content_scripts/script-runner-core.js` → `../../extension-shared/script-runner-core.js`
- `extension-headless/sandbox/sandbox.html` → `../../extension-shared/sandbox.html`
- `extension-headless/sandbox/sandbox.js` → `../../extension-shared/sandbox.js`

**Note**: This is optional. The symlinks are harmless if left in place. Removing them
makes the deprecated state more visible (broken symlinks would fail if someone tries
to load the extension).

---

### Phase 6: Update Documentation

#### Task 6.1: Update extension_design_overview.md

**Goal**: Reflect the simplified single-extension architecture.

**File**: `documentation/features/extension/extension_design_overview.md`

**Changes** (lines 140-176):
- Remove extension-headless row from the Extensions table (line 145)
- Update extension-iframe description to note it serves both contexts
- Remove "Regular browser tab" postMessage flow from Communication Patterns (line 162)
- Update "Transport auto-detection" description (line 164) — no longer auto-detects, always uses externally_connectable
- Rename `window.__aiIframeExtId` to `window.__aiExtId` in Extension ID discovery (line 165)
- Remove headless service-worker row from Key Files table (line 172)
- Update extension-bridge.js description (line 175): "Single-transport client (externally_connectable)" instead of "Dual-transport"
- Update line count estimate for extension-bridge.js (was ~381, now ~180)

#### Task 6.2: Update extension-shared/README.md

**Goal**: Remove references to extension-headless as a consumer.

**File**: `extension-shared/README.md`

**Changes**:
- Remove mentions of extension-headless symlinks
- Update the "Used by" section to only list extension-iframe
- Note that extension-headless is deprecated

#### Task 6.3: Update operations-handler.js header comment

**Goal**: Remove the "extracted from extension-headless" origin note.

**File**: `extension-shared/operations-handler.js`

**Changes** (lines 4-5): Update comment to say this module is the canonical shared
operations handler, used by extension-iframe. Remove historical "extracted from
extension-headless" note.

**Verification for Phase 6**: Review all updated documentation for accuracy. Ensure
no references to headless as an active extension remain in feature documentation.

---

## Known Limitations

### URL restriction (externally_connectable)

`externally_connectable` only works for URL patterns hardcoded in the manifest:
- `http://localhost:5000/*`
- `http://127.0.0.1:5000/*`
- `https://assist-chat.site/*`

Custom server URLs (e.g., `localhost:8080`, custom domains) will NOT have extension
support. Previously, the headless extension supported any URL via content script injection.

**Mitigation**: This is acceptable for current deployments. If needed later, additional
URL patterns can be added to the manifest's `externally_connectable.matches` array
(e.g., `http://localhost:3000/*`, `http://localhost:8080/*`).

### No Firefox support

`externally_connectable` is Chrome-only. Firefox does not support it (bug 1319168).
If Firefox support is ever needed, a postMessage-based transport would need to be
re-implemented. This is unlikely given the extension uses Chrome-only APIs (sidePanel).

### onConnectExternal sender validation

The iframe extension's service-worker validates sender URLs for `onMessageExternal`
(line 62) but NOT for `onConnectExternal` (Port connections). This is a pre-existing
gap, not introduced by this change. A follow-up hardening task could add matching
validation to `onConnectExternal`.

---

## Files Modified Summary

### Code changes (4 files)

| File | Action | Lines Before | Lines After | Description |
|------|--------|-------------|-------------|-------------|
| `extension-iframe/content_scripts/id-advertiser.js` | Modify | 27 | 27 | Rename `__aiIframeExtId` → `__aiExtId`, event rename |
| `interface/extension-bridge.js` | Major refactor | 377 | ~180 | Remove postMessage transport, simplify init() |
| `interface/interface.html` | Modify | 3721 | ~3717 | Remove ext-btn-iframe-only, simplify visibility |
| `build.sh` | Modify | 107 | 107 | Remove extension-headless from EXTENSION_DIRS |

### New files (1 file)

| File | Description |
|------|-------------|
| `extension-headless/DEPRECATED.md` | Deprecation notice |

### Documentation updates (3 files)

| File | Description |
|------|-------------|
| `documentation/features/extension/extension_design_overview.md` | Remove headless, update architecture |
| `extension-shared/README.md` | Remove headless references |
| `extension-shared/operations-handler.js` | Update header comment |

### Consumer files — NO CHANGES

| File | Confirmed |
|------|-----------|
| `interface/page-context-manager.js` | ✅ Uses only public API |
| `interface/tab-picker-manager.js` | ✅ Uses only public API |
| `interface/script-manager.js` | ✅ Uses only public API |

### Older documentation (informational, no changes needed during implementation)

These plan files reference extension-headless but are historical records of past work.
They do not need updating as part of this plan:

- `documentation/planning/plans/extension_headless_bridge.plan.md`
- `documentation/planning/plans/headless_bridge_api_contract.md`
- `documentation/planning/plans/main_ui_extension_integration.plan.md`
- `documentation/planning/plans/implementation_todo_list.plan.md`
- `documentation/planning/plans/shared_operations_iframe_extraction.plan.md`

### Python backend "headless" references — NOT RELATED

40+ references to "headless" in Python files (agents/search_and_information_agents.py,
base.py, browser_agent.py, etc.) are headless BROWSER mode parameters for
Selenium/Playwright. They have nothing to do with extension-headless and should NOT
be modified.

---

## Verification Checklist

### After Phase 1 (rename)
- [ ] `window.__aiExtId` is set on localhost:5000 (check DevTools console)
- [ ] `window.__aiIframeExtId` is undefined
- [ ] ExtensionBridge still detects extension (rename was applied to both files)

### After Phase 2 (ExtensionBridge refactor)
- [ ] No `postMessage` or `PostMessage` in extension-bridge.js
- [ ] No `__aiBridgeReady` in extension-bridge.js
- [ ] Regular browser tab: buttons appear when extension installed
- [ ] Sidepanel iframe: buttons appear when extension installed
- [ ] No extension: buttons stay hidden after 3s timeout
- [ ] ExtensionBridge.ping() resolves successfully in both contexts
- [ ] ExtensionBridge.extractCurrentPage() works in regular tab
- [ ] ExtensionBridge.extractCurrentPage() works in iframe
- [ ] Streaming operations (captureFullPageWithOcr) work in both contexts

### After Phase 3 (button visibility)
- [ ] All three buttons visible in regular tab when extension available
- [ ] All three buttons visible in iframe when extension available
- [ ] No `ext-btn-iframe-only` class anywhere in interface.html
- [ ] WorkflowManager and ScriptManager still init when available

### After Phase 4 (build script)
- [ ] `./build.sh` completes without errors
- [ ] Output does not mention extension-headless

### After Phase 5 (deprecation)
- [ ] DEPRECATED.md exists in extension-headless/
- [ ] Extension-headless can be uninstalled from Chrome without breaking anything

### End-to-end tests
- [ ] Install ONLY extension-iframe. Open regular tab → buttons appear, extraction works
- [ ] Install ONLY extension-iframe. Open sidepanel → buttons appear, extraction works
- [ ] Uninstall extension-iframe. Open regular tab → buttons stay hidden
- [ ] Multi-tab capture works in both contexts
- [ ] Script execution works in both contexts
- [ ] OCR capture with streaming progress works in both contexts

---

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Custom URL users lose extension support | Low | Low | Document limitation; can add URL patterns later |
| id-advertiser delayed (cold start) | Very Low | Rare | 3s event fallback + timeout in init() |
| chrome.runtime undefined (no extension) | None | Expected | Timeout declares unavailable, buttons stay hidden |
| Breaking consumer code | None | None | Public API unchanged, verified zero internal refs |
| Headless extension users confused | Low | Low | DEPRECATED.md + documentation updates |

## Estimated Effort

- **Phase 1**: 15 min (mechanical rename)
- **Phase 2**: 1-2 hours (ExtensionBridge refactor + testing)
- **Phase 3**: 15 min (button visibility)
- **Phase 4**: 5 min (build.sh one-liner)
- **Phase 5**: 15 min (deprecation notice)
- **Phase 6**: 30 min (documentation)
- **Total**: 2-4 hours
