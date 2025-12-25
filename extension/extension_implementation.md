# Chrome Extension Implementation Documentation

**Version:** 1.3  
**Last Updated:** December 25, 2024  
**Purpose:** Technical reference for extension UI implementation, file structure, and backend integration.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File Tree](#2-file-tree)
3. [Shared Utilities](#3-shared-utilities)
4. [Background Service Worker](#4-background-service-worker)
5. [Popup UI](#5-popup-ui)
6. [Sidepanel UI](#6-sidepanel-ui)
7. [Content Scripts](#7-content-scripts)
8. [Backend Integration](#8-backend-integration)
9. [Data Flow Diagrams](#9-data-flow-diagrams)
10. [State Management](#10-state-management)
11. [Styling Architecture](#11-styling-architecture)
12. [Message Passing](#12-message-passing)
13. [Extension Lifecycle](#13-extension-lifecycle)

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
│   └── service-worker.js            # Context menu, messaging hub
│
├── popup/                           # Extension popup (toolbar icon click)
│   ├── popup.html                   # Login and quick actions UI
│   ├── popup.js                     # Event handlers and logic
│   └── popup.css                    # Styling
│
├── sidepanel/                       # Main chat interface (full height)
│   ├── sidepanel.html               # Chat UI structure
│   ├── sidepanel.js                 # Chat logic, streaming
│   └── sidepanel.css                # Comprehensive styling
│
├── content_scripts/                 # Injected into web pages
│   ├── extractor.js                 # Page extraction, quick action modal
│   └── modal.css                    # Modal styling
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

**View Structure:**

```
popup/popup.html
├── #loading-view          (Initial loading spinner)
├── #login-view            (When not authenticated)
│   ├── .login-header      (Logo + title)
│   ├── #login-form        (Email + password inputs)
│   └── .login-footer      (Web app link)
├── #main-view             (When authenticated)
│   ├── .main-header       (Title + settings button)
│   ├── .quick-actions     (Open sidepanel, summarize, ask)
│   ├── .recent-section    (Recent conversations list)
│   └── .main-footer       (User email + logout)
└── #settings-view         (Settings panel)
    ├── .settings-header   (Back button + title)
    ├── .settings-content  (Model, prompt, history, theme)
    └── #save-settings     (Save button)
```

**DOM Element IDs:**

| ID | Element | Purpose |
|----|---------|---------|
| `loading-view` | div | Initial loading state |
| `login-view` | div | Login form container |
| `main-view` | div | Authenticated main view |
| `settings-view` | div | Settings panel |
| `login-form` | form | Login form |
| `email` | input | Email field |
| `password` | input | Password field |
| `login-btn` | button | Login submit |
| `login-error` | div | Error message display |
| `open-sidepanel` | button | Open sidepanel action |
| `summarize-page` | button | Summarize current page |
| `ask-selection` | button | Ask about selection |
| `recent-list` | ul | Recent conversations |
| `recent-empty` | div | Empty state |
| `user-email` | span | Logged in user email |
| `logout-btn` | button | Logout action |
| `settings-btn` | button | Open settings |
| `back-to-main` | button | Back from settings |
| `default-model` | select | Model dropdown |
| `default-prompt` | select | Prompt dropdown |
| `history-length` | input | History slider |
| `history-length-value` | span | Slider value display |
| `auto-save` | checkbox | Auto-save toggle |
| `theme` | select | Theme dropdown |
| `save-settings` | button | Save settings |

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

**CSS Variables:**
```css
--bg-primary: #0d1117;
--bg-secondary: #161b22;
--bg-tertiary: #21262d;
--bg-hover: #30363d;
--text-primary: #f0f6fc;
--text-secondary: #8b949e;
--text-muted: #6e7681;
--accent: #58a6ff;
--accent-hover: #79b8ff;
--success: #3fb950;
--warning: #d29922;
--error: #f85149;
--border: #30363d;
--popup-width: 320px;
--popup-max-height: 500px;
```

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

**View Structure:**

```
sidepanel/sidepanel.html
├── #login-view                    (When not authenticated)
│   └── .login-container           (Centered login form)
│
└── #main-view                     (Main chat interface)
    ├── .header                    (Toggle, title, new chat, settings)
    ├── #sidebar                   (Conversation list - slidable)
    │   ├── .sidebar-header
    │   ├── #conversation-list
    │   └── #conversation-empty
    ├── #sidebar-overlay           (Click to close sidebar)
    ├── #settings-panel            (Settings - slidable from right)
    │   ├── .settings-header
    │   └── .settings-content
    └── .main-content
        ├── #page-context-bar      (Shows attached page)
        ├── #chat-container
        │   ├── #welcome-screen    (Initial state)
        │   │   └── .quick-suggestions
        │   ├── #messages-container
        │   └── #streaming-indicator
        └── .input-area
            ├── .input-actions     (Attach, multi-tab, voice)
            ├── .input-wrapper     (Textarea + send button)
            └── #stop-btn-container

#tab-modal                         (Multi-tab selection modal)
```

**DOM Element IDs:**

| ID | Element | Purpose |
|----|---------|---------|
| `login-view` | div | Login container |
| `main-view` | div | Main chat interface |
| `login-form` | form | Sidepanel login form |
| `email` | input | Email field |
| `password` | input | Password field |
| `login-error` | div | Error display |
| `toggle-sidebar` | button | Open/close sidebar |
| `new-chat-btn` | button | Create new conversation |
| `settings-btn` | button | Open settings panel |
| `sidebar` | aside | Conversation list sidebar |
| `sidebar-overlay` | div | Click to close sidebar |
| `close-sidebar` | button | Close sidebar button |
| `conversation-list` | ul | List of conversations |
| `conversation-empty` | div | Empty state |
| `sidebar-new-chat` | button | New chat in empty state |
| `settings-panel` | div | Settings panel |
| `close-settings` | button | Close settings |
| `model-select` | select | Model dropdown |
| `prompt-select` | select | Prompt dropdown |
| `history-length-slider` | input | History length |
| `history-value` | span | Slider value |
| `auto-include-page` | checkbox | Auto-include page content |
| `settings-user-email` | span | User email display |
| `logout-btn` | button | Logout button |
| `page-context-bar` | div | Page context indicator |
| `page-context-title` | span | Page title display |
| `remove-page-context` | button | Remove attached page |
| `chat-container` | div | Chat scroll container |
| `welcome-screen` | div | Initial welcome state |
| `messages-container` | div | Message list |
| `streaming-indicator` | div | Typing indicator |
| `attach-page-btn` | button | Attach current page |
| `multi-tab-btn` | button | Multi-tab selector |
| `voice-btn` | button | Voice input |
| `message-input` | textarea | Message input |
| `send-btn` | button | Send message |
| `stop-btn-container` | div | Stop button wrapper |
| `stop-btn` | button | Stop streaming |
| `tab-modal` | div | Tab selection modal |
| `tab-list` | ul | List of tabs |
| `close-tab-modal` | button | Close modal |
| `cancel-tab-modal` | button | Cancel selection |
| `confirm-tab-modal` | button | Confirm selection |

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

**Functions:**

| Function | Signature | Description |
|----------|-----------|-------------|
| **Initialization** |
| `initialize()` | `async () → void` | Entry point, checks auth |
| `initializeMainView()` | `async () → void` | Load conversations, settings |
| `showView(viewName)` | `(string) → void` | Switch login/main views |
| `setupEventListeners()` | `() → void` | Attach all event handlers |
| **Authentication** |
| `handleLogin(e)` | `async (Event) → void` | Login form handler |
| `handleLogout()` | `async () → void` | Logout handler |
| **Sidebar** |
| `toggleSidebar(open)` | `(boolean) → void` | Show/hide sidebar |
| `toggleSettings(open)` | `(boolean) → void` | Show/hide settings |
| **Settings** |
| `loadSettings()` | `async () → void` | Fetch models from server, load and populate settings |
| `saveSettings()` | `async () → void` | Save to storage and server |
| **Conversations** |
| `loadConversations()` | `async () → void` | Fetch conversations list |
| `renderConversationList()` | `() → void` | Render conversation sidebar |
| `handleConversationClick(e)` | `async (Event) → void` | Click handler delegation |
| `selectConversation(id)` | `async (string) → void` | Load and display conversation |
| `createNewConversation()` | `async () → void` | Create new conversation (deletes temp) |
| `deleteConversation(id)` | `async (string) → void` | Delete conversation |
| `saveConversation(id)` | `async (string) → void` | Save conversation (mark non-temporary) |
| **Messages** |
| `renderMessages()` | `() → void` | Render all messages |
| `renderMessage(msg)` | `(object) → string` | Render single message HTML |
| `addCopyButtons()` | `() → void` | Add copy buttons to code blocks |
| `scrollToBottom()` | `() → void` | Scroll chat to bottom |
| **Input Handling** |
| `handleInputChange()` | `() → void` | Textarea resize, button state |
| `handleInputKeydown(e)` | `(Event) → void` | Enter to send (Shift+Enter for newline) |
| `updateSendButton()` | `() → void` | Enable/disable send |
| **Sending Messages** |
| `sendMessage()` | `async () → void` | Send message with streaming |
| `stopStreaming()` | `() → void` | Cancel streaming response |
| `updateConversationInList(preview)` | `(string) → void` | Update title from message |
| **Page Context** |
| `attachPageContent()` | `async () → void` | Attach current page |
| `removePageContext()` | `() → void` | Remove attached page |
| **Multi-Tab** |
| `showTabModal()` | `async () → void` | Show tab selection modal |
| `handleTabSelection()` | `async () → void` | Extract & combine content from selected tabs |
| `truncateUrl(url)` | `(string) → string` | Shorten URL for display |
| `updateTabSelectionCount()` | `() → void` | Update confirm button text |
| `updateMultiTabIndicator()` | `() → void` | Update button tooltip |
| **Quick Suggestions** |
| `handleQuickSuggestion(action)` | `async (string) → void` | Handle suggestion clicks |
| **Runtime Messages** |
| `handleRuntimeMessage(msg, sender, respond)` | `(object, object, function) → void` | Handle incoming messages |
| **Utilities** |
| `escapeHtml(text)` | `(string) → string` | Sanitize HTML |
| `formatTime(timestamp)` | `(string) → string` | Format HH:MM |
| `formatTimeAgo(timestamp)` | `(string) → string` | Relative time |

**Event Listeners:**

| Element | Event | Handler |
|---------|-------|---------|
| `loginForm` | submit | `handleLogin` |
| `toggleSidebarBtn` | click | `toggleSidebar(true)` |
| `closeSidebarBtn` | click | `toggleSidebar(false)` |
| `sidebarOverlay` | click | `toggleSidebar(false)` |
| `sidebarNewChatBtn` | click | `createNewConversation` |
| `settingsBtn` | click | `toggleSettings(true)` |
| `closeSettingsBtn` | click | `toggleSettings(false)` |
| `logoutBtn` | click | `handleLogout` |
| `modelSelect` | change | Update settings, save |
| `promptSelect` | change | Update settings, save |
| `historyLengthSlider` | input | Update settings, save |
| `autoIncludePageCheckbox` | change | Update settings, save |
| `newChatBtn` | click | `createNewConversation` |
| `messageInput` | input | `handleInputChange` |
| `messageInput` | keydown | `handleInputKeydown` |
| `sendBtn` | click | `sendMessage` |
| `stopBtn` | click | `stopStreaming` |
| `attachPageBtn` | click | `attachPageContent` |
| `removePageContextBtn` | click | `removePageContext` |
| `multiTabBtn` | click | `showTabModal` |
| `voiceBtn` | click | Placeholder alert |
| `suggestionBtns` | click | `handleQuickSuggestion` |
| `conversationList` | click | `handleConversationClick` |
| `closeTabModalBtn` | click | Hide modal |
| `cancelTabModalBtn` | click | Hide modal |
| `confirmTabModalBtn` | click | `handleTabSelection` |
| `chrome.runtime.onMessage` | message | `handleRuntimeMessage` |

---

### 6.3 `sidepanel/sidepanel.css`

**Purpose:** Comprehensive styling for sidepanel (dark theme, electric cyan accent).

**CSS Variables:**
```css
/* Colors - Midnight Blue Dark Theme */
--bg-primary: #0a0e14;
--bg-secondary: #0d1219;
--bg-tertiary: #151c25;
--bg-elevated: #1a2332;
--bg-hover: #1e2a3a;

--text-primary: #e6edf3;
--text-secondary: #9ca6b3;
--text-muted: #6b7785;

/* Accent - Electric Cyan */
--accent: #00d4ff;
--accent-hover: #33ddff;
--accent-glow: rgba(0, 212, 255, 0.15);
--accent-dim: rgba(0, 212, 255, 0.3);

/* User message */
--user-bg: linear-gradient(135deg, #1e3a5f 0%, #1a2f4a 100%);
--user-border: #2563eb;

/* Assistant message */
--assistant-bg: var(--bg-tertiary);
--assistant-border: #374151;

/* Sizing */
--header-height: 52px;
--input-area-height: 120px;
--sidebar-width: 280px;
```

**Key Classes:**

| Class | Purpose |
|-------|---------|
| `.view` | Full-height view container |
| `.header` | Fixed header bar |
| `.sidebar` | Slide-in conversation list |
| `.sidebar.open` | Visible sidebar state |
| `.sidebar-overlay` | Dim background when sidebar open |
| `.settings-panel` | Slide-in settings from right |
| `.settings-panel.open` | Visible settings state |
| `.main-content` | Chat area container |
| `.chat-container` | Scrollable messages area |
| `.welcome-screen` | Initial empty state |
| `.messages-container` | Message list |
| `.message` | Message wrapper |
| `.message.user` | User message (right-aligned) |
| `.message.assistant` | Assistant message (left-aligned) |
| `.message-content` | Message body |
| `.streaming-indicator` | Typing dots animation |
| `.input-area` | Fixed input area |
| `.input-wrapper` | Textarea container |
| `.action-btn` | Input action buttons |
| `.send-btn` | Send button |
| `.page-context-bar` | Attached page indicator |
| `.modal` | Modal overlay |
| `.modal-content` | Modal box |
| `.quick-suggestions` | Welcome screen buttons |
| `.suggestion-btn` | Suggestion button |
| `.code-block-header` | Code block header with copy |

**Animations:**

| Animation | Duration | Used For |
|-----------|----------|----------|
| `fadeIn` | 0.3s | Message appearance |
| `bounce` | 1.4s | Typing indicator dots |
| `spin` | 1s | Loading spinners |

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

**Functions:**

| Function | Signature | Description |
|----------|-----------|-------------|
| **Page Extraction** |
| `extractPageContent()` | `() → object` | Extract readable content |
| `getSelectedText()` | `() → object` | Get currently selected text |
| **Modal** |
| `injectModalStyles()` | `() → void` | Inject CSS for modal |
| `showModal(title)` | `(string) → void` | Show modal with loading |
| `updateModalContent(content)` | `(string) → void` | Update modal body HTML |
| `closeModal()` | `() → void` | Remove modal from DOM |
| `copyModalContent()` | `() → void` | Copy modal content |
| `continueInChat()` | `() → void` | Open sidepanel |
| **Quick Actions** |
| `handleQuickAction(action, text)` | `async (string, string) → void` | Process quick action |

**Message Listener:**

| Message Type | Response |
|--------------|----------|
| `EXTRACT_PAGE` | `{ title, url, content, meta, length }` |
| `GET_SELECTION` | `{ text, hasSelection }` |
| `QUICK_ACTION` | `{ success: true }` (calls handleQuickAction) |
| `SHOW_MODAL` | `{ success: true }` (shows modal) |
| `HIDE_MODAL` | `{ success: true }` (closes modal) |

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
- Appears at bottom-left of every page
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

## 8. Backend Integration

### 8.1 API Endpoints Used

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

### 8.2 Authentication Flow

```
┌────────────┐     ┌────────────┐     ┌────────────┐
│   User     │     │  Extension │     │   Server   │
└─────┬──────┘     └─────┬──────┘     └─────┬──────┘
      │                  │                  │
      │ Enter email/pass │                  │
      │─────────────────▶│                  │
      │                  │                  │
      │                  │ POST /ext/auth/login
      │                  │─────────────────▶│
      │                  │                  │
      │                  │ { token, email } │
      │                  │◀─────────────────│
      │                  │                  │
      │                  │ Storage.setToken(token)
      │                  │ Storage.setUserInfo({...})
      │                  │                  │
      │  Show main UI    │                  │
      │◀─────────────────│                  │
```

### 8.3 Streaming Response Flow

```
┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐
│   User     │     │  Sidepanel │     │   Server   │     │    LLM     │
└─────┬──────┘     └─────┬──────┘     └─────┬──────┘     └─────┬──────┘
      │                  │                  │                  │
      │ Send message     │                  │                  │
      │─────────────────▶│                  │                  │
      │                  │                  │                  │
      │                  │ POST /ext/chat/{id}                 │
      │                  │ { message, stream: true }           │
      │                  │─────────────────▶│                  │
      │                  │                  │                  │
      │                  │                  │ Call LLM API     │
      │                  │                  │─────────────────▶│
      │                  │                  │                  │
      │                  │ SSE: data: {"chunk": "Hello"}       │
      │ Update UI        │◀─────────────────│◀─────────────────│
      │◀─────────────────│                  │                  │
      │                  │                  │                  │
      │                  │ SSE: data: {"chunk": " world"}      │
      │ Update UI        │◀─────────────────│◀─────────────────│
      │◀─────────────────│                  │                  │
      │                  │                  │                  │
      │                  │ SSE: data: {"done": true}           │
      │ Final render     │◀─────────────────│                  │
      │◀─────────────────│                  │                  │
```

### 8.4 Page Content Grounding

When page content is attached, the server injects it as a **separate user message** before the user's actual question. This ensures the LLM explicitly acknowledges and uses the page content.

**Flow:**
```
User message: "Summarize this page"
Page context: { url: "...", title: "...", content: "..." }

→ Server injects TWO messages to LLM:

Message 1 (user): 
  "I'm currently viewing this web page:
   **URL:** https://example.com
   **Title:** Example Page
   **Page Content:**
   [page content up to 64,000 chars]
   
   Please use the above page content to answer my questions."

Message 2 (assistant): 
  "I've read the page content. I'll use it to help answer your questions."

Message 3 (user): 
  "Summarize this page"
```

**Key Details:**
- Page content limit: **64,000 characters** (truncated with notice if exceeded)
- Content is injected as user message for better LLM grounding
- LLM acknowledges content before answering
- Works with all quick actions (summarize, explain, etc.)

---

## 9. Data Flow Diagrams

### 9.1 Login Flow

```
[Popup/Sidepanel] ──▶ [API.login(email, pass)]
                              │
                              ▼
                     POST /ext/auth/login
                              │
                              ▼
                     ┌────────────────┐
                     │ extension_server │
                     │ verify password  │
                     │ generate JWT     │
                     └────────┬───────┘
                              │
                              ▼
                     { token, email, name }
                              │
                              ▼
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
    Storage.setToken(token)      Storage.setUserInfo({...})
              │                               │
              └───────────────┬───────────────┘
                              │
                              ▼
                     Show authenticated UI
```

### 9.2 Page Extraction Flow

```
[User clicks "Include Page"]
              │
              ▼
[Sidepanel: attachPageContent()]
              │
              ▼
chrome.runtime.sendMessage({ type: EXTRACT_PAGE })
              │
              ▼
[Service Worker: handleExtractPage()]
              │
              ▼
chrome.tabs.sendMessage(tabId, { type: EXTRACT_PAGE })
              │
              ▼
[Content Script: extractPageContent()]
              │
              ▼
{ title, url, content, meta, length }
              │
              ▼
[Sidepanel: state.pageContext = {...}]
              │
              ▼
Show page context bar
```

### 9.3 Context Menu Quick Action Flow

```
[User selects text, right-clicks "Explain"]
              │
              ▼
[Service Worker: chrome.contextMenus.onClicked]
              │
              ▼
chrome.tabs.sendMessage(tabId, { type: QUICK_ACTION, action: 'explain', text })
              │
              ▼
[Content Script: handleQuickAction('explain', text)]
              │
              ▼
showModal('💡 Explanation')
              │
              ▼
fetch('/ext/chat/quick', { action, text })
              │
              ▼
[Server: LLM call]
              │
              ▼
{ response: "..." }
              │
              ▼
updateModalContent(response)
```

---

## 10. State Management

### 10.1 Chrome Storage

| Key | Type | Contents |
|-----|------|----------|
| `authToken` | string | JWT authentication token |
| `userInfo` | object | `{ email, name }` |
| `settings` | object | User preferences |
| `currentConversation` | string | Active conversation ID |
| `recentConversations` | array | Last 5 accessed conversations |

### 10.2 Sidepanel State

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

### 10.3 State Persistence

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

## 11. Styling Architecture

### 11.1 CSS File Organization

| File | Scope | Variables Defined |
|------|-------|-------------------|
| `popup/popup.css` | Popup only | Own set |
| `sidepanel/sidepanel.css` | Sidepanel only | Own set (similar) |
| `content_scripts/modal.css` | Page-injected modal | Inline in extractor.js |
| `assets/styles/common.css` | Shared reference | `--ai-*` prefixed |

### 11.2 Theme Colors

**Popup Theme (slightly lighter):**
- Background: `#0d1117` → `#161b22` → `#21262d`
- Accent: `#58a6ff` (Blue)

**Sidepanel Theme (darker):**
- Background: `#0a0e14` → `#0d1219` → `#151c25`
- Accent: `#00d4ff` (Cyan)

### 11.3 Responsive Considerations

| Breakpoint | Adjustment |
|------------|------------|
| Popup | Fixed 320px width |
| Sidepanel | Fills Chrome sidepanel width |
| Sidebar | Slides in/out, overlays |
| Settings | Slides from right |
| Modal | 90% width, max 500px |

---

## 12. Message Passing

### 12.1 Message Types

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

### 12.2 Message Flow Example

```javascript
// From popup - open sidepanel
chrome.runtime.sendMessage({ type: MESSAGE_TYPES.OPEN_SIDEPANEL });

// From sidepanel - extract page
chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXTRACT_PAGE }, (response) => {
    // response = { title, url, content, meta, length }
});

// In service worker - forward to content script
chrome.tabs.sendMessage(tabId, { type: MESSAGE_TYPES.EXTRACT_PAGE });
```

---

## 13. Extension Lifecycle

### 13.1 Installation

1. `chrome.runtime.onInstalled` fires in service worker
2. Context menus are created
3. Sidepanel behavior is configured

### 13.2 Popup Open

1. `popup.html` loads
2. `popup.js` runs `initialize()`
3. Check `Storage.isAuthenticated()`
4. If yes: `API.verifyAuth()` → show main or login
5. If no: show login

### 13.3 Sidepanel Open

1. `sidepanel.html` loads
2. `sidepanel.js` runs `initialize()`
3. Check `Storage.isAuthenticated()`
4. If yes: `initializeMainView()`:
   - Load user info
   - Load settings
   - Load conversations
   - Check for current conversation
5. If no: show login

### 13.4 User Session

```
Open Extension → Check Token → Valid?
       │                         │
       │                    ┌────┴────┐
       │                    │         │
       │                   Yes       No
       │                    │         │
       │                    ▼         ▼
       │              Show Main   Show Login
       │                    │         │
       │                    │    (User logs in)
       │                    │         │
       │                    └────┬────┘
       │                         │
       ▼                         ▼
   Use Extension ←────────── Store Token
```

### 13.5 Message Flow on Tab Change

```
[User switches tab]
        │
        ▼
chrome.tabs.onActivated
        │
        ▼
[Service Worker]
        │
        ▼
chrome.runtime.sendMessage({ type: 'TAB_CHANGED', ... })
        │
        ▼
[Sidepanel: handleRuntimeMessage]
        │
        ▼
(Could update page context UI)
```

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

---

---

## Appendix D: Changelog

### Version 1.3 (December 25, 2024)

**Multi-Tab Reading:**
- Full implementation of multi-tab content extraction
- Click "Multi-tab" button to open tab selection modal
- Checkboxes to select which tabs to read from
- Current tab is auto-selected by default
- Restricted URLs (chrome://, about://) are disabled
- Content from all selected tabs is combined with clear separators
- Backend updated to acknowledge multi-tab content explicitly

**New State Properties:**
- `multiTabContexts[]`: Array of extracted tab contexts
- `selectedTabIds[]`: Currently selected tab IDs

**New Message Type:**
- `EXTRACT_FROM_TAB`: Extract content from specific tab by ID

**New Functions (sidepanel.js):**
- `truncateUrl(url)`: Shorten URLs for display
- `updateTabSelectionCount()`: Update confirm button label
- `updateMultiTabIndicator()`: Update multi-tab button tooltip

**New Handler (service-worker.js):**
- `handleExtractFromTab()`: Extract content from any tab, with content script injection fallback

**UI Improvements:**
- Multi-tab button shows active state when tabs are selected
- Loading spinner while extracting from multiple tabs
- Restricted tabs shown as disabled with visual indicator
- Dynamic confirm button text shows selected count

---

### Version 1.2 (December 25, 2024)

**Auto-Include Page Content:**
- `autoIncludePage` setting now **enabled by default**
- When sending a message, page content is automatically attached if not already present
- Works with screenshot fallback for canvas-based apps (Google Docs)

**Temporary Conversations & Save:**
- Creating a new conversation **automatically deletes all temporary conversations**
- Added **Save button** (💾) for temporary conversations in sidebar
- Saved conversations (💬) won't be auto-deleted
- New API endpoint: `POST /ext/conversations/<id>/save`
- Conversation icons: 💭 = temporary, 💬 = saved

**UI Improvements:**
- Removed auto-scroll behavior
- Fixed duplicate code block headers issue
- Added `.conv-actions` wrapper for save/delete buttons
- Save button uses accent color, delete button uses error color on hover

**Screenshot Fallback:**
- Canvas-based apps (Google Docs, Sheets) trigger screenshot capture
- Screenshots sent to LLM as base64 images
- LLM acknowledges it's analyzing a screenshot

**Content Extraction:**
- Added site-specific extractors for: Google Docs, Gmail, Sheets, Twitter/X, Reddit, GitHub, YouTube, Wikipedia, Stack Overflow, LinkedIn, Medium/Substack, Notion, Quip
- Added floating button (bottom-left) to open sidepanel
- Selection priority: if user selects text, that's used instead of full page extraction

---

### Version 1.1 (December 25, 2024)

**Input Handling:**
- Changed from Ctrl+Enter to **Enter** to send messages
- Shift+Enter now creates newlines

**LLM Models:**
- Models now fetched dynamically from server via `GET /ext/models`
- Default model changed to `google/gemini-2.5-flash`
- UI shows short model names (part after `/`)
- New models: gemini-2.5-flash, claude-sonnet-4.5, claude-opus-4.5, gpt-5.2, gemini-3-pro-preview

**Page Content Grounding:**
- Increased page content limit from 2,000 to **64,000 characters**
- Page content now injected as separate user message for better LLM grounding
- LLM acknowledges page content before answering questions

**State Management:**
- Added `availableModels` array to sidepanel state
- `loadSettings()` now fetches models from server

---

*End of Extension Implementation Documentation*

