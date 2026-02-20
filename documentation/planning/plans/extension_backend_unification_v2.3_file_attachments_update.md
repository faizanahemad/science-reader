# Extension Backend Unification Plan v2.3 — File Attachments Update

> **NOTE**: `extension_server.py` referenced in this document has been deprecated. The Chrome extension now uses `server.py` (port 5000). See `documentation/features/extension/` for current architecture.

**Date**: 2026-02-16  
**Status**: Draft addendum to v2.3  
**Scope**: File attachment system unification between main UI and extension

---

## Executive Summary

Recent development (Feb 2026) introduced a unified file attachment system across both main UI and extension with:

1. **Main UI**: FastDocIndex (BM25, 1-3s upload) for message attachments, full DocIndex (FAISS, 15-45s) for conversation docs, global docs with promotion flows
2. **Extension**: Simple pdfplumber text extraction (system messages), display_attachments metadata in DB
3. **9 bug fixes** applied to both UIs for attachment persistence, LLM awareness, and removal functionality

This update adds **new tasks to the unification plan** to bridge these systems and migrate extension data.

---

## File Attachment System Comparison

### Architecture Differences

| Aspect | Main UI | Extension | Unification Target |
|--------|---------|-----------|-------------------|
| **Upload speed** | 1-3s (FastDocIndex), 15-45s (full DocIndex) | Instant (text extraction only) | FastDocIndex by default, opt-in promotion |
| **Indexing** | BM25 keyword + FAISS semantic | None (raw text in system message) | BM25 for all, FAISS on promotion |
| **Document lists** | Two lists: `uploaded_documents_list` (promoted) + `message_attached_documents_list` (temp) | No lists (system messages only) | Adopt two-list model |
| **Storage** | Filesystem: `conversations/{id}/uploaded_documents/{doc_id}/` | DB: system message content in ExtensionMessages | Migrate to filesystem |
| **Persistence** | `display_attachments` in message dict (JSON) | `display_attachments` in ExtensionMessages.display_attachments (TEXT) | Keep both, migrate to message dict |
| **Global docs** | Full system with 7 endpoints, user-scoped | None | Add endpoints to extension bridge |
| **Promotion** | Message-attached → conversation-level → global | None | Add promotion to extension |
| **LLM awareness** | Auto-injection via `#doc_N` references | System messages merged into prompt | Keep both patterns |
| **Re-attachment** | Click to reuse existing doc_id, no re-upload | Click to reuse thumbnail, no re-upload | Unified |

### Endpoint Gap Analysis

**Main UI has, Extension lacks:**

1. `POST /upload_doc_to_conversation/<id>` — Creates DocIndex (main has, extension has simplified version)
2. `POST /promote_message_doc/<id>/<doc_id>` — Promote to conversation-level
3. `DELETE /delete_document_from_conversation/<id>/<doc_id>` — Remove doc
4. `GET /list_documents_by_conversation/<id>` — List all docs
5. `GET /download_doc_from_conversation/<id>/<doc_id>` — Download doc file
6. All 7 global docs endpoints (`/global_docs/*`)

**Extension has, Main UI uses differently:**

7. `POST /ext/upload_doc/<id>` — Simple pdfplumber extraction, stores as system message (128K char limit)

### Data Schema Comparison

**display_attachments Field:**

| Field | Main UI | Extension | Migration Strategy |
|-------|---------|-----------|-------------------|
| **Storage** | Message dict key | DB TEXT column (JSON) | Migrate to message dict during conversation conversion |
| **Schema** | `[{type, name, thumbnail, doc_id?, source?}]` | `[{type, name, thumbnail}]` | Add `doc_id`/`source` during migration |
| **Thumbnail size** | 80x80 JPEG 70% | 100x100 JPEG 60% | Keep extension size (already smaller) |

**Conversation Fields:**

| Field | Main UI | Extension | Migration Strategy |
|-------|---------|-----------|-------------------|
| `uploaded_documents_list` | List of (doc_id, storage, url) tuples | N/A | Create empty list |
| `message_attached_documents_list` | List of (doc_id, storage, url) tuples | N/A | Create from system messages |
| `doc_infos` | String with `#doc_N` mappings | N/A | Rebuild from document lists |

---

## New Plan Tasks (Milestone 6: File Attachments)

### Milestone 6: File Attachment Unification

**Goal**: Extension conversations support the full file attachment system (FastDocIndex, promotion, global docs) with data migration from existing system messages.

