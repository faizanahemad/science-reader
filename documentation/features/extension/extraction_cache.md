# Extraction Cache and Editable Content Viewer

**Feature**: LRU extraction cache in service worker + editable content viewer with per-page editing  
**Status**: Implemented  
**Last Updated**: February 21, 2026

---

## 1. Overview

Two features that improve the page context workflow in the extension:

**Extraction Cache** is an in-memory LRU cache in the service worker that stores extracted page content (DOM text and OCR results). It prevents redundant extractions when the user switches between tabs or re-opens the same page. Both the main extension UI and the iframe UI share the cache transparently through the service worker message bus.

**Editable Content Viewer** replaces the read-only `<pre>` element in the content viewer modal with a `<textarea>`, letting users edit extracted content on a per-page basis before sending it to the LLM. Edits persist across page navigation within the modal and flow back into the `_context` object on close, so `getPageContextForPayload()` picks them up automatically.

---

## 2. Extraction Cache

### Architecture

The cache lives as an `ExtractionCache` class instance inside `extension-iframe/background/service-worker.js`. It wraps a JavaScript `Map` used as an LRU structure (delete-then-re-insert on access to maintain recency order). Every extraction request from any UI surface passes through the service worker's `handleOperation()`, which checks the cache before doing real work.

### Cache Key Format

Each entry is keyed by `url + "|" + mode`, where mode is one of `dom`, `ocr`, or `full-ocr`. This means the same URL can have separate cached entries for different extraction modes.

### Eviction Strategy

The cache enforces two independent limits:

| Limit | Value | Behavior |
|-------|-------|----------|
| Entry count | 100 | Oldest entry evicted when a new insert would exceed 100 |
| Total content bytes | ~50MB | Oldest entries evicted until total bytes drop below threshold |

Both checks run on every insert. Eviction always removes the least-recently-used entry first (front of the Map iteration order).

### Transparent Caching (DOM Extractions)

For `EXTRACT_CURRENT_PAGE` and `EXTRACT_TAB` operations, caching is handled entirely inside `handleOperation()` in the service worker. The client code (page-context-manager, tab-picker-manager) doesn't know caching exists. The flow:

1. `handleOperation()` receives the extraction request.
2. It builds the cache key from the tab's URL and the extraction mode.
3. On cache hit, it returns the cached content immediately.
4. On cache miss, it performs the real extraction, stores the result, and returns it.

### Explicit Caching (OCR Results)

OCR extractions go through the `/ext/ocr` server endpoint, which the client calls directly. The service worker can't intercept this. Instead, after the client receives OCR text back from the server, it explicitly sends a `CACHE_STORE` message to the service worker with the URL, mode, and extracted text. This keeps OCR results available for subsequent lookups without re-running OCR.

### Batch Lookup for Tab Picker

The Tab Picker modal does a `CACHE_BATCH_LOOKUP` before starting multi-tab capture. It sends all selected tab URLs with their intended capture modes. The service worker checks each against the cache and returns hit/miss status per entry. Tabs with cache hits are skipped entirely during capture, saving significant time when re-capturing a set of tabs where only a few have changed.

### Cache Invalidation

Invalidation happens through three mechanisms:

**Automatic (tab events)**:
- `chrome.tabs.onUpdated`: When a tab's URL changes, all cache entries for the old URL are invalidated.
- `chrome.tabs.onRemoved`: When a tab is closed, all cache entries associated with that tab's URLs are invalidated.

**Manual**:
- `CACHE_INVALIDATE` operation: Removes entries for a specific URL (optionally filtered by mode).
- `CACHE_CLEAR` operation: Wipes the entire cache.

### Reverse Map for Tab-Based Invalidation

A `_tabUrls` map (tabId to Set of URLs) tracks which URLs have been cached for each tab. When a tab event fires, the service worker looks up the tab's URL set and invalidates all matching cache entries without scanning the entire cache. This keeps invalidation O(1) relative to the number of URLs per tab rather than O(n) over all cached entries.

