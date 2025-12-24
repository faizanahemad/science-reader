# PKB v0 Implementation Guide

Technical documentation for the Personal Knowledge Base (PKB) module implementation.

## Overview

PKB v0 is a SQLite-backed personal knowledge base designed for integration with LLM chatbot applications. It provides structured storage for claims (atomic memory units), notes, entities, and tags with full-text search and embedding-based semantic search capabilities.

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
│   ├── structured_api.py    # StructuredAPI: unified CRUD + search + for_user()
│   ├── text_orchestration.py    # TextOrchestrator: NL command parsing
│   └── conversation_distillation.py  # ConversationDistiller: extract facts from chat
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
# interface/interface.html   # PKB modal, memory proposal modal
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
             ├── StructuredAPI                                         │
             ├── TextOrchestrator                                      │
             └── ConversationDistiller                                 │
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
| Claims | `edit_claim(claim_id, **patch)` | Update fields |
| Claims | `delete_claim(claim_id)` | Soft delete |
| Claims | `get_claim(claim_id)` | Get by ID |
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

---

## External Integrations

### 11. Flask Server (`server.py`)

The PKB is exposed via REST API endpoints in the main Flask server.

**Global State:**
```python
_pkb_db: PKBDatabase = None         # Shared database instance
_pkb_config: PKBConfig = None       # Configuration
_pkb_keys: dict = None              # API keys
_memory_update_plans: dict = {}     # Temporary plan storage by plan_id
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
| `/pkb/search` | POST | Search claims | Hybrid/FTS/embedding strategy |
| `/pkb/entities` | GET | List entities | For dropdown/autocomplete |
| `/pkb/tags` | GET | List tags | For dropdown/autocomplete |
| `/pkb/conflicts` | GET | List open conflicts | For conflict resolution UI |
| `/pkb/conflicts/<id>/resolve` | POST | Resolve conflict | Optional winning claim |
| `/pkb/propose_updates` | POST | Propose memory updates | ConversationDistiller integration |
| `/pkb/execute_updates` | POST | Execute approved updates | From proposal plan |
| `/pkb/relevant_context` | POST | Get PKB context for LLM | Formatted claim list |

### 12. Conversation.py Integration

The `Conversation` class integrates PKB for context enrichment.

**New Methods:**
```python
def _get_pkb_context(self, user_email: str, query: str, 
                     conversation_summary: str = "", k: int = 10) -> str:
    """
    Retrieve relevant claims from PKB for LLM context injection.
    
    Called asynchronously during reply() to fetch user facts
    without blocking the main chat flow.
    
    Returns:
        Formatted string of claims like:
        "- [preference] I prefer vegetarian food
         - [fact] I live in Seattle"
    """
```

**Integration in reply():**
```python
def reply(self, ...):
    # 1. Start async PKB fetch early
    pkb_future = get_async_future(
        self._get_pkb_context,
        user_email, user_message, conversation_summary
    )
    
    # 2. Continue with other processing (in parallel)
    # ... embeddings, memory, etc. ...
    
    # 3. Get PKB context (blocks only if not ready)
    pkb_context = pkb_future.result(timeout=5.0)
    
    # 4. Inject into system prompt
    if pkb_context:
        user_info += f"\n\nRelevant user facts:\n{pkb_context}"
```

### 13. Frontend (`interface/pkb-manager.js`)

JavaScript module for PKB UI operations.

**Module Structure:**
```javascript
var PKBManager = (function() {
    // Private state
    var currentPage = 1;
    var currentFilters = {};
    
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
        
        // Memory Updates
        checkMemoryUpdates: function(summary, userMsg, assistantMsg) {...},
        showMemoryProposalModal: function(proposals) {...},
        saveSelectedProposals: function(planId, approvedIndices) {...},
        
        // UI
        openPKBModal: function() {...},
        renderClaimsList: function(claims) {...},
        // ...
    };
})();
```

**Auto-Integration in common-chat.js:**
```javascript
function sendMessageCallback() {
    // ... after sending message ...
    
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
}
```

### 14. Migration Script (`migrate_user_details.py`)

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

## Data Flow

### Adding a Claim

```
User Input
    │
    v
StructuredAPI.add_claim()
    │
    ├── [if auto_extract] LLMHelpers.extract_single()
    │       │
    │       ├── generate_tags() ────────────► code_common/call_llm
    │       ├── extract_entities() ─────────► code_common/call_llm
    │       ├── extract_spo() ──────────────► code_common/call_llm
    │       └── classify_claim_type() ──────► code_common/call_llm
    │
    ├── [if auto_extract] LLMHelpers.check_similarity()
    │       │
    │       └── get_document_embedding() ───► code_common/call_llm
    │
    v
