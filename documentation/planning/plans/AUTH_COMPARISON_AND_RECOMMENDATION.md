# Authentication Comparison & Recommendation for Extension Backend Unification

> **NOTE**: `extension_server.py` referenced in this document has been deprecated. The Chrome extension now uses `server.py` (port 5000). See `documentation/features/extension/` for current architecture.

**Date:** 2026-02-16  
**Updated:** 2026-02-16 (Final Decision)  
**Context:** Pre-Milestone 1 decision making  
**Goal:** Choose auth approach that prevents "being logged out every now and then"

---

## ⚠️ FINAL DECISION: SESSION-BASED AUTH (Updated 2026-02-16)

**User Decision**: Use main backend's existing session-based auth for extension. **NO JWT implementation.**

**Rationale**:
1. **"Use the normal main backend auth for extension as well"** — Reuse existing system
2. **"We don't want to make changes to main backend just for Auth"** — Minimize backend modifications
3. **"Extension supports using either local or hosted backend"** — Must work with configurable backend URL (already implemented)
4. **Simpler is better** — Session auth already solves the "don't log me out" problem (30-day sliding sessions)

**Implementation**: See `milestone_1_session_auth_rewrite.md` for complete rewrite.

---

## Executive Summary (Original Analysis — For Reference)

**Original Recommendation**: **Hybrid Authentication**
- Keep session-based auth (30-day sessions + remember-me cookies) for main web UI
- Implement proper JWT with refresh tokens for Chrome extension
- Make extension endpoints accept **EITHER** session cookies **OR** bearer tokens
- **Why**: Best balance of security, user experience, and minimal disruption

**Key Insight**: The "logged out every now and then" issue stems from **7-day JWT expiry with no refresh**, not from auth mechanism choice. Solution: implement **refresh tokens with automatic silent refresh**.

**STATUS**: ~~RECOMMENDED~~ → **SUPERSEDED BY SESSION-BASED AUTH** ✅

---

## Current State Analysis

### Main Backend (Session-Based)
- **Mechanism**: Flask sessions with filesystem storage
- **Transport**: Secure, HttpOnly, SameSite=Lax cookies
- **Lifetime**: 30 days, refreshed on each request
- **Persistence**: Remember-me tokens (30-day HttpOnly cookies, stored in JSON)
- **Validation**: `@login_required` checks `session["email"]`
- **Files**: `endpoints/auth.py`, `server.py` (lines 150-199)

### Extension (Token-Based)
- **Mechanism**: Custom JWT-like tokens (JSON + HMAC SHA256)
- **Transport**: `Authorization: Bearer` headers
- **Storage**: `chrome.storage.local`
- **Lifetime**: **7 days, NO refresh** ⚠️ (This causes unwanted logouts)
- **Validation**: `@require_ext_auth` checks token signature/expiry
- **Files**: `extension.py` (lines 56-264), `extension_server.py` (lines 788-906)

---

## Side-by-Side Comparison

| Aspect | Session Cookies (Main UI) | Current JWT (Extension) | JWT + Refresh Tokens (Proposed) |
|--------|---------------------------|-------------------------|----------------------------------|
| **Security vs XSS** | ✅ Excellent (HttpOnly) | ⚠️ Moderate (JS-readable storage) | ⚠️ Moderate (mitigated by rotation) |
| **Security vs CSRF** | ⚠️ Needs CSRF tokens | ✅ Immune (not auto-sent) | ✅ Immune (not auto-sent) |
| **Persistence** | ✅ Excellent (30-day sliding) | ❌ Poor (7-day hard expiry) | ✅ Excellent (silent refresh) |
| **Browser Restarts** | ✅ Survives (server-side storage) | ⚠️ Requires re-login after 7 days | ✅ Survives (refresh token persists) |
| **Extension Updates** | ❌ Unreliable (cookie issues) | ⚠️ Token persists but expires | ✅ Refresh token survives |
| **Multi-Device** | ✅ Per-browser profile | ✅ Per-extension install | ✅ Per-extension install |
| **Network Issues** | ✅ No impact on auth | ✅ No impact on auth | ✅ No impact on auth |
| **Implementation Effort** | ✅ Already done | ✅ Already done | ⚠️ Medium (1-2 days) |
| **User Experience** | ✅ Seamless | ❌ Forced logout every 7 days | ✅ Seamless (silent refresh) |

