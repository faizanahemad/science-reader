# Multi-Conversation Tabs

## Status: NOT STARTED

## Goal

Allow users to have multiple conversations open simultaneously with fast switching between them, without losing context or scroll position.

## Motivation

Currently the app shows one conversation at a time. Switching via sidebar discards scroll position and requires a full re-fetch + re-render. Users referencing multiple conversations (e.g., comparing answers, working on related topics) must constantly navigate back and forth, losing their place each time.

## Design Decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Tab bar visibility | Show only when ≥2 tabs open |
| 2 | Sidebar click | Replace current tab; context menu + Ctrl+click/long-press for new tab |
| 3 | Closing last tab | Can't close (× hidden) |
| 4 | Tab titles | Conversation title, truncated ~20 chars, hover for full |
| 5 | Tab ordering | Fixed in open-order |
| 6 | Unread indicator | No |
| 7 | New Temp Chat | Opens in new tab |
| 8 | Mobile tab selector | Inside floating gear dropdown (first item) |
| 9 | Max tabs | 5 hard cap with warning toast |
| 10 | $chatView refactor | Minimal — only where needed for desktop pane switching |
| 11 | Mid-stream mobile switch | Buffer chunks in JS, render on focus-back |
| 12 | Entry point | TabManager.focusTab() is top-level; calls setActiveConversation() on mobile |
| 13 | URL | Reflects focused tab only; opening URL with conv_id replaces current tab |
| 14 | Sidebar highlight | Only focused tab's conversation |
| 15 | Domain switching | Global — all tabs follow current domain |
| 16 | Phase scope | Desktop + mobile shipped together |
| 17 | Context menu | Add "Open in New Tab" to existing buildConversationContextMenu() |
| 18 | Gear dropdown placement | Tab list at top of dropdown (before domains) |
| 19 | Tab list style in gear | Blue left-border (reuse .gear-domain-item pattern) |
| 20 | URL with already-open conv | Replace current tab with that conversation |
| 21 | New Chat behavior | Opens in new tab if multiple tabs active, else in same tab |
| 22 | Persistence | Restore tab list on reload; only fetch focused tab (lazy) |
| 23 | Desktop overflow >5 | Hard cap at 5 with toast warning and inability to open more |
| 24 | Mid-stream mobile | Buffer in JS variable, render on focus-back |
| 25 | Tab close mid-stream | Warn "Response in progress, close anyway?" |

## Design Q&A (Full Record)

### UX Questions

**Q1. Tab bar visibility — show only when ≥2 tabs open (zero space cost for single conversation), or always show (doubles as conversation title display)?**
A: Show only when ≥2 tabs open.

**Q2. Sidebar click behavior — (A) Replace current tab's conversation (today's behavior) with Ctrl+click/long-press for new tab, (B) Always open in new tab, or (C) Replace current but warn if input box has unsent text?**
A: (A) Replace current tab, and also add "Open in New Tab" option in the conversation context menu.

**Q3. Closing the last tab — (A) Can't close it (× hidden), (B) Close and create new empty conversation, or (C) Close and show placeholder?**
A: (A) Can't close it.

**Q4. Tab titles — (A) Conversation title from sidebar truncated ~20 chars, (B) First user message snippet, or (C) Title if set else first message?**
A: (A) Conversation title, with hover to get full title.

**Q5. Tab ordering — (A) Fixed in open-order, or (B) Draggable?**
A: (A) Fixed in open-order.

**Q6. Unread indicator on background tabs (desktop) — (A) Dot/highlight when new content arrives, or (B) No?**
A: (B) No — keep it simple.

**Q7. "New Temp Chat" behavior — (A) Opens in current tab, (B) Always opens in new tab, or (C) New tab + closing deletes temp chat?**
A: (B) Always opens in new tab.

**Q8. Mobile tab selector location — (A) Floating top-left separate from gear, (B) First item inside floating gear dropdown, or (C) Thin strip above chat?**
A: (B) Inside the floating gear dropdown.

**Q9. Max open tabs — (A) 3, (B) 5, (C) 7, or (D) No cap with LRU?**
A: (B) Hard cap at 5.

### Implementation Questions

**Q10. `$chatView()` refactor scope — (A) All 41 references, or (B) Only common-chat.js and chat.js?**
A: Simplest implementation to reduce risk (minimal refactor — only the critical paths that need pane targeting).

