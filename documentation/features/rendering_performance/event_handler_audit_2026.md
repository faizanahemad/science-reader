# Event Handler & Rendering Pipeline Audit — 2026

## Background

A systematic audit of `interface/common.js`, `interface/common-chat.js`, and related UI files
identified a set of event-handler accumulation bugs, deprecated API usages, and per-render
overhead patterns. Fixes were applied incrementally in severity order. This document covers
all items investigated and changed.

The audit divided findings into severity tiers:

- **High (H1–H6)**: handler stacking that actively fires multiple times per event, deprecated
  synchronous DOM events on hot streaming paths, or per-render DOM query explosions.
- **Medium (M1–M8)**: latent stacking risks, O(N²) loops, forced reflows, and dead code.
- **Low (L1–L9)**: code organisation, hoist-out refactors, deduplication of shared utilities,
  and a correctness fix for the file-browser Escape key race.

All High, Medium, and Low items are fully resolved.

---

## High-Severity Fixes

### H1 — `setupFloatingTocHandlers` handler accumulation

**File:** `common.js` — `setupFloatingTocHandlers`, around line 854.

**Problem:** The function registered `click` and `keydown` handlers on the floating ToC panel
every time it was called (on every ToC open). Without a prior `.off()`, each open stacked an
additional copy, so N rapid opens produced N simultaneous handlers.

**Fix:** Added `.off('click.floatingToc')` and `.off('keydown.floatingToc')` immediately before
each `.on()` call.

---

### H2 — `sendMessageCallback` handler accumulation + orphaned 5-second timer

**File:** `common-chat.js` — `sendMessageCallback`, around line 3390.

**Problem:** Two issues in the send-message flow:
1. A 5-second auto-close timer was created fresh on every invocation without cancelling any
   previous one. Rapid Send presses could queue N independent timers that all fired.
2. The modal-open handler was re-attached on every invocation without `.off()`.

**Fix:**
- Added module-level `_preventChatRenderingTimer` variable to track the timer reference.
- Added `clearTimeout(_preventChatRenderingTimer)` before scheduling a new one.
- Added `.off(...)` before the 200 ms re-attach.
- Also fixed HTML: `data-bs-dismiss="modal"` → `data-dismiss="modal"` in `interface.html` (Bootstrap 4.6 syntax).

---

### H3 — `attachSectionListeners` called on every render

**File:** `common.js` and `common-chat.js`.

**Problem:** `attachSectionListeners()` was called from both `renderMessages` (once per historic
card) and `renderStreamingResponse`, re-binding section-toggle listeners on every render.

**Fix:** Deleted the `attachSectionListeners` function entirely. Moved the `.off().on()` body
to module-level one-time init. Removed both call sites.

---

### H4 — `updateFloatingTocIfOpen` re-bound click handlers on every streaming tick

**File:** `common.js` — `updateFloatingTocIfOpen` and `setupFloatingTocHandlers`.

**Problem:** On every streaming chunk while the floating ToC was open, the function destroyed
and re-registered click handlers on all `.floating-toc-link` elements (33-line re-bind block).
This accumulated N handlers × M streaming chunks.

**Fix:**
- Switched to delegated event handling: `$panel.on('click', '.floating-toc-link', ...)` in
  `setupFloatingTocHandlers`. The handler survives ToC content rebuilds automatically.
- Removed the entire 33-line re-bind block from `updateFloatingTocIfOpen`.
- Added null-target fallback: `window.location.hash = targetId` when heading is not in DOM
  during streaming.

---

### H5 — `applyModelResponseTabs` called unconditionally on every streaming chunk

**File:** `common.js` — inside `renderInnerContentAsMarkdown`, around line 5363.

**Problem:** `applyModelResponseTabs` was called on every streaming render regardless of
whether the content contained tab markers (`[TAB:...]`, `[MODEL_RESPONSE_TAB]`, etc.).
The function does ~6 DOM traversals per call.

**Fix:** Added a 5-condition string gate on the raw `htmlChunk` before the call. The function
is skipped entirely for plain messages that contain none of the marker strings.

