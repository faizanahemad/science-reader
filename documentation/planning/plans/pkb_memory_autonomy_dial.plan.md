# PKB / TMS — Unified Memory Autonomy Dial (Manual ◀──▶ Automatic)

**Status:** Draft
**Created:** 2026-06-12
**Owner:** PKB / TMS

---

## 1. Goals & Objectives

**Primary objective:** Give the user a single, legible control — a **0–100 "Memory Autonomy" dial** — that sets *how much the PKB does on its own* across the **entire memory lifecycle**, from capturing new memories to curating, decaying, and enriching them. At **0** the PKB is fully manual (it only ever proposes; the user does everything); at **100** it is fully automatic (it acts on its own, always reversibly and transparently). One dial, coherent behavior across every subsystem and every surface (chat UI, standalone UI, REST, MCP).

### Goals

| # | Goal | Success criteria |
|---|------|------------------|
| G1 | **One dial, whole lifecycle** | A single per-user `memory_autonomy ∈ [0,100]` drives capture, curation, decay/lifecycle, and enrichment coherently |
| G2 | **Fully manual at 0** | At 0, *nothing* mutates the store without explicit user action; all automation proposes only |
| G3 | **Fully automatic at 100** | At 100, the PKB captures/curates/decays/enriches on its own — but every action is logged, notified, and reversible |
| G4 | **Safety floor at every level** | Conflicts, `inferred` claims, sensitive domains, and deletions are *never silently lost* — at high autonomy they auto-apply with notify+undo, never without a trace |
| G5 | **Reversibility-ordered** | Automation turns on in order of reversibility/trust-cost as the dial rises (safest first) |
| G6 | **Legible** | The user can see exactly what each dial level does (live "what changes" preview) and override any facet |
| G7 | **Per-user, cross-surface** | The same policy governs UI, REST, and MCP; resolved from the authenticated identity |
| G8 | **Dev-inert, eval-gated, Balanced GA default** | Code lands inert (no behavior change during development); the **GA default for users is Balanced (50)**, switched on only after the per-facet eval gate passes. Users who never touch the dial get Balanced once GA'd; the dial can always be set back to Manual (0) for fully-manual behavior |
| G9 | **Transparent provenance** | Every automated action records why/when/by-which-policy; a unified activity/undo log exists |

### Non-goals
- New extraction prompts or a new sensitivity ML model (v1 derives risk from existing signals).
- Changing the *algorithms* of decay/consolidation/search — only *when they run automatically vs propose*.
- Multi-tenant admin policy (per-user only for now).

### Relationship to other plans
- **`pkb_tiered_memory_persistence.plan.md`** is the detailed design of the **Capture facet** (silent-save vs confirm vs skip). This plan is the **umbrella**: it generalizes that 3-preset idea into a 0–100 dial spanning all facets and owns the per-user policy store + config-resolution architecture that the Capture facet also needs.
- **`pkb_external_access_ui_mcp_rest_auth.plan.md`** — the dial must work identically across the external surfaces; policy resolves from the JWT identity (`_effective_email`, landed).
- **`pkb_retrieval_ranking.plan.md`** — retrieval consumes what the lifecycle leaves behind (dormant down-ranking etc.).

---

## 2. Background & Current State (verified 2026-06-12)

The PKB already has ~12 independent lifecycle automation subsystems, each gated by its own `PKBConfig` field and **mostly defaulting to inert**. The dial is a coherent preset layer over these existing flags — not new machinery.

| Subsystem | Config field(s) | Inert/manual default |
|-----------|-----------------|----------------------|
| Capture / persistence | (new) `tiered_persistence_enabled`, `auto_save_confidence` | confirm everything |
| Dedup reinforcement on add | `reinforce_on_duplicate` (`off`/`reinforce`/`reinforce_warn`) | `off` |
| Consolidation (merge similar claims) | `consolidation_similarity_threshold` (0.95) | propose via dedup endpoint |
| Entity resolution / merge | `entity_dedup_threshold` (0.85) | propose |
| Dormancy decay | `dormancy_threshold` (0.0 = off), `nondecayable_types` | off |
| Background lifecycle sweep | `sweep_interval_seconds` (0 = off) | off (lazy on-search only) |
| Reinforcement | `reinforce_alpha` (0.1), `reinforce_ttl_days_by_type` | gentle |
| Conflict/contradiction detection + resolution | detection flag; `conflict_scan_limit` | detect → **manual** resolve |
| Batch enrichment (entities/tags) | `combined_enrichment` (G2, default True) | auto (cheap) |
| STM → long-term promotion | `stm_promotion_threshold` (3), `stm_reinforcement_threshold` | manual/lazy |
| Overview refresh | overview auto-refresh | — |
| Recency rerank | `recency_rerank_enabled` (True) | on (display-only) |

