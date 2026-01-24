# PKB v0 API Reference

Public API documentation for the Personal Knowledge Base module.

## Quick Start

```python
from truth_management_system import (
    PKBConfig, get_database, StructuredAPI, TextOrchestrator
)

# 1. Initialize
config = PKBConfig(db_path="./my_knowledge.sqlite")
db = get_database(config)
keys = {"OPENROUTER_API_KEY": "sk-or-v1-..."}  # For LLM features
api = StructuredAPI(db, keys, config)

# 2. Add a claim
result = api.add_claim(
    statement="I prefer morning workouts over evening ones",
    claim_type="preference",
    context_domain="health",
    auto_extract=True  # Auto-generate tags/entities
)
print(f"Added claim: {result.data.claim_id}")

# 3. Search
results = api.search("what are my workout preferences?", k=10)
for r in results.data:
    print(f"- {r.claim.statement} (score: {r.score:.2f})")

# 4. Natural language commands
orchestrator = TextOrchestrator(api, keys)
result = orchestrator.process("remember that I like coffee with oat milk")
```

---

## Configuration

### `PKBConfig`

Configuration dataclass for the PKB instance.

```python
from truth_management_system import PKBConfig, load_config

# Option 1: Direct instantiation
config = PKBConfig(
    db_path="~/.pkb/kb.sqlite",    # Database location
    fts_enabled=True,              # Enable FTS5 search
    embedding_enabled=True,        # Enable semantic search
    default_k=20,                  # Default search results
    llm_model="openai/gpt-4o-mini" # Model for extraction
)

# Option 2: Load from file/env
config = load_config(
    config_file="~/.pkb/config.json",
    config_dict={"db_path": "./override.sqlite"}
)
```

**Configuration Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `db_path` | str | "~/.pkb/kb.sqlite" | SQLite database path |
| `fts_enabled` | bool | True | Enable full-text search |
| `embedding_enabled` | bool | True | Enable embedding search |
| `default_k` | int | 20 | Default result count |
| `include_contested_by_default` | bool | True | Include contested claims in search |
| `llm_model` | str | "openai/gpt-4o-mini" | LLM for extraction |
| `llm_temperature` | float | 0.0 | Deterministic extraction |
| `max_parallel_llm_calls` | int | 8 | Concurrent LLM calls |
| `log_llm_calls` | bool | True | Log LLM interactions |

---

## Core API: StructuredAPI

The main programmatic interface for all PKB operations.

### Initialization

```python
from truth_management_system import PKBConfig, get_database, StructuredAPI

config = PKBConfig(db_path="./kb.sqlite")
db = get_database(config)
keys = {"OPENROUTER_API_KEY": "your-key"}  # Optional but recommended

# Single-user mode
api = StructuredAPI(db, keys, config)

# Multi-user mode (all operations scoped to user)
api = StructuredAPI(db, keys, config, user_email="user@example.com")

# Or create user-scoped instance from shared API
shared_api = StructuredAPI(db, keys, config)
user_api = shared_api.for_user("user@example.com")
```

### Multi-User Support

```python
# Initialize with user_email for per-user data isolation
user_api = StructuredAPI(db, keys, config, user_email="alice@example.com")
# Or use factory: shared_api.for_user("alice@example.com")

# All operations auto-scoped: alice_api.add_claim(...) → Alice's data only
```

**Key Points:** `user_email` scopes all records; unique constraints are per-user; search auto-filters by user

### ActionResult

All API methods return `ActionResult`:

```python
@dataclass
class ActionResult:
    success: bool           # Operation succeeded?
    action: str             # What was done (add, edit, delete, search, etc.)
    object_type: str        # Type affected (claim, note, entity, tag)
    object_id: str          # ID of primary object (if applicable)
    data: Any               # Result data (object, list, etc.)
    warnings: List[str]     # Non-fatal warnings
    errors: List[str]       # Error messages if failed
```

---

## Claims API

Claims are atomic memory units: facts, preferences, decisions, tasks, etc.

### Add Claim