ClaimCRUD.add()
    │
    ├── INSERT INTO claims
    ├── _get_or_create_tag() × N
    ├── INSERT INTO claim_tags
    ├── _get_or_create_entity() × N
    └── INSERT INTO claim_entities
            │
            └── [triggers] INSERT INTO claims_fts
    │
    v
ActionResult { success, claim, warnings }
```

### Hybrid Search

```
Query String
    │
    v
HybridSearchStrategy.search()
    │
    ├── [parallel] FTSSearchStrategy.search()
    │       │
    │       └── SELECT ... FROM claims_fts MATCH ? ORDER BY bm25()
    │
    ├── [parallel] EmbeddingSearchStrategy.search()
    │       │
    │       ├── get_query_embedding() ──────► code_common/call_llm
    │       ├── EmbeddingStore.batch_get_or_compute()
    │       └── cosine_similarity() sort
    │
    v
merge_results_rrf()
    │
    └── RRF formula: score = Σ(1 / (rank + k))
    │
    v
[optional] _llm_rerank()
    │
    └── call_llm() for ranking ─────────────► code_common/call_llm
    │
    v
List[SearchResult]
```

### Conversation Distillation

```
(summary, user_msg, assistant_msg)
    │
    v
ConversationDistiller.extract_and_propose()
    │
    ├── _extract_claims_from_turn()
    │       │
    │       └── call_llm() ─────────────────► code_common/call_llm
    │               │
    │               └── Extract JSON array of candidate facts
    │
    ├── [for each candidate] _find_existing_matches()
    │       │
    │       └── StructuredAPI.search()
    │
    ├── _propose_actions()
    │       │
    │       └── Determine: add | update | retract | skip | conflict
    │
    └── _generate_confirmation_prompt()
    │
    v
MemoryUpdatePlan { candidates, proposed_actions, user_prompt }
    │
    v
[User confirms]
    │
    v
ConversationDistiller.execute_plan()
    │
    └── [for each approved] _execute_action()
            │
            ├── StructuredAPI.add_claim()
            ├── StructuredAPI.edit_claim()
            └── StructuredAPI.delete_claim()
    │
    v
DistillationResult { plan, executed, execution_results }
```

---

## Database Schema Diagram

```
                                  ┌─────────────────┐
                                  │   schema_version │
                                  │─────────────────│
                                  │ version (PK)    │
                                  │ applied_at      │
                                  └─────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                                 CLAIMS                                    │
│──────────────────────────────────────────────────────────────────────────│
│ claim_id (PK)    │ claim_type      │ statement       │ status            │
│ context_domain   │ subject_text    │ predicate       │ object_text       │
│ confidence       │ created_at      │ updated_at      │ valid_from/to     │
│ meta_json        │ retracted_at    │                 │                   │
└──────────┬───────────────────────┬─────────────────────┬─────────────────┘
           │                       │                     │
           │ 1:N                   │ M:N                 │ M:N
           │                       │                     │
           v                       v                     v
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ claim_embeddings │    │   claim_tags     │    │ claim_entities   │
│──────────────────│    │──────────────────│    │──────────────────│
│ claim_id (PK,FK) │    │ claim_id (FK)    │    │ claim_id (FK)    │
│ embedding (BLOB) │    │ tag_id (FK)      │    │ entity_id (FK)   │
│ model_name       │    │ (PK: claim,tag)  │    │ role             │
│ created_at       │    └────────┬─────────┘    │ (PK: all 3)      │
└──────────────────┘             │              └────────┬─────────┘
                                 │ M:1                   │ M:1
                                 v                       v
                      ┌──────────────────┐    ┌──────────────────┐
                      │      tags        │    │    entities      │
                      │──────────────────│    │──────────────────│
                      │ tag_id (PK)      │    │ entity_id (PK)   │
                      │ name             │    │ entity_type      │
                      │ parent_tag_id◄───┤    │ name             │
                      │ (self-ref FK)    │    │ UNIQUE(type,name)│
                      │ meta_json        │    │ meta_json        │
                      │ created/updated  │    │ created/updated  │
                      └──────────────────┘    └──────────────────┘

┌──────────────────────┐          ┌────────────────────────────┐
│ conflict_set_members │          │      conflict_sets         │
│──────────────────────│          │────────────────────────────│
│ conflict_set_id (FK) │◄─────────│ conflict_set_id (PK)       │
│ claim_id (FK)        │          │ status (open/resolved)     │
│ (PK: both)           │          │ resolution_notes           │
└──────────────────────┘          │ created/updated            │
                                  └────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                                  NOTES                                    │
