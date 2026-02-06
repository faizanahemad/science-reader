# Rendering Performance Optimizations

## Overview

When loading a conversation with many messages, the UI was slow to render because:
1. **`showMore()` and buttons waited for MathJax**: They were queued AFTER MathJax typesetting, meaning the last card's structure wasn't visible until ALL previous cards' MathJax completed.
2. **MathJax processed cards FIFO**: The most relevant card (the last one) was processed last.
3. **No CSS scroll anchoring**: Async MathJax rendering caused scroll shifts.

These optimizations dramatically improve perceived rendering speed and prevent scroll disruption during page load.

## Changes Made

### 1. Moved `showMore()`/`addScrollToTopButton()` to `immediate_callback`

**File**: `interface/common-chat.js` (`renderMessages`)

**Before**: The `showMore()`, slide height adjustment, and `addScrollToTopButton()` functions were passed as the `callback` parameter (2nd argument) to `renderInnerContentAsMarkdown()`. This callback is queued AFTER MathJax via `MathJax.Hub.Queue(callback)`.

**Problem**: With 10 messages, the 10th card's `showMore()` wouldn't run until ALL previous cards' MathJax typesetting completed. Cards appeared "raw" (uncollapsed, no buttons) for seconds.

**After**: These functions are now passed as `immediate_callback` (5th argument), which runs **synchronously** right after HTML rendering — before MathJax starts.

```javascript
// Before (queued after MathJax):
renderInnerContentAsMarkdown(textElem,
    callback = function() { showMore(); addScrollToTopButton(); },
    continuous = false,
    html = message.text);

// After (runs synchronously):
renderInnerContentAsMarkdown(currentTextElem,
    /* callback (after MathJax) */ null,
    /* continuous */ false,
    /* html */ currentMessage.text,
    /* immediate_callback (synchronous) */ function() {
        showMore(); addScrollToTopButton();
    },
    /* defer_mathjax */ !isLastMessage);
```

**Impact**: All cards get their collapsed structure and scroll-to-top buttons immediately. Users see the final card layout before MathJax processes any math.

### 2. MathJax Priority for Last Card (`defer_mathjax` Parameter)

**File**: `interface/common.js` (`renderInnerContentAsMarkdown`)

Added a 6th parameter `defer_mathjax` (default: `false`):

```javascript
function renderInnerContentAsMarkdown(
    jqelem, callback, continuous, html, immediate_callback,
    defer_mathjax = false  // NEW: when true, MathJax is deferred
)
```

**When `defer_mathjax=true`**: MathJax typesetting is wrapped in `setTimeout(fn, 0)`, deferring it to after the current call stack completes.

**When `defer_mathjax=false`** (default): MathJax is queued immediately.

**How it's used in `renderMessages`**:

```javascript
(function(currentMessageElement, currentMessage, currentTextElem, currentShowHide, isLastMessage) {
    renderInnerContentAsMarkdown(currentTextElem,
        null,
        false,
        currentMessage.text,
        function() { showMore(); addScrollToTopButton(); },
        /* defer_mathjax */ !isLastMessage  // Only last card gets immediate MathJax
    );
})(messageElement, message, textElem, showHide, isLastInBatch);
```

**Effect**: During page load:
1. All cards render HTML + showMore + buttons synchronously (fast)
2. Last card's MathJax is queued immediately (first in MathJax queue)
3. Other cards' MathJax is deferred via `setTimeout(0)` (queued after last card)
4. MathJax processes: last card first → then other cards

**MathJax queue ordering**:
```
Last card MathJax → (setTimeout yields) → Card 1 MathJax → Card 2 MathJax → ... → Card N-1 MathJax
```

### 3. CSS Scroll Anchoring for Reflow

**File**: `interface/style.css`

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

When MathJax renders math in cards above the viewport (changing their height), CSS scroll anchoring automatically adjusts `scrollTop` to keep the user's visible content in place. Without this, each MathJax completion would shift the viewport.

