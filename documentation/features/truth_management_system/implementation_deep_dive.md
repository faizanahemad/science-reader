# Truth Management System (PKB v0) - Implementation Deep Dive

**Document Purpose:** Comprehensive technical documentation for developers working on or integrating with the Truth Management System. Includes architecture, data flows, file responsibilities, and integration patterns.

**Last Updated:** 2026-02-07  
**Current Version:** v0.6

> **Note:** The core sections below (Architecture through Troubleshooting) were written for v0.4.1 and remain accurate for foundational concepts. The **[v0.5+ Addendum](#v05-addendum)** section documents v0.5.0 and v0.5.1 features. The **[v0.6 Addendum](#v06-addendum)** section documents the latest features: claim_number, possible_questions (QnA), unified search+filter endpoint, search+filter unification in UI, and context search panel.

---

## Table of Contents

0a. [v0.6 Addendum](#v06-addendum) — **Latest: claim numbers, QnA, unified search**
0b. [v0.5+ Addendum](#v05-addendum) — Friendly IDs, contexts, autocomplete
1. [Architecture Overview](#architecture-overview)
2. [Module Structure & Responsibilities](#module-structure--responsibilities)
3. [Data Flow Patterns](#data-flow-patterns)
4. [Integration Patterns](#integration-patterns)
5. [API Surface](#api-surface)
6. [Frontend Architecture](#frontend-architecture)
7. [Multi-User Implementation](#multi-user-implementation)
8. [Memory Attachment System](#memory-attachment-system)
9. [Search Architecture](#search-architecture)
10. [Common Development Patterns](#common-development-patterns)
11. [Testing Strategy](#testing-strategy)
12. [Troubleshooting Guide](#troubleshooting-guide)

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

**Pattern:** Entity, tag, and context cards are rendered as Bootstrap cards with collapsible bodies. On first expand, claims are lazy-loaded via AJAX and cached. All expanded claim lists use `renderClaimCard()` + `bindClaimCardActions()` for consistent Pin/Use/Edit/Delete controls.

| View | Data Source | Cache Variable | Extra Controls |
|------|-------------|---------------|----------------|
| Entity | `GET /pkb/entities/<id>/claims` | `_entityClaimsCache` | "Add Memory" button (auto-links new claim) |
| Tag | `GET /pkb/tags/<id>/claims` | `_tagClaimsCache` | — |
| Context | `GET /pkb/contexts/<id>` | `_contextClaimsCache` | "Attach Memory" (prompt), "Remove from Context" per claim |

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
Optional: LLM rerank top 50 → final top 10
    ↓
Return List[SearchResult] → JSON → UI renders claim cards
```

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

**PKB Modal** (lines 539-823):
```html
<div class="modal" id="pkb-modal">
  <div class="modal-body">
    <ul class="nav nav-tabs">
      <li><a href="#pkb-claims-pane">Claims</a></li>
      <li><a href="#pkb-entities-pane">Entities</a></li>
      <li><a href="#pkb-tags-pane">Tags</a></li>
      <li><a href="#pkb-conflicts-pane">Conflicts</a></li>
      <li><a href="#pkb-bulk-pane">Bulk Add</a></li>
      <li><a href="#pkb-import-pane">Import Text</a></li>
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

**Memory Proposal Modal** (lines 888-950):
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

**End of Implementation Deep Dive**
