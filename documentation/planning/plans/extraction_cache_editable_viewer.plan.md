# Plan: Extraction Cache + Editable Content Viewer

**Status**: `implemented`
**Oracle Review**: Completed 2026-02-21. Architecture approved with refinements integrated below.
**Created**: 2026-02-21
**Scope**: Extension service worker cache for tab extractions + editable content viewer modal

## Goals

1. **Extraction Cache**: Cache extracted tab content in the extension service worker so re-extracting a previously extracted tab returns cached content instantly. Cache is shared across main UI and iframe extension since both communicate with the same service worker.
2. **Editable Content Viewer**: Make the content shown in `content-viewer-modal` editable. User can modify extracted text per-page. Edits persist back to context and cache. Includes "(edited)" indicator and "Reset to original" button.

## Requirements

### Extraction Cache

- Cache key: `url + "|" + mode` (mode = `dom`, `ocr`, `full-ocr`)
- 100-entry LRU eviction
- Auto-invalidate on `chrome.tabs.onUpdated` (URL change) and `chrome.tabs.onRemoved` (tab closed)
- Also invalidate stale entries when `LIST_TABS` is called (cross-check cached URLs against open tab URLs)
- `ext-refresh-page` force-refreshes only currently attached pages (in `_context`). Unattached cached content stays.
- `page-context-clear` clears `_context` only, cache untouched.
- For OCR/full-ocr: extension produces screenshots, client does OCR via `/ext/ocr`. Client sends final OCR text back to extension via `CACHE_STORE` operation so it's cached for future lookups.
- DOM extraction results cached directly in the extension (text content returned by `handleExtractTab`/`handleExtractCurrentPage`).

### Editable Content Viewer

