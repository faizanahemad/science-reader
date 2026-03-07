# Desktop Companion — Build Task Breakdown

**Created**: 2026-03-07
**Source**: `desktop_companion.plan.md` (Draft v13)
**Purpose**: Granular milestones, tasks, sub-tasks with dependency graph, parallel streams, and critical path for building the Science Reader Desktop Companion.

---

## How to Read This Document

- **Task IDs**: `M0.1.a` = Milestone 0, Task 1, Sub-task a
- **Dependencies**: `→ M0.1.a` means "depends on M0.1.a completing first"
- **Streams**: A–E represent parallel resource lanes (can run simultaneously)
- **Effort**: S (< 2 hrs), M (2–6 hrs), L (6–16 hrs), XL (16+ hrs)
- **Critical Path**: Tasks marked `[CP]` are on the critical path — any delay here delays the entire project

---

## Resource Streams (Parallel Lanes)

| Stream | Focus | Description |
|--------|-------|-------------|
| **A** | Server-Side Backend | MCP expansion, nginx config, desktopBridge API — runs on remote server |
| **B** | Electron Core | Project scaffold, main process, windows, tray, hotkeys, session auth |
| **C** | Desktop Surfaces | PopBar, Results Dropdown, Dictation Pop — custom HTML/CSS/JS |
| **D** | Native & Integration | Swift accessibility addon, macOS Services, screen capture, folder sync |
| **E** | Terminal & OpenCode | Tab 2 (OpenCode), Tab 3 (Terminal), local filesystem MCP |

Streams A and B can start **day 1 in parallel**. Stream E can start as soon as the Electron scaffold exists. Streams C and D layer on after core shell is up.

---

## Dependency Graph (Simplified)

```
M0 Foundation ──────────────────────────────────────────────────
  ├─ A: MCP Server Expansion (remote) ──────────┐
  ├─ A: nginx reverse proxy ─────────────────────┤
  ├─ A: desktopBridge API (interface.html) ──────┤── needed by M4, M5, M7
  ├─ B: Electron scaffold + package.json ────────┤── needed by everything in B/C/D/E
  └─ E: Local Filesystem MCP ───────────────────┘── needed by M1 Tab 2

M1 Core Shell ──────────────────────────────────────────────────
  ├─ B: Sidebar window + Tab 1 (BrowserView) ───┐
  ├─ B: Session cookie sharing ──────────────────┤── needed by M3 PopBar API calls
  ├─ B: Tray icon + global hotkeys ──────────────┤
  ├─ E: Tab 2 OpenCode integration ──────────────┤── needs M0 MCP servers + local FS MCP
  └─ E: Tab 3 Terminal (node-pty + xterm.js) ────┘── needs scaffold only

M2 Focus Management ────── needs M1 Sidebar window ────────────
  └─ B: focusable toggle, visual states, Escape flow

M3 PopBar ─────────────── needs M1 session cookie, M2 focus ──
  ├─ C: PopBar window + custom UI ──────────────┐
  ├─ C: Results Dropdown + streaming ────────────┤
  ├─ C: Tool calling whitelist ──────────────────┤
  └─ C: Ephemeral conversation + cleanup ────────┘

M4 File Ingestion ─────── needs M1 Sidebar, M0 desktopBridge ─
  ├─ B: Drag-and-drop handler ──────────────────┐
  └─ B: desktopBridge integration ──────────────┘

M5 macOS Services ─────── needs M3 PopBar, M4 desktopBridge ──
  ├─ D: NSServices Info.plist registration
  ├─ D: Apple Events handler
  └─ D: 6 service action flows

M6 Screen Context ─────── needs M3 PopBar, M4 desktopBridge ──
  ├─ D: Swift Accessibility addon ───── can start early (M0)
  ├─ D: Screenshot capture (4 modes)
  ├─ D: OCR integration
  ├─ D: Context awareness
  └─ D: In-place text replacement (@jitsi/robotjs)

M7 Voice Dictation ────── needs M1 window basics ─────────────
  ├─ C: Dictation Pop window
  ├─ C: Audio recording + Whisper proxy
  └─ D: Smart paste (Accessibility API) ─── needs M6 Swift addon

M8 Folder Sync ────────── needs M1 session cookie, M0 desktopBridge
  ├─ D: chokidar file watcher
  ├─ D: Sync state SQLite cache
  └─ D: Settings UI

M9 Polish & Packaging ─── needs all above ─────────────────────
  ├─ B: electron-builder config
  ├─ B: Settings window (all panels)
  └─ B: Error handling, performance, accessibility
```

---

## M0: Foundation (Week 1–2)

Everything here can start **day 1**. No cross-dependencies within M0 — all 5 tasks run in parallel.

### M0.1 — Electron Project Scaffold [CP]
**Stream B** | Effort: M | Dependencies: none

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create `desktop/` directory in monorepo root | `chatgpt-iterative/desktop/` per Decision 63 |
| b | `package.json` with `"type": "module"` | ESM project (Decision 75). All pinned versions from Decision 77 |
| c | Dependencies: `electron@40.8.0`, `@jitsi/robotjs@0.6.21`, `node-pty@1.1.0`, `electron-store@11.0.2`, `chokidar@5.0.0`, `@xterm/xterm@6.0.0`, `@xterm/addon-webgl`, `@xterm/addon-fit@0.11.0`, `@xterm/addon-web-links@0.12.0`, `@xterm/addon-search@0.16.0`, `@xterm/addon-unicode11`, `marked@17.0.4`, `highlight.js@11.11.1`, `pdf-parse`, `mammoth` | Pin exact versions |
| d | devDependencies: `electron-builder@26.8.2`, `@electron/rebuild@4.0.3` | |
| e | `postinstall` script: `electron-rebuild -f -w node-pty` | Rebuild native modules for Electron's Node ABI |
| f | `electron-builder` config in `package.json` (mac target) | `NSAudioCaptureUsageDescription` in `extendInfo` (Decision 74/Electron 39) |
| g | Main process entry point: `src/main.js` (ESM) | `import.meta.url` + `fileURLToPath()` replaces `__dirname` (Decision 75) |
| h | Preload script: `src/preload.js` | `contextBridge.exposeInMainWorld` skeleton (Decision 72). Use `registerPreloadScript()` not deprecated `setPreloads()` (Decision 74/Electron 35) |
| i | `.gitignore` for `node_modules/`, `dist/`, `out/` | |
| j | `npm install` + verify `electron-rebuild` succeeds for `node-pty` on Apple Silicon | Validates Decision 71 — darwin-arm64 prebuilts |
| k | Smoke test: `npx electron .` opens an empty BrowserWindow | |

### M0.2 — MCP Server Expansion (Remote)
**Stream A** | Effort: XL | Dependencies: none

These 4 sub-groups can themselves be parallelized across the existing MCP codebase.

**M0.2a — Documents MCP (port 8102): 4 new tools**

| # | Sub-task | Detail |
|---|----------|--------|
| a | `docs_upload_global` tool | Wrap `POST /global_docs/upload` — multipart file, display_name, folder_id, tags |
| b | `docs_delete_global` tool | Wrap `DELETE /global_docs/<doc_id>` |
| c | `docs_set_global_doc_tags` tool | Wrap `POST /global_docs/<doc_id>/tags` |
| d | `docs_assign_to_folder` tool | Wrap `POST /doc_folders/<id>/assign` |
| e | Tests: verify all 4 tools via MCP client | |

