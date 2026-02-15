# File Attachment Preview and Persistence System

A unified file attachment system for both the Chrome extension UI and the main web UI. Supports drag-and-drop of images and PDFs, preview thumbnails above the message input, persistent attachment rendering in sent messages (surviving page reload), context menus on rendered attachments, and LLM awareness of attached documents.

## Key Features

- **Drag-and-drop images and PDFs** in both UIs (page-wide in main UI, panel-wide in extension)
- **Preview thumbnails** above message input before sending (removable)
- **Persistent attachment rendering** in sent messages that survives page reload
- **Context menu on rendered attachments** in main UI (Preview, Download, Add to Conversation, Attach for current turn)
- **Clickable attachments** in extension (re-attach for current turn)
- **FastDocIndex** for instant uploads (BM25 keyword search, no FAISS embeddings)
- **Promotion flow** to upgrade FastDocIndex to full ImmediateDocIndex with FAISS + LLM summaries
- **LLM reads attached document content** when generating its reply to that message
- **Extension PDF text extraction** via pdfplumber, stored as system message and merged into LLM prompt

## Architecture

### display_attachments Field

Both UIs store a `display_attachments` JSON array in each user message for rendering purposes.

**Schema:**
```json
[
  {
    "type": "image",
    "name": "screenshot.png",
    "thumbnail": "data:image/jpeg;base64,..."
  },
  {
    "type": "pdf",
    "name": "document.pdf",
    "thumbnail": null,
    "doc_id": "2332129554",
    "source": "/path/to/document.pdf"
  }
]
```

**Storage:**
- Extension: `ExtensionMessages.display_attachments` TEXT column (SQLite, JSON string)
- Main UI: `display_attachments` key in user message dict within conversation storage

**Constraints:**
- Not sent to LLM context (purely for UI rendering)
- Thumbnails are small: Canvas-based, 80x80 JPEG at 70% quality (main UI) / 100x100 at 60% (extension), ~2-5KB per image
- PDF attachments use styled badges instead of thumbnails

### FastDocIndex Architecture (Main UI)

When a file is drag-dropped in the main UI, the upload endpoint creates a **FastDocIndex** instead of a full DocIndex. This reduces upload latency from 15-45 seconds to 1-3 seconds.

**What FastDocIndex skips vs full DocIndex:**

| Operation | Full DocIndex | FastDocIndex |
|-----------|---------------|--------------|
| Text extraction | Yes | Yes |
| Chunking | Yes | Yes |
| BM25 keyword index | No | Yes |
| FAISS embeddings (OpenAI API) | Yes (slow) | No |
| LLM-generated title | Yes (API call) | No (filename) |
| LLM-generated summary | Yes (API call) | No (first 500 chars) |
| LLM long summary | Yes (2 API calls) | No |
| Total time | 15-45s | 1-3s |

**Classes in `DocIndex.py`:**
- `FastDocIndex(DocIndex)` — BM25 keyword index over text chunks, title from filename, summary from first 500 chars. Overrides `semantic_search_document()` to use BM25 instead of FAISS. Has `bm25_search(query, top_k)` method.
- `FastImageDocIndex(DocIndex)` — Stores image and exposes `_llm_image_source` for vision models. No OCR or captioning. Returns "Image: {title}. Use vision model to analyze." from `semantic_search_document()`.
- `create_fast_document_index(pdf_url, folder, keys)` — Same text extraction + file detection + chunking as `create_immediate_document_index()`, but creates FastDocIndex/FastImageDocIndex instead of full DocIndex. No embedding model or LLM calls.