**Two architectural facts the dial must work around:**
1. **Config is shared, not per-user.** `StructuredAPI.__init__(db, keys, config, user_email=None)`; `for_user(email)` returns a new API **with the same `config` object**. So today every user shares one `PKBConfig`. Per-user autonomy needs an **effective-config resolution** step in `for_user`.
2. **No per-user settings store exists** in the TMS DB. We must add one.
3. **The lifecycle scheduler is global** — started once in `endpoints/pkb.py:190` as `start_lifecycle_sweep_scheduler(db, config)` reading `config.sweep_interval_seconds`. Per-user sweep cadence needs the scheduler to iterate users (or use an effective global interval). 
4. `inferred` claims already get `inferred_confidence_cap = 0.4`, so they naturally fall below any reasonable `auto_save_confidence` — the safety floor is partly self-enforcing.

---

## 3. Concept — the Dial as a Policy Vector

`memory_autonomy: int (0–100)` → a **pure function** `derive_policy(autonomy, facet_overrides) → effective PKBConfig overrides`. The slider is a *preset generator*; the underlying per-subsystem flags remain the source of truth, so the dial can never express anything the flags can't, and every level is auditable.

### 3.1 Design principle — reversibility ordering
As the dial rises, automation activates **safest-first** (cheap, reversible, down-ranking-only behaviors early; irreversible/high-trust-cost behaviors last):

```
0 ────────────────────────────────────────────────────────► 100
recency rerank · enrichment · reinforcement · background sweep(down-rank only) ·
silent-save high-confidence STATED facts · auto-consolidate near-identical ·
gentle dormancy · STM auto-promote · auto entity-merge ·
silent-save inferred(w/ undo) · auto-resolve conflicts(w/ undo) · auto hard-expire/delete
```

### 3.2 Four facets (the dial drives all; each can be overridden)
| Facet | Subsystems | "What automating it means" |
|-------|-----------|----------------------------|
| **Capture** | persistence (tiered plan), STM promotion | save new memories silently vs ask |
| **Curation** | dedup reinforcement, consolidation, entity merge, conflict resolution | merge/clean/resolve automatically vs propose |
| **Lifecycle** | dormancy decay, background sweep, expiry, reinforcement | age/down-rank/expire automatically vs manual |
| **Enrichment** | entity/tag extraction, overview refresh, provenance backfill | enrich on add vs on-demand |

A user can keep the master dial at *Balanced* but, say, set **Lifecycle = Manual** (never auto-decay) — an explicit facet override wins over the master-derived value.

---

## 4. The Band Mapping (dial → subsystem state)

Five labeled detents. Cells show the effective behavior; numbers become the `derive_policy` table (illustrative, tuned during eval).

| Subsystem | **0 Manual** | **25 Assisted** | **50 Balanced** | **75 Proactive** | **100 Full** |
|-----------|----------|-------------|-------------|--------------|----------|
| Capture: safe stated facts | confirm | silent ≥0.95 | silent ≥0.85 | silent ≥0.75 | silent (all non-escalated) |
| Capture: inferred claims | confirm | confirm | confirm | confirm | silent + undo |
| Capture: sensitive / conflict | confirm | confirm | confirm | confirm | notify + auto + undo |
| STM → long-term promotion | manual | ≥4 reinforces | ≥3 | ≥2 | auto on first reinforce |
| Dedup on add | off | reinforce_warn | reinforce | reinforce | reinforce |
| Consolidation | propose | propose | auto ≥0.97 | auto ≥0.95 | auto ≥0.93 |
| Entity merge | propose | propose | auto ≥0.92 | auto ≥0.88 | auto ≥0.85 |
| Dormancy decay | off | off | gentle | on | aggressive |
| Background sweep interval | off | 24h | 12h | 6h | 1h |
| Hard expiry (valid_to passed) | propose | propose | auto | auto | auto |
| Conflict resolution | manual | manual | manual | assisted (propose winner) | auto-pick winner (recency/confidence) + notify |
| Update/supersede existing claim | confirm | low-risk* auto | low-risk* auto | non-sensitive confident auto | auto + undo |
| Enrichment (entities/tags) | on-demand | auto | auto | auto | auto |
| Overview refresh | manual | on demand | periodic | periodic | continuous |

