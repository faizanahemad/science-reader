# PKB v0 Implementation Guide

Technical documentation for the Personal Knowledge Base (PKB) module implementation.

## Overview

PKB v0 is a SQLite-backed personal knowledge base designed for integration with LLM chatbot applications. It provides structured storage for claims (atomic memory units), notes, entities, and tags with full-text search and embedding-based semantic search capabilities.

**Key Features (v0.4):**
- **Multi-user support**: Shared database with per-user data isolation via `user_email`
- **Flask REST API**: Full CRUD endpoints at `/pkb/*` for web integration
- **Conversation.py integration**: Async PKB context retrieval for LLM prompts
- **Frontend module**: `pkb-manager.js` for UI operations
- **Memory update workflow**: Propose → Approve → Execute pattern for chat distillation
- **Schema migration**: Automatic v1→v2 upgrade for existing databases
- **Legacy data migration**: Script to import from `UserDetails` table
- **Bulk operations**: Batch claim addition and text ingestion with AI analysis
- **Deliberate memory attachment**: Global pinning, conversation pinning, "Use Now", and @memory references

## File Tree Structure

```
truth_management_system/
├── __init__.py              # Package entry point with all exports
├── constants.py             # Enums: ClaimType, ClaimStatus, EntityType, etc.
├── config.py                # PKBConfig dataclass and load/save functions
├── utils.py                 # UUID generation, timestamps, JSON helpers, ParallelExecutor
├── models.py                # Dataclasses: Claim, Note, Entity, Tag, ConflictSet (all with user_email)
├── schema.py                # SQLite DDL v2 with user_email columns and indexes
├── database.py              # PKBDatabase connection manager with schema migration
├── llm_helpers.py           # LLM-powered extraction (tags, entities, SPO, similarity)
├── migrate_user_details.py  # Migration script: UserDetails → PKB claims
│
├── crud/                    # Data access layer (all support user_email filtering)
│   ├── __init__.py          # CRUD exports
│   ├── base.py              # BaseCRUD with user_email filtering helpers
│   ├── claims.py            # ClaimCRUD: add, edit, delete, get_by_entity/tag
│   ├── notes.py             # NoteCRUD: add, edit, delete, list
│   ├── entities.py          # EntityCRUD: add, edit, delete, get_or_create
│   ├── tags.py              # TagCRUD: add, edit, delete, hierarchy operations
│   ├── conflicts.py         # ConflictCRUD: create, resolve, ignore
│   └── links.py             # Join table operations (claim_tags, claim_entities)
│
├── search/                  # Search strategies (all support user_email)
│   ├── __init__.py          # Search exports
│   ├── base.py              # SearchStrategy ABC, SearchFilters (with user_email)
│   ├── fts_search.py        # FTSSearchStrategy: BM25 via SQLite FTS5
│   ├── embedding_search.py  # EmbeddingSearchStrategy + EmbeddingStore
│   ├── rewrite_search.py    # RewriteSearchStrategy: LLM rewrites query → FTS
│   ├── mapreduce_search.py  # MapReduceSearchStrategy: LLM scores candidates
│   ├── hybrid_search.py     # HybridSearchStrategy: parallel + RRF + optional rerank
│   └── notes_search.py      # NotesSearchStrategy: FTS + embedding for notes
│
├── interface/               # High-level API layer
│   ├── __init__.py          # Interface exports
│   ├── structured_api.py    # StructuredAPI: unified CRUD + search + for_user() + add_claims_bulk()
│   ├── text_orchestration.py    # TextOrchestrator: NL command parsing
│   ├── conversation_distillation.py  # ConversationDistiller: extract facts from chat
│   └── text_ingestion.py    # TextIngestionDistiller: bulk text parsing + AI analysis
│
└── tests/                   # Unit tests
    ├── __init__.py
    ├── test_crud.py         # CRUD operation tests
    ├── test_search.py       # Search strategy tests
    └── test_interface.py    # Interface layer tests

# Related files outside the package:
# server.py                  # Flask endpoints: /pkb/claims, /pkb/search, etc.
# Conversation.py            # LLM chat with _get_pkb_context() integration
# interface/pkb-manager.js   # Frontend JavaScript PKB API
# interface/interface.html   # PKB modal (with Bulk Add/Import Text tabs), memory proposal modal
# interface/common-chat.js   # Chat with memory update integration
```

---

## Dependency Graph

### Core Dependencies

```
code_common/call_llm.py     # External: LLM calls, embeddings, keywords
        │
        v
┌─────────────────────────────────────────────────────────────────────┐
│                         truth_management_system                      │
└─────────────────────────────────────────────────────────────────────┘
        │
        ├── constants.py ─────────────────────────────────────────────┐
        │                                                              │
        ├── utils.py                                                   │
        │    ├── generate_uuid()                                       │
        │    ├── now_iso(), epoch_iso()                                │
        │    └── ParallelExecutor                                      │
        │                                                              │
        ├── config.py ────────────────────────────────────────────────┤
        │    ├── PKBConfig                                             │
        │    └── load_config(), save_config()                          │
        │                                                              │
        ├── models.py ◄───── depends on: utils, constants              │
        │    ├── Claim, Note, Entity, Tag                              │
        │    └── ConflictSet, ClaimTag, ClaimEntity                    │
        │                                                              │
        ├── schema.py                                                  │
        │    └── SQL DDL strings + get_all_ddl()                       │
        │                                                              │
        ├── database.py ◄─── depends on: config, schema, utils         │
        │    └── PKBDatabase                                           │
        │                                                              │
        ├── llm_helpers.py ◄── depends on: config, models, constants   │
        │    └── LLMHelpers                 + code_common/call_llm     │
        │                                                              │
        ├── crud/ ◄────────── depends on: database, models, utils      │
        │    ├── BaseCRUD (abstract)                                   │
        │    ├── ClaimCRUD, NoteCRUD, EntityCRUD, TagCRUD              │
        │    └── ConflictCRUD, link functions                          │
        │                                                              │
        ├── search/ ◄──────── depends on: database, config, models,    │
        │    │                           crud, llm_helpers, utils      │
        │    ├── SearchStrategy (ABC)                                  │
        │    ├── FTS/Embedding/Rewrite/MapReduce strategies            │
        │    └── HybridSearchStrategy (combines all)                   │
        │                                                              │
        └── interface/ ◄───── depends on: everything above             │
             ├── StructuredAPI (+ add_claims_bulk)                     │
             ├── TextOrchestrator                                      │
             ├── ConversationDistiller                                 │
             └── TextIngestionDistiller                                │
```

---

## Module Details

### 1. `constants.py`

Defines all enums and allowed values used throughout the system.

| Enum | Values | Purpose |
|------|--------|---------|
| `ClaimType` | fact, memory, decision, preference, task, reminder, habit, observation | Classify claim nature |
| `ClaimStatus` | active, contested, historical, superseded, retracted, draft | Lifecycle state |
| `EntityType` | person, org, place, topic, project, system, other | Entity classification |
| `EntityRole` | subject, object, mentioned, about_person | Role in claim |
| `ConflictStatus` | open, resolved, ignored | Conflict state |
| `ContextDomain` | personal, health, relationships, learning, life_ops, work, finance | Life domains |
| `MetaJsonKeys` | keywords, source, visibility, llm | Standard metadata keys |

---

### 2. `config.py`

Configuration management with layered loading (defaults → env → file → dict).

