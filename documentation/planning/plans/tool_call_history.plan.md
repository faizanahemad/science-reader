# Tool Call History & Result Caching

**Status: IMPLEMENTED** (March 2026)

All 8 tasks completed. Files created/modified:
- `code_common/tool_call_history.py` (NEW — 725 lines)
- `Conversation.py` (recording hooks at 2 insertion points in `_run_tool_loop`)
- `mcp_server/mcp_app.py` (thread-local, recording helper, 4 existing tool wrappers, 4 new MCP tools)
- `code_common/tools.py` (4 new `@register_tool` handlers)
- `interface/interface.html` (4 new options in Conversation optgroup)
- `interface/chat.js` (4 new tools in `categoryDefaults.conversation`)
- Documentation files updated

## Motivation and Background

Currently, tool call results are **ephemeral**. When the LLM invokes a tool (e.g. `web_search`, `perplexity_search`, `read_link`), the result text exists only in a local `messages` list during `_run_tool_loop`, is fed back to the LLM for synthesis, and is then **discarded**. The `<tool_calls_summary>` block shown to the user is explicitly stripped before persistence (Conversation.py lines 3836-3848). Only minimal timing metadata survives in `time_dict.tool_calls` (tool name, duration, result char count — no actual content).

This means:
- The LLM cannot reference results from prior tool calls in previous turns or conversations.
- Identical searches are re-executed every time (e.g. user asks the same question across conversations).
- MCP tool calls are completely stateless — no history at all.
- Users cannot browse or audit what tools were called and what they returned.

### Goals

1. **Persist all tool call inputs and results** across both the tool-calling framework (in-chat) and MCP server.
2. **Expose four new tools** in both surfaces (tool-calling + MCP) so the LLM and MCP clients can query history — split into two pairs for search/page visits (high-frequency) and general tool calls (all categories).
3. **Enable implicit result caching** — the LLM can check if a recent identical search exists before re-executing.
4. **Cover all tool categories** (search, docs, PKB, memory, artefacts, prompts, conversation, code runner) — not just search.

### Non-Goals

- Automatic transparent caching (skipping execution if a cache hit exists). The LLM or MCP client decides whether to reuse a previous result.
- UI for browsing tool call history (future enhancement).
- Cross-user result sharing.

## Requirements

### Functional

- R1: Every tool call executed via `_run_tool_loop` (tool-calling framework) is recorded with: unique ID, tool name, full args, full result text, error (if any), user email, conversation ID, timestamp, duration, result char count, source ("tool_calling"), and a `tool_category` field (e.g. "search", "documents", "pkb").
- R2: Every tool call executed via MCP server tools is recorded with the same fields, except `conversation_id` is NULL and source is "mcp".
- R3: Four query tools are exposed (both in tool-calling and MCP):

| Tool | Purpose | Scope |
|---|---|---|
| `list_search_history` | List previous web searches and page reads with metadata | `search` category tools only (`web_search`, `perplexity_search`, `jina_search`, `jina_read_page`, `read_link`) |
| `get_search_results` | Get full result text for a list of search/page-read call IDs | `search` category results only |
| `list_tool_call_history` | List previous tool calls with metadata (all categories) | All tool categories |
| `get_tool_call_results` | Get full result text for a list of tool call IDs (any category) | All tool categories |

- R4: All list tools return metadata (ID, tool name, args summary, result length, duration, timestamp) with optional filters: tool name, conversation scope, time range, limit.
- R5: All get tools return full result text for given IDs.
- R6: Tool call IDs are deterministic hashes of `(tool_name, canonical_args_json)` so identical calls produce the same ID (enabling dedup/caching lookups).
- R7: Data is scoped per user (user_email). Users cannot see other users' tool call history.
- R8: Old records are automatically pruned (configurable max age, default 30 days; configurable max rows per user, default 10000).

### Non-Functional

- NR1: Recording must not noticeably slow down tool execution (< 5ms overhead per write).
- NR2: Storage must handle large result texts (up to 50,000 chars per result, the existing truncation limit).
- NR3: Must not break existing behavior when the history DB is unavailable (fail-open).

