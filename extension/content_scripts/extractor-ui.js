/**
 * Extractor UI — Modal, Toast, and Floating Button
 *
 * Purpose:
 *   UI layer for the page extractor. Provides the quick-action modal,
 *   toast notifications, and the floating AI Assistant button.
 *   Depends on extractor-core.js being loaded first (window.__extractorCore).
 *
 * Contents:
 *   - Modal system: injectModalStyles, showModal, updateModalContent,
 *     closeModal, copyModalContent, continueInChat
 *   - handleQuickAction() — UI wrapper that calls core's quickActionRequest()
 *     then renders the result in a modal
 *   - showToast() — toast notification overlay
 *   - createFloatingButton() — floating AI Assistant FAB
 *   - chrome.runtime.onMessage handler for UI types:
 *     QUICK_ACTION, SHOW_MODAL, HIDE_MODAL
 *
 * Load order: extractor-core.js MUST be loaded before this file.
 */

(function() {
    'use strict';

    // ==================== Modal for Quick Actions ====================

    let modal = null;
    let modalStylesInjected = false;

    /**
     * Inject modal styles
     */
    function injectModalStyles() {
        if (modalStylesInjected) return;
        
        const styles = document.createElement('style');
        styles.textContent = `
            .ai-assistant-modal {
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                width: 90%;
                max-width: 500px;
                max-height: 70vh;
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 12px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
                z-index: 2147483647;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                color: #e6edf3;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            .ai-assistant-modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.6);
                z-index: 2147483646;
            }

            .ai-assistant-modal-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 12px 16px;
                border-bottom: 1px solid #30363d;
                background: #161b22;
            }

            .ai-assistant-modal-title {
                font-size: 14px;
                font-weight: 600;
                margin: 0;
            }

            .ai-assistant-modal-close {
                background: none;
                border: none;
                color: #8b949e;
                cursor: pointer;
                padding: 4px;
                border-radius: 4px;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .ai-assistant-modal-close:hover {
                background: #30363d;
                color: #e6edf3;
            }

            .ai-assistant-modal-body {
                flex: 1;
                padding: 16px;
                overflow-y: auto;
                font-size: 14px;
                line-height: 1.6;
            }

            .ai-assistant-modal-body p {
                margin: 8px 0;
            }

            .ai-assistant-modal-body code {
                background: rgba(255, 255, 255, 0.1);
                padding: 2px 6px;
                border-radius: 4px;
                font-family: monospace;
            }

            .ai-assistant-modal-body pre {
                background: #0a0e14;
                padding: 12px;
                border-radius: 8px;
                overflow-x: auto;
                margin: 12px 0;
            }

            .ai-assistant-modal-body pre code {
                background: none;
                padding: 0;
            }

            .ai-assistant-modal-footer {
                display: flex;
                gap: 8px;
                padding: 12px 16px;
                border-top: 1px solid #30363d;
                background: #161b22;
            }

            .ai-assistant-modal-btn {
                padding: 8px 16px;
                border: 1px solid #30363d;
                border-radius: 6px;
                background: #21262d;
                color: #e6edf3;
                font-size: 13px;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .ai-assistant-modal-btn:hover {
                background: #30363d;
            }

            .ai-assistant-modal-btn-primary {
                background: #00d4ff;
                color: #0d1117;
                border-color: #00d4ff;
            }

            .ai-assistant-modal-btn-primary:hover {
                background: #33ddff;
            }

            .ai-assistant-loading {
                display: flex;
                align-items: center;
                gap: 8px;
                color: #8b949e;
            }

            .ai-assistant-loading-dots span {
                width: 6px;
                height: 6px;
                background: #00d4ff;
                border-radius: 50%;
                display: inline-block;
                animation: aiAssistantBounce 1.4s infinite ease-in-out;
            }

            .ai-assistant-loading-dots span:nth-child(1) { animation-delay: 0s; }
            .ai-assistant-loading-dots span:nth-child(2) { animation-delay: 0.2s; }
            .ai-assistant-loading-dots span:nth-child(3) { animation-delay: 0.4s; }

            @keyframes aiAssistantBounce {
                0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
                40% { transform: scale(1); opacity: 1; }
            }
            
            /* Floating Button Styles */
            :root {
                /* Tune these if the FAB overlaps site UI */
                --ai-assistant-fab-right: 12px;
                --ai-assistant-fab-bottom: 160px;
                --ai-assistant-fab-size: 40px;
            }

            #ai-assistant-floating-btn {
                position: fixed;
                bottom: var(--ai-assistant-fab-bottom);
                right: var(--ai-assistant-fab-right);
                width: var(--ai-assistant-fab-size);
                height: var(--ai-assistant-fab-size);
                border-radius: 50%;
                background: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
                border: none;
                color: white;
                font-size: 22px;
                cursor: pointer;
                box-shadow: 0 4px 16px rgba(0, 212, 255, 0.4);
                z-index: 2147483645;
                transition: transform 0.2s, box-shadow 0.2s;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            #ai-assistant-floating-btn:hover {
                transform: scale(1.08);
                box-shadow: 0 6px 24px rgba(0, 212, 255, 0.6);
            }
            
            #ai-assistant-floating-btn:active {
                transform: scale(0.95);
            }
            
            #ai-assistant-floating-btn svg {
                width: 20px;
                height: 20px;
            }
        `;
        document.head.appendChild(styles);
        modalStylesInjected = true;
    }

    /**
     * Show modal with loading state
     */
    function showModal(title) {
        injectModalStyles();
        closeModal();

        const overlay = document.createElement('div');
        overlay.className = 'ai-assistant-modal-overlay';
        overlay.addEventListener('click', closeModal);

        modal = document.createElement('div');
        modal.className = 'ai-assistant-modal';
        modal.innerHTML = `
            <div class="ai-assistant-modal-header">
                <h3 class="ai-assistant-modal-title">${title}</h3>
                <button class="ai-assistant-modal-close" aria-label="Close">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
            <div class="ai-assistant-modal-body">
                <div class="ai-assistant-loading">
                    <div class="ai-assistant-loading-dots">
                        <span></span><span></span><span></span>
                    </div>
                    <span>Thinking...</span>
                </div>
            </div>
            <div class="ai-assistant-modal-footer">
                <button class="ai-assistant-modal-btn" id="ai-copy-btn">
                    📋 Copy
                </button>
                <button class="ai-assistant-modal-btn" id="ai-continue-btn">
                    💬 Continue in Chat
                </button>
            </div>
        `;

        modal.querySelector('.ai-assistant-modal-close').addEventListener('click', closeModal);
        modal.querySelector('#ai-copy-btn').addEventListener('click', copyModalContent);
        modal.querySelector('#ai-continue-btn').addEventListener('click', continueInChat);

        document.body.appendChild(overlay);
        document.body.appendChild(modal);
    }

    /**
     * Update modal content
     */
    function updateModalContent(content) {
        if (!modal) return;
        const body = modal.querySelector('.ai-assistant-modal-body');
        body.innerHTML = content;
    }

    /**
     * Close modal
     */
    function closeModal() {
        const overlay = document.querySelector('.ai-assistant-modal-overlay');
        if (overlay) overlay.remove();
        if (modal) {
            modal.remove();
            modal = null;
        }
    }

    /**
     * Copy modal content to clipboard
     */
    function copyModalContent() {
        if (!modal) return;
        const body = modal.querySelector('.ai-assistant-modal-body');
        const text = body.innerText || body.textContent;
        navigator.clipboard.writeText(text).then(() => {
            const btn = modal.querySelector('#ai-copy-btn');
            btn.textContent = '✓ Copied!';
            setTimeout(() => {
                btn.textContent = '📋 Copy';
            }, 2000);
        });
    }

    /**
     * Continue conversation in sidepanel
     */
    function continueInChat() {
        if (!modal) return;
        
        chrome.runtime.sendMessage({
            type: 'OPEN_SIDEPANEL'
        });
        
        closeModal();
    }

    // ==================== Quick Action Handler ====================

    /**
     * Handle quick action from context menu.
     * Shows a modal, calls the core quickActionRequest() API, and renders the result.
     */
    async function handleQuickAction(action, text) {
        const actionTitles = {
            explain: '💡 Explanation',
            summarize: '📝 Summary',
            critique: '🔍 Critique',
            expand: '📖 Expansion',
            eli5: '🧒 ELI5',
            translate: '🌐 Translation'
        };

        const title = actionTitles[action] || 'AI Response';
        showModal(title);

        try {
            const data = await window.__extractorCore.quickActionRequest(action, text);
            
            // Simple markdown-ish rendering
            let content = data.response || 'No response';
            content = content
                .replace(/\n/g, '<br>')
                .replace(/`([^`]+)`/g, '<code>$1</code>')
                .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            
            updateModalContent(`<p>${content}</p>`);

        } catch (error) {
            console.error('[AI Assistant] Quick action failed:', error);
            updateModalContent(`<p style="color: #ef4444;">Error: ${error.message}</p>`);
        }
    }

    // ==================== Toast Notification ====================

    /**
     * Show a toast notification to the user
     * @param {string} message - Message to display
     * @param {number} duration - Duration in ms (default 4000)
     */
    function showToast(message, duration = 4000) {
        // Remove existing toast if any
        const existingToast = document.getElementById('ai-assistant-toast');
        if (existingToast) {
            existingToast.remove();
        }
        
        const toast = document.createElement('div');
        toast.id = 'ai-assistant-toast';
        toast.innerHTML = `
            <style>
                #ai-assistant-toast {
                    position: fixed;
                    bottom: calc(var(--ai-assistant-fab-bottom) + var(--ai-assistant-fab-size) + 12px);
                    right: var(--ai-assistant-fab-right);
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    color: #e8e8e8;
                    padding: 14px 20px;
                    border-radius: 12px;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    font-size: 14px;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
                    z-index: 2147483647;
                    animation: ai-toast-slide-in 0.3s ease-out;
                    max-width: 320px;
                    border: 1px solid rgba(79, 134, 247, 0.3);
                }
                #ai-assistant-toast.hiding {
                    animation: ai-toast-slide-out 0.3s ease-in forwards;
                }
                @keyframes ai-toast-slide-in {
                    from { transform: translateX(100%); opacity: 0; }
                    to { transform: translateX(0); opacity: 1; }
                }
                @keyframes ai-toast-slide-out {
                    from { transform: translateX(0); opacity: 1; }
                    to { transform: translateX(100%); opacity: 0; }
                }
            </style>
            ${message}
        `;
        
        document.body.appendChild(toast);
        
        // Auto-remove after duration
        setTimeout(() => {
            toast.classList.add('hiding');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // ==================== Floating Button ====================

    function createFloatingButton() {
        // Don't add button if it already exists
        if (document.getElementById('ai-assistant-floating-btn')) return;
        
        // Inject styles first
        injectModalStyles();
        
        const button = document.createElement('button');
        button.id = 'ai-assistant-floating-btn';
        button.title = 'Open AI Assistant';
        button.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z"></path>
                <path d="M2 17l10 5 10-5"></path>
                <path d="M2 12l10 5 10-5"></path>
            </svg>
        `;
        
        button.addEventListener('click', (e) => {
            // Stop propagation to prevent page scripts from handling this click
            // (fixes issues on sites like Hacker News where their JS tries to call .split() on SVG className)
            e.stopPropagation();
            e.preventDefault();
            
            console.log('[AI Assistant] Floating button clicked, requesting sidepanel open');
            
            chrome.runtime.sendMessage({ type: 'OPEN_SIDEPANEL' }, (response) => {
                if (chrome.runtime.lastError) {
                    console.error('[AI Assistant] Failed to send OPEN_SIDEPANEL message:', chrome.runtime.lastError.message);
                    showToast('Click the extension icon (🤖) in the toolbar to open AI Assistant');
                    return;
                }
                if (response && response.error) {
                    console.error('[AI Assistant] Sidepanel open failed:', response.error);
                    // If Chrome blocks sidePanel.open(), the service worker may fall back to a popup window.
                    // Otherwise, guide the user to click the extension icon.
                    if (response.fallbackToIcon) {
                        showToast('Click the extension icon (🤖) in the toolbar to open AI Assistant');
                    } else {
                        showToast('Could not open AI Assistant. Please try clicking the extension icon (🤖).');
                    }
                } else if (response && response.success) {
                    console.log('[AI Assistant] Sidepanel opened successfully');
                }
            });
        });
        
        document.body.appendChild(button);
        console.log('[AI Assistant] Floating button created');
    }

    // ==================== UI Message Listener ====================

    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        var UI_TYPES = {
            'QUICK_ACTION': true,
            'SHOW_MODAL': true,
            'HIDE_MODAL': true
        };

        if (!UI_TYPES[message.type]) return;

        console.log('[AI Assistant] UI received:', message.type);

        try {
            switch (message.type) {
                case 'QUICK_ACTION':
                    handleQuickAction(message.action, message.text);
                    sendResponse({ success: true });
                    break;

                case 'SHOW_MODAL':
                    showModal(message.title || 'AI Response');
                    if (message.content) {
                        updateModalContent(message.content);
                    }
                    sendResponse({ success: true });
                    break;

                case 'HIDE_MODAL':
                    closeModal();
                    sendResponse({ success: true });
                    break;
            }
        } catch (error) {
            console.error('[AI Assistant] UI message handler error:', error);
            sendResponse({ error: error.message });
        }

        return true; // Keep channel open for async
    });
    
    // Create floating button after DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', createFloatingButton);
    } else {
        createFloatingButton();
    }

    console.log('[AI Assistant] Extractor UI ready');
})();
