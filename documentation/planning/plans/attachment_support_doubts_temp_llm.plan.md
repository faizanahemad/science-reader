# Attachment Support for Doubts and Temp LLM Action Messages

**Version:** 1.0
**Created:** 2026-06-22
**Status:** Planning Complete — Ready for Implementation

---

## 1. Background and Motivation

Normal conversation messages support file and image attachments end-to-end: the user picks a file, it is uploaded immediately via `/attach_doc_to_message`, and at send time the `display_attachments` payload is included in the message body. The backend stores a `FastDocIndex` for the file and injects `#doc_N` references into the LLM prompt so the model can read the content.

**Doubts** (threaded Q&A cards pinned to a specific message) and **temp LLM action messages** (ephemeral explain/critique/ELI5/ask-temporarily interactions) are two other message types that involve user input and LLM responses but currently have no attachment support at all. Users cannot upload a file to provide context when asking a doubt or running a temp LLM action.

### Prior Work

The original file attachment system (upload endpoint, `add_message_attached_document`, `display_attachments` rendering) is documented in `file_attachment_preview_system.plan.md`. That plan is complete. This plan builds on top of it.

A Windows-specific bug was also fixed just before this plan: `create_fast_document_index` in `DocIndex.py` was importing all langchain loaders unconditionally at function entry, causing a `torch` DLL crash on every file upload. The fix (committed `414fe15`) moved all imports inline to their per-filetype `elif` branch so only the required loader is imported.

---

## 2. Investigation Summary

### 2.1 What Are Doubts?

A doubt is a persisted Q&A record attached to a specific existing message. The user opens the doubt modal from a message card dropdown or by right-clicking selected text. The doubt text is sent to `POST /clear_doubt/<conversation_id>/<message_id>`, the LLM answer streams back, and the result is saved in the doubts database table. Doubts can be threaded (parent/child), pinned, bookmarked, and regenerated.

**Key files:**
- `endpoints/doubts.py` lines 44–218: `clear_doubt_route()`
- `Conversation.py` lines 13615–13820: `clear_doubt()` method
- `interface/doubt-manager.js` lines 1013–1096: `sendDoubt()` → `streamDoubtResponse()`
- `interface/interface.html` lines 2148–2227: `#doubt-chat-modal` HTML

### 2.2 What Are Temp LLM Action Messages?

Temp LLM actions are ephemeral, in-memory-only interactions. The user right-clicks selected text in a message card and chooses Explain, Critique, Expand, ELI5, or Ask Temporarily. The conversation history lives only in `TempLLMManager.currentHistory` (a JS array) for the duration the modal is open. Nothing is saved to the database.

**Key files:**
- `endpoints/doubts.py` lines 221–357: `temporary_llm_action_route()`
- `Conversation.py` lines 13822–end: `temporary_llm_action()` method
- `interface/temp-llm-manager.js` lines 460–506: `streamResponse()`
- `interface/interface.html` lines 2350–2429: `#temp-llm-modal` HTML

### 2.3 Normal Message Attachment Flow (existing, working)

1. User picks a file via paperclip or drag-drop in the main chat input area
2. JS: `addFileToAttachmentPreview()` (`common-chat.js` line 51) adds entry to global `pendingAttachments[]`
3. JS: file is POSTed to `POST /attach_doc_to_message/<conversationId>` (`endpoints/documents.py` lines 101–136)
4. Backend: `conversation.add_message_attached_document()` (`Conversation.py` lines 2093–2158) calls `create_fast_document_index()`, stores result in `message_attached_documents_list`
5. Endpoint returns `{doc_id, source}`, JS calls `enrichAttachmentWithDocInfo()` (`common-chat.js` line 85) to store these on the pending entry
6. At send time: `getDisplayAttachmentsPayload()` (`common-chat.js` line 129) serialises `pendingAttachments` into `display_attachments` and includes it in the POST body to `/send_message/`
7. Backend `Conversation.reply()` lines 9640–9675: reads `display_attachments`, maps `doc_id` → `#doc_N` index, injects reference into the LLM prompt
8. `persist_current_turn()` (`Conversation.py` line 4259): saves `display_attachments` on the user message dict so it re-renders on reload
9. JS on message load (`common-chat.js` lines 2567–2586): renders thumbnails/file badges from `display_attachments` in the message card

