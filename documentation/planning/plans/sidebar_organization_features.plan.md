# Sidebar Organization Features: Archive, Time View, Message Pinning

**Status: DONE** (June 2026)

## Motivation and Background

The sidebar currently has Recent (top N by last_updated), Pinned (flagged conversations), and jsTree workspaces. As the conversation count grows (66+ currently), additional organization tools become necessary:

1. **Archiving** — hide old conversations without deleting them, reducing sidebar clutter
2. **Time View** — an alternative flat view grouped by time period (no workspace folders), for quick temporal navigation
3. **Message Pinning** — star important messages within a conversation for quick reference later

These build on the existing infrastructure: conversation metadata, workspace-manager.js rendering patterns, context menus, and localStorage state persistence.

### Existing Infrastructure Leveraged

- `Conversation` object — dill-pickled with attributes, `save_local()` persists changes
- `get_metadata()` — returns conversation fields for sidebar display
- `/list_conversation_by_user/<domain>` — returns all conversation metadata for domain
- `WorkspaceManager` — jsTree rendering, Recent/Pinned sections, context menu builders
- `localStorage` — per-user/domain state persistence for UI preferences
- `persistSectionState()` / `SectionHiddenDetails` table — section state persistence pattern
- `DoubtsClearing` table — existing example of pin/bookmark columns on a DB table

---

## Feature 1: Conversation Archiving

### Requirements

