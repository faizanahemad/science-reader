---
name: Main UI Extension Integration
overview: >
  Add extension-powered controls to the main web UI (interface/) so it can leverage
  the headless bridge extension for page extraction, multi-tab capture, screenshot OCR,
  workflow management, and custom script management. Controls are hidden until the
  headless bridge extension is detected. No changes to existing chat, workspace, PKB,
  or other main UI features. The same code works whether the main UI is in a regular
  browser tab or inside the iframe sidepanel extension.
status: draft
created: 2026-02-19
revised: 2026-02-19
depends-on:
  - extension_headless_bridge.plan.md
depended-on-by:
  - extension_iframe_sidepanel.plan.md
---

# Main UI Extension Integration Plan

## Purpose & Intent

### Why This Exists

The main web UI (`interface/interface.html`) is the most feature-rich interface we have:
workspaces, PKB, artefacts, global docs, prompts, doubts, clarifications, code editor,
math rendering, multi-model tabs, etc. The current Chrome extension's sidepanel UI will
never reach this level of feature parity.

**This plan adds Chrome-extension-powered capabilities directly into the main UI.** When
the headless bridge extension is installed, the main UI gains buttons for:
- Extracting page content from the current or any open tab
- Multi-tab capture with a tab picker modal
- Managing workflows (multi-step prompt sequences)
- Managing custom scripts (Tampermonkey-like page scripts)

When the headless bridge extension is NOT installed, these controls are completely hidden.
The main UI works exactly as before — no broken buttons, no error states.

### How It Fits

```
Main UI in browser tab                  Main UI in iframe (sidepanel extension)
+----------------------------+          +----------------------------+
| interface/interface.html   |          | interface/interface.html   |
|                            |          | (loaded via iframe)        |
| [existing features]        |          | [existing features]        |
| + extension-bridge.js      |          | + extension-bridge.js      |
| + page-context-manager.js  |          | + page-context-manager.js  |
| + tab-picker-manager.js    |          | + tab-picker-manager.js    |
| + workflow-manager.js      |          | + workflow-manager.js      |
| + script-manager.js        |          | + script-manager.js        |
|                            |          |                            |
| All talk to headless       |          | All talk to headless       |
| bridge via postMessage     |          | bridge via postMessage     |
+----------------------------+          +----------------------------+
         |                                       |
         +------- same code, same behavior ------+
```

