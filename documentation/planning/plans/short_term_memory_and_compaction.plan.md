---
name: Short-Term Cross-Conversation Memory & Compaction
overview: "Add a short-term memory layer to PKB that captures ephemeral cross-conversation context (with LLM-judged importance + TTL), auto-injects recent context into new conversations, auto-promotes reinforced memories to long-term, and provides a unified cleanup/compaction modal."
todos:
  - id: schema-short-term-table
    content: Create pkb_short_term_memory table with TTL, importance, conversation_id, expires_at, last_accessed_at
    status: done
  - id: last-accessed-tracking
    content: Add last_accessed_at column to claims table + update on retrieval
    status: done
  - id: extraction-dual-output
    content: Modify conversation_distillation to produce both short-term and long-term suggestions in one pass with importance + TTL judgment
    status: done
  - id: short-term-crud
    content: Add CRUD methods for short-term memories in structured_api.py (add, get, list, delete, expire)
    status: done
  - id: auto-expire-sweep
    content: Extend expire_stale_claims() to also sweep expired short-term memories
    status: done
  - id: retrieval-injection
    content: Inject top 5-10 recent short-term memories into conversation context (recency-sorted, before PKB retrieval)
    status: done
  - id: promotion-logic
    content: Auto-promote short-term memories to long-term claims when reinforced across 3+ conversations
    status: done
  - id: compaction-orchestrator
    content: Extend Memory Cleanup to include compaction (archive old low-access claims) and present unified suggestion modal
    status: done
  - id: ui-short-term-section
    content: Add "Recent cross-conversation context" section within PKB tab with auto-expire badges
    status: done
  - id: endpoints
    content: REST endpoints for short-term memory CRUD + compaction trigger
    status: done
  - id: tests
    content: Unit tests for extraction, expiry, promotion, compaction
    status: done
---

# Short-Term Cross-Conversation Memory & Compaction

## Motivation & Problem Statement

### The gap today

The system has 3 disconnected memory layers:
1. **Within-conversation**: Memory pad + conversation summary — dies with the session.
2. **Long-term PKB**: Permanent facts, preferences, decisions — persists forever.
3. **Cross-conversation search**: FTS index over past conversations — exists but the system doesn't know *what* to search for because it has no awareness of recent activity.

**Missing: short-term cross-conversation memory.** When a user starts a new conversation after spending 3 sessions debugging a React hook issue, the system has zero awareness of that context unless the user explicitly references it. The long-term PKB doesn't store "user is currently debugging a React hook" because it's ephemeral. The memory pad is gone (previous conversation ended).

### What goes wrong

- **Ephemeral context pollutes long-term KB**: "User is learning Python" gets stored as a permanent fact. 6 months later it still surfaces during retrieval.
- **No cross-conversation continuity**: Starting a new chat loses all "what am I working on" context.
- **Precision degradation over time**: Low-importance, never-accessed claims accumulate and dilute retrieval quality.
- **No importance filtering at extraction time**: Every extractable fact is treated equally — "user is vegetarian" and "user asked about a Python import error" get the same persistence.

### How this solves it

Short-term memories give the system a "recent activity map" that:
- Auto-injects into new conversations ("I know you were debugging X last session")
- Enables intelligent cross-conversation search triggering
- Auto-expires so no manual cleanup needed
- Promotes to long-term only when reinforced (proving persistence value)

---

## Architecture: 3-Layer Memory Model

### Layer 1: Within-Conversation (existing, unchanged)
- Memory pad (rolling state summary)
- Conversation summary (condensed history)
- Message context window
- Lives and dies with the conversation. No PKB involvement.

