# Smart Auto-Archival

**Status: PLANNED** (June 2026)

## Motivation and Background

With 66+ conversations and growing, older conversations clutter the sidebar even with workspace organization. The existing manual archive feature (from `sidebar_organization_features.plan.md`) lets users hide conversations explicitly, but most stale conversations are never manually archived — they just accumulate.

Smart auto-archival automatically archives conversations that are likely no longer relevant, using multiple signals beyond simple time-based expiry. The key insight: a conversation is stale when it hasn't been opened or updated in a while AND no importance signals exist AND (optionally) a newer conversation on the same topic supersedes it.

### Existing Infrastructure

- `Conversation` object with `archived` property, `save_local()` persistence
- `get_metadata()` returns `last_updated`, `flag`, `archived`, `title`, `summary_till_now`
- `/list_conversation_by_user/<domain>` — already runs stateless cleanup, natural place for auto-archival
- `POST /archive_conversation/<id>` — toggle endpoint (manual unarchive still works)
- Pinned messages: `database/pinned_messages.py` — `get_pinned_messages(conversation_id)`
- Embedding infrastructure: `get_embedding_model(keys)`, `openai_embed` on Conversation objects
- `conversation_history` list on Conversation — gives message count

### What's Missing

- `last_opened_at` — no tracking of when a conversation was last viewed (only `last_updated` which requires a message send/edit)
- Similarity computation between conversations
- Auto-archival scoring logic
- User preference for grace period
- Cached BM25 tokens and embeddings for title+summary

## Requirements

### Core Behavior

1. Auto-archive conversations that meet staleness criteria on each `list_conversation_by_user` call (throttled to once per hour)
2. Auto-archived conversations behave exactly like manually archived ones (hidden by default, visible with "Show Archived" toggle, unarchivable)
3. Never auto-archive: flagged conversations, conversations with pinned messages, conversations with `auto_archive_exempt` flag
4. User can unarchive any auto-archived conversation — sets `auto_archive_exempt = True` so it's never auto-archived again
5. Max 5 conversations auto-archived per page load (gradual rollout). Next load processes next batch.
6. Toast notification with "Undo" button on auto-archival
7. "Show Archived" displays auto-archived in a separate sub-section from manually archived

### Staleness Algorithm

```
Base grace period: 90 days (user-configurable: 30/60/90/180/never)

Staleness clock = max(last_updated, last_opened_at)

Message count modifier:
- < 4 messages (≤1 full turn):   grace × 0.5  → 45 days
- 4–40 messages:                  grace × 1.0  → 90 days
- > 40 messages:                  grace × 2.0  → 180 days

Superseded modifier (hybrid similarity check):
- If a newer conversation with similar title+summary exists: grace × 0.5

Exempt (never auto-archive):
- Flagged conversations (any color)
- Conversations with ≥1 pinned message
- Conversations with auto_archive_exempt = True

Final condition:
  stale = staleness_clock_age > adjusted_grace
          AND (last_opened_age > 45 days OR last_updated_age > adjusted_grace)
          AND NOT exempt
```

### Superseded Conversation Detection (Hybrid: BM25 → Embedding)

**Step 1 — BM25 pre-filter (fast, no API calls):**
- For each candidate stale conversation, compute BM25/Jaccard similarity of `title + summary[:200]` against all newer conversations in the same domain
- If similarity > 0.4 → mark as candidate for embedding check
- Uses simple tokenization: lowercase, split on whitespace/punctuation, remove stopwords
- BM25 tokens cached in DB per conversation (recomputed only when title/summary changes)

**Step 2 — Embedding confirmation (accurate, API call):**
- For BM25 candidates, compute cosine similarity of `title + summary[:200]` embeddings
- If embedding similarity > 0.75 AND the similar conversation has more recent `last_updated` → apply superseded modifier (grace × 0.5)
- Embeddings cached in DB per conversation (recomputed only when title/summary changes)
- If embedding already exists on conversation object, reuse it (no API call)
- If API fails, skip superseded check entirely — fall back to time-only logic

