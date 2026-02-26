# Hierarchical Doc Store + Folder Hierarchy + Summary View

**Status:** Planning — Clarifications Finalized (2026-02-26)
**Created:** 2026-02-26  
**Scope:** DocIndex canonical storage, per-user folder hierarchy, doc summary view, index upgrade UX

---

## 1. Goals & User Requirements

The user confirmed the following goals in a Q&A session:

1. **Canonical shared doc store** — each unique document (by `doc_id`) stored once on disk. Multiple conversations and the global doc list hold *references*, not copies. Eliminates duplication when the same file is uploaded to multiple conversations.

2. **Hierarchical folder structure** — separate trees for local (per-conversation) and global (per-user). Folders are organizational containers holding references to docs. A folder can be @-referenced in chat to include *all* its docs in LLM context at once.

3. **Doc summary view** — surface the `title` that is already produced by `get_short_info()` in the doc list UI. Short summary to be shown on demand (not inline). (First pass: title-only, no new modal complexity.)

4. **Explicit index upgrade ("Analyze" button)** — local docs uploaded via the "Add Document" modal are created as `FastDocIndex` (BM25, no LLM). User can explicitly trigger upgrade to full `DocIndex` (FAISS + LLM) via a button. Not automatic on upload.

5. **Force full re-index on promote-to-global** — when a local doc is promoted to global, always build a full `DocIndex` regardless of current index type. User waits; quality guaranteed.

6. **File browser integration** — the canonical doc store lives inside `storage/` which is inside `SERVER_ROOT`. The existing file browser can browse it. Markdown files viewable/editable directly (no PDF conversion needed for `.md`).

7. **Reference model (dedup)** — "store once, referenced from many". All conversations pointing to the same canonical doc_id share one DocIndex on disk. Upgrades (BM25 → FAISS) propagate automatically to all referencing conversations.

---

## 2. Current State (What Exists Today)

### 2.1 Storage Layout

```
storage/
  conversations/
    {conversation_id}/
      uploaded_documents/
        {doc_id}/               ← per-conversation DocIndex copy
          {doc_id}.index        ← dill-pickled DocIndex object
          {doc_id}-raw_data.partial
          {doc_id}-indices.partial
          {doc_id}-static_data.json
  global_docs/
    {user_hash}/
      {doc_id}/                 ← per-user global DocIndex copy
  documents/                    ← EXISTS but unused (docs_folder in server.py:342)
  pdfs/                         ← incoming PDF staging area
  users/
    users.db                    ← SQLite: GlobalDocuments, PKB, etc.
```

### 2.2 Local Docs (Per-Conversation)

- **In-memory/serialized:** `uploaded_documents_list` field on Conversation — `List[Tuple[doc_id, doc_storage_path, source_url, display_name]]`
- **4-tuple format** (current), backward-compat with old 3-tuples
- **Index type:** Always `FastDocIndex` (BM25) for docs uploaded via "Add Document" modal
- **Loading:** `DocIndex.load_local(entry[1])` where `entry[1]` is `doc_storage_path`
- **Message attachments:** `message_attached_documents_list` — 3-tuples, always `FastDocIndex`; can be promoted to full `DocIndex` via existing `promote_message_attached_document()`

### 2.3 Global Docs

- **DB schema:**
  ```sql
  GlobalDocuments(doc_id, user_email, display_name, doc_source, doc_storage,
                  title, short_summary, created_at, updated_at,
                  PRIMARY KEY (doc_id, user_email))
  ```
- **On disk:** `storage/global_docs/{user_hash}/{doc_id}/` — always full `DocIndex`
- **Promote-to-global:** `shutil.copytree(source_storage, target_storage)` → full copy
- **No dedup:** promotes always create a new copy even if canonical already exists

### 2.4 DocIndex Types

| Feature | FastDocIndex | DocIndex (full) |
|---|---|---|
| Search | BM25 keyword | FAISS semantic |
| Title | Filename (no LLM) | LLM-generated |
| Summary | First 500 chars (no LLM) | LLM-generated |
| Build time | 1–3 sec | 15–45 sec |
| `_is_fast_index` | `True` | absent / `False` |
| Upgrade path | Via "Analyze" button | N/A |

### 2.5 Doc → LLM Context Pipeline