---

### H6 — `renderMessages` per-iteration `.find('.message-card')` DOM query

**File:** `common-chat.js` — `renderMessages`, around line 2603.

**Problem:** Inside the `messages.forEach` loop, each iteration called
`$('#chatView').find('.message-card').length` to determine the message index. For a 40-message
history load this ran 40 DOM queries that grew progressively more expensive (1 card, 2 cards,
…, 40 cards).

**Fix:** Captured `var initialCardCount = $('#chatView').find('.message-card').length` once
before the loop. Each iteration uses `initialCardCount + originalIndex`.

---

### Dropdown close-on-outside-click (3-part fix)

**File:** `common-chat.js` — `renderMessages` and `MultiSelectManager`.

**Problem:** Three related issues prevented Bootstrap 4.6 dropdowns from closing when clicking
outside them after a re-render:

1. `$('[data-toggle="dropdown"]').dropdown()` was scoped globally, re-initialising Bootstrap
   on every previously-rendered card (stacking instances on stale DOM nodes).
2. `e.stopPropagation()` in `MultiSelectManager`'s document click handler was unconditionally
   blocking Bootstrap's outside-click dismiss event.
3. The streaming path also called the global selector unnecessarily (M7 below).

**Fix:**
1. Collected newly-rendered cards into `newMessageElements[]` during the forEach loop.
2. Scoped dropdown init to `$(newMessageElements).find('[data-toggle="dropdown"]').dropdown()`.
3. Guarded `e.stopPropagation()` with `$('.dropdown-menu.show').length === 0` — only suppress
   when no dropdown is open.

---

## Medium-Severity Fixes

### M1 — `scrollToBottom` attaches listeners with no guard

**File:** `common-chat.js` — `scrollToBottom`, around line 3702.

**Problem:** Every call to `scrollToBottom` unconditionally attached `scroll`, `change`,
`DOMSubtreeModified`, and `click` handlers, and created a new `ResizeObserver`, with no way
to clean up previous ones. The function is currently called only once per page load (from
`chat_interface_readiness()` in `chat.js`), so the bug was latent, but the `ResizeObserver`
was stored in a local variable and could never be disconnected.

**Fix:**
- Added module-level `_scrollToBottomInitDone` flag and `_chatViewResizeObserver` reference.
- All `.on()` calls namespaced with `.scrollToBottom`.
- Button uses `.off('click.scrollToBottom').on('click.scrollToBottom', ...)`.
- `checkScroll()` still runs unconditionally on every call (correct for re-entrant use).
- Listener binding block is guarded by the init flag.
- Removed unused `$messageText` variable.

---

### M2 — `renderMermaidIfDetailsTagOpened`: deprecated `DOMNodeInserted`, 3 unguarded handlers, orphaned observer

**File:** `common.js` — `renderMermaidIfDetailsTagOpened`, around line 5650.

**Problem:** Three issues:

1. **`DOMNodeInserted` (line 5699)** — a deprecated synchronous DOM Level 3 Mutation Event
   registered on `$(document)`. It fired on *every single DOM write* across the entire page
   during streaming (every token appended to a message card). Because it is synchronous, it
   blocked the browser's rendering pipeline mid-mutation. Browsers have been warning of removal
   since 2011; it is no longer in the DOM Living Standard.

2. **Three `$(document).on(...)` calls with no namespace or `.off()` guard.** If the function
   were called more than once, all three handlers would stack. Additionally, the `click` handler
   (line 5667) raced with the `toggle` handler — both called `mermaid.run()` for the same open
   event, causing it to run twice per `<details>` open.

3. **`MutationObserver` stored in a local `const`** — could never be disconnected from outside
   the function scope.

**Fix:**
- Added module-level `_mermaidDetailsInitDone` flag, `_mermaidAttrObserver`, and
  `_mermaidNewDetailsObserver`.
- Function returns immediately if `_mermaidDetailsInitDone` is true.
- Deleted the redundant `click details summary` handler. `toggle` alone is spec-compliant and
  sufficient in all modern browsers.
