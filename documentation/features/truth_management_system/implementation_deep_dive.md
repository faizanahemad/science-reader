# Truth Management System (PKB v0) - Implementation Deep Dive

**Document Purpose:** Comprehensive technical documentation for developers working on or integrating with the Truth Management System. Includes architecture, data flows, file responsibilities, and integration patterns.

**Last Updated:** 2026-02-07  
**Current Version:** v0.6

> **Note:** The core sections below (Architecture through Troubleshooting) were written for v0.4.1 and remain accurate for foundational concepts. The **[v0.5+ Addendum](#v05-addendum)** section documents v0.5.0 and v0.5.1 features. The **[v0.6 Addendum](#v06-addendum)** section documents the latest features: claim_number, possible_questions (QnA), unified search+filter endpoint, search+filter unification in UI, and context search panel.

---

## Table of Contents

0. [Retrieval Ranking Improvements (W-A/W-B/W-C)](#retrieval-ranking-improvements-w-a--w-b--w-c) — weighted RRF, query scoping, entity retrieval
0a. [v0.6 Addendum](#v06-addendum) — **Latest: claim numbers, QnA, unified search**
0b. [v0.5+ Addendum](#v05-addendum) — Friendly IDs, contexts, autocomplete
1. [Architecture Overview](#architecture-overview)
2. [Module Structure & Responsibilities](#module-structure--responsibilities)
3. [Data Flow Patterns](#data-flow-patterns)
4. [Integration Patterns](#integration-patterns)
5. [API Surface](#api-surface)
5a. [Contexts (Groups): Hierarchy & Resolution](#contexts-groups-hierarchy--resolution)
5b. [Intelligence Layer: Auto-Parsing, Connections & Conflict Detection](#intelligence-layer-auto-parsing-connections--conflict-detection)
5c. [PKB Tool Surfaces (MCP vs LLM Tool-Calling vs REST)](#pkb-tool-surfaces-mcp-vs-llm-tool-calling-vs-rest)
6. [Frontend Architecture](#frontend-architecture)
7. [Multi-User Implementation](#multi-user-implementation)
8. [Memory Attachment System](#memory-attachment-system)
9. [Search Architecture](#search-architecture)
10. [Common Development Patterns](#common-development-patterns)
11. [Testing Strategy](#testing-strategy)
12. [Troubleshooting Guide](#troubleshooting-guide)

---

## Auto-Fill / Statement Analysis (v0.7+)

### Overview

A shared LLM-powered analysis method that extracts all claim metadata (type, domain, tags, entities, possible_questions) from a statement in a **single LLM call**. Used by:

1. **Add Memory modal "Auto-fill" button** — uses `VERY_CHEAP_LLM[0]` (fast, low-cost) for interactive UI
2. **Text Ingestion enrichment** — uses `CHEAP_LLM[0]` (slightly better model) to enrich parsed candidates

### New Endpoint: `POST /pkb/analyze_statement`

| Field | Value |
|-------|-------|
| Rate limit | 20/min |
| Auth | `@login_required` |

**Request:** `{"statement": "I prefer morning workouts"}`

**Response:**
```json
{"success": true, "analysis": {
    "claim_type": "preference",
    "context_domain": "health",
    "tags": ["morning_exercise", "fitness", "routine"],
    "entities": [{"type": "topic", "name": "morning workouts", "role": "object"}],
    "possible_questions": ["Do I prefer morning or evening workouts?", "What is my exercise routine preference?"],
    "confidence": 0.9
}}
```

### UI: Auto-fill Button

A small `<i class="bi bi-magic"></i> Auto-fill` link button sits below `#pkb-claim-statement` textarea (ID: `#pkb-autofill-btn`). On click:

1. `autofillClaimFields()` in `pkb-manager.js` reads the statement
2. Calls `POST /pkb/analyze_statement`
3. Populates Type, Domain, Tags, and Possible Questions fields
4. Shows loading spinner during the LLM call

### Text Ingestion Enrichment

After `_parse_text_with_llm()` extracts candidates, `_enrich_candidates()` runs `analyze_claim_statement()` on each candidate (max 20) to populate tags, entities, and possible_questions. These are then passed through to `_execute_proposal()` → `add_claim()`.

### Backend: Shared Method

`LLMHelpers.analyze_claim_statement(statement, model=None)` → `ClaimAnalysisResult`

The `ClaimAnalysisResult` dataclass: `claim_type`, `context_domain`, `tags`, `entities`, `possible_questions`, `confidence`.

### Files Modified

| File | Changes |
|------|---------|
| `truth_management_system/llm_helpers.py` | `ClaimAnalysisResult` dataclass, `analyze_claim_statement()` method |
| `truth_management_system/__init__.py` | Export `ClaimAnalysisResult` |
| `truth_management_system/interface/text_ingestion.py` | `IngestCandidate` gains `tags`, `possible_questions`, `entities` fields; `_enrich_candidates()` method; `_execute_proposal()` passes enriched fields |
| `endpoints/pkb.py` | `POST /pkb/analyze_statement` route; ingest proposal serialization includes tags/questions/entities |
| `interface/interface.html` | `#pkb-autofill-btn` button below statement textarea |
| `interface/pkb-manager.js` | `autofillClaimFields()` function; click handler in `init()` |

---

## Retrieval Ranking Improvements (W-A / W-B / W-C)

Three eval-gated improvements to hybrid retrieval ranking. Each defaults to the
prior behavior (or is inert for queries that don't trigger it) and is gated by
`PKBConfig`, so they can be rolled out and tuned independently.

### W-A — Weighted RRF fusion

`merge_results_rrf(result_lists, k, rrf_k, strategy_weights=None)` adds an
optional per-strategy multiplier on each list's reciprocal-rank contribution:
`score += weight[source] * 1/(rank + rrf_k)`. Weights are keyed by
`SearchResult.source` (`"fts"`, `"embedding"`, `"rewrite"`, `"entity"`).
`HybridSearchStrategy.search` passes `config.rrf_strategy_weights`; an empty dict
(the default) makes every weight `1.0`, reproducing plain unweighted RRF
exactly. Intended use after eval tuning: trust semantic/embedding above literal
FTS, e.g. `{"fts": 0.6, "embedding": 1.0, "rewrite": 1.0, "entity": 0.8}`.
`rrf_k` stays fixed at 60 during tuning.

### W-B — Per-strategy query scoping

Literal FTS no longer receives the summary-laden contextual query. `search` /
`_execute_parallel` accept an optional `strategy_queries: Dict[str, str]` map;
`_query_for(name)` returns the override for a strategy or falls back to the base
`query` (so `None` is an exact no-op). `StructuredAPI.search` threads the map on
the `hybrid` strategy only. `Conversation._get_pkb_context` sets
`{"fts": <current message>, "entity": <current message>}` when
`config.fts_use_focused_query` is True (default), so FTS reflects *current*
intent and the entity strategy resolves entities from the current message (not
past-topic summary text), while embedding/rewrite keep the contextual
`enhanced_query`. The STM `<stm_context>` prepend and the
post-distillation `last_accessed_at` update are preserved untouched. Fallback
when no LLM key: FTS uses the current message, never the summary.

### W-C — Entity-linked retrieval strategy

`EntitySearchStrategy` (`search/entity_search.py`, `source="entity"`)
participates in RRF fusion as another ranked list:

1. Extract capitalized / quoted surface forms from the query.
2. Resolve to entities by exact (case-insensitive) name match, plus
   `meta_json.aliases` (W6) when `entity_alias_match` is set. Exact matching
   makes the loose extraction self-filtering.
3. Pull linked claims via `EntityCRUD.resolve_claims`, which applies the status
   filter (default active + contested) and user scope — so compaction-archived /
   superseded / expired claims are **not** resurfaced through the entity path.
4. Rank by cosine similarity to the query embedding (reusing the `EmbeddingStore`
   cache); degrade to recency order when no query embedding is available.
5. Return top-N (`entity_strategy_top_n`, default 5); `[]` when disabled, the
   query is empty, or nothing resolves (RRF no-op).

Registered in `HybridSearchStrategy` independent of the API key (it works
offline, degrading to recency order) behind `entity_strategy_enabled`, and added
to the default fusion set. RRF sums the reciprocal-rank scores of a claim found
by both embedding and entity link (it rises to the top) and de-dupes by
`claim_id` automatically.

### Rewrite/entity unification — single LLM call, single RRF

The overview-aware rewrite is the single source of query derivation. When
`rewrite_is_query_source` is set, an API key is present, and `rewrite` is an
active strategy, `HybridSearchStrategy._build_strategy_context` makes ONE
`_rewrite_query` LLM call up front and packages its `RewriteMetadata` into a
`strategy_context: Dict[str, Any]` threaded alongside `strategy_queries`:

- the **rewrite** strategy receives `precomputed_metadata` and skips its own LLM
  call (no double-call);
- the **entity** strategy receives the LLM `entities` as `surface_forms` (when
  `entity_use_rewrite_entities` is set) — resolving higher-quality names than the
  regex heuristic, capped at `entity_strategy_max_entities` — plus a reusable
  query vector of the rewrite's `embedding_query` for cosine ranking.

`_execute_parallel` dispatches these reuse kwargs **only** to the rewrite/entity
strategies (the base `SearchStrategy.search(query, k, filters)` interface is
untouched). All four strategies remain distinct RRF sources, so W-A per-source
weighting and the single top-level fusion are preserved — there is no
fusion-of-fusions for the entity signal. The path is inert (current behavior)
without a key, when `rewrite` is not active, or when the flags are off: the
entity strategy falls back to regex extraction and the rewrite strategy
self-calls. See `tests/test_rewrite_entity_unification.py` (asserts exactly one
rewrite LLM call) and the plan
`documentation/planning/plans/pkb_rewrite_entity_unification.plan.md`.

**Corpus parity (migration).** No schema change — `claim_entities` already
exists. Claims predating entity extraction simply have no links and are still
retrieved by FTS/embedding/rewrite; the optional, idempotent
`StructuredAPI.backfill_entities(dry_run=, limit=)` links entities for unlinked
active claims (mirrors `backfill_embeddings`), raising entity-path recall on the
existing corpus without being required for correctness.

### Config fields

| Field | Default | Workstream |
|-------|---------|-----------|
| `rrf_strategy_weights: Dict[str, float]` | `{}` (unweighted) | W-A |
| `fts_use_focused_query: bool` | `True` | W-B |
| `entity_strategy_enabled: bool` | `True` | W-C |
| `entity_strategy_top_n: int` | `5` | W-C |
| `entity_alias_match: bool` | `True` | W-C |
| `entity_strategy_max_entities: int` | `5` | W-C (anti-flooding cap) |
| `rewrite_is_query_source: bool` | `True` | Unification (single rewrite call) |
| `entity_use_rewrite_entities: bool` | `True` | Unification (entity uses LLM entities) |

All are wired through `to_dict` / `from_dict` / env (`PKB_*`;
`PKB_RRF_STRATEGY_WEIGHTS` is JSON).

### Eval & verification notes

The offline harness (`tests/eval/`, no `OPENROUTER_API_KEY`) runs FTS-only, so it
**cannot** measure W-A fusion or W-C cosine ranking; W-B's value lives in
`_get_pkb_context` (summary pollution), which eval queries don't exercise. The
harness was extended to seed entities + `claim_entities` links and added
entity-mention cases plus an offline `[entity]` strategy set: offline the entity
strategy alone scores recall@5 = 1.000 / mrr = 0.833 on the entity category
(returns nothing for non-entity queries; in production it is fused via RRF).
Fusion-level and cosine tuning require a keyed run of `run_eval.sh`. Unit tests:
`tests/test_weighted_rrf.py`, `tests/test_query_scoping.py`,
`tests/test_entity_strategy.py`.

---

## v0.6 Addendum

This section documents all features added in v0.6 (schema versions 5 and 6), building on the v0.5 foundation.

### Schema Evolution: v4 → v5 → v6

**v5: Claim Numbers**
- Added `claim_number INTEGER` column to `claims` table
- Per-user auto-incremented numeric identifier (assigned in `ClaimCRUD.add()`)
- Referenceable in chat as `@claim_42` — parsed by `parseMemoryReferences()` regex
- Migration `_migrate_v4_to_v5()`: adds column, backfills existing claims sequentially per user by `created_at`, creates index `idx_claims_user_claim_number`
- `ClaimCRUD.get_by_claim_number(claim_number)`: lookup by numeric ID (user-scoped)

**v6: Possible Questions (QnA)**
- Added `possible_questions TEXT` column to `claims` table (stores JSON array of question strings)
- Enables QnA-style retrieval: search matches user questions against stored possible questions
- Migration `_migrate_v5_to_v6()`: adds column, rebuilds `claims_fts` to include `possible_questions`
- `LLMHelpers.generate_possible_questions(statement, claim_type)`: generates 2-4 self-sufficient questions via LLM
- Each question must contain the specific subjects/entities from the claim so it is understandable on its own without reading the claim
- Example: "I am allergic to peanuts" → `["Do I have a peanut allergy?", "Should I avoid peanut-containing foods?"]`
- NOT: `["Am I allergic to anything?"]` — too vague, not self-sufficient

### Unified Search + Filter Endpoint

**Before v0.6:** Two separate endpoints:
- `GET /pkb/claims` — list with filters (type, domain, status, limit, offset)
- `POST /pkb/search` — text search with strategy and filters

**After v0.6:** Single unified `GET /pkb/claims`:
- When `query` parameter is absent → list mode (DB query with filters, pagination)
- When `query` parameter is present → search mode (hybrid/fts/embedding with filters)
- Query params: `query`, `strategy`, `claim_type`, `context_domain`, `status`, `limit`, `offset`
- Always returns `{"claims": [...], "count": N}` — same shape regardless of mode
- `POST /pkb/search` kept for backwards compatibility but UI no longer calls it

**Frontend unification:**
- `listClaims(filters, limit, offset, query, strategy)` now accepts optional `query` param
- `loadClaims()` reads both `#pkb-search-input` and all filter dropdowns, passes to single `listClaims()` call
- `performSearch()` is now a one-liner: `currentPage = 0; loadClaims()`
- This means search and filters always work together — no more dual-path issue

### Universal Claim Identifier Resolution

`StructuredAPI.resolve_claim_identifier(identifier)` accepts any format a user might type:

| Input | Resolution Strategy |
|-------|-------------------|
| `42` | `get_by_claim_number(42)` |
| `claim_42` | parse `claim_(\d+)`, then `get_by_claim_number(42)` |
| `@claim_42` | strip `@`, then as above |
| `550e8400-...` (UUID) | direct `get(claim_id)` |
| `prefer_morning_a3f2` | `get_by_friendly_id()` |
| `@prefer_morning_a3f2` | strip `@`, then `get_by_friendly_id()` |

Used by: `GET /pkb/claims/by-friendly-id/<id>` endpoint, `POST /pkb/contexts/<id>/claims` endpoint (accepts any ID format to link claims).

### Auto-Generation on Edit

When editing a claim via `StructuredAPI.edit_claim()`:
1. **friendly_id**: If claim has none and none provided → `ClaimCRUD.edit()` auto-generates via `generate_friendly_id(statement)` (stopword-filtered heuristic, 1-3 words + 4-char suffix)
2. **possible_questions**: If claim has none and none provided and LLM available → `edit_claim()` calls `llm.generate_possible_questions(statement, claim_type)` to generate 2-3 questions

### Improved `generate_friendly_id()`

Updated to produce shorter, more descriptive IDs:
- Comprehensive stopword list (80+ words): removes pronouns, articles, auxiliary verbs, prepositions, conjunctions
- Takes only 1-3 meaningful words (down from 4)
- Max 60 characters (down from 120)
- Examples: "I prefer morning workouts" → `prefer_morning_workouts_a3f2`, "My favorite color is blue" → `favorite_color_blue_6e98`

### Context Search Panel (UI)

When expanding a context card, the panel shows two sections:

1. **Linked Memories** — claims currently in the context, each with an unlink button
2. **Add Memories** — search bar + Type/Domain filter dropdowns + results with checkboxes
   - Text search uses the unified `listClaims()` endpoint
   - ID lookups (`#N`, `@claim_N`, `@friendly_id`) try `GET /pkb/claims/by-friendly-id/` first
   - Checking a checkbox links the claim; unchecking unlinks it
   - Results show `#claim_number`, `@friendly_id`, type badge, domain

### Search Filter Fix

`StructuredAPI.search()` now accepts both singular and plural filter keys:
- `claim_type: "fact"` (string) → maps to `claim_types: ["fact"]`
- `claim_types: ["fact", "preference"]` (array) → used directly
- Same for `context_domain`/`context_domains` and `status`/`statuses`

### Claim Card Display

`renderClaimCard()` now shows:
- `#N` badge (dark, monospace) — claim_number
- `@friendly_id` badge (light, monospace) — friendly_id
- Type badge, domain badge, pinned/contested badges
- Updated timestamp

### Edit Modal Fields

The claim Add/Edit modal (`#pkb-claim-edit-modal`) now contains:
1. Statement (textarea)
2. Friendly ID (text input with `@` prefix)
3. Type (multi-select, populated from `GET /pkb/types`, with inline "Add New" input)
4. Domain (multi-select, populated from `GET /pkb/domains`, with inline "Add New" input)
5. Tags (comma-separated text)
6. Possible Questions (textarea, one per line, auto-generated if blank)
7. Contexts (multi-select, populated from `GET /pkb/contexts`)

### Modal Entry Points

| Trigger | Location | Mode | Notes |
|---------|----------|------|-------|
| `#pkb-add-claim-btn` click | `pkb-manager.js` init() | Add (blank) | Opens via `openAddClaimModal()` |
| `.pkb-edit-claim` button on claim cards | `pkb-manager.js` `bindClaimCardActions()` | Edit | Opens via `openEditClaimModal(claimId)` |
| `.pkb-entity-add-memory` on entity cards | `pkb-manager.js` | Add (with entity link) | Also sets `_pendingEntityLink` |
| "Save to Memory" in message triple-dots | `common.js` `initialiseVoteBank()` | Add (pre-filled) | Calls `PKBManager.openAddClaimModalWithText(text)`. Strips `<answer>` tags. Defaults type to `fact`, domain to `personal`. |

### Conversation.py Context Formatting

When formatting claims for the LLM system prompt, `_get_pkb_context()` now includes possible_questions as a hint:
```
- [REFERENCED @fid] [fact] I am allergic to peanuts (answers: Do I have a peanut allergy?; Should I avoid peanut-containing foods?)
```

### Data Flow: Unified Search + Filter

```
User types query + selects filters in Claims tab
    ↓
loadClaims() reads #pkb-search-input + filter dropdowns
    ↓
listClaims(filters, limit, offset, query) builds URL params
    ↓
GET /pkb/claims?query=age&claim_type=preference&status=active
    ↓
pkb_list_claims_route() detects query param
    ↓ (query present)
api.search(query, filters=filters) → HybridSearchStrategy
    ↓
SearchFilters(claim_types=["preference"], statuses=["active"])
    ↓
FTS + Embedding parallel search with SQL WHERE filters
    ↓
RRF merge → deduplicate → serialize → {"claims": [...], "count": N}
```

### Data Flow: Context @Reference in Chat

```
User types: "Check @work_context_a3b2 for details"
    ↓
parseMemoryReferences() regex captures "work_context_a3b2"
    ↓
sendMessage() includes referenced_friendly_ids: ["work_context_a3b2"]
    ↓
Server passes query dict to Conversation.reply()
    ↓
_get_pkb_context() receives referenced_friendly_ids
    ↓
api.resolve_reference("work_context_a3b2")
    ↓ (step 1: not a claim_N)
    ↓ (step 2: claims.get_by_friendly_id → no match)
    ↓ (step 3: contexts.get_by_friendly_id → MATCH)
    ↓
contexts.resolve_claims(context_id) → recursive claim collection
    ↓
All claims added to context with [REFERENCED @work_context_a3b2] label
    ↓
Formatted as: "- [REFERENCED @work_context_a3b2] [fact] Claim text (answers: Q1; Q2)"
```

### New REST Endpoints (v0.6)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/claims?query=...` | Unified list/search (added `query`, `strategy` params) |
| GET | `/pkb/types` | List all valid claim types (system + custom) |
| POST | `/pkb/types` | Add custom claim type |
| GET | `/pkb/domains` | List all valid context domains (system + custom) |
| POST | `/pkb/domains` | Add custom context domain |

### Files Modified (v0.6)

| File | Changes |
|------|---------|
| `schema.py` | SCHEMA_VERSION=6, `claim_number` (v5), `possible_questions` (v6) columns |
| `database.py` | `_migrate_v4_to_v5()`, `_migrate_v5_to_v6()`, dynamic FTS column detection in `_ensure_fts_v3()` |
| `models.py` | `claim_number`, `possible_questions` fields in Claim, CLAIM_COLUMNS |
| `utils.py` | Improved `generate_friendly_id()` with 80+ stopwords, 1-3 words |
| `llm_helpers.py` | `generate_possible_questions()` method |
| `crud/claims.py` | `get_by_claim_number()`, auto-assign `claim_number` in `add()`, auto-generate `friendly_id` on `edit()` |
| `crud/catalog.py` | `TypeCatalogCRUD`, `DomainCatalogCRUD` (v0.5.1, documented here for completeness) |
| `interface/structured_api.py` | `resolve_claim_identifier()`, `possible_questions` handling in `add_claim()`/`edit_claim()`, context name fallback in `resolve_reference()`, search filter normalization |
| `endpoints/pkb.py` | Unified `GET /pkb/claims` with `query` param, `GET/POST /pkb/types`, `GET/POST /pkb/domains`, updated `serialize_claim()`, `friendly_id` in PUT allowed fields |
| `interface/pkb-manager.js` | `listClaims()` with `query` param, unified `loadClaims()`, context search panel, `populateTypesDropdown/DomainsDropdown`, `saveClaim()` with friendly_id/possible_questions/contexts, `#claim_number` badge in `renderClaimCard()` |
| `interface/interface.html` | Possible questions textarea, multi-select type/domain/context fields, inline add-new-type/domain inputs |
| `Conversation.py` | `possible_questions` in context formatting, debug logging for referenced_friendly_ids, `_extract_referenced_claims()` for post-distillation re-injection of referenced claims |
| `search/fts_search.py` | `possible_questions` in `allowed_columns` |

---

## v0.5+ Addendum

This section documents all features added in v0.5.0 and v0.5.1. For full design decisions, see [PKB_V05_ENHANCEMENT_PLAN.md](./PKB_V05_ENHANCEMENT_PLAN.md).

### Schema Evolution: v2 → v3 → v4

**v3 (v0.5.0):** Added `friendly_id`, `claim_types` (JSON), `context_domains` (JSON) columns to `claims`. Created `contexts` and `context_claims` tables. Rebuilt `claims_fts` to include `friendly_id`.

**v4 (v0.5.1):** Added `claim_types_catalog` and `context_domains_catalog` tables. These replace hardcoded Python enums with DB-backed storage, allowing users to add custom types and domains.

**Migration path:** `database.py` handles automatic migration via `_migrate_v1_to_v2()`, `_migrate_v2_to_v3()`, `_migrate_v3_to_v4()`. Idempotent fixups (`_ensure_fts_v3()`, `_ensure_catalog_seeded()`) run on every startup.

### New CRUD Modules

| Module | Class | Purpose |
|--------|-------|---------|
| `crud/contexts.py` | `ContextCRUD` | Hierarchical context CRUD: add, edit, delete, resolve_claims (recursive), add_claim, remove_claim, get_contexts_for_claim, cycle detection |
| `crud/catalog.py` | `TypeCatalogCRUD` | List/add/delete claim types (system + user-defined) |
| `crud/catalog.py` | `DomainCatalogCRUD` | List/add/delete context domains (system + user-defined) |

### New REST Endpoints

**v0.5.0 Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/claims/by-friendly-id/<fid>` | Get claim by friendly_id |
| GET | `/pkb/autocomplete?q=prefix` | Autocomplete for @references |
| GET | `/pkb/resolve/<reference_id>` | Resolve @reference to claims |
| GET/POST | `/pkb/contexts` | List/create contexts |
| GET/PUT/DELETE | `/pkb/contexts/<id>` | Get/update/delete context |
| POST | `/pkb/contexts/<id>/claims` | Link claim to context |
| DELETE | `/pkb/contexts/<id>/claims/<cid>` | Unlink claim from context |
| GET | `/pkb/contexts/<id>/resolve` | Recursive claim resolution |
| POST | `/pkb/entities` | Create entity |
| GET/POST/DELETE | `/pkb/claims/<id>/entities[/<eid>]` | Entity linking |

**v0.5.1 Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/entities/<id>/claims` | Claims linked to an entity |
| GET | `/pkb/tags/<id>/claims` | Claims linked to a tag |
| POST | `/pkb/tags` | Create a new tag |
| GET | `/pkb/claims/<id>/tags` | Tags linked to a claim |
| POST | `/pkb/claims/<id>/tags` | Link a tag to a claim |
| DELETE | `/pkb/claims/<id>/tags/<tid>` | Unlink a tag from a claim |
| GET | `/pkb/claims/<id>/contexts` | Contexts a claim belongs to |
| PUT | `/pkb/claims/<id>/contexts` | Set claim's contexts (diff-based) |
| GET/POST | `/pkb/types` | List/add claim types |
| GET/POST | `/pkb/domains` | List/add context domains |

### Friendly IDs and @References

Claims and contexts have `friendly_id` fields (alphanumeric + underscores/hyphens). Auto-generated from statement text if not user-specified. Used for `@friendly_id` references in chat messages.

**Resolution flow in `Conversation.py._get_pkb_context()`:**
1. Extract `@friendly_id` patterns from user message via `parseMemoryReferences()` in `parseMessageForCheckBoxes.js`
2. Pass `referenced_friendly_ids` to `_get_pkb_context()`
3. For each friendly_id, call `api.resolve_reference(fid)` — tries claim first, then context
4. Context resolution recursively collects all leaf claims
5. Claims added to context with `[REFERENCED @friendly_id]` source label

### Frontend: Expandable Views (v0.5.1)

**Pattern:** Entity, tag, and context cards are rendered as Bootstrap cards with collapsible bodies. On first expand, claims are lazy-loaded via AJAX and cached. All expanded views now show two sections: **Linked Memories** (with unlink buttons) and **Add Memories** (search panel with type/domain filters and link/unlink checkboxes).

| View | Data Source | Extra Controls |
|------|-------------|----------------|
| Entity | `GET /pkb/entities/<id>/claims` | "Add Memory" button (opens add modal with entity link), search panel with link/unlink checkboxes, per-claim unlink button |
| Tag | `GET /pkb/tags/<id>/claims` | Search panel with link/unlink checkboxes, per-claim unlink button |
| Context | `GET /pkb/contexts/<id>` | "Attach Memory" (prompt), search panel with link/unlink checkboxes, per-claim unlink button |

All three views use the same architectural pattern: `toggle*Claims()` -> `load*ClaimsPanel()` (AJAX fetch + render linked claims + search-to-add panel) -> `perform*Search()` -> `render*SearchResults()` (checkboxes that call link/unlink endpoints). CSS class prefixes: `pkb-ent-` (entity), `pkb-tag-` (tag), `pkb-ctx-` (context).

### Frontend: Claim Edit Modal Enhancements (v0.5.1)

The claim Add/Edit modal now includes:
- **Type** — multi-select dropdown, populated from `GET /pkb/types`, with inline "Add New" input
- **Domain** — multi-select dropdown, populated from `GET /pkb/domains`, with inline "Add New" input
- **Contexts** — multi-select dropdown, populated from `GET /pkb/contexts`, pre-selected with claim's current contexts (fetched via `GET /pkb/claims/<id>/contexts`)

On save, `saveClaim()` chains: create/update claim → `PUT /pkb/claims/<id>/contexts` → optional entity link.

### Bug Fixes Applied (Post-v0.5.0)

1. **`no such column: friendly_id`** — `initialize_schema()` now ensures v3 columns exist on every call (not just first init). `ClaimCRUD.add()` uses `_get_actual_claim_columns()` for dynamic column detection. `_ensure_fts_v3()` upgrades FTS idempotently.
2. **`IngestProposal.match` AttributeError** — Fixed `pkb_ingest_text_route()` to use `proposal.existing_claim` and `proposal.similarity_score`.
3. **Text ingestion LLM timeout** — Changed `_execute_proposal()` to use `auto_extract=False` since analysis was already done in proposal phase.

### StructuredAPI New Attributes (v0.5.1)

```python
api = StructuredAPI(db, keys, config, user_email="user@example.com")
api.contexts        # ContextCRUD instance
api.type_catalog    # TypeCatalogCRUD instance
api.domain_catalog  # DomainCatalogCRUD instance

# Tag linking methods (two-way: claim gets the tag, tag's claims list includes the claim)
api.link_tag_to_claim(claim_id, tag_id)      # -> ActionResult
api.unlink_tag_from_claim(claim_id, tag_id)  # -> ActionResult
api.get_claim_tags_list(claim_id)            # -> ActionResult with list of Tag objects

# Entity linking methods (existing, listed for reference)
api.link_entity_to_claim(claim_id, entity_id, role)  # -> ActionResult
api.unlink_entity_from_claim(claim_id, entity_id)    # -> ActionResult
api.get_claim_entities_list(claim_id)                 # -> ActionResult with list of (Entity, role)
```

---

## Architecture Overview

### System Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                     USER INTERFACES                              │
│  - interface/interface.html (PKB Modal UI)                       │
│  - interface/pkb-manager.js (Frontend API wrapper)              │
│  - Conversation.py (_get_pkb_context integration)               │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                     REST API LAYER                               │
│  - endpoints/pkb.py (Flask Blueprint)                            │
│    * All /pkb/* endpoints                                        │
│    * Authentication & rate limiting                              │
│    * Request/response serialization                              │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                  INTERFACE LAYER                                 │
│  - StructuredAPI (unified programmatic API)                      │
│  - ConversationDistiller (chat fact extraction)                  │
│  - TextIngestionDistiller (bulk text import)                     │
│  - TextOrchestrator (natural language commands)                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                    SEARCH LAYER                                  │
│  - HybridSearchStrategy (orchestrator)                           │
│  - FTSSearchStrategy (SQLite FTS5/BM25)                         │
│  - EmbeddingSearchStrategy (cosine similarity)                   │
│  - RewriteSearchStrategy (LLM → FTS)                            │
│  - MapReduceSearchStrategy (LLM scoring)                         │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                     CRUD LAYER                                   │
│  - ClaimCRUD (claims data access)                                │
│  - NoteCRUD (notes data access)                                  │
│  - EntityCRUD (entities management)                              │
│  - TagCRUD (tags & hierarchy)                                    │
│  - ConflictCRUD (conflict resolution)                            │
│  - BaseCRUD (shared abstractions)                                │
└──────────────────────┬──────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────────┐
│                  PERSISTENCE LAYER                               │
│  - PKBDatabase (connection & transaction management)             │
│  - Schema management (DDL + migrations)                          │
│  - SQLite with WAL mode                                          │
│  - FTS5 virtual tables                                           │
└─────────────────────────────────────────────────────────────────┘
```

### Cross-Cutting Concerns

```
┌─────────────────────────────────────────────────────────────────┐
│                    SUPPORTING MODULES                            │
│                                                                  │
│  LLMHelpers          │  Parallel execution, tag/entity           │
│  (llm_helpers.py)    │  extraction, similarity checking          │
│                      │                                           │
│  Utilities           │  UUID generation, ISO timestamps,         │
│  (utils.py)          │  JSON helpers, ParallelExecutor           │
│                      │                                           │
│  Configuration       │  PKBConfig management, env/file loading   │
│  (config.py)         │                                           │
│                      │                                           │
│  Models & Constants  │  Dataclasses, enums, validation           │
│  (models.py,         │                                           │
│   constants.py)      │                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module Structure & Responsibilities

### Core Implementation Files

#### 1. Database & Schema (`database.py`, `schema.py`)

**database.py Responsibilities:**
- Connection pooling and lifecycle management
- Transaction context manager
- Schema initialization and migration
- WAL mode configuration
- Foreign key constraint enforcement

**Key Classes:**
```python
class PKBDatabase:
    def __init__(self, config: PKBConfig)
    def connect() -> Connection
    def initialize_schema(include_triggers=True)
    def get_schema_version() -> Optional[int]
    def transaction() -> ContextManager
    def execute(sql, params) -> Cursor
    def close()
```

**Schema Version Management:**
- v1: Initial schema (single-user)
- v2: Added `user_email` column + indexes for multi-user support
- Automatic migration on `get_database()` call

**schema.py Responsibilities:**
- All DDL statements for tables, indexes, triggers
- FTS virtual table definitions
- Schema version tracking
- Migration SQL generation

**Critical Tables:**
```sql
-- Core data tables
claims, notes, entities, tags

-- Relationship tables
claim_tags, claim_entities

-- Conflict management
conflict_sets, conflict_set_members

-- Search optimization
claim_embeddings, note_embeddings
claims_fts, notes_fts (FTS5 virtual tables)

-- System metadata
schema_version
```

---

#### 2. CRUD Layer (`crud/`)

**Inheritance Hierarchy:**
```
BaseCRUD[T] (Abstract)
    ├── ClaimCRUD
    ├── NoteCRUD
    ├── EntityCRUD
    ├── TagCRUD
    └── ConflictCRUD
```

**BaseCRUD (`crud/base.py`) - Abstract Base:**
```python
class BaseCRUD[T]:
    # Abstract methods (must implement)
    def _table_name() -> str
    def _id_column() -> str
    def _to_model(row) -> T
    
    # Concrete methods (inherited)
    def get(id: str) -> Optional[T]
    def exists(id: str) -> bool
    def list(filters, limit, offset) -> List[T]
    def count(filters) -> int
    
    # Multi-user support
    def _user_filter_sql() -> str
    def _user_filter_params() -> tuple
```

**ClaimCRUD (`crud/claims.py`) - Most Complex:**
```python
class ClaimCRUD(BaseCRUD[Claim]):
    def add(claim, tags, entities) -> Claim
        # 1. Validate user_email
        # 2. Begin transaction
        # 3. INSERT claim
        # 4. Link tags (get_or_create)
        # 5. Link entities (get_or_create)
        # 6. FTS sync (automatic via triggers)
        # 7. Commit
    
    def edit(claim_id, patch) -> Optional[Claim]
        # 1. Get existing claim
        # 2. Update fields
        # 3. Invalidate embedding if statement changed
        # 4. Update FTS (trigger)
    
    def delete(claim_id, mode="retract") -> Optional[Claim]
        # Soft delete: set status='retracted', retracted_at
    
    # Special queries
    def get_by_entity(entity_id, role) -> List[Claim]
    def get_by_tag(tag_id, include_children) -> List[Claim]
    def get_contested() -> List[Claim]
    def get_active(context_domain, claim_type) -> List[Claim]
    def search_by_predicate(predicate) -> List[Claim]
```

**Helper Functions (`crud/base.py`):**
```python
# FTS synchronization
sync_claim_to_fts(conn, claim_id, operation)  # 'insert'|'update'|'delete'
sync_note_to_fts(conn, note_id, operation)

# Embedding invalidation
delete_claim_embedding(conn, claim_id)
delete_note_embedding(conn, note_id)
```

---

#### 3. Search Layer (`search/`)

**Search Strategy Pattern:**
```python
class SearchStrategy(ABC):
    @abstractmethod
    def search(query: str, k: int, filters: SearchFilters) -> List[SearchResult]
    
    @abstractmethod
    def name() -> str
```

**FTSSearchStrategy (`search/fts_search.py`):**
- Uses SQLite FTS5 with BM25 ranking
- Fast, deterministic, no API cost
- Best for exact keyword matches

**Key SQL Pattern:**
```sql
SELECT c.*, bm25(claims_fts) as score
FROM claims_fts f
JOIN claims c ON f.claim_id = c.claim_id
WHERE claims_fts MATCH ?
  AND c.status IN (?, ?)
  AND c.user_email = ?  -- Multi-user filter
ORDER BY score
LIMIT ?
```

**EmbeddingSearchStrategy (`search/embedding_search.py`):**
- Cosine similarity over cached embeddings
- Good for semantic/conceptual queries
- API cost for query embedding

**Embedding cache reuse on the add path (2026-06-09):** `StructuredAPI.add_claim` now populates the `claim_embeddings` cache on insert (and refreshes it on edit when `statement` changes), and the duplicate/conflict check reuses those cached vectors instead of recomputing every existing claim's embedding per add. Specifically: `add_claim` calls `EmbeddingStore.ensure_embeddings(existing)` to build a `claim_id → vector` map and passes it to `LLMHelpers.check_similarity(..., cached_embeddings=...)`. The scan is capped by `config.conflict_scan_limit` (default 500; `<= 0` = all), replacing the former hardcoded `[:100]`. `get_embedding(claim_id, expected_model=...)` is **model-aware** — a cached vector built under a different `embedding_model` is treated as a miss and recomputed (handles embedding-model drift). Gated by `config.embedding_cache_enabled` (default True); all cache writes are best-effort. `StructuredAPI.backfill_embeddings()` populates the cache for existing claims. See `documentation/planning/plans/pkb_memory_system_improvements.plan.md` (Workstream A).

**Key Components:**
```python
class EmbeddingStore:
    def get_embedding(claim_id) -> Optional[np.ndarray]
    def store_embedding(claim_id, embedding, model)
    def get_or_compute(claim_id, statement) -> np.ndarray
    def batch_get_or_compute(claims) -> List[np.ndarray]

class EmbeddingSearchStrategy:
    def search(query, k, filters) -> List[SearchResult]
        # 1. Get query embedding
        # 2. Load candidate claims (filtered)
        # 3. Get/compute claim embeddings (parallel)
        # 4. Compute cosine similarity
        # 5. Sort and return top-k
```

**CRITICAL: Numpy Array Truthiness Issue**
```python
# ❌ WRONG - causes "ambiguous truth value" error
if query_emb:
    process(query_emb)

# ✅ CORRECT - use identity comparison
if query_emb is not None:
    process(query_emb)
```

**HybridSearchStrategy (`search/hybrid_search.py`):**
- Orchestrates multiple strategies
- Parallel execution using `ParallelExecutor`
- Reciprocal Rank Fusion (RRF) for merging
- Optional LLM reranking

**Execution Flow:**
```python
def search(query, strategy_names, k, filters, llm_rerank):
    # 1. Select available strategies
    active = [s for s in strategy_names if s in self.strategies]
    
    # 2. Execute in parallel
    futures = []
    for name in active:
        future = executor.submit(
            self.strategies[name].search,
            query, k*2, filters
        )
        futures.append((name, future))
    
    # 3. Collect results
    all_results = [f.result() for _, f in futures]
    
    # 4. Merge using RRF
    merged = merge_results_rrf(all_results, k=top_n)
    
    # 5. Optional LLM rerank
    if llm_rerank:
        merged = self._llm_rerank(query, merged, k)
    
    return merged[:k]
```

**RRF (Reciprocal Rank Fusion) Algorithm:**
```python
def merge_results_rrf(result_lists, k=60, rrf_k=60):
    """
    RRF score for item at rank r: 1 / (rrf_k + r)
    Sum scores across all result lists
    """
    scores = {}
    for results in result_lists:
        for rank, result in enumerate(results):
            claim_id = result.claim.claim_id
            score = 1.0 / (rrf_k + rank + 1)
            scores[claim_id] = scores.get(claim_id, 0) + score
    
    # Sort by combined score, return top-k
    sorted_claims = sorted(scores.items(), key=lambda x: -x[1])[:k]
    return [get_claim_result(cid) for cid, score in sorted_claims]
```

---

#### 4. Interface Layer (`interface/`)

**StructuredAPI (`interface/structured_api.py`):**

Main programmatic API. All methods return `ActionResult`:

```python
@dataclass
class ActionResult:
    success: bool
    action: str          # add|edit|delete|search|get|...
    object_type: str     # claim|note|entity|tag|conflict_set
    object_id: Optional[str]
    data: Any            # Result data
    warnings: List[str]  # Non-fatal warnings
    errors: List[str]    # Error messages
```

**Key Patterns:**

```python
# User-scoped operations
api = StructuredAPI(db, keys, config, user_email="user@example.com")
# All operations automatically filtered by user_email

# Factory pattern for multi-user
shared_api = StructuredAPI(db, keys, config)
user_api = shared_api.for_user("user@example.com")

# Add claim with auto-extraction
result = api.add_claim(
    statement="I prefer morning workouts",
    claim_type="preference",
    context_domain="health",
    auto_extract=True  # Extract entities/tags via LLM
)

# Bulk operations (v0.3+)
result = api.add_claims_bulk(
    claims=[{...}, {...}],
    auto_extract=False,    # Optional per-claim extraction
    stop_on_error=False    # Continue on individual failures
)
```

**ConversationDistiller (`interface/conversation_distillation.py`):**

Extracts memorable facts from chat conversations:

```python
class ConversationDistiller:
    def extract_and_propose(
        conversation_summary: str,
        user_message: str,
        assistant_message: str
    ) -> MemoryUpdatePlan:
        # 1. LLM extracts CandidateClaim objects
        # 2. Search for existing similar claims
        # 3. Determine relation (duplicate/update/new)
        # 4. Generate ProposedAction for each
        # 5. Return plan for user confirmation
    
    def execute_plan(
        plan: MemoryUpdatePlan,
        user_response: str,
        approved_indices: List[int]
    ) -> DistillationResult:
        # Execute approved actions
```

**Data Flow:**
```
User chat turn
    ↓
Extract candidates (LLM)
    ↓
Search existing (hybrid)
    ↓
Propose actions (add/update/skip/conflict)
    ↓
User confirmation
    ↓
Execute approved actions (StructuredAPI.add_claim, etc.)
```

**TextIngestionDistiller (`interface/text_ingestion.py`):**

Bulk text import with AI analysis and duplicate detection:

```python
class TextIngestionDistiller:
    def ingest_and_propose(
        text: str,
        default_claim_type: str,
        default_domain: str,
        use_llm: bool
    ) -> TextIngestionPlan:
        # 1. Parse text (LLM or rule-based)
        # 2. For each candidate:
        #    - Search existing claims
        #    - Compute similarity score
        #    - Determine action based on thresholds
        # 3. Return plan with proposals
```

**Similarity Thresholds:**
```python
DUPLICATE_THRESHOLD = 0.92  # Skip: exact duplicate
EDIT_THRESHOLD = 0.75       # Edit: update existing
RELATED_THRESHOLD = 0.55    # Add with warning
# < 0.55: Add new claim
```

---

## Data Flow Patterns

### Pattern 1: Add Claim Flow

```
User Interface (UI or Chat)
    ↓
POST /pkb/claims {statement, claim_type, context_domain, auto_extract}
    ↓
endpoints/pkb.py: handle_add_claim()
    ├── Extract user_email from session
    ├── Get StructuredAPI for user
    └── Call api.add_claim(...)
        ↓
interface/structured_api.py: StructuredAPI.add_claim()
    ├── If auto_extract and LLM available:
    │   ├── LLMHelpers.extract_single() → ExtractionResult
    │   ├── Merge extracted tags/entities
    │   └── Check similarity with existing claims
    ├── Claim.create() with user_email
    └── ClaimCRUD.add(claim, tags, entities)
        ↓
crud/claims.py: ClaimCRUD.add()
    ├── Begin transaction
    ├── INSERT into claims table
    ├── For each tag:
    │   ├── Get or create tag
    │   └── INSERT into claim_tags
    ├── For each entity:
    │   ├── Get or create entity
    │   └── INSERT into claim_entities
    └── Commit (FTS sync via triggers)
        ↓
Return ActionResult → JSON response → UI update
```

### Pattern 2: Hybrid Search Flow

```
User Query: "what are my coffee preferences?"
    ↓
POST /pkb/search {query, strategy: "hybrid", k: 10, filters}
    ↓
HybridSearchStrategy.search()
    ├── Select strategies: ["fts", "embedding"]
    ├── Build SearchFilters (include user_email)
    └── Execute in parallel:
        ├── FTSSearchStrategy.search()
        │   ├── Build FTS query
        │   ├── Execute: SELECT ... FROM claims_fts WHERE ...
        │   └── Return List[SearchResult]
        │
        └── EmbeddingSearchStrategy.search()
            ├── Get query embedding (API call)
            ├── Load candidate claims (filtered by user)
            ├── Batch get/compute claim embeddings
            ├── Compute cosine similarities
            └── Return List[SearchResult]
    ↓
merge_results_rrf([fts_results, emb_results], k=10)
    ├── Assign RRF scores: 1/(60 + rank)
    ├── Sum scores across strategies
    └── Sort by combined score
    ↓
apply_recency_confidence_rerank(merged, config)   # Workstream C; no-op at default weights
    ↓
Optional: LLM rerank top 50 → final top 10
    ↓
Return List[SearchResult] → JSON → UI renders claim cards
```

### Recency & Confidence Re-rank (Workstream C)

`merge_results_rrf` fuses FTS + embedding ranks but is blind to *time* and
*confidence*: an old and a new claim on the same topic tie. `apply_recency_confidence_rerank`
(`search/base.py`) is a pure post-fusion step applied once after the RRF merge,
inside `HybridSearchStrategy.search`:

```
recency = 0.5 ** (age_days / half_life)          # 1.0 fresh -> 0.5 at one half-life
conf    = claim.confidence or default_confidence
penalty = contested_penalty if claim.status == "contested" else 1.0   # C2
final   = rrf_score * (recency ** w_recency) * (conf ** w_confidence) * penalty
```

- **Default is an exact no-op.** With `w_recency = w_confidence = 0` (the
  shipped defaults), both factors are `x ** 0 == 1.0`, so scores and order are
  unchanged — existing behavior is preserved until the weights are tuned (plan C3).
- **Age source:** reads `last_reinforced_at` when present (the column lands in
  Workstream H), falling back to `updated_at` — so this re-rank works today and
  upgrades automatically once H adds reinforcement tracking.
- **Per-type half-life (C1a):** `half_life_by_type[claim_type]` overrides the
  default `recency_half_life_days` (e.g. facts long, observations short).
- **Pinned override (C1b):** a pinned claim (`meta_json.pinned`) keeps `recency = 1.0`.
- **New-claim grace (C1b):** claims younger than `recency_grace_days` keep
  `recency = 1.0` so fresh claims aren't buried by long-lived ones.
- **Status & contested down-ranking (C2):** `expired`/`retracted`/`superseded`/
  `dormant` are excluded upstream by `SearchFilters` default statuses
  (`default_search_statuses` = `[active, contested]`). Contested claims still
  surface (with warnings) but can be **buried** via `contested_penalty` — a
  multiplier applied to a contested claim's score (default `1.0` = no-op; e.g.
  `0.5` sinks it below uncontested peers). The fast-path no-op return also
  checks `contested_penalty == 1.0`, so default ranking is untouched.

**Config (C3, all in `PKBConfig`):** `recency_rerank_enabled`, `w_recency`,
`w_confidence`, `default_confidence`, `recency_half_life_days`,
`half_life_by_type`, `recency_grace_days`, `contested_penalty` — all sweepable
via the eval harness (`EvalRunner(config=PKBConfig(w_recency=...))`).

**Measured (eval harness, FTS-only, k=5):** at the default `w_recency = 0` the
`recency` and `conflict` categories score MRR 0.500; enabling `w_recency = 1.0`
(half-life 60d) lifts both to **1.000** while `lexical`/`temporal`/`semantic`
and overall recall stay unchanged — i.e. the re-rank fixes newer-vs-older
ordering without disturbing strong lexical matches. Unit-tested in
`tests/test_recency_rerank.py` (zero-weight no-op, newer-promotion, pinned
override, grace floor, per-type half-life, confidence weighting, and the C2
contested-penalty no-op/bury/compose cases).

### Reinforcement & Decay — Schema v8 (Workstream H)

The recency re-rank above decays a claim by *age*, but age should reset when the
user **re-affirms** a memory ("use it or lose it"). That requires a queryable,
sortable timestamp — so it lives in indexed columns, not `meta_json`. **Schema
v8** adds to `claims`:

- `last_reinforced_at TEXT` — the clock recency/decay measure from (the C
  re-rank reads this in preference to `updated_at`).
- `reinforcement_count INTEGER NOT NULL DEFAULT 0`.
- Index `idx_claims_last_reinforced` for the recency sort / future decay sweep.

**Migration (`database.py:_migrate_v7_to_v8`):** `ALTER TABLE` adds both columns,
backfills `last_reinforced_at = updated_at` for existing rows (so old claims get a
sensible anchor), and creates the index. Because the base DDL runs *before*
migrations via `executescript`, the index on the migration-added column is
created **after** the always-run column-reconciliation block in
`initialize_schema` (not in the base `INDEXES_DDL`) — this covers both fresh and
upgraded databases. Verified on a copy of the real `storage/users/pkb.sqlite`
(v6→v8, all 49 claims backfilled, count preserved, idempotent re-init).

**`StructuredAPI.reinforce_claim(claim_id, strength=1.0)`** — the single
state transition:

```
last_reinforced_at = now
reinforcement_count += 1
updated_at = now                                  # via the CRUD layer
confidence += (1 - confidence) * (reinforce_alpha * strength)   # asymptotic → 1.0
if reinforce_ttl_days_by_type[type] and valid_to: valid_to = now + ttl   # extend hard TTL
if status == 'dormant': status = 'active'         # revive
```

- **Confidence vs. freshness are separate but linked:** confidence (belief it's
  true) rises with diminishing returns and never reaches 1.0; freshness
  (`last_reinforced_at`) is what ranking/decay act on. A claim can be
  true-but-stale.
- **H4 safeguard:** reinforcing a `contested` or `superseded` claim is *refused*
  (returns an error) — that path should trigger conflict review, not silently
  resurrect a claim known to be false/replaced.
- **`ClaimStatus.DORMANT`** is added now (forward-compat); the Workstream F2
  decay sweep will be the producer that flips inactive claims to `dormant`, and
  `reinforce_claim` revives them.

**Config (`PKBConfig`, all inert by default):** `reinforce_alpha=0.1`,
`reinforce_ttl_days_by_type={}`, `reinforce_on_duplicate="off"`,
`dormancy_threshold=0.0`.

**H3 reinforcement signals (wired):** three surfaces now feed
`last_reinforced_at`, strongest → weakest:

1. **`add_claim` near-duplicate branch (primary).** When the similarity check
   flags an existing `duplicate` and `reinforce_on_duplicate` is `"reinforce"` /
   `"reinforce+warn"`, `add_claim` reinforces that existing claim and returns its
   `ActionResult` (action `"reinforce"`) **instead of** creating a redundant
   claim. Default `"off"` preserves today's warn-and-create behavior. If the
   match is `contested`/`superseded`, the H4 safeguard refuses and `add_claim`
   falls through to normal creation.
2. **`ConversationDistiller` (user-confirmed).** A candidate that restates an
   existing claim now becomes a `reinforce` proposal (carrying the matched
   `existing_claim`) rather than being silently skipped; approving it calls
   `reinforce_claim`. Shared logic lives in `StructuredAPI._build_reinforcement_patch`.
3. **`pin_claim` (weakest).** Pinning is an explicit "this matters" signal, so
   `pin=True` also reinforces (skipped on unpin and for contested/superseded).

Unit-tested in `tests/test_reinforcement.py` (17: migration backfill, fresh-DB
columns, count/timestamp/confidence transitions, strength scaling, dormant
revive, contested/superseded refusal, TTL extension, the recency re-rank
preferring `last_reinforced_at`, pin reinforcement, distiller reinforce
proposal+execution, and the `add_claim` duplicate routing on/off).

### Soft-TTL Decay Sweep (Workstream F2)

The producer side of the same `last_reinforced_at` clock (one timestamp, two
consumers — C ranks on it, F2 sweeps on it). `utils.decay_dormant_claims(db,
config, user_email=None, now=None)` flips `active` claims to **`dormant`** when
their freshness `0.5 ** (age_days / half_life)` falls below
`config.dormancy_threshold`, where `age_days` is measured from
`last_reinforced_at` (falling back to `updated_at`) and `half_life` reuses C's
`recency_half_life_days` / `half_life_by_type` (so dormancy and ranking decay
agree). It skips pinned claims, `config.dormancy_exempt_types`, and any type
whose half-life is non-positive. **Inert by default:** `dormancy_threshold == 0`
short-circuits the sweep because `0.5 ** x` is always > 0.

Dormant is a soft state, not a delete: `ClaimStatus.default_search_statuses()`
omits `dormant` (so normal search won't surface it) but `all_visible_statuses()`
**includes** it (still browsable/revivable), and `reinforce_claim` flips it back
to `active`. The sweep runs (a) lazily before search via
`maybe_expire_claims(db, user_email, config)` — now alongside the hard-TTL
`expire_stale_claims` under the same `EXPIRY_CHECK_INTERVAL` guard — and (b)
on-demand via `StructuredAPI.run_decay_sweep()` (the entry point a scheduled F1
job would call). Config knob: `dormancy_exempt_types: List[str]` (default `[]` =
all types decayable). Unit-tested in `tests/test_decay.py` (9: inert default,
stale→dormant, fresh survives, `last_reinforced_at` clock, pinned/exempt/per-type
half-life skips, reinforce-revives-decayed, the API entry point, and the F3
default-search-vs-visible status split).

### Scheduled Sweep & Notifications (Workstream F1/F4)

F2 made the sweep *correct*; F1 makes it *timely* and F4 makes it *visible*.

**F1 — scheduled sweep.** The expiry/dormancy passes previously ran only lazily
(before search, behind the `EXPIRY_CHECK_INTERVAL` guard) so a quiet PKB never
swept. `utils.run_lifecycle_sweep(db, config, user_email=None, now=None)` runs
hard-TTL `expire_stale_claims` + soft-TTL `decay_dormant_claims`
**unconditionally** (no interval guard — the caller controls cadence) and
returns `{"expired": N, "dormant": M}`. A new `truth_management_system/
scheduler.py` runs it on a daemon thread:
`start_lifecycle_sweep_scheduler(db, config, interval_seconds=None)` spins a
`threading.Thread` + `threading.Event` loop (matching the existing `server.py`
background-thread convention — no new dependency), `stop_lifecycle_sweep_
scheduler()` signals it to stop, and `is_running()` reports liveness. It is
**config-gated** (`sweep_interval_seconds <= 0` disables it, leaving the lazy
path as the only trigger) and **idempotent** (a second start while alive is a
no-op). `endpoints.pkb.start_pkb_background_jobs()` initializes the shared PKB DB
and starts the scheduler; `server.py` calls it at startup next to the
search-backfill thread. `StructuredAPI.run_lifecycle_sweep()` exposes the same
sweep on demand, surfaced at `POST /pkb/sweep`.

**F4 — notifications.** `StructuredAPI.get_lifecycle_notifications(within_days=
None, limit=50)` returns two buckets (scoped to the user): `soon_to_expire` —
active `task`/`reminder` claims whose `valid_to` is within the next
`within_days` days — and `newly_dormant` — claims flipped to `dormant` within
the last `within_days` days (the decay sweep stamps `updated_at` on flip, so the
window is precise). `within_days` defaults to `config.notify_expiry_within_days`
(7). Surfaced at `GET /pkb/notifications` for a UI badge/affordance.

Config knobs: `sweep_interval_seconds` (0 = disabled) and
`notify_expiry_within_days` (7), both with `to_dict`/`from_dict`/env wiring.
Unit-tested in `tests/test_lifecycle_sweep.py` (8: unconditional expiry,
dormancy via injected `now`, the API sweep, scheduler disabled/enabled/idempotent
+ stop, the soon-to-expire window, the task/reminder type filter, and
newly-dormant detection).

### Supersession — Schema v9 (Workstream D1)

Contradiction handling needs more than flipping a status: when "I live in
Bengaluru" becomes "I live in Mumbai", the system should record *which* claim
replaced *which*, retire the old one, and retrieve only the current head. D1 adds
a typed claim-to-claim graph.

- **`claim_links` table (v9):** `(link_id, user_email, from_claim_id,
  to_claim_id, link_type, created_at, meta_json)` with
  `UNIQUE(from_claim_id, to_claim_id, link_type)` and indexes on both endpoints
  + `link_type`. The base DDL creates it (and its indexes) with `IF NOT EXISTS`,
  and `_migrate_v8_to_v9` re-creates it defensively for upgrading DBs — verified
  on a copy of the real DB (v6→v9, 49 claims preserved, idempotent). Unlike the
  v8 column-index, these indexes live in base DDL safely because the table is
  brand new (no migration-added column to wait on).
- **Direction convention:** a `supersedes` link runs **from the newer claim to
  the older one** (`from` supersedes `to`).
- **`crud/links.py`:** `link_claims` (rejects self-links, idempotent on the
  UNIQUE edge), `unlink_claims`, `get_outgoing_links`/`get_incoming_links`, and
  `get_supersession_head(db, claim_id)` which walks the chain forward to the
  newest non-superseded claim (cycle- and depth-guarded, `max_hops=50`).
- **`StructuredAPI.supersede_claim(new_id, old_id, resolution_notes=None)`:**
  creates the link and moves the old claim to `superseded` (refuses
  self-supersession and missing claims; idempotent — a duplicate edge is warned,
  not errored). Returns the resolved chain head.
- **Two confirmed entry points (no silent edits):** (1) `add_claim(...,
  supersedes=<id|list>)` retires the named claim(s) right after creating the new
  one; (2) `resolve_conflict_set(..., winning_claim_id=W)` — where the user
  already picks a winner — now records `W -supersedes-> loser` for every loser
  (which `ConflictCRUD.resolve` had already moved to `superseded`), so the graph
  is captured, not just the status.
- **Chain-head retrieval comes for free:** `superseded` is absent from
  `SearchFilters` default statuses (`default_search_statuses` =
  `[active, contested]`, applied as `c.status IN (...)`), so the old claim drops
  out of normal search while the active head remains. `get_supersession_head`
  is there for callers that explicitly land on a superseded claim and want to
  jump to the current one. The H4 safeguard already refuses to reinforce a
  `superseded` claim, so a retired claim can't be silently revived.
- **Deferred follow-up:** the `ConversationDistiller` currently classifies
  matches only as `duplicate`/`related` by score — it has no contradiction
  detector — so an automatic distiller→supersede proposal is left as a follow-up
  (the API and confirmation surfaces above are in place for it to call).

Unit-tested in `tests/test_supersession.py` (12: schema/table presence, link
CRUD + multi-hop head, self/dup rejection, cycle guard, the supersede transition
and guards, idempotent link, `add_claim(supersedes=)`, conflict-resolution link
recording, superseded-excluded-from-active-set, and the no-reinforce-superseded
bridge).

### Consolidation & Entity Resolution (Workstream D2/D3)

Once claims accumulate, near-duplicates and entity-name variants clutter the
graph. D2/D3 add **on-demand** passes (no LLM) that detect and merge them,
reusing the A1 embedding cache and the D1 supersession links. The clustering
itself lives in a pure, dependency-free helper module
`search/consolidation.py` (single-linkage union-find), so it is trivially
unit-testable offline.

**D2 — claim consolidation.**
- `cluster_near_duplicate_claims(embeddings, threshold)` normalises the cached
  vectors, computes pairwise cosine similarity, and single-linkage clusters any
  pair at/above `threshold` (default `config.consolidation_similarity_threshold
  = 0.95`). Returns clusters of size >= 2 sorted by max similarity.
- `StructuredAPI.find_consolidation_candidates(threshold, limit)` pulls all
  active/contested vectors via `EmbeddingStore.get_all_embeddings(SearchFilters())`,
  clusters them, and annotates each cluster with a `suggested_keep_id` chosen by
  `_suggest_keeper` (highest confidence, tie-broken by most recent). These are
  merge **proposals** for the existing confirmation/proposal modal.
- `StructuredAPI.consolidate_claims(claim_ids, keep_id=None)` executes a merge:
  it unions the duplicates' tags onto the keeper, then calls the D1
  `supersede_claim(keep, dup)` for each duplicate — so duplicates become
  `superseded` (dropping out of default search but staying linked and
  reversible), and the keeper stays active.

**D3 — canonical entity resolution.**
- `entity_name_similarity(a, b, threshold)` scores two names: exact normalised
  match = 1.0; a `difflib` character ratio otherwise; with a **token-subset
  boost** so `"john"` clusters with `"John Smith"` (one name's tokens ⊆ the
  other's → at least `threshold`).
- `cluster_entity_variants(entities, threshold)` single-linkage clusters
  same-type entities, picking the longest name as the canonical
  `suggested_keep_id`.
- `StructuredAPI.find_entity_duplicates(entity_type, threshold)` runs this per
  `EntityType` (default `config.entity_dedup_threshold = 0.85`).
- `StructuredAPI.merge_entities(source_id, target_id)` records the source's name
  (and any aliases it already held) in the target's `meta_json.aliases`, then
  re-points the source's `claim_entities` to the target and deletes the source
  via the existing `EntityCRUD.merge` — turning `claim_entities` into a cleaner
  graph without losing the variant name.

**REST surface:** `GET /pkb/consolidation/candidates`,
`POST /pkb/consolidation/merge` (`{claim_ids, keep_id?}`),
`GET /pkb/entities/duplicates`, `POST /pkb/entities/merge`
(`{source_id, target_id}`).

Config knobs: `consolidation_similarity_threshold`, `entity_dedup_threshold`
(both with `to_dict`/`from_dict`/env wiring). Unit-tested in
`tests/test_consolidation.py` (12: clustering helpers, name similarity,
consolidate supersede+tag-union, default keeper, guards, alias-merge,
claim re-pointing, duplicate detection).

### Provenance — "Why do I know this?" (Workstream E1/E2)

Auto-distilled claims should be traceable back to the conversation that produced
them. E1/E2 record that provenance **in `meta_json`** (no schema migration) under
a `source` object, matching the existing `pinned` and text-ingestion `source`
conventions:

```json
{"source": {"type": "chat_distillation", "conversation_id": "...",
            "message_id": "...", "distilled": true}}
```

- **`add_claim` provenance params (E1):** `source_conversation_id`,
  `source_message_id`, `source_type` (via `**kwargs`). When any is present,
  `add_claim` merges the `source` object into `meta_json` (preserving existing
  keys like `pinned`) before creating the claim.
- **Provenance tag (E2):** when a `source_conversation_id` is present,
  `add_claim` also appends a `source:conversation` tag so distilled claims are
  filterable. A message id alone (no conversation) records provenance but adds
  no tag.
- **Distiller threading:** `MemoryUpdatePlan` carries
  `source_conversation_id`/`source_message_id`; `extract_and_propose` accepts
  them (the `/pkb/distill` route passes the request's `conversation_id` +
  optional `message_id`), and they ride on the persisted plan to execute time —
  `execute_plan` stashes them and the add branch of `_execute_action` forwards
  them to `add_claim`. So a claim saved from chat is automatically stamped with
  its origin, with no extra UI step.
- **Read path (E1):** `StructuredAPI.get_claim_provenance(claim_id)` parses
  `meta_json.source` and returns `{claim_id, source_type, conversation_id,
  message_id, distilled, created_at}` — `source_type` defaults to `"manual"` for
  hand-entered claims. Exposed at `GET /pkb/claims/<id>/provenance` for the claim
  card's "why do I know this?" affordance.

Unit-tested in `tests/test_provenance.py` (7: provenance recording, meta merge
with `pinned`, manual-claim default, missing-claim error, the
`source:conversation` tag, message-only-no-tag, and the distiller
`MemoryUpdatePlan -> execute_plan -> add_claim` threading offline).

### Portability & Audit Log — Schema v10 (Workstream G3)

Two trust/ownership features that travel together: users should be able to take
their memory with them, and to see *what changed when*.

**Audit log.** A new `audit_log` table (v10) is an **append-only** history —
the code only ever INSERTs and SELECTs, never UPDATEs or DELETEs, so it is
tamper-evident. Columns: `(audit_id, user_email, action, object_type,
object_id, detail_json, created_at)` with `idx_audit_log_user(user_email,
created_at)`. `portability.record_audit(db, user_email, action, object_type,
object_id, detail)` writes one row in its own transaction and is **best-effort**
— wrapped so a logging failure can never break the user operation it records.
`StructuredAPI._record_audit` is called from the success paths of `add_claim`
(`add`), `edit_claim` (`edit`, `detail={"fields": [...]}`), `delete_claim`
(`delete`, `detail={"mode": ...}`) and `import_data` (`import`, `detail`=counts).
Reinforcement/supersession/consolidation mutate through the CRUD layer rather
than `edit_claim`, so they don't emit `edit` rows — the log tracks the
user-facing CRUD surface, not every internal status flip.

**Export.** `portability.export_user_data(db, user_email)` builds a
JSON-serializable envelope `{pkb_export_version, schema_version, exported_at,
user_email, counts, data}`. `data` carries the user's owned rows (`entities`,
`tags`, `contexts`, `claims`, `claim_links` — filtered by `user_email`) plus the
join rows that connect them (`claim_entities`, `claim_tags`, `context_claims` —
filtered by membership in the exported claim set). Embeddings are **excluded**:
they're derived and large, and `backfill_embeddings()` rebuilds them. Rows are
captured with `SELECT *` → `dict(row)`, so new schema columns ride along
automatically.

**Import.** `portability.import_user_data(db, user_email, payload, mode="merge")`
inserts the envelope under the importing user. Two design choices make it
robust: (1) owned rows are **re-stamped** with the importer's `user_email`, so an
export can move between users; (2) the whole load runs in one transaction with
`PRAGMA defer_foreign_keys=ON`, so self-referential (`parent_tag_id`,
`parent_context_id`) and cross-table references resolve regardless of insert
order and are verified atomically at commit. `merge` mode uses `INSERT OR
IGNORE`, so primary-key collisions are skipped — re-importing the same envelope
is a no-op and partial overlaps merge cleanly. Inserting into `claims` fires the
existing FTS sync trigger, so search stays consistent without extra work.

Surfaced as `StructuredAPI.export_data()` / `import_data(payload, mode)` /
`get_audit_log(limit, offset, action)` (all returning `ActionResult`) and REST
`GET /pkb/export`, `POST /pkb/import`, `GET /pkb/audit`. The v9→v10 migration
(`_migrate_v9_to_v10`) mirrors the v9 pattern — defensive `CREATE TABLE IF NOT
EXISTS`, verified on a copy of the real DB (v6→v10, 49 claims preserved,
idempotent, original untouched). Unit-tested in `tests/test_portability.py` (9:
v10/audit-table presence, add/edit/delete audit rows, action filter + user
scoping, export envelope shape, cross-user round-trip, merge idempotency,
invalid-payload rejection, import audit row, and tag/link preservation).

### Combined & Batched Enrichment (Workstream G2)

`add_claim`'s auto-extract used to fire ~5-6 LLM calls per claim: `extract_single`
ran four-to-five field extractors (tags, entities, SPO, type, keywords) and then
a separate `generate_possible_questions` call. But `analyze_claim_statement`
already does the whole job — claim_type, context_domain, tags, entities **and**
possible_questions — in **one** combined prompt. G2 routes the add path through
that single call and reuses its questions (no extra round-trip), so a typical
interactive add drops from six LLM calls to one — cheaper *and* lower latency.
The behavior is gated by `combined_enrichment` (default True); set it False to
fall back to the legacy multi-call path. Only fields the caller didn't supply
are filled, and the claim_type is only overridden when it came in as the generic
`observation`.

For bulk, `LLMHelpers.batch_analyze` fans `analyze_claim_statement` across the
shared parallel executor (the same `map_parallel` used by `batch_extract_all`).
`add_claims_bulk` pre-computes every statement's analysis in one parallel batch
up front and injects each result into `add_claim` via the private `_analysis`
kwarg, so N claims cost N concurrent combined calls instead of N×6 sequential
ones; if batching errors it falls back to the per-claim path. The
`auto_extract=False` path (unit tests and the eval harness) is untouched, so the
retrieval baseline is unaffected. Unit-tested in `tests/test_batch_enrichment.py`
(6, a fake LLM with per-method call counters): single combined call, question
reuse, user-field precedence, the legacy-flag path, and single-batch bulk
fan-out.

### Distiller Contradiction → Supersede (Workstream D1 follow-up)

D1 gave the PKB supersession links but left the distiller unable to *detect*
contradictions — it only classified matches as duplicate/related by score, so a
claim that *replaced* an existing one was saved as a parallel, conflicting claim.
This follow-up closes that gap. `llm_helpers.detect_contradiction(new, existing)`
is an **ungated** LLM check: unlike `_classify_relation` (which treats
near-identical statements as duplicates and only probes for contradictions in a
narrow similarity band), it asks directly whether the new statement updates the
old on the same subject/attribute — catching the most common case, where the two
are near-identical in surface form yet assert incompatible values ("I live in
Mumbai" → "I live in Bengaluru").

`ConversationDistiller._detect_contradictions` runs that check over the top
matches (capped at 3 to bound cost, gated by `distiller_detect_contradictions`
[default True] and LLM availability) and upgrades any hit to a `contradicts`
relation. `_propose_actions` maps a contradiction to a user-confirmed
`supersede` proposal, taking **priority** over the duplicate→reinforce path, and
`_execute_action` runs an approved supersede via `add_claim(..., supersedes=old_id)`
— reusing the D1 path that creates the `supersedes` claim_link and retires the
old claim, with provenance threaded through like a normal add. Because it's a
*proposal* requiring confirmation, it can't silently rewrite memory. Unit-tested
in `tests/test_distiller_contradiction.py` (7): relation upgrade, the
no-contradiction / config-disabled / no-LLM no-ops, the supersede proposal and
its priority over duplicate, and end-to-end execution (old claim → `superseded`,
new claim active, `supersedes` link present).

### Vector Index for Embedding Search (Workstream B)

Embedding search used to score candidates with a Python `for` loop calling
`_cosine_similarity` once per claim — fine at dozens of claims, linear and
interpreter-bound at thousands. `search/ann_vector_index.py` introduces a
`VectorIndex` with two pluggable backends behind one interface:

- **`flat`** (default): all of a user's embeddings are stacked into one
  L2-normalized `(N, d)` matrix; a query is scored with a single `matrix @ q`
  BLAS matmul and a partial sort (`argpartition`). This is **exact** — it
  returns the same ranking as the linear scan — but moves the O(N·d) work into
  vectorized native code. Needs no third-party dependency.
- **`hnsw`** (optional): a faiss `IndexHNSWFlat` (inner product over normalized
  vectors) for approximate, sub-linear search at very large corpora. Selected
  only when `ann_backend="hnsw"` *and* faiss is importable; otherwise the index
  transparently degrades to `flat`.

**Backend choice.** The plan recommended `sqlite-vec` to stay single-file, but
`sqlite-vec`/`sqlite-vss`/`hnswlib` aren't installed in this environment (and
can't be added without network). faiss *is* available, so the design keeps an
exact, dependency-free `flat` default and uses faiss for the optional `hnsw`
mode — which also sidesteps the per-user index-*file* lifecycle (creation,
corruption recovery) the original plan flagged as the main risk.

**Lifecycle.** Indexes build lazily from the A1 embedding cache
(`claim_embeddings`) and are cached per-user in a process-level dict keyed by
`(id(db), user_email)`. Each lookup computes a cheap **staleness signature** —
`(COUNT(*), MAX(created_at))` of the user's cached embeddings — and rebuilds when
it changes. Adds/deletes change the count; an edit re-embeds and bumps
`created_at`; so the signature catches all three without an explicit
maintenance hook. This is the plan's "rebuild if missing + checksum" mitigation.

**Query path & filter correctness.** `EmbeddingSearchStrategy.search` calls
`_ann_search` first. It over-fetches `k * ann_overfetch` (default 5) hits from
the index — more than `k`, to survive post-filtering — then loads *only* those
claims via `_load_claims_by_ids`, which re-applies the full `SearchFilters` SQL
(`status`/`domain`/`type`/`validity`/`user`). So the fast path honors exactly the
same constraints as the linear scan; it simply avoids loading and scanning every
embedding. `_ann_search` returns `None` — signalling the caller to use the
exhaustive linear scan — whenever the index is unavailable, the user has fewer
than `ann_min_claims` (default 200) cached embeddings, or there are no hits.
That threshold is the key safety valve: the unit tests and the 49-claim eval
corpus sit far below it, so they stay on the exact linear path and the retrieval
baseline (`precision@5=0.537 recall@5=0.763 mrr=0.664`) is unchanged.

**Benchmark** (`tests/eval/benchmark_vector_index.py`, synthetic random vectors,
dim 1536, k 20): the `flat` backend is ~3.6× faster than the Python loop at 1k
vectors and **~13× faster at 50k** (82.8 ms → 6.3 ms/query); `hnsw` is faster
still (~1.2 ms at 50k) but its recall on *uniform random* vectors is low (0.12 at
50k) — random high-dimensional points are nearly equidistant, the adversarial
worst case for a graph index. Real embeddings cluster, so HNSW recall is far
higher in practice; the benchmark's value is the flat-vs-linear scaling curve,
which is why `flat` is the default. Tests: `tests/test_vector_index.py` (11) —
`flat` equals brute force, top-k edge cases, zero-vector query, HNSW build + the
no-faiss fallback, cache hit + staleness rebuild, per-user scoping, the
filter-preserving claim load, and the engage/decline threshold.

### Two-Axis Provenance, Origin & Memory Cleanup (Provenance & Cleanup plan)

**Why two axes.** A single `source` string conflated *where* a claim entered
with *how it was derived*. Splitting them into **channel**
(`manual|chat|ingest|import`) and **derivation** (`stated|extracted|inferred`)
lets retrieval and UI treat "the user told me" differently from "I concluded
this." Both live in `meta_json.source` (no migration); the legacy `type` is kept
for back-compat. `ProvenanceChannel.normalize` folds legacy values
(`chat_distillation→chat`, `text_ingestion→ingest`, `migration→import`);
`referenced` is *not* a channel — it is a transient retrieval-time injection
label and never persisted. `add_claim` always stamps both axes
(`utils.set_provenance`), defaulting manual→stated, distilled→chat/extracted.

**Trust mechanics for `inferred`.** An inferred claim is a conclusion the user
never stated, so it is trusted less in two independent ways: its confidence is
capped at `inferred_confidence_cap` (0.4) *at add time*, and it is multiplied by
`(1 − inferred_rerank_penalty)` in `apply_recency_confidence_rerank`. The penalty
is active even when the recency/confidence weights are 0, so the rerank's fast
no-op path now also requires `inferred_penalty == 0`. Corpora without inferred
claims are unaffected — the eval baseline is unchanged. The distiller's
extraction LLM labels each candidate; an explicit restatement later
*reconfirms* it: `reinforce_claim(upgrade_derivation=True)` promotes
`inferred→stated` and the confidence nudge lifts it past the cap (the distiller's
duplicate→reinforce path passes the flag).

**Origin (entities/tags).** Index objects are not propositional, so they carry a
one-bit `meta_json.origin` (`auto` from enrichment via the `get_or_create_*`
link helpers, `curated` from the facade `add_*`). It is a cleanup/trust signal
only and deliberately does **not** gate dedup.

**Dedup & merge.** Cheap prefilters (embedding cosine for claims, token-subset
name similarity for entities/tags) propose clusters; an optional LLM pass
(`judge_duplicates`, gated by `dedup_llm_verify`/`use_llm`) confirms each cluster
and suggests a canonical form before a merge is offered. `TagCRUD.merge` is the
non-lossy tag counterpart to entity merge: it re-points `claim_tags`, re-parents
the source's children to the target, and lifts the target out from under the
source first to avoid a self-cycle.

**Memory Cleanup orchestrator.** `run_memory_cleanup(apply=False)` is the single
entry point: it always runs the *safe* maintenance (lifecycle sweep + best-effort
overview refresh) and gathers dedup proposals; with `apply=True` it merges each
cluster by its suggested keeper. Two-phase by design — nothing destructive
happens until the user clicks Apply — mirroring the propose→execute pattern.
Surfaced at `POST /pkb/cleanup` and the UI Maintenance tab.

**Lifecycle notification & audit.** When an add supersedes an existing claim the
change is reported in `ActionResult.metadata["lifecycle_changes"]` (aggregated
onto `DistillationResult.lifecycle_changes` and toasted in the UI). Merges and
derivation upgrades are written to the append-only `audit_log` (`merge` /
`derivation_change`). Tests: `test_provenance_axes`, `test_provenance_distiller`,
`test_inferred_rerank`, `test_reconfirmation_upgrade`, `test_origin`,
`test_tag_merge`, `test_dedup_llm_verify`, `test_lifecycle_notification`,
`test_memory_cleanup`, `test_audit_coverage`.

### Pattern 3: Memory Update from Chat

```
Chat Turn Completes
    ↓
Frontend: setTimeout(() => {
    PKBManager.checkMemoryUpdates(summary, userMsg, assistantMsg)
}, 3000)
    ↓
POST /pkb/propose_updates {conversation_summary, user_message, assistant_message}
    ↓
ConversationDistiller.extract_and_propose()
    ├── LLM extracts CandidateClaim objects
    │   Prompt: "Extract memorable personal facts..."
    │   Response: [{statement, claim_type, context_domain, confidence}, ...]
    ├── For each candidate:
    │   ├── api.search(candidate.statement, k=5)
    │   └── Determine relation:
    │       ├── score > 0.9 → duplicate (skip)
    │       └── score > 0.7 → related (add with warning)
    └── Generate ProposedAction for each non-duplicate
    ↓
MemoryUpdatePlan {plan_id, proposed_actions, user_prompt}
    ├── Store in _memory_update_plans dict
    └── Return JSON to frontend
    ↓
Show Memory Proposal Modal
    ├── Render each proposal as editable row
    ├── User checks which to approve
    └── Click "Save Selected"
    ↓
POST /pkb/execute_updates {plan_id, approved_indices}
    ↓
ConversationDistiller.execute_plan()
    ├── Get plan from _memory_update_plans
    ├── For each approved index:
    │   └── api.add_claim(candidate.statement, ...)
    └── Return DistillationResult {executed_count, results}
    ↓
UI shows success toast → Refresh claims list
```

### Pattern 4: Deliberate Memory Attachment (v0.4)

```
User selects "Use in next message" on a claim
    ↓
PKBManager.addToNextMessage(claim_id)
    ├── Add to pendingMemoryAttachments[]
    ├── Fetch claim details for display
    └── updatePendingAttachmentsIndicator()
        └── Show chip near chat input
    ↓
User types message and sends
    ↓
sendMessageCallback()
    ├── attached_claim_ids = PKBManager.getPendingAttachments()
    ├── parseMemoryReferences(messageText) → referenced_claim_ids
    └── ChatManager.sendMessage(convId, text, ..., attached_claim_ids, referenced_claim_ids)
    ↓
POST /send_message/<conversation_id>
    {
        messageText,
        attached_claim_ids,      # From "Use Now"
        referenced_claim_ids     # From @memory:id
    }
    ↓
server.py: Inject conversation_pinned_claim_ids
    conv_pinned = get_conversation_pinned_claims(conversation_id)
    query['conversation_pinned_claim_ids'] = list(conv_pinned)
    ↓
Conversation.reply(query, ...)
    ├── Extract:
    │   ├── attached_claim_ids
    │   ├── conversation_pinned_claim_ids
    │   └── referenced_claim_ids
    └── Start async: pkb_future = get_async_future(
            self._get_pkb_context,
            user_email, query_text, summary, k=10,
            attached_claim_ids=attached_claim_ids,
            conversation_id=conversation_id,
            conversation_pinned_claim_ids=conv_pinned_ids,
            referenced_claim_ids=referenced_claim_ids
        )
    ↓
_get_pkb_context() in parallel with other processing
    ├── 1. REFERENCED: api.get_claims_by_ids(referenced_ids)
    ├── 2. ATTACHED: api.get_claims_by_ids(attached_ids)
    ├── 3. GLOBAL PINNED: api.get_pinned_claims()
    ├── 4. CONV PINNED: api.get_claims_by_ids(conv_pinned_ids)
    ├── 5. AUTO SEARCH: api.search(query, strategy='hybrid', k=remaining)
    ├── Deduplicate by claim_id (keep highest priority)
    └── Format with source indicators:
        "[REFERENCED] [preference] I prefer morning meetings
         [GLOBAL PINNED] [fact] My timezone is IST
         [AUTO] [preference] I like detailed explanations"
    ↓
pkb_context = pkb_future.result(timeout=5.0)
    ↓
Two-stage injection into system prompt:
  1. Full pkb_context included in distillation prompt → cheap LLM extracts relevant user prefs
  2. Only [REFERENCED ...] claims re-appended AFTER distillation verbatim
     (_extract_referenced_claims() parses bullet boundaries, keeps only referenced claims)
     Auto/pinned/attached claims are left to the distillation; referenced claims are preserved
     because the user explicitly asked for them and they must reach the main LLM word-for-word.
    ↓
user_info_text = distilled_prefs + referenced_claims_section
    ↓
Injected into permanent_instructions slot of chat_slow_reply_prompt
    ↓
LLM receives context → Generates response with user's memories
```

---

## Integration Patterns

### Pattern A: Flask Server Integration

**File:** `endpoints/pkb.py` (Flask Blueprint)

**Key Functions:**
```python
# Module-level state
_pkb_db = None           # Shared PKBDatabase instance
_pkb_config = None       # PKBConfig
_memory_update_plans = {}   # Temp plan storage (conversation distillation)
_text_ingestion_plans = {}  # Temp plan storage (text ingestion)

# Helper: get conversation-pinned claims (ephemeral session state)
def get_conversation_pinned_claims(conversation_id: str) -> set
def add_conversation_pinned_claim(conversation_id: str, claim_id: str)
def remove_conversation_pinned_claim(conversation_id: str, claim_id: str)
def clear_conversation_pinned_claims(conversation_id: str)

# Database initialization
def get_pkb_db() -> Tuple[PKBDatabase, PKBConfig]:
    # Lazy-init shared database
    # Path: storage/users/pkb.sqlite

# User-scoped API factory
def get_pkb_api_for_user(user_email: str, keys: dict) -> StructuredAPI:
    # Returns StructuredAPI instance scoped to user

# Serialization helpers
def serialize_claim(claim) -> dict
def serialize_entity(entity) -> dict
def serialize_tag(tag) -> dict
def serialize_conflict_set(cs) -> dict
def serialize_search_result(sr) -> dict
```

**Endpoint Pattern:**
```python
@pkb_bp.route('/pkb/claims', methods=['POST'])
@login_required
@limiter.limit("100 per hour")
def handle_add_claim():
    # 1. Check PKB availability
    if not PKB_AVAILABLE:
        return json_error("PKB not available", 503)
    
    # 2. Get user from session
    user_email = get_session_identity().email
    
    # 3. Get user-scoped API
    api = get_pkb_api_for_user(user_email, keyParser.get_api_keys())
    
    # 4. Parse request
    data = request.get_json()
    
    # 5. Call API method
    result = api.add_claim(
        statement=data['statement'],
        claim_type=data['claim_type'],
        context_domain=data['context_domain'],
        auto_extract=data.get('auto_extract', True)
    )
    
    # 6. Return response
    if result.success:
        return jsonify({
            'success': True,
            'claim': serialize_claim(result.data),
            'warnings': result.warnings
        })
    else:
        return json_error('; '.join(result.errors), 400)
```

**CRITICAL: Database Path Configuration**

Both `endpoints/pkb.py` and `Conversation.py` MUST use the same database path:

```python
# endpoints/pkb.py
def get_pkb_db():
    st = get_state()
    pkb_db_path = os.path.join(st.users_dir, "pkb.sqlite")
    # → storage/users/pkb.sqlite

# Conversation.py
def get_pkb_database():
    pkb_db_path = os.path.join(os.path.dirname(__file__), "storage", "users", "pkb.sqlite")
    # MUST match the path above
```

**Common Bug:** Mismatched paths cause UI writes to go to one database while Conversation.py reads from another.

---

### Pattern B: Conversation.py Integration

**Purpose:** Async PKB context retrieval during LLM reply generation

**Key Function:** `_get_pkb_context()`

```python
def _get_pkb_context(
    self,
    user_email: str,
    query: str,
    conversation_summary: str = "",
    k: int = 10,
    attached_claim_ids: list = None,           # From UI "Use Now"
    conversation_id: str = None,
    conversation_pinned_claim_ids: list = None,  # From server
    referenced_claim_ids: list = None          # From @memory:id
) -> str:
```

**Integration in reply():**
```python
def reply(self, query, userData=None, ...):
    # Extract attachment IDs from query
    attached_claim_ids = query.get("attached_claim_ids", [])
    conversation_pinned_claim_ids = query.get("conversation_pinned_claim_ids", [])
    referenced_claim_ids = query.get("referenced_claim_ids", [])
    
    # Start async PKB fetch (runs in parallel with other processing)
    pkb_future = get_async_future(
        self._get_pkb_context,
        user_email,
        query["messageText"],
        self.running_summary,
        k=10,
        attached_claim_ids=attached_claim_ids,
        conversation_id=self.conversation_id,
        conversation_pinned_claim_ids=conversation_pinned_claim_ids,
        referenced_claim_ids=referenced_claim_ids
    )
    
    # ... continue with other processing (embeddings, memory, etc.) ...
    
    # Wait for PKB context (only blocks if not ready yet)
    pkb_context = pkb_future.result(timeout=5.0)
    
    # Stage 1: Include in distillation prompt sent to cheap LLM
    # (extracts relevant user prefs from pkb + user_memory + user_preferences)
    user_info_text = f"... {pkb_section} {user_memory} {user_preferences} ..."
    distilled = cheap_llm(user_info_text)
    
    # Stage 2: Re-append only [REFERENCED] claims AFTER distillation
    # (auto/pinned/attached claims handled by distillation; referenced claims
    #  must reach the main LLM verbatim since the user explicitly asked for them)
    referenced_only = self._extract_referenced_claims(pkb_context)
    if referenced_only:
        ref_section = f"\n**User's explicitly referenced memories (ground truth):**\n{referenced_only}\n"
    user_info_text = f"User Preferences:\n{distilled}\n{ref_section}"
```

**Priority System:**
1. **REFERENCED** (from `@memory:id`) - Highest
2. **ATTACHED** (from "Use Now" UI) - High
3. **GLOBAL PINNED** (meta_json.pinned=true) - Medium-high
4. **CONV PINNED** (session-level) - Medium
5. **AUTO** (hybrid search) - Normal

**Deduplication:**
- Claims are deduplicated by `claim_id`
- Earlier sources (higher priority) win

---

## API Surface

### REST Endpoints (endpoints/pkb.py)

All endpoints require authentication (`@login_required`) and return JSON.

#### Claims Management

```
GET    /pkb/claims                        List claims with filters
POST   /pkb/claims                        Add new claim
GET    /pkb/claims/<id>                   Get single claim
PUT    /pkb/claims/<id>                   Edit claim
DELETE /pkb/claims/<id>                   Soft-delete claim
POST   /pkb/claims/bulk                   Bulk add claims
```

#### Search

```
POST   /pkb/search                        Search claims
       Body: {query, strategy, k, filters}
```

#### Memory Update Workflow

```
POST   /pkb/propose_updates               Extract from conversation
       Body: {conversation_summary, user_message, assistant_message}
       Returns: {plan_id, proposed_actions, user_prompt}

POST   /pkb/execute_updates               Execute approved updates
       Body: {plan_id, approved_indices}
       OR    {plan_id, approved: [{index, statement?, ...}]}
```

#### Text Ingestion

```
POST   /pkb/ingest_text                   Analyze text for memories
       Body: {text, default_claim_type, default_domain, use_llm}
       Returns: {plan_id, proposals, add_count, edit_count, skip_count}

POST   /pkb/execute_ingest                Execute ingestion plan
       Body: {plan_id, approved: [{index, statement?, ...}]}
```

#### Pinning (Deliberate Memory Attachment)

```
POST   /pkb/claims/<id>/pin               Toggle global pin
       Body: {pin: true|false}

GET    /pkb/pinned                        Get all globally pinned claims

POST   /pkb/conversation/<conv_id>/pin    Pin to conversation
       Body: {claim_id, pin}

GET    /pkb/conversation/<conv_id>/pinned Get conversation-pinned claims

DELETE /pkb/conversation/<conv_id>/pinned Clear conversation pins
```

#### Entities & Tags

```
GET    /pkb/entities                      List entities
GET    /pkb/tags                          List tags
```

#### Conflicts

```
GET    /pkb/conflicts                     List open conflicts
POST   /pkb/conflicts/<id>/resolve        Resolve conflict
       Body: {winning_claim_id?, resolution_notes}
```

#### Context Retrieval (Internal)

```
POST   /pkb/relevant_context              Get formatted context for LLM
       Body: {query, conversation_summary, k}
```

---

## Contexts (Groups): Hierarchy & Resolution

Contexts are named, hierarchical groupings of claims (`truth_management_system/crud/contexts.py`). They are the PKB's primary user-driven organizing structure and one of the `@reference` types.

**Data model:**
- A context has `context_id`, `name`, `friendly_id` (suffixed `_context`), optional `description`, optional `parent_context_id`, `domain`, and `user_email`.
- Claims link to contexts many-to-many via the `context_claims` join table.
- Contexts form a **tree** via `parent_context_id` (a claim can belong to many contexts; a context has at most one parent).

**Hierarchy traversal (recursive CTEs):**
- `get_descendants(context_id)` walks the tree downward with a `WITH RECURSIVE` CTE (children → grandchildren → …).
- `resolve_claims(context_id, statuses, max_depth=10)` is the **core resolution method** used when a user references `@context_friendly_id` in chat. It builds the full sub-tree of context IDs (recursive CTE, depth-capped at 10), joins through `context_claims` to `claims`, filters by status (default active + contested), de-duplicates by `claim_id`, and returns them newest-first. So referencing a parent context pulls in claims from every nested sub-context.

**Cycle safety:** `_validate_no_cycle(context_id, parent_id)` runs before any parent assignment — it rejects self-parenting and walks the ancestor chain to ensure the proposed parent doesn't already descend from the context (raising `ValueError` on a detected cycle). `max_depth` on resolution is a second guard against runaway recursion.

**UI:** the **Contexts tab** (`#pkb-contexts-pane`) lets users create a context (name, friendly-id, description), list contexts with claim counts (`get_with_claim_count()`), expand a context to see its linked claims (`loadContextClaimsPanel`), and attach/detach claims (`addClaimToContext` / `removeClaimFromContext` → `POST/DELETE /pkb/contexts/<id>/claims`). The Add/Edit Memory modal (`#pkb-claim-edit-modal`) also offers a multi-select to assign a claim to contexts at creation/edit time.

**REST:** `GET/POST /pkb/contexts`, `GET/PUT/DELETE /pkb/contexts/<id>`, `POST /pkb/contexts/<id>/claims`, `DELETE /pkb/contexts/<id>/claims/<claim_id>`, `GET /pkb/contexts/<id>/resolve`.

---

## Intelligence Layer: Auto-Parsing, Connections & Conflict Detection

The PKB turns a free-text statement into a richly-linked, searchable memory through an LLM enrichment pipeline plus cross-claim graph links. The LLM helpers live in `truth_management_system/llm_helpers.py` (`LLMHelpers`); enrichment is orchestrated by `StructuredAPI.add_claim()` (`auto_extract=True` by default).

### 1. Auto-parsing on add (`StructuredAPI.add_claim`, `auto_extract=True`)
When a claim is added with auto-extract on and an LLM configured:
- **`extract_single()` / `analyze_claim_statement()`** — a (mostly) single-call analysis that extracts **claim_type** (fact, preference, decision, task, reminder, habit, memory, observation), **context_domain** (personal, health, work, relationships, learning, life_ops, finance), **tags** (3–5 reusable lowercase tags), and **entities** (people/orgs/places/topics/projects/systems with a `type`). User-provided values win; extracted values fill the gaps. A generic `observation` type is upgraded to the inferred type. `analyze_claim_statement()` is the shared path behind both the modal **Auto-fill** button (cheap/fast model) and text ingestion (stronger model).
- **`generate_possible_questions()`** — generates 2–4 **self-sufficient** questions the claim could answer (each must embed the claim's specific entities so it is searchable standalone). Stored in `possible_questions`, indexed into FTS — this is the "QnA-style" retrieval boost that lets a user's natural question match a stored fact.
- **`extract_spo()`** — extracts a subject–predicate–object triple for structured relations.

### 2. Connections across types (the graph)
A claim becomes a node connected to other object types:
- **Entities** (`claim_entities` join) — extracted people/places/orgs/topics are upserted and linked; `@entity_fid` resolves to *all* claims linked to that entity.
- **Tags** (`claim_tags` join, hierarchical) — `@tag_fid` resolves recursively to claims tagged with the tag *and all descendant tags* (recursive CTE).
- **Contexts** (`context_claims` join, hierarchical) — see the Contexts section above.
- **Domains** — `@domain_name_domain` resolves to all claims in a domain via query-time filtering.

All four are reachable through the unified `@reference` resolver `StructuredAPI.resolve_reference()`, which uses the friendly-id **type suffix** (`_context` / `_entity` / `_tag` / `_domain`, none = claim) to route directly to the right object type, with legacy fallbacks for unsuffixed references.

### 3. Similarity, duplicates & conflict detection
On add, `check_similarity(new_statement, existing_claims, threshold=0.85)` embeds the new claim (via `code_common.call_llm` embeddings) and computes cosine similarity against existing active claims in the same domain:
- **> 0.95 → `duplicate`** (warns the user a near-identical claim exists).
- **> 0.85 → LLM contradiction check** (`_classify_relation` asks the LLM "do these contradict?"; returns `contradicts` or `related`).
- Contradictions can be promoted into a **ConflictSet** (`crud/conflicts.py`: `create` / `add_member` / `resolve` / `ignore`), surfaced in the **Conflicts tab** for the user to resolve. This is the "truth management" part — the system actively notices when a new memory clashes with an old one instead of silently storing both.

### 4. Auto-capture from conversation (distillation, `auto_pkb_extract`)
This is what the **"Auto-save facts"** checkbox (`#settings-auto_pkb_extract`, default ON) controls. When enabled, after each chat turn the frontend (`common-chat.js`) fires a 3-second-delayed `PKBManager.checkMemoryUpdates()` → `POST /pkb/propose_updates`. When the box is OFF, that call is skipped entirely (no request, no modal). `/pkb` and `/memory` commands also skip it to avoid duplicate proposals.

Backend: `interface/conversation_distillation.py` (`ConversationDistiller.extract_and_propose()`) uses the PKB's configured LLM (`config.llm_model`, default `google/gemini-3.1-flash-lite-preview`, temperature 0.0) to scan the conversation summary + latest user message for memorable facts (`_extract_claims_from_turn`). An `extraction_mode` of `relaxed` (default) or `aggressive` tunes how eagerly it proposes. Each candidate is matched against existing memories (`_find_existing_matches`, reusing the embedding-similarity machinery from §3) and returned as a `MemoryUpdatePlan` of proposed **add / edit / skip** actions. **Nothing is persisted** until the user approves in the bulk proposal modal `#memory-proposal-modal` (`showBulkProposalModal` → `collectApprovedProposals` → `POST /pkb/execute_updates` → `execute_plan`).

### 5. Temporal intelligence (auto-expiry)
`task`/`reminder` claims require `valid_to`. `expire_stale_claims()` (run at DB init and lazily during search) flips claims whose `valid_to` is in the past to the `expired` status, which is excluded from search by default — so time-bound memories age out automatically without user cleanup.

### 6. Bulk / text ingestion
`interface/text_ingestion.py` and `add_claims_bulk()` apply the same per-claim enrichment (optionally) across many statements in parallel (`batch_extract_all`), used by the **Bulk Add** and **Import Text** tabs.

### 7. Models used (the intelligence runs on cheap LLMs + embeddings)
| Pipeline | Model | Where |
|---|---|---|
| Per-claim enrichment (`extract_single`, `generate_possible_questions`, `extract_spo`) | `config.llm_model` (default `google/gemini-3.1-flash-lite-preview`) | `StructuredAPI.add_claim` |
| Modal **Auto-fill** button (`analyze_claim_statement`) | `CHEAP_LLM[0]` (falls back to `config.llm_model`) | `POST /pkb/analyze_statement` |
| Conversation distillation (auto-save) | `config.llm_model`, temp 0.0 | `ConversationDistiller` |
| `pkb_nl_command` / `/pkb` NL agent | `pkb_nl_model` override → else `CHEAP_LLM[0]` | `PKBNLAgent` |
| Text ingestion enrichment | stronger/expensive model | `text_ingestion.py` |
| Similarity / duplicate / contradiction | embeddings (`get_query_embedding`/`get_document_embedding`) + an LLM yes/no contradiction check | `LLMHelpers.check_similarity` / `_classify_relation` |
| Embeddings | `config.embedding_model` | search + similarity |

The design deliberately uses **cheap, fast models** (Gemini Flash Lite / `CHEAP_LLM`) for the high-frequency enrichment and auto-save paths, reserving stronger models for explicit bulk text ingestion.

---

## PKB Tool Surfaces (MCP vs LLM Tool-Calling vs REST)

The PKB is exposed through **three** programmatic surfaces plus auto-save. Do not confuse them:

### A. MCP tools — `mcp_server/pkb.py` (external clients)
Streamable-HTTP + JWT, port 8101, tiered by `MCP_TOOL_TIER` (8 baseline / 15 full). See the README "MCP Tool Surface" for the full list. MCP does **not** include `pkb_propose_memory` (it is UI-interactive); MCP writes go through `pkb_add_claim` / `pkb_nl_command`.

### B. In-app LLM tool-calling tools — `code_common/tools.py`
`tools.py` registers ~16 PKB tools (mirroring the MCP surface: `pkb_search`, `pkb_get_claim`, `pkb_resolve_reference`, `pkb_get_pinned_claims`, `pkb_add_claim`, `pkb_edit_claim`, `pkb_get_claims_by_ids`, `pkb_autocomplete`, `pkb_resolve_context`, `pkb_delete_claim`, `pkb_pin_claim`, `pkb_nl_command`, `pkb_propose_memory`, `pkb_list_contexts`, `pkb_list_entities`, `pkb_list_tags`). **Only 3 are user-selectable** in the chat tool selector (`interface.html` optgroup "Knowledge Base (PKB)"):

| UI option | Tool | Interactive | Notes |
|---|---|---|---|
| 🗣️ NL Command | `pkb_nl_command` | no | Default-selected; also in `DEFAULT_ENABLED_TOOLS`. Runs `PKBNLAgent` agentic loop; description steers it to high-recall search. |
| Delete Claim | `pkb_delete_claim` | no | Delete a claim by id. |
| 📝 Propose Memory | `pkb_propose_memory` | **yes** | Shows an editable review modal before saving (see below). |

The remaining ~13 are registered for tool-calling but not surfaced in the selector — typically invoked indirectly (e.g. by the NL agent).

### C. REST — `endpoints/pkb.py` (`/pkb/*`), used by the web UI.

### How `pkb_propose_memory` works (interactive, two-path)
`pkb_propose_memory` is `is_interactive=True` — its handler executes **no logic**; it returns `ToolCallResult(needs_user_input=True, ui_schema=args)` to pause the agentic loop for user confirmation. Input schema: a `claims` array (each `text`, `claim_type` ∈ {fact, preference, event, task, reminder, goal, note}, `valid_from`, `valid_to` [required for task/reminder], `tags`, `entities`, `context`) plus a `message` explaining why review is needed.

Two paths surface the **same** modal:
1. **Main LLM path:** the LLM calls `pkb_propose_memory` directly → `needs_user_input` → SSE `tool_input_request` event.
2. **`/pkb` NL-agent path:** `handle_pkb_nl_command` runs `PKBNLAgent`; if `result.needs_user_input and result.proposed_claims`, it re-labels the result as `tool_name="pkb_propose_memory"` with `ui_schema={claims, message}` → same event.

Frontend (`interface/tool-call-manager.js`): `handleToolInputRequest()` renders the **`#tool-call-modal`** ("Review Proposed Memories") via `_renderMemoryProposalForm(claims)` — editable cards with a remove button. **Submit** → `_collectMemoryProposalResponse()` → `submitToolResponse()`; the backend's `tool_response_waiter` resumes the loop and saves the confirmed claims. **Skip** → `{ skipped: true }`.

### Two different "proposal" modals — don't conflate
| Modal | Trigger | Purpose |
|---|---|---|
| `#memory-proposal-modal` | Auto-save (`auto_pkb_extract` → `checkMemoryUpdates` → `/pkb/propose_updates`) | Review bulk facts distilled from the conversation |
| `#tool-call-modal` | `pkb_propose_memory` tool (main LLM or `/pkb` agent) | Review claims the LLM/agent explicitly proposes during tool use |

---

## Frontend Architecture

### JavaScript Module: pkb-manager.js

**Module Pattern:**
```javascript
var PKBManager = (function() {
    'use strict';
    
    // Private state
    var currentPage = 0;
    var pageSize = 20;
    var currentPlanId = null;
    var currentProposals = [];
    var pendingMemoryAttachments = [];  // For "Use Now"
    var pendingMemoryDetails = {};
    
    // Private functions
    function listClaims(filters, limit, offset) { ... }
    function renderClaimCard(claim) { ... }
    
    // Public API
    return {
        // CRUD
        listClaims: listClaims,
        addClaim: addClaim,
        editClaim: editClaim,
        deleteClaim: deleteClaim,
        
        // Search
        searchClaims: searchClaims,
        
        // Memory updates
        checkMemoryUpdates: checkMemoryUpdates,
        showMemoryProposalModal: showMemoryProposalModal,
        saveSelectedProposals: saveSelectedProposals,
        
        // Bulk operations
        addBulkRow: addBulkRow,
        saveBulkClaims: saveBulkClaims,
        analyzeTextForIngestion: analyzeTextForIngestion,
        
        // Pinning
        pinClaim: pinClaim,
        getPinnedClaims: getPinnedClaims,
        addToNextMessage: addToNextMessage,
        clearPendingAttachments: clearPendingAttachments,
        
        // UI
        openPKBModal: openPKBModal,
        loadClaims: loadClaims
    };
})();
```

### HTML Structure (interface.html)

**PKB Modal** (`#pkb-modal`, interface.html line ~843; tab bar `#pkb-tabs`):
```html
<div class="modal" id="pkb-modal">
  <div class="modal-body">
    <ul class="nav nav-tabs" id="pkb-tabs">
      <li><a href="#pkb-claims-pane">Claims</a></li>      <!-- search, filters, paginated list, Add Memory -->
      <li><a href="#pkb-entities-pane">Entities</a></li>  <!-- create + expandable linked-claim panels -->
      <li><a href="#pkb-tags-pane">Tags</a></li>          <!-- create + expandable linked-claim panels -->
      <li><a href="#pkb-conflicts-pane">Conflicts</a></li><!-- list + resolve contradictory claims -->
      <li><a href="#pkb-bulk-pane">Bulk Add</a></li>      <!-- multi-row add with progress bar -->
      <li><a href="#pkb-import-pane">Import Text</a></li> <!-- paste text, LLM analyze, ingest -->
      <li><a href="#pkb-contexts-pane">Contexts</a></li>  <!-- create context, expand, attach/detach claims -->
    </ul>
    
    <div class="tab-content">
      <!-- Claims Tab -->
      <div id="pkb-claims-pane">
        <input id="pkb-search-input" />
        <button id="pkb-search-btn">Search</button>
        <button id="pkb-add-claim-btn">Add Memory</button>
        
        <!-- Filters -->
        <select id="pkb-filter-type">...</select>
        <select id="pkb-filter-domain">...</select>
        <select id="pkb-filter-status">...</select>
        
        <!-- Claims List -->
        <div id="pkb-claims-list">
          <!-- Rendered by renderClaimCard() -->
        </div>
        
        <!-- Pagination -->
        <button id="pkb-prev-page">Prev</button>
        <button id="pkb-next-page">Next</button>
      </div>
      
      <!-- Other tabs... -->
    </div>
  </div>
</div>
```

**Memory Proposal Modal** (`#memory-proposal-modal`, interface.html line ~1327):
```html
<div class="modal" id="memory-proposal-modal">
  <div class="modal-body">
    <p id="memory-proposal-intro">...</p>
    
    <!-- Summary counts -->
    <span id="proposal-add-count">0 new</span>
    <span id="proposal-edit-count">0 updates</span>
    <span id="proposal-skip-count">0 skipped</span>
    
    <!-- Select controls -->
    <button id="proposal-select-all">Select All</button>
    <button id="proposal-deselect-all">Deselect All</button>
    
    <!-- Proposals list (rendered by JS) -->
    <div id="memory-proposal-list">
      <!-- Each proposal: checkbox, badge, statement, type/domain dropdowns -->
    </div>
    
    <!-- Hidden fields -->
    <input type="hidden" id="memory-proposal-plan-id">
    <input type="hidden" id="memory-proposal-source">
  </div>
  
  <div class="modal-footer">
    <button id="memory-proposal-skip">Cancel</button>
    <button id="memory-proposal-save">Save Selected (<span id="proposal-save-count">0</span>)</button>
  </div>
</div>
```

### Common UI Patterns

**Pattern 1: Render Claim Card**
```javascript
function renderClaimCard(claim) {
    var isPinned = isClaimPinned(claim);
    var pinIcon = isPinned ? 'bi-pin-fill' : 'bi-pin';
    
    return '<div class="list-group-item" data-claim-id="' + claim.claim_id + '">' +
        '<p>' + escapeHtml(claim.statement) + '</p>' +
        '<span class="badge badge-' + typeColor + '">' + claim.claim_type + '</span>' +
        (claim.status === 'contested' ? '<span class="badge badge-warning">Contested</span>' : '') +
        (isPinned ? '<span class="badge badge-warning"><i class="bi bi-pin-fill"></i> Pinned</span>' : '') +
        '<div class="btn-group">' +
            '<button class="pkb-pin-claim" data-claim-id="' + claim.claim_id + '"><i class="' + pinIcon + '"></i></button>' +
            '<button class="pkb-use-now-claim"><i class="bi bi-chat-right-text"></i></button>' +
            '<button class="pkb-edit-claim"><i class="bi bi-pencil"></i></button>' +
            '<button class="pkb-delete-claim"><i class="bi bi-trash"></i></button>' +
        '</div>' +
    '</div>';
}
```

**Pattern 2: Event Delegation**
```javascript
// Bind handlers to parent, use event delegation
$('#pkb-claims-list').on('click', '.pkb-pin-claim', function() {
    var claimId = $(this).data('claim-id');
    var isPinned = $(this).data('pinned');
    togglePinAndRefresh(claimId, isPinned);
});

$('#pkb-claims-list').on('click', '.pkb-use-now-claim', function() {
    var claimId = $(this).data('claim-id');
    addToNextMessage(claimId);
});
```

**Pattern 3: Pending Attachments Indicator**
```javascript
function updatePendingAttachmentsIndicator() {
    // Create indicator if doesn't exist
    if ($('#pending-memories-indicator').length === 0) {
        var html = '<div id="pending-memories-container">' +
            '<div id="pending-memories-indicator" class="alert alert-info">' +
                '<strong><i class="bi bi-bookmark-star"></i> Memories attached:</strong>' +
                '<span id="pending-memories-list"></span>' +
                '<button id="clear-pending-memories">Clear</button>' +
            '</div>' +
        '</div>';
        $('#chat-input-container').before(html);
    }
    
    // Show/hide based on pending count
    if (pendingMemoryAttachments.length === 0) {
        $('#pending-memories-container').hide();
    } else {
        // Build chips for each pending memory
        var chips = pendingMemoryAttachments.map(function(claimId) {
            var statement = pendingMemoryDetails[claimId].statement;
            return '<span class="badge badge-pill badge-primary">' +
                escapeHtml(statement.substring(0, 40)) + '...' +
                '<button class="remove-pending-memory" data-claim-id="' + claimId + '">×</button>' +
            '</span>';
        });
        $('#pending-memories-list').html(chips.join(''));
        $('#pending-memories-container').show();
    }
}
```

---

## Multi-User Implementation

### Schema Design

**User Email Column:** Added to all primary tables in v2:
- `claims.user_email`
- `notes.user_email`
- `entities.user_email`
- `tags.user_email`
- `conflict_sets.user_email`

**Unique Constraints (Per-User):**
```sql
-- Entities: prevent duplicate names per user
UNIQUE(user_email, entity_type, name)

-- Tags: prevent duplicate tag names under same parent per user
UNIQUE(user_email, name, parent_tag_id)
```

**Indexes:**
```sql
CREATE INDEX idx_claims_user_email ON claims(user_email);
CREATE INDEX idx_claims_user_status ON claims(user_email, status);
CREATE INDEX idx_notes_user_email ON notes(user_email);
CREATE INDEX idx_entities_user_email ON entities(user_email);
CREATE INDEX idx_tags_user_email ON tags(user_email);
CREATE INDEX idx_conflict_sets_user_email ON conflict_sets(user_email);
```

### CRUD Layer Integration

**BaseCRUD Methods:**
```python
class BaseCRUD[T]:
    def __init__(self, db: PKBDatabase, user_email: Optional[str] = None):
        self.db = db
        self.user_email = user_email
    
    def _user_filter_sql(self) -> str:
        """Return SQL clause for user filtering."""
        if self.user_email:
            return f" AND {self._table_name()}.user_email = ?"
        return ""
    
    def _user_filter_params(self) -> tuple:
        """Return params tuple for user filtering."""
        if self.user_email:
            return (self.user_email,)
        return ()
    
    def list(self, filters=None, limit=None, offset=None) -> List[T]:
        # Build SQL with user filter
        sql = f"SELECT * FROM {self._table_name()} WHERE 1=1"
        params = []
        
        # Add user filter
        sql += self._user_filter_sql()
        params.extend(self._user_filter_params())
        
        # Add other filters...
        # ...
        
        rows = self.db.fetchall(sql, tuple(params))
        return [self._to_model(row) for row in rows]
```

**ClaimCRUD Auto User Assignment:**
```python
def add(self, claim: Claim, tags, entities) -> Claim:
    # Ensure claim has user_email
    if self.user_email and not claim.user_email:
        claim.user_email = self.user_email
    
    # Continue with insert...
```

### Search Layer Integration

**SearchFilters:**
```python
@dataclass
class SearchFilters:
    statuses: List[str] = field(default_factory=lambda: ['active', 'contested'])
    context_domains: Optional[List[str]] = None
    claim_types: Optional[List[str]] = None
    tag_ids: Optional[List[str]] = None
    entity_ids: Optional[List[str]] = None
    valid_at: Optional[str] = None
    include_contested: bool = True
    user_email: Optional[str] = None  # <-- Multi-user support
    
    def to_sql_conditions(self) -> Tuple[str, List]:
        conditions = []
        params = []
        
        # ... other filters ...
        
        # User filter
        if self.user_email:
            conditions.append("c.user_email = ?")
            params.append(self.user_email)
        
        return (" AND ".join(conditions), params)
```

### API Layer Integration

**StructuredAPI:**
```python
class StructuredAPI:
    def __init__(self, db, keys, config, user_email=None):
        self.user_email = user_email
        
        # All CRUD instances scoped to user
        self.claims = ClaimCRUD(db, user_email=user_email)
        self.notes = NoteCRUD(db, user_email=user_email)
        # ...
    
    def search(self, query, strategy, k, filters=None):
        # Build filters with user_email
        search_filters = SearchFilters(
            user_email=self.user_email,
            # ... other filters ...
        )
        
        results = self.search_strategy.search(query, k=k, filters=search_filters)
        return ActionResult(success=True, data=results)
```

### Endpoint Layer Integration

**endpoints/pkb.py:**
```python
@pkb_bp.route('/pkb/claims', methods=['GET'])
@login_required
def handle_list_claims():
    # Get user from session
    user_email = get_session_identity().email
    
    # Get user-scoped API
    api = get_pkb_api_for_user(user_email, keyParser.get_api_keys())
    
    # All operations automatically filtered by user_email
    result = api.claims.list(filters={'status': 'active'})
    
    return jsonify({
        'claims': [serialize_claim(c) for c in result]
    })
```

---

## Memory Attachment System

### Attachment Mechanisms

1. **@memory References** (Highest Priority)
   - Syntax: `@memory:claim_id` or `@mem:claim_id`
   - Parsed in message text
   - Claim IDs extracted and sent as `referenced_claim_ids`

2. **"Use in Next Message"** (High Priority)
   - User clicks button on claim card
   - Stored in `pendingMemoryAttachments[]` (frontend)
   - Sent as `attached_claim_ids` with next message
   - Cleared after sending

3. **Global Pinning** (Medium-High Priority)
   - Toggle button on claim card
   - Stored in `meta_json.pinned = true` (database)
   - Always retrieved via `api.get_pinned_claims()`

4. **Conversation Pinning** (Medium Priority)
   - Pin claim to specific conversation
   - Stored in server memory: `_conversation_pinned_claims[conv_id] = set(claim_ids)`
   - Ephemeral (lost on server restart)
   - Injected by server before passing to Conversation.py

5. **Auto-Retrieval** (Normal Priority)
   - Hybrid search based on query
   - Fills remaining slots after deliberate attachments

### Frontend Implementation

**@memory and @friendly_id Reference Parsing:**
```javascript
// parseMemoryReferences(text) in parseMessageForCheckBoxes.js
// Parses three kinds of references:
//   1. Legacy: @memory:uuid or @mem:uuid → claimIds
//   2. Friendly IDs (claims): @prefer_morning_a3f2 → friendlyIds
//   3. Friendly IDs (contexts): @ssdva, @work_context_a3b2 → friendlyIds
//
// Rules:
//   - @ must be at start of string or preceded by whitespace (not email)
//   - Friendly IDs need 3+ chars after @ (avoids false positives)
//   - @memory and @mem standalone are skipped (legacy prefix words)
//   - Backend resolve_reference() determines if a friendlyId is a claim or context
//
// Returns: {cleanText, claimIds: [...], friendlyIds: [...]}
```

**Send Message Integration:**
```javascript
function sendMessageCallback() {
    var messageText = $('#user-input').val();
    
    // Get pending attachments
    var attached_claim_ids = [];
    if (typeof PKBManager !== 'undefined') {
        attached_claim_ids = PKBManager.getPendingAttachments();
        PKBManager.clearPendingAttachments();
    }
    
    // Parse @memory and @friendly_id references
    var referenced_claim_ids = [];
    var referenced_friendly_ids = [];
    var memoryRefs = parseMemoryReferences(messageText);
    referenced_claim_ids = memoryRefs.claimIds;        // Legacy @memory:uuid
    referenced_friendly_ids = memoryRefs.friendlyIds;  // @friendly_id (claim or context)
    
    // Send message with attachments
    ChatManager.sendMessage(
        conversationId,
        messageText,
        checkboxes,
        links,
        search,
        attached_claim_ids,
        referenced_claim_ids,
        referenced_friendly_ids
    ).then(function(response) {
        // Handle response...
    });
}
```

### Backend Implementation

**Server Injection (endpoints/conversations.py or server.py):**
```python
@app.route('/send_message/<conversation_id>', methods=['POST'])
@login_required
def send_message(conversation_id):
    query = request.get_json()
    
    # Inject conversation-pinned claim IDs
    conv_pinned_ids = list(get_conversation_pinned_claims(conversation_id))
    if conv_pinned_ids:
        query['conversation_pinned_claim_ids'] = conv_pinned_ids
    
    # Pass to Conversation.reply()
    # ... conversation.reply(query, ...) ...
```

**Conversation.py Context Retrieval:**
```python
def _get_pkb_context(
    self, user_email, query, conversation_summary, k,
    attached_claim_ids=None,
    conversation_pinned_claim_ids=None,
    referenced_claim_ids=None
):
    attached_claim_ids = attached_claim_ids or []
    conversation_pinned_claim_ids = conversation_pinned_claim_ids or []
    referenced_claim_ids = referenced_claim_ids or []
    
    all_claims = []  # List of (source, claim) tuples
    seen_ids = set()
    
    # 1. REFERENCED (highest priority)
    if referenced_claim_ids:
        result = api.get_claims_by_ids(referenced_claim_ids)
        if result.success:
            for claim in result.data:
                if claim and claim.claim_id not in seen_ids:
                    all_claims.append(("referenced", claim))
                    seen_ids.add(claim.claim_id)
    
    # 2. ATTACHED
    if attached_claim_ids:
        result = api.get_claims_by_ids(attached_claim_ids)
        if result.success:
            for claim in result.data:
                if claim and claim.claim_id not in seen_ids:
                    all_claims.append(("attached", claim))
                    seen_ids.add(claim.claim_id)
    
    # 3. GLOBAL PINNED
    result = api.get_pinned_claims(limit=50)
    if result.success:
        for claim in result.data:
            if claim.claim_id not in seen_ids:
                all_claims.append(("global_pinned", claim))
                seen_ids.add(claim.claim_id)
    
    # 4. CONV PINNED
    if conversation_pinned_claim_ids:
        result = api.get_claims_by_ids(conversation_pinned_claim_ids)
        if result.success:
            for claim in result.data:
                if claim and claim.claim_id not in seen_ids:
                    all_claims.append(("conv_pinned", claim))
                    seen_ids.add(claim.claim_id)
    
    # 5. AUTO SEARCH (fill remaining slots)
    remaining_k = max(0, k - len(all_claims))
    if remaining_k > 0:
        result = api.search(query, strategy='hybrid', k=remaining_k)
        if result.success:
            for search_result in result.data:
                claim = search_result.claim
                if claim.claim_id not in seen_ids:
                    all_claims.append(("auto", claim))
                    seen_ids.add(claim.claim_id)
    
    # Format with source indicators
    formatted_lines = []
    for source, claim in all_claims:
        source_label = {
            "referenced": "[REFERENCED]",
            "attached": "[ATTACHED]",
            "global_pinned": "[GLOBAL PINNED]",
            "conv_pinned": "[CONV PINNED]",
            "auto": "[AUTO]"
        }[source]
        
        formatted_lines.append(
            f"{source_label} [{claim.claim_type}] {claim.statement}"
        )
    
    return "\n".join(formatted_lines)
```

---

## Search Architecture

### Strategy Comparison

| Strategy | Speed | Cost | Deterministic | Best For |
|----------|-------|------|---------------|----------|
| **FTS** | ⚡ Fast | Free | ✅ Yes | Keyword matches, deterministic recall |
| **Embedding** | Medium | API | ❌ No | Semantic/conceptual queries |
| **Rewrite** | Medium | API | ❌ No | Messy queries, voice transcripts |
| **MapReduce** | Slow | High API | ❌ No | High-precision requirements |
| **Hybrid** | Medium | API | ❌ No | General use (recommended) |

### Hybrid Strategy Details

**Default Configuration:**
```python
# strategies = ["fts", "embedding"]
# Runs both in parallel, merges with RRF
```

**Execution Timeline:**
```
Time 0ms: Start both strategies in parallel
    ├── FTS thread:    SELECT ... FROM claims_fts ... (~50ms)
    └── Embedding thread:
        ├── Get query embedding (~200ms)
        ├── Load candidates from DB (~50ms)
        └── Compute similarities (~100ms)

Time 350ms: Both complete, merge with RRF
Time 370ms: Return top-k results
```

**RRF Algorithm:**
```python
def merge_results_rrf(result_lists, k, rrf_k=60):
    """
    RRF (Reciprocal Rank Fusion) merging:
    - Score for item at rank r: 1 / (rrf_k + r)
    - Sum scores across all result lists
    - Sort by combined score
    """
    scores = {}
    
    for results in result_lists:
        for rank, result in enumerate(results):
            claim_id = result.claim.claim_id
            rrf_score = 1.0 / (rrf_k + rank + 1)
            
            if claim_id in scores:
                scores[claim_id] += rrf_score
            else:
                scores[claim_id] = rrf_score
    
    # Sort by combined score, descending
    sorted_items = sorted(scores.items(), key=lambda x: -x[1])
    
    # Return top-k
    return [reconstruct_result(cid) for cid, score in sorted_items[:k]]
```

**Benefits of RRF:**
- No need to normalize scores across strategies
- Naturally handles different score ranges
- Prioritizes items ranked highly by multiple strategies
- Simple and effective in practice

### FTS Query Patterns

**Basic Match:**
```sql
SELECT c.*, bm25(claims_fts) as score
FROM claims_fts f
JOIN claims c ON f.claim_id = c.claim_id
WHERE claims_fts MATCH 'coffee preferences'
  AND c.status IN ('active', 'contested')
  AND c.user_email = ?
ORDER BY score
LIMIT 10
```

**Phrase Match:**
```sql
-- Use quotes for exact phrase
WHERE claims_fts MATCH '"morning workout"'
```

**Boolean Operators:**
```sql
-- AND
WHERE claims_fts MATCH 'coffee AND morning'

-- OR
WHERE claims_fts MATCH 'coffee OR tea'

-- NOT
WHERE claims_fts MATCH 'coffee NOT decaf'
```

**Column-Specific:**
```sql
-- Search only in statement column
WHERE claims_fts MATCH 'statement:coffee'
```

### Embedding Search Details

**Cosine Similarity:**
```python
def cosine_similarity(query_emb, doc_emb):
    """
    Compute cosine similarity between query and document embeddings.
    
    cos_sim(q, d) = dot(q, d) / (||q|| * ||d||)
    
    Returns: float in range [-1, 1], higher is more similar
    """
    dot_product = np.dot(query_emb, doc_emb)
    query_norm = np.linalg.norm(query_emb)
    doc_norm = np.linalg.norm(doc_emb)
    
    if query_norm == 0 or doc_norm == 0:
        return 0.0
    
    return dot_product / (query_norm * doc_norm)
```

**Embedding Caching:**
```python
class EmbeddingStore:
    def get_or_compute(self, claim_id, statement):
        # 1. Check cache
        cached = self.get_embedding(claim_id)
        if cached is not None:
            return cached
        
        # 2. Compute via API
        embedding = get_embedding(statement, model=self.model)
        
        # 3. Store in cache
        self.store_embedding(claim_id, embedding, self.model)
        
        return embedding
    
    def store_embedding(self, claim_id, embedding, model):
        # Store as BLOB in claim_embeddings table
        conn = self.db.connect()
        conn.execute(
            "INSERT OR REPLACE INTO claim_embeddings "
            "(claim_id, embedding, model_name, created_at) "
            "VALUES (?, ?, ?, ?)",
            (claim_id, embedding.tobytes(), model, now_iso())
        )
```

**Invalidation on Edit:**
```python
def edit(self, claim_id, patch):
    # If statement changed, invalidate embedding
    if 'statement' in patch:
        delete_claim_embedding(conn, claim_id)
    
    # Update claim...
```

---

## Common Development Patterns

### Pattern 1: Adding a New Endpoint

**Step 1:** Add endpoint to `endpoints/pkb.py`
```python
@pkb_bp.route('/pkb/my_new_endpoint', methods=['POST'])
@login_required
@limiter.limit("50 per hour")
def handle_my_new_endpoint():
    if not PKB_AVAILABLE:
        return json_error("PKB not available", 503)
    
    user_email = get_session_identity().email
    api = get_pkb_api_for_user(user_email, keyParser.get_api_keys())
    
    data = request.get_json()
    
    # Call API method
    result = api.my_new_method(...)
    
    if result.success:
        return jsonify({
            'success': True,
            'data': serialize_my_data(result.data)
        })
    else:
        return json_error('; '.join(result.errors), 400)
```

**Step 2:** Add method to `StructuredAPI`
```python
def my_new_method(self, param1, param2) -> ActionResult:
    try:
        # Use CRUD layer
        result = self.claims.some_operation(...)
        
        return ActionResult(
            success=True,
            action='my_action',
            object_type='claim',
            data=result
        )
    except Exception as e:
        logger.error(f"Failed: {e}")
        return ActionResult(
            success=False,
            action='my_action',
            object_type='claim',
            errors=[str(e)]
        )
```

**Step 3:** Add frontend function to `pkb-manager.js`
```javascript
function myNewOperation(param1, param2) {
    return $.ajax({
        url: '/pkb/my_new_endpoint',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            param1: param1,
            param2: param2
        }),
        dataType: 'json'
    });
}

// Public API
return {
    // ... existing methods ...
    myNewOperation: myNewOperation
};
```

**Step 4:** Add UI handler
```javascript
$(document).on('click', '#my-button', function() {
    PKBManager.myNewOperation(value1, value2)
        .done(function(response) {
            if (response.success) {
                showToast('Success!', 'success');
                loadClaims();  // Refresh
            } else {
                showToast(response.error, 'error');
            }
        })
        .fail(function(err) {
            showToast('Operation failed', 'error');
        });
});
```

### Pattern 2: Adding a New CRUD Operation

**Step 1:** Add method to CRUD class
```python
class ClaimCRUD(BaseCRUD[Claim]):
    def my_special_query(self, param) -> List[Claim]:
        """
        Description of what this query does.
        
        Args:
            param: Description
            
        Returns:
            List of claims matching criteria
        """
        sql = f"""
            SELECT * FROM {self._table_name()}
            WHERE some_condition = ?
            {self._user_filter_sql()}
            ORDER BY created_at DESC
        """
        
        params = [param]
        params.extend(self._user_filter_params())
        
        rows = self.db.fetchall(sql, tuple(params))
        return [self._to_model(row) for row in rows]
```

**Step 2:** Expose via StructuredAPI if needed
```python
def query_by_special_criteria(self, param) -> ActionResult:
    try:
        claims = self.claims.my_special_query(param)
        
        return ActionResult(
            success=True,
            action='query',
            object_type='claim',
            data=claims
        )
    except Exception as e:
        return ActionResult(
            success=False,
            action='query',
            object_type='claim',
            errors=[str(e)]
        )
```

### Pattern 3: Adding a New Search Strategy

**Step 1:** Create strategy class
```python
from .base import SearchStrategy, SearchFilters, SearchResult

class MyNewSearchStrategy(SearchStrategy):
    def __init__(self, db, keys, config):
        self.db = db
        self.keys = keys
        self.config = config
    
    def search(self, query: str, k: int, filters: SearchFilters) -> List[SearchResult]:
        # 1. Get candidates (apply filters)
        candidates = self._get_candidates(filters)
        
        # 2. Score candidates
        scored = self._score_candidates(query, candidates)
        
        # 3. Sort and return top-k
        scored.sort(key=lambda x: -x.score)
        return scored[:k]
    
    def name(self) -> str:
        return "my_strategy"
    
    def _get_candidates(self, filters):
        # Apply user_email and other filters
        sql = "SELECT * FROM claims WHERE 1=1"
        params = []
        
        conditions, filter_params = filters.to_sql_conditions()
        if conditions:
            sql += " AND " + conditions
            params.extend(filter_params)
        
        rows = self.db.fetchall(sql, tuple(params))
        return [Claim.from_row(row) for row in rows]
    
    def _score_candidates(self, query, candidates):
        results = []
        for claim in candidates:
            # Compute score
            score = self._compute_score(query, claim)
            
            results.append(SearchResult(
                claim=claim,
                score=score,
                source=self.name(),
                is_contested=(claim.status == 'contested'),
                warnings=[],
                metadata={}
            ))
        
        return results
```

**Step 2:** Register in HybridSearchStrategy
```python
def __init__(self, db, keys, config):
    # ... existing strategies ...
    
    # Add new strategy
    self.strategies["my_strategy"] = MyNewSearchStrategy(db, keys, config)
```

**Step 3:** Use in search
```python
# Direct use
strategy = MyNewSearchStrategy(db, keys, config)
results = strategy.search(query, k=10, filters=filters)

# Via HybridSearchStrategy
hybrid = HybridSearchStrategy(db, keys, config)
results = hybrid.search(query, strategy_names=["my_strategy"], k=10)
```

---

## Testing Strategy

### Unit Tests

**Location:** `truth_management_system/tests/`

**Key Test Files:**
- `test_crud.py` - CRUD operations
- `test_search.py` - Search strategies
- `test_interface.py` - Interface layer

**Common Patterns:**

```python
import pytest
from truth_management_system import (
    get_memory_database,
    ClaimCRUD,
    Claim,
    PKBConfig
)

@pytest.fixture
def db():
    """Create in-memory database for testing."""
    db = get_memory_database(auto_init=True)
    yield db
    db.close()

@pytest.fixture
def claim_crud(db):
    """Create ClaimCRUD instance."""
    return ClaimCRUD(db, user_email="test@example.com")

def test_add_claim(claim_crud):
    """Test adding a claim."""
    claim = Claim.create(
        statement="Test statement",
        claim_type="fact",
        context_domain="personal",
        user_email="test@example.com"
    )
    
    added = claim_crud.add(claim, tags=["test"], entities=[])
    
    assert added is not None
    assert added.claim_id == claim.claim_id
    assert added.statement == "Test statement"
    
    # Verify persistence
    retrieved = claim_crud.get(claim.claim_id)
    assert retrieved is not None
    assert retrieved.statement == "Test statement"

def test_multi_user_isolation(db):
    """Test that users only see their own claims."""
    user1_crud = ClaimCRUD(db, user_email="user1@example.com")
    user2_crud = ClaimCRUD(db, user_email="user2@example.com")
    
    # User 1 adds claim
    claim1 = Claim.create(
        statement="User 1 claim",
        claim_type="fact",
        context_domain="personal",
        user_email="user1@example.com"
    )
    user1_crud.add(claim1)
    
    # User 2 should not see user 1's claim
    user2_claims = user2_crud.list()
    assert len(user2_claims) == 0
    
    # User 1 should see their claim
    user1_claims = user1_crud.list()
    assert len(user1_claims) == 1
```

### Integration Tests

**Testing with External APIs:**

```python
@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="No API key")
def test_llm_extraction(db):
    """Test LLM extraction (requires API key)."""
    from truth_management_system import LLMHelpers, PKBConfig
    
    keys = {"OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY")}
    config = PKBConfig()
    llm = LLMHelpers(keys, config)
    
    result = llm.extract_single(
        statement="I prefer morning workouts",
        context_domain="health"
    )
    
    assert result.claim_type == "preference"
    assert "fitness" in result.tags or "workout" in result.tags
```

### Retrieval Eval Harness

**Location:** `truth_management_system/tests/eval/` (plan Workstream G, G1-task).

Measures *retrieval quality* (not just correctness) so ranking changes (recency/decay/confidence) and an ANN index can be validated against a baseline instead of eyeballed.

- `metrics.py` — `recall_at_k`, `precision_at_k`, `reciprocal_rank`, `mean_reciprocal_rank`, `aggregate_case_metrics` (pure functions over ID lists).
- `dataset.py` + `seed_dataset.json` — a persona dataset (~46 keyed claims across all 7 domains, some carrying lifecycle state: `status`, `confidence`, relative `created_at/updated_at`, past `valid_to`) plus ~38 `query → expected` cases tagged with a `category`. Categories: `lexical` (shares words — FTS wins), `semantic` (paraphrase, no shared word-prefix — needs embeddings), `multi`/`temporal` (recall several), `recency` (expect the newer — needs Workstream C), `conflict` (contradictory active claims, expect the current — needs D/H), `hard_negative` (a distractor shares strong tokens — ranking signal), `scoped` (per-case `SearchFilters` — existing capability), `lifecycle` (superseded/expired excluded — existing). Cases may also carry `not_expected` and `filters`. Keys map to auto-generated `claim_id`s at seed time. `EvalRunner.seed()` applies the lifecycle overrides and runs the expiry sweep.
- `runner.py` — `EvalRunner` seeds a throwaway PKB (its own temp SQLite, or a passed-in `db`), runs each query through `HybridSearchStrategy`, and computes per-case, aggregate, **and per-category** metrics: `recall@k`, `precision@k`, and `mrr` (`StrategyReport.by_category`). `evaluate()` scores multiple strategy configs (`fts`, and `embedding`/`hybrid` when an API key is available). CLI supports `--json` and `--verbose`; `run_eval.sh` is a portable wrapper. Full README at `truth_management_system/tests/eval/README.md`.

**Why categories matter:** the per-category breakdown is what gives *clear signal*. On the seed set, network-free FTS scores recall@5=1.0 on `lexical`/`multi`/`scoped`/`temporal` but only ~0.10 on `semantic`, with MRR 0.500 on `recency` and `conflict` and low `precision` on `hard_negative` (0.38). Those gaps are exactly what embeddings/hybrid retrieval and Workstreams C (recency) and D/H (conflict) must close — and the harness now measures each directly instead of reporting one blended number. (Workstream C is implemented: enabling `w_recency` lifts `recency`/`conflict` MRR to 1.0 — see the Recency & Confidence Re-rank section.)

**Run the bundled dataset (network-free, FTS):**
```bash
./truth_management_system/tests/eval/run_eval.sh --k 5        # portable wrapper
# python -m truth_management_system.tests.eval.runner --k 5 [--json] [--verbose]
# PKB eval report — dataset='pkb_seed_v3', claims=46, cases=38, k=5
# [fts] strategies=['fts']
#     overall       precision@5=0.537  recall@5=0.763  mrr=0.664
#     lexical       precision@5=0.730  recall@5=1.000  mrr=1.000
#     semantic      precision@5=0.050  recall@5=0.100  mrr=0.050
#     recency       precision@5=0.500  recall@5=1.000  mrr=0.500
#     conflict      precision@5=0.500  recall@5=1.000  mrr=0.500
#     ... (also: multi, temporal, scoped, lifecycle, hard_negative)
```

**Programmatic sweep (for tuning C3 / H4 weights):**
```python
from truth_management_system.tests.eval import EvalRunner, load_dataset

ds = load_dataset()
with EvalRunner(keys={"OPENROUTER_API_KEY": "..."}) as r:
    r.seed(ds)
    report = r.evaluate(ds, k=10, strategy_sets={"fts": ["fts"], "hybrid": ["fts", "embedding"]})
    print(report.format_report())
```

**Regression guard:** `tests/test_eval_harness.py` runs the FTS strategy over the seed set network-free and asserts (a) the `lexical` subset stays strong (`recall@5 ≥ 0.8`, `MRR ≥ 0.7`); (b) the lexical-vs-`semantic` recall gap stays visible (`≥ 0.4`) so the dataset can't silently regress to all-easy; (c) the existing-capability categories `scoped` (filters) and `lifecycle` (superseded/expired exclusion) keep high recall — a regression there is a real bug; plus category-coverage and precision-presence checks and metric unit tests. The room-to-grow categories (`semantic`/`recency`/`conflict`/`hard_negative`) are intentionally **not** floored. `EvalRunner(keys={})` guarantees offline FTS-only execution.

### Manual Testing Checklist

**Basic Operations:**
- [ ] Add claim via UI
- [ ] Edit claim via UI
- [ ] Delete claim via UI
- [ ] Search claims
- [ ] Filter by type/domain/status

**Memory Updates:**
- [ ] Chat turn triggers proposal modal
- [ ] Approve all → claims saved
- [ ] Approve some → only selected saved
- [ ] Cancel → no changes

**Bulk Operations:**
- [ ] Bulk Add tab: add multiple rows
- [ ] Save all → all claims created
- [ ] Import Text with AI → proposals shown
- [ ] Approve ingestion → claims saved

**Memory Attachment:**
- [ ] Pin claim globally → always included
- [ ] "Use in next message" → included once
- [ ] @memory:id reference → included with highest priority
- [ ] Conversation pin → included for that conversation

**Multi-User:**
- [ ] User A adds claim
- [ ] User B cannot see User A's claim
- [ ] User A searches → only sees own claims
- [ ] User B adds claim with same statement → no conflict

---

## Troubleshooting Guide

### Common Issues & Solutions

#### Issue: No search results

**Symptoms:**
- Search returns empty list
- Claims exist in database (verified via `api.claims.list()`)

**Diagnosis:**
```python
# Check if claims exist
claims = api.claims.list(limit=10)
print(f"Total claims: {len(claims)}")

# Check FTS index
db.execute("SELECT COUNT(*) FROM claims_fts")
print(f"FTS entries: {db.fetchone()[0]}")

# Check user_email filtering
filters = SearchFilters(user_email="user@example.com")
results = api.search("test", filters=filters)
```

**Solutions:**
1. Verify user_email matches
2. Check FTS index is populated (should happen via triggers)
3. Try FTS-only search: `strategy="fts"`
4. Check if claims are in `active` or `contested` status

#### Issue: UI works but Conversation.py doesn't retrieve memories

**Symptoms:**
- Memories visible in PKB modal
- Chat doesn't include memories in context
- No PKB-related logs in conversation

**Diagnosis:**
```python
# Check database path in Conversation.py
print(f"PKB DB path: {pkb_db_path}")
# Should be: storage/users/pkb.sqlite

# Check in endpoints/pkb.py
print(f"Endpoint DB path: {os.path.join(st.users_dir, 'pkb.sqlite')}")
# Should match the above
```

**Solution:**
Ensure both use the same path:
```python
# Conversation.py
pkb_db_path = os.path.join(os.path.dirname(__file__), "storage", "users", "pkb.sqlite")

# endpoints/pkb.py: get_pkb_db()
st = get_state()
pkb_db_path = os.path.join(st.users_dir, "pkb.sqlite")
# st.users_dir should be "storage/users"
```

#### Issue: Embedding search fails with "ambiguous truth value"

**Symptoms:**
```
ValueError: The truth value of an array with more than one element is ambiguous
```

**Cause:**
Using truthiness check on numpy array:
```python
# ❌ WRONG
if query_emb:
    ...
```

**Solution:**
Use identity comparison:
```python
# ✅ CORRECT
if query_emb is not None:
    ...
```

**Locations to check:**
- `search/embedding_search.py`
- `search/hybrid_search.py`
- Any code that checks embedding results

#### Issue: Search logs not appearing

**Symptoms:**
- FTS/embedding search happens
- No logs in server output

**Cause:**
Module logger not configured to show DEBUG level

**Solution:**
Use `time_logger` instead:
```python
# In search modules
try:
    from common import time_logger
except ImportError:
    time_logger = logger

# Use time_logger for guaranteed visibility
time_logger.info(f"[FTS] Query returned {len(rows)} rows")
```

**Enable module logging:**
```python
import logging
logging.getLogger("truth_management_system.search").setLevel(logging.DEBUG)
```

#### Issue: Contested claims showing without warning

**Symptoms:**
- Contested claims in search results
- No warning badge/indicator

**Solution:**
Check `SearchResult.is_contested` and `SearchResult.warnings`:
```python
for result in search_results:
    if result.is_contested:
        # Show warning badge
        print(f"⚠️ CONTESTED: {result.claim.statement}")
```

Frontend rendering:
```javascript
var contestedBadge = claim.status === 'contested' ?
    '<span class="badge badge-warning">Contested</span>' : '';
```

#### Issue: Pending memory attachments lost

**Symptoms:**
- User clicks "Use in next message"
- Sends message
- Attachments not included

**Diagnosis:**
```javascript
// Check pending state
console.log('Pending:', PKBManager.getPendingAttachments());

// Check sendMessage call
// Should include attached_claim_ids parameter
```

**Solution:**
Ensure `sendMessageCallback()` gets pending attachments and clears them:
```javascript
function sendMessageCallback() {
    var attached_claim_ids = [];
    if (typeof PKBManager !== 'undefined' && PKBManager.getPendingAttachments) {
        attached_claim_ids = PKBManager.getPendingAttachments();
        if (attached_claim_ids.length > 0) {
            PKBManager.clearPendingAttachments();
        }
    }
    
    // Include in sendMessage call
    ChatManager.sendMessage(..., attached_claim_ids, referenced_claim_ids);
}
```

#### Issue: Global pins not working

**Symptoms:**
- Pin button toggled
- Claim not always included in context

**Diagnosis:**
```python
# Check meta_json
claim = api.get_claim(claim_id)
print(f"meta_json: {claim.meta_json}")
# Should contain: {"pinned": true}

# Check get_pinned_claims
result = api.get_pinned_claims()
print(f"Pinned claims: {len(result.data)}")
```

**Solution:**
Ensure `_get_pkb_context()` fetches pinned claims:
```python
# 3. GLOBAL PINNED
result = api.get_pinned_claims(limit=50)
if result.success:
    for claim in result.data:
        if claim.claim_id not in seen_ids:
            all_claims.append(("global_pinned", claim))
            seen_ids.add(claim.claim_id)
```

#### Issue: Duplicate claims created

**Symptoms:**
- Same statement added multiple times
- No duplicate warning shown

**Diagnosis:**
```python
# Check if similarity checking is enabled
result = api.add_claim(
    statement="Test",
    claim_type="fact",
    context_domain="personal",
    auto_extract=True  # Should enable similarity checking
)

print(f"Warnings: {result.warnings}")
# Should show if similar claims found
```

**Solution:**
1. Use `auto_extract=True` to enable similarity checking
2. Check that LLM helpers are available (OPENROUTER_API_KEY set)
3. Review similarity threshold in `LLMHelpers.check_similarity()`

#### Issue: FTS not finding exact matches

**Symptoms:**
- Claim exists with text "morning workout"
- Search for "morning workout" returns nothing

**Diagnosis:**
```sql
-- Check FTS index
SELECT * FROM claims_fts WHERE claim_id = '<claim_id>';

-- Check FTS match
SELECT * FROM claims_fts WHERE claims_fts MATCH 'morning';
```

**Solution:**
1. Verify FTS triggers are created (in schema)
2. Manually sync FTS if needed:
```python
from truth_management_system.crud.base import sync_claim_to_fts

with db.transaction() as conn:
    sync_claim_to_fts(conn, claim_id, 'update')
```

3. Rebuild FTS index:
```sql
INSERT INTO claims_fts(claims_fts) VALUES('rebuild');
```

---

## System Integration: How PKB Works With the Rest of the Application

This section documents exactly how the PKB system connects to every other part of the application, tracing data flow across all boundaries.

### Integration Map

```
┌──────────────────────────────────────────────────────────────────────────┐
│ BROWSER (JavaScript)                                                     │
│                                                                          │
│  interface.html ─── pkb-manager.js ─┬─ AJAX calls → /pkb/* endpoints    │
│      │                               │                                    │
│      └── common-chat.js ────────────┼─ POST → /send_message/{conv_id}   │
│           │                          │       (includes attached_claim_ids,│
│           │                          │        referenced_claim_ids)       │
│           └── parseMessageForCheckBoxes.js                               │
│                (@memory:id parsing)                                       │
└─────────────────────────┬────────────────────────────────────────────────┘
                          │ HTTP
┌─────────────────────────▼────────────────────────────────────────────────┐
│ FLASK SERVER                                                             │
│                                                                          │
│  server.py ──── init_state() → AppState(pinned_claims={})               │
│      │                                                                    │
│      └── register_blueprints(app)                                        │
│           ├── endpoints/pkb.py ──── /pkb/* routes                        │
│           │    │                    │                                      │
│           │    │                    └── get_pkb_api_for_user(email, keys) │
│           │    │                         └── StructuredAPI(db, keys, cfg) │
│           │    │                                                          │
│           │    ├── _pinned_store() → AppState.pinned_claims              │
│           │    │                                                          │
│           │    └── _memory_update_plans{}, _text_ingestion_plans{}       │
│           │                                                               │
│           └── endpoints/conversations.py ── /send_message/{conv_id}      │
│                ├── Reads state.pinned_claims[conv_id]                     │
│                ├── Injects conversation_pinned_claim_ids into query       │
│                └── Calls conversation.reply(query, ...)                   │
│                                                                          │
│                    ┌──────────────────────────────────┐                   │
│                    │ Conversation.py (per conversation)│                   │
│                    │                                    │                   │
│                    │  reply():                          │                   │
│                    │   ├── Extract PKB IDs from query  │                   │
│                    │   ├── get_async_future(            │                   │
│                    │   │     _get_pkb_context, ...)     │                   │
│                    │   ├── ... other processing ...     │                   │
│                    │   ├── pkb_future.result()          │                   │
│                    │   └── Inject into system prompt    │                   │
│                    │                                    │                   │
│                    │  _get_pkb_context():               │                   │
│                    │   ├── get_pkb_database() → SQLite  │                   │
│                    │   ├── StructuredAPI(db, keys, cfg) │                   │
│                    │   ├── Fetch claims by priority     │                   │
│                    │   └── Format as text for LLM       │                   │
│                    └──────────────────────────────────┘                   │
└──────────────────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────────────┐
│ PERSISTENCE                                                              │
│                                                                          │
│  storage/users/pkb.sqlite ← Single shared file for all users            │
│   ├── claims, notes, entities, tags (with user_email column)            │
│   ├── claim_tags, claim_entities (join tables)                          │
│   ├── conflict_sets, conflict_set_members                               │
│   ├── claims_fts, notes_fts (FTS5 virtual tables)                      │
│   ├── claim_embeddings, note_embeddings (BLOB cache)                    │
│   └── schema_version                                                     │
│                                                                          │
│  External: code_common/call_llm.py → OpenRouter API (LLM & embeddings) │
└──────────────────────────────────────────────────────────────────────────┘
```

---

### A. Server Startup & Initialization

**File:** `server.py`

**What happens at startup:**

1. **State initialization** - `server.py` calls `init_state()` from `endpoints/state.py`:
   ```python
   init_state(
       folder=folder,
       users_dir=users_dir,           # "storage/users"
       pinned_claims={},              # Empty dict for conversation pins
       conversation_cache=conv_cache,
       ...
   )
   ```
   This creates a process-global `AppState` used by all endpoint modules.

2. **Blueprint registration** - `register_blueprints(app)` from `endpoints/__init__.py`:
   ```python
   from .pkb import pkb_bp
   app.register_blueprint(pkb_bp)   # Registers all /pkb/* routes
   ```

3. **PKB database is NOT initialized at startup** - it's lazy-loaded on first request. When the first `/pkb/*` endpoint is called, `get_pkb_db()` creates the database:
   ```python
   # endpoints/pkb.py
   def get_pkb_db():
       global _pkb_db, _pkb_config
       if _pkb_db is None:
           st = get_state()
           pkb_db_path = os.path.join(st.users_dir, "pkb.sqlite")
           _pkb_config = PKBConfig(db_path=pkb_db_path)
           _pkb_db = get_database(_pkb_config)  # Also runs migrations
       return _pkb_db, _pkb_config
   ```

**Key Files:**
| File | PKB Role |
|------|----------|
| `server.py` | Creates `AppState`, registers blueprints |
| `endpoints/__init__.py` | `register_blueprints()` registers `pkb_bp` |
| `endpoints/state.py` | `AppState` dataclass with `pinned_claims` field |

---

### B. Authentication & User Scoping Chain

**How user identity flows through the system:**

```
Flask session (set at login)
    ↓ session["email"], session["name"]
endpoints/auth.py: @login_required decorator
    ↓ Ensures session has email + name
endpoints/session_utils.py: get_session_identity()
    ↓ Returns (email, name, loggedin) tuple
endpoints/pkb.py: Each endpoint extracts email
    ↓ email = get_session_identity()[0]
get_pkb_api_for_user(email, keys)
    ↓ Creates StructuredAPI(db, keys, config, user_email=email)
StructuredAPI
    ↓ All CRUD/search scoped to user_email
ClaimCRUD, SearchFilters, etc.
    └── SQL: ... AND user_email = ?
```

**Authentication:** All PKB endpoints use `@login_required`:
```python
@pkb_bp.route('/pkb/claims', methods=['GET'])
@login_required
@limiter.limit("30 per minute")
def handle_list_claims():
    email = get_session_identity()[0]
    api = get_pkb_api_for_user(email, keyParser.get_api_keys())
    ...
```

**Rate Limits by Endpoint Group:**
| Endpoint Group | Rate Limit |
|----------------|------------|
| Claims CRUD | 15-30 per minute |
| Search | 20 per minute |
| Bulk operations | 10-15 per minute |
| Text ingestion | 5-10 per minute |
| Context retrieval | 60 per minute |
| Pinning operations | 30 per minute |

**API Keys:** `keyParser.get_api_keys()` provides keys (including `OPENROUTER_API_KEY`) to LLM-dependent features (auto_extract, embedding search, text ingestion).

---

### C. Conversation.py Integration (Deep Detail)

**File:** `Conversation.py`  
**Location:** Lines 240-400 (`_get_pkb_context`), Lines 4620-4750 (reply integration)

**How PKB context gets into the LLM prompt:**

**Step 1: Extract attachment IDs from request** (in `reply()`, ~line 4645)
```python
attached_claim_ids = query.get("attached_claim_ids", [])
conversation_pinned_claim_ids = query.get("conversation_pinned_claim_ids", [])
referenced_claim_ids = query.get("referenced_claim_ids", [])
```

**Step 2: Launch async PKB retrieval** (in `reply()`, ~line 4669)
```python
if PKB_AVAILABLE and user_email:
    pkb_context_future = get_async_future(
        self._get_pkb_context,
        user_email,
        query["messageText"],
        self.running_summary,     # Conversation summary for better search
        k=10,
        attached_claim_ids=attached_claim_ids,
        conversation_id=self.conversation_id,
        conversation_pinned_claim_ids=conversation_pinned_claim_ids,
        referenced_claim_ids=referenced_claim_ids,
    )
```

**Step 3: Continue other processing in parallel**

While PKB retrieval runs, `reply()` continues with:
- Building memory context
- Preparing system prompt
- Processing attachments/links/search options

**Step 4: Wait for PKB result** (~line 5398)
```python
pkb_context = pkb_context_future.result(timeout=5.0)
```

**Step 5: Format into system prompt** (~line 5468)

The PKB context is wrapped in a formatted section and injected into the user information:
```python
if pkb_context:
    user_info += f"\n\nRelevant user facts:\n{pkb_context}"
```

**Inside `_get_pkb_context()`:**

Creates its OWN `StructuredAPI` instance (separate from the endpoint-layer API):
```python
db, config = get_pkb_database()   # Gets PKB database (must match endpoints/pkb.py path)
api = StructuredAPI(db, self.get_api_keys(), config, user_email=user_email)
```

Then retrieves claims in priority order:

| Step | Source | Priority | Method |
|------|--------|----------|--------|
| 1 | Referenced (`@memory:id`) | Highest | `api.get_claims_by_ids(referenced_claim_ids)` |
| 2 | Attached ("Use Now") | High | `api.get_claims_by_ids(attached_claim_ids)` |
| 3 | Global Pinned | Medium-High | `api.get_pinned_claims(limit=20)` |
| 4 | Conversation Pinned | Medium | `api.get_claims_by_ids(conversation_pinned_claim_ids)` |
| 5 | Auto Search | Normal | `api.search(query, strategy='hybrid', k=remaining)` |

**Search Enhancement:** The auto-search query is enriched with conversation summary:
```python
search_query = query
if conversation_summary:
    # Cap summary to prevent overwhelming the search
    capped_summary = conversation_summary[:4000]
    search_query = f"{query}\n\nContext: {capped_summary}"
```

**Deduplication:** Claims seen in earlier (higher priority) steps are skipped:
```python
for claim in result.data:
    if claim and claim.claim_id not in seen_ids:
        all_claims.append((source, claim))
        seen_ids.add(claim.claim_id)
```

**Output Format:**
```
[REFERENCED] [preference] I prefer morning meetings
[ATTACHED] [fact] My team uses Python
[GLOBAL PINNED] [fact] My timezone is IST
[CONV PINNED] [decision] Using microservices for project X
[AUTO] [preference] I like detailed explanations
[AUTO] [fact] I work in tech
```

**CRITICAL:** `Conversation.py` creates its own `PKBDatabase` instance via `get_pkb_database()`. This MUST use the same file path as `endpoints/pkb.py`'s `get_pkb_db()`. Both should resolve to `storage/users/pkb.sqlite`.

---

### D. Frontend → Backend → PKB Flow (Send Message)

**Complete trace of a message with PKB attachments:**

**Step 1: User composes message (Browser)**

```
User:
  1. Opens PKB modal, clicks "Use in next message" on claim
     → PKBManager.addToNextMessage(claimId)
     → Adds to pendingMemoryAttachments[] (JS state)
     → Shows chip indicator near chat input
  
  2. Types message: "Considering @memory:abc123 what should I do?"
  
  3. Clicks Send
```

**Step 2: sendMessageCallback() (common-chat.js, ~line 2745)**

```javascript
// 1. Collect pending PKB attachments
var attached_claim_ids = [];
if (typeof PKBManager !== 'undefined' && PKBManager.getPendingAttachments) {
    attached_claim_ids = PKBManager.getPendingAttachments();
    if (attached_claim_ids.length > 0) {
        PKBManager.clearPendingAttachments();  // Clear after getting
    }
}

// 2. Parse @memory references from message text
var referenced_claim_ids = [];
if (typeof parseMemoryReferences === 'function') {
    var memoryRefs = parseMemoryReferences(messageText);
    referenced_claim_ids = memoryRefs.claimIds;
    // NOTE: Original message text (with @memory: refs) is still sent
}

// 3. Send message with all IDs
ChatManager.sendMessage(
    conversationId, messageText, checkboxes, links, search,
    attached_claim_ids,      // From "Use Now" button
    referenced_claim_ids     // From @memory:id parsing
);
```

**Step 3: ChatManager.sendMessage() (common-chat.js, ~line 2579)**

```javascript
var requestBody = {
    'messageText': messageText,
    'checkboxes': checkboxes,
    'links': links,
    'search': search
};

// Include PKB IDs if present
if (attached_claim_ids && attached_claim_ids.length > 0) {
    requestBody['attached_claim_ids'] = attached_claim_ids;
}
if (referenced_claim_ids && referenced_claim_ids.length > 0) {
    requestBody['referenced_claim_ids'] = referenced_claim_ids;
}

// POST /send_message/{conversationId}
return fetch('/send_message/' + conversationId, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(requestBody)
});
```

**Step 4: /send_message endpoint (endpoints/conversations.py, ~line 1281)**

```python
@conversations_bp.route('/send_message/<conversation_id>', methods=['POST'])
@login_required
def send_message(conversation_id):
    query = request.get_json()
    
    # SERVER-SIDE INJECTION: Add conversation-pinned claim IDs
    # These come from AppState, NOT from the frontend
    conv_pinned_ids = list(get_state().pinned_claims.get(conversation_id, set()))
    if conv_pinned_ids:
        query["conversation_pinned_claim_ids"] = conv_pinned_ids
    
    # Pass to conversation
    conversation = get_conversation(conversation_id)
    response = conversation.reply(query, userData=...)
```

**Key insight:** `conversation_pinned_claim_ids` are NEVER sent from the frontend. They are injected server-side from `AppState.pinned_claims`, which is an in-memory dict managed by `/pkb/conversation/<id>/pin` endpoints.

**Step 5: Conversation.reply() → _get_pkb_context() (see Section C above)**

**Step 6: Post-response memory update check (common-chat.js, ~line 2879)**

```javascript
// After response completes (3 second delay to avoid interrupting streaming)
setTimeout(function() {
    if (typeof PKBManager !== 'undefined' && PKBManager.checkMemoryUpdates) {
        var conversationSummary = ConversationManager.currentConversationSummary || '';
        PKBManager.checkMemoryUpdates(conversationSummary, messageText, '');
    }
}, 3000);
```

This triggers the memory proposal flow:
1. `POST /pkb/propose_updates` → `ConversationDistiller.extract_and_propose()`
2. If proposals found → Show memory proposal modal
3. User approves → `POST /pkb/execute_updates` → Claims saved

---

### E. PKB Endpoint Architecture (endpoints/pkb.py)

**Blueprint:** `pkb_bp = Blueprint("pkb", __name__)`

**Module-Level State:**
```python
_pkb_db = None               # Shared PKBDatabase (lazy-initialized)
_pkb_config = None            # PKBConfig
_memory_update_plans = {}     # plan_id → MemoryUpdatePlan (temp storage)
_text_ingestion_plans = {}    # plan_id → TextIngestionPlan (temp storage)
```

**Plan Storage Pattern:**

When `/pkb/propose_updates` or `/pkb/ingest_text` is called, the resulting plan is stored in the module-level dict with a UUID key. The frontend receives the `plan_id` and sends it back when executing:

```python
# On propose:
plan_id = str(uuid.uuid4())
_memory_update_plans[plan_id] = plan
return jsonify({'plan_id': plan_id, 'proposed_actions': [...]})

# On execute:
plan = _memory_update_plans.get(plan_id)
if not plan:
    return json_error("Plan not found or expired", 404)
```

**WARNING:** Plans are stored in-memory and lost on server restart. This is acceptable for v0 but should be persisted in a future version.

**Conversation Pinning State:**

Stored in `AppState.pinned_claims` (accessed via `_pinned_store()`):
```python
def _pinned_store() -> dict[str, set]:
    st = get_state()
    if st.pinned_claims is None:
        st.pinned_claims = {}
    return st.pinned_claims
```

This is also in-memory only, lost on server restart. This is by design for v0 (ephemeral conversation-level context).

---

### F. Shared State & Lifecycle

| State | Storage | Lifetime | Used By | Purpose |
|-------|---------|----------|---------|---------|
| `_pkb_db` | Module global in `endpoints/pkb.py` | Process lifetime | All PKB endpoints | Shared DB connection |
| `_pkb_config` | Module global in `endpoints/pkb.py` | Process lifetime | All PKB endpoints | PKB configuration |
| `AppState.pinned_claims` | In-memory dict | Process lifetime | `endpoints/pkb.py`, `endpoints/conversations.py` | Conversation-level pins |
| `_memory_update_plans` | Module global dict | Process lifetime | `/pkb/propose_updates`, `/pkb/execute_updates` | Temp plan storage |
| `_text_ingestion_plans` | Module global dict | Process lifetime | `/pkb/ingest_text`, `/pkb/execute_ingest` | Temp plan storage |
| `pendingMemoryAttachments` | JS variable in `PKBManager` | Page session | `common-chat.js`, UI | "Use Now" queue |
| `pendingMemoryDetails` | JS variable in `PKBManager` | Page session | UI chip display | Claim display info |
| `session["email"]` | Flask session | Login session | All endpoints | User identity |

**State Relationships:**
```
AppState (server.py creates at startup)
    ├── pinned_claims: dict[str, set]  ← endpoints/pkb.py writes
    │                                   ← endpoints/conversations.py reads
    └── users_dir: str                 ← endpoints/pkb.py uses for DB path

_memory_update_plans (endpoints/pkb.py module)
    ← /pkb/propose_updates writes     ← /pkb/execute_updates reads

PKBManager (pkb-manager.js browser)
    ├── pendingMemoryAttachments[]     ← "Use Now" button writes
    │                                   ← sendMessageCallback() reads + clears
    └── currentPlanId, currentProposals ← Memory proposal modal state
```

---

### G. Error Handling & Graceful Degradation

**PKB Unavailability:**

If `truth_management_system` is not installed:
```python
# endpoints/pkb.py
try:
    from truth_management_system import ...
    PKB_AVAILABLE = True
except ImportError:
    PKB_AVAILABLE = False

# Every endpoint checks:
if not PKB_AVAILABLE:
    return json_error("PKB feature is not available", 503)
```

```python
# Conversation.py
if not PKB_AVAILABLE:
    return ""  # Empty context, conversation works without PKB
```

**Frontend checks:**
```javascript
// common-chat.js
if (typeof PKBManager !== 'undefined' && PKBManager.getPendingAttachments) {
    attached_claim_ids = PKBManager.getPendingAttachments();
}
// If PKBManager not loaded, attached_claim_ids stays empty - no error

if (typeof parseMemoryReferences === 'function') {
    var memoryRefs = parseMemoryReferences(messageText);
}
// If function not available, @memory refs are ignored - no error
```

**Principle:** The PKB system is entirely optional. If it's unavailable, disabled, or errors out:
- Chat works normally without memory context
- UI buttons are hidden or gracefully disabled
- No crashes or blocked operations

---

### H. TextOrchestrator Integration (Natural Language Commands)

**File:** `truth_management_system/interface/text_orchestration.py`

**Purpose:** Parse natural language commands and route to PKB operations

**Currently NOT exposed via REST endpoint** but available as a Python API:

```python
orchestrator = TextOrchestrator(api, keys, config)

# Parse and execute
result = orchestrator.process("remember that I prefer morning meetings")
# → Calls api.add_claim(statement="I prefer morning meetings", ...)

result = orchestrator.process("find what I know about Python")
# → Calls api.search("Python", ...)

result = orchestrator.process("delete the reminder about dentist")
# → Calls api.delete_claim(claim_id=...) (after search + confirmation)
```

**Intent Detection:** Uses LLM to classify intent, with rule-based fallback:

| Keywords | Intent | Action |
|----------|--------|--------|
| "remember", "add", "save" | `add_claim` | Create new claim |
| "find", "search", "what" | `search` | Search claims |
| "update", "change", "edit" | `edit_claim` | Update existing |
| "delete", "remove", "forget" | `delete_claim` | Soft-delete |
| "conflicts", "contradictions" | `list_conflicts` | Show conflicts |

**Future Integration:** Could be exposed as a `/pkb/command` endpoint for a chat-based PKB interface.

---

### I. External Dependencies

**code_common/call_llm.py:**

The PKB's LLM features depend on the shared `call_llm` module:

```python
# Used by llm_helpers.py, conversation_distillation.py, text_orchestration.py, 
# text_ingestion.py, rewrite_search.py, mapreduce_search.py

from code_common.call_llm import call_llm, get_embedding, get_query_embedding

# LLM call pattern:
response = call_llm(keys, model, prompt, temperature=0.0)

# Embedding pattern:
embedding = get_embedding(text, model="openai/text-embedding-3-small")
query_emb = get_query_embedding(query, model="openai/text-embedding-3-small")
```

**External API Dependency:** OpenRouter API (via `OPENROUTER_API_KEY`)

| Feature | Requires API | Fallback |
|---------|-------------|----------|
| Auto-extract (tags/entities) | Yes | Manual entry |
| Embedding search | Yes | FTS-only search |
| Text ingestion (LLM parsing) | Yes | Rule-based line splitting |
| Memory proposals (distillation) | Yes | No proposals shown |
| Search rewrite | Yes | Direct FTS query |
| MapReduce scoring | Yes | Skip strategy |

---

## Files Modified Summary

**All Files That Touch PKB:**

| File | Role | Key Functions |
|------|------|---------------|
| `server.py` | App startup, state init | `init_state(pinned_claims={})` |
| `endpoints/__init__.py` | Blueprint registration | `register_blueprints()` → `pkb_bp` |
| `endpoints/state.py` | Shared state | `AppState.pinned_claims`, `get_state()` |
| `endpoints/pkb.py` | REST API (all `/pkb/*`) | All PKB endpoints, serialization, plan storage |
| `endpoints/conversations.py` | Message sending | Injects `conversation_pinned_claim_ids` |
| `endpoints/auth.py` | Authentication | `@login_required` decorator |
| `endpoints/session_utils.py` | User identity | `get_session_identity()` → email |
| `Conversation.py` | LLM chat integration | `_get_pkb_context()`, `reply()` |
| `interface/interface.html` | UI modals | PKB modal, proposal modal, pending indicator |
| `interface/pkb-manager.js` | Frontend API | All AJAX calls, UI rendering, state |
| `interface/common-chat.js` | Message sending | Collects PKB IDs, triggers proposals |
| `interface/parseMessageForCheckBoxes.js` | @memory parsing | `parseMemoryReferences()` |
| `truth_management_system/` | Core PKB package | All business logic |
| `code_common/call_llm.py` | LLM utilities | `call_llm()`, `get_embedding()` |

**Integration Points:**
1. **Browser → Server:** jQuery AJAX from `pkb-manager.js` → `/pkb/*` endpoints
2. **Browser → Server:** Fetch from `common-chat.js` → `/send_message/{id}` with PKB IDs
3. **Server Injection:** `endpoints/conversations.py` injects `conversation_pinned_claim_ids` from `AppState`
4. **Server → PKB Package:** `endpoints/pkb.py` → `StructuredAPI` → CRUD/Search layers
5. **Conversation → PKB:** `Conversation.py` → `_get_pkb_context()` → own `StructuredAPI` instance
6. **PKB → External:** `llm_helpers.py` → `code_common/call_llm.py` → OpenRouter API

---

## Next Steps for Development

1. **Add Provenance Tracking:** Track where each claim came from (chat, manual, import)
2. **Improve Conflict Detection:** Automatic contradiction detection during add
3. **Enhanced Entity Resolution:** Better entity deduplication and merging
4. **Tag Hierarchy UI:** Visual tag tree browser in modal
5. **Export/Import:** JSON export of all user data
6. **Analytics:** Usage statistics, most-used claims, etc.
7. **Scheduled Review:** Periodic review of old/stale claims
8. **Permission System:** Share claims between users (requires schema update)
9. **Versioning:** Track claim edits over time
10. **LLM Prompt Engineering:** Improve extraction accuracy
11. **Persist Plan Storage:** Move `_memory_update_plans` from in-memory to database
12. **TextOrchestrator Endpoint:** Expose natural language command interface via REST
13. **Conversation Pin Persistence:** Optionally persist conversation pins to database
14. **Search within entity/tag views:** Add search bar in expanded entity/tag claim lists
15. **Pagination for expanded views:** Add "show more" for entities/tags with many claims
16. **Bulk context assignment:** Assign multiple claims to a context at once
17. **Delete custom types/domains:** UI and endpoint to remove user-created types/domains

---

## Short-Term Cross-Conversation Memory (v12)

A separate memory layer between within-conversation memory and permanent claims:

- **Table:** `pkb_short_term_memory` with TTL-based auto-expiry (session/day/week)
- **Extraction:** `_extract_short_term_memories()` in `conversation_distillation.py` — separate LLM call, includes existing STM for dedup
- **Storage:** Silent (no user approval); reinforcement detection via `SequenceMatcher` against existing STM from different conversations
- **Injection:** In `Conversation._get_pkb_context()` — `<stm_context>` block prepended to PKB claims, word-budgeted
- **Promotion:** Auto at `reinforcement_count >= 3` AND `importance = "high"`; manual via `POST /pkb/stm/<id>/promote`
- **Recency:** `_claim_age_days()` now uses `max(last_reinforced_at, last_accessed_at, updated_at)` — claims accessed for context are treated as fresher
- **Compaction:** `run_memory_cleanup()` expires STM + identifies/archives stale long-term claims (>90d inactive, confidence < 0.5, not pinned)

Full details: `short_term_memory.md`

---

## PKB UX Improvements (v1.0)

Comprehensive set of 21 improvements across capture, organization, retrieval, interaction, maintenance, and transparency. All capabilities are independently usable via REST API, LLM Tool Calling, and MCP (for external AI editors like Claude Code, Cursor, ChatGPT).

### Design Principle

The PKB module works as a **universal memory backend** for any AI assistant. Every new capability is exposed on 3 surfaces:
1. **REST API** — standard HTTP endpoints in `endpoints/pkb.py`
2. **LLM Tool Calling** — `@register_tool(category="pkb")` in `code_common/tools.py`
3. **MCP** — `@mcp.tool()` in `mcp_server/pkb.py` (baseline + full tiers)

### MCP Tool Tier System

- **Baseline** = operations external AI needs in normal conversation (feedback, STM, summarize, reinforce, extract)
- **Full** = administrative/maintenance operations (stats, fading, clusters, bulk, demote)

### Batch 0 — API Parity Foundation

Registered existing STM and extraction operations as MCP + LLM tools:
- `pkb_get_stm`, `pkb_promote_stm`, `pkb_dismiss_stm` (baseline tier)
- `pkb_propose_extraction` (baseline tier)
- `pkb_recent_promotions`, `pkb_demote_claim` (full tier)

### Batch 1 — Capture & Visibility

1. **STM Capture Toast**: Added `stm_stored`/`stm_reinforced` counts to `propose_updates` response; frontend shows info toast.
2. **STM in Audit Details**: `<stm_context>` XML parsing in `_format_pkb_audit_details`; items get `source='stm'`, type 'STM' badge.
3. **STM Promotion Visibility**: "Recently Promoted" collapsible section in PKB modal (Maintenance tab) with demote buttons.
4. **Undo Cleanup Actions**: "Recently Archived" section with one-click restore.
5. **Import Button**: Visible "Import" button in settings bar opens PKB modal directly to Import tab.
6. **Save to Memory Extraction**: "Save to Memory" context menu rewired to call `propose_updates` with `extraction_mode='aggressive'` (multi-claim LLM extraction) instead of single manual add.

### Batch 2 — Organization & Retrieval

7. **Dedup at Proposal**: `_propose_actions` passes related claim (0.7-0.9 similarity match) as `existing_claim` on 'add' actions. Frontend shows yellow "⚠️ Similar existing" warning.
8. **Why-Tooltip on Proposals**: Added `reason` field to `CandidateClaim` dataclass. Both extraction prompts ask LLM for a brief source quote (max 15 words). Displayed inline next to action badges.
9. **Retrieval Scoping**: Text input `#settings-pkb-scope` in chat settings (comma-separated domain names). Passed through `_get_pkb_context` → `api.search(filters={context_domains: [...]})`.
10. **Fading Memories Section**: `GET /pkb/claims/fading` + `POST /pkb/claims/<id>/reinforce`; MCP/LLM tools; warning-bordered card in Maintenance tab with reinforce buttons.
11. **Proactive Cleanup Nudge**: On PKB modal open, checks `GET /pkb/notifications` and shows red badge on Maintenance tab.
12. **NL Search Rich Results**: NL agent `_tool_search` returns enriched fields: `friendly_id`, `confidence`, `tags`, `created_at`, `reinforcement_count`.

### Batch 3 — Intelligence & Maintenance

13. **PKB Summarize Command**: `summarize_knowledge` action in NL agent dispatch. Uses `overview_manager.get_key_areas_snippet()` with tag-list fallback. MCP tool `pkb_summarize` (baseline), LLM tool.
14. **Negative Feedback Retrieval**: New `claim_feedback` table in schema. `add_claim_feedback()`, `get_claim_feedback()`, `get_negative_claim_ids()` methods. Search applies 50% score penalty to claims with negative feedback. REST + MCP + LLM tool.
15. **Health Dashboard**: `get_health_stats()` — aggregate SQL counts by status, type, domain. `GET /pkb/health`. MCP tool (full tier). Frontend: health summary bar at top of Maintenance tab.
16. **Dedup Highlight Matching**: `highlightDiff(newText, oldText)` utility — word-level diff wrapping unique words in `<mark>` tags. Applied to existing-statement displays in proposal cards.

### Batch 4 — Bulk & Clustering

17. **Bulk Organization**: Checkboxes on claim cards + floating action bar (Archive/Tag/Group/Clear). `POST /pkb/claims/bulk` endpoint.
18. **Create Context from Selection**: "Group" button in bulk bar prompts for context name, calls `POST /pkb/contexts` with selected `claim_ids`.
19. **Auto-Clustering Suggestions**: `GET /pkb/claims/clusters` at threshold 0.75 (lower than dedup). MCP tool `pkb_auto_clusters` (full tier). "Suggested Clusters" info-card in Maintenance tab.

### Schema Changes

```sql
CREATE TABLE IF NOT EXISTS claim_feedback (
    feedback_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    user_email TEXT,
    feedback_type TEXT NOT NULL DEFAULT 'negative',
    context TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (claim_id) REFERENCES claims(claim_id)
);
```

### Files Modified

| File | Changes |
|------|---------|
| `Conversation.py` | STM audit parsing, retrieval scoping (`pkb_scope` param) |
| `code_common/tools.py` | 10 new LLM tools (PKB category) |
| `endpoints/pkb.py` | 8 new REST endpoints |
| `interface/chat.js` | `pkb_scope` settings collection + restoration |
| `interface/common.js` | Save-to-Memory rewire |
| `interface/interface.html` | Bulk action bar, health dashboard, fading/clusters/archived sections, scope input, import button |
| `interface/pkb-manager.js` | loadFadingClaims, loadClusters, loadRecentlyArchived, highlightDiff, bulk handlers, reinforce handler, proposeFromText, notification badge |
| `mcp_server/pkb.py` | 12 new MCP tools (6 baseline + 6 full tier) |
| `truth_management_system/interface/conversation_distillation.py` | `reason` field in CandidateClaim, dedup match passing |
| `truth_management_system/interface/nl_agent.py` | `summarize_knowledge` action, enriched search results, indentation fixes |
| `truth_management_system/interface/structured_api.py` | `get_health_stats()`, feedback methods, negative feedback penalty in search, archived/restore |
| `truth_management_system/schema.py` | `claim_feedback` table |

---

**End of Implementation Deep Dive**