1. User writes `#doc_1` or `#doc_all` in message
2. `reply()` in Conversation.py calls `get_uploaded_documents_for_query(query)` → returns matching `DocIndex` objects
3. `get_multiple_answers(query_text, docs, ...)` in `base.py` calls `doc.semantic_search_document(query)` per doc → retrieves relevant chunks
4. Results aggregated as: `"For '{title}' information is given below.\n{content}"` per doc
5. Injected into prompt as `conversation_docs_answer`
6. `doc_infos` (persisted string on Conversation) = `#doc_1: (title)[source]\n#doc_2: ...` — shown in system prompt as document manifest
7. Global docs: `#gdoc_1`, `#gdoc_all` → same pipeline via `get_global_documents_for_query()`

### 2.6 File Browser

- Full VS Code-like modal: tree sidebar, CodeMirror editor, markdown preview/WYSIWYG, PDF viewer
- `SERVER_ROOT` = project root; all paths under `storage/` are accessible
- Sandboxed via `_safe_resolve()` — path traversal protected
- Endpoints: `/file-browser/tree`, `/read`, `/write`, `/mkdir`, `/rename`, `/delete`, `/upload`, `/serve`
- Markdown already handled: `.md` → CodeMirror GFM mode + preview + EasyMDE WYSIWYG
- Entry point: Settings → Actions → "File Browser" button

### 2.7 Key Gap: `_visible` Flag Not Enforced

`get_uploaded_documents()` returns all docs regardless of `_visible`. `_visible` is set on DocIndex instances but not actually filtered anywhere today. This is the natural hook for folder-level inclusion.

---

## 3. Clarifications & Design Decisions

### 3.1 Canonical Store Location

**Decision:** `storage/documents/{user_hash}/{doc_id}/`

- The `storage/documents/` directory already exists (created at startup in `server.py:342`, `docs_folder` variable) but is currently **unused** — perfect for repurposing.
- Mirrors `global_docs/{user_hash}/{doc_id}/` pattern.
- Inside `SERVER_ROOT` → visible in file browser immediately.
- Per-user hash provides isolation without per-conversation scoping.
- `global_docs/` entries migrate **eagerly at first server startup** via migration script.

**Rejected:** `storage/users/{user_hash}/docs/` — mixes doc blobs with user DB and PKB data. `global_docs/` as canonical — conflates "globally listed" with "stored once".

### 3.2 Reference Model for Local Docs

**Decision:** Keep 4-tuple format. Change `doc_storage` to point at canonical path.

- No schema change. The tuple `(doc_id, canonical_path, source_url, display_name)` is drop-in compatible with existing `get_uploaded_documents()` code.
- Deletion removes the tuple from the conversation but does NOT `rmtree` the canonical folder.
- Orphan cleanup is a separate periodic sweep.
- On dedup: **SHA256 hash** the file bytes on upload. If `storage/documents/{user_hash}/{sha256_hash}/` exists, skip re-indexing — just write the tuple reference pointing at the existing entry. For mutable files (e.g. `.md`), rehash on modification before writing.

**Rejected:** `doc_id`-only dedup (does not catch same file uploaded under different names), no-dedup approach.

### 3.3 Folder Hierarchy Storage

**Decision:** Two new SQLite tables in `users.db`.

```sql
DocFolders(
  folder_id     TEXT PRIMARY KEY,   -- uuid4
  user_email    TEXT NOT NULL,
  name          TEXT NOT NULL,
  parent_folder_id TEXT,            -- NULL = root
  scope         TEXT NOT NULL,      -- 'local' | 'global'
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
)

DocFolderItems(
  folder_id     TEXT NOT NULL,
  doc_id        TEXT NOT NULL,
  user_email    TEXT NOT NULL,
  display_name  TEXT,               -- override per-folder label (optional)
  added_at      TEXT NOT NULL,
  PRIMARY KEY (folder_id, doc_id, user_email)
)
```

- `scope='local'` folders are visible in conversation doc panel; `scope='global'` in global doc panel.
- Rename = single `UPDATE DocFolders SET name=?`. Move = `UPDATE DocFolderItems SET folder_id=?`.
- Context inclusion query: `SELECT doc_id FROM DocFolderItems WHERE folder_id=?` (recursive for subfolders).
- **Folder UI: reuse the existing file browser UI** — the canonical store lives at `storage/documents/{user_hash}/` which is inside `SERVER_ROOT`. The file browser already renders this tree. Folder creation, renaming, and doc upload all happen via the existing file browser controls.

