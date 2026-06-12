# PKB / TMS — Notification System

**Status:** Implemented (cc633e0b)
**Created:** 2026-06-12
**Scope:** A persistent, queryable notification queue for TMS/PKB events that ensures auto-saves, confirm-lane items, conflicts, reminders, and other PKB state changes are never silently missed. Each notification carries enough state to execute or roll back the underlying action. Ships active (no feature flag — purely additive). Schema v14.

**Related plans:** `pkb_memory_autonomy_dial.plan.md` (autonomy dial produces confirm/auto-save lanes that feed notifications), `pkb_tiered_memory_persistence.plan.md` (routing decisions that emit notifications), `pkb_external_access_ui_mcp_rest_auth.plan.md` (MCP surface).

**Non-goals:** App-wide notification system (designed to be consumed by one later), email digest delivery, push notifications (existing `notification-manager.js` handles OS-level dispatch separately).

---

## 1. Background & Motivation

The tiered persistence system routes candidates into auto-save / confirm / skip lanes. Today:
- **Auto-saves** produce a toast. If the user misses it, the auto-save is invisible until they browse PKB.
- **Confirm-lane items** appear in the memory-proposal-modal during the conversation. If the user dismisses the modal or navigates away, the pending item is lost.
- **Conflicts, reminders due, decayed claims** — no proactive notification at all.

A persistent notification system ensures:
1. No actionable PKB event is silently lost.
2. Users can resolve pending actions at their own pace (async from the conversation).
3. Every notification is self-contained: carries the data to approve, reject, undo, or dismiss without needing the original conversation context.
4. Analytics: response time, action distribution, rejection rate — feeds back into autonomy dial tuning.

---

## 2. Goals & Success Criteria

| # | Goal | Success criteria |
|---|------|------------------|
| G1 | No lost events | Every PKB state change creates a notification; confirm-lane items remain until resolved |
| G2 | Self-contained actions | Approve/reject/undo from notification works without original conversation |
| G3 | Priority triage | High-priority items (conflicts, confirms) are visually distinct from informational ones |
| G4 | Sync with data state | External undo/retract/delete auto-resolves corresponding notifications |
| G5 | Bounded storage | Low-priority notifications capped at 500; high/medium persist forever until resolved |
| G6 | MCP + REST access | Full API surface for programmatic access |
| G7 | In-PKB-modal UI | Notification tab with badge, expandable cards, inline actions |

---

## 2.5 Design Decisions (from design discussion 2026-06-12)

### Architecture

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Replace the confirm modal or augment it? | **Augment.** Modal remains the primary UX for in-conversation confirms. Notifications are a fallback for missed ones. Even confirmed items become low-priority notifications; unconfirmed ones become high-priority. | Users are accustomed to the modal flow; notifications add async resolution without disrupting the existing pattern. |
| 2 | PKB-only scope or app-wide? | **PKB-only.** Design so an app-wide system can pull from PKB notifications later, but keep the UI, backend, and table independent. | Reduces scope; app-wide can compose on top without coupling. |
| 3 | Separate table or extend activity_log? | **Separate `pkb_notifications` table.** | Cleaner lifecycle separation — activity_log is an audit trail (append-only), notifications are a work queue (mutable state: seen, resolved, action_taken). |
| 4 | Notifications carry enough state to be self-contained actions? | **Yes.** `action_payload` JSON stores full data to execute approve/reject/undo without needing original conversation context. | Enables async resolution hours/days after the original conversation. |

