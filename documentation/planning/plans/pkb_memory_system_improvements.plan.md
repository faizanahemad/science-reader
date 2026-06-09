# PKB / TMS Memory System — Improvement Plan

**Status:** M1 (embedding cache + eval harness) complete 2026-06-09 — remainder Draft
**Created:** 2026-06-09
**Scope:** Internal improvements to the Truth Management System (PKB) — retrieval quality, scale, truth-management depth, provenance, lifecycle, and quality/ops. Does **not** cover external access (standalone UI, MCP, REST API) — see `pkb_external_access_ui_mcp_rest_auth.plan.md`.

---

## 1. Background & Motivation

The PKB (`truth_management_system/`, current v0.9 / schema v7) is a SQLite-backed, per-user memory store with an LLM enrichment pipeline (auto-parse type/domain/tags/entities/possible_questions), a cross-type graph (claims ↔ entities ↔ tags ↔ contexts), conflict detection, conversation auto-distillation, and hybrid search (FTS + embedding + RRF). See `documentation/features/truth_management_system/implementation_deep_dive.md` (Intelligence Layer section).

While functionally rich, several mechanisms were built for correctness first and have **scale, cost, and quality** gaps that will bite as the per-user claim count grows. This plan sequences those improvements.

### Key code references
- `truth_management_system/llm_helpers.py` — `check_similarity()`, `_classify_relation()`, `analyze_claim_statement()`, `generate_possible_questions()`, `batch_extract_all()`.
- `truth_management_system/interface/structured_api.py` — `add_claim()` (enrichment orchestration), `add_claims_bulk()`.
- `truth_management_system/search/` — `fts_search.py`, `embedding_search.py`, `hybrid_search.py` (RRF).
- `truth_management_system/crud/claims.py`, `crud/conflicts.py`, `crud/contexts.py`, `crud/entities.py`.
- `truth_management_system/config.py` — `llm_model` (default `google/gemini-3.1-flash-lite-preview`), `embedding_model`.
- `truth_management_system/interface/conversation_distillation.py` — auto-save distillation.

---

## 2. Goals & Success Criteria

| # | Goal | Success criteria |
|---|------|------------------|
| G1 | Make similarity/conflict detection scalable and cheap | No per-add embedding recompute; conflict scan covers the full claim base (not just first 100); add-claim p95 latency unaffected by claim count |
| G2 | Make embedding search scale | Sub-100ms vector retrieval at 10k+ claims/user via an index, not linear scan |
| G3 | Improve retrieval relevance | Recency/decay + confidence weighting in ranking; measurable lift on an eval set |
| G4 | Deepen truth management | Temporal supersession chains + consolidation reduce duplicate/contradictory clutter |
| G5 | Add provenance | Every auto-extracted claim links back to its source conversation/message |
| G6 | Lifecycle correctness | Expiry runs on a schedule, not only on query traffic |
| G7 | Cost & quality guardrails | Enrichment LLM calls batched/debounced; a retrieval eval harness exists |
| G8 | Reinforcement & decay | Re-affirmed claims stay fresh/rank higher; untouched claims decay and go `dormant`; a TTL that resets on reinforcement, driven by a schema-backed `last_reinforced_at` |

### Non-goals
- External API/UI/MCP work (separate plan).
- Replacing SQLite (stay on SQLite + a vector index unless eval forces a move).
- Multi-tenant/sharded storage.

---

## 3. Workstreams, Tasks & Sequencing

Sequenced so early work de-risks later work. Each task is independently shippable.

### Workstream A — Embedding cache & scalable similarity (G1) — **do first**

**Problem (original):** `LLMHelpers.check_similarity(new, existing_claims, threshold)` calls `get_document_embedding()` for each existing claim *on every add*, and `add_claim()` only passes `existing[:100]`. This is O(N) LLM/embedding calls per add and silently ignores claims beyond the first 100.

