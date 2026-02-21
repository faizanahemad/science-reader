/**
 * Service Worker for AI Assistant Iframe Sidepanel Extension
 *
 * Provides Chrome API operations (page extraction, tab listing, screenshots,
 * OCR capture, script execution) to the main UI loaded inside the sidepanel
 * iframe. Communication via externally_connectable:
 *   - onMessageExternal for request-response operations
 *   - onConnectExternal for streaming operations (progress events)
 *
 * Operation handler logic is imported from the shared operations-handler.js
 * module (extension-shared/).
 *
 * Also preserves sidepanel open behavior from the original background.js.
 */

import {
    handlePing, handleListTabs, handleGetTabInfo,
    handleExtractCurrentPage, handleExtractTab,
    handleCaptureScreenshot, handleCaptureFullPage,
    handleCaptureFullPageWithOcr, handleCaptureMultiTab,
    handleExecuteScript
} from './operations-handler.js';

var P = '[IframeSW]';
console.log(P, '=== SERVICE WORKER LOADING ===');
console.log(P, 'chrome.runtime.id:', chrome.runtime.id);

// ==================== Extraction Cache (LRU) ====================

/**
 * ExtractionCache — In-memory LRU cache for tab extraction results.
 *
 * Shared across all UI clients (main UI tab + iframe sidepanel) because it
 * lives in the service worker. Caches DOM extraction results transparently
 * and OCR text results when explicitly stored by the client.
 *
 * Dual eviction: entry count (maxEntries) AND total content byte size
 * (maxBytes). Whichever limit is hit first triggers LRU eviction.
 *
 * Cache key format: "url|mode" (e.g., "https://example.com|dom").
 *
 * Maintains a reverse map (_tabUrls: tabId → Set<url>) so that
 * chrome.tabs.onUpdated and onRemoved can efficiently invalidate entries
 * for a specific tab without scanning all entries.
 */
class ExtractionCache {
    /**
     * @param {number} maxEntries - Maximum number of cache entries (default 100).
     * @param {number} maxBytes   - Maximum total content byte size (default ~50MB).
     */
    constructor(maxEntries, maxBytes) {
        this._maxEntries = maxEntries || 100;
        this._maxBytes = maxBytes || 50 * 1024 * 1024;
        this._map = new Map();      // key → entry (insertion order = LRU order)
        this._tabUrls = new Map();  // tabId → Set<url>
        this._totalBytes = 0;
    }

    /**
     * Estimate byte size of a cache entry's content.
     * Uses string length as proxy (JS strings are ~2 bytes/char but this is
     * an approximation — good enough for eviction decisions).
     * @param {Object} entry - Cache entry.
     * @returns {number} Estimated byte size.
     */
    _estimateBytes(entry) {
        var content = (entry && entry.content) || '';
        return content.length * 2;
    }

    /**
     * Evict oldest entries until both entry count and byte size are under limits.
     * Called internally by set().
     */
    _evictIfNeeded() {
        while (this._map.size > this._maxEntries || this._totalBytes > this._maxBytes) {
            var oldest = this._map.keys().next();
            if (oldest.done) break;
            this.delete(oldest.value);
        }
    }

    /**
     * Update the tabId → url reverse map when adding an entry.
     * @param {number|undefined} tabId - Browser tab ID.
     * @param {string} url - Page URL.
     */
    _trackTabUrl(tabId, url) {
        if (tabId == null) return;
        var urls = this._tabUrls.get(tabId);
        if (!urls) {
            urls = new Set();
            this._tabUrls.set(tabId, urls);
        }
        urls.add(url);
    }

    /**
     * Remove a URL from the tabId reverse map.
     * @param {number|undefined} tabId - Browser tab ID.
     * @param {string} url - Page URL.
     */
    _untrackTabUrl(tabId, url) {
        if (tabId == null) return;
        var urls = this._tabUrls.get(tabId);
        if (urls) {
            urls.delete(url);
            if (urls.size === 0) this._tabUrls.delete(tabId);
        }
    }

    /**
     * Retrieve a cached entry by key. Promotes entry to most-recent (LRU).
     * @param {string} key - Cache key ("url|mode").
     * @returns {Object|null} Cached entry data or null if miss.
     */
    get(key) {
        var entry = this._map.get(key);
        if (!entry) return null;
        // LRU promotion: delete and re-insert to move to end
        this._map.delete(key);
        this._map.set(key, entry);
        return entry;
    }