## Architecture

### Storage: Shared SQLite Database with Per-User Scoping

The project uses a **single shared `users.db`** SQLite file in `storage/users/` for all user-scoped data. Every table has a `user_email` column for scoping — this is the universal pattern used by:
- `database/users.py` — `UserDetails` table (path: `storage/users/users.db`)
- `database/global_docs.py` — `GlobalDocuments` table (same `users.db`)
- `database/conversations.py` — `UserToConversationId` table (same `users.db`)
- `database/doc_folders.py` — `GlobalDocFolders` table (same `users.db`)
- `database/search_index.py` — separate `storage/users/search_index.db` (but same shared pattern)
- `endpoints/pkb.py` — separate `storage/users/pkb.sqlite` (same shared pattern)

Tool call history follows this pattern with its own separate SQLite file:

```
storage/users/tool_call_history.sqlite
```

**Why a separate file (not adding a table to `users.db`)**: Tool call history has very different access patterns — high write frequency, large TEXT blobs (up to 50K chars), aggressive pruning. Keeping it in a separate file avoids bloating `users.db` and allows independent VACUUM/maintenance. This matches the precedent of `pkb.sqlite` and `search_index.db` — both are per-feature SQLite files in the same `storage/users/` directory, all sharing the `user_email` column pattern.

**Why not per-user separate files**: The project never uses per-user directories. All user data goes into shared databases with `user_email` WHERE clauses. Following the existing convention.

**Why not per-conversation `store_separate`**: MCP calls have no conversation context. Cross-conversation queries would require scanning all conversations. SQLite with indexes is much more efficient.

### Schema

```sql
CREATE TABLE IF NOT EXISTS tool_call_history (
    id TEXT NOT NULL,                      -- hash of (tool_name, canonical_args)
    tool_name TEXT NOT NULL,
    tool_category TEXT NOT NULL,            -- e.g. "search", "documents", "pkb", "memory"
    args_json TEXT NOT NULL,               -- full JSON args
    result_text TEXT,                       -- full result (NULL on error-only)
    error TEXT,                            -- error message if failed, NULL on success
    user_email TEXT NOT NULL,
    conversation_id TEXT,                   -- NULL for MCP calls
    timestamp REAL NOT NULL,               -- time.time() epoch
    duration_seconds REAL,
    result_chars INTEGER,
    source TEXT NOT NULL DEFAULT 'tool_calling',  -- 'tool_calling' or 'mcp'
    PRIMARY KEY (id, timestamp)            -- same ID can appear multiple times (re-executions)
);

CREATE INDEX IF NOT EXISTS idx_tch_user ON tool_call_history(user_email);
CREATE INDEX IF NOT EXISTS idx_tch_tool ON tool_call_history(tool_name);
CREATE INDEX IF NOT EXISTS idx_tch_category ON tool_call_history(tool_category);
CREATE INDEX IF NOT EXISTS idx_tch_ts ON tool_call_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_tch_conv ON tool_call_history(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tch_id ON tool_call_history(id);
-- Composite index for the most common query pattern (user + category + time)
CREATE INDEX IF NOT EXISTS idx_tch_user_cat_ts ON tool_call_history(user_email, tool_category, timestamp DESC);
```

**Composite primary key `(id, timestamp)`**: The same tool with the same args can be called multiple times. Each execution is a separate row. The `id` enables dedup lookups ("has this exact call been made recently?") while `timestamp` ensures uniqueness.

**`tool_category` column**: Enables the search-specific tools (`list_search_history`, `get_search_results`) to filter efficiently without checking tool names. The category is already known from `ToolDefinition.category` in the registry.

### ID Generation

```python
import hashlib, json

def tool_call_hash(tool_name: str, args: dict) -> str:
    """Deterministic hash of tool name + canonical args."""
    canonical = json.dumps(args, sort_keys=True, ensure_ascii=False)
    raw = f"{tool_name}:{canonical}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

16-char hex = 64 bits of entropy. Collision probability is negligible for the expected volume.

### Tool Category Resolution

When recording, we need the tool's category. The `TOOL_REGISTRY` singleton already tracks categories:

```python
def get_tool_category(tool_name: str) -> str:
    """Get tool category from the registry, or 'unknown'."""
    tool_def = TOOL_REGISTRY.get_tool(tool_name)
    return tool_def.category if tool_def else "unknown"
