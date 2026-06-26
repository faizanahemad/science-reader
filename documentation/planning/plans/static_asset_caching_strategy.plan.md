# Static Asset Caching Strategy

## Motivation & Background

The app serves ~37 local JS/CSS files and ~22 CDN assets (in `interface.html` alone; `shared.html` adds ~10 local + ~20 CDN, `terminal.html` adds 1 local + 4 CDN). Today the caching story has several layers that don't work together cleanly:

1. **HTTP layer**: Flask serves all interface assets with `max_age=0` (must revalidate every request). Flask's `send_from_directory` does auto-set `Last-Modified` and `ETag` based on file mtime, so browsers *can* get `304 Not Modified` — but they must make a network round-trip every time.

2. **Service Worker layer**: The SW (CACHE_VERSION `"v50"`) is the real caching layer. Despite comments suggesting StaleWhileRevalidate, the actual strategy for same-origin and CDN assets is **CacheFirst when fresh (< 6h TTL), NetworkFirst when stale** — it blocks on the network when stale, with stale fallback only on network failure. It precaches ~22 URLs on install. But:
   - 17 local files loaded by `interface.html` are missing from the precache list
   - 4 precached files have a `?v=N` query string in the HTML that doesn't match the bare precache URL, making the precache entry useless
   - 3 CDN allowlist hosts (`cdn.datatables.net`, `mozilla.github.io`, `laingsimon.github.io`) are not referenced in `interface.html` but **are still used by `shared.html`** — cannot remove without breaking shared page caching
   - No intra-cache cleanup: old entries within the same `CACHE_VERSION` are never removed — they accumulate until the entire cache bucket is deleted by a version bump

3. **Cache busting**: Only 7 of ~37 local files have manual `?v=N` query strings. The rest are bare URLs. Version numbers are not synchronized. There is no automated hash-based cache busting.

4. **CDN integrity**: Only 5 of 22 CDN references in `interface.html` have SRI `integrity` hashes. `shared.html` also has 5 of ~20. `terminal.html` has 0 of 4.

5. **No build step**: `interface.html` is a raw static file. There is no bundler, no build pipeline, no Jinja2 templating. All JS files are unbundled source.

### The core problem

When a developer edits a JS file and deploys, users may get the stale version from the SW cache for up to 6 hours (the TTL). The only reliable invalidation is manually bumping `CACHE_VERSION` in `service-worker.js`, which forces a full re-download of everything — there's no way to invalidate just one file.

Without the SW (first visit, private browsing, SW update in progress), every asset triggers a network round-trip because `max_age=0`. Flask's auto `ETag`/`Last-Modified` means these can be `304` responses (fast, no body), but it's still one round-trip per file (~37 requests).

### What we want

- **Returning users (SW active)**: Assets served instantly from cache. When a file changes, only that file is re-fetched — not everything.
- **First visit / no SW**: Assets cached by the browser with long-lived HTTP headers. Cache busting via URL ensures stale files are never served.
- **Developer workflow**: Zero manual version bumping. Deploy and it works.
- **CDN assets**: Properly integrity-checked, properly cached.

---

## Current State: Detailed Audit

### A. Service Worker Precache vs Actual Assets

**Precached (22 URLs in `PRECACHE_URLS`):**
- `/interface` (HTML shell)
- 3 CSS: `style.css`, `workspace-styles.css`, `css_patched_mobile_view.css`
- 17 JS: `parseMessageForCheckBoxes.js`, `common.js`, `rendered-state-manager.js`, `gamification.js`, `common-chat.js`, `markdown-editor.js`, `interface.js`, `codemirror.js`, `doubt-manager.js`, `clarifications-manager.js`, `temp-llm-manager.js`, `context-menu-manager.js`, `prompt-manager.js`, `pkb-manager.js`, `chat.js`, `workspace-manager.js`, `audio_process.js`, `file-browser-manager.js`, `tool-call-manager.js`
- 2 icons: `app-icon.svg`, `maskable-icon.svg`

**Missing from precache (17 local files loaded by HTML):**
- 1 CSS: `dark-mode.css`
- 16 JS: `lazy-libs.js`, `local-docs-manager.js`, `notification-manager.js`, `artefacts-manager.js`, `global-docs-manager.js`, `extension-bridge.js`, `page-context-manager.js`, `content-viewer.js`, `tab-picker-manager.js`, `workflow-manager.js`, `script-manager.js`, `image-gen-manager.js`, `cross-conversation-search.js`, `compare-manager.js`, `desktop-bridge.js`, `tab-manager.js`

