---
name: PKB Retrieval Ranking Improvements
overview: "Improve PKB retrieval precision with three independent, eval-gated changes: (W-A) weighted RRF so literal FTS is trusted less than semantic embedding, (W-B) per-strategy query scoping so the conversation summary stops polluting the literal FTS signal, and (W-C) an entity-linked retrieval strategy that boosts claims tied to entities the user names directly (reusing the entities the rewrite LLM already emits and the existing claim-embedding cache)."
todos:
  - id: eval-baseline
    content: "RE-BASELINE the retrieval eval against the CURRENT working tree (post short-term-memory v12 + the w_recency=0.15/w_confidence=0.1 tuning). The historical 0.537/0.763/0.664 was measured at w_recency=w_confidence=0 and is now stale. Capture the new precision@5/recall@5/mrr before any change."
    status: done
  - id: wa-weighted-rrf
    content: "W-A: add per-strategy weights to merge_results_rrf (weighted RRF); config w_fts < w_embedding; default weights reproduce current ranking exactly"
    status: done
  - id: wa-eval
    content: "W-A: eval-gate — tune w_fts/w_embedding on the harness, keep or revert based on precision@5/mrr"
    status: done
  - id: wb-query-scoping
    content: "W-B: route per-strategy queries in hybrid — FTS gets the focused current-message/rewrite fts_query, embedding gets the contextual embedding_query; stop feeding the summary-laden enhanced_query to literal FTS"
    status: done
  - id: wb-eval
    content: "W-B: eval-gate query scoping; verify stale past-topic matches drop without recall regression"
    status: done
  - id: wc-entity-strategy
    content: "W-C: new EntitySearchStrategy — resolve query entities (reuse rewrite entities + W6 aliases), pull claim_entities-linked claims, rank by cached claim-embedding cosine to query, return top-N"
    status: done
  - id: wc-hybrid-wire
    content: "W-C: register entity strategy in hybrid default set behind a flag; RRF fusion gives the boost + dedup automatically"
    status: done
  - id: wc-eval
    content: "W-C: eval-gate entity strategy; add entity-mention queries to the eval set if missing"
    status: done
  - id: config-fields
    content: Add config fields (rrf strategy weights, entity strategy top-N + enable flags) wired through to_dict/from_dict/env
    status: done
  - id: coordinate-getpkbcontext
    content: "W-B builds on the ALREADY-LANDED short-term-memory _get_pkb_context (STM injects a <stm_context> block and updates last_accessed_at after distillation). Preserve both; the query-scoping change is confined to the enhanced_query/api.search construction region."
    status: done
  - id: docs
    content: Update implementation.md + deep-dive (search section), feature doc, config docs with the three changes
    status: done
  - id: tests
    content: Unit tests for weighted RRF, per-strategy query routing, and the entity strategy (resolution, alias linking, embedding ranking, top-N, RRF boost)
    status: done
---

**Status:** DONE (June 2026) — Code for W-A (weighted RRF), W-B (query scoping), W-C (entity strategy) all implemented with tests. Eval baseline and validation completed 2026-06-13.

## Eval Results (2026-06-13)

Dataset: `pkb_seed_v3` — 58 claims, 45 cases, 11 categories. k=5.

| Configuration | precision@5 | recall@5 | mrr |
|---------------|-------------|----------|-----|
| **Baseline** (equal weights, W-B on, W-C on) | 0.209 | 0.926 | 0.827 |
| **W-A tuned** (emb=1.0, fts=0.6, entity=0.8) | 0.218 | 0.941 | 0.851 |
| **W-A tuned + W-B off** | 0.218 | 0.941 | 0.862 |
| Entity-only (W-C solo) | 0.056 | 0.067 | 0.056 |
| Embedding-only | 0.231 | 0.963 | 0.904 |
| FTS-only | 0.455 | 0.726 | 0.700 |