**M0.2b — PKB MCP (port 8101): 3 new tools**

| # | Sub-task | Detail |
|---|----------|--------|
| a | `pkb_list_contexts` tool | Wrap `GET /pkb/contexts` — returns contexts with claim counts |
| b | `pkb_list_entities` tool | Wrap `GET /pkb/entities` — returns entities with types and linked claims |
| c | `pkb_list_tags` tool | Wrap `GET /pkb/tags` — returns tags with hierarchy and claim counts |
| d | Tests: verify all 3 tools via MCP client | |

**M0.2c — Image Generation MCP (port 8107): 1 new tool + new server**

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create new MCP server file `mcp_server/image_gen.py` | Same pattern as other MCP servers. Starlette + JWT auth |
| b | `generate_image` tool | Wrap `generate_image_from_prompt()` from `endpoints/image_gen.py`. Accept prompt, optional base64 image input. Return base64 image |
| c | Server startup script / integration into screen session | Bind to `127.0.0.1:8107` |
| d | Tests: verify tool via MCP client | |

**M0.2d — Prompts & Actions MCP (port 8105): 1 new tool**

| # | Sub-task | Detail |
|---|----------|--------|
| a | `transcribe_audio` tool | Wrap `POST /transcribe` — accept base64 audio bytes, return transcribed text. Server calls Whisper API (Decision 48) |
| b | Tests: verify tool via MCP client | |

### M0.3 — nginx Reverse Proxy for MCP
**Stream A** | Effort: M | Dependencies: none (but test after M0.2)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Bind all MCP servers to `127.0.0.1` | Currently some may bind `0.0.0.0`. Audit and fix all 8 servers |
| b | Add 8 nginx location blocks to existing HTTPS server block | `/mcp/search/` → `:8100`, `/mcp/pkb/` → `:8101`, `/mcp/docs/` → `:8102`, `/mcp/artefacts/` → `:8103`, `/mcp/conversations/` → `:8104`, `/mcp/prompts/` → `:8105`, `/mcp/code/` → `:8106`, `/mcp/image/` → `:8107` |
| c | Each location: `proxy_pass http://127.0.0.1:<port>/;` (trailing slash strips prefix), `proxy_buffering off`, `proxy_read_timeout 300s` | Same SSL cert, no new domains |
| d | `sudo nginx -t && sudo systemctl reload nginx` | |
| e | Test all MCP servers via `https://assist-chat.site/mcp/*/health` | Verify JWT auth works through nginx |

### M0.4 — Main UI tools.py Expansion (Dual-Surface)
**Stream A** | Effort: L | Dependencies: none (parallel with M0.2)

Add corresponding tool handlers in `code_common/tools.py` so the Sidebar Chat (Tab 1) can also use the new tools via the existing tool-calling framework. Per `mcp_expansion.plan.md` Section 3.

| # | Sub-task | Detail |
|---|----------|--------|
| a | 4 new Document tool handlers | `upload_global_doc`, `delete_global_doc`, `set_global_doc_tags`, `assign_doc_to_folder` — using existing `database/global_docs.py` functions |
| b | 3 new PKB tool handlers | `pkb_list_contexts`, `pkb_list_entities`, `pkb_list_tags` — using existing `truth_management_system/` functions |
| c | 1 new Image Generation tool handler | `generate_image` — using existing `generate_image_from_prompt()` |
| d | 1 new Transcribe Audio tool handler | `transcribe_audio` — using existing `POST /transcribe` logic |
| e | Register all 9 new tools with `@register_tool` decorator | Follow existing pattern in tools.py |
| f | Update tool count references in docs (57 → 66 tools) | |

### M0.5 — Local Filesystem MCP Server
**Stream E** | Effort: L | Dependencies: → M0.1.b (needs package.json)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create `desktop/src/mcp/filesystem-server.js` | Node.js MCP server, streamable-HTTP transport, no auth (localhost only) |
| b | Implement 10 tools: `fs_read_file`, `fs_write_file`, `fs_edit_file`, `fs_list_directory`, `fs_glob`, `fs_grep`, `fs_run_shell`, `fs_mkdir`, `fs_move`, `fs_delete` | Each tool validates paths via `path.resolve(workdir, userPath)` then `startsWith(workdir)` |
| c | Dynamic port allocation (find free port on startup) | Export port number to parent Electron process via IPC |
| d | Sandbox validation: write tests for path traversal attempts (`../`, symlinks, absolute paths outside workdir) | |
| e | `fs_run_shell`: 120s timeout, `cwd` = workdir, capture stdout/stderr | |
| f | Smoke test: spawn server, call each tool via HTTP, verify responses | |

### M0.6 — desktopBridge API (Server-Side)
**Stream A** | Effort: M | Dependencies: none

This is a change to `interface/interface.html` (server-side) that defines the stable injection surface for all Electron `executeJavaScript()` calls. Per Phase 4 plan, but it **should be built early** since Phases 4, 5, 6, and 7 all depend on it.

| # | Sub-task | Detail |
|---|----------|--------|
| a | Add `window.desktopBridge` object in `interface.html` (or a new `desktop-bridge.js` module) | Only active when loaded inside Electron (detect via `navigator.userAgent` or preload-injected flag) |
| b | `desktopBridge.openGlobalDocsModal(filePath)` | Opens Global Docs modal, pre-fills file. Calls `GlobalDocsManager` methods |
| c | `desktopBridge.openPKBModal(text)` | Opens PKB Add Memory modal with text pre-filled, triggers auto-fill API |
| d | `desktopBridge.openPKBIngestFlow(text)` | Opens PKB text ingestion flow via existing ingest UI |
| e | `desktopBridge.fillChatInput(text)` | Inserts text into chat input textarea |
| f | `desktopBridge.attachFileToChatInput(fileInfo)` | Simulates file attachment in chat input (triggers existing attachment flow) |
| g | Guard: all methods are no-ops when not in Electron context | Prevent errors in normal browser usage |
| h | Test: open web UI in browser, verify no errors and bridge methods are inert | |

---

## M1: Core Shell (Week 2–4)

The Electron app skeleton with 3-tab Sidebar, tray, hotkeys, and auth. This is the **longest milestone** and contains the critical path.

### M1.1 — Sidebar BrowserWindow [CP]
**Stream B** | Effort: L | Dependencies: → M0.1.k (scaffold smoke test)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create `BrowserWindow` with `alwaysOnTop: true`, `level: 'floating'`, `type: 'panel'` | Non-activating overlay per Decision 69 |
| b | Default size: 400px wide, full screen height. Right-edge snapped | |
| c | Snap buttons in minimal title bar: Right / Left / Bottom / Float | Like Chrome DevTools dock |
| d | Resize handling: freely resizable when floating, full height/width when snapped | |
| e | Position + size + snap-state persistence via `electron-store` | Restore on restart (Decision 57) |
| f | Off-screen recovery: if stored position is offscreen after display change, reset to default | |
| g | Tab bar UI: 3 tabs — Chat, OpenCode, Terminal | HTML/CSS tab switcher in Sidebar renderer |
| h | Tab switching: show/hide corresponding `BrowserView` per active tab | |

