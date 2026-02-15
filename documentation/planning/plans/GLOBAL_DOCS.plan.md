# Global Documents

**Created:** 2026-02-15
**Status:** Planning
**Depends On:** Existing DocIndex system (`DocIndex.py`), conversation document pipeline (`Conversation.py`, `endpoints/documents.py`), Blueprint architecture (`endpoints/__init__.py`)
**Related Docs:**
- `documentation/product/behavior/chat_app_capabilities.md` — Section 4: Document ingestion + document-grounded Q&A
- `documentation/api/external/external_api.md` — Documents section
- `documentation/api/external/external_api_implementation.md` — `endpoints/documents.py` details
- `documentation/dev/cursor/LOCK_CLEARANCE_QUICK_REF.md` — DocIndex lock file patterns

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals](#goals)
3. [Non-Goals](#non-goals)
4. [Current State](#current-state)
5. [Design Overview](#design-overview)
6. [Reference Syntax](#reference-syntax)
7. [Data Model](#data-model)
8. [Storage Layout](#storage-layout)
9. [Backend: Database Layer](#backend-database-layer)
10. [Backend: Endpoint Layer](#backend-endpoint-layer)
11. [Backend: Conversation Integration](#backend-conversation-integration)
12. [Frontend: UI Components](#frontend-ui-components)
13. [Frontend: JavaScript Logic](#frontend-javascript-logic)
14. [Promote Conversation Doc to Global Doc](#promote-conversation-doc-to-global-doc)
15. [Implementation Plan (Milestones)](#implementation-plan-milestones)
16. [Files to Create/Modify (Summary)](#files-to-createmodify-summary)
17. [Testing Plan](#testing-plan)
18. [Risks and Mitigations](#risks-and-mitigations)
19. [Alternatives Considered](#alternatives-considered)

---

## Problem Statement

Today every document (`DocIndex`) is scoped to a single conversation. The document is indexed under `{conversation_folder}/uploaded_documents/{doc_id}/` and tracked in that conversation's `uploaded_documents_list` field. If a user wants to reference the same document in a different conversation they must re-upload it, which:

1. **Wastes time.** Indexing takes 1-2 minutes per document (text extraction + FAISS embedding).
2. **Wastes storage.** Each upload creates a separate copy of the FAISS indices, chunks, and summaries.
3. **Creates inconsistency.** Two copies of the "same" document can drift if one gets summary updates the other doesn't.
4. **Breaks cross-conversation workflows.** A user working on a research topic across many conversations must manually manage document copies.

**What we need:**

- A way to index a document **once** and reference it from **any** conversation.
- A user-scoped "global document library" with CRUD operations.
- A reference syntax (`#gdoc_N` / `#global_doc_N`) that works in the existing reply flow alongside per-conversation `#doc_N` references.
- UI for creating, listing, viewing, and deleting global docs.
- Ability to "promote" a conversation-local doc to a global doc (move, not copy; avoid re-indexing).

---

## Goals

1. **Index once, use everywhere.** A global doc is indexed once and loadable from any conversation.
2. **Seamless conversation integration.** `#gdoc_1` and `#global_doc_1` work identically to `#doc_1` in the reply pipeline — same RAG, same answering, same detail levels.
3. **Full CRUD via UI.** Users can create (upload), list, view (PDF viewer), and delete global docs through modals in the web interface.
4. **Promote existing docs.** A conversation-scoped doc can be promoted to a global doc without re-indexing.
5. **User-scoped.** Each user has their own global doc library; docs are not shared across users.
6. **Minimal DocIndex changes.** DocIndex is already path-independent for loading. We should not modify DocIndex internals.

---

## Non-Goals

- **Cross-user sharing** of global docs (future feature).
- **Automatic de-duplication** (detecting that two uploads are the same document).
- **Versioning** of global docs.
- **Folders/tags** for organizing global docs (future enhancement).
- **Global doc references in PKB** or cross-conversation references system.

---

## Current State

### How conversation docs work today

**Storage:** Each conversation stores its docs under:
```
storage/conversations/{conversation_id}/uploaded_documents/{doc_id}/
    {doc_id}.index          ← dill-serialized DocIndex object
    indices/                ← FAISS vector stores
    raw_data/               ← Document chunks (JSON)
    static_data/            ← Source path, filetype, text (JSON)
    review_data/            ← Review/analysis (JSON)
    _paper_details/         ← Paper metadata (dill)
    locks/                  ← Per-field lock files
```

**Tracking:** `Conversation.uploaded_documents_list` is a list of tuples:
```python
[(doc_id, doc_storage_path, pdf_url), ...]
```

**Loading:** `Conversation.get_uploaded_documents()` calls `DocIndex.load_local(doc_storage_path)` for each tuple. `DocIndex.load_local()` is **path-independent** — it loads from any directory containing `{doc_id}.index` and sets `_storage` to the provided path. **No conversation ID is stored inside DocIndex.**

**API endpoints** (`endpoints/documents.py`):
- `POST /upload_doc_to_conversation/<cid>` — upload file or URL
- `GET /list_documents_by_conversation/<cid>` — list docs
- `GET /download_doc_from_conversation/<cid>/<doc_id>` — download
- `DELETE /delete_document_from_conversation/<cid>/<doc_id>` — delete

**Reference syntax in messages:**
- `#doc_1`, `#doc_2`, ... — reference the N-th conversation doc
- `#doc_all` / `#all_docs` — reference all conversation docs
- `#summary_doc_N` / `#dense_summary_doc_N` — force summary generation
- `#full_doc_N` / `#raw_doc_N` — get raw text

**Reply flow parsing** (all in `Conversation.py`):
1. `reply()` line 5454: `re.findall(r"#doc_\d+", ...)` parses doc references
2. `reply()` lines 5456-5460: checks for `#doc_all` / `#all_docs`
3. `reply()` lines 5810-5820: resolves references via `get_uploaded_documents_for_query()`
4. `get_uploaded_documents_for_query()` (line 4416): parses, resolves to DocIndex objects, classifies as readable/data, replaces references with enriched text
5. `get_multiple_answers()` (base.py ~line 4491): calls `doc.get_short_answer()` on each doc in parallel

**Key insight for implementation:** DocIndex has **zero coupling to conversations**. The only coupling is that `Conversation` stores `(doc_id, storage_path, url)` tuples and calls `DocIndex.load_local(path)`. We can store a DocIndex anywhere and load it the same way.

---

## Design Overview

```
                    ┌─────────────────────────────────┐
                    │        User's Global Docs        │
                    │   (DB table + filesystem store)   │
                    └───────────┬─────────────────────┘
                                │
              ┌─────────────────┼──────────────────┐
              │                 │                    │
    Conversation A      Conversation B       Conversation C
    #gdoc_1, #doc_1     #gdoc_1, #gdoc_2     #gdoc_1
              │                 │                    │
              └─────────────────┼──────────────────┘
                                │
                    ┌───────────▼─────────────────────┐
                    │      Reply Flow Merge Point       │
                    │  conversation_docs + global_docs  │
                    │       → unified attached_docs     │
                    └──────────────────────────────────┘
```

**Approach:**
1. New DB table `GlobalDocuments` in `users.db` tracks global docs per user.
2. New filesystem directory `storage/global_docs/{user_email_hash}/` stores DocIndex artifacts (identical structure to conversation docs).
3. New blueprint `endpoints/global_docs.py` provides CRUD API.
4. `Conversation.py` modified to resolve `#gdoc_N` / `#global_doc_N` references alongside `#doc_N`.
5. New UI modal for global docs management + a "Global Docs" button in the chat top bar.
6. Promotion endpoint moves DocIndex storage from conversation to global and updates DB.

---

## Reference Syntax

### In conversation messages

| Syntax | Meaning |
|--------|---------|
| `#gdoc_1` | Reference the 1st global doc (by display order) |
| `#global_doc_1` | Same as `#gdoc_1` (alias) |
| `#gdoc_all` | Reference all global docs |
| `#global_doc_all` | Same as `#gdoc_all` |
| `#summary_gdoc_1` | Force summary of global doc 1 |
| `#dense_summary_gdoc_1` | Force dense summary of global doc 1 |
| `#full_gdoc_1` | Get raw text of global doc 1 |

### Numbering

Global docs are numbered **per-user** in the order they appear in the DB (ordered by `created_at`). The numbering is stable: deleting `#gdoc_2` does not renumber `#gdoc_3` → `#gdoc_2`. Instead, the list response includes an `index` field and the UI shows the current position.

**Alternative considered:** Using `doc_id` hash instead of positional numbers. Rejected because `#gdoc_a8f3b2c1` is not user-friendly. The PKB system uses friendly IDs; we use simple sequential numbers since global docs are expected to be a small set (tens, not thousands).

**Clarification on numbering stability:** Since we use display-order position (not a persistent number), if a user has gdocs [A, B, C] and deletes B, then C becomes `#gdoc_2`. This matches how `#doc_N` works for conversation docs (positional). Users see the current numbering in the global docs list panel. This is simpler than maintaining a persistent numbering scheme and consistent with existing conversation doc behavior.

---

## Data Model

### New DB table: `GlobalDocuments`

```sql
CREATE TABLE IF NOT EXISTS GlobalDocuments (
    doc_id          TEXT NOT NULL,
    user_email      TEXT NOT NULL,
    display_name    TEXT,          -- user-editable name, defaults to DocIndex.title
    doc_source      TEXT NOT NULL, -- original URL or file path
    doc_storage     TEXT NOT NULL, -- filesystem path to DocIndex storage folder
    title           TEXT,          -- DocIndex-generated title (cached)
    short_summary   TEXT,          -- DocIndex-generated summary (cached)
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (doc_id, user_email)
);
```

**Indexes:**
```sql
CREATE INDEX IF NOT EXISTS idx_GlobalDocuments_user_email ON GlobalDocuments (user_email);
CREATE INDEX IF NOT EXISTS idx_GlobalDocuments_created_at ON GlobalDocuments (user_email, created_at);
```

**Why cache `title` and `short_summary` in the DB?** Listing global docs should not require loading every DocIndex from disk (dill deserialization + FAISS loading). The DB row has enough info for the list endpoint. Title/summary are populated after indexing completes and updated if DocIndex regenerates them.

---

## Storage Layout

```
storage/
├── global_docs/                          ← NEW top-level directory
│   ├── {user_email_hash}/                ← per-user subdirectory (md5 of email)
│   │   ├── {doc_id}/                     ← same structure as conversation docs
│   │   │   ├── {doc_id}.index
│   │   │   ├── indices/
│   │   │   ├── raw_data/
│   │   │   ├── static_data/
│   │   │   ├── review_data/
│   │   │   ├── _paper_details/
│   │   │   └── locks/
│   │   └── {doc_id}/
│   │       └── ...
│   └── {user_email_hash}/
│       └── ...
├── conversations/                        ← existing
├── users/                                ← existing
├── pdfs/                                 ← existing (shared temp upload dir)
├── locks/                                ← existing
└── ...
```

**Why hash the email?** Email addresses can contain characters invalid in directory names (`@`, `+`). Using `hashlib.md5(email.encode()).hexdigest()` gives a clean, fixed-length directory name. This pattern is common in the codebase (conversation IDs are already hashes).

**Lock directory:** Global docs use the same `storage/locks/` directory as conversation docs. Lock keys use the pattern `gdoc_{doc_id}` to avoid collisions with conversation doc locks (which use `{doc_id}` directly). Since doc_id is `mmh3.hash(source + filetype + type)`, a global doc and conversation doc from the same source *would* have the same doc_id — the `gdoc_` prefix distinguishes their locks.

---

## Backend: Database Layer

### New file: `database/global_docs.py`

Follows the pattern of `database/conversations.py` and `database/workspaces.py`.

```python
"""
Global document persistence helpers.

All functions use keyword-only arguments and open/close their own SQLite connections.
"""

# Key functions:

def add_global_doc(*, users_dir, user_email, doc_id, doc_source, doc_storage,
                   title="", short_summary="", display_name=""):
    """Insert a new global doc row. Deduplicates on (doc_id, user_email)."""

def list_global_docs(*, users_dir, user_email) -> list[dict]:
    """Return all global docs for a user, ordered by created_at ASC.
    Each dict: {doc_id, user_email, display_name, doc_source, doc_storage,
                title, short_summary, created_at, updated_at}."""

def get_global_doc(*, users_dir, user_email, doc_id) -> dict | None:
    """Return a single global doc row or None."""

def delete_global_doc(*, users_dir, user_email, doc_id):
    """Delete a global doc row. Does NOT delete filesystem storage (caller handles)."""

def update_global_doc_metadata(*, users_dir, user_email, doc_id,
                                title=None, short_summary=None, display_name=None):
    """Update cached metadata fields."""
```

All functions take `users_dir` as a keyword argument and derive the DB path as `os.path.join(users_dir, "users.db")`. They open and close their own connections (consistent with existing `database/` pattern).

### Modify: `database/connection.py` — `create_tables()`

Add the `GlobalDocuments` table creation and index creation to the existing `create_tables()` function, after the existing table definitions (around line 150).

---

## Backend: Endpoint Layer

### New file: `endpoints/global_docs.py`

New Flask Blueprint: `global_docs_bp`. Follows the exact pattern of `endpoints/documents.py`.

#### `POST /global_docs/upload`

Upload a new global document (file or URL).

**Request:**
- Multipart: `pdf_file` field, OR
- JSON: `{"pdf_url": "https://...", "display_name": "optional name"}`

**Flow:**
1. `get_state_and_keys()` for state and API keys.
2. Get `user_email` from session.
3. Compute `user_hash = md5(user_email)`.
4. Create storage path: `storage/global_docs/{user_hash}/`.
5. If file upload: save to `state.pdfs_dir`, get `full_pdf_path`.
6. Call `create_immediate_document_index(pdf_url_or_path, storage, keys)` → `DocIndex`.
7. Call `doc_index.save_local()`.
8. Insert row into `GlobalDocuments` table with `doc_id`, `doc_source`, `doc_storage`, `title`, `short_summary`.
9. Return `{"status": "ok", "doc_id": doc_id}`.

**Response:** `{"status": "ok", "doc_id": "..."}` or `{"error": "..."}` with 400.

#### `GET /global_docs/list`

List all global docs for the current user.

**Response:** JSON array of objects:
```json
[
  {
    "index": 1,
    "doc_id": "123456789",
    "display_name": "My Research Paper",
    "title": "A Study of X",
    "short_summary": "This paper examines...",
    "source": "https://arxiv.org/...",
    "created_at": "2026-02-15T10:30:00"
  },
  ...
]
```

The `index` field is the 1-based position in the list (matching `#gdoc_N` numbering).

**Flow:**
1. `get_state_and_keys()`.
2. `list_global_docs(users_dir=state.users_dir, user_email=session["email"])`.
3. Add `index` field (1-based enumerate).
4. Return JSON array.

#### `GET /global_docs/download/<doc_id>`

Download the source file for a global doc.

**Flow:** Same pattern as `download_doc_from_conversation_route` — load DocIndex, check if `doc_source` exists locally → `send_from_directory`, else `redirect(doc_source)`.

#### `DELETE /global_docs/<doc_id>`

Delete a global doc.

**Flow:**
1. Get user email, verify ownership via DB lookup.
2. Delete DB row.
3. Delete filesystem storage directory (`shutil.rmtree`).
4. Return `{"status": "ok"}`.

#### `POST /global_docs/promote/<conversation_id>/<doc_id>`

Promote a conversation doc to a global doc.

**Flow:**
1. Load the conversation, get the specific doc by `doc_id`.
2. Move (not copy) the DocIndex storage folder from `conversation/uploaded_documents/{doc_id}/` to `global_docs/{user_hash}/{doc_id}/`.
3. Update the DocIndex's `_storage` path and call `save_local()`.
4. Insert row into `GlobalDocuments` table.
5. Remove from conversation's `uploaded_documents_list`.
6. Rebuild conversation's `doc_infos`.
7. Return `{"status": "ok", "doc_id": doc_id}`.

**Why move not copy?** To avoid storage duplication. The promoted doc leaves the conversation and becomes global. If the user still wants it in that conversation, they can reference it with `#gdoc_N`.

**Risk:** If shutil.move fails midway, we could lose the doc. Mitigation: copy first, verify, then delete original. See [Risks and Mitigations](#risks-and-mitigations).

#### `GET /global_docs/info/<doc_id>`

Get detailed info for a single global doc (for the view modal).

**Flow:**
1. Load DB row for metadata.
2. Load DocIndex via `DocIndex.load_local(doc_storage)`.
3. Return extended info: `{doc_id, title, short_summary, source, doc_type, doc_filetype, text_len, created_at, visible}`.

### Register Blueprint

**Modify: `endpoints/__init__.py`** — add:
```python
from .global_docs import global_docs_bp
app.register_blueprint(global_docs_bp)
```

### Modify: `endpoints/state.py` — `AppState`

Add `global_docs_dir: str` field to `AppState` dataclass.

### Modify: `server.py` — storage setup

Add `global_docs_dir` creation alongside existing directories:
```python
global_docs_dir = os.path.join(os.getcwd(), folder, "global_docs")
os.makedirs(global_docs_dir, exist_ok=True)
```
Pass to `init_state(... global_docs_dir=global_docs_dir ...)`.

---

## Backend: Conversation Integration

This is the most critical section. We need to modify `Conversation.py` so the reply flow resolves `#gdoc_N` references alongside `#doc_N`.

### New method: `get_global_documents_for_query()`

Add a new method to the `Conversation` class (or as a standalone helper function in `Conversation.py`) that resolves `#gdoc_N` / `#global_doc_N` references.

```python
def get_global_documents_for_query(self, query, user_email, users_dir, replace_reference=True):
    """
    Parse #gdoc_N and #global_doc_N references from message text,
    resolve them to DocIndex objects from the global docs DB.

    Returns the same tuple shape as get_uploaded_documents_for_query:
    (query, attached_docs, attached_docs_names,
     (readable_docs, readable_names), (data_docs, data_names))
    """
```

**Logic:**
1. Parse `#gdoc_\d+` and `#global_doc_\d+` from `messageText` using regex.
2. Normalize both to integer indices.
3. Call `list_global_docs(users_dir=users_dir, user_email=user_email)` to get ordered list.
4. Resolve each index to a `DocIndex` via `DocIndex.load_local(doc_storage)`.
5. Attach API keys to each DocIndex.
6. Classify as readable vs data (same logic as existing `get_uploaded_documents_for_query`).
7. If `replace_reference`, replace `#gdoc_N` in text with enriched `"#gdoc_N (Title of #gdoc_N 'title')\n"`.
8. Return same tuple shape for seamless integration with downstream code.

### Modify: `Conversation.reply()` — 6 code points

**Point 1: Initial regex parsing (line ~5454)**

Current:
```python
attached_docs = re.findall(r"#doc_\d+", query["messageText"])
```

Add after:
```python
attached_gdocs = re.findall(r"#(?:gdoc|global_doc)_\d+", query["messageText"])
```

**Point 2: all-docs check (line ~5456)**

Current:
```python
all_docs_referenced = (
    "#doc_all" in query["messageText"]
    or "#all_docs" in query["messageText"]
    or "#all_doc" in query["messageText"]
)
```

Add new variable:
```python
all_gdocs_referenced = (
    "#gdoc_all" in query["messageText"]
    or "#global_doc_all" in query["messageText"]
)
```

**Point 3: Summary doc patterns (line ~5495)**

Current:
```python
pattern = r"(#dense_summary_doc_\d+|#summary_doc_\d+|...)"
```

Extend pattern:
```python
pattern = r"(#dense_summary_(?:doc|gdoc|global_doc)_\d+|#summary_(?:doc|gdoc|global_doc)_\d+|#summarise_(?:doc|gdoc|global_doc)_\d+|#summarize_(?:doc|gdoc|global_doc)_\d+|#dense_summarise_(?:doc|gdoc|global_doc)_\d+|#dense_summarize_(?:doc|gdoc|global_doc)_\d+)"
```

**Point 4: Full text doc patterns (line ~5632)**

Similarly extend the `#full_doc_\d+|#raw_doc_\d+|#content_doc_\d+` pattern to include `gdoc` and `global_doc` variants.

**Point 5: Main doc resolution (line ~5810-5820)**

Current:
```python
if all_docs_referenced:
    all_docs = self.get_uploaded_documents()
    all_doc_ids = ["#doc_{}".format(idx + 1) for idx, d in enumerate(all_docs)]
    attached_docs_future = get_async_future(
        self.get_uploaded_documents_for_query,
        {"messageText": " ".join(all_doc_ids)},
    )
else:
    attached_docs_future = get_async_future(
        self.get_uploaded_documents_for_query, query
    )
```

Add parallel resolution for global docs:
```python
# Global docs resolution (parallel with conversation docs)
if all_gdocs_referenced or len(attached_gdocs) > 0:
    gdocs_future = get_async_future(
        self.get_global_documents_for_query,
        query if not all_gdocs_referenced else {"messageText": "#gdoc_all"},
        user_email, users_dir
    )
else:
    gdocs_future = None
```

**Point 6: Merge results (after both futures resolve)**

After `attached_docs_future.result()` and `gdocs_future.result()`, merge the two lists:
```python
# Merge conversation docs + global docs
if gdocs_future is not None:
    (_, gdoc_attached, gdoc_names,
     (gdoc_readable, gdoc_readable_names),
     (gdoc_data, gdoc_data_names)) = gdocs_future.result()
    all_attached = conversation_attached + gdoc_attached
    all_readable = conversation_readable + gdoc_readable
    all_data = conversation_data + gdoc_data
    # ... merge names similarly
```

The downstream code (`get_multiple_answers`, `streaming_get_short_answer`) operates on `List[DocIndex]` — it doesn't care whether a DocIndex came from a conversation or global storage. No changes needed downstream.

### Passing user_email and users_dir into reply()

The `reply()` method needs `user_email` and `users_dir` to resolve global docs. Check how they're currently available:

- `users_dir`: Available via `endpoints.state.get_state().users_dir`. The reply method is called from `endpoints/conversations.py`'s `send_message` endpoint, which has access to state.
- `user_email`: Available from `flask.session["email"]`.

**Approach:** Pass `user_email` and `users_dir` as parameters in the `query` dict (they're already partially present — `query` has `messageText`, `checkboxes`, etc.). Add `query["_user_email"]` and `query["_users_dir"]` before calling `reply()`. This follows the existing pattern of injecting metadata into the query dict (e.g., `query["_conversation_loader"]` from the cross-conversation references feature).

**Modify: `endpoints/conversations.py` — `send_message` endpoint**

Before calling `conversation.reply(query, ...)`, inject:
```python
query["_user_email"] = session.get("email", "")
query["_users_dir"] = state.users_dir
```

---

## Frontend: UI Display Design

This section describes exactly how global documents appear across the interface — in the doc bar, management modal, PDF viewer, chat messages, and alongside conversation docs.

### 1. Chat Doc Bar (`#chat-doc-view`)

The existing doc bar (top of chat area, line 276 of `interface.html`) shows conversation docs as `#doc_1`, `#doc_2`, etc. We add:

**Global Docs Button:** A new button placed immediately after the "Add Doc" button:
```
[📥 transcript] [🔗 share] [➕ Add Doc] [🌐 Global Docs]  ...  [#doc_1 ⬇️ ❌] [#doc_2 ⬇️ ❌]
```

- **Button style:** `btn btn-outline-info btn-sm` (info color to differentiate from primary "Add Doc").
- **Icon:** `fa-globe` — globe icon signals cross-conversation scope.
- **Click action:** Opens `#global-docs-modal`.

**No inline global doc buttons** in the doc bar itself — global docs are managed via the modal to keep the bar clean. Users reference them via `#gdoc_N` in their messages. The modal shows the numbering so users know which number to use.

### 2. Global Docs Management Modal

Full-screen-capable modal (`modal-lg`) with two sections:

**Section A — Upload (top card):**
- URL text input + file browse button + drag-drop zone (same pattern as `#add-document-modal-chat`).
- Optional "Display Name" text field.
- Submit button with spinner + progress percentage.
- File accept list matches the existing chat file upload: PDF, DOCX, HTML, MD, TXT, images, audio, CSV, XLSX, etc.

**Section B — Document List (bottom card):**
- `list-group-flush` with one row per global doc.
- Each row layout:
  ```
  | #gdoc_1 — Document Title                                    | 👁️ ⬇️ 🗑️ |
  |   source_url | Feb 15, 2026                                  |          |
  ```
- **`#gdoc_N` label** is bold, styled as a badge (`badge badge-info`) to show the reference number.
- **Title** is the `display_name` if set, else `title` from DocIndex.
- **Source** and **created_at** shown as muted small text.
- **Action buttons** (right side):
  - 👁️ View: `btn-outline-primary gdoc-view-btn` — opens PDF viewer.
  - ⬇️ Download: `btn-outline-success gdoc-download-btn` — opens download in new tab.
  - 🗑️ Delete: `btn-outline-danger gdoc-delete-btn` — confirmation prompt, then delete.
- **Empty state:** "No global documents yet. Upload one above." centered muted text.
- **Refresh button** in card header (🔄 icon).

### 3. PDF Viewer Integration

When user clicks "View" on a global doc:
1. Modal stays open (or auto-closes, same behavior as conversation docs).
2. The existing `#chat-pdf-content` iframe + PDF.js viewer is reused.
3. `showPDF(doc.source, "chat-pdf-content", "/proxy_shared")` is called — identical to conversation doc viewing.
4. `#chat-content` is hidden, `#chat-pdf-content` shown (same toggle pattern).
5. `ChatManager.shownDoc` is updated to avoid reloading the same doc.
6. Close behavior: The existing close mechanism (clicking any doc button again or a close button) returns to chat view.

**No new PDF viewer infrastructure needed** — global docs fully reuse the existing viewer.

### 4. Global Doc References in Chat Messages

When a user types `#gdoc_1` in a message:
- **Before sending:** The text is sent as-is. No client-side transformation needed.
- **In the LLM reply:** The reply flow enriches `#gdoc_1` to `#gdoc_1 (Title of #gdoc_1 'actual title')` so the LLM has context.
- **In the rendered response:** The LLM's response may mention `#gdoc_1` naturally. No special rendering is applied to `#gdoc_N` patterns in the rendered HTML (same as how `#doc_N` patterns appear in responses today — they're plain text).
- **Optional future enhancement:** Make `#gdoc_N` clickable in rendered messages (detect pattern → link to PDF viewer). This is NOT in scope for initial implementation.

### 5. Visual Differentiation: Conversation Docs vs Global Docs

| Aspect | Conversation Docs | Global Docs |
|--------|-------------------|-------------|
| **Location** | Inline buttons in `#chat-doc-view` bar | Listed in `#global-docs-modal` |
| **Reference syntax** | `#doc_1`, `#doc_2`, ... | `#gdoc_1`, `#global_doc_1`, ... |
| **Button color** | `btn-outline-primary` (blue) | N/A (no inline buttons) |
| **Trigger button** | "Add Doc" (primary blue) | "Global Docs" (info cyan/teal) |
| **Badge in modal** | N/A | `badge-info` for `#gdoc_N` label |
| **Scope indicator** | None (implied per-conversation) | Globe icon (🌐) on trigger button |
| **PDF viewing** | Same viewer | Same viewer |

### 6. Promote Button on Conversation Docs

Each conversation doc button in the doc bar gets an additional action icon:
```
[#doc_1 🌐 ⬇️ ❌]
```
- **Globe icon** (`fa-globe`): `btn-outline-info` — placed before download and delete.
- **Click action:** `confirm('Promote this doc to Global Docs? It will be removed from this conversation.')` → calls promote API → refreshes doc bar.
- **Post-promote:** The doc disappears from the conversation doc bar. User can reference it via `#gdoc_N` in any conversation.

### 7. User Discovery Flow

How does a user discover available global docs when composing a message?

1. **Click "Global Docs" button** in the doc bar → modal opens with numbered list.
2. **See `#gdoc_N` labels** next to each document in the list.
3. **Close modal**, type `#gdoc_1` (or `#gdoc_all`) in the message input.
4. **No autocomplete** for global doc references in initial implementation (consistent with existing `#doc_N` behavior — no autocomplete there either).
5. **Future enhancement:** Add `#gdoc_` autocomplete similar to the `@` autocomplete for PKB references.

---

## Frontend: UI Components

### Global Docs Management Modal

New modal: `#global-docs-modal`. Follows the same Bootstrap 4.6 pattern as `#add-document-modal-chat` and the PKB modal.

**Structure:**
```html
<div class="modal fade" id="global-docs-modal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Global Documents</h5>
        <button type="button" class="close" data-dismiss="modal">
          <span>&times;</span>
        </button>
      </div>
      <div class="modal-body">
        <!-- Upload section -->
        <div class="card mb-3">
          <div class="card-header">
            <h6 class="mb-0">Add New Global Document</h6>
          </div>
          <div class="card-body">
            <form id="global-doc-upload-form">
              <div class="form-group">
                <label for="global-doc-url">Document URL</label>
                <input type="text" class="form-control" id="global-doc-url"
                       placeholder="Enter URL (PDF, web page, etc.)">
              </div>
              <div class="form-group">
                <label>Or upload a file:
                  <button type="button" id="global-doc-file-browse"
                          class="btn btn-link btn-sm">Browse</button>
                </label>
                <div id="global-doc-drop-area"
                     style="border: 2px dashed #aaa; padding: 10px; text-align: center;">
                  Drop a file here
                </div>
                <input type="file" id="global-doc-file-input"
                       accept="(same accept list as chat-file-upload)"
                       style="display: none;">
              </div>
              <div class="form-group">
                <label for="global-doc-display-name">Display Name (optional)</label>
                <input type="text" class="form-control" id="global-doc-display-name"
                       placeholder="Custom name for this document">
              </div>
              <button type="submit" class="btn btn-primary" id="global-doc-submit">
                Upload
              </button>
              <span id="global-doc-upload-spinner" style="display:none;">
                <div class="spinner-border spinner-border-sm text-primary"></div>
                <span id="global-doc-upload-progress">0%</span>
              </span>
            </form>
          </div>
        </div>

        <!-- Document list section -->
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
            <h6 class="mb-0">Your Global Documents</h6>
            <button class="btn btn-sm btn-outline-secondary"
                    id="global-doc-refresh">
              <i class="fa fa-refresh"></i>
            </button>
          </div>
          <div class="card-body p-0">
            <div id="global-docs-list" class="list-group list-group-flush">
              <!-- Dynamically populated -->
              <!-- Each item:
              <div class="list-group-item d-flex justify-content-between align-items-center">
                <div>
                  <strong>#gdoc_1</strong> — Document Title
                  <br><small class="text-muted">source | created_at</small>
                </div>
                <div>
                  <button class="btn btn-sm btn-outline-primary gdoc-view-btn"
                          data-doc-id="...">
                    <i class="fa fa-eye"></i>
                  </button>
                  <button class="btn btn-sm btn-outline-success gdoc-download-btn"
                          data-doc-id="...">
                    <i class="fa fa-download"></i>
                  </button>
                  <button class="btn btn-sm btn-outline-danger gdoc-delete-btn"
                          data-doc-id="...">
                    <i class="fa fa-trash"></i>
                  </button>
                </div>
              </div>
              -->
            </div>
            <div id="global-docs-empty" class="p-3 text-center text-muted"
                 style="display:none;">
              No global documents yet. Upload one above.
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
```

### Trigger Button

Add a "Global Docs" button in `#chat-doc-view` (line 276 of `interface.html`), next to "Add Doc":

```html
<button id="global-docs-button" type="button"
        class="btn btn-outline-primary mr-2 btn-sm mb-1">
  <i class="fa fa-globe">&nbsp; Global Docs</i>
</button>
```

### Promote Button

Add a "Promote to Global" option on each conversation doc button in `renderDocuments()`. This will be an additional icon button (globe icon) next to the existing download and delete buttons.

### View Modal (PDF Viewer)

When clicking "view" on a global doc in the list, reuse the existing `showPDF()` function and `#chat-pdf-content` iframe. The view button calls:
```javascript
showPDF(doc.source, "chat-pdf-content", "/proxy_shared");
```
Then closes the modal and shows the PDF viewer, identical to clicking a conversation doc button.

---

## Frontend: JavaScript Logic

### New file: `interface/global-docs-manager.js`

Follows the pattern of existing managers (WorkspaceManager, ConversationManager). A single global object `GlobalDocsManager` initialized on `$(document).ready()`.

```javascript
var GlobalDocsManager = {

    // ---- API Calls ----

    list: function() {
        return $.ajax({ url: '/global_docs/list', type: 'GET' });
    },

    upload: function(fileOrUrl, displayName) {
        // If file: FormData with pdf_file
        // If URL: JSON body with pdf_url
        // Returns promise
    },

    delete: function(docId) {
        return $.ajax({
            url: '/global_docs/' + docId,
            type: 'DELETE'
        });
    },

    promote: function(conversationId, docId) {
        return $.ajax({
            url: '/global_docs/promote/' + conversationId + '/' + docId,
            type: 'POST'
        });
    },

    // ---- Rendering ----

    renderList: function(docs) {
        var $list = $('#global-docs-list');
        var $empty = $('#global-docs-empty');
        $list.empty();

        if (docs.length === 0) {
            $empty.show();
            return;
        }
        $empty.hide();

        docs.forEach(function(doc) {
            // Create list-group-item with #gdoc_N label, title, action buttons
            // Wire up view, download, delete handlers
        });
    },

    // ---- Setup (called once) ----

    setup: function() {
        // Wire modal open button
        $('#global-docs-button').off().on('click', function() {
            $('#global-docs-modal').modal('show');
            GlobalDocsManager.refresh();
        });

        // Wire upload form
        $('#global-doc-upload-form').off().on('submit', function(e) {
            e.preventDefault();
            // ... upload logic with progress
        });

        // Wire file browse, drag-drop (same pattern as setupAddDocumentForm)
        // Wire refresh button
    },

    refresh: function() {
        GlobalDocsManager.list().done(function(docs) {
            GlobalDocsManager.renderList(docs);
        });
    }
};
```

### Modify: `interface/common-chat.js`

1. **`ChatManager.renderDocuments()`** (line 2115): Add a "promote to global" button on each conversation doc:
   ```javascript
   var promoteButton = $('<i></i>')
       .addClass('fa fa-globe')
       .attr('aria-hidden', 'true')
       .attr('aria-label', 'Promote to Global Document');

   var promoteDiv = $('<div></div>')
       .addClass('btn p-0 btn-sm btn-outline-info ml-1')
       .append(promoteButton);

   promoteDiv.click(function(event) {
       event.stopPropagation();
       if (confirm('Promote this document to a Global Document? It will be removed from this conversation and available across all conversations.')) {
           GlobalDocsManager.promote(conversation_id, doc.doc_id)
               .done(function() {
                   ChatManager.listDocuments(conversation_id).done(function(documents) {
                       ChatManager.renderDocuments(conversation_id, documents);
                   });
                   showToast('Document promoted to Global Documents.');
               })
               .fail(function() {
                   alert('Error promoting document.');
               });
       }
   });
   ```

2. **`ChatManager.setupAddDocumentForm()`** (line 1874): No changes needed. Conversation doc upload remains as-is.

### Modify: `interface/interface.html`

1. Add the `#global-docs-modal` HTML (see UI Components section above).
2. Add the `#global-docs-button` in `#chat-doc-view`.
3. Add `<script src="global-docs-manager.js"></script>` in the scripts section.

---

## Promote Conversation Doc to Global Doc

This is a backend operation that:

1. **Validates** the doc exists in the conversation and belongs to the user.
2. **Copies** the DocIndex storage folder from `{conversation}/uploaded_documents/{doc_id}/` to `storage/global_docs/{user_hash}/{doc_id}/`.
3. **Verifies** the copy by calling `DocIndex.load_local()` on the new location.
4. **Inserts** a row into `GlobalDocuments` table.
5. **Removes** the doc from the conversation's `uploaded_documents_list`.
6. **Rebuilds** the conversation's `doc_infos` string.
7. **Deletes** the original storage folder (only after verification succeeds).
8. **Saves** the conversation.

**Why copy-then-delete instead of move?** `shutil.move` is atomic on the same filesystem but can fail across filesystems. Copy + verify + delete is safer. If verify fails, we abort and the original remains intact.

**Edge case: What if the same doc_id already exists as a global doc?** This happens if the user re-uploaded the same file. In this case, skip the storage copy (global version already exists) and just remove from conversation.

---

## Implementation Plan (Milestones)

### M0: Database + Storage Foundation
**Goal:** DB table exists, storage directory created, schema migration runs on server start.

**Tasks:**
1. **M0.1:** Add `GlobalDocuments` CREATE TABLE statement to `database/connection.py` `create_tables()` function.
   - File: `database/connection.py` (~line 150)
   - Add SQL string, `create_table()` call, and two `CREATE INDEX` calls.

2. **M0.2:** Create `database/global_docs.py` with all CRUD functions.
   - New file. Functions: `add_global_doc`, `list_global_docs`, `get_global_doc`, `delete_global_doc`, `update_global_doc_metadata`.
   - Follow the pattern of `database/conversations.py` (keyword-only args, own connection, close after use).

3. **M0.3:** Add `global_docs_dir` to `AppState`.
   - File: `endpoints/state.py` — add field to `AppState` dataclass.
   - File: `endpoints/state.py` — add parameter to `init_state()`.

4. **M0.4:** Create `global_docs_dir` on server startup.
   - File: `server.py` (~line 203) — add `global_docs_dir = os.path.join(...)` and `os.makedirs(...)`.
   - Pass to `init_state()`.

**Verification:** Server starts without errors, `GlobalDocuments` table exists in `users.db`, `storage/global_docs/` directory created.

---

### M1: Backend CRUD Endpoints
**Goal:** All 5 API endpoints work and can be tested via curl.

**Tasks:**
1. **M1.1:** Create `endpoints/global_docs.py` with the blueprint and all route handlers.
   - `POST /global_docs/upload`
   - `GET /global_docs/list`
   - `GET /global_docs/download/<doc_id>`
   - `DELETE /global_docs/<doc_id>`
   - `GET /global_docs/info/<doc_id>`
   - Each handler: `get_state_and_keys()`, session email check, delegate to `database/global_docs.py` and `DocIndex`.

2. **M1.2:** Register the blueprint.
   - File: `endpoints/__init__.py` — import and register `global_docs_bp`.

3. **M1.3:** Add the promote endpoint.
   - `POST /global_docs/promote/<conversation_id>/<doc_id>`
   - Uses `shutil.copytree` + verify + delete pattern.
   - Modifies conversation's `uploaded_documents_list` and `doc_infos`.

**Verification:** curl tests for all endpoints: upload a PDF URL, list returns it, download works, info returns metadata, delete removes it. Promote: upload doc to conversation, promote it, verify it appears in global list and is gone from conversation list.

---

### M2: Conversation Integration (Reply Flow)
**Goal:** `#gdoc_N` and `#global_doc_N` references work in conversation messages.

**Tasks:**
1. **M2.1:** Add `get_global_documents_for_query()` method to `Conversation.py`.
   - New method (~50 lines), placed near `get_uploaded_documents_for_query()` (line ~4416).
   - Parses `#gdoc_\d+` and `#global_doc_\d+`, resolves to DocIndex objects, classifies readable/data.
   - Returns same tuple shape as `get_uploaded_documents_for_query()`.

2. **M2.2:** Inject `_user_email` and `_users_dir` into query dict.
   - File: `endpoints/conversations.py` — in `send_message` endpoint, before calling `reply()`:
     ```python
     query["_user_email"] = session.get("email", "")
     query["_users_dir"] = state.users_dir
     ```

3. **M2.3:** Modify `reply()` — initial parsing (line ~5454).
   - Add regex for `#gdoc_\d+` and `#global_doc_\d+`.
   - Add `all_gdocs_referenced` check for `#gdoc_all` / `#global_doc_all`.

4. **M2.4:** Modify `reply()` — summary doc pattern (line ~5495).
   - Extend regex to include `gdoc` and `global_doc` variants.
   - Route gdoc summary references through `get_global_documents_for_query()`.

5. **M2.5:** Modify `reply()` — full text doc pattern (line ~5632).
   - Extend regex to include `gdoc` and `global_doc` variants.

6. **M2.6:** Modify `reply()` — main doc resolution (line ~5810).
   - Launch `get_global_documents_for_query()` as async future in parallel with conversation docs.
   - Merge results after both futures resolve.
   - Feed merged list to downstream answering logic.

**Verification:** In a conversation, type `#gdoc_1 explain this paper` and get an answer grounded in the global doc. Type `#gdoc_all` and get answers from all global docs. Mix `#doc_1` and `#gdoc_1` in one message and get answers from both.

---

### M3: Frontend — Global Docs Modal + Manager
**Goal:** Users can manage global docs through the UI.

**Tasks:**
1. **M3.1:** Add `#global-docs-modal` HTML to `interface/interface.html`.
   - Upload form (URL + file + display name).
   - List panel with action buttons.
   - Place after the existing `#add-document-modal-chat` modal.

2. **M3.2:** Add `#global-docs-button` to `#chat-doc-view` in `interface/interface.html`.
   - Globe icon button, placed after "Add Doc" button (line 279).

3. **M3.3:** Create `interface/global-docs-manager.js`.
   - `GlobalDocsManager` object with: `list()`, `upload()`, `delete()`, `promote()`, `renderList()`, `setup()`, `refresh()`.
   - Upload with XHR progress tracking (same pattern as `uploadFile_internal`).
   - File drag-and-drop support.

4. **M3.4:** Add `<script>` tag for `global-docs-manager.js` in `interface/interface.html`.

5. **M3.5:** Initialize `GlobalDocsManager.setup()` in the page ready handler.
   - File: `interface/chat.js` or `interface/common-chat.js` — wherever `$(document).ready()` handlers are.

**Verification:** Click "Global Docs" button → modal opens, shows empty list. Upload a doc via URL → spinner → appears in list. Click view → PDF viewer opens. Click delete → confirmation → removed from list.

---

### M4: Frontend — Promote + Cross-Conversation Visibility
**Goal:** Users can promote conversation docs and see global docs referenced in chat.

**Tasks:**
1. **M4.1:** Add promote button to conversation doc buttons.
   - File: `interface/common-chat.js` — `ChatManager.renderDocuments()` (line ~2183).
   - Add globe icon button with click handler calling `GlobalDocsManager.promote()`.
   - Confirmation dialog before promoting.

2. **M4.2:** Show global doc references in chat messages.
   - When the reply flow returns `#gdoc_N` references in answers, they should be visually distinct.
   - This may happen naturally if the LLM includes `#gdoc_N` text in its response. No special rendering needed unless we want clickable links.
   - **Optional enhancement:** In message rendering, detect `#gdoc_\d+` patterns and make them clickable (opens global doc in PDF viewer). This can be a follow-up.

**Verification:** Upload a doc to a conversation → click promote (globe) → confirmation → doc disappears from conversation, appears in global docs list. Open a different conversation → type `#gdoc_1 what is this about?` → get answer.

---

### M5: Documentation
**Goal:** Feature documented for developers and users.

**Tasks:**
1. **M5.1:** Create `documentation/features/global_docs/README.md`.
   - Feature overview, API reference, UI guide, storage layout, integration details.

2. **M5.2:** Update `documentation/product/behavior/chat_app_capabilities.md`.
   - Add new section for Global Documents.

3. **M5.3:** Update `documentation/api/external/external_api.md`.
   - Add Global Docs endpoints section.

4. **M5.4:** Update `documentation/README.md`.
   - Add `features/global_docs/` entry.

---

## Files to Create/Modify (Summary)

### New Files

| File | Purpose |
|------|---------|
| `database/global_docs.py` | DB CRUD for GlobalDocuments table |
| `endpoints/global_docs.py` | Flask Blueprint with 6 REST endpoints |
| `interface/global-docs-manager.js` | Frontend JS manager object |
| `documentation/features/global_docs/README.md` | Feature documentation |

### Modified Files

| File | Change | Milestone |
|------|--------|-----------|
| `database/connection.py` | Add `GlobalDocuments` table + indexes to `create_tables()` | M0 |
| `endpoints/state.py` | Add `global_docs_dir` field to `AppState` + `init_state()` | M0 |
| `server.py` | Create `global_docs_dir`, pass to `init_state()` | M0 |
| `endpoints/__init__.py` | Import and register `global_docs_bp` | M1 |
| `Conversation.py` | Add `get_global_documents_for_query()`, modify `reply()` at 6 points | M2 |
| `endpoints/conversations.py` | Inject `_user_email` and `_users_dir` into query dict | M2 |
| `interface/interface.html` | Add modal HTML, button, script tag | M3 |
| `interface/common-chat.js` | Add promote button to `renderDocuments()` | M4 |
| `documentation/product/behavior/chat_app_capabilities.md` | Add Global Docs section | M5 |
| `documentation/api/external/external_api.md` | Add Global Docs API | M5 |
| `documentation/README.md` | Add feature entry | M5 |

---

## Testing Plan

### Manual Tests

| Test Case | Steps | Expected |
|-----------|-------|----------|
| Upload global doc via URL | Open Global Docs modal → paste URL → Submit | Doc appears in list with title and summary |
| Upload global doc via file | Open Global Docs modal → drop/browse file → Submit | Doc appears in list |
| List global docs | Open modal | Shows all user's global docs with indices |
| Delete global doc | Click trash icon → confirm | Doc removed from list and storage |
| View global doc | Click eye icon | PDF viewer opens with document |
| Download global doc | Click download icon | File downloads in new tab |
| Reference #gdoc_1 | Type `#gdoc_1 summarize this` in chat | Answer based on global doc 1 |
| Reference #global_doc_1 | Type `#global_doc_1 what is this?` | Same as #gdoc_1 |
| Reference #gdoc_all | Type `#gdoc_all compare these docs` | Answer synthesizing all global docs |
| Mix doc types | Type `#doc_1 and #gdoc_1 compare` | Answer using both conversation and global doc |
| Promote doc | Click globe icon on conversation doc → confirm | Doc moves to global, disappears from conversation |
| Promote then reference | Promote doc, open new conversation, use #gdoc_N | Works in the new conversation |
| Summary gdoc | Type `#summary_gdoc_1` | Get forced summary of global doc 1 |
| No global docs | Reference `#gdoc_1` with no global docs | Graceful handling, no crash |
| Wrong index | Reference `#gdoc_99` when only 2 exist | Graceful skip, no crash |

### Automated Tests (future)

- Unit tests for `database/global_docs.py` CRUD functions.
- Integration tests for endpoint responses (similar to `extension/tests/`).
- Test that promoting a doc correctly moves storage and updates both DB and conversation state.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Promote fails midway** (storage copied but DB not updated or vice versa) | Doc in limbo state | Use copy-verify-delete pattern. If verify fails, abort and keep original. If DB insert fails after copy, delete the copy. Wrap in try/except with cleanup. |
| **Concurrent access** to same global doc from multiple conversations | Lock contention on DocIndex.set_doc_data() | Global docs are primarily read-only during conversation use. Only `streaming_get_short_answer` might trigger lazy summary generation, which uses locks. The existing FileLock mechanism handles this. |
| **Large number of global docs** slows list_global_docs DB query | Slow modal load | DB query is lightweight (no DocIndex loading). Add pagination if >100 docs (future enhancement). |
| **DocIndex.load_local() from global storage has different lock directory** | Lock path mismatch | DocIndex._get_lock_location() uses `path.parent.parent / "locks"`. For global docs stored at `global_docs/{hash}/{doc_id}/`, locks go to `global_docs/{hash}/locks/`. Ensure this directory exists when creating storage. |
| **doc_id collision** between conversation doc and global doc | Wrong doc resolved | doc_id is derived from `mmh3.hash(source + filetype + type)` — same source produces same doc_id regardless of where it's stored. The `#doc_N` vs `#gdoc_N` prefix ensures we look in the right place. DB lookups are scoped by table. |
| **User references #gdoc_N but has no global docs** | Error in reply flow | `get_global_documents_for_query()` returns empty lists when no global docs exist, same as `get_uploaded_documents_for_query()` does for empty conversations. Downstream code already handles empty doc lists. |
| **API keys not attached to global DocIndex** | LLM calls fail during doc answering | `get_global_documents_for_query()` calls `attach_keys()` on every loaded DocIndex, same as `get_uploaded_documents()` does for conversation docs. |

---

## Alternatives Considered

### 1. Symlink-based sharing

Instead of a separate global storage, create symlinks from conversations to a shared DocIndex folder.

**Rejected because:** Symlinks are fragile across OS (Windows doesn't support them well), complicate cleanup (deleting conversation doesn't know symlink exists), and make the storage model harder to reason about.

### 2. Reference-counting with shared storage

Keep DocIndex in a shared pool, reference-count usage across conversations.

**Rejected because:** Adds significant complexity (ref-counting, garbage collection, race conditions). The simpler "global docs are a separate entity" model is easier to implement and understand.

### 3. Copy-on-attach to conversation

When user references `#gdoc_N`, copy the DocIndex into the conversation's uploaded_documents.

**Rejected because:** This defeats the purpose — we'd still duplicate storage and indexing work. The whole point is index-once-use-everywhere.

### 4. Persistent numbering for global docs

Assign each global doc a permanent number that never changes even after deletions.

**Rejected for now because:** Adds complexity (need a counter in DB, gaps in numbering confuse users). Positional numbering matches existing `#doc_N` behavior. Can be revisited if users find renumbering confusing.