See [Scroll Preservation](../scroll_preservation/README.md) for full details.

## Implementation Details

### `isLastInBatch` Detection

The `originalIndex` from `forEach` is used (not the reassigned `index` which reflects card count in DOM):

```javascript
messages.forEach(function (message, originalIndex, array) {
    var card_elements_count = $('#chatView').find('.message-card').length;
    var index = card_elements_count;
    var isLastInBatch = (originalIndex === array.length - 1);
    // ...
    renderInnerContentAsMarkdown(currentTextElem, ..., !isLastInBatch);
});
```

### `_queueMathJax()` Internal Function

Inside `renderInnerContentAsMarkdown`, MathJax queuing is wrapped in a helper:

```javascript
function _queueMathJax() {
    MathJax.Hub.Queue(["Typeset", MathJax.Hub, mathjax_elem]);

    // Release min-height lock after MathJax finishes (added by math reflow fix)
    MathJax.Hub.Queue(function() {
        if (_lockedMinHeight) targetElement.style.minHeight = '';
    });

    if (isSlidePresentation) {
        MathJax.Hub.Queue(function() { adjustCardHeightForSlides(...); });
    }
    if (callback) {
        MathJax.Hub.Queue(callback);
    }
}

if (defer_mathjax) {
    setTimeout(_queueMathJax, 0);
} else {
    _queueMathJax();
}
```

The min-height release step was added by the [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md). During streaming (`continuous=true`), element height is locked before innerHTML replacement to prevent layout collapse while MathJax re-typesets.

### Callback vs Immediate Callback

| Parameter | When Runs | Use For |
|-----------|-----------|---------|
| `callback` (2nd arg) | After MathJax completes (async, via `MathJax.Hub.Queue`) | Operations that need MathJax to finish (e.g., slide height calculation) |
| `immediate_callback` (5th arg) | Synchronously after HTML render, BEFORE MathJax | `showMore()`, `addScrollToTopButton()`, anything that shouldn't wait for MathJax |

### Other Call Sites (Unchanged)

The `defer_mathjax` parameter defaults to `false`, so existing call sites are unaffected:

| Call Site | `defer_mathjax` | Reason |
|-----------|----------------|--------|
| `renderMessages` (non-last cards) | `true` | Deferred to let last card go first |
| `renderMessages` (last card) | `false` | Priority rendering |
| `renderStreamingResponse` (streaming chunks) | `false` (default) | Single card, no competition |
| `renderStreamingResponse` (final render) | `false` (default) | Single card |
| `codemirror.js` | `false` (default) | Editor preview |

## Performance Impact

| Metric | Before | After |
|--------|--------|-------|
| Time to see last card's `showMore` structure | After ALL cards' MathJax | Immediate (synchronous) |
| Time to see scroll-to-top buttons | After ALL cards' MathJax | Immediate (synchronous) |
| Last card MathJax typesetting | Last in queue (after N-1 cards) | First in queue |
| Scroll stability during load | No CSS anchoring → shifts | CSS anchoring → stable |

## Files Modified

| File | Changes |
|------|---------|
| `interface/common.js` | Added `defer_mathjax` parameter to `renderInnerContentAsMarkdown()`, `_queueMathJax()` helper, docstring updates |
| `interface/common-chat.js` | `renderMessages`: moved showMore/buttons to `immediate_callback`, pass `defer_mathjax: !isLastInBatch` |
| `interface/style.css` | CSS scroll anchoring for `#chatView` and `.message-card`, increased card margins |

## Related Features

- [Scroll Preservation](../scroll_preservation/README.md) — CSS scroll anchoring and JavaScript anchor restoration
- [Multi-Model Response Tabs](../multi_model_response_tabs/README.md) — Tab rendering that triggers DOM changes
- [ToC Streaming Fix](../toc_streaming_fix/README.md) — Collapsed ToC reduces reflow during streaming
- [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md) — Math-aware render gating, min-height stabilization, over-indented list normalization