### M1.2 — Tab 1: Chat BrowserView [CP]
**Stream B** | Effort: M | Dependencies: → M1.1.a

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create `BrowserView` inside Sidebar, load `https://assist-chat.site/` | Full web UI as-is |
| b | Handle responsive layout: at ~400px the workspace sidebar auto-hides (existing mobile responsive mode) | Verify existing CSS handles this |
| c | Offline/disconnect handling: intercept failed loads, show custom offline page (Decision 54) | "Cannot reach Science Reader server" + Retry button |
| d | Caching: implement `protocol.registerFileProtocol` or service worker for static assets | Reduce load time on subsequent opens |
| e | Inject preload script into BrowserView via `registerPreloadScript()` | This BrowserView needs `desktopBridge` access |
| f | Test: full web UI features work — chat, PKB, Global Docs modal, artefacts, tool calling | |

### M1.3 — Session Cookie Sharing [CP]
**Stream B** | Effort: M | Dependencies: → M1.2.a (BrowserView exists)

| # | Sub-task | Detail |
|---|----------|--------|
| a | After user logs in via BrowserView, extract Flask session cookie via `session.defaultSession.cookies.get({ url: serverUrl })` | |
| b | Create `auth.js` module: `getSessionCookie()` returns cookie string for HTTP headers | Used by all main process API calls |
| c | Detect session expiry: watch for BrowserView navigating to login page | Re-extract cookie after re-login |
| d | Include cookie as `Cookie` header in all main-process `fetch` / `net.request` calls | |
| e | Pre-login guard utility: `requireAuth()` — if no cookie, auto-open Sidebar to login page | Reused by PopBar, folder sync, etc. |
| f | Test: main process can call `GET /list_conversations` using extracted cookie | |

### M1.4 — Tray Icon & Global Hotkeys
**Stream B** | Effort: M | Dependencies: → M0.1.g (main process entry)

| # | Sub-task | Detail |
|---|----------|--------|
| a | `Tray` icon in menu bar (monochrome template image) | |
| b | Tray dropdown menu: Show/Hide PopBar, Show/Hide Sidebar, Dictation, Capture Screen, separator, Connected status, Settings, Quit | |
| c | Connection status indicator: connected/disconnected based on periodic health check to server | |
| d | `globalShortcut.register('CommandOrControl+Shift+Space', ...)` → toggle PopBar | |
| e | `globalShortcut.register('CommandOrControl+Shift+J', ...)` → toggle Sidebar | |
| f | `globalShortcut.register('CommandOrControl+J', ...)` → toggle Dictation Pop | |
| g | `globalShortcut.register('CommandOrControl+Shift+S', ...)` → capture screenshot | |
| h | `globalShortcut.register('CommandOrControl+Shift+M', ...)` → save to memory mode | |
| i | Hotkey conflict detection: warn user if registration fails (another app has the shortcut) | |
| j | `app.on('will-quit', () => globalShortcut.unregisterAll())` | Clean up |

### M1.5 — Tab 2: OpenCode Integration
**Stream E** | Effort: XL | Dependencies: → M0.2 (MCP servers up), → M0.3 (nginx proxy), → M0.5 (local FS MCP), → M1.1 (Sidebar window)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Working directory manager: `electron-store` for recent dirs (last 10) + pinned favorites | |
| b | Directory picker UI in Tab 2 header: dropdown of recent + pinned + "Browse..." button (→ `dialog.showOpenDialog`) | |
| c | Spawn `opencode web --port <dynamic> --hostname 127.0.0.1` as child process | `cwd` = selected working directory |
| d | Inject `MCP_JWT_TOKEN` env var into child process environment | Token from `electron-store` or config file |
| e | Generate `opencode.json` template with remote MCP server URLs (`https://assist-chat.site/mcp/*`) + local filesystem MCP (`http://127.0.0.1:<port>`) | Write to working directory or use `--config` flag |
| f | Second `BrowserView` loading `http://127.0.0.1:<dynamic-port>` | OpenCode Web UI |
| g | Directory change flow: warn user dialog → kill opencode process (SIGTERM → SIGKILL 2s) → restart with new cwd | Also signal terminal (Tab 3) about new cwd |
| h | Handle child process crash: show error in Tab 2, "Restart" button | |
| i | Clean shutdown: kill opencode process on app quit | |
| j | Test: OpenCode can search PKB, read docs, edit local files, run shell commands | End-to-end MCP verification |

### M1.6 — Tab 3: Local Terminal
**Stream E** | Effort: XL | Dependencies: → M0.1.j (node-pty rebuilt), → M1.1 (Sidebar window)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Terminal BrowserView: HTML page with xterm.js setup | Load `@xterm/xterm`, WebGL addon, fit addon, web-links addon, search addon, unicode11 addon |
| b | WebGL renderer setup: `try { terminal.loadAddon(new WebglAddon()) } catch { /* DOM fallback */ }` | Decision 76 |
| c | Catppuccin Mocha theme: port from existing `interface/opencode-terminal.js` | Reuse same color values |
| d | IPC bridge: main process → renderer | `ipcMain.on('terminal:data', ...)` routes PTY stdout to xterm.js `terminal.write()`. `ipcMain.on('terminal:input', ...)` routes xterm.js `terminal.onData()` to PTY stdin |
| e | Spawn PTY via `node-pty`: `pty.spawn(process.env.SHELL || '/bin/zsh', [], { cwd: workdir })` | Inherits user shell profile |
| f | Terminal instance tab bar: New (Cmd+N), Close (Cmd+W), Switch (Cmd+[/]) | Multiple independent PTY processes |
| g | Split panes: Cmd+D (vertical), Cmd+Shift+D (horizontal) | Each pane = independent PTY |
| h | Shared working directory: new terminals start in OpenCode tab's cwd. Existing terminals keep their cwd | |
| i | Keyboard shortcuts: Cmd+C (copy selection), Ctrl+C (SIGINT), Cmd+V (paste), Cmd+K (clear), Ctrl+Shift+F (search) | Decision 51: Cmd+C always copies |
| j | PTY cleanup on tab close: SIGTERM → wait 2s → SIGKILL | Same pattern as `endpoints/terminal.py` |
| k | PTY cleanup on app quit: iterate all PTY processes, same cleanup | |
| l | `addon-fit`: auto-resize on container resize / Sidebar resize / snap position change | `terminal.fit()` on resize observer |
| m | Scrollback: 5000 lines default | |
| n | Test: open terminal, run `ls`, `git status`, verify output. Test split panes. Test multiple instances | |

---

## M2: Focus Management (Week 3)

Can overlap with late M1 work. Only needs the Sidebar BrowserWindow to exist.

### M2.1 — Focus State Machine [CP]
**Stream B** | Effort: L | Dependencies: → M1.1.a (Sidebar window)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Implement 3-state focus model: Hidden → Hover → Active | Per section 4.9 of PRD |
| b | Hover state: `setFocusable(false)` + `setIgnoreMouseEvents(true, { forward: true })` | Decision 69 — `forward: true` is mandatory for hover detection |
| c | Active state: on text input click → `setFocusable(true)` + `window.focus()` | Detect click on input via IPC from renderer |
| d | Deactivate: `Escape` → `setFocusable(false)` + `window.blur()` | Return keyboard focus to underlying app |
| e | Double-Escape: first Escape = deactivate (hover), second Escape = hide | State machine: Active → Hover → Hidden |
| f | Visual indicators: Hover = 0.85 opacity + thin border + grayed input. Active = full opacity + highlighted border + cursor | CSS class toggles via IPC |
| g | Apply focus model to Sidebar window | |
| h | Apply focus model to PopBar window (created in M3 but focus model designed here) | Reusable `FocusManager` class |
| i | Apply focus model to Dictation Pop window (created in M7) | Same reusable class |
| j | Cross-app persistence: Sidebar + PopBar + Dictation Pop all stay visible on Cmd+Tab (Decision 53) | `alwaysOnTop: true` at `'floating'` level handles this |
| k | Test: open Sidebar, type in input, press Escape, verify focus returns to underlying app. Cmd+Tab, verify overlay stays visible | |

