/**
 * Sidepanel Script for AI Assistant Chrome Extension
 * 
 * Main chat interface handling:
 * - Conversation management (list, create, delete, switch)
 * - Message sending with streaming responses
 * - Page content extraction and attachment
 * - Model/prompt selection
 * - Settings management
 */

import { API, AuthError } from '../shared/api.js';
import { Storage } from '../shared/storage.js';
import { MODELS, MESSAGE_TYPES } from '../shared/constants.js';

// ==================== State ====================

const state = {
    currentConversation: null,
    conversations: [],
    messages: [],
    isStreaming: false,
    pageContext: null,
    multiTabContexts: [],  // Array of {tabId, url, title, content} for multi-tab reading
    selectedTabIds: [],     // Tab IDs selected in the modal
    ocrCache: {},           // In-memory OCR cache by URL
    pendingImages: [],      // User-attached images for next message
    settings: {
        model: 'google/gemini-2.5-flash',
        promptName: 'preamble_short',
        agentName: 'None',
        workflowId: '',
        historyLength: 10,
        autoIncludePage: true,  // Enabled by default
        apiBaseUrl: ''
    },
    abortController: null,
    availableModels: [], // Fetched from server
    workflows: [],
    // Script creation mode
    scriptMode: {
        active: false,
        pendingScript: null, // Holds the generated script before saving
        pageContext: null    // Page context for script generation
    }
};

// Script creation intent patterns
const SCRIPT_INTENT_PATTERNS = [
    /create\s+(a\s+)?script/i,
    /make\s+(a\s+)?script/i,
    /build\s+(a\s+)?script/i,
    /write\s+(a\s+)?script/i,
    /generate\s+(a\s+)?script/i,
    /i\s+want\s+(a\s+)?script/i,
    /can\s+you\s+(create|make|build|write)\s+(a\s+)?script/i,
    /script\s+(to|that|for|which)/i,
    /userscript/i,
    /tampermonkey/i,
    /custom\s+script/i,
    /automation\s+script/i
];

// ==================== DOM Elements ====================

// Views
const loginView = document.getElementById('login-view');
const mainView = document.getElementById('main-view');

// Login
const loginForm = document.getElementById('login-form');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
const serverUrlInput = document.getElementById('server-url');
const loginError = document.getElementById('login-error');

// Header
const toggleSidebarBtn = document.getElementById('toggle-sidebar');
const newChatBtn = document.getElementById('new-chat-btn');
const settingsBtn = document.getElementById('settings-btn');

// Sidebar
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebar-overlay');
const closeSidebarBtn = document.getElementById('close-sidebar');
const conversationList = document.getElementById('conversation-list');
const conversationEmpty = document.getElementById('conversation-empty');
const sidebarNewChatBtn = document.getElementById('sidebar-new-chat');

// Settings Panel
const settingsPanel = document.getElementById('settings-panel');
const closeSettingsBtn = document.getElementById('close-settings');
const modelSelect = document.getElementById('model-select');
const promptSelect = document.getElementById('prompt-select');
const serverUrlSettingsInput = document.getElementById('server-url-settings');
const agentSelect = document.getElementById('agent-select');
const workflowSelect = document.getElementById('workflow-select');
const workflowNewBtn = document.getElementById('workflow-new');
const workflowSaveBtn = document.getElementById('workflow-save');
const workflowDeleteBtn = document.getElementById('workflow-delete');
const workflowNameInput = document.getElementById('workflow-name');
const workflowStepsEl = document.getElementById('workflow-steps');
const workflowAddStepBtn = document.getElementById('workflow-add-step');
const historyLengthSlider = document.getElementById('history-length-slider');
const historyValue = document.getElementById('history-value');
const autoIncludePageCheckbox = document.getElementById('auto-include-page');
const settingsUserEmail = document.getElementById('settings-user-email');
const logoutBtn = document.getElementById('logout-btn');

// Custom Scripts (Settings)
const scriptsCreateFromPageBtn = document.getElementById('scripts-create-from-page');
const scriptsOpenEditorBtn = document.getElementById('scripts-open-editor');
const scriptsRefreshBtn = document.getElementById('scripts-refresh');
const scriptsListEl = document.getElementById('scripts-list');
const scriptsHelpBtn = document.getElementById('scripts-help-btn');
const scriptsHelpPopover = document.getElementById('scripts-help-popover');

// Chat
const chatContainer = document.getElementById('chat-container');
const welcomeScreen = document.getElementById('welcome-screen');
const messagesContainer = document.getElementById('messages-container');
const streamingIndicator = document.getElementById('streaming-indicator');

// Page Context
const pageContextBar = document.getElementById('page-context-bar');
const pageContextTitle = document.getElementById('page-context-title');
const removePageContextBtn = document.getElementById('remove-page-context');

// Input
const attachPageBtn = document.getElementById('attach-page-btn');
const attachScreenshotBtn = document.getElementById('attach-screenshot-btn');
const attachScrollshotBtn = document.getElementById('attach-scrollshot-btn');
const multiTabBtn = document.getElementById('multi-tab-btn');
const voiceBtn = document.getElementById('voice-btn');
const messageInput = document.getElementById('message-input');
const inputWrapper = document.getElementById('input-wrapper');
const imageAttachmentsEl = document.getElementById('image-attachments');
const sendBtn = document.getElementById('send-btn');
const stopBtnContainer = document.getElementById('stop-btn-container');
const stopBtn = document.getElementById('stop-btn');

// Tab Modal
const tabModal = document.getElementById('tab-modal');
const tabList = document.getElementById('tab-list');
const closeTabModalBtn = document.getElementById('close-tab-modal');
const cancelTabModalBtn = document.getElementById('cancel-tab-modal');
const confirmTabModalBtn = document.getElementById('confirm-tab-modal');

// Quick suggestions
const suggestionBtns = document.querySelectorAll('.suggestion-btn');

// ==================== Initialization ====================

/**
 * Normalize API base URL input to avoid trailing slashes.
 * @param {string} value - Raw input value.
 * @returns {string}
 */
function normalizeApiBaseUrl(value) {
    return (value || '').trim().replace(/\/+$/, '');
}

/**
 * Sync server URL inputs between login and settings views.
 * @param {string} value - Server URL to apply.
 */
function syncServerUrlInputs(value) {
    if (serverUrlInput) serverUrlInput.value = value;
    if (serverUrlSettingsInput) serverUrlSettingsInput.value = value;
}

/**
 * Load server URL from storage into UI and state.
 * @returns {Promise<void>}
 */
async function loadServerUrlSetting() {
    const stored = await Storage.getApiBaseUrl();
    const normalized = normalizeApiBaseUrl(stored);
    state.settings.apiBaseUrl = normalized;
    syncServerUrlInputs(normalized);
}

/**
 * Persist server URL to storage and update state.
 * @param {string} value - Server URL value.
 * @returns {Promise<void>}
 */
async function persistServerUrlSetting(value) {
    const normalized = normalizeApiBaseUrl(value);
    if (!normalized) return;
    state.settings.apiBaseUrl = normalized;
    syncServerUrlInputs(normalized);
    await Storage.setApiBaseUrl(normalized);
}

async function initialize() {
    console.log('[Sidepanel] Initializing...');
    
    try {
        await loadServerUrlSetting();
        const isAuth = await Storage.isAuthenticated();
        
        if (isAuth) {
            const result = await API.verifyAuth();
            if (result.valid) {
                await initializeMainView();
            } else {
                await Storage.clearAuth();
                showView('login');
            }
        } else {
            showView('login');
        }
    } catch (error) {
        console.error('[Sidepanel] Init error:', error);
        showView('login');
    }
    
    // Set up event listeners
    setupEventListeners();
    
    // Listen for messages from service worker
    chrome.runtime.onMessage.addListener(handleRuntimeMessage);
}

async function initializeMainView() {
    // Load user info
    const userInfo = await Storage.getUserInfo();
    if (userInfo) {
        settingsUserEmail.textContent = userInfo.email;
    }
    
    // Load settings
    await loadSettings();
    
    // Load conversations
    await loadConversations();
    
    // Check for current conversation
    const currentId = await Storage.getCurrentConversation();
    if (currentId && state.conversations.find(c => c.conversation_id === currentId)) {
        await selectConversation(currentId);
    }
    
    showView('main');
}

function showView(viewName) {
    loginView.classList.toggle('hidden', viewName !== 'login');
    mainView.classList.toggle('hidden', viewName !== 'main');
}

// ==================== Event Listeners ====================

