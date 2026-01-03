## PWA + Service Worker + Multi-Window (Android) — Ops & Debug Notes

This repo’s web UI can be used “app-like” on Android by installing it as a **PWA** and using a **Service Worker** to cache the UI shell (JS/CSS/icons), so reopening does not re-download assets.

### What we changed (where)
- **PWA manifest**: `interface/manifest.json` (served at `/interface/manifest.json`)
- **Icons** (text-based SVG): `interface/icons/app-icon.svg`, `interface/icons/maskable-icon.svg`
- **Manifest link + theme color**: `interface/interface.html`
- **Service Worker**: `interface/service-worker.js` (served at `/interface/service-worker.js`)
- **Service Worker registration**: appended to `interface/common.js`
- **Multi-window chats**:
  - Conversation list items now have real `href="/interface/<conversation_id>"` in `interface/workspace-manager.js`
  - Conversation context menu includes “Open in New Window” (UI: `interface/interface.html`, handler: `interface/workspace-manager.js`)

---

## Cache boundary (critical)

### Cache-eligible (same-origin, GET only)
- **UI shell + assets** under:
  - `/interface/*` (local JS/CSS/icons, and cached HTML shell as fallback)
  - `/static/*` (if/when you ship assets there)

### Cache-eligible (selected CDN assets, GET only)
Some third-party libraries referenced in `interface/interface.html` are fetched from CDNs. The Service Worker now caches **asset-like** requests (script/style/font/image) for an allowlisted set of hosts, with a **6-hour TTL** refresh policy.

### Never cached (NetworkOnly)
Everything outside the `/interface/*` and `/static/*` asset world, including:
- **All JSON APIs** (conversations, docs, doubts, audio, workspaces, users, sections, prompts, PKB, code runner)
- **All streaming endpoints**: `/send_message/*`, `/clear_doubt/*`, `/temporary_llm_action`, `/tts/*`, etc.
- **Uploads/downloads**: `/upload_doc_to_conversation/*`, `/download_doc_from_conversation/*`, `/get_conversation_output_docs/*`
- **Auth/session/locks**: `/login`, `/logout`, `/get_user_info`, `/clear_session`, `/clear_locks`, `/get_lock_status/*`, `/ensure_locks_cleared/*`, `/force_clear_locks/*`
- **Proxy/shared**: `/proxy*`, `/shared*`

This is enforced by `interface/service-worker.js` by only intercepting same-origin GET requests whose path starts with `/interface/` or `/static/` (plus `/interface` itself).

---

## What this does and does not solve

### Solves (primary goal)
- **Cuts “network reload” cost** on reopen by caching the UI’s same-origin JS/CSS/icons.
- Makes your web UI feel closer to a native app for repeated opens.

### Does not solve (by design)
- Does **not** cache conversation history JSON, streamed responses, uploads, or downloads.
- Does **not** eliminate the heavy **Markdown/MathJax re-render cost** (that would require separate client-side optimizations and/or partial rendering).
- Does **not** keep a Chrome tab alive after OS eviction (not reliably possible).

---

## Multi-window chats (Android “tabs” without building a native app)

### Canonical “open chat” URL
Use **single-segment** conversation URLs:
- `/interface/<conversation_id>`

Avoid deep-linking into `/interface/<conversation_id>/<message_id>` for new windows because relative UI assets would resolve under `/interface/<conversation_id>/...` and can break.

### How to use
- From the chat list:
  - **Long-press** a conversation and choose “open in new tab/window” (works because items now have real `href`s), or
  - Use the custom right-click context menu on desktop: **Open in New Window**
- In PWA mode, each “new tab” typically becomes a separate **PWA window** you can switch between using the Android app switcher.

---

## Installability checklist (Android)

Prereqs:
- Site must be served over **HTTPS** (localhost is allowed for dev).
- You must be **logged in** (these routes currently require session auth).

Steps:
1. Open the UI at `/interface/` in Chrome on Android.
2. Menu → **Install app** (or “Add to Home screen” depending on Chrome version).
3. Launch from home screen; you should get a standalone window.

---

## Debug / Verification checklist

### 1) Confirm the PWA artifacts load
- Open:
  - `/interface/manifest.json`
  - `/interface/service-worker.js`
  - `/interface/icons/app-icon.svg`

### 2) Confirm Service Worker is registered and controlling
In Chrome DevTools:
- Application → Service Workers
  - Service worker URL should be `/interface/service-worker.js`
  - Scope should be `/interface/`
  - “Status” should be activated/running

### 3) Confirm cached hits for UI assets
In DevTools Network tab:
- Reload once (online) → assets should be fetched.
- Reload again → `interface/*.js` / `interface/*.css` should show **(from ServiceWorker)** / **(disk cache)** depending on devtools settings.

### 4) Confirm APIs are NOT cached
Try:
- Send a message (streaming): `/send_message/<conversation_id>` should behave normally.
- Upload a document: should behave normally.
If streaming/upload breaks, the SW cache boundary is too broad (should not happen with current rules).

---

## Update policy (how new UI code deploys)
- The Service Worker uses a **versioned cache** name (`ui-shell-v1`).
- It does **not** call `skipWaiting()` or `clients.claim()` (conservative).
- A new SW will take control on a subsequent navigation/reload as per standard SW lifecycle.

