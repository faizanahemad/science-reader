---
name: Extension Backend Unification (Phase 1)
overview: >
  Deprecate extension_server.py by migrating its functionality into the main server.py.
  The Chrome extension will use the main server as its backend, gaining full Conversation.py
  pipeline benefits (PKB distillation, agents, math formatting, TLDR) while
  eliminating ~4700 lines of duplicate backend code. Extension-specific features (scripts,
  workflows, OCR, page context, memories bridge, prompts bridge) are ported as new
  endpoints/modules in the main server. Extension sidebar uses jsTree-based workspace tree
  (matching main UI), with domain and workspace selection via popup Settings panel.
   KaTeX renders math in LLM responses. Two conversation buttons: New Chat (permanent)
   and Quick Chat (temporary). File attachment system unified with FastDocIndex (BM25, 1-3s
   uploads) by calling existing main backend endpoints directly (zero new server code).
   Document management panels (conversation docs + global docs) and PKB claims viewer
   added as overlay panels in the sidepanel. Full conversation context menu (8 items)
   matching main UI. Attachment context menus for promotion/management.
status: in-progress
created: 2026-02-13
revised: 2026-02-16
---

# Extension Backend Unification — Phase 1 Plan

> **NOTE**: `extension_server.py` referenced in this document has been deprecated. The Chrome extension now uses `server.py` (port 5000). See `documentation/features/extension/` for current architecture.

## Plan Errata (v1.0 → v2.0)

Changes from the initial v1.0 plan based on deep code investigation:

1. **Auth strategy rewritten**: Instead of replacing `@login_required` on all 128+ routes, the new approach updates `get_session_identity()` (called 114 times across 11 files) to be JWT-aware — a single-file fix that upgrades all call sites automatically. `@auth_required` is added only to `/ext/*` endpoints and the subset of existing endpoints the extension needs.
2. **`keyParser_from_env()` eliminated**: Investigation found `keyParser({})` (passing empty dict) returns env-var-only values identically, making a separate function unnecessary.
3. **send_message bridge rewritten**: Task 3.3 now describes the full `send_message()` pipeline internals (queue/threading, pinned claims, users_dir/loader injection, auto-takeaways scheduling) that the bridge must replicate, not just a naive `Conversation.__call__()` invocation.
4. **Conversation storage details corrected**: Filesystem-based storage with exact folder structure, JSON file schemas, ID format (`{email}_{36_chars}`), `DefaultDictQueue` LRU cache (maxsize=200), and field-by-field migration mapping.
5. **Workspace system corrected**: Conversations assigned via join table `ConversationIdToWorkspaceId`, not a field on the conversation. Default workspace pattern: `default_{user_email}_{domain}`.
6. **Streaming formats documented**: Exact JSON shapes for both main server (newline-delimited) and extension (SSE) with field-level comparison.
7. **New tasks added**: Memory/PKB bridge (Task 4.6), Prompts bridge (Task 4.7), Rate limiting (Task 1.6).
8. **Settings clarified**: Extension settings and main server UserDetails are complementary, not overlapping — no merge needed.
9. **Document upload declared Phase 2**: Extension has no upload UI; images (base64) in chat payload work through existing Conversation.py multimodal support.
10. **Risk assessment expanded**: Added risks for auth precedence conflicts, bridge bypassing send_message internals, and conversation ID format mismatch.
11. **Remember-me tokens noted**: Main server has `generate_remember_token`/`verify_remember_token` system that JWT must not interfere with.

### v2.0 → v2.1 Changes (workspace/domain/sidebar)

12. **Domain system documented**: Three domains identified — `assistant`, `search`, `finchat` (defined in `interface/common.js:12`). Extension must support domain switching with sidebar reload.
13. **Workspace hierarchy for extension**: Task 3.1 rewritten to support user choosing domain and workspace hierarchy for conversation placement, not just a single "Browser Extension" workspace.
14. **jsTree sidebar for extension (Task 5.4)**: New task to replace the extension's flat `<ul>` conversation list with a jsTree-based hierarchical workspace tree matching the main UI. Extension currently has no workspace concept (`extension/sidepanel/sidepanel.js` uses flat `renderConversationList()`). New module `extension/sidepanel/workspace-tree.js` mirrors `interface/workspace-manager.js`.
15. **Domain selector (Task 5.5)**: New task to add domain switching UI to extension sidebar, with sidebar reload on domain change.
16. **Temp/permanent conversation buttons (Task 5.6)**: New task to add two creation buttons — "New Chat" (permanent, in selected workspace) and "Quick Chat" (temporary, in default workspace). Replaces single `createNewConversation()` that only created temporary chats.
17. **Milestone 5 effort revised**: From 1-2 days to 4-6 days due to jsTree sidebar conversion (substantial — mirrors 1078 lines of workspace-manager.js).
18. **Extension sidebar documented**: Current flat-list implementation fully mapped — `<ul id="conversation-list">` populated by `renderConversationList()`, no workspace/domain concept.

### v2.1 → v2.2 Changes (API mapping and auth differences)

19. **Complete API endpoint mapping (Section 4c)**: All 38 extension endpoints mapped to main server targets with plan task references, auth requirements, and migration notes. 3 endpoints have no direct main server equivalent and need fresh implementations.
20. **Auth differences documented (Section 4b)**: Side-by-side comparison of all auth aspects — credential verification, token format, session data, remember-me, decorators, identity access, key management, rate limiting, CORS, user creation.
21. **Credential verification discrepancy found**: Extension's `verify_user_credentials()` checks `password_hash` in DB first (SHA256), then falls back to env `PASSWORD`. Main server's `check_credentials()` only checks env `PASSWORD`. Plan Task 1.3 updated to use the extension's more robust pattern.
22. **Extension has zero rate limiting**: Unlike main server (Flask-Limiter on every endpoint), extension_server.py has NO rate limiting at all. All bridge endpoints will ADD rate limits (Task 1.6).
23. **Missing endpoints added to Task 3.2**: `POST /ext/chat/<id>/message` (add message without LLM) and `DELETE /ext/chat/<id>/messages/<msg_id>` (delete specific message) were not in v2.1.

### v2.2 → v2.3 Changes (git diff analysis of recent extension changes)

Analysis of 11 modified extension files (~1438 lines added). Changes are **overwhelmingly client-side** (6 of 7 features are purely browser-side). Only Task 4.3 (OCR) required a plan correction.

**7 features shipped in the extension (pre-unification):**