**Query string mismatch (precache URL won't match browser request):**
- HTML loads `style.css?v=29` but precache has `/interface/interface/style.css` (no `?v=`)
- Same for `css_patched_mobile_view.css?v=29`, `tool-call-manager.js?v=1`, `file-browser-manager.js?v=27`

**CDN allowlist entries not in `interface.html` but used by `shared.html`:**
- `cdn.datatables.net` — DataTables JS/CSS in `shared.html`
- `mozilla.github.io` — pdf.js in `shared.html`
- `laingsimon.github.io` — drawio-renderer in `shared.html`

These hosts cannot be removed from the SW allowlist (see updated Task 5c).

### B. Manual `?v=N` Status

Files WITH `?v=N` (7 of ~37):
| File | Version |
|------|---------|
| `css_patched_mobile_view.css` | `?v=29` |
| `style.css` | `?v=29` |
| `tool-call-manager.js` | `?v=1` |
| `artefacts-manager.js` | `?v=20` |
| `image-gen-manager.js` | `?v=1` |
| `cross-conversation-search.js` | `?v=1` |
| `file-browser-manager.js` | `?v=27` |

Files WITHOUT `?v=N`: the remaining ~30 local JS/CSS files.

### C. CDN SRI Integrity Status

WITH integrity + crossorigin (5):
- jQuery UI CSS, jQuery UI JS, mermaid JS, Bootstrap CSS, Bootstrap bundle JS

WITHOUT integrity (15+):
- KaTeX JS, KaTeX CSS, marked-katex-extension, highlight.js CSS, highlight.js JS, uuid, marked, MathJax, jQuery, animate.css, bootstrap-select JS, bootstrap-select CSS, Bootstrap Icons, Font Awesome, bootstrap-toggle CSS/JS, jsTree CSS/JS

### D. `shared.html` Issues (discovered during plan revision)

`shared.html` has several problems beyond just needing hash injection:

1. **Duplicate script/link tags**: `popper.js` loaded twice (lines 68 & 133), `bootstrap-toggle.min.js` loaded twice (lines 70 & 136), `bootstrap-toggle.min.css` loaded twice (lines 69 & 135). These cause double-parsing and potential issues.
2. **highlight.js version mismatch**: CSS is version 10.7.2 (line 10) but JS is version 11.9.0 (line 11). Themes may not match correctly.
3. **Bootstrap Icons version discrepancy**: `shared.html` uses 1.7.2 (line 61), `interface.html` uses 1.11.3 (line 60). Missing newer icons on shared pages.
4. **MathJax vs KaTeX divergence**: `shared.html` actively loads MathJax (line 15) which `interface.html` has commented out (line 19) in favor of KaTeX. Shared pages render math differently.
5. **External pdf.js**: `shared.html` loads pdf.js from `mozilla.github.io` (line 19) while `interface.html` uses the local `/interface/pdf.js/` bundle. The shared page depends on a third-party CDN that could go down.
6. **Shared uses DataTables + drawio-renderer** (lines 36, 39, 31) from CDN hosts that only `shared.html` uses — these CDN hosts must remain in the SW allowlist.
7. **No auth**: `shared.html` is served at `/shared/<conversation_id>` without `@login_required`, so the 403 auth fix doesn't apply — but hash injection still should.

These issues pre-date the caching plan but should be noted as they affect CDN allowlist decisions, SRI scope, and the completeness of shared page caching. A dedicated cleanup task (Task 11) is added below.

### E. HTTP Cache Headers by Route

| Route | `max_age` | Notes |
|-------|-----------|-------|
| `/interface` (HTML) | 0 | Always revalidate (correct) |
| `/interface/service-worker.js` | 0 (or `no-store` with `--no-cache`) | Always revalidate (correct) |
| `/interface/<path>` (JS/CSS assets) | 0 | Always revalidate (the problem) |
| PWA manifest + icons | 2,592,000 (30 days) + `immutable` | Long cache (correct) |
| `/static/<path>` | Flask default (~12h) | Reasonable |
| `/favicon.ico`, `/loader.gif` | Flask default (~12h) | Reasonable |

---

## Strategy

### Approach: Server-side content hashing with `immutable` HTTP headers

Since there's no build step and `interface.html` is served as a raw static file, we need a lightweight mechanism that:
1. Computes content hashes for local JS/CSS files at server startup
2. Injects `?h=<hash>` into `interface.html` when serving it (switch from `send_from_directory` to a templated response)
3. Serves assets with long-lived `Cache-Control: public, max-age=31536000, immutable` when the request has a `?h=` parameter
4. Keeps `max_age=0` for requests without hash parameters (development, direct URL access)

This gives us:
- **Automatic cache busting**: File changes produce a new hash, which produces a new URL, which bypasses all caches
- **Long-lived HTTP caching**: Browser caches the hashed URL for 1 year; never revalidates until the hash changes
- **SW works correctly**: SW caches the hashed URL; new hashes mean new cache entries
- **Zero manual version bumping**: No more `?v=N` to maintain
- **No build step**: Hashes computed at server startup, HTML injection at serve time

### Why not a build step?

The project has no bundler and all JS files are unbundled source. Introducing webpack/vite/rollup would be a large change that affects the entire development workflow. The server-side approach achieves the same caching benefits with minimal disruption.

### Why not just fix the SW precache list?

Fixing the precache list helps with offline support but doesn't solve:
- HTTP-layer caching for non-SW scenarios
- Per-file cache invalidation (SW still uses a global version bump)
- The manual `?v=N` maintenance problem

---

## Tasks

### Task 1: Server-side asset hash registry (Python)

**File:** `endpoints/static_routes.py`

At server startup, compute SHA-256 content hashes for all JS/CSS files in the `interface/` directory. Store as a dict: `{ "common.js": "a1b2c3d4", "style.css": "e5f6g7h8", ... }`. Use first 8 hex chars of the hash (sufficient for cache busting, keeps URLs short). Also compute a composite hash of all values for use as dynamic `CACHE_VERSION` (Task 8).

```python
import hashlib, os

_asset_hashes = {}  # "filename" -> "8-char hex hash"
_composite_hash = ""  # hash of all hashes, for CACHE_VERSION

def _compute_asset_hashes():
    """Compute content hashes for all interface JS/CSS assets at startup."""
    global _composite_hash
    interface_dir = os.path.join(os.path.dirname(__file__), '..', 'interface')
    # Directories to skip — third-party bundles with internal references
    skip_dirs = {'pdf.js'}
    for root, dirs, files in os.walk(interface_dir):
        # Prune skip_dirs from walk
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith(('.js', '.css')):
                filepath = os.path.join(root, f)
                relpath = os.path.relpath(filepath, interface_dir).replace('\\', '/')
                with open(filepath, 'rb') as fh:
                    content_hash = hashlib.sha256(fh.read()).hexdigest()[:8]
                _asset_hashes[relpath] = content_hash
    
    # Composite hash for CACHE_VERSION
    all_hashes = '|'.join(f'{k}={v}' for k, v in sorted(_asset_hashes.items()))
    _composite_hash = hashlib.sha256(all_hashes.encode()).hexdigest()[:8]
```

**Call `_compute_asset_hashes()` once** in the blueprint registration or app setup, before any request is served.

**Development mode:** In debug mode, the HTML injection function (Task 2) skips caching and re-reads files on every request. However, the hash registry itself is computed once at startup. If a developer edits a JS file, they need to restart the server to pick up the new hash. This is acceptable since Flask debug mode with `use_reloader=True` already restarts on file changes. Alternatively, wrap the hash computation in a `before_request` hook in debug mode that checks mtimes — but this adds complexity for little gain since the reloader handles it.

**Exclude `service-worker.js` from hashing** since it gets dynamic `CACHE_VERSION` injection (Task 8) — its hash would change every time any other file changes, which is the correct behavior but doesn't need its own `?h=` parameter (it's served with `max_age=0` anyway).

