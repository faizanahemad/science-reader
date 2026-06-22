# Reading Overlay (Full-Screen Read View)

## Goal

Provide a focused, full-screen reading experience for assistant answer cards (main chat), doubt answer cards, and temp LLM assistant cards. The overlay fills the entire viewport, showing the rendered answer with section expand/collapse working natively, and a simple [X] close button at the top-right.

## User Decisions

| Question | Answer |
|---|---|
| Trigger | Compact ⋮ menu (compact mode, main chat cards) + right triple-dot vote menu (normal mode, main chat cards) + icon button in doubt/temp LLM card action rows |
| Font size | 0.9rem (up from 0.8rem default) |
| Width | Full screen, edge-to-edge |
| Temp LLM rendering | Clone rendered HTML as-is (no re-render pipeline) |
| Availability | Always (not gated to compact mode) |
| Interactive elements | Only native `<details>` section collapse; no extra buttons |
| Collapsed card behavior | Always show full content regardless of collapse state |

## Assumptions

- Overlay implemented as a full-viewport `position:fixed` div (not a Bootstrap modal) to avoid z-index/stacking conflicts.
- Content is extracted by cloning rendered HTML from the DOM — no re-parsing of raw text.
- For main chat cards: if `.more-text` is present (showMore ran), clone `.more-text`'s innerHTML to always get full content regardless of collapse state. Otherwise clone `.actual-card-text` directly.
- For doubt and temp LLM: clone `.card-body` HTML.
- Section state (which `<details>` are open/closed in the overlay) does not persist back to the DB.
- `#reading-overlay-body` is given classes `actual-card-text card-text` so existing markdown CSS applies.
- Dark mode respects `body.dark-mode` via a CSS rule.
- Escape key closes the overlay.
- Z-index 2100 — above all existing modals (highest found was 1095).
- The compact ⋮ menu `compact-proxy-read` item is always visible (no conditional hiding in populate handler) — useful for all message cards, not just assistant.
- The "Read Full Screen" vote menu item and doubt/temp LLM icon buttons appear only for assistant cards (not user/question cards), controlled at template-render time.

## Files Modified

| File | Change |
|---|---|
| `interface/style.css` | Add `#reading-overlay`, `#reading-overlay-close`, `body.reading-overlay-open`, dark-mode rule |
| `interface/interface.html` | Add `#reading-overlay` div before `</body>` |
| `interface/interface.js` | Add `openReadingOverlay()`, `closeReadingOverlay()`, close button handler, Escape key handler, compact proxy populate entry, compact proxy click handler |
| `interface/common-chat.js` | Add `compact-proxy-read` item to compact ⋮ menu template (line ~2554) |
| `interface/common.js` | Add "Read Full Screen" item in `initialiseVoteBank()` vote dropdown |
| `interface/doubt-manager.js` | Add read icon button to assistant doubt card actions template |
| `interface/temp-llm-manager.js` | Add read icon button to assistant temp LLM card actions template |
| `documentation/features/compact_view/README.md` (or existing compact doc) | Document new reading overlay feature |

## Implementation Tasks

### Task 1 — CSS (`interface/style.css`)
Add:
- `#reading-overlay` — `position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:2100; background:#fff; overflow-y:auto; padding:1.5rem 2rem; font-size:0.9rem; box-sizing:border-box;`
- `#reading-overlay-close` — `position:fixed; top:0.75rem; right:1rem; z-index:2101; background:transparent; border:none; font-size:1.5rem; cursor:pointer; line-height:1; padding:0.1rem 0.4rem;`
- `body.reading-overlay-open { overflow:hidden; }`
- `body.dark-mode #reading-overlay { background:#1a1a1a; color:#e0e0e0; }`

### Task 2 — HTML (`interface/interface.html`)
Add before `</body>`:
```html
<!-- ===== Reading Overlay ===== -->
<div id="reading-overlay" style="display:none;" role="dialog" aria-modal="true" aria-label="Full screen reading view">
    <button id="reading-overlay-close" title="Close (Esc)" aria-label="Close">
        <i class="bi bi-x-lg"></i>
    </button>
    <div id="reading-overlay-body" class="actual-card-text card-text"></div>
</div>
<!-- ===== /Reading Overlay ===== -->
```

### Task 3 — Core JS (`interface/interface.js`)
Add `openReadingOverlay($triggerElem)` and `closeReadingOverlay()` functions, plus event handlers:
- Extract content based on card type
- Inject into `#reading-overlay-body`
- Show overlay, add `reading-overlay-open` to body, scroll overlay to top
- Close handler wires to `#reading-overlay-close` click and `Escape` keydown

### Task 4 — Compact menu template (`interface/common-chat.js`)
After current last item (`compact-proxy-move-pair`, line 2554), add:
```html
<div class="dropdown-divider"></div>
<a class="dropdown-item compact-proxy-read" href="#"><i class="bi bi-arrows-fullscreen mr-2"></i>Read Full Screen</a>
```

### Task 5 — Compact populate + click handler (`interface/interface.js`)
- In populate handler (line ~245), no conditional needed — `compact-proxy-read` is always shown.
- Add proxy click handler: `$('.compact-proxy-read')` → calls `openReadingOverlay($(this).closest('.message-card'))`.

### Task 6 — Vote menu (`interface/common.js`)
In `initialiseVoteBank()` after the word count item, add a "Read Full Screen" `<a>` item with class `reading-overlay-trigger` and append it to `voteDropdown` with a divider, only for assistant cards (`disable_voting === false`).

### Task 7 — Doubt card button (`interface/doubt-manager.js`)
In `createDoubtChatCard()`, for `!isUser`, add a read button to the action buttons:
```html
<button class="btn btn-sm p-1 doubt-read-btn" title="Read Full Screen"><i class="bi bi-arrows-fullscreen"></i></button>
```
Wire up in the doubt manager's event handlers section.

### Task 8 — Temp LLM card button (`interface/temp-llm-manager.js`)
In `addMessageToChat()`, for `!isUser`, add read button to `.temp-llm-card-actions`:
```html
<button class="temp-llm-read-btn btn btn-sm p-1" title="Read Full Screen"><i class="bi bi-arrows-fullscreen"></i></button>
```
Wire up in the temp LLM manager's event handlers.

## Alternatives Considered

- **Bootstrap modal** — rejected because it stacks awkwardly over other modals (doubt modal, temp LLM modal are already Bootstrap modals). A fixed-position div avoids all stacking complexity.
- **Re-rendering temp LLM via full pipeline** — rejected per user choice; cloning rendered HTML is simpler.
- **Separate reading-mode font/theme** — rejected per user choice; inherit existing theme.