**Q11. Mid-stream mobile tab switch — (A) Abort stream, (B) Stream completes server-side then re-fetch on focus-back, or (C) Buffer chunks in JS variable and render on focus-back?**
A: (C) Buffer in JS variable, render on focus-back.

**Q12. Entry point architecture — (A) TabManager.focusTab() is new top-level, calls setActiveConversation() only on mobile, or (B) Refactor setActiveConversation() to be mode-aware?**
A: (A) TabManager.focusTab() is the top-level entry point.

**Q13. URL behavior — (A) Reflects focused tab only, or (B) Encodes all open tab IDs?**
A: (A) Focused tab only. When a URL is copied and opened, just open that conversation.

**Q14. Sidebar highlight — (A) Only focused tab's conversation, or (B) All open tabs with different style?**
A: (A) Only focused tab.

**Q15. Domain switching — (A) Global, all tabs follow, or (B) Each tab has its own domain?**
A: (A) Global.

**Q16. Phase scope — (A) Desktop only first, mobile as Phase 2, or (B) Ship both together?**
A: (B) Ship both together.

### Follow-up Questions

**Q17. Conversation context menu — does one already exist?**
A: Yes — `buildConversationContextMenu()` in `workspace-manager.js` (uses jsTree + vakata context). Has: Copy Ref, Open in New Window, Clone, Toggle Stateless, Set Flag, etc. Add "Open in New Tab" to existing menu.

**Q18. Gear dropdown placement of tab list — (A) Top (before domains), (B) After domains, or (C) After actions?**
A: (A) Top of dropdown, before domains.

**Q19. Tab list in gear dropdown visual style — (A) Radio dot (●/○), or (B) Blue left-border like domain items?**
A: (B) Reuse the `.gear-domain-item` blue-left-border pattern.

**Q20. Opening a URL with conversation_id that's already open in a tab — (A) Focus existing tab, or (B) Replace current tab?**
A: (B) Replace current tab with that conversation.

**Q21. "New Chat" (not temp) behavior — (A) Also opens in new tab, or (B) Replaces current tab?**
A: (A) Opens in new tab if multiple tabs are active, else opens in same tab.

**Q22. Persistence across reload — (A) Restore all tabs but only fetch focused (lazy), or (B) Restore and fetch all?**
A: (A) Restore all, only fetch focused, lazy-load others on first focus.

**Q23. Desktop >5 tabs overflow — (A) Horizontal scroll, (B) "N more..." dropdown, or (C) Tabs shrink?**
A: (B) Collapse into dropdown. Hard cap at 5 with user warning toast and inability to open more.

**Q24. Mid-stream behavior confirmed?**
A: (C) Buffer in JS variable, render on focus-back. Rationale: shows live progress when user returns rather than a jump to completed state.

**Q25. Tab close while mid-stream — (A) Abort immediately, or (B) Warn first?**
A: (B) Warn "Response in progress, close anyway?"

## Architecture

### State Model

```js
var TabManager = {
    tabs: [],              // [{conversationId, title, streamBuffer: null}]
    focusedTabId: null,    // conversationId of visible tab
    MAX_TABS: 5
};
// ConversationManager.activeConversationId = TabManager.focusedTabId (always)
```

### Platform Detection

```js
const isMobileLayout = window.matchMedia(
    '(max-width: 768px) and (pointer: coarse) and (max-height: 768px)'
).matches;
```

### Desktop Strategy: Live DOM Panes

```html
<div id="chatView-container">
    <div id="chatView-{id1}" class="chatView-pane active">...</div>
    <div id="chatView-{id2}" class="chatView-pane" style="display:none">...</div>
</div>
```

- Tab switch: hide current pane CSS, show target pane CSS — instant
- Background streaming continues into hidden panes
- Max 5 live DOMs

### Mobile Strategy: Single DOM + Buffer

- Single `#chatView` element (unchanged)
- Tab switch: `RenderedStateManager.saveNow(old)` → `setActiveConversation(new)` (restore + fetch)
- If a background tab was mid-stream: chunks buffered in `TabManager.tabs[i].streamBuffer`
- On focus-back: if buffer has content, render buffered chunks then clear buffer

### Desktop Tab Bar UI

```
┌─[Chat about X ×]─[Research Y ×]─[+]───────────────────────┐  (30px height)
```