**Note:** The original list-based modal UI (local docs modal and global docs modal) is **kept alongside** the file browser view. For conversations with very few files, the flat list modal remains the primary interface. The file browser is the power-user path for organized folder hierarchies.

### 3.4 Folder Context Inclusion in Chat

**Decision:** Use `#folder:FolderName` prefix (separate from PKB `@` references). Resolves to all docs in the named folder, passed through `ContextualReader` (map-reduce) if total content exceeds context length.

- Detection regex: `#folder:[\.\w/\-]+` in message text.
- Resolution: folder path → `DocFolderItems` query → list of `doc_id`s → load from canonical store → append to `attached_docs`.
- **No hard cap on doc count.** If folder content exceeds context length, `ContextualReader` (existing map-reduce class) handles chunking and aggregation automatically — same path as `#doc_all`.
- Subfolders: recursive, flattened.
- The LLM sees it as standard `#doc_N` entries — no prompt changes.

### 3.5 FastDocIndex in Canonical Store

**Decision:** Yes — canonical store accepts both `FastDocIndex` and full `DocIndex`. "Best available" wins.

- Initial upload: `FastDocIndex` stored in canonical store.
- "Analyze" button: upgrades in-place — `create_immediate_document_index()` into same `{doc_id}/` folder → overwrites `.index` file.
- All conversations referencing that `doc_id` automatically get upgraded index on next `load_local()`.
- Promote-to-global: forces full re-index (by requirement), writes back to canonical store.
- Add `index_type` column to `GlobalDocuments` and track it in canonical store DB record (Phase 2).

### 3.6 Migration Strategy

**Decision (updated):** Two tracks:

  1. **Local/conversation docs** — lazy migration on next access (in `get_uploaded_documents()`).
  2. **Global docs** — **eager migration at first server startup** via `migrate_docs.py` script, which runs automatically if canonical store does not yet contain global docs. Migration moves `storage/global_docs/{user_hash}/{doc_id}/` → `storage/documents/{user_hash}/{sha256_hash}/` and updates `GlobalDocuments.doc_storage` in DB.
- Race condition: use `FileLock` on canonical `{sha256_hash}` path during `copytree`.
- Disk temporarily doubles during migration; cleanup script reclaims old copies.
- Clone flow (`Conversation.clone()` around line 1969): updated to copy tuple references only, not doc folders.

### 3.7 Finalized User Decisions (Quick Reference)

| Decision | Choice |
|---|---|
| Dedup matching | **SHA256 content hash**. Mutable files (`.md`, `.txt`) are rehashed on modification. |
| Build scope | **All 8 phases**, end-to-end as dependency graph prescribes. |
| Old conversations | Keep flat hierarchy as-is (lazy migration moves doc files to canonical store on access). |
| Folder UI | **Reuse existing file browser UI** for folder management. Old flat list modals kept alongside for low-doc-count convs. |
| Folder context cap | **No hard cap.** Use existing `ContextualReader` (map-reduce) for long-context handling. |
| Analyze button UX | **Background with status badge.** 202 Accepted immediately; spinner badge polls for completion. |
| Orphan docs on delete | **Keep on disk**, sweep via periodic cleanup job. No immediate deletion. |
| Summary view UX | **Title in list row** (LLM-generated, replacing raw filename). **Short summary on hover tooltip.** |
| Folder chat reference syntax | **`#folder:FolderName`** — separate from PKB `@` autocomplete. New handler in `common-chat.js`. |
| Global docs migration | **Eager at first startup.** `migrate_docs.py` runs automatically; sentinel file prevents re-runs. |
---

## 4. What Is NOT Changing

- The `DocIndex` and `FastDocIndex` classes themselves — no changes to indexing logic.
- The `get_short_info()` return shape — already returns `title`, `short_summary`, `display_name`.
- The `doc_infos` string format and `#doc_N` / `#gdoc_N` prompt injection mechanism.
- The `promote_message_attached_document()` path (message attachment → full DocIndex) — already works.
- Global doc **listing** UI — `GlobalDocsManager.renderList()` — no changes needed (still lists from `GlobalDocuments` table; `doc_storage` just points to canonical path now).
- **File browser as folder UI** — the existing file browser already browses `storage/` and will show `documents/{user_hash}/` naturally. The file browser upload dialog is reused for adding docs to folders. No new folder-tree JS module needed.
- The `#folder:` prefix autocomplete in the chat input is a **new autocomplete handler** (not the existing `@` PKB autocomplete). It surfaces folders from `DocFolders` DB table.