### UX & Behavior

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 5 | Badge counts what? | Unseen items where `action_required=True` AND priority is high or medium. | Avoids badge fatigue from low-priority informational items. |
| 6 | Notification lifetime? | **Forever until dismissed.** No auto-expiry. Low-priority capped at 500 (oldest resolved pruned). | User never loses a notification unintentionally; cap prevents unbounded DB growth. |
| 7 | Group multiple auto-saves from one conversation? | **No grouping in v1.** 5 auto-saves = 5 individual notifications. | Simpler implementation; grouping can be a future enhancement. |
| 8 | Reminder scheduling mechanism? | **On-request check** — triggered when PKB modal opens and when notifications tab opens. No background worker. | Avoids adding infrastructure (cron/scheduler); sufficient for v1 since users see reminders when they open the app. |
| 9 | MCP access? | **Yes.** `pkb_list_notifications` + `pkb_resolve_notification` MCP tools. But external agents **cannot create** notifications — internal-only emission. | Agents can help users triage notifications but can't spam the queue. |
| 10 | Email digest? | **Future.** Not in v1. | No email sending mechanism configured; purely additive later. |
| 11 | Feature flag? | **No flag — ships active.** Purely additive UI (new tab); existing behavior unchanged. | Unlike tiered persistence (which changes confirm behavior), notifications only add visibility. No risk of wrong behavior. |
| 12 | UI in first pass? | **Yes.** Backend + UI together. Bell icon + badge + notification tab in PKB modal. | Notifications without UI are invisible — defeats the purpose. |

### Data Integrity & Cross-Reference

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 13 | Store `activity_id` FK in notifications? | **Yes.** Nullable column `activity_id` links notification to its activity log entry. | Enables sync: when `undo_activity()` is called directly, we find and auto-resolve the matching notification. |
| 14 | Sync notifications when claim is deleted/retracted externally? | **Yes.** On claim retract/delete, find notifications WHERE `object_id = claim_id` AND unresolved → set `action_taken = 'resolved_externally'`. | Prevents stale "approve this claim" notifications for claims that no longer exist. |
| 15 | Stale check on approve-from-notification? | **Yes.** Before executing an approve, check for conflicts that may have emerged since notification creation. If conflict found → reject the approve, update notification body, keep unresolved. | Prevents silently adding contradictory claims when PKB state has evolved. |
| 16 | Record rejections in activity log? | **Yes.** `log_activity(action="user_reject", facet="capture", object_type="notification", object_id=notification_id)`. | Enables tracking rejection rate for autonomy dial threshold tuning. |

### UI Details

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 17 | Badge display format? | Bell icon + count number (not the word "Notifications"). | Compact; universally understood iconography. |
| 18 | Default tab when PKB modal opens? | **Claims** (unchanged). Do not auto-switch to Notifications even with pending items. | Respects user's workflow; badge is sufficient to draw attention. |
| 19 | Card layout? | **Expandable cards.** Collapsed shows title + priority + timestamp. Expanded shows full details + action buttons. | Balances information density with clean UI. |
| 20 | MCP tool for creating notifications? | **No.** Agents cannot create notifications. Internal emission only. | Prevents notification spam from external agents. |
| 21 | REST auth model? | Same as existing PKB: `@login_required` + `get_session_identity()`. No additional permission checks — notifications are per-user. | Consistent with existing PKB endpoints; per-user isolation is sufficient. |

### Notification Emission Triggers (v1 scope)

| Trigger | Category | Priority | Condition |
|---------|----------|----------|-----------|
| Tiered routing: confirm lane | `confirm_required` | high | `tiered_persistence_enabled=True` |
| Tiered routing: auto-save lane | `auto_save` | medium | `tiered_persistence_enabled=True` |
| User confirms via modal | `claim_confirmed` | low | Always (even without tiered) |
| MCP agent writes (provenance="mcp") | `mcp_write` | medium | Any MCP write |
| Conflict detection | `conflict_detected` | high | Conflict set created/expanded |
| Claim expiry/decay | `claim_deprecated` | low | On-request check |
| Reminder due within threshold | `reminder_due` | medium | On-request check, configurable threshold |

### Configuration

