---
name: Iframe Sidepanel Extension
overview: >
  A thin Chrome extension (extension-iframe/) whose sole purpose is to provide a
  sidepanel that loads the main web UI inside an iframe. The sidepanel page is a
  minimal HTML wrapper — just an iframe pointing at the main UI URL (localhost:5000
  or production). The main UI inside the iframe detects and uses the headless bridge
  extension for Chrome API operations (page extraction, multi-tab capture, etc.).
  This extension itself has NO Chrome API logic — it is purely a viewport container.
status: draft
created: 2026-02-19
revised: 2026-02-19
depends-on:
  - extension_headless_bridge.plan.md
  - main_ui_extension_integration.plan.md
---

# Iframe Sidepanel Extension Plan

## Purpose & Intent

### Why This Exists

Users want to use the AI assistant while browsing without switching tabs. The current
extension provides a sidepanel for this, but its custom chat UI will never match the
main web UI's feature set (workspaces, PKB, artefacts, global docs, prompts, doubts,
clarifications, code editor, math rendering, multi-model tabs, etc.).

**This extension solves the problem by showing the actual main UI in the sidepanel.**
It is the thinnest possible extension — a single HTML page with an iframe. No custom
chat code, no duplicate features, no maintenance burden. The main UI is the main UI,
whether in a tab or in the sidepanel.

### How It Fits in the Multi-Extension Architecture

```
User installs:
  1. Headless Bridge Extension    (required — provides Chrome APIs)
  2. Iframe Sidepanel Extension   (this — provides the sidepanel viewport)
  3. Current Extension            (optional — independent, self-contained)

User opens sidepanel:
  - Iframe extension's sidepanel.html loads
  - iframe src = http://localhost:5000/interface/interface.html
  - Main UI loads inside iframe
  - Headless bridge injects bridge.js into the iframe (matches localhost:5000/*)
  - Main UI detects bridge, shows extension controls
  - User has full main UI with page extraction etc. in the sidepanel
```

### What This Extension Does

- Provides a sidepanel with an iframe to the main web UI
- Lets the user resize the sidepanel (Chrome built-in)
- Opens sidepanel when user clicks the extension icon
- That's it. Everything else is handled by the main UI + headless bridge.

### What This Extension Does NOT Do

- No Chrome API calls (that's the headless bridge's job)
- No backend API calls (that's the main UI's job via session cookie)
- No content scripts on external pages
- No message passing, no service worker logic
- No chat UI, no conversations, no settings

### Key Architectural Insight

The headless bridge extension's `bridge.js` content script matches `http://localhost:5000/*`.
When the main UI is loaded in this extension's iframe, the iframe URL is `http://localhost:5000/...`.
Chrome injects matching content scripts into iframes inside extension pages. Therefore,
`bridge.js` is automatically injected into the iframe — no special configuration needed.

The main UI code in the iframe calls `ExtensionBridge.init()`, detects the bridge, and
works exactly as it would in a regular browser tab. Zero code differences.

### Session Cookie Behavior

The iframe loads from `http://localhost:5000` (or `https://production-domain`). The Flask
session cookie is set with `SameSite=None; Secure=True`. Since the iframe is cross-origin
(parent is `chrome-extension://`, child is `http://localhost:5000`), the cookie behavior
depends on Chrome's third-party cookie policy:

- **Currently (2026)**: Works. `SameSite=None` cookies are sent in cross-origin iframes.
- **Future risk**: Chrome is deprecating third-party cookies. If/when this affects
  extension-to-web iframes, we'll need a fallback (token-based auth via postMessage
  from parent, or `chrome.cookies` API in the headless extension).
- **Localhost exemption**: `localhost` is treated as a secure context even over HTTP,
  so `Secure=True` doesn't block it on localhost.

## 0. Corrections and Code Sharing Reference (Added 2026-02-19)

### Code Sharing
This extension has NO shared code with other extensions — it is purely a viewport container.
See `extension_headless_bridge.plan.md` section "0. Code Sharing Strategy" for the overall architecture.

### Corrections from Code Analysis

