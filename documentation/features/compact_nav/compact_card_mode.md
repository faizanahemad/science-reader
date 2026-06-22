# Compact Mode — Message Card Header Compaction

## User Requirements

The user asked for a "compact mode" that makes the chat interface more information-dense. Across several sessions the following requirements were specified:

### Navbar / Toolbar
- Hide the full desktop toolbar row in compact mode (already existed via `body.compact-nav` CSS).
- Show a floating gear button (fixed top-right) instead.

### Message Card Headers
The full card header is too busy for dense reading. In compact mode:

1. **Hide from the LEFT header div** (keep only the sender name "You" / "Assistant"):
   - Checkbox (`.history-message-checkbox`)
   - Reference badge (`.message-ref-badge`)
   - The entire "Message Actions" left triple-dot dropdown (`.message-action-dropdown`)
   - Has-doubts indicator button (`.has-doubts-btn`)

2. **Hide from the RIGHT header div**:
   - Scroll-to-bottom button (`.scroll-to-bottom-btn`)
   - Show/hide collapse toggle (`.header-hide-toggle`)
   - Copy button (`.copy-btn-header`)
   - Pin button (`.pin-message-btn`)
   - The entire "More Options" right triple-dot dropdown (`.vote-menu-dropdown-container`)

3. **Replace both triple-dot menus with one merged compact dropdown** (`.compact-message-menu-container`) containing:
   - Word count (from right vote menu)
   - Edit Message (from right vote menu)
   - --- divider ---
   - Bottom / scroll-to-bottom
   - Show / Hide (collapse toggle)
   - Copy
   - --- divider ---
   - Show Doubts
   - Ask New Doubt
   - --- divider ---
   - Fork from here
   - --- divider ---
   - Delete Message (danger)
   - Delete Pair (danger)
   - Move Pair as Doubt (warning, conditional)

   **Not included** in the compact menu (removed from left menu as well): Move Up, Move Down, Artefacts.

### Typography and Spacing
- Line height: `1.2` (down from inherited Bootstrap `1.5`) on `.message-card .card-body`.
- Remove card margins: `margin: 0 !important` on `.message-card`.
- Remove card border: `border: none !important` on `.message-card`.

### Table of Contents
- In compact mode the TOC should be **collapsed** (body hidden, header bar visible showing "Table of Contents [Show N]") — **not fully hidden**.
- The user should still be able to click "Show" to expand the TOC even while in compact mode.
- When compact mode is disabled the TOC should re-expand to its previous state.

---

## Architecture Overview

### Toggle Mechanism

| File | Location | Role |
|---|---|---|
| `interface/interface.html` | `#gear-compact-nav-toggle`, `#gear-floating-compact-toggle` | Gear menu items that toggle compact mode |
| `interface/interface.js` | ~line 191 | Click handler: flips `#settings-compact_nav` checkbox, triggers `change` |
| `interface/chat.js` | `applyCompactNav(enabled)` ~line 10 | Adds/removes `body.compact-nav`; collapses/restores TOC bodies |
| `interface/chat.js` | `setModalFromState(state)` ~line 732 | Restores compact state from localStorage on page load |
| `interface/style.css` | Lines 10-100 | CSS rules keyed on `body.compact-nav` |

State is persisted via `chatSettingsState.compact_nav` in localStorage (keyed per tab: `${tab}chatSettingsState`).

### CSS-Driven Hiding

All header element hiding in compact mode is **purely CSS** — no JS needed for element visibility. This means new cards added to the DOM (during streaming or conversation load) automatically get the correct compact appearance without any per-card JS call.

```
body.compact-nav .message-card .{class} { display: none !important; }
```

The `!important` is required to override Bootstrap's `d-inline-block` utility class (which itself uses `!important`). Our rule wins because it has higher CSS specificity (`[0,3,1]` vs Bootstrap's `[0,1,0]`).

### Compact Menu Container

The merged dropdown is appended to the right side of every card header by the static template in `common-chat.js`. It is always present in the DOM but hidden with `display: none` in non-compact mode. In compact mode `display: inline-block !important` reveals it.

**Critical**: The container div must NOT have Bootstrap's `d-inline-block` class. That class applies `display: inline-block !important` which would override the `display: none` base rule, making the compact button permanently visible even in non-compact mode.

```html
<!-- correct — no d-inline-block -->
<div class="dropdown compact-message-menu-container">
  <button class="... compact-message-menu-toggle" data-toggle="dropdown">⋮</button>
  <div class="dropdown-menu compact-message-dropdown-menu">
    <span class="dropdown-item-text compact-word-count" ...></span>
    <div class="dropdown-divider compact-word-count-divider"></div>
    <a class="dropdown-item compact-proxy-edit-message" href="#">...</a>
    ... etc ...
  </div>
</div>
```