| Setting | Default | Location |
|---------|---------|----------|
| `reminder_threshold_hours` | 24 | `pkb_user_settings.notification_preferences` |
| `badge_min_priority` | "medium" | `pkb_user_settings.notification_preferences` |
| `emit_low_priority` | True | `pkb_user_settings.notification_preferences` |
| `categories_muted` | [] | `pkb_user_settings.notification_preferences` |
| `LOW_PRIORITY_CAP` | 500 | Code constant |

### Existing System Integration Notes

- **`notification-manager.js`** — existing OS-level push notification system (Electron IPC / Web Notification API). This is a delivery *channel*, not a persistence layer. The PKB notification system is the *source of truth*; in future, high-priority items could trigger `NotificationManager.notify()` as well.
- **`pkb_activity_log`** — audit trail. Notifications reference it via `activity_id` for sync. Activity log remains append-only; notifications are mutable (seen/resolved state).
- **`conflict_sets` table** — existing conflict detection. Notifications add visibility; conflict resolution logic remains in existing code, notification just surfaces it.
- **`#memory-proposal-modal`** — existing confirm UX. Continues to work as-is. Notification system is additive fallback, not replacement.

---

## 3. Schema Design (v14)

```sql
CREATE TABLE IF NOT EXISTS pkb_notifications (
    notification_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    priority TEXT NOT NULL,              -- 'high' | 'medium' | 'low'
    category TEXT NOT NULL,              -- see §3.1
    title TEXT NOT NULL,
    body TEXT,
    object_type TEXT,                    -- 'claim' | 'context' | 'tag' | 'conflict_set' | NULL
    object_id TEXT,                      -- FK to the referenced object
    activity_id TEXT,                    -- FK to pkb_activity_log (nullable)
    action_required INTEGER NOT NULL DEFAULT 0,  -- 1 = user must act
    available_actions TEXT,              -- JSON array: ["approve","reject","undo","dismiss","snooze","pick_new","pick_existing","keep_both"]
    action_payload TEXT,                 -- JSON blob: data to execute action OR prior_state to undo
    action_taken TEXT,                   -- NULL until resolved; e.g. 'approved','rejected','undone','dismissed','resolved_externally','undone_externally'
    resolved_at TEXT,                    -- NULL until resolved
    seen_at TEXT,                        -- NULL until rendered in UI
    source TEXT NOT NULL DEFAULT 'system',  -- 'distillation' | 'text_ingestion' | 'mcp' | 'system' | 'scheduler'
    session_id TEXT,                     -- group by conversation
    expires_at TEXT,                     -- optional TTL (NULL = forever)
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notif_user_unresolved
    ON pkb_notifications(user_email, resolved_at, priority, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_object
    ON pkb_notifications(object_id, object_type);
CREATE INDEX IF NOT EXISTS idx_notif_activity
    ON pkb_notifications(activity_id);
```

### 3.1 Categories

| Category | Priority | Trigger | available_actions |
|----------|----------|---------|-------------------|
| `confirm_required` | high | Tiered routing confirm lane | `["approve","reject","dismiss"]` |
| `conflict_detected` | high | Conflict set created/expanded | `["pick_new","pick_existing","keep_both","dismiss"]` |
| `auto_save` | medium | Tiered routing auto-save lane | `["undo","dismiss"]` |
| `mcp_write` | medium | MCP agent writes a claim | `["undo","dismiss"]` |
| `reminder_due` | medium | Reminder claim within threshold | `["dismiss","snooze"]` |
| `claim_confirmed` | low | User confirms via modal | `["dismiss"]` |
| `claim_deprecated` | low | Claim decayed/expired | `["undo","dismiss"]` |
| `claim_enriched` | low | Auto-tag, auto-link, etc. | `["undo","dismiss"]` |
| `stm_promoted` | low | STM → LTM promotion | `["dismiss"]` |

### 3.2 action_payload Schema (varies by category)

**confirm_required:**
```json
{
  "proposed_action": "add",
  "statement": "I'm allergic to shellfish",
  "claim_type": "fact",
  "context_domain": "health",
  "confidence": 0.88,
  "confidence_aspects": [9, 8, 9, 9],
  "derivation": "stated",
  "tags": ["allergy"],
  "meta": {}
}
```

