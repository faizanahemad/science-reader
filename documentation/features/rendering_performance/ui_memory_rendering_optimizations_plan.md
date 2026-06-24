# UI Memory & Rendering Optimizations — Implementation Plan (2026)

## Status: ALL CHANGES IMPLEMENTED

All five changes have been implemented and verified. See "Implementation Notes"
section at the bottom for details on what was actually committed.

## Background and Motivation

After the event-handler audit documented in `event_handler_audit_2026.md` (which
fixed handler stacking, deprecated DOM events, per-iteration DOM query explosions, and
redundant work on the streaming path), a second-pass review of the **page-load →
`list_messages` → render** flow identified a remaining set of memory-management and
rendering-overhead issues.

These are **not** correctness bugs — the UI works. They are efficiency gaps that, for
long sessions and large conversation histories (40–100+ messages), cause:

- Growing memory usage that is never reclaimed until a full page reload.
- Repeated per-card work on every render that scales linearly with history size.
- A redundant full-chat-view DOM traversal after every history render.

This document specifies five incremental, low-risk changes. Each is self-contained and
can be implemented and tested independently. They are ordered by
impact-to-risk ratio, but the order is not a hard dependency — a junior developer
may implement them in any order, though the suggested order minimizes context
switching between files.

> **Prerequisite reading:** `event_handler_audit_2026.md` (same directory) covers the
> prior round of fixes. This plan assumes those fixes are in place. Verify by
> checking that `common-chat.js:2603` uses `initialCardCount + originalIndex` (H6 fix)
> and `common-chat.js:2931-2934` scopes dropdown init to `newMessageElements`
> (dropdown 3-part fix) before starting.

---

## Flow Context (read this first)

When the page loads and a conversation is selected, this is the path we are optimizing:

1. `chat.js:623` `$(document).ready` → `interface.js:407` triggers `#assistant-tab`.
2. `activateChatTab()` (`common-chat.js:3251`) → `loadConversations` →
   `WorkspaceManager` autoselects a conversation →
   `ConversationManager.setActiveConversation` (`common-chat.js:686`).
3. `setActiveConversation` fires two things **in parallel**:
   - `RenderedStateManager.restore(conversationId)` (`common-chat.js:800-809`) —
     instant DOM paint from an IndexedDB HTML snapshot (fast path).
   - `ChatManager.listMessages(conversationId, includeUiState=true)`
     (`common-chat.js:811`) — GET `/list_messages_by_conversation/<id>?include_ui_state=true`.
4. On `$.when(restorePromise, messagesRequest).done(...)` (`common-chat.js:813`):
   - Populates `ConversationUIState._cache` from the response (`common-chat.js:853-854`).
   - If `RenderedStateManager.matchesMessages(snapshotMeta, msgList)` passes
     (`common-chat.js:860-861`), the snapshot is reused (skips `renderMessages`).
   - Otherwise calls `ChatManager.renderMessages(conversationId, msgList, true)`
     (`common-chat.js:866`), which runs a synchronous `messages.forEach` building
     every card (`common-chat.js:2609`+).

The optimizations below target steps 3–4 and the caches they populate.

---

## Change 1 — Delegated Focus Handlers + Module-Scope Focus State

### What

Convert the three **direct, per-card** event bindings in `renderMessages` into a
**single delegated handler** bound once on `#chatView` (or `document`), surviving
DOM replacement. Move the `focusTimer` / `currentFocusedMessageId` state out of
`renderMessages`'s function scope into module level.

### Why

Currently, inside the `messages.forEach` loop in `renderMessages`
(`interface/common-chat.js`), every card gets three direct jQuery binds:

- `messageElement.on('click', ...)` — `common-chat.js:2846`
- `messageElement.on('selectstart mouseup', ...)` — `common-chat.js:2858`
- `messageElement.on('focus focusin', ...)` — `common-chat.js:2874`

That is **3 × N binds per render** (120 binds for a 40-message history). Each handler
is a closure capturing the full `message` object (including its `text` string, which
can be large) and the shared `focusTimer` / `currentFocusedMessageId` variables
declared in `renderMessages`'s own scope (`common-chat.js:2593-2594`).

Problems:

1. **CPU cost**: 3N jQuery `.on()` calls + 3N closure allocations per render.
2. **Memory retention**: each closure holds a reference to the full `message` object.
   The rendered HTML already lives in the DOM as a separate string, so keeping the
   original `message.text` alive via the closure is pure waste — it cannot be GC'd
   until the card is removed on the next render.
3. **Re-binding on snapshot restore**: the snapshot-restore path
   (`common-chat.js:865-898`) restores HTML but loses JS handlers, so it has to
   re-run `initialiseVoteBank` per card (`common-chat.js:883-896`). Delegated
   handlers would survive this automatically (though `initialiseVoteBank` is still
   needed for copy/vote menus — see "Out of scope" below).

The prior audit (H-series in `event_handler_audit_2026.md`) already converted the
per-*button* handlers (`.delete-message-button`, `.move-message-up-button`, etc.) to
`$(document).on(...)` delegation for exactly these reasons. The three card-level
focus handlers were intentionally left as direct binds at the time; this change
finishes the job.

### How

#### Step 1 — Add a module-level focus-state holder

Near the top of `interface/common-chat.js` (alongside other module-level state such
as `_scrollToBottomInitDone` and `_chatViewResizeObserver` added by the M1 fix),
add:

```javascript
// Focus/URL-update state for the delegated card focus handler.
// Previously lived inside renderMessages' function scope, which meant each
// render created fresh closures over it. Hoisted to module scope so a single
// delegated handler can share it across all renders.
var _messageFocusTimer = null;
var _currentFocusedMessageId = null;
```

#### Step 2 — Extract `handleMessageFocus` to module scope

Currently `handleMessageFocus` is a nested function declared inside
`renderMessages` at `common-chat.js:2892`. Move it out to module scope (anywhere
near the new state vars) and make it read the shared module-level vars instead of
the closure-scoped ones:

```javascript
function handleMessageFocus(messageId, convId) {
    if (_messageFocusTimer) {
        clearTimeout(_messageFocusTimer);
    }
    var messageIdInUrl = getMessageIdFromUrl();
    if (_currentFocusedMessageId === messageId && messageIdInUrl === messageId) {
        return;
    }
    _currentFocusedMessageId = messageId;
    _messageFocusTimer = setTimeout(function() {
        updateUrlWithMessageId(convId, messageId);
        _messageFocusTimer = null;
    }, 1000);
}
```

This is a literal move + rename of the closure vars. No logic change.

#### Step 3 — Add a one-time delegated handler

Register the three event types as a **single delegated handler** bound once on
`document` (consistent with the other delegated handlers in `common.js:2649+`).
Place this in a module-level init block — either at the top of `common-chat.js`
inside the existing `$(document).ready` block at `common-chat.js:4522`/`4942`, or
in a small new init function called from `chat_interface_readiness()`
(`chat.js:103`). Binding once on `document` is simplest and matches the existing
pattern.