**Scope:** Across all workspaces in the domain (topic similarity doesn't depend on folder organization).

**Performance:**
- Time pre-filter: only check conversations where `staleness_clock_age > grace/2` (eliminates most)
- Cap: max 50 candidates per load for similarity checks
- BM25 tokens + embeddings cached in DB — subsequent runs are fast
- Throttle: entire auto-archival runs at most once per hour

### `last_opened_at` Tracking

- Set to `datetime.now()` every time `get_conversation_history/<conversation_id>` is called (every open)
- Persisted on the Conversation object (same pattern as other properties)
- Backfill: for existing conversations without `last_opened_at`, treat as "opened today" on first encounter (conservative — innocent until proven stale)
- Does NOT skip `save_local()` — since opens are less frequent than renders, and this is important for correctness

### User Preference

- Setting: `auto_archive_grace_days` (default 90, options: 30 / 60 / 90 / 180 / never)
- Stored in: user settings in DB (persisted server-side, consistent across devices)
- "Never" disables auto-archival entirely
- Previously auto-archived conversations stay archived when user disables (no mass restore)

### Mass Archival (Manual Cleanup)

- Button in chat-settings-modal: "Archive Stale Conversations"
- Runs the same staleness algorithm but archives ALL qualifying conversations at once (not capped at 5)
- Shows count before confirming: "24 conversations will be archived. Proceed?"
- Useful for first-time cleanup or periodic maintenance
- Separate from the gradual auto-archival on page load

## Questions & Decisions

### Q1: Mass auto-archival on first deployment
40+ old conversations could suddenly disappear on first load.

- (A) ✅ **Max 5 per load + toast with "Undo" button** — gradual, reversible
- (B) Dry-run first (show badge, user confirms)
- (C) Grace period after feature enable (7 days before archiving starts)

### Q2: `last_opened_at` is None for all existing conversations
Old conversations have no open-tracking. Could cause false positives.

- (A) ✅ **Treat as "opened today"** — conservative, innocent until proven stale. Self-corrects after first real open.
- (B) Use `last_updated` as-is (accept some false positives)
- (C) Backfill from file system mtime

### Q3: Embedding API failures / no API key configured
Similarity check can't complete. Does the conversation get archived anyway?

- (A) ✅ **Skip superseded check entirely, fall back to time-only logic** — superseded is a bonus signal, not a requirement
- (B) Cache BM25 result and retry embedding next load
- (C) Never auto-archive "possibly superseded" without confirmed embedding

### Q4: Conversation re-archival loop
User unarchives, next load re-archives it immediately (still old).

- (A) ✅ **`auto_archive_exempt` flag set on unarchive** — plus `last_opened_at` updates on every access (opening a conversation = signal of interest)
- (B) `unarchived_at` timestamp with 30-day cooldown
- (C) Track `archive_source` and only re-archive if source was "manual"

### Q5: Superseded detection false positives
"Workout Split v1" archived because "v2" exists, but user keeps both intentionally.

- (A) ✅ **Multiplicative grace reduction only (×0.5), never archives alone** — plus `last_opened_at` updates on access (if user opens it, staleness clock resets automatically)
- (B) Show user which conversations are considered superseded
- (C) Require both superseded AND unopened >45d

### Q6: Performance on large conversation sets (500+)
BM25 on all pairs at list-time could be slow.

- (A+C) ✅ **Time pre-filter (only check conversations past grace/2) + cap 50 candidates per load** — next load handles remainder. BM25/embeddings cached in DB for fast subsequent runs.
- (B) Background task, not on page load

### Q7: `save_local()` performance on batch archival
10 pickle writes on one page load could be slow.

- (C) ✅ **Async save_local() calls in background thread** — non-blocking, deterministic (no lost state)
- (A) Batch in-memory then save all synchronously
- (B) Lazy save (risk: lost on restart)

### Q8: Auto-archival scope: per-domain or global?
Conversations are domain-scoped. Should settings be too?

- (B) ✅ **Global: one setting for all domains** — less cognitive load
- (A) Per-domain settings

### Q9: Should auto-archived show a visual indicator vs manually archived?
When "Show Archived" is active, can user distinguish auto from manual?

- (C) ✅ **Separate sub-sections: "Auto-archived (15)" vs "Archived (3)"** — clear distinction
- (A) No distinction
- (B) Subtle badge/icon

### Q10: Notification/undo mechanism
How does user know conversations were auto-archived?

- (A) ✅ **Toast notification: "3 conversations auto-archived" with Undo button** — builds trust, prevents surprise
- (B) Toast only (no undo)
- (C) Silent

### Q11: Where does the grace period setting live?
localStorage vs server-side DB.

- (B) ✅ **User settings in DB (server-side)** — consistent across devices
- (A) localStorage only

### Q12: Superseded check: same workspace or across all?
Should "similar newer conversation" only count within the same workspace folder?

- (B) ✅ **Across all workspaces in the domain** — users reorganize, topic similarity doesn't depend on folder
- (A) Same workspace only
- (C) All workspaces, weight same-workspace higher

### Q13: What happens when user disables auto-archival (sets "never")?
Should previously auto-archived conversations be restored?

- (A) ✅ **Previously archived stay archived** — least surprising. User opted out of future archival, not requesting mass restore.
- (B) Bulk unarchive all auto-archived
- (C) One-time prompt to restore

### Q14: Should auto-archival run on every list call or throttled?
Endpoint called on every page load and sidebar refresh.

- (A) ✅ **Throttle: once per hour** (in-memory timestamp) — sufficient granularity, conversations don't become stale in minutes
- (B) Every time (with pre-filter making it cheap)
- (C) Once per session

### Q15: Embedding model choice for similarity

- (A+C) ✅ **Reuse `get_embedding_model(keys)` + existing cached embeddings on conversation object** — only call API for missing ones. Cache new results in DB for fast reuse.
- (B) Hardcode cheap model

### Q16: Mass archival as manual option
Gradual 5/load may not clean up fast enough for users who want immediate results.

- ✅ **"Archive Stale Conversations" button in chat-settings-modal** — runs full algorithm with no cap. Shows count + confirmation before proceeding.

### Q17: Caching strategy for BM25 tokens and embeddings
Repeated runs should be fast without recomputing.

- ✅ **DB-backed cache table** (`ConversationSimilarityCache`): stores BM25 tokens (JSON) + embedding (BLOB) + hash of title+summary. Only recompute when hash changes.

## Granular Tasks

### Phase 1: Data Model (no behavior change)

#### Task 1.1: Add `last_opened_at` property to Conversation
- Add property with `getattr(self, "_last_opened_at", None)` + setter with `save_local()`
- Same pattern as `archived` property (after it, ~line 310)

**File:** `Conversation.py`

#### Task 1.2: Add `last_opened_at` to `get_metadata()`
- Return `last_opened_at` in metadata dict
- Fallback: if None, use `last_updated` value

**File:** `Conversation.py`

#### Task 1.3: Set `last_opened_at` in `get_conversation_history` endpoint
- After loading conversation, set `conversation.last_opened_at = datetime.now()`
- This triggers `save_local()` via the setter

**File:** `endpoints/conversations.py`

#### Task 1.4: Add `auto_archive_exempt` property to Conversation
- `getattr(self, "_auto_archive_exempt", False)` + setter with `save_local()`
- Add to `get_metadata()` return dict

**File:** `Conversation.py`

#### Task 1.5: Add `archive_source` property to Conversation
- `getattr(self, "_archive_source", None)` — values: `"auto"`, `"manual"`, `None`
- Setter (no `save_local` — set alongside `archived` which already saves)
- Add to `get_metadata()` return dict

**File:** `Conversation.py`

#### Task 1.6: Update `archive_conversation` endpoint to set source + exempt
- When toggling archive ON: set `archive_source = "manual"`
- When toggling archive OFF (unarchive): if `archive_source == "auto"`, set `auto_archive_exempt = True`

**File:** `endpoints/conversations.py`

#### Task 1.7: Verify syntax + commit Phase 1

---

### Phase 2: Similarity Cache (DB + utilities)

#### Task 2.1: Add `ConversationSimilarityCache` table to `connection.py`
- Columns: `conversation_id TEXT PRIMARY KEY`, `title_summary_hash TEXT`, `bm25_tokens TEXT` (JSON), `embedding BLOB`, `updated_at TEXT`
- `CREATE TABLE IF NOT EXISTS` in `create_tables()`

**File:** `database/connection.py`

#### Task 2.2: Create `database/similarity_cache.py` CRUD
- `get_cached(conversation_id)` → dict or None
- `upsert_cache(conversation_id, title_summary_hash, bm25_tokens, embedding)` 
- `get_all_cached(conversation_ids)` → dict mapping id → cache entry

**File:** `database/similarity_cache.py` (new)

#### Task 2.3: Create `utils/text_similarity.py` — tokenizer + Jaccard
- `STOPWORDS` — small hardcoded set (~50 common English words)
- `tokenize(text: str) -> list[str]` — lowercase, split on non-alphanumeric, remove stopwords, dedupe
- `jaccard_similarity(tokens_a: list, tokens_b: list) -> float` — |intersection| / |union|

**File:** `utils/text_similarity.py` (new)

#### Task 2.4: Add `embedding_cosine_similarity` to `utils/text_similarity.py`
- `embedding_cosine_similarity(emb_a, emb_b) -> float` — numpy dot product / norms
- Handle None inputs gracefully (return 0.0)

**File:** `utils/text_similarity.py`

#### Task 2.5: Add `compute_title_summary_hash` helper
- `hashlib.md5((title + summary[:200]).encode()).hexdigest()`
- Used to detect when cache is stale

**File:** `utils/text_similarity.py`

#### Task 2.6: Verify syntax + commit Phase 2

---

### Phase 3: Staleness Scoring (pure logic)

#### Task 3.1: Create `utils/auto_archival.py` — exemption check
- `is_exempt(conv, pinned_message_ids: set) -> bool`
- True if: flagged, has pinned messages, or `auto_archive_exempt == True`

**File:** `utils/auto_archival.py` (new)

#### Task 3.2: Add message count grace modifier
- `message_count_modifier(conv) -> float`
- `< 4` → 0.5, `4–40` → 1.0, `> 40` → 2.0

**File:** `utils/auto_archival.py`

#### Task 3.3: Add superseded detection function
- `find_superseding_conversation(conv, all_convs, cache_map, embed_fn) -> bool`
- BM25 pre-filter (Jaccard > 0.4 against newer conversations)
- Embedding confirmation (cosine > 0.75) for BM25 hits
- Returns True if a newer similar conversation exists
- Graceful: returns False if embedding unavailable

**File:** `utils/auto_archival.py`

#### Task 3.4: Add main `compute_staleness` function
- `compute_staleness(conv, all_convs, grace_days, cache_map, pinned_ids, embed_fn) -> (bool, str)`
- Orchestrates: exempt check → time pre-filter → message modifier → superseded modifier → final time comparison
- Returns `(is_stale, reason_string)`

**File:** `utils/auto_archival.py`

#### Task 3.5: Verify syntax + commit Phase 3

---

### Phase 4: Wire auto-archival into backend

#### Task 4.1: Add throttle tracking to conversation list endpoint
- Module-level `_last_auto_archive_run: float = 0`
- Skip auto-archival if `time.time() - _last_auto_archive_run < 3600`

**File:** `endpoints/conversations.py`

#### Task 4.2: Add auto-archival pass in `list_conversation_by_user`
- After domain filter, before return:
  - If throttle allows AND grace != "never":
    - Pre-filter candidates (staleness_clock_age > grace/2, not archived, not exempt)
    - Cap at 50 candidates
    - Run `compute_staleness` on each
    - Archive top 5 stale (set `archived=True`, `archive_source="auto"`)
    - Async `save_local()` in background threads
    - Update throttle timestamp
- Add `auto_archived_ids` to response JSON

**File:** `endpoints/conversations.py`

#### Task 4.3: Fetch pinned message conversation IDs for batch exempt check
- Query `PinnedMessages` table grouped by `conversation_id` to get set of conv IDs with pins
- Pass to `compute_staleness`

**File:** `endpoints/conversations.py`

#### Task 4.4: Populate/update similarity cache during archival pass
- For each candidate: compute title_summary_hash, check cache
- If cache miss or stale hash: compute BM25 tokens, store in DB
- If embedding needed and missing: call API, store in DB
- Use `get_embedding_model(keys)` for new embeddings

**File:** `endpoints/conversations.py`

#### Task 4.5: Verify syntax + commit Phase 4

---

### Phase 5: Frontend — toast, undo, sub-sections

#### Task 5.1: Handle `auto_archived_ids` in response
- In `loadConversationsWithWorkspaces` AJAX success: check for `auto_archived_ids`
- If present and non-empty: show toast "N conversations auto-archived" with Undo button

**File:** `interface/workspace-manager.js`

#### Task 5.2: Undo handler
- "Undo" button fires `POST /archive_conversation/<id>` for each auto-archived ID
- On success: reload conversations

**File:** `interface/workspace-manager.js`

#### Task 5.3: Split archived section into two sub-groups
- In `renderArchivedConversations()`: separate conversations by `archive_source`
- Render "Auto-archived (N)" header + list, then "Archived (N)" header + list
- Only show sub-headers when both groups have items

**File:** `interface/workspace-manager.js`

#### Task 5.4: Verify syntax + commit Phase 5

---

### Phase 6: User preference + mass archival

#### Task 6.1: Add `auto_archive_grace_days` column to UserDetails table
- `ALTER TABLE UserDetails ADD COLUMN auto_archive_grace_days INTEGER DEFAULT 90`
- In `create_tables()` (idempotent migration pattern)

**File:** `database/connection.py`

#### Task 6.2: Add get/set endpoints for user setting
- `GET /get_user_setting/<key>` (or reuse existing settings endpoint)
- `POST /set_user_setting/<key>` with JSON body `{ "value": 90 }`
- Specific to `auto_archive_grace_days` for now

**File:** `endpoints/conversations.py` or existing settings endpoint

#### Task 6.3: Read grace setting in auto-archival pass
- Fetch user's `auto_archive_grace_days` before running staleness check
- If "never" (value 0): skip entire pass

**File:** `endpoints/conversations.py`

#### Task 6.4: Add dropdown to chat-settings-modal
- "Auto-archive after: Never / 30d / 60d / 90d / 180d"
- On change: call set endpoint
- Load current value on modal open

**File:** `interface/interface.html`, `interface/common-chat.js`

#### Task 6.5: Add "Archive Stale Conversations" button to settings modal
- Button below the dropdown
- Calls `POST /auto_archive_all/<domain>` endpoint

**File:** `interface/interface.html`, `interface/common-chat.js`

#### Task 6.6: Add `POST /auto_archive_all/<domain>` endpoint
- Runs same staleness logic but no cap (archives all qualifying)
- Returns `{ count: N, archived_ids: [...] }`
- Frontend shows confirmation before calling, then success toast

**File:** `endpoints/conversations.py`

#### Task 6.7: Verify syntax + commit Phase 6

---

### Phase 7: Documentation

#### Task 7.1: Update `chat_app_capabilities.md`
- Add auto-archival behavior to sidebar section
- Add new endpoints to API section

**File:** `documentation/product/behavior/chat_app_capabilities.md`

#### Task 7.2: Cross-reference from `sidebar_organization_features.plan.md`
- Add note pointing to this plan

**File:** `documentation/planning/plans/sidebar_organization_features.plan.md`

#### Task 7.3: Commit docs

---

## Files Modified (estimated)

| File | Purpose |
|------|---------|
| `Conversation.py` | `last_opened_at`, `auto_archive_exempt`, `archive_source` properties |
| `endpoints/conversations.py` | Set `last_opened_at`, auto-archival pass, mass archive endpoint, user setting |
| `database/connection.py` | `ConversationSimilarityCache` table + `auto_archive_grace_days` column |
| `database/similarity_cache.py` | New: cache CRUD for BM25 tokens + embeddings |
| `utils/text_similarity.py` | New: tokenize, Jaccard, embedding cosine, hash |
| `utils/auto_archival.py` | New: exemption, modifiers, superseded detection, staleness scoring |
| `interface/workspace-manager.js` | Toast + undo, archived sub-sections |
| `interface/interface.html` | Grace period dropdown + mass archive button in settings |
| `interface/common-chat.js` | Settings handlers |
| Documentation | Capabilities + plan cross-ref |

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| False positive archival | Exempt flagged + pinned + exempt flag; max 5/load; toast + undo |
| Performance on large sets | Time pre-filter + cap 50 + cached BM25/embeddings in DB + once/hour throttle |
| Embedding API cost | Reuse existing embeddings; cache in DB; skip on failure |
| `last_opened_at` backfill | Treat None as "today"; self-corrects after first real open |
| Re-archival loop | `auto_archive_exempt` flag on unarchive; last_opened_at updates on every access |
| Superseded false match | High embedding threshold (0.75) + must be genuinely unopened >45d |
| Mass archival panic | Gradual (5/load) + toast + undo + separate manual "Archive Stale" button for bulk |
| Server restart loses in-memory throttle | Acceptable — runs again on next load, max 5 archives is safe |
| DB table migration | `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN` pattern — auto-migrates |