**`PKBConfig` Dataclass Fields:**
```python
db_path: str = "~/.pkb/kb.sqlite"
fts_enabled: bool = True
embedding_enabled: bool = True
default_k: int = 20
include_contested_by_default: bool = True
validity_filter_default: bool = False
llm_model: str = "openai/gpt-4o-mini"
embedding_model: str = "openai/text-embedding-3-small"
llm_temperature: float = 0.0
max_parallel_llm_calls: int = 8
max_parallel_embedding_calls: int = 16
log_llm_calls: bool = True
log_search_queries: bool = True
```

**Key Functions:**
- `load_config(config_dict, config_file, env_prefix)` → `PKBConfig`
- `save_config(config, config_file)` → None

---

### 3. `utils.py`

Utility functions and parallel execution support.

| Function | Signature | Purpose |
|----------|-----------|---------|
| `generate_uuid` | `() → str` | UUID4 for primary keys |
| `now_iso` | `() → str` | Current UTC timestamp |
| `epoch_iso` | `() → str` | "1970-01-01T00:00:00Z" |
| `is_valid_iso_timestamp` | `(ts: str) → bool` | Validate timestamp |
| `parse_iso_timestamp` | `(ts: str) → datetime` | Parse to datetime |
| `is_timestamp_in_range` | `(check, from, to) → bool` | Check validity range |
| `parse_meta_json` | `(s: str) → Dict` | Parse JSON metadata |
| `update_meta_json` | `(existing, updates) → str` | Merge and return JSON |
| `get_parallel_executor` | `(max_workers) → ParallelExecutor` | Get shared executor |

**`ParallelExecutor` Class:**
- `map_parallel(fn, items, timeout)` → Execute fn on items in parallel
- `map_parallel_kwargs(fn, kwargs_list, timeout)` → Execute with different kwargs
- `submit_all(tasks)` → Submit tasks, return futures
- `wait_all(futures, timeout)` → Collect results

---

### 4. `models.py`

Dataclasses for all database entities. All primary models include `user_email` for multi-user support.

**`Claim` Fields:**
```python
claim_id: str                    # UUID primary key
claim_type: str                  # From ClaimType enum
statement: str                   # The claim text
context_domain: str              # From ContextDomain enum
status: str = "active"           # From ClaimStatus enum
subject_text: Optional[str]      # SPO subject
predicate: Optional[str]         # SPO predicate
object_text: Optional[str]       # SPO object
confidence: Optional[float]      # 0.0-1.0
created_at: str                  # ISO timestamp
updated_at: str                  # ISO timestamp
valid_from: str                  # Temporal validity start
valid_to: Optional[str]          # Temporal validity end
meta_json: Optional[str]         # JSON metadata
retracted_at: Optional[str]      # Soft delete timestamp
user_email: Optional[str]        # Owner email for multi-user (v2)
```

**Common Methods (all models):**
- `to_dict()` → Dict for DB insert
- `to_insert_tuple()` → Tuple matching column order
- `from_row(row)` → Create from SQLite row
- `create(**kwargs)` → Factory with generated ID (accepts `user_email`)

**Other Models with user_email:** `Note`, `Entity`, `Tag`, `ConflictSet`
**Join Models (no user_email):** `ClaimTag`, `ClaimEntity`

---

### 5. `schema.py`

SQLite DDL definitions. **Schema version: 2** (multi-user support).

**Tables Created:**
| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `claims` | Atomic memory units | claim_id, claim_type, statement, status, **user_email** |
| `notes` | Narrative content | note_id, title, body, **user_email** |
| `entities` | People/places/topics | entity_id, entity_type, name, **user_email** (UNIQUE per user) |
| `tags` | Hierarchical labels | tag_id, name, parent_tag_id, **user_email** (UNIQUE per user) |
| `claim_tags` | M:N claim-tag links | claim_id, tag_id |
| `claim_entities` | M:N claim-entity links | claim_id, entity_id, role |
| `conflict_sets` | Contradiction groups | conflict_set_id, status, **user_email** |
| `conflict_set_members` | Conflict membership | conflict_set_id, claim_id |
| `claim_embeddings` | Vector cache | claim_id, embedding (BLOB), model_name |
| `note_embeddings` | Vector cache for notes | note_id, embedding (BLOB) |
| `claims_fts` | FTS5 virtual table | statement, predicate, context_domain |
| `notes_fts` | FTS5 virtual table | title, body, context_domain |
| `schema_version` | Migration tracking | version, applied_at |

**Multi-User Unique Constraints (v2):**
- `entities`: UNIQUE(user_email, entity_type, name)
- `tags`: UNIQUE(user_email, name, parent_tag_id)

**User Email Indexes (v2):**
- `idx_claims_user_email`, `idx_claims_user_status`
- `idx_notes_user_email`
- `idx_entities_user_email`
- `idx_tags_user_email`
- `idx_conflict_sets_user_email`

**Key Functions:**
- `get_all_ddl(include_triggers)` → Complete DDL string
- `get_tables_list()` → List of table names
- `get_fts_tables_list()` → List of FTS table names
- `SCHEMA_VERSION` → Current version (2)

---

### 6. `database.py`

SQLite connection management with automatic schema migration.

**`PKBDatabase` Class:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `__init__` | `(config: PKBConfig)` | Initialize with config |
| `connect` | `() → Connection` | Get/create connection (WAL mode, FK on) |
| `initialize_schema` | `(include_triggers)` | Create tables, run migrations if needed |
| `get_schema_version` | `() → Optional[int]` | Get current schema version |
| `_run_migrations` | `(conn, from_v, to_v)` | Run schema migrations |
| `_migrate_v1_to_v2` | `(conn)` | Add user_email columns/indexes |
| `transaction` | `() → ContextManager` | Atomic transaction context |
| `execute` | `(sql, params)` → Cursor | Execute SQL |
| `fetchone` | `(sql, params)` → Row | Execute and fetch one |
| `fetchall` | `(sql, params)` → List[Row] | Execute and fetch all |
| `table_exists` | `(table_name)` → bool | Check table existence |
| `close` | `()` | Close connection |
| `vacuum` | `()` | Reclaim space |

**Schema Migration (v1 → v2):**
- Adds `user_email TEXT` column to: claims, notes, entities, tags, conflict_sets
- Creates user_email indexes for all tables
- Called automatically during `initialize_schema()` if upgrading

**Factory Functions:**
- `get_database(config, auto_init=True)` → Initialized PKBDatabase (runs migrations)
- `get_memory_database(auto_init=True)` → In-memory database for testing

---

### 7. `llm_helpers.py`

LLM-powered extraction via `code_common/call_llm.py`.

**`LLMHelpers` Class Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `generate_tags` | `(statement, context_domain, existing_tags)` → `List[str]` | Suggest tags |
| `extract_entities` | `(statement)` → `List[Dict]` | Extract entities with type/role |
| `extract_spo` | `(statement)` → `Dict` | Subject/predicate/object structure |
| `classify_claim_type` | `(statement)` → `str` | Classify into claim type |
| `check_similarity` | `(new_claim, existing_claims, threshold)` → `List[Tuple]` | Find similar claims |
| `batch_extract_all` | `(statements, context_domain)` → `List[ExtractionResult]` | Parallel extraction |
| `extract_single` | `(statement, context_domain)` → `ExtractionResult` | Single extraction |

**`ExtractionResult` Dataclass:**
```python
tags: List[str]
entities: List[Dict[str, str]]  # {type, name, role}
spo: Dict[str, Optional[str]]   # {subject, predicate, object}
claim_type: str
keywords: List[str]
```

---

### 8. CRUD Module (`crud/`)

#### `crud/base.py`

**`BaseCRUD[T]` Abstract Class:**