**conflict_detected:**
```json
{
  "new_claim_id": "uuid-new",
  "new_statement": "I prefer tea",
  "existing_claim_id": "uuid-existing",
  "existing_statement": "I prefer coffee",
  "conflict_set_id": "uuid-cs"
}
```

**auto_save / mcp_write:**
```json
{
  "claim_id": "uuid",
  "statement": "I run 5k every morning",
  "prior_state": null
}
```

**reminder_due:**
```json
{
  "claim_id": "uuid",
  "statement": "Dentist appointment Monday",
  "valid_to": "2026-06-16T00:00:00Z"
}
```

---

## 4. Backend API

### 4.1 StructuredAPI Methods

```python
# Core CRUD
create_notification(priority, category, title, body, object_type, object_id,
                    activity_id, action_required, available_actions, action_payload,
                    source, session_id, expires_at) -> notification_id

# Queries
get_notifications(priority=None, category=None, unresolved_only=True,
                  unseen_only=False, limit=50, offset=0) -> list[dict]
get_notification_count(unresolved_only=True, action_required_only=True) -> int

# Actions
resolve_notification(notification_id, action_taken) -> dict  # executes action if needed
mark_seen(notification_ids: list) -> int  # returns count marked
bulk_resolve(notification_ids: list, action_taken: str) -> dict

# Sync
resolve_notifications_for_object(object_id, reason="resolved_externally") -> int
check_reminders_due(threshold_hours=24) -> int  # creates notifications, returns count

# Maintenance
prune_low_priority(keep=500) -> int  # deletes oldest resolved low-priority beyond cap
```

### 4.2 REST Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/pkb/memory/notifications` | GET | List (filters: priority, category, unresolved, unseen, limit, offset) |
| `/pkb/memory/notifications/count` | GET | Badge count (unseen + action_required, high/medium only) |
| `/pkb/memory/notifications/<id>/action` | POST | Take action: `{"action": "approve"}` |
| `/pkb/memory/notifications/bulk_action` | POST | `{"ids": [...], "action": "dismiss"}` |
| `/pkb/memory/notifications/mark_seen` | POST | `{"ids": [...]}` |
| `/pkb/memory/notifications/settings` | GET/PUT | Notification preferences |

Note: Routes use `/pkb/memory/notifications/*` prefix to avoid collision with existing `/pkb/notifications` lifecycle endpoint (Workstream F4: expire/dormant claims).

### 4.3 MCP Tools

| Tool | Purpose |
|------|---------|
| `pkb_list_notifications` | List with filters (priority, category, unresolved) |
| `pkb_resolve_notification` | Take action on a notification by ID |

---

## 5. Notification Emission Points

### 5.1 Tiered Routing (conversation_distillation.py, text_ingestion.py)

- **Confirm lane:** Create `high` / `confirm_required` notification. `action_payload` = full proposed action data. `action_required=1`.
- **Auto-save lane:** Create `medium` / `auto_save` notification after successful execution. `activity_id` = the log entry. `action_required=0`.
- **Skip lane:** No notification.

### 5.2 Modal Confirm (endpoints/pkb.py — execute_plan)

- User approves items via modal → create `low` / `claim_confirmed` notification per item.

### 5.3 MCP Writes (mcp_server/pkb.py)

- `pkb_add_claim` with provenance="mcp" → create `medium` / `mcp_write` notification.

### 5.4 Conflict Detection (structured_api.py — add_claim / edit_claim)

- When conflict_set is created/expanded → create `high` / `conflict_detected` notification.

### 5.5 Claim Expiry/Decay (on-request check)

- Claims with `valid_to` past and status changed → create `low` / `claim_deprecated` notification.

### 5.6 Reminder Due (on-request check)