```python
result = api.add_claim(
    statement="I decided to switch to decaf coffee",
    claim_type="decision",           # fact, memory, decision, preference, task, reminder, habit, observation
    context_domain="health",         # personal, health, relationships, learning, life_ops, work, finance
    tags=["coffee", "health"],       # Optional: manual tags
    entities=[                       # Optional: manual entities
        {"type": "topic", "name": "coffee", "role": "object"}
    ],
    auto_extract=True,               # Use LLM to extract tags/entities
    confidence=0.9,                  # Optional: confidence score
    valid_from="2024-01-01T00:00:00Z",  # Optional: temporal validity
    valid_to=None,                   # None = valid forever
    meta_json='{"source": "chat"}'   # Optional: custom metadata
)

if result.success:
    claim = result.data
    print(f"Created: {claim.claim_id}")
    print(f"Warnings: {result.warnings}")  # e.g., similar claims found
```

### Edit Claim

```python
result = api.edit_claim(
    claim_id="abc123...",
    statement="I decided to quit coffee entirely",  # Update text
    confidence=0.95                                  # Update score
)

if result.success:
    print(f"Updated: {result.data.statement}")
```

### Delete Claim (Soft Delete)

```python
result = api.delete_claim(claim_id="abc123...")

if result.success:
    # Claim status is now "retracted"
    print(f"Retracted at: {result.data.retracted_at}")
```

### Get Claim

```python
result = api.get_claim(claim_id="abc123...")

if result.success:
    claim = result.data
    print(f"Statement: {claim.statement}")
    print(f"Type: {claim.claim_type}")
    print(f"Status: {claim.status}")
```

---

## Search API

Multiple search strategies for finding relevant claims.

### Basic Search

```python
result = api.search(
    query="what are my coffee preferences?",
    strategy="hybrid",      # hybrid, fts, embedding, rerank
    k=10,                   # Number of results
    include_contested=True  # Include contested claims (with warnings)
)

for search_result in result.data:
    claim = search_result.claim
    print(f"[{search_result.score:.3f}] {claim.statement}")
    if search_result.warnings:
        print(f"  ⚠️ {search_result.warnings}")
```

### Search with Filters

```python
from truth_management_system import SearchFilters

# Search with specific filters
result = api.search(
    query="health decisions",
    filters={
        "context_domains": ["health", "personal"],
        "claim_types": ["decision", "preference"],
        "statuses": ["active"],  # Exclude contested
        "valid_at": "2024-06-15T00:00:00Z"  # Valid at this time
    }
)
```

### Search Strategies

| Strategy | Speed | Cost | Best For |
|----------|-------|------|----------|
| `fts` | ⚡ Fast | Free | Exact keyword matches |
| `embedding` | Medium | API | Conceptual/semantic queries |
| `hybrid` | Medium | API | General use (default, recommended) |
| `rerank` | Slow | More API | High-precision requirements |

**Hybrid** runs FTS + Embedding in parallel, merges via RRF, optionally applies LLM reranking.

### Search Notes

```python
result = api.search_notes(
    query="meeting notes about project X",
    k=10,
    context_domain="work"  # Optional filter
)
```

---

## Notes API

Notes store longer narrative content.

### Add Note

```python
result = api.add_note(
    body="Detailed meeting notes about project X...",
    title="Project X Kickoff Meeting",
    context_domain="work",
    meta_json='{"meeting_date": "2024-01-15"}'
)
```

### Edit Note

```python
result = api.edit_note(
    note_id="xyz789...",
    body="Updated meeting notes...",
    title="Project X Kickoff - Updated"
)
```

### Delete Note

```python
result = api.delete_note(note_id="xyz789...")
```

---

## Entities API

Entities are canonical references (people, places, topics).

### Add Entity

```python
result = api.add_entity(
    name="Dr. Smith",
    entity_type="person",  # person, org, place, topic, project, system, other
    meta_json='{"specialty": "cardiology"}'
)
```

### Get or Create Entity

```python
# Using lower-level CRUD (via api.entities)
entity, was_created = api.entities.get_or_create(
    name="Mom",
    entity_type="person"
)
print(f"Entity ID: {entity.entity_id}, Created: {was_created}")
```

### Find Claims by Entity

```python
# Get all claims mentioning an entity
claims = api.claims.get_by_entity(
    entity_id="entity-uuid...",
    role="subject"  # Optional: filter by role
)
```

---

## Tags API

Tags provide hierarchical organization.

### Add Tag

```python
# Root tag
result = api.add_tag(name="health")

# Child tag
result = api.add_tag(
    name="fitness",
    parent_tag_id=health_tag_id
)
```

