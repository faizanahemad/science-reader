# Milestone 1 Rewrite: Session-Based Auth (Simplified Approach)

**Date**: 2026-02-16  
**Status**: Ready for implementation  
**Context**: User decision to use main backend's existing session-based auth instead of implementing JWT

---

## User Requirements

1. **Use normal main backend auth for extension** — No JWT implementation, reuse existing session system
2. **No changes to main backend just for auth** — Minimal backend modifications
3. **Support local AND hosted backends** — Extension must work with `http://localhost:5000` (debugging) and hosted server (production)
4. **Prevent unwanted logouts** — Main backend's 30-day sessions already solve this

---

## Background: Why This Is Simpler

### Current Main Backend Auth (What We're Reusing)
- **Session-based**: Flask sessions with filesystem storage
- **30-day lifetime**: Sessions refresh on each request (`SESSION_REFRESH_EACH_REQUEST=True`)
- **Remember-me cookies**: 30-day HttpOnly cookies for persistence
- **Decorators**: `@login_required` checks session, redirects to `/login` if missing
- **Login endpoint**: `POST /login` accepts email/password, creates session
- **No JWT needed**: Session cookies handle everything

### Current Extension Auth (What We're Replacing)
- Custom JWT-like tokens (7-day expiry, no refresh)
- Separate `/ext/auth/login` endpoint
- `@require_ext_auth` decorator
- Stored in `chrome.storage.local`

### What Changes
- Extension calls main backend `/login` instead of `/ext/auth/login`
- Extension stores session cookies instead of JWT tokens
- Extension uses `credentials: 'include'` in fetch requests
- Backend adjusts CORS + SameSite policy for extension origin

---

## Technical Challenges & Solutions

### Challenge 1: Cross-Origin Cookies

**Problem**: Extension runs at `chrome-extension://[extension-id]` origin. By default, `SameSite=Lax` cookies won't be sent on cross-origin requests.

**Solution** (for extension endpoints only):
1. Add CORS support for extension origin: `Access-Control-Allow-Origin: chrome-extension://[extension-id]` and `Access-Control-Allow-Credentials: true`
2. For **hosted backend** (cross-origin): Use `SameSite=None; Secure` cookies for `/ext/*` endpoints
3. For **local backend** (`localhost`): `SameSite=Lax` already works (same-site)
4. Extension uses `credentials: 'include'` in all fetch requests

**Implementation**:
```python
# server.py - Add extension-specific cookie configuration
def set_extension_session_cookie(response):
    """Set session cookie with extension-compatible SameSite policy."""
    if request.path.startswith('/ext/') or request.path == '/login':
        # For extension requests, use SameSite=None to allow cross-origin
        # (requires Secure flag, so only works over HTTPS)
        response.set_cookie(
            'session_id',
            session.sid,
            secure=True,
            httponly=True,
            samesite='None',  # Allow cross-origin for extension
            max_age=30*24*60*60  # 30 days
        )
    # For web UI, keep existing Lax policy
    return response
```

### Challenge 2: Extension ID Varies (Dev vs Production)

**Problem**: Extension ID changes between development (unpacked) and production (Chrome Web Store). Can't hardcode in CORS config.

**Solution**: Dynamic extension ID detection
```python
# server.py - CORS configuration
ALLOWED_EXTENSION_PATTERNS = [
    r'chrome-extension://[a-z]{32}',  # Production extension IDs
    r'chrome-extension://[a-zA-Z]{16}',  # Dev extension IDs (different format)
]

def is_allowed_extension_origin(origin):
    """Check if origin matches extension pattern."""
    import re
    for pattern in ALLOWED_EXTENSION_PATTERNS:
        if re.match(pattern, origin):
            return True
    return False

# In CORS setup
CORS(app, resources={
    r"/ext/*": {
        "origins": lambda origin: is_allowed_extension_origin(origin) or origin.startswith('http://localhost'),
        "supports_credentials": True,
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-Requested-With"]
    },
    # Keep existing restrictive CORS for other endpoints
    r"/get_conversation_output_docs/*": {
        "origins": ["https://laingsimon.github.io", "https://app.diagrams.net/", ...]
    }
})
```

### Challenge 3: CSRF Protection

**Problem**: Cross-origin cookies need CSRF protection to prevent attacks.