**\*low-risk** (for silent edits/updates): the change is to a non-sensitive domain, the candidate is `stated`/`extracted` (not `inferred`), confidence is high, and it is not a conflict — i.e. it passes the same safety floor as a silent add. Risky updates (sensitive, inferred, conflicting) always confirm below Full and notify+undo at Full.

**Detent semantics:**
- **0 Manual:** read/propose only. No background sweep, no decay, no auto-merge, no silent save. The PKB never mutates without a user click.
- **50 Balanced (recommended default once shipped):** the tiered Capture policy for safe facts; gentle lifecycle; curation proposes for risky merges, auto for near-identical; conflicts still ask.
- **100 Full:** acts autonomously everywhere; the only thing that changes vs lower levels for risky items is *ask-first → tell-after-with-undo*. Never *silently-and-irreversibly*.

---

## 5. `derive_policy()` — Resolution & Invariants

### 5.1 Resolution order (per user, per request/session)
```
effective_config_field =
    explicit_facet_override[field]            # user set this facet manually
    ?? master_derived[field]                  # from derive_policy(autonomy)
    ?? base_config_default[field]             # PKBConfig default / env
```
`derive_policy` returns only the fields it manages; everything else falls through to base config.

### 5.2 Invariants (must hold at all autonomy levels — unit-tested)
- **I1 — Audit:** every automated mutation writes an activity-log row (what, why-route-reason, policy level, ts, source surface).
- **I2 — Reversible:** every automated mutation is undoable (retract for adds/merges; restore for decays/expiries within window).
- **I3 — No silent loss of risk:** conflicts, `inferred` claims, sensitive-domain claims, and deletions are never *silently dropped*; at high autonomy they auto-apply **with notification**, never without.
- **I4 — Monotonic:** higher autonomy never *reduces* what's automated (the band table is monotonic per subsystem).
- **I5 — 0 ⇒ inert:** at autonomy 0 (or master flag off), the resolved config equals today's behavior exactly.

---

## 6. Per-User Policy Store & Config Resolution (architectural change)

### 6.1 Policy store (new)
Add a per-user settings row in the TMS DB (e.g. `pkb_user_settings(email TEXT PRIMARY KEY, memory_autonomy INT, facet_overrides JSON, updated_at)`). Read/write via `StructuredAPI` (and exposed over REST/MCP). Defaults: row absent ⇒ autonomy = `default_autonomy`. During development this is **0** (dev-inert, behavior identical to today); the **GA default is 50/Balanced** (flipped via the `default_autonomy` config once the eval gate passes — G8). External MCP/agent callers default to **100** (see §7.3), regardless of the human default.

### 6.2 Effective config in `for_user` (the key change)
`for_user(email)` currently passes the shared `config`. Change it to compute an **effective config**: load the user's policy, run `derive_policy`, overlay onto the base `PKBConfig` (reuse `PKBConfig.from_dict` + a merge), and pass that per-user config into the scoped `StructuredAPI`. Cache per email to avoid recompute. This localizes the entire change to one method + the resolver.

### 6.3 Scheduler (global → policy-aware)
`sweep_interval_seconds` is per-user under the dial. Options:
- **v1 (simple):** scheduler runs at the **finest active interval** (min across users with sweep enabled) and, per tick, sweeps each user with that user's dormancy/expiry policy (the sweep already takes `user_email`). Users at *Manual/Assisted* (sweep off) are skipped.
- **v2:** per-user schedules. v1 is sufficient and matches the existing `run_lifecycle_sweep(db, config, user_email)` signature.

---

## 7. UX by Surface

