# Reading Overlay — Full-Screen Read View

## Motivation and Background

Long assistant answers, doubt answers, and temp LLM responses are rendered inside constrained Bootstrap card bodies. Even with compact mode reducing chrome, the card width and surrounding UI elements limit reading space.

The reading overlay provides a full-viewport, distraction-free reading experience for any message card. The user opens it from the card's action menu, reads the full rendered content with native section expand/collapse working, and closes with the `[X]` button or `Escape`.

## User-Facing Behaviour

- Fills 100vw × 100vh on top of everything else (`z-index: 2100`).
- Font size `0.9rem` (slightly larger than the default card `0.8rem`).
- Background matches the current light/dark theme.
- Single `[X]` button fixed at the top-right. `Escape` also closes.
- Body scroll is locked (`body.reading-overlay-open { overflow: hidden }`) while the overlay is open.
- **Always shows full content** — if the source card is collapsed via `[show]/[hide]`, the overlay still shows the entire message.
- **Section `<details>` expand/collapse** works natively inside the overlay. Browser handles it; state is NOT persisted back to the DB (independent read view).
- No other interactive controls — pure reading surface.

## Entry Points

| Card type | Mode | Element |
|---|---|---|
| Main chat (`.message-card`) | Compact mode | "Read Full Screen" item at the bottom of the compact `⋮` dropdown (`.compact-proxy-read`) |
| Main chat (`.message-card`) | Normal mode | "Read Full Screen" item at the bottom of the right triple-dot vote menu (`.reading-overlay-trigger`) |
| Doubt answer (`.doubt-conversation-card`) | Both | `⤢` fullscreen icon button (`.doubt-read-btn`) in the card header action row, between bookmark and copy buttons |
| Temp LLM (`.temp-llm-card`) | Both | `⤢` fullscreen icon button (`.temp-llm-read-btn`) in `.temp-llm-card-actions`, between copy button and end |

The entry point is available for **all** message cards (user and assistant), not limited to assistant cards.

## Content Extraction Logic

Content is cloned from the already-rendered DOM — no re-parsing of raw text.

### Main chat cards

After streaming, `renderInnerContentAsMarkdown` hides `.actual-card-text` (`#message-render-space`) and places all rendered content — including the `.more-text` wrapper created by `showMore()` — into the **sibling** `#message-render-space-md-render`. For server-loaded answers, the same content lives inside `.actual-card-text`. The extraction logic handles both:

```
1. .actual-card-text .more-text          — server-loaded answers with showMore() wrapping
2. #message-render-space-md-render .more-text  — streaming answers with showMore() wrapping
3. .actual-card-text (direct)            — short server-loaded cards (text ≤ 300 chars, no showMore)
4. #message-render-space-md-render (direct)    — short streaming cards
```

`.more-text` always contains the **full** rendered HTML regardless of whether the card is collapsed or expanded at the time of opening. The wrapper's `.less-text` stub and `[show/hide]` link are not extracted.

### Doubt and temp LLM cards

`.card-body` is cloned directly. The `doubt-answer-collapsed` CSS class (which hides `.card-body` when the doubt card is collapsed) is not inherited in the overlay, so the full content is always visible.

Temp LLM cards use `marked.parse()` directly and have no section collapse structure. Their rendered card body HTML is cloned as-is.

## Architecture

### HTML (`interface/interface.html`)

A single `#reading-overlay` div appended before `</body>`, hidden by default:

```html
<div id="reading-overlay" style="display:none;" role="dialog" aria-modal="true" aria-label="Full screen reading view">
    <button id="reading-overlay-close" title="Close (Esc)" aria-label="Close">
        <i class="bi bi-x-lg"></i>
    </button>
    <div id="reading-overlay-body" class="actual-card-text card-text"></div>
</div>
```

`#reading-overlay-body` has classes `actual-card-text card-text` so that all existing markdown and card CSS rules apply to the content without modification.

`#reading-overlay-close` is `position: fixed` at `top: 0.6rem; right: 0.8rem` so it stays visible regardless of scroll position within the overlay.

### CSS (`interface/style.css`)

```css
#reading-overlay {
    position: fixed; top: 0; left: 0;
    width: 100vw; height: 100vh;
    z-index: 2100;
    background: #fff;
    overflow-y: auto;
    padding: 0.75rem 1rem 1.5rem 1rem;
    font-size: 0.9rem;
    box-sizing: border-box;
}
#reading-overlay-close {
    position: fixed; top: 0.6rem; right: 0.8rem;
    z-index: 2101;
    background: transparent; border: none;
    font-size: 1.4rem; cursor: pointer;
    color: #555;
}
body.reading-overlay-open { overflow: hidden; }
body.dark-mode #reading-overlay { background: #1e1e1e; color: #ddd; }
body.dark-mode #reading-overlay-close { color: #bbb; }
```

Z-index 2100 sits above all existing modals (highest previously was the Answer Edit Diff Modal at z-index 1095).

### JavaScript (`interface/interface.js`)

Two global functions defined before `interface_readiness()`:

**`window.openReadingOverlay($triggerElem)`**
- Accepts any jQuery element; navigates up to the nearest card wrapper via `.closest()`
- Extracts content HTML using the 4-step fallback described above
- Injects HTML into `#reading-overlay-body`, shows the overlay, adds `reading-overlay-open` to body, scrolls to top
- Silent no-op if no content found