---

## M3: PopBar (Week 4–5)

The PopBar is the primary desktop-native interaction surface. Builds on focus management and session auth.

### M3.1 — PopBar Window [CP]
**Stream C** | Effort: M | Dependencies: → M2.1 (focus model), → M1.4.d (PopBar hotkey registered)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create PopBar `BrowserWindow`: ~500x50px, frameless, transparent background, `type: 'panel'`, `alwaysOnTop: true` | |
| b | Default position: fixed top-center (~50px from top, horizontally centered) | Decision 52 |
| c | Drag handle: CSS draggable region | `electron.BrowserWindow.setMovable(true)` |
| d | Persist drag position in `electron-store`, restore on next invocation | |
| e | Off-screen recovery: if stored position is outside current display bounds, reset to center | |
| f | Show/hide via hotkey toggle (`Cmd+Shift+Space`) | Connected to M1.4.d |
| g | Apply `FocusManager` from M2.1 | Hover by default, Active on input click |
| h | Stays visible on app switch (Decision 53) | `alwaysOnTop` handles this |

### M3.2 — PopBar UI (Custom HTML/CSS/JS) [CP]
**Stream C** | Effort: L | Dependencies: → M3.1

| # | Sub-task | Detail |
|---|----------|--------|
| a | PopBar HTML layout: action buttons row + text input + context chip area | `desktop/src/renderer/popbar/popbar.html` |
| b | 8 core action buttons with icons: Quick Ask (💬), Save to Memory (🧠), Explain (📖), Summarize (📝), Screenshot (📸), Search Memory (🗂), Context (🔗), Generate Image (🎨) | |
| c | 2–3 configurable slot buttons (empty by default, configured in Settings) | |
| d | Text input field with placeholder text | |
| e | Model selector dropdown next to input (collapsed by default, shows current model name) | |
| f | Keyboard shortcuts: Enter (execute), Cmd+Enter (execute + escalate), Escape (dismiss), Tab (cycle actions), 1–8 (quick select), Up/Down (input history) | |
| g | Input history: store last 20 inputs in memory (not persisted), navigate with Up/Down | |
| h | Context chip display: `[AppName: WindowTitle | detail]` with × button to remove | |
| i | CSS: compact design, dark theme matching Catppuccin Mocha, smooth animations | |
| j | IPC: all button clicks and input sends communicate with main process via `ipcRenderer` | |

### M3.3 — Results Dropdown [CP]
**Stream C** | Effort: L | Dependencies: → M3.2 (PopBar UI)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Dropdown panel: same width as PopBar, appears below it, max height ~400px, scrollable | Expand PopBar window height dynamically or use a second child window |
| b | Markdown rendering via `marked@17.0.4` | Use v17 token-based renderer API (Decision 77). Import `marked` + configure renderer |
| c | Code highlighting via `highlight.js@11.11.1` | Import core + register languages selectively (Python, JS, TS, JSON, Bash, etc.) |
| d | Streaming AI response display: incremental markdown rendering as tokens arrive | Use SSE `EventSource` or `fetch` with `ReadableStream` for newline-delimited streaming |
| e | **Replace** button: shown only when text was originally selected. Writes result to clipboard, simulates `Cmd+V` via `@jitsi/robotjs`, restores original clipboard after 200ms | Per section 4.14 |
| f | **Copy** button: writes result to clipboard | Always shown |
| g | **Expand** link with choice dropdown: "New Conversation" / "Add to [active conversation name]" | Per section 4.2 escalation |
| h | Expand → New Conversation: call `POST /create_stateless_conversation`, inject query + response, open Sidebar Tab 1 | |
| i | Expand → Add to Active: inject into current Sidebar conversation via `desktopBridge.fillChatInput()` | Needs M0.6 desktopBridge |
| j | Result persistence: dropdown stays open after save/action, user manually dismisses with Escape | |
| k | Mid-stream disconnect: keep partial response visible + show error banner `⚠️ Connection lost` + Retry button (Decision 59) | |
| l | Test: Quick Ask a question, verify streaming markdown renders, copy works, Replace works on selected text | |

### M3.4 — PopBar LLM Backend [CP]
**Stream C** | Effort: L | Dependencies: → M1.3 (session cookie), → M3.3 (dropdown)

| # | Sub-task | Detail |
|---|----------|--------|
| a | **Quick Ask (with tools)**: create temp stateless conversation via `POST /create_stateless_conversation`, then `POST /send_message/<temp_id>` with tool whitelist | Per section 8 PopBar LLM implementation |
| b | **Quick Ask (without tools)**: `POST /ext/llm_action` for simple Explain/Summarize | Direct single-turn LLM call |
| c | **Temp conversation cleanup**: on query completion (success or error), call `DELETE /delete_conversation/<temp_id>` | Decision 66 confirms full cleanup |
| d | Tool calling with max 1–2 iterations, `ask_clarification` always disabled | Client-side enforcement: set `tool_choice="none"` after N iterations |
| e | Inline tool status indicators: tool name + spinner/checkmark in dropdown | |
| f | Configurable tool whitelist from `electron-store` | Default: `pkb_search` + `pkb_add_claim` enabled |
| g | Pre-login guard: if no session cookie, show inline message "Opening Science Reader — please log in" + auto-open Sidebar | Calls `requireAuth()` from M1.3.e |

### M3.5 — PopBar Actions (Non-LLM)
**Stream C** | Effort: M | Dependencies: → M3.4 (LLM backend), → M1.3 (session cookie)

| # | Sub-task | Detail |
|---|----------|--------|
| a | **Save to Memory**: Quick Review form in dropdown — text display + Quick Save / Review & Edit / Extract Multiple buttons | Per section 4.5 |
| b | Quick Save: `POST /pkb/analyze_statement` → `POST /pkb/claims`. Toast notification on success | |
| c | Review & Edit: open Sidebar + call `desktopBridge.openPKBModal(text)` | Needs M0.6 |
| d | Extract Multiple: open Sidebar + call `desktopBridge.openPKBIngestFlow(text)` | Needs M0.6 |
| e | **Search Memory**: `POST /pkb/search` with query. Results in dropdown as claim cards (statement, type badge, domain label) | |
| f | **Generate Image**: `POST /api/generate-image` with prompt + optional context. Image card in dropdown with download button | |
| g | **Prompt slots**: fetch pinned prompts via `GET /prompts/list`, show mini-list on click, run selected prompt on text/input | |
| h | Test: each PopBar action end-to-end | |

---

## M4: File Ingestion + desktopBridge Integration (Week 5–6)

Connects drag-and-drop files to the existing web UI modals via the desktopBridge.