---

## Root Cause of "Logged Out Every Now and Then"

**Current Extension Behavior**:
1. User logs in → receives JWT token valid for 7 days
2. Extension stores token in `chrome.storage.local`
3. After 7 days, token expires
4. Next API call fails with 401 Unauthorized
5. **User is forced to log in again** ❌

**Why 7 days?**
- `TOKEN_EXPIRY_HOURS = 24 * 7` in `extension.py` line 59
- No refresh mechanism → hard expiry

**Fix**: Implement refresh tokens with automatic silent refresh (see implementation plan below)

---

## Industry Best Practice: Chrome Extension → Flask Backend

**Standard approach**: Bearer tokens (JWT or OAuth2-style access tokens)

**Why NOT cookies for extensions?**
1. Extensions run at `chrome-extension://` origin (cross-origin from server)
2. `SameSite=Lax` cookies won't be sent on cross-origin requests
3. Changing to `SameSite=None` requires HTTPS + CSRF protection (fragile)
4. Cookie policies vary across browsers/versions

**Why bearer tokens?**
1. Explicit `Authorization` headers work reliably cross-origin
2. No cookie policy headaches
3. Standard OAuth2 pattern (widely understood)

**Hybrid approach** (web + extension):
- Web UI: Session cookies (better security via HttpOnly)
- Extension: Bearer tokens (reliability + explicit auth)
- Backend: Accept either mechanism

---

## Recommended Implementation Plan

### Phase 1: Add Refresh Token System (1-2 days)

#### Server-Side Changes

**1. Create unified `@auth_required` decorator** (replaces both `@login_required` and `@require_ext_auth`):
```python
def auth_required(f):
    """Accept EITHER session OR bearer token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check session first (for main UI)
        if session.get("email"):
            request.user_email = session["email"]
            return f(*args, **kwargs)
        
        # Check bearer token (for extension)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            valid, payload = verify_access_token(token)
            if valid:
                request.user_email = payload["email"]
                return f(*args, **kwargs)
        
        # Neither auth method worked
        return redirect("/login") if request.accept_mimetypes.accept_html else (jsonify({"error": "Unauthorized"}), 401)
    
    return decorated
```

**2. Add token endpoints**:
```python
@app.route("/auth/token", methods=["POST"])
def get_token():
    """
    Login and receive access + refresh tokens.
    
    Request: {"email": "...", "password": "..."}
    Response: {
        "access_token": "...",
        "access_expires_at": "2026-02-16T13:30:00Z",
        "refresh_token": "...",
        "refresh_expires_at": "2026-03-18T12:11:56Z"
    }
    """
    # Verify credentials
    # Generate short-lived access token (15-60 min)
    # Generate long-lived refresh token (30 days)
    # Store refresh token hash server-side (reuse remember_tokens.json pattern)
    # Return both tokens

@app.route("/auth/refresh", methods=["POST"])
def refresh_token():
    """
    Exchange refresh token for new access token.
    
    Request: {"refresh_token": "..."}
    Response: {
        "access_token": "...",
        "access_expires_at": "...",
        "refresh_token": "...",  # NEW rotated refresh token
        "refresh_expires_at": "..."
    }
    """
    # Verify refresh token
    # Invalidate old refresh token (rotation)
    # Generate new access token
    # Generate new refresh token
    # Store new refresh token hash
    # Return both tokens
```

