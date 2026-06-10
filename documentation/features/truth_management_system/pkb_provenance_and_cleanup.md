# PKB Provenance, Origin & Memory Cleanup

**Two-axis claim provenance, auto/curated origin for entities & tags, tag merge, LLM-assisted dedup, a one-shot Memory Cleanup orchestrator, lifecycle-change notifications, reconfirmation upgrade, and audit coverage.**

Implements the `pkb_provenance_and_cleanup` plan (workstreams W1–W11). Backend, REST and UI are complete.

## Motivation

As the knowledge base grows, the user needs to know *where* each memory came from and *how much to trust it*, and needs cheap ways to keep the base tidy. Provenance answers "did I tell you this, or did you infer it?"; origin answers "did I create this tag/entity or did the machine?"; and Memory Cleanup bundles the maintenance actions behind one button.

## Two-axis claim provenance (W1–W4)

Every claim records provenance under `meta_json.source` as **two orthogonal axes** (no schema migration — stored in `meta_json`):

- **channel** — where the claim entered: `manual | chat | ingest | import`. Legacy values are normalized (`chat_distillation→chat`, `text_ingestion→ingest`, `migration→import`); the legacy free-form `type` is preserved for back-compat. `referenced` is **not** a channel (it is a transient retrieval-time injection label).
- **derivation** — the epistemic basis: `stated` (user said it ~verbatim) | `extracted` (rephrased from the user's own words) | `inferred` (a conclusion the user never explicitly stated).

Key code: `constants.ProvenanceChannel` / `Derivation`; `utils.set_provenance` / `get_provenance` / `infer_legacy_provenance`.

**Behavior:**
- **Defaults** (`add_claim`): manual UI adds → `manual`/`stated`; distilled → `chat`/`extracted`. The distiller's extraction LLM labels each candidate `stated|extracted|inferred` (both relaxed and aggressive prompts); text ingestion → `ingest`/`extracted`.
- **Inferred is trusted less:** its confidence is capped at `config.inferred_confidence_cap` (0.4) at add time, and it is down-ranked in retrieval by `config.inferred_rerank_penalty` (0.1 → ×0.9 score) in `apply_recency_confidence_rerank`. Corpora without inferred claims are unaffected.
- **Reconfirmation upgrade (W4):** when the user explicitly restates an inferred claim, `reinforce_claim(..., upgrade_derivation=True)` promotes it `inferred→stated` and lifts the cap. The distiller's duplicate→reinforce path passes this flag.
- **Backfill:** `StructuredAPI.backfill_provenance()` (idempotent) infers axes for pre-feature claims (`manual→stated`, else `extracted`).

## auto vs curated origin for entities & tags (W5)

Index objects record `meta_json.origin = "auto" | "curated"` — a cleanup/trust signal, **not** an epistemic claim, and (by decision) it does **not** gate dedup.

- Enrichment-created (via `get_or_create_*_by_name`) → `auto`.
- User-created (facade `add_entity`/`add_tag`) → `curated`.
- `StructuredAPI.backfill_origin()` marks pre-existing rows `curated` (history treated as user-trusted; idempotent).

## Tag merge (W6)

Tags previously had only delete (which cascades and loses claim links). `TagCRUD.merge(source, target)` is the non-lossy counterpart: re-points `claim_tags` (INSERT OR IGNORE), re-parents the source's children to the target (lifting the target out from under the source first to avoid a self-cycle), then deletes the source. Facade `find_tag_duplicates` / `merge_tags` (records the source name in `target.meta_json.aliases`). Mirrors the entity dedup/merge flow.

## LLM-assisted overlap judging (W7)

The cheap prefilter (embedding cosine for claims, name similarity for entities/tags) can be confirmed by an LLM verification pass before a merge is offered. `LLMHelpers.judge_duplicates(items, kind)` returns `{duplicate, canonical, reason}` (fail-safe `False`). `find_consolidation_candidates` / `find_entity_duplicates` / `find_tag_duplicates` accept `use_llm` (defaults to `config.dedup_llm_verify`, **off**); when on, only LLM-confirmed clusters survive, annotated `llm_verified` + `llm_canonical`.

## Memory Cleanup orchestrator (W9)

`StructuredAPI.run_memory_cleanup(apply=False, use_llm=None)` — one call that:
1. runs **safe** maintenance: the lifecycle sweep (hard-TTL expiry + soft-TTL dormancy) and a best-effort overview refresh;
2. gathers **dedup proposals** for claims, entities and tags.

With `apply=False` (default) it returns a review report without mutating; with `apply=True` it merges each proposed cluster by its suggested keeper. Report shape: `{swept, overview_refreshed, claims/entities/tags: {clusters, merged}, applied}`. REST: `POST /pkb/cleanup`.

## Lifecycle-change notification (W8)

When an add/extract supersedes an existing claim, the change is surfaced so the user is told after the fact. `ActionResult.metadata["lifecycle_changes"]` carries `{claim_id, statement, old_status, new_status, change, by_claim_id}`; `DistillationResult.lifecycle_changes` aggregates them across executed actions.

## Audit coverage (W10)

Merges and provenance changes are now audited via the append-only `audit_log`: `consolidate_claims` (action `merge`), `merge_entities` / `merge_tags` (action `merge`, detail `merged_from`+aliases), and the reinforce derivation upgrade (action `derivation_change`). Read via `GET /pkb/audit`.

## UI (W11)

In `interface/interface.html` + `interface/pkb-manager.js` (consumes the REST surface; no new backend):
- **Provenance badge** on each claim card — `derivation` (stated=green / extracted=blue / inferred=amber) with a `channel` tooltip (`renderProvenanceBadge`).
- **Origin badge** (auto/curated) on entity and tag cards (`renderOriginBadge`).
- **Maintenance tab** (PKB modal Tab 9) — the Memory Cleanup home: an **Analyze** button (non-destructive) renders the sweep counts + duplicate claim/entity/tag clusters (with an "LLM✓" marker when LLM verification is on), and **Apply suggested** merges them. An **LLM verify** checkbox maps to `use_llm`. Backed by `runMemoryCleanup` / `renderCleanupReport`.
- **Lifecycle toast** (`showLifecycleChanges`) when an add supersedes earlier memories; the add-claim REST response returns `lifecycle_changes`.

## Configuration

| Flag | Default | Purpose |
|------|---------|---------|
| `inferred_confidence_cap` | 0.4 | Confidence ceiling for `inferred` claims |
| `inferred_rerank_penalty` | 0.1 | Score reduction for `inferred` claims in re-rank (0 = off) |
| `dedup_llm_verify` | False | LLM verification pass over dedup clusters |
| `entity_dedup_threshold` | 0.85 | Name-similarity cutoff (entities & tags) |
| `consolidation_similarity_threshold` | 0.95 | Embedding cutoff for claim dedup |

## REST endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/pkb/tags/duplicates` | Tag name-variant clusters (query: threshold) |
| POST | `/pkb/tags/merge` | Merge tag `{source_id, target_id}` |
| POST | `/pkb/cleanup` | Memory Cleanup `{apply?, use_llm?}` |

(plus the existing `/pkb/consolidation/*`, `/pkb/entities/duplicates|merge`, `/pkb/sweep`, `/pkb/audit`.)

## Files modified

- `truth_management_system/constants.py` — `ProvenanceChannel`, `Derivation`, `MetaJsonKeys.ORIGIN*`
- `truth_management_system/utils.py` — `set_provenance` / `get_provenance` / `infer_legacy_provenance`
- `truth_management_system/config.py` — `inferred_confidence_cap`, `inferred_rerank_penalty`, `dedup_llm_verify`
- `truth_management_system/search/base.py` — inferred down-rank in `apply_recency_confidence_rerank`
- `truth_management_system/search/consolidation.py` — `cluster_tag_variants`
- `truth_management_system/crud/tags.py` — `TagCRUD.merge`
- `truth_management_system/crud/links.py` — `origin=auto` on auto-created tags/entities
- `truth_management_system/llm_helpers.py` — `judge_duplicates`
- `truth_management_system/interface/structured_api.py` — provenance wiring, `backfill_provenance`/`backfill_origin`, `_with_curated_origin`, `find_tag_duplicates`/`merge_tags`, `_verify_dedup_clusters`, `run_memory_cleanup`, lifecycle_changes, audit hooks, `reinforce_claim(upgrade_derivation)`
- `truth_management_system/interface/conversation_distillation.py` — derivation labeling, lifecycle_changes aggregation
- `truth_management_system/interface/text_ingestion.py` — ingest channel/derivation
- `endpoints/pkb.py` — `/pkb/tags/duplicates`, `/pkb/tags/merge`, `/pkb/cleanup`; add-claim response returns `lifecycle_changes`
- `interface/interface.html` — Maintenance tab (Tab 9) with Analyze/Apply + LLM-verify
- `interface/pkb-manager.js` — provenance/origin badges, `runMemoryCleanup`/`renderCleanupReport`, lifecycle toast
- Tests: `test_provenance_axes.py`, `test_provenance_distiller.py`, `test_inferred_rerank.py`, `test_reconfirmation_upgrade.py`, `test_origin.py`, `test_tag_merge.py`, `test_dedup_llm_verify.py`, `test_lifecycle_notification.py`, `test_memory_cleanup.py`, `test_audit_coverage.py`

## Compaction Extension (v12)

`run_memory_cleanup` was extended in schema v12 to also:
1. **Expire short-term memories** (from `pkb_short_term_memory` table) — hard delete past `expires_at`
2. **Identify stale long-term claims** for archival — `last_accessed_at` > 90 days, confidence < 0.5, not pinned
3. **Archive stale claims** on `apply=True` — sets `status = 'archived'`

The cleanup report now includes a `compaction` key:
```json
{
  "compaction": {
    "stm_expired": 3,
    "stale_candidates": [{"claim_id": "...", "statement": "...", "confidence": 0.3, "last_activity": "2025-01-01T..."}],
    "archived": ["claim_id_1", "claim_id_2"]
  }
}
```

Full details: see `short_term_memory.md`.