function setupEventListeners() {
    // Login
    loginForm.addEventListener('submit', handleLogin);
    serverUrlInput?.addEventListener('change', async () => {
        await persistServerUrlSetting(serverUrlInput.value);
    });
    document.querySelectorAll('.server-preset-btn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const url = btn.getAttribute('data-url') || '';
            if (!url) return;
            await persistServerUrlSetting(url);
        });
    });
    
    // Sidebar
    toggleSidebarBtn.addEventListener('click', () => toggleSidebar(true));
    closeSidebarBtn.addEventListener('click', () => toggleSidebar(false));
    sidebarOverlay.addEventListener('click', () => toggleSidebar(false));
    sidebarNewChatBtn.addEventListener('click', async () => {
        toggleSidebar(false);
        await createNewConversation();
    });
    
    // Settings
    settingsBtn.addEventListener('click', () => toggleSettings(true));
    closeSettingsBtn.addEventListener('click', () => toggleSettings(false));
    logoutBtn.addEventListener('click', handleLogout);

    // Custom Scripts (Settings)
    scriptsCreateFromPageBtn?.addEventListener('click', async () => {
        const description = prompt(
            'Describe what you want to automate on this page.\n\n' +
            'Tip: scripts use aiAssistant.dom.click/setValue/type/hide/remove (no direct document.querySelector).'
        );
        if (!description || !description.trim()) return;
        toggleSettings(false);
        await handleScriptGeneration(description.trim());
    });
    scriptsOpenEditorBtn?.addEventListener('click', async () => {
        chrome.runtime.sendMessage({ type: 'OPEN_SCRIPT_EDITOR' });
    });
    scriptsRefreshBtn?.addEventListener('click', async () => {
        await refreshScriptsList();
    });

    scriptsHelpBtn?.addEventListener('click', () => {
        scriptsHelpPopover?.classList.toggle('hidden');
    });
    
    // Settings controls
    modelSelect.addEventListener('change', () => {
        state.settings.model = modelSelect.value;
        saveSettings();
    });
    
    promptSelect.addEventListener('change', () => {
        state.settings.promptName = promptSelect.value;
        saveSettings();
    });

    serverUrlSettingsInput?.addEventListener('change', async () => {
        await persistServerUrlSetting(serverUrlSettingsInput.value);
        saveSettings();
    });

    agentSelect?.addEventListener('change', () => {
        state.settings.agentName = agentSelect.value;
        saveSettings();
    });

    workflowSelect?.addEventListener('change', () => {
        state.settings.workflowId = workflowSelect.value || '';
        const selected = state.workflows.find(w => w.workflow_id === state.settings.workflowId);
        if (selected) {
            loadWorkflowIntoForm(selected);
        }
        saveSettings();
    });

    workflowNewBtn?.addEventListener('click', () => {
        loadWorkflowIntoForm({ workflow_id: '', name: '', steps: [] });
    });

    workflowSaveBtn?.addEventListener('click', async () => {
        await saveWorkflowFromForm();
    });

    workflowDeleteBtn?.addEventListener('click', async () => {
        await deleteWorkflowFromForm();
    });

    workflowAddStepBtn?.addEventListener('click', () => {
        addWorkflowStep();
    });
    
    historyLengthSlider.addEventListener('input', () => {
        state.settings.historyLength = parseInt(historyLengthSlider.value);
        historyValue.textContent = historyLengthSlider.value;
        saveSettings();
    });
    
    autoIncludePageCheckbox.addEventListener('change', () => {
        state.settings.autoIncludePage = autoIncludePageCheckbox.checked;
        saveSettings();
    });
    
    // New chat
    newChatBtn.addEventListener('click', createNewConversation);
    
    // Input
    messageInput.addEventListener('input', handleInputChange);
    messageInput.addEventListener('keydown', handleInputKeydown);
    sendBtn.addEventListener('click', sendMessage);
    stopBtn.addEventListener('click', stopStreaming);
    
    // Page context
    attachPageBtn.addEventListener('click', attachPageContent);
    attachScreenshotBtn?.addEventListener('click', attachScreenshotFromPage);
    attachScrollshotBtn?.addEventListener('click', attachScrollingScreenshotFromPage);
    removePageContextBtn.addEventListener('click', removePageContext);
    
    // Multi-tab
    multiTabBtn.addEventListener('click', showTabModal);
    closeTabModalBtn.addEventListener('click', () => tabModal.classList.add('hidden'));
    cancelTabModalBtn.addEventListener('click', () => tabModal.classList.add('hidden'));
    confirmTabModalBtn.addEventListener('click', handleTabSelection);
    
    // Voice (placeholder)
    voiceBtn.addEventListener('click', () => {
        alert('Voice input coming soon!');
    });
    
    // Quick suggestions
    suggestionBtns.forEach(btn => {
        btn.addEventListener('click', () => handleQuickSuggestion(btn.dataset.action));
    });

    // Image drag-and-drop (input + whole panel)
    const dragTargets = [inputWrapper, mainView].filter(Boolean);
    dragTargets.forEach((target) => {
        target.addEventListener('dragover', (e) => {
            e.preventDefault();
            inputWrapper?.classList.add('drag-over');
        });
        target.addEventListener('dragleave', () => {
            inputWrapper?.classList.remove('drag-over');
        });
        target.addEventListener('drop', handleImageDrop);
    });
    
    // Conversation list delegation
    conversationList.addEventListener('click', handleConversationClick);
}

// ==================== Login ====================

async function handleLogin(e) {
    e.preventDefault();
    
    const email = emailInput.value.trim();
    const password = passwordInput.value;
    const serverUrl = serverUrlInput?.value || '';
    
    if (!email || !password) return;
    
    const loginBtn = document.getElementById('login-btn');
    loginBtn.disabled = true;
    loginBtn.textContent = 'Signing in...';
    loginError.classList.add('hidden');
    
    try {
        if (serverUrl) {
            await persistServerUrlSetting(serverUrl);
        }
        await API.login(email, password);
        await initializeMainView();
    } catch (error) {
        console.error('[Sidepanel] Login failed:', error);
        loginError.textContent = error.message || 'Login failed';
        loginError.classList.remove('hidden');
    } finally {
        loginBtn.disabled = false;
        loginBtn.textContent = 'Sign In';
    }
}

async function handleLogout() {
    try {
        await API.logout();
    } catch (e) {
        // Ignore
    }
    
    state.currentConversation = null;
    state.conversations = [];
    state.messages = [];
    
    toggleSettings(false);
    showView('login');
    emailInput.value = '';
    passwordInput.value = '';
}

// ==================== Sidebar & Settings ====================

function toggleSidebar(open) {
    sidebar.classList.toggle('open', open);
    sidebarOverlay.classList.toggle('hidden', !open);
}

function toggleSettings(open) {
    settingsPanel.classList.toggle('open', open);
    if (open) {
        refreshScriptsList().catch(() => {});
    }
}

// ==================== Settings ====================

/**
 * Render the scripts list inside Settings > Custom Scripts.
 * Uses `/ext/scripts` and provides an Edit button to open the editor.
 */
