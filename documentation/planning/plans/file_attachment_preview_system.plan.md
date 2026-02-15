# File Attachment Preview & Persistence System

**Version:** 1.1  
**Created:** 2026-02-15  
**Status:** Implementation Complete  
**Estimated Effort:** 4-6 days (Extension: 2-3 days, Main UI: 2-3 days)

**Implementation Summary:** All Phase 1 (Extension) and Phase 2 (Main UI) tasks are complete. Two post-implementation bugs were found and fixed — see Section 9.

---

## 1. Objectives

### What We're Building

A unified file attachment experience across both the Chrome extension sidebar and the main web UI:

1. **Extension: PDF drag-and-drop support** — Currently only accepts `image/*`. Add PDF support so users can drop PDFs into the extension for processing.
2. **Extension: Full-body drag-and-drop feedback** — Drag targets already include `mainView` (entire side panel), but visual feedback (highlight) only shows on `inputWrapper`. Add panel-wide visual drag feedback.
3. **Persistent attachment previews in rendered messages** — In both UIs, when a user sends a message with images/PDFs attached, the attachment thumbnails should render in the conversation message and survive page reload/conversation reload.
4. **Main UI: Preview thumbnails above message input** — Extension already shows 64×64 thumbnails below the input for pending attachments. Main UI has no preview at all. Add similar preview strip.

### What We're NOT Building

- No changes to LLM context construction (images already go to LLM correctly in both UIs)
- No new document processing pipeline (PDFs in extension will reuse the existing `/upload_doc_to_conversation` endpoint)
- No changes to how the main UI sends uploaded documents to the server (that pipeline works fine)
- No changes to conversation reload/list APIs beyond adding the new `display_attachments` field

---

## 2. Current Architecture

### 2.1 Extension UI (sidepanel.js)

**File:** `extension/sidepanel/sidepanel.js`

| Component | Current Behavior | Lines |
|-----------|-----------------|-------|
| **Drag targets** | Bound to `[inputWrapper, mainView]` via `dragTargets.forEach(...)` | 452-463 |
| **Drop handler** | `handleImageDrop(e)` — calls `addImageFiles(files)` | 1820-1827 |
| **File validation** | `if (!file.type.startsWith('image/')) continue;` — rejects non-images | 1795 |
| **Pending state** | `state.pendingImages[]` — array of `{id, name, dataUrl}` | 27, 1806-1810 |
| **Preview rendering** | `renderImageAttachments()` — 64×64 thumbnails in `#image-attachments` div | 1759-1784 |
| **Send flow** | `sendMessage()` maps `pendingImages` → `imagesToSend` data URLs, sends via `API.sendMessageStreaming()` as `images[]` | 1177, 1340-1349 |
| **User message object** | `{message_id, role, content, created_at, images: imagesToSend}` — ephemeral, client-only | 1268-1274 |
| **Message rendering** | `renderMessage(msg)` — checks `msg.images` array, renders `<img class="message-image">` | 1030-1059 |
| **On reload** | `selectConversation()` → `API.getConversation()` — messages come from DB, no `images` field → images disappear | 899-924 |

**File:** `extension/sidepanel/sidepanel.html`
- `#image-attachments` div at line 359 (below `#input-wrapper`)
- `#message-input` textarea at line 347

**File:** `extension/sidepanel/sidepanel.css`
- `.input-wrapper.drag-over` — drag highlight on input area only (line 1213-1216)
- `.image-attachments` — flex container for pending thumbnails (line 1262-1267)
- `.image-attachment` — 64×64 thumbnail box with remove button (lines 1269-1298)
- `.message-images` — grid for images inside rendered messages (lines 999-1004)
- `.message-image` — individual image in message (lines 1006-1011)

**File:** `extension/shared/api.js`
- `sendMessageStreaming()` sends `images: data.images` to `/ext/chat/<id>` (line 467-474)

**File:** `extension_server.py`
- `ext_chat()` receives `images[]` from request, passes to LLM as multimodal content (lines 1535-1787)
- Images are NOT stored in DB — only used for the current LLM call
- `ext_get_conversation()` returns `conv.to_dict()` which includes messages from DB (line 1416)

**File:** `extension.py`
- `ExtensionDB.add_message()` — stores `(message_id, conversation_id, role, content, page_context, created_at)` — NO images column (lines 859-908)
- `ExtensionDB.get_messages()` — returns `{message_id, role, content, page_context, created_at}` — no images (lines 915-967)
- `ExtensionMessages` table schema: `message_id TEXT, conversation_id TEXT, role TEXT, content TEXT, page_context TEXT, created_at TEXT` (lines 319-329)