```

For MCP tools (not in TOOL_REGISTRY), hardcode the category in `_record_mcp_tool_call()` since MCP only has search tools currently.

### Search vs All: How the 4 Tools Relate

```
┌─────────────────────────────────────────────────────────┐
│            tool_call_history table                       │
│                                                         │
│  ┌─────────────────────┐  ┌──────────────────────────┐  │
│  │ tool_category =     │  │ tool_category =          │  │
│  │   "search"          │  │   everything else        │  │
│  │                     │  │   (docs, pkb, memory,    │  │
│  │ list_search_history │  │    artefacts, ...)       │  │
│  │ get_search_results  │  │                          │  │
│  └─────────────────────┘  └──────────────────────────┘  │
│                                                         │
│  list_tool_call_history  ← queries ALL rows             │
│  get_tool_call_results   ← queries ALL rows             │
└─────────────────────────────────────────────────────────┘
```

The search pair (`list_search_history` / `get_search_results`) is a **convenience subset** — it queries the same table but with `WHERE tool_category = 'search'` hardcoded. This makes it cheaper for the LLM to use (fewer irrelevant results, shorter descriptions) and semantically clearer ("find my previous web searches" vs "find any previous tool call").

The general pair (`list_tool_call_history` / `get_tool_call_results`) queries **all categories** and accepts an optional `tool_category_filter` param. These are the superset.

## Implementation Plan

### Task 1: Storage Module (`code_common/tool_call_history.py`) — NEW FILE

Create a self-contained module with:

1. **`ToolCallHistoryDB` class** — manages the SQLite connection and provides CRUD methods:
   - `__init__(db_path)` — opens/creates the DB, runs `CREATE TABLE IF NOT EXISTS` and all indexes. Sets `PRAGMA journal_mode=WAL` for concurrent access. Uses `check_same_thread=False`.
   - `record(id, tool_name, tool_category, args_json, result_text, error, user_email, conversation_id, timestamp, duration_seconds, result_chars, source)` — INSERT a record. Fail-open (catch and log exceptions, never raise).
   - `list_calls(user_email, tool_category=None, tool_name=None, conversation_id=None, since=None, until=None, limit=50)` — SELECT metadata rows (id, tool_name, tool_category, args_json, result_chars, duration_seconds, timestamp, conversation_id, source — **no result_text** for efficiency). Returns list of dicts ordered by timestamp DESC.
   - `get_results(user_email, ids)` — SELECT full rows (including result_text) for given IDs. User-scoped: only returns rows matching the user_email. Returns list of dicts.
   - `prune(max_age_days=30, max_rows_per_user=10000)` — DELETE old rows. Two passes: (1) delete rows older than max_age_days, (2) for each user, delete rows beyond max_rows_per_user keeping newest. Returns count deleted.

2. **`tool_call_hash(tool_name, args)` function** — generates the deterministic ID.

3. **`get_tool_category(tool_name)` function** — looks up category from TOOL_REGISTRY, defaults to "unknown".

4. **Module-level singleton** `_db_instance` with `get_tool_call_history_db()` function (lazy init, following the PKB pattern from `endpoints/pkb.py:get_pkb_db`).

5. **`TOOL_HISTORY_TOOLS` dict** — shared tool metadata for all 4 tools (following the `CONVERSATION_TOOLS` pattern from `code_common/conversation_search.py`).

**DB path**: `os.path.join(os.environ.get("STORAGE_DIR", "storage"), "users", "tool_call_history.sqlite")`

**Thread safety**: Use `check_same_thread=False` on the SQLite connection. WAL mode allows concurrent reads + serialized writes — adequate for the expected concurrency (ThreadPoolExecutor parallel tool execution in `_run_tool_loop`).

**File**: `code_common/tool_call_history.py`
**Dependencies**: Standard library only (`sqlite3`, `hashlib`, `json`, `time`, `os`). Plus `loggers.py` for logging. Lazy import of `TOOL_REGISTRY` to avoid circular dependencies.

### Task 2: Recording Hook in Tool-Calling Framework (`Conversation.py`)

**Insertion point**: Conversation.py line ~7113, immediately after:
```python
messages.append({
    "role": "tool",
    "tool_call_id": tc_id,
    "content": tool_result_text,
})
```

Add:
```python
# Record tool call to history (fail-open)
try:
    from code_common.tool_call_history import get_tool_call_history_db, tool_call_hash, get_tool_category
    _tch_db = get_tool_call_history_db()
    if _tch_db:
        _tch_db.record(
            id=tool_call_hash(tc_name, tc_args),
            tool_name=tc_name,
            tool_category=get_tool_category(tc_name),
            args_json=json.dumps(tc_args, ensure_ascii=False),
            result_text=tool_result_text,
            error=result.error if hasattr(result, 'error') else None,
            user_email=tool_context.user_email,
            conversation_id=tool_context.conversation_id,
            timestamp=time.time(),
            duration_seconds=tool_total_duration,
            result_chars=result_len,
            source='tool_calling',
        )
