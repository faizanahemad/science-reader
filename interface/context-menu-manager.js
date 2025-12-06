/**
 * ContextMenuManager - Handles the custom LLM-assisted right-click context menu
 * 
 * This module overrides the browser's default right-click menu in the chat view
 * and modals to provide LLM-assisted actions on selected text.
 * 
 * Features:
 * - Context-aware menu items (different items shown based on text selection)
 * - Works recursively in modals (doubt modal, temp LLM modal)
 * - Integration with DoubtManager for "Ask a Doubt" functionality
 * - Temporary LLM actions (Explain, Critique, Expand, ELI5) without database persistence
 * - "with Ctx" actions that include conversation context
 * - Standard browser actions (Copy, Search Google, etc.)
 */
const ContextMenuManager = {
    // Current state
    currentSelection: '',
    currentMessageId: null,
    currentMessageText: '',
    currentConversationId: null,
    isMenuVisible: false,
    
    // Track selection state
    selectionTimeout: null,
    lastSelectionRange: null,
    
    // Selectors for areas where context menu should work
    CONTEXT_MENU_SELECTORS: '#chatView, #doubt-chat-messages, #temp-llm-messages',
    
    /**
     * Initialize the context menu manager
     * Sets up event listeners for contextmenu events, text selection, and click-outside handling
     * Works on main chat view AND modals (doubt modal, temp LLM modal)
     */
    init: function() {
        const self = this;
        
        // Listen for contextmenu (right-click) events on chat view AND modals
        $(document).on('contextmenu', this.CONTEXT_MENU_SELECTORS, function(e) {
            e.preventDefault();
            e.stopPropagation(); // Prevent bubbling to parent handlers
            self.handleContextMenu(e);
        });
        
        // Listen for text selection completion (mouseup after selection) on chat view AND modals
        $(document).on('mouseup', this.CONTEXT_MENU_SELECTORS, function(e) {
            // Don't trigger on menu clicks or button clicks
            if ($(e.target).closest('#llm-context-menu, .btn, button, a, .dropdown').length > 0) {
                return;
            }
            
            // Clear any existing timeout
            if (self.selectionTimeout) {
                clearTimeout(self.selectionTimeout);
            }
            
            // Small delay to let selection complete
            self.selectionTimeout = setTimeout(function() {
                self.handleSelectionComplete(e);
            }, 150);
        });
        
        // Hide menu when clicking outside
        $(document).on('click', function(e) {
            if (!$(e.target).closest('#llm-context-menu').length) {
                self.hideMenu();
            }
        });
        
        // Hide menu on Escape key
        $(document).on('keydown', function(e) {
            if (e.key === 'Escape') {
                self.hideMenu();
            }
        });
        
        // Hide menu on scroll (for all relevant containers)
        $(document).on('scroll', '#chatView, #doubt-chat-messages, #temp-llm-messages', function() {
            self.hideMenu();
        });
        
        // Set up menu item click handlers
        this.setupMenuItemHandlers();
        
        console.log('ContextMenuManager initialized (with modal support)');
    },
    
    /**
     * Handle text selection completion
     * Shows context menu when user finishes selecting text
     * 
     * @param {Event} e - The mouseup event
     */
    handleSelectionComplete: function(e) {
        const selection = window.getSelection();
        const selectedText = selection ? selection.toString().trim() : '';
        
        // Only show menu if there's a meaningful selection (more than just whitespace)
        if (selectedText.length < 3) {
            return;
        }
        
        // Check if this is a new/different selection
        const currentRange = selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
        if (currentRange && this.lastSelectionRange) {
            // Skip if it's the same selection as before
            if (currentRange.toString() === this.lastSelectionRange.toString() && this.isMenuVisible) {
                return;
            }
        }
        
        // Store current selection range
        this.lastSelectionRange = currentRange ? currentRange.cloneRange() : null;
        
        // Get message context
        const messageContext = this.getMessageContext(e.target);
        this.currentSelection = selectedText;
        this.currentMessageId = messageContext.messageId;
        this.currentMessageText = messageContext.messageText;
        this.currentConversationId = typeof ConversationManager !== 'undefined' 
            ? ConversationManager.activeConversationId 
            : null;
        
        // Update menu visibility and show at selection end position
        this.updateMenuVisibility();
        this.showMenu(e.pageX, e.pageY);
    },
    
    /**
     * Handle the contextmenu event
     * Gets selection state and shows the appropriate menu
     * 
     * @param {Event} e - The contextmenu event
     */
    handleContextMenu: function(e) {
        // Get current text selection
        this.currentSelection = this.getSelectedText();
        
        // Get message context (which message card the right-click is in)
        const messageContext = this.getMessageContext(e.target);
        this.currentMessageId = messageContext.messageId;
        this.currentMessageText = messageContext.messageText;
        
        // Get active conversation ID from ConversationManager
        this.currentConversationId = typeof ConversationManager !== 'undefined' 
            ? ConversationManager.activeConversationId 
            : null;
        
        // Update menu visibility based on selection state
        this.updateMenuVisibility();
        
        // Show menu at cursor position
        this.showMenu(e.pageX, e.pageY);
    },
    
    /**
     * Get the currently selected text
     * 
     * @returns {string} The selected text, trimmed
     */
    getSelectedText: function() {
        const selection = window.getSelection();
        return selection ? selection.toString().trim() : '';
    },
    
    /**
     * Get the message context (message ID and text) from the click target
     * 
     * @param {Element} target - The element that was right-clicked
     * @returns {Object} Object with messageId and messageText
     */
    getMessageContext: function(target) {
        const $target = $(target);
        const $messageCard = $target.closest('.message-card, .card');
        
        if ($messageCard.length > 0) {
            // Try to get message ID from checkbox or header
            const $checkbox = $messageCard.find('.history-message-checkbox');
            const messageId = $checkbox.attr('message-id') || 
                             $messageCard.find('.card-header').attr('message-id') || 
                             null;
            
            // Get message text
            const $textElem = $messageCard.find('.actual-card-text, .card-text');
            const messageText = $textElem.text() || '';
            
            return {
                messageId: messageId,
                messageText: messageText
            };
        }
        
        return {
            messageId: null,
            messageText: ''
        };
    },
    
    /**
     * Update menu item visibility based on whether text is selected
     * Items with class 'selection-required' are hidden when no text is selected
     */
    updateMenuVisibility: function() {
        const hasSelection = this.currentSelection.length > 0;
        const $menu = $('#llm-context-menu');
        
        if (hasSelection) {
            // Show all items
            $menu.find('.selection-required').show();
        } else {
            // Hide selection-required items
            $menu.find('.selection-required').hide();
        }
    },
    
    /**
     * Show the context menu at the specified position
     * 
     * @param {number} x - X coordinate (pageX)
     * @param {number} y - Y coordinate (pageY)
     */
    showMenu: function(x, y) {
        const $menu = $('#llm-context-menu');
        
        // Position the menu
        // Adjust position if menu would go off-screen
        const menuWidth = 220; // Approximate menu width
        const menuHeight = 350; // Approximate max menu height
        const windowWidth = $(window).width();
        const windowHeight = $(window).height();
        const scrollTop = $(window).scrollTop();
        const scrollLeft = $(window).scrollLeft();
        
        // Adjust X if menu would go off right edge
        if (x + menuWidth > windowWidth + scrollLeft) {
            x = windowWidth + scrollLeft - menuWidth - 10;
        }
        
        // Adjust Y if menu would go off bottom edge
        if (y + menuHeight > windowHeight + scrollTop) {
            y = windowHeight + scrollTop - menuHeight - 10;
        }
        
        // Ensure menu doesn't go off left or top edge
        x = Math.max(10, x);
        y = Math.max(10, y);
        
        $menu.css({
            left: x + 'px',
            top: y + 'px',
            display: 'block'
        });
        
        this.isMenuVisible = true;
    },
    
    /**
     * Hide the context menu
     */
    hideMenu: function() {
        $('#llm-context-menu').hide();
        this.isMenuVisible = false;
    },
    
    /**
     * Set up click handlers for menu items
     */
    setupMenuItemHandlers: function() {
        const self = this;
        
        // Handle menu item clicks
        $(document).on('click', '#llm-context-menu .context-menu-item a', function(e) {
            e.preventDefault();
            const action = $(this).data('action');
            self.handleAction(action);
            self.hideMenu();
        });
    },
    
    /**
     * Handle a menu action
     * 
     * @param {string} action - The action to perform
     */
    handleAction: function(action) {
        console.log('Context menu action:', action, 'Selection:', this.currentSelection.substring(0, 50));
        
        switch (action) {
            case 'explain':
            case 'critique':
            case 'expand':
            case 'eli5':
                // LLM actions that require selection
                if (this.currentSelection) {
                    TempLLMManager.executeAction(action, this.currentSelection, {
                        messageId: this.currentMessageId,
                        messageText: this.currentMessageText,
                        conversationId: this.currentConversationId
                    }, false); // withContext = false
                } else {
                    this.showToast('Please select some text first', 'warning');
                }
                break;
                
            case 'ask-doubt':
                // Open the existing doubt modal
                this.handleAskDoubt(false); // withContext = false
                break;
                
            case 'ask-doubt-ctx':
                // Open the doubt modal with conversation context
                this.handleAskDoubt(true); // withContext = true
                break;
                
            case 'ask-temp':
                // Open temporary chat modal
                TempLLMManager.openTempChatModal(this.currentSelection, {
                    messageId: this.currentMessageId,
                    messageText: this.currentMessageText,
                    conversationId: this.currentConversationId
                }, false); // withContext = false
                break;
                
            case 'ask-temp-ctx':
                // Open temporary chat modal with conversation context
                TempLLMManager.openTempChatModal(this.currentSelection, {
                    messageId: this.currentMessageId,
                    messageText: this.currentMessageText,
                    conversationId: this.currentConversationId
                }, true); // withContext = true
                break;
                
            case 'search-google':
                // Search Google for selected text
                if (this.currentSelection) {
                    const searchUrl = 'https://www.google.com/search?q=' + encodeURIComponent(this.currentSelection);
                    window.open(searchUrl, '_blank');
                }
                break;
                
            case 'lookup':
                // Lookup (could be a dictionary or definition lookup)
                if (this.currentSelection) {
                    const lookupUrl = 'https://www.google.com/search?q=define+' + encodeURIComponent(this.currentSelection);
                    window.open(lookupUrl, '_blank');
                } else {
                    this.showToast('Please select some text to look up', 'info');
                }
                break;
                
            case 'copy-text':
                // Copy selected text or all visible text
                this.copyText();
                break;
                
            case 'copy-link':
                // Copy current page link
                this.copyLink();
                break;
                
            default:
                console.warn('Unknown context menu action:', action);
        }
    },
    
    /**
     * Handle the "Ask a Doubt" action
     * Uses the existing DoubtManager to open the doubt modal
     * 
     * @param {boolean} withContext - Whether to include conversation context
     */
    handleAskDoubt: function(withContext = false) {
        if (typeof DoubtManager !== 'undefined' && this.currentConversationId && this.currentMessageId) {
            // Store context info for potential use
            if (withContext) {
                DoubtManager.withContext = true;
                DoubtManager.contextSelection = this.currentSelection;
                this.showToast('Opening doubt with conversation context...', 'info');
            } else {
                DoubtManager.withContext = false;
                DoubtManager.contextSelection = '';
            }
            DoubtManager.askNewDoubt(this.currentConversationId, this.currentMessageId);
        } else if (typeof DoubtManager !== 'undefined' && this.currentConversationId) {
            // If no specific message, try to use the last message
            this.showToast('Please right-click on a specific message to ask a doubt', 'info');
        } else {
            this.showToast('Unable to open doubt dialog. Please try again.', 'warning');
        }
    },
    
    /**
     * Copy text to clipboard
     */
    copyText: function() {
        const textToCopy = this.currentSelection || this.currentMessageText;
        
        if (textToCopy) {
            navigator.clipboard.writeText(textToCopy).then(() => {
                this.showToast('Text copied to clipboard', 'success');
            }).catch(err => {
                console.error('Failed to copy text:', err);
                this.showToast('Failed to copy text', 'error');
            });
        } else {
            this.showToast('No text to copy', 'info');
        }
    },
    
    /**
     * Copy current page link (with message ID if available)
     */
    copyLink: function() {
        let url = window.location.href;
        
        // Add message ID to URL if available
        if (this.currentMessageId && this.currentConversationId) {
            const baseUrl = url.split('?')[0].split('#')[0];
            url = `${baseUrl}?conversation=${this.currentConversationId}&message=${this.currentMessageId}`;
        }
        
        navigator.clipboard.writeText(url).then(() => {
            this.showToast('Link copied to clipboard', 'success');
        }).catch(err => {
            console.error('Failed to copy link:', err);
            this.showToast('Failed to copy link', 'error');
        });
    },
    
    /**
     * Show a toast notification
     * 
     * @param {string} message - The message to show
     * @param {string} type - The type of toast (success, error, warning, info)
     */
    showToast: function(message, type) {
        // Use existing showToast function if available
        if (typeof showToast === 'function') {
            showToast(message, type);
        } else {
            // Fallback to console
            console.log(`[${type}] ${message}`);
        }
    }
};

// Initialize when document is ready
$(document).ready(function() {
    ContextMenuManager.init();
});