### 2.2 Main UI (interface/)

**File:** `interface/common-chat.js`

| Component | Current Behavior | Lines |
|-----------|-----------------|-------|
| **Drag targets** | `$(document)` — whole page accepts drops | 2097-2113 |
| **Drop handler** | Calls `uploadFile(file)` for each file | 2106-2113 |
| **Upload flow** | `uploadFile_internal()` → `POST /upload_doc_to_conversation/<id>` as FormData (server-side document processing) | 1925-1976 |
| **File types** | PDF, Word, images, audio, markdown, CSV, Excel, JSON — extensive (via `#chat-file-upload` accept attr) | HTML line 300 |
| **Pending state** | **None** — files upload immediately, no client-side tracking | — |
| **Preview** | **None** — no thumbnail/preview mechanism exists | — |
| **Send flow** | `ChatManager.sendMessage()` sends `{messageText, checkboxes, links, search}` — no attachments | 2664-2706 |
| **Message format** | `{message_id, text, sender, user_id, conversation_id, show_hide, config}` — no attachments field | Conversation.py 3442-3460 |
| **Message rendering** | `renderMessages()` creates Bootstrap cards with `message.text` as markdown — no attachment rendering | 2264-2658 |

**File:** `interface/interface.html`
- `#messageText` textarea at line 309
- `#chat-file-upload` hidden file input at line 300
- `#chat-file-upload-span` paperclip icon trigger at line 296-301
- `#uploadProgressContainer` spinner at lines 319-326
- No `#image-attachments` equivalent exists

**File:** `Conversation.py`
- `persist_current_turn()` creates message dicts: `{message_id, text, show_hide, sender, user_id, conversation_id, config, answer_tldr}` (lines 3442-3460)
- `get_message_list()` returns messages from storage, backfills `message_short_hash` (lines 8439-8460)
- Messages stored in `conversation.json` as part of the messages array

**File:** `endpoints/conversations.py`
- `/send_message/<id>` — accepts `{messageText, checkboxes, links, search}` (line 1326-1425)
- `/list_messages_by_conversation/<id>` — returns `conversation.get_message_list()` (line 64-86)

---

## 3. Design Decisions

### 3.1 `display_attachments` Field

Both UIs will store a `display_attachments` JSON array in each message for rendering purposes. This field:

- **Does NOT go into LLM context** — purely for UI display
- **Persists across reloads** — stored in DB (extension) or conversation.json (main)
- **Contains small thumbnails** — not full-resolution images (to keep storage reasonable)

**Schema:**
```json
{
  "display_attachments": [
    {
      "type": "image",
      "name": "screenshot.png",
      "thumbnail": "data:image/jpeg;base64,...",  // Small ~100px thumbnail
      "original_data_url": null  // Not stored (too large), or could be a reference
    },
    {
      "type": "pdf",
      "name": "document.pdf",
      "thumbnail": null,  // PDFs get an icon, not a thumbnail
      "doc_id": "abc123"  // Reference to uploaded document if applicable
    }
  ]
}
```

### 3.2 Thumbnail Generation Strategy

- **Images**: Resize to max 100×100 using HTML Canvas, convert to JPEG at 60% quality → ~2-5KB per thumbnail
- **PDFs**: No thumbnail — render as a styled badge with filename and PDF icon
- **Documents** (Word, etc.): Same as PDF — styled badge with filename

### 3.3 Extension PDF Handling

When a PDF is dropped in the extension:
1. Show a filename badge in the pending attachments area (not a thumbnail)
2. Upload to the extension server via a new `/ext/upload_doc/<conversation_id>` endpoint
3. The extension server routes to the main server's document processing pipeline (or uses its own)
4. The PDF is treated as a document attachment (like page context), not as an image for the LLM

**Alternative (simpler, recommended for v1)**: For now, when a PDF is dropped in the extension, show it in the pending area, but on send, upload it as a document to the existing `/upload_doc_to_conversation/<id>` endpoint on the main server. This reuses existing infrastructure and the extension server doesn't need a new endpoint.

### 3.4 Main UI Image Handling Change

Currently, **all** dropped files (images included) go through `uploadFile()` → `/upload_doc_to_conversation/<id>`. This treats images as documents to be chunked and indexed.

For the preview feature:
- Images dropped will STILL upload via the same pipeline (no change to backend)
- But we also capture a thumbnail and store it in `pendingAttachments[]` for preview
- On message send, the `display_attachments` array is included in the request
- The backend stores it in the message dict alongside `text`, `sender`, etc.

---

## 4. Implementation Plan

### Phase 1: Extension Changes (Groups A + B + C-extension)

