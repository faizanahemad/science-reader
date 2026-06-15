/**
 * TempLLMManager - Handles temporary/ephemeral LLM interactions
 * 
 * This module manages LLM actions that don't persist to the database:
 * - Explain this
 * - Critique this  
 * - Expand this
 * - ELI5 (Explain Like I'm 5)
 * - Ask Temporarily (multi-turn conversation without persistence)
 * 
 * Unlike DoubtManager, conversations here are stored only in memory
 * and are lost when the modal is closed or the page is refreshed.
 */
const TempLLMManager = {
    // Current state
    currentHistory: [],  // In-memory only, not persisted
    currentSelection: '',
    currentMessageContext: null,
    currentActionType: null,
    isStreaming: false,
    currentStreamingController: null,
    withContext: false,  // Whether to include conversation context from backend
    
    // Action type titles for the modal
    ACTION_TITLES: {
        'explain': '💡 Explain This',
        'critique': '🔍 Critique This',
        'expand': '📖 Expand This',
        'eli5': '🧒 ELI5 (Explain Like I\'m 5)',
        'ask_temp': '💬 Ask Temporarily',
        'explain_visual': '🎨 Explain Visually',
        'summarize_selection': '📝 Summarize Selection',
        'run_preamble': '⚙️ Run Preamble'
    },
    
    /**
     * Execute a quick LLM action (explain, critique, expand, eli5)
     * Opens the modal and immediately streams the response
     * 
     * @param {string} action - The action type
     * @param {string} selectedText - The text that was selected
     * @param {Object} messageContext - Context about the message (messageId, messageText, conversationId)
     * @param {boolean} withContext - Whether to include conversation context from backend
     */
    executeAction: function(action, selectedText, messageContext, withContext = false) {
        console.log('TempLLMManager.executeAction:', action, 'withContext:', withContext);
        
        this.currentSelection = selectedText;
        this.currentMessageContext = messageContext;
        this.currentActionType = action;
        this.currentHistory = [];
        this.withContext = withContext;
        
        // Open modal and start streaming
        this.openModal(action, selectedText);
        
        // Immediately start the action
        this.streamActionResponse(action, selectedText, messageContext);
    },
    
    /**
     * Open the temporary chat modal for multi-turn conversation
     * 
     * @param {string} selectedText - The text that was selected (optional)
     * @param {Object} messageContext - Context about the message
     * @param {boolean} withContext - Whether to include conversation context from backend
     */
    openTempChatModal: function(selectedText, messageContext, withContext = false) {
        console.log('TempLLMManager.openTempChatModal, withContext:', withContext);
        
        this.currentSelection = selectedText || '';
        this.currentMessageContext = messageContext;
        this.currentActionType = 'ask_temp';
        this.currentHistory = [];
        this.withContext = withContext;
        
        // Open modal without auto-streaming
        this.openModal('ask_temp', selectedText, false);
    },
    
    /**
     * Open the temporary LLM modal
     * 
     * @param {string} action - The action type
     * @param {string} selectedText - The selected text to show in context
     * @param {boolean} autoStream - Whether to auto-start streaming (default: true for quick actions)
     */
    openModal: function(action, selectedText, autoStream = true) {
        const modal = $('#temp-llm-modal');
        const messagesContainer = $('#temp-llm-messages');
        const contextDisplay = $('#temp-llm-context-display');
        const selectedTextDisplay = $('#temp-llm-selected-text');
        const modalTitle = $('#temp-llm-modal-title');
        const input = $('#temp-llm-input');
        
        // Clear previous content
        messagesContainer.empty();
        input.val('');
        
        // Set modal title based on action
        modalTitle.text(this.ACTION_TITLES[action] || 'Temporary Chat');
        
        // Show selected text context if available
        if (selectedText && selectedText.length > 0) {
            selectedTextDisplay.text(selectedText.length > 200 
                ? selectedText.substring(0, 200) + '...' 
                : selectedText);
            contextDisplay.show();
        } else {
            contextDisplay.hide();
        }
        
        // Show modal
        modal.modal('show');
        
        // Set up event handlers
        this.setupEventHandlers();
        
        // Initialize voice transcription if available
        this.initializeVoiceTranscription();
        
        // Focus on input after a short delay
        setTimeout(() => {
            input.focus();
        }, 500);
    },
    
    /**
     * Set up event handlers for the temporary LLM modal
     */
    setupEventHandlers: function() {
        const self = this;
        const input = $('#temp-llm-input');
        const sendBtn = $('#temp-llm-send-btn');
        const stopBtn = $('#stop-temp-llm-button');
        
        // Send button click
        sendBtn.off('click').on('click', function() {
            self.sendMessage();
        });
        
        // Enter key handling (Ctrl+Enter to send)
        input.off('keydown').on('keydown', function(e) {
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                self.sendMessage();
            }
        });
        
        // Stop button click
        stopBtn.off('click').on('click', function() {
            self.cancelStreaming();
        });
        
        // Modal close - clear state
        $('#temp-llm-modal').off('hidden.bs.modal').on('hidden.bs.modal', function() {
            self.cancelStreaming();
            self.currentHistory = [];
            self.currentSelection = '';
            self.currentMessageContext = null;
        });

        // Copy a card's text (user prompt or assistant answer).
        $(document).off('click', '#temp-llm-messages .temp-llm-copy-btn').on('click', '#temp-llm-messages .temp-llm-copy-btn', function(e) {
            e.preventDefault();
            e.stopPropagation();
            self.copyCardText($(this).closest('.temp-llm-card'));
        });

        // Length dropdown
        $('#temp-llm-length-dropdown-btn').parent().find('.temp-llm-length-option').off('click').on('click', function(e) {
            e.preventDefault();
            $('.temp-llm-length-option').removeClass('active');
            $(this).addClass('active');
            $('#temp-llm-length-dropdown-btn').text($(this).data('label'));
        });

        // Tools toggle
        $('#temp-llm-tools-toggle-btn').off('click').on('click', function() {
            $(this).toggleClass('active btn-outline-secondary btn-primary');
        });

        // Preamble multi-select dropdown
        $('#temp-llm-preamble-dropdown-menu .temp-llm-preamble-option').off('click').on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const val = $(this).data('value');
            if (!val) {
                // "None" — clear all
                $('#temp-llm-preamble-dropdown-menu .temp-llm-preamble-option').removeClass('active');
            } else {
                $('#temp-llm-preamble-dropdown-menu .temp-llm-preamble-option[data-value=""]').removeClass('active');
                $(this).toggleClass('active');
            }
            // Update button badge
            const count = $('#temp-llm-preamble-dropdown-menu .temp-llm-preamble-option.active').length;
            const btn = $('#temp-llm-preamble-dropdown-btn');
            btn.find('.badge').remove();
            if (count > 0) btn.append(' <span class="badge badge-info">' + count + '</span>');
        });

        // Copy thread
        $('#temp-llm-copy-thread-btn').off('click').on('click', function() {
            self.copyThread();
        });

        // Summarize thread
        $('#temp-llm-summarize-btn').off('click').on('click', function() {
            self.summarizeThread();
        });
    },

    /**
     * Copy a temp-LLM card's text to the clipboard. Prefers the stashed raw
     * markdown/plain text; falls back to the rendered body's text.
     *
     * @param {jQuery} $card - the .temp-llm-card element
     */
    copyCardText: function($card) {
        if (!$card || !$card.length) return;
        let text = $card.data('rawText');
        if (!text) {
            const $body = $card.find('.card-body').first();
            text = $body.length ? ($body[0].innerText || $body.text() || '') : '';
        }
        const ok = function() { if (typeof showToast === 'function') showToast('Copied to clipboard', 'success'); };
        const bad = function() { if (typeof showToast === 'function') showToast('Failed to copy', 'error'); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(ok).catch(bad);
        } else {
            try {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                ok();
            } catch (err) {
                bad();
            }
        }
    },

    /**
     * Get the currently selected preamble options from the dropdown.
     * @returns {string[]}
     */
    getSelectedPreambleOptions: function() {
        var opts = [];
        $('#temp-llm-preamble-dropdown-menu .temp-llm-preamble-option.active').each(function() {
            var v = $(this).data('value');
            if (v) opts.push(v);
        });
        return opts;
    },

    /**
     * Get the selected length label (Short/Medium/Long).
     * @returns {string}
     */
    getSelectedLength: function() {
        var active = $('.temp-llm-length-option.active').data('length') || 'medium';
        return active.charAt(0).toUpperCase() + active.slice(1);
    },

    /**
     * Copy entire thread as markdown to clipboard.
     */
    copyThread: function() {
        var lines = [];
        $('#temp-llm-messages .temp-llm-card').each(function() {
            var sender = $(this).find('.temp-llm-card-sender').text().trim();
            var text = $(this).data('rawText') || $(this).find('.card-body').first().text().trim();
            lines.push('**' + sender + ':** ' + text);
        });
        var md = lines.join('\n\n');
        if (!md) { if (typeof showToast === 'function') showToast('Nothing to copy', 'info'); return; }
        navigator.clipboard.writeText(md).then(function() {
            if (typeof showToast === 'function') showToast('Thread copied', 'success');
        }).catch(function() {
            if (typeof showToast === 'function') showToast('Failed to copy', 'error');
        });
    },

    /**
     * Summarize the current thread by sending it as a new temp LLM request.
     */
    summarizeThread: function() {
        if (this.isStreaming) return;
        var threadText = '';
        $('#temp-llm-messages .temp-llm-card').each(function() {
            var sender = $(this).find('.temp-llm-card-sender').text().trim();
            var text = $(this).data('rawText') || $(this).find('.card-body').first().text().trim();
            threadText += sender + ': ' + text + '\n\n';
        });
        if (!threadText.trim()) { if (typeof showToast === 'function') showToast('Nothing to summarize', 'info'); return; }
        // Inject a summarize request into the chat
        this.currentSelection = threadText;
        var assistantCard = this.addMessageToChat('', 'assistant');
        this.streamResponse('Summarize this conversation thread concisely. Capture key points, decisions, and conclusions.', assistantCard, 'summarize_selection');
    },
    
    /**
     * Initialize voice transcription for the temporary LLM modal
     */
    initializeVoiceTranscription: function() {
        if (typeof VoiceTranscription !== 'undefined') {
            if (!window.tempLLMVoice) {
                window.tempLLMVoice = new VoiceTranscription(
                    '#temp-llm-input',
                    '#temp-llm-voice-record',
                    'label[for="temp-llm-voice-record"] i'
                );
                console.log('Temp LLM voice transcription initialized');
            } else {
                window.tempLLMVoice.reinitialize();
            }
        }
    },
    
    /**
     * Send a message in the temporary chat
     */
    sendMessage: function() {
        const input = $('#temp-llm-input');
        const userMessage = input.val().trim();
        
        if (!userMessage && this.currentActionType === 'ask_temp') {
            this.showToast('Please enter a message', 'warning');
            return;
        }
        
        // Disable input while processing
        input.prop('disabled', true);
        $('#temp-llm-send-btn').prop('disabled', true);
        
        // Add user message to chat
        if (userMessage) {
            this.addMessageToChat(userMessage, 'user');
            input.val('');
        }
        
        // Create assistant message placeholder
        const assistantCard = this.addMessageToChat('', 'assistant');
        
        // Stream the response
        this.streamResponse(userMessage, assistantCard);
    },
    
    /**
     * Stream an action response (explain, critique, expand, eli5)
     * 
     * @param {string} action - The action type
     * @param {string} selectedText - The selected text
     * @param {Object} messageContext - The message context
     */
    streamActionResponse: function(action, selectedText, messageContext) {
        // Create assistant message placeholder
        const assistantCard = this.addMessageToChat('', 'assistant');
        
        // Stream the response
        this.streamResponse('', assistantCard, action);
    },
    
    /**
     * Add a message to the chat display
     * 
     * @param {string} text - The message text
     * @param {string} sender - 'user' or 'assistant'
     * @returns {jQuery} The created message card
     */
    addMessageToChat: function(text, sender) {
        const messagesContainer = $('#temp-llm-messages');
        const isUser = sender === 'user';
        const senderClass = isUser ? 'user-message' : 'assistant-message';
        const senderText = isUser ? 'You' : 'Assistant';
        
        let renderedContent;
        if (isUser) {
            renderedContent = text.replace(/\n/g, '<br>');
        } else if (text) {
            // Render markdown for assistant messages
            if (typeof marked !== 'undefined' && marked.parse) {
                renderedContent = marked.parse(text);
            } else {
                renderedContent = text.replace(/\n/g, '<br>');
            }
        } else {
            // Empty placeholder for streaming
            renderedContent = '<div class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> Thinking...</div>';
        }
        
        const card = $(`
            <div class="card temp-llm-card ${senderClass}" style="position: relative;">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span class="temp-llm-card-sender">${senderText}</span>
                    <span class="temp-llm-card-actions d-flex align-items-center">
                        <button class="temp-llm-copy-btn btn btn-sm p-1" title="Copy text"><i class="bi bi-clipboard"></i></button>
                    </span>
                </div>
                <div class="card-body">
                    ${renderedContent}
                </div>
            </div>
        `);
        // Stash the raw text so the copy button preserves the original markdown /
        // plain text rather than the rendered HTML.
        card.data('rawText', text || '');
        
        messagesContainer.append(card);
        
        // Only scroll to bottom for user messages (to show their message was sent)
        // Don't scroll for assistant messages as streaming will handle that at the end
        if (isUser) {
        messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
        }
        
        // Add scroll-to-top button for assistant messages that are long enough (non-streaming)
        if (!isUser && text && text.length > 300) {
            setTimeout(function() {
                if (typeof window.addScrollToTopButton === 'function') {
                    window.addScrollToTopButton(card, '↑ Top', 'temp-llm-scroll-top');
                }
            }, 50);
        }
        
        // Trigger MathJax typesetting for assistant cards
        if (!isUser && text) {
            setTimeout(function() {
                if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                    MathJax.Hub.Queue(["Typeset", MathJax.Hub, card.find('.card-body')[0]]);
                }
            }, 50);
        }
        
        return card;
    },
    
    /**
     * Stream response from the server
     * 
     * @param {string} userMessage - The user's message (optional for quick actions)
     * @param {jQuery} assistantCard - The card to update with the response
     * @param {string} actionType - Override action type (optional)
     */
    streamResponse: function(userMessage, assistantCard, actionType = null) {
        const self = this;
        const assistantBody = assistantCard.find('.card-body');
        const action = actionType || this.currentActionType;
        
        // Show stop button
        $('#stop-temp-llm-button').show();
        this.isStreaming = true;
        
        // Build request body
        const requestBody = {
            action_type: action,
            selected_text: this.currentSelection,
            user_message: userMessage,
            message_id: this.currentMessageContext?.messageId,
            message_text: this.currentMessageContext?.messageText,
            conversation_id: this.currentMessageContext?.conversationId,
            history: this.currentHistory,
            with_context: this.withContext || false,
            preamble_name: this.preambleName || '',
            preamble_options: this.getSelectedPreambleOptions(),
            length: this.getSelectedLength(),
            tools_enabled: $('#temp-llm-tools-toggle-btn').hasClass('active')
        };
        
        // Make the streaming request
        fetch('/temporary_llm_action', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody)
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response;
        })
        .then(response => {
            this.renderStreamingResponse(response, assistantCard, assistantBody, userMessage);
        })
        .catch(error => {
            console.error('Error in temporary LLM action:', error);
            assistantBody.html(`<div class="alert alert-danger alert-sm">Error: ${error.message}</div>`);
            this.resetInputState();
        });
    },
    
    /**
     * Render streaming response
     * 
     * @param {Response} streamingResponse - The fetch response object
     * @param {jQuery} assistantCard - The assistant card element
     * @param {jQuery} assistantBody - The card body to update
     * @param {string} userMessage - The original user message
     */
    renderStreamingResponse: function(streamingResponse, assistantCard, assistantBody, userMessage) {
        const self = this;
        const reader = streamingResponse.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulatedText = '';
        
        // Store reader for cancellation
        this.currentStreamingController = {
            reader: reader,
            cancel: function() {
                self.isStreaming = false;
                reader.cancel();
            }
        };
        
        async function read() {
            try {
                const { value, done } = await reader.read();
                
                if (done || !self.isStreaming) {
                    // Streaming complete
                    $('#stop-temp-llm-button').hide();
                    self.currentStreamingController = null;
                    self.isStreaming = false;
                    
                    // Preserve the original markdown for the copy button.
                    if (accumulatedText) {
                        assistantCard.data('rawText', accumulatedText);
                    }
                    
                    // Add to history (guard against double-push from completed chunk)
                    if (accumulatedText && !assistantCard.data('historyPushed')) {
                        assistantCard.data('historyPushed', true);
                        if (userMessage) {
                            self.currentHistory.push({
                                role: 'user',
                                content: userMessage
                            });
                        }
                        self.currentHistory.push({
                            role: 'assistant',
                            content: accumulatedText
                        });
                    }
                    
                    // Add scroll-to-top button for long responses
                    if (accumulatedText.length > 300) {
                        setTimeout(function() {
                            if (assistantCard.find('.scroll-to-top-btn').length === 0) {
                            if (typeof window.addScrollToTopButton === 'function') {
                                window.addScrollToTopButton(assistantCard, '↑ Top', 'temp-llm-scroll-top');
                                }
                            }
                        }, 100);
                    }
                    // Trigger MathJax typesetting on completed response
                    if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                        MathJax.Hub.Queue(["Typeset", MathJax.Hub, assistantBody[0]]);
                    }
                    
                    // Reset input state
                    self.resetInputState();
                    
                    // NOTE: No automatic scroll to bottom after streaming - user may have scrolled to read
                    // They can scroll manually if needed
                    
                    return;
                }
                
                buffer += decoder.decode(value, { stream: true });
                let boundary = buffer.indexOf('\n');
                
                while (boundary !== -1) {
                    try {
                        const part = JSON.parse(buffer.slice(0, boundary));
                        buffer = buffer.slice(boundary + 1);
                        boundary = buffer.indexOf('\n');
                        
                        if (part.error) {
                            assistantBody.html(`<div class="alert alert-danger alert-sm">Error: ${part.status || part.error}</div>`);
                            self.resetInputState();
                            return;
                        }
                        
                        if (part.text) {
                            accumulatedText += part.text;
                            
                            // Render markdown
                            if (typeof marked !== 'undefined' && marked.parse) {
                                assistantBody.html(marked.parse(accumulatedText));
                            } else {
                                assistantBody.html(accumulatedText.replace(/\n/g, '<br>'));
                            }
                            if (typeof renderMermaidIn === 'function') renderMermaidIn(assistantBody);
                            
                            // NOTE: No automatic scroll during streaming - user may be reading
                            // Scroll will happen only at the end when streaming completes
                        }
                        
                        if (part.completed) {
                            // Final processing
                            $('#stop-temp-llm-button').hide();
                            self.currentStreamingController = null;
                            self.isStreaming = false;
                            
                            // Add to history (guard against double-push from done branch)
                            if (accumulatedText && !assistantCard.data('historyPushed')) {
                                assistantCard.data('historyPushed', true);
                                if (userMessage) {
                                    self.currentHistory.push({
                                        role: 'user',
                                        content: userMessage
                                    });
                                }
                                self.currentHistory.push({
                                    role: 'assistant',
                                    content: accumulatedText
                                });
                            }
                            
                            // Add scroll-to-top button for long responses
                            if (accumulatedText.length > 300) {
                                setTimeout(function() {
                                    if (assistantCard.find('.scroll-to-top-btn').length === 0) {
                                        if (typeof window.addScrollToTopButton === 'function') {
                                            window.addScrollToTopButton(assistantCard, '↑ Top', 'temp-llm-scroll-top');
                                        }
                                    }
                                }, 100);
                            }
                            // Trigger MathJax typesetting on completed response
                            if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                                MathJax.Hub.Queue(["Typeset", MathJax.Hub, assistantBody[0]]);
                            }
                            
                            self.resetInputState();
                            return;
                        }
                    } catch (parseError) {
                        console.warn('Error parsing streaming chunk:', parseError);
                        buffer = buffer.slice(boundary + 1);
                        boundary = buffer.indexOf('\n');
                    }
                }
                
                // Continue reading
                setTimeout(read, 10);
                
            } catch (error) {
                console.error('Error in streaming:', error);
                $('#stop-temp-llm-button').hide();
                self.currentStreamingController = null;
                self.isStreaming = false;
                
                if (error.name !== 'AbortError') {
                    assistantBody.html(`<div class="alert alert-danger alert-sm">Streaming error: ${error.message}</div>`);
                }
                
                self.resetInputState();
            }
        }
        
        read();
    },
    
    /**
     * Cancel the current streaming response
     */
    cancelStreaming: function() {
        if (this.currentStreamingController) {
            this.currentStreamingController.cancel();
            this.currentStreamingController = null;
        }
        this.isStreaming = false;
        $('#stop-temp-llm-button').hide();
        this.resetInputState();
    },
    
    /**
     * Reset input state after streaming completes or is cancelled
     */
    resetInputState: function() {
        $('#temp-llm-input').prop('disabled', false);
        $('#temp-llm-send-btn').prop('disabled', false);
        $('#temp-llm-input').focus();
    },
    
    /**
     * Show a toast notification
     * 
     * @param {string} message - The message to show
     * @param {string} type - The type of toast
     */
    showToast: function(message, type) {
        if (typeof showToast === 'function') {
            showToast(message, type);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }
};

// Initialize when document is ready
$(document).ready(function() {
    console.log('TempLLMManager loaded');
});
