# Auto Context History Mode

**Status:** Implemented and live  
**Created:** 2026-05-28  
**Related plan:** `documentation/planning/plans/auto_context_history_mode.plan.md`

---

## Overview

Auto Context is an intelligent conversation history mode that replaces the manual "how many past messages to include" selector with three smart modes (Light, Medium, Deep). Instead of blindly including the last N messages, the system classifies each past message by relevance to the current query and assembles a context block containing only what matters — either verbatim or as a paraphrase/summary.

The user selects the mode from the history dropdown in the chat settings panel. **Auto Medium is the default.**

---

## Design Philosophy

The core insight is that most conversations have a mix of highly relevant turns, background turns, and completely irrelevant turns relative to any given query. A fixed lookback window wastes tokens on irrelevant messages while potentially missing relevant ones from further back. Auto Context solves this by:

1. **Classifying** past messages by relevance (verbatim / summarised / none)
2. **Searching** for relevant messages using a tool-calling agent
3. **Extracting** key facts from relevant windows using LLM
4. **Assembling** a deduplicated context block from all three signals
5. **Falling back** gracefully if any component fails — never breaking the main reply

All three signals run in parallel with the main reply stream, so there is zero added latency to the user-visible response.

---

## Modes

| Mode | Lookback | Dedup Rule | Memory Pad | LLM Calls |
|------|----------|------------|------------|-----------|
| **Auto Light** | 1 turn anchor | paraphrase_wins | No | Single-call extraction, no verbatim |
| **Auto Medium** | 2 turn anchor | any_verbatim_wins | No | Windowed extraction + classifier + agent |
| **Auto Deep** | 2 turn anchor | any_verbatim_wins | **Yes** | Windowed extraction + classifier + agent (wider) |

**Anchor turns** are the most recent N turns included verbatim regardless of classification — they provide grounding for the LLM.

**Memory pad** (Deep only): the conversation's persistent memory pad is always injected into the prompt for Deep mode, giving the LLM access to long-term facts the user has stored.

---

## Architecture

### Three parallel signals

```
query arrives
    │
    ├─► retrieve_prior_context_llm_based()   ← windowed LLM extraction
    │       Extracts key facts from message windows as bullet points
    │       (moved from Conversation.py into code_common/auto_context.py)
    │
    ├─► classify_messages_for_context()      ← per-message classification
    │       LLM classifies each message: verbatim / summarised / none
    │       Uses compact metadata repr (tldr + keywords) not full text
    │
    └─► agentic_context_finder()             ← tool-calling agent
            Uses search_messages / list_messages / read_message tools
            to find relevant messages, outputs {message_id, mode} decisions
```

All three fire as `get_async_future` calls immediately after the `enablePreviousMessages` check. They resolve before the main LLM call starts (the main call waits on `prior_context_llm_based_future` with a 120s timeout; classifier and agent each have 90s timeouts via `sleep_and_get_future_result`).

### `retrieve_prior_context_llm_based` — moved to `auto_context.py`

The original implementation in `Conversation.py` was ~290 lines. It is now a 12-line delegation:

```python
def retrieve_prior_context_llm_based(self, query, past_message_ids=[], required_message_lookback=30):
    from code_common.auto_context import retrieve_prior_context_llm_based as _rpc_llm, AutoContextMode
    return _rpc_llm(self, query, past_message_ids=past_message_ids,
                    required_message_lookback=required_message_lookback,
                    mode=AutoContextMode.DEEP)
```

The function in `auto_context.py` is mode-aware: LIGHT uses a single call (`llm_based_single_call=True`), DEEP/MEDIUM use windowed parallel calls. Window sizing: last 6 messages → window=3, last 16 → window=5, older → window=6.

### Classifier — compact message representation

The classifier never sends full message text to the LLM. Instead `_compact_message_repr()` builds a metadata-only dict per message:

```python
{
  "index": N,
  "message_id": "...",
  "sender": "user"|"model",
  "tldr": user_ask_tldr or text[:200],      # user messages
  "keywords": {entities, topics, ...},       # if present
  "prior_context": "...",                    # if present (user only)
}
```

For model messages: `answer_tldr or text[:200]` + `answer_keywords`. This makes classification cheap and fast — the LLM sees summaries, not full text.

The classifier output uses `"summarised"` as the label, which is normalised to `"paraphrased"` during assembly (`mode_str = "paraphrased" if cls == "summarised" else cls`).

### Assembly — dedup and ranking

`_RANK = {"verbatim": 2, "paraphrased": 1, "summarised": 1, "none": 0}`

- `any_verbatim_wins` (Deep/Medium): `max(modes, key=_RANK.get)` — highest rank across all signals wins
- `paraphrase_wins` (Light): any non-none → `"paraphrased"` (verbatim never used)

For each selected message, rendering:
- `verbatim` → `_extract_user_answer(msg["text"])` (strips `<answer>` tags)
- `paraphrased` → `user_ask_tldr or text[:300]` (user) / `answer_tldr or text[:300]` (model)

