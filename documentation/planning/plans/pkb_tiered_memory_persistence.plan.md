# PKB / TMS — Tiered Memory Persistence (Silent-with-Undo + Confirm-when-Risky)

**Status:** DONE — Backend routing logic complete (routing.py, config, REST/MCP endpoints, tests). UI landed 2026-06-13 (auto-save toast with undo, recently auto-saved section, undo handler).
**Created:** 2026-06-12
**Scope:** Replace the current "every long-term claim requires user confirmation" behavior with a **tiered routing policy** that decides, per extracted candidate, whether to (A) **save silently with undo**, (B) **ask the user to confirm**, or (C) **skip silently**. The decision is computed from signals the pipeline *already* produces (confidence, dedup similarity, conflict relation, derivation, context domain, claim type, visibility). Covers product design, the UX at UI / REST / MCP levels, the implementation seam, config, rollout (inert-by-default, eval-gated), and evaluation.

**Related plans:** `pkb_memory_autonomy_dial.plan.md` — the **umbrella** plan; this plan is the detailed design of its **Capture facet**, and the autonomy dial owns the per-user policy store + effective-config resolution that this plan also relies on. `pkb_external_access_ui_mcp_rest_auth.plan.md` (standalone/MCP/REST surfaces — the policy must work across all of them), `pkb_retrieval_ranking.plan.md` (retrieval is downstream of what we persist), `pkb_rewrite_entity_unification.plan.md`.

**Non-goals:** Changing the *extraction* LLM/prompts; building a new sensitivity ML classifier (v1 derives sensitivity from existing enums); changing STM behavior (already silent).

---

## 1. Background & Motivation

### The UX question
Most ambient-memory systems (ChatGPT memory, etc.) **auto-extract and save silently** — zero friction, high recall, but they accumulate wrong/stale/sensitive memories the user never approved, and trust collapses the day a user discovers a bad memory. Our PKB instead **auto-extracts and asks** — high precision and trust, but every prompt is friction; at volume users either rubber-stamp (defeats the point) or disable the feature (zero memory). Neither pure approach wins.

**Thesis:** make the *confirmation itself conditional*. Save the safe, high-confidence, low-stakes facts silently (with a visible, one-click undo and a review surface), and only interrupt the user for the genuinely risky ones (low confidence, inferred conclusions, sensitive domains, conflicts). This captures the silent systems' recall/frictionlessness on the ~80% safe items and keeps our precision/trust on the ~20% that need a human.

### Current state (verified 2026-06-12)
- **Extraction → proposal → execute** lives in `truth_management_system/interface/conversation_distillation.py` (`ConversationDistiller.extract_and_propose()` → `MemoryUpdatePlan` → `execute_plan(plan, approved_indices)`), and `text_ingestion.py` (`TextIngestionDistiller.ingest_and_propose()` → `IngestProposal`).
- **STM (short-term memory) is already saved silently** — `MemoryUpdatePlan.short_term_candidates` are "stored silently, no user confirmation."
- **Long-term claims always require confirmation** — `requires_user_confirmation = len(proposed_actions) > 0`. The endpoint `POST /pkb/...` (≈`endpoints/pkb.py:2107`) returns `proposed_actions` (each with `statement`, `claim_type`, `context_domain`, `action`, `reason`, `confidence`, `editable`, `existing_claim_id`); the UI shows `#memory-proposal-modal` via `showBulkProposalModal()` and applies the user's picks via `executeUpdates(planId, approvedIndices)` → `POST /pkb/.../execute`.
- **Signals already produced** (the policy inputs):
  - `CandidateClaim.confidence` (0.0–1.0; default 0.8) — `ClaimAnalysisResult.confidence`.
  - `similarity_score` + `DUPLICATE_THRESHOLD` (~0.92) — `text_ingestion._find_existing_*`.
  - `relation` ∈ {`duplicate`, `related`, `conflict`} — `_find_existing_matches`.
  - `Derivation` ∈ {`stated`, `extracted`, `inferred`} — `constants.py`.
  - `ContextDomain` ∈ {`personal`, `health`, `relationships`, `learning`, `life_ops`, `work`, `finance`}.
  - `ClaimType` ∈ {`fact`, `memory`, `decision`, `preference`, `task`, `reminder`, `habit`, `observation`}.
  - `Visibility` ∈ {`default`, `restricted`, `shareable`}; `importance` ∈ {`medium`, `high`}.
  - `Status` includes `draft` ("not yet confirmed") and `retracted` (soft delete) — useful for modeling auto-save + undo.