| Method | Type | Purpose |
|--------|------|---------|
| `__init__` | concrete | Initialize with db and optional `user_email` |
| `_table_name` | abstract | Return table name |
| `_id_column` | abstract | Return PK column name |
| `_to_model` | abstract | Convert row to model |
| `_user_filter_sql` | concrete | Get "AND user_email = ?" clause |
| `_user_filter_params` | concrete | Get (user_email,) params tuple |
| `get` | concrete | Get by ID (user-scoped) |
| `exists` | concrete | Check if exists (user-scoped) |
| `list` | concrete | Query with filters/pagination (user-scoped) |
| `count` | concrete | Count matching records (user-scoped) |

**User Scoping:**
All CRUD operations automatically filter by `user_email` if set:
```python
crud = ClaimCRUD(db, user_email="alice@example.com")
crud.list()  # Only returns Alice's claims
```

**Helper Functions:**
- `sync_claim_to_fts(conn, claim_id, operation)` → Manual FTS sync
- `sync_note_to_fts(conn, note_id, operation)` → Manual FTS sync
- `delete_claim_embedding(conn, claim_id)` → Invalidate embedding
- `delete_note_embedding(conn, note_id)` → Invalidate embedding

#### `crud/claims.py` - `ClaimCRUD`

| Method | Signature | Purpose |
|--------|-----------|---------|
| `__init__` | `(db, user_email=None)` | Initialize with optional user scope |
| `_ensure_user_email` | `(claim)` → Claim | Set user_email on claim if needed |
| `add` | `(claim, tags, entities)` → Claim | Add with user_email and optional linking |
| `edit` | `(claim_id, patch)` → Claim | Update fields, invalidate embedding |
| `delete` | `(claim_id, mode)` → Claim | Soft-delete (set retracted) |
| `get_by_entity` | `(entity_id, role, statuses)` → List | Claims linked to entity (user-scoped) |
| `get_by_tag` | `(tag_id, statuses, include_children)` → List | Claims with tag (user-scoped) |
| `get_contested` | `()` → List | All contested claims (user-scoped) |
| `get_active` | `(context_domain, claim_type)` → List | Active claims (user-scoped) |
| `search_by_predicate` | `(predicate, statuses)` → List | Find by predicate (user-scoped) |

#### `crud/notes.py` - `NoteCRUD`

| Method | Signature | Purpose |
|--------|-----------|---------|
| `add` | `(note)` → Note | Add new note |
| `edit` | `(note_id, patch)` → Note | Update fields |
| `delete` | `(note_id)` → bool | Hard delete |

#### `crud/entities.py` - `EntityCRUD`

| Method | Signature | Purpose |
|--------|-----------|---------|
| `add` | `(entity)` → Entity | Add entity |
| `edit` | `(entity_id, patch)` → Entity | Update entity |
| `delete` | `(entity_id)` → bool | Hard delete |
| `get_or_create` | `(name, entity_type)` → Tuple[Entity, bool] | Get existing or create |
| `find_by_name` | `(name, exact)` → List | Search by name |

#### `crud/tags.py` - `TagCRUD`

| Method | Signature | Purpose |
|--------|-----------|---------|
| `add` | `(tag)` → Tag | Add tag |
| `edit` | `(tag_id, patch)` → Tag | Update tag |
| `delete` | `(tag_id)` → bool | Hard delete |
| `get_hierarchy` | `(root_tag_id)` → List | Get descendants |
| `validate_no_cycles` | `(tag_id, new_parent_id)` → bool | Check for cycles |
| `get_full_path` | `(tag_id)` → str | Get "parent/child/..." path |

#### `crud/conflicts.py` - `ConflictCRUD`

| Method | Signature | Purpose |
|--------|-----------|---------|
| `create` | `(claim_ids, notes)` → ConflictSet | Create conflict set |
| `resolve` | `(set_id, notes, winning_id)` → ConflictSet | Resolve conflict |
| `ignore` | `(set_id, notes)` → ConflictSet | Mark as ignored |
| `get_open` | `()` → List | Get open conflicts |
| `add_member` | `(set_id, claim_id)` → bool | Add claim to set |
| `remove_member` | `(set_id, claim_id)` → bool | Remove claim |

#### `crud/links.py` - Join Table Functions

| Function | Signature | Purpose |
|----------|-----------|---------|
| `link_claim_tag` | `(db, claim_id, tag_id)` → bool | Create link |
| `unlink_claim_tag` | `(db, claim_id, tag_id)` → bool | Remove link |
| `link_claim_entity` | `(db, claim_id, entity_id, role)` → bool | Create link |
| `unlink_claim_entity` | `(db, claim_id, entity_id, role)` → bool | Remove link |
| `get_claim_tags` | `(db, claim_id)` → List[Tag] | Get tags for claim |
| `get_claim_entities` | `(db, claim_id)` → List[Dict] | Get entities for claim |
| `get_tags_for_claims` | `(db, claim_ids)` → Dict | Batch get tags |
| `get_entities_for_claims` | `(db, claim_ids)` → Dict | Batch get entities |

---

### 9. Search Module (`search/`)

#### `search/base.py`

**`SearchFilters` Dataclass:**
```python
statuses: List[str]                    # Default: active + contested
context_domains: Optional[List[str]]   # Filter by domains
claim_types: Optional[List[str]]       # Filter by types
tag_ids: Optional[List[str]]           # Filter by tags
entity_ids: Optional[List[str]]        # Filter by entities
valid_at: Optional[str]                # Temporal validity filter
include_contested: bool = True         # Include contested claims
user_email: Optional[str] = None       # Filter by user (multi-user mode)
```

**User Filtering in SQL:**
```python
def to_sql_conditions(self) -> Tuple[str, List]:
    # ... other conditions ...
    if self.user_email:
        conditions.append("c.user_email = ?")
        params.append(self.user_email)
```

**`SearchResult` Dataclass:**
```python
claim: Claim                           # Matched claim
score: float                           # Relevance score
source: str                            # Strategy name
is_contested: bool                     # Warning flag
warnings: List[str]                    # User warnings
metadata: Dict[str, Any]               # Strategy-specific data
```

**`SearchStrategy` ABC:**
```python
@abstractmethod
def search(self, query: str, k: int, filters: SearchFilters) -> List[SearchResult]

@abstractmethod
def name(self) -> str
```

**Utility Functions:**
- `merge_results_rrf(result_lists, k, rrf_k)` → RRF-merged results
- `dedupe_results(results)` → Deduplicated by claim_id
- `apply_tag_filter(db, claim_ids, tag_ids)` → Filter by tags
- `apply_entity_filter(db, claim_ids, entity_ids)` → Filter by entities

#### `search/fts_search.py` - `FTSSearchStrategy`

BM25 ranking via SQLite FTS5.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `search` | `(query, k, filters)` → List[SearchResult] | FTS5 search with BM25 |
| `name` | `()` → "fts" | Strategy identifier |

**SQL Query Pattern:**
```sql
SELECT c.*, bm25(claims_fts) as score
FROM claims_fts f
JOIN claims c ON f.claim_id = c.claim_id
WHERE claims_fts MATCH ?
  AND c.status IN (...)
ORDER BY score
LIMIT ?
```

#### `search/embedding_search.py` - `EmbeddingSearchStrategy`

Cosine similarity over vector embeddings.

**`EmbeddingStore` Class:**
| Method | Purpose |
|--------|---------|
| `get_embedding(claim_id)` | Get cached embedding |
| `store_embedding(claim_id, embedding, model)` | Cache embedding |
| `get_or_compute(claim_id, statement)` | Get/compute embedding |
| `batch_get_or_compute(claims)` | Parallel batch operation |

