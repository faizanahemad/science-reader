# Short-Term Cross-Conversation Memory

**Status:** Implemented (schema v12)
**Plan:** `documentation/planning/plans/short_term_memory_and_compaction.plan.md`

## Motivation

The PKB had a gap between within-conversation memory (dies when the session ends) and long-term claims (permanent facts). When a user spends 3 sessions debugging a React hook, starts a new conversation, and expects the system to remember — it couldn't. Short-term memory fills this gap: ephemeral cross-conversation context that auto-injects into new conversations, auto-expires, and auto-promotes to long-term if reinforced.

## Architecture: 3-Layer Memory Model

| Layer | Storage | Lifetime | Approval |
|-------|---------|----------|----------|
| Within-conversation | Memory pad + summary | Session only | None |
| **Short-term (NEW)** | `pkb_short_term_memory` table | 4h / 24h / 7d (TTL classes) | Silent (no modal) |
| Long-term | `claims` table | Permanent | User-approved modal |

## Data Flow

```
User message
    ↓
POST /pkb/propose_updates (existing extraction hook)
    ↓
ConversationDistiller.extract_and_propose()
    ├── _extract_claims_from_turn() → long-term candidates (existing)
    └── _extract_short_term_memories() → short-term candidates (NEW)
            ↓
    For each short-term candidate:
        1. Check existing STM for semantic overlap (SequenceMatcher ≥ 0.85)
           from a DIFFERENT conversation → reinforce existing memory
        2. Check same-conversation STM for dedup → skip if duplicate
        3. Otherwise → api.add_short_term_memory() (silent, no modal)
            ↓
    Auto-promote if reinforcement_count ≥ 3 AND importance = "high"
```

## Context Injection

In `Conversation._get_pkb_context()`, before PKB claims are formatted:

1. Query `get_active_short_term_memories(limit=stm_inject_limit)`
2. Format as `<stm_context>` block with relative timestamps ("3h ago", "2d ago")
3. Enforce word budget (`stm_inject_max_words`, default 200)
4. Call `touch_short_term_memories()` for accessed IDs
5. Prepend to the PKB claims XML output

The LLM sees this as:
```
<stm_context>
## Recent context from your other conversations:
- [3h ago] Working on React dashboard migration from class to hooks
- [1d ago] Debugging useEffect cleanup issue with WebSocket subscriptions
</stm_context>
<pkb_item source="auto" type="preference">User prefers TypeScript...</pkb_item>
...
```

## Recency Rerank Update

`_claim_age_days()` in `search/base.py` now uses `max(last_reinforced_at, last_accessed_at, updated_at)` — claims that were recently retrieved for context are treated as "fresher" in ranking.

## Schema (v12 Migration)

```sql
CREATE TABLE IF NOT EXISTS pkb_short_term_memory (
    memory_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    importance TEXT NOT NULL DEFAULT 'medium',  -- medium|high
    ttl_class TEXT NOT NULL DEFAULT 'week',     -- session|day|week
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_accessed_at TEXT,
    reinforcement_count INTEGER NOT NULL DEFAULT 0,
    promoted_to_claim_id TEXT,
    meta_json TEXT
);

-- Also added to claims table:
ALTER TABLE claims ADD COLUMN last_accessed_at TEXT;
```

TTL mappings (from config):
- `session` → 4 hours
- `day` → 24 hours
- `week` → 7 days

## Config Fields (PKBConfig)

| Field | Default | Description |
|-------|---------|-------------|
| `stm_enabled` | `True` | Enable/disable STM system |
| `stm_ttl_session_hours` | `4` | TTL for "session" class |
| `stm_ttl_day_hours` | `24` | TTL for "day" class |
| `stm_ttl_week_days` | `7` | TTL for "week" class |
| `stm_max_per_user` | `50` | Max active STM per user |
| `stm_inject_limit` | `10` | Max STM injected into context |
| `stm_inject_max_words` | `200` | Word budget for injection |
| `stm_reinforcement_threshold` | `0.85` | SequenceMatcher ratio for dedup/reinforce |
| `stm_promotion_threshold` | `3` | Reinforcements needed for auto-promotion |
| `compaction_stale_days` | `90` | Days of inactivity before "stale" |
| `compaction_confidence_threshold` | `0.5` | Max confidence for stale detection |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/pkb/stm` | List active short-term memories |
| POST | `/pkb/stm/<id>/promote` | Manually promote to long-term claim |
| DELETE | `/pkb/stm/<id>` | Dismiss (delete) a memory |

## UI

**Claims pane** (top): Collapsible "Recent Cross-Conversation Context" card (info-colored). Each memory shows:
- Statement text
- Time remaining badge (e.g. "3d left", "5h left")
- Importance badge (high = red, medium = grey)
- Reinforcement count badge (if > 0)
- Promote button (↑ arrow)
- Dismiss button (× circle)

Hidden when no active STM exists. Auto-refreshes on PKB modal open.

**Maintenance tab**: Cleanup report now shows compaction section:
- STM expired count
- Stale claim candidates (if any) with confidence and last activity date
- Archived count (after Apply)

## Compaction (Extended Memory Cleanup)

`run_memory_cleanup()` now additionally:
1. Expires short-term memories (before lifecycle sweep)
2. Identifies stale long-term claims: `last_accessed_at > 90d`, `confidence < 0.5`, not pinned
3. On `apply=True`: archives stale claims (`status → archived`)

## Extraction Prompt (STM-specific)

A separate LLM call (same model, temperature=0) identifies ephemeral context:
- Active projects/tasks being worked on
- Ongoing debugging sessions
- Decisions being evaluated
- Multi-session work in progress

The prompt includes existing active STM to avoid duplicates (pre-extraction dedup).

## Files Modified

| File | Changes |
|------|---------|
| `truth_management_system/schema.py` | v12 DDL, `last_accessed_at` in claims DDL |
| `truth_management_system/database.py` | v12 migration, `last_accessed_at` column reconciliation |
| `truth_management_system/config.py` | 12 new STM/compaction config fields |
| `truth_management_system/interface/structured_api.py` | STM CRUD (8 methods) + compaction extension |
| `truth_management_system/interface/conversation_distillation.py` | `ShortTermCandidate`, `_extract_short_term_memories()`, `short_term_candidates` on plan |
| `truth_management_system/search/base.py` | `_claim_age_days` uses max of 3 timestamps |
| `truth_management_system/utils.py` | `expire_stale_claims` also sweeps STM |
| `Conversation.py` | STM injection + `touch_claims_accessed` in `_get_pkb_context` |
| `endpoints/pkb.py` | STM storage with reinforcement detection, 3 REST endpoints, config pass-through |
| `interface/interface.html` | Collapsible STM section in claims pane |
| `interface/pkb-manager.js` | `loadShortTermMemories()`, promote/dismiss handlers, compaction report |
| `truth_management_system/tests/test_short_term_memory.py` | 17 tests covering CRUD, expiry, reinforcement, promotion, compaction |

## Tests

17 dedicated tests in `test_short_term_memory.py`:
- CRUD: add, list, delete, validate importance/ttl, meta_json round-trip
- Expiry: past-due deletion, active preservation
- Reinforcement: increment count, TTL extension, auto-promote at threshold, no promote for medium, manual promote
- Touch: STM `last_accessed_at`, claims `last_accessed_at`
- Compaction: STM expired count in cleanup, stale claim identification, archive on apply
