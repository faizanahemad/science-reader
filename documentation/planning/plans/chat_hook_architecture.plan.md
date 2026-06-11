# Chat Architecture: Pre/Post Message Hook System

**Status:** Draft
**Created:** 2026-06-11
**Scope:** Refactor the `Conversation.reply()` monolith (~400 lines of pre-LLM setup, streaming, and ~300 lines of post-LLM persistence/analysis) into a declarative hook-based pipeline. Enable PKB and other integrations to register as hooks rather than being hard-coded into the reply flow.

---

## 1. Background — What Runs Today (Hard-Coded)

The entire chat flow lives in `Conversation.reply()` (~13,768 lines total in `Conversation.py`). There is **no hook system, no plugin registry, no middleware chain**. Everything is inline `if/elif` branches and parallel futures.

### Current Pre-Message (before LLM call)

| Step | What it does | Trigger condition | Latency |
|------|-------------|-------------------|---------|
| Lock acquisition | Per-conversation file lock | Always | ~0ms (or 10s wait) |
| Slash command routing | `/pkb`, `/image`, `/title`, `/temp`, `/enable_*` | Message starts with `/` | ~0ms |
| Checkbox override parsing | `/enable_X`, `/disable_X` in message | Slash commands in text | ~0ms |
| PKB context retrieval | Hybrid search (6 strategies: FTS, embedding, rewrite, entity, tag, mapreduce; RRF fusion; k=15), reference resolution, STM injection | `PKB_AVAILABLE + use_pkb=True` | ~200-500ms |
| Prior context retrieval | 5 length variants of conversation history | Always (if persist) | ~50ms |
| Prior context LLM-based | Semantic extraction of relevant history | Always | ~1-3s |
| Auto-classifier + auto-agent | Classify intent, route to context finder | `auto_context` mode | ~2-5s |
| User ask analysis | TLDR, keywords, prior context of user message | Message > 20 words | ~1-2s (parallel) |
| Reward evaluation | Initiate async critique signal | `reward_level > 0` | ~2-5s (async) |
| Model/field/preamble resolution | Select agent, model, system prompt | Always | ~0ms |
| Tool configuration | Build tools list, inject tool docs into preamble | `enable_tool_use=True` | ~0ms |
| Web search | Google/Scholar + Perplexity | `perform_web_search=True` | ~2-5s (async) |
| Document reading | Conversation docs + global docs + link reading | Docs/links present | ~2-10s (async) |
| User memory distillation | Extract relevant user preferences for query | `user_memory` set | ~1-2s (parallel) |
| Auto-context assembly | Override history with agentic-found context | Auto mode | ~5-15s |
| Web search summary | Summarize batches of web results | Web search returned results | ~2-5s |
| Final prompt assembly | Combine all context into final prompt string | Always | ~0ms |

### Current Post-Message (after LLM response)

**During streaming (inline):**

| Step | What it does | Trigger condition |
|------|-------------|-------------------|
| DrawIO extraction | Extract/save `.xml` diagrams | `<drawio>` tags in response |
| Mermaid extraction | Normalize mermaid blocks | ` ```mermaid` in response |
| Code execution | Run `<code action="execute">` blocks | Code tags in response |
| Reward collection (non-blocking) | Check if reward eval finished | `reward_level > 0` |
| Cancellation check | Stop streaming if user cancelled | Every 200 chars |

**After streaming completes (in reply()):**

| Step | What it does | Trigger condition |
|------|-------------|-------------------|
| TLDR generation | Summarize long answers | Answer > 300 words |
| Visual tab | Generate visual learning content | Deep Learn mode |
| Reward output (blocking) | Collect and emit reward output | `reward_level > 0` |
| Web links appendage | Append remaining search links | Web search ran |

**After streaming completes (async, in persist_current_turn):**

| Step | What it does | Trigger condition |
|------|-------------|-------------------|
| Summary + title generation | LLM call to create conversation summary | Always (if persist) |
| Next question suggestions | LLM call to create follow-up suggestions | Always (if persist) |
| Memory pad update | LLM distills new facts into rolling memory | Always (if persist) |
| Message storage | Save user + assistant messages to disk | Always (if persist) |
| Running summary update | Store updated conversation summary | Always (if persist) |
| Search indexing | Index messages for BM25 | Always (fail-open) |
| Cross-conversation indexing | Update cross-conv search index | Index exists |
| Keyword extraction | Extract answer keywords | Answer > 20 words |
| Message hash generation | Generate short hashes for references | Friendly ID exists |

**After streaming completes (in endpoint layer, `endpoints/conversations.py`):**

| Step | What it does | Trigger condition |
|------|-------------|-------------------|
| Auto-doubt threads (5) | Takeaways, maximize learning, challenge/verify, foundations, raised questions | `persist + auto_doubts_enabled` + per-conv `auto_doubt_categories` filter |

**After streaming completes (client-side, `common-chat.js`):**

| Step | What it does | Trigger condition |
|------|-------------|-------------------|
| PKB memory extraction | `POST /pkb/propose_extraction` → extract_and_propose | `auto_pkb_extract=True` + not `/pkb` command |

---

## 2. Problems with Current Architecture

1. **Monolithic coupling** — Adding any new pre/post behavior requires editing `reply()`, understanding 400+ lines of context, and risking regressions in unrelated flows.
2. **No ordering control** — Steps are implicitly ordered by code position. Changing order requires moving code blocks.
3. **No conditional disabling** — Skipping a step requires `if` guards everywhere. Each integration checks its own conditions.
4. **Mixed concerns** — PKB retrieval, web search, doc reading, model selection, prompt assembly are all interleaved in one method.
5. **No error isolation** — A crash in PKB context retrieval could fail the entire reply (though most are try/except wrapped individually).
6. **Client-side hooks** — PKB extraction runs client-side (in JS after stream) which is fragile (page reload loses it, mobile clients skip it).
7. **Testing difficulty** — Can't test individual hooks in isolation; must mock the entire Conversation.
8. **No observability** — Can't measure individual hook latency from outside (only `time_logger` prints inside).

---

## 3. Proposed Architecture — Hook Pipeline

### Core Concept

Replace the inline pre/post code with a **hook registry** where each hook is a small class declaring:
- **Phase** — when it runs (pre-context, pre-prompt, post-stream, post-persist)
- **Priority** — execution order within a phase
- **Condition** — when to activate (returns bool)
- **Async** — whether it runs as a parallel future or blocks

```python
class Hook:
    phase: HookPhase          # ENUM: PRE_CONTEXT, PRE_PROMPT, STREAM_FILTER, POST_STREAM, POST_PERSIST
    priority: int = 100       # Lower runs first; default 100
    async_parallel: bool = True  # If True, launched as future; results collected before next phase
    timeout_ms: int = 2000    # Hard timeout; hook killed after this (graceful skip, logged)

    def should_run(self, ctx: HookContext) -> bool: ...
    def execute(self, ctx: HookContext) -> HookResult: ...
