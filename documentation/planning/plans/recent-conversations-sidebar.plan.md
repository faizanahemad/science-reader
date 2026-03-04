# Plan: Recent Conversations Sidebar Section

## Motivation & Background

### The Problem

The workspace sidebar organizes conversations into hierarchical folder-based workspaces using jsTree. This is great for long-term organization — grouping conversations by project, topic, or priority. But the folder structure creates friction for the most common interaction pattern: **resuming a conversation you were just working on**.

Consider a user with 5 workspaces and 40+ conversations. They switch between 3-4 active conversations throughout the day. Each switch requires:
1. Remembering which workspace the conversation is in.
2. Expanding that workspace folder (if collapsed).
3. Scanning the list to find the right conversation.

This is 2-3 clicks/scans per switch. For the most frequent operation in the app, that's too much friction.

### The Solution

A dedicated "Recent" section at the top of the sidebar — a flat, chronologically-ordered list of the N most recently active conversations, regardless of which workspace they live in. This gives instant one-click access to conversations the user is actively working with.

**Analogy**: VS Code's "Recently Opened" in the File menu, or the "Recent" section in Finder/Explorer. Every file manager has this — because hierarchical organization and temporal access are complementary, not competing.

### Why No Backend Changes

The front-end already loads all conversations sorted by `last_updated` DESC into `WorkspaceManager.conversations` (populated by `GET /list_conversation_by_user/{domain}` → `_processAndRenderData()`). The Recent section just slices the first N items from this already-sorted array. No new API endpoint, no new database query, no additional network request.

## Goals

### Primary Goals

1. **Reduce conversation switching friction** — from 2-3 clicks (find workspace → expand → find conversation) to 1 click (click in Recent).
2. **Cross-workspace visibility** — surface the most recently active conversations regardless of workspace, giving a temporal view that complements the organizational view.
3. **Visual consistency** — the Recent section should feel like a natural part of the existing sidebar, not a bolted-on widget. Same fonts, colors, icons, hover states, selection highlight, and context menu as the jsTree nodes.

### Functional Goals

4. Collapsible "Recent" section header above the jsTree workspace folders, expanded by default on first visit.
5. Show the last N conversations (configurable constant, default 10) sorted by `last_updated` descending.
6. Conversations appear in both the Recent section and their workspace folder (duplicates are intentional — removing from the tree would be confusing).
7. Clicking a recent item switches conversations and highlights the corresponding node in the jsTree below (full cross-highlight sync).
8. Right-click context menu on recent items — same menu as jsTree conversation nodes (delete, move, clone, flag, etc.).
9. Collapse/expand state persisted to `localStorage` (scoped by user+domain).
10. Active conversation highlighted in both Recent list and jsTree simultaneously.
11. Flag indicators (colored left border) on recent items, matching jsTree flag styling.
12. Count badge on header — shown only when displaying fewer than the max (informational, not noise).

### Non-Functional Goals

13. No backend changes — pure front-end feature using existing data.
14. No new dependencies — jQuery, Font Awesome, and vakata (bundled with jsTree) are sufficient.
15. Mobile-correct — clicking a recent item closes the sidebar on mobile (≤768px), same as jsTree clicks.

## Requirements Checklist

- [ ] Collapsible section header ("Recent") with count badge (badge shown only when count < max)
- [ ] Flat list of recent conversations (plain DOM, not jsTree)
- [ ] Click → `ConversationManager.setActiveConversation(id)` (which internally highlights in jsTree via `highLightActiveConversation()`)
- [ ] Right-click / long-press → same context menu as jsTree conversation nodes (reuse `buildConversationContextMenu()` via fake node)
- [ ] No triple-dot (⋮) menu button on items (right-click / long-press only — keep items clean)
- [ ] Active conversation visually highlighted in both Recent and jsTree simultaneously
- [ ] Collapse/expand persisted to localStorage (scoped by user+domain)
- [ ] Configurable count (stored as a constant `_recentSectionCount = 10`, easy to change)
- [ ] Section refreshes automatically on CRUD operations (piggyback on existing `_processAndRenderData` calls)
- [ ] Mobile: clicking a recent item closes the sidebar (≤768px, same behavior as jsTree clicks)
- [ ] Flag indicators on recent items (colored left border, matching jsTree flag colors)
- [ ] Title-only display, title text HTML-escaped to prevent XSS
- [ ] No separate header for the workspace tree section ("Explorer" toolbar stays as-is)

