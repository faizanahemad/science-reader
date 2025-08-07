/**
 * DoubtManager - Handles all doubt-related functionality
 * Provides methods for showing doubts, asking new doubts, and managing doubt conversations
 */
const DoubtManager = {
    currentConversationId: null,
    currentMessageId: null,
    currentDoubtHistory: [],
    
    /**
     * Show doubts overview modal for a specific message
     */
    showDoubtsOverview: function(conversationId, messageId) {
        this.currentConversationId = conversationId;
        this.currentMessageId = messageId;
        
        const modal = $('#doubts-overview-modal');
        const loading = $('#doubts-overview-loading');
        const content = $('#doubts-overview-content');
        const empty = $('#doubts-overview-empty');
        
        // Show modal and loading state
        modal.modal('show');
        loading.show();
        content.empty();
        empty.hide();
        
        // Fetch doubts for this message
        fetch(`/get_doubts/${conversationId}/${messageId}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            loading.hide();
            
            if (data.success && data.doubts && data.doubts.length > 0) {
                this.renderDoubtsOverview(data.doubts);
            } else {
                empty.show();
            }
        })
        .catch(error => {
            console.error('Error fetching doubts:', error);
            loading.hide();
            content.html(`<div class="alert alert-danger">Failed to load doubts: ${error.message}</div>`);
        });
        
        // Set up event handlers
        this.setupOverviewEventHandlers();
    },
    
    /**
     * Render doubts overview with preview cards
     */
    renderDoubtsOverview: function(doubts) {
        const content = $('#doubts-overview-content');
        content.empty();
        
        doubts.forEach(doubt => {
            const previewCard = this.createDoubtPreviewCard(doubt);
            content.append(previewCard);
        });
    },
    
    /**
     * Create a preview card for a doubt
     */
    createDoubtPreviewCard: function(doubt) {
        const truncatedDoubt = doubt.doubt_text.length > 100 
            ? doubt.doubt_text.substring(0, 100) + '...' 
            : doubt.doubt_text;
        
        const truncatedAnswer = doubt.doubt_answer.length > 150 
            ? doubt.doubt_answer.substring(0, 150) + '...' 
            : doubt.doubt_answer;
        
        const childrenCount = doubt.children ? doubt.children.length : 0;
        const childrenText = childrenCount > 0 ? ` (${childrenCount} follow-ups)` : '';
        
        const createdDate = new Date(doubt.created_at).toLocaleDateString();
        
        const card = $(`
            <div class="card doubt-preview-card" data-doubt-id="${doubt.doubt_id}">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span><strong>Doubt:</strong> ${createdDate}${childrenText}</span>
                    <button class="doubt-delete-btn" data-doubt-id="${doubt.doubt_id}" title="Delete Doubt">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
                <div class="card-body">
                    <p class="mb-2"><strong>Q:</strong> ${truncatedDoubt}</p>
                    <p class="mb-0 text-muted"><strong>A:</strong> ${truncatedAnswer}</p>
                </div>
            </div>
        `);
        
        return card;
    },
    
    /**
     * Set up event handlers for overview modal
     */
    setupOverviewEventHandlers: function() {
        const self = this;
        
        // Click on doubt preview card to open chat
        $(document).off('click', '.doubt-preview-card').on('click', '.doubt-preview-card', function(e) {
            // Don't trigger if clicking delete button
            if ($(e.target).closest('.doubt-delete-btn').length > 0) {
                return;
            }
            
            const doubtId = $(this).data('doubt-id');
            self.openDoubtChat(doubtId);
        });
        
        // Delete doubt button
        $(document).off('click', '.doubt-delete-btn').on('click', '.doubt-delete-btn', function(e) {
            e.stopPropagation();
            const doubtId = $(this).data('doubt-id');
            self.deleteDoubt(doubtId);
        });
        
        // Ask new doubt from overview
        $('#ask-new-doubt-from-overview-btn, #ask-first-doubt-btn').off('click').on('click', function() {
            $('#doubts-overview-modal').modal('hide');
            self.askNewDoubt(self.currentConversationId, self.currentMessageId);
        });
    },
    
    /**
     * Ask a new doubt (opens chat modal, loading existing doubts as history)
     */
    askNewDoubt: function(conversationId, messageId) {
        this.currentConversationId = conversationId;
        this.currentMessageId = messageId;
        
        // Load existing doubts to build proper parent-child relationships
        this.loadExistingDoubtsAsHistory(conversationId, messageId);
    },
    
    /**
     * Load existing doubts as history for new doubt conversations
     */
    loadExistingDoubtsAsHistory: function(conversationId, messageId) {
        const self = this;
        
        // Fetch existing doubts for this message
        fetch(`/get_doubts/${conversationId}/${messageId}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.success && data.doubts && data.doubts.length > 0) {
                // Flatten and sort all doubts by created_at to build a linear conversation history
                const allDoubts = self.flattenDoubtTree(data.doubts);
                allDoubts.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
                
                self.currentDoubtHistory = allDoubts;
                self.openDoubtChatModal();
                self.renderDoubtHistory(allDoubts);
            } else {
                // No existing doubts, start fresh
                self.currentDoubtHistory = [];
                self.openDoubtChatModal();
            }
        })
        .catch(error => {
            console.error('Error loading existing doubts:', error);
            // Fallback to empty history
            self.currentDoubtHistory = [];
            self.openDoubtChatModal();
        });
    },
    
    /**
     * Flatten doubt tree into a linear array
     */
    flattenDoubtTree: function(doubts) {
        const flattened = [];
        
        function flattenRecursive(doubtList) {
            for (const doubt of doubtList) {
                flattened.push(doubt);
                if (doubt.children && doubt.children.length > 0) {
                    flattenRecursive(doubt.children);
                }
            }
        }
        
        flattenRecursive(doubts);
        return flattened;
    },
    
    /**
     * Open doubt chat modal for a specific doubt thread
     */
    openDoubtChat: function(doubtId) {
        const self = this;
        
        // Get doubt history
        fetch(`/get_doubt/${doubtId}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.success && data.doubt) {
                // Get the full tree for this message and find the conversation thread
                const conversationId = data.doubt.conversation_id;
                const messageId = data.doubt.message_id;
                
                return fetch(`/get_doubts/${conversationId}/${messageId}`)
                    .then(response => response.json())
                    .then(treeData => {
                        if (treeData.success && treeData.doubts) {
                            // Flatten the tree and sort by created_at
                            const allDoubts = self.flattenDoubtTree(treeData.doubts);
                            allDoubts.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
                            return allDoubts;
                        }
                        return [];
                    });
            } else {
                throw new Error('Doubt not found');
            }
        })
        .then(history => {
            self.currentDoubtHistory = history;
            self.openDoubtChatModal();
            self.renderDoubtHistory(history);
        })
        .catch(error => {
            console.error('Error opening doubt chat:', error);
            showToast('Failed to open doubt conversation', 'error');
        });
    },
    
    /**
     * Get complete doubt history for a doubt thread
     */
    getDoubtHistory: function(doubtId) {
        return new Promise((resolve, reject) => {
            // This would need to be implemented on the server side
            // For now, we'll simulate it by getting the doubt and building history
            fetch(`/get_doubt/${doubtId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // In a real implementation, we'd have an API endpoint to get the full history
                        // For now, we'll just return the single doubt
                        resolve([data.doubt]);
                    } else {
                        reject(new Error('Failed to get doubt history'));
                    }
                })
                .catch(reject);
        });
    },
    
    /**
     * Open the doubt chat modal
     */
    openDoubtChatModal: function() {
        const modal = $('#doubt-chat-modal');
        const messagesContainer = $('#doubt-chat-messages');
        const input = $('#doubt-chat-input');
        
        // Clear and show modal
        messagesContainer.empty();
        input.val('');
        modal.modal('show');
        
        // Hide overview modal if it's open
        $('#doubts-overview-modal').modal('hide');
        
        // Set up chat event handlers
        this.setupChatEventHandlers();
        
        // Initialize voice transcription for doubt modal
        this.initializeDoubtVoiceTranscription();
        
        // Focus on input
        setTimeout(() => {
            input.focus();
        }, 500);
    },
    
    /**
     * Render doubt history in chat format
     */
    renderDoubtHistory: function(history) {
        const messagesContainer = $('#doubt-chat-messages');
        messagesContainer.empty();
        
        history.forEach(doubt => {
            // Add user doubt message
            const userCard = this.createDoubtChatCard(doubt.doubt_text, 'user', doubt.doubt_id);
            messagesContainer.append(userCard);
            
            // Add assistant answer message
            const assistantCard = this.createDoubtChatCard(doubt.doubt_answer, 'assistant', doubt.doubt_id);
            messagesContainer.append(assistantCard);
        });
        
        // Scroll to bottom
        messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
    },
    
    /**
     * Create a chat card for doubt conversation
     */
    createDoubtChatCard: function(text, sender, doubtId) {
        const isUser = sender === 'user';
        const senderClass = isUser ? 'user-doubt' : 'assistant-doubt';
        const senderText = isUser ? 'You' : 'Assistant';
        
        // Always create delete button for user messages, even if doubtId is null initially
        const deleteBtn = isUser ? `<button class="doubt-delete-btn float-right" data-doubt-id="${doubtId || ''}" title="Delete Doubt"><i class="bi bi-trash"></i></button>` : '';
        
        // Render content based on sender type
        let renderedContent;
        if (isUser) {
            // User messages are plain text - just convert line breaks
            renderedContent = text.replace(/\n/g, '<br>');
        } else {
            // Assistant messages should be rendered as markdown
            if (typeof marked !== 'undefined' && marked.parse) {
                renderedContent = marked.parse(text);
            } else {
                // Fallback if marked is not available
                renderedContent = text.replace(/\n/g, '<br>');
            }
        }
        
        const card = $(`
            <div class="card doubt-conversation-card ${senderClass}">
                <div class="card-header">
                    ${senderText} ${deleteBtn}
                </div>
                <div class="card-body">
                    ${renderedContent}
                </div>
            </div>
        `);
        
        return card;
    },
    
    /**
     * Initialize voice transcription for doubt modal
     */
    initializeDoubtVoiceTranscription: function() {
        // Initialize doubt chat voice transcription if not already done
        if (typeof doubtChatVoice === 'undefined' || !doubtChatVoice) {
            // Check if VoiceTranscription class is available
            if (typeof VoiceTranscription !== 'undefined') {
                window.doubtChatVoice = new VoiceTranscription(
                    '#doubt-chat-input', 
                    '#doubt-voice-record', 
                    'label[for="doubt-voice-record"] i'
                );
                console.log('Doubt chat voice transcription initialized');
            }
        } else {
            // Reinitialize if already exists (in case modal was closed and reopened)
            doubtChatVoice.reinitialize();
        }
    },
    
    /**
     * Set up event handlers for chat modal
     */
    setupChatEventHandlers: function() {
        const self = this;
        const input = $('#doubt-chat-input');
        const sendBtn = $('#doubt-chat-send-btn');
        
        // Send button click
        sendBtn.off('click').on('click', function() {
            self.sendDoubt();
        });
        
        // Enter key handling
        input.off('keydown').on('keydown', function(e) {
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                self.sendDoubt();
            }
        });
        
        // Delete doubt from chat
        $(document).off('click', '#doubt-chat-messages .doubt-delete-btn').on('click', '#doubt-chat-messages .doubt-delete-btn', function(e) {
            e.stopPropagation();
            const doubtId = $(this).data('doubt-id');
            self.deleteDoubt(doubtId);
        });
    },
    
    /**
     * Send a new doubt or follow-up
     */
    sendDoubt: function() {
        const input = $('#doubt-chat-input');
        const doubtText = input.val().trim();
        
        if (!doubtText) {
            showToast('Please enter your doubt', 'warning');
            return;
        }
        
        // Disable input while processing
        input.prop('disabled', true);
        $('#doubt-chat-send-btn').prop('disabled', true);
        
        // Add user message to chat immediately
        const userCard = this.createDoubtChatCard(doubtText, 'user', null);
        $('#doubt-chat-messages').append(userCard);
        
        // Disable the delete button on the user card until we get the doubt_id
        userCard.find('.doubt-delete-btn').prop('disabled', true).addClass('text-muted');
        
        // Create assistant card for streaming response
        const assistantCard = this.createDoubtChatCard('', 'assistant', null);
        $('#doubt-chat-messages').append(assistantCard);
        
        // Clear input
        input.val('');
        
        // Scroll to bottom
        const messagesContainer = $('#doubt-chat-messages');
        messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
        
        // Determine parent doubt ID for follow-ups
        // In a chat conversation, each new question should be a child of the last question
        const parentDoubtId = this.currentDoubtHistory.length > 0 
            ? this.currentDoubtHistory[this.currentDoubtHistory.length - 1].doubt_id 
            : null;
        
        // Send doubt to server with streaming
        this.streamDoubtResponse(doubtText, assistantCard, parentDoubtId);
    },
    
    /**
     * Stream doubt response from server
     */
    streamDoubtResponse: function(doubtText, assistantCard, parentDoubtId) {
        const self = this;
        const assistantBody = assistantCard.find('.card-body');
        
        // Show loading state
        assistantBody.html('<div class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div> Thinking...</div>');
        
        // Show stop button
        $('#stop-doubt-chat-button').show();
        
        // Find the user card that was just added (the previous sibling of assistantCard)
        const userCard = assistantCard.prev('.doubt-conversation-card.user-doubt');
        
        const requestBody = {
            doubt_text: doubtText
        };
        
        if (parentDoubtId) {
            requestBody.parent_doubt_id = parentDoubtId;
        }
        
        // Use fetch for streaming
        fetch(`/clear_doubt/${this.currentConversationId}/${this.currentMessageId}`, {
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
            this.renderStreamingDoubtResponse(response, assistantCard, assistantBody, userCard);
        })
        .catch(error => {
            console.error('Error streaming doubt response:', error);
            assistantBody.html(`<div class="alert alert-danger alert-sm">Failed to get response: ${error.message}</div>`);
        })
        .finally(() => {
            // Re-enable input (but don't hide stop button here - it's handled in renderStreamingDoubtResponse)
            $('#doubt-chat-input').prop('disabled', false);
            $('#doubt-chat-send-btn').prop('disabled', false);
            $('#doubt-chat-input').focus();
        });
    },
    
    /**
     * Render streaming doubt response
     */
    renderStreamingDoubtResponse: function(streamingResponse, assistantCard, assistantBody, userCard) {
        const self = this;
        const reader = streamingResponse.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulatedText = '';
        let doubtId = null;
        let isCancelled = false;
        
        // Set up streaming controller
        currentDoubtStreamingController = {
            reader: reader,
            conversationId: self.currentConversationId,
            cancel: function() {
                isCancelled = true;
                reader.cancel();
            }
        };
        
        async function read() {
            try {
                const { value, done } = await reader.read();
                
                if (done || isCancelled) {
                    console.log('Doubt streaming complete');
                    // Reset UI state
                    $('#stop-doubt-chat-button').hide();
                    currentDoubtStreamingController = null;
                    
                    if (isCancelled) {
                        console.log('Doubt streaming cancelled by user');
                        
                        // Still try to update doubt ID if we have one (partial response was saved)
                        if (doubtId) {
                            // Update user card with doubt ID for deletion
                            if (userCard && userCard.length > 0) {
                                const userDeleteBtn = userCard.find('.doubt-delete-btn');
                                userDeleteBtn.data('doubt-id', doubtId);
                                userDeleteBtn.prop('disabled', false).removeClass('text-muted');
                            }
                            
                            // Update the current doubt history for follow-up questions
                            if (self.currentDoubtHistory) {
                                self.currentDoubtHistory.push({
                                    doubt_id: doubtId,
                                    doubt_text: userCard ? userCard.find('.card-body').text() : '',
                                    doubt_answer: accumulatedText + "\n\n**[Cancelled by user]**"
                                });
                            }
                        }
                        return;
                    }
                    
                    // Update both user and assistant cards with doubt ID for deletion
                    if (doubtId) {
                        // Update assistant card (if it has a delete button)
                        assistantCard.find('.doubt-delete-btn').data('doubt-id', doubtId);
                        
                        // Update user card with doubt ID - this is the main fix
                        if (userCard && userCard.length > 0) {
                            const userDeleteBtn = userCard.find('.doubt-delete-btn');
                            userDeleteBtn.data('doubt-id', doubtId);
                            // Re-enable the delete button and remove muted styling
                            userDeleteBtn.prop('disabled', false).removeClass('text-muted');
                        }
                        
                        // Update the current doubt history for follow-up questions
                        if (self.currentDoubtHistory) {
                            self.currentDoubtHistory.push({
                                doubt_id: doubtId,
                                doubt_text: userCard ? userCard.find('.card-body').text() : '',
                                doubt_answer: accumulatedText
                            });
                        }
                    }
                    
                    // Scroll to bottom
                    const messagesContainer = $('#doubt-chat-messages');
                    messagesContainer.scrollTop(messagesContainer[0].scrollHeight);
                    
                    return;
                }
                
                buffer += decoder.decode(value, { stream: true });
                let boundary = buffer.indexOf('\n');
                
                while (boundary !== -1) {
                    const part = JSON.parse(buffer.slice(0, boundary));
                    buffer = buffer.slice(boundary + 1);
                    boundary = buffer.indexOf('\n');
                    
                    if (part.error) {
                        assistantBody.html(`<div class="alert alert-danger alert-sm">Error: ${part.status}</div>`);
                        return;
                    }
                    
                    if (part.text) {
                        // Check for doubt_id tags
                        const doubtIdMatch = part.text.match(/<doubt_id>([^<]+)<\/doubt_id>/);
                        if (doubtIdMatch) {
                            doubtId = doubtIdMatch[1];
                            // Remove the tags from display
                            part.text = part.text.replace(/<doubt_id>[^<]+<\/doubt_id>/, '');
                        }
                        
                        accumulatedText += part.text;
                        // Render markdown if available
                        if (typeof marked !== 'undefined' && marked.parse) {
                            assistantBody.html(marked.parse(accumulatedText));
                        } else {
                            assistantBody.html(accumulatedText.replace(/\n/g, '<br>'));
                        }
                    }
                    
                    if (part.completed) {
                        // Final processing
                        if (part.doubt_id) {
                            doubtId = part.doubt_id;
                        }
                        return;
                    }
                }
                
                // Continue reading
                setTimeout(read, 10);
                
            } catch (error) {
                console.error("Error in doubt streaming:", error);
                $('#stop-doubt-chat-button').hide();
                currentDoubtStreamingController = null;
                
                if (error.name === 'AbortError') {
                    assistantBody.html(`<div class="alert alert-warning alert-sm">Doubt clearing was cancelled</div>`);
                } else {
                    assistantBody.html(`<div class="alert alert-danger alert-sm">Streaming error: ${error.message}</div>`);
                }
            }
        }
        
        read();
    },
    
    /**
     * Delete a doubt
     */
    deleteDoubt: function(doubtId) {
        // Check if doubtId is valid
        if (!doubtId || doubtId.trim() === '') {
            showToast('Cannot delete doubt: ID not available yet', 'warning');
            return;
        }
        
        if (!confirm('Are you sure you want to delete this doubt? This action cannot be undone.')) {
            return;
        }
        
        fetch(`/delete_doubt/${doubtId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                showToast('Doubt deleted successfully', 'success');
                
                // Refresh current view
                if ($('#doubts-overview-modal').hasClass('show')) {
                    // Refresh overview
                    this.showDoubtsOverview(this.currentConversationId, this.currentMessageId);
                }
                
                if ($('#doubt-chat-modal').hasClass('show')) {
                    // Remove the doubt from chat view
                    $(`.doubt-conversation-card .doubt-delete-btn[data-doubt-id="${doubtId}"]`)
                        .closest('.doubt-conversation-card')
                        .fadeOut(300, function() {
                            $(this).remove();
                        });
                }
            } else {
                throw new Error(data.message || 'Failed to delete doubt');
            }
        })
        .catch(error => {
            console.error('Error deleting doubt:', error);
            showToast('Failed to delete doubt: ' + error.message, 'error');
        });
    }
};

// Initialize when document is ready
$(document).ready(function() {
    console.log('DoubtManager initialized');
}); 