```

**Timeout discipline (inspired by Claude Code's 1500ms hook timeout):** Every hook has a hard timeout. If it exceeds it, the pipeline logs a warning and continues without that hook's contribution. Suggested defaults per phase:
- ROUTING: 500ms (should be instant — local routing logic)
- PRE_CONTEXT: 3000ms (PKB), 5000ms (web search), 500ms (local data like history/summary)
- PRE_PROMPT: 1000ms (all local assembly)
- STREAM_FILTER: per-chunk, 5000ms per filter invocation (code execution may be longer)
- POST_STREAM: 5000ms (TLDR generation involves an LLM call)
- POST_PERSIST: 30000ms (async, non-blocking — can be generous since user isn't waiting)

### Phases

```
User Message Arrives
        │
        ▼
┌─────────────────────────┐
│  ROUTING (phase 0)      │  Slash commands, agent dispatch
│  Synchronous, ordered   │  Can short-circuit entire pipeline
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  PRE_CONTEXT (phase 1)  │  Gather context: PKB, history, web, docs, STM
│  Parallel futures       │  Each hook contributes to ctx.context_parts
└───────────┬─────────────┘
            │  (await all futures)
            ▼
┌─────────────────────────┐
│  PRE_PROMPT (phase 2)   │  Assemble final prompt from context parts
│  Sequential             │  Model selection, tool config, prompt template
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  LLM CALL               │  Tool loop or direct call (core, not a hook)
└───────────┬─────────────┘
            │ (streaming)
            ▼
┌─────────────────────────┐
│  STREAM_FILTER (phase 3)│  Transform/intercept stream chunks
│  Sequential pipeline    │  DrawIO, Mermaid, code exec, math formatting
└───────────┬─────────────┘
            │ (stream complete)
            ▼
┌─────────────────────────┐
│  POST_STREAM (phase 4)  │  TLDR, visual tab, reward output
│  Sequential             │  Has access to full response text
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  POST_PERSIST (phase 5) │  Async fire-and-forget:
│  Parallel futures       │  Summary, memory pad, search index, PKB extract,
│  (non-blocking)         │  auto-doubts, next-question suggestions
└─────────────────────────┘
```

### HookContext (shared state bag)

```python
@dataclass
class HookContext:
    # Input
    conversation: "Conversation"
    query_text: str
    query_dict: dict              # Full query with checkboxes, attachments, etc.
    user_email: str
    
    # Metadata (enriched automatically before any hook fires)
    client_type: str = "browser"  # "browser", "mcp", "rest_api", "opencode"
    timestamp: datetime = None    # When the message arrived
    timezone: str = ""            # User's timezone (from session/settings)
    conversation_turn_count: int = 0  # How deep into the conversation we are
    session_message_count: int = 0    # Messages today across all conversations
    recent_topics: list = field(default_factory=list)  # Topics from recent conversations (for cross-conv context)
    
    # Accumulated by PRE_CONTEXT hooks
    context_parts: dict[str, str] = field(default_factory=dict)
    # Keys: "pkb", "stm", "web_search", "documents", "user_memory",
    #        "previous_messages", "running_summary", etc.
    
    # Set by PRE_PROMPT hooks
    system_prompt: str = ""
    model_name: str = ""
    tools_config: list = field(default_factory=list)
    prompt: str = ""
    images: list = field(default_factory=list)
    
    # Accumulated during/after LLM call
    response_text: str = ""       # Full accumulated response
    response_message_id: str = ""
    tool_calls: list = field(default_factory=list)
    
    # Timing/observability
    timings: dict[str, float] = field(default_factory=dict)
    
    # Control flow
    short_circuit: bool = False   # If True, skip remaining phases
    skip_persist: bool = False
```

### HookResult

```python
@dataclass
class HookResult:
    success: bool = True
    context_key: str = ""         # Which context_parts key this contributes to
    context_value: str = ""       # The content to inject
    error: str = ""               # If failed (non-fatal)
    timing_ms: float = 0
