# Math Streaming Reflow Fix & Markdown Normalization

## Overview

This feature addresses two categories of rendering issues during streaming of LLM responses:

1. **Math equation reflow/jumps** — display math (`$$...$$` and `\[...\]`) causes layout instability during streaming because MathJax re-typesets the entire section on every incremental update.
2. **Over-indented list items rendered as code** — some LLMs indent bullet points with 4+ spaces (e.g., `    *   text`), which `marked.js` treats as indented code blocks instead of list items.

Both issues occur in the rendering pipeline between `renderStreamingResponse()` and `renderInnerContentAsMarkdown()`.

---

## Problem 1: Math Streaming Reflow

### Symptoms

- During streaming, math equations "flash" between raw delimiter text and rendered form.
- The page jumps/scrolls when math-heavy content is re-rendered.
- Equations that were already typeset get destroyed and recreated every ~50 characters of new text.

### Root Causes

1. **Full section re-rendering**: `renderStreamingResponse()` calls `renderInnerContentAsMarkdown(elem, null, true, rendered_answer)` with the ENTIRE section text every ~50 characters. This replaces innerHTML and queues a full MathJax re-typeset, including already-rendered equations.
2. **Missing `\\[...\\]` detection**: `getTextAfterLastBreakpoint()` only tracked `$$` display math blocks as protected environments. `\\[...\\]` display math (which arrives from the backend after `process_math_formatting()` doubles the backslashes) was not tracked, so breakpoints could be placed mid-equation.
3. **Rendering during incomplete math**: No check prevented a render cycle while inside an unclosed `$$` or `\\[` block, causing MathJax to attempt typesetting of incomplete expressions.
4. **Layout collapse**: When innerHTML is replaced, the element shrinks to raw-text height. Until MathJax re-typesets (async), there's a visible height jump.

### Solution: Five Coordinated Changes (A–D + E)

#### A. Backend: `math_formatting.py` — Display Math Newline Insertion

**New function**: `ensure_display_math_newlines(text)`

```python
def ensure_display_math_newlines(text: str) -> str:
    """
    Ensure display math delimiters (\\[ and \\]) are on their own lines.
    Inserts \\n before \\[ and after \\] when adjacent to non-newline content.
    """
```

- Called inside `stream_with_math_formatting()` after `process_math_formatting()` on each yielded chunk.
- **Why**: The frontend's `getTextAfterLastBreakpoint()` works line-by-line. Putting `\\[` and `\\]` on their own lines makes them trivially detectable as block boundaries.
- **Only affects display math** (`\\[`/`\\]`), not inline math (`\\(`/`\\)`).

**Integration point**:

```python
# In stream_with_math_formatting():
processed_text = process_math_formatting(to_process)
processed_text = ensure_display_math_newlines(processed_text)  # NEW
yield processed_text
```

**Edge cases**:
- If `\\[` is already at the start of a line, no extra newline is added (the regex requires a preceding non-newline char).
- During streaming, chunk boundaries mean `\\]` at the end of a chunk may not get a trailing newline until the next chunk carries the adjacent content. This is acceptable — the UI-side `isInsideDisplayMath()` handles incomplete blocks.

#### B. Frontend: `common-chat.js` — `isInsideDisplayMath()` Helper

**New function**: detects whether accumulated text currently ends inside an unclosed display math block.

```javascript
function isInsideDisplayMath(text) → boolean
```

**Algorithm**:
1. Strip complete fenced code blocks (`\`\`\`...\`\`\``) so math delimiters inside code don't count.
2. Handle incomplete code fences (odd `\`\`\`` count → remove from last fence to end).
3. Count `\\[` vs `\\]` — if opens > closes → inside bracket math.
4. Count `$$` — if odd count → inside dollar math.

**Used by**: The math-aware rendering gate in `renderStreamingResponse()` (section C).

#### C. Frontend: `common-chat.js` — Improved `getTextAfterLastBreakpoint()`