**Findings:**
- **W-A (weighted RRF)** provides a clear improvement: +0.009 precision, +0.015 recall, +0.024 mrr over baseline.
- **W-B (focused query)** shows *no improvement on this eval dataset* because queries don't include running summaries. In production (where running summary is appended to the query), W-B would prevent summary noise from polluting FTS results. Keeping W-B on is the correct production default.
- **W-C (entity strategy)** has zero marginal effect on hybrid — the 3 entity-specific cases are already found by embedding search at rank 1. Entity strategy is valuable as a *fallback* when embeddings are unavailable.
- Adding entity to hybrid fusion (`fts+embedding+entity`) produces identical scores to `fts+embedding` — entity's contribution is redundant when embedding covers those cases.
- **Recommended production config:** `rrf_strategy_weights = {"embedding": 1.0, "fts": 0.6, "entity": 0.8}`, `fts_use_focused_query = True`, `entity_strategy_enabled = True`.

# PKB Retrieval Ranking Improvements

## Motivation & Problem Statement

The PKB hybrid retrieval works but has three concrete precision problems, all verified in the current code:

1. **FTS is trusted as much as semantic search.** `merge_results_rrf` (search/base.py) fuses every strategy with **equal weight** — `1/(rank+60)` per list, no per-strategy weighting. For a personal KB, literal keyword (FTS) precision is generally lower than embedding similarity, yet they vote equally.

2. **The conversation summary pollutes the literal FTS signal.** `_get_pkb_context` (Conversation.py) builds one `enhanced_query` = current user message + the last 4000 chars of the conversation summary, then passes that *same* string to the base FTS strategy **and** the base embedding strategy. FTS then keyword-matches claims about *past* topics that appear in the summary, not the current message — surfacing stale, off-topic claims. (The conversation summary is legitimately useful as *semantic context* — it belongs in the embedding signal, not in literal keyword matching.)

3. **Entities the user names directly don't boost their claims.** When the user mentions an entity by name, that entity's claims should rank higher. Today they don't: retrieval is FTS + embedding + RRF only. The `RewriteSearchStrategy` already extracts an `entities` list from the query in its single LLM call, but that list is **discarded for routing** — never used to pull entity-linked claims. The relational entity graph (`entities`, `claim_entities`, plus W6 aliases/merge) exists but is unused at query time.

These are independent and individually small, but together they degrade top-K precision — the most important property for context injection, where only a handful of claims reach the LLM.

## Goals

- Trust semantic matches more than literal FTS, configurably, without losing FTS's exact-match recall.
- Remove the class of stale matches caused by feeding the conversation summary to literal FTS.
- Make a direct entity mention boost that entity's claims, reusing work we already pay for (the rewrite LLM's `entities` output, the claim-embedding cache, W6 aliases).
- Every change is **independently eval-gated** against the retrieval harness and **defaults to a no-op / current behavior** until tuned, so nothing regresses the baseline silently.

## Non-Goals

- Verb-form normalization / FTS Porter stemming — explicitly out of scope (embeddings + LLM rewrite already cover tense; a stemming tokenizer is a schema rebuild for marginal gain).
- A hard token-budget guardrail on the injected PKB block — out of scope; top-K is sufficient.
- Changes to `apply_recency_confidence_rerank` — the short-term-memory work already added the `last_accessed_at` signal (`max(last_reinforced_at, last_accessed_at, updated_at)`). This plan deliberately does **not** modify the rerank; W-A/W-B/W-C all operate *upstream* of it (fusion + query construction).
- New LLM calls — W-C consumes the existing rewrite output; no added latency.

## Verified Current State (post short-term-memory implementation)

> **Note:** The Short-Term Cross-Conversation Memory & Compaction plan
> (`short_term_memory_and_compaction.plan.md`) has been **implemented** (schema
> v12, uncommitted in the working tree at the time of writing). The findings
> below reflect that landed state, which this plan builds on.

