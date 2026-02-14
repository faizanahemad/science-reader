# Chrome Extension Implementation Guide

This document provides quick setup instructions for the Chrome Extension. The full design and architecture details are in `EXTENSION_DESIGN.md`.

## Quick Start

### 1. Setup Development Environment

```bash
cd extension  # navigate to extension directory
curl -o lib/marked.min.js https://cdn.jsdelivr.net/npm/marked@11.1.1/marked.min.js  # Markdown parser
curl -o lib/highlight.min.js https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/es/highlight.min.js  # Syntax highlighter
curl -o lib/highlight.min.css https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css  # Syntax theme
```

### 2. Backend Setup

The extension requires the `extension_server.py` backend running:

```bash
# Activate environment
conda activate science-reader

# Start the extension server (runs on port 5001)
python extension_server.py --port 5001 --debug
```

The server provides all LLM and data APIs that the extension UI consumes.

### 3. Load Extension in Chrome

1. Open Chrome and go to `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Navigate to the `chatgpt-iterative/extension/` folder and select it
5. The extension will appear in your extensions list

### 4. Test the Extension

1. Click the extension icon in the toolbar → you should see the **Login** popup
2. Enter your credentials (same as web UI)
3. After login, click **Open Sidepanel** to launch the main chat interface

## File Structure

```
extension/
├── manifest.json                  # Extension configuration
├── popup/                         # Login & quick actions UI
│   ├── popup.html                # Login and main view
│   ├── popup.js                  # Event handlers
│   └── popup.css                 # Styling
├── sidepanel/                     # Main chat interface (full height)
│   ├── sidepanel.html            # Chat UI with conversation list
│   ├── sidepanel.js              # Conversation handling + script creation
│   └── sidepanel.css             # Styling
├── background/
│   └── service-worker.js         # Context menus, message passing, script coordination
├── content_scripts/
│   ├── extractor.js              # Page content extraction & quick actions
│   ├── modal.css                 # Modal styling for quick actions
│   ├── script_runner.js          # Custom script execution engine
│   ├── script_ui.js              # Floating toolbar + command palette
│   └── script_ui.css             # Script UI styles
├── editor/                        # Script editor UI (opened in a new tab)
│   ├── editor.html               # Editor UI
│   ├── editor.js                 # CodeMirror + action builder
│   └── editor.css                # Editor styles
├── sandbox/                       # Sandboxed page for script execution (no unsafe-eval)
│   ├── sandbox.html              # Sandbox host page (manifest "sandbox")
│   └── sandbox.js                # Sandbox runtime + RPC bridge to content script
├── shared/                        # Shared utilities
│   ├── constants.js              # API config, models, message types
│   ├── storage.js                # Chrome storage wrapper
│   └── api.js                    # API client (including script methods)
├── lib/                          # Third-party libraries
│   ├── marked.min.js             # Markdown parser
│   ├── highlight.min.js          # Syntax highlighter
│   └── highlight.min.css         # Syntax highlighting theme
├── assets/
│   ├── icons/                    # Extension icons (16x16, 32x32, etc)
│   └── styles/                   # Common styles (if needed)
└── tests/                        # Integration tests (for backend)
```

## Key Features

### ✅ Implemented (Phase 1)

- **Authentication**: Email/password login with JWT tokens
- **Chat Interface**: Full-height sidepanel with message display
- **Conversations**: Create, list, delete conversations
- **Settings**: Model, prompt, history length, auto-include page
- **Page Integration**: Extract page content, refresh/append context for SPAs, and include in messages
- **Screenshot & OCR**: Viewport screenshots, full-page scrolling screenshots with vision-LLM OCR
- **Inner Scroll Detection**: Automatically detects inner scrollable containers (Office Word Online, Google Docs, Notion, Confluence, Slack, Overleaf, etc.) for correct full-page capture in web apps with fixed shells
- **Pipelined OCR**: Fires OCR per screenshot as it's captured (40-60% faster than batch)
- **Content Viewer**: Paginated viewer for extracted/OCR text with per-page navigation and copy-to-clipboard
- **Multi-Tab Scroll Capture**: Capture content from other tabs using scroll+screenshot+OCR for document apps (Google Docs, Word Online, Notion, etc.) with 4 per-tab capture modes (Auto/DOM/OCR/Full OCR), auto-detection of document apps via URL patterns, deferred OCR with immediate tab restoration, on-page toast overlays during capture, and content script pre-injection for reliability
- **Context Menu**: Right-click actions (explain, summarize, etc)
- **Quick Actions**: Summarize page, ask about selection
- **Markdown**: Rendered responses with syntax highlighting
- **Streaming**: Real-time response display as it's generated

### ✅ Implemented (Phase 2) - Custom Scripts

- **Tampermonkey-like Scripts**: Create custom scripts for any website
- **Two Creation Modes**: 
  - Chat-driven (LLM sees page structure, iterative refinement)
  - Direct editor (code editor + action builder)
- **aiAssistant API**: Scripts get access to DOM, clipboard, LLM, UI, storage APIs
- **Floating Toolbar**: Draggable toolbar showing available actions
- **Command Palette**: Ctrl+Shift+K to search and run actions
- **Injected Buttons**: Actions can be injected into page DOM
- **Script Editor**: CodeMirror-based editor with syntax highlighting

### 🚀 Phase 3 (Future)

- Browser automation
- MCP tools integration
- Workflow orchestration
- Voice input/commands
- Auto-complete in text fields

## Using Custom Scripts

### Creating a Script via Chat

1. Open the sidepanel
2. Type a message like "Create a script to copy the title from this page"
3. The LLM will analyze the page structure and generate a script
4. Click **Test on Page** to try it
5. Click **Save Script** to save it
6. Click **Edit in Editor** to refine it

### Creating a Script via Editor

1. Press `Ctrl+Shift+K` to open command palette
2. Select "Create New Script"
3. Or click the floating toolbar's settings → "Create New Script"
4. Fill in script details, write code, add actions
5. Click **Test** to try on current page
6. Click **Save** to save

### Script Code Structure

```javascript
// Your handlers object with all actions
const handlers = {
    copyTitle() {
        const title = aiAssistant.dom.getText('h1');
        aiAssistant.clipboard.copy(title);
        aiAssistant.ui.showToast('Copied: ' + title, 'success');
    },
    
    async summarizePage() {
        const content = aiAssistant.dom.getText('article');
        const summary = await aiAssistant.llm.ask('Summarize: ' + content);
        aiAssistant.ui.showModal('Summary', summary);
    }
};

