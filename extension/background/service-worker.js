/**
 * Service Worker for AI Assistant Chrome Extension
 * 
 * Responsibilities:
 * 1. Create context menu items on install
 * 2. Handle context menu clicks (quick actions)
 * 3. Coordinate messages between popup, sidepanel, content scripts
 * 4. Manage sidepanel state
 */

import { QUICK_ACTIONS, MESSAGE_TYPES, API_BASE } from '../shared/constants.js';

// ==================== Installation & Context Menu ====================

/**
 * Set up extension on install
 */
chrome.runtime.onInstalled.addListener(() => {
    console.log('[AI Assistant] Extension installed, creating context menus');
    
    // Create parent menu item
    chrome.contextMenus.create({
        id: 'ai-assistant-menu',
        title: 'AI Assistant',
        contexts: ['selection']
    });

    // Create quick action items
    QUICK_ACTIONS.forEach(action => {
        chrome.contextMenus.create({
            id: `ai-${action.id}`,
            parentId: 'ai-assistant-menu',
            title: `${action.icon} ${action.name}`,
            contexts: ['selection']
        });
    });

    // Separator
    chrome.contextMenus.create({
        id: 'ai-separator',
        parentId: 'ai-assistant-menu',
        type: 'separator',
        contexts: ['selection']
    });

    // Add to chat option
    chrome.contextMenus.create({
        id: 'ai-add-to-chat',
        parentId: 'ai-assistant-menu',
        title: '💬 Add to Chat',
        contexts: ['selection']
    });

    // Set sidepanel to open on action click
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(console.error);
});

// ==================== Context Menu Click Handler ====================

/**
 * Handle context menu item clicks
 */
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
    const actionId = info.menuItemId.toString().replace('ai-', '');
    const selectedText = info.selectionText || '';

    console.log(`[AI Assistant] Context menu clicked: ${actionId}`, { selectedText: selectedText.substring(0, 50) });

    if (actionId === 'add-to-chat') {
        // Open sidepanel and add text to chat
        try {
            await chrome.sidePanel.open({ tabId: tab.id });
            // Wait a bit for sidepanel to initialize
            setTimeout(() => {
                chrome.runtime.sendMessage({
                    type: MESSAGE_TYPES.ADD_TO_CHAT,
                    text: selectedText,
                    pageUrl: tab.url,
                    pageTitle: tab.title
                }).catch(console.error);
            }, 500);
        } catch (e) {
            console.error('[AI Assistant] Failed to open sidepanel:', e);
        }
    } else if (QUICK_ACTIONS.find(a => a.id === actionId)) {
        // Quick action - send to content script to show modal
        try {
            await chrome.tabs.sendMessage(tab.id, {
                type: MESSAGE_TYPES.QUICK_ACTION,
                action: actionId,
                text: selectedText,
                pageUrl: tab.url,
                pageTitle: tab.title
            });
        } catch (e) {
            console.error('[AI Assistant] Failed to send to content script:', e);
            // Content script might not be loaded, try injecting it
            try {
                await chrome.scripting.executeScript({
                    target: { tabId: tab.id },
                    files: ['content_scripts/extractor.js']
                });
                // Retry the message
                await chrome.tabs.sendMessage(tab.id, {
                    type: MESSAGE_TYPES.QUICK_ACTION,
                    action: actionId,
                    text: selectedText,
                    pageUrl: tab.url,
                    pageTitle: tab.title
                });
            } catch (e2) {
                console.error('[AI Assistant] Failed to inject content script:', e2);
            }
        }
    }
});

// ==================== Message Handler ====================

/**
 * Handle messages from popup, sidepanel, and content scripts
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    console.log('[AI Assistant] Service worker received:', message.type);

    switch (message.type) {
        case MESSAGE_TYPES.OPEN_SIDEPANEL:
            handleOpenSidepanel(sender, sendResponse);
            return true; // Keep channel open for async response

        case MESSAGE_TYPES.EXTRACT_PAGE:
            handleExtractPage(message, sender, sendResponse);
            return true;

        case MESSAGE_TYPES.GET_TAB_INFO:
            handleGetTabInfo(sendResponse);
            return true;

        case MESSAGE_TYPES.GET_ALL_TABS:
            handleGetAllTabs(sendResponse);
            return true;

        case MESSAGE_TYPES.EXTRACT_FROM_TAB:
            handleExtractFromTab(message, sendResponse);
            return true;

        case MESSAGE_TYPES.CAPTURE_SCREENSHOT:
            handleCaptureScreenshot(sender, sendResponse);
            return true;

        case MESSAGE_TYPES.AUTH_STATE_CHANGED:
            // Broadcast to all extension pages
            broadcastAuthState(message.isAuthenticated);
            sendResponse({ success: true });
            break;

        default:
            console.log('[AI Assistant] Unknown message type:', message.type);
            sendResponse({ error: 'Unknown message type' });
    }
});

// ==================== Message Handlers ====================

/**
 * Open the sidepanel
 */