**3. Refresh token storage** (reuse `remember_tokens.json` pattern):
```json
{
  "refresh_token_hash_abc123": {
    "email": "user@example.com",
    "device_id": "extension_install_uuid",
    "created_at": "2026-02-16T12:11:56Z",
    "expires_at": "2026-03-18T12:11:56Z"
  }
}
```

**4. Token validation helpers**:
```python
def generate_access_token(email: str) -> tuple[str, datetime]:
    """Generate short-lived access token (15-60 min)."""
    # Use existing ExtensionAuth.generate_token() but with shorter expiry
    
def generate_refresh_token(email: str, device_id: str) -> tuple[str, datetime]:
    """Generate long-lived refresh token (30 days), store hash."""
    # Similar to generate_remember_token()
    
def verify_access_token(token: str) -> tuple[bool, dict]:
    """Verify access token signature and expiry."""
    # Use existing ExtensionAuth.verify_token()
    
def verify_refresh_token(token: str) -> tuple[bool, dict]:
    """Verify refresh token against stored hashes."""
    # Similar to verify_remember_token()
    
def rotate_refresh_token(old_token: str) -> tuple[str, datetime]:
    """Invalidate old token, generate new one."""
```

#### Extension-Side Changes

**1. Update `extension/shared/api.js`**:
```javascript
class API {
    static async call(endpoint, options = {}) {
        let token = await Storage.getAccessToken();
        
        // Try request with current access token
        let response = await fetch(endpoint, {
            ...options,
            headers: {
                'Authorization': `Bearer ${token}`,
                ...options.headers
            }
        });
        
        // If 401, try to refresh
        if (response.status === 401) {
            const refreshed = await this.refreshToken();
            if (refreshed) {
                // Retry with new access token
                token = await Storage.getAccessToken();
                response = await fetch(endpoint, {
                    ...options,
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        ...options.headers
                    }
                });
            } else {
                // Refresh failed, redirect to login
                this.handleAuthFailure();
            }
        }
        
        return response;
    }
    
    static async refreshToken() {
        const refreshToken = await Storage.getRefreshToken();
        if (!refreshToken) return false;
        
        const response = await fetch('/auth/refresh', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({refresh_token: refreshToken})
        });
        
        if (response.ok) {
            const data = await response.json();
            await Storage.setAccessToken(data.access_token);
            await Storage.setRefreshToken(data.refresh_token);
            return true;
        }
        
        return false;
    }
}
```

**2. Update storage to handle two tokens**:
```javascript
class Storage {
    static async setAccessToken(token) {
        return chrome.storage.local.set({access_token: token});
    }
    
    static async getAccessToken() {
        const result = await chrome.storage.local.get('access_token');
        return result.access_token;
    }
    
    static async setRefreshToken(token) {
        return chrome.storage.local.set({refresh_token: token});
    }
    
    static async getRefreshToken() {
        const result = await chrome.storage.local.get('refresh_token');
        return result.refresh_token;
    }
}
```

**3. Update login flow**:
```javascript
// Old: receives single token valid for 7 days
// New: receives access token (short) + refresh token (long)
async function login(email, password) {
    const response = await fetch('/auth/token', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email, password})
    });
    
    const data = await response.json();
    await Storage.setAccessToken(data.access_token);
    await Storage.setRefreshToken(data.refresh_token);
}
```

### Phase 2: Gradual Migration (Backward Compatible)

1. **Keep legacy token validation temporarily**:
   - `@auth_required` also accepts old 7-day tokens (log warning)
   - Extension can continue using old tokens during transition

2. **Next login generates new tokens**:
   - Users who log in get new access + refresh tokens
   - Old tokens still work until expiry

3. **After 7 days** (old token lifetime):
   - All users have migrated to new system
   - Remove legacy token validation

### Phase 3: Apply to All Extension Endpoints

1. **Replace decorators**:
   - Change `@require_ext_auth` → `@auth_required` on all extension endpoints
   - This automatically enables session OR bearer auth

2. **Test both auth methods**:
   - Web UI calls with session: should work
   - Extension calls with bearer: should work

---

## Security Considerations

