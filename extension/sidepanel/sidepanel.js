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
    settings: {
        model: 'google/gemini-2.5-flash',
        promptName: 'Short',
        historyLength: 10,
        autoIncludePage: true  // Enabled by default
    },
    abortController: null,
    availableModels: [] // Fetched from server
};

// ==================== DOM Elements ====================

// Views
const loginView = document.getElementById('login-view');
const mainView = document.getElementById('main-view');

// Login
const loginForm = document.getElementById('login-form');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
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
const historyLengthSlider = document.getElementById('history-length-slider');
const historyValue = document.getElementById('history-value');
const autoIncludePageCheckbox = document.getElementById('auto-include-page');
const settingsUserEmail = document.getElementById('settings-user-email');
const logoutBtn = document.getElementById('logout-btn');

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
const multiTabBtn = document.getElementById('multi-tab-btn');
const voiceBtn = document.getElementById('voice-btn');
const messageInput = document.getElementById('message-input');
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

async function initialize() {
    console.log('[Sidepanel] Initializing...');
    
    try {
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
    
    // Sidebar
    toggleSidebarBtn.addEventListener('click', () => toggleSidebar(true));
    closeSidebarBtn.addEventListener('click', () => toggleSidebar(false));
    sidebarOverlay.addEventListener('click', () => toggleSidebar(false));
    sidebarNewChatBtn.addEventListener('click', () => {
        toggleSidebar(false);
        createNewConversation();
    });
    
    // Settings
    settingsBtn.addEventListener('click', () => toggleSettings(true));
    closeSettingsBtn.addEventListener('click', () => toggleSettings(false));
    logoutBtn.addEventListener('click', handleLogout);
    
    // Settings controls
    modelSelect.addEventListener('change', () => {
        state.settings.model = modelSelect.value;
        saveSettings();
    });
    
    promptSelect.addEventListener('change', () => {
        state.settings.promptName = promptSelect.value;
        saveSettings();
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
    
    // Conversation list delegation
    conversationList.addEventListener('click', handleConversationClick);
}

// ==================== Login ====================

async function handleLogin(e) {
    e.preventDefault();
    
    const email = emailInput.value.trim();
    const password = passwordInput.value;
    
    if (!email || !password) return;
    
    const loginBtn = document.getElementById('login-btn');
    loginBtn.disabled = true;
    loginBtn.textContent = 'Signing in...';
    loginError.classList.add('hidden');
    
    try {
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
}

// ==================== Settings ====================

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
        promptSelect.innerHTML = '<option value="Short">Short</option>';
    }
    
    // Load saved settings
    const savedSettings = await Storage.getSettings();
    state.settings = { ...state.settings, ...savedSettings };
    
    // Apply to UI
    modelSelect.value = state.settings.defaultModel || state.settings.model;
    promptSelect.value = state.settings.defaultPrompt || state.settings.promptName;
    historyLengthSlider.value = state.settings.historyLength;
    historyValue.textContent = state.settings.historyLength;
    // Default to true if not explicitly set to false
    autoIncludePageCheckbox.checked = state.settings.autoIncludePage !== false;
}

async function saveSettings() {
    await Storage.setSettings({
        defaultModel: state.settings.model,
        defaultPrompt: state.settings.promptName,
        historyLength: state.settings.historyLength,
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
        
    } catch (error) {
        console.error('[Sidepanel] Failed to create conversation:', error);
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
    sendBtn.disabled = !messageInput.value.trim() || state.isStreaming;
}

// ==================== Send Message ====================

async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text || state.isStreaming) return;
    
    // Ensure we have a conversation
    if (!state.currentConversation) {
        await createNewConversation();
    }
    
    // Auto-attach page content if enabled and not already attached
    // Skip if we already have multi-tab context - don't overwrite it!
    if (state.settings.autoIncludePage && !state.pageContext) {
        console.log('[Sidepanel] Auto-attaching page content (no existing context)');
        try {
            const response = await chrome.runtime.sendMessage({ type: MESSAGE_TYPES.EXTRACT_PAGE });
            if (response && !response.error && response.content) {
                // Check if we need screenshot fallback
                if (response.needsScreenshot || response.canvasApp) {
                    try {
                        const screenshotResponse = await chrome.runtime.sendMessage({ 
                            type: MESSAGE_TYPES.CAPTURE_SCREENSHOT 
                        });
                        if (screenshotResponse && screenshotResponse.screenshot) {
                            state.pageContext = {
                                url: response.url,
                                title: response.title,
                                content: response.instructions || '',
                                screenshot: screenshotResponse.screenshot,
                                isScreenshot: true
                            };
                        }
                    } catch (e) {
                        console.warn('[Sidepanel] Screenshot capture failed:', e);
                    }
                } else {
                    state.pageContext = {
                        url: response.url,
                        title: response.title,
                        content: response.content
                    };
                    console.log('[Sidepanel] Auto-attached single page:', response.title, response.content?.length);
                }
                
                if (state.pageContext) {
                    pageContextTitle.textContent = state.pageContext.title || 'Page content';
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
        content: text,
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
        
        await API.sendMessageStreaming(
            state.currentConversation.conversation_id,
            {
                message: text,
                pageContext: state.pageContext,
                model: state.settings.model
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
                    updateConversationInList(text);
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
            // Check if we need to fall back to screenshot
            if (response.needsScreenshot || response.canvasApp) {
                console.log('[Sidepanel] Canvas app detected, attempting screenshot...');
                
                // Try to capture screenshot
                try {
                    const screenshotResponse = await chrome.runtime.sendMessage({ 
                        type: MESSAGE_TYPES.CAPTURE_SCREENSHOT 
                    });
                    
                    if (screenshotResponse && screenshotResponse.screenshot) {
                        state.pageContext = {
                            url: response.url,
                            title: response.title,
                            content: response.instructions || '',
                            screenshot: screenshotResponse.screenshot,
                            isScreenshot: true
                        };
                        
                        pageContextTitle.textContent = `📷 ${response.title || 'Screenshot captured'}`;
                        pageContextBar.classList.remove('hidden');
                        return;
                    }
                } catch (screenshotError) {
                    console.error('[Sidepanel] Screenshot failed:', screenshotError);
                }
                
                // If screenshot failed, show instructions
                alert(response.instructions || 'Could not extract content from this page. Try selecting text with Ctrl+A and then clicking attach again.');
                attachPageBtn.classList.remove('active');
                return;
            }
            
            state.pageContext = {
                url: response.url,
                title: response.title,
                content: response.content
            };
            
            pageContextTitle.textContent = response.title || 'Page content attached';
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

