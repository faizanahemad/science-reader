/**
 * Shared Operation Handlers for Chrome Extension Service Workers
 *
 * Canonical shared operation handlers for Chrome extension service workers.
 * Used by extension-iframe (externally_connectable transport) which serves both
 * regular browser tabs and sidepanel iframe contexts.
 *
 * Each exported handler is a standalone async function that accepts:
 *   - chromeApi: Adapter object wrapping chrome.tabs, chrome.scripting, chrome.runtime
 *   - Additional parameters specific to the operation (payload, captureState, onProgress)
 *
 * The chromeApi adapter pattern follows the same approach used by full-page-capture.js,
 * allowing each service-worker to provide its own Chrome API bindings.
 *
 * chromeApi adapter shape:
 *   {
 *     tabs: {
 *       query(q): Promise<Tab[]>,
 *       get(id): Promise<Tab>,
 *       sendMessage(id, msg): Promise<any>,
 *       update(id, props): Promise<Tab>,
 *       captureVisibleTab(windowId, opts): Promise<string>
 *     },
 *     scripting: {
 *       executeScript(opts): Promise<InjectionResult[]>
 *     },
 *     runtime: {
 *       id: string
 *     }
 *   }
 *
 * captureState shape: { inProgress: boolean }
 *   - Each service-worker owns its own captureState object
 *   - Handlers check/set captureState.inProgress as a mutex
 *
 * @module operations-handler
 */

import { captureFullPage } from './full-page-capture.js';

var P = '[OpsHandler]';

// ==================== Utility Functions (internal) ====================

/**
 * Check if a URL belongs to the main UI application.
 *
 * @param {string} url - URL to check
 * @param {string[]} patterns - Array of URL substrings that identify main UI pages
 * @returns {boolean} True if the URL matches any main UI pattern
 */
function isMainUITab(url, patterns) {
    return patterns.some(function(p) { return url && url.includes(p); });
}

/**
 * Check if a URL is a restricted Chrome internal page that cannot be scripted.
 *
 * @param {string} url - URL to check
 * @returns {boolean} True if the URL is restricted (chrome://, about:, etc.)
 */
function isRestrictedUrl(url) {
    return !url ||
        url.startsWith('chrome://') ||
        url.startsWith('chrome-extension://') ||
        url.startsWith('about:') ||
        url.startsWith('devtools://');
}

/**
 * Count the number of words in a text string.
 *
 * @param {string} text - Text to count words in
 * @returns {number} Word count
 */
