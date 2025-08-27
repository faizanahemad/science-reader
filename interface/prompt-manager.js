/**
 * PromptManager - Handles all prompt management functionality
 * Provides methods for listing, viewing, editing, and saving prompts
 */
const PromptManager = {
    // State management
    allPrompts: [],
    filteredPrompts: [],
    currentPrompt: null,
    originalContent: null,
    hasUnsavedChanges: false,

    /**
     * Initialize the prompt manager
     */
    init: function() {
        this.setupEventHandlers();
        this.loadPrompts();
    },

    /**
     * Set up all event handlers
     */
    setupEventHandlers: function() {
        const self = this;

        // Button to open the modal
        $('#settings-prompt-manager-modal-open-button').on('click', function(e) {
            e.preventDefault();
            self.open();
        });

        // Search functionality
        $('#prompt-search-input').on('input', function() {
            self.filterPrompts($(this).val());
        });

        $('#prompt-search-clear').on('click', function() {
            $('#prompt-search-input').val('');
            self.filterPrompts('');
        });

        // Editor actions
        $('#prompt-save-btn').on('click', function() {
            self.saveCurrentPrompt();
        });

        $('#prompt-revert-btn').on('click', function() {
            self.revertChanges();
        });

        $('#prompt-copy-btn').on('click', function() {
            self.copyToClipboard();
        });

        // Track changes in editor
        $('#prompt-content-textarea').on('input', function() {
            self.markAsChanged();
            self.updateStats();
        });

        // Metadata fields change tracking
        $('#prompt-description-input, #prompt-category-input, #prompt-tags-input').on('input', function() {
            self.markAsChanged();
        });

        // Modal events
        $('#prompt-management-modal').on('shown.bs.modal', function() {
            self.loadPrompts();
        });

        $('#prompt-management-modal').on('hide.bs.modal', function(e) {
            if (self.hasUnsavedChanges) {
                if (!confirm('You have unsaved changes. Are you sure you want to close?')) {
                    e.preventDefault();
                    return false;
                }
            }
        });

        // Keyboard shortcuts
        $(document).on('keydown', function(e) {
            if ($('#prompt-management-modal').is(':visible')) {
                // Ctrl+S to save
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    if (self.hasUnsavedChanges && self.currentPrompt) {
                        self.saveCurrentPrompt();
                    }
                }
                // Escape to close (if no unsaved changes)
                if (e.key === 'Escape' && !self.hasUnsavedChanges) {
                    $('#prompt-management-modal').modal('hide');
                }
            }
        });
    },

    /**
     * Load all prompts from the server
     */
    loadPrompts: function() {
        const self = this;
        const loading = $('#prompt-list-loading');
        const itemsContainer = $('#prompt-list-items');
        const emptyState = $('#prompt-list-empty');

        loading.show();
        itemsContainer.hide();
        emptyState.hide();

        fetch('/get_prompts', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
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
            
            if (data.status === 'success' && data.prompts && data.prompts.length > 0) {
                self.allPrompts = data.prompts.sort();
                self.filteredPrompts = [...self.allPrompts];
                self.renderPromptList();
                itemsContainer.show();
            } else {
                emptyState.show();
            }
        })
        .catch(error => {
            console.error('Error loading prompts:', error);
            loading.hide();
            self.showError('Failed to load prompts: ' + error.message);
        });
    },

    /**
     * Render the prompt list
     */
    renderPromptList: function() {
        const itemsContainer = $('#prompt-list-items');
        const emptyState = $('#prompt-list-empty');
        
        itemsContainer.empty();

        if (this.filteredPrompts.length === 0) {
            itemsContainer.hide();
            emptyState.show();
            return;
        }

        emptyState.hide();
        itemsContainer.show();

        this.filteredPrompts.forEach(promptName => {
            const listItem = this.createPromptListItem(promptName);
            itemsContainer.append(listItem);
        });
    },

    /**
     * Create a list item for a prompt
     */
    createPromptListItem: function(promptName) {
        const self = this;
        const isActive = this.currentPrompt === promptName;
        
        // Format the prompt name for display
        const displayName = promptName.replace(/_/g, ' ')
            .replace(/\b\w/g, l => l.toUpperCase());
        
        const item = $(`
            <a href="#" class="list-group-item list-group-item-action ${isActive ? 'active' : ''}" data-prompt-name="${promptName}">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <div class="font-weight-medium">${displayName}</div>
                        <small class="text-muted">${promptName}</small>
                    </div>
                    ${this.hasUnsavedChanges && isActive ? '<span class="badge badge-warning">Modified</span>' : ''}
                </div>
            </a>
        `);

        item.on('click', function(e) {
            e.preventDefault();
            
            // Check for unsaved changes
            if (self.hasUnsavedChanges && self.currentPrompt !== promptName) {
                if (!confirm('You have unsaved changes. Do you want to discard them?')) {
                    return;
                }
            }
            
            self.loadPrompt(promptName);
        });

        return item;
    },

    /**
     * Load a specific prompt for editing
     */
    loadPrompt: function(promptName) {
        const self = this;
        
        // Show loading state
        this.showLoading();

        fetch(`/get_prompt_by_name/${encodeURIComponent(promptName)}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'success') {
                self.currentPrompt = promptName;
                self.originalContent = {
                    content: data.raw_content || data.content,
                    description: data.metadata?.description || '',
                    category: data.metadata?.category || '',
                    tags: Array.isArray(data.metadata?.tags) ? data.metadata.tags.join(', ') : ''
                };
                self.displayPrompt(data);
                self.hasUnsavedChanges = false;
                
                // Update active state in list
                $('#prompt-list-items .list-group-item').removeClass('active');
                $(`#prompt-list-items .list-group-item[data-prompt-name="${promptName}"]`).addClass('active');
            } else {
                self.showError('Failed to load prompt: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error loading prompt:', error);
            self.showError('Failed to load prompt: ' + error.message);
        });
    },

    /**
     * Display a prompt in the editor
     */
    displayPrompt: function(promptData) {
        // Hide empty state and show form
        $('#prompt-editor-empty').hide();
        $('#prompt-editor-form').show();
        $('#prompt-editor-actions').show();

        // Update header
        const displayName = promptData.name.replace(/_/g, ' ')
            .replace(/\b\w/g, l => l.toUpperCase());
        $('#prompt-editor-title').text(displayName);
        $('#prompt-editor-subtitle').text(promptData.name);

        // Fill in the form fields
        $('#prompt-name-input').val(promptData.name);
        $('#prompt-content-textarea').val(promptData.raw_content || promptData.content);
        
        // Fill metadata if available
        if (promptData.metadata) {
            $('#prompt-description-input').val(promptData.metadata.description || '');
            $('#prompt-category-input').val(promptData.metadata.category || '');
            
            if (Array.isArray(promptData.metadata.tags)) {
                $('#prompt-tags-input').val(promptData.metadata.tags.join(', '));
            } else {
                $('#prompt-tags-input').val('');
            }
            
            $('#prompt-created-at').text(
                promptData.metadata.created_at ? 
                new Date(promptData.metadata.created_at).toLocaleString() : 
                'N/A'
            );
            $('#prompt-updated-at').text(
                promptData.metadata.updated_at ? 
                new Date(promptData.metadata.updated_at).toLocaleString() : 
                'N/A'
            );
        }

        // Update stats
        this.updateStats();
        
        // Clear any previous messages
        $('#prompt-editor-messages').empty();
        
        // Reset save button
        $('#prompt-save-btn').removeClass('btn-success').addClass('btn-outline-success').prop('disabled', false);
    },

    /**
     * Save the current prompt
     */
    saveCurrentPrompt: function() {
        const self = this;
        
        if (!this.currentPrompt) {
            this.showError('No prompt selected');
            return;
        }

        const saveBtn = $('#prompt-save-btn');
        saveBtn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm mr-1"></span> Saving...');

        // Prepare the data
        const content = $('#prompt-content-textarea').val();
        const description = $('#prompt-description-input').val();
        const category = $('#prompt-category-input').val();
        const tagsInput = $('#prompt-tags-input').val();
        const tags = tagsInput ? tagsInput.split(',').map(tag => tag.trim()).filter(tag => tag) : [];

        const data = {
            name: this.currentPrompt,
            content: content,
            description: description,
            category: category,
            tags: tags
        };

        fetch('/update_prompt', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'success') {
                self.showSuccess('Prompt saved successfully!');
                self.hasUnsavedChanges = false;
                self.originalContent = {
                    content: content,
                    description: description,
                    category: category,
                    tags: tagsInput
                };
                
                // Update the list item to remove modified badge
                self.renderPromptList();
                
                // Update save button
                saveBtn.removeClass('btn-outline-success').addClass('btn-success')
                    .html('<i class="bi bi-check-circle"></i> Saved');
                
                setTimeout(() => {
                    saveBtn.removeClass('btn-success').addClass('btn-outline-success')
                        .html('<i class="bi bi-check-circle"></i> Save')
                        .prop('disabled', false);
                }, 2000);
            } else {
                self.showError('Failed to save prompt: ' + (data.error || 'Unknown error'));
                saveBtn.prop('disabled', false).html('<i class="bi bi-check-circle"></i> Save');
            }
        })
        .catch(error => {
            console.error('Error saving prompt:', error);
            self.showError('Failed to save prompt: ' + error.message);
            saveBtn.prop('disabled', false).html('<i class="bi bi-check-circle"></i> Save');
        });
    },

    /**
     * Revert changes to original content
     */
    revertChanges: function() {
        if (!this.currentPrompt || !this.originalContent) {
            return;
        }

        if (!this.hasUnsavedChanges) {
            this.showInfo('No changes to revert');
            return;
        }

        if (confirm('Are you sure you want to revert all changes?')) {
            $('#prompt-content-textarea').val(this.originalContent.content);
            $('#prompt-description-input').val(this.originalContent.description);
            $('#prompt-category-input').val(this.originalContent.category);
            $('#prompt-tags-input').val(this.originalContent.tags);
            
            this.hasUnsavedChanges = false;
            this.updateStats();
            this.renderPromptList();
            this.showInfo('Changes reverted');
        }
    },

    /**
     * Copy prompt content to clipboard
     */
    copyToClipboard: function() {
        const content = $('#prompt-content-textarea').val();
        
        if (!content) {
            this.showError('No content to copy');
            return;
        }

        const textarea = document.createElement('textarea');
        textarea.value = content;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        
        try {
            document.execCommand('copy');
            this.showSuccess('Copied to clipboard!');
            
            // Visual feedback on button
            const copyBtn = $('#prompt-copy-btn');
            copyBtn.removeClass('btn-outline-secondary').addClass('btn-success')
                .html('<i class="bi bi-check"></i> Copied');
            
            setTimeout(() => {
                copyBtn.removeClass('btn-success').addClass('btn-outline-secondary')
                    .html('<i class="bi bi-clipboard"></i> Copy');
            }, 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
            this.showError('Failed to copy to clipboard');
        } finally {
            document.body.removeChild(textarea);
        }
    },

    /**
     * Filter prompts based on search query
     */
    filterPrompts: function(query) {
        if (!query) {
            this.filteredPrompts = [...this.allPrompts];
        } else {
            const lowerQuery = query.toLowerCase();
            this.filteredPrompts = this.allPrompts.filter(prompt => 
                prompt.toLowerCase().includes(lowerQuery)
            );
        }
        
        this.renderPromptList();
    },

    /**
     * Mark the current prompt as having unsaved changes
     */
    markAsChanged: function() {
        if (!this.currentPrompt || !this.originalContent) {
            return;
        }

        const currentContent = {
            content: $('#prompt-content-textarea').val(),
            description: $('#prompt-description-input').val(),
            category: $('#prompt-category-input').val(),
            tags: $('#prompt-tags-input').val()
        };

        this.hasUnsavedChanges = (
            currentContent.content !== this.originalContent.content ||
            currentContent.description !== this.originalContent.description ||
            currentContent.category !== this.originalContent.category ||
            currentContent.tags !== this.originalContent.tags
        );

        // Update the list to show modified badge
        if (this.hasUnsavedChanges) {
            $(`#prompt-list-items .list-group-item[data-prompt-name="${this.currentPrompt}"] .badge`).remove();
            $(`#prompt-list-items .list-group-item[data-prompt-name="${this.currentPrompt}"] .d-flex`).append(
                '<span class="badge badge-warning">Modified</span>'
            );
        } else {
            $(`#prompt-list-items .list-group-item[data-prompt-name="${this.currentPrompt}"] .badge`).remove();
        }
    },

    /**
     * Update content statistics
     */
    updateStats: function() {
        const content = $('#prompt-content-textarea').val();
        const lines = content.split('\n').length;
        const words = content.trim() ? content.trim().split(/\s+/).length : 0;
        const chars = content.length;

        $('#prompt-char-count').text(chars.toLocaleString());
        $('#prompt-line-count').text(lines.toLocaleString());
        $('#prompt-word-count').text(words.toLocaleString());
    },

    /**
     * Show loading state
     */
    showLoading: function() {
        $('#prompt-editor-messages').html(`
            <div class="text-center">
                <div class="spinner-border text-primary" role="status">
                    <span class="sr-only">Loading...</span>
                </div>
            </div>
        `);
    },

    /**
     * Show success message
     */
    showSuccess: function(message) {
        $('#prompt-editor-messages').html(`
            <div class="alert alert-success alert-dismissible fade show" role="alert">
                <i class="bi bi-check-circle"></i> ${message}
                <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>
        `);
    },

    /**
     * Show error message
     */
    showError: function(message) {
        $('#prompt-editor-messages').html(`
            <div class="alert alert-danger alert-dismissible fade show" role="alert">
                <i class="bi bi-exclamation-circle"></i> ${message}
                <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>
        `);
    },

    /**
     * Show info message
     */
    showInfo: function(message) {
        $('#prompt-editor-messages').html(`
            <div class="alert alert-info alert-dismissible fade show" role="alert">
                <i class="bi bi-info-circle"></i> ${message}
                <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>
        `);
    },

    /**
     * Open the prompt management modal
     */
    open: function() {
        $('#prompt-management-modal').modal('show');
    }
};

// Initialize when document is ready
$(document).ready(function() {
    PromptManager.init();
});

// Export for external use
window.PromptManager = PromptManager;