### 7.1 UI (chat app + standalone `/memory/`)
- **Master slider** "Memory Autonomy: Manual ◀──▶ Automatic" with 5 labeled detents (Manual / Assisted / Balanced / Proactive / Full). Discrete detents, not a mystery analog.
- **Live "what changes" preview** beneath the slider: a diff of behaviors at the selected level ("Safe facts saved silently · consolidation automatic · conflicts still ask you · memories decay gently"). Makes the abstraction legible (G6).
- **Advanced → per-facet controls:** 4 facet selectors (Capture / Curation / Lifecycle / Enrichment), each Manual/Assisted/Auto (or a mini-slider). An override marks the master as "Custom". Facet override wins (§5.1).
- **Unified Activity & Undo feed:** one place listing automated actions (saved, merged, decayed, expired, resolved) newest-first, each with Undo and the route reason — the trust backstop for I1/I2. Filterable by facet.
- **Provenance badges** on claims: auto vs confirmed vs manual; "why do I know this?" already supported via source provenance.
- **Toasts** for high-salience automated actions (silent save, auto-resolve) with inline Undo; coalesced when batched.

### 7.2 REST API
- `GET/PUT /pkb/memory/policy` → `{ "autonomy": 0-100, "facets": {"capture": "...", "curation": "...", "lifecycle": "...", "enrichment": "..."} }`.
- `GET /pkb/memory/preview?autonomy=75&facets=...` → the "what changes" description (server-computed from `derive_policy`, so UI and docs stay in sync).
- `GET /pkb/memory/activity?days=7&facet=...` → the unified activity/undo feed.
- `POST /pkb/memory/undo` → `{claim_ids|action_ids|session_id}` reverses automated actions.
- Distillation/add responses gain the Capture-facet split (`auto_saved`/`proposed_actions`/`skipped`) per the tiered plan.
- **Back-compat:** autonomy 0 / flag off ⇒ all responses identical to today.