#### Milestone M1: PDF Support in Extension Drag-and-Drop

**Objective:** Allow PDFs to be dropped into the extension side panel alongside images.

##### Task A1: Rename and extend `addImageFiles()` to `addAttachmentFiles()`

**File:** `extension/sidepanel/sidepanel.js`  
**Lines:** 1791-1814

**Current code (line 1795):**
```javascript
if (!file.type.startsWith('image/')) continue;
```

**Changes:**
1. Rename function `addImageFiles` → `addAttachmentFiles`
2. Accept `image/*` AND `application/pdf` file types
3. For images: keep existing base64 data URL behavior
4. For PDFs: create a structured attachment object with `{id, name, type: 'pdf', dataUrl: null, size: file.size, file: file}` — store the File object for later upload
5. Update the caller `handleImageDrop` to call new function name

**Also update:**
- `handleImageDrop()` (line 1820) — call `addAttachmentFiles` instead of `addImageFiles`
- State field name: Keep `state.pendingImages` as-is for now (rename would be too many changes), but the array now holds both image and PDF attachment objects

**Acceptance criteria:**
- PDF files dropped into input area are accepted and added to `state.pendingImages`
- Non-image, non-PDF files are still rejected
- Max 5 attachments limit still enforced

##### Task A2: Update `renderImageAttachments()` to handle PDFs

**File:** `extension/sidepanel/sidepanel.js`  
**Lines:** 1759-1784

**Changes:**
1. For image attachments (has `dataUrl`): render as before — `<img src="${img.dataUrl}">`
2. For PDF attachments (type === 'pdf'): render a styled badge with PDF icon + filename
3. Both types get the × remove button

**New HTML for PDF:**
```html
<div class="image-attachment pdf-attachment" data-id="${att.id}">
    <div class="pdf-badge">
        <svg>...</svg>  <!-- PDF icon -->
        <span class="pdf-name">${att.name}</span>
    </div>
    <button class="remove-btn" aria-label="Remove attachment">×</button>
</div>
```

**File:** `extension/sidepanel/sidepanel.css`  
**Add new styles:**
```css
.pdf-attachment .pdf-badge {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    font-size: 10px;
    color: var(--text-secondary);
    padding: 4px;
}
.pdf-badge svg { /* PDF icon */ }
.pdf-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60px; }
```

**Acceptance criteria:**
- PDF attachments show as styled badges in the preview area
- Image attachments still show as thumbnails
- Both have working remove buttons

##### Task A3: Handle PDF upload on send

**File:** `extension/sidepanel/sidepanel.js`  
**Function:** `sendMessage()` (line 1175)

**Changes:**
1. Separate pending attachments into images and PDFs
2. Images: send as `images[]` data URLs (existing behavior)
3. PDFs: upload via `POST /upload_doc_to_conversation/<conv_id>` to the main server (FormData), before or alongside the chat message
4. After upload, the PDF becomes a conversation document (existing pipeline handles indexing)

**New helper function:**
```javascript
async function uploadPendingPdfs(conversationId) {
    const pdfs = state.pendingImages.filter(att => att.type === 'pdf');
    for (const pdf of pdfs) {
        const formData = new FormData();
        formData.append('pdf_file', pdf.file);
        await fetch(`${API_BASE}/upload_doc_to_conversation/${conversationId}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });
    }
}
```

**Note:** We need to verify that the extension server either:
- Proxies the upload to the main server, OR
- Has its own document upload endpoint

**Check needed**: Does the extension server already have `/upload_doc_to_conversation`? If not, we need to add a proxy or use the extension server's existing infrastructure.

**Alternative (simpler):** Add a new `/ext/upload_doc/<conversation_id>` endpoint to `extension_server.py` that accepts FormData PDF and processes it similarly to how the main server does. This keeps the extension self-contained.

**Acceptance criteria:**
- PDFs are uploaded and processed when user sends a message
- The PDF content becomes available as a conversation document
- Progress feedback shown to user during upload

##### Task A4: Update `updateSendButton()` for mixed attachments

**File:** `extension/sidepanel/sidepanel.js`  
**Lines:** 1136-1140

**Current:** `const hasImages = state.pendingImages.length > 0;`  
**No change needed** — this already checks the array length, which works for both images and PDFs.

---

#### Milestone M2: Full-Body Drag-and-Drop Visual Feedback

**Objective:** Ensure drag-and-drop works across the entire extension side panel with visible feedback.

##### Task B1: Verify existing drag target behavior

**File:** `extension/sidepanel/sidepanel.js`  
**Lines:** 452-463

**Current code:**
```javascript
const dragTargets = [inputWrapper, mainView].filter(Boolean);
dragTargets.forEach((target) => {
    target.addEventListener('dragover', (e) => {
        e.preventDefault();
        inputWrapper?.classList.add('drag-over');
    });
    target.addEventListener('dragleave', () => {
        inputWrapper?.classList.remove('drag-over');
    });
    target.addEventListener('drop', handleImageDrop);
});
```

**Analysis:** `mainView` is already a drag target, so full-body drop WORKS. But:
- Only `inputWrapper` gets the `drag-over` CSS class (highlight)
- User gets no visual feedback when dragging over the panel body (outside input area)

##### Task B2: Add panel-wide drag visual feedback

**File:** `extension/sidepanel/sidepanel.js`  
**Lines:** 452-463

**Changes:**
1. When drag enters `mainView`, add a CSS class to the entire `mainView` element
2. Use a drag counter to handle nested dragenter/dragleave correctly
3. On drop or drag-leave-panel, remove the class

**Updated code pattern:**
```javascript
let dragCounter = 0;
const dragTargets = [inputWrapper, mainView].filter(Boolean);