Output format: `<messages>\n<user>\n...\n</user>\n\n<model>\n...\n</model>\n</messages>`

The `llm_based_extracted_context` (bullet points from windowed extraction) is appended after the messages block.

### Key files

| File | Role |
|------|------|
| `code_common/auto_context.py` | All auto context logic (~720 lines) |
| `Conversation.py` `reply()` ~L7745 | Mode detection, future firing |
| `Conversation.py` `reply()` ~L9468 | Future resolution, assembly, override |
| `interface/interface.html` `#settings-historySelector` | UI dropdown |
| `interface/common.js` `getOptions()` | Passes value to backend as string |

---

## Per-Message Metadata

As a companion feature, each message now stores metadata generated asynchronously at persist time (zero latency — futures fire at turn start, resolve during streaming):

**User message fields:**
- `user_ask_tldr` — 1-2 sentence summary of the user's query (generated when > 20 words)
- `user_ask_keywords` — structured JSON `{entities, topics, technical_terms, general_terms}` (> 20 words)
- `user_ask_prior_context` — 2-3 sentences describing conversation state at time of message (> 20 words, requires existing summary)

**Model message fields:**
- `answer_tldr` — extracted from `<answer_tldr>` tag in response (generated when answer > 300 words)
- `answer_keywords` — same structure as user keywords, generated from answer text

These fields are used by the classifier's compact message representation (`_compact_message_repr`) — instead of sending full message text to the classifier LLM, it sends the tldr + keywords, which is much cheaper and faster. For old messages without these fields, it falls back to `text[:200]`.

### Async generation pattern

All four metadata futures fire at the top of `reply()` in parallel with `prior_context_future`:

```python
# All fire immediately, resolve during streaming — zero latency
user_ask_tldr_future        = get_async_future(llm, user_ask_tldr_prompt.format(...))
user_ask_keywords_future    = get_async_future(llm, keyword_extraction_prompt.format(...))
user_ask_prior_context_future = get_async_future(llm, user_ask_prior_context_prompt.format(...))
```

They are collected in `_persist_current_turn_inner()` with 30s timeouts each. `answer_keywords` is generated inside `_persist_current_turn_inner` from the final response text.

### `persist_current_turn` wrapper

`persist_current_turn` now has a try/except wrapper that delegates to `_persist_current_turn_inner`. Any exception is logged with `exc_info=True` to `error_logger` — previously all failures were silently swallowed since the function runs in a thread via `get_async_future`.

### API exposure

`list_messages()` exposes all four new fields when present:

```python
for field in ("user_ask_tldr", "user_ask_keywords", "user_ask_prior_context", "answer_keywords"):
    val = msg.get(field)
    if val:
        entry[field] = val
```

These are available to the tool-calling agent via `list_messages` and `read_message` tools, enabling the agent to use metadata for relevance decisions without reading full message text.

---

## Data Flow

```
enablePreviousMessages = "auto-medium"
    │
    ├─ message_lookback = 4  (2 turns × 2, from MEDIUM config)
    ├─ prior_context_future fired  (last 4 messages verbatim anchor)
    ├─ prior_context_llm_based_future fired  (windowed extraction, 30 msg lookback)
    ├─ _auto_classifier_future fired  (classify last 30 msgs)
    └─ _auto_agent_future fired  (tool-calling agent, 3 iterations)
    
    ... main LLM streams to user ...
    
    prior_context resolves → previous_messages set to anchor turns
    prior_context_llm_based resolves (timeout 120s)
    classifier resolves (timeout 90s)
    agent resolves (timeout 90s)
    
    assemble_auto_context() merges all signals
    
    previous_messages = assembled context  (overrides all 4 variants)
    prior_context_llm_based_context = ""   (already embedded)
    
    chat_slow_reply_prompt.format(previous_messages=assembled, ...)
```

---

## UI

The history selector (`#settings-historySelector`) has three new options at the bottom:

```html
<option value="auto-light">Auto Light</option>
<option value="auto-medium" selected>Auto Medium</option>
<option value="auto-deep">Auto Deep</option>
```

The string value flows through `getOptions()` → `enable_previous_messages` checkbox → backend unchanged. The backend detects `startswith("auto-")` before attempting `int()` conversion to avoid `ValueError`.

Status messages shown during streaming:
- `"Prior context LLM based extraction done with len = N tokens ..."` — always shown (N=0 in auto mode since we zero it out after embedding)
- `"Auto context [medium] assembled with K tokens ..."` — shown after assembly

---

## Bugs Found and Fixed During Implementation

### 1. `int()` crash on auto mode values
`enablePreviousMessages = "auto-medium"` → `int("auto-medium")` → `ValueError`. Fixed by adding `elif enablePreviousMessages.startswith("auto-"):` branch before the `else: int(...)` branch.

### 2. `assemble_auto_context` not in try/except
Any exception inside assembly propagated up through the generator, killing the entire reply — `persist_current_turn` was never reached and messages were not saved. Fixed by wrapping the entire assembly block in try/except with `exc_info=True` logging.