except Exception:
    pass  # Fail-open: never break tool execution for history recording
```

**Variables available at this point** (verified from Conversation.py lines 7050-7113):
- `tc_name` — tool name (str)
- `tc_args` — parsed args dict
- `tc_id` — tool call ID from API
- `tool_result_text` — full result text (str)
- `tool_total_duration` — float seconds
- `result_len` — len(tool_result_text)
- `tool_context` — ToolContext with `.user_email` and `.conversation_id`
- `result` — ToolCallResult with `.error`
- `time` and `json` already imported

**File**: `Conversation.py`
**Lines modified**: ~7113 (insert after existing `messages.append`)

### Task 3: Recording Hook in MCP Server (`mcp_server/mcp_app.py`)

MCP tools are sync functions returning `str`, called by the FastMCP SDK in a thread pool. They don't have direct access to the ASGI scope (which contains the user email from JWT).

**Approach**: Use `threading.local()` to pass user_email from the auth middleware to the tool functions.

```python
import threading
_mcp_request_context = threading.local()
```

In `JWTAuthMiddleware.__call__`, after line 102 (where `scope["mcp_client_email"]` is set):
```python
_mcp_request_context.user_email = payload.get("email", "unknown")
```

Helper function:
```python
def _record_mcp_tool_call(tool_name: str, tool_category: str, args_dict: dict, result_text: str, duration: float):
    """Record an MCP tool call to history. Fail-open."""
    try:
        from code_common.tool_call_history import get_tool_call_history_db, tool_call_hash
        db = get_tool_call_history_db()
        if db:
            user_email = getattr(_mcp_request_context, 'user_email', 'unknown')
            is_error = result_text.startswith("Search failed:") or result_text.startswith("Error")
            db.record(
                id=tool_call_hash(tool_name, args_dict),
                tool_name=tool_name,
                tool_category=tool_category,
                args_json=json.dumps(args_dict, ensure_ascii=False),
                result_text=result_text,
                error=result_text if is_error else None,
                user_email=user_email,
                conversation_id=None,
                timestamp=time.time(),
                duration_seconds=duration,
                result_chars=len(result_text),
                source='mcp',
            )
    except Exception:
        pass
```

Then in each of the 4 existing MCP tool functions, wrap the return:
```python
# Example for perplexity_search:
start = time.time()
result = _collect_agent_output(agent, agent_input)
_record_mcp_tool_call(
    "perplexity_search", "search",
    {"query": query, "context": context, "detail_level": detail_level},
    result, time.time() - start
)
return result
```

**Files**: `mcp_server/mcp_app.py`
**Lines modified**: JWTAuthMiddleware.__call__ (~line 102), new `_mcp_request_context` and `_record_mcp_tool_call`, each of the 4 tool functions (`perplexity_search`, `jina_search`, `jina_read_page`, `read_link`).

### Task 4: Tool-Calling Framework — 4 Tool Handlers (`code_common/tools.py`)

Add four new tool handlers at the end of the conversation tools section (after the existing `_conv_tool_kwargs` pattern at line ~2796):

```python
from code_common.tool_call_history import TOOL_HISTORY_TOOLS

