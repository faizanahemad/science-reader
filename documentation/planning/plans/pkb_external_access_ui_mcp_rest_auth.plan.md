# PKB / TMS External Access — Standalone UI, MCP, REST API, Auth & Agent Integration

**Status:** Draft (revised)
**Created:** 2026-06-09
**Revised:** 2026-06-10
**Scope:** Make the PKB usable *outside* the chat shell: a standalone `/memory/` web UI, an externally-reachable authenticated MCP server, a token-authenticated REST API, a dual-auth scheme, and integration recipes for Claude Code / other agentic systems. Internal memory-system improvements are covered separately in `pkb_memory_system_improvements.plan.md` and `pkb_ux_improvements.plan.md`.

---

## 1. Background & Motivation

Today the PKB is reachable only from inside the logged-in chat app:
- **UI:** the PKB lives as Bootstrap modals (`#pkb-modal` with 9 tabs: Claims/Entities/Tags/Conflicts/Bulk/Import/Contexts/Overview/Maintenance, plus `#pkb-claim-edit-modal`, `#memory-proposal-modal`) inside `interface/interface.html`, driven by the `PKBManager` IIFE in `interface/pkb-manager.js`. There is no dedicated URL — no `memory.html`, no `/memory` route, no `init()` on PKBManager.
- **REST:** `endpoints/pkb.py` exposes 82 routes under `/pkb/*`, all guarded by `@login_required` (Flask session via Google OAuth) — unusable by external programmatic clients. No bearer token auth exists anywhere in the REST layer. `endpoints/auth.py` only has `generate_remember_token`/`verify_remember_token` for session "remember me" — not suitable for API access.
- **MCP:** `mcp_server/pkb.py` implements a JWT-authenticated streamable-HTTP MCP server (port 8101) with **27 tools** (19 baseline + 8 full tier). Auth handled by `mcp_server/auth.py` (HS256 JWT with `{email, scopes, iat, exp}`). **Security gap:** `user_email` is a client-supplied parameter in every tool — NOT derived from the JWT. The server trusts whatever email the client passes.
- **nginx:** `documentation/planning/nginx_mcp_blocks.conf` has ready-to-paste location blocks for `/mcp/pkb/` → `localhost:8101` (and 7 other servers), but these are NOT deployed yet.

Goal: a clean, authenticated "memory anywhere" surface — a bookmarkable UI at `https://assist-chat.site/memory/`, plus MCP and REST endpoints an external agent (Claude Code, OpenCode, scripts) can connect to with a per-user token.

### Current surface area (post v1.0 UX improvements)

| Surface | Count | Auth |
|---------|-------|------|
| REST endpoints | 82 | Session only (`@login_required`) |
| MCP tools | 27 (19 baseline + 8 full) | JWT header, but `user_email` is client-supplied |
| LLM tools (in-chat) | 26 | Implicit (session user) |
| NL agent actions | 14 | Implicit (session user) |
| structured_api methods | 82 | Called server-side with known email |
| UI tabs | 9 | Session |

### Key code references
- `endpoints/static_routes.py` — `/interface` + `/interface/<path:path>` serve `interface/interface.html`; `/` redirects to `/interface`. Auth via `@login_required`.
- `endpoints/auth.py` — `login_required` decorator (checks `session["email"]`/`["name"]`); `generate_remember_token`/`verify_remember_token` for remember-me only.
- `endpoints/session_utils.py` — `get_session_identity()` → `(email, name, loggedin)`.
- `endpoints/pkb.py` — all 82 `/pkb/*` routes (`@login_required` + `get_session_identity()`).
- `mcp_server/pkb.py` — `create_pkb_mcp_app(jwt_secret, rate_limit)`; 27 tiered tools; `PKB_MCP_PORT=8101`.
- `mcp_server/auth.py` — `generate_token(secret, email, days=365, scopes=["search"])` → HS256 JWT; `verify_jwt(token, secret)` → payload or None. `JWTAuthMiddleware` extracts bearer token. Stateless — no revocation.
- `documentation/planning/nginx_mcp_blocks.conf` — ready location blocks for all 8 MCP servers.
- `documentation/product/ops/mcp_server_setup.md` — ports 8100-8108, shared `MCP_JWT_SECRET`.

---

## 2. Goals & Success Criteria