The breakpoint detector now tracks **three** types of display math (previously only `$$`):

| State Variable | Delimiter | Previously Tracked? |
|---|---|---|
| `inMathBlock` | `$$...$$` | ✅ Yes |
| `inDisplayMathBracket` | `\\[...\\]` | ❌ No → ✅ Now tracked |
| `inCodeBlock` | ` \`\`\`...\`\`\` ` | ✅ Yes |

**New breakpoint types added**:
- `"after-display-math-bracket"` — placed after a line containing closing `\\]`
- `"after-display-math-dollar"` — placed after a line containing closing `$$` (or complete `$$...$$` on one line)

**Improved unclosed-structure validation** (prevents breakpoints inside incomplete structures):
- Now checks `\\[` vs `\\]` count in addition to `$$` count and ` \`\`\` ` count.

**Improved paragraph-break safety**:
- The `isAfterMath` / `isBeforeMath` checks now also look for `\\]` and `\\[` patterns (not just `$$`/`$`).

#### D. Frontend: `common-chat.js` — Math-Aware Render Gate in `renderStreamingResponse()`

The rendering decision point was changed from:

```javascript
// BEFORE: renders every 50 chars, even inside math
if (rendered_answer.length > content_length + 50 && ...)
```

To:

```javascript
// AFTER: skips rendering inside math, uses dynamic threshold
var insideMath = isInsideDisplayMath(rendered_answer);
var hasMathContent = /* checks for \\[ or $$ in section */;
var renderThreshold = hasMathContent ? 200 : 80;

if (!insideMath
    && (rendered_answer.length > content_length + renderThreshold || breakpointResult.hasBreakpoint)
    && !rendered_till_now.includes(rendered_answer)) {
    renderInnerContentAsMarkdown(elem_to_render, ...);
}
```

**Three behaviors**:
1. **Inside unclosed math block** → rendering is **completely deferred** until the block closes.
2. **Section contains rendered math** → threshold is **200 chars** (fewer MathJax re-runs).
3. **Section has no math** → threshold is **80 chars** (smooth text streaming).

#### E. Frontend: `common.js` — Min-Height Stabilization in `renderInnerContentAsMarkdown()`

During `continuous=true` (streaming) renders:

1. **Before innerHTML replacement**: Capture the element's current `offsetHeight` and set it as CSS `min-height`. This prevents the element from collapsing when raw markdown text replaces MathJax-rendered content.
2. **After MathJax re-typesets**: Clear `min-height` via a `MathJax.Hub.Queue()` callback so the element sizes naturally.

```javascript
// Lock height before innerHTML replacement
if (continuous && _curHeight > 50) {
    targetElement.style.minHeight = _curHeight + 'px';
    _lockedMinHeight = true;
}

// Unlock after MathJax finishes
MathJax.Hub.Queue(function() {
    if (_lockedMinHeight) targetElement.style.minHeight = '';
});
```

Only locks when height > 50px (avoids locking empty/new elements).

---

## Problem 2: Over-Indented List Items as Code Blocks

### Symptoms

- Bullet points with inline math appear inside `<pre><code>` blocks with hljs syntax highlighting.
- The math delimiters show as raw text instead of being typeset by MathJax.
- Occurs when LLMs format list items with 4+ spaces of indentation (e.g., `    *   $R_{x}$ text`).

### Root Cause

In CommonMark / GFM markdown, **4 or more leading spaces create an indented code block**. `marked.js` correctly interprets `    *   text` as code, not as a list item. This is standard markdown behavior, but LLMs don't always follow the convention.

### Solution: `normalizeOverIndentedLists()` in `common.js`

**New function** added near the `marked` parser setup:

```javascript
function normalizeOverIndentedLists(text) → string
```