if (mainView) {
    mainView.addEventListener('dragenter', (e) => {
        e.preventDefault();
        dragCounter++;
        mainView.classList.add('panel-drag-over');
    });
    mainView.addEventListener('dragleave', () => {
        dragCounter--;
        if (dragCounter <= 0) {
            dragCounter = 0;
            mainView.classList.remove('panel-drag-over');
        }
    });
    mainView.addEventListener('dragover', (e) => {
        e.preventDefault();
    });
    mainView.addEventListener('drop', (e) => {
        dragCounter = 0;
        mainView.classList.remove('panel-drag-over');
        handleImageDrop(e);  // will be renamed to handleAttachmentDrop
    });
}
```

**File:** `extension/sidepanel/sidepanel.css`  
**Add:**
```css
.panel-drag-over {
    outline: 2px dashed var(--accent);
    outline-offset: -4px;
    background: rgba(var(--accent-rgb), 0.05);
}
```

**Also:** Keep the existing `inputWrapper` highlight for when dragging directly over the input area.

**Acceptance criteria:**
- Dragging a file anywhere over the extension side panel shows a dashed outline
- Dropping a file anywhere on the panel accepts it (images + PDFs)
- Visual feedback disappears on drop or drag-leave

---

#### Milestone M3: Persistent Attachment Display in Extension Messages

**Objective:** When a user sends a message with images/PDFs, thumbnails persist in the rendered message even after conversation reload.

##### Task C1: Add `display_attachments` column to `ExtensionMessages` table

**File:** `extension.py`  
**Lines:** 317-330 (table schema)

**Changes:**
1. Add migration logic in `ExtensionDB.__init__()` to add column if not exists:
```python
# After table creation, add migration:
try:
    cursor.execute("ALTER TABLE ExtensionMessages ADD COLUMN display_attachments TEXT")
except:
    pass  # Column already exists
