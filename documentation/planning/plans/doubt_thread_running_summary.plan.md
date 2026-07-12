# Doubt Thread Running Summary Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Give each doubt thread a durable, incrementally maintained path-local running summary so follow-up clears don’t dump unbounded full Q&A history and the model keeps direction/focus on long threads.

**Architecture:** Mirror main-chat `running_summary` semantics, but path-local on the doubt chain. After each doubt answer is saved (post-stream), run a cheap SUPERFAST / `conversation_internal_model` incremental summarizer and store the result on that doubt row (`thread_summary_upto_here`). On the next follow-up, pack prompt as: host target message + path tip summary + last **3** raw turns (not full history). Short threads keep full replay (no summarizer). **Legacy threads with no tip summary:** on the first follow-up that actually needs thread memory (`len(history) >= DOUBT_SUMMARY_MIN_TURNS`), make a **blocking (sync) SUPERFAST bootstrap** of the path summary *before* `clear_doubt` generates the answer, so that call already packs `summary + last 3` rather than an empty/missing thread summary. Subsequent turns use non-blocking incremental post-save updates. Manual “Summarize Thread” stays a separate user-facing artefact and must not double as system running summary.

**Tech Stack:** Flask endpoints, SQLite `DoubtsClearing` (users.db), `database/doubts.py` helpers, `Conversation.clear_doubt`, existing `get_async_future` / background call pattern, `CallLLm` + `get_model_override("conversation_internal_model", SUPERFAST_LLM[0])`.

**Status:** IMPLEMENTED (v1 Phase 0 + 1 + 1b + docs). Packing unit tests green. Partial live dogfood: post-save tip summary `ready` on real 2-node path. Task 11 residual: long legacy thread bootstrap + regen dirty still manual.

**Session continuity note:** This plan is written to be fully self-contained for a cold session (no prior chat needed). Prefer the survey below + exact paths over re-tracing from scratch. Repo root: `chatgpt-iterative`. Conda env: `science-reader`. Don't invent alternate architecture without re-checking these files.

**Related prior art:**
- Main chat summary write: `Conversation.persist_current_turn` / `_persist_current_turn_inner` (~4433–4875)
- Doubt clear packing: `Conversation.clear_doubt` (~14658–14891) — **line numbers drift; re-grep `def clear_doubt`**
- History walk: `database/doubts.get_doubt_history` (~432–490)
- Save follow-up answer: `endpoints/doubts.clear_doubt_route` finally → `add_doubt`
- Regen in place: `endpoints/doubts.regenerate_doubt_route` → `update_doubt_answer`
- Manual summarize (separate UX): `POST /summarize_doubt_thread/<doubt_id>` (do not overload)
- Feature docs: `documentation/features/doubt_and_temp_llm/README.md`
- Prior enhancements: `documentation/planning/plans/doubt_system_enhancements.plan.md` (DONE)
- Model overrides: `documentation/features/conversation_model_overrides/README.md`
- Hermes / workspace copy of plan: `.hermes/plans/2026-07-12_202532-doubt_thread_running_summary.md` (keep in sync when editing)

---

## Cold-session background survey (captured facts)

Use this as the briefing packet if past chat is gone.

### Why this feature exists
- Main chat has `memory["running_summary"]`, updated in `persist_current_turn` after each turn. Next turn uses latest summary + recent turns.
- Doubt threads have **no** analogous memory. Follow-ups call `get_doubt_history(parent_doubt_id)` and dump **every** prior Q/A fully into `clear_doubt`'s prompt as `# Previous Doubt History`.
- Temp LLM (sibling feature) *does* truncate (last 6 msgs × 1000 chars) — doubts do not. Long doubt threads bloat context and models lose focus/direction.
- Manual `POST /summarize_doubt_thread/<doubt_id>` creates a **visible** child with `doubt_text="Thread Summary"` using `senior_engineer_summary_prompt` — user artefact, not machine working memory. Do not overload it.

### Doubt system lifetime (end-to-end)
1. User right-clicks a main-chat message card (or uses card menu) → “Ask a Doubt” / “…with context”.
2. UI: `interface/context-menu-manager.js` → `handleAskDoubt(withContext)` → `DoubtManager` modal (`interface/doubt-manager.js`).
3. Submit → `POST /clear_doubt/<conversation_id>/<message_id>` (`endpoints/doubts.py` `clear_doubt_route`).
4. Body (important fields): `doubt_text`, `parent_doubt_id` (follow-up), `with_context`, `selected_text`, `preamble_options`, `tools_enabled`, `display_attachments`, `reward_level`.
5. If `parent_doubt_id` set → `get_doubt_history(parent)` → chronological root→parent chain.
6. `conversation.clear_doubt(message_id, doubt_text, doubt_history, ...)` streams the answer.
7. Stream `finally`: if non-empty accumulated answer → `add_doubt(..., parent_doubt_id=..., with_context=...)` returns new `doubt_id`.
8. Follow-ups store **same host** `message_id` as the root; they are parent-linked nodes, not re-anchored.

### Anchor model: doubt ↔ main message
- Every row has `conversation_id` + `message_id` (host). Host can be **assistant or user**; product usually anchors on assistant answers.
- Host text is **not** snapshotted on the doubt row. Each clear reloads live text via `get_context_around_message(message_id, before=4, after=2)`.
- `with_context=False` (default): only `# Target Message` = that one host message.
- `with_context=True`: main `running_summary` + surrounding messages (target marked `← [TARGET MESSAGE]`).
- Promote-pair path: `POST /move_pair_as_doubt/...` attaches to **preceding assistant** message; user turn becomes `doubt_text` (often `[Promoted from Chat] ...`), assistant turn becomes `doubt_answer`.

### Storage
- DB: `DoubtsClearing` in **users.db** (not conversation json memory), helpers in `database/doubts.py`.
- CREATE / ALTER live in `database/connection.py` (additive ALTER try/except pattern for `child_doubt_id`, `show_hide`, `with_context`, `pinned`, `bookmarked`, `display_attachments` — new columns should match that style ~269–314).
- Existing indexes already cover `parent_doubt_id`, `conversation_id+message_id`, roots — no new index required for summary fields.
- Schema fields today (mental model):
  - `doubt_id` (md5 of content+time+parent), `doubt_text`, `doubt_answer`
  - `parent_doubt_id`, `child_doubt_id` (forward convenience pointer; multi-child still possible via children query)
  - `is_root_doubt`, `with_context`, `show_hide`, `pinned`, `bookmarked`, `display_attachments`, timestamps
