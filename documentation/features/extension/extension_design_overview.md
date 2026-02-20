# Chrome Extension — Design Overview

**Version:** 1.0
**Last Updated:** February 17, 2026

The Chrome extension is a sidepanel-based AI assistant that connects to `server.py` (port 5000) — the same unified backend as the main web UI. It uses JWT authentication, real-time streaming, workspace-aware conversations, and the full `Conversation.py` pipeline (PKB, agents, math formatting, TLDR). Built with vanilla JS, jQuery (for jsTree), and KaTeX (for math rendering). All third-party libraries are bundled locally under `extension/lib/` to comply with Chrome MV3 CSP (`script-src 'self'`).

---

## 1. Features Supported

| Category | Features |
|----------|----------|
| **Chat** | Send messages with streaming responses, conversation history (configurable length), page context grounding (single page + multi-tab), screenshots with vision-LLM OCR, voice input (MediaRecorder + `/transcribe`), markdown rendering (marked.js), syntax highlighting (highlight.js) |
| **Workspaces** | jsTree sidebar with expandable workspace folders, color indicators, domain switching (assistant/search/finchat), "Browser Extension" workspace auto-created per domain (#9b59b6 purple) |
| **Conversations** | Create permanent ("New Chat") and temporary ("Quick Chat"), clone, toggle stateless mode, set flag (7 colors), move between workspaces, copy reference link, open in new window, save/delete |
| **Documents** | Upload PDF/images via drag-and-drop (FastDocIndex, 1-3s), list conversation docs and global docs in overlay panel, upload/download/delete, promote (message-attached to conversation to global) |
| **PKB / Claims** | Read-only claims viewer overlay with debounced text search, type/domain/status filter dropdowns, paginated "Load more" results |
| **Custom Scripts** | Tampermonkey-like scripts created via chat (LLM sees page structure) or direct editor (CodeMirror), `aiAssistant` API (dom/clipboard/llm/ui/storage), floating toolbar, command palette (Ctrl+Shift+K), injected DOM buttons |
| **Math** | KaTeX renders LaTeX in LLM responses: display math (`\[...\]`, `$$...$$`), inline math (`\(...\)`, `$...$`), applied after message completion, dark theme overrides |
| **Settings** | Model, prompt, history length, auto-include page, domain, workspace. Stored in `chrome.storage.local` and synced to server via `/ext/settings`. Configurable backend URL (localhost vs hosted). |
| **Context Menus** | 8-item conversation menu (copy ref, open new window, clone, stateless, flag submenu, move submenu, save, delete). 4-item attachment menu (download, promote to conversation, promote to global, delete). Right-click quick actions on page text (explain, summarize, etc.). |

---

## 2. Architecture Design Decisions

- **Unified backend** (`server.py:5000`): Extension calls the same server as the web UI. Eliminates ~4700 lines of duplicate code from the deprecated `extension_server.py`. Gains full `Conversation.py` pipeline: PKB distillation, agents, math formatting, TLDR summaries.

- **Dual auth** (JWT + session cookies): Extension sends JWT in `Authorization: Bearer` header. Web UI uses Flask session cookies. Both verified by the same `get_session_identity()` function in `server.py`. No separate auth system needed.

- **IIFE modules for panels**: `DocsPanel` and `ClaimsPanel` are IIFEs loaded as plain `<script>` tags before the ES module `sidepanel.js`. They access the API via `window.API` global (set in sidepanel.js). This avoids ES module import issues in Chrome MV3.

- **jsTree for workspace sidebar**: Matches the main web UI's `workspace-manager.js` pattern. Dark theme with vakata CSS overrides. Context menus for both workspaces and conversations. CustomEvents (`tree-clone-conversation`, `tree-set-flag`, etc.) decouple `workspace-tree.js` from `sidepanel.js`.

- **KaTeX over MathJax**: Lighter weight (~250KB JS vs ~1MB). Renders after message completion only (not during streaming). Dark theme color overrides in sidepanel.css.

- **MV3 CSP compliance**: Chrome MV3 only allows `script-src 'self'`. All libraries (jQuery, jsTree, KaTeX, marked, highlight.js) bundled locally in `extension/lib/`. No CDN references.

- **Configurable backend URL**: Popup Settings panel allows switching between `http://localhost:5000` (dev) and production domains at runtime. Stored in `chrome.storage.local`, read by `Storage.getApiBaseUrl()`.

- **Domain concept**: Three domains (assistant, search, finchat). Each domain has its own "Browser Extension" workspace auto-created on first use. Domain change triggers full tree reload + conversation clear.

- **Zero server code for M5-M7**: All UI features (jsTree sidebar, docs panel, claims panel, context menus, file uploads) use existing main backend endpoints directly. No new server endpoints were added.

- **FastDocIndex for uploads**: PDF/image uploads create FastDocIndex (BM25 keyword search) or FastImageDocIndex on the server. 1-3s upload time vs instant (old system message approach). Stored on server filesystem.

- **Newline-delimited JSON streaming**: Extension's `streamJsonLines()` parser reads `{"status":"...", "content":"...", "type":"..."}` lines from `/send_message/<id>`. No SSE bridge needed.

---

## 3. Conversation Flow: Extension to Backend

### Standard Chat Flow

1. **User types message** in the sidepanel input and presses Enter.

2. **File uploads**: If pending attachments (PDF/images), `uploadPendingFiles()` uploads each via `POST /upload_doc_to_conversation/<id>`. Server creates FastDocIndex (PDF) or FastImageDocIndex (image). Returns `{doc_id, source, title}` per file.

3. **Page context**: If "Include page" is active, the `page_context` object (`{url, title, content}`) is added to the request payload. Content is capped at 64K chars (single page) or 128K (multi-tab).

4. **Payload construction**: `{message, checkboxes: {model, prompt_name, use_pkb, history_length, ...}, page_context, images, display_attachments, source: "extension"}`.

5. **API call**: `POST /send_message/<conversation_id>` with streaming enabled. Uses `fetch()` with `ReadableStream` reader.

6. **Server pipeline** (`Conversation.py.reply()`):
   - Saves user message to conversation history
   - Injects page context as grounding messages (user message with content + assistant acknowledgment)
   - Resolves system prompt from prompt library
   - Appends PKB memory snippets to system prompt
   - Includes document context from any FastDocIndex associated with the conversation
   - Retrieves conversation history (configurable length)
   - Calls LLM with the full message array
   - Streams response chunks as newline-delimited JSON

7. **Streaming render**: `streamJsonLines()` in sidepanel.js reads each line, appends content to the message card, renders markdown via marked.js with syntax highlighting via highlight.js.

8. **Post-completion**: KaTeX renders math expressions in the completed message. Conversation title is auto-set by the backend LLM (no client-side title generation).

### Quick Chat Flow

1. User clicks "Quick Chat" button
2. `POST /create_temporary_conversation/<domain>` — atomic endpoint that creates temporary conversation, cleans old temps, returns updated conversation list
3. Sidepanel auto-selects the new conversation in the jsTree sidebar
4. User sends message (standard flow above)

### Quick Action Flow (Context Menu)

1. User selects text on a webpage, right-clicks, chooses "Explain" (or other action)
2. Service worker receives `chrome.contextMenus.onClicked` event
3. Service worker sends message to content script on the active tab
4. Content script shows modal overlay on the page
5. Content script calls `POST /ext/chat/quick` with selected text + action
6. Server calls LLM, returns response
7. Content script updates modal with the response

---

## 4. Key Files

| File | Purpose |
|------|---------|
| `extension/shared/api.js` | API client — 50+ methods: auth, conversations, chat, documents, global docs, claims, scripts, workflows, settings |
| `extension/shared/constants.js` | `API_BASE` (default `http://localhost:5000`), model list, quick actions, message types |
| `extension/shared/storage.js` | Chrome storage wrapper — token, user info, settings, domain, API base URL |
| `extension/sidepanel/sidepanel.js` | Main UI logic (~4000 lines): conversation handling, streaming, message rendering, event handlers, panel wiring |
| `extension/sidepanel/sidepanel.html` | Chat UI: workspace tree, message area, input, overlay panels, context menus |
| `extension/sidepanel/sidepanel.css` | Dark theme styles (~2100 lines): layout, messages, panels, KaTeX overrides |
| `extension/sidepanel/workspace-tree.js` | jsTree sidebar module (~390 lines): tree init, 8-item context menu, flag/move submenus |
| `extension/sidepanel/docs-panel.js` | Document management overlay (IIFE, 188 lines): conversation docs + global docs sections |
| `extension/sidepanel/claims-panel.js` | PKB claims viewer overlay (IIFE, 136 lines): search, 3 filters, paginated load |
| `extension/popup/popup.js` | Login flow, settings panel (domain/workspace dropdowns), data flow to sidepanel |
| `extension/background/service-worker.js` | Context menus, message coordination between popup/sidepanel/content scripts, tab management |
| `extension/content_scripts/extractor.js` | Page content extraction (site-specific extractors for 16 document apps), quick action modals |
| `extension/content_scripts/script_runner.js` | Custom script execution engine + `aiAssistant` API |
| `extension/manifest.json` | Chrome MV3 configuration: permissions, content scripts, sidepanel, sandbox |
| `server.py` | Unified backend (port 5000) — registers all endpoint blueprints |
| `Conversation.py` | Core conversation pipeline: `reply()`, history, PKB integration, math, TLDR |
| `endpoints/ext_scripts.py` | Extension scripts CRUD (9 endpoints) |
| `endpoints/ext_workflows.py` | Extension workflows CRUD (5 endpoints) |
| `endpoints/ext_settings.py` | Extension settings get/put (stored in `user_preferences.extension` JSON) |
| `endpoints/ext_ocr.py` | OCR endpoint (gemini-2.5-flash-lite, 8 workers) |

---

## 5. Related Documentation

| Document | What it covers |
|----------|---------------|
| `extension_implementation.md` | File-by-file code reference (~1500 lines): every export, every handler, every state variable |
| `extension_api.md` | API endpoint reference: all `/ext/*` routes with request/response formats |
| `README.md` | Quick start guide: setup, load in Chrome, test, feature list, custom scripts usage |
| `multi_tab_scroll_capture.md` | Multi-tab capture: 4 modes (Auto/DOM/OCR/Full OCR), deferred OCR, tab restoration, 16 URL patterns |

---

## 6. Extension Architecture (Unified)

Beyond the original `extension/` sidepanel extension, `extension-iframe/` provides page extraction capabilities to the main web UI in both regular browser tabs and sidepanel iframe contexts. `extension-headless/` has been deprecated (see `extension-headless/DEPRECATED.md`).

### Extensions

| Extension | Purpose | Transport |
|-----------|---------|-----------|
| `extension-iframe/` | Provides Chrome API ops to main UI in both regular browser tabs and sidepanel iframe | externally_connectable (onMessageExternal / onConnectExternal) |

### Shared Code (`extension-shared/`)

`extension-iframe` imports shared operation handlers from `extension-shared/`:

| Module | Description |
|--------|-------------|
| `operations-handler.js` | 10 operation handlers (PING, LIST_TABS, EXTRACT_CURRENT_PAGE, etc.) with chromeApi adapter pattern |
| `full-page-capture.js` | Scrolling screenshot capture algorithm |
| `extractor-core.js` | DOM extraction with 16 site-specific extractors |
| `script-runner-core.js` | Custom script execution engine |
| `sandbox.html/js` | Sandboxed script execution |

### Communication Patterns

- **All contexts (regular tab or iframe in sidepanel)**: Main UI uses `ExtensionBridge` with externally_connectable transport → `chrome.runtime.sendMessage(extId)` / `chrome.runtime.connect(extId)` → iframe service-worker → shared handlers
- **Extension ID discovery**: `id-advertiser.js` content script (iframe extension) sets `window.__aiExtId` on main UI pages at `document_start`.

### Key Files

| File | Lines | Description |
|------|-------|-------------|
| `extension-shared/operations-handler.js` | ~826 | Shared operation handlers with chromeApi adapter |
| `extension-iframe/background/service-worker.js` | ~143 | externally_connectable transport adapter over shared handlers |
| `extension-iframe/content_scripts/id-advertiser.js` | ~18 | Extension ID advertiser for main UI pages |
| `interface/extension-bridge.js` | ~200 | Single-transport client (externally_connectable) |

---

*End of Extension Design Overview*
