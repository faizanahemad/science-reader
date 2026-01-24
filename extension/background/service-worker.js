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
import { Storage } from '../shared/storage.js';

// Ensure the toolbar icon opens the sidepanel (best-effort; may fail on older Chrome)
chrome.sidePanel?.setPanelBehavior?.({ openPanelOnActionClick: true }).catch(() => {});

/**
 * Resolve API base URL from storage, with safe fallback.
 * @returns {Promise<string>}
 */
async function getApiBaseUrl() {
    const base = await Storage.getApiBaseUrl();
    const normalized = (base || API_BASE).trim().replace(/\/+$/, '');
    return normalized || API_BASE;
}

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

        case MESSAGE_TYPES.CAPTURE_FULLPAGE_SCREENSHOTS:
            handleCaptureFullPageScreenshots(message, sender, sendResponse);
            return true;

        case MESSAGE_TYPES.AUTH_STATE_CHANGED:
            // Broadcast to all extension pages
            broadcastAuthState(message.isAuthenticated);
            sendResponse({ success: true });
            break;

        // ==================== Custom Scripts Handlers ====================
        
        case 'GET_SCRIPTS_FOR_URL':
            handleGetScriptsForUrl(message, sendResponse);
            return true;

        case 'SCRIPT_LLM_REQUEST':
            handleScriptLlmRequest(message, sendResponse);
            return true;

        case 'EXECUTE_SCRIPT_ACTION':
            handleExecuteScriptAction(message, sender, sendResponse);
            return true;

        case 'GET_PAGE_CONTEXT':
            handleGetPageContext(sendResponse);
            return true;

        case 'SCRIPTS_UPDATED':
            handleScriptsUpdated(sendResponse);
            return true;

        case 'OPEN_SCRIPT_EDITOR':
            handleOpenScriptEditor(message, sendResponse);
            return true;

        default:
            console.log('[AI Assistant] Unknown message type:', message.type);
            sendResponse({ error: 'Unknown message type' });
    }
});

// ==================== Message Handlers ====================

/**
 * Open the sidepanel.
 *
 * CRITICAL: `chrome.sidePanel.open()` must be called without crossing an async boundary
 * (no `await` before calling it), otherwise Chrome may treat it as not being initiated
 * by a user gesture and reject it.
 *
 * For clicks originating in a content script (like the floating button), `sender.tab.id`
 * is available and we can open immediately.
 */