---

## 5. New Components

| Component | Type | Purpose |
|---|---|---|
| `database/doc_folders.py` | New Python module | CRUD for `DocFolders` + `DocFolderItems` tables |
| `endpoints/doc_folders.py` | New Flask Blueprint | REST API for folder CRUD + context inclusion |
| `interface/doc-folders-manager.js` | New JS module (lightweight) | `#folder:` autocomplete handler in chat input only. No separate folder panel — file browser handles the tree UI. |
| `CanonicalDocStore` helper | New class or module | Dedup check, store-once logic, orphan cleanup |
| `migrate_docs.py` | New script | **Eager** migration of all global docs + lazy migration trigger for local docs. Runs automatically at startup if migration not yet completed. |

---

## 6. Modified Components

| Component | File | Change |
|---|---|---|
| `server.py` | `server.py` | Pass `docs_folder` to app state; add `canonical_docs_dir` |
| Conversation init | `Conversation.py` | `add_fast_uploaded_document()` → store to canonical path |
| Conversation loading | `Conversation.py` | `get_uploaded_documents()` → lazy migration + canonical load |
| Conversation clone | `Conversation.py` | `clone()` → copy tuple references not doc files |
| Promote to global | `endpoints/global_docs.py` | Force full re-index; write to canonical store |
| DB schema | `database/connection.py` | Add `DocFolders`, `DocFolderItems` tables; add `index_type` col to `GlobalDocuments` |
| Local docs UI | `interface/local-docs-manager.js` | Add "Analyze" button (background badge UX); title in row, short_summary on hover tooltip. Folder assignment via file browser (no new panel in modal). |
| Global docs UI | `interface/global-docs-manager.js` | Add "Analyze" button; title/tooltip. Folder view via file browser. |
| Reply pipeline | `Conversation.py` | Detect `#folder:FolderName` references; expand to doc list; pass through `ContextualReader` for long-context handling (no cap). |
| File browser tree | `endpoints/file_browser.py` | Optional: filter `.partial`/`.index` blobs in `storage/documents/` |

---

## 7. Implementation Plan

### Phase 0: Foundation (Pre-requisite, Quick — ~2h)

**Goal:** Wire `docs_folder` into app state so all phases can use it.

- **Task 0.1:** In `server.py`, add `docs_folder` to the `AppState` / state object (alongside `global_docs_dir`). It's already created as a directory; just not passed anywhere.
- **Task 0.2:** Add `_ensure_user_canonical_dir(state, email)` helper in `endpoints/` (mirrors `_ensure_user_global_dir` in `global_docs.py`). Returns `storage/documents/{user_hash}/`.
- **Task 0.3:** Add `create_tables()` migration for `DocFolders` and `DocFolderItems` in `database/connection.py`. Add `index_type TEXT DEFAULT 'full'` column to `GlobalDocuments` via `ALTER TABLE IF NOT EXISTS`.

**Files:** `server.py`, `database/connection.py`, `endpoints/global_docs.py` (borrow helper pattern)  
**Risk:** Low. No behavior changes.

---

### Phase 1: Canonical Store + Dedup on Upload (Core — ~4h)

**Goal:** New docs stored once in `storage/documents/{user_hash}/{sha256_hash}/`. Conversations hold pointer, not copy.

- **Task 1.1:** Create `CanonicalDocStore` helper (can be a module-level function set or thin class in new file `canonical_docs.py`):
  - `compute_file_hash(file_path) -> str` — SHA256 of file bytes. For mutable files (`.md`, `.txt`), called again on modification to detect content changes.
  - `get_canonical_path(docs_folder, user_hash, content_hash) -> str`
  - `exists_in_canonical(docs_folder, user_hash, content_hash) -> bool`
  - `store_or_get(docs_folder, user_hash, content_hash, build_fn) -> DocIndex` — builds if not exists, loads if exists. Uses `FileLock`.

- **Task 1.2:** Modify `Conversation.add_fast_uploaded_document()`:
  - Compute SHA256 of incoming file bytes.
  - Check `exists_in_canonical()` using hash. If yes, load from canonical, skip re-indexing.
  - If no, build `FastDocIndex` and store to canonical path.
  - Store `doc_storage = canonical_path` (keyed by `sha256_hash`) in the 4-tuple.