### Tag Hierarchy

```python
# Get all descendant tags
children = api.tags.get_hierarchy(root_tag_id)

# Get full path
path = api.tags.get_full_path(tag_id)  # "health/fitness/running"
```

### Find Claims by Tag

```python
claims = api.claims.get_by_tag(
    tag_id="tag-uuid...",
    include_children=True  # Include child tags
)
```

---

## Conflicts API

Manage contradicting claims.

### Create Conflict Set

```python
result = api.create_conflict_set(
    claim_ids=["claim-1-id", "claim-2-id"],
    notes="These claims about diet seem to contradict"
)
```

### Resolve Conflict

```python
result = api.resolve_conflict_set(
    conflict_set_id="conflict-uuid...",
    resolution_notes="Claim 1 is more recent and accurate",
    winning_claim_id="claim-1-id"  # Optional: mark winner as active
)
```

### Get Open Conflicts

```python
result = api.get_open_conflicts()
for conflict in result.data:
    print(f"Conflict: {conflict.conflict_set_id}")
    print(f"Claims: {conflict.member_claim_ids}")
```

---

## Natural Language Interface: TextOrchestrator

Parse and execute natural language commands.

### Initialization

```python
from truth_management_system import TextOrchestrator

orchestrator = TextOrchestrator(api, keys, config)
```

### Process Commands

```python
# Add fact
result = orchestrator.process("remember that I'm allergic to shellfish")
print(result.action_taken)  # "Added fact: I'm allergic to shellfish..."

# Search
result = orchestrator.process("what do I know about my allergies?")
for search_result in result.action_result.data:
    print(f"- {search_result.claim.statement}")

# Delete (requires confirmation)
result = orchestrator.process("delete the reminder about dentist")
if result.clarifying_questions:
    print(result.clarifying_questions[0])  # "Which claim would you like to delete?"
```

### OrchestrationResult

```python
@dataclass
class OrchestrationResult:
    action_taken: str              # What was done
    action_result: ActionResult    # API result
    clarifying_questions: List[str]  # Questions if unclear
    affected_objects: List[Dict]   # Objects affected
    raw_intent: Dict               # Parsed intent (for debugging)
```

### Supported Commands

| Command Pattern | Action |
|-----------------|--------|
| "remember that...", "add fact...", "save that..." | Add claim |
| "find...", "search...", "what do I know about..." | Search |
| "update...", "change...", "edit..." | Edit (with confirmation) |
| "delete...", "remove...", "forget..." | Delete (with confirmation) |
| "show conflicts", "list conflicts" | List open conflicts |

### Execute Confirmed Action

After user selects from search results:

```python
# User selected claim to delete
result = orchestrator.execute_confirmed_action(
    action="delete_claim",
    target_id="claim-uuid..."
)
```

---

## Bulk Operations

Add multiple claims at once and intelligently ingest text into the PKB.

### Bulk Add Claims

Add multiple claims in a single operation:

```python
result = api.add_claims_bulk(
    claims=[
        {
            "statement": "I prefer morning workouts",
            "claim_type": "preference",
            "context_domain": "health",
            "tags": ["fitness", "routine"]
        },
        {
            "statement": "I'm allergic to shellfish",
            "claim_type": "fact",
            "context_domain": "health"
        },
        {
            "statement": "My favorite color is blue",
            "claim_type": "preference",
            "context_domain": "personal"
        }
    ],
    auto_extract=True,   # Use LLM to extract entities/tags
    stop_on_error=False  # Continue on individual failures
)

if result.success:
    print(f"Added {result.data['added_count']} claims")
    for r in result.data['results']:
        if r['success']:
            print(f"✓ Claim {r['claim_id'][:8]}")
        else:
            print(f"✗ Error: {r['error']}")
```

### Text Ingestion with AI Analysis

Parse freeform text into structured claims with intelligent duplicate detection:

```python
from truth_management_system import TextIngestionDistiller

distiller = TextIngestionDistiller(api, keys, config)

# Analyze and propose actions
plan = distiller.ingest_and_propose(
    text="""
    I prefer working in the morning.
    My favorite programming language is Python.
    I'm trying to reduce my caffeine intake.
    - I take my coffee with oat milk
    - Allergic to peanuts
    """,
    default_claim_type='fact',
    default_domain='personal',
    use_llm_parsing=True  # AI-powered parsing vs simple line split
)

# Review proposals
print(f"Extracted {len(plan.candidates)} candidates")
print(f"Proposed: {plan.add_count} adds, {plan.edit_count} edits, {plan.skip_count} skips")

for proposal in plan.proposals:
    print(f"- [{proposal.action}] {proposal.candidate.statement}")
    if proposal.existing_claim:
        print(f"  → Updates: {proposal.existing_claim.statement[:50]}...")
        print(f"  Similarity: {proposal.similarity_score:.2f}")

# Execute approved actions
approved = [
    {"index": 0, "statement": "I prefer working in the morning"},
    {"index": 1},  # Use original values
    {"index": 3, "claim_type": "preference"}  # Override type
]

result = distiller.execute_plan(plan, approved)
print(f"Executed: {result.added_count} added, {result.edited_count} edited")
```

### TextIngestionPlan

```python
@dataclass
class TextIngestionPlan:
    plan_id: str                      # UUID for this plan
    raw_text: str                     # Original input text
    candidates: List[IngestCandidate]  # Extracted candidates
    proposals: List[IngestProposal]   # Proposed actions
    add_count: int                    # Count of 'add' proposals
    edit_count: int                   # Count of 'edit' proposals
    skip_count: int                   # Count of 'skip' proposals
    summary: str                      # Human-readable summary
```

### IngestProposal

```python
@dataclass
class IngestProposal:
    action: str                       # 'add', 'edit', 'skip'
    candidate: IngestCandidate        # The extracted claim
    existing_claim: Optional[Claim]   # Matched claim (for edit/skip)
    similarity_score: Optional[float] # Match score (0-1)
    reason: str                       # Why this action was proposed
    editable: bool = True             # Can user edit before saving?
```

### Action Thresholds

| Similarity Score | Action | Description |
|------------------|--------|-------------|
| ≥ 0.92 | `skip` | Exact duplicate, don't add |
| ≥ 0.75 | `edit` | Similar enough to update existing |
| ≥ 0.55 | `add` (with warning) | Related claim exists |
| < 0.55 | `add` | New claim, no match |

---

## Conversation Distillation

Extract facts from chat conversations for memory storage.

### Initialization

```python
from truth_management_system import ConversationDistiller

distiller = ConversationDistiller(api, keys, config)
```

### Extract and Propose

```python
# From a chat conversation turn
plan = distiller.extract_and_propose(
    conversation_summary="User asked about diet recommendations...",
    user_message="I've been trying to eat more vegetables lately",
    assistant_message="That's great! Vegetables are rich in nutrients..."
)

# Review proposed actions
print(f"Found {len(plan.candidates)} memorable facts")
for action in plan.proposed_actions:
    print(f"- {action.action}: {action.candidate.statement}")
    if action.existing_claim:
        print(f"  (Similar to: {action.existing_claim.claim_id[:8]})")

# Show user prompt for confirmation
print(plan.user_prompt)
```

### Execute Approved Actions

```python
# After user approves (e.g., "yes to all" or "1, 3")
result = distiller.execute_plan(
    plan=plan,
    user_response="yes",  # or "1, 3" for specific items
    approved_indices=[0, 1]  # Alternatively, explicit indices
)

print(f"Executed: {result.executed}")
for action_result in result.execution_results:
    if action_result.success:
        print(f"✓ Added: {action_result.object_id}")
```

### MemoryUpdatePlan

```python
@dataclass
class MemoryUpdatePlan:
    candidates: List[CandidateClaim]     # Extracted facts
    existing_matches: List[Tuple]        # Matches with existing claims
    proposed_actions: List[ProposedAction]  # add, update, skip, conflict
    user_prompt: str                     # Generated prompt for user
    requires_user_confirmation: bool     # Always true
```

### ProposedAction Types

| Action | Description |
|--------|-------------|
| `add` | New fact, no existing match |
| `update` | Similar existing claim, propose update |
| `skip` | Duplicate exists |
| `conflict` | Contradicts existing claim |
| `retract` | Suggests retracting existing claim |

---

## Data Types Reference

### Claim Types

