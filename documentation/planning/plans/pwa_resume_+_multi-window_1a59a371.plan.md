---
name: PWA Resume + Multi-Window
overview: Add a minimal PWA + Service Worker layer to cache the UI shell for instant reopen on Android, and enable a multi-window (one-chat-per-window) workflow using your existing stable conversation URLs—without backend changes and with minimal `interface/` edits.
todos:
  - id: recon-static-serving
    content: "Repo reconnaissance: confirm the exact UI entry route(s), static asset URL prefixes, and how `/interface/...` paths map to files, so SW + manifest are served from the right scope."
    status: completed
  - id: recon-ui-entry
    content: "Repo reconnaissance: identify the UI bootstrap points to minimally change: `interface/interface.html` (manifest link), and the best JS file(s) to register the service worker (likely `interface/common.js` or `interface/interface.js`)."
    status: completed
    dependencies:
      - recon-static-serving
  - id: recon-multi-window
    content: "Repo reconnaissance: find where conversation navigation is triggered and where to add multi-window support with minimal UI change (likely `interface/workspace-manager.js` conversation list or its context menu)."
    status: completed
    dependencies:
      - recon-ui-entry
  - id: decide-sw-scope
    content: "Decide service worker script URL + scope given current routing: recommended serve at `/interface/service-worker.js` with scope `/interface/` so it controls `/interface`, `/interface/<conversation_id>`, and `/interface/<conversation_id>/<message_id>`."
    status: completed
    dependencies:
      - recon-static-serving
  - id: decide-cache-inventory
    content: "Inventory caching boundaries using `endpoints/external_api.md`: define which URL prefixes are cache-eligible (UI shell + same-origin static assets) vs always NetworkOnly (ALL APIs, streaming endpoints, uploads/downloads, auth/session/lock utilities)."
    status: completed
    dependencies:
      - recon-ui-entry
  - id: cache-boundary-policy
    content: "Write explicit cache boundary rules (most important part): cache only GET requests for same-origin `/interface/*` assets and `/static/*` assets; treat everything else as NetworkOnly by default."
    status: completed
    dependencies:
      - decide-cache-inventory
  - id: cache-denylist-from-api-doc
    content: "From `endpoints/external_api.md`, enumerate explicit NetworkOnly denylist paths/prefixes (examples: `/send_message/*`, `/tts/*`, `/transcribe`, `/upload_doc_to_conversation/*`, `/proxy*`, `/shared*`, `/login`, `/logout`, `/get_user_info`, lock/session utilities)."
    status: completed
    dependencies:
      - decide-cache-inventory
  - id: cache-allowlist-interface-assets
    content: Build an explicit precache allowlist for same-origin UI assets referenced by `interface/interface.html` (CSS/JS + any local images/fonts). Keep this list small and deterministic.
    status: completed
    dependencies:
      - decide-cache-inventory
  - id: cache-navigation-policy
    content: "Decide how to handle navigation requests under `/interface/*`: NetworkFirst for HTML `interface.html` (avoid stale JS/HTML mismatch), with fallback to cached shell when offline."
    status: completed
    dependencies:
      - cache-boundary-policy
  - id: cache-size-policy
    content: "Decide cache size/retention: which caches exist (e.g., `ui-shell-vX`), what is safe to evict, and how to bump versions without breaking users."
    status: completed
    dependencies:
      - cache-allowlist-interface-assets
  - id: decide-cdn-policy
    content: "Decide whether to attempt runtime caching of third-party CDN assets (MathJax/Marked/etc). Default: do NOT cache cross-origin initially to minimize risk; optionally add later if network is still a problem."
    status: completed
    dependencies:
      - cache-boundary-policy
  - id: cdn-asset-audit
    content: Audit which heavyweight dependencies are loaded cross-origin (MathJax, Marked, KaTeX, highlight.js, etc.) and document why they will NOT be cached initially (cross-origin + update risk).
    status: completed
    dependencies:
      - decide-cdn-policy
  - id: pwa-manifest
    content: Create and serve a web app manifest + icons; link it from the main UI HTML so the UI is installable as a PWA.
    status: completed
    dependencies:
      - recon-ui-entry
  - id: pwa-manifest-fields
    content: "Define manifest fields precisely: `start_url` (recommend `/interface/`), `scope` (`/interface/`), `display` (`standalone`), `id` (stable), `name/short_name`, colors, orientation."
    status: completed
    dependencies:
      - pwa-manifest
  - id: pwa-icons
    content: Decide icon set and where it lives under `interface/` (at minimum 192x192 + 512x512). Confirm paths resolve via `/interface/...` routing.
    status: completed
    dependencies:
      - pwa-manifest-fields
  - id: pwa-link-html
    content: Add `<link rel="manifest" href="...">` to `interface/interface.html` and confirm correct relative/absolute URL under `/interface` routing.
    status: completed
    dependencies:
      - pwa-icons
  - id: pwa-manifest-validation
    content: "Validation checklist: manifest is reachable at `/interface/...`, has correct content type, icons load, and Chrome shows install prompt / 'Install app' menu item."
    status: completed
    dependencies:
      - pwa-link-html
  - id: pwa-meta
    content: "Add minimal PWA meta tags: theme-color, viewport is already present; ensure start_url and scope match `/interface` usage; confirm icon URLs resolve under `/interface/...`."
    status: completed
    dependencies:
      - pwa-manifest-validation
  - id: sw-cache-shell
    content: Add a Service Worker that pre-caches the UI shell and uses conservative fetch strategies (CacheFirst for same-origin static assets, NetworkFirst for HTML, NetworkOnly for APIs initially) with cache versioning + cleanup.
    status: completed
    dependencies:
      - decide-sw-scope
      - cache-boundary-policy
      - cache-allowlist-interface-assets
      - cache-navigation-policy
      - cache-size-policy
  - id: sw-cache-names
    content: Define cache names and versioning scheme (e.g., `ui-shell-v1`). Decide when to bump version (any UI asset changes).
    status: completed
    dependencies:
      - cache-size-policy
  - id: sw-install-precache
    content: "Plan SW `install` behavior: pre-cache allowlisted same-origin assets, handle failures gracefully, and avoid caching redirect-to-login responses."
    status: completed
    dependencies:
      - sw-cache-names
  - id: sw-activate-cleanup
    content: "Plan SW `activate` behavior: delete old caches, claim clients (or not), and document why."
    status: completed
    dependencies:
      - sw-cache-names
  - id: sw-fetch-routing
    content: "Plan SW `fetch` routing rules: ignore non-GET; ignore cross-origin by default; bypass all API paths (NetworkOnly); cache-first for same-origin `/interface/*.js|css|png|svg|ico|woff*`; network-first for navigation HTML under `/interface/*`."
    status: completed
    dependencies:
      - cache-denylist-from-api-doc
      - cache-navigation-policy
  - id: sw-offline-fallback
    content: "Plan offline behavior: when navigation to `/interface/*` fails, serve cached `interface.html` as shell (even if data calls fail). Document expected UX."
    status: completed
    dependencies:
      - sw-fetch-routing
  - id: sw-debug-logging
    content: Add a debug flag plan for SW logging (install/activate/fetch) so we can verify cache hits on Android without excessive noise.
    status: completed
    dependencies:
      - sw-fetch-routing
  - id: sw-register
    content: Register the Service Worker from the web UI bootstrap JS with minimal code changes and safe guards (HTTPS only, SW supported).
    status: completed
    dependencies:
      - sw-cache-shell
  - id: sw-register-entrypoint
    content: Pick the smallest-risk JS entrypoint for SW registration (prefer earliest loaded same-origin script such as `interface/common.js`), to ensure it registers on every UI load.
    status: completed
    dependencies:
      - sw-cache-shell
  - id: sw-register-guards
    content: "Define registration guards: only on HTTPS, only when SW supported, avoid running in iframes if applicable, and handle registration failures without impacting UI."
    status: completed
    dependencies:
      - sw-register-entrypoint
  - id: sw-register-verification
    content: "Define how to verify registration: Chrome DevTools Application tab, checking controlled clients under `/interface/`, and confirming cache hits for `interface/*.js`."
    status: completed
    dependencies:
      - sw-register-guards
  - id: sw-update-strategy
    content: "Define SW update behavior and user experience: pick defaults for `skipWaiting`/`clients.claim` and how/when the page reloads to pick up new cached assets; document how to bump cache versions safely."
    status: completed
    dependencies:
      - sw-register-verification
  - id: sw-update-policy-choice
    content: "Decide update policy: conservative default = do NOT auto-reload; instead activate on next load. Document tradeoffs and pick a single policy."
    status: completed
    dependencies:
      - sw-update-strategy
  - id: sw-update-user-flow
    content: "Plan user-visible update flow (optional): if a new SW is waiting, show a small non-blocking banner 'Update available' with a reload action."
    status: completed
    dependencies:
      - sw-update-policy-choice
  - id: multi-window-entrypoints
    content: "Enable multi-window chats with minimal UI change. Preferred: add an “Open in new window” action in the existing conversation context menu, or add a small per-conversation action button; fallback: rely on system long-press if we set a real `href`."
    status: completed
    dependencies:
      - sw-register
      - recon-multi-window
  - id: multiwindow-url-shape
    content: "Decide canonical URL to open in new window: prefer `/interface/<conversation_id>` (or `/interface/<conversation_id>/<message_id>` when deep-linking to a specific message)."
    status: completed
    dependencies:
      - recon-multi-window
  - id: multiwindow-href-support
    content: "If we want long-press 'open in new tab/window': update conversation list items to have a real `href=\"/interface/<id>\"` while keeping normal tap behavior SPA (preventDefault)."
    status: completed
    dependencies:
      - multiwindow-url-shape
  - id: multiwindow-context-menu-action
    content: Add 'Open in new window' action to the existing conversation context menu implementation (likely in `interface/context-menu-manager.js` + `interface/workspace-manager.js`). Ensure it works on mobile long-press if `contextmenu` is used.
    status: completed
    dependencies:
      - multiwindow-url-shape
  - id: multiwindow-action-button-alt
    content: "Alternative if context menu is unreliable on mobile: add a small per-conversation button next to clone/delete that does `window.open('/interface/<id>', '_blank', 'noopener')`."
    status: cancelled
    dependencies:
      - multiwindow-url-shape
  - id: multiwindow-ux-decision
    content: Choose one multi-window UX path (href+long-press, context menu, or action button) and document why; keep only one to minimize UI changes.
    status: completed
    dependencies:
      - multiwindow-href-support
      - multiwindow-context-menu-action
      - multiwindow-action-button-alt
  - id: android-verify
    content: "Validate on Android: installability, fast reopen with low/no network for UI shell, service worker update safety, and switching between multiple conversation windows."
    status: completed
    dependencies:
      - multi-window-entrypoints
  - id: verify-install
    content: "Android verification: confirm 'Install app' appears and installed PWA launches into `/interface/` and stays within `/interface/` scope."
    status: completed
    dependencies:
      - pwa-manifest-validation
  - id: verify-cache-hit-ui-assets
    content: "Android verification: confirm cached hits for same-origin `interface/*.js` and `interface/*.css` after first load (no network re-download on reopen)."
    status: completed
    dependencies:
      - sw-register-verification
  - id: verify-no-api-caching
    content: "Android verification: confirm API endpoints from `endpoints/external_api.md` are not cached (streaming works; uploads/downloads work; auth redirects not cached)."
    status: completed
    dependencies:
      - sw-fetch-routing
  - id: verify-eviction-resume
    content: "Android verification: simulate eviction (close app, reclaim memory) and confirm UI shell reload is fast and mostly offline; note remaining cost from MathJax/Marked rendering (expected)."
    status: completed
    dependencies:
      - sw-offline-fallback
  - id: verify-multiwindow
    content: "Android verification: open 2–3 conversation windows, switch via app switcher, confirm each window restores to its conversation URL and remains within scope."
    status: completed
    dependencies:
      - multiwindow-ux-decision
  - id: verify-sw-update
    content: "Android verification: update scenario (cache version bump) and confirm users do not get stuck with stale assets; validate chosen update policy."
    status: completed
    dependencies:
      - sw-update-policy-choice
  - id: docs-ops
    content: "Write a short ops note: how to install the PWA, how multi-window is expected to work, how to debug SW (chrome://serviceworker-internals or Application tab), and how to invalidate caches."
    status: completed
    dependencies:
      - android-verify
  - id: docs-cache-boundaries
    content: "Document the caching boundary explicitly: only `/interface/*` + `/static/*` GET assets cached; all endpoints in `endpoints/external_api.md` treated as NetworkOnly."
    status: completed
    dependencies:
      - cache-boundary-policy
  - id: docs-troubleshooting
    content: "Write troubleshooting checklist: 'SW not controlling page', 'install not showing', 'stale assets', 'logout/login redirects', and how to hard-refresh and clear storage."
    status: completed
    dependencies:
      - docs-ops