---

## Compact Menu Populate Handler

The compact menu items are populated **dynamically** on every click of `.compact-message-menu-toggle` before Bootstrap opens the dropdown. A single document-level delegated handler (`interface/interface.js` ~line 201) runs synchronously when the toggle button is clicked.

### What it populates

| Item | Logic |
|---|---|
| Word count | Computed fresh from `.actual-card-text.split(/\s+/)`. NOT read from the hidden `.vote-dropdown-menu` — see below why. |
| Edit Message | Visible when `initialiseVoteBank` has added it to `.vote-dropdown-menu`; toggled via `hasEdit`. |
| After-edit divider | Only shown when Edit Message itself is shown (NOT when word count alone is present — avoids double dividers). |
| Bottom | Shown only when `.scroll-to-bottom-btn[0].style.display !== 'none'` — i.e., `decorateMessageCardNav` has activated it (messages > 300 chars). Checks **inline style**, not computed style, to avoid false negatives from the CSS `!important` rule hiding the button in compact mode. |
| Show/Hide | Same inline-style check on `.header-hide-toggle`. When active, its current text (`[hide]` or `[show]`) is reflected in the menu item. |
| Move Pair as Doubt | Mirrors the original item's index-based `display:none` via `.is(':hidden')`. |

### Why word count is computed directly

The populate handler fires at document level via jQuery event delegation. Bootstrap 4's `click.bs.dropdown.data-api` handler is also at document level but was registered BEFORE our DOM-ready handler (Bootstrap JS loads before `interface.js` runs). jQuery fires document-level handlers in registration order. Therefore Bootstrap opens the dropdown FIRST, then our populate handler runs. The browser defers painting until the JS call stack empties, so users never see the stale state — but reading from `.vote-dropdown-menu` was found to sometimes return an empty result. Computing from `.actual-card-text` is immune to this race.

### Proxy click handlers

Every compact menu item has a corresponding `compact-proxy-*` delegated handler that `trigger('click')`s the original (CSS-hidden) element in the same card. The original event delegation in `common.js` and `common-chat.js` fires unchanged — no duplication of business logic.

```js
$(document).on('click', '.compact-proxy-delete-message', function(e) {
    e.preventDefault();
    $(this).closest('.message-card').find('.delete-message-button').trigger('click');
});
```

---

## Table of Contents Compact Collapse

### Desired behaviour

| State | TOC visibility |
|---|---|
| Compact mode ON + message expanded | Container visible, body hidden, button says "Show (N)" |
| Compact mode ON + message collapsed | Container hidden (message body is hidden) |
| Compact mode OFF + message expanded | Container visible, body visible (normal state) |
| Compact mode OFF + message collapsed | Container hidden |

### How the collapse works

Two helpers in `common.js` (defined after `renderMessageToc`):

**`_tocCollapseForCompact($container)`**
1. Shows `.message-toc-container`
2. Hides `.message-toc-body` (the list)
3. Sets `.message-toc-toggle` text to `"Show (N)"`
4. Sets `data-toc-expanded="false"` on `.message-toc`
5. Sets `data-compact-auto-collapsed="true"` — marker for the restore helper

**`_tocRestoreFromCompact($container)`**
1. Only acts if `data-compact-auto-collapsed === "true"` (distinguishes auto-collapse from user-intentional click)
2. Shows `.message-toc-body`
3. Sets button text to `"Hide"`
4. Sets `data-toc-expanded="true"`
5. Removes the marker attribute

### Call sites

| Call site | File | What it does |
|---|---|---|
| `renderMessageToc()` | `common.js` ~L328 | After building HTML: if compact mode, call `_tocCollapseForCompact`. If message is collapsed, just set HTML without showing. |
| `decorateMessageCardNav()` | `common.js` ~L2404 | If compact mode + message expanded: call `_tocCollapseForCompact`. If message hidden: hide container. |
| `applyConversationUIState()` show-branch | `common.js` ~L4387 | If compact mode: call `_tocCollapseForCompact`. Else: show container normally. |
| `applyCompactNav(true)` | `chat.js` ~L16 | Iterates all existing `.message-toc-container`s, calls `_tocCollapseForCompact`. |
| `applyCompactNav(false)` | `chat.js` ~L23 | Iterates all containers, calls `_tocRestoreFromCompact` for non-collapsed messages. |

Message-collapse hide path (`.show-more` delegated handler in `common.js`) is **unchanged** — it already calls `.hide()` on the container when the message body collapses. This is correct in all modes.

### Tab-based messages

Tab-pane messages have one `.message-toc-container` per tab pane (prepended inside the `.tab-pane` element). The card-level container is cleared and hidden. The queries `$card.find('.message-toc-container')` and `$('.message-toc-container')` both find tab-pane containers. The helpers operate identically on them.