### 2.4 Gaps in Doubts and Temp LLM

| Gap | Doubts | Temp LLM |
|-----|--------|----------|
| No `display_attachments` in request payload | `doubt-manager.js` line 1076 | `temp-llm-manager.js` line 470 |
| No attachment UI in modal | `interface.html` lines 2148–2227 | `interface.html` lines 2350–2429 |
| Backend endpoint ignores `display_attachments` | `endpoints/doubts.py` line 64 | `endpoints/doubts.py` line 247 |
| `Conversation` method has no attachment handling | `clear_doubt()` line 13615 | `temporary_llm_action()` line 13822 |
| No persistence of attachments | doubts DB schema | N/A (ephemeral) |
| No cleanup of uploaded files | N/A | temp modal on close |

### 2.5 Key Architectural Difference: Doubts vs Temp LLM

**Doubts** are persistent and go through a similar prompt-building path as normal messages. The existing `#doc_N` injection mechanism from `reply()` can be reused with minimal adaptation.

**Temp LLM actions** build their prompts from scratch and have no document-reading pipeline. Uploaded file content must be **inlined as raw text** directly into the prompt, not referenced via `#doc_N`. The `FastDocIndex` object exposes the indexed text which can be read and appended.

Additionally, since temp LLM actions are ephemeral, uploaded files persist on the `Conversation` object's `message_attached_documents_list` unnecessarily. These must be cleaned up when the modal closes.

---

## 3. Decisions Made

| Question | Decision | Rationale |
|----------|----------|-----------|
| How should doc content reach LLM in temp LLM? | Inline full text appended after user message | No doc-reading pipeline; simple and effective for typical doc sizes |
| Where in the temp LLM prompt? | Append after user message with `--- Attached: filename ---` label | LLM sees it naturally as part of the turn |
| What happens to temp LLM uploads after modal closes? | Clean up via new `DELETE /detach_doc_from_message/<conv_id>/<doc_id>` endpoint | Keeps `message_attached_documents_list` clean; explicit and restful |
| Should attachment info persist with doubts in DB? | Yes — new `display_attachments` JSON column on the doubts table | Re-renders on page reload; consistent with normal messages |
| Where do attachment badges show for doubts on reload? | In the doubt card on the main conversation view | Consistent with normal message card rendering |
| How to make attachment JS helpers reusable? | Parameterize in-place — add `{container, list}` context param | Minimal duplication; no new files; all three modals share one code path |
| Where does attachment UI appear in modals? | Preview strip above textarea + paperclip beside send button | Consistent with main chat UX |
| Supported file types? | Same as normal messages (all types in `create_fast_document_index`) | No reason to restrict; same backend path |
| Multiple files per message? | Yes | Consistent with normal messages |
| How to share `#doc_N` injection logic? | Extract `_inject_display_attachments()` private method on `Conversation` | DRY; avoids drift between three call sites |

---

## 4. Implementation Plan

Work order is designed so each step leaves the system in a working state. Backend helpers first, then endpoints, then frontend.

---

### Step 1 — Extract `_inject_display_attachments()` in `Conversation.py`

**File:** `Conversation.py`

The block at lines 9640–9675 inside `reply()` maps each `display_attachments` entry's `doc_id` to a `#doc_N` index and injects the reference into `messageText`. Extract this into a new private method:

```python
def _inject_display_attachments(self, display_attachments, message_text):
    """
    Given a display_attachments list and a message text string, return a new
    message text with #doc_N references injected for each attachment that has
    a known doc_id in message_attached_documents_list or uploaded_documents_list.

    Parameters
    ----------
    display_attachments : list[dict]
        Each entry has at least {doc_id, source, name, type}.
    message_text : str
        The user's message text.

    Returns
    -------
    str
        Message text with #doc_N references prepended/appended.
    """
```