### M4.1 — Drag-and-Drop Handler
**Stream B** | Effort: M | Dependencies: → M1.1 (Sidebar), → M3.1 (PopBar window), → M0.6 (desktopBridge)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Drop zone visual indicator on Sidebar + PopBar: dashed border, blue tint, "Drop to add" label on dragover | |
| b | Detect drop location: Sidebar chat-input area vs. Sidebar message history vs. PopBar | Route to different handlers per section 4.8 |
| c | PopBar drop / Sidebar non-input drop: open Sidebar Tab 1 + call `desktopBridge.openGlobalDocsModal(filePath)` | File pre-filled in Global Docs modal |
| d | Sidebar chat-input drop: let web UI's existing `setupPaperclipAndPageDrop()` handle it natively | No desktop-specific code needed |
| e | File path extraction from Electron drop event: use `webUtils.getPathForFile()` (Electron 32+ replaced `File.path`) | Decision 74 |
| f | Toast notifications via Electron `Notification` API for success/failure | |
| g | Test: drag PDF from Finder to Sidebar, verify Global Docs modal opens with file pre-filled. Drag to chat input, verify attachment strip shows | |

### M4.2 — desktopBridge Preload Integration
**Stream B** | Effort: M | Dependencies: → M0.6 (desktopBridge server-side), → M1.2.e (preload script)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Electron preload script exposes `window.isDesktopApp = true` flag via `contextBridge` | The server-side `desktopBridge` checks this flag to activate |
| b | Preload exposes specific IPC methods: `desktopBridge.onOpenGlobalDocs(callback)`, `desktopBridge.onOpenPKBModal(callback)`, etc. | Whitelist-only IPC — never expose raw `ipcRenderer` (Decision 72) |
| c | Main process sends IPC messages when drag-drop / Finder / Services actions need web UI modals | The preload-bridged listener calls the server-side `desktopBridge` methods |
| d | Test: end-to-end drag file → IPC → preload → desktopBridge.openGlobalDocsModal → modal opens with file | |

---

## M5: Text Selection → PKB (macOS Services) (Week 6–7)

Right-click selected text anywhere on macOS to trigger Science Reader actions.

### M5.1 — macOS Services Registration
**Stream D** | Effort: M | Dependencies: → M0.1.f (electron-builder config for Info.plist)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Add `NSServices` entries to `Info.plist` via electron-builder `extendInfo` | 6 services: Save to Memory, Ask About This, Explain, Summarize, Send to Chat, Run Prompt |
| b | Each service declares `NSSendTypes: [NSStringPboardType]` to receive selected text | |
| c | `NSMessage` handler names: `saveToMemory`, `askAboutThis`, `explain`, `summarize`, `sendToChat`, `runPrompt` | |
| d | App restart required for macOS to discover new Services (one-time) | Document in user instructions |
| e | Test: select text in TextEdit, right-click → Services, verify "Science Reader: ..." items appear | |

### M5.2 — Apple Events Handler
**Stream D** | Effort: M | Dependencies: → M5.1, → M3.4 (PopBar LLM backend)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Register Apple Events / pasteboard handler in Electron main process | Receive text from macOS Services via pasteboard (`NSStringPboardType`) |
| b | Route `saveToMemory` action: show PopBar with Quick Review form (Quick Save / Review & Edit / Extract Multiple) | Reuses M3.5.a |
| c | Route `askAboutThis` action: open PopBar with text in Quick Ask mode, input pre-filled with `"Explain this: <text>"` | User can edit before sending |
| d | Route `explain` action: direct PopBar action, send text with "Explain this:" prefix, result in dropdown | No user input step |
| e | Route `summarize` action: same as explain but "Summarize this:" prefix | |
| f | Route `sendToChat` action: open Sidebar, call `desktopBridge.fillChatInput(text)` | Needs M0.6 |
| g | Route `runPrompt` action: open PopBar with pinned prompt selector, apply to text | Reuses M3.5.g prompt slot logic |
| h | Test: select text in Safari, right-click → Services → each action. Verify end-to-end flow | |

---

## M6: Screen Context & Capture (Week 7–9)

The most technically complex milestone: native Swift addon, screenshot capture, OCR, context awareness, in-place text replacement.

**Note**: M6.1 (Swift addon) can start as early as M0 since it has no Electron dependencies beyond the scaffold. Starting it early de-risks the most uncertain piece.

### M6.1 — Swift Accessibility Addon (START EARLY)
**Stream D** | Effort: XL | Dependencies: → M0.1.b (package.json for N-API build config)

This is the **highest-risk** task in the project. It involves writing a native Swift/Objective-C N-API addon that wraps macOS Accessibility APIs.

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create `desktop/native/accessibility/` with N-API + Swift bridge | `node-addon-api` or raw N-API. Swift code calls `AXUIElement` APIs. Bridged via C++ wrapper |
| b | `getActiveApp()`: return `{ name, bundleId, pid }` | `NSWorkspace.shared.frontmostApplication` |
| c | `getWindowTitle()`: return window title of frontmost app | `AXUIElementCopyAttributeValue(app, kAXTitleAttribute)` |
| d | `getSelectedText()`: return currently selected text | `AXUIElementCopyAttributeValue(focused, kAXSelectedTextAttribute)` |
| e | `getFocusedElement()`: return reference to focused UI element | For smart paste target (Decision 47) |
| f | `getBrowserURL()`: AppleScript bridge for Safari/Chrome/Arc URL | `tell application "Safari" to get URL of current tab of front window` |
| g | `getFinderSelection()`: AppleScript bridge for Finder file paths | `tell application "Finder" to get selection as alias list` |
| h | `getVSCodeFilePath()`: AppleScript bridge for VS Code/Xcode current file | |
| i | Build configuration: `node-gyp` / `cmake-js` for Apple Silicon. Ensure C++20 (Electron 38 requirement) | |
| j | Rebuild with `@electron/rebuild` after `npm install` | Add to postinstall script |
| k | macOS Accessibility permission prompt: detect if permission granted, guide user to System Settings if not | |
| l | Test: run addon, verify it reads window title, selected text, browser URL from Safari | Requires Accessibility permission |

### M6.2 — Screenshot Capture (4 Modes)
**Stream D** | Effort: L | Dependencies: → M3.1 (PopBar window for UI), → M6.1.b (active app detection for window capture)

| # | Sub-task | Detail |
|---|----------|--------|
| a | **App Window** capture: `desktopCapturer.getSources({ types: ['window'] })` + filter by frontmost window | Match using PID from `getActiveApp()` |
| b | **Full Screen** capture: `desktopCapturer.getSources({ types: ['screen'] })` + `screen.getAllDisplays()` | Capture the display containing the overlay |
| c | **Select Area** capture: temporarily hide PopBar + show crosshair overlay + user draws rectangle + capture region | New transparent fullscreen window for crosshair selection |
| d | **Scrolling Screenshot (browsers)**: integrate with Chrome extension's existing full-page capture API | The extension already has 3 capture modes (DOM, OCR, Full OCR) with cross-origin iframe support |
| e | **Scrolling Screenshot (native apps)**: Accessibility API auto-scroll + stitch | Send scroll events via Accessibility API, capture visible area at each position, stitch images with canvas |
| f | Screenshot dropdown submenu UI in PopBar: 8 options (4 modes × plain/+OCR) | Single click = App Window + OCR (Decision 55). Chevron/long-press = full submenu |
| g | Screen Recording permission prompt on first capture attempt | Check `CGPreflightScreenCaptureAccess()` / `CGRequestScreenCaptureAccess()` |
| h | Test: capture app window, full screen, select area. Verify images are clean and correctly cropped | |