```javascript
// Delegated card focus handlers (bound once; survive #chatView DOM replacement).
// Replaces the 3 per-card direct binds previously created inside renderMessages.
$(document)
    .on('click.messageCardFocus', '.message-card', function(e) {
        if (_focusEventShouldBeIgnored(e)) return;
        if (typeof MultiSelectManager !== 'undefined' &&
            (MultiSelectManager.count() > 0 || e.metaKey || e.ctrlKey)) return;
        var messageId = _getMessageIdFromCard(this);
        if (messageId) {
            handleMessageFocus(messageId, ConversationManager.activeConversationId);
        }
    })
    .on('selectstart.messageCardFocus mouseup.messageCardFocus', '.message-card', function(e) {
        if (_focusEventShouldBeIgnored(e)) return;
        setTimeout(function() {
            var selection = window.getSelection();
            if (selection && selection.toString().trim().length > 0) {
                var messageId = _getMessageIdFromCard(e.currentTarget);
                if (messageId) {
                    handleMessageFocus(messageId, ConversationManager.activeConversationId);
                }
            }
        }, 10);
    })
    .on('focus.messageCardFocus focusin.messageCardFocus', '.message-card', function(e) {
        if (_focusEventShouldBeIgnored(e)) return;
        var messageId = _getMessageIdFromCard(this);
        if (messageId) {
            handleMessageFocus(messageId, ConversationManager.activeConversationId);
        }
    });
```

Add two small helpers next to the handler:

```javascript
// Returns true if the event originated from an interactive control inside the
// card (buttons, checkboxes, dropdowns) and should NOT trigger card focus.
// This is the same selector list previously inlined in all 3 direct binds.
function _focusEventShouldBeIgnored(e) {
    return $(e.target).closest(
        '.delete-message-button, .delete-pair-button, .history-message-checkbox, ' +
        '.move-message-up-button, .move-message-down-button, .show-doubts-button, ' +
        '.ask-doubt-button, .open-artefacts-button, .has-doubts-btn, .copy-btn-header, ' +
        '.pin-message-btn, .scroll-to-bottom-btn, .header-hide-toggle, .scroll-to-top-btn, ' +
        '.dropdown, .dropdown-menu, .dropdown-item, [data-toggle="dropdown"]'
    ).length > 0;
}

// Read the message-id from a card by looking at its header's attribute.
// The header carries message-id on .card-header[message-id] (set at render time).
function _getMessageIdFromCard(cardEl) {
    var $card = $(cardEl);
    var $header = $card.find('.card-header[message-id]').first();
    if (!$header.length) return null;
    var mid = $header.attr('message-id');
    return (mid && mid !== 'undefined') ? mid : null;
}
```

> **Why read `message-id` from the DOM instead of closing over it?** Because a
> delegated handler bound once cannot close over per-card data. Reading from the
> DOM attribute is cheap (one `.find` within the card subtree, not a full-document
> query) and the attribute is already stamped at render time
> (`common-chat.js:2672` builds the header with `message-id=${message.message_id}`).

#### Step 4 — Remove the direct binds and nested function from `renderMessages`

Delete:

- The three `messageElement.on(...)` blocks at `common-chat.js:2846-2881`.
- The nested `function handleMessageFocus(...)` at `common-chat.js:2892-2911`.
- The `let focusTimer = null;` and `let currentFocusedMessageId = null;`
  declarations at `common-chat.js:2593-2594`.

Leave the comment block at `common-chat.js:2914-2923` (about delegated per-button
handlers) and extend it to mention the focus handlers are now delegated too.

### Implementation Details

- **Namespacing**: use the `.messageCardFocus` event namespace on all three
  delegated binds. This is important — if any code ever needs to unbind just these
  handlers, it can do `$(document).off('.messageCardFocus')` without touching the
  other delegated handlers registered by `common.js` (which use their own
  namespaces or none). Check `grep -n "\.off(" interface/` before adding `.off()`
  calls — none currently target `.messageCardFocus`.
- **Where to bind**: a single `$(document).ready` block at module scope in
  `common-chat.js` is sufficient (there are already several ready blocks in this
  file at `4522`, `4942`, `5190`, `5575`). Add a new one or append to an existing
  one. Do NOT bind inside `renderMessages` — that would re-bind on every render,
  recreating the exact bug we are fixing.
- **`mouseup` handler**: note the original code used `setTimeout(..., 10)` to check
  the selection after the browser updates it. Preserve this — it is required for
  `window.getSelection()` to return the newly-selected text.
- **`ConversationManager.activeConversationId`**: the original closures captured
  `conversationId` from `renderMessages`'s argument. The delegated handler reads
  `ConversationManager.activeConversationId` at event time instead. This is safe
  because `setActiveConversation` sets `this.activeConversationId` at
  `common-chat.js:774` **before** firing `listMessages`, so by the time any focus
  event fires, the property is correct. Verify with:
  `grep -n "activeConversationId" interface/common-chat.js`.

### Risks

- **Low** — this mirrors the exact delegation pattern already used for the
  per-button handlers (H-series in the audit doc). The only behavioral change is
  reading `message-id` from the DOM instead of a closure, which is functionally
  equivalent because the attribute is set from the same `message.message_id` value
  at render time (`common-chat.js:2672`).
- **Snapshot-restore interaction**: delegated handlers fire on snapshot-restored
  cards automatically (they are in the DOM). This is a **benefit** — focus now
  works on restored cards without any re-init. `initialiseVoteBank` is still
  required for copy/vote menus (those bind non-focus handlers and build menu DOM),
  so the re-init loop at `common-chat.js:883-896` stays.
- **Multi-select guard**: the `click` handler checks
  `MultiSelectManager.count() > 0 || e.metaKey || e.ctrlKey`. Preserve this exactly
  — Cmd/Ctrl+click toggles the checkbox instead of focusing.

### Verification

1. Load a conversation with 10+ messages. Click on different cards → the URL should
   update to `/interface/<convId>/<messageId>` after ~1 second (debounced).
2. Select text within a card → URL should update to that card's message id.
3. Tab-navigate into a card → URL should update.
4. Click a card's delete/move/copy/dropdown button → URL should NOT update
   (the `.closest()` guard must block it).
5. Cmd/Ctrl+click a card → checkbox toggles, URL does NOT update.
6. Delete a message → reindex happens → click another card → URL updates to the
   new card's id (delegated handler reads live `message-id` attribute, which
   `reindexMessageCards` keeps current — see `common.js:2642`).
7. Snapshot-restore path: reload a conversation whose snapshot is valid (no
   re-render). Click a restored card → URL should update (proves delegated handler
   fires on restored HTML).

### Files Modified

- `interface/common-chat.js` — add module-level state + helpers + delegated binds;
  remove direct binds + nested `handleMessageFocus` + closure vars from
  `renderMessages`.

### Out of Scope

- `initialiseVoteBank` (`common.js:1565`) still binds copy/vote dropdown menu
  handlers per card on every render. Converting it to delegation is a larger
  refactor (it builds menu DOM and binds menu-item handlers tied to the card's
  `message-id` and `activeDocId`). Not included here.

---

## Change 2 — `ConversationUIState` LRU Eviction + Logout Clear

### What

Add a bounded LRU (least-recently-used) eviction policy to the
`ConversationUIState._cache` object so it holds at most N conversation entries, and
clear the cache on logout alongside the existing `RenderedStateManager.clearAll()`
call.