- **Task 1.3:** Modify `Conversation.add_uploaded_document()` (legacy full-index path): compute SHA256 of incoming file bytes on upload, store canonical path keyed by hash. Same dedup logic as above.

- **Task 1.4:** Modify `Conversation.add_message_attached_document()` same way: compute SHA256 and store to canonical path keyed by hash. Same dedup logic.

- **Task 1.5:** Modify `Conversation.delete_uploaded_document()`:
  - Remove tuple from list (existing behavior).
  - Do NOT `rmtree` canonical folder. Leave for orphan cleanup.

- **Task 1.6:** Add `get_canonical_doc_path(conversation, doc_id)` utility to find canonical path given a doc_id (needed for promote-to-global and upgrade).

**Files:** New `canonical_docs.py`, `Conversation.py`  
**Risk:** Medium. Test with fresh upload, reload, and chat reference of doc.  
**Backward compat:** Old 4-tuples pointing to `{conv_storage}/uploaded_documents/{doc_id}/` still load correctly via `DocIndex.load_local()` — lazy migration in Phase 2 handles them.

---

### Phase 2: Lazy Migration + Clone Fix (~3h)

**Goal:** Existing conversations migrate their doc paths to canonical store on next access.

- **Task 2.1:** In `Conversation.get_uploaded_documents()` (line 1690):
  - After `DocIndex.load_local(doc_storage)`, check if `doc_storage` is under conversation-local path (i.e., contains `uploaded_documents` in path and NOT under `storage/documents/`).
  - If yes: compute canonical path, `copytree` (if not exists), update tuple in `uploaded_documents_list`, call `save_field()`.
  - Use `FileLock` on canonical path to prevent races.
  - Log migration: `logger.info("Migrated doc %s to canonical store", doc_id)`.

- **Task 2.2:** In `Conversation.clone()` (around line 1969):
  - Find where doc storage is copied during clone.
  - Change to copy only the tuples, not the doc folders. Both original and cloned conversation reference the same canonical folder.

- **Task 2.3:** Write `migrate_docs.py` script with **two modes**:
  - **Local docs (lazy trigger mode):** Iterates all conversations, calls `get_uploaded_documents()` to trigger lazy migration on each.
  - **Global docs (eager mode, runs at startup):** Iterates all `GlobalDocuments` rows. For each, compute SHA256 of source file, copy `global_docs/{user_hash}/{doc_id}/` → `storage/documents/{user_hash}/{sha256_hash}/` (if not already there), update `GlobalDocuments.doc_storage` in DB to canonical path. Marks migration complete in a sentinel file `storage/documents/.global_migration_done` to avoid re-running.
  - `server.py` calls `migrate_docs.run_global_migration_if_needed(state)` at startup.
  - Prints summary: N docs migrated, M already canonical, K errors.

**Files:** `Conversation.py`, `migrate_docs.py`  
**Risk:** Medium. The `FileLock` pattern is already used — follow existing pattern in `save_local()`.

---

### Phase 3: Explicit Upgrade ("Analyze" Button) (~3h)

**Goal:** User can upgrade a local `FastDocIndex` doc to full `DocIndex` via a button in the local docs modal.

- **Task 3.1:** Add endpoint `POST /upgrade_doc_index/<conversation_id>/<doc_id>` in `endpoints/documents.py`:
  - Load doc from canonical store.
  - Check `hasattr(doc, '_is_fast_index') and doc._is_fast_index`. If already full, return `{"status": "already_full"}`.
  - Run `create_immediate_document_index(doc.doc_source, canonical_dir, keys)`.
  - The new full DocIndex is saved to the same `{doc_id}/` canonical folder (overwrites `.index` file).
  - Update `doc_storage` in conversation tuple (same path, but now holds full DocIndex).
  - Return `get_short_info()` of upgraded doc.

- **Task 3.2:** In `interface/local-docs-manager.js` `renderList()`:
  - If `doc.is_fast_index` (new field from `get_short_info()`), show "Analyze" button (spinner icon).
  - On click: `POST /upgrade_doc_index/{conv}/{doc_id}` — fires and **immediately returns 202 Accepted**.
  - Doc row shows an "Analyzing..." spinner badge. UI polls `GET /upgrade_doc_index_status/{conv}/{doc_id}` every 3 seconds.
  - On complete: re-render doc row (show updated LLM-generated title/summary, replace badge with "✓ Analyzed", hide Analyze button).

