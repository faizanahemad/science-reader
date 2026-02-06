# Tab-Based Rendering (Multi-Model + TLDR)

This doc captures how the chat UI turns multi-model responses and long-answer TLDR summaries into a tabbed “Main / Model / TLDR” interface, and the fixes we made to keep it stable across streaming, `showMore()`, reloads, and cached DOM snapshots.

## Goals

- Present multi-model outputs as tabs (one per model) instead of a stack of `<details>`.
- For long single-model answers, present “Main” and “TLDR” tabs.
- Avoid duplicate content (main answer visible above/below tabs).
- Survive:
  - streaming incremental renders
  - `showMore()` DOM rebuilds
  - page reloads (including RenderedStateManager IndexedDB snapshots)

## Output Formats (Server)

### Multi-model

Server streams markup like:

```html
<details open>
  <summary>Response from gpt-4.1</summary>
  ...model answer...
</details>

<details open>
  <summary>Response from claude-sonnet</summary>
  ...model answer...
</details>
```

The UI derives tab labels from the `<summary>` string.

### TLDR for long answers

When a long answer triggers a TLDR, the server appends:

```html
---

<answer_tldr>
  <details>
    <summary><strong>📝 TLDR Summary (Quick Read)</strong></summary>
    ...tldr content...
  </details>
</answer_tldr>
```

Backend persistence note:
- `Conversation.persist_current_turn()` can inject this `<answer_tldr>...</answer_tldr>` block into the stored assistant `message.text` (controlled by `PERSIST_TLDR_IN_SAVED_ANSWER_TEXT`).
- This is required for reload/history, because the UI primarily re-renders from `message.text`.

## Parsing + Rendering (Frontend)

### Entry point

- Markdown rendering: `interface/common.js:renderInnerContentAsMarkdown()`
  - strips `<answer>` wrappers
  - converts `<answer_tldr>` tags to a stable wrapper:
    - `<answer_tldr>` -> `<div data-answer-tldr="true">`
  - optionally wraps `---` sections into `<details class="section-details">...` (used for the Table of Contents)
  - calls `applyModelResponseTabs(elem_to_render_in)` after writing rendered HTML

### Tab construction

- Tab builder: `interface/common.js:applyModelResponseTabs()`

What it looks for:
- Model sources: `<details>` blocks whose summary starts with `Response from ...`
- TLDR sources:
  - `[data-answer-tldr]` wrapper (preferred)
  - fallback: `<details>` whose summary contains `tldr`

What it creates:
- A `.model-tabs-container` containing Bootstrap `.nav-tabs` + `.tab-content`.
- Tab panes contain clones of the source nodes (not the original nodes).

## Single-Model+TLDR vs Multi-Model+TLDR (Key Difference)

### Why multi-model “just worked”

Multi-model responses include explicit `<details>` sources per model, so hiding/removing those `<details>` eliminates the raw content.

### Why single-model+TLDR was fragile

Single-model answers typically do NOT have `Response from ...` `<details>`.
So the only way to prevent the main answer from appearing twice is to hide the non-tab source containers (siblings in the message DOM).

In this repo, a single assistant card can have multiple render containers under the same message body during streaming/history:
- `#message-render-space.actual-card-text`
- `#message-render-space-md-render` (streaming sibling)
- `.less-text` / `.more-text` (created by `showMore()` which rebuilds DOM)

If tabs are inserted into one container but the others remain visible, the main answer appears above/below the tabs.

## The Stabilizing Fixes We Added

### 1) Re-apply tabs after `showMore()`

Problem:
- `showMore(..., as_html=true)` rebuilds the message DOM (wraps into `.less-text` + `.more-text`).
- Any earlier tab UI / hiding logic can be lost.

Fix:
- `interface/common.js:showMore()` calls `applyModelResponseTabs(moreText)`:
  - immediately after building `.more-text`
  - again when the user expands (toggle to show)

### 2) Validate TLDR content (avoid empty TLDR tabs)

Problem:
- During streaming/rebuilds, TLDR sources can exist but contain only partial markup (e.g. `<strong></strong>`), causing an empty TLDR tab.