**`EmbeddingSearchStrategy` Class:**
| Method | Purpose |
|--------|---------|
| `search(query, k, filters)` | Semantic search via cosine similarity |
| `name()` | Returns "embedding" |

**Algorithm:**
1. Get query embedding via `get_query_embedding()`
2. Get/compute embeddings for candidate claims
3. Compute cosine similarity: `dot(q, d) / (||q|| * ||d||)`
4. Sort by similarity, return top-k

**Important: Numpy Array Truthiness**

When checking if embeddings exist, always use identity comparison (`is not None`) instead of truthiness:

```python
# WRONG - causes "ambiguous truth value" error with numpy arrays
if query_emb:  
    process(query_emb)

# CORRECT - use identity comparison
if query_emb is not None:
    process(query_emb)
```

This applies to all embedding-related code where numpy arrays might be checked.

#### `search/rewrite_search.py` - `RewriteSearchStrategy`

LLM rewrites natural language query → FTS keywords.

**Process:**
1. Call LLM with prompt to extract search keywords
2. Build FTS query from keywords
3. Execute FTS search
4. Return results with rewrite metadata

#### `search/mapreduce_search.py` - `MapReduceSearchStrategy`

LLM scores/filters candidate claims.

**Process:**
1. Get candidate pool via FTS (k * 3)
2. Batch claims and send to LLM for relevance scoring
3. Parse scores (0-10) from LLM response
4. Sort by score, return top-k

#### `search/hybrid_search.py` - `HybridSearchStrategy`

Orchestrates multiple strategies with parallel execution.

| Method | Signature | Purpose |
|--------|-----------|---------|
| `search` | `(query, strategy_names, k, filters, llm_rerank)` | Hybrid search |
| `search_simple` | `(query, k, filters)` | Default: FTS + embedding |
| `search_with_rerank` | `(query, k, filters)` | Hybrid + LLM rerank |
| `search_all_strategies` | `(query, k, filters)` | Use all strategies |
| `get_available_strategies` | `()` → List[str] | List available strategies |

**Algorithm:**
1. Execute selected strategies in parallel
2. Merge results using Reciprocal Rank Fusion (RRF)
3. Optionally apply LLM reranking to top-N
4. Return final top-k results

#### `search/notes_search.py` - `NotesSearchStrategy`

Search notes via FTS + embedding (separate from claims).

---

### 10. Interface Module (`interface/`)

#### `interface/structured_api.py` - `StructuredAPI`

Unified programmatic API for all operations. **Supports multi-user mode via `user_email`.**

**`ActionResult` Dataclass:**
```python
success: bool                    # Operation success
action: str                      # Action name
object_type: str                 # Object type affected
object_id: Optional[str]         # Primary object ID
data: Any                        # Result data
warnings: List[str]              # Non-fatal warnings
errors: List[str]                # Error messages
```

**`StructuredAPI` Initialization:**
```python
# Single-user or admin mode
api = StructuredAPI(db, keys, config)

# Multi-user mode (all operations scoped to user)
api = StructuredAPI(db, keys, config, user_email="user@example.com")

# Factory method for user-scoped instance
user_api = shared_api.for_user("user@example.com")
```

**`StructuredAPI` Methods:**

| Category | Method | Purpose |
|----------|--------|---------|
| Factory | `for_user(user_email)` → StructuredAPI | Create user-scoped instance |
| Claims | `add_claim(statement, claim_type, ...)` | Add with auto-extraction (user-scoped) |
| Claims | `add_claims_bulk(claims, auto_extract, stop_on_error)` | Add multiple claims in batch |
| Claims | `edit_claim(claim_id, **patch)` | Update fields |
| Claims | `delete_claim(claim_id)` | Soft delete |
| Claims | `get_claim(claim_id)` | Get by ID |
| Claims | `get_claims_by_ids(claim_ids)` | Get multiple claims by IDs |
| Pinning | `pin_claim(claim_id, pin)` | Toggle global pin status via meta_json |
| Pinning | `get_pinned_claims(limit)` | Get all globally pinned claims |
| Notes | `add_note(body, title, ...)` | Add note (user-scoped) |
| Notes | `edit_note(note_id, **patch)` | Update note |
| Notes | `delete_note(note_id)` | Delete note |
| Search | `search(query, strategy, k, filters)` | Search claims (user-scoped) |
| Search | `search_notes(query, k, ...)` | Search notes (user-scoped) |
| Entities | `add_entity(name, entity_type)` | Add entity (user-scoped) |
| Tags | `add_tag(name, parent_tag_id)` | Add tag (user-scoped) |
| Conflicts | `create_conflict_set(claim_ids)` | Create conflict (user-scoped) |
| Conflicts | `resolve_conflict_set(set_id, notes, winning_id)` | Resolve |
| Conflicts | `get_open_conflicts()` | List open conflicts (user-scoped) |

#### `interface/text_orchestration.py` - `TextOrchestrator`

Natural language command parser.

**`OrchestrationResult` Dataclass:**
```python
action_taken: str                # Description of action
action_result: ActionResult      # Result from API
clarifying_questions: List[str]  # Questions if unclear
affected_objects: List[Dict]     # Objects affected
raw_intent: Dict                 # Parsed intent
```

**`TextOrchestrator` Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `process` | `(user_text, context)` → OrchestrationResult | Parse and execute |
| `execute_confirmed_action` | `(action, target_id, **kwargs)` | Execute after confirmation |

**Intent Parsing:**
- Uses LLM to parse command into structured intent
- Falls back to rule-based parsing if LLM unavailable
- Detects: add_claim, search, edit_claim, delete_claim, add_note, list_conflicts

**Supported Commands:**
- "remember that I prefer morning workouts"
- "find what I said about mom's health"
- "delete the reminder about dentist"
- "update my coffee preference"

#### `interface/conversation_distillation.py` - `ConversationDistiller`

Extract memorable facts from chat conversations.

**Key Dataclasses:**
```python
@dataclass
class CandidateClaim:
    statement: str
    claim_type: str
    context_domain: str
    confidence: float
    source: str

@dataclass
class ProposedAction:
    action: str           # add, update, retract, skip, conflict
    candidate: CandidateClaim
    existing_claim: Optional[Claim]
    relation: Optional[str]
    reason: str

@dataclass
class MemoryUpdatePlan:
    candidates: List[CandidateClaim]
    existing_matches: List[Tuple]
    proposed_actions: List[ProposedAction]
    user_prompt: str
    requires_user_confirmation: bool

@dataclass
class DistillationResult:
    plan: MemoryUpdatePlan
    executed: bool
    execution_results: List[ActionResult]
```

**`ConversationDistiller` Methods:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `extract_and_propose` | `(summary, user_msg, assistant_msg)` → MemoryUpdatePlan | Extract and analyze |
| `execute_plan` | `(plan, user_response, approved_indices)` → DistillationResult | Execute approved actions |

**Process:**
1. Extract candidate claims from conversation turn (LLM)
2. Search for existing similar claims
3. Determine relationship (duplicate, update, conflict, new)
4. Generate user confirmation prompt
5. Execute approved actions

#### `interface/text_ingestion.py` - `TextIngestionDistiller`

Parse and ingest bulk text with AI-powered analysis and duplicate detection.