**The main UI code is identical in both contexts.** The bridge content script from the
headless extension is injected into any page at localhost:5000/* — whether that page is
in a regular tab or in an iframe inside the sidepanel extension.

### What This Plan Changes

- Adds 5 new JS modules to `interface/`
- Adds HTML for extension controls, page context panel, tab picker modal, workflow + script management sections
- Adds CSS for new UI components
- Small hook in `chat.js` send flow to include page context
- Zero backend changes

### What This Plan Does NOT Change

- No Flask backend changes (ext_* endpoints already exist)
- No changes to existing main UI features (chat, workspaces, PKB, artefacts, etc.)
- No changes to the current Chrome extension (`extension/`)
- No changes to the headless bridge extension (it's a dependency, not modified here)

## 0. Corrections and Code Sharing Reference (Added 2026-02-19)

### Code Sharing
This plan depends on the headless bridge extension. See `extension_headless_bridge.plan.md` section "0. Code Sharing Strategy" for the `extension-shared/` directory approach. This plan does NOT modify any extension code — it only adds new JS modules to `interface/`.

### Critical Corrections from Code Analysis

1. **Send function location**: The chat message send function is `ChatManager.sendMessage()` in `interface/common-chat.js` (line 2874), NOT in `interface/chat.js`. The file `chat.js` contains only settings modal handlers and initialization code (1,214 lines of settings persistence, model overrides, and UI event wiring).

2. **Exact main UI payload format** (from `common-chat.js` lines 2887-2921):
```javascript
var requestBody = {
    'messageText': messageText,
    'checkboxes': checkboxes,
    'links': links,
    'search': search
};
```
To add page context, we simply add `page_context` to this object.

3. **Exact extension payload format** (from `extension/shared/api.js` lines 493-525):
```javascript
page_context: {
    url: string,           // Page URL
    title: string,         // Page title
    content: string,       // Extracted text content
    screenshot: string,    // Base64 data URL (for canvas apps)
    isScreenshot: boolean, // True for canvas-only apps
    isMultiTab: boolean,   // True if from multiple tabs
    tabCount: number,      // Number of tabs captured
    isOcr: boolean,        // True if content from OCR
    sources: Array,        // [{url, title, content, timestamp}] for multi-tab
    mergeType: string,     // 'single' or 'multi'
    lastRefreshed: number  // Timestamp
}
```

4. **Backend processing** (from `Conversation.py:build_page_context_text()` line 9726): The backend already handles `page_context` from the extension. Content size limits: single page 64,000 chars, multi-tab 128,000 chars.

5. **No backend changes confirmed**: The `/send_message/{conversationId}` endpoint processes `page_context` as a top-level key in the POST body. Main UI just includes it in the same format.

## 1. Architecture

### 1.1 Extension Detection Flow

```
Page loads
    |
    v
extension-bridge.js sets up listener for CustomEvent("ai-assistant-bridge-ready")
    |
    +--- bridge.js (from headless extension) fires event --> detected!
    |    |
    |    v
    |    Show extension controls, enable page extraction, etc.
    |
    +--- No event after 2 seconds --> not installed
         |
         v
         Extension controls remain hidden. Main UI works normally.
```

### 1.2 Page Context Flow (Extract -> Display -> Chat)

```
User clicks "Extract Page" button
    |
    v
ExtensionBridge.extractCurrentPage()
    |
    v
postMessage -> bridge.js -> service worker -> inject extractor -> extract
    |
    v
Result returns: { title, url, content, contentType }
    |
    v
PageContextManager.setPageContext(result)
    |
    v
Page context panel shows: title, URL, content preview (collapsible)
    |
    v
User types message and clicks Send
    |
    v
chat.js send flow checks PageContextManager.getPageContextForMessage()
    |
    v
Page context prepended to message payload (same format current extension uses)
    |
    v
Backend receives message with page context, LLM responds about the page
```

### 1.3 Multi-Tab Capture Flow

```
User clicks "Multi-tab" button
    |
    v
ExtensionBridge.listTabs()  ->  returns [{ id, title, url, favIconUrl }, ...]
    |
    v
Tab picker modal opens with tab list, checkboxes, capture mode dropdowns
    |
    v
User selects tabs, chooses modes (Auto/DOM/OCR/Full OCR), clicks "Capture"
    |
    v
For each selected tab:
    |
    +-- DOM mode: ExtensionBridge.extractTab(tabId) -> text content
    +-- OCR mode: ExtensionBridge.captureScreenshot(tabId) -> screenshot
    |             then main UI calls POST /ext/ocr with screenshot -> OCR text
    +-- Full OCR: ExtensionBridge.captureFullPage(tabId) -> screenshots[]
    |             then main UI calls POST /ext/ocr for each -> combined OCR text
    +-- Auto:     Try DOM first, fall back to OCR if content too short
    |
    v
PageContextManager.setMultiTabContext(results) -> combined context in panel
    |
    v
Progress bar updates during capture. Cancel button aborts remaining tabs.
```

### 1.4 Workflow Management Flow

```
User opens Chat Settings modal -> Workflows tab
    |
    v
GET /ext/workflows/list  ->  display workflow list
    |
    +-- Create: POST /ext/workflows/create
    +-- Edit: PUT /ext/workflows/{id}
    +-- Delete: DELETE /ext/workflows/{id}
    +-- Select for conversation: store workflow_id in conversation settings
    |
    v
When sending message with workflow selected:
    chat payload includes workflow_id
    Backend applies workflow steps server-side
```

### 1.5 Script Management Flow

```
User opens Chat Settings modal -> Scripts tab
    |
    v
GET /ext/scripts/list  ->  display script list
    |
    +-- Create: POST /ext/scripts/create
    +-- Edit: PUT /ext/scripts/{id}
    +-- Delete: DELETE /ext/scripts/{id}
    +-- Generate via LLM: POST /ext/scripts/generate
    +-- Validate: POST /ext/scripts/validate
    +-- Test on page: ExtensionBridge.executeScript(scriptId, tabId) [needs headless ext]
    +-- Open in editor: ExtensionBridge.openEditor(scriptId) [opens extension editor tab]
```

## 2. New Files

| File | Lines (est.) | Purpose |
|------|-------------|---------|
| `interface/extension-bridge.js` | ~200 | Bridge client API — detects extension, sends/receives messages, Promise-based |
| `interface/page-context-manager.js` | ~250 | Page context panel — extract, display, clear, provide to chat send flow |
| `interface/tab-picker-manager.js` | ~300 | Tab picker modal — list tabs, capture modes, orchestrate capture, progress bar |
| `interface/workflow-manager.js` | ~250 | Workflow CRUD UI — list, create, edit, delete, select for conversation |
| `interface/script-manager.js` | ~300 | Script CRUD UI — list, create, edit, delete, generate, test, editor link |

## 3. Modified Files

| File | Changes |
|------|---------|
| `interface/interface.html` | Add extension control buttons, page context panel HTML, tab picker modal, workflow/script sections in settings, new script tags |
| `interface/style.css` | Page context panel styles, tab picker styles, compact adjustments |
| `interface/common-chat.js` | Hook in `ChatManager.sendMessage()` (line 2874) to include page context and workflow_id |

## 4. Detailed Tasks

### Task 1: Create extension-bridge.js

**File**: `interface/extension-bridge.js` (~200 lines)

This is the main UI's client library for the headless bridge extension. It provides
a clean Promise-based API that the rest of the main UI code calls.

```javascript
/**
 * ExtensionBridge - Client API for the headless bridge extension.
 * 
 * Detects whether the headless bridge extension is installed by listening
 * for the "ai-assistant-bridge-ready" CustomEvent dispatched by bridge.js.
 * Provides Promise-based methods for all bridge operations.
 * 
 * Usage:
 *   ExtensionBridge.init();
 *   ExtensionBridge.onAvailabilityChange(function(available) { ... });
 *   ExtensionBridge.extractCurrentPage().then(function(result) { ... });
 */
