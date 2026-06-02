# Compact Nav — Mobile Viewport Height Maximization

## Motivation and Background

On mobile devices (particularly iPhones), vertical screen real estate is precious. The chat interface had a row of action buttons (Download Transcript, Share, Docs, Global Docs, New Temp Chat, plus extension extraction buttons) sitting between the top navbar and the chat messages area. This row consumed ~35px of vertical space, reducing the visible chat area on already-constrained mobile viewports.

Additionally, the app runs in multiple contexts with varying viewport characteristics:

| Context | Width | Height | Pointer | Expected Behavior |
|---|---|---|---|---|
| iPhone (mobile browser) | Low (<768px) | Low (<768px) | coarse (touch) | Compact / mobile layout |
| Desktop browser | High (>768px) | High | fine (mouse) | Full desktop layout |
| Sidebar extension (desktop) | Low (<768px) | High (>700px) | fine (mouse) | Desktop layout (height is fine) |
| iframe extension (desktop) | Low (<768px) | High | fine (mouse) | Desktop layout |
| iPad / tablet portrait | Low (<768px) | High (>768px) | coarse (touch) | Desktop layout (tall viewport) |

A simple `max-width` media query incorrectly triggered mobile layout in sidebar/iframe contexts where width is narrow but vertical space is plentiful. The solution needed to distinguish true mobile phones from narrow-but-tall desktop panels.

## What Changed

### 1. Action Buttons Moved to Navbar Dropdown (Mobile Only)

The doc-action row below the top navbar was split into two presentations:

- **Desktop**: Original row remains inside `#mainView` (visible via `d-none d-md-flex`), containing all buttons including extension extraction buttons (Page, DOM, OCR, Full Page OCR, Extract Comments, Refresh, Multi-tab).
- **Mobile**: A `⋮` (vertical ellipsis) dropdown added to the top navbar (`#pdf-details-tab`) before the Logout item. Contains only: Download Transcript, Share Chat, Docs, Global Docs, New Temp Chat. Extension buttons are excluded from mobile — they are desktop-only.

The mobile dropdown items use `mob-*` prefixed IDs (`mob-get-chat-transcript`, `mob-share-chat`, etc.) and proxy clicks to the desktop buttons via jQuery `.trigger('click')`, so all existing JS handlers work without modification.

### 2. Smart Mobile Detection via Combined Media Queries

Instead of a pure `max-width` breakpoint, mobile layout now requires ALL three conditions:

```css
@media (max-width: 768px) and (pointer: coarse) and (max-height: 768px) {
    /* True mobile styles */
}
```

- `max-width: 768px` — narrow viewport
- `pointer: coarse` — touch device (phones, tablets)
- `max-height: 768px` — short viewport (phones, not tablets)

These breakpoint values are documented as constants at the top of `style.css`:

```
MOBILE_MAX_WIDTH:  768px
MOBILE_MAX_HEIGHT: 768px
MOBILE_MIN_HEIGHT_INVERSE: 769px  (MOBILE_MAX_HEIGHT + 1)
```

To change the mobile threshold, find-replace these values throughout the file.

### 3. Narrow-but-Not-Mobile Overrides

Two CSS blocks ensure desktop behavior in sidebar/iframe/tablet contexts:

**Fine pointer (desktop mouse)** — any narrow window with a mouse gets desktop layout:
```css
@media (max-width: 767.98px) and (pointer: fine) { ... }
```

**Tall touch device (tablet portrait)** — narrow + touch but tall viewport:
```css
@media (max-width: 767.98px) and (min-height: 769px) and (pointer: coarse) { ... }
```

Both overrides:
- Force-show the desktop doc-action row (`display: flex !important`)
- Force-hide the mobile navbar dropdown (`display: none !important`)
- Set explicit heights on `#chat-assistant`, `#chat-assistant-sidebar` to `calc(100vh - 35px)` and `#mainView` to `height: 100%` — preventing a layout gap where neither mobile nor desktop height rules applied

### 4. "Compact Nav" User Setting

For devices where the automatic detection doesn't match user preference (e.g., a phone with a tall-enough viewport that doesn't trigger mobile mode), a **Compact Nav** toggle is available in Chat Settings > Basic Options.

When enabled, it forces the mobile navbar-dropdown layout regardless of viewport size by adding `body.compact-nav` CSS class.

- **Setting name**: Compact Nav
- **Checkbox ID**: `#settings-compact_nav`
- **State key**: `compact_nav` (boolean, default `false`)
- **Persistence**: localStorage per-device, survives page reloads
- **Immediate effect**: Applies on toggle without closing the modal

