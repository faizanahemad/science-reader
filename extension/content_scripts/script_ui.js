/**
 * Script UI - Floating Toolbar and Command Palette
 * 
 * This content script provides the UI for interacting with custom scripts:
 * 1. Floating toolbar showing available actions for the current page
 * 2. Command palette (Ctrl+Shift+K) for quick action access
 * 3. Button injection into page DOM
 * 
 * @module script_ui
 */

(function() {
    'use strict';

    // Prevent multiple initializations
    if (window.__scriptUIInitialized) {
        return;
    }
    window.__scriptUIInitialized = true;

    // Debug logging
    const DEBUG = true;
    const log = (...args) => DEBUG && console.log('[ScriptUI]', ...args);

    // ==========================================================================
    // Icon Mapping
    // ==========================================================================

    const ICONS = {
        clipboard: '📋',
        copy: '📄',
        download: '⬇️',
        eye: '👁️',
        trash: '🗑️',
        star: '⭐',
        edit: '✏️',
        settings: '⚙️',
        search: '🔍',
        refresh: '🔄',
        play: '▶️',
        pause: '⏸️',
        check: '✓',
        close: '✕',
        plus: '+',
        minus: '−',
        menu: '☰',
        expand: '▼',
        collapse: '▲',
        default: '🔧'
    };

    function getIcon(iconName) {
        return ICONS[iconName] || ICONS.default;
    }

    // ==========================================================================
    // State
    // ==========================================================================

    let toolbar = null;
    let palette = null;
    let currentScripts = [];
    let isToolbarMinimized = false;
    let toolbarPosition = { x: null, y: null };

    // ==========================================================================
    // CSS Injection
    // ==========================================================================

    function injectStyles() {
        if (document.getElementById('ai-script-ui-styles')) return;

        const link = document.createElement('link');
        link.id = 'ai-script-ui-styles';
        link.rel = 'stylesheet';
        link.href = chrome.runtime.getURL('content_scripts/script_ui.css');
        document.head.appendChild(link);
    }

    // ==========================================================================
    // Floating Toolbar
    // ==========================================================================

    /**
     * Create the floating toolbar element
     */
    function createToolbar() {
        if (toolbar) return toolbar;

        toolbar = document.createElement('div');
        toolbar.className = 'ai-script-toolbar';
        toolbar.innerHTML = `
            <div class="ai-script-toolbar-header">
                <div class="ai-script-toolbar-title">
                    <span class="ai-script-toolbar-title-icon">🤖</span>
                    <span>AI Scripts</span>
                </div>
                <div class="ai-script-toolbar-actions">
                    <button class="ai-script-toolbar-btn" data-action="minimize" title="Minimize">
                        ${ICONS.minus}
                    </button>
                    <button class="ai-script-toolbar-btn" data-action="close" title="Close">
                        ${ICONS.close}
                    </button>
                </div>
            </div>
            <div class="ai-script-toolbar-content">
                <div class="ai-script-toolbar-empty">
                    No scripts available for this page
                </div>
            </div>
            <div class="ai-script-toolbar-footer">
                <button class="ai-script-create-btn">
                    <span>${ICONS.plus}</span>
                    <span>Create New Script</span>
                </button>
            </div>
        `;

        // Add event listeners
        setupToolbarEvents(toolbar);

        document.body.appendChild(toolbar);
        
        // Load saved position
        loadToolbarPosition();

        return toolbar;
    }

    /**
     * Set up toolbar event listeners
     */
    function setupToolbarEvents(toolbar) {
        // Header actions
        toolbar.querySelector('[data-action="minimize"]').addEventListener('click', toggleToolbarMinimize);
        toolbar.querySelector('[data-action="close"]').addEventListener('click', hideToolbar);

        // Create button
        toolbar.querySelector('.ai-script-create-btn').addEventListener('click', openScriptEditor);

        // Dragging
        const header = toolbar.querySelector('.ai-script-toolbar-header');
        let isDragging = false;
        let dragStart = { x: 0, y: 0 };

        header.addEventListener('mousedown', (e) => {
            if (e.target.closest('.ai-script-toolbar-btn')) return;
            isDragging = true;
            dragStart = { x: e.clientX - toolbar.offsetLeft, y: e.clientY - toolbar.offsetTop };
            toolbar.style.transition = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const x = Math.max(0, Math.min(window.innerWidth - toolbar.offsetWidth, e.clientX - dragStart.x));
            const y = Math.max(0, Math.min(window.innerHeight - toolbar.offsetHeight, e.clientY - dragStart.y));
            toolbar.style.left = x + 'px';
            toolbar.style.top = y + 'px';
            toolbar.style.right = 'auto';
            toolbar.style.bottom = 'auto';
        });

        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                toolbar.style.transition = '';
                saveToolbarPosition();
            }
        });
    }

    /**
     * Show the toolbar
     */
    function showToolbar() {
        injectStyles();
        const tb = createToolbar();
        updateToolbarContent();
        requestAnimationFrame(() => {
            tb.classList.add('show');
        });
    }

    /**
     * Hide the toolbar
     */
    function hideToolbar() {
        if (toolbar) {
            toolbar.classList.remove('show');
        }
    }

    /**
     * Toggle toolbar minimize state
     */
    function toggleToolbarMinimize() {
        isToolbarMinimized = !isToolbarMinimized;
        if (toolbar) {
            toolbar.classList.toggle('minimized', isToolbarMinimized);
            const btn = toolbar.querySelector('[data-action="minimize"]');
            btn.innerHTML = isToolbarMinimized ? ICONS.expand : ICONS.minus;
        }
    }

    /**
     * Update toolbar content with current scripts
     */
    function updateToolbarContent() {
        if (!toolbar) return;

        const content = toolbar.querySelector('.ai-script-toolbar-content');
        
        if (currentScripts.length === 0) {
            content.innerHTML = `
                <div class="ai-script-toolbar-empty">
                    No scripts available for this page
                </div>
            `;
            return;
        }

        // Group actions by script
        let html = '';
        currentScripts.forEach(script => {
            const actions = script.actions || [];
            if (actions.length === 0) return;

            html += `<div class="ai-script-group">`;
            html += `<div class="ai-script-group-header">${escapeHtml(script.name)}</div>`;
            
            actions.forEach(action => {
                if (action.exposure !== 'floating' && action.exposure !== undefined) return;
                
                html += `
                    <button class="ai-script-action" 
                            data-script-id="${script.script_id}" 
                            data-handler="${action.handler}">
                        <span class="ai-script-action-icon">${getIcon(action.icon)}</span>
                        <span class="ai-script-action-info">
                            <span class="ai-script-action-name">${escapeHtml(action.name)}</span>
                        </span>
                    </button>
                `;
            });
            
            html += `</div>`;
        });

        content.innerHTML = html || `
            <div class="ai-script-toolbar-empty">
                No floating actions configured
            </div>
        `;

        // Add click handlers
        content.querySelectorAll('.ai-script-action').forEach(btn => {
            btn.addEventListener('click', () => {
                const scriptId = btn.dataset.scriptId;
                const handler = btn.dataset.handler;
                executeAction(scriptId, handler);
            });
        });
    }

    /**
     * Save toolbar position
     */
    function saveToolbarPosition() {
        if (!toolbar) return;
        const pos = {
            left: toolbar.style.left,
            top: toolbar.style.top
        };
        chrome.storage.local.set({ 'ai_script_toolbar_position': pos });
    }

    /**
     * Load toolbar position
     */
    function loadToolbarPosition() {
        chrome.storage.local.get(['ai_script_toolbar_position'], (result) => {
            if (result.ai_script_toolbar_position && toolbar) {
                const pos = result.ai_script_toolbar_position;
                if (pos.left) toolbar.style.left = pos.left;
                if (pos.top) toolbar.style.top = pos.top;
                if (pos.left || pos.top) {
                    toolbar.style.right = 'auto';
                    toolbar.style.bottom = 'auto';
                }
            }
        });
    }

    // ==========================================================================
    // Command Palette
    // ==========================================================================

    /**
     * Create the command palette element
     */
    function createPalette() {
        if (palette) return palette;

        palette = document.createElement('div');
        palette.className = 'ai-script-palette-overlay';
        palette.innerHTML = `
            <div class="ai-script-palette">
                <div class="ai-script-palette-search">
                    <span class="ai-script-palette-search-icon">${ICONS.search}</span>
                    <input type="text" class="ai-script-palette-input" placeholder="Search actions...">
                </div>
                <div class="ai-script-palette-results"></div>
                <div class="ai-script-palette-footer">
                    <div class="ai-script-palette-hint">
                        <span class="ai-script-palette-hint-item">
                            <span class="ai-script-palette-hint-key">↑↓</span>
                            <span>Navigate</span>
                        </span>
                        <span class="ai-script-palette-hint-item">
                            <span class="ai-script-palette-hint-key">Enter</span>
                            <span>Select</span>
                        </span>
                        <span class="ai-script-palette-hint-item">
                            <span class="ai-script-palette-hint-key">Esc</span>
                            <span>Close</span>
                        </span>
                    </div>
                </div>
            </div>
        `;

        // Close on overlay click
        palette.addEventListener('click', (e) => {
            if (e.target === palette) closePalette();
        });

        // Search input
        const input = palette.querySelector('.ai-script-palette-input');
        input.addEventListener('input', (e) => {
            updatePaletteResults(e.target.value);
        });

        // Keyboard navigation
        input.addEventListener('keydown', handlePaletteKeydown);

        document.body.appendChild(palette);
        return palette;
    }

    /**
     * Show the command palette
     */
    function showPalette() {
        injectStyles();
        const p = createPalette();
        updatePaletteResults('');
        
        requestAnimationFrame(() => {
            p.classList.add('show');
            p.querySelector('.ai-script-palette-input').focus();
        });
    }

    /**
     * Close the command palette
     */
    function closePalette() {
        if (palette) {
            palette.classList.remove('show');
            palette.querySelector('.ai-script-palette-input').value = '';
        }
    }

    /**
     * Update palette results based on search query
     */
    function updatePaletteResults(query) {
        if (!palette) return;

        const results = palette.querySelector('.ai-script-palette-results');
        query = query.toLowerCase().trim();

        // Collect all actions
        let actions = [];
        currentScripts.forEach(script => {
            (script.actions || []).forEach(action => {
                actions.push({
                    ...action,
                    scriptId: script.script_id,
                    scriptName: script.name
                });
            });
        });

        // Filter by query
        if (query) {
            actions = actions.filter(a => 
                a.name.toLowerCase().includes(query) ||
                (a.description || '').toLowerCase().includes(query) ||
                a.scriptName.toLowerCase().includes(query)
            );
        }

        // Build HTML
        let html = '';

        if (actions.length > 0) {
            html += `<div class="ai-script-palette-section">`;
            html += `<div class="ai-script-palette-section-header">Script Actions</div>`;
            
            actions.forEach((action, idx) => {
                html += `
                    <button class="ai-script-palette-item ${idx === 0 ? 'selected' : ''}"
                            data-script-id="${action.scriptId}"
                            data-handler="${action.handler}"
                            data-index="${idx}">
                        <span class="ai-script-palette-item-icon">${getIcon(action.icon)}</span>
                        <span class="ai-script-palette-item-info">
                            <span class="ai-script-palette-item-name">${escapeHtml(action.name)}</span>
                            <span class="ai-script-palette-item-desc">${escapeHtml(action.scriptName)}</span>
                        </span>
                    </button>
                `;
            });
            
            html += `</div>`;
        }

        // System commands
        html += `<div class="ai-script-palette-divider"></div>`;
        html += `<div class="ai-script-palette-section">`;
        html += `<div class="ai-script-palette-section-header">System</div>`;
        
        const systemCommands = [
            { id: 'create', name: 'Create New Script', icon: 'plus', desc: 'Open script editor' },
            { id: 'edit', name: 'Edit Scripts', icon: 'edit', desc: 'Manage your scripts' },
            { id: 'reload', name: 'Reload Scripts', icon: 'refresh', desc: 'Refresh scripts for this page' }
        ];

        const startIdx = actions.length;
        systemCommands.forEach((cmd, idx) => {
            if (query && !cmd.name.toLowerCase().includes(query)) return;
            
            html += `
                <button class="ai-script-palette-item system ${!query && actions.length === 0 && idx === 0 ? 'selected' : ''}"
                        data-system="${cmd.id}"
                        data-index="${startIdx + idx}">
                    <span class="ai-script-palette-item-icon">${getIcon(cmd.icon)}</span>
                    <span class="ai-script-palette-item-info">
                        <span class="ai-script-palette-item-name">${cmd.name}</span>
                        <span class="ai-script-palette-item-desc">${cmd.desc}</span>
                    </span>
                </button>
            `;
        });
        
        html += `</div>`;

        if (actions.length === 0 && !html.includes('ai-script-palette-item')) {
            html = `<div class="ai-script-palette-empty">No matching actions found</div>`;
        }

        results.innerHTML = html;

        // Add click handlers
        results.querySelectorAll('.ai-script-palette-item').forEach(item => {
            item.addEventListener('click', () => {
                if (item.dataset.system) {
                    handleSystemCommand(item.dataset.system);
                } else {
                    executeAction(item.dataset.scriptId, item.dataset.handler);
                }
                closePalette();
            });
        });
    }

    /**
     * Handle keyboard navigation in palette
     */
    function handlePaletteKeydown(e) {
        const items = palette.querySelectorAll('.ai-script-palette-item');
        const selected = palette.querySelector('.ai-script-palette-item.selected');
        let selectedIdx = selected ? parseInt(selected.dataset.index) : -1;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                selectedIdx = Math.min(selectedIdx + 1, items.length - 1);
                break;
            case 'ArrowUp':
                e.preventDefault();
                selectedIdx = Math.max(selectedIdx - 1, 0);
                break;
            case 'Enter':
                e.preventDefault();
                if (selected) selected.click();
                return;
            case 'Escape':
                e.preventDefault();
                closePalette();
                return;
            default:
                return;
        }

        // Update selection
        items.forEach((item, idx) => {
            item.classList.toggle('selected', idx === selectedIdx);
        });

        // Scroll into view
        const newSelected = palette.querySelector('.ai-script-palette-item.selected');
        if (newSelected) {
            newSelected.scrollIntoView({ block: 'nearest' });
        }
    }

    /**
     * Handle system commands
     */
    function handleSystemCommand(cmd) {
        switch (cmd) {
            case 'create':
                openScriptEditor();
                break;
            case 'edit':
                openScriptEditor(); // TODO: Open with list view
                break;
            case 'reload':
                reloadScripts();
                break;
        }
    }

    // ==========================================================================
    // Injected Buttons
    // ==========================================================================

    /**
     * Inject buttons into the page for actions with exposure: "inject"
     */
    function injectButtons() {
        // Remove existing injected buttons
        document.querySelectorAll('.ai-script-injected-btn').forEach(btn => btn.remove());

        currentScripts.forEach(script => {
            (script.actions || []).forEach(action => {
                if (action.exposure !== 'inject' || !action.inject_selector) return;

                const target = document.querySelector(action.inject_selector);
                if (!target) return;

                const btn = document.createElement('button');
                btn.className = 'ai-script-injected-btn';
                btn.innerHTML = `${getIcon(action.icon)} ${escapeHtml(action.name)}`;
                btn.title = action.description || action.name;
                btn.style.cssText = `
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 8px 12px;
                    background: var(--ai-script-primary, #3b82f6);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 13px;
                    cursor: pointer;
                    margin: 4px;
                `;

                btn.addEventListener('click', () => {
                    executeAction(script.script_id, action.handler);
                });

                const position = action.inject_position || 'after';
                if (position === 'before') {
                    target.parentNode.insertBefore(btn, target);
                } else if (position === 'after') {
                    target.parentNode.insertBefore(btn, target.nextSibling);
                } else if (position === 'inside') {
                    target.appendChild(btn);
                }
            });
        });
    }

    // ==========================================================================
    // Action Execution
    // ==========================================================================

    /**
     * Execute a script action
     */
    async function executeAction(scriptId, handlerName) {
        log(`Executing action: ${handlerName} from script ${scriptId}`);
        
        try {
            // Call the handler through script_runner
            if (window.__scriptRunner) {
                await window.__scriptRunner.callHandler(scriptId, handlerName);
            } else {
                // Fallback to message
                chrome.runtime.sendMessage({
                    type: 'EXECUTE_SCRIPT_ACTION',
                    scriptId,
                    handlerName
                });
            }
        } catch (err) {
            console.error('[ScriptUI] Action execution failed:', err);
            if (window.__scriptRunner) {
                window.__scriptRunner.showToast(`Error: ${err.message}`, 'error');
            }
        }
    }

    /**
     * Open the script editor popup
     */
    function openScriptEditor() {
        chrome.runtime.sendMessage({ type: 'OPEN_SCRIPT_EDITOR' });
    }

    /**
     * Reload scripts for current page
     */
    function reloadScripts() {
        chrome.runtime.sendMessage({ type: 'RELOAD_SCRIPTS' });
    }

    // ==========================================================================
    // Event Listeners
    // ==========================================================================

    /**
     * Listen for scripts loaded event from script_runner
     */
    window.addEventListener('ai-scripts-loaded', (e) => {
        log('Scripts loaded:', e.detail.scripts.length);
        currentScripts = e.detail.scripts;
        
        if (currentScripts.length > 0) {
            showToolbar();
            injectButtons();
        }
    });

    /**
     * Keyboard shortcut for command palette (Ctrl+Shift+K)
     */
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.shiftKey && e.key === 'K') {
            e.preventDefault();
            
            if (palette && palette.classList.contains('show')) {
                closePalette();
            } else {
                showPalette();
            }
        }
        
        // Escape to close palette
        if (e.key === 'Escape' && palette && palette.classList.contains('show')) {
            closePalette();
        }
    });

    /**
     * Message listener
     */
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        switch (message.type) {
            case 'SHOW_SCRIPT_TOOLBAR':
                showToolbar();
                sendResponse({ success: true });
                break;
            case 'HIDE_SCRIPT_TOOLBAR':
                hideToolbar();
                sendResponse({ success: true });
                break;
            case 'SHOW_COMMAND_PALETTE':
                showPalette();
                sendResponse({ success: true });
                break;
            case 'UPDATE_SCRIPTS':
                currentScripts = message.scripts || [];
                updateToolbarContent();
                injectButtons();
                sendResponse({ success: true });
                break;
        }
    });

    // ==========================================================================
    // Utilities
    // ==========================================================================

    /**
     * Escape HTML
     */
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    // ==========================================================================
    // MutationObserver for SPA
    // ==========================================================================

    // Watch for DOM changes to re-inject buttons
    let debounceTimer = null;
    const observer = new MutationObserver(() => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            injectButtons();
        }, 500);
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    // ==========================================================================
    // Initialization
    // ==========================================================================

    log('Script UI initialized');

})();

