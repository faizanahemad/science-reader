---
name: Dynamic Document References & @doc/ Autocomplete
overview: "Two features: (1) Dynamic tool descriptions that inject available document names/IDs into the tool calling descriptions so the LLM can skip the list call, and (2) Unified @doc/ autocomplete in chat input that searches both conversation docs and global docs with type badges, converting to #doc_N / #gdoc_N format on send."
todos:
  - id: backend-docs-autocomplete-endpoint
    content: "Add /docs/autocomplete endpoint that searches both conversation docs and global docs by prefix, returning unified results with type badges"
    status: completed
  - id: backend-dynamic-tool-descriptions
    content: "Modify _get_enabled_tools in Conversation.py to inject dynamic doc listings into tool descriptions for docs_list_global_docs and docs_list_conversation_docs"
    status: completed
  - id: frontend-doc-autocomplete
    content: "Add @doc/ autocomplete trigger in common-chat.js with unified dropdown showing local+global docs with type badges"
    status: completed
  - id: frontend-reference-conversion
    content: "Parse @doc/ references on send and convert to #doc_N / #gdoc_N format in parseMessageForCheckBoxes.js"
    status: completed
  - id: documentation-update
    content: "Update feature docs for new @doc/ autocomplete and dynamic tool descriptions"
    status: completed
---

# Dynamic Document References & @doc/ Autocomplete

## Problem Statement

Currently, document references in chat require the user to remember `#doc_1`, `#gdoc_3`, or `#folder:Research` syntax with no discoverability. Users must know which documents exist and their numbering. Additionally, the LLM's tool descriptions for document tools are static — it doesn't know which documents are available without first calling `docs_list_global_docs` or `docs_list_conversation_docs`, wasting a tool call round-trip.

## Goals

1. **Dynamic tool descriptions**: When tool calling is enabled, inject actual document names/IDs into the tool description strings so the LLM knows what documents are available without calling list tools first.
2. **Unified @doc/ autocomplete**: Add `@doc/` autocomplete in the chat input that searches both conversation (local) and global documents, with type badges to distinguish. On selection, insert a human-readable reference that gets converted to the existing `#doc_N` / `#gdoc_N` backend format on send.

## Non-Goals

- MCP server dynamic descriptions (MCP tools keep static descriptions; MCP clients call list tools anyway)
- Changing the backend `#doc_N` / `#gdoc_N` parsing logic (we convert to this format on the frontend)
- Adding new backend reference resolution — we reuse the existing parsing in `get_uploaded_documents_for_query()` and `get_global_documents_for_query()`

## Architecture

### Feature 1: Dynamic Tool Descriptions

**Injection point**: `Conversation._get_enabled_tools()` (Conversation.py line 6410)

Currently this method calls `TOOL_REGISTRY.get_openai_tools_param(enabled_names)` which returns static descriptions. We modify the flow to:

1. After `get_openai_tools_param()` returns the tools list, iterate through it
2. For `docs_list_global_docs`: append `\n\nCurrently available global documents:\n1. <display_name> (doc_id: <id>)\n2. ...` to the description
3. For `docs_list_conversation_docs`: append `\n\nCurrently attached conversation documents:\n1. <title> (#doc_1)\n2. ...` to the description
4. This lets the LLM see what's available directly and skip calling list tools, going straight to `docs_query` or `docs_get_full_text`

**Data sources**:
- Global docs: `list_global_docs(users_dir, user_email)` from `database/global_docs.py`
- Conversation docs: `self.get_field("uploaded_documents_list")` from the Conversation object

**Key decisions**:
- Only inject up to ~20 docs to avoid bloating the tool description
- If no docs exist, add "No documents currently available" to signal the LLM
- Format: concise one-liner per doc with index, display_name/title, and doc_storage_path

### Feature 2: @doc/ Autocomplete

**Pattern**: Follow the existing `@memory` autocomplete architecture in `common-chat.js` (lines 3640-4078)

**Trigger**: User types `@doc/` in the chat textarea (or just `@doc` followed by typing)

**UI Flow**:
1. User types `@doc/` → detect the `@doc/` prefix (or `@doc` followed by characters)
2. Debounce 200ms, then call new endpoint `GET /docs/autocomplete?conversation_id=<id>&prefix=<text>`
3. Backend returns combined list of conversation docs + global docs, each with `type` field ("local" or "global")
4. Render dropdown with type badges: blue "local" badge for conversation docs, green "global" badge for global docs
5. On selection, insert `@doc/<display_name_or_title>` into textarea
6. On message send, parse `@doc/` references and convert them to `#doc_N` or `#gdoc_N` format

