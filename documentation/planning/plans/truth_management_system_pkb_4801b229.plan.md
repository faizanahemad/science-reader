---
name: Truth Management System PKB
overview: Implement a minimal Personal Knowledge Base (PKB) v0 Python package in `truth_management_system/` that provides durable claim storage backed by SQLite, with multiple search strategies (FTS, embeddings, LLM), structured CRUD APIs, text orchestration, and conversation distillation capabilities for chatbot integration.
todos:
  - id: phase0-constants
    content: "Create constants.py with enums: CLAIM_TYPES, CLAIM_STATUSES, ENTITY_TYPES, ENTITY_ROLES, CONFLICT_STATUSES, CONTEXT_DOMAINS, META_JSON_KEYS"
    status: completed
  - id: phase0-config
    content: Create config.py with PKBConfig dataclass and load_config() supporting file/env/dict
    status: completed
  - id: phase0-utils
    content: Create utils.py with UUID gen, timestamp helpers, JSON validators, parallel executor wrapper
    status: completed
  - id: phase0-models
    content: Create models.py with Claim, Note, Entity, Tag, ConflictSet, ClaimEntity, ClaimTag dataclasses + to_dict/from_row methods
    status: completed
  - id: phase0-schema
    content: Create schema.py with full SQLite DDL (10 tables + FTS5 + claim_embeddings + all indexes + unique constraints)
    status: completed
  - id: phase0-database
    content: Create database.py with PKBDatabase class (connect, WAL mode, initialize_schema, transaction context manager)
    status: completed
  - id: phase0-crud-base
    content: Create crud/base.py with BaseCRUD abstract class for shared CRUD patterns + FTS sync helpers
    status: completed
  - id: phase0-crud-claims
    content: Create crud/claims.py with ClaimCRUD (add/edit/delete/get/list/get_by_entity/get_by_tag) + auto FTS sync
    status: completed
  - id: phase0-crud-notes
    content: Create crud/notes.py with NoteCRUD (add/edit/delete/get/list) + auto FTS sync
    status: completed
  - id: phase0-crud-entities
    content: Create crud/entities.py with EntityCRUD (add/edit/delete/get/list/get_or_create/find_by_name)
    status: completed
  - id: phase0-crud-tags
    content: Create crud/tags.py with TagCRUD (add/edit/delete/get/list/get_hierarchy/validate_no_cycles)
    status: completed
  - id: phase0-crud-conflicts
    content: Create crud/conflicts.py with ConflictCRUD (create/resolve/ignore/get/list/add_member/remove_member)
    status: completed
  - id: phase0-crud-links
    content: Create crud/links.py with functions for claim_tags and claim_entities join table management
    status: completed
  - id: phase1-search-base
    content: Create search/base.py with SearchStrategy ABC, SearchResult dataclass, merge/dedup utilities
    status: completed
  - id: phase1-fts-search
    content: Create search/fts_search.py implementing FTSSearchStrategy with BM25 ranking + validity filtering
    status: completed
  - id: phase1-embedding-search
    content: Create search/embedding_search.py with EmbeddingSearchStrategy + EmbeddingStore (compute/cache/batch)
    status: completed
  - id: phase1-rewrite-search
    content: Create search/rewrite_search.py with RewriteSearchStrategy (S4) + logging of rewrites
    status: completed
  - id: phase1-mapreduce-search
    content: Create search/mapreduce_search.py with MapReduceSearchStrategy (S1) + batching + context limits
    status: completed
  - id: phase1-hybrid-search
    content: Create search/hybrid_search.py with parallel strategy execution, RRF merging, optional LLM rerank
    status: completed
  - id: phase1-notes-search
    content: Create search/notes_search.py for searching notes (FTS + embedding) separate from claims
    status: completed
  - id: phase2-llm-helpers
    content: Create llm_helpers.py with parallel LLM extraction functions (tags, entities, SPO, claim_type, similarity)
    status: completed
  - id: phase2-structured-api
    content: Create interface/structured_api.py with StructuredAPI class (full CRUD for all types + search)
    status: completed
  - id: phase2-text-orchestration
    content: Create interface/text_orchestration.py with TextOrchestrator (NL parsing + action routing + logging)
    status: completed
  - id: phase2-conversation-distillation
    content: Create interface/conversation_distillation.py with ConversationDistiller (extract + propose + execute)
    status: completed
  - id: package-init
    content: Create all __init__.py files with proper exports and convenience factory functions
    status: completed
  - id: phase3-tests
    content: Create tests/ folder with unit tests for CRUD, search, and interface layers
    status: completed
---

# Truth Management System (PKB v0) Implementation Plan

## Goals and Objectives

Build a **local-first "claim store"** backed by a single SQLite file that enables:

1. **CRUD operations** on claims, notes, entities, tags, and conflict sets
2. **Four interchangeable search strategies**: FTS/BM25, embedding similarity, LLM rewrite→FTS, LLM map-reduce
3. **Structured API** for UI/agent integration (add/edit/delete/search)
4. **Text orchestration API** for natural language commands
5. **Conversation distillation** to extract and manage facts from chat turns

---

## Package Structure

```javascript
truth_management_system/
├── __init__.py                      # Package exports + factory functions
├── constants.py                     # Enums and allowed values
├── config.py                        # Configuration management (db_path, settings)
├── utils.py                         # UUID gen, timestamps, validators, parallel helpers
├── models.py                        # Data models (Claim, Note, Entity, Tag, etc.)
├── schema.py                        # SQLite schema DDL & migrations
├── database.py                      # Database connection, setup, transactions
├── crud/
│   ├── __init__.py
│   ├── base.py                      # BaseCRUD abstract class + FTS sync helpers
│   ├── claims.py                    # ClaimCRUD + FTS sync
│   ├── notes.py                     # NoteCRUD + FTS sync
│   ├── entities.py                  # EntityCRUD
│   ├── tags.py                      # TagCRUD (with hierarchy validation)
│   ├── conflicts.py                 # ConflictCRUD operations
│   └── links.py                     # claim_tags, claim_entities join management
├── search/
│   ├── __init__.py
│   ├── base.py                      # SearchStrategy ABC, SearchResult, merge utils
│   ├── fts_search.py                # S2: FTS/BM25 search
│   ├── embedding_search.py          # S3: Embedding similarity + storage
│   ├── rewrite_search.py            # S4: LLM rewrite → FTS
│   ├── mapreduce_search.py          # S1: LLM map-reduce ranking
│   ├── hybrid_search.py             # Combined strategies + parallel exec + reranking
│   └── notes_search.py              # Notes-specific search (FTS + embedding)
├── interface/
│   ├── __init__.py
│   ├── structured_api.py            # Structured CRUD + search API
│   ├── text_orchestration.py        # NL → action router + logging
│   └── conversation_distillation.py # Extract facts from chat
├── llm_helpers.py                   # Tag/keyword/entity extraction (parallelized)
└── tests/                           # Unit tests
    ├── __init__.py
    ├── test_crud.py
    ├── test_search.py
    └── test_interface.py
```