- Claims with `claim_type='reminder'` and `valid_to` within `REMINDER_DUE_THRESHOLD_HOURS` → create `medium` / `reminder_due` if not already notified.

---

## 6. Data State Sync

### 6.1 Undo via activity log syncs notification

When `undo_activity(activity_id)` is called:
1. Find notification WHERE `activity_id = ?` AND `resolved_at IS NULL`
2. Set `action_taken = 'undone_externally'`, `resolved_at = now`

### 6.2 Claim delete/retract syncs notification

When a claim is retracted or deleted:
1. Find notifications WHERE `object_id = claim_id` AND `resolved_at IS NULL`
2. Set `action_taken = 'resolved_externally'`, `resolved_at = now`

### 6.3 Approve from notification (stale check)

When user clicks "approve" on a `confirm_required` notification:
1. Deserialize `action_payload`
2. Check for conflicts: query existing claims for semantic overlap (same as `_find_existing_matches`)
3. If new conflict found → reject the approve, update notification body with "conflict emerged since this was created", keep unresolved
4. If clean → execute `add_claim` / `edit_claim` with payload data, log to activity, resolve notification

### 6.4 Reject records to activity log

When user rejects a confirm-lane notification:
1. `log_activity(action="user_reject", facet="capture", object_type="notification", object_id=notification_id)`
2. Resolve notification with `action_taken='rejected'`

### 6.5 Modal confirm resolves pending notification

When user approves via the in-conversation memory-proposal-modal:
1. Emit `low`/`claim_confirmed` notification for the approved item.
2. Find and resolve any `confirm_required` notification with matching title (statement).
3. Set `action_taken='approved_via_modal'`.

This prevents dangling high-priority notifications when the user confirms via the modal instead of the notification panel.

---

## 7. UI Design

### 7.1 PKB Modal — Notifications Tab

- New tab in PKB modal tab bar: bell icon (`bi-bell-fill`) + badge count (unresolved high+medium with action_required)
- Badge: red dot with number, e.g. `🔔 3`
- Tab content: scrollable list of expandable notification cards

### 7.2 Notification Card (collapsed)

```
┌─────────────────────────────────────────────────────┐
│ 🔴 Confirm: "I'm allergic to shellfish"     2h ago  │
│    health • fact • conf 0.88                        │
│    [▼ Expand]                                       │
└─────────────────────────────────────────────────────┘
```

### 7.3 Notification Card (expanded)

```
┌─────────────────────────────────────────────────────┐
│ 🔴 Confirm: "I'm allergic to shellfish"     2h ago  │
│    health • fact • conf 0.88                        │
│                                                     │
│    Source: conversation distillation                 │
│    Derivation: stated                               │
│    Confidence aspects: [9, 8, 9, 9]                 │
│                                                     │
│    [✓ Approve]  [✗ Reject]  [— Dismiss]             │
└─────────────────────────────────────────────────────┘
```

### 7.4 Conflict Card (expanded)

```
┌─────────────────────────────────────────────────────┐
│ 🔴 Conflict Detected                       30m ago  │
│                                                     │
│    NEW: "I prefer tea"                              │
│    vs EXISTING: "I prefer coffee"                   │
│                                                     │
│    [Keep New]  [Keep Existing]  [Keep Both]         │
└─────────────────────────────────────────────────────┘
```

### 7.5 Tab Filters

- Quick filter pills at top: "Action Needed" | "Recent" | "All"
- "Action Needed" = unresolved + action_required (default view)
- "Recent" = last 50 regardless of state
- "All" = paginated full list

### 7.6 Bulk Actions

- Checkbox per card + toolbar: "Approve All" | "Dismiss All" | "Undo Session"
- "Undo Session" groups by session_id, undoes all auto-saves from that conversation

### 7.7 On-Open Behavior

- When PKB modal opens (any tab) → fire `GET /pkb/notifications/count` → update badge
- When Notifications tab activated → fire `GET /pkb/notifications` + `POST /mark_seen` for rendered items
- Also triggers `check_reminders_due()` on server side