function countWords(text) {
    if (!text) return 0;
    return text.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * Inject the extractor content script into a tab if not already present.
 * Waits 150ms after injection for the script to initialize.
 *
 * @param {number} tabId - Chrome tab ID to inject into
 * @param {object} chromeApi - Chrome API adapter
 * @throws {{ code: string, message: string }} If injection fails
 */
async function ensureExtractorInjected(tabId, chromeApi) {
    try {
        await chromeApi.scripting.executeScript({
            target: { tabId: tabId },
            files: ['content_scripts/extractor-core.js']
        });
        await new Promise(function(r) { setTimeout(r, 150); });
    } catch (e) {
        throw { code: 'INJECTION_FAILED', message: 'Failed to inject extractor: ' + e.message };
    }
}

/**
 * Find the active non-main-UI tab in the current window.
 * Falls back to any non-main-UI tab if the active one is the main UI itself.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {string[]} mainUIPatterns - URL patterns identifying main UI pages
 * @returns {Promise<object|null>} The target tab object, or null if none found
 */
async function findTargetTab(chromeApi, mainUIPatterns) {
    var tabs = await chromeApi.tabs.query({ currentWindow: true });
    var nonUITabs = tabs.filter(function(t) {
        return !isRestrictedUrl(t.url) && !isMainUITab(t.url, mainUIPatterns);
    });

    // Prefer the active non-UI tab
    var activeNonUI = nonUITabs.find(function(t) { return t.active; });
    if (activeNonUI) return activeNonUI;

    // Fall back to the most recently accessed non-UI tab
    if (nonUITabs.length > 0) return nonUITabs[0];

    return null;
}

// ==================== Simple Operation Handlers ====================

/**
 * Handle PING — returns extension alive status and ID.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @returns {{ alive: boolean, version: number, extensionId: string }}
 */
export function handlePing(chromeApi) {
    return {
        alive: true,
        version: 1,
        extensionId: chromeApi.runtime.id
    };
}

/**
 * Handle LIST_TABS — returns non-restricted, non-main-UI tabs in current window.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {string[]} mainUIPatterns - URL patterns identifying main UI pages
 * @returns {Promise<{ tabs: object[] }>}
 */
export async function handleListTabs(chromeApi, mainUIPatterns) {
    var tabs = await chromeApi.tabs.query({ currentWindow: true });
    var filtered = tabs.filter(function(t) {
        return !isRestrictedUrl(t.url) && !isMainUITab(t.url, mainUIPatterns);
    });

    return {
        tabs: filtered.map(function(t) {
            return {
                id: t.id,
                title: t.title || '',
                url: t.url || '',
                favIconUrl: t.favIconUrl || '',
                active: t.active,
                windowId: t.windowId,
                index: t.index
            };
        })
    };
}

/**
 * Handle GET_TAB_INFO — returns info about the current target tab.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {string[]} mainUIPatterns - URL patterns identifying main UI pages
 * @returns {Promise<{ id: number, title: string, url: string, favIconUrl: string }>}
 * @throws {{ code: string, message: string }} If no suitable tab found
 */
export async function handleGetTabInfo(chromeApi, mainUIPatterns) {
    var tab = await findTargetTab(chromeApi, mainUIPatterns);
    if (!tab) {
        throw { code: 'NO_ACTIVE_TAB', message: 'No non-main-UI active tab found' };
    }
    return {
        id: tab.id,
        title: tab.title || '',
        url: tab.url || '',
        favIconUrl: tab.favIconUrl || ''
    };
}

// ==================== Extraction Handlers ====================

/**
 * Handle EXTRACT_CURRENT_PAGE — extract DOM content from the active non-UI tab.
 * Injects extractor-core.js, sends EXTRACT_PAGE message, returns content with word count.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {string[]} mainUIPatterns - URL patterns identifying main UI pages
 * @returns {Promise<object>} Extraction result with tabId, title, url, content, wordCount, etc.
 * @throws {{ code: string, message: string }} On no tab, restricted page, or extraction failure
 */
export async function handleExtractCurrentPage(chromeApi, mainUIPatterns) {
    var tab = await findTargetTab(chromeApi, mainUIPatterns);
    if (!tab) {
        throw { code: 'NO_ACTIVE_TAB', message: 'No non-main-UI active tab found' };
    }

    if (isRestrictedUrl(tab.url)) {
        throw { code: 'RESTRICTED_PAGE', message: 'Cannot extract content from ' + tab.url };
    }

    await ensureExtractorInjected(tab.id, chromeApi);

    try {
        var result = await chromeApi.tabs.sendMessage(tab.id, { type: 'EXTRACT_PAGE' });
        var content = result.content || '';
        var words = countWords(content);
        console.log(P, 'extractCurrentPage:', tab.title, '|', content.length, 'chars |', words, 'words');
        return {
            tabId: tab.id,
            title: tab.title || '',
            url: tab.url || '',
            content: content,
            wordCount: words,
            charCount: content.length,
            contentType: result.contentType || 'text',
            extractionMethod: (result.meta && result.meta.extractionMethod) || result.extractionMethod || 'generic'
        };
    } catch (e) {
        throw { code: 'EXTRACTION_FAILED', message: 'Extraction failed: ' + e.message };
    }
}

/**
 * Handle EXTRACT_TAB — extract DOM content from a specific tab by ID.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {object} payload - Must contain { tabId: number }
 * @returns {Promise<object>} Extraction result with tabId, title, url, content, wordCount, etc.
 * @throws {{ code: string, message: string }} On missing tabId, tab not found, or extraction failure
 */
export async function handleExtractTab(chromeApi, payload) {
    var tabId = payload && payload.tabId;
    if (!tabId) {
        throw { code: 'TAB_NOT_FOUND', message: 'No tabId provided' };
    }

    var tab;
    try {
        tab = await chromeApi.tabs.get(tabId);
    } catch (e) {
        throw { code: 'TAB_NOT_FOUND', message: 'Tab ' + tabId + ' not found' };
    }

    if (isRestrictedUrl(tab.url)) {
        throw { code: 'RESTRICTED_PAGE', message: 'Cannot extract content from ' + tab.url };
    }

    await ensureExtractorInjected(tabId, chromeApi);

    try {
        var result = await chromeApi.tabs.sendMessage(tabId, { type: 'EXTRACT_PAGE' });
        var content = result.content || '';
        var words = countWords(content);
        console.log(P, 'extractTab:', tab.title, '|', content.length, 'chars |', words, 'words');
        return {
            tabId: tabId,
            title: tab.title || '',
            url: tab.url || '',
            content: content,
            wordCount: words,
            charCount: content.length,
            contentType: result.contentType || 'text',
            extractionMethod: (result.meta && result.meta.extractionMethod) || result.extractionMethod || 'generic'
        };
    } catch (e) {
        throw { code: 'EXTRACTION_FAILED', message: 'Extraction failed on tab ' + tabId + ': ' + e.message };
    }
}

// ==================== Screenshot / Capture Handlers ====================

/**
 * Handle CAPTURE_SCREENSHOT — single viewport screenshot of a specific tab.
 * Activates the tab, waits 300ms, then captures the visible area.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {object} payload - Must contain { tabId: number }
 * @param {object} captureState - Shared mutex: { inProgress: boolean }
 * @returns {Promise<{ tabId: number, dataUrl: string, width: null, height: null }>}
 * @throws {{ code: string, message: string }} On capture in progress, tab not found, or failure
 */
export async function handleCaptureScreenshot(chromeApi, payload, captureState) {
    var tabId = payload && payload.tabId;
    if (!tabId) {
        throw { code: 'TAB_NOT_FOUND', message: 'No tabId provided' };
    }

    if (captureState.inProgress) {
        throw { code: 'CAPTURE_IN_PROGRESS', message: 'Another capture is already running' };
    }

    var tab;
    try {
        tab = await chromeApi.tabs.get(tabId);
    } catch (e) {
        throw { code: 'TAB_NOT_FOUND', message: 'Tab ' + tabId + ' not found' };
    }

    if (isRestrictedUrl(tab.url)) {
        throw { code: 'RESTRICTED_PAGE', message: 'Cannot capture ' + tab.url };
    }

    captureState.inProgress = true;
    try {
        await chromeApi.tabs.update(tabId, { active: true });
        await new Promise(function(r) { setTimeout(r, 300); });

        var dataUrl = await chromeApi.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
        return {
            tabId: tabId,
            dataUrl: dataUrl,
            width: null,
            height: null
        };
    } catch (e) {
        throw { code: 'CAPTURE_FAILED', message: 'Screenshot failed: ' + e.message };
    } finally {
        captureState.inProgress = false;
    }
}

/**
 * Handle CAPTURE_FULL_PAGE — scrolling full-page screenshot capture.
 * Delegates to the shared captureFullPage() from full-page-capture.js.
 * Returns all screenshots at once (not streaming).
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {object} payload - { tabId, options?: { overlapRatio, scrollDelayMs } }
 * @param {object} captureState - Shared mutex: { inProgress: boolean }
 * @param {function} [onProgress] - Callback (progressPayload) for capture progress
 * @returns {Promise<object>} { tabId, screenshots[], pageTitle, pageUrl, scrollType, totalHeight, viewportHeight }
 * @throws {{ code: string, message: string }} On capture in progress, tab not found, or failure
 */
export async function handleCaptureFullPage(chromeApi, payload, captureState, onProgress) {
    var tabId = payload && payload.tabId;
    if (!tabId) {
        throw { code: 'TAB_NOT_FOUND', message: 'No tabId provided' };
    }

    if (captureState.inProgress) {
        throw { code: 'CAPTURE_IN_PROGRESS', message: 'Another capture is already running' };
    }

    var tab;
    try {
        tab = await chromeApi.tabs.get(tabId);
    } catch (e) {
        throw { code: 'TAB_NOT_FOUND', message: 'Tab ' + tabId + ' not found' };
    }

    if (isRestrictedUrl(tab.url)) {
        throw { code: 'RESTRICTED_PAGE', message: 'Cannot capture ' + tab.url };
    }

    captureState.inProgress = true;
    try {
        await chromeApi.tabs.update(tabId, { active: true });
        await new Promise(function(r) { setTimeout(r, 300); });

        await ensureExtractorInjected(tabId, chromeApi);

        var captureApi = {
            captureVisibleTab: function(windowId) {
                return chromeApi.tabs.captureVisibleTab(windowId, { format: 'png' });
            },
            sendMessage: function(tid, message) {
                return chromeApi.tabs.sendMessage(tid, message);
            },
            getTab: function(tid) {
                return chromeApi.tabs.get(tid);
            }
        };

        var options = {
            overlapRatio: (payload.options && payload.options.overlapRatio) || 0.1,
            delayMs: (payload.options && payload.options.scrollDelayMs) || 200
        };

        var progressCb = onProgress ? function(step, total, msg) {
            onProgress({
                step: step,
                total: total,
                tabId: tabId,
                message: msg || ('Capturing screenshot ' + step + ' of ' + total)
            });
        } : null;

        var result = await captureFullPage(tabId, captureApi, options, progressCb);

        return {
            tabId: tabId,
            screenshots: result.screenshots || [],
            pageTitle: tab.title || '',
            pageUrl: tab.url || '',
            scrollType: (result.meta && result.meta.scrollType) || (result.meta && result.meta.targetKind) || 'window',
            totalHeight: (result.meta && result.meta.scrollHeight) || 0,
            viewportHeight: (result.meta && result.meta.viewportHeight) || 0
        };
    } catch (e) {
        throw { code: e.code || 'CAPTURE_FAILED', message: e.message || String(e) };
    } finally {
        captureState.inProgress = false;
    }
}

/**
 * Handle CAPTURE_FULL_PAGE_WITH_OCR — scrolling capture that streams each screenshot
 * individually via onProgress for client-side OCR pipelining.
 *
 * Unlike handleCaptureFullPage which returns all screenshots at once, this sends
 * each screenshot as a progress event so the client can fire OCR immediately.
 * The final return value contains only metadata (no screenshots).
 *
 * Progress payload: { step, total, tabId, pageIndex, screenshot, pageUrl, pageTitle, message }
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {object} payload - { tabId, options?: { overlapRatio, scrollDelayMs } }
 * @param {object} captureState - Shared mutex: { inProgress: boolean }
 * @param {function} onProgress - Callback (progressPayload) — required for streaming screenshots
 * @returns {Promise<object>} { tabId, capturedCount, total, pageTitle, pageUrl, meta }
 */
export async function handleCaptureFullPageWithOcr(chromeApi, payload, captureState, onProgress) {
    var tabId = payload && payload.tabId;
    if (!tabId) {
        throw { code: 'TAB_NOT_FOUND', message: 'No tabId provided' };
    }

    if (captureState.inProgress) {
        throw { code: 'CAPTURE_IN_PROGRESS', message: 'Another capture is already running' };
    }

    var tab;
    try {
        tab = await chromeApi.tabs.get(tabId);
    } catch (e) {
        throw { code: 'TAB_NOT_FOUND', message: 'Tab ' + tabId + ' not found' };
    }

    if (isRestrictedUrl(tab.url)) {
        throw { code: 'RESTRICTED_PAGE', message: 'Cannot capture ' + tab.url };
    }

    captureState.inProgress = true;
    try {
        await chromeApi.tabs.update(tabId, { active: true });
        await new Promise(function(r) { setTimeout(r, 300); });
        await ensureExtractorInjected(tabId, chromeApi);

        var overlapRatio = (payload.options && payload.options.overlapRatio) || 0.1;
        var delayMs = (payload.options && payload.options.scrollDelayMs) || 1000;

        // Try modern capture context protocol (supports inner scroll containers)
        var contextId = null;
        var scrollHeight, clientHeight, maxScrollTop, originalScrollTop;
        var targetKind = 'window';

        try {
            var ctxResult = await chromeApi.tabs.sendMessage(tabId, {
                type: 'INIT_CAPTURE_CONTEXT',
                options: {}
            });
            if (ctxResult && ctxResult.ok) {
                contextId = ctxResult.contextId;
                scrollHeight = ctxResult.metrics.scrollHeight;
                clientHeight = ctxResult.metrics.clientHeight;
                maxScrollTop = ctxResult.metrics.maxScrollTop;
                originalScrollTop = ctxResult.metrics.scrollTop;
                targetKind = ctxResult.target.kind;
                console.log(P, 'OCR capture context:', targetKind, 'scrollH:', scrollHeight, 'clientH:', clientHeight);
            }
        } catch (_) {}

        // Fallback to legacy scroll metrics
        if (!contextId) {
            var metrics = await chromeApi.tabs.sendMessage(tabId, { type: 'GET_PAGE_METRICS' });
            clientHeight = Math.max(1, metrics.viewportHeight || 1);
            scrollHeight = Math.max(clientHeight, metrics.scrollHeight || clientHeight);
            maxScrollTop = Math.max(0, scrollHeight - clientHeight);
            originalScrollTop = metrics.scrollY || 0;
        }

        var overlapPx = Math.max(0, Math.round(clientHeight * overlapRatio));
        var step = Math.max(100, clientHeight - overlapPx);

        var positions = [];
        for (var y = 0; y <= maxScrollTop; y += step) {
            positions.push(y);
        }
        if (positions.length === 0 || positions[positions.length - 1] !== maxScrollTop) {
            positions.push(maxScrollTop);
        }

        if (originalScrollTop > 0) {
            var scrollTopMsg = contextId
                ? { type: 'SCROLL_CONTEXT_TO', contextId: contextId, top: 0 }
                : { type: 'SCROLL_TO', y: 0 };
            await chromeApi.tabs.sendMessage(tabId, scrollTopMsg);
            await new Promise(function(r) { setTimeout(r, delayMs); });
        }

        var capturedCount = 0;
        for (var i = 0; i < positions.length; i++) {
            var scrollY = positions[i];

            var scrollMsg = contextId
                ? { type: 'SCROLL_CONTEXT_TO', contextId: contextId, top: scrollY }
                : { type: 'SCROLL_TO', y: scrollY };
            await chromeApi.tabs.sendMessage(tabId, scrollMsg);
            await new Promise(function(r) { setTimeout(r, delayMs); });

            var dataUrl;
            try {
                dataUrl = await chromeApi.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
            } catch (captureErr) {
                if ((captureErr && captureErr.message || '').includes('MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND')) {
                    await new Promise(function(r) { setTimeout(r, 1200); });
                    try {
                        dataUrl = await chromeApi.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
                    } catch (_) { continue; }
                } else {
                    console.warn(P, 'OCR capture screenshot failed at', scrollY, captureErr.message);
                    continue;
                }
            }

            capturedCount++;
            if (onProgress) {
                try {
                    onProgress({
                        step: capturedCount,
                        total: positions.length,
                        tabId: tabId,
                        pageIndex: i,
                        screenshot: dataUrl,
                        pageUrl: tab.url || '',
                        pageTitle: tab.title || '',
                        message: 'Screenshot ' + capturedCount + ' of ' + positions.length
                    });
                } catch (_) {}
            }
        }

        // Restore scroll and release capture context
        try {
            var restoreMsg = contextId
                ? { type: 'SCROLL_CONTEXT_TO', contextId: contextId, top: originalScrollTop }
                : { type: 'SCROLL_TO', y: originalScrollTop };
            await chromeApi.tabs.sendMessage(tabId, restoreMsg);
            if (contextId) {
                await chromeApi.tabs.sendMessage(tabId, { type: 'RELEASE_CAPTURE_CONTEXT', contextId: contextId });
            }
        } catch (_) {}

        return {
            tabId: tabId,
            capturedCount: capturedCount,
            total: positions.length,
            pageTitle: tab.title || '',
            pageUrl: tab.url || '',
            meta: { scrollHeight: scrollHeight, clientHeight: clientHeight, step: step, overlapPx: overlapPx, targetKind: targetKind }
        };
    } catch (e) {
        throw { code: e.code || 'CAPTURE_FAILED', message: e.message || String(e) };
    } finally {
        captureState.inProgress = false;
    }
}

// ==================== Multi-Tab Capture ====================

/**
 * Handle CAPTURE_MULTI_TAB — capture/extract content from multiple tabs sequentially.
 * Supports modes: dom, ocr, full-ocr, auto. Reports per-tab progress via onProgress.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {object} payload - { tabs: [{ tabId, mode }] }
 * @param {object} captureState - Shared mutex: { inProgress: boolean }
 * @param {function} [onProgress] - Callback (progressPayload) for per-tab progress
 * @returns {Promise<{ results: object[], completedCount: number, totalCount: number }>}
 */
export async function handleCaptureMultiTab(chromeApi, payload, captureState, onProgress) {
    if (!payload || !Array.isArray(payload.tabs) || payload.tabs.length === 0) {
        throw { code: 'UNKNOWN', message: 'No tabs provided for multi-tab capture' };
    }

    if (captureState.inProgress) {
        throw { code: 'CAPTURE_IN_PROGRESS', message: 'Another capture is already running' };
    }

    captureState.inProgress = true;
    var results = [];
    var totalTabs = payload.tabs.length;
    var originalTabId = null;

    try {
        // Save the currently active tab so we can restore it after all captures
        try {
            var activeTabs = await chromeApi.tabs.query({ active: true, currentWindow: true });
            if (activeTabs && activeTabs.length > 0) {
                originalTabId = activeTabs[0].id;
            }
        } catch (_) {}

        for (var i = 0; i < totalTabs; i++) {
            var tabSpec = payload.tabs[i];
            var tabId = tabSpec.tabId;
            var mode = tabSpec.mode || 'auto';

            if (onProgress) {
                try {
                    onProgress({
                        type: 'tab-progress',
                        step: i + 1,
                        total: totalTabs,
                        tabId: tabId,
                        mode: mode,
                        message: 'Processing tab ' + (i + 1) + ' of ' + totalTabs + ' (mode: ' + mode + ')'
                    });
                } catch (_) {}
            }

            var tabResult = await captureOneTab(chromeApi, tabId, mode, onProgress);
            results.push(tabResult);
        }

        return {
            results: results,
            completedCount: results.filter(function(r) { return !r.error; }).length,
            totalCount: totalTabs
        };
    } catch (e) {
        throw { code: e.code || 'CAPTURE_FAILED', message: e.message || String(e) };
    } finally {
        // Restore the original active tab
        if (originalTabId) {
            try {
                await chromeApi.tabs.update(originalTabId, { active: true });
                console.log(P, 'Restored original tab:', originalTabId);
            } catch (_) {}
        }
        captureState.inProgress = false;
    }
}

// ==================== Multi-Tab Helpers (internal) ====================

async function captureOneTab(chromeApi, tabId, mode, onProgress) {
    var tab;
    try {
        tab = await chromeApi.tabs.get(tabId);
    } catch (e) {
        return { tabId: tabId, title: '', url: '', mode: mode, content: null, screenshots: null, error: 'Tab not found' };
    }

    if (isRestrictedUrl(tab.url)) {
        return { tabId: tabId, title: tab.title || '', url: tab.url || '', mode: mode, content: null, screenshots: null, error: 'Restricted page' };
    }

    try {
        if (mode === 'dom') {
            return await captureTabDom(chromeApi, tab);
        } else if (mode === 'ocr') {
            return await captureTabOcr(chromeApi, tab, onProgress);
        } else if (mode === 'full-ocr') {
            return await captureTabFullOcr(chromeApi, tab, onProgress);
        } else {
            // auto: try DOM first, fall back to OCR if content too short
            var domResult = await captureTabDom(chromeApi, tab);
            if (domResult.content && domResult.content.length >= 100) {
                return domResult;
            }
            var ocrResult = await captureTabOcr(chromeApi, tab, onProgress);
            ocrResult.mode = 'ocr';
            return ocrResult;
        }
    } catch (e) {
        return { tabId: tabId, title: tab.title || '', url: tab.url || '', mode: mode, content: null, screenshots: null, error: e.message };
    }
}

async function captureTabDom(chromeApi, tab) {
    await ensureExtractorInjected(tab.id, chromeApi);
    var result = await chromeApi.tabs.sendMessage(tab.id, { type: 'EXTRACT_PAGE' });
    var content = result.content || '';
    var words = countWords(content);
    console.log(P, 'captureTabDom:', tab.title, '|', content.length, 'chars |', words, 'words');
    return {
        tabId: tab.id,
        title: tab.title || '',
        url: tab.url || '',
        mode: 'dom',
        content: content,
        wordCount: words,
        charCount: content.length,
        screenshots: null,
        error: null
    };
}

// ==================== Capture Toast Overlay Helpers ====================

function injectCaptureToast(chromeApi, tabId, title, mode) {
    try {
        return chromeApi.scripting.executeScript({
            target: { tabId: tabId },
            func: function(title, mode) {
                var existing = document.getElementById('__ai_capture_toast');
                if (existing) existing.remove();
                var el = document.createElement('div');
                el.id = '__ai_capture_toast';
                el.textContent = '\uD83D\uDCF7 AI Assistant ' + (mode === 'scroll' ? 'scroll-capturing' : 'capturing') + ': ' + title;
                el.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483647;background:rgba(30,30,30,0.95);color:#fff;padding:10px 20px;border-radius:10px;font-size:13px;font-family:system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,0.4);pointer-events:none;transition:opacity 0.3s;';
                document.body.appendChild(el);
            },
            args: [title, mode]
        }).catch(function() {});
    } catch (_) { return Promise.resolve(); }
}

function updateCaptureToast(chromeApi, tabId, message) {
    try {
        chromeApi.scripting.executeScript({
            target: { tabId: tabId },
            func: function(msg) {
                var el = document.getElementById('__ai_capture_toast');
                if (el) el.textContent = '\uD83D\uDCF7 ' + msg;
            },
            args: [message]
        });
    } catch (_) {}
}

function removeCaptureToast(chromeApi, tabId) {
    try {
        return chromeApi.scripting.executeScript({
            target: { tabId: tabId },
            func: function() {
                var el = document.getElementById('__ai_capture_toast');
                if (el) el.remove();
            }
        }).catch(function() {});
    } catch (_) { return Promise.resolve(); }
}

async function captureTabOcr(chromeApi, tab, onProgress) {
    await chromeApi.tabs.update(tab.id, { active: true });
    await new Promise(function(r) { setTimeout(r, 300); });

    await injectCaptureToast(chromeApi, tab.id, tab.title || '', 'ocr');

    var dataUrl = await chromeApi.tabs.captureVisibleTab(tab.windowId, { format: 'png' });

    await removeCaptureToast(chromeApi, tab.id);

    if (onProgress) {
        try {
            onProgress({
                type: 'screenshot',
                tabId: tab.id,
                pageIndex: 0,
                screenshot: dataUrl,
                pageUrl: tab.url || '',
                pageTitle: tab.title || '',
                step: 1,
                total: 1,
                message: 'Screenshot 1 of 1'
            });
        } catch (_) {}
    }

    return {
        tabId: tab.id,
        title: tab.title || '',
        url: tab.url || '',
        mode: 'ocr',
        content: null,
        screenshots: onProgress ? [] : [dataUrl],
        screenshotCount: 1,
        error: null
    };
}

async function captureTabFullOcr(chromeApi, tab, onProgress) {
    await chromeApi.tabs.update(tab.id, { active: true });
    await new Promise(function(r) { setTimeout(r, 300); });

    await ensureExtractorInjected(tab.id, chromeApi);
    await injectCaptureToast(chromeApi, tab.id, tab.title || '', 'scroll');

    var screenshotIndex = 0;
    var captureApi = {
        captureVisibleTab: function(windowId) {
            return chromeApi.tabs.captureVisibleTab(windowId, { format: 'png' }).then(function(dataUrl) {
                if (onProgress) {
                    try {
                        onProgress({
                            type: 'screenshot',
                            tabId: tab.id,
                            pageIndex: screenshotIndex,
                            screenshot: dataUrl,
                            pageUrl: tab.url || '',
                            pageTitle: tab.title || ''
                        });
                    } catch (_) {}
                }
                screenshotIndex++;
                return dataUrl;
            });
        },
        sendMessage: function(tid, message) {
            return chromeApi.tabs.sendMessage(tid, message);
        },
        getTab: function(tid) {
            return chromeApi.tabs.get(tid);
        }
    };

    var result = await captureFullPage(tab.id, captureApi, { overlapRatio: 0.1, delayMs: 200 }, function(step, total, msg) {
        if (onProgress) {
            try {
                onProgress({
                    type: 'capture-progress',
                    tabId: tab.id,
                    step: step,
                    total: total,
                    message: msg
                });
            } catch (_) {}
        }
        updateCaptureToast(chromeApi, tab.id, msg);
    });

    await removeCaptureToast(chromeApi, tab.id);

    return {
        tabId: tab.id,
        title: tab.title || '',
        url: tab.url || '',
        mode: 'full-ocr',
        content: null,
        screenshots: onProgress ? [] : (result.screenshots || []),
        screenshotCount: result.screenshots ? result.screenshots.length : 0,
        error: null
    };
}

// ==================== Script Execution Handler ====================

/**
 * Handle EXECUTE_SCRIPT — inject and run user-provided JavaScript on a target tab.
 * Optionally invokes a named action handler registered by the script.
 *
 * @param {object} chromeApi - Chrome API adapter
 * @param {object} payload - { tabId, code, action? }
 * @returns {Promise<{ tabId: number, result: any, success: boolean }>}
 */
export async function handleExecuteScript(chromeApi, payload) {
    if (!payload) {
        throw { code: 'UNKNOWN', message: 'No payload provided for EXECUTE_SCRIPT' };
    }

    var tabId = payload.tabId;
    var code = payload.code;
    var action = payload.action;

    if (!tabId) {
        throw { code: 'TAB_NOT_FOUND', message: 'No tabId provided' };
    }
    if (!code || typeof code !== 'string') {
        throw { code: 'SCRIPT_ERROR', message: 'No script code provided' };
    }

    var tab;
    try {
        tab = await chromeApi.tabs.get(tabId);
    } catch (e) {
        throw { code: 'TAB_NOT_FOUND', message: 'Tab ' + tabId + ' not found' };
    }

    if (isRestrictedUrl(tab.url)) {
        throw { code: 'RESTRICTED_PAGE', message: 'Cannot execute script on ' + tab.url };
    }

    try {
        await chromeApi.scripting.executeScript({
            target: { tabId: tabId },
            func: function() { window.__scriptRunnerMode = 'ondemand'; }
        });

        await chromeApi.scripting.executeScript({
            target: { tabId: tabId },
            files: ['content_scripts/script-runner-core.js']
        });
        await new Promise(function(r) { setTimeout(r, 100); });

        await chromeApi.scripting.executeScript({
            target: { tabId: tabId },
            func: function(userCode) {
                try {
                    var fn = new Function(userCode);
                    fn();
                } catch (e) {
                    console.error('[OpsHandler] User script error:', e);
                    throw e;
                }
            },
            args: [code]
        });
        await new Promise(function(r) { setTimeout(r, 100); });

        if (action) {
            try {
                var actionResult = await chromeApi.tabs.sendMessage(tabId, {
                    type: 'EXECUTE_SCRIPT_ACTION',
                    handlerName: action
                });
                return {
                    tabId: tabId,
                    result: actionResult,
                    success: true
                };
            } catch (e) {
                throw { code: 'ACTION_NOT_FOUND', message: 'Action "' + action + '" failed: ' + e.message };
            }
        }

        return {
            tabId: tabId,
            result: null,
            success: true
        };
    } catch (e) {
        if (e.code) throw e;
        throw { code: 'SCRIPT_ERROR', message: 'Script execution failed: ' + e.message };
    }
}