**Dependencies**: M1 (auth), M2 (page context), M3 (conversation bridge)

**Effort**: 5-7 days

---

#### Task 6.1: Add FastDocIndex upload to extension bridge

**What**: Replace extension's simple pdfplumber extraction with FastDocIndex creation (matching main UI's fast path).

**Files to create**:
- None (endpoint already exists at `/ext/upload_doc/<id>`)

**Files to modify**:
- `extension_server.py` — Update `ext_upload_doc()` to create FastDocIndex instead of system message

**Details**:
- Change from:
  ```python
  # Current: Simple text extraction
  doc_content = f"[Document uploaded: {filename}]\n[Pages: {N}]\n\n{full_text}"
  conv.add_message("system", doc_content)
  ```
- Change to:
  ```python
  # New: FastDocIndex creation
  from DocIndex import create_fast_document_index
  doc_index = create_fast_document_index(pdf_path, conversation_storage, keys)
  conversation.add_message_attached_document(pdf_path)
  ```
- Return shape changes from `{status, filename, pages, chars}` to `{status, doc_id, source, title}` (matches main UI)
- Extension client needs update to store `doc_id` in `display_attachments` (currently only stores `{type, name, thumbnail}`)

**Acceptance criteria**:
- Extension PDF upload creates FastDocIndex on disk
- Upload completes in 1-3s (not instant, but much faster than 15-45s full index)
- Response includes `doc_id` for later reference
- Extension client stores `doc_id` in `display_attachments` metadata

---

#### Task 6.2: Migrate existing extension system messages to FastDocIndex

**What**: One-time migration script to convert existing extension PDF system messages to FastDocIndex format.

**Files to create**:
- `scripts/migrate_extension_docs.py` — Migration script

**Details**:
- For each extension conversation in `extension.db`:
  1. Find system messages with pattern `[Document uploaded: ...]`
  2. Extract filename and text content from message
  3. Create FastDocIndex from text (no file available, use content directly)
  4. Add to conversation's `message_attached_documents_list`
  5. Update `display_attachments` with `doc_id` and `source`
  6. **Keep system message** (for LLM backward compat during transition)
- Handle edge cases: missing content, corrupt PDFs, large documents
- Dry-run mode with report before actual migration

**Acceptance criteria**:
- Script successfully migrates all extension conversations with PDF system messages
- FastDocIndex created for each document with correct `doc_id` hash
- `display_attachments` updated with `doc_id` and `source` fields
- System messages preserved
- Migration report shows count of docs migrated, skipped, failed

---

#### Task 6.3: Add document promotion endpoints to extension bridge

**What**: Add `/ext/promote_message_doc/<id>/<doc_id>` and `/ext/promote_to_global/<id>/<doc_id>` for promoting attachments.

**Files to create**:
- `endpoints/ext_documents.py` — New blueprint for document operations

**Files to modify**:
- `server.py` — Register `ext_documents_bp`

**Details**:
- `POST /ext/promote_message_doc/<conversation_id>/<doc_id>`:
  - Rate limit: 20/min
  - Auth: `@auth_required`
  - Calls `conversation.promote_message_attached_document(doc_id)` (creates full DocIndex with FAISS, 15-45s)
  - Returns `{status, doc_id, source, title}`
- `POST /ext/promote_to_global/<conversation_id>/<doc_id>`:
  - Rate limit: 20/min
  - Auth: `@auth_required`
  - Copies doc from conversation to `storage/global_docs/{user_hash}/{doc_id}/`
  - Registers in `GlobalDocuments` table
  - Returns `{status, doc_id}`

**Acceptance criteria**:
- Extension can promote message-attached docs to conversation-level (full index)
- Extension can promote conversation docs to global storage
- Promotion flows match main UI behavior exactly

---

#### Task 6.4: Add global docs endpoints to extension bridge

**What**: Add all 7 global docs endpoints to extension (`/ext/global_docs/*`).

**Files to modify**:
- `endpoints/ext_documents.py` — Add global docs routes

**Details**:
- `GET /ext/global_docs/list` → delegates to `endpoints/global_docs.py:list_global_docs()`
- `POST /ext/global_docs/upload` → delegates to `endpoints/global_docs.py:upload_global_doc()`
- `GET /ext/global_docs/info/<doc_id>` → delegates
- `GET /ext/global_docs/download/<doc_id>` → delegates
- `DELETE /ext/global_docs/<doc_id>` → delegates
- `POST /ext/global_docs/promote/<conv_id>/<doc_id>` → delegates
- `GET /ext/global_docs/serve?file=<doc_id>` → delegates (for PDF viewer)
- All routes use `@auth_required` and appropriate rate limits