1. **Storage permission needed**: The sidepanel.html code uses `chrome.storage?.local` for URL preference persistence. Add `"storage"` to the permissions array in manifest.json.

2. **Content script injection into iframe confirmed**: When the headless bridge extension's manifest matches `http://localhost:5000/*`, Chrome injects matching content scripts INTO iframes with that URL, even inside this extension's sidepanel. This is the key mechanism making the architecture work — no special configuration needed, but must be verified during testing.

3. **Production URL confirmed**: `https://assist-chat.site` (from nginx config in README.md). The CSP `frame-src` must include both localhost and production.

## 1. File Structure

```
extension-iframe/
+-- manifest.json           # Minimal: sidePanel permission only
+-- sidepanel/
|   +-- sidepanel.html      # Just an iframe wrapper
|   +-- sidepanel.css       # Minimal: make iframe fill viewport
+-- assets/
    +-- icons/              # Extension icons (distinct from other extensions)
        +-- icon16.png
        +-- icon32.png
        +-- icon48.png
        +-- icon128.png
```

**Total: 4-5 files.** This is an extremely minimal extension.

## 2. Detailed Tasks

### Task 1: Create manifest.json

```json
{
    "manifest_version": 3,
    "name": "AI Assistant Sidepanel",
    "version": "1.0.0",
    "description": "View AI Assistant in a browser sidepanel while browsing",
    
    "permissions": [
        "sidePanel",
        "storage"
    ],
    
    "action": {
        "default_icon": {
            "16": "assets/icons/icon16.png",
            "32": "assets/icons/icon32.png",
            "48": "assets/icons/icon48.png",
            "128": "assets/icons/icon128.png"
        },
        "default_title": "AI Assistant - Open Sidepanel"
    },
    
    "side_panel": {
        "default_path": "sidepanel/sidepanel.html"
    },
    
    "background": {
        "service_worker": "background.js"
    },
    
    "content_security_policy": {
        "extension_pages": "script-src 'self'; object-src 'self'; frame-src http://localhost:5000 https://assist-chat.site"
    },
    
    "icons": {
        "16": "assets/icons/icon16.png",
        "32": "assets/icons/icon32.png",
        "48": "assets/icons/icon48.png",
        "128": "assets/icons/icon128.png"
    }
}
```

**Key points**:
- Only permission: `sidePanel`
- `content_security_policy.extension_pages`: Allows framing localhost:5000 and production domain
- `background.js`: Minimal service worker just to set sidepanel open on icon click
- No `content_scripts`, no `host_permissions`, no `tabs`, no `scripting`

### Task 2: Create background.js (minimal service worker)

```javascript
/**
 * Minimal service worker for Iframe Sidepanel Extension.
 * Only purpose: open sidepanel when user clicks extension icon.
 */
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
```

That's the entire file. ~3 lines.

### Task 3: Create sidepanel.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Assistant</title>
    <link rel="stylesheet" href="sidepanel.css">