### M6.3 — OCR Integration
**Stream D** | Effort: M | Dependencies: → M6.2 (screenshots to OCR)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Plain +OCR: send captured image to `POST /ext/ocr` endpoint | Base64 encode image, POST to backend |
| b | "Extract Comments" checkbox in capture dropdown | Per section 4.6 — adds `extract_comments: true` flag to OCR request |
| c | Display OCR results in Results Dropdown: clean text section + separate Comments section (`[anchor → body]` pairs) | |
| d | Action buttons on OCR results: Replace, Copy, "Ask AI" (sets OCR text as context chip), "Save to PKB" | |
| e | "Ask AI" action: set OCR text as context chip in PopBar input + attach screenshot image, focus input | |
| f | Test: capture app window + OCR a text-heavy app, verify extracted text. Test Extract Comments on a Google Doc with comments | |

### M6.4 — Context Awareness (Context Button)
**Stream D** | Effort: L | Dependencies: → M6.1 (Swift addon), → M3.2 (PopBar UI)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Context button (`🔗`) in PopBar: dropdown with 4 levels — Basic, + Selected Text, + Screenshot, + Full Scrolling OCR | Per section 4.11 |
| b | **Basic**: `getActiveApp()` + `getWindowTitle()` | From Swift addon |
| c | **+ Selected Text**: Basic + `getSelectedText()` | From Swift addon |
| d | **+ Screenshot**: Basic + App Window capture | From M6.2.a |
| e | **+ Full Scrolling OCR**: Basic + scrolling screenshot + OCR | From M6.2.d/e + M6.3.a |
| f | Per-app enrichment: Safari/Chrome → URL, VS Code → file path, Finder → selected files, Terminal → cwd | AppleScript bridges from M6.1.f/g/h |
| g | Context chip display: `[AppName: WindowTitle | level_detail]` with × button | |
| h | Include context as system message in next PopBar AI request | Prepend context to LLM system prompt |
| i | Test: open Safari, press PopBar hotkey, click Context → + Selected Text, verify chip shows URL and selected text | |

### M6.5 — Sidebar Screenshot Integration
**Stream D** | Effort: M | Dependencies: → M6.2 (capture), → M6.3 (OCR), → M0.6 (desktopBridge)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Inject 📸 button into Sidebar Tab 1 chat input toolbar via preload script / `desktopBridge` | Per section 4.6 Sidebar screenshot flow |
| b | Button click → same capture mode submenu (8 options + Extract Comments) | |
| c | Plain capture: insert image as attachment thumbnail above chat input (existing attachment UX) | Use `desktopBridge.attachFileToChatInput(imageData)` |
| d | +OCR capture: insert extracted text into chat input + attach screenshot as image | Call `desktopBridge.fillChatInput(ocrText)` + attach image |
| e | Test: click Sidebar screenshot button, capture + OCR, verify text appears in chat input with image attached | |

### M6.6 — In-Place Text Replacement (@jitsi/robotjs)
**Stream D** | Effort: M | Dependencies: → M0.1.c (@jitsi/robotjs installed)

| # | Sub-task | Detail |
|---|----------|--------|
| a | `clipboard.readText()` to save original clipboard before Replace action | Using Electron clipboard API (must use main process, not renderer — Electron 40 deprecated renderer clipboard) |
| b | `clipboard.writeText(aiResult)` to write AI result | |
| c | `robotjs.keyTap('v', 'command')` to simulate Cmd+V in frontmost app | |
| d | After 200ms delay, restore original clipboard: `clipboard.writeText(originalClipboard)` | |
| e | Replace button: only shown when text was originally selected (tracked in PopBar state) | |
| f | Test: select text in Notes, use Explain action, click Replace, verify text is replaced in Notes | |

### M6.7 — Text Selection Auto-Trigger (Optional)
**Stream D** | Effort: M | Dependencies: → M6.1 (Swift addon for text selection detection), → M3.1 (PopBar)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Off by default. Toggle in Settings | Decision: off by default (section 4.1) |
| b | Poll `getSelectedText()` or use Accessibility notifications to detect text selection changes | 400ms debounce (Decision 58) |
| c | On selection detected: auto-show PopBar with context chip containing selected text | |
| d | Per-app toggle if feasible (v1: simple global on/off is acceptable) | |
| e | Test: enable in settings, select text in Safari, verify PopBar appears after 400ms with selection | |

---

## M7: Voice Dictation (Week 8–10)

Mostly independent of M5 and M6. Can run in parallel once basic window infrastructure exists.

### M7.1 — Dictation Pop Window
**Stream C** | Effort: M | Dependencies: → M2.1 (focus model), → M1.4.f (Cmd+J hotkey)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create Dictation Pop `BrowserWindow`: ~350x120px, frameless, `type: 'panel'`, `alwaysOnTop: true` | |
| b | Default position: bottom-left of screen | |
| c | Draggable, persist position in `electron-store` across restarts (Decision 60) | |
| d | Off-screen recovery: if stored position is outside display bounds, reset to bottom-left | |
| e | Toggle via `Cmd+J` hotkey: show/start recording, or stop if already recording | |
| f | Apply `FocusManager` from M2.1: non-activating by default | |
| g | Stays visible on Cmd+Tab (same as PopBar/Sidebar) | |

### M7.2 — Dictation Pop UI
**Stream C** | Effort: M | Dependencies: → M7.1

| # | Sub-task | Detail |
|---|----------|--------|
| a | Layout: recording indicator (waveform/pulsing dot) + transcribed text area + format dropdown + action buttons | Per section 4.10 |
| b | Recording indicator: pulsing red dot + "Recording..." text + Stop button (■) | |
| c | Transcribed text area: shows transcription result (editable) | |
| d | Format dropdown: Raw (default), As Bullets, As Markdown Paragraphs, Custom Prompt... | |
| e | Action buttons: Copy, Paste, History dropdown | |
| f | History panel: expandable list at bottom, last 10 transcriptions (timestamp + first ~50 chars + format used) | Stored in memory, not persisted across restarts |
| g | CSS: dark theme matching Catppuccin Mocha, compact layout | |

### M7.3 — Audio Recording & Transcription
**Stream C** | Effort: L | Dependencies: → M7.2 (UI), → M1.3 (session cookie for backend calls)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Audio recording via `navigator.mediaDevices.getUserMedia({ audio: true })` + `MediaRecorder` | In Dictation Pop renderer process |
| b | Toggle recording: `Cmd+J` first press = start, second press = stop and transcribe | |
| c | Push-to-talk: hold `Fn` = record, release = stop and transcribe | Low-level key monitoring: may need native addon or `IOKit` for Fn key detection |
| d | Audio format: WAV or WebM (check which `POST /transcribe` accepts) | |
| e | Send recorded audio to `POST /transcribe` on backend | Backend proxies to OpenAI Whisper API (Decision 48). Send as base64 or multipart |
| f | Display transcription result in text area | |
| g | Reformat flow: if format ≠ Raw, send transcription through LLM with reformat prompt → replace text in display | Use PopBar's ephemeral LLM call mechanism |
| h | Reformat selection persists across sessions via `electron-store` | |
| i | Microphone permission prompt on first use | Check `systemPreferences.getMediaAccessStatus('microphone')`, request if needed |
| j | `NSAudioCaptureUsageDescription` already in Info.plist from M0.1.f | |
| k | Test: press Cmd+J, speak, verify transcription appears. Test reformat. Test push-to-talk | |

### M7.4 — Smart Paste
**Stream D** | Effort: M | Dependencies: → M6.1.e (getFocusedElement from Swift addon), → M6.6 (robotjs paste simulation)