// REQUIRED: Export handlers
window.__scriptHandlers = handlers;
```

### Available aiAssistant APIs

| Category | Methods |
|----------|---------|
| **dom** | `exists`, `count`, `query`, `queryAll`, `getText`, `getHtml`, `getAttr`, `setAttr`, `getValue`, `waitFor`, `scrollIntoView`, `focus`, `blur`, `click`, `setValue`, `type`, `hide`, `show`, `remove`, `addClass`, `removeClass`, `toggleClass`, `setHtml` |
| **clipboard** | `copy`, `copyHtml` |
| **llm** | `ask`, `askStreaming` |
| **ui** | `showToast`, `showModal`, `closeModal` |
| **storage** | `get`, `set`, `remove` |

### Script Runtime Note (Important)

Scripts are executed via a sandboxed extension page for CSP safety. **Do not use direct DOM access** like `document.querySelector(...)` in user scripts.
Instead, always use `aiAssistant.dom.*` methods (they run inside the content script and can safely interact with the page).

### Action Exposure Types

| Type | Description |
|------|-------------|
| `floating` | Shows in the floating toolbar |
| `inject` | Injects a button into the page DOM |
| `command` | Only appears in command palette |
| `context_menu` | Appears in right-click menu |

---

## Architecture

### Data Flow

`User Action (Extension UI) → Content Script / Service Worker → extension_server.py API → LLM API → Streaming Response → Extension UI (render markdown + syntax highlighting)`

### Authentication

- JWT tokens stored in `chrome.storage.local`
- Tokens included in all API requests via `Authorization: Bearer` header
- Tokens verified on each extension startup
- Automatic logout if token expires

### Storage

- **Conversations**: Stored in extension_server.py SQLite database
- **Settings**: Stored in chrome.storage.local (synced to server on change)
- **Auth Token**: Stored in chrome.storage.local
- **Recent Conversations**: Cache in chrome.storage.local for quick access

## Configuration

### API Base URL

Set **Server URL** in the extension UI (login screen or Settings). The value is stored in `chrome.storage` and used by all extension API calls. Defaults to `http://localhost:5001` if not set. Quick presets are available in the UI: **Use Hosted** and **Use Local**.

