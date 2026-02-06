# ToC Streaming Fix

This feature addresses the layout shift issue that occurred when the Table of Contents (ToC) was generated during streaming responses.

## Problem Statement

During streaming, the Table of Contents grows as new headings appear in the response. This caused layout reflow that pushed the answer content down and disrupted the user's reading position - content would "jump" as the ToC expanded.

### Root Cause

1. **Variable ToC height**: As LLM generates sections with new headings, ToC grows from 0 items to N items
2. **Browser layout recalculation**: Each ToC update triggers a reflow
3. **No scroll compensation**: The browser maintains the scroll position relative to the viewport, not the content

## Solution Overview

Two complementary solutions were implemented:

### Solution 3: Collapsed ToC During Streaming

- **Streaming mode**: ToC shows collapsed with item count (e.g., "Show (5)")
- **User click**: Expands ToC and stays expanded through subsequent streaming updates
- **Non-streaming (historic)**: ToC shows fully expanded by default (backward compatible)
- **After streaming ends**: ToC remains collapsed unless user manually expanded

### Solution 7: Floating ToC via Triple-Dot Menu

- **Menu entry**: "Table of Contents" item in the card's triple-dot dropdown menu
- **Floating panel**: Opens a floating ToC panel positioned over the answer card
- **Live updates**: Panel updates automatically during streaming
- **Dismiss**: Click outside, press Escape, or use the close button

## Files Modified

| File | Changes |
|------|---------|
| `interface/common-chat.js` | Added `data-live-stream` and `data-live-stream-ended` attributes to streaming cards |
| `interface/common.js` | Modified ToC functions, added floating ToC functions, updated toggle handler |
| `interface/style.css` | Added CSS for collapsed ToC state and floating ToC panel |

## Implementation Details

### Card Streaming Flags (`common-chat.js`)

```javascript
// When streaming starts (line ~920)
card.attr('data-live-stream', 'true');

// When streaming ends (line ~1105)
card.removeAttr('data-live-stream');
card.attr('data-live-stream-ended', 'true');
```

### ToC State Determination (`common.js`)

The `determineTocExpandedState()` function implements 3-way logic:

1. **Historic render** (no streaming flags): `expanded = true`
2. **Live streaming** (`data-live-stream="true"`): `expanded = false` (unless user expanded)
3. **Post-streaming** (`data-live-stream-ended="true"`): Keep current state

### User Expanded Tracking

- `data-toc-user-expanded="true"` attribute stored on card (or tab-pane for tabbed responses)
- Set when user clicks to expand the ToC
- Persists through streaming updates and rebuilds

### Floating ToC Functions

| Function | Purpose |
|----------|---------|
| `showFloatingToc($card)` | Opens floating panel for a card |
| `buildFloatingTocPanelHtml(items, prefix)` | Builds panel HTML |
| `setupFloatingTocHandlers($panel, $card)` | Sets up click/keyboard handlers |
| `closeFloatingToc($card)` | Closes panel for a specific card |
| `closeAllFloatingTocs()` | Closes all panels, cleans up handlers |
| `updateFloatingTocIfOpen($card, items, prefix)` | Updates panel during streaming |

### Menu Integration

Added in `initialiseVoteBank()`:

```javascript
var tocItem = $('<a class="dropdown-item floating-toc-trigger" href="#">...');
tocItem.click(function(e) {
    e.preventDefault();
    showFloatingToc(cardElem);
});
```

## CSS Additions

### Collapsed ToC State

```css
.message-toc[data-toc-expanded="false"] {
    padding: 6px 10px;
}
.message-toc[data-toc-expanded="false"] .message-toc-header {
    margin-bottom: 0;
}
```

### ToC Toggle Button Styling

The "Show (N)" / "Hide" button was restyled for better visibility:

```css
.message-toc-toggle {
    font-weight: 600;
    font-size: 0.72rem;
    color: #fff !important;
    background-color: #5a7d8a !important;
    border-color: #4a6d7a !important;
    padding: 2px 10px;
    border-radius: 3px;
}

.message-toc-toggle:hover,
.message-toc-toggle:focus {
    background-color: #3d5f6d !important;
    border-color: #2e4f5d !important;
}
```

**Rationale**: The original Bootstrap `btn-secondary` was too light and hard to see. The dark teal style provides clear contrast and obvious clickability.

### Floating ToC Panel

- Positioned `absolute` relative to card
- `z-index: 1045` (above dropdowns, below modals)
- Smooth fade-in animation
- Dark mode support
- Mobile responsive

### Dropdown Close Fix

When opening the floating ToC from the triple-dot menu, the dropdown wasn't closing. Fixed by explicitly hiding the dropdown in the click handler:

```javascript
tocItem.click(function(e) {
    e.preventDefault();
    $(this).closest('.dropdown-menu').dropdown('hide'); // Close dropdown first
    showFloatingToc(cardElem);
});
```

## Testing Checklist

- [ ] Stream a long response with headings - ToC should appear collapsed
- [ ] Click "Show (N)" - ToC should expand and stay expanded during streaming
- [ ] Click to collapse after expanding during streaming - should stay collapsed
- [ ] Historic messages - ToC should appear expanded by default
- [ ] Triple-dot menu → "Table of Contents" - Floating panel should appear
- [ ] Triple-dot menu dropdown should close when floating ToC opens
- [ ] Click outside floating panel - Panel should close
- [ ] Press Escape - Panel should close
- [ ] Switch conversations - All floating panels should close
- [ ] Tabbed responses - Each tab should have independent ToC state
- [ ] ToC "Show" button should be clearly visible (dark teal, not light grey)

## Related Features

- [Multi-Model Response Tabs](../multi_model_response_tabs/README.md) - ToC works per-tab in tabbed responses
- [Scroll Preservation](../scroll_preservation/README.md) - Collapsed ToC prevents scroll shifts during streaming
- [Rendering Performance](../rendering_performance/README.md) - ToC generation interacts with deferred MathJax