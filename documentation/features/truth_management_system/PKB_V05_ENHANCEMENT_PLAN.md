# PKB v0.5 Enhancement Plan — Comprehensive Implementation Guide

**Created:** 2026-02-07  
**Status:** Implemented (Phases 1-8 complete) + Post-implementation bug fixes  
**Target Version:** v0.5.0  
**Implementation Date:** 2026-02-07  
**Last Updated:** 2026-02-07

### Post-Implementation Bug Fixes

1. **`no such column: friendly_id` during text ingestion** — Root cause: v2 databases had not been migrated to v3. Multiple fixes applied:
   - `schema.py`: Removed v3-specific indexes from base DDL; moved to `_ensure_fts_v3()` in `database.py`.
   - `database.py`: Added `_ensure_fts_v3()` idempotent fixup that checks FTS table schema and upgrades if needed. Added column existence checks in `initialize_schema()` so long-running servers pick up schema changes. Both `get_pkb_db()` (in `endpoints/pkb.py`) and `get_pkb_database()` (in `Conversation.py`) now call `initialize_schema()` on every access to ensure up-to-date schema.
   - `crud/claims.py`: Added `_get_actual_claim_columns()` to dynamically detect columns in the `claims` table at runtime, so `INSERT` only references columns that exist. Added `reset_claim_columns_cache()`.
   - `crud/base.py`: Added `_fts_has_friendly_id()` check; `sync_claim_to_fts()` conditionally includes `friendly_id`.
   - `search/fts_search.py`: Added `friendly_id` to `allowed_columns` in `search_by_column()`.

2. **`'IngestProposal' object has no attribute 'match'`** — Root cause: `endpoints/pkb.py` `pkb_ingest_text_route()` referenced `proposal.match.claim` but `IngestProposal` uses `existing_claim` and `similarity_score` attributes. Fixed attribute references.

3. **Text ingestion save triggering excessive LLM calls / timeout** — Root cause: `text_ingestion.py` `_execute_proposal()` called `api.add_claim(auto_extract=True)` for each claim during bulk save, causing 2+ LLM calls per claim. Since similarity analysis was already done during the `ingest_and_propose()` phase, changed to `auto_extract=False`.

---

## 1. Goals & Requirements

We are enhancing the Personal Knowledge Base (PKB) with 8 interrelated features to improve usability, organization, and reference capability.

### Feature Summary

| # | Feature | Description |
|---|---------|-------------|
| 1 | **Friendly IDs** | User-facing alphanumeric IDs for memories (auto-generated or user-specified) |
| 2 | **Enhanced Filtering** | Sort and filter memories by tag, domain, type, entity in UI |
| 3 | **Entity Management** | Full entity CRUD in UI; attach entities to claims |
| 4 | **Multi-Type/Domain** | Claims support multiple types and domains; custom types/domains |
| 5 | **@reference in Chat** | Reference memories by friendly_id using `@friendly_id` in messages |
| 6 | **Context/Group System** | Hierarchical grouping (DAG) where leaves are memories; `@context_id` resolution |
| 7 | **Autocomplete** | `@` triggered autocomplete in chat input for memory/context references |
| 8 | **Encapsulation** | Keep PKB logic internal; expose clean API to UI and Conversation module |

---

## 2. Design Decisions

### 2.1 Friendly IDs

- **Column:** `friendly_id TEXT` on `claims` table
- **Format:** Alphanumeric + underscores + hyphens. Regex: `^[a-zA-Z0-9_-]+$`
- **Auto-generation:** If not provided, auto-generate from statement: lowercase first 4 words joined by underscores + 4-char random suffix. Example: `prefer_morning_workouts_a3f2`
- **Uniqueness:** UNIQUE per `user_email` (indexed)
- **Lookup:** `get_by_friendly_id(friendly_id, user_email)` returns claim

### 2.2 Multi-Type and Multi-Domain

