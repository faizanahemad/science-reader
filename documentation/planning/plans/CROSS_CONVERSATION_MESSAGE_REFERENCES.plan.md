# Cross-Conversation Message References

**Created:** 2026-02-08  
**Updated:** 2026-02-09  
**Status:** Implemented (M0-M4 complete, M5 docs pending)  
**Depends On:** PKB v0.7 (universal @references), Hierarchical Workspace System (jsTree sidebar, vakata context menus)  
**Related Docs:**
- `documentation/planning/plans/PKB_V07_UNIVERSAL_REFERENCES.plan.md` — existing @reference system
- `documentation/planning/plans/HIERARCHICAL_WORKSPACE_SYSTEM.plan.md` — jsTree sidebar, workspace hierarchy
- `documentation/features/workspaces/README.md` — workspace implementation details (jsTree, vakata, data model)
- `documentation/features/truth_management_system/pkb_reference_resolution_flow.md` — PKB reference resolution flow
- `documentation/features/conversation_flow/README.md` — message flow, streaming, persistence, sidebar selection

**Change Log:**
- 2026-02-09 (v2): Major update after Hierarchical Workspace System implementation.
  - Updated all line numbers to match post-workspace-rewrite codebase.
  - UI: Changed from "tooltip + context menu" to **context menu ONLY** for sidebar conversation reference copy. No inline display of friendly ID in jsTree. Keeps tree clean.
  - Backend: Changed conversation loading strategy to dependency injection via `query["_conversation_loader"]` for cache-aware loading.
  - New file: `conversation_reference_utils.py` — utility module for ID generation (instead of adding to Conversation.py).
  - Added concrete code for `_ensure_conversation_friendly_id()`, backfill logic, streaming hash updates, and the full reference regex with greedy match explanation.
  - Added detailed data flow section for how `conversation_friendly_id` reaches the frontend context menu.
  - Expanded testing plan with specific test cases and edge cases.
  - Added correct ConversationManager property management for `activeConversationFriendlyId`.
  - Added within-request caching for cross-conversation loads.

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals](#goals)
3. [Current State](#current-state)
4. [Design: Conversation and Message Identifiers](#design-conversation-and-message-identifiers)
5. [Reference Syntax](#reference-syntax)
6. [Backend Resolution Strategy](#backend-resolution-strategy)
7. [UI Changes](#ui-changes)
8. [Autocomplete Strategy](#autocomplete-strategy)
9. [Complete Data Flow (End-to-End)](#complete-data-flow-end-to-end)
10. [Implementation Plan](#implementation-plan)
11. [Testing Plan](#testing-plan)
12. [Risks and Mitigations](#risks-and-mitigations)
13. [Files to Create/Modify (Summary)](#files-to-createmodify-summary)
14. [Implementation Ordering and Dependencies](#implementation-ordering-and-dependencies)

---

## Problem Statement

Today the `@reference` system allows users to pull in PKB memories (claims, contexts, entities, tags, domains) into their current conversation. However, users frequently want to refer to **specific messages from other conversations** — for example:

- "In that conversation about React optimization, you gave me a great component structure — use it here."
- "Apply the SQL pattern from message 3 of our database design chat to this new schema."
- "Continue the analysis from @database_design_b4f2_message_5."

Currently there is **no mechanism** to reference a message from another conversation (or even from earlier in the current conversation by a stable identifier). The only way to reuse content from another conversation is to manually copy-paste it, which is fragile and loses context.

**Why this matters:**

1. **Knowledge reuse across conversations.** Users build up valuable context, code snippets, analyses, and explanations across many conversations. Today that knowledge is siloed — each conversation is a completely isolated object with no cross-links.

2. **Continuity of thought.** A user might start a design discussion in one conversation and want to reference a specific decision or explanation later. The PKB captures extracted *facts*, but the original reasoning, code, or detailed explanation lives only in the conversation message.

3. **PKB captures claims, not messages.** The PKB distills conversation content into atomic claims. But sometimes the user wants the *full original message* — the code block, the step-by-step analysis, the formatted explanation — not a one-line distilled fact.

4. **Discoverability.** Users don't remember conversation IDs (which are long opaque strings like `user@example.com_a8f3b2c1d4e5...`). They need short, memorable, human-readable conversation identifiers and per-message identifiers they can easily find and copy.

**What we need:**

- A way to identify conversations with short, friendly names (like PKB friendly IDs).
- A way to identify individual messages within a conversation by index or content hash.
- A reference syntax that works with the existing `@reference` system.
- UI affordances so users can discover and copy these identifiers easily.
- Backend resolution that can load a message from another conversation and inject it into the current conversation's LLM context.

---

## Goals

1. **Users can reference any message from any of their conversations** using an `@` reference syntax like `@conv_<conversation_friendly_id>_message_<index_or_hash>`.

2. **Conversation friendly IDs are short, human-readable, and memorable** — derived from the conversation title (2 indicative words) plus a 4-character alphanumeric hash of title + creation time. Example: `react_optimization_b4f2`.

3. **Message hashes are stable and copyable** — derived from message content + conversation friendly_id, producing a 6-character alphanumeric hash. Example: `a3f2b1`. Message index (1-based) is also supported as an alternative.

4. **No ambiguity with existing PKB references** — conversation message references use a distinctive prefix/suffix pattern (`conv_..._message_...`) that cannot collide with claim, context, entity, tag, or domain friendly IDs.

5. **Users can easily discover identifiers from the UI:**
   - Conversation friendly name is accessible via the sidebar context menu ("Copy Conversation Reference" item). It is NOT shown inline beside the conversation title in the jsTree view — we keep the tree clean.
   - Message hash is visible in the message card header (beside "You" / "Assistant") as a small monospace badge.
   - Both are copyable with a click.

6. **Backwards compatible** — all existing `@reference` patterns continue to work. The new conversation message references are a new branch in `resolve_reference()` or handled in `_get_pkb_context()` before the PKB resolution path.

7. **Autocomplete is addressed pragmatically** — full autocomplete for cross-conversation messages is complex (would need to search across all conversations). A simpler two-step approach or a conversation-search endpoint is preferred over trying to fit this into the existing single-dropdown autocomplete.

---

## Current State

### How Conversations Are Identified Today

| Identifier | Format | Example | Where Used |
|-----------|--------|---------|------------|
| `conversation_id` | `{email}_{36 random alphanumeric}` | `user@ex.com_a8f3b2c1d4e5f6...` | URLs, API routes, storage paths, DB keys |
| `title` | LLM-generated free text | `"React Performance Optimization"` | Sidebar display, metadata |
| `summary_till_now` | LLM-generated rolling summary | `"Discussed component memoization..."` | Sidebar display (truncated to 60 chars) |

- **No friendly_id** exists for conversations. The `conversation_id` is long and opaque — not suitable for human reference.
- Generated in `endpoints/conversations.py:_create_conversation_simple()` (lines 1096-1130): `email + "_" + "".join(secrets.choice(_ALPHABET) for _ in range(36))` — 36 random alphanumeric chars appended to email.
- Title is auto-generated by an LLM in `Conversation.persist_current_turn()` (lines 3009-3187) after the first message is persisted. Title parsed from LLM response at line 3175 and stored at line 3187 (only if `title_force_set` is False). Can be manually set via `/title` slash command.

### How Messages Are Identified Today

| Identifier | Format | Example | Where Used |
|-----------|--------|---------|------------|
| `message_id` | `str(mmh3.hash(conv_id + user_id + text))` | `"3847291234"` | DOM attributes, delete/edit/move actions |
| `message-index` | Client-side count of cards in `#chatView` | `0, 1, 2, ...` (0-based) | DOM `message-index` attribute |

- `message_id` is generated by `Conversation.get_message_ids()` using MurmurHash3 on `conversation_id + user_id + messageText`. It's deterministic but not human-readable.
- `message-index` is computed client-side from DOM card count — it's positional and not persisted.
- Neither identifier is designed for human reference or cross-conversation use.

### How Messages Are Stored

Each conversation stores messages as a JSON array in `{conversation_id}-messages.json`:

```json
[
  {
    "message_id": "3847291234",
    "text": "How do I optimize React renders?",
    "show_hide": "show",
    "sender": "user",
    "user_id": "user@example.com",
    "conversation_id": "user@example.com_a8f3b2c1..."
  },
  {
    "message_id": "9182736450",
    "text": "Here are several strategies for React optimization...",
    "show_hide": "show",
    "sender": "model",
    "user_id": "user@example.com",
    "conversation_id": "user@example.com_a8f3b2c1...",
    "config": {"model": "claude-opus-4"},
    "answer_tldr": "..."
  }
]
```

### How Conversations Are Loaded

- `Conversation.load_local(folder)` deserializes from dill `.index` file.
- `conversation_cache` (`DefaultDictQueue` in `server.py`, maxsize=200) is an LRU cache that auto-loads from disk when accessed by `conversation_id`.
- Loading any conversation is: `state.conversation_cache[conversation_id]` — returns a `Conversation` object.
- Messages are then: `conversation.get_message_list()` (line 7584-7586) — returns `self.get_field("messages")`, the raw JSON array.

### Cross-Conversation Access Today

**None exists.** Each conversation is fully self-contained:
- `_get_pkb_context()` only accesses the PKB (shared claim store), never other conversations.
- No endpoint queries across multiple conversations for message content.
- The `conversation_cache` *can* load any conversation by ID, but this capability is only used for single-conversation endpoints, never for cross-referencing.
- The only shared knowledge store is the PKB (`pkb.sqlite`), which stores extracted claims, not raw messages.

### How @References Work Today (Relevant Parts)

**UI parsing** (`parseMemoryReferences()` in `parseMessageForCheckBoxes.js`, lines 375-458):
- Friendly ID regex (line 410): `/@([a-zA-Z][a-zA-Z0-9_-]{2,})/g` captures friendly IDs into `friendlyIds[]`.
- Additional checks: must be preceded by start-of-string or whitespace (line 417), skips legacy `@memory:/@mem:` overlaps (lines 422-429).
- Returns `{ cleanText, claimIds, friendlyIds }`.
- `friendlyIds` are sent in the POST body as `referenced_friendly_ids`.

**Backend resolution** (`_get_pkb_context()` in `Conversation.py`, lines 310-614):
- Referenced friendly IDs resolved at lines 385-406: iterates `referenced_friendly_ids`, calls `api.resolve_reference(fid)` on the PKB `StructuredAPI`.
- Resolved claims are labeled `[REFERENCED @fid]` and given highest priority (Priority 0).
- The formatted context is injected into the LLM prompt.
- Post-distillation, `_extract_referenced_claims()` (lines 250-308) re-injects `[REFERENCED ...]` claims verbatim.

**resolve_reference()** (`structured_api.py`, line 1159+):
- Uses suffix-based routing: `_context`, `_entity`, `_tag`, `_domain` suffixes route directly.
- No suffix → backwards-compatible path (claim_number → claim friendly_id → context friendly_id → context name).
- **No handling for conversation or message references** — these would be a new branch, intercepted in `_get_pkb_context()` before the PKB resolution loop.

### Sidebar UI Today (jsTree-based — post Hierarchical Workspace rewrite)

The sidebar was fully rewritten to use **jsTree 3.3.17** with vakata context menus. The old `createConversationElement()` with custom HTML divs no longer exists.

**Conversation nodes** are jsTree data objects built in `workspace-manager.js:buildJsTreeData()` (lines 270-315):
```javascript
// Lines 291-312
{
    id: 'cv_' + conv.conversation_id,
    parent: 'ws_' + wsId,
    text: title,            // conv.title ? conv.title.trim() : '(untitled)'  (line 294)
    type: 'conversation',
    li_attr: {
        'data-conversation-id': conv.conversation_id,
        'data-flag': conv.flag || 'none',
        'class': ' jstree-flag-' + flag   // only if flag !== 'none'
    },
    a_attr: {
        title: conv.title || '',
        'data-conversation-id': conv.conversation_id
    }
}
```

**Workspace nodes** (lines 275-288):
```javascript
{
    id: 'ws_' + ws.workspace_id,
    parent: ws.parent_workspace_id ? ('ws_' + ws.parent_workspace_id) : '#',
    text: displayName + ' (N)',  // N = conversation count, omitted if 0
    type: 'workspace',
    state: { opened: ws.expanded },
    li_attr: { 'data-workspace-id': ws.workspace_id, 'data-color': ws.color },
    a_attr: { title: displayName }
}
```

**Context menus** use `$.vakata.context.show()` with custom item builders (via `showNodeContextMenu()` → `buildContextMenuItems()` → `_convertToVakataItems()`):
- `buildConversationContextMenu(node)` (lines 646-713) — items: Open in New Window, Clone, Toggle Stateless, Set Flag (submenu), Move to... (submenu), Delete.
- `buildWorkspaceContextMenu(node)` (lines 601-644) — items: New Conversation, New Sub-Workspace, Rename, Change Color, Move to... (submenu), Delete.

These are natural extension points for adding "Copy Conversation Reference" actions. Each context menu item has: `label`, `icon`, `action`, optional `_disabled`, optional `submenu`, optional `separator_before`/`separator_after`.

**Triple-dot buttons** (`addTripleDotButtons()`) add `<span class="jstree-node-menu-btn"><i class="fa fa-ellipsis-v"></i></span>` after each `<a class="jstree-anchor">` to trigger context menus on click. They are re-added on `ready.jstree`, `redraw.jstree`, and `after_open.jstree` events.

**Data flow**: `loadConversationsWithWorkspaces()` → parallel AJAX for `GET /list_workspaces/{domain}` + `GET /list_conversation_by_user/{domain}` → builds workspacesMap (with `parent_workspace_id`) + groups conversations by workspace → `renderTree(convByWs)` (lines 320-457) → `buildJsTreeData()` → `$('#workspaces-container').jstree({core: {data: treeData}, themes: 'default-dark', types: {workspace, conversation}, plugins: ['types','wholerow','contextmenu']})`.

**Important:** The `conversation` metadata returned by `list_conversation_by_user` currently includes: `conversation_id`, `user_id`, `title`, `summary_till_now`, `domain`, `flag`, `last_updated`, `conversation_settings`, `workspace_id`, `workspace_name`. We will add `conversation_friendly_id` to this payload so the frontend can access it in `buildJsTreeData()` and context menu builders.

### Message Card Header Today

In `common-chat.js:renderMessages()` (lines 2200-2400+, header built at lines 2259-2278):
```html
<div class="card-header d-flex justify-content-between align-items-center"
     message-index="${messageIndex}" message-id="${messageId}">
    <div class="d-flex align-items-center">
        <input type="checkbox" class="history-message-checkbox"
               message-index="${messageIndex}" message-id="${messageId}" ...>
        <small><small><strong>You / Assistant</strong></small></small>
        ${actionDropdown}   <!-- Show Doubts, Ask New Doubt, Move Up/Down, Artefacts, Delete -->
    </div>
    <div class="d-flex align-items-center">
        <button class="copy-btn-header" title="Copy Text">...</button>
        <div class="dropdown vote-menu-toggle">...</div>  <!-- initialised by initialiseVoteBank() -->
    </div>
</div>
```

**Streaming message_ids handling** in `renderStreamingResponse()` (lines 874-1542):
- `message_ids` arrive at lines 1210-1235: `part['message_ids']` contains `user_message_id` and `response_message_id`.
- These are set on checkbox, card-header, delete, doubts, and move buttons' `message-id` attributes.
- This is the integration point for also sending `message_short_hash` values.

### Key Files Summary

| Area | File | Relevant Lines/Functions |
|------|------|------------------------|
| Conversation constructor | `Conversation.py` | Lines 187-232, `__init__()` — stores `conversation_id`, `user_id`, `_storage`, `memory` dict, `messages` list |
| Message ID generation | `Conversation.py` | `get_message_ids()` — hashes `(conversation_id + user_id + messageText)` via mmh3 |
| Message persistence | `Conversation.py` | Lines 2988-3211, `persist_current_turn()` — title generated lines 3009-3087, parsed at 3175, stored at 3187; messages stored at lines 3106-3134 |
| Conversation metadata | `Conversation.py` | Lines 7588-7607, `get_metadata()` — returns dict with: `conversation_id`, `user_id`, `title`, `summary_till_now`, `domain`, `flag`, `last_updated`, `conversation_settings` |
| Message list access | `Conversation.py` | Lines 7584-7586, `get_message_list()` — returns `self.get_field("messages")` |
| PKB context retrieval | `Conversation.py` | Lines 310-614, `_get_pkb_context()` — referenced friendly IDs resolved at lines 385-406 |
| Referenced claims extraction | `Conversation.py` | Lines 250-308, `_extract_referenced_claims()` — static method, splits on `r"(?=^- \[|\n- \[)"`, keeps `[REFERENCED` bullets |
| reply() entry point | `Conversation.py` | Lines 4717-4900+, `reply()` — `pkb_context_future` created at lines 4804-4815; query fields extracted at lines 4764-4781 |
| conversation_id generation | `endpoints/conversations.py` | Lines 1096-1130, `_create_conversation_simple()` — `email + "_" + 36-char random` |
| Conversation list endpoint | `endpoints/conversations.py` | Lines 1133-1235, `list_conversation_by_user()` — DB fetch at 1147, metadata built at 1191-1202, augmented with workspace_id/name/domain |
| Message list endpoint | `endpoints/conversations.py` | Lines 63-86, `list_messages_by_conversation()` — returns `conversation.get_message_list()` as JSON |
| Send message handler | `endpoints/conversations.py` | Lines 1281-1431, `/send_message/<conversation_id>` — query=request.json at 1309, pinned IDs injected at 1317-1320, streaming at 1345 |
| Conversation cache | `server.py` | `load_conversation()` + `DefaultDictQueue` — LRU cache (maxsize=200) keyed by conversation_id |
| Sidebar rendering (jsTree) | `interface/workspace-manager.js` | Lines 270-315 `buildJsTreeData()`; Lines 320-457 `renderTree()`; Lines 646-713 `buildConversationContextMenu()`; Lines 601-644 `buildWorkspaceContextMenu()` |
| Context menu infrastructure | `interface/workspace-manager.js` | `showNodeContextMenu()` → `buildContextMenuItems()` → `_convertToVakataItems()` → `$.vakata.context.show()` |
| Message card header | `interface/common-chat.js` | Lines 2259-2278, `renderMessages()` — card-header with checkbox, sender label, action dropdown, copy btn, vote menu |
| Streaming message_ids | `interface/common-chat.js` | Lines 1210-1235 in `renderStreamingResponse()` |
| @reference parsing (UI) | `interface/parseMessageForCheckBoxes.js` | Lines 375-458, `parseMemoryReferences()` — regex at line 410: `/@([a-zA-Z][a-zA-Z0-9_-]{2,})/g` |
| @reference resolution (backend) | `truth_management_system/interface/structured_api.py` | Line 1159+, `resolve_reference()` — suffix-based routing |
| PKB autocomplete (UI) | `interface/common-chat.js` | Lines 3428-3511, `fetchAutocompleteResults()` — calls `PKBManager.searchAutocomplete()`, builds results from 5 categories |
| Friendly ID generation | `truth_management_system/utils.py` | Lines 438-646 `generate_friendly_id()`, Lines 780-808 `_extract_meaningful_words()` |
| DB tables | `database/connection.py` | Lines 65-231, `create_tables()` — `UserToConversationId` (80-85), `ConversationIdToWorkspaceId` (96-102), `WorkspaceMetadata` (105-114) |
| DB conversation helpers | `database/conversations.py` | 279 lines — `addConversation()` (50), `getCoversationsForUser()` (121), `deleteConversationForUser()` (186) |
| DB workspace helpers | `database/workspaces.py` | 613 lines — `load_workspaces_for_user()` (27), `createWorkspace()` (392), `moveWorkspaceToParent()` (299), `deleteWorkspace()` (516) |

## Design: Conversation and Message Identifiers

This feature needs identifiers that are:
- short and human-copyable
- stable over time (survive reloads / storage)
- unambiguous (avoid collisions with PKB friendly IDs)
- resolvable server-side without expensive global scans

### Conversation Friendly ID (new)

We will introduce a new conversation-level identifier: `conversation_friendly_id`.

**Generation timing**
- Create the friendly ID the first time a conversation becomes "real" (when the first user+assistant message pair is persisted).
- Concretely: in `Conversation.persist_current_turn()` after the title is generated and assigned for the first turn (the same place the title is set today).

**Algorithm (deterministic given title + creation time)**

Inputs:
- `title`: conversation title string
- `created_at`: the creation timestamp for the conversation (captured once, stored)

Output:
- `conversation_friendly_id` of the form:
  - `{w1}_{w2}_{h4}`
  - where `w1`, `w2` are the first 2 meaningful words from the title (lowercase, stopwords removed)
  - and `h4` is a 4-character lowercase alphanumeric hash derived from `(title + created_at)`

Notes:
- Use the same word cleaning + stopword removal philosophy as `truth_management_system/utils.py:_extract_meaningful_words()`.
- Hash generation should match existing repo patterns:
  - prefer `mmh3.hash(..., signed=False)` and then map to a base36 alphabet (a-z0-9) and take 4 chars, OR
  - use `hashlib.md5(...).hexdigest()` and map to base36, or take 4 from an existing alphanumeric encoding.
- Store `created_at` once (string) so the friendly ID remains stable.

**Collision handling**

Collisions are unlikely but must be handled (two conversations can share the same title created at similar times).

Strategy:
1. Compute candidate `conversation_friendly_id`.
2. Check for an existing mapping for this user+domain with the same friendly ID.
3. If collision, re-hash with a salt (e.g. append `conversation_id` to the hash input) and retry.

This requires a DB-backed lookup (see section 6) rather than only storing friendly_id inside the conversation memory JSON.

**Where it lives (storage)**

We store the friendly ID in two places:
- Conversation storage (for portability): in `memory` dict as `memory["conversation_friendly_id"]` and `memory["created_at"]`.
- Users DB (for lookup): add `conversation_friendly_id TEXT` column to the `UserToConversationId` table.

**DB schema change (concrete)**

The `UserToConversationId` table currently has columns: `user_email, conversation_id, created_at, updated_at` (defined at lines 80-85 in `database/connection.py`). There is a unique index `idx_UserToConversationId_email_doc` on `(user_email, conversation_id)` (lines 155-157). We add:

```sql
ALTER TABLE UserToConversationId ADD COLUMN conversation_friendly_id TEXT;
CREATE INDEX IF NOT EXISTS idx_UserToConversationId_friendly_id
    ON UserToConversationId (user_email, conversation_friendly_id);
```

This follows the same pattern as the `parent_workspace_id` migration in `database/connection.py` (lines 170-180): idempotent `ALTER TABLE` in a try/except block inside `create_tables()`. Place the new migration after the existing `parent_workspace_id` migration (after line 180) and before the `DoubtsClearing` migration (line 182).

Note: `UserToConversationId` is not domain-scoped (no `domain` column). We scope collision checks to `user_email` only. Since conversations belong to a single user and the conversation list endpoint already filters by domain, this is sufficient. Two conversations from different domains for the same user could theoretically collide, but this is handled by the collision-retry logic (since `created_at` will differ).

**Concrete helper functions (database/conversations.py)**

```python
def setConversationFriendlyId(
    *, users_dir: str, user_email: str, conversation_id: str,
    conversation_friendly_id: str
) -> None:
    """Set the friendly_id for a conversation in the DB mapping."""
    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "UPDATE UserToConversationId SET conversation_friendly_id=? "
        "WHERE user_email=? AND conversation_id=?",
        (conversation_friendly_id, user_email, conversation_id),
    )
    conn.commit()
    conn.close()

def getConversationIdByFriendlyId(
    *, users_dir: str, user_email: str, conversation_friendly_id: str
) -> Optional[str]:
    """Look up conversation_id from a conversation_friendly_id for a user."""
    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "SELECT conversation_id FROM UserToConversationId "
        "WHERE user_email=? AND conversation_friendly_id=?",
        (user_email, conversation_friendly_id),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def conversationFriendlyIdExists(
    *, users_dir: str, user_email: str, conversation_friendly_id: str
) -> bool:
    """Check if a conversation_friendly_id already exists for this user."""
    conn = create_connection(_db_path(users_dir=users_dir))
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM UserToConversationId "
        "WHERE user_email=? AND conversation_friendly_id=?",
        (user_email, conversation_friendly_id),
    )
    exists = cur.fetchone() is not None
    conn.close()
    return exists
```

**Concrete ID generation function — new file: `conversation_reference_utils.py`**

We create a separate utility module rather than adding to `Conversation.py` (which is already 7600+ lines). This module is small, testable, and can be imported by both `Conversation.py` and `endpoints/conversations.py`.

```python
"""
conversation_reference_utils.py

Utilities for generating human-readable cross-conversation reference identifiers.

Provides:
- generate_conversation_friendly_id(title, created_at) -> str
    Produces a short ID like "react_optimization_b4f2" from conversation title + creation time.
- generate_message_short_hash(conversation_friendly_id, message_text) -> str
    Produces a 6-char hash like "a3f2b1" for a specific message.
- _to_base36(num, length) -> str
    Helper to convert unsigned integer to fixed-length base36 string.

These are used for the cross-conversation message reference system that lets users
reference specific messages from other conversations using @conversation_<fid>_message_<hash>.
"""

import mmh3
import string

_BASE36 = string.ascii_lowercase + string.digits  # 'abcdefghijklmnopqrstuvwxyz0123456789'

def _to_base36(num: int, length: int) -> str:
    """
    Convert unsigned integer to fixed-length base36 string.

    Parameters
    ----------
    num : int
        Non-negative integer to convert.
    length : int
        Desired output length (zero-padded if needed).

    Returns
    -------
    str
        Fixed-length base36 string (lowercase a-z, 0-9).
    """
    result = []
    for _ in range(length):
        result.append(_BASE36[num % 36])
        num //= 36
    return ''.join(reversed(result))

def generate_conversation_friendly_id(title: str, created_at: str) -> str:
    """
    Generate a short, human-readable conversation identifier.

    Format: {w1}_{w2}_{h4}
    - w1, w2: first 2 meaningful words from title (lowercase, stopwords removed)
    - h4: 4-char base36 hash of (title + created_at)

    Parameters
    ----------
    title : str
        The conversation title string.
    created_at : str
        Stable creation timestamp string (ISO format or any consistent format).

    Returns
    -------
    str
        Conversation friendly ID like "react_optimization_b4f2".

    Notes
    -----
    Uses the same stopword removal as truth_management_system/utils.py:_extract_meaningful_words().
    That function is private (prefixed with _) but is a stable utility within the TMS module.
    If this import becomes an issue, we can copy the ~30-line stopword list and word extraction
    logic directly into this module.
    """
    from truth_management_system.utils import _extract_meaningful_words
    words = _extract_meaningful_words(title, max_words=2)
    if not words:
        words = ['chat']
    base = '_'.join(words)
    h = mmh3.hash(title + created_at, signed=False)
    suffix = _to_base36(h, 4)
    return f"{base}_{suffix}"

def generate_message_short_hash(conversation_friendly_id: str, message_text: str) -> str:
    """
    Generate a 6-char base36 hash for a message.

    Parameters
    ----------
    conversation_friendly_id : str
        The conversation's friendly ID (e.g. "react_optimization_b4f2").
    message_text : str
        The full text of the message.

    Returns
    -------
    str
        6-char lowercase alphanumeric hash (e.g. "a3f2b1").
    """
    h = mmh3.hash(conversation_friendly_id + message_text, signed=False)
    return _to_base36(h, 6)
```

**Import note:** `_extract_meaningful_words` from `truth_management_system/utils.py` (lines 780-808) is a private function. It is stable and well-tested within TMS. The import `from truth_management_system.utils import _extract_meaningful_words` works because Python does not enforce the `_` prefix convention at the module level. If this import becomes problematic (e.g., TMS module refactoring), the function is simple (~30 lines) and can be copied into `conversation_reference_utils.py`.

**Alternative approach (if we want zero TMS dependency):** Extract the ~80 stopwords from `_extract_meaningful_words` and reimplement the 10-line word extraction inline. This makes the module fully self-contained.

### Message Short Hash (new)

We will introduce a short message identifier intended for humans: `message_short_hash`.

**Goal**: a 6-character lowercase alphanumeric code that can be displayed in the card header and used in references.

**Algorithm (deterministic)**

Inputs:
- `conversation_friendly_id`
- `message text` (the exact stored `text` field)

Output:
- `message_short_hash` of the form `{h6}` where `h6` is base36 and length 6.

Implementation approach consistent with repo:
- Use `mmh3.hash(conversation_friendly_id + message_text, signed=False)` and then base36 encode.
- Alternatively, mimic existing patterns where a 6-digit hash is derived by truncating `str(mmh3.hash(...))[:6]` (seen in multiple agents), but base36 is preferable because it is more compact and less biased.

**Where it lives**

We do NOT strictly need to persist `message_short_hash` if it can be recomputed from stored content and `conversation_friendly_id`.

However, to make UI rendering and cross-conversation resolution simple and stable even if message text is edited, we have two options:

Option A (recompute):
- do not store hash, compute on the fly from current `text`.
- pro: no migrations
- con: edits change hashes, references break

Option B (persist):
- store `message_short_hash` in each message dict at persistence time.
- pro: references survive later edits
- con: requires updating stored messages structure and possibly backfilling.

Recommended: Option B.

### Message Index

We also support 1-based message indexing within a conversation.

Definition:
- **Message index** is 1-based over the persisted `messages` list returned by `Conversation.get_message_list()`.
- It counts *each message*, not user+assistant pair.
  - i.e. first user message is index 1, first assistant response is index 2, next user message index 3, etc.

Rationale:
- Easy for users to understand.
- Works even without hashes.

### Relationship to Existing IDs

Existing `message_id` and `conversation_id` remain the system's internal identifiers:
- `conversation_id`: opaque primary ID used in URLs, storage, and DB keys.
- `message_id`: numeric string from `mmh3.hash(conversation_id + user_id + messageText)` used for per-message actions.

The new identifiers are **additional**:
- `conversation_friendly_id`: discoverable and copyable.
- `message_short_hash`: discoverable and copyable.
- message index: positional reference.

## Reference Syntax

We add a new `@` reference family dedicated to conversation messages. It is intentionally verbose and structured to avoid collisions with PKB friendly IDs.

### Primary Syntax (recommended)

```
@conversation_<conv_friendly_id>_message_<index_or_hash>
```

Examples:
- By index: `@conversation_react_optimization_b4f2_message_5`
- By message short hash: `@conversation_react_optimization_b4f2_message_a3f2b1`

Where:
- `conv_friendly_id` is the new conversation friendly ID (section 4)
- `index_or_hash` is either:
  - a positive integer (`[1-9][0-9]*`) meaning 1-based message index, OR
  - a 6-character lowercase alphanumeric message short hash (`[a-z0-9]{6}`)

### Alternate Short Alias (optional)

If the long prefix is too heavy, we can support a shorter alias as a pure parser convenience:

```
@conv_<conv_friendly_id>_msg_<index_or_hash>
```

This should resolve identically to the primary syntax. The UI can still insert the longer canonical form.

### Reserved Prefix

To prevent collisions with PKB friendly IDs and to make parsing simple, we reserve:
- `conversation_` (and optionally `conv_`) as prefixes for cross-conversation references.

Because the PKB-friendly-ID regex already captures `@([a-zA-Z][a-zA-Z0-9_-]{2,})`, these references will arrive in `referenced_friendly_ids` as full strings like:
- `conversation_react_optimization_b4f2_message_5`

### Parsing Rules

Client-side parsing should:
- treat these references the same as other `@friendly_id` references (i.e. keep using `friendlyIds[]`)
- NOT strip them from `cleanText` in a way that loses meaning; current behavior removes matched `@...` substrings from the query text before sending (this is already the behavior for PKB references). That is acceptable as long as the referenced message content is injected as context.

Backend parsing should:
- detect the `conversation_..._message_...` pattern before passing the identifier to PKB `StructuredAPI.resolve_reference()`.

### Formatting and Injection Contract

When resolved, the backend will format the referenced message content into an injected context block that is:
- clearly labeled
- includes source conversation friendly ID and message index/hash
- includes sender (You vs Assistant)

Example injected block (conceptual):

```
[REFERENCED @conversation_react_optimization_b4f2_message_5]
Conversation: react_optimization_b4f2
Message: #5 (user)
---
<message text>
```

Important: the prefix `[REFERENCED ...]` ensures this content can be preserved in the post-distillation reinjection path if we reuse the existing `_extract_referenced_claims()` logic (section 6).

## Backend Resolution Strategy

We need to resolve `@conversation_<conv_friendly_id>_message_<index/hash>` into an actual message text (and metadata) and inject it into the current prompt.

### Where Resolution Happens

We will resolve cross-conversation message references in the same stage as PKB reference resolution, because:
- the UI already ships `referenced_friendly_ids` in the `/send_message` request
- `_get_pkb_context()` already contains the highest-priority referenced resolution step and formatting logic
- resolution is mostly I/O (load another conversation's messages), so doing it alongside PKB retrieval reduces end-to-end latency

There are two viable integration options.

Option 1 (recommended): Extend `_get_pkb_context()` to resolve conversation-message references first
- In `Conversation._get_pkb_context()`, before calling `StructuredAPI.resolve_reference(fid)`, check if `fid` matches the `conversation_..._message_...` pattern.
- If yes, resolve it locally by loading the referenced conversation and message.
- Append a new line in the same `context_lines` format using a `[REFERENCED @...]` prefix.

Pros:
- Minimal new concurrency paths (already running in a background future)
- Keeps all referenced resolution in one place
- Reuses existing formatting and dedup behavior

Cons:
- `_get_pkb_context()` becomes "PKB + cross-conversation" rather than PKB-only

Option 2: Separate future
- Add a second async future next to `pkb_context_future` for cross-conversation references.
- Merge the resulting text into `user_info_text` alongside PKB context.

Pros:
- Keeps PKB function pure

Cons:
- More wiring; more places to keep formatting consistent

We will implement Option 1.

### Conversation Lookup: conv_friendly_id -> conversation_id

To resolve a conversation reference we need a fast lookup mapping.

**Add a new column to the DB mapping table**:
- Table: `UserToConversationId`
- New column: `conversation_friendly_id TEXT`
- Index: `(user_email, conversation_friendly_id)`

Add DB helpers in `database/conversations.py`:
- `getConversationIdByFriendlyId(user_email: str, domain: str, conversation_friendly_id: str) -> Optional[str]`
- `setConversationFriendlyId(user_email: str, conversation_id: str, domain: str, conversation_friendly_id: str) -> None`

The domain is included because the UI routes by domain and the DB rows are domain-scoped in practice; if the table is not domain-scoped, the lookup must still be constrained to the user's conversations in that domain.

### Loading the Referenced Conversation

We can load another conversation in two ways:

**Option A: Cache-aware (best performance):**
- Use `state.conversation_cache[conversation_id]`.
- But `Conversation.py` does not have access to `state`. The `conversation_cache` is a `DefaultDictQueue` (maxsize=200) in `server.py` that auto-loads from disk when accessed.

**Option B: Direct disk load (no new dependencies):**
- Use `Conversation.load_local(folder_path)`.
- The conversation root folder can be derived from `self._storage`:
  - `self._storage` is set at `__init__` line 193-194 and is the path to the conversation folder (e.g. `storage/conversations/domain/conv_id/`)
  - `conv_root = os.path.dirname(self._storage)` gives the domain-level conversation directory
  - `other_path = os.path.join(conv_root, other_conversation_id)` gives the other conversation's folder
- This avoids importing endpoint state.

**Option C: Dependency injection via query dict:**
- Inject a `conversation_loader` callable into `query` (alongside `conversation_pinned_claim_ids` at line 1317-1320 in `endpoints/conversations.py`).
- But Python callables cannot be JSON-serialized, so this only works if we inject post-JSON-parsing.
- In practice, the endpoint handler constructs `query = request.json` (line 1309) then augments it (line 1317+). We can inject a loader function at this point:
  ```python
  query["_conversation_loader"] = lambda cid: state.conversation_cache[cid]
  ```
- This gives `_get_pkb_context()` access to the cache without importing `state`.

**Plan decision:**
- Use **Option C** (dependency injection) as the primary approach because it leverages the existing LRU cache and avoids redundant disk I/O.
- The endpoint handler at line 1317+ already augments `query` with non-JSON-serializable data (`conversation_pinned_claim_ids` is a Python list extracted from session state). Adding `_conversation_loader` follows the same pattern.
- Fallback to **Option B** (direct `Conversation.load_local()`) if the loader is not available (e.g. in tests or standalone usage).

**Concrete wiring:**
```python
# In endpoints/conversations.py, /send_message handler (after line 1320):
query["_conversation_loader"] = lambda cid: state.conversation_cache[cid]
query["_users_dir"] = state.users_dir

# In Conversation._get_pkb_context() (new parameter):
def _get_pkb_context(self, ..., conversation_loader=None, users_dir=None, ...):
    # ...resolve cross-conversation refs...
    if conversation_loader:
        other_conv = conversation_loader(other_conversation_id)
    else:
        # Fallback: load from disk
        conv_root = os.path.dirname(self._storage)
        other_conv = Conversation.load_local(os.path.join(conv_root, other_conversation_id))
```

### Resolving the Message (index/hash)

Once we have the referenced `Conversation` object:
- Load messages: `messages = other_conversation.get_message_list()`.

If reference uses index:
- Validate `1 <= index <= len(messages)`.
- Select: `msg = messages[index - 1]`.

If reference uses hash:
- Prefer stored `message_short_hash` if present (recommended design).
- Otherwise compute on the fly from `(conversation_friendly_id + msg['text'])`.
- Select first match.

Message metadata to include:
- sender (`user` or `model`)
- message index (1-based)
- message_id (existing numeric string)
- message_short_hash (new)

### Formatting and Injection

We will inject referenced conversation messages into the same returned string as PKB claims, using a distinct prefix.

Format per referenced message:

```
- [REFERENCED @conversation_<conv_friendly_id>_message_<index_or_hash>] [conversation_message] (from <conv_friendly_id>, #<index>, <sender>): <first line / preview>
```

Because conversation messages can be long, we should:
- include full message text in a fenced block, not a single bullet
- enforce a max character cap per referenced message (e.g. 8k chars) and note truncation

Recommended injected structure:

```
- [REFERENCED @conversation_<...>] [conversation_message] from <conv_friendly_id> #<index> (<sender>):
  ```
  <full message text, possibly truncated>
  ```
```

This keeps the "referenced" tag detectable by `_extract_referenced_claims()` (it looks for `[REFERENCED`), ensuring explicitly referenced content can be re-injected verbatim after distillation.

### Error Handling

Resolution failures should be fail-open:
- If a conversation friendly ID cannot be found: log and skip
- If message index/hash not found: log and skip

But we should surface a lightweight notice to the user (future enhancement). For now we follow PKB behavior which silently continues and logs.

### Security / Multi-user Boundaries

Lookups must be scoped to the logged-in user:
- Only allow resolving conversations where `UserToConversationId.user_email == current_user_email`.
- Never allow direct conversation_id references to bypass ownership checks.

### Backwards Compatibility

- Existing PKB `@...` references continue unchanged.
- The new handler only triggers when the friendly_id begins with `conversation_` (or `conv_` alias if added).
- All other strings still go through `StructuredAPI.resolve_reference()`.

## UI Changes

We need to make conversation/message identifiers discoverable and easy to copy. The sidebar now uses **jsTree** with **vakata context menus** (from the Hierarchical Workspace feature), which changes the approach.

### 1) Sidebar: conversation friendly ID via context menu ONLY

**Design decision:** The conversation friendly name is accessible ONLY via the right-click / triple-dot context menu as a "Copy Conversation Reference" item. It is NOT displayed inline beside the conversation title in the jsTree view, NOT shown in the tooltip, and NOT appended to the node text. This keeps the tree clean and uncluttered.

The sidebar no longer uses custom HTML divs. Conversation nodes are jsTree data objects built in `buildJsTreeData()` (lines 291-312). We modify the node data minimally — only adding `data-conversation-friendly-id` to `li_attr` for the context menu to read:

```javascript
// In buildJsTreeData(), conversation node (lines 291-312):
{
    id: 'cv_' + conv.conversation_id,
    parent: 'ws_' + wsId,
    text: title,                  // unchanged — no friendly ID in display text
    type: 'conversation',
    li_attr: {
        'data-conversation-id': conv.conversation_id,
        'data-flag': conv.flag || 'none',
        'data-conversation-friendly-id': conv.conversation_friendly_id || '',  // NEW
        'class': flagClass
    },
    a_attr: {
        title: conv.title || '',   // unchanged — no friendly ID in tooltip
        'data-conversation-id': conv.conversation_id
    }
}
```

**Context menu item** — Add "Copy Conversation Reference" to `buildConversationContextMenu(node)` (lines 646-713). Place it as the first item, before "Open in New Window":

```javascript
// In buildConversationContextMenu(node), add before openNewWindow:
copyConvRef: {
    label: 'Copy Conversation Reference',
    icon: 'fa fa-at',
    action: function () {
        var fid = node.li_attr['data-conversation-friendly-id'];
        if (fid) {
            navigator.clipboard.writeText(fid).then(function() {
                // Optional: brief toast or console.log
            });
        }
    },
    _disabled: !node.li_attr['data-conversation-friendly-id']
},
```

Note: The context menu copies just the `conversation_friendly_id` (e.g. `react_optimization_b4f2`), NOT the full `@conversation_react_optimization_b4f2_message_N` syntax. The user composes the full message reference by appending `@conversation_<fid>_message_<index_or_hash>` manually or by also copying a message hash from the message card badge. Copying just the friendly name is most useful because users may want to reference different messages from the same conversation.

**Data flow for `conversation_friendly_id` in the frontend:**
1. Server: `Conversation.get_metadata()` includes `conversation_friendly_id` in return dict.
2. Endpoint: `list_conversation_by_user()` returns metadata array — each item now has `conversation_friendly_id`.
3. Frontend: `loadConversationsWithWorkspaces()` receives it via AJAX. Conversations array items have `conv.conversation_friendly_id`.
4. Frontend: `buildJsTreeData()` stores it in `li_attr['data-conversation-friendly-id']`.
5. Frontend: `buildConversationContextMenu(node)` reads from `node.li_attr['data-conversation-friendly-id']`.

Implementation details:
- `Conversation.get_metadata()` (lines 7588-7607) must include `conversation_friendly_id` in its return dict.
- `loadConversationsWithWorkspaces()` already fetches metadata from `/list_conversation_by_user/<domain>` — the field will flow through automatically once the backend includes it.
- In `buildJsTreeData()` (line 296+), add `'data-conversation-friendly-id': conv.conversation_friendly_id || ''` to `li_attr`.
- In `buildConversationContextMenu()` (line 646+), add the "Copy Conversation Reference" item as the first menu item.

### 2) Message cards: show message short hash + index badge

Message card headers are built in `interface/common-chat.js:renderMessages()` (lines 2259-2278).

Current header structure:
```html
<div class="card-header d-flex justify-content-between align-items-center"
     message-index="${messageIndex}" message-id="${messageId}">
    <div class="d-flex align-items-center">
        <input type="checkbox" class="history-message-checkbox"
               message-index="${messageIndex}" message-id="${messageId}" ...>
        <small><small><strong>${senderText}</strong></small></small>
        ${actionDropdown}   <!-- Show Doubts, Ask New Doubt, Move Up/Down, Artefacts, Delete -->
    </div>
    <div class="d-flex align-items-center">
        <button class="copy-btn-header" title="Copy Text">...</button>
        <div class="dropdown vote-menu-toggle">...</div>
    </div>
</div>
```

**Change:** Add a clickable reference badge after the `<strong>${senderText}</strong>` element, within the same `<small><small>` wrapper:
```html
<small><small>
    <strong>${senderText}</strong>
    <span class="message-ref-badge text-muted"
          style="font-family: monospace; font-size: 0.65rem; cursor: pointer; margin-left: 4px;"
          title="Click to copy message reference"
          data-msg-idx="${displayIndex}"
          data-msg-hash="${message.message_short_hash || ''}"
    >#${displayIndex}${message.message_short_hash ? ' · ' + message.message_short_hash : ''}</span>
</small></small>
```

Where:
- `displayIndex` = 1-based index. In `renderMessages()`, the loop variable `originalIndex` is the 0-based position in the messages array; we use `originalIndex + 1`.
- `message.message_short_hash` = the 6-char hash from the message dict (may be absent for old messages without backfill).

**Click handler** (delegated via `$(document).on('click', '.message-ref-badge', ...)`):
- Reads `data-msg-hash` and `data-msg-idx` from the badge element.
- Reads `ConversationManager.activeConversationFriendlyId` for the conversation part.
- Builds the full reference: `@conversation_<conv_friendly_id>_message_<hash>` (prefer hash for stability, fall back to index if hash is empty).
- Copies to clipboard via `navigator.clipboard.writeText(...)`.
- Brief visual feedback: temporarily replace badge text with "Copied!", restore after 1200ms.

```javascript
$(document).on('click', '.message-ref-badge', function(e) {
    e.stopPropagation();
    var hash = $(this).data('msg-hash');
    var idx = $(this).data('msg-idx');
    var convFid = ConversationManager.activeConversationFriendlyId || '';
    if (!convFid) return;
    var msgPart = hash ? hash : idx;
    var ref = '@conversation_' + convFid + '_message_' + msgPart;
    navigator.clipboard.writeText(ref).then(function() {
        var original = $(e.target).text();
        $(e.target).text('Copied!');
        setTimeout(function() { $(e.target).text(original); }, 1200);
    });
});
```

**Where the UI gets `conv_friendly_id`:**
- The active conversation's metadata is loaded in `ConversationManager.setActiveConversation()` (line 376+) which calls `ConversationManager.getConversationDetails()` (line 333+).
- Add a new property: `ConversationManager.activeConversationFriendlyId = ''` (initialized at line 8, alongside `activeConversationId`).
- Populate it when activating a conversation: after metadata is received, set `ConversationManager.activeConversationFriendlyId = metadata.conversation_friendly_id || ''`.
- Note: `ConversationManager.activateConversation()` (in common-chat.js) fetches messages and settings — this is where metadata becomes available. The `conversation_friendly_id` can also be passed from the sidebar's conversation data since `loadConversationsWithWorkspaces()` already has it.

**Streaming case:**
- When the placeholder assistant card is created during streaming, the hash is not yet known (the text hasn't been persisted).
- Once `part['message_ids']` arrives in `renderStreamingResponse()` (lines 1210-1235), the server should also send `message_short_hash` values in the same chunk.
- Update the `.message-ref-badge` in the card header at that point:
```javascript
// Inside the message_ids handling block (lines 1210-1235):
if (part['message_ids']['response_message_short_hash']) {
    var hash = part['message_ids']['response_message_short_hash'];
    card.find('.message-ref-badge').attr('data-msg-hash', hash);
    var idx = card.find('.message-ref-badge').data('msg-idx');
    card.find('.message-ref-badge').text('#' + idx + ' · ' + hash);
}
```

**User message hash during streaming:**
- The user message card is rendered before the streaming response starts (`ChatManager.renderMessages(conversationId, [userMessage], false, ...)`).
- At that point, the user message hash is not yet computed (message not persisted).
- When `part['message_ids']` arrives, it also includes `user_message_short_hash` — find the user card (previous sibling of the assistant card) and update its badge.
```javascript
if (part['message_ids']['user_message_short_hash']) {
    var userHash = part['message_ids']['user_message_short_hash'];
    // Find the user message card (the card before the current assistant card)
    var userCard = card.prev('.message-card');
    if (userCard.length) {
        userCard.find('.message-ref-badge').attr('data-msg-hash', userHash);
        var userIdx = userCard.find('.message-ref-badge').data('msg-idx');
        userCard.find('.message-ref-badge').text('#' + userIdx + ' · ' + userHash);
    }
}
```

### 3) Message list API payload changes

`GET /list_messages_by_conversation/<conversation_id>` returns the raw message array from `Conversation.get_message_list()`.

We extend each message dict to include:
- `message_short_hash` (string, 6-char) — persisted at creation time.

For existing stored messages without `message_short_hash`:
- The endpoint (or `get_message_list()`) should compute it on the fly if the conversation has a `conversation_friendly_id` available.
- This avoids a hard migration while still providing hashes for old messages.

The `message_ids` streaming chunk should be extended:
```python
{
    "message_ids": {
        "user_message_id": "...",
        "response_message_id": "...",
        "user_message_short_hash": "...",       # NEW
        "response_message_short_hash": "..."    # NEW
    }
}
```

### 4) Minimal UI disruption principle

- Do not change existing jsTree node types, icons, selection behavior, or node text format.
- Do not add any visible elements to the sidebar tree (no inline friendly ID, no tooltip changes, no icon changes).
- Conversation friendly ID is accessible ONLY via the context menu — zero visual impact on the tree.
- Do not change existing message card action menus or checkbox semantics.
- Context menu additions go at natural positions ("Copy Conversation Reference" is first, before existing items).
- Message ref badges use small monospace text with muted color — minimal visual impact on card headers.
- On mobile, context menu copy works the same (vakata menus work on touch).
- On very small screens, message ref badges can be hidden via CSS media query if needed (future enhancement).

## Autocomplete Strategy

Autocomplete for cross-conversation message references is harder than PKB autocomplete because:
- PKB objects live in one DB and can be prefix-searched cheaply.
- Conversation messages are spread across many folders/files and are not indexed.

We will treat autocomplete in two phases:

### Phase 1 (MVP): No message-level autocomplete

MVP behavior:
- Keep existing PKB autocomplete unchanged.
- Users build references by copying from UI (sidebar friendly ID + message header hash/index).

Rationale:
- Lowest complexity.
- Provides an immediate workflow: discover/copy identifiers.

### Phase 2: Conversation-level autocomplete (recommended next)

Add a lightweight autocomplete for conversation IDs only:
- When a user types `@conversation_` (or `@conv_`), autocomplete suggests conversation friendly IDs.
- Selecting one inserts `@conversation_<fid>_message_` and leaves cursor ready for index/hash.

Implementation approach:
- Create a new endpoint `GET /conversations/autocomplete?q=<prefix>&domain=<domain>&limit=<n>` that:
  - searches `UserToConversationId.conversation_friendly_id LIKE '<prefix>%'` for the current user
  - returns small payload: `[{ friendly_id, title }]`.
- Extend the existing autocomplete dropdown in `interface/common-chat.js`:
  - In `fetchAutocompleteResults()` (line 3428+), detect that `prefix.startsWith('conversation_')` or `prefix.startsWith('conv_')`
  - Call the new endpoint instead of (or alongside) `/pkb/autocomplete`
  - Render results under a new category (e.g. "Conversations") with icon `bi-chat-dots` (or `fa-comment-o` to match jsTree conversation icon)
  - On selection, insert `@conversation_<fid>_message_` (with trailing underscore so the user can type index/hash)

This keeps PKB `/pkb/autocomplete` focused on PKB entities.

### Phase 3: Message-level search (optional, heavier)

If we want full `@conversation_<fid>_message_<...>` autocomplete:
- we'd need an index of message hashes and/or message previews.

Two possible approaches:

Approach A: On-demand message listing after selecting a conversation
- After inserting `@conversation_<fid>_message_`, a secondary dropdown shows the last N messages from that conversation:
  - `#1 You: ...`
  - `#2 Assistant: ...`
  - etc.

This requires a new endpoint:
- `GET /conversations/<fid>/messages?limit=20`

Approach B: Build a global message index
- Maintain a SQLite table mapping `(user, domain, conversation_friendly_id, message_index, message_short_hash, sender, preview)`.
- Update it on persistence/edit/move.

This is more invasive and is not required for initial functionality.

Plan decision:
- Implement Phase 1 now.
- Design Phase 2 endpoint/UI hook in this plan so we can add it quickly.

## Complete Data Flow (End-to-End)

This section traces the full data flow for a cross-conversation message reference, from user action to LLM prompt injection. Understanding this flow is critical for correct implementation.

### Flow 1: Generating and storing identifiers

```
1. User sends first message in a new conversation
   → endpoints/conversations.py: /send_message/<conversation_id> (line 1281)
   → query["_users_dir"] = state.users_dir (injected at line 1320+)

2. Conversation.reply() processes the message
   → calls persist_current_turn(users_dir=users_dir) (lines 2988-3211)

3. persist_current_turn() generates title via LLM
   → title parsed at line 3175, stored at line 3187
   → THEN calls _ensure_conversation_friendly_id(memory, users_dir)

4. _ensure_conversation_friendly_id():
   a. generate_conversation_friendly_id(title, created_at)
      → _extract_meaningful_words(title, max_words=2) → ["react", "optimization"]
      → mmh3.hash("React Optimization" + "2026-02-08T10:00:00", signed=False) → base36[:4] → "b4f2"
      → result: "react_optimization_b4f2"
   b. conversationFriendlyIdExists(users_dir, user_email, "react_optimization_b4f2")
      → SELECT 1 FROM UserToConversationId WHERE user_email=? AND conversation_friendly_id=?
   c. If no collision: store in memory["conversation_friendly_id"] and DB

5. persist_current_turn() also stores messages with message_short_hash:
   → generate_message_short_hash("react_optimization_b4f2", message_text)
   → mmh3.hash("react_optimization_b4f2" + text, signed=False) → base36[:6] → "a3f2b1"
   → stored in each message dict as "message_short_hash": "a3f2b1"

6. Streaming yields message_ids including hashes:
   → {"message_ids": {"user_message_id": "...", "response_message_id": "...",
       "user_message_short_hash": "...", "response_message_short_hash": "..."}}
```

### Flow 2: User copies a reference from the UI

```
1. User right-clicks a conversation in the sidebar
   → workspace-manager.js: buildConversationContextMenu(node)
   → "Copy Conversation Reference" item reads node.li_attr['data-conversation-friendly-id']
   → navigator.clipboard.writeText("react_optimization_b4f2")

2. User clicks a message badge (#5 · a3f2b1) in the chat area
   → common-chat.js: delegated click handler on .message-ref-badge
   → reads data-msg-hash="a3f2b1", data-msg-idx="5"
   → reads ConversationManager.activeConversationFriendlyId = "react_optimization_b4f2"
   → navigator.clipboard.writeText("@conversation_react_optimization_b4f2_message_a3f2b1")

3. User pastes the reference into their next message:
   "Use the approach from @conversation_react_optimization_b4f2_message_a3f2b1"
```

### Flow 3: Resolving a cross-conversation reference

```
1. User sends message containing @conversation_react_optimization_b4f2_message_a3f2b1
   → parseMessageForCheckBoxes.js: parseMemoryReferences(text)
   → friendlyRegex matches: "conversation_react_optimization_b4f2_message_a3f2b1"
   → friendlyIds = ["conversation_react_optimization_b4f2_message_a3f2b1"]

2. POST /send_message/<current_conversation_id>
   → body.referenced_friendly_ids = ["conversation_react_optimization_b4f2_message_a3f2b1"]

3. Conversation.reply() → _get_pkb_context():
   a. CONV_REF_PATTERN.match("conversation_react_optimization_b4f2_message_a3f2b1")
      → conv_fid = "react_optimization_b4f2", msg_identifier = "a3f2b1"
      → classified as conv_ref (not pkb_fid)
   
   b. getConversationIdByFriendlyId(user_email, "react_optimization_b4f2")
      → SELECT conversation_id FROM UserToConversationId WHERE ...
      → returns "user@example.com_a8f3b2c1d4e5..."
   
   c. Load conversation via conversation_loader(conversation_id) or Conversation.load_local()
   
   d. other_conv.get_message_list() → iterate, find msg where message_short_hash == "a3f2b1"
      → found: message #5, sender: "model", text: "Here are several strategies..."
   
   e. Format as:
      "- [REFERENCED @conversation_react_optimization_b4f2_message_a3f2b1] [conversation_message]:
        ```
        Here are several strategies for React optimization...
        ```"

4. context_lines now includes the referenced message alongside PKB claims.
   → After distillation, _extract_referenced_claims() preserves [REFERENCED @conversation_...] blocks.
   → Main LLM receives the referenced message verbatim in the final prompt.
```

### Flow 4: Frontend data flow for conversation_friendly_id

```
1. Server: GET /list_conversation_by_user/<domain>
   → endpoints/conversations.py: list_conversation_by_user() (line 1133)
   → For each conversation: c.get_metadata() returns {..., conversation_friendly_id: "react_optimization_b4f2"}
   → Backfill runs for old conversations without friendly IDs

2. Frontend: loadConversationsWithWorkspaces()
   → AJAX GET /list_conversation_by_user/<domain>
   → conversations array: [{..., conversation_friendly_id: "react_optimization_b4f2", ...}, ...]

3. Frontend: buildJsTreeData(convByWs)
   → For each conversation:
     li_attr['data-conversation-friendly-id'] = conv.conversation_friendly_id || ''

4. Frontend: On conversation selection
   → ConversationManager.setActiveConversation(conversationId)
   → Looks up conversation_friendly_id from WorkspaceManager.conversations
   → Sets ConversationManager.activeConversationFriendlyId = "react_optimization_b4f2"

5. Frontend: Context menu or badge click reads the stored friendly_id
```

## Implementation Plan

Milestones are ordered to keep the system working end-to-end at every step. Each task lists the exact file and function to modify.

### Milestone 0: DB schema + utility functions

**Task 0.1: DB migration — add `conversation_friendly_id` column**
- File: `database/connection.py`, inside `create_tables()`, after the `parent_workspace_id` migration (after line 180) and before the `DoubtsClearing` migration (line 182)
- Add idempotent `ALTER TABLE UserToConversationId ADD COLUMN conversation_friendly_id text` in try/except:
  ```python
  # Add conversation_friendly_id column if it doesn't exist (cross-conversation references)
  try:
      cur.execute("ALTER TABLE UserToConversationId ADD COLUMN conversation_friendly_id text")
      log.info("Added conversation_friendly_id column to UserToConversationId table")
  except Exception:
      pass  # Column already exists
  
  cur.execute(
      "CREATE INDEX IF NOT EXISTS idx_UserToConversationId_friendly_id "
      "ON UserToConversationId (user_email, conversation_friendly_id)"
  )
  ```
- Pattern: identical to the `parent_workspace_id` migration at lines 170-180

**Task 0.2: DB helper functions**
- File: `database/conversations.py` (add after existing functions, ~line 279)
- All functions use keyword-only arguments and open/close their own SQLite connections (same pattern as existing functions in this file).
- Add: `setConversationFriendlyId(*, users_dir, user_email, conversation_id, conversation_friendly_id)` — UPDATE query
- Add: `getConversationIdByFriendlyId(*, users_dir, user_email, conversation_friendly_id)` — SELECT query, returns `Optional[str]`
- Add: `conversationFriendlyIdExists(*, users_dir, user_email, conversation_friendly_id)` — SELECT 1 existence check, returns `bool`
- See section 4 for concrete code
- Note: `_db_path()` is at line 46 and returns `f"{users_dir}/users.db"`. All new functions call `create_connection(_db_path(users_dir=users_dir))`.

**Task 0.3: ID generation utility module**
- File: **new file** `conversation_reference_utils.py` (in repo root, alongside `Conversation.py`)
- Add: `_to_base36(num, length)` — convert unsigned int to fixed-length base36
- Add: `generate_conversation_friendly_id(title, created_at)` — `{w1}_{w2}_{h4}` using `_extract_meaningful_words()` + mmh3
- Add: `generate_message_short_hash(conversation_friendly_id, message_text)` — 6-char base36 via mmh3
- Dependencies: `mmh3` (already installed, used throughout the codebase), `truth_management_system.utils._extract_meaningful_words`
- See section 4 for concrete code with full docstrings

**Verify:** Run existing tests to ensure nothing breaks: `python -m pytest truth_management_system/tests/ -v`

### Milestone 1: Generate and persist conversation_friendly_id

**Task 1.1: Generate friendly ID on first persist**
- File: `Conversation.py`, method `persist_current_turn()` (lines 2988-3211)
- **Where to add:** After the title is assigned at line 3187 (`memory["title"] = title`), add a call to a new method `_ensure_conversation_friendly_id(memory, users_dir)`.
- The title assignment block runs at lines 3175-3187 inside the condition `if not memory["title_force_set"]`. Place the friendly ID generation right after `memory["title"] = title`.
- `_ensure_conversation_friendly_id(memory, users_dir)` should:
  1. Check `memory.get("conversation_friendly_id")` — if already set, return early
  2. Get or create `memory["created_at"]` from `memory["last_updated"]` (use the first value as a stable timestamp and store it in memory so it doesn't change)
  3. Call `generate_conversation_friendly_id(title, created_at)` from `conversation_reference_utils`
  4. Check collision via `conversationFriendlyIdExists(users_dir=users_dir, user_email=self.user_id, conversation_friendly_id=candidate)`
  5. If collision, retry with salt (append `self.conversation_id` to hash input), up to 5 attempts
  6. On persistent collision (5 failures), extend hash to 6 chars and try once more
  7. Store in `memory["conversation_friendly_id"] = fid`
  8. Write to DB via `setConversationFriendlyId(users_dir=users_dir, user_email=self.user_id, conversation_id=self.conversation_id, conversation_friendly_id=fid)`

- **Challenge: `persist_current_turn()` does not have `users_dir`.**
  - `users_dir` flows from the endpoint layer: `state.users_dir` is available in `endpoints/conversations.py`.
  - The endpoint handler already injects data into `query` (line 1317-1320: `query["conversation_pinned_claim_ids"]`).
  - **Solution:** Inject `query["_users_dir"] = state.users_dir` in the `/send_message` handler (after line 1320).
  - In `Conversation.reply()` (line 4764+), extract: `users_dir = query.get("_users_dir", None)`.
  - Pass `users_dir` through to `persist_current_turn()` as a new optional parameter.
  - In `persist_current_turn()`, add `users_dir=None` parameter. The method already has access to `self` so it can get `self.user_id` and `self.conversation_id`.

```python
# In persist_current_turn(), after line 3187 (memory["title"] = title):
if users_dir and not memory.get("conversation_friendly_id"):
    self._ensure_conversation_friendly_id(memory, users_dir)
```

```python
def _ensure_conversation_friendly_id(self, memory: dict, users_dir: str) -> None:
    """
    Generate and persist a conversation_friendly_id if not already set.
    
    Called on first persist after title is generated. The friendly ID is
    stored in both the conversation memory dict and the UserToConversationId
    DB table for fast lookup during cross-conversation reference resolution.
    
    Parameters
    ----------
    memory : dict
        The conversation memory dict (modified in-place).
    users_dir : str
        Path to users directory for DB access.
    """
    from conversation_reference_utils import generate_conversation_friendly_id
    from database.conversations import setConversationFriendlyId, conversationFriendlyIdExists
    
    title = memory.get("title", "")
    if not title:
        return
    
    # Use a stable timestamp — first persist time, never changes
    if "created_at" not in memory:
        memory["created_at"] = memory.get("last_updated", "")
    created_at = memory["created_at"]
    
    candidate = generate_conversation_friendly_id(title, created_at)
    
    # Collision retry loop
    for attempt in range(5):
        if not conversationFriendlyIdExists(
            users_dir=users_dir, user_email=self.user_id,
            conversation_friendly_id=candidate
        ):
            break
        # Re-hash with salt
        salt_input = title + created_at + self.conversation_id + str(attempt)
        candidate = generate_conversation_friendly_id(salt_input, created_at)
    else:
        # All 5 attempts collided — extend hash length
        import mmh3
        from conversation_reference_utils import _to_base36
        from truth_management_system.utils import _extract_meaningful_words
        words = _extract_meaningful_words(title, max_words=2) or ['chat']
        h = mmh3.hash(title + created_at + self.conversation_id, signed=False)
        candidate = '_'.join(words) + '_' + _to_base36(h, 6)
    
    memory["conversation_friendly_id"] = candidate
    setConversationFriendlyId(
        users_dir=users_dir, user_email=self.user_id,
        conversation_id=self.conversation_id,
        conversation_friendly_id=candidate
    )
```

**Task 1.2: Expose in metadata**
- File: `Conversation.py`, method `get_metadata()` (lines 7588-7607)
- Add `"conversation_friendly_id": memory.get("conversation_friendly_id", "")` to the returned dict.
- Current dict keys: `conversation_id`, `user_id`, `title`, `summary_till_now`, `domain`, `flag`, `last_updated`, `conversation_settings`.
- Add the new key after `conversation_settings` for logical grouping.

```python
# In get_metadata(), add to return dict:
"conversation_friendly_id": memory.get("conversation_friendly_id", ""),
```

**Task 1.3: Backfill existing conversations on list**
- File: `endpoints/conversations.py`, inside `list_conversation_by_user()` (lines 1133-1235)
- The metadata is built at lines 1191-1202 where `c.get_metadata()` is called per conversation and augmented with `workspace_id`, `workspace_name`, `domain`.
- After building metadata for each conversation, check if `conversation_friendly_id` is empty/None:
  - If so, generate a friendly_id from `metadata["title"]` + `metadata["last_updated"]`
  - Store in the conversation's memory dict and in the DB
  - Update the metadata dict

```python
# After line 1202, within the metadata loop:
for metadata_item, conv_obj in data:
    if not metadata_item.get("conversation_friendly_id"):
        try:
            from conversation_reference_utils import generate_conversation_friendly_id
            from database.conversations import setConversationFriendlyId, conversationFriendlyIdExists
            
            title = metadata_item.get("title", "")
            last_updated = metadata_item.get("last_updated", "")
            if title and last_updated:
                candidate = generate_conversation_friendly_id(title, last_updated)
                # Simple collision check (no retry in backfill — keep it fast)
                if conversationFriendlyIdExists(
                    users_dir=state.users_dir, user_email=email,
                    conversation_friendly_id=candidate
                ):
                    # Append conversation_id fragment to break collision
                    candidate = generate_conversation_friendly_id(
                        title + conv_obj.conversation_id[:8], last_updated
                    )
                
                # Store in memory
                memory = conv_obj.get_field("memory")
                memory["conversation_friendly_id"] = candidate
                if "created_at" not in memory:
                    memory["created_at"] = last_updated
                
                # Store in DB
                setConversationFriendlyId(
                    users_dir=state.users_dir, user_email=email,
                    conversation_id=conv_obj.conversation_id,
                    conversation_friendly_id=candidate
                )
                
                # Update metadata for this response
                metadata_item["conversation_friendly_id"] = candidate
        except Exception:
            logger.exception("Failed to backfill conversation_friendly_id for %s",
                           metadata_item.get("conversation_id", "unknown"))
```

- This is a lazy backfill: runs once per conversation that lacks a friendly_id when the list endpoint is called.
- Rate: bounded by the number of conversations per user (typically < 200). Each backfill is a single UPDATE + existence check.
- **Performance note:** For a user with 200 conversations and no friendly IDs yet, the first list call will execute ~400 DB queries (200 existence checks + 200 updates). This is acceptable for SQLite on localhost but could add 1-2 seconds. Subsequent calls skip conversations that already have friendly IDs.

**Verify:** Start server, list conversations, check that new conversations get friendly IDs and old ones get backfilled. Verify via `sqlite3 storage/users/users.db "SELECT conversation_friendly_id FROM UserToConversationId WHERE user_email='...'"` that the column is populated.

### Milestone 2: Message short hash

**Task 2.1: Compute and store hash at persist time**
- File: `Conversation.py`, method `persist_current_turn()` (lines 3106-3134, where messages are built and stored)
- Messages are persisted as two dicts: user message (lines ~3108) and model/response message (lines ~3117).
- After the conversation_friendly_id is ensured (Task 1.1) and message dicts are built:
  - Get `conv_fid = memory.get("conversation_friendly_id", self.conversation_id)`
  - Import `from conversation_reference_utils import generate_message_short_hash`
  - Compute `user_hash = generate_message_short_hash(conv_fid, query_text)`
  - Compute `response_hash = generate_message_short_hash(conv_fid, response_text)`
- Add `"message_short_hash": user_hash` to the user preserved_message dict
- Add `"message_short_hash": response_hash` to the model preserved_message dict
- These are persisted alongside the existing `message_id`, `text`, `sender`, etc. fields

```python
# After building preserved_messages and before set_messages_field:
from conversation_reference_utils import generate_message_short_hash
conv_fid = memory.get("conversation_friendly_id", self.conversation_id)

user_msg_dict["message_short_hash"] = generate_message_short_hash(conv_fid, query_text)
response_msg_dict["message_short_hash"] = generate_message_short_hash(conv_fid, response_text)
```

**Task 2.2: Include hash in streaming message_ids chunk**
- File: `Conversation.py`, method `reply()` (wherever `message_ids` dict is yielded to the stream — search for `"message_ids"` in the yield statements)
- The `message_ids` chunk currently includes `user_message_id` and `response_message_id`.
- Extend the yielded dict to include short hashes:
  ```python
  {"message_ids": {
      "user_message_id": user_message_id,
      "response_message_id": response_message_id,
      "user_message_short_hash": user_hash,       # NEW
      "response_message_short_hash": response_hash  # NEW
  }}
  ```
- The hash computation should happen right after `get_message_ids()` is called (since we have the text at that point).
- Note: `persist_current_turn()` is called during the streaming yield cycle. The hashes computed in Task 2.1 should be captured and yielded.

**Task 2.3: Backfill missing hashes on list_messages**
- File: `Conversation.py`, method `get_message_list()` (lines 7584-7586)
- Currently this is a one-liner: `return self.get_field("messages")`
- Expand it to compute missing hashes on-the-fly:
  ```python
  def get_message_list(self):
      """Return the message list, backfilling message_short_hash for old messages."""
      msg_list = self.get_field("messages")
      if not msg_list:
          return msg_list
      conv_fid = self.get_field("memory").get("conversation_friendly_id", "")
      if conv_fid:
          from conversation_reference_utils import generate_message_short_hash
          for msg in msg_list:
              if "message_short_hash" not in msg and msg.get("text"):
                  msg["message_short_hash"] = generate_message_short_hash(
                      conv_fid, msg.get("text", "")
                  )
      return msg_list
  ```
- This is **non-persisting** (does not write back to the messages JSON), so it's safe and has no migration cost.
- On each `GET /list_messages_by_conversation/<id>` call, old messages without hashes will have them computed on-the-fly.
- The computed hashes are consistent (mmh3 is deterministic) so the same message always gets the same hash.

**Verify:** Send a message, check stored JSON has `message_short_hash`. Call `GET /list_messages_by_conversation/<id>` endpoint and verify each message has the `message_short_hash` field. For old messages (pre-feature), verify the hash is computed on-the-fly.

### Milestone 3: UI discoverability

**Task 3.1: Sidebar — context menu "Copy Conversation Reference" (NO tooltip, NO inline text)**
- File: `interface/workspace-manager.js`
- In `buildJsTreeData()` (lines 291-312), conversation node:
  - Add `'data-conversation-friendly-id': conv.conversation_friendly_id || ''` to `li_attr` (line ~300)
  - Do NOT modify `a_attr.title` — keep it as `conv.title || ''` (the tooltip shows the full title, not the friendly ID)
  - Do NOT modify `text` — keep it as the conversation title only
  ```javascript
  // Modify li_attr to include:
  li_attr: {
      'data-conversation-id': conv.conversation_id,
      'data-flag': conv.flag || 'none',
      'data-conversation-friendly-id': conv.conversation_friendly_id || '',  // NEW
      'class': flagClass
  },
  ```

- In `buildConversationContextMenu()` (lines 646-713):
  - Add a new "Copy Conversation Reference" item as the **first** item (before `openNewWindow`):
  ```javascript
  // Add as first item in the menu items object:
  copyConvRef: {
      label: 'Copy Conversation Reference',
      icon: 'fa fa-at',
      action: function () {
          var fid = node.li_attr['data-conversation-friendly-id'];
          if (fid) {
              navigator.clipboard.writeText(fid).then(function() {
                  // Optional: showToast or console.log
              });
          }
      },
      _disabled: !node.li_attr['data-conversation-friendly-id'],
      separator_after: true  // visual separator after this item
  },
  // Then existing: openNewWindow, clone, toggleStateless, flag, moveTo, deleteConv
  ```
  - The item copies just the friendly ID string (e.g. `react_optimization_b4f2`), not the full `@conversation_..._message_...` syntax. Users compose the full reference manually.
  - Disabled (grayed out) when `conversation_friendly_id` is empty (e.g. for conversations that haven't been backfilled yet).

**Task 3.2: Message card headers — ref badge**
- File: `interface/common-chat.js`, in `renderMessages()` (lines 2259-2278)
- After the `<strong>${senderText}</strong>` element, within the same `<small><small>` wrapper, add:
  ```html
  <span class="message-ref-badge text-muted"
        style="font-family:monospace;font-size:0.65rem;cursor:pointer;margin-left:4px;"
        data-msg-idx="${displayIndex}" data-msg-hash="${message.message_short_hash || ''}"
        title="Click to copy message reference"
  >#${displayIndex}${message.message_short_hash ? ' · ' + message.message_short_hash : ''}</span>
  ```
- `displayIndex` = `originalIndex + 1` (1-based), where `originalIndex` is the iteration index in the messages array.
- Example rendered output: `#5 · a3f2b1` or just `#5` if hash is unavailable.
- The badge is small, monospace, muted color — minimal visual impact.

**Task 3.3: Click-to-copy handler for ref badges**
- File: `interface/common-chat.js` (add near the bottom where other delegated event handlers are defined)
- Add delegated click handler:
  ```javascript
  $(document).on('click', '.message-ref-badge', function(e) {
      e.stopPropagation();
      var hash = $(this).data('msg-hash');
      var idx = $(this).data('msg-idx');
      var convFid = ConversationManager.activeConversationFriendlyId || '';
      if (!convFid) return;
      var msgPart = hash ? hash : idx;
      var ref = '@conversation_' + convFid + '_message_' + msgPart;
      navigator.clipboard.writeText(ref).then(function() {
          var badge = $(e.target).closest('.message-ref-badge');
          var original = badge.text();
          badge.text('Copied!');
          setTimeout(function() { badge.text(original); }, 1200);
      });
  });
  ```
- Uses `closest('.message-ref-badge')` to handle clicks on child elements.
- Prefers hash over index for the reference (more stable across edits/reordering).

**Task 3.4: Store active conversation friendly ID**
- File: `interface/common-chat.js`
- Add property: `ConversationManager.activeConversationFriendlyId = ''` (at line 8, alongside `activeConversationId`)
- Populate it in `ConversationManager.setActiveConversation()` (line 376+):
  - The method currently calls `this.activateConversation(conversationId)` which fetches messages and settings.
  - After the conversation metadata is available (either from the sidebar data or from `getConversationDetails()`), set:
    ```javascript
    ConversationManager.activeConversationFriendlyId = metadata.conversation_friendly_id || '';
    ```
  - **Alternative (simpler):** Since `WorkspaceManager.conversations` already has all conversation metadata from `loadConversationsWithWorkspaces()`, we can look it up directly:
    ```javascript
    // In setActiveConversation() or activateConversation():
    var convData = WorkspaceManager.conversations.find(function(c) {
        return c.conversation_id === conversationId;
    });
    if (convData) {
        ConversationManager.activeConversationFriendlyId = convData.conversation_friendly_id || '';
    }
    ```

**Task 3.5: Streaming update for message hashes**
- File: `interface/common-chat.js`, in `renderStreamingResponse()` where `part['message_ids']` is handled (lines 1210-1235)
- Add after the existing `message_id` updates:
  ```javascript
  // Update response message ref badge with hash
  if (part['message_ids']['response_message_short_hash']) {
      var hash = part['message_ids']['response_message_short_hash'];
      card.find('.message-ref-badge').attr('data-msg-hash', hash);
      var idx = card.find('.message-ref-badge').data('msg-idx');
      card.find('.message-ref-badge').text('#' + idx + ' · ' + hash);
  }
  
  // Update user message ref badge with hash
  if (part['message_ids']['user_message_short_hash']) {
      var userHash = part['message_ids']['user_message_short_hash'];
      var userCard = card.prev('.message-card');
      if (userCard.length) {
          userCard.find('.message-ref-badge').attr('data-msg-hash', userHash);
          var userIdx = userCard.find('.message-ref-badge').data('msg-idx');
          userCard.find('.message-ref-badge').text('#' + userIdx + ' · ' + userHash);
      }
  }
  ```

**Verify:** Manual testing:
1. Right-click a conversation in the sidebar → "Copy Conversation Reference" → verify clipboard contains the friendly ID.
2. Open a conversation → verify message cards show `#1`, `#2`, etc. with hashes after the dot.
3. Click a message badge → verify clipboard contains `@conversation_<fid>_message_<hash>`.
4. Send a new message → verify streaming updates the badges with hashes once `message_ids` arrive.
5. Verify old conversations without friendly IDs show the context menu item as disabled (grayed out).

### Milestone 4: Backend resolution

**Task 4.1: Reference pattern detection**
- File: `Conversation.py`, in `_get_pkb_context()` (lines 385-406, where referenced_friendly_ids are iterated)
- Before the existing friendly_id resolution loop, separate conversation references from PKB references.
- **Regex design challenge:** The `conv_friendly_id` can contain underscores (e.g. `react_optimization_b4f2`), so we cannot simply split on `_`. The `_message_` segment is the reliable separator.
- Pattern: match `conversation_` or `conv_` prefix, then everything up to the last `_message_` or `_msg_`, then the message identifier.

  ```python
  import re
  # Match: conversation_<anything>_message_<index_or_hash>
  # or:    conv_<anything>_msg_<index_or_hash>
  # The <anything> part is the conv_friendly_id (which may contain underscores).
  # We use a non-greedy match up to the LAST occurrence of _message_ or _msg_.
  CONV_REF_PATTERN = re.compile(
      r'^(?:conversation|conv)_(.+)_(?:message|msg)_([a-z0-9]+)$'
  )
  # Note: .+ is greedy by default, so it will match up to the LAST _message_ or _msg_.
  # This handles conv_friendly_ids like "react_optimization_b4f2" correctly:
  #   "conversation_react_optimization_b4f2_message_5"
  #   → group(1) = "react_optimization_b4f2", group(2) = "5"
  
  conv_refs = []
  pkb_fids = []
  for fid in referenced_friendly_ids:
      m = CONV_REF_PATTERN.match(fid)
      if m:
          conv_refs.append((fid, m.group(1), m.group(2)))  # (full_ref, conv_fid, msg_identifier)
      else:
          pkb_fids.append(fid)
  ```

- **Greedy vs non-greedy:** Using greedy `.+` ensures `group(1)` captures everything up to the LAST `_message_` or `_msg_`. This is correct because conversation friendly IDs can contain `_message` as part of their words (unlikely but possible). The `_message_` pattern with trailing `_` makes it unambiguous.
- **Validation:** `group(2)` (the message identifier) must be either all digits (index) or exactly 6 lowercase alphanumeric chars (hash). We validate this in Task 4.2.

**Task 4.2: Resolve conversation references**
- File: `Conversation.py`, new method `_resolve_conversation_message_refs(self, conv_refs, user_email, users_dir, conversation_loader=None)`
- For each `(full_ref, conv_fid, msg_identifier)`:
  1. Look up `conversation_id` via `getConversationIdByFriendlyId(users_dir=users_dir, user_email=user_email, conversation_friendly_id=conv_fid)`
  2. If not found: log warning, skip to next reference
  3. Load conversation using the injected loader or fallback:
     ```python
     if conversation_loader:
         other_conv = conversation_loader(conversation_id)
     else:
         conv_root = os.path.dirname(self._storage)
         other_conv = Conversation.load_local(os.path.join(conv_root, conversation_id))
     ```
  4. Get messages: `messages = other_conv.get_message_list()`
  5. Resolve message:
     - If `msg_id` is all digits: use 1-based index
     - Else: search by `message_short_hash`
  6. Format the resolved content as a `[REFERENCED @...]` block
  7. Return list of `(source_label, formatted_text)` tuples

**Task 4.3: Inject into context_lines**
- File: `Conversation.py`, in `_get_pkb_context()` (after conversation ref resolution, before PKB ref resolution)
- After resolving conversation references via `_resolve_conversation_message_refs()`, add formatted blocks to `context_lines`:
  ```python
  for ref_label, msg_text in resolved_conv_messages:
      # Truncate to 8000 chars to prevent oversized context
      truncated = msg_text[:8000]
      if len(msg_text) > 8000:
          truncated += "\n... [truncated, original message was {} chars]".format(len(msg_text))
      context_lines.append(
          f"- [REFERENCED @{ref_label}] [conversation_message]:\n  ```\n  {truncated}\n  ```"
      )
  ```
- The `[REFERENCED @...]` prefix ensures these blocks are preserved by `_extract_referenced_claims()` (lines 250-308), which matches any bullet starting with `[REFERENCED`. This means cross-conversation message references will survive post-distillation re-injection, same as PKB claim references.
- **Cache within request:** If multiple references point to the same conversation, load it once:
  ```python
  loaded_conversations = {}  # cache: conv_id -> Conversation object
  for full_ref, conv_fid, msg_identifier in conv_refs:
      conv_id = getConversationIdByFriendlyId(...)
      if conv_id not in loaded_conversations:
          loaded_conversations[conv_id] = load_conversation(conv_id)
      other_conv = loaded_conversations[conv_id]
      # ... resolve message from other_conv ...
  ```

**Task 4.4: Pass `users_dir` and `conversation_loader` into the resolution path**
- File: `endpoints/conversations.py`, in the `/send_message` handler (after line 1320)
  ```python
  # Inject cross-conversation resolution dependencies
  query["_users_dir"] = state.users_dir
  query["_conversation_loader"] = lambda cid: state.conversation_cache[cid]
  ```

- File: `Conversation.py`, in `reply()` (lines 4764-4781, where query fields are extracted)
  ```python
  users_dir = query.get("_users_dir", None)
  conversation_loader = query.get("_conversation_loader", None)
  ```

- File: `Conversation.py`, in `reply()` (lines 4804-4815, where `pkb_context_future` is created)
  - Add `users_dir` and `conversation_loader` as new keyword arguments to `_get_pkb_context()`:
  ```python
  pkb_context_future = get_async_future(
      self._get_pkb_context,
      user_email,
      query["messageText"],
      self.running_summary,
      k=10,
      attached_claim_ids=attached_claim_ids,
      conversation_id=self.conversation_id,
      conversation_pinned_claim_ids=conv_pinned_ids,
      referenced_claim_ids=referenced_claim_ids,
      referenced_friendly_ids=referenced_friendly_ids,
      users_dir=users_dir,                    # NEW
      conversation_loader=conversation_loader  # NEW
  )
  ```

- File: `Conversation.py`, in `_get_pkb_context()` (line 310)
  - Add `users_dir=None` and `conversation_loader=None` parameters to the function signature.

- File: `Conversation.py`, in `persist_current_turn()` (lines 2988+)
  - Add `users_dir=None` parameter. Extract from arguments passed by `reply()`.
  - The calling chain: `reply()` → calls `persist_current_turn()` → uses `users_dir` for friendly ID generation (Task 1.1).

**Verify:** Integration test — create two conversations, reference conv A's message from conv B using `@conversation_<fid>_message_<index>`, verify:
1. `_get_pkb_context()` output contains `[REFERENCED @conversation_...]` block with the message text.
2. The referenced message text survives post-distillation re-injection.
3. The LLM receives the referenced message content in the final prompt.

### Milestone 5: Documentation + autocomplete prep

**Task 5.1: Update documentation**
- `documentation/features/conversation_flow/README.md` — add a new section "Cross-Conversation Message References" describing:
  - How `@conversation_<fid>_message_<hash>` references work in the message flow
  - How they are parsed (same `parseMemoryReferences()` regex, detected in `_get_pkb_context()` by prefix)
  - How they are resolved (DB lookup → conversation load → message extraction)
  - How they survive post-distillation re-injection (same `[REFERENCED @...]` mechanism)
- `documentation/product/behavior/chat_app_capabilities.md` — add new capability: "Cross-conversation message references"
- `documentation/README.md` — add entry for cross-conversation references under features
- `documentation/features/workspaces/README.md` — update context menu section to mention "Copy Conversation Reference" item

**Task 5.2: Create feature documentation**
- New file: `documentation/features/cross_conversation_references/README.md`
- Document:
  - Feature overview and user workflow
  - Reference syntax (`@conversation_<fid>_message_<index_or_hash>`)
  - How conversation friendly IDs are generated (algorithm, collision handling)
  - How message short hashes are generated
  - UI: context menu copy, message badge, click-to-copy
  - API changes: new fields in metadata, new DB column, new streaming fields
  - Files modified (complete list)
  - Implementation notes and gotchas

**Task 5.3: Prepare conversation autocomplete endpoint (Phase 2)**
- File: `endpoints/conversations.py`
- Add: `GET /conversations/autocomplete?q=<prefix>&domain=<domain>&limit=<n>`
- DB query: `SELECT conversation_id, conversation_friendly_id FROM UserToConversationId WHERE user_email=? AND conversation_friendly_id LIKE ?||'%' LIMIT ?`
- Load title from conversation metadata for each result
- Return: `[{friendly_id, title, conversation_id}]`
- Wire into `fetchAutocompleteResults()` (lines 3428-3511 in `common-chat.js`) — when prefix starts with `conversation_` or `conv_`:
  - Call the new endpoint instead of (or alongside) `/pkb/autocomplete`
  - Render results under a new category "Conversations" with icon `fa-comment-o`
  - On selection, insert `@conversation_<fid>_message_` (with trailing underscore so the user can type index/hash)
- **Note:** This is Phase 2 and not required for the initial implementation.

### Non-goals for initial implementation

- Global message search across all conversations
- Full message-level autocomplete (Phase 3)
- Sharing references across users
- Referencing messages from the current conversation (possible future extension)
- Inline display of conversation friendly ID in the sidebar tree (explicitly excluded per design decision — context menu only)

## Testing Plan

### Unit Tests (Python — `test_conversation_references.py`)

Test file location: `tests/test_conversation_references.py` (new file)

1. **Friendly ID generation**
   - Given a title "React Performance Optimization" and created_at "2026-02-08T10:00:00", generates `react_performance_XXXX` (4-char hash suffix).
   - Stopwords removed: "How to learn Python" → `learn_python_XXXX` (removes "How", "to").
   - Punctuation stripped: "What's the best approach?" → `best_approach_XXXX`.
   - Short title (1 word): "Debugging" → `debugging_XXXX`.
   - Empty/no meaningful words: "" → `chat_XXXX`.
   - Deterministic: same inputs always produce same output.
   - Collision handling: when first candidate exists, retry produces a different ID.

2. **Message short hash generation**
   - Given conversation_friendly_id "react_perf_b4f2" and message text "Hello", returns stable 6-char base36.
   - Different messages produce different hashes.
   - Same message + same conv_fid always produces same hash (deterministic).
   - Different conv_fid + same message produces different hash (scoped to conversation).

3. **Base36 conversion**
   - `_to_base36(0, 4)` → `"aaaa"` (all zeros).
   - `_to_base36(35, 1)` → `"9"`.
   - `_to_base36(36, 2)` → `"ba"`.
   - Output length is always exactly the requested length.

4. **Reference regex pattern**
   - Valid patterns parse correctly:
     - `conversation_react_optimization_b4f2_message_5` → conv_fid=`react_optimization_b4f2`, msg=`5`
     - `conversation_react_optimization_b4f2_message_a3f2b1` → conv_fid=`react_optimization_b4f2`, msg=`a3f2b1`
     - `conv_debug_b4f2_msg_3` → conv_fid=`debug_b4f2`, msg=`3`
     - `conversation_chat_a1b2_message_1` → conv_fid=`chat_a1b2`, msg=`1` (single-word title)
   - Invalid patterns do NOT match:
     - `react_optimization_b4f2` (no `conversation_` prefix)
     - `conversation_react_optimization_b4f2` (no `_message_` part)
     - `conversation__message_5` (empty conv_fid)
   - Edge case: conv_fid containing "message" as a word: `conversation_message_passing_b4f2_message_3` → conv_fid=`message_passing_b4f2`, msg=`3` (greedy match works correctly)

5. **Resolver behavior**
   - Resolves by 1-based index: `_message_1` → first message.
   - Resolves by hash: `_message_a3f2b1` → message with matching `message_short_hash`.
   - Out-of-range index (0, negative, > len): logs warning, skips.
   - Unknown conversation friendly_id: logs warning, skips.
   - Missing hash (no message matches): logs warning, skips.
   - Ownership check: cannot resolve conversation not mapped to user_email.

### Integration Tests (Python)

1. **End-to-end: conversation friendly ID creation**
   - Create a new conversation, send first message.
   - Assert `get_metadata()` returns `conversation_friendly_id` (non-empty string matching `{word}_{word}_{hash}` pattern).
   - Assert DB: `SELECT conversation_friendly_id FROM UserToConversationId WHERE conversation_id=?` returns matching value.

2. **End-to-end: message hash stored**
   - After first turn, call `get_message_list()` and ensure each message has `message_short_hash` field.
   - Hash is 6 chars, lowercase alphanumeric.
   - User message hash differs from response message hash.

3. **End-to-end: backfill**
   - Create a conversation without a friendly_id (simulate old data).
   - Call `list_conversation_by_user()`.
   - Assert the conversation now has a `conversation_friendly_id` in the response.

4. **End-to-end: cross-conversation reference injection**
   - Create conversation A, send a message with known text.
   - Create conversation B.
   - In conversation B, send a message referencing conversation A: `@conversation_<A's_fid>_message_1`.
   - Assert `_get_pkb_context()` output contains `[REFERENCED @conversation_...]` block.
   - Assert the block contains conversation A's message text.

### Manual UI Tests

1. **Sidebar context menu**
   - Right-click a conversation → "Copy Conversation Reference" item is visible (first in menu).
   - Click it → clipboard contains the friendly ID (e.g. `react_optimization_b4f2`).
   - For conversations without friendly IDs → item is grayed out / disabled.
   - Triple-dot button → same menu with same behavior.

2. **Message cards**
   - Open a conversation → each message card header shows `#<index>` or `#<index> · <hash>`.
   - Click the badge → clipboard contains `@conversation_<fid>_message_<hash>` (or `_<index>` if no hash).
   - Badge shows brief "Copied!" feedback, then restores.

3. **Streaming**
   - Send a new message → user card initially shows `#N` (no hash).
   - Once response starts streaming and `message_ids` arrive → both user and assistant badges update with hashes.

4. **Chat behavior**
   - Type `@conversation_<fid>_message_<index>` and send → assistant uses that message's content in its response.
   - Mixed references: `@conversation_<fid>_message_1 @some_pkb_claim` → both resolve correctly.
   - Ensure no regression to existing PKB @reference autocomplete and resolution.

### Performance Checks

- Reference a message from a non-cached conversation and measure latency (should be < 500ms for disk load).
- Reference multiple messages from the same conversation → verify within-request caching (loads conversation once).
- Backfill 100 conversations on first `list_conversation_by_user` call → measure latency (should be < 3 seconds).

## Risks and Mitigations

### 1) Conversation friendly_id collisions

Risk:
- Two conversations generate the same `{w1}_{w2}_{h4}`.

Mitigation:
- Check DB uniqueness per user+domain and re-hash with salt on collision.
- Keep collision loop bounded (e.g. 5 attempts) then fall back to including more hash chars.

### 2) Message references break after message edits

Risk:
- If message hash is computed from text on the fly, editing changes the hash.

Mitigation:
- Persist `message_short_hash` at creation time (recommended).
- When messages are edited, do not recompute stored short hash.

### 3) Message references break after message reordering

Risk:
- Index-based references can shift if messages are moved.

Mitigation:
- Support hash-based references and encourage copying hash-based references.
- In UI, copy-by-default can use hash (stable), while still displaying index for readability.

### 4) Loading other conversations adds latency

Risk:
- Cross-conversation references require loading another conversation object and reading its messages.

Mitigation:
- Use `state.conversation_cache` via dependency injection (`query["_conversation_loader"]`) — LRU cache (200 entries) avoids disk I/O for recently-accessed conversations.
- Keep a cap on referenced message length (truncate at 8000 chars).
- Cache within the request: if multiple references point to the same conversation, load once (loaded_conversations dict).
- Fallback to `Conversation.load_local()` from disk only when cache is unavailable (tests, standalone usage).

### 5) Security: referencing other users' conversations

Risk:
- If lookup is not scoped, user could guess a friendly ID.

Mitigation:
- DB lookup always constrained by `user_email`.
- Do not allow direct `conversation_id` addressing in reference syntax.

### 6) UI clutter

Risk:
- Adding hash/index to headers could clutter the UI.

Mitigation:
- Keep typography small and monospace.
- Use muted color.
- Hide on very small screens or move into a tooltip.

### 7) Autocomplete complexity

Risk:
- Trying to add full message-level autocomplete may explode scope.

Mitigation:
- MVP relies on copy-to-clipboard.
- Conversation-level autocomplete can be added later with a small DB-backed endpoint.

## Files to Create/Modify (Summary)

### New Files (2)

| File | Purpose | Lines (est.) |
|------|---------|-------------|
| `conversation_reference_utils.py` | Utility module: `generate_conversation_friendly_id()`, `generate_message_short_hash()`, `_to_base36()` | ~100 |
| `tests/test_conversation_references.py` | Unit tests for ID generation, regex parsing, resolver logic | ~200 |

### Modified Files (7)

| File | Changes | Milestone |
|------|---------|-----------|
| `database/connection.py` | Add `ALTER TABLE UserToConversationId ADD COLUMN conversation_friendly_id text` migration + index (after line 180) | M0 |
| `database/conversations.py` | Add 3 new functions: `setConversationFriendlyId()`, `getConversationIdByFriendlyId()`, `conversationFriendlyIdExists()` (after line 279) | M0 |
| `Conversation.py` | Add `_ensure_conversation_friendly_id()` method; modify `persist_current_turn()` to accept `users_dir` and call friendly ID generation; modify `get_metadata()` to include `conversation_friendly_id`; modify `get_message_list()` to backfill hashes; modify `_get_pkb_context()` to accept `users_dir`/`conversation_loader` and resolve conversation refs; modify `reply()` to extract and pass new query fields; add `_resolve_conversation_message_refs()` method | M1, M2, M4 |
| `endpoints/conversations.py` | Inject `query["_users_dir"]` and `query["_conversation_loader"]` in `/send_message` handler (after line 1320); add backfill logic in `list_conversation_by_user()` (after line 1202) | M1, M4 |
| `interface/workspace-manager.js` | Add `data-conversation-friendly-id` to conversation node `li_attr` in `buildJsTreeData()` (line ~300); add "Copy Conversation Reference" menu item in `buildConversationContextMenu()` (line ~650) | M3 |
| `interface/common-chat.js` | Add `.message-ref-badge` span in `renderMessages()` card header (line ~2265); add click-to-copy handler for `.message-ref-badge`; add `ConversationManager.activeConversationFriendlyId` property; populate it in `setActiveConversation()`; add streaming hash update in `renderStreamingResponse()` (line ~1220) | M3 |

### Documentation Files (4, Milestone 5)

| File | Changes |
|------|---------|
| `documentation/features/cross_conversation_references/README.md` | New feature documentation (comprehensive) |
| `documentation/features/conversation_flow/README.md` | Add "Cross-Conversation Message References" section |
| `documentation/features/workspaces/README.md` | Update context menu section to mention "Copy Conversation Reference" |
| `documentation/product/behavior/chat_app_capabilities.md` | Add cross-conversation references capability |

### Files NOT Modified

| File | Reason |
|------|--------|
| `truth_management_system/interface/structured_api.py` | Conversation refs are intercepted before PKB resolution — no changes to `resolve_reference()` |
| `interface/parseMessageForCheckBoxes.js` | Existing `/@([a-zA-Z][a-zA-Z0-9_-]{2,})/g` regex already captures `conversation_..._message_...` patterns — no changes needed |
| `interface/workspace-styles.css` | Message ref badge styling is inline; no CSS changes needed for context menu item (vakata handles it) |
| `database/workspaces.py` | Workspace tables/functions unaffected |

## Implementation Ordering and Dependencies

```
M0: DB + Utils (no runtime changes, safe to deploy)
 └── M1: Friendly ID Generation + Backfill (backend only, no UI changes yet)
      ├── M2: Message Hashes (backend only, extends M1)
      │    └── M3: UI Discoverability (frontend changes, depends on M1+M2 data being available)
      └── M4: Backend Resolution (can be done in parallel with M3, depends on M0+M1)
           └── M5: Documentation + Autocomplete Prep (final, depends on M3+M4)
```

Key parallelism opportunity: M3 (UI) and M4 (Backend Resolution) can be developed in parallel once M1 and M2 are complete. M3 only needs the data (friendly IDs and hashes) to be present in the API responses. M4 only needs the DB helpers and conversation loading infrastructure.

---

**End of Plan**
