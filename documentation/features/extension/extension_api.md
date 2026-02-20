# Extension Server API Reference (Compact)

**Base URL:** `http://localhost:5000` • **Content-Type:** `application/json` • **Auth:** `Authorization: Bearer <token>` (all endpoints except `/ext/health` and `/ext/auth/login`)

## Endpoint Index

| Category | Method | Path |
|---------|--------|------|
| Auth | POST | `/ext/auth/login` |
| Auth | POST | `/ext/auth/logout` |
| Auth | POST | `/ext/auth/verify` |
| Prompts (RO) | GET | `/ext/prompts` |
| Prompts (RO) | GET | `/ext/prompts/<prompt_name>` |
| Memories (RO) | GET | `/ext/memories` |
| Memories (RO) | POST | `/ext/memories/search` |
| Memories (RO) | GET | `/ext/memories/<claim_id>` |
| Memories (RO) | GET | `/ext/memories/pinned` |
| Conversations | GET | `/ext/conversations` |
| Conversations | POST | `/ext/conversations` |
| Conversations | GET | `/ext/conversations/<conversation_id>` |
| Conversations | PUT | `/ext/conversations/<conversation_id>` |
| Conversations | DELETE | `/ext/conversations/<conversation_id>` |
| Conversations | POST | `/ext/conversations/<conversation_id>/save` |
| Chat | POST | `/ext/chat/<conversation_id>` |
| Chat | POST | `/ext/chat/<conversation_id>/message` |
| Chat | DELETE | `/ext/chat/<conversation_id>/messages/<message_id>` |
| Settings | GET | `/ext/settings` |
| Settings | PUT | `/ext/settings` |
| Utility | GET | `/ext/models` |
| Utility | GET | `/ext/health` |
| Custom Scripts | GET | `/ext/scripts` |
| Custom Scripts | POST | `/ext/scripts` |
| Custom Scripts | GET | `/ext/scripts/<script_id>` |
| Custom Scripts | PUT | `/ext/scripts/<script_id>` |
| Custom Scripts | DELETE | `/ext/scripts/<script_id>` |
| Custom Scripts | GET | `/ext/scripts/for-url` |
| Custom Scripts | POST | `/ext/scripts/<script_id>/toggle` |
| Custom Scripts | POST | `/ext/scripts/generate` |
| Custom Scripts | POST | `/ext/scripts/validate` |

## Common Error Format

`{"error": "Error message description"}`

Common HTTP codes: `400` bad request • `401` unauthorized • `404` not found • `500` server error • `503` unavailable

## Auth

### POST `/ext/auth/login`
- **Auth**: none
- **Request**: `{ "email": string, "password": string }`
- **Response**: `{ "token": string, "email": string, "name": string }`
- **Errors**: `400` missing fields, `401` invalid credentials

### POST `/ext/auth/logout`
- **Auth**: required
- **Response**: `{ "message": "Logged out successfully" }`

### POST `/ext/auth/verify`
- **Auth**: required
- **Response (valid)**: `{ "valid": true, "email": string }`
- **Response (invalid)**: `{ "valid": false, "error": string }`

## Prompts (Read-Only)

### GET `/ext/prompts`
- **Response**: `{ "prompts": [ { "name": string, "description": string, "category": string }, ... ] }`

### GET `/ext/prompts/<prompt_name>`
- **Response**: `{ "name": string, "content": string, "raw_content": string, "description": string, "category": string, "tags": [] }`
- **Errors**: `404` prompt not found, `503` prompt library unavailable

## Memories / PKB (Read-Only)

### GET `/ext/memories`
- **Query**: `limit:int=50`, `offset:int=0`, `status:string="active"`, `claim_type:string|null`
- **Response**: `{ "memories": [ { "claim_id": string, "user_email": string, "claim_type": string, "statement": string, "context_domain": string, "status": string, "confidence": number, "created_at": string, "updated_at": string }, ... ], "total": number }`

### POST `/ext/memories/search`
- **Request**: `{ "query": string, "k": number, "strategy": "hybrid" }`
- **Response**: `{ "results": [ { "claim": object, "score": number }, ... ] }`

