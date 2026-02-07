# Scroll Preservation

## Overview

When the chat UI rebuilds DOM elements (model tabs appearing, TLDR rendering, MathJax typesetting, `showMore()` collapsing), the user's reading position must remain stable. Without intervention, these DOM changes cause jarring scroll shifts — the page "jumps" up or down.

This document covers all scroll-preservation mechanisms in the chat UI and the iterative fixes applied to reach the current stable state.

## Problem Statement

Multiple events cause scroll-disrupting DOM changes:

| Event | When | Scroll Impact |
|-------|------|---------------|
| **Tabs appear** (multi-model) | During streaming, when 2nd model starts | Content shifts as tab nav+panes are inserted |
| **Tabs finalize** (single-model+TLDR) | After streaming ends, TLDR added to tabs | Tab nav grows (~40px for TLDR tab entry), cloned content may be shorter |
| **`showMore()` rebuild** | After streaming ends or on reload | Entire DOM is emptied and rebuilt with collapsed structure |
| **`innerHTML` rewrite** | Final render (`continuous=false`) | Full content replacement |
| **MathJax typesetting** | Async, per-card after render | Math formulas expand, changing element heights |
| **Scroll-to-top button** | After render completes | Small height addition at card bottom |
| **`scrollToHashTargetInCard()`** | After streaming ends | Could scroll to an element in a *different* card if URL hash is stale |

## Solution Architecture

### Layer 1: CSS Scroll Anchoring (Primary)

**File**: `interface/style.css`

The browser's built-in CSS Scroll Anchoring (`overflow-anchor: auto`) automatically compensates for content height changes above the viewport.

```css
#chatView {
    overflow-anchor: auto;
}

.message-card {
    overflow-anchor: auto;
    margin-bottom: 0.75rem !important;
    margin-top: 0.25rem !important;
}
```

**How it works**: When content above the viewport grows or shrinks (e.g., MathJax renders math, `showMore()` collapses a card), the browser adjusts `scrollTop` to keep the user's visible content in place.

**Coverage**: Handles ~90% of reflow issues automatically. Works for:
- MathJax rendering in cards above viewport
- `showMore()` collapsing cards above viewport
- Button additions
- ToC appearance/collapse