---

## Phase 0: Storage Kernel

### Task 0.0: Constants (`constants.py`)

Centralized enums to avoid magic strings:

```python
from enum import Enum

class ClaimType(str, Enum):
    FACT = "fact"
    MEMORY = "memory"
    DECISION = "decision"
    PREFERENCE = "preference"
    TASK = "task"
    REMINDER = "reminder"
    HABIT = "habit"
    OBSERVATION = "observation"

class ClaimStatus(str, Enum):
    ACTIVE = "active"
    CONTESTED = "contested"        # In default search WITH warnings
    HISTORICAL = "historical"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    DRAFT = "draft"
    
    @classmethod
    def default_search_statuses(cls): return [cls.ACTIVE.value, cls.CONTESTED.value]

class EntityType(str, Enum):
    PERSON = "person"
    ORG = "org"
    PLACE = "place"
    TOPIC = "topic"
    PROJECT = "project"
    SYSTEM = "system"
    OTHER = "other"

class EntityRole(str, Enum):
    SUBJECT = "subject"
    OBJECT = "object"
    MENTIONED = "mentioned"
    ABOUT_PERSON = "about_person"

class ConflictStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"

class ContextDomain(str, Enum):
    PERSONAL = "personal"
    HEALTH = "health"
    RELATIONSHIPS = "relationships"
    LEARNING = "learning"
    LIFE_OPS = "life_ops"
    WORK = "work"
    FINANCE = "finance"

# meta_json standard keys (documented, not enforced)
class MetaJsonKeys:
    KEYWORDS = "keywords"      # List[str]
    SOURCE = "source"          # "manual"|"chat_distillation"|"import"
    VISIBILITY = "visibility"  # "default"|"restricted"|"shareable"
    LLM = "llm"               # {model, prompt_version, confidence_notes}
```



### Task 0.1: Configuration (`config.py`)

```python
@dataclass
class PKBConfig:
    # Database
    db_path: str = "~/.pkb/kb.sqlite"
    
    # Feature toggles
    fts_enabled: bool = True
    embedding_enabled: bool = True
    
    # Search defaults (from requirements)
    default_k: int = 20
    include_contested_by_default: bool = True
    validity_filter_default: bool = False  # Show everything unless filtered
    
    # LLM settings
    llm_model: str = "openai/gpt-4o-mini"
    embedding_model: str = "openai/text-embedding-3-small"
    llm_temperature: float = 0.0
    
    # Parallelization
    max_parallel_llm_calls: int = 8
    max_parallel_embedding_calls: int = 16
    
    # Logging
    log_llm_calls: bool = True
    log_search_queries: bool = True
    
    def expand_db_path(self) -> str:
        return os.path.expanduser(os.path.expandvars(self.db_path))

def load_config(
    config_dict: Optional[Dict] = None,
    config_file: Optional[str] = None,
    env_prefix: str = "PKB_"
) -> PKBConfig:
    """Load from: dict > file > env vars > defaults."""
    ...
```



### Task 0.1b: Utilities (`utils.py`)

```python
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, List, TypeVar
T = TypeVar('T')

# UUID Generation
def generate_uuid() -> str: ...

# Timestamp Helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def epoch_iso() -> str:
    return "1970-01-01T00:00:00Z"

def is_valid_iso_timestamp(ts: str) -> bool: ...

# JSON Validators
def is_valid_json(s: Optional[str]) -> bool: ...
def parse_meta_json(s: Optional[str]) -> Dict: ...
def update_meta_json(existing: Optional[str], updates: Dict) -> str: ...

# Parallel Execution (like call_llm.py pattern)
class ParallelExecutor:
    def __init__(self, max_workers: int = 8):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    
    def map_parallel(self, fn: Callable[..., T], items: List, timeout: float = 60.0) -> List[T]:
        """Execute fn on each item in parallel, return results in order."""
        futures = [self.executor.submit(fn, item) for item in items]
        return [f.result(timeout=timeout) for f in futures]
    
    def submit_all(self, tasks: List[Callable]) -> List[Future]:
        """Submit multiple independent tasks."""
        return [self.executor.submit(task) for task in tasks]

def get_parallel_executor(max_workers: int = 8) -> ParallelExecutor: ...
```



### Task 0.2: Data Models (`models.py`)

All models include `to_dict()` for DB insertion and `from_row()` for reading:

```python
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import numpy as np
import sqlite3

# Column names for DB operations
CLAIM_COLUMNS = [
    'claim_id', 'claim_type', 'statement', 'subject_text', 'predicate', 
    'object_text', 'context_domain', 'status', 'confidence', 'created_at', 
    'updated_at', 'valid_from', 'valid_to', 'meta_json', 'retracted_at'
]

@dataclass
class Claim:
    claim_id: str
    claim_type: str      # Use ClaimType enum values
    statement: str
    context_domain: str  # Use ContextDomain enum values
    status: str = "active"
    subject_text: Optional[str] = None
    predicate: Optional[str] = None
    object_text: Optional[str] = None
    confidence: Optional[float] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    valid_from: str = field(default_factory=epoch_iso)
    valid_to: Optional[str] = None
    meta_json: Optional[str] = None
    retracted_at: Optional[str] = None
    
    # Computed fields (not stored in DB)
    _embedding: Optional[np.ndarray] = field(default=None, repr=False, compare=False)
    _tags: List[str] = field(default_factory=list, repr=False, compare=False)
    _entities: List[Dict] = field(default_factory=list, repr=False, compare=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for DB insert (excludes computed fields)."""
        return {k: getattr(self, k) for k in CLAIM_COLUMNS}
    
    def to_insert_tuple(self) -> tuple:
        """Return tuple for SQL INSERT."""
        return tuple(getattr(self, k) for k in CLAIM_COLUMNS)
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Claim':
        """Create from SQLite row."""
        return cls(**{k: row[k] for k in CLAIM_COLUMNS if k in row.keys()})
    
    @property
    def is_contested(self) -> bool:
        return self.status == ClaimStatus.CONTESTED.value

@dataclass
class Note:
    note_id: str
    body: str
    title: Optional[str] = None
    context_domain: Optional[str] = None
    meta_json: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    
    def to_dict(self) -> Dict: ...
    @classmethod
    def from_row(cls, row) -> 'Note': ...

@dataclass
class Entity:
    entity_id: str
    entity_type: str  # Use EntityType enum
    name: str
    meta_json: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    
    def to_dict(self) -> Dict: ...
    @classmethod
    def from_row(cls, row) -> 'Entity': ...

@dataclass
class Tag:
    tag_id: str
    name: str
    parent_tag_id: Optional[str] = None
    meta_json: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    
    def to_dict(self) -> Dict: ...
    @classmethod
    def from_row(cls, row) -> 'Tag': ...

@dataclass
class ConflictSet:
    conflict_set_id: str
    status: str = "open"  # Use ConflictStatus enum
    resolution_notes: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    # Populated from join table
    member_claim_ids: List[str] = field(default_factory=list, compare=False)
    
    def to_dict(self) -> Dict: ...
    @classmethod
    def from_row(cls, row) -> 'ConflictSet': ...

# Join table models (for type safety in CRUD operations)
@dataclass
class ClaimTag:
    claim_id: str
    tag_id: str

@dataclass
class ClaimEntity:
    claim_id: str
    entity_id: str
    role: str  # Use EntityRole enum
```