- Position: between toolbar row and chatView-container
- Hidden when tabs.length ≤ 1
- Active tab: background highlight + bottom-border
- Close button (×): on each tab except when only 1 tab
- "+" button: creates new conversation in new tab
- Overflow: "2 more ▾" dropdown at end when >5 would be reached (but capped at 5)
- Tab click: `TabManager.focusTab(convId)`
- Tab × click: `TabManager.closeTab(convId)` with mid-stream warning

### Mobile Tab Selector (inside Gear Dropdown)

```
┌──────────────────────┐
│ ● Chat about X       │  ← focused (blue left-border)
│   Research Y         │
│   Planning Z         │
├──────────────────────┤
│   Assistant          │  ← domain selector (existing)
│   Search             │
│   Prep-Chat          │
├──────────────────────┤
│   ...actions...      │
└──────────────────────┘
```

- Same `.gear-domain-item` visual pattern (blue left-border for active)
- Tap to switch (triggers `TabManager.focusTab()`)
- No × in dropdown (close via sidebar context menu or swipe — stretch goal)

### Streaming Architecture

```js
// Per-tab stream tracking (replaces global currentStreamingController)
TabManager.streamControllers = {};  // {conversationId: {reader, cancel()}}

// On send:
TabManager.streamControllers[convId] = { reader, cancel: () => {...} };

// On stream chunk received:
if (convId === TabManager.focusedTabId) {
    // Append to visible DOM (existing logic)
} else if (isMobileLayout) {
    // Buffer: TabManager.getTab(convId).streamBuffer += chunk
} else {
    // Desktop: append to hidden pane DOM (works since pane exists)
}

// On mobile focus-back:
var tab = TabManager.getTab(convId);
if (tab.streamBuffer) {
    renderBufferedChunks(tab.streamBuffer);
    tab.streamBuffer = null;
}
```

### $chatView() Accessor

```js
function $chatView(convId) {
    if (isMobileLayout) return $('#chatView');
    return $('#chatView-' + (convId || TabManager.focusedTabId));
}
```

Refactor scope: only the references in `renderStreamingResponse()` and `ChatManager.renderMessages()` that need to target a specific conversation's pane. Other `$('#chatView')` references (scroll, event handlers) can remain as-is since they always operate on the focused pane.

### Tab Persistence (localStorage)

```js
// Key: 'openTabs:{email}:{domain}'
// Value: JSON [{conversationId, title}]
// On load: restore tab list, focusTab(tabs[0]) — only focused tab fetches
// Other tabs: lazy-load on first focus
```

### Sidebar Integration

**Existing context menu** (`buildConversationContextMenu` in `workspace-manager.js`):
- Add item: `{ label: 'Open in New Tab', icon: 'fa fa-columns', action: ... }`
- Positioned after "Open in New Window"

**Ctrl+click / long-press**:
- Desktop: intercept `click` with `e.ctrlKey || e.metaKey` → open in new tab
- Mobile: long-press (>500ms hold) → show context menu (already implemented via `contextmenu` event)

**New Chat / New Temp Chat**:
- If `TabManager.tabs.length > 1`: open in new tab
- If `TabManager.tabs.length === 1`: open in same tab (replace)
- Temp Chat always opens in new tab regardless

### Domain Switch Handling