- **Approach:** Keep primary `claim_type` and `context_domain` columns for backwards compatibility.
- **New columns:** `claim_types TEXT` (JSON array) and `context_domains TEXT` (JSON array)
- **Behaviour:** Primary type/domain is always the first element. The JSON arrays hold ALL types/domains.
- **Custom types/domains:** Stored in user's `meta_json` preferences or a lightweight `custom_types`/`custom_domains` table.
- **UI:** Multi-select dropdowns. "Add custom" option.

### 2.3 Context/Group System

- **New table:** `contexts` — hierarchical grouping nodes
- **New table:** `context_claims` — junction linking contexts to claims (many-to-many)
- **Hierarchy:** Contexts can contain other contexts via `parent_context_id` (tree, not full DAG for v0.5 simplicity)
- **Claims:** A claim can belong to multiple contexts
- **Friendly IDs:** Contexts also have `friendly_id` for `@context_id` references
- **Resolution:** `resolve_context(context_id)` recursively collects all leaf claims through the hierarchy

### 2.4 @Reference Syntax

- **Syntax:** `@friendly_id` — single `@` prefix followed by the friendly ID
- **Resolution order:** Try memory `friendly_id` first, then context `friendly_id`
- **Regex:** `/@([a-zA-Z0-9_-]+)/g` (must not clash with other `@` patterns like `@memory:uuid`)
- **Backwards compatibility:** Old `@memory:uuid` and `@mem:uuid` syntax still supported

### 2.5 Autocomplete

- **Trigger:** After typing `@` in the chat input
- **Endpoint:** `GET /pkb/autocomplete?q=prefix&limit=10` returns matching memories and contexts
- **Response:** `{memories: [{friendly_id, statement_preview, claim_type}], contexts: [{friendly_id, name, claim_count}]}`
- **UI:** Lightweight dropdown below cursor position, keyboard navigable

---

## 3. Schema Changes (v2 → v3)

### 3.1 Claims Table Additions

```sql
ALTER TABLE claims ADD COLUMN friendly_id TEXT;
ALTER TABLE claims ADD COLUMN claim_types TEXT;     -- JSON array: ["preference", "fact"]
ALTER TABLE claims ADD COLUMN context_domains TEXT;  -- JSON array: ["health", "personal"]

CREATE UNIQUE INDEX IF NOT EXISTS idx_claims_user_friendly_id 
    ON claims(user_email, friendly_id);
CREATE INDEX IF NOT EXISTS idx_claims_friendly_id ON claims(friendly_id);
```

### 3.2 New Contexts Table

```sql
CREATE TABLE IF NOT EXISTS contexts (
    context_id TEXT PRIMARY KEY,
    user_email TEXT,
    friendly_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    parent_context_id TEXT REFERENCES contexts(context_id) ON DELETE SET NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_email, friendly_id)
);

CREATE TABLE IF NOT EXISTS context_claims (
    context_id TEXT NOT NULL REFERENCES contexts(context_id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    PRIMARY KEY (context_id, claim_id)
);

CREATE INDEX IF NOT EXISTS idx_contexts_user_email ON contexts(user_email);
CREATE INDEX IF NOT EXISTS idx_contexts_friendly_id ON contexts(friendly_id);
CREATE INDEX IF NOT EXISTS idx_contexts_parent ON contexts(parent_context_id);
CREATE INDEX IF NOT EXISTS idx_context_claims_claim_id ON context_claims(claim_id);
```

### 3.3 Migration v2 → v3

```python
def _migrate_v2_to_v3(self, conn):
    """Add friendly_id, multi-type/domain columns, and contexts tables."""
    # 1. Add friendly_id to claims if not exists
    # 2. Add claim_types and context_domains to claims
    # 3. Create contexts and context_claims tables
    # 4. Create indexes
    # 5. Backfill friendly_id for existing claims
```

---

## 4. Milestones & Granular Tasks

### Milestone 1: Database Schema & Models (Foundation)