**Key Dataclasses:**
```python
@dataclass
class IngestCandidate:
    """A candidate claim extracted from text ingestion."""
    statement: str
    claim_type: str
    context_domain: str
    confidence: float
    line_number: Optional[int] = None
    original_text: Optional[str] = None

@dataclass
class IngestProposal:
    """Proposed action for a candidate."""
    action: str           # 'add', 'edit', 'skip'
    candidate: IngestCandidate
    existing_claim: Optional[Claim] = None
    similarity_score: Optional[float] = None
    reason: str = ""
    editable: bool = True

@dataclass
class TextIngestionPlan:
    """Complete plan for text ingestion."""
    plan_id: str = ""
    raw_text: str = ""
    candidates: List[IngestCandidate] = field(default_factory=list)
    proposals: List[IngestProposal] = field(default_factory=list)
    add_count: int = 0
    edit_count: int = 0
    skip_count: int = 0
    summary: str = ""

@dataclass
class IngestExecutionResult:
    """Result of executing approved proposals."""
    success: bool
    added_count: int = 0
    edited_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    results: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
```

**`TextIngestionDistiller` Class:**

| Method | Signature | Purpose |
|--------|-----------|---------|
| `__init__` | `(api, keys, config)` | Initialize with StructuredAPI |
| `ingest_and_propose` | `(text, default_type, default_domain, use_llm)` → TextIngestionPlan | Parse and propose actions |
| `execute_plan` | `(plan, approved_proposals)` → IngestExecutionResult | Execute approved proposals |
| `_parse_text_with_llm` | `(text, type, domain)` → List[IngestCandidate] | AI-powered text parsing |
| `_parse_text_simple` | `(text, type, domain)` → List[IngestCandidate] | Rule-based parsing fallback |
| `_find_matches_for_candidate` | `(candidate)` → List[Tuple[Claim, float]] | Search for similar claims |
| `_determine_action` | `(candidate, matches)` → IngestProposal | Decide add/edit/skip |

**Similarity Thresholds:**
```python
DUPLICATE_THRESHOLD = 0.92  # Skip: exact duplicate
EDIT_THRESHOLD = 0.75       # Edit: update existing claim
RELATED_THRESHOLD = 0.55    # Add with warning: related exists
```

**Process:**
1. Parse input text into candidate claims (LLM or rule-based)
2. For each candidate, search existing claims using hybrid search
3. Determine action based on similarity score thresholds
4. Return plan with proposals for user review
5. Execute approved proposals with optional user edits

---

## External Integrations

### 11. Flask Server (`server.py`)

The PKB is exposed via REST API endpoints in the main Flask server.

**Global State:**
```python
_pkb_db: PKBDatabase = None         # Shared database instance
_pkb_config: PKBConfig = None       # Configuration
_pkb_keys: dict = None              # API keys
_memory_update_plans: dict = {}     # Temporary plan storage (conversation distillation)
_text_ingestion_plans: dict = {}    # Temporary plan storage (text ingestion)
_conversation_pinned_claims: dict = {}  # conv_id -> set(claim_ids) (v0.4 ephemeral pins)
```

**Conversation Pinning Helper Functions (v0.4):**
```python
def get_conversation_pinned_claims(conversation_id: str) -> set:
    """Get set of claim IDs pinned to a specific conversation."""
    return _conversation_pinned_claims.get(conversation_id, set())

def add_conversation_pinned_claim(conversation_id: str, claim_id: str):
    """Add a claim ID to the conversation's pinned set."""
    if conversation_id not in _conversation_pinned_claims:
        _conversation_pinned_claims[conversation_id] = set()
    _conversation_pinned_claims[conversation_id].add(claim_id)

def remove_conversation_pinned_claim(conversation_id: str, claim_id: str):
    """Remove a claim ID from the conversation's pinned set."""
    if conversation_id in _conversation_pinned_claims:
        _conversation_pinned_claims[conversation_id].discard(claim_id)

def clear_conversation_pinned_claims(conversation_id: str):
    """Clear all pinned claims for a conversation."""
    if conversation_id in _conversation_pinned_claims:
        del _conversation_pinned_claims[conversation_id]
```

**Helper Functions:**
| Function | Purpose |
|----------|---------|
| `get_pkb_db()` | Lazy-initialize shared PKB database |
| `get_pkb_api_for_user(user_email, keys)` | Get user-scoped StructuredAPI |
| `serialize_claim(claim)` | Convert Claim to JSON dict |
| `serialize_entity(entity)` | Convert Entity to JSON dict |
| `serialize_tag(tag)` | Convert Tag to JSON dict |
| `serialize_conflict_set(cs)` | Convert ConflictSet to JSON dict |
| `serialize_search_result(sr)` | Convert SearchResult to JSON dict |

**REST Endpoints:**

| Endpoint | Method | Handler | Purpose |
|----------|--------|---------|---------|
| `/pkb/claims` | GET | List claims with filters | Pagination, status/type/domain filters |
| `/pkb/claims` | POST | Add new claim | Auto-extract, return with ID |
| `/pkb/claims/<id>` | GET | Get single claim | Full claim details |
| `/pkb/claims/<id>` | PUT | Edit claim | Partial update |
| `/pkb/claims/<id>` | DELETE | Soft-delete claim | Sets status=retracted |
| `/pkb/claims/bulk` | POST | Add multiple claims | Bulk add via `add_claims_bulk()` |
| `/pkb/search` | POST | Search claims | Hybrid/FTS/embedding strategy |
| `/pkb/entities` | GET | List entities | For dropdown/autocomplete |
| `/pkb/tags` | GET | List tags | For dropdown/autocomplete |
| `/pkb/conflicts` | GET | List open conflicts | For conflict resolution UI |
| `/pkb/conflicts/<id>/resolve` | POST | Resolve conflict | Optional winning claim |
| `/pkb/propose_updates` | POST | Propose memory updates | ConversationDistiller integration |
| `/pkb/execute_updates` | POST | Execute approved updates | Supports edits to proposals |
| `/pkb/ingest_text` | POST | Parse text with AI | TextIngestionDistiller analysis |
| `/pkb/execute_ingest` | POST | Execute text ingestion | From text ingestion plan |
| `/pkb/relevant_context` | POST | Get PKB context for LLM | Formatted claim list |
| `/pkb/claims/<id>/pin` | POST | Toggle global pin | Set meta_json.pinned |
| `/pkb/pinned` | GET | Get globally pinned claims | All claims with pinned=true |
| `/pkb/conversation/<id>/pin` | POST | Pin/unpin to conversation | Ephemeral session state |
| `/pkb/conversation/<id>/pinned` | GET | Get conversation-pinned | Claims pinned to session |
| `/pkb/conversation/<id>/pinned` | DELETE | Clear conversation pins | Clear ephemeral pins |

### 12. Conversation.py Integration

The `Conversation` class integrates PKB for context enrichment with support for deliberate memory attachment.

**Critical: Database Path Configuration**

Both `Conversation.py` and `server.py` must use the **same** database path:

```python
# server.py uses:
users_dir = os.path.join(os.getcwd(), "storage", "users")
pkb_db_path = os.path.join(users_dir, "pkb.sqlite")  # → storage/users/pkb.sqlite

# Conversation.py must match:
pkb_db_path = os.path.join(os.path.dirname(__file__), "storage", "users", "pkb.sqlite")
```

**Common Bug:** If these paths don't match, the UI (via server.py) writes to one database while Conversation.py reads from another, causing memories to not appear in chat despite being visible in the PKB modal.