```

**Acceptance criteria:**
- Existing databases get the column added without data loss
- New databases create the column in the table definition

##### Task C2: Update `ExtensionDB.add_message()` to accept `display_attachments`

**File:** `extension.py`  
**Function:** `add_message()` (lines 859-908)

**Changes:**
1. Add `display_attachments: list = None` parameter
2. Store as JSON string in the new column
3. Return it in the message dict

**Updated signature:**
```python
def add_message(self, conversation_id, role, content, page_context=None, display_attachments=None):
```

**Updated INSERT:**
```sql
INSERT INTO ExtensionMessages
(message_id, conversation_id, role, content, page_context, display_attachments, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
```

**Acceptance criteria:**
- `display_attachments` stored as JSON string in DB
- Returned in the message dict on creation

##### Task C3: Update `ExtensionDB.get_messages()` to return `display_attachments`

**File:** `extension.py`  
**Function:** `get_messages()` (lines 915-967)

**Changes:**
1. Add `display_attachments` to the SELECT query
2. Parse JSON when building return dicts

**Updated SELECT:**
```sql
SELECT message_id, role, content, page_context, display_attachments, created_at
FROM ExtensionMessages
WHERE conversation_id = ?
ORDER BY created_at ASC
```

**Updated return dict:**
```python
{
    'message_id': r[0],
    'role': r[1],
    'content': r[2],
    'page_context': json.loads(r[3]) if r[3] else None,
    'display_attachments': json.loads(r[4]) if r[4] else None,
    'created_at': r[5]
}
```

**Acceptance criteria:**
- `display_attachments` returned as parsed JSON array (or None) in message dicts
- Existing messages without attachments return `null`

##### Task C4: Generate thumbnails on the client side

**File:** `extension/sidepanel/sidepanel.js`  
**New helper function**

**Add function `generateThumbnail(dataUrl, maxSize=100)`:**
```javascript
function generateThumbnail(dataUrl, maxSize = 100) {
    return new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
            const canvas = document.createElement('canvas');
            const scale = Math.min(maxSize / img.width, maxSize / img.height, 1);
            canvas.width = img.width * scale;
            canvas.height = img.height * scale;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            resolve(canvas.toDataURL('image/jpeg', 0.6));
        };
        img.onerror = () => resolve(null);
        img.src = dataUrl;
    });
}
```

This produces ~2-5KB thumbnails per image.

**Acceptance criteria:**
- Thumbnail generated for each image attachment before sending
- PDF attachments get `null` thumbnail (rendered as badge/icon)

##### Task C5: Build `display_attachments` in `sendMessage()` and send to server

**File:** `extension/sidepanel/sidepanel.js`  
**Function:** `sendMessage()` (line 1175)

**Changes:**
1. Before sending, build `display_attachments` array from `state.pendingImages`:
   - For images: `{type: 'image', name, thumbnail: await generateThumbnail(dataUrl)}`
   - For PDFs: `{type: 'pdf', name, thumbnail: null}`
2. Include `display_attachments` in the user message object added to `state.messages`
3. Send `display_attachments` to the server alongside the message

**Changes to user message creation (line 1268-1274):**
```javascript
const displayAttachments = await buildDisplayAttachments(state.pendingImages);
const userMessage = {
    message_id: 'temp-user-' + Date.now(),
    role: 'user',
    content: text || '[Attachment]',
    created_at: new Date().toISOString(),
    images: imagesToSend,  // Keep for live rendering
    display_attachments: displayAttachments  // For persistence
};
```

**File:** `extension/shared/api.js`  
**Functions:** `sendMessage()` and `sendMessageStreaming()`

**Changes:**
- Add `display_attachments: data.display_attachments` to the request body

**Acceptance criteria:**
- `display_attachments` sent to server with each message that has attachments
- Thumbnails are small (~2-5KB per image)

##### Task C6: Store `display_attachments` in the server when saving messages

**File:** `extension_server.py`  
**Function:** `ext_chat()` (line 1535)

**Changes:**
1. Extract `display_attachments` from request data
2. Pass to `conv.add_message()` for the user message

**Current (line 1586):**
```python
user_msg = conv.add_message("user", message, page_context)
```

**Updated:**
```python
display_attachments = data.get("display_attachments")
user_msg = conv.add_message("user", message, page_context, display_attachments=display_attachments)
```

**File:** `extension.py`  
**Class:** `ExtensionConversation.add_message()` (lines 1876-1890)

**Changes:**
1. Accept `display_attachments` parameter
2. Pass through to `self.db.add_message()`

**Acceptance criteria:**
- User messages with attachments have `display_attachments` stored in DB
- Assistant messages have `display_attachments = null` (no attachments)

##### Task C7: Update `renderMessage()` to use `display_attachments` for persistence

**File:** `extension/sidepanel/sidepanel.js`  
**Function:** `renderMessage()` (lines 1030-1059)

**Current (lines 1043-1048):**
```javascript
const images = Array.isArray(msg.images) ? msg.images : [];
const imagesHtml = images.length > 0
    ? `<div class="message-images">${images.map((src) => `
        <img class="message-image" src="${src}" alt="Attached image">
    `).join('')}</div>`
    : '';
```

**Updated:**
```javascript
// Use display_attachments for persistent rendering, fall back to images for live messages
const attachments = Array.isArray(msg.display_attachments) ? msg.display_attachments : [];
const liveImages = Array.isArray(msg.images) ? msg.images : [];

let attachmentsHtml = '';
if (attachments.length > 0) {
    attachmentsHtml = `<div class="message-images">${attachments.map(att => {
        if (att.type === 'image' && att.thumbnail) {
            return `<img class="message-image" src="${att.thumbnail}" alt="${att.name || 'Image'}" title="${att.name || 'Image'}">`;
        } else if (att.type === 'pdf') {
            return `<div class="message-pdf-badge"><svg>...</svg><span>${att.name}</span></div>`;
        }
        return '';
    }).join('')}</div>`;
} else if (liveImages.length > 0) {
    // Fallback for live messages before persistence
    attachmentsHtml = `<div class="message-images">${liveImages.map(src =>
        `<img class="message-image" src="${src}" alt="Attached image">`
    ).join('')}</div>`;
}
```

**File:** `extension/sidepanel/sidepanel.css`  
**Add styles for PDF badge in messages:**
```css
.message-pdf-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 12px;
    color: var(--text-secondary);
}
```

**Acceptance criteria:**
- On first render (live), full-resolution images show from `msg.images`
- On reload, thumbnails show from `msg.display_attachments`
- PDF attachments show as styled badges in both cases
- Messages without attachments render exactly as before

---

### Phase 2: Main UI Changes (Groups C-main + D)

#### Milestone M4: Main UI Preview Above Message Input

**Objective:** Show pending file attachment previews above the message input area, similar to the extension.

##### Task D1: Add `#attachment-preview` container to HTML

