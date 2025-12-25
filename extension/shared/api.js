/**
 * API Client for Extension Server
 * 
 * Provides methods for communicating with extension_server.py.
 * Handles authentication headers, error handling, and streaming responses.
 */

import { API_BASE, TIMEOUTS } from './constants.js';
import { Storage } from './storage.js';

/**
 * Custom error for authentication failures
 */
export class AuthError extends Error {
    constructor(message = 'Authentication required') {
        super(message);
        this.name = 'AuthError';
    }
}

/**
 * Main API object with methods for all endpoints
 */
export const API = {
    /**
     * Make an authenticated API call
     * @param {string} endpoint - API endpoint (e.g., '/ext/conversations')
     * @param {Object} options - Fetch options
     * @returns {Promise<Object>} - JSON response
     * @throws {AuthError} - If authentication fails
     * @throws {Error} - For other errors
     */
    async call(endpoint, options = {}) {
        const token = await Storage.getToken();
        
        const headers = {
            'Content-Type': 'application/json',
            ...(token && { 'Authorization': `Bearer ${token}` }),
            ...options.headers
        };

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), TIMEOUTS.API_REQUEST);

        try {
            const response = await fetch(`${API_BASE}${endpoint}`, {
                ...options,
                headers,
                signal: controller.signal
            });

            clearTimeout(timeout);

            if (response.status === 401) {
                await Storage.clearAuth();
                throw new AuthError('Token expired or invalid');
            }

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.error || `HTTP ${response.status}`);
            }

            return response.json();
        } catch (error) {
            clearTimeout(timeout);
            if (error.name === 'AbortError') {
                throw new Error('Request timeout');
            }
            throw error;
        }
    },

    /**
     * Make a streaming API call
     * @param {string} endpoint - API endpoint
     * @param {Object} body - Request body
     * @param {Function} onChunk - Callback for each chunk
     * @param {Function} onDone - Callback when streaming completes
     * @param {Function} onError - Callback for errors
     * @returns {Promise<void>}
     */
    async stream(endpoint, body, { onChunk, onDone, onError }) {
        const token = await Storage.getToken();

        try {
            const response = await fetch(`${API_BASE}${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token && { 'Authorization': `Bearer ${token}` })
                },
                body: JSON.stringify({ ...body, stream: true })
            });

            if (response.status === 401) {
                await Storage.clearAuth();
                throw new AuthError('Token expired or invalid');
            }

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.error || `HTTP ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                
                if (done) {
                    if (onDone) onDone();
                    break;
                }

                buffer += decoder.decode(value, { stream: true });

                // Parse Server-Sent Events format
                const lines = buffer.split('\n');
                buffer = lines.pop() || ''; // Keep incomplete line in buffer

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            if (data.chunk && onChunk) {
                                onChunk(data.chunk);
                            }
                            if (data.done && onDone) {
                                onDone(data);
                            }
                            if (data.error && onError) {
                                onError(new Error(data.error));
                            }
                        } catch (e) {
                            console.warn('Failed to parse SSE data:', line);
                        }
                    }
                }
            }
        } catch (error) {
            if (onError) onError(error);
            else throw error;
        }
    },

    // ==================== Auth Methods ====================

    /**
     * Login with email and password
     * @param {string} email
     * @param {string} password
     * @returns {Promise<{token: string, email: string, name: string}>}
     */
    async login(email, password) {
        const result = await this.call('/ext/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password })
        });
        
        // Store token and user info
        await Storage.setToken(result.token);
        await Storage.setUserInfo({ email: result.email, name: result.name });
        
        return result;
    },

    /**
     * Logout
     * @returns {Promise<void>}
     */
    async logout() {
        try {
            await this.call('/ext/auth/logout', { method: 'POST' });
        } catch (e) {
            // Ignore errors, clear local state anyway
        }
        await Storage.clearAuth();
    },

    /**
     * Verify if current token is valid
     * @returns {Promise<{valid: boolean, email?: string}>}
     */
    async verifyAuth() {
        try {
            return await this.call('/ext/auth/verify', { method: 'POST' });
        } catch (e) {
            return { valid: false };
        }
    },

    // ==================== Prompts Methods ====================

    /**
     * Get all available prompts
     * @returns {Promise<{prompts: Array}>}
     */
    async getPrompts() {
        return this.call('/ext/prompts');
    },

    /**
     * Get a specific prompt by name
     * @param {string} name - Prompt name
     * @returns {Promise<Object>}
     */
    async getPrompt(name) {
        return this.call(`/ext/prompts/${encodeURIComponent(name)}`);
    },

    // ==================== Memories Methods ====================

    /**
     * List user's memories
     * @param {Object} params - Query parameters
     * @returns {Promise<{memories: Array, total: number}>}
     */
    async getMemories(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.call(`/ext/memories${query ? '?' + query : ''}`);
    },

    /**
     * Search memories
     * @param {string} query - Search query
     * @param {number} k - Number of results
     * @returns {Promise<{results: Array}>}
     */
    async searchMemories(query, k = 10) {
        return this.call('/ext/memories/search', {
            method: 'POST',
            body: JSON.stringify({ query, k })
        });
    },

    /**
     * Get pinned memories
     * @returns {Promise<{memories: Array}>}
     */
    async getPinnedMemories() {
        return this.call('/ext/memories/pinned');
    },

    // ==================== Conversations Methods ====================

    /**
     * List conversations
     * @param {Object} params - Query parameters (limit, offset, include_temporary)
     * @returns {Promise<{conversations: Array, total: number}>}
     */
    async getConversations(params = { limit: 50 }) {
        const query = new URLSearchParams(params).toString();
        return this.call(`/ext/conversations?${query}`);
    },

    /**
     * Create a new conversation
     * @param {Object} data - Conversation data
     * @returns {Promise<{conversation: Object}>}
     */
    async createConversation(data = {}) {
        return this.call('/ext/conversations', {
            method: 'POST',
            body: JSON.stringify({
                title: data.title || 'New Chat',
                is_temporary: data.is_temporary !== false,
                model: data.model,
                prompt_name: data.prompt_name,
                history_length: data.history_length
            })
        });
    },

    /**
     * Get a conversation with messages
     * @param {string} id - Conversation ID
     * @returns {Promise<{conversation: Object}>}
     */
    async getConversation(id) {
        return this.call(`/ext/conversations/${id}`);
    },

    /**
     * Update conversation metadata
     * @param {string} id - Conversation ID
     * @param {Object} data - Fields to update
     * @returns {Promise<{conversation: Object}>}
     */
    async updateConversation(id, data) {
        return this.call(`/ext/conversations/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    },

    /**
     * Delete a conversation
     * @param {string} id - Conversation ID
     * @returns {Promise<void>}
     */
    async deleteConversation(id) {
        return this.call(`/ext/conversations/${id}`, {
            method: 'DELETE'
        });
    },

    /**
     * Save a conversation (mark as non-temporary)
     * @param {string} id - Conversation ID
     * @returns {Promise<{conversation: Object, message: string}>}
     */
    async saveConversation(id) {
        return this.call(`/ext/conversations/${id}/save`, {
            method: 'POST'
        });
    },

    // ==================== Chat Methods ====================

    /**
     * Send a message (non-streaming)
     * @param {string} conversationId
     * @param {Object} data - Message data
     * @returns {Promise<{response: string, message_id: string}>}
     */
    async sendMessage(conversationId, data) {
        // Build page context with screenshot and multi-tab info
        const pageContext = data.pageContext ? {
            url: data.pageContext.url,
            title: data.pageContext.title,
            content: data.pageContext.content,
            screenshot: data.pageContext.screenshot,
            isScreenshot: data.pageContext.isScreenshot,
            isMultiTab: data.pageContext.isMultiTab,
            tabCount: data.pageContext.tabCount
        } : null;
        
        return this.call(`/ext/chat/${conversationId}`, {
            method: 'POST',
            body: JSON.stringify({
                message: data.message,
                page_context: pageContext,
                model: data.model,
                stream: false
            })
        });
    },

    /**
     * Send a message with streaming response
     * @param {string} conversationId
     * @param {Object} data - Message data
     * @param {Object} callbacks - {onChunk, onDone, onError}
     * @returns {Promise<void>}
     */
    async sendMessageStreaming(conversationId, data, callbacks) {
        // Build page context with screenshot and multi-tab info
        const pageContext = data.pageContext ? {
            url: data.pageContext.url,
            title: data.pageContext.title,
            content: data.pageContext.content,
            screenshot: data.pageContext.screenshot,
            isScreenshot: data.pageContext.isScreenshot,
            isMultiTab: data.pageContext.isMultiTab,
            tabCount: data.pageContext.tabCount
        } : null;
        
        return this.stream(`/ext/chat/${conversationId}`, {
            message: data.message,
            page_context: pageContext,
            model: data.model
        }, callbacks);
    },

    /**
     * Add a message without LLM response
     * @param {string} conversationId
     * @param {Object} data - {role, content, page_context}
     * @returns {Promise<{message: Object}>}
     */
    async addMessage(conversationId, data) {
        return this.call(`/ext/chat/${conversationId}/message`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },

    /**
     * Delete a message
     * @param {string} conversationId
     * @param {string} messageId
     * @returns {Promise<void>}
     */
    async deleteMessage(conversationId, messageId) {
        return this.call(`/ext/chat/${conversationId}/messages/${messageId}`, {
            method: 'DELETE'
        });
    },

    // ==================== Settings Methods ====================

    /**
     * Get user settings from server
     * @returns {Promise<{settings: Object}>}
     */
    async getSettings() {
        return this.call('/ext/settings');
    },

    /**
     * Update user settings on server
     * @param {Object} settings
     * @returns {Promise<{settings: Object}>}
     */
    async updateSettings(settings) {
        return this.call('/ext/settings', {
            method: 'PUT',
            body: JSON.stringify(settings)
        });
    },

    // ==================== Utility Methods ====================

    /**
     * Get available models
     * @returns {Promise<{models: Array}>}
     */
    async getModels() {
        return this.call('/ext/models');
    },

    /**
     * Health check
     * @returns {Promise<{status: string, services: Object}>}
     */
    async healthCheck() {
        return this.call('/ext/health');
    }
};

export default API;

