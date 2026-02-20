# Milestone 2: Page Context Support - Implementation Analysis

> **NOTE**: `extension_server.py` referenced in this document has been deprecated. The Chrome extension now uses `server.py` (port 5000). See `documentation/features/extension/` for current architecture.

**Date**: February 16, 2026  
**Status**: Analysis Complete - Ready for Implementation Planning  
**Milestone 1 Status**: ✅ COMPLETE (Session-based auth implemented and tested)

---

## Executive Summary

### What We Discovered

After deep-diving into the extension UI and backend implementation, **Milestone 2 is mostly complete in the extension UI**. The extension already has sophisticated page context capture, screenshots, OCR, and multi-tab extraction. However, these features currently use **legacy `extension_server.py` endpoints** that need to be migrated to the main backend.

**Key Finding**: M2 is NOT about building new UI features - it's about **backend integration** to make existing extension features work with main backend endpoints.

### Current State

| Feature | Extension UI | Backend Support | Status |
|---------|-------------|----------------|--------|
| Page content extraction | ✅ Implemented | ❌ Uses `/ext/chat/{id}` (legacy) | Needs migration |
| Viewport screenshots | ✅ Implemented | ❌ Legacy endpoint | Needs migration |
| Scrolling screenshots + OCR | ✅ Implemented | ⚠️ `/ext/ocr` exists but in legacy | Needs migration |
| Multi-tab extraction | ✅ Implemented | ❌ Legacy endpoint | Needs migration |
| Voice input | ❌ Placeholder only | ❌ Not implemented | New feature (optional) |
| Refresh/append page context | ✅ Implemented | ❌ Legacy endpoint | Needs migration |

---

## Detailed Findings

### 1. Extension UI Button Implementation (7 Buttons)

#### ✅ Fully Implemented (6/7 buttons)

**attach-page-btn** (Attach Page Content)
- **Handler**: `attachPageContent()`
- **Extraction**: `extractPageContent()` via service worker
- **Method**: DOM text extraction with site-specific heuristics (YouTube, GitHub, Wikipedia, etc.)
- **Data format**: `{url, title, content}` (text only)
- **Backend call**: `POST /ext/chat/{conversationId}` with `page_context` field
- **Status**: ✅ Fully functional, needs backend migration

**refresh-page-btn** (Refresh Page Content)
- **Handler**: `refreshPageContent()`
- **Behavior**: Re-extracts page content, replaces existing context
- **Use case**: Single-page apps (SPAs) where content changes without URL change
- **Data format**: Same as attach-page
- **Backend call**: Same as attach-page
- **Status**: ✅ Fully functional, needs backend migration

**append-page-btn** (Append Page Content)
- **Handler**: `appendPageContent()`
- **Behavior**: Merges new content with existing, adds `## Source X:` headers
- **Use case**: Combining content from multiple sources/states
- **Data format**: Combined content with source markers
- **Backend call**: Same as attach-page
- **Status**: ✅ Fully functional, needs backend migration

**attach-screenshot-btn** (Viewport Screenshot)
- **Handler**: `attachScreenshotFromPage()`
- **Extraction**: `chrome.tabs.captureVisibleTab(null, {format:'png'})`
- **Data format**: Base64 PNG data URL
- **Storage**: `pageContext.screenshot` field
- **Backend call**: `POST /ext/chat/{conversationId}` with screenshot in `page_context`
- **LLM handling**: Vision API for image analysis
- **Status**: ✅ Fully functional, needs backend migration

**attach-scrollshot-btn** (Full-Page Scrolling Screenshot)
- **Handler**: `attachScrollingScreenshotFromPage()`
- **Extraction**: `captureAndOcrPipelined()` - scrolls page, captures frames, OCR per frame
- **Method**: 
  1. Detect scroll target (window or inner element like Google Docs iframe)
  2. Scroll step-by-step with overlap
  3. Capture each frame: `chrome.tabs.captureVisibleTab()`
  4. Fire OCR per screenshot during capture (40-60% faster than batch)
  5. Combine OCR text from all frames