### 3. Wrong tool call chunk format in `agentic_context_finder`
`call_llm` yields tool calls as `{"type":"tool_call", "id":..., "function":{"name":..., "arguments":...}}` but the agent was reading `chunk.get("tool_name")`, `chunk.get("tool_input")`, `chunk.get("tool_id")` — all returning None/empty. Tools executed with empty inputs, returned nothing, agent output `{"decisions": [], "done": true}`. Fixed by normalising the chunk at read time.

### 4. `prompts.keyword_extraction_prompt` AttributeError
In `Conversation.py`, `prompts` is a `CustomPrompts` instance, not the module. New prompts added as module-level variables in `prompts.py` are available via `from prompts import *` as bare names, not as `prompts.X`. Fixed by removing the `prompts.` prefix from all four new prompt usages.

### 5. Hang after a few messages
Bare `.result()` calls on `prior_context_llm_based_future`, `_auto_classifier_future`, `_auto_agent_future` — no timeout. For conversations with several messages, windowed LLM extraction spawns multiple parallel API calls; if any stall, `.result()` blocks the generator thread forever. Fixed by replacing all three with `sleep_and_get_future_result(..., timeout=90/120)`.

### 6. Memory pad not injected for Deep mode on assembly failure
The `inject_memory_pad` check was inside the `assemble_auto_context` try block. If assembly raised an exception, memory pad was never set. Fixed by moving the check to before the try block so it always runs for Deep mode.

### 7. Classifier too aggressive about returning `none`
Medium mode prompt said "be conservative / only mark verbatim if truly necessary" and Light said "be aggressive about none". Both caused the LLM to mark most messages as `none`. Rewritten to: "only use none if clearly unrelated". Also added fallback in `assemble_auto_context`: if merged result is empty after dedup, include all pre-anchor messages as paraphrased.

### 8. `persist_current_turn` silent failures
The function ran in a thread via `get_async_future` — any exception was silently swallowed. Added a top-level try/except wrapper that logs with `exc_info=True`, delegating to `_persist_current_turn_inner`. This surfaced the `keyword_extraction_prompt` AttributeError (bug #4 above).

### 9. `prior_context_future.result()` bare call
`prior_context_future.result()` at L7908 and L9448 are still bare (no timeout). These call `retrieve_prior_context` (the 4-bucket verbatim system, not LLM-based), which is fast and unlikely to hang. Left as-is intentionally — adding timeouts there would require handling partial `prior_context` dicts.

### 10. `_AUTO_MODE_MAP` uses string values not enum
The map uses `"DEEP"/"MEDIUM"/"LIGHT"` strings then calls `AutoContextMode(name.lower())`. This works because `AutoContextMode.DEEP = "deep"` etc. — the enum values are lowercase strings matching the `.lower()` of the map values.

---

## Configuration Reference

```python
AUTO_CONTEXT_CONFIGS = {
    AutoContextMode.DEEP: {
        "lookback_turns": 2,
        "llm_based_lookback": 50,
        "classify_lookback": 50,
        "classify_window_size": 5,
        "agent_max_iterations": 3,
        "dedup_rule": "any_verbatim_wins",
        "inject_memory_pad": True,
        "llm_based_single_call": False,
    },
    AutoContextMode.MEDIUM: {
        "lookback_turns": 2,
        "llm_based_lookback": 30,
        "classify_lookback": 30,
        "classify_window_size": 5,
        "agent_max_iterations": 3,
        "dedup_rule": "any_verbatim_wins",
        "inject_memory_pad": False,
        "llm_based_single_call": False,
    },
    AutoContextMode.LIGHT: {
        "lookback_turns": 1,
        "llm_based_lookback": 20,
        "classify_lookback": 20,
        "classify_window_size": 20,
        "agent_max_iterations": 2,
        "dedup_rule": "paraphrase_wins",
        "inject_memory_pad": False,
        "llm_based_single_call": True,
    },
}
```

---

## Prompts

All prompts live in `prompts.py` as module-level variables (not in `CustomPrompts` / `create_base_prompts.py`):

- `user_ask_tldr_prompt` — 1-2 sentence user query summary
- `keyword_extraction_prompt` — structured JSON keyword extraction
- `user_ask_prior_context_prompt` — conversation state at message time

Classifier system prompts (`_CLASSIFY_SYSTEM_DEEP/MEDIUM/LIGHT`) and agent system prompts (`_AGENT_SYSTEM_DEEP/MEDIUM/LIGHT`) are in `code_common/auto_context.py`.

---

## Thresholds

| Condition | Threshold |
|-----------|-----------|
| Generate `user_ask_tldr` | user message > 20 words |
| Generate `user_ask_keywords` | user message > 20 words |
| Generate `user_ask_prior_context` | user message > 20 words AND summary exists |
| Generate `answer_tldr` | answer > 300 words |
| Generate `answer_keywords` | answer > 20 words |