**File:** `interface/interface.html`  
**Location:** Above or below the `#chat-controls` div (around line 291)

**Add:**
```html
<div id="attachment-preview" class="attachment-preview" style="display: none;">
    <!-- Thumbnails rendered here dynamically -->
</div>
```

**Placement:** Between `#chatView` and `#chat-controls`, or inside `#chat-controls` above the input row.

##### Task D2: Create pending attachments JS state and render function

**File:** `interface/common-chat.js`  
**Add to ChatManager or as module-level state:**

```javascript
var pendingAttachments = [];  // [{id, name, type, thumbnail, file}]

function renderAttachmentPreviews() {
    var container = $('#attachment-preview');
    if (pendingAttachments.length === 0) {
        container.hide().empty();
        return;
    }
    container.show();
    var html = pendingAttachments.map(function(att) {
        if (att.type === 'image') {
            return '<div class="att-preview" data-id="' + att.id + '">' +
                '<img src="' + att.thumbnail + '" alt="' + att.name + '">' +
                '<button class="att-remove-btn" title="Remove">×</button></div>';
        } else {
            return '<div class="att-preview att-file" data-id="' + att.id + '">' +
                '<i class="fa fa-file-pdf-o"></i> <span>' + att.name + '</span>' +
                '<button class="att-remove-btn" title="Remove">×</button></div>';
        }
    }).join('');
    container.html(html);
    
    container.find('.att-remove-btn').off('click').on('click', function() {
        var id = $(this).closest('.att-preview').data('id');
        pendingAttachments = pendingAttachments.filter(function(a) { return a.id !== id; });
        renderAttachmentPreviews();
    });
}
```

##### Task D3: Hook drag-drop to populate pending attachments (images)

**File:** `interface/common-chat.js`  
**Lines:** 2097-2113 (document-level drop handler)

**Changes:**
For **image** files (JPEG, PNG, etc.): 
1. Generate a thumbnail (Canvas resize)
2. Add to `pendingAttachments[]`
3. Render preview
4. Still call `uploadFile(file)` for server-side processing

For **non-image** files (PDF, Word, etc.):
1. Create a file badge entry in `pendingAttachments[]`
2. Render preview
3. Call `uploadFile(file)` for server-side processing

**Key:** The upload happens immediately (existing behavior), but we also capture a preview.

##### Task D4: Include `display_attachments` in `sendMessage()`

**File:** `interface/common-chat.js`  
**Function:** `ChatManager.sendMessage()` (line 2664)

**Changes:**
1. Build `display_attachments` from `pendingAttachments[]`
2. Include in the request body
3. Clear `pendingAttachments[]` after send

**Updated request body:**
```javascript
var requestBody = {
    'messageText': messageText,
    'checkboxes': checkboxes,
    'links': links,
    'search': search,
    'display_attachments': pendingAttachments.map(function(a) {
        return { type: a.type, name: a.name, thumbnail: a.thumbnail };
    })
};
```

##### Task D5: Render `display_attachments` in messages

**File:** `interface/common-chat.js`  
**Function:** `renderMessages()` (line 2264)

**Changes:**
After creating `cardBody` and `textElem` (line 2346-2350), check for `display_attachments`:

```javascript
if (message.display_attachments && message.display_attachments.length > 0) {
    var attachHtml = '<div class="message-attachments">';
    message.display_attachments.forEach(function(att) {
        if (att.type === 'image' && att.thumbnail) {
            attachHtml += '<img class="msg-att-thumb" src="' + att.thumbnail + '" alt="' + (att.name || 'Image') + '">';
        } else {
            attachHtml += '<span class="msg-att-badge"><i class="fa fa-file"></i> ' + (att.name || 'File') + '</span>';
        }
    });
    attachHtml += '</div>';
    cardBody.append($(attachHtml));
}
```

##### Task D6: Add CSS for preview area and message attachments

**File:** `interface/style.css` (or inline in `interface.html`)

