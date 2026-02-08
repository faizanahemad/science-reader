# Cross-Conversation Message References

**Created:** 2026-02-08  
**Status:** Plan (Not Started)  
**Depends On:** PKB v0.7 (universal @references), current conversation system

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
9. [Implementation Plan](#implementation-plan)
10. [Testing Plan](#testing-plan)
11. [Risks and Mitigations](#risks-and-mitigations)

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
   - Conversation friendly name is visible in the sidebar (replacing or augmenting the summary line).
   - Message hash is visible in the message card header (beside "You" / "Assistant").
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
- Generated in `endpoints/conversations.py:_create_conversation_simple()` (line 1111): `email + "_" + 36 random chars`.
- Title is auto-generated by an LLM in `Conversation.persist_current_turn()` (line 3076-3187) after the first message is persisted. Can be manually set via `/title` slash command.

### How Messages Are Identified Today

| Identifier | Format | Example | Where Used |
|-----------|--------|---------|------------|
| `message_id` | `str(mmh3.hash(conv_id + user_id + text))` | `"3847291234"` | DOM attributes, delete/edit/move actions |
| `message-index` | Client-side count of cards in `#chatView` | `0, 1, 2, ...` (0-based) | DOM `message-index` attribute |

- `message_id` is generated by `Conversation.get_message_ids()` (line 2820-2839) using MurmurHash3 on `conversation_id + user_id + messageText`. It's deterministic but not human-readable.
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

- `Conversation.load_local(folder)` deserializes from dill `.index` file (line 1404-1422).
- `conversation_cache` (`DefaultDictQueue` in `server.py`, maxsize=200) is an LRU cache that auto-loads from disk when accessed by `conversation_id`.
- Loading any conversation is: `state.conversation_cache[conversation_id]` — returns a `Conversation` object.
- Messages are then: `conversation.get_message_list()` — returns the JSON array.

### Cross-Conversation Access Today

**None exists.** Each conversation is fully self-contained:
- `_get_pkb_context()` only accesses the PKB (shared claim store), never other conversations.
- No endpoint queries across multiple conversations for message content.
- The `conversation_cache` *can* load any conversation by ID, but this capability is only used for single-conversation endpoints, never for cross-referencing.
- The only shared knowledge store is the PKB (`pkb.sqlite`), which stores extracted claims, not raw messages.

### How @References Work Today (Relevant Parts)

**UI parsing** (`parseMemoryReferences()` in `parseMessageForCheckBoxes.js`, line 375-458):
- Regex: `/@([a-zA-Z][a-zA-Z0-9_-]{2,})/g` captures friendly IDs into `friendlyIds[]`.
- These are sent in the POST body as `referenced_friendly_ids`.

**Backend resolution** (`_get_pkb_context()` in `Conversation.py`, line 310-614):
- For each friendly_id, calls `api.resolve_reference(fid)` on the PKB `StructuredAPI`.
- Resolved claims are labeled `[REFERENCED @fid]` and given highest priority.
- The formatted context is injected into the LLM prompt.

**resolve_reference()** (`structured_api.py`, line 1159+):
- Uses suffix-based routing: `_context`, `_entity`, `_tag`, `_domain` suffixes route directly.
- No suffix → backwards-compatible path (claim_number → claim friendly_id → legacy context → context name).
- **No handling for conversation or message references** — these would be a new branch.

### Sidebar UI Today

In `workspace-manager.js:createConversationElement()` (line 378-416):
```html
<div class="conversation-content flex-grow-1">
    <strong class="conversation-title-in-sidebar">${title (max 45 chars)}</strong>
    <div class="conversation-summary">${summary (max 60 chars)}...</div>
</div>
```

### Message Card Header Today

In `common-chat.js:renderMessages()` (line 2226-2280):
```html
<div class="card-header d-flex justify-content-between align-items-center">
    <div class="d-flex align-items-center">
        <input type="checkbox" class="history-message-checkbox" ...>
        <small><small><strong>You / Assistant</strong></small></small>
        ${actionDropdown}
    </div>
    <div class="d-flex align-items-center">
        <button class="copy-btn-header" title="Copy Text">...</button>
        <div class="dropdown vote-menu-toggle">...</div>
    </div>
</div>
```

### Key Files Summary

| Area | File | Relevant Lines/Functions |
|------|------|------------------------|
| Conversation constructor | `Conversation.py` | Line 187-232, `__init__()` |
| Message ID generation | `Conversation.py` | Line 2820-2839, `get_message_ids()` |
| Message persistence | `Conversation.py` | Line 2988-3210, `persist_current_turn()` |
| Title generation | `Conversation.py` | Line 3076-3187 (LLM-based) |
| Conversation metadata | `Conversation.py` | Line 7588-7607, `get_metadata()` |
| Message list access | `Conversation.py` | Line 7584-7586, `get_message_list()` |
| PKB context retrieval | `Conversation.py` | Line 310-614, `_get_pkb_context()` |
| Referenced claims extraction | `Conversation.py` | Line 249-308, `_extract_referenced_claims()` |
| conversation_id generation | `endpoints/conversations.py` | Line 1111-1113, `_create_conversation_simple()` |
| Conversation list endpoint | `endpoints/conversations.py` | Line 1133-1235, `list_conversation_by_user()` |
| Message list endpoint | `endpoints/conversations.py` | Line 63-86, `list_messages_by_conversation()` |
| Conversation cache | `server.py` | Line 103-120, `load_conversation()` + `DefaultDictQueue` |
| Sidebar rendering | `interface/workspace-manager.js` | Line 378-416, `createConversationElement()` |
| Message card header | `interface/common-chat.js` | Line 2226-2280, `renderMessages()` |
| @reference parsing (UI) | `interface/parseMessageForCheckBoxes.js` | Line 375-458, `parseMemoryReferences()` |
| @reference resolution (backend) | `truth_management_system/interface/structured_api.py` | Line 1159+, `resolve_reference()` |
| PKB autocomplete | `interface/common-chat.js` | Line 3428-3511, `fetchAutocompleteResults()` |
| DB conversation mapping | `database/conversations.py` | `UserToConversationId`, `ConversationIdToWorkspaceId` tables |

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
- Users DB (for lookup): add `conversation_friendly_id` to the `UserToConversationId` mapping row.

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

Recommended (cache-aware, best performance):
- Use `state.conversation_cache[conversation_id]`.

But `Conversation.py` does not have access to `state`. To avoid tight coupling to `endpoints.state.get_state()`, we prefer:

Dependency-injection approach:
- Inject a `conversation_loader` callable (or the cache object) into `Conversation.reply()` / `_get_pkb_context()`.
- The endpoint layer already injects `conversation_pinned_claim_ids` into `query`; similarly it can attach a loader, but Python objects should not be sent in JSON.

Practical approach for this repo (simple, works immediately):
- Load directly from disk using `Conversation.load_local()`.
  - The conversation root folder can be derived from `self._storage`:
    - `conv_root = os.path.dirname(self._storage)`
    - `other_path = os.path.join(conv_root, other_conversation_id)`
  - This avoids importing endpoint state.

Plan decision:
- Start with direct `Conversation.load_local()` (no new dependencies).
- If performance becomes an issue, add a small optional hook to use the cache when available.

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

We need to make conversation/message identifiers discoverable and easy to copy.

### 1) Sidebar: show conversation friendly ID

Current sidebar rendering is in `interface/workspace-manager.js:createConversationElement()` (line 378+).

Today it shows:
- `conversation.title` (truncated)
- `conversation.summary_till_now` (truncated) in `.conversation-summary`

Change:
- Replace the summary line with a friendly ID line, or show both.

Recommended layout (keep summary available, but deprioritize):
- Line 1: Title
- Line 2: Friendly ID (monospace, copyable)
- Optional Line 3 (smaller/grey): summary snippet

Implementation:
- Ensure `Conversation.get_metadata()` includes `conversation_friendly_id`.
- Update `createConversationElement()` to render it:
  - e.g. in the `.conversation-summary` div, show something like:
    - `<code>@conversation_<friendly_id></code>`
  - or show the raw `friendly_id` without the `@conversation_` prefix to reduce noise.

Copy UX:
- Clicking the friendly ID line copies `conversation_<friendly_id>` or `@conversation_<friendly_id>` to clipboard.
- Keep this as a small inline element with `cursor: pointer`.

### 2) Message cards: show message short hash

Current header is built in `interface/common-chat.js:renderMessages()` (line 2259+).
It currently renders:
- checkbox
- sender label ("You" / "Assistant")
- actions

Change:
- Add a small badge next to sender label:
  - `#<index>` and/or `<hash>`.

Recommended:
- show both: `#5 · a3f2b1`
  - index improves discoverability
  - hash is stable even if messages are inserted/moved

Implementation:
- Ensure message objects include `message_short_hash` (persisted or computed in backend and included in message payload returned by `/list_messages_by_conversation`).
- Update the card header template to include:
  - `<span class="message-ref text-muted" style="font-family: monospace; font-size: 0.75rem;">#${displayIndex} · ${hash}</span>`

Copy UX:
- On click, copy the full canonical reference:
  - `@conversation_<conv_friendly_id>_message_<index>` (or `_message_<hash>`)

Where the UI gets `conv_friendly_id`:
- It must be present in conversation metadata stored in `ConversationManager` state (from `get_metadata()` and list endpoint).

Streaming case:
- When the first streaming chunk creates the placeholder assistant card, the `message_id` is not known yet.
- Once `part['message_ids']` arrives, we already update attributes (line 1210+).
- At that moment we should also set/update the displayed short hash if the server provides it.

### 3) Conversation details panel (optional)

If there is a conversation header area (outside the sidebar), we can show:
- `conversation_friendly_id`
- a "Copy conversation reference" button

This is optional; sidebar + message headers are sufficient.

### 4) Message list API payload changes

The UI mostly renders messages from `/list_messages_by_conversation/<conversation_id>`.

We should extend the message dict schema to include:
- `message_short_hash` (string)
- `message_index_1based` (optional convenience)

If we do not include `message_index_1based`, the UI can compute it as it iterates.

### 5) Minimal UI disruption principle

- Do not change existing action menus or checkbox semantics.
- Add new elements adjacent to existing labels.
- Ensure mobile layout remains stable (use compact monospace text and avoid wrapping).

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
  - searches `UserToConversationId.conversation_friendly_id LIKE '<prefix>%` for the current user
  - returns small payload: `{ friendly_id, title }`.
- Extend the existing autocomplete dropdown in `interface/common-chat.js`:
  - detect that the current prefix begins with `conversation_` and call the new endpoint
  - render results under a new category (e.g. "Conversations") with icon `bi-chat-dots`
  - insert `@conversation_<fid>_message_`.

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

## Implementation Plan

Milestones are ordered to keep the system working end-to-end at every step.

### Milestone 0: Add data model fields (conversation friendly ID + created_at)

1. **Conversation memory schema**
   - Add `memory["created_at"]` if missing (string timestamp)
   - Add `memory["conversation_friendly_id"]` if missing

2. **DB schema update**
   - Add `conversation_friendly_id` column to `UserToConversationId`.
   - Add index on `(user_email, domain?, conversation_friendly_id)`.
   - Add migration path for existing users DB.

3. **Conversation metadata**
   - Update `Conversation.get_metadata()` to return `conversation_friendly_id`.

### Milestone 1: Generate and persist conversation_friendly_id

1. Implement a helper in `Conversation.py`:
   - `_ensure_conversation_friendly_id()`
   - Called from `persist_current_turn()` when first title is assigned.
   - Generates friendly ID using title + created_at.
   - Stores it in memory dict and writes DB mapping via `database/conversations.py` helper.

2. Backfill existing conversations:
   - Add a small one-time backfill path in list endpoint or a dedicated admin script:
     - for each conversation lacking friendly_id, generate from current title + last_updated or first created_at.
   - Prefer backfill-on-read to avoid heavy migrations initially.

### Milestone 2: Message short hash + API plumbing

1. Extend message dict schema at persistence time:
   - In `persist_current_turn()`, after `message_ids = self.get_message_ids(...)`, compute:
     - `user_message_short_hash`
     - `assistant_message_short_hash`
   - Add `message_short_hash` to each preserved message.

2. Ensure message list endpoints return `message_short_hash`:
   - `GET /list_messages_by_conversation/<conversation_id>` should include the new fields.
   - For existing stored messages without `message_short_hash`, compute on the fly (non-persistent) to avoid hard migration.

### Milestone 3: UI discoverability

1. Sidebar
   - Update `interface/workspace-manager.js:createConversationElement()` to show `conversation_friendly_id`.
   - Add click-to-copy.

2. Message card headers
   - Update `interface/common-chat.js:renderMessages()` to display `message_short_hash` and index.
   - Add click-to-copy that emits a canonical `@conversation_<fid>_message_<index or hash>` reference.

3. Streaming update
   - Ensure streamed message cards display the hash once message_ids arrive.

### Milestone 4: Backend resolution of conversation message references

1. Update `_get_pkb_context()` to intercept conversation references:
   - Parse `referenced_friendly_ids` and split into:
     - PKB references
     - conversation message references

2. Add DB lookup:
   - `getConversationIdByFriendlyId()`
   - Ensure ownership checks.

3. Load referenced conversation:
   - `Conversation.load_local()` from the conversations root.

4. Resolve the message by index/hash.

5. Inject formatted referenced message blocks into the returned context string with `[REFERENCED @...]` prefix.

### Milestone 5: Documentation + follow-ups

1. Update:
   - `documentation/features/conversation_flow/README.md` (add cross-conversation reference path)
   - `documentation/product/behavior/chat_app_capabilities.md` (new capability)

2. Optional Phase 2 autocomplete
   - Add `GET /conversations/autocomplete` and wire UI.

### Non-goals for initial implementation

- Global message search across all conversations
- Full message-level autocomplete
- Sharing references across users

## Testing Plan

### Unit Tests (Python)

1. Friendly ID generation
- Given a title and created_at, generates `{w1}_{w2}_{h4}`.
- Stopwords removed; punctuation stripped.
- Collision handling path exercised.

2. Message short hash generation
- Given conversation_friendly_id and message text, returns stable 6-char base36.
- Different messages produce different hashes.

3. Reference parser
- Valid patterns:
  - `conversation_x_y_z_message_1`
  - `conversation_x_y_z_message_a3f2b1`
- Invalid patterns reject:
  - missing parts
  - index 0
  - hash not length 6

4. Resolver behavior
- Resolves by index.
- Resolves by hash.
- Proper errors/skip on:
  - unknown conversation
  - out-of-range index
  - missing hash
- Ownership check: cannot resolve conversation not mapped to user.

### Integration Tests (Python)

1. End-to-end: conversation friendly ID creation
- Create a new conversation, send first message.
- Assert metadata contains `conversation_friendly_id`.
- Assert DB mapping includes it.

2. End-to-end: message hash stored
- After first turn, list messages and ensure each has `message_short_hash`.

3. End-to-end: cross-conversation reference injection
- Create conversation A with known message.
- Create conversation B and reference A's message via `@conversation_<fid>_message_<index>`.
- Assert `_get_pkb_context()` output contains `[REFERENCED @conversation_...]` block.

### Manual UI Tests

1. Sidebar
- Friendly ID renders for each conversation.
- Clicking copies the expected token.

2. Message cards
- Header shows `#<index> · <hash>`.
- Clicking copies `@conversation_<fid>_message_<index>` (or hash).

3. Chat behavior
- Typing a conversation reference and sending results in the assistant using that message content.
- Ensure no regression to PKB autocomplete and PKB references.

### Performance Checks

- Reference a message from a non-cached conversation and ensure latency is acceptable.
- Reference multiple messages from the same conversation (should reuse loaded messages within the request).

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

### 4) Loading other conversations from disk adds latency

Risk:
- Cross-conversation references require reading another conversation's messages JSON.

Mitigation:
- Keep a cap on referenced message length (truncate).
- Cache within the request: if multiple references point to the same conversation, load once.
- Later optimization: use `state.conversation_cache` via dependency injection.

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

---

**End of Plan**
