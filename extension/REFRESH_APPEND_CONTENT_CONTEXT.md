# Refresh & Append Page Content - Implementation Context

## Requirements

**Feature:** Add two buttons for SPA content management in the sidepanel input area:
1. **Refresh Content** (`🔄`) - Re-extract current page, **replace** existing context
2. **Append Content** (`➕`) - Extract current page, **merge** with existing context

**Use Cases:**
- **Refresh**: Page content changed (user edited doc, scrolled to new SPA section)
- **Append**: User switched views/tabs in SPA, wants both old + new content as context

---

## Files to Modify

### 1. `extension/sidepanel/sidepanel.html` (lines 270-308)

**Current buttons:** `attach-page-btn`, `attach-screenshot-btn`, `attach-scrollshot-btn`, `multi-tab-btn`, `voice-btn`

**Additional page-context-bar actions (added separately):** `view-content-btn` (eye icon — opens content viewer modal to inspect/copy extracted text with pagination), `remove-page-context` (close icon).

**Related features (implemented separately, not part of this plan):**
- **Inner scroll container detection**: The scrollshot button (`attach-scrollshot-btn`) now uses a capture context protocol (`INIT_CAPTURE_CONTEXT`) that detects inner scrollable elements in web apps like Office Word Online, Google Docs, Notion, etc. instead of only scrolling the window.
- **Pipelined capture + OCR**: OCR requests fire per screenshot during capture rather than waiting for all screenshots to complete. Reduces total OCR time by 40-60%.
- **Content viewer**: Clicking the page-context title or the eye icon opens a paginated viewer showing extracted/OCR text with copy-to-clipboard.

**Add after `attach-page-btn` (line 278):**
```html
<button id="refresh-page-btn" class="action-btn" title="Refresh content (replace)" disabled>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M23 4v6h-6M1 20v-6h6"/>
        <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
    </svg>
</button>
<button id="append-page-btn" class="action-btn" title="Append content (add to existing)" disabled>
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <line x1="12" y1="8" x2="12" y2="16"/>
        <line x1="8" y1="12" x2="16" y2="12"/>
    </svg>
</button>
```

---

### 2. `extension/sidepanel/sidepanel.css`

**Button styles (add near line 300):**
```css
.action-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
```

**Page context bar (update near line 850):**
- Add `.context-count-badge` for showing "N sources"
- Keep existing `.page-context-bar`, `.page-context-info` styles

---

### 3. `extension/sidepanel/sidepanel.js` - Main Changes

#### A. State (lines 18-46)
Current `state.pageContext` structure works. Add optional fields for tracking:
```javascript
state.pageContext = {
    url: string,
    title: string, 
    content: string,
    // Existing flags (preserve)
    isMultiTab: boolean,
    tabCount: number,
    isScreenshot: boolean,
    isOcr: boolean,
    // NEW optional fields
    sources: [{url, title, content, timestamp}],  // For append tracking
    mergeType: 'single'|'appended'|'refreshed',
    lastRefreshed: number
};
```

#### B. DOM Elements (add at line ~131)
```javascript
const refreshPageBtn = document.getElementById('refresh-page-btn');
const appendPageBtn = document.getElementById('append-page-btn');
```

#### C. Event Listeners (add at line ~372)
```javascript
refreshPageBtn?.addEventListener('click', refreshPageContent);
appendPageBtn?.addEventListener('click', appendPageContent);
removePageContextBtn?.addEventListener('click', removePageContext);  // Already exists
```

