# PKB Reference Resolution Flow: Complete Technical Guide

**Last Updated:** 2026-02-09  
**Version:** v0.8

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

Contexts form a **tree hierarchy**. Example:

- **Project Alpha** (`@ssdva`) -- root context
  - **Backend** (`@backend_ssdva_sub1`) -- child of Project Alpha
    - API Design -- child of Backend
    - Database Schema -- child of Backend
  - **Frontend** (`@frontend_ssdva_sub2`) -- child of Project Alpha
    - UI Components -- child of Frontend
    - State Management -- child of Frontend

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

### XML-Tagged Format

Each claim is wrapped in a `<pkb_item>` XML tag with structured attributes:

```xml
<!-- source: referenced | attached | pinned | conv_pinned | auto -->
<!-- type: fact | preference | decision | conversation_message | etc. -->
<!-- ref: optional @friendly_id or @conversation_..._message_... reference -->

<pkb_item source="referenced" type="fact" ref="@ssdva">Working on project Alpha (answers: What project am I on?)</pkb_item>
<pkb_item source="referenced" type="preference" ref="@prefer_morning_a3f2">I prefer morning workouts</pkb_item>
<pkb_item source="attached" type="decision">Using Python 3.11</pkb_item>
<pkb_item source="pinned" type="fact">My timezone is IST</pkb_item>
<pkb_item source="conv_pinned" type="preference">I like detailed explanations</pkb_item>
<pkb_item source="auto" type="fact">I work in tech</pkb_item>
```

**Why XML tags instead of bullet prefixes?**

The previous format used `- [SOURCE] [type] statement` bullets separated by newlines. This broke when item content contained its own newlines or bullet points (e.g., cross-conversation message references with markdown-formatted text). The XML `<pkb_item>...</pkb_item>` tags provide unambiguous boundaries regardless of content, and LLMs handle XML-tagged content well.

### Legacy Bullet Format (Backward Compatibility)

The old format is still supported by the parser as a fallback:

```
- [REFERENCED @ssdva] [fact] Working on project Alpha (answers: What project am I on?)
- [ATTACHED] [decision] Using Python 3.11
- [PINNED] [fact] My timezone is IST
- [CONV-PINNED] [preference] I like detailed explanations
- [fact] I work in tech
```

### Source Attributes

| Source Attribute | Meaning | Why Important |
|-------|---------|---------------|
| `source="referenced"` (with `ref="@fid"`) | User explicitly asked for this memory/context | **Must not be dropped** by distillation |
| `source="referenced"` (no ref) | Legacy UUID reference | **Must not be dropped** by distillation |
| `source="attached"` | User clicked "Use Now" in UI | High priority, user intent |
| `source="pinned"` | User pinned globally (persistent) | Always relevant |
| `source="conv_pinned"` | Pinned to this conversation (ephemeral) | Session-specific relevance |
| `source="auto"` | Hybrid search result | Contextually relevant |

### Deduplication Logic

```python
seen_ids = set()
formatted_claims = []

# Priority 0: Referenced
for claim in referenced_claims:
    if claim.claim_id not in seen_ids:
        seen_ids.add(claim.claim_id)
        formatted_claims.append(
            f'<pkb_item source="referenced" type="{claim.claim_type}" ref="@{fid}">'
            f'{claim.statement}</pkb_item>'
        )

# Priority 1: Attached
for claim in attached_claims:
    if claim.claim_id not in seen_ids:  # Skip if already added as REFERENCED
        seen_ids.add(claim.claim_id)
        formatted_claims.append(
            f'<pkb_item source="attached" type="{claim.claim_type}">'
            f'{claim.statement}</pkb_item>'
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

**Location:** `Conversation.py` (lines 249-330)

**Purpose:** Parse PKB context and extract only `source="referenced"` items.

**Algorithm:**
```python
def _extract_referenced_claims(pkb_context):
    """
    Parse XML-tagged PKB context and extract only referenced items.
    Falls back to legacy bullet parsing for backward compatibility.
    
    Example input (XML format):
    <pkb_item source="referenced" type="fact" ref="@ssdva">Working on Alpha</pkb_item>
    <pkb_item source="auto" type="fact">I work in tech</pkb_item>
    <pkb_item source="referenced" type="preference" ref="@prefer">Morning workouts</pkb_item>
    
    Output (full XML tags preserved):
    <pkb_item source="referenced" type="fact" ref="@ssdva">Working on Alpha</pkb_item>
    <pkb_item source="referenced" type="preference" ref="@prefer">Morning workouts</pkb_item>
    """
    if not pkb_context:
        return ""
    
    # Parse <pkb_item> tags with DOTALL regex
    xml_pattern = re.compile(r'<pkb_item\s+([^>]*)>(.*?)</pkb_item>', re.DOTALL)
    matches = list(xml_pattern.finditer(pkb_context))
    if matches:
        referenced = [m.group(0) for m in matches
                      if 'source="referenced"' in m.group(1)]
        return '\n'.join(referenced)
    
    # Legacy fallback: split on "\n- [" and check for [REFERENCED
    # ...
