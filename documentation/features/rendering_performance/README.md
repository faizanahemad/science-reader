# Rendering Performance Optimizations

## Overview

When loading a conversation with many messages (40-80+), the UI was slow to render
because of multiple compounding bottlenecks:

1. **`showMore()` serialized/parsed DOM per card**: 2 full HTML serialize+parse cycles per long message
2. **MathJax processed cards FIFO synchronously**: 40 Typeset calls queued back-to-back with no yields
3. **Double markdown parse for sectioned messages**: `marked.marked()` ran twice on content with `---` dividers
4. **No browser yields during render**: All 40 cards built in one synchronous batch
5. **All `$(document).ready` handlers ran eagerly**: 23 feature-init handlers blocked boot
6. **Network calls waited for render to complete**: Doubts/pins fetched after all cards rendered

These optimizations bring perceived load from ~13s to <1s for first card, <4s for all cards.

## Current Architecture

### Render Pipeline Flow (conversation load)

```
setActiveConversation
  |
  |-- _perfReset() + _mathJaxScheduler.clear()  [clear stale state]
  |-- Fire doubts + pins fetch early (R2)        [network overlaps render]
  |-- $.when(snapshot, messages).done:
  |     |
  |     |-- renderMessages() with CHUNK_SIZE=1   [per-card yields]
  |     |     |
  |     |     |-- For each card (one per setTimeout(0) yield):
  |     |     |     |-- _buildMessageCard()
  |     |     |     |     |-- cardTemplate (jQuery HTML parse)
  |     |     |     |     |-- renderInnerContentAsMarkdown()
  |     |     |     |     |     |-- processContentWithDetails() [R3: sections parsed once]
  |     |     |     |     |     |-- marked.marked() [skipped if R3 flag set]
  |     |     |     |     |     |-- innerHTML assignment
  |     |     |     |     |     |-- applyModelResponseTabs [skipped for collapsed, R1]
  |     |     |     |     |     |-- updateMessageToc [skipped for collapsed, R1]
  |     |     |     |     |     |-- applyUIState [skipped for collapsed, R12]
  |     |     |     |     |     |-- _mathJaxScheduler.enqueue() [R5: yields between cards]
  |     |     |     |     |-- showMore() [R1: in-place wrapAll, no serialize/parse]
  |     |     |     |     |-- setTimeout(0): initialiseVoteBank + decorateNav [R12]
  |     |     |     |
  |     |     |-- _runPostRenderWork()
  |     |           |-- mermaid, dropdowns, URL scroll
  |     |           |-- _perfSummary() at fullyInteractive mark
  |     |
  |     |-- Promise.all([doubtsPromise, _renderCompletePromise]).then(applyDoubts)
  |     |-- Promise.all([pinsPromise, _renderCompletePromise]).then(applyPins)
```

### Key Optimizations Implemented

| # | Optimization | Estimated Savings | Status |
|---|-------------|-------------------|--------|
| R1 | showMore() in-place wrapAll + deferred tabs/ToC for collapsed | 2-4s (40 msgs) | **DONE** |
| R2 | Fetch-early / apply-late for doubts+pins | 200-600ms | **DONE** |
| R3 | Double marked parse elimination (sections parsed once) | 0.5-1s | **DONE** |
| R4 | Defer 23 non-critical $(document).ready handlers | 100-300ms boot | **DONE** |
| R5 | Yielding MathJax scheduler (one-at-a-time with setTimeout yield) | Page stays responsive during 69s MathJax | **DONE** |
| R12 | Per-card chunking (CHUNK_SIZE=1) + collapsed card deferral | First card <500ms, 1-4s total | **DONE** |

## R5 — Yielding MathJax Scheduler

**File:** `interface/common.js:134-193` (`_mathJaxScheduler` IIFE)

### Problem

MathJax 2.7.5's `Hub.Queue` is a synchronous FIFO. When 40 Typeset calls are
queued at once, MathJax runs them back-to-back in one giant main-thread task
("Processing Math: 100%"), freezing the page for 10-70 seconds depending on
math complexity. The page is completely unscrollable and unresponsive.

Profiling data (80-message conversation, 4 math cards):
- `mathJaxTypeset` total: **69,137ms** (average 17,284ms per card, max 30,774ms)
- All other rendering combined: ~7,500ms

### Solution

A custom scheduler (`_mathJaxScheduler`) replaces direct `MathJax.Hub.Queue`
calls for history loads. It:

1. Collects pending `{elem, callback}` entries in its own queue
2. Drains one element at a time: calls `MathJax.Hub.Queue(["Typeset", ...])` for
   a single element
3. In the MathJax completion callback, yields via `setTimeout(_drain, 0)` before
   processing the next element
4. This lets the browser run paint, scroll, and input handlers between each card

Priority support: the last/visible card is prepended (`priority=true`), others
appended.

Streaming path bypasses the scheduler entirely — streaming already controls its
own pacing via the `isInsideDisplayMath` gate and dynamic render thresholds.

### API

```javascript
_mathJaxScheduler.enqueue(element, callback, priority)  // add to queue
_mathJaxScheduler.clear()                                // discard pending (on conv switch)
_mathJaxScheduler.pending()                              // items waiting
```

### Stale-response guard

`_mathJaxScheduler.clear()` is called at the top of `setActiveConversation`
(`common-chat.js:694`) alongside `_perfReset()`. This prevents stale Typeset
calls from a previous conversation from running after switching.

### Call sites

| Path | Uses scheduler? | Why |
|------|----------------|-----|
| History load (non-last card) | Yes, `priority=false` | Deferred, yields between cards |
| History load (last card) | Yes, `priority=true` | Typeset first (visible card) |
| Streaming (`continuous=true`) | No — direct `MathJax.Hub.Queue` | Streaming pacing is self-managed |
| Doubt manager (6 sites) | No — direct `MathJax.Hub.Queue` | Per-card, post-stream only |
| Temp LLM manager (3 sites) | No — direct `MathJax.Hub.Queue` | Per-card, post-stream only |
| Markdown editor (1 site) | No — direct `MathJax.Hub.Queue` | Single preview pane |

### Perf mark

Each scheduler drain emits a `mathJaxTypeset` perf mark, visible in
`_perfSummary()` and Chrome DevTools Performance timeline.

### Limitations

The scheduler keeps the page **responsive** during MathJax processing, but does
not reduce the total MathJax wall time. MathJax 2.7.5 with HTML-CSS output is
inherently slow (DOM measurement per glyph). For a 30s card, the user can scroll
and interact but math still takes 30s to render. The real fix is MathJax 3
migration (CHTML output, 2-5x faster) or viewport-based deferral.

## R12 — Per-Card Chunking + Collapsed Card Deferral

**File:** `interface/common-chat.js:2960` (CHUNK_SIZE), `common-chat.js:2806-2870`
(deferred init), `common.js:5105` (skip_deferred_formatting param)

### Changes

1. **`CHUNK_SIZE = 1`** — each card gets its own `setTimeout(0)` yield. Page is
   scrollable after the first card (~100-400ms) instead of after 5 cards.

2. **`skip_deferred_formatting`** — for cards that will be collapsed by `showMore()`
   (`show_hide != 'show' && text > 300`), skips:
   - `applyModelResponseTabs` (tab layout)
   - `updateMessageTocForElement` (ToC generation)
   - `applyConversationUIState` (section collapse state)

   The delegated expand handler at `common.js:1669` re-applies tabs+ToC on first
   `[show]` click.

3. **Deferred `initialiseVoteBank` + `decorateMessageCardNav`** — wrapped in
   `setTimeout(0)` IIFE closures. Both set up UI that users don't interact with
   during initial load.

4. **Removed wasted `textElem.html(message.text)`** — this was immediately
   overwritten by `renderInnerContentAsMarkdown`.

## Performance Instrumentation

**File:** `interface/common.js:46-132`

### Utilities

| Function | Purpose |
|----------|---------|
| `_perfStart(label)` | Start a named timer; returns start timestamp; creates Performance API mark |
| `_perfEnd(label, startTime)` | End timer; records duration; creates Performance API measure |
| `_perfSummary()` | Print grouped summary table to console (sorted by total time desc) |
| `_perfJSON()` | Return JSON string of all timings + copy to clipboard |
| `_perfReset()` | Clear all collected timings and Performance API marks/measures |

### Perf marks (19 labels)