- **Data format**: Paginated text with page numbers, stored as `pageContext.content` with `isOcr: true`
- **Backend call**: `POST /ext/ocr` with base64 PNG array → Returns combined text
- **Special features**:
  - Inner scroll detection for web apps (Google Docs, Word Online, Notion, Confluence, Slack, Overleaf)
  - Pipelined OCR (parallel processing during capture)
  - Content viewer with page navigation
- **Status**: ✅ Fully functional, `/ext/ocr` endpoint exists in `extension_server.py` **needs migration to main backend**

**multi-tab-btn** (Multi-Tab Extraction)
- **Handler**: `showTabModal()` → `handleTabSelection()`
- **Extraction**: Parallel DOM or OCR extraction from selected tabs
- **Capture modes**: 4 modes (Auto, DOM, OCR, Full OCR) per tab
- **Data format**: Combined content with tab separators, stored as `pageContext` with `isMultiTab: true`, `tabCount: N`
- **Special features**:
  - Auto-detection of document apps via URL patterns (16 patterns)
  - Deferred OCR with immediate tab restoration
  - On-page toast overlays during capture
  - Content script pre-injection for reliability
- **Backend call**: Same as attach-page but with multi-source content
- **Status**: ✅ Fully functional, needs backend migration

#### ❌ Not Implemented (1/7 buttons)

**voice-btn** (Voice Input)
- **Handler**: Placeholder alert "Voice input coming soon!"
- **Implementation**: None
- **Status**: ❌ Feature not implemented
- **Recommendation**: Consider as Phase 3 enhancement (out of scope for M2)

---

### 2. Backend Endpoint Status

#### Legacy Extension Server (`extension_server.py`)

**Currently Active Endpoints Used by Extension**:

| Endpoint | Purpose | Status | Migration Needed |
|----------|---------|--------|------------------|
| `POST /ext/chat/{id}` | Send message with streaming response | ❌ Legacy | YES - Replace with main backend `/send_message` |
| `POST /ext/ocr` | OCR processing for scrolling screenshots | ⚠️ Legacy | YES - Migrate to main backend |
| `GET /ext/conversations` | List conversations | ❌ Legacy | YES - M3 task |
| `POST /ext/conversations` | Create conversation | ❌ Legacy | YES - M3 task |
| `PUT /ext/settings` | Save settings | ❌ Legacy | YES - M4 task |

**Key Discovery**: The `/ext/ocr` endpoint (lines 2250-2306 in `extension_server.py`) is fully implemented with:
- Vision LLM processing (google/gemini-2.5-flash-lite)
- Parallel OCR with ThreadPoolExecutor
- Base64 PNG input
- Paginated text output

#### Main Backend (`server.py` + `endpoints/`)

**Image/PDF Handling in Conversations**:

| Endpoint | Purpose | Format | Status |
|----------|---------|--------|--------|
| `POST /upload_doc_to_conversation/{id}` | Upload PDF/image to conversation | Multipart or URL | ✅ Exists |
| `POST /global_docs/upload` | Upload global document | Multipart or URL | ✅ Exists |
| `POST /send_message/{id}` | Send message in conversation | JSON with text, images, etc | ✅ Exists |

**Image Handling in Main Backend**:
- Images passed to vision LLMs via `ImageDocIndex`
- File storage: `storage/pdfs/` + DocIndex metadata
- Multimodal support: `images=[d.llm_image_source]` in `Conversation.reply()`
- No explicit OCR - vision models handle image text recognition

**Key Gap**: Main backend has **no dedicated `/ext/ocr` endpoint** for processing screenshot arrays. Extension's OCR needs require this endpoint to be migrated.

---

### 3. Data Flow Analysis

#### Current Extension Flow (Legacy)