### Task 0.3: Schema Definition (`schema.py`)

Complete SQLite DDL with all tables, indexes, and constraints from requirements:

```python
SCHEMA_VERSION = 1

TABLES_DDL = """
-- Claims: atomic memory units
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    claim_type TEXT NOT NULL,           -- fact|memory|decision|preference|task|reminder|habit|observation
    statement TEXT NOT NULL,
    subject_text TEXT,
    predicate TEXT,
    object_text TEXT,
    context_domain TEXT NOT NULL,       -- personal|health|relationships|learning|life_ops
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    valid_from TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    valid_to TEXT,
    meta_json TEXT,                     -- JSON: {keywords, source, visibility, llm}
    retracted_at TEXT
);

-- Notes: narrative storage
CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY,
    title TEXT,
    body TEXT NOT NULL,
    context_domain TEXT,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Entities: canonical people/topics/projects
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,          -- person|org|place|topic|project|system|other
    name TEXT NOT NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(entity_type, name)
);

-- Tags: hierarchical labels
CREATE TABLE IF NOT EXISTS tags (
    tag_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_tag_id TEXT REFERENCES tags(tag_id),
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(name, parent_tag_id)
);

-- Join: claim_tags (many-to-many)
CREATE TABLE IF NOT EXISTS claim_tags (
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (claim_id, tag_id)
);

-- Join: claim_entities (many-to-many with role)
CREATE TABLE IF NOT EXISTS claim_entities (
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    role TEXT NOT NULL,                 -- subject|object|mentioned|about_person
    PRIMARY KEY (claim_id, entity_id, role)
);

-- Conflict sets: manual contradiction buckets
CREATE TABLE IF NOT EXISTS conflict_sets (
    conflict_set_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'open', -- open|resolved|ignored
    resolution_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Conflict set members
CREATE TABLE IF NOT EXISTS conflict_set_members (
    conflict_set_id TEXT NOT NULL REFERENCES conflict_sets(conflict_set_id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    PRIMARY KEY (conflict_set_id, claim_id)
);

-- Embeddings storage (separate for efficient vector search)
CREATE TABLE IF NOT EXISTS claim_embeddings (
    claim_id TEXT PRIMARY KEY REFERENCES claims(claim_id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,
    model_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

INDEXES_DDL = """
-- Claims indexes (from requirements)
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_context_domain ON claims(context_domain);
CREATE INDEX IF NOT EXISTS idx_claims_claim_type ON claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claims_validity ON claims(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_claims_predicate ON claims(predicate);

-- Notes indexes
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at);
CREATE INDEX IF NOT EXISTS idx_notes_context_domain ON notes(context_domain);

-- Join table indexes (for reverse lookup)
CREATE INDEX IF NOT EXISTS idx_claim_tags_tag_id ON claim_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_claim_entities_entity_id ON claim_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_claim_entities_role ON claim_entities(role);
"""

FTS_DDL = """
-- FTS5 for claims (indexes: statement, predicate, object_text, context_domain, subject_text)
CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    claim_id UNINDEXED,
    statement,
    predicate,
    object_text,
    subject_text,
    context_domain,
    content='claims',
    content_rowid='rowid'
);

-- FTS5 for notes (indexes: title, body, context_domain)
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    note_id UNINDEXED,
    title,
    body,
    context_domain,
    content='notes',
    content_rowid='rowid'
);
"""

def get_all_ddl() -> str:
    return TABLES_DDL + INDEXES_DDL + FTS_DDL
```



### Task 0.4: Database Setup (`database.py`)

```python
import sqlite3
from contextlib import contextmanager

class PKBDatabase:
    """SQLite database manager with WAL mode and transaction support."""
    
    def __init__(self, config: PKBConfig):
        self.config = config
        self.db_path = config.expand_db_path()
        self._conn: Optional[sqlite3.Connection] = None
    
    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn
    
    def initialize_schema(self) -> None:
        conn = self.connect()
        conn.executescript(get_all_ddl())
        conn.commit()
    
    @contextmanager
    def transaction(self):
        """Context manager for atomic transactions."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

def get_database(config: PKBConfig) -> PKBDatabase:
    db = PKBDatabase(config)
    db.initialize_schema()
    return db
```



### Task 0.5a: Base CRUD (`crud/base.py`)

Abstract base for shared CRUD patterns:

```python
from abc import ABC, abstractmethod
from typing import TypeVar, Generic
T = TypeVar('T')

class BaseCRUD(ABC, Generic[T]):
    def __init__(self, db: PKBDatabase):
        self.db = db
    
    @abstractmethod
    def _table_name(self) -> str: ...
    @abstractmethod
    def _id_column(self) -> str: ...
    @abstractmethod
    def _to_model(self, row: sqlite3.Row) -> T: ...
    
    def get(self, id: str) -> Optional[T]:
        conn = self.db.connect()
        row = conn.execute(
            f"SELECT * FROM {self._table_name()} WHERE {self._id_column()} = ?", (id,)
        ).fetchone()
        return self._to_model(row) if row else None
    
    def list(self, filters: Dict = {}, limit: int = 100, offset: int = 0) -> List[T]: ...
    def _update_timestamp(self, data: Dict) -> Dict:
        data['updated_at'] = now_iso()
        return data

def sync_to_fts(conn, table: str, fts_table: str, id_col: str, id_val: str, op: str):
    """Sync row to FTS. op: 'insert'|'update'|'delete'"""
    ...
```



