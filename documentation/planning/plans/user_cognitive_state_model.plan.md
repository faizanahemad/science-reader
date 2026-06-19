# User Cognitive State Model (UCSM) — Design Document

## Motivation & Background

The PKB stores *what the system knows about the user* — facts, preferences, decisions. But it doesn't track *what the user knows* — which topics were explained in depth, what the user actually read and engaged with, and where knowledge gaps might exist.

**Core problem:** When a user discusses a concept in detail in one conversation and returns days later with a quick question about it, the system re-explains from scratch. Conversely, if the system gave a long explanation but the user scrolled past it, the system incorrectly assumes comprehension.

**Solution:** A separate system — the User Cognitive State Model (UCSM) — that tracks:
1. Topic depth: what was discussed, at what level, across which conversations
2. Engagement signals: what the user actually interacted with (viewport time, scrolls, selections, doubts, pins)
3. Retention inference: combining depth + engagement into an "absorption score" per topic

**Key design principle:** UCSM is separate from PKB. PKB is high-precision, high-recall, short factual claims with human curation. UCSM is lower-precision, unsupervised, unstructured, any-length observations with no expected human intervention in collection. Users can inspect and edit but are not expected to curate.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        UCSM System                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐   ┌──────────────────┐   ┌───────────────────┐  │
│  │ Topic Depth  │   │ Engagement       │   │ Retention         │  │
│  │ Extractor    │   │ Tracker          │   │ Inference Engine  │  │
│  │ (LLM-based)  │   │ (Client signals) │   │ (Scoring logic)   │  │
│  └──────┬───────┘   └────────┬─────────┘   └────────┬──────────┘  │
│         │                    │                       │              │
│         ▼                    ▼                       ▼              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              ucsm.db (SQLite, per-user)                     │   │
│  │  Tables: topics, topic_history, engagement_signals,         │   │
│  │          topic_embeddings, topic_fts                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Prompt Injection Layer                          │   │
│  │  Retrieved at response time → injected into PKB distillation│   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

