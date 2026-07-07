/**
 * Script Runner Core - Custom Scripts Execution Engine (Shared)
 *
 * This is the shared core of the script runner, used by both the main Chrome
 * extension and the headless bridge extension. It loads user-created custom
 * scripts that match the current URL, provides the `aiAssistant` API to those
 * scripts, executes them in a sandboxed context, and manages their lifecycle.
 *
 * ## Modes
 *
 * **Default (auto-init)** – When loaded without any prior configuration the
 * script runner calls `initialize()` immediately, exactly as the original
 * `script_runner.js` does. This keeps backwards compatibility with the main
 * extension.
 *
 * **On-demand** – When the hosting page sets
 *   `window.__scriptRunnerMode = 'ondemand'`
 * *before* this script is injected/executed, the auto-init is skipped. The
 * caller is then responsible for triggering initialization explicitly via:
 *   `window.__scriptRunner.initialize()`
 * This is used by the headless bridge extension which needs to configure the
 * environment before the script runner starts talking to the service worker.
 *
 * ## Public API (`window.__scriptRunner`)
 *
 * - `initialize()`              – Start the script runner (load scripts, watch
 *                                  for SPA navigations). No-op if already
 *                                  initialised.
 * - `loadedScripts`             – Map of currently loaded scripts.
 * - `callHandler(scriptId, fn)` – Invoke a handler inside a loaded script.
 * - `loadScriptsForCurrentUrl()`– Re-fetch & execute matching scripts.
 * - `showToast(msg, type)`      – Display a toast notification.
 * - `showModal(title, html)`    – Display a modal dialog.
 * - `closeModal()`              – Close the current modal.
 *
 * @module script-runner-core
 */