def _history_tool_kwargs(tool_name: str) -> dict:
    """Return TOOL_HISTORY_TOOLS[tool_name] kwargs suitable for register_tool."""
    return {k: v for k, v in TOOL_HISTORY_TOOLS[tool_name].items()
            if k in ('name', 'description', 'parameters', 'is_interactive', 'category')}
```

#### Tool 1: `list_search_history`

```python
@register_tool(**_history_tool_kwargs("list_search_history"))
def handle_list_search_history(args: dict, context: ToolContext) -> ToolCallResult:
    """List previous web searches and page reads."""
```

- Params: `query_contains` (optional str — substring match on args_json), `conversation_only` (bool, default False), `limit` (int, default 20), `since_hours` (float, optional)
- Calls `db.list_calls(user_email, tool_category="search", ...)`
- Returns JSON array of metadata dicts (no full result_text). Each dict includes: `id`, `tool_name`, `args_summary` (truncated args_json), `result_chars`, `duration_seconds`, `timestamp`, `conversation_id`, `source`.

#### Tool 2: `get_search_results`

```python
@register_tool(**_history_tool_kwargs("get_search_results"))
def handle_get_search_results(args: dict, context: ToolContext) -> ToolCallResult:
    """Get full result text of previous search/page-read calls by ID."""
```

- Params: `ids` (required array of strings)
- Calls `db.get_results(user_email, ids)` — internally also filters `tool_category='search'` for safety
- Returns JSON array with full result_text per ID

#### Tool 3: `list_tool_call_history`

```python
@register_tool(**_history_tool_kwargs("list_tool_call_history"))
def handle_list_tool_call_history(args: dict, context: ToolContext) -> ToolCallResult:
    """List previous tool calls across all categories."""
```

- Params: `tool_name_filter` (optional str), `tool_category_filter` (optional str), `conversation_only` (bool, default False), `limit` (int, default 20), `since_hours` (float, optional)
- Calls `db.list_calls(user_email, tool_category=filter, tool_name=filter, ...)`
- Returns JSON array of metadata dicts

#### Tool 4: `get_tool_call_results`

```python
@register_tool(**_history_tool_kwargs("get_tool_call_results"))
def handle_get_tool_call_results(args: dict, context: ToolContext) -> ToolCallResult:
    """Get full result text of previous tool calls by ID (any category)."""
```

- Params: `ids` (required array of strings)
- Calls `db.get_results(user_email, ids)` — no category filter
- Returns JSON array with full result_text per ID

**File**: `code_common/tools.py`
**Lines modified**: End of file (append four new tool registrations + handler functions)

### Task 5: MCP Server — 4 Tool Handlers (`mcp_server/mcp_app.py`)

Add four new `@mcp.tool()` functions in `create_mcp_app()`, after the existing 4 search tools:

```python
@mcp.tool()
def list_search_history(
    query_contains: str = "",
    limit: int = 20,
    since_hours: float = 0,
) -> str:
    """List previous web searches and page reads with metadata.
    Returns ID, tool name, args summary, result size, duration, timestamp.
    Use get_search_results with the IDs to retrieve full results."""
    from code_common.tool_call_history import get_tool_call_history_db
    db = get_tool_call_history_db()
    if not db:
        return "Tool call history unavailable."
    user_email = getattr(_mcp_request_context, 'user_email', 'unknown')
    rows = db.list_calls(user_email, tool_category="search", limit=limit,
                          since=time.time() - since_hours * 3600 if since_hours else None)
    if query_contains:
        rows = [r for r in rows if query_contains.lower() in r.get("args_json", "").lower()]
    return json.dumps(rows, default=str)