async function refreshScriptsList() {
    if (!scriptsListEl) return;

    scriptsListEl.innerHTML = `<div class="scripts-empty">Loading…</div>`;

    try {
        const result = await API.getScripts();
        const scripts = result.scripts || [];
        if (scripts.length === 0) {
            scriptsListEl.innerHTML = `<div class="scripts-empty">No scripts yet.</div>`;
            return;
        }

        scriptsListEl.innerHTML = scripts.map((s) => {
            const patterns = Array.isArray(s.match_patterns) ? s.match_patterns : [];
            const patternPreview = patterns.slice(0, 2).join(', ') + (patterns.length > 2 ? '…' : '');
            const type = s.script_type || 'functional';
            const enabled = s.enabled === 0 ? 'disabled' : 'enabled';
            return `
                <div class="script-list-item" data-script-id="${escapeHtml(String(s.script_id || ''))}">
                    <div class="meta">
                        <div class="name">${escapeHtml(s.name || 'Unnamed Script')}</div>
                        <div class="details">${escapeHtml(type)} • ${escapeHtml(enabled)} • ${escapeHtml(patternPreview || '(no patterns)')}</div>
                    </div>
                    <div class="actions">
                        <button class="btn btn-secondary btn-small scripts-edit-btn" data-script-id="${escapeHtml(String(s.script_id || ''))}">
                            Edit
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        // Attach edit handlers
        scriptsListEl.querySelectorAll('.scripts-edit-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                const scriptId = btn.getAttribute('data-script-id');
                if (!scriptId) return;
                chrome.runtime.sendMessage({ type: 'OPEN_SCRIPT_EDITOR', scriptId });
            });
        });
    } catch (e) {
        console.warn('[Sidepanel] Failed to refresh scripts list:', e);
        scriptsListEl.innerHTML = `<div class="scripts-empty">Failed to load scripts. Try again.</div>`;
    }
}

async function loadSettings() {
    // Fetch models from server
    try {
        const modelsData = await API.getModels();
        if (modelsData.models && modelsData.models.length > 0) {
            state.availableModels = modelsData.models;
            modelSelect.innerHTML = modelsData.models.map(m => 
                `<option value="${m.id}">${m.name}</option>`
            ).join('');
        } else {
            // Fallback to constants
            modelSelect.innerHTML = MODELS.map(m => 
                `<option value="${m.id}">${m.name}</option>`
            ).join('');
        }
    } catch (e) {
        console.warn('[Sidepanel] Failed to load models from server:', e);
        // Fallback to constants
        modelSelect.innerHTML = MODELS.map(m => 
            `<option value="${m.id}">${m.name}</option>`
        ).join('');
    }
    
    // Populate prompt dropdown
    try {
        const promptsData = await API.getPrompts();
        if (promptsData.prompts && promptsData.prompts.length > 0) {
            promptSelect.innerHTML = promptsData.prompts.map(p => 
                `<option value="${p.name}">${p.name}</option>`
            ).join('');
        }
    } catch (e) {
        console.warn('[Sidepanel] Failed to load prompts:', e);
        promptSelect.innerHTML = '<option value="preamble_short">preamble_short</option>';
    }

    // Populate agent dropdown
    try {
        const agentsData = await API.getAgents();
        if (agentsData.agents && agentsData.agents.length > 0) {
            agentSelect.innerHTML = agentsData.agents.map(a =>
                `<option value="${a}">${a}</option>`
            ).join('');
        } else {
            agentSelect.innerHTML = '<option value="None">None</option>';
        }
    } catch (e) {
        console.warn('[Sidepanel] Failed to load agents:', e);
        agentSelect.innerHTML = '<option value="None">None</option>';
    }

    // Populate workflow dropdown + form
    await refreshWorkflows();
    
    // Load saved settings
    const savedSettings = await Storage.getSettings();
    state.settings = { ...state.settings, ...savedSettings };
    if (!state.settings.apiBaseUrl) {
        state.settings.apiBaseUrl = await Storage.getApiBaseUrl();
    }
    
    // Apply to UI
    modelSelect.value = state.settings.defaultModel || state.settings.model;
    promptSelect.value = state.settings.defaultPrompt || state.settings.promptName;
    if (!promptSelect.value && promptSelect.options.length > 0) {
        promptSelect.value = promptSelect.options[0].value;
    }
    state.settings.promptName = promptSelect.value;
    if (serverUrlSettingsInput) {
        serverUrlSettingsInput.value = state.settings.apiBaseUrl || '';
    }
    agentSelect.value = state.settings.defaultAgent || state.settings.agentName || 'None';
    if (workflowSelect) {
        workflowSelect.value = state.settings.defaultWorkflowId || state.settings.workflowId || '';
        const selected = state.workflows.find(w => w.workflow_id === workflowSelect.value);
        if (selected) {
            loadWorkflowIntoForm(selected);
        }
    }
    historyLengthSlider.value = state.settings.historyLength;
    historyValue.textContent = state.settings.historyLength;
    // Default to true if not explicitly set to false
    autoIncludePageCheckbox.checked = state.settings.autoIncludePage !== false;
}

async function saveSettings() {
    await Storage.setSettings({
        defaultModel: state.settings.model,
        defaultPrompt: state.settings.promptName,
        defaultAgent: state.settings.agentName,
        defaultWorkflowId: state.settings.workflowId,
        historyLength: state.settings.historyLength,
        apiBaseUrl: state.settings.apiBaseUrl,
        autoIncludePage: state.settings.autoIncludePage
    });
}

// ==================== Conversations ====================

async function loadConversations() {
    try {
        const data = await API.getConversations({ limit: 50 });
        state.conversations = data.conversations || [];
        renderConversationList();
    } catch (error) {
        console.error('[Sidepanel] Failed to load conversations:', error);
        state.conversations = [];
        renderConversationList();
    }
}

function renderConversationList() {
    if (state.conversations.length === 0) {
        conversationList.classList.add('hidden');
        conversationEmpty.classList.remove('hidden');
        return;
    }
    
    conversationList.classList.remove('hidden');
    conversationEmpty.classList.add('hidden');
    
    conversationList.innerHTML = state.conversations.map(conv => `
        <li data-id="${conv.conversation_id}" class="${conv.conversation_id === state.currentConversation?.conversation_id ? 'active' : ''}">
            <span class="conv-icon">${conv.is_temporary ? '💭' : '💬'}</span>
            <div class="conv-info">
                <div class="conv-title">${escapeHtml(conv.title || 'New Chat')}</div>
                <div class="conv-time">${formatTimeAgo(conv.updated_at)}</div>
            </div>
            <div class="conv-actions">
                ${conv.is_temporary ? `
                    <button class="icon-btn-small conv-save" data-action="save" title="Save conversation">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                            <polyline points="17 21 17 13 7 13 7 21"></polyline>
                            <polyline points="7 3 7 8 15 8"></polyline>
                        </svg>
                    </button>
                ` : ''}
                <button class="icon-btn-small conv-delete" data-action="delete" title="Delete">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        </li>
    `).join('');
}

// ==================== Workflows ====================

/**
 * Refresh workflows list from the backend and update UI.
 */
async function refreshWorkflows() {
    try {
        const data = await API.getWorkflows();
        state.workflows = data.workflows || [];
        renderWorkflowSelect();
        if (state.workflows.length === 0) {
            loadWorkflowIntoForm({ workflow_id: '', name: '', steps: [] });
        }
    } catch (error) {
        console.warn('[Sidepanel] Failed to load workflows:', error);
        state.workflows = [];
        renderWorkflowSelect();
        loadWorkflowIntoForm({ workflow_id: '', name: '', steps: [] });
    }
}

/**
 * Render the workflow dropdown.
 */
function renderWorkflowSelect() {
    if (!workflowSelect) return;
    const options = ['<option value="">None</option>']
        .concat(state.workflows.map(w => `<option value="${w.workflow_id}">${escapeHtml(w.name)}</option>`));
    workflowSelect.innerHTML = options.join('');
}

/**
 * Load workflow data into the editor form.
 * @param {Object} workflow - Workflow object.
 */
function loadWorkflowIntoForm(workflow) {
    if (!workflowNameInput || !workflowStepsEl) return;
    workflowNameInput.value = workflow.name || '';
    workflowStepsEl.innerHTML = '';
    const steps = Array.isArray(workflow.steps) ? workflow.steps : [];
    if (steps.length === 0) {
        addWorkflowStep();
    } else {
        steps.forEach(step => addWorkflowStep(step));
    }
    workflowStepsEl.dataset.workflowId = workflow.workflow_id || '';
}

/**
 * Add a workflow step block to the editor.
 * @param {Object} step - Optional step data.
 */
function addWorkflowStep(step = {}) {
    if (!workflowStepsEl) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'workflow-step';
    wrapper.innerHTML = `
        <div class="workflow-step-header">
            <input class="workflow-input workflow-step-title" type="text" placeholder="Step title" value="${escapeHtml(step.title || '')}">
            <button class="remove-btn" type="button">Remove</button>
        </div>
        <textarea class="workflow-textarea workflow-step-prompt" rows="3" placeholder="Step prompt">${escapeHtml(step.prompt || '')}</textarea>
    `;
    wrapper.querySelector('.remove-btn').addEventListener('click', () => {
        wrapper.remove();
    });
    workflowStepsEl.appendChild(wrapper);
}

/**
 * Read workflow data from the editor form.
 * @returns {Object} Workflow payload.
 */
function readWorkflowFromForm() {
    const workflowId = workflowStepsEl?.dataset.workflowId || '';
    const name = workflowNameInput?.value?.trim() || '';
    const steps = [];
    workflowStepsEl?.querySelectorAll('.workflow-step').forEach((el) => {
        const title = el.querySelector('.workflow-step-title')?.value?.trim() || '';
        const prompt = el.querySelector('.workflow-step-prompt')?.value?.trim() || '';
        if (title || prompt) {
            steps.push({ title, prompt });
        }
    });
    return { workflowId, name, steps };
}

/**
 * Save workflow from the editor form (create or update).
 */
async function saveWorkflowFromForm() {
    const { workflowId, name, steps } = readWorkflowFromForm();
    if (!name) {
        alert('Workflow name is required.');
        return;
    }
    if (steps.length === 0) {
        alert('Add at least one step.');
        return;
    }
    try {
        if (workflowId) {
            await API.updateWorkflow(workflowId, { name, steps });
        } else {
            const res = await API.createWorkflow({ name, steps });
            workflowStepsEl.dataset.workflowId = res.workflow.workflow_id;
        }
        await refreshWorkflows();
        const selected = state.workflows.find(w => w.name === name);
        if (selected) {
            state.settings.workflowId = selected.workflow_id;
            saveSettings();
            if (workflowSelect) workflowSelect.value = selected.workflow_id;
        }
    } catch (e) {
        console.error('[Sidepanel] Failed to save workflow:', e);
        alert('Failed to save workflow.');
    }
}

/**
 * Delete the workflow currently loaded in the editor.
 */
async function deleteWorkflowFromForm() {
    const workflowId = workflowStepsEl?.dataset.workflowId || '';
    if (!workflowId) return;
    if (!confirm('Delete this workflow?')) return;
    try {
        await API.deleteWorkflow(workflowId);
        workflowStepsEl.dataset.workflowId = '';
        await refreshWorkflows();
        state.settings.workflowId = '';
        saveSettings();
        if (workflowSelect) workflowSelect.value = '';
        loadWorkflowIntoForm({ workflow_id: '', name: '', steps: [] });
    } catch (e) {
        console.error('[Sidepanel] Failed to delete workflow:', e);
        alert('Failed to delete workflow.');
    }
}

async function handleConversationClick(e) {
    const li = e.target.closest('li');
    if (!li) return;
    
    const convId = li.dataset.id;
    const deleteBtn = e.target.closest('[data-action="delete"]');
    const saveBtn = e.target.closest('[data-action="save"]');
    
    if (deleteBtn) {
        e.stopPropagation();
        await deleteConversation(convId);
    } else if (saveBtn) {
        e.stopPropagation();
        await saveConversation(convId);
    } else {
        await selectConversation(convId);
        toggleSidebar(false);
    }
}

async function selectConversation(convId) {
    try {
        const data = await API.getConversation(convId);
        state.currentConversation = data.conversation;
        state.messages = data.conversation.messages || [];
        
        // Update UI
        renderConversationList();
        renderMessages();
        
        // Save as current
        await Storage.setCurrentConversation(convId);
        await Storage.addRecentConversation({
            id: convId,
            title: data.conversation.title,
            updatedAt: data.conversation.updated_at
        });
        
        // Hide welcome, show messages
        welcomeScreen.classList.add('hidden');
        messagesContainer.classList.remove('hidden');
        
    } catch (error) {
        console.error('[Sidepanel] Failed to load conversation:', error);
    }
}

async function createNewConversation() {
    try {
        clearOcrCache();
        clearImageAttachments();
        const data = await API.createConversation({
            title: 'New Chat',
            is_temporary: true,
            model: state.settings.model,
            prompt_name: state.settings.promptName,
            history_length: state.settings.historyLength
        });
        
        state.currentConversation = data.conversation;
        state.messages = [];
        
        // Add to list
        state.conversations.unshift(data.conversation);
        renderConversationList();
        
        // Reset UI
        welcomeScreen.classList.remove('hidden');
        messagesContainer.classList.add('hidden');
        messagesContainer.innerHTML = '';
        removePageContext();
        messageInput.value = '';
        updateSendButton();
        
        await Storage.setCurrentConversation(data.conversation.conversation_id);
        return true;
    } catch (error) {
        console.error('[Sidepanel] Failed to create conversation:', error);
        alert(`Failed to start chat: ${error.message || error}`);
        state.currentConversation = null;
        return false;
    }
}

async function deleteConversation(convId) {
    if (!confirm('Delete this conversation?')) return;
    
    try {
        await API.deleteConversation(convId);
        
        // Remove from list
        state.conversations = state.conversations.filter(c => c.conversation_id !== convId);
        renderConversationList();
        
        // If was current, reset
        if (state.currentConversation?.conversation_id === convId) {
            state.currentConversation = null;
            state.messages = [];
            welcomeScreen.classList.remove('hidden');
            messagesContainer.classList.add('hidden');
            messagesContainer.innerHTML = '';
            await Storage.setCurrentConversation(null);
        }
    } catch (error) {
        console.error('[Sidepanel] Failed to delete conversation:', error);
    }
}

async function saveConversation(convId) {
    try {
        const result = await API.saveConversation(convId);
        
        // Update in local state
        const conv = state.conversations.find(c => c.conversation_id === convId);
        if (conv) {
            conv.is_temporary = false;
        }
        
        // Update current conversation if it's the one being saved
        if (state.currentConversation?.conversation_id === convId) {
            state.currentConversation.is_temporary = false;
        }
        
        renderConversationList();
        
        // Show brief feedback
        console.log('[Sidepanel] Conversation saved:', convId);
    } catch (error) {
        console.error('[Sidepanel] Failed to save conversation:', error);
        alert('Failed to save conversation');
    }
}

// ==================== Messages ====================

function renderMessages() {
    if (state.messages.length === 0) {
        welcomeScreen.classList.remove('hidden');
        messagesContainer.classList.add('hidden');
        return;
    }
    
    welcomeScreen.classList.add('hidden');
    messagesContainer.classList.remove('hidden');
    
    messagesContainer.innerHTML = state.messages.map(msg => renderMessage(msg)).join('');
    
    // Syntax highlighting and copy buttons
    processCodeBlocks(messagesContainer);
}

function renderMessage(msg) {
    const isUser = msg.role === 'user';
    const avatar = isUser ? '👤' : '🤖';
    const roleName = isUser ? 'You' : 'Assistant';
    
    // Parse markdown for assistant messages
    let content = msg.content;
    if (!isUser && window.marked) {
        content = marked.parse(content);
    } else {
        content = escapeHtml(content).replace(/\n/g, '<br>');
    }
    
    return `
        <div class="message ${msg.role}" data-id="${msg.message_id}">
            <div class="message-header">
                <span class="message-avatar">${avatar}</span>
                <span>${roleName}</span>
                <span class="message-time">${formatTime(msg.created_at)}</span>
            </div>
            <div class="message-content">${content}</div>
        </div>
    `;
}

/**
 * Process code blocks: highlight and add copy buttons
 * @param {HTMLElement} container - The container to process
 */
function processCodeBlocks(container) {
    container.querySelectorAll('pre').forEach(pre => {
        // Skip if already processed
        if (pre.dataset.processed) return;
        pre.dataset.processed = 'true';
        
        const code = pre.querySelector('code');
        
        // Highlight
        if (code && window.hljs) {
            hljs.highlightElement(code);
        }
        
        // Get language from class (remove 'language-' prefix and 'hljs')
        let lang = 'code';
        if (code?.className) {
            const match = code.className.match(/language-(\w+)/);
            if (match) lang = match[1];
        }
        
        // Create wrapper if not exists
        let wrapper = pre.closest('.code-block-wrapper');
        if (!wrapper) {
            wrapper = document.createElement('div');
            wrapper.className = 'code-block-wrapper';
            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(pre);
        }
        
        // Add header if not exists
        if (!wrapper.querySelector('.code-block-header')) {
            const header = document.createElement('div');
            header.className = 'code-block-header';
            header.innerHTML = `
                <span class="code-lang">${lang}</span>
                <button class="copy-code-btn">Copy</button>
            `;
            
            header.querySelector('.copy-code-btn').addEventListener('click', function() {
                const text = code?.textContent || pre.textContent;
                navigator.clipboard.writeText(text);
                this.textContent = 'Copied!';
                setTimeout(() => {
                    this.textContent = 'Copy';
                }, 2000);
            });
            
            wrapper.insertBefore(header, pre);
        }
    });
}

// ==================== Input Handling ====================

function handleInputChange() {
    // Auto-resize textarea
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
    
    updateSendButton();
}

function handleInputKeydown(e) {
    // Send on Enter (without Shift for newline)
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function updateSendButton() {
    const hasText = !!messageInput.value.trim();
    const hasImages = state.pendingImages.length > 0;
    sendBtn.disabled = (!hasText && !hasImages) || state.isStreaming;
}

// ==================== Send Message ====================

async function sendMessage() {
    const text = messageInput.value.trim();
    const hasImages = state.pendingImages.length > 0;
    if ((!text && !hasImages) || state.isStreaming) return;
    
    // Check for script creation intent
    if (text && detectScriptIntent(text)) {
        console.log('[Sidepanel] Script creation intent detected');
        handleScriptGeneration(text);
        return;
    }
    
    // Ensure we have a conversation
    if (!state.currentConversation) {
        const created = await createNewConversation();
        if (!created || !state.currentConversation) {
            return;
        }
    }
    
    // Auto-attach page content if enabled and not already attached
    // Skip if we already have multi-tab context - don't overwrite it!
    if (state.settings.autoIncludePage && !state.pageContext) {
        console.log('[Sidepanel] Auto-attaching page content (no existing context)');
        try {
            const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXTRACT_PAGE });
            if (response && !response.error) {
                const context = await buildPageContextFromResponse(response, { showAlerts: false });
                if (context) {
                    state.pageContext = context;
                    const prefix = context.isOcr ? '🧾 ' : context.isScreenshot ? '📷 ' : '';
                    pageContextTitle.textContent = `${prefix}${state.pageContext.title || 'Page content'}`;
                    pageContextBar.classList.remove('hidden');
                    attachPageBtn.classList.add('active');
                }
            }
        } catch (e) {
            console.warn('[Sidepanel] Auto page attach failed:', e);
        }
    } else if (state.pageContext) {
        console.log('[Sidepanel] Using existing pageContext:', {
            isMultiTab: state.pageContext.isMultiTab,
            tabCount: state.pageContext.tabCount,
            contentLength: state.pageContext.content?.length
        });
    }
    
    // Add user message to UI
    const userMessage = {
        message_id: 'temp-user-' + Date.now(),
        role: 'user',
        content: text || '[Image attached]',
        created_at: new Date().toISOString()
    };
    state.messages.push(userMessage);
    
    // Show messages container
    welcomeScreen.classList.add('hidden');
    messagesContainer.classList.remove('hidden');
    
    // Render user message
    messagesContainer.insertAdjacentHTML('beforeend', renderMessage(userMessage));
    
    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';
    updateSendButton();
    
    // Start streaming
    state.isStreaming = true;
    streamingIndicator.classList.remove('hidden');
    stopBtnContainer.classList.remove('hidden');
    
    // Create assistant message placeholder
    const assistantMessage = {
        message_id: 'temp-assistant-' + Date.now(),
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString()
    };
    state.messages.push(assistantMessage);
    messagesContainer.insertAdjacentHTML('beforeend', renderMessage(assistantMessage));
    
    const assistantEl = messagesContainer.querySelector(`[data-id="${assistantMessage.message_id}"] .message-content`);
    
    try {
        state.abortController = new AbortController();
        
        // Debug: Check if multi-tab context was preserved
        const contextInfo = {
            hasPageContext: !!state.pageContext,
            isMultiTab: state.pageContext?.isMultiTab,
            tabCount: state.pageContext?.tabCount,
            contentLength: state.pageContext?.content?.length,
            multiTabContextsLength: state.multiTabContexts?.length
        };
        console.log('[Sidepanel] Sending message with pageContext:', contextInfo);
        
        // If we have multiTabContexts but pageContext lost isMultiTab, restore it
        if (state.multiTabContexts?.length > 0 && !state.pageContext?.isMultiTab) {
            console.warn('[Sidepanel] Multi-tab context was overwritten! Restoring...');
            const combinedContent = state.multiTabContexts.map(c => 
                `## Tab: ${c.title}\nURL: ${c.url}\n\n${c.content}`
            ).join('\n\n---\n\n');
            
            state.pageContext = {
                url: state.multiTabContexts.length === 1 ? state.multiTabContexts[0].url : 'Multiple tabs',
                title: state.multiTabContexts.length === 1 ? state.multiTabContexts[0].title : `${state.multiTabContexts.length} tabs`,
                content: combinedContent,
                isMultiTab: true,
                tabCount: state.multiTabContexts.length
            };
            console.log('[Sidepanel] Restored multi-tab pageContext:', state.pageContext.content?.length);
        }
        
        const workflowId = state.settings.workflowId || '';
        const agentToUse = workflowId ? 'PromptWorkflowAgent' : state.settings.agentName;

        await API.sendMessageStreaming(
            state.currentConversation.conversation_id,
            {
                message: text,
                pageContext: state.pageContext,
                model: state.settings.model,
                agent: agentToUse,
                workflow_id: workflowId || null,
                images: state.pendingImages.map((img) => img.dataUrl)
            },
            {
                onChunk: (chunk) => {
                    assistantMessage.content += chunk;
                    if (window.marked) {
                        assistantEl.innerHTML = marked.parse(assistantMessage.content);
                    } else {
                        assistantEl.textContent = assistantMessage.content;
                    }
                },
                onDone: (data) => {
                    // Update message ID if provided
                    if (data?.message_id) {
                        assistantMessage.message_id = data.message_id;
                    }
                    
                    // Process code blocks (highlight + copy buttons)
                    processCodeBlocks(assistantEl);
                    
                    // Update conversation in list
                    updateConversationInList(text || '[Image attached]');

                    // Clear image attachments after successful send
                    clearImageAttachments();
                },
                onError: (error) => {
                    console.error('[Sidepanel] Streaming error:', error);
                    assistantEl.innerHTML = `<div class="error-message">Error: ${error.message}</div>`;
                }
            }
        );
    } catch (error) {
        console.error('[Sidepanel] Send message failed:', error);
        
        if (error instanceof AuthError) {
            showView('login');
            return;
        }
        
        assistantEl.innerHTML = `<div class="error-message">Failed to get response: ${error.message}</div>`;
    } finally {
        state.isStreaming = false;
        state.abortController = null;
        streamingIndicator.classList.add('hidden');
        stopBtnContainer.classList.add('hidden');
    }
}