| # | Sub-task | Detail |
|---|----------|--------|
| a | On recording start (`Cmd+J` press or `Fn` hold): capture `AXFocusedUIElement` from frontmost app via Swift addon | Store as paste target (Decision 47) |
| b | Clicking Dictation Pop to adjust format does NOT update stored paste target | Only recording-start capture matters |
| c | Paste button: use stored paste target | If target is a text field: write to clipboard + `robotjs.keyTap('v', 'command')` |
| d | No paste target (user invoked dictation with no text field focused): copy to clipboard + toast "Copied to clipboard" | |
| e | Test: open Notes, place cursor in text, Cmd+J, speak, click Paste → verify text appears in Notes at cursor | |

### M7.5 — Dictation in Tray Menu
**Stream B** | Effort: S | Dependencies: → M7.3 (dictation history exists), → M1.4.b (tray menu)

| # | Sub-task | Detail |
|---|----------|--------|
| a | "Recent Dictations" submenu in tray dropdown: last 10 transcriptions | Click to copy to clipboard |
| b | Update tray menu dynamically when new transcription is added | |
| c | Test: dictate twice, verify both appear in tray → Recent Dictations | |

---

## M8: Folder Sync (Week 9–10)

Independent of M5–M7. Only needs session cookie and desktopBridge.

### M8.1 — Folder Sync Engine
**Stream D** | Effort: L | Dependencies: → M1.3 (session cookie for API calls)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Create `desktop/src/services/folder-sync.js` module | Runs in main process |
| b | chokidar watcher: `chokidar.watch(folderPath, { persistent: true, ignoreInitial: true })` | One watcher per configured folder. Use macOS `fsevents` backend |
| c | Sync frequency modes: real-time (fsevents), 5 min, 15 min, hourly, manual | For non-realtime: chokidar detects, but uploads are batched on timer |
| d | Local SQLite cache at `~/.science-reader-desktop/sync_cache.db` | Schema: `{ path TEXT, modified_time INTEGER, global_doc_id TEXT, sync_timestamp INTEGER }` |
| e | **New file** detection: path not in cache → `POST /global_docs/upload` with configured folder_id + tags → record in cache | |
| f | **Modified file** detection: path in cache but `mtime` changed → `POST /global_docs/<id>/replace` (Decision 61 — update in-place, preserve tags/folder) | |
| g | **Deleted file** handling: one-way sync — remove cache entry, do NOT delete from Global Docs | |
| h | Supported file types check: PDF, DOCX, TXT, MD, CSV, images. Skip unsupported | Per section 4.4 |
| i | Duplicate detection: if file already exists in Global Docs by SHA-256, skip upload | |
| j | File filter glob: per-folder include/exclude pattern (default: `*`) | |
| k | Tray icon badge for sync activity: spinning icon during upload | |
| l | Toast notification: "Synced report.pdf to Global Docs" | |
| m | Error handling: retry failed uploads 3 times with exponential backoff, then skip and log | |
| n | Test: configure watched folder, drop a PDF in, verify it appears in Global Docs. Modify it, verify update. Delete it, verify Global Docs unchanged | |

### M8.2 — Folder Sync Settings UI
**Stream D** | Effort: M | Dependencies: → M8.1 (engine), → M9.2 (Settings window — or build inline if M9 not started yet)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Watched folders CRUD: list of folders + "Add Folder" button (→ `dialog.showOpenDialog`) | |
| b | Per-folder config: sync frequency dropdown, auto-assign Global Docs folder picker, auto-assign tags input, file filter glob, enable/disable toggle | |
| c | Persist config in `electron-store` | |
| d | On config change: create/destroy chokidar watchers dynamically | |
| e | Test: add folder, set frequency, add tags, verify sync respects all settings | |

---

## M9: Polish & Packaging (Week 10–12)

### M9.1 — electron-builder Packaging
**Stream B** | Effort: M | Dependencies: all previous milestones functional

| # | Sub-task | Detail |
|---|----------|--------|
| a | electron-builder config: target macOS `.app` and `.dmg` | APFS-only DMG (electron-builder 26 requirement) |
| b | `Info.plist` entries: `NSAudioCaptureUsageDescription`, `NSMicrophoneUsageDescription`, `NSAccessibilityUsageDescription`, `NSAppleEventsUsageDescription` (for AppleScript) | |
| c | Bundle native Swift addon (M6.1) into `.app` | Ensure `node-gyp` output is included in asar or unpacked |
| d | Ad-hoc signing script: `codesign --force --deep --sign - /path/to/app.app` | |
| e | Gatekeeper bypass doc: `xattr -cr /path/to/app.app` (one-time) | |
| f | `npm run build` → produces working `.app` | |
| g | Test: build, run from `/Applications`, verify all features work | |

### M9.2 — Settings Window
**Stream B** | Effort: L | Dependencies: → M1.1 (can be started alongside any milestone)

| # | Sub-task | Detail |
|---|----------|--------|
| a | Settings `BrowserWindow`: standard window (not overlay), tabbed panel layout | |
| b | **General** panel: server URL input, startup on login toggle, hotkey configuration (all 6 hotkeys) | |
| c | **PopBar** panel: tool whitelist multi-select, 3 configurable slot pickers (prompt/workflow), default model dropdown, text-selection auto-trigger toggle | |
| d | **Dictation** panel: default reformat option dropdown, push-to-talk key selector | |
| e | **Folder Sync** panel: watched folders CRUD, per-folder sync freq / folder / tags / filter / toggle (from M8.2) | Can be embedded here or standalone |
| f | **Appearance** panel: Sidebar default width slider, default snap position, theme toggle (Catppuccin Mocha / system light/dark) | |
| g | All settings persisted via `electron-store`, applied immediately on change | |
| h | Test: change each setting, verify it takes effect without restart | |

### M9.3 — Launch on Login
**Stream B** | Effort: S | Dependencies: → M9.1 (packaged app)

| # | Sub-task | Detail |
|---|----------|--------|
| a | `app.setLoginItemSettings({ openAtLogin: true })` when enabled in Settings | macOS Login Items |
| b | Toggle in Settings > General | |
| c | Test: enable, restart Mac, verify app launches automatically | |

### M9.4 — Error Handling & Resilience
**Stream B** | Effort: M | Dependencies: all features built

| # | Sub-task | Detail |
|---|----------|--------|
| a | Server disconnect detection: periodic health check (every 30s) to `GET /desktop/status` or root URL | |
| b | Tray icon shows connected/disconnected status with visual indicator | |
| c | Auto-reconnect: when server comes back, refresh session cookie if expired | |
| d | Graceful degradation: offline features still work (terminal, file browsing) | |
| e | Crash recovery: Electron uncaughtException handler — log, show dialog, offer restart | |
| f | Test: kill Flask server, verify tray shows disconnected + PopBar shows error. Restart server, verify reconnect | |

### M9.5 — Performance & Final QA
**Stream B** | Effort: M | Dependencies: all features built

| # | Sub-task | Detail |
|---|----------|--------|
| a | Memory profiling: idle memory usage target < 200MB (Electron base + BrowserViews) | |
| b | CPU profiling: idle CPU usage target < 1% | |
| c | Terminal performance: verify WebGL renderer handles high-throughput output (e.g., `yes` command) | |
| d | Keyboard accessibility: Tab navigation through all forms and buttons | |
| e | Full feature walkthrough: test every UX flow from section 5 of PRD | 8 flows defined in sections 5.1–5.8 |
| f | Permission flow walkthrough: fresh install, grant Accessibility + Screen Recording + Microphone one by one | |

