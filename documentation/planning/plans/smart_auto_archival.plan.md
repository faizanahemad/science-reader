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

## Requirements

### Core Behavior

1. Auto-archive conversations that meet staleness criteria on each `list_conversation_by_user` call
2. Auto-archived conversations behave exactly like manually archived ones (hidden by default, visible with "Show Archived" toggle, unarchivable)
3. Never auto-archive: flagged conversations, conversations with pinned messages
4. User can unarchive any auto-archived conversation (it stays unarchived permanently unless manually re-archived or meets criteria again after fresh activity)

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

**Step 2 — Embedding confirmation (accurate, API call):**
- For BM25 candidates, compute cosine similarity of `title + summary[:200]` embeddings
- If embedding similarity > 0.75 AND the similar conversation has more recent `last_updated` → apply superseded modifier (grace × 0.5)
- Embeddings cached on the Conversation object (reuse existing `openai_embed`)

**Performance considerations:**
- BM25 pre-filter runs on in-memory strings — fast for 66–500 conversations
- Embedding step only runs on BM25 candidates (typically <10% of conversations)
- Embedding results cached — only computed once per conversation title+summary change
- Entire check runs lazily inside `list_conversation_by_user` (already loads all conversations)

### User Preference

- Setting: `auto_archive_grace_days` (default 90, options: 30 / 60 / 90 / 180 / never)
- Stored in: localStorage (frontend) + passed as query param or read from user settings
- "Never" disables auto-archival entirely
- UI: Small dropdown in sidebar toolbar or conversation settings

### `last_opened_at` Tracking

- Set to `datetime.now()` whenever `get_conversation_history/<conversation_id>` is called
- Persisted on the Conversation object (same pattern as other properties)
- Backfill: for existing conversations without `last_opened_at`, use `last_updated` as initial value
- Does NOT trigger `save_local()` on every open (too expensive) — batch-save periodically or on next message

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Trigger location | `list_conversation_by_user` | Already loads all conversations, runs cleanup, natural batch point |
| Similarity approach | Hybrid BM25 → Embedding | BM25 is fast pre-filter; embedding confirms semantic similarity without false positives |
| Embedding similarity threshold | 0.75 | High enough to avoid false supersession, low enough to catch rephrased topics |
| BM25 threshold | 0.4 Jaccard on top terms | Generous pre-filter — let embedding do the precision work |
| Grace period modifiers | Multiplicative | Compose cleanly: short conv (×0.5) + superseded (×0.5) = 90×0.25 = 22 days |
| `last_opened_at` save strategy | Lazy (not immediate save_local) | Avoid disk I/O on every page load; piggyback on next message or periodic flush |
| Unarchive permanence | Stays unarchived until fresh staleness | Prevents annoying re-archival loop; user intent is respected |
| Auto-archive vs auto-delete | Auto-archive | Reversible, non-destructive, uses existing archive infrastructure |

## Tasks

### Task 1: Add `last_opened_at` property to Conversation

- Add `last_opened_at` property (getattr-based, defaults to None → falls back to `last_updated`)
- Add to `get_metadata()` return dict
- Set in `get_conversation_history` endpoint (lazy save — update in-memory, persist on next `save_local`)

**Files:** `Conversation.py`, `endpoints/conversations.py`

### Task 2: BM25 similarity utility

- New file: `utils/text_similarity.py`
- `tokenize(text)` — lowercase, split, remove stopwords (small hardcoded list)
- `jaccard_similarity(tokens_a, tokens_b)` — intersection/union on sets
- `bm25_candidates(target_conv, all_convs, threshold=0.4)` — returns list of similar newer conversations

**Files:** `utils/text_similarity.py` (new)

### Task 3: Embedding similarity check

- Function: `embedding_similarity(conv_a, conv_b)` — cosine similarity of cached embeddings
- Cache embedding of `title + summary[:200]` on conversation (reuse existing embed infrastructure)
- Only called for BM25 candidates

**Files:** `utils/text_similarity.py`

### Task 4: Staleness scoring function

- `compute_staleness(conv, all_conversations, grace_days=90)` → returns `(is_stale: bool, reason: str)`
- Implements the full algorithm: exemption check → message count modifier → superseded check → time comparison
- Pure logic function, no side effects

**Files:** `utils/auto_archival.py` (new)

### Task 5: Wire into `list_conversation_by_user`

- After filtering by domain, before returning: run `compute_staleness` on each non-archived conversation
- Auto-archive those that qualify (set `conv.archived = True`)
- Log auto-archival events for debugging
- Respect user preference (`auto_archive_grace_days` param)

**Files:** `endpoints/conversations.py`

### Task 6: User preference UI

- Dropdown in sidebar settings or toolbar: "Auto-archive after: Never / 30d / 60d / 90d / 180d"
- Store in localStorage, pass as query param to `list_conversation_by_user`
- Default: 90 days

**Files:** `interface/interface.html`, `interface/workspace-manager.js`

### Task 7: Documentation

- Update `chat_app_capabilities.md` with auto-archival behavior
- Update `sidebar_organization_features.plan.md` with cross-reference

**Files:** `documentation/product/behavior/chat_app_capabilities.md`, `documentation/planning/plans/sidebar_organization_features.plan.md`

## Files Modified (estimated)

| File | Purpose |
|------|---------|
| `Conversation.py` | `last_opened_at` property |
| `endpoints/conversations.py` | Set `last_opened_at`, run auto-archival in list endpoint |
| `utils/text_similarity.py` | New: BM25 tokenize, Jaccard, embedding cosine |
| `utils/auto_archival.py` | New: staleness scoring, superseded detection |
| `interface/interface.html` | Grace period dropdown |
| `interface/workspace-manager.js` | Pass grace param, UI control |
| Documentation | Capabilities + plan cross-ref |

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| False positive archival (important conv archived) | Exempt flagged + pinned; embedding threshold conservative (0.75); user can unarchive |
| Performance on large conversation sets | BM25 pre-filter limits embedding calls; lazy evaluation; runs only on page load |
| Embedding API cost | Only for BM25 candidates (<10%); cache results; skip if no API key |
| `last_opened_at` disk I/O | Lazy save strategy — don't persist every open, batch with next message |
| Superseded false match (e.g., "Meeting Notes Jan" vs "Meeting Notes Feb") | High embedding threshold (0.75) + must be genuinely newer with activity |