### GET `/ext/memories/<claim_id>`
- **Response**: `{ "memory": object }`
- **Errors**: `404` not found

### GET `/ext/memories/pinned`
- **Response**: `{ "memories": array }`

## Conversations

### GET `/ext/conversations`
- **Query**: `limit:int=50`, `offset:int=0`, `include_temporary:bool=true`
- **Response**: `{ "conversations": [ { "conversation_id": string, "title": string, "is_temporary": bool, "model": string, "prompt_name": string|null, "history_length": number, "created_at": string, "updated_at": string }, ... ], "total": number }`

### POST `/ext/conversations`
- **Note**: by default deletes all temporary conversations before creating a new one.
- **Request**: `{ "title": string="New Chat", "is_temporary": bool=true, "model": string="openai/gpt-4o-mini", "prompt_name": string|null, "history_length": number=10, "delete_temporary": bool=true }`
- **Response**: `{ "conversation": object, "deleted_temporary": number }`

### GET `/ext/conversations/<conversation_id>`
- **Response**: `{ "conversation": { "conversation_id": string, "title": string, "messages": [ { "message_id": string, "role": string, "content": string, "page_context": object|null, "created_at": string }, ... ], ... } }`
- **Errors**: `404` not found

### PUT `/ext/conversations/<conversation_id>`
- **Request**: partial update allowed (e.g. `{ "title": string, "is_temporary": bool, "model": string, "history_length": number }`)
- **Response**: `{ "conversation": object }`
- **Errors**: `404` not found

### DELETE `/ext/conversations/<conversation_id>`
- **Response**: `{ "message": "Deleted successfully" }`
- **Errors**: `404` not found

### POST `/ext/conversations/<conversation_id>/save`
- **Response**: `{ "conversation": { "is_temporary": false, ... }, "message": "Conversation saved" }`
- **Errors**: `404` not found, `500` save failed

## Chat

### POST `/ext/chat/<conversation_id>`
- **Request**: `{ "message": string, "page_context": { "url": string, "title": string, "content": string }|null, "model": string, "stream": bool }`
- **Response (non-streaming)**: `{ "response": string, "message_id": string, "user_message_id": string }`
- **Response (streaming)**: Server-Sent Events with `data: {"chunk": "..."}` and final `data: {"done": true, "message_id": "..."}`.
- **Errors**: `400` message required, `404` conversation not found, `503` LLM unavailable

### POST `/ext/chat/<conversation_id>/message`
- **Request**: `{ "role": string, "content": string, "page_context": object|null }`
- **Response**: `{ "message": { "message_id": string, "role": string, "content": string, "created_at": string } }`

### DELETE `/ext/chat/<conversation_id>/messages/<message_id>`
- **Response**: `{ "message": "Deleted successfully" }`
- **Errors**: `404` not found

## Settings

### GET `/ext/settings`
- **Response**: `{ "settings": { "default_model": string, "default_prompt": string, "history_length": number, "auto_save_conversations": bool, "theme": string } }`

### PUT `/ext/settings`
- **Request**: partial update allowed (e.g. `{ "default_model": string, "history_length": number }`)
- **Response**: `{ "settings": object }`

## Utility

### GET `/ext/models`
- **Response**: `{ "models": [ { "id": string, "name": string, "provider": string }, ... ] }`

### GET `/ext/health`
- **Auth**: none
- **Response**: `{ "status": "healthy", "services": { "prompt_lib": bool, "pkb": bool, "llm": bool }, "timestamp": string }`

## Custom Scripts

### GET `/ext/scripts`
- **Query**: `enabled_only:bool=false`
- **Response**: `{ "scripts": [ { "script_id": string, "name": string, "description": string|null, "script_type": "functional"|"parsing", "match_patterns": string[], "match_type": "glob"|"regex", "enabled": bool, "version": number, "created_at": string, "updated_at": string }, ... ] }`

### POST `/ext/scripts`
- **Request**: `{ "name": string, "description": string|null, "script_type": "functional"|"parsing", "match_patterns": string[], "match_type": "glob"|"regex", "code": string, "actions": array }`
- **Response**: `{ "script": object }`

