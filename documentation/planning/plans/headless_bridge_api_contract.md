# Headless Bridge API Contract

**Version**: 1  
**Status**: Active  
**Created**: 2026-02-19  

This document defines the **exact** message protocol between the main UI (or any page with the bridge content script) and the headless bridge Chrome extension. All three workstreams (headless bridge, main UI integration, iframe sidepanel) MUST implement against this contract.

## 1. Transport

- **Page → Bridge**: `window.postMessage()` (received by bridge.js content script in isolated world)
- **Bridge → Page**: `window.postMessage()` (from bridge.js back to page context)
- **Bridge → Service Worker**: `chrome.runtime.connect()` Port (persistent, survives SW sleep)
- **Detection**: `CustomEvent("ai-assistant-bridge-ready")` dispatched on `document` when bridge connects

## 2. Message Envelope

Every message through the bridge follows this exact schema:

### 2.1 Request (Page → Extension)

```javascript
{
    channel: "ai-assistant-bridge",       // Fixed namespace. MUST be exactly this string.
    version: 1,                           // Protocol version. Integer.
    direction: "page-to-ext",             // MUST be "page-to-ext" for requests.
    requestId: "<uuid-v4>",              // Unique per request. Used for response matching.
    clientId: "<uuid-v4>",               // Unique per page/iframe instance. For multiplexing.
    type: "<OPERATION_TYPE>",            // One of the operation types in Section 3.
    payload: { ... }                      // Operation-specific data. May be empty object {}.
}
```

### 2.2 Response (Extension → Page)

```javascript
{
    channel: "ai-assistant-bridge",       // Same fixed namespace.
    version: 1,
    direction: "ext-to-page",            // MUST be "ext-to-page" for responses.
    requestId: "<matching-request-id>",  // Matches the request's requestId.
    clientId: "<matching-client-id>",    // Matches the request's clientId.
    type: "RESPONSE",                    // Always "RESPONSE" for final results.
    success: true | false,               // Whether the operation succeeded.
    payload: { ... },                    // Operation-specific result (when success=true).
    error: {                             // Error details (when success=false).
        code: "<ERROR_CODE>",
        message: "<human-readable message>"
    }
}
```

### 2.3 Progress Event (Extension → Page, for long operations)

```javascript
{
    channel: "ai-assistant-bridge",
    version: 1,
    direction: "ext-to-page",
    requestId: "<matching-request-id>",
    clientId: "<matching-client-id>",
    type: "PROGRESS",                    // Distinguishes from final RESPONSE.
    payload: {
        step: 3,                         // Current step (1-indexed).
        total: 5,                        // Total steps.
        tabId: 42,                       // Tab being processed (if applicable).
        message: "Capturing tab 3 of 5..." // Human-readable status.
    }
}
```

### 2.4 Bridge Lifecycle Events (CustomEvents on `document`)

```javascript
// Bridge connected and ready
document.addEventListener("ai-assistant-bridge-ready", function(e) {
    // e.detail = { version: 1 }
});

// Bridge disconnected (SW sleep, extension disabled, etc.)
document.addEventListener("ai-assistant-bridge-disconnected", function(e) {
    // e.detail = { reason: "port-disconnect" | "extension-disabled" }
});
```

## 3. Operation Types

### 3.1 PING

Health check / extension detection.

**Request payload**: `{}`

**Response payload**:
```javascript
{
    alive: true,
    version: 1,
    extensionId: "<chrome-extension-id>"
}
```

**Timeout**: 5 seconds

---

### 3.2 LIST_TABS

Get all open tabs in the current window.

**Request payload**: `{}`

**Response payload**:
```javascript
{
    tabs: [
        {
            id: 123,                    // Chrome tab ID (integer)
            title: "Page Title",
            url: "https://example.com",
            favIconUrl: "https://...",   // May be empty string
            active: true,               // Whether this is the active tab
            windowId: 1,
            index: 0                    // Tab position in window
        },
        // ...more tabs
    ]
}
```

**Notes**: Filters out `chrome://`, `chrome-extension://`, and `about:` URLs. Filters out the main UI tab itself (based on localhost:5000 or production domain matching).

**Timeout**: 5 seconds

---

### 3.3 GET_TAB_INFO

Get info about the currently active non-main-UI tab.

**Request payload**: `{}`

**Response payload**:
```javascript
{
    id: 456,
    title: "Active Tab Title",
    url: "https://example.com/page",
    favIconUrl: "https://..."
}
```

**Timeout**: 5 seconds

---

### 3.4 EXTRACT_CURRENT_PAGE

Extract content from the active non-main-UI tab. The bridge determines which tab is "current" by finding the active tab that is NOT the main UI page.

**Request payload**: `{}`