Domain is global. When user switches domain:
- Tab list clears (all tabs belong to current domain's workspace)
- Single tab with first conversation of new domain loads
- Or: preserve tabs but re-fetch sidebar for new domain — tabs with conversations from old domain show a "wrong domain" dimmed state

Simpler approach: **clear tabs on domain switch** (matches how sidebar already reloads).

### Send Button / Stop Button State

```js
// Only update send/stop UI if stream belongs to focused tab
function updateStreamUI(convId, streaming) {
    if (convId !== TabManager.focusedTabId) return;
    if (streaming) {
        $('#sendMessageButton').hide();
        $('#stopResponseButton').show();
    } else {
        $('#sendMessageButton').show();
        $('#stopResponseButton').hide();
    }
}
```

### Close Tab Flow

```
User clicks × on tab
  → Is tab mid-stream?
     Yes → confirm("Response in progress, close anyway?")
       → If confirmed: abort stream, remove pane, focus adjacent tab
       → If cancelled: no-op
     No → remove pane from DOM, remove from TabManager.tabs
  → If closed tab was focused: focus adjacent (prefer right, then left)
  → If tabs.length === 1: hide tab bar
  → Update localStorage
```

## Files to Modify

| File | Changes |
|------|---------|
| `interface/tab-manager.js` (NEW) | TabManager module: state, focusTab, openTab, closeTab, renderTabBar, renderGearTabs, persistence |
| `interface/interface.html` | Tab bar container div; chatView-container wrapper; gear dropdown tab section |
| `interface/common-chat.js` | `$chatView()` accessor in renderStreamingResponse + renderMessages; per-tab streamController; buffer logic |
| `interface/workspace-manager.js` | "Open in New Tab" context menu item; Ctrl+click handler on sidebar items |
| `interface/chat.js` | Import/init TabManager; New Chat routing logic |
| `interface/interface.js` | Gear dropdown tab items handler; domain switch clears tabs |
| `interface/style.css` | Tab bar styles; `.chatView-pane` display rules; mobile gear tab section |
| `interface/rendered-state-manager.js` | No change (used by mobile path via existing setActiveConversation) |

## Tasks

### Phase 1: Core TabManager + Desktop Tab Bar
- [ ] 1.1 Create `tab-manager.js` with state model, openTab, closeTab, focusTab, persistence
- [ ] 1.2 Add `<div id="conv-tab-bar">` to HTML between toolbar and chatView
- [ ] 1.3 Wrap `#chatView` in `#chatView-container`; desktop: create per-tab pane divs
- [ ] 1.4 Tab bar rendering: tabs, active state, × button, + button, overflow dropdown
- [ ] 1.5 Tab bar CSS: height, active highlight, hover, overflow
- [ ] 1.6 `focusTab()` desktop path: show/hide panes, update activeConversationId, URL
- [ ] 1.7 Hide tab bar when tabs.length ≤ 1

### Phase 2: $chatView Refactor + Streaming
- [ ] 2.1 Create `$chatView(convId)` accessor function
- [ ] 2.2 Update `renderStreamingResponse()` to use `$chatView(convId)`
- [ ] 2.3 Update `ChatManager.renderMessages()` to use `$chatView(convId)`
- [ ] 2.4 Per-tab `streamControllers` map (replace global `currentStreamingController`)
- [ ] 2.5 Send/stop button state scoped to focused tab
- [ ] 2.6 Mid-stream close warning

### Phase 3: Sidebar Integration
- [ ] 3.1 Add "Open in New Tab" to `buildConversationContextMenu()`
- [ ] 3.2 Ctrl+click / meta+click handler on sidebar conversation items
- [ ] 3.3 New Chat / New Temp Chat routing (new tab if tabs > 1; temp chat always new)
- [ ] 3.4 Max tab enforcement (5 cap + toast warning)

### Phase 4: Mobile
- [ ] 4.1 Add tab list section to floating gear dropdown (and inline gear)
- [ ] 4.2 `focusTab()` mobile path: saveNow → setActiveConversation
- [ ] 4.3 Stream buffering: buffer chunks when background on mobile
- [ ] 4.4 Render buffered content on focus-back
- [ ] 4.5 Gear tab items: tap to switch, active highlight sync

### Phase 5: Polish
- [ ] 5.1 Tab persistence to localStorage (save on change, restore on load)
- [ ] 5.2 Domain switch clears tabs
- [ ] 5.3 URL open with conv_id: if tabs exist, replace current tab
- [ ] 5.4 Lazy load: only fetch focused tab on restore; others on first focus
- [ ] 5.5 Tab title updates when conversation title changes in sidebar

## Estimated Effort

| Phase | Effort |
|-------|--------|
| 1. Core + Desktop Tab Bar | 1.5 days |
| 2. $chatView + Streaming | 1 day |
| 3. Sidebar Integration | 0.5 day |
| 4. Mobile | 1 day |
| 5. Polish | 1 day |
| **Total** | **~5 days** |

## Risks

| Risk | Mitigation |
|------|-----------|
| Breaking existing single-conversation flow | Tab bar hidden when 1 tab — zero visual change from today |
| Memory with 5 live DOMs | Hard cap at 5; conversations >4MB DOM already handled by RenderedStateManager |
| Mobile stream buffering complexity | If buffer gets too large, fall back to re-fetch on focus |
| 41 `$('#chatView')` references | Only refactor the 2-3 critical ones (renderMessages, renderStreamingResponse); rest operate on focused pane by default |
| Domain switch edge cases | Clear all tabs on domain switch (clean slate) |