| Mark | What it measures | File:Line |
|------|-----------------|-----------|
| `setActiveConversation` | Full conversation load (network + render + loader hide) | `common-chat.js:692` |
| `networkWait` | Time waiting for `list_messages` API response | `common-chat.js:860` |
| `renderMessages` | Full render pipeline | `common-chat.js:2652` |
| `renderChunk#N` | Each single-card chunk | `common-chat.js:3024` |
| `buildCard#N` | Building one message card | `common-chat.js:2692` |
| `cardTemplate#N` | jQuery HTML template parsing | `common-chat.js:2721` |
| `renderInner` | `renderInnerContentAsMarkdown` per card | `common.js:5591` |
| `processContentWithDetails` | Section splitting + per-section markdown parse | `common.js:5180` |
| `marked.marked` | Global markdown parse (skipped by R3 when sections pre-rendered) | `common.js:5479` |
| `innerHTML` | DOM write per card | `common.js:5717` |
| `applyModelResponseTabs` | Tab layout construction | `common.js:5773` |
| `updateMessageToc` | ToC generation | `common.js:5796` |
| `applyUIState` | Section collapse state restore | `common.js:5810` |
| `showMore` | Show/hide wrapper construction | `common.js:1561` |
| `immediate_callback` | showMore + decorateNav callback | `common.js:5881` |
| `postRenderWork` | Mermaid + dropdowns + URL scroll | `common-chat.js:2913` |
| `mermaidRun` | Mermaid diagram rendering | `common-chat.js:2937` |
| `dropdownInit` | Bootstrap dropdown initialization | `common-chat.js:2948` |
| `fullyInteractive` | Total time from conversation switch to all deferred work done | `common-chat.js:2998` |
| `mathJaxTypeset` | Per-element MathJax typeset (R5 scheduler) | `common.js:164` |
| `doubtsFetch` / `pinsFetch` | Network time for doubts/pins fetches | `common-chat.js:924-927` |
| `applyDoubts` / `applyPins` | DOM application after render completes | `common-chat.js:930-940` |

### Usage

`window._PERF` is enabled by default (`common.js:53`). After loading a
conversation, a summary table auto-prints to the console.

```javascript
// In browser console:
_perfSummary()    // reprint summary table
_perfJSON()       // get JSON string (auto-copies to clipboard)
_perfReset()      // clear timings
window._PERF = false  // disable all perf logging
```

### Example output (80-message conversation, 4 math cards)

| Label | Count | Total (ms) | Avg (ms) | Max (ms) |
|-------|-------|-----------|---------|---------|
| mathJaxTypeset | 4 | 69,137 | 17,284 | 30,774 |
| renderChunk | 80 | 7,498 | 94 | 391 |
| buildCard | 80 | 7,207 | 90 | 377 |
| renderInner | 80 | 6,741 | 84 | 368 |
| immediate_callback | 80 | 3,140 | 39 | 200 |
| showMore | 52 | 3,093 | 60 | 198 |
| networkWait | 1 | 2,569 | - | - |
| processContentWithDetails | 50 | 1,228 | 25 | 190 |
| applyModelResponseTabs | 47 | 946 | 20 | 79 |
| updateMessageToc | 80 | 657 | 8 | 42 |
| innerHTML | 80 | 386 | 5 | 26 |
| cardTemplate | 80 | 219 | 3 | 26 |
| marked.marked | 30 | 193 | 6 | 115 |
| applyUIState | 80 | 65 | 1 | 3 |

Key insight: MathJax is 90% of total wall time. Non-MathJax rendering is ~7.5s
for 80 cards. The yielding scheduler (R5) keeps the page responsive but MathJax 2
is inherently slow. Next step: MathJax 3 migration or viewport-based deferral.

## Console Cleanup

**131 debug `console.log`/`console.warn` calls** commented out across 4 files,
all prefixed with `// [DEBUG]` for easy re-enablement:

| File | Logs removed | Examples |
|------|-------------|---------|
| `common.js` | 23 | applyModelResponseTabs tracing, visual/slide/copy/cache diagnostics |
| `common-chat.js` | 27 | Stream diagnostics, show_more debug, cancellation traces, suggestion logs |
| `chat.js` | 21 | Settings modal, terminal, user details, model catalog |
| `doubt-manager.js` | 60 | Button injection debug, thread state, streaming diagnostics |

No error handlers were touched. Console output during profiling now only shows
perf marks + actual errors.

## Bug Fixes

### PDF.js iframe relative URL

**File:** `interface/interface.html:128`

Changed `src="interface/pdf.js/web/viewer.html"` to `src="/interface/pdf.js/web/viewer.html"`.
Without the leading `/`, the browser resolved the path relative to the current
URL, which includes the conversation ID (e.g., `/c/abc123/interface/pdf.js/...`),
causing 404s for locale files.

