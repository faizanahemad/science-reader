/**
 * Chrome Storage Wrapper
 * 
 * Provides a clean async interface for chrome.storage.local operations.
 * Abstracts away callback-style API with Promise-based methods.
 */

import { STORAGE_KEYS, DEFAULT_SETTINGS } from './constants.js';

export const Storage = {
    /**
     * Get a value from storage
     * @param {string} key - Storage key
     * @returns {Promise<any>} - The stored value or undefined
     */
    async get(key) {
        return new Promise((resolve) => {
            chrome.storage.local.get(key, (result) => {
                resolve(result[key]);
            });
        });
    },

    /**
     * Set a value in storage
     * @param {string} key - Storage key
     * @param {any} value - Value to store
     * @returns {Promise<void>}
     */
    async set(key, value) {
        return new Promise((resolve) => {
            chrome.storage.local.set({ [key]: value }, resolve);
        });
    },

    /**
     * Remove a key from storage
     * @param {string} key - Storage key
     * @returns {Promise<void>}
     */
    async remove(key) {
        return new Promise((resolve) => {
            chrome.storage.local.remove(key, resolve);
        });
    },

    /**
     * Clear all storage
     * @returns {Promise<void>}
     */
    async clear() {
        return new Promise((resolve) => {
            chrome.storage.local.clear(resolve);
        });
    },

    // ==================== Auth Token Methods ====================

    /**
     * Get the stored auth token
     * @returns {Promise<string|null>}
     */
    async getToken() {
        return this.get(STORAGE_KEYS.AUTH_TOKEN);
    },

    /**
     * Store the auth token
     * @param {string} token - JWT token
     * @returns {Promise<void>}
     */
    async setToken(token) {
        return this.set(STORAGE_KEYS.AUTH_TOKEN, token);
    },

    /**
     * Remove the auth token (logout)
     * @returns {Promise<void>}
     */
    async clearToken() {
        return this.remove(STORAGE_KEYS.AUTH_TOKEN);
    },

    // ==================== User Info Methods ====================

    /**
     * Get stored user info
     * @returns {Promise<{email: string, name: string}|null>}
     */
    async getUserInfo() {
        return this.get(STORAGE_KEYS.USER_INFO);
    },

    /**
     * Store user info
     * @param {{email: string, name: string}} userInfo
     * @returns {Promise<void>}
     */
    async setUserInfo(userInfo) {
        return this.set(STORAGE_KEYS.USER_INFO, userInfo);
    },

    /**
     * Clear user info
     * @returns {Promise<void>}
     */
    async clearUserInfo() {
        return this.remove(STORAGE_KEYS.USER_INFO);
    },

    // ==================== Settings Methods ====================

    /**
     * Get user settings with defaults
     * @returns {Promise<Object>}
     */
    async getSettings() {
        const saved = await this.get(STORAGE_KEYS.SETTINGS);
        return { ...DEFAULT_SETTINGS, ...saved };
    },

    /**
     * Update settings (merges with existing)
     * @param {Object} settings - Settings to update
     * @returns {Promise<void>}
     */
    async setSettings(settings) {
        const current = await this.getSettings();
        return this.set(STORAGE_KEYS.SETTINGS, { ...current, ...settings });
    },

    // ==================== Conversation Methods ====================

    /**
     * Get the current active conversation ID
     * @returns {Promise<string|null>}
     */
    async getCurrentConversation() {
        return this.get(STORAGE_KEYS.CURRENT_CONVERSATION);
    },

    /**
     * Set the current active conversation ID
     * @param {string} conversationId
     * @returns {Promise<void>}
     */
    async setCurrentConversation(conversationId) {
        return this.set(STORAGE_KEYS.CURRENT_CONVERSATION, conversationId);
    },

    /**
     * Get recently accessed conversations (for quick access in popup)
     * @returns {Promise<Array>}
     */
    async getRecentConversations() {
        const recent = await this.get(STORAGE_KEYS.RECENT_CONVERSATIONS);
        return recent || [];
    },

    /**
     * Add a conversation to recent list
     * @param {{id: string, title: string}} conversation
     * @param {number} maxRecent - Maximum recent items to keep
     * @returns {Promise<void>}
     */
    async addRecentConversation(conversation, maxRecent = 5) {
        const recent = await this.getRecentConversations();
        // Remove if already exists
        const filtered = recent.filter(c => c.id !== conversation.id);
        // Add to front
        filtered.unshift(conversation);
        // Keep only maxRecent
        const trimmed = filtered.slice(0, maxRecent);
        return this.set(STORAGE_KEYS.RECENT_CONVERSATIONS, trimmed);
    },

    // ==================== Auth State Check ====================

    /**
     * Check if user is authenticated
     * @returns {Promise<boolean>}
     */
    async isAuthenticated() {
        const token = await this.getToken();
        return !!token;
    },

    /**
     * Clear all auth-related data (full logout)
     * @returns {Promise<void>}
     */
    async clearAuth() {
        await this.clearToken();
        await this.clearUserInfo();
        await this.remove(STORAGE_KEYS.CURRENT_CONVERSATION);
    }
};

export default Storage;