- **Task 3.3:** Add `is_fast_index` to `get_short_info()` return in `DocIndex.py`:
  ```python
  "is_fast_index": getattr(self, "_is_fast_index", False),
  ```

- **Task 3.4:** Add `is_fast_index` to `GlobalDocuments` return in `endpoints/global_docs.py` list endpoint (for global docs that were promoted before being upgraded).

**Files:** `DocIndex.py`, `endpoints/documents.py`, `interface/local-docs-manager.js`  
**Risk:** Low. Upgrade writes to same canonical path, all refs automatically get full index.

---

### Phase 4: Force Full Re-Index on Promote-to-Global (~2h)

**Goal:** Promote always produces a full `DocIndex`, stored in canonical store.

- **Task 4.1:** Modify `promote_doc_to_global()` in `endpoints/global_docs.py`:
  - Load doc from canonical store.
  - If `_is_fast_index`: run `create_immediate_document_index()` into canonical store (in-place upgrade).
  - If already full: just ensure canonical store has it (no-op or `copytree` from old location).
  - Insert/update `GlobalDocuments` row with `doc_storage = canonical_path`, `index_type = 'full'`.
  - Remove `shutil.copytree()` entirely — canonical store is the target.

- **Task 4.2:** Add `index_type` column handling in `database/global_docs.py` `add_global_doc()` and `list_global_docs()`.

**Files:** `endpoints/global_docs.py`, `database/global_docs.py`  
**Risk:** Low. The forced re-index is the existing behavior of `create_immediate_document_index()`.

---

### Phase 5: Folder Hierarchy — Backend (~4h)

**Goal:** CRUD for folder tree in SQLite + REST API. **Note:** The file browser already provides the visual folder tree UI for `storage/documents/{user_hash}/`. These DB tables are needed for `#folder:` context-inclusion resolution in chat and for folder metadata (name → doc_id mapping) that the file system alone cannot provide (since the canonical store uses hash-based dir names, not human-readable names).

- **Task 5.1:** Create `database/doc_folders.py` with functions:
  - `create_folder(users_dir, user_email, name, parent_folder_id, scope) -> folder_id`
  - `rename_folder(users_dir, user_email, folder_id, new_name)`
  - `delete_folder(users_dir, user_email, folder_id, recursive=False)`
  - `list_folders(users_dir, user_email, scope, parent_folder_id=None) -> List[dict]`
  - `add_doc_to_folder(users_dir, user_email, folder_id, doc_id, display_name=None)`
  - `remove_doc_from_folder(users_dir, user_email, folder_id, doc_id)`
  - `get_docs_in_folder(users_dir, user_email, folder_id, recursive=False) -> List[str]` (returns doc_ids)
  - `get_folder_by_name(users_dir, user_email, name, scope) -> Optional[dict]` (for `#folder:FolderName` resolution in chat)

- **Task 5.2:** Create `endpoints/doc_folders.py` Blueprint with REST endpoints:
  - `GET /doc_folders?scope=local|global` — list root folders
  - `GET /doc_folders/<folder_id>` — get folder + children + docs
  - `POST /doc_folders` — create folder `{name, parent_folder_id, scope}`
  - `PATCH /doc_folders/<folder_id>` — rename or move
  - `DELETE /doc_folders/<folder_id>` — delete (with `recursive` param)
  - `POST /doc_folders/<folder_id>/docs` — add doc to folder
  - `DELETE /doc_folders/<folder_id>/docs/<doc_id>` — remove doc from folder

- **Task 5.3:** Register `doc_folders_bp` in `endpoints/__init__.py`.

**Files:** New `database/doc_folders.py`, new `endpoints/doc_folders.py`, `endpoints/__init__.py`  
**Risk:** Low. Pure new code, no existing code modified.

---

### Phase 6: Folder Hierarchy — Frontend (~6h)

**Goal:** Minimal UI additions. The file browser already provides the folder tree for `storage/documents/{user_hash}/`. Phase 6 scope is **limited** to:

- **Task 6.1:** In `interface/local-docs-manager.js` `renderList()` — for each doc row:
  - Show LLM-generated **title** (from `get_short_info()`) instead of raw filename.
  - Show `short_summary` as a **hover tooltip** on the title/row.
  - Show `is_fast_index` badge ("BM25" or "Semantic") next to the doc name.
  - If `is_fast_index`, show **"Analyze" button** with spinner badge background UX (Task 3.2 UX).

- **Task 6.2:** Same title/tooltip/badge enhancements for `interface/global-docs-manager.js`.

- **Task 6.3:** Add a **"Browse in File Browser"** button/link in the local docs modal and global docs modal that opens the file browser pre-navigated to `storage/documents/{user_hash}/`. This is the power-user folder management path.

- **Task 6.4:** Add a `#folder:` autocomplete handler in `interface/common-chat.js`:
  - Triggered by typing `#folder:` in the chat input.
  - Calls `GET /doc_folders?scope=local` (or global) to fetch available folder names.
  - Shows a dropdown of matching folder names (separate from existing `@` PKB dropdown).
  - Inserts `#folder:FolderName` token on selection.

**No new split-panel or folder tree UI in the docs modals.** The flat list modal is kept as-is. Folder organization happens in the file browser.

**Files:** `interface/local-docs-manager.js`, `interface/global-docs-manager.js`, `interface/common-chat.js`, `interface/interface.html` ("Browse" button only)  
**Risk:** Low–Medium. Title/tooltip additions are low risk. `#folder:` autocomplete is medium (new handler).

---

### Phase 7: Folder Context Inclusion in Chat (~3h)

**Goal:** `#folder:FolderName` in chat message includes all docs in that folder as `#doc_N` context, using `ContextualReader` for long-context handling.

- **Task 7.1:** In `Conversation.reply()` (around line 6656 where `#doc_\d+` is detected):
  - Add detection for `#folder:[\.\w/\-]+` pattern (folder references).
  - Resolve: call `get_folder_by_name()` → `get_docs_in_folder(recursive=True)` → list of `doc_id`s.
  - Load each doc from canonical store via `DocIndex.load_local(canonical_path)`.
  - **No hard cap.** Pass all loaded docs to `ContextualReader` (map-reduce), which automatically handles context length limits — same code path as `#doc_all`.
  - Append results to `attached_docs` list with auto-generated `#doc_N` indices.

- **Task 7.2:** In `interface/common-chat.js` — add `#folder:` autocomplete (see Task 6.4).
  - Style `#folder:FolderName` tokens in the sent message with a distinct badge (similar to how `#doc_N` is handled).

- **Task 7.3:** Update `doc_infos` rebuilding to include folder-sourced docs in the manifest string.

**Files:** `Conversation.py`, `interface/common-chat.js`  
**Risk:** Medium. Modifying the reply pipeline is the highest-risk area.

---

### Phase 8: Orphan Cleanup + File Browser Polish (~2h)

**Goal:** Reclaim disk space from old conversation-local doc copies; polish file browser view of canonical store.

- **Task 8.1:** Add `cleanup_orphan_docs(state, user_email)` function:
  - Collect all doc_ids referenced by any conversation or global doc for the user.
  - List all `{user_hash}/` subdirectories in `storage/documents/`.
  - Delete entries not referenced by anyone.
  - Run via a new endpoint `POST /admin/cleanup_orphan_docs` or as a scheduled task.

- **Task 8.2:** In `endpoints/file_browser.py` `tree` endpoint:
  - Add optional filter: if path is under `storage/documents/`, suppress `.partial`, `.index`, locks files from tree output (or mark them as hidden). Only show source files + `.md` files prominently.
  - Optionally: add a "Canonical Docs" shortcut in the file browser sidebar root.

**Files:** New or existing cleanup module, `endpoints/file_browser.py`  
**Risk:** Low. Purely additive.

---

## 8. Dependency Graph

```
Phase 0 (Foundation)
  └── Phase 1 (Canonical Store + Dedup)
        ├── Phase 2 (Lazy Migration + Clone Fix)
        ├── Phase 3 (Analyze Button / Upgrade)
        │     └── Phase 4 (Promote-to-Global Force Re-index)
        └── Phase 5 (Folder Backend)
              ├── Phase 6 (Folder UI)
              └── Phase 7 (Folder Chat Context)

Phase 8 (Orphan Cleanup) depends on Phase 1+2
```