**Enhanced `_get_pkb_context()` Method:**
```python
def _get_pkb_context(
    self, 
    user_email: str, 
    query: str, 
    conversation_summary: str = "",
    k: int = 10,
    attached_claim_ids: list = None,       # From UI "Use Now" selection
    conversation_id: str = None,            # For conversation-level pinning
    conversation_pinned_claim_ids: list = None,  # Injected from server
    referenced_claim_ids: list = None       # From @memory: mentions
) -> str:
    """
    Retrieve PKB context with multiple sources:
    1. Referenced claims (@memory mentions) - highest priority
    2. Attached claims (from UI selection) - high priority
    3. Globally pinned claims - medium-high priority  
    4. Conversation-pinned claims - medium priority
    5. Auto-retrieved via hybrid search - normal priority
    
    Returns:
        Formatted string with source indicators:
        "[REFERENCED] [preference] I prefer morning meetings
         [GLOBAL PINNED] [fact] My timezone is IST
         [AUTO] [fact] I work in tech"
    """
```

**Context Retrieval Flow:**
```
1. Fetch referenced claims (explicit @memory)
   └── api.get_claims_by_ids(referenced_claim_ids)

2. Fetch attached claims (UI selection)
   └── api.get_claims_by_ids(attached_claim_ids)

3. Fetch globally pinned claims
   └── api.get_pinned_claims()

4. Get conversation-pinned IDs (passed from server)
   └── api.get_claims_by_ids(conversation_pinned_claim_ids)

5. Fill remaining slots with auto-search
   └── api.search(query, strategy='hybrid', k=remaining)

6. Deduplicate by claim_id (keep highest priority)

7. Format with source indicators
```

**Integration in reply():**
```python
def reply(self, query, userData=None, ...):
    # Extract deliberate attachment IDs from query
    attached_claim_ids = query.get("attached_claim_ids", [])
    conversation_pinned_claim_ids = query.get("conversation_pinned_claim_ids", [])
    referenced_claim_ids = query.get("referenced_claim_ids", [])
    
    # 1. Start async PKB fetch with all parameters
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
    
    # 2. Continue with other processing (in parallel)
    # ... embeddings, memory, etc. ...
    
    # 3. Get PKB context (blocks only if not ready)
    pkb_context = pkb_future.result(timeout=5.0)
    
    # 4. Inject into system prompt
    if pkb_context:
        user_info += f"\n\nRelevant user facts:\n{pkb_context}"
```

**Server-Side Injection (server.py):**
```python
# In /send_message/<conversation_id> endpoint
@app.route('/send_message/<conversation_id>', methods=['POST'])
def send_message(conversation_id):
    query = request.json
    
    # Inject conversation-pinned claim IDs from session state
    conv_pinned_ids = list(get_conversation_pinned_claims(conversation_id))
    if conv_pinned_ids:
        query['conversation_pinned_claim_ids'] = conv_pinned_ids
    
    # ... pass to conversation.reply() ...
```

### 13. Frontend (`interface/pkb-manager.js`)

JavaScript module for PKB UI operations.

**Module Structure:**
```javascript
var PKBManager = (function() {
    // Private state
    var currentPage = 1;
    var currentFilters = {};
    var pendingMemoryAttachments = [];  // Claim IDs for "Use Now" (v0.4)
    var pendingMemoryDetails = {};      // {claimId: {statement, type}} (v0.4)
    
    // Public API
    return {
        // CRUD
        listClaims: function(filters) {...},
        addClaim: function(claimData) {...},
        editClaim: function(claimId, updates) {...},
        deleteClaim: function(claimId) {...},
        
        // Search
        searchClaims: function(query, options) {...},
        
        // Entities/Tags
        listEntities: function() {...},
        listTags: function() {...},
        
        // Memory Updates (Conversation)
        checkMemoryUpdates: function(summary, userMsg, assistantMsg) {...},
        showMemoryProposalModal: function(proposals) {...},
        saveSelectedProposals: function(planId, approvedIndices) {...},
        
        // Bulk Add (v0.3)
        addBulkRow: function() {...},
        removeBulkRow: function(index) {...},
        clearBulkRows: function() {...},
        saveBulkClaims: function() {...},
        renderBulkRow: function(index) {...},
        collectBulkRows: function() {...},
        initBulkAddTab: function() {...},
        
        // Text Ingestion (v0.3)
        analyzeTextForIngestion: function() {...},
        
        // Enhanced Bulk Approval Modal (v0.3)
        showBulkProposalModal: function(proposals, source, planId, summary) {...},
        renderProposalRow: function(proposal, index) {...},
        updateProposalSelectedCount: function() {...},
        collectApprovedProposals: function() {...},
        saveSelectedProposals: function() {...},
        
        // Global Pinning (v0.4)
        pinClaim: function(claimId, pin) {...},
        getPinnedClaims: function() {...},
        isClaimPinned: function(claimId) {...},
        togglePinAndRefresh: function(claimId) {...},
        
        // Conversation-Level Pinning (v0.4)
        pinToConversation: function(convId, claimId, pin) {...},
        getConversationPinned: function(convId) {...},
        clearConversationPinned: function(convId) {...},
        pinToCurrentConversation: function(claimId, pin) {...},
        
        // "Use in Next Message" (v0.4)
        addToNextMessage: function(claimId) {...},
        removeFromPending: function(claimId) {...},
        getPendingAttachments: function() {...},
        getPendingCount: function() {...},
        clearPendingAttachments: function() {...},
        updatePendingAttachmentsIndicator: function() {...},
        
        // UI
        openPKBModal: function() {...},
        renderClaimsList: function(claims) {...},
        // ...
    };
})();
```

**Bulk Add Functions:**

| Function | Purpose |
|----------|---------|
| `addBulkRow()` | Append new empty row to bulk add container |
| `removeBulkRow(index)` | Remove row at specified index |
| `clearBulkRows()` | Clear all rows and add one fresh row |
| `renderBulkRow(index)` | Generate HTML for a single bulk row |
| `collectBulkRows()` | Collect data from all rows for submission |
| `saveBulkClaims()` | POST to `/pkb/claims/bulk` with collected rows |
| `initBulkAddTab()` | Ensure tab starts with at least one row |

**Text Ingestion Functions:**

| Function | Purpose |
|----------|---------|
| `analyzeTextForIngestion()` | POST to `/pkb/ingest_text`, show proposals in modal |

**Enhanced Approval Modal Functions:**

| Function | Purpose |
|----------|---------|
| `showBulkProposalModal(proposals, source, planId, summary)` | Render proposals in modal |
| `renderProposalRow(proposal, index)` | Generate editable row HTML |
| `updateProposalSelectedCount()` | Update "Save Selected (N)" count |
| `collectApprovedProposals()` | Get checked proposals with edits |
| `saveSelectedProposals()` | Execute via appropriate endpoint |

**Global Pinning Functions (v0.4):**

| Function | Purpose |
|----------|---------|
| `pinClaim(claimId, pin)` | POST to `/pkb/claims/{id}/pin`, toggle global pin |
| `getPinnedClaims()` | GET `/pkb/pinned`, return all globally pinned |
| `isClaimPinned(claimId)` | Check if claim is currently pinned |
| `togglePinAndRefresh(claimId)` | Toggle pin state and refresh claim list UI |

**Conversation-Level Pinning Functions (v0.4):**

| Function | Purpose |
|----------|---------|
| `pinToConversation(convId, claimId, pin)` | POST to `/pkb/conversation/{id}/pin` |
| `getConversationPinned(convId)` | GET `/pkb/conversation/{id}/pinned` |
| `clearConversationPinned(convId)` | DELETE `/pkb/conversation/{id}/pinned` |
| `pinToCurrentConversation(claimId, pin)` | Pin to active conversation (uses ConversationManager) |

**"Use in Next Message" Functions (v0.4):**

