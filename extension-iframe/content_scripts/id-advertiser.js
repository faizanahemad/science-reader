/**
 * ID Advertiser Content Script for AI Assistant Extension
 *
 * Injected into main UI pages (localhost:5000, 127.0.0.1:5000, assist-chat.site)
 * to advertise the extension ID so ExtensionBridge can call
 * chrome.runtime.sendMessage(extId) / chrome.runtime.connect(extId).
 *
 * Uses a DOM attribute on <html> to pass the ID to page JavaScript.
 * DOM attributes are shared between the content script's isolated world
 * and the page's main world, unlike window properties. This avoids
 * inline <script> injection which is blocked by CSP in sandboxed iframes.
 *
 * Runs at document_start on matching pages so the attribute is set before
 * ExtensionBridge.init() runs at DOMContentLoaded.
 */
(function() {
    'use strict';
    var extId = chrome.runtime.id;
    console.log('[IdAdv] running, extId:', extId, 'url:', location.href,
        'isTopFrame:', (window === window.top));

    // DOM attribute — readable by page JS, no CSP issues, no world isolation issues
    document.documentElement.setAttribute('data-ai-ext-id', extId);
    console.log('[IdAdv] attribute set, readback:',
        document.documentElement.getAttribute('data-ai-ext-id'));

    // Notify any listeners that the extension ID is available
    document.dispatchEvent(new CustomEvent('ai-extension-ready'));
    console.log('[IdAdv] event dispatched');
})();