#### D. New Function: `refreshPageContent()` (add after line 1897)
```javascript
async function refreshPageContent() {
    if (state.isStreaming) return;
    
    try {
        pageContextTitle.textContent = '🔄 Refreshing...';
        
        const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXTRACT_PAGE });
        if (!response || response.error) {
            throw new Error(response?.error || 'Extraction failed');
        }
        
        const context = await buildPageContextFromResponse(response, { showAlerts: true });
        if (!context) return;
        
        // Replace existing context entirely
        state.pageContext = {
            ...context,
            sources: [{ url: context.url, title: context.title, content: context.content, timestamp: Date.now() }],
            mergeType: 'refreshed',
            lastRefreshed: Date.now()
        };
        state.multiTabContexts = [];
        state.selectedTabIds = [];
        
        const prefix = context.isOcr ? '🧾 ' : context.isScreenshot ? '📷 ' : '🔄 ';
        pageContextTitle.textContent = `${prefix}${context.title || 'Content refreshed'}`;
        pageContextBar.classList.remove('hidden');
        
        updatePageContextButtons();
    } catch (e) {
        console.error('[Sidepanel] Refresh failed:', e);
        alert('Failed to refresh page content');
    }
}
```

#### E. New Function: `appendPageContent()` (add after refreshPageContent)
```javascript
async function appendPageContent() {
    if (state.isStreaming || !state.pageContext) return;
    
    try {
        pageContextTitle.textContent = '➕ Appending...';
        
        const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXTRACT_PAGE });
        if (!response || response.error) {
            throw new Error(response?.error || 'Extraction failed');
        }
        
        const newContext = await buildPageContextFromResponse(response, { showAlerts: true });
        if (!newContext) return;
        
        // Normalize existing context to sources array
        if (!state.pageContext.sources) {
            state.pageContext.sources = [{
                url: state.pageContext.url,
                title: state.pageContext.title,
                content: state.pageContext.content,
                timestamp: state.pageContext.lastRefreshed || Date.now()
            }];
        }
        
        // Check for duplicate URL (optional: warn or auto-refresh)
        const existingUrls = state.pageContext.sources.map(s => s.url);
        if (existingUrls.includes(newContext.url)) {
            if (!confirm('This page is already included. Add anyway?')) return;
        }
        
        // Add new source
        state.pageContext.sources.push({
            url: newContext.url,
            title: newContext.title,
            content: newContext.content,
            timestamp: Date.now()
        });
        
        // Combine content (same format as multi-tab)
        const combinedContent = state.pageContext.sources.map((s, i) => 
            `## Source ${i + 1}: ${s.title}\nURL: ${s.url}\n\n${s.content}`
        ).join('\n\n---\n\n');
        
        state.pageContext = {
            ...state.pageContext,
            url: 'Multiple sources',
            title: `${state.pageContext.sources.length} sources`,
            content: combinedContent,
            mergeType: 'appended',
            tabCount: state.pageContext.sources.length,
            lastRefreshed: Date.now()
        };
        
        pageContextTitle.textContent = `➕ ${state.pageContext.sources.length} sources attached`;
        pageContextBar.classList.remove('hidden');
        
        updatePageContextButtons();
    } catch (e) {
        console.error('[Sidepanel] Append failed:', e);
        alert('Failed to append page content');
    }
}
```

#### F. New Helper: `updatePageContextButtons()` (add near other UI helpers)
```javascript
function updatePageContextButtons() {
    const hasContext = !!state.pageContext;
    const isStreaming = state.isStreaming;
    
    if (refreshPageBtn) refreshPageBtn.disabled = !hasContext || isStreaming;
    if (appendPageBtn) appendPageBtn.disabled = !hasContext || isStreaming;
    
    // Update active states
    attachPageBtn.classList.toggle('active', hasContext);
    refreshPageBtn?.classList.toggle('active', hasContext && state.pageContext?.mergeType === 'refreshed');
    appendPageBtn?.classList.toggle('active', hasContext && state.pageContext?.mergeType === 'appended');
    multiTabBtn.classList.toggle('active', hasContext && state.pageContext?.isMultiTab);
}
```

#### G. Update `removePageContext()` (line 1899)
```javascript
function removePageContext() {
    state.pageContext = null;
    state.multiTabContexts = [];
    state.selectedTabIds = [];
    pageContextBar.classList.add('hidden');
    attachPageBtn.classList.remove('active');
    refreshPageBtn?.classList.remove('active');
    appendPageBtn?.classList.remove('active');
    multiTabBtn.classList.remove('active');
    updateMultiTabIndicator();
    updatePageContextButtons();  // Update button disabled states
}
```

#### H. Update `attachPageContent()` (line 1864)
Add at end of success path:
```javascript
state.pageContext.mergeType = 'single';
state.pageContext.sources = [{ url: context.url, title: context.title, content: context.content, timestamp: Date.now() }];
updatePageContextButtons();
```

#### I. Call `updatePageContextButtons()` from:
- `attachPageContent()` - after setting context
- `refreshPageContent()` - after setting context  
- `appendPageContent()` - after setting context
- `removePageContext()` - after clearing
- `handleTabSelection()` (line 2116) - after setting multi-tab context
- When streaming starts/ends - to disable during streaming

---

## No Changes Needed

| File | Reason |
|------|--------|
| `extension_server.py` | Already handles `page_context.content` as string (lines 1486-1644) |
| `extension.py` | Stores `page_context` as JSON, no schema changes |
| `extractor.js` | Stateless, reuse `EXTRACT_PAGE` message |
| `service-worker.js` | Just routes messages |
| `shared/api.js` | Agnostic to page_context structure |
| `shared/constants.js` | Reuse `EXTRACT_PAGE` (no new message types needed) |

---

## Reference: Existing Multi-Tab Merge Pattern

`handleTabSelection()` (lines 2004-2116) shows the pattern:
```javascript
// From existing code
const combinedContent = contexts.map(c => 
    `## Tab: ${c.title}\nURL: ${c.url}\n\n${c.content}`
).join('\n\n---\n\n');

