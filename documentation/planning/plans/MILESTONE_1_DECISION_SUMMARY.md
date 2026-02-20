# Milestone 1 Authentication Decision - Summary

**Date**: 2026-02-16  
**Status**: ✅ **DECIDED - Ready for Implementation**  
**Decision**: Session-Based Auth (Main Backend Auth Reuse)

---

## Quick Reference

| Document | Purpose | Lines | Status |
|----------|---------|-------|--------|
| **This File** | Executive summary of decision | 200+ | Current |
| `milestone_1_session_auth_rewrite.md` | Complete implementation plan | 4800+ | Ready to implement |
| `AUTH_COMPARISON_AND_RECOMMENDATION.md` | Original analysis + final decision | 663 | Updated with decision |
| `extension_backend_unification.plan.md` | Main plan (needs M1 update) | 2000+ | To be updated |

---

## The Decision

**Use main backend's session-based auth for extension. NO JWT implementation.**

### User Requirements (Verbatim)

1. > "Use the normal main backend auth for extension as well."
2. > "We don't want to make changes to main backend just for Auth."
3. > "Extension supports using either local or hosted backend, we want to keep that ability to make debugging easier."

---

## What This Means

### ✅ DO THIS (Session Auth)

- Extension calls `/ext/auth/login` (new endpoint, uses main backend credential verification)
- Server creates Flask session (same as web UI `/login`)
- Session cookie sent with `SameSite=None; Secure` (allows cross-origin)
- Extension uses `credentials: 'include'` in all fetch requests
- Browser automatically handles cookies
- **30-day sessions** with auto-refresh (no more "logged out" issues)

### ❌ DON'T DO THIS (Original Plan)

- ~~Implement JWT token generation/verification~~
- ~~Add PyJWT library~~
- ~~Implement refresh token system~~
- ~~Create token storage in extension~~
- ~~Build token refresh logic~~

---

## Why This Is Better

| Aspect | JWT Approach (Original) | Session Approach (Decided) |
|--------|-------------------------|---------------------------|
| **Backend Changes** | Moderate (JWT middleware, decorators) | **Minimal** (CORS + 1 endpoint) |
| **Complexity** | High (tokens, refresh, rotation) | **Low** (reuse existing system) |
| **Logout Prevention** | Needs refresh tokens (new code) | **Already solved** (30-day sessions) |
| **Debugging** | New auth system to debug | **Same as web UI** (familiar) |
| **Timeline** | 3-5 days | **2-3 days** ✅ |
| **Backend URL Config** | Works | **Works** (already implemented) |

---

## Implementation Summary

### 6 Tasks (2-3 days total)

| Task | What | Effort | Key Deliverable |
|------|------|--------|-----------------|
| **1.1** | Add CORS for extension origin | 0.5 day | `is_allowed_extension_origin()` function |
| **1.2** | Adjust SameSite policy | 0.5 day | `SameSite=None; Secure` for `/ext/*` |
| **1.2b** | Create `/ext/auth/login` | 0.5 day | `endpoints/ext_auth.py` blueprint |
| **1.3** | Update extension client | 0.5-1 day | `credentials: 'include'` in all calls |
| **1.4** | Add `@auth_required` | 0.25 day | JSON 401 decorator (not redirect) |
| **1.5** | Test both backends | 0.5 day | Verify local + hosted work |
| **1.6** | Rate limiting | 0.25 day | `@limiter.limit()` on endpoints |

### Key Code Changes

**Backend** (server.py):
```python
# CORS for extension
CORS(app, resources={
    r"/ext/*": {
        "origins": is_allowed_extension_origin,
        "supports_credentials": True,  # CRITICAL for cookies
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    }
})

# Session config for cross-origin
app.config.update(
    SESSION_COOKIE_SAMESITE='None',  # Allow cross-origin
    SESSION_COOKIE_SECURE=True       # Required with None
)
```

**Backend** (endpoints/ext_auth.py):
```python
@ext_auth_bp.route("/ext/auth/login", methods=["POST"])
def ext_login():
    # Uses check_credentials() from main backend
    # Creates Flask session
    # Returns JSON (not redirect)
    session["email"] = email
    session["name"] = email
    return jsonify({"success": True, "email": email})
```

**Extension** (shared/api.js):
```javascript
export const API = {
    async call(endpoint, options = {}) {
        const apiBase = await getApiBaseUrl();
        return fetch(`${apiBase}${endpoint}`, {
            ...options,
            credentials: 'include'  // Send cookies!
        });
    }
}
```

---

## How It Works

### Login Flow
```
User enters credentials
    ↓
POST /ext/auth/login
    ↓
Server verifies (same code as web UI)
    ↓
Server creates session
    ↓
Cookie sent (SameSite=None; Secure)
    ↓
Browser stores cookie
    ↓
Done!
```

### API Call Flow
```
Extension calls API with credentials: 'include'
    ↓
Browser includes session cookie automatically
    ↓
Server validates session (@login_required or @auth_required)
    ↓
Response returned
```