</head>
<body>
    <div id="loading">
        <div class="spinner"></div>
        <p>Loading AI Assistant...</p>
    </div>
    
    <iframe id="main-ui-frame" 
            src="http://localhost:5000/interface/interface.html"
            allow="microphone; clipboard-write"
            sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals allow-downloads">
    </iframe>
    
    <div id="error" style="display: none;">
        <h3>Cannot connect to AI Assistant</h3>
        <p>Make sure the server is running at:</p>
        <code id="server-url">http://localhost:5000</code>
        <br><br>
        <button id="retry-btn">Retry</button>
        <button id="switch-url-btn">Switch Server</button>
    </div>
    
    <script>
        /**
         * Minimal sidepanel logic:
         * 1. Show loading spinner while iframe loads
         * 2. Hide loading when iframe finishes loading
         * 3. Show error if iframe fails to load
         * 4. Allow switching between localhost and production URL
         */
        (function() {
            var frame = document.getElementById('main-ui-frame');
            var loading = document.getElementById('loading');
            var error = document.getElementById('error');
            
            // URLs (can be extended or made configurable via chrome.storage)
            var urls = [
                'http://localhost:5000/interface/interface.html',
                'https://assist-chat.site/interface/interface.html'
            ];
            var currentUrlIndex = 0;
            
            // Try to load saved URL preference
            chrome.storage?.local?.get?.(['sidepanel_url_index'], function(result) {
                if (result && typeof result.sidepanel_url_index === 'number') {
                    currentUrlIndex = result.sidepanel_url_index;
                    frame.src = urls[currentUrlIndex];
                    document.getElementById('server-url').textContent = urls[currentUrlIndex];
                }
            });
            
            frame.addEventListener('load', function() {
                loading.style.display = 'none';
                error.style.display = 'none';
                frame.style.display = 'block';
            });
            
            frame.addEventListener('error', function() {
                loading.style.display = 'none';
                error.style.display = 'block';
                frame.style.display = 'none';
            });
            
            // Timeout: if iframe hasn't loaded in 10 seconds, show error
            setTimeout(function() {
                if (loading.style.display !== 'none') {
                    loading.style.display = 'none';
                    error.style.display = 'block';
                }
            }, 10000);
            
            document.getElementById('retry-btn').addEventListener('click', function() {
                error.style.display = 'none';
                loading.style.display = 'flex';
                frame.src = urls[currentUrlIndex];
            });
            
            document.getElementById('switch-url-btn').addEventListener('click', function() {
                currentUrlIndex = (currentUrlIndex + 1) % urls.length;
                chrome.storage?.local?.set?.({ sidepanel_url_index: currentUrlIndex });
                document.getElementById('server-url').textContent = urls[currentUrlIndex];
                error.style.display = 'none';
                loading.style.display = 'flex';
                frame.src = urls[currentUrlIndex];
            });
        })();
    </script>
</body>
</html>
```

**Key points**:
- iframe `src` defaults to localhost:5000
- `allow="microphone; clipboard-write"` — needed for voice recording and copy
- `sandbox` attribute allows necessary capabilities while maintaining security
- Loading spinner shown while iframe loads
- Error state with retry and server switch if connection fails
- Server URL preference saved in chrome.storage.local
- Minimal inline script (~50 lines) — acceptable for this single-purpose page

### Task 4: Create sidepanel.css

```css
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

html, body {
    width: 100%;
    height: 100%;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f8f9fa;
}

#main-ui-frame {
    display: none; /* shown after load */
    width: 100%;
    height: 100%;
    border: none;
}

#loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #6c757d;
}

.spinner {
    width: 32px;
    height: 32px;
    border: 3px solid #dee2e6;
    border-top-color: #007bff;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-bottom: 12px;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

#error {
    padding: 24px;
    text-align: center;
    color: #495057;
}

#error h3 {
    color: #dc3545;
    margin-bottom: 12px;
}

#error code {
    background: #e9ecef;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 0.9rem;
}

#error button {
    padding: 8px 16px;
    border: 1px solid #dee2e6;
    border-radius: 4px;
    background: white;
    cursor: pointer;
    margin: 4px;
    font-size: 0.9rem;
}

#error button:hover {
    background: #e9ecef;
}