**Key insight:** the seam already exists. `MemoryUpdatePlan` separates silent (STM) from confirm (long-term). We are generalizing that split — routing *each* long-term candidate into a lane — rather than building new machinery.

---

## 2. Goals & Success Criteria

| # | Goal | Success criteria |
|---|------|------------------|
| G1 | Conditional confirmation | Each extracted candidate is routed to silent-save / confirm / skip by an explainable policy over existing signals |
| G2 | Frictionless safe path | High-confidence, low-risk facts save with **no modal** — only a non-blocking toast + undo |
| G3 | Trust preserved | Every silent save is visible (toast + a "Recently auto-saved" review list) and reversible with one click within an undo window |
| G4 | Risk always escalates | Conflicts, inferred claims, sensitive domains (`health`/`finance`/`relationships`), `restricted` visibility, and low-confidence items **always** go to confirm |
| G5 | Works across surfaces | Same policy governs chat distillation, REST, and MCP (external agents) — with per-user policy config |
| G6 | Inert-by-default + eval-gated | Ships OFF (current all-confirm behavior); flipped on only after an eval shows acceptable wrong-auto-save precision + measured friction reduction |
| G7 | Reversible & auditable | Auto-saves are logged; undo is reliable; "undo all auto-saves from this session" exists |

**Headline metrics:** (a) **wrong-auto-save rate** = fraction of silently-saved claims the user later undoes/retracts (target: very low, e.g. < 3%); (b) **friction reduction** = fraction of candidates that no longer require a modal; (c) **recall lift** = net increase in retained useful claims vs all-confirm baseline.

---

## 3. Product Design — the Tiered Routing Policy

### 3.1 Three lanes