### GET `/ext/scripts/<script_id>`
- **Response**: `{ "script": { "script_id": string, "name": string, "code": string, "actions": array, ... } }`

### PUT `/ext/scripts/<script_id>`
- **Request**: partial update supported (e.g. `{ "name": string, "code": string, "enabled": bool }`)
- **Response**: `{ "script": object }`

### DELETE `/ext/scripts/<script_id>`
- **Response**: `{ "message": "Script deleted successfully" }`

### GET `/ext/scripts/for-url`
- **Query**: `url:string` (required)
- **Response**: `{ "scripts": [ { "script_id": string, "name": string, "code": string, "actions": array, ... }, ... ] }`

### POST `/ext/scripts/<script_id>/toggle`
- **Response**: `{ "script": object, "enabled": bool }`

### POST `/ext/scripts/generate`
- **Request**: `{ "description": string, "page_url": string, "page_html": string, "page_context": object, "refinement": string|null }`
- **Response**: `{ "script": { "name": string, "description": string, "match_patterns": string[], "script_type": string, "code": string, "actions": array }, "explanation": string }`
- **Errors**: `400` description required, `503` LLM unavailable

### POST `/ext/scripts/validate`
- **Request**: `{ "code": string }`
- **Response (valid)**: `{ "valid": true }`
- **Response (invalid)**: `{ "valid": false, "error": string }`

## Custom Scripts Runtime Notes (Important)

Scripts execute via a sandboxed extension page for CSP safety:
- **No direct DOM access** in user scripts (`document`, `querySelector`, etc.).
- Use `aiAssistant.dom.*` instead (content script performs DOM interactions safely).
- Common helpers: `click`, `setValue` (dispatches `input`/`change`), `type({ clearFirst, delayMs })`, `hide`, `remove`.

## Example Flow (Compact)

1) `POST /ext/auth/login` → store `token`  
2) `POST /ext/conversations` → get `conversation_id`  
3) `POST /ext/chat/<conversation_id>` (optionally `stream:true`)  
4) `GET /ext/conversations/<conversation_id>` to retrieve full messages  
5) `POST /ext/auth/logout` (client clears token)

---

## Main Backend Endpoints Used by Extension (M1-M5)

After backend unification (M1+), the extension calls these main server endpoints directly in addition to the `/ext/*` endpoints above.

### Workspaces (M5)

#### GET `/list_workspaces/<domain>`
- **Auth**: required (JWT)
- **Response**: `[{ "workspace_id": string, "workspace_name": string, "workspace_color": string, "parent_workspace_id": string|null, "domain": string, "expanded": bool }]`

#### POST `/create_workspace/<domain>/<workspace_name>`
- **Auth**: required (JWT)
- **Request**: `{ "workspace_color": string }` (e.g., `"#9b59b6"` for purple)
- **Response**: `{ "workspace_id": string, "workspace_name": string, "workspace_color": string, "parent_workspace_id": null }`

### Conversations (M3+M5)

#### POST `/create_conversation/<domain>/<workspace_id>`
- **Auth**: required (JWT)
- **Request**: `{ "name": string }` (optional, default: "New Conversation")
- **Response**: `{ "conversation_id": string, "title": string, "last_updated": string, ... }`
- **Note**: Creates a permanent conversation in the specified workspace.

#### POST `/create_temporary_conversation/<domain>`
- **Auth**: required (JWT)
- **Request**: `{ "workspace_id": string }`
- **Response**: `{ "conversation": object, "conversations": array, "workspaces": array }`
- **Note**: Atomic endpoint — creates temp conversation and returns updated lists. Used by "Quick Chat" button.

#### GET `/list_conversation_by_user/<domain>`
- **Auth**: required (JWT)
- **Response**: `[{ "conversation_id": string, "title": string, "workspace_id": string, "workspace_name": string, "last_updated": string, "is_temporary": bool, ... }]`

#### PUT `/make_conversation_stateful/<conversation_id>`
- **Auth**: required (JWT)
- **Response**: `{ "success": true }`
- **Note**: Converts temporary conversation to permanent. Used by "Save" action.

### Client-Side Message Types (M5)

