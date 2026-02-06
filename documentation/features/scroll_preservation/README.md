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

### Layer 1: Height Lock — Scroll Prevention (Primary)

**Files**: `interface/common.js`, `interface/common-chat.js`

The most effective approach: **prevent** the scroll from shifting in the first place by locking container heights during DOM manipulation, rather than trying to correct after the fact.

**How it works**: Before any DOM changes that hide/remove/insert large content blocks, we set `minHeight` on the container element to its current `offsetHeight`. All DOM changes happen inside this locked height, so the total page height never changes and `scrollTop` never shifts. After all DOM work completes, the lock is released and CSS scroll anchoring handles any small delta.

**Three height locks at different levels:**

| Lock Location | File | Container Locked | Covers |
|---------------|------|-----------------|--------|
| `applyModelResponseTabs()` | common.js | `$root` (`.chat-card-body`) | Hide originals → insert tab container → remove TLDR sources |
| `showMore()` | common.js | Closest `.chat-card-body` | `textElem.empty()` → rebuild with less/more text → `applyModelResponseTabs(moreText)` |
| Streaming `done` handler | common-chat.js | `card.find('.chat-card-body')` | Entire finalization: `renderInnerContentAsMarkdown` → `applyModelResponseTabs` → `showMore` → buttons |

```javascript
// Example: Height lock in applyModelResponseTabs
var _heightLockEl = $root[0];
var _heightLockValue = _heightLockEl.offsetHeight;
_heightLockEl.style.minHeight = _heightLockValue + 'px';  // LOCK

// ... all DOM changes (hide, insert, remove) ...

_heightLockEl.style.minHeight = '';  // RELEASE
```

**Why this is seamless**: With `minHeight` locked, the card body stays the same size throughout all DOM manipulation. The browser never sees a height change, so `scrollTop` never shifts. The user perceives zero scroll movement.

**Coverage**: Handles the "scroll up then back down" jank that occurred when:
- Tabs are first created (content hidden → tabs inserted)
- `showMore()` empties and rebuilds the text element
- `innerHTML` replaces content during final render
- TLDR sources are removed from the DOM

### Why Previous Approaches Failed

Before the height lock, several scroll **correction** approaches were tried:

1. **scrollTop capture/restore inside `applyModelResponseTabs()`**: Captured AFTER `innerHTML` already shifted scroll — restoring a wrong value.
2. **Multiple nested restores**: `applyModelResponseTabs()`, `renderInnerContentAsMarkdown()`, and `showMore()` each trying to restore independently caused progressive scroll drift (each captured a new anchor on a changed DOM).
3. **Anchor-based restore competing with CSS anchoring**: In multi-model mode, CSS scroll anchoring already handled the shift, but JavaScript restore overrode it with a worse value (~40px regression).
4. **Raw scrollTop restore**: When TLDR content was stripped from the Main tab clone, the page got ~2000px shorter, making the original `scrollTop` value exceed the new `maxScrollTop`. Restoring was impossible because the page wasn't tall enough anymore.

**Key insight**: Scroll **correction** (restore after the fact) is fundamentally flawed because (a) the page may be shorter after tab creation, (b) multiple corrections interfere, and (c) the correction is visible to the user as jank. Scroll **prevention** (height lock) avoids all these issues.

### Layer 2: CSS Scroll Anchoring (Secondary)

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
- Small height deltas when height locks are released