### Layer 2: Short-Term Cross-Conversation (new)
- Stored in `pkb_short_term_memory` table
- `conversation_id` attached — knows which conversation produced it
- LLM-judged TTL: `session` (4h), `day` (24h), `week` (7d)
- LLM-judged importance: `low` (don't store), `medium`, `high`
- Auto-expires via `expires_at` timestamp
- Retrieved by recency (no search needed — just top N most recent)
- Promotes to long-term when reinforced across 3+ conversations

### Layer 3: Long-Term (existing PKB claims table)
- `conversation_id` stored in `meta_json.source.conversation_id` for provenance only
- No TTL (or very long — years)
- Subject to compaction/archival sweep (new: `last_accessed_at` tracking)
- Permanent facts, preferences, decisions

---

## Requirements

### R1: Short-Term Memory Table

New SQLite table in the same database:

```sql
CREATE TABLE IF NOT EXISTS pkb_short_term_memory (
    memory_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    importance TEXT NOT NULL DEFAULT 'medium',  -- medium|high (low = not stored)
    ttl_class TEXT NOT NULL DEFAULT 'week',     -- session|day|week
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_accessed_at TEXT,
    reinforcement_count INTEGER NOT NULL DEFAULT 0,
    promoted_to_claim_id TEXT,                  -- NULL until promoted to long-term
    meta_json TEXT                              -- {tags, entities, reasoning, source_conversation_title}
);

CREATE INDEX IF NOT EXISTS idx_stm_user_expires ON pkb_short_term_memory(user_email, expires_at);
CREATE INDEX IF NOT EXISTS idx_stm_user_recency ON pkb_short_term_memory(user_email, created_at DESC);
```

TTL mappings:
- `session` → 4 hours
- `day` → 24 hours
- `week` → 7 days

### R2: Dual-Output Extraction

The existing auto-extraction hook (conversation_distillation) produces both outputs in a single LLM pass:

```json
{
  "long_term": [
    {"statement": "User is vegetarian", "claim_type": "preference", ...}
  ],
  "short_term": [
    {"statement": "User is debugging a React useEffect hook in their dashboard component",
     "importance": "high", "ttl": "week",
     "reasoning": "Active task context, relevant across sessions this week"}
  ]
}
```

**Extraction rules for the LLM prompt:**
- `importance: low` → do NOT store (e.g., "user wants to learn X framework" — too vague/transient)
- `importance: medium` → store with shorter TTL
- `importance: high` → store, candidate for promotion if reinforced
- Skip if already in long-term PKB (avoid duplication)
- Skip pure conversation mechanics ("user said thanks", "user asked to clarify")
- Skip things the memory pad covers for the current conversation
- The prompt includes the user's **current active short-term memories** so the LLM can: avoid re-extracting duplicates, recognize updates to existing STM (output `"update": "memory_id"` instead of new entry), and judge whether something truly adds new cross-conversation context

**Guidance for importance judgment:**
- High: Active projects, ongoing debugging, multi-session tasks, decisions being evaluated
- Medium: Current interests, temporary preferences, one-off context
- Low (don't store): Passing mentions, learning interests without commitment, trivial observations

### R3: Auto-Injection into Conversations

Before each conversation turn (in `_get_pkb_context()` or earlier):
1. Query `pkb_short_term_memory` for user: `WHERE expires_at > NOW() ORDER BY created_at DESC LIMIT 10`
2. Format as lightweight context block:
   ```
   ## Recent context from your other conversations:
   - [2h ago] Debugging React useEffect hook in dashboard component
   - [1d ago] Working on database migration project, using Alembic
   - [3d ago] Evaluating Tailwind vs styled-components for new frontend
   ```
3. Inject into the system prompt before the PKB retrieval section
4. Update `last_accessed_at` for injected memories

**Budget**: Max 200 words for this section. If more than 10 memories qualify, take top 10 by importance × recency.

### R4: Promotion to Long-Term

When a short-term memory is **reinforced** (the same topic appears in a different conversation's extraction output):
1. Increment `reinforcement_count`
2. Reset `expires_at` (extend TTL)
3. When `reinforcement_count >= 3` AND importance = high:
   - Create a long-term claim from it (appropriate `claim_type`, `context_domain`)
   - Set `promoted_to_claim_id` on the short-term record
   - Mark short-term record as promoted (keep for audit, will eventually expire)

**Reinforcement detection**: During extraction, before storing a new short-term memory, check existing short-term memories for semantic overlap (simple keyword/embedding match). If >0.8 similarity to an existing memory from a *different* conversation, reinforce rather than duplicate.

### R5: `last_accessed_at` for Long-Term Claims

Add column to `claims`:
```sql
ALTER TABLE claims ADD COLUMN last_accessed_at TEXT;
```

Update whenever a claim appears in search results that are sent to the LLM (after distillation, update the claims that were actually used):
```python
# After distillation in _get_pkb_context()
accessed_ids = [c['claim_id'] for c in claims_sent_to_distiller]
db.execute("UPDATE claims SET last_accessed_at = ? WHERE claim_id IN (...)", now_iso(), accessed_ids)
```

This enables:
- Smart compaction (never accessed in 90+ days → suggest archive)
- Decay-based ranking (complement to `last_reinforced_at`)
- Usage analytics in UI

### R6: Compaction & Cleanup Orchestrator

Extend the existing Memory Cleanup (`POST /pkb/cleanup`) to be a **one-stop button** that:

1. **Expire short-term memories** — delete records past `expires_at`
2. **Archive stale long-term claims** — identify claims where:
   - `last_accessed_at` > 90 days (or NULL and `updated_at` > 90 days)
   - `confidence` < 0.5
   - Not pinned, not referenced by other active claims
   - Suggest `status → archived`
3. **Consolidate near-duplicates** — existing dedup logic
4. **Entity/tag dedup** — existing merge logic
5. **Refresh overview** — trigger overview update after changes

**UI flow:**
- Button: "Cleanup & Compact" in PKB Management tab (or Maintenance tab)
- Click → runs analysis (streaming progress)
- Presents modal with categorized suggestions:
  - "Archive these stale claims" (list with accept/reject checkboxes)
  - "Merge these duplicates" (list with accept/reject)
  - "Expired short-term memories removed: N"
  - Stats: "Freed N claims, merged M duplicates"
- User accepts/rejects per-item or bulk
- Apply → executes accepted changes

### R7: UI — Short-Term Memory Section

Within the existing PKB tab (not a new tab), add a collapsible section:

**"Recent Cross-Conversation Context"**
- Shows active (non-expired) short-term memories
- Each item shows:
  - Statement text
  - Source conversation title (linked)
  - Time remaining (badge: "expires in 3d", "expires in 5h")
  - Importance badge (medium/high)
  - Reinforcement count if > 0
  - "Promote to permanent" button (manual promotion)
  - "Dismiss" button (expire immediately)
- Sorted by recency
- Collapsed by default if empty

---

## Interactions with Existing Systems

### Schema Migration (current: v11)
New table + column additions follow the established pattern in `database.py`:
- `_migrate_v11_to_v12()`: adds `pkb_short_term_memory` table + `last_accessed_at` column on `claims`
- Idempotent: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN` with try/except
- Backfill `last_accessed_at` from `updated_at` for existing claims (same pattern as v8 `last_reinforced_at` backfill)

### Provenance for Promoted Claims
When a short-term memory promotes to long-term:
- `channel = "chat"` (it came from conversation extraction)
- `derivation = "extracted"` (LLM extracted, user never stated it as a "fact to remember")
- `meta_json.source.conversation_id` = the *first* conversation that produced it
- `meta_json.source.promoted_from_stm` = memory_id (audit trail back to short-term)
- `confidence` = `inferred_confidence_cap` (0.4) since it was extracted, not stated — same rule as inferred claims. Gets the rerank penalty too. User can later reinforce to upgrade.

### Interaction with Existing Dormancy / Decay
- `decay_dormant_claims()` already exists for long-term claims — unchanged
- Short-term memories don't use dormancy (they have hard TTL via `expires_at`)
- `last_accessed_at` on claims gives the compaction sweep a better signal than `last_reinforced_at` alone (reinforcement requires the *same fact* restated; access just means it was retrieved)
- `recency_rerank` currently reads `last_reinforced_at` → should also consider `last_accessed_at` as a secondary signal (take the more recent of the two)

### Interaction with Overview System
- Short-term memories do **NOT** trigger overview updates (they live in a separate table, not in `claims`)
- When a short-term memory is **promoted** to a long-term claim, that `add_claim()` call fires the normal overview write hook → overview learns about the new permanent fact
- The overview's Key Areas thus reflects only persistent knowledge, not ephemeral context — this is correct behavior

### Interaction with Cross-Conversation Search
The existing `CrossConversationIndex` (FTS5 over titles/summaries/memory_pads/message_tldrs) already provides *how* to search across conversations. Short-term memories solve *when* to search:
- The injected "Recent context" block gives the LLM awareness of recent topics
- LLM tools (`cross_conversation_search`) can now be triggered intelligently because the system prompt mentions the recent context
- Example: if short-term memory says "debugging React hook in dashboard" and user says "let's continue where we left off", the LLM now has enough context to invoke cross-conversation search with the right query

### Interaction with NL Agent (`/pkb` commands)
- `/pkb` and `/memory` commands currently skip auto-extraction (`auto_pkb_extract` is not fired for them)
- Short-term extraction should **also** be skipped for `/pkb` commands (same gating)
- But `/pkb search` should optionally search short-term memories too (see Open Question 1)
- The NL agent already receives Key Areas in system prompt; it should also receive the short-term context block for continuity awareness

### Interaction with Auto-Save Proposal Modal
- The existing bulk proposal modal (`#memory-proposal-modal`) handles long-term claims
- Short-term memories should be **stored silently** (no modal approval needed) — they're ephemeral and auto-expire. Requiring user approval for every session context would be disruptive.
- Only **long-term** suggestions continue through the existing propose → modal → approve flow
- This is a key UX decision: short-term = silent extraction, long-term = user-approved

### Interaction with Existing `valid_to` / Expiry
- Claims table has `valid_to` → `expire_stale_claims()` marks as `expired`
- Short-term table has `expires_at` → separate sweep (simpler: just DELETE, not status change)
- No conflict — different tables, different semantics
- `expire_stale_claims()` extended to also sweep `pkb_short_term_memory` in the same pass

### Interaction with `reinforce_claim()` 
- When the distiller detects a near-duplicate of an existing long-term claim → existing `reinforce` path (unchanged)
- When the distiller detects a near-duplicate of an existing **short-term** memory from a *different* conversation → short-term `reinforce` (increment count, extend TTL, check promotion)
- When the distiller detects a near-duplicate of an existing short-term memory from the *same* conversation → skip (same-session dedup)
- Matching approach: same embedding similarity used for long-term duplicate detection, threshold configurable (`stm_reinforcement_threshold`, default 0.85)

---

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Separate table vs column on claims | Separate table | Different lifecycle, extraction, retrieval, and cleanup logic. Cleaner separation of concerns. |
| LLM judges importance at extraction time | Yes | Filter at write-time is cheaper than accumulate-then-clean. Prevents low-value memories from ever being stored. |
| Low importance = don't store | Yes | "User wants to learn X framework" is not worth storing. Reduces noise proactively. |
| Injection method | Auto-inject top 5-10 into every turn | Cheap (recency query, no embedding search needed). Gives "recent activity awareness" for free. |
| Promotion threshold | 3 reinforcements across different conversations | Proves the topic persists across sessions, not just a one-off. |
| Compaction as unified modal | Yes | One button for all cleanup. Accept/reject per-suggestion. User stays in control. |
| UI placement | Section within existing PKB tab | Not complex enough for its own tab. Collapsible keeps it unobtrusive. |
| Extraction: one pass or two | One pass, dual output | Saves an LLM call. Same context produces both short-term and long-term in one JSON response. |
| Short-term retrieval strategy | Pure recency (no search) | These are injected every turn regardless of query. Search is for long-term. |
| Short-term storage: silent vs approval | Silent (no modal) | Ephemeral context doesn't warrant user interruption. Long-term still goes through approval. |
| Schema version | v12 (after current v11) | Follow sequential migration pattern |
| Promoted claim provenance | channel=chat, derivation=extracted, confidence=capped | Same trust level as other extracted claims until user reinforces |
| Recency rerank signal | `max(last_reinforced_at, last_accessed_at)` | Access proves relevance even without restatement; frequently-retrieved claims decay slower |
| STM dedup strategy | Pre-extraction (LLM sees existing STM) | LLM avoids duplicates at source; can judge "update vs duplicate" nuance; cleaner output |
| Cross-conv search triggering | LLM judgment (tool calling) | STM provides awareness; LLM decides when to search. No brittle heuristics, no wasted searches |
| Overview interaction | None until promotion | Overview reflects only persistent knowledge, not ephemeral context |

---

## Open Questions

1. **Should short-term memories participate in search?** Currently proposed as inject-only (top N by recency). But should `api.search()` also search short-term memories when doing hybrid search? Pros: catches relevant recent context even if not in top-10. Cons: adds complexity, they already auto-inject.

2. **Deduplication between short-term and long-term at extraction**: If the extraction produces a long-term suggestion that's semantically identical to an existing long-term claim, the existing dedup-at-add logic handles it (near-duplicate detection). But for short-term, should we also deduplicate against existing short-term memories from the *same* conversation? (Probably yes — avoid "user is debugging React hook" appearing 5 times from the same session.)

3. **Compaction aggressiveness**: Should archived claims be permanently deleted after N days, or kept indefinitely in archived state? (Lean: keep archived forever, they're cheap. User can manually purge if they want.)

4. **Short-term memory cap per user**: Should there be a max (e.g., 50 active short-term memories)? If someone has many active conversations, could accumulate many. A cap with LRU eviction prevents unbounded growth.

5. **Should the compaction modal also suggest promoting high-value short-term memories?** e.g., "This memory has been reinforced 2 times — promote to permanent?" (even below the auto-promote threshold of 3).

6. **`last_accessed_at` vs `last_reinforced_at` for recency rerank**: ~~Currently `apply_recency_confidence_rerank` reads `last_reinforced_at` for its decay formula. Should it use `max(last_reinforced_at, last_accessed_at)` instead?~~ **DECIDED: Yes.** Take the more recent of the two. Access proves relevance even without restatement.

7. **Extraction context**: ~~Should the short-term extraction LLM see existing short-term memories to avoid re-extracting the same thing?~~ **DECIDED: Pre-extraction dedup (LLM sees existing STM).** Include current short-term memories in the extraction prompt so the LLM avoids outputting duplicates. Adds ~200-500 tokens per extraction call but produces cleaner output and avoids post-processing. The LLM can also make nuanced judgments (e.g., "this is an update to an existing STM, not a duplicate").

8. **Cross-conversation search triggering**: ~~Should the system automatically invoke cross-conversation search when short-term memories are relevant to the current query?~~ **DECIDED: LLM judgment via tool calling.** STM injection gives the LLM awareness; it decides when to invoke `cross_conversation_search`. No brittle heuristics, no wasted searches on every turn. If unreliable in practice, add a system prompt hint.

---

## Implementation Plan

### Phase 1: Foundation (can be done independently)
1. `last_accessed_at` column on claims + update-on-retrieval logic
2. `pkb_short_term_memory` table DDL + migration (v11 → v12)
3. CRUD methods in structured_api.py

### Phase 2: Extraction
4. Modify conversation_distillation prompt to produce dual output (short_term + long_term)
5. Wire short-term storage into the extraction hook (silent, no modal)
6. Same-session dedup (embedding similarity check against existing STM from same conversation)
7. Cross-conversation reinforcement detection (similarity check against STM from *different* conversations)

### Phase 3: Retrieval & Injection
8. Auto-inject recent short-term memories into conversation context (in `_get_pkb_context` or `reply()`)
9. Also inject into NL agent system prompt
10. Auto-expire sweep in `expire_stale_claims()` — DELETE expired STM rows
11. Update `last_accessed_at` on long-term claims after distillation

### Phase 4: Promotion & Compaction
12. Promotion logic (reinforce + auto-promote at threshold 3)
13. Extended compaction orchestrator (archive stale long-term, expire short-term, dedup, promote suggestions)
14. Compaction suggestion modal UI (extend existing Maintenance tab)

### Phase 5: UI
15. "Recent cross-conversation context" collapsible section in PKB tab
16. Promote/dismiss buttons per memory
17. Compaction modal with categorized accept/reject

---

## Config Fields (new in PKBConfig)

```python
# Short-term memory
stm_ttl_session_hours: float = 4.0
stm_ttl_day_hours: float = 24.0
stm_ttl_week_days: float = 7.0
stm_max_per_user: int = 50                  # Cap, LRU eviction beyond this
stm_inject_limit: int = 10                  # Max memories injected per turn
stm_inject_max_words: int = 200             # Budget for injection block
stm_reinforcement_threshold: float = 0.85   # Embedding similarity for reinforce
stm_promotion_threshold: int = 3            # Reinforcements needed for promotion
stm_enabled: bool = True                    # Feature toggle

# Compaction
compaction_stale_days: int = 90             # last_accessed_at threshold for archive suggestion
compaction_confidence_threshold: float = 0.5  # Below this + stale → suggest archive
compaction_enabled: bool = True             # Feature toggle
```

---

## Files Expected to Change

- `truth_management_system/schema.py` — new table DDL, v12 migration, `last_accessed_at` column
- `truth_management_system/database.py` — `_migrate_v11_to_v12()` function
- `truth_management_system/interface/structured_api.py` — short-term CRUD methods, compaction extension, promotion logic
- `truth_management_system/interface/conversation_distillation.py` — dual-output extraction prompt, short-term storage wiring
- `truth_management_system/config.py` — TTL mappings, STM config fields, compaction thresholds
- `truth_management_system/utils.py` — `expire_stale_claims()` extension to sweep STM table
- `truth_management_system/search/base.py` — `apply_recency_confidence_rerank` to consider `last_accessed_at`
- `Conversation.py` — short-term injection in `_get_pkb_context()`, `last_accessed_at` update after distillation
- `endpoints/pkb.py` — REST endpoints for short-term CRUD, extended cleanup
- `interface/pkb-manager.js` — short-term section UI, promote/dismiss handlers, compaction modal
- `interface/interface.html` — HTML for short-term section + compaction modal enhancements
- `truth_management_system/interface/nl_agent.py` — inject STM context into NL agent system prompt
- `truth_management_system/tests/test_short_term.py` — unit tests for STM CRUD, expiry, promotion, extraction