```
User clicks button
  ↓
Extension UI captures data (DOM text / screenshot / OCR)
  ↓
Extension calls legacy endpoint:
  - Page content → POST /ext/chat/{id} with page_context
  - Screenshots → POST /ext/chat/{id} with page_context.screenshot
  - Scrolling screenshots → POST /ext/ocr → POST /ext/chat/{id} with OCR text
  ↓
extension_server.py processes
  ↓
ExtensionDB stores message
  ↓
LLM response streamed back
```

#### Target Flow (After M2 Migration)

```
User clicks button
  ↓
Extension UI captures data (same as before)
  ↓
Extension calls main backend:
  - Page content → POST /send_message/{id} with page_context in query
  - Screenshots → POST /send_message/{id} with images array
  - Scrolling screenshots → POST /ext/ocr (migrated) → POST /send_message/{id}
  ↓
Main backend endpoints (endpoints/conversations.py, Conversation.py)
  ↓
Filesystem conversation storage
  ↓
LLM response streamed back (same format as web UI)
```

---

## Revised Milestone 2 Scope

### Original Plan (from plan doc lines 691-828)

**4 Tasks**:
1. ✅ Task 2.1: Add `page_context` to send_message payload processing
2. ✅ Task 2.2: Inject page context into Conversation.reply() prompt
3. ✅ Task 2.3: Support extension-specific checkboxes defaults
4. ✅ Task 2.4: Support extension images in chat payload

**Focus**: Enable main backend to accept and process page context and images from extension.

### What's Actually Needed (Based on Analysis)

**Backend Tasks**:

| Task | What | Files | Complexity |
|------|------|-------|------------|
| **2.1** | Migrate `/ext/ocr` endpoint to main backend | `endpoints/ext_page_context.py` (NEW) | Medium - Vision LLM integration |
| **2.2** | Add `page_context` support to `/send_message` | `endpoints/conversations.py`, `Conversation.py` | Low - Just pass through to reply() |
| **2.3** | Inject page context into LLM prompts | `Conversation.py` - `reply()` method | Low - Format and inject text |
| **2.4** | Support extension-specific defaults | `endpoints/conversations.py` | Low - Default checkboxes |
| **2.5** | Verify multimodal image handling | `Conversation.py` | Very Low - Already exists, just verify |

**Extension Tasks**:

| Task | What | Files | Complexity |
|------|------|-------|------------|
| **2.6** | Update screenshot capture to use new flow | `extension/sidepanel/sidepanel.js`, `extension/shared/api.js` | Low - Change endpoint URLs |
| **2.7** | Update OCR calls to new endpoint | `extension/sidepanel/sidepanel.js`, `extension/shared/api.js` | Low - Change endpoint URL |
| **2.8** | Update page context payload format | `extension/shared/api.js` | Low - Match main backend format |
| **2.9** | Test all 6 button flows end-to-end | All extension files | Medium - Integration testing |

**Optional (Out of Scope for M2)**:
- Voice input implementation (Phase 3 feature)

---

## Implementation Strategy

### Phase 1: Backend Preparation (M2 Tasks 2.1-2.5) - 1-2 days

**Priority Order**:
1. **Task 2.1**: Migrate `/ext/ocr` endpoint (CRITICAL - needed for scrolling screenshots)
2. **Task 2.2**: Add `page_context` to `/send_message` (CRITICAL - needed for all page capture)
3. **Task 2.3**: Inject page context into prompts (CRITICAL - makes page context useful)
4. **Task 2.4**: Extension defaults (NICE TO HAVE - prevents errors)
5. **Task 2.5**: Verify images (VERIFICATION ONLY - already works)

**Why this order**:
- OCR is the most complex feature that doesn't exist in main backend
- Page context support is needed before testing any button flows
- Defaults prevent errors during testing
- Image verification is last because it likely already works

### Phase 2: Extension Integration (M2 Tasks 2.6-2.8) - 1 day

**After backend is ready**:
1. Update API client to call new endpoints
2. Update payload formats to match main backend
3. Handle response format differences

### Phase 3: Testing (M2 Task 2.9) - 1 day