### Why

`ConversationUIState` (`interface/common.js:4508`) is an in-memory cache mapping
`conversationId → { section_details, message_show_hide }`. It is populated by:

- `setFromList(convId, msgList, sectionDetails)` (`common.js:4510`) — on every
  `list_messages` response with `include_ui_state=true` (the page-load path).
- `set(convId, ...)` (`common.js:4519`) — on the `/get_conversation_ui_state`
  fallback network path.
- `updateSection` / `updateMessage` (`common.js:4525, 4530`) — on user toggles.

It is **read** by:
- `fetchConversationUIState` (`common.js:4638`) — cache-first, avoids a second
  backend conversation load.
- `renderInnerContentAsMarkdown` (`common.js:5539`) — synchronous per-card apply
  to eliminate the expand-then-collapse flash.

**Problem**: the cache has **no eviction**. Every conversation visited during a
session adds an entry that is never removed. Each entry holds `section_details` (a
map of every section in the conversation) and `message_show_hide` (a map of every
message id). For a user who browses 50 conversations of 100 messages each in one
session, this grows without bound in heap memory until the page is reloaded.

Worse: it is **not cleared on logout**. The logout flow calls `clearSwCaches()`
(`common.js:6372`) which clears the Cache API and `RenderedStateManager.clearAll()`
(`common.js:6379`) for IndexedDB, but `ConversationUIState._cache` is left
populated. After a user logs out and another logs in on the same tab (without a
full reload), the prior user's UI state is still in memory — a minor data-hygiene
issue (in-memory only; not persisted, not cross-origin accessible, but still wrong).

### How

#### Step 1 — Add an LRU cap and access tracking to `ConversationUIState`

Edit the `window.ConversationUIState` object at `interface/common.js:4508`. The
current shape is:

```javascript
window.ConversationUIState = window.ConversationUIState || {
    _cache: {},
    setFromList: function(convId, msgList, sectionDetails) { ... },
    set: function(convId, sectionDetails, messageShowHide) { ... },
    has: function(convId) { ... },
    get: function(convId) { ... },
    updateSection: function(convId, sectionHash, hidden) { ... },
    updateMessage: function(convId, messageId, showHide) { ... }
};
```

Add:

1. A `MAX_ENTRIES` constant (suggest `20` — see "Choosing the cap" below).
2. A `_lastUsed` sibling map tracking access time per `convId`.
3. A private `_touch(convId)` helper that updates access time and runs eviction.
4. Call `_touch` inside `get` (the read path — this is what makes it LRU).
5. Call `_touch` inside `setFromList`, `set`, `updateSection`, `updateMessage`
   (the write paths — also count as access).
6. A `clear()` method that empties both maps.

```javascript
window.ConversationUIState = window.ConversationUIState || {
    _cache: {},
    _lastUsed: {},        // convId -> Date.now() of last access
    MAX_ENTRIES: 20,

    /** Mark a conversation as recently used and evict the oldest if over cap. */
    _touch: function(convId) {
        if (!convId) return;
        this._lastUsed[convId] = Date.now();
        var keys = Object.keys(this._cache);
        if (keys.length <= this.MAX_ENTRIES) return;
        // Find the oldest entry by _lastUsed and drop it.
        var oldestKey = null;
        var oldestTime = Infinity;
        for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            var t = this._lastUsed[k] || 0;
            if (t < oldestTime) {
                oldestTime = t;
                oldestKey = k;
            }
        }
        if (oldestKey) {
            delete this._cache[oldestKey];
            delete this._lastUsed[oldestKey];
        }
    },

    /** Empty the cache entirely (call on logout). */
    clear: function() {
        this._cache = {};
        this._lastUsed = {};
    },

    setFromList: function(convId, msgList, sectionDetails) {
        if (!convId) return;
        var messageShowHide = {};
        (msgList || []).forEach(function(m) {
            if (m && m.message_id) { messageShowHide[m.message_id] = m.show_hide || 'show'; }
        });
        this._cache[convId] = { section_details: sectionDetails || {}, message_show_hide: messageShowHide };
        this._touch(convId);
    },
    set: function(convId, sectionDetails, messageShowHide) {
        if (!convId) return;
        this._cache[convId] = { section_details: sectionDetails || {}, message_show_hide: messageShowHide || {} };
        this._touch(convId);
    },
    has: function(convId) { return !!(convId && this._cache[convId]); },
    get: function(convId) {
        if (!convId || !this._cache[convId]) return undefined;
        this._touch(convId);  // read counts as access for LRU
        return this._cache[convId];
    },
    updateSection: function(convId, sectionHash, hidden) {
        if (!convId || !sectionHash) return;
        var e = this._cache[convId] || (this._cache[convId] = { section_details: {}, message_show_hide: {} });
        e.section_details[sectionHash] = { hidden: !!hidden };
        this._touch(convId);
    },
    updateMessage: function(convId, messageId, showHide) {
        if (!convId || !messageId) return;
        var e = this._cache[convId] || (this._cache[convId] = { section_details: {}, message_show_hide: {} });
        e.message_show_hide[messageId] = showHide;
        this._touch(convId);
    }
};
```

> **Note on `get` returning `undefined`**: the current `get` returns
> `this._cache[convId]` which is `undefined` for a missing key. Callers already
> guard with `has()` first (`common.js:4638`, `common.js:5539`), so adding a
> `_touch` side-effect in `get` is safe. If you prefer a pure `get`, move the
> `_touch` call into `has` instead — but `has` is called slightly less often, so
> LRU accuracy is marginally worse. Either is acceptable.

#### Step 2 — Clear on logout

In `clearSwCaches()` at `interface/common.js:6372`, alongside the existing
`RenderedStateManager.clearAll()` call at `common.js:6379`, add:

```javascript
try {
    if (window.ConversationUIState && typeof window.ConversationUIState.clear === 'function') {
        window.ConversationUIState.clear();
    }
} catch (_e) { /* best-effort */ }
```

Place it immediately before or after the `RenderedStateManager.clearAll()` block
(`common.js:6378-6389`). Wrap in try/catch to match the defensive style of the
surrounding code.

### Implementation Details

- **Choosing the cap (MAX_ENTRIES)**: 20 is a reasonable default. A user rarely
  has more than a few conversations' UI state actively relevant. The cost of a
  cache miss is one extra `/get_conversation_ui_state` GET (which re-loads the
  conversation server-side) — so the cap should be high enough to avoid thrashing
  during normal back-and-forth between a handful of conversations, but low enough
  to bound memory. If unsure, start at 20; it is a single constant, easy to tune.
- **LRU vs FIFO**: LRU (evict least-recently-used) is chosen over FIFO because a
  user editing toggles in conversation A, then visiting B–Z, then returning to A
  should NOT lose A's cache. `_touch` on every read/write keeps A fresh.
- **No persistence**: this cache is intentionally in-memory only (it mirrors what
  `RenderedStateManager` persists to IndexedDB as DOM HTML). Do not add
  `localStorage` persistence — the `include_ui_state` flag on `list_messages`
  already rebuilds it from the server on load.
