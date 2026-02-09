# Cross-Conversation Message References

**Last Updated:** 2026-02-09
**Status:** Implemented (M0-M4), XML-tagged PKB format
**Related Docs:**
- [Conversation Flow](../conversation_flow/README.md) -- message send/render pipeline
- [PKB Reference Resolution Flow](../truth_management_system/pkb_reference_resolution_flow.md) -- existing `@reference` system
- [Workspaces](../workspaces/README.md) -- jsTree sidebar, context menus

---

## Summary

Users can reference specific messages from any of their conversations using `@conversation_<friendly_id>_message_<index_or_hash>` syntax. The referenced message content is injected into the LLM prompt alongside PKB claims, giving the assistant access to prior outputs without manual copy-paste.

The system introduces two new identifier types:
- **Conversation friendly ID** -- short, human-readable identifier like `react_optimization_b4f2`
- **Message short hash** -- 6-char alphanumeric per-message hash like `a3f2b1`

These are discoverable from the UI (sidebar context menu and message card badges) and resolved by the backend when included in a message.

---

## User Workflow

1. **Discover identifiers:**
   - Right-click a conversation in the sidebar -> "Copy Conversation Reference" -> copies the friendly ID to clipboard (e.g. `react_optimization_b4f2`).
   - In a conversation, each message header shows a badge like `#5 . a3f2b1`. Clicking the badge copies the full `@conversation_<fid>_message_<hash>` reference.

2. **Use a reference:**
   - Paste or type `@conversation_react_optimization_b4f2_message_a3f2b1` in any message.
   - The existing `@friendly_id` regex captures the full string and sends it as a `referenced_friendly_ids` entry.

3. **Backend resolution:**
   - `_get_pkb_context()` detects the `conversation_..._message_...` pattern before PKB resolution.
   - Looks up the conversation by friendly ID in the DB, loads the conversation, extracts the target message by hash or index.
   - Injects the message content as a `[REFERENCED @conversation_...]` block alongside PKB claims.
   - The `[REFERENCED ...]` prefix ensures the content survives post-distillation re-injection.

---

## Reference Syntax

```
@conversation_<conv_friendly_id>_message_<index_or_hash>
```

- **By index (1-based):** `@conversation_react_optimization_b4f2_message_5`
- **By hash (6-char):** `@conversation_react_optimization_b4f2_message_a3f2b1`
- **Short alias:** `@conv_<fid>_msg_<identifier>` also supported

The `conversation_` prefix prevents collisions with PKB friendly IDs. The regex uses a greedy `.+` to capture the friendly ID up to the last `_message_` or `_msg_` occurrence, correctly handling underscores in friendly IDs.

---

## Identifier Generation

### Conversation Friendly ID

Format: `{word1}_{word2}_{4-char-base36-hash}`

- Words extracted via `_extract_meaningful_words()` from `truth_management_system/utils.py` (stopword removal, lowercase).
- Hash: `mmh3.hash(title + created_at, signed=False)` converted to 4-char base36.
- Collision handling: up to 5 retry attempts with salt (`conversation_id + attempt`), then extend hash to 6 chars.
- Generated on first persist after the title is created (in `persist_current_turn()`).
- Stored in both `memory["conversation_friendly_id"]` and the `UserToConversationId` DB table.

### Message Short Hash

Format: 6-char lowercase base36

- Input: `mmh3.hash(conversation_friendly_id + message_text, signed=False)` converted to 6-char base36.
- Scoped to conversation (different conversations produce different hashes for the same text).
- Persisted in message dicts at persist time (in `message_short_hash` field).
- Backfilled on-the-fly for old messages in `get_message_list()` (non-persisting).

---

## DB Schema

### Modified table: `UserToConversationId`

```sql
ALTER TABLE UserToConversationId ADD COLUMN conversation_friendly_id text;
CREATE INDEX idx_UserToConversationId_friendly_id
    ON UserToConversationId (user_email, conversation_friendly_id);
```

Migration is idempotent (`try/except` in `database/connection.py:create_tables()`), following the existing `parent_workspace_id` migration pattern.

### DB helper functions (`database/conversations.py`)

| Function | Purpose |
|----------|---------|
| `setConversationFriendlyId(users_dir, user_email, conversation_id, conversation_friendly_id)` | Store friendly ID in DB |
| `getConversationIdByFriendlyId(users_dir, user_email, conversation_friendly_id)` | Look up `conversation_id` from friendly ID |
| `conversationFriendlyIdExists(users_dir, user_email, conversation_friendly_id)` | Collision check |

---

## API Changes

### `GET /list_conversation_by_user/<domain>`

Each conversation metadata item now includes:
- `conversation_friendly_id` (string) -- the short friendly ID, or `""` if not yet generated.

Old conversations without friendly IDs are lazily backfilled on the first list call.

### `GET /list_messages_by_conversation/<conversation_id>`

Each message dict now includes:
- `message_short_hash` (string, 6-char) -- backfilled on-the-fly for old messages.

### Streaming `message_ids` chunk

Extended with short hashes:
```json
{
  "message_ids": {
    "user_message_id": "...",
    "response_message_id": "...",
    "user_message_short_hash": "...",
    "response_message_short_hash": "..."
  }
}
```

### `POST /send_message/<conversation_id>`

Server-side injection (in addition to existing `conversation_pinned_claim_ids`):
- `query["_users_dir"]` -- path to users directory for DB access.
- `query["_conversation_loader"]` -- callable for cache-aware conversation loading.

