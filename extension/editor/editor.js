/**
 * Script Editor - Main JavaScript
 * 
 * Handles the script editor popup functionality:
 * - CodeMirror integration
 * - Action builder
 * - Script CRUD operations
 * - Test execution
 */

(function() {
    'use strict';

    // ==========================================================================
    // Configuration
    // ==========================================================================

    const API_BASE = 'http://localhost:5001';
    
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
        default: '🔧'
    };

    // ==========================================================================
    // State
    // ==========================================================================

    let editor = null;
    let currentScript = null;
    let actions = [];
    let editingActionIndex = -1;
    let authToken = null;

    // ==========================================================================
    // Initialization
    // ==========================================================================

    document.addEventListener('DOMContentLoaded', async () => {
        // Get auth token
        authToken = await getAuthToken();
        if (!authToken) {
            showError('Not authenticated. Please log in first.');
            return;
        }

        // Initialize CodeMirror
        initCodeEditor();

        // Set up event listeners
        setupEventListeners();

        // Check if we have pending script from AI generation
        const pendingScriptData = await getPendingScript();
        if (pendingScriptData) {
            loadPendingScript(pendingScriptData);
        } else {
            // Check if editing existing script via URL param
            const params = new URLSearchParams(window.location.search);
            const scriptId = params.get('scriptId');
            if (scriptId) {
                loadScript(scriptId);
            } else {
                // New script - set default code
                setDefaultCode();
            }
        }
    });

    /**
     * Get auth token from chrome.storage
     */
    async function getAuthToken() {
        return new Promise((resolve) => {
            chrome.storage.local.get(['auth_token'], (result) => {
                resolve(result.auth_token || null);
            });
        });
    }

    /**
     * Check for pending script from AI generation
     * @returns {Promise<Object|null>} Script data or null
     */
    async function getPendingScript() {
        return new Promise((resolve) => {
            chrome.storage.local.get(['_pending_script_edit'], (result) => {
                const data = result._pending_script_edit;
                
                // Check if data exists and is recent (within 5 minutes)
                if (data && data.timestamp && (Date.now() - data.timestamp < 300000)) {
                    // Clear the pending data
                    chrome.storage.local.remove('_pending_script_edit');
                    resolve(data.script);
                } else {
                    // Clear stale data if any
                    if (data) {
                        chrome.storage.local.remove('_pending_script_edit');
                    }
                    resolve(null);
                }
            });
        });
    }

    /**
     * Load a pending script from AI generation into the editor
     * @param {Object} script - Script data from AI generation
     */
    function loadPendingScript(script) {
        console.log('[Editor] Loading pending script:', script);
        
        // Populate form - this is a new script (not saved yet)
        document.getElementById('scriptName').value = script.name || '';
        document.getElementById('scriptDescription').value = script.description || '';
        document.getElementById('scriptType').value = script.script_type || 'functional';
        document.querySelector(`input[name="matchType"][value="glob"]`).checked = true;

        // Patterns
        const patterns = script.match_patterns || [];
        const patternsList = document.getElementById('patternsList');
        patternsList.innerHTML = '';
        patterns.forEach(pattern => {
            addPatternItem(pattern);
        });
        if (patterns.length === 0) {
            addPatternItem('');
        }

        // Code
        editor.setValue(script.code || '');

        // Actions
        actions = script.actions || [];
        renderActions();

        // Update UI to indicate this is a new script from AI
        document.getElementById('scriptId').textContent = 'New script from AI';
        document.getElementById('lastSaved').textContent = 'Not saved yet';
        
        showSuccess('Script loaded from AI - Review and save when ready!');
    }

    /**
     * Initialize CodeMirror editor
     */
    function initCodeEditor() {
        const container = document.getElementById('codeEditor');
        
        editor = CodeMirror(container, {
            mode: 'javascript',
            theme: 'dracula',
            lineNumbers: true,
            matchBrackets: true,
            autoCloseBrackets: true,
            tabSize: 4,
            indentWithTabs: false,
            lineWrapping: true,
            placeholder: '// Your script code here...'
        });

        // Validate on change
        editor.on('change', () => {
            validateCode();
        });
    }

    /**
     * Set default code template
     */
    function setDefaultCode() {
        const template = `// Define your handler functions
const handlers = {
    // Example action handler
    exampleAction() {
        const text = aiAssistant.dom.getText('h1');
        aiAssistant.clipboard.copy(text);
        aiAssistant.ui.showToast('Copied: ' + text, 'success');
    }
};

// Export handlers (required)
window.__scriptHandlers = handlers;`;

        editor.setValue(template);
    }

    /**
     * Set up all event listeners
     */
    function setupEventListeners() {
        // Header buttons
        document.getElementById('saveBtn').addEventListener('click', saveScript);
        document.getElementById('testBtn').addEventListener('click', testScript);
        document.getElementById('askAiBtn').addEventListener('click', openAiAssistant);

        // Pattern management
        document.getElementById('addPatternBtn').addEventListener('click', addPattern);
        document.getElementById('patternsList').addEventListener('click', handlePatternClick);

        // Actions
        document.getElementById('addActionBtn').addEventListener('click', () => openActionModal());
        document.getElementById('actionsList').addEventListener('click', handleActionClick);

        // Action modal
        document.getElementById('closeActionModal').addEventListener('click', closeActionModal);
        document.getElementById('cancelActionBtn').addEventListener('click', closeActionModal);
        document.getElementById('saveActionBtn').addEventListener('click', saveAction);
        document.getElementById('actionExposure').addEventListener('change', handleExposureChange);

        // Test modal
        document.getElementById('closeTestModal').addEventListener('click', closeTestModal);
        document.getElementById('closeTestBtn').addEventListener('click', closeTestModal);

        // Click outside modal to close
        document.getElementById('actionModal').addEventListener('click', (e) => {
            if (e.target.id === 'actionModal') closeActionModal();
        });
        document.getElementById('testModal').addEventListener('click', (e) => {
            if (e.target.id === 'testModal') closeTestModal();
        });
    }

    // ==========================================================================
    // Script CRUD
    // ==========================================================================

    /**
     * Load an existing script for editing
     */
    async function loadScript(scriptId) {
        try {
            const response = await fetch(`${API_BASE}/ext/scripts/${scriptId}`, {
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            });

            if (!response.ok) {
                throw new Error('Failed to load script');
            }

            const data = await response.json();
            currentScript = data.script;

            // Populate form
            document.getElementById('scriptName').value = currentScript.name || '';
            document.getElementById('scriptDescription').value = currentScript.description || '';
            document.getElementById('scriptType').value = currentScript.script_type || 'functional';
            document.querySelector(`input[name="matchType"][value="${currentScript.match_type || 'glob'}"]`).checked = true;

            // Patterns
            const patterns = currentScript.match_patterns || [];
            const patternsList = document.getElementById('patternsList');
            patternsList.innerHTML = '';
            patterns.forEach(pattern => {
                addPatternItem(pattern);
            });
            if (patterns.length === 0) {
                addPatternItem('');
            }

            // Code
            editor.setValue(currentScript.code || '');

            // Actions
            actions = currentScript.actions || [];
            renderActions();

            // Update UI
            document.getElementById('scriptId').textContent = `ID: ${scriptId}`;
            document.getElementById('lastSaved').textContent = `Last saved: ${formatDate(currentScript.updated_at)}`;

        } catch (err) {
            console.error('Failed to load script:', err);
            showError('Failed to load script: ' + err.message);
        }
    }

    /**
     * Save the script
     */
    async function saveScript() {
        // Validate
        const name = document.getElementById('scriptName').value.trim();
        if (!name) {
            showError('Script name is required');
            return;
        }

        const patterns = getPatterns();
        if (patterns.length === 0) {
            showError('At least one URL pattern is required');
            return;
        }

        const code = editor.getValue().trim();
        if (!code) {
            showError('Script code is required');
            return;
        }

        // Build script data
        const scriptData = {
            name: name,
            description: document.getElementById('scriptDescription').value.trim(),
            script_type: document.getElementById('scriptType').value,
            match_patterns: patterns,
            match_type: document.querySelector('input[name="matchType"]:checked').value,
            code: code,
            actions: actions
        };

        try {
            let response;
            if (currentScript) {
                // Update existing
                response = await fetch(`${API_BASE}/ext/scripts/${currentScript.script_id}`, {
                    method: 'PUT',
                    headers: {
                        'Authorization': `Bearer ${authToken}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(scriptData)
                });
            } else {
                // Create new
                response = await fetch(`${API_BASE}/ext/scripts`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${authToken}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(scriptData)
                });
            }

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Save failed');
            }

            const data = await response.json();
            currentScript = data.script;

            // Update UI
            document.getElementById('scriptId').textContent = `ID: ${currentScript.script_id}`;
            document.getElementById('lastSaved').textContent = `Last saved: ${formatDate(new Date().toISOString())}`;

            showSuccess('Script saved successfully!');

            // Notify other parts of extension to reload scripts
            chrome.runtime.sendMessage({ type: 'SCRIPTS_UPDATED' });

        } catch (err) {
            console.error('Failed to save script:', err);
            showError('Failed to save: ' + err.message);
        }
    }

    /**
     * Test the script on the active tab
     */
    async function testScript() {
        const code = editor.getValue();
        
        // Show test modal
        const modal = document.getElementById('testModal');
        const results = document.getElementById('testResults');
        results.innerHTML = `
            <div class="test-status">
                <span class="test-icon">⏳</span>
                <span class="test-text">Running test...</span>
            </div>
        `;
        modal.classList.remove('hidden');

        try {
            // Get active tab
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (!tab) {
                throw new Error('No active tab');
            }

            // Send test message to content script
            const response = await chrome.tabs.sendMessage(tab.id, {
                type: 'TEST_SCRIPT',
                code: code,
                actions: actions
            });

            if (response.success) {
                results.innerHTML = `
                    <div class="test-status success">
                        <span class="test-icon">✓</span>
                        <span class="test-text">Script executed successfully!</span>
                    </div>
                    <div class="test-message">Script loaded and handlers registered. Check the page to see if it works.</div>
                `;
            } else {
                throw new Error(response.error || 'Test failed');
            }

        } catch (err) {
            results.innerHTML = `
                <div class="test-status error">
                    <span class="test-icon">✕</span>
                    <span class="test-text">Test failed</span>
                </div>
                <div class="test-message">${escapeHtml(err.message)}</div>
            `;
        }
    }

    /**
     * Open AI assistant with script context
     */
    function openAiAssistant() {
        // Open sidepanel with current script context
        chrome.runtime.sendMessage({
            type: 'OPEN_SIDEPANEL_WITH_CONTEXT',
            context: {
                mode: 'script_edit',
                code: editor.getValue(),
                actions: actions,
                scriptName: document.getElementById('scriptName').value
            }
        });
    }

    // ==========================================================================
    // Pattern Management
    // ==========================================================================

    function addPattern() {
        addPatternItem('');
    }

    function addPatternItem(value) {
        const patternsList = document.getElementById('patternsList');
        const item = document.createElement('div');
        item.className = 'pattern-item';
        item.innerHTML = `
            <input type="text" class="pattern-input" placeholder="*://example.com/*" value="${escapeHtml(value)}">
            <button type="button" class="btn-icon remove-pattern" title="Remove">✕</button>
        `;
        patternsList.appendChild(item);
    }

    function handlePatternClick(e) {
        if (e.target.classList.contains('remove-pattern')) {
            const item = e.target.closest('.pattern-item');
            const patternsList = document.getElementById('patternsList');
            
            // Don't remove the last pattern
            if (patternsList.children.length > 1) {
                item.remove();
            }
        }
    }

    function getPatterns() {
        const inputs = document.querySelectorAll('.pattern-input');
        const patterns = [];
        inputs.forEach(input => {
            const value = input.value.trim();
            if (value) {
                patterns.push(value);
            }
        });
        return patterns;
    }

    // ==========================================================================
    // Action Management
    // ==========================================================================

    function renderActions() {
        const actionsList = document.getElementById('actionsList');
        const emptyState = document.getElementById('actionsEmpty');

        if (actions.length === 0) {
            actionsList.innerHTML = '';
            emptyState.classList.remove('hidden');
            return;
        }

        emptyState.classList.add('hidden');
        actionsList.innerHTML = actions.map((action, index) => `
            <div class="action-item" data-index="${index}">
                <span class="action-icon">${ICONS[action.icon] || ICONS.default}</span>
                <div class="action-info">
                    <div class="action-name">${escapeHtml(action.name)}</div>
                    <div class="action-handler">${escapeHtml(action.handler)}</div>
                </div>
                <span class="action-badge">${action.exposure || 'floating'}</span>
                <div class="action-actions">
                    <button class="btn-icon edit-action" title="Edit">✏️</button>
                    <button class="btn-icon btn-danger delete-action" title="Delete">🗑️</button>
                </div>
            </div>
        `).join('');
    }

    function handleActionClick(e) {
        const actionItem = e.target.closest('.action-item');
        if (!actionItem) return;

        const index = parseInt(actionItem.dataset.index);

        if (e.target.classList.contains('edit-action') || e.target.closest('.edit-action')) {
            openActionModal(index);
        } else if (e.target.classList.contains('delete-action') || e.target.closest('.delete-action')) {
            deleteAction(index);
        }
    }

    function openActionModal(index = -1) {
        editingActionIndex = index;
        const modal = document.getElementById('actionModal');
        const title = document.getElementById('actionModalTitle');

        // Reset form
        document.getElementById('actionName').value = '';
        document.getElementById('actionHandler').value = '';
        document.getElementById('actionIcon').value = 'clipboard';
        document.getElementById('actionExposure').value = 'floating';
        document.getElementById('actionDescription').value = '';
        document.getElementById('actionPagePattern').value = '';
        document.getElementById('injectSelector').value = '';
        document.getElementById('injectPosition').value = 'after';
        document.getElementById('injectOptions').classList.add('hidden');

        if (index >= 0 && actions[index]) {
            // Editing existing action
            title.textContent = 'Edit Action';
            const action = actions[index];
            document.getElementById('actionName').value = action.name || '';
            document.getElementById('actionHandler').value = action.handler || '';
            document.getElementById('actionIcon').value = action.icon || 'clipboard';
            document.getElementById('actionExposure').value = action.exposure || 'floating';
            document.getElementById('actionDescription').value = action.description || '';
            document.getElementById('actionPagePattern').value = action.page_pattern || '';
            document.getElementById('injectSelector').value = action.inject_selector || '';
            document.getElementById('injectPosition').value = action.inject_position || 'after';

            if (action.exposure === 'inject') {
                document.getElementById('injectOptions').classList.remove('hidden');
            }
        } else {
            title.textContent = 'Add Action';
        }

        modal.classList.remove('hidden');
        document.getElementById('actionName').focus();
    }

    function closeActionModal() {
        document.getElementById('actionModal').classList.add('hidden');
        editingActionIndex = -1;
    }

    function handleExposureChange(e) {
        const injectOptions = document.getElementById('injectOptions');
        if (e.target.value === 'inject') {
            injectOptions.classList.remove('hidden');
        } else {
            injectOptions.classList.add('hidden');
        }
    }

    /**
     * Save the current action from the modal
     */
    function saveAction() {
        const name = document.getElementById('actionName').value.trim();
        const handler = document.getElementById('actionHandler').value.trim();

        if (!name) {
            showError('Action name is required');
            return;
        }

        if (!handler) {
            showError('Handler function name is required');
            return;
        }

        const exposure = document.getElementById('actionExposure').value;
        
        // Validate inject options
        if (exposure === 'inject') {
            const selector = document.getElementById('injectSelector').value.trim();
            if (!selector) {
                showError('CSS selector is required for inject exposure');
                return;
            }
        }

        // Build action object
        const action = {
            id: editingActionIndex >= 0 ? actions[editingActionIndex].id : generateId(),
            name: name,
            handler: handler,
            icon: document.getElementById('actionIcon').value,
            exposure: exposure,
            description: document.getElementById('actionDescription').value.trim() || null,
            page_pattern: document.getElementById('actionPagePattern').value.trim() || null,
            inject_selector: exposure === 'inject' ? document.getElementById('injectSelector').value.trim() : null,
            inject_position: exposure === 'inject' ? document.getElementById('injectPosition').value : null
        };

        if (editingActionIndex >= 0) {
            // Update existing
            actions[editingActionIndex] = action;
        } else {
            // Add new
            actions.push(action);
        }

        renderActions();
        closeActionModal();
    }

    /**
     * Delete an action
     */
    function deleteAction(index) {
        if (confirm('Are you sure you want to delete this action?')) {
            actions.splice(index, 1);
            renderActions();
        }
    }

    /**
     * Close the test modal
     */
    function closeTestModal() {
        document.getElementById('testModal').classList.add('hidden');
    }

    // ==========================================================================
    // Code Validation
    // ==========================================================================

    /**
     * Validate the code in the editor
     */
    function validateCode() {
        const code = editor.getValue();
        const statusEl = document.getElementById('codeStatus');
        
        if (!code.trim()) {
            statusEl.innerHTML = `
                <span class="status-icon">⚠</span>
                <span class="status-text">Empty</span>
            `;
            statusEl.classList.remove('error');
            return;
        }

        // Basic validation: check for balanced braces
        const result = validateBraces(code);
        
        if (result.valid) {
            // Check for handler export
            if (!code.includes('window.__scriptHandlers')) {
                statusEl.innerHTML = `
                    <span class="status-icon">⚠</span>
                    <span class="status-text">Missing window.__scriptHandlers</span>
                `;
                statusEl.classList.add('error');
                return;
            }
            
            statusEl.innerHTML = `
                <span class="status-icon">✓</span>
                <span class="status-text">Valid</span>
            `;
            statusEl.classList.remove('error');
        } else {
            statusEl.innerHTML = `
                <span class="status-icon">✕</span>
                <span class="status-text">${escapeHtml(result.error)}</span>
            `;
            statusEl.classList.add('error');
        }
    }

    /**
     * Check for balanced braces/brackets/parens
     * 
     * @param {string} code - The code to validate
     * @returns {Object} - { valid: boolean, error?: string }
     */
    function validateBraces(code) {
        const stack = [];
        const pairs = { ')': '(', ']': '[', '}': '{' };
        
        let inString = false;
        let stringChar = null;
        let escaped = false;
        let inSingleLineComment = false;
        let inMultiLineComment = false;
        
        for (let i = 0; i < code.length; i++) {
            const char = code[i];
            const nextChar = code[i + 1];
            
            // Handle newlines - end single line comments
            if (char === '\n') {
                inSingleLineComment = false;
                continue;
            }
            
            // Skip if in comment
            if (inSingleLineComment) {
                continue;
            }
            
            // Check for multi-line comment end
            if (inMultiLineComment) {
                if (char === '*' && nextChar === '/') {
                    inMultiLineComment = false;
                    i++; // Skip next char
                }
                continue;
            }
            
            // Check for comment start (only if not in string)
            if (!inString) {
                if (char === '/' && nextChar === '/') {
                    inSingleLineComment = true;
                    i++; // Skip next char
                    continue;
                }
                if (char === '/' && nextChar === '*') {
                    inMultiLineComment = true;
                    i++; // Skip next char
                    continue;
                }
            }
            
            // Handle escape sequences
            if (escaped) {
                escaped = false;
                continue;
            }
            
            if (char === '\\' && inString) {
                escaped = true;
                continue;
            }
            
            // Handle strings
            if (inString) {
                if (char === stringChar) {
                    inString = false;
                }
                continue;
            }
            
            if (char === '"' || char === "'" || char === '`') {
                inString = true;
                stringChar = char;
                continue;
            }
            
            // Handle braces/brackets/parens
            if (char === '(' || char === '[' || char === '{') {
                stack.push(char);
            } else if (char === ')' || char === ']' || char === '}') {
                if (stack.length === 0 || stack[stack.length - 1] !== pairs[char]) {
                    return { valid: false, error: `Unmatched ${char} at position ${i}` };
                }
                stack.pop();
            }
        }
        
        if (stack.length > 0) {
            return { valid: false, error: `Unclosed ${stack[stack.length - 1]}` };
        }
        
        if (inString) {
            return { valid: false, error: 'Unclosed string' };
        }
        
        if (inMultiLineComment) {
            return { valid: false, error: 'Unclosed multi-line comment' };
        }
        
        return { valid: true };
    }

    // ==========================================================================
    // Utility Functions
    // ==========================================================================

    /**
     * Generate a unique ID for actions
     * 
     * @returns {string} - Unique ID
     */
    function generateId() {
        return 'action_' + Date.now().toString(36) + Math.random().toString(36).substr(2, 5);
    }

    /**
     * Escape HTML to prevent XSS
     * 
     * @param {string} str - String to escape
     * @returns {string} - Escaped string
     */
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    /**
     * Format a date string for display
     * 
     * @param {string} dateStr - ISO date string
     * @returns {string} - Formatted date string
     */
    function formatDate(dateStr) {
        if (!dateStr) return 'Never';
        const date = new Date(dateStr);
        return date.toLocaleString();
    }

    /**
     * Show an error toast/notification
     * 
     * @param {string} message - Error message to display
     */
    function showError(message) {
        showNotification(message, 'error');
    }

    /**
     * Show a success toast/notification
     * 
     * @param {string} message - Success message to display
     */
    function showSuccess(message) {
        showNotification(message, 'success');
    }

    /**
     * Show a notification toast
     * 
     * @param {string} message - Message to display
     * @param {string} type - Type of notification: 'success', 'error', or 'info'
     */
    function showNotification(message, type = 'info') {
        // Remove existing notification
        const existing = document.querySelector('.editor-notification');
        if (existing) {
            existing.remove();
        }

        // Create notification element
        const notification = document.createElement('div');
        notification.className = `editor-notification notification-${type}`;
        notification.innerHTML = `
            <span class="notification-icon">${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span>
            <span class="notification-message">${escapeHtml(message)}</span>
            <button class="notification-close">✕</button>
        `;

        // Add styles if not present
        if (!document.getElementById('notification-styles')) {
            const style = document.createElement('style');
            style.id = 'notification-styles';
            style.textContent = `
                .editor-notification {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 12px 16px;
                    background: var(--editor-bg-tertiary, #0f3460);
                    border-radius: 8px;
                    color: var(--editor-text, #e8e8e8);
                    font-size: 14px;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
                    z-index: 10000;
                    animation: slideIn 0.3s ease;
                }
                .notification-success {
                    border-left: 4px solid #10b981;
                }
                .notification-error {
                    border-left: 4px solid #ef4444;
                }
                .notification-info {
                    border-left: 4px solid #3b82f6;
                }
                .notification-icon {
                    font-size: 18px;
                }
                .notification-success .notification-icon { color: #10b981; }
                .notification-error .notification-icon { color: #ef4444; }
                .notification-info .notification-icon { color: #3b82f6; }
                .notification-close {
                    background: none;
                    border: none;
                    color: var(--editor-text-muted, #666);
                    cursor: pointer;
                    padding: 0;
                    font-size: 16px;
                }
                .notification-close:hover {
                    color: var(--editor-text, #e8e8e8);
                }
                @keyframes slideIn {
                    from {
                        transform: translateX(100%);
                        opacity: 0;
                    }
                    to {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }
            `;
            document.head.appendChild(style);
        }

        // Add close handler
        notification.querySelector('.notification-close').addEventListener('click', () => {
            notification.remove();
        });

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.style.animation = 'slideIn 0.3s ease reverse';
                setTimeout(() => notification.remove(), 300);
            }
        }, 5000);

        document.body.appendChild(notification);
    }

})();