| Type | Direction | Payload | Purpose |
|------|-----------|---------|---------|
| `DOMAIN_CHANGED` | Popup → SW → Sidepanel | `{ domain: string }` | Triggers sidebar tree reload + conversation clear |

### Client-Side JS API Methods Added (M5)

| Module | Method | Description |
|--------|--------|-------------|
| `api.js` | `createPermanentConversation(domain, workspaceId)` | Calls `POST /create_conversation/<domain>/<workspaceId>` |
| `api.js` | `listWorkspaces(domain)` | Calls `GET /list_workspaces/<domain>` |
| `api.js` | `createWorkspace(domain, name, options)` | Calls `POST /create_workspace/<domain>/<name>` |

### Documents — Conversation-Scoped (M6)

#### POST `/upload_doc_to_conversation/<conversation_id>`
- **Auth**: required (session/JWT)
- **Request**: multipart/form-data with `pdf_file` field (PDF, images, doc, html, md, csv, xlsx, json)
- **Response**: `{ "status": "Indexing started", "doc_id": string, "source": string, "title": string }`
- **Note**: Creates FastDocIndex (BM25, 1-3s) or FastImageDocIndex for images. Replaces broken `/ext/upload_doc`.

#### GET `/list_documents_by_conversation/<conversation_id>`
- **Auth**: required
- **Response**: `[{ "doc_id": string, "source": string, "title": string, ... }]`

#### DELETE `/delete_document_from_conversation/<conversation_id>/<doc_id>`
- **Auth**: required
- **Response**: `{ "status": "Document deleted" }`

#### GET `/download_doc_from_conversation/<conversation_id>/<doc_id>`
- **Auth**: required
- **Response**: File download (or redirect to source URL)

#### POST `/promote_message_doc/<conversation_id>/<doc_id>`
- **Auth**: required
- **Response**: `{ "status": "Document promoted to conversation", "doc_id": string, "source": string, "title": string }`
- **Note**: Creates full DocIndex with FAISS embeddings (15-45s). Extension uses 60s timeout.

### Documents — Global (M6)

#### GET `/global_docs/list`
- **Auth**: required
- **Response**: `[{ "doc_id": string, "display_name": string, "title": string, "source": string, "created_at": string, ... }]`

#### POST `/global_docs/upload`
- **Auth**: required
- **Request**: multipart/form-data with `pdf_file` + optional `display_name`
- **Response**: `{ "status": "ok", "doc_id": string }`

#### DELETE `/global_docs/<doc_id>`
- **Auth**: required
- **Response**: `{ "status": "ok" }`

#### GET `/global_docs/download/<doc_id>`
- **Auth**: required
- **Response**: File download

#### POST `/global_docs/promote/<conversation_id>/<doc_id>`
- **Auth**: required
- **Response**: `{ "status": "ok", "doc_id": string }`
- **Note**: Promotes conversation doc to global library. Copy-verify-delete strategy.

### Conversation Actions (M6)

#### POST `/clone_conversation/<conversation_id>`
- **Auth**: required
- **Response**: `{ "conversation_id": string, "message": "Conversation cloned" }`

#### DELETE `/make_conversation_stateless/<conversation_id>`
- **Auth**: required
- **Response**: `{ "success": true }`

#### POST `/set_flag/<conversation_id>/<flag>`
- **Auth**: required
- **Params**: flag = none | red | blue | green | yellow | orange | purple
- **Response**: `{ "success": true }`

#### PUT `/move_conversation_to_workspace/<conversation_id>`
- **Auth**: required
- **Request**: `{ "target_workspace_id": string }`
- **Response**: `{ "message": "Conversation moved to workspace ..." }`

### PKB Claims (M6)

#### GET `/pkb/claims`
- **Auth**: required
- **Query**: `query`, `claim_type`, `context_domain`, `status`, `limit` (default 20), `offset` (default 0)
- **Response**: `{ "claims": [{ "claim_id": string, "statement": string, "claim_type": string, "context_domain": string, "status": string, "friendly_id": string, "claim_number": number, ... }], "count": number }`
- **Claim types**: fact, preference, decision, task, reminder, habit, memory, observation
- **Domains**: personal, health, work, relationships, learning, life_ops, finance