- Replace `<pre id="cv-text">` with `<textarea id="cv-text">` styled identically.
- Each page independently editable in paginated view.
- "All" view remains read-only (can't map edits back to individual pages).
- Edits persist to `_context.sources[i].content` and merged `_context.content`.
- Edits also update extension cache via `CACHE_STORE` (so edits are available across UIs).
- "(edited)" visual indicator when content differs from original.
- "Reset to original" button per page to discard edits (restores from original extraction stored alongside edited version).
- Char/word counts update live during editing.

## Architecture

### Cache Location: Extension Service Worker

The cache lives in the service worker (`extension-iframe/background/service-worker.js`), making it shared across all UI clients. This is better than client-side caching because:
- Both main UI tab and iframe sidepanel share the same cache
- Cache survives UI page reloads (service worker persists)
- Single source of truth for extraction data

### Cache Class: Inline in `extension-iframe/background/service-worker.js`

Per Oracle review: cache is SW-specific, not shared. Defined inline in service-worker.js.

- `ExtractionCache` class with LRU Map + byte-size cap
- Methods: `get(key)`, `set(key, value)`, `delete(key)`, `invalidateByTabId(tabId)`, `invalidateByUrl(url)`, `batchLookup(entries)`, `clear()`, `size`, `keys()`
- LRU: on `get()`, entry moves to end of Map (most recent). On `set()` when full, delete first Map entry (oldest).
- Dual cap: 100 entries AND ~50MB total content size (whichever hits first)
- Maintains a `_tabUrls` reverse map (`tabId → Set<url>`) for efficient `onUpdated`/`onRemoved` invalidation
- Each entry: `{ url, mode, tabId, content, title, wordCount, charCount, contentType, extractionMethod, isOcr, timestamp }`

### New Extension Operations

Per Oracle review: DOM extractions are cached transparently inside `handleOperation()` —
no separate CACHE_LOOKUP round-trip needed. Client only needs explicit operations for
OCR result storage and cache management.

| Operation | Direction | Purpose |
|-----------|-----------|---------|
| `CACHE_STORE` | Client → Extension | Store OCR text result after client-side OCR |
| `CACHE_BATCH_LOOKUP` | Client → Extension | Check cache for multiple tabs at once (multi-tab flow) |
| `CACHE_INVALIDATE` | Client → Extension | Invalidate specific entries (refresh button) |
| `CACHE_CLEAR` | Client → Extension | Clear entire cache |

### New ExtensionBridge Methods

```javascript
ExtensionBridge.cacheStore(url, mode, data)        // → { success: true }
ExtensionBridge.cacheBatchLookup(entries)           // → { results: [{ url, mode, hit, data? }] }
ExtensionBridge.cacheInvalidate(url, mode)          // → { success: true, removed: number }
ExtensionBridge.cacheClear()                        // → { success: true, removed: number }
```

### Extraction Flow With Cache

#### Single Tab (ext-extract-page) — Transparent caching
```
1. PageContextManager click handler
2. → ExtensionBridge.extractCurrentPage()
3. → Service worker handleOperation():
   a. Resolve active tab → get tab.url
   b. Check cache: extractionCache.get(tab.url + '|dom')
   c. If hit: return cached result immediately (no extraction)
   d. If miss: extract, cache result, return it
4. → setSingleContext(result)
```
Client code UNCHANGED — caching is invisible at this level.

#### Multi-Tab (Tab Picker) — Batch lookup + selective extraction
```
1. TabPickerManager._startCapture()
2. → ExtensionBridge.cacheBatchLookup(selected.map(t => {url, mode}))
3. → Partition into cachedResults[] and uncachedTabs[]
4. → If uncachedTabs.length > 0:
   ExtensionBridge.captureMultiTab(uncachedTabs)
   → Extension auto-caches DOM results inside captureOneTab
   → For OCR/full-ocr tabs: client does OCR, then calls
     ExtensionBridge.cacheStore(url, mode, { content, title, ... })
5. → Merge cachedResults + freshResults in _assembleResults()
6. → PageContextManager.setMultiTabContext(merged)
```

#### Refresh (ext-refresh-page)
```
1. Get currently attached URLs from _context
2. → ExtensionBridge.cacheInvalidate(url, mode) for each attached source
3. → Re-extract (transparent cache miss since entry was just invalidated)
```

### Content Viewer Editing Flow

```
1. User opens content viewer (click "View")
2. ContentViewer.show(ctx) renders textarea per page
3. User edits text
4. On input (debounced 500ms):
   a. Update _state.pages[currentPage]
   b. Mark page as edited: _state.editedFlags[currentPage] = true
   c. Store original: _state.originals[currentPage] (only first time)
   d. Update char/word counts
5. On page navigation (Prev/Next): current page edits auto-saved to _state
6. On modal close:
   a. Write edited pages back to _context.sources[i].content
   b. Rebuild merged _context.content
   c. For each edited page: ExtensionBridge.cacheStore(url, mode, updatedData)
7. "Reset" button: restore _state.pages[i] from _state.originals[i]
```

## Implementation Tasks

### Phase 1: Cache Class in Service Worker

**Task 1.1**: Add `ExtractionCache` class inline in service-worker.js
- LRU Map with dual cap: 100 entries AND ~50MB content size
- Methods: get, set, delete, invalidateByTabId, invalidateByUrl, batchLookup, clear, size, keys
- `_tabUrls` reverse map (tabId → Set of urls) for efficient invalidation
- Cache key format: `url + "|" + mode`
- Entry shape: `{ url, mode, tabId, content, title, wordCount, charCount, contentType, extractionMethod, isOcr, timestamp }`
- On get(): move entry to end of Map (LRU promotion)
- On set(): evict oldest if over entry/size cap, update _tabUrls

**Task 1.2**: Instantiate cache: `var extractionCache = new ExtractionCache(100);`

### Phase 2: Transparent Cache in handleOperation()

**Task 2.1**: Add cache check/store for EXTRACT_CURRENT_PAGE
- After resolving the active tab (to get tab.url), check `extractionCache.get(tab.url + '|dom')`
- If hit: return cached result directly (skip extraction)
- If miss: extract, then `extractionCache.set(tab.url + '|dom', result)`, return result
- Note: Must resolve tab URL before cache check. Extract the tab-resolution logic from
  handleExtractCurrentPage into a helper, or do a quick `chromeApi.tabs.query()` first.

**Task 2.2**: Add cache check/store for EXTRACT_TAB
- Get tab URL via `chromeApi.tabs.get(payload.tabId)`
- Check `extractionCache.get(tab.url + '|dom')`
- If hit: return cached result. If miss: extract, cache, return.

**Task 2.3**: Add tab change listeners for invalidation
- `chrome.tabs.onUpdated.addListener(function(tabId, changeInfo) { ... })`
  - ONLY on `changeInfo.url` (not every update event — title/favicon changes are frequent)
  - Call `extractionCache.invalidateByTabId(tabId)`
- `chrome.tabs.onRemoved.addListener(function(tabId) { ... })`
  - Call `extractionCache.invalidateByTabId(tabId)`

**Task 2.4**: Add new operation handlers to handleOperation switch
- `CACHE_STORE`: `extractionCache.set(payload.url + '|' + payload.mode, payload.data)` — for OCR results from client
- `CACHE_BATCH_LOOKUP`: `extractionCache.batchLookup(payload.entries)` — returns `[{url, mode, hit, data?}]`
- `CACHE_INVALIDATE`: invalidate by url+mode or url-only
- `CACHE_CLEAR`: `extractionCache.clear()`

### Phase 3: ExtensionBridge Client Methods

**Task 3.1**: Add 4 new methods to ExtensionBridge
- `cacheStore(url, mode, data)` → sends `CACHE_STORE` message, 5000ms timeout
- `cacheBatchLookup(entries)` → sends `CACHE_BATCH_LOOKUP` message, 5000ms timeout
  - entries: `[{ url, mode }]`, returns `{ results: [{ url, mode, hit, data? }] }`
- `cacheInvalidate(url, mode)` → sends `CACHE_INVALIDATE` message, 5000ms timeout
- `cacheClear()` → sends `CACHE_CLEAR` message, 5000ms timeout
- All use request-response (non-streaming)

### Phase 4: PageContextManager Cache Integration

**Task 4.1**: `#ext-extract-page` click handler — NO CHANGES NEEDED
- Cache check happens transparently in the service worker's handleOperation()
- Client code calls `ExtensionBridge.extractCurrentPage()` as before
- Service worker returns cached result or fresh extraction — client can't tell the difference
- Toast can optionally indicate "(cached)" if result has a `cached: true` flag

**Task 4.2**: Update `#ext-refresh-page` click handler
- Call `ExtensionBridge.cacheInvalidate(url)` for the currently attached URL before re-extracting
- Need current URL: read from `_context.url` (already stored)
- Toast: "Page context refreshed" (same as current)

**Task 4.3**: `#page-context-clear` — no cache changes needed (already just clears _context)

### Phase 5: TabPickerManager Cache Integration

**Task 5.1**: Update `_startCapture()` to batch-check cache
- Before building `tabDescriptors`, call `ExtensionBridge.cacheBatchLookup(selected.map(...))`
- Partition into cachedResults[] and uncachedTabs[]
- Only send uncachedTabs to `captureMultiTab` (keep multi-tab pipeline even for 1 tab — per Oracle)
- Merge cached + fresh in `_assembleResults()`

**Task 5.2**: After OCR assembly, call `CACHE_STORE`
- In `_assembleResults()`, for each tab that had OCR:
  - `ExtensionBridge.cacheStore(tab.url, tab.mode, { content: ocrText, title, ... })`
- Fire-and-forget (don't await — caching is best-effort)

**Task 5.3**: Show "(cached)" indicator in Tab Picker list
- After rendering tabs, do a batch lookup for all visible tabs (all modes)
- Add small "cached" badge next to tabs that have cached content

### Phase 6: Editable Content Viewer

**Task 6.1**: Replace `<pre id="cv-text">` with `<textarea id="cv-text">` in interface.html
- Same styling (monospace, same font, colors, border)
- Add `resize: vertical` CSS
- Remove `user-select: text` (textarea handles this natively)

**Task 6.2**: Add editing state to ContentViewer._state
- `_state.originals = []` — original page text (set on first edit per page)
- `_state.editedFlags = []` — boolean per page, true if edited
- `_state.editCallback = null` — debounced input handler

**Task 6.3**: Update `_render()` for textarea
- Change `$('#cv-text').text(displayText)` to `$('#cv-text').val(displayText)`
- Make textarea readonly when showing "All" view
- Make textarea editable when showing individual pages

**Task 6.4**: Add input handler for editing
- On `input` event (debounced 500ms): save current text to `_state.pages[currentPage]`
- On first edit: store original in `_state.originals[currentPage]`
- Set `_state.editedFlags[currentPage] = true`
- Update char/word counts immediately

**Task 6.5**: Add "Reset" and "(edited)" indicator to UI
- Add "Reset" button in modal footer (visible only when current page is edited)
- Add "(edited)" text next to page indicator when current page is edited
- Reset restores `_state.pages[i]` from `_state.originals[i]`, clears editedFlag

**Task 6.6**: Save edits on modal close
- On close/hide: write back edited pages to the context object passed to show()
- If `ctx.sources` exists (multi-tab): update `sources[i].content`
- Rebuild merged `ctx.content`
- For each edited page: fire `ExtensionBridge.cacheStore(url, mode, updatedData)` (fire-and-forget)
- Update PageContextManager's `_context` with edited content

### Phase 7: Documentation

**Task 7.1**: Create feature documentation at `documentation/features/extension/extraction_cache.md`
- Describes cache architecture, operations, invalidation rules
- Documents the two-level cache alternative for future reference
- Lists files modified and API details

## Files to Modify

| File | Changes |
|------|---------|
| `extension-iframe/background/service-worker.js` | ExtractionCache class, cache in handleOperation, tab listeners, new ops |
| `interface/extension-bridge.js` | Add cacheStore, cacheBatchLookup, cacheInvalidate, cacheClear methods |
| `interface/page-context-manager.js` | Refresh handler invalidates cache; updateSourceContent method |
| `interface/tab-picker-manager.js` | Batch lookup before capture, CACHE_STORE after OCR, cached badge |
| `interface/content-viewer.js` | Textarea, editing state, input handler, reset, save-on-close |
| `interface/interface.html` | Replace `<pre>` with `<textarea>`, add Reset button, edited indicator |
| `documentation/features/extension/extraction_cache.md` | **NEW** — Feature documentation |

## Risks and Alternatives

### Risk: Service worker restart clears in-memory cache
Chrome may kill the service worker after ~30s of inactivity. The Map-based cache would be lost.
**Mitigation**: Acceptable — cache is a performance optimization, not correctness. Extraction still works on miss. DOM extraction takes ~200ms. The SW stays alive during active `chrome.runtime.connect()` ports (streaming ops) and any `sendMessage` wakes it. In practice SW stays alive while user is actively using UI.
**Future**: Persist to `chrome.storage.session` (MV3 session storage, cleared on browser restart, 10MB limit) if frequent misses observed.

### Risk: Cache key collision
Two different pages could have the same URL (e.g., SPA with client-side routing that doesn't update URL).
**Mitigation**: Unlikely edge case. URL is the most natural cache key — same URL = same content is what users expect. `chrome.tabs.onUpdated` invalidation handles navigation.

### Risk: Memory pressure from OCR text cache
100 entries × multi-page OCR could be significant. Dual cap (100 entries + 50MB byte size) mitigates this.
**Mitigation**: byte-size cap enforced alongside entry count. Eviction is LRU — oldest entries dropped first.

### Risk: chrome.tabs.onUpdated fires frequently
Tab updates include title changes, favicon changes, loading status — not just URL changes.
**Mitigation**: Only invalidate when `changeInfo.url` is present (URL actually changed).

### Alternative: Two-Level Cache (Future Enhancement)
Add a second cache layer in `PageContextManager` (client-side) for even faster lookups:
- Client cache checked first (no extension message needed — zero round-trip)
- Extension cache checked second (cross-UI sharing, ~1-5ms round-trip)
- Fresh extraction last
This would eliminate the message round-trip for cache lookups in the common case. Deferred to future iteration since the extension message overhead is ~1-5ms.

### Alternative: Persist cache to chrome.storage.session
MV3 session storage survives service worker restarts (cleared on browser restart). 10MB limit. Adds async overhead to every cache operation. Deferred to future iteration — only if frequent SW termination observed.

### Alternative: Cross-UI edit sync via chrome.storage.onChanged
Currently edits in main UI won't propagate to iframe in real-time. Could add `chrome.storage.onChanged` listener or `BroadcastChannel` for aggressive sync. Deferred — same user rarely edits in both contexts concurrently.
