---
name: Extension Backend Unification (Phase 1)
overview: >
  Deprecate extension_server.py by migrating its functionality into the main server.py.
  The Chrome extension will use the main server as its backend, gaining full Conversation.py
  pipeline benefits (PKB distillation, agents, math formatting, TLDR) while
  eliminating ~4700 lines of duplicate backend code. Extension-specific features (scripts,
  workflows, OCR, page context, memories bridge, prompts bridge) are ported as new
  endpoints/modules in the main server. Document upload support for the extension is
  deferred to Phase 2 (extension currently has no UI for it). Extension sidebar will be
  converged to use jsTree workspace hierarchy matching the main UI, with domain switching
  and separate temporary/permanent conversation creation.
status: planning
created: 2026-02-13
revised: 2026-02-14
---

# Extension Backend Unification — Phase 1 Plan

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

## 1. Problem Statement

The Chrome extension currently runs against a **separate Flask server** (`extension_server.py`, port 5001) with its own conversation engine, storage, and auth system. This creates significant problems:

- **Duplicate code**: ~4700 lines across `extension_server.py` (2681) + `extension.py` (2062) reimplementing conversation management, auth, LLM calls, PKB access, and agent instantiation.
- **Degraded experience**: Extension's chat pipeline (`ext_chat()`) manually builds messages and calls `call_llm()` directly, bypassing `Conversation.py`'s rich pipeline. Extension users miss: PKB distillation with `@reference` resolution, running summaries, math formatting, TLDR auto-summary, document ingestion, memory pad, cross-conversation references, reward system, and code execution.
- **Operational overhead**: Two Flask processes to deploy, monitor, and maintain. Two sets of CORS configs, two auth systems, two conversation storages.
- **Divergent feature sets**: Features added to the main server never reach the extension and vice versa.

## 2. Goals

1. **Single backend**: Extension calls `server.py` (port 5000) instead of `extension_server.py` (port 5001).
2. **Full Conversation.py pipeline**: Extension chat uses the same pipeline as `/send_message/<conversation_id>` with page-context support, giving users the full main-app experience (PKB distillation, agents, math formatting, TLDR, running summaries, cross-conversation references, reward system).
3. **Unified conversation storage**: Extension conversations use the main filesystem-based conversation system (with a dedicated "Browser Extension" workspace per user). Extension-specific data (scripts, workflows, extension UI settings) migrates from `extension.db` to tables in `users.db`. The `extension.db` file is eventually eliminated.
4. **JWT auth coexistence**: Main server accepts both session cookies (web UI) and JWT Bearer tokens (extension). Identity resolution via `get_session_identity()` is made JWT-aware so all existing endpoint code works without mass edits.
5. **Extension-specific features preserved**: Scripts, workflows, OCR, page context, extension settings, memory/PKB browsing, and prompt access are ported to the main server as new blueprints/modules.
6. **Zero regression for web UI**: All existing web UI behavior remains unchanged, including remember-me tokens and session-based auth.
7. **Document upload deferred**: Extension currently has no document upload UI. Extension users can attach base64 images in chat (supported by Conversation.py multimodal). Full document upload is a Phase 2 enhancement.

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

### Milestone 1: Dual Auth (JWT + Session) on Main Server

**Goal**: Extension can authenticate against the main server via JWT tokens. All existing endpoints work for JWT-authenticated requests through a JWT-aware `get_session_identity()` without mass decorator replacement.

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

### Milestone 5: Extension Client Updates

**Goal**: Update extension JS to point at the main server, handle payload/format differences, replace the flat conversation list with a jsTree-based workspace hierarchy matching the main UI, add domain switching, and add separate temporary/permanent conversation creation buttons.

#### Task 5.1: Update extension API base URL default

**What**: Change the default server URL from `http://localhost:5001` to `http://localhost:5000`.

**Files to modify**:
- `extension/shared/constants.js` — Update `API_BASE` default.
- `extension/sidepanel/sidepanel.html` — Update "Use Local" preset URL.
- `extension/popup/popup.html` — Update any server URL references.

**Details**:
- Change `API_BASE` from `http://localhost:5001` to `http://localhost:5000`.
- Update hosted preset from `https://assist-chat.site` to whatever the production URL is (likely same since nginx proxies both).
- Keep the "Use Local" button but change port from 5001 to 5000.