**Limitation**: Does NOT help when the actively-being-modified card (the one you're reading) restructures its DOM without a height lock.

### Layer 3: JavaScript Anchor-Based Restoration (Safety Net)

**File**: `interface/common-chat.js` (streaming `done` handler)

A last-resort JavaScript-based anchor restore runs ONCE after all DOM work completes. With the height lock in place, this should rarely trigger (drift should be < 50px, handled by CSS anchoring). It exists as a safety net for edge cases.

**Key design decision**: The JavaScript restore DEFERS to CSS anchoring when it's working. If scrollTop barely changed (< 50px drift), the JS restore is skipped. This prevents the JS restore from **fighting** the browser's CSS anchoring.

#### Capture (at start of `done` block)

```javascript
var _streamScrollTopBeforeDone = _streamScrollChatView.scrollTop();
var _streamScrollAnchor = captureChatViewScrollAnchorForCard(_streamScrollChatView, _lastCard);
```

Captures:
1. **Raw `scrollTop`** — used as the ground truth for CSS anchoring comparison
2. **Visual anchor** — an element+offset inside the last card for anchor-based restoration

#### Restore (after all DOM work + height lock release)

```javascript
function _tryRestore(label) {
    var drift = Math.abs(currentScrollTop - _streamScrollTopBeforeDone);
    if (drift <= CSS_ANCHORING_THRESHOLD) return; // CSS handled it
    // Try anchor-based restore, fallback to raw scrollTop
}
```

Runs at 4 timing points:
1. **Immediate** — right after synchronous DOM work + height lock release
2. **`requestAnimationFrame`** — after browser layout
3. **700ms** — after `showMore()` via `setTimeout(500)` settles
4. **1200ms** — after MathJax/Mermaid

### Layer 4: `scrollToHashTargetInCard()` Safety Guard

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

### Height Lock Details

#### In `applyModelResponseTabs()` (`interface/common.js`)

```javascript
// Before Step A (hide originals):
var _heightLockEl = $root[0]; // .chat-card-body
var _heightLockValue = _heightLockEl.offsetHeight;
_heightLockEl.style.minHeight = _heightLockValue + 'px';

// Step A: Hide all children (display: none)
// Step B: Insert/move tab container
// Step C: Remove TLDR sources

// After Step C:
_heightLockEl.style.minHeight = ''; // Release
```

**Early exits**: If the tab container can't be attached to the DOM, the height lock is released before the early return to prevent orphaned min-height styles.

#### In `showMore()` (`interface/common.js`)

```javascript
// Before textElem.empty():
var _smHeightLockEl = textElem.closest('.chat-card-body')[0];
var _smHeightLockValue = _smHeightLockEl.offsetHeight;
_smHeightLockEl.style.minHeight = _smHeightLockValue + 'px';

// textElem.empty() + rebuild + applyModelResponseTabs(moreText)

// After applyModelResponseTabs:
_smHeightLockEl.style.minHeight = ''; // Release
```

#### In Streaming `done` handler (`interface/common-chat.js`)

This is the outermost lock — covers the entire finalization pipeline:

```javascript
// Before renderInnerContentAsMarkdown:
var _cardBodyForLock = card.find('.chat-card-body')[0];
_cardBodyForLock.style.minHeight = _cardBodyForLock.offsetHeight + 'px';

// renderInnerContentAsMarkdown → innerHTML → applyModelResponseTabs → showMore
// initialiseVoteBank, mermaid.run, addScrollToTopButton...

// After all synchronous DOM work, before scroll restoration:
_cardBodyForLock.style.minHeight = ''; // Release
```

### Helper Functions (`interface/common.js`)

#### `captureChatViewScrollAnchorForCard($chatView, $card)`

Captures a visual scroll anchor strictly scoped to a specific card:
1. Forces `$card` to the **last** `.message-card` in `#chatView` if not provided
2. Uses `elementFromPoint()` to find the visible element at the viewport intersection with the card
3. Walks up to find an element with an ID
4. Records the element's viewport offset and card-relative offset
5. Fallback: uses the card's own position + message-id

**Critical**: Never falls back to a generic (non-card-scoped) capture. This prevents anchoring to a different card.

#### `restoreChatViewScrollAnchor($chatView, anchor)`

Restores scroll position using a captured anchor:
1. Find the anchor element by ID → compute delta → adjust scrollTop
2. Fallback: find card by message-id → use card-relative offset

### Where Height Locks Are NOT Active

| Context | Reason |
|---------|--------|
| Non-streaming renders (page reload) | Cards render in sequence; CSS scroll anchoring handles it naturally |
| Streaming chunks (`continuous=true`) | Height is already locked by the math-reflow min-height mechanism |
| `renderInnerContentAsMarkdown()` — no separate lock | Covered by the outermost streaming `done` handler lock |

### Why Inner Functions Don't Do Scroll Correction

Early iterations had scroll **correction** (capture/restore scrollTop) inside `applyModelResponseTabs()`, `renderInnerContentAsMarkdown()`, and `showMore()`. This caused **progressive scroll drift** because:

1. Each function captured a NEW anchor after the previous function had already modified the DOM
2. Multiple `requestAnimationFrame` callbacks competed
3. Each restore adjusted slightly differently, drifting further from the original position

**Current approach**: Inner functions do height **locking** (prevention), not scroll **correction** (restoration). Only the outermost streaming `done` handler does correction, and only as a safety net.

## Multi-Model vs Single-Model Differences

### Single-Model + TLDR

1. During streaming: tabs NOT built (`isLiveStreaming: true` prevents single-model+TLDR tabs)
2. After streaming: final render builds tabs for the first time
3. Height lock in `applyModelResponseTabs` keeps card body at constant height during tab creation
4. CSS scroll anchoring handles the small delta when lock is released

### Multi-Model (2+ models)

1. During streaming: tabs ARE built (`modelDetails.length >= 2` bypasses live streaming check)
2. Tabs are rebuilt on each streaming update
3. After streaming: TLDR tab may be added, changing nav height by ~40px
4. Height lock + CSS scroll anchoring handles this combination
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
| `interface/common.js` | Height lock in `applyModelResponseTabs()` around DOM swap (Steps A-C) |
| `interface/common.js` | Height lock in `showMore()` around `textElem.empty()` + rebuild |
| `interface/common.js` | `captureChatViewScrollAnchorForCard()`: card-scoped anchor capture |
| `interface/common.js` | `restoreChatViewScrollAnchor()`: anchor-based restore with card fallback |
| `interface/common-chat.js` | Height lock in streaming `done` handler (outermost level) |
| `interface/common-chat.js` | Streaming `done` handler: anchor capture, CSS-threshold-aware restore (safety net) |
| `interface/common-chat.js` | `scrollToHashTargetInCard()`: card-scoped safety guard |

## Debugging

### Console Logs

Diagnostic `console.warn` logs are **commented out** by default. Uncomment them to debug:

| Log (commented) | Location | Meaning |
|-----------------|----------|---------|
| `[streaming done] CAPTURED anchor` | common-chat.js | Anchor ID, offsets, and original scrollTop |
| `[streaming done] CSS OK / Anchor restore / Raw restore` | common-chat.js | Restore attempt results |
| `[applyModelResponseTabs] models, tldr, streaming` | common.js | Tab decision inputs |
| `[renderInnerContentAsMarkdown] answer_tldr` | common.js | TLDR tag detection |

### Common Scroll Issues and Their Causes

| Symptom | Likely Cause |
|---------|-------------|
| Visible "scroll up then back down" jank | Height lock not covering a DOM change path — check if min-height is set before the problematic operation |
| Jumps to previous card | `scrollToHashTargetInCard()` finding element outside current card (fixed) |
| 40px shift in multi-model | JavaScript restore fighting CSS anchoring (fixed by threshold check) |
| Scroll jumps on page reload | Height lock should NOT be active for non-streaming (check `data-live-stream` flags) |
| Progressive drift | Multiple nested scroll corrections competing (fixed: only outermost handler does correction) |

## Evolution of Scroll Preservation

1. **V1**: scrollTop capture/restore inside each function → Failed (captured wrong values after DOM changes)
2. **V2**: Anchor-based restore inside each function → Failed (progressive drift from competing restores)
3. **V3**: Single outermost anchor-based restore in streaming handler → Worked but visible jank (restore happened after browser painted shifted position)
4. **V4 (Current)**: Height lock (prevention) + CSS anchoring + outermost JS safety net → Seamless (scroll never shifts in the first place)

## Related Features

- [Multi-Model Response Tabs](../multi_model_response_tabs/README.md) — Tab creation causes the DOM changes this feature compensates for
- [ToC Streaming Fix](../toc_streaming_fix/README.md) — Collapsed ToC prevents additional scroll shifts during streaming
- [Rendering Performance](../rendering_performance/README.md) — MathJax deferred rendering reduces reflow from async typesetting
- [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md) — Min-height locking and math-aware render gating reduce scroll-disrupting DOM changes during streaming