---

# PWA + Service Worker + Multi-Window Chats (Android)

## Requirements (from you)

- **No backend changes**.
- **Minimal changes in `interface/`** (thin wrapper over existing web UI).
- **Reduce reload cost primarily by cutting network** (Service Worker cache of UI shell).
- **Multi-chat “tabs”**: you’re OK with **multiple app windows** (PWA multi-window), not a browser-like tab strip.
- Site is served over **HTTPS** (Service Worker eligible).

## Approach Summary

- Implement an **installable PWA** (manifest + icons + display mode) and a **Service Worker** that caches the UI shell (HTML/CSS/JS/fonts/icons) using a safe caching strategy.
- For “tabs”: leverage **multi-window PWA** by opening each conversation URL in a **new window** (separate app window instance). This requires either:
- **Zero UI work**: user uses OS/browser “open in new window/tab” behaviors (sometimes awkward in PWA), or
- **Tiny UI change (recommended)**: add an “Open in new window” action that opens `/interface/<conversation_id>` with `target="_blank"` / `window.open(...)` so Chrome creates another standalone PWA window.

### Cache boundary (grounded in `endpoints/external_api.md`)

- **Primary rule (safe default)**: the Service Worker should **only** cache same-origin **GET** requests where `pathname` starts with:
- `/interface/` (static assets like `.js`, `.css`, icons) and navigation shell fallback
- `/static/` (app-shipped static assets)
- plus small one-offs: `/favicon.ico`, `/loader.gif` (optional)
- **Everything else** is treated as **NetworkOnly** by default.