**Key design decisions:**
- Same deterministic `doc_id` (mmh3 hash of source + filetype + doctype) for both FastDocIndex and full DocIndex, enabling in-place promotion
- `store_separate` includes only `["raw_data", "static_data"]` (no `"indices"` since there are no FAISS indices)
- `set_api_keys()` overridden to skip FAISS index update (base class tries to load "indices" which doesn't exist)
- BM25 index built from tokenized chunks via `rank_bm25.BM25Okapi`, serialized with dill alongside the doc

### Two Document Lists (Main UI)

The conversation maintains two separate document lists:

| List | Field | Contents | When populated |
|------|-------|----------|----------------|
| Uploaded (promoted) | `uploaded_documents_list` | Full DocIndex/ImmediateDocIndex/ImageDocIndex | Manual upload via doc modal, or promotion from message-attached |
| Message-attached | `message_attached_documents_list` | FastDocIndex/FastImageDocIndex | Drag-drop onto message input |

Both are registered in `store_separate` (Conversation.py) for field persistence.

**Combined numbering:** `#doc_N` references use a combined index where uploaded docs come first, then message-attached docs. This is used by both the injection block and `get_uploaded_documents_for_query()`.

### Doc Reference Injection (LLM Reading)

When `display_attachments` contains entries with a `doc_id`, the `reply()` method in `Conversation.py` auto-injects `#doc_N` references into the message text. The injection block builds the mapping from BOTH `uploaded_documents_list` and `message_attached_documents_list`.

The original clean text is preserved in `_user_text_before_da_injection` and used for `original_user_query` so the persisted message stays clean.

For FastDocIndex docs during reply:
- Small docs (text length < token_limit): full text injected directly
- Large docs: BM25 keyword search over chunks, top results returned
- Images (FastImageDocIndex): `_llm_image_source` provided for vision models

### doc_infos Rebuilding

The `doc_infos` property (string of `#doc_N: (Title)[source]` mappings shown to LLM) is rebuilt from the combined list whenever a document is added to either list or promoted between lists.

## Data Flow

### Main UI — Upload (Fast Path)

1. User drops file onto page
2. `addFileToAttachmentPreview(file)` generates 80x80 canvas thumbnail, pushes to `pendingAttachments[]` with `doc_id: null`
3. `renderAttachmentPreviews()` shows preview strip above message input
4. `uploadFile_internal(file, attId)` fires XHR POST to `/upload_doc_to_conversation/<id>`
5. Server: `add_message_attached_document(pdf_url)` calls `create_fast_document_index()` — text extraction + chunking + BM25 (1-3s)
6. Server returns `{doc_id, source, title}`
7. `enrichAttachmentWithDocInfo(attId, doc_id, source, title)` fills in the pending entry
8. Send button re-enabled

### Main UI — Send Message

1. `getDisplayAttachmentsPayload()` maps `pendingAttachments` to `[{type, name, thumbnail, doc_id, source}]`
2. POST to `/send_message/<id>` with `display_attachments` in body
3. `reply()` injection block maps doc_ids from BOTH lists to `#doc_N` references
4. `get_uploaded_documents_for_query()` loads docs from combined list
5. For FastDocIndex: BM25 search for large docs, full text for small docs
6. LLM receives document content in its prompt
7. `persist_current_turn()` stores `display_attachments` in user message dict

### Main UI — Re-attach for Current Turn

1. User clicks attachment in a rendered message
2. Context menu shows "Attach for current turn"
3. Clicking pushes the attachment data (with existing `doc_id`) to `pendingAttachments[]`
4. No re-upload, no re-parse — the existing FastDocIndex on disk is reused
5. On send, the `doc_id` flows through the injection block as normal

### Main UI — Promote to Conversation

1. User clicks attachment in a rendered message
2. Context menu shows "Add to Conversation"
3. POST to `/promote_message_doc/<conversation_id>/<doc_id>`
4. `promote_message_attached_document(doc_id)`:
   - Removes from `message_attached_documents_list`
   - Creates full `ImmediateDocIndex` via `create_immediate_document_index()` (FAISS + LLM summaries, 15-45s)
   - Adds to `uploaded_documents_list`
   - Rebuilds `doc_infos`
5. Toast confirms promotion; doc list refreshed

### Main UI — Persistence

- `display_attachments` stored in user message dict by `persist_current_turn()`
- All 7 `persist_current_turn()` call sites pass `display_attachments=query.get("display_attachments")`
- On page reload, `get_message_list()` returns messages with `display_attachments`
- `renderMessages()` renders thumbnails/badges with context menu click handlers

### Extension — Upload

1. User drops file anywhere on side panel (panel-wide drag via `handleAttachmentDrop()`)
2. Image or PDF added to `state.pendingImages[]`
3. `renderImageAttachments()` shows preview (thumbnail for images, badge for PDFs)
4. On send, `uploadPendingPdfs(conversationId)` uploads PDFs via `API.uploadDoc()` to `POST /ext/upload_doc/<conversation_id>`
5. Server: pdfplumber extracts text (truncated at 128K chars), stores as system message via `conv.add_message("system", doc_content)`

### Extension — Send Message

1. `buildDisplayAttachments(state.pendingImages)` generates thumbnails for images, null for PDFs
2. `API.sendMessageStreaming()` sends message with `display_attachments`
3. Server stores `display_attachments` in `ExtensionMessages.display_attachments` column
4. LLM receives PDF content via two paths:
   - **Direct LLM path:** System messages from history merged into main system prompt (not mid-conversation)
   - **Agent path:** System messages placed in "Reference Documents" section of agent prompt (separate from conversation history)

### Extension — Re-attach for Current Turn

1. User clicks attachment (image or PDF badge) in a rendered message
2. Attachment data decoded from `data-att` attribute
3. Entry pushed to `state.pendingImages`
4. `renderImageAttachments()` shows it in the preview strip

### Extension — Persistence

- `display_attachments` TEXT column in `ExtensionMessages` table (JSON string)
- `get_messages()` returns `display_attachments` (line 1057 in extension.py)
- `get_conversation()` includes `display_attachments` in message dicts
- Survives panel reload via DB round-trip

## Files Modified

### Extension
| File | Changes |
|------|---------|
| `extension.py` | `display_attachments TEXT` column migration; `add_message()` and `get_messages()` updated; `get_conversation()` SELECT includes `display_attachments`; `get_history_for_llm()` always includes system messages regardless of history_length |
| `extension_server.py` | Extracts `display_attachments` from request; `POST /ext/upload_doc/<conversation_id>` endpoint with pdfplumber; `ext_chat()` merges system messages into system prompt; `build_agent_prompt_from_history()` puts uploaded docs in "Reference Documents" section |
| `extension/shared/api.js` | `display_attachments` in `sendMessage()` and `sendMessageStreaming()`; `uploadDoc()` method |
| `extension/sidepanel/sidepanel.js` | `addAttachmentFiles()` (accepts PDF); `generateThumbnail()`, `buildDisplayAttachments()`, `uploadPendingPdfs()`; panel-wide drag feedback; `renderMessage()` with clickable `msg-att-clickable` attachments and `data-att` JSON; attachment click delegation for re-attach; `pendingImages` save/restore around `createNewConversation()` |
| `extension/sidepanel/sidepanel.css` | `.pdf-attachment`, `.pdf-badge`, `.panel-drag-over`, `.message-pdf-badge`, `.msg-att-clickable` styles |

### Main UI
| File | Changes |
|------|---------|
| `interface/interface.html` | `#attachment-preview` container div above message input |
| `interface/common-chat.js` | `pendingAttachments[]` state; `generateThumbnailForMainUI()`, `addFileToAttachmentPreview()`, `renderAttachmentPreviews()`, `clearAttachmentPreviews()`, `getDisplayAttachmentsPayload()`, `enrichAttachmentWithDocInfo()`, `showAttachmentContextMenu()` (4 options: Preview, Download, Add to Conversation, Attach for current turn); drag-drop hooks; `sendMessage` includes `display_attachments`; `renderMessages()` renders attachments with context menu |
| `interface/style.css` | `.attachment-preview`, `.att-preview`, `.att-file`, `.att-remove-btn`, `.message-attachments`, `.msg-att-thumb`, `.msg-att-badge`, `.attachment-context-menu` styles |

### Backend
| File | Changes |
|------|---------|
| `DocIndex.py` | `FastDocIndex` class (BM25, no FAISS/LLM); `FastImageDocIndex` class (image store only); `create_fast_document_index()` function |
| `Conversation.py` | `message_attached_documents_list` in `store_separate`; `add_message_attached_document()`, `get_message_attached_documents()`, `promote_message_attached_document()` methods; `persist_current_turn()` accepts `display_attachments` (all 7 call sites); injection block uses combined docs list; `get_uploaded_documents_for_query()` loads from both lists |
| `endpoints/documents.py` | Upload endpoint uses `add_message_attached_document()` (fast path); returns `doc_id`, `source`, `title`; new `POST /promote_message_doc/<conversation_id>/<document_id>` endpoint |

## API Endpoints

### Main UI

| Method | Path | Description |
|--------|------|-------------|
| POST | `/upload_doc_to_conversation/<conversation_id>` | Upload file, create FastDocIndex (fast path). Returns `{status, doc_id, source, title}` |
| POST | `/promote_message_doc/<conversation_id>/<document_id>` | Promote FastDocIndex to full ImmediateDocIndex. Returns `{status, doc_id, source, title}` |
| POST | `/send_message/<conversation_id>` | Send message with `display_attachments` in body |
| GET | `/download_doc_from_conversation/<conversation_id>/<doc_id>` | Download attached document |

### Extension

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ext/upload_doc/<conversation_id>` | Upload PDF, extract text with pdfplumber, store as system message. Returns `{status, filename, pages, chars}` |
| POST | `/ext/chat/<conversation_id>` | Send message with `display_attachments` and `images` |

## Data Structures

### pendingAttachments (Main UI JS)
```javascript
{
  id: "att_1708012345678",
  file: File,           // null for re-attached entries
  name: "document.pdf",
  type: "pdf",
  thumbnail: null,      // or data URL for images
  doc_id: "2332129554", // null until upload completes
  source: "/path/...",  // null until upload completes
  title: "document"     // null until upload completes
}
```

### state.pendingImages (Extension JS)
```javascript
// Image
{ type: undefined, dataUrl: "data:image/png;base64,...", name: "image.png" }

// PDF
{ type: "pdf", file: File, name: "document.pdf" }

// Re-attached image
"data:image/png;base64,..."

// Re-attached PDF
{ type: "pdf", name: "document.pdf", dataUrl: null }
```

### message_attached_documents_list (Conversation.py)
```python
[(doc_id, doc_storage_path, pdf_url), ...]
# Example: [("2332129554", "/storage/conversations/.../uploaded_documents/2332129554", "/storage/pdfs/React.pdf")]
```

Same tuple structure as `uploaded_documents_list`.

## Context Menu (Main UI)

Clicking on a rendered attachment in a sent message shows a context menu with:
- **Preview**: Uses `showPDF(source, container_id, proxy_route)` from `interface/common.js` for PDF viewing. Only shown for PDFs with a source path.
- **Download**: Direct download via `/download_doc_from_conversation/<conv_id>/<doc_id>`. Only shown when `doc_id` is present.
- **Add to Conversation**: Promotes FastDocIndex to full ImmediateDocIndex (slow — FAISS + LLM). Only shown when `doc_id` is present.
- **Attach for current turn**: Adds the attachment to `pendingAttachments` for the current message. Always shown. No re-upload; reuses existing FastDocIndex.

Implemented in `showAttachmentContextMenu()` in `interface/common-chat.js`.

## Extension Clickable Attachments

Rendered attachments (images and PDF badges) in extension messages have `msg-att-clickable` class and `data-att` JSON attribute. Clicking re-attaches the file for the current turn via event delegation on `messagesContainer`. Single click action (no context menu).

## Bug Fixes Applied

### Extension: First-load attachment loss
- **Root cause:** `createNewConversation()` calls `clearImageAttachments()` which wipes `state.pendingImages`. On first message when no conversation exists, `sendMessage()` calls `createNewConversation()` before `buildDisplayAttachments()`.
- **Fix:** `pendingImages` saved before `createNewConversation()` and restored after, matching the existing pattern for `pageContext`.
- **File:** `extension/sidepanel/sidepanel.js`

### Extension: display_attachments missing after reload
- **Root cause:** `get_conversation()` SQL query did not include `display_attachments` column.
- **Fix:** Added `display_attachments` to SELECT and to returned message dicts.
- **File:** `extension.py`

### Extension: PDF not used by LLM (history truncation)
- **Root cause:** `get_history_for_llm()` applied `history_length` limit (default 10) to ALL messages including system messages containing PDF text. Early system messages got truncated.
- **Fix:** System messages always included regardless of history window; only user/assistant messages are limited.
- **File:** `extension.py`

### Extension: PDF not used by LLM (mid-conversation system messages + agent path)
- **Root cause:** Many models ignore system messages mid-conversation. Additionally, the agent path in `build_agent_prompt_from_history()` put PDF text as `System: [content]` in flat conversation history, which agents did not recognize as reference material.
- **Fix (direct LLM path):** System messages from history merged into the initial system prompt.
- **Fix (agent path):** Uploaded doc content placed in dedicated "Reference Documents" section, separate from conversation history.
- **File:** `extension_server.py`

### Extension: PDF upload API call failure
- **Root cause:** `uploadDoc()` method in `api.js` used `this.getToken()` and `this.baseUrl`, but `API` is a plain object literal, not a class instance. `this.getToken` was undefined, causing "TypeError: this.getToken is not a function".
- **Fix:** Changed to `Storage.getToken()` and `await getApiBaseUrl()` to match the pattern used in all other API methods.
- **File:** `extension/shared/api.js` (line 410-411)

### Extension: X button doesn't remove re-attached documents
- **Root cause:** When clicking a rendered attachment to re-attach it for the current turn (lines 484-498), the pushed objects lacked an `id` property. The remove button handler filters by `img.id !== id`, so attachments without IDs couldn't be removed.
- **Fix:** Generate unique ID (`reattached-{timestamp}-{random}`) when re-attaching. For image thumbnails, check if `thumbnail.id` exists and add if missing. For PDFs, always add ID when creating the object.
- **File:** `extension/sidepanel/sidepanel.js` (lines 489-493)

### Main UI: display_attachments not persisting
- **Root cause:** Only 2 of 7 `persist_current_turn()` call sites passed `display_attachments`.
- **Fix:** All 7 call sites now pass `display_attachments=query.get("display_attachments")`.
- **File:** `Conversation.py`

### Main UI: LLM not reading attached doc content
- **Root cause:** Drag-dropped files get uploaded with a `doc_id`, but the message text lacks `#doc_N` references. `get_uploaded_documents_for_query` only reads docs explicitly referenced.
- **Fix:** Injection block in `reply()` maps `display_attachments` doc_ids to `#doc_N` indices. Clean text preserved via `_user_text_before_da_injection`.
- **File:** `Conversation.py`

## Debugging Instrumentation

For investigating extension PDF attachment issues, debug logging has been added at key points in the PDF upload → LLM prompt flow:

### Browser Console Logs (extension/sidepanel/sidepanel.js)

- **Line 1847-1854 (`uploadPendingPdfs`)**: Logs the number of PDFs found to upload, full `pendingImages` array, per-PDF upload start with file object details, and upload success/failure results.
- **Line 1283 (`createNewConversation`)**: Logs restored `pendingImages` after conversation creation, showing name, type, and presence of `.file` object for each attachment.
- **Line 1327 (`sendMessage`)**: Logs the built `displayAttachments` payload before sending the message.

All browser console logs are prefixed with `[DEBUG]` for easy filtering.

### Server Logs (extension_server.py, extension.py)

- **`ext_upload_doc` (lines 1964-2019)**: 
  - Line 1966: Request received with user email, conversation ID, and file presence
  - Line 1970: PDF file details (filename, content_type)
  - Line 1980: Bytes read from uploaded file
  - Line 1983: PDF opened, page count
  - Line 1993: Extracted page count and character count
  - Line 1997: Truncation notification (if over 128K chars)
  - Line 2001: System message added to conversation with content length

- **`get_history_for_llm` (extension.py lines 2060-2101)**: 
  - Line 2076: Total message count and history length limit
  - Line 2087: System message count found
  - Line 2090: Recent non-system message count selected
  - Line 2097: Final message list details with role breakdown

- **`add_message` (extension.py lines 2042-2064)**:
  - Line 2062: Message added to conversation with role, content length, and message ID

- **`ext_chat` (extension_server.py lines 1777-1794)**:
  - Line 1778: History retrieved from `get_history_for_llm()` with message count and role list
  - Line 1785: System message extraction count
  - Line 1788: Merged system prompt final length (after merging PDF text)
  - Line 1793: Final message list count sent to LLM

- **`build_agent_prompt_from_history` (extension_server.py lines 461-485)**:
  - Line 470: Document parts extracted from system messages
  - Line 473: Reference Documents section added with character count
  - Line 483: Final agent prompt length and section count

All server logs are prefixed with `[DEBUG]` for filtering. Use these logs to trace the entire PDF flow from browser upload through LLM prompt construction.

### Database Verification Queries

```sql
-- Verify system message storage
SELECT role, LENGTH(content) as content_length, SUBSTR(content, 1, 100) as preview
FROM ExtensionMessages 
WHERE conversation_id = ? 
ORDER BY created_at;

-- Verify display_attachments persistence
SELECT message_id, display_attachments 
FROM ExtensionMessages 
WHERE conversation_id = ? AND display_attachments IS NOT NULL;
```

### Debugging Workflow

1. **Browser console**: Filter for `[DEBUG]` to see attachment upload flow
2. **Extension server logs**: Check `extension_server.py` output for PDF text extraction and prompt construction
3. **Database**: Query `ExtensionMessages` table to verify system message persistence
4. **LLM prompt inspection**: Review final `messages` list in server logs before `call_llm()` to confirm PDF text is present

## Implementation Notes

- Thumbnail generation: HTML Canvas, max 80x80 JPEG at 70% quality (main UI) / 100x100 at 60% (extension)
- PDF attachments rendered as styled badges with filename (no thumbnail image)
- Max 5 attachments per message (extension-enforced limit)
- `persist_current_turn()` has 7 call sites across different code paths in `reply()` — all pass `display_attachments`
- Doc reference injection preserves original user text for clean persistence
- Extension uses `ALTER TABLE ADD COLUMN` migration (silent catch for existing columns)
- BM25 index built with `rank_bm25.BM25Okapi`, serialized with dill via `save_local()`
- `doc_id` is deterministic from `mmh3.hash(source + filetype + doctype)` so FastDocIndex and full DocIndex for the same file get the same id — enables in-place promotion
- FastDocIndex `set_api_keys()` overridden to skip FAISS index lookup (no "indices" in `store_separate`)

## Known Limitations

- Extension PDFs limited to 128K chars of extracted text
- BM25 is keyword-based (no semantic search) until promoted to full DocIndex with FAISS
- Extension has no "Add to Conversation" or promotion flow — PDFs are always system messages
- No automated tests for attachment flows
- Re-attached entries have `file: null` so they cannot be downloaded if the original file is no longer available on disk