var ExtensionBridge = (function() {
    var _available = false;
    var _clientId = generateUUID();
    var _pendingRequests = {};  // requestId -> { resolve, reject, timeout }
    var _availabilityCallbacks = [];
    var _progressCallbacks = [];
    
    return {
        isAvailable: false,
        
        // Initialize — call on page load
        init: function() { /* listen for bridge-ready event, set up message listener */ },
        
        // Availability
        onAvailabilityChange: function(cb) { /* register callback */ },
        
        // Operations (all return Promises)
        ping: function() { /* PING */ },
        extractCurrentPage: function() { /* EXTRACT_CURRENT_PAGE */ },
        extractTab: function(tabId) { /* EXTRACT_TAB */ },
        listTabs: function() { /* LIST_TABS */ },
        captureScreenshot: function(tabId) { /* CAPTURE_SCREENSHOT */ },
        captureFullPage: function(tabId, options) { /* CAPTURE_FULL_PAGE */ },
        captureMultiTab: function(tabConfigs) { /* CAPTURE_MULTI_TAB */ },
        executeScript: function(scriptId, tabId) { /* EXECUTE_SCRIPT */ },
        getTabInfo: function() { /* GET_TAB_INFO */ },
        
        // Progress events
        onProgress: function(cb) { /* register progress callback */ }
    };
})();
```

**Key implementation details**:
- Uses `var` (matches existing interface/ code style)
- IIFE pattern (matches other interface/ modules like ConversationManager, WorkspaceManager)
- `_sendMessage(type, payload)` internal method generates requestId, posts message, returns Promise
- Listens for `window` message events with `direction: "ext-to-page"` and matching channel
- Routes responses to pending Promises by `requestId`
- Default timeout: 30s, configurable per operation (120s for multi-tab capture)
- On timeout: reject Promise with "Extension not responding" error

### Task 2: Create page-context-manager.js

**File**: `interface/page-context-manager.js` (~250 lines)

Manages the page context panel and provides context to the chat send flow.

```javascript
/**
 * PageContextManager - Manages page content extraction and display.
 *
 * Provides a collapsible panel showing extracted page content (title, URL,
 * preview text). Integrates with the chat send flow to include page context
 * in messages. Works with both single-page and multi-tab extraction.
 */