This rule covers the entire API surface in `endpoints/external_api.md` without needing a fragile per-endpoint list. In particular, it guarantees we do **not** cache:

- **All JSON APIs** (conversations, documents, doubts, audio, workspaces, users, sections, prompts, PKB, code runner)
- **All streaming endpoints** (examples: `/send_message/*`, `/clear_doubt/*`, `/temporary_llm_action`, `/tts/*`)
- **All uploads/downloads** (examples: `/upload_doc_to_conversation/*`, `/download_doc_from_conversation/*`, `/get_conversation_output_docs/*`)
- **Auth/session/lock/proxy utilities** (examples: `/login`, `/logout`, `/get_user_info`, `/clear_session`, `/clear_locks`, `/get_lock_status/*`, `/proxy*`)
- **Shared/public endpoints** (examples: `/shared/*`, `/shared_chat/*`)

## Repo & UI Reconnaissance (findings so far)

### UI routing + static serving

- **UI entry route**: `/interface` serves `interface/interface.html` (see [`endpoints/static_routes.py`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/endpoints/static_routes.py)).
- **Stable chat URLs already exist**:
- `/interface/<conversation_id>`
- `/interface/<conversation_id>/<message_id>`
- The server checks whether `<conversation_id>` belongs to the logged-in user; if yes, it serves `interface.html`.
- **Interface assets are served through the same `/interface/<path>` route** and mapped to files in the `interface/` directory using `send_from_directory(...)`. This means the PWA artifacts can also live in `interface/` and be served as `/interface/manifest.webmanifest`, `/interface/service-worker.js`, `/interface/icons/...`, etc.