```

---

## 4. Hook Catalog — Mapping Current Code to Hooks

### ROUTING hooks (phase 0)

| Hook | Priority | Current location | Behavior |
|------|----------|-----------------|----------|
| `SlashCommandRouter` | 10 | `reply()` top | Parse `/pkb`, `/image`, `/title`, `/enable_*`; set `short_circuit` if handled |
| `OpenCodeRouter` | 20 | `reply()` top | Route to OpenCode if enabled; set `short_circuit` |
| `AgentFieldRouter` | 30 | `reply()` model resolution | Route to specialized agent class |

### PRE_CONTEXT hooks (phase 1) — all async-parallel

| Hook | Priority | Current location | Contributes |
|------|----------|-----------------|-------------|
| `PreviousMessagesHook` | 10 | `retrieve_prior_context()` (line 3167) | `ctx.context_parts["previous_messages"]` |
| `RunningSummaryHook` | 10 | `self.running_summary` property | `ctx.context_parts["running_summary"]` |
| `PKBContextHook` | 20 | `_get_pkb_context()` (line 519) | `ctx.context_parts["pkb"]`, `ctx.context_parts["stm"]` |
| `WebSearchHook` | 30 | `web_search_queue()` + Perplexity | `ctx.context_parts["web_search"]` |
| `DocumentReadHook` | 30 | `get_multiple_answers()` | `ctx.context_parts["documents"]` |
| `LinkReadHook` | 30 | `read_over_multiple_links()` | `ctx.context_parts["links"]` |
| `UserMemoryHook` | 40 | User memory distillation | `ctx.context_parts["user_memory"]` |
| `PriorContextLLMHook` | 40 | `retrieve_prior_context_llm_based()` (line 3251) | `ctx.context_parts["prior_context_deep"]` |
| `AutoContextHook` | 50 | Auto-classifier + auto-agent | Overrides `ctx.context_parts["previous_messages"]` |
| `UserAskAnalysisHook` | 60 | TLDR/keywords/prior of user msg | `ctx.context_parts["user_ask_metadata"]` (stored, not in prompt) |
| `RewardInitHook` | 90 | `_initiate_reward_evaluation()` | Stores future in `ctx` for POST_STREAM |

**Note on PKBContextHook internals:** PKB retrieval now runs a multi-strategy hybrid search with RRF fusion. Active strategies include:
- FTS (full-text search)
- Embedding (semantic similarity)
- Rewrite (LLM query rewrite → re-search)
- Entity (named entity → linked claims)
- Tag (category tag → linked claims, boost-only corroboration mode) — NEW, gated by `config.tag_strategy_enabled`
- MapReduce (for long queries)

The tag strategy (W-D, 2026-06-11) is currently **inert by default** (`tag_strategy_enabled=False`). When enabled, it operates in boost-only mode: tags only re-rank claims that another strategy also found — never introduces tag-only claims. This is transparent to the hook architecture; it's an internal implementation detail of `_get_pkb_context()`.

### PRE_PROMPT hooks (phase 2) — sequential

| Hook | Priority | Current location | Does |
|------|----------|-----------------|------|
| `ModelSelectionHook` | 10 | Checkbox → model name | Sets `ctx.model_name` |
| `PreambleAssemblyHook` | 20 | `get_preamble()` + preamble_options | Sets `ctx.system_prompt` |
| `ToolConfigHook` | 30 | `_get_enabled_tools()` | Sets `ctx.tools_config`, appends tool docs to system_prompt |
| `PromptAssemblyHook` | 50 | `prompts.chat_slow_reply_prompt.format(...)` | Sets `ctx.prompt` from context_parts |
| `WebSearchSummaryHook` | 40 | Summarize web results (blocking wait) | Enriches `ctx.context_parts["web_search"]` |

### STREAM_FILTER hooks (phase 3) — sequential pipeline

| Hook | Priority | Current location | Does |
|------|----------|-----------------|------|
| `MathFormattingFilter` | 10 | `stream_text_with_math_formatting()` | Buffers/reformats LaTeX |
| `DrawIOFilter` | 20 | `_process_stream_artifacts()` | Extracts diagrams, yields embed HTML |
| `MermaidFilter` | 30 | `_process_stream_artifacts()` | Normalizes mermaid blocks |
| `CodeExecutionFilter` | 40 | `code_runner_with_retry()` | Runs code blocks, yields output |
| `CancellationFilter` | 99 | `is_cancelled()` check | Terminates stream |

### POST_STREAM hooks (phase 4) — sequential

| Hook | Priority | Current location | Does |
|------|----------|-----------------|------|
| `TLDRHook` | 10 | TLDR generation | Appends TLDR to response |
| `VisualTabHook` | 20 | Visual tab future | Appends visual content |
| `RewardOutputHook` | 30 | `_collect_reward_output(block=True)` | Appends reward/critique |
| `WebLinksAppendHook` | 40 | Remaining search links | Appends collapsible links |
| `TimingStatsHook` | 90 | `time_dict` YAML block | Appends timing info |

### POST_PERSIST hooks (phase 5) — all async-parallel, fire-and-forget

Today these are tangled inside `_persist_current_turn_inner` — a single 250-line method under one `FileLock` where a slow summary LLM call (up to 30s) blocks memory pad, search indexing, and everything else. As independent parallel hooks with timeouts, they become isolated: a slow summary doesn't delay memory pad or keyword extraction.

The auto-doubt system was recently refactored (2026-06-11) to use a dispatch table with per-conversation category selection and model override — this is already structured like a hook and is the easiest candidate to extract.

| Hook | Priority | Current location | Does | Timeout |
|------|----------|-----------------|------|---------|
| `MessagePersistenceHook` | 5 | Message storage in `_persist_current_turn_inner` | Saves user/assistant messages to disk (the only one needing FileLock) | 5000ms |
| `SummaryGenerationHook` | 10 | `_persist_current_turn_inner` LLM call | LLM generates conversation summary + title; stores in memory field | 15000ms |
| `MemoryPadUpdateHook` | 20 | `add_to_memory_pad_from_response()` | LLM distills new facts into rolling memory pad | 15000ms |
| `SearchIndexHook` | 30 | `_index_messages_for_search()` | BM25 indexing of new messages | 3000ms |
| `CrossConvIndexHook` | 30 | `_cross_conv_index.index_new_messages()` | Cross-conversation search indexing | 3000ms |
| `PKBExtractionHook` | 40 | Currently client-side (`checkMemoryUpdates`) | **Move server-side**: extract_and_propose → silent/proposal mode | 15000ms |
| `NextQuestionHook` | 50 | `create_next_question_suggestions()` | LLM generates follow-up suggestions | 10000ms |
| `AutoDoubtHook` | 60 | `endpoints/conversations.py` line 1977 (`_AUTO_DOUBT_DISPATCH`) | Dispatch selective auto-doubt categories with model override | 30000ms |
| `KeywordExtractionHook` | 70 | Answer keyword extraction | Extract keywords from response | 5000ms |
| `MessageHashHook` | 80 | `generate_message_short_hash()` | Generate reference hashes | 500ms |
| `RAGQualityHook` | 85 | NEW | Score PKB context usage in response | 10000ms |
| `ConversationAnalyticsHook` | 90 | NEW | Track conversation patterns, topic shifts | 5000ms |
| `PredictivePrefetchHook` | 95 | NEW (Hermes-inspired) | Pre-warm next-turn PKB/context cache | 30000ms |

**Auto-doubt dispatch (current implementation, ready for hook extraction):**
```python
# endpoints/conversations.py line 1977 — already a clean dispatch table
_AUTO_DOUBT_DISPATCH = {
    "takeaways": _create_auto_takeaways_doubt_for_last_assistant_message,
    "maximize_learning": _create_maximize_learning_doubt,
    "challenge_verify": _create_challenge_and_verify_doubt,
    "foundations_practice": _create_foundations_and_practice_doubt,
    "answer_questions": _create_answer_raised_questions_doubt,
}
_conv_settings = conversation.get_conversation_settings() or {}
_enabled_categories = _conv_settings.get("auto_doubt_categories")  # None = all
for _cat, _func in _AUTO_DOUBT_DISPATCH.items():
    if _enabled_categories is None or _cat in _enabled_categories:
        get_async_future(_func, **_auto_doubt_kwargs)