**Response payload**:
```javascript
{
    tabId: 456,
    title: "Page Title",
    url: "https://example.com",
    content: "Extracted page text content...",
    contentType: "text",              // "text" | "html"
    extractionMethod: "site-specific" // "site-specific" | "generic" | "readability"
}
```

**Error codes**: `RESTRICTED_PAGE`, `NO_ACTIVE_TAB`, `EXTRACTION_FAILED`, `INJECTION_FAILED`

**Timeout**: 30 seconds

---

### 3.5 EXTRACT_TAB

Extract content from a specific tab by ID.

**Request payload**:
```javascript
{
    tabId: 456                        // Required. Chrome tab ID.
}
```

**Response payload**: Same as EXTRACT_CURRENT_PAGE.

**Error codes**: `RESTRICTED_PAGE`, `TAB_NOT_FOUND`, `EXTRACTION_FAILED`, `INJECTION_FAILED`

**Timeout**: 30 seconds

---

### 3.6 CAPTURE_SCREENSHOT

Capture a visible-area screenshot of a specific tab.

**Request payload**:
```javascript
{
    tabId: 456                        // Required. Tab will be briefly activated.
}
```

**Response payload**:
```javascript
{
    tabId: 456,
    dataUrl: "data:image/png;base64,...",  // Full base64 PNG data URL
    width: 1920,
    height: 1080
}
```

**Notes**: Tab must be briefly activated for `captureVisibleTab`. Callers should warn users not to switch tabs.

**Error codes**: `RESTRICTED_PAGE`, `TAB_NOT_FOUND`, `CAPTURE_FAILED`, `CAPTURE_IN_PROGRESS`

**Timeout**: 30 seconds

---

### 3.7 CAPTURE_FULL_PAGE

Scroll-capture entire page content (multiple screenshots stitched by caller if needed).

**Request payload**:
```javascript
{
    tabId: 456,                       // Required.
    options: {                        // Optional, defaults shown.
        minScreenshots: 5,
        scrollDelayMs: 200,
        useInnerScroll: true          // Auto-detect inner scroll containers
    }
}
```

**Response payload**:
```javascript
{
    tabId: 456,
    screenshots: [                    // Array of base64 PNG data URLs
        "data:image/png;base64,...",
        "data:image/png;base64,...",
        // ...
    ],
    pageTitle: "Page Title",
    pageUrl: "https://example.com",
    scrollType: "window" | "inner",   // Whether window or inner container was scrolled
    totalHeight: 5000,
    viewportHeight: 900
}
```

**Progress events**: Fires PROGRESS messages with step/total as each screenshot is captured.

**Error codes**: `RESTRICTED_PAGE`, `TAB_NOT_FOUND`, `CAPTURE_FAILED`, `CAPTURE_IN_PROGRESS`

**Timeout**: 120 seconds

---

### 3.8 CAPTURE_MULTI_TAB

Extract/capture from multiple tabs in sequence. Each tab can have a different capture mode.

**Request payload**:
```javascript
{
    tabs: [
        {
            tabId: 456,
            mode: "auto"              // "auto" | "dom" | "ocr" | "full-ocr"
        },
        {
            tabId: 789,
            mode: "dom"
        }
    ]
}
```

**Mode descriptions**:
- `auto`: Try DOM extraction first, fall back to OCR if content too short (<100 chars)
- `dom`: DOM text extraction only (fastest)
- `ocr`: Single viewport screenshot (caller sends to OCR endpoint)
- `full-ocr`: Full-page scroll capture (caller sends screenshots to OCR endpoint)

**Response payload**:
```javascript
{
    results: [
        {
            tabId: 456,
            title: "Page Title",
            url: "https://example.com",
            mode: "dom",              // Actual mode used (may differ from "auto")
            content: "Extracted text...",    // For dom/auto modes
            screenshots: null,              // null for dom mode
            error: null                     // null if successful
        },
        {
            tabId: 789,
            title: "Google Doc",
            url: "https://docs.google.com/...",
            mode: "ocr",
            content: null,                  // null for ocr modes
            screenshots: ["data:image/png;base64,..."],
            error: null
        }
    ],
    completedCount: 2,
    totalCount: 2
}
```

**Progress events**: Fires PROGRESS for each tab start/complete.

**Error codes**: `CAPTURE_IN_PROGRESS`, individual tab errors in `results[].error`

**Timeout**: 300 seconds

---

### 3.9 EXECUTE_SCRIPT

Execute a custom script on a target tab via the script runner.

**Request payload**:
```javascript
{
    tabId: 456,                       // Required. Target tab.
    code: "const handlers = {...}; window.__scriptHandlers = handlers;",  // Script code.
    action: "myAction"                // Optional. Specific action to invoke after injection.
}
```