**Test each button**:
1. attach-page-btn on various site types (news, docs, social, e-commerce)
2. refresh-page-btn on SPA sites (Twitter, Gmail)
3. append-page-btn with multiple sources
4. attach-screenshot-btn with vision LLM
5. attach-scrollshot-btn on long pages and document apps
6. multi-tab-btn with 3+ tabs

**Total M2 Effort**: 3-4 days (revised from 2-3 days due to OCR migration complexity)

---

## Technical Specifications

### 1. OCR Endpoint Migration

**Source**: `extension_server.py:2250-2306`  
**Target**: `endpoints/ext_page_context.py` (NEW FILE)  
**Blueprint**: `ext_page_bp`

**Endpoint Spec**:
```python
@ext_page_bp.route("/ext/ocr", methods=["POST"])
@limiter.limit("50 per minute")  # Lower limit for expensive OCR
@auth_required
def ocr_screenshots():
    """
    Perform OCR on screenshot array using vision-capable LLM.
    
    Request body:
    {
        "images": ["data:image/png;base64,...", ...],  # Max 30 images
        "url": "https://...",                           # Optional
        "title": "Page title",                          # Optional
        "model": "google/gemini-2.5-flash-lite"         # Optional
    }
    
    Returns:
    {
        "text": "combined OCR text from all pages",
        "pages": [
            {"index": 0, "text": "page 1 text..."},
            {"index": 1, "text": "page 2 text..."},
            ...
        ]
    }
    """
    # Implementation
```

**Key Components**:
1. Vision LLM call per image (parallel with ThreadPoolExecutor)
2. Max 30 images enforced (matching extension_server.py)
3. Page-by-page OCR results
4. Combined text output with page separators
5. Error handling for vision API failures

**Dependencies**:
- `call_llm.py` for vision model calls
- `keyParser()` for API key management
- ThreadPoolExecutor for parallel processing

### 2. Page Context Support in `/send_message`

**File**: `endpoints/conversations.py` - `send_message()` function

**Changes**:
```python
# After query = request.json (around line 1354)
# Extract optional page_context field
page_context = query.get("page_context", None)

# Validate page_context structure if present
if page_context:
    # Basic validation
    if not isinstance(page_context, dict):
        return json_error("page_context must be an object", 400)
    
    # Validate required fields
    # (url and title are recommended but optional)
    
    # Pass through to Conversation.reply() via query dict
    # (already in query, no action needed)
```

**Page Context Object Shape**:
```json
{
    "url": "https://example.com",
    "title": "Example Page",
    "content": "extracted text content...",
    "screenshot": "data:image/png;base64,...",  // Optional viewport screenshot
    "isScreenshot": false,                       // True if screenshot-only (no text)
    "isMultiTab": false,                         // True if multi-tab capture
    "tabCount": 1,                               // Number of tabs captured
    "isOcr": false,                              // True if content from OCR
    "sources": [                                 // Optional multi-source details
        {"tabId": 123, "url": "...", "title": "..."}
    ],
    "mergeType": "replace",                      // "replace" or "append"
    "lastRefreshed": "2026-02-16T12:00:00Z"     // ISO timestamp
}
```

### 3. Prompt Injection in `Conversation.reply()`

**File**: `Conversation.py` - `reply()` method (around line 5288)