**Reference format in textarea**: `@doc/<name>` where name is the display_name (global) or title (local)

**Conversion on send**: The frontend parses `@doc/<name>` references before sending and converts them:
- Match against known conversation docs by title → `#doc_N`
- Match against known global docs by display_name → `#gdoc_N`
- This reuses the existing backend parsing in `get_uploaded_documents_for_query()` and `get_global_documents_for_query()`

## Implementation Tasks

### Task 1: Backend — `/docs/autocomplete` endpoint

**File**: `endpoints/documents.py` (or new endpoint in `endpoints/global_docs.py`)

**Endpoint**: `GET /docs/autocomplete`

**Query params**:
- `conversation_id` (optional): If provided, also search conversation docs
- `prefix` (required): Search prefix to filter docs by
- `limit` (optional, default 10): Max results

**Response**:
```json
{
  "status": "ok",
  "docs": [
    {
      "type": "local",
      "index": 1,
      "doc_id": "abc-123",
      "title": "ML Research Paper",
      "display_name": "ML Research Paper",
      "short_summary": "A paper about...",
      "ref": "#doc_1"
    },
    {
      "type": "global",
      "index": 3,
      "doc_id": "def-456",
      "title": "My Resume",
      "display_name": "resume_2025",
      "short_summary": "Professional resume...",
      "ref": "#gdoc_3"
    }
  ]
}
```

**Implementation notes**:
- Import `list_global_docs` from `database/global_docs.py`
- For conversation docs, load conversation from cache, call `get_field("uploaded_documents_list")`
- Filter by prefix matching against display_name, title (case-insensitive, substring match)
- Local docs come first, then global docs
- Each result includes the `ref` field (e.g., `#doc_1`, `#gdoc_3`) which is what gets inserted on send

**Files to modify**: `endpoints/global_docs.py` (add route to existing blueprint since it already has autocomplete), OR create the endpoint in `endpoints/documents.py` since it covers both local and global.

**Recommendation**: Add to `endpoints/documents.py` since it naturally spans both document types. The endpoint needs access to conversation_cache for local docs.

### Task 2: Backend — Dynamic Tool Descriptions

**File**: `Conversation.py`

**Function**: `_get_enabled_tools(self, checkboxes)` (line 6410)

**Changes**:
1. After line 6473 (`tools_param = TOOL_REGISTRY.get_openai_tools_param(enabled_names)`), add a post-processing step
2. Create helper method `_inject_dynamic_doc_descriptions(self, tools_param, user_email)` that:
   - Iterates through `tools_param`
   - For `docs_list_global_docs`: fetches global docs, appends listing to description
   - For `docs_list_conversation_docs`: fetches conversation docs, appends listing to description
   - For `docs_query` and `docs_get_full_text`: optionally append available doc_storage_paths so LLM can use them directly
3. Returns modified tools_param

**Helper method pseudocode**:
```python
def _inject_dynamic_doc_descriptions(self, tools_param, user_email):
    """Inject available document listings into doc tool descriptions."""
    if not tools_param:
        return tools_param
    
    # Fetch global docs (lazy, only if needed)
    global_docs = None
    # Fetch conversation docs (lazy, only if needed)
    conv_docs = None
    
    for tool in tools_param:
        func_name = tool["function"]["name"]
        
        if func_name == "docs_list_global_docs":
            if global_docs is None:
                from database.global_docs import list_global_docs
                global_docs = list_global_docs(users_dir=self._docs_users_dir(), user_email=user_email)
            if global_docs:
                listing = "\n\nCurrently available global documents:"
                for idx, row in enumerate(global_docs[:20]):
                    name = row.get("display_name") or row.get("title") or row.get("doc_id")
                    listing += f"\n  {idx+1}. {name} (doc_id: {row['doc_id']}, path: {row.get('doc_storage', '')})"
                tool["function"]["description"] += listing
            else:
                tool["function"]["description"] += "\n\nNo global documents currently available."
        
        elif func_name == "docs_list_conversation_docs":
            if conv_docs is None:
                conv_docs = self.get_field("uploaded_documents_list") or []
            if conv_docs:
                listing = "\n\nCurrently attached conversation documents:"
                for idx, entry in enumerate(conv_docs[:20]):
                    doc_id, doc_storage, pdf_url = entry[0], entry[1], entry[2]
                    name = entry[3] if len(entry) > 3 and entry[3] else doc_id
                    listing += f"\n  {idx+1}. {name} (#doc_{idx+1}, path: {doc_storage})"
                tool["function"]["description"] += listing
            else:
                tool["function"]["description"] += "\n\nNo documents attached to this conversation."
        
        elif func_name in ("docs_query", "docs_get_full_text", "docs_get_info",
                           "docs_answer_question"):
            # Inject available doc_storage_paths so LLM can use directly
            all_paths = []
            if conv_docs is None:
                conv_docs = self.get_field("uploaded_documents_list") or []
            for idx, entry in enumerate(conv_docs[:20]):
                name = entry[3] if len(entry) > 3 and entry[3] else entry[0]
                all_paths.append(f"  - {name}: {entry[1]}")
            if global_docs is None:
                from database.global_docs import list_global_docs
                global_docs = list_global_docs(users_dir=self._docs_users_dir(), user_email=user_email)
            for idx, row in enumerate(global_docs[:20]):
                name = row.get("display_name") or row.get("title") or row.get("doc_id")
                all_paths.append(f"  - {name}: {row.get('doc_storage', '')}")
            if all_paths:
                tool["function"]["description"] += "\n\nAvailable doc_storage_path values:\n" + "\n".join(all_paths)
    
    return tools_param
```