> **Correction (verified 2026-06-09):** the `claim_embeddings` table **already exists** in `schema.py`, and `EmbeddingStore` (`search/embedding_search.py`) already persists/caches/ensures embeddings — but only the *search* path used it. The add-path `check_similarity` bypassed the cache and recomputed every existing claim's embedding. So A1's storage layer was already present; the real work was wiring the cache into the add/edit path. **No schema migration was needed.**

- **A1. Persist claim embeddings.** ~~Add an `embedding BLOB`…~~ Table already present. **DONE (2026-06-09):** embeddings are now populated at add time (`add_claim` → `EmbeddingStore.compute_and_store` after insert) and refreshed on edit when `statement` changes. `EmbeddingStore.get_embedding` is now **model-aware** (`expected_model` param; returns None on `model_name` mismatch so stale-model vectors recompute), addressing the model-drift risk. `StructuredAPI.backfill_embeddings(context_domain=None)` added for one-off population. Behind `config.embedding_cache_enabled` (default True); all cache writes are best-effort/non-fatal.
- **A2. Refactor `check_similarity`** to read cached vectors instead of recomputing; embed only the *new* statement. **DONE (2026-06-09):** `check_similarity(..., cached_embeddings=None)` reuses a `claim_id → vector` map; `add_claim` builds it via `EmbeddingStore.ensure_embeddings(existing)` (which fills misses in parallel and stores them), so repeat adds hit the cache. Backward compatible (falls back to recompute when no map supplied).
- **A3. Remove the `[:100]` cap** in `add_claim()`. **DONE (interim, 2026-06-09):** replaced the hardcoded `[:100]` with `config.conflict_scan_limit` (default 500; `<= 0` = scan all). The full removal of any cap is unblocked once the ANN index (Workstream B) makes the scan sub-linear.
- **Tests (2026-06-09):** `truth_management_system/tests/test_embedding_cache.py` (3 network-free tests: model-aware reads, add-path cache population, `check_similarity` cache reuse). Regression: `test_search.py` + `test_crud.py` = 26 passing.
- **Challenge/alternative:** if storing vectors in SQLite bloats the DB, use a separate vector store (see B). Feature flag `embedding_cache_enabled` is now present.

### Workstream B — ANN vector index (G2)

**Problem:** embedding search currently does linear cosine scans (`search/embedding_search.py`).

- **B1. Choose an index.** Options: `sqlite-vss`/`sqlite-vec` (keeps everything in SQLite, simplest ops), `hnswlib`/`faiss` (faster, separate file per user), or pgvector (only if migrating off SQLite — out of scope). **Recommendation:** `sqlite-vec` to stay single-file per user.
- **B2. Build/maintain the index** from the A1 embedding cache; update on add/edit/delete.
- **B3. Wire `embedding_search.py`** to query the index; keep the linear path as a fallback behind a flag.
- **B4. Benchmark** at 1k/10k/50k claims; record in the eval harness (G7).
- **Challenge:** per-user index lifecycle (create/rebuild/corruption recovery). Mitigation: rebuild-on-startup if missing + checksum.

### Workstream C — Ranking: recency, decay & confidence (G3)

**Problem:** `hybrid_search.py` RRF-merges FTS + embedding (`base.py:merge_results_rrf`, `score = Σ 1/(rank + 60)`) but does not weight by recency or confidence; old and new claims at the same rank tie. RRF scores are un-normalized and tiny (~0.016–0.03).