---

## Critical Path Analysis

The **critical path** is the longest chain of sequential dependencies. Delaying any task on this path delays the entire project.

```
M0.1 Scaffold (2h)
  ↓
M1.1 Sidebar Window (8h)
  ↓
M1.2 Tab 1 BrowserView (4h)
  ↓
M1.3 Session Cookie (4h)
  ↓
M2.1 Focus Management (8h)
  ↓
M3.1 PopBar Window (4h)
  ↓
M3.2 PopBar UI (8h)
  ↓
M3.3 Results Dropdown (8h)
  ↓
M3.4 PopBar LLM Backend (8h)
  ↓
M3.5 PopBar Actions (4h)
  ↓
M6.4 Context Awareness (8h)  [← also needs M6.1 Swift addon]
  ↓
M9.5 Final QA (4h)

Total critical path: ~72 hours of sequential work
```

**Critical path insight**: The Swift Accessibility addon (M6.1, ~16h) is NOT on the critical path if started early in parallel with M0–M2. But if delayed until M6, it **becomes** the bottleneck since M6.4, M6.7, M7.4 all depend on it.

---

## Parallel Execution Plan

This shows what can run simultaneously at each phase of the project. Each column is an independent resource/worker.

### Week 1–2: Foundation (M0)
```
Worker 1 (Stream B)    Worker 2 (Stream A)     Worker 3 (Stream A)     Worker 4 (Stream E)     Worker 5 (Stream D)
──────────────────   ────────────────────    ────────────────────    ────────────────────    ────────────────────
M0.1 Scaffold          M0.2a Docs MCP          M0.2c Image Gen MCP    M0.5 Local FS MCP      M6.1 Swift Addon
                       M0.2b PKB MCP           M0.2d Prompts MCP                             (start early!)
                       M0.3 nginx              M0.4 tools.py
                       M0.6 desktopBridge
```

### Week 2–4: Core Shell (M1)
```
Worker 1 (Stream B)    Worker 2 (Stream E)     Worker 3 (Stream E)     Worker 4 (Stream D)
──────────────────   ────────────────────    ────────────────────    ────────────────────
M1.1 Sidebar Window    M1.5 OpenCode Tab 2     M1.6 Terminal Tab 3    M6.1 Swift Addon
M1.2 Tab 1 BrowserView                                                (continued)
M1.3 Session Cookie
M1.4 Tray + Hotkeys
```

### Week 3–5: Focus + PopBar (M2, M3)
```
Worker 1 (Stream B/C)  Worker 2 (Stream C)     Worker 3 (Stream D)     Worker 4 (Stream D)
───────────────────  ────────────────────    ────────────────────    ────────────────────
M2.1 Focus Management  M3.2 PopBar UI *        M6.1 Swift Addon       M6.6 In-Place Replace
M3.1 PopBar Window     M3.3 Results Dropdown   (finish & test)
M3.4 PopBar LLM        M3.5 PopBar Actions

* PopBar UI HTML/CSS can be designed in parallel before the window is ready
```

### Week 5–7: File Ingestion + Services (M4, M5)
```
Worker 1 (Stream B)    Worker 2 (Stream D)     Worker 3 (Stream C)     Worker 4 (Stream D)
──────────────────   ────────────────────    ────────────────────    ────────────────────
M4.1 Drag-and-Drop     M5.1 Services Reg       M7.1 Dictation Window  M6.2 Screenshot Capture
M4.2 desktopBridge Int M5.2 Apple Events       M7.2 Dictation UI      M6.3 OCR Integration
```

### Week 7–9: Screen Context + Dictation (M6, M7)
```
Worker 1 (Stream D)    Worker 2 (Stream D)     Worker 3 (Stream C)     Worker 4 (Stream D)
──────────────────   ────────────────────    ────────────────────    ────────────────────
M6.4 Context Awareness M6.5 Sidebar Screenshot  M7.3 Audio + Whisper   M8.1 Folder Sync
M6.7 Auto-Trigger      M6.6 In-Place Replace   M7.4 Smart Paste       M8.2 Folder Sync UI
                                                M7.5 Tray Dictation
```

### Week 10–12: Polish (M9)
```
Worker 1 (Stream B)    Worker 2 (Stream B)     Worker 3 (Stream B)
──────────────────   ────────────────────    ────────────────────
M9.1 Packaging         M9.2 Settings Window    M9.4 Error Handling
M9.3 Login Item                                M9.5 Final QA
```

---

## Task Count Summary

| Milestone | Tasks | Sub-tasks | Effort Est. | Stream(s) |
|-----------|-------|-----------|-------------|-----------|
| **M0** Foundation | 6 | 56 | XL (week 1–2) | A, B, D, E |
| **M1** Core Shell | 6 | 49 | XL (week 2–4) | B, E |
| **M2** Focus Management | 1 | 11 | L (week 3) | B |
| **M3** PopBar | 5 | 42 | XL (week 4–5) | C |
| **M4** File Ingestion | 2 | 11 | M (week 5–6) | B |
| **M5** macOS Services | 2 | 13 | M (week 6–7) | D |
| **M6** Screen Context | 7 | 47 | XL (week 7–9) | D |
| **M7** Voice Dictation | 5 | 27 | L (week 8–10) | C, D |
| **M8** Folder Sync | 2 | 19 | L (week 9–10) | D |
| **M9** Polish & Packaging | 5 | 27 | L (week 10–12) | B |
| **Total** | **41 tasks** | **302 sub-tasks** | **~12 weeks** | |

---

## Key Risks to Schedule

| Risk | Impact | Mitigation |
|------|--------|------------|
| **M6.1 Swift Accessibility addon** takes longer than expected | Blocks M6.4, M6.7, M7.4 | Start in Week 1. Fallback: use AppleScript-only for v1 (slower but works) |
| **OpenCode Web** spawning issues or MCP connection failures | Blocks Tab 2 functionality | Isolated to Stream E. Tab 1 + Tab 3 work independently |
| **macOS Services** registration doesn't work with ad-hoc signed app | Blocks M5 entirely | Test early in M5.1.e before building handlers. Fallback: hotkey-only text actions |
| **Web UI responsive layout** breaks at 400px | Tab 1 looks broken | Test in M1.2.b. May need CSS overrides (small, isolated fix) |
| **`Fn` key** can't be captured for push-to-talk | Dictation push-to-talk mode unavailable | Fallback: use a different modifier key. Toggle mode (`Cmd+J`) always works |

---

## Quick Reference: What Depends on What

| I need to build... | I must finish first... |
|--------------------|-----------------------|
| Any Electron window | M0.1 Scaffold |
| Tab 2 (OpenCode) | M0.2 + M0.3 + M0.5 (all MCP servers) |
| Tab 3 (Terminal) | M0.1.j (node-pty rebuild) |
| PopBar LLM calls | M1.3 Session Cookie |
| Any desktopBridge call | M0.6 (server-side) + M4.2 (preload integration) |
| macOS Services actions | M3 PopBar + M4 desktopBridge |
| Context awareness | M6.1 Swift Addon |
| Smart paste (Dictation) | M6.1 Swift Addon + M6.6 robotjs |
| In-place Replace | M6.6 (@jitsi/robotjs) |
| Folder sync | M1.3 Session Cookie |
| Settings window | M1.1 (can build the window anytime) |
| Packaging | All features (but can test packaging early with subset) |

---

*End of Build Task Breakdown*