Integration points:
- Extraction: hooks into persist_current_turn (after every turn)
- Engagement: POST /ucsm/engagement from frontend IntersectionObserver + interaction events
- Prompt injection: _get_pkb_context distillation step reads UCSM topics
- UI inspection: new "Knowledge Map" tab in PKB modal
- Deletion cascade: conversation delete → remove UCSM records for that conversation
```

---

## Separation from PKB

| Aspect | PKB | UCSM |
|--------|-----|------|
| Purpose | What the system knows about the user | What the user knows/has absorbed |
| Precision | High — curated, correctable | Lower — inferred, probabilistic |
| Human intervention | Expected (approve, edit, retract) | Not expected (inspect-only) |
| Data shape | Short factual claims (1-2 sentences) | Unstructured topics of any length |
| Storage | `truth_management_system/` SQLite | Separate `ucsm.db` SQLite |
| Extraction | Per-turn with user confirmation modal | Per-turn, fully unsupervised |
| Provenance | Detailed (channel, derivation, confidence) | Lightweight (conversation_id, turn_range) |
| Indexing | Embeddings + FTS5 + entity links | Embeddings + FTS5 (simpler) |
| API surface | REST + NL agent + slash commands | REST + inspection UI (no NL agent) |
| Decay | No decay (permanent unless retracted) | 30-day half-life, decays without reinforcement |


---

## Decisions Log

### Design Questions & Answers

**Q1. Visibility to user?**
- Decision: **B — Visible.** User can see a "knowledge map" of what the system thinks they know. Implemented as a tab in the PKB modal.

**Q2. How does this affect responses?**
- Decision: **A + reference.** Give full answer but shorter (no background, just the specific answer), plus a link/reference to the old conversation. Note: answer length is mostly controlled by prompting — this system provides signals, the LLM decides verbosity.

**Q3. Primary goal?**
- Decision: **Improve UX** — less repetitive, more targeted responses. Not primarily about cost/speed.

**Q4. What does "pointing back" look like?**
- Decision: **A — Clickable link that opens in a modal first.** Shows the referenced content. Only switches to that conversation if user clicks a "Go to conversation" button on the modal. This is a new UI pattern (no "Go to conversation" button exists today — closest is cross-conv search which just switches directly).

**Q5. Track user's own explanations or only assistant's?**
- Decision: **C — Track both, weight differently.** Assistant explanations = knowledge the user was taught. User's own detailed descriptions = context they already possess but might want refreshed (lower weight as "needs re-explanation").

**Q6. What's the unit of a "topic"?**
- Decision: **A — Free-form text labels extracted by LLM.** Not tied to PKB entities or claims. Examples: "5/3/1 workout progression", "React useEffect cleanup", "Kubernetes pod scheduling". LLM extracts topic labels during summarization.

**Q7. Survive conversation deletion?**
- Decision: **B — No.** If the source conversation is deleted, remove the UCSM signals from that conversation. The delete API cascades to UCSM storage. If a topic was reinforced across multiple conversations, only the signals from the deleted conversation are removed (topic may still exist from other sources).

**Q8. How many depth levels?**
- Decision: **D — Categorical with multiple axes:**
  - `explained_to_user` — assistant gave a detailed explanation
  - `user_demonstrated_understanding` — user asked informed follow-ups, explained it themselves, or applied it
  - `mentioned_in_passing` — topic came up briefly without elaboration
  - `user_asked_about_but_moved_on` — user showed interest but didn't engage deeply

**Q9. Who decides depth level?**
- Decision: **A + heuristics.** Modify existing `persist_current_turn_prompt` to annotate topics (free — runs every turn). Additionally, heuristic signals contribute: doubts asked on a message boost engagement, natural scrolling (non-programmatic) on a message counts, follow-up questions later in conversation indicate retention.

**Q10. Does depth accumulate across conversations?**
- Decision: **D — Track full history.** Store per-conversation depth entries. The system sees that user encountered topic X at multiple depths over time (e.g., mentioned briefly June 1, explained in detail June 5, user demonstrated understanding June 10). Most recent + maximum depth both inform the absorption score.

**Q11. Does knowledge decay?**
- Decision: **A + C combined.** Active decay — after N days without engagement, downgrade depth level. But soft: older knowledge gets a "may need refresh" flag rather than being deleted entirely.

**Q12. Decay half-life?**
- Decision: **B — 30 days.** Topics not reinforced within 30 days start getting "may need refresh" treatment. Reinforcement resets the clock.

**Q13. Can user explicitly reset knowledge state?**
- Decision: **A + C + D.** Three mechanisms:
  1. Explicit detection: if user says "I forgot about X" or "explain X again from scratch", detect intent and reset depth
  2. Implicit: if user asks for a full explanation (phrasing suggests unfamiliarity), model judges from query and gives full treatment regardless of stored depth
  3. Both work together — explicit resets the stored state, implicit overrides it at response time

**Q14. Build engagement tracking now or defer?**
- Decision: **A — Build alongside Phase 1.** Both topic depth extraction and engagement signal collection ship together.

**Q15. Creepiness — surface tracking to user?**
- Decision: **C — Show in PKB knowledge map as "confidence: high/medium/low" without explaining why.** Never say "I noticed you didn't read that." The confidence level is visible but the raw signals (viewport time, scroll events) are not shown.
- **Additional decision:** This system needs a **separate DB and storage design** from PKB. PKB is high-precision, high-recall short facts. UCSM is lower-precision, lower-recall, LLM-detected, completely unsupervised, any-length observations.

**Q16. Text selection/copy signal handling?**
- Decision: **C — Weight by content type.** Prose copy/selection = very engaged (actively extracting meaning). Code block copy = usage signal, not learning signal (lower weight). Differentiate via DOM context (is parent `.code-block` or prose `.card-text`?).

**Q17. Where does "user knows X" live in the prompt?**
- Decision: **A + D — PKB distillation step.** The existing distillation LLM call (line 9972 in Conversation.py) that converts raw PKB claims into behavioral instructions is extended to also consume UCSM topic data. But UCSM uses its own separate database, tables, embeddings, and FTS5 indexing — NOT the same PKB database.

**Q18. Instruction to model when user "knows" something?**
- Decision: **C + D combined.** "Give a concise answer and reference the prior conversation" + "Don't repeat explanations already given — assume familiarity." The prompt instruction should convey both: be concise AND point back.

**Q19. How aggressive when model might be wrong?**
- Decision: **C — Tiered.**
  - `explained_to_user` + high engagement = bare minimum answer + pointer
  - `explained_to_user` + moderate engagement = concise answer with enough context to stand alone + pointer
  - `mentioned_in_passing` or low engagement = full treatment (no assumption of retention)

**Q20. Where does topic depth data live?**
- Decision: **C — Separate `topic_knowledge` table(s) in a dedicated `ucsm.db`.** Decoupled from PKB entirely. Own embedding table, own FTS5 index, own API surface.

**Q21. Where do engagement signals live?**
- Decision: **C — Separate `engagement.db`.** Keeps analytics separate from both PKB and UCSM core topic data. Raw signals aggregated here, then consumed by UCSM inference engine.

---

### Assumptions & Confirmations

**A1. Single-user system?**
- Answer: **No.** Must support multi-user like the rest of the system. All tables keyed by `user_email`. Per-user isolation in all queries and cascades.

**A2. UCSM piggybacks on existing PKB extraction pipeline?**
- Answer: **No.** Data design and extraction for UCSM are different from PKB. UCSM expects much more unstructured data with zero human intervention in collection or provenance. It's a parallel pipeline with its own extractor, prompts, and storage — not an extension of `conversation_distillation.py`. We will build inspection/edit support, but user is not expected to correct what the system stores.

**A3. "Concise + pointer" is the safe default — never withhold information?**
- Answer: **Yes.** Always provide enough to answer the question. Brevity should feel like efficiency, not dismissal. Always offer elaboration path.

**A4. Behavior when auto_pkb_extract is OFF?**
- Answer: **C — Silently enable UCSM tracking regardless.** UCSM is not "memory" in the PKB sense — it's a behavioral optimization signal. It runs independently of the PKB auto-extract toggle. User can disable UCSM separately if we add that toggle later.

**A5. Pointer degrades gracefully when conversation is deleted?**
- Answer: **Yes.** If source conversation is deleted, the cascade removes UCSM records tied to it. If the topic was reinforced from other conversations, those remain. The pointer falls back to "previously discussed" without a link. The delete endpoint hooks into UCSM cleanup.

**A6. Phase 1 works without Phase 2?**
- Answer: **No — build both together.** Topic depth extraction and engagement signal collection are implemented simultaneously. They're separate subsystems but ship as one feature.

**A7. No new UI for Phase 1?**
- Answer: **Mostly yes, but inspection needed.** The core behavior change is invisible (smarter responses). But a "Knowledge Map" tab in the PKB modal provides inspection capability — shows topics, depth levels, confidence, and recency. Users can see what the system thinks they know.


---

## Data Model & Storage

### Database Layout

Two separate SQLite databases per user, stored in `storage/ucsm/{user_email}/`:

```
storage/ucsm/{user_email}/
├── ucsm.db          — topics, depth history, retention scores, embeddings, FTS5
└── engagement.db    — raw engagement signals (high-write, aggregated periodically)
```

### ucsm.db Schema

```sql
-- Core topic records
CREATE TABLE IF NOT EXISTS topics (
    topic_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    topic_label TEXT NOT NULL,           -- free-form LLM-extracted label
    canonical_label TEXT,                 -- normalized canonical form (for dedup)
    aliases TEXT,                         -- JSON array of variant labels seen
    current_depth TEXT NOT NULL,          -- explained_to_user|user_demonstrated_understanding|mentioned_in_passing|user_asked_about_but_moved_on
    absorption_score REAL DEFAULT 0.0,   -- 0.0-1.0, computed from depth + engagement
    first_seen_at TEXT NOT NULL,          -- ISO 8601
    last_reinforced_at TEXT NOT NULL,     -- ISO 8601, reset on any reinforcement
    last_decayed_at TEXT,                 -- last time decay was applied
    reinforcement_count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',        -- active|decayed|reset
    meta_json TEXT,                       -- extensible: related_topic_ids, etc.
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_topics_user ON topics(user_email);
CREATE INDEX idx_topics_label ON topics(user_email, topic_label);
CREATE INDEX idx_topics_score ON topics(user_email, absorption_score DESC);

-- Per-conversation depth entries (history tracking, decision Q10=D)
CREATE TABLE IF NOT EXISTS topic_history (
    history_id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    user_email TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    depth_level TEXT NOT NULL,            -- same enum as topics.current_depth
    confidence_in_depth REAL DEFAULT 0.8, -- 0.0-1.0, lower when signals conflict
    turn_range_start INTEGER,            -- message index where topic discussion began
    turn_range_end INTEGER,              -- message index where it ended
    message_ids TEXT,                     -- JSON array of stable message UUIDs
    message_count INTEGER,               -- how many messages covered this topic
    key_points TEXT,                      -- distilled bullet summary of what was discussed
    source_signals TEXT,                  -- JSON: what contributed to this depth classification
    created_at TEXT NOT NULL
);
CREATE INDEX idx_history_topic ON topic_history(topic_id);
CREATE INDEX idx_history_conversation ON topic_history(conversation_id);
CREATE INDEX idx_history_user ON topic_history(user_email);

-- Embedding index for semantic retrieval
CREATE TABLE IF NOT EXISTS topic_embeddings (
    topic_id TEXT PRIMARY KEY REFERENCES topics(topic_id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,             -- float32 array, same model as PKB embeddings
    model_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- FTS5 for keyword search
CREATE VIRTUAL TABLE IF NOT EXISTS topics_fts USING fts5(
    topic_id UNINDEXED,
    user_email UNINDEXED,
    topic_label,
    content='topics',
    content_rowid='rowid'
);

-- Schema versioning for migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

### engagement.db Schema

```sql
-- Per-message engagement signals (batched from frontend)
CREATE TABLE IF NOT EXISTS message_engagement (
    engagement_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    message_index INTEGER NOT NULL,
    message_id TEXT,
    signal_type TEXT NOT NULL,           -- viewport|manual_scroll|doubt_asked|pinned|text_selected|text_copied|follow_up_asked
    duration_ms INTEGER,                 -- for viewport signals
    content_type TEXT,                   -- prose|code|mixed (for selection/copy weighting)
    word_count INTEGER,                  -- of the message (for viewport threshold scaling)
    created_at TEXT NOT NULL
);
CREATE INDEX idx_engagement_conv ON message_engagement(conversation_id);
CREATE INDEX idx_engagement_user ON message_engagement(user_email);
CREATE INDEX idx_engagement_message ON message_engagement(conversation_id, message_index);

-- Aggregated engagement per message (computed periodically or on conversation switch)
CREATE TABLE IF NOT EXISTS message_engagement_summary (
    user_email TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    message_index INTEGER NOT NULL,
    primary_topic_id TEXT,               -- attributed topic (may be NULL if unattributed)
    total_viewport_ms INTEGER DEFAULT 0,
    manual_scroll_count INTEGER DEFAULT 0,
    doubt_asked INTEGER DEFAULT 0,       -- boolean 0/1
    pinned INTEGER DEFAULT 0,            -- boolean 0/1
    text_selected INTEGER DEFAULT 0,     -- boolean 0/1
    text_copied INTEGER DEFAULT 0,       -- boolean 0/1
    prose_selected INTEGER DEFAULT 0,    -- boolean 0/1
    code_copied INTEGER DEFAULT 0,       -- boolean 0/1
    follow_up_asked INTEGER DEFAULT 0,   -- boolean 0/1
    engagement_score REAL DEFAULT 0.0,   -- weighted composite 0.0-1.0
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_email, conversation_id, message_index)
);
CREATE INDEX idx_summary_conv ON message_engagement_summary(conversation_id);
CREATE INDEX idx_summary_topic ON message_engagement_summary(primary_topic_id);

-- Schema versioning for migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

### Engagement Score Computation

```python
def compute_engagement_score(summary: dict, word_count: int) -> float:
    """Weighted composite of engagement signals. Returns 0.0-1.0."""
    viewport_threshold_ms = max(3000, word_count * 50)  # scales with message length
    viewport_ratio = min(1.0, summary['total_viewport_ms'] / viewport_threshold_ms)
    
    weights = {
        'viewport': 0.25,          # saw it long enough
        'manual_scroll': 0.15,     # came back to it
        'doubt_asked': 0.25,       # actively questioned it
        'pinned': 0.10,            # saved it (but may not have read)
        'prose_selected': 0.15,    # engaged specific text
        'code_copied': 0.05,       # usage, not learning
        'follow_up_asked': 0.20,   # asked about it later
    }
    
    score = (
        weights['viewport'] * viewport_ratio +
        weights['manual_scroll'] * min(1.0, summary['manual_scroll_count'] / 2) +
        weights['doubt_asked'] * summary['doubt_asked'] +
        weights['pinned'] * summary['pinned'] +
        weights['prose_selected'] * summary['prose_selected'] +
        weights['code_copied'] * summary['code_copied'] * 0.3 +  # downweighted
        weights['follow_up_asked'] * summary['follow_up_asked']
    )
    return min(1.0, score / sum(weights.values()))
```

### Absorption Score (Topic-Level)

```python
def compute_absorption_score(topic: dict, engagement_scores: list, now: datetime) -> float:
    """Combines topic depth + engagement signals + decay."""
    depth_weights = {
        'user_demonstrated_understanding': 1.0,
        'explained_to_user': 0.7,
        'user_asked_about_but_moved_on': 0.3,
        'mentioned_in_passing': 0.1,
    }
    
    depth_score = depth_weights.get(topic['current_depth'], 0.1)
    avg_engagement = sum(engagement_scores) / len(engagement_scores) if engagement_scores else 0.0
    
    # Decay: 30-day half-life
    days_since_reinforced = (now - topic['last_reinforced_at']).days
    decay_factor = 0.5 ** (days_since_reinforced / 30.0)
    
    # Reinforcement bonus (diminishing returns)
    reinforcement_bonus = min(0.2, topic['reinforcement_count'] * 0.05)
    
    raw = (depth_score * 0.5) + (avg_engagement * 0.3) + reinforcement_bonus
    return min(1.0, raw * decay_factor)
```

### Absorption Score Interpretation at Prompt Time

| Score Range | Interpretation | Response Behavior |
|-------------|---------------|-------------------|
| 0.8 - 1.0 | User deeply knows this | Bare minimum answer + pointer to old conversation |
| 0.5 - 0.79 | User likely remembers | Concise answer with enough context to stand alone + pointer |
| 0.2 - 0.49 | Uncertain retention | Full answer, mention it was discussed before |
| 0.0 - 0.19 | Effectively unknown | Full treatment, no assumption of prior knowledge |


---

## Extraction Pipeline

### Trigger & Timing

The UCSM extraction hooks into `_persist_current_turn_inner()` (Conversation.py line 4096) — the same point that generates the running summary after every turn. This is free (already runs) and provides full context.

**Trigger flow:**
```
User sends message → assistant responds → persist_current_turn fires →
  ├── Running summary generation (existing)
  ├── Memory pad extraction (existing)
  ├── Per-message metadata (existing)
  └── UCSM topic depth extraction (NEW, parallel)
```

### Modified Summarization Prompt

The `persist_current_turn_prompt` is extended to output an additional XML block:

```xml
<topics_discussed>
[
  {
    "topic": "5/3/1 workout progression",
    "depth": "explained_to_user",
    "signals": ["multi-paragraph explanation", "examples given", "user asked clarifying question"],
    "turn_range": [12, 15]
  },
  {
    "topic": "progressive overload principle",
    "depth": "mentioned_in_passing",
    "signals": ["single sentence reference"],
    "turn_range": [14, 14]
  }
]
</topics_discussed>
```

**Depth classification criteria in prompt:**
- `explained_to_user`: Assistant gave multi-sentence/paragraph explanation, provided examples, broke down steps
- `user_demonstrated_understanding`: User explained it in their own words, applied it correctly, asked advanced follow-ups
- `mentioned_in_passing`: Topic came up in 1-2 sentences without elaboration
- `user_asked_about_but_moved_on`: User asked about it but conversation didn't go deep (maybe they got distracted or changed subject)

### Extraction Class

```python
class UCSMExtractor:
    """Parallel to ConversationDistiller but for topic depth, fully unsupervised."""
    
    def __init__(self, db: UCSMDatabase, keys: dict, config: UCSMConfig = None):
        self.db = db
        self.keys = keys
        self.config = config or UCSMConfig()
    
    def extract_from_turn(
        self,
        conversation_summary: str,
        user_message: str,
        assistant_message: str,
        recent_turns: list,
        conversation_id: str,
        message_index: int,
        user_email: str
    ) -> list[TopicObservation]:
        """Extract topic depth observations from the current turn.
        
        Returns list of observations to store. No user confirmation needed.
        """
        ...
    
    def merge_observation(self, user_email: str, observation: TopicObservation):
        """Merge a new observation into existing topic state.
        
        - If topic exists: update depth (take max or most recent per Q10=D), 
          add history entry, bump reinforcement_count, update last_reinforced_at
        - If new topic: create topic + first history entry + compute embedding
        """
        ...
```

### Topic Matching (Deduplication)

When a new topic label is extracted (e.g., "React useEffect"), we need to determine if it matches an existing topic (e.g., "useEffect hook in React"). Strategy:

1. **FTS5 keyword match** — quick check for exact or near-exact labels
2. **Embedding similarity** — compute embedding of new label, compare against `topic_embeddings`. Threshold: cosine > 0.85 = same topic
3. **If ambiguous (0.7-0.85)**: Create new topic but link as `related_topic_id` in meta_json

No LLM call for dedup — keep it fast since this runs every turn.

### Heuristic Signals (Beyond LLM Classification)

These signals upgrade or downgrade depth classification without an LLM call:

| Signal | Source | Effect |
|--------|--------|--------|
| Doubt asked on explanation message | engagement.db | Upgrades to `user_demonstrated_understanding` |
| Natural scroll back to message | engagement.db | Confirms `explained_to_user` (actually read it) |
| Follow-up question 3+ turns later | Detected in extraction prompt | Upgrades to `user_demonstrated_understanding` |
| User copied prose from explanation | engagement.db | Confirms engagement |
| Viewport < 3s on long message | engagement.db | Downgrades confidence (may not have read) |
| Conversation deleted | Cascade hook | Removes that history entry; may downgrade if only source |

### Integration with Existing Persist Flow

```python
# In Conversation._persist_current_turn_inner(), after summary generation:

# Existing code:
actual_summary = parse_summary(result)
memory["running_summary"].append(actual_summary)

# NEW: UCSM extraction (fire-and-forget, non-blocking)
if state.ucsm_extractor:
    threading.Thread(
        target=state.ucsm_extractor.extract_from_turn,
        args=(actual_summary, query, response, recent_turns,
              self.conversation_id, message_index, self.user_email),
        daemon=True
    ).start()
```

No user confirmation modal. No blocking. Pure background extraction.


---

## Engagement Tracking (Frontend)

### IntersectionObserver Setup

Uses the existing empty `window.messageObservers` array and `cleanupMessageObservers()` infrastructure.

```javascript
// In renderMessages(), after appending each message card:
const observer = new IntersectionObserver(
    (entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target._ucsmViewStart = Date.now();
            } else if (entry.target._ucsmViewStart) {
                const duration = Date.now() - entry.target._ucsmViewStart;
                if (duration > 1000) { // ignore sub-second flashes
                    UCSMTracker.recordViewport(entry.target, duration);
                }
                delete entry.target._ucsmViewStart;
            }
        });
    },
    { root: document.getElementById('chatView'), threshold: 0.5 }
);
observer.observe(messageElement[0]);
window.messageObservers.push(observer);
```

### Signal Collection (UCSMTracker Module)

```javascript
const UCSMTracker = (function() {
    let pendingSignals = [];
    let flushTimer = null;
    
    function record(conversationId, messageIndex, messageId, signalType, extra = {}) {
        pendingSignals.push({
            conversation_id: conversationId,
            message_index: messageIndex,
            message_id: messageId,
            signal_type: signalType,
            timestamp: new Date().toISOString(),
            ...extra
        });
        scheduleFlush();
    }
    
    function scheduleFlush() {
        if (flushTimer) return;
        flushTimer = setTimeout(flush, 30000); // batch every 30s
    }
    
    function flush() {
        if (pendingSignals.length === 0) return;
        const batch = pendingSignals.splice(0);
        flushTimer = null;
        fetch('/ucsm/engagement', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ signals: batch })
        }).catch(() => {
            // Re-queue on failure
            pendingSignals.unshift(...batch);
            scheduleFlush();
        });
    }
    
    // Public API
    return {
        recordViewport: function(el, durationMs) {
            const idx = parseInt(el.querySelector('.card-header').getAttribute('message-index'));
            const msgId = el.querySelector('.card-header').getAttribute('message-id');
            const convId = ChatManager.activeConversationId;
            const wordCount = (el.querySelector('.actual-card-text')?.textContent || '').split(/\s+/).length;
            record(convId, idx, msgId, 'viewport', { duration_ms: durationMs, word_count: wordCount });
        },
        recordManualScroll: function(el) {
            // Only counts if user scrolled UP to this message (not auto-scroll)
            const idx = parseInt(el.querySelector('.card-header').getAttribute('message-index'));
            const msgId = el.querySelector('.card-header').getAttribute('message-id');
            record(ChatManager.activeConversationId, idx, msgId, 'manual_scroll');
        },
        recordTextSelection: function(el, selectedText, isCode) {
            const idx = parseInt(el.querySelector('.card-header').getAttribute('message-index'));
            const msgId = el.querySelector('.card-header').getAttribute('message-id');
            record(ChatManager.activeConversationId, idx, msgId, 'text_selected', {
                content_type: isCode ? 'code' : 'prose',
                char_count: selectedText.length
            });
        },
        recordCopy: function(el, isCode) {
            const idx = parseInt(el.querySelector('.card-header').getAttribute('message-index'));
            const msgId = el.querySelector('.card-header').getAttribute('message-id');
            record(ChatManager.activeConversationId, idx, msgId, 'text_copied', {
                content_type: isCode ? 'code' : 'prose'
            });
        },
        flush: flush,
        init: function() {
            // Flush on conversation switch and page unload
            window.addEventListener('beforeunload', flush);
            $(document).on('click', '.recent-conversation-item', flush);
        }
    };
})();
```

### Event Hooks (Wired Into Existing Patterns)

```javascript
// Text selection — extends existing selectstart/mouseup handler on message cards
messageElement.on('mouseup', function(e) {
    const selection = window.getSelection();
    if (selection && selection.toString().trim().length > 10) {
        const isCode = !!$(selection.anchorNode).closest('pre, code').length;
        UCSMTracker.recordTextSelection(this, selection.toString(), isCode);
    }
});