### Access Token Theft Mitigation
1. **Short lifetime** (15-60 min) → small theft window
2. **No sensitive operations** without additional verification (e.g., account deletion requires re-auth)

### Refresh Token Theft Mitigation
1. **Rotation**: Every refresh invalidates old token (prevents replay)
2. **Server-side tracking**: Store hashes, can revoke all tokens for a user
3. **Device binding**: Associate refresh token with extension install ID
4. **Extension security**: Follow Chrome extension security best practices (CSP, message validation)

### CSRF Protection
- Bearer tokens: Immune (not auto-sent)
- Session cookies: Existing CSRF protection (if any) continues to work

### Comparison to Remember-Me Cookies
| Feature | Remember-Me Cookie | Refresh Token |
|---------|-------------------|---------------|
| Storage | Server file + HttpOnly cookie | Server file + extension storage |
| Theft protection | ✅ HttpOnly (can't read via JS) | ⚠️ JS-readable (mitigate with rotation) |
| Rotation | ❌ Not typically rotated | ✅ Rotated on each refresh |
| Revocation | ✅ Can delete from server file | ✅ Can delete from server file |
| Cross-origin | ⚠️ Cookie policy issues | ✅ Works reliably |

---

## Timeline Impact

### Original Milestone 1 Estimate: 3-5 days
**Tasks**:
1. Generate JWT on install (0.5 day)
2. Store in extension storage (0.5 day)
3. Add to all requests (0.5 day)
4. Backend validation middleware (1 day)
5. Add `@auth_required` to all routes (0.5-1.5 days)

### Recommended Approach Estimate: 4-6 days (+1 day)
**Additional work**:
- Implement refresh token system (+1 day)
- Token rotation logic (+0.5 day)
- Silent refresh in extension (+0.5 day)

**BUT**: Prevents future "logged out" complaints and security incidents. **ROI is positive.**

### Alternative: Quick Fix (1 hour)
**Option**: Just change `TOKEN_EXPIRY_HOURS = 24 * 7` to `24 * 30` (30 days)

**Pros**:
- Minimal code change
- Reduces logout frequency immediately

**Cons**:
- ❌ 30-day theft window if token stolen
- ❌ No revocation capability
- ❌ Still forces logout every 30 days
- ❌ Doesn't follow industry best practices

**Verdict**: Not recommended for production, but acceptable for quick testing.

---

## Migration Path (Minimal User Disruption)

### Phase 1: Server-Side Setup (No User Impact)
1. Add `/auth/token` and `/auth/refresh` endpoints
2. Add refresh token storage system
3. Update `@auth_required` decorator to accept session OR bearer
4. Keep legacy token validation active

### Phase 2: Extension Update (Seamless)
1. Update extension to use new token endpoints
2. Implement silent refresh
3. On next login, users get new tokens automatically
4. Old tokens continue working until expiry (7 days grace period)

### Phase 3: Cleanup (After Grace Period)
1. Remove legacy token validation
2. Update documentation
3. Monitor for any issues

**User Experience**: Completely seamless. Users don't notice any change except they stop getting logged out unexpectedly.

---

## Edge Cases & Advanced Considerations

### 1. "Log out everywhere" (Token Revocation)
**Scenario**: User suspects account compromise, wants to invalidate all tokens.

**Implementation**:
```python
@app.route("/auth/revoke_all", methods=["POST"])
@auth_required
def revoke_all_tokens():
    """Revoke all refresh tokens for current user."""
    email = request.user_email
    # Delete all refresh tokens for this email from storage
    # User must re-login on all devices
```

### 2. Multiple Extension Installations
**Scenario**: User installs extension on Chrome + Edge + Firefox.

**Behavior**:
- Each installation gets its own refresh token
- All can be active simultaneously
- Each tracked separately via `device_id`

### 3. Extension Update Wipes Storage
**Scenario**: Chrome extension update clears `chrome.storage.local`.

**Mitigation**:
- Use `chrome.storage.sync` for critical tokens (syncs across devices)
- Or: Prompt user to re-login (unavoidable if storage lost)

### 4. Clock Skew
**Scenario**: User's system clock is wrong, token appears expired/not-yet-valid.

**Mitigation**:
- Server generates timestamps (not client)
- Allow small clock skew tolerance (±5 min) in token validation

### 5. Concurrent Refresh Requests
**Scenario**: Multiple tabs/windows refresh token simultaneously, only one succeeds.

**Mitigation**:
- Use mutex/lock in extension before calling `/auth/refresh`
- Or: Server allows 1-time grace period (both old & new refresh tokens valid for 60 sec)

---

## Recommendation Summary

### ✅ DO THIS: Hybrid Auth with Refresh Tokens

**What**:
1. Keep session-based auth for main web UI
2. Implement JWT access tokens (15-60 min) + refresh tokens (30 days) for extension
3. Make extension endpoints accept session OR bearer
4. Implement automatic silent refresh in extension

**Why**:
- Solves "logged out every now and then" problem ✅
- Best security/UX balance for each context ✅
- Industry standard approach ✅
- Minimal disruption to existing systems ✅
- Enables future features (multi-device, revocation) ✅

**Effort**: 4-6 days (1 day more than original plan)

**Risk**: Low (backward compatible, additive changes)

### ❌ DON'T DO THIS

**Option A: Force sessions everywhere (including extension)**
- **Problem**: Cookie policies make this brittle for extensions
- **Requires**: `SameSite=None` + CSRF tokens + CORS credentials
- **Verdict**: More complexity, less reliability

**Option B: Just extend token lifetime to 30 days**
- **Problem**: Doesn't solve root cause, increases security risk
- **Verdict**: Band-aid, not a solution

**Option C: Force full JWT everywhere (including main UI)**
- **Problem**: Destabilizes working web UI, loses HttpOnly security
- **Verdict**: Unnecessary disruption

---

## Files to Modify

### New Files
- `endpoints/token_auth.py` — Token generation, validation, refresh logic (≈200 lines)

### Modified Files
- `endpoints/auth.py` — Add `@auth_required` decorator, token endpoints (±100 lines)
- `extension.py` — Update token expiry constants, add refresh token helpers (±50 lines)
- `extension_server.py` — Replace `@require_ext_auth` with `@auth_required` (±10 files, bulk replace)
- `extension/shared/api.js` — Add silent refresh logic (±80 lines)
- `extension/shared/storage.js` — Add access/refresh token storage (±30 lines)

### Affected Endpoints (Apply `@auth_required`)
- All 38 extension endpoints (bulk decorator replacement)
- Keep main backend endpoints using `@login_required` (no change)

---

## Testing Strategy

### Unit Tests
- Token generation: verify payload structure, signature
- Token validation: verify expiry checks, signature verification
- Token rotation: verify old token invalidated, new token valid

### Integration Tests
1. **Login flow**: Verify access + refresh tokens returned
2. **API call with valid access token**: Should succeed
3. **API call with expired access token + valid refresh**: Should auto-refresh and succeed
4. **API call with expired both tokens**: Should fail with 401
5. **Session-based call**: Should still work (hybrid validation)
6. **Token rotation**: Verify old refresh token rejected after rotation
7. **Concurrent refresh**: Verify no race conditions

### Manual Testing
1. Log in via extension → verify tokens stored
2. Wait for access token expiry (or mock expiry) → verify silent refresh
3. Close browser, reopen → verify still logged in
4. Log out → verify both tokens cleared

---

## Next Steps

1. **Review this document** with team/stakeholders
2. **Decide on token lifetimes**:
   - Access: 15-60 min (recommend 30 min)
   - Refresh: 30 days (recommend 30 days, can extend to 90)
3. **Update Milestone 1 tasks** in main plan with refresh token implementation
4. **Begin implementation** starting with server-side token system
5. **Test thoroughly** with above test cases
6. **Deploy with backward compatibility** (phased migration)

---

## Conclusion (Original Analysis)

The "logged out every now and then" issue is caused by **7-day hard token expiry with no refresh mechanism**. The solution is **implementing refresh tokens with silent auto-refresh**, NOT changing the authentication mechanism itself.

**Hybrid authentication** (sessions for web, bearer tokens for extension) is the industry-standard approach that provides:
- ✅ Best security for each context
- ✅ Best reliability for each context
- ✅ Seamless user experience (no unexpected logouts)
- ✅ Minimal disruption to existing systems

**Effort**: +1 day to Milestone 1 (4-6 days total instead of 3-5 days)  
**Benefit**: Eliminates user complaints, follows best practices, enables future features  
**Risk**: Low (backward compatible, additive)

~~**Recommendation**: Proceed with this approach for Milestone 1.~~

---

## FINAL DECISION & UPDATE (2026-02-16)

### User Decision: Session-Based Auth Only

After reviewing this comprehensive analysis, the user made a **simpler, more pragmatic decision**:

> "Use the normal main backend auth for extension as well. We don't want to make changes to main backend just for Auth. Also the extension supports using either local or hosted backend, we want to keep that ability to make debugging easier."

### Why This Is Actually Better

The original analysis **over-complicated** the solution. The user correctly identified that:

1. **Main backend auth already works** — 30-day sessions solve the "logged out" problem
2. **JWT adds unnecessary complexity** — New library, new endpoints, new security considerations
3. **Extension backend URL is configurable** — Already supports `http://localhost:5000` (local) and hosted server
4. **Minimal backend changes** — Only need CORS + one new endpoint (`/ext/auth/login`)

### Session Auth for Extension: Simplified Approach

**How it works**:
- Extension calls `/ext/auth/login` (uses main backend credential verification)
- Server creates Flask session (same as web UI)
- Session cookie sent with `SameSite=None; Secure` (allows cross-origin)
- Extension uses `credentials: 'include'` in all fetch requests
- Cookies automatically included by browser

**Timeline**:
- Original JWT approach: 3-5 days
- Session-based approach: **2-3 days** ✅
- **Savings: 1-2 days**

**Complexity reduction**:
- No JWT library needed
- No token refresh mechanism
- No token storage in extension
- No hybrid auth decorator logic
- Uses existing session system

### Complete Implementation

See **`milestone_1_session_auth_rewrite.md`** for full implementation details:
- CORS configuration for extension origin
- `SameSite=None` cookie policy for cross-origin
- `/ext/auth/login` endpoint (JSON API, reuses main auth)
- Extension client updates (`credentials: 'include'`)
- Testing with local AND hosted backends

### Lessons Learned

1. **Always start with the simplest solution** — Session auth was available all along
2. **Industry best practices aren't always best for your context** — JWT is standard for REST APIs, but not required here
3. **Listen to the user** — User's requirement for "no backend changes" revealed the simpler path
4. **Backend URL configurability matters** — Extension's ability to switch backends (local/hosted) was a key requirement that influenced the decision

### Final Status

- ❌ **JWT + Refresh Tokens** — Rejected (too complex, unnecessary backend changes)
- ✅ **Session-Based Auth** — **APPROVED & IMPLEMENTED IN PLAN**

**Implementation document**: `milestone_1_session_auth_rewrite.md` (4800 lines, ready for implementation)  
**Timeline**: 2-3 days (Milestone 1)  
**Status**: Ready to proceed

---

## Document History

| Version | Date | Decision | Rationale |
|---------|------|----------|-----------|
| v1.0 | 2026-02-16 | Hybrid Auth (JWT + Session) | Analysis of auth mechanisms, industry best practices |
| v2.0 | 2026-02-16 | **Session Auth Only** | User requirement for simplicity, no backend changes, backend URL configurability |

**Current recommendation**: Use session-based auth (v2.0). This document preserved for historical context and to document the analysis process.