| Function | Purpose |
|----------|---------|
| `addToNextMessage(claimId)` | Add claim ID to pending attachments queue |
| `removeFromPending(claimId)` | Remove specific claim from queue |
| `getPendingAttachments()` | Return array of pending claim IDs |
| `getPendingCount()` | Return count of pending attachments |
| `clearPendingAttachments()` | Clear all pending (called after message sent) |
| `updatePendingAttachmentsIndicator()` | Render/update pending chips near chat input |

**UI Changes for Deliberate Memory (v0.4):**

- **Claim Card Buttons**: `renderClaimCard()` adds:
  - Pin button (`pkb-pin-claim`) with visual indicator for pinned state
  - "Use in next message" button (`pkb-use-now-claim`)
- **Pending Attachments Indicator**: Visual chips near chat input showing queued memories
- **Event Listeners**: `renderClaimsList()` adds handlers for new buttons

**Auto-Integration in common-chat.js (v0.4 Enhanced):**
```javascript
function sendMessageCallback() {
    // Get pending memory attachments from PKBManager
    var attached_claim_ids = [];
    if (typeof PKBManager !== 'undefined' && PKBManager.getPendingAttachments) {
        attached_claim_ids = PKBManager.getPendingAttachments();
        if (attached_claim_ids.length > 0) {
            PKBManager.clearPendingAttachments();  // Clear after getting
        }
    }
    
    // Parse @memory references from message text
    var referenced_claim_ids = [];
    if (typeof parseMemoryReferences === 'function') {
        var memoryRefs = parseMemoryReferences(messageText);
        referenced_claim_ids = memoryRefs.claimIds;
        // messageText can be set to memoryRefs.cleanText if desired
    }
    
    // Send with attached and referenced IDs
    ChatManager.sendMessage(
        conversationId, 
        messageText, 
        options, 
        links, 
        search,
        attached_claim_ids,      // v0.4: From "Use Now"
        referenced_claim_ids     // v0.4: From @memory: refs
    ).then(function(response) {
        // ... handle response ...
        
        // Trigger memory update check after delay
        setTimeout(function() {
            if (typeof PKBManager !== 'undefined') {
                PKBManager.checkMemoryUpdates(
                    conversationSummary, 
                    messageText, 
                    ''  // assistant message filled later
                );
            }
        }, 3000);
    });
}

// ChatManager.sendMessage now accepts attached_claim_ids and referenced_claim_ids
sendMessage: function(conversationId, messageText, checkboxes, links, search, 
                      attached_claim_ids, referenced_claim_ids) {
    var requestBody = { ... };
    
    // Include attached claim IDs if provided
    if (attached_claim_ids && attached_claim_ids.length > 0) {
        requestBody['attached_claim_ids'] = attached_claim_ids;
    }
    // Include referenced claim IDs from @memory: refs if provided
    if (referenced_claim_ids && referenced_claim_ids.length > 0) {
        requestBody['referenced_claim_ids'] = referenced_claim_ids;
    }
    
    return fetch('/send_message/' + conversationId, { ... });
}
```

**@memory Reference Parsing (parseMessageForCheckBoxes.js):**
```javascript
function parseMemoryReferences(text) {
    // Regex to match @memory:claim_id or @mem:claim_id
    var regex = /@(?:memory|mem):([a-zA-Z0-9-]+)/g;
    var claimIds = [];
    var match;
    var cleanText = text;
    
    while ((match = regex.exec(text)) !== null) {
        claimIds.push(match[1]);
        cleanText = cleanText.replace(match[0], '');
    }
    
    return {
        cleanText: cleanText.trim(),  // Text with references removed
        claimIds: claimIds             // Array of extracted claim IDs
    };
}
```

### 14. Frontend HTML (`interface/interface.html`)

The PKB modal includes tabs for different operations.

**PKB Modal Tabs:**
| Tab | ID | Purpose |
|-----|----|---------|
| My Memories | `#pkb-list-pane` | View/edit existing claims |
| Add Memory | `#pkb-add-pane` | Add single claim form |
| **Bulk Add** | `#pkb-bulk-pane` | Row-wise multi-claim entry (v0.3) |
| **Import Text** | `#pkb-import-pane` | AI-powered text parsing (v0.3) |
| Search | `#pkb-search-pane` | Search claims |

**Bulk Add Tab (`#pkb-bulk-pane`):**
- Container `#pkb-bulk-rows-container` for dynamically added rows
- Each row: statement textarea, type dropdown, domain dropdown, remove button
- "Add Another Row" button (`#pkb-bulk-add-row`)
- "Clear All" button (`#pkb-bulk-clear`)
- "Save All Memories" button (`#pkb-bulk-save-all`)
- Progress indicator (`#pkb-bulk-progress`)

**Import Text Tab (`#pkb-import-pane`):**
- Large textarea (`#pkb-import-text`) for pasting text
- Default type dropdown (`#pkb-import-default-type`)
- Default domain dropdown (`#pkb-import-default-domain`)
- "Use AI for intelligent parsing" checkbox (`#pkb-import-use-llm`)
- "Analyze & Extract Memories" button (`#pkb-import-analyze`)
- Loading indicator (`#pkb-import-loading`)

**Enhanced Memory Proposal Modal (`#memory-proposal-modal`):**
- Summary counts: `#proposal-add-count`, `#proposal-edit-count`, `#proposal-skip-count`
- Bulk selection: `#proposal-select-all`, `#proposal-deselect-all` buttons
- Proposal list with editable rows in `#memory-proposal-list`
- Hidden inputs: `#memory-proposal-plan-id`, `#memory-proposal-source`
- Save button with count: `#proposal-selected-count`

**Proposal Row Structure (rendered by JS):**
```html
<div class="proposal-row" data-index="0">
  <input type="checkbox" class="proposal-checkbox" checked>
  <span class="badge badge-success">New</span>
  <textarea class="proposal-statement">Statement text...</textarea>
  <select class="proposal-type">...</select>
  <select class="proposal-domain">...</select>
  <!-- For edits: shows existing claim info -->
</div>
```

### 15. Migration Script (`migrate_user_details.py`)

Standalone script for migrating legacy UserDetails data.

**Main Functions:**
| Function | Purpose |
|----------|---------|
| `get_user_details_connection(db_path)` | Connect to users.db |
| `get_all_users(conn)` | Fetch users with memory/preferences |
| `parse_text_to_claims(text, type, domain)` | Parse text into claim dicts |
| `migrate_user(api, user_data, dry_run)` | Migrate one user's data |
| `run_migration(users_db, pkb_db, user, dry_run)` | Orchestrate migration |
| `main()` | CLI entry point |

**Claim Type Inference:**
```python
# Keywords trigger claim type assignment
"prefer" → preference
"decided" → decision  
"remind" → reminder
"habit" → habit
"every day/week" → habit
```

**Usage:**
```bash
# Preview
python -m truth_management_system.migrate_user_details --dry-run

# Full migration
python -m truth_management_system.migrate_user_details

# Single user
python -m truth_management_system.migrate_user_details --user alice@example.com
```

---

## Data Flow Summary

| Flow | Steps |
|------|-------|
| **Add Claim** | `StructuredAPI.add_claim()` → [auto_extract: LLMHelpers.extract_single() → tags/entities/SPO] → `ClaimCRUD.add()` (INSERT + links + FTS trigger) → `ActionResult` |
| **Hybrid Search** | `HybridSearchStrategy.search()` → [parallel: FTS(BM25) + Embedding(cosine)] → `merge_results_rrf()` → [optional: LLM rerank] → `List[SearchResult]` |
| **Distillation** | `extract_and_propose()` → [LLM extract] → [search existing] → [propose actions] → `MemoryUpdatePlan` → user confirms → `execute_plan()` |
| **Bulk Add** | `add_claims_bulk()` → for each: `add_claim()` (with optional auto_extract) → `ActionResult{added_count, failed_count}` |
| **Text Ingest** | `ingest_and_propose()` → [LLM/rule parse] → [search matches] → [threshold: ≥0.92→skip, ≥0.75→edit, else→add] → `TextIngestionPlan` → user review → `execute_plan()` |