(function() {
    'use strict';

    // Prevent multiple initializations
    if (window.__scriptRunnerInitialized) {
        return;
    }
    window.__scriptRunnerInitialized = true;

    // Debug logging (can be disabled in production)
    const DEBUG = true;
    const log = (...args) => DEBUG && console.log('[ScriptRunner]', ...args);
    const logError = (...args) => console.error('[ScriptRunner]', ...args);

    // ==========================================================================
    // State Management
    // ==========================================================================

    /**
     * Currently loaded scripts and their handlers
     * @type {Map<string, {script: Object, handlers: Object}>}
     */
    const loadedScripts = new Map();

    /**
     * Script storage prefix for isolation
     * @type {string}
     */
    const STORAGE_PREFIX = 'script_';

    // ==========================================================================
    // aiAssistant API Implementation
    // ==========================================================================

    /**
     * Creates the aiAssistant API object for a specific script.
     * Each script gets its own isolated storage namespace.
     * 
     * @param {string} scriptId - The script's unique ID
     * @returns {Object} The aiAssistant API object
     */
    function createAiAssistantAPI(scriptId) {
        /**
         * Dispatch a bubbling event on an element.
         * @param {Element} el
         * @param {string} type
         */
        function dispatchBubbledEvent(el, type) {
            el.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }));
        }

        /**
         * Get first matching element or null.
         * @param {string} selector
         * @returns {Element|null}
         */
        function first(selector) {
            return document.querySelector(selector);
        }

        /**
         * Get all matching elements.
         * @param {string} selector
         * @returns {Element[]}
         */
        function all(selector) {
            return [...document.querySelectorAll(selector)];
        }

        return {
            // -----------------------------------------------------------------
            // DOM Helpers
            // -----------------------------------------------------------------
            dom: {
                /**
                 * Check whether an element exists.
                 * @param {string} selector
                 * @returns {boolean}
                 */
                exists: (selector) => !!first(selector),

                /**
                 * Count matching elements.
                 * @param {string} selector
                 * @returns {number}
                 */
                count: (selector) => document.querySelectorAll(selector).length,

                /**
                 * Query for a single element
                 * @param {string} selector - CSS selector
                 * @returns {Element|null}
                 */
                query: (selector) => first(selector),

                /**
                 * Query for all matching elements
                 * @param {string} selector - CSS selector
                 * @returns {Element[]}
                 */
                queryAll: (selector) => all(selector),

                /**
                 * Get text content of an element
                 * @param {string} selector - CSS selector
                 * @returns {string}
                 */
                getText: (selector) => {
                    const el = first(selector);
                    return el ? el.textContent.trim() : '';
                },

                /**
                 * Get innerHTML of an element.
                 * @param {string} selector
                 * @returns {string}
                 */
                getHtml: (selector) => {
                    const el = first(selector);
                    return el ? el.innerHTML : '';
                },

                /**
                 * Get an attribute value.
                 * @param {string} selector
                 * @param {string} name
                 * @returns {string|null}
                 */
                getAttr: (selector, name) => {
                    const el = first(selector);
                    return el ? el.getAttribute(name) : null;
                },

                /**
                 * Set an attribute value.
                 * @param {string} selector
                 * @param {string} name
                 * @param {string} value
                 * @returns {boolean}
                 */
                setAttr: (selector, name, value) => {
                    const el = first(selector);
                    if (!el) return false;
                    el.setAttribute(name, String(value));
                    return true;
                },

                /**
                 * Get current value for inputs/textareas/selects.
                 * @param {string} selector
                 * @returns {string}
                 */
                getValue: (selector) => {
                    const el = first(selector);
                    if (!el) return '';
                    if (el instanceof HTMLInputElement) {
                        if (el.type === 'checkbox' || el.type === 'radio') return el.checked ? 'true' : 'false';
                        return el.value;
                    }
                    if (el instanceof HTMLTextAreaElement) return el.value;
                    if (el instanceof HTMLSelectElement) return el.value;
                    if (el instanceof HTMLElement && el.isContentEditable) return el.textContent || '';
                    // Fallback
                    // @ts-ignore
                    return String(el.value ?? '');
                },

                /**
                 * Wait for an element to appear in the DOM
                 * @param {string} selector - CSS selector
                 * @param {number} timeout - Timeout in ms (default 10000)
                 * @returns {Promise<Element>}
                 */
                waitFor: (selector, timeout = 10000) => {
                    return new Promise((resolve, reject) => {
                        const el = first(selector);
                        if (el) {
                            resolve(el);
                            return;
                        }

                        const observer = new MutationObserver((mutations, obs) => {
                            const el = first(selector);
                            if (el) {
                                obs.disconnect();
                                resolve(el);
                            }
                        });

                        observer.observe(document.body, {
                            childList: true,
                            subtree: true
                        });

                        setTimeout(() => {
                            observer.disconnect();
                            reject(new Error(`Timeout waiting for ${selector}`));
                        }, timeout);
                    });
                },

                /**
                 * Hide element(s) matching selector
                 * @param {string|Element} selectorOrElement - CSS selector or element
                 */
                hide: (selectorOrElement) => {
                    if (typeof selectorOrElement === 'string') {
                        all(selectorOrElement).forEach(el => {
                            el.style.display = 'none';
                        });
                    } else if (selectorOrElement instanceof Element) {
                        selectorOrElement.style.display = 'none';
                    }
                },

                /**
                 * Show element(s) matching selector
                 * @param {string|Element} selectorOrElement - CSS selector or element
                 */
                show: (selectorOrElement) => {
                    if (typeof selectorOrElement === 'string') {
                        all(selectorOrElement).forEach(el => {
                            el.style.display = '';
                        });
                    } else if (selectorOrElement instanceof Element) {
                        selectorOrElement.style.display = '';
                    }
                },

                /**
                 * Set innerHTML of element
                 * @param {string} selector - CSS selector
                 * @param {string} html - HTML content
                 */
                setHtml: (selector, html) => {
                    const el = first(selector);
                    if (el) {
                        el.innerHTML = html;
                    }
                },

                /**
                 * Scroll an element into view.
                 * @param {string} selector
                 * @param {ScrollBehavior} behavior
                 * @returns {boolean}
                 */
                scrollIntoView: (selector, behavior = 'smooth') => {
                    const el = first(selector);
                    if (!el) return false;
                    el.scrollIntoView({ behavior, block: 'center', inline: 'center' });
                    return true;
                },

                /**
                 * Focus an element.
                 * @param {string} selector
                 * @returns {boolean}
                 */
                focus: (selector) => {
                    const el = first(selector);
                    if (!el) return false;
                    // @ts-ignore
                    el.focus?.();
                    return true;
                },

                /**
                 * Blur an element.
                 * @param {string} selector
                 * @returns {boolean}
                 */
                blur: (selector) => {
                    const el = first(selector);
                    if (!el) return false;
                    // @ts-ignore
                    el.blur?.();
                    return true;
                },

                /**
                 * Click an element (best-effort).
                 * @param {string} selector
                 * @returns {boolean}
                 */
                click: (selector) => {
                    const el = first(selector);
                    if (!el) return false;
                    try {
                        el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
                    } catch {}
                    // Dispatch pointer/mouse events to satisfy some sites
                    try {
                        el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                        el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                    } catch {}
                    // Also call native click
                    // @ts-ignore
                    el.click?.();
                    return true;
                },

                /**
                 * Set value for inputs/textareas/selects/contenteditable and dispatch input/change events.
                 * @param {string} selector
                 * @param {any} value
                 * @returns {boolean}
                 */
                setValue: (selector, value) => {
                    const el = first(selector);
                    if (!el) return false;

                    const v = value == null ? '' : String(value);

                    if (el instanceof HTMLInputElement) {
                        if (el.type === 'checkbox') {
                            el.checked = v === 'true' || v === '1' || v === 'yes' || v === 'on';
                            dispatchBubbledEvent(el, 'change');
                            return true;
                        }
                        if (el.type === 'radio') {
                            el.checked = true;
                            dispatchBubbledEvent(el, 'change');
                            return true;
                        }
                        el.value = v;
                        dispatchBubbledEvent(el, 'input');
                        dispatchBubbledEvent(el, 'change');
                        return true;
                    }

                    if (el instanceof HTMLTextAreaElement) {
                        el.value = v;
                        dispatchBubbledEvent(el, 'input');
                        dispatchBubbledEvent(el, 'change');
                        return true;
                    }

                    if (el instanceof HTMLSelectElement) {
                        el.value = v;
                        dispatchBubbledEvent(el, 'change');
                        return true;
                    }

                    if (el instanceof HTMLElement && el.isContentEditable) {
                        el.textContent = v;
                        dispatchBubbledEvent(el, 'input');
                        dispatchBubbledEvent(el, 'change');
                        return true;
                    }

                    // Fallback: try value property
                    try {
                        // @ts-ignore
                        el.value = v;
                        dispatchBubbledEvent(el, 'input');
                        dispatchBubbledEvent(el, 'change');
                        return true;
                    } catch {
                        return false;
                    }
                },

                /**
                 * Type text into an input/textarea/contenteditable with optional delay.
                 * @param {string} selector
                 * @param {string} text
                 * @param {{ delayMs?: number, clearFirst?: boolean }} opts
                 * @returns {Promise<boolean>}
                 */
                type: async (selector, text, opts = {}) => {
                    const el = first(selector);
                    if (!el) return false;
                    const delayMs = typeof opts.delayMs === 'number' ? opts.delayMs : 0;
                    const clearFirst = !!opts.clearFirst;

                    // Focus
                    // @ts-ignore
                    el.focus?.();

                    if (clearFirst) {
                        // Clear existing
                        // @ts-ignore
                        if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) el.value = '';
                        else if (el instanceof HTMLElement && el.isContentEditable) el.textContent = '';
                        dispatchBubbledEvent(el, 'input');
                        dispatchBubbledEvent(el, 'change');
                    }

                    const chars = String(text ?? '').split('');
                    for (const ch of chars) {
                        if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
                            el.value += ch;
                        } else if (el instanceof HTMLElement && el.isContentEditable) {
                            el.textContent = (el.textContent || '') + ch;
                        } else {
                            // @ts-ignore
                            el.value = String((el.value ?? '')) + ch;
                        }
                        dispatchBubbledEvent(el, 'input');
                        if (delayMs > 0) await new Promise(r => setTimeout(r, delayMs));
                    }
                    dispatchBubbledEvent(el, 'change');
                    return true;
                },

                /**
                 * Remove elements matching selector.
                 * @param {string} selector
                 * @returns {number} number removed
                 */
                remove: (selector) => {
                    const els = all(selector);
                    els.forEach(el => el.remove());
                    return els.length;
                },

                /**
                 * Add a class to matching elements.
                 * @param {string} selector
                 * @param {string} className
                 * @returns {number}
                 */
                addClass: (selector, className) => {
                    const els = all(selector);
                    els.forEach(el => el.classList.add(className));
                    return els.length;
                },

                /**
                 * Remove a class from matching elements.
                 * @param {string} selector
                 * @param {string} className
                 * @returns {number}
                 */
                removeClass: (selector, className) => {
                    const els = all(selector);
                    els.forEach(el => el.classList.remove(className));
                    return els.length;
                },

                /**
                 * Toggle a class on matching elements.
                 * @param {string} selector
                 * @param {string} className
                 * @param {boolean=} force
                 * @returns {number}
                 */
                toggleClass: (selector, className, force) => {
                    const els = all(selector);
                    els.forEach(el => el.classList.toggle(className, force));
                    return els.length;
                }
            },

            // -----------------------------------------------------------------
            // Clipboard
            // -----------------------------------------------------------------
            clipboard: {
                /**
                 * Copy text to clipboard
                 * @param {string} text - Text to copy
                 * @returns {Promise<void>}
                 */
                copy: async (text) => {
                    try {
                        await navigator.clipboard.writeText(text);
                    } catch (err) {
                        // Fallback for older browsers
                        const textarea = document.createElement('textarea');
                        textarea.value = text;
                        textarea.style.position = 'fixed';
                        textarea.style.opacity = '0';
                        document.body.appendChild(textarea);
                        textarea.select();
                        document.execCommand('copy');
                        document.body.removeChild(textarea);
                    }
                },

                /**
                 * Copy HTML to clipboard (as rich text)
                 * @param {string} html - HTML content
                 * @returns {Promise<void>}
                 */
                copyHtml: async (html) => {
                    try {
                        const blob = new Blob([html], { type: 'text/html' });
                        const item = new ClipboardItem({ 'text/html': blob });
                        await navigator.clipboard.write([item]);
                    } catch (err) {
                        // Fallback: copy as plain text
                        const div = document.createElement('div');
                        div.innerHTML = html;
                        await navigator.clipboard.writeText(div.textContent);
                    }
                }
            },

            // -----------------------------------------------------------------
            // UI Helpers
            // -----------------------------------------------------------------
            ui: {
                /**
                 * Show a toast notification
                 * @param {string} message - Message to display
                 * @param {string} type - 'success', 'error', 'info', 'warning'
                 */
                showToast: (message, type = 'info') => {
                    showToast(message, type);
                },

                /**
                 * Show a modal dialog
                 * @param {string} title - Modal title
                 * @param {string} content - Modal content (can be HTML)
                 */
                showModal: (title, content) => {
                    showModal(title, content);
                },

                /**
                 * Close the current modal
                 */
                closeModal: () => {
                    closeModal();
                }
            },

            // -----------------------------------------------------------------
            // LLM API (proxied through service worker)
            // -----------------------------------------------------------------
            llm: {
                /**
                 * Ask the LLM a question
                 * @param {string} prompt - The prompt to send
                 * @returns {Promise<string>}
                 */
                ask: async (prompt) => {
                    return new Promise((resolve, reject) => {
                        chrome.runtime.sendMessage({
                            type: 'SCRIPT_LLM_REQUEST',
                            prompt: prompt
                        }, (response) => {
                            if (chrome.runtime.lastError) {
                                reject(new Error(chrome.runtime.lastError.message));
                            } else if (response.error) {
                                reject(new Error(response.error));
                            } else {
                                resolve(response.response);
                            }
                        });
                    });
                },

                /**
                 * Ask the LLM with streaming response
                 * @param {string} prompt - The prompt to send
                 * @param {function} onChunk - Callback for each chunk
                 * @returns {Promise<void>}
                 */
                askStreaming: async (prompt, onChunk) => {
                    // Streaming is more complex with content scripts
                    // For now, fall back to non-streaming
                    const response = await this.ask(prompt);
                    onChunk(response);
                }
            },

            // -----------------------------------------------------------------
            // Storage (per-script isolated)
            // -----------------------------------------------------------------
            storage: {
                /**
                 * Get a stored value
                 * @param {string} key - Storage key
                 * @returns {Promise<any>}
                 */
                get: async (key) => {
                    return new Promise((resolve) => {
                        const fullKey = `${STORAGE_PREFIX}${scriptId}_${key}`;
                        chrome.storage.local.get([fullKey], (result) => {
                            resolve(result[fullKey]);
                        });
                    });
                },

                /**
                 * Set a stored value
                 * @param {string} key - Storage key
                 * @param {any} value - Value to store
                 * @returns {Promise<void>}
                 */
                set: async (key, value) => {
                    return new Promise((resolve) => {
                        const fullKey = `${STORAGE_PREFIX}${scriptId}_${key}`;
                        chrome.storage.local.set({ [fullKey]: value }, resolve);
                    });
                }
            }
        };
    }

    // ==========================================================================
    // UI Components (Toast & Modal)
    // ==========================================================================

    // Style element for UI components
    let styleElement = null;

    /**
     * Inject styles for UI components
     */
    function injectStyles() {
        if (styleElement) return;

        styleElement = document.createElement('style');
        styleElement.id = 'ai-assistant-script-styles';
        styleElement.textContent = `
            /* Toast Notifications */
            .ai-script-toast {
                position: fixed;
                bottom: 20px;
                right: 20px;
                padding: 12px 24px;
                border-radius: 8px;
                color: white;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 14px;
                z-index: 2147483647;
                opacity: 0;
                transform: translateY(20px);
                transition: opacity 0.3s, transform 0.3s;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            }
            .ai-script-toast.show {
                opacity: 1;
                transform: translateY(0);
            }
            .ai-script-toast.success { background: #10b981; }
            .ai-script-toast.error { background: #ef4444; }
            .ai-script-toast.info { background: #3b82f6; }
            .ai-script-toast.warning { background: #f59e0b; }

            /* Modal */
            .ai-script-modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0,0,0,0.5);
                z-index: 2147483646;
                display: flex;
                align-items: center;
                justify-content: center;
                opacity: 0;
                transition: opacity 0.3s;
            }
            .ai-script-modal-overlay.show {
                opacity: 1;
            }
            .ai-script-modal {
                background: white;
                border-radius: 12px;
                max-width: 600px;
                max-height: 80vh;
                width: 90%;
                overflow: hidden;
                box-shadow: 0 20px 40px rgba(0,0,0,0.2);
                transform: scale(0.9);
                transition: transform 0.3s;
            }
            .ai-script-modal-overlay.show .ai-script-modal {
                transform: scale(1);
            }
            .ai-script-modal-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 16px 20px;
                border-bottom: 1px solid #e5e7eb;
            }
            .ai-script-modal-title {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 18px;
                font-weight: 600;
                color: #111827;
                margin: 0;
            }
            .ai-script-modal-close {
                background: none;
                border: none;
                font-size: 24px;
                color: #6b7280;
                cursor: pointer;
                padding: 0;
                line-height: 1;
            }
            .ai-script-modal-close:hover {
                color: #111827;
            }
            .ai-script-modal-content {
                padding: 20px;
                overflow-y: auto;
                max-height: calc(80vh - 60px);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                font-size: 14px;
                color: #374151;
                line-height: 1.6;
            }
        `;
        document.head.appendChild(styleElement);
    }

    /**
     * Show a toast notification
     * @param {string} message - Message to display
     * @param {string} type - 'success', 'error', 'info', 'warning'
     */
    function showToast(message, type = 'info') {
        injectStyles();

        const toast = document.createElement('div');
        toast.className = `ai-script-toast ${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        // Remove after 3 seconds
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // Current modal element
    let currentModal = null;

    /**
     * Show a modal dialog
     * @param {string} title - Modal title
     * @param {string} content - Modal content (can be HTML)
     */
    function showModal(title, content) {
        injectStyles();
        closeModal(); // Close any existing modal

        const overlay = document.createElement('div');
        overlay.className = 'ai-script-modal-overlay';
        overlay.innerHTML = `
            <div class="ai-script-modal">
                <div class="ai-script-modal-header">
                    <h3 class="ai-script-modal-title">${escapeHtml(title)}</h3>
                    <button class="ai-script-modal-close">&times;</button>
                </div>
                <div class="ai-script-modal-content">${content}</div>
            </div>
        `;

        // Close on overlay click
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });

        // Close button
        overlay.querySelector('.ai-script-modal-close').addEventListener('click', closeModal);

        document.body.appendChild(overlay);
        currentModal = overlay;

        // Trigger animation
        requestAnimationFrame(() => {
            overlay.classList.add('show');
        });
    }

    /**
     * Close the current modal
     */
    function closeModal() {
        if (currentModal) {
            currentModal.classList.remove('show');
            setTimeout(() => {
                currentModal.remove();
                currentModal = null;
            }, 300);
        }
    }

    /**
     * Escape HTML to prevent XSS
     * @param {string} str - String to escape
     * @returns {string}
     */
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ==========================================================================
    // Script Execution
    // ==========================================================================

    // --------------------------------------------------------------------------
    // Sandbox Transport (no unsafe-eval in content scripts)
    // --------------------------------------------------------------------------

    const sandboxOrigin = new URL(chrome.runtime.getURL('sandbox/sandbox.html')).origin;
    let sandboxIframe = null;
    let sandboxReady = false;
    /** @type {Map<string, {resolve: Function, reject: Function, timeoutId: number}>} */
    const sandboxPending = new Map();

    function ensureSandboxIframe() {
        if (sandboxIframe && sandboxReady) return;
        if (sandboxIframe) return;

        sandboxIframe = document.createElement('iframe');
        sandboxIframe.id = 'ai-assistant-sandbox-iframe';
        sandboxIframe.src = chrome.runtime.getURL('sandbox/sandbox.html');
        sandboxIframe.style.position = 'fixed';
        sandboxIframe.style.width = '1px';
        sandboxIframe.style.height = '1px';
        sandboxIframe.style.opacity = '0';
        sandboxIframe.style.pointerEvents = 'none';
        sandboxIframe.style.left = '-9999px';
        sandboxIframe.style.top = '-9999px';
        document.documentElement.appendChild(sandboxIframe);
    }

    function sandboxRequest(type, payload) {
        ensureSandboxIframe();
        const requestId = `sb_${Date.now()}_${Math.random().toString(16).slice(2)}`;

        return new Promise((resolve, reject) => {
            const timeoutId = window.setTimeout(() => {
                sandboxPending.delete(requestId);
                reject(new Error(`Sandbox timeout: ${type}`));
            }, 15000);

            sandboxPending.set(requestId, { resolve, reject, timeoutId });

            const msg = {
                __aiAssistantSandbox: true,
                type,
                requestId,
                ...payload
            };

            // Post to sandbox iframe
            sandboxIframe.contentWindow.postMessage(msg, sandboxOrigin);
        });
    }

    // Handle messages from sandbox iframe
    window.addEventListener('message', async (event) => {
        if (event.origin !== sandboxOrigin) return;
        const data = event.data;
        if (!data || data.__aiAssistantSandbox !== true) return;

        // Handshake
        if (data.type === 'READY') {
            sandboxReady = true;
            return;
        }

        // Sandbox -> Content Script RPC
        if (data.type === 'RPC') {
            const { requestId, scriptId, method, args } = data;
            try {
                const result = await handleSandboxRpc(scriptId, method, args || []);
                event.source.postMessage({
                    __aiAssistantSandbox: true,
                    type: 'RPC_RESPONSE',
                    requestId,
                    ok: true,
                    result
                }, sandboxOrigin);
            } catch (e) {
                event.source.postMessage({
                    __aiAssistantSandbox: true,
                    type: 'RPC_RESPONSE',
                    requestId,
                    ok: false,
                    error: e?.message || String(e)
                }, sandboxOrigin);
            }
            return;
        }

        // Responses to our sandboxRequest calls
        if (data.type === 'RESPONSE') {
            const pending = sandboxPending.get(data.requestId);
            if (!pending) return;
            sandboxPending.delete(data.requestId);
            window.clearTimeout(pending.timeoutId);
            if (data.ok) pending.resolve(data.result);
            else pending.reject(new Error(data.error || 'Sandbox error'));
        }
    });

    async function handleSandboxRpc(scriptId, method, args) {
        const api = createAiAssistantAPI(scriptId);

        switch (method) {
            // DOM (must return serializable values)
            case 'dom.query': {
                const selector = args[0];
                return { exists: api.dom.exists(selector), selector };
            }
            case 'dom.queryAll': {
                const selector = args[0];
                return { count: api.dom.count(selector), selector };
            }
            case 'dom.exists':
                return api.dom.exists(args[0]);
            case 'dom.count':
                return api.dom.count(args[0]);
            case 'dom.getText':
                return api.dom.getText(args[0]);
            case 'dom.getHtml':
                return api.dom.getHtml(args[0]);
            case 'dom.getAttr':
                return api.dom.getAttr(args[0], args[1]);
            case 'dom.setAttr':
                return api.dom.setAttr(args[0], args[1], args[2]);
            case 'dom.getValue':
                return api.dom.getValue(args[0]);
            case 'dom.waitFor': {
                const selector = args[0];
                const timeout = args[1] ?? 10000;
                await api.dom.waitFor(selector, timeout);
                return { found: true, selector };
            }
            case 'dom.hide':
                api.dom.hide(args[0]);
                return true;
            case 'dom.show':
                api.dom.show(args[0]);
                return true;
            case 'dom.setHtml':
                api.dom.setHtml(args[0], args[1]);
                return true;
            case 'dom.scrollIntoView':
                return api.dom.scrollIntoView(args[0], args[1] ?? 'smooth');
            case 'dom.focus':
                return api.dom.focus(args[0]);
            case 'dom.blur':
                return api.dom.blur(args[0]);
            case 'dom.click':
                return api.dom.click(args[0]);
            case 'dom.setValue':
                return api.dom.setValue(args[0], args[1]);
            case 'dom.type':
                return await api.dom.type(args[0], args[1], args[2] || {});
            case 'dom.remove':
                return api.dom.remove(args[0]);
            case 'dom.addClass':
                return api.dom.addClass(args[0], args[1]);
            case 'dom.removeClass':
                return api.dom.removeClass(args[0], args[1]);
            case 'dom.toggleClass':
                return api.dom.toggleClass(args[0], args[1], args[2]);

            // Clipboard
            case 'clipboard.copy':
                return api.clipboard.copy(args[0]);
            case 'clipboard.copyHtml':
                return api.clipboard.copyHtml(args[0]);

            // UI
            case 'ui.showToast':
                api.ui.showToast(args[0], args[1]);
                return true;
            case 'ui.showModal':
                api.ui.showModal(args[0], args[1]);
                return true;
            case 'ui.closeModal':
                api.ui.closeModal();
                return true;

            // LLM
            case 'llm.ask':
                return api.llm.ask(args[0]);

            // Storage
            case 'storage.get':
                return api.storage.get(args[0]);
            case 'storage.set':
                return api.storage.set(args[0], args[1]);
        }

        throw new Error(`Unsupported sandbox RPC method: ${method}`);
    }

    /**
     * Execute a user script in a sandboxed context
     * @param {Object} script - Script object from database
     */
    async function executeScript(script) {
        const { script_id, code, actions, name } = script;

        log(`Executing script: ${name} (${script_id})`);

        try {
            // Ensure sandbox is ready
            ensureSandboxIframe();

            const result = await sandboxRequest('EXECUTE', {
                scriptId: script_id,
                code
            });

            loadedScripts.set(script_id, { script, handlerNames: result?.handlerNames || [] });
            log(`Script loaded successfully: ${name}`);

            // Notify that scripts are available
            notifyScriptsLoaded();
        } catch (err) {
            logError(`Failed to execute script: ${name}`, err);
        }
    }

    /**
     * Call a handler function from a loaded script
     * @param {string} scriptId - Script ID
     * @param {string} handlerName - Handler function name
     * @returns {Promise<any>}
     */
    async function callHandler(scriptId, handlerName) {
        const loaded = loadedScripts.get(scriptId);
        if (!loaded) {
            throw new Error(`Script ${scriptId} not loaded`);
        }
        // Invoke the handler inside the sandbox environment
        return await sandboxRequest('INVOKE', {
            scriptId,
            handlerName
        });
    }

    // ==========================================================================
    // Script Loading
    // ==========================================================================

    /**
     * Request scripts for current URL from service worker
     */
    async function loadScriptsForCurrentUrl() {
        const url = window.location.href;
        log(`Loading scripts for URL: ${url}`);

        try {
            const response = await new Promise((resolve, reject) => {
                chrome.runtime.sendMessage({
                    type: 'GET_SCRIPTS_FOR_URL',
                    url: url
                }, (response) => {
                    if (chrome.runtime.lastError) {
                        reject(new Error(chrome.runtime.lastError.message));
                    } else {
                        resolve(response);
                    }
                });
            });

            if (response.error) {
                logError('Failed to load scripts:', response.error);
                return;
            }

            const scripts = response.scripts || [];
            log(`Found ${scripts.length} matching scripts`);

            // Execute each script
            // Execute each script
            scripts.forEach(script => { executeScript(script); });

        } catch (err) {
            logError('Error loading scripts:', err);
        }
    }

    /**
     * Notify UI components that scripts have been loaded
     */
    function notifyScriptsLoaded() {
        // Dispatch custom event for UI components
        window.dispatchEvent(new CustomEvent('ai-scripts-loaded', {
            detail: {
                scripts: Array.from(loadedScripts.values()).map(s => ({
                    script_id: s.script.script_id,
                    name: s.script.name,
                    actions: s.script.actions || []
                }))
            }
        }));
    }

    // ==========================================================================
    // Page Context Extraction
    // ==========================================================================

    /**
     * Get structured page context for LLM-based script generation.
     * Extracts meaningful DOM structure, forms, interactive elements, etc.
     * 
     * @returns {Object} Structured page context
     */
    function getPageContext() {
        const context = {
            url: window.location.href,
            origin: window.location.origin,
            pathname: window.location.pathname,
            title: document.title,
            timestamp: new Date().toISOString()
        };

        // Extract meta information
        context.meta = {
            description: document.querySelector('meta[name="description"]')?.content || '',
            keywords: document.querySelector('meta[name="keywords"]')?.content || '',
            ogTitle: document.querySelector('meta[property="og:title"]')?.content || '',
            ogDescription: document.querySelector('meta[property="og:description"]')?.content || ''
        };

        // Extract main headings
        context.headings = [];
        document.querySelectorAll('h1, h2, h3').forEach((h, i) => {
            if (i < 20) { // Limit to first 20 headings
                context.headings.push({
                    level: parseInt(h.tagName[1]),
                    text: h.textContent.trim().substring(0, 200),
                    id: h.id || null,
                    className: h.className || null
                });
            }
        });

        // Extract forms
        context.forms = [];
        document.querySelectorAll('form').forEach((form, i) => {
            if (i < 10) { // Limit to 10 forms
                const fields = [];
                form.querySelectorAll('input, select, textarea').forEach((field, j) => {
                    if (j < 20) { // Limit to 20 fields per form
                        fields.push({
                            type: field.type || field.tagName.toLowerCase(),
                            name: field.name || null,
                            id: field.id || null,
                            placeholder: field.placeholder || null,
                            required: field.required || false
                        });
                    }
                });
                context.forms.push({
                    id: form.id || null,
                    className: form.className || null,
                    action: form.action || null,
                    method: form.method || 'get',
                    fields: fields
                });
            }
        });

        // Extract buttons and interactive elements
        context.buttons = [];
        document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]').forEach((btn, i) => {
            if (i < 30) { // Limit to 30 buttons
                context.buttons.push({
                    text: btn.textContent?.trim().substring(0, 100) || btn.value || '',
                    id: btn.id || null,
                    className: btn.className || null,
                    type: btn.type || null,
                    ariaLabel: btn.getAttribute('aria-label') || null
                });
            }
        });

        // Extract links (main navigation and important links)
        context.links = [];
        document.querySelectorAll('nav a, header a, [role="navigation"] a').forEach((link, i) => {
            if (i < 30) {
                context.links.push({
                    text: link.textContent?.trim().substring(0, 100) || '',
                    href: link.href || null,
                    id: link.id || null
                });
            }
        });

        // Extract main content areas
        context.contentAreas = [];
        const contentSelectors = ['main', 'article', '[role="main"]', '.content', '#content', '.main-content'];
        contentSelectors.forEach(selector => {
            const el = document.querySelector(selector);
            if (el) {
                context.contentAreas.push({
                    selector: selector,
                    tagName: el.tagName.toLowerCase(),
                    id: el.id || null,
                    className: el.className || null,
                    textPreview: el.textContent?.trim().substring(0, 500) || ''
                });
            }
        });

        // Extract tables
        context.tables = [];
        document.querySelectorAll('table').forEach((table, i) => {
            if (i < 5) { // Limit to 5 tables
                const headers = [];
                table.querySelectorAll('th').forEach((th, j) => {
                    if (j < 15) {
                        headers.push(th.textContent?.trim().substring(0, 50) || '');
                    }
                });
                context.tables.push({
                    id: table.id || null,
                    className: table.className || null,
                    headers: headers,
                    rowCount: table.querySelectorAll('tr').length
                });
            }
        });

        // Extract lists
        context.lists = [];
        document.querySelectorAll('ul, ol').forEach((list, i) => {
            if (i < 10 && list.children.length > 0) {
                const items = [];
                Array.from(list.children).slice(0, 5).forEach(li => {
                    items.push(li.textContent?.trim().substring(0, 100) || '');
                });
                context.lists.push({
                    type: list.tagName.toLowerCase(),
                    id: list.id || null,
                    className: list.className || null,
                    itemCount: list.children.length,
                    sampleItems: items
                });
            }
        });

        // Get simplified DOM structure (important elements only)
        context.domStructure = getSimplifiedDOM(document.body, 3); // Limit depth to 3

        // Get selected text if any
        const selection = window.getSelection();
        context.selectedText = selection ? selection.toString().trim() : '';

        // Truncated HTML for direct reference (limit to 50KB)
        context.htmlSnapshot = document.documentElement.outerHTML.substring(0, 50000);

        return context;
    }

    /**
     * Get a simplified DOM structure for understanding page layout.
     * 
     * @param {Element} element - Root element to analyze
     * @param {number} maxDepth - Maximum depth to traverse
     * @param {number} currentDepth - Current depth (for recursion)
     * @returns {Object|null} Simplified DOM node representation
     */
    function getSimplifiedDOM(element, maxDepth, currentDepth = 0) {
        if (!element || currentDepth > maxDepth) return null;
        
        // Skip script, style, and other non-visible elements
        const skipTags = ['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG', 'PATH', 'IFRAME'];
        if (skipTags.includes(element.tagName)) return null;

        // Skip hidden elements
        const style = window.getComputedStyle(element);
        if (style.display === 'none' || style.visibility === 'hidden') return null;

        const node = {
            tag: element.tagName.toLowerCase(),
            id: element.id || null,
            class: element.className ? element.className.toString().split(' ').slice(0, 3).join(' ') : null
        };

        // Add role if present
        const role = element.getAttribute('role');
        if (role) node.role = role;

        // Add data attributes that might be useful
        const dataTestId = element.getAttribute('data-testid') || element.getAttribute('data-test-id');
        if (dataTestId) node.testId = dataTestId;

        // Get children (limit to first 5 significant children)
        const significantChildren = [];
        const significantTags = ['DIV', 'SECTION', 'ARTICLE', 'NAV', 'HEADER', 'FOOTER', 'MAIN', 'ASIDE', 'FORM', 'TABLE', 'UL', 'OL'];
        
        for (const child of element.children) {
            if (significantChildren.length >= 5) break;
            if (significantTags.includes(child.tagName) || child.id || child.getAttribute('role')) {
                const childNode = getSimplifiedDOM(child, maxDepth, currentDepth + 1);
                if (childNode) {
                    significantChildren.push(childNode);
                }
            }
        }

        if (significantChildren.length > 0) {
            node.children = significantChildren;
        }

        return node;
    }

    // ==========================================================================
    // Message Handling
    // ==========================================================================

    /**
     * Handle messages from service worker or other extension components
     */
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        log('Received message:', message.type);

        switch (message.type) {
            case 'EXECUTE_SCRIPT_ACTION':
                // Execute a specific action from a script
                callHandler(message.scriptId, message.handlerName)
                    .then(result => sendResponse({ success: true, result }))
                    .catch(err => sendResponse({ success: false, error: err.message }));
                return true; // Keep channel open for async response

            case 'GET_LOADED_SCRIPTS':
                // Return list of loaded scripts
                const scripts = Array.from(loadedScripts.values()).map(s => ({
                    script_id: s.script.script_id,
                    name: s.script.name,
                    actions: s.script.actions || []
                }));
                sendResponse({ scripts });
                return false;

            case 'TEST_SCRIPT':
                // Execute a script for testing (not saved)
                (async () => {
                    try {
                        const testScript = {
                            script_id: 'test_' + Date.now(),
                            name: 'Test Script',
                            code: message.code,
                            actions: message.actions || []
                        };
                        await executeScript(testScript);
                        sendResponse({ success: true });
                    } catch (err) {
                        sendResponse({ success: false, error: err.message });
                    }
                })();
                return true; // async

            case 'RELOAD_SCRIPTS':
                // Reload scripts for current page
                loadedScripts.clear();
                // Clear sandbox registry too (best-effort)
                sandboxRequest('CLEAR_ALL', {}).catch(() => {});
                loadScriptsForCurrentUrl();
                sendResponse({ success: true });
                return false;

            case 'GET_PAGE_CONTEXT':
                // Return rich page context for script generation
                sendResponse(getPageContext());
                return false;
        }
    });

    // ==========================================================================
    // Initialization
    // ==========================================================================

    /**
     * Initialize the script runner
     */
    function initialize() {
        log('Initializing Script Runner');

        // Load scripts for current URL
        if (document.readyState === 'complete' || document.readyState === 'interactive') {
            loadScriptsForCurrentUrl();
        } else {
            document.addEventListener('DOMContentLoaded', loadScriptsForCurrentUrl);
        }

        // Watch for SPA navigation (URL changes without page reload)
        let lastUrl = window.location.href;
        const urlObserver = new MutationObserver(() => {
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;
                log('URL changed, reloading scripts');
                loadedScripts.clear();
                loadScriptsForCurrentUrl();
            }
        });

        urlObserver.observe(document.body, {
            childList: true,
            subtree: true
        });

        // Also listen for popstate (back/forward navigation)
        window.addEventListener('popstate', () => {
            log('Navigation detected, reloading scripts');
            loadedScripts.clear();
            loadScriptsForCurrentUrl();
        });
    }

    // Support on-demand mode: skip auto-init when __scriptRunnerMode is 'ondemand'
    if (window.__scriptRunnerMode !== 'ondemand') {
        initialize();
    }

    // Expose public API
    window.__scriptRunner = {
        initialize,
        loadedScripts,
        callHandler,
        loadScriptsForCurrentUrl,
        showToast,
        showModal,
        closeModal
    };

})();