**Response payload**:
```javascript
{
    tabId: 456,
    result: { ... },                  // Whatever the script action returned
    success: true
}
```

**Error codes**: `RESTRICTED_PAGE`, `TAB_NOT_FOUND`, `SCRIPT_ERROR`, `INJECTION_FAILED`, `ACTION_NOT_FOUND`

**Timeout**: 30 seconds

---

## 4. Error Codes Reference

| Code | Meaning |
|------|---------|
| `RESTRICTED_PAGE` | Cannot access chrome://, chrome-extension://, about: pages |
| `TAB_NOT_FOUND` | No tab with the given tabId exists |
| `NO_ACTIVE_TAB` | No non-main-UI active tab found |
| `EXTRACTION_FAILED` | Extractor injected but content extraction failed |
| `INJECTION_FAILED` | chrome.scripting.executeScript failed (CSP, permissions) |
| `CAPTURE_FAILED` | captureVisibleTab failed |
| `CAPTURE_IN_PROGRESS` | Single-flight lock — another capture is running |
| `SCRIPT_ERROR` | Custom script threw an error |
| `ACTION_NOT_FOUND` | Requested script action does not exist |
| `TIMEOUT` | Operation timed out |
| `PORT_DISCONNECTED` | Bridge port lost during operation |
| `UNKNOWN` | Unexpected error |

## 5. Validation Rules (bridge.js)

The bridge content script validates incoming page messages:

1. `event.source === window` — message from same window
2. `event.origin` is in allowed origins (`http://localhost:5000`, `https://assist-chat.site`)
3. `event.data.channel === "ai-assistant-bridge"` — correct namespace
4. `event.data.direction === "page-to-ext"` — correct direction
5. `event.data.requestId` is a non-empty string
6. `event.data.type` is a non-empty string
7. Frame check: `top === self` (regular tab) OR parent is `chrome-extension://` origin (iframe in sidepanel extension)

Messages failing any check are silently dropped.

## 6. Concurrency

- **Single-flight lock**: Only one capture/screenshot operation at a time. Concurrent requests receive `CAPTURE_IN_PROGRESS` error.
- **Multiplexing**: Multiple UI tabs/iframes can have active bridges. Responses are routed by `clientId` + `requestId`.
- **Port reconnect**: Bridge reconnects to SW with exponential backoff (100ms → 5s max) on port disconnect.

## 7. Main UI Page Context Format

When the main UI sends extracted content to the backend, it uses this exact format (matching existing extension payload from `extension/shared/api.js`):

```javascript
// POST /send_message/{conversationId}
{
    "messageText": "User message",
    "checkboxes": { ... },
    "page_context": {
        "url": "https://example.com",
        "title": "Page Title",
        "content": "Extracted text...",
        "screenshot": null,               // base64 data URL or null
        "isScreenshot": false,            // true for canvas-only apps
        "isMultiTab": false,              // true if from multiple tabs
        "tabCount": 1,
        "isOcr": false,                   // true if content from OCR
        "sources": [],                    // [{url, title, content, timestamp}] for multi-tab
        "mergeType": "single",            // "single" | "multi"
        "lastRefreshed": 1708300000       // Unix timestamp (ms)
    }
}
```

**Content size limits** (enforced by backend):
- Single page: 64,000 characters
- Multi-tab combined: 128,000 characters

**Multi-tab content format** (for the `content` field when `isMultiTab: true`):
```
## Tab: {title}
URL: {url}

{content}

---

## Tab: {title2}
URL: {url2}

{content2}

---
```

## 8. Implementor Checklist

### Headless Bridge Extension (extension-headless/)
- [ ] bridge.js: Implement validation rules (Section 5)
- [ ] bridge.js: Dispatch lifecycle CustomEvents (Section 2.4)
- [ ] bridge.js: Port reconnect with exponential backoff
- [ ] service-worker.js: Handle all 9 operation types (Section 3)
- [ ] service-worker.js: Single-flight capture lock (Section 6)
- [ ] service-worker.js: Progress events for long operations
- [ ] service-worker.js: Error codes from Section 4

### Main UI Integration (interface/)
- [ ] extension-bridge.js: Send requests matching Section 2.1
- [ ] extension-bridge.js: Parse responses matching Section 2.2
- [ ] extension-bridge.js: Handle PROGRESS events (Section 2.3)
- [ ] extension-bridge.js: Listen for lifecycle events (Section 2.4)
- [ ] extension-bridge.js: Timeout per operation type
- [ ] page-context-manager.js: Build page_context matching Section 7
- [ ] page-context-manager.js: Enforce content size limits

### Iframe Sidepanel Extension (extension-iframe/)
- [ ] No bridge code needed — bridge.js auto-injected by headless extension
- [ ] Verify CSP allows framing main UI URLs
- [ ] Verify bridge works inside iframe context
