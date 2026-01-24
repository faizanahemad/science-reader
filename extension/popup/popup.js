/**
 * Popup Script for AI Assistant Chrome Extension
 * 
 * Handles:
 * - Authentication (login/logout)
 * - Quick actions (summarize page, open sidepanel)
 * - Recent conversations display
 * - Settings management
 */

import { API } from '../shared/api.js';
import { Storage } from '../shared/storage.js';
import { MODELS, MESSAGE_TYPES } from '../shared/constants.js';

// ==================== DOM Elements ====================

const views = {
    loading: document.getElementById('loading-view'),
    login: document.getElementById('login-view'),
    main: document.getElementById('main-view'),
    settings: document.getElementById('settings-view')
};

// Login elements
const loginForm = document.getElementById('login-form');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
const serverUrlInput = document.getElementById('server-url');
const loginBtn = document.getElementById('login-btn');
const loginError = document.getElementById('login-error');

// Main view elements
const openSidepanelBtn = document.getElementById('open-sidepanel');
const summarizePageBtn = document.getElementById('summarize-page');
const askSelectionBtn = document.getElementById('ask-selection');
const recentList = document.getElementById('recent-list');
const recentEmpty = document.getElementById('recent-empty');
const userEmailSpan = document.getElementById('user-email');
const logoutBtn = document.getElementById('logout-btn');
const settingsBtn = document.getElementById('settings-btn');

// Settings elements
const backToMainBtn = document.getElementById('back-to-main');
const defaultModelSelect = document.getElementById('default-model');
const defaultPromptSelect = document.getElementById('default-prompt');
const serverUrlSettingsInput = document.getElementById('server-url-settings');
const historyLengthInput = document.getElementById('history-length');
const historyLengthValue = document.getElementById('history-length-value');
const autoSaveCheckbox = document.getElementById('auto-save');
const themeSelect = document.getElementById('theme');
const saveSettingsBtn = document.getElementById('save-settings');

// ==================== View Management ====================

function showView(viewName) {
    Object.entries(views).forEach(([name, element]) => {
        element.classList.toggle('hidden', name !== viewName);
    });
}

/**
 * Normalize API base URL input to avoid trailing slashes.
 * @param {string} value
 * @returns {string}
 */
function normalizeApiBaseUrl(value) {
    return (value || '').trim().replace(/\/+$/, '');
}

/**
 * Sync server URL inputs between login and settings.
 * @param {string} value
 */
function syncServerUrlInputs(value) {
    if (serverUrlInput) serverUrlInput.value = value;
    if (serverUrlSettingsInput) serverUrlSettingsInput.value = value;
}

/**
 * Load server URL from storage into UI.
 * @returns {Promise<void>}
 */
async function loadServerUrlSetting() {
    const stored = await Storage.getApiBaseUrl();
    const normalized = normalizeApiBaseUrl(stored);
    syncServerUrlInputs(normalized);
}

/**
 * Persist server URL to storage and update UI.
 * @param {string} value
 * @returns {Promise<void>}
 */
async function persistServerUrlSetting(value) {
    const normalized = normalizeApiBaseUrl(value);
    if (!normalized) return;
    syncServerUrlInputs(normalized);
    await Storage.setApiBaseUrl(normalized);
}

// ==================== Initialization ====================

async function initialize() {
    console.log('[Popup] Initializing...');
    
    try {
        await loadServerUrlSetting();
        // Check if user is authenticated
        const isAuth = await Storage.isAuthenticated();
        
        if (isAuth) {
            // Verify token is still valid
            const result = await API.verifyAuth();
            if (result.valid) {
                await showMainView();
            } else {
                await Storage.clearAuth();
                showView('login');
            }
        } else {
            showView('login');
        }
    } catch (error) {
        console.error('[Popup] Initialization error:', error);
        showView('login');
    }
}

async function showMainView() {
    // Load user info
    const userInfo = await Storage.getUserInfo();
    if (userInfo) {
        userEmailSpan.textContent = userInfo.email;
    }
    
    // Load recent conversations
    await loadRecentConversations();
    
    showView('main');
}

async function loadRecentConversations() {
    const recent = await Storage.getRecentConversations();
    
    if (recent.length === 0) {
        recentList.classList.add('hidden');
        recentEmpty.classList.remove('hidden');
        return;
    }
    
    recentList.classList.remove('hidden');
    recentEmpty.classList.add('hidden');
    
    recentList.innerHTML = recent.map(conv => `
        <li data-id="${conv.id}">
            <span class="conv-icon">💬</span>
            <span class="conv-title">${escapeHtml(conv.title)}</span>
            <span class="conv-time">${formatTimeAgo(conv.updatedAt)}</span>
        </li>
    `).join('');
}

// ==================== Event Handlers ====================

// Login form submission
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const email = emailInput.value.trim();
    const password = passwordInput.value;
    const serverUrl = serverUrlInput?.value || '';
    
    if (!email || !password) return;
    
    // Show loading state
    loginBtn.disabled = true;
    loginBtn.querySelector('.btn-text').classList.add('hidden');
    loginBtn.querySelector('.btn-loading').classList.remove('hidden');
    loginError.classList.add('hidden');
    
    try {
        if (serverUrl) {
            await persistServerUrlSetting(serverUrl);
        }
        await API.login(email, password);
        await showMainView();
    } catch (error) {
        console.error('[Popup] Login failed:', error);
        loginError.textContent = error.message || 'Login failed. Please try again.';
        loginError.classList.remove('hidden');
    } finally {
        loginBtn.disabled = false;
        loginBtn.querySelector('.btn-text').classList.remove('hidden');
        loginBtn.querySelector('.btn-loading').classList.add('hidden');
    }
});

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