| Type | Description | Example |
|------|-------------|---------|
| `fact` | Stable assertions | "My home city is Bengaluru" |
| `memory` | Episodic experiences | "I enjoyed that restaurant last week" |
| `decision` | Commitments | "I decided to avoid processed foods" |
| `preference` | Likes/dislikes | "I prefer morning workouts" |
| `task` | Actionable items | "Need to buy medication" |
| `reminder` | Future prompts | "Remind me to call mom Friday" |
| `habit` | Recurring targets | "Sleep by 11pm" |
| `observation` | Low-commitment notes | "Noticed knee pain after running" |

### Context Domains

| Domain | Description |
|--------|-------------|
| `personal` | General personal facts |
| `health` | Health, medical, fitness |
| `relationships` | Family, friends, social |
| `learning` | Education, skills, knowledge |
| `life_ops` | Daily operations, logistics |
| `work` | Professional, career |
| `finance` | Financial matters |

### Claim Statuses

| Status | Description | In Search? |
|--------|-------------|------------|
| `active` | Currently valid | Yes |
| `contested` | In conflict (shown with warnings) | Yes |
| `historical` | No longer current but preserved | No (by default) |
| `superseded` | Replaced by newer claim | No (by default) |
| `retracted` | Soft-deleted | No |
| `draft` | Not yet confirmed | No (by default) |

### Entity Types

| Type | Description |
|------|-------------|
| `person` | People (Mom, Dr. Smith) |
| `org` | Organizations (Google, gym) |
| `place` | Locations (Bengaluru, cafe) |
| `topic` | Abstract topics (machine learning) |
| `project` | Projects (home renovation) |
| `system` | Technical systems (this PKB) |
| `other` | Catch-all |

### Entity Roles

| Role | Description |
|------|-------------|
| `subject` | Entity performing action |
| `object` | Entity receiving action |
| `mentioned` | Referenced but not central |
| `about_person` | Claim is about this person |

---

## Search Filters

```python
from truth_management_system import SearchFilters

filters = SearchFilters(
    statuses=["active", "contested"],  # Default
    context_domains=["health", "personal"],
    claim_types=["preference", "decision"],
    tag_ids=["tag-1", "tag-2"],
    entity_ids=["entity-1"],
    valid_at="2024-06-15T00:00:00Z",
    include_contested=True,
    user_email="user@example.com"  # For multi-user filtering
)

result = api.search("query", filters=filters.to_dict())
```

---

## LLM Helpers

Direct access to LLM extraction utilities.

```python
from truth_management_system import LLMHelpers

llm = LLMHelpers(keys, config)

# Generate tags
tags = llm.generate_tags(
    statement="I prefer running in the morning",
    context_domain="health",
    existing_tags=["fitness", "routine"]  # Prefer reusing
)
# ['morning_running', 'fitness', 'exercise']

# Extract entities
entities = llm.extract_entities("My mom recommended this doctor")
# [{'type': 'person', 'name': 'Mom', 'role': 'subject'},
#  {'type': 'person', 'name': 'doctor', 'role': 'object'}]

# Extract SPO
spo = llm.extract_spo("I prefer morning workouts")
# {'subject': 'I', 'predicate': 'prefer', 'object': 'morning workouts'}

# Classify type
claim_type = llm.classify_claim_type("I decided to quit smoking")
# 'decision'

# Check similarity
similar = llm.check_similarity(
    new_claim="I like morning exercise",
    existing_claims=claims_list,
    threshold=0.85
)
# [(claim, 0.92, 'related'), (claim2, 0.88, 'duplicate')]

# Batch extraction
results = llm.batch_extract_all(
    statements=["Statement 1", "Statement 2"],
    context_domain="personal"
)
# [ExtractionResult, ExtractionResult]
```

---

## Convenience Function

Quick setup with minimal code:

```python
from truth_management_system import create_pkb

# One-liner setup
api, db, config = create_pkb(
    db_path="./my_kb.sqlite",
    api_key="sk-or-v1-..."
)

# Ready to use
api.add_claim(
    statement="Quick test",
    claim_type="observation",
    context_domain="personal"
)
```

---

## Use Cases