```css
/* Pending attachment preview strip */
.attachment-preview {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 6px 10px;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    margin-bottom: 4px;
    background: #fafafa;
}
.att-preview {
    position: relative;
    width: 52px;
    height: 52px;
    border-radius: 4px;
    overflow: hidden;
    border: 1px solid #ddd;
}
.att-preview img {
    width: 100%;
    height: 100%;
    object-fit: cover;
}
.att-preview.att-file {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    padding: 4px;
    background: #f0f0f0;
}
.att-remove-btn {
    position: absolute;
    top: 2px;
    right: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: none;
    background: rgba(0,0,0,0.5);
    color: #fff;
    font-size: 11px;
    cursor: pointer;
    line-height: 16px;
    text-align: center;
    padding: 0;
}

/* Message attachment thumbnails */
.message-attachments {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
}
.msg-att-thumb {
    max-width: 120px;
    max-height: 90px;
    border-radius: 4px;
    border: 1px solid #e0e0e0;
    object-fit: cover;
}
.msg-att-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    background: #f0f0f0;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 0.75rem;
}
```

---

#### Milestone M5: Main UI Backend — Store `display_attachments`

##### Task C10: Accept `display_attachments` in `/send_message` endpoint

**File:** `endpoints/conversations.py`  
**Function:** `send_message()` (line 1326)

**Changes:**
1. Extract `display_attachments` from `request.json`
2. Inject into the query dict so `Conversation.__call__` can pass it to `persist_current_turn()`

```python
query = request.json
display_attachments = query.pop('display_attachments', None)
# ... later, inject into conversation context for persistence
```

##### Task C11: Store `display_attachments` in `persist_current_turn()`

**File:** `Conversation.py`  
**Function:** `persist_current_turn()` (line 3323)

**Changes:**
1. Accept `display_attachments` parameter (or extract from query dict)
2. Add to the user message dict:

```python
preserved_messages = [
    {
        "message_id": message_ids["user_message_id"],
        "text": query,
        "show_hide": "show",
        "sender": "user",
        "user_id": self.user_id,
        "conversation_id": self.conversation_id,
        "display_attachments": display_attachments,  # NEW
    },
    ...
]
```

**Acceptance criteria:**
- `display_attachments` persisted in conversation.json as part of the user message
- `get_message_list()` returns it (no changes needed — it reads the full message dict)
- Old messages without the field render normally (missing field = no attachments)

---

## 5. File Change Summary

### Phase 1 (Extension) — Files Modified

| File | Changes |
|------|---------|
| `extension/sidepanel/sidepanel.js` | Rename `addImageFiles` → `addAttachmentFiles`, accept PDFs, update `renderImageAttachments`, generate thumbnails, build `display_attachments`, update `renderMessage`, update drag handlers for panel feedback |
| `extension/sidepanel/sidepanel.css` | Add `.panel-drag-over`, `.pdf-attachment`, `.message-pdf-badge` styles |
| `extension/shared/api.js` | Add `display_attachments` to `sendMessage()` and `sendMessageStreaming()` request bodies |
| `extension.py` | Add `display_attachments` column to `ExtensionMessages`, update `add_message()`, `get_messages()` |
| `extension_server.py` | Pass `display_attachments` through in `ext_chat()` and `ExtensionConversation.add_message()` |

### Phase 2 (Main UI) — Files Modified

| File | Changes |
|------|---------|
| `interface/interface.html` | Add `#attachment-preview` container div |
| `interface/common-chat.js` | Add `pendingAttachments` state, `renderAttachmentPreviews()`, thumbnail generation, hook drag-drop, update `sendMessage()`, update `renderMessages()` |
| `interface/style.css` | Add `.attachment-preview`, `.att-preview`, `.msg-att-thumb`, `.msg-att-badge`, `.message-attachments` styles |
| `endpoints/conversations.py` | Extract and pass `display_attachments` from request |
| `Conversation.py` | Store `display_attachments` in user message dict in `persist_current_turn()` |

---

## 6. Risks and Alternatives

### Risk: Thumbnail storage size
- **Mitigation:** Canvas resize to 100×100, JPEG 60% quality → ~2-5KB per image. Max 5 per message = ~25KB worst case. Negligible for SQLite or JSON storage.

### Risk: Extension PDF upload endpoint
- **Challenge:** Extension server doesn't have `/upload_doc_to_conversation`. Need either a new endpoint or proxy to main server.
- **Mitigation:** For v1, use a simple proxy endpoint on extension server that forwards to main server. Or, if both servers share the same storage directory, call the main server's endpoint directly.
- **Alternative:** Skip PDF upload in extension for v1, just show the preview badge but don't process the PDF content. Inform user that PDF indexing requires the main UI.