### Task 0.5b: Claims CRUD (`crud/claims.py`)

```python
class ClaimCRUD(BaseCRUD[Claim]):
    def add(self, claim: Claim, tags: List[str] = [], 
            entities: List[Dict] = []) -> Claim:
        """Add claim with tags/entities, sync FTS."""
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO claims (...) VALUES (...)", claim.to_dict())
            for tag_name in tags:
                tag_id = self._get_or_create_tag(conn, tag_name)
                conn.execute("INSERT INTO claim_tags VALUES (?,?)", (claim.claim_id, tag_id))
            for e in entities:
                entity_id = self._get_or_create_entity(conn, e)
                conn.execute("INSERT INTO claim_entities VALUES (?,?,?)",
                            (claim.claim_id, entity_id, e['role']))
            sync_to_fts(conn, "claims", "claims_fts", "claim_id", claim.claim_id, "insert")
        return claim
    
    def edit(self, claim_id: str, patch: Dict) -> Claim:
        """Update, sync FTS, invalidate embedding if statement changed."""
        ...
    
    def delete(self, claim_id: str, mode: str = "retract") -> Claim:
        return self.edit(claim_id, {'status': 'retracted', 'retracted_at': now_iso()})
    
    def get_by_entity(self, entity_id: str, role: Optional[str] = None) -> List[Claim]: ...
    def get_by_tag(self, tag_id: str) -> List[Claim]: ...
```



### Task 0.5c: Tags CRUD with Cycle Validation (`crud/tags.py`)

```python
class TagCRUD(BaseCRUD[Tag]):
    def add(self, tag: Tag) -> Tag:
        if tag.parent_tag_id:
            self._validate_no_cycle(tag.tag_id, tag.parent_tag_id)
        ...
    
    def _validate_no_cycle(self, tag_id: str, parent_id: str) -> None:
        """Raise if adding parent would create a cycle."""
        visited = {tag_id}
        current = parent_id
        while current:
            if current in visited:
                raise ValueError(f"Cycle detected")
            visited.add(current)
            parent = self.get(current)
            current = parent.parent_tag_id if parent else None
    
    def get_hierarchy(self, tag_id: str) -> List[Tag]: ...
    def get_children(self, parent_tag_id: Optional[str]) -> List[Tag]: ...
```



### Task 0.5d: Conflicts CRUD (`crud/conflicts.py`)

```python
class ConflictCRUD(BaseCRUD[ConflictSet]):
    def create(self, claim_ids: List[str], notes: Optional[str] = None) -> ConflictSet:
        """Create conflict set (>= 2 members), set claims to contested."""
        if len(claim_ids) < 2:
            raise ValueError("Conflict set requires at least 2 claims")
        with self.db.transaction() as conn:
            # Insert conflict set and members
            # Update claims to status='contested'
            ...
    
    def resolve(self, conflict_set_id: str, resolution_notes: str,
                winning_claim_id: Optional[str] = None) -> ConflictSet: ...
    def ignore(self, conflict_set_id: str) -> ConflictSet: ...
    def add_member(self, conflict_set_id: str, claim_id: str) -> None: ...
```



### Task 0.5e: Links Management (`crud/links.py`)

```python
def link_claim_tag(db, claim_id: str, tag_id: str) -> None: ...
def unlink_claim_tag(db, claim_id: str, tag_id: str) -> None: ...
def link_claim_entity(db, claim_id: str, entity_id: str, role: str) -> None: ...
def get_claim_tags(db, claim_id: str) -> List[Tag]: ...
def get_claim_entities(db, claim_id: str) -> List[Tuple[Entity, str]]: ...
```

---

## Phase 1: Retrieval Strategies

### Task 1.0: Search Base (`search/base.py`)

Strategy pattern for interchangeable search:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

@dataclass
class SearchFilters:
    """Filters applicable to all search strategies."""
    statuses: List[str] = field(default_factory=lambda: ClaimStatus.default_search_statuses())
    context_domains: Optional[List[str]] = None
    claim_types: Optional[List[str]] = None
    tag_ids: Optional[List[str]] = None
    entity_ids: Optional[List[str]] = None
    valid_at: Optional[str] = None  # Filter to claims valid at this timestamp
    include_contested: bool = True

@dataclass
class SearchResult:
    """Unified search result with metadata."""
    claim: Claim
    score: float
    source: str  # 'fts'|'embedding'|'rewrite'|'mapreduce'|'llm_rerank'
    is_contested: bool
    warnings: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if self.is_contested:
            self.warnings.append("This claim is contested and may conflict with other claims.")

class SearchStrategy(ABC):
    """Abstract base for search strategies."""
    
    @abstractmethod
    def search(self, query: str, k: int, filters: SearchFilters) -> List[SearchResult]: ...
    
    @abstractmethod
    def name(self) -> str: ...

def merge_results(result_lists: List[List[SearchResult]], k: int) -> List[SearchResult]:
    """Merge results from multiple strategies using Reciprocal Rank Fusion (RRF)."""
    ...

def dedupe_results(results: List[SearchResult]) -> List[SearchResult]:
    """Remove duplicates, keep highest score."""
    ...
```



### Task 1.1: FTS/BM25 Search (`search/fts_search.py`) - S2

```python
class FTSSearchStrategy(SearchStrategy):
    """BM25 ranking via SQLite FTS5. Fast, deterministic baseline."""
    
    def __init__(self, db: PKBDatabase):
        self.db = db
    
    def name(self) -> str: return "fts"
    
    def search(self, query: str, k: int = 20, 
               filters: SearchFilters = SearchFilters()) -> List[SearchResult]:
        """
    1. Build FTS5 MATCH query
    2. Apply filters via JOIN/WHERE
    3. Return BM25-ranked results
        """
        conn = self.db.connect()
        # Use bm25() function for scoring
        sql = """
            SELECT c.*, bm25(claims_fts) as score
            FROM claims_fts
            JOIN claims c ON claims_fts.claim_id = c.claim_id
            WHERE claims_fts MATCH ?
              AND c.status IN ({statuses})
              {domain_filter}
              {type_filter}
            ORDER BY score
            LIMIT ?
        """
        ...