**Algorithm**:
1. Split text into lines and iterate.
2. Skip fenced code blocks (` \`\`\` ` and `~~~`) entirely.
3. For lines with 4+ leading spaces followed by a list marker (`*`, `-`, `+`, or `1.`), **subtract exactly 4 spaces**.
4. For continuation lines (non-blank, non-list-marker lines with 4+ spaces that follow a de-indented list item), also subtract 4 spaces.
5. Blank lines maintain the de-indent state (blank between list items is normal).
6. Lines with <4 spaces of indentation end the de-indent run.

**Why subtract 4 instead of stripping to zero**:
Preserves relative nesting — `8-space` items become `4-space` (nested), `4-space` items become `0-space` (top-level). This means the list structure is preserved even if the LLM used consistent but excessive indentation.

**Integration**:
Called at both `marked.marked()` call sites in `renderInnerContentAsMarkdown()`:

```javascript
// Normal path:
htmlChunk = marked.marked(normalizeOverIndentedLists(html), { renderer: markdownParser });

// Slide-text path:
var renderedText = marked.marked(normalizeOverIndentedLists(part.content), { renderer: markdownParser });
```

---

## Complete Data Flow

```
LLM API (streaming tokens)
  │
  ▼
stream_text_with_math_formatting()  OR  stream_with_math_formatting()   [math_formatting.py]
  ├─ _find_safe_split_point()          Buffer until math delimiters complete
  ├─ process_math_formatting()         \[ → \\[,  \] → \\],  \( → \\(,  \) → \\)
  └─ ensure_display_math_newlines()    Insert \n around \\[ and \\]
  │
  ▼
Conversation.__call__() → JSON wire    [Conversation.py → endpoints/conversations.py]
  │
  ▼
renderStreamingResponse()              [interface/common-chat.js]
  ├─ Accumulate text in rendered_answer
  ├─ isInsideDisplayMath(rendered_answer)   Skip render if inside unclosed math
  ├─ getTextAfterLastBreakpoint()           Split into committed sections at safe boundaries
  │   └─ Tracks: code blocks, $$, \\[...\\], <details>, lists, blockquotes
  ├─ Dynamic threshold (80 / 200 chars)     Fewer re-renders for math-heavy sections
  └─ renderInnerContentAsMarkdown()         Render current section
      │
      ▼
renderInnerContentAsMarkdown()         [interface/common.js]
  ├─ normalizeOverIndentedLists(html)       Fix 4+ space-indented list items
  ├─ Lock min-height (continuous mode)      Prevent layout collapse
  ├─ marked.marked(html)                    Markdown → HTML
  ├─ innerHTML replacement                  DOM update
  ├─ MathJax.Hub.Queue(["Typeset", ...])    Typeset math
  └─ MathJax.Hub.Queue(unlock min-height)   Release height lock after typesetting
```

---

## Files Modified

| File | Functions Added/Changed | Purpose |
|------|------------------------|---------|
| `math_formatting.py` | `ensure_display_math_newlines()` (new), `stream_with_math_formatting()` (modified), `stream_text_with_math_formatting()` (new) | Newlines around display math delimiters for easier frontend detection; text-string variant for shim path |
| `interface/common-chat.js` | `isInsideDisplayMath()` (new), `getTextAfterLastBreakpoint()` (improved), `renderStreamingResponse()` (modified) | Math-aware breakpoints, render gating during unclosed math |
| `interface/common.js` | `normalizeOverIndentedLists()` (new), `renderInnerContentAsMarkdown()` (modified), `_queueMathJax()` (modified) | List normalization, min-height locking/unlocking |

---

## Function Signatures

### Backend (Python)

```python
def ensure_display_math_newlines(text: str) -> str
def process_math_formatting(text: str) -> str
def _find_safe_split_point(text: str, min_keep: int = 1) -> int
def stream_with_math_formatting(response: Iterator) -> Generator[str, None, None]
def stream_text_with_math_formatting(text_iterator: Iterator) -> Generator[str, None, None]
```

