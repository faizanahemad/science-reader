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

## Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Mass archival on first deploy | Max 5/load + toast with undo | Prevents panic; gradual discovery |
| 2 | `last_opened_at` is None initially | Treat as "opened today" | Conservative — innocent until proven stale |
| 3 | Embedding API failure | Skip superseded, use time-only | Superseded is bonus signal, not requirement |
| 4 | Re-archival after unarchive | `auto_archive_exempt` flag + last_opened_at updates on every access | Respects user intent; opening updates clock |
| 5 | Superseded false positives | Multiplicative grace reduction only; opened_at updated on access protects active convs | Self-correcting — if user opens it, it's no longer stale |
| 6 | Performance at scale | Time pre-filter + cap 50 candidates + cache BM25/embeddings in DB | Next load handles remainder |
| 7 | Batch save cost | Async save_local() calls in background thread | Non-blocking |
| 8 | Scope | Global: one setting for all domains | Less cognitive load |
| 9 | Visual indicator | Separate sub-section: "Auto-archived (15)" vs "Archived (3)" | Clear distinction |
| 10 | Notification | Toast + undo button | Builds trust |
| 11 | Setting storage | User settings in DB (server-side) | Consistent across devices |
| 12 | Superseded scope | Across all workspaces in domain | Users reorganize; topic != folder |
| 13 | Disable behavior | Previously archived stay archived | Least surprising |
| 14 | Throttle | Once per hour | Sufficient granularity |
| 15 | Embedding model | Reuse `get_embedding_model(keys)` + existing cached embeddings | Avoid extra API calls |

## Tasks

### Task 1: Add `last_opened_at` property to Conversation

- Add `last_opened_at` property (getattr-based, defaults to None)
- Add to `get_metadata()` return dict (fallback: `last_updated` if None)
- Set to `datetime.now()` in `get_conversation_history` endpoint
- Call `save_local()` after setting (every open counts)

**Files:** `Conversation.py`, `endpoints/conversations.py`

### Task 2: Add `auto_archive_exempt` property to Conversation

- Add `auto_archive_exempt` property (getattr-based, defaults False)
- Set to `True` when user manually unarchives an auto-archived conversation
- Add to `get_metadata()` return dict

**Files:** `Conversation.py`, `endpoints/conversations.py`

### Task 3: Similarity cache table in DB

- New table: `ConversationSimilarityCache` with columns: `conversation_id`, `title_summary_hash`, `bm25_tokens` (JSON), `embedding` (BLOB), `updated_at`
- Only recompute when title+summary hash changes
- CRUD helpers

**Files:** `database/connection.py`, `database/similarity_cache.py` (new)

### Task 4: BM25 similarity utility

- `tokenize(text)` — lowercase, split, remove stopwords
- `jaccard_similarity(tokens_a, tokens_b)` — intersection/union on sets
- `bm25_candidates(target_conv, all_convs, threshold=0.4)` — returns list of similar newer conversations
- Uses cached tokens from DB

**Files:** `utils/text_similarity.py` (new)

### Task 5: Embedding similarity check

- `embedding_similarity(conv_a, conv_b)` — cosine similarity
- Check conversation object for existing embedding first
- Fall back to cached embedding in DB
- Only call API if missing; cache result
- Graceful failure: return None if API fails

**Files:** `utils/text_similarity.py`

### Task 6: Staleness scoring function

- `compute_staleness(conv, all_conversations, grace_days=90)` → `(is_stale: bool, reason: str)`
- Full algorithm: exemption → message count modifier → superseded check → time comparison
- Pure logic, no side effects except reading cache

**Files:** `utils/auto_archival.py` (new)

### Task 7: Wire into `list_conversation_by_user`

- Throttle: check `last_auto_archive_run` (in-memory timestamp), skip if < 1 hour ago
- Time pre-filter: only score conversations with `staleness_clock_age > grace/2`
- Cap: max 50 candidates for similarity, max 5 archives per run
- Async `save_local()` for archived conversations
- Log auto-archival events

**Files:** `endpoints/conversations.py`

### Task 8: Toast notification + undo

- Return `auto_archived_ids` in `list_conversation_by_user` response
- Frontend shows toast: "N conversations auto-archived" + "Undo" button
- Undo calls `POST /archive_conversation/<id>` for each (toggles back)

**Files:** `interface/workspace-manager.js`, `endpoints/conversations.py`

### Task 9: Archived sub-sections (Auto-archived vs Manually archived)

- Split `#archived-conversations-section` into two sub-groups
- Track `archive_source: "auto" | "manual" | null` on Conversation
- Render separately when "Show Archived" active

**Files:** `Conversation.py`, `interface/workspace-manager.js`

### Task 10: User preference (grace period setting)

- Add `auto_archive_grace_days` to user settings (DB-backed)
- Endpoint to get/set
- Frontend: dropdown in chat-settings-modal
- Pass setting to staleness scorer

**Files:** `database/users.py`, `endpoints/conversations.py`, `interface/interface.html`

### Task 11: Mass archival cleanup button

- Button in chat-settings-modal: "Archive Stale Conversations"
- New endpoint: `POST /auto_archive_all/<domain>` — runs full staleness check, no cap
- Confirmation dialog with count before proceeding
- Returns list of archived conversation IDs

**Files:** `endpoints/conversations.py`, `interface/interface.html`, `interface/common-chat.js`

### Task 12: Documentation

- Update `chat_app_capabilities.md`
- Cross-reference from `sidebar_organization_features.plan.md`

**Files:** documentation

## Files Modified (estimated)

| File | Purpose |
|------|---------|
| `Conversation.py` | `last_opened_at`, `auto_archive_exempt`, `archive_source` properties |
| `endpoints/conversations.py` | Set `last_opened_at` on history load, auto-archival in list endpoint, mass archive endpoint |
| `database/connection.py` | `ConversationSimilarityCache` table |
| `database/similarity_cache.py` | New: cache CRUD for BM25 tokens + embeddings |
| `utils/text_similarity.py` | New: tokenize, Jaccard, embedding cosine |
| `utils/auto_archival.py` | New: staleness scoring, superseded detection, batch logic |
| `interface/workspace-manager.js` | Toast + undo, sub-sections for auto/manual archived |
| `interface/interface.html` | Mass archive button in settings modal |
| `interface/common-chat.js` | Mass archive button handler |
| `database/users.py` | `auto_archive_grace_days` setting |
| Documentation | Capabilities + plan |

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