```



### Task 1.2: Embedding Search (`search/embedding_search.py`) - S3

```python
class EmbeddingStore:
    """Manage claim embeddings with caching and batch computation."""
    
    def __init__(self, db: PKBDatabase, keys: Dict[str, str], config: PKBConfig):
        self.db = db
        self.keys = keys
        self.executor = get_parallel_executor(config.max_parallel_embedding_calls)
    
    def get_embedding(self, claim_id: str) -> Optional[np.ndarray]:
        """Get cached embedding or None."""
        ...
    
    def compute_and_store(self, claim: Claim) -> np.ndarray:
        """Compute embedding using get_document_embedding(), store in DB."""
        from code_common.call_llm import get_document_embedding
        embedding = get_document_embedding(claim.statement, self.keys)
        self._store(claim.claim_id, embedding)
        return embedding
    
    def ensure_embeddings(self, claim_ids: List[str]) -> None:
        """Batch compute embeddings for claims missing them (PARALLEL)."""
        missing = [cid for cid in claim_ids if self.get_embedding(cid) is None]
        if missing:
            claims = [self.db.crud.claims.get(cid) for cid in missing]
            # Parallel embedding computation
            self.executor.map_parallel(self.compute_and_store, claims)

class EmbeddingSearchStrategy(SearchStrategy):
    """Cosine similarity search over claim embeddings."""
    
    def __init__(self, db: PKBDatabase, keys: Dict[str, str], config: PKBConfig):
        self.db = db
        self.keys = keys
        self.store = EmbeddingStore(db, keys, config)
    
    def name(self) -> str: return "embedding"
    
    def search(self, query: str, k: int = 20,
               filters: SearchFilters = SearchFilters()) -> List[SearchResult]:
        from code_common.call_llm import get_query_embedding
        query_emb = get_query_embedding(query, self.keys)
        
        # Get all candidate claim embeddings
        candidates = self._get_filtered_claims(filters)
        self.store.ensure_embeddings([c.claim_id for c in candidates])
        
        # Compute cosine similarities
        scores = []
        for claim in candidates:
            emb = self.store.get_embedding(claim.claim_id)
            sim = np.dot(query_emb, emb) / (np.linalg.norm(query_emb) * np.linalg.norm(emb))
            scores.append((claim, float(sim)))
        
        # Sort and return top-k
        scores.sort(key=lambda x: x[1], reverse=True)
        return [SearchResult(c, s, "embedding", c.status == "contested") 
                for c, s in scores[:k]]
```



### Task 1.3: LLM Rewrite → FTS (`search/rewrite_search.py`) - S4

```python
@dataclass
class RewriteMetadata:
    original_query: str
    rewritten_query: str
    extracted_keywords: List[str]
    extracted_tags: List[str]
    llm_model: str

class RewriteSearchStrategy(SearchStrategy):
    """LLM rewrites query into keywords/tags, then runs FTS."""
    
    def __init__(self, db: PKBDatabase, keys: Dict[str, str], config: PKBConfig):
        self.db = db
        self.keys = keys
        self.fts = FTSSearchStrategy(db)
        self.config = config
    
    def name(self) -> str: return "rewrite"
    
    def search(self, query: str, k: int = 20,
               filters: SearchFilters = SearchFilters()) -> Tuple[List[SearchResult], RewriteMetadata]:
        # 1. LLM rewrites query
        from code_common.call_llm import call_llm
        rewrite_prompt = f"""
        Rewrite this query into search keywords for a personal knowledge base.
        Extract: keywords (1-3 words each), relevant tags, entities mentioned.
        Return JSON: {{"keywords": [...], "tags": [...], "entities": [...]}}
        
        Query: {query}
        """
        response = call_llm(self.keys, self.config.llm_model, rewrite_prompt, 
                           temperature=0.0)
        parsed = json.loads(response)
        
        # 2. Build enhanced FTS query
        rewritten = " OR ".join(parsed['keywords'])
        
        # 3. Run FTS with rewritten query
        results = self.fts.search(rewritten, k, filters)
        
        # 4. Return with metadata (for logging/debugging)
        metadata = RewriteMetadata(
            original_query=query,
            rewritten_query=rewritten,
            extracted_keywords=parsed['keywords'],
            extracted_tags=parsed.get('tags', []),
            llm_model=self.config.llm_model
        )
        
        # Log for debugging (requirements: log all LLM rewrites)
        if self.config.log_llm_calls:
            logger.info(f"Rewrite: {query} -> {rewritten}")
        
        return results, metadata
```



### Task 1.4: LLM Map-Reduce (`search/mapreduce_search.py`) - S1

```python
class MapReduceSearchStrategy(SearchStrategy):
    """LLM scores/ranks candidate claims. Expensive but nuanced."""
    
    def __init__(self, db: PKBDatabase, keys: Dict[str, str], config: PKBConfig):
        self.db = db
        self.keys = keys
        self.config = config
        self.executor = get_parallel_executor(config.max_parallel_llm_calls)
    
    def name(self) -> str: return "mapreduce"
    
    def search(self, query: str, k: int = 20,
               filters: SearchFilters = SearchFilters(),
               candidate_pool_size: int = 100) -> List[SearchResult]:
        # 1. Get candidate pool (FTS or embedding pre-filter)
        fts = FTSSearchStrategy(self.db)
        candidates = fts.search(query, k=candidate_pool_size, filters=filters)
        
        # 2. Batch claims for LLM scoring (respect context limits)
        batch_size = 20  # ~20 claims per LLM call
        batches = [candidates[i:i+batch_size] for i in range(0, len(candidates), batch_size)]
        
        # 3. PARALLEL LLM scoring
        def score_batch(batch: List[SearchResult]) -> List[Tuple[str, float]]:
            claims_text = "\n".join([f"[{r.claim.claim_id}] {r.claim.statement}" for r in batch])
            prompt = f"""
            Score each claim's relevance to the query (0.0-1.0).
            Return JSON: [{{"id": "...", "score": 0.8, "reason": "..."}}]
            
            Query: {query}
            Claims:
            {claims_text}
            """
            response = call_llm(self.keys, self.config.llm_model, prompt, temperature=0.0)
            return json.loads(response)
        
        all_scores = []
        score_results = self.executor.map_parallel(score_batch, batches)
        for batch_scores in score_results:
            all_scores.extend(batch_scores)
        
        # 4. Merge scores and return top-k
        ...
