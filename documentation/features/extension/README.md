# Chrome Extension Implementation Guide

This document provides quick setup instructions for the Chrome Extension. For design and architecture details, see `extension_design_overview.md`. For file-by-file code reference, see `extension_implementation.md`.

## Quick Start

### 1. Setup Development Environment

```bash
cd extension  # navigate to extension directory
curl -o lib/marked.min.js https://cdn.jsdelivr.net/npm/marked@11.1.1/marked.min.js  # Markdown parser
curl -o lib/highlight.min.js https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/es/highlight.min.js  # Syntax highlighter
curl -o lib/highlight.min.css https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css  # Syntax theme
```

### 2. Backend Setup

The extension connects to the main `server.py` backend (port 5000) after unification (M1+):

```bash
# Activate environment
conda activate science-reader

# Start the main server (runs on port 5000)
python server.py
```

The server provides all LLM, conversation, workspace, and data APIs that the extension UI consumes. The legacy `extension_server.py` (port 5001) is no longer needed for M1-M6 functionality.

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
│   ├── sidepanel.html            # Chat UI with workspace tree + dual buttons
│   ├── sidepanel.js              # Conversation handling + script creation + KaTeX
│   ├── sidepanel.css             # Styling + KaTeX dark theme overrides
│   ├── workspace-tree.js         # jsTree workspace sidebar module (M5)
│   ├── workspace-tree.css        # jsTree dark theme overrides (M5)
│   ├── docs-panel.js             # Document management overlay panel (M6)
│   └── claims-panel.js           # PKB claims viewer overlay panel (M6)
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
├── lib/                          # Third-party libraries (bundled locally — MV3 CSP)
│   ├── marked.min.js             # Markdown parser
│   ├── highlight.min.js          # Syntax highlighter
│   ├── highlight.min.css         # Syntax highlighting theme
│   ├── jquery.min.js             # jQuery 3.5.1 (required by jsTree) (M5)
│   ├── jstree.min.js             # jsTree 3.3.17 (M5)
│   ├── jstree-themes/            # jsTree theme assets (M5)
│   │   └── default-dark/         # CSS + PNG sprites + throbber
│   ├── katex.min.js              # KaTeX math rendering (M5)
│   ├── katex.min.css             # KaTeX styles (M5)
│   ├── katex-auto-render.min.js  # KaTeX auto-render extension (M5)
│   └── fonts/                    # KaTeX woff2 font files (20 files) (M5)
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
- **Page Integration**: Extract page content and include in messages
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

### ✅ Implemented (Phase 3) - Backend Unification (M1-M6)

- **Unified Backend**: Extension connects to main `server.py` (port 5000) instead of separate `extension_server.py`
- **Session Auth**: Uses main backend's session/JWT auth (same credentials as web UI)
- **Full Conversation Pipeline**: Extension uses `Conversation.py` pipeline (PKB, agents, math, TLDR)
- **Workspace Sidebar**: jsTree-based hierarchical workspace tree matching main UI (M5)
- **Domain/Workspace Settings**: Domain + workspace selectors in popup Settings panel (M5)
- **Dual Chat Buttons**: "New Chat" (permanent) + "Quick Chat" (temporary) conversation creation (M5)
- **KaTeX Math Rendering**: LaTeX math expressions rendered in LLM responses (M5)
- **Page Context & OCR**: Page content extraction with pipelined OCR (migrated to main backend)
- **Scripts & Workflows**: Extension-specific scripts/workflows stored in main `users.db` (M4)
- **File Attachments**: PDF + image upload via FastDocIndex/FastImageDocIndex on main backend (M6)
- **Document Management Panel**: Conversation docs + global docs overlay panel with upload/download/remove (M6)
- **PKB Claims Panel**: Read-only claims/memories viewer with search, type/domain/status filters (M6)
- **Full Context Menu**: 8-item conversation context menu (copy ref, open in new window, clone, stateless, flag, move, save, delete) (M6)
- **Attachment Context Menu**: Right-click on rendered attachments for download, promote, delete (M6)

### 🚀 Phase 4 (Future)

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

`User Action (Extension UI) → Content Script / Service Worker → server.py API (port 5000) → Conversation.py Pipeline → LLM API → Streaming Response → Extension UI (render markdown + syntax highlighting + KaTeX math)`

### Authentication

- JWT tokens stored in `chrome.storage.local`
- Tokens included in all API requests via `Authorization: Bearer` header
- Tokens verified on each extension startup
- Automatic logout if token expires

### Storage

- **Conversations**: Stored via main server filesystem-based Conversation.py system (unified with web UI)
- **Scripts/Workflows**: Stored in `users.db` tables (`ExtensionScripts`, `ExtensionWorkflows`)
- **Settings**: Stored in chrome.storage.local (synced to server via `user_preferences.extension`)
- **Auth Token**: Stored in chrome.storage.local
- **Domain**: Stored in chrome.storage.local (`assistant`, `search`, or `finchat`)
- **Recent Conversations**: Cache in chrome.storage.local for quick access

## Configuration

### API Base URL

Edit `shared/constants.js`:

```javascript
export const API_BASE = 'http://localhost:5000';  // Main server (unified backend)
```

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

- Check that `server.py` is running on port 5000
- Verify API_BASE in `shared/constants.js` is correct (should be `http://localhost:5000`)

### "Token expired or invalid"

- Login again using the popup
- Check that server has the same JWT secret

### "Page content extraction failed"

- Content script might not be injected on that page
- Check the page's Content Security Policy (CSP)

### Settings not saving

- Check that `server.py` is accessible on port 5000
- Verify user is authenticated

## Development Tips

### Testing Flow

1. **Login**: Use popup to login
2. **Domain/Workspace**: Open popup Settings → select domain and workspace
3. **Create chat**: Click "New Chat" (permanent) or "Quick Chat" (temporary) in sidepanel
4. **Send message**: Type and press Enter (Shift+Enter for newline)
5. **Test page context**: Click "Include page" button
6. **Quick actions**: Right-click text on page
7. **Math rendering**: Send a message asking for math — verify KaTeX renders

### Making Changes

- Popup, Sidepanel, CSS: Changes take effect after reload (click extension icon in chrome://extensions/)
- Service Worker: Auto-reloads
- Content Scripts: Reload page to get new version
- Shared code: Changes to shared/ files require extension reload

### Adding New API Methods

1. Add endpoint to `server.py` or appropriate `endpoints/*.py` file
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

1. Check `extension_design_overview.md` for architecture and conversation flow
2. Check `extension_implementation.md` for file-by-file code reference
2. Review `extension_api.md` for API reference
3. Check browser console for errors
4. Review `server.py` logs

## Next Steps

1. ✅ Complete Phase 1 (basic chat)
2. ✅ Phase 2: Custom scripts and automation
3. ✅ Phase 3 (M1-M5): Backend unification + workspace UI + KaTeX
4. ✅ M6: File attachments, docs panel, claims panel, full context menu
5. ✅ M7: Legacy code cleanup (deprecate extension_server.py, update all docs)
6. 🎯 Phase 4: Workflow orchestration and MCP tools

---

**Version**: 1.7  
**Last Updated**: February 17, 2026
