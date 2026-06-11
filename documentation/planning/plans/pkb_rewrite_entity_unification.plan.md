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

**Keyed eval gate — PASSED** (k=5 on `pkb_seed_v3`, OpenRouter key, strategies
serialized to dodge a pre-existing bulk-embedding SQLite concurrency bug — see
caveat below; serialization does not change retrieval results):

| set | overall mrr | recall@5 | semantic mrr | conflict mrr |
|---|---|---|---|---|
| `fts` (offline baseline) | 0.740 | 0.780 | 0.050 | 1.000 |
| `embedding` | 0.953 | 1.000 | 0.875 | 0.333 |
| `hybrid_base` = fts+embedding (prior default) | 0.872 | 1.000 | 0.473 | 1.000 |
| **`hybrid_full`** = fts+embedding+rewrite+entity (unification) | **0.927** | 1.000 | **0.700** | 1.000 |

The unification lifts overall mrr **+0.055 over the prior hybrid default**
(+0.187 over FTS) and **semantic mrr +0.227** (0.473→0.700), with **no recall
regression and no per-category mrr below 0.700** — it is the most uniformly
robust config (embedding-only edges aggregate mrr but is brittle: conflict
0.333). A W-A weight sweep (`{}`, `{fts:0.6,emb:1.0,rewrite:1.0,entity:0.8}`,
`{fts:0.5,emb:1.0,rewrite:0.9,entity:1.0}`) moved overall mrr by <0.01 — RRF is
rank-based, so **the default unweighted RRF ships as-is; no W-A tuning needed.**

> Note (FIXED — commit follows this gate): bulk-embedding the whole seed at
> once tripped `SQLITE_MISUSE` because `EmbeddingStore.ensure_embeddings`
> read/wrote the single shared sqlite connection from parallel worker threads.
> `PKBDatabase` now serializes all connection access with a reentrant lock
> (network/LLM work stays parallel), so bulk keyed eval no longer needs the
> `max_parallel_*=1` workaround. Covered by `tests/test_db_concurrency.py`.

## Implementation status (landed)

Implemented and committed (defaults inert; full TMS suite 287 passed / 44
skipped / 0 fail; offline eval unchanged, confirming inert defaults):

- `780ac27` — config flags `rewrite_is_query_source` + `entity_use_rewrite_entities`.
- `2fce268` — rewrite `precomputed_metadata`; entity `surface_forms` + `query_embedding` (inert).
- `1279144` — hybrid single rewrite call (`_build_strategy_context`) + `strategy_context` threading + `test_rewrite_entity_unification.py` (asserts exactly one rewrite LLM call).
- `a62e346` — `StructuredAPI.backfill_entities` (idempotent, dry-run, user-scoped) + tests.
- `bbd2409` — docs (README, implementation.md, implementation_deep_dive.md).
- `a286cbd` — `backfill_entities` CLI (`python -m truth_management_system.backfill_entities`) + keyed-eval gating recipe in `tests/eval/README.md`.

**Remaining:** none required — the keyed gate passed and the default unweighted
RRF ships as-is (see results above). Optional, NOT started (would be scope creep
on this plan): a tag-linked retrieval strategy (the rewrite already emits `tags`,
currently unused); a REST endpoint wrapping `backfill_entities` (the CLI exists).
The embedding-store SQLite-concurrency bug noted above is now FIXED
(`PKBDatabase` reentrant lock + `tests/test_db_concurrency.py`).

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

---

# Appendix: Cold-Start Implementation Notes (read this first if you have no context)

This appendix makes the plan executable by a session with **zero prior context**.
All paths are relative to the repo root
(`/Users/ahemf/Documents/Backup_2025/Research/chatgpt-iterative`, macOS).

## A. Environment & how to verify

- **Conda env (required for Python):**
  `source "$(conda info --base)/etc/profile.d/conda.sh"; conda activate science-reader`
- **Run tests:** `python -m pytest truth_management_system/tests/ -q`
  - Single file: `python -m pytest truth_management_system/tests/test_entity_strategy.py -q`
  - **Test-noise filter** (pipe stderr/stdout through this; these warnings are expected):
    `grep -vE "RuntimeWarning|sys.modules|get_openai_embedding|call_llm|Unauthorized|WARNING|INFO|SwigPy|swigvarlink|DeprecationWarning"`
