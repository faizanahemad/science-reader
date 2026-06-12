# App-Wide Notification System

**Status:** Draft
**Created:** 2026-06-12
**Scope:** A persistent, app-wide notification system in the main header bar (bell icon + dropdown) that aggregates non-PKB events (background tasks, auto-doubts, doc failures, system errors) plus a link to PKB notifications. Ships active in `users.db`. 7-day auto-expiry for app notifications.

**Related plans:** `pkb_notification_system.plan.md` (PKB-specific notifications, independent table in PKB DB), `auto_context_history_mode.plan.md`, `agent_delegate_task.plan.md`.

**Non-goals:** Replacing PKB notifications (they remain independent), email digest, mobile push.

---

## 1. Background & Motivation

The app has multiple subsystems that generate events needing user attention:
- Background sub-agent tasks complete with no notification (result silently expires after 30min)
- Auto-doubts finish generating but only show a pulse animation (missed if user looks away)
- Document indexing can fail silently
- Auto-context degradation is logged but not surfaced

The PKB notification system (v14) solved this for knowledge-base events. The app-wide system extends the same philosophy to everything else: **no event should be silently lost**.

---

## 2. Design Decisions

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Bell shows PKB notifications? | **No.** Shows non-PKB only + a link card "🧠 N PKB items need attention — Open PKB" when unread PKB items exist. | PKB modal has its own tab; avoid duplication. |
| 2 | Persistence level? | **DB-persistent** in `users.db`, survives page reload. | Enables polling from any tab. |
| 3 | Notification lifetime? | **7 days** auto-expiry for app notifications. | App events are time-sensitive; unlike PKB facts, they lose relevance quickly. |
| 4 | Conversation-scoped? | Always show in bell, but card includes conversation name/link so user can navigate. | Don't hide relevant notifications based on active conversation. |
| 5 | Panel format? | Fixed-width dropdown (~400px, like GitHub). | Lightweight, doesn't disrupt workflow. |
| 6 | Actions? | "Dismiss" is universal. Feature-specific bonus actions: "View" (navigate), "View Result" (show content). | Simple and consistent. |
| 7 | Background task notification? | Include truncated original prompt (first 100 chars) so user knows which task. | Context without clutter. |
| 8 | Auto-doubts signal? | Server-side write when generation completes. | Reliable across tabs, works even if JS polling misses. |
| 9 | Table location? | `users.db` (main app DB), alongside conversations. | These are conversation/session-scoped events, not knowledge. |
| 10 | Doc indexing? | Only emit notification on **failure**. Success is obvious from UI update. | Reduce noise. |
| 11 | Polling frequency? | Every 30s, lightweight (COUNT query only for badge). Full list on dropdown open. | Low server load. |
| 12 | Mark-as-read? | Opening bell panel marks all as seen. | Consistent with PKB behavior. |
| 13 | STM→LTM promotion? | **PKB notification** (not app-wide). It's a knowledge-base event. | Correct ownership. |

### Pre-Mortem Decisions (2026-06-12)

| # | Issue | Decision | Detail |
|---|-------|----------|--------|
| PM1 | Multi-tab polling storm | **localStorage dedup** — skip poll if another tab polled <25s ago | ~5 lines JS; eliminates 80% redundant polls |
| PM2 | SQLite contention on users.db | **WAL mode** — `PRAGMA journal_mode=WAL` on users.db | Concurrent readers + one writer; notification writes are infrequent |
| PM3 | Doubt watcher thread accumulation | **Cap at 2** per user — new message skips if 2 watchers already active | Bounded resource, still covers rapid-fire edge case |
| PM4 | Duplicate doubts signals (pulse + notification) | **Keep both** — pulse is immediate visual, notification is persistent record | Distinct purposes; no toast on notification creation to avoid triple-signal |
| PM5 | Auto-context noise | **1 per conversation per session** (until dismissed) | Minimal noise; suppresses repeated same-issue notifications |
| PM6 | Background task missing user_email | **Make `user_email` required parameter** of `start_background_agent` | Prevents the bug structurally; small refactor of callers |
| PM7 | "View" navigation for doubts | **Full navigation** — switch conversation + scroll to message | Complex but correct; user lands exactly where doubts are |
| PM8 | Badge combines app + PKB count | **Two parallel requests** (`Promise.all`) — independent, no coupling | Both are fast COUNT queries; perceived as single update |
| PM9 | Emission failure handling | **Retry once after 1s, then skip** | Handles transient DB lock; adds minimal delay |
| PM10 | Expiry behavior | **7 days from creation (unseen); 3 days from seen_at (seen)** — whichever is later | Fair: gives seen items a shorter tail; unseen items persist full week |