**Goal:** Update schema, models, and migration logic. No behaviour changes yet.

| Task | File(s) | Description |
|------|---------|-------------|
| 1.1 | `schema.py` | Update `SCHEMA_VERSION` to 3. Add `friendly_id`, `claim_types`, `context_domains` columns to claims DDL. Add `contexts` and `context_claims` table DDL. Add indexes. |
| 1.2 | `database.py` | Add `_migrate_v2_to_v3()` method. Update `_run_migrations()` to handle v2→v3. Include friendly_id backfill for existing claims. |
| 1.3 | `models.py` | Add `friendly_id`, `claim_types`, `context_domains` fields to `Claim` dataclass. Update `CLAIM_COLUMNS`. Create `Context` and `ContextClaim` dataclasses with `CONTEXT_COLUMNS`. |
| 1.4 | `constants.py` | No changes needed (types/domains already defined as enums). Optionally add `FRIENDLY_ID_REGEX`. |
| 1.5 | `utils.py` | Add `generate_friendly_id(statement: str) -> str` function. Add `validate_friendly_id(fid: str) -> bool` function. |
| 1.6 | `__init__.py` | Export new models (`Context`, `ContextClaim`, `CONTEXT_COLUMNS`). |

**Function Signatures:**

```python
# utils.py
def generate_friendly_id(statement: str, max_words: int = 4, suffix_len: int = 4) -> str:
    """Generate a friendly ID from a statement text.
    Takes first max_words, lowercases, joins with underscores, adds random suffix.
    Returns: e.g. 'prefer_morning_workouts_a3f2'
    """

def validate_friendly_id(friendly_id: str) -> bool:
    """Validate that a friendly_id matches allowed pattern: ^[a-zA-Z0-9_-]+$"""
```

```python
# models.py - Context dataclass
@dataclass
class Context:
    context_id: str
    user_email: Optional[str] = None
    friendly_id: Optional[str] = None
    name: str = ""
    description: Optional[str] = None
    parent_context_id: Optional[str] = None
    meta_json: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    # Computed
    _children: List['Context'] = field(default_factory=list)
    _claim_ids: List[str] = field(default_factory=list)
```

---

### Milestone 2: CRUD Layer Enhancements

**Goal:** Add CRUD operations for contexts, friendly_id lookup, entity attachment improvements.

| Task | File(s) | Description |
|------|---------|-------------|
| 2.1 | `crud/claims.py` | Add `get_by_friendly_id(friendly_id)` method. Update `add()` to generate/validate friendly_id. Update `edit()` to support friendly_id changes. |
| 2.2 | `crud/contexts.py` (NEW) | Create `ContextCRUD` class with: `add()`, `edit()`, `delete()`, `get()`, `get_by_friendly_id()`, `get_children()`, `get_descendants()`, `resolve_claims()` (recursively get all leaf claims), `add_claim()`, `remove_claim()`. |
| 2.3 | `crud/links.py` | Add `link_context_claim()`, `unlink_context_claim()`, `get_context_claims()`, `get_claims_for_context()`, `get_contexts_for_claim()`. |
| 2.4 | `crud/__init__.py` | Export `ContextCRUD`. |

**Function Signatures:**

```python
# crud/claims.py
class ClaimCRUD(BaseCRUD[Claim]):
    def get_by_friendly_id(self, friendly_id: str) -> Optional[Claim]:
        """Get claim by user-facing friendly_id. User-scoped."""
    
    def search_friendly_ids(self, prefix: str, limit: int = 10) -> List[Claim]:
        """Search claims by friendly_id prefix (for autocomplete). User-scoped."""
```

