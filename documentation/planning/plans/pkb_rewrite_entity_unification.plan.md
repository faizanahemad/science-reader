---
name: PKB Rewrite/Entity Unification (single LLM call → FTS + embedding + entity, single top-level RRF)
overview: "Make the existing overview-aware rewrite the single source of query derivation: one SUPERFAST_LLM call emits {fts_query, embedding_query, keywords, tags, entities}; the orchestrator dispatches those outputs to the base FTS, embedding, and the standalone entity strategy (fed the LLM entities as surface forms), then fuses everything in ONE top-level RRF with per-source W-A weights. Design (ii): keep strategies as distinct sources (preserves weighting + offline fallback + single RRF, avoids redundancy). No schema change; old claims keep working; optional data-level entity-link backfill brings the existing corpus up to parity. Eval-gated; defaults preserve current behavior."
todos:
  - id: context-mechanism
    content: "Add a per-call dispatch mechanism to thread rewrite outputs to strategies without a 2nd LLM call: a `strategy_context` (entities/embedding_query/precomputed rewrite metadata) carried alongside the existing W-B `strategy_queries` map through hybrid.search → _execute_parallel → strategy.search. Decide interface: extend SearchFilters (transient hints) vs a dedicated context param. Lean: dedicated `strategy_context: Dict[str, Any]` symmetric with strategy_queries."
    status: pending
  - id: single-call-coordination
    content: "In the hybrid orchestrator: when a key is present and rewrite+entity are both active, compute the rewrite metadata ONCE (rewrite.search_with_metadata or a memoized _rewrite_query), use those rewrite results as the `rewrite` source (do not re-run rewrite's LLM in parallel), and pass extracted_entities → entity strategy (surface_forms) and embedding_query → embedding. Inject precomputed metadata into the rewrite strategy so it never double-calls."
    status: pending
  - id: rewrite-precomputed-metadata
    content: "Add an optional `precomputed_metadata`/`metadata` param to RewriteSearchStrategy.search/search_with_metadata so the orchestrator can supply the already-computed RewriteMetadata and the strategy skips its own _rewrite_query call. Default None = current behavior (self-call)."
    status: pending
  - id: entity-consume-rewrite-entities
    content: "Entity strategy consumes the LLM entities via the surface_forms hook (already added in 05b604a) read from strategy_context; falls back to regex extraction when absent (offline / no key). Gate with `entity_use_rewrite_entities` (default True). Cap still applies (entity_strategy_max_entities=5)."
    status: pending
  - id: reuse-query-embedding
    content: "Avoid the entity strategy's extra get_query_embedding call: pass the embedding_query (or a precomputed query vector) via strategy_context so entity cosine ranking reuses what embedding/rewrite already computed. Fallback: compute as today. Keep _cosine dimension-consistent (same get_query_embedding/get_embedding_model path)."
    status: pending
  - id: config-flags
    content: "Add config flags (default to current behavior): entity_use_rewrite_entities: bool = True; rewrite_is_query_source: bool = True (single-call dispatch). Wire through dataclass/to_dict/from_dict/env. No-op/inert defaults so a restart with no env changes preserves behavior."
    status: pending
  - id: backfill-entities
    content: "Optional data-level migration: StructuredAPI.backfill_entities(context_domain=None, dry_run=False) following the existing backfill_embeddings/backfill_provenance/backfill_origin pattern — for claims lacking claim_entities links, run extract_entities + get_or_create + link_claim_entity. Idempotent, batched, dry-run, user-scoped. Optional REST endpoint + CLI. NOT required for correctness (FTS/embedding still retrieve un-linked claims); only raises entity-path recall on the existing corpus."
    status: pending
  - id: eval
    content: "Extend the retrieval eval harness with entity-mention + paraphrase cases that exercise the LLM-entity path (keyed run). Re-baseline, then gate: confirm precision@5/mrr improve (or hold) and recall@5 does not regress. Tune rrf_strategy_weights (W-A) on this harness (fts<embedding; entity≈0.8) and ship only what helps."
    status: pending
  - id: tests
    content: "Unit: strategy_context threading; rewrite precomputed_metadata skips the LLM call; entity consumes surface_forms from context; reused embedding ranking; config round-trip/defaults. Integration: hybrid issues exactly ONE rewrite LLM call (no double-call) and entity claims surface + dedup in a single top-level RRF. Migration: backfill_entities idempotency + dry-run + user scope + status filter. Restart: load_config defaults preserve behavior."
    status: pending
  - id: docs
    content: "Update README (search approaches), implementation.md (rewrite + entity sections, orchestration), implementation_deep_dive.md (single-call dispatch + RRF flow), and config docs. Document the backfill command + that it is optional."
    status: pending
  - id: rollback
    content: "Verify rollback: flags off (entity_use_rewrite_entities=False, rewrite_is_query_source=False) returns to today's behavior (entity uses regex; strategies run independently). rrf_strategy_weights={} keeps unweighted fusion. No schema change to revert."
    status: pending