@mcp.tool()
def get_search_results(ids: list[str]) -> str:
    """Get full result text of previous search/page-read calls by their IDs.
    Use list_search_history first to find IDs."""
    ...

@mcp.tool()
def list_tool_call_history(
    tool_name_filter: str = "",
    tool_category_filter: str = "",
    limit: int = 20,
    since_hours: float = 0,
) -> str:
    """List previous tool calls across all categories.
    Returns ID, tool name, category, args summary, result size, duration, timestamp.
    Use get_tool_call_results with the IDs to retrieve full results."""
    ...

@mcp.tool()
def get_tool_call_results(ids: list[str]) -> str:
    """Get full result text of previous tool calls by their IDs (any category).
    Use list_tool_call_history first to find IDs."""
    ...
```

**File**: `mcp_server/mcp_app.py`
**Lines modified**: Inside `create_mcp_app()`, after the `read_link` tool definition (~line 493).

### Task 6: Frontend UI Updates

#### 6a. HTML: Add options to Conversation optgroup (`interface/interface.html`)

Add four `<option>` elements inside the `<optgroup label="Conversation">` block (after line 2480):

```html
<option value="list_search_history">List Search History</option>
<option value="get_search_results">Get Search Results</option>
<option value="list_tool_call_history">List Tool Call History</option>
<option value="get_tool_call_results">Get Tool Call Results</option>
```

#### 6b. JavaScript: Update categoryDefaults (`interface/chat.js`)

Add the four tool names to the `conversation` array in `categoryDefaults` (line 686):

```javascript
conversation: ['search_messages', 'list_messages', 'read_message', 'get_conversation_details', 'get_conversation_memory_pad', 'search_conversations', 'list_user_conversations', 'get_conversation_summary', 'list_search_history', 'get_search_results', 'list_tool_call_history', 'get_tool_call_results'],
```

**Files**: `interface/interface.html`, `interface/chat.js`

### Task 7: Auto-Pruning

Add a startup pruning call (following the PKB pattern at `endpoints/pkb.py` lines 131-136 which prunes stale claims on startup):

In `code_common/tool_call_history.py`'s `get_tool_call_history_db()`, after first initialization:

```python
if _db_instance is None:
    _db_instance = ToolCallHistoryDB(db_path)
    # Prune old records on startup
    try:
        pruned = _db_instance.prune(max_age_days=30, max_rows_per_user=10000)
        if pruned > 0:
            logger.info(f"Pruned {pruned} old tool call history records")
    except Exception:
        pass