| # | Goal | Success criteria |
|---|------|------------------|
| G1 | Standalone PKB UI | `https://assist-chat.site/memory/` renders the full PKB (all 9 tabs) as a first-class page, session-authenticated, no chat shell required |
| G1b | Single source of truth | The standalone page and the in-chat modal render from one `pkb-manager.js` with an `init(container)` entry point; no forked markup |
| G2 | Deep-linkable | `/memory/<friendly_id>` opens that claim/context directly |
| G3 | External MCP (secured) | PKB MCP reachable over HTTPS at `/mcp/pkb/` with bearer token; `user_email` **derived from JWT**, not client-supplied |
| G4 | External REST API | `/pkb/*` callable by external clients with `Authorization: Bearer <token>`, scoped per user |
| G5 | Unified auth | One token type works for both MCP and REST; mintable from the UI; scoped + revocable |
| G6 | Documented integration | Copy-paste setup for Claude Code / OpenCode + curl examples |

### Non-goals
- Public/unauthenticated access.
- A separate SPA framework — reuse existing jQuery/Bootstrap + `pkb-manager.js`.
- OAuth client-credentials / third-party app authorization flows (future).
- Mobile-specific responsive layout (future).

---

## 3. Workstream 1 — Standalone `/memory/` UI (G1, G2)

**Design principle:** one canonical PKB UI implementation, reused everywhere. The standalone `/memory/` page and the in-chat modal render from the **same** `pkb-manager.js`, so they stay in sync automatically.

### Approach: add `init(container)` to PKBManager + create a thin shell page

- **T1.1 Add `PKBManager.init(containerSelector)`.** Today PKBManager is an IIFE that assumes its DOM exists inside `#pkb-modal`. Refactor to accept a container: when `containerSelector` is given, render the 9-tab UI directly into that element (no `.modal()` calls). When no container is given (or `#pkb-modal` exists), preserve current modal behavior. This requires:
  - Moving the tab HTML into a template string (or a `<template>` tag in interface.html that both paths consume).
  - Guarding all `$('#pkb-modal').modal(...)` calls behind a `isModal` flag.
  - Ensuring all `/pkb/*` AJAX calls work identically in both contexts (they will — same session cookie).

- **T1.2 Create `interface/memory.html`** — a thin full-page shell:
  ```html
  <!DOCTYPE html>
  <html>
  <head>
    <title>Memory — PKB</title>
    <!-- Same CSS deps as interface.html: Bootstrap 4.6, bootstrap-icons, custom styles -->
  </head>
  <body>
    <nav><!-- minimal header: logo, user name, back-to-chat link --></nav>
    <div id="memory-root" style="max-width:1200px; margin:0 auto; padding:20px"></div>
    <div id="memory-deeplink" data-ref="" style="display:none"></div>
    <!-- JS deps: jQuery, Bootstrap, shared utils (showToast, escapeHtml), pkb-manager.js -->
    <script>
      $(function() {
        PKBManager.init('#memory-root');
        var ref = $('#memory-deeplink').data('ref');
        if (ref) PKBManager.openByReference(ref);
      });
    </script>
  </body>
  </html>
  ```
  Extract the minimal subset of `common.js` helpers needed (`showToast`, `escapeHtml`, `debounce`) into a `common-utils.js` or include `common.js` with a guard.

- **T1.3 Add Flask route** in `endpoints/static_routes.py`:
  ```python
  @static_bp.route("/memory", strict_slashes=False)
  @static_bp.route("/memory/<path:path>", strict_slashes=False)
  @login_required
  def memory_ui(path: str = ""):
      if path:
          html = open(os.path.join("interface", "memory.html")).read()
          div = f'<div id="memory-deeplink" data-ref="{path}" style="display:none"></div>'
          return Response(html.replace("</body>", div + "</body>"), mimetype="text/html")
      return send_from_directory("interface", "memory.html", max_age=0)
  ```

- **T1.4 Deep-link handling (G2).** `PKBManager.openByReference(ref)` calls `GET /pkb/claims/by-friendly-id/<ref>` or `GET /pkb/resolve/<ref>` and opens the edit modal or context view.

- **T1.5 No backend changes** — reuse existing session-authenticated `/pkb/*` endpoints.

- **T1.6 nginx:** none required — nginx already proxies `/` → `localhost:5000`.

### Chat-integrated touchpoints (stay in-page, NOT in the standalone UI)
These remain as direct `PKBManager` calls within `interface.html`:
- `@reference` autocomplete in chat input
- "Save to Memory" from message context menu
- `/pkb` and `/memory` slash commands
- "Use in next message" pending-attachments indicator
- Memory proposal modals (`#memory-proposal-modal`, tool-call modal)
- STM capture toasts