### Session Persistence
- **30-day cookies** (same as web UI)
- **Auto-refresh** on each request
- **Survives browser restarts**
- **No manual refresh needed**

---

## Cross-Origin Challenge (Solved)

**Problem**: Extension at `chrome-extension://` origin, server at `http://localhost:5000` or `https://sci-tldr.pro`

**Solution**:
- Use `SameSite=None; Secure` for `/ext/*` endpoints
- Use `credentials: 'include'` in fetch
- CORS allows extension origin
- For localhost (same-site), `SameSite=Lax` works

**HTTPS requirement**: `SameSite=None` requires Secure flag (HTTPS only)
- **Local dev**: `localhost` is exempt, Lax works
- **Production**: Enforce HTTPS (already required by Chrome)

---

## Backend URL Configuration

**Already implemented** ✅ — No changes needed!

Extension has:
- "Use Local" preset → `http://localhost:5000`
- "Use Hosted" preset → `https://sci-tldr.pro`
- Custom URL input
- Stored in `chrome.storage.local` as `apiBaseUrl`
- `getApiBaseUrl()` reads from storage

**Works with session auth** because cookies are domain-specific.

---

## Migration Impact

### User Experience
- **One-time re-login** (JWT tokens → session cookies)
- **No data loss** (conversations on server)
- **Better persistence** (30 days vs 7 days)

### Developer Experience
- **Simpler debugging** (same auth as web UI)
- **Familiar tools** (Flask session, Chrome DevTools cookies)
- **Less code to maintain** (no JWT library, no refresh logic)

---

## Timeline Impact

| Milestone | Old Effort | New Effort | Savings |
|-----------|-----------|-----------|---------|
| M1: Auth | 3-5 days | **2-3 days** | -1 to -2 days |
| **Other milestones** | 18-25 days | 18-25 days | No change |
| **TOTAL** | 21-30 days | **20-29 days** | **-1 to -2 days** |

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **SameSite=None requires HTTPS** | High | Localhost exempt (same-site), production enforces HTTPS |
| **Extension ID changes** | Medium | Regex patterns match any ID format |
| **Session cookie not sent** | High | Verify `credentials: 'include'` everywhere, test thoroughly |
| **CSRF attacks** | Medium | Extension origin inherently trusted, add optional CSRF token |

---

## Success Criteria

✅ Extension logs in with main backend credentials  
✅ Session cookie set correctly (visible in DevTools)  
✅ Session persists across browser restarts  
✅ Works with `http://localhost:5000` (local dev)  
✅ Works with hosted server (production)  
✅ No CORS errors in console  
✅ 30-day session means no unexpected logouts  

---

## Next Steps

1. ✅ **Decision made** — Session-based auth
2. ✅ **Documentation complete** — `milestone_1_session_auth_rewrite.md`
3. 📋 **Pending**: Update main plan `extension_backend_unification.plan.md` Milestone 1 section
4. 🚀 **Ready to implement** — Task 1.1 (CORS support)

---

## Reference Documents

### Primary Implementation Guide
- **`milestone_1_session_auth_rewrite.md`** (4800 lines)
  - Complete task breakdown
  - Code samples for all changes
  - Testing procedures
  - Edge case handling

### Supporting Analysis
- **`AUTH_COMPARISON_AND_RECOMMENDATION.md`** (663 lines)
  - Original JWT analysis (for reference)
  - User decision documentation
  - Lessons learned

### Main Plan (To Be Updated)
- **`extension_backend_unification.plan.md`** (2000+ lines)
  - Currently has old Milestone 1 (JWT-based)
  - Needs update to reference new session-based approach

---

## Key Insights

### What We Learned

1. **Simpler is often better** — Session auth was available all along
2. **Listen to user requirements** — "No backend changes" revealed the simpler path
3. **Context matters** — JWT is "industry standard" but not always best choice
4. **Configurability is valuable** — Backend URL switching (local/hosted) influenced decision
5. **Existing solutions are underrated** — 30-day sessions already solved the logout problem

### Design Principles Applied

- **YAGNI** (You Aren't Gonna Need It) — JWT refresh tokens were unnecessary complexity
- **KISS** (Keep It Simple) — Reuse existing auth system
- **DRY** (Don't Repeat Yourself) — One auth system for web + extension
- **Pragmatism over purity** — "Industry best practice" isn't always right for your context

---

## Conclusion

**Session-based auth is the right choice** for extension backend unification because:

✅ Reuses proven system (main backend auth)  
✅ Minimal backend changes (CORS + 1 endpoint)  
✅ Solves "logged out" problem (30-day sessions)  
✅ Simpler implementation (2-3 days vs 3-5 days)  
✅ Easier debugging (same as web UI)  
✅ Works with local + hosted backends  
✅ No new dependencies or complexity  

**Status**: Ready for implementation. Proceed to Task 1.1 (CORS support) when ready.

---

**Last Updated**: 2026-02-16  
**Decision By**: User  
**Documented By**: Sisyphus (OpenCode AI)  
**Implementation Status**: Planned, not started