---

# PKB Rewrite/Entity Unification

## Motivation & Problem Statement

The overview-aware `RewriteSearchStrategy` already makes a single `SUPERFAST_LLM`
call that emits `{fts_query, embedding_query, keywords, tags, entities}`
(committed in `ed1dcb9`). Today, at hybrid time:

- `extracted_entities` / `extracted_tags` / `fts_query` / `embedding_query` are
  **discarded at the orchestration level** — the orchestrator calls each
  strategy's plain `search()`, throwing away the rewrite metadata.
- The standalone `entity` strategy works, but resolves entity names with a
  **regex heuristic** (capitalized/quoted spans) instead of the higher-quality
  LLM `entities` list, and computes its **own** query embedding (a redundant
  embedding call).
- The base `fts`/`embedding` strategies still receive the contextual
  `enhanced_query`, not the rewrite's focused `fts_query`/`embedding_query`
  (W-B only routes the raw current message to FTS/entity so far).

Net: we pay for a rich LLM call and then ignore most of it. This plan makes the
rewrite the **single source of query derivation** and dispatches its outputs to
the existing strategies — **reusing work we already pay for**, with no new LLM
call and no schema change.

## Goals

- One rewrite LLM call per retrieval; its outputs drive FTS, embedding, and
  entity resolution (zero extra LLM/embedding calls vs. today's keyed path).
- Entity resolution uses the LLM `entities` (higher precision/recall than
  regex), capped at `entity_strategy_max_entities` (5).
- **Single top-level RRF** over distinct sources (`fts`, `embedding`, `rewrite`,
  `entity`) so W-A per-source weighting still applies (no double fusion).
- Every change **eval-gated** and **defaults to current behavior**; safe across
  server restart; old claims keep working.

## Non-Goals

- No new retrieval strategy and no new LLM call (design (ii): enhance the
  current rewrite + reuse the existing entity strategy).
- No schema change. `claim_entities` already exists; `SCHEMA_VERSION` unchanged.
- No change to `apply_recency_confidence_rerank` (operates downstream).
- Tag-linked retrieval (consuming `extracted_tags`) is out of scope here; can be
  a symmetric follow-up once the entity path is proven.

## Verified Current State (post `ed1dcb9` + `05b604a`)

- `RewriteSearchStrategy` (committed): one `SUPERFAST_LLM` call →
  `RewriteMetadata{rewritten_query(fts), embedding_query, extracted_keywords,
  extracted_tags, extracted_entities}`; runs FTS + embedding internally and
  RRF-merges; overview-aware (`set_overview_context`); has `search_with_metadata`.
- Hybrid default set (committed) = `[fts, embedding, rewrite, entity]` when
  registered (rewrite/embedding require a key; `entity` is key-independent and
  degrades to recency offline).
- `EntitySearchStrategy` (committed): resolves entities (exact name + W6
  aliases), pulls **status-filtered** linked claims via
  `EntityCRUD.resolve_claims`, cosine-ranks vs. the query embedding, caps
  resolved entities to `entity_strategy_max_entities=5`, and **already accepts
  caller-supplied `surface_forms`** in `_resolve_entity_ids` (the reuse hook).
- `merge_results_rrf(result_lists, k, rrf_k, strategy_weights=None)` (committed,
  W-A): weighted fusion keyed on `result.source`; default `{}` = unweighted.
- W-B (`_get_pkb_context`): routes the focused current message to `fts` + `entity`
  via the `strategy_queries` map; embedding/rewrite keep the contextual query.
- Schema/migration: `database.initialize_schema()` checks `get_schema_version()`
  and runs versioned, idempotent `_run_migrations` (ALTER TABLE …). Entity links
  are created at ingestion (`add_claim(auto_extract=True)` →
  `llm_helpers.extract_entities` → `_get_or_create_entity` + `link_claim_entity`).
  Established backfill pattern exists: `backfill_embeddings/provenance/origin`.

## Design

### The single-call dispatch (design (ii), lightweight)

```
                       ┌──────────────────────────────────────────┐
 query  ──────────────►│  Hybrid orchestrator                     │
 (focused + context)   │  1) ONE rewrite LLM call (if key)         │
                       │     → RewriteMetadata{fts_query,          │
                       │        embedding_query, entities, tags}   │
                       └───────────────┬──────────────────────────┘
        dispatch via strategy_context  │
        ┌──────────────┬───────────────┼───────────────────────────┐
        ▼              ▼               ▼                            ▼
   FTS(fts_query)  EMB(embedding_   REWRITE(precomputed_       ENTITY(surface_forms=
                       query)         metadata → no 2nd call)     entities, reuse emb)
        └──────────────┴───────────────┴───────────────────────────┘
                       ▼  ONE top-level merge_results_rrf (weighted, W-A)
                  fused, de-duped by claim_id  → recency/confidence rerank
```

Key points:
- **One LLM call.** The orchestrator computes `RewriteMetadata` once and injects
  it into the rewrite strategy (new optional `precomputed_metadata` param) so it
  does not call the LLM again. Entities + embedding_query travel via
  `strategy_context`.
- **Distinct sources preserved.** `fts`, `embedding`, `rewrite`, `entity` each
  return their own list with their own `source`; one top-level RRF fuses them →
  W-A weights still apply (e.g. `fts≈0.6, embedding=1.0, rewrite=1.0, entity≈0.8`).
- **No double RRF.** The rewrite still does its internal FTS+embedding merge as a
  `rewrite` source; entity is a separate source — there is exactly one *additional*
  fusion (the top-level one that already exists), not a fusion-of-fusions for the
  entity signal.
- **Offline / no key.** No rewrite call → `strategy_context` empty → entity falls
  back to regex extraction and computes its own embedding (or recency). Exactly
  today's behavior. The flags make this the inert default until enabled.

### Interface decision (task `context-mechanism`)

Prefer a dedicated `strategy_context: Dict[str, Any]` threaded exactly like the
existing `strategy_queries` map (hybrid.search → `_execute_parallel` →
per-strategy). The entity strategy reads `strategy_context["entity_surface_forms"]`
and `strategy_context["query_embedding"]`; absent keys → current behavior. This
avoids overloading `SearchFilters` (which is for filtering) and keeps the no-op
default trivial.

## Migration, Backward Compatibility & Restart Safety

This is the part to get right. Summary: **nothing breaks; migration is optional.**

1. **No schema migration.** (ii) adds no columns/tables. `claim_entities`,
   `entities`, `claim_embeddings` all already exist. `SCHEMA_VERSION` is
   unchanged, so `initialize_schema()` is a no-op on existing DBs and a normal
   create on fresh ones. There is nothing to roll back at the schema level.

2. **Old claims without entity links still work.** Claims created before entity
   extraction (or with `auto_extract=False`) simply have no `claim_entities`
   rows. The entity *path* won't boost them, but `fts`/`embedding`/`rewrite`
   retrieve them exactly as today — **no regression**, only a missed *bonus* on
   un-linked claims.

3. **Optional entity-link backfill (data-level).** To bring the existing corpus
   to parity, add `StructuredAPI.backfill_entities()` mirroring the proven
   `backfill_embeddings/provenance/origin`:
   - Find active claims with no `claim_entities` link (user-scoped, batched).
   - Run `extract_entities(statement)` → `get_or_create` entity →
     `link_claim_entity`. Respect status filter (don't link archived/superseded).
   - **Idempotent** (skip claims already linked), **dry-run** flag, bounded batch
     size, resumable. Returns `{scanned, linked, skipped}`.
   - Optional REST endpoint (`POST /pkb/backfill/entities`) + a CLI module, same
     ergonomics as existing backfills. Costs LLM calls → run off-peak; not on the
     hot path and not required for correctness.

4. **Embedding-cache compatibility.** Entity cosine ranking reuses cached claim
   vectors via `get_embedding(claim_id, expected_model=config.embedding_model)`.
   If the embedding model changes, the `expected_model` mismatch yields a cache
   miss → the claim sorts after scored ones (recency fallback) → **degraded
   ranking, not breakage**. Same query/claim embedding path
   (`get_embedding_model(keys)`) guarantees dimension consistency.

5. **Server restart / config.** New flags load via `load_config()` from
   env/dict with **safe defaults** (`entity_use_rewrite_entities=True`,
   `rewrite_is_query_source=True` only change *which query text* each strategy
   sees; `rrf_strategy_weights={}` keeps fusion unweighted). A restart with no
   env changes preserves behavior. No new persistent/ephemeral state is added;
   `strategy_context` is per-request and transient.

6. **Failure isolation.** The rewrite LLM call already degrades to the raw query
   on error; the parallel executor catches per-strategy exceptions and returns
   `[]` (an RRF no-op). A missing/oversized `strategy_context` must never break a
   search — entity falls back to regex; tests assert this.

## Eval Methodology (gates the change)

- Re-baseline on a **keyed** `run_eval.sh` (offline can't measure rewrite fusion,
  embedding cosine, or LLM-entity resolution).
- Add entity-mention + paraphrase cases that the regex path would miss
  (e.g. lowercase entity names) so the LLM-entity reuse is visible to the metric.
- Gate: precision@5 / mrr improve or hold; recall@5 must not regress.
- Then tune `rrf_strategy_weights` (W-A) on the same harness; ship only weights
  that help. Backfill is eval-checked separately (recall on a pre-existing corpus).

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Double LLM call (rewrite runs again in parallel) | Orchestrator computes metadata once; inject `precomputed_metadata` into rewrite so it skips its call. Integration test asserts exactly one rewrite LLM call. |
| Lost per-source weighting | Design (ii) keeps `entity` a distinct source; single top-level RRF with W-A weights. |
| Entity flooding | `entity_strategy_max_entities=5` cap (committed) + `entity_strategy_top_n=5` claim cap + RRF dedup. |
| Extra embedding call for entity ranking | Reuse `embedding_query`/precomputed vector via `strategy_context`. |
| Backfill cost / partial runs | Dry-run, batched, idempotent, resumable; off the hot path; optional. |
| Latency | One LLM call total; strategies still parallel; entity reuses embedding. |
| Restart behavior drift | Safe flag defaults; config round-trip test; no persistent state. |

## Sequencing

1. `context-mechanism` + `rewrite-precomputed-metadata` (plumbing, no behavior change; unit-tested).
2. `single-call-coordination` + `entity-consume-rewrite-entities` + `reuse-query-embedding` (the unification; behind flags).
3. `config-flags` (defaults inert) → `tests` → keyed `eval` → tune W-A.
4. `backfill-entities` (independent, optional) — can land in parallel; eval its recall effect separately.
5. `docs` + `rollback` verification.

## Files (anticipated)

| File | Change |
|---|---|
| `search/hybrid_search.py` | single-call coordination; thread `strategy_context`; use precomputed rewrite metadata as the `rewrite` source |
| `search/rewrite_search.py` | optional `precomputed_metadata` param on `search`/`search_with_metadata` (skip self-call) |
| `search/entity_search.py` | read `surface_forms` + `query_embedding` from `strategy_context`; flag-gated; (reuse hook already present) |
| `Conversation.py` `_get_pkb_context` | pass focused/context queries (W-B) and let hybrid own the single rewrite call |
| `config.py` | `entity_use_rewrite_entities`, `rewrite_is_query_source` (+ env), inert defaults |
| `interface/structured_api.py` | `backfill_entities()` (+ optional REST) following backfill_* pattern |
| `tests/` | plumbing, no-double-call integration, backfill, restart/config |
| `docs/` | README + implementation.md + deep-dive + config |
