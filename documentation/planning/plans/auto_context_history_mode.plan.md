# Auto Context History Mode

**Created:** 2026-04-09
**Status:** Planning
**Depends On:** History setting flow (`Conversation.py` reply()), Global Documents system (`database/global_docs.py`, `DocIndex.py`), running summary lifecycle (`persist_current_turn()`), existing LLM context extraction (`retrieve_prior_context_llm_based()`), collapsible UI sections (`common.py:collapsible_wrapper()`, `common.js`), tool-calling framework (`code_common/tools.py`)
**Related Docs:**
- `documentation/features/global_docs/README.md` — Global docs system, reference syntax, RAG pipeline
- `documentation/features/conversation_flow/conversation_flow.md` — Chat message pipeline
- `documentation/features/conversation_model_overrides/README.md` — Per-conversation model override system
- `documentation/features/tool_calling/` — Tool-calling framework and `_inject_dynamic_doc_descriptions()`
- `documentation/product/behavior/chat_app_capabilities.md` — System overview

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals](#goals)
3. [Non-Goals](#non-goals)
4. [Current State](#current-state)
5. [Design Overview](#design-overview)
6. [Architecture](#architecture)
7. [Data Flow](#data-flow)
8. [Component 1: Message Classification Pipeline](#component-1-message-classification-pipeline)
9. [Component 2: Global Doc Selection Pipeline](#component-2-global-doc-selection-pipeline)
10. [Component 3: Context Assembly & Budget Trimming](#component-3-context-assembly--budget-trimming)
11. [Component 4: UI — Dropdown Option](#component-4-ui--dropdown-option)
12. [Component 5: UI — Context Selection Display](#component-5-ui--context-selection-display)
13. [Component 6: Fallback & Error Handling](#component-6-fallback--error-handling)
14. [Scoring Formula](#scoring-formula)
15. [Prompt Templates](#prompt-templates)
16. [Implementation Plan (Tasks)](#implementation-plan-tasks)
17. [Files to Create/Modify](#files-to-createmodify)
18. [Testing Plan](#testing-plan)
19. [Risks and Mitigations](#risks-and-mitigations)
20. [Alternatives Considered](#alternatives-considered)

---

## Problem Statement

Today the history setting is a blunt manual control: the user picks a fixed number of past messages (0–10, infinite, or ∅). This creates two problems:

1. **Users must guess the right history depth.** Too few messages and the LLM loses context; too many and the token budget is wasted on irrelevant messages while relevant ones get truncated. Most users leave it on `infinite` (the default) or `2` — neither is optimal for every query.

2. **Global docs are never auto-included.** The user must explicitly reference docs with `#gdoc_N`, `#folder:`, or `#tag:` syntax. If a user has 20 global docs and their question is clearly about a topic covered by one of them, the system doesn't help — the user must remember which doc to reference.

**What we need:** An "Auto" mode that intelligently selects the optimal context for each turn — choosing which past messages to include (fully or summarized), and which global docs to pull in — without user intervention. The system should be transparent about what it selected.

---

## Goals

1. **Intelligent message selection.** Classify each past message as "not useful" / "background info" / "highly relevant" relative to the current query. Include highly relevant messages fully, summarize background messages, exclude the rest.
2. **Automatic global doc selection.** Score all (non-deprecated) global docs against the current query using an LLM, auto-include relevant ones as RAG context.
3. **Fully dynamic token budget.** No fixed allocations — fill the context window greedily with the most relevant content regardless of type.
4. **Transparency.** Show a collapsible section above the response with a detailed breakdown of what was auto-selected (doc titles, relevance scores, message classifications, token budget usage).
5. **Graceful degradation.** If doc selection or message classification fails, fall back independently to safe defaults with a toast notification.
6. **Low latency.** Auto selection must complete within 3–5 seconds. Doc selection and message classification run fully in parallel.

---

## Non-Goals

- Changing how conversation-local docs (`#doc_N`) work — they are always fully included when referenced.
- Auto-selecting which conversation-local docs to include — only global docs are auto-selected.
- Replacing the existing manual history options — Auto is an opt-in addition.
- Persisting auto-selection results — they are ephemeral and re-evaluated every send/regenerate.
- Auto-generating TLDRs for messages that don't have them — use first 200 + last 100 words instead.

---

## Current State

### History Setting Flow

1. **UI**: `#settings-historySelector` dropdown in `interface/interface.html` (lines 2615–2629). Values: `-1` (∅), `0`–`10`, `infinite`.
2. **JS state**: `chatSettingsState.history` in `chat.js` (lines 623, 658, 777). Persisted to localStorage per tab.
3. **POST body**: `enable_previous_messages` packed in `common.js:getOptions()` (lines 4479–4480).
4. **Backend**: `Conversation.py:reply()` extracts `enablePreviousMessages` at line 7896. Converts to `message_lookback = int(value) * 2` at line 7924. Special handling for `"-1"` (stateless) and `"infinite"` (20 messages).

### Context Assembly

- `retrieve_prior_context()` (lines 3057–3138) builds 4 message tiers: very_short (10K tokens), short (20K), long (48K), very_long (64K). Currently all code paths use `very_long`.
- `retrieve_prior_context_llm_based()` (lines 3141–3370+) does LLM-based fact extraction per message window using `SUPERFAST_LLM[0]`.
- Running summary always included (unless ∅ mode). Generated after every turn via `persist_current_turn()`.
- Memory pad included when `use_memory_pad` checkbox is on.
- Token budget managed by `truncate_text()` (lines 13040–13139) with model-specific limits.

### Global Doc RAG Pipeline

- `get_global_documents_for_query()` (line 5922) resolves `#gdoc_N`, `#folder:`, `#tag:`, quoted display-name references.
- Each doc loaded via `DocIndex.load_local(doc_storage)` → `semantic_search_document(query)` for RAG chunks.
- FAISS similarity search: `raw_index.similarity_search(query, k=N)` returns top-k chunks by embedding distance.
- `semantic_search_document_small(query, token_limit)` is the lightweight variant using `raw_index_small`.
- Docs merged into prompt via `conversation_docs_answer` / `doc_answer` template slots.
- `_inject_dynamic_doc_descriptions()` (line 6840) enriches tool descriptions with available global docs.

### Message TLDRs

- Assistant messages: `answer_tldr` field on the message dict (line 3966). Populated during `persist_current_turn()`.
- User messages: No TLDR stored. Use first 200 + last 100 words of `messageText`.

### LLM Model Tiers

- `SUPERFAST_LLM[0]` = `"inception/mercury-2"` (100K tokens, cheapest)
- `CHEAP_LLM[0]` = `"anthropic/claude-haiku-4.5"` (160K tokens, mid-tier)
- `EXPENSIVE_LLM` = Claude Sonnet/Opus, GPT-5.x, etc. (200K tokens)
- Model override: `conversation.get_model_override("conversation_internal_model", default)`
- `CallLLm(api_keys, model_name=model, use_16k=True)` instantiation pattern.

### Collapsible UI Pattern

- Primary: HTML `<details class="section-details">` with `<summary>` (backend: `collapsible_wrapper()` in `common.py` lines 187–305).
- Frontend: `renderInnerContentAsMarkdown()` auto-wraps sections in `<details>` with state persistence via `data-section-hash` + localStorage.
- Close button: `.details-close-btn` class with global event delegation.

---

## Design Overview

Auto mode adds a new value `"auto"` to the history dropdown. When active, two parallel pipelines run before the main LLM call:

```
User sends message
        │
        ├──── [Pipeline 1: Message Classification] ────┐
        │     • Get all past messages                   │
        │     • Extract TLDR per message                │
        │     • Classify in 5-msg windows (parallel)    │
        │     • Returns: per-message classification     │
        │                                               │
        ├──── [Pipeline 2: Global Doc Selection] ───────┤
        │     • List all non-deprecated global docs     │
        │     • Pull top-1 FAISS chunk per doc          │
        │     • LLM selects relevant docs (yes/no)      │
        │     • Apply priority/date scoring             │
        │     • Returns: selected doc list + scores     │
        │                                               │
        ▼                                               ▼
   ┌─────────── Context Assembly ───────────┐
   │  1. Always include: summary + memory pad│
   │  2. Highly relevant messages (full)     │
   │  3. Background messages (summarized)    │
   │  4. Auto-selected doc RAG chunks        │
   │  5. Explicit #gdoc refs (additive)      │
   │  6. Local docs (always full)            │
   │  7. Trim to token budget by relevance   │
   └──────────────┬─────────────────────────┘
                  │
                  ▼
        Main LLM call (with assembled context)
        + Context selection metadata → UI collapsible
```

---

## Architecture

### New Module: `auto_context.py`

A standalone module in the project root (next to `Conversation.py`) containing all Auto context selection logic. This keeps the new feature cleanly separated from the already-large `Conversation.py`.

**Public API:**

```python
class AutoContextResult:
    """Holds the results of auto context selection."""
    messages_classified: list[dict]  # [{msg_id, classification, summary_if_background}]
    docs_selected: list[dict]       # [{doc_id, title, score, reason}]
    summary_included: bool
    memory_pad_included: bool
    token_usage: dict               # {messages: N, docs: N, summary: N, memory_pad: N, total: N}
    error_messages: list[str]       # Any fallback notifications
    
async def auto_select_context(
    query: str,
    messages: list[dict],
    global_docs: list[dict],
    api_keys: dict,
    model_name: str,
    token_budget: int,
    conversation: "Conversation",  # For DocIndex loading and FAISS queries
) -> AutoContextResult:
    """Main entry point for Auto context selection."""
```

**Internal functions:**

```python
async def _classify_messages(
    query: str,
    messages: list[dict],
    api_keys: dict,
    model_name: str,
) -> list[dict]:
    """Classify messages in parallel 5-msg windows."""

async def _select_global_docs(
    query: str,
    global_docs: list[dict],
    api_keys: dict,
    model_name: str,
    conversation: "Conversation",
) -> list[dict]:
    """LLM-based doc selection with FAISS scoring."""

def _assemble_context(
    result: AutoContextResult,
    messages: list[dict],
    summary_text: str,
    memory_pad: str,
    token_budget: int,
) -> dict:
    """Assemble final context within token budget."""

def _compute_doc_score(llm_relevance: float, priority: int, date_written: str) -> float:
    """Apply priority/date boost to LLM relevance score."""
```

---

## Data Flow

### End-to-End Sequence

1. **UI**: User selects "Auto" in `#settings-historySelector`. Value `"auto"` sent as `enable_previous_messages`.
2. **Backend** (`Conversation.py:reply()` line ~7896): Detects `enablePreviousMessages == "auto"`.
3. **Parallel launch**:
   - Pipeline 1: `_classify_messages()` — classifies all past messages via windowed LLM calls.
   - Pipeline 2: `_select_global_docs()` — scores all global docs via FAISS + LLM.
4. **Assembly**: `_assemble_context()` combines results into a single context block within token budget.
5. **Injection**: Auto-selected messages replace `previous_messages`. Auto-selected docs are RAG-queried and added to `doc_answer`. Summary and memory pad always included.
6. **Prompt**: Normal prompt assembly via `prompts.chat_slow_reply_prompt.format(...)`.
7. **Tool descriptions**: Auto-selected docs also injected into `_inject_dynamic_doc_descriptions()`.
8. **UI metadata**: Context selection metadata streamed as a collapsible section prepended to the response.

---

## Component 1: Message Classification Pipeline

### Input
- `query`: Current user message text.
- `messages`: All past messages from the conversation (list of dicts with `text`, `sender`, `answer_tldr`, `message_id`).

### TLDR Extraction

For each message:
- **Assistant messages**: Use `msg.get("answer_tldr", "")`. If empty/missing, use first 200 + last 100 words of `msg["text"]`.
- **User messages**: First 200 words + last 100 words of `msg["text"]` (user messages never have TLDRs).

### Windowed Classification

1. Group messages into windows of 5 (ordered chronologically, most recent first).
2. For each window, call LLM with fixed system prompt (for prompt caching) + variable user content.
3. All window calls run in parallel via `get_async_future()`.
4. LLM classifies each message as one of:
   - `"not_useful"` — Not relevant to the current query. Excluded from context.
   - `"background"` — Provides background context. Include as a compressed summary.
   - `"relevant"` — Directly relevant. Include full message text.

### LLM Model

- Default: `CHEAP_LLM[0]` (`"anthropic/claude-haiku-4.5"`, mid-tier).
- Override: `conversation.get_model_override("conversation_internal_model", CHEAP_LLM[0])`.

### Output Format (JSON)

```json
{
  "classifications": {
    "msg_1": "relevant",
    "msg_2": "background",
    "msg_3": "not_useful",
    "msg_4": "relevant",
    "msg_5": "background"
  }
}
```

### Background Message Summarization

For messages classified as `"background"`, generate a one-line summary. This can be done in the same LLM call — the classification prompt also asks for a brief summary for background messages:

```json
{
  "classifications": {
    "msg_1": {"class": "relevant"},
    "msg_2": {"class": "background", "summary": "User asked about deployment options for the ML model."},
    "msg_3": {"class": "not_useful"}
  }
}
```

### Fallback

If classification fails (timeout, parse error, LLM error):
- Fall back to `retrieve_prior_context()` with `message_lookback = 20` (same as `infinite` mode).
- Add error to `AutoContextResult.error_messages` for toast notification.

---

## Component 2: Global Doc Selection Pipeline

### Input
- `query`: Current user message text.
- `global_docs`: All non-deprecated global docs for the user (from `list_global_docs()`).
- `conversation`: Conversation object (for loading DocIndex and running FAISS queries).

### Step 1: Filter Deprecated Docs

```python
candidates = [d for d in global_docs if not d.get("deprecated")]
```

### Step 2: Pull Top-1 FAISS Chunk Per Doc

For each candidate doc:
1. Load DocIndex: `DocIndex.load_local(doc["doc_storage"])`.
2. Run lightweight similarity search: `doc_index.raw_index_small.similarity_search(query, k=1)`.
3. Extract the top chunk's `page_content` (full text, not truncated — these are already chunked).

Run all loads + searches in parallel via `get_async_future()`.

**Error handling**: If a DocIndex fails to load or FAISS search fails, skip that doc silently (same pattern as existing `get_global_documents_for_query()`).

### Step 3: LLM Selection

Send a single LLM call with:
- Fixed system prompt (for prompt caching) describing the task.
- Variable user content: the query + a numbered list of docs, each with:
  - Title
  - Short summary
  - Tags (if any)
  - Top-1 FAISS chunk
  - Priority label
  - Date written

LLM returns a JSON dict with yes/no per doc:

```json
{
  "selections": {
    "1": {"include": true, "reason": "Directly discusses the ML deployment topic"},
    "2": {"include": false, "reason": "About unrelated financial data"},
    "3": {"include": true, "reason": "Contains relevant code examples"}
  }
}
```

### Step 4: Apply Priority/Date Score

For each doc where `include == true`, compute final score (see [Scoring Formula](#scoring-formula)).

### Step 5: Merge with Explicit References

If the user also explicitly referenced docs (e.g., `#gdoc_5`), those are additive. Deduplicate by `doc_id`.

### LLM Model

Same as message classification: `CHEAP_LLM[0]` with `conversation_internal_model` override.

### Fallback

If doc selection fails:
- Skip auto-doc selection for this turn (no docs auto-included).
- Explicit `#gdoc` references still work normally.
- Add error to `AutoContextResult.error_messages`.

---

## Component 3: Context Assembly & Budget Trimming

### Token Budget

Determined by the conversation's model:
- Call `_get_token_limit(model_name)` from `code_common/call_llm.py`.
- Reserve ~2000 tokens for the query itself + system/format overhead.
- Available budget = `token_limit - 2000 - len(query_tokens)`.

### Assembly Priority (Greedy Fill)

Token budget is filled in this order. Each item either fits or is truncated/skipped:

1. **Running summary** — Always included. Typically 100–500 words (cheap). Truncate if very long.
2. **Memory pad** — Always included if exists. Typically compact. Truncate if very long.
3. **Permanent instructions** — Always included (coding rules, user info, page context). Fixed cost.
4. **Highly relevant messages** — Include full text, ordered by recency (most recent first). Each message consumes tokens from the budget.
5. **Auto-selected global doc RAG chunks** — For each selected doc, run `semantic_search_document(query, token_limit=remaining_per_doc)`. Order by score (highest first).
6. **Background messages** — Include their one-line summaries (very cheap per message).
7. **Explicit doc references** — Already included via normal pipeline. Budget shared with auto-selected docs.

### Trimming Strategy

- After filling all high-priority items, if budget is exceeded:
  - First trim: Reduce auto-selected doc RAG chunks (fewer chunks per doc, lowest-scored docs first).
  - Second trim: Reduce number of "highly relevant" messages (drop oldest first).
  - Third trim: Truncate background summaries.
  - Summary and memory pad are last to be trimmed (they're compact).

### Token Counting

Use `get_gpt4_word_count()` (already used throughout the codebase) for fast token estimation.

---

## Component 4: UI — Dropdown Option

### HTML Change

Add "Auto" option to `#settings-historySelector` in `interface/interface.html` (after line 2628):

```html
<option value="auto">Auto</option>
```

Place it as the last option (after `infinite`), so the dropdown reads:
∅, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, ∞, Auto

### JS Changes

No changes needed to `chat.js` or `common.js` — they pass the value through unchanged as a string. The `getOptions()` function in `common.js` (line 4479) reads `$('#settings-historySelector').val()` and sends it as-is.

### Backend Handling

In `Conversation.py:reply()` at line ~7919, add handling before the `int()` conversion:

```python
if enablePreviousMessages == "infinite":
    message_lookback = 10 * 2
elif enablePreviousMessages == "auto":
    # Auto mode — handled separately below
    message_lookback = None  # Sentinel value
else:
    message_lookback = int(enablePreviousMessages) * 2
```

---

## Component 5: UI — Context Selection Display

### Collapsible Section Above Response

When Auto mode is active, prepend a collapsible `<details>` section to the streamed response. This section contains a detailed breakdown of the auto-selection.

### HTML Structure

```html
<details class="section-details auto-context-details" data-section-hash="auto-ctx-{msg_id}">
  <summary class="section-summary">
    <strong>🔍 Auto Context</strong>
    <span class="auto-ctx-badge">{N} docs · {M}/{T} messages</span>
  </summary>
  <div class="section-content auto-context-breakdown">
    <div class="auto-ctx-section">
      <h4>Global Documents</h4>
      <table class="table table-sm">
        <thead><tr><th>Doc</th><th>Score</th><th>Reason</th></tr></thead>
        <tbody>
          <tr><td>#gdoc_1 — My Paper</td><td>0.92</td><td>Directly discusses ML deployment</td></tr>
          <tr><td>#gdoc_3 — Code Examples</td><td>0.78</td><td>Contains relevant code examples</td></tr>
        </tbody>
      </table>
    </div>
    <div class="auto-ctx-section">
      <h4>Messages</h4>
      <table class="table table-sm">
        <thead><tr><th>Message</th><th>Classification</th></tr></thead>
        <tbody>
          <tr class="auto-ctx-relevant"><td>Turn 12 (user): "How should we deploy..."</td><td>Relevant ✓</td></tr>
          <tr class="auto-ctx-background"><td>Turn 11 (assistant): Discussed options...</td><td>Background</td></tr>
          <tr class="auto-ctx-excluded"><td>Turn 10 (user): "What's for lunch?"</td><td>Excluded</td></tr>
        </tbody>
      </table>
    </div>
    <div class="auto-ctx-section">
      <h4>Token Budget</h4>
      <ul>
        <li>Messages: 4,200 tokens (3 relevant, 5 background)</li>
        <li>Documents: 6,800 tokens (2 docs)</li>
        <li>Summary: 320 tokens</li>
        <li>Memory pad: 180 tokens</li>
        <li>Total: 11,500 / 64,000 tokens</li>
      </ul>
    </div>
  </div>
</details>

---

```

### Rendering

The collapsible section is generated backend-side as an HTML string and yielded as the first chunk of the streaming response (before the actual LLM output begins). The existing `renderInnerContentAsMarkdown()` will detect and style the `<details>` element automatically.

### CSS

Add minimal CSS for the auto-context-specific classes:

```css
.auto-context-details { margin-bottom: 12px; }
.auto-ctx-badge { font-size: 0.8em; color: #6c757d; margin-left: 8px; }
.auto-ctx-relevant { color: #155724; }
.auto-ctx-background { color: #856404; }
.auto-ctx-excluded { color: #6c757d; text-decoration: line-through; }
.auto-context-breakdown table { font-size: 0.85em; }
.auto-context-breakdown h4 { font-size: 0.95em; margin: 8px 0 4px; }
```

---

## Component 6: Fallback & Error Handling

### Independent Fallbacks

| Component | Failure | Fallback | Notification |
|---|---|---|---|
| Message classification | LLM timeout/error/parse failure | Use `retrieve_prior_context()` with `message_lookback=20` (same as `infinite`) | Toast: "Auto context: message classification unavailable, using full history" |
| Doc selection | LLM timeout/error/parse failure | Skip auto-docs. Explicit `#gdoc` refs still work. | Toast: "Auto context: doc selection unavailable, no docs auto-included" |
| FAISS search for a single doc | DocIndex load failure | Skip that doc, continue with others | Silent (logged server-side) |
| Both pipelines fail | Both LLM calls fail | Equivalent to `infinite` mode + no auto-docs | Toast: "Auto context unavailable, using default history" |

### Timeout

Each LLM call has a 10-second timeout. The parallel window calls share this budget — if any single window times out, its messages are classified as `"background"` by default (safe fallback).

### JSON Parse Failure

If the LLM returns malformed JSON:
1. Try `json.loads()` on the raw output.
2. If that fails, try extracting JSON from markdown code blocks (` ```json ... ``` `).
3. If that fails, try regex extraction of the JSON object `\{.*\}` (with `re.DOTALL`).
4. If all parsing fails, trigger the component's fallback.

---

## Scoring Formula

### Doc Relevance Score

```python
def _compute_doc_score(llm_relevance: float, priority: int, date_written: str) -> float:
    """
    Compute final doc relevance score.
    
    Args:
        llm_relevance: 1.0 if LLM said "include", 0.0 if "exclude"
        priority: 1-5 (default 3)
        date_written: ISO date string or None
    
    Returns:
        Final score (0.0 - ~1.2)
    """
    # Priority boost: ±10% per level from neutral (3)
    # Priority 1 → 0.8x, Priority 3 → 1.0x, Priority 5 → 1.2x
    priority_factor = 1.0 + 0.1 * (priority - 3)
    
    # Date decay: -5% per year old, minimum 0.8x
    if date_written:
        years_old = (datetime.now() - datetime.fromisoformat(date_written)).days / 365.25
        date_factor = max(0.8, 1.0 - 0.05 * years_old)
    else:
        date_factor = 1.0  # No date → no decay
    
    return llm_relevance * priority_factor * date_factor
```

### Examples

| Doc | LLM | Priority | Age | Final Score |
|---|---|---|---|---|
| Paper A | Yes (1.0) | 5 (high) | 1 year | 1.0 × 1.2 × 0.95 = 1.14 |
| Paper B | Yes (1.0) | 3 (medium) | 0 years | 1.0 × 1.0 × 1.0 = 1.00 |
| Paper C | Yes (1.0) | 1 (very low) | 4 years | 1.0 × 0.8 × 0.80 = 0.64 |
| Paper D | No (0.0) | 5 (high) | 0 years | 0.0 × 1.2 × 1.0 = 0.00 |

Score is used for budget-trimming order (lowest-scored docs trimmed first), not for include/exclude (that's the LLM's binary decision).

---

## Prompt Templates

### Message Classification System Prompt (Fixed — Cacheable)

```
You are a message relevance classifier. You will receive a user's current query and a window of past conversation messages. For each message, classify it as one of:

- "relevant": Directly relevant to answering the current query. Contains information, context, decisions, or instructions that the AI needs to see in full.
- "background": Provides useful background context but is not directly relevant. Include a brief 1-sentence summary.
- "not_useful": Not relevant to the current query. Can be safely excluded.

Rules:
- Messages containing instructions, preferences, or rules the user set should be "relevant" (they may apply to the current query).
- Messages about completely different topics are "not_useful".
- When in doubt between "background" and "not_useful", choose "background".
- When in doubt between "relevant" and "background", choose "relevant".

Respond with ONLY a JSON object. No markdown, no explanation.

Output format:
{
  "classifications": {
    "<msg_id>": {"class": "relevant"},
    "<msg_id>": {"class": "background", "summary": "Brief 1-sentence summary"},
    "<msg_id>": {"class": "not_useful"}
  }
}
```

### Message Classification User Prompt (Variable)

```
Current user query: {query}

Past messages (classify each):

[Message {msg_id_1}] (user)
{tldr_or_excerpt_1}

[Message {msg_id_2}] (assistant)
{tldr_or_excerpt_2}

...

Classify each message.
```

### Doc Selection System Prompt (Fixed — Cacheable)

```
You are a document relevance selector. You will receive a user's current query and a list of available documents. For each document, decide whether it should be included as context for answering the query.

For each document, respond with:
- "include": true/false
- "reason": Brief 1-sentence explanation

Rules:
- Include documents that contain information relevant to answering the query.
- Include documents that provide important background knowledge for the topic.
- Exclude documents about completely unrelated topics.
- When in doubt, include (better to have extra context than miss something).
- Consider the document's title, summary, tags, and the sample content chunk.

Respond with ONLY a JSON object. No markdown, no explanation.

Output format:
{
  "selections": {
    "<doc_number>": {"include": true, "reason": "..."},
    "<doc_number>": {"include": false, "reason": "..."}
  }
}
```

### Doc Selection User Prompt (Variable)

```
Current user query: {query}

Available documents:

[Doc 1] Title: {title}
Summary: {short_summary}
Tags: {tags}
Priority: {priority_label}
Date written: {date_written}
Sample content: {top_faiss_chunk}

[Doc 2] ...

Select which documents to include.
```

---

## Implementation Plan (Tasks)

### Milestone 1: Core Backend — Auto Context Module

**Task 1.1: Create `auto_context.py` module skeleton**
- Create new file `auto_context.py` in project root.
- Define `AutoContextResult` dataclass with fields: `messages_classified`, `docs_selected`, `summary_included`, `memory_pad_included`, `token_usage`, `error_messages`.
- Define `auto_select_context()` entry point (skeleton that returns empty `AutoContextResult`).
- Define `_classify_messages()`, `_select_global_docs()`, `_assemble_context()`, `_compute_doc_score()` as skeleton functions.
- Define `_extract_message_tldr(msg)` helper: returns `answer_tldr` for assistant msgs, first 200 + last 100 words for user msgs.
- Define `_parse_json_response(raw_text)` helper: try `json.loads()` → extract from code blocks → regex `\{.*\}` → raise.
- Import model constants (`CHEAP_LLM` from `common`), `CallLLm` from `code_common.call_llm`, `get_async_future` from `common`, `get_gpt4_word_count` from `common`.
- Files: `auto_context.py` (new)
- **Delegation**: `category="deep"`, `load_skills=[]`
- **QA**: Run `conda activate science-reader && python -c "from auto_context import AutoContextResult, auto_select_context; print('imports OK')"`. Verify exit code 0.

**Task 1.2: Implement message classification pipeline**
- Implement `_extract_message_tldr(msg)`: check `msg.get("answer_tldr", "")`, if empty use first 200 words + last 100 words of `msg["text"]`.
- Implement `_group_into_windows(messages, window_size=5)`: group messages into windows of 5 (most recent first). Handle remainder window.
- Implement `_classify_message_window(query, window, api_keys, model_name)`: single LLM call for one window. Uses fixed system prompt (from Prompt Templates section) + variable user content. Returns parsed JSON dict.
- Implement `_classify_messages(query, messages, api_keys, model_name)`: groups messages into windows, launches parallel `get_async_future()` calls for each window, collects results with 10s timeout per window, merges into single dict.
- Use model: `CHEAP_LLM[0]` with `conversation.get_model_override("conversation_internal_model", CHEAP_LLM[0])`.
- Implement JSON parsing via `_parse_json_response()` with 3-stage fallback.
- Fallback on failure: return all messages as `{"class": "background", "summary": first_200_words}`.
- Store system + user prompt templates as module-level constants `MSG_CLASSIFY_SYSTEM_PROMPT` and `MSG_CLASSIFY_USER_TEMPLATE`.
- Files: `auto_context.py`
- **Delegation**: `category="deep"`, `load_skills=[]`
- **QA**: Write a small test at the bottom of `auto_context.py` guarded by `if __name__ == "__main__":` that calls `_extract_message_tldr()` with a sample assistant msg dict (with `answer_tldr`) and a user msg dict (no tldr, 300-word text), prints results. Also test `_group_into_windows()` with 12 messages — verify 3 windows (5, 5, 2). Run `conda activate science-reader && python auto_context.py` and verify output.

**Task 1.3: Implement global doc selection pipeline**
- Implement `_load_doc_top_chunk(doc_storage, query, api_keys)`: calls `DocIndex.load_local(doc_storage)`, then `doc_index.raw_index_small.similarity_search(query, k=1)`, returns chunk `page_content` string. Catch all exceptions and return `""` on failure.
- Implement `_select_global_docs(query, global_docs, api_keys, model_name, conversation)`:
  1. Filter: `candidates = [d for d in global_docs if not d.get("deprecated")]`.
  2. Parallel FAISS: launch `get_async_future(_load_doc_top_chunk, doc["doc_storage"], query, api_keys)` for each candidate.
  3. Build LLM prompt: numbered list of docs with title, short_summary, tags, priority_label, date_written, top_chunk.
  4. Single LLM call with fixed system prompt + variable user content.
  5. Parse JSON, apply `_compute_doc_score()` to each `include=true` doc.
  6. Return list of selected docs sorted by score descending.
- Implement `_compute_doc_score(llm_relevance, priority, date_written)`: formula from Scoring Formula section.
- Fallback on failure: return empty list.
- Store prompts as `DOC_SELECT_SYSTEM_PROMPT` and `DOC_SELECT_USER_TEMPLATE`.
- Files: `auto_context.py`
- **Delegation**: `category="deep"`, `load_skills=[]`
- **QA**: Run `conda activate science-reader && python -c "from auto_context import _compute_doc_score; assert abs(_compute_doc_score(1.0, 5, '2025-04-09') - 1.14) < 0.05; assert _compute_doc_score(0.0, 5, None) == 0.0; print('scoring OK')"`. Verify exit code 0.

**Task 1.4: Implement context assembly and budget trimming**
- Implement `_assemble_context(result, messages, summary_text, memory_pad, token_budget)`:
  1. Always include summary_text — count tokens via `get_gpt4_word_count()`.
  2. Always include memory_pad (if non-empty) — count tokens.
  3. Add "relevant" messages full text (most recent first) until budget fills.
  4. Add auto-selected doc placeholders (token cost estimated from scores/chunk sizes).
  5. Add "background" message summaries (cheap).
  6. Trimming: if over budget, trim lowest-score docs first → oldest relevant messages → background summaries.
  7. Populate `result.token_usage` dict.
- Return assembled `previous_messages` string and `auto_doc_ids` list.
- Files: `auto_context.py`
- **Delegation**: `category="deep"`, `load_skills=[]`
- **QA**: Write a `if __name__ == "__main__":` test that creates mock classified messages (3 relevant, 5 background, 4 not_useful) and a 10K token budget, calls `_assemble_context()`, verifies: relevant messages are included first, background summaries added, total tokens <= budget. Print token_usage dict.

### Milestone 2: Backend Integration — Wire into `reply()`

**Task 2.1: Add Auto mode detection in `reply()`**
- In `Conversation.py:reply()` at line ~7919, add `elif enablePreviousMessages == "auto":` branch before the `else: message_lookback = int(...)` line.
- Set `message_lookback = None` as sentinel value (so downstream code can check `if message_lookback is None:` for Auto mode).
- Do NOT clear `summary_text` or `summary_text_init` (Auto always includes summary).
- Do NOT change `use_memory_pad` logic (Auto always includes memory pad if it exists — force `use_memory_pad = True` when Auto).
- Files: `Conversation.py`
- **Depends on**: None (can start independently)
- **Delegation**: `category="quick"`, `load_skills=[]`
- **QA**: After edit, run `conda activate science-reader && python -c "from Conversation import Conversation; print('import OK')"`. Verify the import succeeds (no syntax errors introduced). Grep for `enablePreviousMessages == \"auto\"` in Conversation.py to confirm the branch exists.

**Task 2.2: Call auto_select_context() from reply()**
- When `message_lookback is None` (Auto mode):
  - Gather inputs: `query["messageText"]`, `self.get_message_list()`, `list_global_docs(users_dir=..., user_email=...)`, `self.get_api_keys()`, model name from `self.get_model_override("conversation_internal_model", CHEAP_LLM[0])`, token budget from `_get_token_limit(model)`.
  - Call `auto_select_context()` — internally launches both pipelines in parallel via `get_async_future()`.
  - From the `AutoContextResult`:
    - Build `previous_messages` string from classified messages (relevant = full XML `<user>...</user>` / `<model>...</model>`, background = one-line summary, not_useful = omitted).
    - Set `previous_messages_short = previous_messages_long = previous_messages_very_long = previous_messages` (all tiers identical in Auto mode).
    - Store `auto_doc_ids` for use in Task 2.3.
    - Store `auto_context_result` for use in Task 2.5.
- Files: `Conversation.py`, `auto_context.py`
- **Depends on**: Task 1.1, 1.2, 1.3, 1.4, 2.1
- **Delegation**: `category="deep"`, `load_skills=[]`
- **QA**: Add temporary `logger.info(f"Auto context: {len(result.messages_classified)} msgs classified, {len(result.docs_selected)} docs selected")` after the call. Start server (`conda activate science-reader && python server.py`), send a message with Auto mode, check server logs for the info line.

**Task 2.3: Integrate auto-selected docs into RAG pipeline**
- After `auto_select_context()` returns, for each doc in `auto_context_result.docs_selected`:
  1. Load DocIndex: `DocIndex.load_local(doc["doc_storage"])`.
  2. Attach API keys: `doc_index.set_api_keys(self.get_api_keys())`.
  3. Run RAG: `doc_index.semantic_search_document(query["messageText"], token_limit=remaining_per_doc)`.
  4. Format result same way `get_global_documents_for_query()` formats doc answers.
- Merge auto-doc RAG results into `doc_answer` (or `conversation_docs_answer`).
- Deduplicate with any explicit `#gdoc` references by `doc_id` — explicit refs take priority (skip auto-selected if already explicitly referenced).
- Files: `Conversation.py`
- **Depends on**: Task 2.2
- **Delegation**: `category="deep"`, `load_skills=[]`
- **QA**: Send a message with Auto mode that is clearly about a topic covered by a global doc. Check the response references/uses information from that doc. Verify in server logs that the doc was loaded and RAG-queried.

**Task 2.4: Integrate auto-selected docs into tool descriptions**
- In `_inject_dynamic_doc_descriptions()` (line ~6840 in Conversation.py):
  - Accept an optional `auto_selected_doc_ids: set` parameter.
  - When formatting global doc entries, if a doc's `doc_id` is in `auto_selected_doc_ids`, append `[AUTO-INCLUDED]` to its description line.
  - This tells the LLM which docs are already in context (so it can query them further via tools if needed).
- Pass `auto_selected_doc_ids` from the reply() Auto mode branch.
- Files: `Conversation.py`
- **Depends on**: Task 2.2
- **Delegation**: `category="quick"`, `load_skills=[]`
- **QA**: Search `_inject_dynamic_doc_descriptions` in Conversation.py, verify the new parameter is accepted and `[AUTO-INCLUDED]` appears in the formatted output for auto-selected docs.

**Task 2.5: Stream context metadata as collapsible section**
- Create helper function `_build_auto_context_html(result: AutoContextResult) -> str` in `auto_context.py`.
- Generates the `<details class="auto-context-details">` HTML from AutoContextResult (following the structure in Component 5 section).
- In `reply()`, when Auto mode is active, yield this HTML as the first chunk of the streaming response (before `<answer>` tag).
- Include `data-auto-context-fallback="true"` attribute if `result.error_messages` is non-empty (for frontend toast detection).
- Files: `Conversation.py`, `auto_context.py`
- **Depends on**: Task 2.2
- **Delegation**: `category="unspecified-low"`, `load_skills=[]`
- **QA**: Call `_build_auto_context_html()` with a mock AutoContextResult containing 2 docs and 5 classified messages. Verify the returned HTML contains `<details class="auto-context-details"`, doc titles, message classifications, and token usage. Check HTML is valid (no unclosed tags).

### Milestone 3: Frontend — UI Integration

**Task 3.1: Add "Auto" option to history dropdown**
- Add `<option value="auto">Auto</option>` to `#settings-historySelector` in `interface/interface.html` (after the `infinite` option, line ~2628).
- Files: `interface/interface.html`
- **Depends on**: None (can start independently)
- **Delegation**: `category="quick"`, `load_skills=[]`
- **QA**: Open `interface/interface.html` in browser, open chat settings modal, verify "Auto" appears as the last option in the History dropdown. Select it, close/reopen modal — verify it persists (chatSettingsState handles any string value).

**Task 3.2: Add CSS for auto-context display**
- Add CSS rules in `interface/interface.html` (within existing `<style>` block) or `interface/style.css`:
  - `.auto-context-details { margin-bottom: 12px; }` 
  - `.auto-ctx-badge { font-size: 0.8em; color: #6c757d; margin-left: 8px; }`
  - `.auto-ctx-relevant { color: #155724; }` (green — matches Bootstrap success)
  - `.auto-ctx-background { color: #856404; }` (amber — matches Bootstrap warning)
  - `.auto-ctx-excluded { color: #6c757d; text-decoration: line-through; }` (gray)
  - `.auto-context-breakdown table { font-size: 0.85em; }`
  - `.auto-context-breakdown h4 { font-size: 0.95em; margin: 8px 0 4px; }`
- Files: `interface/interface.html` or `interface/style.css`
- **Depends on**: None (can start independently)
- **Delegation**: `category="visual-engineering"`, `load_skills=["frontend-ui-ux"]`
- **QA**: Create a static HTML file with the auto-context `<details>` structure from Component 5, link the CSS, open in browser. Verify color coding, font sizes, and table layout match the design. Verify collapsed state hides content.

**Task 3.3: Toast notification for fallback**
- In `interface/common.js` or `interface/common-chat.js`, in the response rendering path:
  - After rendering the auto-context `<details>` section, check for `data-auto-context-fallback="true"` attribute.
  - If present, call `showToast("Auto context: some features unavailable, using fallback", "warning")`.
- Files: `interface/common.js` or `interface/common-chat.js`
- **Depends on**: Task 2.5 (needs the data attribute), Task 3.2 (needs CSS)
- **Delegation**: `category="quick"`, `load_skills=[]`
- **QA**: Simulate by manually injecting `<details class="auto-context-details" data-auto-context-fallback="true">` into a response. Verify toast appears with warning styling.

**Task 3.4: Bump service worker cache version**
- Increment `CACHE_VERSION` in `interface/service-worker.js`.
- Files: `interface/service-worker.js`
- **Depends on**: Tasks 3.1, 3.2, 3.3 (do after all frontend changes)
- **Delegation**: `category="quick"`, `load_skills=[]`
- **QA**: Open `interface/service-worker.js`, verify the version number increased by 1 from its current value.

### Milestone 4: Testing & Documentation

**Task 4.1: End-to-end testing**
- Start server: `conda activate science-reader && python server.py`.
- Test scenarios:
  1. **First turn with Auto**: New conversation, select Auto, send message. Verify collapsible section appears with doc selection results and "0 messages classified". Verify response is coherent.
  2. **Multi-turn with Auto**: Conversation with 10+ turns, switch to Auto, send a message referencing an earlier topic. Verify relevant earlier messages are included (check collapsible breakdown). Verify irrelevant messages are excluded.
  3. **No global docs**: User with 0 global docs. Verify doc selection gracefully skips (no errors, collapsible shows "0 docs").
  4. **Many global docs**: User with 5+ global docs. Verify relevant ones are selected, irrelevant ones excluded. Check scores in collapsible.
  5. **Explicit + auto docs**: Send `#gdoc_1 tell me about X` with Auto mode. Verify gdoc_1 is force-included AND auto-selected docs are additive (deduplicated).
  6. **Fallback**: Temporarily break LLM call (e.g., bad API key). Verify toast notification appears and response still works (falls back to infinite history, no auto-docs).
  7. **Regenerate**: Send message with Auto, regenerate. Verify re-evaluation (collapsible may show different selections if context changed).
  8. **Budget trimming**: Use a small-context model, send message in a long conversation. Verify total tokens in collapsible don't exceed model limit.
- Files: None (manual testing)
- **Depends on**: All previous tasks
- **Delegation**: Manual (not delegated)
- **QA**: All 8 scenarios pass without errors.

**Task 4.2: Update documentation**
- Create `documentation/features/auto_context/README.md` with:
  - Feature overview, user guide (how to enable Auto mode).
  - Architecture description (two pipelines, assembly, budget).
  - Prompt templates used.
  - Scoring formula with examples.
  - Fallback behavior table.
  - API details (no new endpoints — all internal).
  - Files modified.
  - Collapsible section UI description.
- Update `documentation/features/conversation_flow/conversation_flow.md`: add section on Auto mode in the history setting flow.
- Update `AGENTS.md`: add entry under features for auto_context.
- Files: `documentation/features/auto_context/README.md` (new), `documentation/features/conversation_flow/conversation_flow.md`, `AGENTS.md`
- **Depends on**: All previous tasks (need final implementation to document)
- **Delegation**: Manual (not delegated — requires full context)
- **QA**: Verify new README.md exists and covers all sections listed. Verify conversation_flow.md mentions Auto mode. Verify AGENTS.md has auto_context entry.

---

## Task Dependency Graph

| Task | Depends On | Blocks |
|---|---|---|
| 1.1 | — | 1.2, 1.3, 1.4, 2.2 |
| 1.2 | 1.1 | 2.2 |
| 1.3 | 1.1 | 2.2 |
| 1.4 | 1.1 | 2.2 |
| 2.1 | — | 2.2 |
| 2.2 | 1.1, 1.2, 1.3, 1.4, 2.1 | 2.3, 2.4, 2.5 |
| 2.3 | 2.2 | 4.1 |
| 2.4 | 2.2 | 4.1 |
| 2.5 | 2.2 | 3.3, 4.1 |
| 3.1 | — | 4.1 |
| 3.2 | — | 3.3, 4.1 |
| 3.3 | 2.5, 3.2 | 3.4, 4.1 |
| 3.4 | 3.1, 3.2, 3.3 | 4.1 |
| 4.1 | All above | 4.2 |
| 4.2 | 4.1 | — |

---

## Parallel Execution Graph

### Wave 1 (Independent — all can start simultaneously)
| Task | Category | Skills | Est. Effort |
|---|---|---|---|
| 1.1: Create auto_context.py skeleton | `deep` | `[]` | Medium |
| 2.1: Add Auto mode detection in reply() | `quick` | `[]` | Small |
| 3.1: Add "Auto" dropdown option | `quick` | `[]` | Trivial |
| 3.2: Add CSS for auto-context display | `visual-engineering` | `["frontend-ui-ux"]` | Small |

### Wave 2 (Depends on Wave 1: 1.1 complete)
| Task | Category | Skills | Est. Effort |
|---|---|---|---|
| 1.2: Message classification pipeline | `deep` | `[]` | Large |
| 1.3: Global doc selection pipeline | `deep` | `[]` | Large |
| 1.4: Context assembly & budget trimming | `deep` | `[]` | Medium |

Note: 1.2 and 1.3 are independent of each other and can run in parallel. 1.4 depends conceptually on 1.2/1.3 output format but can be implemented against the dataclass contract from 1.1.

### Wave 3 (Depends on Wave 2 + 2.1: all M1 tasks + 2.1 complete)
| Task | Category | Skills | Est. Effort |
|---|---|---|---|
| 2.2: Wire auto_select_context() into reply() | `deep` | `[]` | Large |

### Wave 4 (Depends on Wave 3: 2.2 complete)
| Task | Category | Skills | Est. Effort |
|---|---|---|---|
| 2.3: Integrate auto-docs into RAG pipeline | `deep` | `[]` | Medium |
| 2.4: Integrate auto-docs into tool descriptions | `quick` | `[]` | Small |
| 2.5: Stream context metadata HTML | `unspecified-low` | `[]` | Medium |

Note: 2.3, 2.4, 2.5 are independent of each other and can run in parallel.

### Wave 5 (Depends on Wave 4: 2.5 + 3.2 complete)
| Task | Category | Skills | Est. Effort |
|---|---|---|---|
| 3.3: Toast notification for fallback | `quick` | `[]` | Small |

### Wave 6 (Depends on Wave 5: all frontend tasks complete)
| Task | Category | Skills | Est. Effort |
|---|---|---|---|
| 3.4: Bump service worker cache | `quick` | `[]` | Trivial |

### Wave 7 (Depends on all above)
| Task | Category | Skills | Est. Effort |
|---|---|---|---|
| 4.1: End-to-end testing | Manual | — | Large |
| 4.2: Documentation | Manual | — | Medium |

---

## Files to Create/Modify

### New Files
| File | Purpose |
|---|---|
| `auto_context.py` | Core Auto context selection module (message classification, doc selection, assembly, scoring) |
| `documentation/features/auto_context/README.md` | Feature documentation |

### Modified Files
| File | Change |
|---|---|
| `Conversation.py` | Add Auto mode branch in `reply()`, wire `auto_select_context()`, stream metadata HTML, integrate auto-docs into RAG + tool descriptions |
| `interface/interface.html` | Add `<option value="auto">Auto</option>` to `#settings-historySelector`. Add CSS for auto-context display. |
| `interface/service-worker.js` | Bump `CACHE_VERSION` |
| `interface/common.js` or `interface/common-chat.js` | Toast notification for Auto fallback (if needed) |
| `interface/style.css` | CSS for auto-context collapsible section (alternative to inline in interface.html) |

---

## Testing Plan

### Unit-Level Verification
- `_compute_doc_score()` with various priority/date combinations.
- TLDR extraction: assistant with `answer_tldr`, assistant without, user messages.
- Window grouping: verify 5-msg windows, handle remainder.
- JSON parsing: valid JSON, JSON in code blocks, malformed JSON.

### Integration Verification
- Auto mode end-to-end: send message with Auto, verify classification + doc selection + assembly.
- Token budget: verify context fits within model limit.
- Fallback: simulate LLM failure, verify independent fallbacks.
- Explicit + auto docs: verify deduplication.
- Collapsible section: verify HTML renders correctly in chat.

### Edge Cases
- First message in conversation (no history, no summary).
- Conversation with 100+ messages (verify performance within 3–5s).
- User with 50+ global docs (verify doc selection latency).
- All docs deprecated (no candidates).
- All messages classified as "not_useful" (verify summary still provides context).
- Token budget very small (8K model) — verify aggressive trimming.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LLM classification quality is poor | Wrong messages selected, bad responses | Use mid-tier model (CHEAP_LLM), bias toward "relevant" when in doubt, user can switch to manual mode |
| Latency exceeds 5s with many docs | Slow UX | Parallel FAISS loads, 10s timeout, skip slow docs |
| Token cost per turn increases | Higher API costs | Use CHEAP_LLM (not EXPENSIVE_LLM) for selection calls, windowed calls are cheap |
| DocIndex loading is slow (disk I/O) | FAISS chunk retrieval bottleneck | Load in parallel, use `raw_index_small` (lighter), skip on timeout |
| JSON parsing fails frequently | Fallbacks triggered too often | Multiple parsing strategies, clear prompts with format examples |
| Auto-included docs confuse the LLM | Lower response quality | Clear separation in prompt ("Auto-included context"), user can disable |
| Context metadata section clutters UI | Visual noise | Collapsed by default, minimal styling, matches existing patterns |

---

## Alternatives Considered

### 1. Embedding-based message selection (no LLM)
Embed the current query and each message TLDR, select by cosine similarity. Rejected because: no embeddings exist for messages today, and LLM classification captures semantic nuance (e.g., instructions that apply broadly) that pure similarity misses.

### 2. FAISS-only doc selection (no LLM)
Score docs by FAISS similarity of query vs doc chunks. Rejected because: FAISS similarity is per-chunk, not per-doc. A doc might have one relevant chunk but be overall irrelevant. LLM sees the full picture (title, summary, chunk) and makes better whole-doc decisions.

### 3. Auto as default for all conversations
Make Auto the default instead of `infinite`. Rejected because: it adds latency and cost per turn. Users who don't need it shouldn't pay for it. Opt-in is safer.

### 4. Fixed token budget allocation (30/50/20 split)
Reserve percentages for docs/history/summary. Rejected because: fully dynamic allocation adapts better to varied queries (some need lots of history, others need lots of docs).

### 5. Persist auto-selection results
Save what was selected so the collapsible section survives page reload. Rejected because: selection should be fresh per-query. Persisting adds schema complexity for marginal benefit. The ephemeral collapsible section disappears on reload — acceptable since the response itself captures the benefit.