function stopStreaming() {
    if (state.abortController) {
        state.abortController.abort();
    }
    state.isStreaming = false;
    streamingIndicator.classList.add('hidden');
    stopBtnContainer.classList.add('hidden');
}

// ==================== Script Creation Mode ====================

/**
 * Check if user message indicates script creation intent
 * @param {string} text - User message
 * @returns {boolean} - True if script creation intent detected
 */
function detectScriptIntent(text) {
    return SCRIPT_INTENT_PATTERNS.some(pattern => pattern.test(text));
}

/**
 * Handle script generation flow
 * @param {string} description - User's description of what the script should do
 */
async function handleScriptGeneration(description) {
    console.log('[Sidepanel] Starting script generation:', description);
    
    // Ensure we have a conversation
    if (!state.currentConversation) {
        await createNewConversation();
    }
    
    // Add user message to UI
    const userMessage = {
        message_id: 'temp-user-' + Date.now(),
        role: 'user',
        content: description,
        created_at: new Date().toISOString()
    };
    state.messages.push(userMessage);
    
    // Show messages container
    welcomeScreen.classList.add('hidden');
    messagesContainer.classList.remove('hidden');
    messagesContainer.insertAdjacentHTML('beforeend', renderMessage(userMessage));
    
    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';
    updateSendButton();
    
    // Start streaming-like UI feedback
    state.isStreaming = true;
    streamingIndicator.classList.remove('hidden');
    
    // Create assistant message placeholder
    const assistantMessage = {
        message_id: 'temp-assistant-script-' + Date.now(),
        role: 'assistant',
        content: '🔧 Generating script...',
        created_at: new Date().toISOString(),
        isScript: true
    };
    state.messages.push(assistantMessage);
    messagesContainer.insertAdjacentHTML('beforeend', renderMessage(assistantMessage));
    
    const assistantEl = messagesContainer.querySelector(`[data-id="${assistantMessage.message_id}"] .message-content`);
    
    try {
        // Get page context for script generation
        let pageUrl = '';
        let pageHtml = '';
        let pageContext = null;
        
        try {
            const response = await chrome.runtime.sendMessage({ type: 'GET_PAGE_CONTEXT' });
            if (response) {
                pageUrl = response.url || '';
                pageHtml = response.htmlSnapshot || '';
                pageContext = response;
            }
        } catch (e) {
            console.warn('[Sidepanel] Could not get page context:', e);
        }
        
        // Call script generation API
        const result = await API.generateScript({
            description: description,
            page_url: pageUrl,
            page_html: pageHtml,
            page_context: pageContext
        });
        
        if (result.error) {
            throw new Error(result.error);
        }
        
        // Store pending script
        state.scriptMode.active = true;
        state.scriptMode.pendingScript = result.script;
        state.scriptMode.pageContext = pageContext;
        
        // Render script response with buttons
        assistantEl.innerHTML = renderScriptResponse(result.script, result.explanation);
        
        // Attach event handlers to script buttons
        attachScriptButtonHandlers(assistantEl, result.script);
        
        // Process code blocks
        processCodeBlocks(assistantEl);
        
        // Update conversation title
        updateConversationInList(description);
        
    } catch (error) {
        console.error('[Sidepanel] Script generation failed:', error);
        assistantEl.innerHTML = `
            <div class="error-message">
                Failed to generate script: ${escapeHtml(error.message)}
            </div>
            <p>You can try rephrasing your request or provide more details about what you want the script to do.</p>
        `;
    } finally {
        state.isStreaming = false;
        streamingIndicator.classList.add('hidden');
        stopBtnContainer.classList.add('hidden');
    }
}