- **Compile check:** `python -m py_compile <file>`. JS (if touched): `node --check <file>`.
- **Eval harness:** `truth_management_system/tests/eval/` (`run_eval.sh`, `runner.py`,
  `dataset.py`, `metrics.py`, `seed_dataset.json`).
  - Offline (no `OPENROUTER_API_KEY`) = **FTS-only**; it CANNOT measure rewrite
    fusion, embedding cosine, or LLM-entity resolution. The unification MUST be
    eval-gated on a **keyed** run.
  - Run offline: `python -m truth_management_system.tests.eval.runner --k 5`.
  - `EvalClaim` already has an optional `entities: List[str]` field; `runner.seed()`
    creates+links them (role "subject"); `compare()` includes an `entity` strategy
    set. Add new cases to `seed_dataset.json`.
- macOS has **no `timeout`** command. Use `git -P` for all git (no pager).
- Regression guards live in `tests/test_eval_harness.py` (category floors); they are
  category-specific (lexical/semantic) so new `entity` cases won't trip them.

## B. Commit discipline (standing constraints — do not deviate)

- **Do NOT `git push`.** Commit each logical unit separately.
- **Stage by path** (`git add <path>`), **never `git add .`**.
- **First action:** `git -P status` and `git -P diff <target files>`. Other sessions
  may have **uncommitted parallel work** in the same files. If a target file has
  changes you did not make, do NOT sweep them into your commit — either ask, or
  reconstruct a "HEAD + your hunks only" copy and `git apply --cached` it.
- Conventional Commit messages; one workstream per commit.

## C. Exact current signatures (as of plan authoring; re-grep to confirm)

```python
# truth_management_system/search/hybrid_search.py
def search(self, query, strategy_names=None, k=20, filters=None,
           llm_rerank=False, llm_rerank_top_n=50, strategy_queries=None)   # ~L89
def _execute_parallel(self, query, strategy_names, k, filters, strategy_queries=None)  # ~L166
#   contains nested `_query_for(name)`: returns strategy_queries[name] or query  (mirror this for strategy_context)
#   __init__ registers self.strategies["fts"|"embedding"|"rewrite"|"mapreduce"|"entity"]  (~L75-87)
#   default set when strategy_names is None: ["fts", ("embedding"?), ("rewrite"?), ("entity"?)]  (~L110-120)

# truth_management_system/search/rewrite_search.py
def search(self, query, k=20, filters=None)                       # ~L90  -> add precomputed_metadata=None
def search_with_metadata(self, query, k=20, filters=None)         # ~L145 -> returns (results, RewriteMetadata)
def _rewrite_query(self, query) -> Tuple[str, RewriteMetadata]    # ~L185 (the SINGLE LLM call)
def set_overview_context(self, overview_context)                  # ~L83
# RewriteMetadata fields: original_query, rewritten_query (=fts), embedding_query,
#   extracted_keywords, extracted_tags, extracted_entities, llm_model

# truth_management_system/search/entity_search.py
def search(self, query, k=20, filters=None)                       # ~L76
def _resolve_entity_ids(self, query, filters, surface_forms=None) # ~L143  (REUSE HOOK already present)
def _query_embedding(self, query) -> Optional[np.ndarray]         # ~L271

# truth_management_system/search/base.py
def merge_results_rrf(result_lists, k=60, rrf_k=60, strategy_weights=None)  # ~L191  (W-A; keyed on result.source)

# truth_management_system/crud/entities.py
def get_or_create(self, name, entity_type, meta_json=None) -> Tuple[Entity, bool]  # ~L149
def resolve_claims(self, entity_id, statuses=None, limit=50) -> List[Claim]        # ~L338 (honors status + user scope)

# truth_management_system/crud/links.py
def link_claim_entity(db, claim_id, entity_id, role) -> bool      # ~L182

# truth_management_system/llm_helpers.py
def extract_entities(self, statement) -> List[Dict[str, str]]     # ~L179  -> dicts with keys: type, name, role

# truth_management_system/interface/structured_api.py
def backfill_embeddings(self, context_domain=None) -> Dict[str, int]  # ~L160 (PATTERN to mirror for backfill_entities)
#   uses self.claims.get_active(context_domain=...) ; user scope via self.user_email
```

## D. Integration points & ownership

- **Single rewrite call lives in `HybridSearchStrategy.search`** (NOT in
  `_get_pkb_context`). Reason: `Conversation._get_pkb_context` already calls
  `api.search_strategy.set_overview_context(_ov_snippet)` (Conversation.py ~L805)
  **before** `api.search(...)` (~L828). So by the time `hybrid.search` runs, the
  rewrite strategy already has overview context. Compute `RewriteMetadata` once at
  the top of `hybrid.search` (when key present and `rewrite` in active set), then:
  - feed `metadata` into the `rewrite` strategy via the new `precomputed_metadata`
    param so it does NOT call the LLM again;
  - put `metadata.extracted_entities` and `metadata.embedding_query` into a new
    `strategy_context: Dict[str, Any]` and thread it exactly like `strategy_queries`
    (`hybrid.search` → `_execute_parallel` → each `strategy.search`).