var PageContextManager = (function() {
    var _contexts = [];  // Array of { title, url, content, contentType, tabId }
    var _panelVisible = false;
    
    return {
        // Extraction
        extractCurrentPage: function() { /* calls ExtensionBridge, updates panel */ },
        extractFromTab: function(tabId) { /* calls ExtensionBridge, updates panel */ },
        captureAndOCR: function(tabId, mode) { /* capture screenshots, POST /ext/ocr, update panel */ },
        
        // Multi-tab
        setMultiTabContext: function(results) { /* set combined multi-tab context */ },
        
        // Panel UI
        showPanel: function() { /* show page context panel */ },
        hidePanel: function() { /* hide panel */ },
        togglePanel: function() { /* toggle expand/collapse */ },
        clearContext: function() { /* clear all context, hide panel */ },
        refreshContext: function() { /* re-extract from same tabs */ },
        
        // Chat integration
        getPageContextForMessage: function() {
            /* Returns formatted page context string to prepend to chat message.
               Returns null if no context set.
               Format matches what current extension sends:
               "Page Context from [title] ([url]):\n\n[content]" */
        },
        
        // State
        hasContext: function() { return _contexts.length > 0; },
        getContextCount: function() { return _contexts.length; }
    };
})();
```

**UI elements** (added to interface.html):
- `#page-context-panel` — collapsible panel above chat input area
- `#page-context-header` — title bar with "Page Context" label + tab count badge
- `#page-context-body` — content preview (max-height 150px, scrollable)
- `#page-context-refresh` — refresh button
- `#page-context-toggle` — expand/collapse button
- `#page-context-clear` — clear/close button

### Task 3: Create tab-picker-manager.js

**File**: `interface/tab-picker-manager.js` (~300 lines)

Manages the multi-tab capture modal.

```javascript
/**
 * TabPickerManager - Multi-tab capture modal.
 *
 * Opens a Bootstrap 4.6 modal listing all open tabs with checkboxes and
 * per-tab capture mode dropdowns. Orchestrates capture across selected tabs
 * with progress feedback and cancel support.
 */
var TabPickerManager = (function() {
    var _tabs = [];
    var _capturing = false;
    var _cancelled = false;
    
    return {
        open: function() { /* fetch tabs, populate modal, show */ },
        close: function() { /* hide modal, reset state */ },
        startCapture: function() { /* iterate selected tabs, capture per mode, update progress */ },
        cancelCapture: function() { /* set _cancelled = true, abort remaining */ },
        
        // Helpers
        selectAll: function() { /* check all tab checkboxes */ },
        deselectAll: function() { /* uncheck all */ }
    };
})();
```

**Modal HTML structure** (added to interface.html):
```html
<div class="modal fade" id="tab-picker-modal" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-lg">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title"><i class="fa fa-clone"></i> Multi-Tab Capture</h5>
                <button type="button" class="close" data-dismiss="modal">...</button>
            </div>
            <div class="modal-body">
                <div class="alert alert-warning" id="tab-picker-warning" style="display:none;">
                    <i class="fa fa-exclamation-triangle"></i> 
                    Do not switch tabs during capture. Tabs will briefly activate for screenshots.
                </div>
                <div class="d-flex justify-content-between mb-2">
                    <div>
                        <button class="btn btn-sm btn-outline-secondary" id="tab-select-all">Select All</button>
                        <button class="btn btn-sm btn-outline-secondary" id="tab-deselect-all">Deselect All</button>
                    </div>
                </div>
                <div id="tab-picker-list">
                    <!-- Dynamically populated tab rows -->
                </div>
                <div class="progress mt-3" id="tab-picker-progress" style="display:none;">
                    <div class="progress-bar" role="progressbar" style="width: 0%"></div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-danger" id="tab-picker-cancel" style="display:none;">Cancel</button>
                <button class="btn btn-secondary" data-dismiss="modal">Close</button>
                <button class="btn btn-primary" id="tab-picker-capture">Capture Selected</button>
            </div>
        </div>
    </div>
</div>
```

