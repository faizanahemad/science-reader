# Milestone 3: Conversation Management — Direct Integration

**Created**: 2026-02-16
**Status**: Implementation ready
**Estimated Effort**: 4-6 days
**Approach**: Direct integration (no bridge endpoints — extension calls main backend directly)

---

## Overview

Replace the extension's conversation system (backed by `extension.db` SQLite) with the main backend's
filesystem-based conversation system (`Conversation.py` + `storage/conversations/{id}/`). After M3,
extension conversations appear in the main web UI, use the full `Conversation.py` pipeline (PKB,
agents, math formatting, running summaries, auto-takeaways), and `ExtensionDB` conversation tables
become obsolete.

### User Decisions (M3-Specific)

| Decision | Choice |
|----------|--------|
| Architecture | **Direct integration** — extension JS calls main backend endpoints, no bridge layer |
| Workspace name | **"Browser Extension"** |
| Data migration | **Skip** — no migration script, start fresh |
| Domain support | **Add now** — wire up as a setting (default `assistant`) before M5 adds UI selectors |
| Temp conversation cleanup | **Auto-delete is fine** — extension temp chats are ephemeral |
| Save conversation | Use existing `PUT /make_conversation_stateful/<id>` |

---

## Endpoint Mapping

### Conversation Operations

| Extension Currently | Main Backend Replacement | Method | Notes |
|---|---|---|---|
| `POST /ext/conversations` | `POST /create_temporary_conversation/<domain>` | POST | Atomic: creates temp conv + returns fresh list |
| `GET /ext/conversations?limit=50` | `GET /list_conversation_by_user/<domain>` | GET | Cleans up stateless convs first, returns sorted metadata list |
| `GET /ext/conversations/<id>` | `GET /list_messages_by_conversation/<id>` + `GET /get_conversation_details/<id>` | GET | Two calls: messages + metadata |
| `PUT /ext/conversations/<id>` (title) | **Auto-set by main backend** | — | `Conversation.reply()` sets title via LLM; extension skips manual title update |
| `DELETE /ext/conversations/<id>` | `DELETE /delete_conversation/<id>` | DELETE | Direct replacement |
| `POST /ext/conversations/<id>/save` | `PUT /make_conversation_stateful/<id>` | PUT | Direct replacement |

### Chat / Streaming

| Extension Currently | Main Backend Replacement | Method | Notes |
|---|---|---|---|
| `POST /ext/chat/<id>` (streaming SSE) | `POST /send_message/<id>` | POST | **Different streaming format** — see below |

### Workspace

| Operation | Main Backend Endpoint | Method |
|---|---|---|
| List workspaces | `GET /list_workspaces/<domain>` | GET |
| Create workspace | `POST /create_workspace/<domain>/<workspace_name>` | POST |

---

## Format Differences

### Streaming Format

**Current (extension expects SSE via `API.stream()`)**:
```
data: {"chunk": "Hello"}\n\n
data: {"chunk": " world"}\n\n
data: {"done": true, "message_id": "..."}\n\n
data: {"error": "something failed"}\n\n
```

**Main backend produces (newline-delimited JSON, content-type `text/plain`)**:
```
{"text": "", "status": "Getting preamble ..."}\n
{"text": "Hello", "status": "answering in progress"}\n
{"text": " world", "status": "answering in progress"}\n
{"text": "", "status": "saving answer ...", "message_ids": {"user_message_id": "...", "response_message_id": "..."}}\n
{"text": "", "status": "saving message ..."}\n
```

**Key differences**:
- Main backend: `text/plain`, chunks separated by `\n`
- Extension SSE: `text/event-stream`, chunks prefixed with `data: ` and separated by `\n\n`
- Main backend: `text` field (can be empty for status-only chunks), `status` field
- Extension SSE: `chunk` field for text, `done` flag, `error` field
- Main backend: No explicit "done" event — stream ends when generator finishes
- Main backend: `message_ids` dict appears in status chunks near end
- Done detection: `status` containing `"saving answer"` signals streaming of answer text is complete

### Message Format

| Field | Extension | Main Backend |
|---|---|---|
| Role/sender | `role: "user" \| "assistant"` | `sender: "user" \| "model"` |
| Content | `content` | `text` |
| ID | `message_id` | `message_id` |
| Timestamp | `created_at` (ISO string) | Not stored per-message |
| User | Not tracked | `user_id` |
| Hash | Not present | `message_short_hash` (lazy backfill) |
| Conversation | Not tracked | `conversation_id` |