```python
# crud/contexts.py
class ContextCRUD(BaseCRUD[Context]):
    def add(self, context: Context) -> Context
    def edit(self, context_id: str, patch: Dict) -> Optional[Context]
    def delete(self, context_id: str) -> bool
    def get_by_friendly_id(self, friendly_id: str) -> Optional[Context]
    def search_friendly_ids(self, prefix: str, limit: int = 10) -> List[Context]
    def get_children(self, parent_id: Optional[str] = None) -> List[Context]
    def get_descendants(self, context_id: str) -> List[Context]
    def resolve_claims(self, context_id: str) -> List[Claim]:
        """Recursively get all claims under this context and all sub-contexts."""
    def add_claim(self, context_id: str, claim_id: str) -> bool
    def remove_claim(self, context_id: str, claim_id: str) -> bool
    def get_claims(self, context_id: str) -> List[Claim]:
        """Get claims directly in this context (not recursive)."""
```

---

### Milestone 3: StructuredAPI Enhancements

**Goal:** Expose new capabilities through the unified API layer.

| Task | File(s) | Description |
|------|---------|-------------|
| 3.1 | `interface/structured_api.py` | Add context CRUD methods: `add_context()`, `edit_context()`, `delete_context()`, `get_context()`, `resolve_context()`. |
| 3.2 | `interface/structured_api.py` | Add `get_claim_by_friendly_id()` and `resolve_reference()` (tries memory then context). |
| 3.3 | `interface/structured_api.py` | Add `autocomplete(prefix, limit)` → returns memories and contexts matching prefix. |
| 3.4 | `interface/structured_api.py` | Update `add_claim()` to accept and process `friendly_id`, `claim_types`, `context_domains`. |
| 3.5 | `interface/structured_api.py` | Add `add_entity()` improvements, `link_entity_to_claim()`, `unlink_entity_from_claim()` methods. |

**Function Signatures:**

```python
# interface/structured_api.py
class StructuredAPI:
    # Context methods
    def add_context(self, name, friendly_id=None, description=None, 
                    parent_context_id=None, claim_ids=None) -> ActionResult
    def edit_context(self, context_id, **patch) -> ActionResult
    def delete_context(self, context_id) -> ActionResult
    def get_context(self, context_id) -> ActionResult
    def resolve_context(self, context_id) -> ActionResult:
        """Get all claims (recursive) under a context. Returns ActionResult with List[Claim]."""
    def add_claim_to_context(self, context_id, claim_id) -> ActionResult
    def remove_claim_from_context(self, context_id, claim_id) -> ActionResult
    
    # Reference resolution
    def get_claim_by_friendly_id(self, friendly_id) -> ActionResult
    def resolve_reference(self, reference_id) -> ActionResult:
        """Try memory friendly_id first, then context friendly_id. 
        Returns ActionResult with data={'type': 'claim'|'context', 'claims': [...]}"""
    
    # Autocomplete
    def autocomplete(self, prefix, limit=10) -> ActionResult:
        """Search memories and contexts by friendly_id prefix.
        Returns ActionResult with data={'memories': [...], 'contexts': [...]}"""
    
    # Entity management
    def link_entity_to_claim(self, claim_id, entity_id, role) -> ActionResult
    def unlink_entity_from_claim(self, claim_id, entity_id, role=None) -> ActionResult
    def get_claim_entities(self, claim_id) -> ActionResult
```

---

### Milestone 4: REST Endpoints

**Goal:** Expose new features via REST API for frontend consumption.

| Task | File(s) | Description |
|------|---------|-------------|
| 4.1 | `endpoints/pkb.py` | Add context CRUD endpoints: `POST/GET/PUT/DELETE /pkb/contexts`, `GET /pkb/contexts/<id>`, `POST /pkb/contexts/<id>/claims`. |
| 4.2 | `endpoints/pkb.py` | Add `GET /pkb/autocomplete?q=prefix&limit=10` endpoint. |
| 4.3 | `endpoints/pkb.py` | Add `GET /pkb/claims/by-friendly-id/<friendly_id>` endpoint. |
| 4.4 | `endpoints/pkb.py` | Update claim serialization to include `friendly_id`, `claim_types`, `context_domains`. |
| 4.5 | `endpoints/pkb.py` | Add entity management endpoints: `POST /pkb/entities`, `POST /pkb/claims/<id>/entities`, `DELETE /pkb/claims/<id>/entities/<entity_id>`. |
| 4.6 | `endpoints/pkb.py` | Add `serialize_context()` function. |