### Deliberate Memory Attachment Flow (v0.4)

```
Frontend Triggers:
  Global Pin → POST /pkb/claims/{id}/pin → meta_json.pinned=true
  Conv Pin → POST /pkb/conversation/{id}/pin → session state
  Use Now → pendingMemoryAttachments[] (JS)
  @memory:id → parseMemoryReferences() extracts claim IDs

Send Message (common-chat.js):
  attached_claim_ids = PKBManager.getPendingAttachments()
  referenced_claim_ids = parseMemoryReferences(text).claimIds
  POST /send_message/{convId} {messageText, attached_claim_ids, referenced_claim_ids}

Server (server.py):
  Inject conversation_pinned_claim_ids from get_conversation_pinned_claims(convId)
  Pass to conversation.reply()

Conversation.py (_get_pkb_context):
  1. REFERENCED: get_claims_by_ids(referenced_ids) [HIGHEST]
  2. ATTACHED: get_claims_by_ids(attached_ids) [HIGH]
  3. GLOBAL PINNED: get_pinned_claims() [MEDIUM-HIGH]
  4. CONV PINNED: get_claims_by_ids(conv_pinned) [MEDIUM]
  5. AUTO: search(query, strategy='hybrid') [NORMAL]
  → Deduplicate by claim_id (keep highest priority) → Format with source labels
```

---

## Database Schema (v2)

| Table | Key Columns | Relationships |
|-------|-------------|---------------|
| **claims** | claim_id (PK), claim_type, statement, status, context_domain, meta_json, user_email | → claim_embeddings (1:N), claim_tags (M:N), claim_entities (M:N) |
| **notes** | note_id (PK), title, body, context_domain, user_email | → note_embeddings (1:N) |
| **entities** | entity_id (PK), entity_type, name, user_email, UNIQUE(user,type,name) | ← claim_entities (M:1) |
| **tags** | tag_id (PK), name, parent_tag_id (self-ref), user_email, UNIQUE(user,name,parent) | ← claim_tags (M:1) |
| **conflict_sets** | conflict_set_id (PK), status, resolution_notes, user_email | → conflict_set_members |
| **claim_embeddings** | claim_id (PK,FK), embedding (BLOB), model_name | |
| **note_embeddings** | note_id (PK,FK), embedding (BLOB), model_name | |
| **claims_fts** | FTS5: statement, predicate, object_text, subject_text, context_domain | |
| **notes_fts** | FTS5: title, body, context_domain | |
| **schema_version** | version (PK), applied_at — Current: 2 | |

**User Email Indexes (v2):** idx_claims_user_email, idx_claims_user_status, idx_notes_user_email, idx_entities_user_email, idx_tags_user_email, idx_conflict_sets_user_email

---

## Parallelization

Uses `ParallelExecutor` and `get_async_future()`:
- Hybrid Search: parallel strategies; Batch Extraction: parallel LLM calls; Embedding: parallel computation
- PKB Context in `Conversation.py`: `pkb_future = get_async_future(...)` runs parallel with chat processing

---

## Testing

```bash
cd truth_management_system && pytest tests/ -v
```

Tests: `test_crud.py`, `test_search.py`, `test_interface.py` — use in-memory SQLite, isolated fixtures

---

## Key Design Decisions

| Category | Decision | Rationale |
|----------|----------|-----------|
| **Data** | Multi-user via user_email; soft deletes only; FTS/BM25 as backbone | Per-user isolation; history preserved; deterministic retrieval |
| **Search** | Embeddings as BLOBs; contested claims with warnings; async PKB context | Recomputable vectors; users see conflicts; no latency impact |
| **Safety** | Transaction boundaries; FTS sync invariant; enums over magic strings | Atomicity; reliability; prevents typos |
| **Extensibility** | meta_json for non-core fields; LLM via call_llm.py | No migrations needed; easy model swapping |
| **Bulk Ops** | Individual fallback; plan storage; editable proposals; configurable thresholds | Partial success; user review; flexibility |

---

## Potential Challenges

| Category | Challenges & Mitigations |
|----------|-------------------------|
| **Data Integrity** | FTS drift (triggers), tag cycles (validate_no_cycle), embedding staleness (delete on edit) |
| **LLM** | Non-determinism (temp=0.0), rate limits (rule-based fallback), large text (size limits) |
| **Multi-User (v2)** | Data leak (user_email filter), migration failures (transaction), cross-user conflicts (validate) |
| **Bulk/Ingest** | Partial failures (stop_on_error), stale plans (cleanup), concurrent access (plan ID check) |
| **Pinning (v0.4)** | Too many pins (limit), orphaned pins (check existence), @memory typos (skip invalid), attachments lost (ephemeral), restart clears pins (by design) |
| **Database Path** | UI and Conversation.py using different databases (ensure both use `storage/users/pkb.sqlite`) |
| **Numpy Arrays** | Truthiness check fails for arrays (use `is not None` instead of `if arr:`) |

---

## Invariants to Maintain

| Category | Invariant |
|----------|-----------|
| **Data Sync** | FTS tables sync via triggers; delete embedding on statement edit |
| **Transactions** | Multi-table ops wrapped in `db.transaction()`; edit updates `updated_at` |
| **Soft Delete** | Claims: `status='retracted'` + `retracted_at` (never hard-delete) |
| **Tags** | Tag parents pass `_validate_no_cycle()` check |
| **Conflicts** | Min 2 members; all claims same `user_email`; status → `contested` |
| **Multi-User (v2)** | CRUD scoped by `user_email`; unique constraints per-user; auto-set on create |
| **Pinning (v0.4)** | Global: `meta_json.pinned`; Conversation: server memory (ephemeral); clear pending on send |
| **Context Priority** | Dedupe: referenced > attached > global > conversation > auto |
| **Database Path** | server.py and Conversation.py must use same path: `storage/users/pkb.sqlite` |
| **Numpy Checks** | Use `if arr is not None:` for numpy arrays, never `if arr:` |

---

## Logging

```python
logging.getLogger("truth_management_system").setLevel(logging.DEBUG)  # Or .search, .llm_helpers
```

**Key logs:** database (connection), claims (CRUD), fts_search (queries), embedding_search (similarity), hybrid_search (strategy times)

**Guaranteed Visibility with time_logger**

For debugging PKB search issues, the search modules use `time_logger` from `common.py` instead of standard module loggers. This ensures logs appear in the server output regardless of logging configuration:

```python
# In search modules (fts_search.py, embedding_search.py, hybrid_search.py):
try:
    from common import time_logger
except ImportError:
    time_logger = logger  # Fallback to module logger

# Usage - guaranteed to appear in server logs:
time_logger.info(f"[FTS] Query returned {len(rows)} rows")
time_logger.info(f"[HYBRID] Strategy {name} returned {len(results)} results")
time_logger.info(f"[EMBEDDING] Got {len(candidates)} candidate claims")
```

**Log Prefixes:**
- `[PKB]` - Conversation.py PKB context retrieval
- `[FTS]` - Full-text search operations
- `[EMBEDDING]` - Embedding search operations  
- `[HYBRID]` - Hybrid search orchestration