// Copy detection — document-level
document.addEventListener('copy', function(e) {
    const selection = window.getSelection();
    if (!selection || !selection.toString()) return;
    const messageCard = $(selection.anchorNode).closest('.message-card');
    if (messageCard.length) {
        const isCode = !!$(selection.anchorNode).closest('pre, code').length;
        UCSMTracker.recordCopy(messageCard[0], isCode);
    }
});

// Manual scroll detection — distinguish user scroll from programmatic
let lastScrollWasProgrammatic = false;
$('#chatView').on('scroll', function() {
    if (lastScrollWasProgrammatic) { lastScrollWasProgrammatic = false; return; }
    // Find topmost visible message card
    const cards = document.querySelectorAll('#chatView .message-card');
    // ... identify which card is at scroll position, record if scrolled UP to older message
});

// Existing signals that already have endpoints — just forward to UCSM:
// - Pin: hook into .pin-message-btn click handler → also record signal_type='pinned'
// - Doubt: hook into doubt creation → also record signal_type='doubt_asked'
```

### Distinguishing Manual Scroll from Programmatic

The codebase uses `scrollToBottomBtn` and auto-scroll during streaming. Set a flag before programmatic scrolls:

```javascript
// Patch existing scroll-to-bottom:
const originalScrollToBottom = scrollToBottom;
function scrollToBottom() {
    lastScrollWasProgrammatic = true;
    originalScrollToBottom.apply(this, arguments);
}
```

Only `scroll` events without the flag preceding them count as manual engagement.


---

## Prompt Injection

### Where It Hooks In

The existing PKB distillation step (Conversation.py line ~9972) takes raw PKB context and distills it into `user_info_text`. UCSM injects its signal here.

**Flow:**
```
reply() →
  _get_pkb_context() → raw PKB claims (existing)
  _get_ucsm_context() → relevant topic states (NEW)
  
  → PKB distillation LLM call receives BOTH:
    - Raw PKB claims (what system knows about user)
    - UCSM topic states (what user knows/has absorbed)
  
  → Outputs user_info_text including behavioral instructions
