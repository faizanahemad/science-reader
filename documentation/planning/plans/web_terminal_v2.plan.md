# Web Terminal v2 — flask-terminal (now) + ttyd (production)

## Goal

Replace the broken Approach C terminal (flask-sock + PTY WebSocket, plagued by PerMessageDeflate compression bugs) with a two-phase approach:

1. **Phase 1 (immediate)**: Integrate `flask-terminal` (HTTP polling blueprint) for a working terminal right now — no WebSocket, no compression bugs, works locally and in production identically.
2. **Phase 2 (production upgrade)**: Add `ttyd` (standalone C binary) behind nginx `auth_request` for a high-performance production terminal with native WebSocket (handled by battle-tested libwebsockets, not Python).

Both terminals get **separate modals**, **separate ingress buttons**, and **separate code** — completely decoupled from the existing chat-settings-modal and the broken Approach C code.

---

## Decisions

| Question | Decision |
|----------|----------|
| Why not fix Approach C? | PerMessageDeflate bug is in `simple_websocket` library. Patching library source is fragile (overwritten on pip install). flask-sock author confirms no compression support. We've spent 3+ sessions debugging — time to move on. |
| Why flask-terminal first? | Zero WebSocket = zero compression bugs. Pure Flask blueprint, works with existing auth, no nginx changes needed, works locally. 30-min integration. |
| Why ttyd later? | Battle-tested C WebSocket (libwebsockets), 11k stars, used by Docker/OpenWrt/QuickBox. But requires nginx config + separate process — production-only concern. |
| Modal approach | Two separate modals: `#flask-terminal-modal` (Phase 1) and `#ttyd-terminal-modal` (Phase 2). NOT shared — each has own HTML, JS, lifecycle. |
| Ingress separation | Two separate buttons in the settings panel Actions section. NOT inside chat-settings-modal or opencode-settings-modal. |
| Existing terminal code | Approach C code (`endpoints/terminal.py` WebSocket handler, `interface/opencode-terminal.js`, `#terminal-modal`) will be deprecated. Remove after Phase 1 is verified working. |
| Authentication | flask-terminal: `@terminal_blueprint.before_request` using `session["email"]`. ttyd: nginx `auth_request` to existing `/ext/auth/verify` endpoint. |
| Session isolation | flask-terminal ships with single global PTY session (all users share). We MUST fix this — per-user sessions keyed by `session["email"]`. |
| Shell | Configurable via `TERMINAL_SHELL` env var (default: user's login shell from `$SHELL`). NOT hardcoded `/bin/sh`. |
| Terminal resize | flask-terminal has no resize support. We MUST add it (new `/resize` route + `TIOCSWINSZ` ioctl). |
| iframe vs integrated | flask-terminal: iframe embed in our modal (it serves its own xterm.js page). ttyd: iframe embed in our modal (it serves its own xterm.js page). Both avoid us writing custom xterm.js client code. |
| CSS theme | Both terminals use their own built-in xterm.js. We style the modal wrapper (Catppuccin Mocha dark theme: `#1e1e2e` background) to match. Terminal themes configured server-side (ttyd: `-t theme=...`, flask-terminal: CSS override). |
| Polling interval | flask-terminal default is 1s — too slow. We'll reduce to 100-200ms for acceptable interactivity. |

---

## Requirements

### Functional

#### Phase 1: flask-terminal (HTTP Polling Terminal)

1. **New "Terminal" button** in settings panel Actions section (NOT inside opencode-settings-modal)
   - Icon: `bi-terminal`
   - Label: "Terminal"
   - Position: alongside existing action buttons (File Browser, OpenCode, etc.)
   - Click → opens flask-terminal modal

2. **Flask-terminal modal** (`#flask-terminal-modal`)
   - Fullscreen overlay (~99vw × 99vh), same pattern as file-browser modal
   - Catppuccin Mocha dark theme wrapper (#1e1e2e background, #313244 header)
   - Header: terminal icon + "Terminal" title + close button
   - Body: iframe pointing to `/flask-terminal/` (flask-terminal's built-in page)
   - iframe fills 100% of modal body
   - ESC key closes modal
   - Window resize triggers iframe content refresh (if needed)

3. **flask-terminal blueprint integration**
   - `pip install flask-terminal`
   - Register blueprint with `url_prefix='/flask-terminal'`
   - Add `@terminal_blueprint.before_request` auth guard using `session["email"]`
   - Register in `endpoints/__init__.py` alongside other blueprints

4. **Enhancements to flask-terminal** (fork or monkey-patch):
   - **Per-user session isolation**: Each authenticated user gets their own PTY session (keyed by email). Concurrent users don't interfere.
   - **Configurable shell**: Use `TERMINAL_SHELL` env var or `$SHELL` instead of hardcoded `/bin/sh`
   - **Terminal resize**: Add `/flask-terminal/resize` route accepting `{cols, rows}` JSON. Call `fcntl.ioctl(fd, termios.TIOCSWINSZ, ...)` on the PTY master fd.
   - **Faster polling**: Reduce polling interval from 1000ms to 150ms for acceptable interactivity
   - **Larger read buffer**: Increase from 1024 bytes to 16384 for better throughput on large output
   - **Session cleanup**: Cleanup PTY when user session expires or on `/flask-terminal/stop`

5. **Deprecate Approach C**:
   - Remove the "Terminal" button from `#opencode-settings-modal` (`#opencode-open-terminal-button`)
   - Remove the "Terminal" button in settings panel that calls `_showTerminalModal` (`#settings-opencode-terminal-button`)
   - Keep `#terminal-modal`, `opencode-terminal.js`, and `endpoints/terminal.py` WebSocket handler in code but mark deprecated (remove in Phase 2)

#### Phase 2: ttyd (Production WebSocket Terminal)

6. **New "Terminal (Pro)" button** in settings panel Actions section
   - Icon: `bi-terminal-fill` (filled variant to distinguish from Phase 1)
   - Label: "Terminal (Pro)"
   - Only visible when ttyd is available (feature flag or server-side check)
   - Click → opens ttyd-terminal modal

7. **ttyd-terminal modal** (`#ttyd-terminal-modal`)
   - Same fullscreen overlay pattern as flask-terminal modal
   - Same Catppuccin Mocha theme wrapper
   - Body: iframe pointing to `/ttyd/` (ttyd's built-in page, proxied via nginx)
   - iframe fills 100% of modal body

8. **ttyd server setup**
   - Install: `brew install ttyd` (macOS) / `apt install ttyd` (production)
   - Start command:
     ```
     ttyd -i /tmp/ttyd.sock \
          -H X-WEBAUTH-USER \
          -W \
          -b /ttyd \
          -w $PROJECT_DIR \
          -t fontSize=14 \
          -t 'theme={"background":"#1e1e2e","foreground":"#cdd6f4"}' \
          bash
     ```
   - Process management: systemd service (production) or manual (dev)

9. **nginx configuration for ttyd**
   - Auth subrequest to existing `/ext/auth/verify` endpoint
   - WebSocket proxy headers (Upgrade, Connection)
   - Unix socket proxy to ttyd

10. **Flask auth endpoint for ttyd** (reuse existing)
    - `/ext/auth/verify` already returns 200 + `{email}` if authenticated, 401 if not
    - Add `X-WEBAUTH-USER` response header with email for nginx to forward to ttyd

11. **Feature detection endpoint**
    - `GET /api/terminal/capabilities` → returns `{"flask_terminal": true, "ttyd": true/false}`
    - Frontend checks on settings panel load to show/hide ttyd button

### Non-Functional

- No new JS frameworks — jQuery + Bootstrap 4.6 only (modals are raw DOM, matching existing terminal-modal pattern)
- No new Python dependencies besides `flask-terminal` (Phase 1) and ttyd binary (Phase 2)
- Follow existing blueprint registration pattern in `endpoints/__init__.py`
- Follow existing settings panel button pattern (col + btn-sm rounded-pill)
- Security: `login_required` equivalent on all terminal routes, no anonymous access
- All terminal activity is per-user — no shared sessions

---

## Existing Patterns to Follow

### Settings Panel Button (interface.html, Actions section, ~line 2185-2200)
```html
<div class="col">
    <button class="btn btn-outline-info btn-sm rounded-pill w-100" id="settings-flask-terminal-button">
        <i class="bi bi-terminal"></i> Terminal
    </button>
</div>
```

### Fullscreen Modal (same pattern as file-browser-modal and terminal-modal)
```html
<div id="flask-terminal-modal" tabindex="-1" role="dialog"
     style="display:none; z-index:100000 !important; position:fixed;
            top:0; left:0; right:0; bottom:0;">
  <div class="modal-dialog" style="max-width:99vw; margin:0.5vh auto;">
    <div class="modal-content" style="height:99vh; background:#1e1e2e;">
      <div class="modal-header" style="background:#313244;">
        <!-- title + close button -->
      </div>
      <div class="modal-body" style="height:calc(100% - 40px); padding:0;">
        <iframe src="/flask-terminal/" style="width:100%;height:100%;border:none;"></iframe>
      </div>
    </div>
  </div>
</div>
```

### Blueprint Registration (endpoints/__init__.py)
```python
from flask_terminal import terminal_blueprint
# ... in register_blueprints():
app.register_blueprint(terminal_blueprint, url_prefix='/flask-terminal')
```

### Auth Guard (before_request pattern)
```python
from endpoints.auth import login_required
from flask import session, redirect

@terminal_blueprint.before_request
def require_auth():
    if not session.get('email') or not session.get('name'):
        return redirect('/login')
```

### Document-Level Click Handler (matching existing delegated handler pattern)
```javascript
document.addEventListener('click', function(event) {
    var btn = event.target.closest('#settings-flask-terminal-button');
    if (!btn) return;
    event.preventDefault();
    event.stopPropagation();
    showFlaskTerminalModal();
});
```

---

## nginx Configuration (Phase 2 — ttyd)

### Auth Subrequest Endpoint

Reuse existing `/ext/auth/verify` endpoint. Enhance it to return the user email in a response header:

```python
# endpoints/ext_auth.py — modify ext_verify()
@ext_auth_bp.route("/ext/auth/verify", methods=["GET", "POST"])
@limiter.limit("100 per minute")
def ext_verify():
    email = session.get("email")
    if email:
        resp = jsonify({"valid": True, "email": email})
        resp.headers["X-WEBAUTH-USER"] = email  # NEW: for nginx auth_request_set
        return resp
    return jsonify({"valid": False}), 401
```

### nginx Location Blocks

```nginx
# ── Flask app (existing) ──
location / {
    proxy_pass http://localhost:5000;
    proxy_read_timeout 3600;
    proxy_connect_timeout 300;
    proxy_send_timeout 3600;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
}

# ── Internal auth subrequest (for ttyd) ──
location = /_auth/verify {
    internal;  # only accessible via auth_request, not directly
    proxy_pass http://localhost:5000/ext/auth/verify;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header Cookie $http_cookie;  # forward session cookie
}

# ── ttyd terminal (WebSocket) ──
location ~ ^/ttyd(.*)$ {
    # Authenticate via Flask session
    auth_request /_auth/verify;
    auth_request_set $auth_user $upstream_http_x_webauth_user;

    # Forward auth identity to ttyd
    proxy_set_header X-WEBAUTH-USER $auth_user;

    # WebSocket support (critical)
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Long-lived connection timeouts
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;

    # Proxy to ttyd (unix socket for security)
    proxy_pass http://unix:/tmp/ttyd.sock:/$1;
}
```

### Cookie Forwarding Note

The `auth_request` subrequest must forward the session cookie to Flask so Flask can validate the session. The `proxy_set_header Cookie $http_cookie;` line in `/_auth/verify` handles this. Without it, Flask sees an anonymous request and returns 401.

### ttyd systemd Service (Production)

```ini
[Unit]
Description=ttyd Web Terminal
After=network.target

[Service]
Type=simple
User=www-data
ExecStart=/usr/local/bin/ttyd \
    -i /tmp/ttyd.sock \
    -H X-WEBAUTH-USER \
    -W \
    -b /ttyd \
    -w /home/user/workspace \
    -t fontSize=14 \
    -t 'theme={"background":"#1e1e2e","foreground":"#cdd6f4","cursor":"#f5e0dc"}' \
    -t disableLeaveAlert=true \
    -t disableReconnect=true \
    bash
ExecStartPost=/bin/sh -c 'chmod 660 /tmp/ttyd.sock; chown www-data:www-data /tmp/ttyd.sock'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Implementation Plan

### Phase 1: flask-terminal Integration

#### Milestone 1.1: Backend — Install and Enhance flask-terminal

| # | Task | Files | Est. |
|---|------|-------|------|
| 1.1.1 | `pip install flask-terminal` and verify import works | requirements.txt or pip | 2 min |
| 1.1.2 | Create `endpoints/flask_terminal_integration.py` — wrapper module that imports `terminal_blueprint`, adds `before_request` auth guard, enhances with per-user sessions, resize support, configurable shell, faster polling | New file | 30 min |
| 1.1.3 | Register the enhanced blueprint in `endpoints/__init__.py` with `url_prefix='/flask-terminal'` | `endpoints/__init__.py` | 2 min |
| 1.1.4 | Test: visit `/flask-terminal/` while logged in → terminal page loads. Visit while logged out → redirect to login. | Manual | 5 min |

#### Milestone 1.1 Detail: `endpoints/flask_terminal_integration.py`

This module wraps flask-terminal's blueprint and adds our enhancements:

```python
"""
Flask-terminal integration with per-user sessions, auth, resize, and configurable shell.

Wraps the flask-terminal blueprint to add:
- Authentication via Flask session (login_required equivalent)
- Per-user PTY session isolation (keyed by session email)
- Terminal resize support (TIOCSWINSZ)
- Configurable shell (TERMINAL_SHELL env var)
- Faster polling interval (150ms instead of 1000ms)
- Larger read buffer (16KB instead of 1KB)
"""
import os
import pty
import select
import struct
import fcntl
import termios
import signal
import logging
from flask import Blueprint, jsonify, request, session, render_template_string
from endpoints.auth import login_required

logger = logging.getLogger(__name__)

flask_terminal_bp = Blueprint('flask_terminal', __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/flask-terminal/static'
)

# Per-user terminal sessions: {email: TerminalSession}
_sessions = {}

class TerminalSession:
    """Manages a single PTY session for one user."""
    def __init__(self, shell=None, cwd=None):
        # ... PTY spawn with configurable shell
    def read_output(self):
        # ... select + os.read with 16KB buffer
    def write_input(self, data):
        # ... os.write to master_fd
    def resize(self, cols, rows):
        # ... fcntl.ioctl TIOCSWINSZ
    def cleanup(self):
        # ... kill process, close fds

# Routes: /, /init, /execute, /poll, /resize, /stop
```

**Key decision**: We write our OWN blueprint inspired by flask-terminal rather than monkey-patching theirs. Their code is 100 lines of Python — it's simpler to write a clean version with our enhancements than to patch a package that has fundamental design issues (single global session, no resize, hardcoded shell). We still `pip install flask-terminal` for reference and its static/template files, but our blueprint handles the backend logic.

**Alternative**: If we want to reuse flask-terminal's JS and HTML directly, we can import their blueprint for the frontend routes (`/` serving the HTML page) but override the backend routes (`/init`, `/execute`, `/poll`, `/stop`) in our own blueprint registered at the same prefix. Flask blueprint route precedence gives our routes priority.

#### Milestone 1.2: Frontend — Modal + Button

| # | Task | Files | Est. |
|---|------|-------|------|
| 1.2.1 | Add "Terminal" button in settings panel Actions section (new col+button, id=`settings-flask-terminal-button`) | `interface/interface.html` (~line 2197) | 5 min |
| 1.2.2 | Add `#flask-terminal-modal` HTML (fullscreen, iframe to `/flask-terminal/`, Catppuccin theme) after existing terminal-modal | `interface/interface.html` (~line 2560) | 10 min |
| 1.2.3 | Add `showFlaskTerminalModal()` / `closeFlaskTerminalModal()` functions in a new `interface/flask-terminal-modal.js` file | New file | 15 min |
| 1.2.4 | Add document-level delegated click handler for `#settings-flask-terminal-button` | `interface/interface.html` or `flask-terminal-modal.js` | 5 min |
| 1.2.5 | Load `flask-terminal-modal.js` via script tag in interface.html | `interface/interface.html` | 2 min |
| 1.2.6 | Test: click Terminal button → modal opens with iframe → terminal works → ESC closes | Manual | 5 min |

#### Milestone 1.2 Detail: `interface/flask-terminal-modal.js`

```javascript
/**
 * Flask Terminal Modal — manages the fullscreen modal that embeds
 * the flask-terminal page in an iframe.
 *
 * Separate from the old WebSocket-based terminal (opencode-terminal.js).
 * Uses HTTP polling (no WebSocket) via the flask-terminal blueprint.
 */
(function() {
    'use strict';

    function showFlaskTerminalModal() {
        var modal = document.getElementById('flask-terminal-modal');
        if (!modal) return;
        modal.style.display = 'block';
        modal.classList.add('show');
        modal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
        // The iframe auto-initializes the terminal on load
    }

    function closeFlaskTerminalModal() {
        var modal = document.getElementById('flask-terminal-modal');
        if (!modal) return;
        modal.classList.remove('show');
        modal.style.display = 'none';
        modal.setAttribute('aria-hidden', 'true');
        // Cleanup orphan backdrops
        if ($('.modal.show').length === 0) {
            document.body.classList.remove('modal-open');
            $('.modal-backdrop').remove();
        }
    }

    // Expose globally
    window.showFlaskTerminalModal = showFlaskTerminalModal;
    window.closeFlaskTerminalModal = closeFlaskTerminalModal;
})();
```

#### Milestone 1.3: Deprecate Approach C

| # | Task | Files | Est. |
|---|------|-------|------|
| 1.3.1 | Remove `#settings-opencode-terminal-button` from settings panel (the old Terminal button) | `interface/interface.html` (~line 2195) | 2 min |
| 1.3.2 | Remove `#opencode-open-terminal-button` from opencode-settings-modal | `interface/interface.html` (~line 2516) | 2 min |
| 1.3.3 | Remove document-level click handler for old terminal button | `interface/interface.html` (~line 3301) | 2 min |
| 1.3.4 | Remove `_showTerminalModal`, `_closeTerminalModal`, terminal handlers from chat.js | `interface/chat.js` (~lines 375-404, 846-932) | 5 min |
| 1.3.5 | Add deprecation comment to `endpoints/terminal.py` and `interface/opencode-terminal.js` (don't delete yet — safety net) | Both files | 2 min |
| 1.3.6 | Remove old `#terminal-modal` HTML | `interface/interface.html` (~lines 2529-2556) | 2 min |
| 1.3.7 | Verify no references to old terminal remain in active code paths | grep | 5 min |

#### Milestone 1.4: Cleanup and Verify

| # | Task | Files | Est. |
|---|------|-------|------|
| 1.4.1 | Clean up debug code from flask_sock `__init__.py` (revert debug instrumentation from prior sessions) | `/site-packages/flask_sock/__init__.py` | 5 min |
| 1.4.2 | Clean up debug code from `endpoints/terminal.py` (remove duplicate imports + debug prints) | `endpoints/terminal.py` | 5 min |
| 1.4.3 | Restart Flask server, test full flow: login → settings → Terminal button → terminal works | Manual | 5 min |
| 1.4.4 | Test: multiple commands, terminal resize (if implemented), CTRL+C, exit | Manual | 5 min |
| 1.4.5 | Update documentation | `documentation/features/` | 10 min |

### Phase 2: ttyd Production Terminal

#### Milestone 2.1: ttyd Server Setup

| # | Task | Files | Est. |
|---|------|-------|------|
| 2.1.1 | Install ttyd: `brew install ttyd` (macOS) or download binary (Linux) | System | 2 min |
| 2.1.2 | Test ttyd locally: `ttyd -p 7681 -W bash` → visit `http://localhost:7681` | Manual | 2 min |
| 2.1.3 | Configure ttyd for production: unix socket, auth-header, base-path, theme | Startup script or systemd | 10 min |
| 2.1.4 | Create systemd service file for ttyd (see nginx section above) | `/etc/systemd/system/ttyd.service` | 10 min |

#### Milestone 2.2: nginx auth_request Setup

| # | Task | Files | Est. |
|---|------|-------|------|
| 2.2.1 | Enhance `/ext/auth/verify` to return `X-WEBAUTH-USER` header with email | `endpoints/ext_auth.py` | 5 min |
| 2.2.2 | Add `/_auth/verify` internal location block to nginx config | nginx config | 5 min |
| 2.2.3 | Add `/ttyd` location block with `auth_request` + WebSocket proxy to unix socket | nginx config | 10 min |
| 2.2.4 | Test nginx config: `sudo nginx -t` | Manual | 2 min |
| 2.2.5 | Reload nginx: `sudo systemctl reload nginx` | Manual | 1 min |
| 2.2.6 | Test: visit `/ttyd/` while logged in → terminal works. While logged out → 401. | Manual | 5 min |

#### Milestone 2.3: Frontend — ttyd Modal + Button

| # | Task | Files | Est. |
|---|------|-------|------|
| 2.3.1 | Add feature detection endpoint `GET /api/terminal/capabilities` | `endpoints/flask_terminal_integration.py` | 10 min |
| 2.3.2 | Add "Terminal (Pro)" button in settings panel (hidden by default, shown when ttyd available) | `interface/interface.html` | 5 min |
| 2.3.3 | Add `#ttyd-terminal-modal` HTML (same pattern as flask-terminal modal, iframe to `/ttyd/`) | `interface/interface.html` | 10 min |
| 2.3.4 | Add `showTtydTerminalModal()` / `closeTtydTerminalModal()` in `interface/ttyd-terminal-modal.js` | New file | 15 min |
| 2.3.5 | Add click handler and feature-flag check on settings panel load | `interface/ttyd-terminal-modal.js` | 10 min |
| 2.3.6 | Test full flow: login → settings → Terminal (Pro) → ttyd terminal in modal | Manual | 5 min |

#### Milestone 2.4: Full Cleanup

| # | Task | Files | Est. |
|---|------|-------|------|
| 2.4.1 | Delete deprecated Approach C files: `endpoints/terminal.py` (WebSocket handler), `interface/opencode-terminal.js`, `interface/terminal.html` | Multiple | 5 min |
| 2.4.2 | Remove `terminal_bp` import and registration from `endpoints/__init__.py` | `endpoints/__init__.py` | 2 min |
| 2.4.3 | Remove flask-sock dependency if no longer used elsewhere | `requirements.txt` | 2 min |
| 2.4.4 | Revert `simple_websocket/ws.py` PerMessageDeflate patch (no longer needed) | Site-packages | 2 min |
| 2.4.5 | Update all documentation | `documentation/` | 15 min |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| flask-terminal polling too slow for interactive programs (vim, htop) | High | Medium | Phase 2 (ttyd) fixes this. flask-terminal is for basic command execution. Document the limitation. |
| flask-terminal single global session causes user interference | Certain (if unpatched) | High | Milestone 1.1.2 — we write our own enhanced blueprint with per-user sessions. |
| flask-terminal no resize causes wrapped/truncated output | Certain (if unpatched) | Medium | Milestone 1.1.2 — add resize route + ioctl. |
| ttyd unix socket permission issues | Medium | Low | systemd ExecStartPost sets correct ownership. Document troubleshooting. |
| nginx auth_request doesn't forward session cookie | Medium | High | Explicitly add `proxy_set_header Cookie $http_cookie;` in `/_auth/verify` location. |
| iframe CSP/X-Frame-Options blocks embedding | Low | Medium | flask-terminal serves from same origin (no CSP issue). ttyd behind nginx same origin. |
| Users expect interactive TUI support (vim, opencode) | Medium | Medium | Document: flask-terminal = basic commands only. ttyd = full TUI support. |

---

## Files Modified / Created

### Phase 1 (flask-terminal)

| File | Action | Description |
|------|--------|-------------|
| `endpoints/flask_terminal_integration.py` | **CREATE** | Enhanced flask-terminal blueprint with auth, per-user sessions, resize, configurable shell |
| `endpoints/__init__.py` | EDIT | Register `flask_terminal_bp` blueprint |
| `interface/interface.html` | EDIT | Add Terminal button in settings, add `#flask-terminal-modal` HTML, remove old terminal button/modal |
| `interface/flask-terminal-modal.js` | **CREATE** | Modal open/close functions + click handler |
| `interface/chat.js` | EDIT | Remove old terminal functions (`_showTerminalModal`, `_closeTerminalModal`, handlers) |
| `endpoints/terminal.py` | EDIT | Add deprecation comment (don't delete yet) |
| `interface/opencode-terminal.js` | EDIT | Add deprecation comment (don't delete yet) |

### Phase 2 (ttyd)

| File | Action | Description |
|------|--------|-------------|
| `endpoints/ext_auth.py` | EDIT | Add `X-WEBAUTH-USER` header to `/ext/auth/verify` response |
| `endpoints/flask_terminal_integration.py` | EDIT | Add `/api/terminal/capabilities` endpoint |
| `interface/interface.html` | EDIT | Add ttyd button + `#ttyd-terminal-modal` HTML |
| `interface/ttyd-terminal-modal.js` | **CREATE** | ttyd modal open/close + feature detection |
| nginx config (production) | EDIT | Add `/_auth/verify` + `/ttyd` location blocks |
| `/etc/systemd/system/ttyd.service` | **CREATE** | systemd service for ttyd (production) |
| `endpoints/terminal.py` | DELETE | Remove deprecated Approach C WebSocket handler |
| `interface/opencode-terminal.js` | DELETE | Remove deprecated Approach C JS client |
| `interface/terminal.html` | DELETE | Remove deprecated standalone terminal page |