/**
 * Render script response with code and action buttons
 * @param {Object} script - Generated script object
 * @param {string} explanation - LLM explanation
 * @returns {string} - HTML string
 */
function renderScriptResponse(script, explanation) {
    const actionsHtml = script.actions?.length > 0 
        ? script.actions.map(action => `
            <div class="script-action-item">
                <span class="action-icon">${getActionIcon(action.icon)}</span>
                <span class="action-name">${escapeHtml(action.name)}</span>
                <span class="action-exposure">${action.exposure || 'floating'}</span>
            </div>
        `).join('')
        : '<p class="no-actions">No actions defined</p>';
    
    return `
        <div class="script-response">
            <div class="script-response-header">
                <h4>🔧 ${escapeHtml(script.name || 'Generated Script')}</h4>
                <details class="script-runtime-help">
                    <summary title="Script runtime help">?</summary>
                    <div class="script-runtime-help-body">
                        <div><strong>Runtime:</strong> Tampermonkey-style. No direct <code>document.querySelector</code>.</div>
                        <div>Use <code>aiAssistant.dom.click</code>, <code>setValue</code>, <code>type</code>, <code>hide</code>/<code>remove</code>.</div>
                        <div>Export: <code>window.__scriptHandlers = handlers;</code></div>
                    </div>
                </details>
            </div>
            <p>${escapeHtml(script.description || '')}</p>
            
            <div class="script-meta">
                <span class="script-type">${script.script_type || 'functional'}</span>
                <span class="script-patterns">${(script.match_patterns || []).join(', ')}</span>
            </div>
            
            <div class="script-explanation">
                ${window.marked ? marked.parse(explanation || '') : escapeHtml(explanation || '')}
            </div>
            
            <div class="script-code-section">
                <h5>Code</h5>
                <pre><code class="language-javascript">${escapeHtml(script.code || '')}</code></pre>
            </div>
            
            <div class="script-actions-section">
                <h5>Actions</h5>
                <div class="script-actions-list">
                    ${actionsHtml}
                </div>
            </div>
            
            <div class="script-buttons">
                <button class="btn btn-primary script-save-btn">💾 Save Script</button>
                <button class="btn btn-secondary script-test-btn">▶️ Test on Page</button>
                <button class="btn btn-ghost script-edit-btn">✏️ Edit in Editor</button>
            </div>
        </div>
    `;
}