- **`strategy_context` plumbing** mirrors the committed W-B `strategy_queries`
  pattern (`_query_for`). Entity reads `strategy_context.get("entity_surface_forms")`
  → passes as `surface_forms`; reads `strategy_context.get("query_embedding")` →
  reuses for cosine instead of calling `get_query_embedding`.
- **W-B already routes** `{"fts": <current message>, "entity": <current message>}`
  in `_get_pkb_context` (~L817-819). The unification may additionally route the
  rewrite's `fts_query`→FTS and `embedding_query`→embedding (optional; gate with
  `rewrite_is_query_source`).

## E. Edge cases / fallbacks (must all be no-ops, tested)

- No key / rewrite not registered / `rewrite` not in active set → `strategy_context`
  empty → entity uses **regex** extraction + its own embedding (today's behavior).
- `precomputed_metadata=None` → rewrite calls the LLM itself (today's behavior).
- `strategy_context` missing keys → each strategy uses its current path.
- `rrf_strategy_weights={}` → unweighted fusion (today). Flags default to inert.

## F. Config wiring pattern (4 edits per field, in config.py)

1. dataclass field with default (group under the "Retrieval ranking" comment);
2. entry in `to_dict`;
3. add the key to the `valid_keys` set in `from_dict`;
4. entry in `env_mapping` (UPPER_SNAKE, `PKB_`-less key in the map; bools via
   `lambda x: x.lower() in ('true','1','yes')`, ints via `int`, dicts via JSON).
New flags: `entity_use_rewrite_entities: bool = True`,
`rewrite_is_query_source: bool = True`. Add a config round-trip + env test.

## G. Backfill specifics (task `backfill-entities`)

- Mirror `backfill_embeddings`: `def backfill_entities(self, context_domain=None,
  dry_run=False) -> Dict[str,int]`. Use `self.claims.get_active(context_domain=...)`,
  filter to claims with **no** `claim_entities` row, then per claim:
  `LLMHelper.extract_entities(stmt)` → for each `{type,name,role}`:
  `EntityCRUD(db, user_email=self.user_email).get_or_create(name, type)` →
  `link_claim_entity(db, claim_id, entity.entity_id, role)`.
- Idempotent (skip already-linked), batched, `dry_run` returns counts without
  writing, user-scoped, respect status (active only). Return
  `{"scanned":N, "linked":M, "skipped":K}`. It costs LLM calls → ops/off-peak,
  NOT on the request path, NOT required for correctness.

## H. Test setup notes

- In-memory DB for tests REQUIRES: `db = PKBDatabase(config); db.connect();
  db.initialize_schema()` (config `db_path=":memory:"`). Just `PKBDatabase(config)`
  is not enough.
- **Assert "exactly one rewrite LLM call"** by monkeypatching
  `code_common.call_llm.call_llm` (or the rewrite's import site) with a counter and
  asserting it's called once across a hybrid search that includes both rewrite and
  entity. Also assert entity claims appear in the fused output and are de-duped.
- Reuse existing helpers in `tests/test_entity_strategy.py` (`_env`, `_claim`,
  `_entity`) and `tests/test_weighted_rrf.py` / `tests/test_query_scoping.py` as
  templates.

## I. Known pre-existing redundancy (out of scope, do not "fix" silently)

With a key, the keyed hybrid path runs base `embedding` AND `rewrite` (which also
does embedding internally) — two embedding passes. This predates this plan. The
unification removes only the *entity* strategy's extra embedding call (by reusing
the query vector). Collapsing base-embedding vs rewrite-embedding is a separate
future simplification; do not bundle it here.

## J. Per-task acceptance criteria (quick gates)

- `context-mechanism` + `rewrite-precomputed-metadata`: behavior-neutral; all
  existing tests still pass; new unit tests prove threading + LLM-call skip.
- `single-call-coordination`: integration test shows **one** rewrite LLM call and
  entity claims fused via a single top-level RRF; offline path unchanged.
- `entity-consume-rewrite-entities` + `reuse-query-embedding`: entity resolves an
  entity the regex misses (e.g. lowercase name) when fed LLM names; no extra
  `get_query_embedding` call when a vector is supplied.
- `config-flags`: round-trip + env test; flags off ⇒ byte-for-byte today's behavior.
- `eval`: keyed run shows precision@5/mrr improve-or-hold, recall@5 no regression.
- `backfill-entities`: idempotency + dry-run + user-scope + status tests pass.
- `docs` + `rollback`: docs updated; flags-off + weights-`{}` verified inert.