### Missing semicolons causing IIFE parse error

**File:** `interface/common-chat.js:2830,2842`

`msgElements = [$(cardElem)]` lacked semicolons. The IIFE on the next line
`(function(_ce, _mt, _mid, _adid) {...})()` was parsed as a function call on the
array result: `[$(cardElem)](function...)`. Arrays are not callable — TypeError.
Added semicolons to both lines.

## MathJax Integration Points (Audit)

### Configuration (3 HTML files, inconsistent)

| File | CDN Config | Output Mode | TeX Extensions | Macros | skipTags |
|------|-----------|-------------|---------------|--------|----------|
| `interface.html` | `TeX-AMS-MML_HTMLorMML` | HTML-CSS | AMSmath, AMSsymbols, noErrors, noUndefined, color | `\RR`, `\bold`, `\red` | code, pre, math, script |
| `shared.html` | `TeX-MML-AM_CHTML` | CommonHTML | None | None | code, pre |
| `render_mermaid.html` | `TeX-AMS_HTML` | HTML-CSS | None (CDN defaults) | None | None (CDN defaults) |

Note: `shared.html` has duplicate config blocks (lines 42 and 146) and incoherent
delimiter config (`\(` and `\[` appear in both `inlineMath` and `displayMath`).

### Direct `MathJax.Hub.Queue(["Typeset", ...])` call sites (16 total)

| File | Count | Guard | Uses Scheduler? |
|------|-------|-------|----------------|
| `common.js` (scheduler _drain) | 1 | None (assumes loaded) | Is the scheduler |
| `common.js` (streaming path) | 1 | None | No — streaming self-paced |
| `doubt-manager.js` | 6 | `typeof MathJax !== 'undefined' && MathJax.Hub` | No |
| `temp-llm-manager.js` | 3 | Same guard | No |
| `markdown-editor.js` | 1 | Same guard | No |

Plus `MathJax.Hub.Queue(callback)` at:
- `common.js` (drawio sequencing, post-typeset callback)
- `rendered-state-manager.js` (queue-drain wait before IndexedDB snapshot)

### Known bottleneck

MathJax 2.7.5 HTML-CSS output measures each glyph by inserting hidden DOM elements
and reading `offsetWidth`/`offsetHeight`, forcing synchronous layout reflow per
measurement. For complex equations, this compounds into 10-30s per card. The yielding
scheduler (R5) keeps the page responsive but cannot reduce total typeset time.

**Next steps:**
- **Viewport-based MathJax deferral**: Only typeset visible cards; lazy-typeset
  off-screen cards via IntersectionObserver
- **MathJax 3 migration**: CHTML output (CSS-based positioning, no DOM measurement),
  2-5x faster, Promise-based API. Requires updating all 16 call sites, 3 HTML configs,
  and streaming path. High impact but medium-risk migration.

## Files Modified

| File | Changes |
|------|---------|
| `interface/common.js:46-193` | Perf instrumentation utilities + yielding MathJax scheduler |
| `interface/common.js:1561` | showMore() perf mark |
| `interface/common.js:5105` | `skip_deferred_formatting` parameter |
| `interface/common.js:5805-5857` | Scheduler integration (history) + direct Queue (streaming) |
| `interface/common-chat.js:692-695` | _perfReset + scheduler clear on conversation switch |
| `interface/common-chat.js:921-940` | R2 fetch-early with perf marks (doubtsFetch/pinsFetch/applyDoubts/applyPins) |
| `interface/common-chat.js:2652-2998` | renderMessages + _buildMessageCard + _runPostRenderWork perf marks |
| `interface/common-chat.js:2830,2842` | Semicolon fix (IIFE parse error) |
| `interface/common-chat.js:2960` | CHUNK_SIZE = 1 |
| `interface/chat.js` | 21 debug logs commented out |
| `interface/doubt-manager.js` | 60 debug logs commented out |
| `interface/interface.html:128` | PDF.js iframe URL fix |

## Related Features

- [Scroll Preservation](../scroll_preservation/README.md) — CSS scroll anchoring and JavaScript anchor restoration
- [Multi-Model Response Tabs](../multi_model_response_tabs/README.md) — Tab rendering that triggers DOM changes
- [ToC Streaming Fix](../toc_streaming_fix/README.md) — Collapsed ToC reduces reflow during streaming
- [Math Streaming Reflow Fix](../math_streaming_reflow_fix/README.md) — Math-aware render gating, min-height stabilization
