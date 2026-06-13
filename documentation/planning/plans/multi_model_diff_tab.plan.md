# Multi-Model Diff Tab

## Motivation

When users select multiple models, responses appear as tabs in the message card header. Currently there's no way to quickly understand how models differ without reading each response fully and mentally comparing. This feature adds:
1. **Badge counts** on non-primary model tabs showing additions/contradictions at a glance
2. **A "⚡ Diff" tab** with the actual unique content from secondary models, grouped by model

## Requirements

- Pre-computed: fires immediately after multi-model response completes
- Persisted in message text (loads on reload via `<answer_diff>` tags, like `<answer_tldr>`)
- Parallel LLM calls: one per secondary model (vs primary), yielded as each completes
- Diff tab shows loading spinner until all diffs arrive
- Detail field contains **actual content** in markdown (not summaries about content)
- Empty diff (all models agree) shows "✅ All models agree" in the diff tab
- Badges: `+N ⚠M` format (additions + contradictions count)
- Diff tab body: grouped by model, with typed sections (addition/contradiction/omission)
- Multi-model only (not single-model + TLDR)
- Pairwise vs primary only for now; architecture supports pairwise between all models later

## UX Decisions

| Decision | Choice |
|----------|--------|
| Badge style | `+3 ⚠1` (count of additions and contradictions) |
| Diff tab ordering | Group by model |
| Empty diff | Show "✅ All models agree" |
| Diff tab loading | Spinner until LLM calls complete |
| Detail content | Actual information in markdown, directly renderable |
| Tab position | After model tabs, before TLDR: `[Model A] [Model B (+2⚠1)] [⚡ Diff] [TLDR]` |

## Architecture

### Data Flow

```
stream_multiple_models completes → model_responses dict available
    │
    ├─ Model A text (primary, first in list)
    ├─ Model B text → fire diff LLM (A vs B) via get_async_future
    ├─ Model C text → fire diff LLM (A vs C) via get_async_future
    │                        (parallel)
    │
    ▼ As each future completes:
    yield {"text": "\n<answer_diff model=\"B\" vs=\"A\">\n{json}\n</answer_diff>\n"}
    → persisted in message text
    → streamed to frontend
```

### LLM Call

- Model: `VERY_CHEAP_LLM[0]` (gemini-flash-lite) — analytical comparison, not creative
- Cost: ~$0.0005 per pair (~1k tokens in, ~300 out)
- Called via `get_async_future` for parallelism
- `stream=False` since we need complete JSON

### Prompt Design

```
You are comparing two LLM responses to the same question. Your job is to extract the ACTUAL unique content from Response B that isn't in Response A.

Response A (PRIMARY - from {primary_name}):
<response_a>
{primary_text}
</response_a>

Response B (from {secondary_name}):
<response_b>
{secondary_text}
</response_b>

Compare B against A. Identify:
1. ADDITIONS: Information in B not present in A. Extract the actual content.
2. CONTRADICTIONS: Where B makes different claims than A. Show what B actually says.
3. OMISSIONS: Topics A covers that B skips entirely (brief note only).

Output ONLY valid JSON (no markdown fences, no explanation):
{
  "stats": {"additions": N, "contradictions": N, "omissions": N},
  "badge_summary": "+N ⚠M",
  "diff_sections": [
    {
      "type": "addition|contradiction|omission",
      "topic": "2-5 word heading",
      "detail": "The actual content/information in markdown format. For additions: write the full explanation/info that B provides. For contradictions: write what B claims (the reader already has A). For omissions: one sentence noting what's missing."
    }
  ]
}

Rules:
- detail field must contain the ACTUAL information — not "Model B explains X" but the explanation itself
- Use markdown in detail (code blocks, bold, lists) for readability
- Only include genuinely meaningful differences (ignore phrasing/formatting/ordering differences)
- If responses are essentially the same, return {"stats": {"additions": 0, "contradictions": 0, "omissions": 0}, "badge_summary": "", "diff_sections": []}
- Maximum 8 diff_sections total
- badge_summary format: "+N" if only additions, "+N ⚠M" if contradictions exist, "" if empty
```

### JSON Output Schema