### Task 2: Inject hashes into interface.html at serve time

**File:** `endpoints/static_routes.py`

Change the `/interface` route from `send_from_directory` to reading the file and performing string replacements. Replace all `interface/<filename>` and `interface/<filename>?v=N` references with `interface/<filename>?h=<hash>`.

```python
import re

_cached_html = {}  # keyed by filename, stores (processed_html, source_mtime)

def _inject_asset_hashes(html_content):
    """Replace interface/foo.js(?v=N) with interface/foo.js?h=<hash> in HTML."""
    def replace_asset_ref(match):
        prefix = match.group(1)       # 'src="' or 'href="' etc.
        iface_path = match.group(2)   # 'interface/' or '/interface/'
        filename = match.group(3)     # 'common.js' or 'style.css'
        h = _asset_hashes.get(filename, '')
        if h:
            return f'{prefix}{iface_path}{filename}?h={h}'
        return match.group(0)  # no hash available, leave as-is
    
    # Match src="interface/..." or href="interface/..." or src="/interface/..." patterns.
    # The optional leading / handles both relative paths (interface.html) and
    # absolute paths (shared.html, terminal.html).
    # This avoids false matches on CDN URLs or inline JS strings.
    # Captures: (attribute_prefix)(optional_slash)(filename.ext) — strips any existing ?v=N
    return re.sub(
        r'((?:src|href)=["\'])(/?interface/)([\w\-./]+\.(?:js|css))(?:\?v=\d+)?',
        replace_asset_ref,
        html_content
    )

@app.route('/interface')
@login_required
def serve_interface():
    return _serve_html_with_hashes('interface.html')

def _serve_html_with_hashes(filename):
    """Read an HTML file, inject asset hashes, and return as response."""
    html_path = os.path.join('interface', filename)
    current_mtime = os.path.getmtime(html_path)
    
    cached = _cached_html.get(filename)
    if cached and cached[1] == current_mtime and not app.debug:
        html = cached[0]
    else:
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
        html = _inject_asset_hashes(html)
        if not app.debug:
            _cached_html[filename] = (html, current_mtime)
    
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers['Cache-Control'] = 'no-cache'  # HTML always revalidates
    return response
```

**Key design decisions:**
- Regex is anchored to `src=` or `href=` attribute contexts to avoid false matches on inline JS strings or CDN URLs.
- Cache keyed by `(filename, mtime)` — simpler than hashing the HTML itself and handles file edits during development.
- `_serve_html_with_hashes` is reusable for `interface.html`, `shared.html`, and `terminal.html`.
- In debug mode, always re-reads and re-processes (no caching). In production, caches until file changes.

Apply the same replacement in the catch-all route (conversation URL paths) that also serves `interface.html`.

**Other HTML files that reference local assets:**
- `interface/shared.html` — loads 1 CSS (`style.css`) + 9 JS files (including `shared.js`). Served via `endpoints/static_routes.py` at `/shared/<conversation_id>` (line 432) which already reads the file and does string replacement (injecting a `<div>` with the conversation ID). Add hash injection to the same code path. Note: `shared.html` has no auth (`@login_required` absent), so the 403 auth fix doesn't apply, but hash injection still should work for caching benefits.
- `interface/terminal.html` — loads 1 local JS (`opencode-terminal.js`). Served via `endpoints/terminal.py` at a terminal route (line 297, uses `send_from_directory` with `max_age=0`). Would need to switch to a read + replace + `make_response` pattern for hash injection, same as `interface.html`.

These are lower-traffic pages but should get the same treatment for consistency. The `shared.html` route already does dynamic string replacement, so adding hash injection is straightforward. The `terminal.html` route currently uses `send_from_directory` and would need to switch to a read + replace + `make_response` pattern, same as `interface.html`.

`login.html` and `render_mermaid.html` load only CDN assets (no local `interface/` files), so no changes needed.

### Task 3: Long-lived HTTP headers for hashed assets + auth fix (PARTIALLY DONE)

**File:** `endpoints/static_routes.py`