**Acceptance criteria**:
- Extension connects to port 5000 by default.
- Users can still override via settings.

#### Task 5.2: Adapt streaming parser (if not using SSE bridge)

**What**: If we decide to have the extension call `/send_message/<id>` directly (skipping the `/ext/chat/<id>` bridge), update the streaming parser.

**Files to modify**:
- `extension/shared/api.js` — Update `stream()` method.

**Details**:
- Current extension parser expects SSE: `data: {"chunk": "..."}\n\n`
- Main server sends newline-delimited JSON: `{"text": "...", "status": "..."}\n`
- Update `stream()` to detect format and parse accordingly:
  ```javascript
  for (const line of lines) {
      if (!line.trim()) continue;
      try {
          const data = JSON.parse(line);
          if (data.text && onChunk) onChunk(data.text);
          // ... handle status, message_ids, done
      } catch (e) {
          // Try SSE format as fallback
          if (line.startsWith('data: ')) { ... }
      }
  }
  ```

**Note**: This task is optional if we use the SSE bridge in Task 3.3. Recommended to defer until Phase 2 when the bridge is removed.

**Acceptance criteria**:
- Extension can parse streaming responses from the main server.
- Markdown rendering, syntax highlighting still work.

#### Task 5.3: Handle enriched response features

**What**: The main server's responses include features the extension UI doesn't currently handle (TLDR, math formatting, multi-model tabs, slide presentations). Ensure graceful handling.

**Files to modify**:
- `extension/sidepanel/sidepanel.js` — Update message rendering.

**Details**:
- TLDR: The `<details>` block with TLDR will render as HTML in marked.js output. Should work automatically.
- Math: `\\[` and `\\(` blocks will appear in text. Without MathJax, they'll show as raw LaTeX. This is acceptable for Phase 1. Phase 2 can add KaTeX.
- Slides: `<slide-presentation>` tags will appear as raw text. Acceptable for Phase 1.
- Multi-model `<details>` blocks: Will render as collapsible sections via marked.js. Should work.
- Status messages: The extension should skip/hide status-only chunks (`text: ""` with `status` set).

**Acceptance criteria**:
- Extension doesn't crash on enriched responses.
- TLDR sections render as collapsible blocks.
- Math/slides degrade gracefully (shown as text).

#### Task 5.4: Replace flat conversation list with jsTree workspace hierarchy

**What**: Replace the extension's flat `<ul id="conversation-list">` sidebar with a jsTree-based hierarchical workspace+conversation tree, matching the main UI's design. This gives extension users the same folder-like workspace browsing experience.

**Current extension sidebar** (`extension/sidepanel/sidepanel.html:76-94`, `extension/sidepanel/sidepanel.js`):
- `<aside id="sidebar">` containing `<ul id="conversation-list">` populated by `renderConversationList()`
- Flat list of `<li>` items with title, time, save/delete buttons
- Key functions: `loadConversations()`, `renderConversationList()`, `selectConversation()`, `createNewConversation()`, `deleteConversation()`, `saveConversation()`
- API calls: `API.getConversations()`, `API.createConversation()`, etc.

**Target**: Same jsTree-based structure as `interface/workspace-manager.js` (1078 lines), adapted for the extension's vanilla JS environment (no jQuery in extension).

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Replace sidebar HTML structure, add jsTree CSS/JS CDN links.
- `extension/sidepanel/sidepanel.js` — Replace `loadConversations()` / `renderConversationList()` with jsTree-based workspace tree.
- `extension/sidepanel/sidepanel.css` — Add jsTree workspace tree styles (adapt from `interface/workspace-styles.css`).
- `extension/shared/api.js` — Add workspace API calls: `getWorkspaces(domain)`, `createWorkspace(domain, name, color, parentId)`, `moveConversationToWorkspace(convId, wsId)`.

