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

### Multi-User Quick Start

```python
# For multi-user applications (e.g., web app with user sessions)
from truth_management_system import (
    PKBConfig, get_database, StructuredAPI
)

# Shared database for all users
config = PKBConfig(db_path="./shared_knowledge.sqlite")
db = get_database(config)
keys = {"OPENROUTER_API_KEY": "sk-or-v1-..."}

# Create user-scoped API instance
user_api = StructuredAPI(db, keys, config, user_email="user@example.com")

# All operations are now scoped to this user
result = user_api.add_claim(
    statement="I prefer Python over JavaScript",
    claim_type="preference",
    context_domain="work"
)

# Or use factory method from shared instance
shared_api = StructuredAPI(db, keys, config)
user_api = shared_api.for_user("user@example.com")
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

The PKB supports multi-user deployments where a shared database stores data for multiple users, with each user's data isolated by their email address.

```python
# Option 1: Initialize with user_email
user_api = StructuredAPI(db, keys, config, user_email="alice@example.com")

# Option 2: Use for_user() factory method
shared_api = StructuredAPI(db, keys, config)
alice_api = shared_api.for_user("alice@example.com")
bob_api = shared_api.for_user("bob@example.com")

# All CRUD operations and searches are automatically scoped
alice_api.add_claim(statement="I like tea", ...)  # Scoped to Alice
bob_api.search("tea preferences")  # Only searches Bob's claims
```

**Key Points:**
- `user_email` is stored on all records (claims, notes, entities, tags, conflict sets)
- Unique constraints are per-user (e.g., entity names unique within a user's data)
- Search filters automatically apply user scoping
- Schema migration handles existing single-user databases

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

| Strategy | Description | Best For |
|----------|-------------|----------|
| `hybrid` | FTS + Embedding + RRF merge | General queries (default) |
| `fts` | BM25 full-text search | Exact keyword matches |
| `embedding` | Semantic similarity | Conceptual queries |
| `rerank` | Hybrid + LLM reranking | High-precision needs |

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

### 1. Personal Assistant Memory

Store user preferences and facts for a chatbot:

```python
# During conversation
distiller = ConversationDistiller(api, keys)

# After each turn
plan = distiller.extract_and_propose(summary, user_msg, assistant_msg)

# Confirm with user
if plan.proposed_actions:
    # Show: "I noticed: [facts]. Should I remember these?"
    # On confirmation:
    distiller.execute_plan(plan, "yes")
```

### 2. Health Tracking

```python
# Add health observations
api.add_claim(
    statement="Felt tired after skipping breakfast",
    claim_type="observation",
    context_domain="health",
    tags=["energy", "nutrition"]
)

# Search patterns
results = api.search(
    "what affects my energy levels?",
    filters={"context_domains": ["health"]}
)
```

### 3. Decision Log

```python
# Record decisions
api.add_claim(
    statement="Decided to invest in index funds only",
    claim_type="decision",
    context_domain="finance",
    confidence=0.9
)

# Later, review decisions
results = api.search(
    "what investment decisions have I made?",
    filters={"claim_types": ["decision"], "context_domains": ["finance"]}
)
```

### 4. Task/Reminder Management

```python
# Add task
api.add_claim(
    statement="Schedule dentist appointment",
    claim_type="task",
    context_domain="health"
)

# Add reminder with validity
from truth_management_system.utils import now_iso
api.add_claim(
    statement="Call mom for her birthday",
    claim_type="reminder",
    context_domain="relationships",
    valid_from="2024-03-15T00:00:00Z",
    valid_to="2024-03-15T23:59:59Z"
)
```

### 5. Conflict Detection

```python
# System detects conflicting claims during add
result = api.add_claim(
    statement="I don't like coffee",
    claim_type="preference",
    context_domain="personal",
    auto_extract=True
)

if result.warnings:
    for warning in result.warnings:
        if "contradict" in warning.lower():
            print(f"⚠️ {warning}")
            # Optionally create conflict set
```

---

## Error Handling

```python
result = api.add_claim(...)

if not result.success:
    # Handle errors
    for error in result.errors:
        print(f"Error: {error}")
else:
    # Handle warnings (non-fatal)
    for warning in result.warnings:
        print(f"Warning: {warning}")
    
    # Use result
    claim = result.data
```

---

## Performance Tips

1. **Batch Operations**: Use `llm_helpers.batch_extract_all()` for multiple statements
2. **Disable Auto-Extract**: Set `auto_extract=False` when LLM extraction not needed
3. **Limit Search Results**: Use appropriate `k` values (default 20 is reasonable)
4. **Filter Early**: Use search filters to narrow results before RRF merge
5. **Cache Embeddings**: Embeddings are cached automatically; avoid deleting `claim_embeddings` table

---

## Logging

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or for specific module
logging.getLogger("truth_management_system").setLevel(logging.DEBUG)
```