/**
 * Get emoji icon for action
 * @param {string} iconName - Icon name
 * @returns {string} - Emoji
 */
function getActionIcon(iconName) {
    const icons = {
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
        play: '▶️'
    };
    return icons[iconName] || '🔧';
}

/**
 * Attach event handlers to script action buttons
 * @param {HTMLElement} container - Container element
 * @param {Object} script - Script object
 */
function attachScriptButtonHandlers(container, script) {
    // Save button
    const saveBtn = container.querySelector('.script-save-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            try {
                saveBtn.disabled = true;
                saveBtn.textContent = '⏳ Saving...';
                
                const result = await API.saveScript(script);
                
                if (result.error) {
                    throw new Error(result.error);
                }
                
                saveBtn.textContent = '✅ Saved!';
                state.scriptMode.active = false;
                state.scriptMode.pendingScript = null;
                
                // Notify script runner to reload
                chrome.runtime.sendMessage({ type: 'SCRIPTS_UPDATED' });
                
            } catch (error) {
                console.error('[Sidepanel] Failed to save script:', error);
                saveBtn.textContent = '❌ Save Failed';
                setTimeout(() => {
                    saveBtn.disabled = false;
                    saveBtn.textContent = '💾 Save Script';
                }, 2000);
            }
        });
    }
    
    // Test button
    const testBtn = container.querySelector('.script-test-btn');
    if (testBtn) {
        testBtn.addEventListener('click', async () => {
            try {
                testBtn.disabled = true;
                testBtn.textContent = '⏳ Testing...';
                
                // Get active tab
                const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
                if (!tab) {
                    throw new Error('No active tab');
                }
                
                // Send test message to content script
                const response = await chrome.tabs.sendMessage(tab.id, {
                    type: 'TEST_SCRIPT',
                    code: script.code,
                    actions: script.actions || []
                });
                
                if (response.success) {
                    testBtn.textContent = '✅ Test OK';
                } else {
                    throw new Error(response.error || 'Test failed');
                }
                
                setTimeout(() => {
                    testBtn.disabled = false;
                    testBtn.textContent = '▶️ Test on Page';
                }, 2000);
                
            } catch (error) {
                console.error('[Sidepanel] Test failed:', error);
                testBtn.textContent = '❌ Test Failed';
                setTimeout(() => {
                    testBtn.disabled = false;
                    testBtn.textContent = '▶️ Test on Page';
                }, 2000);
            }
        });
    }
    
    // Edit button - open in editor
    const editBtn = container.querySelector('.script-edit-btn');
    if (editBtn) {
        editBtn.addEventListener('click', () => {
            // Open editor popup with script data
            chrome.runtime.sendMessage({
                type: 'OPEN_SCRIPT_EDITOR',
                script: script
            });
        });
    }
}

function updateConversationInList(messagePreview) {
    if (!state.currentConversation) return;
    
    // Update title if it's still "New Chat"
    if (state.currentConversation.title === 'New Chat') {
        const newTitle = messagePreview.substring(0, 50) + (messagePreview.length > 50 ? '...' : '');
        state.currentConversation.title = newTitle;
        
        // Update in conversations list
        const conv = state.conversations.find(c => c.conversation_id === state.currentConversation.conversation_id);
        if (conv) {
            conv.title = newTitle;
            conv.updated_at = new Date().toISOString();
        }
        
        renderConversationList();
        
        // Update on server
        API.updateConversation(state.currentConversation.conversation_id, { title: newTitle }).catch(console.error);
    }
}

// ==================== Page Context ====================

/**
 * Clear OCR cache when starting a new chat.
 */
function clearOcrCache() {
    state.ocrCache = {};
}

/**
 * Clear pending image attachments for the next message.
 */
function clearImageAttachments() {
    state.pendingImages = [];
    renderImageAttachments();
    updateSendButton();
}

/**
 * Render the image attachment thumbnails.
 */
function renderImageAttachments() {
    if (!imageAttachmentsEl) return;
    if (state.pendingImages.length === 0) {
        imageAttachmentsEl.classList.add('hidden');
        imageAttachmentsEl.innerHTML = '';
        return;
    }

    imageAttachmentsEl.classList.remove('hidden');
    imageAttachmentsEl.innerHTML = state.pendingImages.map((img) => `
        <div class="image-attachment" data-id="${img.id}">
            <img src="${img.dataUrl}" alt="${img.name || 'attachment'}">
            <button class="remove-btn" aria-label="Remove image">×</button>
        </div>
    `).join('');

    imageAttachmentsEl.querySelectorAll('.remove-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const container = btn.closest('.image-attachment');
            const id = container?.getAttribute('data-id');
            if (!id) return;
            state.pendingImages = state.pendingImages.filter((img) => img.id !== id);
            renderImageAttachments();
            updateSendButton();
        });
    });
}

/**
 * Add image file(s) to pending attachments.
 * @param {FileList|File[]} files - Files dropped by the user.
 */
async function addImageFiles(files) {
    const maxAttachments = 5;
    const list = Array.from(files || []);
    for (const file of list) {
        if (!file.type.startsWith('image/')) continue;
        if (state.pendingImages.length >= maxAttachments) {
            alert(`You can attach up to ${maxAttachments} images per message.`);
            break;
        }
        const dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(file);
        });
        state.pendingImages.push({
            id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
            name: file.name,
            dataUrl
        });
    }
    renderImageAttachments();
    updateSendButton();
}

/**
 * Handle drag-and-drop images into the input area.
 * @param {DragEvent} e - Drop event.
 */
function handleImageDrop(e) {
    e.preventDefault();
    inputWrapper?.classList.remove('drag-over');
    const files = e.dataTransfer?.files || [];
    addImageFiles(files).catch((err) => {
        console.error('[Sidepanel] Failed to add images:', err);
    });
}

/**
 * Attach a screenshot of the current tab as page context.
 */
async function attachScreenshotFromPage() {
    try {
        const tabInfo = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.GET_TAB_INFO });
        const screenshotResponse = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.CAPTURE_SCREENSHOT });
        if (!screenshotResponse?.screenshot) {
            alert('Could not capture a screenshot.');
            return;
        }
        state.pageContext = {
            url: tabInfo?.url,
            title: tabInfo?.title,
            content: 'Screenshot attached for analysis.',
            screenshot: screenshotResponse.screenshot,
            isScreenshot: true
        };
        pageContextTitle.textContent = `📷 ${tabInfo?.title || 'Screenshot attached'}`;
        pageContextBar.classList.remove('hidden');
        attachPageBtn.classList.add('active');
    } catch (e) {
        console.error('[Sidepanel] Manual screenshot failed:', e);
        alert('Failed to capture screenshot.');
    }
}

/**
 * Attach a scrolling full-page screenshot and OCR content.
 */