| Lane | Action | UX |
|------|--------|-----|
| **A — Silent save** | Persist immediately (`origin=auto`), record provenance | Non-blocking "🧠 Remembered: <statement>" toast with **Undo**; item appears in "Recently auto-saved" |
| **B — Confirm** | Add to `proposed_actions`; do not persist yet | Existing `#memory-proposal-modal` (batched), user approves/edits/rejects |
| **C — Skip** | Drop silently (optionally log) | Nothing shown (today's behavior for near-duplicates/noise) |

### 3.2 The decision function (v1 — explainable, no new classifier)

Evaluate gates **top-to-bottom; first match wins.** All thresholds are config (see §6).

```
route(candidate, match) ->
  # --- hard escalations (never silent) ---
  if relation == "conflict":                      return CONFIRM   # never silently contradict
  if derivation == "inferred":                    return CONFIRM   # never silently store conclusions user didn't state
  if context_domain in SENSITIVE_DOMAINS:         return CONFIRM   # health, finance, relationships
  if visibility == "restricted":                  return CONFIRM
  if claim_type in HIGH_STAKES_TYPES:             return CONFIRM   # decision, task, reminder (configurable)

  # --- silent skip (noise / exact dup) ---
  if relation == "duplicate" and similarity >= DUPLICATE_THRESHOLD:  return SKIP   # (or silent-merge, see 3.4)
  if confidence < SKIP_CONFIDENCE:                return SKIP        # too weak to bother anyone

  # --- silent auto-save (safe, confident, low-stakes) ---
  if (confidence >= AUTO_SAVE_CONFIDENCE
      and derivation in {"stated", "extracted"}
      and claim_type in SAFE_TYPES            # fact, preference, habit, observation, memory
      and relation in {None, "related"}):     return AUTO_SAVE

  # --- everything else ---
  return CONFIRM
```

Defaults: `SENSITIVE_DOMAINS = {health, finance, relationships}`, `HIGH_STAKES_TYPES = {decision, task, reminder}`, `SAFE_TYPES = {fact, preference, habit, observation, memory}`, `AUTO_SAVE_CONFIDENCE = 0.85`, `SKIP_CONFIDENCE = 0.45`, `DUPLICATE_THRESHOLD = 0.92` (existing).

**Why a decision tree, not a score?** It's auditable ("saved silently because: stated fact, confidence 0.91, non-sensitive, no conflict"), trivially tunable, and every branch maps to a real signal. A weighted risk-score variant is a possible v2 (see §11).

### 3.3 Related-but-not-duplicate (`relation == "related"`)
A `related` match means a near-neighbor exists but it's not a dup. Safe types with high confidence can still auto-save (they add nuance). If it actually *updates/supersedes* an existing claim:

**Silent edits are autonomy- and risk-gated (decision 2026-06-12), not always-confirm.** Updates to existing claims may auto-apply when they are **low-risk** — non-sensitive domain, `stated`/`extracted` (not `inferred`), high confidence, non-conflicting — even at lower autonomy levels; and more broadly at higher autonomy. Risky updates (sensitive domain, `inferred`, or conflicting with the existing claim) still confirm below Full and notify+undo at Full. The update path records the prior value in the activity log so any auto-applied edit is fully reversible within the 24h tombstone window. (Editing an existing memory is no longer treated as categorically higher-risk than a silent add; the risk is judged by the same safety-floor signals.)

### 3.4 Silent merge (optional v1.1)
For `duplicate` with `0.85 ≤ similarity < 0.92` we may silently reinforce the existing claim (bump recency/confidence) instead of skipping — improves the dormancy/decay signals without a new claim. Gate behind its own flag.

### 3.5 Undo model
- Auto-saved claim is `status=ACTIVE`, `origin=auto`, `source.derivation` recorded, plus metadata `auto_saved_at` (timestamp) and `plan_id`/`session_id`.
- **Undo** = retract (soft-delete → `status=RETRACTED`) or hard-delete if within a short grace window. Undo token = `claim_id`.
- "Recently auto-saved" view = query `origin=auto AND auto_saved_at within N days`, newest first, each with Undo + "Edit" + "Pin".
- **Undo-all-from-session** = retract all `origin=auto` claims with a given `session_id`/`plan_id`.

---

## 4. UX Design by Surface

### 4.1 UI (chat app + standalone `/memory/`)
- **Silent-save toast:** non-blocking, bottom-corner: "🧠 Remembered: *<statement>*" + **Undo** + (optional) "Why?" tooltip showing the route reason. Stacks/coalesces if several saved at once ("🧠 Remembered 3 things — Review").
- **Confirm path unchanged:** the existing `#memory-proposal-modal` now only appears for Lane-B items, so it shows up far less often and feels meaningful.
- **"Recently auto-saved" surface:** a section/tab in the PKB UI (and a filter `origin=auto`) listing silent saves with Undo/Edit/Pin and the route reason. This is the trust backstop (G3).
- **Provenance badge:** claims show an "auto" vs "confirmed" vs "manual" badge (we already store `origin`/`source`).
- **Settings — "Memory autonomy":** a per-user control with presets:
  - *Ask me* (current behavior — everything confirms; policy OFF),
  - *Balanced* (the tiered policy, default once shipped),
  - *Just remember* (auto-save everything except conflicts/sensitive),
  and advanced sliders for `AUTO_SAVE_CONFIDENCE`, sensitive-domain list, high-stakes types.

### 4.2 REST API
- **Distillation response gains a routing split.** `extract_and_propose` endpoint returns, in addition to `proposed_actions` (Lane B):
  ```json
  {
    "plan_id": "...",
    "auto_saved": [
      {"claim_id": "...", "statement": "...", "claim_type": "fact",
       "confidence": 0.91, "route_reason": "stated fact, high confidence, non-sensitive",
       "undo_token": "<claim_id>", "auto_saved_at": "..."}
    ],
    "proposed_actions": [ /* Lane B, as today */ ],
    "skipped": [ {"statement": "...", "reason": "near-duplicate (0.95)"} ],
    "requires_user_confirmation": true
  }
  ```
  i.e. the server **already persisted** the `auto_saved` items before responding.
- **New `POST /pkb/memory/undo`** `{ "claim_ids": [...] }` (or `{"session_id": "..."}`) → retracts auto-saved claims. Scope-guarded (`write`).
- **New `GET /pkb/memory/recent_auto`** `?days=7` → the review list.
- **Policy config:** `GET/PUT /pkb/memory/policy` → per-user policy (preset + overrides). Stored per user (see §6).
- **Back-compat:** when policy = *Ask me* (default/off), the response is identical to today (`auto_saved=[]`, everything in `proposed_actions`).

### 4.3 MCP (external agents — Claude Code, etc.)
External agents are the strongest case for silent-save (an agent shouldn't block on a human mid-task), but also the riskiest (no human watching). Design:
- **External agents default to accept-all (autonomy 100)** (decision 2026-06-12) — they don't block on a human, so Capture accepts automatically. Safety comes from mandatory provenance + reversibility, not from confirmation.
- **Mandatory provenance tagging** on every agent write: `source.channel="mcp"`, `source.agent=<token identity>`, `origin="auto"`, and `derivation="inferred"` by default (an agent asserting on the user's behalf is an inference unless it passes `derivation="stated"` with evidence). Agent-sourced + `inferred` claims may be down-weighted in retrieval so they don't overpower user-stated memories, and are filterable in the "Recently auto-saved" view.
- Tool responses still include `auto_saved` (with `undo_token`s) and `pending_confirmation` so the agent can surface/undo on its user's behalf.
- A tool param `confirmation_mode: "policy" | "always_confirm" | "never_confirm"` allows per-call override; **hard escalations remain server-enforced** — even at accept-all, conflicts/sensitive/inferred are logged + surfaced in the response and reversible (never silently lost).
- Add an MCP tool `pkb_undo_auto_saves(session_id|claim_ids)` mirroring the REST undo.
- Audit: every MCP auto-save is logged with the agent's token identity.

---

## 5. Implementation Deep-Dive

### 5.1 Where the routing inserts
Single seam in `conversation_distillation.py` (and mirror in `text_ingestion.py`):
- Add `route_candidate(candidate, match, policy) -> "AUTO_SAVE"|"CONFIRM"|"SKIP"` (pure function, unit-testable like the M1 helper).
- In `extract_and_propose()`, after `_propose_actions(...)` builds candidate→action mappings, **partition** into three buckets by `route_candidate`. For the AUTO_SAVE bucket, **execute immediately** (reuse `_execute_action`) and collect saved `claim_id`s; put CONFIRM in `proposed_actions`; record SKIP reasons.
- Extend `MemoryUpdatePlan` with `auto_saved: List[ActionResult]` and `skipped: List[...]`; set `requires_user_confirmation = len(proposed_actions) > 0` (unchanged semantics for the modal).
- Persist `origin=auto`, `auto_saved_at`, `session_id`/`plan_id` on auto-saved claims (metadata already supports `source`/`origin`).

### 5.2 Sensitivity derivation (no new model in v1)
`is_sensitive(candidate) = context_domain in SENSITIVE_DOMAINS or visibility == "restricted"`. The extraction LLM already assigns `context_domain`; for free-text edge cases not captured by domain, a **v2** lightweight keyword/regex or small-LLM sensitivity check can be added behind a flag. Record the chosen reason for auditability.

### 5.3 Config & policy storage
- Add `PKBConfig` fields (all defaulting to today's behavior when the master flag is off): `tiered_persistence_enabled: bool = False`, `auto_save_confidence: float = 0.85`, `skip_confidence: float = 0.45`, `sensitive_domains: tuple`, `high_stakes_types: tuple`, `safe_types: tuple`, `auto_save_undo_window_hours: int = 24` (24h tombstone — clean reversal within the window, finalized after), `silent_merge_enabled: bool = False`.
- **Per-user policy override** persisted in the PKB DB (a small `user_settings`-style row keyed by email) so REST/MCP/UI all read the same policy. Resolve order: per-user override → config default → off.

### 5.4 Undo, audit, telemetry
- Undo reuses existing retract/delete paths; expose via REST + MCP (§4).
- **Audit table / log**: `auto_save_log(email, claim_id, route_reason, confidence, derivation, domain, source, ts)` — drives the wrong-auto-save metric and abuse detection.
- **Telemetry counters** per route lane to watch the silent/confirm/skip mix in production.

### 5.5 Order of work
0. **Verify the STM-silent precedent** (decision 2026-06-12): trace the actual execution path for `short_term_candidates` and confirm STM is persisted **without** user confirmation today (the "already silent" claim currently rests on a dataclass comment, not a traced path). Add a test asserting STM persistence requires no approval. This both validates the design premise and is a cheap correctness check.
1. **Confidence calibration (§5.6) — prerequisite.** Land the improved confidence elicitation *before* tuning thresholds; gating on a miscalibrated score is meaningless.
2. `route_candidate` pure function + unit tests (all branches + a source guard that hard escalations can't be bypassed).
3. Wire partitioning into `conversation_distillation.py` behind `tiered_persistence_enabled` (default OFF → zero behavior change).
4. Mirror in `text_ingestion.py`.
5. REST: response split + `undo` + `recent_auto` + `policy` endpoints.
6. UI: toast + Recently-auto-saved view + settings.
7. MCP: policy-aware tool responses + undo tool + server-enforced hard escalations.
8. Eval harness + gate (§7), including a confidence-calibration check. Only then consider flipping the default.

### 5.6 Confidence calibration (make the gating signal trustworthy)

The whole Capture facet gates on `confidence`; LLM-emitted confidence is notoriously overconfident/uncalibrated. Improve elicitation (decision 2026-06-12) so the score is discriminative:

- **Integer 1–10, not a float.** Ask the LLM for an integer 1–10, not a 0.0–1.0 float (floats invite false precision and cluster at 0.8/0.9). Map to [0,1] for internal thresholds.
- **Verbal-then-numeric.** Require the model to first state a **verbal** confidence label, *then* the number — e.g. "Very confident (the user stated it explicitly) → 9". Anchoring the number to words improves calibration.
- **Anchored rubric.** Give each number a meaning in the prompt (e.g. 10 = user stated verbatim; 7 = clearly implied; 4 = inferred/uncertain; 1 = speculative), so scores are comparable across extractions.
- **Multi-aspect, then combine.** Score **3–4 aspects** rather than one blended number, e.g.:
  - `explicitness` (stated ↔ inferred), `stability` (durable fact ↔ fleeting), `clarity` (unambiguous ↔ vague), `usefulness` (worth remembering ↔ trivial).
  - Combine into the final gating confidence (e.g. weighted min/mean; `explicitness` also feeds `derivation`). Storing the per-aspect scores aids the activity log's "why" and future tuning.
- **Validate calibration in eval (§7):** bucket predicted confidence vs human-judged correctness (reliability curve); the auto-save threshold is chosen from that curve, not guessed. If confidence isn't discriminative even after this, fall back to a more conservative policy (e.g. only `derivation=stated` + `safe_types` auto-save, ignoring the numeric score).
- Touch points: the extraction prompts in `conversation_distillation.py` (`_extract_claims_from_turn`, both relaxed/aggressive) and `text_ingestion.py`; parse the per-aspect scores into `CandidateClaim`.

---

## 6. Config Knobs (summary)

| Knob | Default | Meaning |
|------|---------|---------|
| `tiered_persistence_enabled` | **False** | Master switch; off = today's all-confirm |
| `auto_save_confidence` | 0.85 | Min confidence for Lane A |
| `skip_confidence` | 0.45 | Below this → Lane C skip |
| `sensitive_domains` | health, finance, relationships | Always confirm |
| `high_stakes_types` | decision, task, reminder | Always confirm |
| `safe_types` | fact, preference, habit, observation, memory | Eligible for Lane A |
| `silent_merge_enabled` | False | Reinforce near-dups instead of skipping |
| `auto_save_undo_window_hours` | 24 | 24h tombstone: clean undo within window, finalized after |
| (per-user) `memory_autonomy_preset` | ask_me | ask_me / balanced / just_remember |

---

## 7. Rollout & Evaluation (inert-by-default, eval-gated)

Matches the project's philosophy (cf. the W-D tag strategy): **ship the code OFF, prove it on an eval set, then flip per-user.**

1. **Phase 0 — inert.** Land the policy + plumbing with `tiered_persistence_enabled=False`. Full suite stays green; behavior identical.
2. **Phase 1 — eval.** Build/extend a labeled set of conversation turns with gold labels: for each extracted candidate, the "correct" lane (a human-judged should-this-have-been-silent). Measure: wrong-auto-save precision (Lane-A items a human would have rejected), missed-save recall, friction reduction (modal rate), and that **100% of conflicts/inferred/sensitive are escalated** (hard-gate must be inviolable). Reuse the eval harness under `truth_management_system/tests/eval/`.
3. **Phase 2 — opt-in.** Enable *Balanced* for opt-in users; watch the production wrong-auto-save (undo) rate and telemetry.
4. **Phase 3 — default.** Flip *Balanced* on by default only if Phase 2 wrong-auto-save rate stays under target and undo usage is low.

**Gate to flip default:** wrong-auto-save (undo within window) < 3%, hard-escalation coverage = 100%, measurable modal-rate reduction, no recall regression vs baseline.

---

## 8. Risks

- **Silent wrong memory (core risk):** a bad Lane-A save biases retrieval invisibly. Mitigations: conservative `auto_save_confidence`, hard escalations, always-visible toast + review list + easy undo, and the eval gate. Start strict; loosen only on evidence.
- **Decision-tree brittleness:** thresholds may misroute. Mitigation: per-user presets, telemetry on the lane mix, and the audit log to retune.
- **Sensitivity false-negatives:** domain mislabeled by the extractor → a sensitive fact auto-saves. Mitigation: treat `inferred` and `restricted` as additional gates; v2 sensitivity classifier; conservative defaults.
- **MCP over-trust:** an external agent setting `never_confirm`. Mitigation: hard escalations are **server-enforced**, never client-overridable.
- **Undo reliability:** undo must fully remove from retrieval. Mitigation: reuse the tested retract path; integration test that undone claims don't surface in search.
- **Cross-surface policy drift:** UI/REST/MCP must read one policy. Mitigation: single per-user policy store (§5.3).

---

## 9. Files Likely Touched

| File | Change |
|------|--------|
| `truth_management_system/interface/conversation_distillation.py` | `route_candidate()`; partition into auto_save/confirm/skip; auto-execute Lane A; extend `MemoryUpdatePlan` |
| `truth_management_system/interface/text_ingestion.py` | Mirror routing for bulk ingest proposals |
| `truth_management_system/config.py` | New policy config fields (default OFF) |
| `truth_management_system/models.py` / `constants.py` | `origin=auto` + `auto_saved_at` metadata; (no new enums required) |
| `truth_management_system/database.py` | Per-user policy row + `auto_save_log` audit table |
| `endpoints/pkb.py` | Response split (`auto_saved`/`skipped`); `POST /pkb/memory/undo`; `GET /pkb/memory/recent_auto`; `GET/PUT /pkb/memory/policy` |
| `mcp_server/pkb.py` (→ package, per other plan) | Policy-aware tool responses; `pkb_undo_auto_saves`; server-enforced hard escalations |
| `interface/pkb-manager.js` | Silent-save toast + Undo; "Recently auto-saved" view; "Memory autonomy" settings |
| `truth_management_system/tests/eval/` + `tests/` | `route_candidate` unit tests (+ hard-gate guard); routing eval set + harness |
| docs | `chat_app_capabilities.md`, TMS feature docs, this plan |

---

## 10. Resolved Decisions

| Decision | Resolution |
|----------|-----------|
| Score vs decision tree | Decision tree for v1 (auditable, tunable); weighted score is a v2 candidate |
| New sensitivity classifier? | No — derive from `context_domain`/`visibility`/`derivation` in v1 |
| Where do auto-saves live? | `status=ACTIVE`, `origin=auto` (retrievable), undo via retract; not `draft` (draft would be excluded from retrieval) |
| Default behavior | Inert — `tiered_persistence_enabled=False` ships first; identical to today |

---

## 11. Open Questions

### Resolved (2026-06-12)
- **Auto-save undo window:** **24h tombstone** — clean reversal within 24h, finalized after.
- **Silent edits:** updates to existing claims **auto-apply when low-risk** (non-sensitive, stated/extracted, confident, non-conflicting) — at lower autonomy for low-risk items, more broadly at higher autonomy; risky updates confirm (below Full) or notify+undo (Full). See §3.3.
- **MCP default:** external agents default to **accept-all (100)** with mandatory provenance tagging (`origin=auto`, `derivation=inferred`, agent identity); hard escalations stay server-enforced. See §4.3.
- **Confidence trustworthiness:** improve elicitation (integer 1–10, verbal-then-numeric, anchored rubric, 3–4 aspects combined) and validate calibration in eval before threshold tuning. See §5.6.

### Still open
1. **Per-domain confidence thresholds:** one global `auto_save_confidence`, or per `context_domain`/`claim_type` thresholds?
2. **Notification batching:** how aggressively to coalesce toasts when many items save in one turn?
3. **v2 risk score:** replace the tree with `risk = f(confidence, sensitivity, derivation, conflict, importance)` and a single threshold — worth it once we have eval data?
4. **Reinforcement (silent merge):** ship §3.4 in v1 or defer?