## Non-Goals

- No new backend API endpoint (use existing client-side data)
- No drag-and-drop from Recent to workspace folders (future enhancement)
- No search/filter within the Recent section
- No relative timestamps (title-only display)
- No triple-dot menu button (keep items visually clean; context menu via right-click/long-press only)
- No live title update when conversation title changes mid-session (updates on next full reload, same as jsTree)
- No "See all" or "Show more" link (fixed count, configurable as constant)
## Architecture Overview

### Data Source

`WorkspaceManager.conversations` is an array of conversation metadata objects, already sorted by `last_updated` DESC in `_processAndRenderData()` (line 221 of workspace-manager.js). Each object has:

```javascript
{
    conversation_id: "...",
    title: "...",
    flag: "red" | "blue" | ... | "none" | null,
    last_updated: "YYYY-MM-DD HH:MM:SS",
    workspace_id: "...",
    workspace_name: "...",
    conversation_friendly_id: "...",
    // ... other fields
}
```

We slice the first N items for the Recent section.

### Rendering Strategy

**Plain DOM** (not jsTree). The Recent section is a flat list — using jsTree for it would be unnecessary complexity. We render `<div>` items styled to match jsTree conversation nodes visually (same font size, padding, icon, flag colors, hover/selection styles).

### Context Menu Reuse

The existing `WorkspaceManager.buildConversationContextMenu(node)` expects a jsTree node object with `node.id` (format `cv_{id}`), `node.li_attr['data-conversation-friendly-id']`, etc. For the Recent section, we construct a "fake node" object with the same shape and pass it to the same method. The vakata context menu system renders identically.

## Files to Modify

| # | File | Change Type | Description |
|---|------|-------------|-------------|
| 1 | `interface/interface.html` | Edit | Add Recent section HTML between `.sidebar-toolbar` and `#workspaces-container` |
| 2 | `interface/workspace-manager.js` | Edit | Add `renderRecentConversations()`, `_recentSectionCount` constant, collapse/expand handlers, context menu integration |
| 3 | `interface/workspace-styles.css` | Edit | Add CSS for Recent section (header, list items, highlight, flags) |

No backend files changed. No new files created.

## Detailed Implementation

### Task 1: HTML Structure (`interface/interface.html`)

**Location**: Between line 261 (end of `.sidebar-toolbar`) and line 263 (start of `<!-- jsTree Container -->` comment).

**Insert the following HTML:**

```html
<!-- Recent Conversations Section -->
<div id="recent-conversations-section" style="margin-top: 4px;">
    <div class="recent-section-header d-flex justify-content-between align-items-center" 
         id="recent-section-toggle" 
         title="Toggle Recent Conversations">
        <span class="recent-section-title">
            <i class="fa fa-chevron-down recent-chevron"></i>
            Recent
            <span class="recent-count-badge" id="recent-count-badge"></span>
        </span>
    </div>
    <div id="recent-conversations-list">
        <!-- Populated by WorkspaceManager.renderRecentConversations() -->
    </div>
</div>
```

**Design notes:**
- The header has a chevron icon that rotates on collapse (CSS transform).
- `recent-count-badge` shows the count (e.g., "(10)") — same pattern as workspace node count.
- `recent-conversations-list` is the container for dynamically rendered items.
- No Bootstrap collapse component — we use simple jQuery `slideToggle()` for smoother UX and to avoid Bootstrap collapse's accessibility overhead on a sidebar section.

**Risks:** None. This is pure HTML insertion between two existing elements. No existing IDs/classes conflict.

### Task 2: JavaScript (`interface/workspace-manager.js`)

#### 2a. New Constants & State Properties

Add to the `WorkspaceManager` object (near the top, after `_contextMenuOpenedAt: 0`):

```javascript
_recentSectionCount: 10,             // Default number of recent conversations to show
_recentSectionCollapsed: false,      // In-memory collapse state
_recentSectionLocalStorageKey: 'recentSectionCollapsed',  // localStorage key base
```