│──────────────────────────────────────────────────────────────────────────│
│ note_id (PK)     │ title           │ body            │ context_domain    │
│ meta_json        │ created_at      │ updated_at      │                   │
└──────────┬───────────────────────────────────────────────────────────────┘
           │
           │ 1:N
           v
┌──────────────────┐
│ note_embeddings  │
│──────────────────│
│ note_id (PK,FK)  │
│ embedding (BLOB) │
│ model_name       │
│ created_at       │
└──────────────────┘

┌─────────────────────────────────────────┐
│           FTS5 Virtual Tables            │
│─────────────────────────────────────────│
│ claims_fts: statement, predicate,       │
│             object_text, subject_text,  │
│             context_domain              │
│                                         │
│ notes_fts: title, body, context_domain  │
└─────────────────────────────────────────┘
```

---

## Parallelization Points

The system uses `ParallelExecutor` from `utils.py` for concurrent operations:

| Operation | Location | What's Parallelized |
|-----------|----------|---------------------|
| Hybrid Search | `hybrid_search.py` | Multiple search strategies |
| Batch Extraction | `llm_helpers.py` | Tag/entity/SPO extraction per statement |
| Embedding Computation | `embedding_search.py` | Multiple claim embeddings |
| Similarity Check | `llm_helpers.py` | Embedding comparisons |

---

## Extension Points

### Adding a New Search Strategy

1. Create `search/my_strategy.py`
2. Inherit from `SearchStrategy` ABC
3. Implement `search(query, k, filters)` and `name()`
4. Register in `HybridSearchStrategy.__init__`

### Adding a New Claim Type

1. Add to `ClaimType` enum in `constants.py`
2. Update LLM prompts in `llm_helpers.py` if needed
3. Update `text_orchestration.py` parsing prompts

### Adding a New Entity Type

1. Add to `EntityType` enum in `constants.py`
2. Update entity extraction prompts in `llm_helpers.py`

### Adding Database Columns

1. Update model dataclass in `models.py`
2. Update `*_COLUMNS` constant
3. Update DDL in `schema.py`
4. Increment `SCHEMA_VERSION`
5. Add migration logic (future: migrations module)

---

## Testing

Run tests with pytest:

```bash
cd truth_management_system
pytest tests/ -v
```

**Test Files:**
- `test_crud.py`: Tests CRUD operations with in-memory DB
- `test_search.py`: Tests FTS and search filters
- `test_interface.py`: Tests StructuredAPI methods

**Test Patterns:**
- Each test uses a fresh in-memory SQLite database (`:memory:`)
- Fixtures create isolated `PKBDatabase` instances per test
- Unique identifiers (UUIDs) used to prevent test interference

---

## Key Design Decisions

These decisions inform how the system behaves and should be understood before making changes:

| Decision | Rationale | Impact |
|----------|-----------|--------|
| **FTS as Backbone** | FTS/BM25 (S2) is the default, deterministic retrieval method | LLM-based methods supplement, not replace FTS |
| **Embeddings as BLOBs** | Store in separate `claim_embeddings` table for efficient vector search | Embeddings can be recomputed; invalidated on statement change |
| **Contested Claims with Warnings** | Always return in search results but with warnings | Users see conflicts; prefer `active` in ranking |
| **Soft Deletes Only** | Never hard-delete claims; use `status='retracted'` + `retracted_at` | Preserves history and conflict set integrity |
| **Propose-First Distillation** | Conversation distillation proposes changes, requires user confirmation | No silent memory writes; user stays in control |
| **Enums over Magic Strings** | All allowed values in `constants.py` | Prevents typos; enables IDE autocomplete |
| **Transaction Safety** | All multi-step operations wrapped in `db.transaction()` | Atomicity for linked inserts (claim + tags + entities) |
| **FTS Sync Invariant** | Every CRUD operation on claims/notes syncs to FTS tables | Search reliability; handled by SQLite triggers |
| **Extensibility via meta_json** | Non-core fields stored in JSON to avoid migrations | Future fields don't require schema changes |
| **LLM via call_llm.py** | Single integration point for all LLM calls | Consistent error handling; easy to swap models |

---

## Potential Challenges and Mitigations

Known issues and how the system handles them:

| Challenge | Risk | Mitigation |
|-----------|------|------------|
| **FTS Sync Drift** | Search becomes unreliable if FTS tables diverge from source tables | Sync in same transaction; SQLite triggers enforce consistency |
| **Tag Hierarchy Cycles** | Infinite loops in hierarchical filtering | `_validate_no_cycle()` in TagCRUD before any parent assignment |
| **Embedding Staleness** | Old embeddings return wrong results after statement edit | Delete embedding when `statement` changes in `edit_claim()` |
| **LLM Non-Determinism** | Same query yields different results | Log all prompts/outputs; use temperature=0.0 for extraction |
| **SQLite Single-Writer** | Concurrent writes block | WAL mode enabled; readers don't block; designed for single-user |
| **Near-Duplicate Claims** | Memory pollution with repetitions | `check_similarity()` before `add_claim()` in auto mode; warns user |
| **Privacy Leakage** | Sensitive facts exposed in wrong context | `meta_json.visibility` field; future: add policy gating |
| **Schema Regret** | Need provenance/versioning later | Soft delete preserved; `meta_json` extensible; conflict sets track history |

---

## Schema Verification Checklist

Use this checklist to verify the schema is complete and matches requirements:

### Tables

- [x] **claims** (15 columns): claim_id, claim_type, statement, subject_text, predicate, object_text, context_domain, status, confidence, created_at, updated_at, valid_from, valid_to, meta_json, retracted_at
- [x] **notes** (7 columns): note_id, title, body, context_domain, meta_json, created_at, updated_at
- [x] **entities** (6 columns + UNIQUE): entity_id, entity_type, name, meta_json, created_at, updated_at + UNIQUE(entity_type, name)
- [x] **tags** (6 columns + UNIQUE + self-ref): tag_id, name, parent_tag_id, meta_json, created_at, updated_at + UNIQUE(name, parent_tag_id)
- [x] **claim_tags**: PK(claim_id, tag_id) + CASCADE deletes
- [x] **claim_entities**: PK(claim_id, entity_id, role) + CASCADE deletes
- [x] **conflict_sets** (5 columns): conflict_set_id, status, resolution_notes, created_at, updated_at
- [x] **conflict_set_members**: PK(conflict_set_id, claim_id) + CASCADE deletes
- [x] **claim_embeddings**: claim_id, embedding BLOB, model_name, created_at
- [x] **note_embeddings**: note_id, embedding BLOB, model_name, created_at
- [x] **schema_version**: version, applied_at

### FTS5 Virtual Tables

- [x] **claims_fts**: statement, predicate, object_text, subject_text, context_domain
- [x] **notes_fts**: title, body, context_domain

### Indexes

- [x] idx_claims_status, idx_claims_context_domain, idx_claims_claim_type
- [x] idx_claims_validity, idx_claims_predicate, idx_claims_created_at, idx_claims_updated_at
- [x] idx_notes_created_at, idx_notes_context_domain
- [x] idx_entities_name, idx_entities_type
- [x] idx_tags_name, idx_tags_parent
- [x] idx_claim_tags_tag_id (reverse lookup)
- [x] idx_claim_entities_entity_id, idx_claim_entities_role
- [x] idx_conflict_sets_status, idx_conflict_set_members_claim_id

---

## Dependencies

### Python Version

- **Python 3.9+** required (for dataclasses, type hints)

### Standard Library (built-in)

- `sqlite3` - Database operations
- `dataclasses` - Model definitions
- `json` - JSON parsing
- `uuid` - UUID generation
- `datetime` - Timestamp handling
- `concurrent.futures` - Parallelization (ThreadPoolExecutor)
- `contextlib` - Context managers
- `abc` - Abstract base classes
- `enum` - Enum types
- `logging` - Logging
- `os` - Path expansion

### External Dependencies

- **numpy** - Embedding operations (cosine similarity, array manipulation)
- **code_common/call_llm.py** - LLM integration (required for LLM features)

### Optional Dependencies

- **pytest** - Running tests

### Installation

No special installation needed for core functionality. For LLM features:

```bash
# Ensure numpy is available
pip install numpy