---

## 8. Settings

Stored in `pkb_user_settings` (extend existing JSON blob):

```json
{
  "notification_preferences": {
    "badge_min_priority": "medium",
    "reminder_threshold_hours": 24,
    "emit_low_priority": true,
    "categories_muted": []
  }
}
```

Editable via `/pkb/notifications/settings` GET/PUT and in-panel gear icon.

---

## 9. Implementation Tasks

### Phase A — Backend (schema + CRUD + emission)

| # | Task | Deps |
|---|------|------|
| A1 | Schema v14: `pkb_notifications` table + migration | — |
| A2 | StructuredAPI: `create_notification`, `get_notifications`, `get_notification_count` | A1 |
| A3 | StructuredAPI: `resolve_notification` (with approve stale-check + execute), `mark_seen`, `bulk_resolve` | A2 |
| A4 | StructuredAPI: `resolve_notifications_for_object`, sync hook in `undo_activity` | A3 |
| A5 | StructuredAPI: `check_reminders_due`, `prune_low_priority` | A2 |
| A6 | Emit from tiered routing: confirm → high notif, auto-save → medium notif | A2 |
| A7 | Emit from modal confirm (execute_plan) → low notif | A2 |
| A8 | Emit from MCP writes → medium notif | A2 |
| A9 | Emit from conflict detection → high notif | A2 |
| A10 | Emit on claim retract/delete → resolve corresponding notifs | A4 |
| A11 | REST endpoints (6 routes) | A2, A3, A5 |
| A12 | MCP tools: `pkb_list_notifications`, `pkb_resolve_notification` | A11 |
| A13 | Tests: schema, CRUD, emission, sync, stale-check | A1–A12 |

### Phase B — UI

| # | Task | Deps |
|---|------|------|
| B1 | PKB modal: add notifications tab (bell icon + badge) | A11 |
| B2 | Notification card component (collapsed/expanded) | B1 |
| B3 | Conflict card variant (side-by-side) | B2 |
| B4 | Action buttons wired to REST (approve/reject/undo/dismiss/snooze) | B2 |
| B5 | Filter pills (Action Needed / Recent / All) | B1 |
| B6 | Bulk actions toolbar (checkboxes + Approve All / Dismiss All / Undo Session) | B4 |
| B7 | Mark-seen on render + badge update on modal open | B1 |
| B8 | Settings gear (reminder threshold, muted categories, badge priority) | A11 |

---

## 10. Migration Strategy

- Schema v14: `CREATE TABLE pkb_notifications` + indexes.
- No feature flag: the table is inert until emission code writes to it. Emission code is always-on but only creates notifications when tiered routing produces confirm/auto-save/skip decisions (which themselves are gated by `tiered_persistence_enabled`). Conflict/reminder/MCP notifications emit regardless — these are unconditionally useful.
- Low-priority cap: `prune_low_priority(keep=500)` called at end of `check_reminders_due()` and periodically from `get_notifications()` if count exceeds threshold.

---

## 11. Constants

```python
REMINDER_DUE_THRESHOLD_HOURS = 24  # configurable in notification_preferences
LOW_PRIORITY_CAP = 500
NOTIFICATION_CATEGORIES = [
    "confirm_required", "conflict_detected", "auto_save", "mcp_write",
    "reminder_due", "claim_confirmed", "claim_deprecated", "claim_enriched", "stm_promoted"
]
NOTIFICATION_PRIORITIES = ["high", "medium", "low"]
```

---

## 12. Future Extensions (not in scope)

- App-wide notification system that pulls from PKB notifications + other sources
- Email digest (daily summary of unresolved high/medium)
- Push notifications via existing `notification-manager.js` for high-priority
- Notification preferences per category with custom priority override
- Smart batching: group 5 auto-saves from one session into 1 expandable notification