**Tab row template**:
```html
<div class="tab-picker-item d-flex align-items-center py-2 border-bottom">
    <input type="checkbox" class="mr-2 tab-checkbox" data-tab-id="...">
    <img src="favicon-url" class="mr-2" style="width:16px;height:16px;">
    <div class="flex-grow-1 text-truncate">
        <strong class="tab-title">Tab Title</strong>
        <small class="text-muted d-block text-truncate">https://example.com/...</small>
    </div>
    <select class="form-control form-control-sm ml-2" style="width:100px;">
        <option value="auto">Auto</option>
        <option value="dom">DOM</option>
        <option value="ocr">OCR</option>
        <option value="full-ocr">Full OCR</option>
    </select>
</div>
```

### Task 4: Create workflow-manager.js

**File**: `interface/workflow-manager.js` (~250 lines)

CRUD UI for workflows. Integrated into the chat settings modal.

```javascript
/**
 * WorkflowManager - Workflow CRUD and selection.
 *
 * Workflows are multi-step prompt sequences stored on the backend.
 * This module provides list/create/edit/delete UI integrated into the
 * chat settings modal. Selected workflow is included in chat messages.
 *
 * API endpoints (all existing, no backend changes):
 *   GET    /ext/workflows/list
 *   POST   /ext/workflows/create
 *   PUT    /ext/workflows/{id}
 *   DELETE /ext/workflows/{id}
 */
var WorkflowManager = (function() {
    var _workflows = [];
    var _selectedWorkflowId = null;
    
    return {
        init: function() { /* fetch workflows on page load */ },
        loadWorkflows: function() { /* GET /ext/workflows/list */ },
        createWorkflow: function(name, description, steps) { /* POST */ },
        updateWorkflow: function(id, data) { /* PUT */ },
        deleteWorkflow: function(id) { /* DELETE with confirm */ },
        selectWorkflow: function(id) { /* set selected for current conversation */ },
        getSelectedWorkflowId: function() { return _selectedWorkflowId; },
        renderList: function() { /* render workflow list in settings panel */ },
        renderEditor: function(workflow) { /* render edit form with step management */ }
    };
})();
```

**Settings modal addition**: New tab/section "Workflows" inside `#chat-settings-modal`:
- Workflow list with name, step count, edit/delete buttons
- "New Workflow" button
- Workflow editor: name field, description field, sortable step list (title + prompt per step), add/remove step buttons
- Workflow selector dropdown for current conversation

### Task 5: Create script-manager.js

**File**: `interface/script-manager.js` (~300 lines)

CRUD UI for custom scripts. Integrated into chat settings modal.

```javascript
/**
 * ScriptManager - Custom script CRUD and execution.
 *
 * Custom scripts run on web pages via the aiAssistant API (DOM manipulation,
 * LLM calls, clipboard, storage). This module provides list/create/edit/delete
 * UI. Script execution and editor opening require the headless bridge extension.
 *
 * API endpoints (all existing, no backend changes):
 *   GET    /ext/scripts/list
 *   GET    /ext/scripts/{id}
 *   POST   /ext/scripts/create
 *   PUT    /ext/scripts/{id}
 *   DELETE /ext/scripts/{id}
 *   POST   /ext/scripts/generate
 *   POST   /ext/scripts/validate
 */
var ScriptManager = (function() {
    var _scripts = [];
    
    return {
        init: function() { /* fetch scripts on page load */ },
        loadScripts: function() { /* GET /ext/scripts/list */ },
        createScript: function(data) { /* POST */ },
        updateScript: function(id, data) { /* PUT */ },
        deleteScript: function(id) { /* DELETE with confirm */ },
        generateScript: function(description, pageContext) { /* POST /ext/scripts/generate */ },
        validateScript: function(code) { /* POST /ext/scripts/validate */ },
        testOnPage: function(scriptId) {
            /* Requires headless bridge extension.
               ExtensionBridge.executeScript(scriptId, tabId) */
        },
        renderList: function() { /* render script list in settings panel */ },
        renderDetail: function(script) { /* render script detail view */ }
    };
})();
```

