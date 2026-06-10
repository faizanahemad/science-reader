# PKB Provenance, Origin & Memory Cleanup — Implementation Plan

Status: COMPLETE (W1-W12). Backend + REST + UI shipped; UI not browser-verified in this env. Builds on `pkb_memory_system_improvements.plan.md` (workstreams A–H, all complete) and the `pkb_memory_overview` feature. Each unit is a discrete commit, staged by path, verified (`py_compile` + tests in conda env `science-reader`) before commit. Never pushed.

## Goals (decisions locked with user 2026-06-10)

1. **Two-axis claim provenance.**
   - **Channel** (where it entered): `manual | chat | ingest | import`. Fold legacy `migration` → `import`. `referenced` is NOT a channel (it is a retrieval-time injection label) — excluded.
   - **Derivation** (epistemic basis): `stated` (user said/entered ~verbatim) | `extracted` (rephrased from the user's own message, same content) | `inferred` (a conclusion the user never explicitly stated).
   - One derivation per claim. Set by the distiller/ingestion LLM at extraction time; manual adds = `stated`; import preserves incoming value (defaults `extracted` if absent).
   - `inferred` ⇒ **lower default confidence** (seeded) **and** retrieval **down-rank**.
   - Backfill existing claims: infer derivation from current `source.type` (`manual`→`stated`, else `extracted`); channel from existing source.
   - Stored in `meta_json` (migration-free). Promote to a column only if server-side filtering demands it later.
2. **`auto` vs `curated` origin for entities & tags** (in their existing `meta_json`, key `origin`).
   - `auto` when created during LLM enrichment; `curated` when user manually creates/renames/edits. Merging into a curated target stays curated.
   - Backfill existing entities/tags → `curated` (treat history as user-trusted).
   - Does **NOT** gate dedup (user decision C10 = no). Display/cleanup signal only.
3. **Tag merge** — add `TagCRUD.merge` + facade `merge_tags` + `find_tag_duplicates` + REST, parallel to entities, so tag consolidation is non-lossy (today only delete exists, which cascades and loses links).
4. **LLM-assisted overlap judging** for claim consolidation AND entity/tag dedup — an LLM verification pass layered on the cheap candidate generation (embedding/string), to confirm a cluster is a true duplicate and propose the canonical/merged form. Gated by config; cheap-candidate path remains the prefilter.
5. **Single "Memory Cleanup" orchestrator** — one action (button + endpoint) that:
   - runs safe maintenance automatically: expiry sweep, dormancy decay sweep, overview refresh;
   - gathers dedup/merge **proposals** (claims, entities, tags) for user review (two-phase analyze → apply, mirroring the existing propose→execute pattern; merges are destructive so they are confirmed, not auto-applied);
   - returns a single consolidated report.
6. **Lifecycle-change notification** — when an `add`/`extract` causes an existing claim to become `contested` or `superseded`, explicitly report this back to the user after the new claim is added (surface in ActionResult + UI toast + distiller proposal summary).
7. **Reconfirmation upgrade** — if an `inferred` claim is later explicitly stated by the user, reinforcement upgrades its derivation to `stated` (and lifts the inferred confidence cap).
8. **Audit coverage** — merges (`consolidate_claims`, `merge_entities`, `merge_tags`) and derivation/origin changes write to `audit_log` (today merges are not audited).
9. **UI** — provenance badge + filter (stated/extracted/inferred), channel filter, auto/curated indicator + "review auto-created" view, tag-merge UI, Memory Cleanup button + report modal, lifecycle-change notices.

## Existing behavior confirmed (baseline)

- Claim consolidation candidates: embedding cosine clustering (`search/consolidation.py:cluster_near_duplicate_claims`, threshold `consolidation_similarity_threshold`=0.95), manual confirm via `consolidate_claims` / `POST /pkb/consolidation/merge`. No auto trigger.
- Entity dedup: `cluster_entity_variants` (string sim + token-subset, `entity_dedup_threshold`=0.85), `merge_entities` re-points `claim_entities` then deletes source, records `meta_json.aliases`.
- Delete cascades: `claim_tags`/`claim_entities` have `ON DELETE CASCADE` (delete drops links; merge re-points them). Tags have no merge.
- Claim `meta_json.source` is already a structured object `{type, conversation_id, message_id, distilled}`.

## Workstreams & tasks

### W1 — Claim provenance two-axis (backend foundation)
- [x] W1.1 `utils.py`: helpers `set_provenance(meta, channel, derivation)` / `get_provenance(meta)`; constants for channels + `Derivation` enum in `constants.py`. Define inferred confidence cap (`config.inferred_confidence_cap`, default e.g. 0.5) and downrank weight (`config.inferred_rerank_penalty`).
- [x] W1.2 `structured_api.add_claim`: accept `derivation`/`channel` (via kwargs), normalize channel vocab (migration→import), default manual=stated; seed lower confidence when derivation=inferred and no explicit confidence; write both axes into `meta_json.source`.
- [x] W1.3 Backfill helper (idempotent) inferring derivation/channel for legacy claims; expose as ops method (not auto-run on every init).
- [x] W1.4 Tests.

### W2 — Distiller / ingestion derivation labeling
- [x] W2.1 `llm_helpers`: extend the distiller/ingestion extraction prompt to label each candidate `stated|extracted|inferred`; add field to `CandidateClaim` / `IngestCandidate`.
- [x] W2.2 Thread derivation through `_propose_actions` → `add_claim`. Manual UI path stays `stated`.
- [x] W2.3 Tests.

### W3 — Retrieval downrank for inferred
- [x] W3.1 Recency/confidence re-rank: subtract `inferred_rerank_penalty` for `derivation=inferred`. Default keeps behavior near-unchanged unless configured.
- [x] W3.2 Eval baseline unchanged on the 49-claim set (no inferred claims there); tests.

### W4 — Reconfirmation upgrade (inferred → stated)
- [x] W4.1 `reinforce_claim` (and the distiller duplicate→reinforce path): when the triggering input is a user statement and the claim is `inferred`, upgrade derivation to `stated` and lift the confidence cap.
- [x] W4.2 Tests.

### W5 — auto vs curated origin (entities & tags)
- [x] W5.1 Set `meta_json.origin="auto"` on enrichment-created entities/tags; `"curated"` on manual create/rename/edit; promotion on edit; merge target stays curated.
- [x] W5.2 Backfill existing → curated (idempotent ops method).
- [x] W5.3 Tests.

### W6 — Tag merge
- [x] W6.1 `TagCRUD.merge(source_id, target_id)`: re-point `claim_tags` (INSERT OR IGNORE), re-parent children, delete source. `find_tag_duplicates` (name sim). Facade `merge_tags`/`find_tag_duplicates`.
- [x] W6.2 REST `GET /pkb/tags/duplicates`, `POST /pkb/tags/merge`.
- [x] W6.3 Tests.

### W7 — LLM-assisted overlap judging
- [x] W7.1 `llm_helpers.judge_duplicates(items)` verification pass; integrate as optional `use_llm` step in `find_consolidation_candidates` and `find_entity_duplicates`/`find_tag_duplicates` (cheap prefilter → LLM confirm + canonical suggestion). Config `dedup_llm_verify` (default off/on TBD).
- [x] W7.2 Tests (mock LLM).

### W8 — Lifecycle-change notification
- [x] W8.1 When add/extract sets an existing claim `contested`/`superseded`, collect the affected claims and surface them: `ActionResult.data["lifecycle_changes"]`, distiller proposal summary text, and UI toast.
- [x] W8.2 Tests.

### W9 — Memory Cleanup orchestrator
- [x] W9.1 Facade `run_memory_cleanup(apply=False)`: phase 1 analyze (gather claim/entity/tag dedup proposals + run safe sweeps + overview refresh) → report; `apply=True` executes confirmed merges. REST `POST /pkb/cleanup` (+ `/pkb/cleanup/apply`).
- [x] W9.2 Tests.

### W10 — Audit coverage
- [x] W10.1 `record_audit` hooks in `consolidate_claims`, `merge_entities`, `merge_tags`, and derivation/origin changes.
- [x] W10.2 Tests.

### W11 — UI
- [x] W11.1 Provenance badge + derivation/channel filter on Claims tab; inferred styled distinctly.
- [x] W11.2 auto/curated indicator on Entities/Tags tabs + "review auto-created" filter.
- [x] W11.3 Tag-merge UI (mirror entity merge); duplicate review.
- [x] W11.4 "Memory Cleanup" button + report/confirm modal.
- [x] W11.5 Lifecycle-change toast wiring.

### W12 — Docs
- [x] W12.1 Update `pkb_memory_overview.md` (or new section), `implementation.md`, `implementation_deep_dive.md`, `api.md`, README.

## Open / deferred
- LLM verify default (on vs off) — start OFF, enable after eval.
- Whether to promote `derivation` to a real column — defer until UI filtering perf needs it.

## Implementation order
Backend first, additive: W1 → W2 → W3 → W4 → W5 → W6 → W7 → W8 → W9 → W10, then W11 (UI), then W12 (docs). Each task its own commit.