### Refresh vs. Clear Button Behavior

| Button | ID | Behavior |
|--------|----|----------|
| Refresh (header) | `ext-refresh-page` | Invalidates cache for current URL, then re-extracts |
| Refresh (context panel) | `page-context-refresh` | Same: invalidate first, then re-extract |
| Clear (context panel) | `page-context-clear` | Clears `_context` object only. Cache is untouched. |

The distinction matters: clearing context is a UI-level reset, while refresh forces a fresh extraction from the page.

### Service Worker Lifecycle

The cache is purely in-memory. Chrome terminates idle service workers after roughly 30 seconds of inactivity. When the service worker restarts, the cache is empty. This is acceptable because the cache is a performance optimization, not a persistence layer. The first extraction after a cold start simply repopulates the cache.

---

## 3. New Extension Operations

These operations are handled by the service worker's message listener:

| Operation | Direction | Parameters | Response |
|-----------|-----------|------------|----------|
| `CACHE_STORE` | Client to SW | `{url, mode, data}` | `{success, key, cacheSize}` |
| `CACHE_BATCH_LOOKUP` | Client to SW | `{entries: [{url, mode}]}` | `{results: [{url, mode, hit, data?}]}` |
| `CACHE_INVALIDATE` | Client to SW | `{url, mode?}` | `{success, removed}` |
| `CACHE_CLEAR` | Client to SW | `{}` | `{success, removed}` |

`CACHE_STORE` returns the computed cache key and current cache size for debugging. `CACHE_BATCH_LOOKUP` returns results in the same order as the input entries array, with `data` present only on hits. `CACHE_INVALIDATE` accepts an optional `mode` parameter; omitting it removes all modes for that URL. `CACHE_CLEAR` returns the count of entries removed.

---

## 4. New ExtensionBridge Methods

Four methods added to `interface/extension-bridge.js` for use by the main web UI's page context system:

| Method | Signature | Purpose |
|--------|-----------|---------|
| `cacheStore` | `cacheStore(url, mode, data)` | Store extraction result in SW cache |
| `cacheBatchLookup` | `cacheBatchLookup(entries)` | Check multiple URL+mode pairs at once |
| `cacheInvalidate` | `cacheInvalidate(url, mode)` | Remove cached entries for a URL |
| `cacheClear` | `cacheClear()` | Clear entire extraction cache |

All methods return Promises that resolve with the service worker's response object. They use the existing `ExtensionBridge` message-passing channel (postMessage to the extension iframe, which relays to the service worker).

---

## 5. Editable Content Viewer

### UI Change

The `#content-viewer-modal` previously displayed extracted content in a `<pre>` element. This has been replaced with a `<textarea>` that allows direct editing. The textarea preserves monospace formatting and matches the previous visual appearance.

### Per-Page Editing

In paginated view (when content has multiple pages or tabs), each page is independently editable. The "All" view remains read-only since it concatenates all pages and editing a merged view would be ambiguous about which source to update.

### Editing State

Three arrays track editing:

- `_state.pages[]`: The current content for each page (modified in place when the user edits).
- `_state.originals[]`: A snapshot of each page's content at load time, used for reset.
- `_state.editedFlags[]`: Boolean per page, set to `true` when content diverges from the original.

### Input Handling

A debounced input handler (500ms delay) fires on textarea changes. It compares the current textarea value against `_state.originals[currentPage]` and updates `_state.pages[currentPage]` and the corresponding edited flag. This avoids excessive state updates during rapid typing while still capturing edits reliably.

### Visual Indicators

When a page has been edited, two things appear:

- An "(edited)" text indicator next to the page number in the pagination bar.
- A "Reset Page" button in the modal footer that reverts the current page to its original content.