- Replaced `DOMNodeInserted` with a `MutationObserver` watching `{ childList: true, subtree: true }`
  on `document.body`. The callback is async, batched, and only calls
  `_mermaidAttrObserver.observe(node, ...)` for inserted `<details>` nodes — no DOM reads, no
  layout pressure. An early-exit guards against calling `querySelectorAll` on leaf nodes
  (`node.children.length === 0`).
- Namespaced the `toggle` handler as `toggle.mermaidDetails`.
- Promoted `observer` to module-level `_mermaidAttrObserver` (disconnectable).

---

### M3 — `restoreCodeBlocks` O(N²) `reduce` inside loop

**File:** `common.js` — `restoreCodeBlocks`, around line 4930.

**Problem:** Inside the `for (var i = 0; i < placeholders.length; i++)` loop, line 4972 ran:

```js
var expectedMaxSize = originalLength + codeBlocks.reduce(function(sum, cb) {
    return sum + (cb ? cb.length : 0);
}, 0);
```

The `reduce` result is a constant (total size of all code blocks). Running it on every iteration
made the function O(N²) in the number of code blocks. `restoreCodeBlocks` is called up to 9
times per `renderInnerContentAsMarkdown` invocation, which itself fires on every streaming chunk.

**Fix:** Hoisted the `reduce` to two pre-loop variables before the `for`:

```js
var totalCodeBlockSize = codeBlocks.reduce(function(sum, cb) {
    return sum + (cb ? cb.length : 0);
}, 0);
var expectedMaxSize = originalLength + totalCodeBlockSize;
```

The loop body now reads `expectedMaxSize` as a constant. Zero functional change.

---

### M4 — `offsetHeight` read after DOM writes forces layout reflow at stream completion

**File:** `common-chat.js` — `if (done)` block, around line 1876 (original position).

**Problem:** The height-lock block (`_cardBodyForLock.offsetHeight`) was positioned after
`statusDiv.hide()`, `statusDiv.find('.spinner-border').removeClass('spinner-border')`,
`card.removeAttr('data-live-stream')`, and `card.attr('data-live-stream-ended', 'true')`.
Reading `offsetHeight` after those DOM writes forced a synchronous layout flush (reflow) —
the browser had to complete all pending style recalculations before returning the value.

This happens once per AI response (inside `if (done)`, not per streaming chunk), so the impact
is bounded but avoidable.

**Fix:** Moved the height-lock block (`var _cardBodyForLock`, `_cardBodyLockedHeight`,
`_cardBodyForLock.style.minHeight`) to immediately after `currentStreamingController = null`,
*before* any DOM writes (`statusDiv.hide()`, `removeAttr`, etc.). The `offsetHeight` read now
hits a clean layout with no pending mutations — no flush required.

---

### M5 — `removeEmTags` identity function called 4 times per render

**File:** `common.js` — `removeEmTags` (definition) and 4 call sites.

**Problem:** `removeEmTags` was a pure identity function — its entire body was `return htmlChunk`.
A comment explained it was intentionally emptied to preserve italic rendering after a prior
refactor. It was called at 4 points in the render pipeline including the hot streaming path
(once per chunk for the default markdown branch).

**Fix:** Deleted all 4 call sites (lines 5093, 5166, 5210, 5285) and the function definition.
No callers exist in any other file. Zero functional change.

---

### M6 — `.find('.status-div')` queried twice per SSE chunk

**File:** `common-chat.js` — per-chunk streaming handler (`if (!done)` branch).

**Problem:** In the non-done streaming path, `card.find('.status-div')` was called at two
separate points — once near the top of the chunk handler (line 1603, to show the spinner) and
once near the bottom (line 1750, to update the status text) — with ~150 lines of content
rendering logic between them. Each was a separate jQuery subtree traversal.

**Fix:** Removed the second `var statusDiv = card.find('.status-div')` declaration (line 1750).
The variable declared at line 1603 is reused by the usage at line 1750 through normal `var`
function-scope hoisting. Saves one jQuery traversal per SSE chunk (~200 per response).