```



### Task 1.5: Hybrid Search (`search/hybrid_search.py`)

Key feature: **Parallel execution** of independent search strategies.

```python
class HybridSearchStrategy:
    """Combines multiple strategies with parallel execution and RRF merging."""
    
    def __init__(self, db: PKBDatabase, keys: Dict[str, str], config: PKBConfig):
        self.db = db
        self.keys = keys
        self.config = config
        self.executor = get_parallel_executor(config.max_parallel_llm_calls)
        
        # Initialize all strategies
        self.strategies = {
            "fts": FTSSearchStrategy(db),
            "embedding": EmbeddingSearchStrategy(db, keys, config),
            "rewrite": RewriteSearchStrategy(db, keys, config),
            "mapreduce": MapReduceSearchStrategy(db, keys, config),
        }
    
    def search(
        self,
        query: str,
        strategy_names: List[str] = ["fts", "embedding"],
        k: int = 20,
        filters: SearchFilters = SearchFilters(),
        llm_rerank: bool = False,
        llm_rerank_top_n: int = 50,
    ) -> List[SearchResult]:
        """
    1. Run selected strategies IN PARALLEL
    2. Merge using Reciprocal Rank Fusion (RRF)
    3. Optionally LLM-rerank top candidates
    4. Always mark contested claims with warnings
        """
        # PARALLEL execution of strategies
        def run_strategy(name: str) -> List[SearchResult]:
            return self.strategies[name].search(query, k=k*2, filters=filters)
        
        # Submit all strategy searches in parallel
        futures = {name: self.executor.submit(run_strategy, name) 
                   for name in strategy_names if name in self.strategies}
        
        # Collect results
        all_results = []
        for name, future in futures.items():
            results = future.result(timeout=30.0)
            for r in results:
                r.source = name  # Tag with source
            all_results.append(results)
        
        # Merge using RRF
        merged = self._rrf_merge(all_results, k=llm_rerank_top_n if llm_rerank else k)
        
        # Optional LLM reranking
        if llm_rerank and len(merged) > 0:
            merged = self._llm_rerank(query, merged, k)
        
        return merged[:k]
    
    def _rrf_merge(self, result_lists: List[List[SearchResult]], k: int = 60) -> List[SearchResult]:
        """Reciprocal Rank Fusion: score = sum(1/(rank + 60)) across lists."""
        scores = {}  # claim_id -> (SearchResult, total_score, sources)
        
        for results in result_lists:
            for rank, result in enumerate(results):
                cid = result.claim.claim_id
                rrf_score = 1.0 / (rank + 60)
                
                if cid in scores:
                    scores[cid][1] += rrf_score
                    scores[cid][2].append(result.source)
                else:
                    scores[cid] = [result, rrf_score, [result.source]]
        
        # Sort by combined score
        sorted_items = sorted(scores.values(), key=lambda x: x[1], reverse=True)
        
        # Build final results
        final = []
        for result, score, sources in sorted_items[:k]:
            result.score = score
            result.sources = list(set(sources))
            final.append(result)
        
        return final
    
    def _llm_rerank(self, query: str, results: List[SearchResult], k: int) -> List[SearchResult]:
        """Use LLM to rerank top candidates."""
        ...
```



### Task 1.6: Notes Search (`search/notes_search.py`)

```python
class NotesSearchStrategy:
    """Search notes separately from claims (FTS + optional embedding)."""
    
    def search_fts(self, query: str, k: int = 20) -> List[Note]: ...
    def search_embedding(self, query: str, keys: Dict, k: int = 20) -> List[Note]: ...
```

---

## Phase 2: Interface Layer

### Task 2.1: LLM Helpers (`llm_helpers.py`)

All extraction functions support **parallel execution** for batch processing:

```python
from concurrent.futures import Future
from code_common.call_llm import call_llm, getKeywordsFromText

class LLMHelpers:
    """LLM-powered extraction with parallelization support."""
    
    def __init__(self, keys: Dict[str, str], config: PKBConfig):
        self.keys = keys
        self.config = config
        self.executor = get_parallel_executor(config.max_parallel_llm_calls)
    
    def generate_tags(self, statement: str, context_domain: str,
                      existing_tags: List[str] = []) -> List[str]:
        """Use LLM to suggest relevant tags for a claim."""
        # Also use getKeywordsFromText for initial extraction
        keywords = getKeywordsFromText(statement, self.keys)
        
        prompt = f"""
        Suggest 3-5 tags for this claim from a personal knowledge base.
        Context domain: {context_domain}
        Existing tags in system: {existing_tags[:20]}
        Extracted keywords: {keywords}
        
        Claim: {statement}
        
        Return JSON: {{"tags": ["tag1", "tag2", ...]}}
        """
        response = call_llm(self.keys, self.config.llm_model, prompt, temperature=0.0)
        return json.loads(response)['tags']
    
    def extract_entities(self, statement: str) -> List[Dict[str, str]]:
        """Extract {entity_type, name, role} tuples from statement."""
        prompt = f"""
        Extract entities from this claim.
        Entity types: person, org, place, topic, project, system, other
        Roles: subject, object, mentioned, about_person
        
        Claim: {statement}
        
        Return JSON: [{{"type": "person", "name": "Mom", "role": "subject"}}]
        """
        response = call_llm(self.keys, self.config.llm_model, prompt, temperature=0.0)
        return json.loads(response)
    
    def extract_spo(self, statement: str) -> Dict[str, Optional[str]]:
        """Extract subject/predicate/object structure if possible."""
        ...
    
    def classify_claim_type(self, statement: str) -> str:
        """Classify into fact|memory|decision|preference|task|reminder|habit|observation."""
        prompt = f"""
        Classify this claim into one type:
    - fact: stable assertions ("My home city is Bengaluru")
    - memory: episodic ("I enjoyed that restaurant")
    - decision: commitments ("I decided to avoid X")
    - preference: likes/dislikes ("I prefer morning workouts")
    - task: actionable ("Buy medication")
    - reminder: future prompt ("Remind me to call mom Friday")
    - habit: recurring target ("Sleep by 11pm")
    - observation: low-commitment notes ("Noticed knee pain")
        
        Claim: {statement}
        
        Return JSON: {{"type": "preference"}}
        """
        response = call_llm(self.keys, self.config.llm_model, prompt, temperature=0.0)
        return json.loads(response)['type']
    
    def check_similarity(self, new_claim: str, existing_claims: List[Claim],
                         threshold: float = 0.85) -> List[Tuple[Claim, float, str]]:
        """Find similar claims. Returns (claim, similarity, relation)."""
        from code_common.call_llm import get_query_embedding, get_document_embedding
        
        new_emb = get_query_embedding(new_claim, self.keys)
        results = []
        
        for claim in existing_claims:
            claim_emb = get_document_embedding(claim.statement, self.keys)
            sim = np.dot(new_emb, claim_emb) / (np.linalg.norm(new_emb) * np.linalg.norm(claim_emb))
            
            if sim >= threshold:
                relation = self._classify_relation(new_claim, claim.statement, sim)
                results.append((claim, float(sim), relation))
        
        return sorted(results, key=lambda x: x[1], reverse=True)
    
    def _classify_relation(self, new: str, existing: str, sim: float) -> str:
        """Classify as 'duplicate'|'related'|'contradicts'."""
        if sim > 0.95:
            return "duplicate"
        # Use LLM to check for contradiction
        ...
    
    # PARALLEL batch processing
    def batch_extract_all(self, statements: List[str]) -> List[Dict]:
        """Extract tags, entities, SPO, type for multiple statements IN PARALLEL."""
        def extract_one(stmt: str) -> Dict:
            return {
                "tags": self.generate_tags(stmt, "personal"),
                "entities": self.extract_entities(stmt),
                "spo": self.extract_spo(stmt),
                "type": self.classify_claim_type(stmt),
            }
        
        return self.executor.map_parallel(extract_one, statements)