### Frontend (JavaScript)

```javascript
function isInsideDisplayMath(text) → boolean
function getTextAfterLastBreakpoint(text) → { hasBreakpoint, textBeforeBreakpoint?, textAfterBreakpoint, breakpointType?, reason? }
function normalizeOverIndentedLists(text) → string
function renderInnerContentAsMarkdown(jqelem, callback, continuous, html, immediate_callback, defer_mathjax)
```

---

## Implementation Notes

- The `\\[` pattern in JavaScript runtime strings corresponds to `'\\\\['` in JS source code (two escaped backslashes + bracket). In regex: `/\\\\\[/g`.
- `ensure_display_math_newlines` only handles `\\[`/`\\]` (not `$$`), because `$$` doesn't go through backslash escaping and is already well-handled by the frontend `getTextAfterLastBreakpoint()` line-level tracking.
- The min-height approach was chosen over double-buffering (two hidden elements swapped after MathJax) for simplicity. Double-buffering could be a future enhancement if min-height proves insufficient for complex layouts.
- The dynamic threshold (80 vs 200 chars) balances streaming smoothness against MathJax overhead. The 200-char math threshold means a display equation is shown 2–3 fewer times per section than the old 50-char threshold.
- `normalizeOverIndentedLists` subtracts 4 spaces instead of stripping to zero so that `8-space → 4-space` nesting relationships are preserved. Continuation lines within a de-indented run are also de-indented to avoid partial code-block treatment.

---

## Testing Notes

### Backend (`math_formatting.py`)

Run the built-in test suite:

```bash
conda activate science-reader
python math_formatting.py
```

All 7 tests should pass. Tests 3 and 5 were updated to expect the new newline-insertion behavior.

### Frontend (manual)

Test scenarios:
1. **Display math with `$$`**: Stream a response with `$$equation$$` blocks. Verify no flash of raw `$$` delimiters during streaming.
2. **Display math with `\[...\]`**: Stream a response with `\[equation\]`. Verify smooth rendering.
3. **Mixed math and text**: Stream a response alternating text paragraphs and display math. Verify sections split at math boundaries.
4. **Over-indented list items**: Stream a response where the LLM outputs `    *   bullet text`. Verify bullets render as a proper list, not as a code block.
5. **Nested lists**: Stream `    *   top` followed by `        *   nested`. Verify nesting is preserved.
6. **Code blocks with math delimiters inside**: Ensure `$$` or `\\[` inside ``` fenced code blocks are NOT treated as math boundaries.

---

## Known Limitations & Future Work

1. **Single-line inline math** (`$...$`) is not tracked as a protected environment in `getTextAfterLastBreakpoint()`. This could cause breakpoints mid-inline-math if a paragraph break happens to coincide. Low impact since inline math is short.
2. **Min-height lock** can cause briefly oversized elements if MathJax renders smaller content (e.g., removing a long equation and replacing with short text). The height releases after MathJax completes, so the visual impact is minimal.
3. **`normalizeOverIndentedLists`** strips indentation from ALL 4+-space list items, including legitimately deeply-nested ones (e.g., 3-level nesting). In practice, LLMs rarely produce 3+ level nesting with consistent 4-space indentation, so this is acceptable.
4. **Double-buffering** (rendering new content into a hidden element, then swapping after MathJax) would eliminate reflow entirely but adds implementation complexity. Consider if min-height proves insufficient.

---

## Related Features

- [Conversation Flow](../conversation_flow/README.md) — End-to-end message pipeline including streaming render
- [Rendering Performance](../rendering_performance/README.md) — MathJax deferred rendering, `defer_mathjax` parameter, `immediate_callback`
- [Scroll Preservation](../scroll_preservation/README.md) — Scroll stability during DOM changes from rendering
- [Multi-Model Response Tabs](../multi_model_response_tabs/README.md) — Tab creation triggers DOM changes this feature helps stabilize