# code_common/call_llm.py must be in PYTHONPATH
# Typically already available in the project
```

---

## Future-Proofing Examples

### Adding a New Claim Type

```python
# 1. Add to constants.py
class ClaimType(str, Enum):
    FACT = "fact"
    MEMORY = "memory"
    # ... existing types ...
    GOAL = "goal"  # NEW: Long-term objectives

# 2. Update LLM prompt in llm_helpers.py (classify_claim_type)
claim_types = {
    # ... existing ...
    'goal': 'long-term objectives ("Become fluent in Spanish")'
}

# 3. No database changes needed - claim_type is TEXT
```

### Adding a New Search Strategy

```python
# 1. Create search/my_strategy.py
from .base import SearchStrategy, SearchResult, SearchFilters

class MySearchStrategy(SearchStrategy):
    def __init__(self, db, keys, config):
        self.db = db
        self.keys = keys
        self.config = config
    
    def name(self) -> str:
        return "my_strategy"
    
    def search(self, query: str, k: int = 20, 
               filters: SearchFilters = None) -> List[SearchResult]:
        # Your implementation
        ...

# 2. Register in hybrid_search.py __init__
self.strategies["my_strategy"] = MySearchStrategy(db, keys, config)

# 3. Use via API
api.search("query", strategy="my_strategy")
# Or include in hybrid
api.search("query", strategy="hybrid")  # Will auto-include if registered
```

### Adding Privacy/Visibility Filtering (Future)

```python
# 1. Values already defined in MetaJsonKeys
# Use: meta_json = '{"visibility": "restricted"}'

