# PKB v0.7: Universal @References — Entities, Tags, and Domains

**Created:** 2026-02-08  
**Status:** Implemented (2026-02-08)  
**Depends On:** v0.6 (friendly IDs, contexts, claim numbers)

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Goals](#goals)
3. [Current State](#current-state)
4. [Design: Type-Suffixed Friendly IDs](#design-type-suffixed-friendly-ids)
5. [Namespace Resolution Strategy](#namespace-resolution-strategy)
6. [What Each Reference Returns](#what-each-reference-returns)
7. [DB Schema Changes](#db-schema-changes)
8. [Friendly ID Generation Rules](#friendly-id-generation-rules)
9. [Backend Changes](#backend-changes)
10. [UI Changes](#ui-changes)
11. [Migration Strategy](#migration-strategy)
12. [Risks and Mitigations](#risks-and-mitigations)
13. [Implementation Plan](#implementation-plan)
14. [Testing Plan](#testing-plan)

---

## Problem Statement

Today a user can reference individual claims (`@prefer_morning_a3f2`) or entire contexts (`@ssdva`) in chat. But there is no way to reference:

- **An entity** — e.g., "show me everything about @john_smith"
- **A tag** — e.g., "what do I know about @fitness"
- **A domain** — e.g., "what are my @health memories"

Adding these introduces a **namespace clash** problem: a tag named `health`, a context named `health`, a domain `health`, and a claim friendly_id `health_xyz` could all collide under the `@health` reference.

---

## Goals

1. Users can reference entities, tags, and domains in chat using `@` syntax
2. No ambiguity — each reference resolves to exactly one object type
3. Backwards compatible — existing claim and context references continue to work
4. Clean UI — no new buttons or dropdowns needed; the suffix is self-documenting
5. Autocomplete shows all types (claims, contexts, entities, tags, domains) in a single dropdown

---

## Current State

### What Can Be Referenced Today

| Object | Has friendly_id? | Reference Syntax | Resolution |
|--------|-----------------|------------------|------------|
| **Claim** | Yes (auto-generated) | `@prefer_morning_a3f2` | `claims.get_by_friendly_id()` |
| **Claim (numeric)** | N/A | `@claim_42` | `claims.get_by_claim_number()` |
| **Claim (UUID)** | N/A | `@memory:uuid` | Legacy direct lookup |
| **Context** | Yes (auto-generated) | `@ssdva` | `contexts.get_by_friendly_id()` |
| **Entity** | **No** | Not supported | — |
| **Tag** | **No** | Not supported | — |
| **Domain** | **No** | Not supported | — |

### Current Resolution Order (in `resolve_reference()`)

1. Try as `@claim_N` numeric
2. Try as claim `friendly_id`
3. Try as context `friendly_id`
4. Try as context name (fallback, case-insensitive)
5. Not found

### Current DB Schema (Relevant Parts)

```sql
-- Claims: have friendly_id and claim_number
claims (claim_id, friendly_id, claim_number, statement, ...)

-- Contexts: have friendly_id
contexts (context_id, friendly_id, name, parent_context_id, ...)

-- Entities: NO friendly_id
entities (entity_id, entity_type, name, user_email, ...)

-- Tags: NO friendly_id
tags (tag_id, name, parent_tag_id, user_email, ...)

-- Domains: just catalog entries, no UUID or friendly_id
claim_types_catalog (type_name, user_email, display_name, ...)
context_domains_catalog (domain_name, user_email, display_name, ...)
```

---

## Design: Type-Suffixed Friendly IDs

### Core Idea

Append a `_<type>` suffix to the friendly_id of non-claim objects. This suffix:
- **Disambiguates** — no namespace clashes possible
- **Self-documents** — user sees the type in the reference
- **Enables direct routing** — backend can parse the suffix and skip irrelevant lookups
- **Is UI-clean** — no extra badges/icons needed; the suffix IS the type indicator

### Suffix Convention

| Object Type | Suffix | Example Friendly ID | User Types In Chat | Notes |
|------------|--------|--------------------|--------------------|-------|
| **Claim** | _(none)_ | `prefer_morning_a3f2` | `@prefer_morning_a3f2` | Unchanged. Most common, no suffix needed. |
| **Context** | `_context` | `health_goals_context` | `@health_goals_context` | Change from current (no suffix). Migration needed. |
| **Entity** | `_entity` | `john_smith_person_entity` | `@john_smith_person_entity` | New. Includes entity_type for disambiguation. |
| **Tag** | `_tag` | `fitness_tag` | `@fitness_tag` | New. |
| **Domain** | `_domain` | `health_domain` | `@health_domain` | New. No random suffix — domains are unique by name. |

### Why Claims Keep No Suffix

Claims are the most common reference type. Adding `_claim` would be verbose and break all existing references. The suffix convention is:
- **No suffix = claim** (default, most common)
- **Has suffix = other type** (context, entity, tag, domain)

---

## Namespace Resolution Strategy

### New Resolution Order (in `resolve_reference()`)

```python
def resolve_reference(reference_id):
    """
    Resolve any @reference to its target object and associated claims.
    
    Strategy:
    1. Parse suffix to determine object type (fast path)
    2. If no suffix, fall through to existing claim resolution (backwards compat)
    3. Each type returns a list of claims for LLM context injection
    """
    
    # --- FAST PATH: Suffix-based routing ---
    
    # 1a. Ends with _context → context lookup
    if reference_id.endswith('_context'):
        return resolve_context(reference_id)
    
    # 1b. Ends with _entity → entity lookup  
    if reference_id.endswith('_entity'):
        return resolve_entity(reference_id)
    
    # 1c. Ends with _tag → tag lookup
    if reference_id.endswith('_tag'):
        return resolve_tag(reference_id)
    
    # 1d. Ends with _domain → domain lookup
    if reference_id.endswith('_domain'):
        return resolve_domain(reference_id)
    
    # --- BACKWARDS COMPATIBLE PATH: No suffix ---
    
    # 2. Try as @claim_N numeric reference
    claim_num_match = re.match(r'^claim_(\d+)$', reference_id)
    if claim_num_match:
        return resolve_claim_number(int(claim_num_match.group(1)))
    
    # 3. Try as claim friendly_id (no suffix = claim)
    claim = claims.get_by_friendly_id(reference_id)
    if claim:
        return ActionResult(type='claim', claims=[claim])
    
    # 4. Try as context friendly_id (legacy, for old contexts without _context suffix)
    context = contexts.get_by_friendly_id(reference_id)
    if context:
        return ActionResult(type='context', claims=resolve_claims(context))
    
    # 5. Try as context name (fallback)
    context = find_context_by_name(reference_id)
    if context:
        return ActionResult(type='context', claims=resolve_claims(context))
    
    # 6. Not found
    return ActionResult(success=False)
```

### Why This Is Backwards Compatible

- Existing claim references like `@prefer_morning_a3f2` don't end with any reserved suffix → fall through to step 3 (claim lookup)
- Existing context references like `@ssdva` don't end with `_context` → fall through to step 4 (legacy context lookup)
- New references with suffixes → routed directly by step 1
- Over time, new contexts get `_context` suffix automatically; old ones still work via fallback

---

## What Each Reference Returns

Each reference type ultimately returns a list of claims (because claims are what the LLM needs). The difference is HOW the claims are collected.

### Entity Reference: `@john_smith_person_entity`

**Resolution:**
1. Look up entity by friendly_id in `entities` table
2. Query `claim_entities` join table for all claims linked to this entity
3. Return all linked claims (any role: subject, object, mentioned, about_person)

**SQL:**
```sql
SELECT c.* FROM claims c
JOIN claim_entities ce ON c.claim_id = ce.claim_id
JOIN entities e ON ce.entity_id = e.entity_id
WHERE e.friendly_id = ? AND e.user_email = ?
  AND c.status IN ('active', 'contested')
ORDER BY c.updated_at DESC
```

**Label:** `[REFERENCED @john_smith_person_entity]`

**Use Case:** "Tell me everything I know about @john_smith_person_entity"

---

### Tag Reference: `@fitness_tag`

**Resolution:**
1. Look up tag by friendly_id in `tags` table
2. **Recursively** get all descendant tags (like tag hierarchy: fitness → running → marathon)
3. Query `claim_tags` join table for all claims linked to any tag in the tree
4. Return all linked claims

**SQL (Recursive):**
```sql
WITH RECURSIVE tag_tree AS (
    SELECT tag_id FROM tags WHERE friendly_id = ? AND user_email = ?
    UNION ALL
    SELECT t.tag_id FROM tags t
    JOIN tag_tree tt ON t.parent_tag_id = tt.tag_id
)
SELECT DISTINCT c.* FROM claims c
JOIN claim_tags ct ON c.claim_id = ct.claim_id
JOIN tag_tree tt ON ct.tag_id = tt.tag_id
WHERE c.status IN ('active', 'contested')
ORDER BY c.updated_at DESC
```

**Label:** `[REFERENCED @fitness_tag]`

**Use Case:** "What are my @fitness_tag memories?" → returns claims tagged fitness, running, yoga, etc.

---

### Domain Reference: `@health_domain`

**Resolution:**
1. Strip `_domain` suffix to get domain_name (e.g., `health`)
2. Query claims where `context_domain = domain_name` OR `context_domains` JSON array contains domain_name
3. Return all matching claims

**SQL:**
```sql
SELECT c.* FROM claims c
WHERE c.user_email = ?
  AND c.status IN ('active', 'contested')
  AND (c.context_domain = ? OR c.context_domains LIKE ?)
ORDER BY c.updated_at DESC
LIMIT 50
```

**Label:** `[REFERENCED @health_domain]`

**Use Case:** "Show me my @health_domain memories" → all health claims

**Note:** Domain references could return many claims. We should limit to the most recent N (e.g., 50) and/or use hybrid search with the user's query to rank them.

---

### Context Reference: `@health_goals_context` (Updated)

Same as today, but with `_context` suffix:
1. Look up context by friendly_id in `contexts` table
2. Recursively collect all claims from context tree
3. Return all claims

**Label:** `[REFERENCED @health_goals_context]`

---

### Claim Reference: `@prefer_morning_a3f2` (Unchanged)

Same as today, no suffix:
1. Look up claim by friendly_id in `claims` table
2. Return single claim

**Label:** `[REFERENCED @prefer_morning_a3f2]`

---

## DB Schema Changes

### Schema v7: Add friendly_id to entities and tags

```sql
-- Migration: Add friendly_id column to entities
ALTER TABLE entities ADD COLUMN friendly_id TEXT;
CREATE INDEX IF NOT EXISTS idx_entities_friendly_id ON entities(friendly_id);
-- Unique per user
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_user_friendly_id ON entities(user_email, friendly_id);

-- Migration: Add friendly_id column to tags
ALTER TABLE tags ADD COLUMN friendly_id TEXT;
CREATE INDEX IF NOT EXISTS idx_tags_friendly_id ON tags(friendly_id);
-- Unique per user  
CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_user_friendly_id ON tags(user_email, friendly_id);
```

### No Schema Change for Domains

Domains use `domain_name` as their key. The friendly_id is computed: `{domain_name}_domain`. No DB column needed.

### No Schema Change for Claims

Claim friendly_ids remain as-is (no suffix).

### Context Migration

Existing context friendly_ids need `_context` appended. This is a data migration:

```sql
-- Append _context to all existing context friendly_ids
UPDATE contexts 
SET friendly_id = friendly_id || '_context'
WHERE friendly_id IS NOT NULL 
  AND friendly_id NOT LIKE '%_context';
```

---

## Friendly ID Generation Rules

### Entity Friendly ID

```python
def generate_entity_friendly_id(name: str, entity_type: str) -> str:
    """
    Generate friendly_id for an entity.
    
    Format: {name_words}_{entity_type}_entity
    
    Examples:
        ("John Smith", "person") → "john_smith_person_entity"
        ("Google", "org") → "google_org_entity"
        ("Bengaluru", "place") → "bengaluru_place_entity"
        ("Machine Learning", "topic") → "machine_learning_topic_entity"
    """
    # Lowercase, remove non-alphanumeric
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', name.lower().strip())
    words = cleaned.split()
    
    # Take up to 3 meaningful words
    filtered = [w for w in words if w not in STOPWORDS and len(w) > 1]
    if not filtered:
        filtered = words[:2]
    id_words = filtered[:3]
    
    base = '_'.join(id_words)
    return f"{base}_{entity_type}_entity"
```

**Note:** No random suffix needed — entities are unique per (user_email, entity_type, name), so the deterministic friendly_id is already unique. If two entities have the same name but different types (e.g., "Apple" as org vs "Apple" as topic), the entity_type in the friendly_id disambiguates: `apple_org_entity` vs `apple_topic_entity`.

### Tag Friendly ID

```python
def generate_tag_friendly_id(name: str) -> str:
    """
    Generate friendly_id for a tag.
    
    Format: {name_words}_tag
    
    Examples:
        "fitness" → "fitness_tag"
        "morning routine" → "morning_routine_tag"
        "health/diet" → "health_diet_tag"
    """
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', name.lower().strip())
    words = cleaned.split()
    
    filtered = [w for w in words if w not in STOPWORDS and len(w) > 1]
    if not filtered:
        filtered = words[:2]
    id_words = filtered[:3]
    
    base = '_'.join(id_words)
    return f"{base}_tag"
```

**Note:** Tags are unique per (user_email, name, parent_tag_id). For child tags with the same name under different parents (unlikely), we could append a disambiguator later. For now, the simple scheme is sufficient.

### Context Friendly ID (Updated)

```python
def generate_context_friendly_id(name: str) -> str:
    """
    Generate friendly_id for a context.
    
    Format: {name_words}_context (changed from v0.6 which had no suffix)
    
    Examples:
        "Health Goals" → "health_goals_context"
        "Project Alpha" → "project_alpha_context"
    """
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', name.lower().strip())
    words = cleaned.split()
    
    filtered = [w for w in words if w not in STOPWORDS and len(w) > 1]
    if not filtered:
        filtered = words[:2]
    id_words = filtered[:3]
    
    base = '_'.join(id_words)
    return f"{base}_context"
```

### Domain Friendly ID

No generation needed — computed at reference time:

```python
def domain_to_friendly_id(domain_name: str) -> str:
    """Convert domain_name to friendly_id format."""
    return f"{domain_name}_domain"
    # "health" → "health_domain"
    # "life_ops" → "life_ops_domain"
```

### Claim Friendly ID (Unchanged)

```python
# Same as v0.6 — no suffix
generate_friendly_id("I prefer morning workouts") → "prefer_morning_workouts_a3f2"
```

**Safeguard:** When generating claim friendly_ids, we should check that the result does NOT end with any reserved suffix (`_context`, `_entity`, `_tag`, `_domain`). If it does, regenerate with a different random suffix. This is extremely unlikely (the 4-char random suffix would have to spell out `ntity`, `text`, etc.) but we add the guard for correctness.

---

## Backend Changes

### Files to Modify

#### 1. `truth_management_system/schema.py`

- Bump `SCHEMA_VERSION` to 7
- Add migration logic for `entities.friendly_id` and `tags.friendly_id` columns
- Add migration to append `_context` to existing context friendly_ids

#### 2. `truth_management_system/models.py`

- Add `friendly_id` field to `Entity` dataclass
- Add `friendly_id` field to `Tag` dataclass
- Update `ENTITY_COLUMNS` and `TAG_COLUMNS`
- Update `Entity.create()` to auto-generate friendly_id
- Update `Tag.create()` to auto-generate friendly_id
- Update `Context.create()` to use `_context` suffix

#### 3. `truth_management_system/utils.py`

- Add `generate_entity_friendly_id(name, entity_type)` function
- Add `generate_tag_friendly_id(name)` function
- Update `generate_friendly_id()` to check for reserved suffix collisions
- Add `RESERVED_SUFFIXES = ['_context', '_entity', '_tag', '_domain']` constant

#### 4. `truth_management_system/crud/entities.py`

- Add `get_by_friendly_id(friendly_id)` method
- Add `search_friendly_ids(prefix, limit)` method
- Update `add()` to auto-generate friendly_id if not present
- Add `resolve_claims(entity_id)` method — get all claims linked to this entity

#### 5. `truth_management_system/crud/tags.py`

- Add `get_by_friendly_id(friendly_id)` method
- Add `search_friendly_ids(prefix, limit)` method
- Update `add()` to auto-generate friendly_id if not present
- Add `resolve_claims(tag_id)` method — recursively get all claims with this tag + child tags

#### 6. `truth_management_system/interface/structured_api.py`

- Update `resolve_reference()` to handle suffix-based routing
- Add `resolve_entity_reference(friendly_id)` method
- Add `resolve_tag_reference(friendly_id)` method
- Add `resolve_domain_reference(domain_name)` method
- Update `autocomplete()` to include entities, tags, and domains

#### 7. `truth_management_system/constants.py`

- Add `RESERVED_FRIENDLY_ID_SUFFIXES` list
- Add `REFERENCE_TYPE_SUFFIXES` dict mapping suffix → type

#### 8. `Conversation.py`

- Update `_get_pkb_context()` — the `referenced_friendly_ids` loop already calls `resolve_reference()`, so no change needed if `resolve_reference()` handles new types correctly
- The formatting/labeling logic should work as-is since it's already generic: `[REFERENCED @fid]`

#### 9. `interface/parseMessageForCheckBoxes.js`

- No regex changes needed — the existing `/@([a-zA-Z][a-zA-Z0-9_-]{2,})/g` already matches suffixed IDs like `@fitness_tag` and `@john_smith_person_entity`

#### 10. `endpoints/pkb.py`

- Update autocomplete endpoint to include entities, tags, domains in results

---

## UI Changes

### Autocomplete Dropdown (Minimal Change)

The autocomplete dropdown already shows `memories` and `contexts`. We add three more categories:

```javascript
// Current response format:
{ memories: [...], contexts: [...] }

// New response format:
{ 
    memories: [...],    // Claim friendly_ids (no suffix)
    contexts: [...],    // Context friendly_ids (now with _context suffix)
    entities: [...],    // Entity friendly_ids (with _entity suffix)
    tags: [...],        // Tag friendly_ids (with _tag suffix)
    domains: [...]      // Domain friendly_ids (with _domain suffix)
}
```

### Display in Chat

References are displayed as-is. The suffix serves as a visual type indicator:

```
User: "Tell me about @john_smith_person_entity and my @fitness_tag habits"
```

The `_entity` and `_tag` suffixes tell the user (and the LLM) what type of object is being referenced. No extra badges or icons needed.

### PKB Manager Tab (No Change)

The PKB Manager already shows entities, tags, and contexts in separate tabs. No change needed there.

### Memory Reference Display in PKB Retrieval Details

The existing display already shows each referenced claim with its label. New types will appear as:

```
[REFERENCED @john_smith_person_entity] [fact] John's birthday is March 15
[REFERENCED @john_smith_person_entity] [preference] John prefers Italian food
[REFERENCED @fitness_tag] [habit] Run 3 times per week
[REFERENCED @health_domain] [fact] Blood type is O+
```

---

## Migration Strategy

### Phase 1: Schema Migration (v7)

1. Add `friendly_id TEXT` column to `entities` table
2. Add `friendly_id TEXT` column to `tags` table
3. Create indexes on new columns
4. Backfill existing entities with auto-generated friendly_ids
5. Backfill existing tags with auto-generated friendly_ids
6. Append `_context` to existing context friendly_ids

```python
def _migrate_to_v7(conn):
    """Add friendly_id to entities and tags, suffix contexts."""
    
    # 1. Add columns
    try:
        conn.execute("ALTER TABLE entities ADD COLUMN friendly_id TEXT")
    except Exception:
        pass  # Column already exists
    
    try:
        conn.execute("ALTER TABLE tags ADD COLUMN friendly_id TEXT")
    except Exception:
        pass  # Column already exists
    
    # 2. Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_friendly_id ON entities(friendly_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_friendly_id ON tags(friendly_id)")
    
    # 3. Backfill entities
    entities = conn.execute("SELECT entity_id, name, entity_type FROM entities WHERE friendly_id IS NULL").fetchall()
    for e in entities:
        fid = generate_entity_friendly_id(e['name'], e['entity_type'])
        conn.execute("UPDATE entities SET friendly_id = ? WHERE entity_id = ?", (fid, e['entity_id']))
    
    # 4. Backfill tags
    tags = conn.execute("SELECT tag_id, name FROM tags WHERE friendly_id IS NULL").fetchall()
    for t in tags:
        fid = generate_tag_friendly_id(t['name'])
        conn.execute("UPDATE tags SET friendly_id = ? WHERE tag_id = ?", (fid, t['tag_id']))
    
    # 5. Suffix contexts (only if not already suffixed)
    conn.execute("""
        UPDATE contexts 
        SET friendly_id = friendly_id || '_context'
        WHERE friendly_id IS NOT NULL 
          AND friendly_id NOT LIKE '%_context'
    """)
```

### Phase 2: Backwards Compatibility

- Old context references without `_context` suffix still work via the fallback path in `resolve_reference()`
- Claim references never had a suffix, so no migration needed
- Old code that creates contexts with `Context.create()` will automatically get the `_context` suffix

### Phase 3: Deprecation (Future)

- After a few releases, we can remove the legacy fallback path for unsuffixed context references
- Log warnings when fallback is used: "Consider using @{fid}_context instead of @{fid}"

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| **Claim friendly_id accidentally ends with `_context`** | Very Low | Medium | Add reserved-suffix check in `generate_friendly_id()`. Regenerate if collision. |
| **Entity name collision** (two entities same name, same type) | Already Prevented | N/A | DB has `UNIQUE(user_email, entity_type, name)` constraint |
| **Tag name collision** (two tags same name, different parent) | Low | Low | Add parent path to friendly_id if needed: `fitness_running_tag` vs `fitness_yoga_tag` |
| **Domain search returns too many claims** | Medium | Medium | Limit to 50 most recent. Use hybrid search with user query to rank. |
| **Migration breaks existing context references** | Medium | High | Keep fallback path for unsuffixed context references. Log deprecation warning. |
| **Performance: entity/tag with 1000+ linked claims** | Low | Medium | Limit returned claims. Use search ranking. |
| **Friendly_id uniqueness for entities/tags** | Low | Low | Entity: `name_type_entity` is unique by construction. Tag: add random suffix if collision detected. |
| **UI autocomplete becomes crowded** | Low | Low | Group by type in dropdown. Show max 5 per type. |

---

## Implementation Plan

### Milestone 1: Schema and Models (Estimated: 2-3 hours)

**Tasks:**

1.1. Update `schema.py`: Bump version to 7, add migration DDL  
1.2. Update `models.py`: Add `friendly_id` to `Entity` and `Tag` dataclasses, update column lists  
1.3. Update `utils.py`: Add `generate_entity_friendly_id()`, `generate_tag_friendly_id()`, reserved suffix check  
1.4. Update `constants.py`: Add `RESERVED_FRIENDLY_ID_SUFFIXES`  
1.5. Write and test migration function  
1.6. Update `database.py`: Add v7 migration to initialization flow  

**Verification:** Run `python -m pytest truth_management_system/tests/test_crud.py -v` — existing tests pass, new columns accessible.

### Milestone 2: CRUD Layer (Estimated: 2-3 hours)

**Tasks:**

2.1. Update `crud/entities.py`: Add `get_by_friendly_id()`, `search_friendly_ids()`, `resolve_claims()`  
2.2. Update `crud/tags.py`: Add `get_by_friendly_id()`, `search_friendly_ids()`, `resolve_claims()` (recursive)  
2.3. Update `crud/entities.py`: Auto-generate friendly_id on `add()` and `get_or_create()`  
2.4. Update `crud/tags.py`: Auto-generate friendly_id on `add()` and `get_or_create()`  
2.5. Update `crud/contexts.py`: Ensure new contexts get `_context` suffix  
2.6. Update `crud/claims.py`: Guard against reserved suffix in claim friendly_id generation  

**Verification:** Write unit tests for new CRUD methods. Run full test suite.

### Milestone 3: API Layer (Estimated: 2-3 hours)

**Tasks:**

3.1. Update `structured_api.py`: Suffix-based routing in `resolve_reference()`  
3.2. Add `resolve_entity_reference()` method  
3.3. Add `resolve_tag_reference()` method  
3.4. Add `resolve_domain_reference()` method  
3.5. Update `autocomplete()` to include entities, tags, domains  
3.6. Test the full resolution chain  

**Verification:** Manual test with `resolve_reference("fitness_tag")`, `resolve_reference("john_smith_person_entity")`, etc.

### Milestone 4: Conversation Integration (Estimated: 1 hour)

**Tasks:**

4.1. Verify `Conversation.py:_get_pkb_context()` works with new reference types (should work as-is if resolve_reference is updated)  
4.2. Verify formatting/labeling works for new types  
4.3. Verify re-injection (`_extract_referenced_claims()`) works for new labels  

**Verification:** End-to-end test: type `@fitness_tag some query` in chat, verify claims appear in PKB Retrieval Details.

### Milestone 5: UI (Estimated: 1-2 hours)

**Tasks:**

5.1. Update autocomplete endpoint in `endpoints/pkb.py` to return entities, tags, domains  
5.2. Update autocomplete dropdown rendering in `interface/pkb-manager.js` to show new categories  
5.3. Verify `parseMemoryReferences()` captures suffixed IDs correctly (should work as-is)  
5.4. Test end-to-end autocomplete flow  

**Verification:** Type `@fit` in chat input, see `fitness_tag` appear in autocomplete dropdown.

### Milestone 6: Migration and Testing (Estimated: 1-2 hours)

**Tasks:**

6.1. Test schema migration on existing database  
6.2. Verify backwards compatibility for existing context references (no suffix)  
6.3. Write integration tests for each reference type  
6.4. Update documentation  

**Verification:** Full test suite passes. Manual end-to-end verification.

---

## Testing Plan

### Unit Tests

```python
# test_crud.py additions

class TestEntityFriendlyId:
    def test_auto_generate_friendly_id(self):
        """Entity.create() auto-generates friendly_id with _entity suffix"""
        entity = Entity.create(name="John Smith", entity_type="person")
        assert entity.friendly_id.endswith("_entity")
        assert "john" in entity.friendly_id
    
    def test_get_by_friendly_id(self):
        """EntityCRUD.get_by_friendly_id() returns entity"""
        entity = Entity.create(name="Google", entity_type="org")
        crud.add(entity)
        found = crud.get_by_friendly_id(entity.friendly_id)
        assert found.entity_id == entity.entity_id
    
    def test_resolve_claims(self):
        """EntityCRUD.resolve_claims() returns linked claims"""
        # Create entity, create claims, link them, verify resolution

class TestTagFriendlyId:
    def test_auto_generate_friendly_id(self):
        """Tag.create() auto-generates friendly_id with _tag suffix"""
        tag = Tag.create(name="fitness")
        assert tag.friendly_id == "fitness_tag"
    
    def test_resolve_claims_recursive(self):
        """TagCRUD.resolve_claims() includes child tag claims"""
        # Create parent tag, child tag, claims for each, verify all returned

class TestResolveReference:
    def test_entity_suffix_routing(self):
        """resolve_reference() routes _entity suffix correctly"""
        result = api.resolve_reference("john_smith_person_entity")
        assert result.data['type'] == 'entity'
    
    def test_tag_suffix_routing(self):
        """resolve_reference() routes _tag suffix correctly"""
        result = api.resolve_reference("fitness_tag")
        assert result.data['type'] == 'tag'
    
    def test_domain_suffix_routing(self):
        """resolve_reference() routes _domain suffix correctly"""
        result = api.resolve_reference("health_domain")
        assert result.data['type'] == 'domain'
    
    def test_backwards_compat_claim(self):
        """resolve_reference() still finds claims without suffix"""
        result = api.resolve_reference("prefer_morning_a3f2")
        assert result.data['type'] == 'claim'
    
    def test_backwards_compat_context_no_suffix(self):
        """resolve_reference() still finds old contexts without _context suffix"""
        result = api.resolve_reference("ssdva")
        assert result.data['type'] == 'context'
    
    def test_claim_friendly_id_no_reserved_suffix(self):
        """Claim friendly_ids never end with reserved suffixes"""
        for _ in range(100):
            fid = generate_friendly_id("Some statement about context and entity and tag")
            for suffix in RESERVED_SUFFIXES:
                assert not fid.endswith(suffix)
```

### Integration Tests

```python
class TestEndToEndReference:
    def test_entity_in_chat(self):
        """Type @entity_ref in chat → claims about entity appear in context"""
    
    def test_tag_in_chat(self):
        """Type @tag_ref in chat → tagged claims appear in context"""
    
    def test_domain_in_chat(self):
        """Type @domain_ref in chat → domain claims appear in context"""
    
    def test_mixed_references(self):
        """Type @claim_ref @entity_ref @tag_ref → all appear in context"""
```

### Manual Testing Checklist

- [ ] Create entity "John Smith" (person) → friendly_id is `john_smith_person_entity`
- [ ] Create tag "fitness" → friendly_id is `fitness_tag`
- [ ] Create context "Health Goals" → friendly_id is `health_goals_context`
- [ ] Type `@john` in chat → autocomplete shows `john_smith_person_entity`
- [ ] Type `@fit` in chat → autocomplete shows `fitness_tag`
- [ ] Type `@health` in chat → autocomplete shows `health_domain`, `health_goals_context`, and any health claims
- [ ] Send message with `@fitness_tag what are my habits?` → tagged claims appear in PKB Retrieval Details
- [ ] Send message with `@health_domain summary` → health claims appear in PKB Retrieval Details
- [ ] Old context reference `@ssdva` (no suffix) still works → backwards compat
- [ ] Old claim reference `@prefer_morning_a3f2` still works → backwards compat
- [ ] Schema migration on existing v6 database succeeds
- [ ] All existing unit tests pass after migration

---

## Summary

**Key Design Decisions:**

1. **Type suffix for disambiguation:** `_context`, `_entity`, `_tag`, `_domain` — no namespace clashes possible
2. **Claims keep no suffix:** Most common reference type, backwards compatible
3. **Suffix enables fast routing:** Backend parses suffix and routes directly, no sequential fallback needed
4. **Self-documenting UI:** The suffix IS the type indicator, no extra UI elements needed
5. **Backwards compatible:** Old references without suffixes still work via fallback path
6. **Deterministic entity/tag IDs:** No random suffix needed (unique by DB constraint)
7. **Domain references computed:** No DB column, just `{domain_name}_domain`

**Files Modified (Summary):**
- `truth_management_system/schema.py` — Schema v7, migration
- `truth_management_system/models.py` — Entity/Tag friendly_id fields
- `truth_management_system/utils.py` — New generation functions
- `truth_management_system/constants.py` — Reserved suffixes
- `truth_management_system/crud/entities.py` — friendly_id CRUD
- `truth_management_system/crud/tags.py` — friendly_id CRUD
- `truth_management_system/crud/contexts.py` — _context suffix
- `truth_management_system/crud/claims.py` — Reserved suffix guard
- `truth_management_system/interface/structured_api.py` — Routing logic
- `endpoints/pkb.py` — Autocomplete expansion
- `interface/pkb-manager.js` — Autocomplete dropdown categories

**No Changes Needed:**
- `interface/parseMessageForCheckBoxes.js` — Regex already captures suffixed IDs
- `Conversation.py` — Already generic; calls `resolve_reference()` which we update

---

**End of Plan**