### Available Models

Update `MODELS` array in `shared/constants.js` to match your backend:

```javascript
export const MODELS = [
    { id: 'openai/gpt-4o-mini', name: 'GPT-4o Mini' },
    // Add more models here
];
```

### Permissions

The extension requests minimal permissions:

- `activeTab`: Read current tab when user interacts
- `storage`: Store auth tokens and settings
- `sidePanel`: Display full-height sidebar
- `contextMenus`: Add right-click menu
- `scripting`: Inject content scripts

Optional permissions (requested when needed):
- `tabs`: Read all tabs for multi-tab support

## Debugging

### Check Extension Errors

1. Go to `chrome://extensions/`
2. Click **Details** on the AI Assistant extension
3. Scroll to **Errors** section

### View Console Logs

**Popup**: `chrome://extensions/` → Details → **Inspect views** → `popup.html` • **Sidepanel**: open sidepanel → right-click → **Inspect** • **Service Worker**: `chrome://extensions/` → Details → **Inspect views** → `service-worker.js` • **Content Script**: open any webpage → **Inspect** → Console

### Enable Debug Logging

The code already has console.log statements prefixed with `[AI Assistant]`. Filter the console for these.

## Common Issues

### "Cannot GET /ext/health"

- Check that `extension_server.py` is running on port 5001
- Verify API_BASE in `shared/constants.js` is correct

### "Token expired or invalid"

- Login again using the popup
- Check that server has the same JWT secret

### "Page content extraction failed"

- Content script might not be injected on that page
- Check the page's Content Security Policy (CSP)

### Settings not saving

- Check that `extension_server.py` is accessible
- Verify user is authenticated

## Development Tips

### Testing Flow

1. **Login**: Use popup to login
2. **Create chat**: Click "New Chat" in sidepanel
3. **Send message**: Type and press Enter (Shift+Enter for newline)
4. **Test page context**: Click "Include page" button
5. **Quick actions**: Right-click text on page

### Making Changes

- Popup, Sidepanel, CSS: Changes take effect after reload (click extension icon in chrome://extensions/)
- Service Worker: Auto-reloads
- Content Scripts: Reload page to get new version
- Shared code: Changes to shared/ files require extension reload

### Adding New API Methods

1. Add endpoint to `extension_server.py`
2. Add method to `API` object in `shared/api.js`
3. Import and use in appropriate component

## Performance Considerations

- Conversations loaded on demand (not all at once)
- Streaming prevents UI blocking during LLM responses
- CSS uses efficient selectors
- Sidebar is collapsible to save space

## Security

- API keys never exposed to extension (all calls via server)
- Auth tokens stored in chrome.storage.local
- Content scripts run in isolated worlds
- No sensitive data in extension storage (except token)
- HTTPS enforced for production

## Support

For issues or questions:

1. Check `EXTENSION_DESIGN.md` for architectural details
2. Review `extension_api.md` for API reference
3. Check browser console for errors
4. Review `extension_server.py` logs

## Next Steps

1. ✅ Complete Phase 1 (current)
2. 📋 Phase 2: Custom scripts and automation
3. 🎯 Phase 3: Workflow orchestration and MCP tools

---

**Version**: 1.5  
**Last Updated**: February 15, 2026