**Settings modal addition**: New tab/section "Scripts" inside `#chat-settings-modal`:
- Script list with name, URL pattern, enabled toggle, edit/delete/test buttons
- "New Script" button
- "Generate from description" button (uses LLM)
- Script detail view: name, description, URL patterns, code preview (read-only)
- "Test on Page" button (grayed out if headless extension not available)

### Task 6: Add extension controls to interface.html

**Location**: Near chat input area (around line 291), add a button group:

```html
<!-- Extension Controls (hidden until extension detected) -->
<div id="extension-controls" style="display: none;" class="mb-1">
    <div class="btn-group btn-group-sm" role="group">
        <button id="ext-extract-page" class="btn btn-outline-info" 
                title="Extract content from current page">
            <i class="fa fa-globe"></i> Page
        </button>
        <button id="ext-multi-tab" class="btn btn-outline-info" 
                title="Capture content from multiple tabs">
            <i class="fa fa-clone"></i> Multi-tab
        </button>
    </div>
</div>
```

These buttons are shown/hidden by `extension-bridge.js` based on bridge availability.

### Task 7: Add page context panel to interface.html

**Location**: Above `#chat-controls` div (before line 291):

```html
<!-- Page Context Panel (hidden until content extracted) -->
<div id="page-context-panel" style="display: none;">
    <div class="page-context-header d-flex justify-content-between align-items-center">
        <span>
            <i class="fa fa-globe"></i> <strong>Page Context</strong>
            <span id="page-context-count" class="badge badge-info ml-1" 
                  style="display:none;">1 tab</span>
        </span>
        <div>
            <button id="page-context-refresh" class="btn btn-sm btn-link p-0 mr-1" 
                    title="Refresh"><i class="fa fa-refresh"></i></button>
            <button id="page-context-toggle" class="btn btn-sm btn-link p-0 mr-1" 
                    title="Expand/Collapse"><i class="fa fa-chevron-down"></i></button>
            <button id="page-context-clear" class="btn btn-sm btn-link p-0 text-danger" 
                    title="Clear"><i class="fa fa-times"></i></button>
        </div>
    </div>
    <div id="page-context-body" style="display: none; max-height: 150px; overflow-y: auto;">
        <!-- Filled dynamically with extracted content preview -->
    </div>
</div>
```

### Task 8: Add tab picker modal to interface.html

Add after existing modals (around line 2900+). Full modal HTML as described in Task 3.

### Task 9: Add workflow + script sections to settings modal

**Location**: Inside `#chat-settings-modal` `.modal-body` (around line 1794).

Add two new collapsible sections (or tabs within the existing settings structure):

```html
<!-- Workflows Section -->
<div class="card mb-3" id="settings-workflows-section">
    <div class="card-header" data-toggle="collapse" data-target="#workflows-collapse">
        <h6 class="mb-0"><i class="fa fa-list-ol"></i> Workflows</h6>
    </div>
    <div id="workflows-collapse" class="collapse">
        <div class="card-body">
            <div id="workflow-list"><!-- populated by WorkflowManager --></div>
            <button class="btn btn-sm btn-primary mt-2" id="workflow-create-btn">
                <i class="fa fa-plus"></i> New Workflow
            </button>
        </div>
    </div>
</div>

<!-- Scripts Section -->
<div class="card mb-3" id="settings-scripts-section">
    <div class="card-header" data-toggle="collapse" data-target="#scripts-collapse">
        <h6 class="mb-0"><i class="fa fa-code"></i> Custom Scripts</h6>
    </div>
    <div id="scripts-collapse" class="collapse">
        <div class="card-body">
            <div id="script-list"><!-- populated by ScriptManager --></div>
            <button class="btn btn-sm btn-primary mt-2" id="script-create-btn">
                <i class="fa fa-plus"></i> New Script
            </button>
            <button class="btn btn-sm btn-outline-secondary mt-2 ml-1" id="script-generate-btn">
                <i class="fa fa-magic"></i> Generate with LLM
            </button>
        </div>
    </div>
</div>
```