Update `reply()` to call this method instead of the inline block.

---

### Step 2 — Add `_get_attached_doc_texts()` helper in `Conversation.py`

**File:** `Conversation.py`

For temp LLM actions, we need to read full text from each attached `FastDocIndex`. Add a helper:

```python
def _get_attached_doc_texts(self, display_attachments):
    """
    For each entry in display_attachments that has a known doc_id, load the
    FastDocIndex and return its full indexed text.

    Returns
    -------
    list[dict]
        Each entry: {name, text} for inlining into a prompt.
    """
```

This iterates `message_attached_documents_list`, matches by `doc_id`, loads the stored index from disk, and reads `.get_text()` or equivalent.

---

### Step 3 — Add `remove_message_attached_document()` in `Conversation.py`

**File:** `Conversation.py`

```python
def remove_message_attached_document(self, doc_id):
    """
    Remove a document from message_attached_documents_list by doc_id.
    Used when a temp LLM modal closes to clean up ephemeral uploads.
    """
```

Filters `self.message_attached_documents_list` to remove the entry with matching `doc_id`. Also removes from `self.doc_infos` string if present.

---

### Step 4 — Update `clear_doubt()` in `Conversation.py`

**File:** `Conversation.py` line 13615

Add `display_attachments=None` parameter. Before building the LLM prompt, call `self._inject_display_attachments(display_attachments, doubt_text)` and use the returned text as the effective doubt text fed to the LLM.

---

### Step 5 — Update `temporary_llm_action()` in `Conversation.py`

**File:** `Conversation.py` line 13822

Add `display_attachments=None` parameter. After building the base prompt from `selected_text` + `user_message`, call `self._get_attached_doc_texts(display_attachments)` and append each result as:

```
--- Attached: <filename> ---
<full doc text>
```

This appended block is added to the user-turn content before calling the LLM.

---

### Step 6 — Add `DELETE /detach_doc_from_message/<conv_id>/<doc_id>` endpoint

**File:** `endpoints/documents.py` (alongside the existing `/attach_doc_to_message` route)

```
DELETE /detach_doc_from_message/<conversation_id>/<doc_id>
```

- Loads the conversation object
- Calls `conversation.remove_message_attached_document(doc_id)`
- Returns `{"status": "ok"}`
- Returns 404 if conversation not found, 400 if doc_id not found

---

### Step 7 — Update `clear_doubt_route()` in `endpoints/doubts.py`

**File:** `endpoints/doubts.py` line 64

Read:
```python
display_attachments = request.json.get("display_attachments", [])
```

Pass to `conversation.clear_doubt(..., display_attachments=display_attachments)`.

Also pass `display_attachments` to `database.doubts.add_doubt()` (see Step 8).

---

### Step 8 — Update `temporary_llm_action_route()` in `endpoints/doubts.py`

**File:** `endpoints/doubts.py` line 247

Read `display_attachments = data.get("display_attachments", [])` and pass to `conversation.temporary_llm_action(..., display_attachments=display_attachments)`.

---

### Step 9 — Doubts DB schema migration

**File:** doubts database module (find via `database.doubts`)

Add a `display_attachments` TEXT/JSON column to the doubts table. Default `NULL` / empty list for existing rows.

Update:
- `add_doubt()`: accept and store `display_attachments` parameter (serialise to JSON string)
- `get_doubts()` / doubt fetch queries: deserialise `display_attachments` back to list when reading rows

---

### Step 10 — Parameterize attachment JS helpers in `common-chat.js`

**File:** `interface/common-chat.js`

Current helpers use the global `pendingAttachments` array and hardcoded `#attachment-preview` selector. Add an optional `context` parameter to each:

```javascript
// context = { list: [], container: $('#attachment-preview') }
// If context is omitted, falls back to the global pendingAttachments + #attachment-preview
function addFileToAttachmentPreview(file, conversationId, context) { ... }
function renderAttachmentPreviews(context) { ... }
function clearAttachmentPreviews(context) { ... }
function getDisplayAttachmentsPayload(context) { ... }
function enrichAttachmentWithDocInfo(tempId, docInfo, context) { ... }
```