Clicking "Reset Page" restores `_state.originals[i]` into both the textarea and `_state.pages[i]`, clears the edited flag, and removes the visual indicators.

### Saving Edits on Close

When the modal closes, `_saveEditsToContext()` writes any edited pages back into the `_context` object. It handles three content structures:

| Source Type | How edits are written |
|-------------|----------------------|
| Multi-tab sources | Strips the header line from the edited text, writes to `sources[i].content` |
| OCR pages | Writes to `ocrPagesData[i].text` |
| Single content | Writes directly to `_context.content` |

### Automatic Flow to Chat

No additional wiring is needed. `getPageContextForPayload()` reads from `_context` when building the chat request payload. Since `_saveEditsToContext()` modifies `_context` in place, edits are included in the next message automatically.

### Scroll Position Preservation

When navigating between pages in the paginated view, the textarea's `scrollTop` is saved before switching and restored after loading the new page's content. This prevents the jarring jump-to-top that would otherwise happen on every page change.

---

## 6. Files Modified

| File | Changes |
|------|---------|
| `extension-iframe/background/service-worker.js` | `ExtractionCache` class with LRU Map, dual eviction (count + bytes), `_tabUrls` reverse map, cached extraction helpers wrapping `handleOperation()`, `CACHE_STORE` / `CACHE_BATCH_LOOKUP` / `CACHE_INVALIDATE` / `CACHE_CLEAR` operation handlers, `chrome.tabs.onUpdated` and `chrome.tabs.onRemoved` listeners for automatic invalidation |
| `interface/extension-bridge.js` | Four new methods: `cacheStore()`, `cacheBatchLookup()`, `cacheInvalidate()`, `cacheClear()` |
| `interface/page-context-manager.js` | Refresh button handlers (`ext-refresh-page`, `page-context-refresh`) now call `cacheInvalidate()` before re-extracting |
| `interface/tab-picker-manager.js` | `CACHE_BATCH_LOOKUP` before multi-tab capture to skip cached tabs, `CACHE_STORE` after OCR results return from `/ext/ocr` |
| `interface/content-viewer.js` | `<pre>` replaced with `<textarea>` rendering, `_state.originals[]` and `_state.editedFlags[]` arrays, debounced input handler (500ms), "(edited)" pagination indicator, "Reset Page" button, `_saveEditsToContext()` on modal close, scroll position preservation |
| `interface/interface.html` | `<textarea>` element in content viewer modal markup, "(edited)" indicator span, "Reset Page" button in modal footer |

---

## 7. Future Enhancements

**Two-level cache**: Add a client-side cache in `PageContextManager` (L1) for zero round-trip lookups on repeated access. The service worker cache becomes L2. L1 would be a simple object keyed the same way, checked before sending any message to the extension. This eliminates the postMessage overhead for the most common case (viewing the same page repeatedly).

**Persist to chrome.storage.session**: The current in-memory cache is lost when the service worker terminates. `chrome.storage.session` survives SW restarts and has a 10MB limit (expandable to 10MB with `setAccessLevel`). Trade-off: async reads add latency vs. the current synchronous Map lookup, but cache survival across SW restarts could be worth it for users who extract large documents.

**Cross-UI edit sync**: When both the main UI and the extension iframe are open, edits made in one content viewer don't propagate to the other. A `BroadcastChannel` or `chrome.storage.onChanged` listener could sync edits in real time, though the complexity may not be justified unless users frequently have both surfaces open simultaneously.

**Byte-size cap refinement**: The current 50MB total content limit is conservative. Usage telemetry (average extraction size, typical number of cached pages) could inform a tighter or looser cap. For users who primarily extract short pages, 50MB is wasteful as a limit; for users doing full-OCR on long documents, it might be tight.

---

**Version**: 1.0  
**Related**: `extension_design_overview.md` (architecture), `multi_tab_scroll_capture.md` (OCR pipeline), `extension_api.md` (endpoint reference)
