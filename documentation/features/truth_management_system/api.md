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

### Link/Unlink Tags to Claims

```python
# Link a tag to a claim (two-way: claim gets the tag, tag's claims list includes the claim)
result = api.link_tag_to_claim(claim_id="claim-uuid...", tag_id="tag-uuid...")

# Unlink a tag from a claim
result = api.unlink_tag_from_claim(claim_id="claim-uuid...", tag_id="tag-uuid...")

# Get all tags for a claim
result = api.get_claim_tags_list(claim_id="claim-uuid...")
# result.data -> list of Tag objects
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

REST endpoints at `/pkb/*` require authentication (`@login_required`). All use JSON content-type.

**Implementation:** `endpoints/pkb.py` (Flask Blueprint `pkb_bp`), registered via `endpoints/__init__.py`.

**Authentication Chain:**
```
Flask session (set at login)
    → @login_required (endpoints/auth.py)
    → get_session_identity() (endpoints/session_utils.py) → (email, name, loggedin)
    → get_pkb_api_for_user(email, keys) → StructuredAPI(db, keys, config, user_email=email)
```

All operations are automatically scoped to the authenticated user's data.

### All Endpoints

| Method | Endpoint | Description | Rate Limit |
|--------|----------|-------------|------------|
| GET | `/pkb/claims` | List claims (query: status, claim_type, context_domain, limit, offset) | 30/min |
| POST | `/pkb/claims` | Add claim `{statement, claim_type, context_domain, auto_extract}` | 15/min |
| GET | `/pkb/claims/<id>` | Get single claim by ID | 30/min |
| PUT | `/pkb/claims/<id>` | Update claim fields | 15/min |
| DELETE | `/pkb/claims/<id>` | Soft-delete (retract) claim | 15/min |
| POST | `/pkb/claims/bulk` | Bulk add (max 100) `{claims: [...], auto_extract}` | 10/min |
| POST | `/pkb/claims/<id>/pin` | Toggle global pin `{pin: true/false}` | 30/min |
| GET | `/pkb/pinned` | Get all globally pinned claims | 30/min |
| POST | `/pkb/conversation/<conv_id>/pin` | Pin claim to conversation `{claim_id, pin}` | 30/min |
| GET | `/pkb/conversation/<conv_id>/pinned` | Get conversation-pinned claims | 30/min |
| DELETE | `/pkb/conversation/<conv_id>/pinned` | Clear conversation pins | 30/min |
| POST | `/pkb/search` | Search `{query, strategy, k, filters}` | 20/min |
| GET | `/pkb/entities` | List entities for user | 30/min |
| POST | `/pkb/entities` | Create entity `{name, entity_type}` | 15/min |
| GET | `/pkb/entities/<id>/claims` | Claims linked to an entity | 30/min |
| GET | `/pkb/claims/<id>/entities` | Entities linked to a claim | 30/min |
| POST | `/pkb/claims/<id>/entities` | Link entity to claim `{entity_id, role}` | 15/min |
| DELETE | `/pkb/claims/<id>/entities/<eid>` | Unlink entity from claim | 15/min |
| GET | `/pkb/tags` | List tags for user | 30/min |
| POST | `/pkb/tags` | Create tag `{name, parent_tag_id?}` | 15/min |
| GET | `/pkb/tags/<id>/claims` | Claims linked to a tag | 30/min |
| GET | `/pkb/claims/<id>/tags` | Tags linked to a claim | 30/min |
| POST | `/pkb/claims/<id>/tags` | Link tag to claim `{tag_id}` | 15/min |
| DELETE | `/pkb/claims/<id>/tags/<tid>` | Unlink tag from claim | 15/min |
| GET | `/pkb/conflicts` | List open conflicts | 30/min |
| POST | `/pkb/conflicts/<id>/resolve` | Resolve `{winning_claim_id?, resolution_notes}` | 15/min |
| POST | `/pkb/propose_updates` | Extract from chat `{conversation_summary, user_message, assistant_message}` | 10/min |
| POST | `/pkb/execute_updates` | Execute `{plan_id, approved_indices}` or `{plan_id, approved: [{index, ...}]}` | 10/min |
| POST | `/pkb/ingest_text` | AI text parsing `{text, default_claim_type, default_domain, use_llm}` | 5/min |
| POST | `/pkb/execute_ingest` | Execute `{plan_id, approved: [{index, statement?, ...}]}` | 10/min |
| POST | `/pkb/relevant_context` | Get context `{query, conversation_summary, k}` | 60/min |
| POST | `/pkb/analyze_statement` | Analyze statement, extract type/domain/tags/questions `{statement}` | 20/min |

**Plan Storage Note:** `/pkb/propose_updates` and `/pkb/ingest_text` store plans in server memory (`_memory_update_plans`, `_text_ingestion_plans`). Plans are lost on server restart. The frontend should execute plans promptly after receiving them.

### Endpoint Examples

```javascript
// Add claim
fetch('/pkb/claims', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    statement: "I prefer tea over coffee",
    claim_type: "preference",
    context_domain: "personal",
    auto_extract: true,
    tags: ["beverages"]
  })
});
// Response: {success: true, claim: {claim_id, statement, ...}, warnings: [...]}

// Search
fetch('/pkb/search', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({query: "beverage preferences", strategy: "hybrid", k: 10})
});
// Response: {results: [{claim: {...}, score: 0.85, source: "hybrid"}], count: 3}

// Toggle global pin
fetch('/pkb/claims/abc-123/pin', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({pin: true})
});
// Response: {success: true, claim: {...}}

// Pin to conversation
fetch('/pkb/conversation/conv-456/pin', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({claim_id: "abc-123", pin: true})
});
// Response: {success: true}

// Analyze statement (auto-fill)
fetch('/pkb/analyze_statement', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({statement: "I prefer morning workouts over evening ones"})
});
// Response: {success: true, analysis: {claim_type: "preference", context_domain: "health",
//   tags: ["morning_exercise", "fitness", "routine"],
//   entities: [{type: "topic", name: "morning workouts", role: "object"}],
//   possible_questions: ["Do I prefer morning or evening workouts?", ...],
//   confidence: 0.9, friendly_id: "prefer_morning_workouts_a3f2"}}
```

### Frontend (pkb-manager.js)

```javascript
// Global PKBManager API
PKBManager.listClaims({status:'active'});  PKBManager.addClaim({...});  PKBManager.searchClaims("query");
PKBManager.checkMemoryUpdates(summary, userMsg, assistantMsg);  PKBManager.openPKBModal();
PKBManager.openAddClaimModal();  PKBManager.openAddClaimModalWithText("pre-filled text");
// Bulk: addBulkRow(), saveBulkClaims(), analyzeTextForIngestion(), saveSelectedProposals()
// Pinning: pinClaim(id, true), addToNextMessage(id), getPendingAttachments()
```

**Modal Tabs:** Claims | Entities | Tags | Conflicts | Bulk Add | Import Text

**Triggered by:** `#settings-pkb-modal-open-button` ("Personal Memory" button in sidebar)

### Conversation.py Integration

PKB context fetched async in `reply()` via `_get_pkb_context()`, injected into system prompt:

```python
# In Conversation.reply() (~line 4669)
pkb_future = get_async_future(
    self._get_pkb_context,
    user_email, query["messageText"], self.running_summary,
    k=10,
    attached_claim_ids=attached_claim_ids,        # From "Use Now" button
    conversation_id=self.conversation_id,
    conversation_pinned_claim_ids=conv_pinned_ids, # From server session state
    referenced_claim_ids=referenced_claim_ids       # From @memory:id parsing
)
# ... other processing runs in parallel ...
pkb_context = pkb_future.result(timeout=5.0)
if pkb_context:
    user_info += f"\n\nRelevant user facts:\n{pkb_context}"
```

**Context Priority:** Referenced > Attached > Global Pinned > Conversation Pinned > Auto Search

**Key:** `conversation_pinned_claim_ids` are injected server-side by `endpoints/conversations.py` from `AppState.pinned_claims`, NOT sent by the frontend.

### Send Message Integration

The `/send_message/<conversation_id>` endpoint (in `endpoints/conversations.py`) is where PKB data merges into the chat flow:

```python
# endpoints/conversations.py
def send_message(conversation_id):
    query = request.get_json()
    # query already has: attached_claim_ids, referenced_claim_ids (from frontend)
    
    # Server injects conversation-pinned claim IDs from session state
    conv_pinned_ids = list(get_state().pinned_claims.get(conversation_id, set()))
    if conv_pinned_ids:
        query["conversation_pinned_claim_ids"] = conv_pinned_ids
    
    # Pass to conversation.reply()
    conversation.reply(query, ...)
```

### Post-Message Memory Proposals

After a message response completes, the frontend automatically checks for memory updates (with a 3-second delay):

```javascript
// common-chat.js (~line 2879)
setTimeout(function() {
    PKBManager.checkMemoryUpdates(conversationSummary, messageText, '');
}, 3000);
```

This calls `POST /pkb/propose_updates`, and if proposals are found, shows the Memory Proposal Modal for user review.

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
- **External:** `code_common/call_llm.py` - Shared LLM calling utilities (`call_llm()`, `get_embedding()`, `get_query_embedding()`)

### Feature → API Key Requirements

| Feature | Requires OPENROUTER_API_KEY | Fallback |
|---------|---------------------------|----------|
| Auto-extract (tags/entities) | Yes | Manual entry only |
| Embedding search | Yes | FTS-only search |
| Hybrid search | Partially (for embedding part) | FTS-only results |
| Text ingestion (LLM parsing) | Yes | Rule-based line splitting |
| Memory proposals (distillation) | Yes | No proposals shown |
| Search rewrite strategy | Yes | Strategy skipped |
| MapReduce strategy | Yes | Strategy skipped |
| FTS/BM25 search | No | Always available |
| CRUD operations | No | Always available |
| Global/conversation pinning | No | Always available |

### Graceful Degradation

The PKB system is entirely optional. If unavailable:
- **Server:** Endpoints return 503; chat works without memory context
- **Conversation.py:** Returns empty string; conversation proceeds normally
- **Frontend:** Checks `typeof PKBManager !== 'undefined'` before calling; no errors if missing

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No search results | Check `api.claims.list(limit=10)` exists; try `strategy="fts"`; broaden filters |
| Stale embeddings | `EmbeddingStore(db,keys,config).compute_and_store(claim)` |
| LLM fails | Verify API key; use `auto_extract=False` as fallback |
| Database locked | `db.close(); db = get_database(config)` or use context manager |
| Contested warnings | Expected; use `include_contested=False` or filter `r.is_contested` |
| UI works but Conversation.py doesn't | **Check database paths match** - both must use `storage/users/pkb.sqlite` |
| Embedding search fails with "ambiguous truth value" | Numpy array issue - fixed in v0.4.1. Ensure `if query_emb is not None:` not `if query_emb:` |
| Search logs not appearing | Use `time_logger.info()` instead of `logger.debug()` for guaranteed visibility |
| PKB endpoints return 503 | `truth_management_system` package not installed or import error |
| Memory proposals never appear | Check `OPENROUTER_API_KEY` is set (LLM required for distillation) |
| Conversation pins lost | Expected: pins are in-memory only, lost on server restart |
| Memory update plans expired | Plans stored in server memory; execute promptly before restart |
| @memory refs not working | Verify `parseMemoryReferences` is loaded (in `parseMessageForCheckBoxes.js`) |
| "Use Now" attachments lost | Attachments cleared after send; if page refreshes before send, they're lost |
| PKB 401 errors | Session expired; user needs to log in again |

For detailed troubleshooting with diagnosis steps, see [Implementation Deep Dive - Troubleshooting Guide](./implementation_deep_dive.md#troubleshooting-guide).

---

## Deliberate Memory Attachment

Force specific memories into LLM context. Multiple mechanisms with different scopes and persistence.

| Mechanism | Scope | Persistence | Priority | Storage |
|-----------|-------|-------------|----------|---------|
| **@memory Reference** | Single message | One-shot | Highest | Parsed from message text |
| **"Use in Next Message"** | Single message | One-shot | High | JS variable (browser) |
| **Global Pinning** | All conversations | Persistent | Medium-high | `meta_json.pinned` (database) |
| **Conversation Pinning** | Current session | Ephemeral | Medium | `AppState.pinned_claims` (server memory) |
| **Auto Search** | Per message | Computed | Normal | Not stored, computed per query |

### How Each Mechanism Flows

**@memory References:**
```
User types: "Based on @memory:abc-123 and @ssdva what should I do?"
    → parseMemoryReferences() in parseMessageForCheckBoxes.js
    → Extracts: referenced_claim_ids = ["abc-123"], referenced_friendly_ids = ["ssdva"]
    → Sent in POST /send_message body
    → Conversation.py: api.get_claims_by_ids(["abc-123"]) for legacy refs
    → Conversation.py: api.resolve_reference("ssdva") for friendly_id refs
    → resolve_reference tries: claim friendly_id → context friendly_id → context name
    → Included as [REFERENCED] or [REFERENCED @ssdva] in LLM context
```
Legacy regex: `/@(?:memory|mem):([a-zA-Z0-9-]+)/g`
Friendly ID regex: `/@([a-zA-Z][a-zA-Z0-9_-]{2,})/g` (with preceding whitespace/start check, excludes `@memory`/`@mem`)

**"Use in Next Message":**
```
User clicks "Use Now" button on claim card
    → PKBManager.addToNextMessage(claimId) → pendingMemoryAttachments[]
    → Shows chip indicator near chat input
When user sends message:
    → sendMessageCallback() gets PKBManager.getPendingAttachments()
    → Clears pending: PKBManager.clearPendingAttachments()
    → Sent as attached_claim_ids in POST /send_message body
    → Conversation.py: api.get_claims_by_ids(attached_claim_ids)
    → Included as [ATTACHED] in LLM context
```

**Global Pinning:**
```
User clicks pin button on claim card
    → POST /pkb/claims/{id}/pin {pin: true}
    → Updates claim meta_json: {"pinned": true}
    → Persists in database
For every message:
    → Conversation.py: api.get_pinned_claims()
    → Included as [GLOBAL PINNED] in LLM context
```

**Conversation Pinning:**
```
User pins claim to conversation
    → POST /pkb/conversation/{conv_id}/pin {claim_id, pin: true}
    → Stored in AppState.pinned_claims[conv_id] (server memory)
When user sends message in that conversation:
    → endpoints/conversations.py reads state.pinned_claims[conv_id]
    → Injects conversation_pinned_claim_ids into query (server-side)
    → Conversation.py: api.get_claims_by_ids(conv_pinned_ids)
    → Included as [CONV PINNED] in LLM context
```

**IMPORTANT:** Conversation pins are NOT sent by the frontend. They are injected server-side. This means they work automatically for any message in that conversation without the frontend needing to track them.

### Python API

```python
api.pin_claim(claim_id, pin=True)     # Global pin/unpin (persists in meta_json)
api.get_pinned_claims(limit=50)       # Get all globally pinned
api.get_claims_by_ids(claim_ids)      # Batch fetch by IDs

# Context retrieval with all sources
context = _get_pkb_context(
    user_email="user@example.com",
    query="current question",
    conversation_summary="recent summary",
    k=10,
    attached_claim_ids=["id1"],          # From "Use Now"
    conversation_pinned_claim_ids=["id2"], # From server session
    referenced_claim_ids=["id3"]          # From @memory:id
)
```

### REST Endpoints

| Method | Endpoint | Body/Params | Notes |
|--------|----------|-------------|-------|
| POST | `/pkb/claims/<id>/pin` | `{pin: true/false}` | Persists in database |
| GET | `/pkb/pinned` | `?limit=50` | All globally pinned claims |
| POST | `/pkb/conversation/<conv_id>/pin` | `{claim_id, pin}` | Ephemeral (server memory) |
| GET | `/pkb/conversation/<conv_id>/pinned` | - | Returns pinned for conversation |
| DELETE | `/pkb/conversation/<conv_id>/pinned` | - | Clears all pins for conversation |

### Frontend (PKBManager)

```javascript
// Global Pinning
PKBManager.pinClaim(claimId, true);          // POST /pkb/claims/{id}/pin
PKBManager.getPinnedClaims();                // GET /pkb/pinned
PKBManager.isClaimPinned(claim);             // Check meta_json.pinned
PKBManager.togglePinAndRefresh(claimId, currentlyPinned);  // Toggle + refresh UI

// Conversation Pinning
PKBManager.pinToConversation(convId, claimId, true);  // POST /pkb/conversation/{id}/pin
PKBManager.getConversationPinned(convId);              // GET /pkb/conversation/{id}/pinned
PKBManager.clearConversationPinned(convId);            // DELETE /pkb/conversation/{id}/pinned
PKBManager.pinToCurrentConversation(claimId);          // Uses ConversationManager.activeConversationId

// "Use in Next Message"
PKBManager.addToNextMessage(claimId);        // Add to pending queue
PKBManager.getPendingAttachments();          // Get queued claim IDs
PKBManager.getPendingCount();                // Count queued
PKBManager.removeFromPending(claimId);       // Remove specific
PKBManager.clearPendingAttachments();        // Clear all (called after send)
PKBManager.updatePendingAttachmentsIndicator();  // Update UI chips

// Modal (Add/Edit Memory)
PKBManager.openAddClaimModal();              // Open blank Add Memory modal
PKBManager.openAddClaimModalWithText(text);  // Open Add Memory modal with statement pre-filled (used by message triple-dots "Save to Memory")

// Tag Linking
PKBManager.createTag({name: "my_tag"});      // POST /pkb/tags
PKBManager.getClaimTags(claimId);            // GET /pkb/claims/{id}/tags
PKBManager.linkTagToClaim(claimId, tagId);   // POST /pkb/claims/{id}/tags
PKBManager.unlinkTagFromClaim(claimId, tagId); // DELETE /pkb/claims/{id}/tags/{tid}
```

### @memory and @friendly_id References

**Legacy syntax** — Use `@memory:claim_id` or `@mem:claim_id` in messages:
```
Consider @memory:abc-123-def what approach should I take?
Based on @mem:xyz-789 this should work.
```

**v0.5+ syntax** — Use `@friendly_id` directly (works for both claims and contexts):
```
According to @prefer_morning_workouts_a3f2 I should schedule morning meetings.
Let me check @work_context for relevant memories.
Check @ssdva for project details.
```

**Resolution order:** `@friendly_id` is first resolved as a claim friendly_id, then as a context friendly_id (which recursively resolves to all claims in that context), then as a context name (case-insensitive, spaces→underscores).

**Parsing:** `parseMemoryReferences(text)` in `parseMessageForCheckBoxes.js`
- Returns `{cleanText: "...", claimIds: ["abc-123-def"], friendlyIds: ["prefer_morning_workouts_a3f2", "ssdva"]}`
- Supports UUID-based `@memory:uuid`, long `@friendly_id_with_underscores`, and short `@contextid` patterns
- Minimum 3 characters after `@` (e.g., `@abc` matches, `@ab` does not)
- Must be preceded by start of string or whitespace (not part of emails like `user@domain`)
- Skips `@memory` and `@mem` as standalone words (reserved for legacy syntax)
- Removes duplicates
- Note: Original text (with refs) is still sent to server

### v0.5 Endpoints — Contexts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/contexts` | List all contexts with claim counts |
| POST | `/pkb/contexts` | Create a context (`{name, friendly_id?, description?, parent_context_id?, claim_ids?}`) |
| GET | `/pkb/contexts/<id>` | Get context with children and claims |
| PUT | `/pkb/contexts/<id>` | Update context fields |
| DELETE | `/pkb/contexts/<id>` | Delete context (claims remain, links removed) |
| POST | `/pkb/contexts/<id>/claims` | Link claim to context (`{claim_id}`) |
| DELETE | `/pkb/contexts/<id>/claims/<cid>` | Remove claim from context |
| GET | `/pkb/contexts/<id>/resolve` | Recursively get all claims under context and sub-contexts |

### v0.5 Endpoints — Entity Linking

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/pkb/entities` | Create entity (`{name, entity_type?, meta_json?}`) |
| GET | `/pkb/claims/<id>/entities` | Get entities linked to a claim (with roles) |
| POST | `/pkb/claims/<id>/entities` | Link entity to claim (`{entity_id, role?}`) |
| DELETE | `/pkb/claims/<id>/entities/<eid>` | Unlink entity from claim (`?role=` optional) |

### v0.5 Endpoints — Autocomplete & References

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/autocomplete?q=prefix` | Prefix search for memories and contexts by friendly_id |
| GET | `/pkb/resolve/<reference_id>` | Resolve @reference to claims (tries memory first, then context) |
| GET | `/pkb/claims/by-friendly-id/<fid>` | Get claim by friendly_id |

### Context Format to LLM

```
[REFERENCED] [preference] I prefer morning meetings
[ATTACHED] [fact] My team uses Python 3.11
[GLOBAL PINNED] [fact] My timezone is IST
[CONV PINNED] [decision] Using microservices for project X
[AUTO] [preference] I like detailed explanations
[AUTO] [fact] I work in tech
```

### Deduplication

If the same claim appears in multiple sources (e.g., a claim is both globally pinned AND returned by search), it is included only once, keeping the highest-priority source label.

### v0.5.1 Endpoints — Expandable Views

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/entities/<entity_id>/claims` | Get all claims linked to an entity (for expandable entity cards) |
| GET | `/pkb/tags/<tag_id>/claims` | Get all claims linked to a tag (for expandable tag cards) |

### v0.5.1 Endpoints — Claim-Context Linking

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/claims/<claim_id>/contexts` | Get all contexts a claim belongs to (for edit modal pre-selection) |
| PUT | `/pkb/claims/<claim_id>/contexts` | Set (replace) contexts for a claim. Body: `{context_ids: [...]}` |

### v0.5.1 Endpoints — Dynamic Types & Domains Catalog

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/types` | List all valid claim types (system + user-defined) |
| POST | `/pkb/types` | Add custom claim type. Body: `{type_name, display_name?, description?}` |
| GET | `/pkb/domains` | List all valid context domains (system + user-defined) |
| POST | `/pkb/domains` | Add custom domain. Body: `{domain_name, display_name?, description?}` |

### v0.5.1 Python API — Catalog CRUD

```python
# TypeCatalogCRUD and DomainCatalogCRUD are available on StructuredAPI:
api = StructuredAPI(db, keys, config, user_email="user@example.com")

# List all types (system defaults + user-created)
types = api.type_catalog.list()
# Returns: [{"type_name": "fact", "display_name": "Fact", "is_system": True, ...}, ...]

# Add a custom type
api.type_catalog.add("research_note", display_name="Research Note")

# List all domains
domains = api.domain_catalog.list()

# Add a custom domain
api.domain_catalog.add("hobbies", display_name="Hobbies")
```

### v0.6 — Numeric IDs, QnA Questions, Unified Search

#### Claim Number (`claim_number`)
Per-user auto-incremented numeric ID. Reference in chat as `@claim_42`.

```python
# Get claim by number
claim = api.claims.get_by_claim_number(42)

# Resolve any identifier (number, UUID, friendly_id)
claim = api.resolve_claim_identifier("42")       # bare number
claim = api.resolve_claim_identifier("claim_42")  # claim_N format
claim = api.resolve_claim_identifier("@claim_42") # with @ prefix
claim = api.resolve_claim_identifier("abc-uuid")  # UUID
claim = api.resolve_claim_identifier("my_fid_a3f2") # friendly_id
```

#### Possible Questions (`possible_questions`)
JSON array of self-sufficient questions a claim answers. Auto-generated by LLM or user-provided.

**Self-sufficiency requirement:** Each question must include the specific subjects, names, topics, or entities from the claim so that the question is fully understandable on its own without reading the claim. This is critical for FTS and embedding search quality — vague questions like "Am I allergic to anything?" would match too many claims, while specific questions like "Do I have a peanut allergy?" enable precise retrieval.

```python
# Add claim with explicit self-sufficient questions
api.add_claim(
    "I am allergic to peanuts", "fact", "health",
    possible_questions='["Do I have a peanut allergy?", "Can I eat peanuts safely?"]'
)
# NOT: ["Am I allergic to anything?"] — too vague, not self-sufficient

# Auto-generate questions (when auto_extract=True and LLM available)
api.add_claim("I prefer morning workouts", "preference", "health", auto_extract=True)
# -> possible_questions auto-generated: ["Do I prefer morning or evening workouts?", ...]

# Edit also auto-generates if missing
api.edit_claim(claim_id, statement="Updated text")
# -> if claim had no possible_questions, LLM generates them
```

#### Unified `GET /pkb/claims` Endpoint

Now supports both list and search modes in a single endpoint:

```
# List mode (no query)
GET /pkb/claims?claim_type=fact&context_domain=health&status=active&limit=20

# Search mode (with query) — filters + text search combined
GET /pkb/claims?query=morning+workout&claim_type=preference&limit=30

# Search with strategy
GET /pkb/claims?query=health&strategy=fts&limit=10
```

The separate `POST /pkb/search` still works but is deprecated in the UI.

#### Context Search Panel (Frontend)

Expanding a context card in the Contexts tab shows a two-part panel:
1. **Linked Memories** — claims currently in the context, each with an unlink (x) button
2. **Add Memories** — search bar + Type/Domain filter dropdowns + results with checkboxes

The search uses the unified `listClaims()` function:
- ID lookups (`#42`, `@claim_42`, `@friendly_id`) → try `GET /pkb/claims/by-friendly-id/<id>` first
- Text queries → `GET /pkb/claims?query=...&claim_type=...&context_domain=...`
- Empty query + filters → `GET /pkb/claims?claim_type=...&status=active`

Checking a checkbox calls `POST /pkb/contexts/<id>/claims` to link; unchecking calls `DELETE /pkb/contexts/<id>/claims/<claim_id>` to unlink.

#### LLM Question Generation

```python
# Direct LLM call — generates self-sufficient questions
questions = api.llm.generate_possible_questions("I am allergic to peanuts", "fact")
# -> ["Do I have a peanut allergy?", "Can I eat peanuts safely?", "Should I avoid peanut-containing foods?"]
```

#### Context Name Fallback

`resolve_reference()` now tries matching context names (case-insensitive) when friendly_id lookup fails:
```python
# Context named "My Health" with friendly_id "health_goals_a3b2"
api.resolve_reference("my_health")  # matches by name if friendly_id doesn't match
```

---

## Version History

| Version | Features |
|---------|----------|
| **v0.6** | Numeric `claim_number` with `@claim_N` syntax; `possible_questions` QnA field (schema v5-v6); unified `GET /pkb/claims` with `query` param; `resolve_claim_identifier()` universal resolver; context name fallback; improved `generate_friendly_id()`; auto-generate `friendly_id` and `possible_questions` on edit; search filter bug fixes |
| **v0.5.1** | Expandable entity/tag/context views with claim action controls; context multi-select in create/edit modal; dynamic types/domains catalog (schema v4, `claim_types_catalog`, `context_domains_catalog` tables); new endpoints for entity claims, tag claims, claim contexts, types, domains; `TypeCatalogCRUD`, `DomainCatalogCRUD`; multi-select type/domain dropdowns with inline "Add New" |
| **v0.5.0** | Friendly IDs, schema v3, contexts/groups, entity linking UI, @friendly_id references, autocomplete, multi-type/domain columns, enhanced filtering. Bug fixes: `no such column: friendly_id` migration fix, `IngestProposal.match` attribute fix, `auto_extract=False` for text ingestion execution. |
| **v0.4.1** | Bug fixes: Fixed database path mismatch between server.py and Conversation.py; Fixed numpy array truthiness check in embedding search; Added time_logger for guaranteed log visibility in search modules |
| **v0.4.0** | Deliberate Memory Attachment: global/conversation pinning, "Use Now", @memory refs, priority merging |
| **v0.3.0** | Bulk operations: `add_claims_bulk()`, `TextIngestionDistiller`, text ingestion endpoints, enhanced approval modal |
| **v0.2.0** | Multi-user (`user_email` scoping), schema migration v1→v2, Flask REST API, `pkb-manager.js`, Conversation.py integration |
| **v0.1.0** | Initial: SQLite/WAL, FTS5, embedding search, hybrid RRF, LLM extraction, text orchestration, conversation distillation |