### Task 10: Add CSS for new components

**File**: `interface/style.css` (append)

```css
/* ============================================
   Extension Controls & Page Context Panel
   ============================================ */

#extension-controls {
    padding: 2px 0;
}

.page-context-header {
    padding: 6px 10px;
    background: #f0f7ff;
    border: 1px solid #bee5eb;
    border-radius: 4px 4px 0 0;
    font-size: 0.85rem;
}

.page-context-header .btn-link {
    color: #6c757d;
    font-size: 0.8rem;
}

#page-context-body {
    padding: 8px 10px;
    background: #f8f9fa;
    border: 1px solid #dee2e6;
    border-top: none;
    border-radius: 0 0 4px 4px;
    font-size: 0.8rem;
    font-family: monospace;
    white-space: pre-wrap;
    word-break: break-word;
}

/* Tab picker */
.tab-picker-item {
    padding: 8px 0;
}

.tab-picker-item img {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
}

.tab-picker-item .tab-title {
    font-size: 0.9rem;
}
```

### Task 11: Hook page context into common-chat.js send flow

**File**: `interface/common-chat.js` (MODIFY — small surgical change at line ~2891)

Find the `ChatManager.sendMessage()` method (line 2874) and add page context to the request body.
The current code at lines 2887-2921 builds `requestBody` with messageText, checkboxes, links, search.

Add after the request body construction (after `'search': search`):

```javascript
// Include page context from extension bridge if available
if (typeof PageContextManager !== 'undefined' && PageContextManager.hasContext()) {
    requestBody.page_context = PageContextManager.getPageContextForPayload();
}

// Include workflow_id if selected via extension
if (typeof WorkflowManager !== 'undefined') {
    var workflowId = WorkflowManager.getSelectedWorkflowId();
    if (workflowId) {
        requestBody.checkboxes = requestBody.checkboxes || {};
        requestBody.checkboxes.workflow_id = workflowId;
        requestBody.checkboxes.field = 'PromptWorkflowAgent';
    }
}
```

This is a ~10-line addition. The backend processes `page_context` identically whether it comes
from the extension or the main UI. Zero backend changes needed.

`PageContextManager.getPageContextForPayload()` must return the exact dict format the backend
expects: `{ url, title, content, isMultiTab, tabCount, isScreenshot, screenshot, isOcr, sources, mergeType, lastRefreshed }`

### Task 12: Add script tags to interface.html

Add at the bottom of interface.html, after existing script tags:

```html
<!-- Extension Bridge Integration -->
<script src="extension-bridge.js"></script>
<script src="page-context-manager.js"></script>
<script src="tab-picker-manager.js"></script>
<script src="workflow-manager.js"></script>
<script src="script-manager.js"></script>
```

And add initialization in the page load sequence:

```javascript
// In the existing $(document).ready() or page init:
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

## 5. Important Implementation Notes

### Page Context Format (VERIFIED)

The backend expects `page_context` as a top-level key in the POST body to `/send_message/{conversationId}`.
Format defined in `Conversation.py:build_page_context_text()` (line 9726):

```javascript
page_context: {
    url: "https://example.com",
    title: "Page Title",
    content: "Extracted page text...",
    isScreenshot: false,      // true for canvas-only apps (Google Docs)
    screenshot: null,         // base64 PNG data URL if isScreenshot
    isMultiTab: false,        // true if content from multiple tabs
    tabCount: 1,              // number of tabs captured
    isOcr: false,             // true if content came from OCR
    sources: [],              // [{url, title, content, timestamp}] for multi-tab
    mergeType: "single",      // "single" or "multi"
    lastRefreshed: 1708300000 // timestamp
}
```

Content size limits enforced by backend:
- Single page: 64,000 chars
- Multi-tab: 128,000 chars

For multi-tab, the `content` field is formatted as:
```
## Tab: {title}
URL: {url}