---

## Search Strategy Comparison

Choose the right strategy for your use case:

| Strategy | Speed | Quality | Cost | Best For |
|----------|-------|---------|------|----------|
| `fts` | ⚡ Fast | Good | Free | Exact keyword matches, quick lookups |
| `embedding` | Medium | Better | API calls | Conceptual/semantic queries |
| `hybrid` | Medium | Best | API calls | General use (recommended default) |
| `rerank` | Slow | Excellent | More API calls | High-precision requirements |

### When to Use Each

```python
# Fast keyword search (no LLM needed)
result = api.search("coffee preference", strategy="fts")

# Semantic search (finds related concepts)
result = api.search("what beverages do I enjoy?", strategy="embedding")

# Best quality for general queries (default)
result = api.search("morning routine habits", strategy="hybrid")

# Maximum precision for important queries
result = api.search("critical health decisions", strategy="rerank")
```

### Hybrid Strategy Details

The hybrid strategy:
1. Runs FTS and Embedding searches **in parallel**
2. Merges results using **Reciprocal Rank Fusion (RRF)**
3. Optionally applies **LLM reranking** for final refinement

```python
# Control which strategies are combined
result = api.search_strategy.search(
    query="workout preferences",
    strategy_names=["fts", "embedding"],  # Choose combination
    k=20,
    llm_rerank=True,  # Enable final LLM reranking
    llm_rerank_top_n=50  # Rerank top 50 candidates
)
```

---

## Meta JSON Usage

The `meta_json` field stores extensible metadata. Standard keys:

```python
import json

# When adding a claim
meta = {
    "keywords": ["morning", "workout", "fitness"],  # For search
    "source": "chat_distillation",  # "manual"|"chat_distillation"|"import"
    "visibility": "default",  # "default"|"restricted"|"shareable"
    "llm": {
        "model": "gpt-4o-mini",
        "prompt_version": "v1",
        "confidence_notes": "User explicitly stated"
    }
}

result = api.add_claim(
    statement="I prefer morning workouts",
    claim_type="preference",
    context_domain="health",
    meta_json=json.dumps(meta)
)

# Reading metadata
from truth_management_system.utils import parse_meta_json

claim = api.get_claim(claim_id).data
metadata = parse_meta_json(claim.meta_json)
print(metadata.get("source"))  # "chat_distillation"
```

---

## Chatbot Integration Pattern

Complete example for integrating PKB with a chatbot:

```python
from truth_management_system import (
    PKBConfig, get_database, StructuredAPI,
    ConversationDistiller, TextOrchestrator
)

class ChatbotMemory:
    """Chatbot memory manager using PKB."""
    
    def __init__(self, db_path: str, api_key: str):
        config = PKBConfig(db_path=db_path)
        db = get_database(config)
        keys = {"OPENROUTER_API_KEY": api_key}
        
        self.api = StructuredAPI(db, keys, config)
        self.distiller = ConversationDistiller(self.api, keys, config)
        self.orchestrator = TextOrchestrator(self.api, keys, config)
    
    def process_turn(self, summary: str, user_msg: str, assistant_msg: str):
        """Extract and propose memory updates from conversation."""
        plan = self.distiller.extract_and_propose(summary, user_msg, assistant_msg)
        
        if plan.proposed_actions:
            return {
                "has_memories": True,
                "prompt": plan.user_prompt,
                "plan": plan
            }
        return {"has_memories": False}
    
    def confirm_memories(self, plan, user_response: str):
        """User confirmed memory updates."""
        result = self.distiller.execute_plan(plan, user_response)
        return result.execution_results
    
    def recall(self, query: str, k: int = 5):
        """Retrieve relevant memories for context."""
        result = self.api.search(query, k=k)
        if result.success:
            return [
                {
                    "statement": r.claim.statement,
                    "type": r.claim.claim_type,
                    "confidence": r.score
                }
                for r in result.data
            ]
        return []
    
    def handle_command(self, text: str):
        """Handle natural language memory commands."""
        return self.orchestrator.process(text)

# Usage in chatbot
memory = ChatbotMemory("./chatbot_memory.sqlite", "sk-or-v1-...")

# After each conversation turn
turn_result = memory.process_turn(
    summary="Discussing user's diet preferences...",
    user_msg="I've decided to go vegetarian",
    assistant_msg="That's a great choice! Let me know if you need recipe ideas."
)

if turn_result["has_memories"]:
    # Show user: "I noticed you mentioned going vegetarian. Should I remember this?"
    # On confirmation:
    memory.confirm_memories(turn_result["plan"], "yes")

# Before generating response, recall relevant context
context = memory.recall("diet food preferences")
# Include in system prompt: "User preferences: {context}"
```

