# Cross-Conversation Search

Search across **all** conversations by keyword, phrase, or regex — from both LLM tools and a UI search modal.

## Motivation

Users accumulate hundreds of conversations. Per-conversation search (BM25 via `MessageSearchIndex`) already exists, but there was no way to search *across* conversations. This feature answers questions like:
- "Where did I discuss JWT token expiry?"
- "Find all conversations about database migration"
- "What was that Python snippet I worked on last week?"

## Architecture

### FTS5 Index (`search_index.db`)

A **separate** SQLite database at `{users_dir}/search_index.db` (alongside `users.db`) containing three tables:

| Table | Type | Purpose |
|---|---|---|
| `ConversationSearchMeta` | FTS5 | One row per conversation — title, summary, memory_pad, concatenated message TLDRs. **Fast path**: searched first. |
| `ConversationSearchMessages` | FTS5 | One row per ~10-message chunk — extracted headers, bold text, TLDRs. **Deep path**: searched when fast path returns too few results. |
| `ConversationSearchState` | Regular SQL | Filterable metadata — workspace_id, domain, flag, dates, message counts, friendly_id. |

**Design decisions:**
- Direct FTS5 tables (no content table, no triggers) — source data is dill-serialized files on disk, not in SQLite
- `porter unicode61` tokenizer for stemming and Unicode support
- Column weights: title (3.0) > summary (2.0) > message_tldrs (1.5) > memory_pad (1.0) > headers_and_bold (1.0)
- WAL mode for concurrent reads + single writer
- Separate from `users.db` — rebuildable, deletable without affecting core data
- FTS5 `snippet()` uses column index `-1` (best-matching column) for result snippets
- Post-search filter removes results with no title, no snippet, and 0 messages

### Index Manager (`code_common/cross_conversation_search.py`)

`CrossConversationIndex` class with methods:
- `index_conversation(conv)` — full index/reindex of one conversation
- `index_new_messages(conv, count)` — incremental: index only new messages since last index
- `update_metadata(conv)` — update title, summary, memory_pad, flag, workspace
- `remove_conversation(conv_id)` — delete from all 3 tables
- `backfill(folder, candidates)` — batch index existing conversations (startup)
- `search(user_email, query, ...)` — FTS5 search with BM25 ranking
- `list_conversations(user_email, ...)` — browse/filter without query
- `get_summary(conv_id, user_email)` — detailed view of one conversation

### Real-Time Indexing Hooks

All hooks are fail-open (wrapped in try/except, errors logged, never block the main operation).

| Hook Point | File | Trigger |
|---|---|---|
| `persist_current_turn()` | `Conversation.py` | After each turn — indexes new messages + updates metadata |
| `set_title()` | `Conversation.py` | Title change — updates metadata |
| `delete_message()` | `Conversation.py` | Message deleted — full reindex |
| `edit_message()` | `Conversation.py` | Message edited — full reindex |
| `delete_conversation` | `endpoints/conversations.py` | Conversation deleted — removes from index |
| `_create_conversation_simple()` | `endpoints/conversations.py` | New conversation — creates index entry |
| `set_flag()` | `endpoints/conversations.py` | Flag set/cleared — updates metadata |
| `move_conversation` | `endpoints/workspaces.py` | Workspace changed — targeted SQL UPDATE |

Conversations receive their `_cross_conv_index` via `get_conversation_with_keys()` in `endpoints/request_context.py`.

### Backfill Daemon

On server startup, a daemon thread finds conversations missing from the index (via LEFT JOIN against `UserToConversationId`) and indexes them. Non-blocking, progress logged every 100 conversations, GC every 50 to control memory. Truly empty conversations (no title, no summary, no memory_pad, no messages) are skipped during backfill.

**Re-indexing**: Delete `{users_dir}/search_index.db` and restart the server. The backfill daemon will recreate the tables and re-index all conversations. This is safe — the search index is fully derived from on-disk conversation data and affects no core functionality.

## Three New Tools

### 1. `search_conversations`
- **Category**: conversation
- **Parameters**: query (required), mode (keyword/phrase/regex), deep, workspace_id, date_from, date_to, flag, sender_filter, top_k
- **Returns**: Ranked results with title, snippet, friendly_id, score

### 2. `list_user_conversations`
- **Category**: conversation
- **Parameters**: workspace_id, domain, flag, date_from, date_to, sort_by, limit, offset
- **Returns**: Paginated conversation list with metadata

### 3. `get_conversation_summary`
- **Category**: conversation
- **Parameters**: conversation_id (accepts both full ID and friendly_id)
- **Returns**: Full details including summary, memory_pad, highlights (top 5 TLDRs)