function handleOpenSidepanel(sender, sendResponse) {
    try {
        const tabId = sender?.tab?.id;

        // If we don't have a tabId, we intentionally do NOT call chrome.tabs.query()
        // because that introduces an async boundary and can break the user-gesture token.
        if (!tabId) {
            sendResponse({
                error: 'No sender tab. Please click the extension icon to open the sidepanel.',
                fallbackToIcon: true
            });
            return;
        }

        console.log('[AI Assistant] Opening sidepanel for tab:', tabId);

        // Best-effort: enable sidepanel for this tab without awaiting.
        chrome.sidePanel
            .setOptions({ tabId, path: 'sidepanel/sidepanel.html', enabled: true })
            .catch(() => {});

        // MUST be called immediately (no await before this line).
        chrome.sidePanel
            .open({ tabId })
            .then(() => {
                sendResponse({ success: true, opened: 'sidepanel' });
            })
            .catch((e) => {
                sendResponse({
                    error: `Sidepanel failed: ${e?.message || String(e)}`,
                    fallbackToIcon: true
                });
            });
    } catch (e) {
        console.error('[AI Assistant] Failed to open sidepanel:', e.message, e);
        sendResponse({
            error: `Sidepanel failed: ${e?.message || String(e)}`,
            fallbackToIcon: true
        });
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
 * Ensure extractor content script is present in the tab.
 * @param {number} tabId - Chrome tab ID.
 */
async function ensureExtractorInjected(tabId) {
    try {
        await chrome.tabs.sendMessage(tabId, { type: MESSAGE_TYPES.GET_PAGE_METRICS });
        return;
    } catch (_) {
        await chrome.scripting.executeScript({
            target: { tabId },
            files: ['content_scripts/extractor.js']
        });
        await new Promise(resolve => setTimeout(resolve, 150));
    }
}

/**
 * Capture full-page screenshots by scrolling the page and grabbing visible frames.
 * @param {Object} message - Capture options.
 * @param {Object} sender - Message sender.
 * @param {Function} sendResponse - Response callback.
 */
async function handleCaptureFullPageScreenshots(message, sender, sendResponse) {
    try {
        const tabId = message.tabId || sender.tab?.id;
        const overlapRatio = Number.isFinite(message?.overlapRatio) ? message.overlapRatio : 0.1;
        const delayMs = Number.isFinite(message?.delayMs) ? message.delayMs : 1000;

        let tab;
        if (tabId) {
            tab = await chrome.tabs.get(tabId);
        } else {
            const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
            tab = activeTab;
        }

        if (!tab?.id) {
            sendResponse({ error: 'No active tab available for capture' });
            return;
        }

        if (tab.url?.startsWith('chrome://') || tab.url?.startsWith('chrome-extension://') ||
            tab.url?.startsWith('about:') || tab.url?.startsWith('edge://')) {
            sendResponse({ error: 'Cannot capture screenshots on restricted URLs' });
            return;
        }

        await ensureExtractorInjected(tab.id);

        const metrics = await chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.GET_PAGE_METRICS });
        const viewportHeight = Math.max(1, metrics.viewportHeight || 1);
        const scrollHeight = Math.max(viewportHeight, metrics.scrollHeight || viewportHeight);
        const maxScrollTop = Math.max(0, scrollHeight - viewportHeight);
        const overlapPx = Math.max(0, Math.round(viewportHeight * overlapRatio));
        const step = Math.max(100, viewportHeight - overlapPx);

        const positions = [];
        for (let y = 0; y <= maxScrollTop; y += step) {
            positions.push(y);
        }
        if (positions.length === 0 || positions[positions.length - 1] !== maxScrollTop) {
            positions.push(maxScrollTop);
        }

        const originalScrollY = metrics.scrollY || 0;

        if (originalScrollY > 0) {
            await chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y: 0 });
            await new Promise(resolve => setTimeout(resolve, delayMs));
        }

        const screenshots = [];
        for (let i = 0; i < positions.length; i += 1) {
            const y = positions[i];
            await chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y });
            await new Promise(resolve => setTimeout(resolve, delayMs));
            try {
                const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
                screenshots.push(dataUrl);
            } catch (e) {
                const msg = e?.message || String(e);
                if (msg.includes('MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND')) {
                    // Backoff and retry once
                    await new Promise(resolve => setTimeout(resolve, 1200));
                    const retryUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
                    screenshots.push(retryUrl);
                } else {
                    throw e;
                }
            }
        }

        await chrome.tabs.sendMessage(tab.id, { type: MESSAGE_TYPES.SCROLL_TO, y: originalScrollY });

        sendResponse({
            screenshots,
            url: tab.url,
            title: tab.title,
            meta: {
                scrollHeight,
                viewportHeight,
                step,
                overlapPx,
                total: screenshots.length
            }
        });
    } catch (e) {
        console.error('[AI Assistant] Failed full-page capture:', e);
        sendResponse({ error: e.message || String(e) });
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

// ==================== Custom Scripts Handlers ====================

/**
 * Get scripts that match a given URL
 */
async function handleGetScriptsForUrl(message, sendResponse) {
    try {
        const token = await Storage.getToken();
        if (!token) {
            console.log('[AI Assistant] No auth token for scripts, returning empty');
            sendResponse({ scripts: [] });
            return;
        }

        const apiBase = await getApiBaseUrl();
        const url = encodeURIComponent(message.url);
        const response = await fetch(`${apiBase}/ext/scripts/for-url?url=${url}`, {
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            if (response.status === 401) {
                // Token expired
                sendResponse({ scripts: [], error: 'auth_expired' });
                return;
            }
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        console.log('[AI Assistant] Loaded scripts for URL:', data.scripts?.length || 0);
        sendResponse({ scripts: data.scripts || [] });

    } catch (e) {
        console.error('[AI Assistant] Failed to get scripts for URL:', e);
        sendResponse({ scripts: [], error: e.message });
    }
}

/**
 * Handle LLM request from a user script
 */
async function handleScriptLlmRequest(message, sendResponse) {
    try {
        const token = await Storage.getToken();
        if (!token) {
            sendResponse({ error: 'Not authenticated' });
            return;
        }

        const apiBase = await getApiBaseUrl();
        // Create a temporary conversation for the LLM request
        const createResponse = await fetch(`${apiBase}/ext/conversations`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                title: 'Script LLM Request',
                is_temporary: true,
                delete_temporary: false // Don't delete other temp convos
            })
        });

        if (!createResponse.ok) {
            throw new Error('Failed to create conversation');
        }

        const convData = await createResponse.json();
        const conversationId = convData.conversation.conversation_id;

        // Send the chat message
        const chatResponse = await fetch(`${apiBase}/ext/chat/${conversationId}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: message.prompt,
                stream: false
            })
        });

        if (!chatResponse.ok) {
            throw new Error('LLM request failed');
        }

        const chatData = await chatResponse.json();
        sendResponse({ response: chatData.response });

    } catch (e) {
        console.error('[AI Assistant] Script LLM request failed:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Execute a script action in the active tab
 */
async function handleExecuteScriptAction(message, sender, sendResponse) {
    try {
        // Get the tab to execute in
        const tabId = message.tabId || sender.tab?.id;
        
        if (!tabId) {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (!tab) {
                sendResponse({ error: 'No active tab' });
                return;
            }
            message.tabId = tab.id;
        }

        // Send to content script
        const result = await chrome.tabs.sendMessage(message.tabId || tabId, {
            type: 'EXECUTE_SCRIPT_ACTION',
            scriptId: message.scriptId,
            handlerName: message.handlerName
        });

        sendResponse(result);

    } catch (e) {
        console.error('[AI Assistant] Failed to execute script action:', e);
        sendResponse({ success: false, error: e.message });
    }
}

/**
 * Get page context from active tab for script generation
 */
async function handleGetPageContext(sendResponse) {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.id) {
            sendResponse({ error: 'No active tab' });
            return;
        }

        // Send to content script to get page context
        const result = await chrome.tabs.sendMessage(tab.id, {
            type: 'GET_PAGE_CONTEXT'
        });

        sendResponse(result);

    } catch (e) {
        console.error('[AI Assistant] Failed to get page context:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Notify all tabs that scripts have been updated
 */
async function handleScriptsUpdated(sendResponse) {
    try {
        const tabs = await chrome.tabs.query({});
        
        // Notify all tabs to reload scripts
        for (const tab of tabs) {
            if (tab.id && tab.url && !tab.url.startsWith('chrome://')) {
                chrome.tabs.sendMessage(tab.id, { type: 'RELOAD_SCRIPTS' }).catch(() => {
                    // Tab might not have content script
                });
            }
        }

        sendResponse({ success: true });

    } catch (e) {
        console.error('[AI Assistant] Failed to notify scripts updated:', e);
        sendResponse({ error: e.message });
    }
}

/**
 * Open the script editor popup with optional script data
 */
async function handleOpenScriptEditor(message, sendResponse) {
    try {
        // Create editor URL with optional scriptId
        let editorUrl = chrome.runtime.getURL('editor/editor.html');
        if (message.scriptId) {
            editorUrl = `${editorUrl}?scriptId=${encodeURIComponent(message.scriptId)}`;
        }
        
        if (message.script) {
            // Store script data in storage for the editor to pick up
            await chrome.storage.local.set({
                '_pending_script_edit': {
                    script: message.script,
                    timestamp: Date.now()
                }
            });
        }

        // Open editor in a new tab (avoids needing the "windows" permission)
        const tab = await chrome.tabs.create({
            url: editorUrl,
            active: true
        });

        sendResponse({ success: true, tabId: tab?.id });

    } catch (e) {
        console.error('[AI Assistant] Failed to open script editor:', e);
        sendResponse({ error: e.message });
    }
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