### Scope Decisions

| Item | In v1? | Notes |
|------|--------|-------|
| Background delegate task completion | ✓ | Biggest gap — currently zero notification |
| Auto-doubts ready | ✓ | Persistent fallback for pulse animation |
| Document indexing failure | ✓ | Only on failure (success obvious from UI) |
| PKB unread link card | ✓ | "N PKB items — Open PKB" in dropdown |
| Auto-context degradation | ✓ | 1 per conversation per session |
| Auto-archival (conversations) | ✓ | "N conversations auto-archived" with undo action. Batched per sweep (max 5/run). |
| ask_clarification tool | ✗ | Already has modal (real-time, blocks stream) |
| STM→LTM promotion | ✗ | Goes to PKB notifications (knowledge-base event) |
| Stale/expired conversations | ✗ | Rare edge case: temp chat expired while away, just shows toast. Not worth persisting. |

### Full Design Q&A (2026-06-12)

**Q1: Bell shows PKB notifications or just non-PKB?**
A: Show non-PKB only + link card to PKB notifications if unread exist.

**Q2: Persistence level — DB or in-memory?**
A: Persistent in DB (users.db). Polling works; survives page reload.

**Q3: Background task notification — include full result?**
A: "Background task completed — click to view" with truncated prompt (100 chars).

**Q4: Auto-doubts — persistent notification in bell?**
A: Yes, persistent notification. Keep pulse animation too (both).

**Q5: Scope for v1?**
A: Full (all items listed above).

**Q6: Multi-tab polling — how to handle?**
A: localStorage dedup — skip if another tab polled <25s ago.

**Q7: SQLite contention?**
A: WAL mode on users.db (concurrent readers + 1 writer).

**Q8: Doubt watcher thread accumulation?**
A: Cap at 2 per user. New message skips if 2 watchers already active.

**Q9: Duplicate doubts signals (pulse + notification)?**
A: Keep both. Pulse = immediate; notification = persistent record.

**Q10: Auto-context noise?**
A: 1 per conversation per session (until dismissed).

**Q11: Background task missing user_email in context?**
A: Make user_email a required parameter of start_background_agent (structural fix).

**Q12: "View" navigation for doubts (cross-conversation)?**
A: Full navigation — switch conversation + scroll to message.

**Q13: Badge combines app + PKB — one request or two?**
A: Two parallel requests via Promise.all (independent, no coupling).

**Q14: Emission failure handling?**
A: Retry once after 1s, then log warning and skip.

**Q15: Expiry — 7 days from when?**
A: 7 days from creation for unseen; 3 days from seen_at for seen (whichever is later).

**Q16: STM→LTM promotion in app notifications?**
A: No — it's a knowledge-base event, should be a PKB notification.

**Q17: What is "stale conversation"?**
A: When a temporary chat expires/deleted while user is away. Rare edge case, just a toast currently. Not worth persisting.

---

## 3. Schema

```sql
CREATE TABLE IF NOT EXISTS AppNotifications (
    notification_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    priority TEXT NOT NULL DEFAULT 'low',
    conversation_id TEXT,
    conversation_name TEXT,
    action_url TEXT,
    action_label TEXT,
    action_data TEXT,
    seen_at TEXT,
    dismissed_at TEXT,
    expires_at TEXT NOT NULL,           -- 7d from creation; or 3d from seen_at (whichever later)
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_app_notif_user_active
    ON AppNotifications(user_email, dismissed_at, expires_at, created_at DESC);
```