### Conversation Metadata Format

**Main backend `get_metadata()` returns:**
```json
{
  "conversation_id": "email_36chars",
  "user_id": "email",
  "title": "...",
  "summary_till_now": "...",
  "domain": "assistant",
  "flag": "...",
  "last_updated": "2026-02-16 12:00:00",
  "conversation_settings": {},
  "conversation_friendly_id": "slug-string"
}
```

Plus `workspace_id`, `workspace_name`, `domain` added by list/create endpoints.

**Extension currently expects:**
```json
{
  "conversation_id": "hex_token",
  "title": "...",
  "is_temporary": true,
  "updated_at": "2026-02-16T12:00:00.000Z"
}
```

**Adaptation needed in extension JS:**
- `updated_at` → read from `last_updated`
- `is_temporary` → track locally (not in main backend metadata)
- `title` → same field name, works directly

### Send Message Payload

**Extension currently sends to `/ext/chat/<id>`:**
```json
{
  "message": "user text",
  "page_context": { "url": "...", "title": "...", "content": "...", "..." : "..." },
  "model": "google/gemini-2.5-flash",
  "agent": "None",
  "workflow_id": null,
  "images": ["data:image/png;base64,..."],
  "display_attachments": ["..."],
  "stream": true
}
```

**Main backend `/send_message/<id>` expects:**
```json
{
  "messageText": "user text",
  "checkboxes": {
    "main_model": "google/gemini-2.5-flash",
    "field": "None",
    "persist_or_not": true,
    "provide_detailed_answers": 2,
    "use_pkb": true,
    "enable_previous_messages": "10",
    "perform_web_search": false,
    "googleScholar": false,
    "ppt_answer": false,
    "preamble_options": []
  },
  "search": [],
  "links": [],
  "source": "extension",
  "page_context": { "..." : "..." },
  "images": ["data:image/png;base64,..."]
}
```

**Key mappings:**
- `message` → `messageText`
- `model` → `checkboxes.main_model`
- `agent` → `checkboxes.field`
- Add `source: "extension"` (triggers server-side defaults at conversations.py line 1498)
- `page_context`, `images` pass through unchanged
- `display_attachments` → not used by main backend (extension UI display only)
- `stream: true` → not needed (main backend always streams)
- `workflow_id` → `checkboxes.field = "PromptWorkflowAgent"` when workflow active

---

## Task Breakdown

### Task 3.1: Add Domain/Workspace Support to Extension

**Goal**: Extension stores and uses a `domain` setting (default `"assistant"`) for all conversation
operations.

**Files to modify:**
- `extension/shared/constants.js` — Add `domain` to `DEFAULT_SETTINGS`, add `STORAGE_KEYS.DOMAIN`
- `extension/shared/storage.js` — Add `getDomain()` / `setDomain()` helpers

**Changes:**

1. **constants.js**: Add to `DEFAULT_SETTINGS`:
   ```javascript
   domain: 'assistant',   // Active domain: 'assistant', 'search', 'finchat'
   ```
   Add to `STORAGE_KEYS`:
   ```javascript
   DOMAIN: 'activeDomain',
   ```

2. **storage.js**: Add methods:
   ```javascript
   async getDomain() {
       return (await this.get(STORAGE_KEYS.DOMAIN)) || DEFAULT_SETTINGS.domain;
   },
   async setDomain(domain) {
       return this.set(STORAGE_KEYS.DOMAIN, domain);
   },
   ```

**Acceptance criteria:**
- Extension stores domain in chrome.storage.local
- Default domain is `'assistant'`
- Domain is accessible throughout extension via `Storage.getDomain()`

---

### Task 3.2: Rewrite Extension API Layer (`api.js`)

**Goal**: All conversation API methods call main backend endpoints directly instead of `/ext/*`
legacy endpoints. New streaming method parses newline-delimited JSON.

**File to modify:** `extension/shared/api.js`

**Changes:**

1. **Replace `API.stream()` with `API.streamJsonLines()`** — New method that parses
   newline-delimited JSON (main backend format) instead of SSE:
   ```javascript
   async streamJsonLines(endpoint, body, { onChunk, onStatus, onMessageIds, onDone, onError }) {
       // fetch with POST, credentials: 'include'
       // Read response.body with getReader()
       // Buffer chunks, split by '\n'
       // JSON.parse each line → extract text, status, message_ids
       // Call onChunk(text) for non-empty text
       // Call onStatus(status) for status updates
       // Call onMessageIds(ids) when message_ids appear
       // Call onDone() when stream ends
   }
   ```