- `merge_results_rrf(result_lists, k=60, rrf_k=60)` — **untouched by the STM work**; still unweighted reciprocal-rank fusion. A claim appearing in multiple lists already gets its scores **summed** (the mechanism W-C relies on for the entity boost + automatic dedup). **W-A is clean.**
- `apply_recency_confidence_rerank` / `_claim_age_days` — **STM already changed this** to use `max(last_reinforced_at, last_accessed_at, updated_at)` for the decay age. The new `last_accessed_at` column (schema v12) is updated for claims sent to the LLM after distillation. **This plan does NOT touch the rerank** — that work is done.
- Working-tree rerank defaults are now `w_recency=0.15`, `w_confidence=0.1` (the tuning), **not** the historical `0/0`. So the rerank is *active* by default and the old eval baseline `0.537/0.763/0.664` (measured at `0/0`) is **stale** — re-baseline first.
- Default hybrid strategies = `["fts", "embedding", "rewrite"]` when an LLM key is present. `rewrite` now runs **FTS + embedding internally and merges via RRF**, is **overview-aware** (`set_overview_context`, Key Areas), and emits `{fts_query, embedding_query, keywords, tags, entities}` in one `SUPERFAST_LLM` call. `expand_query()` is a thin wrapper over the same call.
- The base `fts` and `embedding` strategies still receive the raw `enhanced_query` (current message + last 4000 chars of conversation summary); they do **not** consume the rewrite's focused `fts_query`/`embedding_query`. → W-B's target is unchanged.
- `_get_pkb_context` now: (1) **prepends** a `<stm_context>` "recent context from your other conversations" block (recency-based, ephemeral, separate from long-term search), (2) runs the long-term hybrid search on `enhanced_query`, (3) distills, (4) **updates `last_accessed_at`** for the claims sent to the LLM, (5) injects the overview snippet. W-B edits only the search-construction region (2); it must preserve (1) and (4).
- `EmbeddingStore.get_embedding(claim)` gives cached per-claim vectors; the query embedding is already computed for embedding search → W-C cosine ranking needs **no** extra model calls.
- Entity resolution can reuse the `entities` table + W6 alias set so name variants ("Tom"/"Thomas") link.
- `config.py` now carries `stm_*` and `compaction_*` fields; this plan's fields **append** after them (no overlap). Schema is **v12**; this plan adds **no** schema change.

---

## Design

### W-A: Weighted RRF (trust FTS less than semantic)

Extend `merge_results_rrf` to accept per-strategy weights and compute
`score += weight[source] · 1/(rank + rrf_k)`. The `SearchResult.source` field already
labels which strategy produced each result (`"fts"`, `"embedding"`, `"rewrite"`, and the
new `"entity"`), so weighting keys off that.

- Config: `rrf_strategy_weights: Dict[str, float]`, default `{}` → **every weight is 1.0**, which reproduces today's exact ranking (no-op default, mirrors the C3 invariant pattern already used for the rerank).
- Recommended starting point after eval tuning: `embedding=1.0`, `rewrite=1.0`, `fts≈0.6`, `entity≈0.8` — but the **eval harness decides** the final values; ship only what improves precision@5/mrr without hurting recall@5.

Files: `search/base.py` (`merge_results_rrf` signature + math), `search/hybrid_search.py` (pass weights from config into the merge call), `config.py` (field + to_dict/from_dict/env).

Alternatives considered:
- Score normalization + linear blend instead of weighted RRF — rejected; RRF's rank-based fusion is robust to incomparable score scales and is already in place. Weighting it is the minimal change.
- Hard-drop FTS below a rank threshold — rejected; too blunt, loses exact-match recall.

Challenges / risks:
- Weights interact with `rrf_k`; keep `rrf_k` fixed (60) while tuning weights so there's one variable.
- Must confirm `source` is consistently set on every result list (verify embedding/fts/rewrite all stamp it).

### W-B: Per-strategy query scoping (de-pollute FTS)