All three are available via:
- **Tool-calling**: `code_common/tools.py` (3 `@register_tool` handlers)
- **MCP**: `mcp_server/conversation.py` (3 `@mcp.tool()` functions, port 8104)

## UI — Search Modal

- **Entry point**: Magnifying glass icon (`#search-conversations-btn`) in sidebar toolbar (`div.sidebar-toolbar-actions`)
- **Modal**: Bootstrap 4 modal (`#cross-conversation-search-modal`) with:
  - Debounced search input (500ms delay, minimum 5 characters for auto-search)
  - **Enter key**: fires search immediately with any non-empty query (bypasses 5-char minimum and debounce)
  - Collapsible filter row: workspace dropdown (populated from `/list_workspaces/{domain}`), flag, date range, deep search toggle
  - Result cards: title + flag badge, snippet with highlighted matches (`<b>` tags from FTS5 `snippet()` across best-matching column), date, message count, friendly_id
  - Click-to-navigate: opens the matching conversation via `ConversationManager.setActiveConversation()`
  - Empty/irrelevant results (no title, no snippet, 0 messages) are filtered out before display

## Flask Endpoint

`POST /search_conversations` (rate limit: 30/minute)

Three actions in one endpoint:
- `action=search` — FTS5 search (requires `query`)
- `action=list` — browse/filter (no query needed)
- `action=summary` — detailed view (requires `conversation_id`)

## Files Modified

| File | Change |
|---|---|
| `database/search_index.py` | **NEW** — FTS5 schema, connection helpers, CRUD, search queries |
| `database/__init__.py` | Export new module |
| `code_common/cross_conversation_search.py` | **NEW** — `CrossConversationIndex` class + `CROSS_CONVERSATION_TOOLS` dict |
| `endpoints/state.py` | Added `cross_conversation_index` field to `AppState` |
| `server.py` | Create search tables, index instance, backfill daemon, STORAGE_DIR sanity check |
| `endpoints/request_context.py` | Attach `_cross_conv_index` to conversations |
| `Conversation.py` | 4 hooks: persist_current_turn, set_title, delete_message, edit_message |
| `endpoints/conversations.py` | 3 hooks + `POST /search_conversations` endpoint |
| `endpoints/workspaces.py` | Hook in move_conversation |
| `code_common/tools.py` | 3 new `@register_tool` handlers |
| `mcp_server/conversation.py` | 3 new `@mcp.tool()` functions |
| `interface/interface.html` | Search button, modal HTML, script tag, option elements |
| `interface/cross-conversation-search.js` | **NEW** — Search modal manager |
| `interface/chat.js` | Updated `categoryDefaults.conversation` array |
| `interface/style.css` | Result card styles |

## Implementation Plan

Full plan: `documentation/planning/plans/cross_conversation_search.plan.md` (1061 lines)

## Implementation Notes

### Conversation Lazy Loading

The `Conversation` class uses `dill` serialization with **lazy-loaded fields**. Fields listed in `store_separate` (`memory`, `messages`, `uploaded_documents_list`, etc.) are stored as separate JSON files on disk and set to `None` on the dill-serialized `.index` file. After `Conversation.load_local()`, these fields are `None` until explicitly loaded via `conversation.get_field("memory")`.

The index manager's `_load_memory()` helper calls `get_field("memory")` to trigger the lazy load, and `_get_messages()` calls `get_field("messages")`. Properties like `running_summary`, `memory_pad`, `domain`, and `flag` are stored directly on the dill object or use `get_field` internally, so they work without special handling.

This matters for the **backfill path** (which loads conversations via `load_local`). The **real-time hooks** pass the live conversation object where fields are already in memory, so both paths work correctly.

### Field Location Reference

| Field | Storage | Access Pattern |
|---|---|---|
| `title` | `memory["title"]` (JSON file) | `get_field("memory")["title"]` |
| `messages` | Separate JSON file | `get_field("messages")` |
| `running_summary` | `_running_summary` (dill) + `memory["running_summary"]` | Property — calls `get_field` internally |
| `memory_pad` | `_memory_pad` (dill) | Property — direct attribute |
| `domain` | `_domain` (dill) | Property — direct attribute |
| `flag` | `_flag` (dill) | Property — direct attribute |
| `user_email` | `user_id` (dill) / `memory["user_email"]` | Attribute, then memory fallback |
| `workspace_id` | `memory["workspace_id"]` (JSON file) | `get_field("memory")["workspace_id"]` |
| `conversation_friendly_id` | `memory["conversation_friendly_id"]` (JSON file) | `get_field("memory")["conversation_friendly_id"]` |
| `last_updated` | `memory["last_updated"]` (JSON file) | `get_field("memory")["last_updated"]` |
| `created_at` | `memory["created_at"]` (JSON file) | `get_field("memory")["created_at"]` |