| Use Case | Claim Type | Pattern |
|----------|------------|---------|
| Personal Assistant | various | `ConversationDistiller.extract_and_propose()` → confirm → `execute_plan()` |
| Health Tracking | observation | `add_claim(type="observation", domain="health")` → `search(filters={"context_domains":["health"]})` |
| Decision Log | decision | `add_claim(type="decision", confidence=0.9)` → search by `claim_types: ["decision"]` |
| Task/Reminder | task, reminder | Use `valid_from`/`valid_to` for time-bound reminders |
| Conflict Detection | any | Check `result.warnings` for "contradict" after `add_claim(auto_extract=True)` |

---

## Error Handling, Performance & Logging

```python
result = api.add_claim(...)
if not result.success: print(result.errors)    # Fatal errors
else: print(result.warnings)                    # Non-fatal (similar claims found, etc.)

# Debug logging
import logging
logging.getLogger("truth_management_system").setLevel(logging.DEBUG)
```

**Performance:** Use `auto_extract=False` when not needed; filter early; embeddings auto-cached.

## Meta JSON

Standard keys: `keywords` (search), `source` (manual|chat_distillation|import), `visibility` (default|restricted|shareable), `llm` (model info)

```python
api.add_claim(statement="...", meta_json='{"source": "chat_distillation"}')
# Read: parse_meta_json(claim.meta_json)
```

---

## Chatbot Integration Pattern

```python
# Key components: StructuredAPI (CRUD), ConversationDistiller (extract facts), TextOrchestrator (NL commands)
api = StructuredAPI(db, keys, config, user_email="user@example.com")
distiller = ConversationDistiller(api, keys, config)

# After each chat turn: extract → propose → confirm → execute
plan = distiller.extract_and_propose(summary, user_msg, assistant_msg)
if plan.proposed_actions:
    distiller.execute_plan(plan, "yes")  # or user_response

# Recall context for LLM prompt
results = api.search("diet preferences", k=5)
context = [r.claim.statement for r in results.data]
```

---

## Flask Server Integration (REST API)

REST endpoints at `/pkb/*` require authentication. All use JSON content-type.

### All Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/claims` | List claims (query params: status, claim_type, context_domain, limit, offset) |
| POST | `/pkb/claims` | Add claim `{statement, claim_type, context_domain, auto_extract}` |
| GET/PUT/DELETE | `/pkb/claims/<id>` | Get/Edit/Soft-delete claim |
| POST | `/pkb/claims/bulk` | Bulk add `{claims: [...], auto_extract}` |
| POST | `/pkb/search` | Search `{query, strategy, k, filters}` |
| GET | `/pkb/entities`, `/pkb/tags` | List entities/tags for user |
| GET | `/pkb/conflicts` | List open conflicts |
| POST | `/pkb/conflicts/<id>/resolve` | Resolve `{winning_claim_id?, resolution_notes}` |
| POST | `/pkb/ingest_text` | AI text parsing `{text, default_claim_type, default_domain, use_llm}` |
| POST | `/pkb/execute_ingest` | Execute `{plan_id, approved: [{index, statement?, ...}]}` |
| POST | `/pkb/propose_updates` | Extract from chat `{conversation_summary, user_message, assistant_message}` |
| POST | `/pkb/execute_updates` | Execute `{plan_id, approved_indices}` or `{plan_id, approved: [{index, ...}]}` |
| POST | `/pkb/relevant_context` | Get context `{query, conversation_summary, k}` |

**Example (typical pattern):**

```javascript
// Add claim
fetch('/pkb/claims', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({statement:"I prefer tea", claim_type:"preference", context_domain:"personal"})
});

// Search
fetch('/pkb/search', {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify({query:"preferences", strategy:"hybrid", k:10})
});
```

### Frontend (pkb-manager.js)

```javascript
// Global PKBManager API
PKBManager.listClaims({status:'active'});  PKBManager.addClaim({...});  PKBManager.searchClaims("query");
PKBManager.checkMemoryUpdates(summary, userMsg, assistantMsg);  PKBManager.openPKBModal();
// Bulk: addBulkRow(), saveBulkClaims(), analyzeTextForIngestion(), saveSelectedProposals()
```

**Modal Tabs:** My Memories | Add Memory | Bulk Add | Import Text | Search

### Conversation.py Integration

PKB context fetched async in `reply()` via `_get_pkb_context()`, injected into system prompt. See implementation.md for details.

---

## Data Migration