Fix:
- `hasMeaningfulContent($elem)` heuristic (currently `> 10` chars of text)
- TLDR is only considered present if it passes `hasMeaningfulContent`
- TLDR sources are removed only after cloning validated TLDR content

See also: `documentation/features/multi_model_response_tabs/EMPTY_TLDR_FIX_CONTEXT.md`.

### 3) Preserve TLDR content across rebuilds/reloads

Problem:
- The first successful render may remove TLDR sources from the DOM.
- On reload or re-apply, the UI might rebuild tabs from an existing `.model-tabs-container` but have no TLDR source nodes left.

Fix:
- If a `.model-tabs-container` already exists, clone its TLDR pane content early (before clearing) and reuse it if needed.

### 4) Hide all source render containers consistently (single-model duplicate fix)

Problem:
- Hiding only `<details>` sources works for multi-model.
- Single-model needs sibling hiding across the whole message.

Fix:
- `applyModelResponseTabs()` scopes to the message body container (`.chat-card-body`).
- After inserting tabs, it hides all direct children of `.chat-card-body` except:
  - `.model-tabs-container`
  - `.message-toc-container`

This makes single-model+TLDR behavior match multi-model+TLDR: only the tab UI remains visible.

### 5) Guardrails: never leave the message blank

Problem:
- If tab insertion fails but sources are hidden, the card can show ToC but no content.

Fix:
- If `.model-tabs-container` isn’t attached to the DOM, restore hidden nodes.
- Final sanity check: if no `.model-tabs-container` is present in the root, unhide sources.

## Caching + Reload Notes

This UI has *two* persistence/caching layers that can preserve broken DOM:

1) Service worker cache
- `interface/service-worker.js` uses `CACHE_VERSION` (currently `v12`)

2) Rendered DOM snapshots in IndexedDB
- `interface/rendered-state-manager.js` uses `window.UI_CACHE_VERSION` as `RENDER_SNAPSHOT_VERSION`
- `interface/common.js` sets `window.UI_CACHE_VERSION` (currently `v12`)

When changing tab/render logic, bump both versions together so old JS + old snapshots don’t keep reproducing stale hidden-content states.

## Debugging Checklist

- Confirm the stored assistant `message.text` includes `<answer_tldr>...</answer_tldr>` (history/reload TLDR depends on this).
- Inspect a message card DOM:
  - `.chat-card-body` should contain exactly:
    - `.message-toc-container` (optional)
    - `.model-tabs-container`
    - hidden source nodes (marked `data-model-tabs-hidden="true"`)
- If behavior differs between reload vs fresh render:
  - clear the service worker and refresh
  - clear IndexedDB `science-chat-rendered-state` (or bump `UI_CACHE_VERSION`)

## 6) Stream-Safe `<answer_tldr>` Tag Handling

Problem:
- During streaming (`continuous=true`), the opening `<answer_tldr>` tag may arrive before the closing `</answer_tldr>`.
- The markdown-to-HTML conversion turns this unclosed tag into malformed HTML, which can cause the browser to wrap all subsequent content inside the TLDR div — hiding the main answer.

Fix in `renderInnerContentAsMarkdown()`:
```javascript
if (continuous && hasOpenAnswerTldr && !hasCloseAnswerTldr) {
    // Stream-safe: replace opening tag with placeholder until closing tag arrives
    html = html.replace(/<\s*answer_tldr\s*>/i, '<!--answer_tldr_pending-->');
}
```

When `continuous=false` (final render), both tags are present and converted normally:
```javascript
html = html.replace(/<\s*answer_tldr\s*>/gi, '<div data-answer-tldr="true">');
html = html.replace(/<\s*\/\s*answer_tldr\s*>/gi, '</div>');
```

## 7) `isLiveStreaming` Guard for Single-Model+TLDR

Problem:
- During streaming, `hasMeaningfulContent()` could count `<summary>` text from a partially-rendered TLDR `<details>` block, triggering premature tab creation.
- This hid the main answer content while TLDR was still being generated.

