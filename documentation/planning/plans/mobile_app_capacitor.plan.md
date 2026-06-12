# Mobile App via Capacitor

**Status:** Draft
**Created:** 2026-06-12
**Scope:** Ship a native Android (and optionally iOS) app wrapping the existing web UI using Capacitor, with targeted fixes for mobile UX, auth, streaming reliability, and native integrations.

---

## 1. Background — Why Capacitor

The web UI (`interface/interface.html` + 30 JS modules) is a full-featured chat app with streaming, doubts, PKB, file browser, TTS, code execution, and more. Rewriting in React Native or Flutter would take 8-10 weeks and lose feature parity. Capacitor wraps the existing web app in a native shell (WKWebView on iOS, Chrome WebView on Android) while providing native plugin access.

**Key compatibility findings:**
- All API calls use relative paths — no hardcoded domains
- Streaming uses fetch + `ReadableStream.getReader()` — supported in WebView (Android 5+, iOS 11+)
- localStorage and IndexedDB work natively
- Bootstrap 4.6 responsive grid + existing `(pointer: coarse)` media queries provide a baseline
- Auth uses Flask session cookies — WebView handles these identically to a browser

**What does NOT work out of the box:**
- Service Worker (silently ignored in Capacitor WebView)
- `100vh` on iOS (keyboard doesn't reduce viewport height)
- MediaSource for TTS streaming (unreliable on Android WebView)
- Desktop-only interactions: drag-and-drop, right-click context menu, keyboard shortcuts
- 30 CDN dependencies require network on every launch
- No safe area inset handling (notch/home bar overlap)
- No server heartbeat (cellular connections drop after 30s idle silence)
- WebSocket URL in `opencode-terminal.js` uses `window.location.host` (breaks under `file://` if using local serving)

---

## 2. Architecture Decision

**Approach: Remote WebView (Phase 1) → Local + Remote hybrid (Phase 2)**

Phase 1: Capacitor loads `https://assist-chat.site/interface/` directly. Zero bundling needed. Auth works via cookies. All features available immediately. Requires network.

Phase 2 (optional): Bundle critical assets locally (`www/`), load the app shell offline, hit server only for API calls. Provides faster launch and offline conversation reading.

---

## 3. Auth Strategy

### Current State
- `login_required` decorator checks `session["email"]` (Flask filesystem-backed sessions)
- Session cookie: `SameSite=None, Secure=True, HttpOnly=True`, 30-day lifetime
- Remember-me token: 64-char SHA-256 hex cookie, 30-day, auto-restores session via `before_app_request` hook
- JWT infrastructure exists in `mcp_server/auth.py` (HS256, `MCP_JWT_SECRET`, scopes)
- Google OAuth: config keys loaded but **no routes implemented**

### Mobile Auth Plan
- **Phase 1 (zero changes):** WebView loads login page → user enters credentials → session cookie set → works like browser
- **Phase 2 (optional, for native HTTP and background tasks):** Add Bearer token fallback to `login_required`, return JWT from login endpoint, store in Capacitor secure storage

### Changes Required (Phase 2 only)
```
endpoints/auth.py:
  - login_required: add Authorization: Bearer header check → verify_jwt → populate session
  - login route: return {"token": jwt} alongside session cookie
```

---

## 4. Streaming Reliability on Mobile

### Current State
- NDJSON over `text/plain` (not SSE, not WebSocket)
- Frontend: `fetch().body.getReader()` + `TextDecoder` + line-split + `JSON.parse`
- No AbortController/timeout on main chat stream
- No server-side heartbeat during LLM think time (30-60s gaps possible)
- Nginx: `proxy_read_timeout 3600` (fine)

### Problems on Cellular
- NAT/carrier middleboxes kill idle TCP after ~30s
- Stream silently dies — UI frozen with stop button visible
- No reconnection logic

### Fixes
1. Server: emit `{"type":"ping"}\n` every 15s during silent periods (tool calls, LLM thinking)
2. Client: add AbortController with configurable timeout (120s without any chunk = dead)
3. Client: show "Connection lost" toast + retry button on stream error
4. Response headers: add `X-Accel-Buffering: no` and `Cache-Control: no-cache` to streaming endpoints

---

## 5. Critical UX Fixes

### 5.1 iOS `100vh` Keyboard Bug
**Problem:** `style.css` uses `100vh` for chat container heights. iOS keyboard doesn't reduce `100vh` — content clips behind keyboard.
**Fix:** Replace `100vh` with `100dvh` (dynamic viewport height) or use `@capacitor/keyboard` plugin's `resize` mode + JS-based height calculation.
**Files:** `interface/style.css` (lines 272, 277, 790-835), `interface/css_patched_mobile_view.css`

### 5.2 Safe Area Insets
**Problem:** No `env(safe-area-inset-*)` anywhere. Content overlaps notch and home bar.
**Fix:** Add `viewport-fit=cover` to `<meta viewport>`, add padding to fixed header/footer elements.
**Files:** `interface/interface.html` (meta tag), `interface/style.css` (header, input area)

### 5.3 Touch Targets Too Small
**Problem:** Many `btn-sm` buttons are ~28px. iOS HIG requires 44px minimum.
**Fix:** Add mobile media query increasing `min-height: 44px; min-width: 44px` on interactive elements inside modals and chat.
**Files:** `interface/style.css` or new `interface/css_mobile_capacitor.css`

### 5.4 Keyboard Shortcuts → Visible Buttons
**Problem:** Ctrl+Enter (send), Ctrl+K (voice), Ctrl+S (save) are the only way to trigger some actions.
**Fix:** Ensure every shortcut has a visible button alternative. Main chat already has this (send button exists). Check: prompt editor save, file browser generate.
**Files:** Various, audit needed

### 5.5 Context Menu (Long-Press)
**Problem:** `context-menu-manager.js` listens for `contextmenu` event which fires on long-press in WebView. This works but conflicts with native text selection. `mouseup` for selection-based menu needs `touchend` equivalent.
**Fix:** Add `touchend` listener alongside `mouseup` in `handleSelectionComplete`. Test that long-press doesn't interfere with native copy/paste.
**Files:** `interface/context-menu-manager.js`

### 5.6 Drag-and-Drop → Hidden on Mobile
**Problem:** `dragover`/`drop` handlers exist for file upload. Non-functional on touch.
**Fix:** Hide drop zone visual on `(pointer: coarse)`. File upload via `<input type="file">` tap still works.
**Files:** `interface/common-chat.js` (line 2286), CSS

### 5.7 Send Button Visibility
**Problem:** Main chat input needs a clearly visible send button for mobile (no physical Enter key behavior).
**Fix:** Verify send button exists and is prominent. Add if missing.
**Files:** `interface/interface.html` chat input area

---

## 6. Service Worker & Offline

### Current State
- Full SW in `interface/service-worker.js` (caches UI shell, NetworkFirst for HTML, NetworkOnly for API)
- SW registration in `interface/common.js` (HTTPS-gated)
- Manifest.json with standalone display mode

### Capacitor Behavior
- **Service workers are silently ignored** in Capacitor WebView
- Registration call succeeds but SW never activates
- No offline shell caching

### Fix
- Guard SW registration: `if (!window.Capacitor || !Capacitor.isNativePlatform()) { registerSW(); }`
- For Phase 2 (local assets): bundle critical files in Capacitor's `www/` folder — SW becomes unnecessary

---

## 7. Rendered State Manager (IndexedDB Snapshots)

### Current State
- `rendered-state-manager.js` saves DOM snapshots to IndexedDB for instant conversation restore
- Max 4MB per snapshot
- Keyed by `conv:<conversationId>`

### Mobile Considerations
- IndexedDB works in Capacitor WebView ✅
- Storage quota is lower on mobile (~50MB default vs ~unlimited on desktop)
- App backgrounding on iOS can evict WebView process memory but IndexedDB persists on disk
- Need LRU eviction: keep last N conversations (suggest N=20 on mobile vs unlimited on desktop)

### Fix
- Add `MAX_SNAPSHOTS_MOBILE = 20` constant
- Detect Capacitor: `if (window.Capacitor) { evictOldest(); }`
- Or simply let the existing "versioned invalidation" handle it (snapshots naturally expire on version bump)

---

## 8. TTS / Audio

### Current State
- `convertToTTSAutoPlay`: uses MediaSource for streaming audio playback
- `convertToTTSNoAutoPlay`: downloads full audio then plays (fallback)
- Fallback triggers when `!window.MediaSource`

### Mobile Behavior
- Android WebView: MediaSource support varies by device/Chrome version — fallback will fire on many devices
- iOS WKWebView: MediaSource not supported — fallback always fires ✅
- Autoplay blocked without user gesture on both platforms

### Fix
- Verify fallback path works correctly (it should — already exists)
- Ensure TTS buttons require user tap (not auto-triggered)
- Optional Phase 2: use `@niceplugins/capacitor-tts` for native speech synthesis

---

## 9. Notifications

### Current State
- `notification-manager.js` with two branches: Electron (IPC) and Browser (Web Notification API)
- Used for: clarification requests, tool call approvals, general alerts

### Mobile Plan
- Add third branch for Capacitor using `@capacitor/local-notifications`
- Later: `@capacitor/push-notifications` for server-triggered notifications (auto-doubt completion, PKB extraction done)

### Detection
```javascript
if (window.__isElectronDesktop) { /* Electron */ }
else if (window.Capacitor && Capacitor.isNativePlatform()) { /* Capacitor */ }
else { /* Browser */ }
```

---

## 10. Native Enhancements (Phase 2+)

| Feature | Capacitor Plugin | Effort |
|---------|-----------------|--------|
| Push notifications (auto-doubt ready) | `@capacitor/push-notifications` | 1 day |
| Native voice recording (better quality) | `@capacitor/microphone` | 2h |
| Camera → document upload | `@capacitor/camera` | 1h |
| Biometric unlock | `@capacitor/biometrics` | 2h |
| Share extension (receive text from other apps) | `@capacitor/share` | 4h |
| Haptic feedback on events | `@capacitor/haptics` | 30min |
| Native file picker | `@capacitor/filesystem` | 2h |
| App badge (unread doubts count) | `@capacitor/badge` | 1h |
| Background fetch (PKB sync) | `@niceplugins/capacitor-background-mode` | 4h |
| Deep links (`assistchat://conversation/ID`) | `@capacitor/app` (appUrlOpen event) | 2h |

---

## 11. CDN Dependencies

### Current State (30 external requests on load)
- jQuery 3.5.1, jQuery UI 1.12.1, Bootstrap 4.6.2
- marked 11.2.0, highlight.js 11.9.0, KaTeX 0.16.8, MathJax 2.7.5
- Mermaid 11.5.0, CodeMirror 5.65.16, Reveal.js 4.3.1
- PDF.js, EasyMDE, DataTables, animate.css, bootstrap-select, Font Awesome, Bootstrap Icons

### Mobile Impact
- App non-functional without network (all deps are CDN-loaded)
- Initial load time on 3G: 5-10 seconds (latency × 30 requests)

### Phase 1 Fix (minimal)
- Accept network requirement — chat app needs network anyway for API calls
- Add a loading splash screen while CDN assets load

### Phase 2 Fix (for offline + faster launch)
- Bundle critical subset locally in `www/assets/`: jQuery, Bootstrap CSS/JS, marked, highlight.js
- Keep heavy optional deps on CDN (Mermaid, CodeMirror, Reveal.js, PDF.js — loaded on demand)
- Reduces launch-critical requests from 30 → ~5

---

## 12. Implementation Phases

### Phase 1: Working APK (1-2 days)
- [ ] Install Capacitor: `npm init @capacitor/app`, `npx cap add android`
- [ ] Configure `capacitor.config.ts` with `server.url: 'https://assist-chat.site/interface/'`
- [ ] Add `viewport-fit=cover` to meta tag
- [ ] Guard SW registration with Capacitor check
- [ ] Add safe area padding to header and chat input
- [ ] Replace `100vh` with `100dvh` in CSS (or add override in mobile CSS)
- [ ] Test: streaming works, login works, doubts work, file upload works
- [ ] Build APK, install on device

### Phase 2: Mobile UX Polish (1 week)
- [ ] Add server heartbeat (ping every 15s during silent LLM periods)
- [ ] Add AbortController + timeout to chat fetch
- [ ] Add stream error toast + retry button
- [ ] Fix touch targets (44px minimum on interactive elements)
- [ ] Add `touchend` handler for context menu selection
- [ ] Hide drag-drop zones on `(pointer: coarse)`
- [ ] Add `capture="camera"` to image upload inputs
- [ ] Test TTS fallback on Android WebView
- [ ] Add Capacitor branch to notification-manager.js
- [ ] Add IndexedDB snapshot eviction (LRU, 20 conversations)
- [ ] Add `X-Accel-Buffering: no` header to streaming endpoints

### Phase 3: Native Features (2 weeks)
- [ ] JWT token auth for background/native HTTP requests
- [ ] Push notifications for auto-doubt completion
- [ ] Native voice recording via `@capacitor/microphone`
- [ ] Camera integration for document upload
- [ ] Share extension (receive shared text/files)
- [ ] Biometric unlock
- [ ] Deep links for conversation URLs
- [ ] App badge for unread doubts

### Phase 4: Offline + Performance (2 weeks)
- [ ] Bundle critical CDN deps locally
- [ ] Splash screen during initial load
- [ ] Offline conversation reading (cached messages in IndexedDB)
- [ ] Background sync for PKB
- [ ] Performance profiling: MathJax render time, scroll jank, memory usage

---

## 13. Files to Modify

| File | Changes |
|------|---------|
| `interface/interface.html` | viewport-fit, safe area meta, camera capture attribute |
| `interface/style.css` | Replace `100vh`, add safe area insets, touch target sizes |
| `interface/common.js` | Guard SW registration, add Capacitor detection utility |
| `interface/common-chat.js` | AbortController on stream fetch, hide drag-drop on mobile |
| `interface/context-menu-manager.js` | Add `touchend` listener |
| `interface/notification-manager.js` | Add Capacitor branch |
| `interface/rendered-state-manager.js` | Add LRU eviction for mobile |
| `endpoints/conversations.py` | Add heartbeat ping during streaming, `X-Accel-Buffering` header |
| `endpoints/auth.py` | (Phase 3) Bearer token fallback in `login_required` |
| NEW: `capacitor.config.ts` | Capacitor configuration |
| NEW: `android/` | Generated Android project |
| NEW: `interface/css_capacitor_overrides.css` | Mobile-specific CSS overrides |

---

## 14. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| iOS WKWebView IndexedDB eviction on memory pressure | Medium | Lost rendered snapshots (not data loss — re-fetches from server) | Accept graceful degradation |
| Android WebView version fragmentation (old Samsung etc.) | Low (target Android 8+) | Some CSS/JS features unavailable | Set `minSdkVersion 26` (Android 8) |
| Cookie-based auth breaks if switching to local asset serving | Medium | Can't authenticate API calls | Use absolute server URL for API calls OR switch to JWT |
| MathJax rendering performance on low-end phones | High | Scroll jank on math-heavy conversations | Lazy-render off-screen cards, or switch to KaTeX (faster) |
| App Store rejection (just a WebView) | Low (Android), Medium (iOS) | iOS App Store may reject "minimal functionality" apps | Add native features (biometrics, push, camera) in Phase 3 before iOS submission |

---

## 15. Decision Log

| Decision | Rationale |
|----------|-----------|
| Capacitor over React Native/Flutter | Preserves all existing features without rewrite; 1-day to working APK vs 8+ weeks |
| Remote WebView over local bundling (Phase 1) | Zero build step, zero asset management, cookies work naturally |
| Heartbeat over WebSocket migration | Minimal change (add one `yield` in a loop) vs rewriting all streaming to WS |
| JWT as Phase 3 (not Phase 1) | Cookie auth works perfectly in WebView; JWT only needed for native background tasks |
| Target Android first | WebView is Chrome-based (predictable); iOS WKWebView has more quirks (safe areas, MediaSource) |