```bash
python -m truth_management_system.migrate_user_details --dry-run  # Preview
python -m truth_management_system.migrate_user_details --user alice@example.com  # Migrate
```

Options: `--users-db`, `--pkb-db`, `--dry-run`, `--user`, `--verbose`

### Schema Migration

The PKB automatically handles schema upgrades:

```python
# Schema version is tracked in schema_version table
# Current version: 2 (added user_email column)

# Migration happens automatically on get_database()
db = get_database(config)  # Runs migrations if needed
```

**Schema Versions:**
- **v1**: Initial schema (single-user)
- **v2**: Added `user_email` column and indexes for multi-user support

---

## Dependencies

- **Required:** Python 3.9+, numpy (`pip install numpy`)
- **Optional:** OPENROUTER_API_KEY (for LLM features: auto_extract, embedding search, ConversationDistiller)
- **Without API Key:** FTS search and `auto_extract=False` still work

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No search results | Check `api.claims.list(limit=10)` exists; try `strategy="fts"`; broaden filters |
| Stale embeddings | `EmbeddingStore(db,keys,config).compute_and_store(claim)` |
| LLM fails | Verify API key; use `auto_extract=False` as fallback |
| Database locked | `db.close(); db = get_database(config)` or use context manager |
| Contested warnings | Expected; use `include_contested=False` or filter `r.is_contested` |
| UI works but Conversation.py doesn't | **Check database paths match** - server.py uses `storage/users/pkb.sqlite`, ensure Conversation.py uses the same path |
| Embedding search fails with "ambiguous truth value" | Numpy array issue - fixed in v0.4.1. Ensure `if query_emb is not None:` not `if query_emb:` |
| Search logs not appearing | Use `time_logger.info()` instead of `logger.debug()` for guaranteed visibility |

---

## Deliberate Memory Attachment

Force specific memories into LLM context:

| Mechanism | Scope | Persistence | Priority |
|-----------|-------|-------------|----------|
| **@memory Reference** | Single message | One-shot | Highest |
| **"Use in Next Message"** | Single message | One-shot | High |
| **Global Pinning** | All conversations | Persistent (meta_json) | Medium-high |
| **Conversation Pinning** | Current session | Ephemeral | Medium |

### Python API

```python
api.pin_claim(claim_id, pin=True)  # Global pin/unpin
api.get_pinned_claims(limit=50)    # Get all globally pinned
api.get_claims_by_ids([...])       # Batch fetch
```

### REST Endpoints

| Method | Endpoint | Body/Params |
|--------|----------|-------------|
| POST | `/pkb/claims/<id>/pin` | `{pin: true/false}` |
| GET | `/pkb/pinned` | - |
| POST | `/pkb/conversation/<conv_id>/pin` | `{claim_id, pin}` |
| GET/DELETE | `/pkb/conversation/<conv_id>/pinned` | - |

### Frontend (PKBManager)

```javascript
// Global: pinClaim(id,true), getPinnedClaims(), togglePinAndRefresh(id)
// Conversation: pinToConversation(convId,claimId,true), getConversationPinned(convId)
// Use Now: addToNextMessage(id), getPendingAttachments(), clearPendingAttachments()
```

### @memory References

Use `@memory:claim_id` or `@mem:claim_id` in messages. Auto-parsed and included with highest priority.

### Context Format to LLM

```
[REFERENCED] [preference] I prefer morning meetings
[GLOBAL PINNED] [fact] My timezone is IST
[AUTO] [preference] I like detailed explanations
```

---

## Version History

| Version | Features |
|---------|----------|
| **v0.4.1** | Bug fixes: Fixed database path mismatch between server.py and Conversation.py; Fixed numpy array truthiness check in embedding search; Added time_logger for guaranteed log visibility in search modules |
| **v0.4.0** | Deliberate Memory Attachment: global/conversation pinning, "Use Now", @memory refs, priority merging |
| **v0.3.0** | Bulk operations: `add_claims_bulk()`, `TextIngestionDistiller`, text ingestion endpoints, enhanced approval modal |
| **v0.2.0** | Multi-user (`user_email` scoping), schema migration v1→v2, Flask REST API, `pkb-manager.js`, Conversation.py integration |
| **v0.1.0** | Initial: SQLite/WAL, FTS5, embedding search, hybrid RRF, LLM extraction, text orchestration, conversation distillation |