**Details**:
- **jsTree integration**: Include jsTree 3.3.17 via CDN in sidepanel.html. Note: jsTree requires jQuery — either include jQuery for the sidepanel or find a lightweight tree alternative. Since the main UI already uses jQuery+jsTree, including them in the extension sidepanel maintains consistency.
- **Workspace tree rendering**:
  - On load: fetch `GET /ext/workspaces/<domain>` + `GET /ext/conversations` in parallel.
  - Build jsTree data structure matching `buildJsTreeData()` from `interface/workspace-manager.js`:
    - Workspace nodes: `{id: 'ws_'+id, parent: parentWsId ? 'ws_'+parentWsId : '#', type: 'workspace', text: name}`
    - Conversation nodes: `{id: 'cv_'+id, parent: 'ws_'+wsId, type: 'conversation', text: title}`
  - Initialize jsTree with same plugins: `['types', 'wholerow', 'contextmenu', 'sort']`
  - Apply same dark theme styles from `interface/workspace-styles.css` (adapted for extension dimensions).
- **Context menus**: Right-click on workspaces → New Conversation, New Sub-Workspace, Rename, Move to, Delete. Right-click on conversations → Move to, Delete, Toggle Stateless.
- **Conversation selection**: Clicking a conversation node → loads messages, updates chat area (same as current `selectConversation()`).
- **Workspace color indicators**: Same as main UI — `border-left: 3px solid {color}`.
- **Mobile handling**: Extension sidepanel is already a narrow panel; adapt the mobile touch handlers from `workspace-manager.js`.

**Implementation approach**: Create a new `extension/sidepanel/workspace-tree.js` module that encapsulates the jsTree logic, keeping it separate from the main chat logic in `sidepanel.js`. This module mirrors `interface/workspace-manager.js` structure but adapted for the extension context.

**Acceptance criteria**:
- Extension sidebar shows hierarchical workspace tree matching main UI style.
- Workspaces expand/collapse with persistence.
- Context menus work for workspace and conversation management.
- Conversation selection loads messages correctly.
- Same workspaces visible in both extension and main web UI.

#### Task 5.5: Add domain selector to extension settings/UI

**What**: Allow extension users to switch between the 3 domains (`assistant`, `search`, `finchat`), which reloads the sidebar workspace tree and conversation list for that domain.

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Add domain selector UI element.
- `extension/sidepanel/sidepanel.js` — Handle domain switching.
- `extension/sidepanel/workspace-tree.js` (NEW) — Reload tree on domain change.
- `extension/shared/api.js` — Pass domain to workspace/conversation listing calls.

**Details**:
- **UI placement**: Add a domain selector as either:
  - A dropdown/tabs at the top of the sidebar (above the workspace tree), or
  - A setting in the extension settings panel.
  - Recommended: Small tab bar or segmented control at the top of the sidebar for quick switching, similar to the main UI's Bootstrap tabs.
- **Domain state**: Store active domain in `ExtensionSettings.settings_json` (persisted via `PUT /ext/settings`). Default: `assistant`.
- **Domain switching behavior**:
  1. User clicks a domain tab/selector.
  2. Active domain updated in settings.
  3. Workspace tree reloads: calls `GET /ext/workspaces/<new_domain>` + `GET /ext/conversations` (filtered by domain).
  4. Previous domain's tree state is not lost — workspace `expanded` state is persisted server-side.
- **Domain-specific behavior**:
  - `search` domain: conversations auto-created as stateless (matching main UI `workspace-manager.js:236`).
  - `finchat` domain: standard behavior.
  - `assistant` domain: standard behavior (default).
- **Three domains**: `assistant` (displayed as "Assistant"), `search` (displayed as "Search"), `finchat` (displayed as "Finance").

**Acceptance criteria**:
- Extension shows domain selector.
- Switching domain reloads sidebar with correct workspaces/conversations.
- Active domain is persisted across extension reopens.
- Domain-specific behaviors (e.g., search auto-stateless) work correctly.

#### Task 5.6: Add temporary and permanent conversation creation buttons

**What**: Replace the single "New Chat" button with two buttons: one for temporary (stateless) conversations and one for permanent (stored) conversations, allowing the user to choose before creating.

**Current state**: Extension has a single `createNewConversation()` function that creates temporary conversations by default. Saving is done retroactively via a "Save" button on the conversation item.

**Files to modify**:
- `extension/sidepanel/sidepanel.html` — Add two buttons to sidebar header or toolbar.
- `extension/sidepanel/sidepanel.js` — Wire up handlers for both creation modes.
- `extension/sidepanel/workspace-tree.js` (NEW) — Handle conversation creation in workspace context.

