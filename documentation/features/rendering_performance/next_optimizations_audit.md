# UI Performance & UX Optimization Audit — Next Steps (2026)

## Context

This audit follows the completed event-handler audit (`event_handler_audit_2026.md`)
and memory/rendering optimizations (`ui_memory_rendering_optimizations_plan.md`).
It surveys the entire UI codebase for remaining performance bottlenecks across:

- Page load sequence and asset loading
- Conversation history rendering (`renderMessages` loop)
- Per-card initialization (`initialiseVoteBank`)
- Markdown rendering pipeline (`renderInnerContentAsMarkdown`)
- Sidebar/workspace management
- Streaming response handling
- Modal and manager modules

Findings are grouped by area, prioritized by impact. Each item includes enough
detail for a junior developer to implement it safely.

---

## TIER 1 — Highest Impact (Page Load + History Render)

### 1.1 `initialiseVoteBank` Is Massively Wasteful (622 lines, ~1560 ops saved)

**File:** `common.js:1554-2176`
**Fires:** Once per card on history load (40x for a typical conversation)
**When it runs:** Called from `renderMessages` at `common-chat.js:2751` (user cards)
and `:2757` (assistant cards), and from the snapshot-restore loop at `:880-886`.

#### What it does per call

Per-call cost:
- Creates **18-20 DOM elements** (6 ghost buttons never appended to DOM + 12 dropdown items)
- Binds **18-20 event handlers** (6 on ghost buttons, 12 on dropdown items)
- Runs `text.split(/\s+/).filter(Boolean).length` regex word-count on full message text
- 4 immediate `.find()` DOM queries per card
- 24 inline `.css()` property writes (6 properties × 4 TTS buttons)

**Critical waste — ghost buttons:** In the **dropdown path** (always taken for
modern cards because `.vote-dropdown-menu` exists in the card template at
`common-chat.js:2700`), 6 buttons (`copyBtn`, `editBtn`, `ttsBtn`, `shortTtsBtn`,
`podcastTtsBtn`, `shortPodcastTtsBtn`) are created at lines 1555-1685 with full
inline styles and click handlers — but **never appended to the DOM**. They exist
only as click-proxy targets. For example, `editItem.click()` at line 1942 just
calls `editBtn.click()`. The ghost buttons serve no purpose except being proxies.

**For 40 cards:** ~720-800 elements, ~720-800 handlers, ~160 DOM queries. Of these,
240 elements and 240 handlers are pure waste (ghost buttons).

#### Fixes (in priority order)

**Fix 1A — Defer dropdown population to first open (biggest single win)**

The entire `voteDropdownMenu` content (lines 1902-2153) — 12 dropdown items, 12
click handlers, the word-count regex — is only visible when the user clicks the
triple-dot button on a card. The user will click at most 1-2 cards per session,
but every card pays the cost upfront.

**How:** Instead of populating the dropdown eagerly at render time, listen for
Bootstrap's `show.bs.dropdown` event on the dropdown toggle and build the menu
contents on first open.

```javascript
// At the end of initialiseVoteBank, instead of the eager population block:
cardElem.find('.vote-menu-toggle').one('show.bs.dropdown', function() {
    populateVoteDropdown(cardElem, text, contentId, activeDocId, disable_voting);
});
```

Move the entire block from line 1902 to 2153 into a new function
`populateVoteDropdown(...)`. The `.one()` ensures it runs exactly once per card,
on first open. Subsequent opens reuse the already-built menu.

**Saves:** 480 element creates + 480 handler binds + 40 regex word-counts on load.

**Risks:**
- The dropdown must open without visible delay. Building ~12 elements and binding
  ~12 handlers is fast (<1ms) so the user won't notice.
- The `text` parameter captured in the closure at render time must still be valid
  at dropdown-open time. Since `text` is a string primitive (immutable), the
  closure is safe.
- The `.vote-menu-toggle` selector must match the actual toggle element in the
  card template. Verify by checking the HTML at `common-chat.js:2636-2675` for
  the `data-toggle="dropdown"` element class.
- Test: open a dropdown on the first card, verify all items appear (TTS, edit,
  copy, TOC, fullscreen, etc.). Then open a second card's dropdown.

**Fix 1B — Eliminate ghost buttons**

Inline the 6 ghost button handlers directly into their dropdown-item click
handlers. For example, instead of:

```javascript
// Current (wasteful):
var editBtn = $('<button>').addClass(...);  // ghost — never appended
editBtn.click(function() { ... edit logic ... });    // ghost handler
// ... later:
editItem.click(function() { editBtn.click(); });     // proxy
```

Do:

```javascript
// Fixed:
editItem.click(function() { ... edit logic ... });   // direct
```

This eliminates the creation of `copyBtn`, `editBtn`, `ttsBtn`, `shortTtsBtn`,
`podcastTtsBtn`, `shortPodcastTtsBtn` entirely.

**Risks:** Low. The edit/copy/TTS logic is self-contained in each handler. Just
move the function body, don't change the logic. Test each menu item after the
change. If Fix 1A (lazy dropdown) is done first, Fix 1B happens inside the lazy
builder, so ghost buttons were never created eagerly anyway.

**Fix 1C — Delegate `headerCopyBtn` click**

Line 1890 does `cardElem.find('.copy-btn-header').click(...)` per card. This is
identical to the pattern already fixed in the H-series audit for delete/move
buttons.

**How:** Add a single delegated handler in `$(document).ready`:
```javascript
$(document).on('click', '.copy-btn-header', function() {
    var $card = $(this).closest('.message-card');
    var messageText = $card.find('.chat-card-body .text-elem').text();
    // ... copy logic from current handler
});
```

Remove the per-card `.find('.copy-btn-header').click(...)` from `initialiseVoteBank`.

**Risks:** Very low — same delegation pattern used throughout the codebase.

**Fix 1D — Cache word count**

Move `text.split(/\s+/).filter(Boolean).length` (line 1907) into the lazy
dropdown builder (Fix 1A). Or compute server-side and include as
`message.word_count` in the payload. The word count is only displayed in the
dropdown menu, so it is not needed at render time.

---

### 1.2 Render-Blocking Scripts — Understanding `defer` and What to Do

**File:** `interface/interface.html`

#### The problem

All **62+ `<script>` tags** (33 in `<head>`, 33+ at bottom of `<body>`) have no
`defer` or `async` attribute. **~45 cross-origin CDN requests** must all download
and execute before the browser can paint anything.

#### What `defer` actually does (important — read this)

**`defer` does NOT prevent scripts from loading.** It changes *when* they execute:

| Attribute | Download | Execute | Order |
|-----------|----------|---------|-------|
| (none) | Blocks HTML parsing | Immediately, blocks parsing | Sequential |
| `defer` | Parallel with HTML parsing | After HTML is fully parsed, before `DOMContentLoaded` | **Preserved** (in document order) |
| `async` | Parallel with HTML parsing | As soon as downloaded | **NOT preserved** (race condition) |

With `defer`:
1. The browser sees `<script defer src="jquery.js">` and starts downloading it
   **in parallel** with continuing to parse the HTML.
2. The browser also starts downloading the next `<script defer>` in parallel.
3. **The HTML document renders immediately** — the user sees the page structure
   (sidebar skeleton, chat area, input box) while scripts download.
4. After the HTML is fully parsed, all `defer`red scripts execute **in document
   order** (jQuery first, then Bootstrap, then common.js, etc.).
5. Then `DOMContentLoaded` fires, which triggers all `$(document).ready()`
   handlers.

**Result:** All `$(document).ready()` code works exactly as before. The only
difference is the user sees the page layout ~1-3 seconds sooner.

**`async` is NOT safe here** because it does not preserve execution order. If
Bootstrap finishes downloading before jQuery, it would execute first and crash.
Always use `defer`, never `async`, for interdependent scripts.

#### Which scripts CAN be deferred safely

**Safe to defer (no inline callers):**
- `uuid` (line 15)
- `PDF.js` (line 22) — loaded from mozilla CDN
- `drawio-renderer` (line 33)
- `Reveal.js` + 4 plugins (lines 39-43) — only used for slide presentations
- `DataTables` (line 173) — only used for table rendering
- `jQuery UI` (line 175)
- `Popper.js` (line 5025) — **REDUNDANT**, already in Bootstrap bundle. Remove entirely.
- `bootstrap-toggle` (line 5028)
- All 33 local JS files (lines 5029-5075) — they all use `$(document).ready()`

**Cannot just add `defer` without moving inline code:**
- `highlight.js` (line 14) — line 23 calls `hljs.initHighlightingOnLoad()` inline
- `mermaid` (line 25) — lines 26-30 call `mermaid.initialize()` inline
- `CodeMirror` core + addons (lines 46-66) — line 72-162 defines a factory using `CodeMirror`
- `katex` (line 9) — `marked-katex-extension` (line 11) needs it at load time
- `jQuery` (line 18) — `Bootstrap` (line 180) and `bootstrap-select` (line 181) need it
- `marked` (line 16) — `marked-katex-extension` (line 11) configures it at load time
- `Bootstrap` (line 180) — `bootstrap-select` (line 181) extends it immediately

#### Step-by-step implementation plan

**Phase 1 — Move inline initialization calls (required first)**

Before adding `defer` to any script, move these inline blocks into the deferred
execution path. Inline `<script>` blocks (no `src` attribute) cannot have `defer`
— they execute immediately during HTML parsing. So if the library they depend on
is deferred, the inline call will crash with a ReferenceError.

1. **Line 23:** `hljs.initHighlightingOnLoad();` — This is a cheap initialization
   call (~microseconds). It registers a `DOMContentLoaded` listener that will
   later scan the page for `<pre><code>` blocks and highlight them. The call
   itself is fast — but the scan at DOMContentLoaded finds nothing useful because
   no code blocks exist in the HTML at that point (they are injected later by
   `renderMessages`). Per-card highlighting already runs inside
   `renderInnerContentAsMarkdown`.

   **If deferring hljs:** Move this call into a `$(document).ready()` block in
   one of the local JS files (e.g., `chat.js:chat_interface_readiness`), or
   remove it entirely since the DOMContentLoaded scan does nothing useful.
   **If NOT deferring hljs:** Leave it as-is — it's harmless.

