/**
 * Constants for the AI Assistant Chrome Extension
 * 
 * Centralizes configuration values used across all extension components
 * (popup, sidepanel, content scripts, service worker).
 */

// API Configuration
export const API_BASE = 'http://localhost:5001';

// Available LLM Models - fetched from server, this is fallback
// Names shown in UI use short format (part after /)
export const MODELS = [
    { id: 'google/gemini-2.5-flash', name: 'gemini-2.5-flash', provider: 'Google', default: true },
    { id: 'anthropic/claude-sonnet-4.5', name: 'claude-sonnet-4.5', provider: 'Anthropic' },
    { id: 'anthropic/claude-opus-4.5', name: 'claude-opus-4.5', provider: 'Anthropic' },
    { id: 'openai/gpt-5.2', name: 'gpt-5.2', provider: 'OpenAI' },
    { id: 'google/gemini-3-pro-preview', name: 'gemini-3-pro-preview', provider: 'Google' }
];

// Quick Actions for context menu
export const QUICK_ACTIONS = [
    { id: 'explain', name: 'Explain', icon: '💡', description: 'Explain the selected text' },
    { id: 'summarize', name: 'Summarize', icon: '📝', description: 'Summarize the selected text' },
    { id: 'critique', name: 'Critique', icon: '🔍', description: 'Provide critical analysis' },
    { id: 'expand', name: 'Expand', icon: '📖', description: 'Expand on the topic' },
    { id: 'eli5', name: 'ELI5', icon: '🧒', description: 'Explain like I\'m 5' },
    { id: 'translate', name: 'Translate', icon: '🌐', description: 'Translate the text' }
];

// Default Settings
export const DEFAULT_SETTINGS = {
    defaultModel: 'google/gemini-2.5-flash',
    defaultPrompt: 'preamble_short',
    defaultAgent: 'None',
    defaultWorkflowId: null,
    historyLength: 10,
    apiBaseUrl: API_BASE,
    autoSave: false,
    autoIncludePage: true, // Auto-include page content with every message
    theme: 'system' // 'light', 'dark', or 'system'
};

// Storage Keys
export const STORAGE_KEYS = {
    AUTH_TOKEN: 'authToken',
    USER_INFO: 'userInfo',
    SETTINGS: 'settings',
    CURRENT_CONVERSATION: 'currentConversation',
    RECENT_CONVERSATIONS: 'recentConversations'
};

// Message Types for chrome.runtime messaging
export const MESSAGE_TYPES = {
    // Auth
    AUTH_STATE_CHANGED: 'AUTH_STATE_CHANGED',
    
    // Page extraction
    EXTRACT_PAGE: 'EXTRACT_PAGE',
    GET_SELECTION: 'GET_SELECTION',
    CAPTURE_SCREENSHOT: 'CAPTURE_SCREENSHOT',
    CAPTURE_FULLPAGE_SCREENSHOTS: 'CAPTURE_FULLPAGE_SCREENSHOTS',
    GET_PAGE_METRICS: 'GET_PAGE_METRICS',
    SCROLL_TO: 'SCROLL_TO',
    
    // Capture context (inner scroll container support)
    INIT_CAPTURE_CONTEXT: 'INIT_CAPTURE_CONTEXT',
    SCROLL_CONTEXT_TO: 'SCROLL_CONTEXT_TO',
    GET_CONTEXT_METRICS: 'GET_CONTEXT_METRICS',
    RELEASE_CAPTURE_CONTEXT: 'RELEASE_CAPTURE_CONTEXT',
    
    // Sidepanel
    OPEN_SIDEPANEL: 'OPEN_SIDEPANEL',
    ADD_TO_CHAT: 'ADD_TO_CHAT',
    
    // Quick actions
    QUICK_ACTION: 'QUICK_ACTION',
    SHOW_MODAL: 'SHOW_MODAL',
    HIDE_MODAL: 'HIDE_MODAL',
    
    // Tab info
    GET_TAB_INFO: 'GET_TAB_INFO',
    GET_ALL_TABS: 'GET_ALL_TABS',
    EXTRACT_FROM_TAB: 'EXTRACT_FROM_TAB'
};

// UI Constants
export const UI = {
    SIDEPANEL_WIDTH: 400,
    MODAL_MAX_WIDTH: 500,
    FLOATING_BUTTON_SIZE: 48,
    ANIMATION_DURATION: 200
};

// Timeouts
export const TIMEOUTS = {
    API_REQUEST: 30000,
    STREAMING_FIRST_CHUNK: 10000,
    TOKEN_REFRESH_BUFFER: 300000 // 5 minutes before expiry
};