- R1: Conversations can be archived (hidden from sidebar by default) and unarchived.
- R2: The `/list_conversation_by_user/<domain>` endpoint excludes archived conversations unless `?include_archived=true` query param is passed.
- R3: The sidebar has a toggle (eye icon or similar) that switches between "hide archived" (default) and "show archived" modes.
- R4: When archived conversations are visible, they render with a dimmed/italic style to distinguish from active ones.
- R5: The conversation context menu shows "Archive" for active conversations. "Unarchive" is only shown when the "Show Archived" toggle is active.
- R6: Archived conversations are excluded from Recent and Pinned sections.
- R7: Archived conversations are still searchable via cross-conversation search (search doesn't filter by archive state).
- R8: The archive toggle state is persisted in `localStorage` (per user+domain).
- R9: When "Show Archived" is active, archived conversations appear in a separate "Archived" group at the bottom of the sidebar (not inline in their original workspace folder). This group is collapsible.

### Backend Changes

#### Conversation.py

Add `_archived` attribute:

```python
# In __init__ (after self._flag = None):
self._archived = False

# Property:
@property
def archived(self) -> bool:
    return getattr(self, "_archived", False)

@archived.setter
def archived(self, value: bool):
    self._archived = bool(value)
    self.save_local()
```

#### get_metadata()

Add `archived` field:
```python
return dict(
    ...,
    flag=self.flag,
    archived=self.archived,
    last_updated=...
)
```

#### endpoints/conversations.py

New endpoint:
```python
@conversations_bp.route("/archive_conversation/<conversation_id>", methods=["POST"])
def archive_conversation(conversation_id: str):
    # Toggle archived state
    conversation = get_conversation(conversation_id)
    conversation.archived = not conversation.archived
    return jsonify({"success": True, "archived": conversation.archived})
```

Modify `/list_conversation_by_user/<domain>`:
```python
include_archived = request.args.get("include_archived", "false").lower() == "true"
# In the filter:
conversations = [c for c in conversations if c is not None and c.domain == domain
                 and (include_archived or not c.archived) ...]
```

### Frontend Changes

#### interface.html

Add archive toggle button in sidebar toolbar (near the search button):
```html
<button id="toggle-archived-btn" class="btn btn-sm" title="Show/hide archived">
    <i class="fa fa-eye-slash"></i>
</button>
```

#### workspace-manager.js

1. New state: `this._showArchived = false` (restored from localStorage on init)
2. Toggle handler in `initEventHandlers()`:
   - Flip `_showArchived`, persist to localStorage
   - Update icon (eye / eye-slash)
   - Call `loadConversationsWithWorkspaces(false)` to reload
3. Pass `?include_archived=true` in AJAX call when `_showArchived` is true
4. In `renderRecentConversations()` and `renderPinnedConversations()`: filter out `conv.archived === true`
5. In `buildJsTreeData()`: add `.archived-conversation` class to archived nodes
6. In `buildConversationContextMenu()`: add "Archive"/"Unarchive" item

#### workspace-styles.css

```css
.archived-conversation > .jstree-anchor {
    opacity: 0.5;
    font-style: italic;
}
```

### Task Breakdown

1. Add `_archived` property to Conversation.py + include in `get_metadata()`
2. Add `POST /archive_conversation/<conversation_id>` endpoint
3. Modify `/list_conversation_by_user` to filter by `include_archived` param
4. Add archive toggle button to sidebar HTML
5. Add toggle handler + pass param in AJAX call
6. Filter archived from Recent/Pinned, add CSS class in jsTree
7. Add "Archive"/"Unarchive" to context menu
8. Verify + commit

---

## Feature 2: Time View (Smart Groups)

### Requirements

- R1: A toggle button in the sidebar header switches between Workspace View (default, current jsTree) and Time View.
- R2: In Time View, the jsTree workspace container is hidden. A flat grouped list replaces it.
- R3: Conversations are grouped into collapsible time categories:
  - **Today** — `last_updated` is today
  - **This Week** — `last_updated` within last 7 days (excluding today)
  - **This Month** — `last_updated` within last 30 days (excluding this week)
  - **This Quarter** — `last_updated` within last 90 days (excluding this month)
  - **Older** — everything else
- R4: Each time group is a collapsible section (chevron toggle, same pattern as Recent).
- R5: Conversations within each group are sorted by `last_updated` DESC, with flagged conversations floating to the top of each group.
- R6: Each conversation item uses the same rendering as Recent items (title, flag color border, click to open, right-click context menu).
- R7: Recent and Pinned sections remain visible above the time groups (they're independent of the view toggle).
- R8: The view toggle state is persisted in `localStorage` (per user+domain).
- R9: When archived conversations are hidden, they're also excluded from Time View.
- R10: No backend changes required — uses same data from `/list_conversation_by_user`.
- R11: Active conversation is highlighted in Time View (same as workspace view).
- R12: Switching from Time View back to Workspace View auto-expands and highlights the active conversation's workspace folder.

### Frontend Changes

#### interface.html

Add view toggle button next to search button:
```html
<button id="sidebar-view-toggle" class="btn btn-sm" title="Toggle time/workspace view">
    <i class="fa fa-clock-o"></i>
</button>
```

Add time view container (hidden by default):
```html
<div id="time-view-container" style="display: none; margin-top: 4px;">
    <!-- Populated by WorkspaceManager.renderTimeView() -->
</div>
```

#### workspace-manager.js

1. New state: `this._timeViewActive = false` (restored from localStorage)
2. Toggle handler:
   - Flip `_timeViewActive`, persist to localStorage
   - Toggle icon (clock ↔ folder)
   - Show/hide `#workspaces-container` vs `#time-view-container`
   - Call `renderTimeView()` when activating
3. New function `renderTimeView()`:

```javascript
renderTimeView: function () {
    var container = $('#time-view-container');
    container.empty();

    var conversations = this.conversations.filter(function (c) {
        return !c.archived;
    });

    var now = new Date();
    var todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var weekAgo = new Date(todayStart - 7 * 86400000);
    var monthAgo = new Date(todayStart - 30 * 86400000);
    var quarterAgo = new Date(todayStart - 90 * 86400000);

    var groups = [
        { label: 'Today', items: [] },
        { label: 'This Week', items: [] },
        { label: 'This Month', items: [] },
        { label: 'This Quarter', items: [] },
        { label: 'Older', items: [] }
    ];

    conversations.forEach(function (conv) {
        var updated = new Date(conv.last_updated);
        if (updated >= todayStart) groups[0].items.push(conv);
        else if (updated >= weekAgo) groups[1].items.push(conv);
        else if (updated >= monthAgo) groups[2].items.push(conv);
        else if (updated >= quarterAgo) groups[3].items.push(conv);
        else groups[4].items.push(conv);
    });

    // Render each non-empty group as collapsible section
    groups.forEach(function (group) {
        if (group.items.length === 0) return;
        // Build header + item list (same pattern as Recent)
        ...
    });
}
```

4. In `_processAndRenderData()`: after `renderPinnedConversations()`, call `renderTimeView()` if `_timeViewActive` is true.
5. Each item: same DOM structure as Recent items (class `recent-conversation-item`, flag border, click/contextmenu handlers).
6. Group collapse state: persisted per group label in localStorage key `timeViewCollapsed:<email>:<domain>:<label>`.

#### workspace-styles.css

```css
.time-group-header {
    padding: 3px 8px;
    cursor: pointer;
    user-select: none;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #888;
}
.time-group-header:hover {
    background: rgba(255, 255, 255, 0.04);
}
```

### Task Breakdown

1. Add view toggle button HTML + time view container
2. Add toggle handler with localStorage persistence
3. Implement `renderTimeView()` with time bucketing logic
4. Render conversation items (reuse Recent item pattern) with group headers
5. Add group collapse/expand with localStorage
6. Wire into `_processAndRenderData` render pipeline
7. Add CSS for time group headers
8. Verify + commit

---

## Feature 3: Message Pinning (Star)

### Requirements

- R1: Users can star/unstar individual **assistant** messages within a conversation.
- R2: Starred messages are persisted in a new DB table.
- R3: A "Starred Messages" button in the conversation toolbar opens a modal listing all starred messages for the current conversation.
- R4: Starred messages in the modal show a ~200 char preview with a "Go to message" link (scrolls to it in main chat) and a "View full" button (opens the existing markdown viewer used by "Edit Message").
- R5: Each assistant message in the main chat view shows a star icon (☆ unfilled / ★ filled) in its action row.
- R6: Clicking the star toggles pin state via API.
- R7: The pinned messages modal allows unstarring and navigating to messages.
- R8: Max pinned messages per conversation: no hard limit (UI scrolls).
- R9: When a message is edited or regenerated, the pin is kept (message_id stays the same).

### Backend Changes

#### database/connection.py

New table:
```sql
CREATE TABLE IF NOT EXISTS PinnedMessages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    user_email TEXT NOT NULL,
    pinned_at TEXT NOT NULL,
    UNIQUE(conversation_id, message_id)
);
```

#### database/pinned_messages.py (new file)

```python
def pin_message(conversation_id, message_id, user_email, users_dir, logger):
    """Insert or ignore a pinned message."""

def unpin_message(conversation_id, message_id, users_dir, logger):
    """Delete a pinned message record."""

def get_pinned_messages(conversation_id, users_dir, logger):
    """Return list of {message_id, pinned_at} for conversation."""

def is_message_pinned(conversation_id, message_id, users_dir, logger):
    """Check if a specific message is pinned."""
```

#### endpoints/conversations.py (or new endpoints/pinned_messages.py)

```python
@bp.route("/pin_message/<conversation_id>/<message_id>", methods=["POST"])
def pin_message_route(conversation_id, message_id):
    """Toggle pin state for a message. Returns {pinned: bool}."""

@bp.route("/get_pinned_messages/<conversation_id>", methods=["GET"])
def get_pinned_messages_route(conversation_id):
    """Return {pinned_message_ids: [...]} for the conversation."""
```

### Frontend Changes

#### interface.html

Add toolbar button (near existing conversation toolbar buttons):
```html
<button id="pinned-messages-btn" class="btn btn-sm" title="Starred Messages">
    <i class="fa fa-star"></i>
    <span id="pinned-messages-count" class="badge badge-sm" style="display:none;"></span>
</button>
```

Add modal for pinned messages list:
```html
<div class="modal fade" id="pinned-messages-modal" ...>
    <div class="modal-body" id="pinned-messages-list">
        <!-- Rendered pinned message cards -->
    </div>
</div>
```

#### interface/common.js (or new pinned-messages.js)

1. On conversation load (`setActiveConversation` flow): fetch `GET /get_pinned_messages/<conv_id>`, store IDs in `window.pinnedMessageIds = new Set([...])`
2. In message rendering (`addMessage` / `renderMessages`): for **assistant** messages, if message_id is in `pinnedMessageIds`, add `.message-pinned` class and fill star icon
3. Star button click handler (assistant cards only):
   - Call `POST /pin_message/<conv_id>/<msg_id>`
   - Toggle star fill + update `pinnedMessageIds` set
4. Toolbar button click: open modal, fetch pinned messages, render each as:
   - ~200 char text preview (stripped markdown)
   - "Go to message" link (scrolls main chat to that message)
   - "View full" button (opens existing markdown viewer modal used by Edit Message)
   - Unstar button
5. Badge count on toolbar button

#### interface/common-chat.js

Add star icon to the **assistant** message action row (alongside copy, edit, regenerate):
```javascript
// In the assistant message card builder, add to action buttons:
var starIcon = isPinned ? 'fa-star' : 'fa-star-o';
var starBtn = '<button class="btn btn-sm msg-pin-btn" data-message-id="' + msgId + '" title="Star message"><i class="fa ' + starIcon + '"></i></button>';
```

#### workspace-styles.css

```css
.msg-pin-btn .fa-star { color: #ffc107; }
.message-pinned { border-left: 2px solid #ffc107; }
```

### Task Breakdown

1. Create `PinnedMessages` table in `database/connection.py`
2. Create `database/pinned_messages.py` with CRUD functions
3. Add `POST /pin_message` and `GET /get_pinned_messages` endpoints
4. Add star icon to message action row in chat rendering
5. Fetch pinned IDs on conversation load, highlight pinned messages
6. Add star toggle click handler (API call + UI update)
7. Add toolbar button + modal with pinned message list
8. Add CSS for star color and pinned message border
9. Verify + commit

---

## Implementation Order

1. **Archiving** (8 tasks) — touches backend + frontend, simplest overall
2. **Time View** (8 tasks) — frontend only, builds on workspace-manager patterns
3. **Message Pinning** (9 tasks) — new DB table, most complex

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Archive storage | Attribute on Conversation object | Consistent with `flag`, persisted via dill, no migration |
| Archive API filtering | Query param on existing endpoint | No new list endpoint needed |
| Archive toggle | Simple toggle, but "Unarchive" only visible when Show Archived is active | Prevents accidental unarchive |
| Archived display | Separate "Archived" group at bottom (not inline in workspace folders) | Clear visual separation |
| Time view data source | Same `this.conversations` array | No extra API call, already sorted |
| Time view categories | 5 buckets (Today/Week/Month/Quarter/Older) | Covers natural lookup patterns |
| Time view flagged sort | Flagged float to top within each time group | Consistent with workspace behavior |
| Time view highlight | Active conversation highlighted | Same as workspace view |
| Time→Workspace switch | Auto-expand and highlight in workspace tree | Consistent with Recent/Pinned behavior |
| Message pin storage | New SQLite table (not on Conversation object) | Many-to-many, queryable, no pickle bloat |
| Message pin on edit/regen | Keep pin on new version | Message ID stays same, pin persists |
| Pinned messages display | Modal with ~200 char preview + "Go to message" link + full view via markdown viewer | Avoids layout disruption, handles long messages |
| Pin eligibility | Assistant messages only | Those contain the actual answers |
| Star icon location | Message action row (assistant cards only) | Consistent with existing copy/edit/regen buttons |

## Files Modified (estimated)

| File | Features |
|------|----------|
| `Conversation.py` | Archive (property) |
| `endpoints/conversations.py` | Archive (endpoint + filter) |
| `database/connection.py` | Message Pin (table) |
| `database/pinned_messages.py` | Message Pin (new file) |
| `endpoints/pinned_messages.py` | Message Pin (new file) |
| `interface/interface.html` | All three (buttons, containers, modal) |
| `interface/workspace-manager.js` | Archive + Time View |
| `interface/common.js` or `common-chat.js` | Message Pin (star in action row, modal) |
| `interface/workspace-styles.css` | All three (CSS) |

## Implementation Notes (completed)

### Commits
- `679164da` — Conversation.py `archived` property + interface.html sidebar buttons/containers
- `cab07adf` — Archive frontend: toggle, rendering, context menu, CSS
- `1033e285` — Time View: `renderTimeView()`, CSS
- `7eebfaec` — Message Pinning: full stack (DB table, CRUD, endpoints, star icon, modal)
- `ef8e6367` — Bug fixes: decorator names, preview field, missing helper function

### Design Decisions Made During Implementation
- **Auto-archival**: Chose Option C (auto-collapse "Older" group in Time View) over backend auto-archiving — safer, no data changes
- **Pin endpoint location**: Added to `endpoints/conversations.py` instead of a new file — simpler, follows existing pattern
- **Context menu for archived**: `_showContextMenuAtPosition` helper extracts common positioning logic used by Archived section and Time View
- **Archived in jsTree**: When "Show Archived" active, archived conversations appear in their workspace folders with dimmed/italic styling AND in the separate Archived group at bottom

### Related: Smart Auto-Archival
Full-featured auto-archival system built on top of the manual archive infrastructure above. See `documentation/planning/plans/smart_auto_archival.plan.md` for design, Q&A decisions, and implementation details.