Fix in `applyModelResponseTabs()`:
- `hasMeaningfulContent()` ignores `<summary>` text when checking `<details>` elements.
- When `isLiveStreaming=true` and there's only 1 model detail (single-model), tabs are NOT built even if TLDR content exists — the TLDR is still being generated.

```javascript
var isLiveStreaming = $card.attr('data-live-stream') === 'true';

// Single model + TLDR during live streaming: don't build tabs yet
if (modelDetails.length <= 1 && isLiveStreaming && actuallyHasTldrContent) {
    shouldBuildTabs = false;
}
```

Multi-model (2+ models) tabs ARE built during streaming because the model tabs are needed immediately.

## 8) Scroll Preservation During Tab Creation

When tabs are first created or rebuilt (e.g., TLDR tab added after streaming), large DOM changes can shift the user's scroll position. Multiple approaches were tried and refined:

### What Didn't Work
- **scrollTop capture/restore inside `applyModelResponseTabs()`**: Captured AFTER `innerHTML` already shifted scroll.
- **Multiple nested restores**: `applyModelResponseTabs()`, `renderInnerContentAsMarkdown()`, and `showMore()` each trying to restore independently caused progressive drift.
- **Anchor-based restore competing with CSS anchoring**: In multi-model mode, CSS scroll anchoring already handled the shift, but JavaScript restore overrode it with a worse value.
- **Raw scrollTop restore**: When TLDR content was stripped from the Main tab clone, the page got ~2000px shorter, making the original scrollTop exceed maxScrollTop.
- **Scroll correction (any approach)**: Even a correct correction was visible to the user as a "scroll up then back down" jank because the browser painted the shifted position before the correction could run.

### Current Solution — Height Lock (Prevention, Not Correction)
The key insight is that scroll **correction** is fundamentally flawed — it's always visible. Instead, we **prevent** the shift from happening by locking container heights during DOM manipulation.

**Three height locks:**
1. **`applyModelResponseTabs()`** locks `$root` (`chat-card-body`) min-height before hiding children + inserting tabs, releases after all DOM changes.
2. **`showMore()`** locks closest `chat-card-body` min-height before `textElem.empty()` + rebuild, releases after `applyModelResponseTabs(moreText)`.
3. **Streaming `done` handler** locks card body min-height before `renderInnerContentAsMarkdown`, releases after all synchronous DOM work.

**Fallback layers:**
- **CSS `overflow-anchor: auto`** on `#chatView` and `.message-card` handles small deltas when height locks are released.
- **JavaScript anchor-based restore** as safety net: only runs if drift > 50px (CSS anchoring threshold).

See [Scroll Preservation](../scroll_preservation/README.md) for full implementation details and evolution history.

## Files Touched (Most Relevant)

- `interface/common.js`
  - `renderInnerContentAsMarkdown()` — stream-safe TLDR handling, `defer_mathjax` parameter
  - `applyModelResponseTabs()` — `isLiveStreaming` guard, `hasMeaningfulContent` improvements, **height lock** around DOM swap
  - `showMore()` — re-applies tabs after DOM rebuild, **height lock** around `textElem.empty()`
  - `captureChatViewScrollAnchorForCard()` — card-scoped anchor capture (last card forced)
  - `restoreChatViewScrollAnchor()` — anchor-based restore with card fallback
  - `window.UI_CACHE_VERSION`
- `interface/common-chat.js`
  - Calls renderer for history + streaming
  - Streaming `done` handler: **height lock** (outermost), anchor capture, CSS-threshold-aware restore (safety net)
  - `renderMessages`: `immediate_callback` for showMore, `defer_mathjax` for non-last cards
  - `scrollToHashTargetInCard()`: card-scoped safety guard
- `interface/style.css` — CSS scroll anchoring (`overflow-anchor: auto`), card spacing, ToC toggle button styling
- `interface/service-worker.js` (`CACHE_VERSION`)
- `interface/rendered-state-manager.js` (snapshot versioning)
- `Conversation.py` (`persist_current_turn()` TLDR injection)
- `common.py` (`PERSIST_TLDR_IN_SAVED_ANSWER_TEXT` env flag)