2. **Replace `API.sendMessageStreaming()`** — Build main backend payload format:
   ```javascript
   async sendMessageStreaming(conversationId, data, callbacks) {
       const payload = {
           messageText: data.message,
           checkboxes: {
               main_model: data.model || 'google/gemini-2.5-flash',
               field: data.agent || 'None',
               persist_or_not: true,
               provide_detailed_answers: 2,
               use_pkb: true,
               enable_previous_messages: String(data.historyLength || 10),
               perform_web_search: false,
               googleScholar: false,
               ppt_answer: false,
               preamble_options: [],
           },
           search: [],
           links: [],
           source: 'extension',
           page_context: data.pageContext || null,
           images: data.images || [],
       };
       return this.streamJsonLines(`/send_message/${conversationId}`, payload, callbacks);
   }
   ```

3. **Replace `API.createConversation()`** — Use atomic temp creation:
   ```javascript
   async createConversation(data = {}) {
       const domain = await Storage.getDomain();
       return this.call(`/create_temporary_conversation/${domain}`, {
           method: 'POST',
           body: JSON.stringify({ workspace_id: data.workspace_id || null })
       });
   }
   ```

4. **Replace `API.getConversations()`** — Use main backend list:
   ```javascript
   async getConversations() {
       const domain = await Storage.getDomain();
       return this.call(`/list_conversation_by_user/${domain}`);
   }
   ```

5. **Replace `API.getConversation(id)`** — Use messages + details endpoints:
   ```javascript
   async getConversationMessages(id) {
       return this.call(`/list_messages_by_conversation/${id}`);
   }
   async getConversationDetails(id) {
       return this.call(`/get_conversation_details/${id}`);
   }
   ```

6. **Replace `API.deleteConversation(id)`**:
   ```javascript
   async deleteConversation(id) {
       return this.call(`/delete_conversation/${id}`, { method: 'DELETE' });
   }
   ```

7. **Replace `API.saveConversation(id)`** — Use make_stateful:
   ```javascript
   async saveConversation(id) {
       return this.call(`/make_conversation_stateful/${id}`, { method: 'PUT' });
   }
   ```

8. **Remove `API.sendMessage()` (non-streaming)** — Main backend always streams.

9. **Remove `API.updateConversation()`** — Title auto-set by main backend during reply.

10. **Remove `API.addMessage()`** and **`API.deleteMessage()`** — Legacy extension endpoints.

11. **Add workspace methods**:
    ```javascript
    async listWorkspaces(domain) {
        return this.call(`/list_workspaces/${domain}`);
    },
    async createWorkspace(domain, name, options = {}) {
        return this.call(
            `/create_workspace/${encodeURIComponent(domain)}/${encodeURIComponent(name)}`,
            {
                method: 'POST',
                body: JSON.stringify({
                    workspace_color: options.color || '#6f42c1',
                    parent_workspace_id: options.parentId || null,
                })
            }
        );
    },
    ```

**Keep unchanged:**
- `API.call()` — Generic authenticated request
- `API.login()`, `API.logout()`, `API.verifyAuth()` — M1 auth
- `API.ocrScreenshots()` — M2 OCR
- `API.transcribeAudio()` — M2 voice
- `API.getPrompts()`, `API.getAgents()` — Still `/ext/*` (ported in M4)
- `API.getWorkflows()`, etc. — Still `/ext/*` (ported in M4)
- `API.getSettings()`, `API.updateSettings()` — Still `/ext/*` (ported in M4)
- `API.generateScript()`, `API.saveScript()`, etc. — Still `/ext/*` (ported in M4)
- `API.uploadDoc()` — Still `/ext/upload_doc` (ported in M6)

**Acceptance criteria:**
- All conversation API methods call main backend endpoints
- New streaming parser handles newline-delimited JSON
- Payload transformation builds correct main backend format
- `source: "extension"` included in every send_message payload
- Domain passed to all domain-parameterized endpoints

---

### Task 3.3: Adapt Sidepanel Conversation Management

**Goal**: Update `sidepanel.js` conversation functions to work with new API response formats.