#retry-btn {
    border-color: #007bff;
    color: #007bff;
}
```

### Task 5: Create extension icons

Create or adapt icons with a distinct style from both the current extension and the
headless bridge extension. Suggested: same base icon with a different background color
or a small "panel" indicator overlay.

## 3. Optional Enhancements

These are NOT required for v1 but could be added later:

### 3a. Compact Mode CSS (deferred)

If the main UI looks too cramped at sidepanel width (~400px), add a `?mode=compact`
query param to the iframe URL and corresponding CSS in the main UI:

```javascript
// In sidepanel.html, change iframe src to:
frame.src = urls[currentUrlIndex] + '?mode=compact';
```

```css
/* In interface/style.css */
body.compact-mode #chat-assistant-sidebar { display: none; }
body.compact-mode #pdf-details-tab { display: none; }
body.compact-mode .modal-dialog { max-width: 100%; margin: 0.5rem; }
/* ... */
```

This is a separate concern and should be evaluated after basic iframe functionality works.

### 3b. Parent-to-Iframe Communication (deferred)

The sidepanel parent page could communicate with the iframe for:
- Passing the current tab's URL to the main UI (so it can show "you're on: [url]")
- Triggering page extraction for the tab the sidepanel is attached to

This would require adding `storage` permission to the manifest and a small postMessage
handler. Deferred until basic functionality is validated.

### 3c. URL Configuration Page (deferred)

Instead of the simple toggle between localhost and production, a small options page
could let users enter a custom server URL. Low priority since the toggle covers the
two main use cases (development vs production).

## 4. Testing Strategy

| Test | Steps | Expected |
|------|-------|----------|
| Basic load | Install extension, click icon | Sidepanel opens, main UI loads in iframe |
| Login | Log in via the iframe | Session established, conversations load |
| Chat | Send a message | Streaming response renders correctly |
| Workspaces | Navigate workspace tree | Workspaces work (may be tight at 400px) |
| Page extraction (with headless ext) | Install headless ext too, click "Page" button | Extracts content from active tab |
| Multi-tab capture | Click "Multi-tab" in iframe | Tab picker modal opens (may need compact CSS) |
| Server switch | Click "Switch Server" on error screen | URL switches between localhost and production |
| Retry on failure | Stop server, open sidepanel, start server, click Retry | Iframe loads after retry |
| Voice recording | Click mic button in iframe | Permission prompt appears, recording works |
| File upload | Drag file onto iframe | File upload works (if sandbox allows) |
| Without headless ext | Install only this extension (no headless) | Main UI loads but extension controls hidden |

## 5. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Third-party cookie deprecation breaks session | Can't log in inside iframe | Fallback: token-based auth via postMessage from parent; or user opens main UI in tab to log in, session persists |
| Main UI too cramped at 400px | Poor UX | Defer to compact mode CSS (enhancement 3a); sidepanel is resizable by user |
| CSP blocks iframe | Iframe won't load | `frame-src` in manifest CSP; ensure Flask doesn't send X-Frame-Options: DENY |
| Bridge not injected into iframe | Extension controls missing | Verify Chrome injects content scripts into cross-origin iframes in extension sidepanels; fallback: use `chrome.scripting.executeScript` from headless extension |
| Sandbox attribute blocks functionality | Features broken (forms, popups) | Test each `sandbox` allow-* flag; adjust as needed |
| Multiple extensions with sidepanels | User confusion about which sidepanel | Different extension names and icons; Chrome shows extension name in sidepanel header |

### Critical Check: X-Frame-Options

The Flask backend must NOT send `X-Frame-Options: DENY` or `X-Frame-Options: SAMEORIGIN`
headers for the main UI page. Check:

```python
# In server.py or middleware — verify no X-Frame-Options header is set
# If present, either remove it or set it to ALLOW-FROM chrome-extension://...
# Note: ALLOW-FROM is deprecated. Better to use Content-Security-Policy: frame-ancestors
```

Current server.py search shows NO X-Frame-Options header is set — this is good.
No changes needed to the backend.

## 6. Estimated Effort

| Task | Effort |
|------|--------|
| Task 1: manifest.json | 15 min |
| Task 2: background.js | 5 min |
| Task 3: sidepanel.html | 1-2h |
| Task 4: sidepanel.css | 30 min |
| Task 5: Icons | 30 min |
| Testing | 1-2h |
| **Total** | **~3-5h (half day)** |

This is intentionally the simplest extension in the architecture. Its value comes from
the main UI and headless bridge doing the heavy lifting.

## 7. Success Criteria

1. Sidepanel opens when user clicks extension icon
2. Main UI loads inside iframe within 3 seconds (localhost)
3. User can log in and use all main UI features
4. With headless bridge installed: extension controls appear and work
5. Without headless bridge: main UI works normally, extension controls hidden
6. Server switch between localhost and production works
7. Error screen shows when server is unreachable, retry works
8. No console errors from CSP violations