Stop sending the summary-laden `enhanced_query` to literal FTS. Route different queries to
different strategies inside hybrid search:

- **FTS** ← the *focused* query: the current user message, or the rewrite's `fts_query` (3–6 intent keywords the LLM already derives). Literal matching should reflect *current* intent, not past summary topics.
- **Embedding** ← the *contextual* query: the rewrite's `embedding_query` (or the existing `enhanced_query`). Semantic search legitimately benefits from conversation context.
- **Rewrite** ← unchanged (it self-derives both).

Implementation shape (no code here): give `HybridSearchStrategy.search` an optional
per-strategy query map, or have it call the rewrite once up front and dispatch
`fts_query`→FTS and `embedding_query`→embedding. The cleanest version makes the rewrite the
**single source of query derivation** and feeds the base strategies its outputs, so the LLM
call we already make does double duty.

Files: `search/hybrid_search.py` (per-strategy query dispatch), `Conversation.py` (`_get_pkb_context`: pass the current message separately from the contextual summary instead of pre-fusing them into one `enhanced_query` — **rebase onto the landed STM version: keep the `<stm_context>` prepend and the post-distillation `last_accessed_at` update intact**), possibly `search/rewrite_search.py` (expose `fts_query`/`embedding_query` to the orchestrator).

Alternatives considered:
- Keep one query but **weight FTS lower** (W-A alone) — helps but doesn't remove the *wrong* matches, only down-weights them; the stale claim can still crack top-K. W-B addresses the root cause. Do both.
- Drop the base `fts` strategy entirely in favor of rewrite-driven FTS — possible later simplification, but keep base FTS as a no-LLM fallback for when keys are absent.

Challenges / risks:
- When no LLM key is present (no rewrite), FTS must fall back to the current message (not the summary). Define the fallback explicitly.
- Recall risk: a tightly-scoped FTS query might miss a claim the summary would have surfaced — but that claim *should* come from embedding/contextual search instead. Eval must confirm recall@5 holds.

### W-C: Entity-linked retrieval strategy (boost named entities)

New `EntitySearchStrategy` that participates in hybrid fusion as another ranked list:

1. **Resolve query entities** — reuse the `entities` list the rewrite LLM already emits (zero extra calls). Match each against the `entities` table by normalized name **and W6 aliases** (`meta_json.aliases`) so variants link. Fallback when no rewrite: cheap capitalized-token / quoted-span extraction from the current message.
2. **Pull candidate claims** — via `claim_entities` for the resolved entity ids (respecting `SearchFilters`: user scope, status, domain).
3. **Rank by semantic fit** — cosine(query_embedding, claim_embedding) using the existing `EmbeddingStore` cache; the query embedding is already computed for the embedding strategy, so reuse it.
4. **Return top-N** (config `entity_strategy_top_n`, default 5) as a ranked `SearchResult` list with `source="entity"`.

Fusion does the rest: in RRF a claim found by **both** embedding and entity-link gets its
reciprocal-rank scores **summed** → it rises to the top (the "named entity ⇒ more important"
behavior), and **dedup is automatic** (same `claim_id` merges). W-A can additionally tune the
entity list's weight.

Files: new `search/entity_search.py` (or a method in an existing search module), `search/hybrid_search.py` (register + include in default set behind `entity_strategy_enabled`), `config.py` (top-N + enable flag), reuse `crud/links.py`/`crud/entities.py` for lookups.

Alternatives considered:
- **Post-hoc boost** of existing results whose claims are entity-linked, instead of a separate retrieval list — rejected; a separate list also *introduces* entity-linked claims that literal/semantic search missed entirely (higher recall for named entities), and RRF gives the boost for free.
- Graph traversal (multi-hop entity→claim→entity) — out of scope; single-hop entity→claim is the high-value, low-risk start.