```
Model: `conversation.get_model_override("auto_doubt_model", "gemini-flash-3.5-non-reasoning")`

**Key ordering constraints and independence:**
- `MessagePersistenceHook` (priority 5) writes messages first — only hook needing the `FileLock`
- `SummaryGenerationHook` and `MemoryPadUpdateHook` both need only `ctx.response_text` (already in HookContext) — fully parallel, no dependency on each other or on message persistence
- `PKBExtractionHook` needs only `ctx.query_text` + `ctx.response_text` — fully independent
- `AutoDoubtHook` needs `ctx.response_message_id` + conversation reference — fully independent of persistence
- `PredictivePrefetchHook` runs last — uses conversation summary if available, degrades gracefully if not
- **Thread safety:** `PKBDatabase` now uses a `threading.RLock` on its shared connection (commit `0fdaa15`), so multiple parallel POST_PERSIST hooks calling PKB methods concurrently are safe — no `SQLITE_MISUSE` risk

---

## 5. PKB Integration as Hooks

Today PKB touches the pipeline at 3 points. Under the hook architecture:

### PKBContextHook (PRE_CONTEXT, priority 20)

```python
class PKBContextHook(Hook):
    phase = HookPhase.PRE_CONTEXT
    priority = 20
    async_parallel = True

    def should_run(self, ctx):
        return (PKB_AVAILABLE 
                and ctx.query_dict.get("checkboxes", {}).get("use_pkb", True)
                and ctx.user_email)

    def execute(self, ctx):
        api = get_pkb_api(ctx.user_email)
        # Hybrid search, reference resolution, STM injection
        pkb_text, stm_text, audit = self._retrieve(api, ctx)
        ctx.context_parts["pkb"] = pkb_text
        ctx.context_parts["stm"] = stm_text
        ctx.metadata["pkb_audit"] = audit
        return HookResult(success=True, timing_ms=...)
```

### PKBExtractionHook (POST_PERSIST, priority 40)

**Key change:** Move from client-side JS to server-side hook. This makes extraction reliable (no page reload loss, works for all clients including MCP/API).

```python
class PKBExtractionHook(Hook):
    phase = HookPhase.POST_PERSIST
    priority = 40
    async_parallel = True
    timeout_ms = 15000  # Extraction involves an LLM call

    def should_run(self, ctx):
        return (PKB_AVAILABLE
                and ctx.user_email
                and not ctx.skip_persist
                and ctx.query_dict.get("checkboxes", {}).get("auto_pkb_extract", True)
                and not ctx.query_text.startswith("/pkb"))

    def execute(self, ctx):
        api = get_pkb_api(ctx.user_email)
        plan = api.distiller.extract_and_propose(
            user_message=ctx.query_text,
            assistant_message=ctx.response_text,
        )
        if plan.candidates:
            for c in plan.candidates:
                if c.confidence >= 0.85:
                    # Silent mode: auto-accept, no user notification
                    api.add_claim(statement=c.statement, claim_type=c.claim_type,
                                  context_domain=c.context_domain, source="auto_extract")
                else:
                    # Proposal mode: queue for review, show badge count on next page load
                    api.queue_proposal(c)
        return HookResult(success=True)