### Cache invalidation options
You have two complementary ways to avoid stale UI assets after you deploy changes:

1) **Deterministic (recommended): bump `CACHE_VERSION`**
- In `interface/service-worker.js`, change:
  - `const CACHE_VERSION = "v1";` → `"v2"`, etc.
- This forces a new cache namespace and deletes old caches on activate.

2) **Time-based safety net: 6-hour TTL**
- For cached assets, the Service Worker treats entries older than **6 hours** as stale and will refresh them from the network when possible.
- This helps if you forget to bump `CACHE_VERSION`, but it is not as immediate as a version bump.

To force-update during development (manual):
- Chrome DevTools → Application → Storage → “Clear site data”
- Or bump `CACHE_VERSION` in `interface/service-worker.js`.

---

## Current implementation recap (what we changed)

### What the PWA implementation does (today)
- **Manifest + installability**: `interface/interface.html` links `interface/manifest.json` and sets `theme-color`.
- **Service Worker**: `interface/service-worker.js`
  - **Same-origin UI shell** (`/interface/*`, `/static/*`): cached to cut reload cost.
  - **Navigation** (`/interface`, `/interface/<conversation_id>`): **NetworkFirst**, with offline fallback to cached shell.
  - **APIs / streaming / uploads**: **not cached** (NetworkOnly by design).
  - **Selected CDN assets**: cached conservatively for allowlisted hosts with **6-hour TTL** refresh.
- **Multi-window / stable per-chat URL**: conversation items are real links (`/interface/<conversation_id>`), so the browser/Android can open multiple windows.

### Files changed/added
- **Added**: `interface/manifest.json`
- **Added**: `interface/icons/app-icon.svg`
- **Added**: `interface/icons/maskable-icon.svg`
- **Added**: `interface/service-worker.js`
- **Updated**: `interface/common.js` (registers Service Worker)
- **Updated**: `interface/interface.html` (manifest link + theme-color meta + real `href` links + context menu option)
- **Updated**: `interface/workspace-manager.js` (conversation links + click interception for SPA behavior)
- **Updated**: `interface/common-chat.js` (mobile sidebar hide is now deterministic, not toggle)
- **Updated**: `PWA_ANDROID.md` (this doc)

---

## Rendered-state persistence (ideas; not implemented yet)
Goal: reduce “reload cost” further by restoring *already-rendered* conversation UI instantly (even if we keep APIs NetworkOnly).

### Option A: client-side snapshot of rendered DOM (per conversation)
- **What**: After a conversation finishes rendering (including MathJax), store:
  - `chatView.innerHTML` (or per-message card HTML chunks)
  - `scrollTop` (and potentially selected tab / UI toggles)
  - a **schema/version key** tied to UI (`CACHE_VERSION`) so snapshots invalidate cleanly
- **Where**: IndexedDB (preferred) or localStorage (not great for size).
- **Restore flow**:
  - On load of `/interface/<conversation_id>`, immediately inject snapshot into the chat container and set scroll.
  - In parallel, fetch real conversation history via existing APIs and re-render/refresh if needed (or only refresh if snapshot version mismatches).
- **Pros**: fastest perceived resume; works offline for already-opened chats.
- **Cons**: storage bloat, snapshot invalidation is tricky, MathJax/layout reflow can shift scroll, and any UI code change can break old snapshots unless versioned.

### Option B: structured rendered cache (per message)
- **What**: Instead of whole DOM, store per-message:
  - message id (if available in data / DOM)
  - rendered HTML fragment
  - any metadata needed to rehydrate (collapsed/expanded state, ToC ids, etc.)
- **Pros**: smaller diffs; easier partial updates.
- **Cons**: requires stable message identifiers (we’d likely need to derive/store them).

### Option C: “soft resume” (no HTML snapshot)
- **What**: Store only conversation history JSON + scroll, then run the same render pipeline.
- **Pros**: simpler and safer than DOM snapshot.
- **Cons**: still pays the big render cost (MathJax/Marked), which is what you’re trying to avoid.

---

## Rendered-state persistence (implemented: IndexedDB DOM snapshot)
This repo now implements **Option A** (DOM snapshot per conversation) with **versioned invalidation**:

- **New file**: `interface/rendered-state-manager.js`
  - Saves `#chatView.innerHTML` + `#chatView.scrollTop` + snapshot meta (`lastMessageId`, `messageCount`)
  - Stored in **IndexedDB** under DB `science-chat-rendered-state`, store `snapshots`
  - Snapshots are keyed by conversation: `conv:<conversationId>`
  - Snapshot version is `window.UI_CACHE_VERSION` (see below)

- **Wiring**:
  - `ConversationManager.setActiveConversation()` now:
    - Restores snapshot first (instant paint)
    - Fetches messages via `/list_messages_by_conversation/<id>` (still NetworkOnly)
    - Skips expensive re-render if last message id + count match the snapshot meta
  - `ChatManager.renderMessages()` schedules debounced snapshot saves after renders

### Versioned invalidation (how to avoid stale snapshots)
- Bump **one constant**:
  - `window.UI_CACHE_VERSION` in `interface/common.js`
  - (Recommended: keep it aligned with `CACHE_VERSION` in `interface/service-worker.js`)
- When the version changes, old snapshots are ignored (and best-effort deleted).