```

**Why XML parsing?**
- Previous approach split on `\n- [` boundaries which broke when item content contained newlines
- XML `<pkb_item>` tags provide unambiguous boundaries via DOTALL regex
- Filtering by `source="referenced"` attribute is simpler and more robust than checking for `[REFERENCED` substring
- Full XML tags are preserved in the output so the LLM can interpret them

---

## Complete Data Flow

This section traces a complete example through the system. The user types: `"@ssdva @prefer_morning_a3f2 what should I do?"`

### Step 1: UI Parsing

**Function:** `parseMemoryReferences()` in `interface/parseMessageForCheckBoxes.js:375`

The UI applies two regexes to extract references before sending to the server:

- `legacyRegex` (`/@(?:memory|mem):([a-zA-Z0-9-]+)/g`) -- matches `@memory:uuid` format. Result for this input: `claimIds: []` (none matched).
- `friendlyRegex` (`/@([a-zA-Z][a-zA-Z0-9_-]{2,})/g`) -- matches `@identifier` format (3+ chars, starts with letter). Checks whitespace before `@` (not email), skips standalone `@memory`/`@mem`. Result: `friendlyIds: ["ssdva", "prefer_morning_a3f2"]`.

Clean text sent to server: `"what should I do?"`

### Step 2: HTTP Request

**Endpoint:** `POST /send_message/<conversation_id>`

Request body:
```json
{
  "messageText": "what should I do?",
  "referenced_friendly_ids": ["ssdva", "prefer_morning_a3f2"],
  "checkboxes": { "use_pkb": true }
}
```

### Step 3: Server Routing

**File:** `endpoints/conversations.py`

The endpoint handler injects `conversation_pinned_claim_ids` from session state, then calls `conversation.reply(query)`.

### Step 4: Async PKB Retrieval

**Function:** `Conversation.reply()` at `Conversation.py:4717`

If `use_pkb` is true and `user_email` is present, launches an async future:

```python
pkb_context_future = get_async_future(
    self._get_pkb_context,
    user_email,
    query["messageText"],
    k=10,
    referenced_friendly_ids=["ssdva", "prefer_morning_a3f2"]
)
```

This runs in parallel with embeddings and other preprocessing.

### Step 5: Reference Resolution (inside `_get_pkb_context`)

**Function:** `_get_pkb_context()` at `Conversation.py:452`

For each friendly ID, calls `api.resolve_reference(fid)` which tries resolution strategies sequentially (see "Backend Resolution Flow" section above).

**For `"ssdva"`:** Step 1 (@claim_N?) -- No. Step 2 (claim friendly_id?) -- No. Step 3 (context friendly_id?) -- Yes. Resolves via `contexts.get_by_friendly_id("ssdva")` to `context_id="ctx-uuid-123"`, then `contexts.resolve_claims()` with recursive CTE. Returns `type='context', claims=[c1, c2, c3]` (all claims from context tree).

**For `"prefer_morning_a3f2"`:** Step 1 (@claim_N?) -- No. Step 2 (claim friendly_id?) -- Yes. Resolves via `claims.get_by_friendly_id("prefer_morning_a3f2")` to `claim_id="claim-uuid-456"`. Returns `type='claim', claims=[claim456]`.

### Step 6: XML Formatting

All resolved claims are formatted as XML-tagged items:

```xml
<pkb_item source="referenced" type="fact" ref="@ssdva">Working on project Alpha (answers: What project am I on?)</pkb_item>
<pkb_item source="referenced" type="fact" ref="@ssdva">Using Python 3.11 for Alpha</pkb_item>
<pkb_item source="referenced" type="decision" ref="@ssdva">Microservices architecture</pkb_item>
<pkb_item source="referenced" type="preference" ref="@prefer_morning_a3f2">I prefer morning</pkb_item>
```

### Step 7: Collect Other Priority Levels

After referenced items, `_get_pkb_context` collects from lower-priority sources (attached, globally pinned, conversation pinned, auto-search), deduplicating by `claim_id` (highest priority wins). All are wrapped in `<pkb_item>` tags.

Full PKB context example:

```xml
<pkb_item source="referenced" type="fact" ref="@ssdva">Working on project Alpha</pkb_item>
<pkb_item source="referenced" type="fact" ref="@ssdva">Using Python 3.11</pkb_item>
<pkb_item source="referenced" type="preference" ref="@prefer_morning_a3f2">I prefer morning...</pkb_item>
<pkb_item source="auto" type="fact">I work in tech</pkb_item>
<pkb_item source="pinned" type="fact">My timezone is IST</pkb_item>
```

### Step 8: Stage 1 -- Distillation (Cheap LLM)

The full PKB context (XML-tagged) plus `user_memory` and `user_preferences` are sent to a cheap LLM for distillation. The prompt asks it to extract the most relevant user preferences and context for answering the query.

Input includes all items (referenced + auto + pinned). Output is a condensed summary like: `"User works in tech, timezone IST, morning person"`. The distillation may drop or paraphrase some claims to save tokens.

### Step 9: Stage 2 -- Re-inject Referenced Items

**Function:** `_extract_referenced_claims()` at `Conversation.py:249`

Parses the original PKB context for `<pkb_item>` tags with `source="referenced"` attribute. Keeps only those items (full XML tags preserved):

```xml
<pkb_item source="referenced" type="fact" ref="@ssdva">Working on project Alpha</pkb_item>
<pkb_item source="referenced" type="fact" ref="@ssdva">Using Python 3.11</pkb_item>
<pkb_item source="referenced" type="preference" ref="@prefer">I prefer morning...</pkb_item>
```

These are appended after the distillation output as `"**User's explicitly referenced memories (ground truth):**"` + the referenced items.

### Step 10: Final Prompt Assembly

The main LLM receives `user_info_text` containing:

1. **Distilled preferences** (condensed from cheap LLM): `"User works in tech, timezone IST, morning person"`
2. **Referenced items verbatim** (not summarized, ground truth): the 3 referenced `<pkb_item>` tags from Step 9

The main LLM also receives the user query `"what should I do?"`, conversation history, system prompt, etc. It generates a response using the explicitly referenced memories as ground truth.

---

## Cross-Conversation Message References

In addition to PKB references (`@claim_42`, `@context_fid`, `@entity_fid`, `@tag_fid`, `@domain_fid`), the `@reference` system also supports **cross-conversation message references** using the syntax:

```
@conversation_<conv_friendly_id>_message_<index_or_hash>
```

These are handled as a separate branch in `_get_pkb_context()` **before** the PKB resolution loop.

### How they differ from PKB references

| Aspect | PKB References | Cross-Conversation References |
|--------|---------------|-------------------------------|
| Syntax | `@friendly_id` (with optional suffix) | `@conversation_<fid>_message_<id>` |
| Resolver | `StructuredAPI.resolve_reference()` | `Conversation._resolve_conversation_message_refs()` |
| Data source | PKB SQLite (`pkb.sqlite`) | Conversation storage (dill `.index` files) |
| Content type | Atomic claims (1-line statements) | Full message text (possibly multi-KB) |
| Detection | No `conversation_` prefix | `CONV_REF_PATTERN` regex match |
| Truncation | None (claims are short) | 8000 chars max |

### Detection regex

```python
CONV_REF_PATTERN = re.compile(
    r'^(?:conversation|conv)_(.+)_(?:message|msg)_([a-z0-9]+)$'
)
```

The greedy `.+` captures everything up to the LAST `_message_` or `_msg_`, handling underscores in friendly IDs correctly.

### Resolution flow

1. `_get_pkb_context()` partitions `referenced_friendly_ids` into `conv_refs` and `pkb_fids`.
2. `_resolve_conversation_message_refs()` is called for `conv_refs`:
   - DB lookup: `getConversationIdByFriendlyId(users_dir, user_email, conv_fid)` (scoped by user).
   - Load conversation via `conversation_loader` (LRU cache) or `Conversation.load_local()` fallback.
   - Extract message by 1-based index (digits) or `message_short_hash` (6-char alphanumeric).
3. Resolved messages are wrapped as mock claim-like objects with `claim_type = "conversation_message"` and injected into `all_claims` with source `"referenced_@conversation_..."`. The XML formatting wraps them as `<pkb_item source="referenced" type="conversation_message" ref="@conversation_...">...</pkb_item>`.
4. The `source="referenced"` attribute ensures they survive `_extract_referenced_claims()` post-distillation re-injection.

### Coexistence with PKB references

Cross-conversation references and PKB references can be mixed in the same message. For example:

```
@conversation_react_optimization_b4f2_message_a3f2b1 @my_health_context Apply the approach from the React chat to my health tracker
```

Both are captured by the existing `friendlyRegex` in `parseMemoryReferences()`. The backend separates them by pattern matching before resolution.

For full details, see [Cross-Conversation Message References](../cross_conversation_references/README.md).

---

## Key Files Reference

### UI Parsing
- **`interface/parseMessageForCheckBoxes.js`** (lines 375-458)
  - `parseMemoryReferences(text)` - Extract `@references` from message
  - 13 test cases in `testParseMemoryReferences()` (lines 461-568)

### Backend Resolution
- **`Conversation.py`**
  - `_get_pkb_context()` (lines ~4800-6600) - Main entry point (handles both PKB and cross-conversation refs)
  - `_resolve_conversation_message_refs()` - Cross-conversation message resolution
  - `_ensure_conversation_friendly_id()` - Friendly ID generation on first persist
  - `_extract_referenced_claims()` (lines 249-308) - Re-injection helper
  - `reply()` (lines 4717+) - Async PKB retrieval invocation

- **`conversation_reference_utils.py`** (repo root)
  - `CONV_REF_PATTERN` - Regex for detecting cross-conversation refs
  - `generate_conversation_friendly_id(title, created_at)` - Conversation ID generation
  - `generate_message_short_hash(conv_fid, message_text)` - Message hash generation
  - `_to_base36(num, length)` - Base36 encoding helper

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
