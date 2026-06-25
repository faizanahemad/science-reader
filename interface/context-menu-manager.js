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
     * Determines whether the custom LLM context menu feature is enabled.
     *
     * Requirements:
     * - When disabled, we must NOT override the browser's default right-click menu.
     * - Default should be ON for desktop, OFF for mobile.
     * - Setting is stored in window.chatSettingsState.enable_custom_context_menu.
     *
     * @returns {boolean} True if custom context menu should be active.
     */
    isFeatureEnabled: function() {
        // If settings are loaded/persisted, honor them.
        try {
            const state = (typeof window !== 'undefined') ? window.chatSettingsState : null;
            if (state && state.enable_custom_context_menu !== undefined && state.enable_custom_context_menu !== null) {
                return !!state.enable_custom_context_menu;
            }
        } catch (e) {
            // Fall through to defaults.
        }

        // Otherwise fall back to device default: desktop ON, mobile OFF.
        try {
            if (typeof window !== 'undefined' && typeof window.isProbablyMobileDevice === 'function') {
                return !window.isProbablyMobileDevice();
            }
        } catch (e) {
            // Ignore and fall back to width heuristic.
        }
        return (typeof window !== 'undefined') ? (window.innerWidth > 768) : true;
    },
    
    /**
     * Initialize the context menu manager
     * Sets up event listeners for contextmenu events, text selection, and click-outside handling
     * Works on main chat view AND modals (doubt modal, temp LLM modal)
     *
     * Mobile strategy:
     *   On mobile, we suppress the native context menu (copy/paste toolbar) by
     *   calling preventDefault() on the 'contextmenu' event inside our managed
     *   containers.  We then show our LLM menu via the 'selectionchange'
     *   listener once the OS selection handles settle (300 ms debounce).
     *   The selectionchange approach preserves native text-selection handle
     *   behaviour while giving us full control of the menu.
     */
    init: function() {
        const self = this;
        const isMobile = typeof window.isProbablyMobileDevice === 'function'
            && window.isProbablyMobileDevice();
        
        // Listen for contextmenu (right-click) events on chat view AND modals.
        $(document).on('contextmenu', this.CONTEXT_MENU_SELECTORS, function(e) {
            // If feature disabled, allow browser default menu.
            if (!self.isFeatureEnabled()) {
                return;
            }
            if (isMobile) {
                // Suppress native Android copy/paste toolbar so only our
                // menu appears.  The selectionchange listener below will
                // show the LLM menu once the selection settles.
                e.preventDefault();
                return;
            }
            e.preventDefault();
            e.stopPropagation(); // Prevent bubbling to parent handlers
            self.handleContextMenu(e);
        });
        
        // --- Mobile: show LLM menu after native selection settles -----------
        if (isMobile) {
            var selChangeTimer = null;
            document.addEventListener('selectionchange', function() {
                if (!self.isFeatureEnabled()) return;
                if (selChangeTimer) clearTimeout(selChangeTimer);
                selChangeTimer = setTimeout(function() {
                    self._handleMobileSelectionChange();
                }, 300);
            });
        }

        // Listen for text selection completion (mouseup after selection) on chat view AND modals
        $(document).on('mouseup', this.CONTEXT_MENU_SELECTORS, function(e) {
            // If feature disabled, do nothing (keep default selection behavior).
            if (!self.isFeatureEnabled()) {
                return;
            }
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
        if (!this.isFeatureEnabled()) {
            return;
        }
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
     * Handle mobile text selection changes (called from the selectionchange
     * listener after a debounce).
     *
     * Checks whether the current selection falls inside one of our managed
     * containers.  If so, populates the context-menu state and shows the
     * menu positioned relative to the selection rectangle (via showMenu,
     * which already implements selection-aware positioning for mobile).
     *
     * If the selection is empty or outside our containers, the menu is hidden.
     */
    _handleMobileSelectionChange: function() {
        if (!this.isFeatureEnabled()) return;

        var sel = window.getSelection();
        var text = sel ? sel.toString().trim() : '';

        // If selection cleared or too short, hide menu
        if (text.length < 3) {
            this.hideMenu();
            return;
        }

        // Make sure the selection anchor is inside one of our containers
        var anchorNode = sel.anchorNode;
        if (!anchorNode) { this.hideMenu(); return; }
        var $anchor = $(anchorNode.nodeType === 3 ? anchorNode.parentNode : anchorNode);
        var selectors = this.CONTEXT_MENU_SELECTORS; // e.g. '#chatView, #doubt-chat-messages, #temp-llm-messages'
        if ($anchor.closest(selectors).length === 0) {
            // Selection is outside our managed areas — ignore
            return;
        }

        // Avoid re-showing for the exact same selection
        var currentRange = sel.rangeCount > 0 ? sel.getRangeAt(0) : null;
        if (currentRange && this.lastSelectionRange) {
            if (currentRange.toString() === this.lastSelectionRange.toString() && this.isMenuVisible) {
                return;
            }
        }
        this.lastSelectionRange = currentRange ? currentRange.cloneRange() : null;

        // Populate context-menu state
        var contextTarget = anchorNode.nodeType === 3 ? anchorNode.parentNode : anchorNode;
        var messageContext = this.getMessageContext(contextTarget);
        this.currentSelection   = text;
        this.currentMessageId   = messageContext.messageId;
        this.currentMessageText = messageContext.messageText;
        this.currentConversationId = (typeof ConversationManager !== 'undefined')
            ? ConversationManager.activeConversationId
            : null;

        this.updateMenuVisibility();
        // x/y are ignored on mobile when a selection rect exists (Fix 1)
        this.showMenu(0, 0);
    },
    
    /**
     * Handle the contextmenu event
     * Gets selection state and shows the appropriate menu
     * 
     * @param {Event} e - The contextmenu event
     */
    handleContextMenu: function(e) {
        if (!this.isFeatureEnabled()) {
            return;
        }
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
     * Show the context menu at the specified position.
     *
     * On mobile, if there is an active text selection, the menu is positioned
     * relative to the selection bounding box (below it, or above if there is
     * no room below) so it never obscures the selected text or the Android
     * selection handles.  On desktop the original cursor-position behaviour
     * is preserved.
     * 
     * @param {number} x - X coordinate (pageX), used as fallback / desktop
     * @param {number} y - Y coordinate (pageY), used as fallback / desktop
     */
    showMenu: function(x, y) {
        if (!this.isFeatureEnabled()) {
            this.hideMenu();
            return;
        }
        const $menu = $('#llm-context-menu');
        const isMobile = typeof window.isProbablyMobileDevice === 'function'
            && window.isProbablyMobileDevice();

        // On mobile: show "More..." toggle, hide collapsible items initially.
        // On desktop: hide "More..." toggle, show all items directly.
        if (isMobile) {
            $menu.find('.ctx-more-toggle').show();
            $menu.find('.ctx-more-item').hide();
            this._moreExpanded = false;
        } else {
            $menu.find('.ctx-more-toggle').hide();
            $menu.find('.ctx-more-item').show();
        }

        // Show the menu off-screen first so we can measure its actual height
        $menu.css({ left: '-9999px', top: '-9999px', display: 'block' });
        var menuWidth  = $menu.outerWidth();
        var menuHeight = $menu.outerHeight();

        // Viewport dimensions (position: fixed uses viewport coords)
        var vpW = window.innerWidth;
        var vpH = window.innerHeight;

        // On mobile, position relative to the selection rectangle
        if (isMobile) {
            var selRect = null;
            try {
                var sel = window.getSelection();
                if (sel && sel.rangeCount > 0) {
                    selRect = sel.getRangeAt(0).getBoundingClientRect();
                    // Ignore degenerate (collapsed) rects
                    if (selRect && selRect.width === 0 && selRect.height === 0) {
                        selRect = null;
                    }
                }
            } catch (_e) { /* ignore */ }

            if (selRect) {
                // selRect is already viewport-relative (perfect for position:fixed)
                var gap = 8;
                var posY = selRect.bottom + gap;
                // If menu would go off the bottom, place it above the selection
                if (posY + menuHeight > vpH - 8) {
                    posY = selRect.top - menuHeight - gap;
                }
                // Centre horizontally on the selection
                var selCenterX = (selRect.left + selRect.right) / 2;
                var posX = selCenterX - menuWidth / 2;

                // Clamp to viewport edges
                posX = Math.max(8, Math.min(posX, vpW - menuWidth - 8));
                posY = Math.max(8, posY);

                $menu.css({ left: posX + 'px', top: posY + 'px' });
                this.isMenuVisible = true;
                return;
            }
            // Fall through to default positioning if no selection rect
        }

        // --- Default (desktop) positioning: at cursor coordinates ---
        // Convert page coords to viewport coords for position:fixed
        var scrollTop = $(window).scrollTop();
        var scrollLeft = $(window).scrollLeft();
        var posX = x - scrollLeft;
        var posY = y - scrollTop;

        // Adjust if menu would go off edges
        if (posX + menuWidth > vpW - 10) posX = vpW - menuWidth - 10;
        if (posY + menuHeight > vpH - 10) posY = vpH - menuHeight - 10;
        posX = Math.max(10, posX);
        posY = Math.max(10, posY);
        
        $menu.css({ left: posX + 'px', top: posY + 'px' });
        this.isMenuVisible = true;
    },
    
    /**
     * Hide the context menu
     */
    hideMenu: function() {
        var $menu = $('#llm-context-menu');
        $menu.hide();
        // Collapse "More..." section so it's closed next time
        $menu.find('.ctx-more-item').hide();
        $menu.find('.ctx-more-toggle a[data-action="ctx-toggle-more"] i')
            .removeClass('bi-chevron-up').addClass('bi-three-dots');
        $menu.find('.ctx-more-toggle a[data-action="ctx-toggle-more"]').contents().last()
            .replaceWith(' More...');
        this._moreExpanded = false;
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
            if (action === 'ctx-toggle-more') {
                // Toggle the "More..." section
                self._toggleMoreSection();
                return; // Don't hide the menu
            }
            self.handleAction(action);
            self.hideMenu();
        });
    },
    
    /**
     * Toggle the "More..." collapsed section in the context menu.
     * On expand, also repositions the menu so it stays within the viewport.
     */
    _toggleMoreSection: function() {
        var $menu = $('#llm-context-menu');
        var $moreItems = $menu.find('.ctx-more-item');
        var $toggleLink = $menu.find('.ctx-more-toggle a[data-action="ctx-toggle-more"]');
        
        if (this._moreExpanded) {
            // Collapse: hide extra items, update label
            $moreItems.hide();
            // Also re-apply selection-required visibility
            $toggleLink.find('i').removeClass('bi-chevron-up').addClass('bi-three-dots');
            $toggleLink.contents().last().replaceWith(' More...');
            this._moreExpanded = false;
        } else {
            // Expand: show extra items (respect selection-required)
            var hasSelection = this.currentSelection && this.currentSelection.length > 0;
            $moreItems.each(function() {
                var $item = $(this);
                if ($item.hasClass('selection-required') && !hasSelection) {
                    $item.hide();
                } else {
                    $item.show();
                }
            });
            $toggleLink.find('i').removeClass('bi-three-dots').addClass('bi-chevron-up');
            $toggleLink.contents().last().replaceWith(' Less');
            this._moreExpanded = true;
        }
        // Reposition to keep menu in viewport after size change
        this._repositionMenuInViewport();
    },
    
    /**
     * Reposition the already-visible menu so it fits within the viewport.
     * Called after the "More..." section is expanded/collapsed.
     */
    _repositionMenuInViewport: function() {
        var $menu = $('#llm-context-menu');
        if (!$menu.is(':visible')) return;
        
        var menuH = $menu.outerHeight();
        var menuW = $menu.outerWidth();
        var vpW = window.innerWidth;
        var vpH = window.innerHeight;
        
        var curLeft = parseFloat($menu.css('left')) || 0;
        var curTop  = parseFloat($menu.css('top'))  || 0;
        
        // Clamp to viewport (position:fixed uses viewport coords)
        if (curLeft + menuW > vpW - 8) curLeft = vpW - menuW - 8;
        if (curTop + menuH > vpH - 8) curTop = vpH - menuH - 8;
        if (curLeft < 8) curLeft = 8;
        if (curTop < 8)  curTop = 8;
        
        $menu.css({ left: curLeft + 'px', top: curTop + 'px' });
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

            case 'explain_visual': {
                // Use full message text if selection is too short (< 3 words)
                const self = this;
                const visualText = (self.currentSelection.trim().split(/\s+/).length < 3)
                    ? self.currentMessageText
                    : self.currentSelection;
                TempLLMManager.executeAction('explain_visual', visualText, {
                    messageId: self.currentMessageId,
                    messageText: self.currentMessageText,
                    conversationId: self.currentConversationId
                }, false);
                break;
            }
                
            case 'ask-doubt':
                // Open the existing doubt modal
                this.handleAskDoubt(false); // withContext = false
                break;
                
            case 'ask-doubt-ctx':
                // Open the doubt modal with conversation context
                this.handleAskDoubt(true); // withContext = true
                break;
            
            case 'continue-doubt-in-chat':
                // Inject a doubt thread's content into the main chat as context
                this.handleContinueDoubtInChat();
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

            case 'artefacts':
                if (typeof ArtefactsManager !== 'undefined' && this.currentConversationId) {
                    ArtefactsManager.openModal(this.currentConversationId);
                } else {
                    this.showToast('Unable to open artefacts', 'warning');
                }
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
     * @param {boolean} withContext - Whether to include conversation summary and surrounding messages
     */
    handleAskDoubt: function(withContext = false) {
        if (typeof DoubtManager !== 'undefined' && this.currentConversationId && this.currentMessageId) {
            if (withContext) {
                this.showToast('Opening doubt with conversation context...', 'info');
            }
            DoubtManager.askNewDoubt(
                this.currentConversationId,
                this.currentMessageId,
                this.currentSelection || '',
                withContext
            );
        } else if (typeof DoubtManager !== 'undefined' && this.currentConversationId) {
            // If no specific message, try to use the last message
            this.showToast('Please right-click on a specific message to ask a doubt', 'info');
        } else {
            this.showToast('Unable to open doubt dialog. Please try again.', 'warning');
        }
    },
    
    /**
     * Continue a doubt thread in main chat — fetches doubts for the message,
     * shows a picker, and injects the selected thread into the main input.
     */
    handleContinueDoubtInChat: function() {
        const self = this;
        if (!this.currentConversationId || !this.currentMessageId) {
            this.showToast('Please right-click on a specific message', 'info');
            return;
        }
        // Fetch doubts for this message
        fetch(`/get_doubts/${this.currentConversationId}/${this.currentMessageId}`)
            .then(r => r.json())
            .then(data => {
                if (!data.success || !data.doubts || data.doubts.length === 0) {
                    self.showToast('No doubts found for this message', 'info');
                    return;
                }
                // If only 1 doubt thread, inject directly
                if (data.doubts.length === 1) {
                    self.injectDoubtThreadIntoChat(data.doubts[0]);
                    return;
                }
                // Multiple: show a quick picker via prompt (simple approach)
                const options = data.doubts.map((d, i) => `${i + 1}. ${d.doubt_text.substring(0, 60)}`).join('\n');
                const choice = prompt(`Select a doubt thread to inject into main chat:\n\n${options}\n\nEnter number:`);
                if (choice) {
                    const idx = parseInt(choice) - 1;
                    if (idx >= 0 && idx < data.doubts.length) {
                        self.injectDoubtThreadIntoChat(data.doubts[idx]);
                    }
                }
            })
            .catch(() => self.showToast('Failed to fetch doubts', 'error'));
    },
    
    /**
     * Flatten a doubt tree and inject its Q&A content into the main chat input
     */
    injectDoubtThreadIntoChat: function(doubtTree) {
        // Flatten the tree to get all Q&A pairs
        const pairs = [];
        function flatten(node) {
            pairs.push({ q: node.doubt_text, a: node.doubt_answer });
            if (node.children) node.children.forEach(flatten);
        }
        flatten(doubtTree);
        
        const contextBlock = pairs.map(p => `Q: ${p.q}\nA: ${p.a}`).join('\n\n');
        const injection = `[Doubt Context]\n${contextBlock}\n[/Doubt Context]\n\n`;
        
        // Prepend to main chat input
        const mainInput = $('#messageInput, #prompt-textarea').first();
        if (mainInput.length) {
            mainInput.val(injection + mainInput.val());
            mainInput.focus();
            this.showToast('Doubt thread injected into chat input', 'success');
        } else {
            this.showToast('Could not find chat input', 'warning');
        }
    },
    
    /**
     * Copy text to clipboard
     */
    copyText: function() {
        let textToCopy = this.currentSelection || this.currentMessageText;
        
        if (textToCopy) {
            // Normalize unicode that can break Mermaid/code when pasting elsewhere.
            if (typeof normalizeMermaidText === 'function') {
                textToCopy = normalizeMermaidText(textToCopy);
            } else {
                // Minimal fallback
                textToCopy = String(textToCopy)
                    .replace(/\u00A0/g, ' ')
                    .replace(/\u202F/g, ' ')
                    .replace(/[“”]/g, '"')
                    .replace(/[‘’]/g, "'");
            }
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

// Initialize when document is ready (R4: deferred — right-click unlikely in first 100ms)
deferReady(function() {
    ContextMenuManager.init();
});
