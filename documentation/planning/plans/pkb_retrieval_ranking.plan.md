---
name: PKB Retrieval Ranking Improvements
overview: "Improve PKB retrieval precision with three independent, eval-gated changes: (W-A) weighted RRF so literal FTS is trusted less than semantic embedding, (W-B) per-strategy query scoping so the conversation summary stops polluting the literal FTS signal, and (W-C) an entity-linked retrieval strategy that boosts claims tied to entities the user names directly (reusing the entities the rewrite LLM already emits and the existing claim-embedding cache)."
todos:
  - id: eval-baseline
    content: Re-confirm the retrieval eval baseline (precision@5/recall@5/mrr) before any change; capture the exact command + numbers in the plan thread
    status: pending
  - id: wa-weighted-rrf
    content: "W-A: add per-strategy weights to merge_results_rrf (weighted RRF); config w_fts < w_embedding; default weights reproduce current ranking exactly"
    status: pending
  - id: wa-eval
    content: "W-A: eval-gate — tune w_fts/w_embedding on the harness, keep or revert based on precision@5/mrr"
    status: pending
  - id: wb-query-scoping
    content: "W-B: route per-strategy queries in hybrid — FTS gets the focused current-message/rewrite fts_query, embedding gets the contextual embedding_query; stop feeding the summary-laden enhanced_query to literal FTS"
    status: pending
  - id: wb-eval
    content: "W-B: eval-gate query scoping; verify stale past-topic matches drop without recall regression"
    status: pending
  - id: wc-entity-strategy
    content: "W-C: new EntitySearchStrategy — resolve query entities (reuse rewrite entities + W6 aliases), pull claim_entities-linked claims, rank by cached claim-embedding cosine to query, return top-N"
    status: pending
  - id: wc-hybrid-wire
    content: "W-C: register entity strategy in hybrid default set behind a flag; RRF fusion gives the boost + dedup automatically"
    status: pending
  - id: wc-eval
    content: "W-C: eval-gate entity strategy; add entity-mention queries to the eval set if missing"
    status: pending
  - id: config-fields
    content: Add config fields (rrf strategy weights, entity strategy top-N + enable flags) wired through to_dict/from_dict/env
    status: pending
  - id: coordinate-getpkbcontext
    content: Coordinate _get_pkb_context edits with the short-term-memory plan (STM injection vs query-scoping live in the same function); agree on ordering to avoid conflicts
    status: pending
  - id: docs
    content: Update implementation.md + deep-dive (search section), feature doc, config docs with the three changes
    status: pending
  - id: tests
    content: Unit tests for weighted RRF, per-strategy query routing, and the entity strategy (resolution, alias linking, embedding ranking, top-N, RRF boost)
    status: pending
---

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
- Changes to `apply_recency_confidence_rerank` — left to the short-term-memory plan (its `last_accessed_at` work). This plan must not touch that function.
- New LLM calls — W-C consumes the existing rewrite output; no added latency.

## Verified Current State (as of this plan)

- `merge_results_rrf(result_lists, k=60, rrf_k=60)` — unweighted reciprocal-rank fusion; a claim appearing in multiple lists already gets its scores **summed** (this is the mechanism W-C relies on for the entity boost + automatic dedup).
- Default hybrid strategies = `["fts", "embedding", "rewrite"]` when an LLM key is present (`hybrid_search.py`). `rewrite` makes one `SUPERFAST_LLM` call emitting `{fts_query, embedding_query, keywords, tags, entities}`. `expand_query()` is a thin wrapper over the same call.
- The base `fts` and `embedding` strategies both receive the raw `enhanced_query` (summary-laden); they do **not** consume the rewrite's focused `fts_query`/`embedding_query`.
- `EmbeddingStore.get_embedding(claim)` gives cached per-claim vectors; the query embedding is already computed for embedding search → W-C cosine ranking is free of extra model calls.
- Entity resolution can reuse the `entities` table + W6 alias set (`meta_json.aliases`) so name variants ("Tom"/"Thomas") link.
- Eval baseline to protect: **precision@5 = 0.537, recall@5 = 0.763, mrr = 0.664** (unchanged across all prior PKB workstreams).

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

Files: `search/hybrid_search.py` (per-strategy query dispatch), `Conversation.py` (`_get_pkb_context`: pass the current message separately from the contextual summary instead of pre-fusing them into one `enhanced_query`), possibly `search/rewrite_search.py` (expose `fts_query`/`embedding_query` to the orchestrator).

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

---

## Eval Methodology (gates every workstream)

- Run the retrieval eval harness (`truth_management_system/tests/eval/`) before and after each workstream; record `precision@5`, `recall@5`, `mrr`.
- **Acceptance:** a change ships only if it improves (or holds) `precision@5`/`mrr` without regressing `recall@5` beyond noise. Default config values must reproduce the **0.537 / 0.763 / 0.664** baseline exactly (proves the no-op default).
- For W-C, add a handful of **entity-mention queries** to the eval set if it lacks them (otherwise the entity strategy's value is invisible to the metric).
- Tune one variable at a time (e.g., fix `rrf_k`, sweep `w_fts`).

## Coordination with the Short-Term Memory Plan

`short_term_memory_and_compaction.plan.md` is in flight in another window and edits some of the
same files. This plan is **orthogonal in purpose** (it adds an ephemeral memory layer + injection;
this improves long-term ranking) but must coordinate on touchpoints:

| File | Short-term plan | This plan | Conflict / resolution |
|---|---|---|---|
| `search/base.py` | `apply_recency_confidence_rerank` (+`last_accessed_at`) | `merge_results_rrf` (weighted) | Different functions → low; do **not** touch the rerank here |
| `config.py` | STM/compaction fields | RRF weights + entity flags | Append-only → low; land sequentially |
| `Conversation.py` `_get_pkb_context` | prepend STM "recent context" block | split FTS/embedding queries + entity wiring | **Medium** — same function. Agree ordering: STM block is a prepend near the top; query-scoping is in the search-construction region lower down. Land one, rebase the other. |
| `hybrid_search.py`, `rewrite_search.py`, `search/entity_search.py` | none | this plan only | none |

Recommendation: keep them as **separate plans** with an explicit handshake on `_get_pkb_context`
and `config.py`. Land **W-A and W-B first** (pure ranking, no schema, immediately measurable);
**W-C** after. W-B is likely the single biggest precision win because it removes a whole class of
stale matches at the source.

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
- `truth_management_system/config.py` — new fields + to_dict/from_dict/env (W-A/W-B/W-C)
- `Conversation.py` — `_get_pkb_context`: separate current-message vs contextual query (W-B) [coordinate with STM plan]
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
