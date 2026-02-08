# PKB Reference Resolution Flow: Complete Technical Guide

**Last Updated:** 2026-02-08  
**Version:** v0.7

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Database Structure](#database-structure)
3. [ID Types and Formats](#id-types-and-formats)
4. [UI Parsing](#ui-parsing-parsememoryreferencesjsr)
5. [Backend Resolution Flow](#backend-resolution-flow)
6. [Context Resolution (Recursive)](#context-resolution-recursive)
7. [LLM Context Formatting](#llm-context-formatting)
8. [Post-Distillation Re-Injection](#post-distillation-re-injection)
9. [Complete Data Flow Diagram](#complete-data-flow-diagram)
10. [Key Files Reference](#key-files-reference)

---

## Executive Summary

The Personal Knowledge Base (PKB) system allows users to reference memories and contexts in conversation using various ID formats. This document explains the complete data flow from UI parsing through backend resolution to LLM context injection.

**Key Capabilities:**
- Reference individual claims by UUID, number, or friendly ID
- Reference entire contexts (groups of claims) by friendly ID or name
- Recursive resolution: contexts can contain sub-contexts
- Priority-based deduplication when claims appear in multiple sources
- Post-distillation re-injection ensures explicitly referenced claims bypass LLM summarization

---

## Database Structure

### Core Tables

```sql
-- Claims: Atomic memory units
CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY,            -- UUID (e.g., "550e8400-e29b-...")
    user_email TEXT,                      -- Owner (multi-user scoping)
    claim_number INTEGER,                 -- Per-user auto-incremented (1, 2, 3...)
    friendly_id TEXT,                     -- User-facing ID (e.g., "prefer_morning_a3f2")
    claim_type TEXT,                      -- fact, preference, decision, etc.
    claim_types TEXT,                     -- JSON array ["preference","fact"]
    statement TEXT NOT NULL,              -- The actual memory text
    context_domain TEXT,                  -- health, personal, work, etc.
    context_domains TEXT,                 -- JSON array ["health","personal"]
    status TEXT DEFAULT 'active',         -- active, contested, retracted, etc.
    possible_questions TEXT,              -- JSON array of self-sufficient questions
    -- ... temporal, metadata columns ...
);

-- Contexts: Hierarchical grouping of claims
CREATE TABLE contexts (
    context_id TEXT PRIMARY KEY,          -- UUID
    user_email TEXT,                      -- Owner
    friendly_id TEXT,                     -- User-facing ID (e.g., "ssdva", "work_context_a3b2")
    name TEXT NOT NULL,                   -- Display name (e.g., "Work Context")
    description TEXT,                     -- Optional description
    parent_context_id TEXT,               -- For hierarchy (tree structure)
    -- ... metadata columns ...
);

-- Context-Claims Join: Many-to-many
CREATE TABLE context_claims (
    context_id TEXT,                      -- FK to contexts
    claim_id TEXT,                        -- FK to claims
    PRIMARY KEY (context_id, claim_id)
);
```

### Key Indexes

```sql
-- User-scoped lookups
CREATE INDEX idx_claims_user_email ON claims(user_email);
CREATE INDEX idx_claims_user_claim_number ON claims(user_email, claim_number);
CREATE INDEX idx_claims_friendly_id ON claims(friendly_id);
CREATE INDEX idx_contexts_friendly_id ON contexts(friendly_id);
CREATE INDEX idx_contexts_user_email ON contexts(user_email);
```

**Why these indexes?** Fast lookups for:
- All claims for a user (`user_email`)
- Claim by number: `#42` → `get_by_claim_number(42)` with user scope
- Claim/context by friendly ID: `@prefer_morning_a3f2` → `get_by_friendly_id()`

---

## ID Types and Formats

| Type | Format | Example | Referenceable As | Used For |
|------|--------|---------|------------------|----------|
| **Claim UUID** | 36-char UUID | `550e8400-e29b-41d4-a716-446655440000` | `@memory:uuid` | Internal storage, legacy references |
| **Claim Number** | Per-user integer | `42` | `@claim_42`, `#42`, `42` | Human-friendly numeric IDs |
| **Claim Friendly ID** | Auto-generated, no suffix | `prefer_morning_workouts_a3f2` | `@friendly_id` | Chat references, autocomplete |
| **Context Friendly ID** | Auto-generated, `_context` suffix | `health_goals_context` | `@friendly_id` | Chat references, autocomplete |
| **Entity Friendly ID** | Auto-generated, `_entity` suffix | `john_smith_person_entity` | `@friendly_id` | Chat references, all linked claims (v0.7) |
| **Tag Friendly ID** | Auto-generated, `_tag` suffix | `fitness_tag` | `@friendly_id` | Chat references, recursive tag claims (v0.7) |
| **Domain Friendly ID** | Computed, `_domain` suffix | `health_domain` | `@friendly_id` | Chat references, domain filter (v0.7) |
| **Context Name** | Free-form text | `"My Health Goals"` | Fallback: case-insensitive match | UI display, fallback resolution |

### Friendly ID Generation

**Algorithm** (`truth_management_system/utils.py:generate_friendly_id()`):

1. Extract meaningful words (1-3 words, skipping 80+ stopwords like "I", "the", "is")
2. Lowercase, replace spaces with underscores
3. Append 4-char random suffix (hex)
4. Max 60 characters

**Examples:**
```python
"I prefer morning workouts" → "prefer_morning_workouts_a3f2"
"My favorite color is blue" → "favorite_color_blue_6e98"
"Health Goals" → "health_goals_3b2a"
```

**Why?** Short, memorable, human-readable IDs that avoid collisions via random suffix.

---

## UI Parsing (`parseMemoryReferences.js`)

**Location:** `interface/parseMessageForCheckBoxes.js` (lines 375-458)

**Purpose:** Extract memory/context references from user message text before sending to server.

### Supported Patterns

| Pattern | Example | Captured Array | Notes |
|---------|---------|----------------|-------|
| Legacy UUID | `@memory:abc-123-def` | `claimIds[]` | Old format, still supported |
| Legacy short | `@mem:abc-123` | `claimIds[]` | Shorter variant |
| Claim friendly | `@prefer_morning_a3f2` | `friendlyIds[]` | 3+ chars, alphanumeric+underscore+hyphen |
| Context friendly | `@ssdva`, `@work_context_a3b2` | `friendlyIds[]` | Same pattern as claim friendly_id |
| Claim numeric | `@claim_42`, `#42` | `friendlyIds[]` | Captured as `"claim_42"` |

### Regex Patterns

```javascript
// 1. Legacy: @memory:uuid or @mem:uuid
var legacyRegex = /@(?:memory|mem):([a-zA-Z0-9-]+)/g;

// 2. Friendly IDs (claims and contexts): @identifier
// Must start with letter, 3+ chars total, alphanumeric+underscore+hyphen
var friendlyRegex = /@([a-zA-Z][a-zA-Z0-9_-]{2,})/g;
```

### Exclusion Rules

- **Standalone `@memory` and `@mem`**: Skipped (reserved for legacy syntax)
- **Email addresses**: Must be preceded by whitespace or start-of-string (prevents matching `user@domain.com`)
- **Minimum length**: 3 characters after `@` (e.g., `@ab` is ignored, `@abc` matches)
- **Overlap deduplication**: If `@memory:uuid` and `@uuid` both match, only one is captured

### Function Signature

```javascript
/**
 * Parse @memory references from message text.
 * 
 * @param {string} text - The message text to parse
 * @returns {{cleanText: string, claimIds: string[], friendlyIds: string[]}}
 */
function parseMemoryReferences(text) {
    // ...
    return {
        cleanText: "what should I do?",       // Text with references removed
        claimIds: ["abc-123-def"],            // Legacy @memory:uuid refs
        friendlyIds: ["ssdva", "prefer_morning_a3f2", "claim_42"]  // Modern refs
    };
}
```

### Test Cases

**13 comprehensive test cases** in `testParseMemoryReferences()` (lines 461-568):

```javascript
// Claim friendly ID
"@prefer_morning_a3f2 what time?" 
→ friendlyIds: ["prefer_morning_a3f2"]

// Context friendly ID (short form)
"@ssdva project details" 
→ friendlyIds: ["ssdva"]

// Email exclusion
"user@domain.com" 
→ friendlyIds: []  // Not matched

// Mixed legacy + modern
"@memory:uuid and @friendly_id" 
→ claimIds: ["uuid"], friendlyIds: ["friendly_id"]

// Numeric claim reference
"@claim_42 details" 
→ friendlyIds: ["claim_42"]

// Minimum length enforcement
"@ab is too short" 
→ friendlyIds: []  // Less than 3 chars

"@abc is ok" 
→ friendlyIds: ["abc"]  // 3+ chars matches
```

---

## Backend Resolution Flow

### Entry Point: `Conversation.py:_get_pkb_context()`

**Location:** `Conversation.py` (lines ~4800-6600)

**Invocation:**
```python
# Conversation.reply() (line ~4804)
pkb_context_future = get_async_future(
    self._get_pkb_context,
    user_email,
    query["messageText"],
    self.running_summary,
    k=10,
    attached_claim_ids=attached_claim_ids,          # From UI "Use Now" button
    conversation_id=self.conversation_id,
    conversation_pinned_claim_ids=conv_pinned_ids,  # From server session state
    referenced_claim_ids=referenced_claim_ids,      # From @memory:uuid parsing
    referenced_friendly_ids=referenced_friendly_ids # From @friendly_id parsing (v0.5+)
)
```

**Why async?** PKB retrieval runs in parallel with embeddings and other preprocessing to reduce latency.

### Priority System

Claims are collected from multiple sources and prioritized:

| Priority | Source | Label | Persistence | Example |
|----------|--------|-------|-------------|---------|
| **0 (Highest)** | Referenced | `[REFERENCED @fid]` or `[REFERENCED]` | One-shot | User typed `@ssdva` |
| **1** | Attached | `[ATTACHED]` | One-shot | UI "Use Now" button |
| **2** | Global Pinned | `[GLOBAL PINNED]` | Persistent (DB) | meta_json.pinned = true |
| **3** | Conversation Pinned | `[CONV PINNED]` | Ephemeral (session) | Server state |
| **4** | Auto Search | `[AUTO]` | Computed | Hybrid search results |

**Deduplication:** Claims are deduplicated by `claim_id`. If a claim appears in multiple sources, the **highest priority** source label wins.

### Resolution for `referenced_friendly_ids`

**Code:**
```python
for fid in referenced_friendly_ids:
    result = api.resolve_reference(fid)
    if result.success:
        claims.extend(result.data['claims'])
        # Label each claim with [REFERENCED @fid]
```

### Function: `resolve_reference(reference_id)`

**Location:** `truth_management_system/interface/structured_api.py` (lines 1159-1274)

**Purpose:** Universal resolver for any `@reference` in chat. Tries multiple strategies in order.

#### Resolution Strategy (Sequential)

##### **Step 1: Try as `@claim_N` numeric reference**

```python
import re
claim_num_match = re.match(r'^claim_(\d+)$', reference_id)
if claim_num_match:
    num = int(claim_num_match.group(1))
    claim = self.claims.get_by_claim_number(num)
    if claim:
        return ActionResult(
            type='claim', 
            claims=[claim], 
            source_id=claim.claim_id
        )
```

**SQL:**
```sql
SELECT * FROM claims 
WHERE claim_number = ? AND user_email = ?
```

**Example:**
- Input: `@claim_42`
- Match: `claim_(\d+)` → `num = 42`
- Lookup: `get_by_claim_number(42)` for user
- Result: Single claim with `claim_number=42`

---

##### **Step 2: Try as claim friendly_id**

```python
claim = self.claims.get_by_friendly_id(reference_id)
if claim:
    return ActionResult(
        type='claim', 
        claims=[claim], 
        source_id=claim.claim_id
    )
```

**SQL:**
```sql
SELECT * FROM claims 
WHERE friendly_id = ? AND user_email = ?
```

**Example:**
- Input: `@prefer_morning_a3f2`
- Lookup: `get_by_friendly_id("prefer_morning_a3f2")`
- Result: Single claim with matching friendly_id

---

##### **Step 3: Try as context friendly_id (RECURSIVE)**

```python
context = self.contexts.get_by_friendly_id(reference_id)
if context:
    resolved_claims = self.contexts.resolve_claims(context.context_id)
    # resolve_claims() recursively collects all claims in context + sub-contexts
    return ActionResult(
        type='context', 
        claims=resolved_claims, 
        source_id=context.context_id
    )
```

**SQL (Recursive CTE):**
```sql
WITH RECURSIVE ctx_tree AS (
    -- Start with the root context
    SELECT context_id, 0 as depth 
    FROM contexts 
    WHERE context_id = ?
    
    UNION ALL
    
    -- Recursively get child contexts
    SELECT c.context_id, ct.depth + 1 
    FROM contexts c
    JOIN ctx_tree ct ON c.parent_context_id = ct.context_id
    WHERE ct.depth < 10  -- Max depth limit
)
SELECT DISTINCT c.* 
FROM claims c
JOIN context_claims cc ON c.claim_id = cc.claim_id
JOIN ctx_tree ct ON cc.context_id = ct.context_id
WHERE c.status IN ('active', 'contested') 
  AND c.user_email = ?
ORDER BY c.updated_at DESC
```

**Explanation:**
1. **Start:** Root context (the one user referenced)
2. **Recurse:** Walk down the tree, collecting all child/grandchild contexts
3. **Join:** Get all claims linked to any context in the tree
4. **Flatten:** Deduplicate and return as a flat list

**Example:**
- Input: `@ssdva`
- Lookup: `contexts.get_by_friendly_id("ssdva")` → `context_id = "ctx-123"`
- Resolve: `contexts.resolve_claims("ctx-123")`
  - Context tree: `ssdva` → `sub_context_a` → `sub_context_b`
  - Claims: 15 claims linked across all 3 contexts
- Result: List of 15 claims, all labeled `[REFERENCED @ssdva]`

---

##### **Step 4: Try as context name (Fallback)**

```python
all_contexts = self.contexts.get_children(parent_context_id=None)
for ctx in all_contexts:
    # Case-insensitive, spaces replaced with underscores
    if ctx.name.lower().replace(' ', '_') == reference_id.lower().replace(' ', '_'):
        resolved_claims = self.contexts.resolve_claims(ctx.context_id)
        return ActionResult(
            type='context', 
            claims=resolved_claims, 
            source_id=ctx.context_id
        )
```

**Why?** User might type `@my_health_goals` but the context name is `"My Health Goals"` with friendly_id `health_goals_a3b2`.

**Normalization:**
- Lowercase both sides
- Replace spaces with underscores
- Compare: `my_health_goals` == `my_health_goals` ✓

**Example:**
- Context name: `"My Health Goals"`
- Friendly ID: `health_goals_a3b2`
- User types: `@my_health_goals`
- Match: Name normalization succeeds
- Result: All claims from `"My Health Goals"` context

---

##### **Step 5: Not found**

```python
return ActionResult(
    success=False, 
    errors=[f"No memory or context found with ID: {reference_id}"]
)
```

**Result:** Error message shown to user (or logged in server).

---

## Context Resolution (Recursive)

### Why Recursive?

Contexts form a **tree hierarchy**:
```
Project Alpha (@ssdva)
├── Backend (@backend_ssdva_sub1)
│   ├── API Design
│   └── Database Schema
└── Frontend (@frontend_ssdva_sub2)
    ├── UI Components
    └── State Management
```

When user types `@ssdva`, they want **all** claims from:
- Project Alpha itself
- Backend (and its children)
- Frontend (and its children)

### Algorithm: `contexts.resolve_claims(context_id)`

**Location:** `truth_management_system/crud/contexts.py` (lines 271-320)

**Pseudocode:**
```python
def resolve_claims(context_id, max_depth=10):
    # 1. Build context tree using recursive CTE
    context_ids = [context_id]  # Start with root
    for depth in range(max_depth):
        child_ids = get_children(context_ids[-1])
        context_ids.extend(child_ids)
    
    # 2. Collect all claims linked to any context in tree
    all_claims = []
    for ctx_id in context_ids:
        claims = get_claims_for_context(ctx_id)
        all_claims.extend(claims)
    
    # 3. Deduplicate by claim_id
    unique_claims = deduplicate(all_claims)
    
    return unique_claims
```

**Actual SQL (Recursive CTE):**
```sql
WITH RECURSIVE ctx_tree AS (
    -- Base case: root context
    SELECT context_id, 0 as depth 
    FROM contexts 
    WHERE context_id = 'ctx-uuid-123'
    
    UNION ALL
    
    -- Recursive case: children
    SELECT c.context_id, ct.depth + 1 
    FROM contexts c
    JOIN ctx_tree ct ON c.parent_context_id = ct.context_id
    WHERE ct.depth < 10  -- Prevent infinite loops
)
-- Collect all claims
SELECT DISTINCT c.* 
FROM claims c
JOIN context_claims cc ON c.claim_id = cc.claim_id
JOIN ctx_tree ct ON cc.context_id = ct.context_id
WHERE c.status IN ('active', 'contested') 
  AND c.user_email = 'user@example.com'
ORDER BY c.updated_at DESC
```

**Result:**
- Flat list of claims
- All claims from root context + all descendant contexts
- Deduplicated (a claim can be in multiple contexts)
- User-scoped (only user's claims)
- Status-filtered (active + contested only)

---

## LLM Context Formatting

### Label System

Each claim is formatted with a source label to indicate priority:

```python
# Format: "- [LABEL] [type] statement (answers: Q1; Q2)"

# Priority 0: Referenced (highest)
"- [REFERENCED @ssdva] [fact] Working on project Alpha (answers: What project am I on?)"

# Priority 1: Attached
"- [ATTACHED] [decision] Using Python 3.11"

# Priority 2: Global Pinned
"- [GLOBAL PINNED] [fact] My timezone is IST"

# Priority 3: Conversation Pinned
"- [CONV PINNED] [preference] I like detailed explanations"

# Priority 4: Auto Search
"- [AUTO] [fact] I work in tech"
```

### Label Meanings

| Label | Meaning | Why Important |
|-------|---------|---------------|
| `[REFERENCED @fid]` | User explicitly asked for this memory/context | **Must not be dropped** by distillation |
| `[REFERENCED]` | Legacy UUID reference | **Must not be dropped** by distillation |
| `[ATTACHED]` | User clicked "Use Now" in UI | High priority, user intent |
| `[GLOBAL PINNED]` | User pinned globally (persistent) | Always relevant |
| `[CONV PINNED]` | Pinned to this conversation (ephemeral) | Session-specific relevance |
| `[AUTO]` | Hybrid search result | Contextually relevant |

### Deduplication Logic

```python
seen_ids = set()
formatted_claims = []

# Priority 0: Referenced
for claim in referenced_claims:
    if claim.claim_id not in seen_ids:
        seen_ids.add(claim.claim_id)
        formatted_claims.append(
            f"- [REFERENCED @{fid}] [{claim.claim_type}] {claim.statement}"
        )

# Priority 1: Attached
for claim in attached_claims:
    if claim.claim_id not in seen_ids:  # Skip if already added as REFERENCED
        seen_ids.add(claim.claim_id)
        formatted_claims.append(
            f"- [ATTACHED] [{claim.claim_type}] {claim.statement}"
        )

# ... and so on for other priority levels
```

**Result:** Each claim appears **once** with the **highest priority** label it qualifies for.

---

## Post-Distillation Re-Injection

### Problem

**Scenario:**
1. User has 100 PKB claims (auto-search returns 50, user references 3)
2. Cheap LLM distills this into user preferences (to save tokens)
3. **Risk:** Distillation may drop or paraphrase the 3 explicitly referenced claims

**Why bad?** User explicitly asked for those 3 claims via `@reference`. They **must** reach the main LLM verbatim.

### Solution: Two-Stage Injection

**Stage 1: Distillation** (with full PKB context)
```python
# All PKB claims (referenced + auto + pinned) go into distillation prompt
distillation_prompt = f"""
User query: {query}

User memory:
{pkb_context}  # All claims, including [REFERENCED @fid] ones

User preferences:
{user_preferences}

Extract the most relevant user preferences and context for answering the query.
"""

distilled_prefs = cheap_llm(distillation_prompt)
# Result: Condensed user info, may have dropped some claims
```

**Stage 2: Re-injection** (only `[REFERENCED ...]` claims)
```python
# Extract only the [REFERENCED ...] claims from original PKB context
referenced_only = _extract_referenced_claims(pkb_context)

# Append them AFTER distillation output
ref_section = f"""

**User's explicitly referenced memories (ground truth):**
{referenced_only}
"""

# Final user info for main LLM
user_info_text = f"""
User Preferences:
{distilled_prefs}

{ref_section}
"""
```

**Why this works:**
- Auto/pinned/attached claims can be safely summarized (they're contextual hints)
- Referenced claims are preserved verbatim (user explicitly asked for them)
- Main LLM sees both: condensed context + explicit references

### Function: `_extract_referenced_claims(pkb_context)`

**Location:** `Conversation.py` (lines 249-308)

**Purpose:** Parse PKB context and extract only `[REFERENCED ...]` bullets.

**Algorithm:**
```python
def _extract_referenced_claims(pkb_context):
    """
    Parse bullet-point PKB context and extract only [REFERENCED ...] claims.
    
    Example input:
    - [REFERENCED @ssdva] [fact] Working on Alpha
    - [AUTO] [fact] I work in tech
    - [REFERENCED @prefer] [pref] Morning workouts
    - [GLOBAL PINNED] [fact] Timezone IST
    
    Output:
    - [REFERENCED @ssdva] [fact] Working on Alpha
    - [REFERENCED @prefer] [pref] Morning workouts
    """
    if not pkb_context:
        return ""
    
    # Split on "- [" boundaries (robust against multi-line claims)
    bullets = pkb_context.split('\n- [')
    
    referenced = []
    for bullet in bullets:
        if bullet.strip().startswith('REFERENCED'):
            referenced.append(bullet)
    
    # Rebuild with "- [" prefix
    if referenced:
        return '\n- [' + '\n- ['.join(referenced)
    return ""
```

**Why split on `\n- [`?**
- Claim statements can span multiple lines
- Splitting on `\n-` would break multi-line claims
- `\n- [` is the exact bullet prefix pattern

**Edge Cases:**
- Empty PKB context → returns `""`
- No referenced claims → returns `""`
- Claim statement contains `"- ["` → safe (we split on `\n- [`, not just `- [`)

---

## Complete Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ USER TYPES IN CHAT INPUT:                                           │
│ "@ssdva @prefer_morning_a3f2 what should I do?"                     │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ UI: parseMemoryReferences() (parseMessageForCheckBoxes.js:375)     │
│                                                                      │
│   ├─ legacyRegex: /@(?:memory|mem):([a-zA-Z0-9-]+)/g               │
│   │  → claimIds: []                                                 │
│   │                                                                  │
│   └─ friendlyRegex: /@([a-zA-Z][a-zA-Z0-9_-]{2,})/g                │
│      ├─ Check whitespace before @ (not email)                      │
│      ├─ Skip @memory/@mem standalone                               │
│      └─ friendlyIds: ["ssdva", "prefer_morning_a3f2"]              │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ HTTP POST /send_message/<conversation_id>                           │
│                                                                      │
│   body: {                                                            │
│     messageText: "what should I do?",                                │
│     referenced_friendly_ids: ["ssdva", "prefer_morning_a3f2"],      │
│     checkboxes: { use_pkb: true, ... }                              │
│   }                                                                  │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Server: endpoints/conversations.py                                  │
│   ├─ Inject conversation_pinned_claim_ids from session state        │
│   └─ Call conversation.reply(query)                                 │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Conversation.reply() (Conversation.py:4717)                         │
│                                                                      │
│   if use_pkb and user_email:                                         │
│       pkb_context_future = get_async_future(                         │
│           self._get_pkb_context,                                     │
│           user_email,                                                │
│           query["messageText"],                                      │
│           k=10,                                                       │
│           referenced_friendly_ids=["ssdva", "prefer_morning_a3f2"]  │
│       )                                                              │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ _get_pkb_context() (async, runs in parallel)                        │
│                                                                      │
│   for fid in referenced_friendly_ids:                               │
│       result = api.resolve_reference(fid)                           │
│       # Priority 0: REFERENCED claims                               │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                  ┌──────────────────┴──────────────────┐
                  │                                      │
                  ▼                                      ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│ resolve_reference("ssdva")      │   │ resolve_reference("prefer_...") │
│ (structured_api.py:1159)        │   │                                 │
│                                 │   │                                 │
│ Step 1: @claim_N? No            │   │ Step 1: @claim_N? No            │
│ Step 2: claim friendly_id? No   │   │ Step 2: claim friendly_id? YES  │
│ Step 3: context friendly_id? YES│   │   → claims.get_by_friendly_id() │
│   → contexts.get_by_friendly_id()│  │   → claim_id="claim-uuid-456"   │
│   → context_id="ctx-uuid-123"   │   │                                 │
│   → contexts.resolve_claims()   │   │ Return: type='claim',           │
│                                 │   │         claims=[claim456]       │
│ SQL: WITH RECURSIVE ctx_tree... │   └─────────────────────────────────┘
│ SELECT c.* FROM claims c        │                 │
│ JOIN context_claims cc ...      │                 │
│ JOIN ctx_tree ct ...            │                 │
│ WHERE user_email=? AND status..│                 │
│                                 │                 │
│ Return: type='context',         │                 │
│         claims=[c1, c2, c3]     │                 │
└─────────────────────────────────┘                 │
                  │                                  │
                  └──────────────────┬───────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Format with labels:                                                  │
│                                                                      │
│ "- [REFERENCED @ssdva] [fact] Working on project Alpha (answers...)"│
│ "- [REFERENCED @ssdva] [fact] Using Python 3.11 for Alpha"         │
│ "- [REFERENCED @ssdva] [decision] Microservices architecture"      │
│ "- [REFERENCED @prefer_morning_a3f2] [preference] I prefer morning" │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Collect from other priority levels:                                 │
│   ├─ Priority 1: Attached claims ([ATTACHED])                       │
│   ├─ Priority 2: Global pinned ([GLOBAL PINNED])                    │
│   ├─ Priority 3: Conversation pinned ([CONV PINNED])                │
│   └─ Priority 4: Auto search ([AUTO])                               │
│                                                                      │
│ Deduplicate by claim_id (keep highest priority label)               │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ PKB Context (full):                                                  │
│                                                                      │
│ - [REFERENCED @ssdva] [fact] Working on project Alpha               │
│ - [REFERENCED @ssdva] [fact] Using Python 3.11                       │
│ - [REFERENCED @prefer_morning_a3f2] [preference] I prefer morning... │
│ - [AUTO] [fact] I work in tech                                      │
│ - [GLOBAL PINNED] [fact] My timezone is IST                          │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 1: Distillation (Cheap LLM)                                   │
│                                                                      │
│   Input: full PKB context + user_memory + user_preferences          │
│                                                                      │
│   Prompt:                                                            │
│   "User query: what should I do?                                    │
│                                                                      │
│    User memory:                                                      │
│    - [REFERENCED @ssdva] [fact] Working on project Alpha            │
│    - [REFERENCED @ssdva] [fact] Using Python 3.11                    │
│    - [REFERENCED @prefer] [pref] I prefer morning...                │
│    - [AUTO] [fact] I work in tech                                   │
│    - [GLOBAL PINNED] [fact] My timezone is IST                       │
│                                                                      │
│    Extract relevant user preferences..."                            │
│                                                                      │
│   Output (distilled_prefs):                                          │
│   "User works in tech, timezone IST, morning person"                │
│   (May have dropped/paraphrased some claims to save tokens)         │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STAGE 2: Re-inject REFERENCED claims                                │
│   (Conversation.py:249 _extract_referenced_claims())                │
│                                                                      │
│   ├─ Parse PKB context on "\n- [" boundaries                        │
│   ├─ Keep only bullets starting with "REFERENCED"                   │
│   └─ referenced_only:                                                │
│       "- [REFERENCED @ssdva] [fact] Working on project Alpha        │
│        - [REFERENCED @ssdva] [fact] Using Python 3.11               │
│        - [REFERENCED @prefer] [pref] I prefer morning..."           │
│                                                                      │
│   ref_section = "**User's explicitly referenced memories:**\n" +    │
│                 referenced_only                                      │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Final user_info_text (injected into main LLM prompt):               │
│                                                                      │
│ User Preferences:                                                    │
│ User works in tech, timezone IST, morning person                    │
│                                                                      │
│ **User's explicitly referenced memories (ground truth):**           │
│ - [REFERENCED @ssdva] [fact] Working on project Alpha               │
│ - [REFERENCED @ssdva] [fact] Using Python 3.11                       │
│ - [REFERENCED @prefer_morning_a3f2] [preference] I prefer morning... │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Main LLM receives:                                                   │
│   - User query: "what should I do?"                                 │
│   - Distilled user preferences (condensed context)                  │
│   - Referenced claims verbatim (ground truth, not summarized)       │
│                                                                      │
│ → Generates response using explicitly referenced memories           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Files Reference

### UI Parsing
- **`interface/parseMessageForCheckBoxes.js`** (lines 375-458)
  - `parseMemoryReferences(text)` - Extract `@references` from message
  - 13 test cases in `testParseMemoryReferences()` (lines 461-568)

### Backend Resolution
- **`Conversation.py`**
  - `_get_pkb_context()` (lines ~4800-6600) - Main entry point
  - `_extract_referenced_claims()` (lines 249-308) - Re-injection helper
  - `reply()` (lines 4717+) - Async PKB retrieval invocation

- **`truth_management_system/interface/structured_api.py`**
  - `resolve_reference()` (lines 1159-1274) - Universal resolver
  - `resolve_claim_identifier()` (lines 1102-1157) - Claim-only resolver
  - `autocomplete()` (lines 1276-1338) - Autocomplete for `@references`

### CRUD Operations
- **`truth_management_system/crud/claims.py`**
  - `get_by_friendly_id()` (lines 354-377) - Claim lookup
  - `get_by_claim_number()` (lines 379-401) - Numeric ID lookup
  - `search_friendly_ids()` (lines 403-430) - Autocomplete helper

- **`truth_management_system/crud/contexts.py`**
  - `get_by_friendly_id()` (lines 165-187) - Context lookup
  - `resolve_claims()` (lines 271-320) - Recursive claim collection
  - `search_friendly_ids()` (lines 189-213) - Autocomplete helper

### Database Schema
- **`truth_management_system/schema.py`**
  - `claims` table (lines 35-57) - Includes `claim_number`, `friendly_id`, `possible_questions`
  - `contexts` table (lines 167-178) - Includes `friendly_id`, `parent_context_id`
  - `context_claims` join table (lines 184-188)

### Models
- **`truth_management_system/models.py`**
  - `Claim` dataclass (lines 69-246) - All claim fields
  - `Context` dataclass (lines 523-622) - All context fields
  - `CLAIM_COLUMNS` (line 35-40) - Column definitions
  - `CONTEXT_COLUMNS` (line 59-62) - Column definitions

---

## Summary

**Key Points:**
1. **Multiple ID formats** supported: UUID, claim number, friendly ID, context name
2. **UI parsing** extracts references via regex before sending to server
3. **Backend resolution** tries multiple strategies sequentially (claim number → claim friendly_id → context friendly_id → context name)
4. **Context resolution** is **recursive** (collects all claims from context tree)
5. **Priority system** deduplicates claims across multiple sources
6. **Post-distillation re-injection** ensures explicitly referenced claims bypass LLM summarization

**Design Rationale:**
- **Friendly IDs:** Human-readable, memorable, URL-safe
- **Claim numbers:** Simple, incrementing, easy to remember (`#42`)
- **Contexts:** Organize memories hierarchically, reference entire projects/topics
- **Recursive resolution:** Natural mental model (project → sub-project → tasks)
- **Re-injection:** Preserve user intent (if they explicitly asked for it, show it verbatim)

**Testing:**
- 13 UI parsing test cases cover all edge cases
- Backend resolution handles all ID formats gracefully
- Fallbacks ensure user intent is preserved even with typos

---

**End of Document**