**Expiry logic (PM10):** `expires_at` initially set to `created_at + 7 days`. When `mark_seen` is called, if `seen_at + 3 days > current expires_at`, extend `expires_at` to `seen_at + 3 days`. This means: unseen = 7 days max; seen but not dismissed = min(7d from creation, 3d from seen), whichever is later.

### 3.1 Categories

| Category | Priority | Source | action_label |
|----------|----------|--------|--------------|
| `background_task_done` | medium | `code_common/agent_tool.py` | "View Result" |
| `background_task_error` | medium | `code_common/agent_tool.py` | "View Error" |
| `doubts_ready` | low | `endpoints/conversations.py` | "View" |
| `doc_index_failed` | medium | doc indexing endpoints | "Retry" |
| `auto_context_degraded` | low | `code_common/auto_context.py` | None |
| `conversations_archived` | low | `utils/auto_archival.py` via list_conversation_by_user | "Undo" |
| `system_error` | medium | various | None |

---

## 4. Backend API

### 4.1 Module: `database/app_notifications.py`

```python
def create_app_notification(user_email, category, title, body=None, priority="low",
                            conversation_id=None, conversation_name=None,
                            action_url=None, action_label=None, action_data=None) -> str

def get_app_notifications(user_email, limit=30, include_dismissed=False) -> list

def get_app_notification_count(user_email) -> int  # unseen + undismissed + not expired

def mark_app_notifications_seen(user_email, notification_ids=None) -> int  # None = mark all

def dismiss_app_notification(user_email, notification_id) -> bool

def prune_expired_app_notifications() -> int  # delete where expires_at < now
```

### 4.2 REST Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/notifications` | GET | List active notifications (params: limit, include_dismissed) |
| `/notifications/count` | GET | Badge count (unseen + active + not expired + non-PKB) |
| `/notifications/mark_seen` | POST | Mark all/specific as seen |
| `/notifications/<id>/dismiss` | POST | Dismiss one notification |
| `/notifications/pkb_count` | GET | Proxy to PKB badge count for the bell link card |

---

## 5. Emission Points

### 5.1 Background Task Completion (`code_common/agent_tool.py`)

Refactor: make `user_email` a required parameter of `start_background_agent` (PM6).

In `_run_background_task`, after setting `status = "done"` or `"error"`:
```python
# Retry once on failure (PM9)
def _emit_task_notification(user_email, task_id, prompt, status, context):
    for attempt in range(2):
        try:
            create_app_notification(
                user_email=user_email,
                category=f"background_task_{status}",
                title=f"Background task {'completed' if status == 'done' else 'failed'}",
                body=prompt[:100] + ("..." if len(prompt) > 100 else ""),
                priority="medium",
                conversation_id=context.get("conversation_id"),
                conversation_name=context.get("conversation_name"),
                action_data=json.dumps({"task_id": task_id}),
                action_label="View Result" if status == "done" else "View Error",
            )
            return
        except Exception:
            if attempt == 0:
                time.sleep(1)
            else:
                logger.warning("Failed to emit notification for task %s", task_id)
```

### 5.2 Auto-Doubts Ready (`endpoints/conversations.py`)

Wrap each doubt dispatch in a counter; emit notification when all dispatched doubts complete. Cap at 2 active watcher threads per user (PM3):
```python
# Module-level tracker
_doubt_watchers: Dict[str, int] = {}  # user_email -> active count

# After all get_async_future() calls, spawn a watcher thread:
def _watch_doubts(futures, user_email, conversation_id, conv_name, message_id):
    if _doubt_watchers.get(user_email, 0) >= 2:
        return  # Skip — too many active watchers
    _doubt_watchers[user_email] = _doubt_watchers.get(user_email, 0) + 1
    try:
        for f in futures:
            try: f.result(timeout=120)
            except: pass
        count = sum(1 for f in futures if f.done() and not f.exception())
        if count > 0:
            create_app_notification(
                user_email=user_email,
                category="doubts_ready",
                title=f"{count} learning aids ready",
                conversation_id=conversation_id,
                conversation_name=conv_name,
                action_url=f"#message-{message_id}",
                action_label="View",
            )
    finally:
        _doubt_watchers[user_email] = max(0, _doubt_watchers.get(user_email, 0) - 1)
```