Phases 3, 5, 6, 7 can be parallelized once Phase 1 is done.

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Race condition: two conversations write same canonical doc simultaneously | Medium | Data corruption | `FileLock` on `{sha256_hash}` path during `copytree` / save |
| Clone flow copies canonical doc to conversation storage | High (will happen if clone not fixed) | Regression to old behavior | Fix clone in Phase 2 *before* running migration |
| `get_uploaded_documents()` lazy migration triggers mid-reply | Low | Slow response | Migration is quick (path update, no re-index); acceptable |
| Folder with many docs included via `#folder:` causes token overflow | Low | Slow/truncated response | `ContextualReader` map-reduce handles this automatically — no extra mitigation needed |
| Existing `storage/documents/` has legacy data (4 doc_id folders found) | Medium | Hash-keyed subdir collision | Audit at startup; legacy folders are under `{doc_id}/` not `{sha256_hash}/` — names won't collide since hashes are 64-char hex strings |
| `_visible` flag not enforced in `get_uploaded_documents()` | Low (known) | Unexpected docs in context | Enforce filter in Phase 1 once visibility semantics are confirmed |
| `dill` pickle files not readable if DocIndex class changes | Low | Load failure | Existing known risk; not introduced by this plan |

---

## 10. Out of Scope (Future)

- Cross-user sharing of docs (public/shared folders)
- Full-text search across the canonical doc store
- Doc versioning (multiple versions of same file)
- Automatic folder organization via LLM classification
- Long summary / paper details view (beyond short_summary)
- Sync with external storage (S3, Google Drive)

---

## 11. Files Created / Modified Summary

### New Files
- `canonical_docs.py` — canonical store helper (SHA256 dedup, load-or-create, FileLock)
- `database/doc_folders.py` — folder CRUD
- `endpoints/doc_folders.py` — folder REST API Blueprint
- `interface/doc-folders-manager.js` — **NOT needed** (no custom folder tree panel; `#folder:` autocomplete added directly to `common-chat.js` in Phase 6)
- `migrate_docs.py` — eager global doc migration (runs at startup) + lazy local doc migration trigger

### Modified Files
- `server.py` — wire `docs_folder` into app state
- `database/connection.py` — add `DocFolders`, `DocFolderItems` tables; add `index_type` to `GlobalDocuments`
- `database/global_docs.py` — handle `index_type` field
- `Conversation.py` — canonical paths on upload, lazy migration on load, clone fix
- `DocIndex.py` — add `is_fast_index` to `get_short_info()`
- `endpoints/documents.py` — add `/upgrade_doc_index` endpoint
- `endpoints/global_docs.py` — force re-index on promote, canonical store target
- `endpoints/__init__.py` — register `doc_folders_bp`
- `endpoints/file_browser.py` — optional: filter blob files in canonical store tree
- `interface/local-docs-manager.js` — Analyze button (background badge), title in row, tooltip for summary, "Browse" link to file browser
- `interface/global-docs-manager.js` — Analyze button, title/tooltip, "Browse" link
- `interface/interface.html` — "Browse in File Browser" button in both doc modals
- `Conversation.py` (reply) — `#folder:FolderName` reference detection + expansion via `ContextualReader`
- `interface/common-chat.js` — `#folder:` autocomplete handler + badge styling for folder tokens

---

## 12. Testing Checklist

- [ ] Upload same PDF to two conversations → only one `{sha256_hash}/` in canonical store (not two)
- [ ] Upload same file under different filename → dedup still triggers (SHA256 match)
- [ ] Delete doc from conv A → doc still loads in conv B
- [ ] Upgrade FastDocIndex via Analyze button → both conversations get full DocIndex on next load
- [ ] Promote local doc to global → canonical store has full DocIndex; GlobalDocuments row has `doc_storage` pointing to canonical
- [ ] Lazy migration: old conversation with local copy → on next load, tuple updated to canonical path
- [ ] Clone conversation → cloned conv references same canonical doc, not a new copy
- [ ] Create folder, add doc, rename folder → doc still accessible, title updated
- [ ] `#folder:Research/Papers` in chat → all docs in that folder appear as `#doc_N` in context via ContextualReader
- [ ] Global docs migration at startup → all `global_docs/` entries moved to canonical store, `GlobalDocuments.doc_storage` updated, sentinel file created
- [ ] Delete folder → docs remain in canonical store (folder is reference only)
- [ ] Orphan cleanup → docs with no references removed from canonical store