### Client-Side JS API Methods Added (M6 — IMPLEMENTED)

All methods below are implemented in `extension/shared/api.js` and verified via `node --check` syntax validation. Methods use `this.call()` (which resolves `getApiBaseUrl()` dynamically, supporting localhost and hosted backends). Upload methods use direct `fetch()` with `credentials: 'include'` and 401 auth error handling.

| Module | Method | Description | Notes |
|--------|--------|-------------|-------|
| `api.js` | `uploadImage(conversationId, imageFile)` | Upload image via FastImageDocIndex | Uses `pdf_file` field name — backend auto-detects type |
| `api.js` | `listDocuments(conversationId)` | List conversation docs | `GET /list_documents_by_conversation/<id>` |
| `api.js` | `deleteDocument(conversationId, docId)` | Delete conversation doc | `DELETE` method |
| `api.js` | `downloadDocUrl(conversationId, docId)` | Get download URL for conv doc | Returns URL string (not an API call) — caller opens in `window.open` |
| `api.js` | `promoteMessageDoc(conversationId, docId)` | Promote to full DocIndex (15-45s) | 60s timeout via `timeoutMs` option |
| `api.js` | `listGlobalDocs()` | List global docs | `GET /global_docs/list` |
| `api.js` | `uploadGlobalDoc(formData)` | Upload global doc | Direct `fetch()` with auth error handling |
| `api.js` | `deleteGlobalDoc(docId)` | Delete global doc | `DELETE /global_docs/<docId>` |
| `api.js` | `downloadGlobalDocUrl(docId)` | Get download URL for global doc | Returns URL string (not an API call) |
| `api.js` | `promoteToGlobal(conversationId, docId)` | Promote to global library | 60s timeout via `timeoutMs` option |
| `api.js` | `cloneConversation(conversationId)` | Clone conversation | Returns `{conversation_id}` of the clone |
| `api.js` | `makeConversationStateless(conversationId)` | Make conversation stateless | `DELETE` method |
| `api.js` | `setFlag(conversationId, flag)` | Set conversation flag color | flag: none/red/blue/green/yellow/orange/purple |
| `api.js` | `moveConversationToWorkspace(convId, wsId)` | Move to different workspace | `PUT` with JSON body `{target_workspace_id}` |
| `api.js` | `getClaims(params)` | List/search PKB claims with filters | Params → URLSearchParams query string |

### New Client-Side Modules (M6 — IMPLEMENTED)

Both modules are IIFE scripts loaded via plain `<script>` tags before `sidepanel.js` (ES module). They access `API` via `window.API` global that `sidepanel.js` exports after ES module import.

| Module | Type | Lines | Public API |
|--------|------|-------|------------|
| `docs-panel.js` | DocsPanel (IIFE global) | 188 | `init()`, `show()`, `hide()`, `toggle()`, `setConversation(id)`, `loadConversationDocs()`, `loadGlobalDocs()` |
| `claims-panel.js` | ClaimsPanel (IIFE global) | 136 | `init()`, `show()`, `hide()`, `toggle()`, `loadClaims()` |

### M6 Wiring Details (IMPLEMENTED)

**Panel coordination**: Only one overlay visible at a time. Opening Docs hides Claims + Settings. Opening Claims hides Docs + Settings. Opening Settings hides both panels.

**Conversation change hooks**: `DocsPanel.setConversation(convId)` called in `selectConversation()` and `createNewConversation()`.

**Context menu events**: 5 new DOM CustomEvent types dispatched by `workspace-tree.js`, handled in `sidepanel.js`:
- `tree-clone-conversation` → `API.cloneConversation()` + `selectConversation()` + tree refresh
- `tree-toggle-stateless` → `API.makeConversationStateless()` (falls back to `API.saveConversation()`)
- `tree-set-flag` → `API.setFlag()` + tree refresh
- `tree-move-conversation` → `API.moveConversationToWorkspace()` + tree refresh
- `tree-toast` → `showToast()`

**Attachment context menu**: Right-click on `.msg-att-clickable` elements with `doc_id` → fixed-position menu with download/promote/delete actions. Promotions show toast before and after (15-45s operations).