```

**Silent vs proposal mode (inspired by Hermes's silent "Sync" pattern):**
- **Silent mode** (confidence ≥ 0.85): Auto-accept into PKB with `source="auto_extract"`. No toast, no modal, no interruption. User can review in the Maintenance tab's "Recently Auto-Extracted" section.
- **Proposal mode** (confidence < 0.85): Queue for user review. UI shows a subtle badge count ("3 pending proposals") on the PKB icon. User clicks to review/accept/reject at their leisure.

This replaces the current client-side `checkMemoryUpdates` which fires a modal immediately — disruptive and fragile (lost on page reload, doesn't work for MCP/API clients).

### PKBNLCommandHook (ROUTING, priority 15)

Handles `/pkb` and `/memory` slash commands — routes to `PKBNLConversationAgent`.

---

## 6. Other Hooks We Can Build

Beyond reorganizing existing code, the hook architecture enables new capabilities:

### Content Safety / Moderation (PRE_PROMPT, priority 5)

Currently **no content moderation exists**. A hook can:
- Check user message against a policy classifier before sending to LLM
- Filter/redact PII from the prompt
- Enforce per-user content policies

### Response Validation (POST_STREAM, priority 5)

- Check response for hallucination markers
- Validate code blocks compile/parse
- Flag responses that contradict PKB claims

### Conversation Analytics (POST_PERSIST, priority 90)

- Track conversation patterns, topic shifts
- Compute engagement metrics
- Feed into recommendation systems

### RAG Quality Scoring (POST_PERSIST, priority 45)

- Score how well PKB context was used in the response
- Track retrieval precision/recall over time
- Feed back into PKB relevance ranking

### Custom User Hooks (all phases)

Allow users to define lightweight hooks via settings:
- "Always search web for code questions"
- "Include my project README in every response"
- "Extract action items from every response"

### Agent Orchestration (ROUTING, priority 25)

- Route complex queries to multi-step agent pipelines
- Decide whether single-shot or tool-loop is needed
- Select specialized agents based on query classification

### Doubt-to-PKB Feedback Loop (POST_PERSIST, priority 65)

Leverage the recently implemented doubt system (pin/star, summarization, bookmarks, regeneration, global view) to feed insights back into PKB:
- When a doubt thread is summarized, check if the summary contains correctable facts → propose PKB edits
- When a user pins a doubt, extract the underlying claim as a PKB candidate
- When `create_conversation_from_doubt_thread` fires, link the new conversation's future extractions to the doubt's topic context

### Response Caching (PRE_PROMPT, priority 99)

- Check if an identical or semantically-similar query was recently answered
- Return cached response (with freshness indicator) instead of re-calling LLM

### Predictive Prefetch (POST_PERSIST, priority 95)

Inspired by Hermes's "Background Prefetch" — predict what context the *next* turn will need while the user reads the current response.
- After response completes, use conversation trajectory (running summary + last few turns) to predict likely follow-up queries
- Pre-warm PKB search cache with results for predicted queries
- Pre-compute STM candidates likely relevant next turn
- Store in a short-lived per-conversation cache (`_prefetch_cache`) that `PKBContextHook` checks first on next turn
- Timeout: generous (30s) since it's entirely background and non-blocking
- Cost: 1 cheap LLM call to predict next query + 1-2 embedding searches — negligible vs the value of shaving 200-500ms off next-turn PKB retrieval

### Input Normalization (ROUTING, priority 5)

Ingress-style pre-processing before any hooks fire:
- Normalize whitespace, strip invisible characters
- Detect and tag language (useful for multilingual PKB retrieval)
- Extract inline references (`@friendly_id`, `#doc_N`, URLs) into structured `ctx.query_dict` fields
- Rate limit validation (reject if user is flooding)

### Lightweight Custom User Hooks (all phases)

Inspired by OpenCode's `tui.prompt.append` — a simple function-based hook format for power users:

```python
# User drops this in their settings or a hooks/ directory
# No need to understand HookPhase/HookContext/HookResult — just a function

def before_prompt(query_text: str, context_parts: dict) -> dict:
    """Modify context_parts before prompt assembly. Return modified dict."""
    context_parts["custom_instruction"] = "Always prefer TypeScript over JavaScript"
    return context_parts

def after_response(query_text: str, response_text: str) -> None:
    """Fire-and-forget after response. No return value needed."""
    # e.g., log to external system, trigger webhook
    pass
```

The framework wraps these in proper Hook instances at registration time. Configuration via a settings JSON:
```json
{
  "custom_hooks": [
    {"phase": "before_prompt", "script": "~/.config/assist-chat/hooks/inject_project_readme.py"},
    {"phase": "after_response", "script": "~/.config/assist-chat/hooks/log_to_notion.py", "timeout_ms": 5000}
  ]
}
```

---

## 7. Implementation Plan

### Phase 1: Framework (no behavior change)

- **T1.1** Define `Hook`, `HookPhase`, `HookContext`, `HookResult`, `HookRegistry` classes in `code_common/hooks.py`.
- **T1.2** Create `HookPipeline` class with `run_phase(phase, ctx)` that executes hooks in priority order, handles parallel futures, captures timings.
- **T1.3** Add `HookRegistry` singleton. Hooks register via decorator: `@register_hook` (similar to existing `@register_tool`).
- **T1.4** Unit test the framework with mock hooks.

### Phase 2: Extract first hooks (incremental, one at a time)

Start with the simplest, most self-contained pieces:

- **T2.1** `PreviousMessagesHook` — extract `_get_previous_messages()` call into a hook. Verify `reply()` still works.
- **T2.2** `RunningSummaryHook` — trivial; just reads `self.running_summary`.
- **T2.3** `PKBContextHook` — extract `_get_pkb_context()` into a hook. High value: decouples PKB from reply().
- **T2.4** `WebSearchHook` — extract web search future launch.
- **T2.5** `DocumentReadHook` — extract doc reading future.

After each extraction: the original code in `reply()` is replaced with `hook_pipeline.run_phase(PRE_CONTEXT, ctx)` call (or a subset if migrating incrementally).

### Phase 3: Post-processing hooks

- **T3.1** `PKBExtractionHook` — move from client-side to POST_PERSIST. Remove `checkMemoryUpdates` client call (keep as fallback for a release cycle).
- **T3.2** `SummaryGenerationHook` — extract from `_persist_current_turn_inner`.
- **T3.3** `MemoryPadUpdateHook` — extract `add_to_memory_pad_from_response`.
- **T3.4** `AutoDoubtHook` — move from endpoint layer into POST_PERSIST hook.
- **T3.5** `SearchIndexHook`, `CrossConvIndexHook`, `KeywordExtractionHook` — simple extractions.

### Phase 4: Stream filters

- **T4.1** Define `StreamFilter` interface (receives chunk, yields transformed chunks).
- **T4.2** Extract `DrawIOFilter`, `MermaidFilter`, `CodeExecutionFilter`.
- **T4.3** Extract `MathFormattingFilter` (currently wraps the entire generator).

### Phase 5: New hooks (new functionality)

- **T5.1** Content moderation hook (placeholder, configurable).
- **T5.2** Response validation hook.
- **T5.3** RAG quality scoring hook.
- **T5.4** Custom user hooks framework.

---

## 8. Migration Strategy

**Key constraint:** `Conversation.py` is 13,768 lines. We cannot rewrite it in one pass.

### Incremental extraction pattern:

1. Create the hook class in a separate file (e.g., `hooks/pkb_context_hook.py`).
2. In `reply()`, replace the inline code with a hook invocation:
   ```python
   # Before:
   pkb_context_future = get_async_future(self._get_pkb_context, ...)
   # ... 200 lines later ...
   pkb_context = pkb_context_future.result()
   
   # After:
   # (handled by HookPipeline.run_phase(PRE_CONTEXT, ctx))
   ```
3. The hook calls the same internal method (`_get_pkb_context`) — just wraps it in the hook interface.
4. Test that behavior is identical.
5. Over time, move the method body into the hook class and remove from Conversation.

### Coexistence period:

During migration, `reply()` will have a mix of:
- Old inline code (not yet extracted)
- Hook pipeline calls (already extracted)

This is fine — the hook pipeline handles its subset, and old code handles the rest. The `HookContext` accumulates `context_parts` regardless of whether they came from a hook or inline code.

### Feature flags:

```python
HOOKS_ENABLED = {
    "pkb_context": True,      # Use hook instead of inline code
    "web_search": False,      # Still inline
    "post_persist_pkb": True, # Server-side extraction
}
```

Each hook extraction can be toggled independently during testing.

---

## 9. Directory Structure

```
code_common/
  hooks.py                    # Framework: Hook, HookPhase, HookContext, HookPipeline, HookRegistry
hooks/                        # Hook implementations
  __init__.py
  routing/
    slash_command.py
    opencode_router.py
    pkb_nl_router.py
  pre_context/
    pkb_context.py
    previous_messages.py
    running_summary.py
    web_search.py
    document_read.py
    user_memory.py
    auto_context.py
  pre_prompt/
    model_selection.py
    preamble_assembly.py
    tool_config.py
    prompt_assembly.py
  stream_filters/
    math_formatting.py
    drawio.py
    mermaid.py
    code_execution.py
  post_stream/
    tldr.py
    visual_tab.py
    reward_output.py
  post_persist/
    summary_generation.py
    memory_pad.py
    pkb_extraction.py
    search_index.py
    auto_doubt.py
    next_question.py
```

---

## 10. Observability

Each hook execution automatically records:
- Hook name, phase, priority
- `should_run` result (was it skipped?)
- Execution time (ms)
- Success/failure
- Context contribution size (chars)

Exposed via:
- `time_dict` in the streaming YAML block (existing pattern)
- New `GET /conversation/<id>/hook_timings` endpoint for debugging
- Structured logging for aggregation

---

## 11. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Performance regression from hook overhead | Added latency per message | Framework is minimal (~1ms overhead); parallel hooks run same as current futures |
| Behavior change during extraction | Users notice different responses | Extract one hook at a time; feature-flag each; A/B test |
| Shared state bugs in HookContext | Hooks step on each other's data | Each hook writes only its own `context_key`; framework validates no conflicts |
| Ordering dependencies between hooks | Wrong context assembly | Explicit priority + documented dependencies; framework can enforce `depends_on` |
| `reply()` size during coexistence | Harder to read with mixed patterns | Accept temporarily; clean up after each batch of extractions |
| PKB extraction moved server-side | Client can no longer control timing | Keep `auto_pkb_extract` as a setting; hook checks it |

---

## 12. Success Metrics

- **Modularity:** Can add a new hook (e.g., content moderation) without modifying `Conversation.py`
- **Testability:** Each hook has isolated unit tests with mocked `HookContext`
- **Performance:** No measurable latency increase (hooks run same parallel futures as today)
- **PKB decoupled:** PKB integration is entirely in `hooks/pre_context/pkb_context.py` + `hooks/post_persist/pkb_extraction.py` — zero PKB code in `reply()`
- **Lines of code:** `reply()` reduced from ~700 active lines to ~100 (pipeline orchestration + LLM call)