---

## Flask Server Integration (REST API)

The PKB is integrated into the main Flask server (`server.py`) providing REST endpoints for web applications.

### Server Endpoints

All endpoints require authentication (`@login_required`) and are rate-limited.

#### Claims Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/claims` | List claims with optional filters |
| POST | `/pkb/claims` | Add a new claim |
| GET | `/pkb/claims/<claim_id>` | Get a specific claim |
| PUT | `/pkb/claims/<claim_id>` | Edit a claim |
| DELETE | `/pkb/claims/<claim_id>` | Soft-delete a claim |

**GET /pkb/claims**

Query Parameters:
- `status` - Filter by status (active, contested, retracted)
- `claim_type` - Filter by type (fact, preference, decision, etc.)
- `context_domain` - Filter by domain (health, work, personal, etc.)
- `limit` - Maximum results (default: 50)
- `offset` - Pagination offset

```javascript
// Example: Fetch active preferences
fetch('/pkb/claims?status=active&claim_type=preference')
    .then(r => r.json())
    .then(data => console.log(data.claims));
```

**POST /pkb/claims**

```javascript
fetch('/pkb/claims', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        statement: "I prefer morning meetings",
        claim_type: "preference",
        context_domain: "work",
        auto_extract: true
    })
});
```

#### Search Endpoint

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/pkb/search` | Search claims with query and filters |

**POST /pkb/search**

```javascript
fetch('/pkb/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        query: "what are my diet preferences?",
        strategy: "hybrid",  // fts, embedding, hybrid, rerank
        k: 10,
        filters: {
            context_domains: ["health"],
            statuses: ["active"]
        }
    })
});
```

#### Entities and Tags Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/entities` | List all entities for user |
| GET | `/pkb/tags` | List all tags for user |

#### Conflicts Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pkb/conflicts` | List open conflict sets |
| POST | `/pkb/conflicts/<id>/resolve` | Resolve a conflict |

**POST /pkb/conflicts/{conflict_id}/resolve**

```javascript
fetch('/pkb/conflicts/abc123/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        winning_claim_id: "claim-uuid-123",  // Optional
        resolution_notes: "Claim 1 is more recent"
    })
});
```

#### Memory Update Proposal Endpoints

These endpoints power the automatic memory extraction from conversations.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/pkb/propose_updates` | Extract and propose memory updates from conversation |
| POST | `/pkb/execute_updates` | Execute user-approved updates |
| POST | `/pkb/relevant_context` | Get PKB context for LLM prompt |

**POST /pkb/propose_updates**

```javascript
fetch('/pkb/propose_updates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        conversation_summary: "Discussing user's fitness routine...",
        user_message: "I've started running every morning at 6am",
        assistant_message: "That's great for building a habit!"
    })
});
// Response: { plan_id, proposals: [...], user_prompt }
```

**POST /pkb/execute_updates**

```javascript
fetch('/pkb/execute_updates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        plan_id: "plan-uuid-123",
        approved_indices: [0, 1, 3]  // User-approved proposals
    })
});
```

**POST /pkb/relevant_context**

```javascript
// Get formatted PKB context for LLM system prompt
fetch('/pkb/relevant_context', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        query: "What should I eat for breakfast?",
        conversation_summary: "User asking about meal planning",
        k: 10
    })
});
// Response: { context: "- [preference] I prefer vegetarian food\n- ..." }
```

### Frontend Integration (pkb-manager.js)

The `interface/pkb-manager.js` module provides a JavaScript API for PKB operations:

```javascript
// Initialize (auto-runs on page load)
// PKBManager is available globally

// List claims with filters
PKBManager.listClaims({ status: 'active', claim_type: 'preference' })
    .then(data => console.log(data.claims));

// Add a claim
PKBManager.addClaim({
    statement: "I like green tea",
    claim_type: "preference",
    context_domain: "health"
});

// Search claims
PKBManager.searchClaims("diet preferences")
    .then(results => results.forEach(r => console.log(r.claim.statement)));

// Check for memory updates (called automatically after chat messages)
PKBManager.checkMemoryUpdates(conversationSummary, userMessage, assistantMessage);

// Open PKB management modal
PKBManager.openPKBModal();
```

### Conversation.py Integration

The `Conversation.py` class integrates PKB for LLM context enrichment:

```python
# Automatically included in reply() method
class Conversation:
    def _get_pkb_context(self, user_email: str, query: str, 
                         conversation_summary: str = "", k: int = 10) -> str:
        """
        Retrieve relevant claims from PKB for context injection.
        
        Called asynchronously during reply() to fetch relevant user facts
        without blocking the main chat flow.
        """
        ...

    def reply(self, ...):
        # PKB context is fetched in parallel with other operations
        pkb_future = get_async_future(
            self._get_pkb_context,
            user_email, user_message, conversation_summary
        )
        
        # ... other processing ...
        
        # Get PKB context (blocks here if not ready)
        pkb_context = pkb_future.result(timeout=5.0)
        
        # Inject into system prompt
        if pkb_context:
            system_prompt += f"\n\nRelevant user facts:\n{pkb_context}"
