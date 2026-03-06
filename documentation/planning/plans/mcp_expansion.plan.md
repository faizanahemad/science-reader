## MCP Server Expansion Plan

**Status**: v3 — Enhanced with tools.py architecture, corrected status, dependency maps
**Created**: 2026-03-05
**Updated**: 2026-03-06
**Platform**: Remote server (assist-chat.site) + Local Electron (macOS)
**Parent**: `desktop_companion.plan.md` (BRD v6, Phase 0)

Based on:
- `documentation/product/behavior/chat_app_capabilities.md` (full capability inventory)
- `documentation/product/ops/mcp_server_setup.md` (existing MCP server architecture)
- `desktop_companion.plan.md` Section 4.3 Tab 2, Section 6, Section 8

Primary goals:
- Extend existing MCP servers with write operations and structural queries
- Add Image Generation MCP server
- Set up nginx reverse proxy with SSL for remote MCP access
- Build local filesystem MCP for OpenCode Tab 2 in the desktop companion
- Mirror all new MCP tools as `@register_tool` handlers in `code_common/tools.py` for the main web UI
- Serve as the implementation guide for BRD Phase 0

---

## Table of Contents

0. [Status Corrections & Gap Analysis](#0-status-corrections--gap-analysis)
1. [Current State](#1-current-state)
2. [New Remote MCP Tools](#2-new-remote-mcp-tools)
3. [Main UI Tool Handlers (code_common/tools.py)](#3-main-ui-tool-handlers)
   - 3.5 [tools.py Architecture Guide](#35-toolspy-architecture-guide)
4. [New Local Filesystem MCP](#4-new-local-filesystem-mcp)
5. [Nginx Reverse Proxy Setup](#5-nginx-reverse-proxy-setup)
6. [Security Hardening](#6-security-hardening)
7. [Server Registration](#7-server-registration)
8. [Implementation Plan](#8-implementation-plan)
9. [Testing](#9-testing)
10. [Appendix: OpenCode Config Template](#appendix-opencode-config-template)
11. [Appendix B: Complete File Change Summary](#appendix-b-complete-file-change-summary)

---

## 0) Status Corrections & Gap Analysis

The v2 plan contained several inaccuracies about what work was completed. This section corrects the record.

### Security hardening (127.0.0.1 bind)

The v2 plan marked this as "DONE" across all 7 servers. **Actual state at time of v3 audit (2026-03-06)**:

| Server | File | Status |
|--------|------|--------|
| Web Search (8100) | `mcp_server/__init__.py` | `127.0.0.1` (done) |
| PKB (8101) | `mcp_server/pkb.py` | `127.0.0.1` (done) |
| Documents (8102) | `mcp_server/docs.py` | `127.0.0.1` (done) |
| Artefacts (8103) | `mcp_server/artefacts.py` | `127.0.0.1` (done) |
| **Conversation (8104)** | **`mcp_server/conversation.py`** | **Was still `0.0.0.0` -- FIXED in v3** |
| Prompts & Actions (8105) | `mcp_server/prompts_actions.py` | `127.0.0.1` (done) |
| Code Runner (8106) | `mcp_server/code_runner_mcp.py` | `127.0.0.1` (done) |

The conversation server was left unsecured, binding to all interfaces. Fixed during v3 plan review.

### New tools

**None of the planned new MCP tools or tools.py handlers have been implemented.** The v2 plan was a specification document; no implementation followed.

| Planned Item | Status |
|-------------|--------|
| `mcp_server/image_gen.py` (new file) | Not created |
| `start_image_gen_mcp_server` in `__init__.py` + `server.py` | Not added |
| 4 new tools in `mcp_server/docs.py` | Not added |
| 3 new tools in `mcp_server/pkb.py` | Not added |
| `_get_keys()` + `transcribe_audio` in `mcp_server/prompts_actions.py` | Not added |
| 8 new `@register_tool` handlers in `code_common/tools.py` | Not added |
| nginx `/mcp/*` location blocks | Not added |

---

## 1) Current State

### Existing MCP servers (7 servers, ~49 tools)

| Server | Port | File | Tools |
|--------|------|------|-------|
| Web Search | 8100 | `mcp_server/mcp_app.py` | 4: perplexity_search, jina_search, jina_read_page, read_link |
| PKB | 8101 | `mcp_server/pkb.py` | 6-10: search, get_claim, resolve_reference, get_pinned, add_claim, edit_claim (+4 full-tier) |
| Documents | 8102 | `mcp_server/docs.py` | 4-9: list_conv_docs, list_global_docs, query, get_full_text (+5 full-tier) |
| Artefacts | 8103 | `mcp_server/artefacts.py` | 8: list, create, get, get_file_path, update, delete, propose_edits, apply_edits |
| Conversations | 8104 | `mcp_server/conversation.py` | 12: memory pad get/set, history, user detail/prefs, messages, search/list/read messages, details, memory_pad |
| Prompts & Actions | 8105 | `mcp_server/prompts_actions.py` | 5: list, get, create, update, temp_llm_action |
| Code Runner | 8106 | `mcp_server/code_runner_mcp.py` | 1: run_python_code |

All servers:
- Run as daemon threads inside `server.py`
- Use JWT Bearer auth (HS256, `MCP_JWT_SECRET`)
- Rate limited at 10 req/min per token
- **DONE** ~~Currently bind to `0.0.0.0`~~ → Now bind to `127.0.0.1` (security fix completed 2026-03-06, all 7 servers confirmed)
- Currently accessed via `http://localhost:810x/` (local only)

### Dual-surface architecture

Every tool exists in **two places**:

1. **MCP server** (`mcp_server/*.py`) — exposed via streamable-HTTP for external clients (OpenCode desktop, curl, etc.)
2. **Main UI tool handler** (`code_common/tools.py`) — `@register_tool` decorated functions called by the LLM tool-calling loop in `Conversation.py` when the user is chatting in the web UI

Both surfaces call the **same backend logic** (database functions, DocIndex, StructuredAPI, etc.) — the MCP server is a thin ASGI wrapper, the tools.py handler is a thin `ToolCallResult` wrapper. They must be kept in sync: every MCP tool gets a corresponding tools.py handler with matching parameters.

---

## 2) New Remote MCP Tools

### 2.1) Extend Documents MCP (port 8102) — 4 new tools

File: `mcp_server/docs.py`

#### `docs_upload_global`

Upload a file or URL to the Global Docs library.

```python
@mcp.tool()
async def docs_upload_global(
    user_email: str,
    source: str,           # File path on server OR URL
    display_name: str = None,
    folder_id: str = None
) -> str:
    """Upload a file or URL to the user's Global Documents library.
    
    The document is indexed (FAISS + LLM title/summary) and available
    across all conversations via #gdoc_N references.
    
    Args:
        user_email: Email of the document owner.
        source: Absolute file path on the server, or a URL to index.
        display_name: Optional human-readable name for the document.
        folder_id: Optional folder ID to organize the document into.
    
    Returns:
        JSON with doc_id, title, source, display_name.
    """
```

**Implementation**: Calls the existing `global_docs.upload_global_document()` logic (from `endpoints/global_docs.py`). For file paths, reads the file from server filesystem. For URLs, downloads and indexes. Uses `create_immediate_document_index()` for full FAISS + LLM indexing.

**Note**: This tool operates on server-side files/URLs. To upload a file from the user's Mac, the Electron client must first transfer the file (e.g., via a separate upload endpoint or by providing a URL).

#### `docs_delete_global`

```python
@mcp.tool()
async def docs_delete_global(
    user_email: str,
    doc_id: str
) -> str:
    """Delete a global document by its doc_id.
    
    Removes the database entry and filesystem storage.
    """
```

**Implementation**: Calls existing `database.global_docs.delete_global_document()` + filesystem cleanup.

#### `docs_set_global_doc_tags`

```python
@mcp.tool()
async def docs_set_global_doc_tags(
    user_email: str,
    doc_id: str,
    tags: list[str]
) -> str:
    """Set tags on a global document (replaces all existing tags).
    
    Args:
        tags: List of tag strings, e.g. ["research", "arxiv", "2026"].
    """
```

**Implementation**: Calls existing `database.doc_tags.set_tags()`.

#### `docs_assign_to_folder`

```python
@mcp.tool()
async def docs_assign_to_folder(
    user_email: str,
    doc_id: str,
    folder_id: str = None
) -> str:
    """Assign a global document to a folder, or unassign (folder_id=null).
    
    Args:
        folder_id: Folder ID to assign to. Pass null/None to unassign.
    """
```

**Implementation**: Calls existing `database.doc_folders.assign_doc_to_folder()`.

---

### 2.2) Extend PKB MCP (port 8101) — 3 new tools

File: `mcp_server/pkb.py`

#### `pkb_list_contexts`

```python
@mcp.tool()
async def pkb_list_contexts(
    user_email: str,
    limit: int = 100
) -> str:
    """List all PKB contexts with their claim counts.
    
    Contexts organize claims hierarchically. Each context has a
    friendly_id (suffixed with _context) for @-referencing in chat.
    
    Returns:
        JSON array of {id, name, friendly_id, description, parent_id, claim_count}.
    """
```

**Implementation**: Queries `truth_management_system/crud/contexts.py` — `get_all()` + count claims via `context_claims` join table.

#### `pkb_list_entities`

```python
@mcp.tool()
async def pkb_list_entities(
    user_email: str,
    limit: int = 100
) -> str:
    """List all PKB entities with types and linked claim counts.
    
    Entities represent people, organizations, or concepts linked to claims.
    Each entity has a friendly_id (suffixed with _entity) for @-referencing.
    
    Returns:
        JSON array of {id, name, friendly_id, entity_type, description, claim_count}.
    """
```

**Implementation**: Queries `truth_management_system/crud/entities.py` — `get_all()` + count via `claim_entities` join.

#### `pkb_list_tags`

```python
@mcp.tool()
async def pkb_list_tags(
    user_email: str,
    limit: int = 100
) -> str:
    """List all PKB tags with hierarchy and claim counts.
    
    Tags categorize claims and form a hierarchy. Referencing @tag_friendly_id
    resolves to all claims with that tag and descendant tags (recursive).
    
    Returns:
        JSON array of {id, name, friendly_id, parent_id, claim_count}.
    """
```

**Implementation**: Queries `truth_management_system/crud/tags.py` — `get_all()` + count via `claim_tags` join.

---

### 2.3) New Image Generation MCP (port 8107) — 1 tool

File: `mcp_server/image_gen.py` (new file)

This is a **new MCP server** that runs alongside the existing 7 servers as a daemon thread in `server.py`.

#### `generate_image`

```python
@mcp.tool()
async def generate_image(
    user_email: str,
    prompt: str,
    model: str = "google/gemini-3.1-flash-image-preview",
    input_image: str = None,
    better_context: bool = True
) -> str:
    """Generate an image from a text prompt, or edit an existing image.
    
    Uses the server's image generation pipeline with prompt refinement.
    Returns the image as a base64-encoded PNG string.
    
    Args:
        user_email: Email of the requesting user.
        prompt: Text description of the desired image.
        model: Image model to use. Options: google/gemini-3.1-flash-image-preview (default),
               google/gemini-2.5-flash-image, google/gemini-3-pro-image-preview,
               openai/gpt-5-image-mini, openai/gpt-5-image.
        input_image: Optional base64-encoded image for editing (data:image/png;base64,...).
        better_context: If true (default), refine the prompt via a cheap LLM for better results.
    
    Returns:
        JSON with {image_base64, text, refined_prompt, model}.
        The image_base64 field contains the full data:image/png;base64,... URI.
        The calling client is responsible for saving the image to disk.
    """
```

**Implementation**: Calls the existing `generate_image_from_prompt()` from `endpoints/image_gen.py`. The function already handles prompt refinement, model selection, and input image processing. The MCP tool wraps it to return base64 instead of saving to a conversation.

**Server startup**: Add to `server.py` alongside the other MCP server threads:
```python
from mcp_server.image_gen import create_image_gen_mcp_app
image_gen_thread = start_mcp_server(create_image_gen_mcp_app, port=8107, name="image-gen")
```

---

### 2.4) Extend Prompts & Actions MCP (port 8105) — 1 new tool

File: `mcp_server/prompts_actions.py`

#### `transcribe_audio`

```python
@mcp.tool()
async def transcribe_audio(
    user_email: str,
    audio_base64: str,
    format: str = "wav"
) -> str:
    """Transcribe audio to text using OpenAI Whisper API.
    
    Args:
        user_email: Email of the requesting user.
        audio_base64: Base64-encoded audio data (without data: URI prefix).
        format: Audio format — wav, mp3, webm, m4a, ogg.
    
    Returns:
        JSON with {text: "transcribed text"}.
    """
```

**Implementation**: Decodes base64 to bytes, writes to temp file, calls OpenAI Whisper API (`POST https://api.openai.com/v1/audio/transcriptions`), returns text. Reuses the same API key access pattern as the existing `/transcribe` endpoint.

---

## 3) Main UI Tool Handlers (`code_common/tools.py`)

### Architecture

`code_common/tools.py` is a **3,537-line** file containing `@register_tool`-decorated handler functions that the main LLM tool-calling loop in `Conversation.py` invokes. Each MCP server tool has a mirrored handler here. The handler:

1. Extracts args from the `args: dict` parameter
2. Calls the same backend functions the MCP server calls (database CRUD, DocIndex, StructuredAPI, etc.)
3. Returns a `ToolCallResult(tool_id="", tool_name="...", result=..., error=...)`

### Existing tool categories in tools.py

| Category | Tools | Lines |
|----------|-------|-------|
| `clarification` | ask_clarification | 403-472 |
| `search` | web_search, perplexity_search, jina_search, jina_read_page, read_link | 475-1224 |
| `documents` | document_lookup, docs_list_conversation_docs, docs_list_global_docs, docs_query, docs_get_full_text, docs_get_info, docs_answer_question, docs_get_global_doc_info, docs_query_global_doc, docs_get_global_doc_full_text | 1227-1761 |
| `pkb` | pkb_search, pkb_get_claim, pkb_resolve_reference, pkb_get_pinned_claims, pkb_add_claim, pkb_edit_claim, pkb_get_claims_by_ids, pkb_autocomplete, pkb_resolve_context, pkb_pin_claim | 1764-2245 |
| `memory` | conv_get_memory_pad, conv_set_memory_pad, conv_get_history, conv_get_user_detail, conv_get_user_preference, conv_get_messages, conv_set_user_detail | 2248-2535 |
| `conversation` | search_messages, list_messages, read_message, get_conversation_details, get_conversation_memory_pad, search_conversations, list_user_conversations, get_conversation_summary | 2538-2806 |
| `code_runner` | run_python_code | 2809-2878 |
| `artefacts` | artefacts_list, artefacts_create, artefacts_get, artefacts_get_file_path, artefacts_update, artefacts_delete, artefacts_propose_edits, artefacts_apply_edits | 2881-3241 |
| `prompts` | prompts_list, prompts_get, temp_llm_action, prompts_create, prompts_update | 3244-3537 |

### New tool handlers to add

For each new MCP tool defined in Section 2, add a corresponding `@register_tool` handler. These go at the end of their respective category sections.

#### 3.1) Document tools — 4 new handlers (append after line ~1761)

Insertion point: After `handle_docs_get_global_doc_full_text` (last doc tool), before the PKB tools section.

```python
# ---------------------------------------------------------------------------
# New Document Write Tools (category: documents)
# ---------------------------------------------------------------------------


@register_tool(
    name="docs_delete_global",
    description=(
        "Delete a global document by its doc_id (write operation). "
        "Removes the database entry and filesystem storage."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier to delete"},
        },
        "required": ["doc_id"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_delete_global(args: dict, context: ToolContext) -> ToolCallResult:
    """Delete a global document by doc_id."""
    doc_id = args.get("doc_id", "")
    try:
        import shutil
        row, doc_storage = _docs_resolve_global_doc(context.user_email, doc_id)
        if row is None:
            return ToolCallResult(
                tool_id="", tool_name="docs_delete_global",
                error=f"Global doc '{doc_id}' not found for user.",
                result="",
            )
        # Delete database entry
        from database.global_docs import delete_global_doc
        delete_global_doc(
            users_dir=_docs_users_dir(),
            user_email=context.user_email,
            doc_id=doc_id,
        )
        # Delete filesystem storage
        if doc_storage and os.path.isdir(doc_storage):
            shutil.rmtree(doc_storage, ignore_errors=True)
        return ToolCallResult(
            tool_id="", tool_name="docs_delete_global",
            result=json.dumps({"success": True, "doc_id": doc_id}),
        )
    except Exception as exc:
        logger.exception("docs_delete_global error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_delete_global",
            error=f"Failed to delete global doc: {exc}",
            result="",
        )


@register_tool(
    name="docs_set_global_doc_tags",
    description=(
        "Set tags on a global document (write operation). "
        "Replaces all existing tags with the provided list."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tag strings, e.g. ['research', 'arxiv', '2026']",
            },
        },
        "required": ["doc_id", "tags"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_set_global_doc_tags(args: dict, context: ToolContext) -> ToolCallResult:
    """Set tags on a global document."""
    doc_id = args.get("doc_id", "")
    tags = args.get("tags", [])
    try:
        from database.doc_tags import set_tags
        set_tags(
            users_dir=_docs_users_dir(),
            user_email=context.user_email,
            doc_id=doc_id,
            tags=tags,
        )
        return ToolCallResult(
            tool_id="", tool_name="docs_set_global_doc_tags",
            result=json.dumps({"success": True, "doc_id": doc_id, "tags": tags}),
        )
    except Exception as exc:
        logger.exception("docs_set_global_doc_tags error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_set_global_doc_tags",
            error=f"Failed to set doc tags: {exc}",
            result="",
        )


@register_tool(
    name="docs_assign_to_folder",
    description=(
        "Assign a global document to a folder, or unassign (write operation). "
        "Pass folder_id=null to move to 'Unfiled'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "The global document identifier"},
            "folder_id": {
                "type": "string",
                "description": "Folder ID to assign to. Null/empty to unassign.",
            },
        },
        "required": ["doc_id"],
    },
    is_interactive=False,
    category="documents",
)
def handle_docs_assign_to_folder(args: dict, context: ToolContext) -> ToolCallResult:
    """Assign a global document to a folder."""
    doc_id = args.get("doc_id", "")
    folder_id = args.get("folder_id") or None
    try:
        from database.doc_folders import assign_doc_to_folder
        assign_doc_to_folder(
            users_dir=_docs_users_dir(),
            user_email=context.user_email,
            doc_id=doc_id,
            folder_id=folder_id,
        )
        return ToolCallResult(
            tool_id="", tool_name="docs_assign_to_folder",
            result=json.dumps({"success": True, "doc_id": doc_id, "folder_id": folder_id}),
        )
    except Exception as exc:
        logger.exception("docs_assign_to_folder error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="docs_assign_to_folder",
            error=f"Failed to assign doc to folder: {exc}",
            result="",
        )
```

**Note**: `docs_upload_global` is omitted from tools.py because it requires file/URL ingestion which is already handled by the existing `/global_docs/upload` endpoint. The LLM in the main UI would never call this directly — it's an MCP-only tool for external clients.

#### 3.2) PKB tools — 3 new handlers (append after line ~2245)

Insertion point: After `handle_pkb_pin_claim` (last PKB tool), before the Conversation Memory Tools section.

```python
# ---------------------------------------------------------------------------
# New PKB Structural Query Tools (category: pkb)
# ---------------------------------------------------------------------------


@register_tool(
    name="pkb_list_contexts",
    description=(
        "List all PKB contexts with their claim counts. "
        "Contexts organize claims hierarchically. Each context has a "
        "friendly_id (suffixed with _context) for @-referencing in chat."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of contexts to return",
                "default": 100,
            },
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_list_contexts(args: dict, context: ToolContext) -> ToolCallResult:
    """List all PKB contexts with claim counts."""
    limit = args.get("limit", 100)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        # Use the contexts CRUD to get contexts with claim counts
        contexts_crud = user_api._db.contexts  # ContextCRUD instance
        rows = contexts_crud.get_with_claim_count(user_email=context.user_email, limit=limit)
        results = []
        for row in rows:
            results.append({
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "friendly_id": row.get("friendly_id", ""),
                "description": row.get("description", ""),
                "parent_id": row.get("parent_context_id"),
                "claim_count": row.get("claim_count", 0),
            })
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_contexts",
            result=_truncate_result(json.dumps(results, default=str)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_contexts",
            error=f"pkb_list_contexts failed: {exc}",
        )


@register_tool(
    name="pkb_list_entities",
    description=(
        "List all PKB entities with types and linked claim counts. "
        "Entities represent people, organizations, or concepts linked to claims. "
        "Each entity has a friendly_id (suffixed with _entity) for @-referencing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of entities to return",
                "default": 100,
            },
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_list_entities(args: dict, context: ToolContext) -> ToolCallResult:
    """List all PKB entities with claim counts."""
    limit = args.get("limit", 100)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        entities_crud = user_api._db.entities  # EntityCRUD instance
        rows = entities_crud.get_with_claim_count(user_email=context.user_email, limit=limit)
        results = []
        for row in rows:
            results.append({
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "friendly_id": row.get("friendly_id", ""),
                "entity_type": row.get("entity_type", ""),
                "description": row.get("description", ""),
                "claim_count": row.get("claim_count", 0),
            })
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_entities",
            result=_truncate_result(json.dumps(results, default=str)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_entities",
            error=f"pkb_list_entities failed: {exc}",
        )


@register_tool(
    name="pkb_list_tags",
    description=(
        "List all PKB tags with hierarchy and claim counts. "
        "Tags categorize claims and form a hierarchy. Referencing @tag_friendly_id "
        "resolves to all claims with that tag and descendant tags (recursive)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of tags to return",
                "default": 100,
            },
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_list_tags(args: dict, context: ToolContext) -> ToolCallResult:
    """List all PKB tags with claim counts."""
    limit = args.get("limit", 100)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        tags_crud = user_api._db.tags  # TagCRUD instance
        rows = tags_crud.get_with_claim_count(user_email=context.user_email, limit=limit)
        results = []
        for row in rows:
            results.append({
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "friendly_id": row.get("friendly_id", ""),
                "parent_id": row.get("parent_tag_id"),
                "claim_count": row.get("claim_count", 0),
            })
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_tags",
            result=_truncate_result(json.dumps(results, default=str)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_tags",
            error=f"pkb_list_tags failed: {exc}",
        )
```

#### 3.3) Image Generation tool — 1 new handler (append after prompts section, ~line 3537)

Insertion point: At the very end of `tools.py`.

```python
# ---------------------------------------------------------------------------
# MCP Image Generation Tools (category: image_gen)
# ---------------------------------------------------------------------------


@register_tool(
    name="generate_image",
    description=(
        "Generate an image from a text prompt, or edit an existing image. "
        "Uses OpenRouter image-capable models (Gemini, GPT-5). "
        "Returns the image as a base64-encoded PNG data URI."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Text description of the desired image"},
            "model": {
                "type": "string",
                "description": (
                    "Image model to use. Options: google/gemini-3.1-flash-image-preview (default), "
                    "google/gemini-2.5-flash-image, google/gemini-3-pro-image-preview, "
                    "openai/gpt-5-image-mini, openai/gpt-5-image"
                ),
                "default": "google/gemini-3.1-flash-image-preview",
            },
            "input_image": {
                "type": "string",
                "description": "Optional base64-encoded image for editing (data:image/png;base64,...)",
            },
            "better_context": {
                "type": "boolean",
                "description": "If true (default), refine the prompt via a cheap LLM for better results",
                "default": True,
            },
        },
        "required": ["prompt"],
    },
    is_interactive=False,
    category="image_gen",
)
def handle_generate_image(args: dict, context: ToolContext) -> ToolCallResult:
    """Generate an image from a text prompt."""
    prompt = args.get("prompt", "")
    model = args.get("model", "google/gemini-3.1-flash-image-preview")
    input_image = args.get("input_image")
    better_context = args.get("better_context", True)

    if not prompt.strip():
        return ToolCallResult(
            tool_id="", tool_name="generate_image",
            error="prompt is required and must not be empty.",
        )

    try:
        keys = context.keys if context.keys else {}
        if not keys.get("OPENROUTER_API_KEY"):
            from endpoints.utils import keyParser
            keys = keyParser({})

        # Optional prompt refinement
        final_prompt = prompt
        if better_context:
            try:
                from endpoints.image_gen import _refine_prompt_with_llm
                final_prompt = _refine_prompt_with_llm(prompt, None, keys)
            except Exception:
                logger.warning("Prompt refinement failed, using raw prompt")

        from endpoints.image_gen import generate_image_from_prompt
        result = generate_image_from_prompt(
            prompt=final_prompt,
            keys=keys,
            model=model,
            input_image=input_image,
        )

        if result.get("error"):
            return ToolCallResult(
                tool_id="", tool_name="generate_image",
                error=result["error"],
            )

        images = result.get("images", [])
        text = result.get("text", "")
        response = {
            "image_base64": images[0] if images else None,
            "image_count": len(images),
            "text": text,
            "refined_prompt": final_prompt if better_context else None,
            "model": model,
        }
        return ToolCallResult(
            tool_id="", tool_name="generate_image",
            result=_truncate_result(json.dumps(response)),
        )

    except Exception as exc:
        logger.exception("generate_image failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="generate_image",
            error=f"Image generation failed: {exc}",
        )
```

#### 3.4) Transcribe Audio tool — 1 new handler (append in prompts section, ~line 3537)

Insertion point: At the end of the prompts section, before the image gen section.

```python
# ---------------------------------------------------------------------------
# Transcribe Audio Tool (category: prompts)
# ---------------------------------------------------------------------------


@register_tool(
    name="transcribe_audio",
    description=(
        "Transcribe audio to text using OpenAI Whisper API. "
        "Accepts base64-encoded audio data and returns transcribed text."
    ),
    parameters={
        "type": "object",
        "properties": {
            "audio_base64": {
                "type": "string",
                "description": "Base64-encoded audio data (without data: URI prefix)",
            },
            "format": {
                "type": "string",
                "description": "Audio format — wav, mp3, webm, m4a, ogg",
                "default": "wav",
            },
        },
        "required": ["audio_base64"],
    },
    is_interactive=False,
    category="prompts",
)
def handle_transcribe_audio(args: dict, context: ToolContext) -> ToolCallResult:
    """Transcribe audio to text using OpenAI Whisper."""
    audio_base64 = args.get("audio_base64", "")
    audio_format = args.get("format", "wav")

    if not audio_base64.strip():
        return ToolCallResult(
            tool_id="", tool_name="transcribe_audio",
            error="audio_base64 is required and must not be empty.",
        )

    try:
        import base64
        import tempfile
        import requests as _requests

        # Resolve API key
        keys = context.keys if context.keys else {}
        if not keys.get("openAIKey"):
            from endpoints.utils import keyParser
            keys = keyParser({})
        api_key = keys.get("openAIKey", "")
        if not api_key:
            return ToolCallResult(
                tool_id="", tool_name="transcribe_audio",
                error="OpenAI API key not configured.",
            )

        # Decode and write to temp file
        audio_bytes = base64.b64decode(audio_base64)
        with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            # Call Whisper API
            with open(tmp_path, "rb") as f:
                resp = _requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (f"audio.{audio_format}", f, f"audio/{audio_format}")},
                    data={"model": "whisper-1"},
                    timeout=120,
                )
            resp.raise_for_status()
            text = resp.json().get("text", "")
        finally:
            os.unlink(tmp_path)

        return ToolCallResult(
            tool_id="", tool_name="transcribe_audio",
            result=json.dumps({"text": text}),
        )

    except Exception as exc:
        logger.exception("transcribe_audio failed: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="transcribe_audio",
            error=f"Transcription failed: {exc}",
        )
```

### Summary of tools.py changes

| New Tool | Category | Insert After | Backend Call |
|----------|----------|-------------|--------------|
| `docs_delete_global` | documents | `handle_docs_get_global_doc_full_text` | `database.global_docs.delete_global_doc()` + `shutil.rmtree()` |
| `docs_set_global_doc_tags` | documents | `handle_docs_delete_global` | `database.doc_tags.set_tags()` |
| `docs_assign_to_folder` | documents | `handle_docs_set_global_doc_tags` | `database.doc_folders.assign_doc_to_folder()` |
| `pkb_list_contexts` | pkb | `handle_pkb_pin_claim` | `ContextCRUD.get_with_claim_count()` |
| `pkb_list_entities` | pkb | `handle_pkb_list_contexts` | `EntityCRUD.get_with_claim_count()` |
| `pkb_list_tags` | pkb | `handle_pkb_list_entities` | `TagCRUD.get_with_claim_count()` |
| `transcribe_audio` | prompts | `handle_prompts_update` | OpenAI Whisper API |
| `generate_image` | image_gen | `handle_transcribe_audio` | `endpoints.image_gen.generate_image_from_prompt()` |

**Note on `docs_upload_global`**: Omitted from tools.py — it requires multipart file ingestion or URL download + full FAISS indexing which is already handled by the existing `/global_docs/upload` Flask endpoint. The LLM in the web UI would not call this directly; it's for MCP external clients (OpenCode) that want to index a server-side file or URL.

---

## 3.5) tools.py Architecture Guide

This section documents the patterns and conventions used in `code_common/tools.py` (3,537 lines) so that new tool handlers are implemented consistently. This is critical because tools.py is the **main UI's tool-calling surface** — every tool here is what the LLM sees and invokes during web chat.

### 3.5.1) Helper function patterns by category

Each tool category has its own set of helper functions that follow a consistent pattern: lazy imports (to avoid circular dependencies), stateless calls (except one singleton), and standardized return types.

| Category | Helpers | Singleton? | Key Pattern |
|----------|---------|-----------|-------------|
| `documents` | `_docs_get_keys()`, `_docs_storage_dir()`, `_docs_users_dir()`, `_docs_conversation_folder()`, `_docs_load_doc_index()`, `_docs_load_conversation()`, `_docs_resolve_global_doc()` | No | All imports lazy inside function body. `_docs_users_dir()` constructs `os.path.join(os.getcwd(), storage, "users")` |
| `pkb` | `_get_pkb_api()`, `_pkb_serialize_action_result()`, `_pkb_serialize_data()` | **Yes** — `_pkb_api_instance` global | StructuredAPI singleton created once, `user_api = api.for_user(email)` per call |
| `memory` | `_conv_load()`, `_conv_users_dir()` | No | Load conversation from disk per call |
| `conversation` | `_conv_tool_kwargs()` + external `CONVERSATION_TOOLS` dict | No | Tool definitions shared with MCP server modules |
| `artefacts` | `_art_load_conversation()` | No | Same as `_conv_load` pattern |
| `prompts` | `_get_prompt_manager()`, `_get_prompt_cache()` | Effectively yes | Access module-level globals from `prompts` module |

**Important**: New doc write tools (`docs_delete_global`, `docs_set_global_doc_tags`, `docs_assign_to_folder`) can reuse the existing `_docs_*` helpers. No new helpers needed for these.

### 3.5.2) PKB CRUD serialization — corrected signatures

The v2 plan's code samples for `pkb_list_contexts/entities/tags` assumed the CRUD methods return `list[dict]`. **This is incorrect.** The actual return types are:

```python
# truth_management_system/crud/contexts.py:431
def get_with_claim_count(self, limit: int = 100) -> List[Tuple[Context, int]]:
    # Returns List[Tuple[Context_model_object, claim_count_int]]

# truth_management_system/crud/entities.py:255
def get_with_claim_count(self, entity_type: Optional[str] = None, limit: int = 100) -> List[Tuple[Entity, int]]:
    # Returns List[Tuple[Entity_model_object, claim_count_int]]

# truth_management_system/crud/tags.py:380
def get_with_claim_count(self, limit: int = 100) -> List[Tuple[Tag, int]]:
    # Returns List[Tuple[Tag_model_object, claim_count_int]]
```

All three PKB model classes (`Context`, `Entity`, `Tag`) have a `.to_dict()` method. The correct serialization pattern is:

```python
rows = crud.get_with_claim_count(limit=limit)
results = []
for model_obj, claim_count in rows:
    d = model_obj.to_dict()
    d["claim_count"] = claim_count
    results.append(d)
return json.dumps(results, default=str)
```

**Also note**: `ContextCRUD.get_with_claim_count` applies `WHERE ctx.user_email = ?` filtering via `self.user_email`, while `EntityCRUD` and `TagCRUD` do **not** filter by user. The CRUD instance gets `user_email` set when created via `user_api._db.contexts` (the `_db` is initialized with the user's email). So the user filtering happens at the CRUD layer for contexts but is absent for entities/tags — this is an existing design choice in the PKB system.

**Access pattern**: The CRUD instances are accessed via `user_api._db.contexts`, `user_api._db.entities`, `user_api._db.tags` — these are attributes on the `DatabaseManager` object, which is accessed through the `StructuredAPI.for_user(email)._db` chain.

### 3.5.3) Database function signatures for doc write tools

The existing database modules use **keyword-only** arguments. Callers must use named parameters:

```python
# database/global_docs.py
def delete_global_doc(*, users_dir, user_email, doc_id) -> bool:
    # Returns True if deleted. Does NOT delete filesystem storage.

# database/doc_tags.py
def set_tags(*, users_dir, user_email, doc_id, tags: list[str]) -> bool:
    # Atomic replace: deletes all existing, inserts new. Returns True on success.

# database/doc_folders.py
def assign_doc_to_folder(*, users_dir, user_email, doc_id, folder_id) -> bool:
    # Pass folder_id=None to move to "Unfiled". Returns True on success.
```

All three use `_docs_users_dir()` for `users_dir` and `context.user_email` for `user_email`. Note that `delete_global_doc` only removes the database entry — filesystem cleanup (`shutil.rmtree(doc_storage)`) must be done separately by the caller.

### 3.5.4) Image generation function signatures

```python
# endpoints/image_gen.py:150
def generate_image_from_prompt(
    prompt: str,
    keys: dict,
    model: str = "google/gemini-3.1-flash-image-preview",
    referer: str = "https://localhost",
    input_image: Optional[str] = None,   # base64 data URI
) -> Dict[str, Any]:
    # Returns {"images": [data_uri, ...], "text": str, "error": str|None}

# endpoints/image_gen.py:98
def _refine_prompt_with_llm(
    raw_prompt: str,
    context_parts: Optional[Dict[str, str]],   # Can be None for tools.py
    keys: dict,
) -> str:
    # Returns refined prompt string. Falls back to raw_prompt on failure.
```

**Important**: The tools.py handler should pass `context_parts=None` to `_refine_prompt_with_llm` since there's no conversation context available during tool execution. The function handles `None` gracefully.

### 3.5.5) Registration pattern for new tools

All new tools should use the standard inline `@register_tool` decorator (not the `_conv_tool_kwargs` pattern, which is only for tools whose definitions are shared with external MCP modules).

New tools append **after the last existing tool** in their category section:
- Doc write tools → after `handle_docs_get_global_doc_full_text` (line ~1761)
- PKB list tools → after `handle_pkb_pin_claim` (line ~2245)
- `transcribe_audio` → after `handle_prompts_update` (line ~3537)
- `generate_image` → after `handle_transcribe_audio` (new section at end of file)

Each new tool follows this exact pattern:

```python
@register_tool(
    name="tool_name",
    description="Human-readable description for the LLM.",
    parameters={
        "type": "object",
        "properties": { ... },
        "required": [ ... ],
    },
    is_interactive=False,
    category="category_name",
)
def handle_tool_name(args: dict, context: ToolContext) -> ToolCallResult:
    """Brief docstring."""
    param = args.get("param", "")
    try:
        # ... business logic ...
        return ToolCallResult(
            tool_id="", tool_name="tool_name",
            result=_truncate_result(json.dumps(result_data)),
        )
    except Exception as exc:
        logger.exception("tool_name error: %s", exc)
        return ToolCallResult(
            tool_id="", tool_name="tool_name",
            error=f"tool_name failed: {exc}",
            result="",
        )
```

Key conventions:
- `tool_id=""` always (filled in by the registry's `execute()` method)
- `result` is always a string (use `json.dumps()` for structured data)
- Always wrap in `_truncate_result()` before returning
- Always use `logger.exception()` in the except block
- Always provide both `error` and `result=""` in the error case
- Get `user_email` from `context.user_email`, never from `args`

### 3.5.6) Corrected code for PKB list tools in tools.py

The v2 plan's code for `pkb_list_contexts`, `pkb_list_entities`, and `pkb_list_tags` had a bug: it called `row.get("id")` on the result, but the CRUD methods return `List[Tuple[Model, int]]` not `list[dict]`. Here is the corrected implementation:

```python
@register_tool(
    name="pkb_list_contexts",
    description=(
        "List all PKB contexts with their claim counts. "
        "Contexts organize claims hierarchically. Each context has a "
        "friendly_id (suffixed with _context) for @-referencing in chat."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of contexts to return",
                "default": 100,
            },
        },
        "required": [],
    },
    is_interactive=False,
    category="pkb",
)
def handle_pkb_list_contexts(args: dict, context: ToolContext) -> ToolCallResult:
    """List all PKB contexts with claim counts."""
    limit = args.get("limit", 100)
    try:
        api = _get_pkb_api()
        user_api = api.for_user(context.user_email)
        rows = user_api._db.contexts.get_with_claim_count(limit=limit)
        results = []
        for ctx_obj, claim_count in rows:
            d = ctx_obj.to_dict()
            d["claim_count"] = claim_count
            results.append(d)
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_contexts",
            result=_truncate_result(json.dumps(results, default=str)),
        )
    except Exception as exc:
        return ToolCallResult(
            tool_id="", tool_name="pkb_list_contexts",
            error=f"pkb_list_contexts failed: {exc}",
            result="",
        )
```

Same pattern for `pkb_list_entities` (using `user_api._db.entities.get_with_claim_count()`) and `pkb_list_tags` (using `user_api._db.tags.get_with_claim_count()`).

### 3.5.7) Dual-surface implementation checklist

For every new tool, two implementations must be created and kept in sync:

```
┌──────────────────────────────────────┐      ┌──────────────────────────────────────┐
│   MCP Server (mcp_server/*.py)       │      │   Main UI (code_common/tools.py)     │
│                                      │      │                                      │
│   @mcp.tool()                        │      │   @register_tool(...)                │
│   def tool_name(                     │      │   def handle_tool_name(              │
│       user_email: str, ...           │      │       args: dict,                    │
│   ) -> str:                          │      │       context: ToolContext            │
│       # calls same backend functions │      │   ) -> ToolCallResult:               │
│       return json.dumps(result)      │      │       # calls same backend functions │
│                                      │      │       return ToolCallResult(...)      │
└──────────────┬───────────────────────┘      └──────────────┬───────────────────────┘
               │                                             │
               └─────────────┐  ┌────────────────────────────┘
                             ▼  ▼
                    ┌─────────────────────┐
                    │  Backend Logic       │
                    │  (database/*, PKB,   │
                    │   endpoints/*, etc.) │
                    └─────────────────────┘
```

Key differences between the two surfaces:

| Aspect | MCP Server | tools.py |
|--------|-----------|----------|
| `user_email` source | Function parameter (from JWT) | `context.user_email` |
| Return type | `str` (JSON string) | `ToolCallResult` |
| Error handling | `return json.dumps({"error": ...})` | `return ToolCallResult(error=..., result="")` |
| Truncation | Not applied (client handles) | `_truncate_result()` applied |
| Logging | `logger.exception()` | `logger.exception()` |
| API keys | `_get_keys()` per-server helper | `context.keys` or `keyParser({})` fallback |

### 3.5.8) Corrected code for PKB list tools in MCP servers

The v2 plan's MCP server code for `pkb_list_contexts/entities/tags` (Section 7.6) also had the same bug of calling `.get()` on tuple results. The correct MCP server implementation:

```python
@mcp.tool()
def pkb_list_contexts(user_email: str, limit: int = 100) -> str:
    """List all PKB contexts with their claim counts."""
    try:
        api = _get_pkb_api()
        user_api = api.for_user(user_email)
        rows = user_api._db.contexts.get_with_claim_count(limit=limit)
        results = []
        for ctx_obj, claim_count in rows:
            d = ctx_obj.to_dict()
            d["claim_count"] = claim_count
            results.append(d)
        return json.dumps(results, default=str)
    except Exception as exc:
        logger.exception("pkb_list_contexts error: %s", exc)
        return json.dumps({"error": f"pkb_list_contexts failed: {exc}"})
```

---

## 4) New Local Filesystem MCP

This MCP server runs **locally inside the Electron app** on the user's Mac. It is NOT deployed on the remote server. It provides OpenCode Tab 2 with file system access to the user's selected working directory.

### Architecture

- **Runtime**: Node.js (spawned by Electron as a child process or in-process)
- **Transport**: Streamable HTTP on `localhost:<dynamic-port>`
- **Auth**: None (localhost only, consumed by OpenCode on the same machine)
- **Sandbox**: All path operations validated against the working directory root
- **Lifecycle**: Started when Electron launches. Restarted when working directory changes.

### Tool definitions

#### `fs_read_file`

Read a file's content with optional line range.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Relative path from working directory |
| `offset` | int | no | Start line (1-indexed, default 1) |
| `limit` | int | no | Max lines to return (default 2000) |

Returns: `{ content: string, total_lines: int, path: string }`

#### `fs_write_file`

Write content to a file (creates or overwrites).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Relative path from working directory |
| `content` | string | yes | File content to write |

Returns: `{ success: bool, path: string, bytes_written: int }`

#### `fs_edit_file`

Find-and-replace edit within a file.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Relative path from working directory |
| `old_string` | string | yes | Text to find (exact match) |
| `new_string` | string | yes | Replacement text |
| `replace_all` | bool | no | Replace all occurrences (default false) |

Returns: `{ success: bool, replacements: int }`. Fails if `old_string` not found or ambiguous (multiple matches when `replace_all` is false).

#### `fs_list_directory`

List files and directories.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | no | Relative path (default: working directory root) |

Returns: Array of `{ name, type: "file"|"directory", size_bytes, modified_at }`, sorted dirs-first then alphabetical.

#### `fs_glob`

Find files by glob pattern.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `pattern` | string | yes | Glob pattern (e.g. `**/*.py`, `src/**/*.ts`) |

Returns: Array of matching relative file paths, sorted by modification time.

Uses: `fast-glob` or `glob` npm package. Respects `.gitignore` by default.

#### `fs_grep`

Search file contents by regex.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `pattern` | string | yes | Regex pattern to search for |
| `include` | string | no | File pattern filter (e.g. `*.py`, `*.{ts,tsx}`) |
| `path` | string | no | Subdirectory to search in (default: working directory root) |

Returns: Array of `{ file, line_number, line_content, match }`, sorted by file modification time.

Uses: `ripgrep` (`rg`) binary if available, otherwise Node.js regex scan. Skips binary files and `.git/`.

#### `fs_run_shell`

Run a shell command in the working directory.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | yes | Shell command to execute |
| `timeout` | int | no | Timeout in milliseconds (default 120000) |

Returns: `{ stdout, stderr, exit_code, timed_out: bool }`

Uses: Node.js `child_process.exec()` with `cwd` set to working directory. No additional sandboxing beyond the working directory as cwd.

#### `fs_mkdir`

Create a directory (with parent directories).

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Relative path for new directory |

Returns: `{ success: bool, path: string }`

Uses: `fs.mkdirSync(resolvedPath, { recursive: true })`.

#### `fs_move`

Move or rename a file/directory.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | yes | Relative path of source |
| `destination` | string | yes | Relative path of destination |

Returns: `{ success: bool }`. Fails if destination exists.

Both source and destination must be within the working directory.

#### `fs_delete`

Delete a file or directory.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Relative path to delete |
| `recursive` | bool | no | Required for directories (default false) |

Returns: `{ success: bool, path: string }`

Uses: `fs.rmSync(resolvedPath, { recursive })`. Refuses to delete the working directory root itself.

### Security implementation

```javascript
const path = require('path');

function validatePath(workdir, userPath) {
  const resolved = path.resolve(workdir, userPath);
  if (!resolved.startsWith(workdir + path.sep) && resolved !== workdir) {
    throw new Error(`Path "${userPath}" escapes working directory`);
  }
  return resolved;
}
```

Every tool calls `validatePath()` before any filesystem operation. Path traversal attacks (`../../etc/passwd`) are blocked.

---

## 5) Nginx Reverse Proxy Setup

### Location blocks to add

Add inside the existing HTTPS `server { }` block in `/etc/nginx/sites-enabled/science-reader`:

```nginx
# ===== MCP Server Reverse Proxy =====
# All MCP servers use streamable-HTTP transport.
# SSL termination happens here; backends speak plain HTTP on localhost.
# JWT Bearer auth is handled by each MCP server, not nginx.

location /mcp/search/ {
    proxy_pass http://127.0.0.1:8100/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_read_timeout 300s;
}

location /mcp/pkb/ {
    proxy_pass http://127.0.0.1:8101/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_read_timeout 300s;
}

location /mcp/docs/ {
    proxy_pass http://127.0.0.1:8102/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_read_timeout 300s;
}

location /mcp/artefacts/ {
    proxy_pass http://127.0.0.1:8103/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_read_timeout 300s;
}

location /mcp/conversations/ {
    proxy_pass http://127.0.0.1:8104/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_read_timeout 300s;
}

location /mcp/prompts/ {
    proxy_pass http://127.0.0.1:8105/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_read_timeout 300s;
}

location /mcp/code/ {
    proxy_pass http://127.0.0.1:8106/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_read_timeout 300s;
}

location /mcp/image/ {
    proxy_pass http://127.0.0.1:8107/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection '';
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

### Deployment steps

```bash
# 1. Edit nginx config
sudo nano /etc/nginx/sites-enabled/science-reader

# 2. Test config
sudo nginx -t

# 3. Reload (zero-downtime)
sudo systemctl reload nginx

# 4. Verify each endpoint
curl -s https://assist-chat.site/mcp/search/health
curl -s https://assist-chat.site/mcp/pkb/health
curl -s https://assist-chat.site/mcp/docs/health
# ... etc for all 8 servers

# 5. Test authenticated call
curl -H "Authorization: Bearer $MCP_JWT_TOKEN" \
     https://assist-chat.site/mcp/pkb/mcp \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### No new SSL certificate needed

The existing Let's Encrypt cert for `assist-chat.site` covers all paths. Path-based routing (`/mcp/*`) is just nginx location matching within the same domain and cert.

---

## 6) Security Hardening

### Bind MCP servers to localhost only

Current state: All MCP servers bind to `0.0.0.0:810x` — accessible directly from the internet (bypassing nginx/SSL/auth if firewall allows these ports).

**Fix**: Change each MCP server's Uvicorn startup to bind to `127.0.0.1`:

File: `mcp_server/__init__.py` (or wherever `start_mcp_server` is defined)

```python
# Before:
uvicorn.run(app, host="0.0.0.0", port=port)

# After:
uvicorn.run(app, host="127.0.0.1", port=port)
```

After this change, MCP servers are only reachable via nginx reverse proxy (which adds SSL termination).

### JWT token security

- Tokens are HS256-signed with `MCP_JWT_SECRET` — cannot be forged without the secret.
- Tokens have `exp` claim for expiry.
- Rate limiting: 10 req/min per token (per email in JWT payload).
- Over HTTPS: the `Authorization: Bearer <jwt>` header is encrypted in transit.
- Health endpoints (`/health`) remain unauthenticated — return only `{"status":"ok"}`.

---

## 7) Server Registration

### New Image Gen MCP server registration

#### 7.1) `mcp_server/image_gen.py` — NEW FILE

Follow the exact pattern of `mcp_server/docs.py`. The file structure:

```python
"""
MCP image generation server application.

Port 8107. Wraps endpoints.image_gen.generate_image_from_prompt().

Environment variables:
    IMAGE_GEN_MCP_ENABLED: Set to "false" to skip startup (default "true").
    IMAGE_GEN_MCP_PORT: Port (default 8107).
    MCP_JWT_SECRET: Required. HS256 secret.
    MCP_RATE_LIMIT: Max tool calls per token per minute (default 10).
"""

# Standard imports: contextlib, json, logging, os, threading
# Import: JWTAuthMiddleware, RateLimitMiddleware, _health_check from mcp_server.mcp_app
# Import: _get_keys helper (or define local _get_keys like docs.py)

def create_image_gen_mcp_app(jwt_secret, rate_limit=10):
    """Create the Image Gen MCP server as an ASGI application."""
    from mcp.server.fastmcp import FastMCP
    
    mcp = FastMCP("Image Generation Server", stateless_http=True, json_response=True, streamable_http_path="/")

    @mcp.tool()
    def generate_image(
        user_email: str,
        prompt: str,
        model: str = "google/gemini-3.1-flash-image-preview",
        input_image: str = None,
        better_context: bool = True,
    ) -> str:
        """Generate an image from a text prompt, or edit an existing image.
        
        Uses the server's image generation pipeline with prompt refinement.
        Returns the image as a base64-encoded PNG string.
        
        Args:
            user_email: Email of the requesting user.
            prompt: Text description of the desired image.
            model: Image model to use.
            input_image: Optional base64-encoded image for editing.
            better_context: If true, refine the prompt via a cheap LLM.
        """
        keys = _get_keys()
        final_prompt = prompt
        if better_context:
            try:
                from endpoints.image_gen import _refine_prompt_with_llm
                final_prompt = _refine_prompt_with_llm(prompt, None, keys)
            except Exception:
                pass  # fall back to raw prompt
        
        from endpoints.image_gen import generate_image_from_prompt
        result = generate_image_from_prompt(
            prompt=final_prompt, keys=keys, model=model, input_image=input_image,
        )
        if result.get("error"):
            return json.dumps({"error": result["error"]})
        
        images = result.get("images", [])
        return json.dumps({
            "image_base64": images[0] if images else None,
            "image_count": len(images),
            "text": result.get("text", ""),
            "refined_prompt": final_prompt if better_context else None,
            "model": model,
        })

    # Build Starlette ASGI app with middleware (same pattern as docs.py)
    # lifespan → mcp.session_manager.run()
    # Starlette routes: /health + Mount("/", mcp_starlette)
    # RateLimitMiddleware → JWTAuthMiddleware
    
    return app_with_auth, mcp


def start_image_gen_mcp_server():
    """Start the Image Gen MCP server in a daemon thread."""
    # Same pattern as start_docs_mcp_server():
    # Check IMAGE_GEN_MCP_ENABLED, MCP_JWT_SECRET
    # port = int(os.getenv("IMAGE_GEN_MCP_PORT", "8107"))
    # Thread: _run() → create_image_gen_mcp_app() → uvicorn.run(host="127.0.0.1")
```

#### 7.2) `mcp_server/__init__.py` — Add import + export

After line 110 (after `from mcp_server.code_runner_mcp import start_code_runner_mcp_server`):

```python
from mcp_server.image_gen import start_image_gen_mcp_server
```

Add to `__all__` list:

```python
"start_image_gen_mcp_server",
```

Update the module docstring to include:
```
Image Gen  (port 8107)  — ``start_image_gen_mcp_server()``
```

And add env var docs:
```
IMAGE_GEN_MCP_ENABLED, IMAGE_GEN_MCP_PORT : str
    Enable/port for Image Gen MCP (defaults ``"true"`` / ``8107``).
```

#### 7.3) `server.py` — Add startup call

In the `main()` function, after the other MCP server starts (after `start_code_runner_mcp_server()`):

```python
from mcp_server import start_image_gen_mcp_server
start_image_gen_mcp_server()  # port 8107
```

### New tool in existing servers

#### 7.4) `mcp_server/prompts_actions.py` — Add `transcribe_audio`

Insert after the last tool (before the Starlette build section). This is a baseline tool (not gated by `MCP_TOOL_TIER`).

```python
    # -----------------------------------------------------------------
    # Tool 6: transcribe_audio
    # -----------------------------------------------------------------

    @mcp.tool()
    def transcribe_audio(
        user_email: str,
        audio_base64: str,
        format: str = "wav",
    ) -> str:
        """Transcribe audio to text using OpenAI Whisper API.
        
        Args:
            user_email: Email of the requesting user.
            audio_base64: Base64-encoded audio data (without data: URI prefix).
            format: Audio format — wav, mp3, webm, m4a, ogg.
        """
        import base64 as _base64
        import tempfile
        import requests as _requests
        
        keys = _get_keys()  # Uses the module-level _get_keys() helper
        api_key = keys.get("openAIKey", "")
        if not api_key:
            return json.dumps({"error": "OpenAI API key not configured."})
        
        try:
            audio_bytes = _base64.b64decode(audio_base64)
        except Exception as e:
            return json.dumps({"error": f"Invalid base64 audio data: {e}"})
        
        with tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        
        try:
            with open(tmp_path, "rb") as f:
                resp = _requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (f"audio.{format}", f, f"audio/{format}")},
                    data={"model": "whisper-1"},
                    timeout=120,
                )
            resp.raise_for_status()
            text = resp.json().get("text", "")
            return json.dumps({"text": text})
        except Exception as e:
            logger.exception("transcribe_audio error: %s", e)
            return json.dumps({"error": f"Transcription failed: {e}"})
        finally:
            import os as _os
            _os.unlink(tmp_path)
```

**Note**: `prompts_actions.py` currently lacks a `_get_keys()` helper — add one at module level, same pattern as `docs.py`:

```python
_keys_cache = None

def _get_keys():
    global _keys_cache
    if _keys_cache is None:
        from endpoints.utils import keyParser
        _keys_cache = keyParser({})
    return _keys_cache
```

#### 7.5) `mcp_server/docs.py` — Add 4 new full-tier tools

Insert inside the `if tool_tier == "full":` block, after the last existing full-tier tool (`docs_get_global_doc_full_text`).

```python
        # -------------------------------------------------------------
        # Full Tool 10: docs_delete_global
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_delete_global(user_email: str, doc_id: str) -> str:
            """Delete a global document by its doc_id.
            
            Removes the database entry and filesystem storage.
            
            Args:
                user_email: Email of the document owner.
                doc_id: The global document identifier to delete.
            """
            import shutil
            try:
                row, doc_storage = _resolve_global_doc_storage(user_email, doc_id)
                if row is None:
                    return json.dumps({"error": f"Global doc '{doc_id}' not found."})
                from database.global_docs import delete_global_doc
                delete_global_doc(users_dir=_users_dir(), user_email=user_email, doc_id=doc_id)
                if doc_storage and os.path.isdir(doc_storage):
                    shutil.rmtree(doc_storage, ignore_errors=True)
                return json.dumps({"success": True, "doc_id": doc_id})
            except Exception as exc:
                logger.exception("docs_delete_global error: %s", exc)
                return json.dumps({"error": f"Failed to delete: {exc}"})

        # -------------------------------------------------------------
        # Full Tool 11: docs_upload_global
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_upload_global(
            user_email: str,
            source: str,
            display_name: str = None,
            folder_id: str = None,
        ) -> str:
            """Upload a file or URL to the user's Global Documents library.
            
            The document is indexed (FAISS + LLM title/summary) and available
            across all conversations via #gdoc_N references.
            
            Args:
                user_email: Email of the document owner.
                source: Absolute file path on the server, or a URL to index.
                display_name: Optional human-readable name for the document.
                folder_id: Optional folder ID to organize the document into.
            """
            try:
                import hashlib, uuid
                from DocIndex import create_immediate_document_index
                from database.global_docs import add_global_doc
                
                keys = _get_keys()
                user_hash = _user_hash(user_email)
                doc_id = str(uuid.uuid4())[:12]
                storage_base = os.path.join(_users_dir(), user_hash, "global_docs")
                os.makedirs(storage_base, exist_ok=True)
                doc_storage = os.path.join(storage_base, doc_id)
                
                # Create the document index (handles both file paths and URLs)
                doc = create_immediate_document_index(
                    source=source,
                    storage_path=doc_storage,
                    keys=keys,
                )
                if doc is None:
                    return json.dumps({"error": f"Failed to index source: {source}"})
                
                # Add to database
                add_global_doc(
                    users_dir=_users_dir(),
                    user_email=user_email,
                    doc_id=doc_id,
                    doc_source=source,
                    doc_storage=doc_storage,
                    title=doc.title or display_name or source,
                    short_summary=doc.short_summary or "",
                    display_name=display_name,
                    folder_id=folder_id,
                )
                
                return json.dumps({
                    "success": True,
                    "doc_id": doc_id,
                    "title": doc.title,
                    "source": source,
                    "display_name": display_name,
                })
            except Exception as exc:
                logger.exception("docs_upload_global error: %s", exc)
                return json.dumps({"error": f"Upload failed: {exc}"})

        # -------------------------------------------------------------
        # Full Tool 12: docs_set_global_doc_tags
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_set_global_doc_tags(
            user_email: str,
            doc_id: str,
            tags: list[str],
        ) -> str:
            """Set tags on a global document (replaces all existing tags).
            
            Args:
                user_email: Email of the document owner.
                doc_id: The global document identifier.
                tags: List of tag strings, e.g. ["research", "arxiv", "2026"].
            """
            try:
                from database.doc_tags import set_tags
                set_tags(users_dir=_users_dir(), user_email=user_email, doc_id=doc_id, tags=tags)
                return json.dumps({"success": True, "doc_id": doc_id, "tags": tags})
            except Exception as exc:
                logger.exception("docs_set_global_doc_tags error: %s", exc)
                return json.dumps({"error": f"Failed to set tags: {exc}"})

        # -------------------------------------------------------------
        # Full Tool 13: docs_assign_to_folder
        # -------------------------------------------------------------

        @mcp.tool()
        def docs_assign_to_folder(
            user_email: str,
            doc_id: str,
            folder_id: str = None,
        ) -> str:
            """Assign a global document to a folder, or unassign (folder_id=null).
            
            Args:
                user_email: Email of the document owner.
                doc_id: The global document identifier.
                folder_id: Folder ID to assign to. Pass null/None to unassign.
            """
            try:
                from database.doc_folders import assign_doc_to_folder
                assign_doc_to_folder(
                    users_dir=_users_dir(), user_email=user_email,
                    doc_id=doc_id, folder_id=folder_id,
                )
                return json.dumps({"success": True, "doc_id": doc_id, "folder_id": folder_id})
            except Exception as exc:
                logger.exception("docs_assign_to_folder error: %s", exc)
                return json.dumps({"error": f"Failed to assign folder: {exc}"})
```

#### 7.6) `mcp_server/pkb.py` — Add 3 new full-tier tools

Insert inside the `if is_full:` block, after the last existing full-tier tool (`pkb_pin_claim`).

```python
        # -------------------------------------------------------------
        # Tool 11: pkb_list_contexts — list all contexts with claim counts
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_list_contexts(user_email: str, limit: int = 100) -> str:
            """List all PKB contexts with their claim counts.
            
            Contexts organize claims hierarchically. Each context has a
            friendly_id (suffixed with _context) for @-referencing in chat.
            
            Args:
                user_email: Email of the PKB owner.
                limit: Maximum number of contexts to return (default 100).
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                contexts_crud = user_api._db.contexts
                rows = contexts_crud.get_with_claim_count(user_email=user_email, limit=limit)
                results = [{
                    "id": r.get("id", ""),
                    "name": r.get("name", ""),
                    "friendly_id": r.get("friendly_id", ""),
                    "description": r.get("description", ""),
                    "parent_id": r.get("parent_context_id"),
                    "claim_count": r.get("claim_count", 0),
                } for r in rows]
                return json.dumps(results, default=str)
            except Exception as exc:
                logger.exception("pkb_list_contexts error: %s", exc)
                return json.dumps({"error": f"pkb_list_contexts failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 12: pkb_list_entities — list all entities with claim counts
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_list_entities(user_email: str, limit: int = 100) -> str:
            """List all PKB entities with types and linked claim counts.
            
            Entities represent people, organizations, or concepts linked to claims.
            Each entity has a friendly_id (suffixed with _entity) for @-referencing.
            
            Args:
                user_email: Email of the PKB owner.
                limit: Maximum number of entities to return (default 100).
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                entities_crud = user_api._db.entities
                rows = entities_crud.get_with_claim_count(user_email=user_email, limit=limit)
                results = [{
                    "id": r.get("id", ""),
                    "name": r.get("name", ""),
                    "friendly_id": r.get("friendly_id", ""),
                    "entity_type": r.get("entity_type", ""),
                    "description": r.get("description", ""),
                    "claim_count": r.get("claim_count", 0),
                } for r in rows]
                return json.dumps(results, default=str)
            except Exception as exc:
                logger.exception("pkb_list_entities error: %s", exc)
                return json.dumps({"error": f"pkb_list_entities failed: {exc}"})

        # -------------------------------------------------------------
        # Tool 13: pkb_list_tags — list all tags with claim counts
        # -------------------------------------------------------------

        @mcp.tool()
        def pkb_list_tags(user_email: str, limit: int = 100) -> str:
            """List all PKB tags with hierarchy and claim counts.
            
            Tags categorize claims and form a hierarchy. Referencing @tag_friendly_id
            resolves to all claims with that tag and descendant tags (recursive).
            
            Args:
                user_email: Email of the PKB owner.
                limit: Maximum number of tags to return (default 100).
            """
            try:
                api = _get_pkb_api()
                user_api = api.for_user(user_email)
                tags_crud = user_api._db.tags
                rows = tags_crud.get_with_claim_count(user_email=user_email, limit=limit)
                results = [{
                    "id": r.get("id", ""),
                    "name": r.get("name", ""),
                    "friendly_id": r.get("friendly_id", ""),
                    "parent_id": r.get("parent_tag_id"),
                    "claim_count": r.get("claim_count", 0),
                } for r in rows]
                return json.dumps(results, default=str)
            except Exception as exc:
                logger.exception("pkb_list_tags error: %s", exc)
                return json.dumps({"error": f"pkb_list_tags failed: {exc}"})
```

---

## 8) Implementation Plan

### Completed

- [x] **Security hardening**: All 7 MCP server bind addresses changed from `0.0.0.0` to `127.0.0.1` (6/7 done in original pass, `conversation.py` fixed 2026-03-06 in v3 plan review)

### Phase 1A: Extend existing MCP servers — new tools (1-2 days)

Each server change is independent and can be parallelized across files.

1. **`mcp_server/docs.py`** — Add 4 tools inside `if tool_tier == "full":` block
   - `docs_upload_global` — wraps `create_immediate_document_index()` + `add_global_doc()`
   - `docs_delete_global` — wraps `delete_global_doc()` + `shutil.rmtree()`
   - `docs_set_global_doc_tags` — wraps `database.doc_tags.set_tags()`
   - `docs_assign_to_folder` — wraps `database.doc_folders.assign_doc_to_folder()`

2. **`mcp_server/pkb.py`** — Add 3 tools inside `if is_full:` block
   - `pkb_list_contexts` — wraps `ContextCRUD.get_with_claim_count()` (**use corrected tuple unpacking from Section 3.5.8**)
   - `pkb_list_entities` — wraps `EntityCRUD.get_with_claim_count()` (**use corrected tuple unpacking**)
   - `pkb_list_tags` — wraps `TagCRUD.get_with_claim_count()` (**use corrected tuple unpacking**)

3. **`mcp_server/prompts_actions.py`** — Add `_get_keys()` helper + `transcribe_audio` tool

### Phase 1B: Mirror to tools.py — new handlers (1 day)

Depends on Phase 1A being complete (or can be done in parallel using the same backend function contracts).

4. **`code_common/tools.py`** — Add 8 `@register_tool` handlers (see Section 3.5 for architecture guide):
   - 3 doc write tools (after line ~1761, using `_docs_*` helpers)
   - 3 PKB list tools (after line ~2245, using `_get_pkb_api()` + **corrected tuple unpacking from Section 3.5.6**)
   - 1 `transcribe_audio` (after line ~3537, new at end of prompts section)
   - 1 `generate_image` (new section at end of file)

**Implementation order within tools.py**: Doc tools → PKB tools → Prompts tools → Image Gen tools (follows the existing section order in the file)

5. **Test each tool** both via MCP client AND via the `TOOL_REGISTRY.get_openai_tools_param()` output

### Phase 2: New Image Generation MCP (1 day)

1. Create `mcp_server/image_gen.py` with `generate_image` tool
2. Add `start_image_gen_mcp_server` import in `mcp_server/__init__.py`
3. Add `start_image_gen_mcp_server()` call in `server.py`
4. Test image generation via MCP client

**Note**: The tools.py `generate_image` handler (Phase 1B) is independent of the MCP server — it calls `endpoints.image_gen` directly, not via MCP. So Phase 1B.generate_image can proceed before Phase 2.

### Phase 3: nginx (half day)

1. Add 8 nginx location blocks for `/mcp/*` (copy-paste from Section 5)
2. `sudo nginx -t && sudo systemctl reload nginx`
3. Test all health endpoints via HTTPS
4. Test authenticated MCP call via HTTPS

### Phase 4: Local Filesystem MCP (2-3 days, deferred)

1. Create `desktop/filesystem-mcp/` Node.js project
2. Implement 10 tools with path validation
3. Implement streamable-HTTP transport (no auth)
4. Test with OpenCode locally
5. Integration with Electron spawner

### Phase 5: OpenCode config template (half day, deferred)

1. Create `opencode.json` template for desktop companion
2. Configure all 9 remote MCP servers with `https://assist-chat.site/mcp/*` URLs
3. Configure local filesystem MCP with `http://localhost:<port>/`
4. Test end-to-end: OpenCode → remote MCP → server capabilities

### Dependency graph

```
Phase 1A (MCP server tools)  ──→  Phase 3 (nginx)  ──→  Phase 5 (OpenCode config)
       │                                                         ↑
       ▼                                                         │
Phase 1B (tools.py handlers)                    Phase 4 (local FS MCP) ──┘
       │
       ▼
Phase 2 (Image Gen MCP)  ─────→  Phase 3 (nginx needs /mcp/image/ block)
```

**Phases 1A and 1B can be done in parallel** — they call the same backend functions but through different wrappers.

**Total estimated effort**: 5-7 days

---

## 9) Testing

### Remote MCP tools

For each new tool, test:
1. **Happy path**: Valid params → expected result
2. **Auth**: No token → 401. Invalid token → 401. Expired token → 401.
3. **Rate limit**: 11 rapid calls → 429 on the 11th.
4. **Error cases**: Invalid doc_id → 404. Invalid user_email → empty results.

### Main UI tools (code_common/tools.py)

For each new `@register_tool` handler:
1. **Unit test pattern**: Call `handle_<tool_name>(args_dict, mock_context)` directly
2. **Integration test**: Ensure the tool appears in `TOOL_REGISTRY.get_openai_tools_param()` output
3. **LLM invocation**: Test via conversation with tool-calling enabled — LLM should discover and invoke new tools

### Nginx proxy

1. Health check via HTTPS: `curl https://assist-chat.site/mcp/*/health`
2. Authenticated call via HTTPS: `curl -H "Authorization: Bearer $TOKEN" https://assist-chat.site/mcp/pkb/mcp`
3. Direct port access blocked: `curl http://assist-chat.site:8101/health` should fail (bound to 127.0.0.1)
4. Path stripping: `/mcp/search/mcp` → backend receives `/mcp` (not `/mcp/search/mcp`)

### Local Filesystem MCP

1. **Sandbox**: `fs_read_file("../../etc/passwd")` → error "escapes working directory"
2. **Read/write round-trip**: Write file → read file → content matches
3. **Edit**: Write file → edit (find/replace) → read file → replacement applied
4. **Glob**: Create files → glob pattern → matches expected files
5. **Grep**: Write file with content → grep regex → finds match
6. **Shell**: `fs_run_shell("echo hello")` → stdout = "hello\n"
7. **Timeout**: `fs_run_shell("sleep 300")` with timeout=1000 → timed_out = true

---

## Appendix: OpenCode Config Template

This is the `opencode.json` that the Electron app will generate/maintain in the working directory (or globally at `~/.config/opencode/config.json`):

```json
{
  "provider": {
    "openrouter": {
      "apiKey": "{env:OPENROUTER_API_KEY}"
    }
  },
  "mcp": {
    "web-search": {
      "type": "remote",
      "url": "https://assist-chat.site/mcp/search/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MCP_JWT_TOKEN}"
      },
      "enabled": true
    },
    "pkb": {
      "type": "remote",
      "url": "https://assist-chat.site/mcp/pkb/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MCP_JWT_TOKEN}"
      },
      "enabled": true
    },
    "documents": {
      "type": "remote",
      "url": "https://assist-chat.site/mcp/docs/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MCP_JWT_TOKEN}"
      },
      "enabled": true
    },
    "artefacts": {
      "type": "remote",
      "url": "https://assist-chat.site/mcp/artefacts/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MCP_JWT_TOKEN}"
      },
      "enabled": true
    },
    "conversations": {
      "type": "remote",
      "url": "https://assist-chat.site/mcp/conversations/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MCP_JWT_TOKEN}"
      },
      "enabled": true
    },
    "prompts": {
      "type": "remote",
      "url": "https://assist-chat.site/mcp/prompts/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MCP_JWT_TOKEN}"
      },
      "enabled": true
    },
    "code-runner": {
      "type": "remote",
      "url": "https://assist-chat.site/mcp/code/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MCP_JWT_TOKEN}"
      },
      "enabled": true
    },
    "image-gen": {
      "type": "remote",
      "url": "https://assist-chat.site/mcp/image/",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:MCP_JWT_TOKEN}"
      },
      "enabled": true
    },
    "filesystem": {
      "type": "remote",
      "url": "http://localhost:{FILESYSTEM_MCP_PORT}/",
      "oauth": false,
      "enabled": true
    },
    "context7": {
      "type": "local",
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"],
      "enabled": true
    },
    "pdf-reader": {
      "type": "local",
      "command": "npx",
      "args": ["-y", "@sylphx/pdf-reader-mcp@latest"],
      "enabled": true
    }
  }
}
```

The `{FILESYSTEM_MCP_PORT}` placeholder is replaced by Electron at runtime with the actual port of the local filesystem MCP server.

---

## Appendix B: Complete File Change Summary

### Files to MODIFY

| File | Changes | Lines Added | Status |
|------|---------|-------------|--------|
| `mcp_server/__init__.py` | ~~`0.0.0.0`→`127.0.0.1`~~ DONE. Add `start_image_gen_mcp_server` import + `__all__` entry + docstring | ~10 | Pending |
| `mcp_server/docs.py` | ~~`0.0.0.0`→`127.0.0.1`~~ DONE. Add 4 full-tier tools inside `if tool_tier == "full":` | ~130 | Pending |
| `mcp_server/pkb.py` | ~~`0.0.0.0`→`127.0.0.1`~~ DONE. Add 3 full-tier tools inside `if is_full:` (use corrected tuple unpacking, see 3.5.8) | ~100 | Pending |
| `mcp_server/prompts_actions.py` | ~~`0.0.0.0`→`127.0.0.1`~~ DONE. Add `_get_keys()` helper + `transcribe_audio` tool | ~60 | Pending |
| `mcp_server/artefacts.py` | ~~`0.0.0.0`→`127.0.0.1`~~ DONE. No tool changes. | 0 | Done |
| `mcp_server/conversation.py` | ~~`0.0.0.0`→`127.0.0.1`~~ DONE (v3 fix). No tool changes. | 0 | Done |
| `mcp_server/code_runner_mcp.py` | ~~`0.0.0.0`→`127.0.0.1`~~ DONE. No tool changes. | 0 | Done |
| `server.py` | Add `start_image_gen_mcp_server()` call in `main()` | ~3 | Pending |
| `code_common/tools.py` | Add 8 new `@register_tool` handlers (3 doc, 3 pkb, 1 transcribe, 1 image gen). Follow Section 3.5 conventions. | ~350 | Pending |
| `/etc/nginx/sites-enabled/science-reader` | Add 8 `/mcp/*/` location blocks | ~80 | Pending |

### Files to CREATE

| File | Purpose | Lines | Status |
|------|---------|-------|--------|
| `mcp_server/image_gen.py` | New Image Gen MCP server (port 8107) | ~150 | Pending |

### Total new code: ~900 lines across 4 modified files + 1 new file

---

*End of MCP Expansion Plan v3*