**Limitation**: Does NOT help when the actively-being-modified card (the one you're reading) restructures its DOM (e.g., tabs appearing, content hidden and re-inserted).

### Layer 2: JavaScript Anchor-Based Restoration (Streaming Finalization)

**File**: `interface/common-chat.js` (streaming `done` handler)

For the streaming card being actively modified, CSS anchoring alone may not suffice. A JavaScript-based anchor restore runs at the outermost level — ONCE after all DOM work completes.

**Key design decision**: The JavaScript restore DEFERS to CSS anchoring when it's working. If scrollTop barely changed (< 50px drift), the JS restore is skipped because CSS anchoring already handled it. This prevents the JS restore from **fighting** the browser's CSS anchoring (which caused a 40px regression in multi-model mode).

#### Capture (at start of `done` block)

```javascript
var _streamScrollTopBeforeDone = _streamScrollChatView.scrollTop();
var _streamScrollAnchor = captureChatViewScrollAnchorForCard(_streamScrollChatView, _lastCard);
```

Captures:
1. **Raw `scrollTop`** — used as the ground truth for CSS anchoring comparison
2. **Visual anchor** — an element+offset inside the last card for anchor-based restoration

#### Restore (after all DOM work)

```javascript
function _tryRestore(label) {
    var drift = Math.abs(currentScrollTop - _streamScrollTopBeforeDone);
    
    if (drift <= CSS_ANCHORING_THRESHOLD) {
        // CSS scroll anchoring already handled it — don't override
        return;
    }
    
    // Significant drift — try anchor-based restore, fallback to raw scrollTop
    if (_streamScrollAnchor) {
        restoreChatViewScrollAnchor(_streamScrollChatView, _streamScrollAnchor);
        // If anchor didn't improve, fallback to raw scrollTop
    }
}
```

Runs at 4 timing points:
1. **Immediate** — right after synchronous DOM work
2. **`requestAnimationFrame`** — after browser layout
3. **700ms** — after `showMore()` via `setTimeout(500)` settles
4. **1200ms** — after MathJax/Mermaid

### Layer 3: `scrollToHashTargetInCard()` Safety Guard

**File**: `interface/common-chat.js`

When streaming ends, `scrollToHashTargetInCard(card)` is called to honor URL hash deep-links. Previously, it would scroll to any element with the hash ID — even in a *different* card — causing jumps to the previous message.

**Fix**: Only scrolls if the hash target element is INSIDE the current card:

```javascript
if (!cardElem[0].contains(targetEl)) {
    return; // Don't scroll to elements outside this card
}
```

Also: only called when there's actually a hash in the URL (not unconditionally).

## Implementation Details

### Helper Functions (`interface/common.js`)

#### `captureChatViewScrollAnchorForCard($chatView, $card)`

Captures a visual scroll anchor strictly scoped to a specific card:
1. Uses `elementFromPoint()` to find the visible element at the viewport intersection with the card
2. Walks up to find an element with an ID
3. Records the element's viewport offset and card-relative offset
4. Fallback: uses the card's own position + message-id

**Critical**: Never falls back to a generic (non-card-scoped) capture. This prevents anchoring to a different card.

#### `restoreChatViewScrollAnchor($chatView, anchor)`

Restores scroll position using a captured anchor:
1. Find the anchor element by ID → compute delta → adjust scrollTop
2. Fallback: find card by message-id → use card-relative offset

### Where Scroll Preservation is NOT Active

| Context | Reason |
|---------|--------|
| Non-streaming renders (page reload) | Cards render in sequence; CSS scroll anchoring handles it naturally |
| `applyModelResponseTabs()` | Scroll preservation removed from here — was causing double-restoration and drift |
| `renderInnerContentAsMarkdown()` | Scroll preservation removed from here — same reason |
| `showMore()` | Scroll preservation removed from here — handled at outermost level |

### Why Inner Functions Don't Do Scroll Preservation

Early iterations had scroll preservation inside `applyModelResponseTabs()`, `renderInnerContentAsMarkdown()`, and `showMore()`. This caused **progressive scroll drift** because:

1. Each function captured a NEW anchor after the previous function had already modified the DOM
2. Multiple `requestAnimationFrame` callbacks competed
3. Each restore adjusted slightly differently, drifting further from the original position

**Solution**: Single capture at the outermost level (streaming `done` handler), single restore after everything settles.

## Multi-Model vs Single-Model Differences

### Single-Model + TLDR

1. During streaming: tabs NOT built (`isLiveStreaming: true` prevents single-model+TLDR tabs)
2. After streaming: final render builds tabs for the first time
3. CSS scroll anchoring handles the tab insertion well (same card, content height roughly preserved)

### Multi-Model (2+ models)

1. During streaming: tabs ARE built (`modelDetails.length >= 2` bypasses live streaming check)
2. Tabs are rebuilt on each streaming update
3. After streaming: TLDR tab may be added, changing nav height by ~40px
4. CSS scroll anchoring handles this well — the 40px nav growth is compensated automatically
5. **Critical**: JavaScript restore must NOT override CSS anchoring for multi-model (the `CSS_ANCHORING_THRESHOLD` check prevents this)

## Card Spacing

**File**: `interface/style.css`

Increased card margins from Bootstrap's `mb-1 mt-0 my-1` (~4px) to:

```css
.message-card {
    margin-bottom: 0.75rem !important; /* ~12px */
    margin-top: 0.25rem !important;    /* ~4px */
}
```

Benefits:
- Better visual separation between messages
- Provides a buffer zone that absorbs minor reflow from deferred MathJax/button rendering
- Makes CSS scroll anchoring more effective (clearer boundary between cards)

## Files Modified

| File | Changes |
|------|---------|
| `interface/style.css` | Added `overflow-anchor: auto` to `#chatView` and `.message-card`; increased card margins |
| `interface/common-chat.js` | Streaming `done` handler: anchor capture, CSS-threshold-aware restore, multi-timing restore |
| `interface/common-chat.js` | `scrollToHashTargetInCard()`: card-scoped safety guard |
| `interface/common.js` | `captureChatViewScrollAnchorForCard()`: card-scoped anchor capture |
| `interface/common.js` | `restoreChatViewScrollAnchor()`: anchor-based restore with card fallback |
| `interface/common.js` | Removed scroll preservation from `applyModelResponseTabs()`, `renderInnerContentAsMarkdown()`, `showMore()` |

## Debugging

### Console Logs

The following `console.warn` diagnostic logs are active during streaming:

| Log | Location | Meaning |
|-----|----------|---------|
| `[streaming done] CAPTURED scroll anchor` | common-chat.js | Anchor ID, offsets, and original scrollTop |
| `[streaming done] Immediate/rAF/700ms/1200ms` | common-chat.js | Restore attempt: CSS anchoring check result and scrollTop |
| `[renderInnerContentAsMarkdown] BEFORE/AFTER innerHTML write` | common.js | scrollTop around innerHTML assignment |
| `[applyModelResponseTabs] shouldBuildTabs` | common.js | Whether tabs are being built |
| `[showMore] BEFORE/AFTER textElem.empty()` | common.js | scrollTop around showMore DOM rebuild |

### Common Scroll Issues and Their Causes

| Symptom | Likely Cause |
|---------|-------------|
| Jumps to previous card | `scrollToHashTargetInCard()` finding element outside current card (fixed) |
| 40px shift in multi-model | JavaScript restore fighting CSS anchoring (fixed by threshold check) |
| Scroll jumps on page reload | Scroll preservation shouldn't be active for non-streaming (check `data-live-stream` flags) |
| Progressive drift (scroll gets worse with each update) | Multiple nested restores competing (fixed by single outermost restore) |

## Related Features

- [Multi-Model Response Tabs](../multi_model_response_tabs/README.md) — Tab creation causes the DOM changes this feature compensates for
- [ToC Streaming Fix](../toc_streaming_fix/README.md) — Collapsed ToC prevents additional scroll shifts during streaming
- [Rendering Performance](../rendering_performance/README.md) — MathJax deferred rendering reduces reflow from async typesetting
- [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md) — Min-height locking and math-aware render gating reduce scroll-disrupting DOM changes during streaming