---

## Page-Load State Restoration Bug Fix

### Problem

On page load, `initializeSettingsState()` correctly calls `applyCompactNav(true)`. Shortly after, Bootstrap fires `shown.bs.tab` during its initialization. That event handler calls:

```js
const defaultsForTab = getPersistedSettingsState() || computeDefaultStateForTab(tab);
setModalFromState(defaultsForTab);
```

`computeDefaultStateForTab()` does NOT include a `compact_nav` key. So `setModalFromState` received `compact_nav: undefined` and called `applyCompactNav(!!undefined)` = `applyCompactNav(false)`, stripping `body.compact-nav`.

Cards then rendered without the class → two dots visible instead of one.

### Fix (`chat.js` `setModalFromState`)

Guard `applyCompactNav` with an `hasOwnProperty` check:

```js
if (Object.prototype.hasOwnProperty.call(state, 'compact_nav')) {
    $('#settings-compact_nav').prop('checked', !!state.compact_nav);
    applyCompactNav(!!state.compact_nav);
}
```

`computeDefaultStateForTab` does not have `compact_nav` → the call is skipped. `getPersistedSettingsState()` includes it → the call fires correctly. All manual toggles (checkbox change, gear menu click) pass a full state object → unaffected.

---

## CSS Rules Summary

All rules live in `interface/style.css` inside the `/* Compact Nav — message card header compaction */` section.

```css
/* Base: merged menu always hidden */
.compact-message-menu-container { display: none; }

/* In compact mode: hide header controls */
body.compact-nav .message-card .history-message-checkbox,
body.compact-nav .message-card .message-ref-badge,
body.compact-nav .message-card .message-action-dropdown,
body.compact-nav .message-card .has-doubts-btn,
body.compact-nav .message-card .scroll-to-bottom-btn,
body.compact-nav .message-card .header-hide-toggle,
body.compact-nav .message-card .copy-btn-header,
body.compact-nav .message-card .pin-message-btn,
body.compact-nav .message-card .vote-menu-dropdown-container {
    display: none !important;
}

/* Show merged menu */
body.compact-nav .message-card .compact-message-menu-container {
    display: inline-block !important;
}

/* Typography and spacing */
body.compact-nav .message-card .card-body { line-height: 1.2; }
body.compact-nav .message-card { margin: 0 !important; border: none !important; }
```

All rules are mirrored in the auto-mobile `@media (max-width: 768px) and (pointer: coarse) and (max-height: 768px)` block using `body:not(.compact-nav-off)` so touch devices get compact mode automatically but users who have explicitly opted out are excluded.

---

## Streaming Compatibility

Streaming cards are created via `ChatManager.renderMessages(conversationId, [serverMessage], ...)` — the **same template path** as history cards. They receive `compact-message-menu-container` from the template and CSS applies reactively once `body.compact-nav` is set.

After streaming completes, `initialiseVoteBank(card, answer, ...)` runs (`common-chat.js` ~L1831) populating the vote dropdown and wiring the copy button. The compact menu's populate handler reads word count from `.actual-card-text` (not the vote menu) so it works correctly the first time the compact dot is clicked, even before `initialiseVoteBank` has run.

The document-level delegated populate handler (`$(document).on('click', '.compact-message-menu-toggle', ...)`) covers all current and future cards including streaming cards — no per-card binding needed.

---

## Files Modified

| File | What changed |
|---|---|
| `interface/common-chat.js` | Added `message-action-dropdown` class to left dropdown wrapper; added `vote-menu-dropdown-container` class to right dropdown wrapper; added full `compact-message-menu-container` dropdown HTML to card header template |
| `interface/style.css` | Compact card header hiding rules, line-height, margin, border rules (all in compact-nav section) |
| `interface/interface.js` | Populate handler for compact menu; 10 proxy click handlers; guard on `applyCompactNav` in `setModalFromState` |
| `interface/chat.js` | `applyCompactNav`: uses `_tocCollapseForCompact`/`_tocRestoreFromCompact` instead of `.hide()`/`.show()`; `setModalFromState` `hasOwnProperty` guard |
| `interface/common.js` | `_tocCollapseForCompact()` and `_tocRestoreFromCompact()` helper functions; updated `renderMessageToc`, `decorateMessageCardNav`, `applyConversationUIState` to use collapse helpers |

---

## Commits