**Implementation**:
```python
# After prior_context retrieval, before prompt construction
page_context = query.get("page_context", None) if isinstance(query, dict) else None

if page_context and isinstance(page_context, dict):
    # Build page context text for injection
    page_text = _build_page_context_text(page_context)
    
    # Inject into permanent_instructions or as separate context
    if page_text:
        permanent_instructions += "\n\n" + page_text


def _build_page_context_text(page_context: dict) -> str:
    """
    Build formatted page context text for LLM injection.
    
    Handles 3 cases:
    1. Screenshot-only (isScreenshot=true): Describe screenshot presence
    2. Multi-tab (isMultiTab=true): Format all tab contents with separators
    3. Single page: Format URL, title, content
    
    Content size limits:
    - Single page: 64K chars
    - Multi-tab: 128K chars
    - Truncate with "[Content truncated...]" if exceeded
    """
    url = page_context.get("url", "")
    title = page_context.get("title", "")
    content = page_context.get("content", "")
    is_screenshot = page_context.get("isScreenshot", False)
    is_multi_tab = page_context.get("isMultiTab", False)
    tab_count = page_context.get("tabCount", 1)
    
    # Case 1: Screenshot-only
    if is_screenshot:
        # Note: Screenshot itself handled via images array, not page_context
        return f"[Browser Page Context - Screenshot]\nURL: {url}\nTitle: {title}\n\n(Visual content captured as screenshot)\n[End Browser Page Context]"
    
    # Case 2: Multi-tab
    if is_multi_tab:
        # Truncate combined content at 128K
        if len(content) > 128000:
            content = content[:128000] + "\n\n[Content truncated...]"
        return f"[Browser Page Context - {tab_count} tabs]\n{content}\n[End Browser Page Context]"
    
    # Case 3: Single page
    # Truncate at 64K
    if len(content) > 64000:
        content = content[:64000] + "\n\n[Content truncated...]"
    
    return f"""[Browser Page Context]
URL: {url}
Title: {title}

Page Content:
{content}

Use the above page content to ground your response.
[End Browser Page Context]"""
```

### 4. Extension Defaults

**File**: `endpoints/conversations.py` - `send_message()`

**Implementation**:
```python
from endpoints.session_utils import is_jwt_request

# After query extraction, before processing
if query.get("source") == "extension" or is_jwt_request():
    # Set extension-friendly defaults
    checkboxes = query.setdefault("checkboxes", {})
    checkboxes.setdefault("persist_or_not", True)
    checkboxes.setdefault("provide_detailed_answers", 2)
    checkboxes.setdefault("use_pkb", True)
    checkboxes.setdefault("enable_previous_messages", "10")
    checkboxes.setdefault("perform_web_search", False)
    checkboxes.setdefault("googleScholar", False)
    checkboxes.setdefault("ppt_answer", False)
    checkboxes.setdefault("preamble_options", [])
    
    # Set search/links defaults
    query.setdefault("search", [])
    query.setdefault("links", [])
```

---

## Risk Assessment

### High Risk Items

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| OCR endpoint migration breaks existing extension | High | Medium | Thorough testing, keep legacy endpoint temporarily |
| Vision LLM API differences between extension_server and main backend | High | Medium | Review call_llm.py vision support, test with multiple models |
| Page context truncation loses critical info | Medium | Medium | Smart truncation (keep headers, first/last N chars) |
| Extension payload format incompatibility | Medium | Low | Define clear schema, validate at endpoint |

### Medium Risk Items

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Performance degradation with large page content | Medium | Medium | Monitor response times, optimize if needed |
| Streaming response format differences | Medium | Low | Test streaming with page context |
| Multimodal image handling already works differently | Low | Medium | Verify with actual test cases |

---

## Success Criteria

### M2 Complete When:

**Backend**:
- ✅ `/ext/ocr` endpoint exists in main backend and processes screenshot arrays
- ✅ `/send_message` accepts `page_context` in payload without errors
- ✅ Page context is injected into LLM prompts correctly
- ✅ Extension defaults prevent KeyError on minimal payloads
- ✅ Images array works with vision models
- ✅ All endpoints pass smoke tests

**Extension**:
- ✅ attach-page-btn works end-to-end with main backend
- ✅ refresh-page-btn replaces page context correctly
- ✅ append-page-btn merges multiple sources
- ✅ attach-screenshot-btn sends viewport screenshot to LLM
- ✅ attach-scrollshot-btn captures + OCRs full pages
- ✅ multi-tab-btn captures content from multiple tabs
- ✅ All button states (active/disabled) work correctly

**Integration**:
- ✅ Extension can send messages with page context to main backend
- ✅ LLM responses include page context grounding
- ✅ Screenshot-based Q&A works (vision LLM analyzes images)
- ✅ OCR text extraction works for long documents
- ✅ Multi-tab capture works for 3+ tabs
- ✅ Error handling works (network errors, API failures, etc)