**Risks and mitigations**:
- **Token bloat**: Cap at 20 docs per type. If user has 100+ global docs, truncate with "...and N more"
- **Performance**: `list_global_docs` is a DB call. Only execute if doc tools are enabled. Cache within the method scope (done via lazy init above).
- **Stale data**: This is called per-request, so always fresh. No caching concerns.

**Integration point** (line ~6473 in Conversation.py):
```python
tools_param = TOOL_REGISTRY.get_openai_tools_param(enabled_names)
# NEW: inject dynamic doc listings
if tools_param:
    tools_param = self._inject_dynamic_doc_descriptions(tools_param, user_email)
```

Note: `user_email` needs to be accessible. Check if `self` has it or if it needs to be passed. The `reply()` method (which calls `_get_enabled_tools`) has access to `session.get("email")` or `query.get("user_email")`. May need to add `user_email` parameter to `_get_enabled_tools`.

### Task 3: Frontend — @doc/ Autocomplete in Chat Input

**File**: `interface/common-chat.js`

**Approach**: Add a new IIFE (Immediately Invoked Function Expression) block similar to the existing `@memory` autocomplete (lines 3640-4078) and `/slash` autocomplete (lines 4080-4383).

**New section**: `// @doc/ Document Reference Autocomplete`

**State object**:
```javascript
var docAutocompleteState = {
    active: false,
    query: '',
    triggerPosition: -1,  // Position of '@doc/' in textarea
    selectedIndex: 0,
    results: [],           // [{type:'local'|'global', index, doc_id, title, display_name, short_summary, ref}]
    debounceTimer: null,
    conversationId: null   // Current conversation ID for local doc lookup
};
```

**Trigger detection** (in `handleDocInput`):
- Match pattern `@doc/` followed by 0+ non-space characters before cursor
- Regex on textBeforeCursor: `/@doc\/([^\s]*)$/`
- `@doc/` must be at start or preceded by whitespace
- Trigger after 0 characters after `@doc/` (show all docs immediately)
- Also trigger on just `@doc` (without slash) for partial typing

**Dropdown ID**: `#doc-autocomplete-dropdown`

**Item rendering**:
```javascript
// Type badge colors
var typeBadge = item.type === 'local' 
    ? '<span class="badge badge-sm ml-1" style="background-color:#007bff;color:white;">local</span>'
    : '<span class="badge badge-sm ml-1" style="background-color:#28a745;color:white;">global</span>';

html += '<div class="doc-ac-item px-3 py-2" data-index="' + index + '" ...>' +
    '<i class="bi bi-file-earmark-text mr-2 text-muted"></i>' +
    '<div class="flex-grow-1">' +
        '<div style="font-size:13px;">' + escapeHtml(item.display_name || item.title) + typeBadge + '</div>' +
        '<div style="font-size:11px;color:#6c757d;">' +
            '<code>' + escapeHtml(item.ref) + '</code> &middot; ' + escapeHtml(item.short_summary || '') +
        '</div>' +
    '</div>' +
'</div>';
```

**Selection handling** (`selectDocItem`):
- Replace `@doc/<prefix>` with `@doc/<display_name> ` in textarea
- Store the mapping `{displayName → ref}` so we can convert on send