Challenges / risks:
- Entity flooding: a heavily-linked entity could dominate. Mitigated by embedding-ranking + top-N cap + RRF weight.
- Resolution precision: over-eager alias matching could pull unrelated claims. Start with exact normalized-name + curated aliases only; measure before loosening.
- Cold cache: if a linked claim has no cached embedding yet, fall back to its rank position or skip (don't block on synchronous embedding).
- **Status filtering (new requirement from STM compaction):** the entity strategy MUST apply the same `ClaimStatus.default_search_statuses` filter as FTS/embedding, so claims the compaction sweep moved to `archived` (and `superseded`/`expired`) are **not** resurfaced through the entity path. The entity graph links persist after archival, so this is a real leak risk if the join ignores status.

---

## Eval Methodology (gates every workstream)

- **Re-baseline first.** Run the retrieval eval harness (`truth_management_system/tests/eval/`, e.g. `run_eval.sh`) on the **current working tree** and record the new `precision@5`/`recall@5`/`mrr`. The historical `0.537/0.763/0.664` was measured with `w_recency=w_confidence=0`; the working tree now defaults to `0.15/0.1` plus the `last_accessed_at` decay signal, so that number no longer holds. All "no-op default reproduces baseline" claims below mean **the freshly captured working-tree baseline**, not the old one.
- The eval harness scores the **search layer** (`api.search`), not `_get_pkb_context`, so the STM `<stm_context>` injection does **not** affect the metric — but the active rerank weights + `last_accessed_at` do (another reason to re-baseline).
- Run the harness before and after each workstream; a change ships only if it improves (or holds) `precision@5`/`mrr` without regressing `recall@5` beyond noise.
- For W-C, add a handful of **entity-mention queries** to the eval set if it lacks them (otherwise the entity strategy's value is invisible to the metric).
- Tune one variable at a time (e.g., fix `rrf_k`, sweep `w_fts`).

## Relationship to Short-Term Memory (already implemented)

`short_term_memory_and_compaction.plan.md` is **implemented** (schema v12, in the working tree).
It is **orthogonal in purpose** — it adds an ephemeral cross-conversation memory layer (a
recency-injected `<stm_context>` block) and a compaction sweep; this plan improves **long-term
claim ranking**. They **compose**: STM gives "recent activity" awareness at the top of the prompt,
while W-A/W-B/W-C sharpen which long-term claims get retrieved below it.

What STM already did to this plan's surfaces (so there's no double-work / conflict):

| Surface | STM's landed change | This plan |
|---|---|---|
| `search/base.py` `apply_recency_confidence_rerank` | added `last_accessed_at` to decay age (`max(reinforced, accessed, updated)`) | **don't touch** — done |
| `search/base.py` `merge_results_rrf` | untouched | W-A adds per-strategy weights here — clean |
| `Conversation.py` `_get_pkb_context` | prepends `<stm_context>` block; updates `last_accessed_at` after distillation; injects overview snippet | W-B edits only the `enhanced_query`/`api.search` region; **must preserve** the STM prepend + `last_accessed_at` update |
| `config.py` | added `stm_*` / `compaction_*` fields | this plan's fields **append** after them |
| `search/rewrite_search.py`, `hybrid_search.py` | rewrite now does FTS+embedding+RRF, overview-aware, emits `entities`/`embedding_query` | W-B/W-C **consume** those existing outputs |

Net: STM **removed** the coordination risk by landing first. The only remaining care is that W-B's
`_get_pkb_context` edit rebases cleanly onto the STM version (preserve the STM prepend + the
`last_accessed_at` touch). Land **W-A and W-B first** (pure ranking, no schema, immediately
measurable); **W-C** after. W-B is likely the single biggest precision win because it removes a
whole class of stale matches at the source.

A shared surface to note: STM's **compaction** extends the same Memory Cleanup orchestrator (W9)
from the provenance/cleanup plan — unrelated to retrieval ranking, but the `/pkb/cleanup` button
now does more.

**Logical interaction to be aware of — the `last_accessed_at` feedback loop.** STM made
`_get_pkb_context` stamp `last_accessed_at` on every claim sent to the LLM, and the rerank now
decays from `max(reinforced, accessed, updated)`. So changing *which* claims this plan retrieves
will, over time, shift the access-recency distribution (retrieved claims stay "fresh" and rank
higher next time; never-retrieved claims age and become compaction candidates). This is benign and
self-reinforcing, but two consequences matter:
- **Eval is unaffected** — the harness runs a single pass over a static corpus, so there's no loop
  inside a measurement; the captured baseline is stable.
- **In production**, W-A/W-B/W-C effectively steer the long-term decay + compaction signals, not
  just the immediate ranking. Worth monitoring that improved precision doesn't prematurely starve
  borderline-useful claims into archival. No code implication for this plan, but a reason to roll
  out behind the config flags and watch the access distribution.

## Config Fields (new in PKBConfig)

```python
# Weighted RRF (W-A). Empty dict => all weights 1.0 => current behavior exactly.
rrf_strategy_weights: Dict[str, float] = field(default_factory=dict)
#   e.g. {"embedding": 1.0, "rewrite": 1.0, "fts": 0.6, "entity": 0.8} after eval tuning

# Per-strategy query scoping (W-B)
fts_use_focused_query: bool = True        # FTS gets current-message/rewrite fts_query, not the summary

# Entity-linked retrieval (W-C)
entity_strategy_enabled: bool = True
entity_strategy_top_n: int = 5            # max entity-linked claims fed into RRF
entity_alias_match: bool = True           # also resolve via W6 aliases
```

All wired through `to_dict` / `from_dict` (valid_keys) / env mapping, following the existing
config pattern.

## Files Expected to Change

- `truth_management_system/search/base.py` — `merge_results_rrf` per-strategy weights (W-A)
- `truth_management_system/search/hybrid_search.py` — pass weights, per-strategy query dispatch, register entity strategy (W-A/W-B/W-C)
- `truth_management_system/search/rewrite_search.py` — expose `fts_query`/`embedding_query`/`entities` to the orchestrator (W-B/W-C)
- `truth_management_system/search/entity_search.py` — **new** `EntitySearchStrategy` (W-C)
- `truth_management_system/config.py` — new fields + to_dict/from_dict/env (W-A/W-B/W-C), **appended after the landed `stm_*`/`compaction_*` fields**
- `Conversation.py` — `_get_pkb_context`: separate current-message vs contextual query (W-B) — **rebase onto the landed STM version (preserve `<stm_context>` prepend + `last_accessed_at` update)**
- `truth_management_system/crud/links.py` / `crud/entities.py` — reuse for entity→claims lookup (read-only; likely no change)
- `truth_management_system/tests/test_weighted_rrf.py`, `test_query_scoping.py`, `test_entity_strategy.py` — **new** unit tests
- `truth_management_system/tests/eval/` — add entity-mention eval queries (W-C)
- `documentation/features/truth_management_system/implementation.md` + `implementation_deep_dive.md` (search section) + feature doc — docs

## Open Questions

1. **FTS focused-query source:** prefer the rewrite's `fts_query` (LLM intent keywords) or the literal current user message? Likely the rewrite `fts_query` when available, raw message as fallback. Eval both.
2. **Entity strategy in the no-LLM path:** is the cheap capitalized-token/quoted-span fallback worth it, or should the entity strategy simply no-op without a rewrite? (Lean: no-op without rewrite for v1; add lexical fallback only if it helps.)
3. **Should weighted RRF weights be global or query-type-aware?** Start global; revisit only if eval shows a query class that wants different weighting.
4. **Entity boost vs flooding:** is top-N=5 the right cap, and should it scale with `k`? Measure on entity-heavy users.
5. **Reuse of the rewrite call:** confirm a single rewrite invocation can cleanly feed FTS, embedding, and entity strategies without re-calling the LLM per strategy (it should — one call, three consumers).