async function attachScrollingScreenshotFromPage() {
    try {
        attachScrollshotBtn?.setAttribute('disabled', 'true');
        pageContextTitle.textContent = '🧾 Capturing scrolling screenshot...';
        pageContextBar.classList.remove('hidden');

        const tabInfo = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.GET_TAB_INFO });
        const ocrContext = await buildOcrPageContext({
            url: tabInfo?.url,
            title: tabInfo?.title
        });
        if (!ocrContext) {
            pageContextTitle.textContent = '🧾 Scrolling screenshot failed';
            alert('Could not capture scrolling screenshot or OCR text.');
            return;
        }
        state.pageContext = ocrContext;
        pageContextTitle.textContent = `🧾 ${tabInfo?.title || 'OCR attached'}`;
        pageContextBar.classList.remove('hidden');
        attachPageBtn.classList.add('active');
    } catch (e) {
        console.error('[Sidepanel] Scrolling screenshot failed:', e);
        pageContextTitle.textContent = '🧾 Scrolling screenshot failed';
        alert('Failed to capture scrolling screenshot.');
    } finally {
        attachScrollshotBtn?.removeAttribute('disabled');
    }
}

/**
 * Get cached OCR results for a URL.
 * @param {string} url - Page URL.
 * @returns {Object|null} Cached OCR entry if available.
 */
function getCachedOcr(url) {
    return url ? state.ocrCache[url] || null : null;
}

/**
 * Store OCR results for a URL.
 * @param {string} url - Page URL.
 * @param {Object} entry - OCR cache entry.
 */
function setCachedOcr(url, entry) {
    if (!url) return;
    state.ocrCache[url] = entry;
}

/**
 * Capture full-page screenshots by scrolling with overlap.
 * @param {Object} options - Capture options for overlap/delay.
 * @returns {Promise<Object|null>} Capture response with screenshots.
 */
async function captureFullPageScreenshots(options = {}) {
    const response = await chrome.runtime.sendMessage({
        type: MESSAGE_TYPES.CAPTURE_FULLPAGE_SCREENSHOTS,
        overlapRatio: options.overlapRatio ?? 0.1,
        delayMs: options.delayMs ?? 1000
    });
    if (!response || response.error) {
        console.warn('[Sidepanel] Full-page capture failed:', response?.error);
        return null;
    }
    return response;
}

/**
 * Attempt OCR-based page context for canvas-rendered apps.
 * @param {Object} extractResponse - Response from EXTRACT_PAGE.
 * @returns {Promise<Object|null>} Page context if OCR succeeded.
 */
async function buildOcrPageContext(extractResponse) {
    const cached = getCachedOcr(extractResponse.url);
    if (cached?.text) {
        return {
            url: extractResponse.url,
            title: extractResponse.title,
            content: cached.text,
            isOcr: true,
            ocrCached: true,
            ocrPages: cached.pages?.length || 0
        };
    }

    const capture = await captureFullPageScreenshots();
    if (!capture?.screenshots?.length) {
        return null;
    }

    pageContextTitle.textContent = '🧾 Running OCR...';
    pageContextBar.classList.remove('hidden');

    const ocrResult = await API.ocrScreenshots(capture.screenshots, {
        url: extractResponse.url,
        title: extractResponse.title
    });
    if (!ocrResult?.text) {
        return null;
    }

    setCachedOcr(extractResponse.url, {
        text: ocrResult.text,
        pages: ocrResult.pages,
        createdAt: Date.now()
    });

    return {
        url: extractResponse.url,
        title: extractResponse.title,
        content: ocrResult.text,
        isOcr: true,
        ocrCached: false,
        ocrPages: ocrResult.pages?.length || 0
    };
}

/**
 * Build pageContext from extraction response (text, OCR, or screenshot fallback).
 * @param {Object} response - Extract page response.
 * @param {Object} options - Behavior flags.
 * @returns {Promise<Object|null>} Page context object.
 */
async function buildPageContextFromResponse(response, options = {}) {
    const showAlerts = options.showAlerts ?? true;

    if (response.needsScreenshot || response.canvasApp) {
        console.log('[Sidepanel] Canvas app detected, attempting full-page OCR...');
        try {
            const ocrContext = await buildOcrPageContext(response);
            if (ocrContext) {
                return ocrContext;
            }
        } catch (e) {
            console.warn('[Sidepanel] OCR failed, falling back to screenshot:', e);
        }

        try {
            const screenshotResponse = await chrome.runtime.sendMessage({
                type: MESSAGE_TYPES.CAPTURE_SCREENSHOT
            });
            if (screenshotResponse && screenshotResponse.screenshot) {
                return {
                    url: response.url,
                    title: response.title,
                    content: response.instructions || '',
                    screenshot: screenshotResponse.screenshot,
                    isScreenshot: true
                };
            }
        } catch (screenshotError) {
            console.error('[Sidepanel] Screenshot failed:', screenshotError);
        }

        if (showAlerts) {
            alert(response.instructions || 'Could not extract content from this page. Try selecting text with Ctrl+A and then clicking attach again.');
        }
        return null;
    }

    return {
        url: response.url,
        title: response.title,
        content: response.content
    };
}

async function attachPageContent() {
    // If we already have multi-tab context, don't overwrite it
    if (state.pageContext?.isMultiTab) {
        console.log('[Sidepanel] attachPageContent skipped - multi-tab context exists');
        return;
    }
    
    try {
        attachPageBtn.classList.add('active');
        
        // Request page content from service worker
        const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXTRACT_PAGE });
        
        if (response && !response.error) {
            const context = await buildPageContextFromResponse(response, { showAlerts: true });
            if (!context) {
                attachPageBtn.classList.remove('active');
                return;
            }

            state.pageContext = context;
            const prefix = context.isOcr ? '🧾 ' : context.isScreenshot ? '📷 ' : '';
            pageContextTitle.textContent = `${prefix}${response.title || 'Page content attached'}`;
            pageContextBar.classList.remove('hidden');
        } else {
            alert('Could not extract page content');
            attachPageBtn.classList.remove('active');
        }
    } catch (error) {
        console.error('[Sidepanel] Failed to attach page:', error);
        alert('Failed to get page content');
        attachPageBtn.classList.remove('active');
    }
}

function removePageContext() {
    state.pageContext = null;
    state.multiTabContexts = [];
    state.selectedTabIds = [];
    pageContextBar.classList.add('hidden');
    attachPageBtn.classList.remove('active');
    multiTabBtn.classList.remove('active');
    updateMultiTabIndicator();
}

// ==================== Multi-Tab ====================

async function showTabModal() {
    console.log('[Sidepanel] showTabModal called');
    try {
        console.log('[Sidepanel] Sending GET_ALL_TABS message');
        const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.GET_ALL_TABS });
        console.log('[Sidepanel] GET_ALL_TABS response:', response);
        
        if (response && response.tabs) {
            // Determine which tabs should be pre-selected
            const preSelectedIds = state.selectedTabIds.length > 0 
                ? state.selectedTabIds 
                : response.tabs.filter(t => t.active).map(t => t.tabId);
            
            tabList.innerHTML = response.tabs.map(tab => {
                const isSelected = preSelectedIds.includes(tab.tabId);
                const tabUrl = tab.url || '';
                const isRestricted = !tabUrl || 
                                     tabUrl.startsWith('chrome://') || 
                                     tabUrl.startsWith('chrome-extension://') ||
                                     tabUrl.startsWith('about:') ||
                                     tabUrl.startsWith('edge://') ||
                                     tabUrl.startsWith('devtools://');
                const faviconHtml = tab.favIconUrl 
                    ? `<img class="tab-favicon" src="${tab.favIconUrl}" data-fallback="true">`
                    : `<span class="tab-favicon-placeholder">🌐</span>`;
                return `
                <li data-id="${tab.tabId}" class="${isRestricted ? 'restricted' : ''}">
                    <input type="checkbox" class="tab-checkbox" ${isSelected ? 'checked' : ''} ${isRestricted ? 'disabled' : ''}>
                    ${faviconHtml}
                    <div class="tab-info">
                        <div class="tab-title">${escapeHtml(tab.title || 'Untitled')}${tab.active ? ' (current)' : ''}</div>
                        <div class="tab-url">${escapeHtml(truncateUrl(tabUrl))}</div>
                    </div>
                </li>
            `}).join('');
            
            // Handle favicon load errors (CSP-safe)
            tabList.querySelectorAll('.tab-favicon[data-fallback]').forEach(img => {
                img.addEventListener('error', () => {
                    img.style.display = 'none';
                });
            });
            
            console.log('[Sidepanel] Showing tab modal');
            tabModal.classList.remove('hidden');
            console.log('[Sidepanel] Tab modal hidden class removed, current classes:', tabModal.className);
            updateTabSelectionCount();
            
            // Add listeners for checkbox changes
            tabList.querySelectorAll('.tab-checkbox').forEach(cb => {
                cb.addEventListener('change', updateTabSelectionCount);
            });
        } else {
            console.error('[Sidepanel] No tabs in response:', response);
        }
    } catch (error) {
        console.error('[Sidepanel] Failed to get tabs:', error);
        alert('Failed to get tabs list: ' + error.message);
    }
}

