# Math Streaming Reflow Fix & Markdown Normalization

**Date:** February 2026
**Category:** Bug Fix / UX Improvement
**Feature Doc:** [features/math_streaming_reflow_fix/README.md](../features/math_streaming_reflow_fix/README.md)

## Summary

Fixed two rendering issues in the chat UI:

1. **Math equation reflow during streaming** — Display math (`$$...$$` and `\[...\]`) caused visual jumps during streaming because MathJax re-typeset the entire section on every incremental update (~50 chars). The fix adds math-aware render gating, improved breakpoint detection, and min-height stabilization.

2. **Over-indented list items rendered as code** — LLMs sometimes indent bullet points with 4+ spaces (e.g., `    *   text`), which `marked.js` treats as indented code blocks. The fix normalizes these before markdown parsing.

## Changes

### Backend: `math_formatting.py`

| Change | Details |
|--------|---------|
| **New function**: `ensure_display_math_newlines()` | Inserts newlines around `\\[` and `\\]` display math delimiters to aid frontend breakpoint detection |
| **Modified**: `stream_with_math_formatting()` | Integrated `ensure_display_math_newlines()` after `process_math_formatting()` |
| **Updated**: inline test expectations | Tests 3 and 5 updated for new newline-insertion behavior |

### Frontend: `interface/common-chat.js`

| Change | Details |
|--------|---------|
| **New function**: `isInsideDisplayMath(text)` | Detects unclosed `$$` or `\\[` blocks; strips code blocks before counting |
| **Improved**: `getTextAfterLastBreakpoint(text)` | Tracks `\\[...\\]` as protected environment; adds breakpoint types `"after-display-math-bracket"` and `"after-display-math-dollar"`; validates `\\[` vs `\\]` count in unclosed-structure check |
| **Modified**: `renderStreamingResponse()` render gate | Skips rendering inside unclosed math; dynamic threshold (80 chars for text, 200 chars for math-heavy sections) |

### Frontend: `interface/common.js`

| Change | Details |
|--------|---------|
| **New function**: `normalizeOverIndentedLists(text)` | Subtracts 4 spaces from lines with 4+ leading spaces + list marker; handles continuation lines; skips code blocks |
| **Modified**: `renderInnerContentAsMarkdown()` | Calls `normalizeOverIndentedLists()` before `marked.marked()`; adds min-height lock during `continuous=true` streaming renders |
| **Modified**: `_queueMathJax()` | Releases min-height lock after MathJax finishes typesetting |

## Files Modified

| File | Lines Changed (approx) |
|------|----------------------|
| `math_formatting.py` | +66 |
| `interface/common-chat.js` | +153 |
| `interface/common.js` | +113 |

## Testing

- Backend: `python math_formatting.py` — 7/7 tests pass
- Frontend: Manual testing with math-heavy and list-heavy LLM responses during streaming

## Impact

- Math equations render smoothly during streaming without flash/jump
- Bullet points with inline math render as proper lists instead of code blocks
- Reduced MathJax re-typesetting frequency for math-heavy sections
- Layout stability improved via min-height locking

## Related

- [Rendering Performance](../features/rendering_performance/README.md)
- [Scroll Preservation](../features/scroll_preservation/README.md)
- [Conversation Flow](../features/conversation_flow/README.md)