---

## 13. Prior Art & Design Influences

| System | Pattern | What we adopt |
|--------|---------|---------------|
| **Hermes (Nous Research)** | "Prefetch" hook (sync, pre-LLM, pulls from vector store) | Already have this as `PKBContextHook`. Confirms our approach of forced injection > hoping LLM calls a tool. |
| **Hermes** | "Sync" hook (background thread, post-response, extracts facts silently) | `PKBExtractionHook` in POST_PERSIST. Silent mode for high-confidence. |
| **Hermes** | "Background Prefetch" (predict next turn, pre-warm cache) | `PredictivePrefetchHook` — speculative context warming. |
| **OpenClaw** | Ingress Middleware (authenticate, safety check, enrich metadata before core processing) | `InputNormalizationHook` at ROUTING priority 5 + metadata enrichment in HookContext construction. |
| **OpenClaw** | Tool Orchestration (custom Python tool classes in action space) | Already have via `@register_tool` in `code_common/tools.py`. Hook system is orthogonal. |
| **Claude Code** | `UserPromptSubmit` with hard 1500ms timeout, stdout→context injection | `timeout_ms` field on every Hook. Silent fail on timeout. |
| **Claude Code** | File-based hook config (`settings.json`) | Custom user hooks via JSON config pointing at Python scripts. |
| **OpenCode** | `tui.prompt.append` (simple function: text in → text out) | Lightweight custom user hook format: `before_prompt(query, context_parts) → context_parts`. |

**Key architectural insight confirmed across all systems:** Injecting memory/context *before* the prompt hits the LLM is universally preferred over relying on the LLM to "decide" to use a memory tool. This eliminates:
- Latency of an extra tool call round-trip
- Token waste from tool call syntax
- Risk of LLM choosing not to call the tool
- Hallucination from the LLM "filling in" when it should have retrieved

Our architecture already does this correctly. The hook system formalizes it and makes it extensible.

---

## 14. Open Questions

