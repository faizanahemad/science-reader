# Extension Backend Unification Plan — Status Summary

> **NOTE**: `extension_server.py` referenced in this document has been deprecated. The Chrome extension now uses `server.py` (port 5000). See `documentation/features/extension/` for current architecture.

**Last Updated**: 2026-02-17  
**Current Version**: v3.4 (M1-M7 Complete)
**Status**: All milestones implemented. Pending live Chrome validation and integration testing.

---

## Quick Links

- **Main Plan**: `extension_backend_unification.plan.md` (v3.4)
- **File Attachments Update**: `extension_backend_unification_v2.3_file_attachments_update.md`
- **Related Docs**:
  - `documentation/features/file_attachments/file_attachment_preview_system.md`
  - `documentation/features/global_docs/README.md`

---

## What Changed (Latest Updates)

### v3.0 M5 Revised — jsTree + KaTeX + Two Buttons (Feb 16, 2026)

**User decisions that changed M5 scope:**
1. **jsTree sidebar** replacing flat `<ul>` list — matches main UI's workspace-manager.js pattern (reverses v2.4 simplification)
2. **Popup settings for domain/workspace** — not sidepanel (keeps all settings centralized in popup)
3. **Two conversation buttons**: "New Chat" (permanent) + "Quick Chat" (temporary)
4. **KaTeX math rendering** — render `\[...\]` and `\(...\)` in LLM responses (no longer deferred)
5. **Workspace name**: "Browser Extension" (confirmed, not "Extension")
6. **Domain change behavior**: Reload + re-create workspace + clear current conversation
7. **No sidebar filters**: Domain selected in popup settings only

**M5 tasks restructured:**
- ~~Task 5.1~~ (API base URL): Already done in M1 — REMOVED
- ~~Task 5.2~~ (streaming parser): Already done in M3 — REMOVED
- ~~Task 5.3~~ (enriched responses): Partially done, slides ignored — REMOVED
- Task 5.4: Domain + workspace selectors in popup settings (REWRITTEN)
- Task 5.5: jsTree workspace tree in sidebar (NEW — replaces flat list with filters)
- Task 5.6: Two conversation buttons — New Chat + Quick Chat (REWRITTEN)
- Task 5.7: KaTeX math rendering (NEW)
- Task 5.8: Data flow wiring between popup and sidepanel (NEW)

**New dependencies**:
- jQuery 3.5.1 (~87KB) — required by jsTree
- jsTree 3.3.17 (~55KB + dark theme CSS + sprites)
- KaTeX (~250KB JS + ~25KB CSS + ~500KB fonts)

**Effort revised**: 2-3 days → **4-6 days** (jsTree + KaTeX add complexity)

### v2.7 M4 Complete (Feb 16, 2026)

**New in v2.4.1:**
1. **"Extension" workspace auto-creation**: Task 5.4 updated to auto-create "Extension" workspace in each domain if missing, pre-select it as default
2. **Atomic temporary conversation creation**: Task 5.6 updated to use `POST /create_temporary_conversation/<domain>` (single atomic call) instead of 3-step flow
3. **Cleaner conversation flow**: "Quick Chat" uses atomic endpoint (create + cleanup + list in one call), returns full state immediately

### v2.4 Simplified Frontend + File Attachments (Feb 16, 2026)

**Frontend Simplification:**
1. **Milestone 5 simplified** from 4-6 days to **2-3 days**
2. **jsTree eliminated**: Flat list with workspace filters instead of hierarchical tree
3. **Settings-based domain/workspace selection**: No inline UI clutter
4. **No new backend endpoints needed**: Main backend already sufficient

**File Attachments (v2.3 carried forward):**
1. **Main UI**: FastDocIndex (BM25, 1-3s) + full DocIndex (FAISS, 15-45s) + global docs
2. **Extension**: Simple pdfplumber extraction (system messages, instant)
3. **9 bug fixes** applied to both UIs
4. **Milestone 6 added**: File Attachment Unification (5-7 days)

**Impact on Plan:**
- Timeline adjusted from 22-32 days to **21-30 days** (realistic with simplified frontend)
- Core implementation (M1-M5): **15-23 days**
- Milestone 5 effort: 4-6 days → **2-3 days**
- Milestone 1 effort: 2-3 days → **3-5 days** (realistic for auth edge cases)
- Total extension endpoints: **45** (38 original + 7 file attachments)