All existing call sites (main chat) pass no context, so they keep working unchanged via the fallback.

Also extract the file-upload POST logic into a standalone helper:
```javascript
function uploadFileToConversation(file, conversationId, context) {
    // POST to /attach_doc_to_message/<conversationId>
    // On success: enrichAttachmentWithDocInfo(tempId, docInfo, context)
}
```

---

### Step 11 — Add attachment UI to doubt modal in `interface.html`

**File:** `interface/interface.html` lines 2207–2226 (input area of `#doubt-chat-modal`)

Before the `<textarea>` in the doubt input row, add:

```html
<div id="doubt-attachment-preview" class="attachment-preview-strip"></div>
```

Beside the send button row, add:

```html
<span id="doubt-file-upload-span" class="paperclip-btn" title="Attach file">
    <i class="fas fa-paperclip"></i>
    <input type="file" id="doubt-file-upload" multiple style="display:none">
</span>
```

Mirror the exact structure from the main chat input area (`interface.html` lines 476–481) so existing CSS applies.

---

### Step 12 — Add attachment UI to temp LLM modal in `interface.html`

**File:** `interface/interface.html` lines 2410–2428 (input area of `#temp-llm-modal`)

Same additions as Step 11, with IDs `#temp-llm-attachment-preview`, `#temp-llm-file-upload-span`, `#temp-llm-file-upload`.

---

### Step 13 — Wire attachment logic in `doubt-manager.js`

**File:** `interface/doubt-manager.js`

1. At `DoubtManager` init, create:
   ```javascript
   this.attachmentContext = {
       list: [],
       container: $('#doubt-attachment-preview')
   };
   ```

2. Wire `#doubt-file-upload` `change` event to call `uploadFileToConversation(file, conversationId, this.attachmentContext)` for each selected file.

3. In `streamDoubtResponse()` before `fetch('/clear_doubt/...')`:
   ```javascript
   const displayAtts = getDisplayAttachmentsPayload(this.attachmentContext);
   if (displayAtts) requestBody.display_attachments = displayAtts;
   ```

4. After send completes: `clearAttachmentPreviews(this.attachmentContext)`.

5. In `createDoubtChatCard()` for user-turn cards: if the doubt object has `display_attachments`, render thumbnail/badge elements using the same rendering logic as `common-chat.js` lines 2567–2586.

6. On modal close (or doubt modal reset): iterate `this.attachmentContext.list`, call `DELETE /detach_doc_from_message/<convId>/<docId>` for any entries that were **not** sent (i.e. still pending), then clear the list.
   - Note: sent attachments should **not** be deleted on close — they belong to the saved doubt.

---

### Step 14 — Wire attachment logic in `temp-llm-manager.js`

**File:** `interface/temp-llm-manager.js`

1. At `TempLLMManager` init (or modal open), create:
   ```javascript
   this.attachmentContext = {
       list: [],
       container: $('#temp-llm-attachment-preview')
   };
   this.sentAttachmentDocIds = [];  // track doc_ids that were actually sent
   ```

2. Wire `#temp-llm-file-upload` `change` event to `uploadFileToConversation`.

3. In `streamResponse()` before `fetch('/temporary_llm_action')`:
   ```javascript
   const displayAtts = getDisplayAttachmentsPayload(this.attachmentContext);
   if (displayAtts) {
       requestBody.display_attachments = displayAtts;
       displayAtts.forEach(a => this.sentAttachmentDocIds.push(a.doc_id));
   }
   clearAttachmentPreviews(this.attachmentContext);
   ```

4. On modal close (`#temp-llm-modal` `hidden.bs.modal` event):
   - Call `DELETE /detach_doc_from_message/<convId>/<docId>` for **all** doc_ids in `sentAttachmentDocIds` plus any remaining in `this.attachmentContext.list`
   - Reset `this.attachmentContext.list = []` and `this.sentAttachmentDocIds = []`
   - Rationale: unlike doubts, temp LLM results are never saved, so uploaded docs serve no purpose after the modal closes regardless of whether they were sent