**`window.closeReadingOverlay()`**
- Hides overlay, empties `#reading-overlay-body`, removes `reading-overlay-open` from body

Event handlers inside `interface_readiness()`:
- `#reading-overlay-close` click → `closeReadingOverlay()`
- `keydown.readingOverlay` Escape → `closeReadingOverlay()` when overlay visible

### Compact menu template (`interface/common-chat.js`)

`compact-proxy-read` item added at the bottom of `.compact-message-dropdown-menu`:

```html
<div class="dropdown-divider compact-read-divider"></div>
<a class="dropdown-item compact-proxy-read" href="#">
    <i class="bi bi-arrows-fullscreen mr-2"></i>Read Full Screen
</a>
```

The populate handler (`interface/interface.js`) sets this item and its divider to always visible (`.show()`). The click handler calls `window.openReadingOverlay($(this).closest('.message-card'))`.

### Normal-mode vote dropdown (`interface/common.js`)

In `initialiseVoteBank()`, a `readFullScreenItem` is appended after all existing items for all cards (user and assistant) using a closure over `cardElem`:

```javascript
var readFullScreenItem = $('<a class="dropdown-item reading-overlay-trigger" href="#">
    <i class="bi bi-arrows-fullscreen mr-2"></i>Read Full Screen
</a>');
readFullScreenItem.click(function(e) {
    ...
    window.openReadingOverlay(cardElem);
});
voteDropdown.append($('<div class="dropdown-divider"></div>'), readFullScreenItem);
```

### Doubt card button (`interface/doubt-manager.js`)

`readBtn` template variable added for `!isUser` assistant doubt cards only:

```javascript
const readBtn = !isUser
    ? `<button class="btn btn-sm p-1 doubt-read-btn" title="Read Full Screen">
           <i class="bi bi-arrows-fullscreen"></i>
       </button>`
    : '';
```

Placed between `${bookmarkBtn}` and the copy button in the card header template. Click handler:

```javascript
$(document).off('click', '#doubt-chat-messages .doubt-read-btn')
    .on('click', '#doubt-chat-messages .doubt-read-btn', function(e) {
        window.openReadingOverlay($(this).closest('.doubt-conversation-card'));
    });
```

### Temp LLM card button (`interface/temp-llm-manager.js`)

`temp-llm-read-btn` injected into `.temp-llm-card-actions` for `!isUser` cards:

```javascript
${!isUser ? '<button class="temp-llm-read-btn btn btn-sm p-1" title="Read Full Screen">
    <i class="bi bi-arrows-fullscreen"></i>
</button>' : ''}
```

Click handler wired alongside the existing copy button handler.

### Dark mode (`interface/dark-mode.css`)

Bootstrap 4's `.btn { color: #212529 }` is an explicit element-level rule that overrides any inherited `color` from `.card-header`. Without an explicit override, `.doubt-read-btn` and `.temp-llm-read-btn` icons render as near-black on the `#21262d` card header — invisible. Fixed with:

```css
body.dark-mode .doubt-read-btn { color: #c9d1d9; }
body.dark-mode #temp-llm-modal .temp-llm-read-btn { color: #8b949e; }
```

Colors match those already set on their respective `.card-header` parents.

## Known Design Decisions

1. **Fixed div, not Bootstrap modal** — avoids z-index/stacking issues with existing Bootstrap modals (doubt modal, temp LLM modal are already at ~1050). Using `position: fixed` with a custom high z-index is simpler and has no side effects.

2. **Clone rendered DOM, not re-render** — avoids needing to run the full `renderInnerContentAsMarkdown` pipeline (MathJax, section processing, ToC, streaming swap) a second time. The already-rendered HTML is sufficient since `<details>` section collapse is handled natively by the browser.

3. **`.actual-card-text card-text` on the body div** — re-uses all existing markdown and card CSS rules without duplication.

4. **Section state not persisted** — toggling `<details>` in the overlay is ephemeral. The overlay is a read view; write-back would require re-syncing with `persistSectionState()` calls and adds complexity for minimal benefit.

5. **No ToC widget** — a floating Table of Contents in an already-fullscreen view would add no navigation value.

6. **`body.reading-overlay-open`** — locking body scroll on `<body>` directly (rather than `overflow: hidden` on the overlay) handles mobile safari's rubber-band scroll correctly.

## Files Modified

| File | Change |
|---|---|
| `interface/interface.html` | Added `#reading-overlay` div before `</body>` |
| `interface/interface.js` | `window.openReadingOverlay()`, `window.closeReadingOverlay()`, close + Escape handlers, `compact-proxy-read` populate + click handler |
| `interface/common-chat.js` | `compact-proxy-read` + `.compact-read-divider` at end of compact menu template |
| `interface/common.js` | `readFullScreenItem` in `initialiseVoteBank()` for all cards, appended at end of vote dropdown |
| `interface/doubt-manager.js` | `readBtn` template variable for assistant cards; `.doubt-read-btn` click handler |
| `interface/temp-llm-manager.js` | `temp-llm-read-btn` in card actions for assistant cards; `.temp-llm-read-btn` click handler |
| `interface/style.css` | `#reading-overlay`, `#reading-overlay-close`, `body.reading-overlay-open`, dark-mode rules |
| `interface/dark-mode.css` | `.doubt-read-btn` and `.temp-llm-read-btn` color overrides for dark mode |
| `documentation/features/compact_nav/compact_card_mode.md` | "Reading Overlay" section appended |