### Optional: iframe the management view in the main chat app
For CSS/JS isolation, the in-chat modal *may* iframe `/memory/` (same-origin, session cookie inherited). Only do this if the shared-template approach causes CSS/DOM conflicts. Adds complexity (postMessage bridge for `open-add-with-text`, `switch-tab`; double jQuery load; iframe sizing).

**Recommendation:** Ship `init(container)` + shared template first. Add iframe only if isolation proves necessary.

### Challenges
- The `pkb-manager.js` refactor (T1.1) must not regress the in-chat modal. Gate all modal calls with `if (isModal)`.
- Audit `common.js` dependencies used by PKBManager — may need to extract a standalone utility bundle.
- The 9-tab template is ~300 lines of HTML — embedding as a JS template string is feasible but consider a `<template id="pkb-template">` approach for maintainability.

---

## 4. Workstream 2 — Secure External MCP (G3)

The MCP server exists and works. Two tasks: deploy externally via nginx, and fix the `user_email` security gap.

### T2.1 Fix `user_email` derivation (SECURITY — MUST DO FIRST)

**Current state:** Every MCP tool takes `user_email` as an explicit parameter. The JWT middleware validates the token but does NOT enforce that the client-supplied `user_email` matches `token["email"]`. A malicious client with a valid token can access any user's PKB.

**Fix:** In `JWTAuthMiddleware` or a wrapper, after JWT validation:
1. Store `request.state.authenticated_email = payload["email"]` (or equivalent for the MCP framework).
2. In each tool function, **ignore** the `user_email` parameter and use the authenticated email from request state.
3. Alternatively, remove `user_email` from tool signatures entirely and inject it from middleware. But this breaks the MCP tool schema for clients that expect to pass it. **Recommended approach:** keep `user_email` in signatures for documentation/client hinting, but override it server-side with the JWT email. Log a warning if they differ.

### T2.2 Deploy via nginx