```



### Task 2.2: Structured API (`interface/structured_api.py`)

```python
@dataclass
class ActionResult:
    success: bool
    action: str  # add|edit|delete|search|create_conflict|resolve_conflict
    object_type: str  # claim|note|entity|tag|conflict_set
    object_id: Optional[str]
    data: Any
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

class StructuredAPI:
    def __init__(self, db: PKBDatabase, keys: Dict[str, str], config: PKBConfig): ...
    
    # Claims
    def add_claim(self, statement: str, claim_type: str, context_domain: str,
                  tags: List[str] = [], entities: List[Dict] = [],
                  auto_extract: bool = True, **kwargs) -> ActionResult: ...
    def edit_claim(self, claim_id: str, **patch) -> ActionResult: ...
    def delete_claim(self, claim_id: str, mode: str = "retract") -> ActionResult: ...
    
    # Notes
    def add_note(self, body: str, title: Optional[str] = None, **kwargs) -> ActionResult: ...
    def edit_note(self, note_id: str, **patch) -> ActionResult: ...
    def delete_note(self, note_id: str) -> ActionResult: ...
    
    # Entities & Tags
    def add_entity(self, name: str, entity_type: str, **kwargs) -> ActionResult: ...
    def add_tag(self, name: str, parent_tag_id: Optional[str] = None) -> ActionResult: ...
    
    # Search
    def search(self, query: str, strategy: str = "hybrid",
               k: int = 20, filters: Optional[Dict] = None,
               include_contested: bool = True) -> ActionResult: ...
    
    # Conflicts
    def create_conflict_set(self, claim_ids: List[str], notes: Optional[str] = None) -> ActionResult: ...
    def resolve_conflict_set(self, conflict_set_id: str, resolution_notes: str, actions: Dict = {}) -> ActionResult: ...
```



### Task 2.3: Text Orchestration (`interface/text_orchestration.py`)

```python
@dataclass
class OrchestrationResult:
    action_taken: str
    action_result: Optional[ActionResult]
    clarifying_questions: List[str]
    affected_objects: List[Dict]
    raw_intent: Dict  # LLM parsed intent

class TextOrchestrator:
    def __init__(self, api: StructuredAPI, keys: Dict[str, str]): ...
    
    def process(self, user_text: str, context: Optional[Dict] = None) -> OrchestrationResult:
        """
        Parse natural language command → route to structured API.
        
        Examples:
    - "add this fact: I prefer morning workouts" → add_claim
    - "find what I said about mom's health" → search
    - "update my preference about coffee" → search + edit_claim
    - "delete the reminder about dentist" → search + delete_claim
        """
    
    def _parse_intent(self, user_text: str, context: Optional[Dict]) -> Dict:
        """Use LLM to extract: action, object_type, parameters, constraints."""
    
    def _route_to_action(self, intent: Dict) -> OrchestrationResult:
        """Execute the appropriate StructuredAPI method."""
```



### Task 2.4: Conversation Distillation (`interface/conversation_distillation.py`)

```python
@dataclass
class CandidateClaim:
    statement: str
    claim_type: str
    context_domain: str
    confidence: float
    source: str  # "user_stated", "assistant_inferred", "user_confirmed"

@dataclass
class MemoryUpdatePlan:
    candidates: List[CandidateClaim]
    existing_matches: List[Tuple[CandidateClaim, Claim, str]]  # (candidate, existing, relation: 'exact'|'update'|'contradicts')
    proposed_actions: List[Dict]  # {action: 'add'|'update'|'retract', claim_id, data}
    user_prompt: str  # Confirmation prompt for user
    requires_user_confirmation: bool = True

@dataclass
class DistillationResult:
    plan: MemoryUpdatePlan
    executed: bool
    execution_results: List[ActionResult]

class ConversationDistiller:
    def __init__(self, api: StructuredAPI, keys: Dict[str, str]): ...
    
    def extract_and_propose(
        self,
        conversation_summary: str,
        user_message: str,
        assistant_message: str,
    ) -> MemoryUpdatePlan:
        """
    1. Extract candidate claims from conversation turn
    2. Search for existing matches (FTS + entity/tag filters)
    3. Classify: already_exists | should_update | should_retract | conflicts_with | new
    4. Generate user confirmation prompt
        """
    
    def execute_plan(
        self,
        plan: MemoryUpdatePlan,
        user_response: str,  # User's confirmation/modification
    ) -> DistillationResult:
        """
        Parse user response → execute approved actions.
        Default: propose-first, not silent writes.
        """
    
    def _extract_claims_from_turn(
        self,
        conversation_summary: str,
        user_message: str,
        assistant_message: str,
    ) -> List[CandidateClaim]:
        """Use LLM to identify memorable facts, preferences, decisions, etc."""
    
    def _find_existing_matches(
        self,
        candidate: CandidateClaim,
    ) -> List[Tuple[Claim, str]]:
        """Search for semantically similar existing claims."""
```

---

## Parallelization Opportunities

The plan includes parallelization at multiple levels:

```javascript
┌─────────────────────────────────────────────────────────────────┐
│                    PARALLELIZATION POINTS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. HYBRID SEARCH                                                │
│     ┌─────────┐   ┌───────────┐   ┌─────────┐                  │
│     │   FTS   │   │ Embedding │   │ Rewrite │   ← Run in       │
│     │ Search  │   │  Search   │   │ Search  │     parallel     │
│     └────┬────┘   └─────┬─────┘   └────┬────┘                  │
│          │              │              │                        │
│          └──────────────┼──────────────┘                        │
│                         ▼                                        │
│                   RRF Merge                                      │
│                         │                                        │
│                         ▼                                        │
│                  LLM Rerank (optional)                           │
│                                                                  │
│  2. EMBEDDING COMPUTATION                                        │
│     Multiple claims → Parallel get_document_embedding()          │
│                                                                  │
│  3. LLM MAP-REDUCE                                               │
│     Batch scoring → Parallel LLM calls per batch                 │
│                                                                  │
│  4. LLM EXTRACTION (batch_extract_all)                           │
│     Multiple statements → Parallel tag/entity/SPO extraction     │
│                                                                  │
│  5. SIMILARITY CHECKS                                            │
│     Multiple candidates → Parallel embedding comparisons         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation**: Uses `ParallelExecutor` from `utils.py` wrapping `ThreadPoolExecutor` (compatible with `code_common/call_llm.py` patterns).---

