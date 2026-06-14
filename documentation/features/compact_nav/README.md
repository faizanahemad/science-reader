# Gear Menu — Navbar Replacement & Domain Selector

## Motivation and Background

The top navbar (`#pdf-details-tab`) consumed ~35px of vertical space and contained:
- Hamburger sidebar toggle
- Domain tabs (Assistant, Search, Prep-Chat)
- A mobile-only `⋮` dropdown with action shortcuts (compact_nav setting forced this on desktop)
- Logout button

This was wasteful: the domain tabs are rarely switched, and the navbar was always visible. The "Compact Nav" setting existed to collapse the navbar into a dropdown on desktop, but even then the navbar row itself remained visible.

**Solution:** Remove the top navbar entirely. Move all its functionality into a gear (⚙) dropdown button placed in the top-right of the chat area, beside the existing "New Temp Chat" button. This reclaims the full ~35px for chat content.

## Architecture

### Before
```
┌─────────────────────────────────────────────┐
│ ☰  Assistant | Search | Prep-Chat  ⋮  Logout│  ← #pdf-details-tab (35px)
├─────────────────────────────────────────────┤
│ [toolbar]                    [temp chat]     │
│ [chat messages...]                           │
└─────────────────────────────────────────────┘
```

### After
```
┌─────────────────────────────────────────────┐
│ [toolbar]            [☰] [temp chat] [⚙]    │  ← merged into toolbar row
│ [chat messages...]                           │
└─────────────────────────────────────────────┘
```

The gear dropdown contains:
1. **Domain selector** — vertical nav with active item highlighted (blue left-border + tinted background)
2. New Temp Chat
3. Download Transcript, Share Chat
4. Docs, Global Docs
5. Logout

## UI Details

### Gear Dropdown Layout
```
┌──────────────────────┐
│ ◉ Assistant          │  ← active: blue border + bg
│   Search             │
│   Prep-Chat          │
├──────────────────────┤
│ 👁 New Temp Chat     │
│ ⬇ Download Transcript│
│ ↗ Share Chat         │
├──────────────────────┤
│ 📄 Docs              │
│ 🌐 Global Docs       │
├──────────────────────┤
│ ⊡ Compact Mode    ✓  │  ← checkmark when active
│ ↩ Logout             │
└──────────────────────┘
```

### Top-Right Button Group
From left to right in the `ml-auto` area:
- `☰` Sidebar toggle (`#chat-area-show-sidebar`)
- `👁` New Temp Chat (`#new-temp-chat`) — existing
- `⚙` Gear menu (`#gear-menu-btn`)

### Domain Switching
Clicking a domain item in the gear menu:
1. Updates the visual highlight (`.gear-domain-item.active`)
2. Hides PDF view if open, shows chat content
3. Sets `currentDomain["manual_domain_change"] = true`
4. Manages `.active` class on the hidden original tabs
5. Triggers `shown.bs.tab` on the corresponding hidden tab link
6. This fires all existing domain-switch logic (workspace reload, settings swap, URL clear)

A `domainChanged` custom event keeps the gear menu in sync when domain changes programmatically (e.g., loading a conversation from a different domain auto-switches the tab).

## Compact Mode

The "Compact Mode" toggle (available inside the gear dropdown itself) switches between two presentations:

### Normal Mode (default)
- Toolbar row visible with all action buttons + inline gear dropdown + sidebar toggle
- Gear dropdown serves as secondary access to domain switching, docs, logout

### Compact Mode (body.compact-nav)
- Toolbar row hidden (`display: none !important` on `.row.d-none.d-md-flex`)
- Floating gear button appears (`#gear-menu-floating`, `position: fixed; top: 8px; right: 12px; z-index: 1050`)
- Floating dropdown includes an extra "Toggle Sidebar" item (`.gear-sidebar-item`)
- Maximizes vertical space for chat content

### Toggle Behavior
- `#gear-compact-nav-toggle` click → sets `#settings-compact_nav` checkbox → triggers `change` event
- `chat.js` `change` handler calls `applyCompactNav()` → adds/removes `body.compact-nav`
- CSS checkmark (`.gear-compact-check::after { content: '✓' }`) reacts to `body.compact-nav` automatically
- Setting persisted to localStorage via `chatSettingsState.compact_nav`

## Implementation Details

### CSS

