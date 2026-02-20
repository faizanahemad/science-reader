/**
 * API Client for Extension Server
 * 
 * Provides methods for communicating with extension_server.py.
 * Handles authentication headers, error handling, and streaming responses.
 */

import { API_BASE, TIMEOUTS, EXTENSION_PROMPT_ALLOWLIST, EXTENSION_AGENT_ALLOWLIST } from './constants.js';
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
 * Resolve the API base URL from settings.
 * @returns {Promise<string>}
 */
async function getApiBaseUrl() {
    const base = await Storage.getApiBaseUrl();
    const normalized = (base || API_BASE).trim().replace(/\/+$/, '');
    return normalized || API_BASE;
}

function _processJsonLineChunk(parsed, onChunk, onStatus, onMessageIds) {
    var text = parsed.text || '';
    var status = parsed.status || '';

    if (text && onChunk) onChunk(text);
    if (status && onStatus) onStatus(status);
    if (parsed.message_ids && onMessageIds) onMessageIds(parsed.message_ids);
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
        const apiBase = await getApiBaseUrl();
        const { timeoutMs, ...fetchOptions } = options;
        
        const headers = {
            'Content-Type': 'application/json',
            ...fetchOptions.headers
        };

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), timeoutMs ?? TIMEOUTS.API_REQUEST);

        try {
            const response = await fetch(`${apiBase}${endpoint}`, {
                ...fetchOptions,
                headers,
                credentials: 'include',
                signal: controller.signal
            });

            clearTimeout(timeout);

            if (response.status === 401) {
                await Storage.clearAuth();
                throw new AuthError('Session expired or invalid');
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
     * Stream a response using newline-delimited JSON (main backend format).
     * Each line is a JSON object: {"text": "...", "status": "...", "message_ids": {...}}
     *
     * @param {string} endpoint - API endpoint
     * @param {Object} body - Request body
     * @param {Object} callbacks
     * @param {Function} callbacks.onChunk - Called with non-empty text from each chunk
     * @param {Function} [callbacks.onStatus] - Called with status string updates
     * @param {Function} [callbacks.onMessageIds] - Called with message_ids dict when present
     * @param {Function} [callbacks.onDone] - Called when streaming completes
     * @param {Function} [callbacks.onError] - Called on errors
     * @param {AbortSignal} [callbacks.signal] - AbortController signal for cancellation
     * @returns {Promise<void>}
     */
    async streamJsonLines(endpoint, body, { onChunk, onStatus, onMessageIds, onDone, onError, signal }) {
        const apiBase = await getApiBaseUrl();

        try {
            const response = await fetch(`${apiBase}${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(body),
                signal: signal || undefined,
            });

            if (response.status === 401) {
                await Storage.clearAuth();
                throw new AuthError('Session expired or invalid');
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
                    if (buffer.trim()) {
                        try {
                            const parsed = JSON.parse(buffer.trim());
                            _processJsonLineChunk(parsed, onChunk, onStatus, onMessageIds);
                        } catch (e) { /* incomplete trailing data */ }
                    }
                    if (onDone) onDone();
                    break;
                }

                buffer += decoder.decode(value, { stream: true });

                let boundary = buffer.indexOf('\n');
                while (boundary !== -1) {
                    const line = buffer.slice(0, boundary).trim();
                    buffer = buffer.slice(boundary + 1);

                    if (line) {
                        try {
                            const parsed = JSON.parse(line);
                            _processJsonLineChunk(parsed, onChunk, onStatus, onMessageIds);
                        } catch (e) {
                            console.warn('[API] Failed to parse JSON line:', line.slice(0, 100));
                        }
                    }
                    boundary = buffer.indexOf('\n');
                }
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                if (onDone) onDone();
                return;
            }
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
     * Get prompts from main backend, filtered by extension allowlist.
     * Calls /get_prompts directly and applies client-side filtering.
     * @returns {Promise<{prompts: Array}>}
     */
    async getPrompts() {
        var allPrompts = await this.call('/get_prompts');
        // Main backend returns a flat array, not {prompts: [...]}
        var arr = Array.isArray(allPrompts) ? allPrompts : (allPrompts.prompts || []);
        var allowSet = new Set(EXTENSION_PROMPT_ALLOWLIST);
        var filtered = allowSet.size > 0
            ? arr.filter(function(p) { return allowSet.has(p.name); })
            : arr;
        return { prompts: filtered };
    },

    /**
     * Get a specific prompt by name from main backend.
     * @param {string} name - Prompt name
     * @returns {Promise<Object>}
     */
    async getPrompt(name) {
        return this.call('/get_prompt_by_name/' + encodeURIComponent(name));
    },

    /**
     * Get available agents for the extension (client-side allowlist).
     * @returns {Promise<{agents: Array}>}
     */
    async getAgents() {
        return { agents: EXTENSION_AGENT_ALLOWLIST.slice().sort() };
    },

    // ==================== Workflow Methods ====================

    /**
     * List workflows for the current user.
     * @returns {Promise<{workflows: Array}>}
     */
    async getWorkflows() {
        return this.call('/ext/workflows');
    },

    /**
     * Create a new workflow.
     * @param {Object} data - Workflow payload.
     * @returns {Promise<{workflow: Object}>}
     */
    async createWorkflow(data) {
        return this.call('/ext/workflows', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },

    /**
     * Update an existing workflow.
     * @param {string} workflowId - Workflow ID.
     * @param {Object} data - Workflow payload.
     * @returns {Promise<{workflow: Object}>}
     */
    async updateWorkflow(workflowId, data) {
        return this.call(`/ext/workflows/${encodeURIComponent(workflowId)}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    },

    /**
     * Delete a workflow.
     * @param {string} workflowId - Workflow ID.
     * @returns {Promise<{message: string}>}
     */
    async deleteWorkflow(workflowId) {
        return this.call(`/ext/workflows/${encodeURIComponent(workflowId)}`, {
            method: 'DELETE'
        });
    },

    // ==================== OCR / Vision Methods ====================

    /**
     * OCR a list of screenshots using a vision-capable model.
     * @param {string[]} images - Array of data URLs (base64).
     * @param {Object} meta - Optional metadata like url/title/model.
     * @returns {Promise<{text: string, pages: Array}>}
     */
    async ocrScreenshots(images, meta = {}) {
        return this.call('/ext/ocr', {
            method: 'POST',
            body: JSON.stringify({
                images,
                ...meta
            }),
            timeoutMs: 120000
        });
    },

    /**
     * Transcribe audio to text via server-side Whisper/AssemblyAI.
     * Uses FormData (not JSON) so we must bypass this.call() which
     * sets Content-Type: application/json.
     * @param {Blob} audioBlob - Audio blob (webm/mp3/etc)
     * @returns {Promise<{transcription: string}>}
     */
    async transcribeAudio(audioBlob) {
        const apiBase = await getApiBaseUrl();
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');

        const response = await fetch(`${apiBase}/transcribe`, {
            method: 'POST',
            body: formData,
            credentials: 'include'
        });

        if (response.status === 401) {
            await Storage.clearAuth();
            throw new AuthError('Session expired or invalid');
        }

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error || `HTTP ${response.status}`);
        }

        return response.json();
    },

    // ==================== Memories Methods ====================

    /**
     * List user's memories (PKB claims) via main backend /pkb/claims.
     * @param {Object} params - Query parameters (limit, offset, status, claim_type)
     * @returns {Promise<{memories: Array, total: number}>}
     */
    async getMemories(params = {}) {
        var query = new URLSearchParams(params).toString();
        var result = await this.call('/pkb/claims' + (query ? '?' + query : ''));
        // Main backend returns {claims: [...], count: N}
        return { memories: result.claims || [], total: result.count || 0 };
    },

    /**
     * Search memories via main backend /pkb/claims?query=...
     * @param {string} query - Search query
     * @param {number} k - Number of results
     * @returns {Promise<{results: Array}>}
     */
    async searchMemories(query, k = 10) {
        var result = await this.call('/pkb/claims?query=' + encodeURIComponent(query) + '&limit=' + k);
        // Adapt: main backend returns {claims: [...]}; wrap each as {claim, score}
        var claims = result.claims || [];
        return { results: claims.map(function(c) { return { claim: c, score: 1.0 }; }) };
    },

    /**
     * Get pinned memories (not directly supported — returns empty for now).
     * @returns {Promise<{memories: Array}>}
     */
    async getPinnedMemories() {
        return { memories: [] };
    },

    // ==================== Conversations Methods ====================

    async getConversations() {
        var domain = await Storage.getDomain();
        return this.call('/list_conversation_by_user/' + domain);
    },

    async createConversation(data = {}) {
        var domain = await Storage.getDomain();
        return this.call('/create_temporary_conversation/' + domain, {
            method: 'POST',
            body: JSON.stringify({ workspace_id: data.workspace_id || null })
        });
    },

    async createPermanentConversation(data = {}) {
        var domain = await Storage.getDomain();
        var workspaceId = data.workspace_id || null;
        var endpoint = '/create_conversation/' + domain;
        if (workspaceId) {
            endpoint += '/' + encodeURIComponent(workspaceId);
        }
        return this.call(endpoint, { method: 'POST' });
    },

    async getConversationMessages(id) {
        return this.call('/list_messages_by_conversation/' + id);
    },

    async getConversationDetails(id) {
        return this.call('/get_conversation_details/' + id);
    },

    async deleteConversation(id) {
        return this.call('/delete_conversation/' + id, { method: 'DELETE' });
    },

    async saveConversation(id) {
        return this.call('/make_conversation_stateful/' + id, { method: 'PUT' });
    },

    // ==================== Chat Methods ====================

    /**
     * Upload a document (PDF) to a conversation via main backend's FastDocIndex endpoint.
     * Creates BM25 keyword index (1-3s). Returns {status, doc_id, source, title}.
     * @param {string} conversationId
     * @param {FormData} formData - Must contain 'pdf_file' field
     * @returns {Promise<{status: string, doc_id: string, source: string, title: string}>}
     */
    async uploadDoc(conversationId, formData) {
        const apiBase = await getApiBaseUrl();
        const response = await fetch(
            `${apiBase}/upload_doc_to_conversation/${conversationId}`,
            { method: 'POST', credentials: 'include', body: formData }
        );
        if (response.status === 401) {
            await Storage.clearAuth();
            throw new AuthError('Session expired or invalid');
        }
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.error || `Upload failed: ${response.status}`);
        }
        return response.json();
    },

    /**
     * Upload an image to a conversation via main backend (creates FastImageDocIndex).
     * Same endpoint as uploadDoc — backend auto-detects file type.
     * @param {string} conversationId
     * @param {File} imageFile - Image file to upload
     * @returns {Promise<{status: string, doc_id: string, source: string, title: string}>}
     */
    async uploadImage(conversationId, imageFile) {
        const apiBase = await getApiBaseUrl();
        const formData = new FormData();
        formData.append('pdf_file', imageFile);  // Same field name — backend auto-detects file type
        const response = await fetch(
            `${apiBase}/upload_doc_to_conversation/${conversationId}`,
            { method: 'POST', credentials: 'include', body: formData }
        );
        if (response.status === 401) {
            await Storage.clearAuth();
            throw new AuthError('Session expired or invalid');
        }
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.error || `Image upload failed: ${response.status}`);
        }
        return response.json();
    },

    /**
     * Send a message with streaming response via main backend /send_message endpoint.
     * Transforms extension payload to main backend format and streams newline-delimited JSON.
     *
     * @param {string} conversationId
     * @param {Object} data - {message, pageContext, model, agent, workflow_id, images, historyLength}
     * @param {Object} callbacks - {onChunk, onStatus, onMessageIds, onDone, onError, signal}
     * @returns {Promise<void>}
     */
    async sendMessageStreaming(conversationId, data, callbacks) {
        var agentField = data.agent || 'None';
        if (data.workflow_id) agentField = 'PromptWorkflowAgent';

        var pageContext = data.pageContext ? {
            url: data.pageContext.url,
            title: data.pageContext.title,
            content: data.pageContext.content,
            screenshot: data.pageContext.screenshot,
            isScreenshot: data.pageContext.isScreenshot,
            isMultiTab: data.pageContext.isMultiTab,
            tabCount: data.pageContext.tabCount,
            sources: data.pageContext.sources,
            mergeType: data.pageContext.mergeType,
            lastRefreshed: data.pageContext.lastRefreshed
        } : null;

        var payload = {
            messageText: data.message,
            checkboxes: {
                main_model: data.model || 'google/gemini-2.5-flash',
                field: agentField,
                persist_or_not: true,
                provide_detailed_answers: 2,
                use_pkb: true,
                enable_previous_messages: String(data.historyLength || 10),
                perform_web_search: false,
                googleScholar: false,
                ppt_answer: false,
                preamble_options: []
            },
            search: [],
            links: [],
            source: 'extension',
            page_context: pageContext,
            images: data.images || [],
        };

        if (data.workflow_id) {
            payload.checkboxes.workflow_id = data.workflow_id;
        }

        return this.streamJsonLines(
            '/send_message/' + conversationId,
            payload,
            callbacks
        );
    },

    // ==================== Workspace Methods ====================

    async listWorkspaces(domain) {
        return this.call('/list_workspaces/' + domain);
    },

    async createWorkspace(domain, name, options = {}) {
        return this.call(
            '/create_workspace/' + encodeURIComponent(domain) + '/' + encodeURIComponent(name),
            {
                method: 'POST',
                body: JSON.stringify({
                    workspace_color: options.color || '#6f42c1',
                    parent_workspace_id: options.parentId || null,
                })
            }
        );
    },

    // ==================== Document Methods (Conversation-Scoped) ====================

    async listDocuments(conversationId) {
        return this.call('/list_documents_by_conversation/' + conversationId);
    },

    async deleteDocument(conversationId, docId) {
        return this.call('/delete_document_from_conversation/' + conversationId + '/' + docId, {
            method: 'DELETE'
        });
    },

    async downloadDocUrl(conversationId, docId) {
        const apiBase = await getApiBaseUrl();
        return `${apiBase}/download_doc_from_conversation/${conversationId}/${docId}`;
    },

    async promoteMessageDoc(conversationId, docId) {
        return this.call('/promote_message_doc/' + conversationId + '/' + docId, {
            method: 'POST',
            timeoutMs: 60000
        });
    },

    // ==================== Global Document Methods ====================

    async listGlobalDocs() {
        return this.call('/global_docs/list');
    },

    async uploadGlobalDoc(formData) {
        const apiBase = await getApiBaseUrl();
        const response = await fetch(`${apiBase}/global_docs/upload`, {
            method: 'POST', credentials: 'include', body: formData
        });
        if (response.status === 401) {
            await Storage.clearAuth();
            throw new AuthError('Session expired or invalid');
        }
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.error || `Upload failed: ${response.status}`);
        }
        return response.json();
    },

    async deleteGlobalDoc(docId) {
        return this.call('/global_docs/' + docId, { method: 'DELETE' });
    },

    async downloadGlobalDocUrl(docId) {
        const apiBase = await getApiBaseUrl();
        return `${apiBase}/global_docs/download/${docId}`;
    },

    async promoteToGlobal(conversationId, docId) {
        return this.call('/global_docs/promote/' + conversationId + '/' + docId, {
            method: 'POST',
            timeoutMs: 60000
        });
    },

    // ==================== Conversation Action Methods ====================

    async cloneConversation(conversationId) {
        return this.call('/clone_conversation/' + conversationId, { method: 'POST' });
    },

    async makeConversationStateless(conversationId) {
        return this.call('/make_conversation_stateless/' + conversationId, { method: 'DELETE' });
    },

    async setFlag(conversationId, flag) {
        return this.call('/set_flag/' + conversationId + '/' + flag, { method: 'POST' });
    },

    async moveConversationToWorkspace(conversationId, targetWorkspaceId) {
        return this.call('/move_conversation_to_workspace/' + encodeURIComponent(conversationId), {
            method: 'PUT',
            body: JSON.stringify({ workspace_id: targetWorkspaceId })
        });
    },

    // ==================== PKB Claims Methods ====================

    async getClaims(params = {}) {
        var query = new URLSearchParams(params).toString();
        return this.call('/pkb/claims' + (query ? '?' + query : ''));
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

    // ==================== Script Methods ====================

    /**
     * Generate a script using LLM
     * @param {Object} data - {description, page_url, page_html, page_context, refinement}
     * @returns {Promise<{script: Object, explanation: string}>}
     */
    async generateScript(data) {
        return this.call('/ext/scripts/generate', {
            method: 'POST',
            body: JSON.stringify({
                description: data.description,
                page_url: data.page_url || '',
                page_html: data.page_html || '',
                page_context: data.page_context || null,
                refinement: data.refinement || ''
            })
        });
    },

    /**
     * Save a generated script
     * @param {Object} scriptData - Full script object
     * @returns {Promise<{script: Object}>}
     */
    async saveScript(scriptData) {
        return this.call('/ext/scripts', {
            method: 'POST',
            body: JSON.stringify(scriptData)
        });
    },

    /**
     * Get all scripts for current user
     * @returns {Promise<{scripts: Array}>}
     */
    async getScripts() {
        return this.call('/ext/scripts');
    },

    // ==================== Utility Methods ====================

    /**
     * Get available models from main backend /model_catalog.
     * Adapts response to {models: [{id, name, provider}], default: str}.
     * @returns {Promise<{models: Array, default: string}>}
     */
    async getModels() {
        var result = await this.call('/model_catalog');
        // Main backend returns {models: ["model/name", ...], defaults: {...}}
        var modelIds = result.models || [];
        var models = modelIds.map(function(id) {
            var parts = id.split('/');
            return {
                id: id,
                name: parts.length > 1 ? parts.slice(1).join('/') : id,
                provider: parts.length > 1 ? parts[0].charAt(0).toUpperCase() + parts[0].slice(1) : 'Unknown'
            };
        });
        return { models: models, default: models.length > 0 ? models[0].id : 'google/gemini-2.5-flash' };
    },

    /**
     * Health check — uses auth verify as a proxy.
     * @returns {Promise<{status: string}>}
     */
    async healthCheck() {
        var result = await this.verifyAuth();
        return { status: result.valid ? 'healthy' : 'unhealthy' };
    }
};

export default API;