---

### M7 — Bootstrap dropdown re-initialised on every streaming `message_ids` chunk

**File:** `common-chat.js` — streaming `message_ids` handler, around line 1808.

**Problem:** A `setTimeout(() => card.find('[data-toggle="dropdown"]').dropdown(), 25)` block
fired once per `message_ids` SSE chunk. Bootstrap 4.6 auto-initialises `data-toggle="dropdown"`
elements on DOM insertion, `setupStreamingCardEventHandlers` re-wires all card handlers in
the same block, and the stream-done path already handles dropdown init. The explicit call was
entirely redundant.

**Fix:** Removed the `setTimeout/.dropdown()` block. Replaced with a comment explaining why
it is not needed. The stream-done path at line 2932 (`$newCards.find('[data-toggle="dropdown"]').dropdown()`) is unaffected.

---

### M8 — `doubt-manager.js` handler re-registration on every modal open (investigated; no fix needed)

**File:** `interface/doubt-manager.js` — `setupChatEventHandlers` and `setupOverviewEventHandlers`.

**Investigated:** `setupChatEventHandlers` re-registers 6 `$(document).on(...)` handlers on
every doubt-chat-modal open; `setupOverviewEventHandlers` re-registers 4 on every overview
open. However, every single registration is immediately preceded by an inline `.off(sameEvent,
sameSelector)`. Because the selector strings are identical on `.off()` and `.on()`, no
accumulation occurs in practice. The issue is event-system churn (off+on per open), not a
correctness bug.

**Decision:** No functional change made. An optional future improvement would be moving the
6 `$(document)` handlers from `setupChatEventHandlers` into `setupGlobalDoubtsHandlers`
(called once at `document.ready`) and adding a `.doubtChat` namespace, eliminating the
per-open churn entirely.

---

## Low-Severity Fixes

### L1 — `simpleHash` defined inside a nested `if` block

**File:** `common.js`.

**Problem:** `simpleHash` was defined inside a deeply nested `if (wrapSectionsInDetails && hasHorizontalRules)` block, making it inaccessible outside that branch.

**Fix:** Hoisted to module level with a JSDoc comment. Zero duplication; call site unchanged.

---

### L2 — `isFenceLine` defined 3 levels deep inside `extractCodeBlocks`

**File:** `common.js` — `isFenceLine`, around line 4857 (original).

**Problem:** `isFenceLine` is a pure function (no closure over outer state) that was defined
inside `renderInnerContentAsMarkdown → if-block → extractCodeBlocks`. It was re-created on
every call to `extractCodeBlocks`.

**Fix:** Hoisted to module level at line 4717 (immediately after `simpleHash`) with a JSDoc
comment. The single call site inside `protectIncompleteFence` is unchanged. Mirrors the
already-fixed `simpleHash` pattern.

---

### L3 — `file-browser-manager.js` four unguarded `$(document).on('keydown')` handlers merged

**File:** `interface/file-browser-manager.js` — `init()` function.

**Problem:** Four separate bare `$(document).on('keydown', ...)` handlers were registered
inside `init()`: one for the confirm-modal Escape (line 2545), one for AI-edit overlay Escape
(line 2574), one for context-menu Escape (line 2819), and one for the main modal Ctrl+S /
Escape (line 2851). Three bugs:

1. **No namespace** — none could be removed individually; a future `destroy()` had no way to
   clean them up.
2. **Multi-instance accumulation** — two `createFileBrowser()` instances (`fb` + `global-docs-fb`)
   each register their own 4 handlers → 8 live `$(document).on('keydown')` listeners
   simultaneously on the page.
3. **Escape race condition** — `e.stopPropagation()` does not prevent other handlers registered
   on the same node from firing. Concretely: opening a sub-modal (confirm, AI edit) while the
   main modal was open caused a single Escape to close *both* the sub-modal and the main modal.
   Handler A (confirm-modal) also lacked the outer `_$('modal').hasClass('show')` guard, so it
   fired globally even when the file browser was closed.

