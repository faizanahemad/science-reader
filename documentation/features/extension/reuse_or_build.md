# Reuse vs Build Analysis

## Overview

This document analyzes the existing `server.py`, `Conversation.py`, and `interface/*` codebase to identify what can be reused for the Chrome extension and what needs to be built new.

### ⚠️ Important Distinction: Python vs JavaScript

| Code Type | Reuse Strategy |
|-----------|----------------|
| **Python (server.py, Conversation.py, etc.)** | ✅ **DIRECT REUSE** - Same server runs for both web UI and extension. All Python code, APIs, and logic are directly callable. |
| **JavaScript (interface/*.js)** | ⚠️ **PATTERN ONLY** - UI code is separate. Patterns and logic can be studied and copied, but code must be **rewritten** for extension context. Cannot import or use directly. |

---

## Table of Contents

1. [Server-Side Components](#1-server-side-components) - **Direct Python Reuse**
2. [Conversation.py Analysis](#2-conversationpy-analysis) - **Direct Python Reuse**
3. [Interface JavaScript Analysis](#3-interface-javascript-analysis) - **Pattern Reference Only**
4. [Summary Tables](#4-summary-tables)
5. [Reuse Strategy](#5-reuse-strategy)
6. [What to Build New](#6-what-to-build-new)

---

## 1. Server-Side Components (Python - DIRECT REUSE)

> **All Python code runs on the same server.** Extension calls these APIs over HTTPS.
> No code duplication needed - just call the existing endpoints.

### 1.1 Existing APIs - Direct Reuse (No Modification)

These endpoints can be called directly from the extension:

| Endpoint | Purpose | Notes |
|----------|---------|-------|
| `/get_prompts` | List all prompts | ✅ Direct use for prompt selection dropdown |
| `/get_prompt_by_name/<name>` | Get prompt content | ✅ Fetch selected prompt |
| `/create_prompt` | Create new prompt | ✅ If extension supports prompt creation |
| `/update_prompt` | Update prompt | ✅ If extension supports prompt editing |
| `/pkb/claims` GET | List memories | ✅ For memory selection in extension |
| `/pkb/claims` POST | Add memory | ✅ For adding memories from extension |
| `/pkb/claims/<id>` PUT | Edit memory | ✅ For editing memories |
| `/pkb/claims/<id>` DELETE | Delete memory | ✅ For deleting memories |
| `/pkb/search` | Semantic search memories | ✅ For finding relevant memories |
| `/pkb/relevant_context` | Get relevant memories for query | ✅ Auto-attach memories |
| `/pkb/pinned` | Get pinned memories | ✅ For pinned memory list |
| `/transcribe` | Audio transcription (STT) | ✅ For voice input in extension |
| `/get_user_detail` | Get user details | ✅ For user context |
| `/get_user_preference` | Get user preferences | ✅ For settings |
| `/modify_user_detail` | Update user details | ✅ For editing |
| `/modify_user_preference` | Update preferences | ✅ For settings |
| `/temporary_llm_action` | Ephemeral LLM action | ⚠️ Can be adapted for quick actions |

### 1.2 Existing APIs - Reuse with Adaptation

These endpoints exist but need wrapper or adaptation for extension:

| Endpoint | Current Use | Extension Adaptation Needed |
|----------|-------------|---------------------------|
| `/login` | Session-based | Need token-based auth variant `/ext/auth/login` |
| `/logout` | Session-based | Need token-based variant `/ext/auth/logout` |
| `/send_message/<id>` | Web UI conversations | Create `/ext/chat/<id>` with page context support |
| `/proxy` | Fetch external URLs | May need CORS handling for extension |

### 1.3 Existing APIs - NOT Used by Extension

| Endpoint | Reason |
|----------|--------|
| `/create_workspace/*` | Extension has no workspaces |
| `/list_workspaces/*` | Extension has no workspaces |
| `/move_conversation_to_workspace/*` | Extension has no workspaces |
| `/upload_doc_to_conversation/*` | Extension reads pages directly |
| `/download_doc_from_conversation/*` | Not needed |
| `/tts/*` | Not in Phase 1 |
| `/get_coding_hint/*` | Interview prep feature not needed |
| `/get_full_solution/*` | Interview prep feature not needed |
| `/clear_doubt/*` | Extension uses temporary LLM |
| `/get_doubt/*` | Not needed |
| `/get_doubts/*` | Not needed |
| `/shared_chat/*` | Not in Phase 1 |
| `/clone_conversation/*` | Not needed initially |
| `/set_memory_pad/*` | Different approach for extension |

### 1.4 Server Database Tables - Reuse

| Table | Reuse | Notes |
|-------|-------|-------|
| `UserDetails` | ✅ Shared | Same users for web and extension |
| `UserToConversationId` | ❌ New table | Extension needs separate: `ExtensionConversations` |
| `WorkspaceMetadata` | ❌ Not used | Extension has no workspaces |
| `ConversationIdToWorkspaceId` | ❌ Not used | Extension has no workspaces |
| `DoubtsClearing` | ❌ Not used | Extension uses temp LLM |
| PKB tables (in `pkb.sqlite`) | ✅ Shared | Same memories for web and extension |
| Prompt storage | ✅ Shared | Same prompts for web and extension |

### 1.5 Server Helper Functions - Reuse

From `server.py`:

| Function | Purpose | Reuse |
|----------|---------|-------|
| `keyParser(session)` | Extract API keys from session | ⚠️ Need token-based variant |
| `check_login(session)` | Verify user logged in | ⚠️ Need token-based variant |
| `getUserFromUserDetailsTable(email)` | Get user details | ✅ Direct use |
| `login_required` decorator | Protect endpoints | ⚠️ Need token-based decorator |
| `limiter.limit()` | Rate limiting | ✅ Use for extension endpoints |
| `get_pkb_api_for_user(email)` | Get PKB API instance | ✅ Direct use |
| `serialize_claim(claim)` | Serialize PKB claim | ✅ Direct use |

---

## 2. Conversation.py Analysis (Python - DIRECT REUSE)

> **Same Python module runs on the server.** Extension-specific `ExtensionConversation` class 
> will be added to `extension.py` and can import/reuse methods from `Conversation.py`.

### 2.1 Conversation Class Methods - Direct Reuse

These methods are directly available since the same server runs:

| Method | Purpose | Reuse Strategy |
|--------|---------|----------------|
| `__init__` | Create conversation | ⚠️ Create `ExtensionConversation` variant |
| `__call__` (reply) | Process query, stream response | ✅ Core LLM logic reusable |
| `get_field` / `set_field` | Storage access | ⚠️ Adapt for extension storage |
| `save_local` / `load_local` | Persistence | ⚠️ Adapt for extension storage |
| `_get_pkb_context` | Retrieve relevant memories | ✅ Direct use |
| `retrieve_prior_context` | Get conversation history | ✅ Core logic reusable |
| `persist_current_turn` | Save messages | ⚠️ Adapt for extension (optional persist) |
| `get_message_ids` | Generate message IDs | ✅ Direct use |
| `delete_message` | Remove message | ✅ Direct use |
| `edit_message` | Edit message | ✅ Direct use |
| `make_stateless` / `make_stateful` | Toggle persistence | ✅ Core for temporary conversations |
| `set_api_keys` / `get_api_keys` | API key management | ✅ Direct use |

### 2.2 Conversation Class Methods - NOT Needed

| Method | Reason |
|--------|--------|
| `add_uploaded_document` | Extension reads pages directly |
| `delete_uploaded_document` | No document uploads |
| `get_uploaded_documents` | No document uploads |
| `convert_to_tts*` | Not in Phase 1 |
| `convert_to_podcast*` | Not in Phase 1 |
| `clone_conversation` | Not needed |
| `get_uploaded_documents_for_query` | No document uploads |
| `clear_doubt` | Uses temporary LLM instead |

### 2.3 Conversation Processing Logic - Reuse

The core processing flow in `reply()` method contains reusable logic:

```python
# Reusable components from reply():
1. Query parsing and validation
2. Model selection logic
3. Prompt composition with context
4. PKB memory retrieval (_get_pkb_context)
5. Conversation history retrieval
6. LLM call with streaming
7. Response parsing and formatting
```

**Adaptation needed:**
- Add page content as context input
- Add multi-tab content aggregation
- Handle extension-specific settings (history_length)
- Optional persistence (temporary by default)

### 2.4 New Conversation Features for Extension

| Feature | Description | Implementation |
|---------|-------------|----------------|
| Page context | Include current page content | Add `page_content`, `page_url` to query |
| Multi-tab | Aggregate multiple tabs | Add `multi_tab_content` array to query |
| History length | Configurable context window | Add `history_length` parameter |
| Temporary default | Don't persist by default | Invert stateless logic |
| Summarization | Compress old messages | Add conversation summary endpoint |

---

## 3. Interface JavaScript Analysis (PATTERN REFERENCE ONLY - MUST REWRITE)

> ⚠️ **JavaScript code CANNOT be directly imported or used.**
> The extension UI is a completely separate codebase. 
> Study these patterns and rewrite equivalent functionality in the extension.

### 3.1 JavaScript Managers - Patterns to Study (Not Import)

From `interface/*.js` - **study the logic, rewrite for extension**:

| Manager | File | Reuse for Extension |
|---------|------|---------------------|
| `ConversationManager` | common-chat.js | ⚠️ Pattern reusable, simpler version |
| `ChatManager` | common-chat.js | ⚠️ Pattern reusable, adapt for extension |
| `WorkspaceManager` | workspace-manager.js | ❌ Not needed (no workspaces) |
| `PKBManager` | pkb-manager.js | ⚠️ Partial reuse for memory selection |
| `DoubtManager` | doubt-manager.js | ❌ Not needed (use temp LLM) |
| `TempLLMManager` | temp-llm-manager.js | ✅ Pattern reusable for quick actions |
| `ContextMenuManager` | context-menu-manager.js | ⚠️ Logic reusable for right-click menu |
| `PromptManager` | prompt-manager.js | ❌ Not needed (manage in web UI) |

### 3.2 UI Components - Patterns to Study (REWRITE, NOT COPY)

#### From `common-chat.js` (study and rewrite):

| Component | What to Study | Rewrite Notes |
|-----------|---------------|---------------|
| Streaming response handling | `renderStreamingResponse()` logic | Use fetch + ReadableStream |
| Message rendering | `ChatManager.renderMessages()` structure | Simpler card layout |
| Markdown rendering | Uses marked.js | Include marked.js fresh |
| Code highlighting | Uses highlight.js | Include highlight.js fresh |
| Copy code button | Copy to clipboard logic | Standard clipboard API |

#### From `common.js` (study and rewrite):

| Utility | What to Study | Rewrite Notes |
|---------|---------------|---------------|
| `getMimeType()` | MIME type mapping | Copy the mapping object |
| `addNewlineToTextbox()` | Textarea handling | Similar vanilla JS |
| `setMaxHeightForTextbox()` | Auto-resize logic | Similar CSS approach |
| `responseWaitAndSuccessChecker()` | Error handling pattern | Adapt for extension |

#### From `workspace-manager.js` (mostly skip):

| Component | Use |
|-----------|-----|
| Drag-drop logic | ❌ Not needed |
| Workspace rendering | ❌ Not needed |
| Context menus for workspaces | ❌ Not needed |
| Conversation list rendering | 📖 Study for simpler flat list |

#### From `pkb-manager.js` (study API call patterns):

| Component | Use |
|-----------|-----|
| API call patterns (`listClaims`, `searchClaims`) | 📖 Study fetch patterns |
| Claim selection UI | 📖 Study for simpler dropdown |
| Memory attachment logic | 📖 Study data flow |
| Proposal review UI | ❌ Not needed (use web UI) |

#### From `temp-llm-manager.js` (study for quick actions):

| Component | Use |
|-----------|-----|
| Quick action execution | 📖 Study streaming pattern |
| Modal UI structure | 📖 Study for extension modal |
| History tracking (in-memory) | 📖 Study state management |
| Action types (explain, critique, etc.) | 📖 Copy action definitions |

#### From `context-menu-manager.js` (study for right-click):

| Component | Use |
|-----------|-----|
| Context menu structure | 📖 Adapt for Chrome context menu API |
| Selection detection | 📖 Similar for content scripts |
| Action triggering | 📖 Study event handling |
| Modal positioning | 📖 Study positioning logic |

### 3.3 CSS/Styling - Patterns to Study (WRITE NEW CSS)

From `style.css` and `workspace-styles.css` - **study for inspiration, write new**:

| Style Component | Study For | Extension Approach |
|-----------------|-----------|-------------------|
| Message card styling | Layout patterns | Simpler cards, new CSS |
| Code block styling | Theme colors | Copy color values only |
| Input field styling | Dimensions | Adapt for sidepanel width |
| Modal styling | Overlay pattern | Simpler overlay, new CSS |
| Conversation list styling | List structure | Flat list, new CSS |
| Workspace accordion | ❌ Skip | Not needed |

### 3.4 Third-Party Libraries - Fresh Includes (Not Imports)

| Library | Web UI | Extension | Notes |
|---------|--------|-----------|-------|
| jQuery | Used | ❌ NO | Use vanilla JS |
| Bootstrap | Used | ❌ NO | Write lightweight CSS |
| marked.js | Used | ✅ Include fresh | Download and include in extension |
| highlight.js | Used | ✅ Include fresh | Download and include in extension |
| KaTeX | Used | ⚠️ Maybe Phase 2 | Adds bundle size |
| Mermaid.js | Used | ❌ NO | Not in Phase 1 |
| CodeMirror | Used | ❌ NO | Not needed |
| jQuery UI | Used | ❌ NO | Not needed |

---

## 4. Summary Tables

### 4.1 Backend Reuse Summary (Python - DIRECT USE)

| Category | Direct Reuse | New to Add | Notes |
|----------|--------------|------------|-------|
| **APIs** | 15 endpoints | 12 new `/ext/*` | Same server, just add endpoints |
| **DB Tables** | 2 shared | 4 new | Add extension tables to same DB |
| **Helper Functions** | 8 functions | 3 new | Import and use directly |
| **Conversation Methods** | 12 methods | 5 new | Inherit or call from ExtensionConversation |
| **Modules** | call_llm, prompts, PKB | extension.py | Full module reuse |

### 4.2 Frontend Summary (JavaScript - ALL NEW, PATTERN REFERENCE ONLY)

| Category | Pattern Source | Build New | Notes |
|----------|----------------|-----------|-------|
| **Managers** | Study 3 from web UI | Write 4 new | Cannot import, rewrite in vanilla JS |
| **UI Components** | Study 5 patterns | Write 8 new | Extension-specific implementation |
| **Utilities** | Study 6 functions | Write 4 new | Copy logic, rewrite syntax |
| **Libraries** | - | Include 2 (marked, hljs) | Fresh includes in extension |
| **HTML/CSS** | Study structure | Write all new | Sidepanel, popup, modals |

### 4.3 What's Shared vs Separate

| Component | Server (Python) | Extension UI (JavaScript) |
|-----------|-----------------|---------------------------|
| **User accounts** | ✅ Same DB table | Calls server API |
| **Prompts** | ✅ Same storage | Calls server API |
| **Memories (PKB)** | ✅ Same DB | Calls server API |
| **API keys** | ✅ Server-side only | Never exposed to extension |
| **LLM calls** | ✅ Same call_llm.py | Calls server API |
| **Conversations** | ❌ Separate table | New UI code |
| **Custom scripts** | ❌ New table | New UI code |
| **Settings** | ❌ New table | New UI code |
| **UI Code** | N/A | ❌ All new (pattern reference only) |

---

## 5. Reuse Strategy

### 5.1 Server-Side Strategy (Python - DIRECT REUSE)

**Same server, same codebase.** Just add new files and endpoints.

1. **Create `extension.py`** (new file, imports from existing):
   ```python
   from Conversation import Conversation  # Direct import
   from call_llm import CallLLm           # Direct import
   from prompts import *                  # Direct import
   
   class ExtensionConversation(Conversation):
       # Inherit and extend, not rewrite
       pass
   ```

2. **Add extension endpoints to `server.py`**:
   - Prefix all with `/ext/`
   - Call existing helper functions directly
   - Use same PKB, prompts, user tables

3. **Directly import these modules**:
   - `call_llm.py` - Import `CallLLm` class
   - `prompts.py` - Import prompt templates
   - `truth_management_system/` - Import PKB classes
   - `prompt_lib/` - Import prompt manager
   - `Conversation.py` - Inherit `Conversation` class

### 5.2 Frontend Strategy (JavaScript - PATTERN ONLY, REWRITE ALL)

**Completely separate codebase.** Study patterns, write fresh code.

1. **Study patterns, rewrite from scratch**:
   - Read `common-chat.js` → understand streaming logic → rewrite
   - Read `temp-llm-manager.js` → understand quick actions → rewrite
   - Read `context-menu-manager.js` → understand selection → rewrite
   - **DO NOT copy-paste** - write new vanilla JS

2. **Fresh dependencies (include in extension)**:
   - `marked.js` for markdown (include fresh)
   - `highlight.js` for code (include fresh)
   - **NO jQuery, NO Bootstrap** - use vanilla JS + lightweight CSS

3. **Build simpler UI from scratch**:
   - Study web UI layout for inspiration
   - Build simpler sidepanel (no workspaces)
   - Build simpler overlays (no complex modals)
   - All HTML/CSS/JS is new code

---

## 6. What to Build New

### 6.1 Server-Side New Components (Python - Add to Existing Codebase)

| Component | Description | Reuses From | Effort |
|-----------|-------------|-------------|--------|
| `extension.py` | Extension-specific logic | Imports from Conversation.py, call_llm.py | Medium |
| `/ext/auth/*` endpoints | Token-based authentication | Adapts existing login logic | Medium |
| `/ext/conversations/*` endpoints | Extension conversation CRUD | Uses ExtensionConversation | Medium |
| `/ext/chat/*` endpoints | Chat with page context | Reuses LLM call logic | Medium |
| `/ext/scripts/*` endpoints | Custom script management | New functionality | Low |
| `/ext/settings` endpoints | Extension settings | Similar to user preferences | Low |
| `ExtensionConversation` class | Simplified conversation | **Inherits from Conversation** | Medium |
| Extension database tables | SQLite schema | Same DB file, new tables | Low |

### 6.2 Extension UI New Components (JavaScript - ALL NEW CODE)

| Component | Description | Pattern Source | Effort |
|-----------|-------------|----------------|--------|
| `manifest.json` | Extension configuration | None (new) | Low |
| Sidepanel HTML/CSS/JS | Main chat interface | Study interface.html | High |
| Popup HTML/CSS/JS | Quick settings/actions | Study interface.html | Medium |
| Content script: extractor.js | Page content extraction | New (no equivalent) | Medium |
| Content script: context_menu.js | Right-click handling | Study context-menu-manager.js | Medium |
| Content script: floating_button.js | Toggle sidepanel | New (no equivalent) | Low |
| Content script: modal.js | Response overlay | Study temp-llm-manager.js | Medium |
| Background: service-worker.js | Multi-tab coordination | New (no equivalent) | Medium |
| Shared: api.js | Server communication | Study common-chat.js fetch calls | Medium |
| Shared: auth.js | Token management | New (session-based doesn't apply) | Medium |
| Shared: storage.js | Chrome storage wrapper | New (localStorage doesn't apply) | Low |
| Custom script runner | Tampermonkey-like execution | New (no equivalent) | High |

### 6.3 Integration Components

| Component | Description | Effort |
|-----------|-------------|--------|
| Message passing system | Background ↔ Content ↔ Sidepanel | Medium |
| Auth flow | Login → Token → Storage → API calls | Medium |
| Page context pipeline | Extract → Send → Include in LLM | Medium |
| Multi-tab aggregation | Select tabs → Extract all → Merge | Medium |
| Streaming response handler | SSE-like in extension context | Medium |

---

## 7. Development Priority Order

### Phase 1: Foundation (Week 1-2)
1. Extension boilerplate (manifest, folder structure)
2. Token-based auth (`/ext/auth/*`)
3. Extension database tables
4. Basic sidepanel UI
5. Floating toggle button

### Phase 2: Core Chat (Week 3-4)
1. `ExtensionConversation` class
2. `/ext/chat/*` endpoints
3. Chat UI with streaming
4. Page content extraction
5. Basic conversation management

### Phase 3: Personalization (Week 5-6)
1. Model selection (reuse existing models list)
2. Prompt selection (reuse `/get_prompts`)
3. Memory selection (reuse `/pkb/*`)
4. Context menu quick actions
5. Settings UI

### Phase 4: Advanced (Week 7-8)
1. Multi-tab reading
2. Custom scripts storage
3. Custom script execution
4. STT integration
5. Polish and testing

---

## 8. Risk Analysis

### 8.1 Technical Risks

| Risk | Mitigation |
|------|------------|
| CORS issues with API calls | Use background worker for all API calls |
| Manifest V3 service worker limits | Use alarms and storage for persistence |
| Content script isolation | Proper message passing architecture |
| Large page content | Truncate/summarize before sending |
| Token expiry handling | Auto-refresh or prompt re-login |

### 8.2 Complexity Risks

| Risk | Mitigation |
|------|------------|
| Custom script security | Sandbox execution, permission checks |
| Multi-tab memory usage | Limit concurrent extractions |
| Streaming in extension context | Use fetch + ReadableStream |
| UI responsiveness | Keep logic in background worker |

---

*Document Version: 1.0*  
*Last Updated: December 2024*