**Endpoint Specifications:**

```
# Context CRUD
GET    /pkb/contexts                    List user's contexts
POST   /pkb/contexts                    Create context {name, friendly_id?, description?, parent_context_id?, claim_ids?}
GET    /pkb/contexts/<id>               Get context with child contexts and claim count
PUT    /pkb/contexts/<id>               Update context
DELETE /pkb/contexts/<id>               Delete context (claims remain, just unlinked)

# Context-Claim linking
POST   /pkb/contexts/<id>/claims        Add claim to context {claim_id}
DELETE /pkb/contexts/<id>/claims/<cid>  Remove claim from context
GET    /pkb/contexts/<id>/resolve       Get all claims (recursive) under context

# Autocomplete
GET    /pkb/autocomplete?q=pref&limit=10    Search memory/context friendly_ids

# Friendly ID lookup
GET    /pkb/claims/by-friendly-id/<fid>     Get claim by friendly_id

# Entity management
POST   /pkb/entities                         Create entity {name, entity_type}
POST   /pkb/claims/<id>/entities             Link entity {entity_id, role}
DELETE /pkb/claims/<id>/entities/<eid>        Unlink entity
GET    /pkb/claims/<id>/entities              Get claim's entities
```

---

### Milestone 5: Conversation.py Integration

**Goal:** Update `_get_pkb_context()` to resolve `@friendly_id` and `@context_id` references.

| Task | File(s) | Description |
|------|---------|-------------|
| 5.1 | `Conversation.py` | Update `_get_pkb_context()` to accept and resolve `referenced_friendly_ids` (from new @syntax). |
| 5.2 | `Conversation.py` | Add logic: for each referenced_friendly_id, call `api.resolve_reference(fid)`. If it's a context, expand to all leaf claims. If it's a claim, include directly. |
| 5.3 | `Conversation.py` | Update context formatting to show `[REFERENCED @fid]` source label. |

**Key changes to `_get_pkb_context()`:**

```python
def _get_pkb_context(
    self,
    user_email: str,
    query: str,
    conversation_summary: str = "",
    k: int = 10,
    attached_claim_ids: list = None,
    conversation_id: str = None,
    conversation_pinned_claim_ids: list = None,
    referenced_claim_ids: list = None,
    referenced_friendly_ids: list = None,  # NEW: from @friendly_id syntax
) -> str:
```

---

### Milestone 6: Frontend — Enhanced Filtering & Entity Management

**Goal:** Improve the PKB modal with better filtering, entity management, and multi-select.

| Task | File(s) | Description |
|------|---------|-------------|
| 6.1 | `interface/interface.html` | Add entity filter dropdown to claims tab. Add tag filter dropdown. Update type/domain dropdowns to multi-select. |
| 6.2 | `interface/interface.html` | Enhance Entities tab: add entity list, add entity form, link entity to claim UI. |
| 6.3 | `interface/pkb-manager.js` | Add entity CRUD functions: `createEntity()`, `linkEntityToClaim()`, `unlinkEntity()`, `getClaimEntities()`. |
| 6.4 | `interface/pkb-manager.js` | Update `listClaims()` to support tag, entity, multi-type, multi-domain filters. |
| 6.5 | `interface/pkb-manager.js` | Update `renderClaimCard()` to show friendly_id, entities, multiple types/domains. |
| 6.6 | `interface/pkb-manager.js` | Update add/edit claim forms to support friendly_id, multi-type, multi-domain, entities. |
| 6.7 | `interface/interface.html` | Update claim add/edit modal: add friendly_id input, multi-select for type/domain, entity selection. |

---

### Milestone 7: Frontend — Context Management & Autocomplete