**Auth fix — DONE (commit 32189d2):** The 403 + `no-store` response for unauthenticated static asset requests is already implemented at `static_routes.py:361-369`. The `_is_static_asset()` helper and `_STATIC_ASSET_EXTENSIONS` frozenset are in place at lines 318-327.

**Remaining:** Add `?h=` detection in the catch-all route. In the catch-all `/interface/<path:path>` route, detect `?h=` in the query string. If present, serve the file with aggressive caching:

```python
@app.route('/interface/<path:path>')
def serve_interface_asset(path):
    # ... existing PWA / conversation-URL logic ...
    
    # For actual assets:
    has_hash = request.args.get('h')
    if has_hash:
        # Content-addressed URL: cache for 1 year, immutable
        resp = send_from_directory('interface', actual_path, max_age=31536000)
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return resp
    else:
        # No hash: revalidate every time (development, direct access)
        return send_from_directory('interface', actual_path, max_age=0)
```

**Auth fix — return 403 + no-store instead of 302 for static assets:**

The current auth check redirects unauthenticated requests to `/login` with a 302. With immutable caching, a 302 response could get cached by the browser's HTTP cache for a hashed URL, poisoning that cache entry. Since removing auth isn't viable (internet-facing server, DDoS concern), we instead return 403 Forbidden with `Cache-Control: no-store` for unauthenticated static asset requests (`.js`, `.css`, images, fonts). This prevents the error response from being cached.

```python
# In interface_combined_route, replace the current redirect for static assets:
if not loggedin or email is None:
    # For static asset requests, return 403 with no-store to prevent
    # cache poisoning of immutable hashed URLs
    if _is_static_asset(path):
        resp = make_response("Forbidden", 403)
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    return redirect("/login", code=302)

def _is_static_asset(path):
    """Check if the path is a static asset (not a conversation URL or HTML page)."""
    return path.rsplit('.', 1)[-1].lower() in {
        'js', 'css', 'svg', 'png', 'jpg', 'jpeg', 'gif', 'ico', 'woff', 'woff2', 'ttf', 'eot'
    }
```

The rate limiter (1000 req/min) already provides DDoS protection. Navigation requests (conversation URLs that serve `interface.html`) still get the 302 redirect to `/login` as before.

### Task 4: Remove manual `?v=N` from interface.html

Since Task 2 injects `?h=<hash>` automatically, remove all existing manual `?v=N` query strings from `interface.html`. This avoids the regex needing to handle both `?v=N` and `?h=<hash>`.

Files affected:
- `interface/interface.html` — 7 occurrences: `css_patched_mobile_view.css?v=29` (line 8), `style.css?v=29` (line 63), `tool-call-manager.js?v=1` (line 4950), `artefacts-manager.js?v=20` (line 4955), `image-gen-manager.js?v=1` (line 4976), `cross-conversation-search.js?v=1` (line 4977), `file-browser-manager.js?v=27` (line 4979)

### Task 5: Update service worker for hash-aware caching

**File:** `interface/service-worker.js`

Changes needed:

**5a. Remove the `PRECACHE_URLS` array entirely (or make it empty).**

Precaching with content hashes doesn't work well because the SW doesn't know the current hashes. The HTML page (which contains the hashed URLs) is the source of truth. Instead, the SW's runtime caching strategy will cache assets on first load — which happens immediately on page load since the HTML references them all.

**Decision:** Remove precaching. The precache list was already broken (17 missing files, 4 mismatched URLs). The runtime cache strategy handles subsequent visits. If offline-first on first visit is needed later, add an `/interface/asset-manifest.json` endpoint.

**5b. Hash-aware caching works naturally** because Cache API matches by full URL including query string. A new hash = a new URL = a cache miss = network fetch + cache store. The existing CacheFirst-when-fresh / NetworkFirst-when-stale strategy handles this correctly.

**However**, old hashed entries (`common.js?h=abc123`) will **accumulate** alongside new ones (`common.js?h=def456`) within the same cache bucket, since there is no intra-cache cleanup logic. Over many deployments this wastes storage. Two mitigations:

1. **Dynamic `CACHE_VERSION` (Task 8)** means any file change triggers a new SW version, which deletes the old cache bucket on activate — so stale entries only live until the next deploy.
2. **(Optional, lower priority)** Add a cleanup step in the SW `activate` handler that enumerates entries in the current cache, groups by base path (strip `?h=`), and deletes duplicates keeping only the most recent. This is defensive and low-priority because Task 8 already provides the primary cleanup.

**5c. ~~Clean up stale CDN allowlist entries~~ REVISED: Keep all CDN allowlist entries.** Originally planned to remove `cdn.datatables.net`, `mozilla.github.io`, `laingsimon.github.io`. However, `shared.html` still actively loads assets from all three hosts (DataTables JS/CSS, pdf.js from Mozilla, drawio-renderer from laingsimon). These are not stale — they're just not used by `interface.html`. The SW caches shared page assets too, so these hosts must remain in the allowlist. No changes to `CDN_ALLOWLIST_HOSTS`.

**5d. Adjust cache cleanup on activate:** Currently deletes old `ui-shell-*` and `meta-*` cache buckets by name. This is still correct — when `CACHE_VERSION` changes (now dynamic via Task 8), all old entries are purged.

**5e. Increase TTL from 6 hours to 30 days.** The current implementation is CacheFirst when the entry is fresh (< 6h TTL), and NetworkFirst when stale — it `await`s the network fetch when stale, blocking the response. A stale cached copy is only used as offline fallback (when `fetch()` throws). With content-hashed URLs and `immutable` HTTP headers, the 6h TTL is unnecessarily aggressive because:
- **Same hash URL** = content hasn't changed = the cached response is correct indefinitely
- **Different hash URL** = new URL = cache miss = network fetch regardless of TTL