    /**
     * Store an entry in the cache. Evicts oldest if over capacity.
     * @param {string} key   - Cache key ("url|mode").
     * @param {Object} value - Entry data. Should include: url, mode, tabId, content,
     *                         title, wordCount, charCount, contentType, extractionMethod,
     *                         isOcr, timestamp.
     */
    set(key, value) {
        // If replacing existing entry, subtract its bytes first
        var existing = this._map.get(key);
        if (existing) {
            this._totalBytes -= this._estimateBytes(existing);
            this._untrackTabUrl(existing.tabId, existing.url);
            this._map.delete(key);
        }
        value.timestamp = value.timestamp || Date.now();
        this._map.set(key, value);
        this._totalBytes += this._estimateBytes(value);
        this._trackTabUrl(value.tabId, value.url);
        this._evictIfNeeded();
    }

    /**
     * Delete a single cache entry by key.
     * @param {string} key - Cache key.
     * @returns {boolean} True if entry existed and was deleted.
     */
    delete(key) {
        var entry = this._map.get(key);
        if (!entry) return false;
        this._totalBytes -= this._estimateBytes(entry);
        this._untrackTabUrl(entry.tabId, entry.url);
        this._map.delete(key);
        return true;
    }

    /**
     * Invalidate all cache entries associated with a tab ID.
     * Used by chrome.tabs.onUpdated (URL change) and onRemoved.
     * @param {number} tabId - Browser tab ID.
     * @returns {number} Number of entries removed.
     */
    invalidateByTabId(tabId) {
        var urls = this._tabUrls.get(tabId);
        if (!urls) return 0;
        var removed = 0;
        var urlList = Array.from(urls);
        for (var i = 0; i < urlList.length; i++) {
            removed += this.invalidateByUrl(urlList[i]);
        }
        this._tabUrls.delete(tabId);
        return removed;
    }

    /**
     * Invalidate all cache entries for a given URL (all modes).
     * @param {string} url - Page URL.
     * @returns {number} Number of entries removed.
     */
    invalidateByUrl(url) {
        var removed = 0;
        var modes = ['dom', 'ocr', 'full-ocr'];
        for (var i = 0; i < modes.length; i++) {
            if (this.delete(url + '|' + modes[i])) removed++;
        }
        return removed;
    }

    /**
     * Batch lookup: check cache for multiple url+mode pairs in one call.
     * @param {Array} entries - Array of { url, mode }.
     * @returns {Array} Array of { url, mode, hit, data? } in same order.
     */
    batchLookup(entries) {
        var results = [];
        for (var i = 0; i < entries.length; i++) {
            var key = entries[i].url + '|' + entries[i].mode;
            var entry = this.get(key);
            results.push({
                url: entries[i].url,
                mode: entries[i].mode,
                hit: entry !== null,
                data: entry || undefined
            });
        }
        return results;
    }

    /**
     * Clear all entries.
     * @returns {number} Number of entries removed.
     */
    clear() {
        var count = this._map.size;
        this._map.clear();
        this._tabUrls.clear();
        this._totalBytes = 0;
        return count;
    }

    /** @returns {number} Current number of entries. */
    get size() { return this._map.size; }

    /** @returns {number} Current estimated total bytes. */
    get totalBytes() { return this._totalBytes; }

    /** @returns {IterableIterator<string>} Iterator of cache keys. */
    keys() { return this._map.keys(); }
}

var extractionCache = new ExtractionCache(100, 50 * 1024 * 1024);
console.log(P, 'ExtractionCache initialized (max 100 entries, ~50MB)');

// ==================== Core State ====================

var captureState = { inProgress: false };
var MAIN_UI_PATTERNS = ['localhost:5000', '127.0.0.1:5000', 'assist-chat.site'];

var chromeApi = {
    tabs: {
        query: function(q) { return chrome.tabs.query(q); },
        get: function(id) { return chrome.tabs.get(id); },
        sendMessage: function(id, msg) { return chrome.tabs.sendMessage(id, msg); },
        update: function(id, props) { return chrome.tabs.update(id, props); },
        captureVisibleTab: function(wid, opts) { return chrome.tabs.captureVisibleTab(wid, opts || { format: 'png' }); }
    },
    scripting: {
        executeScript: function(opts) { return chrome.scripting.executeScript(opts); }
    },
    runtime: { id: chrome.runtime.id }
};

// ==================== Sidepanel Behavior (from old background.js) ====================

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(function() {});

chrome.runtime.onMessage.addListener(function(message, sender, sendResponse) {
    if (message.type === 'OPEN_SIDEPANEL' && sender.tab) {
        chrome.sidePanel.open({ tabId: sender.tab.id })
            .then(function() { sendResponse({ success: true }); })
            .catch(function(err) { sendResponse({ success: false, error: err.message }); });
        return true;
    }
});