1. Should stream filters be a separate concept from hooks (they have different signatures — chunk in/chunks out vs ctx in/result out)?
2. Should hooks be able to modify `ctx.query_text` (e.g., a "query rewriter" hook for spelling correction)?
3. How to handle hooks that need results from other hooks (e.g., `PromptAssemblyHook` needs all PRE_CONTEXT results)? Phase ordering handles most cases, but explicit `depends_on` may be needed.
4. Should the auto-doubt threads (currently in endpoint layer) move into `Conversation` as a POST_PERSIST hook, or stay in the endpoint layer as a post-stream callback?
5. For the PKB extraction move to server-side: should we auto-accept high-confidence proposals, or always queue for user review? (Current plan: dual-mode with 0.85 threshold.)
6. Should custom user hooks be Python (unsafe, sandboxed) or declarative config (limited but safe)? Or both with a trust boundary?
7. For `PredictivePrefetchHook`: what's the cache eviction strategy? Per-conversation LRU? Time-based expiry? How many predicted queries to pre-warm?
8. Should `SummaryGenerationHook` and `MemoryPadUpdateHook` share a single LLM call (one prompt that returns both summary+title and memory pad update)? Would reduce cost but couples them.
9. How do we handle hook failures in POST_PERSIST gracefully? Today `_persist_current_turn_inner` has a broad try/except. Per-hook isolation is better but what about partial failures (messages persisted but summary failed)?
10. Should the metadata enrichment (timestamp, client_type, turn_count) be a hook itself or part of HookContext construction? (Plan: construction — it's framework-level, not optional.)

---

## 15. Relationship to Other Plans

- **`pkb_external_access_ui_mcp_rest_auth.plan.md`** — PKB hooks are a subset of this plan. The external access plan focuses on exposing PKB; this plan focuses on how PKB plugs into the chat flow.
- **`pkb_ux_improvements.plan.md`** — Completed; introduced STM, bulk operations, maintenance. These become hook inputs (STM in `PKBContextHook`).
- **`pkb_memory_system_improvements.plan.md`** — Internal PKB improvements. Hook architecture doesn't change the PKB internals, just how the chat flow calls them.
- **`doubt_system_enhancements.plan.md`** — Implemented (2026-06-11). Added pin/star, regeneration, summarization, doubt-to-chat injection, conversation seeding, selective categories, model override, global doubts view. The `AutoDoubtHook` wraps this — the dispatch table and category selection are already hook-shaped. New doubt features (summarize, regenerate, seed conversation) are user-initiated actions, not hooks.
- **`pkb_rewrite_entity_unification.plan.md`** — Entity/tag unification. The tag-linked retrieval strategy (W-D, boost-only mode) is the first step. Affects `PKBContextHook` internals but not the hook interface.

---

## Appendix A — Key Line Numbers in Conversation.py

```
Line     Method/Section
----     --------------
519      def _get_pkb_context(...)            → PKBContextHook
1066     def add_to_memory_pad_from_response  → MemoryPadUpdateHook
3167     def retrieve_prior_context(...)      → PreviousMessagesHook
3251     def retrieve_prior_context_llm_based → PriorContextLLMHook
3385     def create_next_question_suggestions → NextQuestionHook
3591     def persist_current_turn(...)        → POST_PERSIST orchestrator
3663     def _persist_current_turn_inner(...) → MessagePersistenceHook + SummaryGenerationHook
6204     def get_preamble(...)                → PreambleAssemblyHook
6728     def _get_enabled_tools(...)          → ToolConfigHook
7056     def _run_tool_loop(...)              → Core LLM call (not a hook)
7706     def reply(...)                       → Main entry point (the monolith to decompose)
11117    def _process_stream_artifacts(...)   → STREAM_FILTER hooks (DrawIO, Mermaid, Code)
11572    def _handle_image_generation(...)    → Routed via SlashCommandRouter
```

File: `Conversation.py` — 13,768 lines total.
File: `endpoints/conversations.py` — auto-doubt dispatch at line 1977.
File: `endpoints/pkb.py` — 83 routes, 4,127 lines.
File: `endpoints/doubts.py` — 13 routes (pin, bookmark, regenerate, summarize, create-conversation-from-thread, global view, etc.).

---

## Appendix B — Checkbox Keys → Hook Mapping

These are the `query["checkboxes"]` keys that control behavior in `reply()`:

| Key | Default | Controls which hook |
|-----|---------|---------------------|
| `use_pkb` | `True` | `PKBContextHook.should_run()` |
| `perform_web_search` | `False` | `WebSearchHook.should_run()` |
| `googleScholar` | `False` | `WebSearchHook` (scholar mode) |
| `enable_tool_use` | `True` | `ToolConfigHook` + tool loop path |
| `enabled_tools` | `{}` | `ToolConfigHook` (category filter) |
| `enable_previous_messages` | `True` | `PreviousMessagesHook.should_run()` |
| `use_memory_pad` | `True` | `UserMemoryHook` (memory pad injection) |
| `persist_or_not` | `True` | All POST_PERSIST hooks skip if False |
| `field` | `""` | `AgentFieldRouter` + `PreambleAssemblyHook` |
| `main_model` | `""` | `ModelSelectionHook` |
| `opencode_enabled` | `False` | `OpenCodeRouter.should_run()` |
| `reward_level` | `0` | `RewardInitHook` + `RewardOutputHook` |
| `pkb_scope` | `""` | `PKBContextHook` (domain filter) |
| `ensemble` | `False` | Ensemble mode (affects LLM call path) |
| `code_execution` | `False` | `CodeExecutionFilter.should_run()` |
| `preamble_options` | `[]` | `PreambleAssemblyHook` (modular sections) |
| `stream_check_interval_chars` | `200` | STREAM_FILTER check frequency |
| `agentic_search` | `False` | `AutoContextHook` |

Client-side only (in `common-chat.js`, not passed to server):
| Key | Default | Controls |
|-----|---------|----------|
| `auto_pkb_extract` | `True` | Client-side `checkMemoryUpdates` call (moves server-side as `PKBExtractionHook`) |

Endpoint-layer (in `endpoints/conversations.py`):
| Key | Default | Controls |
|-----|---------|----------|
| `auto_doubts_enabled` | `True` | `AutoDoubtHook` (currently lives in endpoint, not Conversation) |

Per-conversation settings (stored via `set_conversation_settings`, read from `get_conversation_settings()`):
| Key | Default | Controls |
|-----|---------|----------|
| `auto_doubt_categories` | `None` (all 5) | Which doubt categories to generate: `takeaways`, `maximize_learning`, `challenge_verify`, `foundations_practice`, `answer_questions` |
| `model_overrides.auto_doubt_model` | `"gemini-flash-3.5-non-reasoning"` | Model for all auto-doubt LLM calls |

---

## Appendix C — Existing Async Primitives

File: `very_common.py` (also duplicated in `code_common/call_llm.py`)

```python
def get_async_future(fn, *args, **kwargs):
    """Submit fn(*args, **kwargs) to a thread pool. Returns a Future."""
    afn = make_async(fn, traceback.format_stack())
    return afn(*args, **kwargs)

def sleep_and_get_future_result(future, sleep_time=0.2, timeout=1000):
    """Poll a Future with sleep. Raises TimeoutError after `timeout` seconds."""
    start_time = time.time()
    while not future.done():
        time.sleep(sleep_time)
        if time.time() - start_time > timeout:
            raise TimeoutError(...)
    return future.result()

def wrap_in_future(s):
    """Wrap a value in an already-resolved Future (for uniform interfaces)."""
    future = Future()
    future.set_result(s)
    return future
```

The `HookPipeline` should wrap these — for parallel hooks, launch each via `get_async_future`, then collect results with timeout enforcement (replacing `sleep_and_get_future_result` with the hook's `timeout_ms`).

---

## Appendix D — The `@register_tool` Pattern (Model for `@register_hook`)

File: `code_common/tools.py`, line 353

```python
TOOL_REGISTRY = ToolRegistry()  # Singleton

@register_tool(
    name="web_search",
    description="Search the web for current information",
    parameters={"type": "object", "properties": {...}, "required": [...]},
    category="search",
)
def handle_web_search(args: dict, context: ToolContext) -> ToolCallResult:
    ...
```

The decorator creates a `ToolDefinition` and registers it in the global `TOOL_REGISTRY`. The analogous hook pattern:

```python
HOOK_REGISTRY = HookRegistry()  # Singleton

@register_hook(
    phase=HookPhase.PRE_CONTEXT,
    priority=20,
    timeout_ms=3000,
    async_parallel=True,
)
class PKBContextHook:
    def should_run(self, ctx: HookContext) -> bool:
        return PKB_AVAILABLE and ctx.query_dict.get("checkboxes", {}).get("use_pkb", True)

    def execute(self, ctx: HookContext) -> HookResult:
        ...
```

Key difference: tools are functions, hooks are classes (because they carry config/state). The registry pattern is the same.
