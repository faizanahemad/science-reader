# Cross-Conversation Search — Implementation Plan

## Motivation & Background

Users accumulate hundreds of conversations over time. Today, per-conversation search exists (BM25 + text/regex via `MessageSearchIndex` in `code_common/conversation_search.py`), but there is **no way to search across conversations** — you must remember which conversation had the information you need and then search within it.

Cross-conversation search solves: "Where did I discuss JWT token expiry?", "Find all conversations about database migration", "What was that Python snippet I worked on last week?"

**Prior art in the codebase:**
- Per-conversation BM25 index (`message_search_index.json` per conversation folder)
- Cross-conversation *references* (`@conversation_<fid>_message_<hash>`) — linking, not searching
- PKB/TMS has FTS5 + embeddings — but only for claims/entities, not messages
- SQLite DB with `user_email → conversation_id → workspace_id` mappings
- Conversation metadata: title, running_summary, domain, workspace, flag, last_updated, conversation_friendly_id

---

## Goals

1. **LLM tool + MCP tools** — Three tools: `search_conversations`, `list_user_conversations`, `get_conversation_summary`
2. **UI modal** — Sidebar magnifying glass icon → search modal with debounced input → filtered conversation results → click to open
3. **SQLite FTS5 index** — Separate `search_index.db` file, real-time incremental updates, supports keyword + phrase + regex
4. **Extensible** — Architecture allows future addition of embedding-based semantic search

---

## Architecture Overview

```
                    ┌─────────────────────────────────────────────┐
                    │              search_index.db                │
                    │  ┌──────────────────────────────────────┐   │
                    │  │ ConversationSearchMeta (FTS5)        │   │
                    │  │  conversation_id UNINDEXED           │   │
                    │  │  user_email UNINDEXED                │   │
                    │  │  title                               │   │
                    │  │  summary                             │   │
                    │  │  memory_pad                          │   │
                    │  │  message_tldrs                       │   │
                    │  └──────────────────────────────────────┘   │
                    │  ┌──────────────────────────────────────┐   │
                    │  │ ConversationSearchMessages (FTS5)    │   │
                    │  │  conversation_id UNINDEXED           │   │
                    │  │  user_email UNINDEXED                │   │
                    │  │  chunk_index UNINDEXED               │   │
                    │  │  message_ids UNINDEXED               │   │
                    │  │  headers_and_bold                    │   │
                    │  │  tldrs                               │   │
                    │  └──────────────────────────────────────┘   │
                    │  ┌──────────────────────────────────────┐   │
                    │  │ ConversationSearchState (regular)     │   │
                    │  │  conversation_id TEXT PK             │   │
                    │  │  user_email TEXT                     │   │
                    │  │  title TEXT                          │   │
                    │  │  last_updated TEXT                   │   │
                    │  │  domain TEXT                         │   │
                    │  │  workspace_id TEXT                   │   │
                    │  │  flag TEXT                           │   │
                    │  │  message_count INTEGER               │   │
                    │  │  indexed_message_count INTEGER       │   │
                    │  │  created_at TEXT                     │   │
                    │  │  updated_at TEXT                     │   │
                    │  │  friendly_id TEXT                    │   │
                    │  └──────────────────────────────────────┘   │
                    └─────────────────────────────────────────────┘
```

**Three tables:**

1. **`ConversationSearchMeta`** (FTS5 virtual table) — One row per conversation. Contains title, latest running_summary, memory_pad text, and concatenated answer_tldrs from all model messages. Tokenized with `porter unicode61`. This is the **fast path** — searched first.

2. **`ConversationSearchMessages`** (FTS5 virtual table) — One row per ~10 messages (chunked). Contains extracted markdown headers + bold text + TLDRs from those messages. This is the **deep path** — searched when fast path has insufficient results or user explicitly requests deep search.

3. **`ConversationSearchState`** (regular table) — One row per conversation. Stores filterable metadata (workspace_id, domain, flag, date range, message counts) plus `indexed_message_count` to track incremental indexing progress. This table supports the `list_user_conversations` tool and filter operations.

**Why separate tables for meta vs messages?**
- Meta FTS5 searches title+summary: small, fast, covers 80% of queries
- Message FTS5 searches headers+bold+tldrs from messages: larger, more granular
- Regular state table supports SQL WHERE filtering (workspace, date, flag) before FTS
- Column weighting: `bm25(ConversationSearchMeta, 0, 0, 3.0, 2.0, 1.0, 1.5)` weights title highest

---

## Detailed Design

### 1. Database — `search_index.db`

**Location:** `{users_dir}/search_index.db` (alongside `users.db`)

**Connection management:** New module `database/search_index.py` with:
- `create_search_tables(users_dir)` — called from `create_tables()` in `database/connection.py`
- `get_search_connection(users_dir)` — returns connection with WAL mode enabled, REGEXP function registered
- All helper functions follow existing pattern: get connection → cursor → execute → commit → close in finally

**FTS5 table DDL:**

```sql
-- Fast path: conversation-level metadata search
CREATE VIRTUAL TABLE IF NOT EXISTS ConversationSearchMeta USING fts5(
    conversation_id UNINDEXED,
    user_email UNINDEXED,
    title,
    summary,
    memory_pad,
    message_tldrs,
    tokenize='porter unicode61'
);

-- Deep path: message-level content search (chunked, ~10 messages per row)
CREATE VIRTUAL TABLE IF NOT EXISTS ConversationSearchMessages USING fts5(
    conversation_id UNINDEXED,
    user_email UNINDEXED,
    chunk_index UNINDEXED,
    message_ids UNINDEXED,
    headers_and_bold,
    tldrs,
    tokenize='porter unicode61'
);

-- Filterable metadata (regular table with indexes)
CREATE TABLE IF NOT EXISTS ConversationSearchState (
    conversation_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    title TEXT DEFAULT '',
    last_updated TEXT DEFAULT '',
    domain TEXT DEFAULT '',
    workspace_id TEXT DEFAULT '',
    flag TEXT DEFAULT 'none',
    message_count INTEGER DEFAULT 0,
    indexed_message_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    friendly_id TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_css_user_email ON ConversationSearchState(user_email);
CREATE INDEX IF NOT EXISTS idx_css_domain ON ConversationSearchState(domain);
CREATE INDEX IF NOT EXISTS idx_css_workspace ON ConversationSearchState(workspace_id);
CREATE INDEX IF NOT EXISTS idx_css_last_updated ON ConversationSearchState(last_updated);
CREATE INDEX IF NOT EXISTS idx_css_flag ON ConversationSearchState(flag);
```

**Helper functions in `database/search_index.py`:**

```python
def upsert_conversation_meta(users_dir, conversation_id, user_email, title, summary, memory_pad, message_tldrs)
def upsert_conversation_messages_chunk(users_dir, conversation_id, user_email, chunk_index, message_ids_json, headers_and_bold, tldrs)
def upsert_conversation_state(users_dir, conversation_id, user_email, title, last_updated, domain, workspace_id, flag, message_count, indexed_message_count, created_at, friendly_id)
def delete_conversation_from_index(users_dir, conversation_id)
def search_conversations_fts(users_dir, user_email, query, mode, workspace_id, domain, flag, date_from, date_to, top_k, deep)
def list_conversations_filtered(users_dir, user_email, workspace_id, domain, flag, date_from, date_to, sort_by, limit, offset)
def get_conversation_state(users_dir, conversation_id)
def get_backfill_candidates(users_dir, user_email) -> list of conversation_ids not yet indexed
def rebuild_index(users_dir, user_email) -> reindex everything from scratch
```