```

### UCSM Context Retrieval

```python
def _get_ucsm_context(self, user_email: str, query: str, k: int = 5) -> str:
    """Retrieve UCSM topics relevant to the current query."""
    # 1. Compute query embedding
    # 2. Search topic_embeddings for cosine similarity > 0.6
    # 3. Also FTS5 keyword search on topic labels
    # 4. Merge results, take top k
    # 5. Format with label, depth, absorption_score, last_reinforced, source conversation friendly_id
    
    return """
USER'S COGNITIVE STATE (topics previously engaged with):
- "5/3/1 workout progression": deeply explained Jun 3 (conv #w4k), high engagement (absorption: 0.85)
- "progressive overload": mentioned briefly Jun 3 (conv #w4k), uncertain retention (absorption: 0.35)
"""
```

### Modified Distillation Prompt

The existing distillation prompt is extended with UCSM context:

```
Given the user's personal knowledge AND their cognitive state (topics previously discussed):

{pkb_context}

{ucsm_context}

Current query: {query}

Extract:
1. User preferences/facts relevant to this query (from PKB)
2. For topics with absorption > 0.7: "User is familiar with [topic] — be concise, reference prior discussion in conversation [friendly_id]"
3. For topics with absorption 0.4-0.7: "User has seen [topic] — provide enough context to stand alone"
4. For topics with absorption < 0.4 or unseen: no special instruction (full treatment)