**Alternatives & Risks:**
- Could make count user-configurable via a settings UI. For now, a constant is sufficient — easy to expose later.
- localStorage key needs to be scoped by user+domain (like the active conversation key). We'll compute it dynamically.

#### 2b. `getRecentSectionStorageKey()` Method

```javascript
getRecentSectionStorageKey: function () {
    var email = (typeof userDetails !== 'undefined' && userDetails.email) ? userDetails.email : 'unknown';
    var domain = (typeof currentDomain !== 'undefined' && currentDomain['domain']) ? currentDomain['domain'] : 'unknown';
    return 'recentSectionCollapsed:' + email + ':' + domain;
}
```

Follows the same pattern as the existing `lastActiveConversationId:{email}:{domain}` key.

#### 2c. `renderRecentConversations()` Method

This is the core new method. Pseudo-code:

```javascript
renderRecentConversations: function () {
    var self = this;
    var container = $('#recent-conversations-list');
    var badge = $('#recent-count-badge');
    container.empty();

    // 1. Slice recent conversations
    var recentConversations = this.conversations.slice(0, this._recentSectionCount);
    
    // 2. Update badge (only show when count < max — otherwise it's noise)
    if (recentConversations.length > 0 && recentConversations.length < self._recentSectionCount) {
        badge.text('(' + recentConversations.length + ')');
    } else {
        badge.text('');
    }

    // 3. If no conversations, show nothing (or a subtle placeholder)
    if (recentConversations.length === 0) {
        container.append('<div class="recent-empty-message">No conversations yet</div>');
        return;
    }

    // 4. Get current active conversation for highlighting
    var activeConvId = (ConversationManager.getActiveConversation && ConversationManager.getActiveConversation()) || null;

    // 5. Render each item
    recentConversations.forEach(function (conv) {
        var title = conv.title ? conv.title.trim() : '(untitled)';
        var isActive = activeConvId && String(activeConvId) === String(conv.conversation_id);
        var flagClass = (conv.flag && conv.flag !== 'none') ? ' recent-flag-' + conv.flag : '';

        // Build item using jQuery to avoid XSS via string concatenation in attributes.
        // The display text is escaped via .text(), and data-* attributes are set
        // via .attr()/.data() which handle escaping correctly.
        var item = $('<div class="recent-conversation-item"></div>');
        if (isActive) item.addClass('recent-active');
        if (flagClass) item.addClass(flagClass.trim());
        item.attr({
            'data-conversation-id': conv.conversation_id,
            'data-conversation-friendly-id': conv.conversation_friendly_id || '',
            'data-flag': conv.flag || 'none',
            'title': conv.title || ''
        });
        item.append('<i class="fa fa-comment-o recent-conv-icon"></i>');
        item.append($('<span class="recent-conv-title"></span>').text(title));

        // Click handler — switch conversation
        item.on('click', function (e) {
            if (e.which === 2 || e.metaKey || e.ctrlKey) return; // Allow middle-click / cmd-click
            e.preventDefault();
            e.stopPropagation();

            var convId = $(this).data('conversation-id');
            if (!convId) return;

            // Skip if already active
            var currentActive = ConversationManager.getActiveConversation();
            if (currentActive && String(currentActive) === String(convId)) return;

            // Mobile: close sidebar
            try {
                if (window.matchMedia && window.matchMedia('(max-width: 768px)').matches) {
                    var sidebar = $('#chat-assistant-sidebar');
                    var contentCol = $('#chat-assistant');
                    if (sidebar.length && contentCol.length && !sidebar.hasClass('d-none')) {
                        sidebar.addClass('d-none');
                        contentCol.removeClass('col-md-10').addClass('col-md-12');
                        $(window).trigger('resize');
                    }
                }
            } catch (_e) {}

            // Switch conversation.
            // IMPORTANT: Do NOT call WorkspaceManager.highlightActiveConversation() separately.
            // setActiveConversation() internally calls highLightActiveConversation() (common-chat.js:740),
            // which already calls WorkspaceManager.highlightActiveConversation(). Calling it again
            // would cause double-highlight processing. This matches the jsTree click handler pattern
            // (workspace-manager.js:478) which also only calls setActiveConversation().
            ConversationManager.setActiveConversation(convId);
        });

        // Right-click handler — show context menu (reuse workspace-manager's)
        item.on('contextmenu', function (e) {
            e.preventDefault();
            e.stopPropagation();
            var convId = $(this).data('conversation-id');
            if (!convId) return;

            // Build a fake jsTree-like node object for buildConversationContextMenu()
            var fakeNode = {
                id: 'cv_' + convId,
                li_attr: {
                    'data-conversation-id': convId,
                    'data-conversation-friendly-id': $(this).data('conversation-friendly-id') || '',
                    'data-flag': $(this).data('flag') || 'none'
                }
            };

            var items = self.buildConversationContextMenu(fakeNode);
            var vakataItems = self._convertToVakataItems(items, fakeNode);
            $.vakata.context.hide();

            // Position menu (same logic as showNodeContextMenu)
            var sidebar = $('#chat-assistant-sidebar');
            var sidebarRight = 0;
            if (sidebar.length) {
                var sidebarOffset = sidebar.offset();
                sidebarRight = sidebarOffset.left + sidebar.outerWidth();
            }
            var menuX = Math.max(e.pageX, sidebarRight + 2);
            var menuY = e.pageY;

            var posEl = $('<span>').css({
                position: 'absolute', left: menuX + 'px', top: menuY + 'px',
                width: '1px', height: '1px'
            });
            $('body').append(posEl);
            $.vakata.context.show(posEl, { x: menuX, y: menuY }, vakataItems);
            setTimeout(function () { posEl.remove(); }, 200);
        });

        container.append(item);
    });

    // 6. Restore collapse state
    var collapsed = false;
    try { collapsed = localStorage.getItem(self.getRecentSectionStorageKey()) === 'true'; } catch (_e) {}
    self._recentSectionCollapsed = collapsed;
    if (collapsed) {
        container.hide();
        $('#recent-section-toggle .recent-chevron').addClass('collapsed');
    } else {
        container.show();
        $('#recent-section-toggle .recent-chevron').removeClass('collapsed');
    }
}
```