**Fix:** Merged all four into one unified namespaced handler per instance:

```js
var _kbNs = 'keydown.fileBrowser_' + instanceId.replace(/-/g, '_');
$(document).off(_kbNs).on(_kbNs, function (e) { … });
```

The single handler dispatches in explicit priority order using `e.stopImmediatePropagation()`
at each branch exit, preventing the second instance's handler from double-acting:

1. Ctrl/Cmd+S → `saveFile()` (requires modal open)
2. Escape: AI diff overlay → `_rejectAiEdit()`
3. Escape: AI edit overlay → `_hideAiEditModal()`
4. Escape: confirm modal → `_hideConfirmModal()`
5. Escape: context menu → `_hideContextMenu()`
6. Escape: main modal → `_closeModal()`

Handlers A (confirm Escape), B (AI edit Escape), C (context-menu Escape) were deleted. Handler
D was replaced by the unified handler. The `$(document).off(_kbNs)` before `.on()` makes
`init()` safely idempotent and enables a single-call teardown.

---

### L4 — `escapeHtml` defined 10 times across 8 files — consolidated into `common.js`

**Files:** `common.js` (new canonical), `common-chat.js`, `file-browser-manager.js`,
`tool-call-manager.js`, `artefacts-manager.js`, `clarifications-manager.js`,
`cross-conversation-search.js`, `doubt-manager.js`, `pkb-manager.js`.

**Problem:** The same HTML-escaping logic was copy-pasted under 5 different names:
`escapeHtml`, `_escHtml`, `_escapeHtml`, `escapeDocHtml`, `_doubtEscapeHtml`. Three semantic
variants existed (3-entity, 4-entity, 5-entity regex; DOM-based). The author of
`doubt-manager.js` even left a comment: *"not available as a global elsewhere"*.

**Fix:** Added one canonical function to `common.js` (loaded first, before all 8 affected
files):

```js
function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
```

5-entity (strict superset of all variants), null-safe, handles non-string input. All 10 local
definitions deleted. Call sites using old names renamed to `escapeHtml`:

| File | Old name(s) | Action |
|------|-------------|--------|
| `artefacts-manager.js` | `escapeHtml` | Definition deleted; calls unchanged |
| `common-chat.js` | `escapeHtml` ×2, `escapeDocHtml` | Definitions deleted; `escapeDocHtml(` → `escapeHtml(` |
| `file-browser-manager.js` | `_escHtml` | Definition deleted; `_escHtml(` → `escapeHtml(` |
| `tool-call-manager.js` | `_escapeHtml` | Definition deleted; `_escapeHtml(` → `escapeHtml(` |
| `clarifications-manager.js` | `_escapeHtml` | Definition deleted; `_escapeHtml(` → `escapeHtml(` |
| `cross-conversation-search.js` | `_escapeHtml` | Definition deleted; `_escapeHtml(` → `escapeHtml(` |
| `doubt-manager.js` | `_doubtEscapeHtml` | Definition deleted; `_doubtEscapeHtml(` → `escapeHtml(` |
| `pkb-manager.js` | `escapeHtml` | Definition deleted; calls unchanged |

---

### L5 — `_fuzzyMatch` duplicated in `common-chat.js` and `file-browser-manager.js`

**Files:** `common-chat.js` (inside slash-command autocomplete IIFE), `file-browser-manager.js`
(inside `createFileBrowser` factory), `common.js` (new canonical location).

**Problem:** Byte-for-byte identical algorithm in two places. The `common-chat.js` copy even
had a comment: *"ported from file-browser-manager.js"* — acknowledged technical debt.

**Fix:** Added `function fuzzyMatch(needle, haystack)` to `common.js` at module level
(immediately after `simpleHash`, with full JSDoc). Deleted both private copies. Updated call
sites:

- `common-chat.js`: `_fuzzyMatch(...)` → `fuzzyMatch(...)` (1 call site in slash autocomplete)
- `file-browser-manager.js`: `_fuzzyMatch(...)` → `fuzzyMatch(...)` (2 call sites inside
  `_fuzzyMatchPath`; the path-specific wrapper itself stays private to the factory)