**Details**:
- **Two buttons in sidebar toolbar**:
  1. **"New Chat" (permanent)** — icon: `fa-file-o` or `+` icon. Creates a conversation in the currently selected workspace (or default). NOT stateless. This is for conversations the user wants to keep.
  2. **"Quick Chat" (temporary)** — icon: `fa-eye-slash` or ephemeral icon. Creates a stateless conversation in the default workspace of the active domain. Matches the `#new-temp-chat` button behavior in the main UI (`interface/workspace-manager.js:1007-1025`).
- **Creation flow for permanent conversation**:
  1. Determine target workspace: selected workspace in tree, or "Browser Extension" workspace, or default.
  2. `POST /ext/conversations` with `{domain: activeDomain, workspace_id: targetWsId, is_temporary: false}`.
  3. Reload tree, highlight new conversation.
- **Creation flow for temporary conversation**:
  1. Always use default workspace of active domain.
  2. `POST /ext/conversations` with `{domain: activeDomain, is_temporary: true}`.
  3. Mark as stateless: `POST /make_conversation_stateless/<id>` (or set via bridge).
  4. Reload tree, highlight new conversation.
  5. Note: Temporary conversations are cleaned up when listed (matching main server behavior in `list_conversation_by_user`).
- **Retroactive save**: Keep the existing "Save" button on temporary conversations that calls `POST /ext/conversations/<id>/save` to convert to permanent.

**Acceptance criteria**:
- Two distinct buttons for creating temporary and permanent conversations.
- Permanent conversations persist across sessions and appear in main web UI.
- Temporary conversations are auto-cleaned on next listing.
- User can convert temporary to permanent via save button.

---

### Milestone 6: Cleanup and Deprecation

**Goal**: Remove `extension_server.py` and `extension.py` from active use.

#### Task 6.1: Add deprecation notice to extension_server.py

**What**: Add a startup warning that extension_server.py is deprecated.

**Files to modify**:
- `extension_server.py` — Add deprecation warning at startup.

**Details**:
- Log a prominent warning on startup:
  ```python
  logger.warning("=" * 60)
  logger.warning("DEPRECATED: extension_server.py is deprecated.")
  logger.warning("The Chrome extension should use server.py (port 5000) instead.")
  logger.warning("This server will be removed in a future release.")
  logger.warning("=" * 60)
  ```
- Keep it running for backward compatibility during transition.

#### Task 6.2: Update documentation

**What**: Update all extension documentation to reflect the new architecture.

**Files to modify**:
- `extension/README.md` — Update backend setup instructions.
- `extension/EXTENSION_DESIGN.md` — Mark as partially outdated, reference new architecture.
- `extension/reuse_or_build.md` — Mark as outdated.
- `extension/extension_api.md` — Update endpoint documentation.
- `AGENTS.md` — Update extension server instructions.

**Acceptance criteria**:
- New developer can set up and run the extension against the main server using only the docs.

#### Task 6.3: Remove extension_server.py (final step, after validation)

**What**: Delete `extension_server.py` and the extension-specific parts of `extension.py` once fully validated.

**Files to delete (eventually)**:
- `extension_server.py`
- `extension.py` (or reduce to shared utilities only)

**Files to preserve**:
- `endpoints/jwt_auth.py` (moved auth logic)
- `endpoints/ext_bridge.py` (bridge endpoints)
- `endpoints/ext_scripts.py`, `ext_workflows.py`, `ext_ocr.py`, `ext_settings.py`

**Note**: Only execute this after at least 2 weeks of running both systems in parallel with the extension pointing at the main server.

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
                         │      ├── M5.4 (jsTree workspace sidebar — requires M3.1 workspaces)
                         │      ├── M5.5 (domain selector — requires M5.4)
                         │      └── M5.6 (temp/permanent conversation buttons — requires M5.4)
                         │
M5.* ────────────────────└──────┬── M6.1 (deprecation notice)
                                ├── M6.2 (documentation)
                                └── M6.3 (removal — deferred)