```

---

## Data Migration

### Migrating from Legacy UserDetails

The `migrate_user_details.py` script migrates existing `user_memory` and `user_preferences` data to PKB claims.

```bash
# Preview migration (dry run)
python -m truth_management_system.migrate_user_details --dry-run

# Migrate all users
python -m truth_management_system.migrate_user_details \
    --users-db ./users/users.db \
    --pkb-db ./users/pkb.sqlite

# Migrate specific user
python -m truth_management_system.migrate_user_details \
    --user "alice@example.com" \
    --verbose
```

**Migration Options:**

| Option | Description |
|--------|-------------|
| `--users-db PATH` | Path to users.db (default: ./users/users.db) |
| `--pkb-db PATH` | Path to PKB database (default: ./users/pkb.sqlite) |
| `--dry-run` | Preview without making changes |
| `--user EMAIL` | Migrate only specific user |
| `--verbose` | Enable detailed logging |

**Migration Process:**
1. Reads `user_memory` and `user_preferences` from `UserDetails` table
2. Parses text into individual facts (splits by newlines, bullets)
3. Infers `claim_type` and `context_domain` from keywords
4. Creates PKB claims with `meta_json.source = "migration"`

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

### Required

- **Python 3.9+**
- **numpy** - For embedding operations

### Optional

- **OPENROUTER_API_KEY** - Required for LLM features (auto-extract, embedding search, rewrite)

### Installation

```bash
# Core dependencies only
pip install numpy

# For development/testing
pip install pytest
```

### Without LLM Features

The PKB works without an API key, but with limited functionality:

```python
# No API key - basic functionality only
config = PKBConfig(db_path="./kb.sqlite")
db = get_database(config)
api = StructuredAPI(db, {}, config)  # Empty keys dict

# These still work:
api.add_claim(
    statement="Test claim",
    claim_type="fact",
    context_domain="personal",
    auto_extract=False  # Must disable auto-extract
)
api.search("test", strategy="fts")  # FTS works without LLM

# These require API key:
# - auto_extract=True
# - strategy="embedding"
# - strategy="rerank"
# - ConversationDistiller
```

---

## Troubleshooting

### Common Issues

**"No results from search"**
```python
# Check if claims exist
claims = api.claims.list(limit=10)
print(f"Total claims: {len(claims)}")

# Check FTS index
fts_results = api.search("test", strategy="fts")
print(f"FTS results: {len(fts_results.data)}")

# Try broader filters
result = api.search(
    "your query",
    filters={"statuses": ["active", "contested", "historical"]}
)
```

**"Embedding search returns wrong results"**
```python
# Embeddings may be stale - recompute
from truth_management_system.search import EmbeddingStore

store = EmbeddingStore(db, keys, config)
# Force recompute for specific claim
claim = api.claims.get(claim_id)
store.compute_and_store(claim)
```

**"LLM extraction fails"**
```python
# Check API key
print(keys.get("OPENROUTER_API_KEY", "NOT SET")[:20] + "...")

# Test LLM directly
from code_common.call_llm import call_llm
response = call_llm(keys, "openai/gpt-4o-mini", "Hello")
print(response)

# Disable auto_extract as fallback
api.add_claim(..., auto_extract=False)
```

**"Database locked"**
```python
# WAL mode should prevent this, but if it happens:
db.close()
db = get_database(config)

# Or use context manager
with PKBDatabase(config) as db:
    api = StructuredAPI(db, keys, config)
    # ... operations ...
# Automatically closes
```

**"Contested claim warnings"**
```python
# This is expected behavior - contested claims are returned with warnings
# To exclude them:
result = api.search("query", include_contested=False)

# Or filter in results
active_only = [r for r in result.data if not r.is_contested]
```

---

## Version History

- **v0.2.0** - Multi-user support and Flask integration
  - Multi-user support with `user_email` scoping
  - Schema migration system (v1 → v2)
  - Flask REST API endpoints (`/pkb/*`)
  - Frontend JavaScript module (`pkb-manager.js`)
  - PKB management modal in UI
  - Memory update proposal workflow
  - Conversation.py integration for LLM context
  - Migration script for legacy UserDetails data
  - `StructuredAPI.for_user()` factory method

- **v0.1.0** - Initial release
  - SQLite storage with WAL mode
  - FTS5 full-text search
  - Embedding-based semantic search
  - Hybrid search with RRF merging
  - LLM-powered extraction
  - Text orchestration
  - Conversation distillation
