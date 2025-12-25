# Chrome Extension Implementation Guide

This document provides quick setup instructions for the Chrome Extension. The full design and architecture details are in `EXTENSION_DESIGN.md`.

## Quick Start

### 1. Setup Development Environment

```bash
# Navigate to extension directory
cd extension

# Download required libraries (if not already done)
# marked.min.js - Markdown parser
curl -o lib/marked.min.js https://cdn.jsdelivr.net/npm/marked@11.1.1/marked.min.js

# highlight.min.js - Syntax highlighter
curl -o lib/highlight.min.js https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/es/highlight.min.js

# highlight.min.css - Syntax highlighting theme
curl -o lib/highlight.min.css https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css
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

1. Click the extension icon in the toolbar
2. You should see the **Login** popup
3. Enter your credentials (same as web UI)
4. After login, click **Open Sidepanel** to launch the main chat interface

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
│   ├── sidepanel.js              # Conversation and message handling
│   └── sidepanel.css             # Styling
├── background/
│   └── service-worker.js         # Context menus, message passing
├── content_scripts/
│   ├── extractor.js              # Page content extraction & quick actions
│   └── modal.css                 # Modal styling for quick actions
├── shared/                        # Shared utilities
│   ├── constants.js              # API config, models, message types
│   ├── storage.js                # Chrome storage wrapper
│   └── api.js                    # API client for extension_server
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
- **Page Integration**: Extract page content and include in messages
- **Context Menu**: Right-click actions (explain, summarize, etc)
- **Quick Actions**: Summarize page, ask about selection
- **Markdown**: Rendered responses with syntax highlighting
- **Streaming**: Real-time response display as it's generated

### 🚀 Phase 2 (Future)

- Custom scripts (Tampermonkey-like)
- Browser automation
- MCP tools integration
- Workflow orchestration
- Voice input/commands
- Auto-complete in text fields

## Architecture

### Data Flow

```
User Action (Extension UI)
    ↓
Content Script / Service Worker (extract, coordinate)
    ↓
extension_server.py API (process, call LLM)
    ↓
LLM API (OpenAI, Anthropic, etc)
    ↓
Streaming Response
    ↓
Extension UI (render markdown, syntax highlighting)
```

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

Edit `shared/constants.js`:

```javascript
export const API_BASE = 'http://localhost:5001';  // Change to your server
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

**Popup**: `chrome://extensions/` → Details → **Inspect views** → `popup.html`

**Sidepanel**: Open sidepanel → Right-click → **Inspect**

**Service Worker**: `chrome://extensions/` → Details → **Inspect views** → `service-worker.js`

**Content Script**: Open any webpage → Right-click → **Inspect** → Console

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
3. **Send message**: Type and press Ctrl+Enter
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

**Version**: 1.0  
**Last Updated**: December 2024