async function handleOpenSidepanel(sender, sendResponse) {
    try {
        const tabId = sender.tab?.id;
        if (tabId) {
            await chrome.sidePanel.open({ tabId });
            sendResponse({ success: true });
        } else {
            // Get active tab
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (tab) {
                await chrome.sidePanel.open({ tabId: tab.id });
                sendResponse({ success: true });
            } else {
                sendResponse({ error: 'No active tab' });
            }
        }
    } catch (e) {
        console.error('[AI Assistant] Failed to open sidepanel:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Extract page content via content script
 */
async function handleExtractPage(message, sender, sendResponse) {
    try {
        const tabId = message.tabId || sender.tab?.id;
        if (!tabId) {
            // Get active tab
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (!tab) {
                sendResponse({ error: 'No active tab' });
                return;
            }
            const result = await chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.EXTRACT_PAGE });
            sendResponse(result);
        } else {
            const result = await chrome.tabs.sendMessage(tabId, { type: MESSAGE_TYPES.EXTRACT_PAGE });
            sendResponse(result);
        }
    } catch (e) {
        console.error('[AI Assistant] Failed to extract page:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Get info about the active tab
 */
async function handleGetTabInfo(sendResponse) {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tab) {
            sendResponse({
                tabId: tab.id,
                url: tab.url,
                title: tab.title,
                favIconUrl: tab.favIconUrl
            });
        } else {
            sendResponse({ error: 'No active tab' });
        }
    } catch (e) {
        console.error('[AI Assistant] Failed to get tab info:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Get info about all open tabs
 */
async function handleGetAllTabs(sendResponse) {
    console.log('[AI Assistant] handleGetAllTabs called');
    try {
        const tabs = await chrome.tabs.query({ currentWindow: true });
        console.log('[AI Assistant] Found tabs:', tabs.length);
        const result = {
            tabs: tabs.map(t => ({
                tabId: t.id,
                url: t.url,
                title: t.title,
                favIconUrl: t.favIconUrl,
                active: t.active
            }))
        };
        console.log('[AI Assistant] Sending response:', result);
        sendResponse(result);
    } catch (e) {
        console.error('[AI Assistant] Failed to get all tabs:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Extract content from a specific tab by ID
 */
async function handleExtractFromTab(message, sendResponse) {
    try {
        const tabId = message.tabId;
        if (!tabId) {
            sendResponse({ error: 'No tabId provided' });
            return;
        }
        
        // Get tab info
        const tab = await chrome.tabs.get(tabId);
        if (!tab) {
            sendResponse({ error: 'Tab not found' });
            return;
        }
        
        // Skip chrome:// and other restricted URLs
        if (tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://') || 
            tab.url.startsWith('about:') || tab.url.startsWith('edge://')) {
            sendResponse({ 
                tabId: tabId,
                url: tab.url,
                title: tab.title,
                content: '[Cannot extract content from browser internal pages]',
                error: 'restricted_url'
            });
            return;
        }
        
        try {
            // Try to send message to content script
            const result = await chrome.tabs.sendMessage(tabId, { type: MESSAGE_TYPES.EXTRACT_PAGE });
            sendResponse({
                tabId: tabId,
                url: tab.url,
                title: tab.title,
                content: result.content || '',
                meta: result.meta,
                length: result.length,
                needsScreenshot: result.needsScreenshot
            });
        } catch (contentScriptError) {
            // Content script not injected, try to inject it
            console.log('[AI Assistant] Injecting content script into tab:', tabId);
            try {
                await chrome.scripting.executeScript({
                    target: { tabId: tabId },
                    files: ['content_scripts/extractor.js']
                });
                
                // Wait a bit for script to initialize
                await new Promise(resolve => setTimeout(resolve, 100));
                
                // Try again
                const result = await chrome.tabs.sendMessage(tabId, { type: MESSAGE_TYPES.EXTRACT_PAGE });
                sendResponse({
                    tabId: tabId,
                    url: tab.url,
                    title: tab.title,
                    content: result.content || '',
                    meta: result.meta,
                    length: result.length
                });
            } catch (injectError) {
                console.error('[AI Assistant] Failed to inject/extract:', injectError);
                sendResponse({
                    tabId: tabId,
                    url: tab.url,
                    title: tab.title,
                    content: '[Failed to extract content from this page]',
                    error: 'extraction_failed'
                });
            }
        }
    } catch (e) {
        console.error('[AI Assistant] Failed to extract from tab:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Capture screenshot of visible area
 */
async function handleCaptureScreenshot(sender, sendResponse) {
    try {
        const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: 'png' });
        sendResponse({ screenshot: dataUrl });
    } catch (e) {
        console.error('[AI Assistant] Failed to capture screenshot:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Broadcast auth state change to all extension pages
 */
function broadcastAuthState(isAuthenticated) {
    chrome.runtime.sendMessage({
        type: MESSAGE_TYPES.AUTH_STATE_CHANGED,
        isAuthenticated
    }).catch(() => {
        // Ignore errors if no listeners
    });
}

// ==================== Tab Change Listeners ====================

/**
 * Update sidepanel when active tab changes
 */
chrome.tabs.onActivated.addListener(async (activeInfo) => {
    try {
        const tab = await chrome.tabs.get(activeInfo.tabId);
        // Notify sidepanel about tab change
        chrome.runtime.sendMessage({
            type: 'TAB_CHANGED',
            tabId: activeInfo.tabId,
            url: tab.url,
            title: tab.title
        }).catch(() => {
            // Sidepanel might not be open
        });
    } catch (e) {
        console.error('[AI Assistant] Tab activated handler error:', e);
    }
});

/**
 * Update when tab URL changes
 */
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === 'complete' && tab.active) {
        chrome.runtime.sendMessage({
            type: 'TAB_UPDATED',
            tabId,
            url: tab.url,
            title: tab.title
        }).catch(() => {
            // Ignore if no listeners
        });
    }
});

console.log('[AI Assistant] Service worker initialized');