For CDN assets (which don't have `?h=`), a longer TTL reduces unnecessary re-fetches for versioned CDN URLs (e.g., `katex@0.16.8/...`) whose content never changes.

**Decision:** Increase `TTL_6H` to `TTL_30D` (30 days = `30 * 24 * 60 * 60 * 1000`). This applies uniformly to both local hashed assets and CDN assets. CDN assets already include version numbers in their URLs, so 30 days is safe. The dynamic `CACHE_VERSION` (Task 8) ensures the entire cache bucket is purged on any deploy, so entries never actually reach 30 days in practice.

```js
// Before:
const TTL_6H = 6 * 60 * 60 * 1000;
// After:
const TTL_30D = 30 * 24 * 60 * 60 * 1000;  // 30 days
```

### Task 6: Add SRI integrity hashes to CDN assets

**File:** `interface/interface.html`

Generate SRI hashes for all CDN assets that currently lack them. This is a security measure (prevents CDN compromise from injecting malicious code) and also enables browsers to cache CDN responses more aggressively (the integrity hash proves the content is correct regardless of source).

For each CDN asset without `integrity`:
1. Fetch the file: `curl -s <URL> | openssl dgst -sha384 -binary | openssl base64 -A`
2. Add `integrity="sha384-<hash>" crossorigin="anonymous"` to the tag

Priority: All JS files first (executable code), then CSS files.

CDN assets needing integrity hashes in `interface.html` (17):
- JS: `katex.min.js`, `marked-katex-extension`, `highlight.js` JS, `uuid`, `marked`, `jquery-3.5.1.min.js`, `bootstrap-select.min.js`, `bootstrap-toggle.min.js`, `jstree.min.js`
- CSS: `katex.min.css`, `highlight.js` CSS, `animate.css`, `bootstrap-select.min.css`, `bootstrap-icons.css`, `font-awesome.css`, `bootstrap-toggle.min.css`, `jstree` dark theme CSS

CDN assets needing integrity in `shared.html` (~15) and `terminal.html` (4) should also get SRI hashes for consistency.

### Task 7: Update `--no-cache` mode

The `--no-cache` flag currently only modifies `service-worker.js`. With the new hashing system:
- In `--no-cache` mode, skip hash injection (serve bare URLs with `max_age=0`)
- Or: still inject hashes but set `Cache-Control: no-store` on all assets

Recommendation: In `--no-cache` mode, skip hash injection entirely. This makes `interface.html` serve with bare URLs and `max_age=0`, and assets serve with `max_age=0`. The SW gets its `nocache-<nonce>` version which purges caches. This gives a fully uncached experience for development.

### Task 8: Inject service worker CACHE_VERSION dynamically

Currently `CACHE_VERSION` in `service-worker.js` must be manually bumped. With content hashing in place, we use the `_composite_hash` (computed in Task 1) as the `CACHE_VERSION` — injected at serve time the same way `--no-cache` already injects a nonce.

This means: whenever any interface file changes, the composite hash changes, the SW gets a new version string, browsers detect the byte difference, trigger a re-install, and the activate handler deletes the old cache bucket. No manual version bumping needed.

**File:** `endpoints/static_routes.py` — modify the existing `/interface/service-worker.js` route:

```python
# In the service-worker.js route (normal mode, not --no-cache):
sw_path = os.path.join('interface', 'service-worker.js')
with open(sw_path, 'r', encoding='utf-8') as f:
    sw_content = f.read()

# Inject composite hash as CACHE_VERSION
sw_content = re.sub(
    r'const CACHE_VERSION = "[^"]*"',
    f'const CACHE_VERSION = "v-{_composite_hash}"',
    sw_content
)

response = make_response(sw_content)
response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
response.headers['Cache-Control'] = 'no-cache'  # SW always revalidates
response.headers['Service-Worker-Allowed'] = '/interface/'
return response
```

**Note:** This changes the SW route from `send_from_directory` to a read + replace + `make_response`, the same pattern as `--no-cache` mode already uses. The `--no-cache` mode continues to use its nonce (Task 7). The normal mode uses the composite hash. The two modes share the same code path with different version strings.

**Impact on `CACHE_VERSION` in source:** The hardcoded `"v50"` in `service-worker.js` on disk becomes a placeholder that is always overridden at serve time. It can be kept as a comment or fallback for local development without the server.

### Task 9: Sync UI_CACHE_VERSION with composite hash

`window.UI_CACHE_VERSION` in `common.js` (currently `"v24"`) controls IndexedDB rendered-state snapshot invalidation. It should be bumped whenever rendering-affecting code changes.

Option A: Inject it dynamically via the same HTML replacement mechanism (add a `<script>window.UI_CACHE_VERSION="v-<hash>"</script>` in the HTML, or replace the value in common.js at serve time).

Option B: Keep it manual. Rendering snapshots should only be invalidated when rendering logic changes, not when any file changes. A content hash of just `common.js` + `common-chat.js` + `rendered-state-manager.js` would be more appropriate than a composite of all files.

Recommendation: Option B for now. `UI_CACHE_VERSION` is conceptually different from `CACHE_VERSION` and should remain manually controlled. Document this clearly.

### Task 10: Fix logout cleanup gaps — DONE (commit 32189d2)

Two pre-existing gaps in the logout flow, both fixed:

**10a. Add `localStorage.clear()` to `clearSwCaches()` in `interface/common.js`**

Currently ~21 `localStorage` keys across 6+ modules survive logout: chat settings state, sidebar collapse state, auto-scroll preference, global docs view mode, message editor type, pdf.js preferences. These should be cleared on logout to avoid leaking one user's preferences to the next session.

Add `localStorage.clear()` in `clearSwCaches()` (at `common.js:6914-6966`), after the `ConversationUIState.clear()` step. This is a blanket clear — simpler and safer than tracking individual keys.

**10b. Change `session.pop()` to `session.clear()` in `/logout` endpoint**

The main `/logout` endpoint at `endpoints/auth.py:237-248` only pops `name` and `email` from the Flask session. Other session keys survive. The `/ext/auth/logout` and `/clear_session` endpoints already use `session.clear()`. The main `/logout` should be consistent.

```python
# Before:
session.pop("name", None)
session.pop("email", None)

# After:
session.clear()
```

### Task 11: Clean up `shared.html` asset issues (NEW)

**File:** `interface/shared.html`

`shared.html` has accumulated several issues that affect caching, correctness, and CDN dependency scope. These should be fixed alongside the caching work:

**11a. Remove duplicate script/link tags:**
- `popper.js` is loaded twice (lines 68 & 133) — remove the duplicate
- `bootstrap-toggle.min.js` loaded twice (lines 70 & 136) — remove the duplicate
- `bootstrap-toggle.min.css` loaded twice (lines 69 & 135) — remove the duplicate

**11b. Fix highlight.js version mismatch:**
- CSS is version 10.7.2 (line 10): `//cdnjs.cloudflare.com/ajax/libs/highlight.js/10.7.2/styles/default.min.css`
- JS is version 11.9.0 (line 11): `https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js`
- Update the CSS to 11.9.0 to match the JS (and match `interface.html`)

**11c. Update Bootstrap Icons version:**
- `shared.html` uses 1.7.2 (line 61), `interface.html` uses 1.11.3 (line 60)
- Update `shared.html` to 1.11.3 for consistency and access to newer icons

**11d. (Optional, deferred) Consider MathJax → KaTeX migration:**
- `shared.html` actively loads MathJax (line 15) while `interface.html` has switched to KaTeX
- This is a behavioral change that may affect math rendering on shared pages — defer unless explicitly wanted

**11e. (Optional, deferred) Consider local pdf.js for shared.html:**
- `shared.html` uses external `mozilla.github.io/pdf.js` while `interface.html` uses the local bundle
- Switching would remove a CDN dependency but may change PDF rendering behavior — defer

**Priority:** Medium. 11a-11c are quick fixes. 11d-11e are larger changes that should be separate.

---

## Task Dependency Order

```
Task 1 (hash registry)
  └─> Task 2 (inject into HTML — regex handles both absolute and relative paths)
       └─> Task 3 (long-lived headers for hashed assets — auth fix already DONE)
            └─> Task 4 (remove manual ?v=N)
                 └─> Task 5 (update service worker: remove precache, TTL 6h→30d, keep CDN allowlist)

Task 6 (SRI hashes) — independent, can be done in parallel

Task 7 (--no-cache mode) — after Tasks 1-3

Task 8 (dynamic CACHE_VERSION) — after Task 1, can parallel with 2-5

Task 9 (UI_CACHE_VERSION decision) — after Task 8, documentation only

Task 10 (logout cleanup: localStorage.clear + session.clear) — DONE (commit 32189d2)

Task 11 (shared.html cleanup: duplicates, versions) — independent, can be done in parallel with Tasks 1-9
```

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| HTML injection regex breaks an asset URL | Unit test the regex against all current URLs in interface.html, shared.html, terminal.html. Include edge cases (paths with hyphens, dots, nested paths like `icons/app-icon.svg`, absolute vs relative paths). |
| Hash computation slows server startup | Startup hash of ~40 small files is <50ms. Not a concern. |
| `interface.html` is no longer byte-for-byte identical to disk | This is intentional. The `/interface` route already does `max_age=0` so the browser always gets the fresh version. Add a comment in the route explaining the injection. |
| Service worker sees different URLs after hash change, doesn't clean old entries | The SW `activate` handler already deletes old versioned caches. With dynamic `CACHE_VERSION` (Task 8), a file change triggers a new SW version which cleans old caches. |
| CDN SRI hash becomes wrong after CDN update | CDN URLs include version numbers (e.g., `katex@0.16.8`). The content at a versioned URL never changes. SRI hash is safe. |
| `--no-cache` mode breaks with new injection | Task 7 explicitly handles this by skipping injection in `--no-cache` mode. Check `app.config.get("SW_CACHE_NONCE")` in `_serve_html_with_hashes()`. |
| Shared/login pages don't get hashed URLs | `shared.html` and `terminal.html` also load local assets (10 and 1 respectively). Task 2 covers these — the regex now handles both absolute (`/interface/...`) and relative (`interface/...`) paths. `login.html` and `render_mermaid.html` load CDN-only, no changes needed. |
| Dynamic JS-loaded CDN assets aren't covered | `lazy-libs.js` dynamically loads ~20 CDN scripts (CodeMirror, Reveal.js, EasyMDE, drawio-renderer) and dark mode toggles highlight.js theme CSS. These are all CDN URLs loaded via `document.createElement('script')`, not from `<script>` tags in HTML. The SW's CDN allowlist caching handles these correctly. SRI hashes cannot be applied to dynamically created script elements without modifying the JS loader code — this is a separate concern from Task 6 (which covers `<script>`/`<link>` tags only). |
| Auth-gated assets + immutable caching = 302 cache poisoning | Task 3 replaces the 302 redirect with 403 + `Cache-Control: no-store` for static asset requests when unauthenticated. The `no-store` header prevents the browser from caching the error response under the hashed URL. Navigation requests still get the 302 redirect. Rate limiter (1000 req/min) provides DDoS protection. |
| Browser HTTP cache survives logout | Intentional. `clearSwCaches()` clears SW caches and unregisters the SW, but the browser's HTTP disk cache is not clearable by JavaScript. Cached files are static JS/CSS with no user data — not a privacy concern. A different user logging in gets the same files (or different hashes if files changed). |
| Hash computation placement with Flask reloader | Ensure `_compute_asset_hashes()` runs during blueprint registration / app factory setup, not at module import time. With `use_reloader=True`, module-level code runs in both the parent (reloader) and child (server) processes. Blueprint registration runs only in the child. |
| `localStorage` leaks across sessions on logout | Task 10 adds `localStorage.clear()` to `clearSwCaches()`. Blanket clear is simpler and safer than tracking individual keys. DONE. |
| CDN allowlist removal breaks `shared.html` caching | REVISED: Keep all 7 CDN allowlist hosts. The 3 hosts originally marked stale (`cdn.datatables.net`, `mozilla.github.io`, `laingsimon.github.io`) are actively used by `shared.html`. Removing them would cause SW to skip caching for shared page CDN assets. |
| New JS files added without plan update | `tab-manager.js` was added after original plan. The hash registry (Task 1) auto-discovers files via `os.walk`, so new files are automatically included. But precache list counts and audit sections must be kept current. |
| `shared.html` duplicates and version mismatches | Task 11 addresses these. Duplicates cause double-loading; version mismatches may cause subtle rendering differences. |
| `terminal.html` served from different module | `terminal.html` is served from `endpoints/terminal.py:297`, not `static_routes.py`. Hash injection for terminal requires modifying `terminal.py`, not the static routes catch-all. |

## Verification

After implementation:

1. **Normal mode:** Open DevTools Network tab. Verify all JS/CSS URLs have `?h=<8chars>`. Verify `Cache-Control: public, max-age=31536000, immutable` on asset responses. Verify HTML has `Cache-Control: no-cache`.
2. **Cache hit:** Reload the page. Verify assets are served from disk cache (size column shows `(disk cache)` or `(memory cache)`). No 304 round-trips.
3. **Cache bust:** Edit a JS file, restart server. Verify the hash changed in the HTML. Verify the browser fetches the new version (not cached).
4. **No SW scenario:** Unregister the service worker. Reload. Verify assets are still cached by the browser via HTTP headers.
5. **`--no-cache` mode:** Start server with `--no-cache`. Verify no `?h=` in URLs. Verify `max_age=0` on assets.
6. **SRI:** In DevTools Console, verify no SRI errors. Intentionally corrupt an integrity hash and verify the browser blocks the script.
7. **Auth expired:** Open a private window, request an asset URL like `/interface/interface/style.css?h=abc123` directly without logging in. Verify 403 response with `Cache-Control: no-store` (not a 302 redirect).
8. **Shared page:** Visit `/shared/<conversation_id>`. Verify asset URLs in the HTML source have `?h=<hash>` with absolute paths (`/interface/style.css?h=...`).
9. **Logout cleanup:** ~~Log in, browse around (populate localStorage, SW caches, IndexedDB). Log out. Verify: SW caches deleted, SW unregistered, localStorage empty, IndexedDB cleared, Flask session fully cleared.~~ DONE (commit 32189d2). Verify after deployment.
10. **SW TTL:** After assets are cached by the SW, wait or manually edit the meta-cache timestamps to simulate >30 days. Verify the SW re-fetches (resolves from HTTP disk cache) and re-caches.
11. **Shared page CDN caching:** Visit `/shared/<conversation_id>`. Open DevTools Network tab. Verify DataTables, pdf.js, and drawio-renderer assets are cached by the SW (check Cache Storage). Confirm CDN allowlist hosts are not removed.
12. **Shared page duplicates (Task 11):** After cleanup, verify `shared.html` source has no duplicate script/link tags. Verify highlight.js CSS version matches JS version (11.9.0).

## Files Modified

| File | Changes |
|------|---------|
| `endpoints/static_routes.py` | Asset hash computation at startup, HTML injection via `_serve_html_with_hashes()`, regex handles both absolute and relative `interface/` paths, long-lived `immutable` headers for `?h=` assets, ~~403 + no-store for unauthed static asset requests~~ DONE, dynamic `CACHE_VERSION` injection in SW route, `--no-cache` mode updates |
| `endpoints/terminal.py` | Switch `terminal.html` serving from `send_from_directory` to read + inject + `make_response` for hash injection (line 297) |
| `interface/interface.html` | Remove manual `?v=N` query strings (7 occurrences), add SRI integrity hashes to ~17 CDN assets |
| `interface/shared.html` | Task 11: Remove duplicate script/link tags, fix highlight.js version mismatch, update Bootstrap Icons version. Hash injection happens at serve time via the `/shared/<conversation_id>` route — no direct hash edits. |
| `interface/service-worker.js` | Remove/empty `PRECACHE_URLS`, increase TTL from 6h to 30 days, ~~clean 3 stale CDN allowlist entries~~ keep all entries, add comments about hash-based caching |
| `interface/common.js` | ~~Add `localStorage.clear()` to `clearSwCaches()` function~~ DONE (commit 32189d2) |
| `endpoints/auth.py` | ~~Change `session.pop("name"/"email")` to `session.clear()` in `/logout` endpoint~~ DONE (commit 32189d2) |
| `interface/terminal.html` | No direct edits — hash injection happens at serve time via `endpoints/terminal.py` |

## Out of Scope

- **`interface/pdf.js/`**: The PDF.js viewer is a pre-built third-party distribution loaded via iframe (`viewer.html`). The iframe `src` reference to `interface/pdf.js/web/viewer.html` is an `.html` file, so the regex (which only matches `.js` and `.css`) won't touch it. However, `pdf.js/web/viewer.html` internally references its own JS/CSS files with relative paths (e.g., `viewer.js`, `viewer.css`). These relative paths don't start with `interface/`, so the regex won't match them even if viewer.html were processed. The hash registry will include `pdf.js/web/viewer.js` etc., but since they're never referenced as `interface/pdf.js/...` in any processed HTML file, no injection occurs. PDF.js assets are cached by the SW's runtime strategy. No changes needed.
- **Dynamically loaded CDN assets** (`lazy-libs.js`, dark mode CSS toggle): These are loaded via `document.createElement('script')` from JS code, not from HTML `<script>` tags. The SW's CDN allowlist caching handles them. SRI cannot be applied without modifying `lazy-libs.js` — this is a separate future concern.
- **API response caching**: Covered in a separate plan.
- **`login.html`, `render_mermaid.html`**: CDN-only assets, no local files to hash.
- **`shared.html` → local pdf.js migration**: `shared.html` uses external `mozilla.github.io/pdf.js` while `interface.html` uses the local bundle. Migrating `shared.html` to the local bundle would remove a CDN dependency but is a separate concern from caching.
- **`shared.html` MathJax → KaTeX migration**: `shared.html` uses MathJax while `interface.html` uses KaTeX. Different math rendering on shared pages. Migration is a separate concern.

## Decisions Log

Clarification decisions made during planning review:

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Auth on static assets with immutable caching | Return 403 + `Cache-Control: no-store` for unauthed static asset requests (instead of 302 redirect) | Prevents 302 cache poisoning of immutable hashed URLs. Can't remove auth entirely — internet-facing server, DDoS concern. Rate limiter provides additional protection. |
| 2 | Regex for absolute vs relative paths | Single regex handles both with optional leading `/`: `(/?interface/)` | `interface.html` uses relative paths, `shared.html`/`terminal.html` use absolute paths. One regex, no duplication. |
| 3 | Logout cleanup gaps (localStorage, session) | Fix now as part of this work (Task 10) | Small changes, low risk, improves hygiene. `localStorage.clear()` in `clearSwCaches()`, `session.clear()` in `/logout`. |
| 4 | Precaching strategy | Remove precaching entirely (empty `PRECACHE_URLS`) | Precache list was already broken (17 missing, 4 mismatched). Runtime caching on first page load is sufficient. Add manifest endpoint later if offline-first on first visit is needed. |
| 5 | SW TTL for cached assets | Increase from 6h to 30 days for all assets | Content-hashed URLs are correct forever (hash guarantees content). CDN URLs include version numbers. Dynamic `CACHE_VERSION` purges everything on each deploy anyway, so entries never actually reach 30 days. |
| 6 | Browser HTTP cache survives logout | Accepted, not a concern | JS/CSS files contain no user data. `clearSwCaches()` already handles SW caches, IndexedDB, and SW unregistration. Browser HTTP disk cache cannot be cleared by JavaScript — this is a browser limitation, not a bug. |
| 7 | CDN allowlist hosts for shared.html | Keep all 7 hosts (REVISED) | Originally planned to remove 3 "stale" hosts. Audit revealed `shared.html` actively loads DataTables, pdf.js (Mozilla), and drawio-renderer (laingsimon) from these hosts. Removing them breaks SW caching for shared pages. |
| 8 | `terminal.html` route location | `endpoints/terminal.py:297`, not `static_routes.py` | Hash injection for terminal requires modifying `terminal.py`, not the static routes catch-all. |
| 9 | `shared.html` asset cleanup | New Task 11 (deduplication, version alignment) | Duplicate scripts, highlight.js version mismatch, Bootstrap Icons version gap. Quick fixes (11a-11c) vs larger migrations (11d-11e) prioritized separately. |
| 10 | New files auto-discovered | Hash registry uses `os.walk`, so `tab-manager.js` and any future files are automatically included | No manual registry maintenance needed. Plan audit sections should be updated periodically. |

## Revision History

| Date | Changes |
|------|---------|
| Initial | Original plan with Tasks 1-10, audit of precache/CDN/SRI/HTTP headers |
| Post-32189d2 | Implemented Task 10 (logout cleanup) and Task 3 auth fix (403+no-store). Committed as 32189d2. |
| Post-UI-optimization | **Major revision.** Updated all file counts (35→37 local, 20→22 CDN, 16→17 precache missing). Added `tab-manager.js` to missing precache list. REVISED Task 5c: keep CDN allowlist hosts (used by `shared.html`). Added section E documenting `shared.html` issues (duplicates, version mismatches). Added Task 11 for `shared.html` cleanup. Fixed `terminal.html` route location (`terminal.py` not `static_routes.py`). Updated Task 3 and Task 10 status to reflect completed work. Updated verification steps, risks table, files modified table, decisions log. Added out-of-scope items for `shared.html` MathJax→KaTeX and pdf.js migration. Noted 28 commits with 1450 lines of JS/CSS changes since plan was written, with zero `?v=N` bumps — validating the automated hashing approach. |