> **Status (2026-06-09): C1, C1a, C1b, C2, C3 DONE.** `apply_recency_confidence_rerank(results, config, now=None)` added to `search/base.py` and called in `HybridSearchStrategy.search` once after `merge_results_rrf` (before LLM rerank/truncation). Weights live in `PKBConfig` (`recency_rerank_enabled`, `w_recency`, `w_confidence`, `default_confidence`, `recency_half_life_days`, `half_life_by_type`, `recency_grace_days`) with `to_dict`/`from_dict`/env wiring. **Defaults (`w_recency = w_confidence = 0`) reproduce current ranking EXACTLY** (`x ** 0 == 1.0`), verified by the unchanged harness baseline + 50 passing tests. Age reads `last_reinforced_at` with `updated_at` fallback (so it works before Workstream H lands the column). Pinned override + new-claim grace floor + per-type half-life all implemented. Unit tests: `tests/test_recency_rerank.py`. Harness validation: at `w_recency = 1.0` (half-life 60d) the `recency` and `conflict` category MRR rise from 0.500 → **1.000** with `lexical`/`temporal`/`semantic` and overall recall unchanged. **C2 remainder:** status exclusion (`expired`/`retracted`/`superseded`/`dormant`) handled by `SearchFilters`; explicit contested down-ranking **DONE 2026-06-09** via `contested_penalty` (default `1.0` = no-op; multiplies a contested claim's re-rank score; fast-path no-op return also checks it). Tests in `tests/test_recency_rerank.py` (11 total).

- **C1. Post-fusion recency + confidence re-weight.** Apply decay **once, after** `merge_results_rrf` (not inside each strategy — avoids double-counting), as a multiplicative, exponent-weighted re-rank of the RRF score:
  ```
  age_days = (now - (last_reinforced_at or updated_at)) / 86400
  recency  = 0.5 ** (age_days / half_life_days)      # 1.0 fresh -> 0.5 at one half-life
  conf     = claim.confidence or default_confidence
  final    = rrf_score * (recency ** w_recency) * (conf ** w_confidence)
  ```
  Multiplicative-with-exponents preserves RRF's rank-fusion semantics while staying tunable; `w_recency = 0` reproduces today's behavior exactly. `recency` reads `last_reinforced_at` (the schema column added in Workstream H), falling back to `updated_at`. Implementation: a post-merge step in `HybridSearchStrategy.search`, or extend `merge_results_rrf` to accept an optional `rerank_fn`. `SearchResult` already carries the full `Claim` (so `updated_at`/`confidence`/`meta_json` are available).
- **C1a. Per-type half-life.** `half_life_by_type` map in `PKBConfig` (facts/preferences long or infinite; observations/tasks short), with an optional per-claim override.
- **C1b. Pinned override + new-claim grace.** If `meta_json.pinned` (existing pin), force `recency = 1.0`. Floor `recency` for the first N days so fresh claims aren't buried by long-reinforced ones (anti rich-get-richer).
- **C2. Status-aware weighting** — down-rank `contested`; exclude `expired`/`retracted`/`dormant` from default retrieval (verify current exclusion set).
- **C3. Expose weights** in `PKBConfig` (`w_recency`, `w_confidence`, `half_life_by_type`, `default_confidence`, `recency_grace_days`) so the eval harness (G1-task) can sweep them. **Defaults must reproduce current ranking** (i.e. `w_recency = 0`) until the harness validates a change.

### Workstream D — Truth management depth (G4)

**Problem:** contradictions become a flat `ConflictSet` (open/resolved/ignored) with no temporal chain; near-duplicates accumulate.

> **Status (2026-06-10): D1 + D2 + D3 DONE.** Schema **v9** adds the `claim_links` table (`from_claim_id`/`to_claim_id`/`link_type`, `UNIQUE(from,to,type)`, endpoint + type indexes); `_migrate_v8_to_v9` is defensive/idempotent (verified on a copy of the real DB, v6→v9, 49 claims preserved). `crud/links.py` gains `link_claims`/`unlink_claims`/`get_outgoing_links`/`get_incoming_links`/`get_supersession_head` (cycle+depth guarded); direction = newer `from` supersedes older `to`. `StructuredAPI.supersede_claim(new, old, notes)` creates the link + moves old→`superseded` (guards self/missing; idempotent link). Two confirmed entry points: `add_claim(..., supersedes=id|list)` and `resolve_conflict_set(..., winning_claim_id=W)` (records `W -supersedes-> loser` for each loser). Chain-head retrieval is automatic — `superseded` is absent from `default_search_statuses` (`[active, contested]`), so the old claim drops out of search while the active head stays; H4 already blocks reinforcing a superseded claim. **Decision:** used the existing `superseded` status (semantically "replaced by a newer claim", and what `ConflictCRUD.resolve` already sets) rather than the plan's original `historical` wording. **Deferred:** the distiller has no contradiction detector (only duplicate/related by score), so the automatic distiller→supersede proposal is a follow-up; the API + confirmation surfaces are ready for it. Tests: `tests/test_supersession.py` (12). **D2/D3 DONE 2026-06-10:** on-demand consolidation (`search/consolidation.py` union-find clustering) — `find_consolidation_candidates`/`consolidate_claims` merge near-duplicate claims (tag union + D1 supersede) and `find_entity_duplicates`/`merge_entities` dedupe entity variants into a canonical entity with `meta_json.aliases`. REST under `/pkb/consolidation/*` and `/pkb/entities/{duplicates,merge}`. Tests: `tests/test_consolidation.py` (12).

- **D1. Supersession links. ✅ DONE 2026-06-09.** Add a typed claim-to-claim link (`supersedes`/`superseded_by`) in `crud/links.py`; when a new claim contradicts an old one and the user confirms, mark the old `superseded` and link them. Retrieval prefers the head of the chain.
- **D2. Consolidation job. ✅ DONE 2026-06-10.** On-demand pass that clusters near-duplicates (using A1 vectors) and proposes merges via the existing proposal modal flow. Pure clustering in `search/consolidation.py` (`cluster_near_duplicate_claims`, union-find cosine, default threshold `0.95`); `StructuredAPI.find_consolidation_candidates` proposes (with `suggested_keep_id` = highest confidence, tie newest) and `consolidate_claims(claim_ids, keep_id)` executes — unions the duplicates' tags onto the keeper, then supersedes the rest via the D1 `supersede_claim` (reversible). REST: `GET /pkb/consolidation/candidates`, `POST /pkb/consolidation/merge`.
- **D3. Canonical entity resolution. ✅ DONE 2026-06-10.** Dedupe entity variants (`john` vs `John Smith`) into a canonical entity with aliases. `cluster_entity_variants` + `entity_name_similarity` (difflib ratio + token-subset boost) detect variants per `EntityType` (default threshold `0.85`); `StructuredAPI.find_entity_duplicates` proposes and `merge_entities(source, target)` records the source name in `target.meta_json.aliases` then re-points claim links via `EntityCRUD.merge`. REST: `GET /pkb/entities/duplicates`, `POST /pkb/entities/merge`. Config knobs: `consolidation_similarity_threshold`, `entity_dedup_threshold`. Tests: `tests/test_consolidation.py` (12).
- **Alternative:** start D1 only (highest value); D2/D3 are follow-ups.

### Workstream E — Provenance (G5)

> **Status (2026-06-10): E1 + E2 DONE.** Provenance is stored in `meta_json` under a `source` object (`{type, conversation_id, message_id, distilled}`) — no schema migration, matching the `pinned`/text-ingestion conventions. `add_claim` accepts `source_conversation_id`/`source_message_id`/`source_type` (kwargs), merges them into `meta_json` (preserving existing keys), and appends a `source:conversation` tag (E2) when a conversation id is present. The `ConversationDistiller` threads provenance end-to-end: `MemoryUpdatePlan` carries the ids, `extract_and_propose` accepts them (the `/pkb/distill` route passes request `conversation_id` + optional `message_id`), and `execute_plan`→`_execute_action` forwards them to `add_claim`. Read path: `StructuredAPI.get_claim_provenance(claim_id)` → `{claim_id, source_type, conversation_id, message_id, distilled, created_at}` (`source_type` = `"manual"` when unsourced), exposed at `GET /pkb/claims/<id>/provenance` for the claim card's "why do I know this?". Tests: `tests/test_provenance.py` (7).

- **E1. Source linking. ✅ DONE 2026-06-10.** On auto-distilled claims, store `source_conversation_id` + `source_message_id` (reuse cross-conversation reference infra; see `documentation/features/cross_conversation_references/`). Surface "why do I know this?" in the claim card.
- **E2. Distillation tagging. ✅ DONE 2026-06-10.** Already tags `create-simple`; extend with a `source:conversation` provenance tag.

### Workstream F — Lifecycle (G6)

Today `expire_stale_claims()` (`utils.py:154`) is a **hard TTL only**: it flips `active` → `expired` when `valid_to < now`, and runs lazily (search/init). Workstream F adds a scheduled sweep and a **soft TTL** driven by decay.

> **Status (2026-06-10): F1 + F2 + F3 + F4 ALL DONE.** F1 (scheduled background sweep) and F4 (notifications) landed 2026-06-10: `utils.run_lifecycle_sweep` (unconditional expiry+dormancy), `truth_management_system/scheduler.py` (config-gated idempotent daemon thread, wired from `server.py` via `endpoints.pkb.start_pkb_background_jobs`), `StructuredAPI.run_lifecycle_sweep` + `get_lifecycle_notifications`, REST `POST /pkb/sweep` + `GET /pkb/notifications`, config knobs `sweep_interval_seconds`/`notify_expiry_within_days`. Tests: `tests/test_lifecycle_sweep.py` (8). Prior (2026-06-09): `utils.decay_dormant_claims(db, config, user_email=None, now=None)` flips `active`→`dormant` when `0.5 ** (age/half_life) < config.dormancy_threshold`, reading `last_reinforced_at` (fallback `updated_at`) and reusing C's `recency_half_life_days`/`half_life_by_type`. Skips pinned, `config.dormancy_exempt_types`, and non-positive half-lives. **Inert by default** (`dormancy_threshold == 0` short-circuits). Wired into `maybe_expire_claims(db, user_email, config)` (lazy, alongside hard-TTL expiry, same `EXPIRY_CHECK_INTERVAL` guard) and exposed as `StructuredAPI.run_decay_sweep()` for a future F1 job. F3: `ClaimStatus.DORMANT` already added (H); `default_search_statuses` omits it, `all_visible_statuses` now includes it (browsable/revivable). Config knob `dormancy_exempt_types` (to_dict/from_dict). Tests: `tests/test_decay.py` (9).

- **F1. Scheduled sweep. ✅ DONE 2026-06-10.** Run `expire_stale_claims()` (hard TTL) + the dormancy decay on a periodic background job so expiry isn't traffic-dependent. `utils.run_lifecycle_sweep(db, config, user_email, now)` runs both unconditionally (returns `{expired, dormant}`); new `truth_management_system/scheduler.py` runs it on a config-gated, idempotent daemon thread (`start_lifecycle_sweep_scheduler`/`stop`/`is_running`, gated by `sweep_interval_seconds <= 0`); `endpoints.pkb.start_pkb_background_jobs()` is called from `server.py` startup; `StructuredAPI.run_lifecycle_sweep()` + `POST /pkb/sweep` give an on-demand trigger. The lazy `maybe_expire_claims` path remains as fallback.
- **F2. Soft-TTL decay pass. ✅ DONE 2026-06-09.** Compute `freshness = 0.5 ** (age / half_life)` from `last_reinforced_at` (Workstream H column). If `freshness < dormancy_threshold` AND `status == active` AND not pinned AND type is decayable → flip to a new **`dormant`** status. Do **not** delete — keep retrievable but heavily down-ranked (the C1 `recency` term already buries it). Reinforcing a dormant claim (Workstream H) revives it to `active`. This makes the sweep a second consumer of `last_reinforced_at` — the same field C1 ranks on (one timestamp, two consumers).
- **F3. Status constant. ✅ DONE 2026-06-09.** Add `dormant` to `ClaimStatus` (constants.py) and exclude it from default search statuses (coordinate with C2) — done; also added to `all_visible_statuses` so dormant claims stay browsable/revivable.
- **F4. Expiry/dormancy notifications. ✅ DONE 2026-06-10.** `StructuredAPI.get_lifecycle_notifications(within_days, limit)` returns `soon_to_expire` (active `task`/`reminder` claims with `valid_to` in the next `within_days`) and `newly_dormant` (claims flipped to `dormant` within the last `within_days`, via the `updated_at` stamp the decay sweep sets). Surfaced at `GET /pkb/notifications`. Config knob `notify_expiry_within_days` (7).

### Workstream G — Cost & quality guardrails (G7) — **partially parallelizable**

- **G1-task. Retrieval eval harness. ✅ DONE 2026-06-09.** A labeled set of (query → expected claim ids) per strategy; a script that reports recall@k / MRR. Gates C/B changes. Implemented under `truth_management_system/tests/eval/`: `metrics.py` (recall@k, precision@k, reciprocal rank, MRR, aggregation), `dataset.py` + `seed_dataset.json` (a ~46-claim persona corpus with lifecycle state, 38 cases tagged by category: lexical/semantic/multi/temporal/recency/conflict/hard_negative/scoped/lifecycle), `runner.py` (`EvalRunner` seeds a throwaway PKB — applying lifecycle overrides + an expiry sweep — and scores each strategy config via `HybridSearchStrategy`, reporting per-case, aggregate, and **per-category** `recall@k`/`precision@k`/`mrr`; CLI: `python -m truth_management_system.tests.eval.runner [--dataset PATH] [--k N] [--json] [--verbose]`, plus a portable `run_eval.sh` wrapper and `README.md`). Network-free for FTS (embedding/hybrid auto-skipped without `OPENROUTER_API_KEY`). `tests/test_eval_harness.py` guards the lexical subset (recall@5 ≥ 0.8, MRR ≥ 0.7), the lexical-vs-semantic gap (≥ 0.4), and existing-capability `scoped`/`lifecycle` recall; the room-to-grow categories are deliberately not floored. Network-free FTS baseline (k=5): overall precision=0.537/recall=0.763/mrr=0.664; semantic recall=0.10, recency mrr=0.50, conflict mrr=0.50 — the headroom embeddings + Workstreams C/D/H must close. C3/H4 weight sweeps plug into `EvalRunner.evaluate(strategy_sets=...)`.
- **G2-task. Batch enrichment.** `analyze_claim_statement` + `generate_possible_questions` are per-claim LLM calls; route single adds through a short debounce/batcher (reuse `batch_extract_all`) to cut cost. Keep latency acceptable for interactive adds (only batch background/bulk paths).
- **G3-task. Export/import + audit log** per user (JSON export of claims/links/contexts; append-only audit of add/edit/delete).

### Workstream H — Reinforcement & decay ("use it or lose it" memory) (G8)

**Goal:** claims that the user keeps re-affirming stay fresh and rank higher; claims that go untouched decay and eventually go dormant — a TTL that **resets on reinforcement**. This is the bridge between C (ranking decay) and F (lifecycle): both read the single `last_reinforced_at` timestamp this workstream introduces. `confidence` (belief it is true) and freshness (how active/current) are kept **separate but linked** — a claim can be true-but-stale.

> **Status (2026-06-09): H1 + H2 + H3 + config DONE (and F2 decay sweep DONE).** Schema bumped to **v8** (`schema.py`): `claims.last_reinforced_at TEXT` + `claims.reinforcement_count INTEGER NOT NULL DEFAULT 0`. `_migrate_v7_to_v8` (`database.py`) adds the columns, backfills `last_reinforced_at = updated_at`, and creates `idx_claims_last_reinforced` — verified on a **copy** of the real `storage/users/pkb.sqlite` (v6→v8, 49 claims backfilled, count preserved, idempotent re-init). The index is created **after** the column-reconciliation block (not in base DDL, which runs before migrations). `Claim` model + `CLAIM_COLUMNS` extended (generic `from_row`/`to_values`). `ClaimStatus.DORMANT` added (forward-compat for F2). `StructuredAPI.reinforce_claim(claim_id, strength=1.0)` implements the transition below incl. the H4 contested/superseded safeguard; the shared math lives in `_build_reinforcement_patch`. Config knobs (`PKBConfig`): `reinforce_alpha=0.1`, `reinforce_ttl_days_by_type={}`, `reinforce_on_duplicate="off"`, `dormancy_threshold=0.0` — all **inert by default**. **H3 signals wired:** (1) `add_claim` near-duplicate branch reinforces the existing claim instead of creating a duplicate when `reinforce_on_duplicate` is `reinforce`/`reinforce+warn` (default `off` = unchanged); (2) the `ConversationDistiller` proposes a user-confirmed `reinforce` action for restatements (was a silent skip); (3) `pin_claim` reinforces on `pin=True` (skipped on unpin / contested / superseded). The Workstream C recency re-rank now reads the real `last_reinforced_at`. Tests: `tests/test_reinforcement.py` (17). **F2 (the dormancy sweep that consumes `last_reinforced_at` and which `reinforce_claim` revives) is now also DONE** — see Workstream F.

**Storage — schema-backed (NOT meta_json). Requires a schema migration (v8).** Reinforcement state must be queryable/sortable for the C1 recency sort and the F2 decay sweep, so it lives in indexed columns, not `meta_json`:

- **H1. Schema v8 migration.** Bump `SCHEMA_VERSION` 7 → 8 in `schema.py` and add an incremental migration in `database.py` (follow the existing v2→v7 `ALTER TABLE` pattern). New columns on `claims`:
  - `last_reinforced_at TEXT` — clock decay measures from.
  - `reinforcement_count INTEGER NOT NULL DEFAULT 0`.
  - (optional, phase 2) `last_accessed_at TEXT`, `access_count INTEGER DEFAULT 0` for implicit retrieval reinforcement.
  - Add `CREATE INDEX idx_claims_last_reinforced ON claims(last_reinforced_at)` for the decay sweep / recency sort.
  - **Backfill:** set `last_reinforced_at = updated_at` for existing rows during migration.
  - Update `Claim` model (`models.py`), `Claim.from_row`, and any insert/select column lists accordingly. Test the migration on a copy of `storage/users/pkb.sqlite`.
- **H2. `reinforce_claim(claim_id, strength=...)` mutator** (`StructuredAPI`): the single state transition —
  ```
  last_reinforced_at = now
  reinforcement_count += 1
  updated_at = now
  confidence = confidence + (1 - confidence) * alpha        # asymptotic to 1.0, diminishing returns
  if claim_type in TTL_TYPES and valid_to:  valid_to = now + ttl_for(type)   # extend hard TTL
  if status == 'dormant':  status = 'active'                 # revive
  ```
- **H3. Reinforcement signals (wire-ups), strongest → weakest. ✅ DONE 2026-06-09.**
  - **Explicit restatement (primary hook):** in `add_claim`, the `check_similarity` `duplicate` branch (sim > 0.95) currently only warns. Route it to `reinforce_claim(existing_id)` instead of creating a near-duplicate (configurable: reinforce / reinforce+warn / create). Reuses the embedding-cache work from Workstream A.
  - **Confirmation/edit/pin:** accepting a distiller proposal, editing, or pinning reinforces.
  - **Distiller:** `ConversationDistiller.extract_and_propose` proposes a **"reinforce"** action (alongside create/merge/supersede) when a candidate restates an existing claim.
  - **Implicit retrieval use (phase 2):** claim returned by `pkb_search` *and* used in the answer → small capped boost (needs `last_accessed_at`/access log).
- **H4. Safeguards.**
  - Reinforcing a `contested`/`superseded` claim triggers conflict review, not a silent boost (don't resurrect false claims).
  - Cap implicit-retrieval boost + apply the C1b new-claim grace floor to avoid rich-get-richer feedback loops.
  - All weights (`alpha`, `TTL_TYPES`, `ttl_for`, `dormancy_threshold`) in `PKBConfig`; defaults chosen so behavior is inert until enabled, and swept by the eval harness (G1-task).

---

## 4. Suggested Milestones

1. **M1 (foundation): ✅ COMPLETE 2026-06-09.** A1 + A2 (embedding cache) + G1-task (eval harness) all done. Unlocks everything else and immediately cuts add-claim cost; B and C are now measurable against the harness.
2. **M2 (scale):** B1–B4 (ANN index) + A3 (remove 100 cap).
3. **M3 (relevance):** **C1–C3 ranking re-rank DONE 2026-06-09** (config-gated, default-off). **H1 (schema v8) + H2 (`reinforce_claim`) + H3 (signal wire-ups) DONE 2026-06-09** — the re-rank reads the real `last_reinforced_at`, and `add_claim`/distiller/pin now update it in production flows. Next: re-validate the recency sweep against the M1 harness once reinforcement has populated `last_reinforced_at` divergent from `updated_at`.
4. **M4 (truth depth):** **D1 (supersession) DONE 2026-06-09** + **C2 (contested down-ranking) DONE** + **E1/E2 (provenance) DONE 2026-06-10**. **F2 dormancy decay + F3 status DONE 2026-06-09** (the second consumer of `last_reinforced_at`).
5. **M5 (lifecycle & polish):** **D2/D3 (consolidation + entity resolution) + F1/F4 (scheduled sweep + notifications) DONE 2026-06-10.** Remaining: G2-task, G3-task, H4 safeguards.

---

## 5. Risks & Challenges

- **Schema migrations:** Workstream **H (v8)** adds `last_reinforced_at` / `reinforcement_count` columns + index to `claims`; D1 adds claim-to-claim link rows. (Note: A1's `claim_embeddings` table already existed, so A1 needed **no** migration.) Reuse the existing `db.initialize_schema()` incremental migration pattern (v2→v7 already handled) — bump `SCHEMA_VERSION`, add an `ALTER TABLE` migration step, backfill (`last_reinforced_at = updated_at`), and update `Claim`/`Claim.from_row` + insert/select column lists. Test the migration on a **copy** of `storage/users/pkb.sqlite`.
- **Embedding model drift:** if `embedding_model` changes, cached vectors are invalid — store the model id and re-embed lazily.
- **Cost vs latency tradeoff** in batching (G2-task): never batch the interactive Auto-fill path; only background/bulk.
- **Per-user vector index ops** (B): corruption/rebuild handling needed.
- **Eval data:** harness is only as good as its labels; seed from real anonymized queries.

---

## 6. Files Likely Touched

- `truth_management_system/schema.py`, `config.py`, `database.py` (v8 migration), `models.py` (Claim + from_row), `constants.py` (`dormant` status)
- `truth_management_system/llm_helpers.py`
- `truth_management_system/interface/structured_api.py` (`reinforce_claim`), `conversation_distillation.py`
- `truth_management_system/search/embedding_search.py`, `hybrid_search.py`, `base.py` (RRF re-weight)
- `truth_management_system/utils.py` (decay/dormancy sweep)
- `truth_management_system/crud/claims.py`, `links.py`, `entities.py`, `conflicts.py`
- `truth_management_system/tests/` (+ new `tests/eval/`)
- `endpoints/pkb.py` (provenance fields, export/import endpoints)
- `interface/pkb-manager.js`, `interface/interface.html` (provenance display, consolidation/merge UI)
- Docs: update `documentation/features/truth_management_system/implementation_deep_dive.md` + `README.md` per change.

---

## 7. Open Questions

1. Acceptable add-claim latency budget for interactive adds (caps how much enrichment stays synchronous)?
2. Is a separate vector store acceptable, or must everything stay in the single per-user SQLite file?
3. Should consolidation/merge be fully automatic (with undo) or always user-confirmed via the proposal modal?
4. Retention policy for `historical`/`expired` claims — keep forever, or archive after N days?