**Key design decisions:**
- All DOM construction uses jQuery's `.attr()` and `.text()` methods for XSS safety. No raw string concatenation for user-provided values (title, conversation_id, friendly_id). The display text uses `.text(title)` which auto-escapes, and attributes use `.attr()` which handles quoting.
- The "fake node" approach lets us reuse `buildConversationContextMenu()` without modification. This is the most maintainable approach — any future context menu items automatically appear in both places.
- Mobile sidebar close logic is duplicated from the jsTree handler. Could be extracted to a shared helper, but for a plan doc we keep it explicit.
- **Click handler only calls `setActiveConversation()`** — NOT `highlightActiveConversation()` separately. This matches the jsTree click handler pattern (workspace-manager.js:478). `setActiveConversation()` internally calls `highLightActiveConversation()` (common-chat.js:740) which calls `WorkspaceManager.highlightActiveConversation()`. Calling highlight separately would cause double processing.
- Badge only shows count when it's less than the max (10). If showing all 10, the badge is hidden — it's informational only when the count is unexpected.

**Alternatives considered:**
- *Use jsTree for the Recent section too*: Rejected — would require a second jsTree instance, separate state management, and adds complexity for a flat list.
- *Use the actual jsTree node for context menu*: Rejected — the recent conversation might not be visible in the tree (parent workspace collapsed), so `tree.get_node('cv_' + id)` might not have a rendered DOM element. The fake node approach is safer.
- *Add triple-dot button on each item*: Rejected — adds visual clutter in a compact list. Right-click and long-press provide the same access. The triple-dot is more important in the dense jsTree where right-click discovery is less obvious.

#### 2d. Collapse/Expand Toggle Handler

Add to `init()` method (after `this.setupToolbarHandlers()`):