---

### Step 15 — Render attachment badges in doubt cards on reload

**File:** `interface/doubt-manager.js` (doubt card rendering) and/or `interface/common-chat.js`

When doubts are loaded on page reload, the doubt object from the DB now has `display_attachments`. The card creation code should check for this and render badges/thumbnails in the user-turn portion of the doubt card, reusing the same rendering function used for normal messages.

---

## 5. File Change Summary

| File | Changes |
|------|---------|
| `Conversation.py` | Extract `_inject_display_attachments()`, add `_get_attached_doc_texts()`, add `remove_message_attached_document()`, update `clear_doubt()` and `temporary_llm_action()` signatures |
| `endpoints/doubts.py` | Read `display_attachments` in both routes; pass to Conversation methods; pass to `add_doubt()` |
| `endpoints/documents.py` | Add `DELETE /detach_doc_from_message/<conv_id>/<doc_id>` route |
| Doubts DB module | Add `display_attachments` column to doubts table; update `add_doubt()` and doubt fetch queries |
| `interface/common-chat.js` | Parameterize attachment helpers with optional context; extract `uploadFileToConversation()` |
| `interface/interface.html` | Add paperclip + preview strip HTML to `#doubt-chat-modal` and `#temp-llm-modal` |
| `interface/doubt-manager.js` | Wire attachment context, upload-before-send, badge rendering in cards, cleanup on close |
| `interface/temp-llm-manager.js` | Wire attachment context, upload-before-send, cleanup all on modal close |

---

## 6. Assumptions and Open Questions

- **FastDocIndex text access:** Step 2 assumes `FastDocIndex` exposes a method to retrieve full indexed text (e.g. via its stored chunks). This should be verified before implementing `_get_attached_doc_texts()`. Look at the `FastDocIndex` class definition in `DocIndex.py`.
- **Doubts DB module location:** The exact file for the doubts database layer needs to be confirmed (grep for `add_doubt` in the DB layer). The schema migration approach (SQLite `ALTER TABLE` or a migration script) should follow the pattern used in other recent migrations in this repo.
- **`doc_infos` string cleanup:** `remove_message_attached_document()` should also remove the doc entry from `self.doc_infos`. The exact format of `doc_infos` should be checked to do this cleanly.
- **Drag-and-drop on modals:** The plan covers only paperclip-click upload for doubts and temp LLM modals. The page-level drag-drop in `common-chat.js` lines 2300–2317 targets the document body and routes to the main chat. Extending drag-drop to modal interiors is out of scope for now but could be added later.
- **Token budget for inlined temp LLM docs:** The decision was to inline full text. Very large documents could overflow the context window. A follow-up improvement would be to truncate or BM25-search before inlining, but this is out of scope for this plan.

---

## 7. Testing Checklist

- [ ] Upload image to doubt → LLM response references image content → doubt saves → badge visible on reload
- [ ] Upload PDF to doubt → LLM response references PDF content → doubt saves → badge visible on reload
- [ ] Upload image to temp LLM explain action → LLM response references image → modal closes → file cleaned up from `message_attached_documents_list`
- [ ] Upload PDF to temp LLM ask-temporarily → multi-turn follows up on doc content → modal closes → file cleaned up
- [ ] Multiple files attached to a single doubt message
- [ ] Normal message attachment still works (regression)
- [ ] Page reload: doubts with attachments render badges correctly
- [ ] Page reload: normal messages with attachments still render correctly (regression)
- [ ] `DELETE /detach_doc_from_message` returns 404 for unknown conversation
- [ ] `DELETE /detach_doc_from_message` returns 400 for unknown doc_id
- [ ] Closing temp LLM modal without sending removes any uploaded docs
- [ ] Closing doubt modal with unsent pending attachment removes it; already-sent doubt attachments are not removed