- **`Date.now()` vs a counter**: `Date.now()` is fine here (sub-millisecond
  precision is not needed; only ordering matters). A monotonic counter would also
  work and avoids clock-skew edge cases, but adds complexity. Stick with
  `Date.now()`.

### Risks

- **Very low** — eviction only drops a cache entry; the next access falls back to
  the network via `fetchConversationUIState` (`common.js:4644`). Worst case is a
  one-time extra GET request, not a bug.
- **LRU during rapid switching**: if a user flips between 25 conversations faster
  than the cap, the oldest get evicted and re-fetched on next visit. This is
  acceptable and bounded.
- **`_touch` in `get` mutates state during a read** — this is standard for LRU
  caches but be aware it means `get` is not pure. No caller relies on `get` being
  side-effect-free (verified: all call sites are `common.js:4639`,
  `common.js:5540`).

### Verification

1. Open DevTools, run in console:
   `Object.keys(window.ConversationUIState._cache).length`. Note the count.
2. Visit 25 different conversations (click each in the sidebar). Re-check the
   count — it should stay at or below `MAX_ENTRIES` (20).
3. Go back to the 1st conversation you visited (now evicted). Confirm the UI still
   renders correctly (it will re-fetch via `/get_conversation_ui_state` — watch
   the Network tab for one GET, and confirm no section-collapse flash appears,
   meaning the cache repopulated before paint).
4. Log out. In console: `Object.keys(window.ConversationUIState._cache).length`
   should be `0`.

### Files Modified

- `interface/common.js` — `ConversationUIState` object (`~4508-4535`) gains
  `_lastUsed`, `MAX_ENTRIES`, `_touch`, `clear`; write methods call `_touch`.
- `interface/common.js` — `clearSwCaches` (`~6372`) gains the `clear()` call.

---

## Change 3 — `cleanupMessageObservers()` in the Snapshot-Restore Path

### What

Call `cleanupMessageObservers()` at the top of the `$.when(...).done(...)` callback
in `setActiveConversation`, **before** the `keepSnapshot` branch, so that both the
re-render path and the snapshot-restore path start from a clean observer state.

### Why

`window.messageObservers` (`interface/common-chat.js:2375`) is a global array of
`MutationObserver` / `ResizeObserver` instances attached to message cards. It is
cleared by `cleanupMessageObservers()` (`common-chat.js:2379`), which disconnects
every observer and resets the array to `[]`.

Currently, `cleanupMessageObservers()` is called **only** from inside
`renderMessages` at `common-chat.js:2589` (inside the `if (shouldClearChatView)`
block). The snapshot-restore path (`common-chat.js:865-898`) skips `renderMessages`
entirely when `keepSnapshot` is true, so it never calls
`cleanupMessageObservers()`.

**Problem**: consider this sequence:

1. User loads conversation A → `renderMessages` runs, attaches observers to A's
   cards, pushes them into `window.messageObservers`.
2. User switches to conversation B whose snapshot is valid → `keepSnapshot` is
   true → the snapshot HTML replaces `#chatView`'s innerHTML (in
   `RenderedStateManager.applySnapshotToDom`, `rendered-state-manager.js:151`).
   A's cards are now detached from the DOM, but the observers in
   `window.messageObservers` still reference them and are never disconnected.
3. The observers themselves hold strong references to the detached card DOM nodes
   (via their internal callback closures), so those nodes cannot be GC'd until the
   observers are disconnected.

The leak is bounded (cleared on the next full re-render or on logout via
`clearAll` paths that incidentally reset state), but it is a genuine retention
gap that is trivial to close.

### How

In `interface/common-chat.js`, inside the `$.when(restorePromise, messagesRequest).done(...)`
callback, the current structure (around `common-chat.js:807`) is:

```javascript
$.when(restorePromise, messagesRequest).done(function (snapshotMeta, messages) {
    // ... payload normalization (818-841) ...
    // ... ConversationUIState.setFromList (847-851) ...

    var keepSnapshot = false;
    try {
        if (snapshotMeta && window.RenderedStateManager && window.RenderedStateManager.matchesMessages) {
            keepSnapshot = window.RenderedStateManager.matchesMessages(snapshotMeta, msgList);
        }
    } catch (_e) { keepSnapshot = false; }

    if (!keepSnapshot) {
        ChatManager.renderMessages(conversationId, msgList, true);
    } else {
        // ... snapshot-restore path (no cleanupMessageObservers call) ...
    }
    // ...
});
```

Add a single call **before** the `keepSnapshot` check (i.e., right after the
`ConversationUIState.setFromList` block at `common-chat.js:845`, before line 847):

```javascript
// Disconnect any observers from the previously-rendered conversation before
// we either replace #chatView (re-render) or paint over it (snapshot restore).
// The snapshot-restore path previously skipped this, leaving observers attached
// to detached DOM nodes from the prior conversation.
try { cleanupMessageObservers(); } catch (_e) { /* ignore */ }
```

Place it at approximately `common-chat.js:846` (after the `setFromList` try/catch,
before the `var keepSnapshot` declaration). The `renderMessages` call at line 855
will still call `cleanupMessageObservers()` again at `2578` — that is a harmless
no-op on an already-empty array (the `forEach` over `[]` does nothing).

### Implementation Details

- **Why before the branch, not inside the `else`?** Putting it before the branch
  means the re-render path also gets it for free, and the redundant call inside
  `renderMessages` (`2589`) becomes a harmless no-op. Putting it only inside the
  `else` would fix the snapshot path but leave the re-render path with two calls
  (one here, one in `renderMessages`) — slightly more confusing. Either placement
  works; the "before the branch" placement is simpler and self-documenting.
- **Idempotency**: `cleanupMessageObservers()` is idempotent. If
  `window.messageObservers` is `undefined` or `[]`, the `if` guard at
  `common-chat.js:2376` handles it. Safe to call multiple times.
- **Timing**: call it **after** `RenderedStateManager.restore` has already applied
  the snapshot HTML (which happens in the `restorePromise` that `$.when` waited
  for). This means the old conversation's DOM is already gone by the time we
  disconnect the observers — which is exactly when we want to disconnect them
  (they are observing detached nodes). Disconnecting a `MutationObserver` that is
  observing a detached subtree is well-defined and safe.

### Risks

- **Negligible** — `cleanupMessageObservers()` is already proven on the re-render
  path. This just extends it to the other branch.
- **No observer is needed across the A→B switch** — observers are per-card
  (attached during `initialiseVoteBank` / render), not per-conversation. New cards
  in conversation B will get fresh observers when they are rendered or vote-bank-
  initialized.

### Verification

1. In DevTools, set a breakpoint or `console.log` inside
   `cleanupMessageObservers` to count calls.
2. Load conversation A (full render) → one call (from `renderMessages`).
3. Switch to conversation B with a valid snapshot (snapshot restore) → confirm
   `cleanupMessageObservers` is now called (previously it was not).
4. Use DevTools "Memory" → "Take heap snapshot", switch between 5 conversations
   with valid snapshots, take another snapshot → search for detached
   `.message-card` nodes; there should be none retained by observers.

### Files Modified

- `interface/common-chat.js` — one line added at `~852` in the `.done` callback.