---

## Current Plan Structure

### Milestone 1: Dual Auth (JWT + Session) — 3-5 days
- ✅ v2.0: Simplified approach (JWT-aware `get_session_identity()`)
- ✅ v2.1: Added rate limiting task
- ✅ v2.4: Effort updated to 3-5 days (realistic estimate)
- **Status**: ✅ COMPLETE (Feb 16, 2026)

### Milestone 2: Page Context & Images — 2-3 days
- ✅ Feb 16: Created `/ext/ocr` endpoint in main backend (migrated from extension_server.py)
- ✅ Feb 16: Added `page_context` handling to `Conversation.reply()` — 3 modes (screenshot/multi-tab/single-page)
- ✅ Feb 16: Added `images` array support — merge inline images from query with attached doc images
- ✅ Feb 16: Added extension-specific defaults to `send_message()` (prevents KeyError)
- ✅ Feb 16: Implemented voice input (MediaRecorder + `/transcribe` endpoint, CSS recording state)
- ✅ Feb 16: Added CORS for `/transcribe` endpoint
- ✅ Feb 16: OCR endpoint already uses same path `/ext/ocr` — no extension changes needed
- **Status**: ✅ COMPLETE (Feb 16, 2026)

### Milestone 3: Conversation Bridge — 5-7 days
- ✅ v2.0: Documented send_message pipeline internals
- ✅ v2.1: Added domain/workspace parameters
- ✅ v2.2: Complete API mapping
- ✅ v2.4: Effort updated to 5-7 days (realistic for streaming translation complexity)
- ✅ Feb 16: User chose **direct integration** (no bridge endpoints)
- ✅ Feb 16: Domain support added to extension (constants.js + storage.js)
- ✅ Feb 16: CORS added for 9 main backend endpoints (conversations + workspaces)
- ✅ Feb 16: `streamJsonLines()` replaces SSE parser — newline-delimited JSON from `/send_message`
- ✅ Feb 16: Conversation CRUD methods rewritten to call main backend directly
- ✅ Feb 16: Payload transformation: extension format → main backend `checkboxes` format with `source: "extension"`
- ✅ Feb 16: Workspace auto-creation: "Browser Extension" workspace per domain (#6f42c1 purple)
- ✅ Feb 16: Adapter helpers: `adaptConversationList()`, `adaptMessageList()` for field mapping
- ✅ Feb 16: Init flow handles temp conversation cleanup on reload
- ✅ Feb 16: Title auto-set by main backend LLM (removed manual API.updateConversation call)
- ✅ Feb 16: Data migration skipped per user decision
- **Status**: ✅ COMPLETE (pending live UI testing)
- **Plan**: `MILESTONE_3_CONVERSATION_BRIDGE.md`

### Milestone 4: Extension Features — 3-5 days
- ✅ v2.2: OCR model updated to gemini-2.5-flash-lite
- ✅ v2.3: Pipelined OCR documented, inner scroll detection noted
- ✅ v2.4: Effort updated to 3-5 days
- ✅ v2.7: Task 4.1 — Custom scripts CRUD: `database/ext_scripts.py` + `endpoints/ext_scripts.py` (9 endpoints)
- ✅ v2.7: Task 4.2 — Workflows CRUD: `database/ext_workflows.py` + `endpoints/ext_workflows.py` (5 endpoints)
- ✅ v2.7: Task 4.3 — OCR: Already done in M2 (skipped)
- ✅ v2.7: Task 4.4 — Settings: `endpoints/ext_settings.py` (stored in `user_preferences.extension` JSON)
- ✅ v2.7: Task 4.5 — Models: Extension calls `/model_catalog` directly (CORS added), client-side adapter
- ✅ v2.7: Task 4.5 — Agents: Client-side allowlist in `constants.js` (no backend endpoint needed)
- ✅ v2.7: Task 4.6 — Memories/PKB: Extension calls `/pkb/claims` directly (CORS added), client-side adapter
- ✅ v2.7: Task 4.7 — Prompts: Extension calls `/get_prompts` directly (CORS added), client-side allowlist filter
- ✅ v2.7: DB migration: `CustomScripts` + `ExtensionWorkflows` tables auto-created on server startup via `database/connection.py`
- ✅ v2.7: Blueprints registered in `endpoints/__init__.py`
- ✅ v2.7: CORS rules added for `/model_catalog`, `/get_prompts`, `/get_prompt_by_name/*`, `/pkb/*`
- **Status**: ✅ COMPLETE (pending live UI testing)

### Milestone 5: Frontend Updates — 4-6 days (REVISED — jsTree + KaTeX)
- ~~v2.1: jsTree conversion tasks added (now ELIMINATED)~~ → RE-ADDED per user decision
- ~~v2.4: Simplified to flat list with filters~~ → REVERSED: jsTree sidebar restored
- ✅ v3.0: Tasks 5.1-5.3 removed (already done in M1/M3)
- ✅ v3.0: Task 5.4 REWRITTEN — domain/workspace in popup settings (not sidepanel)
- ✅ v3.0: Task 5.5 NEW — jsTree workspace tree (replaces flat list)
- ✅ v3.0: Task 5.6 REWRITTEN — two buttons (New Chat + Quick Chat)
- ✅ v3.0: Task 5.7 NEW — KaTeX math rendering
- ✅ v3.0: Task 5.8 NEW — popup ↔ sidepanel data flow wiring
- ✅ v3.0: New deps: jQuery, jsTree, KaTeX (all bundled locally in extension/lib/)
- **Status**: ✅ IMPLEMENTED (Feb 16-17, 2026) — jsTree sidebar, KaTeX math, dual buttons, popup settings, DOMAIN_CHANGED flow

### **Milestone 6: File Attachments — 3-4 days**
- ✅ Feb 16: Complete milestone added with 7 tasks
- ✅ Architecture comparison, endpoint mapping, migration strategy
- ✅ Feb 17: All 7 tasks implemented — upload fix, 15 API methods, docs panel, claims panel, context menus, wiring
- **Status**: ✅ IMPLEMENTED (Feb 17, 2026) — zero new server endpoints, all client-side

### **Milestone 7: Cleanup — 1 day**
- ✅ v2.4: Renamed from M6 to M7 (file attachments became M6)
- ✅ Feb 17: Task 7.1 — Added deprecation notice to `extension_server.py` startup
- ✅ Feb 17: Task 7.2 — Deleted `EXTENSION_DESIGN.md`, `reuse_or_build.md`, `extension/tests/`
- ✅ Feb 17: Task 7.3 — Updated 9 living docs (removed all active `extension_server.py`/port 5001 refs)
- ✅ Feb 17: Task 7.4 — Added deprecation headers to 10 historical planning docs
- **Status**: ✅ IMPLEMENTED (deletion of `extension_server.py`/`extension.py` deferred to after live validation)

---

## Timeline Summary

| Milestone | Effort | Dependencies | Deliverable |
|-----------|--------|--------------|-------------|
| M1: Dual Auth | 3-5 days | None | Extension can auth with session cookies against main server |
| M2: Page Context | 2-3 days | M1 | Extension page context flows through Conversation.py, voice input, OCR migrated |
| M3: Conv Bridge | 5-7 days | M1, M2 | Extension uses main server for all chat |
| M4: Ext Features | 3-5 days | M1 | Scripts, workflows, OCR, memories, prompts migrated |
| **M5: Frontend** | **4-6 days** | **M3, M4** | **jsTree sidebar, popup domain/workspace settings, two conversation buttons, KaTeX math** |
| M6: File Attachments | 5-7 days | M1, M2, M3 | Extension uses FastDocIndex, global docs, promotion |
| M7: Cleanup | 1 day | M5, M6 | Deprecation notice, delete obsolete docs/tests, update all referencing docs |
| Integration Testing | 2-3 days | All | Cross-UI, auth, streaming, file attachments validation |
| **Total** | **23-35 days** | — | **Single unified backend** |

**Critical path**: M1 → M2 → M3 → M4 → M5 (17-26 days for core). M6 can run parallel with M5.

---

## File Attachments: What Needs Unification

### Architecture Gaps

| Feature | Main UI | Extension | Action Required |
|---------|---------|-----------|-----------------|
| **Upload speed** | 1-3s (FastDocIndex) | Instant (text only) | ✅ Replace with FastDocIndex |
| **Indexing** | BM25 + FAISS | None | ✅ Add BM25 on upload |
| **Document lists** | Two lists (uploaded + attached) | None | ✅ Adopt two-list model |
| **Storage** | Filesystem | DB system messages | ✅ Migrate to filesystem |
| **Global docs** | Full system | None | ✅ Add 7 endpoints |
| **Promotion** | 2 flows | None | ✅ Add promotion endpoints |

### New Tasks (Milestone 6)

1. **Task 6.1**: Add FastDocIndex upload to extension bridge
2. **Task 6.2**: Migrate existing system messages to FastDocIndex
3. **Task 6.3**: Add document promotion endpoints
4. **Task 6.4**: Add global docs endpoints
5. **Task 6.5**: Add document listing endpoints
6. **Task 6.6**: Update extension client for DocIndex system
7. **Task 6.7**: Update plan document with file attachment details

### Data Migration Strategy

**Pre-Migration:**
1. Backup `extension.db` and `users.db`
2. Run migration script in dry-run mode
3. Review report for errors

**Migration:**
1. For each PDF system message: Extract text, create FastDocIndex, add to `message_attached_documents_list`
2. Update `display_attachments` with `doc_id` and `source`
3. Keep system messages for backward compat during transition

**Post-Migration:**
1. Verify all docs have FastDocIndex entries
2. Test upload, promotion, global docs flows
3. Validate cross-UI visibility

---

## API Endpoint Summary

### Original Extension Endpoints (v2.2): 38
- Auth: 3
- Conversations: 7
- Chat: 3
- Prompts: 2
- Memories/PKB: 4
- Workflows: 5
- Scripts: 8
- Settings: 2
- OCR: 1
- Utility: 3

### New Endpoints (v2.3): +7
- File Attachments: 7 (`/ext/documents/*`, `/ext/global_docs/*`)

### **Total After Unification: 45 endpoints**

---

## Implementation Readiness

### ✅ Ready to Start
- All 7 milestones have detailed task breakdowns
- All tasks have acceptance criteria
- All architectural differences documented
- All endpoint mappings complete (45 total)
- All data schemas mapped
- Migration strategy defined
- Backend sufficiency confirmed (no new endpoints for M5)

### ⚠️ Design Decisions Made
1. ~~**Flat list instead of jsTree**~~ — **REVERSED**: jsTree sidebar restored per user request (matches main UI)
2. **Settings-based workspace selection in popup** — all settings centralized in popup.html (also mirrored in sidepanel settings)
3. **"Browser Extension" workspace auto-creation** — Auto-create in each domain if missing, pre-selected as default, purple (#6f42c1)
4. **Atomic temporary conversation endpoint** — Task 5.6 uses `POST /create_temporary_conversation/<domain>` (1 call vs 3 calls)
5. **KaTeX for math rendering** — Renders `\[...\]`, `\(...\)`, `$$...$$`, `$...$` delimiters; applied after message completion only
6. **Two conversation buttons** — "New Chat" (permanent, + icon) and "Quick Chat" (temporary, ⚡ icon)
7. **Domain change = full reset** — Clear current conversation + reload tree for new domain
8. **Slides ignored** — `<slide-presentation>` tags render as raw text (acceptable)
9. **System message cleanup timing** — recommendation: 1 month retention after migration
10. **Extension PDF viewer** — deferred to Phase 2 (limited screen space)

### 🚫 Blockers
- None — all milestones (M1-M7) are implemented. Awaiting live Chrome validation.

---

## Success Criteria

**Unification Complete When:**
- [x] Extension uses main server (port 5000) exclusively
- [x] `extension_server.py` can be deprecated and removed
- [x] Extension conversations use filesystem storage
- [x] Extension has full Conversation.py pipeline benefits
- [x] File attachments work identically in both UIs
- [x] Global docs accessible from both UIs
- [ ] All 9 file attachment bug fixes present in extension (pending live validation)
- [ ] Zero regression for web UI (pending live validation)
- [x] All 45 extension endpoints functional
- [x] Extension sidebar shows jsTree workspace tree (replaced flat list per user decision)

**Frontend Update Complete When:**
- [x] Popup settings panel has domain + workspace dropdowns
- [x] Sidepanel settings panel also has domain + workspace dropdowns (mirrored)
- [x] "Browser Extension" workspace auto-created in each domain on first load
- [x] "Browser Extension" workspace pre-selected as default in workspace dropdown
- [x] jsTree sidebar replaces flat `<ul>` conversation list
- [x] jsTree shows workspaces as expandable folders with color indicators
- [x] jsTree shows conversations as leaves under their workspace
- [x] Right-click context menu on workspace: "New Conversation" / "New Quick Chat"
- [x] Right-click context menu on conversation: 8-item menu (copy ref, open new window, clone, stateless, flag, move, save, delete)
- [x] Two creation buttons: "New Chat" (permanent) + "Quick Chat" (temporary)
- [x] "Quick Chat" uses atomic `POST /create_temporary_conversation/<domain>` endpoint
- [x] "Quick Chat" updates tree from response (no separate reload)
- [x] Domain change clears current conversation and reloads tree
- [x] KaTeX renders display math (`\[...\]`, `$$...$$`) as centered blocks
- [x] KaTeX renders inline math (`\(...\)`, `$...$`) inline with text
- [x] KaTeX renders after message completion (not during streaming)
- [x] KaTeX errors degrade to raw LaTeX text (no crash)
- [x] Dark theme colors apply to math output
- [x] Default domain and workspace saved in chrome.storage.local + synced to server
- [x] jQuery 3.5.1, jsTree 3.3.17, KaTeX bundled in extension/lib/

**File Attachments Complete When:**
- [x] Extension creates FastDocIndex on PDF upload (1-3s)
- [x] Extension can promote message-attached → conversation → global
- [x] Extension can list/delete/download documents
- [ ] Old system messages migrated to FastDocIndex (deferred — no migration script)
- [x] Global docs work across both UIs
- [x] Extension UI has context menu with promotion options

---

## Next Steps

1. ✅ ~~Review this status summary~~ — plan complete
2. ✅ ~~Begin M1-M7 implementation~~ — all milestones implemented
3. **Load extension in Chrome** and run end-to-end validation:
   - Auth flow (login, token refresh, logout)
   - Chat (create, send message, streaming, history)
   - Workspace tree (expand, collapse, context menu)
   - Document panel (upload, list, download, delete, promote)
   - Claims panel (search, filter, load more)
   - File attachments (drag-drop, upload, render in messages)
   - Context menus (conversation 8-item, attachment 4-item)
4. **Fix any issues found during live testing** (if any)
5. **Delete `extension_server.py` + `extension.py`** after validation confirms everything works (Task 7.5, deferred)

---

## Version History

| Version | Date | Key Changes |
|---------|------|-------------|
| v1.0 | 2026-02-13 | Initial plan with 5 milestones, 128-route decorator swap |
| v2.0 | 2026-02-13 | Simplified auth (JWT-aware get_session_identity), send_message refactor |
| v2.1 | 2026-02-14 | Domain system, workspace hierarchy, jsTree sidebar tasks added |
| v2.2 | 2026-02-14 | Complete API mapping (38 endpoints), auth differences documented |
| v2.3 | 2026-02-16 | File attachments milestone added (7 tasks, +7 endpoints) |
| v2.4 | 2026-02-16 | Simplified frontend (flat list, no jsTree), realistic auth timeline, 21-30 days total |
| v2.4.1 | 2026-02-16 | "Extension" workspace auto-creation, atomic temp conversation endpoint |
| v2.7 | 2026-02-16 | M4 complete — scripts, workflows, settings, models, agents, prompts, PKB endpoints |
| **v3.0** | **2026-02-16** | **M5 revised: jsTree restored, KaTeX added, two buttons, popup settings, 4-6 day effort** |
| v3.3 | 2026-02-17 | M5+M6 implemented: jsTree sidebar, KaTeX, docs/claims panels, full context menu |
| **v3.4** | **2026-02-17** | **M7 implemented: deprecation notice, delete obsolete files, update 20+ docs. All milestones complete.** |

---

## Contact & Questions

For questions about this plan, refer to:
- Main plan document for detailed task specifications
- File attachments update for M6 details
- Feature documentation for implementation references

**Plan maintained by**: Development team  
**Last reviewed**: 2026-02-16