### Risk: Base64 data URLs in DB (extension)
- **Concern:** Storing base64 thumbnails in SQLite TEXT column.
- **Mitigation:** Thumbnails are ~2-5KB each as base64. A message with 5 images = ~25KB. This is well within SQLite's comfortable range.

### Risk: Breaking existing extension messages on schema migration
- **Mitigation:** `ALTER TABLE ADD COLUMN` is backward-compatible. Existing rows get `NULL` for the new column. Code handles `null` display_attachments gracefully.

### Risk: Main UI `sendMessage()` currently sends as `application/json`
- **Concern:** Cannot send FormData (for PDFs) and JSON in the same request.
- **Mitigation:** In main UI, files upload immediately on drop (existing behavior). `display_attachments` in `sendMessage()` contains only metadata/thumbnails (small JSON), not the actual files.

---

## 7. Testing Strategy

### Extension Tests
1. Drop image → appears as thumbnail in pending area → send → visible in message → reload conversation → thumbnail still visible
2. Drop PDF → appears as badge in pending area → send → badge visible in message → reload → badge still visible
3. Drop file anywhere on side panel → visual drag feedback on entire panel → file accepted
4. Drop non-image non-PDF → rejected (no preview, no upload)
5. Drop 6 files → only 5 accepted, alert shown
6. Remove attachment from pending area → disappears from preview, not sent

### Main UI Tests
1. Drop image → thumbnail appears above input area → send message → thumbnail in rendered message → reload → thumbnail persists
2. Drop PDF → file badge appears above input area → upload progress shown → send → badge in message → reload → badge persists
3. Remove preview before sending → attachment not included in message
4. Send message without attachments → works exactly as before (no regression)

---

## 8. Execution Order

### Immediate (this session): Extension Phase
1. Task C1: DB schema migration (`extension.py`)
2. Task C2 + C3: `add_message()` and `get_messages()` updates (`extension.py`)
3. Task C6: Server pass-through (`extension_server.py`, `extension.py` class)
4. Task A1: `addAttachmentFiles()` rename + PDF acceptance (`sidepanel.js`)
5. Task A2: `renderImageAttachments()` PDF badge support (`sidepanel.js`, `sidepanel.css`)
6. Task C4: `generateThumbnail()` helper (`sidepanel.js`)
7. Task C5: Build and send `display_attachments` (`sidepanel.js`, `api.js`)
8. Task C7: `renderMessage()` uses `display_attachments` (`sidepanel.js`, `sidepanel.css`)
9. Task B2: Panel-wide drag feedback (`sidepanel.js`, `sidepanel.css`)
10. Task A3: PDF upload on send (`sidepanel.js`)

### After verification: Main UI Phase
11. Task D1: Add `#attachment-preview` HTML (`interface.html`)
12. Task D2: JS state + render function (`common-chat.js`)
13. Task D3: Hook drag-drop (`common-chat.js`)
14. Task D6: CSS styles (`style.css`)
15. Task D4: Include in `sendMessage()` (`common-chat.js`)
16. Task D5: Render in messages (`common-chat.js`)
17. Task C10: Backend accept (`endpoints/conversations.py`)
18. Task C11: Backend store (`Conversation.py`)

---

## 9. Post-Implementation Bug Fixes

### Bug 1: display_attachments not persisting after page reload in main UI

**Root cause:** Only 2 of 7 `persist_current_turn()` call sites in `Conversation.py`'s `reply()` method passed `display_attachments`. The other 5 call sites (for single-link, single-doc, web-search-failed, and the main code path) silently dropped it, so most messages lost their attachment metadata.

**Fix:** Added `display_attachments=query.get("display_attachments")` to all 7 call sites in `reply()`.

**File:** `Conversation.py` — all `persist_current_turn` invocations now include `display_attachments`.

### Bug 2: LLM not reading attached doc content when replying

**Root cause:** When a file is drag-dropped, it's uploaded as a conversation document and gets a `doc_id`, but the message text doesn't contain `#doc_N` references. The existing `get_uploaded_documents_for_query()` pipeline only reads docs referenced with `#doc_N` syntax in the message text.

**Fix:** Added a doc reference injection block in `reply()` (before `attached_docs_future` creation) that:
1. Reads `display_attachments` from the query dict
2. Maps each attachment's `doc_id` to its `#doc_N` index via `uploaded_documents_list`
3. Appends missing `#doc_N` references to `query["messageText"]`
4. Saves the original clean text as `_user_text_before_da_injection` for persistence

**File:** `Conversation.py` — injection block at ~line 6011, `original_user_query` assignment at ~line 6114.