---

### L6 — `hideSidebarOnMobileIfOpen` duplicated across `common-chat.js` and `workspace-manager.js`

**Files:** `common-chat.js:786`, `workspace-manager.js:172`, `workspace-manager.js:19`
(public canonical).

**Problem:** Three copies of the same sidebar-hide logic. `WorkspaceManager.hideSidebarIfMobile`
(line 19) already existed as a public method used by 3 of 5 call sites. The public method
lacked the `innerWidth` fallback for browsers without `matchMedia`.

**Fix (3 steps):**

1. **Fixed the canonical public method** (`workspace-manager.js:19`) to add `innerWidth`
   fallback, matching the more robust `isMobileWidth()` pattern already used in the file:
   ```js
   var isMobile = window.matchMedia
       ? window.matchMedia('(max-width: 768px)').matches
       : (window.innerWidth || 9999) <= 768;
   ```

2. **Replaced the private copy** inside `installMobileConversationInterceptor`
   (`workspace-manager.js:172`) with a one-line delegate:
   ```js
   function hideSidebarIfMobileOpen() { WorkspaceManager.hideSidebarIfMobile(); }
   ```

3. **Replaced the `common-chat.js` local function and call** with a guarded delegation:
   ```js
   if (typeof WorkspaceManager !== 'undefined' && WorkspaceManager.hideSidebarIfMobile) {
       WorkspaceManager.hideSidebarIfMobile();
   }
   ```
   The `typeof` guard matches the pattern already used at line 769 in the same function.

---

### L7 — `renderAttachmentPreviews` `.att-remove-btn` rebind (investigated; no fix)

**Investigated:** `.container.html(html)` destroys all child nodes before `.off().on()` runs —
buttons are always freshly created, so `.off()` is a no-op and there is no accumulation.
No functional bug.

**Decision:** Leave as-is. A delegated handler would save an O(n) `.find().on()` per render
for 1–5 attachments — negligible benefit with added complexity.

---

### L8 — `renderDisplayAttachmentBadges` per-element closures (investigated; no fix)

**Investigated:** Each badge is created once and bound exactly once — no re-render cycle,
no accumulation. The closure captures the full `att` object (including a base64 thumbnail
data-URL), keeping it alive for the card's lifetime. Only 2 call sites, both on history-load
paths.

**Decision:** No delegation needed. Optional micro-improvement (extract 5 scalar fields from
`att` to drop the base64 reference) deferred.

---

### L9 — Four AJAX utility functions nested inside `chat_interface_readiness`

**File:** `chat.js` — `fetchUserDetail`, `saveUserDetail`, `fetchUserPreference`,
`saveUserPreference` (lines 528–588 original).

**Problem:** Four pure AJAX wrappers were defined inside `chat_interface_readiness()`, which
is 518 lines long and called once at DOM-ready. None of the four closed over any outer
variable — confirmed by reading all 61 lines. Being buried inside the init function made them
invisible at a glance and slightly inflated the function's apparent complexity.

**Fix:** Hoisted all four to module level immediately above `chat_interface_readiness()` with
a `// User Details and Preferences API functions` section comment. The original definitions
inside `chat_interface_readiness` were deleted. No call-site changes required — the 6 callers
at lines 253, 260, 593, 600, 607, 614 resolve via normal JavaScript hoisting and continue to
work identically.

---

## Files Modified