**File to modify:** `extension/sidepanel/sidepanel.js`

**Changes by function:**

#### 3.3a: `createNewConversation()` (line 969)

Currently calls `API.createConversation({title, is_temporary, model, ...})` and reads
`data.conversation`.

After: Calls `API.createConversation({workspace_id})` → response is
`{conversation, conversations, workspaces}`.

```javascript
async function createNewConversation() {
    try {
        clearOcrCache();
        clearImageAttachments();
        const workspaceId = await getOrCreateExtensionWorkspace();
        const data = await API.createConversation({ workspace_id: workspaceId });

        // Adapt metadata format
        const conv = data.conversation;
        state.currentConversation = {
            conversation_id: conv.conversation_id,
            title: conv.title || 'New Chat',
            is_temporary: true,  // Track locally — create_temporary makes stateless
            updated_at: conv.last_updated,
        };
        state.messages = [];

        // Update full conversation list from response
        state.conversations = adaptConversationList(data.conversations);
        // Mark the new temp conversation
        const newInList = state.conversations.find(
            c => c.conversation_id === conv.conversation_id
        );
        if (newInList) newInList.is_temporary = true;

        renderConversationList();
        // (preserve existing UI reset logic)
        await Storage.setCurrentConversation(conv.conversation_id);
        return true;
    } catch (error) { ... }
}
```

#### 3.3b: `loadConversations()` (line 731)

After: Response is a flat array of metadata dicts (not `{conversations: [...]}`).

```javascript
async function loadConversations() {
    try {
        const data = await API.getConversations();
        // list_conversation_by_user returns array directly
        state.conversations = adaptConversationList(data);
        renderConversationList();
    } catch (error) { ... }
}
```

#### 3.3c: `selectConversation(convId)` (line 942)

After: Fetch messages via `getConversationMessages`, metadata from state.

```javascript
async function selectConversation(convId) {
    try {
        const messages = await API.getConversationMessages(convId);
        state.messages = adaptMessageList(messages);
        const convMeta = state.conversations.find(c => c.conversation_id === convId);
        state.currentConversation = convMeta || { conversation_id: convId, title: 'Chat' };
        renderConversationList();
        renderMessages();
        welcomeScreen.classList.add('hidden');
        messagesContainer.classList.remove('hidden');
    } catch (error) { ... }
}
```

#### 3.3d-f: `deleteConversation`, `saveConversation`, `updateConversationInList`

- `deleteConversation` — Minimal change, API path updated in Task 3.2
- `saveConversation` — Calls `make_conversation_stateful`, updates local `is_temporary = false`
- `updateConversationInList` — Remove API call (title auto-set by backend), keep local title update

#### 3.3g: Add helper functions

```javascript
function adaptConversationList(metadataList) {
    if (!Array.isArray(metadataList)) return [];
    return metadataList.map(meta => ({
        conversation_id: meta.conversation_id,
        title: meta.title || 'New Chat',
        is_temporary: false,  // Stateless cleaned up; only fresh temp is marked locally
        updated_at: meta.last_updated,
        workspace_id: meta.workspace_id,
        workspace_name: meta.workspace_name,
        domain: meta.domain,
    }));
}

function adaptMessageList(messages) {
    if (!Array.isArray(messages)) return [];
    return messages.map(msg => ({
        message_id: msg.message_id,
        role: msg.sender === 'model' ? 'assistant' : msg.sender,
        content: msg.text,
        created_at: '',
    }));
}
```

**Acceptance criteria:**
- All conversation functions use new API methods and adapt response formats
- `is_temporary` tracked locally (true only for freshly created temp conversations)
- Field mappings correct: `last_updated→updated_at`, `sender→role`, `text→content`

---

### Task 3.4: Rewrite Streaming Message Handler

**Goal**: Sidepanel parses newline-delimited JSON from `/send_message` instead of SSE.

**File to modify:** `extension/sidepanel/sidepanel.js`

**Changes to `sendMessage()` streaming section (lines ~1416-1456):**

Updated callbacks for new streaming format:
- `onChunk(text)` — receives text only (empty-text status chunks filtered by `streamJsonLines`)
- `onMessageIds(ids)` — new callback, replaces `onDone(data)` which carried `message_id`
- `onDone()` — called when stream ends (no args)
- Stop streaming: `AbortController.abort()` cancels the fetch — same as current

