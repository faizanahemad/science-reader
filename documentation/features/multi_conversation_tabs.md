# Multi-Conversation Tabs — Implementation Details

## Motivation

Users frequently need to reference one conversation while working in another, or keep multiple conversations "warm" (e.g., a research thread + a coding thread). Previously, switching conversations required a full message reload. This feature enables instant switching between up to 5 conversations.

## Architecture

### Desktop (multi-pane)

On desktop, each open tab gets its own DOM element (`#chatView-{conversationId}`) inside `#chatView-container`. Only the focused pane has the CSS class `active` (making it visible). Switching tabs toggles classes without re-rendering messages -- instant.

```
#chatView-container (flex-grow-1, overflow-hidden, d-flex, flex-column)
  #chatView-{convId1} .chatView-pane.active  (visible)
  #chatView-{convId2} .chatView-pane          (hidden)
  ...
```

### Mobile (single-pane, shared DOM)

On mobile, there's only one `#chatView` element. Switching tabs saves the current state via `RenderedStateManager.saveNow()` then calls `ConversationManager.setActiveConversation()` which does a full reload. The trade-off is accepted since mobile has memory constraints.

### Tab Bar UI

- `#conv-tab-bar` -- sits inside `#chat-toolbar-row` on the left; toolbar buttons (sidebar toggle, new-temp-chat, gear) stay right via `.ml-auto`
- Hidden by default (`display:none`); shown with class `.visible` when tabs > 1
- CSS: `flex:1; display:flex; flex-direction:row;` when visible -- fills remaining space in the toolbar row
- Each tab: `.conv-tab` div with title span + close button
- Active tab highlighted with blue bottom border
- Hidden on mobile: `#chat-toolbar-row` is `display:none` on mobile/compact-nav, and the gear dropdown tab list takes over

### Gear Dropdown (Mobile)

Both inline and floating gear menus have a `.gear-tab-nav` section at the top (before domain items). Shows tab list as dropdown items when tabs > 1.

## Key Design Decisions

1. **Conversation IDs contain special chars** (`@`, `.`) -- all DOM lookups use `document.getElementById()` instead of jQuery `$('#id')` to avoid CSS selector escaping issues.

2. **`$chatView(convId)` accessor** -- global function in `common-chat.js` replacing all direct `$('#chatView')` references. Returns the correct pane for a given conversation, falling back to `$('#chatView')` before TabManager initializes.

3. **Per-tab stream controllers** -- `TabManager.streamControllers[convId]` maps each tab to its active streaming reader. Send/stop button state syncs to the focused tab.

4. **Lazy loading** -- on restore from localStorage, only the focused tab calls `setActiveConversation`. Other tabs load on first focus.

5. **Tab bar visibility** -- controlled via `.visible` CSS class (not inline styles) to avoid Bootstrap `!important` conflicts. Bar HTML is cleared on hide to prevent stale content.

6. **Single-tab replace** -- normal sidebar clicks replace the focused tab's conversation (rename pane ID, clear content, load new). Only Ctrl+click or context menu opens a new tab.

7. **Domain switch** -- listens for `domainChanged` event, tracks `_lastDomain`, clears all tabs only when domain actually changes (ignores redundant events on page load).

## User Interaction

- **Open in New Tab**: Ctrl+click (or Meta+click) on a sidebar conversation, or right-click context menu "Open in New Tab"
- **Switch tabs**: Click a tab in the tab bar (desktop) or select from gear dropdown (mobile)
- **Close tab**: Click the x button on a tab (can't close last tab; warns if stream in progress)
- **New tab**: Click the + button in the tab bar, or "New Temp Chat" which opens in a new tab when tabs are active
- **Maximum 5 tabs**: Toast warning when limit reached

## Files Modified

| File | Changes |
|------|---------|
| `interface/tab-manager.js` | New file. TabManager module -- state, openTab, closeTab, focusTab, renderTabBar, renderGearTabs, persistence, streamControllers, init |
| `interface/common-chat.js` | Added `$chatView()` accessor. Updated renderMessages, renderStreamingResponse, stopCurrentResponse, scrollToBottom, sendMessageCallback, suggestions, multi-select to use it |
| `interface/common.js` | Updated fetchConversationUIState to use `$chatView()` with typeof guard |
| `interface/rendered-state-manager.js` | `getChatViewEl(convId)`, `readDomMeta(convId)`, `applySnapshotToDom(snapshot, convId)` -- all pane-aware |
| `interface/workspace-manager.js` | "Open in New Tab" context menu, Ctrl+click handler, sidebar normal click updates focused tab, createTemporaryConversation opens tab, TabManager.init() call, title sync in highlightActiveConversation |
| `interface/interface.html` | `#conv-tab-bar`, `#chatView-container` wrapper, `.gear-tab-nav` in both gear menus, `tab-manager.js` script tag, MutationObserver targets container |
| `interface/style.css` | Tab bar styles, `.chatView-pane` display rules, `.gear-tab-nav` item styles, container/bar negative margins |

## TabManager API

```js
TabManager.openTab(conversationId, title, shouldFocus) // returns true/false
TabManager.closeTab(conversationId)
TabManager.focusTab(conversationId)
TabManager.getTab(conversationId)    // returns {conversationId, title} or null
TabManager.hasTab(conversationId)    // returns boolean
TabManager.updateTitle(conversationId, title)
TabManager.clearTabs()
TabManager.init(initialConversationId, initialTitle)
TabManager.persist()
TabManager.restore()                 // returns boolean (true if restored)
TabManager.renderUI()                // renders both tab bar and gear tabs
TabManager.tabs                      // [{conversationId, title}, ...]
TabManager.focusedTabId              // current focused conversation ID
TabManager.streamControllers         // {convId: {reader, cancel()}}
```

## localStorage Schema

Key: `openTabs:{email}:{domain}`

```json
{
  "tabs": [
    {"conversationId": "...", "title": "..."},
    {"conversationId": "...", "title": "..."}
  ],
  "focusedTabId": "..."
}
```

## Known Limitations

- Maximum 5 tabs (enforced with toast warning)
- On mobile, switching away from a streaming tab loses real-time progress (stream writes to detached DOM; content available on switch-back via server reload)
- Tab persistence uses conversation IDs which may become invalid if conversations are deleted between sessions (handled gracefully -- loads with current/first available conversation)