- Tree semantics: multiple roots per host message; follow-ups form trees/lists; UI is mostly linear chat per root thread.

### History functions (use these; don’t reimplement walk)
| Helper | Behaviour |
|---|---|
| `get_doubt_history(doubt_id)` | Walk **parent** links to root, reverse → path list (root first) |
| `get_doubt_children(doubt_id)` | Immediate children |
| `get_doubts_for_message(cid, mid)` | Roots for a message + `build_doubt_tree` |
| `add_doubt(...)` | Insert; if parent, updates parent’s `child_doubt_id` |
| `update_doubt_answer(doubt_id, answer)` | Regen in-place |
| `delete_doubt(doubt_id)` | Recursive subtree delete |
| `update_doubt_show_hide` / `_pinned` / `_bookmarked` | Existing UPDATE patterns to copy |

**When adding summary columns:** every SELECT that builds a doubt dict must include the new fields (easy bug: miss one mapper → KeyError or silent absence). Grep: `FROM DoubtsClearing` and `"parent_doubt_id":` dict builders in `database/doubts.py`.

Re-export new helpers from `database/__init__.py` (and dual docs if still maintained):
- `database/external_db.md`
- `documentation/data/external_db/external_db.md`

### `clear_doubt` packing today (rough order)
1. `get_context_around_message(...)`  
2. If `with_context`: append main `# Conversation Summary` from `self.running_summary`  
3. If `doubt_history`: full loop Previous Doubt History (`User asked` / `Assistant answered` **full texts**) including a current-follow-up line (duplicates later User's Doubt section — **improve by not re-emitting current Q in helper**)  
4. Target message only **or** surrounding messages  
5. Selected text optional  
6. Attachments: images → vision; text docs inlined into doubt_text (no `#doc_N` BM25)  
7. LLM: model = `get_model_override("quick_action_model", QUICK_ACTION_LLM)`; tool loop with `DOUBT_DEFAULT_TOOLS` (+ optional Tier1)  
8. Output politics: temp 0.3, max_tokens ~2000 (plain fallback path)

### Models (locked for this feature)
| Use | Override key | Default constant | Default value (as of plan writing) |
|---|---|---|---|
| **Doubt answer stream** | `quick_action_model` | `QUICK_ACTION_LLM` | `anthropic/claude-sonnet-4.6` (`common.py`) |
| **Thread running summary** (this plan) | `conversation_internal_model` | `SUPERFAST_LLM[0]` | `google/gemini-3.1-flash-lite` (`common.py`; prior default was `inception/mercury-2`) |

Resolve with:
```python
self.get_model_override("conversation_internal_model", SUPERFAST_LLM[0])
```
Same family as main `running_summary` / TLDR / memory pad — **do not** use `quick_action_model` for summarizer (cost + latency).

Manual “Summarize Thread” currently uses override with SUPERFAST fallback via conversation (route in `endpoints/doubts.py`) — **leave it alone**.

### Async primitives to reuse
- Prefer existing `get_async_future` (imported via `common` / `very_common`) for post-save schedule — **do not invent ThreadPool / custom daemon plug-ins**.
- Conversation already has executor patterns for `persist_current_turn` and multi-agent work; match local style where possible.
- Fail-open everywhere background work can throw; logging via module `logger` from `getLoggers`.

### Frontend touchpoints (read-only for v1 behaviour)
- `interface/doubt-manager.js`: modal state, `currentMessageId`, `withContext` restore from root, stream render, `parent_doubt_id` on follow-up send, regenerate & summarize buttons.
- No UI required to display system running summary in v1.
- Optional polish later: stream status text if ensure blocks (endpoint can emit status chunks before answer tokens).

### Conventions / AGENTS.md constraints that matter
- Activate `conda activate science-reader` before Python/tests.
- Prefer small patches; follow existing abstractions; when return/dict shape changes, grep all callers.
- Docs live under `documentation/`; feature entry is `documentation/features/doubt_and_temp_llm/README.md`; plans live under `documentation/planning/plans/*.plan.md`.
- Dual-home of some DB docs under `database/*.md` — update if still referenced.
- Do not invent fake implementation status; verify with real tests and manual checklist in Task 11.

### Explicit “do not”
- Do **not** put doubt thread summaries in conversation `memory["running_summary"]`.
- Do **not** create synthetic visible children as system memory (`doubt_text="Thread Summary"` reserved for human action).
- Do **not** block the answer stream on **post-save** incremental summary.
- Do **not** skip the **blocking** ensure on long legacy cold tips (see D3b) unless ensure fails → then truncated fallback.
- Do **not** change temp-LLM history rules in this plan.
- Do **not** offline backfill all historical franken-threads.
- Do **not** assume line numbers in huge files stay stable — re-grep symbols:
  ```bash
  rg -n "def clear_doubt|def get_doubt_history|def add_doubt|def update_doubt_answer|def regenerate_doubt|summarize_doubt_thread" Conversation.py database/doubts.py endpoints/doubts.py
  ```

### Suggested first commands for a cold executor
```bash
conda activate science-reader
cd <repo root>
rg -n "def clear_doubt|Previous Doubt History|get_doubt_history|thread_summary" Conversation.py database/doubts.py endpoints/doubts.py
rg -n "ALTER TABLE DoubtsClearing" database/connection.py
ls documentation/features/doubt_and_temp_llm/
head -120 documentation/planning/plans/doubt_thread_running_summary.plan.md
```

### Constants (locked decisions from product discussion)
| Constant | Value | Notes |
|---|---|---|
| `DOUBT_RECENT_VERBATIM_TURNS` | **3** | was drafted as 2; user locked 3 |
| `DOUBT_SUMMARY_MIN_TURNS` | 2 | full replay under this; no ensure |
| `DOUBT_SUMMARY_MAX_WORDS` | 280 | hard summarizer budget |
| `DOUBT_FULL_REPLAY_CHAR_BUDGET` | 12000 | fallback / bootstrap input soft cap zone |
| `DOUBT_OLDER_TURN_TRUNC_CHARS` | 600 | per older answer in truncated pack |
| Legacy first long follow-up | **blocking bootstrap** | not empty summary |
| Steady post-save | **async incremental** | non-blocking |
| Display summary in UI | no (v1) | |
| Offline backfill | no | progressive via ensure on demand |

### Call graph (target after implementation)

```
POST /clear_doubt
  get_doubt_history(parent) if follow-up
  conversation.clear_doubt(..., users_dir=...)
     optional ensure_path_summary_sync(tip)  # blocking cold path only
     pack: host + summary? + last 3
     stream answer (quick_action_model)
  add_doubt(...)
  schedule_doubt_thread_summary(new_tip)  # async incremental

POST /regenerate_doubt
  clear_doubt(ancestors as history)
  update_doubt_answer
  mark_descendant_summaries_dirty
  schedule/recompute tip summary
```

### Knowledge already settled in plan decisions (don’t re-open casually)
- Path-local columns on each node (D1), not root-only table.
- Dual write timing (D2): async steady-state + sync ensure cold path.
- K=3 verbatim (D3).
- Sync bootstrap on legacy cold path (D3b).
- `conversation_internal_model` for summary (D4), default mercury-2.
- Dirty descendants on regen (D5).
- Manual Thread Summary stays separate (D7).

---

## Requirements & Goals

### Product goals
1. Long doubt threads stop degrading answer quality / topic drift due to full-history replay bloat.
2. Summaries stay path-local (root→current tip); sibling branches do not overwrite each other.
3. User never waits on the summary job for the *just-completed* answer (post-generate after stream remains the steady-state path).
4. **Legacy first follow-up only:** if the path already has enough turns and no ready tip summary, **block once** on a cheap SUPERFAST bootstrap so that first answer after the feature ships already sees summary+last-3 (not empty summary / full-dump fallback as the happy path).
5. Failures / timeouts of that one-shot bootstrap fall back to truncated full history so the user still gets an answer.
6. Steady-state (and fast successive follow-ups after a ready tip exists) stay summary-driven; race if post-save job still pending uses nearest ready ancestor or truncation fallback.
7. Manual “Thread Summary” child remains a user-facing learning dump and is **not** used as automatic system memory.

### Non-goals (YAGNI for v1)
- Structured scratchpad schema (`terms[]`, `claims[]`) — later optional
- Cross-thread / whole-message synopsis of all root doubts — separate feature
- Frontend display of the system running summary (optional small debug badge later; not required)
- Changing temp-LLM history truncation rules
- Migrating existing long threads eagerly offline

### Success criteria
- After turn 3+ on a linear chain (and once a tip summary is ready), next follow-up prompt contains `# Doubt Thread Running Summary` and only last **3** full Q&As.
- Short threads (≤2 turns or under char threshold) still use full history; no extra LLM call.
- **Existing pre-feature threads:** first follow-up that needs memory (`len(history) >= MIN_TURNS`, no ready summary) does a **sync bootstrap** before answering, then packs summary+3 for that same call. No offline backfill job.
- Regen recomputes summary for that node (and marks descendants dirty or recomputes tip on next use).
- Delete of a tip loses that tip’s summary only; parent tip remains valid.
- Failures in summarizer never fail the user-visible stream / save path (bootstrap fail → truncated fallback; post-save fail → log + next turn retry/bootstrap rules).

---

## Current behaviour (baseline)

| Piece | Today |
|---|---|
| Storage | `DoubtsClearing` rows: Q/A + `parent_doubt_id` / `child_doubt_id` tree |
| Follow-up context | Full `get_doubt_history(parent)` inlined as Previous Doubt History |
| Truncation | None on doubt chain (temp LLM *does* last-6 / 1000-char) |
| Main summary | Injected only when `with_context=True` |
| Manual summarize | Creates visible child with `doubt_text="Thread Summary"` |

Anchor host message: always `message_id` on the row; full text reloaded each clear via `get_context_around_message`.

---

## Design Decisions (locked)

### D1. Storage = columns on each doubt row (path tip carries summary)

Add to `DoubtsClearing`:

| Column | Type | Meaning |
|---|---|---|
| `thread_summary_upto_here` | TEXT NULL | Compact running summary covering the path root→this node **inclusive** |
| `summary_status` | TEXT NULL | `ready` \| `pending` \| `dirty` \| `error` \| NULL(never attempted) |
| `summary_updated_at` | TEXT NULL | ISO timestamp |

**Why not a new root-only table?** Roots can branch; path-local summaries on tips are branch-safe and need no “active leaf” keying. Matches linear chat UI (`child_doubt_id`) while surviving multi-child trees.

**Why not a child “Thread Summary” message?** Pollutes UI and `get_doubt_history` unless filtered forever; mixes human artefact with machine memory.

### D2. Write timing = dual-path (steady-state async + rare sync bootstrap)

**Steady-state (new turns on paths that already have memory):**  
After successful `add_doubt` / `update_doubt_answer` with non-empty answer:
1. Optionally mark `summary_status='pending'` on that doubt_id.
2. Fire **background** job that incremental-updates tip summary from parent summary + new Q/A.
3. Never block the NDJSON answer stream on this job.

**Cold path (legacy / missing / dirty tip when next follow-up is requested):**  
Inside the clear/regenerate **request**, **before** building the doubt answer prompt and before streaming the answer:
1. If `select_path_summary(history)` is None/empty **and** `len(history) >= DOUBT_SUMMARY_MIN_TURNS`:
2. Call `ensure_path_summary_sync(tip_id, history)` (blocking SUPERFAST bootstrap).
3. Re-read / use returned summary text in packing.
4. Only then start the main doubt-answer LLM stream.

Do **not** use blocking bootstrap when history is short (full replay is fine and faster than an extra LLM call).  
Do **not** block steady-state turns that already have a ready tip summary.

### D3. Read / packing contract in `clear_doubt`

When building prompt for a follow-up (`doubt_history` non-empty):

```
# Conversation Summary              [only if with_context]
# Doubt Thread Running Summary      [if available]
# Recent Doubt Turns (verbatim)     [last K pairs]
# Target Message / Context Msgs     [existing with_context rules]
# Current Follow-up Question
```

Packing rules (v1 constants, named constants at top of helper module or hardcode near clear_doubt):

| Constant | v1 value | Purpose |
|---|---|---|
| `DOUBT_SUMMARY_MIN_TURNS` | 2 | History length at/below → full replay, skip summary generate too |
| `DOUBT_RECENT_VERBATIM_TURNS` | **3** | Always include last K raw Q&As (higher fidelity than the original draft of 2) |
| `DOUBT_SUMMARY_MAX_WORDS` | 280 | Hard prompt budget for stored summary |
| `DOUBT_FULL_REPLAY_CHAR_BUDGET` | 12000 | If no summary and history chars exceed this, apply truncation pack on older turns |
| `DOUBT_OLDER_TURN_TRUNC_CHARS` | 600 | Truncation pack per older answer when fallback |

Resolution of summary for follow-up of parent tip P (`doubt_history` = root→P):
1. Prefer `P.thread_summary_upto_here` if `summary_status == 'ready'` and text non-empty.
2. Else walk ancestors in `doubt_history` reverse; use nearest ready summary (covers older prefix).
3. Else if `len(doubt_history) >= DOUBT_SUMMARY_MIN_TURNS` (**legacy / dirty / never-summarized tip**):  
   **blocking** `ensure_path_summary_sync(tip=P, history=doubt_history)` → SUPERFAST bootstrap from full path (truncation-aware input), write ready summary onto P, then use it.  
   - Hard time budget: aim < ~3–8s; on timeout/exception → step 4.  
   - Status transitions: set `pending` at start of sync call (optional), then `ready` or `error`.
4. Else fallback (short path **or** bootstrap failed): full history → if over budget, truncation pack (Phase 0 style) without LLM.
5. Always include last **3** raw turns after the summary when a summary is used (**include raw last K always** for precision; slight overlap is fine).

Special nodes: skip rows where `doubt_text.strip() == "Thread Summary"` from “recent verbatim” contribution as normal Q&A if it would dominate. Better long-term: don’t include system summaries in recent turns at all.

### D3b. Existing / pre-migration threads — **sync bootstrap on first needed follow-up**

Locked behaviour for threads created before this feature (and any path that still has no ready tip summary):

1. **Schema only** — ALTER adds nullable columns; existing rows stay `NULL` summary / status. No offline rewrite of past Q&As; no cron warm job in v1.

2. **Open old thread, ask a follow-up whose history already has ≥ `DOUBT_SUMMARY_MIN_TURNS` nodes**  
   - `get_doubt_history(parent)` returns the full parent chain as today.  
   - Packer / clear path finds **no** ready summary on tip or ancestors that are usable for the whole path → run **`ensure_path_summary_sync` on the tip before answer generation**.  
   - Bootstrap input: `pack_history_for_bootstrap(history)` (last 3 full + truncated older on long chains).  
   - Write `thread_summary_upto_here` + `summary_status='ready'` on the **current tip** (the parent of the new question).  
   - Then pack this **same** request as: `# Doubt Thread Running Summary` + last 3 raw turns + host target + current user doubt.  
   - User pays one SUPERFAST latency spike **only this first time** (and only when path is long enough to need it).  
   - Stream status line may say `"Building thread memory..."` then `"Clearing doubt..."` (optional UX polish in endpoint).

3. **Short old paths** (`len(history) < MIN_TURNS`, e.g. only root)  
   - No blocking bootstrap; full replay of the short history (same as new short threads).

4. **After the follow-up’s answer is saved**  
   - `schedule_doubt_thread_summary(new_tip)` runs **async** as usual (incremental: parent tip summary + new Q/A).  
   - Steady-state from here is non-blocking.

5. **Subsequent follow-ups** on the same path  
   - Tip has ready summary → pack summary + last 3; **no** blocking.  
   - If post-save job raced and tip not ready yet: prefer nearest ready ancestor; if none and path long, **may** block again (same ensure rule) — rare.

6. **Dirty tips after regen of an ancestor / tip**  
   - Prefer recompute rules from D5. If tip is `dirty`/`error` and no ready ancestor covers the path usefully: treat as “needs ensure” → **sync recompute** on next follow-up using same gate (`len >= MIN_TURNS`), not silent empty summary.

7. **Stale multi-branch old trees**  
   - Only the path the user continues gets a bootstrap / summary.  
   - Sibling branches stay null until continued (each first long follow-up blocks once on that path).

8. **Read-only reopen** (UI only, no new ask)  
   - No summary generation. Zero change for passive viewing.

9. **Optional later:** background warm of long tips without user wait — out of v1.

**Net:** first legacy follow-up that needs memory is summary-first (blocking cheap model), not empty-summary-with-full-dump. After that one hitch, behaviour matches new threads.

**Latency note:** bootstrap uses `conversation_internal_model` / SUPERFAST, truncation-capped input — not the full doubt-answer model. Accept a one-time delay for correctness of focus; do not block the *answer* token stream beyond this pre-step.

### D4. Model / prompt

- Model: `conversation.get_model_override("conversation_internal_model", SUPERFAST_LLM[0])` — same class of model as main internal summary / TLDR, not `quick_action_model` (which answers doubts).
- Temperature low (~0.2), `max_tokens` ~500–700, non-streaming OK in background.
- Prompt goals (system-facing, short bullets preferred):
  1. Thread topic / user goal
  2. Key definitions & corrections established
  3. Resolved conclusions
  4. Open confusions / pending questions
  5. Hard constraints / caveats the next answer must respect
- Instruct: update prior summary; drop obsolete; keep under N words; no fluff; no markdown headings higher than `####` not required — plain bullets fine.
- Do **not** re-explain the host message; host is re-injected each turn.

### D5. Invalidation

| Event | Action |
|---|---|
| New child saved | Compute summary for **new child only** (uses parent ready summary if any) |
| Regen answer (`update_doubt_answer`) | Recompute summary for **that** doubt_id; set all **descendants** `summary_status='dirty'` (their summaries assume old answer) |
| Delete subtree | Rows gone; no cascade needed beyond existing recursive delete |
| Parent summary used while child dirty | On next follow-up that needs child as tip, recompute lazily if dirty/pending age |

v1 minimum: recompute target tip on regen; mark descendants dirty; recompute dirty tip lazily on next read if that tip is the parent of a new question (or eagerly recompute only the regenerated node).

### D6. Bootstrap / skip policy

- Root first turn: no thread summary needed (no history). Optionally still write a one-paragraph “seed” after root if answer is long — **skip in v1** (write only when `parent_doubt_id is not None` **or** history length after save ≥ 2).
- After save of node where `path_length >= DOUBT_SUMMARY_MIN_TURNS`: schedule summary.
- If parent summary ready: incremental update (cheap).
- If parent summary None、path long: generate from last few full turns + truncated older (still one SUPERFAST call).

### D7. Relationship to existing manual summarize

`POST /summarize_doubt_thread/<doubt_id>` stays. It:
- Produces a **visible** child with `doubt_text="Thread Summary"`
- Uses `senior_engineer_summary_prompt` (concepts / care / applicability)

That output is for humans. Machine packing **may ignore** such children when building “recent turns” (filter by doubt_text). Do not write automatic summary into a synthetic child.

---

## Prompt packing (exact target shape)

### Follow-up without with_context, with ready summary

```text
# Doubt Thread Running Summary

{thread_summary_upto_here from parent tip}

# Recent Doubt Turns

**Previous Doubt {n-2}:**
User asked: ...
Assistant answered: ...

**Previous Doubt {n-1}:**
User asked: ...
Assistant answered: ...

**Previous Doubt {n}:**
User asked: ...
Assistant answered: ...

# Target Message

**Assistant** ← **[TARGET MESSAGE]**:
{target_message text}
```

(Selected text and attachments keep existing placement.)

### Short history (≤ MIN_TURNS) or no summary

Keep current full “Previous Doubt History” loop. If total chars > `DOUBT_FULL_REPLAY_CHAR_BUDGET`, compress older turns only (keep last K full).

---

## Incremental summary job algorithm

```text
function update_thread_summary(doubt_id):
    rec = get_doubt(doubt_id)
    if not rec: return

    history = get_doubt_history(doubt_id)  # root..rec inclusive
    if len(history) < DOUBT_SUMMARY_MIN_TURNS:
        clear or leave summary null; status ready/null
        return

    parent = history[-2] if len(history) >= 2 else None
    prev_summary = parent.thread_summary_upto_here if parent and parent.summary_status == 'ready' else ""

    # Build generation input
    if prev_summary:
        payload = prev_summary + latest Q/A (history[-1])
    else:
        payload = pack_history_for_bootstrap(history)  # truncation-aware

    text = llm(internal_model, DOUBT_THREAD_SUMMARY_PROMPT, payload)
    text = trim_words(text, DOUBT_SUMMARY_MAX_WORDS)
    update_doubt_thread_summary(doubt_id, text, status='ready')
```

Fail-open: catch all, set `summary_status='error'`, log; packing falls back to truncated full history.

---

## Schema & migration

### CREATE TABLE (new DBs)

Extend `sql_create_doubts_clearing_table` in `database/connection.py` with:

```sql
thread_summary_upto_here text,
summary_status text,
summary_updated_at text
```

Note: existing CREATE already aged; live DBs use additive ALTER pattern — must do both CREATE (for greenfield if table recreated is rare) **and** ALTER like sibling columns.

### Additive ALTER (existing DBs)

In same place as other DoubtsClearing ALTERs (`database/connection.py` ~269–314):

```python
try:
    cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN thread_summary_upto_here text")
except Exception:
    pass
try:
    cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN summary_status text")
except Exception:
    pass
try:
    cur.execute("ALTER TABLE DoubtsClearing ADD COLUMN summary_updated_at text")
except Exception:
    pass
```

No backfill required.

---

## Files to change

| File | Change |
|---|---|
| `database/connection.py` | CREATE fields (if practical) + ALTER migrations for 3 columns |
| `database/doubts.py` | SELECT fields in all doubt mappers; `update_doubt_thread_summary`; `mark_descendant_summaries_dirty`; optionally extend `update_doubt_answer` to dirty/regen hooks |
| `database/__init__.py` | Export new helpers |
| `database/external_db.md` / `documentation/data/external_db/external_db.md` | Document columns + helpers |
| `Conversation.py` | Extract packing helper; change `clear_doubt` history packing; add `update_doubt_thread_summary_async` method (or free function in a small module) that runs the LLM write |
| `endpoints/doubts.py` | After `add_doubt` success in clear path; after `update_doubt_answer` on regen; schedule summary job with conversation keys/users_dir |
| `prompts.py` | Add `doubt_thread_running_summary_prompt` (+ short system blurb) |
| `documentation/features/doubt_and_temp_llm/README.md` | Document running summary behaviour, packing, lifecycle |
| Tests (new) | Unit tests for packer + thresholds; optional DB helper tests if free of full app stack |

**UI:** none required for v1. Optional later: tiny “summary ready” indicator.

---

## Step-by-step implementation tasks

### Task 1: Schema migration

**Objective:** Add three nullable columns to `DoubtsClearing` for new and existing DBs.

**Files:**
- Modify: `database/connection.py` (CREATE block ~119–135 and ALTER section ~269–314)
- Docs note: comment only in connection is enough for now; full docs in Task 10

**Steps:**
1. Add columns to ALTER section using the established try/except pattern.
2. Optionally add columns to CREATE TABLE definition for greenfield consistency (if table already exists CREATE is no-op; ALTER still needed).
3. Manually sanity: open users.db after server start / `create_tables` path and `PRAGMA table_info(DoubtsClearing)` includes the three columns.

**Verify:** Server init / import path that runs migrations does not throw; second start is idempotent.

**Commit:** `feat(doubts): add thread_summary columns to DoubtsClearing`

---

### Task 2: DB helpers — read/write summary fields

**Objective:** Helpers to update summary + include fields in all SELECT dicts.

**Files:**
- Modify: `database/doubts.py`
- Modify: `database/__init__.py` exports

**Functions to add:**

```python
def update_doubt_thread_summary(
    *,
    doubt_id: str,
    thread_summary: str | None,
    summary_status: str = "ready",
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """Write thread_summary_upto_here + summary_status + summary_updated_at."""
```

```python
def mark_descendant_summaries_dirty(
    *,
    doubt_id: str,
    users_dir: str | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """
    BFS/DFS children via parent_doubt_id / get_doubt_children.
    Set summary_status='dirty' for all descendants (not the node itself unless requested).
    Returns count updated.
    """
```

Also update every SELECT that builds doubt dicts (`get_doubt`, `get_doubt_history`, `get_doubt_children`, `get_doubts_for_message` tree builders, `get_all_doubts_for_user`, etc.) to include:

```python
"thread_summary_upto_here": row[...],
"summary_status": row[...] or None,
"summary_updated_at": row[...] or None,
```

Treat missing columns defensively only if migration not guaranteed; prefer migration-first, then direct indices with updated column lists (match style of earlier `display_attachments` additions).

**Optional:**

```python
def set_summary_status(*, doubt_id, summary_status, users_dir=None, logger=None) -> bool
```

**Verify:** fresh insert still works; get_doubt returns new keys (None).

**Commit:** `feat(doubts): helpers for path-local thread_summary storage`

---

### Task 3: Prompt constants + packing pure functions

**Objective:** Pure helpers that turn history rows into prior-context sections — unit-testable without LLM/DB.

**Preferred location:** small module `code_common/doubt_context.py` (keeps Conversation.py slimmer) **or** private methods on Conversation. Prefer `code_common/doubt_context.py` for tests.

**Files:**
- Create: `code_common/doubt_context.py`
- Create: `tests/test_doubt_context_packing.py` (or nearest existing equivalent test area)

**API:**

```python
DOUBT_SUMMARY_MIN_TURNS = 2
DOUBT_RECENT_VERBATIM_TURNS = 3  # locked: last 3 raw Q&As always
DOUBT_SUMMARY_MAX_WORDS = 280
DOUBT_FULL_REPLAY_CHAR_BUDGET = 12000
DOUBT_OLDER_TURN_TRUNC_CHARS = 600
THREAD_SUMMARY_DOUBT_TEXT = "Thread Summary"  # filter user-facing summarize nodes

def is_system_thread_summary_node(doubt: dict) -> bool:
    return (doubt.get("doubt_text") or "").strip() == THREAD_SUMMARY_DOUBT_TEXT

def select_path_summary(history: list[dict]) -> str | None:
    """Walk history reverse; first ready non-empty thread_summary_upto_here."""

def format_recent_turns(history: list[dict], k: int = DOUBT_RECENT_VERBATIM_TURNS) -> str:
    """Last k non-system nodes as Previous Doubt N blocks (default K=3)."""

def format_full_or_truncated_history(history: list[dict]) -> str:
    """Full dump, or older-turn truncation if over char budget.
    Used for: short threads, bootstrap-failure fallback, or paths that intentionally skip ensure."""

def pack_history_for_bootstrap(history: list[dict]) -> str:
    """Input for first summary on a path (incl. long pre-feature chains): recent full + truncated older."""

def build_doubt_history_context_section(history: list[dict], current_doubt_text: str = "") -> str:
    """
    Main entry used by clear_doubt (after optional ensure_path_summary_sync):
    - if summary available: summary section + last 3 raw turns
    - else: full/truncated history (short-thread or ensure failed)
    Do not re-emit the current follow-up question (shown later as User's Doubt).
    """

def should_generate_summary_for_path(history_len_incl_new: int) -> bool:
    return history_len_incl_new >= DOUBT_SUMMARY_MIN_TURNS

def needs_sync_bootstrap(history: list[dict]) -> bool:
    """True when path is long enough and select_path_summary(history) is empty."""
```

**TDD:**
1. Write tests for empty history, 1 turn, 4 turns with summary (recent=last 3), 4 without after ensure failed (fallback), system Thread Summary filter, budget truncation, bootstrap pack for long legacy-like histories, `needs_sync_bootstrap` true/false cases.
2. Implement until green.

**Verify:** `conda activate science-reader && python -m pytest tests/test_doubt_context_packing.py -v`

**Commit:** `feat(doubts): pure packing helpers for thread running summary`

---

### Task 4: Summary prompt in `prompts.py`

**Objective:** Dedicated incremental summary prompt (not `senior_engineer_summary_prompt`).

**Files:**
- Modify: `prompts.py`

**Add** (wording may be refined, structure fixed):

```python
doubt_thread_running_summary_system = """You maintain a compact running summary of a doubt/Q&A thread.
Write machine-usable memory for the next assistant turn. Prefer tight bullets.
Hard limit: <= 280 words. No preamble. No closing flourish."""

doubt_thread_running_summary_prompt = """Update the doubt-thread running summary.

Prior running summary (may be empty):
'''{prior_summary}'''

New exchange to fold in:
User asked:
'''{doubt_text}'''

Assistant answered:
'''{doubt_answer}'''

Write an updated running summary that captures:
1) Thread goal / what the user is trying to understand
2) Definitions and corrections that must stick
3) Conclusions already established
4) Open questions / remaining confusion
5) Caveats the next answer must respect

Rules:
- Merge into prior summary; drop obsolete or wrong info
- Do NOT restate the host main-chat message
- Do NOT invent facts not present in prior summary or this exchange
- Prefer bullets; keep <= 280 words
- Output ONLY the summary text
"""
```

Bootstrap variant (no prior): same prompt with `prior_summary = "(none)"` and optional bootstrap_history block; can reuse one template with `{extra_context}`.

**Commit:** `feat(doubts): add doubt thread running summary prompt`

---

### Task 5: Background summarizer on Conversation (or thin orchestrator)

**Objective:** One method that loads path, calls LLM, writes DB; fail-open.

**Files:**
- Modify: `Conversation.py` (or `code_common/doubt_context.py` + thin Conversation wrapper for keys/model)

**Suggested API:**

```python
def ensure_path_summary_sync(
    self,
    *,
    doubt_id: str,
    users_dir: str,
    history: list[dict] | None = None,
) -> str | None:
    """
    Blocking bootstrap/recompute for tip `doubt_id`.
    Returns summary text if ready after this call, else None (caller falls back).
    Used on first long legacy follow-up and dirty-tip follow-ups.
    """

def schedule_doubt_thread_summary(
    self,
    *,
    doubt_id: str,
    users_dir: str,
    parent_doubt_id: str | None = None,
) -> None:
    """Fire-and-forget incremental update after a new answer save; never raise to caller."""

def _update_doubt_thread_summary_sync(
    self,
    *,
    doubt_id: str,
    users_dir: str,
    history: list[dict] | None = None,
    mode: str = "auto",  # "bootstrap" | "incremental" | "auto"
) -> str | None:
    """Shared worker: DB + LLM + update_doubt_thread_summary. Used by ensure (blocking) and schedule (bg)."""
```

Implementation notes:
- `ensure_path_summary_sync` and background schedule **share** `_update_doubt_thread_summary_sync` (no duplicated prompt logic).
- Background: `get_async_future(self._update_doubt_thread_summary_sync, ...)` — **do not invent a new thread system**.
- Resolve model via `self.get_model_override("conversation_internal_model", SUPERFAST_LLM[0])`.
- Bootstrap mode: `pack_history_for_bootstrap(history)` + prior_summary empty/"(none)".
- Incremental mode: parent ready summary + latest Q/A.
- Truncate very long answers in summarizer input (first 4–6k chars).
- Fail-open for **both**: exceptions → status `error`, return None; answer path continues with truncation fallback.
- **Gate:** if `len(history) < DOUBT_SUMMARY_MIN_TURNS`, ensure returns None immediately without LLM.

**When ensure is invoked:** from `clear_doubt` (and regen) after `doubt_history` is known / loaded, **before** `build_doubt_history_context_section`. Endpoint may yield a status chunk first if streaming has already opened; preferably complete ensure before first answer token.

**Commitment rule for post-save path:** never await schedule from inside the token stream loop; only after answer persisted.

**Commit:** `feat(doubts): background incremental thread summary updater`

---

### Task 6: Wire packing + sync ensure into `Conversation.clear_doubt`

**Objective:** Before introducing the main answer LLM, optionally bootstrap tip summary; then pack history via helper (summary+3 when ready).

**Files:**
- Modify: `Conversation.py` ~14699–14708 (history block)
- May need `users_dir` / callers: `clear_doubt` today does not take `users_dir`; either pass it in (add optional kwarg from endpoint) or resolve differently. **Decision:** add optional `users_dir=None` to `clear_doubt` / regen path so ensure can write DB; endpoint already has `state.users_dir`.

**Flow:**

```python
if doubt_history and len(doubt_history) > 0:
    from code_common.doubt_context import (
        build_doubt_history_context_section,
        select_path_summary,
        should_generate_summary_for_path,
    )
    # Cold / legacy / dirty: blocking bootstrap so this call is not summary-empty
    if (
        users_dir
        and should_generate_summary_for_path(len(doubt_history))
        and not select_path_summary(doubt_history)
    ):
        tip_id = doubt_history[-1]["doubt_id"]
        new_sum = self.ensure_path_summary_sync(
            doubt_id=tip_id,
            users_dir=users_dir,
            history=doubt_history,
        )
        if new_sum:
            # keep packer in sync without re-query
            doubt_history[-1]["thread_summary_upto_here"] = new_sum
            doubt_history[-1]["summary_status"] = "ready"

    context_text += build_doubt_history_context_section(history=doubt_history)
```

Same ensure gate for **regenerate** (uses ancestor history + may recompute answer that later dirties descendants).

**Verify:**  
- Fresh short root: no ensure call.  
- Old chain with ≥2 nodes, null summaries: ensure runs once; prompt includes summary section before answer tokens.  
- Tip already ready: no ensure call.

**Commit:** `feat(doubts): sync bootstrap + pack clear_doubt with thread running summary`

---

### Task 7: Pass `users_dir`, schedule after save, optional status chunk

**Objective:** Endpoint supplies `users_dir` into `clear_doubt`; after `add_doubt`, async schedule for **new** tip; optionally emit status during bootstrap.

**Files:**
- Modify: `endpoints/doubts.py` `clear_doubt_route` and `regenerate_doubt_route`

**clear_doubt_route:**
1. Pass `users_dir=state.users_dir` into `conversation.clear_doubt(...)`.
2. Optional: first streamed status `"Preparing thread memory..."` is already generic (`"Analyzing message..."`); ensure happens inside generator so status remains honest — prefer performing ensure at start of generator before answer tokens (already natural if inside `clear_doubt` beginning of history prep).
3. After successful `add_doubt`, schedule async for **new** `doubt_id` (incremental; parent tip now has ready legacy summary if bootstrap ran).

```python
if doubt_id and (doubt_text or "").strip() != "Thread Summary":
    try:
        conversation.schedule_doubt_thread_summary(
            doubt_id=doubt_id,
            users_dir=state.users_dir,
            parent_doubt_id=parent_doubt_id,
        )
    except Exception as sched_err:
        logger.warning("Doubt summary schedule failed for %s: %s", doubt_id, sched_err)
```

**regenerate:** after `update_doubt_answer` + dirty descendants, either `ensure` in regen clear path already handled dirty, and/or `schedule` the regenerated tip.

Skip schedule when `doubt_text == "Thread Summary"`.

**Commit:** `feat(doubts): wire users_dir + post-save schedule for thread summary`

---

### Task 8: Regen invalidation + recompute

**Objective:** After `update_doubt_answer`, recompute that node and dirty descendants.

**Files:**
- Modify: `endpoints/doubts.py` `regenerate_doubt_route` finally (~701–708)
- May use `mark_descendant_summaries_dirty`

```python
if accumulated.strip():
    update_doubt_answer(...)
    try:
        mark_descendant_summaries_dirty(doubt_id=doubt_id, users_dir=state.users_dir, logger=logger)
        conversation.schedule_doubt_thread_summary(
            doubt_id=doubt_id,
            users_dir=state.users_dir,
        )
    except Exception as e:
        logger.warning(...)
```

Rede: child summaries that depended on old answer are dirty until those tips are regenerated or re-summarised on next schedule when they’re answered again. **Next follow-up off a dirty tip** should not use dirty summary: `select_path_summary` only accepts `summary_status == 'ready'`. Walk up to nearest ready ancestor; plus last K raw turns (which include the regenerated answer if it’s in last K). Acceptable.

**Commit:** `feat(doubts): recompute thread summary on regenerate`

---

### Task 9: Root/auto-doubt optional seed (explicitly out of v1)

Document as Phase 2. Do not implement seed summary on first auto-doubt in v1.

---

### Task 10: Documentation

**Objective:** Update feature docs so future agents know the memory model.

**Files:**
- Modify: `documentation/features/doubt_and_temp_llm/README.md`
  - Context building section: summary packing + thresholds
  - Storage schema table: new columns
  - Lifecycle: post-answer summary job
  - Difference vs manual Summarize Thread
- Modify: `documentation/data/external_db/external_db.md` and `database/external_db.md` (keep both dual-homed docs in sync if both still maintained)
- One line in `documentation/README.md` feature blurb if it’s the summary index line for doubt feature (only if already mentions doubts — append memory note if one-line summary exists)

Include motivation paragraph: full-history replay causes focus loss; path-local incremental summary mirrors main chat.

**Commit:** `docs(doubts): document doubt thread running summary`

---

### Task 11: Manual / integration verification checklist

**Environment:** `conda activate science-reader`, run server `./run_server.sh` or `python server.py` per project norms.

**Cases:**

1. **New root doubt** on assistant message  
   - Answer streams & saves  
   - No summary required; `thread_summary_upto_here` may stay null  
   - Follow-up #1: history length 1 → full replay of 1 turn

2. **Second follow-up** (path length becomes 2 after save of follow-up #1? After first follow-up save path has root+child =2)  
   - After first follow-up save, schedule may run (MIN_TURNS=2)  
   - Second follow-up uses ready summary if job finished; else truncated/full fallback  
   - Ready path packs summary + up to last **3** raw turns

3. **Long answers on old turns / pre-existing long thread**  
   - Open a pre-feature thread with many Q&As, no summaries in columns  
   - First follow-up with `len(history) >= MIN_TURNS`: **blocking** bootstrap runs first; answer packing includes summary + last 3 (not empty-summary full dump)  
   - After answer save: async incremental on new tip  
   - Second follow-up: no blocking; uses ready summary + last 3; lower latency than first post-ship follow-up

4. **with_context=True**  
   - Main running_summary + nearby msgs still present; thread summary also present; no double bug

5. **Regen mid-thread**  
   - Answer replaced; that node summary recomputed; children dirty; follow-up off regenerated tip still coherent

6. **Delete tip**  
   - Parent remains; follow-up from earlier parent uses parent summary

7. **Manual Summarize Thread**  
   - Still works as visible child  
   - Does not break packing (system node filtered)

8. **Failure injection** (optional)  
   - Force summarizer exception; answer still saved; next turn falls back gracefully

9. **Regression:** attachments, selected_text, tools toggle, propose_answer_edit still work on clear_doubt path

---

## Exact integration snippets (reference)

### Packing call site (Conversation.clear_doubt)

```python
if doubt_history and len(doubt_history) > 0:
    from code_common.doubt_context import build_doubt_history_context_section
    context_text += build_doubt_history_context_section(
        history=doubt_history,
        # current question already shown later as User's Doubt
    )
```

### Schedule call site (endpoints/doubts.py)

```python
if doubt_id and (doubt_text or "").strip() != "Thread Summary":
    try:
        conversation.schedule_doubt_thread_summary(
            doubt_id=doubt_id,
            users_dir=state.users_dir,
            parent_doubt_id=parent_doubt_id,
        )
    except Exception as sched_err:
        logger.warning(
            "Doubt summary schedule failed for %s: %s", doubt_id, sched_err
        )
```

---

## Testing strategy

| Layer | What |
|---|---|
| Unit | packing helpers thresholds, filter Thread Summary, char budget |
| Unit/DB | update_doubt_thread_summary roundtrip if easy with temp sqlite |
| Manual | checklist Task 11 |
| Non-goals for v1 | full e2e LLM quality fixture |

Run:
```bash
conda activate science-reader
python -m pytest tests/test_doubt_context_packing.py -v
```

---

## Rollout phases

| Phase | Contents | Ship bar |
|---|---|---|
| **0** | Pure packing fallback truncation only (no columns / no LLM) | Immediate bloat relief — **can land inside Task 3+6 before background job** |
| **1** | Columns + schedule + packing prefer ready summary | Full goal |
| **1b** | Regen dirty + recompute | Correctness under edits |
| **2** (later) | Lazy sync refresh when dirty & user waiting; structured scratchpad; optional UI badge; seed summary for long single roots; exclude summary fields from oversize API payloads if needed |

Implementers may merge Phase 0 packing first in same PR as Phase 1 if they keep fallback paths.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Summary drifts / omits a key caveat | Always include last 3 raw turns |
| One-time bootstrap latency on legacy first follow-up | Only when path ≥ MIN_TURNS and no ready summary; SUPERFAST + truncated bootstrap input; status line honesty; subsequent turns free |
| Double bootstrap under concurrent double-submit | `summary_status=pending` + short-circuit if tip already pending/ready mid-flight; soft accept duplicate write |
| Steady-state latency regression | Never block when tip summary already `ready` |
| Double latency if someone awaits post-save future | Never await schedule in request path after answer |
| Branching overwrites | Path tip storage, no global root singleton |
| Race: follow-up before **post-save** summary ready | Nearest ready ancestor; if none and long path, ensure may block again (acceptable, rare) |
| Huge answers explode summarizer cost | Truncate answer input to summarizer |
| Column SELECTs partially updated | Grep all `FROM DoubtsClearing` / dict builders in `database/doubts.py` in one task |
| Duplicate current-question in prompt | Clean helper (no current-follow-up line) |
| Manual Thread Summary pollutes recent turns | Filter known text; later `kind` column if needed |
| SQLite write contention | Same as existing doubt writes; short UPDATE; fail-open |
| Background thread missing keys | Capture from conversation already `attach_keys`'d |

---

## Open questions (defaults locked if unanswered)

1. **MIN_TURNS = 2 vs 3?** Default **2** (summarize as soon as a true follow-up exists).  
2. **`DOUBT_RECENT_VERBATIM_TURNS`?** Locked **3** (user preference; more local fidelity than 2).  
3. **Should root-only long answers get a seed summary?** Default **no** in v1.  
4. **Show summary in UI?** Default **no**.  
5. **Separate `kind` column for system nodes?** Default **no** — string match `"Thread Summary"` enough for now.  
6. **Word limit 280?** Align with tight working memory; tune after dogfood.  
7. **Eager offline backfill of all existing threads?** Default **no**.  
8. **Empty summary on first legacy follow-up?** Default **no** — **blocking** SUPERFAST bootstrap before that answer when `len(history) >= MIN_TURNS` and no ready tip summary (D3b).

---

## Out-of-scope reminders

- Do not change temp LLM `_format_temp_history`.
- Do not use doubt answer `max_tokens` as a history budget (output-only).
- Do not store summary in conversation `memory["running_summary"]` (wrong scope).
- Do not block clear_doubt stream on summarizer.

---

## Implementation order (recommended)

1. Task 3 packing pure helpers + tests (**Phase 0 usable alone**)  
2. Task 6 wire packing (fallback path live)  
3. Task 1 schema  
4. Task 2 DB helpers  
5. Task 4 prompts  
6. Task 5 summarizer  
7. Task 7 schedule on clear  
8. Task 8 regen  
9. Task 10 docs  
10. Task 11 verify  

Estimated implementation size: medium (1 focused session for Phase 0 packing; +1 session for schema/LLM/schedule/regen/docs).

---

## Acceptance checklist (definition of done)

- [x] New columns present on `DoubtsClearing` after app start  
- [x] Follow-up packing uses ready path summary when available (code + packer sim)  
- [x] Ready path always keeps last **3** raw turns (not 2)  
- [x] Full history no longer always injected for long threads with ready summary  
- [x] Short threads still full-replay  
- [ ] Pre-feature long threads: first follow-up **blocks once** for bootstrap then packs summary+3 on that same call; second follow-up is non-blocking *(code ready; dogfood residual)*  
- [x] Bootstrap failure falls back to truncated full history and still returns an answer *(fail-open in code)*  
- [x] Summary job after save is async / fail-open *(live: tip `ready` ~2s after follow-up save)*  
- [x] Steady-state turns with ready tip summary do **not** block on summarizer *(bootstrap gate skips when ready)*  
- [x] Regen dirties descendants and recomputes tip summary *(code; manual residual)*  
- [x] Manual Summarize Thread still works and does not break packing *(filter + schedule skip; manual residual for UX)*  
- [x] Feature + external DB docs updated  
- [x] Packing unit tests pass (`tests/test_doubt_context_packing.py`, 23 tests)  


---

## Handoff

Plan is ready to implement task-by-task. Preferred execution: packing helpers/tests first, then schema + shared summarizer (`ensure` sync + `schedule` async), then wire ensure **before** packing in `clear_doubt` so legacy first follow-ups never answer with empty thread memory when the path is long enough, then post-save schedule + regen, then docs.