### UI entry HTML + local assets

- `interface/interface.html` includes many CDN scripts/styles (MathJax, Marked, etc.) plus **same-origin assets** like:
- `interface/style.css`
- `interface/common.js`
- `interface/common-chat.js`
- `interface/workspace-manager.js` (via script includes in `interface.html`)
- Implication: **service worker can easily cache same-origin UI assets**; cross-origin CDN caching is optional and higher-risk.

#### Same-origin assets referenced by `interface/interface.html` (candidate precache list)

- CSS:
- `interface/style.css`
- `interface/workspace-styles.css`
- JS:
- `interface/parseMessageForCheckBoxes.js`
- `interface/common.js`
- `interface/gamification.js`
- `interface/common-chat.js`
- `interface/markdown-editor.js`
- `interface/interface.js`
- `interface/codemirror.js`
- `interface/doubt-manager.js`
- `interface/clarifications-manager.js`
- `interface/temp-llm-manager.js`
- `interface/context-menu-manager.js`
- `interface/prompt-manager.js`
- `interface/pkb-manager.js`
- `interface/chat.js`
- `interface/workspace-manager.js`
- `interface/audio_process.js`
- Also consider caching same-origin `/static/*` assets served by the app (e.g., favicon/loader + any images/fonts you ship locally).