**Conversation ID**: Get from `window.currentConversation` or `$('#conversation_id').val()` or similar global.

**API call**:
```javascript
$.getJSON('/docs/autocomplete', {
    conversation_id: docAutocompleteState.conversationId,
    prefix: prefix,
    limit: 10
}, function(resp) { ... });
```

**Keyboard navigation**: Same pattern as existing (ArrowUp/Down, Enter/Tab, Escape).

**Event namespaces**: `.docAutocomplete` to avoid conflicts.

### Task 4: Frontend — Reference Conversion on Send

**File**: `interface/parseMessageForCheckBoxes.js`

**New function**: `parseDocReferences(text, docMappings)`

**Logic**:
1. Before sending, scan the message text for `@doc/<name>` patterns
2. Look up `<name>` in the stored mappings (built from autocomplete selections)
3. Replace `@doc/<name>` with the corresponding `#doc_N` or `#gdoc_N` ref
4. The backend already parses these via `get_uploaded_documents_for_query()` and `get_global_documents_for_query()`

**Storage of mappings**: When user selects an autocomplete item, store the mapping in a module-level object:
```javascript
// In common-chat.js (doc autocomplete module)
var docRefMappings = {};  // { 'display_name': '#gdoc_3', 'ML Paper': '#doc_1' }
```

**Integration with send flow** (in `common-chat.js` `sendMessage` function):
- Before the message text is sent, call a conversion function that replaces `@doc/Name` → `#gdoc_N` or `#doc_N`
- This must happen BEFORE the message hits the backend

**Alternative approach** (simpler): Instead of storing mappings, directly insert the `#doc_N` / `#gdoc_N` ref into the textarea on autocomplete selection, and display it with the human-readable name as a label. However, since the textarea is a plain `<textarea>` (not contenteditable), we can't render rich content. So the simplest approach is:

- On autocomplete selection, insert `#gdoc_3` (or `#doc_1`) directly into the textarea
- The dropdown shows the human-readable name with the ref code below it
- User sees `#gdoc_3` in their textarea, which the backend already knows how to parse

This is the simplest approach because:
- No mapping storage needed
- No conversion on send needed
- Backend already handles `#doc_N` and `#gdoc_N` parsing
- Consistent with how `@memory` references insert `@friendly_id` directly

**Recommendation**: Insert `#gdoc_N` / `#doc_N` directly on selection. The autocomplete dropdown shows the human-readable name for discoverability, but the inserted text is the machine-parseable reference.

### Task 5: Documentation Update

**Files to update**:
1. `documentation/features/global_docs/README.md` — Add @doc/ autocomplete section
2. `documentation/features/tool_calling/README.md` — Document dynamic tool descriptions
3. `documentation/features/conversation_flow/` — Update autocomplete section
4. `documentation/README.md` — Update feature index if needed

## Files Modified

### Backend
- `endpoints/documents.py` OR `endpoints/global_docs.py` — New `/docs/autocomplete` endpoint
- `Conversation.py` — `_get_enabled_tools()` + new `_inject_dynamic_doc_descriptions()` helper

### Frontend
- `interface/common-chat.js` — New @doc/ autocomplete IIFE section (~200 lines)
- `interface/parseMessageForCheckBoxes.js` — (Optional, may not be needed if we insert refs directly)

### Documentation
- `documentation/planning/plans/dynamic_doc_references_autocomplete.plan.md` — This plan
- `documentation/features/global_docs/README.md` — Updated feature docs
- `documentation/features/tool_calling/README.md` — Updated feature docs

## Risks and Alternatives

### Risk: Token bloat from dynamic descriptions
**Mitigation**: Cap at 20 docs per type. Add total doc count if truncated. Monitor token usage.

### Risk: Performance of DB call in _get_enabled_tools
**Mitigation**: `list_global_docs` is a lightweight SQLite query. Only called when doc tools are enabled. Lazy-loaded within the method.

### Risk: Autocomplete reference names may be ambiguous
**Mitigation**: Use `#doc_N` / `#gdoc_N` format directly in textarea (no ambiguity). Dropdown shows human-readable names for discovery.

### Alternative: Rich text input (contenteditable)
**Rejected**: Would require rewriting the entire chat input. Too much risk for this feature. Plain textarea with `#ref` syntax is sufficient and consistent with existing `@friendly_id` pattern.

### Alternative: Separate @doc/ and @global_doc/ triggers
**Rejected per user preference**: Unified @doc/ with type badges is simpler for users.