**Acceptance criteria**:
- Extension has full global docs API parity with main UI
- Extension can upload, list, download, delete, promote global docs
- All routes return same response shapes as main UI equivalents

---

#### Task 6.5: Add document listing endpoints to extension bridge

**What**: Add `/ext/documents/list/<id>` and `/ext/documents/delete/<id>/<doc_id>` for managing conversation docs.

**Files to modify**:
- `endpoints/ext_documents.py` — Add list and delete routes

**Details**:
- `GET /ext/documents/list/<conversation_id>`:
  - Rate limit: 500/min
  - Returns combined list from both `uploaded_documents_list` and `message_attached_documents_list`
  - Response shape: `[{doc_id, title, source, type: 'uploaded'|'message_attached', index: N}]`
- `DELETE /ext/documents/delete/<conversation_id>/<doc_id>`:
  - Rate limit: 100/min
  - Removes from appropriate list (uploaded or message-attached)
  - Deletes filesystem storage
  - Returns `{status: 'ok'}`

**Acceptance criteria**:
- Extension can list all docs in a conversation (both lists)
- Extension can delete specific docs by `doc_id`
- Deletion removes both metadata and filesystem storage

---

#### Task 6.6: Update extension client for DocIndex system

**What**: Update extension JS to use the new doc endpoints and store `doc_id` in attachments.

**Files to modify**:
- `extension/sidepanel/sidepanel.js` — Update `uploadPendingPdfs()`, `buildDisplayAttachments()`
- `extension/shared/api.js` — Add new API methods for promotion, listing, deletion

**Details**:
- `uploadPendingPdfs()`: Store returned `doc_id` in `state.pendingImages` entries
- `buildDisplayAttachments()`: Include `doc_id` and `source` in payload
- Add `API.promoteMessageDoc(conversationId, docId)` method
- Add `API.promoteToGlobal(conversationId, docId)` method
- Add `API.listDocuments(conversationId)` method
- Add `API.deleteDocument(conversationId, docId)` method
- Add context menu to rendered attachments with options:
  - "Promote to Conversation" (creates full index)
  - "Promote to Global" (makes doc reusable across conversations)
  - "Delete" (removes from conversation)

**Acceptance criteria**:
- Extension stores `doc_id` in `display_attachments` metadata
- Extension UI shows context menu on attachments
- Promotion/deletion actions work via new endpoints

---

#### Task 6.7: Update extension backend unification plan v2.3 with file attachment details

**What**: Add this entire addendum to the main unification plan document.

**Files to modify**:
- `documentation/planning/plans/extension_backend_unification.plan.md` — Add new section 8 and Milestone 6

**Details**:
- Insert architecture comparison table in section 4c (after endpoint mapping)
- Add Milestone 6 after Milestone 5 (workspace/domain UI)
- Update effort estimates (total plan now 22-32 days instead of 18-26 days)
- Update API endpoint mapping (section 4c) to include new doc endpoints

**Acceptance criteria**:
- Plan updated with file attachment unification details
- All 7 tasks documented with acceptance criteria
- Effort estimates revised

---

## Updated Timeline

| Milestone | Original Effort | New Effort | Reason |
|-----------|----------------|------------|--------|
| M1: Dual Auth | 2-3 days | 2-3 days | Unchanged |
| M2: Page Context | 2-3 days | 2-3 days | Unchanged |
| M3: Conversation Bridge | 5-7 days | 5-7 days | Unchanged |
| M4: Extension Features | 4-6 days | 4-6 days | Unchanged |
| M5: Workspace UI | 4-6 days | 4-6 days | Unchanged |
| **M6: File Attachments** | **N/A** | **5-7 days** | **New milestone** |
| **Total** | **18-26 days** | **22-32 days** | **+4-6 days** |

---

## Data Migration Checklist

### Pre-Migration

- [ ] Backup `extension.db` (full copy)
- [ ] Backup main server `users.db` (full copy)
- [ ] Run migration script in dry-run mode
- [ ] Review migration report for errors

### Migration Steps

