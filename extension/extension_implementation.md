# Chrome Extension Implementation Documentation

**Version:** 1.4  
**Last Updated:** December 31, 2025  
**Purpose:** Technical reference for extension UI implementation, file structure, backend integration, and custom scripts system.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File Tree](#2-file-tree)
3. [Shared Utilities](#3-shared-utilities)
4. [Background Service Worker](#4-background-service-worker)
5. [Popup UI](#5-popup-ui)
6. [Sidepanel UI](#6-sidepanel-ui)
7. [Content Scripts](#7-content-scripts)
8. [Custom Scripts System](#8-custom-scripts-system)
9. [Backend Integration](#9-backend-integration)
10. [Data Flow Diagrams](#10-data-flow-diagrams)
11. [State Management](#11-state-management)
12. [Styling Architecture](#12-styling-architecture)
13. [Message Passing](#13-message-passing)
14. [Extension Lifecycle](#14-extension-lifecycle)

---

## 1. Architecture Overview

### 1.1 Component Hierarchy

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Chrome Extension                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Service Worker (Background)                │   │
│  │  - Context menu management                                    │   │
│  │  - Message coordination                                       │   │
│  │  - Tab management                                             │   │
│  └────────────────────────┬─────────────────────────────────────┘   │
│                           │                                          │
│         ┌─────────────────┼─────────────────┐                       │
│         │                 │                 │                        │
│         ▼                 ▼                 ▼                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐         │
│  │   Popup     │  │  Sidepanel  │  │  Content Scripts    │         │
│  │   (Login)   │  │   (Chat)    │  │  (Page Extraction)  │         │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘         │
│         │                │                     │                     │
│         └────────────────┼─────────────────────┘                    │
│                          │                                           │
│                   ┌──────┴──────┐                                   │
│                   │   Shared    │                                   │
│                   │  Utilities  │                                   │
│                   │ (API, Store)│                                   │
│                   └─────────────┘                                   │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           │ HTTPS API Calls
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    extension_server.py (Port 5001)                   │
│  - Authentication (JWT)                                              │
│  - Conversations CRUD                                                │
│  - LLM Chat (streaming)                                              │
│  - Prompts & Memories (read-only)                                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Separation of Concerns** | UI (extension) separate from logic (server) |
| **Stateless UI** | All state stored server-side or in chrome.storage |
| **Token-based Auth** | JWT tokens, no cookies |
| **Streaming First** | All LLM responses use streaming |
| **Progressive Enhancement** | Core features work, advanced features optional |

---

## 2. File Tree

```
extension/
├── manifest.json                    # Extension configuration
│
├── shared/                          # Shared utilities (imported by all)
│   ├── constants.js                 # Configuration values
│   ├── storage.js                   # Chrome storage wrapper
│   └── api.js                       # Backend API client
│
├── background/                      # Background processes
│   └── service-worker.js            # Context menu, messaging hub, script coordination
│
├── popup/                           # Extension popup (toolbar icon click)
│   ├── popup.html                   # Login and quick actions UI
│   ├── popup.js                     # Event handlers and logic
│   └── popup.css                    # Styling
│
├── sidepanel/                       # Main chat interface (full height)
│   ├── sidepanel.html               # Chat UI structure
│   ├── sidepanel.js                 # Chat logic, streaming, script creation
│   └── sidepanel.css                # Comprehensive styling
│
├── content_scripts/                 # Injected into web pages
│   ├── extractor.js                 # Page extraction, quick action modal
│   ├── modal.css                    # Modal styling
│   ├── script_runner.js             # Custom script execution engine
│   ├── script_ui.js                 # Floating toolbar, command palette
│   └── script_ui.css                # Script UI styles
│
├── editor/                          # Script editor UI
│   ├── editor.html                  # Editor UI structure
│   ├── editor.js                    # CodeMirror, action builder, save/test
│   └── editor.css                   # Editor styling
│
├── sandbox/                         # Sandboxed page for script execution (no unsafe-eval)
│   ├── sandbox.html                 # Sandbox host page (manifest "sandbox")
│   └── sandbox.js                   # Sandbox runtime + RPC bridge to content script
│
├── lib/                             # Third-party libraries
│   ├── marked.min.js                # Markdown parser
│   ├── highlight.min.js             # Syntax highlighter
│   └── highlight.min.css            # Syntax theme
│
├── assets/
│   ├── icons/                       # Extension icons (16, 32, 48, 128 px)
│   │   ├── icon16.png
│   │   ├── icon32.png
│   │   ├── icon48.png
│   │   └── icon128.png
│   └── styles/
│       └── common.css               # Shared CSS variables
│
├── tests/                           # Backend API tests
│   ├── test_extension_api.py
│   ├── run_integration_tests.py
│   └── run_tests.sh
│
├── EXTENSION_DESIGN.md              # High-level design document
├── extension_api.md                 # Backend API reference
├── reuse_or_build.md               # Analysis of code reuse
├── README.md                        # Quick start guide
├── extension_implementation.md      # This file
└── generate_icons.py                # Icon generation script
```

---

## 3. Shared Utilities

### 3.1 `shared/constants.js`

**Purpose:** Centralized configuration for the entire extension.

**Exports:**

| Export | Type | Description |
|--------|------|-------------|
| `API_BASE` | string | Backend URL (`http://localhost:5001`) |
| `MODELS` | array | Fallback LLM models (fetched from server at runtime) |
| `QUICK_ACTIONS` | array | Context menu actions (explain, summarize, etc) |
| `DEFAULT_SETTINGS` | object | Default user settings |
| `STORAGE_KEYS` | object | Chrome storage key names |
| `MESSAGE_TYPES` | object | Message type constants for runtime messaging |
| `UI` | object | UI dimension constants |
| `TIMEOUTS` | object | Timeout values for API calls |

**Usage:**
```javascript
import { API_BASE, MODELS, MESSAGE_TYPES } from '../shared/constants.js';
```

---

### 3.2 `shared/storage.js`

**Purpose:** Wrapper around `chrome.storage.local` with async/await interface.

**Exports:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `get(key)` | `async (string) → any` | Get value from storage |
| `set(key, value)` | `async (string, any) → void` | Set value in storage |
| `remove(key)` | `async (string) → void` | Remove key from storage |
| `clear()` | `async () → void` | Clear all storage |
| `getToken()` | `async () → string\|null` | Get auth token |
| `setToken(token)` | `async (string) → void` | Store auth token |
| `clearToken()` | `async () → void` | Remove auth token |
| `getUserInfo()` | `async () → object\|null` | Get stored user info |
| `setUserInfo(info)` | `async (object) → void` | Store user info |
| `clearUserInfo()` | `async () → void` | Remove user info |
| `getSettings()` | `async () → object` | Get settings (with defaults) |
| `setSettings(settings)` | `async (object) → void` | Update settings (merges) |
| `getCurrentConversation()` | `async () → string\|null` | Get active conversation ID |
| `setCurrentConversation(id)` | `async (string) → void` | Set active conversation |
| `getRecentConversations()` | `async () → array` | Get recent conversations list |
| `addRecentConversation(conv, max)` | `async (object, number) → void` | Add to recent list |
| `isAuthenticated()` | `async () → boolean` | Check if token exists |
| `clearAuth()` | `async () → void` | Clear all auth data |

**Usage:**
```javascript
import { Storage } from '../shared/storage.js';

const token = await Storage.getToken();
await Storage.setSettings({ historyLength: 20 });
```

---

### 3.3 `shared/api.js`

**Purpose:** API client for communicating with `extension_server.py`.

**Exports:**

| Export | Type | Description |
|--------|------|-------------|
| `AuthError` | class | Custom error for auth failures |
| `API` | object | API methods object |

**API Methods:**

| Category | Method | Signature | Description |
|----------|--------|-----------|-------------|
| **Core** | `call(endpoint, options)` | `async (string, object) → object` | Make authenticated API call |
| **Core** | `stream(endpoint, body, callbacks)` | `async (string, object, object) → void` | Streaming API call |
| **Auth** | `login(email, password)` | `async (string, string) → object` | Login, stores token |
| **Auth** | `logout()` | `async () → void` | Logout, clears token |
| **Auth** | `verifyAuth()` | `async () → object` | Verify token validity |
| **Prompts** | `getPrompts()` | `async () → object` | List all prompts |
| **Prompts** | `getPrompt(name)` | `async (string) → object` | Get prompt by name |
| **Memories** | `getMemories(params)` | `async (object) → object` | List memories |
| **Memories** | `searchMemories(query, k)` | `async (string, number) → object` | Search memories |
| **Memories** | `getPinnedMemories()` | `async () → object` | Get pinned memories |
| **Conversations** | `getConversations(params)` | `async (object) → object` | List conversations |
| **Conversations** | `createConversation(data)` | `async (object) → object` | Create conversation (auto-deletes temp) |
| **Conversations** | `getConversation(id)` | `async (string) → object` | Get conversation with messages |
| **Conversations** | `updateConversation(id, data)` | `async (string, object) → object` | Update conversation |
| **Conversations** | `deleteConversation(id)` | `async (string) → void` | Delete conversation |
| **Conversations** | `saveConversation(id)` | `async (string) → object` | Save conversation (mark non-temporary) |
| **Chat** | `sendMessage(convId, data)` | `async (string, object) → object` | Send message (non-streaming) |
| **Chat** | `sendMessageStreaming(convId, data, callbacks)` | `async (string, object, object) → void` | Send with streaming |
| **Chat** | `addMessage(convId, data)` | `async (string, object) → object` | Add message without LLM |
| **Chat** | `deleteMessage(convId, msgId)` | `async (string, string) → void` | Delete message |
| **Settings** | `getSettings()` | `async () → object` | Get server settings |
| **Settings** | `updateSettings(settings)` | `async (object) → object` | Update server settings |
| **Utility** | `getModels()` | `async () → object` | List available models |
| **Utility** | `healthCheck()` | `async () → object` | Server health check |

**Streaming Callbacks:**
```javascript
{
    onChunk: (chunk) => { ... },   // Called for each text chunk
    onDone: (data) => { ... },     // Called when complete
    onError: (error) => { ... }    // Called on error
}
```

**Usage:**
```javascript
import { API, AuthError } from '../shared/api.js';

// Login
await API.login('user@example.com', 'password');

// Create conversation and send message with streaming
const { conversation } = await API.createConversation({ title: 'Test' });
await API.sendMessageStreaming(conversation.conversation_id, 
    { message: 'Hello', model: 'google/gemini-2.5-flash' },
    {
        onChunk: (text) => console.log(text),
        onDone: () => console.log('Complete'),
        onError: (err) => console.error(err)
    }
);
```

---

## 4. Background Service Worker

### 4.1 `background/service-worker.js`

**Purpose:** Background process that runs independently, manages context menus, and coordinates messaging.

**Key Responsibilities:**
1. Create context menu items on extension install
2. Handle context menu clicks
3. Coordinate messages between popup, sidepanel, content scripts
4. Manage sidepanel open/close

**Event Listeners:**

| Event | Handler | Description |
|-------|---------|-------------|
| `chrome.runtime.onInstalled` | Creates context menu items | Runs once on install/update |
| `chrome.contextMenus.onClicked` | Routes to appropriate handler | When user clicks context menu |
| `chrome.runtime.onMessage` | Message router | Inter-component communication |
| `chrome.tabs.onActivated` | Tab change notification | When user switches tabs |
| `chrome.tabs.onUpdated` | Tab update notification | When tab content changes |

**Context Menu Items Created:**

| Menu ID | Parent | Title | Context |
|---------|--------|-------|---------|
| `ai-assistant-menu` | - | AI Assistant | selection |
| `ai-explain` | ai-assistant-menu | 💡 Explain | selection |
| `ai-summarize` | ai-assistant-menu | 📝 Summarize | selection |
| `ai-critique` | ai-assistant-menu | 🔍 Critique | selection |
| `ai-expand` | ai-assistant-menu | 📖 Expand | selection |
| `ai-eli5` | ai-assistant-menu | 🧒 ELI5 | selection |
| `ai-translate` | ai-assistant-menu | 🌐 Translate | selection |
| `ai-add-to-chat` | ai-assistant-menu | 💬 Add to Chat | selection |

**Message Handlers:**

| Message Type | Handler Function | Response |
|--------------|------------------|----------|
| `OPEN_SIDEPANEL` | `handleOpenSidepanel()` | `{ success: boolean }` |
| `EXTRACT_PAGE` | `handleExtractPage()` | `{ title, url, content }` |
| `GET_TAB_INFO` | `handleGetTabInfo()` | `{ tabId, url, title }` |
| `GET_ALL_TABS` | `handleGetAllTabs()` | `{ tabs: array }` |
| `CAPTURE_SCREENSHOT` | `handleCaptureScreenshot()` | `{ screenshot: dataURL }` |
| `AUTH_STATE_CHANGED` | `broadcastAuthState()` | `{ success: true }` |

**Internal Functions:**

| Function | Signature | Description |
|----------|-----------|-------------|
| `handleOpenSidepanel` | `(sender, sendResponse) → void` | Opens sidepanel for tab |
| `handleExtractPage` | `(message, sender, sendResponse) → void` | Forwards to content script |
| `handleGetTabInfo` | `(sendResponse) → void` | Gets active tab info |
| `handleGetAllTabs` | `(sendResponse) → void` | Gets all window tabs |
| `handleCaptureScreenshot` | `(sender, sendResponse) → void` | Captures visible area |
| `broadcastAuthState` | `(isAuthenticated) → void` | Notifies all components |

---

## 5. Popup UI

### 5.1 `popup/popup.html`

**Purpose:** Entry point UI when user clicks extension icon.

**View / IDs (compact):**

- **Top-level views**: `loading-view`, `login-view`, `main-view`, `settings-view`
- **Login**: `login-form` (form), `email` (input), `password` (input), `login-btn` (submit), `login-error` (error display)
- **Main actions**: `open-sidepanel` (open sidepanel), `summarize-page` (summarize current page), `ask-selection` (ask about selection)
- **Recents + user**: `recent-list` (recent conversations), `recent-empty` (empty state), `user-email` (logged-in email), `logout-btn` (logout)
- **Settings**: `settings-btn` (open settings), `back-to-main` (close settings), `default-model` (model select), `default-prompt` (prompt select), `history-length` (history slider), `history-length-value` (slider label), `auto-save` (toggle), `theme` (theme select), `save-settings` (save settings)

---

### 5.2 `popup/popup.js`

**Purpose:** Event handling and logic for popup UI.

**Imports:**
```javascript
import { API } from '../shared/api.js';
import { Storage } from '../shared/storage.js';
import { MODELS, MESSAGE_TYPES } from '../shared/constants.js';
```

**Functions:**

| Function | Signature | Description |
|----------|-----------|-------------|
| `showView(viewName)` | `(string) → void` | Switch between views |
| `initialize()` | `async () → void` | Entry point, checks auth |
| `showMainView()` | `async () → void` | Load and show main view |
| `loadRecentConversations()` | `async () → void` | Fetch and render recent |
| `handleLogin(e)` | `async (Event) → void` | Form submit handler |
| `loadSettings()` | `async () → void` | Populate settings dropdowns |
| `escapeHtml(text)` | `(string) → string` | Sanitize HTML |
| `formatTimeAgo(timestamp)` | `(string) → string` | Relative time display |

**Event Listeners:**

| Element | Event | Handler |
|---------|-------|---------|
| `loginForm` | submit | `handleLogin` |
| `openSidepanelBtn` | click | Opens sidepanel via message |
| `summarizePageBtn` | click | Opens sidepanel with summarize action |
| `askSelectionBtn` | click | Gets selection, opens sidepanel |
| `recentList` | click | Opens selected conversation |
| `logoutBtn` | click | Calls `API.logout()`, shows login |
| `settingsBtn` | click | Shows settings view |
| `backToMainBtn` | click | Shows main view |
| `historyLengthInput` | input | Updates value display |
| `saveSettingsBtn` | click | Saves settings |

---

### 5.3 `popup/popup.css`

**Purpose:** Styling for popup UI (320px width, dark theme).

**CSS Variables (compact):** `--bg-primary:#0d1117; --bg-secondary:#161b22; --bg-tertiary:#21262d; --bg-hover:#30363d; --text-primary:#f0f6fc; --text-secondary:#8b949e; --text-muted:#6e7681; --accent:#58a6ff; --accent-hover:#79b8ff; --success:#3fb950; --warning:#d29922; --error:#f85149; --border:#30363d; --popup-width:320px; --popup-max-height:500px;`

**Key Classes:**

| Class | Purpose |
|-------|---------|
| `.view` | View container with padding |
| `.hidden` | Display none |
| `.btn` | Base button styles |
| `.btn-primary` | Accent colored button |
| `.btn-secondary` | Subtle button |
| `.btn-text` | Text-only button |
| `.icon-btn` | Icon button (square) |
| `.form-group` | Form field wrapper |
| `.error-message` | Error display |
| `.recent-list` | Conversation list |
| `.setting-group` | Settings field wrapper |

---

## 6. Sidepanel UI

### 6.1 `sidepanel/sidepanel.html`

**Purpose:** Main chat interface, full-height sidepanel.

**View / IDs (compact):**

- **Top-level views**: `login-view`, `main-view`
- **Login**: `login-form` (form), `email` (input), `password` (input), `login-error` (error display)
- **Header + panels**: `toggle-sidebar` (toggle sidebar), `new-chat-btn` (new chat), `settings-btn` (open settings), `sidebar` (sidebar), `sidebar-overlay` (overlay), `close-sidebar` (close sidebar), `settings-panel` (settings), `close-settings` (close settings)
- **Conversation list**: `conversation-list` (list), `conversation-empty` (empty state), `sidebar-new-chat` (new chat shortcut)
- **Settings controls**: `model-select`, `prompt-select`, `history-length-slider`, `history-value`, `auto-include-page`, `settings-user-email`, `logout-btn`
- **Chat**: `page-context-bar` (attached page indicator), `page-context-title` (title), `remove-page-context` (detach), `chat-container` (scroll container), `welcome-screen`, `messages-container`, `streaming-indicator`
- **Input**: `attach-page-btn` (attach page), `multi-tab-btn` (multi-tab), `voice-btn` (voice placeholder), `message-input` (textarea), `send-btn` (send), `stop-btn-container`, `stop-btn`
- **Multi-tab modal**: `tab-modal` (modal), `tab-list` (tab list), `close-tab-modal` (close), `cancel-tab-modal` (cancel), `confirm-tab-modal` (confirm)

---

### 6.2 `sidepanel/sidepanel.js`

**Purpose:** Core chat logic, conversation management, streaming.

**Imports:**
```javascript
import { API, AuthError } from '../shared/api.js';
import { Storage } from '../shared/storage.js';
import { MODELS, MESSAGE_TYPES } from '../shared/constants.js';
```

**State Object:**
```javascript
const state = {
    currentConversation: null,    // Active conversation object
    conversations: [],            // All conversations list
    messages: [],                 // Current conversation messages
    isStreaming: false,           // Currently receiving response
    pageContext: null,            // Attached page content (single or combined multi-tab)
    multiTabContexts: [],         // Array of {tabId, url, title, content} for multi-tab
    selectedTabIds: [],           // Tab IDs currently selected in modal
    settings: {                   // User settings
        model: 'google/gemini-2.5-flash',
        promptName: 'Short',
        historyLength: 10,
        autoIncludePage: true     // Auto-include page content (default: true)
    },
    abortController: null,        // For cancelling requests
    availableModels: []           // Fetched from server at runtime
};
```

**Functions (compact):**

- **Initialization**: `initialize(): async ()→void` (entry point, checks auth); `initializeMainView(): async ()→void` (load conversations + settings); `showView(viewName): (string)→void` (switch login/main views); `setupEventListeners(): ()→void` (attach handlers)
- **Authentication**: `handleLogin(e): async (Event)→void` (login form); `handleLogout(): async ()→void` (logout)
- **Sidebar**: `toggleSidebar(open): (boolean)→void` (show/hide sidebar); `toggleSettings(open): (boolean)→void` (show/hide settings)
- **Settings**: `loadSettings(): async ()→void` (fetch models, populate settings); `saveSettings(): async ()→void` (save to storage + server)
- **Conversations**: `loadConversations(): async ()→void` (fetch list); `renderConversationList(): ()→void` (render list); `handleConversationClick(e): async (Event)→void` (delegated click handling); `selectConversation(id): async (string)→void` (load + display); `createNewConversation(): async ()→void` (create; deletes temp); `deleteConversation(id): async (string)→void` (delete); `saveConversation(id): async (string)→void` (mark non-temporary)
- **Messages**: `renderMessages(): ()→void` (render all); `renderMessage(msg): (object)→string` (render one); `addCopyButtons(): ()→void` (copy buttons for code blocks); `scrollToBottom(): ()→void` (scroll)
- **Input**: `handleInputChange(): ()→void` (resize + button state); `handleInputKeydown(e): (Event)→void` (Enter send, Shift+Enter newline); `updateSendButton(): ()→void` (enable/disable)
- **Send/Streaming**: `sendMessage(): async ()→void` (send w/ streaming); `stopStreaming(): ()→void` (cancel); `updateConversationInList(preview): (string)→void` (update preview/title)
- **Page Context**: `attachPageContent(): async ()→void` (attach current page); `removePageContext(): ()→void` (detach)
- **Multi-Tab**: `showTabModal(): async ()→void` (open selector); `handleTabSelection(): async ()→void` (extract + combine); `truncateUrl(url): (string)→string` (shorten for display); `updateTabSelectionCount(): ()→void` (confirm label); `updateMultiTabIndicator(): ()→void` (tooltip)
- **Quick Suggestions**: `handleQuickSuggestion(action): async (string)→void` (handle suggestion buttons)
- **Runtime**: `handleRuntimeMessage(msg, sender, respond): (object, object, function)→void` (incoming messages)
- **Utilities**: `escapeHtml(text): (string)→string`; `formatTime(timestamp): (string)→string`; `formatTimeAgo(timestamp): (string)→string`

**Event Listeners (compact):**

- `loginForm: submit → handleLogin`
- `toggleSidebarBtn: click → toggleSidebar(true)`; `closeSidebarBtn: click → toggleSidebar(false)`; `sidebarOverlay: click → toggleSidebar(false)`
- `sidebarNewChatBtn: click → createNewConversation`; `newChatBtn: click → createNewConversation`
- `settingsBtn: click → toggleSettings(true)`; `closeSettingsBtn: click → toggleSettings(false)`
- `logoutBtn: click → handleLogout`
- `modelSelect: change → update settings + save`; `promptSelect: change → update settings + save`; `historyLengthSlider: input → update settings + save`; `autoIncludePageCheckbox: change → update settings + save`
- `messageInput: input → handleInputChange`; `messageInput: keydown → handleInputKeydown`
- `sendBtn: click → sendMessage`; `stopBtn: click → stopStreaming`
- `attachPageBtn: click → attachPageContent`; `removePageContextBtn: click → removePageContext`
- `multiTabBtn: click → showTabModal`; `voiceBtn: click → placeholder alert`
- `suggestionBtns: click → handleQuickSuggestion`; `conversationList: click → handleConversationClick`
- `closeTabModalBtn: click → hide modal`; `cancelTabModalBtn: click → hide modal`; `confirmTabModalBtn: click → handleTabSelection`
- `chrome.runtime.onMessage: message → handleRuntimeMessage`

---

### 6.3 `sidepanel/sidepanel.css`

**Purpose:** Comprehensive styling for sidepanel (dark theme, electric cyan accent).

**CSS Variables (compact):** `--bg-primary:#0a0e14; --bg-secondary:#0d1219; --bg-tertiary:#151c25; --bg-elevated:#1a2332; --bg-hover:#1e2a3a; --text-primary:#e6edf3; --text-secondary:#9ca6b3; --text-muted:#6b7785; --accent:#00d4ff; --accent-hover:#33ddff; --accent-glow:rgba(0, 212, 255, 0.15); --accent-dim:rgba(0, 212, 255, 0.3); --user-bg:linear-gradient(135deg, #1e3a5f 0%, #1a2f4a 100%); --user-border:#2563eb; --assistant-bg:var(--bg-tertiary); --assistant-border:#374151; --header-height:52px; --input-area-height:120px; --sidebar-width:280px;`

**Key Classes (compact):** `.view` (full-height view), `.header` (fixed header), `.sidebar` (slide-in list), `.sidebar.open` (visible), `.sidebar-overlay` (dim overlay), `.settings-panel` (slide-in settings), `.settings-panel.open` (visible), `.main-content` (chat container), `.chat-container` (scroll area), `.welcome-screen` (empty state), `.messages-container` (message list), `.message` (wrapper), `.message.user` (right-aligned user), `.message.assistant` (left-aligned assistant), `.message-content` (body), `.streaming-indicator` (typing dots), `.input-area` (fixed input), `.input-wrapper` (textarea wrapper), `.action-btn` (input action buttons), `.send-btn` (send), `.page-context-bar` (attached page indicator), `.modal` (overlay), `.modal-content` (modal box), `.quick-suggestions` (welcome buttons), `.suggestion-btn` (suggestion button), `.code-block-header` (code header + copy)

**Animations (compact):** `fadeIn` (0.3s, message appearance), `bounce` (1.4s, typing dots), `spin` (1s, loading spinners)

---

## 7. Content Scripts

### 7.1 `content_scripts/extractor.js`

**Purpose:** Injected into web pages for content extraction and quick action modals.

**Immediately Invoked Function Expression (IIFE):**
```javascript
(function() {
    'use strict';
    if (window.__aiAssistantInjected) return;
    window.__aiAssistantInjected = true;
    // ... implementation
})();
```

**Functions (compact):**

- **Page extraction**: `extractPageContent(): ()→object` (extract readable content); `getSelectedText(): ()→object` (current selection)
- **Modal**: `injectModalStyles(): ()→void` (inject modal CSS); `showModal(title): (string)→void` (show loading modal); `updateModalContent(content): (string)→void` (update modal HTML); `closeModal(): ()→void` (remove modal); `copyModalContent(): ()→void` (copy); `continueInChat(): ()→void` (open sidepanel)
- **Quick actions**: `handleQuickAction(action, text): async (string, string)→void` (process action)

**Message Listener (compact):** `EXTRACT_PAGE → { title, url, content, meta, length }`; `GET_SELECTION → { text, hasSelection }`; `QUICK_ACTION → { success:true }` (calls `handleQuickAction`); `SHOW_MODAL → { success:true }`; `HIDE_MODAL → { success:true }`

**Content Extraction Logic:**
1. Check for user selection (>100 chars) - use that preferentially
2. Detect site and use site-specific extractor (Google Docs, Reddit, etc.)
3. For canvas-based apps, set `needsScreenshot: true` flag
4. Fall back to generic extraction:
   - Try selectors: `article`, `[role="main"]`, `main`, `.post-content`, etc.
   - Fall back to `document.body`
   - Clone and remove: `script`, `style`, `nav`, `header`, `footer`, `.sidebar`, etc.
   - Normalize whitespace
5. Limit to 100,000 characters

**Floating Button:**
- Appears at bottom-right of every page
- SVG icon with gradient background
- Click opens sidepanel via `chrome.runtime.sendMessage`
- Styled in `injectModalStyles()` function

---

### 7.2 `content_scripts/modal.css`

**Purpose:** Styling for quick action response modal (also embedded in extractor.js).

**Key Styles:**
- `.ai-assistant-modal` - Fixed centered modal
- `.ai-assistant-modal-overlay` - Dim background
- `.ai-assistant-modal-header` - Title and close button
- `.ai-assistant-modal-body` - Scrollable content
- `.ai-assistant-modal-footer` - Action buttons
- `.ai-assistant-loading` - Loading animation
- `.ai-assistant-loading-dots` - Bouncing dots

---

## 8. Custom Scripts System

### 8.1 Overview

The custom scripts system enables Tampermonkey-like functionality within the extension. Users can create scripts that:

- **Parse pages**: Extract structured content for chat context
- **Perform actions**: Execute functions on specific websites (copy, modify, etc.)
- **Per-page behavior**: Same script can expose different actions based on URL

**Two Creation Modes:**
1. **Chat-Driven**: LLM sees page structure and helps build scripts iteratively
2. **Direct Editor**: Editor UI (opened in a new tab) with code editor and action builder

### 8.2 File Structure

```
extension/
├── content_scripts/
│   ├── script_runner.js     # Script execution engine + aiAssistant API
│   ├── script_ui.js         # Floating toolbar + command palette
│   └── script_ui.css        # UI styles for scripts
│
└── editor/
    ├── editor.html          # Script editor UI
    ├── editor.js            # Editor logic + CodeMirror
    └── editor.css           # Editor styles
```

### 8.3 `content_scripts/script_runner.js`

**Purpose:** Execute user scripts in a sandboxed environment with the `aiAssistant` API.

**Key Components:**

| Component | Description |
|-----------|-------------|
| `loadedScripts` | Map of currently loaded scripts and handlers |
| `createAiAssistantAPI(scriptId)` | Creates isolated API for each script |
| `executeScript(script)` | Sends script code to sandbox page (no unsafe-eval) and registers handlers |
| `callHandler(scriptId, handlerName)` | Invokes a specific handler function |
| `getPageContext()` | Extracts rich page structure for LLM |

**aiAssistant API:**

```javascript
window.aiAssistant = {
    dom: {
        query(selector),           // Returns first match
        queryAll(selector),        // Returns array of matches
        exists(selector),          // Returns boolean
        count(selector),           // Returns number
        getText(selector),         // Get text content
        getHtml(selector),         // Get innerHTML
        getAttr(selector, name),   // Get attribute
        setAttr(selector, name, value), // Set attribute
        getValue(selector),        // Get input/select value
        waitFor(selector, timeout), // Wait for element (Promise)
        scrollIntoView(selector, behavior), // Scroll to element
        focus(selector),           // Focus element
        blur(selector),            // Blur element
        hide(selector),            // Hide element(s)
        show(selector),            // Show element(s)
        remove(selector),          // Remove element(s)
        addClass(selector, className), // Add class
        removeClass(selector, className), // Remove class
        toggleClass(selector, className, force?), // Toggle class
        setHtml(selector, html),   // Set innerHTML
        getHtml(selector),         // Get innerHTML
        click(selector),           // Click element
        setValue(selector, value), // Set value + dispatch input/change
        type(selector, text, opts), // Type with optional delay/clearFirst
    },
    clipboard: {
        copy(text),                // Copy text to clipboard
        copyHtml(html),            // Copy as rich text
    },
    llm: {
        ask(prompt),               // Ask LLM (Promise<string>)
        askStreaming(prompt, onChunk), // Streaming response
    },
    ui: {
        showToast(message, type),  // Show notification
        showModal(title, content), // Show modal dialog
        closeModal(),              // Close modal
    },
    storage: {
        get(key),                  // Get from script storage
        set(key, value),           // Save to script storage
        remove(key),               // Remove from storage
    },
};
```

**Script Format:**

```javascript
// User scripts must export handlers via window.__scriptHandlers
const handlers = {
    copyProblem() {
        const title = aiAssistant.dom.getText('h1');
        aiAssistant.clipboard.copy(title);
        aiAssistant.ui.showToast('Copied!', 'success');
    },
    
    async analyzePage() {
        const content = aiAssistant.dom.getText('article');
        const analysis = await aiAssistant.llm.ask('Summarize: ' + content);
        aiAssistant.ui.showModal('Analysis', analysis);
    }
};

window.__scriptHandlers = handlers;
```

**Message Handlers:**

| Message Type | Response |
|--------------|----------|
| `EXECUTE_SCRIPT_ACTION` | `{ success, result }` |
| `GET_LOADED_SCRIPTS` | `{ scripts: [...] }` |
| `TEST_SCRIPT` | `{ success }` or `{ error }` |
| `RELOAD_SCRIPTS` | `{ success: true }` |
| `GET_PAGE_CONTEXT` | `{ url, title, headings, forms, ... }` |

### 8.4 `content_scripts/script_ui.js`

**Purpose:** Floating toolbar and command palette for action discovery.

**Key Components:**

| Component | Description |
|-----------|-------------|
| `FloatingToolbar` | Draggable toolbar showing available actions |
| `CommandPalette` | Searchable action list (Ctrl+Shift+K) |
| `InjectedButtons` | Buttons injected into page DOM |

**Floating Toolbar Features:**
- Draggable positioning (persisted)
- Collapsible/expandable
- Shows actions from loaded scripts
- "Create New Script" button opens editor

**Command Palette Features:**
- Opens with `Ctrl+Shift+K`
- Fuzzy search across all actions
- Shows action source (script name)
- System commands: "Edit Scripts", "Create New Script"

**Action Exposure Types:**

| Type | Description |
|------|-------------|
| `floating` | Shown in floating toolbar |
| `inject` | Injected as button in page DOM |
| `command` | Only in command palette |
| `context_menu` | Right-click context menu |

### 8.5 `editor/editor.html` + `editor.js`

**Purpose:** Dedicated editor UI for creating/editing scripts (opened in a new tab by the service worker).

**Features:**
- CodeMirror editor with JavaScript syntax highlighting
- Action builder UI (add/remove/configure)
- URL pattern configuration with test
- Test button to run script on current page
- Save button to persist to backend
- "Ask AI" button to open sidepanel with context

**DOM Elements:**

| ID | Purpose |
|----|---------|
| `scriptName` | Script name input |
| `scriptDescription` | Description input |
| `scriptType` | Type select (functional/parsing) |
| `patternsList` | URL patterns list |
| `codeEditor` | CodeMirror container |
| `actionsList` | Actions list |
| `actionModal` | Modal for editing actions |
| `testModal` | Modal for test results |

**Key Functions:**

| Function | Description |
|----------|-------------|
| `loadScript(scriptId)` | Load existing script for editing |
| `saveScript()` | Save to backend API |
| `testScript()` | Execute on current page |
| `openAiAssistant()` | Open sidepanel with script context |
| `loadPendingScript(script)` | Load AI-generated script |
| `renderActions()` | Render actions list |
| `validateCode()` | Check for syntax errors |

### 8.6 Chat-Driven Script Creation

**Flow in Sidepanel:**

1. User types message with script intent (e.g., "create a script to copy...")
2. `detectScriptIntent()` matches against patterns
3. `handleScriptGeneration()` extracts page context
4. API call to `/ext/scripts/generate`
5. `renderScriptResponse()` shows code with buttons
6. User can Test, Save, or Edit in Editor

**Intent Detection Patterns:**

```javascript
const SCRIPT_INTENT_PATTERNS = [
    /create\s+(a\s+)?script/i,
    /make\s+(a\s+)?script/i,
    /build\s+(a\s+)?script/i,
    /write\s+(a\s+)?script/i,
    /generate\s+(a\s+)?script/i,
    /script\s+(to|that|for|which)/i,
    /userscript/i,
    /tampermonkey/i,
];
```

**Script Response UI:**

```
┌────────────────────────────────────────────┐
│ 🔧 LeetCode Helper                         │
│ Copies problem details to clipboard        │
│                                            │
│ [functional] [*://leetcode.com/*]          │
│                                            │
│ I created a script that extracts...        │
│                                            │
│ ┌──────────────────────────────────────┐   │
│ │ const handlers = {                    │   │
│ │   copyProblem() { ... }               │   │
│ │ };                                    │   │
│ └──────────────────────────────────────┘   │
│                                            │
│ Actions:                                   │
│ [📋] Copy Problem - floating               │
│                                            │
│ [💾 Save Script] [▶️ Test] [✏️ Edit]       │
└────────────────────────────────────────────┘
```

### 8.7 Database Schema

**CustomScripts Table:**

```sql
CREATE TABLE CustomScripts (
    script_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    script_type TEXT DEFAULT 'functional',  -- 'functional' | 'parsing'
    match_patterns TEXT NOT NULL,           -- JSON array
    match_type TEXT DEFAULT 'glob',         -- 'glob' | 'regex'
    code TEXT NOT NULL,
    actions TEXT,                           -- JSON array
    enabled INTEGER DEFAULT 1,
    version INTEGER DEFAULT 1,
    conversation_id TEXT,                   -- Links to creation chat
    created_with_llm INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ext_script_match_patterns ON CustomScripts(match_patterns);
CREATE INDEX idx_ext_script_script_type ON CustomScripts(script_type);
```

**Action Schema:**

```json
{
  "id": "action-xyz123",
  "name": "Copy Problem",
  "description": "Copy problem details to clipboard",
  "handler": "copyProblem",
  "icon": "clipboard",
  "exposure": "floating",
  "page_pattern": null,
  "inject_selector": null,
  "inject_position": null
}
```

### 8.8 Security Considerations

| Aspect | Implementation |
|--------|----------------|
| **Sandboxed Execution** | Scripts run in isolated scope with timeout |
| **Limited API** | Only `aiAssistant` methods exposed, no direct DOM access outside |
| **LLM Proxy** | LLM calls go through service worker, not direct |
| **Storage Isolation** | Each script has namespaced storage |
| **No Network Access** | Scripts cannot make fetch calls directly |
| **No Extension APIs** | No access to chrome.* APIs |

### 8.9 Known Limitations / Caveats

1. **SPA Navigation**: Scripts may need to re-inject on URL changes (MutationObserver used)
2. **Shadow DOM**: Cannot easily select inside shadow roots
3. **CSP Issues**: Some sites block injected scripts
4. **Page Reload**: Scripts re-execute on every page load
5. **Storage Limits**: chrome.storage.local has ~5MB limit
6. **LLM Latency**: `aiAssistant.llm.ask()` can be slow
7. **Injection Timing**: `document_idle` may miss early content

---

## 9. Backend Integration

### 9.1 API Endpoints Used

| Category | Endpoint | Method | Used By |
|----------|----------|--------|---------|
| **Auth** | `/ext/auth/login` | POST | popup.js, sidepanel.js |
| **Auth** | `/ext/auth/logout` | POST | popup.js, sidepanel.js |
| **Auth** | `/ext/auth/verify` | POST | popup.js, sidepanel.js |
| **Prompts** | `/ext/prompts` | GET | popup.js, sidepanel.js |
| **Prompts** | `/ext/prompts/<name>` | GET | (Available) |
| **Memories** | `/ext/memories` | GET | (Available) |
| **Memories** | `/ext/memories/search` | POST | (Available) |
| **Conversations** | `/ext/conversations` | GET | sidepanel.js |
| **Conversations** | `/ext/conversations` | POST | sidepanel.js (deletes temp) |
| **Conversations** | `/ext/conversations/<id>` | GET | sidepanel.js |
| **Conversations** | `/ext/conversations/<id>` | PUT | sidepanel.js |
| **Conversations** | `/ext/conversations/<id>` | DELETE | sidepanel.js |
| **Conversations** | `/ext/conversations/<id>/save` | POST | sidepanel.js |
| **Chat** | `/ext/chat/<id>` | POST | sidepanel.js |
| **Chat** | `/ext/chat/quick` | POST | extractor.js |
| **Settings** | `/ext/settings` | GET | popup.js |
| **Settings** | `/ext/settings` | PUT | popup.js, sidepanel.js |
| **Models** | `/ext/models` | GET | (Available) |
| **Health** | `/ext/health` | GET | (Available) |

### 9.2 Authentication Flow

**Compact flow:** User enters email/password → Extension calls `POST /ext/auth/login` → Server returns `{ token, email, name }` → Extension stores `Storage.setToken(token)` + `Storage.setUserInfo({...})` → UI shows authenticated view.

### 9.3 Streaming Response Flow

**Compact flow:** User sends message → Sidepanel calls `POST /ext/chat/<id>` with `{ message, stream:true }` → Server calls LLM → Server streams SSE chunks (`data: {"chunk": "..."}`) → Sidepanel appends chunks live → final SSE includes `data: {"done": true, "message_id": "..."}` → Sidepanel finalizes render.

### 9.4 Page Content Grounding

When page content is attached, the server injects it as a **separate user message** before the user's actual question. This ensures the LLM explicitly acknowledges and uses the page content.

**Flow (compact):**
- Input: user message (e.g., `"Summarize this page"`) + `page_context = { url, title, content }`
- Server injects **two** messages *before* the user message:
  - Message 1 (**user**): “I’m currently viewing this web page… URL, Title, Page Content (up to 64,000 chars; truncated with notice). Please use the above page content…”
  - Message 2 (**assistant**): “I’ve read the page content. I’ll use it to help answer your questions.”
- Then sends Message 3 (**user**): the original user message.

**Key Details:**
- Page content limit: **64,000 characters** (truncated with notice if exceeded)
- Content is injected as user message for better LLM grounding
- LLM acknowledges content before answering
- Works with all quick actions (summarize, explain, etc.)

---

## 10. Data Flow Diagrams

### 10.1 Login Flow

**Compact flow:** Popup/Sidepanel → `API.login(email, password)` → `POST /ext/auth/login` → Server verifies password + generates JWT → returns `{ token, email, name }` → `Storage.setToken(token)` + `Storage.setUserInfo({...})` → show authenticated UI.

### 10.2 Page Extraction Flow

**Compact flow:** User clicks “Include Page” → Sidepanel `attachPageContent()` → `chrome.runtime.sendMessage({ type: EXTRACT_PAGE })` → Service worker `handleExtractPage()` → `chrome.tabs.sendMessage(tabId,{ type: EXTRACT_PAGE })` → content script `extractPageContent()` → returns `{ title, url, content, meta, length }` → Sidepanel sets `state.pageContext` → shows page context bar.

### 10.3 Context Menu Quick Action Flow

**Compact flow:** User selects text + context menu “Explain” → service worker `chrome.contextMenus.onClicked` → `chrome.tabs.sendMessage(tabId,{ type: QUICK_ACTION, action:'explain', text })` → content script `handleQuickAction()` shows modal → calls `POST /ext/chat/quick` → server calls LLM → returns `{ response }` → content script `updateModalContent(response)`.

---

## 11. State Management

### 11.1 Chrome Storage

| Key | Type | Contents |
|-----|------|----------|
| `authToken` | string | JWT authentication token |
| `userInfo` | object | `{ email, name }` |
| `settings` | object | User preferences |
| `currentConversation` | string | Active conversation ID |
| `recentConversations` | array | Last 5 accessed conversations |

### 11.2 Sidepanel State

```javascript
const state = {
    currentConversation: object | null,  // Full conversation object
    conversations: array,                 // List of all conversations
    messages: array,                      // Current conversation messages
    isStreaming: boolean,                 // Response in progress
    pageContext: object | null,           // Attached page content
    settings: {
        model: string,                    // Default: 'google/gemini-2.5-flash'
        promptName: string,               // Default: 'Short'
        historyLength: number,            // Default: 10
        autoIncludePage: boolean          // Default: false
    },
    abortController: AbortController | null,
    availableModels: array                // Fetched from server via /ext/models
};
```

### 11.3 State Persistence

| State | Storage Location | Persistence |
|-------|------------------|-------------|
| Auth token | chrome.storage.local | Until logout |
| User info | chrome.storage.local | Until logout |
| Settings | chrome.storage.local + server | Permanent |
| Conversations | Server database | Permanent |
| Messages | Server database | Permanent |
| Current conversation | chrome.storage.local | Session |
| Page context | Sidepanel memory | Page session |
| Streaming state | Sidepanel memory | Request duration |

---

## 12. Styling Architecture

### 12.1 CSS File Organization

| File | Scope | Variables Defined |
|------|-------|-------------------|
| `popup/popup.css` | Popup only | Own set |
| `sidepanel/sidepanel.css` | Sidepanel only | Own set (similar) |
| `content_scripts/modal.css` | Page-injected modal | Inline in extractor.js |
| `assets/styles/common.css` | Shared reference | `--ai-*` prefixed |

### 12.2 Theme Colors

**Popup Theme (slightly lighter):**
- Background: `#0d1117` → `#161b22` → `#21262d`
- Accent: `#58a6ff` (Blue)

**Sidepanel Theme (darker):**
- Background: `#0a0e14` → `#0d1219` → `#151c25`
- Accent: `#00d4ff` (Cyan)

### 12.3 Responsive Considerations

| Breakpoint | Adjustment |
|------------|------------|
| Popup | Fixed 320px width |
| Sidepanel | Fills Chrome sidepanel width |
| Sidebar | Slides in/out, overlays |
| Settings | Slides from right |
| Modal | 90% width, max 500px |

---

## 13. Message Passing

### 13.1 Message Types

| Type | Direction | Data |
|------|-----------|------|
| `OPEN_SIDEPANEL` | Any → SW | none |
| `EXTRACT_PAGE` | Any → CS | `{ tabId? }` |
| `GET_SELECTION` | Any → CS | none |
| `CAPTURE_SCREENSHOT` | Any → SW | none |
| `GET_TAB_INFO` | Any → SW | none |
| `GET_ALL_TABS` | Any → SW | none |
| `EXTRACT_FROM_TAB` | Any → SW | `{ tabId }` → `{ tabId, url, title, content }` |
| `ADD_TO_CHAT` | SW → Sidepanel | `{ text, pageUrl, pageTitle }` |
| `QUICK_ACTION` | SW → CS | `{ action, text }` |
| `SHOW_MODAL` | SW → CS | `{ title, content? }` |
| `HIDE_MODAL` | Any → CS | none |
| `AUTH_STATE_CHANGED` | Any → All | `{ isAuthenticated }` |
| `TAB_CHANGED` | SW → Sidepanel | `{ tabId, url, title }` |
| `TAB_UPDATED` | SW → Sidepanel | `{ tabId, url, title }` |
| **Custom Scripts Messages** |
| `GET_SCRIPTS_FOR_URL` | SW → API | `{ url }` → `{ scripts: [...] }` |
| `EXECUTE_SCRIPT_ACTION` | Any → CS | `{ scriptId, handlerName }` → `{ success, result }` |
| `GET_LOADED_SCRIPTS` | Any → CS | none → `{ scripts: [...] }` |
| `TEST_SCRIPT` | Editor → CS | `{ code, actions }` → `{ success }` |
| `RELOAD_SCRIPTS` | Any → CS | none → `{ success: true }` |
| `GET_PAGE_CONTEXT` | Any → CS | none → `{ url, title, headings, forms, ... }` |
| `SCRIPTS_UPDATED` | Any → SW | none → notifies all tabs to reload |
| `OPEN_SCRIPT_EDITOR` | Any → SW | `{ script?, scriptId? }` → opens editor tab |
| `SCRIPT_LLM_REQUEST` | CS → SW | `{ prompt }` → `{ response }` |

### 13.2 Message Flow Example

```javascript
chrome.runtime.sendMessage({ type: MESSAGE_TYPES.OPEN_SIDEPANEL }); // open sidepanel
chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXTRACT_PAGE }, (res) => { /* { title,url,content,meta,length } */ }); // extract page
chrome.tabs.sendMessage(tabId, { type: MESSAGE_TYPES.EXTRACT_PAGE }); // SW forwards to CS
```

---

## 14. Extension Lifecycle

### 14.1 Installation

1. `chrome.runtime.onInstalled` fires in service worker
2. Context menus are created
3. Sidepanel behavior is configured

### 14.2 Popup Open

1. `popup.html` loads
2. `popup.js` runs `initialize()`
3. Check `Storage.isAuthenticated()`
4. If yes: `API.verifyAuth()` → show main or login
5. If no: show login

### 14.3 Sidepanel Open

1. `sidepanel.html` loads
2. `sidepanel.js` runs `initialize()`
3. Check `Storage.isAuthenticated()`
4. If yes: `initializeMainView()`:
   - Load user info
   - Load settings
   - Load conversations
   - Check for current conversation
5. If no: show login

### 14.4 User Session

**Compact flow:** Open extension → check token → if valid: show main; if invalid: show login → on successful login: store token → show main → use extension.

### 14.5 Message Flow on Tab Change

**Compact flow:** User switches tab → `chrome.tabs.onActivated` (SW) → SW emits `TAB_CHANGED` runtime message → Sidepanel `handleRuntimeMessage` → UI may update page context indicator.

---

## Appendix A: File Dependency Graph

```
manifest.json
    ├── background/service-worker.js
    │       └── imports: shared/constants.js
    │
    ├── popup/popup.html
    │       ├── popup/popup.css
    │       └── popup/popup.js
    │               └── imports: shared/api.js
    │                            shared/storage.js
    │                            shared/constants.js
    │
    ├── sidepanel/sidepanel.html
    │       ├── sidepanel/sidepanel.css
    │       ├── lib/highlight.min.css
    │       ├── lib/marked.min.js
    │       ├── lib/highlight.min.js
    │       └── sidepanel/sidepanel.js
    │               └── imports: shared/api.js
    │                            shared/storage.js
    │                            shared/constants.js
    │
    └── content_scripts/extractor.js
            └── (no imports, self-contained)

shared/api.js
    └── imports: shared/constants.js
                 shared/storage.js

shared/storage.js
    └── imports: shared/constants.js
```

---

## Appendix B: Quick Reference

### Adding a New API Method

1. Add endpoint to `extension_server.py`
2. Add method to `API` object in `shared/api.js`
3. Import and call from appropriate component

### Adding a New Message Type

1. Add to `MESSAGE_TYPES` in `shared/constants.js`
2. Add handler in `service-worker.js` switch statement
3. Add listener in appropriate component

### Adding a New Setting

1. Add to `DEFAULT_SETTINGS` in `shared/constants.js`
2. Add to `state.settings` in `sidepanel.js`
3. Add UI control in `sidepanel.html` settings panel
4. Add event listener in `sidepanel.js`
5. Include in `saveSettings()` call

### Adding a New Quick Action

1. Add to `QUICK_ACTIONS` in `shared/constants.js`
2. Context menu created automatically by service worker
3. Handler exists in `extractor.js` → `handleQuickAction()`

### Adding a New LLM Model

1. Add model ID to `AVAILABLE_MODELS` list in `extension_server.py`
2. Models are fetched dynamically at runtime via `GET /ext/models`
3. UI displays short name (part after `/` in model ID)
4. No frontend changes needed - models auto-populate from server

**Current Models (in `extension_server.py`):**
```python
AVAILABLE_MODELS = [
    "google/gemini-2.5-flash",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4.5",
    "openai/gpt-5.2",
    "google/gemini-3-pro-preview"
]
```

### Adding a New Custom Script API Method

To add a new method to the `aiAssistant` API:

1. Add method in `createAiAssistantAPI()` in `script_runner.js`
2. If it needs service worker proxy, add message handler in `service-worker.js`
3. Document in the API section of this file

### Modifying Script UI (Toolbar/Palette)

1. Toolbar: Edit `FloatingToolbar` class in `script_ui.js`
2. Palette: Edit `CommandPalette` class in `script_ui.js`
3. Styles: Update `script_ui.css`
4. New action types: Add handling in `handleActionClick()` and render logic

### Extending Script Editor

1. Add form fields in `editor.html`
2. Add handling logic in `editor.js`
3. Update CSS in `editor.css`
4. If new action properties: Update action schema in backend too

---

## Appendix C: Troubleshooting

| Issue | Check | Solution |
|-------|-------|----------|
| Extension not loading | Console errors in chrome://extensions | Fix JavaScript errors |
| API calls failing | Network tab, server logs | Check API_BASE, server running |
| Auth not working | Storage viewer, server logs | Check token, verify endpoint |
| Page extraction empty | Content script console | Check page CSP, selector matching |
| Streaming not working | Network tab | Check SSE format, CORS |
| Styles not applied | Elements inspector | Check CSS specificity |
| Messages not passing | Service worker console | Check message types match |
| **Custom Scripts Issues** |
| Script not loading | Check URL pattern matches | Use `window.__scriptRunner` to debug |
| Actions not showing | Check script is enabled | Verify `exposure` type is correct |
| Handler not found | Check handler name matches | Must match function name exactly |
| aiAssistant undefined | Script ran too early | Use `waitFor` or check timing |
| LLM calls failing | Check auth token | LLM proxied through service worker |
| Toolbar not showing | Check z-index conflicts | May be hidden by page CSS |
| Command palette stuck | Press Escape | Or click outside to close |
| Editor not opening | Check chrome://extensions errors | Verify service worker can create a tab and editor URL is valid |
| Test script fails | Check content script loaded | May need page refresh |

---

---

## Appendix D: Changelog

### Version 1.4 (December 30, 2024)

**Custom Scripts System (Tampermonkey-like) (compact):**
- **New files**: `content_scripts/script_runner.js` (script engine + `aiAssistant`), `content_scripts/script_ui.js` (toolbar + palette), `content_scripts/script_ui.css` (styles), `editor/editor.html|js|css` (editor UI), `sandbox/sandbox.html|js` (sandbox exec + RPC bridge).
- **Creation modes**: Chat-driven (LLM sees page structure, iterative refinement); Direct editor (tab UI with code editor + action builder + live test).
- **User-script API**: `aiAssistant.dom.*` (DOM query/modify + automation), `clipboard.*` (copy/copyHtml), `llm.*` (ask/stream), `ui.*` (toast/modal), `storage.*` (namespaced per-script).
- **Action exposure**: `floating` (toolbar), `inject` (page button), `command` (palette Ctrl+Shift+K), `context_menu` (right-click).
- **Backend endpoints**: `GET/POST /ext/scripts`, `GET /ext/scripts/for-url?url=...`, `POST /ext/scripts/generate`, `POST /ext/scripts/validate`.
- **DB schema**: `CustomScripts` extended with `actions`, `match_type`, `conversation_id`, `created_with_llm`; indexes on `match_patterns`, `script_type`.
- **New message types**: `GET_SCRIPTS_FOR_URL`, `EXECUTE_SCRIPT_ACTION`, `TEST_SCRIPT`, `GET_PAGE_CONTEXT`, `SCRIPTS_UPDATED`, `OPEN_SCRIPT_EDITOR`.
- **Security**: sandboxed execution + timeout; no direct network (LLM proxied via SW); per-script storage isolation; user scripts must use `aiAssistant.dom.*` (no direct DOM APIs).

---

### Version 1.3 (December 25, 2024)

**Multi-Tab Reading (compact):** Full multi-tab content extraction; “Multi-tab” opens tab selection modal with checkboxes; current tab auto-selected; restricted URLs (`chrome://`, `about://`) disabled; selected tab content combined with clear separators; backend updated to acknowledge multi-tab content explicitly. **State**: `multiTabContexts[]`, `selectedTabIds[]`. **Message**: `EXTRACT_FROM_TAB` (extract by tabId). **sidepanel.js**: `truncateUrl(url)`, `updateTabSelectionCount()`, `updateMultiTabIndicator()`. **service-worker.js**: `handleExtractFromTab()` (fallback injection). **UI**: active-state indicator, loading spinner, disabled restricted tabs, confirm text shows selected count.

---

### Version 1.2 (December 25, 2024)

**Auto-Include Page Content (compact):** `autoIncludePage` enabled by default; messages auto-attach page content if missing; works with screenshot fallback for canvas apps (Google Docs). **Temporary conversations & Save**: new conversations delete all temporary convs; Save button (💾) for temporary convs; saved convs (💬) not auto-deleted; new endpoint `POST /ext/conversations/<id>/save`; icons: 💭 temporary, 💬 saved. **UI**: removed auto-scroll; fixed duplicate code block headers; `.conv-actions` wrapper; save uses accent, delete uses error hover. **Screenshot fallback**: canvas apps (Google Docs/Sheets) capture screenshot; send base64 to LLM; LLM acknowledges screenshot. **Extraction**: site-specific extractors added for Google Docs, Gmail, Sheets, Twitter/X, Reddit, GitHub, YouTube, Wikipedia, Stack Overflow, LinkedIn, Medium/Substack, Notion, Quip; floating button bottom-right opens sidepanel; selection text prioritized over full extraction.

---

### Version 1.1 (December 25, 2024)

**Input handling (compact):** send on Enter; Shift+Enter newline (replaces Ctrl+Enter). **Models:** fetched dynamically via `GET /ext/models`; default `google/gemini-2.5-flash`; UI displays short names (after `/`); models added: gemini-2.5-flash, claude-sonnet-4.5, claude-opus-4.5, gpt-5.2, gemini-3-pro-preview. **Grounding:** page content limit 2,000→64,000 chars; injected as separate user message; LLM acknowledges before answering. **State:** `availableModels[]` added; `loadSettings()` fetches models from server.

---

*End of Extension Implementation Documentation*