---

## Next Steps

### Immediate Actions

1. **Review this analysis** with stakeholders
2. **Clarify scope questions**:
   - Include voice input in M2, or defer to Phase 3?
   - Keep legacy `/ext/ocr` endpoint during transition, or hard cutover?
   - Test with production LLM APIs, or mock responses OK for M2?
3. **Create detailed M2 todo list** based on revised scope
4. **Start with Task 2.1** (OCR migration) as critical path

### Decision Points

**Question 1**: Should voice input be part of M2?
- **Recommendation**: NO - defer to Phase 3 (out of scope for backend unification)
- **Rationale**: Voice input requires new UI, new backend endpoints, and browser API integration. Not related to page context support.

**Question 2**: Should we keep legacy `/ext/ocr` during transition?
- **Recommendation**: YES - keep for 1-2 weeks, deprecate after M3 complete
- **Rationale**: Allows rollback if migration has issues, maintains extension functionality during M2/M3 work.

**Question 3**: Should we migrate `/ext/ocr` exactly as-is, or enhance it?
- **Recommendation**: Migrate as-is for M2, enhance later if needed
- **Rationale**: Existing OCR works well (pipelined, parallel, good quality). Enhancement can wait for M4 (extension features).

---

## Open Questions for User

1. **Voice input**: Include in M2, or defer to Phase 3?
2. **Legacy endpoints**: Keep `/ext/ocr` in extension_server.py during transition, or remove immediately?
3. **Testing scope**: Test with production LLM APIs (requires API keys), or mock responses OK?
4. **Error handling**: How should extension handle main backend errors differently from legacy server?
5. **Rate limiting**: Should OCR have stricter rate limits (expensive operation)?

---

## Appendices

### A. Extension Button Handler Reference

| Button ID | Handler Function | Line in sidepanel.js | Extraction Method | Backend Endpoint (Legacy) |
|-----------|-----------------|---------------------|-------------------|---------------------------|
| attach-page-btn | attachPageContent() | 425, 2522-2575 | DOM extraction via service worker | POST /ext/chat/{id} |
| refresh-page-btn | refreshPageContent() | 426, 2577-2633 | Same as attach-page | POST /ext/chat/{id} |
| append-page-btn | appendPageContent() | 427, 2635-2701 | Same as attach-page | POST /ext/chat/{id} |
| attach-screenshot-btn | attachScreenshotFromPage() | 428, 2703-2793 | chrome.tabs.captureVisibleTab | POST /ext/chat/{id} |
| attach-scrollshot-btn | attachScrollingScreenshotFromPage() | 429, 2795-2854 | Scroll + capture + OCR | POST /ext/ocr, then POST /ext/chat/{id} |
| multi-tab-btn | showTabModal() → handleTabSelection() | 434, 2900-3461 | Parallel tab extraction | POST /ext/chat/{id} |
| voice-btn | alert("Voice input coming soon!") | 443 | None | None |

### B. Files to Modify

**Backend (New Files)**:
- `endpoints/ext_page_context.py` — NEW, OCR endpoint + page context helpers

**Backend (Modifications)**:
- `endpoints/conversations.py` — send_message() modifications for page_context and defaults
- `Conversation.py` — reply() modifications for page context injection
- `endpoints/__init__.py` — Register ext_page_context blueprint

**Extension (Modifications)**:
- `extension/shared/api.js` — Update OCR endpoint URL, update page context payload format
- `extension/sidepanel/sidepanel.js` — Update backend calls to use new endpoints (minimal changes)

**Documentation (Updates)**:
- `documentation/planning/plans/extension_backend_unification.plan.md` — Update M2 section with OCR migration details
- `documentation/planning/plans/EXTENSION_UNIFICATION_STATUS.md` — Update M2 status, add OCR migration note

---

**Version**: 1.0  
**Author**: Analysis based on explore agent findings  
**Last Updated**: February 16, 2026