---

## UI Details

### Sidebar context menu (workspace-manager.js)

A new **"Copy Conversation Reference"** item is added as the first entry in `buildConversationContextMenu()`:
- Icon: `fa fa-at`
- Copies the `conversation_friendly_id` string to clipboard (e.g. `react_optimization_b4f2`).
- Disabled (grayed out) when the conversation has no friendly ID yet.
- Separator after the item to visually separate it from existing actions.
- No changes to the conversation node text, tooltip, or jsTree display.

The `conversation_friendly_id` is stored as `data-conversation-friendly-id` in the jsTree node `li_attr`.

### Message card badges (common-chat.js)

Each message card header now includes a **ref badge** after the sender label:
```
You  #3 . a3f2b1
Assistant  #4 . 8kf2n1
```

- Small monospace text, muted color, 0.65rem font size.
- Click copies the full `@conversation_<fid>_message_<hash>` reference to clipboard.
- Shows "Copied!" briefly (1200ms) then restores.
- Prefers hash over index for stability (falls back to index if hash unavailable).

### Streaming badge updates

When `message_ids` arrive during streaming:
- The response card's badge is updated with `response_message_short_hash`.
- The previous user card's badge is updated with `user_message_short_hash`.

### ConversationManager property

`ConversationManager.activeConversationFriendlyId` is populated from `WorkspaceManager.conversations` when `setActiveConversation()` is called.

---

## Backend Resolution

### Resolution flow in `_get_pkb_context()`

1. **Separate references:** Before PKB resolution, `referenced_friendly_ids` are partitioned:
   - Items matching `CONV_REF_PATTERN` go to `conv_refs` list.
   - Everything else goes to `pkb_fids` for normal PKB resolution.

2. **Resolve conversation refs:** `_resolve_conversation_message_refs()` is called:
   - DB lookup: `getConversationIdByFriendlyId()` (scoped to `user_email`).
   - Load conversation: via `conversation_loader` (cache-aware) or `Conversation.load_local()` fallback.
   - Within-request cache: if multiple refs target the same conversation, it is loaded once.
   - Message resolution: by 1-based index (digits) or by `message_short_hash` match.

3. **Format as mock claims:** Resolved messages are wrapped in mock claim-like objects with:
   - `claim_type = "conversation_message"`
   - `statement = "from <fid> #<idx> (<sender>):\n<text>"`
   - Truncated to 8000 chars max.
   - Wrapped in XML tag: `<pkb_item source="referenced" type="conversation_message" ref="@<full_ref>">...</pkb_item>`.

4. **Post-distillation preservation:** The `source="referenced"` attribute matches `_extract_referenced_claims()` so cross-conversation content is re-injected verbatim after distillation.

### Regex pattern

```python
CONV_REF_PATTERN = re.compile(
    r'^(?:conversation|conv)_(.+)_(?:message|msg)_([a-z0-9]+)$'
)
```

Greedy `.+` captures everything up to the LAST `_message_` or `_msg_`, correctly handling friendly IDs with underscores.

### Error handling

Fail-open: missing conversations or messages are logged and skipped. The rest of the PKB context proceeds normally.

---

## Files Modified

| File | Changes |
|------|---------|
| `conversation_reference_utils.py` | **New file.** ID generation utilities: `generate_conversation_friendly_id()`, `generate_message_short_hash()`, `_to_base36()`, `CONV_REF_PATTERN` regex |
| `database/connection.py` | Migration: `ALTER TABLE UserToConversationId ADD COLUMN conversation_friendly_id` + index |
| `database/conversations.py` | 3 new functions: `setConversationFriendlyId()`, `getConversationIdByFriendlyId()`, `conversationFriendlyIdExists()` |
| `Conversation.py` | `_ensure_conversation_friendly_id()`, `_resolve_conversation_message_refs()` methods; modified `persist_current_turn()`, `get_message_ids()`, `get_message_list()`, `get_metadata()`, `_get_pkb_context()`, `reply()` |
| `endpoints/conversations.py` | Injected `query["_users_dir"]`, `query["_conversation_loader"]`; added lazy backfill in `list_conversation_by_user()` |
| `interface/workspace-manager.js` | `data-conversation-friendly-id` in jsTree nodes; "Copy Conversation Reference" context menu item |
| `interface/common-chat.js` | `activeConversationFriendlyId` property; `.message-ref-badge` in card headers; click-to-copy handler; streaming hash updates |

## Files NOT Modified

| File | Reason |
|------|--------|
| `parseMessageForCheckBoxes.js` | Existing `/@([a-zA-Z][a-zA-Z0-9_-]{2,})/g` regex already captures `conversation_..._message_...` patterns |
| `structured_api.py` | Conversation refs are intercepted before PKB resolution in `_get_pkb_context()` |
| `database/workspaces.py` | Workspace tables unaffected |

---

## Implementation Notes

- The `conversation_friendly_id` is generated only once per conversation (on first title generation). It does not change if the title is later manually edited via `/title`.
- For first-turn messages (before the friendly ID exists), message hashes are not persisted but are backfilled on-the-fly when `get_message_list()` is called.
- The `_conversation_loader` uses the existing LRU cache (`conversation_cache`, maxsize=200 in `server.py`) to avoid redundant disk I/O.
- Security: all DB lookups are scoped to `user_email`. A user cannot reference another user's conversations.
- Autocomplete for conversation references is not implemented in MVP (Phase 2 in the plan). Users discover identifiers via the copy UI.