### 5.3 Document Indexing Failure

In the doc indexing SSE endpoint, on exception/failure:
```python
create_app_notification(
    user_email=email,
    category="doc_index_failed",
    title=f"Document indexing failed: {doc_name[:60]}",
    body=str(error)[:200],
    priority="medium",
    action_label="Retry",
    action_data=json.dumps({"doc_id": doc_id}),
)
```

### 5.4 Auto-Context Degradation (`code_common/auto_context.py`)

On fallback (classification failed, doc selection failed). Dedup: 1 per conversation per session until dismissed (PM5):
```python
# Only emit if no existing undismissed notification for this conv + category
existing = get_app_notifications_for_dedup(email, "auto_context_degraded", conversation_id)
if not existing:
    create_app_notification(
        user_email=email,
        category="auto_context_degraded",
        title="Auto-context unavailable, using fallback",
        body=reason,
        conversation_id=conversation_id,
    )
```

### 5.5 Conversations Auto-Archived (`utils/auto_archival.py`)

After auto-archival sweep archives conversations (max 5 per run, triggered by `list_conversation_by_user`). Batched into a single notification per sweep:
```python
# In the auto-archival sweep, after archiving N conversations:
if archived_count > 0:
    names = [c.title[:40] for c in archived_conversations[:3]]
    body = ", ".join(names)
    if archived_count > 3:
        body += f" + {archived_count - 3} more"
    create_app_notification(
        user_email=user_email,
        category="conversations_archived",
        title=f"{archived_count} conversation{'s' if archived_count > 1 else ''} auto-archived",
        body=body,
        priority="low",
        action_label="Undo",
        action_data=json.dumps({
            "conversation_ids": [c.id for c in archived_conversations],
            "archive_source": "auto",
        }),
    )
```

The "Undo" action calls `POST /archive_conversation/<id>` (toggle) for each conversation in the batch.

---

## 6. UI Design

### 6.1 Header Bell Icon

Position: In the main nav bar (`#pdf-details-tab`), before the logout link.

```html
<li class="nav-item" id="app-notifs-bell">
  <a class="nav-link" href="#" id="app-notifs-toggle">
    <i class="bi bi-bell"></i>
    <span class="badge badge-danger" id="app-notifs-badge" style="display:none;">0</span>
  </a>
</li>
```

### 6.2 Dropdown Panel

Fixed-width (380px), max-height 60vh, scrollable. Opens on bell click.

```
┌─────────────────────────────────────┐
│ Notifications              Mark Read │
├─────────────────────────────────────┤
│ 🧠 3 PKB items — Open PKB     [→]  │  ← shown only if PKB unread > 0
├─────────────────────────────────────┤
│ 🟡 Background task completed  2m    │
│    "Summarize the quarterly..."     │
│    [View Result] [Dismiss]          │
├─────────────────────────────────────┤
│ ⚪ 4 learning aids ready      15m   │
│    in: Research conversation        │
│    [View] [Dismiss]                 │
├─────────────────────────────────────┤
│ 🟡 Doc indexing failed        1h    │
│    report_2026.pdf                  │
│    [Retry] [Dismiss]               │
├─────────────────────────────────────┤
│ All caught up ✓                     │  ← when empty
└─────────────────────────────────────┘
```

### 6.3 Interactions

- Click bell → toggle dropdown, fire `mark_seen` for rendered items
- Badge: shows count of unseen + undismissed + not-expired (app + PKB combined)
- "Open PKB" link → opens PKB modal, switches to notifications tab
- "View Result" → shows background task result in a modal
- "View" (doubts) → full navigation: switch to conversation + scroll to message (PM7). Uses `setActiveConversation(conv_id)` then `scrollToMessage(msg_id)` after render.
- "Dismiss" → POST `/notifications/<id>/dismiss`, remove card from DOM