### 2. Index Manager — `code_common/cross_conversation_search.py` (NEW)

Central module that owns the cross-conversation index lifecycle.

**Class: `CrossConversationIndex`**

```python
class CrossConversationIndex:
    """Manages the cross-conversation FTS5 search index.
    
    Provides methods for:
    - Indexing conversation metadata and messages
    - Searching across conversations (keyword, phrase, regex)
    - Filtering by metadata (workspace, date, flag, domain)
    - Incremental updates and full rebuilds
    - Backfill of existing conversations
    """
    
    def __init__(self, users_dir: str):
        self.users_dir = users_dir
    
    # --- Indexing ---
    def index_conversation(self, conversation) -> None:
        """Full index/reindex of a single conversation.
        Extracts: title, summary, memory_pad, message TLDRs, headers, bold.
        Creates meta row + chunked message rows (10 messages per chunk).
        Updates state row with message_count and indexed_message_count.
        """
    
    def index_new_messages(self, conversation, new_messages: list) -> None:
        """Incremental: index only new messages since last index.
        Appends to existing message chunks or creates new chunk.
        Updates meta row (summary, tldrs may have changed).
        Updates state row (message_count, indexed_message_count).
        """
    
    def update_metadata(self, conversation) -> None:
        """Update only metadata fields (title, summary, memory_pad, flag, workspace).
        Called when title changes, summary updates, or flag is set.
        Does NOT reindex messages.
        """
    
    def remove_conversation(self, conversation_id: str) -> None:
        """Delete all rows for a conversation from all 3 tables."""
    
    def backfill(self, conversations: list, progress_callback=None) -> None:
        """Index multiple conversations (used for startup backfill).
        Runs in background thread. Skips already-indexed conversations.
        """
    
    # --- Extraction helpers ---
    def _extract_meta_fields(self, conversation) -> dict:
        """Extract title, latest summary, memory_pad, concatenated TLDRs."""
    
    def _extract_message_chunks(self, conversation, start_index=0) -> list[dict]:
        """Extract headers+bold+tldrs from messages, chunked by 10.
        Reuses extract_markdown_features() from conversation_search.py.
        """
    
    # --- Search ---
    def search(self, user_email, query, mode="keyword", deep=False,
               workspace_id=None, domain=None, flag=None,
               date_from=None, date_to=None, sender_filter=None,
               top_k=20) -> list[dict]:
        """Search across conversations.
        
        Modes:
        - 'keyword': FTS5 MATCH with BM25 ranking (default)
        - 'phrase': FTS5 quoted phrase match
        - 'regex': SQL REGEXP on ConversationSearchState + meta content
        
        Fast path (default): searches ConversationSearchMeta only
        Deep path (deep=True): also searches ConversationSearchMessages
        
        Returns list of dicts with:
        - conversation_id, title, friendly_id, last_updated, domain
        - workspace_id, flag, message_count
        - match_snippet (FTS5 snippet with highlights)
        - match_source ('title', 'summary', 'memory_pad', 'tldrs', 'messages')
        - score (BM25 rank)
        """
    
    def list_conversations(self, user_email, workspace_id=None, domain=None,
                           flag=None, date_from=None, date_to=None,
                           sort_by="last_updated", limit=50, offset=0) -> list[dict]:
        """Browse/filter conversations without a search query.
        
        Returns list of dicts with:
        - conversation_id, title, friendly_id, last_updated, domain
        - workspace_id, flag, message_count, created_at
        """
    
    def get_summary(self, conversation_id) -> dict:
        """Get detailed summary for one conversation from the index.
        
        Returns:
        - All state fields + title, summary text, memory_pad excerpt
        - Top 5 message TLDRs as conversation highlights
        """
```