```javascript
// Recent section collapse/expand
$('#recent-section-toggle').off('click').on('click', function () {
    var list = $('#recent-conversations-list');
    var chevron = $(this).find('.recent-chevron');
    
    if (list.is(':visible')) {
        list.slideUp(150);
        chevron.addClass('collapsed');
        self._recentSectionCollapsed = true;
    } else {
        list.slideDown(150);
        chevron.removeClass('collapsed');
        self._recentSectionCollapsed = false;
    }
    
    try {
        localStorage.setItem(self.getRecentSectionStorageKey(), String(self._recentSectionCollapsed));
    } catch (_e) {}
});
```

**Risk:** `slideUp`/`slideDown` animations could conflict with the scrollable sidebar. Tested pattern — jQuery slide animations respect `overflow: hidden` on the animated element. The sidebar's `overflow-y: auto` on the parent won't interfere.

#### 2e. Integration Point — Call from `_processAndRenderData()`

At the end of `_processAndRenderData()` (after `this.renderTree(convByWs);` on line 255):

```javascript
this.renderRecentConversations();
```

This ensures the Recent section is refreshed every time the workspace tree is refreshed — after load, after CRUD operations, after conversation creation/deletion.

#### 2f. Active Highlight Update

The Recent section needs to update its active highlight when the user switches conversations. Two integration points:

1. **In `highlightActiveConversation()`** (after the tree selection on line 1077): Add a call to update the Recent section highlight:

```javascript
// Update recent section highlight
$('#recent-conversations-list .recent-conversation-item').removeClass('recent-active');
$('#recent-conversations-list .recent-conversation-item[data-conversation-id="' + conversationId + '"]').addClass('recent-active');
```

2. **In the `select_node.jstree` handler** (line 478, after `ConversationManager.setActiveConversation`): The above `highlightActiveConversation` call already handles this since it's called from `setActiveConversation`.

**Risk:** If `highlightActiveConversation` is called before the tree is ready (`_jsTreeReady === false`), the Recent section highlight should still work because the Recent section is pure DOM, not jsTree. Need to add the Recent highlight update even when the tree highlight is queued as pending. Add the Recent highlight code at the top of `highlightActiveConversation()`, before the `_jsTreeReady` check.

#### 2g. Handling the "Configurable count" setting

For now, `_recentSectionCount` is a constant (10). To make it truly configurable in the future:
- Add a `localStorage` key `recentSectionCount:{email}:{domain}`
- Read it in `init()` 
- Add a small gear icon or setting in the Recent header

This is out of scope for the initial implementation but the architecture supports it trivially.

### Task 3: CSS Styles (`interface/workspace-styles.css`)

Add new section at the end of the file (or after the sidebar-toolbar section):

```css
/* ---- Recent Conversations Section ---- */

#recent-conversations-section {
    border-bottom: 1px solid #333;
    margin-bottom: 2px;
    padding-bottom: 2px;
}

/* Section header — clickable, matches sidebar-toolbar feel */
.recent-section-header {
    padding: 3px 8px;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
}

.recent-section-header:hover {
    background: rgba(255, 255, 255, 0.04);
}

.recent-section-title {
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #888;
    font-weight: 400;
}

.recent-chevron {
    font-size: 0.6rem;
    margin-right: 4px;
    transition: transform 0.15s ease;
    display: inline-block;
}

.recent-chevron.collapsed {
    transform: rotate(-90deg);
}

.recent-count-badge {
    font-size: 0.7rem;
    color: #666;
    margin-left: 4px;
    font-weight: normal;
}

/* Conversation items — match jsTree node styling */
.recent-conversation-item {
    display: flex;
    align-items: flex-start;
    padding: 2px 8px 2px 12px;
    cursor: pointer;
    font-size: 0.76rem;
    line-height: 17px;
    color: #ccc;
    position: relative;
    word-break: break-word;
    overflow-wrap: break-word;
}

.recent-conversation-item:hover {
    background: rgba(255, 255, 255, 0.06);
}

.recent-conversation-item.recent-active {
    background: rgba(0, 120, 212, 0.35);
    color: #fff;
}

.recent-conv-icon {
    font-size: 0.75rem;
    color: #75beff;
    margin-right: 4px;
    margin-top: 2px;
    flex-shrink: 0;
}

.recent-conv-title {
    overflow: hidden;
    white-space: normal;
    word-break: break-word;
}

/* Flag indicators — match jsTree flag colors */
.recent-flag-red    { border-left: 3px solid #dc3545; padding-left: 9px; }
.recent-flag-blue   { border-left: 3px solid #007bff; padding-left: 9px; }
.recent-flag-green  { border-left: 3px solid #28a745; padding-left: 9px; }
.recent-flag-yellow { border-left: 3px solid #ffc107; padding-left: 9px; }
.recent-flag-orange { border-left: 3px solid #fd7e14; padding-left: 9px; }
.recent-flag-purple { border-left: 3px solid #6f42c1; padding-left: 9px; }

/* Empty state */
.recent-empty-message {
    font-size: 0.73rem;
    color: #555;
    padding: 4px 12px;
    font-style: italic;
}
```