# 2. Future: Add to SearchFilters
@dataclass
class SearchFilters:
    # ... existing fields ...
    max_visibility: str = "default"  # Filter out "restricted" claims

# 3. Future: Add filter in search strategies
if filters.max_visibility:
    # Parse meta_json and filter by visibility
    sql += " AND json_extract(c.meta_json, '$.visibility') <= ?"
```

### Adding Claim Versioning (Future)

```python
# 1. Create new table (add to schema.py)
CLAIM_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS claim_versions (
    version_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    version_number INTEGER NOT NULL,
    statement TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    changed_by TEXT,  -- "user" or "system"
    meta_json TEXT,
    UNIQUE(claim_id, version_number)
);
"""

# 2. Modify ClaimCRUD.edit() to create version before update
def edit(self, claim_id: str, patch: Dict) -> Claim:
    existing = self.get(claim_id)
    if existing and 'statement' in patch:
        self._create_version(existing)  # Save old version
    # ... rest of edit logic
```

### Adding New Entity Types

```python
# 1. Add to constants.py
class EntityType(str, Enum):
    PERSON = "person"
    # ... existing ...
    EVENT = "event"      # NEW: Calendar events, milestones
    DOCUMENT = "document"  # NEW: Referenced documents

# 2. Update extraction prompt in llm_helpers.py
entity_types = ", ".join([e.value for e in EntityType])
# Prompt automatically includes new types

# 3. No database changes - entity_type is TEXT
```

---

## Invariants to Maintain

When modifying the codebase, ensure these invariants are preserved:

1. **FTS Sync**: Any operation that modifies `claims.statement` or `notes.body` must update the corresponding FTS table (handled by triggers).

2. **Embedding Invalidation**: Any operation that modifies `claims.statement` must delete the corresponding row from `claim_embeddings`.

3. **Transaction Boundaries**: Multi-table operations (e.g., add claim + link tags + link entities) must be wrapped in `db.transaction()`.

4. **Timestamp Updates**: Any edit operation must update `updated_at` to `now_iso()`.

5. **Soft Delete**: Claims are never hard-deleted; use `status='retracted'` and set `retracted_at`.

6. **Cycle Prevention**: Tag parent assignments must pass `_validate_no_cycle()` check.

7. **Conflict Set Minimum**: Conflict sets require at least 2 members; creating with fewer should raise ValueError.

8. **Contested Status**: When a claim is added to a conflict set, its status must be updated to `contested`.

---

## Logging and Debugging

### Enable Debug Logging

```python
import logging

# All PKB modules
logging.getLogger("truth_management_system").setLevel(logging.DEBUG)

# Specific modules
logging.getLogger("truth_management_system.search").setLevel(logging.DEBUG)
logging.getLogger("truth_management_system.llm_helpers").setLevel(logging.DEBUG)
```

### Key Log Points

| Module | What's Logged |
|--------|---------------|
| `database.py` | Connection events, schema initialization |
| `claims.py` | Add/edit/delete operations, embedding invalidation |
| `fts_search.py` | FTS queries and result counts |
| `embedding_search.py` | Embedding computation, similarity scores |
| `rewrite_search.py` | Query rewrites (original → keywords) |
| `hybrid_search.py` | Strategy execution times, RRF merge stats |
| `text_orchestration.py` | Parsed intents, action routing |
| `conversation_distillation.py` | Extracted candidates, match results |

### Debugging Search Issues

```python
# Enable search query logging in config
config = PKBConfig(log_search_queries=True)

# Check which strategies are available
hybrid = HybridSearchStrategy(db, keys, config)
print(hybrid.get_available_strategies())  # ['fts', 'embedding', ...]

# Test individual strategies
from truth_management_system.search import FTSSearchStrategy, SearchFilters
fts = FTSSearchStrategy(db)
results = fts.search("test query", k=10, filters=SearchFilters())
for r in results:
    print(f"{r.score:.3f} | {r.claim.statement[:50]}")
```