**Key design decisions:**
- Uses `extract_markdown_features()` from `conversation_search.py` for header/bold extraction (code reuse)
- Message chunking: groups of 10 messages, each chunk is one FTS5 row. A conversation with 100 messages = 10 message chunks + 1 meta row
- `message_ids` stored as JSON array in UNINDEXED column for result attribution
- FTS5 `snippet()` used for match highlighting in results
- Column weights: title (3.0) > summary (2.0) > message_tldrs (1.5) > memory_pad (1.0) > headers_and_bold (1.0)
- All search operations scoped by `user_email` via UNINDEXED filter column
- **Direct FTS5 tables, NO content table, NO triggers.** Rationale:
  - PKB uses `content='claims'` + triggers because source data IS in SQLite (the `claims` table), so triggers auto-sync the FTS index when `claims` rows change
  - Cross-conversation search: source data is **dill-serialized files on disk**, NOT in SQLite — there is no content table to sync from
  - Direct FTS5 tables with explicit Python upserts is simpler and correct for this use case
  - UPDATE in direct FTS5: use `DELETE` then `INSERT` (or `INSERT OR REPLACE` for convenience)
  - No rowid reuse issues with direct FTS5 tables — safe to delete and re-insert
  - See `truth_management_system/database.py` lines 395-858 for the PKB content+trigger pattern (for reference only — we don't use it here)

### 3. Hook Points — Real-Time Index Updates

All hooks are **fail-open** (wrapped in try/except, errors logged, never block the main operation).

| Hook Point | File | EXACT Line | What to do | Notes |
|---|---|---|---|---|
| **persist_current_turn()** | `Conversation.py` | Line 3939 (`self.save_local()`) | After save_local, call `index.index_new_messages(self, preserved_messages)` + `index.update_metadata(self)`. Place NEXT TO the existing `_index_messages_for_search()` call at line 3855, inside the same try/except block. | This also covers `running_summary`, `memory_pad`, and `title` updates that happen during persist. |
| **set_title()** | `Conversation.py` | Lines 3946-3951 (full method, `save_local()` at 3951) | After line 3951, add `index.update_metadata(self)` | Small method: `memory["title"] = title` → `set_field` → `save_local`. |
| **delete_message()** | `Conversation.py` | Line 4724 (`self.save_local()`) | After save_local, call `index.index_conversation(self)` — **full reindex** because message chunks are invalidated. | Rare operation. `set_messages_field()` at 4723, then `save_local()` at 4724. |
| **edit_message()** | `Conversation.py` | Line 4739 (`self.save_local()`) | After save_local, call `index.index_conversation(self)` — **full reindex** because edited message content changes indexed text. | `messages[i]["text"] = text` at 4736, `set_messages_field()` at 4738, `save_local()` at 4739. |
| **delete_conversation** | `endpoints/conversations.py` | Lines 610-612 | Add `index.remove_conversation(conversation_id)` at line 610, BEFORE `conversation.delete_conversation()` at 611 and `deleteConversationForUser()` at 612. | Remove from index first, then delete files. Route: `DELETE /conversations/<id>`, function `delete_conversation()` at line 596. |
| **_create_conversation_simple()** | `endpoints/conversations.py` | Line 1230 (`conversation.save_local()`) | After save_local at line 1230, add `index.update_metadata(conversation)`. Creates empty state row with title='', message_count=0. | Called by `POST /create_conversation`. Conversation object created at line 1215. |
| **move_conversation_to_workspace** | `endpoints/workspaces.py` | Lines 207-212 | After `moveConversationToWorkspace()` DB call succeeds (line 207), before the return at line 213. Load conversation to get current metadata, then call `index.update_metadata(conversation)`. | Route: `PUT /move_conversation_to_workspace/<id>`. The mutation is `moveConversationToWorkspace()` — a DB-only operation, no Conversation object loaded. Must load conversation to get full metadata for index update, OR just do a targeted SQL UPDATE on ConversationSearchState.workspace_id. **Prefer the targeted SQL approach** — avoid loading a heavy dill file just to update one field. |
| **memory_pad (direct set)** | `Conversation.py` | Line 947 (`@memory_pad.setter`) | **NOT needed as separate hook.** `persist_current_turn()` already calls `update_metadata()` which picks up the latest memory_pad. For manual sets via `conv_set_memory_pad` tool: the setter at line 947 calls `save_local()`, but the tool handler doesn't call persist_current_turn. **Add hook in setter** with a guard: `if not getattr(self, '_in_persist', False): index.update_metadata(self)`. Set `self._in_persist = True` at top of `persist_current_turn()` and `False` at end. | `add_to_memory_pad_from_response()` (lines 952-1093) also mutates memory_pad but goes through the setter. |
| **Flag mutations (`set_flag`)** | `endpoints/conversations.py` | Lines 1147-1194 | Route: `POST /set_flag/<conversation_id>/<flag>`. Sets `conversation.flag` directly at lines 1185 (clear to None) and 1193 (set color). **No `save_local()` is called** — flag only modifies the in-memory cached object. The next `persist_current_turn()` will persist it. Add `index.update_metadata(conversation)` after line 1193 (and after line 1185 for clear). Since the Conversation object is already loaded from cache (line 1159), no heavy dill load needed. | Valid colors: red, blue, green, yellow, orange, purple, pink, cyan, magenta, lime, indigo, teal, brown, gray, black, white. |

**How to access the index from hook points:**

- **Flask endpoints**: `get_state().cross_conversation_index` — the `AppState` singleton stores the index instance. `get_state()` is at `endpoints/state.py:114`, accessed via `from endpoints.state import get_state`.
- **Conversation.py hooks**: `self._cross_conv_index` attribute. Set during conversation loading by the Flask request handler (the code that calls `get_conversation_with_keys()` should attach it: `conversation._cross_conv_index = get_state().cross_conversation_index`). If the attribute is missing (e.g., MCP server loads conversation directly), skip the hook gracefully: `if hasattr(self, '_cross_conv_index') and self._cross_conv_index:`.
- **MCP server** (`mcp_server/conversation.py`): Creates its own `CrossConversationIndex(_users_dir())` instance per request (stateless, reads from same `search_index.db` file). Uses `STORAGE_DIR` env var (line 43): `os.environ.get("STORAGE_DIR", "storage")`.
- **Tool-calling** (`code_common/tools.py`): Creates its own instance via `CrossConversationIndex(_cross_conv_users_dir())` per tool call. Uses `STORAGE_DIR` env var same as MCP server.


### 3a. AppState Integration (EXACT steps)

`AppState` is a `@dataclass(slots=True)` in `endpoints/state.py` (lines 18-67). It's the process-global singleton holding all shared state, initialized exactly once by `init_state()` (line 73) during `create_app()` in `server.py`.

**Current fields** (14 total): `folder`, `users_dir`, `pdfs_dir`, `locks_dir`, `cache_dir`, `conversation_folder`, `global_docs_dir`, `docs_folder`, `login_not_needed`, `conversation_cache`, `pinned_claims`, `cache`, `limiter`.

**Steps to add `cross_conversation_index`:**

1. **`endpoints/state.py` line 64** — Add field to AppState dataclass (after `limiter`):
   ```python
   cross_conversation_index: Any = None  # CrossConversationIndex instance
   ```
   Use `= None` default so it's optional and doesn't break existing `init_state()` callers.

2. **`endpoints/state.py` line 85** — Add parameter to `init_state()` (after `limiter`):
   ```python
   cross_conversation_index: Any = None,
   ```

3. **`endpoints/state.py` line 107** — Add to `AppState()` instantiation (after `limiter=limiter`):
   ```python
   cross_conversation_index=cross_conversation_index,
   ```

4. **`server.py` line 500** — After `create_tables()` call, create the index and pass to `init_state()`:
   ```python
   # Line 500: create_tables(users_dir=users_dir, logger=logger)
   from database.search_index import create_search_tables
   create_search_tables(users_dir=users_dir, logger=logger)
   
   from code_common.cross_conversation_search import CrossConversationIndex
   cross_conversation_index = CrossConversationIndex(users_dir)
   ```
   Then pass `cross_conversation_index=cross_conversation_index` into the `init_state()` call at line 484.

5. **Access in endpoints:**
   ```python
   from endpoints.state import get_state
   state = get_state()  # get_state() is at endpoints/state.py:114
   index = state.cross_conversation_index
   ```

**NOTE on `create_tables()` integration:** `create_tables()` at `database/connection.py:65` is currently monolithic — all table creation is inline, no sub-function calls. Since `search_index.db` is a SEPARATE DB file (not inside `users.db`), calling `create_search_tables()` separately in `server.py` is cleaner than calling it from inside `create_tables()`. This is a deliberate separation.

### 3b. Storage Path Resolution (CRITICAL for MCP/tools)

Three contexts access storage differently — they MUST all resolve to the same `search_index.db` location:

| Context | How STORAGE_DIR is resolved | users_dir path |
|---|---|---|
| **Flask endpoints** | `server.py` line 449: `users_dir = os.path.join(os.getcwd(), folder, "users")` where `folder` comes from `--folder` CLI arg (default `"storage"`) | Absolute, stored on `AppState.users_dir` |
| **Tool-calling** (`code_common/tools.py`) | `os.environ.get("STORAGE_DIR", "storage")` at line 2258 | Relative: `os.path.join(os.getcwd(), STORAGE_DIR, "users")` |
| **MCP server** (`mcp_server/conversation.py`) | `os.environ.get("STORAGE_DIR", "storage")` at line 43 | Relative: `os.path.join(os.getcwd(), STORAGE_DIR, "users")` via `_users_dir()` at line 56 |

**`search_index.db` location:** `{users_dir}/search_index.db` (alongside `users.db`).

**IMPORTANT:** If Flask's `--folder` CLI arg differs from `STORAGE_DIR` env var, they'll look at different DB files. The default for both is `"storage"`, so they match by default. **Document this assumption and add a startup sanity check:**
```python
# In server.py create_app(), after init_state():
storage_env = os.environ.get('STORAGE_DIR', 'storage')
if os.path.abspath(os.path.join(os.getcwd(), storage_env, 'users')) != os.path.abspath(users_dir):
    logger.warning('STORAGE_DIR env var (%s) differs from --folder (%s). MCP tools may use wrong DB.', storage_env, folder)
```

**Helper functions for MCP and tools:**
```python
# In mcp_server/conversation.py (add near line 56):
def _search_index_users_dir():
    return os.path.join(os.getcwd(), STORAGE_DIR, "users")

# In code_common/tools.py (add near _conv_users_dir() at line 2267):
def _cross_conv_users_dir():
    storage = os.environ.get("STORAGE_DIR", "storage")
    return os.path.join(os.getcwd(), storage, "users")
```

### 4. Backfill Strategy

**On server startup** (in `create_app()` of `server.py`, after `create_tables()`):

```python
import threading

def _backfill_search_index(state):
    """Background thread: index conversations not yet in search_index.db."""
    index = state.cross_conversation_index
    candidates = get_backfill_candidates(state.users_dir, user_email=None)  # all users
    for conv_id in candidates:
        try:
            conv = Conversation.load_local(os.path.join(state.conversation_folder, conv_id))
            index.index_conversation(conv)
        except Exception as e:
            logger.warning(f"Backfill skip {conv_id}: {e}")

threading.Thread(target=_backfill_search_index, args=(state,), daemon=True).start()
```

- Runs as daemon thread, non-blocking
- `get_backfill_candidates()` queries `ConversationSearchState` to find conversations in `UserToConversationId` that are missing from the search index
- Skips corrupted or unloadable conversations gracefully
- One-time cost: ~30s-2min for 1K conversations
- Progress logged every 100 conversations

### 5. Flask Endpoint — `POST /search_conversations`

Added to `endpoints/conversations.py` (existing blueprint).

```python
@conversations_bp.route("/search_conversations", methods=["POST"])
@rate_limit(max_calls=30, period_seconds=60)
def search_conversations_endpoint():
    """Search across user's conversations.
    
    Request body (JSON):
    {
        "query": "search text",           # required for search, optional for list
        "mode": "keyword|phrase|regex",   # default: "keyword"
        "deep": false,                     # search message content too
        "workspace_id": "ws_123",          # optional filter
        "domain": "default",              # optional filter
        "flag": "red",                     # optional filter
        "date_from": "2025-01-01",        # optional filter (ISO date)
        "date_to": "2026-03-04",          # optional filter (ISO date)
        "top_k": 20,                       # max results (default 20)
        "action": "search|list|summary",  # what to do
        "conversation_id": "conv_123",    # required for action=summary
        "sort_by": "last_updated|relevance", # for list action
        "offset": 0,                       # pagination offset for list
    }
    
    Returns: { "results": [...], "total": N, "query": "...", "action": "..." }
    """
```

**Three actions in one endpoint:**
- `action=search` → calls `index.search()` — requires `query`
- `action=list` → calls `index.list_conversations()` — browse/filter, no query needed
- `action=summary` → calls `index.get_summary()` — requires `conversation_id`

### 6. LLM Tools (Tool-Calling Framework)

Three new tools registered in `code_common/tools.py` and defined in `code_common/cross_conversation_search.py`.

#### Tool 1: `search_conversations`
```python
CROSS_CONVERSATION_TOOLS = {
    "search_conversations": {
        "name": "search_conversations",
        "description": (
            "Search across ALL of the user's conversations by keyword, phrase, or regex. "
            "Use this when the user asks to find something they discussed in a previous conversation, "
            "or when they reference past work without specifying which conversation. "
            "Returns matching conversations with title, date, snippet showing where the match is, "
            "conversation ID, and friendly ID. Use 'deep' mode to also search within message "
            "headers and key terms (slower but more thorough). "
            "Combine with get_conversation_summary for full details of a specific result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. For keyword mode: natural language keywords. For phrase mode: exact phrase. For regex mode: regex pattern."
                },
                "mode": {
                    "type": "string",
                    "enum": ["keyword", "phrase", "regex"],
                    "description": "Search mode. 'keyword' (default): BM25 ranked keyword search. 'phrase': exact phrase match. 'regex': regex pattern match.",
                    "default": "keyword"
                },
                "deep": {
                    "type": "boolean",
                    "description": "If true, also searches message headers and key terms (slower). Default false searches only titles and summaries.",
                    "default": false
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Filter to conversations in this workspace only."
                },
                "date_from": {
                    "type": "string",
                    "description": "Filter: only conversations updated on or after this date (ISO format YYYY-MM-DD)."
                },
                "date_to": {
                    "type": "string",
                    "description": "Filter: only conversations updated on or before this date (ISO format YYYY-MM-DD)."
                },
                "flag": {
                    "type": "string",
                    "enum": ["red", "blue", "green", "yellow", "purple", "orange", "none"],
                    "description": "Filter by conversation color flag."
                },
                "sender_filter": {
                    "type": "string",
                    "enum": ["user", "model"],
                    "description": "Only return matches from messages by this sender."
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 20).",
                    "default": 20
                }
            },
            "required": ["query"]
        },
        "is_interactive": False,
        "category": "conversation",
        "usage_guidelines": (
            "Use when user asks 'where did we discuss X', 'find my conversation about Y', "
            "'what did I say about Z last week'. Start with keyword mode (fast path). "
            "Use deep=true only if keyword mode returns too few results. "
            "Use phrase mode for exact quotes. Use regex for patterns like error codes."
        )
    },
    ...
}
```

#### Tool 2: `list_user_conversations`
```python
    "list_user_conversations": {
        "name": "list_user_conversations",
        "description": (
            "Browse and filter the user's conversations WITHOUT a search query. "
            "Use this when the user wants to see their recent conversations, "
            "browse by workspace or domain, or filter by date range or flag color. "
            "Returns conversation titles, dates, message counts, and IDs. "
            "Supports pagination via offset parameter."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Filter to this workspace."},
                "domain": {"type": "string", "description": "Filter by domain."},
                "flag": {"type": "string", "enum": ["red","blue","green","yellow","purple","orange","none"], "description": "Filter by flag color."},
                "date_from": {"type": "string", "description": "Only conversations updated on/after this date (YYYY-MM-DD)."},
                "date_to": {"type": "string", "description": "Only conversations updated on/before this date (YYYY-MM-DD)."},
                "sort_by": {"type": "string", "enum": ["last_updated", "created_at", "title", "message_count"], "description": "Sort field (default: last_updated desc).", "default": "last_updated"},
                "limit": {"type": "integer", "description": "Max results (default 50).", "default": 50},
                "offset": {"type": "integer", "description": "Pagination offset (default 0).", "default": 0}
            },
            "required": []
        },
        "is_interactive": False,
        "category": "conversation",
        "usage_guidelines": (
            "Use when user says 'show my recent chats', 'what conversations do I have in workspace X', "
            "'list my flagged conversations'. No search query needed — this is for browsing and filtering."
        )
    },
```

#### Tool 3: `get_conversation_summary`
```python
    "get_conversation_summary": {
        "name": "get_conversation_summary",
        "description": (
            "Get a detailed summary of a specific conversation by its ID or friendly ID. "
            "Returns: title, full running summary, message count, date range, workspace, "
            "domain, flag, top message TLDRs as highlights, and memory pad excerpt. "
            "Use after search_conversations to get details on a specific result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "The conversation ID or friendly ID to get summary for."
                }
            },
            "required": ["conversation_id"]
        },
        "is_interactive": False,
        "category": "conversation",
        "usage_guidelines": (
            "Use after search_conversations or list_user_conversations to get full details "
            "on a specific conversation. The conversation_id comes from the search/list results."
        )
    }
```

**Friendly ID resolution in `get_conversation_summary`:**

The `conversation_id` parameter accepts BOTH the full opaque ID (e.g., `user@email.com_abc123...`) and the short friendly ID (e.g., `react_optimization_b4f2`). Resolution flow:

1. Try direct lookup in `ConversationSearchState` by `conversation_id` field
2. If not found, try `friendly_id` column in `ConversationSearchState`
3. If still not found, resolve via `getConversationIdByFriendlyId(users_dir=..., user_email=..., conversation_friendly_id=conversation_id)` from `database/conversations.py` (lines 355-387)
4. Friendly IDs have format `{word1}_{word2}_{hash4}` (e.g., `react_optimization_b4f2`), generated by `generate_conversation_friendly_id()` in `conversation_reference_utils.py` (lines 64-102). Uses `mmh3` hash + base36 encoding with collision retry.
5. Resolution is scoped to `user_email` (ownership check built-in).


### 7. MCP Tools — `mcp_server/conversation.py`

Three new `@mcp.tool()` functions following existing pattern:

```python
@mcp.tool()
def search_conversations(user_email: str, query: str, mode: str = "keyword",
                         deep: bool = False, workspace_id: str = "",
                         date_from: str = "", date_to: str = "",
                         flag: str = "", sender_filter: str = "",
                         top_k: int = 20) -> str:
    """Search across all conversations by keyword, phrase, or regex."""
    index = CrossConversationIndex(USERS_DIR)
    results = index.search(user_email=user_email, query=query, mode=mode, deep=deep, ...)
    return json.dumps(results, default=str)

@mcp.tool()
def list_user_conversations(user_email: str, workspace_id: str = "",
                            domain: str = "", flag: str = "",
                            date_from: str = "", date_to: str = "",
                            sort_by: str = "last_updated",
                            limit: int = 50, offset: int = 0) -> str:
    """Browse and filter conversations without a search query."""
    index = CrossConversationIndex(USERS_DIR)
    results = index.list_conversations(user_email=user_email, ...)
    return json.dumps(results, default=str)

@mcp.tool()
def get_conversation_summary(user_email: str, conversation_id: str) -> str:
    """Get detailed summary of a specific conversation."""
    index = CrossConversationIndex(USERS_DIR)
    result = index.get_summary(conversation_id)
    return json.dumps(result, default=str)
```

### 8. UI — Search Modal

#### 8.1 Search Button (interface.html, EXACT line 259)

Insert at line 259, between the existing `add-new-workspace` button (line 259) and the closing `</div>` (line 260).

Current HTML at lines 257-260:
```html
<div class="sidebar-toolbar-actions">
    <button id="add-new-chat" type="button" class="btn btn-sm sidebar-tool-btn" title="New Conversation"><i class="fa fa-file-o"></i></button>
    <button id="add-new-workspace" type="button" class="btn btn-sm sidebar-tool-btn" title="New Workspace"><i class="fa fa-folder-o"></i></button>
    <!-- INSERT NEW BUTTON HERE -->
</div>
```

Add this button (uses Font Awesome 4.7 `fa fa-search` icon, matching existing `btn btn-sm sidebar-tool-btn` pattern):

```html
<button id="search-conversations-btn" type="button" class="btn btn-sm sidebar-tool-btn" title="Search Conversations">
    <i class="fa fa-search"></i>
</button>
```

#### 8.2 Search Modal (interface.html — insert after line ~3920, before `<script>` tags at line 4034)

The last modal in interface.html is `image-gen-modal` (lines 3869-3920). New modals should be placed AFTER that closing `</div>` and BEFORE the `<script>` tag block starting at line 4034. Use `z-index: 1065` (Bootstrap 4.6 modals default to 1050; other custom modals use 100001+).

```html
<div class="modal fade" id="cross-conversation-search-modal" tabindex="-1" aria-hidden="true" style="z-index: 1065;">
  <div class="modal-dialog modal-lg">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="fa fa-search"></i> Search Conversations</h5>
        <button type="button" class="close" data-dismiss="modal" aria-label="Close">
          <span aria-hidden="true">&times;</span>
        </button>
      </div>
      <div class="modal-body" style="max-height: 70vh; overflow-y: auto;">
        <!-- Search Input -->
        <div class="input-group mb-3">
          <input type="text" id="cross-conv-search-input" class="form-control" 
                 placeholder="Search across all conversations... (min 5 characters)"
                 autocomplete="off">
          <div class="input-group-append">
            <button class="btn btn-outline-secondary" type="button" id="cross-conv-search-clear" title="Clear">
              <i class="fa fa-times"></i>
            </button>
          </div>
        </div>
        
        <!-- Filter Row (collapsible) -->
        <div class="collapse mb-3" id="cross-conv-search-filters">
          <div class="card card-body p-2">
            <div class="form-row">
              <div class="col-md-4 mb-2">
                <select id="cross-conv-search-workspace" class="form-control form-control-sm">
                  <option value="">All Workspaces</option>
                </select>
              </div>
              <div class="col-md-3 mb-2">
                <select id="cross-conv-search-flag" class="form-control form-control-sm">
                  <option value="">All Flags</option>
                  <option value="red">🔴 Red</option>
                  <option value="blue">🔵 Blue</option>
                  <option value="green">🟢 Green</option>
                  <option value="yellow">🟡 Yellow</option>
                  <option value="purple">🟣 Purple</option>
                  <option value="orange">🟠 Orange</option>
                </select>
              </div>
              <div class="col-md-5 mb-2">
                <div class="input-group input-group-sm">
                  <input type="date" id="cross-conv-search-date-from" class="form-control">
                  <div class="input-group-prepend input-group-append">
                    <span class="input-group-text">to</span>
                  </div>
                  <input type="date" id="cross-conv-search-date-to" class="form-control">
                </div>
              </div>
            </div>
            <div class="form-row">
              <div class="col-md-4 mb-1">
                <div class="custom-control custom-checkbox">
                  <input type="checkbox" class="custom-control-input" id="cross-conv-search-deep">
                  <label class="custom-control-label" for="cross-conv-search-deep">Deep search (messages)</label>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Toggle Filters Button -->
        <button class="btn btn-sm btn-link mb-2" type="button" data-toggle="collapse" data-target="#cross-conv-search-filters">
          <i class="fa fa-filter"></i> Filters
        </button>
        
        <!-- Search Status -->
        <div id="cross-conv-search-status" class="text-muted small mb-2" style="display:none;"></div>
        
        <!-- Results Container -->
        <div id="cross-conv-search-results"></div>
      </div>
    </div>
  </div>
</div>
```

#### 8.3 Search Result Item Template (rendered by JS)

```html
<!-- Rendered by JS for each result -->
<div class="cross-conv-result-item" data-conversation-id="{conversation_id}" 
     data-conversation-friendly-id="{friendly_id}" style="cursor:pointer;">
  <div class="d-flex justify-content-between align-items-start">
    <div>
      <strong class="cross-conv-result-title">{title}</strong>
      <span class="badge badge-secondary ml-1">{message_count} msgs</span>
      {flag_badge if flag != 'none'}
    </div>
    <small class="text-muted">{relative_date}</small>
  </div>
  <div class="cross-conv-result-snippet text-muted small mt-1">
    {match_snippet with **highlights**}
  </div>
  <small class="text-muted">{workspace_name} · {domain}</small>
</div>
```

#### 8.4 CSS (style.css additions)

```css
.cross-conv-result-item {
    padding: 10px 12px;
    border-bottom: 1px solid #eee;
    transition: background-color 0.15s;
}
.cross-conv-result-item:hover {
    background-color: #f8f9fa;
}
.cross-conv-result-item:last-child {
    border-bottom: none;
}
.cross-conv-result-title {
    font-size: 0.95rem;
}
.cross-conv-result-snippet {
    font-size: 0.85rem;
    line-height: 1.4;
}
.cross-conv-result-snippet mark {
    background-color: #fff3cd;
    padding: 0 2px;
    border-radius: 2px;
}
```

#### 8.5 JavaScript — `interface/cross-conversation-search.js` (NEW)

```javascript
/**
 * Cross-Conversation Search Manager
 * 
 * Handles the search modal UI:
 * - Debounced search input (500ms, min 5 chars)
 * - API calls to POST /search_conversations
 * - Result rendering with snippets
 * - Click to navigate to conversation
 * - Filter management (workspace, flag, date range, deep)
 */
var CrossConversationSearchManager = (function() {
    var _debounceTimer = null;
    var _minChars = 5;
    var _debounceMs = 500;
    var _lastQuery = '';
    
    function init() {
        // Wire up search button
        $('#search-conversations-btn').off('click').on('click', function() {
            $('#cross-conversation-search-modal').modal('show');
            setTimeout(function() { $('#cross-conv-search-input').focus(); }, 300);
        });
        
        // Debounced search on keyup
        $('#cross-conv-search-input').off('keyup').on('keyup', function(e) {
            var query = $(this).val().trim();
            if (_debounceTimer) clearTimeout(_debounceTimer);
            if (query.length < _minChars) {
                $('#cross-conv-search-results').empty();
                $('#cross-conv-search-status').hide();
                return;
            }
            _debounceTimer = setTimeout(function() { _doSearch(query); }, _debounceMs);
        });
        
        // Clear button
        $('#cross-conv-search-clear').off('click').on('click', function() {
            $('#cross-conv-search-input').val('').focus();
            $('#cross-conv-search-results').empty();
            $('#cross-conv-search-status').hide();
        });
        
        // Result click → open conversation
        $(document).off('click', '.cross-conv-result-item').on('click', '.cross-conv-result-item', function(e) {
            e.preventDefault();
            var convId = $(this).data('conversation-id');
            if (!convId) return;
            $('#cross-conversation-search-modal').modal('hide');
            ConversationManager.setActiveConversation(convId);
        });
        
        // Populate workspace dropdown on modal show
        $('#cross-conversation-search-modal').on('show.bs.modal', function() {
            _populateWorkspaceDropdown();
        });
    }
    
    function _doSearch(query) { /* POST /search_conversations, render results */ }
    function _renderResults(results, query) { /* Build result HTML */ }
    function _populateWorkspaceDropdown() { /* Fetch workspaces from /list_workspaces */ }
    function _getFilters() { /* Read filter values from DOM */ }
    
    return { init: init };
})();
```

**Initialization:** Add `CrossConversationSearchManager.init()` call in chat.js where other managers are initialized (after document ready).

### 9. Tool-Calling Framework Registration

In `code_common/tools.py`, add after existing conversation tools:

```python
from code_common.cross_conversation_search import CROSS_CONVERSATION_TOOLS, CrossConversationIndex

def _cross_conv_tool_kwargs(tool_name: str) -> dict:
    """Return CROSS_CONVERSATION_TOOLS[tool_name] kwargs suitable for register_tool."""
    return {k: v for k, v in CROSS_CONVERSATION_TOOLS[tool_name].items()
            if k in ('name', 'description', 'parameters', 'is_interactive', 'category')}

@register_tool(**_cross_conv_tool_kwargs("search_conversations"))
def handle_search_conversations(args: dict, context: ToolContext) -> ToolCallResult:
    """Search across all user conversations."""
    ...

@register_tool(**_cross_conv_tool_kwargs("list_user_conversations"))
def handle_list_user_conversations(args: dict, context: ToolContext) -> ToolCallResult:
    """Browse and filter user conversations."""
    ...

@register_tool(**_cross_conv_tool_kwargs("get_conversation_summary"))
def handle_get_conversation_summary(args: dict, context: ToolContext) -> ToolCallResult:
    """Get detailed summary of a conversation."""
    ...
```

### 10. UI Integration Points (EXACT locations)

**interface.html changes:**

| What | EXACT Line | Detail |
|---|---|---|
| Search button | Line 259 (before `</div>` at line 260) | Insert `<button id="search-conversations-btn" class="btn btn-sm sidebar-tool-btn" ...>` inside `div.sidebar-toolbar-actions` |
| Tool options | Lines 2298-2304 (before `</optgroup>` at 2304) | Add 3 `<option>` elements: `search_conversations`, `list_user_conversations`, `get_conversation_summary` inside the Conversation `<optgroup>` |
| Search modal HTML | After line ~3920 (after `image-gen-modal`) | Before `<script>` tags at line 4034. Use `z-index: 1065` |
| Script include | After line 4078 (after `file-browser-manager.js?v=27`) | `<script src="interface/cross-conversation-search.js?v=1"></script>` — uses `?v=N` cache busting pattern |
| Manager init | Line 4829 (after `ScriptManager.init()`) | `CrossConversationSearchManager.init();` — inside `ExtensionBridge.onAvailabilityChange` callback. OR alternatively in chat.js `$(document).ready()` block at line 549 if not extension-dependent. |

**chat.js changes:**

| What | EXACT Line | Detail |
|---|---|---|
| `categoryDefaults` | Line 663 | Add `'search_conversations', 'list_user_conversations', 'get_conversation_summary'` to the existing `conversation` array (currently has 5 tools, becomes 8) |

Current value at line 663:
```javascript
conversation: ['search_messages', 'list_messages', 'read_message', 'get_conversation_details', 'get_conversation_memory_pad'],
// becomes:
conversation: ['search_messages', 'list_messages', 'read_message', 'get_conversation_details', 'get_conversation_memory_pad', 'search_conversations', 'list_user_conversations', 'get_conversation_summary'],
```

**style.css changes:**
- Append new CSS rules after line 1655 (end of file). Last rule is `.fb-move-folder-tree .fb-move-root-item` block.
---

## File Changes Summary

| File | Action | What | EXACT Lines Affected |
|---|---|---|---|
| `database/search_index.py` | **NEW** | FTS5 table creation, WAL mode, `get_search_connection()`, all CRUD/search helpers for search_index.db | New file (~200 lines) |
| `endpoints/state.py` | MODIFY | Add `cross_conversation_index: Any = None` field to AppState dataclass, add parameter to `init_state()` | Lines 64, 85, 107 |
| `code_common/cross_conversation_search.py` | **NEW** | `CrossConversationIndex` class, `CROSS_CONVERSATION_TOOLS` dict (3 tool schemas) | New file (~400 lines) |
| `code_common/tools.py` | MODIFY | Register 3 new tools with `_cross_conv_tool_kwargs()`, add `_cross_conv_users_dir()` helper | After line 2542 (existing conv tools), near line 2267 |
| `Conversation.py` | MODIFY | Hook `index_new_messages` + `update_metadata` in `persist_current_turn()` (line 3939), hook `update_metadata` in `set_title()` (line 3951), hook full reindex in `delete_message()` (line 4724) and `edit_message()` (line 4739), guard flag in `memory_pad.setter` (line 947) | Lines 3855, 3939, 3951, 4724, 4739, 947 |
| `endpoints/conversations.py` | MODIFY | Add `POST /search_conversations` endpoint, hook `remove_conversation` in `delete_conversation()` (line 610), hook `update_metadata` in `_create_conversation_simple()` (line 1230) | Lines 596-615, 1197-1231, new endpoint |
| `endpoints/workspaces.py` | MODIFY | Hook `update_metadata` (or targeted SQL) in `move_conversation_to_workspace()` after line 212 | Lines 184-222 |
| `mcp_server/conversation.py` | MODIFY | Add 3 new `@mcp.tool()` functions, add `_search_index_users_dir()` helper | After existing tools, near line 56 |
| `server.py` | MODIFY | Create `CrossConversationIndex` + `create_search_tables()` after line 500, pass to `init_state()`, start backfill thread | Lines 484-500 |
| `interface/interface.html` | MODIFY | Search button (line 259), search modal HTML (after line ~3920), 3 new `<option>` (lines 2298-2304), `<script>` tag (after line 4078), init call (line 4829) | Multiple |
| `interface/cross-conversation-search.js` | **NEW** | Search modal manager: debounce, API calls, result rendering, navigation, workspace dropdown | New file (~200 lines) |
| `interface/style.css` | MODIFY | Search result item styles (`.cross-conv-result-item` etc.) | After line 1655 (end of file) |
| `interface/chat.js` | MODIFY | Add 3 tools to `categoryDefaults.conversation` array | Line 663 |
---

## Implementation Tasks (Ordered)

### Milestone 1: Database Layer
1. Create `database/search_index.py`:
   - `get_search_connection(users_dir)` — opens `{users_dir}/search_index.db`, enables WAL mode, registers REGEXP function
   - `create_search_tables(users_dir, logger)` — DDL for `ConversationSearchMeta` (FTS5), `ConversationSearchMessages` (FTS5), `ConversationSearchState` (regular) + 5 indexes
   - `upsert_conversation_meta(...)` — DELETE+INSERT into FTS5 meta table (no UPDATE in FTS5)
   - `upsert_conversation_messages_chunk(...)` — DELETE+INSERT into FTS5 messages table by conversation_id+chunk_index
   - `upsert_conversation_state(...)` — INSERT OR REPLACE into state table
   - `delete_conversation_from_index(...)` — DELETE from all 3 tables by conversation_id
   - `search_conversations_fts(...)` — FTS5 MATCH query with `bm25()` ranking, `snippet()` highlighting, optional deep search across both FTS5 tables, JOIN with state table for filters
   - `list_conversations_filtered(...)` — SELECT from state table with WHERE filters, pagination
   - `get_conversation_state(...)` — SELECT single row from state table
   - `get_backfill_candidates(...)` — LEFT JOIN UserToConversationId vs ConversationSearchState to find missing
   - `rebuild_index(...)` — DROP + recreate FTS5 tables, reindex from scratch
   - Follow existing pattern: get connection → cursor → execute → commit → close in finally (see `database/conversations.py:52-107`)
2. Add `create_search_tables()` call in `server.py` after `create_tables()` at line 500 (NOT inside `create_tables()` since it's a separate DB file)
3. **Verify:** `conda activate science-reader && python -c "from database.search_index import create_search_tables; create_search_tables(users_dir='storage/users')"` — creates `storage/users/search_index.db` with 3 tables

### Milestone 2: Index Manager
4. Create `code_common/cross_conversation_search.py`:
   - `CrossConversationIndex` class with `__init__(self, users_dir)`, all methods from Section 2
   - `_extract_meta_fields(conversation)` — extract title from `memory["title"]`, latest `running_summary`, `memory_pad` text, concatenated `answer_tldr` from all model messages
   - `_extract_message_chunks(conversation, start_index=0)` — iterate messages from start_index, reuse `extract_markdown_features()` from `conversation_search.py` (line 64) for headers+bold extraction, chunk by 10, store message_ids as JSON
   - `index_conversation(conv)` — full index: delete existing rows, extract meta, extract all message chunks, upsert all rows + state
   - `index_new_messages(conv, new_messages)` — incremental: read `indexed_message_count` from state table, extract chunks for only new messages (start_index=indexed_message_count), update meta row (summary may have changed), update state row
   - `update_metadata(conv)` — update only meta FTS5 row + state row (title, summary, memory_pad, flag, workspace_id, last_updated). Does NOT touch message chunks
   - `remove_conversation(conversation_id)` — delete from all 3 tables
   - `backfill(conversations, progress_callback)` — loop + index_conversation + gc.collect() every 50 conversations + progress logging every 100
5. Add `CROSS_CONVERSATION_TOOLS` dict with all 3 tool schemas (search_conversations, list_user_conversations, get_conversation_summary)
6. **Verify:** Write a small test script that creates a mock conversation dict, indexes it, and searches for it

### Milestone 3: AppState + Hook Points
7. Modify `endpoints/state.py` — add `cross_conversation_index: Any = None` to AppState (line 64), `init_state()` (line 85), and instantiation (line 107)
8. Modify `server.py` — after `create_tables()` call at line 500:
   - Call `create_search_tables(users_dir=users_dir, logger=logger)`
   - Create `cross_conversation_index = CrossConversationIndex(users_dir)`
   - Pass to `init_state(cross_conversation_index=cross_conversation_index, ...)`
   - Start backfill daemon thread
   - Add STORAGE_DIR sanity check warning
9. Modify `Conversation.py` — add hooks at:
   - Line 3855 (inside existing `_index_messages_for_search` try/except): add cross-conv `index_new_messages()` + `update_metadata()` call
   - Line 3951 (after `set_title` save_local): add `update_metadata()`
   - Line 4724 (after `delete_message` save_local): add `index_conversation()` (full reindex)
   - Line 4739 (after `edit_message` save_local): add `index_conversation()` (full reindex)
   - All hooks guarded with `if hasattr(self, '_cross_conv_index') and self._cross_conv_index:`
10. Modify `endpoints/conversations.py`:
    - Line 610 in `delete_conversation()`: add `index.remove_conversation(conversation_id)` before delete
    - Line 1193 in `set_flag()`: add `index.update_metadata(conversation)` after flag set (also after line 1185 for flag clear)
    - Line 1230 in `_create_conversation_simple()`: add `index.update_metadata(conversation)` after save_local
    - Line 610 in `delete_conversation()`: add `index.remove_conversation(conversation_id)` before delete
    - Line 1230 in `_create_conversation_simple()`: add `index.update_metadata(conversation)` after save_local
11. Modify `endpoints/workspaces.py` line 212 in `move_conversation_to_workspace()`: targeted SQL UPDATE on `ConversationSearchState.workspace_id` (avoid loading full dill file)
12. **Verify:** Start server with `conda activate science-reader && python server.py`, create a conversation, send a message, check `search_index.db` with `sqlite3 storage/users/search_index.db "SELECT * FROM ConversationSearchState LIMIT 5"`

### Milestone 4: Flask Endpoint
13. Add `POST /search_conversations` to `endpoints/conversations.py`:
    - Parse JSON body: action, query, mode, deep, workspace_id, domain, flag, date_from, date_to, top_k, conversation_id, sort_by, offset
    - Validate: action=search requires query, action=summary requires conversation_id
    - Route to `index.search()`, `index.list_conversations()`, or `index.get_summary()` based on action
    - Return JSON: `{"results": [...], "total": N, "query": "...", "action": "..."}`
    - Rate limit: 30/minute
14. **Verify:** `curl -X POST http://localhost:5000/search_conversations -H 'Content-Type: application/json' -d '{"query":"test","action":"search"}' --cookie <session_cookie>`

### Milestone 5: LLM Tools + MCP
15. Register 3 tools in `code_common/tools.py`:
    - Add `_cross_conv_tool_kwargs()` helper (same pattern as `_conv_tool_kwargs()` at line 2542)
    - Add `_cross_conv_users_dir()` helper near line 2267
    - 3 `@register_tool` handlers that create `CrossConversationIndex(_cross_conv_users_dir())`, call the appropriate method, return `ToolCallResult`
    - For `get_conversation_summary`: implement friendly_id resolution (try state table first, then `getConversationIdByFriendlyId()`)
16. Add 3 MCP tools in `mcp_server/conversation.py`:
    - Add `_search_index_users_dir()` helper near line 56
    - 3 `@mcp.tool()` functions following existing pattern (see existing 12 tools)
17. Update `interface/interface.html` lines 2298-2304: add 3 `<option>` elements before `</optgroup>`
18. Update `interface/chat.js` line 663: add 3 tool names to `categoryDefaults.conversation` array
19. **Verify:** In chat UI, enable conversation tools, ask LLM to search for something across conversations. Check MCP server responds to tool calls.

### Milestone 6: UI Modal
20. Add search button at `interface/interface.html` line 259 (inside `sidebar-toolbar-actions`)
21. Add search modal HTML after line ~3920 (after `image-gen-modal`, before `<script>` tags at line 4034)
22. Create `interface/cross-conversation-search.js`:
    - IIFE module `CrossConversationSearchManager`
    - `init()`: wire button click → modal show, debounced keyup (500ms, min 5 chars), clear button, result click → `ConversationManager.setActiveConversation(convId)`, populate workspace dropdown on modal show
    - `_doSearch(query)`: POST to `/search_conversations` with filters, render results
    - `_renderResults(results, query)`: build result HTML cards with title, badge, snippet, date, workspace
    - `_populateWorkspaceDropdown()`: GET `/list_workspaces` to populate `<select>`
    - `_getFilters()`: read workspace, flag, date_from, date_to, deep checkbox from DOM
23. Add `<script src="interface/cross-conversation-search.js?v=1"></script>` after line 4078
24. Add `CrossConversationSearchManager.init()` at line 4829 (after `ScriptManager.init()`)
25. Add CSS to `interface/style.css` after line 1655
26. **Verify:** Click magnifying glass → modal opens → type 5+ chars → results appear after 500ms → click result → conversation opens

### Milestone 7: Documentation
27. Update `documentation/product/behavior/chat_app_capabilities.md` — tool counts: 53→56, categories still 9, MCP tools: 49→52
28. Update `documentation/features/tool_calling/README.md` — add 3 new tool descriptions, update counts
29. Update `documentation/product/ops/mcp_server_setup.md` — add 3 new MCP tools to conversation server section, update total: 49→52
30. Update `documentation/README.md` — update tool counts, add cross_conversation_search feature link
31. Create `documentation/features/cross_conversation_search/README.md` — feature docs covering FTS5 architecture, tools, UI, hooks, backfill
---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| FTS5 index corruption | Search stops working | `search_index.db` is separate from `users.db` — can be deleted and rebuilt from conversations without data loss. Add `rebuild_index()` management command. |
| Backfill slow for large deployments | Startup delay | Runs in background daemon thread, non-blocking. Log progress every 100 conversations. One-time cost: ~30s-2min for 1K conversations. |
| Message chunking misalignment after delete_message / edit_message | Stale chunks in FTS5 | Full reindex on delete/edit (rare operations). Both hooks documented in Section 3. |
| Title/summary update race with persist_current_turn | Slight staleness | Acceptable — next persist will re-sync. All hooks are fail-open (try/except, errors logged). |
| FTS5 not available in old SQLite | Tables fail to create | Python 3.8+ ships SQLite 3.25+, FTS5 included. Add startup check: `SELECT sqlite_version()` and verify >= 3.25. |
| Memory for loading conversations during backfill | High memory | Load one conversation at a time, call `gc.collect()` every 50 conversations. Backfill thread is daemon (dies with server). |
| **STORAGE_DIR mismatch** | MCP/tools use wrong DB | MCP server and tools.py read `STORAGE_DIR` env var; Flask reads `--folder` CLI arg. Both default to `"storage"`. Add startup sanity check warning (see Section 3b). Document that STORAGE_DIR must match --folder if non-default. |
| **Concurrent backfill + writes** | Potential SQLite locking | SQLite WAL mode allows concurrent readers + one writer. Use connection-per-call pattern (no long-lived connections). `search_index.db` is separate from `users.db` so no contention with existing DB operations. Test under load. |
| **Flag mutation — RESOLVED** | Flag changes not indexed | Found: `POST /set_flag/<conversation_id>/<flag>` at `endpoints/conversations.py:1147`. Sets `conversation.flag` at lines 1185/1193. Hook added to plan (see Section 3 table). No TBD remaining. |
| **get_conversation_summary with stale index** | Index lacks recently created conversations | If backfill hasn't reached a conversation yet, `get_summary()` returns null. Fallback: load conversation from disk directly via `Conversation.load_local()`. Document this fallback. |
---

## Future Extensibility

- **Embedding search:** Add a 4th table `ConversationSearchEmbeddings` with vector column. Use `sqlite-vec` extension or external vector DB. Hybrid search: FTS5 candidates → rerank with cosine similarity.
- **Cross-user search (team/shared):** The `user_email` UNINDEXED column already supports multi-user. Add permission checks.
- **Scroll-to-message in UI:** Future enhancement — when clicking a search result, scroll to the specific matching message. Requires passing `message_id` through to the frontend and adding scroll-to logic.
- **UI search-as-you-type previews:** Show conversation title matches as the user types (even before 5 chars) by querying the ConversationSearchState table directly (no FTS).

---

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| **In-memory BM25 (`rank_bm25` library)** | No incremental updates (full rebuild on every change: 2-10s for 50K docs). 800MB-1.2GB RAM for 50K conversations. No phrase search, prefix search, or snippet highlighting built-in. Requires pickling for persistence. FTS5 wins on every dimension except raw query latency (5-15ms vs 15-40ms — both fast enough). |
| **FTS5 with content table + triggers (PKB pattern)** | PKB uses this because source data IS in SQLite (claims table). Our source data is dill files on disk — no SQLite content table to trigger from. Direct FTS5 tables with explicit Python upserts is simpler and equally correct. |
| **FTS5 table inside `users.db`** | Would grow users.db, can't be rebuilt independently, and would share WAL/locking with all other operations. Separate `search_index.db` can be deleted and rebuilt without risk. |
| **Fan-out over per-conversation BM25 indexes** | Existing `message_search_index.json` files could be loaded and searched per-conversation. But O(N) disk reads per query where N = conversations. Unacceptably slow for 1K+ conversations. |
| **Elasticsearch / Meilisearch** | Overkill for single-user app. Adds external dependency, deployment complexity, and operational burden. SQLite FTS5 is zero-dependency (stdlib). |
| **Embedding/vector search** | Requires embedding model (extra dependency, GPU/API cost). Deferred to future enhancement — architecture supports adding a 4th table for embeddings. |