**Goal:** Add context management UI and @autocomplete in chat.

| Task | File(s) | Description |
|------|---------|-------------|
| 7.1 | `interface/interface.html` | Add Contexts tab to PKB modal (or reuse existing entity tab area). Context tree view with create/edit/delete. |
| 7.2 | `interface/pkb-manager.js` | Add context CRUD functions: `listContexts()`, `createContext()`, `editContext()`, `deleteContext()`, `addClaimToContext()`, `removeClaimFromContext()`, `resolveContext()`. |
| 7.3 | `interface/pkb-manager.js` | Add autocomplete functions: `searchAutocomplete(prefix)`. |
| 7.4 | `interface/common-chat.js` | Add autocomplete widget: detect `@` in input, show dropdown with matching memories/contexts, insert selected reference. |
| 7.5 | `interface/parseMessageForCheckBoxes.js` | Update `parseMemoryReferences()` to support new `@friendly_id` syntax alongside existing `@memory:uuid` and `@mem:uuid`. |
| 7.6 | `interface/common-chat.js` | Update `sendMessageCallback()` to extract and send `referenced_friendly_ids` from new syntax. |

**Autocomplete Widget Behaviour:**
1. User types `@` → start listening for characters
2. After 1+ chars after `@`, call `/pkb/autocomplete?q=prefix`
3. Show dropdown with memories (statement preview) and contexts (name)
4. Up/down arrow to navigate, Enter/Tab to select
5. Insert `@friendly_id` into message text
6. Dismiss on Escape or click outside

---

### Milestone 8: Encapsulation & API Cleanup

**Goal:** Ensure PKB logic is encapsulated; only clean API exposed.

| Task | File(s) | Description |
|------|---------|-------------|
| 8.1 | `truth_management_system/__init__.py` | Review and clean up exports. Ensure only public API surface is exported. |
| 8.2 | `endpoints/pkb.py` | Ensure all PKB logic goes through `StructuredAPI`, not direct CRUD calls. |
| 8.3 | `Conversation.py` | Ensure all PKB interaction goes through `StructuredAPI` methods. |
| 8.4 | Various | Add `resolve_reference()` as the single entry point for reference resolution (used by both Conversation.py and endpoints). |

---

### Milestone 9: Documentation & Testing

| Task | File(s) | Description |
|------|---------|-------------|
| 9.1 | `tests/test_crud.py` | Add tests for friendly_id generation, context CRUD, entity linking. |
| 9.2 | `tests/test_contexts.py` (NEW) | Tests for context hierarchy, resolve_claims, claim linking. |
| 9.3 | Documentation | Update `implementation.md`, `api.md`, `implementation_deep_dive.md` with new features. |

---

## 5. Implementation Order

The implementation follows a bottom-up approach for maximum incremental safety:

```
Phase 1: Schema + Models (Milestone 1)
    ↓ Database can migrate; new columns exist; models updated
Phase 2: CRUD Layer (Milestone 2)  
    ↓ Can create/read/update contexts and friendly_ids
Phase 3: API Layer (Milestone 3)
    ↓ StructuredAPI exposes new capabilities
Phase 4: REST Endpoints (Milestone 4)
    ↓ Frontend can call new APIs
Phase 5: Conversation.py (Milestone 5)
    ↓ Chat uses new reference system
Phase 6: Frontend Filtering & Entities (Milestone 6)
    ↓ UI shows enhanced data
Phase 7: Frontend Contexts & Autocomplete (Milestone 7)
    ↓ Full @reference experience
Phase 8: Cleanup (Milestone 8)
    ↓ Clean API boundaries
Phase 9: Docs & Tests (Milestone 9)
```

Each phase produces working, testable code. Earlier phases don't depend on later ones.

---

## 6. Risks & Challenges