### Multi-window entrypoints

- Conversation list items are generated in `interface/workspace-manager.js` as `<a class="conversation-item" ...>` with a delegated click handler that calls `ConversationManager.setActiveConversation(conversationId)` and updates the URL via `pushState`.
- There is already an existing right-click/context-menu mechanism for conversations in `interface/workspace-manager.js`, which is a good low-UI-risk place to add an “Open in new window” action.
- **Important mobile detail**: the current `.conversation-item` markup uses `href="#"`, so Android long-press won’t naturally offer “open in new tab/window”. If we want long-press behavior, we need to give the element a real `href="/interface/<conversation_id>"` while preserving SPA click behavior.

## Milestones

### Milestone A — Add PWA installability (minimal)

- Add a web app manifest with:
- `name`, `short_name`, `start_url`, `scope`
- `display: "standalone"`
- theme/background colors
- icons (192/512)
- Link the manifest from the main HTML entry (likely [`interface/interface.html`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/interface/interface.html) or the HTML actually served at `/`).

**Files likely touched**

- [`interface/interface.html`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/interface/interface.html) (add `<link rel="manifest" ...>`)
- Add `manifest.webmanifest` under `interface/` (or wherever static files are served from)
- Add icons under `interface/` (or existing assets folder)

**Risks / notes**

- Manifest must be served with correct content-type (`application/manifest+json`); usually OK if served as a static file.

### Milestone B — Add Service Worker (network reload reduction)

Implement a Service Worker that:

- **Pre-caches**: core UI files (the “app shell”) on install.
- **Cache-first** for immutable/static assets (JS/CSS/fonts/icons).
- **Network-first** (or stale-while-revalidate) for the main HTML to ensure you don’t get stuck on an old version.
- **Does NOT cache** sensitive authenticated API responses by default (to avoid stale data surprises), unless explicitly whitelisted.

**Recommended caching policy**

- `CacheFirst`: same-origin `/interface/*.js|css|png|svg|ico|woff*` and `/static/*`
- `NetworkFirst`: navigation requests under `/interface/*` (serve cached `interface.html` on offline fallback)
- `NetworkOnly`: everything in `endpoints/external_api.md` (ALL APIs), plus `/proxy*`, `/shared*`, auth/session/lock utilities

**Versioning strategy**

- Use a `CACHE_VERSION` string in the service worker.
- On activate: delete old caches.

**Files likely touched**