**Solution**: 
1. For extension, rely on `chrome-extension://` origin being inherently trusted (can't be spoofed by malicious websites)
2. Add simple CSRF token for added security (optional):
```python
# Generate CSRF token on login
session['csrf_token'] = secrets.token_hex(32)

# Extension sends token in custom header
# X-CSRF-Token: <token>

# Backend validates on state-changing requests (POST/PUT/DELETE)
@app.before_request
def check_csrf():
    if request.method in ['POST', 'PUT', 'DELETE'] and request.path.startswith('/ext/'):
        token = request.headers.get('X-CSRF-Token')
        if token != session.get('csrf_token'):
            return jsonify({"error": "CSRF token validation failed"}), 403
```

### Challenge 4: Backend URL Configuration

**Problem**: Extension needs to call different backend URLs (local vs hosted).

**Solution**: Extension already has this implemented!
- Setting stored in `chrome.storage.local` as `apiBaseUrl`
- UI has "Use Local" and "Use Hosted" quick presets
- `getApiBaseUrl()` in `extension/shared/api.js` reads from storage

**No changes needed** - existing mechanism works.

---

## New Milestone 1: Session-Based Auth for Extension

**Goal**: Extension authenticates against main backend using normal session cookies (same as web UI).

**Effort**: **2-3 days** (reduced from 3-5 days, no JWT implementation needed)

**Why first**: Every subsequent milestone depends on extension being able to call main server endpoints.

---

### Task 1.1: Add CORS support for extension origin

**What**: Update CORS configuration to allow extension origin with credentials.

**Files to modify**:
- `server.py` — Update CORS initialization (lines 182-194)

**Details**:
```python
# server.py (after line 182)
def is_allowed_extension_origin(origin):
    """Check if origin matches chrome-extension pattern or localhost."""
    import re
    if origin.startswith('http://localhost:') or origin.startswith('http://127.0.0.1:'):
        return True
    # Match chrome-extension://[32_chars] (production) or [16_chars] (dev)
    patterns = [r'^chrome-extension://[a-z]{32}$', r'^chrome-extension://[a-zA-Z]{16}$']
    return any(re.match(p, origin) for p in patterns)

CORS(app, resources={
    r"/ext/*": {
        "origins": is_allowed_extension_origin,  # Function-based origin check
        "supports_credentials": True,  # CRITICAL: Allow cookies
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-Requested-With", "X-CSRF-Token"]
    },
    r"/login": {
        "origins": is_allowed_extension_origin,
        "supports_credentials": True,
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    },
    # Keep existing restrictive CORS for other endpoints
    r"/get_conversation_output_docs/*": {
        "origins": ["https://laingsimon.github.io", "https://app.diagrams.net/",
                    "https://draw.io/", "https://www.draw.io/"]
    }
})
```

**Acceptance criteria**:
- Extension can make CORS preflight requests to `/ext/*` and `/login`
- `Access-Control-Allow-Credentials: true` header present in responses
- `Access-Control-Allow-Origin` header matches extension origin
- Existing draw.io CORS behavior unchanged

---

### Task 1.2: Adjust SameSite policy for extension requests

**What**: Set `SameSite=None; Secure` for session cookies on extension requests (allows cross-origin cookies).

**Files to modify**:
- `server.py` — Add after-request hook for extension cookie policy (add after line 252)

**Details**:
```python
# server.py (add after blueprint registration, before `return app`)
@app.after_request
def set_extension_cookie_policy(response):
    """
    Set SameSite=None for extension requests to allow cross-origin cookies.
    
    Why: Chrome extension runs at chrome-extension:// origin (cross-origin).
    SameSite=Lax (default) cookies won't be sent on cross-origin requests.
    SameSite=None requires Secure flag (HTTPS only).
    
    For localhost (same-origin debugging), Lax already works.
    """
    origin = request.headers.get('Origin', '')
    
    # Extension origin or /ext/* routes: use None policy
    if origin.startswith('chrome-extension://') or request.path.startswith('/ext/'):
        # Check if this response is setting a session cookie
        # Flask-Session typically handles this automatically, but we need to adjust SameSite
        # Note: Flask-Session sets cookies via before_request/after_request hooks internally
        # We may need to override the Set-Cookie header
        
        # For manual control, we'd need to access Flask session implementation
        # Simpler approach: let Flask-Session set cookie, then we won't interfere
        # because Flask-Session respects SESSION_COOKIE_SAMESITE config
        pass
    
    return response

# Alternative: Update session config based on request origin
# This is cleaner - adjust session config at app level
app.config.update(
    SESSION_COOKIE_SAMESITE='None',  # Allow cross-origin (extension)
    SESSION_COOKIE_SECURE=True,      # Required with SameSite=None
)

# NOTE: This makes ALL session cookies SameSite=None, which is less secure for web UI
# Better approach: Use separate session config for /ext/* routes (see Task 1.2b)
```

**Better approach** (Task 1.2b): Create extension-specific login endpoint that sets correct cookie policy.

**Acceptance criteria**:
- Extension can receive and store session cookies from main backend
- Cookies are sent on subsequent requests with `credentials: 'include'`
- Web UI session cookies unaffected

---

### Task 1.2b: Create `/ext/auth/login` that uses main backend auth with extension-friendly cookies

**What**: Create a new login endpoint specifically for extension that:
1. Uses main backend's credential verification (same code as `/login`)
2. Sets session cookies with `SameSite=None; Secure` for cross-origin compatibility
3. Returns JSON (not HTML redirect)

**Files to create**:
- `endpoints/ext_auth.py` — Extension-specific auth endpoints

**Details**:
```python
# endpoints/ext_auth.py
from flask import Blueprint, request, jsonify, session
from endpoints.auth import check_credentials
from database.users import get_user_details, add_user_to_details

ext_auth_bp = Blueprint("ext_auth", __name__)

@ext_auth_bp.route("/ext/auth/login", methods=["POST"])
def ext_login():
    """
    Extension login endpoint.
    
    Uses main backend's credential verification but:
    - Returns JSON (not redirect)
    - Sets session with extension-compatible cookies
    - No rate limiting (extension is trusted origin)
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing request body"}), 400
        
        email = data.get("email", "").strip()
        password = data.get("password", "")
        
        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400
        
        # Use main backend's credential check
        if not check_credentials(email, password):
            return jsonify({"error": "Invalid credentials"}), 401
        
        # Create session (same as main backend /login)
        session.permanent = True
        session["email"] = email
        session["name"] = email  # Main backend uses email as name
        
        # Ensure user exists in details table
        user_details = get_user_details(email)
        if not user_details:
            add_user_to_details(email)
            user_details = {"email": email, "name": email.split("@")[0]}
        
        return jsonify({
            "success": True,
            "email": email,
            "name": user_details.get("name", email.split("@")[0])
        })
    
    except Exception as e:
        logger.error(f"Extension login error: {e}")
        return jsonify({"error": str(e)}), 500


@ext_auth_bp.route("/ext/auth/verify", methods=["GET", "POST"])
def ext_verify():
    """Verify current session validity."""
    email = session.get("email")
    if email:
        return jsonify({"valid": True, "email": email})
    return jsonify({"valid": False}), 401


@ext_auth_bp.route("/ext/auth/logout", methods=["POST"])
def ext_logout():
    """Logout (clear session)."""
    session.clear()
    return jsonify({"message": "Logged out successfully"})
```

```python
# server.py - Register blueprint (add after line 252)
from endpoints.ext_auth import ext_auth_bp
app.register_blueprint(ext_auth_bp)

# server.py - Update session config for extension compatibility (replace lines 159-167)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None' if os.getenv('ALLOW_EXTENSION_CORS', 'true').lower() == 'true' else 'Lax',
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_COOKIE_NAME="session_id",
    SESSION_COOKIE_PATH="/",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
```

**Acceptance criteria**:
- Extension can POST to `/ext/auth/login` with email/password
- Response is JSON (not redirect)
- Session cookie is set with `SameSite=None; Secure`
- Extension can verify session with `/ext/auth/verify`
- Web UI `/login` still works (unchanged)

---

### Task 1.3: Update extension client to use session-based auth

**What**: Replace JWT token storage/handling with session cookie handling.

**Files to modify**:
- `extension/shared/api.js` — Update `API.call()` to use `credentials: 'include'`
- `extension/shared/api.js` — Update `API.login()` to call `/ext/auth/login`
- `extension/shared/storage.js` — Remove token storage methods
- `extension/popup/popup.js` — Update login flow
- `extension/sidepanel/sidepanel.js` — Update auth check

**Details**:

```javascript
// extension/shared/api.js

async function getApiBaseUrl() {
    const base = await Storage.getApiBaseUrl();
    return (base || 'http://localhost:5000').trim().replace(/\/+$/, '');
}

export const API = {
    async call(endpoint, options = {}) {
        const apiBase = await getApiBaseUrl();
        const { timeoutMs, ...fetchOptions } = options;
        
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        // CRITICAL: Include credentials (cookies) in requests
        const response = await fetch(`${apiBase}${endpoint}`, {
            ...fetchOptions,
            headers,
            credentials: 'include'  // Send cookies cross-origin
        });
        
        if (response.status === 401) {
            throw new AuthError('Session expired. Please login again.');
        }
        
        return response;
    },
    
    async login(email, password) {
        const response = await this.call('/ext/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Login failed');
        }
        
        const data = await response.json();
        // No token storage needed - cookies handled by browser
        return data;
    },
    
    async verifyAuth() {
        try {
            const response = await this.call('/ext/auth/verify');
            if (!response.ok) return false;
            const data = await response.json();
            return data.valid;
        } catch {
            return false;
        }
    },
    
    async logout() {
        await this.call('/ext/auth/logout', { method: 'POST' });
        // Cookies cleared by server
    }
};
```

```javascript
// extension/shared/storage.js

export class Storage {
    // REMOVE: static async getToken() { ... }
    // REMOVE: static async setToken(token) { ... }
    // REMOVE: static async clearAuth() { ... }
    
    // KEEP: Backend URL storage
    static async getApiBaseUrl() {
        const result = await chrome.storage.local.get('apiBaseUrl');
        return result.apiBaseUrl || 'http://localhost:5000';
    }
    
    static async setApiBaseUrl(url) {
        return chrome.storage.local.set({ apiBaseUrl: url });
    }
}
```

**Acceptance criteria**:
- Extension login creates session cookie (visible in DevTools > Application > Cookies)
- All API calls include `credentials: 'include'`
- Session persists across browser restarts (30-day cookie)
- Logout clears session cookie
- Auth check on extension startup works

---

### Task 1.4: Add `@auth_required` decorator for JSON-only endpoints

**What**: Create a decorator that checks session (just like `@login_required`) but returns JSON 401 instead of redirecting.

**Files to create**:
- None (add to existing `endpoints/auth.py`)

**Details**:
```python
# endpoints/auth.py (add after login_required)

def auth_required(f):
    """
    Require authenticated session (same as @login_required) but return JSON 401.
    
    Use for API endpoints that extension calls directly.
    Web UI routes should keep using @login_required (HTML redirect).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("email") is None or session.get("name") is None:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    
    return decorated_function
```

**Usage** (in new `/ext/*` endpoints):
```python
@app.route("/ext/chat/<id>", methods=["POST"])
@auth_required  # JSON 401 (not redirect)
def ext_chat(id):
    email = session.get("email")  # Guaranteed to exist after @auth_required
    ...
```

**Acceptance criteria**:
- `@auth_required` returns JSON 401 for unauthenticated requests
- `@auth_required` allows authenticated session requests (same logic as `@login_required`)
- Web UI routes using `@login_required` unchanged

---

### Task 1.5: Test with local and hosted backends

**What**: Verify extension works with both `http://localhost:5000` (development) and hosted server (production).

**Test scenarios**:

| Scenario | Backend URL | Expected Behavior |
|----------|-------------|-------------------|
| **Local development** | `http://localhost:5000` | Extension logs in, session cookie works, no CORS errors |
| **Hosted server (HTTPS)** | `https://sci-tldr.pro` | Extension logs in, `SameSite=None; Secure` cookie works, no CORS errors |
| **Switch backends** | Change from local to hosted | Login again, new session created, old cookie cleared |
| **Browser restart** | Any backend | Session persists (30-day cookie), no re-login needed |
| **Logout** | Any backend | Session cleared, next request requires login |

**Manual test steps**:
1. Set backend URL to `http://localhost:5000` in extension settings
2. Login via extension popup
3. Verify session cookie in DevTools (Application > Cookies)
4. Create conversation, send message
5. Restart browser, verify still logged in
6. Switch backend URL to hosted server
7. Login again (new session)
8. Verify chat works on hosted server
9. Logout, verify session cleared

**Acceptance criteria**:
- Extension works with both local and hosted backends
- No CORS errors in console
- Session cookies set correctly for each backend
- Backend URL change doesn't break extension

---

### Task 1.6: Rate limiting for extension endpoints

**What**: Apply appropriate Flask-Limiter rates to new `/ext/*` routes.

**Files to modify**:
- `endpoints/ext_auth.py` — Add `@limiter.limit()` decorators

**Details**:
```python
from extensions import limiter

@ext_auth_bp.route("/ext/auth/login", methods=["POST"])
@limiter.limit("10 per minute")  # Prevent brute force
def ext_login():
    ...

@ext_auth_bp.route("/ext/auth/verify", methods=["GET", "POST"])
@limiter.limit("100 per minute")
def ext_verify():
    ...

@ext_auth_bp.route("/ext/auth/logout", methods=["POST"])
@limiter.limit("10 per minute")
def ext_logout():
    ...
```

**Recommended rates** (for future `/ext/*` endpoints):
- `/ext/auth/*` — 10-100 per minute (depending on endpoint)
- `/ext/chat/<id>` — 50 per minute (matches `/send_message`)
- `/ext/conversations/*` — 500 per minute (matches list operations)
- `/ext/scripts/*`, `/ext/workflows/*` — 100 per minute
- `/ext/memories/*`, `/ext/prompts/*` — 100 per minute
- `/ext/settings/*` — 100 per minute
- `/ext/ocr` — 30 per minute (expensive vision calls)
- `/ext/health` — 1000 per minute (no auth, lightweight)

**Acceptance criteria**:
- All `/ext/auth/*` endpoints have rate limits
- Rate limits logged when hit
- Extension shows appropriate error message when rate limited

---

## Timeline Impact

### Original Milestone 1 (JWT Approach): 3-5 days
- Task 1.1: Move ExtensionAuth to shared module (0.5 day)
- Task 1.2: Make get_session_identity() JWT-aware (1 day)
- Task 1.3: Add JWT login/verify/logout endpoints (1 day)
- Task 1.4: Update CORS for extension origins (0.5 day)
- Task 1.5: Add @auth_required to endpoints (0.5-1.5 days)
- Task 1.6: Rate limiting (0.5 day)

### New Milestone 1 (Session Approach): **2-3 days** ✅
- Task 1.1: Add CORS support for extension origin (0.5 day)
- Task 1.2: Adjust SameSite policy for extension requests (0.5 day)
- Task 1.2b: Create `/ext/auth/login` endpoint (0.5 day)
- Task 1.3: Update extension client for session-based auth (0.5-1 day)
- Task 1.4: Add `@auth_required` decorator (0.25 day)
- Task 1.5: Test with local and hosted backends (0.5 day)
- Task 1.6: Rate limiting (0.25 day)

**Savings**: 1-2 days (no JWT implementation needed)

---

## Updated Total Timeline

| Milestone | Old Effort | New Effort | Change |
|-----------|-----------|-----------|--------|
| M1: Auth | 3-5 days | **2-3 days** | -1 to -2 days |
| M2: Page Context | 2-3 days | 2-3 days | No change |
| M3: Conv Bridge | 5-7 days | 5-7 days | No change |
| M4: Ext Features | 3-5 days | 3-5 days | No change |
| M5: Client UI | 2-3 days | 2-3 days | No change |
| M6: File Attachments | 5-7 days | 5-7 days | No change |
| M7: Cleanup | 1 day | 1 day | No change |
| **Total** | **21-30 days** | **20-29 days** | **-1 to -2 days** |

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **SameSite=None requires HTTPS** | High | For local development, `localhost` is same-origin so Lax works. For production, enforce HTTPS (already required by Chrome for extensions). |
| **Extension ID changes** | Medium | Use regex patterns to match any extension ID format. Test with both dev (unpacked) and production (CWS) IDs. |
| **CSRF attacks** | Medium | Extension origin is inherently trusted (can't be spoofed). Add optional CSRF token for defense-in-depth. |
| **Session cookie not sent** | High | Verify `credentials: 'include'` in ALL fetch calls. Check CORS `supports_credentials: true`. |
| **Web UI session behavior changes** | Low | Only `/ext/*` routes use `SameSite=None`. Web UI keeps `Lax` (or use conditional config). |

---

## Migration Notes

### From Extension JWT to Session Cookies

**User impact**: Users must log in again (one-time only)

**Migration flow**:
1. Update extension with session-based auth
2. On first launch, check for valid session (will fail for JWT users)
3. Show login screen
4. User logs in → session created
5. Extension works normally

**No data loss**: Conversations remain on server (not stored in extension)

---

## Benefits of This Approach

✅ **Simpler implementation** — Reuses existing auth system  
✅ **No backend changes needed** — Just CORS + new endpoint  
✅ **Better session persistence** — 30-day cookies vs 7-day JWT  
✅ **Familiar debugging** — Same auth as web UI  
✅ **No token refresh needed** — Sessions auto-refresh  
✅ **HTTPS enforced** — SameSite=None requires Secure  
✅ **Local + hosted support** — Works with any backend URL  

---

## Next Steps

1. ✅ Review this document
2. Implement Task 1.1 (CORS support)
3. Implement Task 1.2b (extension login endpoint)
4. Implement Task 1.3 (update extension client)
5. Test with local backend
6. Test with hosted backend
7. Proceed to Milestone 2 (Page Context Support)