---

## Change 4 — `RenderedStateManager` IndexedDB LRU Eviction

### What

Add a bounded-eviction pass to `RenderedStateManager.saveNow` so that, after
writing a new snapshot, the store is pruned to at most N entries (by `savedAt`
timestamp) when the count exceeds the cap.

### Why

`RenderedStateManager` (`interface/rendered-state-manager.js`) persists full
`#chatView` HTML snapshots to IndexedDB keyed per conversation
(`rendered-state-manager.js:240-281`). Each snapshot can be up to
`MAX_HTML_CHARS = 4_000_000` characters (~4 MB, `rendered-state-manager.js:28`).

**Problem**: there is no eviction. `saveNow` (`rendered-state-manager.js:240`)
writes a record and never prunes. The only cleanup paths are:

- `invalidate(conversationId)` (`:192`) — called per-conversation when a message
  is mutated (edit/delete/move). Does not bound total size.
- `clearAll()` (`:209`) — called only on logout (`common.js:6379`).

So across a single session, visiting 30 large conversations can accumulate
~120 MB of HTML in IndexedDB. Browsers' IDB quotas vary (often ~50% of free disk,
with per-origin eviction under pressure), but relying on quota eviction is
unpredictable and can cause `QuotaExceededError` on `saveNow`, which is silently
swallowed (`:266` `.catch(() => {})`) — meaning snapshots silently stop being
saved for new conversations.

### How

#### Step 1 — Add an eviction helper

In `interface/rendered-state-manager.js`, add a new function near the other store
helpers (after `withStore` at `:54` or near `clearAll` at `:209`):

```javascript
// Evict oldest snapshots once the store exceeds MAX_SNAPSHOTS entries.
// Called after every successful put in saveNow. Uses the savedAt index to
// avoid scanning all records. Best-effort: errors are swallowed.
const MAX_SNAPSHOTS = 20;

function evictOldest(db) {
  return new Promise(function (resolve) {
    try {
      var tx = db.transaction([STORE], "readwrite");
      var store = tx.objectStore(STORE);
      var countReq = store.count();
      countReq.onsuccess = function () {
        var total = countReq.result || 0;
        if (total <= MAX_SNAPSHOTS) { resolve(); return; }
        // Evict (total - MAX_SNAPSHOTS) oldest by savedAt index.
        var toEvict = total - MAX_SNAPSHOTS;
        var idx = store.index("savedAt");
        var cursorReq = idx.openCursor();  // ascending by savedAt
        var evicted = 0;
        cursorReq.onsuccess = function (event) {
          var cursor = event.target.result;
          if (!cursor || evicted >= toEvict) { resolve(); return; }
          cursor.delete();
          evicted++;
          cursor.continue();
        };
        cursorReq.onerror = function () { resolve(); };
      };
      countReq.onerror = function () { resolve(); };
      tx.oncomplete = function () { resolve(); };
      tx.onerror = function () { resolve(); };
    } catch (_e) {
      resolve();
    }
  });
}
```

> The `savedAt` index already exists (`rendered-state-manager.js:39`, created in
> `onupgradeneeded`). It is not unique, which is correct for timestamps.

#### Step 2 — Call it from `saveNow`

In `saveNow` (`rendered-state-manager.js:240`), the `write` function currently is:

```javascript
const write = () => {
  openDb()
    .then((db) => withStore(db, "readwrite", (store) => store.put(record)))
    .catch(() => { /* best-effort */ });
};
```

Change it to also run eviction after the put. Because `withStore` resolves on
transaction complete, and eviction needs its own transaction, chain it:

```javascript
const write = () => {
  openDb()
    .then((db) =>
      withStore(db, "readwrite", (store) => store.put(record)).then(() => evictOldest(db))
    )
    .catch(() => { /* best-effort */ });
};
```

The `.then(() => evictOldest(db))` runs eviction in a separate transaction after
the put transaction completes. `evictOldest` is best-effort and never rejects.

### Implementation Details

- **Why count + cursor and not a fixed delete?** The store may have fewer than
  `MAX_SNAPSHOTS` entries (common early in a session). `count()` is cheap (IDB
  stores a count). The cursor walks the `savedAt` index in ascending order, so it
  visits oldest-first — exactly what LRU wants.
- **MAX_SNAPSHOTS = 20** matches the `ConversationUIState.MAX_ENTRIES` cap from
  Change 2 for consistency. The two caches have different sizes per entry
  (ConversationUIState is small JSON; RenderedStateManager is up to 4MB HTML), so
  20 snapshots × 4MB = ~80MB worst case, which fits within typical IDB quotas
  with headroom. If your conversations are consistently large, lower this to 10.
- **Transaction scope**: `evictOldest` opens its own `readwrite` transaction
  separate from the put transaction. Do not combine them — `withStore`'s
  transaction is already committed by the time `.then` runs, and IDB does not
  allow extending a completed transaction.
- **No `Math.random` / `Date.now` for tie-breaking**: `savedAt` is set in
  `saveNow` (`rendered-state-manager.js:253`) as `Date.now()`. Two snapshots saved
  within the same millisecond would have equal `savedAt` — the cursor order among
  equal keys is unspecified, but eviction order among ties does not matter (any
  oldest one is fine to drop).
- **Do not evict the just-written record**: because `put` ran before
  `evictOldest`, the new record has the newest `savedAt` and is last in the
  ascending cursor — it will never be the one evicted (unless it is somehow older,
  which is impossible since `savedAt = Date.now()` is set moments before).

### Risks