1. [ ] Run `scripts/migrate_extension_docs.py --dry-run` — generates report
2. [ ] Review report, verify doc count matches expectations
3. [ ] Run `scripts/migrate_extension_docs.py --execute` — performs migration
4. [ ] Verify all system messages have corresponding FastDocIndex entries
5. [ ] Verify `display_attachments` updated with `doc_id`/`source`
6. [ ] Test extension doc upload with new endpoint (should create FastDocIndex)
7. [ ] Test promotion flows (message-attached → conversation, conversation → global)
8. [ ] Test global docs (upload, list, delete)

### Post-Migration Validation

- [ ] All extension conversations have correct document lists
- [ ] All migrated docs have valid `doc_id` (deterministic hash)
- [ ] System messages preserved for backward compat
- [ ] Extension client can list/delete/promote docs
- [ ] Global docs work across web UI and extension

---

## Risk Assessment for File Attachments

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Migration data loss** | High | Dry-run mode with full report; backup before migration; keep system messages as fallback |
| **doc_id hash collisions** | Low | FastDocIndex uses mmh3.hash(source + filetype + doctype) — same as main UI, proven safe |
| **Extension client breaks with new response shape** | Medium | Gradual rollout: new endpoint returns both old and new shapes during transition period |
| **Large documents timeout during migration** | Medium | Migration script processes in batches with progress checkpoints; skip timeout and log for manual review |
| **Filesystem storage exceeds disk space** | Low | Calculate storage needs pre-migration; warn if insufficient space; migration script checks disk space before starting |
| **Global docs invisible to web UI** | Low | Use same `GlobalDocuments` table and storage paths as main UI; test cross-UI visibility |

---

## Open Questions

1. **System message cleanup**: After migration, should we delete old system messages or keep them for compatibility? → **Recommendation: Keep for 1 month, then clean up**
2. **BM25 index size**: Will BM25 indices significantly increase storage? → **Investigate during M6.1, dill serialization is compact**
3. **Extension PDF viewer**: Should extension have PDF viewer like main UI? → **Defer to Phase 2, not critical for unification**
4. **Mixed conversations**: How to handle conversations with both old (system msg) and new (FastDocIndex) docs? → **Support both, migration makes them equivalent**

---

## Updated API Endpoint Mapping (extends section 4c)

### File Attachments (7 new endpoints)

| Extension Endpoint | Auth | Main Server Target | Plan Task | Notes |
|---|---|---|---|---|
| `POST /ext/upload_doc/<id>` | JWT | Modified in place → `create_fast_document_index()` | M6 Task 6.1 | Changes from system message to FastDocIndex |
| `POST /ext/promote_message_doc/<id>/<doc_id>` | JWT | NEW `endpoints/ext_documents.py` → `/promote_message_doc` | M6 Task 6.3 | Thin wrapper around main UI endpoint |
| `POST /ext/promote_to_global/<id>/<doc_id>` | JWT | NEW `endpoints/ext_documents.py` → `/global_docs/promote` | M6 Task 6.3 | Delegates to global docs endpoint |
| `GET /ext/documents/list/<id>` | JWT | NEW `endpoints/ext_documents.py` | M6 Task 6.5 | Returns combined doc list |
| `DELETE /ext/documents/delete/<id>/<doc_id>` | JWT | NEW `endpoints/ext_documents.py` | M6 Task 6.5 | Removes from conversation |
| `GET /ext/global_docs/*` (7 routes) | JWT | NEW `endpoints/ext_documents.py` → delegates to `endpoints/global_docs.py` | M6 Task 6.4 | Full global docs API |

**Total endpoint count after M6**: 38 (original) + 7 (file attachments) = **45 extension endpoints**

---

## Implementation Notes

- **Backward compatibility**: Extension system messages remain functional during transition (merged into LLM prompt as before)
- **Storage consolidation**: After unification, extension conversations use main server's filesystem storage, `extension.db` only stores auth/settings
- **Performance**: FastDocIndex creation adds 1-3s to PDF uploads (up from instant), but enables semantic search and promotion
- **Client changes**: Extension UI needs updates to store/display `doc_id`, show promotion context menu
- **Testing**: All 9 bug fixes from main UI attachment system must be validated in extension after unification

---

## References

- `documentation/features/file_attachments/file_attachment_preview_system.md` — Complete architecture and bug fix documentation
- `documentation/features/global_docs/README.md` — Global docs implementation guide
- `endpoints/documents.py` — Main UI document endpoints
- `extension_server.py` lines 1972-2045 — Current extension PDF upload
- `Conversation.py` lines 1655-1811 — Two-list document system implementation

---

**End of v2.3 File Attachments Update**