CSS rules for `body.compact-nav`:
```css
body.compact-nav #mainView > .d-none.d-md-flex,
body.compact-nav #mainView > .row.d-none.d-md-flex {
    display: none !important;
}
body.compact-nav #chat-actions-nav.d-md-none {
    display: block !important;
}
```

## UI Details

### Mobile Navbar Dropdown

The dropdown appears as a `⋮` icon between the Prep-Chat tab and the Logout link in the top navbar. Items:

1. Download Transcript (icon: download)
2. Share Chat (icon: share-alt)
3. ---divider---
4. Docs (icon: file) — opens Conversation Documents modal
5. Global Docs (icon: globe) — opens Global Documents modal
6. ---divider---
7. New Temp Chat (icon: eye-slash) — creates a temporary conversation

### Desktop Doc-Action Row

Unchanged from original layout. Shows all buttons including extension extraction tools (hidden by default, shown when browser extension is active via `ext-btn` class toggling).

### Compact Nav Toggle

Located in Chat Settings modal → Basic Options section, alongside other checkboxes (Search, Search Exact, Auto Clarify, Persist, etc.).

## Implementation Details

### Height Calculation Strategy

`#mainView` sits inside `#chat-assistant`, which sits inside a chain of `height: 100%` parents descending from `#chat-content`. The key insight:

- **`#chat-assistant`** (and `#chat-assistant-sidebar`) use viewport-relative heights: `calc(100vh - 35px)` — this accounts for the ~35px top navbar row (`#pdf-details-tab` + `#navbar-trigger`).
- **`#mainView`** uses `height: 100% !important` — filling its parent (`#chat-assistant`) exactly, rather than independently calculating from viewport. This prevents double-deduction bugs where both parent and child subtract navbar height from `100vh`, and eliminates jitter at the height crossover boundary.
- **`#chat-content`** uses `height: calc(100% - 30px)` in all media queries.

Previously, `#mainView` used `calc(100vh - 55px)` in the mobile query (vs `calc(100vh - 35px)` in desktop queries). This caused two bugs:

1. **Bottom clipping**: `#mainView` and `#chat-assistant` were the same absolute size, but any padding/rounding caused `#mainView` to slightly overflow, pushing `#chat-controls` (the input area) below the visible fold.
2. **Jitter at 768px height crossover**: At 768→769px viewport height, the 20px difference between mobile (-55px) and desktop (-35px) deductions caused a visible layout jump when media queries switched.

The fix: all media queries now use `calc(100vh - 35px)` for `#chat-assistant`/`#chat-assistant-sidebar` (consistent across all breakpoints) and `height: 100%` for `#mainView` (parent-relative, not viewport-relative).

### Hidden Settings

Several Basic Options and Advanced settings are hidden via `display:none` as they are unused:

- **Basic Options**: PPT Answer, Render Slides Inline, Only Slides, Search, Search Exact
- **Advanced**: Reward Level

## Files Modified

| File | Changes |
|---|---|
| `interface/interface.html` | Added `⋮` dropdown (`#chat-actions-nav`, `d-md-none`) in navbar; restored desktop-only doc-action row (`d-none d-md-flex`) in `#mainView`; added `#settings-compact_nav` checkbox in Basic Options; hidden unused settings checkboxes |
| `interface/style.css` | Breakpoint constants header; true-mobile media query (`max-width` + `pointer: coarse` + `max-height`); two narrow-not-mobile overrides (fine pointer, tall coarse); desktop `min-width: 769px` query; all use `#mainView { height: 100% }` and `#chat-assistant { calc(100vh - 35px) }`; `body.compact-nav` rules; `#chat-actions-nav` dropdown styling; navbar overflow fix; `#chat-content` overflow fix |
| `interface/chat.js` | `applyCompactNav()` function; `compact_nav` in `buildSettingsStateFromControlsOrDefaults()`, `collectSettingsFromModal()`, `setModalFromState()`; live change handler |
| `interface/common-chat.js` | Mobile `mob-*` click proxy handlers (top of file); removed `#toggleChatDocsView` handler |

### Files NOT Modified

- `interface/shared.js`, `interface/shared.html` — own copies of the doc-action row for Search/Prep-Chat tabs, left untouched
- `interface/workspace-manager.js` — `#new-temp-chat` handler unchanged (ID preserved)
- `interface/local-docs-manager.js` — `#conversation-docs-button` handler unchanged
- `interface/global-docs-manager.js` — `#global-docs-button` handler unchanged
- `interface/page-context-manager.js` — all `#ext-*` handlers unchanged (IDs preserved in desktop row)

### Known Issue

- `interface/interface.html` references `heights.css` (line 8 area) which is a 404 — the actual mobile CSS is `css_patched_mobile_view.css`. This pre-existing issue was not addressed.