- Add `service-worker.js` under `interface/` (or static root)
- Minimal registration snippet in your main JS entry (likely [`interface/common.js`](/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative/interface/common.js) or another early-loaded file):
- `navigator.serviceWorker.register('/interface/service-worker.js', { scope: '/interface/' })`

**Risks / notes**

- Service worker scope/path matters: place it at the correct static root so it controls your UI routes.
- If you serve some assets from a different origin (CDN), SW won’t cache them unless you proxy or change hosting.

### Milestone C — Multi-window “tabs” for multiple chats

Because you already have stable URLs per conversation, implement **multi-window** in the PWA.

**Option C1 (recommended, tiny UI change)**

- Add an “Open in new window” action wherever a conversation is selectable.
- Implementation choices:
- Use an `<a href="/interface/<id>" target="_blank" rel="noopener">` style link, or
- `window.open(url, '_blank', 'noopener')`

**Option C2 (no UI changes)**

- Document a usage pattern:
- Long-press conversation link → open in new window
- Use Android app switcher to swap between PWA windows

**Pros/cons**

- C1 is more reliable across devices and avoids hidden gestures.
- C2 is truly “no UI changes” but usability varies.

**Important note**

- This is not a visible tab strip. It’s multiple standalone windows, which matches your selected preference.

### Milestone C.1 — Decide the minimal UX

- **Preferred**: add “Open in new window” inside the existing conversation context menu (minimal UI surface change; no layout churn).
- **Alternative**: add a small per-conversation action button (next to clone/delete) that calls `window.open('/interface/<id>', '_blank', 'noopener')`.
- **Fallback**: set a real `href="/interface/<id>"` on `.conversation-item` and rely on Android long-press → “open in new tab/window” (requires ensuring normal clicks still use SPA behavior).

### Milestone D — Validation on Android

- Confirm:
- PWA is installable.
- Reopen after Chrome/tab eviction loads UI shell from cache (little/no network).
- Multi-window works: opening 2–3 conversation windows and switching via app switcher.
- Add simple observability:
- Console logs in SW install/activate/fetch.
- A “cache version” debug line in UI.

## Alternatives (and why not)

- **Native WebView tabbed browser app**: real tab strip, but becomes a multi-week effort and still not immune to OS kills.
- **Caching full rendered HTML / freezing JS**: not reliably possible across process eviction; better to rely on app-shell caching and (later) state restoration.

## Challenges / risks

- **Route control**: if your UI is served from multiple entry HTML pages or mixed origins, SW scope and caching rules must be carefully set.
- **Stale assets**: improper caching can cause “old JS talking to new server” issues. Using `NetworkFirst` for HTML and versioned caches helps.
- **Auth/session**: SW caching must not accidentally cache personalized API responses.
- **Auth redirect and SW script fetch**: the `/interface/<path>` route redirects to `/login` if not logged in. Service worker updates/installs will only work while the session is valid. We are intentionally not changing backend auth behavior (per requirement).

## Implementation Todos

- `recon-static-serving`: Confirm `/interface` + `/interface/<path>` behavior and best SW URL/scope.
- `recon-ui-entry`: Confirm where to add manifest link + SW registration with minimal UI change.
- `recon-multi-window`: Confirm the lowest-risk place to add “open in new window” for a conversation.
- `decide-sw-scope`: Decide SW script location + scope (recommend `/interface/service-worker.js`, scope `/interface/`).
- `decide-cache-inventory`: Produce explicit list of same-origin assets to precache + explicit API routes to keep NetworkOnly.
- `decide-cdn-policy`: Decide whether to cache CDN assets now vs later.
- `pwa-manifest`: Add manifest + icons.
- `pwa-meta`: Add minimal meta + verify manifest start_url/scope under `/interface`.
- `sw-cache-shell`: Implement SW caching strategy + versioning.
- `sw-register`: Register SW.
- `sw-update-strategy`: Decide and document update semantics.
- `multi-window-entrypoints`: Implement multi-window affordance (context menu or small action).
- `android-verify`: Validate on Android.
- `docs-ops`: Write ops/debug notes.