### 7.3 MCP (external agents)
- **External agents default to autonomy 100 (accept-all).** A non-interactive agent has no human to confirm with mid-task, so writes are accepted automatically — but this is made safe by **mandatory provenance tagging** (next bullet) plus full reversibility and the activity log. The agent still *receives* `auto_saved` (with `undo_token`s) so it can surface or undo.
- **Mandatory provenance for agent writes (decision 2026-06-12):** every claim an agent creates/edits is tagged so it is never mistaken for user-curated truth and can be filtered/down-weighted: `source.channel = "mcp"`, `source.agent = <token identity / agent name>`, `origin = "auto"`, and `derivation = "inferred"` by default (an agent asserting on the user's behalf is an inference, not a user statement) unless the agent explicitly passes `derivation="stated"` with evidence. Retrieval/ranking may down-weight `derivation=inferred` + agent-sourced claims so they don't overpower user-stated memories.
- Per-call override `autonomy`/`confirmation_mode` allowed, but **invariants I1–I3 are server-enforced** — even at 100, conflicts/sensitive/deletes are logged + notified (surfaced in the response) and reversible; nothing is silently lost.
- Tools: `pkb_get_policy` / `pkb_set_policy`, `pkb_memory_activity`, `pkb_undo` — so an agent (or its user) can inspect, adjust autonomy, review agent-added memories, and undo.

---

## 8. Provenance & Transparency (the backbone for trust)

Automation is only acceptable if it's fully traceable:
- **Activity log table** (new): `pkb_activity_log(id, email, action, target_id, facet, route_reason, autonomy_level, surface, ts, undo_token, undone_at)`. Every automated mutation appends here (I1).
- **Per-claim provenance** (existing `source`/`origin`/`derivation`) extended with `auto_saved_at`, `autonomy_level`, `policy_reason`.
- **Undo** reuses retract/restore paths; activity rows carry the token (I2).
- The UI Activity feed and `GET /pkb/memory/activity` render this log.

---

## 9. Implementation Plan (phases, tasks, milestones)

### Phase A — Foundations (no behavior change; default Manual during dev)
- **A0 (audit)** Audit that nothing bypasses per-user config resolution: grep/trace every reader of `PKBConfig` (esp. cached/long-lived objects — `get_pkb_db`'s shared config, the scheduler's held config, `EmbeddingStore`, any module-level singletons) to confirm they read the per-user *effective* config produced by `for_user`, not the shared base. Document the readers; fix any that bypass. **Blocks A3 sign-off.**
- **A1** Per-user policy store: `pkb_user_settings` table + `StructuredAPI` get/set methods.
- **A2** `derive_policy(autonomy, overrides) → dict` pure function + the band table + exhaustive unit tests (incl. invariants I4/I5 and the safety floor).
- **A3** Effective-config resolution in `for_user` (overlay + per-email cache).
- **A4** Activity-log table + write helper; undo helper (retract/restore); `POST /pkb/memory/undo`. **Undo window = 24h tombstone** (decision 2026-06-12): an auto-action is hard-reversible for 24h via a tombstone record (the created claim / applied merge / decay can be fully undone, restoring prior state); after 24h the action is finalized (undo becomes a normal manual edit/retract, not a clean restore).
- **Gate:** full TMS suite green; `default_autonomy=0` ⇒ identical behavior.

### Phase B — Capture facet (the tiered persistence plan)
- **B1–B6** per `pkb_tiered_memory_persistence.plan.md` (route_candidate, partitioning, REST split, UI toast + activity feed, MCP policy-aware, eval). Capture facet now reads its sub-policy from `derive_policy`.

### Phase C — Curation facet
- **C1** Wire `reinforce_on_duplicate`, `consolidation_similarity_threshold`, `entity_dedup_threshold` to dial-derived values; auto-execute above the auto-threshold, else propose.
- **C2** Conflict resolution: at Proactive, propose a winner; at Full, auto-resolve with undo (never silently at lower levels — I3).

### Phase D — Lifecycle facet
- **D0 (verify)** Confirm a working **restore** path exists for lifecycle transitions before auto-decay/expiry is allowed: that `dormant → active` and `expired → active` (and retract → active) operations exist, are exposed, and that a restored claim **re-enters retrieval** (FTS + embedding + ranking). If any restore path is missing, build it. This is the prerequisite for I2 (reversibility) on the Lifecycle facet — auto-decay/expiry must not ship until restore is proven by an integration test.
- **D1** Dial drives `dormancy_threshold`, `sweep_interval_seconds`, hard-expiry auto-vs-propose, `reinforce_alpha`.
- **D2** Scheduler made policy-aware (§6.3 v1: finest active interval, per-user sweep).

### Phase E — Enrichment facet
- **E1** Dial drives `combined_enrichment` cadence + overview refresh. (Mostly already auto; lowest risk.)

### Phase F — UX & rollout
- **F1** UI: master slider + detents + live preview + facet overrides + Activity/Undo feed.
- **F2** `GET /pkb/memory/preview` + policy/activity endpoints.
- **F3** Eval + gated default flip (see §11).

### Milestones
| Milestone | Phases | Effort |
|-----------|--------|--------|
| **M-A — Policy substrate** | A1–A4 | Medium — store + resolver + activity/undo (foundational) |
| **M-B — Capture autonomy** | B | Medium (tiered plan) |
| **M-C — Curation autonomy** | C | Medium |
| **M-D — Lifecycle autonomy** | D | Medium (scheduler change) |
| **M-E — Enrichment autonomy** | E | Small |
| **M-F — Dial UX + rollout** | F | Medium |

**Order:** M-A first (everything depends on the substrate), then B/C/D/E can proceed largely in parallel, then M-F ties it together and gates the default.

---

## 10. What Changes — Files

| File | Change |
|------|--------|
| `truth_management_system/config.py` | New fields (Capture flags, `default_autonomy=0`); `derive_policy()` table lives here or in a new `autonomy.py` |
| `truth_management_system/autonomy.py` (new) | `derive_policy(autonomy, overrides)`, band table, facet model, resolution helpers |
| `truth_management_system/database.py` | `pkb_user_settings` + `pkb_activity_log` tables; CRUD |
| `truth_management_system/interface/structured_api.py` | `for_user` resolves effective per-user config; get/set policy; activity-log writes; undo |
| `truth_management_system/interface/conversation_distillation.py` | Capture routing (tiered plan) reads dial sub-policy |
| `truth_management_system/interface/text_ingestion.py` | Same routing for bulk ingest |
| `truth_management_system/scheduler.py` | Policy-aware sweep (finest active interval; per-user) |
| `truth_management_system/utils.py` | `run_lifecycle_sweep`/decay honor per-user dial-derived thresholds |
| `endpoints/pkb.py` | `GET/PUT /pkb/memory/policy`, `/preview`, `/activity`, `/undo`; distill response split; scheduler start passes resolver |
| `mcp_server/pkb.py` (→ package per other plan) | `pkb_get_policy`/`set_policy`/`memory_activity`/`undo`; policy-aware writes; server-enforced invariants |
| `interface/pkb-manager.js` | Master slider + detents + live preview + facet overrides + Activity/Undo feed + toasts |
| `interface/interface.html` | Settings UI markup for the dial |
| `truth_management_system/tests/` + `tests/eval/` | `derive_policy`/invariant unit tests; routing + lifecycle eval sets |
| docs | `chat_app_capabilities.md`, TMS feature docs, this plan + tiered plan cross-links |

---

## 11. Rollout & Evaluation (inert-by-default, eval-gated)

1. **Phase 0 — inert:** land M-A..M-E with `default_autonomy=0`. Behavior identical to today; suite green (G8, I5).
2. **Phase 1 — eval:** per facet, measure on labeled sets — Capture: wrong-auto-save rate, friction reduction, hard-escalation coverage = 100%; Curation: wrong-merge rate; Lifecycle: wrongly-decayed/expired rate (and that undo restores). Reuse `truth_management_system/tests/eval/`.
3. **Phase 2 — opt-in:** expose the slider; default stays Manual; watch the activity/undo telemetry per facet.
4. **Phase 3 — default:** move the shipped default to **Balanced (50)** only if undo rates per facet stay under target and no retrieval regression.

**Gate to raise the default:** per-facet undo/correction rate < target (e.g. Capture < 3%, Curation < 2%, Lifecycle < 1%), invariants I1–I5 verified, measurable friction reduction, no recall regression.

---

## 12. Risks

- **Silent wrong mutation (core):** a bad auto-save/merge/decay degrades the store invisibly. Mitigations: reversibility ordering (risky things automate last), conservative thresholds, the safety floor (I3), the universal activity log + undo, and eval gating per facet.
- **Shared→per-user config regression:** changing `for_user` touches every code path. Mitigation: default-0 equals today; cache + thorough tests; land M-A behind the master flag.
- **Scheduler complexity:** per-user cadence. Mitigation: v1 finest-interval approach reuses the existing per-user sweep.
- **Dial misperception:** users may over-trust "Full". Mitigation: live preview, explicit "tell-after-with-undo" framing, and the Activity feed front-and-center.
- **Cross-surface drift:** UI/REST/MCP must read one policy. Mitigation: single per-user store + server-computed `/preview`.
- **Undo gaps for lifecycle:** decays/expiries must be restorable. Mitigation: soft-state transitions (dormant/expired are reversible statuses already) + activity tokens.

---

## 13. Open Questions

### Resolved (2026-06-12)
- **Shipped default:** GA default = **Balanced (50)**. Code lands dev-inert (`default_autonomy=0` during development); the default flips to 50 once the eval gate passes. No forced first-run choice — a non-blocking intro instead (see First-run below). The dial can always be set to Manual (0).
- **Per-domain sub-dial:** **No.** Sensitive domains (`health`/`finance`/`relationships`) do **not** get a separate dial; they are handled by the escalation rules inside the single master dial (they require confirmation below Full, and notify+undo at Full).
- **Conflict auto-resolution at 100:** **auto-pick the winner** by recency/confidence **and notify** (logged + undoable). Never silent below Full.
- **Undo window:** **24h tombstone** — auto-actions are cleanly reversible for 24h; finalized after.
- **First-run UX:** since the default is a sensible Balanced (not Manual), no blocking onboarding — show a one-time non-blocking explainer ("Memory is on Balanced — it remembers safe facts automatically and asks about sensitive ones. Adjust anytime in Settings.") linking to the dial.

### Still open
1. **Granularity** — 5 detents only, or continuous 0–100 with detents as snap points?
2. **Scheduler** — accept v1 finest-interval, or invest in per-user schedules early? (default: v1)
3. **Does the dial belong per-PKB or per-context-domain** in the long run?

---

## 14. Summary

The autonomy dial is a thin, auditable **preset layer** (`derive_policy`) over ~12 lifecycle flags the PKB already has, plus three new substrate pieces — a **per-user policy store**, **effective-config resolution in `for_user`**, and a **universal activity/undo log**. It unifies capture, curation, lifecycle, and enrichment under one legible control, preserves today's behavior at the bottom, and makes "fully automatic" safe by guaranteeing every action is reversible, notified, and logged. It ships inert and is raised per-facet behind evaluation.