// Open sidepanel
openSidepanelBtn.addEventListener('click', async () => {
    try {
        await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.OPEN_SIDEPANEL });
        window.close(); // Close popup after opening sidepanel
    } catch (error) {
        console.error('[Popup] Failed to open sidepanel:', error);
    }
});

// Summarize page
summarizePageBtn.addEventListener('click', async () => {
    try {
        // Get current tab info
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        
        // Open sidepanel and send summarize action
        await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.OPEN_SIDEPANEL });
        
        // Wait a bit for sidepanel to open, then send action
        setTimeout(() => {
            chrome.runtime.sendMessage({
                type: MESSAGE_TYPES.ADD_TO_CHAT,
                text: `Please summarize this page: ${tab.title}`,
                pageUrl: tab.url,
                pageTitle: tab.title,
                action: 'summarize'
            });
        }, 500);
        
        window.close();
    } catch (error) {
        console.error('[Popup] Summarize page failed:', error);
    }
});

// Ask about selection
askSelectionBtn.addEventListener('click', async () => {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        
        // Get selected text from content script
        const response = await chrome.tabs.sendMessage(tab.id, { 
            type: MESSAGE_TYPES.GET_SELECTION 
        });
        
        if (response && response.text) {
            await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.OPEN_SIDEPANEL });
            
            setTimeout(() => {
                chrome.runtime.sendMessage({
                    type: MESSAGE_TYPES.ADD_TO_CHAT,
                    text: response.text,
                    pageUrl: tab.url,
                    pageTitle: tab.title
                });
            }, 500);
            
            window.close();
        } else {
            alert('Please select some text on the page first.');
        }
    } catch (error) {
        console.error('[Popup] Ask selection failed:', error);
        alert('Could not get selection. Make sure you have text selected on the page.');
    }
});

// Recent conversation click
recentList.addEventListener('click', async (e) => {
    const li = e.target.closest('li');
    if (!li) return;
    
    const convId = li.dataset.id;
    await Storage.setCurrentConversation(convId);
    
    await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.OPEN_SIDEPANEL });
    window.close();
});

// Logout
logoutBtn.addEventListener('click', async () => {
    try {
        await API.logout();
        showView('login');
        emailInput.value = '';
        passwordInput.value = '';
    } catch (error) {
        console.error('[Popup] Logout failed:', error);
    }
});

// Settings button
settingsBtn.addEventListener('click', () => {
    loadSettings();
    showView('settings');
});

// Back from settings
backToMainBtn.addEventListener('click', () => {
    showView('main');
});

// History length slider
historyLengthInput.addEventListener('input', (e) => {
    historyLengthValue.textContent = e.target.value;
});

// Save settings
saveSettingsBtn.addEventListener('click', async () => {
    const normalizedServerUrl = normalizeApiBaseUrl(serverUrlSettingsInput?.value || '');
    const settings = {
        defaultModel: defaultModelSelect.value,
        defaultPrompt: defaultPromptSelect.value,
        historyLength: parseInt(historyLengthInput.value),
        autoSave: autoSaveCheckbox.checked,
        theme: themeSelect.value,
        apiBaseUrl: normalizedServerUrl
    };
    
    try {
        await Storage.setSettings(settings);
        if (normalizedServerUrl) {
            await Storage.setApiBaseUrl(normalizedServerUrl);
        }
        
        // Also save to server
        try {
            await API.updateSettings(settings);
        } catch (e) {
            console.warn('[Popup] Failed to sync settings to server:', e);
        }
        
        showView('main');
    } catch (error) {
        console.error('[Popup] Failed to save settings:', error);
    }
});

// ==================== Settings Loading ====================

async function loadSettings() {
    // Fetch models from server
    try {
        const modelsData = await API.getModels();
        if (modelsData.models && modelsData.models.length > 0) {
            defaultModelSelect.innerHTML = modelsData.models.map(m => 
                `<option value="${m.id}">${m.name}</option>`
            ).join('');
        } else {
            // Fallback to constants
            defaultModelSelect.innerHTML = MODELS.map(m => 
                `<option value="${m.id}">${m.name}</option>`
            ).join('');
        }
    } catch (e) {
        console.warn('[Popup] Failed to load models from server:', e);
        defaultModelSelect.innerHTML = MODELS.map(m => 
            `<option value="${m.id}">${m.name}</option>`
        ).join('');
    }
    
    // Populate prompt dropdown
    try {
        const promptsData = await API.getPrompts();
        if (promptsData.prompts) {
            defaultPromptSelect.innerHTML = promptsData.prompts.map(p => 
                `<option value="${p.name}">${p.name}</option>`
            ).join('');
        }
    } catch (e) {
        console.warn('[Popup] Failed to load prompts:', e);
        defaultPromptSelect.innerHTML = '<option value="preamble_short">preamble_short</option>';
    }
    
    // Load current settings
    const settings = await Storage.getSettings();
    
    defaultModelSelect.value = settings.defaultModel;
    defaultPromptSelect.value = settings.defaultPrompt;
    if (serverUrlSettingsInput) {
        serverUrlSettingsInput.value = settings.apiBaseUrl || '';
    }
    if (!defaultPromptSelect.value && defaultPromptSelect.options.length > 0) {
        defaultPromptSelect.value = defaultPromptSelect.options[0].value;
    }
    historyLengthInput.value = settings.historyLength;
    historyLengthValue.textContent = settings.historyLength;
    autoSaveCheckbox.checked = settings.autoSave;
    themeSelect.value = settings.theme;
}

// ==================== Utility Functions ====================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    
    return date.toLocaleDateString();
}

// ==================== Start ====================

initialize();