```css
/* Hide the old navbar and its spacer */
#pdf-details-tab { display: none !important; }
#pdf-details-tab + #navbar-trigger { display: none !important; }

/* Gear dropdown styling */
.gear-dropdown { min-width: 200px; }
.gear-domain-item { border-left: 3px solid transparent; font-weight: 500; }
.gear-domain-item.active {
    background-color: rgba(0, 123, 255, 0.1);
    border-left-color: #007bff;
    color: #007bff;
}
```

### JavaScript (interface/interface.js)

**Gear domain click handler:**
- Prevents default, checks if already active domain
- Sets `manual_domain_change = true` (needed for `clearUrlofConversationId()`)
- Hides `#chat-pdf-content`, shows `#chat-content` (matches original tab click behavior)
- Manages `.active` on hidden `#pdf-details-tab .nav-link` elements
- Triggers `shown.bs.tab` directly (not `.tab('show')` — target panes don't exist in DOM)

**Action delegation:**
All gear action items (`#gear-*`) proxy clicks to existing button IDs:
- `#gear-new-temp-chat` → `#new-temp-chat`
- `#gear-get-chat-transcript` → `#get-chat-transcript`
- `#gear-share-chat` → `#share-chat`
- `#gear-conversation-docs` → `#conversation-docs-button`
- `#gear-global-docs` → `#global-docs-button`
- `#gear-logout` → `#logout-link`

**domainChanged event:**
Each `shown.bs.tab` handler now fires `$(document).trigger('domainChanged')`. The gear menu listens and syncs its `.active` highlight.

### Backward Compatibility

- **Old navbar still in DOM** — hidden via CSS but structurally intact. `toggleSidebar()` still reads `$('#pdf-details-tab .nav-link.active')` successfully.
- **`getCurrentActiveTab()`** in `chat.js` still works (reads `.hasClass('active')` from hidden tab links).
- **Programmatic domain switch** (`common-chat.js:834`) still triggers `$('#' + active_tab).trigger('shown.bs.tab')` — the `domainChanged` event syncs the gear menu.
- **compact_nav setting** still exists in settings modal but is now effectively a no-op (navbar is always hidden).

### Known Design Decisions

1. **Why not remove the old navbar HTML?** — Too many JS references to `#assistant-tab`, `#search-tab`, `#finchat-tab` across the codebase. Hiding via CSS is zero-risk; removing HTML would require rewriting all domain-switch callers.
2. **Why direct `.trigger('shown.bs.tab')` instead of `.tab('show')`?** — Bootstrap 4's `.tab('show')` tries to activate a target pane (`#search-view`, `#finchat-view`) which don't exist as DOM elements. The event might not fire. Direct trigger is the proven pattern (used by `common-chat.js:834`).
3. **Default active domain is `assistant`** — matches the page-load initialization at `interface.js:217` which forces `assistant-tab`.

### Known Design Decisions

1. **Why not remove the old navbar HTML?** — Too many JS references to `#assistant-tab`, `#search-tab`, `#finchat-tab` across the codebase. Hiding via CSS is zero-risk; removing HTML would require rewriting all domain-switch callers.
2. **Why direct `.trigger('shown.bs.tab')` instead of `.tab('show')`?** — Bootstrap 4's `.tab('show')` tries to activate a target pane (`#search-view`, `#finchat-view`) which don't exist as DOM elements. The event might not fire. Direct trigger is the proven pattern (used by `common-chat.js:834`).
3. **Default active domain is `assistant`** — matches the page-load initialization at `interface.js:217` which forces `assistant-tab`.

## Files Modified

| File | Changes |
|---|---|
| `interface/interface.html` | Added `#chat-area-show-sidebar` button, `#gear-menu-container` dropdown with domain items + actions. Default active: `assistant`. |
| `interface/interface.js` | Gear domain click handler, action delegation, `domainChanged` event listener, `$(document).trigger('domainChanged')` in all 3 `shown.bs.tab` handlers, `#chat-area-show-sidebar` click wiring. |
| `interface/style.css` | `#pdf-details-tab` + `#navbar-trigger` hidden. `.gear-dropdown`, `.gear-domain-nav`, `.gear-domain-item` styles. |
| `interface/workspace-styles.css` | (Unchanged — `.sidebar-tool-btn` styles unaffected) |

## Related

- Domain system docs: domains are a UI-level namespace (assistant/search/finchat). Backend behavior is identical across all three.
- Old compact_nav approach: superseded by this change. The `body.compact-nav` class and `applyCompactNav()` still exist but have no visible effect.