| Commit | Summary |
|---|---|
| `43649ac` | Initial implementation: merged compact menu, line-height 1.2, margin/border removal, TOC hiding via `applyCompactNav` |
| `d32b517` | Three bug fixes: page-load class reset (`shown.bs.tab`), always-visible compact menu (`d-inline-block`), TOC page-load visibility |
| `ab7a0ba` | Compact menu populate handler fixes: double divider (S2-B), show/hide always visible (S2-C), bottom always visible (S2-D) |
| `8964766` | Word count computed from `.actual-card-text`; TOC collapsed not hidden (helpers + all call sites) |

---

## Known Behaviour Notes

- **Short messages (≤ 300 chars)**: `decorateMessageCardNav` is not called (intentional). Bottom and Show/Hide items are hidden in the compact menu because their underlying controls were never activated. Only Copy, doubts, delete, and fork items appear.
- **User cards**: Edit Message appears in the compact menu. `initialiseVoteBank` adds it to all cards regardless of sender, so it is available for editing user messages.
- **Manual TOC collapse in compact mode**: If the user clicks "Show" to expand the TOC while compact mode is on, `data-compact-auto-collapsed` remains set. When compact mode is later disabled, `_tocRestoreFromCompact` checks the marker — since the user manually expanded it the marker is still there, so `_tocRestoreFromCompact` expands the body (which was already expanded) — a harmless no-op.
- **Compact mode on mobile**: Auto-enabled via `@media (max-width: 768px) and (pointer: coarse) and (max-height: 768px)` using `body:not(.compact-nav-off)`. Users can opt out by explicitly toggling compact mode off (which sets `body.compact-nav-off`).

---

## Reading Overlay (Full-Screen Read View)

A full-viewport reading mode for individual assistant answer cards, doubt answer cards, and temp LLM assistant cards. Designed for focused, distraction-free reading of long responses.

### Behaviour

- The overlay fills 100vw × 100vh (`position: fixed`, `z-index: 2100`) and is scrollable.
- Font size is `0.9rem` (slightly larger than the default card `0.8rem`).
- A single `[X]` button is fixed at the top-right (`z-index: 2101`). Pressing Escape also closes.
- `body.reading-overlay-open` is added while open, locking background scroll.
- Section `<details>` expand/collapse works natively — clicking a summary toggles its section. State is NOT persisted back to the DB.
- No other interactive elements exist inside the overlay — pure reading.
- Dark mode is respected via `body.dark-mode #reading-overlay { background: #1e1e1e; color: #ddd; }`.

### Content extraction

Content is cloned from the already-rendered DOM:

| Card type | Source element | Full-content handling |
|---|---|---|
| Main chat (`.message-card`) | `.actual-card-text .more-text` if present; else `.actual-card-text` | `.more-text` always contains the full rendered HTML regardless of whether the card is collapsed via `showMore()`. |
| Doubt answer (`.doubt-conversation-card`) | `.card-body` | Cloned directly; `doubt-answer-collapsed` CSS is not inherited in the overlay. |
| Temp LLM (`.temp-llm-card`) | `.card-body` | Cloned directly. No re-render — temp LLM cards use `marked.parse()` and have no section collapse. |

### Entry points

| Card type | Mode | Trigger element |
|---|---|---|
| Main chat | Compact mode | `compact-proxy-read` item in the compact `⋮` dropdown |
| Main chat | Normal mode | "Read Full Screen" item in the right triple-dot vote menu (`.reading-overlay-trigger`), assistant cards only |
| Doubt answer | Both modes | `⤢` icon button (`.doubt-read-btn`) in `.doubt-card-actions`, assistant cards only |
| Temp LLM | Both modes | `⤢` icon button (`.temp-llm-read-btn`) in `.temp-llm-card-actions`, assistant cards only |

### Files modified

| File | Change |
|---|---|
| `interface/style.css` | Added `#reading-overlay`, `#reading-overlay-close`, `body.reading-overlay-open`, dark-mode rules |
| `interface/interface.html` | Added `#reading-overlay` div (with `#reading-overlay-body`) before `</body>` |
| `interface/interface.js` | Added `window.openReadingOverlay()`, `window.closeReadingOverlay()`, close button handler, Escape keydown handler, `compact-proxy-read` in populate handler, `compact-proxy-read` click handler |
| `interface/common-chat.js` | Added `compact-proxy-read` + `.compact-read-divider` items at end of `.compact-message-dropdown-menu` template |
| `interface/common.js` | Added `readFullScreenItem` in `initialiseVoteBank()` for assistant cards (`!disable_voting`), appended at end of vote dropdown |
| `interface/doubt-manager.js` | Added `readBtn` template variable for `!isUser` assistant cards; added `#doubt-chat-messages .doubt-read-btn` click handler |
| `interface/temp-llm-manager.js` | Added `temp-llm-read-btn` button inside `temp-llm-card-actions` for `!isUser`; added `#temp-llm-messages .temp-llm-read-btn` click handler |