```json
{
  "model": "anthropic/claude-opus-latest",
  "vs": "google/gemini-pro-latest",
  "stats": {"additions": 2, "contradictions": 1, "omissions": 1},
  "badge_summary": "+2 ⚠1",
  "diff_sections": [
    {
      "type": "addition",
      "topic": "Async cleanup guarantees",
      "detail": "When a task is cancelled, `__aexit__` is still invoked with `CancelledError`:\n\n```python\nasync with resource() as r:\n    await op()  # cancelled here\n# __aexit__ still runs\n```\n\nThis ensures resources are always released even during cancellation."
    },
    {
      "type": "contradiction",
      "topic": "Default timeout value",
      "detail": "The default timeout is `None` (no timeout), not 30 seconds.\n\n> `asyncio.wait_for(aw, timeout)` — if timeout is None, block until complete."
    },
    {
      "type": "omission",
      "topic": "Performance benchmarks",
      "detail": "Does not include the concrete latency measurements (3.2ms avg) that the primary response provides."
    }
  ]
}
```

### Persistence Format

Emitted inline in the streamed response (after model responses, before `</answer>`):

```html
<answer_diff model="anthropic/claude-opus-latest" vs="google/gemini-pro-latest">
{"stats":{"additions":2,"contradictions":1,"omissions":1},"badge_summary":"+2 ⚠1","diff_sections":[...]}
</answer_diff>
```

Multiple `<answer_diff>` blocks if 3+ models selected (one per secondary).

### Frontend Rendering

**In `applyModelResponseTabs()` (`interface/common.js`):**

1. Detect `<answer_diff>` elements/text in the message body
2. Parse JSON from each block
3. Match `model` attribute to the corresponding tab nav-link
4. Inject badge: `<span class="model-diff-badge">+2 ⚠1</span>` into the nav-link
5. Build the "⚡ Diff" tab:
   - If no `<answer_diff>` blocks found but multi-model detected: show spinner
   - If all diffs have `stats` all zero: show "✅ All models agree"
   - Otherwise: render grouped by model with typed sections

**Diff tab body HTML structure:**

```html
<div class="diff-tab-content">
  <div class="diff-model-group">
    <h6 class="diff-model-header">vs Claude Opus <span class="model-diff-badge">+2 ⚠1</span></h6>
    <div class="diff-section diff-addition">
      <div class="diff-section-header">✅ Async cleanup guarantees</div>
      <div class="diff-section-body">[rendered markdown]</div>
    </div>
    <div class="diff-section diff-contradiction">
      <div class="diff-section-header">⚠️ Default timeout value</div>
      <div class="diff-section-body">[rendered markdown]</div>
    </div>
  </div>
</div>
```

**During streaming:** The diff tab shows a small spinner. As each `<answer_diff>` block arrives, it's parsed and appended to the diff tab in real time.

## Implementation Tasks

### Backend (Conversation.py / common.py)

1. After the ensemble/multi-model streaming loop completes, check if `ensemble` is True and `model_responses` has 2+ entries
2. Identify primary (first model in `model_names` list)
3. Fire parallel `get_async_future` calls with the diff prompt for each secondary
4. As each completes, yield `<answer_diff>` block (with model/vs attributes + JSON body)
5. Add to `answer` string for persistence

### Frontend (common.js)

1. In `applyModelResponseTabs()`: after building model tabs, scan for `[data-answer-diff]` or `<answer_diff>` text
2. Parse JSON from each diff block
3. Inject badges into corresponding model nav-links
4. Add "⚡ Diff" tab (always present if multi-model; shows spinner → content → or "all agree")
5. Render diff sections as HTML with markdown rendering (use existing `marked` library)

### CSS

- `.model-diff-badge` — small inline badge on nav-link (font-size 0.65rem, green/orange colors)
- `.diff-tab-content` — padding and layout
- `.diff-model-group` — border-bottom separator between model groups
- `.diff-section` — left border color by type (green/orange/gray)
- `.diff-section-header` — bold topic with icon
- `.diff-section-body` — rendered markdown content
- `.diff-loading-spinner` — small spinner

## Key Files

| File | Changes |
|------|---------|
| `Conversation.py` | Add diff generation after multi-model stream (around line 11082) |
| `common.py` | Possibly add a `generate_model_diffs()` helper |
| `interface/common.js` | Extend `applyModelResponseTabs()` with diff parsing, badge injection, diff tab |
| `interface/style.css` or inline `<style>` | Badge and diff section styling |

## Future Extensions

- Pairwise diffs (all models vs all models) — architecture already supports by changing the loop
- "Show inline" toggle — highlights corresponding sections in primary tab on hover
- Diff quality scoring — flag when models fundamentally disagree vs just add detail
- User preference to disable diff generation (saves compute)