{content}

---

## Tab: {title2}
URL: {url2}
...
```

This format matches what the extension's sidepanel.js produces (lines 1672-1683).

### Workflow Integration

The backend already handles workflow_id in the chat endpoint. Check `endpoints/ext_workflows.py`
and the chat endpoint to confirm the exact payload field name and how workflows are applied.

### Script CRUD vs Execution

Script CRUD (create/edit/delete/generate) is pure backend API calls — works without the
headless extension. But "Test on Page" and "Open in Editor" require the headless extension
to be installed (they need Chrome APIs). These buttons should be grayed out when extension
is not available.

### No Compact Mode CSS in This Plan

This plan does NOT add compact/mobile CSS. The main UI is designed for full-width tabs.
The iframe sidepanel extension plan handles any viewport concerns separately.
If compact mode CSS is needed, it belongs in a separate task or in the iframe extension plan.

## 6. Testing Strategy

| Test | Steps | Expected |
|------|-------|----------|
| No extension installed | Open main UI without headless extension | Extension controls hidden. All existing features work. |
| Extension installed | Install headless extension, open main UI | Extension controls appear. PING succeeds. |
| Extract current page | Open another tab, click "Page" button | Page context panel shows extracted content |
| Extract Google Docs | Open Google Doc in another tab, extract | Google Docs content extracted correctly |
| Clear page context | Click X on page context panel | Panel disappears, context cleared |
| Send with page context | Extract page, type message, send | Backend receives page context, LLM responds about page |
| Multi-tab DOM capture | Select 2 tabs in DOM mode, capture | Both pages' content in page context panel |
| Multi-tab OCR capture | Select tab in OCR mode, capture | Screenshots taken, OCR text in panel |
| Capture cancel | Start multi-tab capture, click cancel | Remaining tabs skipped, partial results shown |
| Workflow CRUD | Create, edit, delete workflow | Persisted via API, list updates |
| Workflow selection | Select workflow, send message | Backend applies workflow steps |
| Script CRUD | Create, edit, delete script | Persisted via API, list updates |
| Script test on page | Click "Test on Page" | Script executes on target tab via bridge |
| Works in iframe | Load main UI in iframe extension's sidepanel | All controls work identically |

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Page context format mismatch with backend expectations | Verify exact format from current extension code before implementing |
| Workflow/script endpoints require auth | Main UI already has session cookie; ext_* endpoints use @auth_required which checks session |
| Bridge not detected when extension loads slowly | 2-second timeout with retry; also listen for late CustomEvent arrivals |
| Chat.js send function is complex, risky to modify | Minimal change: 3-4 lines to check and include page context. No refactoring. |
| Modal overflow at narrow width (if in iframe) | Not this plan's concern; iframe plan handles viewport issues |

## 8. Estimated Effort

| Task | Effort |
|------|--------|
| Task 1: extension-bridge.js | 3-4h |
| Task 2: page-context-manager.js | 3-4h |
| Task 3: tab-picker-manager.js | 4-5h |
| Task 4: workflow-manager.js | 3-4h |
| Task 5: script-manager.js | 4-5h |
| Tasks 6-9: HTML additions | 2-3h |
| Task 10: CSS | 1h |
| Task 11: chat.js hook | 1h |
| Task 12: Script tags + init | 0.5h |
| **Total** | **~22-28h (3-4 days)** |

## 9. Success Criteria

1. Extension controls hidden when headless bridge not installed
2. Controls appear within 2 seconds when headless bridge is installed
3. Page extraction works and content displays in collapsible panel
4. Multi-tab capture works with progress bar and cancel
5. Page context is included in chat messages and backend processes it correctly
6. Workflow CRUD works (create, edit, delete, select)
7. Script CRUD works (create, edit, delete, generate, test)
8. All features work identically in regular tab and iframe sidepanel contexts
9. Zero regressions in existing main UI features
