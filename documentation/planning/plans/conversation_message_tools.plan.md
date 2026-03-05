# Conversation Message Tools — Implementation Plan

## Context
We are adding 5 new tools under a new `"conversation"` category:
- `search_messages` — BM25 keyword search + text/regex match within conversation
- `list_messages` — list messages with 300-char previews and TLDR
- `read_message` — read full message by ID or index
- `get_conversation_details` — summary, message count, IDs, docs, artefacts
- `get_conversation_memory_pad` — get the memory pad scratchpad

## Architecture
- **Shared metadata**: `code_common/conversation_search.py` has `CONVERSATION_TOOLS` dict with canonical tool names, descriptions, parameter schemas, and usage guidelines.
- **Search engine**: Same file has `MessageSearchIndex` class (BM25 + text search) and `extract_markdown_features()`.
- **Conversation methods**: `Conversation.py` gets 5 new methods + search index storage.
- **Tool-calling tools**: `code_common/tools.py` registers 5 tools importing metadata from `conversation_search.py`.
- **MCP tools**: `mcp_server/conversation.py` registers 5 MCP tools importing metadata from `conversation_search.py`.
- **UI**: `interface/interface.html` gets new `<optgroup>` and `interface/chat.js` gets `categoryDefaults` entry.

## File Changes

### code_common/conversation_search.py (NEW — DONE)
Contains: `extract_markdown_features()`, `tokenize_with_bigrams()`, `MessageSearchIndex`, `CONVERSATION_TOOLS` dict, `CONVERSATION_TOOL_NAMES` list.

### Conversation.py (MODIFY)
1. Add `"message_search_index"` to `store_separate` property (line 1163)
2. Add methods:
   - `_get_or_create_search_index()` — loads index from storage or builds from existing messages
   - `_index_messages_for_search(messages)` — indexes new messages incrementally
   - `search_messages(query, mode, sender_filter, top_k, ...)` — delegates to MessageSearchIndex
   - `list_messages(start, end, from_end, sender_filter)` — returns previews + TLDR
   - `read_message(message_id, index)` — returns full message + context
   - `get_conversation_details()` — comprehensive overview
3. Hook `_index_messages_for_search(preserved_messages)` into `persist_current_turn()` after line 3849

### code_common/tools.py (MODIFY)
Add after the memory section (~line 2536):
- Import: `from code_common.conversation_search import CONVERSATION_TOOLS`
- 5 new `@register_tool(**CONVERSATION_TOOLS["tool_name"])` handlers
- Each handler: parse args → `_conv_load(conversation_id)` → call Conversation method → ToolCallResult
- Pattern matches existing memory tools exactly

### mcp_server/conversation.py (MODIFY)
Add inside `create_conversation_mcp_app()` after tool 7:
- Import: `from code_common.conversation_search import CONVERSATION_TOOLS`
- 5 new `@mcp.tool()` functions
- Each function: load conversation → call method → return JSON
- Pattern matches existing MCP tools exactly

### interface/interface.html (MODIFY)
Add `<optgroup label="Conversation">` with 5 `<option>` elements in `#settings-tool-selector`

### interface/chat.js (MODIFY)
Add `conversation: ['search_messages', 'list_messages', 'read_message', 'get_conversation_details', 'get_conversation_memory_pad']` to `categoryDefaults` mapping in `setModalFromState()`