### 6.4 Polling

Every 30s with localStorage dedup (PM1): skip if another tab polled <25s ago.
Two parallel requests via `Promise.all` (PM8):
- `GET /notifications/count` → app notification count
- `GET /pkb/memory/notifications/count` → PKB count

Badge total = app_count + pkb_count. Only poll when `document.visibilityState === 'visible'`.

```javascript
function pollBadge() {
    var lastPoll = parseInt(localStorage.getItem('notif_poll_ts') || '0');
    if (Date.now() - lastPoll < 25000) return;
    localStorage.setItem('notif_poll_ts', String(Date.now()));
    Promise.all([
        $.get('/notifications/count'),
        $.get('/pkb/memory/notifications/count')
    ]).then(function(results) {
        var total = (results[0].count || 0) + (results[1].count || 0);
        updateBellBadge(total);
    });
}
```

---

## 7. Implementation Tasks

### Phase A — Backend

| # | Task | Details |
|---|------|---------|
| A1 | Schema: `AppNotifications` table in `database/connection.py` | CREATE TABLE + index |
| A2 | Module: `database/app_notifications.py` | CRUD functions (create, get, count, mark_seen, dismiss, prune) |
| A3 | REST endpoints: `/notifications/*` | 5 routes in a new blueprint or existing |
| A4 | Emission: background task completion hook | In `_run_background_task` |
| A5 | Emission: auto-doubts watcher thread | In `send_message` doubt dispatch |
| A6 | Emission: doc index failure | In doc upgrade/index error handlers |
| A7 | Emission: auto-context degradation | In `auto_context.py` fallback paths |
| A8 | Prune expired: call on each `get_app_notifications` | Lazy cleanup |

### Phase B — UI

| # | Task | Details |
|---|------|---------|
| B1 | Header bell icon + badge in nav bar | `interface.html` |
| B2 | Dropdown panel HTML + CSS | Fixed-width, scrollable |
| B3 | JS: fetch notifications on open, render cards | `interface/app-notifications.js` |
| B4 | JS: 30s polling for badge count (visibility-gated) | |
| B5 | JS: dismiss action, mark-seen on open | |
| B6 | JS: PKB link card (fetch PKB count, show if > 0) | |
| B7 | JS: "View Result" action (show bg task result modal) | |
| B8 | JS: "View" action for doubts (navigate to conversation/message) | |

---

## 8. Relationship to PKB Notifications

```
Header Bell (app-wide)                PKB Modal Bell Tab
├── AppNotifications table            ├── pkb_notifications table
│   (users.db, 7-day expiry)         │   (PKB DB, forever)
│                                     │
├── Shows non-PKB events              ├── Shows PKB events only
├── Shows "N PKB items" link card     ├── Full CRUD + approve/reject
└── Lightweight dropdown              └── Full tab in modal
```

The two systems are independent. The header bell queries both:
- `GET /notifications/count` → app notification count
- `GET /pkb/memory/notifications/count` → PKB count (for the link card)

Badge total = app_count + pkb_count (both unseen).

### Coexistence with existing toasts

Several features already show ephemeral toasts (auto-archival toast+undo, auto-doubts pulse, doc indexing progress). The persistent notification system **supplements** these, not replaces:
- **Auto-archival**: Toast+undo fires immediately during the session. Persistent notification is the fallback if user misses the toast (e.g. switched tabs during the sweep).
- **Auto-doubts**: Pulse animation is the primary signal. Persistent notification catches the case where user wasn't looking.
- **Doc indexing**: SSE progress is primary. Notification only for failures.

---

## 9. Constants

```python
APP_NOTIFICATION_EXPIRY_DAYS = 7
APP_NOTIFICATION_CATEGORIES = (
    "background_task_done", "background_task_error",
    "doubts_ready", "doc_index_failed",
    "auto_context_degraded", "conversations_archived", "system_error",
)
APP_NOTIFICATION_POLL_INTERVAL_MS = 30000
```