// Debug: Check DOM elements
console.log('[Sidepanel] DOM elements check:', {
    multiTabBtn: !!multiTabBtn,
    tabModal: !!tabModal,
    tabList: !!tabList,
    confirmTabModalBtn: !!confirmTabModalBtn
});

function truncateUrl(url) {
    if (!url) return '(no URL)';
    try {
        const u = new URL(url);
        const path = u.pathname.length > 30 ? u.pathname.substring(0, 30) + '...' : u.pathname;
        return u.hostname + path;
    } catch {
        return url.length > 50 ? url.substring(0, 50) + '...' : url;
    }
}

function updateTabSelectionCount() {
    try {
        const selected = tabList.querySelectorAll('.tab-checkbox:checked').length;
        console.log('[Sidepanel] Selected tabs count:', selected);
        if (confirmTabModalBtn) {
            confirmTabModalBtn.textContent = selected === 0 ? 'Select Tabs' : `Add ${selected} Tab${selected > 1 ? 's' : ''}`;
            confirmTabModalBtn.disabled = selected === 0;
        }
    } catch (e) {
        console.error('[Sidepanel] updateTabSelectionCount error:', e);
    }
}

async function handleTabSelection() {
    console.log('[Sidepanel] handleTabSelection called');
    const selectedLis = Array.from(tabList.querySelectorAll('li'))
        .filter(li => li.querySelector('.tab-checkbox:checked'));
    
    const selectedTabs = selectedLis.map(li => ({
        tabId: parseInt(li.dataset.id),
        title: li.querySelector('.tab-title')?.textContent?.replace(' (current)', '') || 'Untitled'
    }));
    
    console.log('[Sidepanel] Selected tabs:', selectedTabs);
    tabModal.classList.add('hidden');
    
    if (selectedTabs.length === 0) {
        // Clear multi-tab context
        state.selectedTabIds = [];
        state.multiTabContexts = [];
        multiTabBtn.classList.remove('active');
        updateMultiTabIndicator();
        return;
    }
    
    // Show loading state
    multiTabBtn.disabled = true;
    multiTabBtn.innerHTML = `
        <svg class="spin" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" stroke-dasharray="31.4" stroke-dashoffset="10"></circle>
        </svg>
    `;
    
    // Extract content from all selected tabs
    console.log('[Sidepanel] Starting extraction from', selectedTabs.length, 'tabs');
    const contexts = [];
    for (const tab of selectedTabs) {
        try {
            console.log('[Sidepanel] Extracting from tab:', tab.tabId, tab.title);
            const response = await chrome.runtime.sendMessage({ 
                type: MESSAGE_TYPES.EXTRACT_FROM_TAB, 
                tabId: tab.tabId 
            });
            console.log('[Sidepanel] Extraction response for tab', tab.tabId, ':', response?.content?.length || 0, 'chars');
            
            if (response && !response.error) {
                contexts.push({
                    tabId: tab.tabId,
                    url: response.url,
                    title: response.title || tab.title,
                    content: response.content || '',
                    length: response.length || 0
                });
            } else {
                console.warn('[Sidepanel] Extraction error for tab', tab.tabId, ':', response?.error);
                contexts.push({
                    tabId: tab.tabId,
                    url: response?.url || '',
                    title: tab.title,
                    content: `[Could not extract: ${response?.error || 'unknown error'}]`,
                    length: 0,
                    error: true
                });
            }
        } catch (e) {
            console.error(`[Sidepanel] Failed to extract from tab ${tab.tabId}:`, e);
            contexts.push({
                tabId: tab.tabId,
                url: '',
                title: tab.title,
                content: '[Extraction failed]',
                length: 0,
                error: true
            });
        }
    }
    console.log('[Sidepanel] Extraction complete. Contexts:', contexts.length);
    
    state.selectedTabIds = selectedTabs.map(t => t.tabId);
    state.multiTabContexts = contexts;
    
    // Restore button
    multiTabBtn.disabled = false;
    multiTabBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2"></rect>
            <path d="M3 9h18M9 3v18"></path>
        </svg>
    `;
    multiTabBtn.classList.add('active');
    
    updateMultiTabIndicator();
    
    // Also update pageContext with combined content for backwards compatibility
    if (contexts.length > 0) {
        const combinedContent = contexts.map(c => 
            `## Tab: ${c.title}\nURL: ${c.url}\n\n${c.content}`
        ).join('\n\n---\n\n');
        
        console.log('[Sidepanel] Combined content length:', combinedContent.length);
        console.log('[Sidepanel] First 500 chars of combined:', combinedContent.substring(0, 500));
        
        state.pageContext = {
            url: contexts.length === 1 ? contexts[0].url : 'Multiple tabs',
            title: contexts.length === 1 ? contexts[0].title : `${contexts.length} tabs`,
            content: combinedContent,
            isMultiTab: true,
            tabCount: contexts.length
        };
        
        console.log('[Sidepanel] pageContext set with', contexts.length, 'tabs, isMultiTab:', state.pageContext.isMultiTab);
        
        pageContextTitle.textContent = `📑 ${contexts.length} tab${contexts.length > 1 ? 's' : ''} attached`;
        pageContextBar.classList.remove('hidden');
        attachPageBtn.classList.add('active');
    }
}

function updateMultiTabIndicator() {
    const count = state.multiTabContexts.length;
    if (count > 0) {
        multiTabBtn.title = `${count} tab${count > 1 ? 's' : ''} selected`;
    } else {
        multiTabBtn.title = 'Read from multiple tabs';
    }
}

// ==================== Quick Suggestions ====================

async function handleQuickSuggestion(action) {
    if (!state.currentConversation) {
        await createNewConversation();
    }
    
    switch (action) {
        case 'summarize':
            await attachPageContent();
            messageInput.value = 'Please summarize this page.';
            handleInputChange();
            // Auto-send after a brief moment for page content to attach
            setTimeout(() => {
                sendMessage();
            }, 100);
            break;
        case 'explain':
            messageInput.value = 'Please explain the selected text.';
            handleInputChange();
            messageInput.focus();
            break;
        case 'ask':
            messageInput.focus();
            break;
    }
}

// ==================== Runtime Messages ====================

async function handleRuntimeMessage(message, sender, sendResponse) {
    console.log('[Sidepanel] Received message:', message.type);
    
    switch (message.type) {
        case MESSAGE_TYPES.ADD_TO_CHAT:
            // Set page context first if provided, but don't overwrite multi-tab context
            if (message.pageUrl && message.pageTitle && !state.pageContext?.isMultiTab) {
                // First extract actual page content
                try {
                    const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXTRACT_PAGE });
                    if (response && !response.error) {
                        state.pageContext = {
                            url: response.url || message.pageUrl,
                            title: response.title || message.pageTitle,
                            content: response.content || ''
                        };
                    } else {
                        state.pageContext = {
                            url: message.pageUrl,
                            title: message.pageTitle,
                            content: message.text || ''
                        };
                    }
                } catch (e) {
                    state.pageContext = {
                        url: message.pageUrl,
                        title: message.pageTitle,
                        content: message.text || ''
                    };
                }
                pageContextTitle.textContent = state.pageContext.title;
                pageContextBar.classList.remove('hidden');
                attachPageBtn.classList.add('active');
            } else if (state.pageContext?.isMultiTab) {
                console.log('[Sidepanel] ADD_TO_CHAT skipped page context - multi-tab exists');
            }
            
            // Set message text
            if (message.text) {
                messageInput.value = message.text;
                handleInputChange();
            }
            
            // Auto-send if action is summarize or other quick action
            if (message.action === 'summarize' || message.action === 'explain') {
                // Wait a brief moment for UI to update, then send
                setTimeout(() => {
                    sendMessage();
                }, 100);
            }
            break;
            
        case 'TAB_CHANGED':
        case 'TAB_UPDATED':
            // Could refresh page context indicator
            break;
    }
}

// ==================== Utilities ====================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatTimeAgo(timestamp) {
    if (!timestamp) return '';
    
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'now';
    if (diffMins < 60) return `${diffMins}m`;
    if (diffHours < 24) return `${diffHours}h`;
    if (diffDays < 7) return `${diffDays}d`;
    
    return date.toLocaleDateString();
}

// ==================== Start ====================

// Configure marked if available
if (window.marked) {
    marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
    });
}

initialize();