// ==================== Request-Response (onMessageExternal) ====================

chrome.runtime.onMessageExternal.addListener(function(msg, sender, sendResponse) {
    var senderUrl = sender.url || (sender.tab && sender.tab.url) || '';
    if (!MAIN_UI_PATTERNS.some(function(p) { return senderUrl.includes(p); })) {
        sendResponse({ success: false, error: { code: 'UNAUTHORIZED', message: 'Sender not allowed' } });
        return true;
    }

    var type = msg.type;
    var payload = msg.payload;
    handleOperation(type, payload)
        .then(function(result) {
            sendResponse({ success: true, payload: result });
        })
        .catch(function(err) {
            sendResponse({
                success: false,
                error: { code: err.code || 'UNKNOWN', message: err.message || String(err) }
            });
        });
    return true;
});

// ==================== Streaming (onConnectExternal) ====================

chrome.runtime.onConnectExternal.addListener(function(port) {
    console.log(P, 'External port connected');
    port.onMessage.addListener(function(msg) {
        var type = msg.type;
        var payload = msg.payload;
        var requestId = msg.requestId;

        var onProgress = function(progressPayload) {
            try {
                port.postMessage({ type: 'PROGRESS', requestId: requestId, payload: progressPayload });
            } catch (_) {}
        };

        handleOperation(type, payload, onProgress)
            .then(function(result) {
                try {
                    port.postMessage({ type: 'RESPONSE', requestId: requestId, success: true, payload: result });
                } catch (_) {}
            })
            .catch(function(err) {
                try {
                    port.postMessage({
                        type: 'RESPONSE', requestId: requestId, success: false,
                        error: { code: err.code || 'UNKNOWN', message: err.message || String(err) }
                    });
                } catch (_) {}
            });
    });
});

// ==================== Cache-Aware Extraction Helpers ====================

/**
 * Resolve the active non-UI tab. Used by EXTRACT_CURRENT_PAGE cache check
 * to get the URL before deciding whether to extract or return cached.
 * @returns {Promise<Object>} Chrome tab object with id, url, title, etc.
 */
async function _resolveActiveNonUITab() {
    var tabs = await chromeApi.tabs.query({ active: true, lastFocusedWindow: true });
    for (var i = 0; i < tabs.length; i++) {
        var url = tabs[i].url || '';
        if (!MAIN_UI_PATTERNS.some(function(p) { return url.includes(p); })) {
            return tabs[i];
        }
    }
    var allTabs = await chromeApi.tabs.query({ lastFocusedWindow: true });
    for (var j = 0; j < allTabs.length; j++) {
        var u = allTabs[j].url || '';
        if (!MAIN_UI_PATTERNS.some(function(p) { return u.includes(p); })) {
            return allTabs[j];
        }
    }
    return null;
}

/**
 * Extract current page with transparent cache. Checks cache by resolved tab URL
 * before delegating to the handler. Caches result on miss.
 * @returns {Promise<Object>} Extraction result (cached or fresh).
 */
async function _cachedExtractCurrentPage() {
    var tab = await _resolveActiveNonUITab();
    if (tab && tab.url) {
        var cacheKey = tab.url + '|dom';
        var cached = extractionCache.get(cacheKey);
        if (cached) {
            console.log(P, 'Cache HIT for EXTRACT_CURRENT_PAGE:', tab.url);
            cached.cached = true;
            return cached;
        }
    }
    var result = await handleExtractCurrentPage(chromeApi, MAIN_UI_PATTERNS);
    if (result && result.url) {
        var key = result.url + '|dom';
        result.tabId = result.tabId || (tab && tab.id);
        extractionCache.set(key, Object.assign({}, result, { mode: 'dom' }));
        console.log(P, 'Cache STORE for EXTRACT_CURRENT_PAGE:', result.url, '| entries:', extractionCache.size);
    }
    return result;
}

/**
 * Extract a specific tab with transparent cache. Checks cache by tab URL
 * before delegating to the handler. Caches result on miss.
 * @param {Object} payload - { tabId }.
 * @returns {Promise<Object>} Extraction result (cached or fresh).
 */