- **Low** — eviction is best-effort and swallowed on error. Worst case: eviction
  fails silently and the store stays large (same as today's behavior).
- **Concurrent writes**: if two `saveNow` calls race (e.g., user switches
  conversations rapidly), both may run `evictOldest` concurrently. IDB
  readwrite transactions are serialized per object store, so this is safe — the
  second eviction sees the state after the first commits.
- **`QuotaExceededError` on put**: this change does not fix that error (it is
  swallowed at `:266`). But by keeping the store bounded, it makes quota errors
  far less likely to occur in the first place. If you want to be more defensive,
  add a `navigator.storage.estimate()` check before `put`, but that is out of
  scope here.

### Verification

1. Open DevTools → Application → IndexedDB → `science-chat-rendered-state` →
   `snapshots`. Note the record count.
2. Visit 25 different conversations (triggering snapshot saves). After each save,
   re-check the count — it should never exceed `MAX_SNAPSHOTS + 1` briefly, then
   settle back to `MAX_SNAPSHOTS` (20).
3. Confirm the oldest records (lowest `savedAt`) are the ones evicted.
4. Reload one of the evicted conversations — it should fall back to a full
   `renderMessages` (snapshot miss), and render correctly.
5. Check the Network tab: no new errors; `/list_messages_by_conversation` still
   loads.

### Files Modified

- `interface/rendered-state-manager.js` — add `MAX_SNAPSHOTS` constant,
  `evictOldest` function; call from `saveNow`'s `write`.

---

## Change 5 — Skip Redundant Debounced `applyConversationUIState`

### What

Track whether `applyConversationUIState` has already run synchronously during the
current render pass, and skip the debounced `fetchConversationUIState` re-apply
when it has.

### Why

`renderInnerContentAsMarkdown` (`interface/common.js:4690`) applies conversation UI
state (section collapse + message show/hide) **synchronously** to each card right
after writing its `innerHTML` (`common.js:5539-5551`):

```javascript
if (!continuous && !MOCK_SECTION_STATE_API) {
    try {
        var _uiConvId = ...;
        if (_uiConvId && window.ConversationUIState && window.ConversationUIState.has(_uiConvId)) {
            var _uiEntry = window.ConversationUIState.get(_uiConvId);
            var $_uiCard = $(elem_to_render_in).closest('.card.message-card');
            var _uiScope = $_uiCard.length ? $_uiCard : ...;
            applyConversationUIState(_uiEntry.section_details, _uiEntry.message_show_hide, _uiScope);
        }
    } catch (e) { /* ignore */ }
}
```

Then, in a `requestAnimationFrame` later in the same function
(`common.js:5562-5577`), it schedules a **debounced** `fetchConversationUIState`
call:

```javascript
requestAnimationFrame(function() {
    var resolvedConvId = ...;
    if (resolvedConvId && !continuous && !MOCK_SECTION_STATE_API) {
        attachSectionListeners(elem_to_render_in);
        clearTimeout(window._sectionStateFetchTimer);
        window._sectionStateFetchTimer = setTimeout(function() {
            var $chatView = $('#chatView');
            if ($chatView.length) {
                fetchConversationUIState(resolvedConvId, $chatView[0]);  // <-- re-applies
            }
        }, 300);
    }
    // ...
});
```

`fetchConversationUIState` (`common.js:4634`) is cache-first: if
`ConversationUIState.has(convId)` (which it does, since `setFromList` populated it
before render at `common-chat.js:854`), it calls `applyConversationUIState` again
over the **entire `#chatView`** (`common.js:4640`).

**Problem**: this second `applyConversationUIState` call is a **no-op for
correctness** (the state was already applied per-card) but it still:

- Walks every `.section-details` element in `#chatView` and sets its `open` prop
  (`common.js:4551-4567`).
- Iterates every key in `message_show_hide` and does a
  `$container.find('.card-header[message-id="..."]')` lookup per message
  (`common.js:4572-4574`).

For a 40-message conversation with 5 sections each, that is ~200 DOM traversals
300ms after every history load — wasted work that can cause a visible layout
recompute right as the user starts reading.

### How

#### Step 1 — Add an "already applied" flag to `ConversationUIState`

In `interface/common.js`, extend the `ConversationUIState` object (the same one
edited in Change 2) with a per-conversation flag:

```javascript
_appliedTo: {},   // convId -> true once applyConversationUIState has run for it this render

markApplied: function(convId) {
    if (convId) { this._appliedTo[convId] = true; }
},

isApplied: function(convId) {
    return !!(convId && this._appliedTo[convId]);
},

clearApplied: function(convId) {
    if (convId) { delete this._appliedTo[convId]; }
}
```

#### Step 2 — Set the flag after the synchronous per-card apply

In `renderInnerContentAsMarkdown` at `common.js:5551`, right after the
`applyConversationUIState(...)` call, add:

```javascript
applyConversationUIState(_uiEntry.section_details, _uiEntry.message_show_hide, _uiScope);
window.ConversationUIState.markApplied(_uiConvId);
```

#### Step 3 — Skip the debounced re-apply when the flag is set

In `fetchConversationUIState` (`common.js:4634`), the cache-first branch currently
is:

```javascript
if (window.ConversationUIState && window.ConversationUIState.has(conversation_id)) {
    var entry = window.ConversationUIState.get(conversation_id);
    applyConversationUIState(entry.section_details, entry.message_show_hide, elem_to_render_in);
    return;
}
```

Change it to skip the `applyConversationUIState` call if it was already applied
synchronously during render:

```javascript
if (window.ConversationUIState && window.ConversationUIState.has(conversation_id)) {
    // Skip the DOM walk if the synchronous per-card apply in
    // renderInnerContentAsMarkdown already painted the final state for this
    // render pass. The flag is cleared below before the next render.
    if (window.ConversationUIState.isApplied(conversation_id)) {
        return;
    }
    var entry = window.ConversationUIState.get(conversation_id);
    applyConversationUIState(entry.section_details, entry.message_show_hide, elem_to_render_in);
    return;
}
```

#### Step 4 — Clear the flag before the next render

The flag must be cleared when a new render begins, so that the synchronous apply
in `renderInnerContentAsMarkdown` re-runs (it always does) and the flag is re-set.
Clear it at the start of `renderMessages` in `interface/common-chat.js`, near the
top (e.g., right after `cleanupMessageObservers()` at `common-chat.js:2589`):

```javascript
try {
    if (window.ConversationUIState && typeof window.ConversationUIState.clearApplied === 'function') {
        window.ConversationUIState.clearApplied(conversationId);
    }
} catch (_e) { /* ignore */ }
```

Also clear it in the snapshot-restore path (`common-chat.js:865-898`), because
that path calls `fetchConversationUIState` directly at `common-chat.js:875` and
needs the apply to actually run (snapshot HTML does not go through
`renderInnerContentAsMarkdown`, so the synchronous per-card apply did not happen):

```javascript
// Inside the `else` (keepSnapshot) branch, before fetchConversationUIState:
try {
    if (window.ConversationUIState && typeof window.ConversationUIState.clearApplied === 'function') {
        window.ConversationUIState.clearApplied(conversationId);
    }
} catch (_e) { /* ignore */ }
```

Place it right before the `fetchConversationUIState(conversationId, $chatView[0])`
call at `common-chat.js:875`.

### Implementation Details

- **Why a flag and not just removing the debounced call?** The debounced
  `fetchConversationUIState` is still needed for:
  - The snapshot-restore path (no synchronous apply happened there).
  - The network-fallback path (when `ConversationUIState.has` is false at render
    time, e.g., the `include_ui_state` flag was not set, and the state arrives
    via the AJAX response later — `common.js:4644-4652`).
  - Any future code path that renders without going through the synchronous apply.
  The flag makes the call a no-op only when it is genuinely redundant.
- **The flag is per-conversation, not global**: `window._sectionStateFetchTimer`
  (`common.js:5471`) is global and shared across all cards in a batch — correct,
  because all cards share one debounced call. But the "applied" flag is per
  conversation because a user could switch conversations mid-debounce (unlikely
  but possible). Per-convId is safe and cheap.
- **Flag cleared on conversation switch**: the `clearApplied` call at the top of
  `renderMessages` handles the re-render path. For the snapshot-restore path, the
  explicit clear in the `else` branch handles it. If both paths are skipped
  somehow, the flag just stays set and the next `fetchConversationUIState` is a
  no-op — which is fine because there is nothing to apply to.
- **Interaction with `updateSection` / `updateMessage`**: these are called on
  user toggles (e.g., collapsing a section). They update the cache but do NOT
  touch the `_appliedTo` flag. This is correct — a user toggle after render
  directly mutates the DOM (the toggle handler does its own show/hide) and updates
  the cache; it does not need `applyConversationUIState` to re-run. If you want
  to be safe, you could call `clearApplied` inside `updateSection`/
  `updateMessage` too, but it is not necessary for correctness.

### Risks

- **Low** — the skip only triggers when the synchronous apply already ran for the
  same `convId` in the same render pass. The fallback paths (snapshot restore,
  network) explicitly clear the flag first.
- **Stale flag**: if `markApplied` is called but the DOM is later cleared without a
  new render (e.g., `$('#chatView').empty()` called from somewhere other than
  `renderMessages`), the flag stays set and the next `fetchConversationUIState`
  is a no-op. This is harmless — there is nothing to apply to an empty view, and
  the next proper render clears the flag. Grep confirms `$('#chatView').empty()`
  is only called from `renderMessages` (`common-chat.js:2584`).

### Verification

1. In DevTools, add a `console.log` inside `applyConversationUIState`
   (`common.js:4547`) counting calls.
2. Load a 40-message conversation (full re-render, snapshot stale). Observe:
   - `applyConversationUIState` is called ~40 times (once per card, synchronously).
   - After 300ms, the debounced `fetchConversationUIState` runs but does NOT call
     `applyConversationUIState` (flag is set). Total calls: ~40.
3. Compare with the pre-fix behavior: total calls would be ~40 + 1 (the debounced
   one over the whole view) = ~41. The single extra call is what we eliminate —
   it is the expensive one because its scope is the entire `#chatView`.
4. Trigger the snapshot-restore path (reload a conversation with a valid
   snapshot). Confirm `applyConversationUIState` DOES run once (via
   `fetchConversationUIState`, because the flag was cleared in the `else`
   branch). This proves the fallback path still works.
5. Functional check: collapse a section in a rendered card → it should stay
   collapsed (the cache was updated, the skip does not revert it).

### Files Modified

- `interface/common.js` — `ConversationUIState` gains `_appliedTo`, `markApplied`,
  `isApplied`, `clearApplied`; `fetchConversationUIState` cache-first branch
  gains the skip check; `renderInnerContentAsMarkdown` sets the flag after
  synchronous apply.
- `interface/common-chat.js` — `renderMessages` clears the flag at start;
  snapshot-restore `else` branch clears the flag before `fetchConversationUIState`.

---

## Render Speed Impact Assessment

| Change | Render Speed Benefit | Category | Rationale |
|--------|---------------------|----------|-----------|
| Change 1 (Delegated Focus) | **HIGH** | Render-path | Eliminates 3*N `.on()` calls + closure allocations inside the `messages.forEach` render loop. For 40 messages = 120 fewer jQuery binds during page-load render. Directly reduces time-to-interactive. |
| Change 2 (LRU Cache) | **None** | Memory | No code executes during render. Bounds long-session heap growth. |
| Change 3 (Observer cleanup) | **None** | Memory | Fixes retention of detached DOM nodes. No effect on render path timing. |
| Change 4 (IDB LRU) | **None** | Storage | Async IndexedDB operations, not on the synchronous render path. |
| Change 5 (Skip redundant apply) | **Low-Medium** | Post-render | Avoids one full-`#chatView` DOM traversal 300ms after render. Reduces post-render jank but not initial paint time. |

**Priority for render speed**: Change 1 >> Change 5 > Changes 2,3,4 (memory/storage only).

All five changes are valid optimizations, but only Change 1 directly reduces the
time the user waits on page-load render. Changes 2-4 are memory/storage hygiene
that prevent degradation over longer sessions. Change 5 reduces a post-render
DOM walk that can cause a visible recompute while the user starts reading.

---

## Logic Issues and Corrections (Review Notes)

### Line Number Drift

The `common-chat.js` references in this plan are systematically ~6-14 lines too
high compared to the current codebase state. Actual verified positions:

| Plan Reference | Actual Line | Delta |
|---|---|---|
| `$.when` callback ~813 | **807** | -6 |
| `focusTimer`/`currentFocusedMessageId` ~2593-2594 | **2582-2583** | -11 |
| Per-card binds ~2846/2858/2874 | **2840/2847/2863** | -6 to -11 |
| `cleanupMessageObservers` ~2375 | **2368** | -7 |
| `renderMessages` start ~2589 | **2575** | -14 |

`common.js` and `rendered-state-manager.js` references are accurate (exact match).

### Change 5 — `_appliedTo` Not Cleared on Logout

The `clear()` method added in Change 2 empties `_cache` and `_lastUsed` but the
plan does not mention clearing `_appliedTo`. After logout, stale flags persist.
Currently harmless (empty `_cache` means `has()` returns false, so `isApplied` is
never reached), but a hygiene issue. **Fix**: add `this._appliedTo = {};` to the
`clear()` method body.

### Change 4 — Multiple Promise Resolves

`evictOldest` resolves its promise from: `cursorReq.onsuccess` (when done),
`cursorReq.onerror`, `countReq.onerror`, AND `tx.oncomplete`/`tx.onerror`. This
works (Promise ignores subsequent resolves) but is slightly redundant. A cleaner
implementation would resolve only from `tx.oncomplete` (which fires after all
cursor work is done) and `tx.onerror`, removing the explicit `resolve()` calls
from the cursor callbacks. However, the current approach is functional and
best-effort semantics make this acceptable.

### Change 2 — `updateSection`/`updateMessage` Can Create Entries

These methods use `this._cache[convId] || (this._cache[convId] = {...})` which can
create new entries without going through `setFromList`/`set`. The `_touch` call
handles eviction correctly for these (entries without a prior `_lastUsed` timestamp
default to `0`, making them the oldest candidates for eviction). No fix needed.

### No Issues Found With

- Delete/conversation-history/doubt logic: none of the 5 changes touch message
  deletion, doubt creation, or conversation history traversal code paths.
- UI rendering correctness: snapshot-restore path is explicitly handled in Changes
  3 and 5 with proper flag clearing.
- Page-load message render: the `messages.forEach` loop and card construction are
  untouched by Changes 2-4; Change 1 only removes binds from the loop (delegation
  replaces them); Change 5 only affects a post-render debounced call.

---

## Implementation Order (Suggested)

Each change is independent. This order minimizes file-context switching and
front-loads the lowest-risk, highest-clarity changes:

1. **Change 3** — `cleanupMessageObservers()` in snapshot-restore path. One line.
   Lowest risk. Do this first as a confidence-builder.
2. **Change 2** — `ConversationUIState` LRU + logout clear. Self-contained in
   `common.js` (two spots). No cross-file coordination.
3. **Change 5** — Skip redundant `applyConversationUIState`. Depends on the
   `ConversationUIState` object shape from Change 2 (it adds methods to the same
   object), so do it after Change 2. Touches `common.js` + `common-chat.js`.
   **Note**: ensure `clear()` also resets `_appliedTo = {}` (see review notes).
4. **Change 4** — `RenderedStateManager` IDB LRU. Self-contained in
   `rendered-state-manager.js`. Independent of the others.
5. **Change 1** — Delegated focus handlers. Most code, touches `common-chat.js`
   only. Do last so the simpler changes are committed and reviewable first.
   **Highest render-speed impact** — if render time is the priority, consider
   implementing this earlier despite its larger scope.

## General Notes for the Implementer

- **No comments unless asked**: the codebase convention (see `AGENTS.md`) is to
  avoid adding comments. The code snippets in this doc include comments for
  clarity, but when implementing, keep only comments that explain *why* a
  non-obvious choice was made (e.g., the LRU `_touch` rationale). Remove the
  rest. Existing comments in the touched files are a good style guide.
- **Test after each change**: load a long conversation (40+ messages), switch
  between 3-4 conversations, edit/delete/move a message, log out and back in.
  The full flow is covered in each change's "Verification" section.
- **Do not combine changes in one commit**: commit each change separately with a
  message like `perf(ui): add LRU eviction to ConversationUIState cache`.
- **If something is ambiguous**: the `event_handler_audit_2026.md` doc in the
  same directory is the authoritative reference for the prior round of fixes and
  explains the architecture of the delegated-handler pattern, the snapshot-restore
  fast path, and the `ConversationUIState` cache. Read its "Key Invariants
  Preserved" section before starting.

## Key Invariants to Preserve

- **Message-index stability**: none of these changes touch `message-index`
  assignment or `reindexMessageCards`. Delete/move/fork workflows are unaffected.
- **Snapshot-restore correctness**: Change 3 adds a cleanup call; Change 5 ensures
  the snapshot-restore path still applies UI state (by clearing the applied flag
  first). Neither breaks the fast path.
- **Dropdown close-on-outside-click**: unaffected (fixed in the prior audit; the
  scoped `newMessageElements` dropdown init at `common-chat.js:2931-2934` stays).
- **MathJax/mermaid deferral**: unaffected (these changes are in the
  post-load/cache layers, not the render-async layers).
- **Logout cache clearing**: Change 2 adds `ConversationUIState.clear()` to
  `clearSwCaches`, extending the existing logout cleanup without changing its
  contract.

## Related Documentation

- `documentation/features/rendering_performance/event_handler_audit_2026.md` —
  prior audit (H1–H6, M1–M8, L1–L2). Read first.
- `documentation/features/rendering_performance/README.md` — MathJax priority and
  deferred-render optimizations.
- `interface/rendered-state-manager.js` — full source for the snapshot store
  (345 lines, well-commented).

---

## Implementation Notes (Post-Implementation)

All five changes were implemented. Deviations from the original plan and
additional improvements are noted below.

### Change 1 — Delegated Focus Handlers (DONE)

**Files modified**: `interface/common-chat.js`

- Module-level state vars (`_messageFocusTimer`, `_currentFocusedMessageId`) added
  near existing `_scrollToBottomInitDone` / `_chatViewResizeObserver` at ~line 3660.
- Three helper functions added at module scope: `_focusEventShouldBeIgnored`,
  `_getMessageIdFromCard`, `handleMessageFocus`.
- Single delegated handler registered in `$(document).ready` at end of file with
  `.messageCardFocus` namespace on all three event groups.
- Removed from `renderMessages`: the 3 per-card `.on(...)` blocks, the nested
  `handleMessageFocus` definition, and the `focusTimer`/`currentFocusedMessageId`
  closure vars.
- `selectstart mouseup` handler captures `e.currentTarget` before the `setTimeout`
  to avoid stale event reference edge cases.
- **Review fix**: Added `data-live-stream` / `data-live-stream-ended` guard to all
  three delegated handlers. Without this, the delegated handlers would double-fire
  alongside the direct handlers in `setupStreamingCardEventHandlers` inside
  `renderStreamingResponse`. The guard ensures the delegated handlers only process
  non-streaming (history-rendered) cards; the streaming card keeps its own direct
  handlers which have access to the local `messageId` parameter before the DOM
  attribute may be stamped.

### Change 2 — ConversationUIState LRU Eviction + Logout Clear (DONE)

**Files modified**: `interface/common.js`

- `MAX_ENTRIES: 30` — sized for 20-30 active conversations. Each entry holds
  section_details + message_show_hide maps (lightweight JSON, a few KB each for
  a 20-turn conversation).
- `_lastUsed` map + `_touch()` eviction on every read/write.
- `clear()` method added — empties `_cache`, `_lastUsed`, AND `_appliedTo` (the
  Change 5 flag map). Called from `clearSwCaches()` on logout.
- `get()` changed from a simple property lookup to a guarded function that returns
  `undefined` for missing keys and calls `_touch()` on hits.

### Change 3 — cleanupMessageObservers in Snapshot-Restore Path (DONE)

**Files modified**: `interface/common-chat.js`

- Single `try { cleanupMessageObservers(); } catch (_e) {}` added at line ~850,
  after `ConversationUIState.setFromList` and before `var keepSnapshot`.
- Idempotent with the call inside `renderMessages` (which still fires on the
  re-render branch; harmless no-op on an empty array).

### Change 4 — RenderedStateManager IndexedDB LRU Eviction (DONE)

**Files modified**: `interface/rendered-state-manager.js`

- `MAX_SNAPSHOTS = 30` — sized for 20-30 conversations. Each snapshot can be up to
  4MB (MAX_HTML_CHARS). 30 × 4MB = ~120MB worst case, well within typical IDB quotas.
- `evictOldest(db)` function added after `withStore`. Uses `store.count()` +
  `savedAt` index cursor ascending to delete oldest entries. Resolves only from
  `tx.oncomplete`/`tx.onerror` (cleaner than the plan's multiple-resolve approach).
- `saveNow`'s `write()` chains `.then(() => evictOldest(db))` after the
  `store.put(record)` transaction.
- `RenderedStateManager.clearAll()` already existed and is called on logout from
  `clearSwCaches()` — this deletes ALL snapshots from IndexedDB, so nothing
  persists post-logout.

### Change 5 — Skip Redundant applyConversationUIState (DONE)

**Files modified**: `interface/common.js`, `interface/common-chat.js`

- Added `_appliedTo` map + `markApplied()`, `isApplied()`, `clearApplied()` to
  `ConversationUIState`.
- **Improvement over plan**: `_appliedTo` is also cleared in `clear()` (the logout
  method). The original plan omitted this — a hygiene gap identified during review.
- `markApplied(_uiConvId)` called right after the synchronous
  `applyConversationUIState(...)` in `renderInnerContentAsMarkdown`.
- `fetchConversationUIState` cache-hit branch skips the DOM walk when
  `isApplied(conversation_id)` is true.
- `clearApplied(conversationId)` called at start of `renderMessages` and in the
  snapshot-restore `else` branch (before `fetchConversationUIState`).

### LRU Sizing Rationale

Both caches use `MAX = 30`:
- Supports 20-30 conversations actively cached in a single session (comfortably
  covers the "at least 10-20 conversations with 20 turns each" requirement).
- `ConversationUIState`: ~2-5 KB per conversation (20 messages × small JSON).
  30 entries ≈ 60-150 KB. Negligible.
- `RenderedStateManager`: up to 4MB per snapshot. 30 entries ≈ 120 MB worst case.
  Typical conversations are much smaller (200-800 KB).
- On logout: `clearSwCaches()` calls both `ConversationUIState.clear()` (in-memory)
  and `RenderedStateManager.clearAll()` (IndexedDB). Nothing persists post-logout.