Apply the existing `/mcp/pkb/` block from `documentation/planning/nginx_mcp_blocks.conf`:
```nginx
location /mcp/pkb/ {
    proxy_pass http://127.0.0.1:8101/;
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
Add to `/etc/nginx/sites-available/science-reader` inside the `listen 443 ssl` server block.

### T2.3 Verify server runs persistently

Confirm `PKB_MCP_ENABLED=1` and `MCP_JWT_SECRET` are set in the screen session. Add to the server restart guide if not already there. The MCP server should auto-start with the main app (check `mcp_server/pkb.py` `if __name__` or startup hook).

### T2.4 Tool tier for external use

Default to `full` (all 27 tools) for token holders — they are authenticated power users. The baseline/full split was designed to limit casual in-chat use, not external programmatic access.

### T2.5 Token issuance (shared with Workstream 4)

See §6 T4.1 — provide `/pkb/token` endpoint so users don't need CLI access.

---

## 5. Workstream 3 — Token-authenticated REST API (G4)

**Problem:** All 82 `/pkb/*` routes require Flask session. External agents need bearer token access.

### T3.1 Dual-auth decorator `pkb_auth_required`

Create `endpoints/pkb_auth.py`:
```python
from functools import wraps
from flask import request, session
from mcp_server.auth import verify_jwt
import os

MCP_JWT_SECRET = os.environ.get("MCP_JWT_SECRET", "")

def pkb_auth_required(f):
    """Accept either Flask session OR Bearer token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Path 1: existing session auth
        if session.get("email"):
            request._pkb_email = session["email"]
            return f(*args, **kwargs)
        
        # Path 2: Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = verify_jwt(token, MCP_JWT_SECRET)
            if payload and "email" in payload:
                request._pkb_email = payload["email"]
                request._pkb_scopes = payload.get("scopes", [])
                return f(*args, **kwargs)
        
        # No auth
        return {"error": "Authentication required", "code": "unauthorized"}, 401
    return decorated
```

Helper to get the authenticated email:
```python
def get_pkb_email():
    return getattr(request, '_pkb_email', None)
```

### T3.2 Replace `@login_required` on `/pkb/*` routes

Replace all 82 `@login_required` decorators in `endpoints/pkb.py` with `@pkb_auth_required`. Replace `get_session_identity()` email extraction with `get_pkb_email()`. This is a mechanical find-replace — the email resolution is the only thing that changes.

### T3.3 Scope enforcement

Map JWT scopes to operations:
- `read` — GET endpoints (search, list, export, resolve, autocomplete)
- `write` — POST/PUT/DELETE endpoints (add, edit, delete, bulk, import)
- `admin` — destructive operations (cleanup, sweep, bulk_action archive)

Add a `require_scope(scope)` decorator or check inside `pkb_auth_required`. Session-authenticated users get all scopes implicitly.

### T3.4 Error contract

Already handled — all endpoints use `json_error(...)`. For token-authenticated requests, ensure no HTML redirect on 401 (the dual-auth decorator returns JSON 401, not a redirect).

### T3.5 Rate limiting

Keep existing `@limiter.limit("...")` decorators. Consider per-token stricter limits (e.g., 60/min for token auth vs 200/min for session). Use `request._pkb_email + token_jti` as rate limit key for token requests.

---

## 6. Workstream 4 — Unified Auth & Token Management (G5)

### T4.1 Token issuance endpoint

```python
@pkb_bp.route("/pkb/token", methods=["POST"])
@login_required  # Session-only — must be logged in to mint
def pkb_mint_token():
    email, _, _ = get_session_identity()
    data = request.json or {}
    scopes = data.get("scopes", ["read", "write"])
    days = min(data.get("days", 365), 365)
    token = generate_token(MCP_JWT_SECRET, email, days=days, scopes=scopes)
    return jsonify({"token": token, "expires_in_days": days, "scopes": scopes})
```

### T4.2 Token management UI

In the `/memory/` standalone page (or a Settings section within PKB), add a "Connect External Tools" panel:
- "Generate Token" button with scope checkboxes (read, write, admin) and lifetime dropdown
- Display token once (copy button), never stored server-side
- "Revoke All Tokens" button
- Active token info (when `jti` tracking is added)

### T4.3 Revocation

**Phase 1 (simple):** Per-user `token_version` integer stored in a lightweight JSON/SQLite table. JWT includes `ver` claim. Verifier checks `payload["ver"] >= user_current_version`. "Revoke All" bumps the version → all old tokens instantly invalid.

**Phase 2 (granular):** Add `jti` (JWT ID) claim to each token. Store issued `jti`s with metadata (created_at, label, last_used). Allow revoking individual tokens by `jti`. Check `jti` against a `revoked_jtis` set on each request.

### T4.4 Single secret, single verifier

Both MCP and REST validate against `MCP_JWT_SECRET`. One token works everywhere (G5). Document: rotating the secret invalidates all tokens — provide a "Revoke All + regenerate" workflow in the UI.

### Security considerations
- Tokens grant per-user PKB access — enforce HTTPS-only (already the case).
- Write scopes default to 90-day lifetime; read-only can be 365 days.
- Audit log: record token-authenticated calls (endpoint, email, timestamp) in a lightweight table for abuse detection.
- Never log token values, only `jti` or last-4-chars.

---

## 7. Workstream 5 — Agent Integration Recipes (G6)

### T5.1 Claude Code MCP configuration

```json
{
  "mcpServers": {
    "pkb": {
      "type": "url",
      "url": "https://assist-chat.site/mcp/pkb/",
      "headers": {
        "Authorization": "Bearer <YOUR_TOKEN>"
      }
    }
  }
}
```

Document all 27 tools with one-line descriptions. Note: client should pass their email in `user_email` parameter (server overrides with JWT email for security, but clients should still provide it for tool schema compliance).

### T5.2 OpenCode / Cursor MCP configuration

Same pattern as Claude Code but with OpenCode's config format (`opencode.json` / `mcp` section).

### T5.3 REST quickstart (curl examples)

```bash
# Search memories
curl -H "Authorization: Bearer $TOKEN" \
  "https://assist-chat.site/pkb/search" \
  -d '{"query": "python async patterns", "limit": 5}'

# Add a claim
curl -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "https://assist-chat.site/pkb/claims" \
  -d '{"statement": "FastAPI uses Starlette under the hood", "claim_type": "fact", "context_domain": "python"}'

# NL command
curl -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "https://assist-chat.site/pkb/nl_command" \
  -d '{"command": "what do I know about kubernetes?"}'
```

### T5.4 Documentation

Create `documentation/features/truth_management_system/external_access.md`:
- Token generation (UI + CLI)
- MCP setup for Claude Code, OpenCode, Cursor
- REST API authentication
- Scope descriptions
- Revocation
- Troubleshooting

Cross-link from: `documentation/README.md`, `documentation/product/ops/mcp_server_setup.md`, project `readme.md`.

---

## 8. Implementation Milestones

| Milestone | Tasks | Dependency | Effort |
|-----------|-------|------------|--------|
| **M1 — MCP security fix** | T2.1 (user_email override) | None | Small — critical security fix |
| **M2 — Token issuance + dual auth** | T4.1, T3.1, T3.2, T3.3 | M1 | Medium — enables all external access |
| **M3 — MCP external deployment** | T2.2, T2.3, T2.4 | M1, M2 | Small — nginx config + verification |
| **M4 — Standalone UI** | T1.1, T1.2, T1.3, T1.4 | None (independent) | Medium — JS refactor + new page |
| **M5 — Token management UI** | T4.2, T4.3 | M2, M4 | Medium |
| **M6 — Integration docs** | T5.1–T5.4 | M2, M3 | Small |

**Recommended order:** M1 → M2 → M3 → M6 (external access fully working), then M4 → M5 (standalone UI) in parallel or after.

---

## 9. Risks & Cross-Cutting Concerns

- **`user_email` trust in MCP (critical):** The plan MUST fix this before any external exposure. Currently any valid token holder can impersonate any user. M1 is a hard prerequisite for M3.
- **Auth redirect vs 401:** Browser paths (session) redirect to `/login`; token paths must return JSON 401. The `pkb_auth_required` decorator handles this by checking auth type before responding.
- **`pkb-manager.js` refactor risk (T1.1):** The IIFE pattern + 9 tabs + many event handlers make refactoring non-trivial. Gate all `.modal()` calls behind `isModal` flag. Test both surfaces.
- **Shared CSS/JS deps:** `memory.html` needs a subset of what `interface.html` loads. Audit and extract minimal deps to avoid loading the entire chat UI.
- **Secret rotation:** Single `MCP_JWT_SECRET` for everything — rotation invalidates all tokens. Document the procedure + provide "Revoke All + regenerate" in UI.
- **Rate limiting abuse:** External tokens widen attack surface. Per-token limits + audit log required.
- **CORS:** Not needed for server-side agents (Claude Code, OpenCode). Only add if browser-based external clients are intended (future).

---

## 10. Files Likely Touched

| File | Changes |
|------|---------|
| `mcp_server/pkb.py` | Override `user_email` with JWT email in each tool |
| `mcp_server/auth.py` | Add `token_version` check to `verify_jwt`; expose authenticated email |
| `endpoints/pkb_auth.py` (new) | `pkb_auth_required` dual-auth decorator, `get_pkb_email()` |
| `endpoints/pkb.py` | Replace `@login_required` with `@pkb_auth_required`; add `/pkb/token` |
| `endpoints/static_routes.py` | `/memory` route |
| `interface/memory.html` (new) | Standalone PKB shell page |
| `interface/pkb-manager.js` | Add `init(container)`, `isModal` gate, `openByReference(ref)` |
| `interface/common-utils.js` (new, optional) | Extracted shared utilities (showToast, escapeHtml) |
| nginx config | Add `/mcp/pkb/` location block |
| `documentation/features/truth_management_system/external_access.md` (new) | Integration guide |
| `documentation/product/ops/mcp_server_setup.md` | Update tool counts (27), add external access section |
| `documentation/README.md` | Add external access entry |

---

## 11. Open Questions

1. ~~Subdomain vs path for MCP exposure?~~ **Resolved:** Use `/mcp/pkb/` path — config already prepared in `nginx_mcp_blocks.conf`.
2. Default token lifetime: 365 days for read, 90 days for write? Or uniform 365?
3. Should `/memory/` support PWA install (add to `manifest.json`)?
4. For revocation phase 1, use SQLite table (per-user `token_version`) or the existing user JSON config?
5. Should token-authenticated REST requests get the same rate limits as session requests, or stricter?
6. When overriding `user_email` in MCP tools — log a warning when client-supplied value differs from JWT email, or silently override?

---

## 12. Resolved Decisions (from original draft)

| Decision | Resolution |
|----------|-----------|
| 8 vs 15 MCP tools | Now 27 tools (19 baseline + 8 full) post v1.0 |
| 7-tab modal | Now 9 tabs (added Overview + Maintenance in v1.0) |
| JWT vs opaque API keys | JWT — reuses existing `mcp_server/auth.py` infrastructure |
| Iframe vs shared template for standalone UI | Shared template first; iframe only if CSS conflicts arise |
| Route conflict: `/pkb/claims/bulk` | Resolved — new bulk action uses `/pkb/claims/bulk_action` |