async function _cachedExtractTab(payload) {
    var tab = await chromeApi.tabs.get(payload.tabId);
    if (tab && tab.url) {
        var cacheKey = tab.url + '|dom';
        var cached = extractionCache.get(cacheKey);
        if (cached) {
            console.log(P, 'Cache HIT for EXTRACT_TAB:', tab.url);
            cached.cached = true;
            return cached;
        }
    }
    var result = await handleExtractTab(chromeApi, payload);
    if (result && result.url) {
        var key = result.url + '|dom';
        extractionCache.set(key, Object.assign({}, result, { mode: 'dom' }));
        console.log(P, 'Cache STORE for EXTRACT_TAB:', result.url, '| entries:', extractionCache.size);
    }
    return result;
}

// ==================== Operation Dispatcher ====================

async function handleOperation(type, payload, onProgress) {
    switch (type) {
        case 'PING':
            return handlePing(chromeApi);
        case 'LIST_TABS':
            return handleListTabs(chromeApi, MAIN_UI_PATTERNS);
        case 'GET_TAB_INFO':
            return handleGetTabInfo(chromeApi, MAIN_UI_PATTERNS);
        case 'EXTRACT_CURRENT_PAGE':
            return _cachedExtractCurrentPage();
        case 'EXTRACT_TAB':
            return _cachedExtractTab(payload);
        case 'CAPTURE_SCREENSHOT':
            return handleCaptureScreenshot(chromeApi, payload, captureState);
        case 'CAPTURE_FULL_PAGE':
            return handleCaptureFullPage(chromeApi, payload, captureState, onProgress);
        case 'CAPTURE_FULL_PAGE_WITH_OCR':
            return handleCaptureFullPageWithOcr(chromeApi, payload, captureState, onProgress);
        case 'CAPTURE_MULTI_TAB':
            return handleCaptureMultiTab(chromeApi, payload, captureState, onProgress);
        case 'EXECUTE_SCRIPT':
            return handleExecuteScript(chromeApi, payload);

        // Cache management operations
        case 'CACHE_STORE':
            return _handleCacheStore(payload);
        case 'CACHE_BATCH_LOOKUP':
            return _handleCacheBatchLookup(payload);
        case 'CACHE_INVALIDATE':
            return _handleCacheInvalidate(payload);
        case 'CACHE_CLEAR':
            return _handleCacheClear();

        default:
            throw { code: 'UNKNOWN', message: 'Unknown operation: ' + type };
    }
}

// ==================== Cache Operation Handlers ====================

function _handleCacheStore(payload) {
    if (!payload || !payload.url || !payload.mode) {
        throw { code: 'INVALID_PARAMS', message: 'CACHE_STORE requires url and mode' };
    }
    var key = payload.url + '|' + payload.mode;
    var data = payload.data || {};
    data.url = payload.url;
    data.mode = payload.mode;
    data.tabId = data.tabId || payload.tabId;
    extractionCache.set(key, data);
    console.log(P, 'CACHE_STORE:', key, '| entries:', extractionCache.size);
    return { success: true, key: key, cacheSize: extractionCache.size };
}

function _handleCacheBatchLookup(payload) {
    if (!payload || !Array.isArray(payload.entries)) {
        throw { code: 'INVALID_PARAMS', message: 'CACHE_BATCH_LOOKUP requires entries array' };
    }
    var results = extractionCache.batchLookup(payload.entries);
    return { results: results };
}

function _handleCacheInvalidate(payload) {
    if (!payload || !payload.url) {
        throw { code: 'INVALID_PARAMS', message: 'CACHE_INVALIDATE requires url' };
    }
    var removed;
    if (payload.mode) {
        removed = extractionCache.delete(payload.url + '|' + payload.mode) ? 1 : 0;
    } else {
        removed = extractionCache.invalidateByUrl(payload.url);
    }
    console.log(P, 'CACHE_INVALIDATE:', payload.url, payload.mode || '(all modes)', '| removed:', removed);
    return { success: true, removed: removed };
}

function _handleCacheClear() {
    var removed = extractionCache.clear();
    console.log(P, 'CACHE_CLEAR: removed', removed, 'entries');
    return { success: true, removed: removed };
}

// ==================== Tab Change Listeners (Cache Invalidation) ====================

chrome.tabs.onUpdated.addListener(function(tabId, changeInfo) {
    if (changeInfo.url) {
        var removed = extractionCache.invalidateByTabId(tabId);
        if (removed > 0) {
            console.log(P, 'Cache invalidated on tab URL change:', tabId, '→', changeInfo.url, '| removed:', removed);
        }
    }
});

chrome.tabs.onRemoved.addListener(function(tabId) {
    var removed = extractionCache.invalidateByTabId(tabId);
    if (removed > 0) {
        console.log(P, 'Cache invalidated on tab close:', tabId, '| removed:', removed);
    }
});

console.log(P, '=== SERVICE WORKER INITIALIZED ===');