| Risk | Mitigation |
|------|------------|
| Friendly ID collisions | Auto-generated IDs include random suffix; UNIQUE constraint at DB level |
| Performance of context resolution | Cache resolved claims; limit recursion depth; add `max_depth` parameter |
| Breaking existing @memory:uuid syntax | Keep old regex alongside new one; both work simultaneously |
| Schema migration on existing data | Migration backfills friendly_ids; tested with dry-run flag |
| Multi-select UI complexity | Use Bootstrap 4 compatible multi-select (e.g., data-multiple on select) |
| Autocomplete latency | Prefix search on indexed friendly_id column is fast; debounce at 200ms |
| Context cycles | Same cycle-detection logic as tags (walk parent chain) |
| FTS not indexing friendly_id | Add friendly_id to claims_fts index for searchability |

---

## 7. Files Modified

| File | Changes |
|------|---------|
| `truth_management_system/schema.py` | New columns, tables, indexes, SCHEMA_VERSION=3 |
| `truth_management_system/database.py` | `_migrate_v2_to_v3()` |
| `truth_management_system/models.py` | Claim fields, Context dataclass |
| `truth_management_system/constants.py` | FRIENDLY_ID_REGEX |
| `truth_management_system/utils.py` | `generate_friendly_id()`, `validate_friendly_id()` |
| `truth_management_system/__init__.py` | New exports |
| `truth_management_system/crud/claims.py` | friendly_id methods |
| `truth_management_system/crud/contexts.py` | NEW: ContextCRUD |
| `truth_management_system/crud/links.py` | context-claim links |
| `truth_management_system/crud/__init__.py` | Export ContextCRUD |
| `truth_management_system/interface/structured_api.py` | Context, autocomplete, entity linking methods |
| `endpoints/pkb.py` | New endpoints, updated serialization |
| `Conversation.py` | Updated `_get_pkb_context()` |
| `interface/interface.html` | Multi-select, entity tab, context tab |
| `interface/pkb-manager.js` | Context/entity/autocomplete functions |
| `interface/common-chat.js` | Autocomplete widget, updated sendMessage |
| `interface/parseMessageForCheckBoxes.js` | Updated regex for @friendly_id |

---

## 8. v0.5.1 Follow-Up Enhancements

Built on top of v0.5.0, these enhancements improve the UI and add dynamic type/domain management.

### 8.1 Schema v4: Dynamic Types & Domains

| Change | Description |
|--------|-------------|
| `claim_types_catalog` table | Stores valid claim types (system defaults + user-created) |
| `context_domains_catalog` table | Stores valid domains (system defaults + user-created) |
| `_migrate_v3_to_v4()` | Creates tables, seeds with enum defaults |
| `_ensure_catalog_seeded()` | Idempotent seeder called on every startup |
| `SCHEMA_VERSION = 4` | Bumped from 3 |

### 8.2 Expandable Entity/Tag/Context Views

| Feature | Implementation |
|---------|---------------|
| Expandable entities | `renderEntityCard()` with collapse/expand; `toggleEntityClaims()` fetches `GET /pkb/entities/<id>/claims`; claims rendered with full action buttons |
| Expandable tags | `renderTagCard()` with collapse/expand; `toggleTagClaims()` fetches `GET /pkb/tags/<id>/claims` |
| Expandable contexts | Context cards expand to show claims; "Attach Memory" and "Remove from Context" buttons |
| Shared action helper | `bindClaimCardActions($container, refreshCallback)` reused across all expandable views |
| "Add Memory" on entity | Opens Add Memory modal; after save, auto-links claim to entity via `POST /pkb/claims/<id>/entities` |

### 8.3 Context-Claim Linking in Modals

| Feature | Implementation |
|---------|---------------|
| Context dropdown in modal | `<select multiple>` populated from `GET /pkb/contexts` |
| Pre-selection on edit | Fetches `GET /pkb/claims/<id>/contexts` and pre-selects |
| Save context assignments | After claim save, calls `PUT /pkb/claims/<id>/contexts` with selected IDs |