| # | Feature | Plan Impact | Files | Lines |
|---|---------|-------------|-------|-------|
| 1 | **Inner Scroll Container Detection** — scrolling screenshots now detect and scroll inner elements (not just the window) for web apps like Office Word Online, Google Docs, Notion, etc. 5-stage detection pipeline, known selectors for 15+ apps, capture context management, scroll settle logic, 4 new intra-extension message handlers. | None — purely client-side messaging (`INIT_CAPTURE_CONTEXT`/`SCROLL_CONTEXT_TO`/`GET_CONTEXT_METRICS`/`RELEASE_CAPTURE_CONTEXT` between sidepanel↔content script). Zero backend dependency. | `extractor.js` (+640), `service-worker.js` (+132), `constants.js` (+6) | +778 |
| 2 | **Pipelined Capture + OCR** — OCR fires per-screenshot during capture instead of waiting for all. ~40-60% faster. `captureAndOcrPipelined()`, updated `buildOcrPageContext()` to try pipelined first. | **Minimal** — calls `/ext/ocr` with single images (already supported by same ThreadPoolExecutor endpoint path). No API changes. | `sidepanel.js` | +420 (shared) |
| 3 | **Content Viewer Modal** — paginated viewer to inspect/copy extracted content from the page-context-bar. Eye icon button, per-page navigation, copy-to-clipboard, `ocrPagesData` stored in `pageContext`. | None — purely client-side UI. | `sidepanel.html` (+58), `sidepanel.css` (+141), `sidepanel.js` | +199+ |
| 4 | **Google Docs Extraction Fix** — DOM extractor falsely passed 100-char threshold on toolbar text, bypassing OCR. Threshold raised to 500 chars, chrome-pattern regex filters out toolbar/UI text. | None — client-side content script logic. | `extractor.js` | (included in #1) |
| 5 | **OCR Context Preservation** — OCR content was silently overwritten by DOM re-extraction on summarize/attach/context-menu actions. `isOcr` guards added to `attachPageContent()`, `handleQuickSuggestion('summarize')`, `handleRuntimeMessage(ADD_TO_CHAT)`. | None — client-side guards. Note: Task 5.3 (enriched responses) should preserve this behavior when wiring up the unified backend. | `sidepanel.js` | (included in #2) |
| 6 | **OCR Model Switch** — `openai/gpt-4o` → `google/gemini-2.5-flash-lite` for faster, cheaper OCR on web page screenshots. Max workers 4 → 8. | **Task 4.3 corrected** — ported OCR endpoint must use `gemini-2.5-flash-lite` as default, 8 workers. | `extension_server.py` (+1 functional) | +1 |
| 7 | **Documentation Updates** — all 6 features documented across 5 extension doc files. | Task 6.2 will need to update these again post-unification. | 5 doc files | +40 |

24. **Task 4.3 corrected**: OCR default model updated to `google/gemini-2.5-flash-lite`, max workers to 8. Pipelined single-image OCR pattern documented as supported use case.
25. **`extension_server.py` formatting only**: The file shows ~2000 lines of diff but this is almost entirely Black-style code formatting (single→double quotes, trailing commas, line breaks). No new endpoints, no API changes, no logic changes besides item #6 above.
26. **No plan task changes needed for features 1-5**: All are client-side and will continue working unchanged when the backend switches from port 5001 to 5000, as long as the ported `/ext/ocr` endpoint (Task 4.3) maintains the same request/response contract.
27. **Task 5.3 note**: When implementing enriched responses, preserve the `isOcr` guards in sidepanel.js that prevent DOM re-extraction from overwriting OCR context (feature #5).

### v2.3 → v2.4 Changes (file attachments + simplified frontend)

**File Attachment System** (Feb 16, 2026):

28. **FastDocIndex + global docs shipped**: Main UI has two-list document system (uploaded + message-attached), FastDocIndex (BM25, 1-3s), promotion flows, and global docs. Extension has simple pdfplumber extraction (system messages). Requires unification.
29. **9 bug fixes documented**: Extension PDF upload API call failure, X button removal, first-load attachment loss, display_attachments persistence, LLM awareness, system message handling. All fixes documented in `documentation/features/file_attachments/file_attachment_preview_system.md`.
30. **Milestone 6 added**: File Attachment Unification with 7 tasks (5-7 days). Includes FastDocIndex migration, promotion endpoints, global docs, data migration script. See `extension_backend_unification_v2.3_file_attachments_update.md`.
31. **Endpoint count updated**: 38 → 45 endpoints after file attachment unification.

**Frontend Simplification** (Feb 16, 2026):

32. **Milestone 5 simplified**: User preference for flat list with filters (not jsTree), settings-based domain/workspace selection (not inline UI). Effort reduced from 4-6 days to **2-3 days**.
33. **jsTree task eliminated**: Task 5.4 (jsTree sidebar) replaced with simpler flat-list-with-filters approach. No jQuery, no hierarchical drag-drop, no complex tree state management.
34. **Domain selector simplified**: Task 5.5 (domain tabs) replaced with settings-only approach. Domain stored in ExtensionSettings, no quick switcher needed.
35. **Backend sufficiency confirmed**: Main backend has all needed workspace/domain endpoints. No new backend endpoints required for Milestone 5. Extension calls existing `/list_workspaces/<domain>`, `/create_conversation/<domain>/?workspace_id=<id>` directly.
36. **Timeline updated**: Total plan now **21-30 days** (M1-M7 + testing). Core implementation (M1-M5 without file attachments): **15-23 days**. Realistic auth timeline (3-5 days vs 2-3 days in v2.3) accounts for edge cases.
37. **"Extension" workspace auto-creation** (Task 5.4): Extension Settings panel will auto-create an "Extension" workspace in each domain if it doesn't exist (via `POST /create_workspace/<domain>/Extension`), and use it as the default selected workspace. User can override if desired.
38. **Atomic temporary conversation creation** (Task 5.6): "Quick Chat" button uses `POST /create_temporary_conversation/<domain>` (single atomic endpoint) instead of 3-step flow (create → list → mark temporary). Eliminates race conditions, reduces network round-trips, returns updated conversation/workspace lists in one response. Main UI already uses this endpoint.

### v2.4 → v3.0 Changes (M5 revised — jsTree + KaTeX)

**User decisions (Feb 16, 2026)** that reversed or extended v2.4:

39. **jsTree sidebar restored**: User decided to use jsTree-based workspace tree (matching main UI) instead of flat list with filters. This reverses v2.4's simplification. New file `extension/sidepanel/workspace-tree.js` + `workspace-tree.css`. Dependencies added: jQuery 3.5.1, jsTree 3.3.17.
40. **KaTeX math rendering added**: User requested math rendering in this milestone (previously deferred to Phase 2). KaTeX renders `\[...\]`, `\(...\)`, `$$...$$`, `$...$` delimiters. Applied after message completion only (not during streaming). Dependencies: katex.min.js, katex.min.css, auto-render extension, font files.
41. **Popup settings for domain/workspace**: User chose to put domain/workspace selectors in popup settings (not sidepanel). Both popup.html and sidepanel.html get mirrored dropdowns, reading/writing same Storage keys.
42. **Workspace name confirmed**: "Browser Extension" (not "Extension" as in v2.4.1). Matches M3 implementation.
43. **Domain change = full reset**: When domain changes, clear current conversation + reload tree (not just reload list).
44. **Tasks 5.1-5.3 removed**: Already completed in M1 (API base URL), M3 (streaming parser), and M3 (enriched responses).
45. **Tasks restructured**: 5.4 (popup settings), 5.5 (jsTree), 5.6 (two buttons), 5.7 (KaTeX), 5.8 (data flow wiring).
46. **Effort revised**: 2-3 days → 4-6 days (jsTree sidebar + KaTeX add significant complexity).
47. **No sidebar filters**: Domain is selected in popup settings only; no domain/workspace filter dropdowns in sidebar.

### v3.0 → v3.1 Changes (M5 implementation complete)

**M5 Implementation** (Feb 16, 2026):

48. **M5 fully implemented**: All 5 tasks (5.4-5.8) coded and syntax-verified. Pending live testing in Chrome.
49. **jsTree implementation simplified**: Instead of porting full `workspace-manager.js` (1078 lines), created a focused ~370 line `workspace-tree.js` as a revealing module pattern (IIFE). No drag-drop, no rename, no move — just view, select, create, delete via context menu.
50. **Emoji icons chosen over FontAwesome**: Used Option B from the plan — emoji icons (📁 workspace, 💬 conversation) instead of FontAwesome subset. Avoids additional dependency and CSP concerns.
51. **MV3 CSP discovery**: Chrome MV3 `extension_pages` CSP only allows `script-src 'self'`. All libraries (jQuery, jsTree, KaTeX + fonts) downloaded and bundled locally in `extension/lib/`. External CDN URLs are completely blocked.
52. **jsTree theme files**: Theme assets (CSS + PNGs + GIF) placed in `extension/lib/jstree-themes/default-dark/` subdirectory, not flat in `lib/`.
53. **KaTeX font files**: 20 woff2 files downloaded to `extension/lib/fonts/` for offline math rendering. CSS references fonts via relative `url(fonts/...)` paths.
54. **CustomEvent pattern for tree actions**: WorkspaceTree dispatches DOM CustomEvents (`workspace-tree:select`, `workspace-tree:new-chat`, `workspace-tree:quick-chat`, `workspace-tree:save`, `workspace-tree:delete`) instead of direct function calls, decoupling tree module from sidepanel logic.
55. **`.gitignore` blocks new lib files**: Line 638 of `.gitignore` ignores `lib/` globally. Existing lib files were force-added (`git add -f`). New files need same treatment when committing.
56. **Sidepanel settings mirroring skipped**: Popup settings has domain/workspace dropdowns but sidepanel settings panel does NOT have mirrored dropdowns (simpler — one place to change settings). Domain changes propagate via DOMAIN_CHANGED message.

### v3.1 → v3.2 Changes (M6 complete redesign)

**M6 Redesign** (Feb 16, 2026):

57. **PDF upload is broken post-M1**: Extension's `API_BASE` is `http://localhost:5000` but `api.js` calls `/ext/upload_doc/<id>` which only exists on `extension_server.py` (port 5001). After M1-M4, PDF uploads silently 404. M6 fixes this by pointing at main backend's `/upload_doc_to_conversation/<id>`.
58. **Zero new server endpoints**: All required document endpoints already exist on main backend (`documents_bp`, `global_docs_bp`). Original plan proposed 7 new `/ext/` wrapper endpoints — all eliminated. Extension calls existing endpoints directly, matching M3-M5 pattern.
59. **Task 6.2 (migration script) eliminated**: No old data in `extension.db` needs migration. User confirmed no legacy conversations with PDF system messages.
60. **Images migrate to FastImageDocIndex**: Original plan kept images as base64. User decided images should also go through FastDocIndex/FastImageDocIndex upload path for consistent document handling, `doc_id` tracking, and promotion support.
61. **Docs management panel added**: New overlay panel (like settings-panel) with two collapsible sections — Conversation Docs and Global Docs. Each section supports list, upload, download, remove. Accessed via "Docs" button in button row next to New Chat / Quick Chat.
62. **PKB claims panel added**: New overlay panel for read-only claims browsing with search and filters (type, domain, status). Uses existing `GET /pkb/claims` endpoint. Accessed via "Claims" button in same button row.
63. **Full conversation context menu**: Expanded from 2 items (save/delete) to 8 items matching main UI: Copy Conversation Reference, Open in New Window (main web UI), Clone, Toggle Stateless, Set Flag (submenu with 7 colors), Move to... (flat workspace submenu), Save, Delete.
64. **Attachment context menu added**: Right-click on rendered PDF badges / image thumbnails in messages shows: Download, Promote to Conversation, Promote to Global, Delete. Long-running promotions (15-45s) show toast feedback.
65. **Global docs UI included**: Originally was "Skip global docs UI" then revised — user wants list, add, download, remove for both conversation docs and global docs. No PDF preview needed.
66. **Open in New Window = main web UI**: Opens `/interface/<conversation_id>` on the main web UI in a new browser tab.
67. **Flat workspace submenu for Move to**: Shows all workspaces in a flat jsTree contextmenu submenu list (simple, matches main UI's approach).
68. **Overlay panels for Docs/Claims**: Both panels slide in/out over the main chat view (like settings-panel), dismissable. Not full view replacements.
69. **Button row layout**: Three buttons in a row — New Chat, Quick Chat, then Docs and Claims buttons. All in the action bar above the workspace tree.
70. **M6 effort revised**: 5-7 days → 3-4 days (no server work, no migration, all client-side). Scope increased (panels + context menu) but offset by zero backend work.
71. **Endpoint count unchanged**: No new endpoints added. Extension calls 16 existing main backend endpoints for M6 functionality.

### v3.2 → v3.3 Changes (M6 implementation complete)

**M6 Implementation** (Feb 17, 2026):

72. **M6 fully implemented**: All 7 tasks (6.1-6.7) coded and verified. All JS files pass `node --check` syntax validation. All 22 DOM IDs cross-verified between JS and HTML.
73. **DocsPanel smaller than estimated**: Plan estimated ~250-300 lines, actual is 188 lines. Achieved by removing redundant error handling wrappers and keeping the IIFE lean.
74. **ClaimsPanel smaller than estimated**: Plan estimated ~200-250 lines, actual is 136 lines. Same reason — lean implementation without unnecessary abstractions.
75. **`window.API = API` global export added**: Plan did not anticipate that IIFE scripts (`docs-panel.js`, `claims-panel.js`) loaded as plain `<script>` tags cannot access `API` imported as ES module in `sidepanel.js`. Fix: `sidepanel.js` exports `window.API = API` after import so IIFE panel scripts can call API methods when user interacts.
76. **Open in New Window uses dynamic base URL**: Plan used hardcoded `API_BASE` constant. Implementation uses `Storage.getApiBaseUrl()` to resolve the user-configured server URL (localhost or hosted), matching how all other API calls resolve the base URL.
77. **Docs + Claims buttons as icon-only in header**: Plan showed text buttons in an action-bar div. Implementation adds SVG icon buttons (`docs-btn`, `claims-btn`) alongside existing icon buttons in the header-right div, matching the existing UI pattern (settings gear, new chat +, quick chat ⚡).
78. **Settings button closes panels**: When opening settings, both DocsPanel and ClaimsPanel are hidden. Reciprocally, opening either panel closes settings. Only one overlay visible at a time.
79. **`selectConversation` not `loadConversation`**: Plan referenced `loadConversation()` in clone handler. Actual function name in codebase is `selectConversation()`. Fixed during implementation.
80. **workspace-tree.js imports `API_BASE` from constants.js**: Needed for "Open in New Window" fallback URL. Also imports `Storage` (already imported) for dynamic base URL resolution.

## 1. Problem Statement

The Chrome extension currently runs against a **separate Flask server** (`extension_server.py`, port 5001) with its own conversation engine, storage, and auth system. This creates significant problems:

- **Duplicate code**: ~4700 lines across `extension_server.py` (2681) + `extension.py` (2062) reimplementing conversation management, auth, LLM calls, PKB access, and agent instantiation.
- **Degraded experience**: Extension's chat pipeline (`ext_chat()`) manually builds messages and calls `call_llm()` directly, bypassing `Conversation.py`'s rich pipeline. Extension users miss: PKB distillation with `@reference` resolution, running summaries, math formatting, TLDR auto-summary, document ingestion, memory pad, cross-conversation references, reward system, and code execution.
- **Operational overhead**: Two Flask processes to deploy, monitor, and maintain. Two sets of CORS configs, two auth systems, two conversation storages.
- **Divergent feature sets**: Features added to the main server never reach the extension and vice versa.

## 2. Goals

1. **Single backend**: Extension calls `server.py` (port 5000) instead of `extension_server.py` (port 5001).
2. **Full Conversation.py pipeline**: Extension chat uses the same pipeline as `/send_message/<conversation_id>` with page-context support, giving users the full main-app experience (PKB distillation, agents, math formatting, TLDR, running summaries, cross-conversation references, reward system).
3. **Unified conversation storage**: Extension conversations use the main filesystem-based conversation system with domain/workspace organization. Extension-specific data (scripts, workflows, extension UI settings) migrates from `extension.db` to tables in `users.db`. The `extension.db` file is eventually eliminated.
4. **JWT auth coexistence**: Main server accepts both session cookies (web UI) and JWT Bearer tokens (extension). Identity resolution via `get_session_identity()` is made JWT-aware so all existing endpoint code works without mass edits.
5. **Extension-specific features preserved**: Scripts, workflows, OCR, page context, extension settings, memory/PKB browsing, and prompt access are ported to the main server as new blueprints/modules.
6. **Zero regression for web UI**: All existing web UI behavior remains unchanged, including remember-me tokens and session-based auth.
7. **File attachment unification**: Extension uses main backend's existing FastDocIndex upload endpoint (BM25, 1-3s uploads) instead of broken `/ext/upload_doc` pdfplumber path. Images also upload via FastImageDocIndex. Full support for document promotion (message-attached → conversation → global) and document management (list, download, delete). All via existing main backend endpoints — zero new server code.
8. **Extension UI enhancements**: jsTree-based workspace sidebar (matching main UI), domain/workspace selection in popup settings, two conversation buttons (permanent + temporary), KaTeX math rendering, document management panels (conversation docs + global docs), PKB claims viewer with search/filter, full conversation context menu (8 items matching main UI), attachment context menus for promotion/management.

## 3. Current Architecture (Before)

```
Chrome Extension UI
    │
    ▼ JWT Bearer token
extension_server.py (port 5001)
    ├── /ext/auth/* (JWT auth via ExtensionAuth class)
    ├── /ext/chat/<id> (manual LLM calls via call_llm(), no Conversation.py)
    ├── /ext/conversations/* (ExtensionDB → extension.db SQLite)
    ├── /ext/scripts/* (ExtensionDB → extension.db)
    ├── /ext/workflows/* (ExtensionDB → extension.db)
    ├── /ext/memories/* (reads PKB via StructuredAPI, wraps in {"memories":[...]})
    ├── /ext/prompts/* (reads prompts.json, filtered by allowlist)
    ├── /ext/settings/* (ExtensionDB → extension.db)
    ├── /ext/ocr (vision LLM calls with base64 images)
    └── /ext/models, /ext/agents, /ext/health

Web UI (interface/)
    │
    ▼ Flask session cookie + remember-me token
server.py (port 5000)
    ├── /login, /logout, /get_user_info (session auth + remember-me tokens)
    ├── /send_message/<id> (Conversation.py pipeline via queue/threading)
    ├── /list_conversation_by_user, /create_conversation, etc.
    ├── /upload_doc_to_conversation/<id> (multipart file upload)
    ├── /pkb/* (full PKB CRUD, 40+ routes)
    ├── /get_prompts, /get_prompt_by_name (all prompts, no filter)
    └── ... (128 protected routes across 13 endpoint files)
```

### 3.1 Key Implementation Details

**Main Server Auth** (`endpoints/auth.py`):
- `@login_required` checks `session.get("email")` and `session.get("name")`, redirects to `/login` if missing
- `check_credentials(email, password)` ignores email, compares password to `os.getenv("PASSWORD", "XXXX")`
- Remember-me: `generate_remember_token(email)` creates SHA256 token stored in `{users_dir}/remember_tokens.json`, `check_remember_token` runs as `before_app_request` hook to restore sessions
- Identity: `get_session_identity()` in `endpoints/session_utils.py` reads from Flask `session` directly — called **114 times across 11 endpoint files**

**Main Server Conversation Storage** (filesystem):
- Folder: `storage/conversations/{conversation_id}/`
- ID format: `{email}_{36_random_alphanumeric_chars}` (generated in `_create_conversation_simple`, `endpoints/conversations.py:1111`)
- `{conversation_id}-messages.json` — array of `{"message_id", "text", "sender" (user/model), "user_id", "conversation_id", "message_short_hash"}`
- `memory.json` — `{"title", "last_updated", "running_summary": [...], "title_force_set": bool}`
- `conversation_settings.json`, `uploaded_documents_list.json`, `artefacts.json`, `artefact_message_links.json`
- Cache: `DefaultDictQueue` (LRU, maxsize=200) with `load_conversation` factory that loads from disk + clears lockfiles

**Main Server Domain System** (3 domains):
- Defined in `interface/common.js:12`: `var allDomains = ['finchat', 'search', 'assistant'];` with default `'assistant'`
- UI switches via Bootstrap tabs: `#assistant-tab`, `#search-tab`, `#finchat-tab` (in `interface/interface.js:72-124`)
- Switching tabs sets `currentDomain["domain"]` and calls `WorkspaceManager.loadConversationsWithWorkspaces(true)` to reload the sidebar
- Each domain has its own independent workspace hierarchy with its own default workspace
- `search` domain auto-marks conversations as stateless (`interface/workspace-manager.js:236`)
- Backend routes accept `<domain>` parameter: `/list_workspaces/<domain>`, `/create_conversation/<domain>/<workspace_id>`, etc.

**Main Server Workspace System** (`database/workspaces.py`, `database/connection.py:96-114`):
- Hierarchical folder-like structure: workspaces are folders (unlimited nesting via `parent_workspace_id`), conversations are leaf files
- `UserToConversationId` table: user_email, conversation_id, created_at, updated_at, conversation_friendly_id
- `ConversationIdToWorkspaceId` table: conversation_id (PK), user_email, workspace_id, created_at, updated_at
- `WorkspaceMetadata` table: workspace_id (PK), workspace_name, workspace_color, domain, expanded (bool), parent_workspace_id (nullable), created_at, updated_at
- Default workspace: `default_{user_email}_{domain}` — auto-created if missing during listing, displayed as "General" in the UI
- Workspace ID format: `{email}_{16_random_chars}` (non-default) or `default_{email}_{domain}` (default)
- Workspace colors: primary, success, danger, warning, info, purple, pink, orange (Bootstrap color keys)
- `addConversation()` inserts into BOTH UserToConversationId AND ConversationIdToWorkspaceId
- UI: jsTree 3.3.17 renders VS Code-style file explorer with right-click context menus, wholerow selection, folder/file icons, workspace color indicators (see `interface/workspace-manager.js`, 1078 lines)

**Extension Sidebar** (current — no workspaces):
- Flat conversation list in `extension/sidepanel/sidepanel.html`: `<ul id="conversation-list">` populated by JS
- No workspace or domain concept — all conversations in one flat list
- Conversations rendered as `<li>` items with title, time, save/delete buttons
- Key functions in `extension/sidepanel/sidepanel.js`: `loadConversations()`, `renderConversationList()`, `createNewConversation()`, `selectConversation()`, `deleteConversation()`, `saveConversation()`
- API calls via `extension/shared/api.js`: `getConversations()`, `createConversation()`, `deleteConversation()`, `saveConversation()`
- Popup (`extension/popup/`) shows recent conversations but no management

**Extension Sidebar** (after unification — simplified flat list with filters):
- **Settings-based domain/workspace selection**: Settings panel has domain dropdown and workspace dropdown, stores defaults in `ExtensionSettings.settings_json` as `{default_domain, default_workspace_id, default_workspace_name}`
- **Flat conversation list with filters**: Two dropdowns above list (domain filter: All/Assistant/Search/Finance, workspace filter: All/[workspace names])
- **Optional visual grouping**: Conversations can be grouped by workspace with simple `<li class="workspace-header">Workspace Name</li>` separators (no nesting, no drag-drop)
- **Two creation buttons**: "New Chat" (permanent, in default workspace) and "Quick Chat" (temporary, in default workspace)
- **Backend calls**: `GET /list_conversation_by_user/<domain>` returns conversations with `workspace_id` and `workspace_name` per conversation (no new endpoints needed)
- **No jsTree**: Sidebar remains simple `<ul id="conversation-list">` with `renderConversationList()` enhanced for filtering/grouping
- **Workspace management**: Uses existing main backend endpoints (`/list_workspaces/<domain>`, `/create_conversation/<domain>/?workspace_id=<id>`) — no extension-specific workspace APIs needed

**Main Server keyParser** (`endpoints/utils.py:18-82`):
- Builds dict of all API keys from env vars, then overlays session values: `for k,v: key = session.get(k, v)`
- Returns dict with: openAIKey, jinaAIKey, elevenLabsKey, ASSEMBLYAI_API_KEY, mathpixId, mathpixKey, cohereKey, ai21Key, bingKey, serpApiKey, googleSearchApiKey, googleSearchCxId, openai_models_list, scrapingBrowserUrl, vllmUrl, vllmLargeModelUrl, vllmSmallModelUrl, tgiUrl, tgiLargeModelUrl, tgiSmallModelUrl, embeddingsUrl, zenrows, scrapingant, brightdataUrl, brightdataProxy, OPENROUTER_API_KEY, LOGIN_BEARER_AUTH
- **Key insight**: `keyParser({})` (empty dict) returns pure env-var values, making a separate `keyParser_from_env()` unnecessary

**Main Server send_message pipeline** (`endpoints/conversations.py:1326-1480`):
1. `keys = keyParser(session)`, `email = get_session_identity()[0]`
2. `user_details = getUserFromUserDetailsTable(email)`
3. `checkConversationExists(email, conversation_id)` — ownership check
4. `conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)` — from LRU cache
5. Injects `conversation_pinned_claim_ids` from `state.pinned_claims`
6. Injects `_users_dir` and `_conversation_loader` (lambda loading from cache) into query dict
7. Creates `Queue()`, spawns `generate_response()` thread via `get_async_future()`
8. Thread iterates `conversation(query, user_details)`, captures chunks + message IDs
9. After streaming: schedules `_create_auto_takeaways_doubt_for_last_assistant_message` async
10. Returns `Response(run_queue(), content_type="text/plain")` — yields from queue until `"<--END-->"`

**Main Server Streaming Format** (newline-delimited JSON):
```json
{"text": "chunk", "status": "Generating response...", "message_ids": {"user_message_id": "...", "response_message_id": "..."}, "conversation_id": "..."}\n
```
Completion signaled by status containing "saving answer".

**Main Server CORS** (`server.py:182-194`):
```python
CORS(app, resources={
    r"/get_conversation_output_docs/*": {
        "origins": ["https://laingsimon.github.io", "https://app.diagrams.net/", "https://draw.io/", "https://www.draw.io/"]
    }
})
```
Very restrictive — only one route pattern for draw.io origins.

**Extension Auth** (`extension.py:119-229`):
- `ExtensionAuth.generate_token(email)` — HMAC-SHA256: `payload_b64.signature` where payload = `{"email", "iat", "exp"}`, signature = `sha256(f"{payload_b64}.{JWT_SECRET}")`
- `JWT_SECRET` from env `EXTENSION_JWT_SECRET` or `secrets.token_hex(32)`
- `TOKEN_EXPIRY_HOURS = 24 * 7` (7 days)
- `@require_ext_auth` checks `Authorization: Bearer <token>`, sets `request.ext_user_email`

**Extension Conversation Storage** (SQLite `extension.db`):
- `ExtensionConversations`: conversation_id (PK, 16-hex), user_email, title (default 'New Chat'), is_temporary (default 1), model (default 'gpt-4'), prompt_name, history_length (default 10), created_at, updated_at, summary, settings_json
- `ExtensionMessages`: message_id (PK), conversation_id (FK CASCADE), role (user/assistant), content, page_context (JSON), created_at
- `ExtensionConversationMemories`: id (autoincrement), conversation_id (FK CASCADE), claim_id, attached_at, UNIQUE(conversation_id, claim_id)

**Extension Settings Storage** (SQLite `extension.db`):
- `ExtensionSettings`: user_email (PK), default_model (default 'gpt-4'), default_prompt, history_length (default 10), auto_save (default 0), settings_json (TEXT), updated_at
- These are extension-specific UI preferences, NOT the same as main server's `UserDetails.user_preferences`

**Extension Streaming Format** (SSE):
```
data: {"chunk": "chunk_text"}\n\n
```
Completion:
```
data: {"done": true, "message_id": "..."}\n\n
```

**Extension CORS** (`extension_server.py:80-86`):
```python
CORS(app, resources={
    r"/ext/*": {
        "origins": ["chrome-extension://*", "http://localhost:*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})
```

**Extension Document/Attachment Handling**:
- NO document upload support (no multipart endpoints)
- Images: up to 5 base64 data URLs in chat payload `images` array, added as multimodal message parts
- OCR: separate `/ext/ocr` endpoint processes base64 screenshots via vision model (default: `google/gemini-2.5-flash-lite`, 8 concurrent workers). Extension sidepanel uses both batch (all screenshots at once) and pipelined (one screenshot at a time during capture) OCR patterns. Client-side features include inner scroll container detection (for web apps like Google Docs, Office Online, Notion) and a content viewer modal for paginated OCR text review.

## 4. Target Architecture (After)

```
Chrome Extension UI
    │
    ▼ JWT Bearer token
server.py (port 5000)               ◄── SINGLE SERVER
    ├── endpoints/auth.py            (session + JWT dual identity resolution)
    ├── endpoints/session_utils.py   (get_session_identity() now JWT-aware)
    ├── endpoints/jwt_auth.py        (NEW: JWT token generation/verification)
    ├── endpoints/ext_auth.py        (NEW: /ext/auth/* login/verify)
    ├── endpoints/conversations.py   (existing + page_context support)
    ├── endpoints/ext_bridge.py      (NEW: /ext/conversations/*, /ext/chat/*, utilities)
    ├── endpoints/ext_scripts.py     (NEW: custom scripts CRUD)
    ├── endpoints/ext_workflows.py   (NEW: workflows CRUD)
    ├── endpoints/ext_ocr.py         (NEW: OCR endpoint)
    ├── endpoints/ext_settings.py    (NEW: extension-specific settings)
    ├── endpoints/ext_memories.py    (NEW: /ext/memories/* → PKB bridge with shape translation)
    ├── endpoints/ext_prompts.py     (NEW: /ext/prompts/* → prompts bridge with allowlist)
    ├── endpoints/pkb.py             (existing, JWT-accessible via updated get_session_identity)
    ├── endpoints/prompts.py         (existing, JWT-accessible via updated get_session_identity)
    └── ... (all existing endpoints, identity resolution handles both auth types)

Web UI (interface/)
    │
    ▼ Flask session cookie + remember-me token (unchanged)
    └── Same server.py
```

**Critical note on workspace/domain support**: The main backend already has all necessary endpoints for extension workspace/domain functionality. No new backend endpoints are needed for Milestone 5 (Frontend Updates). The extension will call existing endpoints like `/list_workspaces/<domain>`, `/create_conversation/<domain>/?workspace_id=<id>`, and `/list_conversation_by_user/<domain>` directly. All these endpoints already return workspace_id and workspace_name per conversation, which is exactly what the extension needs for its simplified flat-list-with-filters UI.

## 4b. Auth Mechanism Differences

| Aspect | Main Server (`server.py`) | Extension Server (`extension_server.py`) |
|--------|---------------------------|------------------------------------------|
| **Auth type** | Flask session cookie + remember-me token | JWT Bearer token (HMAC-SHA256) |
| **Login endpoint** | `POST /login` (form data: email, password) → session cookie + optional remember-me cookie | `POST /ext/auth/login` (JSON: email, password) → JWT token string |
| **Credential check** | `check_credentials(email, password)` in `endpoints/auth.py:50-59`: ignores email, compares password to `os.getenv("PASSWORD", "XXXX")` | `verify_user_credentials(email, password)` in `extension_server.py:584-619`: checks `password_hash` in `UserDetails` table first (SHA256), falls back to env `PASSWORD`. **More complex than main server.** |
| **Session data** | `session["email"]`, `session["name"]`, `session["created_at"]`, `session["user_agent"]` | None (stateless JWT). `request.ext_user_email` set by decorator. |
| **Remember-me** | `generate_remember_token(email)` → stored in `{users_dir}/remember_tokens.json`, checked via `check_remember_token` `before_app_request` hook | None |
| **Auth decorator** | `@login_required` → checks `session.get("email")` and `session.get("name")`, redirects to `/login` on failure | `@require_ext_auth` → checks `Authorization: Bearer <token>` header, calls `ExtensionAuth.verify_token()`, sets `request.ext_user_email`, returns JSON 401 on failure |
| **Identity access** | `get_session_identity()` → reads from `session` dict, returns `(email, name, loggedin)`. Called 114 times across 11 files. Also 3 direct `session.get("email")` calls in `endpoints/conversations.py`. | `request.ext_user_email` set by decorator. Each handler reads this directly. |
| **Key management** | `keyParser(session)` in `endpoints/utils.py:18-82`: builds dict from env vars, overlays session values via `session.get(k, v)` | `keyParser_for_extension()` in `extension.py:1990-2045`: reads from env vars only (no session). **Equivalent to `keyParser({})`** |
| **Token format** | Session ID cookie (Flask-managed) | `payload_b64.signature` where payload = `{"email", "iat", "exp"}`, signature = `sha256(f"{payload_b64}.{JWT_SECRET}")` |
| **Token expiry** | Session: configurable (default 31 days). Remember-me: 30 days. | JWT: 7 days (`TOKEN_EXPIRY_HOURS = 168`) |
| **Rate limiting** | Flask-Limiter `@limiter.limit("X per minute")` on every endpoint (10-1000/min) | **No rate limiting at all** |
| **CORS** | Restrictive: only `/get_conversation_output_docs/*` for draw.io origins | `/ext/*` for `chrome-extension://*` and `http://localhost:*` |
| **User creation** | User created on first login (session populated) | `add_user_to_details(email)` called during login if user not in DB. Extension ensures user exists in `UserDetails` table. |

**Critical migration note**: The extension's `verify_user_credentials()` is more sophisticated than the main server's `check_credentials()` — it checks `password_hash` in the `UserDetails` DB table, then falls back to env `PASSWORD`. The main server only checks env `PASSWORD`. The new `POST /ext/auth/login` on the main server should use the extension's pattern (check DB hash first) to maintain backward compatibility for extension users who may have password hashes stored.

## 4c. Complete API Endpoint Mapping

Every extension endpoint (38 total) and its main server bridge/equivalent:

### Auth (3 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `POST /ext/auth/login` | None | NEW `endpoints/ext_auth.py` | M1 Task 1.3 | Uses `verify_user_credentials()` (DB hash → env fallback) |
| `POST /ext/auth/logout` | JWT | NEW `endpoints/ext_auth.py` | M1 Task 1.3 | No-op (stateless token) |
| `POST /ext/auth/verify` | JWT | NEW `endpoints/ext_auth.py` | M1 Task 1.3 | Token validity check |

### Conversations (7 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `GET /ext/conversations` | JWT | NEW `endpoints/ext_bridge.py` → `getCoversationsForUser()` | M3 Task 3.2 | Filters by workspace, translates response shape |
| `POST /ext/conversations` | JWT | NEW `endpoints/ext_bridge.py` → `_create_conversation_simple()` | M3 Task 3.2 | Adds domain/workspace params, `Conversation.__init__` needs `openai_embed` |
| `GET /ext/conversations/<id>` | JWT | NEW `endpoints/ext_bridge.py` → `conversation_cache[id]` | M3 Task 3.2 | Translates message format: `text→content`, `sender→role` |
| `PUT /ext/conversations/<id>` | JWT | NEW `endpoints/ext_bridge.py` → title/settings update | M3 Task 3.2 | Thin wrapper |
| `POST /ext/conversations/<id>/save` | JWT | NEW `endpoints/ext_bridge.py` → `conversation._stateless = False` | M3 Task 3.2 | Convert temporary to permanent |
| `DELETE /ext/conversations/<id>` | JWT | NEW `endpoints/ext_bridge.py` → `deleteConversationForUser()` | M3 Task 3.2 | Also removes from `conversation_cache` and filesystem |

### Chat (3 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `POST /ext/chat/<id>` | JWT | NEW `endpoints/ext_bridge.py` → `_execute_conversation_stream()` | M3 Task 3.3 | **Most complex**. Payload transform + streaming SSE→JSON translation. Must replicate full send_message pipeline (queue, pinned claims, auto-takeaways). |
| `POST /ext/chat/<id>/message` | JWT | NEW `endpoints/ext_bridge.py` → direct message add | M3 Task 3.2 | Add message without LLM response. No main server equivalent — new thin endpoint. |
| `DELETE /ext/chat/<id>/messages/<msg_id>` | JWT | NEW `endpoints/ext_bridge.py` → message delete | M3 Task 3.2 | Maps to existing `delete_last_message` or similar. Need to verify main server supports arbitrary message deletion. |

### Prompts (2 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `GET /ext/prompts` | JWT | NEW `endpoints/ext_prompts.py` → `/get_prompts` + allowlist filter | M4 Task 4.7 | Extension shows filtered subset via `EXTENSION_PROMPT_ALLOWLIST` |
| `GET /ext/prompts/<name>` | JWT | NEW `endpoints/ext_prompts.py` → `/get_prompt_by_name/<name>` | M4 Task 4.7 | Validates name against allowlist |

### Memories/PKB (4 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `GET /ext/memories` | JWT | NEW `endpoints/ext_memories.py` → `StructuredAPI.claims.list()` | M4 Task 4.6 | Translates response: `{"memories": [...]}` vs main PKB format |
| `POST /ext/memories/search` | JWT | NEW `endpoints/ext_memories.py` → `StructuredAPI.search()` | M4 Task 4.6 | Same PKB API, different response wrapping |
| `GET /ext/memories/<id>` | JWT | NEW `endpoints/ext_memories.py` → `StructuredAPI.claims.get()` | M4 Task 4.6 | |
| `GET /ext/memories/pinned` | JWT | NEW `endpoints/ext_memories.py` → pinned claims lookup | M4 Task 4.6 | Uses `conversation_id` param to get pinned memories |

### Workflows (5 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `GET /ext/workflows` | JWT | NEW `endpoints/ext_workflows.py` | M4 Task 4.2 | Migrated from `extension.db` to `users.db` |
| `POST /ext/workflows` | JWT | NEW `endpoints/ext_workflows.py` | M4 Task 4.2 | |
| `GET /ext/workflows/<id>` | JWT | NEW `endpoints/ext_workflows.py` | M4 Task 4.2 | |
| `PUT /ext/workflows/<id>` | JWT | NEW `endpoints/ext_workflows.py` | M4 Task 4.2 | |
| `DELETE /ext/workflows/<id>` | JWT | NEW `endpoints/ext_workflows.py` | M4 Task 4.2 | |

### Scripts (8 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `GET /ext/scripts` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | Migrated from `extension.db` to `users.db` |
| `POST /ext/scripts` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | |
| `GET /ext/scripts/<id>` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | |
| `PUT /ext/scripts/<id>` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | |
| `DELETE /ext/scripts/<id>` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | |
| `GET /ext/scripts/for-url` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | URL pattern matching |
| `POST /ext/scripts/<id>/toggle` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | Toggle enabled/disabled |
| `POST /ext/scripts/generate` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | LLM-powered generation |
| `POST /ext/scripts/validate` | JWT | NEW `endpoints/ext_scripts.py` | M4 Task 4.1 | Syntax validation |

### Settings (2 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `GET /ext/settings` | JWT | NEW `endpoints/ext_settings.py` | M4 Task 4.4 | Extension-specific settings (NOT merged with UserDetails) |
| `PUT /ext/settings` | JWT | NEW `endpoints/ext_settings.py` | M4 Task 4.4 | |

### OCR (1 endpoint)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `POST /ext/ocr` | JWT | NEW `endpoints/ext_ocr.py` | M4 Task 4.3 | Base64 images → vision model (`gemini-2.5-flash-lite` default). Concurrent ThreadPoolExecutor (8 workers). Supports pipelined single-image requests. |

### Utility (3 endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `GET /ext/models` | JWT | NEW in `endpoints/ext_bridge.py` | M4 Task 4.5 | Reuse `/model_catalog` or hardcoded list |
| `GET /ext/agents` | JWT | NEW in `endpoints/ext_bridge.py` | M4 Task 4.5 | `EXTENSION_AGENT_ALLOWLIST` |
| `GET /ext/health` | **None** | NEW in `endpoints/ext_bridge.py` | M4 Task 4.5 | No auth required |

### Coverage Summary

- **38 extension endpoints total** — all mapped
- **37 require JWT auth**, **1 requires no auth** (`/ext/health`), **1 has no auth** (`/ext/auth/login`)
- All 38 are covered by plan tasks
- **No extension endpoint is left unmapped**
- **Extension has zero rate limiting** — all bridge endpoints on main server will ADD rate limits (Task 1.6)
- **3 endpoints have no direct main server equivalent** (must be created fresh): `/ext/chat/<id>/message`, `/ext/chat/<id>/messages/<msg_id>`, `/ext/scripts/validate`

## 5. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Regression in web UI auth | High | JWT-aware `get_session_identity()` falls back to session if no Bearer token. Remember-me hook runs before identity resolution. Existing tests still pass. |
| Bridge bypasses send_message internals | High | Extract shared helper from `send_message()` that handles queue/threading, pinned claims, users_dir/loader injection, auto-takeaways. Both `/send_message` and `/ext/chat` use same helper. |
| Extension streaming format change | Medium-High | Formats are structurally different (newline JSON with `message_ids` vs SSE with `{chunk}/{done}`). Bridge translates; exact shape mapping documented in Task 3.3. |
| Auth precedence conflicts with remember-me | Medium | Define strict precedence: JWT (if Bearer header present) > session > remember-me. JWT check short-circuits before remember-me hook applies. |
| Extension conversations lose history | Medium | Migration script converts extension.db conversations to filesystem format. Field mapping documented: `role→sender`, `content→text`, IDs regenerated. |
| Conversation ID format mismatch | Medium | Main uses `{email}_{36_chars}`, extension uses `16_hex_chars`. Migration generates new main-format IDs; mapping table tracks old→new for any references. |
| Performance: Conversation.py heavier than ext_chat() | Low | Conversation.py is already optimized for streaming. Extension benefits from async PKB retrieval, prior context caching. |
| CORS issues | Low | Add `chrome-extension://*` and `http://localhost:*` for `/ext/*` routes alongside existing restrictive draw.io CORS config. |
| Two servers running during transition | Low | Keep extension_server.py running in parallel; extension JS has configurable server URL. |

## 6. Milestones and Tasks

### Timeline Summary

| Milestone | Effort | Dependencies | Key Deliverables |
|-----------|--------|--------------|------------------|
| M1: Dual Auth | 3-5 days | None | ✅ JWT auth on main server, `@auth_required` decorator |
| M2: Page Context | 2-3 days | M1 | ✅ Page context flows through Conversation.py pipeline |
| M3: Conv Bridge | 5-7 days | M1, M2 | ✅ Extension uses main server for all chat, conversation bridge endpoints |
| M4: Ext Features | 3-5 days | M1 | ✅ Scripts, workflows, OCR, memories, prompts migrated to main server |
| M5: Client UI | 4-6 days | M3, M4 | ✅ jsTree sidebar, KaTeX math, dual buttons, popup settings domain/workspace |
| M6: File Attachments + UI Panels | 3-4 days | M1, M3, M5 | ✅ FastDocIndex upload fix, docs panel, claims panel, full context menu, attachment context menu |
| M7: Cleanup | 1 day | M5, M6 | ✅ Deprecation notice, delete obsolete docs/tests, update all referencing docs |
| **Total** | **21-30 days** | — | **✅ Single unified backend — all milestones complete** |

**Timeline evolution**: v1.0: 15-20 days → v2.1: 18-26 days → v2.2: 18-26 days → v2.3: 22-32 days → **v2.4: 21-30 days** (simplified frontend, refined estimates, realistic auth timeline)

---

### Milestone 1: Dual Auth (JWT + Session) on Main Server

**Goal**: Extension can authenticate against the main server via JWT tokens. All existing endpoints work for JWT-authenticated requests through a JWT-aware `get_session_identity()` without mass decorator replacement.

**Effort**: 2-3 days

**Why first**: Every subsequent milestone depends on the extension being able to call main server endpoints.

**Key insight**: Instead of replacing `@login_required` on 128+ routes, we update `get_session_identity()` (114 call sites across 11 files) to check JWT first, then session. This single-file change makes all existing endpoint code JWT-compatible automatically.

#### Task 1.1: Move ExtensionAuth to a shared module

**What**: Extract `ExtensionAuth` class from `extension.py` into a new `endpoints/jwt_auth.py` module usable by the main server.

**Files to create**:
- `endpoints/jwt_auth.py` — Contains `ExtensionAuth` (token generation/verification), `JWT_SECRET` config, `TOKEN_EXPIRY_HOURS` config, `get_email_from_jwt()` helper.

**Files to modify**:
- None yet (just creating the new module).

**Details**:
- Copy `ExtensionAuth` class (lines 98–252 of `extension.py`) into `endpoints/jwt_auth.py`.
- Keep the same HMAC-SHA256 token format (`payload_b64.signature`).
- Read `JWT_SECRET` from env var `EXTENSION_JWT_SECRET`, fall back to `secrets.token_hex(32)`.
- Keep `TOKEN_EXPIRY_HOURS = 24 * 7` (7 days).
- Add a `get_email_from_jwt(request) -> Optional[str]` helper that checks the `Authorization: Bearer` header and returns the email if valid, `None` otherwise.

**Acceptance criteria**:
- `from endpoints.jwt_auth import ExtensionAuth, get_email_from_jwt` works.
- `ExtensionAuth.generate_token("test@test.com")` returns a valid token.
- `get_email_from_jwt(mock_request_with_bearer)` returns the email.
- `get_email_from_jwt(mock_request_without_bearer)` returns `None`.

#### Task 1.2: Make `get_session_identity()` JWT-aware

**What**: Update the single identity-resolution function so all 114 call sites across 11 endpoint files automatically work for JWT-authenticated requests.

**Files to modify**:
- `endpoints/session_utils.py` — Update `get_session_identity()` to check JWT first, then session.

**Details**:
- Current implementation (lines 18-32):
  ```python
  def get_session_identity():
      email = dict(session).get("email", None)
      name = dict(session).get("name", None)
      return email, name, email is not None and name is not None
  ```
- New implementation:
  ```python
  def get_session_identity():
      # 1. Check JWT (Authorization: Bearer <token>)
      from endpoints.jwt_auth import get_email_from_jwt
      jwt_email = get_email_from_jwt(request)
      if jwt_email:
          return jwt_email, jwt_email, True
      # 2. Fall back to Flask session (including remember-me restored sessions)
      email = dict(session).get("email", None)
      name = dict(session).get("name", None)
      return email, name, email is not None and name is not None
  ```
- **Auth precedence**: JWT (if `Authorization: Bearer` present) > session > remember-me (which populates session via `check_remember_token` hook in `endpoints/auth.py:180-200`). JWT check runs first and short-circuits.
- Also add `is_jwt_request() -> bool` helper to let code detect auth source when needed.

**Why this approach is superior**:
- Fixes all 114 call sites automatically without touching them
- No risk of forgetting to update an endpoint
- Remember-me token flow is unaffected (it populates session; JWT check runs first)
- Minimal code change, maximum coverage

**Files with `get_session_identity()` calls (for reference, NO changes needed)**:
- `endpoints/pkb.py` — 38 calls
- `endpoints/conversations.py` — 30 calls
- `endpoints/workspaces.py` — 8 calls
- `endpoints/doubts.py` — 5 calls
- `endpoints/users.py` — 4 calls
- `endpoints/artefacts.py` — 1 call
- `endpoints/audio.py` — 1 call
- `endpoints/sections.py` — 1 call
- `endpoints/static_routes.py` — 1 call

**Acceptance criteria**:
- `get_session_identity()` returns `(email, email, True)` for valid JWT request.
- `get_session_identity()` returns `(email, name, True)` for valid session request (unchanged).
- `get_session_identity()` returns `(None, None, False)` for unauthenticated request (unchanged).
- All existing web UI flows unaffected (session + remember-me work as before).

#### Task 1.2b: Create `@auth_required` decorator and key resolution helpers

**What**: A new decorator for `/ext/*` endpoints that returns JSON 401 (not redirect) on auth failure. Plus a key resolution helper that uses `keyParser({})` for JWT requests.

**Files to modify**:
- `endpoints/auth.py` — Add `auth_required` decorator.
- `endpoints/request_context.py` — Add `get_request_keys()` helper.

**Details**:
- `@auth_required` decorator:
  ```python
  def auth_required(f):
      @wraps(f)
      def decorated(*args, **kwargs):
          email, name, loggedin = get_session_identity()
          if not loggedin:
              return jsonify({"error": "Authentication required"}), 401
          return f(*args, **kwargs)
      return decorated
  ```
  - Returns JSON 401 (not redirect) — appropriate for API endpoints.
  - `get_session_identity()` already handles both JWT and session (from Task 1.2).
  - Used on new `/ext/*` endpoints. Existing endpoints keep `@login_required` (redirect behavior for web UI).
- `get_request_keys()` helper in `endpoints/request_context.py`:
  ```python
  def get_request_keys():
      from endpoints.session_utils import is_jwt_request
      if is_jwt_request():
          return keyParser({})  # env-var-only — no session overlay
      return keyParser(session)  # session overlay — web UI behavior
  ```
- **Why not `keyParser_from_env()`**: Investigation found `keyParser(session)` iterates keys doing `session.get(k, v)`. An empty dict has no keys to overlay, so `keyParser({})` returns pure env-var values identically. No duplicate function needed.

**Acceptance criteria**:
- `@auth_required` returns JSON 401 for unauthenticated API requests.
- `@auth_required` passes for valid JWT Bearer token.
- `@auth_required` passes for valid Flask session.
- `get_request_keys()` returns env-only keys for JWT requests, session-overlaid keys for web UI.

#### Task 1.3: Add JWT login/verify/logout endpoints to main server

**What**: Add `/ext/auth/login`, `/ext/auth/verify`, `/ext/auth/logout` to the main server so the extension's existing login flow works against port 5000.

**Files to create**:
- `endpoints/ext_auth.py` — Blueprint with `/ext/auth/*` routes.

**Details**:
- `POST /ext/auth/login`: Accept `{"email": "...", "password": "..."}`. Verify credentials using the extension's more sophisticated pattern: check `password_hash` in `UserDetails` DB table first (SHA256), then fall back to `os.getenv("PASSWORD", "XXXX")`. This matches `verify_user_credentials()` from `extension_server.py:584-619`, which is more robust than the main server's `check_credentials()` (which only checks env var). If valid, generate JWT via `ExtensionAuth.generate_token(email)`. Ensure user exists in `UserDetails` table (`add_user_to_details()` if missing). Return `{"token": "...", "email": "...", "name": "..."}`.
- `POST /ext/auth/verify`: Check `Authorization: Bearer` header. Return `{"valid": true, "email": "..."}` or `{"valid": false, "error": "..."}`.
- `POST /ext/auth/logout`: No-op (stateless tokens). Return `{"message": "Logged out successfully"}`.
- Register this blueprint in `server.py`.

**Files to modify**:
- `server.py` — Register `ext_auth_bp` blueprint.

**Acceptance criteria**:
- Extension can POST to `http://localhost:5000/ext/auth/login` with credentials and receive a JWT token.
- Extension can POST to `http://localhost:5000/ext/auth/verify` with the token and get `{"valid": true}`.
- No change to existing `/login` session-based flow.

#### Task 1.4: Update CORS to allow extension origins

**What**: Add extension-compatible CORS alongside the existing restrictive draw.io CORS config.

**Files to modify**:
- `server.py` — Update CORS configuration.

**Details**:
- Current CORS (`server.py:182-194`) is very restrictive — only `/get_conversation_output_docs/*` for draw.io origins.
- Add extension CORS rules alongside existing config:
  ```python
  CORS(app, resources={
      r"/ext/*": {
          "origins": ["chrome-extension://*", "http://localhost:*"],
          "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
          "allow_headers": ["Content-Type", "Authorization"]
      },
      r"/get_conversation_output_docs/*": {
          "origins": ["https://laingsimon.github.io", "https://app.diagrams.net/",
                      "https://draw.io/", "https://www.draw.io/"]
      },
  })
  ```
- Note: JWT auth doesn't need cookies, so `supports_credentials` is NOT needed for `/ext/*`.
- Do NOT use overly broad origins like `"https://*"`.

**Acceptance criteria**:
- Extension can make requests to `/ext/*` without CORS errors.
- Existing draw.io CORS behavior unchanged.

#### Task 1.5: Selective `@auth_required` on endpoints extension needs

**What**: Add `@auth_required` to the specific existing endpoints the extension will call directly (not through bridge). This is a targeted change, NOT a blanket replacement.

**Files to modify (targeted endpoints only)**:
- `endpoints/conversations.py` — `/send_message/<id>`, `/create_conversation`, `/list_conversation_by_user`, `/get_conversation_details`, plus conversation CRUD routes the extension will call
- `endpoints/pkb.py` — PKB search/list routes the extension's memory bridge will call internally (optional if bridge handles auth itself)

**Details**:
- For each targeted route, add `@auth_required` alongside or replacing `@login_required`:
  - Routes that ONLY serve API responses (JSON) → replace with `@auth_required`
  - Routes that serve HTML (like `/interface`) → keep `@login_required`
- The extension bridge endpoints (`/ext/*`) will use `@auth_required` (from Task 1.2b).
- Most existing endpoints do NOT need changes because the extension will access them through bridge endpoints, not directly.
- Key routes to update: `/send_message/<id>` (needed for direct chat), `/create_conversation/<domain>/<workspace_id>`, `/list_conversation_by_user/<domain>`, `/get_conversation_details/<id>`, `/upload_doc_to_conversation/<id>` (future Phase 2)
- Update `get_state_and_keys()` in `endpoints/request_context.py` to use `get_request_keys()`:
  ```python
  def get_state_and_keys():
      return get_state(), get_request_keys()
  ```

**Critical detail**: All routes using `get_session_identity()` already work for JWT thanks to Task 1.2. This task only changes the decorator on routes that need JSON 401 (not redirect) for auth failures.

**Acceptance criteria**:
- Extension with JWT can call `/send_message/<id>` and receive streaming response.
- Extension with JWT can CRUD conversations.
- Web UI with session cookies continues to work on all routes.
- HTML routes still redirect to `/login` if no session.

**Challenges and alternatives**:
- Some endpoints use `session.get("email")` directly (3 occurrences in `endpoints/conversations.py` lines 122, 798, 912) instead of `get_session_identity()`. These need individual fixes to use `get_session_identity()` or `get_auth_email()` instead.
- The `getUserFromUserDetailsTable(email)` pattern should use `get_session_identity()[0]` as the email source, which is already JWT-aware after Task 1.2.

#### Task 1.6: Rate limiting for extension endpoints

**What**: Apply appropriate Flask-Limiter rates to new `/ext/*` routes.

**Files to modify**:
- All new `endpoints/ext_*.py` files — Add `@limiter.limit()` decorators.

**Details**:
- Extension server currently uses 100-500 requests/minute rates.
- Bridge endpoints (chat, conversations) should match main server rates for equivalent operations.
- Recommended rates:
  - `/ext/auth/*` — 100 per minute (matches main server auth)
  - `/ext/chat/<id>` — 50 per minute (matches `/send_message`)
  - `/ext/conversations/*` — 500 per minute (matches list operations)
  - `/ext/scripts/*`, `/ext/workflows/*` — 100 per minute
  - `/ext/memories/*`, `/ext/prompts/*` — 100 per minute
  - `/ext/settings/*` — 100 per minute
  - `/ext/ocr` — 30 per minute (expensive vision calls)
  - `/ext/health` — 1000 per minute (no auth, lightweight)

**Acceptance criteria**:
- All `/ext/*` endpoints have rate limits.
- Rate limits are consistent with extension usage patterns.

---

### Milestone 2: Page Context and Image Support in Conversation.py

**Goal**: The main server's `/send_message/<conversation_id>` endpoint accepts optional `page_context` and `images` in the request payload. `Conversation.py`'s `reply()` method injects these as grounding context for the LLM, matching the quality of `extension_server.py`'s page-context and multimodal handling.

**Effort**: 2-3 days

**Why**: This is the core feature that lets the extension use the main chat pipeline instead of its own simplified `ext_chat()`.

#### Task 2.1: Add `page_context` to send_message payload processing

**What**: The `/send_message/<conversation_id>` endpoint accepts an optional `page_context` field in the JSON body and passes it through to `Conversation.__call__()` via the query dict.

**Files to modify**:
- `endpoints/conversations.py` — In `send_message()`, extract `page_context` from `request.json` and inject into `query`.

**Details**:
- After `query = request.json` (line 1354), add:
  ```python
  # Page context for extension (browser page content, screenshots, multi-tab)
  # Passed through to Conversation.reply() for LLM grounding.
  if "page_context" in query and query["page_context"]:
      # Validated and used by Conversation.reply()
      pass  # Already in query dict, reply() will handle it
  ```
- The `page_context` object shape (matching extension_server.py):
  ```json
  {
      "url": "https://...",
      "title": "Page Title",
      "content": "extracted text...",
      "screenshot": "data:image/png;base64,...",
      "isScreenshot": false,
      "isMultiTab": false,
      "tabCount": 1,
      "sources": [...],
      "mergeType": "replace",
      "lastRefreshed": "ISO timestamp"
  }
  ```

**Acceptance criteria**:
- `send_message` accepts `page_context` in payload without errors.
- The field is available in `query` when `Conversation.__call__` is invoked.

#### Task 2.2: Inject page context into Conversation.reply() prompt

**What**: `Conversation.reply()` reads `page_context` from the query dict and injects it as grounding messages in the LLM prompt, similar to how `extension_server.py:ext_chat()` does it.

**Files to modify**:
- `Conversation.py` — In `reply()` method, after prior context retrieval (around line 5288, after `prior_context = prior_context_future.result()`) and before prompt construction.

**Details**:
- Extract page_context from query:
  ```python
  page_context = query.get("page_context", None) if isinstance(query, dict) else None
  ```
- Build a `page_context_text` string that will be injected into `permanent_instructions` or as a separate context section in the prompt.
- Three cases to handle (matching extension_server.py logic):
  1. **Screenshot (canvas apps)**: If `page_context.get("isScreenshot")` and `page_context.get("screenshot")` — this requires multimodal message handling. For now, describe the screenshot in text or skip if model doesn't support vision. A later enhancement can add full vision support.
  2. **Multi-tab content**: If `page_context.get("isMultiTab")` — format all tab contents with separators.
  3. **Single page text**: Default case — format URL, title, content.
- Content size limits: 64K chars for single page, 128K for multi-tab (matching extension_server.py).
- Truncate with `[Content truncated...]` marker if exceeded.
- Inject the page context text into the `permanent_instructions` variable that gets included in the chat prompt. The format:
  ```
  [Browser Page Context]
  URL: {url}
  Title: {title}

  Page Content:
  {content}

  Use the above page content to ground your response.
  [End Browser Page Context]
  ```
- For multi-tab:
  ```
  [Browser Page Context - {tabCount} tabs]
  {combined content with tab separators}
  [End Browser Page Context]
  ```

**Acceptance criteria**:
- When `page_context` is provided, the LLM receives the page content as context.
- When `page_context` is `None` or empty, behavior is unchanged.
- Content is properly truncated for large pages.
- Streaming still works correctly with page context.

#### Task 2.3: Support extension-specific checkboxes defaults

**What**: When the request comes from the extension (detectable via `is_jwt_request()` or a `source: "extension"` field in the query), apply sensible default checkboxes that match extension behavior.

**Files to modify**:
- `endpoints/conversations.py` — In `send_message()`, detect extension source and set checkbox defaults.

**Details**:
- The extension sends a simplified payload compared to the web UI. Many checkboxes fields may be missing.
- Add default checkbox population for extension requests:
  ```python
  from endpoints.session_utils import is_jwt_request
  if query.get("source") == "extension" or is_jwt_request():
      checkboxes = query.setdefault("checkboxes", {})
      checkboxes.setdefault("persist_or_not", True)
      checkboxes.setdefault("provide_detailed_answers", 2)
      checkboxes.setdefault("use_pkb", True)
      checkboxes.setdefault("enable_previous_messages", "10")
      checkboxes.setdefault("perform_web_search", False)
      checkboxes.setdefault("googleScholar", False)
      checkboxes.setdefault("ppt_answer", False)
      checkboxes.setdefault("preamble_options", [])
      # Set search/links defaults
      query.setdefault("search", [])
      query.setdefault("links", [])
  ```

**Acceptance criteria**:
- Extension requests with minimal payload work without KeyError.
- Default settings produce reasonable behavior (PKB enabled, reasonable history length).

#### Task 2.4: Support extension images in chat payload

**What**: Ensure the `images` array from extension chat payloads (up to 5 base64 data URLs) passes through to Conversation.py's multimodal message handling.

**Files to modify**:
- `endpoints/conversations.py` — In `send_message()`, ensure `images` field from query is preserved.
- `Conversation.py` — Verify multimodal image handling in `reply()` method.

**Details**:
- Extension sends `"images": ["data:image/png;base64,...", ...]` in the chat payload (max 5).
- Verify that `Conversation.py`'s `reply()` method can handle these base64 data URLs as multimodal content in messages.
- If Conversation.py already supports images in the query dict, this may require no changes — just verification.
- If not, add image injection similar to how `ext_chat()` does it (`extension_server.py:1649-1662`): append as multimodal message parts with `{"type": "image_url", "image_url": {"url": img}}`.

**Acceptance criteria**:
- Extension can send images in chat payload and they are processed by the LLM.
- Max 5 images enforced.
- Models without vision support gracefully handle or ignore images.

---

### Milestone 3: Extension Conversation Storage Migration

**Goal**: Extension conversations use the main filesystem-based conversation system instead of `extension.db`. This eliminates `ExtensionDB` conversation/message tables.

**Effort**: 5-7 days

**Storage model difference**:
- Main: Filesystem folders (`storage/conversations/{id}/`) with JSON files per field
- Extension: SQLite tables (`ExtensionConversations`, `ExtensionMessages`)
- Main message fields: `message_id`, `text`, `sender` (user/model), `user_id`, `conversation_id`, `message_short_hash`
- Extension message fields: `message_id`, `conversation_id`, `role` (user/assistant), `content`, `page_context` (JSON), `created_at`
- Main conversation ID: `{email}_{36_random_alphanum}` — Extension: `secrets.token_hex(16)`

#### Task 3.1: Extension workspace and domain integration

**What**: When the extension creates a conversation, the user can choose which domain and which workspace in the hierarchy to place it in. A default "Browser Extension" workspace is auto-created per domain, but users can also select any existing workspace.

**Files to modify**:
- `endpoints/ext_bridge.py` (NEW) — Extension-specific bridge endpoints.

**Details**:
- Create `endpoints/ext_bridge.py` as a new blueprint (`ext_bridge_bp`).
- **Domain support**: The extension must support all 3 domains: `assistant`, `search`, `finchat`.
  - Domain is stored as an extension setting (default: `assistant`).
  - When the domain changes, the sidebar must reload to show that domain's workspace hierarchy and conversations.
  - All conversation CRUD and workspace listing operations pass the active domain.
- **Workspace listing endpoint**: `GET /ext/workspaces/<domain>` — returns workspace hierarchy for a domain.
  - Delegates to `load_workspaces_for_user(users_dir=..., user_email=..., domain=domain)`.
  - Returns array of `{workspace_id, workspace_name, workspace_color, domain, expanded, parent_workspace_id}`.
  - Auto-creates default workspace if missing (existing behavior in `load_workspaces_for_user()`).
- **Auto-provisioned "Browser Extension" workspace**: `get_or_create_extension_workspace(email, domain)` helper:
  1. Queries `WorkspaceMetadata` for a workspace named "Browser Extension" for this user in the given domain.
  2. If not found, creates it using the same DB helpers as `POST /create_workspace/<domain>/<name>` in `endpoints/workspaces.py`:
     - Insert into `WorkspaceMetadata`: workspace_id (generated), workspace_name="Browser Extension", workspace_color="#6f42c1" (purple), domain=domain, parent_workspace_id=NULL.
  3. Returns the `workspace_id`.
  4. Called during first conversation creation if no workspace is explicitly chosen.
- **Conversation creation with workspace selection**: `POST /ext/conversations` accepts optional `workspace_id` and `domain` parameters.
  - If `workspace_id` is provided, creates conversation in that workspace.
  - If no `workspace_id`, creates in the "Browser Extension" workspace (auto-provisioned).
  - If no `domain`, defaults to the extension's active domain setting (from ext_settings).
- **Workspace CRUD for extension**: The extension needs read access to workspaces plus ability to create sub-workspaces. Expose via bridge or reuse existing workspace endpoints (which will be JWT-accessible after Milestone 1):
  - `GET /ext/workspaces/<domain>` — list workspaces (bridge to `load_workspaces_for_user`)
  - `POST /ext/workspaces/<domain>` — create workspace (bridge to `createWorkspace`)
  - `GET /ext/workspace_path/<workspace_id>` — get breadcrumb path (bridge to `getWorkspacePath`)
  - `PUT /ext/move_conversation_to_workspace/<conversation_id>` — move conversation (reuse existing endpoint)

**Database context** (`database/connection.py:96-114`):
- `ConversationIdToWorkspaceId`: conversation_id (PK), user_email, workspace_id, created_at, updated_at
- `WorkspaceMetadata`: workspace_id (PK), workspace_name, workspace_color, domain, expanded (bool), parent_workspace_id, created_at, updated_at

**Acceptance criteria**:
- Extension can list workspaces for any domain.
- First extension conversation request creates the "Browser Extension" workspace if needed.
- User can choose workspace during conversation creation.
- Workspace hierarchy appears correctly in extension sidebar (after Milestone 5).
- Workspaces appear in the main web UI sidebar under the correct domain.

#### Task 3.2: Add extension conversation CRUD bridge endpoints

**What**: Create `/ext/conversations` endpoints that delegate to the main conversation system but provide the simplified interface the extension expects.

**Files to create/modify**:
- `endpoints/ext_bridge.py` — Contains all `/ext/conversations/*` bridge routes.

**Details**:
- `GET /ext/conversations` — List conversations in the "Browser Extension" workspace:
  - Calls `getCoversationsForUser(email, "assistant")` and filters by workspace_id.
  - Returns simplified format: `{"conversations": [...], "total": N}` matching extension's expected shape.
- `POST /ext/conversations` — Create a conversation in the "Browser Extension" workspace:
  - Calls `_create_conversation_simple("assistant", workspace_id)` (from `endpoints/conversations.py:1096`).
  - `Conversation.__init__(user_id, openai_embed, storage, conversation_id, domain)` requires an embedding model via `get_embedding_model(keys)`.
  - If `is_temporary=True`, set `conversation.make_stateless()`.
  - Returns `{"conversation_id": "...", "title": "New Chat", ...}`.
- `GET /ext/conversations/<id>` — Get conversation details + messages:
  - Loads conversation from `state.conversation_cache[id]`.
  - Returns `{"messages": [...], "metadata": {...}}` translated to extension format.
  - Message format translation: `text→content`, `sender→role` (user→user, model→assistant).
- `PUT /ext/conversations/<id>` — Update title, stateless flag. Thin wrapper.
- `DELETE /ext/conversations/<id>` — Delete conversation:
  - Calls `deleteConversationForUser()` + `conversation.delete_conversation()` + removes from cache.
- `POST /ext/conversations/<id>/save` — Make non-temporary (set stateful):
  - `conversation._stateless = False` + `conversation.save_local()`.
- `POST /ext/chat/<id>/message` — Add a message without LLM response:
  - Useful for adding system messages or imported content.
  - Accept `{"role": "user|assistant", "content": "...", "page_context": {...}}`.
  - Adds message directly to conversation's message list. No main server equivalent exists — new thin endpoint.
- `DELETE /ext/chat/<id>/messages/<msg_id>` — Delete a specific message:
  - Maps to existing message deletion in Conversation. Verify main server supports arbitrary message deletion (not just last message via `/delete_last_message/<id>`).
- All routes use `@auth_required` decorator.
- The response shapes match what `extension/shared/api.js` expects, so extension JS needs minimal changes.

**Note on conversation cache**: Main server uses `DefaultDictQueue` (LRU, maxsize=200) with `load_conversation` factory. New conversations are added via `state.conversation_cache[id] = conversation`. Cache auto-loads from filesystem on miss.

**Acceptance criteria**:
- Extension can CRUD conversations via `/ext/conversations/*` on the main server.
- Conversations appear in the web UI under "Browser Extension" workspace.
- Web UI can see and interact with extension conversations.
- Deleting from either UI works correctly.

#### Task 3.3: Add extension chat bridge endpoint

**What**: Create `/ext/chat/<conversation_id>` that delegates to the same internal machinery as `/send_message/<conversation_id>` but transforms the payload and response format to match what the extension JS expects.

**Files to modify**:
- `endpoints/ext_bridge.py` — Add `/ext/chat/<id>` route.
- `endpoints/conversations.py` — Extract reusable helper from `send_message()`.

**Design**: Extract the core logic of `send_message()` into a shared helper. Both `/send_message/<id>` and `/ext/chat/<id>` call this helper. The bridge only does: (a) payload transform, (b) call shared helper, (c) streaming format translation.

**Step 1: Extract shared helper from send_message()**:
- Create `_execute_conversation_stream(conversation_id, query, email, keys, user_details, state)` that encapsulates:
  - Conversation existence check
  - Conversation loading from cache with keys
  - Pinned claims injection from `state.pinned_claims`
  - `_users_dir` and `_conversation_loader` injection into query
  - Queue + threading mechanism (`Queue()`, `get_async_future(generate_response)`, `run_queue()`)
  - Auto-takeaways scheduling post-stream
  - Returns a generator yielding chunks
- Update `send_message()` to call this helper instead of inline code.

**Step 2: Bridge endpoint `/ext/chat/<conversation_id>`**:
- `POST /ext/chat/<conversation_id>`:
  - Accept extension payload: `{"message": "...", "page_context": {...}, "model": "...", "agent": "...", "stream": true, "images": [...]}`
  - Transform to main server query format:
    ```python
    main_query = {
        "messageText": data["message"],
        "checkboxes": {
            "main_model": data.get("model", "openai/gpt-4o-mini"),
            "field": data.get("agent"),
            "provide_detailed_answers": data.get("detail_level", 2),
            "persist_or_not": True,
            "use_pkb": True,
        },
        "search": [],
        "links": [],
        "page_context": data.get("page_context"),
        "images": data.get("images", []),
        "source": "extension",
    }
    ```
  - Get keys via `get_request_keys()`, email via `get_session_identity()`, user_details via `getUserFromUserDetailsTable()`
  - Call `_execute_conversation_stream(conversation_id, main_query, email, keys, user_details, state)` — same core as send_message
  - **Streaming format translation**: Convert main server's newline-delimited JSON to SSE:
    ```python
    def translate_stream(generator):
        for chunk in generator:
            parsed = json.loads(chunk.strip()) if isinstance(chunk, str) else chunk
            text = parsed.get("text", "")
            if text:
                yield f"data: {json.dumps({'chunk': text})}\n\n"
            # Detect completion
            status = str(parsed.get("status", "")).lower()
            if "saving answer" in status:
                msg_ids = parsed.get("message_ids", {})
                yield f"data: {json.dumps({'done': True, 'message_id': msg_ids.get('response_message_id', '')})}\n\n"
    ```
  - Return `Response(translate_stream(...), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})`

**Streaming format mapping**:

| Main Server Chunk | Extension SSE |
|---|---|
| `{"text": "Hi", "status": "Generating..."}\n` | `data: {"chunk": "Hi"}\n\n` |
| `{"text": "", "status": "saving answer..."}\n` | `data: {"done": true, "message_id": "..."}\n\n` |
| `{"text": "", "status": "error: ..."}\n` | `data: {"error": "..."}\n\n` |

**Alternative (simpler, Phase 2)**: Have the extension JS adapt to parse newline-delimited JSON directly. The extension's `API.stream()` method (in `shared/api.js`) would parse `{"text": "...", "status": "..."}\n` lines instead of SSE.

**Recommended approach**: Use the bridge with SSE translation initially (zero extension JS changes), then update extension JS in Phase 2 to call `/send_message/<id>` directly with newline-delimited JSON parsing, eliminating the bridge layer.

**Acceptance criteria**:
- Extension can send chat messages via `/ext/chat/<id>` on the main server.
- Streaming responses are delivered in SSE format the extension can parse.
- Full Conversation.py pipeline is used (PKB distillation, agents, math formatting, running summaries, etc.).
- Page context and images are properly injected.
- Pinned claims, auto-takeaways, and conversation loader injection all work.

#### Task 3.4: Data migration script for existing extension conversations

**What**: A one-time migration script that converts existing `extension.db` conversations into main-system filesystem conversations under the "Browser Extension" workspace.

**Files to create**:
- `scripts/migrate_extension_conversations.py`

**Details**:
- Read all conversations and messages from `extension.db` (`ExtensionConversations`, `ExtensionMessages` tables).
- For each non-temporary conversation:
  1. Generate main-format conversation_id: `{user_email}_{36_random_chars}`.
  2. Create filesystem folder: `storage/conversations/{conversation_id}/`.
  3. Convert messages with field mapping:
     - `role` → `sender`: "user" → "user", "assistant" → "model"
     - `content` → `text`
     - Add `user_id` = user_email, `conversation_id` = new ID
     - Generate `message_short_hash` for cross-conversation references
     - Preserve ordering by `created_at`
  4. Write `{conversation_id}-messages.json` with converted messages.
  5. Write `memory.json`: `{"title": ext_title, "last_updated": ext_updated_at, "running_summary": [ext_summary] if ext_summary else [], "title_force_set": true}`.
  6. Write empty `uploaded_documents_list.json`, `artefacts.json`, `artefact_message_links.json`, `conversation_settings.json`.
  7. Register in DB: `addConversation(email, conversation_id, ext_workspace_id, "assistant")`.
  8. Track mapping: old_ext_id → new_main_id for reference.
- Skip temporary (`is_temporary=True`) conversations.
- Log progress and any failures.
- Can be run multiple times safely (skip already-migrated IDs via mapping file).

**Acceptance criteria**:
- All non-temporary extension conversations appear in the web UI under "Browser Extension" workspace.
- Message content, ordering, and roles are preserved.
- Script is idempotent.
- Migrated conversations can be opened and chatted in via both web UI and extension.

---

### Milestone 4: Port Extension-Specific Features

**Goal**: Extension-only features (scripts, workflows, OCR, settings, agents list, models list) are available as endpoints on the main server.

**Effort**: 4-6 days

#### Task 4.1: Port custom scripts CRUD

**What**: Move script storage from `extension.db:CustomScripts` to a new table in `users.db` (or a new `extension_features.db`), and create endpoints.

**Files to create**:
- `endpoints/ext_scripts.py` — Blueprint with `/ext/scripts/*` routes.
- `database/ext_scripts.py` — DB helper for custom scripts table.

**Details**:
- Create `CustomScripts` table in `users.db` (matching existing schema from extension.py lines 346–375).
- Port all script endpoints from `extension_server.py`:
  - `GET /ext/scripts` — List scripts (with filters: enabled_only, script_type, limit, offset)
  - `POST /ext/scripts` — Create script
  - `GET /ext/scripts/<id>` — Get script
  - `PUT /ext/scripts/<id>` — Update script
  - `DELETE /ext/scripts/<id>` — Delete script
  - `GET /ext/scripts/for-url` — Get scripts matching a URL pattern
  - `POST /ext/scripts/<id>/toggle` — Toggle enabled
  - `POST /ext/scripts/generate` — LLM-powered script generation
  - `POST /ext/scripts/validate` — Basic syntax validation
- All routes use `@auth_required`.
- Register blueprint in `server.py`.

**Acceptance criteria**:
- Extension can manage scripts via main server.
- Scripts are persisted in `users.db`.
- LLM script generation works.

#### Task 4.2: Port workflows CRUD

**What**: Move workflow storage and create endpoints on the main server.

**Files to create**:
- `endpoints/ext_workflows.py` — Blueprint with `/ext/workflows/*` routes.
- `database/ext_workflows.py` — DB helper for workflows table.

**Details**:
- Create `ExtensionWorkflows` table in `users.db` (matching extension.py lines 407–417).
- Port workflow endpoints:
  - `GET /ext/workflows` — List workflows
  - `POST /ext/workflows` — Create workflow
  - `GET /ext/workflows/<id>` — Get workflow
  - `PUT /ext/workflows/<id>` — Update workflow
  - `DELETE /ext/workflows/<id>` — Delete workflow
- All routes use `@auth_required`.

**Acceptance criteria**:
- Extension can manage workflows via main server.
- `PromptWorkflowAgent` integration works from the main chat pipeline.

#### Task 4.3: Port OCR/Vision endpoint

**What**: Create `/ext/ocr` on the main server for screenshot-to-text conversion.

**Files to create**:
- `endpoints/ext_ocr.py` — Blueprint with `/ext/ocr` route.

**Details**:
- Port the OCR endpoint from `extension_server.py` (lines ~2100–2300).
- Uses `call_llm()` with vision model (default: `google/gemini-2.5-flash-lite`, configurable via `EXT_OCR_MODEL` env var). Model was changed from `openai/gpt-4o` to `gemini-2.5-flash-lite` for lower latency/cost on clean typed text (web screenshots).
- Supports multiple images with concurrent processing via ThreadPoolExecutor (max workers: 8, configurable via `EXT_OCR_MAX_WORKERS`).
- **Pipelined OCR pattern**: The extension sidepanel now fires single-image OCR requests per screenshot during capture (not batched). The endpoint already handles single-image requests efficiently via the same ThreadPoolExecutor path — no endpoint changes needed.
- All routes use `@auth_required`.

**Acceptance criteria**:
- Extension can OCR screenshots via main server.
- Multi-image concurrent processing works.

#### Task 4.4: Port extension settings endpoints

**What**: Create `/ext/settings` on the main server. These are extension-specific UI preferences (default model, prompt, history length, auto-save), NOT the same as main server's `UserDetails.user_preferences`. They are complementary and should NOT be merged.

**Files to create**:
- `endpoints/ext_settings.py` — Blueprint with settings routes.

**Details**:
- Create `ExtensionSettings` table in `users.db` (matching `extension.py` lines 419–430):
  ```sql
  CREATE TABLE IF NOT EXISTS ExtensionSettings (
      user_email TEXT PRIMARY KEY,
      default_model TEXT DEFAULT 'gpt-4',
      default_prompt TEXT,
      history_length INTEGER DEFAULT 10,
      auto_save INTEGER DEFAULT 0,
      settings_json TEXT,
      updated_at TEXT DEFAULT CURRENT_TIMESTAMP
  )
  ```
- `GET /ext/settings` — Get user's extension settings (merged with settings_json).
- `PUT /ext/settings` — Update settings fields.
- All routes use `@auth_required`.
- **Do NOT merge with UserDetails**: Main server's `user_preferences` (JSON) and `user_memory` (JSON) serve different purposes than extension settings. Extension settings should not silently mutate web UI preferences or vice versa.

**Acceptance criteria**:
- Extension settings persist on the main server in `users.db`.
- Settings are scoped per-user and independent of main server user preferences.

#### Task 4.5: Port utility endpoints (models, agents, health)

**What**: Create `/ext/models`, `/ext/agents`, `/ext/health` on the main server.

**Files to modify**:
- `endpoints/ext_bridge.py` — Add these utility routes.

**Details**:
- `GET /ext/models` — Return available models list. Can reuse `/model_catalog` logic from main server if it exists, or return the hardcoded list from extension_server.py.
- `GET /ext/agents` — Return agent allowlist (same as `EXTENSION_AGENT_ALLOWLIST` from extension_server.py).
- `GET /ext/health` — Health check endpoint (no auth required).

**Acceptance criteria**:
- Extension can fetch model list, agent list, and health status from main server.

#### Task 4.6: Port memory/PKB bridge endpoints

**What**: Create `/ext/memories/*` endpoints that bridge to the main PKB system with response shape translation.

**Files to create**:
- `endpoints/ext_memories.py` — Blueprint with `/ext/memories/*` routes.

**Details**:
- Extension currently has these memory endpoints in `extension_server.py`:
  - `GET /ext/memories` — List PKB claims (params: limit, offset, status, claim_type)
  - `POST /ext/memories/search` — Search PKB claims (body: query, k, strategy)
  - `GET /ext/memories/<claim_id>` — Get single claim
  - `GET /ext/memories/pinned` — Get pinned memories for conversation
- These are thin wrappers around `StructuredAPI` from the PKB system — the same API the main server's `/pkb/*` endpoints use.
- **Bridge approach**: Each `/ext/memories/*` endpoint calls the corresponding PKB internal API and translates the response to the shape the extension expects:
  - Extension expects: `{"memories": [{"id": "...", "statement": "...", ...}], "total": N}`
  - Main PKB returns different shapes per endpoint
- Use `get_pkb_api_for_user(email, keys)` to get the StructuredAPI instance (same pattern as `extension_server.py:1037-1059`).
- All routes use `@auth_required`.

**Acceptance criteria**:
- Extension can list, search, and view PKB memories via main server.
- Response shapes match what `extension/shared/api.js` expects.

#### Task 4.7: Port prompts bridge endpoint

**What**: Create `/ext/prompts` endpoints that bridge to the main prompts system with allowlist filtering.

**Files to create**:
- `endpoints/ext_prompts.py` — Blueprint with `/ext/prompts/*` routes.

**Details**:
- Extension currently has:
  - `GET /ext/prompts` — List prompts (filtered by allowlist, not all prompts)
  - `GET /ext/prompts/<prompt_name>` — Get single prompt
- Main server has `/get_prompts` (returns all prompts) and `/get_prompt_by_name/<name>`.
- Bridge should apply the extension's allowlist filter to return only permitted prompts.
- Allowlist is defined in `extension_server.py` as `EXTENSION_PROMPT_ALLOWLIST`.
- All routes use `@auth_required`.

**Acceptance criteria**:
- Extension can list and fetch prompts via main server.
- Only allowlisted prompts are returned to the extension.
- Response format matches extension's expected shape.

---

### Milestone 5: Extension Client Updates (✅ IMPLEMENTED — jsTree + KaTeX + Domain/Workspace)

**Goal**: Add jsTree-based workspace sidebar (matching main UI style), domain/workspace selectors in popup settings, two conversation creation modes (permanent + temporary), and KaTeX math rendering for LLM responses. Tasks 5.1-5.3 from the original plan are already done (M1 changed API base URL, M3 adapted streaming parser, enriched responses handled via marked.js).

**Effort**: 4-6 days (increased from 2-3 due to jsTree sidebar and KaTeX addition) — **IMPLEMENTED Feb 16, 2026**

**Design decisions** (per user, Feb 16 2026):
- **jsTree sidebar** replacing the flat `<ul>` conversation list — matches main UI's workspace-manager.js pattern
- **Settings-based domain/workspace** in **popup settings** (not sidepanel) — keeps all settings centralized in one place
- **Two conversation buttons**: "New Chat" (permanent) + "Quick Chat" (temporary)
- **Workspace name**: "Browser Extension" (not "Extension")
- **Domain change behavior**: Reload conversations + re-create workspace + clear current conversation
- **KaTeX math rendering**: Render `\[...\]` display math and `\(...\)` inline math in LLM responses
- **Slides**: Ignored (degrade to raw text)
- **No sidebar filters**: Domain is selected in popup settings only; sidebar shows conversations for that domain

**Dependencies completed by earlier milestones**:
- ✅ Task 5.1 (API base URL → port 5000): Done in M1
- ✅ Task 5.2 (streaming parser → newline-delimited JSON): Done in M3 (`streamJsonLines()`)
- ✅ Task 5.3 (enriched response handling): Partially done — TLDR/details render via marked.js, slides degrade to text

**New backend endpoints needed**: None (main backend workspace/conversation endpoints are sufficient)

**New library dependencies**:
- **jsTree 3.3.17** (JS + CSS, dark theme) — same version as main UI
- **jQuery 3.x** (required by jsTree) — extension currently has no jQuery; must be added
- **KaTeX** (JS + CSS + fonts) — for math rendering
- **KaTeX auto-render extension** — for automatic delimiter detection

---

#### Task 5.4: Add domain and workspace selectors to popup Settings

**What**: Add domain dropdown and workspace dropdown to the **popup settings panel** (`popup.html`). When domain changes, auto-create "Browser Extension" workspace if missing, reload sidebar for new domain, and clear current conversation.

**Files to modify**:
- `extension/popup/popup.html` — Add domain and workspace dropdowns to settings view
- `extension/popup/popup.js` — Wire up domain/workspace change handlers, workspace list loading, save logic
- `extension/shared/storage.js` — Add `getWorkspaceId()` / `setWorkspaceId()` methods
- `extension/shared/constants.js` — Add `STORAGE_KEYS.WORKSPACE_ID`, `DEFAULT_SETTINGS.workspaceId`

**Details**:

Settings fields to add (stored in chrome.storage.local via `Storage.setSettings()`):
```javascript
{
  domain: "assistant",              // "assistant", "search", or "finchat"
  workspaceId: null,                // workspace_id string, populated on first load
  workspaceName: "Browser Extension" // display name for UI
}
```

UI flow:
1. User opens popup → clicks Settings gear → settings view appears
2. Domain dropdown populated from hardcoded `DOMAINS` constant
3. Current domain value loaded from `Storage.getDomain()`
4. When domain selected or settings opened:
   a. Call `API.listWorkspaces(domain)` to fetch workspaces for that domain
   b. Check if "Browser Extension" workspace exists (by `workspace_name`)
   c. If not, create it: `API.createWorkspace(domain, 'Browser Extension', {color: '#6f42c1'})`
   d. Populate workspace dropdown with flat list (ignoring hierarchy/parent)
   e. Pre-select "Browser Extension" workspace
5. User can select a different workspace if desired
6. On Save Settings:
   a. Persist `domain` via `Storage.setDomain(newDomain)`
   b. Persist `workspaceId` and `workspaceName` via `Storage.setSettings()`
   c. Also sync to server: `API.updateSettings(settings)`
   d. If domain changed: send `chrome.runtime.sendMessage({type: 'DOMAIN_CHANGED', domain: newDomain})` to notify sidepanel
   e. Show brief toast "Settings saved"

Domain change message handling (in `sidepanel.js`):
```javascript
chrome.runtime.onMessage.addListener(function(msg) {
    if (msg.type === 'DOMAIN_CHANGED') {
        // Clear current conversation and reload for new domain
        state.currentConversation = null;
        state.messages = [];
        welcomeScreen.classList.remove('hidden');
        messagesContainer.classList.add('hidden');
        messagesContainer.innerHTML = '';
        Storage.setCurrentConversation(null);
        loadConversations(); // reloads tree for new domain
    }
});
```

**Settings HTML layout** (insert after Theme dropdown, before Save button in popup.html):
```html
<div class="setting-group">
    <label for="domain-select">Domain</label>
    <select id="domain-select" class="select">
        <option value="assistant">Assistant</option>
        <option value="search">Search</option>
        <option value="finchat">Finance</option>
    </select>
    <div class="setting-help">Conversations are scoped per domain.</div>
</div>

<div class="setting-group">
    <label for="workspace-select">Default Workspace</label>
    <select id="workspace-select" class="select">
        <option value="">Loading...</option>
    </select>
    <div class="setting-help">New conversations go here. "Browser Extension" workspace is auto-created.</div>
</div>
```

**Also add to sidepanel settings panel** (`sidepanel.html` settings-content):
Same domain + workspace dropdowns, mirrored. Both panels read/write the same `Storage` keys.
When either saves, the other should reflect the change on next open.

**Backend calls**:
- `GET /list_workspaces/<domain>` — Returns workspaces for user/domain
  - Response: `[{workspace_id, workspace_name, workspace_color, parent_workspace_id, domain, expanded}]`
- `POST /create_workspace/<domain>/Browser Extension` — Creates workspace
  - Request body: `{workspace_color: "#6f42c1"}` (purple, matching M3 convention)
  - Response: `{workspace_id, workspace_name, workspace_color, parent_workspace_id}`

**Acceptance criteria**:
- Popup settings has domain + workspace dropdowns
- "Browser Extension" workspace auto-created in each domain on first load if missing
- "Browser Extension" pre-selected by default in workspace dropdown
- Workspace dropdown updates when domain changes (fetches workspaces for new domain)
- Settings persist across extension reloads (chrome.storage.local)
- Settings also synced to server (`API.updateSettings()`)
- Domain change sends message to sidepanel → sidepanel clears current conversation + reloads tree
- Sidepanel settings panel has identical domain/workspace dropdowns (mirrored)

---

#### Task 5.5: Replace flat sidebar with jsTree workspace tree

**What**: Replace the current flat `<ul id="conversation-list">` with a jsTree-based hierarchical workspace tree, matching the main UI's `workspace-manager.js` pattern. Workspaces render as folders, conversations as leaves. Includes workspace color indicators, expand/collapse, and context menu.

**Files to create**:
- `extension/sidepanel/workspace-tree.js` — jsTree initialization, data transformation, event handlers (simplified port of `interface/workspace-manager.js`)
- `extension/sidepanel/workspace-tree.css` — jsTree overrides for extension dark theme (adapted from `interface/workspace-styles.css`)

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Replace `<ul id="conversation-list">` with `<div id="workspace-tree-container">`, add jQuery + jsTree includes
- `extension/sidepanel/sidepanel.js` — Replace `renderConversationList()` with calls to `WorkspaceTree.render()`, update conversation selection/creation to go through tree
- `extension/manifest.json` — Ensure jQuery/jsTree scripts are accessible (web_accessible_resources if needed)

**Library files to add** (in `extension/lib/`):
- `jquery.min.js` — jQuery 3.5.1 (same version as main UI, ~87KB minified)
- `jstree.min.js` — jsTree 3.3.17 (~55KB minified)
- `jstree-default-dark/style.min.css` — jsTree dark theme CSS
- `jstree-default-dark/32px.png` — jsTree theme sprite (tree icons)
- `jstree-default-dark/throbber.gif` — jsTree loading indicator

**jsTree config** (simplified from main UI — no drag-drop, no rename, no move):
```javascript
var WorkspaceTree = {
    _ready: false,
    workspaces: {},
    conversations: [],

    init: function() {
        // Load jQuery + jsTree, then render
    },

    buildTreeData: function(workspaces, conversations) {
        var data = [];
        var convByWs = {};  // group conversations by workspace_id

        // Group conversations
        conversations.forEach(function(conv) {
            var wsId = conv.workspace_id || 'default';
            if (!convByWs[wsId]) convByWs[wsId] = [];
            convByWs[wsId].push(conv);
        });

        // Workspace nodes
        workspaces.forEach(function(ws) {
            var count = (convByWs[ws.workspace_id] || []).length;
            var parentId = ws.parent_workspace_id ? ('ws_' + ws.parent_workspace_id) : '#';
            data.push({
                id: 'ws_' + ws.workspace_id,
                parent: parentId,
                text: ws.workspace_name + (count > 0 ? ' (' + count + ')' : ''),
                type: 'workspace',
                state: { opened: ws.expanded !== false },
                li_attr: { 'data-workspace-id': ws.workspace_id, 'data-color': ws.workspace_color },
                a_attr: { title: ws.workspace_name }
            });
        });

        // Conversation nodes
        Object.keys(convByWs).forEach(function(wsId) {
            convByWs[wsId].forEach(function(conv) {
                data.push({
                    id: 'cv_' + conv.conversation_id,
                    parent: 'ws_' + wsId,
                    text: conv.title || '(untitled)',
                    type: 'conversation',
                    li_attr: {
                        'data-conversation-id': conv.conversation_id,
                        'class': conv.is_temporary ? 'conv-temporary' : ''
                    },
                    a_attr: {
                        title: conv.title || '',
                        'data-conversation-id': conv.conversation_id
                    }
                });
            });
        });

        return data;
    },

    render: function(workspaces, conversations) {
        var container = $('#workspace-tree-container');
        if (this._ready) {
            try { container.jstree('destroy'); } catch(_) {}
        }

        var treeData = this.buildTreeData(workspaces, conversations);

        container.jstree({
            core: {
                data: treeData,
                check_callback: true,
                themes: { name: 'default-dark', dots: false, icons: true, responsive: true },
                multiple: false
            },
            types: {
                workspace: { icon: 'fa fa-folder', li_attr: { 'class': 'ws-node' } },
                conversation: { icon: 'fa fa-comment-o', li_attr: { 'class': 'conv-node' }, max_depth: 0 }
            },
            contextmenu: {
                show_at_node: false,
                select_node: false,
                items: function() { return {}; }
            },
            sort: function(a, b) {
                var nodeA = this.get_node(a);
                var nodeB = this.get_node(b);
                var typeA = (nodeA && nodeA.type === 'workspace') ? 0 : 1;
                var typeB = (nodeB && nodeB.type === 'workspace') ? 0 : 1;
                if (typeA !== typeB) return typeA - typeB;
                return 0;  // preserve server order (last_updated desc)
            },
            plugins: ['types', 'wholerow', 'contextmenu', 'sort']
        });

        // Event: select conversation node
        container.on('select_node.jstree', function(e, data) {
            if (data.node.type === 'workspace') {
                // Toggle expand/collapse
                container.jstree('toggle_node', data.node);
                container.jstree('deselect_node', data.node);
            } else if (data.node.type === 'conversation') {
                var convId = data.node.li_attr['data-conversation-id'];
                selectConversation(convId);  // defined in sidepanel.js
            }
        });

        container.on('ready.jstree', function() { WorkspaceTree._ready = true; });
    },

    highlightConversation: function(conversationId) {
        if (!this._ready) return;
        var container = $('#workspace-tree-container');
        var nodeId = 'cv_' + conversationId;
        container.jstree('deselect_all');
        container.jstree('select_node', nodeId);
        // Expand parent workspace if collapsed
        var node = container.jstree('get_node', nodeId);
        if (node && node.parent && node.parent !== '#') {
            container.jstree('open_node', node.parent);
        }
    }
};
```

**Context menu** (simplified — no rename, move, clone, flags):
- **Right-click workspace**: "New Conversation" (permanent in this workspace), "New Quick Chat" (temporary)
- **Right-click conversation**: "Save" (if temporary → make permanent), "Delete"
- Use `$.vakata.context.show()` like main UI

**CSS adaptation** (from `interface/workspace-styles.css`):
- Adapt all `#workspaces-container` selectors to `#workspace-tree-container`
- Keep workspace color indicators (left border: primary, success, danger, warning, info, purple, pink, orange)
- Keep conversation icon color (#75beff)
- Keep wholerow clicked/hovered styling
- Remove flag colors (not needed in extension)
- Adapt font sizes to extension's slightly larger sidepanel context (0.8rem vs 0.76rem)
- Keep vakata context menu dark styling

**FontAwesome icons**: Main UI uses FontAwesome for folder/comment icons. For the extension, either:
- Option A: Include FontAwesome CSS subset (~8KB for fa-folder + fa-comment-o)
- Option B: Use emoji icons instead (📁 for workspace, 💬 for conversation) via jsTree custom icon config
- **Recommended: Option B** (no additional dependency, simpler)

**Data flow**:
1. `loadConversations()` calls `API.getConversations()` (which calls `/list_conversation_by_user/<domain>`)
2. Also calls `API.listWorkspaces(domain)` to get workspace hierarchy
3. Passes both to `WorkspaceTree.render(workspaces, conversations)`
4. Tree renders with workspaces as folders, conversations as leaves
5. Clicking a conversation node calls `selectConversation(convId)`
6. Active conversation highlighted via `WorkspaceTree.highlightConversation(convId)`

**HTML change** (in sidebar):
```html
<!-- Before (current) -->
<ul id="conversation-list" class="conversation-list">
    <!-- Populated by JS -->
</ul>

<!-- After (new) -->
<div id="workspace-tree-container" class="workspace-tree-container">
    <!-- jsTree renders here -->
</div>
```

**Acceptance criteria**:
- Sidebar displays jsTree with workspaces as expandable folders and conversations as leaves
- Workspace folders show conversation count: "Browser Extension (3)"
- Workspace color indicators match main UI (left border colors)
- Clicking workspace toggles expand/collapse
- Clicking conversation loads it in chat area
- Active conversation is highlighted (wholerow selection)
- Context menu on right-click: workspace gets "New Conversation"/"New Quick Chat", conversation gets "Save"/"Delete"
- Tree reloads when domain changes (via DOMAIN_CHANGED message)
- Empty state shown when no conversations exist
- Scrollable when tree is taller than sidebar
- Dark theme matches existing extension aesthetic

---

#### Task 5.6: Add two conversation creation buttons (New Chat + Quick Chat)

**What**: Replace the single "+" button in the header with two buttons: "New Chat" (permanent) and "Quick Chat" (temporary). Both respect the selected domain and workspace from settings.

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Replace single `#new-chat-btn` with two buttons in header
- `extension/sidepanel/sidepanel.js` — Add `createPermanentConversation()` + update `createNewConversation()` (now Quick Chat)

**Details**:

Header button layout change:
```html
<!-- Before (current) -->
<div class="header-right">
    <button id="new-chat-btn" class="icon-btn" title="New chat">
        <svg>...</svg>  <!-- plus icon -->
    </button>
    <button id="settings-btn" class="icon-btn" title="Settings">
        <svg>...</svg>
    </button>
</div>

<!-- After (new) -->
<div class="header-right">
    <button id="new-chat-btn" class="icon-btn" title="New permanent conversation">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
    </button>
    <button id="quick-chat-btn" class="icon-btn" title="New quick chat (temporary)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"></path>
        </svg>
    </button>
    <button id="settings-btn" class="icon-btn" title="Settings">
        <svg>...</svg>
    </button>
</div>
```

New permanent conversation function:
```javascript
async function createPermanentConversation() {
    var domain = await Storage.getDomain();
    var settings = await Storage.getSettings();
    var workspaceId = settings.workspaceId || await getOrCreateExtensionWorkspace();

    clearOcrCache();
    clearImageAttachments();

    // POST /create_conversation/<domain>/<workspace_id>
    var result = await API.call('/create_conversation/' + domain + '/' + encodeURIComponent(workspaceId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    });

    state.currentConversation = {
        conversation_id: result.conversation_id,
        title: result.title || 'New Chat',
        is_temporary: false,
        updated_at: result.last_updated,
    };
    state.messages = [];

    await Storage.setCurrentConversation(result.conversation_id);
    await loadConversations();  // reload tree to show new conversation

    // Reset UI
    welcomeScreen.classList.remove('hidden');
    messagesContainer.classList.add('hidden');
    messagesContainer.innerHTML = '';
    removePageContext();
    messageInput.value = '';
    updateSendButton();
}
```

Existing `createNewConversation()` stays as-is (already creates temporary via `create_temporary_conversation`), but is now wired to `#quick-chat-btn` instead of `#new-chat-btn`.

**Button styling**:
- "New Chat" (+): Standard icon-btn (existing style)
- "Quick Chat" (⚡): Same icon-btn style, lightning bolt SVG to distinguish
- Tooltip clarifies: "New permanent conversation" vs "New quick chat (temporary)"

**Backend calls**:
- **New Chat (permanent)**: `POST /create_conversation/<domain>/<workspace_id>` → returns `{conversation_id, title, last_updated, ...}`
- **Quick Chat (temporary)**: `POST /create_temporary_conversation/<domain>` with `{workspace_id: <id>}` → returns `{conversation: {...}, conversations: [...], workspaces: [...]}`

**Conversation creation flow**:
1. User clicks "+" (New Chat) → permanent conversation in selected workspace → reloads tree
2. User clicks "⚡" (Quick Chat) → atomic temporary conversation → updates tree from response (no reload)
3. Both read domain + workspaceId from `Storage`
4. Both clear current conversation UI and prepare for new chat
5. "Save" button on temporary conversations still works (uses `PUT /make_conversation_stateful/<id>`)

**Acceptance criteria**:
- Two distinct buttons in header: "New Chat" (+) and "Quick Chat" (⚡)
- "New Chat" creates permanent conversation in selected workspace
- "Quick Chat" creates temporary conversation (current behavior, using atomic endpoint)
- Both respect domain setting from popup/sidepanel settings
- Both respect workspace setting from popup/sidepanel settings
- New conversations appear in correct workspace folder in jsTree
- Temporary conversations show different icon or styling in tree (e.g., 💭 vs 💬, or italic text)
- "Save" button on temporary conversations still converts to permanent

---

#### Task 5.7: Add KaTeX math rendering to LLM responses

**What**: Integrate KaTeX to render LaTeX math expressions in LLM responses. The main backend sends math with `\[...\]` (display) and `\(...\)` (inline) delimiters. Currently these appear as raw LaTeX text.

**Files to create**:
- `extension/lib/katex.min.js` — KaTeX core library
- `extension/lib/katex.min.css` — KaTeX styles
- `extension/lib/katex-auto-render.min.js` — KaTeX auto-render extension (scans DOM for delimiters)
- `extension/lib/katex-fonts/` — KaTeX font files (woff2 format, ~15 files, ~500KB total)

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Add KaTeX CSS and JS includes
- `extension/sidepanel/sidepanel.js` — Call `renderMathInElement()` after each message is rendered

**Details**:

Library setup:
- KaTeX version: latest stable (0.16.x as of writing)
- Download from CDN or npm: `katex.min.js` (~250KB), `katex.min.css` (~25KB), `auto-render.min.js` (~5KB)
- Fonts directory must be at `../fonts/` relative to CSS file, or adjust `@font-face` paths
- Total bundle: ~800KB (fonts dominate; only woff2 needed for Chrome)

HTML includes (in `sidepanel.html` `<head>`):
```html
<link rel="stylesheet" href="../lib/katex.min.css">
<!-- KaTeX JS loaded after marked.js to avoid conflicts -->
```

Script includes (at bottom of `sidepanel.html`, before sidepanel.js):
```html
<script src="../lib/katex.min.js"></script>
<script src="../lib/katex-auto-render.min.js"></script>
```

Auto-render config with correct delimiters:
```javascript
function renderMath(element) {
    if (typeof renderMathInElement !== 'function') return;
    try {
        renderMathInElement(element, {
            delimiters: [
                { left: '\\[', right: '\\]', display: true },
                { left: '\\(', right: '\\)', display: false },
                { left: '$$', right: '$$', display: true },
                { left: '$', right: '$', display: false }
            ],
            throwOnError: false,  // render error text instead of throwing
            trust: false,         // no \includegraphics etc.
            strict: false         // allow non-strict LaTeX
        });
    } catch (e) {
        console.warn('[Sidepanel] KaTeX render failed:', e);
    }
}
```

Integration points in `sidepanel.js`:
1. **After `appendMessage()` renders a complete message**: Call `renderMath(messageElement)` on the new `.message-content` div
2. **After streaming completes** (`onComplete` callback in `sendMessage()`): Call `renderMath()` on the assistant message div
3. **During streaming**: Do NOT call renderMath on every chunk (performance). Only call once when the full message is available.
4. **When loading conversation history** (`selectConversation()` loads messages): Call `renderMath()` on each message after rendering

Performance considerations:
- KaTeX is much faster than MathJax (~10ms per expression vs ~100ms)
- Only render math after full message is available (not during streaming)
- For streamed messages, call renderMath once in the `onComplete` callback
- For loaded history, render all messages then call renderMath on the container

Chrome extension CSP notes:
- KaTeX does NOT use `eval()` or `new Function()` — safe under MV3 CSP
- Fonts loaded via `@font-face` — works fine in extension pages
- No external network requests needed (all local files)

**CSS tweaks** for dark theme compatibility:
```css
/* KaTeX dark theme overrides */
.katex { color: var(--text-primary); }
.katex .mord, .katex .mbin, .katex .mrel,
.katex .mopen, .katex .mclose, .katex .mpunct {
    color: inherit;
}
.katex-display {
    margin: 12px 0;
    overflow-x: auto;
    overflow-y: hidden;
}
```

**Acceptance criteria**:
- Display math (`\[...\]` and `$$...$$`) renders as centered block equations
- Inline math (`\(...\)` and `$...$`) renders inline with text
- Math renders correctly in both new messages and loaded conversation history
- Rendering does NOT happen during streaming (only after completion)
- Errors in LaTeX degrade to showing the raw LaTeX text (not crashing)
- Dark theme colors apply to math output (white text on dark background)
- No CSP violations in Chrome extension console
- KaTeX fonts load correctly from local extension files
- Performance: rendering doesn't cause visible lag (KaTeX is fast)

---

#### Task 5.8: Wire up data flow between popup settings and sidepanel

**What**: Ensure domain/workspace changes in popup settings propagate to the sidepanel, and that the sidepanel loads the correct domain/workspace on startup.

**Files to modify**:
- `extension/sidepanel/sidepanel.js` — Listen for `DOMAIN_CHANGED` message, update `getOrCreateExtensionWorkspace()` to use saved workspace, update `loadConversations()` to use domain from settings
- `extension/popup/popup.js` — Send `DOMAIN_CHANGED` message after saving settings
- `extension/background/service-worker.js` — Relay `DOMAIN_CHANGED` to sidepanel if needed
- `extension/shared/constants.js` — Add `MESSAGE_TYPES.DOMAIN_CHANGED`

**Details**:

Startup flow (when sidepanel opens):
1. `initialize()` in `sidepanel.js` reads domain from `Storage.getDomain()`
2. Reads workspaceId from `Storage.getSettings().workspaceId`
3. If workspaceId is null, calls `getOrCreateExtensionWorkspace()` (auto-creates "Browser Extension")
4. Calls `loadConversations()` which:
   a. Fetches `API.listWorkspaces(domain)` — gets workspace hierarchy
   b. Fetches `API.getConversations()` (which calls `/list_conversation_by_user/<domain>`) — gets conversations
   c. Passes both to `WorkspaceTree.render(workspaces, conversations)`

Settings change flow:
1. User changes domain in popup settings and clicks Save
2. `popup.js` persists to `Storage.setDomain(newDomain)` + `Storage.setSettings({workspaceId, workspaceName})`
3. `popup.js` sends `chrome.runtime.sendMessage({type: 'DOMAIN_CHANGED', domain: newDomain})`
4. `sidepanel.js` receives message → clears state → reloads tree for new domain
5. If workspace changed (same domain), sidepanel just reloads tree (no state clear)

**Message types to add**:
```javascript
// In constants.js MESSAGE_TYPES:
DOMAIN_CHANGED: 'DOMAIN_CHANGED',
SETTINGS_CHANGED: 'SETTINGS_CHANGED'
```

**Acceptance criteria**:
- Sidepanel loads correct domain on startup (from Storage)
- Domain change in popup settings triggers sidepanel reload
- Current conversation cleared on domain change
- Workspace ID used for new conversations matches settings
- No race conditions between popup save and sidepanel reload

---

### Milestone 6: File Attachments, Document Management, PKB Panel & Context Menu Expansion

**Goal**: Fix broken PDF upload by pointing at main backend's FastDocIndex endpoint, migrate images to FastImageDocIndex, add document management panels (conversation docs + global docs), add PKB claims viewer, expand conversation context menu to full parity with main UI, and add attachment context menus.

**Effort**: 3-4 days (all client-side, zero new server code)

**Dependencies**: M1 (auth), M3 (conversation bridge), M5 (jsTree sidebar)

**Why this milestone**: After M1-M4 migration, the extension's `API_BASE` is `http://localhost:5000` (main backend), but `api.js` still calls `/ext/upload_doc/<id>` — a route that only exists on `extension_server.py` (port 5001). PDF upload silently 404s. Additionally, the extension lacks document management UI, PKB browsing, and has a minimal context menu (save/delete only) compared to the main UI's 8-item menu.

**Key insight (v3.2)**: All 16 required backend endpoints already exist on the main server (`documents_bp`, `global_docs_bp`, `conversations_bp`, `workspaces_bp`, `pkb_bp`). No new server code needed. This matches the pattern established in M3-M5 where the extension calls main backend endpoints directly.

**Backend endpoints used (all pre-existing)**:

| Endpoint | Method | Blueprint | Used For |
|----------|--------|-----------|----------|
| `/upload_doc_to_conversation/<id>` | POST | `documents_bp` | PDF & image upload → FastDocIndex |
| `/promote_message_doc/<id>/<doc_id>` | POST | `documents_bp` | Promote to full DocIndex (15-45s) |
| `/delete_document_from_conversation/<id>/<doc_id>` | DELETE | `documents_bp` | Remove conversation doc |
| `/list_documents_by_conversation/<id>` | GET | `documents_bp` | List conversation docs |
| `/download_doc_from_conversation/<id>/<doc_id>` | GET | `documents_bp` | Download doc file |
| `/global_docs/upload` | POST | `global_docs_bp` | Upload global doc |
| `/global_docs/list` | GET | `global_docs_bp` | List user's global docs |
| `/global_docs/promote/<id>/<doc_id>` | POST | `global_docs_bp` | Promote conversation doc to global |
| `/global_docs/<doc_id>` | DELETE | `global_docs_bp` | Delete global doc |
| `/global_docs/download/<doc_id>` | GET | `global_docs_bp` | Download global doc |
| `/clone_conversation/<id>` | POST | `conversations_bp` | Clone conversation |
| `/make_conversation_stateless/<id>` | DELETE | `conversations_bp` | Make conversation stateless |
| `/make_conversation_stateful/<id>` | PUT | `conversations_bp` | Make conversation stateful |
| `/set_flag/<id>/<flag>` | POST | `conversations_bp` | Set flag color |
| `/move_conversation_to_workspace/<id>` | PUT | `workspaces_bp` | Move to workspace |
| `/pkb/claims` | GET | `pkb_bp` | List/search claims |

#### Task 6.1: Fix file upload — point at main backend's FastDocIndex endpoint

**What**: Replace broken `/ext/upload_doc/<id>` call with main backend's `/upload_doc_to_conversation/<id>`. Update response handling to use `doc_id`-based flow. Migrate image uploads from base64-only to FastImageDocIndex.

**Why broken**: Extension's `API_BASE` is `http://localhost:5000` but `api.js` calls `/ext/upload_doc/${conversationId}` — a route that only exists on `extension_server.py` (port 5001). After M1-M4, PDF uploads silently 404.

**Files to modify**:
- `extension/shared/api.js` — Update `uploadDoc()` endpoint and add image upload method
- `extension/sidepanel/sidepanel.js` — Update `uploadPendingPdfs()`, `buildDisplayAttachments()`, `addAttachmentFiles()`

**Details — api.js changes**:

Update `uploadDoc()`:
```javascript
// BEFORE (broken — calls extension_server.py route):
async uploadDoc(conversationId, formData) {
    const response = await fetch(`${apiBase}/ext/upload_doc/${conversationId}`, {
        method: 'POST', credentials: 'include', body: formData
    });
    return response.json();
    // Returns: {status, filename, pages, chars}
}

// AFTER (calls main backend's existing endpoint):
async uploadDoc(conversationId, formData) {
    const apiBase = await getApiBaseUrl();
    const response = await fetch(
        `${apiBase}/upload_doc_to_conversation/${conversationId}`,
        { method: 'POST', credentials: 'include', body: formData }
    );
    if (response.status === 401) {
        await Storage.clearAuth();
        throw new AuthError('Session expired or invalid');
    }
    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `Upload failed: ${response.status}`);
    }
    return response.json();
    // Returns: {status: "Indexing started", doc_id, source, title}
}
```

Add image upload (reuse same endpoint — main backend creates FastImageDocIndex for images):
```javascript
async uploadImage(conversationId, imageFile) {
    const apiBase = await getApiBaseUrl();
    const formData = new FormData();
    formData.append('pdf_file', imageFile);  // Same field name — backend auto-detects file type
    const response = await fetch(
        `${apiBase}/upload_doc_to_conversation/${conversationId}`,
        { method: 'POST', credentials: 'include', body: formData }
    );
    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `Image upload failed: ${response.status}`);
    }
    return response.json();
    // Returns: {status: "Indexing started", doc_id, source, title}
}
```

**Details — sidepanel.js changes**:

Update `uploadPendingPdfs()` → rename to `uploadPendingFiles()`:
```javascript
async function uploadPendingFiles(conversationId) {
    for (const att of state.pendingImages) {
        if (!att.file) continue;  // Skip base64-only entries (thumbnails for re-attach)
        try {
            var result;
            if (att.type === 'pdf') {
                const formData = new FormData();
                formData.append('pdf_file', att.file);
                result = await API.uploadDoc(conversationId, formData);
            } else if (att.type === 'image' && att.file) {
                result = await API.uploadImage(conversationId, att.file);
            }
            if (result) {
                att.doc_id = result.doc_id || null;
                att.source = result.source || null;
                att.title = result.title || att.name;
            }
        } catch (err) {
            console.error('[Sidepanel] File upload failed:', att.name, err);
        }
    }
}
```

Update `buildDisplayAttachments()` to include `doc_id`:
```javascript
async function buildDisplayAttachments(pendingItems) {
    const result = [];
    for (const att of pendingItems) {
        if (att.type === 'pdf') {
            result.push({
                type: 'pdf', name: att.name, thumbnail: null,
                doc_id: att.doc_id || null, source: att.source || null
            });
        } else {
            const thumbnail = att.dataUrl ? await generateThumbnail(att.dataUrl) : null;
            result.push({
                type: 'image', name: att.name, thumbnail,
                doc_id: att.doc_id || null, source: att.source || null
            });
        }
    }
    return result.length > 0 ? result : null;
}
```

Update `addAttachmentFiles()` to store the File object for images too:
```javascript
// In the image branch, also store the File object for later upload:
if (isImage) {
    const dataUrl = await readFileAsDataUrl(file);
    state.pendingImages.push({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        name: file.name, type: 'image', dataUrl,
        file: file  // NEW: store File for FastImageDocIndex upload
    });
}
```

Update `sendMessage()` call site:
```javascript
// Change: await uploadPendingPdfs(...)
// To:     await uploadPendingFiles(...)
await uploadPendingFiles(state.currentConversation.conversation_id);
```

Also update how images are sent to `sendMessageStreaming()`:
```javascript
// BEFORE: images sent as base64 data URLs in payload
const imagesToSend = state.pendingImages.filter(att => att.type !== 'pdf').map(img => img.dataUrl);

// AFTER: images uploaded via FastImageDocIndex; only send base64 for vision models
// that need it (backward compat). doc_ids flow via display_attachments.
const imagesToSend = state.pendingImages
    .filter(att => att.type === 'image' || att.type !== 'pdf')
    .map(img => img.dataUrl)
    .filter(Boolean);
```

**Response shape change**:

| Field | Old (`/ext/upload_doc`) | New (`/upload_doc_to_conversation`) |
|-------|------------------------|-------------------------------------|
| `status` | `"ok"` | `"Indexing started"` |
| `filename` | `"document.pdf"` | ❌ (not returned) |
| `pages` | `3` | ❌ (not returned) |
| `chars` | `12500` | ❌ (not returned) |
| `doc_id` | ❌ | `"2332129554"` |
| `source` | ❌ | `"/storage/pdfs/document.pdf"` |
| `title` | ❌ | `"document.pdf"` |

**Backend behavior** (for reference, no changes needed):
- Main backend's `upload_doc_to_conversation_route()` in `endpoints/documents.py`:
  1. Saves PDF to `state.pdfs_dir`
  2. Calls `conversation.add_message_attached_document(full_pdf_path)`
  3. This creates a `FastDocIndex` (BM25 keyword index, 1-3s) — NOT simple text extraction
  4. Saves conversation state
  5. Returns `{status, doc_id, source, title}`
- For images, `create_fast_document_index()` auto-detects file type and creates `FastImageDocIndex` instead
- Both are added to conversation's `message_attached_documents_list`

**Acceptance criteria**:
- Extension PDF upload calls `/upload_doc_to_conversation/<id>` on main backend
- Extension image upload also calls same endpoint (creates FastImageDocIndex)
- `doc_id` is stored in each pending attachment after upload
- `display_attachments` includes `doc_id` and `source` fields
- LLM can search uploaded documents via BM25 when referenced
- Upload completes in 1-3s (matching main UI behavior)

---

#### Task 6.2: Add document and conversation API methods to api.js

**What**: Add all new API methods needed for document management, conversation context menu actions, and PKB claims browsing.

**Files to modify**:
- `extension/shared/api.js` — Add ~15 new methods

**Details — Document management methods**:

```javascript
// Conversation documents
async listDocuments(conversationId) {
    return this.call('/list_documents_by_conversation/' + conversationId);
}

async deleteDocument(conversationId, docId) {
    return this.call('/delete_document_from_conversation/' + conversationId + '/' + docId, {
        method: 'DELETE'
    });
}

async downloadDocUrl(conversationId, docId) {
    const apiBase = await getApiBaseUrl();
    return `${apiBase}/download_doc_from_conversation/${conversationId}/${docId}`;
}

async promoteMessageDoc(conversationId, docId) {
    return this.call('/promote_message_doc/' + conversationId + '/' + docId, {
        method: 'POST',
        timeoutMs: 60000  // 15-45s operation, generous timeout
    });
}

// Global documents
async listGlobalDocs() {
    return this.call('/global_docs/list');
}

async uploadGlobalDoc(formData) {
    const apiBase = await getApiBaseUrl();
    const response = await fetch(`${apiBase}/global_docs/upload`, {
        method: 'POST', credentials: 'include', body: formData
    });
    if (response.status === 401) {
        await Storage.clearAuth();
        throw new AuthError('Session expired or invalid');
    }
    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `Upload failed: ${response.status}`);
    }
    return response.json();
}

async deleteGlobalDoc(docId) {
    return this.call('/global_docs/' + docId, { method: 'DELETE' });
}

async downloadGlobalDocUrl(docId) {
    const apiBase = await getApiBaseUrl();
    return `${apiBase}/global_docs/download/${docId}`;
}

async promoteToGlobal(conversationId, docId) {
    return this.call('/global_docs/promote/' + conversationId + '/' + docId, {
        method: 'POST',
        timeoutMs: 60000
    });
}
```

**Details — Conversation context menu methods**:

```javascript
async cloneConversation(conversationId) {
    return this.call('/clone_conversation/' + conversationId, { method: 'POST' });
}

async makeConversationStateless(conversationId) {
    return this.call('/make_conversation_stateless/' + conversationId, { method: 'DELETE' });
}

// makeConversationStateful already exists as saveConversation()

async setFlag(conversationId, flag) {
    return this.call('/set_flag/' + conversationId + '/' + flag, { method: 'POST' });
}

async moveConversationToWorkspace(conversationId, targetWorkspaceId) {
    return this.call('/move_conversation_to_workspace/' + conversationId, {
        method: 'PUT',
        body: JSON.stringify({ target_workspace_id: targetWorkspaceId })
    });
}
```

**Details — PKB claims method** (already partially exists):

The existing `getMemories()` and `searchMemories()` methods use `/pkb/claims`. Enhance with filter support:

```javascript
async getClaims(params = {}) {
    // params: { limit, offset, query, claim_type, context_domain, status }
    var query = new URLSearchParams(params).toString();
    return this.call('/pkb/claims' + (query ? '?' + query : ''));
    // Returns: {claims: [...], count: N}
}
```

**Acceptance criteria**:
- All 15 new API methods callable from extension code
- Each method targets the correct main backend endpoint
- Auth errors (401) properly trigger logout flow
- Long-running operations (promote) use extended timeout (60s)
- FormData uploads (global docs) bypass JSON Content-Type header

---

#### Task 6.3: Add document management panel (Docs Panel)

**What**: Create a new overlay panel accessible via a "Docs" button in the action bar. Contains two collapsible sections (Conversation Docs + Global Docs) using a shared reusable UI component. Each section supports list, upload, download, remove.

**Files to create**:
- `extension/sidepanel/docs-panel.js` — DocsPanel module (~250-300 lines)

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Add docs button + docs-panel div
- `extension/sidepanel/sidepanel.js` — Wire docs button toggle, listen for conversation changes
- `extension/sidepanel/sidepanel.css` — Panel styles, collapsible sections, doc items

**Details — HTML structure** (in `sidepanel.html`):

Add button to action bar (beside `new-chat-btn` and `quick-chat-btn`):
```html
<div class="action-bar">
    <button id="new-chat-btn" title="New Chat">+ New</button>
    <button id="quick-chat-btn" title="Quick Chat">⚡ Quick</button>
    <button id="docs-btn" title="Documents">📄 Docs</button>
    <button id="claims-btn" title="Claims">🧠 Claims</button>
</div>
```

Add panel div (sibling of `settings-panel`, `main-view`):
```html
<div id="docs-panel" class="overlay-panel hidden">
    <div class="panel-header">
        <h3>Documents</h3>
        <button id="docs-panel-close" class="close-btn">&times;</button>
    </div>
    <div class="panel-body">
        <!-- Conversation Docs Section -->
        <div class="collapsible-section" id="conv-docs-section">
            <div class="section-header" data-toggle="conv-docs-list">
                <span class="collapse-arrow">▸</span>
                <span>Conversation Documents</span>
                <span class="doc-count" id="conv-doc-count">(0)</span>
            </div>
            <div class="section-body hidden" id="conv-docs-list">
                <div class="doc-upload-row">
                    <input type="file" id="conv-doc-upload" accept=".pdf,.doc,.docx,.html,.md,.csv,.xlsx,.json" hidden>
                    <button id="conv-doc-upload-btn" class="upload-btn">+ Upload</button>
                </div>
                <div id="conv-docs-items" class="doc-items">
                    <!-- Populated by DocsPanel.loadConversationDocs() -->
                </div>
            </div>
        </div>

        <!-- Global Docs Section -->
        <div class="collapsible-section" id="global-docs-section">
            <div class="section-header" data-toggle="global-docs-list">
                <span class="collapse-arrow">▸</span>
                <span>Global Documents</span>
                <span class="doc-count" id="global-doc-count">(0)</span>
            </div>
            <div class="section-body hidden" id="global-docs-list">
                <div class="doc-upload-row">
                    <input type="file" id="global-doc-upload" accept=".pdf,.doc,.docx,.html,.md,.csv,.xlsx,.json" hidden>
                    <button id="global-doc-upload-btn" class="upload-btn">+ Upload</button>
                </div>
                <div id="global-docs-items" class="doc-items">
                    <!-- Populated by DocsPanel.loadGlobalDocs() -->
                </div>
            </div>
        </div>
    </div>
</div>
```

**Details — docs-panel.js module**:

Module pattern (IIFE, matching WorkspaceTree):
```javascript
var DocsPanel = (function() {
    var _conversationId = null;

    function init() {
        // Wire collapsible headers
        document.querySelectorAll('.section-header[data-toggle]').forEach(function(header) {
            header.addEventListener('click', function() {
                var targetId = this.getAttribute('data-toggle');
                var body = document.getElementById(targetId);
                var arrow = this.querySelector('.collapse-arrow');
                body.classList.toggle('hidden');
                arrow.textContent = body.classList.contains('hidden') ? '▸' : '▾';
            });
        });
        // Wire upload buttons
        _wireUploadButton('conv-doc-upload-btn', 'conv-doc-upload', _uploadConvDoc);
        _wireUploadButton('global-doc-upload-btn', 'global-doc-upload', _uploadGlobalDoc);
    }

    function setConversation(conversationId) {
        _conversationId = conversationId;
        if (!document.getElementById('docs-panel').classList.contains('hidden')) {
            loadConversationDocs();
        }
    }

    async function loadConversationDocs() {
        if (!_conversationId) {
            _renderDocItems('conv-docs-items', [], 'conv-doc-count');
            return;
        }
        try {
            var docs = await API.listDocuments(_conversationId);
            if (!Array.isArray(docs)) docs = [];
            _renderDocItems('conv-docs-items', docs, 'conv-doc-count', {
                onDownload: function(doc) { _downloadConvDoc(doc); },
                onRemove: function(doc) { _removeConvDoc(doc); }
            });
        } catch (err) {
            console.error('[DocsPanel] Failed to load conversation docs:', err);
        }
    }

    async function loadGlobalDocs() {
        try {
            var docs = await API.listGlobalDocs();
            if (!Array.isArray(docs)) docs = docs.docs || [];
            _renderDocItems('global-docs-items', docs, 'global-doc-count', {
                onDownload: function(doc) { _downloadGlobalDoc(doc); },
                onRemove: function(doc) { _removeGlobalDoc(doc); }
            });
        } catch (err) {
            console.error('[DocsPanel] Failed to load global docs:', err);
        }
    }

    // Shared renderer for both doc lists
    function _renderDocItems(containerId, docs, countId, actions) {
        var container = document.getElementById(containerId);
        var countEl = document.getElementById(countId);
        if (countEl) countEl.textContent = '(' + docs.length + ')';
        if (!container) return;

        if (docs.length === 0) {
            container.innerHTML = '<div class="doc-empty">No documents</div>';
            return;
        }
        container.innerHTML = docs.map(function(doc, idx) {
            var title = doc.title || doc.display_name || doc.source || 'Document';
            var ref = doc.doc_id ? '#doc_' + (idx + 1) : '';
            return '<div class="doc-item" data-doc-id="' + (doc.doc_id || '') + '">' +
                '<div class="doc-info">' +
                    '<span class="doc-title" title="' + title + '">' + title + '</span>' +
                    (ref ? '<span class="doc-ref">' + ref + '</span>' : '') +
                '</div>' +
                '<div class="doc-actions">' +
                    '<button class="doc-action-btn doc-download" title="Download">⬇</button>' +
                    '<button class="doc-action-btn doc-remove" title="Remove">🗑</button>' +
                '</div>' +
            '</div>';
        }).join('');

        // Wire action buttons
        if (actions) {
            container.querySelectorAll('.doc-download').forEach(function(btn, i) {
                btn.addEventListener('click', function() { actions.onDownload(docs[i]); });
            });
            container.querySelectorAll('.doc-remove').forEach(function(btn, i) {
                btn.addEventListener('click', function() { actions.onRemove(docs[i]); });
            });
        }
    }

    async function _uploadConvDoc(file) {
        if (!_conversationId) return;
        var formData = new FormData();
        formData.append('pdf_file', file);
        await API.uploadDoc(_conversationId, formData);
        loadConversationDocs();
    }

    async function _uploadGlobalDoc(file) {
        var formData = new FormData();
        formData.append('pdf_file', file);
        formData.append('display_name', file.name);
        await API.uploadGlobalDoc(formData);
        loadGlobalDocs();
    }

    async function _downloadConvDoc(doc) {
        var url = await API.downloadDocUrl(_conversationId, doc.doc_id);
        window.open(url, '_blank');
    }

    async function _downloadGlobalDoc(doc) {
        var url = await API.downloadGlobalDocUrl(doc.doc_id);
        window.open(url, '_blank');
    }

    async function _removeConvDoc(doc) {
        if (!confirm('Remove "' + (doc.title || 'document') + '" from conversation?')) return;
        await API.deleteDocument(_conversationId, doc.doc_id);
        loadConversationDocs();
    }

    async function _removeGlobalDoc(doc) {
        if (!confirm('Delete global doc "' + (doc.title || doc.display_name || 'document') + '"?')) return;
        await API.deleteGlobalDoc(doc.doc_id);
        loadGlobalDocs();
    }

    function _wireUploadButton(btnId, inputId, handler) {
        var btn = document.getElementById(btnId);
        var input = document.getElementById(inputId);
        if (btn && input) {
            btn.addEventListener('click', function() { input.click(); });
            input.addEventListener('change', function() {
                if (this.files.length > 0) { handler(this.files[0]); this.value = ''; }
            });
        }
    }

    function show() {
        document.getElementById('docs-panel').classList.remove('hidden');
        loadConversationDocs();
        loadGlobalDocs();
    }

    function hide() {
        document.getElementById('docs-panel').classList.add('hidden');
    }

    function toggle() {
        var panel = document.getElementById('docs-panel');
        if (panel.classList.contains('hidden')) { show(); } else { hide(); }
    }

    return {
        init: init,
        show: show,
        hide: hide,
        toggle: toggle,
        setConversation: setConversation,
        loadConversationDocs: loadConversationDocs,
        loadGlobalDocs: loadGlobalDocs
    };
})();
```

**Details — sidepanel.js wiring**:
```javascript
// In initialization:
DocsPanel.init();

// Wire docs button:
document.getElementById('docs-btn').addEventListener('click', function() {
    DocsPanel.toggle();
    ClaimsPanel.hide();  // Close claims if open
});
document.getElementById('docs-panel-close').addEventListener('click', function() {
    DocsPanel.hide();
});

// When conversation changes:
function onConversationChanged(conversationId) {
    DocsPanel.setConversation(conversationId);
}
```

**Details — CSS styles** (in `sidepanel.css`):
```css
.overlay-panel {
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: var(--bg-primary, #1e1e1e); z-index: 100;
    display: flex; flex-direction: column; overflow-y: auto;
}
.overlay-panel.hidden { display: none; }
.panel-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 16px; border-bottom: 1px solid var(--border-color, #333);
}
.panel-header h3 { margin: 0; font-size: 16px; }
.collapsible-section { border-bottom: 1px solid var(--border-color, #333); }
.section-header {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 16px; cursor: pointer; user-select: none;
}
.section-header:hover { background: rgba(255,255,255,0.05); }
.collapse-arrow { font-size: 12px; width: 16px; text-align: center; }
.section-body { padding: 0 16px 12px; }
.doc-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 6px 8px; border-radius: 4px; margin-bottom: 4px;
}
.doc-item:hover { background: rgba(255,255,255,0.05); }
.doc-info { flex: 1; min-width: 0; }
.doc-title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.doc-ref { font-size: 11px; color: #888; font-family: monospace; }
.doc-actions { display: flex; gap: 4px; flex-shrink: 0; }
.doc-action-btn {
    background: none; border: none; cursor: pointer; padding: 2px 6px;
    font-size: 14px; opacity: 0.6; border-radius: 3px;
}
.doc-action-btn:hover { opacity: 1; background: rgba(255,255,255,0.1); }
.doc-upload-row { margin-bottom: 8px; }
.upload-btn {
    background: rgba(255,255,255,0.1); border: 1px dashed #555; color: #ccc;
    padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 13px; width: 100%;
}
.upload-btn:hover { background: rgba(255,255,255,0.15); border-color: #888; }
.doc-empty { color: #666; font-size: 13px; padding: 8px 0; text-align: center; }
.doc-count { color: #888; font-size: 12px; }
```

**Acceptance criteria**:
- "Docs" button visible in action bar, opens overlay panel
- Panel shows two collapsible sections: "Conversation Documents" and "Global Documents"
- Each section shows doc list with title, `#doc_N` reference, download and remove buttons
- Upload button triggers file picker, uploads via correct endpoint, refreshes list
- Download opens file in new tab
- Remove prompts confirmation, deletes via API, refreshes list
- Conversation docs section updates when active conversation changes
- Sections remember collapsed/expanded state during panel lifetime
- Panel closes via X button or clicking Docs button again

---

#### Task 6.4: Add PKB claims panel

**What**: Create a new overlay panel accessible via a "Claims" button in the action bar. Read-only claims viewer with search and filter (type, domain, status). Uses existing `GET /pkb/claims` endpoint.

**Files to create**:
- `extension/sidepanel/claims-panel.js` — ClaimsPanel module (~200-250 lines)

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Add claims button (already in Task 6.3 HTML) + claims-panel div
- `extension/sidepanel/sidepanel.js` — Wire claims button toggle
- `extension/sidepanel/sidepanel.css` — Claims panel styles, claim cards, filter row

**Details — HTML structure** (in `sidepanel.html`):

```html
<div id="claims-panel" class="overlay-panel hidden">
    <div class="panel-header">
        <h3>Claims / Memories</h3>
        <button id="claims-panel-close" class="close-btn">&times;</button>
    </div>
    <div class="panel-body">
        <!-- Search -->
        <div class="claims-search-row">
            <input type="text" id="claims-search" placeholder="Search claims..." class="claims-search-input">
        </div>
        <!-- Filters -->
        <div class="claims-filter-row">
            <select id="claims-filter-type" class="claims-filter">
                <option value="">All Types</option>
                <option value="fact">Fact</option>
                <option value="preference">Preference</option>
                <option value="decision">Decision</option>
                <option value="task">Task</option>
                <option value="reminder">Reminder</option>
                <option value="habit">Habit</option>
                <option value="memory">Memory</option>
                <option value="observation">Observation</option>
            </select>
            <select id="claims-filter-domain" class="claims-filter">
                <option value="">All Domains</option>
                <option value="personal">Personal</option>
                <option value="health">Health</option>
                <option value="work">Work</option>
                <option value="relationships">Relationships</option>
                <option value="learning">Learning</option>
                <option value="life_ops">Life Ops</option>
                <option value="finance">Finance</option>
            </select>
            <select id="claims-filter-status" class="claims-filter">
                <option value="">All Status</option>
                <option value="active">Active</option>
                <option value="contested">Contested</option>
                <option value="historical">Historical</option>
            </select>
        </div>
        <!-- Claims list -->
        <div id="claims-list" class="claims-list">
            <!-- Populated by ClaimsPanel.loadClaims() -->
        </div>
        <!-- Load more -->
        <div id="claims-load-more" class="claims-load-more hidden">
            <button id="claims-load-more-btn" class="load-more-btn">Load more...</button>
        </div>
    </div>
</div>
```

**Details — claims-panel.js module**:

```javascript
var ClaimsPanel = (function() {
    var _claims = [];
    var _offset = 0;
    var _limit = 20;
    var _total = 0;
    var _searchDebounce = null;

    function init() {
        // Wire search with debounce
        var searchInput = document.getElementById('claims-search');
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                clearTimeout(_searchDebounce);
                _searchDebounce = setTimeout(function() { _resetAndLoad(); }, 300);
            });
        }
        // Wire filters
        ['claims-filter-type', 'claims-filter-domain', 'claims-filter-status'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.addEventListener('change', function() { _resetAndLoad(); });
        });
        // Wire load more
        var loadMoreBtn = document.getElementById('claims-load-more-btn');
        if (loadMoreBtn) {
            loadMoreBtn.addEventListener('click', function() { _loadMore(); });
        }
    }

    function _getFilters() {
        var params = { limit: _limit, offset: _offset };
        var query = (document.getElementById('claims-search') || {}).value || '';
        var claimType = (document.getElementById('claims-filter-type') || {}).value || '';
        var domain = (document.getElementById('claims-filter-domain') || {}).value || '';
        var status = (document.getElementById('claims-filter-status') || {}).value || '';
        if (query.trim()) params.query = query.trim();
        if (claimType) params.claim_type = claimType;
        if (domain) params.context_domain = domain;
        if (status) params.status = status;
        return params;
    }

    function _resetAndLoad() {
        _offset = 0;
        _claims = [];
        loadClaims();
    }

    async function loadClaims() {
        try {
            var params = _getFilters();
            var result = await API.getClaims(params);
            var newClaims = result.claims || [];
            _total = result.count || 0;

            if (_offset === 0) {
                _claims = newClaims;
            } else {
                _claims = _claims.concat(newClaims);
            }
            _renderClaims();
        } catch (err) {
            console.error('[ClaimsPanel] Failed to load claims:', err);
        }
    }

    function _loadMore() {
        _offset += _limit;
        loadClaims();
    }

    function _renderClaims() {
        var container = document.getElementById('claims-list');
        var loadMoreEl = document.getElementById('claims-load-more');
        if (!container) return;

        if (_claims.length === 0) {
            container.innerHTML = '<div class="claims-empty">No claims found</div>';
            if (loadMoreEl) loadMoreEl.classList.add('hidden');
            return;
        }

        container.innerHTML = _claims.map(function(claim) {
            var typeBadge = '<span class="claim-badge claim-type-' + claim.claim_type + '">'
                + claim.claim_type + '</span>';
            var domainBadge = claim.context_domain
                ? '<span class="claim-badge claim-domain">' + claim.context_domain + '</span>' : '';
            var statusBadge = claim.status !== 'active'
                ? '<span class="claim-badge claim-status-' + claim.status + '">' + claim.status + '</span>' : '';
            var refId = claim.friendly_id
                ? '<span class="claim-ref">@' + claim.friendly_id + '</span>' : '';
            var claimNum = claim.claim_number
                ? '<span class="claim-num">#' + claim.claim_number + '</span>' : '';

            return '<div class="claim-card">' +
                '<div class="claim-statement">' + _escapeHtml(claim.statement) + '</div>' +
                '<div class="claim-meta">' +
                    claimNum + refId + typeBadge + domainBadge + statusBadge +
                '</div>' +
            '</div>';
        }).join('');

        // Show/hide load more
        if (loadMoreEl) {
            loadMoreEl.classList.toggle('hidden', _claims.length >= _total);
        }
    }

    function _escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    function show() {
        document.getElementById('claims-panel').classList.remove('hidden');
        if (_claims.length === 0) { _resetAndLoad(); }
    }

    function hide() {
        document.getElementById('claims-panel').classList.add('hidden');
    }

    function toggle() {
        var panel = document.getElementById('claims-panel');
        if (panel.classList.contains('hidden')) { show(); } else { hide(); }
    }

    return {
        init: init, show: show, hide: hide, toggle: toggle, loadClaims: loadClaims
    };
})();
```

**Details — CSS styles** (in `sidepanel.css`):
```css
.claims-search-row { padding: 8px 16px; }
.claims-search-input {
    width: 100%; padding: 6px 10px; border: 1px solid #444; border-radius: 4px;
    background: #2a2a2a; color: #eee; font-size: 13px;
}
.claims-filter-row { display: flex; gap: 6px; padding: 0 16px 8px; }
.claims-filter {
    flex: 1; padding: 4px 6px; border: 1px solid #444; border-radius: 4px;
    background: #2a2a2a; color: #ccc; font-size: 11px;
}
.claims-list { padding: 0 16px; overflow-y: auto; }
.claim-card {
    padding: 8px 10px; border-radius: 4px; margin-bottom: 6px;
    background: rgba(255,255,255,0.03); border: 1px solid #333;
}
.claim-card:hover { background: rgba(255,255,255,0.06); }
.claim-statement { font-size: 13px; line-height: 1.4; margin-bottom: 4px; }
.claim-meta { display: flex; flex-wrap: wrap; gap: 4px; }
.claim-badge {
    font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 500;
}
.claim-type-fact { background: #1a472a; color: #4ade80; }
.claim-type-preference { background: #3b1f5e; color: #c084fc; }
.claim-type-decision { background: #1e3a5f; color: #60a5fa; }
.claim-type-task { background: #5c3d1e; color: #fb923c; }
.claim-type-reminder { background: #5c1e1e; color: #f87171; }
.claim-type-habit { background: #1e4d4d; color: #5eead4; }
.claim-type-memory { background: #4a3728; color: #d4a574; }
.claim-type-observation { background: #3d3d1e; color: #d4d45e; }
.claim-domain { background: #333; color: #aaa; }
.claim-status-contested { background: #5c1e1e; color: #f87171; }
.claim-status-historical { background: #333; color: #888; }
.claim-ref, .claim-num { font-size: 10px; font-family: monospace; color: #888; }
.claims-empty { color: #666; font-size: 13px; padding: 16px 0; text-align: center; }
.load-more-btn {
    width: 100%; padding: 8px; margin: 8px 16px; background: rgba(255,255,255,0.05);
    border: 1px solid #444; border-radius: 4px; color: #aaa; cursor: pointer;
}
```

**Details — sidepanel.js wiring**:
```javascript
ClaimsPanel.init();

document.getElementById('claims-btn').addEventListener('click', function() {
    ClaimsPanel.toggle();
    DocsPanel.hide();  // Close docs if open
});
document.getElementById('claims-panel-close').addEventListener('click', function() {
    ClaimsPanel.hide();
});
```

**PKB endpoint reference** (`GET /pkb/claims`):
- Query params: `query`, `claim_type`, `context_domain`, `status`, `limit`, `offset`
- Returns: `{claims: [{claim_id, statement, claim_type, context_domain, status, friendly_id, claim_number, updated_at, ...}], count: N}`
- Already registered in main backend (`endpoints/pkb.py`, `pkb_bp`)
- Already has `@login_required` decorator
- Extension's existing `api.js` already has `getMemories()` and `searchMemories()` that wrap this endpoint — Task 6.2 adds `getClaims()` for direct access with filter support

**Acceptance criteria**:
- "Claims" button visible in action bar, opens overlay panel
- Search input triggers debounced query (300ms)
- Three filter dropdowns: type (8 options), domain (7 options), status (3 options)
- Claims render as cards with statement, type badge (colored), domain badge, status badge, @friendly_id, #claim_number
- "Load more" button appears when more claims exist
- Panel closes via X button or clicking Claims button again
- Empty state shows "No claims found"

---

#### Task 6.5: Expand conversation context menu to full parity with main UI

**What**: Expand workspace-tree.js `_contextMenuItems()` from 2 items (save/delete) to 8 items matching the main UI's `buildConversationContextMenu()` in `interface/workspace-manager.js`.

**Files to modify**:
- `extension/sidepanel/workspace-tree.js` — Expand `_contextMenuItems()`, add `_buildFlagSubmenu()`, `_buildMoveSubmenu()`
- `extension/sidepanel/sidepanel.js` — Add event listeners for new context menu actions

**Details — workspace-tree.js context menu expansion**:

Replace the existing conversation context menu items:

```javascript
_contextMenuItems: function(node) {
    var self = this;

    if (node.type === 'workspace') {
        return {
            newChat: {
                label: '+ New Chat',
                action: function() {
                    var wsId = node.id.substring(3);
                    document.dispatchEvent(new CustomEvent('tree-new-chat', {
                        detail: { workspaceId: wsId, temporary: false }
                    }));
                }
            },
            quickChat: {
                label: '⚡ Quick Chat',
                action: function() {
                    var wsId = node.id.substring(3);
                    document.dispatchEvent(new CustomEvent('tree-new-chat', {
                        detail: { workspaceId: wsId, temporary: true }
                    }));
                }
            }
        };
    }

    if (node.type === 'conversation') {
        var convId = node.id.substring(3);
        return {
            copyRef: {
                label: '📋 Copy Reference',
                action: function() {
                    var fid = node.li_attr['data-conversation-friendly-id'];
                    if (fid) {
                        navigator.clipboard.writeText(fid).then(function() {
                            document.dispatchEvent(new CustomEvent('tree-toast', {
                                detail: { message: 'Copied: ' + fid, type: 'info' }
                            }));
                        });
                    }
                },
                _disabled: !node.li_attr['data-conversation-friendly-id'],
                separator_after: true
            },
            openNewWindow: {
                label: '🔗 Open in New Window',
                action: function() {
                    // Open on main web UI
                    var apiBase = API_BASE.replace(/\/+$/, '');
                    window.open(apiBase + '/interface/' + convId, '_blank');
                }
            },
            clone: {
                separator_before: true,
                label: '📑 Clone',
                action: function() {
                    document.dispatchEvent(new CustomEvent('tree-clone-conversation', {
                        detail: { conversationId: convId }
                    }));
                }
            },
            toggleStateless: {
                label: '👁️ Toggle Stateless',
                action: function() {
                    document.dispatchEvent(new CustomEvent('tree-toggle-stateless', {
                        detail: { conversationId: convId }
                    }));
                }
            },
            flag: {
                label: '🏳️ Set Flag',
                submenu: self._buildFlagSubmenu(convId)
            },
            moveTo: {
                label: '📁 Move to...',
                submenu: self._buildMoveSubmenu(convId)
            },
            save: {
                separator_before: true,
                label: '💾 Save',
                action: function() {
                    document.dispatchEvent(new CustomEvent('tree-save-conversation', {
                        detail: { conversationId: convId }
                    }));
                }
            },
            deleteConv: {
                label: '🗑️ Delete',
                action: function() {
                    document.dispatchEvent(new CustomEvent('tree-delete-conversation', {
                        detail: { conversationId: convId }
                    }));
                }
            }
        };
    }
    return {};
},

_buildFlagSubmenu: function(convId) {
    var flags = {
        none: '⚪ No Flag', red: '🔴 Red', blue: '🔵 Blue',
        green: '🟢 Green', yellow: '🟡 Yellow', orange: '🟠 Orange', purple: '🟣 Purple'
    };
    var submenu = {};
    Object.keys(flags).forEach(function(color) {
        submenu['flag_' + color] = {
            label: flags[color],
            action: function() {
                document.dispatchEvent(new CustomEvent('tree-set-flag', {
                    detail: { conversationId: convId, flag: color }
                }));
            }
        };
    });
    return submenu;
},

_buildMoveSubmenu: function(convId) {
    var submenu = {};
    // _workspaces is populated during loadTree()
    (this._workspaces || []).forEach(function(ws) {
        submenu['move_' + ws.workspace_id] = {
            label: '📁 ' + ws.workspace_name,
            action: function() {
                document.dispatchEvent(new CustomEvent('tree-move-conversation', {
                    detail: { conversationId: convId, targetWorkspaceId: ws.workspace_id }
                }));
            }
        };
    });
    return submenu;
}
```

**Note**: The `_buildMoveSubmenu()` method requires storing the workspaces array during `loadTree()`. Add to `loadTree()`:
```javascript
// In loadTree(), after loading workspaces:
this._workspaces = workspaces;
```

**Also**: To populate `data-conversation-friendly-id` on tree nodes, update `_buildTreeData()`:
```javascript
// In _buildTreeData(), for conversation nodes:
data.push({
    id: 'cv_' + conv.conversation_id,
    parent: parentId,
    text: conv.title || 'New Chat',
    type: 'conversation',
    li_attr: {
        'data-conversation-id': conv.conversation_id,
        'data-conversation-friendly-id': conv.friendly_id || ''
    }
});
```

**Details — sidepanel.js event handlers for new actions**:

```javascript
// Clone
document.addEventListener('tree-clone-conversation', async function(e) {
    var convId = e.detail.conversationId;
    try {
        var result = await API.cloneConversation(convId);
        await WorkspaceTree.refreshTree();
        showToast('Conversation cloned', 'success');
        // Optionally select the cloned conversation
        if (result.conversation_id) {
            loadConversation(result.conversation_id);
        }
    } catch (err) {
        showToast('Clone failed: ' + err.message, 'error');
    }
});

// Toggle Stateless
document.addEventListener('tree-toggle-stateless', async function(e) {
    var convId = e.detail.conversationId;
    try {
        // Try making stateless first; if already stateless, make stateful
        await API.makeConversationStateless(convId);
        showToast('Conversation set to stateless', 'info');
    } catch (err) {
        try {
            await API.saveConversation(convId);
            showToast('Conversation set to stateful', 'info');
        } catch (err2) {
            showToast('Toggle failed: ' + err2.message, 'error');
        }
    }
});

// Set Flag
document.addEventListener('tree-set-flag', async function(e) {
    var convId = e.detail.conversationId;
    var flag = e.detail.flag;
    try {
        await API.setFlag(convId, flag);
        await WorkspaceTree.refreshTree();
        showToast('Flag set to ' + flag, 'info');
    } catch (err) {
        showToast('Set flag failed: ' + err.message, 'error');
    }
});

// Move to workspace
document.addEventListener('tree-move-conversation', async function(e) {
    var convId = e.detail.conversationId;
    var targetWsId = e.detail.targetWorkspaceId;
    try {
        await API.moveConversationToWorkspace(convId, targetWsId);
        await WorkspaceTree.refreshTree();
        showToast('Conversation moved', 'success');
    } catch (err) {
        showToast('Move failed: ' + err.message, 'error');
    }
});

// Toast helper (dispatched from context menu)
document.addEventListener('tree-toast', function(e) {
    showToast(e.detail.message, e.detail.type || 'info');
});
```

**Backend endpoints used** (all pre-existing):

| Action | Endpoint | Method | Blueprint |
|--------|----------|--------|-----------|
| Clone | `/clone_conversation/<id>` | POST | `conversations_bp` |
| Make stateless | `/make_conversation_stateless/<id>` | DELETE | `conversations_bp` |
| Make stateful | `/make_conversation_stateful/<id>` | PUT | `conversations_bp` |
| Set flag | `/set_flag/<id>/<flag>` | POST | `conversations_bp` |
| Move to workspace | `/move_conversation_to_workspace/<id>` | PUT | `workspaces_bp` |

**Main UI reference**: `interface/workspace-manager.js:buildConversationContextMenu()` (lines 745-826) implements the same 8 items. The extension mirrors this structure using emoji icons (instead of FontAwesome) and CustomEvent dispatching (instead of direct jQuery AJAX calls).

**Acceptance criteria**:
- Right-click on conversation node shows 8-item context menu
- Copy Reference copies `friendly_id` to clipboard (disabled if no friendly_id)
- Open in New Window opens `/interface/<conversation_id>` on main web UI
- Clone creates a duplicate conversation and refreshes tree
- Toggle Stateless switches between stateful/stateless modes
- Set Flag opens color submenu (7 options), applies flag, refreshes tree
- Move to... opens workspace submenu (all workspaces), moves conversation, refreshes tree
- Save and Delete continue working as before
- All actions show toast feedback on success/failure

---

#### Task 6.6: Add attachment context menu on rendered messages

**What**: Add a right-click context menu on rendered PDF badges and image thumbnails in chat messages. Menu items: Download, Promote to Conversation, Promote to Global, Delete. Long-running promotions (15-45s) show toast feedback.

**Files to modify**:
- `extension/sidepanel/sidepanel.js` — Add context menu logic, promotion handlers
- `extension/sidepanel/sidepanel.html` — Add context menu markup
- `extension/sidepanel/sidepanel.css` — Context menu styles

**Details — HTML** (add to `sidepanel.html`):

```html
<!-- Attachment context menu (positioned absolutely, shown on right-click) -->
<div id="attachment-context-menu" class="att-context-menu hidden">
    <div class="att-menu-item" data-action="download">⬇ Download</div>
    <div class="att-menu-item" data-action="promote-conv">📌 Promote to Conversation</div>
    <div class="att-menu-item" data-action="promote-global">🌐 Promote to Global</div>
    <div class="att-menu-divider"></div>
    <div class="att-menu-item att-menu-danger" data-action="delete">🗑 Delete</div>
</div>
```

**Details — sidepanel.js**:

Add context menu handler (delegated from messages container):

```javascript
var _attMenuTarget = null;  // {doc_id, source, name, type, conversationId}

messagesContainer.addEventListener('contextmenu', function(e) {
    var clickable = e.target.closest('.msg-att-clickable');
    if (!clickable) return;
    e.preventDefault();

    var attData = JSON.parse(decodeURIComponent(clickable.getAttribute('data-att') || '{}'));
    if (!attData.doc_id) {
        // Legacy attachment without doc_id — only show download for images
        return;
    }

    _attMenuTarget = {
        doc_id: attData.doc_id,
        source: attData.source,
        name: attData.name,
        type: attData.type,
        conversationId: state.currentConversation?.conversation_id
    };

    var menu = document.getElementById('attachment-context-menu');
    menu.style.left = e.clientX + 'px';
    menu.style.top = e.clientY + 'px';
    menu.classList.remove('hidden');
});

// Close menu on click outside
document.addEventListener('click', function() {
    document.getElementById('attachment-context-menu').classList.add('hidden');
});

// Handle menu item clicks
document.getElementById('attachment-context-menu').addEventListener('click', async function(e) {
    var action = e.target.closest('.att-menu-item')?.getAttribute('data-action');
    if (!action || !_attMenuTarget) return;

    var menu = document.getElementById('attachment-context-menu');
    menu.classList.add('hidden');
    var convId = _attMenuTarget.conversationId;
    var docId = _attMenuTarget.doc_id;

    try {
        switch (action) {
            case 'download':
                var url = await API.downloadDocUrl(convId, docId);
                window.open(url, '_blank');
                break;
            case 'promote-conv':
                showToast('Promoting document... (may take 15-45s)', 'info');
                await API.promoteMessageDoc(convId, docId);
                showToast('Document promoted to conversation', 'success');
                DocsPanel.loadConversationDocs();
                break;
            case 'promote-global':
                showToast('Promoting to global... (may take 15-45s)', 'info');
                await API.promoteToGlobal(convId, docId);
                showToast('Document promoted to global library', 'success');
                DocsPanel.loadGlobalDocs();
                break;
            case 'delete':
                if (!confirm('Delete this document?')) return;
                await API.deleteDocument(convId, docId);
                showToast('Document deleted', 'info');
                DocsPanel.loadConversationDocs();
                break;
        }
    } catch (err) {
        showToast('Action failed: ' + err.message, 'error');
    }
});
```

**Details — CSS** (in `sidepanel.css`):

```css
.att-context-menu {
    position: fixed; z-index: 200; min-width: 200px;
    background: #2a2a2a; border: 1px solid #444; border-radius: 6px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.5); padding: 4px 0;
}
.att-context-menu.hidden { display: none; }
.att-menu-item {
    padding: 8px 16px; cursor: pointer; font-size: 13px; color: #ddd;
}
.att-menu-item:hover { background: rgba(255,255,255,0.1); }
.att-menu-danger { color: #f87171; }
.att-menu-divider { height: 1px; background: #444; margin: 4px 0; }
```

**Note on `data-att` attribute**: The existing `renderMessage()` function already encodes attachment data as `data-att="${encodeURIComponent(JSON.stringify(att))}"` on `.msg-att-clickable` elements. The context menu reads this to get `doc_id`, `source`, `name`, `type`. Attachments without `doc_id` (pre-M6 legacy) will not show the context menu.

**Note on long-running operations**: `promoteMessageDoc` takes 15-45s (creates full DocIndex with FAISS embeddings). The API method uses `timeoutMs: 60000`. A toast with "Promoting document..." shows immediately, replaced by success/failure toast on completion.

**Acceptance criteria**:
- Right-click on any rendered attachment (PDF badge or image thumbnail) with `doc_id` shows context menu
- Download opens doc in new tab
- Promote to Conversation creates full DocIndex (15-45s with toast feedback)
- Promote to Global copies doc to global storage (toast feedback)
- Delete prompts confirmation, removes doc
- Menu closes on outside click
- Menu positions near cursor
- Legacy attachments without `doc_id` do not trigger menu

---

#### Task 6.7: Wiring, integration, and script tags

**What**: Wire all new panels and menus together, add script tags to `sidepanel.html`, update state management, and ensure panels coordinate (only one overlay open at a time).

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Add script tags for new modules, update action bar layout
- `extension/sidepanel/sidepanel.js` — Initialize modules, wire event listeners, coordinate panel state
- `extension/sidepanel/sidepanel.css` — Action bar button styles, ensure overlay panels stack correctly

**Details — sidepanel.html script tags**:

Add before `</body>` (order matters — dependencies first):
```html
<!-- M6: Document management and claims panels -->
<script src="docs-panel.js"></script>
<script src="claims-panel.js"></script>
```

**Details — action bar CSS**:
```css
.action-bar {
    display: flex; gap: 6px; padding: 8px 12px;
    border-bottom: 1px solid var(--border-color, #333);
}
.action-bar button {
    flex: 1; padding: 6px 8px; border: 1px solid #444; border-radius: 4px;
    background: rgba(255,255,255,0.05); color: #ccc; cursor: pointer;
    font-size: 12px; white-space: nowrap;
}
.action-bar button:hover { background: rgba(255,255,255,0.1); }
.action-bar button.active { background: rgba(100,100,255,0.15); border-color: #6666ff; }
```

**Details — panel coordination in sidepanel.js**:
```javascript
// Only one overlay panel open at a time
function closeAllPanels() {
    DocsPanel.hide();
    ClaimsPanel.hide();
    // Settings panel if it exists
    var settingsPanel = document.getElementById('settings-panel');
    if (settingsPanel) settingsPanel.classList.add('hidden');
}

// When opening docs panel, close others
document.getElementById('docs-btn').addEventListener('click', function() {
    var isOpen = !document.getElementById('docs-panel').classList.contains('hidden');
    closeAllPanels();
    if (!isOpen) DocsPanel.show();
});

// When opening claims panel, close others
document.getElementById('claims-btn').addEventListener('click', function() {
    var isOpen = !document.getElementById('claims-panel').classList.contains('hidden');
    closeAllPanels();
    if (!isOpen) ClaimsPanel.show();
});
```

**Details — conversation change hook**:
```javascript
// When user selects a different conversation (from tree or any other trigger),
// update DocsPanel with the new conversation ID:
document.addEventListener('conversation-selected', function(e) {
    // ... existing conversation loading logic ...
    DocsPanel.setConversation(e.detail.conversationId);
});

// Also update when creating new conversation:
function onConversationCreated(conversationId) {
    DocsPanel.setConversation(conversationId);
}
```

**Integration checklist**:
- [x] `DocsPanel.init()` called during sidepanel initialization
- [x] `ClaimsPanel.init()` called during sidepanel initialization
- [x] Docs button toggles docs panel, closes claims panel
- [x] Claims button toggles claims panel, closes docs panel
- [x] Conversation change updates DocsPanel conversation ID
- [x] Attachment context menu wired on messages container
- [x] Context menu items wired for all 8 tree actions
- [x] All 15+ API methods added to api.js
- [x] `uploadPendingPdfs()` renamed to `uploadPendingFiles()` and updated
- [x] `buildDisplayAttachments()` includes doc_id
- [x] Images stored with File object for upload

**Acceptance criteria**:
- All panels, context menus, and API methods work together
- Only one overlay panel open at a time
- Panel state survives conversation switching (docs panel reloads for new conversation)
- No console errors during normal usage
- Extension loads cleanly with all new script tags

---

### Milestone 7: Cleanup and Deprecation

**Goal**: Deprecate `extension_server.py`, delete obsolete docs/tests, update all documentation referencing the legacy server.

**Effort**: 1 day

**Decision log** (from planning session 2026-02-17):
- `extension_server.py` and `extension.py` are **NOT deleted** — deprecation notice only. Deletion deferred to after live validation.
- `extension/EXTENSION_DESIGN.md` (59K) and `extension/reuse_or_build.md` (21K) are **deleted** — superseded by `documentation/features/extension/`.
- `extension/tests/` is **deleted** — tests target deprecated `extension_server.py:5001`.
- **All** docs referencing `extension_server.py` or port 5001 are updated (22+ files), not just the 5 originally planned.
- Historical planning docs get a one-line deprecation header (not rewritten).

#### Task 7.1: Add deprecation notice to extension_server.py

**What**: Add a startup warning that extension_server.py is deprecated.

**Files to modify**:
- `extension_server.py` — Add deprecation warning at startup.

**Details**:
- Log a prominent warning on startup, immediately after `app = Flask(__name__)` or in `if __name__ == '__main__':` block:
  ```python
  logger.warning("=" * 60)
  logger.warning("DEPRECATED: extension_server.py is deprecated.")
  logger.warning("The Chrome extension now uses server.py (port 5000).")
  logger.warning("This server will be removed in a future release.")
  logger.warning("See documentation/features/extension/ for current architecture.")
  logger.warning("=" * 60)
  ```
- Keep it running for backward compatibility during transition.

**Acceptance criteria**:
- Running `python extension_server.py` prints the deprecation banner to stdout/logs.

#### Task 7.2: Delete obsolete files

**What**: Remove pre-unification design docs and the obsolete test suite.

**Files to delete**:
- `extension/EXTENSION_DESIGN.md` (59K) — Pre-unification design doc. Superseded by `documentation/features/extension/extension_implementation.md`.
- `extension/reuse_or_build.md` (21K) — Pre-unification decision analysis. No longer relevant.
- `extension/tests/` (entire directory) — Integration tests targeting `extension_server.py:5001`. Includes:
  - `extension/tests/__init__.py`
  - `extension/tests/README.md`
  - `extension/tests/run_integration_tests.py`
  - `extension/tests/run_tests.sh`
  - `extension/tests/test_extension_api.py`

**Files NOT deleted** (kept for backward compat):
- `extension_server.py` (2,932 lines) — Kept running with deprecation notice. Only imported by itself.
- `extension.py` (2,265 lines) — Contains `ExtensionAuth`, `ExtensionDB`, `ExtensionConversation`. Only imported by `extension_server.py`.

**Acceptance criteria**:
- The 2 doc files and the `extension/tests/` directory no longer exist.
- No other file imports from them (verified: no imports exist).

#### Task 7.3: Update living documentation (substantive edits)

**What**: Update all actively-used documentation that references `extension_server.py`, port 5001, or the old architecture.

**Files to modify** (9 files, substantive rewrites):

| File | Refs | Changes |
|------|------|---------|
| `AGENTS.md` | 2 | Remove `extension_server.py --port 5001` entry point, update file structure to remove `extension_server.py` reference |
| `extension/README.md` | 10 | Rewrite setup/troubleshooting to reference `server.py:5000`. Remove all `extension_server.py` and port 5001 mentions. Update architecture flow, storage, and support sections. |
| `extension/extension_api.md` | 1 | Replace `EXTENSION_PROMPT_ALLOWLIST in extension_server.py` with reference to `endpoints/ext_bridge.py` or equivalent |
| `extension/extension_implementation.md` | 8+ | Update architecture diagram (remove port 5001 box), API client description, prompt/agent allowlist refs, model list refs |
| `extension/REFRESH_APPEND_CONTENT_CONTEXT.md` | 1 | Replace `extension_server.py` reference with `Conversation.py` |
| `documentation/features/extension/extension_implementation.md` | 3+ | Clean up remaining legacy refs from M1-M6 doc updates |
| `documentation/features/file_attachments/file_attachment_preview_system.md` | 4 | Update server logs section, endpoint refs, `ext_chat()` references |
| `documentation/dev/tests/extension_tests_README.md` | 2 | Add note that tests targeted deprecated server; point to new test approach |

**Acceptance criteria**:
- `grep -r 'extension_server' *.md extension/*.md documentation/**/*.md` returns zero hits in living docs (only historical planning docs).
- `grep -r 'port.5001' *.md extension/*.md documentation/**/*.md` returns zero hits in living docs.
- A new developer reading these docs can set up and run the extension against `server.py:5000` without confusion.

#### Task 7.4: Add deprecation headers to historical/planning docs

**What**: Add a one-line deprecation banner to the top of historical planning docs that reference `extension_server.py`. These are point-in-time artifacts — content is NOT rewritten.

**Banner text**:
```markdown
> **⚠️ DEPRECATED**: `extension_server.py` referenced in this document has been deprecated. The Chrome extension now uses `server.py` (port 5000). See `documentation/features/extension/` for current architecture.
```

**Files to modify** (10 files, mechanical one-liner insert):
1. `documentation/planning/plans/extension_backend_unification.plan.md`
2. `documentation/planning/plans/EXTENSION_UNIFICATION_STATUS.md`
3. `documentation/planning/plans/MILESTONE_2_CONTEXT_ANALYSIS.md`
4. `documentation/planning/plans/AUTH_COMPARISON_AND_RECOMMENDATION.md`
5. `documentation/planning/plans/extension_backend_unification_v2.3_file_attachments_update.md`
6. `documentation/planning/plans/custom_scripts_system_20051a23.plan.md`
7. `documentation/planning/plans/custom_scripts_complete_5e7ef9ca.plan.md`
8. `documentation/planning/plans/custom_scripts_system_v2_f4cc006c.plan.md`
9. `documentation/planning/plans/file_attachment_preview_system.plan.md`
10. `documentation/planning/plans/sqlite_migration_auth_adoption.plan.md`

**Acceptance criteria**:
- Each file has the deprecation banner as the first non-empty line (or after the title).

#### Task 7.5: Deferred — Remove extension_server.py (NOT in this milestone)

**What**: Delete `extension_server.py` and `extension.py` entirely once fully validated in production.

**Files to delete (eventually)**:
- `extension_server.py`
- `extension.py`

**Files to preserve**:
- `endpoints/jwt_auth.py` (moved auth logic)
- `endpoints/ext_bridge.py` (bridge endpoints)
- `endpoints/ext_scripts.py`, `ext_workflows.py`, `ext_ocr.py`, `ext_settings.py`

**Note**: Only execute this after live Chrome testing confirms all extension functionality works against `server.py:5000`. No timeline set — depends on validation results.

---

## 7. Execution Order and Dependencies

```
M1.1 (jwt_auth module) ─┐
                         ├─► M1.2 (JWT-aware get_session_identity) ─┐
                         │                                            ├─► M1.2b (auth_required + get_request_keys)
                         │                                            ├─► M1.3 (ext/auth endpoints)
                         │                                            ├─► M1.4 (CORS update)
                         │                                            ├─► M1.5 (selective auth_required on key endpoints)
                         │                                            └─► M1.6 (rate limiting for ext endpoints)
                         │
                         │      ┌── M2.1 (page_context in send_message)
M1.5 ────────────────────┼──────┤── M2.2 (page_context in Conversation.py)
                         │      ├── M2.3 (extension checkbox defaults)
                         │      └── M2.4 (extension images support)
                         │
M1.5 + M2.* ────────────┼──────┬── M3.1 (extension workspace)
                         │      ├── M3.2 (ext/conversations bridge)
                         │      ├── M3.3 (ext/chat bridge + send_message refactor)
                         │      └── M3.4 (migration script)
                         │
M1.5 ────────────────────┼──────┬── M4.1 (scripts)
                         │      ├── M4.2 (workflows)
                         │      ├── M4.3 (OCR)
                         │      ├── M4.4 (settings — extension-scoped, NOT merged with UserDetails)
                         │      ├── M4.5 (models/agents/health)
                         │      ├── M4.6 (memories/PKB bridge)
                         │      └── M4.7 (prompts bridge)
                         │
M3.* + M4.* ─────────────┼──────┬── M5.1 (API base URL)
                         │      ├── M5.2 (streaming parser — optional)
                         │      ├── M5.3 (enriched responses)
                         │      ├── M5.4 (settings panel: domain + workspace dropdowns)
                         │      ├── M5.5 (flat list with workspace filters)
                         │      └── M5.6 (temp/permanent conversation buttons)
                         │
M1.5 + M2.* + M3.* ──────┼──────┬── M6.1 (fix file upload → main backend FastDocIndex)
                         │      ├── M6.2 (add API methods to api.js)
                         │      ├── M6.3 (docs management panel)
                         │      ├── M6.4 (PKB claims panel)
                         │      ├── M6.5 (conversation context menu expansion)
                         │      ├── M6.6 (attachment context menu)
                         │      └── M6.7 (wiring & integration)
                         │
M5.* + M6.* ─────────────└──────┬── M7.1 (deprecation notice)
                                ├── M7.2 (delete obsolete files)
                                ├── M7.3 (update living docs)
                                └── M7.4 (deprecation headers on planning docs)
```

**Recommended implementation order**:
1. M1.1 → M1.2 → M1.2b → M1.3 → M1.4 → M1.6 (auth foundation — most changes are single-file)
2. M1.5 (selective decorator updates for extension-accessible endpoints)
3. M2.1 → M2.2 → M2.3 → M2.4 (page context + images — parallel with M1.5)
4. M3.1 → M3.2 → M3.3 (conversation bridge — M3.3 requires send_message refactor)
5. M4.1–M4.7 (port extension features — all independent, can be parallelized)
6. M3.4 (migration script — run after M3.* is stable)
7. M5.1 → M5.3 (basic client updates — API URL, enriched responses)
8. M5.4 → M5.5 → M5.6 (extension sidebar: settings-based domain/workspace, flat list with filters)
9. M6.1 → M6.2 (fix upload + API methods — foundation for all other M6 tasks)
10. M6.3 + M6.4 (docs panel + claims panel — independent, can be parallel)
11. M6.5 → M6.6 (context menu expansion + attachment context menu)
12. M6.7 (wiring & integration — depends on all M6 tasks)
13. M7.1 (deprecation notice — trivial, first)
14. M7.2 (delete obsolete files — EXTENSION_DESIGN.md, reuse_or_build.md, tests/)
15. M7.3 (update living docs — 9 files, substantive edits)
16. M7.4 (deprecation headers — 10 planning docs, mechanical)
17. M7.5 (deferred — delete extension_server.py + extension.py after live validation)

## 8. Files Created (New)

| File | Purpose |
|------|---------|
| `endpoints/jwt_auth.py` | JWT token generation/verification, `get_email_from_jwt()` helper |
| `endpoints/ext_auth.py` | `/ext/auth/*` login/verify/logout blueprint |
| `endpoints/ext_bridge.py` | `/ext/conversations/*`, `/ext/chat/*`, utility bridges (models/agents/health) |
| `endpoints/ext_scripts.py` | `/ext/scripts/*` custom scripts CRUD blueprint |
| `endpoints/ext_workflows.py` | `/ext/workflows/*` workflows CRUD blueprint |
| `endpoints/ext_ocr.py` | `/ext/ocr` vision OCR blueprint |
| `endpoints/ext_settings.py` | `/ext/settings` extension-specific UI settings (NOT merged with UserDetails) |
| `endpoints/ext_memories.py` | `/ext/memories/*` PKB bridge with response shape translation |
| `endpoints/ext_prompts.py` | `/ext/prompts/*` prompts bridge with allowlist filtering |
| `database/ext_scripts.py` | DB helpers for CustomScripts table in users.db |
| `database/ext_workflows.py` | DB helpers for ExtensionWorkflows table in users.db |
| `scripts/migrate_extension_conversations.py` | One-time migration from extension.db to filesystem conversations |
| `extension/sidepanel/workspace-tree.js` | M5: jsTree workspace sidebar module (~370 lines) |
| `extension/sidepanel/workspace-tree.css` | M5: jsTree dark theme overrides (~100 lines) |
| `extension/sidepanel/docs-panel.js` | M6: Document management panel module — conversation docs + global docs (188 lines) |
| `extension/sidepanel/claims-panel.js` | M6: PKB claims viewer panel module — read-only list, search, filter (136 lines) |

## 9. Files Modified

| File | Changes |
|------|---------|
| `server.py` | Register new blueprints (ext_auth, ext_bridge, ext_scripts, ext_workflows, ext_ocr, ext_settings, ext_memories, ext_prompts), update CORS config |
| `endpoints/session_utils.py` | **Critical**: Make `get_session_identity()` JWT-aware (check Bearer token first, then session). Add `is_jwt_request()` helper. |
| `endpoints/auth.py` | Add `auth_required` decorator (JSON 401 for API endpoints) |
| `endpoints/request_context.py` | Add `get_request_keys()` helper (uses `keyParser({})` for JWT, `keyParser(session)` for web UI). Update `get_state_and_keys()`. |
| `endpoints/conversations.py` | Selective `@auth_required` on key routes, add page_context/images handling in send_message, extension checkbox defaults, extract `_execute_conversation_stream()` shared helper, fix 3 direct `session.get("email")` calls (lines 122, 798, 912) |
| `endpoints/pkb.py` | (Optional) Selective `@auth_required` if extension calls PKB directly instead of through bridge |
| `Conversation.py` | Add page_context extraction and injection in `reply()`, verify multimodal image support |
| `extension/shared/constants.js` | Update default API_BASE URL from 5001 to 5000. (Note: 4 new intra-extension message types already added — `INIT_CAPTURE_CONTEXT`, `SCROLL_CONTEXT_TO`, `GET_CONTEXT_METRICS`, `RELEASE_CAPTURE_CONTEXT` — these are unaffected by backend change.) |
| `extension/sidepanel/sidepanel.html` | Update preset URLs. Add domain dropdown and workspace dropdown to Settings section. Add filter dropdowns above conversation list. Replace single "New Conversation" button with two buttons ("New Chat" + "Quick Chat"). |
| `extension/shared/api.js` | (Phase 2, optional) Update streaming parser for newline-delimited JSON. Add workspace API calls: `getWorkspaces(domain)`, `createConversation(domain, workspaceId, options)` (updated signature). |
| `extension/sidepanel/sidepanel.js` | Handle enriched response features (TLDR, math, slides). Add `loadWorkspacesForSettings()`, `loadConversations()` with domain param, filter/grouping logic in `renderConversationList()`, two creation button handlers. Update Settings save/load to handle `default_domain`, `default_workspace_id`, `default_workspace_name`. M6: Initialize DocsPanel/ClaimsPanel, wire panel toggles, rename `uploadPendingPdfs()` → `uploadPendingFiles()`, update `buildDisplayAttachments()` for doc_id, add attachment context menu handler, add 8 context menu event listeners. |
| `extension/sidepanel/sidepanel.html` | M5: jsTree container, jQuery/jsTree/KaTeX scripts, dual buttons. M6: Add action bar with Docs/Claims buttons, docs-panel div, claims-panel div, attachment-context-menu div, docs-panel.js/claims-panel.js script tags. |
| `extension/sidepanel/sidepanel.css` | Add styles for filter dropdowns, workspace header separators (`.workspace-header`), two-button layout. M6: overlay-panel, collapsible-section, doc-item, claim-card, att-context-menu styles. |
| `extension/sidepanel/workspace-tree.js` | M6: Expand `_contextMenuItems()` from 2 to 8 items. Add `_buildFlagSubmenu()`, `_buildMoveSubmenu()`. Store `_workspaces` during `loadTree()`. Add `data-conversation-friendly-id` to tree nodes. |

## 10. Files Deprecated (Eventually Removed)

| File | Lines | Replacement |
|------|-------|-------------|
| `extension_server.py` | 2681 | `server.py` + new endpoints |
| `extension.py` | 2062 | `endpoints/jwt_auth.py` + `database/ext_*.py` + `endpoints/ext_*.py` |

**Total code eliminated**: ~4700 lines of duplicate backend code.

## 11. Testing Strategy

### Unit Tests
- `endpoints/jwt_auth.py`: Token generation, verification, expiry, invalid token handling.
- `endpoints/session_utils.py`: `get_session_identity()` with JWT Bearer token, with session, with neither, with remember-me (session restored by hook).
- `endpoints/auth.py`: `auth_required` decorator returns JSON 401 (not redirect) for unauthenticated API requests.
- `endpoints/request_context.py`: `get_request_keys()` returns env-only keys for JWT requests, session-overlaid for web UI.
- `endpoints/ext_bridge.py`: Conversation CRUD bridge, chat bridge streaming translation, workspace auto-create.
- `endpoints/ext_memories.py`: Response shape translation from PKB format to extension format.
- `endpoints/ext_prompts.py`: Allowlist filtering.

### Integration Tests
- **Auth precedence**: JWT + remember-me + session interaction — JWT wins when Bearer header present, session/remember-me work when no Bearer header.
- **End-to-end chat**: Extension login → JWT token → create conversation → call `/ext/chat/<id>` with page_context → receive SSE streaming response → verify response includes PKB context.
- **Streaming translation**: Verify main server's newline-delimited JSON is correctly translated to SSE `data: {"chunk": "..."}\n\n` format with proper `{"done": true, "message_id": "..."}` completion signal.
- **Workspace integration**: Extension create conversation → appears in web UI sidebar under "Browser Extension" workspace (workspace_id in `ConversationIdToWorkspaceId`).
- **Cross-UI interaction**: Create conversation via extension → open in web UI → send message via web UI → verify conversation works in both UIs.
- **Web UI regression**: Session auth → all existing routes still work. Remember-me token → session restored correctly.
- **PKB bridge**: Extension JWT auth → `/ext/memories/search` → results match `/pkb/search` results with shape translation.

### Manual Testing
- Install extension, configure to point at port 5000.
- Login via extension popup.
- Create conversation, send message with page context.
- Verify response quality matches web UI (PKB distillation, formatting, TLDR, running summary).
- Send message with images (base64) — verify multimodal handling.
- Verify scripts, workflows, settings still work.
- Verify web UI is completely unaffected.
- Test conversation appearing in both extension and web UI.

### Regression Tests
- Run existing test suites: `python -m pytest truth_management_system/tests/ -v`
- Run extension integration tests: `cd extension/tests && ./run_tests.sh`
- Manually verify all web UI flows (login, chat, PKB, documents, workspaces).

## 12. Estimated Effort

| Milestone | Effort | Risk | Notes |
|-----------|--------|------|-------|
| M1: Dual Auth | 3-5 days | Low-Medium | Much simpler than v1.0 — single-file `get_session_identity()` fix vs 128-route decorator swap. Main risk: auth precedence edge cases with remember-me. |
| M2: Page Context + Images | 2-3 days | Low | Additive changes only. Images may already be supported by Conversation.py multimodal — verify first. |
| M3: Conversation Bridge | 5-7 days | Medium-High | send_message refactor to extract shared helper is the hardest task. Streaming translation adds complexity. |
| M4: Port Features | 3-5 days | Low | Mostly copy+adapt. New tasks 4.6 (memories bridge) and 4.7 (prompts bridge) add ~1 day. |
| M5: Frontend Updates | 4-6 days | Low-Medium | ✅ IMPLEMENTED. jsTree sidebar (workspace-tree.js ~370 lines), KaTeX math rendering, dual conversation buttons, domain/workspace popup settings, DOMAIN_CHANGED message flow. |
| M6: File Attachments + UI Panels | 3-4 days | Low-Medium | ✅ IMPLEMENTED. Zero server code. Fix upload endpoint, add 15 API methods, docs panel (188 lines), claims panel (136 lines), full context menu (8 items), attachment context menu. All client-side. |
| M7: Cleanup | 1 day | Low | ✅ IMPLEMENTED. Deprecation notice on extension_server.py, deleted EXTENSION_DESIGN.md + reuse_or_build.md + extension/tests/, updated 11 living docs, added deprecation headers to 10 planning docs. Code deletion deferred. |
| Integration Testing | 2-3 days | Medium | Cross-UI testing, streaming verification, auth edge cases, file attachment flows. |

**Total estimated**: 23-34 days of focused work (realistic range with all milestones).

**Core implementation** (M1-M5 only, without file attachments): 15-23 days.

### Timeline Summary by Milestone

| Milestone | Tasks | Effort | Key Deliverables |
|-----------|-------|--------|-----------------|
| **M1: Dual Auth System** | 6 tasks | 3-5 days | JWT auth module, JWT-aware `get_session_identity()`, `/ext/auth/*` endpoints, CORS update, selective `@auth_required`, rate limiting |
| **M2: Page Context + Images** | 4 tasks | 2-3 days | Page context in send_message + Conversation.py, extension checkbox defaults, multimodal images support |
| **M3: Conversation Bridge** | 4 tasks | 5-7 days | Extension workspace creation, `/ext/conversations/*` CRUD, `/ext/chat/<id>` bridge with streaming translation, migration script for existing conversations |
| **M4: Extension Features** | 7 tasks | 3-5 days | Scripts CRUD, workflows CRUD, OCR endpoint (gemini-2.5-flash-lite, 8 workers), settings endpoints, models/agents/health utilities, memories/PKB bridge, prompts bridge |
| **M5: Frontend Updates** | 5 tasks | 4-6 days | ✅ IMPLEMENTED — jsTree workspace sidebar (workspace-tree.js), KaTeX math rendering, dual buttons (New Chat + Quick Chat), domain/workspace popup settings, DOMAIN_CHANGED message wiring |
| **M6: File Attachments + UI Panels** | 7 tasks | 3-4 days | ✅ IMPLEMENTED — Fix upload endpoint (FastDocIndex), 15 API methods, docs management panel (conv + global, 188 lines), PKB claims panel (read-only search/filter, 136 lines), full context menu (8 items), attachment context menu (promote/download/delete), wiring with `window.API` global |
| **M7: Cleanup** | 5 tasks | 1 day | ✅ IMPLEMENTED — Deprecation notice on `extension_server.py`, deleted `EXTENSION_DESIGN.md` + `reuse_or_build.md` + `extension/tests/`, updated 11 living docs, added deprecation header to 10 planning docs. Code deletion deferred to after live validation. |
| **Integration Testing** | — | 2-3 days | Auth precedence, end-to-end chat, streaming translation, workspace integration, cross-UI interaction, PKB bridge, regression tests |

**Critical path**: M1 → M2 → M3 → M4 → M5 (15-23 days for core functionality). M6 depends on M1+M3+M5 (jsTree context menu expansion).

**Total with all milestones + testing**: 21-32 days.

## 13. Phase 1 Non-Goals (Explicitly Deferred)

These items are explicitly out of scope for Phase 1:

1. **Extension JS streaming parser rewrite**: Phase 1 uses SSE bridge translation. Phase 2 can update extension JS to parse newline-delimited JSON directly, eliminating the bridge layer.
2. **Merge extension settings with UserDetails**: Extension settings and main server user preferences are complementary. No merge in Phase 1.
3. **Phase 2/3 UI consolidation**: Bringing the extension UI closer to the main web UI in terms of chat rendering (MathJax → KaTeX done, code execution, mermaid diagrams) is a separate effort. jsTree workspace sidebar has been implemented in M5.
4. **Client-side capture features**: Inner scroll container detection, pipelined capture+OCR, and content viewer are already implemented client-side and function correctly with any backend that exposes `/ext/ocr`. No changes needed for backend unification — these features are preserved as-is.
5. **Hierarchical workspace advanced features**: Phase 1 implemented basic jsTree sidebar with view/select/create/delete plus full context menu (M6). Advanced features (drag-and-drop reordering, workspace renaming, nested workspace creation) are deferred to Phase 2.
6. **PDF viewer in extension**: Documents can be downloaded but not previewed inline. Extension's limited screen space makes a PDF viewer impractical. Users can use the main web UI for viewing.
7. **PKB claim CRUD in extension**: Claims panel is read-only (list, search, filter). Creating, editing, and deleting claims is done via the main web UI. Extension supports `@reference` syntax in messages for claim usage.
8. **Global docs `#gdoc_N` reference display**: While docs are listed in the docs panel, the `#gdoc_N` reference syntax for use in messages is not prominently displayed. Users familiar with the syntax can use it.

---

*Plan Version: 3.4*
*Created: 2026-02-13*
*Revised: 2026-02-17*
*Status: Complete (M1-M7 All Implemented — Pending Live Chrome Validation)*