state.pageContext = {
    url: contexts.length === 1 ? contexts[0].url : 'Multiple tabs',
    title: `${contexts.length} tabs`,
    content: combinedContent,
    isMultiTab: true,
    tabCount: contexts.length
};
```

---

## UI State Matrix

| State | attach-btn | refresh-btn | append-btn | multi-tab-btn |
|-------|-----------|-------------|------------|---------------|
| No context | enabled | **disabled** | **disabled** | enabled |
| Single page | active | enabled | enabled | enabled |
| Refreshed | active | **active** | enabled | enabled |
| Appended | active | enabled | **active** | enabled |
| Multi-tab | active | enabled | enabled | **active** |
| Streaming | disabled | disabled | disabled | disabled |

---

## Page Context Bar Display

| State | Display Text |
|-------|--------------|
| Single page | `📄 [Title]` or `📷 [Title]` or `🧾 [Title]` |
| Refreshed | `🔄 [Title]` |
| Appended | `➕ N sources attached` |
| Multi-tab | `📑 N tabs attached` |

---

## Edge Cases to Handle

1. **Refresh on different URL** - Allow (user wants current page)
2. **Append same URL** - Show confirm dialog, allow if user confirms
3. **Append limit** - Consider max 5-10 sources (optional)
4. **Refresh multi-tab** - Clear multi-tab, extract current page only
5. **Streaming active** - Disable all buttons (already handled by `state.isStreaming`)

---

## Testing Checklist

- [ ] Attach page → Refresh → verify content replaced
- [ ] Attach page → Append → verify content merged (2 sources)
- [ ] Append 3 times → verify all in context
- [ ] Refresh appended → verify replaced with 1 source
- [ ] Remove context → verify buttons disabled
- [ ] During streaming → verify buttons disabled
- [ ] Send message with appended context → verify LLM receives combined content
- [ ] Append same URL → verify warning shown

---

## Implementation Order

1. Add buttons to `sidepanel.html`
2. Add DOM refs and event listeners in `sidepanel.js`
3. Add `updatePageContextButtons()` helper
4. Add `refreshPageContent()` function
5. Add `appendPageContent()` function  
6. Update `removePageContext()` to call helper
7. Update `attachPageContent()` to set mergeType and call helper
8. Add CSS for disabled state
9. Test all scenarios
