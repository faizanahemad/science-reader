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
            return handleExtractCurrentPage(chromeApi, MAIN_UI_PATTERNS);
        case 'EXTRACT_TAB':
            return handleExtractTab(chromeApi, payload);
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
        default:
            throw { code: 'UNKNOWN', message: 'Unknown operation: ' + type };
    }
}

console.log(P, '=== SERVICE WORKER INITIALIZED ===');