```

**Recommended implementation order**:
1. M1.1 → M1.2 → M1.2b → M1.3 → M1.4 → M1.6 (auth foundation — most changes are single-file)
2. M1.5 (selective decorator updates for extension-accessible endpoints)
3. M2.1 → M2.2 → M2.3 → M2.4 (page context + images — parallel with M1.5)
4. M3.1 → M3.2 → M3.3 (conversation bridge — M3.3 requires send_message refactor)
5. M4.1–M4.7 (port extension features — all independent, can be parallelized)
6. M3.4 (migration script — run after M3.* is stable)
7. M5.1 → M5.3 (basic client updates — API URL, enriched responses)
8. M5.4 → M5.5 → M5.6 (extension sidebar overhaul — jsTree, domains, temp/permanent buttons)
9. M5.2 (streaming parser — optional, defer to Phase 2)
10. M6.1–M6.3 (cleanup)

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
| `extension/sidepanel/sidepanel.html` | Update preset URLs |
| `extension/shared/api.js` | (Phase 2, optional) Update streaming parser for newline-delimited JSON. Add workspace API calls: `getWorkspaces(domain)`, `createWorkspace()`, `moveConversationToWorkspace()`. |
| `extension/sidepanel/sidepanel.js` | Handle enriched response features (TLDR, math, slides). Wire up domain selector and temp/permanent buttons. Replace flat conversation list with jsTree workspace tree. |
| `extension/sidepanel/sidepanel.html` | Replace sidebar HTML: add jsTree CDN, domain selector tabs, two creation buttons (New Chat + Quick Chat), workspace tree container. |
| `extension/sidepanel/sidepanel.css` | Add jsTree workspace tree styles (adapted from `interface/workspace-styles.css`). |
| `extension/sidepanel/workspace-tree.js` | **NEW**: Extension workspace tree module — jsTree init, workspace CRUD, context menus, domain switching, conversation selection. Mirrors `interface/workspace-manager.js` adapted for extension. |

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
| M1: Dual Auth | 2–3 days | Low-Medium | Much simpler than v1.0 — single-file `get_session_identity()` fix vs 128-route decorator swap. Main risk: auth precedence edge cases with remember-me. |
| M2: Page Context + Images | 2–3 days | Low | Additive changes only. Images may already be supported by Conversation.py multimodal — verify first. |
| M3: Conversation Bridge | 4–5 days | Medium-High | send_message refactor to extract shared helper is the hardest task. Streaming translation adds complexity. |
| M4: Port Features | 4–5 days | Low | Mostly copy+adapt. New tasks 4.6 (memories bridge) and 4.7 (prompts bridge) add ~1 day. |
| M5: Client Updates | 4–6 days | Medium | URL change is trivial, but jsTree sidebar conversion (Task 5.4) is substantial — mirrors 1078 lines of workspace-manager.js. Domain selector + temp/permanent buttons add ~1-2 days. |
| M6: Cleanup | 1 day | Low | Documentation + deprecation notice. |
| Integration Testing | 1–2 days | Medium | Cross-UI testing, streaming verification, auth edge cases. |

**Total estimated**: 19–27 days of focused work.

## 13. Phase 1 Non-Goals (Explicitly Deferred)

These items are explicitly out of scope for Phase 1:

1. **Document upload for extension**: Extension has no document upload UI. Base64 images in chat work through Conversation.py multimodal. Full document upload (multipart form data) is Phase 2.
2. **Extension JS streaming parser rewrite**: Phase 1 uses SSE bridge translation. Phase 2 can update extension JS to parse newline-delimited JSON directly, eliminating the bridge layer.
3. **Merge extension settings with UserDetails**: Extension settings and main server user preferences are complementary. No merge in Phase 1.
4. **Phase 2/3 UI consolidation**: Bringing the extension UI closer to the main web UI in terms of chat rendering (MathJax, code execution, mermaid diagrams) is a separate effort. Phase 1 only converges the sidebar/workspace UI.
5. **Client-side capture features**: Inner scroll container detection, pipelined capture+OCR, and content viewer are already implemented client-side and function correctly with any backend that exposes `/ext/ocr`. No changes needed for backend unification — these features are preserved as-is.

---

*Plan Version: 2.3*
*Created: 2026-02-13*
*Revised: 2026-02-14*
*Status: Planning*