## Key Design Decisions

1. **FTS as Backbone**: FTS/BM25 (S2) is the default, deterministic retrieval method. LLM-based methods supplement, not replace.
2. **Embeddings Storage**: Store embeddings in a separate `claim_embeddings` table as BLOBs for efficient vector search.
3. **Contested Claims**: Always return with warnings, prefer `active` in ranking.
4. **Soft Deletes**: Never hard-delete; use `status='retracted'` + `retracted_at`.
5. **Propose-First for Distillation**: Conversation distillation proposes changes, requires user confirmation before execution.
6. **LLM Integration**: Uses `code_common/call_llm.py` for all LLM calls (call_llm, get_*_embedding, getKeywordsFromText).
7. **Enums over Magic Strings**: All allowed values defined in `constants.py` to prevent typos and enable IDE autocomplete.
8. **Transaction Safety**: All multi-step operations wrapped in `db.transaction()` for atomicity.
9. **FTS Sync Invariant**: Every CRUD operation on claims/notes **must** sync to FTS tables.
10. **Extensibility via meta_json**: Non-core fields stored in `meta_json` to avoid schema migrations.

---

## Potential Challenges and Mitigations

| Challenge | Risk | Mitigation ||-----------|------|------------|| **FTS Sync Invariant** | Search becomes unreliable if FTS tables drift | Sync in same transaction as CRUD; consider SQLite triggers later || **Tag Hierarchy Cycles** | Breaks hierarchical filtering | `_validate_no_cycle()` in TagCRUD before any insert/update || **Embedding Staleness** | Old embeddings return wrong results | Delete embedding when `statement` changes in `edit_claim()` || **LLM Non-Determinism** | Same query yields different results | Log all prompts/outputs; use temperature=0.0 for extraction || **Concurrent Access** | SQLite single-writer bottleneck | WAL mode enabled by default; readers don't block || **Near-Duplicate Claims** | Pollutes memory with repetitions | `check_similarity()` before `add_claim()` in auto mode || **Privacy Leakage** | Sensitive facts in wrong context | Use `meta_json.visibility` field; later add policy gating || **Schema Regret** | Need provenance/versioning later | Keep soft delete, keep `meta_json`, keep conflict sets |---

## Extensibility / Future-Proofing

The design supports future enhancements without breaking changes:**1. New Claim Types:**

```python
# Just add to ClaimType enum in constants.py
class ClaimType(str, Enum):
    ...
    GOAL = "goal"  # New!
```

**2. New Search Strategies:**

```python
# Implement SearchStrategy ABC
class NewSearchStrategy(SearchStrategy):
    def name(self) -> str: return "new_strategy"
    def search(self, query, k, filters) -> List[SearchResult]: ...

# Register in HybridSearchStrategy
self.strategies["new_strategy"] = NewSearchStrategy(db, keys, config)
```

**3. Privacy/Visibility Gating (future):**

```python
# Already have meta_json.visibility hook
# Later add to SearchFilters:
@dataclass
class SearchFilters:
    ...
    max_visibility: str = "default"  # Filter out "restricted" claims
```

**4. Provenance/Versioning (future):**

```python
# Add claim_versions table
# Keep original claim_id, add version_id
# meta_json already supports {source, llm.model, llm.prompt_version}
```

**5. New Entity Types/Roles:**

```python
# Just extend the enums
class EntityType(str, Enum):
    ...
    EVENT = "event"  # New!
```

---

## Schema Verification Checklist

From requirements document, verify implementation includes:

- [ ] **claims table**: 14 columns (claim_id, claim_type, statement, subject_text, predicate, object_text, context_domain, status, confidence, created_at, updated_at, valid_from, valid_to, meta_json, retracted_at)
- [ ] **notes table**: 7 columns (note_id, title, body, context_domain, meta_json, created_at, updated_at)
- [ ] **entities table**: 6 columns + UNIQUE(entity_type, name)
- [ ] **tags table**: 6 columns + UNIQUE(name, parent_tag_id) + self-referential FK
- [ ] **claim_tags**: PK(claim_id, tag_id) + CASCADE deletes
- [ ] **claim_entities**: PK(claim_id, entity_id, role) + CASCADE deletes
- [ ] **conflict_sets**: 5 columns (conflict_set_id, status, resolution_notes, created_at, updated_at)
- [ ] **conflict_set_members**: PK(conflict_set_id, claim_id) + CASCADE deletes
- [ ] **claim_embeddings**: claim_id, embedding BLOB, model_name, created_at
- [ ] **claims_fts**: FTS5 on statement, predicate, object_text, subject_text, context_domain
- [ ] **notes_fts**: FTS5 on title, body, context_domain
- [ ] **Indexes**: status, context_domain, claim_type, validity, predicate, tag_id reverse lookup, entity_id, role

---

## Dependencies

- Python 3.9+
- sqlite3 (built-in)
- numpy (embeddings, cosine similarity)
- `code_common/call_llm.py` (LLM + embeddings + keywords)
- dataclasses, json, uuid, datetime (built-in)
- concurrent.futures (built-in, for parallelization)

---

## Quick Start (After Implementation)

```python
from truth_management_system import PKBConfig, get_database, StructuredAPI

# Initialize
config = PKBConfig(db_path="./my_kb.sqlite")
db = get_database(config)
keys = {"OPENROUTER_API_KEY": "sk-or-v1-..."}
api = StructuredAPI(db, keys, config)

# Add a claim
result = api.add_claim(
    statement="I prefer morning workouts",
    claim_type="preference",
    context_domain="health",
    auto_extract=True  # Auto-generate tags, entities
)

# Search
results = api.search("what are my workout preferences?", strategy="hybrid")

# Text orchestration (for chatbot)
from truth_management_system.interface import TextOrchestrator
orchestrator = TextOrchestrator(api, keys)
result = orchestrator.process("remember that I like coffee")


```