2. **Lines 26-30:** `mermaid.initialize({startOnLoad: true});` — Configures
   mermaid. Must run after mermaid loads. Move into a `$(document).ready()` block
   if mermaid is deferred, ensuring mermaid has executed before `.initialize()`.
   Alternatively, leave mermaid as non-deferred (it's only one script).

3. **Lines 72-162:** `window.CodeMirror5` factory — This only defines a function
   (it does not call `CodeMirror.fromTextArea` at definition time). It references
   `CodeMirror` in the function body, not in the outer scope. As long as
   CodeMirror is loaded before the factory is *called* (not *defined*), this is
   safe. With `defer` preserving order, CodeMirror (line 46) executes before the
   inline block (line 72). **However**, inline scripts cannot have `defer`, so if
   this block executes during parsing and CodeMirror is deferred... it only
   defines a function, so `CodeMirror` is not accessed at definition time. The
   reference is resolved later when the factory is called, by which time
   CodeMirror has loaded. **No change needed** — but verify by testing code
   editor functionality after adding defer.

4. **Line 11:** `marked-katex-extension` — This UMD module registers itself with
   `marked` at load time. Both `katex` (line 9) and `marked` (line 16) must load
   before it. With `defer` preserving order, this works. No change needed.

5. **Lines 5168-5191:** `text/x-mathjax-config` block — **This is fine where it
   is.** `<script type="text/x-mathjax-config">` is NOT regular JavaScript — the
   browser does not execute it. MathJax 2.x scans for these blocks during its
   own internal async startup (via `document.getElementsByTagName('script')`).
   By the time MathJax's deferred startup fires, the entire HTML body has been
   parsed and this block is present in the DOM. MathJax `eval()`s its content
   and applies the config. The current placement after the MathJax script is
   the standard pattern for MathJax 2.x. **No change needed.**

**Phase 2 — Add `defer` to all external scripts in `<head>`**

After Phase 1 is done, add `defer` to every `<script>` tag in `<head>` that has
a `src` attribute:

```html
<!-- Before: -->
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>

<!-- After: -->
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
```

Apply to all ~33 scripts in `<head>`. The `defer` attribute preserves execution
order, so dependency chains (jQuery → Bootstrap → bootstrap-select) are safe.

**Phase 3 — Add `defer` to body scripts**

The 33+ scripts at the bottom of `<body>` are already after the HTML, so
deferring them has less impact. But adding `defer` allows even faster parallel
downloads:

```html
<script defer src="interface/common.js"></script>
<script defer src="interface/common-chat.js"></script>
<!-- etc. -->
```

**Phase 4 (optional, higher risk) — Lazy-load feature libraries**

For libraries used only for specific features, load them dynamically on first use:

| Library | When needed | Trigger |
|---------|------------|---------|
| Reveal.js (4 files) | Slide presentations | User views a message with slides |
| CodeMirror (14 files) + EasyMDE | Code editing, markdown editing | User opens editor |
| `drawio-renderer` | Drawio diagrams | Message contains drawio content |
| `DataTables` | Table rendering | Message contains a formatted table |
| `PDF.js` | PDF viewer | User opens PDF tab |

**How:** Replace the `<script>` tag with a dynamic loader:
```javascript
function loadRevealJs() {
    if (window.Reveal) return Promise.resolve();
    return Promise.all([
        loadScript('https://cdnjs.cloudflare.com/.../reveal.min.js'),
        loadScript('https://cdnjs.cloudflare.com/.../notes.min.js'),
        // ...
    ]);
}
```

**Risk:** Medium. Requires finding all call sites for each library and wrapping
them in `loadX().then(() => { ... })`. Test each feature thoroughly.

#### Verification for `defer` changes

1. Open DevTools Network tab. Verify all scripts still load (status 200).
2. Check the "Waterfall" column — scripts should show parallel downloads instead
   of sequential.
3. Open Console — no `ReferenceError` or `undefined is not a function` errors.
4. Test: load a conversation, send a message, open dropdown menu, render math,
   render mermaid diagrams, open code editor, toggle dark mode, open file browser.
5. Check `DOMContentLoaded` timing in Performance tab — should be earlier.

#### Known issue to fix simultaneously

**Redundant `Popper.js` at line 5025:** `bootstrap.bundle.min.js` (line 180)
already includes Popper.js. The separate load at line 5025 is wasteful and could
cause version conflicts. Remove it.

**Duplicate `hljs.initHighlightingOnLoad()`:** Called at `interface.html:23` AND
`interface.js:374`. Both register a DOMContentLoaded listener to scan for
`<pre><code>` blocks, but no code blocks exist in the static HTML at that point
(they're injected later by `renderMessages`). Both scans find nothing. Per-card
highlighting already runs inside `renderInnerContentAsMarkdown`. Remove the
`interface.js:374` duplicate. The `interface.html:23` one can stay (it's harmless
and costs ~microseconds) unless hljs is being deferred.

---

### 1.3 Sidebar Full Rebuild on Every Tab Switch / CRUD Operation

**File:** `workspace-manager.js:393-1209`, `common-chat.js:3217-3259`

#### The problem

Every tab switch (clicking assistant/search/finchat tabs) fires
`loadConversationsWithWorkspaces` which:
- Makes **2 AJAX calls** (`GET /list_workspaces/` + `GET /list_conversation_by_user/`)
- **Destroys jsTree entirely** (`jstree('destroy')` at line 1152) and recreates it
- Empties and rebuilds **5 sidebar sections** (Most Accessed, Recent, Pinned,
  Archived, Time View) — each calls `container.empty()` then per-item `.append()`
- ~7 DOM mutations per conversation × N conversations × number of sections visible

Also runs after every CRUD operation: rename (line 3138), pin, color change,
move, create, delete. A simple rename (changing one text label) triggers 2 network
requests + full sidebar destroy/rebuild.

#### Fixes

**Fix 1.3A — Cache conversation list with TTL (highest impact, lowest risk)**

Add a module-level cache inside `WorkspaceManager`:

```javascript
var _conversationsCache = null;
var _workspacesCache = null;
var _cacheTimestamp = 0;
var CACHE_TTL = 30000; // 30 seconds

function loadConversationsWithWorkspaces(forceRefresh) {
    var now = Date.now();
    if (!forceRefresh && _conversationsCache && (now - _cacheTimestamp) < CACHE_TTL) {
        _processAndRenderData(_conversationsCache, _workspacesCache);
        return;
    }
    // ... existing AJAX calls ...
    // In success callbacks:
    _conversationsCache = conversations;
    _workspacesCache = workspaces;
    _cacheTimestamp = Date.now();
}
```

After CRUD operations that change data, call with `forceRefresh = true`.

**Risks:**
- If another user renames a conversation in a shared workspace, the sidebar won't
  update for 30 seconds. This is acceptable for a single-user app.
- The cache should be cleared on logout (add to `clearSwCaches`).

**Fix 1.3B — Patch individual DOM nodes on simple mutations**

For rename: instead of full rebuild, find the conversation element by
`data-conversation-id` and update its `.text()`:

```javascript
function patchConversationTitle(convId, newTitle) {
    $('[data-conversation-id="' + convId + '"] .conversation-title').text(newTitle);
    // Also update the cached data:
    if (_conversationsCache) {
        var conv = _conversationsCache.find(c => c.id === convId);
        if (conv) conv.title = newTitle;
    }
}
```

For pin/unpin, color change: same pattern — find the element, toggle class/style.

**Risks:** Low for rename/color. Medium for pin (the conversation may need to
appear in/disappear from the Pinned section, which is a structural change).

**Fix 1.3C — Use jsTree `refresh()` instead of destroy/recreate**

Replace the destroy/recreate at line 1152-1209 with:

```javascript
var tree = $.jstree.reference('#workspaces-container');
if (tree) {
    tree.settings.core.data = newTreeData;
    tree.refresh();
} else {
    $('#workspaces-container').jstree({ ... });
}
```

**Risks:** Medium. jsTree's `refresh()` re-reads `settings.core.data` and
rebuilds the DOM. It re-fires `ready.jstree` and `redraw.jstree` events,
which trigger `addTripleDotButtons`. Test that the triple-dot buttons still
appear correctly after refresh.

**Fix 1.3D — Build sidebar HTML as string**

In `renderRecentConversations` (line 538+), `renderMostAccessed` (line 447+),
etc., replace the per-item `.append()` pattern:

```javascript
// Current (slow):
conversations.forEach(function(conv) {
    var item = $('<div>').attr('data-conversation-id', conv.id).append(...);
    container.append(item);  // triggers reflow each time
});

// Fixed (fast):
var html = conversations.map(function(conv) {
    return '<div data-conversation-id="' + escapeHtml(conv.id) + '">' + ... + '</div>';
}).join('');
container.html(html);  // single DOM write
```

**Risks:** Low. Use `escapeHtml()` (the canonical function in `common.js`) for
any user-provided strings (conversation titles, workspace names) to prevent XSS.

---

### 1.4 `renderInnerContentAsMarkdown` — 12+ Regex Passes Per Render

**File:** `common.js:4934-4995`
**Fires:** Per card on history load (40x) AND per streaming chunk (~200x per response)

#### The problem

Sequential regex operations run before marked.js even starts:
1. `html.includes('</answer>')` — line 4934
2. `html.replace(/<answer>/g, ...)` + `html.replace(/<\/answer>/g, ...)` — 2 calls
3. `answer_diff` open/close regex matches — 2 calls
4. Conditional: 2-3 more `replace` calls for `answer_diff` — when present
5. `answer_tldr` `.test()` — 2 calls
6. Conditional `answer_tldr` replaces — 2 calls  
7. `answer_visual` `.test()` — 2 calls + `indexOf` — 1 call
8. Conditional `answer_visual` replaces — 2 calls
9. `horizontalRuleRegex.test(html)` — 1 call

That's **12-15 regex passes** over potentially large strings. During streaming,
this runs every ~80-200 characters, accumulating to thousands of regex passes per
AI response.

#### Fixes

**Fix 1.4A — Gate expensive branches with fast `indexOf` checks**

`answer_diff`, `answer_tldr`, `answer_visual` are rare tags (used in <5% of
messages). Use `indexOf` before running any regex:

```javascript
// Current (wasteful):
if (/<\s*answer_tldr\s*>/i.test(html)) { ... }
if (/<\s*\/\s*answer_tldr\s*>/i.test(html)) { ... }

// Fixed:
if (html.indexOf('answer_tldr') !== -1) {
    if (/<\s*answer_tldr\s*>/i.test(html)) { ... }
    if (/<\s*\/\s*answer_tldr\s*>/i.test(html)) { ... }
}
```

`indexOf` is 10-100x faster than regex `.test()` because it's a simple substring
search with no regex compilation. For the 95% of messages without these tags, the
entire branch is skipped.

**Risks:** None. `indexOf` is a strict superset check (if the regex would match,
`indexOf` for the tag name will always find it — the tag name string is always
present inside the regex match).

**Fix 1.4B — Combine `<answer>` strip into one call**

```javascript
// Current: two passes
html = html.replace(/<answer>/g, '');
html = html.replace(/<\/answer>/g, '');

// Fixed: one pass
html = html.replace(/<\/?answer>/g, '');
```

**Risks:** None. Functionally identical.

**Fix 1.4C — Cache tag presence during streaming**

For streaming, once the accumulated text passes ~200 chars with no `answer_diff`
found, it is extremely unlikely to appear later (the tag is always near the top
of the response if present). Set a flag on the card element:

```javascript
if (!card.data('has-answer-diff')) {
    // Skip answer_diff regex entirely for subsequent chunks
}
```

**Risks:** Low. The flag is per-card. If the tag appears after the first 200
chars (extremely rare), it would be missed until the next full render. To be
safe, reset the flag every ~50 chunks.

---

### 1.5 `applyConversationUIState` Per-Card Iterates ALL Message IDs

**File:** `common.js:4625-4672`
**Fires:** 40x per history load (once per card from `renderInnerContentAsMarkdown`)

#### The problem

When called per-card (from `renderInnerContentAsMarkdown` at line 5630), the
`Object.keys(message_show_hide).forEach` loop iterates ALL message IDs (40+),
doing `$container.find('.card-header[message-id="X"]')` for each. Since the
container is scoped to one card, 39 of 40 queries return empty results.

Total: 39 × 40 = **1560 failed DOM queries** for a 40-card load.

#### Fix

When `$container` is a single card (detected by checking if it has
`.message-card` class), extract the card's own `message-id` and do a single O(1)
map lookup:

```javascript
function applyConversationUIState(sectionDetails, messageShowHide, container) {
    var $container = $(container);
    
    // Section collapse (existing code, leave as-is for now)
    if (sectionDetails) { ... }
    
    // Message show/hide — optimized path for single-card scope
    if (messageShowHide) {
        if ($container.hasClass('message-card')) {
            // Per-card path: O(1) lookup instead of O(N) loop
            var $header = $container.find('.card-header[message-id]').first();
            var myId = $header.length ? $header.attr('message-id') : null;
            if (myId && messageShowHide[myId]) {
                applyShowHideToCard($container, messageShowHide[myId]);
            }
        } else {
            // Full-view path (existing O(N) loop — fine when scoped to #chatView)
            Object.keys(messageShowHide).forEach(function(messageId) {
                var $header = $container.find('.card-header[message-id="' + messageId + '"]');
                // ... existing show/hide logic
            });
        }
    }
}
```

**Risks:** Low. The per-card path only fires when the container IS a
`.message-card` (set at `renderInnerContentAsMarkdown:5626`). The full-view path
is unchanged.

**Verification:** Load a conversation with hidden messages (show_hide != 'show').
Verify they still render as hidden/collapsed.

---

## TIER 2 — Medium Impact

### 2.1 `$('#settings-render-close-to-source').is(':checked')` Inside Loop

**File:** `common-chat.js:2817`
**Fires:** Per card in `renderMessages` forEach loop (40x)

Reads a settings checkbox on every iteration. The result is constant across the
entire render — the checkbox doesn't change mid-loop.

**Fix:** Hoist above the loop, next to `initialCardCount`:
```javascript
var initialCardCount = $('#chatView').find('.message-card').length;
var renderCloseToSource = $('#settings-render-close-to-source').is(':checked');
```

Then use `renderCloseToSource` inside the loop instead of the per-iteration query.

**Risks:** None. Pure constant hoisting.

### 2.2 `renderCloseToSource` O(N×M) Card Scan Inside Loop

**File:** `common-chat.js:2824-2832`
**Fires:** Per card when `renderCloseToSource` setting is enabled

When `history_message_ids.length > 0 && renderCloseToSource`, the code:
```javascript
var cards = $('#chatView').find('.card.message-card');  // O(N) DOM query
for (var i = 0; i < cards.length; i++) {
    var cardMessageId = $(card).find('.history-message-checkbox').attr('message-id');
    if (history_message_ids.includes(cardMessageId)) { ... }  // O(M) array scan
}
```

This is O(N × M) per message. For 40 messages: 40 × 40 = 1600 iterations.

**Fix:** Hoist the `.find()` above the loop. Convert `history_message_ids` to a
`Set` for O(1) lookup:
```javascript
var historyIdSet = new Set(history_message_ids);
var existingCards = renderCloseToSource ? $('#chatView').find('.card.message-card') : null;
```

**Risks:** None. `Set.has()` is functionally identical to `Array.includes()`.

### 2.3 No DocumentFragment Batching in `renderMessages`

**File:** `common-chat.js:2632-2847`

Each card is built from 4+ jQuery objects, then appended to `#chatView` inside
the loop. Each `$('#chatView').append(messageElement)` triggers a layout recalc.

**Fix:** Collect all cards in a `DocumentFragment`, then do one append:
```javascript
var fragment = document.createDocumentFragment();
messages.forEach(function(message, originalIndex) {
    // ... build messageElement ...
    fragment.appendChild(messageElement[0]);
    newMessageElements.push(messageElement);
});
$('#chatView').append(fragment);
```

**Risks:** Medium. The `renderCloseToSource` path (line 2824) inserts cards at
specific positions using `.after()`, not at the end. This path would need special
handling. If `renderCloseToSource` is not enabled (the common case), batching is
straightforward. Gate the optimization:
```javascript
if (renderCloseToSource && history_message_ids.length > 0) {
    // Use per-card positional insert (existing behavior)
} else {
    fragment.appendChild(messageElement[0]);
}
```

### 2.4 Streaming `card.find('.status-div')` Per Chunk

**File:** `common-chat.js:1604`
**Fires:** Hundreds of times per AI response (~200-400 chunks per response)

Re-queries `.status-div` on every streaming chunk. Also calls `.show()` on an
already-visible element every chunk (sets `display: block` redundantly).

**Fix:** Cache `statusDiv` at card creation time (where the card is first built,
around line 1498). Store as a closure variable in the streaming handler scope.
Guard `.show()` behind an `isVisible` flag.

**Risks:** Very low. The status div doesn't move or get replaced during streaming.

### 2.5 `applyModelResponseTabs` DOM Query in Gate

**File:** `common.js:5501-5512`
**Fires:** Every streaming chunk when the 4 string checks are false

The tab-marker gate's last condition is a DOM query:
```javascript
|| $(elem_to_render_in).find('.model-tabs-container').length > 0;
```
For plain messages (95%+ of cases), the 4 string checks are false AND this DOM
query finds nothing — but the query still runs.

**Fix:** Set `data-has-tabs="1"` on the element when a `.model-tabs-container` is
first created (inside `applyModelResponseTabs`). Check the attribute instead:
```javascript
|| elem_to_render_in.getAttribute('data-has-tabs') === '1';
```

**Risks:** Very low. The attribute is only checked, never cleared (tabs don't
disappear once created).

### 2.6 Doubt Manager O(n^2) Streaming

**File:** `doubt-manager.js:795-804`

On every stream chunk, the entire accumulated text is re-parsed with
`marked.parse(accumulated)` and the result replaces `cardBody.html(rendered)`.
For a 2000-word doubt answer arriving in 200 chunks, that's 200 full markdown
parses of growing strings (200 + 400 + 600 + ... + 40000 characters = O(n^2)).

**Fix:** Throttle the `.html()` update to every 100-200ms:
```javascript
if (!_doubtRenderPending) {
    _doubtRenderPending = true;
    requestAnimationFrame(function() {
        cardBody.html(marked.parse(accumulated));
        _doubtRenderPending = false;
    });
}
```

**Risks:** Low. The user sees updates at ~60fps instead of per-chunk. The final
complete text is always rendered because the `done` path sets `.html()` directly.

### 2.7 `new Date()` Object Churn in Sort Comparator

**File:** `workspace-manager.js:394, 823`

Creates 2 `Date` objects per comparison during conversation sort. ~1400 `Date`
allocations for 100 conversations.

**Fix:** Pre-compute timestamps:
```javascript
conversations.forEach(function(c) {
    c._ts = new Date(c.last_updated).getTime();
});
conversations.sort(function(a, b) { return b._ts - a._ts; });
```

**Risks:** None. `_ts` is a temporary property on existing objects.

---

## TIER 3 — Lower Impact / UX Improvements

### 3.1 Dark Mode CSS Always Loaded (809 Lines)

**File:** `interface.html:187` — `dark-mode.css`

Always loaded even for light-mode users, adding 809 CSS rules to parse.

**Fix:** Check localStorage preference before loading:
```html
<script>
if (localStorage.getItem('darkMode') === 'true') {
    document.write('<link rel="stylesheet" href="interface/dark-mode.css">');
}
</script>
```

Or better: use CSS custom properties for colors and toggle a single class.

**Risks:** Low, but test the dark mode toggle — it must still work when the user
switches modes during a session (the current toggle may need to dynamically
inject/remove the stylesheet).

### 3.2 `workspace-styles.css` Loaded After Body (FOUC)

**File:** `interface.html:5051`

Sidebar styles load after all body HTML, causing the sidebar to briefly render
unstyled.

**Fix:** Move the `<link>` tag to `<head>`. One-line change.

**Risks:** None.

### 3.3 Hardcoded 1-Second Loader Timeout

**File:** `chat.js:173-175`

The loader overlay (the spinning indicator covering the whole page) hides after
a fixed 1000ms via `setTimeout`, regardless of whether data has actually loaded.
If the network is slow, the user sees an empty UI. If the network is fast, the
user waits unnecessarily.

**Fix:** Replace with an event-based signal:
```javascript
// In chat.js — remove the setTimeout, expose a function:
function hideLoader() {
    $('#loader').fadeOut(300);
}

// In common-chat.js — after renderMessages or snapshot restore completes:
if (typeof hideLoader === 'function') hideLoader();
```

**Risks:** Low. If something goes wrong and `hideLoader` is never called, add a
fallback `setTimeout(hideLoader, 5000)` as a safety net.

### 3.4 Serial Network Requests at Page Load

**File:** `chat.js:624-641`

Four independent network requests fire sequentially:
- `loadModelCatalog()` — GET `/model_catalog`
- `loadCustomPromptsOnInit()` — GET `/get_prompts`
- `showUserName()` — GET `/get_user_info`
- `loadConversationsWithWorkspaces()` — triggered by tab activation

**Fix:** Fire the first three in parallel:
```javascript
$.when(
    loadModelCatalog(),
    loadCustomPromptsOnInit(),
    showUserName()
).then(function() {
    // All complete
});
```

Note: these functions must return the jQuery AJAX promise (they currently may
not — check and add `return $.ajax(...)` if missing).

**Risks:** Low. These are read-only GETs with no ordering dependency.

### 3.5 21 `$(document).ready` Handlers Without Prioritization

Every JS file registers its own `$(document).ready`. All 21 run synchronously
on `DOMContentLoaded` with no priority ordering.

**Fix (incremental):** Wrap non-critical inits in `requestIdleCallback`:
```javascript
// In pkb-manager.js, doubt-manager.js, file-browser-manager.js, etc.:
$(document).ready(function() {
    if (window.requestIdleCallback) {
        requestIdleCallback(function() { PkbManager.init(); });
    } else {
        setTimeout(function() { PkbManager.init(); }, 100);
    }
});
```

This lets the critical path (chat UI, conversation load) finish first.

**Risks:** Low. Features initialized in idle callback take 50-100ms longer to be
ready, but the user is unlikely to click PKB or file browser within the first
100ms of page load.

### 3.6 PKB Manager Direct Binding Per Render

**File:** `pkb-manager.js:708-735`

`bindClaimCardActions` binds 4 click handlers per claim card on every render.
With 30+ claims: 120+ handler bindings per render cycle.

**Fix:** Delegate on the stable container:
```javascript
$container.on('click', '.pkb-edit-claim', function() { ... });
$container.on('click', '.pkb-delete-claim', function() { ... });
```

Bind once when the container is created, not on every render.

**Risks:** Low. Same delegation pattern proven in the H-series audit.

### 3.7 File Browser Path Suggestion Full DOM Walk

**File:** `file-browser-manager.js:800-812`

On every `loadTree` call (directory expansion), iterates ALL `<li>` nodes in the
tree to rebuild path suggestions.

**Fix:** Maintain a JS-side `Set` of paths, updated incrementally as entries are
added/removed. Never re-scan DOM.

**Risks:** Low. Keep the Set in sync with tree changes.

### 3.8 File Browser Address Bar No Debounce

**File:** `file-browser-manager.js:2586`

Fuzzy match against all paths runs on every input event (every keystroke). For
1000+ paths, this causes visible lag.

**Fix:** Debounce with 100-150ms:
```javascript
var _filterTimer;
_$('addressBar').on('input', function() {
    var val = $(this).val().trim();
    clearTimeout(_filterTimer);
    _filterTimer = setTimeout(function() {
        _filterAndShowSuggestions(val);
    }, 120);
});
```

**Risks:** None. User won't perceive 120ms debounce.

### 3.9 Artefacts Diff Renders Line-by-Line `.append()`

**File:** `artefacts-manager.js:720-754`

Each diff line is appended individually. For a 500-line diff, that's 500 DOM
mutations.

**Fix:** Build complete HTML string, single `.html()`:
```javascript
var lines = diff.split('\n');
var html = lines.map(function(line) { return buildDiffLine(line, cls); }).join('');
container.html(html);
```

**Risks:** Low. `buildDiffLine` must return an HTML string instead of a jQuery
element (or call `.prop('outerHTML')` on it). Test diff rendering after change.

---

## Bonus Finding: Redundant Popper.js and hljs Calls

**Redundant Popper.js** (`interface.html:5025`): `bootstrap.bundle.min.js`
(line 180) already includes Popper.js. Loading it again is wasteful and could
cause version conflicts. Remove the line 5025 `<script>` tag.

**Duplicate `hljs.initHighlightingOnLoad()`**: Called at `interface.html:23` AND
`interface.js:374`. Both scan the DOM for `<pre><code>` blocks at DOMContentLoaded.
Since no code blocks exist in the static HTML (they are injected later by
`renderMessages`), both calls register listeners that find nothing. Per-card
highlighting already happens in `renderInnerContentAsMarkdown`. Remove the
duplicate at `interface.js:374`. The one at line 23 can stay (it's harmless) or
be removed too if deferring hljs.

---

## Summary: Top 10 Recommendations by Impact

| # | Area | Optimization | Operations Saved | Risk | Effort | Status |
|---|------|-------------|------------------|------|--------|--------|
| 1 | renderMessages | Defer `initialiseVoteBank` dropdown to first open | 960 creates + 960 handlers eliminated from load | Low | Medium | **DONE** |
| 2 | Page Load | Add `defer` to scripts (Phase 1-3) | Unblocks first paint entirely | Low | Low | **DONE** |
| 3 | Sidebar | Cache conversation list + skip redundant reloads | 2 AJAX + full DOM rebuild per tab switch | Low | Low | **DONE** |
| 4 | renderMessages | Eliminate ghost buttons in `initialiseVoteBank` | 240 creates + 240 handlers | Low | Medium | **DONE** |
| 5 | renderInnerContent | Fast `indexOf` gates on regex branches | 8-10 regex passes saved per streaming chunk | Very Low | Low | **DONE** |
| 6 | applyConvUIState | Per-card: O(1) lookup instead of O(N) loop | 1560 failed DOM queries on 40-card load | Low | Low | **DONE** |
| 7 | Page Load | Lazy-load feature libraries (CM, Reveal, mermaid) | ~600KB off critical path | Medium | High | **DONE** |
| 8 | renderMessages | DocumentFragment batching | 40 individual appends → 1 batch | Low | Medium | **DONE** |
| 9 | Sidebar | jsTree `refresh()` instead of destroy/recreate | Full tree rebuild eliminated | Medium | Medium | **DONE** |
| 10 | Streaming | Cache `statusDiv` reference; throttle doubt streaming | ~200 `.find()` queries per response | Very Low | Low | **DONE** |

---

## Item 2 — Script Defer: Implementation Notes (DONE)

### What was done

**Files modified:** `interface/interface.html`, `interface/common.js`

**Phase 1 — Moved inline initialization calls:**
- Removed `hljs.initHighlightingOnLoad()` inline call (was at line 23)
- Removed `mermaid.initialize({ startOnLoad: true })` inline block (was at lines 26-30)
- Added both to a `$(document).ready()` block at the top of `common.js` (line 3+),
  using `hljs.highlightAll()` (the non-deprecated equivalent) and
  `mermaid.initialize()` respectively, both with `typeof` guards
- This ready handler fires first among all $(document).ready handlers because
  common.js is the first local script loaded

**Phase 2 — Added `defer` to head scripts (25 scripts):**
- highlight.js, uuid, PDF.js, mermaid, drawio-renderer (5 scripts)
- Reveal.js core + 4 plugins (5 scripts)
- CodeMirror core + 8 addons + 6 mode/addon scripts (14 scripts)
- EasyMDE (1 script)
- DataTables, jQuery UI (2 scripts, note: jQuery UI was moved to defer but
  `DataTables` depends on jQuery which is still sync — safe)

**Phase 3 — Added `defer` to body scripts + cleanup:**
- Deferred all 33 local JS files (common.js through desktop-bridge.js)
- Deferred bootstrap-toggle, jsTree CDN scripts
- **Removed redundant Popper.js** (line 5025) — already bundled in bootstrap.bundle

**Kept synchronous (7 scripts):**
- katex (line 9) — marked-katex-extension needs it at load time
- marked-katex-extension (line 11) — registers with marked synchronously
- marked (line 16) — needed by marked-katex-extension
- MathJax (line 17) — complex async startup with internal deferrals
- jQuery (line 18) — needed by inline scripts in body (line 3131+)
- Bootstrap bundle (line 180) — needed by bootstrap-select
- bootstrap-select (line 181) — needed by inline at line 3133

**MathJax config block** (line 5168): Confirmed working as-is. The
`text/x-mathjax-config` type is not executed by the browser — MathJax scans for
it during its async startup, by which time the full DOM is parsed.

**CodeMirror5 inline factory** (lines 72-162): Safe with defer. The factory only
defines `window.CodeMirror5.createEditor` — it references `CodeMirror` inside
the function body, never at definition time. By the time the factory is called,
CodeMirror has loaded.

### Total scripts deferred: ~58 (of ~65)

This means ~58 scripts now download in parallel with HTML parsing instead of
blocking it. The browser can paint the page structure (sidebar skeleton, chat
area, input box) while scripts download. All `$(document).ready()` handlers
continue to work identically because `defer` preserves execution order and all
deferred scripts execute before `DOMContentLoaded`.

### Verification checklist

1. Open DevTools Network tab — verify all scripts load (status 200/304)
2. Check Waterfall — parallel downloads for deferred scripts
3. Console — no `ReferenceError` or `undefined is not a function`
4. Load a conversation with 20+ messages — cards render, dropdowns work
5. Send a message — streaming works, copy/edit/TTS buttons work
6. Open code editor — CodeMirror initializes correctly
7. Render a mermaid diagram — `mermaid.run()` works
8. Render math content — MathJax typesets correctly
9. Toggle dark mode — hljs theme switch works
10. Open file browser, PKB, doubt chat — all modals work
11. Sidebar — workspace tree, recent list render correctly

---

## Group A — "Free Wins" Implementation Notes (DONE)

Items 5, 6, 2.1, 10 — all zero/very-low risk, no dependencies, self-contained edits.

### Item 5: indexOf gates on regex branches

**File:** `interface/common.js` (in `renderInnerContentAsMarkdown`, lines ~4977-5035)

**What:** Wrapped three rare-tag regex blocks (`answer_diff`, `answer_tldr`,
`answer_visual`) with fast `html.indexOf('tag_name') !== -1` gates. When the tag
is absent (95%+ of messages), the entire block is skipped — no `match()`,
`test()`, or `replace()` calls executed.

Also gated the post-marked `ANSWER_VISUAL` comment-to-div replacement (lines
~5458-5465) so the two `.replace()` calls only run when placeholders are present.

**Operations saved per call:** 4 `match()` + 2 `test()` + 2 `test()` = 8 regex
operations skipped for normal messages. During streaming (200-400 chunks per
response), this eliminates **1600-3200 unnecessary regex passes**.

### Item 6: Per-card O(1) lookup in applyConversationUIState

**File:** `interface/common.js` (in `applyConversationUIState`, lines ~4643-4664)

**What:** Added a fast path when `$container` is a single `.message-card`:
extracts the card's `message-id` via one `.find()`, then does a direct property
lookup in the `message_show_hide` map. Only processes the matching entry (or
nothing). The full-view path (when container is `#chatView`) is unchanged.

**Operations saved:** On a 40-card conversation load, when called per-card from
`renderInnerContentAsMarkdown`, eliminates **1560 failed DOM queries** (39 misses
x 40 cards). Each card now does 1 `.find()` + 1 map lookup instead of 40
`.find()` calls.

### Item 2.1: Hoist settings read out of renderMessages loop

**File:** `interface/common-chat.js` (in `renderMessages`, lines ~2615-2821)

**What:** Moved `$('#settings-render-close-to-source').is(':checked')` from inside
the `messages.forEach()` loop to before it. The checkbox value is constant during
a single render pass. Added comment at old location for clarity.

**Operations saved:** 39 redundant DOM queries per 40-message render (N-1 reads
eliminated).

### Item 10a: Cache statusDiv reference during streaming

**File:** `interface/common-chat.js` (streaming reader, lines ~1315-1875)

**What:** Added `_cachedStatusDiv` and `_cachedSpinner` variables alongside
`card`. On first access (line ~1609), caches the jQuery objects. All subsequent
chunks reuse the cache. Stream completion path uses cache with fallback to
`.find()` for safety, then clears cache.

**Operations saved:** ~200-400 `.find('.status-div')` + ~200-400
`.find('.spinner-border')` queries eliminated per response.

### Item 10b: Throttle doubt streaming with requestAnimationFrame

**File:** `interface/doubt-manager.js` (3 streaming hot paths)

**What:** Wrapped `marked.parse()` + `.html()` DOM updates in
`requestAnimationFrame()` callbacks in all three doubt streaming paths:
1. Thread summary streaming (lines ~786-830)
2. Regeneration streaming (lines ~995-1035)
3. Main doubt response streaming (lines ~1467-1478)

Text still accumulates every chunk (no data loss). DOM updates are batched to at
most once per frame (~16ms at 60fps). On stream completion (`done` or
`part.completed`), any pending rAF is cancelled and a final synchronous render
ensures the full accumulated text is displayed.

**Operations saved:** If streaming sends 200 chunks in 2 seconds (100 chunks/s),
and frames run at 60fps, only ~120 `marked.parse()` + `.html()` calls execute
instead of 200. Each `marked.parse()` re-parses the entire accumulated text
(O(n)), so the total parsing work is reduced significantly. The `renderMermaidIn`
call (main doubt path only) is also deferred into the rAF, eliminating per-chunk
mermaid scanning.

### Verification checklist (Group A)

1. Load a 40+ message conversation — no console errors, cards render correctly
2. Open a conversation — verify `applyConversationUIState` doesn't log errors
3. Send a message — streaming spinner appears, text streams smoothly
4. Messages with `answer_diff`/`answer_tldr`/`answer_visual` tags still render
5. Messages WITHOUT those tags render at the same speed (faster due to skipped regex)
6. Open doubt chat — ask a question — streaming text appears smoothly
7. Regenerate a doubt answer — text streams correctly
8. Cancel a doubt stream mid-response — text is not cut off (final render fires)
9. Thread summary in doubt chat — renders correctly

---

## Group B — VoteBank Cleanup: Implementation Notes (DONE)

Items 1 + 4 — done together since ghost buttons lived inside the dropdown
population code.

### Item 4: Eliminate ghost buttons

**File:** `interface/common.js` (in `initialiseVoteBank`, lines ~1572-2129)

**What was removed:**
- 6 ghost buttons (`copyBtn`, `editBtn`, `ttsBtn`, `shortTtsBtn`,
  `podcastTtsBtn`, `shortPodcastTtsBtn`) — created with full CSS + handlers but
  never appended to the DOM in the dropdown path
- 4 ghost button click handlers (`ttsBtn.click(...)`, etc.) that forwarded to
  `handleTTSBtnClick()` — the dropdown items already called it directly

**What replaced them:**
- `handleCopyClick()` inner function — called by `.copy-btn-header` click handler
  and fallback vote-box copy button
- `handleEditClick()` inner function — called by `editItem` dropdown click handler
  and fallback edit button
- `handleTTSBtnClick()` was already an inner function — now called directly from
  dropdown items (unchanged) and fallback TTS buttons
- `handleTTSBtnClick` fallback path (old `else` branch that hid/replaced ghost
  buttons) simplified to replace the `.vote-box` content directly

**Operations saved per 40-card load:** 240 element creates + 240 handler binds
eliminated entirely.

### Item 1: Lazy-populate dropdown on first open

**File:** `interface/common.js` (in `initialiseVoteBank`, lines ~1825-2105)

**What was done:**
- Wrapped the entire dropdown population code (word count, 12 menu items, all
  click handlers, compare item, revert item, read full screen item) in a
  `populateVoteDropdown()` inner function
- Registered via `.one('show.bs.dropdown.lazyVoteBank', ...)` on the `.dropdown`
  parent element — fires once per card on the first time the user opens the
  triple-dot menu
- Building 12 items + handlers is <1ms — imperceptible to the user

**Re-init handling (edit/revert):**
- `initialiseVoteBank` is called again after message edits and reverts (with new
  `text` parameter). On re-init: the dropdown is `.empty()`'d, the old
  `show.bs.dropdown.lazyVoteBank` handler is `.off()`'d, and a fresh `.one()` is
  registered. The `populateVoteDropdown` guard (`children().length > 0`)
  prevents race conditions.

**Revert check simplified:**
- The old `click.revertcheck` handler on the toggle button (bound eagerly, fired
  on second dropdown click) was replaced with a direct AJAX check inside
  `populateVoteDropdown()` — fires immediately on first dropdown open. The
  `data-has-original` fast path still works for in-session edits.

**Operations saved per 40-card load:**
- 480 element creates (12 items x 40 cards) deferred to on-demand
- 480 handler binds deferred
- 40 regex word-count computations deferred
- 40 `.empty()` calls on dropdown menus deferred
- Only the 1-2 cards the user actually opens get populated

### Verification checklist (Group B)

1. Load a 40+ message conversation — no console errors
2. Click triple-dot on a card — dropdown appears with all items (Short TTS, Full
   TTS, Short/Full Podcast, Edit, Edit as Artefact, TOC, Save to Memory, Compare,
   Undo Last Edit, Read Full Screen, word count)
3. Click "Edit Message" — editor opens with correct text
4. Click "Full TTS" — audio player appears, audio plays
5. Click "Copy" header button — text copied to clipboard
6. Edit a message via editor, save — `initialiseVoteBank` re-inits, dropdown works
   on second open
7. Click "Undo Last Edit" on an edited message — reverts correctly
8. Check that dropdown loads fast (<50ms) on first open
9. Verify no ghost button references in console errors

---

## Group C — Sidebar Optimizations: Implementation Notes (DONE)

Items 3 + 9 — both reduce sidebar cost from CRUD operations.

### Item 3: Render-Skip Fingerprint

**File:** `interface/workspace-manager.js`

**Problem:** Every CRUD operation (flag, archive, move, rename, create, delete)
triggers `loadConversationsWithWorkspaces(false)`, which fires 2 AJAX requests and
runs 6 render functions (jsTree + 5 sidebar sections). When CRUD operations fire in
quick succession, or when a fetch returns data identical to what's already rendered,
the DOM is rebuilt unnecessarily.

**Note on original audit:** The audit described "2 AJAX + full DOM rebuild per tab
switch" but investigation showed tab switching does NOT call
`loadConversationsWithWorkspaces`. Tab switches go through `setActiveConversation` →
`highlightActiveConversation` (no AJAX, no sidebar rebuild). The actual cost is from
CRUD operations only.

**What was added:**

**Render-skip fingerprint** in `_processAndRenderData`: Before any DOM work,
builds a lightweight string key from all conversation and workspace fields that
affect rendering (IDs, workspace assignments, flags, archived status, titles,
timestamps, workspace names/colors/parents, `_showArchived` toggle). If the key
matches the last render, the full DOM rebuild (jsTree rebuild + 5 section renders)
is skipped entirely. Callers' `.done()` handlers still fire for post-render
actions like `highlightActiveConversation`.

**Design decision — no in-flight deduplication:** An initial implementation added
in-flight request dedup (piggyback on existing AJAX when called again), but this was
removed because CRUD success handlers need post-mutation data. A piggybacking CRUD
caller would see pre-mutation data from a request that started before the mutation
completed. The render-skip fingerprint provides the safety net: if two fetches
return identical data, only the first triggers a DOM rebuild.

**State variable added** (line 53):
- `_lastSidebarDataKey`: Fingerprint of the last rendered sidebar data

**Operations saved:**
- Render-skip: Prevents full sidebar rebuild (jsTree refresh + 5 section renders)
  when data is unchanged between fetches
- No caller changes required — zero risk to existing code

### Item 9: jsTree `refresh()` Instead of Destroy/Recreate

**File:** `interface/workspace-manager.js` (in `renderTree`, lines ~1185-1220)

**Problem:** Every sidebar update destroyed the jsTree instance entirely
(`container.jstree('destroy')`) and recreated it from scratch. This means:
- Full DOM teardown of the tree (dozens/hundreds of nodes)
- All event bindings destroyed and recreated (8 `.off().on()` calls)
- All plugins re-initialized (types, wholerow, contextmenu, sort)
- Triple-dot buttons re-added via `ready.jstree` event
- `_jsTreeReady` toggled to false, queuing pending highlights

**What was changed:**

The `renderTree` function now checks for an existing jsTree instance via
`$.jstree.reference(container)`. Two paths:

1. **Refresh path** (existing tree): Sets `_jsTreeReady = false` (so
   `highlightActiveConversation` queues to `_pendingHighlight` instead of trying
   to select not-yet-rendered nodes). Updates `settings.core.data` with new tree
   data, then calls `existingTree.refresh()`. A one-shot
   `container.one('refresh.jstree')` handler sets `_jsTreeReady = true` and
   processes pending highlights. Triple-dot buttons are re-added by the existing
   `redraw.jstree` handler (bound during first init, persists through refresh).
   Event bindings from the first init are preserved (not re-bound).

2. **First-init path** (no tree): Original code unchanged — full `container.jstree({...})`
   init with all event bindings.

**Expansion state fix:** `buildJsTreeData` previously hardcoded `state: { opened: false }`
for all workspace nodes, causing all workspaces to collapse on every re-render. Changed
to `state: { opened: !!ws.expanded }` which uses the server-persisted expansion state
(tracked by `open_node.jstree` → `PUT /update_workspace/{id}`). This means:
- User-opened workspaces persist across CRUD sidebar updates
- `highlightActiveConversation(cid, true)` (page load) still collapses others first
- `highlightActiveConversation(cid)` (CRUD) preserves other open workspaces

**Operations saved per CRUD sidebar update:**
- Eliminates full DOM teardown of tree nodes (dozens/hundreds of elements)
- Eliminates 8 event handler `.off().on()` re-bindings
- Eliminates 4 plugin re-initializations
- Preserves expansion state (no programmatic open/close after render)
- `refresh()` only updates changed nodes — unchanged nodes stay in DOM

**Risk notes:**
- `refresh.jstree` fires instead of `ready.jstree` after refresh — handled by
  one-shot `refresh.jstree` handler
- `redraw.jstree` and `after_open.jstree` still fire after refresh (event bindings
  persist) — triple-dot buttons re-added via existing handlers
- Node selection is not preserved by `refresh()` — the caller
  (`loadConversationsWithWorkspaces` done handler) re-applies highlight via
  `highlightActiveConversation`

### Verification checklist (Group C)

1. Load page — sidebar appears with all sections (tree, recent, pinned, archived, most accessed)
2. Click triple-dot on a conversation in tree — context menu works (flag, move, archive, delete, clone)
3. Flag a conversation — sidebar refreshes, tree stays in place (no collapse flash)
4. Archive a conversation — sidebar refreshes correctly
5. Expand two workspaces, flag a conversation — both workspaces stay expanded after refresh
6. Create a workspace — tree updates, new workspace appears at correct level
7. Move a conversation to another workspace — tree updates in place
8. Rapidly click "Set Flag" on 3 conversations — only 1-2 AJAX fetches fire (inflight dedup)
9. Page load with multiple workspaces — expanded state matches last session
10. Mobile: long-press context menu still works after refresh
11. No console errors during any of the above

---

## Group D — Item 8: DocumentFragment Batching (DONE)

### Item 8: DocumentFragment Batching in `renderMessages`

**File:** `interface/common-chat.js` (in `renderMessages`, lines ~2632-2885)

**Problem:** Each message card built in the `forEach` loop was immediately appended
to `#chatView` via `$('#chatView').append(messageElement)`. For a 40-message
conversation, this means 40 individual DOM insertions into the live document, each
potentially triggering style recalculation and layout.

**What was changed:**

A `DocumentFragment` collects all cards off-DOM during the loop, then one
`appendChild` flushes them all into `#chatView` after the loop ends. This collapses
N DOM insertions into 1.

**Gate:** The `renderCloseToSource` path (when `renderCloseToSource && history_message_ids.length > 0`) uses `.after()` for positional card insertion relative to
existing cards. This path cannot use fragment batching and retains per-card inserts.
All other call paths (full conversation load, single-message append, streaming card
creation) use the fragment.

**Implementation details:**

1. **Before the loop** (line ~2639): `useFragment` flag computed; `DocumentFragment`
   created when true.
2. **Inside the loop** (line ~2871): Instead of `$('#chatView').append(messageElement)`,
   the card's raw DOM node is added to the fragment via `fragment.appendChild(messageElement[0])`.
3. **After the loop** (line ~2883): `$('#chatView')[0].appendChild(fragment)` flushes
   all cards to the live DOM in one operation.

**Why it's safe:**
- All in-loop operations (`renderInnerContentAsMarkdown`, `initialiseVoteBank`,
  `statusDiv.hide()`, CSS changes) operate on in-memory jQuery objects — they don't
  require the element to be in the live DOM.
- MathJax typesetting is deferred (`defer_mathjax = !isLastMessage`) and runs
  asynchronously after the fragment is flushed.
- `initialCardCount` is snapshotted before the loop (H6 fix), so `message-index`
  stamping doesn't depend on live DOM card count during iteration.
- `newMessageElements[]` still collects all cards for the post-loop Bootstrap
  dropdown init (`$newCards.find('[data-toggle="dropdown"]').dropdown()`).

**Operations saved per 40-message conversation load:**
- 40 live-DOM `appendChild` calls → 1 single `appendChild`
- 39 eliminated intermediate style recalculations (browser may batch some, but
  fragment guarantees no intermediate recalcs)

**Risk:** Very low. The only behavioral change is timing of when cards appear in the
live DOM (end of loop instead of during each iteration). No code inside the loop
reads from the live `#chatView` DOM in the non-renderCloseToSource path.

### Verification checklist (Group D)

1. Load a conversation with 20+ messages — all cards render correctly, in order
2. Send a new message — single card appends correctly at the end
3. Verify `renderCloseToSource` mode — cards insert at correct positions (not at end)
4. Dropdown menus on all cards work (three-dot, vote, compact)
5. MathJax renders on all cards (especially the last card which is non-deferred)
6. Show/hide (showMore) toggles appear on long messages
7. Message actions (edit, delete, move, fork) use correct `message-index` values
8. No console errors during any of the above

---

## Group E — Item 7: Lazy-Load Feature Libraries (DONE)

### Overview

Removed 23 `<script>` tags and 7 `<link>` CSS tags from `interface.html` `<head>`,
replacing them with on-demand dynamic loading via a new `lazy-libs.js` utility.
Libraries are loaded the first time a user triggers the feature that needs them
(e.g., opening a code editor, viewing a drawio diagram).

### What was removed from `<head>`

| Library | Scripts | CSS | Reason |
|---------|---------|-----|--------|
| **DataTables** | 1 | 1 | Dead dependency — zero `.DataTable()` call sites in app code |
| **PDF.js CDN** | 1 | 0 | Unused — iframe viewer at `interface/pdf.js/web/viewer.js` bundles its own copy; app code never references `pdfjsLib` |
| **RevealNotes plugin** | 1 | 0 | Never passed to any Reveal constructor's `plugins` array |
| **RevealMarkdown plugin** | 1 | 0 | Never passed to any Reveal constructor's `plugins` array |
| **Reveal.js core + Highlight + Math** | 3 | 2 | `initializeSlidePresentation()` is defined but never called (dead code); standalone blob page embeds its own CDN links |
| **drawio-renderer** | 1 | 0 | Single call site, already deferred behind MathJax queue |
| **CodeMirror 5 core + 13 addons/modes** | 14 | 3 | All constructors are inside event handlers; loaded on first editor open |
| **EasyMDE** | 1 | 1 | Depends on CodeMirror; loaded on first WYSIWYG editor open |
| **CodeMirror5 inline wrapper** | (inline block) | 0 | Moved into `lazy-libs.js` `_registerCodeMirror5Wrapper()` |

**Total removed:** 23 scripts + 7 CSS = 30 network requests off initial page load.

### New file: `interface/lazy-libs.js`

Small (~190 lines) IIFE that exposes `window.LazyLibs` with per-library loaders:

- `LazyLibs.loadCodeMirror()` — loads CM core first, then all addons/modes in
  parallel, then registers the `window.CodeMirror5` wrapper.  Returns cached
  Promise.
- `LazyLibs.loadEasyMDE()` — chains on `loadCodeMirror()`, then loads EasyMDE
  script + CSS.
- `LazyLibs.loadReveal()` — loads Reveal core first, then Highlight + Math plugins
  in parallel + CSS.
- `LazyLibs.loadDrawio()` — loads drawio-renderer script.
- `LazyLibs.loadScript(url)` / `LazyLibs.loadCSS(url)` — low-level helpers,
  deduped by URL.

All loaders are idempotent — second+ calls return the same resolved Promise
instantly.  `<script defer src="interface/lazy-libs.js">` is placed in `<head>`
before all app scripts, so `LazyLibs` is available when they execute.

### Call site changes

**`interface/codemirror.js`** — Code editor modal:
- `shown.bs.modal` handler wraps init body in `LazyLibs.loadCodeMirror().then()`.
  If editor already exists, just focuses.  Error shown via `showToast`.

**`interface/markdown-editor.js`** — Message edit modal (4 call sites):
- `initEasyMDE()`: wraps EasyMDE construction in `LazyLibs.loadEasyMDE().then()`.
- `initCodeMirror()`: wraps CM construction in `LazyLibs.loadCodeMirror().then()`.
- `shown.bs.modal.editorInit` handler (PKB/custom modals): wraps CM construction
  in `LazyLibs.loadCodeMirror().then()`.
- `openInline()`: wraps CM construction in `LazyLibs.loadCodeMirror().then()`.

**`interface/file-browser-manager.js`** — File browser (2 call sites + 2 callers):
- `_ensureEditor()`: now returns a Promise (was void).  Wraps CM construction in
  `LazyLibs.loadCodeMirror().then()`.
- `_initOrRefreshEasyMDE()`: wraps EasyMDE construction in
  `LazyLibs.loadEasyMDE().then()`.
- Callers of `_ensureEditor()` (file load callback + modal open) updated to chain
  on the returned Promise.

**`interface/common.js`** — Reveal.js + drawio:
- `initializeSlidePresentation()`: existing `typeof Reveal === 'undefined'` guard
  now calls `LazyLibs.loadReveal().then()` and retries, instead of returning
  silently.  Safety net for if this function is ever re-enabled.
- drawio rendering block: checks `typeof waitForDrawIo === 'function'`; if not
  available, loads via `LazyLibs.loadDrawio().then()` before calling `waitForDrawIo`.

### Design decisions

- **Mermaid NOT lazy-loaded**: Called on every `renderMessages` completion (100ms
  setTimeout).  Too early and too frequent to defer — would cause visible flash of
  un-rendered diagrams.
- **No loading spinner for editors**: Bootstrap modal `shown.bs.modal` already shows
  the modal before our handler fires.  CDN scripts are typically browser-cached from
  prior sessions, so the delay is near-zero on repeat visits.  On first-ever visit,
  the ~100-300ms delay is acceptable inside a modal animation.
- **`_ensureEditor()` became async**: Returns `Promise.resolve()` when editor exists
  (hot path), or `LazyLibs.loadCodeMirror().then(...)` on first call.  Both callers
  chain via `.then()`.  No change to behavior — just microtask-delayed on resolve.
- **CodeMirror5 wrapper moved**: Previously an inline `<script>` block (~90 lines)
  in `interface.html`.  Now registered inside `lazy-libs.js` after CM loads.
  Identical behavior, just deferred.

### Verification checklist (Group E)

1. Open page — no console errors about missing CodeMirror/Reveal/EasyMDE/drawio
2. Open code editor modal — CodeMirror loads and initializes (may see brief delay on first open)
3. Open message edit modal (CodeMirror preview mode) — editor works
4. Switch to EasyMDE mode in message edit modal — EasyMDE loads and works
5. Open file browser, open a file — CodeMirror loads, file content displays
6. Switch file browser to WYSIWYG mode — EasyMDE loads
7. Open PKB overview edit modal — CodeMirror loads
8. Open inline editor — CodeMirror loads
9. View a message with drawio diagrams — diagrams render (after lazy load)
10. View a message with slides — standalone blob page still works (loads own CDN)
11. Verify DataTables removal has no visible effect (no tables broken)
12. Verify PDF viewer still works (iframe viewer self-contained)
13. Network tab: no CodeMirror/Reveal/EasyMDE/drawio/DataTables requests on initial load
14. Second code editor open — instant (cached Promise resolves immediately)

---

## Post-Audit: History Render Bottleneck Fixes

### Item 11 — Kill `hljs.highlightAuto()` + alias map + plaintext short-circuit — **DONE**

**File:** `common.js:3060-3153` (markdownParser.code renderer)

**Problem:** `markdownParser.code` is the hot path — called for every code block
during `marked.marked()` which runs per-message in the synchronous `renderMessages`
loop. When the language tag was unrecognized or missing (bare ``` blocks), the old
code called `hljs.highlightAuto(code)` which tested against **all 37 registered
grammars** (~50-200ms per block). For a conversation with 30+ unlabeled code blocks,
this alone was **1.5-6 seconds** of wasted CPU.

**Root cause of 13s render:** Server logs showed network returned at 10:05:58 but
next requests fired at 10:06:11 — 13 seconds of pure client-side rendering.
`highlightAuto` was the single largest contributor, compounded by double
`marked.marked()` for sectioned messages (each section's code blocks also went
through the renderer).

**Changes:**
1. **Eliminated `hljs.highlightAuto()`** — unlabeled blocks now render as
   HTML-escaped plaintext (no highlighting, no auto-detection stall).
2. **Added `_hljsAliasMap`** — O(1) lookup that maps common LLM aliases to hljs
   language names (`py`->`python`, `js`->`javascript`, `ts`->`typescript`,
   `sh`->`bash`, `yml`->`yaml`, etc. — 30+ aliases). This rescues blocks that
   would have fallen through to `highlightAuto` or plaintext.
3. **Plaintext short-circuit** — when final language is `plaintext`, skip `hljs`
   entirely and just HTML-escape. Avoids function-call overhead.
4. **Fixed deprecated API** — `hljs.highlight(lang, code)` (v10 2-arg form) replaced
   with `hljs.highlight(code, {language})` (modern v11 options-object form).

**Estimated savings:** ~3-6 seconds for a 40-message conversation with 60 code
blocks (30 unlabeled). Per-block cost drops from 50-200ms (highlightAuto) to <1ms
(plaintext escape) for unlabeled blocks.

**Trade-off:** Unlabeled code blocks lose auto-detected syntax coloring. In practice
LLMs label blocks correctly >90% of the time, and for the remaining unlabeled blocks
`highlightAuto` often guessed wrong anyway (e.g. highlighting terminal output as
Ruby). The alias map recovers most of the remaining cases.

**Files modified:** `interface/common.js` (markdownParser.code renderer)

---

## Item 12 — Async Chunked Rendering: Implementation Notes (DONE)

### What was done

**Files modified:** `interface/common-chat.js`, `interface/interface.html`

**Core change:** The `renderMessages` function now has two paths:

1. **Async chunked path** — used when `shouldClearChatView=true` AND `messages.length > 5`
   (i.e. full conversation loads from `setActiveConversation`). Processes messages in
   chunks of 5, yielding to the browser between chunks via `setTimeout(0)`. Each chunk
   builds cards off-DOM in a `DocumentFragment` and flushes with one `appendChild`.

2. **Synchronous path** — unchanged, used for small batches, incremental appends
   (streaming, sendMessage), and `renderCloseToSource` positional inserts.

**Refactoring:** The per-message card-building code was extracted into `_buildMessageCard()`
and the post-render work (mermaid, dropdowns, URL scroll, next questions, snapshot save)
was extracted into `_runPostRenderWork()`. Both paths share these helpers, eliminating
code duplication. The post-render work runs immediately for the synchronous path, or
after the last chunk for the async path.

**Cancellation token:** A module-level `_renderGeneration` counter prevents stale chunks
from flushing when:
- The user switches to a different conversation (new `renderMessages` call increments it)
- Streaming starts mid-render (`renderStreamingResponse` increments it)
- A valid DOM snapshot is restored (snapshot path increments it)

Each chunk checks `_renderGeneration !== renderToken` before flushing; if it changed,
the chunk silently bails.

**MathJax cases.js fix (bonus):** Removed `cases.js` from the MathJax TeX extensions
list in `interface.html`. This file doesn't exist in the MathJax 2.7.5 CDN and was
causing a 404 on every page load. The `\begin{cases}` environment is already provided
by `AMSmath.js`.

### Impact

- **Perceived load time:** First 5 messages visible in ~300-500ms instead of 8-12s
- **Total wall time:** Similar (+5% from yield overhead)
- **Browser responsiveness during load:** The browser can paint, handle events, and run
  MathJax between chunks — previously the main thread was blocked for the entire render

### Call sites analysis

| Caller | Path used | Why |
|--------|-----------|-----|
| `setActiveConversation` (line 860) | Chunked | Full conversation load, 10-100 messages |
| `renderStreamingResponse` (line 1498) | Sync | 1 message, `shouldClearChatView=false` |
| `sendMessage` (line 2990) | Sync | 1 message, `shouldClearChatView=false` |
| `deleteLastMessage` (line 2512) | Chunked if >5 msgs | Full re-render after deletion |
| `shared.js` (line 26) | Chunked if >5 msgs | Shared conversation load |

### Risks

- `deleteLastMessage` post-render scroll-to-bottom fires before all chunks complete.
  Acceptable: the scroll animation targets current `scrollHeight` which is close enough
  after the first chunk, and this is a rare user action.
- Post-render `setTimeout` callbacks in `_runPostRenderWork` use relative delays (50-250ms)
  from when the last chunk completes, not from when `renderMessages` was called. This is
  correct behavior — the delays were always meant to wait for DOM stabilization.

---

## Implementation Order (Suggested)

Start with the lowest-risk, highest-clarity changes:

1. ~~**Item 2** (defer scripts) — **DONE**~~
2. ~~**Item 5** (indexOf gates) — **DONE**~~
3. ~~**Item 6** (per-card UI state O(1) lookup) — **DONE**~~
4. ~~**Item 3** (sidebar render-skip fingerprint) — **DONE**~~
5. ~~**Item 10** (cache statusDiv + throttle doubt streaming) — **DONE**~~
6. ~~**Item 2.1** (hoist settings read) — **DONE**~~
7. ~~**Item 4** (eliminate ghost buttons) — **DONE**~~
8. ~~**Item 1** (defer dropdown population) — **DONE**~~
9. ~~**Item 8** (DocumentFragment batching) — **DONE**~~
10. ~~**Item 9** (jsTree refresh + expansion persistence) — **DONE**~~
11. ~~**Item 7** (lazy-load feature libraries) — **DONE**~~
12. ~~**Item 11** (kill highlightAuto + alias map + plaintext short-circuit) — **DONE**~~
13. ~~**Item 12** (async chunked rendering in renderMessages) — **DONE**~~

## Implementation Dependencies

- Item 5 depends on nothing — pure gating logic in `renderInnerContentAsMarkdown`
- Item 6 depends on nothing — edit `applyConversationUIState` only
- Item 3 depends on nothing — add cache layer to WorkspaceManager
- Item 4 should be done before or together with Item 1
- Item 1 depends on understanding the dropdown menu structure (read `initialiseVoteBank` fully first)
- Items 7, 9 are larger refactors with external library interaction

## Related Documentation

- `event_handler_audit_2026.md` — prior fixes (handler stacking, delegation)
- `ui_memory_rendering_optimizations_plan.md` — LRU, observer cleanup, focus delegation, skip redundant apply
- `README.md` — MathJax and deferred-render optimizations

---

## Remaining Optimization Ideas — Master Table

Everything below is what remains after Items 1-12 and Groups A-E were completed.
Organized into three tiers by estimated impact on perceived load time.

### Tier 1 — Core Render Bottleneck (target: 2-5s savings)

| # | Item | Description | Estimated Savings | Effort | Risk | Key Files |
|---|------|-------------|-------------------|--------|------|-----------|
| R1 | showMore() lazy wrap | In-place `wrapAll()` replaces serialize→clone→destroy→rebuild. `applyModelResponseTabs` + `updateMessageTocForElement` deferred to first [show] click for collapsed messages. Eager path kept for `show_at_start=true`. Height lock preserved during DOM reparenting. | 2-4s for 40-msg load (15 messages x 2 HTML serialize/parse cycles + deferred tabs/ToC) | Medium | Low — wrapAll keeps original DOM nodes, safer than clone; delegated handler already covers expand path | `common.js:1382-1570` |
| R2 | Fire network calls before/alongside render | Move 4 DOM-independent calls (`getConversationDetails`, `getConversationSettings`, `fetchMemoryPad`, `LocalDocsManager.refresh`) before `renderMessages`. For 2 DOM-dependent calls (`revealDoubtsButtons`, `_fetchAndHighlightPins`), split into fetch-early + apply-after-render. | 200-600ms per load (serialized network latency overlapped with render) | Low | Low — calls are read-only GETs with no ordering dependency | `common-chat.js:859-979` (`setActiveConversation`) |
| R3 | Double marked parse elimination | `processContentWithDetails` now parses first/last sections via `marked.marked(normalizeOverIndentedLists(...))`. `_sectionsFullyRendered` closure flag skips the global `marked.marked()` call. `hasPlaceholder` sections also pre-rendered. Inner `<details>` first section parsed. Dead-code inner last section removed. | 0.5-1s for conversations with 10+ sectioned messages (50KB of redundant markdown parsing eliminated) | Low | Medium — must verify tabbed layouts don't break; `applyModelResponseTabs` operates on the reassembled HTML | `common.js:5042, 5264, 5323, 5328, 5337, 5377, 5479` |

### Tier 2 — Boot Overhead (target: 300-800ms savings)

| # | Item | Description | Estimated Savings | Effort | Risk | Key Files |
|---|------|-------------|-------------------|--------|------|-----------|
| R4 | Defer 23 non-critical $(document).ready handlers | `window.deferReady` utility wraps `requestIdleCallback({ timeout: 200 })` with `setTimeout(fn, 1)` fallback. 23 handlers across 18 files deferred. 3 critical handlers kept eager: `common.js:7` (hljs+mermaid), `chat.js:627` (main boot), `workspace-manager.js:2123` (sidebar). | 100-300ms boot time | Low | Low — 15 zero-risk modal handlers + 6 low-risk with <100ms vulnerability window | `common.js` (utility), all manager JS files |
| R5 | Yielding MathJax scheduler | Replace per-card `MathJax.Hub.Queue(["Typeset", ...])` chain with `_mathJaxScheduler` that drains one element at a time with `setTimeout(0)` yield between each. Priority flag for visible card. `clear()` on conversation switch. Streaming bypasses scheduler. | Page stays responsive during MathJax (69s for 4 math cards becomes non-blocking) | Medium | Low — scheduler is additive, streaming path unchanged | `common.js:134-193`, `common-chat.js:694` |

### Tier 3 — Targeted Fixes (target: <200ms each, UX improvements)

| # | Item | Description | Estimated Savings | Effort | Risk | Key Files |
|---|------|-------------|-------------------|--------|------|-----------|
| R6 | 2.5 — data-has-tabs attribute gate | Replace `.find('.model-tabs-container').length` with `data-has-tabs` attribute check at 6 query sites | <50ms per 40-msg load | Trivial | Very Low | `common.js` (lines 441, 786, 2474, 4661, 5542) |
| R7 | 3.8 — File browser address bar debounce | Add 120ms debounce to fuzzy-match input event on address bar | UX improvement (eliminates lag on 1000+ paths) | Trivial | None | `file-browser-manager.js:2586` |
| R8 | 3.9 — Artefacts diff line-by-line batching | Replace per-line `.append()` with single `.html()` using `lines.map(buildDiffLine).join('')` | <100ms in diff view (500-line diffs) | Low | Low | `artefacts-manager.js:720-754` |
| R9 | 3.7 — File browser path suggestion Set | Maintain JS-side `Set` of paths updated incrementally on tree changes, instead of full DOM walk on every `loadTree` call | <100ms in file browser modal | Low | Low | `file-browser-manager.js:800-812` |
| R10 | 3.1 — Dark mode conditional CSS load | Check `localStorage.getItem('darkMode')` before loading `dark-mode.css` (809 rules). Or use CSS custom properties + single class toggle. | <50ms CSS parse time for light-mode users | Low | Low — must test runtime dark mode toggle still works | `interface.html:187` |
| R12 | Per-card chunking + collapsed card deferral | `CHUNK_SIZE=1` for per-card browser yields. `skip_deferred_formatting` skips tabs/ToC/UIState for collapsed cards. Deferred `initialiseVoteBank` + `decorateMessageCardNav` via `setTimeout(0)`. Removed wasted `textElem.html()`. | 50-200ms per collapsed card (×15-20 cards = 1-4s total); scrollable after 1st card instead of 5th | Low | Low — expand handler re-applies tabs+ToC; voteBank/decorateNav are cosmetic; streaming path unaffected (param defaults false) | `common-chat.js:2960,2806-2870`, `common.js:4940,5591-5624,5714` |

### Lower Priority / High Effort

| # | Item | Description | Estimated Savings | Effort | Risk | Notes |
|---|------|-------------|-------------------|--------|------|-------|
| R11 | Web Worker for markdown parsing | Run `marked.marked()` in a Web Worker for multiple cards in parallel. Pure text-to-text transform with no DOM dependency. | Proportional to core count | High | High — message passing, result ordering, error handling complexity | Only worthwhile if R1-R3 still leave >2s render time |

### Status Summary

| Item | Status | Notes |
|------|--------|-------|
| R1 — showMore() lazy wrap | **DONE** | Replaced serialize→clone→destroy→rebuild with in-place `wrapAll()`. For collapsed messages (`show_at_start=false`, the majority on history load), `applyModelResponseTabs` + `updateMessageTocForElement` deferred to first [show] click. Delegated toggle handler at `common.js:2507` already calls both on expand, so no new code needed for the expand path. For expanded messages (`show_at_start=true`, streaming completion or persisted 'show' state), tabs+ToC run eagerly. Height lock preserved during DOM reparenting. Updated `applyConversationUIState` comment. All callers verified: history load (`common-chat.js:2845`), streaming completion (`common-chat.js:1973`), shared.js (unaffected, `as_html=false`). Syntax verified. |
| R2 — Network parallelization | **DONE** | Fetch-early / apply-late for doubts+pins. `_renderCompletePromise` signals when all cards are in DOM. Stale-response guards added. Also fixes existing race where async chunked render hadn't finished when fetch responses arrived. |
| R3 — Double marked parse | **DONE** | `_sectionsFullyRendered` closure flag (var-hoisted to function scope). Outer first/last sections: `marked.marked(normalizeOverIndentedLists(sectionWithCode))`. `hasPlaceholder` sections: full `marked()` call after restoring details+code blocks (raw markdown around `<details>` tags now parsed). Inner `<details>` first section: parsed via `marked()` (unless it has `<summary>` tag from server). Inner last section dead-code variable assignment removed (loop already processes it as wrapped middle). Global `marked.marked()` at line ~5479 skipped when flag is true. Syntax verified with `node --check`. |
| R4 — Defer ready handlers | **DONE** | Added `window.deferReady` utility in `common.js` — wraps `requestIdleCallback({ timeout: 200 })` with `setTimeout(fn, 1)` fallback for Safari. Replaced 23 handlers across 18 files. 3 critical handlers kept eager: `common.js:7` (hljs+mermaid), `chat.js:627` (main boot), `workspace-manager.js:2123` (sidebar). 15 zero-risk (modal features, self-deferred), 6 low-risk (delegated handlers, <100ms vulnerability window). All syntax verified. |
| R5 — Batch MathJax | **DONE** | Yielding scheduler (`_mathJaxScheduler`) at `common.js:134-193`. Drains one Typeset at a time with `setTimeout(0)` yield between each. Priority flag for last/visible card. `clear()` on conversation switch. Streaming bypasses scheduler. New `mathJaxTypeset` perf mark. Page stays responsive during 69s MathJax. Does NOT reduce total MathJax wall time — MathJax 2.7.5 HTML-CSS output is inherently slow (DOM measurement per glyph). |
| R6 — data-has-tabs gate | **DONE** | Attribute set/removed in `applyModelResponseTabs`; 6 query sites updated. |
| R7 — File browser debounce | **Pending** | Trivial 1-liner. |
| R8 — Artefacts diff batching | **Pending** | Trivial 1-liner. |
| R9 — File browser path Set | **Pending** | Low effort. |
| R10 — Dark mode conditional CSS | **Pending** | Low effort. |
| R11 — Web Worker markdown | **Deferred** | Only if R1-R3 insufficient. |
| R12 — Per-card chunking + collapsed card deferral | **DONE** | Four changes: (1) `CHUNK_SIZE=1` — each card gets its own `setTimeout(0)` yield, so the browser can paint and handle scroll events between every card build. Page becomes scrollable after the first card instead of after 5. (2) `skip_deferred_formatting` parameter on `renderInnerContentAsMarkdown` — skips `applyModelResponseTabs`, `updateMessageTocForElement`, and `applyConversationUIState` for cards that will be collapsed by `showMore()` (`show_hide!='show' && text>300`). The delegated expand handler at `common.js:2570` re-applies both on first [show] click. (3) Deferred `initialiseVoteBank` and `decorateMessageCardNav` via `setTimeout(0)` — both set up dropdown menu and navigation UI that users don't interact with during initial load. (4) Removed wasted `textElem.html(message.text)` call that was immediately overwritten by `renderInnerContentAsMarkdown`. Syntax verified with `node --check`. |

### Perf Instrumentation — Implementation Notes (DONE)

**Files modified:** `interface/common.js:46-132`, `interface/common-chat.js` (multiple sites)

**What was added:**

1. **`_perfStart(label)`** / **`_perfEnd(label, startTime)`** — wall-clock timers that also
   create Performance API marks/measures (visible in Chrome DevTools Performance timeline).
   Timings grouped by base label (card index stripped via `label.replace(/#\d+$/, '')`).

2. **`_perfSummary()`** — prints a `console.table` sorted by total time descending.
   Auto-prints after `fullyInteractive` mark fires in `_runPostRenderWork`.

3. **`_perfJSON()`** — returns JSON string of all timings. Uses legacy `execCommand('copy')`
   for clipboard (avoids `navigator.clipboard.writeText` focus requirement from DevTools).

4. **`_perfReset()`** — clears all collected timings + Performance API marks/measures.
   Called at top of `setActiveConversation`.

5. **`window._PERF = true`** — enabled by default for always-on profiling.

**19 perf marks** placed throughout the render pipeline (see README.md for full table).

**Key design decision:** Marks are zero-cost when `_PERF=false` (early return in
`_perfStart`/`_perfEnd`). When enabled, overhead is ~0.1ms per mark pair (negligible vs
the operations being measured).

### Console Cleanup — Implementation Notes (DONE)

**Files modified:** `interface/common.js`, `interface/common-chat.js`, `interface/chat.js`,
`interface/doubt-manager.js`

**131 debug `console.log`/`console.warn` calls** commented out with `// [DEBUG]` prefix:
- `common.js`: 23 logs (applyModelResponseTabs tracing, visual/slide/copy/cache diagnostics)
- `common-chat.js`: 27 logs (stream diagnostics, show_more debug, cancellation, suggestions)
- `chat.js`: 21 logs (settings modal, terminal, user details, model catalog)
- `doubt-manager.js`: 60 logs (button injection debug, thread state, streaming)

No error handlers touched. Console output during profiling is now clean (only perf marks + errors).

### Bug Fixes (DONE)

1. **PDF.js iframe relative URL** (`interface.html:128`): Changed
   `src="interface/pdf.js/web/viewer.html"` to `src="/interface/pdf.js/web/viewer.html"`.
   Without leading `/`, browser resolved path relative to conversation URL
   (`/c/abc123/interface/...`), causing 404s.

2. **Missing semicolons causing IIFE parse error** (`common-chat.js:2830,2842`):
   `msgElements = [$(cardElem)]` lacked semicolons. Next line's IIFE
   `(function(...){...})()` was parsed as a function call on the array. Added `;`.

### Deep Analysis: showMore() DOM Cloning (R1)

**What it does per call** (`common.js:1382-1550`): For every message >300 chars (typically 18-25 of 40 messages):

1. `textElem.html()` — serializes the entire rendered message DOM to an HTML string (10-100KB)
2. `$('<span>').html(text)` — parses that string back into a new detached DOM tree
3. `textElem.empty()` — destroys the original children
4. Rebuilds the element with a 10-char preview `<span class="less-text">`, a `[show]` link, and the full content hidden in `<span class="more-text" style="display:none">`
5. `applyModelResponseTabs(moreText)` — scans and rebuilds tabbed layout inside the hidden content
6. `updateMessageTocForElement(moreText)` — generates Table of Contents for the hidden content
7. If `show_at_start=true` (message persisted as expanded): calls `toggle()` which re-runs steps 5 and 6 again

**Cost:** 2 full HTML serialization/parse cycles + DOM destruction/rebuild + tabs + ToC per card. For 20 long messages, that's **40 HTML serialize/parse cycles** during a single conversation load.

**Proposed fix — in-place wrap, deferred work:**

```javascript
// Current (expensive): serialize -> parse -> empty -> rebuild -> tabs -> toc
textElem.html() -> $('<span>').html(text) -> textElem.empty() -> textElem.append(...)
    -> applyModelResponseTabs(moreText) -> updateMessageTocForElement(moreText)

// Proposed (cheap): wrap in-place -> show preview -> defer everything else
textElem.contents().wrapAll($('<span class="more-text" style="display:none">'))
    -> prepend lessText + [show] link
    -> on first expand: applyModelResponseTabs + updateMessageTocForElement
```

The `wrapAll` approach is O(1) DOM reparenting — no serialization, no parsing. Tabs and ToC are deferred to the first `[show]` click. For messages persisted as "show" (`show_at_start=true`), the eager path remains unchanged.

### Deep Analysis: Double marked.marked() (R3)

#### Summary

When a message contains `---` horizontal rules (section dividers), the markdown is parsed by `marked.marked()` **twice**: once per middle section inside `processContentWithDetails`, and then the entire reassembled string (including the already-rendered middle-section HTML) goes through `marked.marked()` again at line 5472. The second parse is redundant — the middle sections are already HTML, and `marked` tokenizes/regex-matches them only to pass them through unchanged. Eliminating this saves one full `marked.marked()` call per sectioned message.

#### Key function locations

| Item | Line | File |
|------|------|------|
| `renderInnerContentAsMarkdown` definition | **4906** | `common.js` |
| `processContentWithDetails` definition (nested) | **5176** | `common.js` |
| Section detection regex (`horizontalRuleRegex`) | **5031** | `common.js` |
| `processContentWithDetails` called | **5383** | `common.js` |
| Slide-tag check (between processContent return and global parse) | **5387** | `common.js` |
| **THE DOUBLE PARSE** — global `marked.marked()` call | **5472** | `common.js` |
| `normalizeOverIndentedLists` definition | **2891** | `common.js` |
| `applyModelResponseTabs` definition | **3390** | `common.js` |
| Middle section parse (outer, no `<details>` placeholder) | **5355** | `common.js` |
| Middle section parse (inner, inside `<details>` placeholder) | **5283** | `common.js` |
| First section — returned as raw markdown | **5326-5331** | `common.js` |
| Last section — returned as raw markdown | **5333-5338** | `common.js` |

#### How section detection works

At line 5031, the regex is:
```js
var horizontalRuleRegex = /^---+\s*$/gm;
```
At lines 5032-5033:
```js
var hasHorizontalRules = horizontalRuleRegex.test(html);
horizontalRuleRegex.lastIndex = 0;
```
If `wrapSectionsInDetails && hasHorizontalRules` (line 5035), the code enters the sectioning branch and calls `processContentWithDetails(html)` at line 5383.

#### What `processContentWithDetails` does (lines 5176-5381)

1. **Extract code blocks** (lines 5179-5182) — replaces fenced code blocks (` ``` `, `~~~`) and inline backticks with null-byte placeholders (`\x00CB...`) to protect `---` inside code from being treated as section separators. Also handles incomplete fences for streaming (lines 5062-5082, `protectIncompleteFence`).

2. **Extract existing `<details>` tags** (lines 5186-5211) — protects pre-existing `<details>` blocks with placeholders (`\x00DP...`), preventing their inner `---` from causing spurious splits.

3. **Split by `---`** (line 5214):
   ```js
   var sections = workingContent.split(horizontalRuleRegex);
   ```

4. **Per-section processing:**

| Section type | Lines | Parsed via `marked.marked()`? | Wrapped in HTML? | Returned as |
|-------------|-------|-------------------------------|------------------|-------------|
| **First** (index 0) | 5326-5331 | **NO** | None | **Raw markdown** with code blocks restored |
| **Middle** (between first and last) | 5340-5366 | **YES** (line 5355: `marked.marked(normalizeOverIndentedLists(sectionWithCode), { renderer: markdownParser })`) | `<details open class="section-details">` + `<summary>` + `<div class="section-content">` | **Rendered HTML** inside HTML wrapper |
| **Last** (index == sections.length-1) | 5333-5338 | **NO** | None | **Raw markdown** with code blocks restored |
| **Has `<details>` placeholder** | 5226-5322 | **YES** for inner middle sections (line 5283) | Nested `<details>` | Mixed raw + rendered |

5. **Return value** (line 5371): A string that is a **mixture** of raw markdown (first/last sections) and already-rendered HTML (middle sections in `<details>` wrappers).

#### The double-parse flow — step by step

For a 3-section message:
```
First section markdown
---
Middle section markdown  
---
Last section markdown
```

**Step 1** (line 4906): Raw markdown enters `renderInnerContentAsMarkdown`.

**Step 2** (lines 4962-5026): Pre-processing — `<answer>` tags stripped, `<answer_tldr>` converted to `<div data-answer-tldr>`, `<answer_visual>` converted to comment placeholders.

**Step 3** (lines 5031-5033): Section detection — `horizontalRuleRegex.test(html)` returns `true`.

**Step 4** (line 5383): `processContentWithDetails(html)` is called. It returns:
```
First section raw markdown
<details open class="section-details" ...>
    <summary>...</summary>
    <div class="section-content">
        <p>Middle section as rendered HTML</p>
    </div>
</details>
Last section raw markdown
```

**Step 5** (line 5387): Slide-tag check — `html.includes('<slide-presentation>')`. For sectioned messages this is `false` (slide tags and `---` sections don't coexist in practice), so we fall into the `else` branch.

**Step 6 — THE DOUBLE PARSE** (line 5472):
```js
htmlChunk = marked.marked(normalizeOverIndentedLists(html), { renderer: markdownParser });
```
This passes the **entire** mixed output through `normalizeOverIndentedLists` (line-by-line processing) and then through `marked.marked()` **again**. The already-rendered middle section HTML goes through marked a second time.

**Step 7** (lines 5478-5485): Post-processing — `ANSWER_VISUAL` comment-to-div conversion.

**Step 8** (lines 5494-5524): DOM insertion — `innerHTML` assignment.

**Step 9** (lines 5546-5568): `applyModelResponseTabs`, ToC update, MathJax.

#### What `marked.marked()` does with already-rendered HTML

With the current config (`sanitize: false` at line 2841, `xhtml: true` at line 2844):

- **HTML block tags** (`<details>`, `<summary>`, `<pre>`, `<div>`): Marked recognizes these as HTML blocks and passes them through mostly untouched.
- **Performance cost**: Marked still **tokenizes** the entire input. It regex-matches every line to determine if it's an HTML block, paragraph, heading, list, etc. For already-rendered HTML, this is wasted work.
- **Correctness risks**: Generally safe. `marked` treats content inside HTML blocks as raw and doesn't transform it. Low risk of entity double-escaping or paragraph re-wrapping. Confirmed by the fact that the current code works correctly with the double parse.

#### What `normalizeOverIndentedLists` does (lines 2891-2933)

Iterates lines, tracks fenced code blocks, detects list items indented by 4+ spaces (`* text`, `1. text`), and strips 4 spaces. Operates on **raw markdown text**, not HTML. When run on already-rendered HTML (the `<details>` output), HTML lines like `<details open class="section-details"...>` won't match list-item patterns and pass through unchanged. **No harm, but wasted CPU cycles** on the HTML portions.

#### Quantification of redundant work

For a 5-section message (first + 3 middle + last) totaling 5KB:
- `processContentWithDetails` parses 3 middle sections individually (~3KB total through `marked.marked()`)
- Returns ~4KB HTML (middle sections) + ~1KB raw markdown (first + last sections) = ~5KB assembled string
- This entire ~5KB goes through `normalizeOverIndentedLists` (line-by-line) and then `marked.marked()` again
- The 4KB of already-rendered HTML is tokenized/regex-matched by marked even though it passes through unchanged

For a 40-message conversation where ~10 messages have sections: **~40-50KB of redundant markdown parsing eliminated**.

#### The proposed fix

Parse first and last sections inside `processContentWithDetails`, making the return value all-HTML. Then skip the global `marked.marked()` call.

**Changes needed in `processContentWithDetails`:**

1. At lines 5326-5331 (first section, index 0): Replace raw append with parse:
   ```js
   // Current (returns raw markdown):
   var sectionWithCode = restoreCodeBlocks(section, codeBlocks, codePlaceholders);
   wrappedHtml += sectionWithCode + '\n';
   
   // Proposed (returns rendered HTML):
   var sectionWithCode = restoreCodeBlocks(section, codeBlocks, codePlaceholders);
   wrappedHtml += marked.marked(normalizeOverIndentedLists(sectionWithCode), { renderer: markdownParser }) + '\n';
   ```

2. At lines 5333-5338 (last section, index == sections.length-1): Same treatment:
   ```js
   // Current (returns raw markdown):
   var sectionWithCode = restoreCodeBlocks(section, codeBlocks, codePlaceholders);
   wrappedHtml += '\n' + sectionWithCode;
   
   // Proposed (returns rendered HTML):
   var sectionWithCode = restoreCodeBlocks(section, codeBlocks, codePlaceholders);
   wrappedHtml += '\n' + marked.marked(normalizeOverIndentedLists(sectionWithCode), { renderer: markdownParser });
   ```

3. At lines 5253-5266 (inner first section inside `<details>` placeholder path): Same treatment — apply `marked.marked(normalizeOverIndentedLists(...))`.

4. At lines 5307-5308 (inner last section inside `<details>` placeholder path): Same treatment.

**Changes needed in `renderInnerContentAsMarkdown`:**

5. Signal mechanism — `processContentWithDetails` needs to tell the caller "all sections are already rendered, skip the global parse." Two options:

   **Option A — closure flag (simplest):**
   ```js
   var _sectionsFullyRendered = false;  // set by processContentWithDetails
   // ... inside processContentWithDetails, after rendering all sections:
   _sectionsFullyRendered = true;
   // ... at the global parse site (line 5472):
   if (_sectionsFullyRendered) {
       htmlChunk = html;  // already rendered, skip parse
   } else {
       htmlChunk = marked.marked(normalizeOverIndentedLists(html), { renderer: markdownParser });
   }
   ```

   **Option B — return object:**
   ```js
   var result = processContentWithDetails(html);
   html = result.html;
   var _sectionsFullyRendered = result.allRendered;
   ```

   Option A is simpler since `processContentWithDetails` is a nested function with closure access.

6. Guard: Only set the flag when `sections.length > 1` (line 5217). When `processContentWithDetails` returns content unchanged (no sections found, lines 5374-5380), the flag stays `false` and the global parse runs as before.

#### Risk analysis

| Risk | Assessment | Detail |
|------|-----------|--------|
| **Code between processContent return (5383) and global parse (5472)** | **SAFE** | Only the slide-presentation check (5387-5466) is between them. If `hasSlideTags` is `false` (normal for sectioned messages), we go straight to the `else` at line 5467 → line 5472. No string modifications happen. |
| **`normalizeOverIndentedLists` not called on first/last** | **Must be done** | Currently the global call at 5472 handles this. Fix: call it per-section inside `processContentWithDetails`, exactly as lines 5283 and 5355 already do for middle sections. |
| **`applyModelResponseTabs` breaks** | **SAFE** | This function (line 3390+) operates on the **DOM** after `innerHTML` assignment. It looks for `<details>` blocks, `[data-answer-tldr]`, `[data-answer-visual]` elements. It doesn't care whether these came from one `marked.marked()` call or from section-by-section parsing. |
| **`ANSWER_VISUAL` comment-to-div conversion (5478-5485)** | **SAFE** | Uses `indexOf` and `replace` on the `htmlChunk` string. These HTML comments survive `processContentWithDetails` output just as they would after `marked.marked()`. |
| **Cross-section markdown interactions** | **SAFE by design** | The code already splits by `---` and processes each section independently. `extractCodeBlocks` protects incomplete fences (lines 5062-5082). After splitting, each section is self-contained. The current double-parse doesn't "heal" cross-section issues either. |
| **Edge case: only 1 section (no `---`)** | **SAFE** | If `sections.length <= 1`, `processContentWithDetails` returns content unchanged (lines 5374-5380). The `_sectionsFullyRendered` flag stays `false`. Global parse runs. |
| **Edge case: message has both `<details>` and `---`** | **LOW RISK** | The nested recursive path (lines 5226-5322) handles this. Inner middle sections are already parsed (line 5283). Inner first/last sections need the same treatment as outer first/last. Must add `marked.marked(normalizeOverIndentedLists(...))` at lines 5258/5264 and 5308 for inner first/last. |
| **Edge case: empty first or last section (message starts/ends with `---`)** | **LOW RISK** | Empty string through `marked.marked()` returns empty string. Harmless. Test this. |
| **MathJax** | **SAFE** | Operates on DOM after `innerHTML` assignment. Unaffected by parse pipeline. |
| **ToC generation (`updateMessageTocForElement`)** | **SAFE** | Takes `elem_to_render_in` and raw `html` string. Doesn't depend on how `htmlChunk` was produced. |
| **Entity double-escaping from second parse** | **SAFE** (eliminated) | Currently there's a theoretical risk of `&amp;` → `&amp;amp;` from the redundant second parse. Eliminating it removes that risk entirely. |

#### Streaming path analysis

During streaming (`continuous=true`), `renderInnerContentAsMarkdown` is called repeatedly with partial content. Each call goes through the full pipeline:

- **Incomplete `---` sections** (e.g., first `---` delivered, second not yet): 2 sections detected (first + "last"). No middle sections → `processContentWithDetails` returns first (raw) + last (raw). If we parse both inside, the global parse is skipped. Equivalent behavior. **SAFE.**

- **Single `---` arriving mid-stream**: 2 sections, both parsed inside, flag set, global parse skipped. On the next stream chunk, if more content follows the second `---`, it becomes 3 sections. Each rendering cycle is self-contained. **SAFE.**

- **`---` inside code blocks during streaming**: `extractCodeBlocks` handles incomplete fences with `protectIncompleteFence` (lines 5062-5082). The entire unclosed fence is placeholder-protected. The split won't see it. **SAFE.**

- **No `---` at all**: No sections detected (line 5032 returns `false`), `processContentWithDetails` never called, global parse runs as before. **SAFE.**

#### Slide-presentation edge case

The slide path (lines 5391-5466) fires when `html.includes('<slide-presentation>')`. Key observations:

- Line 5383 sets `html = processContentWithDetails(html)` (the processed output).
- Line 5387 checks `hasSlideTags` on the already-processed `html`.
- If `hasSlideTags` is `true`, the slide path runs its own rendering (line 5398: `marked.marked()` per text part) and produces `htmlChunk` at line 5466. **It never reaches line 5472.**
- If `hasSlideTags` is `false`, we fall into the `else` at line 5467 → line 5472.

So the flag only matters in the `else` branch (non-slide). **No conflict with slides.**

In practice, slide tags (`<slide-presentation>`) and `---` sections don't coexist in the same message (slides use `---` as slide separators within the `<slide-presentation>` wrapper, but those `---` are inside the tag). The `extractCodeBlocks` and `<details>` extraction would protect them anyway.

#### Inner `<details>` placeholder path — additional parse sites needed

When a section contains a pre-existing `<details>` block that itself has `---` inside it, the code enters the recursive path at lines 5226-5322. This path processes inner sections of the `<details>` block:

- **Inner first section** (lines 5257-5266): Currently returned as raw markdown (with code blocks restored). The `summaryMatch` check at line 5260 looks for `<summary>` tags but regardless of the result, the section is appended as-is (lines 5262, 5264 are identical). **Needs `marked.marked(normalizeOverIndentedLists(...))` treatment.**

- **Inner middle sections** (lines 5269-5305): Already parsed via `marked.marked()` at line 5283. **No change needed.**

- **Inner last section** (lines 5307-5308): Currently just `var lastSection = innerSections[innerSections.length - 1].trim();` and... it's assigned to a variable but never appended to `innerWrapped`. Looking at line 5311: `detailsBlock = detailsOpening + innerWrapped + '</details>';` — the last section is **silently dropped**. This appears to be an **existing bug** (content after the final `---` inside a pre-existing `<details>` block is lost). The fix should either append it or preserve the existing behavior intentionally.

#### Edge cases requiring testing

1. Message with exactly 1 `---` (2 sections, no middle) — verify both first and last are rendered correctly
2. Message with `---` inside a code block — verify no spurious splitting
3. Message with `<details>` tags that also have `---` — the nested recursive path
4. Streaming: partial message with one `---` delivered, then second `---` arrives in next chunk
5. Message with `<answer_tldr>` + `---` sections — ensure tab building still works
6. Message with math (`$$...$$`) in first/last sections — ensure MathJax still processes them
7. Message with no `---` at all — must still go through single `marked.marked()` as before
8. Empty first or last section (message starts with `---` or ends with `---`)
9. Very long first/last sections with over-indented lists — ensure `normalizeOverIndentedLists` runs
10. Message with `<answer_visual>` comment placeholders in first/last sections — ensure they survive

#### Estimated savings

- **Per sectioned message**: Eliminates one full `marked.marked()` call over the entire assembled string. For a typical 5-section message (~5KB), saves ~1-3ms of tokenization/regex work.
- **Per 40-message conversation with ~10 sectioned messages**: ~10-30ms savings from eliminating ~40-50KB of redundant parsing.
- **Per streaming render of a sectioned message**: Each incremental render saves one `marked.marked()` call. With 20-40 streaming renders per message, that's 20-40 eliminated calls. At ~1-3ms each: **~20-120ms saved per streamed sectioned message.**
- **Total for content-heavy conversation load**: **0.5-1s savings** (10 sectioned messages × average 5KB each × one eliminated parse per message, plus reduced `normalizeOverIndentedLists` overhead on already-rendered HTML).

#### Discovered existing bug

**Inner last section silently dropped** (line 5308): In the `<details>` placeholder path, `var lastSection = innerSections[innerSections.length - 1].trim()` is assigned but never appended to `innerWrapped`. Content after the final `---` inside a pre-existing `<details>` block is lost. This is an existing bug unrelated to R3, but should be fixed alongside or noted for separate fix.

### Deep Analysis: Network Parallelization (R2)

**Current flow in `setActiveConversation`:**

```
$.when(restorePromise, messagesRequest).done() ->
    renderMessages() [blocks main thread] ->
    _runPostRenderWork() [fires 6 post-render calls]:
        - revealDoubtsButtons      (fetch + DOM manipulation)
        - _fetchAndHighlightPins   (fetch + DOM manipulation)
        - getConversationDetails   (fetch only, updates domain tabs)
        - getConversationSettings  (fetch only, sets chatSettingsState)
        - fetchMemoryPad           (fetch only, populates sidebar textarea)
        - LocalDocsManager.refresh (fetch only, populates sidebar panel)
```

**Proposed flow:**

```
$.when(restorePromise, messagesRequest).done() ->
    // Fire 4 DOM-independent calls immediately (overlaps with render)
    getConversationDetails()
    getConversationSettings()
    fetchMemoryPad()
    LocalDocsManager.refresh()
    // Start fetches for DOM-dependent calls (data arrives during render)
    var doubtsPromise = fetchDoubtsData()
    var pinsPromise   = fetchPinsData()
    
    renderMessages() ->
    // After render, apply fetched data to DOM
    doubtsPromise.then(applyDoubtsToCards)
    pinsPromise.then(applyPinsToCards)
```

| Call | Depends on rendered cards? | Can fire before render? |
|------|----------------------------|------------------------|
| `getConversationDetails` | No — updates domain tabs | Yes |
| `getConversationSettings` | No — sets chatSettingsState | Yes |
| `fetchMemoryPad` | No — populates sidebar textarea | Yes |
| `LocalDocsManager.refresh` | No — populates sidebar panel | Yes |
| `revealDoubtsButtons` | Yes — toggles btn visibility | Fetch yes, apply after render |
| `_fetchAndHighlightPins` | Yes — sets star icons on cards | Fetch yes, apply after render |

### Recommended Implementation Order

1. **R2** (network parallelization) — **DONE**. Low effort, low risk, 200-600ms savings
2. **R1** (showMore lazy wrap) — **DONE**. Highest impact (2-4s), in-place wrapAll + deferred tabs/ToC
3. **R3** (double marked parse) — **DONE**. Low effort, 0.5-1s savings
4. **R7 + R8** (file browser debounce + diff batching) — Trivial 1-liners
5. **R4** (defer ready handlers) — **DONE**. 23 handlers deferred via `deferReady()`, 100-300ms savings
6. **R12** (per-card chunking + collapsed card deferral) — **DONE**. CHUNK_SIZE=1, skip tabs/ToC/UIState for collapsed, defer voteBank+decorateNav, remove wasted .html()
7. **R5** (yielding MathJax scheduler) — **DONE**. Page stays responsive during MathJax. 69s total but non-blocking.
8. **R9 + R10** (path Set + dark mode CSS) — Low effort, low impact

### Next Steps (Post-R5)

MathJax is now 90% of total wall time (69s for 4 math cards out of 80 messages).
The scheduler keeps the page responsive but cannot reduce total typeset time.
Two approaches remain:

1. **Viewport-based MathJax deferral** — Only typeset cards visible in viewport;
   lazy-typeset off-screen cards via IntersectionObserver. Low risk, immediate
   perceived improvement.

2. **MathJax 3 migration** — CHTML output (CSS-based, no DOM measurement), 2-5x
   faster, Promise-based API. Requires updating 16 call sites, 3 HTML configs,
   streaming path. Medium risk but eliminates the root cause.
