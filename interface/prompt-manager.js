/**
 * PromptManager - Handles all prompt management functionality
 * Provides methods for listing, viewing, editing, and saving prompts
 */
const PromptManager = {
    // State management
    allPrompts: [],
    allPromptsDetailed: [],  // Store prompts with metadata
    filteredPrompts: [],
    currentPrompt: null,
    originalContent: null,
    hasUnsavedChanges: false,
    showOldPrompts: false,  // Toggle for showing prompts older than 30 days
    isCreatingNew: false,  // Flag for creating new prompt mode

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
                // Store both simple list and detailed list
                self.allPrompts = data.prompts;
                
                // Use detailed prompts if available, otherwise create simple entries
                if (data.prompts_detailed) {
                    self.allPromptsDetailed = data.prompts_detailed;
                } else {
                    // Create simple entries for backward compatibility
                    self.allPromptsDetailed = data.prompts.map(name => ({
                        name: name,
                        updated_at: new Date().toISOString()
                    }));
                }
                
                // Sort by updated_at date (newest first)
                self.allPromptsDetailed.sort((a, b) => {
                    const dateA = a.updated_at ? new Date(a.updated_at) : new Date(0);
                    const dateB = b.updated_at ? new Date(b.updated_at) : new Date(0);
                    return dateB - dateA;  // Descending order (newest first)
                });
                
                // Apply initial filter
                self.applyFiltersAndRender();
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
     * Apply filters (search + age filter) and render the list
     */
    applyFiltersAndRender: function() {
        const searchQuery = $('#prompt-search-input').val();
        let filtered = [...this.allPromptsDetailed];
        
        // Apply search filter
        if (searchQuery) {
            const lowerQuery = searchQuery.toLowerCase();
            filtered = filtered.filter(prompt => 
                prompt.name.toLowerCase().includes(lowerQuery) ||
                (prompt.description && prompt.description.toLowerCase().includes(lowerQuery)) ||
                (prompt.category && prompt.category.toLowerCase().includes(lowerQuery))
            );
        }
        
        // Apply age filter (hide prompts older than 30 days unless toggled)
        if (!this.showOldPrompts) {
            const thirtyDaysAgo = new Date();
            thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
            
            filtered = filtered.filter(prompt => {
                if (!prompt.updated_at) return true;  // Keep prompts without dates
                const updateDate = new Date(prompt.updated_at);
                return updateDate >= thirtyDaysAgo;
            });
        }
        
        this.filteredPrompts = filtered.map(p => p.name);
        this.renderPromptList();
        
        // Check if we should show "Create New" option
        if (searchQuery && this.filteredPrompts.length === 0) {
            this.showCreateNewOption(searchQuery);
        }
    },

    /**
     * Render the prompt list
     */
    renderPromptList: function() {
        const itemsContainer = $('#prompt-list-items');
        const emptyState = $('#prompt-list-empty');
        
        itemsContainer.empty();
        
        // Add toggle for showing old prompts at the top
        if (!$('#old-prompts-toggle').length) {
            const toggleHtml = `
                <div id="old-prompts-toggle" class="p-2 mb-2 border-bottom">
                    <div class="custom-control custom-switch">
                        <input type="checkbox" class="custom-control-input" id="showOldPromptsSwitch" 
                            ${this.showOldPrompts ? 'checked' : ''}>
                        <label class="custom-control-label" for="showOldPromptsSwitch">
                            Show prompts older than 30 days
                        </label>
                    </div>
                </div>
            `;
            itemsContainer.before(toggleHtml);
            
            // Add event handler for toggle
            const self = this;
            $('#showOldPromptsSwitch').on('change', function() {
                self.showOldPrompts = $(this).is(':checked');
                self.applyFiltersAndRender();
            });
        }

        if (this.filteredPrompts.length === 0) {
            // Check if it's because of search with no results
            const searchQuery = $('#prompt-search-input').val();
            if (searchQuery) {
                // Show create new option instead of empty state
                this.showCreateNewOption(searchQuery);
                return;
            }
            itemsContainer.hide();
            emptyState.show();
            return;
        }

        emptyState.hide();
        itemsContainer.show();

        // Render filtered prompts with metadata
        this.filteredPrompts.forEach(promptName => {
            const promptDetail = this.allPromptsDetailed.find(p => p.name === promptName);
            const listItem = this.createPromptListItem(promptName, promptDetail);
            itemsContainer.append(listItem);
        });
    },
    
    /**
     * Show option to create a new prompt when search returns no results
     */
    showCreateNewOption: function(searchQuery) {
        const itemsContainer = $('#prompt-list-items');
        const emptyState = $('#prompt-list-empty');
        
        emptyState.hide();
        itemsContainer.show();
        
        const createNewHtml = `
            <div class="create-new-prompt-container p-3 text-center">
                <i class="bi bi-file-plus" style="font-size: 3rem; opacity: 0.5;"></i>
                <p class="mt-2 mb-3">No prompt found matching "<strong>${searchQuery}</strong>"</p>
                <button id="create-new-prompt-btn" class="btn btn-primary" data-prompt-name="${searchQuery}">
                    <i class="bi bi-plus-circle"></i> Create New Prompt
                </button>
            </div>
        `;
        
        itemsContainer.html(createNewHtml);
        
        // Add click handler for create button
        const self = this;
        $('#create-new-prompt-btn').on('click', function() {
            const promptName = $(this).data('prompt-name');
            self.startCreateNewPrompt(promptName);
        });
    },

    /**
     * Create a list item for a prompt
     */
    createPromptListItem: function(promptName, promptDetail) {
        const self = this;
        const isActive = this.currentPrompt === promptName;
        
        // Format the prompt name for display
        const displayName = promptName.replace(/_/g, ' ')
            .replace(/\b\w/g, l => l.toUpperCase());
        
        // Format date if available
        let dateInfo = '';
        if (promptDetail && promptDetail.updated_at) {
            const updateDate = new Date(promptDetail.updated_at);
            const now = new Date();
            const diffTime = Math.abs(now - updateDate);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            
            if (diffDays === 0) {
                dateInfo = 'Updated today';
            } else if (diffDays === 1) {
                dateInfo = 'Updated yesterday';
            } else if (diffDays < 7) {
                dateInfo = `Updated ${diffDays} days ago`;
            } else if (diffDays < 30) {
                const weeks = Math.floor(diffDays / 7);
                dateInfo = `Updated ${weeks} week${weeks > 1 ? 's' : ''} ago`;
            } else {
                const months = Math.floor(diffDays / 30);
                dateInfo = `Updated ${months} month${months > 1 ? 's' : ''} ago`;
            }
        }
        
        // Add category badge if available
        const categoryBadge = (promptDetail && promptDetail.category) ? 
            `<span class="badge badge-secondary mr-1">default</span>` : `<span class="badge badge-secondary mr-1">custom</span>`;
        
        const item = $(`
            <a href="#" class="list-group-item list-group-item-action ${isActive ? 'active' : ''}" data-prompt-name="${promptName}">
                <div class="d-flex justify-content-between align-items-center">
                    <div class="flex-grow-1">
                        <div class="font-weight-medium">
                            ${categoryBadge}${displayName}
                        </div>
                        </br>
                        
                        ${promptDetail && promptDetail.description ? 
                            `<small class="text-muted d-block" style="opacity: 0.8;"><i></i></small>` : ''}
                    </div>
                    <div class="text-right ml-2">
                        ${dateInfo ? `<small class="text-muted d-block">${dateInfo}</small>` : ''}
                        ${this.hasUnsavedChanges && isActive ? '<span class="badge badge-warning">Modified</span>' : ''}
                    </div>
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
            
            self.isCreatingNew = false;
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
        
        // Determine if creating new or updating
        const isNew = this.isCreatingNew;
        const url = isNew ? '/create_prompt' : '/update_prompt';
        const method = isNew ? 'POST' : 'PUT';
        const buttonText = isNew ? 'Creating...' : 'Saving...';
        
        saveBtn.prop('disabled', true).html(`<span class="spinner-border spinner-border-sm mr-1"></span> ${buttonText}`);

        fetch(url, {
            method: method,
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
                const successMsg = self.isCreatingNew ? 'Prompt created successfully!' : 'Prompt saved successfully!';
                self.showSuccess(successMsg);
                self.hasUnsavedChanges = false;
                self.originalContent = {
                    content: content,
                    description: description,
                    category: category,
                    tags: tagsInput
                };
                
                // If we just created a new prompt, update our state
                if (self.isCreatingNew) {
                    self.isCreatingNew = false;
                    // Reload prompts to include the new one
                    self.loadPrompts();
                } else {
                    // Update the list item to remove modified badge
                    self.renderPromptList();
                }
                
                // Update save button
                const buttonIcon = self.isCreatingNew ? 'bi-plus-circle' : 'bi-check-circle';
                const buttonText = self.isCreatingNew ? 'Created' : 'Saved';
                saveBtn.removeClass('btn-primary btn-outline-success').addClass('btn-success')
                    .html(`<i class="bi ${buttonIcon}"></i> ${buttonText}`);
                
                setTimeout(() => {
                    saveBtn.removeClass('btn-success').addClass('btn-outline-success')
                        .html('<i class="bi bi-check-circle"></i> Save')
                        .prop('disabled', false);
                }, 2000);
                
                // Enable revert button after creation
                if (!self.isCreatingNew) {
                    $('#prompt-revert-btn').prop('disabled', false);
                }
            } else {
                const errorMsg = self.isCreatingNew ? 'Failed to create prompt: ' : 'Failed to save prompt: ';
                self.showError(errorMsg + (data.error || 'Unknown error'));
                const buttonText = self.isCreatingNew ? '<i class="bi bi-plus-circle"></i> Create' : '<i class="bi bi-check-circle"></i> Save';
                saveBtn.prop('disabled', false).html(buttonText);
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
        let content = $('#prompt-content-textarea').val();
        
        if (!content) {
            this.showError('No content to copy');
            return;
        }

        const textarea = document.createElement('textarea');
        // If prompt content contains Mermaid/code, normalize unicode that can break renderers on paste.
        if (typeof normalizeMermaidText === 'function') {
            content = normalizeMermaidText(content);
        } else {
            content = String(content)
                .replace(/\u00A0/g, ' ')
                .replace(/\u202F/g, ' ')
                .replace(/[“”]/g, '"')
                .replace(/[‘’]/g, "'");
        }
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
        this.applyFiltersAndRender();
    },
    
    /**
     * Start creating a new prompt
     */
    startCreateNewPrompt: function(promptName) {
        const self = this;
        
        // Check for unsaved changes
        if (this.hasUnsavedChanges) {
            if (!confirm('You have unsaved changes. Do you want to discard them?')) {
                return;
            }
        }
        
        // Set creating new flag
        this.isCreatingNew = true;
        this.currentPrompt = promptName;
        this.hasUnsavedChanges = false;
        
        // Clear search and reload list
        $('#prompt-search-input').val('');
        this.applyFiltersAndRender();
        
        // Display empty form for new prompt
        this.displayNewPromptForm(promptName);
    },
    
    /**
     * Display form for creating a new prompt
     */
    displayNewPromptForm: function(promptName) {
        // Hide empty state and show form
        $('#prompt-editor-empty').hide();
        $('#prompt-editor-form').show();
        $('#prompt-editor-actions').show();

        // Update header
        const displayName = promptName.replace(/_/g, ' ')
            .replace(/\b\w/g, l => l.toUpperCase());
        $('#prompt-editor-title').html(`<i class="bi bi-file-plus"></i> Create New Prompt`);
        $('#prompt-editor-subtitle').text(promptName);

        // Clear form fields
        $('#prompt-name-input').val(promptName);
        $('#prompt-content-textarea').val('');
        $('#prompt-description-input').val('');
        $('#prompt-category-input').val('');
        $('#prompt-tags-input').val('');
        $('#prompt-created-at').text('Not yet created');
        $('#prompt-updated-at').text('Not yet created');

        // Update stats
        this.updateStats();
        
        // Clear any previous messages
        $('#prompt-editor-messages').empty();
        
        // Update save button to show "Create"
        $('#prompt-save-btn').removeClass('btn-success').addClass('btn-primary')
            .html('<i class="bi bi-plus-circle"></i> Create').prop('disabled', false);
        
        // Update revert button
        $('#prompt-revert-btn').prop('disabled', true);
        
        // Focus on content textarea
        $('#prompt-content-textarea').focus();
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