```

### Task 8: Documentation

Update `documentation/features/tool_calling/README.md`:
- Add all 4 tools to the conversation tools inventory table
- Update "Key numbers" line (53 tools → 57 tools)
- Document the tool call history storage mechanism (schema, ID generation, pruning)
- Add implementation note about the recording hooks and dedup IDs
- Add the tools to the Tool Inventory section with parameter descriptions

Update `documentation/features/mcp_web_search_server/README.md`:
- Add 4 new MCP tools to the tools list with parameter tables
- Note that all MCP calls are now recorded to history
- Update the architecture diagram to show 8 tools (4 search + 4 history)

**No new documentation files** — extend existing docs.

## Task Breakdown

| # | Task | Files | Effort | Dependencies |
|---|---|---|---|---|
| 1 | Storage module (ToolCallHistoryDB, schema, hash, singleton, TOOL_HISTORY_TOOLS metadata) | `code_common/tool_call_history.py` (NEW) | Medium | None |
| 2 | Recording hook in tool-calling framework | `Conversation.py` (~line 7113) | Small | Task 1 |
| 3 | Recording hook in MCP server (thread-local + helper + 4 tool wrappers) | `mcp_server/mcp_app.py` | Small | Task 1 |
| 4 | Tool-calling framework handlers (4 tools) | `code_common/tools.py` | Medium | Task 1 |
| 5 | MCP server tool handlers (4 tools) | `mcp_server/mcp_app.py` | Small | Task 1 |
| 6 | Frontend UI updates (HTML + JS) | `interface/interface.html`, `interface/chat.js` | Trivial | Task 4 |
| 7 | Auto-pruning on startup | `code_common/tool_call_history.py` | Trivial | Task 1 |
| 8 | Documentation updates | `documentation/features/tool_calling/README.md`, `documentation/features/mcp_web_search_server/README.md` | Small | Tasks 4, 5 |

**Suggested execution order**: 1 → 2+3 (parallel) → 4+5 (parallel) → 6 → 7 → 8

**Total estimated effort**: Medium. Task 1 (storage module + metadata) is the bulk. Tasks 2-3 are small recording hooks. Tasks 4-5 are mechanical handler implementations following existing patterns. Task 6-8 are trivial/small.

## Detailed Tool Definitions

### `list_search_history`

**Description** (LLM-facing): "List previous web searches and page reads from this session and past conversations. Returns metadata including a unique ID for each call, the tool used, search query/URL, result size, duration, and timestamp. Use this to check if a similar search was already performed before making a new one. Use get_search_results with the returned IDs to retrieve full results without re-executing the search."

**Parameters**:
```json
{
  "type": "object",
  "properties": {
    "query_contains": {
      "type": "string",
      "description": "Filter to searches whose args contain this substring (case-insensitive). E.g. 'quantum' to find searches about quantum computing."
    },
    "conversation_only": {
      "type": "boolean",
      "description": "If true, only show searches from the current conversation. Default false (all conversations).",
      "default": false
    },
    "limit": {
      "type": "integer",
      "description": "Maximum results to return (default 20, max 100).",
      "default": 20
    },
    "since_hours": {
      "type": "number",
      "description": "Only show searches from the last N hours. Omit for no time filter."
    }
  }
}
```

### `get_search_results`

**Description**: "Get the full result text of previous web searches or page reads by their IDs. Use list_search_history first to find relevant IDs. This avoids re-executing expensive searches when the same information was already fetched."

**Parameters**:
```json
{
  "type": "object",
  "properties": {
    "ids": {
      "type": "array",
      "items": {"type": "string"},
      "description": "List of tool call IDs from list_search_history results.",
      "minItems": 1,
      "maxItems": 10
    }
  },
  "required": ["ids"]
}
```

### `list_tool_call_history`

**Description**: "List previous tool calls across all categories (search, documents, PKB, memory, artefacts, etc.). Returns metadata for each call. Use get_tool_call_results with the returned IDs to retrieve full results."

**Parameters**:
```json
{
  "type": "object",
  "properties": {
    "tool_name_filter": {
      "type": "string",
      "description": "Filter by exact tool name (e.g. 'pkb_search', 'document_lookup')."
    },
    "tool_category_filter": {
      "type": "string",
      "description": "Filter by category: search, documents, pkb, memory, artefacts, prompts, conversation, code_runner, clarification."
    },
    "conversation_only": {
      "type": "boolean",
      "description": "If true, only show calls from the current conversation.",
      "default": false
    },
    "limit": {
      "type": "integer",
      "description": "Maximum results to return (default 20, max 100).",
      "default": 20
    },
    "since_hours": {
      "type": "number",
      "description": "Only show calls from the last N hours."
    }
  }
}
```

### `get_tool_call_results`

**Description**: "Get the full result text of previous tool calls by their IDs (any category). Use list_tool_call_history first to find IDs."

**Parameters**:
```json
{
  "type": "object",
  "properties": {
    "ids": {
      "type": "array",
      "items": {"type": "string"},
      "description": "List of tool call IDs from list_tool_call_history results.",
      "minItems": 1,
      "maxItems": 10
    }
  },
  "required": ["ids"]
}
```

## Alternatives Considered

### A. Per-conversation `store_separate` instead of SQLite

Rejected: MCP calls have no conversation context. Cross-conversation queries would require loading every conversation. The existing `store_separate` mechanism stores JSON blobs in the conversation folder — not suitable for indexed queries across conversations.

### B. In-memory cache only (no persistence)

Rejected: Would not survive server restarts. The main value is in cross-session and cross-conversation history.

### C. Adding a table to `users.db` instead of a separate file

Rejected: Tool call history has high write frequency and large TEXT blobs. Keeping it separate avoids bloating `users.db`, allows independent VACUUM, and follows the precedent of `pkb.sqlite` and `search_index.db`.

### D. Two tools instead of four (no search/general split)

Rejected by user preference: Search and page visits are the most frequent tool calls and the most likely to be re-queried. Having dedicated search history tools means the LLM doesn't need to sift through PKB, memory, and document tool calls when looking for a previous web search. The search pair is a convenience fast-path; the general pair covers everything.

### E. Record in `ToolRegistry.execute()` instead of `_run_tool_loop`

Considered: Would capture all tool calls at a lower level. However, `ToolRegistry.execute()` doesn't have access to the full timing (including user wait time for interactive tools) or the final `tool_result_text` (which may differ from `result.result` for interactive tools where user responses override). Recording in `_run_tool_loop` captures the final result that was actually fed back to the LLM.

### F. Transparent caching (auto-skip execution on cache hit)

Not rejected but deferred: Could be added later as an enhancement. The current design enables it — the LLM can call `list_search_history` to check for recent results before calling the actual search tool. A future "cache layer" could intercept in `ToolRegistry.execute()` and check the history DB automatically, but this requires careful cache invalidation logic (how stale is too stale for a web search? for a PKB query?). Letting the LLM decide is simpler and more flexible.

## Possible Challenges

1. **SQLite write contention**: Multiple concurrent tool executions in `ThreadPoolExecutor` (Conversation.py uses parallel execution for non-interactive tools) could cause `SQLITE_BUSY`. Mitigation: WAL mode (`PRAGMA journal_mode=WAL`) allows concurrent reads and serialized writes without blocking. Add a retry with `PRAGMA busy_timeout=5000` (5-second timeout on lock contention).

2. **Large result storage**: Tool results can be up to 50,000 chars each. With 10,000 rows per user, worst case is ~500MB per user. Mitigation: The 30-day pruning + 10,000-row cap keeps this bounded. Could add a per-result size cap (e.g. 100K chars) as a safety net.

3. **MCP user identification**: MCP tools run as sync functions in a thread pool. ASGI middleware sets `scope["mcp_client_email"]` but this isn't directly accessible from the tool function. Mitigation: Use `threading.local()` (described in Task 3) — the auth middleware sets it, and since the SDK runs sync tools in the same thread that handled the HTTP request, the thread-local is available.

4. **Hash collisions**: 16-char hex (64 bits) has a birthday collision probability of ~1 in 2^32 at 2^16 records. For 10,000 records, collision probability is negligible (~10^-6). If concerned, increase to 24 chars.

5. **Category for new/unknown tools**: If a new tool is registered but not yet in the TOOL_REGISTRY when the category is looked up, it falls back to "unknown". This is acceptable — the tool will still be recorded and queryable via `list_tool_call_history`.

## Files Modified and Created

| File | Type | Description |
|---|---|---|
| `code_common/tool_call_history.py` | **New** | Storage module: `ToolCallHistoryDB` class, schema, `tool_call_hash()`, `get_tool_category()`, `TOOL_HISTORY_TOOLS` metadata (4 tools), singleton `get_tool_call_history_db()`, startup pruning |
| `Conversation.py` | Modified | Recording hook after line ~7113 in `_run_tool_loop` (~15 lines inserted) |
| `mcp_server/mcp_app.py` | Modified | `_mcp_request_context` thread-local, `_record_mcp_tool_call` helper, recording calls in 4 existing tools, 4 new `@mcp.tool()` functions |
| `code_common/tools.py` | Modified | 4 new `@register_tool` handlers + `_history_tool_kwargs` helper at end of conversation section |
| `interface/interface.html` | Modified | 4 new `<option>` elements in Conversation `<optgroup>` |
| `interface/chat.js` | Modified | 4 new tool names in `categoryDefaults.conversation` array |
| `documentation/features/tool_calling/README.md` | Modified | Document 4 new tools, history mechanism, updated tool count |
| `documentation/features/mcp_web_search_server/README.md` | Modified | Document 4 new MCP tools, recording behavior |