### 8.4 Dynamic Type/Domain Management

| Feature | Implementation |
|---------|---------------|
| Multi-select type dropdown | Populated from `GET /pkb/types`; supports multi-select |
| Multi-select domain dropdown | Populated from `GET /pkb/domains`; supports multi-select |
| Inline "Add New" inputs | Calls `POST /pkb/types` or `POST /pkb/domains`; adds to dropdown immediately |
| Backend storage | `claim_types` (JSON array) and `context_domains` (JSON array) columns on claims |
| CRUD layer | `TypeCatalogCRUD`, `DomainCatalogCRUD` in `crud/catalog.py` |

### 8.5 New REST Endpoints (v0.5.1)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/entities/<id>/claims` | Claims linked to entity |
| GET | `/pkb/tags/<id>/claims` | Claims linked to tag |
| GET | `/pkb/claims/<id>/contexts` | Contexts for a claim |
| PUT | `/pkb/claims/<id>/contexts` | Set claim's contexts |
| GET | `/pkb/types` | List all valid types |
| POST | `/pkb/types` | Add custom type |
| GET | `/pkb/domains` | List all valid domains |
| POST | `/pkb/domains` | Add custom domain |

### 8.6 Files Modified (v0.5.1)

| File | Changes |
|------|---------|
| `truth_management_system/schema.py` | SCHEMA_VERSION=4, catalog tables DDL |
| `truth_management_system/database.py` | `_migrate_v3_to_v4()`, `_ensure_catalog_seeded()` |
| `truth_management_system/crud/catalog.py` | NEW: TypeCatalogCRUD, DomainCatalogCRUD |
| `truth_management_system/crud/__init__.py` | Export new CRUDs |
| `truth_management_system/interface/structured_api.py` | `type_catalog`, `domain_catalog` instances; multi-type/domain parsing in `add_claim()` |
| `endpoints/pkb.py` | 8 new endpoints (entities/claims, tags/claims, claims/contexts, types, domains) |
| `interface/pkb-manager.js` | Expandable entity/tag/context cards, `bindClaimCardActions()`, `populateTypesDropdown()`, `populateDomainsDropdown()`, `populateContextsDropdown()`, context save in `saveClaim()`, add-new-type/domain handlers |
| `interface/interface.html` | Multi-select type/domain/context in claim modal, inline add-new inputs |

---

## 9. v0.6 Follow-Up Enhancements

Built on top of v0.5.1, v0.6 adds claim numbering, QnA-style possible questions, unified search/filter, and improved ID resolution.

### Key Changes (v0.6)

| Feature | Schema | Description |
|---------|--------|-------------|
| Claim Numbers | v5 | Per-user auto-incremented `claim_number INTEGER`; referenceable as `@claim_N` |
| Possible Questions | v6 | `possible_questions TEXT` (JSON array); LLM auto-generated; FTS-indexed for QnA search |
| Unified Endpoint | — | `GET /pkb/claims` now accepts `query` param for search mode; replaces need for `POST /pkb/search` in UI |
| Universal ID Resolution | — | `resolve_claim_identifier()`: accepts bare number, `claim_N`, `@claim_N`, UUID, friendly_id |
| Auto-gen on Edit | — | `edit_claim()` auto-generates `friendly_id` and `possible_questions` via LLM if missing |
| Improved Friendly IDs | — | Better stopword filtering (80+ words); 1-3 meaningful words + 4-char suffix |
| Search+Filter Fix | — | `StructuredAPI.search()` accepts both singular (`claim_type`) and plural (`claim_types`) filter keys |
| Context Search Panel | — | Inline search bar + type/domain filters + checkbox link/unlink within expanded context cards |
| Context Name Fallback | — | `resolve_reference()` tries context name as fallback after friendly_id |

See `implementation_deep_dive.md` [v0.6 Addendum](./implementation_deep_dive.md#v06-addendum) for full details.

---

**End of Enhancement Plan**