Format conversation references as: "You discussed [topic] in detail previously (conversation #[friendly_id], [date])"
```

### Response Behavior by Absorption Tier

**High absorption (0.8-1.0) — Bare minimum + pointer:**
```
User: "What's the deload week in my program?"
Assistant: "Week 4 — reduce all working sets to 60% of your training max.
(You set this up in detail in conversation #w4k on June 3 — want me to pull that up?)"
```

**Moderate absorption (0.5-0.79) — Concise + context + pointer:**
```
User: "How does progressive overload work in my program?"
Assistant: "Each cycle, you add 5lb to upper lifts and 10lb to lower lifts on your training max.
This means your actual working weights (percentages of TM) go up every 3 weeks.
(We touched on this when setting up your program — conversation #w4k.)"
```

**Low absorption (0.0-0.49) — Full treatment:**
```
User: "What's RPE and how does it apply?"
Assistant: [Full multi-paragraph explanation, no assumption of prior knowledge]
```

### Conversation Reference Modal

When the response contains a pointer like "(conversation #w4k)", the frontend renders it as a clickable link. Clicking opens a modal showing the referenced message content. The modal includes a "Go to conversation" button that switches to that conversation.

```javascript
// Render conversation references as clickable
function renderConversationRef(friendlyId, date) {
    return `<a href="#" class="ucsm-conv-ref" data-friendly-id="${friendlyId}">(conversation #${friendlyId}, ${date})</a>`;
}

// Click handler opens preview modal
$(document).on('click', '.ucsm-conv-ref', function(e) {
    e.preventDefault();
    const fid = $(this).data('friendly-id');
    UCSMModal.showConversationPreview(fid);
});
```

**Modal structure:** Same Bootstrap 4 pattern as cross-conversation search. Shows the relevant message(s) from the referenced conversation. "Go to conversation" button hides modal then calls `ConversationManager.setActiveConversation(convId)`.

### Explicit Reset Detection

Before prompt injection, check if the current query indicates the user wants a fresh explanation:

```python
RESET_PATTERNS = [
    r"explain .+ again",
    r"i forgot about",
    r"remind me (about|how|what)",
    r"from scratch",
    r"walk me through .+ again",
    r"what was .+ again",
    r"can you re-?explain",
]

def should_reset_topic(query: str) -> Optional[str]:
    """Detect if user is asking for a fresh explanation. Returns topic to reset or None."""
    for pattern in RESET_PATTERNS:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return extract_topic_from_query(query)  # simple extraction
    return None
```

If detected, the topic's absorption score is temporarily treated as 0.0 for this response (and optionally the stored state is reset).


---

## Backend API (endpoints/ucsm.py)

### Blueprint Registration

New file `endpoints/ucsm.py` with `ucsm_bp = Blueprint('ucsm', __name__)`. Registered in `endpoints/__init__.py`.

### Endpoints

```
POST /ucsm/engagement              — Batch receive engagement signals from frontend
GET  /ucsm/topics                  — List all topics for user (paginated, sortable)
GET  /ucsm/topics/<topic_id>       — Get single topic with full history
GET  /ucsm/topics/search           — Semantic + FTS search over topics
PUT  /ucsm/topics/<topic_id>       — Edit topic (rename, reset depth, mark as reset)
DELETE /ucsm/topics/<topic_id>     — Delete topic entirely
POST /ucsm/topics/<topic_id>/reset — Reset absorption score (user says "I forgot")
GET  /ucsm/context                 — Get UCSM context for a query (used by prompt assembly)
DELETE /ucsm/conversation/<conv_id> — Delete all UCSM data for a conversation (cascade hook)
```

### Database Module (database/ucsm.py)

Follows pattern from `database/pinned_messages.py`:
- `configure_users_dir(path)` — sets storage root
- CRUD functions: `create_topic()`, `get_topics()`, `update_topic()`, `delete_topic()`, `add_history_entry()`, `get_history_for_topic()`, `record_engagement_batch()`, `get_engagement_summary()`, `delete_by_conversation()`
- Registered in `database/__init__.py`

---

## UI Inspection — Knowledge Map Tab

### Location

New tab in PKB modal, positioned between "Overview" (tab 8) and "Maintenance" (tab 9).

### Tab HTML

```html
<li class="nav-item">
  <a class="nav-link" id="pkb-knowledgemap-tab" data-toggle="tab" href="#pkb-knowledgemap-pane" role="tab">
    <i class="bi bi-diagram-3"></i> Knowledge Map
  </a>
</li>
```

### Content Structure

```html
<div class="tab-pane fade" id="pkb-knowledgemap-pane" role="tabpanel">
  <div class="d-flex justify-content-between mb-3">
    <input type="text" class="form-control form-control-sm w-50" id="ucsm-search" placeholder="Search topics...">
    <select class="form-control form-control-sm w-25" id="ucsm-sort">
      <option value="absorption_desc">Highest confidence</option>
      <option value="recent">Most recent</option>
      <option value="decayed">Needs refresh</option>
    </select>
  </div>
  <div id="ucsm-topics-list"></div>
</div>
```

### Topic Card Rendering

Each topic shows:
- Topic label (bold)
- Confidence badge: High (green) / Medium (yellow) / Low (red) — maps to absorption score ranges
- Depth label: "Deeply explained" / "You demonstrated understanding" / "Mentioned briefly" / "Asked but moved on"
- Last reinforced date
- Reinforcement count
- Source conversations (clickable friendly IDs)
- "Reset" button (resets absorption to 0, user says they forgot)
- "Delete" button (removes topic entirely)

```html
<div class="card mb-2 ucsm-topic-card" data-topic-id="${topic.topic_id}">
  <div class="card-body py-2 px-3">
    <div class="d-flex justify-content-between align-items-center">
      <strong>${topic.topic_label}</strong>
      <span class="badge badge-${confidenceColor}">${confidenceLabel}</span>
    </div>
    <small class="text-muted">
      ${depthLabel} · Last seen ${relativeDate} · ${topic.reinforcement_count}× reinforced
    </small>
    <div class="mt-1">
      <small>Sources: ${conversationLinks}</small>
    </div>
    <div class="mt-1">
      <button class="btn btn-sm btn-outline-warning ucsm-reset-btn">Reset</button>
      <button class="btn btn-sm btn-outline-danger ucsm-delete-btn">Delete</button>
    </div>
  </div>
</div>
```

### What's NOT Shown

- Raw engagement signals (viewport time, scroll counts) — too granular, feels surveillance-like
- The exact computation behind confidence — just the label (High/Medium/Low)
- Per-message engagement breakdown — only topic-level summary

---

## Conversation Deletion Cascade

### Hook Point

In `endpoints/conversations.py`, between line 960 (after cross-conv index removal) and line 963 (before cache eviction):

```python
# After cross-conversation search index removal:
try:
    index = state.cross_conversation_index
    if index:
        index.remove_conversation(conversation_id)
except Exception:
    pass

# NEW: UCSM cascade delete
try:
    from database.ucsm import delete_by_conversation
    delete_by_conversation(email, conversation_id)
except Exception:
    logger.warning(f"UCSM cascade delete failed for {conversation_id}")

# Existing: evict from cache
del state.conversation_cache[conversation_id]
```

### What Gets Deleted

1. `topic_history` rows where `conversation_id` matches
2. `message_engagement` rows where `conversation_id` matches
3. `message_engagement_summary` rows where `conversation_id` matches
4. Topics are NOT deleted — but `current_depth` and `absorption_score` are recomputed from remaining history entries
5. If a topic has zero remaining history entries after cascade → topic is deleted

### Recomputation After Cascade

```python
def delete_by_conversation(user_email: str, conversation_id: str):
    """Remove all UCSM data tied to a conversation and recompute affected topics."""
    # 1. Find all topics that have history entries from this conversation
    affected_topics = get_topics_by_conversation(user_email, conversation_id)
    
    # 2. Delete history entries and engagement data
    delete_history_for_conversation(user_email, conversation_id)
    delete_engagement_for_conversation(user_email, conversation_id)
    
    # 3. Recompute each affected topic
    for topic in affected_topics:
        remaining_history = get_history_for_topic(topic['topic_id'])
        if not remaining_history:
            delete_topic(topic['topic_id'])
        else:
            recompute_topic_state(topic['topic_id'], remaining_history)
```

---

## Decay Mechanism

### When Decay Runs

- On every UCSM context retrieval (lazy — only decay topics that are being queried)
- Optionally: background job on server start that decays all topics older than 30 days

### Decay Logic

```python
def apply_decay(topic: dict, now: datetime) -> dict:
    """Apply 30-day half-life decay to a topic's absorption score."""
    days_since = (now - parse_iso(topic['last_reinforced_at'])).days
    if days_since < 7:
        return topic  # grace period, no decay in first week
    
    decay_factor = 0.5 ** (days_since / 30.0)
    new_score = topic['absorption_score'] * decay_factor
    
    # Status transitions
    if new_score < 0.2 and topic['status'] == 'active':
        topic['status'] = 'decayed'  # "may need refresh"
    
    topic['absorption_score'] = new_score
    topic['last_decayed_at'] = now.isoformat()
    return topic
```

### Reinforcement (Resets Decay Clock)

Any of these reset `last_reinforced_at` to now:
- Topic extracted again in a new conversation turn
- User asks a doubt on a message related to the topic
- User manually scrolls back to the original explanation
- User asks a follow-up question about the topic

---

## Multi-User Support

All tables keyed by `user_email`. Storage path: `storage/ucsm/{user_email}/`. Database connections are per-user (same pattern as PKB's `StructuredAPI.for_user(email)`).

The `UCSMExtractor` and `UCSMDatabase` classes accept `user_email` and scope all queries. The frontend sends the authenticated user's email via the existing session/JWT mechanism.

---

## File Structure (New Files)

```
truth_management_system/
└── ucsm/                           # New subpackage
    ├── __init__.py                  # Exports UCSMExtractor, UCSMDatabase, UCSMConfig
    ├── config.py                    # UCSMConfig dataclass
    ├── database.py                  # UCSMDatabase class (ucsm.db + engagement.db)
    ├── extractor.py                 # UCSMExtractor class
    ├── models.py                    # TopicObservation, TopicState dataclasses
    └── retrieval.py                 # UCSM context retrieval for prompt injection

endpoints/
└── ucsm.py                         # Blueprint: ucsm_bp

interface/
└── ucsm-tracker.js                 # UCSMTracker module (engagement signals)

database/
└── (no changes — UCSM manages its own DB internally)
```

### Why Under truth_management_system/?

UCSM is conceptually part of the "what we know about the user" family. It shares infrastructure patterns (embeddings, FTS5, LLM extraction) with PKB. Placing it as a subpackage keeps it discoverable while maintaining full separation (own DB, own API, own extraction logic).

---

## Implementation Tasks (Ordered)

### Phase A: Storage & Core (No UI, no frontend)

1. Create `truth_management_system/ucsm/` package with config, database, models
2. Implement `UCSMDatabase` class with SQLite schema creation + CRUD
3. Implement `UCSMExtractor.extract_from_turn()` with LLM prompt
4. Implement topic dedup (embedding + FTS5 matching)
5. Implement `merge_observation()` — create or update topics
6. Hook extraction into `_persist_current_turn_inner()` (non-blocking thread)
7. Implement decay logic in retrieval path
8. Implement `_get_ucsm_context()` for prompt injection
9. Modify PKB distillation prompt to consume UCSM context

### Phase B: Engagement Collection (Frontend → Backend)

10. Create `endpoints/ucsm.py` with `POST /ucsm/engagement` endpoint
11. Create `interface/ucsm-tracker.js` with IntersectionObserver + signal batching
12. Wire IntersectionObserver into `renderMessages()` using existing `window.messageObservers`
13. Wire text selection/copy handlers
14. Wire manual scroll detection (flag-based)
15. Wire existing pin/doubt signals to also record in UCSM
16. Implement `message_engagement_summary` aggregation

### Phase C: Scoring & Prompt Injection

17. Implement `compute_engagement_score()` and `compute_absorption_score()`
18. Connect engagement scores to topic absorption computation
19. Implement UCSM context retrieval (semantic + FTS5 search)
20. Integrate into `reply()` prompt assembly path
21. Implement explicit reset detection (regex patterns in query)
22. Test end-to-end: topic extracted → engagement collected → prompt modified → response shorter

### Phase D: UI & Inspection

23. Add "Knowledge Map" tab to PKB modal HTML
24. Implement `loadKnowledgeMap()` in pkb-manager.js (or separate ucsm-ui.js)
25. Implement topic cards with confidence badges, reset/delete buttons
26. Implement conversation reference links (clickable, opens preview modal)
27. Implement "Go to conversation" button in preview modal

### Phase E: Cascade & Cleanup

28. Hook `delete_by_conversation()` into conversation deletion endpoint
29. Implement topic recomputation after cascade
30. Add to `cleanup_deleted_conversations()` batch path
31. Test: delete conversation → UCSM records removed → topics recomputed

---

## Open Items for Future Iteration

- **Topic merging UI**: When two topics are semantically similar but not auto-merged, allow manual merge in Knowledge Map
- **Export/import**: Export UCSM state (for backup or migration between instances)
- **Topic relationships**: "X depends on understanding Y" — so if Y decays, X also gets flagged
- **Model-specific thresholds**: Different users retain differently — adaptive half-life based on observed re-ask patterns
- **Integration with auto-doubts**: If auto-doubt on a topic goes unread, that's a negative engagement signal
- **Conversation-level summary view**: "In this conversation, you deeply covered X, Y, Z" — shown on conversation close or as a conversation metadata card

---

## Data Model Deficiencies & Mitigations

### 1. Topic Granularity & Hierarchy

**Problem:** No relationship between topics. "React hooks" and "useEffect cleanup" are independent rows, but one is a subtopic of the other. User deeply understands "useEffect cleanup" but asks about "React hooks" broadly — system finds no match, gives full explanation, redundantly re-explains the subtopic.

**Mitigation:** Add `related_topic_ids` JSON array in `meta_json`. At retrieval time, if a query matches a broad topic, also check if the user has strong absorption on subtopics and mention those specifically in the prompt injection. No `parent_topic_id` FK needed — relationships are non-hierarchical and soft.

**Schema change:**
```sql
-- No schema change needed. Use meta_json:
-- meta_json.related_topic_ids = ["topic_id_1", "topic_id_2"]
```

**When relationships are created:** During `merge_observation()`, if embedding similarity is 0.6–0.85 (related but not duplicate), link bidirectionally via meta_json.

---

### 2. Topic Label Drift & Synonyms

**Problem:** LLM might extract "5/3/1 program", "Wendler 531", "5/3/1 progression" across conversations — all the same topic. Embedding dedup (cosine > 0.85) won't catch all variants. Results in fragmented topics with low individual scores instead of one consolidated high-score topic.

**Mitigation:** Add `canonical_label` and `aliases` to the topics table. When a new extraction is close but not identical (cosine 0.7–0.85), store it as an alias of the existing topic. Periodic background consolidation pass (LLM-based) merges obvious duplicates.

**Schema change:**
```sql
ALTER TABLE topics ADD COLUMN canonical_label TEXT;  -- normalized form
ALTER TABLE topics ADD COLUMN aliases TEXT;          -- JSON array of variant labels
```

**Matching logic at extraction time:**
1. Exact FTS5 match → same topic
2. Cosine > 0.85 → same topic (store new label as alias)
3. Cosine 0.7–0.85 → same topic (store as alias) but log for review
4. Cosine < 0.7 → new topic (link as related via meta_json)

**Periodic consolidation:** Background job that groups topics by high embedding similarity, presents to LLM: "Are these the same topic? If yes, which is the canonical label?" Merges history entries and aliases.

---

### 3. No Topic-to-Message Mapping

**Problem:** `topic_history` stores `turn_range_start/end` (message indices) but no direct link to specific message_ids. Indices shift if messages are deleted or reordered. The "pointer to old conversation" preview modal needs stable references.

**Mitigation:** Store `message_ids` (JSON array of UUIDs) in topic_history alongside turn_range. Message IDs are stable and don't shift with reordering or deletion.

**Schema change:**
```sql
ALTER TABLE topic_history ADD COLUMN message_ids TEXT;  -- JSON array of message UUIDs
```

**At extraction time:** The extraction prompt already knows the current message_id (passed from persist flow). Store it in the array. For multi-turn topic discussions, accumulate message_ids across turns until the topic is no longer discussed.

---

### 4. Engagement-to-Topic Attribution

**Problem:** Engagement on message #14 and topic "X" discussed in turns 12–15 — the join is implicit (range overlap). If 3 topics co-occur in those turns, engagement is smeared equally across all.

**Mitigation:** Add `primary_topic_id` to `message_engagement_summary`. During extraction, the LLM already identifies which topic a specific turn range covers — propagate that to engagement records. If a message spans multiple topics, attribute proportionally or to the topic that occupies the most text.

**Schema change:**
```sql
ALTER TABLE message_engagement_summary ADD COLUMN primary_topic_id TEXT;
```

**Attribution logic:** After UCSM extraction assigns topics to turn ranges, backfill `primary_topic_id` on engagement summaries that fall within those ranges. For messages in overlapping ranges, use the topic whose turn_range center is closest to that message index.

---

### 5. No Explanation Content Stored

**Problem:** We store *that* a topic was explained but not *what*. Preview modal needs content from the original conversation. If conversation is archived/compressed or messages pruned, content is gone.

**Mitigation:** Add `key_points` field to `topic_history` — a distilled 2-4 bullet summary of what was actually said about this topic in this conversation. Survives message pruning. Generated by the extraction LLM as part of the same call (low marginal cost).

**Schema change:**
```sql
ALTER TABLE topic_history ADD COLUMN key_points TEXT;  -- Distilled summary of what was discussed
```

**In extraction prompt:** Add to output format:
```json
{
  "topic": "5/3/1 progression",
  "depth": "explained_to_user",
  "key_points": ["Add 5lb upper/10lb lower each cycle", "Deload on week 4 at 60%", "Training max != actual max"],
  "turn_range": [12, 15],
  "message_ids": ["uuid-1", "uuid-2"]
}
```

**Preview modal fallback:** Try to load original message content first. If unavailable (deleted/archived), show `key_points` as fallback with a note "Original conversation no longer available — here's what was covered."

---

### 6. Conflicting Depth Within One Conversation

**Problem:** `current_depth` is a single value per topic_history entry, but depth can legitimately differ within one conversation. User demonstrates understanding at turn 5 but reveals confusion at turn 20.

**Mitigation:** Allow multiple history entries per conversation (remove implicit "one per conv" assumption). Add `confidence_in_depth` field. When signals conflict within a conversation, create separate entries for each phase with lower confidence.

**Schema change:**
```sql
ALTER TABLE topic_history ADD COLUMN confidence_in_depth REAL DEFAULT 0.8;  -- 0.0-1.0
```

**Logic:** If the extraction prompt detects the user initially understood but then expressed confusion:
- Entry 1: turns 5-12, depth=`user_demonstrated_understanding`, confidence_in_depth=0.6
- Entry 2: turns 20-22, depth=`user_asked_about_but_moved_on`, confidence_in_depth=0.9

The absorption score computation uses confidence-weighted depth levels.

---

### 7. No User-Level Calibration

**Problem:** All users get same thresholds (absorption > 0.7 = concise, 30-day decay, etc.). Some retain well, others don't. One-size-fits-all feels wrong for outliers.

**Mitigation (deferred to v2):** After accumulating data, observe patterns — if a user frequently re-asks about topics with high absorption scores, their thresholds are miscalibrated. Add a `user_calibration` record that adjusts over time.

**Future schema (not in v1):**
```sql
CREATE TABLE IF NOT EXISTS user_calibration (
    user_email TEXT PRIMARY KEY,
    retention_factor REAL DEFAULT 1.0,         -- multiplier on decay half-life
    concise_threshold REAL DEFAULT 0.7,        -- absorption above this → concise
    moderate_threshold REAL DEFAULT 0.4,       -- absorption above this → moderate
    re_ask_count INTEGER DEFAULT 0,            -- times user re-asked known topics
    last_calibrated_at TEXT,
    created_at TEXT NOT NULL
);
```

**Adaptation signal:** When a reset is triggered (user says "explain again" or implicit detection), compare topic's absorption score at that moment. If score was > 0.7 but user needed re-explanation, increment `re_ask_count` and slightly raise `concise_threshold`.

**Status:** Deferred. Build data collection first, calibration layer later.

---

### 8. Conversation Deletion Leaves Score Artifacts

**Problem:** User learned X in conv A (deleted), then demonstrated understanding in conv B (because they knew from A). After deleting A, conv B's entry remains — score stays high even though the foundational source is gone.

**Assessment:** This is acceptable. The user DID demonstrate understanding in B regardless of the cause. The observation is valid at time of recording. No fix needed — the system correctly represents what was observed, not the causal chain behind it.

**Design decision:** No mitigation. Accept that deletion is lossy and observations from other conversations remain valid independently.

---

### 9. No Schema Versioning

**Problem:** No migration mechanism. First schema change after deployment requires manual migration or data loss.

**Mitigation:** Add `schema_version` table to both databases. Include a migration runner in `UCSMDatabase.initialize()` matching PKB's pattern.

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

**Migration pattern:**
```python
CURRENT_VERSION = 1
MIGRATIONS = {
    2: [
        "ALTER TABLE topics ADD COLUMN canonical_label TEXT",
        "ALTER TABLE topics ADD COLUMN aliases TEXT",
    ],
    # Future migrations added here
}

def _run_migrations(self):
    current = self._get_schema_version()
    for version in sorted(MIGRATIONS.keys()):
        if version > current:
            for sql in MIGRATIONS[version]:
                self.conn.execute(sql)
            self.conn.execute("INSERT INTO schema_version VALUES (?, ?)", (version, now_iso()))
    self.conn.commit()
```

---

### 10. Embedding Model Lock-in

**Problem:** If the embedding model changes, existing topic_embeddings are incomparable to new query embeddings. Retrieval silently degrades — old topics never match queries.

**Mitigation:** The `model_name` column already exists. Add a `recompute_all_embeddings()` utility that re-embeds all topic labels when the model changes. At retrieval time, skip embeddings from mismatched models (fall back to FTS5 only until re-embedding completes).

**Implementation:**
```python
def recompute_all_embeddings(self, new_model_name: str):
    """Re-embed all topics with a new model. Called on model change."""
    topics = self.get_all_topics(self.user_email)
    for topic in topics:
        embedding = get_document_embedding(topic['topic_label'], model=new_model_name)
        self.update_embedding(topic['topic_id'], embedding, new_model_name)

def search_by_embedding(self, query_embedding, model_name, threshold=0.6):
    """Only compare against embeddings from the same model."""
    rows = self.conn.execute(
        "SELECT topic_id, embedding FROM topic_embeddings WHERE model_name = ?",
        (model_name,)
    ).fetchall()
    # ... cosine similarity against matching-model embeddings only
```

**Trigger:** When `config.embedding_model` changes (detected on startup by comparing stored model_name against current config), queue a background re-embedding job.

---

### Priority Matrix

| # | Issue | Severity | Fix in v1? | Effort |
|---|-------|----------|-----------|--------|
| 1 | Topic hierarchy | Medium | Yes (meta_json) | Low |
| 2 | Label drift/synonyms | High | Yes (schema) | Medium |
| 3 | No message_id mapping | High | Yes (schema) | Trivial |
| 4 | Engagement attribution | Medium | Yes (schema) | Low |
| 5 | No explanation content | Medium | Yes (schema) | Low |
| 6 | Conflicting depth | Low | Yes (schema) | Low |
| 7 | User calibration | Low | No (v2) | Medium |
| 8 | Deletion artifacts | N/A | No (accepted) | N/A |
| 9 | Schema versioning | High | Yes | Trivial |
| 10 | Embedding model lock-in | Medium | Yes (utility) | Low |

**All items except #7 and #8 are incorporated into the v1 schema and implementation plan.**