**Design notes:**
- Font sizes (`0.76rem`, `0.75rem`) exactly match jsTree conversation node styling.
- Active background (`rgba(0, 120, 212, 0.35)`) matches `.jstree-wholerow-clicked`.
- Hover background (`rgba(255, 255, 255, 0.06)`) matches `.jstree-wholerow-hovered`.
- Icon color `#75beff` matches `.conv-node > .jstree-anchor > .jstree-themeicon`.
- Flag colors match the jsTree flag indicator colors from the existing CSS.
- `border-bottom: 1px solid #333` on the section creates a subtle visual separator between Recent and the workspace tree.
- Chevron rotation uses CSS `transform` with a transition for smooth animation.

**Risks:** 
- Specificity conflicts with jsTree styles: None expected — all classes are prefixed with `recent-` which don't exist in jsTree.
- Width overflow: Items use `word-break: break-word` matching the jsTree approach. Long titles will wrap rather than overflow.

## Implementation Order (Milestones)

### Milestone 1: Static HTML + CSS (no functionality)
1. Add HTML to `interface.html` (Task 1)
2. Add CSS to `workspace-styles.css` (Task 3)
3. **Verify**: Load the page, confirm the empty "Recent" header renders correctly with proper styling, chevron visible, no layout breakage.

### Milestone 2: Render recent conversations
4. Add `_recentSectionCount`, `getRecentSectionStorageKey()` to `WorkspaceManager` (Task 2a, 2b)
5. Add `renderRecentConversations()` method (Task 2c)
6. Call `renderRecentConversations()` from `_processAndRenderData()` (Task 2e)
7. **Verify**: Conversations appear in Recent section, titles display correctly, flags show, active conversation is highlighted.

### Milestone 3: Interaction
8. Add click handler on items — conversation switching + tree highlight (already in Task 2c)
9. Add collapse/expand toggle handler (Task 2d) — wire in `init()`
10. **Verify**: Click switches conversation and highlights in tree. Collapse/expand works. Mobile sidebar closes on click.

### Milestone 4: Context menu
11. Add right-click handler with fake node construction (already in Task 2c)
12. **Verify**: Right-click shows same menu as jsTree nodes. All menu actions work (delete, move, flag, clone, etc.) and the Recent section refreshes after CRUD operations.

### Milestone 5: Highlight sync
13. Add Recent highlight update in `highlightActiveConversation()` (Task 2f)
14. **Verify**: Switching conversations via jsTree also updates the Recent section highlight. Switching via Recent also updates jsTree highlight.

## Possible Challenges

1. **Context menu actions that reload the tree**: After operations like Delete, Move, Clone, the tree reloads via `loadConversationsWithWorkspaces(false)`, which calls `_processAndRenderData()`, which calls `renderRecentConversations()`. This should naturally refresh the Recent section. **Mitigation**: No extra work needed — the existing reload flow covers it.

2. **Conversation title changes**: If a conversation's title is updated (e.g., auto-generated after first message), the Recent section shows the stale title until the next `loadConversationsWithWorkspaces()` call. **Mitigation**: Acceptable — same behavior as the jsTree currently. Could add a targeted update later.

3. **Performance with many conversations**: `WorkspaceManager.conversations` can be large (hundreds). But `renderRecentConversations()` only renders N items (default 10), so DOM cost is trivial. The `.slice(0, N)` operation is O(1) on the sorted array.