**Acceptance criteria:**
- Messages stream incrementally (same UX as before)
- Message IDs captured from `message_ids` chunks
- Stop button works
- Error messages displayed in assistant bubble

---

### Task 3.5: Workspace Auto-Creation

**Goal**: Before creating the first extension conversation in a domain, check if a "Browser Extension"
workspace exists. If not, create it. Pass its `workspace_id` to `create_temporary_conversation`.

**Files to modify:**
- `extension/sidepanel/sidepanel.js` — Add `getOrCreateExtensionWorkspace()` helper
- `extension/shared/api.js` — Workspace methods added in Task 3.2

**Implementation:**
- Check `listWorkspaces(domain)` for workspace named "Browser Extension"
- If missing, `createWorkspace(domain, 'Browser Extension', { color: '#6f42c1' })`
- Cache workspace_id in `state[`ext_workspace_${domain}`]` to avoid repeated API calls
- Graceful fallback to `null` (uses default workspace) on error

**Acceptance criteria:**
- First conversation in domain auto-creates "Browser Extension" workspace
- Workspace visible in main web UI under correct domain
- Purple color (#6f42c1) for visual distinction
- Graceful fallback on error

---

### Task 3.6: Conversation Initialization Flow Update

**Goal**: Update the extension's init flow for main backend endpoints.

**Key change**: `list_conversation_by_user` cleans up stateless conversations. If the extension
had a temp conversation from a previous session that wasn't saved, it's gone. Handle gracefully:
1. Load conversations
2. Check if stored `currentConversation` ID is in the list
3. If not (was temp, got cleaned up), clear current and show welcome screen

**Acceptance criteria:**
- Extension loads correctly on fresh start
- Temp conversations from previous sessions handled gracefully
- Saved conversations persist across sessions

---

### Task 3.7: CORS and Auth Verification

**Goal**: Ensure main backend CORS config allows extension to call all new endpoints.

**File to check/modify:** `server.py`

**Action**: Verify CORS is global or add patterns for `conversations_bp` and `workspaces_bp`.

**Acceptance criteria:**
- All endpoints accessible from `chrome-extension://` origin
- Preflight (OPTIONS) handled
- Session cookies sent with `credentials: 'include'`

---

### Task 3.8: End-to-End Testing

12 test cases covering: temp conversation creation, streaming, page context, screenshots,
multi-tab, voice, save, load history, delete, persistence, temp cleanup, workspace visibility.

---

## Implementation Order

1. **Task 3.1** (domain/workspace constants + storage) — Foundation
2. **Task 3.7** (CORS verification) — Quick check, unblocks everything
3. **Task 3.5** (workspace auto-creation helpers) — Needed by conversation creation
4. **Task 3.2** (API layer rewrite) — Core change
5. **Task 3.3** (sidepanel conversation management) — Depends on 3.2
6. **Task 3.4** (streaming rewrite) — Depends on 3.2
7. **Task 3.6** (initialization flow) — Depends on 3.3
8. **Task 3.8** (testing) — After all code changes

---

## Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|
| CORS blocks new endpoints | High | Check CORS config first (Task 3.7); add patterns if needed |
| Streaming format parsing edge cases | Medium | Buffer handling for partial JSON lines; test with real server |
| `list_conversation_by_user` auto-creates conversations | Medium | Handle unexpected conversation creation; track server-created convs |
| Title set by LLM might be slow | Low | Keep client-side temporary title; refresh on next list load |
| Workspace creation race condition | Low | Cache workspace_id; null fallback |
| `display_attachments` not in main backend | Low | Store locally per message; not sent to server |

---

## Files Modified Summary

| File | Changes |
|---|---|
| `extension/shared/constants.js` | Add `domain` to DEFAULT_SETTINGS, STORAGE_KEYS.DOMAIN |
| `extension/shared/storage.js` | Add `getDomain()`, `setDomain()` |
| `extension/shared/api.js` | Rewrite conversation/chat methods, new `streamJsonLines()`, add workspace methods, remove legacy methods |
| `extension/sidepanel/sidepanel.js` | Rewrite conversation functions, streaming handler, add adapter helpers, workspace auto-creation |
| `server.py` | CORS additions for conversation/workspace endpoints (if needed) |

**No new files created.** All changes are modifications to existing extension files plus
potentially minor CORS additions to `server.py`.

**No main backend logic changes.** All existing endpoints used as-is.