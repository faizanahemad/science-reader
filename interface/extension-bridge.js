/**
 * ExtensionBridge - Promise-based client library for Chrome extension communication.
 *
 * Uses externally_connectable transport via chrome.runtime.sendMessage(extId) for
 * simple request-response operations, and chrome.runtime.connect(extId) for streaming
 * operations (full-page capture, OCR, multi-tab).
 *
 * Extension detection: id-advertiser.js content script sets a data-ai-ext-id
 * DOM attribute at document_start. ExtensionBridge.init() reads this at DOMContentLoaded.
 *
 * Usage:
 *   ExtensionBridge.init();
 *   ExtensionBridge.onAvailabilityChange(function(available) { ... });
 *   ExtensionBridge.extractCurrentPage().then(function(data) { ... });
 */
var ExtensionBridge = (function() {
    'use strict';

    var P = '[ExtBridge]';

    console.log(P, '=== MODULE LOADING ===');
    console.log(P, 'window.location.href:', window.location.href);

    var _available = false;
    var _availabilityCallbacks = [];
    var _progressCallbacks = [];

    var _extId = null;

    function _generateId() {
        return 'req-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
    }

    var STREAMING_OPS = ['CAPTURE_FULL_PAGE', 'CAPTURE_FULL_PAGE_WITH_OCR', 'CAPTURE_MULTI_TAB'];

    function _sendMessage(type, payload, timeoutMs) {
        console.log(P, '_sendMessage:', type, '_available:', _available);
        if (!_available) return Promise.reject(new Error('Extension not available'));
        timeoutMs = timeoutMs || 30000;
        var requestId = _generateId();

        if (STREAMING_OPS.indexOf(type) >= 0) {
            return _sendMessageExternalStreaming(type, payload, requestId, timeoutMs);
        }
        return _sendMessageExternal(type, payload, requestId, timeoutMs);
    }

    function _sendMessageExternal(type, payload, requestId, timeoutMs) {
        console.log(P, '_sendMessageExternal:', type, 'extId:', _extId);
        return new Promise(function(resolve, reject) {
            var timer = setTimeout(function() {
                reject(new Error('Timeout: ' + type));
            }, timeoutMs);
            chrome.runtime.sendMessage(_extId, {
                type: type, payload: payload || {}, requestId: requestId
            }, function(response) {
                clearTimeout(timer);
                if (chrome.runtime.lastError) {
                    reject(new Error(chrome.runtime.lastError.message));
                    return;
                }
                if (response && response.success) {
                    resolve(response.payload);
                } else {
                    reject(response ? response.error : { message: 'No response' });
                }
            });
        });
    }

    function _sendMessageExternalStreaming(type, payload, requestId, timeoutMs) {
        console.log(P, '_sendMessageExternalStreaming:', type, 'extId:', _extId, 'requestId:', requestId, 'timeout:', timeoutMs);
        return new Promise(function(resolve, reject) {
            var port = chrome.runtime.connect(_extId);
            console.log(P, 'port created for', type);
            var timer = setTimeout(function() {
                console.warn(P, 'TIMEOUT for', type, 'after', timeoutMs, 'ms');
                try { port.disconnect(); } catch (_) {}
                reject(new Error('Timeout: ' + type));
            }, timeoutMs);
            port.postMessage({ type: type, payload: payload || {}, requestId: requestId });
            console.log(P, 'postMessage sent:', type);
            port.onMessage.addListener(function(msg) {
                if (msg.requestId !== requestId) {
                    console.warn(P, 'ignoring msg with wrong requestId:', msg.requestId, 'expected:', requestId);
                    return;
                }
                if (msg.type === 'PROGRESS') {
                    console.log(P, 'PROGRESS received for', type, 'step:', msg.payload && msg.payload.step, 'total:', msg.payload && msg.payload.total, 'hasScreenshot:', !!(msg.payload && msg.payload.screenshot));
                    _progressCallbacks.forEach(function(cb) {
                        try { cb(msg.payload); } catch (e) { console.error(P, 'progressCallback threw:', e); }
                    });
                } else if (msg.type === 'RESPONSE') {
                    console.log(P, 'RESPONSE received for', type, 'success:', msg.success, msg.success ? '' : 'error:' + JSON.stringify(msg.error));
                    clearTimeout(timer);
                    try { port.disconnect(); } catch (_) {}
                    if (msg.success) {
                        resolve(msg.payload);
                    } else {
                        reject(msg.error || { message: 'Unknown error' });
                    }
                } else {
                    console.warn(P, 'unknown msg.type from port:', msg.type);
                }
            });
            port.onDisconnect.addListener(function() {
                var lastErr = chrome.runtime.lastError;
                console.log(P, 'port DISCONNECTED for', type, 'lastError:', lastErr ? lastErr.message : 'none');
                clearTimeout(timer);
                if (lastErr) {
                    reject(new Error(lastErr.message));
                }
                // Note: if no lastError, disconnect was initiated by us (after RESPONSE) — do nothing.
            });
        });
    }

    function _notifyAvailability(available) {
        console.log(P, '_notifyAvailability:', available, 'callbacks:', _availabilityCallbacks.length);
        _availabilityCallbacks.forEach(function(cb) {
            try { cb(available); } catch (e) { console.warn(P, 'availability cb error:', e); }
        });
    }

    function _activate(extId) {
        _extId = extId;
        _available = true;
        ExtensionBridge.isAvailable = true;
        console.log(P, 'Extension detected, extId:', extId);
        _notifyAvailability(true);
    }

    return {
        isAvailable: false,

        init: function() {
            console.log(P, '--- init() START ---');
            console.log(P, 'data-ai-ext-id attr:', document.documentElement.getAttribute('data-ai-ext-id'));
            console.log(P, 'isInIframe:', (window !== window.top));

            // id-advertiser.js sets a DOM attribute at document_start.
            // DOM attributes are shared across content script / page worlds.
            var extId = document.documentElement.getAttribute('data-ai-ext-id');
            if (extId) {
                console.log(P, 'init: extension ID found immediately:', extId);
                _activate(extId);
                console.log(P, '--- init() END (immediate) ---');
                return;
            }

            console.log(P, 'init: no attribute found, registering event listener + 3s timeout');

            // Fallback: listen for the CustomEvent (covers edge case where
            // content script injection was delayed, e.g., extension just installed
            // or service worker cold start).
            document.addEventListener('ai-extension-ready', function() {
                if (_available) return;
                var extId = document.documentElement.getAttribute('data-ai-ext-id');
                console.log(P, '>>> EVENT ai-extension-ready, extId:', extId);
                if (extId) {
                    _activate(extId);
                }
            });

            // Timeout: if neither attribute nor event arrives within 3s,
            // extension is not installed or not matching this URL.
            setTimeout(function() {
                if (_available) return;
                console.log(P, 'init: extension not detected after 3s — not available');
                console.log(P, 'init: final attr check:', document.documentElement.getAttribute('data-ai-ext-id'));
            }, 3000);

            console.log(P, '--- init() END (waiting for event or timeout) ---');
        },

        /**
         * Register a callback for extension availability changes.
         * @param {function} cb - Called with (available: boolean).
         */
        onAvailabilityChange: function(cb) {
            _availabilityCallbacks.push(cb);
            // Late subscriber: if already resolved, fire immediately
            if (_available) {
                try { cb(true); } catch (e) { console.warn(P, 'availability cb error:', e); }
            }
        },

        /**
         * Register a callback for progress events during long operations.
         * @param {function} cb - Called with progress payload object.
         */
        onProgress: function(cb) {
            _progressCallbacks.push(cb);
        },

        /**
         * Remove a previously registered progress callback.
         * @param {function} cb - The exact function reference passed to onProgress.
         */
        offProgress: function(cb) {
            var idx = _progressCallbacks.indexOf(cb);
            if (idx >= 0) _progressCallbacks.splice(idx, 1);
        },

        /** Ping the extension to check connectivity. */
        ping: function() { return _sendMessage('PING', {}); },

        /** Extract content from the currently active page/tab. */
        extractCurrentPage: function() { return _sendMessage('EXTRACT_CURRENT_PAGE', {}, 30000); },

        /**
         * Extract content from a specific tab by ID.
         * @param {number} tabId - Browser tab ID.
         */
        extractTab: function(tabId) { return _sendMessage('EXTRACT_TAB', { tabId: tabId }, 30000); },

        /** List all open browser tabs. */
        listTabs: function() { return _sendMessage('LIST_TABS', {}, 5000); },

        /**
         * Capture a screenshot of a tab.
         * @param {number} tabId - Browser tab ID.
         */
        captureScreenshot: function(tabId) { return _sendMessage('CAPTURE_SCREENSHOT', { tabId: tabId }, 30000); },

        /**
         * Capture a full-page screenshot (scrolling capture).
         * @param {number} tabId - Browser tab ID.
         * @param {Object} options - Capture options (format, quality, etc.).
         */
        captureFullPage: function(tabId, options) { return _sendMessage('CAPTURE_FULL_PAGE', { tabId: tabId, options: options }, 120000); },

        /**
         * Capture content from multiple tabs.
         * @param {Array} tabs - Array of tab descriptors ({ tabId, mode }).
         */
        captureMultiTab: function(tabs) { return _sendMessage('CAPTURE_MULTI_TAB', { tabs: tabs }, 300000); },

        /**
         * Execute a script on a tab.
         * @param {number} tabId - Browser tab ID.
         * @param {string} code - JavaScript code to execute.
         * @param {string} action - Action identifier for the script.
         */
        executeScript: function(tabId, code, action) { return _sendMessage('EXECUTE_SCRIPT', { tabId: tabId, code: code, action: action }, 30000); },

        /** Get info about the current tab (URL, title, etc.). */
        getTabInfo: function() { return _sendMessage('GET_TAB_INFO', {}, 5000); },

        /**
         * Capture full-page screenshots with per-screenshot progress for OCR pipelining.
         * Each screenshot arrives via the onProgress callback as { screenshot, pageIndex, step, total }.
         * The final resolved value contains metadata only (no screenshots).
         *
         * @param {number} tabId - Browser tab ID.
         * @param {Object} options - { overlapRatio, scrollDelayMs }.
         * @returns {Promise} Resolves with capture metadata.
         */
        captureFullPageWithOcr: function(tabId, options) {
            return _sendMessage('CAPTURE_FULL_PAGE_WITH_OCR', { tabId: tabId, options: options }, 300000);
        },

        /**
         * Store a result in the extension's extraction cache (e.g., OCR text after
         * client-side processing). Fire-and-forget — caller need not await.
         * @param {string} url  - Page URL.
         * @param {string} mode - Extraction mode ('dom', 'ocr', 'full-ocr').
         * @param {Object} data - Result data ({ content, title, tabId, ... }).
         * @returns {Promise<Object>} { success, key, cacheSize }.
         */
        cacheStore: function(url, mode, data) {
            return _sendMessage('CACHE_STORE', { url: url, mode: mode, data: data }, 5000);
        },

        /**
         * Check the extension cache for multiple url+mode pairs in one round-trip.
         * @param {Array} entries - Array of { url, mode }.
         * @returns {Promise<Object>} { results: [{ url, mode, hit, data? }] }.
         */
        cacheBatchLookup: function(entries) {
            return _sendMessage('CACHE_BATCH_LOOKUP', { entries: entries }, 5000);
        },

        /**
         * Invalidate cache entries for a URL. If mode is provided, invalidates only
         * that url+mode entry; otherwise invalidates all modes for the URL.
         * @param {string} url  - Page URL.
         * @param {string} [mode] - Optional extraction mode.
         * @returns {Promise<Object>} { success, removed }.
         */
        cacheInvalidate: function(url, mode) {
            var payload = { url: url };
            if (mode) payload.mode = mode;
            return _sendMessage('CACHE_INVALIDATE', payload, 5000);
        },

        /**
         * Clear the entire extraction cache.
         * @returns {Promise<Object>} { success, removed }.
         */
        cacheClear: function() {
            return _sendMessage('CACHE_CLEAR', {}, 5000);
        }
    };
})();