| File | Changes |
|------|---------|
| `interface/common.js` | H1, H3, H4, H5 fixes; L1, L2 hoists; M2 (`renderMermaidIfDetailsTagOpened` rewrite); M3 (`restoreCodeBlocks` reduce hoist); M5 (`removeEmTags` deleted); 3 new module-level guard vars; L4 canonical `escapeHtml` added; L5 canonical `fuzzyMatch` added |
| `interface/common-chat.js` | H2, H3, H6 fixes; dropdown close-on-outside-click 3-part fix; M1 (`scrollToBottom` guard + namespaces); M4 (height-lock reorder); M6 (`statusDiv` hoist); M7 (redundant dropdown init removed); 2 new module-level vars; L4 3 local escape copies deleted + `escapeDocHtml` → `escapeHtml`; L5 `_fuzzyMatch` copy deleted + call site updated; L6 local `hideSidebarOnMobileIfOpen` replaced with `WorkspaceManager.hideSidebarIfMobile()` delegation |
| `interface/interface.html` | H2: `data-bs-dismiss="modal"` → `data-dismiss="modal"` (Bootstrap 4.6 syntax) |
| `interface/file-browser-manager.js` | L3 4 bare `$(document).on('keydown')` merged into 1 namespaced unified handler; L4 `_escHtml` deleted + 6 call sites renamed to `escapeHtml`; L5 `_fuzzyMatch` copy deleted + 2 call sites in `_fuzzyMatchPath` updated |
| `interface/artefacts-manager.js` | L4 local `escapeHtml` definition deleted |
| `interface/tool-call-manager.js` | L4 DOM-based `_escapeHtml` deleted + 17 call sites renamed to `escapeHtml` |
| `interface/clarifications-manager.js` | L4 DOM-based `_escapeHtml` deleted + 9 call sites renamed to `escapeHtml` |
| `interface/cross-conversation-search.js` | L4 `_escapeHtml` deleted + 3 call sites renamed to `escapeHtml` |
| `interface/doubt-manager.js` | L4 `_doubtEscapeHtml` deleted + 2 call sites renamed to `escapeHtml` |
| `interface/pkb-manager.js` | L4 DOM-based `escapeHtml` definition deleted; calls unchanged (same name) |
| `interface/workspace-manager.js` | L6 `hideSidebarIfMobile` public method updated with `innerWidth` fallback; private `hideSidebarIfMobileOpen` replaced with 1-line delegate |
| `interface/chat.js` | L9 4 AJAX utility functions hoisted to module level above `chat_interface_readiness` |

---

## Key Invariants Preserved

- **Message index stability**: `initialCardCount + originalIndex` is equivalent to the prior
  live-query approach for all call paths including `renderCloseToSource` mid-list insertion.
  Delete/move/fork workflows via `/delete_message_pair`, `/fork_conversation`, and move
  endpoints are unaffected.
- **Dropdown close behavior**: Bootstrap's document-level outside-click dismiss event now
  bubbles correctly because `stopPropagation` is suppressed only when a dropdown is actually
  open.
- **Floating ToC clicks**: Delegated handler on the stable `$panel` element survives ToC
  content rebuilds during streaming without re-binding.
- **`checkScroll()` re-entrant**: `scrollToBottom` still runs `checkScroll()` unconditionally
  before the init guard, so calling it multiple times still updates button visibility.
- **`restoreCodeBlocks` size guard**: `expectedMaxSize` is computed from the same inputs as
  before; the guard threshold (2×) is unchanged.
- **`escapeHtml` entity set**: the canonical function escapes 5 entities (`& < > " '`) — a
  strict superset of all prior local copies. No existing output becomes less escaped.
- **`fuzzyMatch` algorithm**: byte-for-byte identical to both prior copies (including all
  scoring constants). No change in autocomplete or file-browser ranking behaviour.
- **File-browser Escape priority**: the merged handler applies the same priority ordering the
  original four handlers implied, but now enforces it correctly via
  `e.stopImmediatePropagation()`. Single-Escape behaviour is unchanged; the race that
  previously double-closed overlays + main modal is fixed.

---

## Related Documentation

- `features/rendering_performance/README.md` — earlier MathJax priority and deferred-render optimizations
- `features/math_streaming_reflow_fix/` — math-aware render gating, min-height stabilisation
- `features/toc_streaming_fix/` — floating ToC panel and streaming ToC updates
- `features/scroll_preservation/` — CSS scroll anchoring and anchor-based scroll restore
- `changelogs/AUTOSCROLL_REMOVAL_CHANGELOG.md` — removal of unwanted auto-scroll behaviors