4. **Fake node for context menu**: The `buildConversationContextMenu()` method accesses `node.id` and `node.li_attr`. If any future context menu item accesses other jsTree node properties (e.g., `node.parent`, `node.state`), the fake node would need updating. **Mitigation**: Review `buildConversationContextMenu()` — currently only uses `node.id` and `node.li_attr`, which the fake node provides. If new properties are needed later, they're easy to add.

5. **CSS specificity**: The Recent section is outside `#workspaces-container`, so none of the jsTree CSS rules (which target `#workspaces-container` descendants) will accidentally apply. This is a feature, not a bug — it keeps the styles isolated.

## Testing Notes

- Test with 0 conversations (empty state message should show)
- Test with < N conversations (should show all, badge shows actual count)
- Test with > N conversations (should show exactly N)
- Test collapse/expand persistence (collapse, reload page, should stay collapsed)
- Test context menu: delete, move, clone, flag — all should work and refresh the section
- Test mobile: click should close sidebar
- Test conversation switching from Recent → verify jsTree highlights correctly
- Test conversation switching from jsTree → verify Recent highlights correctly
- Test after creating new conversation → should appear at top of Recent
- Test after deleting active conversation → should disappear from Recent, next conversation activates

## UX Decisions (Confirmed)

All decisions below were explicitly confirmed during planning.

| Question | Decision | Rationale |
|----------|----------|-----------|
| How many recent conversations? | Configurable constant, default 10 | Easy to change later; 10 covers most active working sets |
| Duplicates in tree? | Yes, same conversation in Recent AND workspace folder | Removing from tree would be confusing — "where did my conversation go?" |
| Cross-highlight? | Yes, clicking Recent highlights in jsTree too | Full visual sync, consistent with single-source-of-truth selection |
| Default state? | Expanded by default, persisted to localStorage | Users should see recent conversations immediately on first visit |
| Item display? | Title only, flag left border | Compact — matches jsTree node style exactly |
| Context menu? | Right-click/long-press, reuse same menu as jsTree nodes | Full feature parity without visual clutter |
| Triple-dot button? | No | Keeps items clean. Right-click/long-press sufficient for power feature |
| Section header text? | "Recent" (not "Recent Conversations") | Sidebar is narrow (~238px); shorter is better |
| Workspace tree header? | No separate header (keep "Explorer" toolbar as-is) | Avoids vertical overhead; tree is the default content |
| Count badge? | Show only when count < max | Badge is informational; "(10)" when always 10 is noise |
| Live title updates? | No — updates on next full reload | Same behavior as jsTree; no extra complexity |

## Review Findings (Bugs Caught in Plan Review)

### Bug 1: Double-highlight in click handler (FIXED)

**Original plan** had the click handler calling:
```javascript
ConversationManager.setActiveConversation(convId);
WorkspaceManager.highlightActiveConversation(convId);  // BUG: redundant
```

**The problem**: `setActiveConversation()` (common-chat.js:740) internally calls `highLightActiveConversation(conversationId)` (common-chat.js:1990), which already calls `WorkspaceManager.highlightActiveConversation(conversationId)` (common-chat.js:1993). Adding a separate `highlightActiveConversation()` call causes double processing.

**Evidence**: The existing jsTree click handler (workspace-manager.js:478) only calls `ConversationManager.setActiveConversation(conversationId)` — it does NOT separately call highlight. Our Recent click handler should match this pattern.

**Fix**: Removed the redundant `WorkspaceManager.highlightActiveConversation(convId)` call from the click handler.

### Bug 2: XSS in HTML attribute string concatenation (FIXED)

**Original plan** used string concatenation for `title` and `data-*` attributes:
```javascript
var item = $(
    '<div ... title="' + (conv.title || '') + '">' + ...
);
```

**The problem**: If `conv.title` contains `"` or `<`, this breaks the HTML or enables XSS. While the display text was correctly escaped via `$('<span>').text(title).html()`, the attributes were raw.

**Fix**: Switched to jQuery's `.attr()` method for all user-provided values. `.attr()` handles proper attribute escaping. Display text uses `.text()` which auto-escapes.
